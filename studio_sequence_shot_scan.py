"""Bounded temporal shot scouting; image-quality evidence, not semantics."""
from functools import lru_cache
import math
import os
from pathlib import Path
import subprocess
import numpy as np

RATE=30
STEP=15
W,H=96,54


def offsets(duration, length):
    """Scout up to four short, separated regions across the entire source."""
    end=max(0,math.floor(float(duration)*RATE)-length)
    if not end:return [0]
    return sorted({max(0,min(end,round(end*f/STEP)*STEP)) for f in (0.,.32,.65,1.)})


def _features(path,start,length,duration):
    seconds=min(max(length/RATE+2.,4.),max(0.,duration-start/RATE))
    if seconds<length/RATE-.001:return []
    args=['ffmpeg','-v','error','-nostdin','-threads','1','-ss',f'{start/RATE:.9f}','-i',path,'-t',f'{seconds:.6f}','-an','-vf',f'fps=2,scale={W}:{H},format=rgb24','-f','rawvideo','-threads','1','pipe:1']
    p=subprocess.run(args,capture_output=True,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
    count=len(p.stdout)//(W*H*3)
    if p.returncode or count==0 or count>20 or len(p.stdout)!=count*W*H*3:return []
    rgb=np.frombuffer(p.stdout,np.uint8).reshape(count,H,W,3).astype(np.float32)/255.
    g=rgb@np.array([.2126,.7152,.0722],np.float32)
    contrast=g.std(axis=(1,2));edge=np.abs(np.diff(g,axis=2)).mean(axis=(1,2))+np.abs(np.diff(g,axis=1)).mean(axis=(1,2))
    clip=((g<.025)|(g>.975)).mean(axis=(1,2))
    motion=np.abs(np.diff(g,axis=0)).mean(axis=(1,2))
    quality=.4*(1-clip)+.3*np.minimum(1,contrast/.18)+.3*np.minimum(1,edge/.15)
    # A sharp title on a mostly empty background is not a useful cinematic
    # cutaway. Assess distributed detail, not just overall contrast.
    edge_map=np.zeros_like(g)
    edge_map[:,:,1:]+=np.abs(np.diff(g,axis=2))
    edge_map[:,1:,:]+=np.abs(np.diff(g,axis=1))
    occupied=(edge_map.reshape(count,6,9,8,12).mean((2,4))>.015).mean((1,2))
    sparse=occupied<.34
    # Bright neutral pages can be legitimate reference material, so downrank
    # rather than categorically exclude. This is not text recognition.
    paper=(g.mean((1,2))>.78)&((g>.93).mean((1,2))>.42)&((rgb.max(3)-rgb.min(3)).mean((1,2))<.035)
    quality=quality-.24*sparse-.16*paper
    samples=math.ceil(length/STEP);rows=[]
    for i in range(count-samples+1):
        at=start+i*STEP
        if at+length>math.floor(duration*RATE+.0001):continue
        q=quality[i:i+samples];m=motion[i:i+samples-1]
        if (sparse[i:i+samples].mean()>.5 or q.min()<.25 or q.mean()<.35 or contrast[i:i+samples].mean()<.035 or edge[i:i+samples].mean()<.008 or (m.size and m.max()>.22)):continue
        rows.append((round(float(q.mean()),4),at))
    return rows


@lru_cache(maxsize=64)
def _cached(path,size,mtime,duration,length):
    if not math.isfinite(duration) or not 1<=duration<=24*60*60 or not 30<=length<=90:raise ValueError('Invalid shot scan range')
    candidates=[]
    for start in offsets(duration,length):
        try:candidates.extend(_features(path,start,length,duration))
        except (OSError,subprocess.TimeoutExpired):continue
    # Distinct windows, not near-duplicate frames of the same shot. Prefer the
    # best measured window, then a second temporally separated candidate.
    selected=[]
    for q,at in sorted(set(candidates),key=lambda r:(-r[0],r[1])):
        if all(abs(at-other)>=max(length,150) for _,other in selected):selected.append((q,at))
        if len(selected)>=2:break
    return tuple(selected)


def scan(path,duration,length):
    p=Path(path).resolve(strict=True);st=p.stat()
    return _cached(str(p),st.st_size,st.st_mtime_ns,float(duration),int(length))


def allocate(groups,budget=6):
    """Keep one window per source before using remaining slots for alternatives."""
    groups=[list(g) for g in groups if g]
    out=[]
    for rank in range(2):
        for group in groups:
            if rank<len(group):out.append(group[rank])
            if len(out)>=budget:return out
    return out
