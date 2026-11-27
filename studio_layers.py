"""Bounded, deterministic editorial composition graph. Positions are normalized.
The only scientific primitives are authored illustrative signals; no inferred facts.
Independent layer clocks, depth ordering, camera parallax and shadowed planes.
"""
from __future__ import annotations
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import studio_media_layers as media
REVISION=11
KINDS={'text','wave','samples','spectrum','particles','paper','line','rings','surface','decay_trace','fluid','additive','light_waves','light_channels','optical_glass','optical_metal','time_orbit','time_samples','time_trajectory','ray_scene','fluid_obstacle','frequency_pair'} | media.KINDS
COLORS={'white':'#f2eee3','gold':'#efce77','mint':'#7ed7c2','muted':'#9caaa9','ink':'#1d2426','blue':'#7fa6de'}

def number(x,lo,hi):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or not lo<=x<=hi:raise ValueError('Invalid composition number')
    return float(x)

def string(x,n):
    if not isinstance(x,str) or not x.strip() or len(x)>n:raise ValueError('Invalid composition text')
    return x.strip()

def track(v,limits):
    if not isinstance(v,list) or not 1<=len(v)<=24:raise ValueError('Invalid keyframe track')
    out=[]
    for row in v:
        if not isinstance(row,(list,tuple)) or len(row)!=len(limits)+1:raise ValueError('Invalid keyframe')
        t=number(row[0],0,1)
        if out and t<=out[-1][0]:raise ValueError('Keyframes must be strictly ordered')
        out.append([t,*[number(x,*lim) for x,lim in zip(row[1:],limits)]])
    return out

def validate(spec):
    if not isinstance(spec,dict):raise ValueError('Invalid composition')
    layers=spec.get('layers');out={'kind':'composition','title':string(spec.get('title'),100),'source':string(spec.get('source'),140)}
    if not isinstance(layers,list) or not 1<=len(layers)<=32:raise ValueError('Composition needs 1–32 layers')
    out['camera']=track(spec.get('camera',[[0,0,0,1],[1,0,0,1]]),[(-.35,.35),(-.35,.35),(.65,1.6)])
    out['layers']=[];ids=set()
    for l in layers:
        if not isinstance(l,dict) or not isinstance(l.get('type'),str) or l.get('type') not in KINDS:raise ValueError('Unknown composition layer')
        ident=string(l.get('id'),48)
        if ident in ids:raise ValueError('Duplicate layer id')
        ids.add(ident);kind=l['type'];color=l.get('color','white')
        if not isinstance(color,str) or color not in COLORS:raise ValueError('Unknown layer color')
        row={'id':ident,'type':kind,'color':color,'depth':number(l.get('depth',0),-1,2),'width':number(l.get('width',.7),.04,1.5),'height':number(l.get('height',.2),.025,.8),'track':track(l.get('track',[[0,.5,.5,1,1]]),[(-.7,1.7),(-.7,1.7),(.1,3),(0,1)])}
        if kind in media.KINDS:
            row['asset']=media.asset_id(l.get('asset'),kind)
            row['fit']=l.get('fit','contain')
            if row['fit'] not in ('contain','cover'):raise ValueError('Invalid media fit')
            if kind=='footage':
                trim=l.get('trim');
                if not isinstance(trim,(list,tuple)) or len(trim)!=2:raise ValueError('Footage needs explicit trim')
                a,b=[number(x,0,1800) for x in trim]
                if not 0<b-a<=20:raise ValueError('Footage strip must be 0–20 seconds')
                row['trim']=[a,b];row['delay']=number(l.get('delay',0),0,120)
            if kind in ('sphere','mesh'):
                row['spin']=number(l.get('spin',.5),-2,2);row['roughness']=number(l.get('roughness',.38),.1,1)
        if kind=='mesh':
            from studio_mesh import validate_mesh
            row['mesh']=validate_mesh(l.get('mesh'));row['metal']=number(l.get('metal',.35),0,1)
            row['morph']=track(l.get('morph',[[0,0],[1,1]]),[(0,1)])
            row['shutter']=number(l.get('shutter',0),0,.04)
        if 'curve' in l:
            row['curve']=l['curve']
            if row['curve'] not in ('smooth','linear','continuous'):raise ValueError('Invalid animation curve')
        if kind in ('text','paper'):
            row['text']=string(l.get('text'),240)
            if kind=='paper':row['label']=string(l.get('label'),80)
            else:
                row['size']=number(l.get('size',.07),.02,.16)
                row['face']=l.get('face','sans');row['align']=l.get('align','center')
                if row['face'] not in ('sans','serif','mono') or row['align'] not in ('center','left'):raise ValueError('Invalid typography')
        if kind in ('wave','samples','particles','rings','surface'):
            row['harmonics']=number(l.get('harmonics',0),0,1)
        if kind in ('fluid','fluid_obstacle'):
            seed=l.get('seed',7)
            if type(seed) is not int or not 0<=seed<2**31:raise ValueError('Invalid fluid seed')
            row['seed']=seed
        if kind=='decay_trace':
            from studio_signal_story import validate_trace
            row['points']=validate_trace(l.get('points'));row['trace_delay']=number(l.get('trace_delay',0),0,120);row['trace_seconds']=number(l.get('trace_seconds',max(.02,row['points'][-1][0])),.02,120)
        if kind=='spectrum':
            values=l.get('values')
            if not isinstance(values,list) or not 2<=len(values)<=8:raise ValueError('Spectrum needs 2–8 supplied values')
            row['values']=[{'label':string(x.get('label'),16),'value':number(x.get('value'),0,1)} for x in values if isinstance(x,dict)]
            if len(row['values'])!=len(values) or not any(x['value']>0 for x in row['values']):raise ValueError('Invalid spectrum values')
        out['layers'].append(row)
    if sum(l['type']=='footage' for l in out['layers'])>3:raise ValueError('At most three footage layers per composition')
    return out

