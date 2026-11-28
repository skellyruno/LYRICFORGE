"""Artist-disjoint, held-out accuracy comparison. Never publish lyric text/audio."""
import argparse,hashlib,json,time
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode,urlparse
from huggingface_hub import HfApi
from faster_whisper import WhisperModel
from singing_benchmark import DATASET,LICENSES,request,tokens,distance
from shared_media_proof import MODEL_SHA,sha

def evaluate(previous,model_dir,out):
    previous=json.loads(Path(previous).read_text())
    excluded={r["row"] for r in previous["cases"]}
    root=Path(out).resolve();root.mkdir(parents=True,exist_ok=True)
    cache=root/"private";cache.mkdir(exist_ok=True)
    rows=[];counts=Counter()
    revision=HfApi().dataset_info(DATASET).sha
    # All 12 prior lines are excluded. At most 6 fresh lines per artist.
    for offset in range(0,1200,100):
        url="https://datasets-server.huggingface.co/rows?"+urlencode({"dataset":DATASET,"config":"pure-en","split":"test","offset":offset,"length":100})
        data=json.loads(request(url,10*1024*1024))
        for item in data.get("rows",[]):
            r=item["row"];artist=r["artist"]
            if item["row_idx"] in excluded or r["license_type"] not in LICENSES or r["language"]!="en" or counts[artist]>=6 or len(tokens(r["text"]))<5:continue
            src=r["audio"][0]["src"]
            if urlparse(src).scheme!="https":raise ValueError("Unexpected audio URL")
            p=cache/f"line-{item['row_idx']}.wav";p.write_bytes(request(src,20*1024*1024))
            rows.append({"row":item["row_idx"],"artist":artist,"title":r["title"],"license":r["license_type"],"path":p,"truth":tokens(r["text"])})
            counts[artist]+=1
            if len(rows)>=24 and len(counts)>=4:break
        if len(rows)>=24 and len(counts)>=4:break
        if not data.get("rows") or offset+100>=data.get("num_rows_total",100000):break
    if len(rows)<18 or len(counts)<4:raise ValueError("Insufficient independent singing data")
    artists=sorted(counts)
    dev=set(artists[::2])
    model_dir=Path(model_dir).resolve()
    if sha(model_dir/"model.bin")!=MODEL_SHA:raise ValueError("Wrong model")
    model=WhisperModel(str(model_dir),device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,local_files_only=True)
    variants={"balanced":{"beam_size":3},"accurate":{"beam_size":5},"beam8":{"beam_size":8},
              "lyric_prompt":{"beam_size":5,"initial_prompt":"Transcribe the sung lyrics."}}
    report={"dataset":DATASET,"revision_at_retrieval":revision,"excluded_prior_rows":sorted(excluded),"cases":[]}
    path=root/"singing-accuracy-sweep.json"
    for row in rows:
        case={k:v for k,v in row.items() if k not in ("truth","path")}
        case["split"]="development" if row["artist"] in dev else "held_out"
        case["file_sha256"]=sha(row["path"]);case["reference_words"]=len(row["truth"]);case["variants"]={}
        for label,kwargs in variants.items():
            start=time.perf_counter()
            segments,_=model.transcribe(str(row["path"]),language="en",best_of=1,temperature=0,
                   word_timestamps=True,vad_filter=False,condition_on_previous_text=False,**kwargs)
            words=[w.word for segment in segments for w in (segment.words or [])]
            case["variants"][label]={"errors":distance(row["truth"],tokens(" ".join(words))),
                  "recognized_words":len(tokens(" ".join(words))),"seconds":round(time.perf_counter()-start,4)}
        report["cases"].append(case)
        path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    report["metrics"]={}
    for split in ("development","held_out"):
        cases=[x for x in report["cases"] if x["split"]==split];n=sum(x["reference_words"] for x in cases)
        if not n:raise RuntimeError("Empty independent split")
        report["metrics"][split]={k:{"wer_percent":100*sum(x["variants"][k]["errors"] for x in cases)/n,
           "reference_words":n,"errors":sum(x["variants"][k]["errors"] for x in cases),
           "seconds":sum(x["variants"][k]["seconds"] for x in cases)} for k in variants}
    m=report["metrics"]["development"];choice=min(variants,key=lambda k:m[k]["errors"])
    h=report["metrics"]["held_out"];report["development_choice"]=choice
    report["improvement_validated"]=choice!="balanced" and h[choice]["errors"]<h["balanced"]["errors"]
    report["production_change"]=False
    path.write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({"metrics":report["metrics"],"choice":choice,"improvement_validated":report["improvement_validated"]}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("previous");p.add_argument("model");p.add_argument("out");a=p.parse_args();evaluate(a.previous,a.model,a.out)
