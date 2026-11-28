"""Bounded CPU triangle rasterizer. Perspective-correct UVs and smooth normals,
Z buffer, GGX direct lighting, analytic environment reflection. No external
mesh paths or code execution; caller supplies a validated indexed triangle mesh.
"""
import math
import numpy as np
from PIL import Image


def validate_mesh(m):
    if not isinstance(m,dict):raise ValueError('Mesh must be an object')
    def rows(key,width,lo,hi,limit,minimum=3):
        a=m.get(key)
        if not isinstance(a,list) or not minimum<=len(a)<=limit:raise ValueError('Invalid mesh '+key)
        for r in a:
            if not isinstance(r,list) or len(r)!=width or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or not lo<=x<=hi for x in r):raise ValueError('Invalid mesh '+key)
        return [list(r) for r in a]
    v=rows('vertices',3,-2,2,512);uv=rows('uv',2,0,1,512)
    f=rows('faces',3,0,len(v)-1,1024,1)
    if len(uv)!=len(v) or any(any(type(i) is not int for i in r) or len(set(r))!=3 for r in f):raise ValueError('Invalid mesh indexing')
    result={'vertices':v,'uv':uv,'faces':f}
    if 'target' in m:
        t=rows('target',3,-2,2,512)
        if len(t)!=len(v):raise ValueError('Morph topology must match')
        result['target']=t
    for k in ('vertices','target'):
        if k in result:
            p=np.array(result[k]);tri=p[np.array(f)];area=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)
            if np.any(area<1e-7):raise ValueError('Degenerate triangle')
    return result


def unit(x):return x/np.maximum(1e-8,np.linalg.norm(x,axis=-1,keepdims=True))

def _raster_numpy(p,z,uv,n,faces,w,h):
    depth=np.full((h,w),np.inf,np.float32);attrs=np.zeros((h,w,5),np.float32)
    for i,j,k in faces:
        a,b,c=p[[i,j,k]];den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-6:continue
        x0=max(0,int(np.floor(min(a[0],b[0],c[0]))));x1=min(w,int(np.ceil(max(a[0],b[0],c[0])))+1)
        y0=max(0,int(np.floor(min(a[1],b[1],c[1]))));y1=min(h,int(np.ceil(max(a[1],b[1],c[1])))+1)
        if x0>=x1 or y0>=y1:continue
        yy,xx=np.mgrid[y0:y1,x0:x1];xx=xx+.5;yy=yy+.5
        wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den;wc=1-wa-wb
        qa,qb,qc=wa/z[i],wb/z[j],wc/z[k];inv=qa+qb+qc;zz=1/np.maximum(1e-8,inv)
        view=depth[y0:y1,x0:x1];mask=(wa>=-1e-6)&(wb>=-1e-6)&(wc>=-1e-6)&(zz<view)
        if not mask.any():continue
        view[mask]=zz[mask];a5=np.concatenate([uv[i],n[i]]);b5=np.concatenate([uv[j],n[j]]);c5=np.concatenate([uv[k],n[k]])
        attrs[y0:y1,x0:x1][mask]=(qa[mask,None]*a5+qb[mask,None]*b5+qc[mask,None]*c5)*zz[mask,None]
    return depth,attrs

# Optional acceleration, identical algorithm. No mandatory dependency.
try:
    from numba import njit
    @njit(cache=True)
    def _fast(p,z,uv,n,faces,w,h):
        depth=np.full((h,w),np.inf,np.float32);attrs=np.zeros((h,w,5),np.float32)
        for face in faces:
            i,j,k=face;ax,ay=p[i];bx,by=p[j];cx,cy=p[k];den=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
            if abs(den)<1e-6:continue
            x0=max(0,int(np.floor(min(ax,bx,cx))));x1=min(w,int(np.ceil(max(ax,bx,cx)))+1)
            y0=max(0,int(np.floor(min(ay,by,cy))));y1=min(h,int(np.ceil(max(ay,by,cy)))+1)
            for y in range(y0,y1):
                for x in range(x0,x1):
                    wa=((by-cy)*(x+.5-cx)+(cx-bx)*(y+.5-cy))/den
                    wb=((cy-ay)*(x+.5-cx)+(ax-cx)*(y+.5-cy))/den;wc=1-wa-wb
                    if min(wa,wb,wc)<-1e-6:continue
                    qa,qb,qc=wa/z[i],wb/z[j],wc/z[k];zz=1/(qa+qb+qc)
                    if zz>=depth[y,x]:continue
                    depth[y,x]=zz
                    for q in range(2):attrs[y,x,q]=(qa*uv[i,q]+qb*uv[j,q]+qc*uv[k,q])*zz
                    for q in range(3):attrs[y,x,q+2]=(qa*n[i,q]+qb*n[j,q]+qc*n[k,q])*zz
        return depth,attrs
