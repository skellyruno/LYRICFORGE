"""Compare larger optional downloadable models on the exact earlier split.

Audio and lyric references remain runner-local. The default model is unchanged.
"""
import argparse,json,time,gc
from pathlib import Path
from urllib.parse import urlencode,urlparse
from huggingface_hub import HfApi,snapshot_download
from faster_whisper import WhisperModel
from singing_benchmark import DATASET,request,tokens,distance
from shared_media_proof import sha,MODEL,REVISION,MODEL_SHA

def run(previous,out):
    old=json.loads(Path(previous).read_text(encoding="utf-8"))
    root=Path(out).resolve();root.mkdir(parents=True,exist_ok=True)
    private=root/"private";private.mkdir(exist_ok=True)
    cases=[]
    for row in old["cases"]:
        url="https://datasets-server.huggingface.co/rows?"+urlencode({"dataset":DATASET,"config":"pure-en","split":"test","offset":row["row"],"length":1})
        item=json.loads(request(url,2*1024*1024))["rows"][0]
        r=item["row"]
        if item["row_idx"]!=row["row"] or r["artist"]!=row["artist"] or r["license_type"]!=row["license"]:raise ValueError("Dataset row changed")
        src=r["audio"][0]["src"]
        if urlparse(src).scheme!="https":raise ValueError("Invalid source URL")
        path=private/f"{row['row']}.wav";path.write_bytes(request(src,20*1024*1024))
        if sha(path)!=row["file_sha256"]:raise ValueError("Reference audio changed")
        truth=tokens(r["text"])
        if len(truth)!=row["reference_words"]:raise ValueError("Reference length changed")
        cases.append((row,path,truth))
    report={"dataset":DATASET,"source_revision":old["revision_at_retrieval"],"models":{},"production_change":False}
    out=root/"model-comparison.json"
    def save():out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    for name,repo,rev in (("small",MODEL,REVISION),("medium","Systran/faster-whisper-medium",None)):
        rev=rev or HfApi().model_info(repo).sha
        if not rev or len(rev)!=40:raise ValueError("Invalid revision")
        folder=Path(snapshot_download(repo,revision=rev,allow_patterns=["*.json","model.bin","vocabulary.*"]))
        digest=sha(folder/"model.bin")
        if name=="small" and digest!=MODEL_SHA:raise ValueError("Reference model changed")
        model=WhisperModel(str(folder),device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,local_files_only=True)
        results={"repo":repo,"revision":rev,"model_sha256":digest,"model_bytes":(folder/"model.bin").stat().st_size,"cases":[]}
        report["models"][name]=results;save()
        for row,path,truth in cases:
            start=time.perf_counter()
            segs,_=model.transcribe(str(path),language="en",beam_size=3,best_of=1,temperature=0,word_timestamps=True,vad_filter=False,condition_on_previous_text=False)
            hyp=tokens(" ".join(w.word for seg in segs for w in (seg.words or [])))
            result={"row":row["row"],"artist":row["artist"],"split":row["split"],"reference_words":len(truth),"errors":distance(truth,hyp),"seconds":round(time.perf_counter()-start,4)}
            if name=="small" and result["errors"]!=row["variants"]["balanced"]["errors"]:raise ValueError("Small reference not reproducible")
            results["cases"].append(result);save()
        results["metrics"]={}
        for split in ("development","held_out"):
            group=[c for c in results["cases"] if c["split"]==split]
            n=sum(c["reference_words"] for c in group);err=sum(c["errors"] for c in group)
            results["metrics"][split]={"wer_percent":100*err/n,"errors":err,"reference_words":n,"seconds":sum(c["seconds"] for c in group)}
        save();del model;gc.collect()
    a,b=[report["models"][n]["metrics"] for n in ("small","medium")]
    report["medium_improvement_validated"]=b["development"]["errors"]<a["development"]["errors"] and b["held_out"]["errors"]<a["held_out"]["errors"]
    save();print(json.dumps({n:x["metrics"] for n,x in report["models"].items()}),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("previous");p.add_argument("out");a=p.parse_args();run(a.previous,a.out)
