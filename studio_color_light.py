"""Original educational light illustrations. Display colors are illustrative;
no spectral calibration, monitor characterization or pigment model is implied."""
from __future__ import annotations
import math
import numpy as np
from PIL import Image, ImageDraw


def unit_progress(t):
    p=float(np.clip(t,0,1));return p*p*(3-2*p)


def linear_to_srgb(a):
    a=np.clip(np.asarray(a,dtype=float),0,1)
    return np.where(a<=.0031308,a*12.92,1.055*a**(1/2.4)-.055)


def rgb_ramp(t):
    """Three staggered, independently dimmable linear-light channels."""
    return np.array([unit_progress((t-.10)/.22),unit_progress((t-.33)/.22),unit_progress((t-.56)/.22)])


def wave_bands(w,h,t,font):
    """Spatial wavelength comparison with three schematic, normalized waves.
    The 420/550/680nm examples illustrate a ratio, not a measured spectrum."""
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);f=font(max(11,round(h*.075)),False)
    colors=['#9280ff','#8ae28b','#ff8675'];wavelengths=[420,550,680];x0=.20*w;x1=.94*w
    for i,(nm,c) in enumerate(zip(wavelengths,colors)):
        y=h*(.23+i*.27);d.line((x0,y,x1,y),fill='#41565b',width=1)
        d.text((.16*w,y),f'{nm} nm',anchor='rm',font=f,fill=c)
        x=np.linspace(x0,x1,240);phase=2*np.pi*((x-x0)/(x1-x0)*(680/nm)*2.8-t*1.8)
        yy=y+np.sin(phase)*h*.085
        d.line(list(zip(x,yy)),fill=c,width=max(2,round(h*.012)),joint='curve')
        # Wavelength bracket follows the wavelength in the same spatial scale.
        span=(x1-x0)/(680/nm*2.8);start=x0+(x1-x0)*.15;yb=y+h*.113
        d.line((start,yb,start+span,yb),fill='#b1b8be',width=1)
        d.line((start,yb-4,start,yb+4),fill='#b1b8be',width=1);d.line((start+span,yb-4,start+span,yb+4),fill='#b1b8be',width=1)
    return im


def channel_mixer(w,h,t,font):
    """Three linear-light inputs routed to a combined swatch, with explicit values."""
    p=rgb_ramp(t);im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im)
    f=font(max(11,round(h*.068)),False);label=font(max(10,round(h*.055)),True)
    yvals=[.21*h,.49*h,.77*h];rgb=np.eye(3);out=np.rint(linear_to_srgb(p)*255).astype(int)
    end=(.72*w,.49*h);r=.19*h
    for i,(y,name) in enumerate(zip(yvals,('RED','GREEN','BLUE'))):
        color=('#ff8f88','#8be6a3','#93a6ff')[i];hot=tuple(np.rint(linear_to_srgb(rgb[i]*p[i])*255).astype(int).tolist())
        d.text((.02*w,y-.052*h),name,font=label,fill=color,anchor='lm')
        d.text((.02*w,y+.060*h),f'{p[i]:.2f}',font=f,fill='#d2dcd9',anchor='lm')
        d.rounded_rectangle((.16*w,y-.045*h,.43*w,y+.045*h),radius=max(2,round(h*.016)),fill='#202c32')
        if p[i]>.005:d.rounded_rectangle((.16*w,y-.045*h,.16*w+.27*w*p[i],y+.045*h),radius=max(1,round(h*.014)),fill=hot)
        pts=[(.45*w,y),(.57*w,y),(.65*w,end[1])];d.line(pts,fill='#405055',width=1,joint='curve')
        if p[i]>.005:d.line(pts,fill=hot,width=max(1,round(h*.013)),joint='curve')
    d.line((.65*w,end[1],end[0],end[1]),fill=tuple(out.tolist()) if np.any(out) else '#405055',width=max(1,round(h*.013)))
    cx,cy=end[0]+.065*w,end[1]
    d.ellipse((cx-r-6,cy-r-6,cx+r+6,cy+r+6),outline='#7a8d90',width=1)
    d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=tuple(out.tolist()),outline='#e2e8e6',width=1)
    d.text((cx,cy+r+.065*h),'COMBINED LIGHT',font=label,fill='#9eaeaf',anchor='mt')
    d.text((cx,cy+r+.13*h),' / '.join(f'{v:.1f}' for v in p),font=f,fill='#e7eae2',anchor='mt')
    return im
