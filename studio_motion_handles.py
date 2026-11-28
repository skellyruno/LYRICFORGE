"""Frame-exact editorial handles. Never overlap a protected listening take.
Pure planning; no media I/O. Can be used by music-video compositors as well.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class Handle:
    boundary: int
    half: int
    style: str


def smoothstep(x):
    x=max(0.,min(1.,float(x)))
    return x*x*(3.-2.*x)


def plan(spans, protected=(), styles=None, half=9):
    """spans: contiguous integer frame ranges; protected indices stay untouched.
    At most one third of either adjacent shot is used for handles.
    """
    if not isinstance(half,int) or isinstance(half,bool) or not 0<=half<=30:raise ValueError('Invalid handle length')
    if not spans or spans[0][0]!=0 or any(type(a)!=int or type(b)!=int or b<=a for a,b in spans) or any(a[1]!=b[0] for a,b in zip(spans,spans[1:])):raise ValueError('Expected contiguous integer frame spans')
    blocked=set(protected);styles=styles or {};out=[]
    for i,((a,b),(c,d)) in enumerate(zip(spans,spans[1:]),1):
        style=styles.get(i,'dissolve');h=min(half,(b-a)//3,(d-c)//3)
        if i-1 in blocked or i in blocked or style=='cut' or h<2:continue
        if style not in ('dissolve','wipe','match','depth'):raise ValueError('Unknown transition style')
        out.append(Handle(b,h,style))
    return out


def sample(handle, frame):
    """Return monotone outgoing and incoming frame positions plus eased opacity.
    Neither source reads outside its original span. Endpoints coincide with
    the surrounding edit; there is no frozen still or reverse frame order.
    """
    b,h=handle.boundary,handle.half
    if not b-h<=frame<b+h:raise ValueError('Frame outside handle')
    x=(frame-(b-h))/(2*h-1)
    return b-h+x*(h-1), b+x*(h-1), smoothstep(x)
