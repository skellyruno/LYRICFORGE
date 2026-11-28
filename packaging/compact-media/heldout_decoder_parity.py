"""Held-out decoder parity using the default Small model and prior real Kokoro narration.

Keep PyAV installed. The compact binary alone supplies candidate metadata and
audio. FFprobe is an independent test oracle, not a new application dependency.
"""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from whisper_decoder_parity import sha, run, compare, decode_ffmpeg, FFMPEG_SHA256
from aac_decoder_parity import priming, alternate
from compact_aac_metadata import read_priming

def transcribe(model,audio):
    segs,info=model.transcribe(audio,word_timestamps=True,beam_size=3,best_of=1,
        temperature=0,language=None,hotwords=None,vad_filter=False,condition_on_previous_text=False)
    words=[{"word":w.word,"start":float(w.start),"end":float(w.end),"probability":float(w.probability)}
           for s in segs for w in (s.words or [])]
    if not words:raise ValueError("No recognized words")
    return {"language":info.language,"words":words}

def audit(baseline,candidate,oracle,narration,out):
    from faster_whisper.audio import decode_audio
    from faster_whisper import WhisperModel
    from huggingface_hub import HfApi,snapshot_download
    baseline,candidate,oracle,narration,out=map(lambda p:Path(p).resolve(),(baseline,candidate,oracle,narration,out))
    out.mkdir(parents=True,exist_ok=True)
    if sha(candidate)!=FFMPEG_SHA256:raise ValueError("Wrong compact runtime")
    model_id="Systran/faster-whisper-small"
    revision=HfApi().model_info(model_id).sha
    if not revision or len(revision)!=40:raise ValueError("Missing exact model revision")
    directory=snapshot_download(model_id,revision=revision,allow_patterns=["*.json","model.bin","vocabulary.*"])
    report={"runtime_sha256":sha(candidate),"narration_sha256":sha(narration),"model":model_id,
        "revision":revision,"model_sha256":sha(Path(directory)/"model.bin"),"cases":[],
        "scope":"Kokoro-generated narration, asymmetric stereo and video; not human singing accuracy"}
    def save(): (out/"held-out-decoder-parity.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    save()
    model=WhisperModel(directory,device="cpu",compute_type="int8",cpu_threads=4,num_workers=1,local_files_only=True)
    fixtures=[
        ("full-narration.m4a",["-ac","1","-ar","48000","-c:a","aac"]),
        ("asymmetric-stereo.m4a",["-t","17.137","-af","aformat=channel_layouts=mono,pan=stereo|c0=c0|c1=0.65*c0","-ar","44100","-c:a","aac"]),
        ("short-narration.flac",["-t","12.513","-ac","2","-ar","44100","-c:a","flac"]),
    ]
    for name,opts in fixtures:
        run(baseline,["-v","error","-y","-i",str(narration),*opts,str(out/name)])
    video=out/"narration-video.mp4"
    run(baseline,["-v","error","-y","-f","lavfi","-i","testsrc2=s=160x96:r=12",
        "-i",str(narration),"-t","9.137","-map","0:v:0","-map","1:a:0","-c:v","libx264","-c:a","aac","-ar","48000",str(video)])
    for name in [x[0] for x in fixtures]+[video.name]:
        media=out/name
        reference=decode_audio(str(media),sampling_rate=16000)
        stereo=decode_audio(str(media),sampling_rate=16000,split_stereo=True)
        start=time.perf_counter()
        if media.suffix in (".m4a",".mp4"):
            # Inspect the independent oracle before parsing, and save the
            # complete compact binary log so future failures are actionable.
            expected=priming(oracle,media)["skip_samples"]
            try:
                skip=read_priming(candidate,media,diagnostic=out/(name+".debug.log"))
            except (ValueError,RuntimeError) as exc:
                report["cases"].append({"name":name,"oracle_skip":expected,"error":str(exc),"passed":False})
                save()
                print("Metadata rejected:",name,"oracle skip:",expected,str(exc),flush=True)
                continue
            if skip!=expected:raise ValueError("Standalone AAC metadata differs from independent oracle")
            filt=["-af",f"atrim=start_sample={skip},asetpts=N/SR/TB"]
            mono=alternate(candidate,media,["-flags2","+skip_manual"],filt,1)[0]
            channels=alternate(candidate,media,["-flags2","+skip_manual"],filt,2)
        else:
            skip=None;mono=decode_ffmpeg(candidate,media);channels=decode_ffmpeg(candidate,media,split_stereo=True)
        decode_seconds=time.perf_counter()-start
        row=compare(reference,mono);row["stereo"]=[compare(a,b) for a,b in zip(stereo,channels)]
        ref=transcribe(model,reference);new=transcribe(model,mono)
        row.update(name=name,skip_samples=skip,candidate_decode_seconds=round(decode_seconds,4),
                   recognized_words=len(ref["words"]),identical_transcript_and_confidence=ref==new)
        row["passed"]=row["exact"] and all(r["exact"] for r in row["stereo"]) and ref==new
        report["cases"].append(row);save();print(row,flush=True)
    # Explicitly reject ambiguous metadata rather than silently choosing a stream.
    multiple=out/"two-audio-streams.m4a"
    run(baseline,["-v","error","-y","-i",str(narration),"-t","2","-map","0:a:0","-map","0:a:0","-c:a","aac",str(multiple)])
    try:read_priming(candidate,multiple,diagnostic=out/"two-audio-streams.debug.log")
    except ValueError:report["ambiguous_streams_rejected"]=True
    else:report["ambiguous_streams_rejected"]=False
    report["passed"]=all(c["passed"] for c in report["cases"]) and report["ambiguous_streams_rejected"]
    save()
    if not report["passed"]:raise RuntimeError("Held-out decoder parity not established")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("baseline","candidate","oracle","narration","out"):p.add_argument(name)
    a=p.parse_args();audit(a.baseline,a.candidate,a.oracle,a.narration,a.out)
