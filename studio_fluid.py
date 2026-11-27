"""Bounded deterministic 2-D flow: spectral pressure projection, semi-Lagrangian
advection, passive RGB dye. Editorial simulation, not a calibrated experiment."""
import math
import numpy as np
from PIL import Image


def project(u,v):
    n,m=u.shape
    kx,ky=np.meshgrid(2*np.pi*np.fft.fftfreq(m),2*np.pi*np.fft.fftfreq(n))
    if m%2==0:kx[:,m//2]=0
    if n%2==0:ky[n//2,:]=0
    a,b=np.fft.fft2(u),np.fft.fft2(v);d=kx*a+ky*b;den=kx*kx+ky*ky
    q=np.divide(d,den,out=np.zeros_like(d),where=den>0)
    return np.fft.ifft2(a-kx*q).real,np.fft.ifft2(b-ky*q).real


def advect(a,u,v,dt,x,y):
    n,m=u.shape;xx,yy=(x-dt*u)%m,(y-dt*v)%n
    i,j=np.floor(xx).astype(int)%m,np.floor(yy).astype(int)%n
    f,g=xx-np.floor(xx),yy-np.floor(yy)
    if a.ndim==3:f,g=f[...,None],g[...,None]
    return (1-g)*((1-f)*a[j,i]+f*a[j,(i+1)%m])+g*((1-f)*a[(j+1)%n,i]+f*a[(j+1)%n,(i+1)%m])


def advect_corrected(a,u,v,dt,x,y):
    """Limited MacCormack transport: preserve thin filaments without overshoot."""
    forward=advect(a,u,v,dt,x,y)
    correction=forward+.5*(a-advect(forward,u,v,-dt,x,y))
    n,m=u.shape
    i=np.floor(x-dt*u).astype(int)%m;j=np.floor(y-dt*v).astype(int)%n
    corners=np.stack([a[j,i],a[j,(i+1)%m],a[(j+1)%n,i],a[(j+1)%n,(i+1)%m]])
    return np.clip(correction,corners.min(axis=0),corners.max(axis=0))


def optical_surface(a):
    """Stylized emissive fluid with density-dependent absorption and environment light.
    The optical model is illustrative, not a physically calibrated experiment."""
    density=a.sum(axis=2);dy,dx=np.gradient(density)
    normal=np.stack([-dx*9,-dy*9,np.ones_like(dx)],axis=-1)
    normal/=np.linalg.norm(normal,axis=-1,keepdims=True)
    light=np.array([-.48,-.65,.59]);light/=np.linalg.norm(light)
    diffuse=np.maximum(0,normal@light)
    half=light+np.array([0,0,1]);half/=np.linalg.norm(half)
    spec=np.maximum(0,normal@half)**20
    fresnel=.035+.965*(1-normal[...,2])**5
    linear=1-np.exp(-a*2.9)
    rgb=linear*(.48+.85*diffuse[...,None])+(.32*spec[...,None]+.35*fresnel[...,None])*np.array([.72,.85,1.])
    alpha=1-np.exp(-density*3.1)
    return np.clip(rgb,0,1)**(1/2.2),alpha


class Fluid:
    """Fixed 30 Hz simulation, interpolated display; cache at most 600 ticks."""
    def __init__(self,seed=7,grid=128):
        if type(seed) is not int or not 0<=seed<2**31 or type(grid) is not int or not 32<=grid<=128:raise ValueError('Invalid fluid budget')
        self.n=grid;self.x,self.y=np.meshgrid(np.arange(grid),np.arange(grid));self.dt=1/30
        self.phase=np.random.default_rng(seed).uniform(0,2*np.pi,3)
        self.u=np.zeros((grid,grid));self.v=self.u.copy();self.dye=np.zeros((grid,grid,3));self.frames=[]
        for i,phi in enumerate(self.phase):
            cx=grid*(.5+.23*np.cos(phi));cy=grid*(.5+.23*np.sin(phi));self.dye[...,i]=.85*np.exp(-((self.x-cx)**2+(self.y-cy)**2)/(grid*.10)**2)
        self.frames.append(self._save())

    def _save(self):return np.uint8(np.clip(self.dye,0,1)*255+.5)

    def step(self):
        t=len(self.frames)*self.dt;n=self.n;x=self.x/n*2*np.pi;y=self.y/n*2*np.pi
        u=advect(self.u,self.u,self.v,self.dt,self.x,self.y)*.992
        v=advect(self.v,self.u,self.v,self.dt,self.x,self.y)*.992
        u+=self.dt*14*(np.sin(y*2+t*.7)+.6*np.cos(x+y+t*.4))
        v+=self.dt*14*(np.cos(x*2-t*.5)-.6*np.cos(x+y+t*.4))
        curl=(np.roll(v,-1,axis=1)-np.roll(v,1,axis=1)-np.roll(u,-1,axis=0)+np.roll(u,1,axis=0))*.5
        gy,gx=np.gradient(abs(curl));norm=np.hypot(gx,gy)+1e-8
        u+=self.dt*1.8*gy/norm*curl;v-=self.dt*1.8*gx/norm*curl
        self.u,self.v=project(u,v);self.dye=advect_corrected(self.dye,self.u,self.v,self.dt,self.x,self.y)*.998
        for i,phase in enumerate(self.phase):
            cx=n*(.5+.27*np.cos(phase+t*.53));cy=n*(.5+.27*np.sin(phase+t*.53));dx=(self.x-cx+n/2)%n-n/2;dy=(self.y-cy+n/2)%n-n/2
            self.dye[...,i]+=self.dt*.48*np.exp(-(dx*dx+dy*dy)/(n*.052)**2)
        self.dye=np.clip(self.dye,0,1);self.frames.append(self._save())

    def render(self,w,h,t):
        if not math.isfinite(t) or not 2<=w<=7680 or not 2<=h<=7680:raise ValueError('Invalid fluid render')
        tick=max(0,min(599,t*30));i=int(tick);j=min(599,i+1)
        while len(self.frames)<=j:self.step()
        a=(self.frames[i].astype(np.float32)*(1-(tick-i))+self.frames[j]*(tick-i))/255
        rgb,alpha=optical_surface(a)
        yy,xx=np.mgrid[-1:1:complex(self.n),-1:1:complex(self.n)];edge=np.clip((1-np.maximum(abs(xx),abs(yy)))*3.6,0,1);alpha*=edge*edge*(3-2*edge)
        return Image.fromarray(np.uint8(np.concatenate([rgb,alpha[...,None]],2)*255+.5),'RGBA').resize((w,h),Image.Resampling.BICUBIC)


def additive(w,h,t):
    """Ideal additive RGB light illustration; not subtractive paint mixing."""
    yy,xx=np.mgrid[-1:1:complex(h),-1:1:complex(w)];xx*=w/h
    p=np.clip(t,0,1);p=p*p*(3-2*p);r=.56;sep=.65-.30*p
    rgb=[]
    for cx,cy in ((0,-sep),(-sep*.866,sep*.5),(sep*.866,sep*.5)):
        d=np.sqrt((xx-cx)**2+(yy-cy)**2);rgb.append(np.clip((r-d)*min(w,h)*.35+.5,0,1))
    rgb=np.stack(rgb,-1);alpha=np.max(rgb,axis=-1)
    rgb=np.divide(rgb,alpha[...,None],out=np.zeros_like(rgb),where=alpha[...,None]>0)
    return Image.fromarray(np.uint8(np.concatenate([rgb,alpha[...,None]],-1)*255+.5),'RGBA')


def light_study(w,h,t):
    """Additive diagram with glowing optical paths; exact colors inside ideal disks."""
    base=additive(w,h,t)
    yy,xx=np.mgrid[-1:1:complex(h),-1:1:complex(w)];xx*=w/h
    p=np.clip(t,0,1);p=p*p*(3-2*p);sep=.65-.30*p
    glow=np.zeros((h,w,3),np.float32)
    for k,(cx,cy) in enumerate(((0,-sep),(-sep*.866,sep*.5),(sep*.866,sep*.5))):
        d=np.hypot(xx-cx,yy-cy)
        glow[...,k]=.16*np.exp(-((d-.56)/.115)**2)+.025*np.exp(-d*d/.50)
    ga=np.max(glow,axis=-1);grgb=np.divide(glow,ga[...,None],out=np.zeros_like(glow),where=ga[...,None]>0)
    out=Image.fromarray(np.uint8(np.clip(np.dstack([grgb,ga]),0,1)*255+.5),'RGBA')
    out.alpha_composite(base)
    return out
