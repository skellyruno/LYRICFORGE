"""Compare the real original and shared PyAV runtimes, including Whisper inference.

Both snapshots are taken with the exact same source media and model. The
installed candidate runs this same function using its actual frozen modules.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

MODEL = "Systran/faster-whisper-small"
REVISION = "536b0662742c02347bc0e980a01041f333bce120"
MODEL_SHA = "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"
CORE = ("avcodec-62.dll", "avdevice-62.dll", "avfilter-11.dll", "avformat-62.dll",
        "avutil-60.dll", "swresample-6.dll", "swscale-9.dll")

def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True, sort_keys=True), encoding="utf-8")

def generate(ffmpeg, narration, output):
    ffmpeg, narration, output = map(lambda x: Path(x).resolve(), (ffmpeg, narration, output))
    output.mkdir(parents=True, exist_ok=True)
    # The independent input is actual prior Kokoro narration, not a new dummy tone.
    cases = [
        ("full-narration.m4a", ["-ac","1","-ar","48000","-c:a","aac"]),
        ("asymmetric-stereo.m4a", ["-t","17.137","-af","aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=0.65*c0","-ar","44100","-c:a","aac"]),
        ("pcm24.wav", ["-t","12.513","-ac","2","-ar","44100","-c:a","pcm_s24le"]),
        ("lossless.flac", ["-t","12.513","-ac","2","-ar","44100","-c:a","flac"]),
        ("mp3.mp3", ["-t","12.513","-ac","2","-ar","44100","-c:a","libmp3lame"]),
        ("vorbis.ogg", ["-t","12.513","-ac","2","-ar","44100","-c:a","libvorbis"]),
        ("opus.opus", ["-t","12.513","-ac","2","-ar","48000","-c:a","libopus"]),
        ("adts.aac", ["-t","12.513","-ac","2","-ar","48000","-c:a","aac"]),
        ("two-audio.m4a", ["-t","12.513","-map","0:a:0","-map","0:a:0","-c:a","aac"]),
    ]
    def run(args):
        subprocess.run([str(ffmpeg),"-hide_banner","-nostdin","-loglevel","error","-y",*args],
                       check=True, timeout=180)
    for name, options in cases:
        run(["-i",str(narration),*options,str(output/name)])
    run(["-f","lavfi","-i","testsrc2=s=320x180:r=24","-i",str(narration),
         "-t","9.137","-map","0:v:0","-map","1:a:0","-c:v","libx264","-c:a","aac",str(output/"video.mp4")])
    run(["-f","lavfi","-i","testsrc2=s=320x180:r=24","-frames:v","1","-c:v","png",str(output/"image.png")])
    (output/"corrupt.wav").write_bytes(b"not a media container")
    write(output/"fixtures.json", {"source_sha256":sha(narration),
          "files":{f.name:sha(f) for f in output.iterdir() if f.is_file() and f.name!="fixtures.json"}})

def download_model(out):
    from huggingface_hub import snapshot_download
    folder=Path(snapshot_download(MODEL, revision=REVISION, local_dir=str(Path(out).resolve()),
                    allow_patterns=["*.json","model.bin","vocabulary.*"] ))
    if sha(folder/"model.bin")!=MODEL_SHA:raise ValueError("Pinned model bytes changed")
    print("Pinned Whisper Small:",MODEL_SHA, flush=True)

def loaded_core(expected):
    """Prove Python resolved the candidate's single native DLL stack."""
    import ctypes
    from ctypes import wintypes
    expected=Path(expected).resolve()
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    get=kernel.GetModuleHandleW;get.argtypes=[wintypes.LPCWSTR];get.restype=wintypes.HMODULE
    name=kernel.GetModuleFileNameW;name.argtypes=[wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD];name.restype=wintypes.DWORD
    result={}
    for dll in CORE:
        handle=get(dll)
        if not handle:raise RuntimeError("Missing loaded shared library: "+dll)
        buffer=ctypes.create_unicode_buffer(32768)
        n=name(handle,buffer,len(buffer))
        if n==0 or n>=len(buffer):raise RuntimeError("Unable to identify loaded library")
        path=Path(buffer.value).resolve()
        if path.parent!=expected or path.name.casefold()!=dll.casefold():
            raise RuntimeError("Wrong shared library resolved: "+str(path))
        result[dll]={"path":str(path),"sha256":sha(path)}
    return result

def pcm_signature(audio):
    import numpy as np
    if audio.dtype!=np.float32 or audio.ndim!=1 or not np.isfinite(audio).all():
        raise RuntimeError("Invalid decoded PCM")
    return {"samples":len(audio),"sha256":hashlib.sha256(audio.astype("<f4",copy=False).tobytes()).hexdigest()}

