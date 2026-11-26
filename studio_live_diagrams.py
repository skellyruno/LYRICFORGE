"""Deterministic, signal-driven instructional visualizations (not plugin DSP measurements).

Frame generation is bounded and streaming: one frame in memory, cancellation at
frame boundaries. A synthetic level envelope drives the actual compressor model.
"""
from __future__ import annotations
import math
from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

RATE = 1000
GREEN = '#a0f58c'; GOLD = '#f5b942'; BLUE = '#70a9e9'; BG = '#101615'; PANEL = '#19241e'; GRID = '#33483b'; TEXT = '#e7f0e7'; MUTED = '#a5b8aa'


def simulate_compression(seconds: float, threshold=-18., ratio=4., attack_ms=30., release_ms=200., *, rate=RATE):
    if not (0 < seconds <= 30 and -60 <= threshold <= 0 and 1 <= ratio <= 20 and 0 < attack_ms <= 500 and 0 < release_ms <= 3000 and 100 <= rate <= 8000):
        raise ValueError('Invalid compressor demonstration parameters')
    attack = math.exp(-1000/(rate*attack_ms)); release = math.exp(-1000/(rate*release_ms))
    gain = 0.; rows = []
    for i in range(max(1, round(seconds*rate))):
        t = i/rate
        # Synthetic syllable-like level, including quiet portions and transients.
        level = -32 + 25 * (0.5 + .5*math.sin(2*math.pi*t/.98-.7))**1.5 + 4*math.exp(-((t%1.96-.50)/.055)**2)
        level = min(-1.,level)
        target = -max(0.,level-threshold)*(1-1/ratio)
        a = attack if target < gain else release
        gain = a*gain+(1-a)*target
        rows.append((level,level+gain,-gain))
    return rows


def simulate_pitch(seconds: float, retune_ms=70., *, rate=RATE):
    """Illustrative cents-domain smoothing, not a pitch shifter or SkellyTune algorithm."""
    if not (0 < seconds <= 30 and 0 <= retune_ms <= 500 and 100 <= rate <= 8000):
        raise ValueError('Invalid pitch demonstration parameters')
    alpha = math.exp(-1000/(rate*retune_ms)) if retune_ms else 0.
    correction=0.; rows=[]
    for i in range(max(1,round(seconds*rate))):
        t=i/rate; note=(0,200,400,200)[int(t/1.4)%4]
        offset=28*math.sin(2*math.pi*4.8*t)+22*math.exp(-(t%1.4)/.20)-13
        raw=note+offset; target=round(raw/100)*100
        correction=alpha*correction+(1-alpha)*(target-raw)
        rows.append((raw,raw+correction,target))
    return rows


@lru_cache(maxsize=32)
def font(size,bold=False):
    for name in ([r'C:\Windows\Fonts\arialbd.ttf','DejaVuSans-Bold.ttf'] if bold else [r'C:\Windows\Fonts\arial.ttf','DejaVuSans.ttf']):
        try: return ImageFont.truetype(name,size)
        except OSError: pass
    return ImageFont.load_default(size=size)


def text(d,xy,label,size=16,color=TEXT,bold=False,anchor='la'):
    d.text(xy,label,font=font(size,bold),fill=color,anchor=anchor)


def chart(d,box,low,high,ticks,unit=''):
    x0,y0,x1,y1=box
    for tick in ticks:
        y=y1-(tick-low)/(high-low)*(y1-y0)
        d.line((x0,y,x1,y),fill=GRID,width=1)
        text(d,(x0-8,y),f'{tick:g}{unit}',11,MUTED,anchor='rm')
    for j in range(5):
        x=x0+(x1-x0)*j/4;d.line((x,y0,x,y1),fill=GRID,width=1)
    return lambda x,y:(x0+x*(x1-x0),y1-(max(low,min(high,y))-low)/(high-low)*(y1-y0))