def ease(x):
    x=max(0.,min(1.,x));return x*x*x*(10+x*(-15+6*x))

def sample(keys,t,curve="smooth"):
    if t<=keys[0][0]:return keys[0][1:]
    for i,(a,b) in enumerate(zip(keys,keys[1:])):
        if t<=b[0]:
            u=(t-a[0])/(b[0]-a[0]);p=u if curve=='linear' else ease(u)
            if curve=='continuous':
                # Monotone cubic Hermite, tangent limiting prevents overshoot.
                prev=keys[max(0,i-1)];nxt=keys[min(len(keys)-1,i+2)];out=[];dt=b[0]-a[0]
                for k,(x,y) in enumerate(zip(a[1:],b[1:]),1):
                    d=(y-x)/dt;m0=(y-prev[k])/(b[0]-prev[0]);m1=(nxt[k]-x)/(nxt[0]-a[0]);m0=0 if d*m0<=0 else math.copysign(min(abs(m0),1.5*abs(d)),d);m1=0 if d*m1<=0 else math.copysign(min(abs(m1),1.5*abs(d)),d)
                    out.append((2*u**3-3*u*u+1)*x+(u**3-2*u*u+u)*dt*m0+(-2*u**3+3*u*u)*y+(u**3-u*u)*dt*m1)
                return out
            return [x+(y-x)*p for x,y in zip(a[1:],b[1:])]
    return keys[-1][1:]

def _fontfit(font,text,size,width):
    size=max(10,int(size));f=font(size,True)
    while size>10 and f.getlength(text)>width:size-=1;f=font(size,True)
    return f

def _lines(font,content,size,width,maxlines=5):
    f=font(max(10,int(size)),True);out=[];line=''
    for word in content.split():
        trial=(line+' '+word).strip()
        if line and f.getlength(trial)>width:out.append(line);line=word
        else:line=trial
    if line:out.append(line)
    if len(out)>maxlines:return _lines(font,content,size*.82,width,maxlines) if size>11 else (f,out[:maxlines])
    return f,out

