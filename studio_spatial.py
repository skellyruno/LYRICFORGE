"""Perspective-projected editorial presentation of genuine captured pixels.
A small analytic rasterizer for an extruded display plane, not a physical model
of the product. Uses Pillow and NumPy only; no GPU or model downloads.
"""
from pathlib import Path
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps
from studio_material import shade

REVISION=5

def ease(x):
    x=max(0.,min(1.,float(x)));return x*x*x*(10+x*(-15+6*x))

def transform(src,dst):
    """Inverse homography, destination pixel -> original texture pixel."""
    mat=[];rhs=[]
    for (x,y),(u,v) in zip(dst,src):
        mat.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]])
        rhs.extend([u,v])
    return tuple(np.linalg.solve(np.asarray(mat),np.asarray(rhs)))

class SpatialShot:
    def __init__(self,image,w,h,scene,font):
        self.w,self.h,self.scene,self.font=w,h,scene,font
        self.source=image.convert('RGB');self.duration=max(.1,scene['end']-scene['start'])
        self.ratio=self.source.width/self.source.height
        self.half_w=min(1.65,self.ratio);self.half_h=self.half_w/self.ratio
        self.front=np.array([[-self.half_w,-self.half_h,0],[self.half_w,-self.half_h,0],[self.half_w,self.half_h,0],[-self.half_w,self.half_h,0]],dtype=float)
        self.mesh=np.vstack([self.front,self.front+np.array([0,0,.075])]);self.faces=((0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7))
        self.tex_coords=((0,0),(self.source.width-1,0),(self.source.width-1,self.source.height-1),(0,self.source.height-1))
        self.mask=Image.new('L',self.source.size,255)
        from studio_layers import atmosphere
        self.bg=atmosphere(w,h);self.title=str(scene.get('hero_title') or scene.get('asset_name') or 'Workspace')[:80]
        self.focus=scene.get('focus_point') or [.5,.5]
        if not isinstance(self.focus,(list,tuple)) or len(self.focus)!=2 or not all(isinstance(a,(int,float)) and math.isfinite(a) for a in self.focus):self.focus=[.5,.5]
        self.focus=[max(0.,min(1.,a)) for a in self.focus]
        self.label=font(max(10,round(h*.022)),True)
        self.multiple=w/h>=1.45 and self.duration>=3.5 and self.source.width>=480 and self.source.height>=260
        self.edge=np.minimum(np.clip((np.arange(h)/h-.052)/.03,0,1),np.clip((.825-np.arange(h)/h)/.055,0,1)).astype(np.float32)
        # A genuine detail crop, never a synthetic reconstruction of a control.
        cw,ch=round(self.source.width*.25),round(self.source.height*.40)
        fx,fy=self.focus if scene.get('focus_point') else (.20,.38)
        x0=max(0,min(self.source.width-cw,round(fx*self.source.width-cw/2)));y0=max(0,min(self.source.height-ch,round(fy*self.source.height-ch/2)))
        self.detail=self.source.crop((x0,y0,x0+cw,y0+ch))
        self.detail_mask=Image.new('L',self.detail.size,255)
        self.detail_coords=((0,0),(cw-1,0),(cw-1,ch-1),(0,ch-1))
    def detail_amount(self,t):
        if not self.multiple:return 0.
        u=t/self.duration
        return ease(u/.11)*(1-ease((u-.30)/.30))
    def detail_layer(self,t):
        w,h=self.w,self.h;amount=self.detail_amount(t)
        layer=Image.new('RGBA',(w,h))
        if amount<=.001:return layer
        # Project an independent image plane at a shallower depth. Its motion
        # is coupled to the principal camera but the texture never changes.
        u=t/self.duration;ratio=self.detail.width/self.detail.height
        hw=min(.76,.66*ratio);hh=hw/ratio;v=np.array([[-hw,-hh,0],[hw,-hh,0],[hw,hh,0],[-hw,hh,0]])
        yaw=math.radians(15-20*ease(u/.55));c,s=math.cos(yaw),math.sin(yaw)
        v=v@np.array([[c,0,-s],[0,1,0],[s,0,c]]);v[:,2]+=2.95
        pts=v[:,:2]/v[:,2,None]*min(w*.72,h*1.05)+[w*(.76+.13*(1-amount)),h*.41]
        coeff=transform(self.detail_coords,pts)
        tile=self.detail.transform((w,h),Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
        mask=self.detail_mask.transform((w,h),Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
        shadow=mask.filter(ImageFilter.GaussianBlur(max(2,h*.014)));layer.paste((0,0,0,180),(0,0,w,h),shadow)
        layer.paste(tile.convert('RGBA'),(0,0),mask)
        d=ImageDraw.Draw(layer);d.line([tuple(p) for p in np.vstack([pts,pts[0]])],fill=(211,188,130,255),width=max(1,h//380))
        d.text((round(pts[:,0].min()),round(pts[:,1].min()-h*.043)),'CAPTURE DETAIL',font=self.label,fill=(220,200,151,255))
        layer.putalpha(layer.getchannel('A').point(lambda a:round(a*amount)));return layer
    def geometry(self,t,exit_progress=0.):
        p=ease(t/(self.duration*.88));q=ease(exit_progress)
        # Camera orbit and dolly in object space. The final view is front-on.
        yaw=math.radians(-43*(1-p)+9*math.sin(math.pi*p));pitch=math.radians(15*(1-p)-4*math.sin(math.pi*p));roll=math.radians(-8*(1-p))
        c,s=math.cos,math.sin
        ry=np.array([[c(yaw),0,s(yaw)],[0,1,0],[-s(yaw),0,c(yaw)]])
        rx=np.array([[1,0,0],[0,c(pitch),-s(pitch)],[0,s(pitch),c(pitch)]])
        rz=np.array([[c(roll),-s(roll),0],[s(roll),c(roll),0],[0,0,1]])
        rot=rz@rx@ry;v=self.mesh@rot.T
        focal=min(self.w*.81,self.h*1.12);target=min(self.w*.83/(2*self.half_w),self.h*.66/(2*self.half_h));distance=focal/target
        # Start close, but keep all screen pixels within the matte at final reveal.
        detail=self.detail_amount(t)*(1-q)
        z=distance*(.89+.11*p+q*.85+.36*detail);v[:,2]+=z
        cx=self.w*(.5+(.5-self.focus[0])*.15*(1-p)-q*.83-.17*detail);cy=self.h*(.425+(.5-self.focus[1])*.09*(1-p)-q*.015)
        points=v[:,:2]/v[:,2,None]*focal+np.array([cx,cy])
        return points,v,rot
    def layer(self,t,exit_progress=0.):
        w,h=self.w,self.h;points,v,rot=self.geometry(t,exit_progress);q=ease(exit_progress)
        im=Image.new('RGBA',(w,h));d=ImageDraw.Draw(im)
        # Soft contact shadow beneath the geometry, independent of its front texture.
        bounds=(float(points[:,0].min()),float(points[:,1].min()),float(points[:,0].max()),float(points[:,1].max()))
        shadow=Image.new('L',(w,h));sd=ImageDraw.Draw(shadow);sd.ellipse((bounds[0]-.025*w,bounds[3]-.02*h,bounds[2]+.025*w,bounds[3]+.035*h),fill=120)
        shadow=shadow.filter(ImageFilter.GaussianBlur(max(2,h*.022)));im.paste((0,0,0,255),(0,0,w,h),shadow)
        # Project a broad area-light shadow from the display silhouette onto
        # an approximate studio floor. Blend the soft penumbra with contact shadow.
        bottom=max(points[2,1],points[3,1]);floor_y=min(h*.80,bottom+h*.028)
        hull=[(float(points[3,0]),floor_y),(float(points[2,0]),floor_y),(float(points[1,0])+w*.12,floor_y+h*.045),(float(points[0,0])+w*.12,floor_y+h*.045)]
        cast=Image.new('L',(w,h));ImageDraw.Draw(cast).polygon(hull,fill=100);cast=cast.filter(ImageFilter.GaussianBlur(max(2,h*.018)))
        sh=Image.new('RGBA',(w,h),(0,0,0,255));sh.putalpha(cast);im.alpha_composite(sh)
        # Reflect the actual screen on a separate floor plane; blur and attenuate.
        # This is a stylized planar reflection, not ray-traced physical lighting.
        rw=max(1,round(bounds[2]-bounds[0]));rh=max(1,round(h*.09));ry=round(bounds[3]+h*.012)
        if ry<h*.82 and rw<=w*2:
            refl=ImageOps.flip(self.source).resize((rw,rh),Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(max(2,h*.009)))
            rm=Image.fromarray(np.tile(np.uint8(np.linspace(31,0,rh))[:,None],(1,rw)))
            im.paste(refl.convert('RGBA'),(round(bounds[0]),ry),rm)
        # Painter ordering of solid faces; screen texture remains color-accurate.
        for face in sorted(self.faces,key=lambda f:float(v[list(f),2].mean()),reverse=True):
            a,b,c=v[list(face)[:3]];normal=np.cross(b-a,c-a)
            col=shade(normal,-v[list(face)].mean(axis=0),ease(t/self.duration))
            d.polygon([tuple(points[i]) for i in face],fill=(*col,255))
        # Perspective-correct texture mapping, with one-pixel antialiased coverage.
        coeff=transform(self.tex_coords,points[:4]);tile=self.source.transform((w,h),Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
        mask=self.mask.transform((w,h),Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
        im.paste(tile.convert('RGBA'),(0,0),mask)
        # Fine edge only; no painted-over UI or synthetic knob values.
        d=ImageDraw.Draw(im);d.line([tuple(x) for x in np.vstack([points[:4],points[0]])],fill=(98,123,119,255),width=max(1,h//600))
        # Soft matte at caption lane, no abrupt crop.
        a=np.asarray(im.getchannel('A'),dtype=np.float32);a*=self.edge[:,None];a*=1-.35*q
        im.putalpha(Image.fromarray(a.astype('uint8')));return im
    def render(self,t):
        im=self.bg.copy();layer=self.layer(t)
        # Depth-of-field approximation on the farther plane during a rack focus.
        # Do not blur the full-capture hold or any recorded demonstration.
        amount=self.detail_amount(t)
        if amount>.01:layer=layer.filter(ImageFilter.GaussianBlur(self.h*.0032*amount))
        im.paste(layer,(0,0),layer)
        if amount>.001:
            detail=self.detail_layer(t);im.paste(detail,(0,0),detail)
        d=ImageDraw.Draw(im);d.text((round(self.w*.06),round(self.h*.027)),'ACTUAL CAPTURE  /  3D EDITORIAL PRESENTATION',font=self.label,fill='#a4b7b3')
        return im
    def bridge(self,target,t,seconds):
        """Outgoing geometry continues moving while a new composition is revealed.
        At time zero the composition exactly matches the preceding held pose.
        """
        u=max(0.,min(1.,t/max(.001,seconds)));p=ease(u)
        if u<=0:return self.render(self.duration)
        if u>=1:return target
        # Keep incoming typography intact; it enters as a complete composition
        # rather than being clipped by the previous directional wipe.
        im=arriving_composition(self.bg,target,p)
        layer=self.layer(self.duration,exit_progress=u);im.paste(layer,(0,0),layer)
        if p<.999:
            label=Image.new('RGBA',im.size);ImageDraw.Draw(label).text((round(self.w*.06),round(self.h*.027)),'ACTUAL CAPTURE  /  3D EDITORIAL PRESENTATION',font=self.label,fill=(164,183,179,round(255*(1-p))))
            im.paste(label,(0,0),label)
        return im

def arriving_composition(bg,target,p):
    if p<=0:return bg.copy()
    if p>=1:return target.copy()
    w,h=bg.size;im=bg.copy();scale=.93+.07*p
    tile=target.resize((round(w*scale),round(h*scale)),Image.Resampling.BICUBIC)
    im.paste(tile,(round((w-tile.width)/2+w*.07*(1-p)),round((h-tile.height)/2)),Image.new('L',tile.size,round(255*p)))
    return im

def editorial_handoff(previous,target,t,seconds):
    """Project the outgoing authored composition into an editorial plane.
    The original final frame and the new frame are exact endpoint poses.
    """
    u=max(0.,min(1.,t/max(.001,seconds)));p=ease(u)
    if u<=0:return previous.copy()
    if u>=1:return target.copy()
    im=target.copy();layer=handoff_layer(previous,p);im.paste(layer,(0,0),layer);return im

def handoff_layer(previous,p):
    """RGBA outgoing editorial texture, suitable over a moving video stream."""
    p=max(0.,min(1.,p));w,h=previous.size
    if p>=1:return Image.new('RGBA',(w,h))
    scale=1-.28*p;dx=-w*.80*p;dy=h*.035*p
    pts=np.array([[dx,dy],[dx+w*scale,dy+h*.075*p],[dx+w*scale,dy+h*scale-h*.075*p],[dx,dy+h*scale]])
    coeff=transform(((0,0),(w-1,0),(w-1,h-1),(0,h-1)),pts)
    tile=previous.transform((w,h),Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC).convert('RGBA')
    mask=Image.new('L',(w,h),round(255*(1-p*p))).transform((w,h),Image.Transform.PERSPECTIVE,coeff,Image.Resampling.BICUBIC)
    tile.putalpha(mask);return tile

def write_handoff_overlay(previous,folder,seconds,fps,check_cancel=lambda:None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    for i in range(max(1,math.ceil(seconds*fps))+1):
        if i%12==0:check_cancel()
        handoff_layer(previous,ease(i/fps/seconds)).save(folder/f'{i+1:05d}.png')
    return fps

def editorial_previous(scene,w,h,font,asset=None,*,media_bank=None,assets_folder=None):
    info=scene.get('editorial_bridge_scene')
    if not info:return None
    from studio_editorial_motion import EditorialShot
    image=None
    if asset:
        with Image.open(asset) as src:image=ImageOps.exif_transpose(src).convert('RGB')
    if media_bank is None:
        from studio_media_layers import MediaBank
        with MediaBank(assets_folder) as bank:
            shot=EditorialShot(info,w,h,image,font,bank);return shot.render(shot.duration)
    shot=EditorialShot(info,w,h,image,font,media_bank);return shot.render(shot.duration)

def last_encoded_frame(clip,frames,check_cancel=lambda:None):
    import io,subprocess
    check_cancel()
    # Scene clips are bounded by Director. Select exact decoded index, not
    # timestamp rounding or speculative source time. A single frame is returned.
    r=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(clip),'-vf',f'select=eq(n\\,{frames-1})','-frames:v','1','-f','image2pipe','-vcodec','png','-threads','1','pipe:1'],capture_output=True,timeout=60,check=True)
    check_cancel()
    with Image.open(io.BytesIO(r.stdout)) as im:return im.convert('RGB')

def write_frames(scene,w,h,asset,folder,fps,font,check_cancel=lambda:None,*,editorial_bridge=None,footage_previous=None,assets_folder=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with Image.open(asset) as src:shot=SpatialShot(ImageOps.exif_transpose(src),w,h,scene,font)
    previous=editorial_previous(scene,w,h,font,editorial_bridge,assets_folder=assets_folder)
    for i in range(scene['frames']):
        if i%12==0:check_cancel()
        frame=shot.render(i/fps)
        if previous is not None and i/fps<scene['editorial_bridge_seconds']:frame=editorial_handoff(previous,frame,i/fps,scene['editorial_bridge_seconds'])
        if footage_previous is not None and i/fps<scene['footage_bridge_seconds']:frame=editorial_handoff(footage_previous,frame,i/fps,scene['footage_bridge_seconds'])
        frame.save(folder/f'{i+1:05d}.jpg',quality=94,subsampling=0)
    return fps
