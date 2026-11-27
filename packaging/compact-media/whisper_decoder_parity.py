"""Research gate: can our existing FFmpeg replace PyAV's Whisper audio decoder?

No production imports, dependency exclusions, or model changes. Compare the
same pinned Faster Whisper engine on the original and alternative PCM.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import time
import numpy as np

MODEL_REPO = "Systran/faster-whisper-tiny.en"
MODEL_REVISION = "0d3d19a32d3338f10357c0889762bd8d64bbdeba"
MODEL_SHA256 = "1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a"
FFMPEG_SHA256 = "861fe956cca8c442eeac82e5971fff0273a166e6410e98269fefbdf6731ae117"

def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def run(exe, args):
    return subprocess.run([str(exe), *args], stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=180, check=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

def decode_ffmpeg(exe, path, sampling_rate=16000, split_stereo=False):
    """Candidate path-only audio decoding for app uploads, not a PyAV shim."""
    channels = 2 if split_stereo else 1
    result = run(exe, ["-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", str(channels), "-ar", str(sampling_rate), "-c:a",
        "pcm_s16le", "-f", "s16le", "pipe:1"])
    if not result.stdout or len(result.stdout) % (2 * channels):
        raise ValueError("Missing or incomplete PCM")
    audio = np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0
    return (audio[::2], audio[1::2]) if split_stereo else audio

def compare(a, b):
    if not len(a) or not len(b):
        raise ValueError("Empty audio")
    row = {"reference_samples": len(a), "candidate_samples": len(b),
           "exact": bool(np.array_equal(a, b)), "same_length": len(a) == len(b)}
    if len(a) == len(b):
        d = a.astype(np.float64) - b.astype(np.float64)
        err = float(np.mean(d*d))
        signal = float(np.mean(a.astype(np.float64)**2))
        row["max_abs_pcm_error_lsb"] = float(np.max(np.abs(d))*32768)
        row["snr_db"] = 120.0 if err == 0 else float(10*np.log10(max(signal, 1e-15)/err))
    return row

def words(model, pcm):
    segments, info = model.transcribe(pcm, language="en", word_timestamps=True,
        beam_size=3, best_of=1, temperature=0, vad_filter=False,
        condition_on_previous_text=False)
    result = [{"word": w.word, "start": float(w.start), "end": float(w.end)}
              for seg in segments for w in (seg.words or [])]
    if not result:
        raise ValueError("No actual recognized words")
    return result

def audit(baseline, candidate, speech, out):
    from faster_whisper.audio import decode_audio
    from faster_whisper import WhisperModel
    from huggingface_hub import snapshot_download
    baseline, candidate, speech, out = map(lambda p: Path(p).resolve(),
                                           (baseline, candidate, speech, out))
    out.mkdir(parents=True, exist_ok=True)
    assert sha(candidate) == FFMPEG_SHA256
    report = {"candidate_sha256": sha(candidate), "reference_sha256": sha(baseline),
              "packages": {n: importlib.metadata.version(n) for n in ("av","faster-whisper","ctranslate2")},
              "model": MODEL_REPO, "model_revision": MODEL_REVISION, "cases": [],
              "scope": "Synthetic Windows speech fixture; not a human-vocal or song accuracy benchmark."}
    def save():
        (out/"decoder-parity.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    save()
    # Model is temporary test data only. Pin weights and prohibit inference network access.
    model_dir = snapshot_download(MODEL_REPO, revision=MODEL_REVISION,
                                  allow_patterns=["*.json","model.bin","vocabulary.*"])
    assert sha(Path(model_dir)/"model.bin") == MODEL_SHA256
    model = WhisperModel(model_dir, device="cpu", compute_type="int8",
                         cpu_threads=2, num_workers=1, local_files_only=True)
    cases = [
        ("speech.wav", "pcm_s16le", 48000),
        ("speech-24.wav", "pcm_s24le", 44100),
        ("speech.flac", "flac", 44100),
        ("speech.mp3", "libmp3lame", 44100),
        ("speech.m4a", "aac", 48000),
        ("speech.ogg", "libvorbis", 44100),
        ("speech.opus", "libopus", 48000),
    ]
    for name, codec, rate in cases:
        path=out/name
        run(baseline, ["-v","error","-y","-i",str(speech),"-ac","2",
                       "-ar",str(rate),"-c:a",codec,str(path)])
        start=time.perf_counter()
        a=decode_audio(str(path),sampling_rate=16000)
        original_time=time.perf_counter()-start
        start=time.perf_counter()
        b=decode_ffmpeg(candidate,path)
        candidate_time=time.perf_counter()-start
        row=compare(a,b)
        row.update(name=name, reference_seconds=original_time, candidate_seconds=candidate_time)
        stereo_a=decode_audio(str(path),sampling_rate=16000,split_stereo=True)
        stereo_b=decode_ffmpeg(candidate,path,split_stereo=True)
        row["stereo"]=[compare(x,y) for x,y in zip(stereo_a,stereo_b)]
        wa,wb=words(model,a),words(model,b)
        row["reference_words"]=wa;row["candidate_words"]=wb
        row["words_equal"]=[w["word"] for w in wa]==[w["word"] for w in wb]
        row["max_timestamp_difference_seconds"]=max((abs(x[k]-y[k]) for x,y in zip(wa,wb) for k in ("start","end")), default=0.0) if row["words_equal"] else None
        row["passed"]=row["exact"] and all(x["exact"] for x in row["stereo"]) and row["words_equal"] and row["max_timestamp_difference_seconds"]<=0.02
        report["cases"].append(row);save()
        print(name, {k:v for k,v in row.items() if k not in ("reference_words","candidate_words")}, flush=True)
    bad=out/"invalid.wav";bad.write_bytes(b"not a media file")
    try:
        decode_ffmpeg(candidate,bad)
    except (subprocess.CalledProcessError,ValueError):
        report["invalid_media_rejected"]=True
    else:
        report["invalid_media_rejected"]=False
    report["passed"]=all(c["passed"] for c in report["cases"]) and report["invalid_media_rejected"]
    save()
    if not report["passed"]:
        raise RuntimeError("Decoder parity not exact; do not remove PyAV")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for arg in ("baseline","candidate","speech","out"):
        p.add_argument(arg)
    a=p.parse_args();audit(a.baseline,a.candidate,a.speech,a.out)
