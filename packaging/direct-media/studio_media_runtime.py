"""Experimental explicit native FFmpeg backend; verified release still uses PyAV."""
from __future__ import annotations
from contextlib import contextmanager
from fractions import Fraction
from functools import lru_cache
import copy,json,math,os,shutil,subprocess,sys,tempfile
from pathlib import Path
import numpy as np
from studio_probe_delta import BASE_SHA,PROBE_SHA,sha,restore_probe

@lru_cache(maxsize=1)
def tools():
    if getattr(sys,"frozen",False):
        root=Path(sys._MEIPASS)/"tools"
        ffmpeg=root/"ffmpeg.exe";ffprobe=restore_probe(root)
        if sha(ffmpeg)!=BASE_SHA or sha(ffprobe)!=PROBE_SHA:raise ValueError("Wrong bundled tools")
    else:
        ffmpeg,ffprobe=shutil.which("ffmpeg"),shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:raise RuntimeError("Missing media tools")
    return str(ffmpeg),str(ffprobe)

def execute(exe,args,timeout):
    return subprocess.run([exe,*args],stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout,
        check=True,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)).stdout

@contextmanager
def local_path(source):
    if isinstance(source,(str,os.PathLike)):
        p=Path(source).resolve(strict=True)
        if not p.is_file():raise ValueError("Expected local file")
        yield p
    else:
        with tempfile.TemporaryDirectory(prefix="skelly-media-") as folder:
            p=Path(folder)/"input"
            with p.open("wb") as out:shutil.copyfileobj(source,out,length=1024*1024)
            yield p

def probe_json(path,options):
    _,probe=tools()
    try:
        raw=execute(probe,["-v","error",*options,"-of","json",str(path)],180)
        if len(raw)>32*1024*1024:raise ValueError("Excessive metadata")
        return json.loads(raw)
    except (subprocess.SubprocessError,OSError,ValueError) as exc:
        raise ValueError("Unreadable media metadata") from exc

def file_identity(path):
    p=Path(path).resolve(strict=True)
    s=p.stat()
    return (str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)

@lru_cache(maxsize=32)
def _media_info(identity):
    path=identity[0]
    value=probe_json(path,["-show_format","-show_streams"])
    if file_identity(path)!=identity:raise ValueError("Media changed during probe")
    return value

def media_info(path):
    return copy.deepcopy(_media_info(file_identity(path)))

def clear_probe_cache():
    _media_info.cache_clear()
    _aac_trim.cache_clear()

def direct_container(path):
    # These magic bytes cannot be ISO-BMFF. No extra FFprobe process is
    # needed for their audio decode; FFmpeg still validates the stream.
    with Path(path).open("rb") as f:header=f.read(12)
    return ((header[:4] in (b"RIFF",b"RF64",b"BW64") and header[8:12]==b"WAVE")
            or header[:4] in (b"fLaC",b"OggS"))

def positive(value):
    try:
        n=float(value)
        return n if math.isfinite(n) and n>0 else None
    except (ValueError,TypeError,OverflowError):return None

def media_duration(path):
    with local_path(path) as p:info=media_info(p)
    duration=positive(info.get("format",{}).get("duration"))
    if duration is not None:return duration
    values=[]
    for stream in info.get("streams",[]):
        try:n=positive(Fraction(str(stream["duration_ts"]))*Fraction(stream["time_base"]))
        except (KeyError,ValueError,TypeError,ZeroDivisionError):continue
        if n is not None:values.append(n)
    if values:return max(values)
    raise ValueError("The uploaded audio/video has no readable duration")

def video_stream_width(path):
    with local_path(path) as p:info=media_info(p)
    for stream in info.get("streams",[]):
        if stream.get("codec_type")=="video":
            try:w,h=int(stream.get("width",0)),int(stream.get("height",0))
            except (ValueError,TypeError):continue
            if w>0 and h>0:return w
    raise ValueError("Background file has no readable video/image stream")

def aac_trim(path):
    return _aac_trim(file_identity(path))

@lru_cache(maxsize=32)
def _aac_trim(identity):
    path=identity[0]
    info=probe_json(path,["-select_streams","a:0","-show_streams","-show_packets"])
    streams=info.get("streams",[])
    if len(streams)!=1 or streams[0].get("codec_name")!="aac":raise ValueError("Unexpected selected audio stream")
    packets=info.get("packets",[])
    if not packets:raise ValueError("No AAC packets")
    skip=discard=0
    for i,p in enumerate(packets):
        for side in p.get("side_data_list",[]):
            if side.get("side_data_type")!="Skip Samples":continue
            s,d=int(side.get("skip_samples",0)),int(side.get("discard_padding",0))
            if s:
                if i!=0 or skip or not 0<s<=65536:raise ValueError("Unsupported midstream AAC priming")
                skip=s
            if d:
                if i!=len(packets)-1 or discard or not 0<d<=65536:raise ValueError("Unsupported AAC discard")
                discard=d
    # PyAV 18.1.1 on FFmpeg 8.1.3 emits the complete last decoded
    # AAC frame in ISO-BMFF. FFmpeg 9 adds discard metadata to honor
    # the container edit duration. Do not impose that newer trimming law
    # on the Whisper input. This is the exact prior held-out parity mode.
    # Keep the discard validation above, but only remove initial priming.
    if file_identity(path)!=identity:raise ValueError("Media changed during AAC probe")
    return skip

def decode_audio(input_file,sampling_rate=16000,split_stereo=False):
    if not isinstance(sampling_rate,int) or not 1<=sampling_rate<=384000:raise ValueError("Invalid sampling rate")
    ffmpeg,_=tools();channels=2 if split_stereo else 1
    with local_path(input_file) as path:
        identity=file_identity(path)
        pre=[];filters=["asetpts=N/SR/TB"]
        if not direct_container(path):
            info=media_info(path)
            stream=next((s for s in info.get("streams",[]) if s.get("codec_type")=="audio"),None)
            if stream is None:raise ValueError("Media has no audio")
            names=set(info.get("format",{}).get("format_name","").split(","))
            if stream.get("codec_name")=="aac" and names.intersection({"mov","mp4","m4a","3gp","3g2","mj2"}):
                skip=aac_trim(path);pre=["-flags2","+skip_manual"]
                filters.insert(0,f"atrim=start_sample={skip}")
        try:
            raw=execute(ffmpeg,["-hide_banner","-nostdin","-v","error",*pre,"-i",str(path),"-map","0:a:0",
                "-vn","-sn","-dn","-af",",".join(filters),"-ac",str(channels),"-ar",str(sampling_rate),
                "-c:a","pcm_s16le","-f","s16le","pipe:1"],1800)
        except (subprocess.SubprocessError,OSError) as exc:raise ValueError("Audio decoding failed") from exc
        if file_identity(path)!=identity:raise ValueError("Media changed during decode")
    if not raw or len(raw)%(2*channels):raise ValueError("Invalid decoded PCM")
    audio=np.frombuffer(raw,dtype="<i2").astype(np.float32)/32768.0
    return (audio[::2],audio[1::2]) if split_stereo else audio