except ImportError:
    _fast=None

class Mesh:
    def __init__(self,spec,texture):
        m=validate_mesh(spec);self.v=np.array(m['vertices'],np.float32);self.target=np.array(m.get('target',m['vertices']),np.float32);self.uv=np.array(m['uv'],np.float32);self.faces=np.array(m['faces'],np.int32)
        self.tex=np.asarray(texture.convert('RGB').resize((512,512),Image.Resampling.BILINEAR),dtype=np.float32)/255
        self.radius=max(.1,float(np.max(np.linalg.norm(np.concatenate([self.v,self.target]),axis=1))))
    def render(self,w,h,angle,morph=0.,roughness=.35,metal=.35):
        # Render within bounded internal raster; output resolution is independent.
        f=min(1.,420/max(w,h));ww=max(2,round(w*f));hh=max(2,round(h*f));v=(self.v+(self.target-self.v)*morph)/self.radius
        ca,sa=math.cos(angle),math.sin(angle);tilt=.30+.13*math.sin(angle*.7);ct,st=math.cos(tilt),math.sin(tilt)
        r=np.array([[ca,0,sa],[st*sa,ct,-st*ca],[-ct*sa,st,ct*ca]],np.float32);v=v@r.T
        tri=v[self.faces];fn=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);n=np.zeros_like(v)
        for q in range(3):np.add.at(n,self.faces[:,q],fn)
        n=unit(n);z=3.4-v[:,2];focal=min(ww,hh)*1.42;p=np.stack([ww/2+focal*v[:,0]/z,hh/2-focal*v[:,1]/z],axis=1)
        raster=_fast if _fast is not None else _raster_numpy;depth,attrs=raster(p,z,self.uv,n,self.faces,ww,hh);mask=np.isfinite(depth);out=np.zeros((hh,ww,4),np.uint8)
        if not mask.any():return Image.fromarray(out).resize((w,h))
        a=attrs[mask];normal=unit(a[:,2:]);u=np.clip(a[:,0],0,1)*511;vv=np.clip(a[:,1],0,1)*511;ix=np.minimum(510,u.astype(int));iy=np.minimum(510,vv.astype(int));fx=(u-ix)[:,None];fy=(vv-iy)[:,None];t=self.tex
        base=((t[iy,ix]*(1-fx)+t[iy,ix+1]*fx)*(1-fy)+(t[iy+1,ix]*(1-fx)+t[iy+1,ix+1]*fx)*fy)**2.2
        yy,xx=np.nonzero(mask);view=unit(np.stack([-(xx+.5-ww/2)/focal,(yy+.5-hh/2)/focal,np.ones(len(xx))],axis=-1));normal=np.where((normal*view).sum(1,keepdims=True)<0,-normal,normal)
        nv=np.maximum(.001,(normal*view).sum(1));f0=.04*(1-metal)+base*metal;refl=2*nv[:,None]*normal-view
        # Analytic softbox environment reflected as broad directional lobes.
        env=np.array([.14,.19,.24])+np.maximum(0,refl@np.array([-.45,.65,.61]))[:,None]**(2+16*(1-roughness))*[1.8,1.42,1.0]+np.maximum(0,refl@np.array([.8,.15,.58]))[:,None]**(2+10*(1-roughness))*[.35,.8,1.5]
        fres=f0+(1-f0)*(1-nv[:,None])**5;lit=base*(1-metal)*.26+env*fres*.8
        alpha=max(.025,roughness**2);a2=alpha**2;k=(roughness+1)**2/8
        for vec,col in [((-.55,.7,.65),(2.0,1.6,1.15)),((.8,.2,.5),(.65,1.05,1.7))]:
            l=unit(np.array(vec));half=unit(view+l);nl=np.maximum(0,normal@l);nh=np.maximum(0,(normal*half).sum(1));vh=np.maximum(0,(view*half).sum(1));D=a2/(np.pi*(nh*nh*(a2-1)+1)**2+1e-8);G=nv/(nv*(1-k)+k)*nl/(nl*(1-k)+k);F=f0+(1-f0)*(1-vh[:,None])**5
            spec=(D*G/(4*nv*np.maximum(.001,nl)))[:,None]*F;lit+=(base*(1-metal)*(1-F)/np.pi+spec)*nl[:,None]*np.array(col)
        rgb=np.clip(lit/(1+.32*lit),0,1)**(1/2.2);out[mask,:3]=np.uint8(rgb*255+.5);out[mask,3]=255
        return Image.fromarray(out).resize((w,h),Image.Resampling.BICUBIC)