def snapshot(fixtures, model_dir, output, dll_root=None, *, app_model=False):
    import av
    import ctranslate2
    from faster_whisper.audio import decode_audio
    from faster_whisper import WhisperModel
    import server
    fixtures, model_dir=Path(fixtures).resolve(),Path(model_dir).resolve()
    if sha(model_dir/"model.bin")!=MODEL_SHA:raise ValueError("Wrong model")
    manifest=json.loads((fixtures/"fixtures.json").read_text())
    for name,digest in manifest["files"].items():
        if sha(fixtures/name)!=digest:raise ValueError("Wrong fixture "+name)
    report={"av_version":av.__version__,"libraries":{k:list(v) for k,v in av.library_versions.items()},
            "ctranslate2":ctranslate2.__version__,"model_sha256":MODEL_SHA,"fixture_manifest":manifest,
            "cases":{}, "complete":False}
    if dll_root:report["loaded_native"]=loaded_core(dll_root)
    write(output,report)
    # Real inference through the exact existing engine. Frozen run also tests
    # the application's real model loader, with a pinned local model.
    if app_model:
        os.environ["WHISPER_MODEL"]=str(model_dir)
        os.environ["WHISPER_DEVICE"]="cpu"
        model=server.load_model()
    else:
        model=WhisperModel(str(model_dir),device="cpu",compute_type="int8",cpu_threads=4,
                           num_workers=1,local_files_only=True)
    for name in sorted(manifest["files"]):
        path=fixtures/name
        row={}
        for key,fn in (("duration",server.media_duration),("width",server.video_stream_width)):
            try:row[key]=fn(path)
            except ValueError:row[key]=None
        if name=="corrupt.wav":
            try:decode_audio(str(path))
            except Exception:row["decode_rejected"]=True
            else:row["decode_rejected"]=False
            if not row["decode_rejected"] or row["duration"] is not None or row["width"] is not None:
                raise RuntimeError("Corrupt media accepted")
        elif name!="image.png":
            start=time.perf_counter()
            mono=decode_audio(str(path),sampling_rate=16000)
            stereo=decode_audio(str(path),sampling_rate=16000,split_stereo=True)
            row["decode_seconds"]=round(time.perf_counter()-start,5)
            row["mono"]=pcm_signature(mono)
            row["stereo"]=[pcm_signature(channel) for channel in stereo]
            # Model uses a path, not pre-injected PCM: the real Whisper decoder is exercised.
            segments,info=model.transcribe(str(path),word_timestamps=True,beam_size=3,best_of=1,
                temperature=0,language="en",vad_filter=False,condition_on_previous_text=False)
            words=[{"word":w.word,"start":float(w.start),"end":float(w.end),"probability":float(w.probability)}
                   for segment in segments for w in (segment.words or [])]
            if not words:raise RuntimeError("No recognized words in "+name)
            row["language"]=info.language
            row["words"]=words
        report["cases"][name]=row
        write(output,report)
        print(name, "words",len(row.get("words",[])), "samples",row.get("mono",{}).get("samples"), flush=True)
    report["complete"]=True
    write(output,report)

def compare_snapshots(reference,candidate,output):
    a,b=[json.loads(Path(p).read_text(encoding="utf-8-sig")) for p in (reference,candidate)]
    if not a["complete"] or not b["complete"] or a["fixture_manifest"]!=b["fixture_manifest"] or a["model_sha256"]!=b["model_sha256"]:
        raise ValueError("Incomplete or mismatched reference")
    if set(a["cases"])!=set(b["cases"]):raise ValueError("Fixture coverage differs")
    checks={}
    for name,x in a["cases"].items():
        y=b["cases"][name]
        changed=[key for key in set(x)|set(y) if key!="decode_seconds" and x.get(key)!=y.get(key)]
        # Exact words and timestamps are mandatory. Floating confidence can vary
        # by CPU scheduling, so compare it separately with a numerical tolerance.
        if "words" in changed:
            wx,wy=x.get("words",[]),y.get("words",[])
            if len(wx)==len(wy) and all(
                all(p[k]==q[k] for k in ("word","start","end")) and abs(p["probability"]-q["probability"])<=1e-6
                for p,q in zip(wx,wy)):
                changed.remove("words")
        checks[name]={"passed":not changed,"changed":changed,"reference_words":len(x.get("words",[])),
                      "candidate_words":len(y.get("words",[])),"reference_decode_seconds":x.get("decode_seconds"),
                      "candidate_decode_seconds":y.get("decode_seconds")}
    result={"reference_av":a["av_version"],"candidate_av":b["av_version"],"cases":checks,
            "passed":all(c["passed"] for c in checks.values())}
    write(output,result)
    print(json.dumps(result,indent=2),flush=True)
    if not result["passed"]:raise RuntimeError("Shared runtime decode, probe or inference parity failed")

def main(args=None, *, frozen=False):
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="mode",required=True)
    q=sub.add_parser("generate")
    for arg in ("ffmpeg","narration","output"):q.add_argument(arg)
    q=sub.add_parser("model");q.add_argument("out")
    q=sub.add_parser("snapshot")
    for arg in ("fixtures","model","output"):q.add_argument(arg)
    q.add_argument("--dll-root")
    q=sub.add_parser("compare")
    for arg in ("reference","candidate","output"):q.add_argument(arg)
    a=p.parse_args(args)
    if a.mode=="generate":generate(a.ffmpeg,a.narration,a.output)
    elif a.mode=="model":download_model(a.out)
    elif a.mode=="snapshot":snapshot(a.fixtures,a.model,a.output,a.dll_root,app_model=frozen)
    else:compare_snapshots(a.reference,a.candidate,a.output)

if __name__=="__main__":main()
