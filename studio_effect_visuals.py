"""Reusable live visual models for educational audio demonstrations.

These are independent mathematical examples, not measured SKELLY plugin DSP.
Each frame derives from a numerical transfer/impulse/level response. No audio
thread or external model dependency is required.
"""
from __future__ import annotations
import math
from functools import lru_cache
import numpy as np
from PIL import Image, ImageDraw

KINDS={'Equalization','Limiter','Saturation','Delay','Reverb','Spectral ducking','Stereo width'}


def bell_response(freq, center=1000., gain=6., q=.9, rate=48000.):
    """RBJ peaking-EQ transfer evaluated at supplied frequencies."""
    a=10**(gain/40);w=2*np.pi*center/rate;alpha=np.sin(w)/(2*q);c=np.cos(w)
    z=np.exp(-2j*np.pi*np.asarray(freq)/rate)
    response=((1+alpha*a)-2*c*z+(1-alpha*a)*z*z)/((1+alpha/a)-2*c*z+(1-alpha/a)*z*z)
    return 20*np.log10(np.maximum(1e-12,np.abs(response)))


def limiter_levels(levels, ceiling=-6., release_ms=180., rate=1000):
    """Instantaneous peak limiting with exponential recovery (no lookahead)."""
    alpha=math.exp(-1000/(rate*release_ms));g=0.;rows=[]
    for level in levels:
        target=min(0.,ceiling-float(level));g=target if target<g else alpha*g+(1-alpha)*target
        rows.append((float(level),float(level)+g,-g))
    return np.asarray(rows)


def saturation(drive=3., count=256):
    """Waveshaping transfer and actual harmonic energy of a sinusoidal input."""
    x=np.sin(2*np.pi*np.arange(count)/count)*.75
    y=np.tanh(drive*x)/np.tanh(drive)
    spec=np.abs(np.fft.rfft(y))/(count/2)
    thd=float(np.sqrt(np.sum(spec[2:]**2))/max(spec[1],1e-12))
    return x,y,spec,thd


def delay_taps(delay=.25, feedback=.58, count=8):
    n=np.arange(count);return n*delay,feedback**n


@lru_cache(maxsize=8)
def reverb_impulse(rt60=1.5, rate=4000):
    """Illustrative parallel feedback-comb impulse; actual decays are computed."""
    n=round(rate*rt60*1.2);y=np.zeros(n);y[0]=.55
    for ms in (29,37,43,53):
        length=round(rate*ms/1000);gain=10**(-3*length/(rate*rt60))
        idx=np.arange(length,n,length);y[idx]+=.11*gain**np.arange(len(idx))
    return y


