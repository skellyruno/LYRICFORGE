"""A continuous optical presentation of a supplied real capture; no invented UI states.
Subpixel resampling, independent environment lighting, soft reflection, macro-to-wide reveal.
"""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageOps, ImageFilter
import numpy as np
REVISION=2

def smooth(x):
    x=max(0.,min(1.,x));return x*x*x*(x*(x*6-15)+10)

class ProductShot:
    def __init__(self,image,w,h,scene,font):
        self.src=image.convert('RGB');self.w=w;self.h=h;self.scene=scene;self.font=font
        y,x=np.ogrid[:h,:w];self.x=x/w;self.y=y/h
        light=np.exp(-((self.x-.72)**2*7+(self.y-.26)**2*5));base=np.zeros((h,w,3),dtype=np.float32)
        base[:]=[8,11,13];base+=light[:,:,None]*[10,24,19];self.bg=Image.fromarray(np.uint8(base))
        # Feather the matte in the macro phase rather than revealing a hard cutoff.
        yy=np.arange(h,dtype=float)/h;edge=np.minimum(np.clip((yy-.075)/.035,0,1),np.clip((.81-yy)/.04,0,1));self.matte=np.uint8(np.broadcast_to(edge[:,None]*255,(h,w))).copy()
        scale=min(w*.85/self.src.width,h*.63/self.src.height);self.tw=self.src.width*scale;self.th=self.src.height*scale
        self.focus=scene.get('focus_point') or scene.get('features',{}).get('focus') or [.5,.5]
        if not isinstance(self.focus,(list,tuple)) or len(self.focus)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in self.focus):self.focus=[.5,.5]
        self.focus=[max(0.,min(1.,v)) for v in self.focus]
    def render(self,t):
        w,h=self.w,self.h;dur=max(.1,self.scene['end']-self.scene['start']);u=max(0.,min(1.,t/dur));p=smooth(u/.76)
        # Continuous macro-to-wide path; starts with a clear crop, ends on the complete genuine capture.
        zoom=1+0.55*(1-p);cx=w*.5+(0.5-self.focus[0])*w*.24*(1-p);cy=h*.44+(0.5-self.focus[1])*h*.18*(1-p)
        tw,th=self.tw*zoom,self.th*zoom;left,top=cx-tw/2,cy-th/2
        bg=self.bg.copy();d=ImageDraw.Draw(bg);d.line((w*.06,h*.78,w*.94,h*.78),fill='#283c32',width=1)
        # A deliberately soft floor reflection of the actual source, not a simulated hardware surface.
        rw=max(1,round(tw));rh=max(1,round(th*.19));reflection=ImageOps.flip(self.src).resize((rw,rh),Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(max(2,h*.008)))
        ry=round(top+th+7);allowed=max(0,min(rh,round(h*.83)-ry))
        if allowed:
            mask=Image.fromarray(np.tile(np.uint8(np.linspace(35,0,allowed))[:,None],(1,rw)));bg.paste(reflection.crop((0,0,rw,allowed)),(round(left),ry),mask)
        # Affine resampling is evaluated in floating point on the full canvas (no snapped crop origin).
        inv=(self.src.width/tw,0,-left*self.src.width/tw,0,self.src.height/th,-top*self.src.height/th)
        tile=self.src.transform((w,h),Image.Transform.AFFINE,inv,Image.Resampling.BICUBIC)
        alpha=Image.new('L',self.src.size,255).transform((w,h),Image.Transform.AFFINE,inv,Image.Resampling.BICUBIC)
        # Keep the narration and attribution lanes clear even at macro scale.
        alpha=Image.fromarray((np.asarray(alpha,dtype=np.uint16)*self.matte.astype(np.uint16)//255).astype(np.uint8))
        bg.paste(tile,(0,0),alpha);d=ImageDraw.Draw(bg)
        d.text((round(w*.06),round(h*.035)),'ACTUAL CAPTURE / EDITORIAL CAMERA',font=self.font(max(11,round(h*.024)),True),fill='#b7c5be')
        return bg

def write_frames(scene,w,h,asset,folder,fps,font,check_cancel=lambda:None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with Image.open(asset) as im:shot=ProductShot(ImageOps.exif_transpose(im),w,h,scene,font)
    for i in range(scene['frames']):
        if i%12==0:check_cancel()
        shot.render(i/fps).save(folder/f'{i+1:05d}.jpg',quality=94,subsampling=0)
    return fps