def atmosphere(w,h):
    """Low-resolution analytic single-scattering approximation through two beams.
    Integrated along view rays; not path traced. No per-frame noise flicker."""
    sw,sh=max(80,w//4),max(60,h//4);y,x=np.mgrid[0:1:complex(sh),0:1:complex(sw)];rgb=np.zeros((sh,sw,3),np.float32);rgb[:]=[6,10,15]
    for z in np.linspace(.15,1.8,16):
        # widening beam cones, exponential distance attenuation
        a=np.exp(-((x-(.09+.23*y+.035*z))**2)/( .002+.008*z))*np.exp(-((y-.44)**2)/.38)*math.exp(-z*1.15)
        b=np.exp(-((x-(.96-.30*y-.045*z))**2)/(.002+.011*z))*np.exp(-((y-.32)**2)/.31)*math.exp(-z*1.4)
        rgb+=a[...,None]*np.array([3.4,2.4,1.15])+b[...,None]*np.array([.75,2.5,3.5])
    floor=np.clip((y-.60)/.40,0,1);rgb+=floor[...,None]*[4,6,7];rgb*=np.clip(1-.75*((x-.5)**2+(y-.5)**2),.6,1)[...,None]
    return Image.fromarray(np.uint8(np.clip(rgb,0,255))).resize((w,h),Image.Resampling.BICUBIC)

class Composition:
    def __init__(self,spec,w,h,duration,font,offset=0.,media_bank=None):
        self.spec=validate(spec);self.w=w;self.h=h;self.duration=max(.1,duration);self.font=__import__("functools").lru_cache(maxsize=128)(font);self.bg=atmosphere(w,h);self.offset=offset
        self.layers=sorted(self.spec['layers'],key=lambda l:-l['depth']);self.media_bank=media_bank;self.spheres={};self.meshes={};self.fluids={};self.static_tiles={};self.static_projections={}
        if any(l['type'] in media.KINDS for l in self.layers) and media_bank is None:raise ValueError('Media layers require an asset registry')
    def _tile(self,l,ww,hh,t):
        im=Image.new('RGBA',(ww,hh));d=ImageDraw.Draw(im);kind=l['type'];c=COLORS[l['color']];f=self.font
        if kind in ('wave','samples','particles','rings','surface'):t+=self.offset
        if kind in media.KINDS:
            if kind=='mesh':
                from studio_mesh import Mesh
                key=l['id']+str(hash(str(l['mesh'])))+l['asset']
                if key not in self.meshes:self.meshes[key]=Mesh(l['mesh'],self.media_bank.image(l['asset']))
                renderer=self.meshes[key];shutter=l['shutter'];times=[t] if not shutter else [t-shutter/2,t,t+shutter/2];tiles=[]
                for at in times:
                    q=sample(l['morph'],max(0,min(1,at/self.duration)),l.get('curve','smooth'))[0]
                    tiles.append(renderer.render(ww,hh,(at+self.offset)*l['spin'],q,l['roughness'],l['metal']))
                if len(tiles)==1:return tiles[0]
                # Accumulate premultiplied RGBA to avoid dark transparent edges.
                a=np.stack([np.asarray(x,dtype=np.float32)/255 for x in tiles]);alpha=a[...,3:4];rgb=(a[...,:3]*alpha).mean(0)/np.maximum(1e-8,alpha.mean(0));return Image.fromarray(np.uint8(np.clip(np.concatenate([rgb,alpha.mean(0)],axis=-1),0,1)*255+.5))
            if kind=='sphere':
                if l['asset'] not in self.spheres:self.spheres[l['asset']]=media.TexturedSphere(self.media_bank.image(l['asset']))
                return self.spheres[l['asset']].render(ww,hh,(t+self.offset)*l['spin'],l['roughness'])
            return media.fit(self.media_bank.frame(l,t),ww,hh,l['fit'])
        if kind=='text':
            if l['face']!='sans':
                def f(size,bold):
                    for name in (('DejaVuSerif.ttf',r'C:\Windows\Fonts\georgia.ttf','LiberationSerif-Regular.ttf') if l['face']=='serif' else ('DejaVuSansMono.ttf',r'C:\Windows\Fonts\consola.ttf','LiberationMono-Regular.ttf')):
                        try:return ImageFont.truetype(name,size)
                        except OSError:pass
                    return self.font(size,bold)
            size=self.h*l['size']*ww/max(1,self.w*l['width'])
            face,lines=_lines(f,l['text'],size,ww*.94)
            while face.size>10 and (len(lines)*face.size*1.22>hh*.96 or any(face.getlength(line)>ww*.94 for line in lines)):
                size=face.size-1;face,lines=_lines(f,l['text'],size,ww*.94)
            dy=face.size*1.22;y=(hh-len(lines)*dy)/2
            for s in lines:
                d.text((ww/2 if l['align']=='center' else ww*.025,y+dy/2),s,font=face,fill=c,anchor='mm' if l['align']=='center' else 'lm');y+=dy
        elif kind=='paper':
            pad=max(4,int(min(ww*.05,hh*.09)));d.rounded_rectangle((1,1,ww-2,hh-2),radius=max(3,ww//50),fill='#e8e5d9',outline='#fcf8ea',width=1)
            face=_fontfit(f,l['label'],min(hh*.18,ww*.065),ww-2*pad);d.text((pad,pad),l['label'],font=face,fill='#626866');y=pad+face.size*1.45;d.line((pad,y,ww-pad,y),fill='#929b96',width=1)
            face,lines=_lines(f,l['text'],min(hh*.28,ww*.10),ww-2*pad,4);y+=pad*.75
            for s in lines:
                if y+face.size>hh-pad:break
                d.text((pad,y),s,font=face,fill='#152627');y+=face.size*1.2
        elif kind in ('wave','samples'):
            x=np.linspace(.035,.965,180);p=2*np.pi*3*x-t*2.3;signal=(np.sin(p)+l['harmonics']*(.5*np.sin(2*p)+.25*np.sin(3*p)))/(1+.75*l['harmonics'])
            pts=list(zip(x*ww,hh*(.5-.38*signal)));d.line((0,hh/2,ww,hh/2),fill='#34454a',width=max(2,hh//200))
            for i in range(1,12):d.line((ww*i/12,0,ww*i/12,hh),fill='#253339',width=max(2,hh//200))
            if kind=='wave':
                d.line(pts,fill=c,width=max(2,hh//70),joint='curve')
            else:
                d.line(pts,fill='#506b70',width=max(2,hh//200))
                for i in range(0,len(pts),6):
                    a,b=pts[i];r=max(2,hh*.025);d.line((a,hh/2,a,b),fill=c,width=1);d.ellipse((a-r,b-r,a+r,b+r),fill=c)
        elif kind in ('optical_glass','optical_metal','time_orbit','time_samples','time_trajectory'):
            from studio_optics import render,orbit,timeline,trajectory
            if kind=='time_orbit':return orbit(ww,hh,t+self.offset,f)
            if kind=='time_trajectory':return trajectory(ww,hh,t+self.offset,f)
            if kind=='time_samples':return timeline(ww,hh,t+self.offset,f)
            return render(ww,hh,t+self.offset,glass=kind=='optical_glass')
        elif kind=='frequency_pair':
            from studio_frequency import pair
            return pair(ww,hh,t+self.offset,f)
        elif kind=='ray_scene':
            from studio_ray_scene import render
            return render(ww,hh,t+self.offset)
        elif kind in ('fluid','fluid_obstacle'):
            from studio_fluid import Fluid
            key=(l['seed'],kind)
            if key not in self.fluids:self.fluids[key]=Fluid(l['seed'],obstacle=kind=='fluid_obstacle')
            return self.fluids[key].render(ww,hh,t)
        elif kind=='additive':
            from studio_fluid import light_study
            return light_study(ww,hh,t/self.duration)
        elif kind in ('light_waves','light_channels'):
            from studio_color_light import wave_bands,channel_mixer
            return wave_bands(ww,hh,t,f) if kind=='light_waves' else channel_mixer(ww,hh,t/self.duration,f)
        elif kind=='decay_trace':
            from studio_signal_story import draw_trace
            return draw_trace(ww,hh,l['points'],(t-l['trace_delay'])/l['trace_seconds'],f,c)
        elif kind=='surface':
            # A projected 3D wave mesh with depth fading. It is an illustration,
            # not a fluid simulation; all vertices move on a continuous clock.
            xs=np.linspace(-1.55,1.55,70);zs=np.linspace(0,2.4,15);xx,zz=np.meshgrid(xs,zs)
            yy=.30*np.sin(4.8*xx-2.2*t+.9*zz)*np.exp(-.18*zz)
            # Camera at elevated position, perspective projection onto image.
            depth=3.5+zz*.82-yy*.33;px=ww*.5+xx/depth*ww*.94;py=hh*.60-(yy*.92+zz*.40)/depth*hh*2.1
            for j in reversed(range(len(zs))):
                a=int(82+150*(1-j/(len(zs)-1)));rgb=tuple(int(x) for x in bytes.fromhex(c[1:]));pts=list(zip(px[j],py[j]));d.line(pts,fill=(*rgb,a),width=max(1,hh//120))
            for j in range(0,len(xs),6):
                d.line(list(zip(px[:,j],py[:,j])),fill=(125,167,169,100),width=max(2,hh//240))
        elif kind=='particles':
            # Lagrangian particle displacement, with fixed identities and local motion.
            for row in range(7):
                for col in range(34):
                    q=(col+.5)/34;x=ww*(q+.014*math.sin(2*math.pi*3*q-t*2.2));y=hh*(.13+row*.123)+math.sin(row*2+col*.7)*hh*.012
                    r=max(1,hh*.009)*(1+.32*math.sin(col*.7-t*2.2));d.ellipse((x-r,y-r,x+r,y+r),fill=c if (col+row)%3 else '#c4e7dc')
        elif kind=='rings':
            for i in range(6):
                p=(i/6+t*.18)%1;r=hh*(.075+.40*p);a=int(210*(1-p));d.ellipse((ww/2-r,hh/2-r,ww/2+r,hh/2+r),outline=(*bytes.fromhex(c[1:]),a),width=max(1,hh//100))
        elif kind=='line':d.line((0,hh/2,ww,hh/2),fill=c,width=max(1,hh//4))
        elif kind=='spectrum':
            n=len(l['values']);base=hh*.78;d.line((0,base,ww,base),fill='#58716d',width=1);p=1.0
            for i,row in enumerate(l['values']):
                x=ww*(i+.5)/n;bh=hh*.68*row['value']*p;bw=ww*.25/n;d.rounded_rectangle((x-bw,base-bh,x+bw,base),radius=max(1,int(bw*.20)),fill=c if i==0 else '#7aa9bb')
                face=_fontfit(f,row['label'],hh*.09,ww*.92/n);d.text((x,base+hh*.055),row['label'],font=face,fill='#e4e5df',anchor='mt')
        return im
    def _states(self,t):
        u=max(0,min(1,t/self.duration));cx,cy,zoom=sample(self.spec['camera'],u);states={}
        for l in self.layers:
            x,y,s,a=sample(l['track'],u,l.get('curve','smooth'));z=l['depth'];pers=1/(1+.24*z);scale=s*zoom*pers
            states[l['id']]=(l,[.5+(x-.5-cx*pers)*zoom,.5+(y-.5-cy*pers)*zoom,scale,a,z],t)
        return states
    def _draw(self,states,source):
        from studio_subpixel import composite, project, raster_size
        w,h=self.w,self.h;im=self.bg.copy().convert('RGBA')
        for l,(x,y,scale,a,z),t in sorted(states,key=lambda row:-row[1][4]):
            if a<.002:continue
            ww=max(2.,min(w*2.,w*l['width']*scale));hh=max(2.,min(h*2.,h*l['height']*scale));px=w*x-ww/2;py=h*y-hh/2
            # The source raster is invariant over the animation. Layout, wrapping,
            # font hinting and texture dimensions never depend on fractional scale.
            rw,rh=raster_size(w*l['width'],h*l['height'],l['type'])
            if l['type'] in ('text','paper','line','spectrum'):
                key=(str(l),rw,rh)
                if key not in self.static_tiles:
                    if len(self.static_tiles)>=64:self.static_tiles.pop(next(iter(self.static_tiles)))
                    self.static_tiles[key]=self._tile(l,rw,rh,t)
                tile=self.static_tiles[key]
            else:tile=self._tile(l,rw,rh,t)
            if l['type'] in ('sphere','mesh'):
                sw=max(8,round(min(ww,hh)*.76));sh=max(4,round(sw*.18));shade=Image.new('RGBA',(sw+20,sh+20));sd=ImageDraw.Draw(shade);sd.ellipse((10,10,sw+10,sh+10),fill=(0,0,0,round(a*155)));shade=shade.filter(ImageFilter.GaussianBlur(9));composite(im,shade,w*x-sw/2-10,h*y+min(ww,hh)*.41-sh/2-10,sw+20,sh+20)
            if l['type'] in ('paper','document','image','footage'):
                pad=max(4,round(h*.017));sw,sh=round(ww),round(hh);shadow=Image.new('RGBA',(sw+pad*2,sh+pad*2));sd=ImageDraw.Draw(shadow);sd.rounded_rectangle((pad,pad,sw+pad,sh+pad),radius=8,fill=(0,0,0,round(a*145)));shadow=shadow.filter(ImageFilter.GaussianBlur(pad*.55));composite(im,shadow,px-pad/2,py+pad/2,ww+pad*2,hh+pad*2)
            if l['type'] in ('text','paper','line','spectrum'):
                # On a hold, reuse the already resampled tile. During motion the
                # fractional transform remains continuous, without snapped keys.
                geometry=(px,py,ww,hh,a);entry=self.static_projections.get(key)
                if entry is None or entry[0]!=geometry:
                    if key not in self.static_projections and len(self.static_projections)>=64:self.static_projections.pop(next(iter(self.static_projections)))
                    entry=(geometry,project(im,tile,px,py,ww,hh,a));self.static_projections[key]=entry
                if entry[1] is not None:im.alpha_composite(*entry[1])
            else:composite(im,tile,px,py,ww,hh,a)
        d=ImageDraw.Draw(im);face=self.font(max(10,round(h*.024)),False)
        d.text((round(w*.055),round(h*.94)),source,font=_fontfit(self.font,source,face.size,w*.9),fill='#9ba9aa',anchor='lb')
        return im.convert('RGB')
    def render(self,t):return self._draw(self._states(t).values(),self.spec['source'])
    def bridge(self,previous,t,seconds):
        """Shared layer identities retain motion; unmatched elements exit/enter.
        No whole-frame swipe. Exact endpoints and stable depth ordering."""
        p=ease(t/max(.001,seconds))
        if p<=0:return previous.render(previous.duration)
        if p>=1:return self.render(t)
        old=previous._states(previous.duration);new=self._states(t);rows=[]
        for key,(l,a,elapsed) in old.items():
            n=new.get(key)
            if n and all(l.get(k)==n[0].get(k) for k in ('type','text','label','values','points','trace_delay','trace_seconds','harmonics','color','width','height','size','asset','trim','delay','fit','spin','roughness','face','align','mesh','morph','metal','shutter','curve','seed')) and l['type']!='footage':
                nl,b,nt=new.pop(key);state=[x+(y-x)*p for x,y in zip(a,b)];rows.append((nl,state,nt))
            else:
                state=a.copy();state[0]-=.035*p;state[3]*=(1-ease(min(1,p*2)) if l['type']=='text' else 1-p);rows.append((l,state,elapsed if l['type']=='footage' else elapsed+previous.offset-self.offset))
        for l,b,nt in new.values():
            state=b.copy();state[0]+=.035*(1-p);state[3]*=(ease(max(0,(p-.5)*2)) if l['type']=='text' else p);rows.append((l,state,nt))
        return self._draw(rows,previous.spec['source'] if p<.5 else self.spec['source'])