def render_frame(kind,t):
    from studio_live_diagrams import BG,PANEL,GRID,TEXT,MUTED,GREEN,GOLD,BLUE,text,chart,simulate_compression,RATE
    im=Image.new('RGB',(960,540),BG);d=ImageDraw.Draw(im)
    text(d,(40,25),kind.upper(),31,GREEN,True);text(d,(920,37),'ILLUSTRATIVE SIGNAL SIMULATION',12,MUTED,True,anchor='rm')
    d.rounded_rectangle((40,82,920,397),14,fill=PANEL,outline=GRID,width=2)
    text(d,(60,101),'INPUT / REFERENCE',13,BLUE,True);text(d,(285,101),'PROCESSED RESPONSE',13,GREEN,True)
    if kind in ('Spectral ducking','Stereo width'):
        from studio_editorial import technical_frame
        return technical_frame(kind,t)
    if kind=='Equalization':
        f=np.geomspace(20,20000,300);center=350*10**(.5+.45*math.sin(t*.9));gain=8*math.sin(t*.72);response=bell_response(f,center,gain)
        xy=chart(d,(100,142,680,340),-12,12,[-12,-6,0,6,12]);d.line([xy(j/299,0) for j in range(300)],fill=BLUE,width=2);d.line([xy(j/299,v) for j,v in enumerate(response)],fill=GREEN,width=3)
        for freq in (20,100,1000,10000,20000):text(d,(xy(math.log10(freq/20)/3,0)[0],350),f'{freq/1000:g}k' if freq>=1000 else str(freq),10,MUTED,anchor='mt')
        text(d,(715,150),f'{center:,.0f} Hz',24,GREEN,True);text(d,(715,181),'BAND CENTER',11,MUTED);text(d,(715,235),f'{gain:+.1f} dB',24,GOLD,True);text(d,(715,266),'BELL GAIN',11,MUTED);footer='PEAKING FILTER FREQUENCY RESPONSE / Q = 0.9'
    elif kind=='Limiter':
        levels=[v[0] for v in simulate_compression(max(2.1,min(30,t+2.1)),ratio=1)]
        data=limiter_levels(levels);index=min(len(data)-1,round(t*RATE));window=data[np.clip(np.arange(index-1500,index+1,10),0,len(data)-1)];ceiling=-6
        xy=chart(d,(100,142,680,340),-48,0,[-48,-36,-24,-12,0]);d.line((xy(0,ceiling),xy(1,ceiling)),fill=GOLD,width=2)
        for k,color in ((0,BLUE),(1,GREEN)):d.line([xy(j/max(1,len(window)-1),v[k]) for j,v in enumerate(window)],fill=color,width=3)
        text(d,(715,150),'−6 dB',25,GOLD,True);text(d,(715,181),'CEILING',11,MUTED);text(d,(715,235),f'{data[index,2]:.1f} dB',25,GREEN,True);text(d,(715,266),'REDUCTION',11,MUTED);footer='INSTANTANEOUS PEAK LIMITER / 180 ms RELEASE / NO LOOKAHEAD'
    elif kind=='Saturation':
        drive=1+4*(.5+.5*math.sin(t*.85));x,y,spec,thd=saturation(drive)
        xy=chart(d,(90,142,565,340),-1,1,[-1,-.5,0,.5,1]);
        for k,color in ((x,BLUE),(y,GREEN)):d.line([xy(j/(len(k)-1),v) for j,v in enumerate(k)],fill=color,width=3)
        text(d,(600,132),'HARMONICS',14,TEXT,True);bx=chart(d,(625,166,878,310),0,1.2,[0,.6,1.2])
        for j in range(1,10):d.line((bx((j-.5)/9,0),bx((j-.5)/9,spec[j])),fill=GREEN,width=8)
        text(d,(600,334),f'{drive:.1f}× DRIVE   /   {thd*100:.1f}% THD',16,GOLD,True);footer='TANH WAVESHAPER / BLUE = INPUT / GREEN = OUTPUT'
    else:
        duration=2.1;head=(t%duration)/duration;xy=chart(d,(100,142,680,340),0,1,[0,.25,.5,.75,1]);
        if kind=='Delay':
            times,amp=delay_taps()
            for j,(time,a) in enumerate(zip(times,amp)):
                x=time/duration;d.line((xy(x,0),xy(x,a)),fill=BLUE if j==0 else GREEN,width=7 if j==0 else 5)
            text(d,(715,150),'250 ms',25,GREEN,True);text(d,(715,181),'TAP SPACING',11,MUTED);text(d,(715,235),'58%',25,GOLD,True);text(d,(715,266),'FEEDBACK',11,MUTED);footer='FEEDBACK DELAY / EACH TAP IS THE PREVIOUS TAP × FEEDBACK'
        else:
            impulse=reverb_impulse();rate=4000;step=40;env=np.array([np.max(np.abs(impulse[j:j+step])) for j in range(0,len(impulse),step)]);env/=max(np.max(env),1e-12)
            d.line([xy(j*step/rate/duration,float(v)) for j,v in enumerate(env)],fill=GREEN,width=3)
            text(d,(715,150),'1.5 s',25,GREEN,True);text(d,(715,181),'MODEL RT60',11,MUTED);text(d,(715,235),'4',25,GOLD,True);text(d,(715,266),'COMB PATHS',11,MUTED);footer='PARALLEL FEEDBACK-COMB IMPULSE RESPONSE / MODEL DECAY'
        d.line((xy(head,0),xy(head,1)),fill=GOLD,width=2);text(d,(100,354),f'{head*duration:.2f} s',13,GOLD,True)
    text(d,(40,404),footer,12,MUTED,True)
    return im
