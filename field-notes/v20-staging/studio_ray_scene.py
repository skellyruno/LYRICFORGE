"""Bounded deterministic multi-object Whitted ray tracing for editorial shots.
Analytic spheres and ground, explicit shadow rays, two secondary bounces.
Not stochastic path tracing or global illumination.
"""
import math
import numpy as np
from PIL import Image
from studio_optics import unit,hit_sphere,reflect,refract,environment


def objects(t):
    a=.28*math.sin(t*.45)
    return [(np.array([-.67,.02,.05]),.70,'glass',np.array([.16,.055,.025])),
            (np.array([.82,-.22,.28]),.47,'metal',np.array([.94,.70,.33])),
            (np.array([.28+.17*math.sin(a),-.40,-.70]),.30,'ceramic',np.array([.10,.38,.43]))]


def nearest(o,d,scene):
    dist=np.full(d.shape[:-1],np.inf);ids=np.full(d.shape[:-1],-1,dtype=int)
    dy=d[...,1];floor=(-.73-o[...,1])/np.where(abs(dy)>1e-9,dy,1e-9)
    floor=np.where((dy<-.0001)&(floor>1e-4),floor,np.inf)
    ids=np.where(np.isfinite(floor),len(scene),ids);dist=np.minimum(dist,floor)
    for i,(c,r,*_) in enumerate(scene):
        s=hit_sphere(o,d,c,r);ids=np.where(s<dist,i,ids);dist=np.minimum(dist,s)
    return dist,ids


def visibility(p,n,scene):
    """Three deterministic area-light samples; transparent objects tint the shadow."""
    illum=np.zeros((len(p),3))
    for light in ((-2.8,4.6,2.3),(-2.,4.6,2.3),(-2.4,4.6,3.1)):
        delta=np.asarray(light)-p;length=np.linalg.norm(delta,axis=-1);d=unit(delta);trans=np.ones((len(p),3))
        for c,r,kind,col in scene:
            blocked=hit_sphere(p+n*.002,d,c,r)<length
            trans[blocked]*=(np.array([.58,.76,.84]) if kind=='glass' else .07)
        illum+=trans*np.maximum(0,np.sum(d*n,axis=-1))[:,None]/3
    return illum


def trace(o,d,scene,depth=2):
    o=np.broadcast_to(o,d.shape).reshape(-1,3);d=d.reshape(-1,3);dist,ids=nearest(o,d,scene);rgb=environment(d)*.55
    if depth<0:return rgb
    for i in range(len(scene)+1):
        mask=ids==i
        if not mask.any():continue
        ray=d[mask];p=o[mask]+ray*dist[mask,None]
        if i==len(scene):
            n=np.broadcast_to([0.,1.,0.],p.shape);v=visibility(p,n,scene);base=np.array([.035,.048,.055]);r=reflect(ray,n)
            # Ground rays can see objects, not just the environment.
            refl=trace(p+n*.002,r,scene,depth-1) if depth else environment(r)
            fresnel=.075+.32*(1-np.clip(-ray[:,1],0,1))**5
            value=base*(.32+v*1.4)+refl*fresnel[:,None]
            fade=np.exp(-dist[mask,None]/16);rgb[mask]=value*fade+rgb[mask]*(1-fade);continue
        center,radius,kind,col=scene[i];n=unit(p-center);rr=reflect(ray,n);v=visibility(p,n,scene)
        refl=trace(p+n*.002,rr,scene,depth-1) if depth else environment(rr)
        cos=np.clip(-np.sum(ray*n,axis=-1),0,1);f=.04+.96*(1-cos)**5
        if kind=='glass':
            inside,_=refract(ray,n,1/1.46);entry=p-n*.002;length=hit_sphere(entry,inside,center,radius);length=np.where(np.isfinite(length),length,0);exitp=entry+inside*length[:,None];exitn=unit(exitp-center);out,valid=refract(inside,-exitn,1.46)
            transmit=trace(exitp+exitn*.002,out,scene,depth-1) if depth else environment(out)
            f=np.where(valid,f,1);value=refl*f[:,None]+transmit*(1-f[:,None])*np.exp(-length[:,None]*col)+v*.018
        elif kind=='metal':value=refl*col*(.72+.28*cos[:,None])+v*.035
        else:value=col*(.18+v*1.5)*(1-f[:,None])+refl*f[:,None]
        rgb[mask]=value
    return rgb


def render(w,h,t,*,antialias=True):
    if not 16<=w<=1920 or not 16<=h<=1080 or not math.isfinite(t):raise ValueError('Invalid ray scene')
    sw=min(w,260);sh=max(16,min(180,round(h*sw/w)));a=.32*math.sin(t*.23);eye=np.array([4.7*math.sin(a),1.05,4.7*math.cos(a)]);f=unit(np.array([.05,-.04,0])-eye);right=unit(np.cross(f,[0,1,0]));up=np.cross(right,f)
    yy,xx=np.mgrid[0:sh,0:sw];u=(xx+.5-sw/2)/sh;v=(sh/2-yy-.5)/sh;scene=objects(t)
    d=unit(f+.81*(u[...,None]*right+v[...,None]*up));rgb=trace(eye,d,scene,2).reshape(sh,sw,3)
    if antialias:
        # Fixed subpixel pattern, evaluated only near radiance discontinuities.
        # No frame-dependent random sampling or denoiser shimmer.
        lum=rgb@np.array([.2126,.7152,.0722]);gy,gx=np.gradient(lum)
        edge=np.hypot(gx,gy)>.025
        # Dilate the edge mask one pixel without wrapping image boundaries.
        pad=np.pad(edge,1);edge=np.logical_or.reduce([pad[dy:dy+sh,dx:dx+sw] for dy in range(3) for dx in range(3)])
        if edge.any():
            result=np.zeros((int(edge.sum()),3))
            for dx,dy in ((-.25,-.25),(.25,-.25),(-.25,.25),(.25,.25)):
                rd=unit(f+.81*((u[edge]+dx/sh)[:,None]*right+(v[edge]+dy/sh)[:,None]*up))
                result+=trace(eye,rd,scene,2)*.25
            rgb[edge]=result
    rgb=np.maximum(rgb,0);rgb=np.clip(rgb*(2.51*rgb+.03)/(rgb*(2.43*rgb+.59)+.14),0,1);rgb=np.where(rgb<=.0031308,12.92*rgb,1.055*rgb**(1/2.4)-.055)
    edge=np.minimum(np.minimum((xx+.5)/sw,(sw-xx-.5)/sw),np.minimum((yy+.5)/sh,(sh-yy-.5)/sh));alpha=np.clip(edge/.14,0,1);alpha=alpha*alpha*(3-2*alpha)
    return Image.fromarray(np.uint8(np.clip(np.dstack([rgb,alpha])*255+.5,0,255))).resize((w,h),Image.Resampling.LANCZOS)