def frame(kind,rows,index,*,threshold=-18.,ratio=4.,attack_ms=30.,release_ms=200.,retune_ms=70.):
    """960×540 artwork with bottom quarter reserved for Director subtitles."""
    im=Image.new('RGB',(960,540),BG);d=ImageDraw.Draw(im)
    is_comp=kind=='Compression';label='COMPRESSION' if is_comp else 'NOTE SELECTION' if kind=='Note selection' else 'PITCH CORRECTION'
    text(d,(40,25),label,31,GREEN,True)
    text(d,(920,37),'ILLUSTRATIVE SIGNAL SIMULATION',12,MUTED,True,anchor='rm')
    d.rounded_rectangle((40,82,920,397),14,fill=PANEL,outline=GRID,width=2)
    level,out,gain=rows[min(index,len(rows)-1)]
    # Moving history, fixed horizontal reference and live cursor.
    start=index-2*RATE; window=[rows[max(0,min(len(rows)-1,start+j*10))] for j in range(201)]
    if is_comp:
        text(d,(65,99),'LEVEL HISTORY',15,TEXT,True);text(d,(241,99),'INPUT',13,BLUE,True);text(d,(320,99),'OUTPUT',13,GREEN,True)
        xy=chart(d,(90,138,575,285),-48,0,[-48,-36,-24,-12,0],'')
        d.line((xy(0,threshold),xy(1,threshold)),fill=GOLD,width=2)
        text(d,(575,xy(1,threshold)[1]-5),f'THRESHOLD {threshold:g} dB',11,GOLD,anchor='rs')
        for k,c in ((0,BLUE),(1,GREEN)):
            d.line([xy(j/200,r[k]) for j,r in enumerate(window)],fill=c,width=3)
        text(d,(65,312),'GAIN REDUCTION',13,GOLD,True)
        gr_max=max(18,math.ceil((-threshold*(1-1/ratio))/6)*6);gx=chart(d,(90,340,575,375),0,gr_max,[0,gr_max/2,gr_max]);d.line([gx(j/200,r[2]) for j,r in enumerate(window)],fill=GOLD,width=3)
        text(d,(610,99),'TRANSFER',15,TEXT,True)
        tr=chart(d,(638,138,878,285),-48,0,[-48,-24,0]);
        d.line((tr(0,-48),tr(1,0)),fill='#64776b',width=1)
        d.line([tr(j/100,(-48+48*j/100)-max(0.,(-48+48*j/100)-threshold)*(1-1/ratio)) for j in range(101)],fill=GREEN,width=3)
        x,y=tr((max(-48,min(0,level))+48)/48,out);d.ellipse((x-6,y-6,x+6,y+6),fill=GOLD,outline=TEXT,width=1)
        text(d,(610,312),f'{gain:4.1f} dB',26,GOLD,True);text(d,(610,344),'GAIN REDUCTION',12,MUTED)
        d.rounded_rectangle((610,367,878,379),5,fill=GRID);d.rounded_rectangle((610,367,610+max(1,268*min(1,gain/gr_max)),379),5,fill=GOLD)
        text(d,(40,402),f'{ratio:g}:1 RATIO  /  {attack_ms:g} ms ATTACK  /  {release_ms:g} ms RELEASE',12,MUTED,True)
    elif kind=='Note selection':
        text(d,(65,99),'EXAMPLE SCALE: C MAJOR',15,TEXT,True)
        text(d,(890,99),'GREEN = TARGET',13,GREEN,True,anchor='ra')
        allowed={0,2,4,5,7,9,11}; input_note=int(index/RATE/.6)%12
        nearest=min(allowed,key=lambda n:min(abs(n-input_note),12-abs(n-input_note)))
        names=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        whites=[0,2,4,5,7,9,11]; width=110; left=95; top=139; bottom=330
        for i,n in enumerate(whites):
            x=left+i*width
            d.rounded_rectangle((x,top,x+width-4,bottom),6,fill=GREEN if n==nearest else '#d8e4db',outline=GRID,width=2)
            text(d,(x+width/2,bottom-24),names[n],16,'#142018',True,anchor='mm')
        for i,n in enumerate(whites[:-1]):
            if n+1 in allowed:continue
            x=left+(i+1)*width-33
            d.rounded_rectangle((x,top,x+62,top+116),4,fill=BLUE if n+1==input_note else '#16221b',outline=GRID,width=2)
            text(d,(x+31,top+93),names[n+1],12,TEXT,True,anchor='mm')
        text(d,(65,352),'INPUT: '+names[input_note],20,BLUE,True)
        text(d,(890,352),'ALLOWED TARGET: '+names[nearest],20,GREEN,True,anchor='ra')
        text(d,(40,402),'ILLUSTRATIVE KEY MASK  /  NOT THE ACTUAL PLUGIN GUI',12,MUTED,True)
    else:
        text(d,(65,99),'DETECTED PITCH',15,BLUE,True);text(d,(268,99),'CORRECTED PITCH',15,GREEN,True);text(d,(660,99),'TARGET NOTE',15,GOLD,True)
        xy=chart(d,(102,140,690,364),-100,500,[-100,0,100,200,300,400,500]);
        for k,c in ((2,GOLD),(0,BLUE),(1,GREEN)):
            d.line([xy(j/200,r[k]) for j,r in enumerate(window)],fill=c,width=2 if k==2 else 3)
        text(d,(722,145),f'{retune_ms:g} ms',32,GREEN,True);text(d,(722,185),'RETUNE',14,MUTED,True)
        text(d,(722,240),f'{out-gain:+.1f}',26,TEXT,True);text(d,(722,272),'CENTS FROM TARGET',11,MUTED,True)
        text(d,(40,402),'CONCEPTUAL RETUNE RESPONSE  /  NOT A MEASURED PLUGIN TRACE',12,MUTED,True)
    return im


def write_frames(kind: str, seconds: float, folder: Path, fps: int, check_cancel=lambda:None, *, retune_ms=70., compressor=None):
    """Use a 15 fps source (interpolated to output FPS) and bounded 960x540 frames."""
    source_fps=15
    from studio_effect_visuals import KINDS,render_frame
    if kind in KINDS:
        folder.mkdir(parents=True,exist_ok=True)
        for i in range(math.ceil(seconds*source_fps)):
            check_cancel()
            render_frame(kind,i/source_fps).save(folder/f'{i:05d}.jpg',quality=91,subsampling=0)
        return source_fps
    params=compressor or {}
    rows=simulate_compression(seconds,**params) if kind=='Compression' else simulate_pitch(seconds,retune_ms)
    folder.mkdir(parents=True,exist_ok=True)
    for i in range(math.ceil(seconds*source_fps)):
        check_cancel()
        frame(kind,rows,round(i*RATE/source_fps),retune_ms=retune_ms,**params).save(folder/f'{i:05d}.jpg',quality=91,subsampling=0)
    return source_fps
