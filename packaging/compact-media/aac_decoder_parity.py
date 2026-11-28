"""Research only: preserve AAC edit-list priming and full decoded tail for Whisper.

The original CLI lost 261 samples versus PyAV on M4A. Do not pad with
synthetic silence or alter the production decoder. Probe packet metadata
and compare exact PCM and actual model output on independent fixtures.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from whisper_decoder_parity import (
    MODEL_REPO, MODEL_REVISION, MODEL_SHA256, FFMPEG_SHA256,
    sha, run, compare, words, decode_ffmpeg
)

def priming(probe,path):
    data=json.loads(run(probe,["-v","error","-select_streams","a:0",
        "-show_streams","-show_packets","-of","json",str(path)]).stdout)
    streams=data["streams"]
    if len(streams)!=1 or streams[0]["codec_name"]!="aac":
        raise ValueError("Not a single selected AAC stream")
    packet=data["packets"][0]
    skips=[int(s["skip_samples"]) for s in packet.get("side_data_list",[])
           if s["side_data_type"]=="Skip Samples"]
    return {"skip_samples":skips[0] if len(skips)==1 else 0,
            "first_pts":packet.get("pts"),"last_packet_duration":data["packets"][-1].get("duration"),
            "sample_rate":int(streams[0]["sample_rate"]),"packet_count":len(data["packets"])}

def alternate(exe,path,pre,filters,channels):
    audio=run(exe,["-v","error","-nostdin",*pre,"-i",str(path),"-map","0:a:0",
        "-vn","-sn","-dn",*filters,"-ac",str(channels),"-ar","16000",
        "-c:a","pcm_s16le","-f","s16le","pipe:1"]).stdout
    if not audio or len(audio)%(2*channels):raise ValueError("Invalid PCM")
    pcm=np.frombuffer(audio,dtype="<i2").astype(np.float32)/32768.0
    return [pcm] if channels==1 else [pcm[::2],pcm[1::2]]

def audit(baseline,candidate,probe,speech,out):
    from faster_whisper.audio import decode_audio
    from faster_whisper import WhisperModel
    from huggingface_hub import snapshot_download
    baseline,candidate,probe,speech,out=[Path(x).resolve() for x in (baseline,candidate,probe,speech,out)]
    out.mkdir(parents=True,exist_ok=True)
    if sha(candidate)!=FFMPEG_SHA256:raise ValueError("Wrong runtime")
    report={"candidate_sha256":sha(candidate),"cases":[],"purpose":"Research, not production dependency removal"}
    def save():
        (out/"aac-parity.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    save()
    model_dir=snapshot_download(MODEL_REPO,revision=MODEL_REVISION,allow_patterns=["*.json","model.bin","vocabulary.*"])
    if sha(Path(model_dir)/"model.bin")!=MODEL_SHA256:raise ValueError("Wrong model")
    model=WhisperModel(model_dir,device="cpu",compute_type="int8",cpu_threads=2,num_workers=1,local_files_only=True)
    cases=[("original-48-stereo",48000,2,None),("44-stereo",44100,2,None),
           ("48-mono",48000,1,None),("short-48",48000,2,3.137),
           ("short-44",44100,2,4.513)]
    for name,rate,channels,duration in cases:
        path=out/(name+".m4a")
        trim=[] if duration is None else ["-t",str(duration)]
        run(baseline,["-v","error","-y","-i",str(speech),*trim,"-ac",str(channels),
            "-ar",str(rate),"-c:a","aac",str(path)])
        meta=priming(probe,path)
        if not 0<=meta["skip_samples"]<=8192:raise ValueError("Unexpected AAC priming")
        filt=["-af",f"atrim=start_sample={meta['skip_samples']},asetpts=N/SR/TB"]
        variants={
            "default":([],[]),
            "copyts":(["-copyts"],[]),
            "reclock":([],["-af","asetpts=N/SR/TB"]),
            "ignore_editlist_trim_priming":(["-ignore_editlist","1"],filt),
            "manual_skip_trim_priming":(["-flags2","+skip_manual"],filt),
        }
        ref=decode_audio(str(path),sampling_rate=16000)
        stereo=decode_audio(str(path),sampling_rate=16000,split_stereo=True)
        expected_words=words(model,ref)
        case={"name":name,"metadata":meta,"variants":{}}
        for label,(pre,filters) in variants.items():
            try:
                mono=alternate(candidate,path,pre,filters,1)[0]
                s=alternate(candidate,path,pre,filters,2)
                row=compare(ref,mono)
                row["stereo"]=[compare(a,b) for a,b in zip(stereo,s)]
                w=words(model,mono)
                row["words_equal"]=[a["word"] for a in expected_words]==[a["word"] for a in w]
                row["timestamps_equal"]=expected_words==w
                row["passed"]=row["exact"] and all(x["exact"] for x in row["stereo"]) and row["timestamps_equal"]
            except Exception as exc:
                row={"passed":False,"error":str(exc)}
            case["variants"][label]=row
            print(name,label,row,flush=True)
        report["cases"].append(case);save()
    report["exact_all_cases"]=[label for label in variants if all(c["variants"][label]["passed"] for c in report["cases"])]
    report["passed"]=bool(report["exact_all_cases"]);save()
    if not report["passed"]:raise RuntimeError("No exact AAC variant; retain PyAV")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("baseline","candidate","probe","speech","out"):p.add_argument(name)
    a=p.parse_args();audit(a.baseline,a.candidate,a.probe,a.speech,a.out)
