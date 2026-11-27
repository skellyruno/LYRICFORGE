"""Bounded analytic ray tracing for original editorial sculptures.
Sphere intersections, finite-area environment approximations, reflected scene rays,
Snell refraction through a solid dielectric and Beer-Lambert absorption.
Not a full global-illumination renderer. Coordinates and colors are artistic.
"""
from __future__ import annotations
import math
import numpy as np
from PIL import Image, ImageDraw


def unit(a):
    return a / np.maximum(1e-9, np.linalg.norm(a, axis=-1, keepdims=True))


def hit_sphere(o,d,c,r):
    q=o-np.asarray(c); b=np.sum(q*d,axis=-1); disc=b*b-np.sum(q*q,axis=-1)+r*r
    root=np.sqrt(np.maximum(0,disc)); a=-b-root; z=-b+root
    return np.where((disc>=0)&(a>1e-4),a,np.where((disc>=0)&(z>1e-4),z,np.inf))


def reflect(d,n):return d-2*np.sum(d*n,axis=-1,keepdims=True)*n


def refract(d,n,eta):
    cos=-np.sum(d*n,axis=-1,keepdims=True); k=1-eta*eta*(1-cos*cos)
    return unit(np.where(k>=0,eta*d+(eta*cos-np.sqrt(np.maximum(k,0)))*n,reflect(d,n))), k[...,0]>=0


def environment(d):
    y=d[...,1:2];base=np.array([.025,.041,.058])+np.maximum(y,0)*np.array([.07,.095,.12]);
    for vec,col,width in [([-.65,.65,-.3],[2.8,2.2,1.35],38),([.7,.38,.5],[.4,1.5,2.9],24),([0,.95,.1],[1.7,1.8,1.6],15)]:
        p=np.maximum(0,np.sum(d*unit(np.array(vec)),axis=-1,keepdims=True));base+=p**width*np.asarray(col)
    return base


def background(o,d):
    dy=d[...,1]; s=(-.83-o[...,1])/np.where(np.abs(dy)>1e-6,dy,1e-6);valid=(dy<-.001)&(s>0);p=o+d*np.where(valid,s,0)[...,None];x,z=p[...,0],p[...,2]
    # Distance-filtered radial engraving: avoid subpixel grain and horizon aliasing.
    radius=np.sqrt(x*x+z*z); phi=np.arctan2(z,x)
    fade=np.exp(-np.maximum(s,0)/18); grain=.5+.5*np.sin(x*24+np.sin(z*8)*.35)
    rings=sum(np.exp(-((radius-r)/.024)**2) for r in (1.10,1.43,1.82))
    marks=np.exp(-((radius-1.64)/.13)**8)*np.exp(-(np.sin(6*phi)/.055)**2)
    tint=np.array([.032,.045,.055]); shadow=1-.55*np.exp(-(x*x+(z+.07)**2)/.74)
    floor=(tint*(.93+.07*grain[...,None]*fade[...,None])+ (rings*.028+marks*.075)[...,None]*np.array([1,.72,.33]))*shadow[...,None]
    floor+=environment(reflect(d,np.broadcast_to([0.,1.,0.],d.shape)))*.09
    sky=environment(d)*.48;blend=np.where(valid,np.clip(fade,0,1),0)[...,None]
    return sky*(1-blend)+floor*blend


def render(w,h,t,*,glass=True,angle=0.):
    if not 16<=w<=1920 or not 16<=h<=1080 or not math.isfinite(t) or not math.isfinite(angle):raise ValueError('Invalid optical frame')
    # Render at bounded internal resolution; temporal motion remains full-rate.
    sw=min(w,380);sh=max(16,round(h*sw/w));sh=min(sh,250); a=.37*math.sin(t*.24)+angle
    eye=np.array([3.9*math.sin(a),1.05,3.9*math.cos(a)]);target=np.array([0.,-.03,0.]);f=unit(target-eye);right=unit(np.cross(f,[0,1,0]));up=np.cross(right,f)
    yy,xx=np.mgrid[0:sh,0:sw];u=(xx+.5-sw/2)/sh;v=(sh/2-yy-.5)/sh;d=unit(f+u[...,None]*right*.86+v[...,None]*up*.86);o=np.broadcast_to(eye,d.shape)
    c=np.array([0.,0.,0.]);r=.84;dist=hit_sphere(o,d,c,r);mask=np.isfinite(dist)
    # Evaluate secondary rays only on the intersected surface. This is much
    # cheaper than shading the entire background for every secondary bounce.
    rgb=background(o,d);p=o[mask]+d[mask]*dist[mask,None];normal=unit(p-c);incident=d[mask];re=reflect(incident,normal)
    reflection=background(p+normal*.002,re)
    cos=np.clip(-np.sum(normal*incident,axis=-1),0,1);fresnel=.035+.965*(1-cos)**5
    if glass:
        inside,_=refract(incident,normal,1/1.46);entry=p-normal*.002;length=hit_sphere(entry,inside,c,r);length=np.where(np.isfinite(length),length,0);exitp=entry+inside*length[...,None];exitn=unit(exitp-c);out,transmits=refract(inside,-exitn,1.46)
        transmitted=background(exitp+exitn*.002,out)*np.exp(-length[...,None]*np.array([.16,.045,.018]));fresnel=np.where(transmits,fresnel,1.);surface=reflection*fresnel[...,None]+transmitted*(1-fresnel[...,None]);surface+=np.maximum(0,np.sum(normal*unit(np.array([-.6,.7,.5])),axis=-1,keepdims=True))**24*np.array([.45,.33,.18])
    else:
        band=.94+.06*np.sin(42*normal[...,1]+3*np.sin(normal[...,0]*9));surface=reflection*np.array([.98,.72,.34])*band[...,None]+.022
    rgb[mask]=surface
    # Orbiting metallic markers: separate ray intersections, depth ordering,
    # and one reflected floor/environment ray per visible surface.
    closest=dist.copy()
    for j in range(3):
        phase=t*.32+j*2*math.pi/3;center=np.array([1.45*math.cos(phase),-.54+.1*math.sin(phase),1.45*math.sin(phase)])
        sd=hit_sphere(o,d,center,.115);visible=sd<closest
        if not visible.any():continue
        point=o[visible]+d[visible]*sd[visible,None];n=unit(point-center);ray=reflect(d[visible],n);v=background(point+n*.002,ray)
        rgb[visible]=v*np.array([1.,.72,.30])+.018;closest=np.minimum(closest,sd)
    # ACES-like bounded exposure and sRGB transfer.
    rgb=np.maximum(rgb,0);rgb=np.clip((rgb*(2.51*rgb+.03))/(rgb*(2.43*rgb+.59)+.14),0,1);rgb=np.where(rgb<=.0031308,12.92*rgb,1.055*rgb**(1/2.4)-.055)
    # Feather the image into the surrounding editorial composition.
    edge=np.minimum(np.minimum((xx+.5)/sw,(sw-xx-.5)/sw),np.minimum((yy+.5)/sh,(sh-yy-.5)/sh));alpha=np.clip(edge/.13,0,1);alpha=alpha*alpha*(3-2*alpha)
    rgba=np.concatenate([rgb,alpha[...,None]],axis=-1)
    return Image.fromarray(np.uint8(np.clip(rgba*255+.5,0,255))).resize((w,h),Image.Resampling.LANCZOS)


