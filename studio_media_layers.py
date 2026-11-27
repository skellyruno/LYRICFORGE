"""Bounded local asset compositor: no arbitrary paths, network or implicit looping."""
from pathlib import Path
import re, tempfile, subprocess, math
from PIL import Image, ImageOps
import numpy as np
PATTERN=re.compile(r'[a-f0-9]{32}\.(?:png|jpg|jpeg|webp|mp4|mov|mkv|m4v|webm)')
VIDEO={'.mp4','.mov','.mkv','.m4v','.webm'}
KINDS={'image','document','footage','sphere','mesh'}

def asset_id(value,kind):
    if not isinstance(value,str) or not PATTERN.fullmatch(value):raise ValueError('Invalid local media layer asset ID')
    if (Path(value).suffix in VIDEO)!=(kind=='footage'):raise ValueError('Media layer type does not match asset')
    return value

def resolve(folder,key):
    if not isinstance(key,str) or not PATTERN.fullmatch(key) or folder is None:raise ValueError('Missing media layer asset registry')
    root=Path(folder);p=root/key
    if root.is_symlink() or p.is_symlink() or not p.is_file():raise ValueError('Missing local media layer asset')
    index=root/'index.json'
    if index.is_file() and not index.is_symlink():
        from studio_performance import read_cache
        entry=read_cache(index).get(key,{})
        if isinstance(entry,dict) and entry.get('disabled'):raise ValueError('Media layer references a disabled asset')
    return p

def stamps(scene,folder):
    result={}
    for s in (scene,scene.get('editorial_bridge_scene',{})):
        g=s.get('graphic') or {}
        for l in g.get('layers',[]):
            if l.get('type') in KINDS:
                p=resolve(folder,asset_id(l.get('asset'),l['type']));st=p.stat();result[p.name]=[st.st_size,st.st_mtime_ns]
    return result

class MediaBank:
    """Decode bounded footage strips to temporary disk, not unbounded RAM.
    At most 6 unique strips per transition; requested frame clock up to 60fps.
    Source exhaustion holds last frame. Original source audio is not mixed.
    """
    def __init__(self,folder,fps=30):
        if fps not in (24,30,60):raise ValueError("Unsupported media clock")
        self.fps=fps;self.folder=folder;self.images={};self.strips={};self.tmp=tempfile.TemporaryDirectory(prefix='skell-media-');self.last={}
    def close(self):self.images.clear();self.strips.clear();self.last.clear();self.tmp.cleanup()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def image(self,key):
        if key not in self.images:
            p=resolve(self.folder,key)
            with Image.open(p) as im:
                if im.width*im.height>32_000_000:raise ValueError('Media layer image exceeds pixel limit')
                tile=ImageOps.exif_transpose(im).convert('RGBA');tile.thumbnail((1280,1280),Image.Resampling.LANCZOS);self.images[key]=tile
        return self.images[key]
    def frame(self,l,t):
        key=l['asset']
        if l['type']!='footage':return self.image(key)
        a,b=l['trim'];k=(key,a,b)
        if k not in self.strips:
            if len(self.strips)>=6:raise ValueError('Too many footage strips in connected compositions')
            p=resolve(self.folder,key);root=Path(self.tmp.name)/str(len(self.strips));root.mkdir()
            args=['ffmpeg','-v','error','-nostdin','-threads','1','-ss',str(a),'-i',str(p),'-t',str(b-a),'-an','-vf',f'fps={self.fps},scale=960:960:force_original_aspect_ratio=decrease','-q:v','3','-threads','1',str(root/'%05d.jpg')]
            subprocess.run(args,capture_output=True,check=True,timeout=90)
            files=sorted(root.glob('*.jpg'))
            if not files:raise ValueError('Footage trim contains no decoded frames')
            self.strips[k]=files
        files=self.strips[k];i=min(len(files)-1,max(0,int((t-l['delay'])*self.fps+1e-6)))
        if k not in self.last or self.last[k][0]!=i:
            with Image.open(files[i]) as im:self.last[k]=(i,im.convert('RGBA'))
        return self.last[k][1]

