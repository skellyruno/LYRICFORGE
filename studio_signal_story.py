"""Measured audio envelopes and intentional score rests for visual storytelling.
No source audio leaves the caller's local environment.
"""
import math
import numpy as np
from PIL import Image, ImageDraw


def decay_example(rate=24000):
    """A deterministic synthetic 440 Hz tone, with a designed 60 dB/s decay."""
    t = np.arange(2*rate, dtype=np.float64)/rate
    return .7*np.sin(2*np.pi*440*t)*10**(-3*t), rate


def measure_decay(samples, rate, windows=40):
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim != 1 or not 8000 <= rate <= 192000 or not 8 <= windows <= 120 or not windows <= len(x) <= 30*rate or not np.isfinite(x).all():
        raise ValueError('Invalid measured decay source')
    edges = np.linspace(0, len(x), windows+1, dtype=int)
    rms = np.array([np.sqrt(np.mean(x[a:b]**2)) for a,b in zip(edges,edges[1:])])
    ref = max(float(rms[0]), 1e-12)
    db = 20*np.log10(np.maximum(rms/ref, 1e-6))
    return [[round((a+b)/(2*rate),6), round(float(v),3)] for a,b,v in zip(edges,edges[1:],db)]


def validate_trace(points):
    if not isinstance(points,list) or not 2 <= len(points) <= 120:
        raise ValueError('Invalid trace point count')
    result = []
    for row in points:
        if not isinstance(row,(list,tuple)) or len(row)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in row):
            raise ValueError('Invalid trace point')
        t,db=map(float,row)
        if not 0 <= t <= 30 or not -120 <= db <= 24 or (result and t<=result[-1][0]):
            raise ValueError('Trace times must increase and remain bounded')
        result.append([t,db])
    return result


def draw_trace(w,h,points,progress,font,color):
    """Plot measured RMS, not invented data. Progressive reveal on a fixed axis."""
    points=validate_trace(points); im=Image.new('RGBA',(w,h)); d=ImageDraw.Draw(im)
    x0,y0,x1,y1=w*.15,h*.16,w*.95,h*.78
    f=font(max(10,round(h*.065)),False)
    top=max(0, math.ceil(max(p[1] for p in points)/20)*20); bottom=-120
    for value in range(bottom,top+1,20):
        y=y0+(top-value)/(top-bottom)*(y1-y0)
        d.line((x0,y,x1,y),fill='#34454a',width=1)
        d.text((x0-w*.025,y),str(value),font=f,anchor='rm',fill='#9caaa9')
    duration=max(.001,points[-1][0])
    for frac in (0,.25,.5,.75,1):
        x=x0+(x1-x0)*frac
        d.line((x,y0,x,y1),fill='#253339',width=1)
        d.text((x,y1+h*.055),f'{duration*frac:.1f}s',font=f,anchor='mt',fill='#9caaa9')
    p=np.asarray(points); limit=duration*min(1,max(0,progress))
    selected=p[p[:,0]<=limit]
    if len(selected) and limit<p[-1,0]:
        selected=np.vstack((selected,[limit,np.interp(limit,p[:,0],p[:,1])]))
    if len(selected):
        xx=x0+(x1-x0)*selected[:,0]/duration; yy=y0+(y1-y0)*(top-selected[:,1])/(top-bottom)
        coords=list(zip(xx,yy))
        if len(coords)>1:d.line(coords,fill=color,width=max(2,round(h*.013)),joint='curve')
        r=max(2,round(h*.018)); x,y=coords[-1];d.ellipse((x-r,y-r,x+r,y+r),fill=color)
    d.text((x0,y0-h*.035),'dB relative to initial RMS',font=f,anchor='lb',fill='#9caaa9')
    return im


def pause_gain(times,windows):
    """Raised-cosine ramps around deliberate silent intervals, absolute clock."""
    t=np.asarray(times,dtype=np.float64);gain=np.ones_like(t)
    if not np.isfinite(t).all() or len(windows)>32:raise ValueError('Invalid score clock')
    for start,end,fade in windows:
        if not all(isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x) for x in (start,end,fade)) or not 0<=start<end<=1800 or not 0<fade<=5:
            raise ValueError('Invalid intentional rest')
        edge=np.clip(np.maximum(start-t,t-end)/fade,0,1)
        gain*=.5-.5*np.cos(np.pi*edge)
    return gain
