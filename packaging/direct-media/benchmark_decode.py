"""Repeatable exact PCM benchmark vs the released direct backend and PyAV."""
import argparse, importlib.util, json, statistics, subprocess, tempfile, time
from pathlib import Path
import numpy as np
import studio_media_runtime as current
from faster_whisper.audio import decode_audio as pyav

def previous(root,folder):
    path=Path(folder)/"released_media.py"
    path.write_bytes(subprocess.check_output(["git","-C",str(root),"show",
        "c5b9e5ceccfab26f77c0f0b6e0c3926c905d3cd0:packaging/direct-media/studio_media_runtime.py"]))
    spec=importlib.util.spec_from_file_location("released_media",path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod.decode_audio

def run(root,fixtures,out):
    root,fixtures,out=[Path(x).resolve() for x in (root,fixtures,out)]
    cases=[p for p in sorted(fixtures.iterdir()) if p.suffix in {".aac",".m4a",".mp4",".flac",".mp3",".opus",".wav",".ogg"} and p.name!="corrupt.wav"]
    report={"cases":{},"passed":False,"repeats":5}
    def save():out.write_text(json.dumps(report,indent=2),encoding="utf-8")
    with tempfile.TemporaryDirectory() as td:
        old=previous(root,td)
        for p in cases:
            ref=pyav(str(p));stereo=pyav(str(p),split_stereo=True)
            timings={k:[] for k in ("pyav","released","cold","warm")}
            for i in range(5):
                # Rotate order to reduce warm OS cache bias.
                methods=[("pyav",pyav),("released",old),("cold",current.decode_audio),("warm",current.decode_audio)]
                if i%2:methods=methods[:2][::-1]+methods[2:]
                for label,fn in methods:
                    if label=="cold":current.clear_probe_cache()
                    start=time.perf_counter()
                    mono=fn(str(p));s=fn(str(p),split_stereo=True)
                    timings[label].append(time.perf_counter()-start)
                    if not np.array_equal(mono,ref) or any(not np.array_equal(a,b) for a,b in zip(stereo,s)):
                        raise RuntimeError("PCM changed: "+p.name+" "+label)
            report["cases"][p.name]={k:statistics.median(v) for k,v in timings.items()}
            save();print(p.name,report["cases"][p.name],flush=True)
    report["totals_seconds"]={k:sum(row[k] for row in report["cases"].values()) for k in ("pyav","released","cold","warm")}
    t=report["totals_seconds"]
    report["warm_improvement_percent"]=100*(1-t["warm"]/t["released"])
    report["cold_improvement_percent"]=100*(1-t["cold"]/t["released"])
    report["passed"]=bool(cases) and t["warm"]<t["released"] and t["cold"]<=t["released"]*1.05
    save();print(json.dumps(report["totals_seconds"]),flush=True)
    if not report["passed"]:raise RuntimeError("No measured aggregate decoding improvement")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("root","fixtures","out"):p.add_argument(name)
    a=p.parse_args();run(a.root,a.fixtures,a.out)
