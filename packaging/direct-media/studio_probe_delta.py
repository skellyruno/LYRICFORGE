"""Restore exactly the previously verified FFprobe from a bounded Git delta."""
from __future__ import annotations
import hashlib,os,tempfile
from pathlib import Path

BASE_SHA="861fe956cca8c442eeac82e5971fff0273a166e6410e98269fefbdf6731ae117"
PROBE_SHA="f04d1654ac6c2016b1654c8634cdaf39fd367b919c417b38f4d9a9913900312c"
BASE_SIZE=44690432
PROBE_SIZE=44490240
MAX_DELTA=5*1024*1024

def sha(path):
    with Path(path).open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def apply_delta(base,delta,output):
    i=written=0
    def byte():
        nonlocal i
        if i>=len(delta):raise ValueError("Truncated delta")
        v=delta[i];i+=1;return v
    def varint():
        value=0
        for shift in range(0,35,7):
            n=byte();value|=(n&127)<<shift
            if not n&128:return value
        raise ValueError("Oversized delta header")
    if varint()!=len(base) or varint()!=PROBE_SIZE:raise ValueError("Wrong delta bounds")
    while i<len(delta):
        cmd=byte()
        if cmd&128:
            offset=count=0
            for k in range(4):
                if cmd&(1<<k):offset|=byte()<<(8*k)
            for k in range(3):
                if cmd&(16<<k):count|=byte()<<(8*k)
            count=count or 65536
            if offset+count>len(base) or written+count>PROBE_SIZE:raise ValueError("Copy outside delta bounds")
            output.write(memoryview(base)[offset:offset+count])
        else:
            count=cmd
            if not count or i+count>len(delta) or written+count>PROBE_SIZE:raise ValueError("Invalid literal")
            output.write(delta[i:i+count]);i+=count
        written+=count
    if written!=PROBE_SIZE:raise ValueError("Incomplete target")

def restore_probe(tools):
    root=Path(tools).resolve()
    base,patch,target=(root/n for n in ("ffmpeg.exe","ffprobe.delta","ffprobe.exe"))
    if target.is_file() and target.stat().st_size==PROBE_SIZE and sha(target)==PROBE_SHA:return target
    if base.stat().st_size!=BASE_SIZE or sha(base)!=BASE_SHA:raise ValueError("Wrong FFmpeg base")
    if not 0<patch.stat().st_size<=MAX_DELTA:raise ValueError("Wrong delta size")
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=root,prefix=".probe-",suffix=".tmp",delete=False) as f:
            tmp=Path(f.name);apply_delta(base.read_bytes(),patch.read_bytes(),f);f.flush();os.fsync(f.fileno())
        if tmp.stat().st_size!=PROBE_SIZE or sha(tmp)!=PROBE_SHA:raise ValueError("FFprobe checksum mismatch")
        try:tmp.replace(target)
        except OSError:
            if not target.is_file() or sha(target)!=PROBE_SHA:raise
        return target
    finally:
        if tmp:tmp.unlink(missing_ok=True)
