"""Human singing benchmark: licensed Jam-ALT Lines, no audio/lyrics in reports."""
import argparse, hashlib, json, re, tempfile, time, urllib.request
from pathlib import Path
from urllib.parse import urlencode,urlparse
from collections import Counter
from huggingface_hub import HfApi
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
import numpy as np
from shared_media_proof import MODEL_SHA,sha

DATASET="jamendolyrics/jam-alt-lines"
LICENSES={"CC BY","CC BY-SA","CC0","CC BY 4.0","CC BY-SA 4.0"}
def request(url,limit):
    with urllib.request.urlopen(url,timeout=60) as r:
        data=r.read(limit+1)
    if len(data)>limit:raise ValueError("Dataset response too large")
    return data
def tokens(text):return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?",text.lower().replace("’","'"))
def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        next_row=[i]
        for j,y in enumerate(b,1):next_row.append(min(row[j]+1,next_row[-1]+1,row[j-1]+(x!=y)))
        row=next_row
    return row[-1]
def fixtures(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    revision=HfApi().dataset_info(DATASET).sha
    selected=[];artists=Counter();seen=set()
    # Select deterministically, not by how well the engine transcribes them.
    for offset in range(0,1000,100):
        url="https://datasets-server.huggingface.co/rows?"+urlencode({"dataset":DATASET,"config":"pure-en","split":"test","offset":offset,"length":100})
        rows=json.loads(request(url,10*1024*1024)).get("rows",[])
        if not rows:break
        for item in rows:
            r=item["row"];artist=r["artist"];song=r["song_name"]
            if r["license_type"] not in LICENSES or r["language"]!="en" or artists[artist]>=3 or len(tokens(r["text"]))<5:continue
            key=(song,tuple(r["line_indices"]))
            if key in seen:continue
            src=r["audio"][0]["src"]
            if urlparse(src).scheme!="https":raise ValueError("Non-HTTPS audio URL")
            index=len(selected);name=f"sing-{index:02d}.wav"
            (root/name).write_bytes(request(src,20*1024*1024))
            selected.append({"file":name,"sha256":sha(root/name),"artist":artist,"title":r["title"],"song":song,
                             "license":r["license_type"],"row":item["row_idx"],"reference":r["text"]})
            artists[artist]+=1;seen.add(key)
            if len(selected)>=12:break
        if len(selected)>=12:break
    if len(selected)<9 or len(artists)<3:raise ValueError("Insufficient licensed diverse singing fixtures")
    (root/"private-fixtures.json").write_text(json.dumps({"dataset":DATASET,"revision_at_retrieval":revision,"rows":selected}),encoding="utf-8")
def snapshot(root,model_dir,out):
    root=Path(root);model_dir=Path(model_dir)
    if sha(model_dir/"model.bin")!=MODEL_SHA:raise ValueError("Wrong pinned model")
    data=json.loads((root/"private-fixtures.json").read_text())
    model=WhisperModel(str(model_dir.resolve()),device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,local_files_only=True)
    report={"dataset":data["dataset"],"revision_at_retrieval":data["revision_at_retrieval"],"cases":[]}
    for row in data["rows"]:
        path=root/row["file"]
        if sha(path)!=row["sha256"]:raise ValueError("Fixture changed")
        audio=decode_audio(str(path))
        start=time.perf_counter()
        segs,_=model.transcribe(str(path),language="en",beam_size=3,best_of=1,temperature=0,word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
        words=[(w.word,float(w.start),float(w.end)) for s in segs for w in (s.words or [])]
        truth=tokens(row["reference"]);hyp=tokens(" ".join(w[0] for w in words))
        case={k:v for k,v in row.items() if k!="reference"}
        case.update(reference_words=len(truth),errors=distance(truth,hyp),recognized_words=len(hyp),
                    pcm_sha256=hashlib.sha256(np.asarray(audio,dtype="<f4").tobytes()).hexdigest(),
                    words_sha256=hashlib.sha256(json.dumps(words,ensure_ascii=False).encode()).hexdigest(),
                    seconds=round(time.perf_counter()-start,4))
        report["cases"].append(case)
        Path(out).write_text(json.dumps(report,indent=2),encoding="utf-8")
    report["wer_percent"]=100*sum(x["errors"] for x in report["cases"])/sum(x["reference_words"] for x in report["cases"])
    Path(out).write_text(json.dumps(report,indent=2),encoding="utf-8")
def compare(a,b,out):
    a,b=[json.loads(Path(x).read_text()) for x in (a,b)]
    if len(a["cases"])!=len(b["cases"]):raise ValueError("Unequal test set")
    equal=all({k:v for k,v in x.items() if k!="seconds"}=={k:v for k,v in y.items() if k!="seconds"} for x,y in zip(a["cases"],b["cases"]))
    report={"cases":len(a["cases"]),"original_wer_percent":a["wer_percent"],"candidate_wer_percent":b["wer_percent"],"identical_pcm_and_words":equal,"passed":equal}
    Path(out).write_text(json.dumps(report,indent=2));print(report)
    if not equal:raise RuntimeError("Human singing parity failed")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["fixtures","snapshot","compare"]);p.add_argument("args",nargs="+");a=p.parse_args()
    {"fixtures":fixtures,"snapshot":snapshot,"compare":compare}[a.mode](*a.args)