def fit(image,w,h,mode):
    if mode=='cover':return ImageOps.fit(image,(w,h),Image.Resampling.BICUBIC)
    tile=Image.new('RGBA',(w,h));im=ImageOps.contain(image,(w,h),Image.Resampling.LANCZOS);tile.alpha_composite(im,((w-im.width)//2,(h-im.height)//2));return tile

class TexturedSphere:
    """Perspective ray/sphere intersections, UV texture, two area-light approximations.
    Real curved surface; no image rotation pretending to be a 3D object."""
    def __init__(self,texture):self.texture=np.array(texture.convert('RGB').resize((1024,512),Image.Resampling.BICUBIC),dtype=np.float32)/255
    def render(self,w,h,angle,roughness=.38):
        # Bound internal resolution to keep many layers affordable.
        factor=min(1.,400/max(w,h));ww=max(2,round(w*factor));hh=max(2,round(h*factor));y,x=np.mgrid[:hh,:ww].astype(np.float32);s=min(ww,hh)*.49
        dx=(x-(ww-1)/2)/s;dy=-(y-(hh-1)/2)/s
        # Camera at z=3; image plane z=0, ray aimed through screen pixel.
        ray=np.stack([dx*1.18,dy*1.18,np.full_like(dx,-3)],axis=-1);ray/=np.linalg.norm(ray,axis=-1,keepdims=True)
        b=3*ray[...,2];disc=b*b-8;mask=disc>=0;t=-b-np.sqrt(np.maximum(0,disc));n=ray*t[...,None];n[...,2]+=3
        u=(np.arctan2(n[...,0],n[...,2])/(2*np.pi)+.5+angle/(2*np.pi))%1;v=np.arccos(np.clip(n[...,1],-1,1))/np.pi
        # Bilinear texture interpolation, periodic horizontal seam.
        tx=u*1024;ty=v*511;ix=np.floor(tx).astype(int)%1024;iy=np.minimum(510,np.floor(ty).astype(int));fx=(tx-np.floor(tx))[...,None];fy=(ty-iy)[...,None]
        tex=self.texture;rgb=(tex[iy,ix]*(1-fx)+tex[iy,(ix+1)%1024]*fx)*(1-fy)+(tex[iy+1,ix]*(1-fx)+tex[iy+1,(ix+1)%1024]*fx)*fy;rgb=rgb**2.2
        lit=rgb*.15
        for vec,col in [((-0.55,.7,.65),(1.5,1.14,.82)),((.8,.2,.3),(.35,.65,1.1))]:
            l=np.asarray(vec,np.float32);l/=np.linalg.norm(l);nl=np.maximum(0,n@l);half=l-ray;half/=np.maximum(1e-6,np.linalg.norm(half,axis=-1,keepdims=True));nh=np.maximum(0,np.sum(n*half,axis=-1));spec=(nh**(4+100*(1-roughness)**2))*.28*nl
            lit+=(rgb*nl[...,None]+spec[...,None])*np.asarray(col,np.float32)
        rgb=(np.clip(lit/(1+.25*lit),0,1)**(1/2.2)*255).astype(np.uint8);alpha=np.where(mask,255,0).astype(np.uint8)
        return Image.fromarray(np.dstack([rgb,alpha]),'RGBA').resize((w,h),Image.Resampling.BICUBIC)

def bind_uploads(chapters,suffixes,actual=None):
    """Creator's upload_index is an ordered attachment reference, never a path.
    Preflight substitutes temporary safe identifiers; after import the caller
    supplies the actual returned asset IDs and validates the complete script.
    """
    import copy
    rows=copy.deepcopy(chapters)
    for ch in rows:
        if not isinstance(ch,dict):continue
        g=ch.get('graphic')
        if not isinstance(g,dict) or g.get('kind')!='composition':continue
        ls=g.get('layers')
        if not isinstance(ls,list):continue
        for l in ls:
            if not isinstance(l,dict) or l.get('type') not in KINDS:continue
            i=l.pop('upload_index',None)
            if type(i) is not int or not 0<=i<len(suffixes) or 'asset' in l:raise ValueError('Creator media layer requires one valid upload_index')
            l['asset']=asset_id(actual[i] if actual is not None else f'{i:032x}{suffixes[i]}',l['type'])
    return rows