def orbit(w,h,t,font):
    """Schematic periodic motion with a continuous phase clock."""
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);cx=w*.50;cy=h*.50;rad=min(h*.46,w*.29);phase=t*math.pi/3
    for j in range(3):
        rr=rad*(.53+.23*j);d.ellipse((cx-rr,cy-rr,cx+rr,cy+rr),outline='#40585c',width=1)
        for k in range(12):
            a=k*math.pi/6;x=cx+rr*math.cos(a);y=cy+rr*math.sin(a);d.ellipse((x-1,y-1,x+1,y+1),fill='#78908c')
        a=phase*(j+1)+j*1.2;coords=[(cx+rr*math.cos(a-q),cy+rr*math.sin(a-q)) for q in np.linspace(.85,0,42)];d.line(coords,fill=['#e9cd83','#7ed7c2','#7fa6de'][j],width=max(2,h//100));x,y=coords[-1];sz=max(3,h//40);d.ellipse((x-sz,y-sz,x+sz,y+sz),fill=['#e9cd83','#7ed7c2','#7fa6de'][j])
    d.ellipse((cx-3,cy-3,cx+3,cy+3),fill='#e9cd83');return im


def timeline(w,h,t,font):
    """24 and 60 Hz sampling of the same continuous trajectory, one-second window."""
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);f=font(max(12,round(h*.08)),False);x0=w*.18;x1=w*.95
    for row,n in enumerate((24,60)):
        y=h*(.33+.42*row);amp=h*.115;xs=np.linspace(0,1,240);ys=np.sin(2*np.pi*(xs-t*.17));d.line([(x0+(x1-x0)*x,y-amp*z) for x,z in zip(xs,ys)],fill='#3b5e61',width=1)
        for x in np.arange(n)/n:
            X=x0+(x1-x0)*x;Y=y-amp*math.sin(2*math.pi*(x-t*.17));d.line((X,y,X,Y),fill='#293c42');r=max(1.4,h*.009);d.ellipse((X-r,Y-r,X+r,Y+r),fill='#efce77' if row==0 else '#7ed7c2')
        d.text((w*.035,y),f'{n} fps',font=f,fill='#f2eee3',anchor='lm')
    return im


def trajectory(w,h,t,font):
    """A bounded Lissajous trajectory from two oscillations, with a moving trail."""
    im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im);cx=w*.5;cy=h*.5;rx=w*.39;ry=h*.40
    for x in np.linspace(-1,1,9):d.line((cx+x*rx,cy-ry,cx+x*rx,cy+ry),fill='#23353a',width=1)
    for y in np.linspace(-1,1,5):d.line((cx-rx,cy+y*ry,cx+rx,cy+y*ry),fill='#23353a',width=1)
    phase=t*.72; q=np.linspace(phase-2*math.pi,phase,360);x=cx+rx*np.sin(2*q);y=cy-ry*np.sin(3*q+.6)
    for i in range(1,len(q)):
        a=i/len(q);color=(int(33+197*a),int(65+140*a),int(79+50*a),int(55+200*a));d.line((x[i-1],y[i-1],x[i],y[i]),fill=color,width=max(1,int(h*.011)))
    r=max(4,h*.023);d.ellipse((x[-1]-r,y[-1]-r,x[-1]+r,y[-1]+r),fill='#f2d381')
    return im
