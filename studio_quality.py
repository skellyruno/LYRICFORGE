"""Decoded-frame heuristic review before publishing, not artistic approval."""
from pathlib import Path
import subprocess
import numpy as np

def review_samples(frames,times):
    frames=np.asarray(frames,dtype=np.uint8)
    if frames.ndim!=4 or frames.shape[-1]!=3 or not len(frames) or len(frames)!=len(times):raise ValueError('Invalid quality samples')
    luma=frames.astype(np.float32)@np.array([.2126,.7152,.0722],np.float32)
    avg=luma.mean(axis=(1,2));spread=luma.std(axis=(1,2));issues=[]
    dark=(avg<7)&(spread<4);bright=(avg>248)&(spread<4)
    for i in np.flatnonzero(dark|bright):issues.append({'time':round(float(times[i]),3),'severity':'warning','message':'Near-empty dark frame; inspect intentional fade' if dark[i] else 'Near-empty bright frame; inspect intentional flash'})
    static=float(np.mean(np.abs(frames[1:].astype(np.float32)-frames[:-1]).mean(axis=(1,2,3))<.65)) if len(frames)>2 else 0.
    if static>.8:issues.append({'severity':'warning','message':'Most sampled frames are almost unchanged; verify intentional hold'})
    return {'samples':len(frames),'near_empty':int(np.sum(dark|bright)),'static_pair_fraction':round(static,4),'median_luma':round(float(np.median(avg)),2),'warnings':len(issues),'issues':issues[:30],'basis':'Decoded-frame heuristic review; not a semantic, text-legibility or artistic approval.'}

def review_video(path,duration,check_cancel=lambda:None):
    if not 0<duration<=1800:raise ValueError('Invalid review duration')
    rate=min(2.,240/duration);w,h=160,90;check_cancel()
    p=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(Path(path)),'-an','-vf',f'fps={rate:.9f},scale={w}:{h}', '-frames:v','240','-pix_fmt','rgb24','-f','rawvideo','-threads','1','pipe:1'],capture_output=True,timeout=120,check=True)
    check_cancel();stride=w*h*3
    if not p.stdout or len(p.stdout)%stride:raise RuntimeError('Cannot decode review frames')
    frames=np.frombuffer(p.stdout,dtype=np.uint8).reshape(-1,h,w,3);return review_samples(frames,[(i+.5)/rate for i in range(len(frames))])

def review_layout(plan,size,font):
    """Report probable clipped or overlapping text from actual rendered glyph bounds.
    Samples five points per authored composition, including its end. Non-text
    overlap is intentional editorial composition and is not treated as an error.
    """
    from studio_layers import Composition,validate
    from studio_subpixel import raster_size
    w,h=size;issues=[];checked=0
    for i,scene in enumerate(plan.get('scenes',[])):
        g=scene.get('graphic') or {}
        if g.get('kind')!='composition':continue
        spec=validate(g);seconds=scene['frames']/plan['fps'];seen=set()
        # Use the actual typography renderer; media isn't decoded for this check.
        text_layers=[l for l in spec['layers'] if l['type']=='text']
        if not text_layers:continue
        shot=Composition({**spec,'layers':text_layers},w,h,seconds,font)
        for frac in (.1,.3,.5,.75,1.):
            boxes=[];t=seconds*frac
            for l,(x,y,scale,a,z),_ in shot._states(t).values():
                if a<.5:continue
                ww=max(2.,min(w*2.,w*l['width']*scale));hh=max(2.,min(h*2.,h*l['height']*scale));px=w*x-ww/2;py=h*y-hh/2
                rw,rh=raster_size(w*l['width'],h*l['height'],l['type']);box=shot._tile(l,rw,rh,t).getchannel('A').getbbox();checked+=1
                if not box:continue
                b=(px+box[0]*ww/rw,py+box[1]*hh/rh,px+box[2]*ww/rw,py+box[3]*hh/rh);key=('edge',l['id'])
                if (b[0]<w*.025 or b[2]>w*.975 or b[1]<h*.025 or b[3]>h*.915) and key not in seen:
                    seen.add(key);issues.append({'scene':i+1,'layer':l['id'],'severity':'warning','message':'Visible text reaches outside the conservative title-safe zone'})
                for other,c in boxes:
                    area=max(0,min(b[2],c[2])-max(b[0],c[0]))*max(0,min(b[3],c[3])-max(b[1],c[1]));small=min((b[2]-b[0])*(b[3]-b[1]),(c[2]-c[0])*(c[3]-c[1]));key=('overlap',*sorted([l['id'],other]))
                    if small and area/small>.15 and key not in seen:seen.add(key);issues.append({'scene':i+1,'layer':l['id'],'severity':'warning','message':'Potential text overlap with '+other})
                boxes.append((l['id'],b))
    return {'checked_text_samples':checked,'warnings':len(issues),'issues':issues[:50],'basis':'Actual glyph bounds at representative layer-clock positions; intentional overlaps need review.'}


def repair_layout(plan,size,font,check_cancel=lambda:None):
    """Bounded preflight correction of generated text only. Preserve content,
    media transforms, timeline, opacity, and original authored plans unless opted in.
    Accept only strictly lower warning count. Never hide text to pass a check.
    """
    from copy import deepcopy
    from studio_layers import validate
    records=[];before=after=0
    for index,scene in enumerate(plan.get('scenes',[])):
        if not (plan.get('auto_repair_layout') or scene.get('automatic_collage')):continue
        g=scene.get('graphic') or {}
        if g.get('kind')!='composition':continue
        check_cancel();g=validate(g)
        def review(spec):return review_layout({'fps':plan['fps'],'scenes':[{'graphic':spec,'frames':scene['frames']}]},size,font)
        original=review(g);current=original;before+=original['warnings']
        for _ in range(min(6,original['warnings']+2)):
            if not current['warnings']:break
            best=None
            for ident in dict.fromkeys(x['layer'] for x in current['issues']):
                check_cancel()
                # Try small, constant positional adjustments; preserve motion path.
                for dx,dy,scale in [(0,.045,1),(0,-.045,1),(.045,0,1),(-.045,0,1),(0,.09,1),(0,-.09,1),(.09,0,1),(-.09,0,1),(0,.135,1),(0,-.135,1),(.135,0,1),(-.135,0,1),(0,.18,1),(0,-.18,1),(.18,0,1),(-.18,0,1),(0,0,.90),(.06,0,.90),(-.06,0,.90),(0,-.06,.90),(0,.06,.90)]:
                    trial=deepcopy(g);l=next(x for x in trial['layers'] if x['id']==ident)
                    l['track']=[[t,x+dx,y+dy,s*scale,a] for t,x,y,s,a in l['track']]
                    try:trial=validate(trial)
                    except ValueError:continue
                    result=review(trial);cost=abs(dx)+abs(dy)+(1-scale)*1.5
                    key=(result['warnings'],cost,ident)
                    if result['warnings']<current['warnings'] and (best is None or key<best[0]):best=(key,trial,result,{'scene':index+1,'layer':ident,'dx':dx,'dy':dy,'scale':scale,'before':current['warnings'],'after':result['warnings']})
                if best and best[0][0]==0:break
            if best is None:break
            _,g,current,change=best;records.append(change)
        if current['warnings']<original['warnings']:scene['graphic']=g
        after+=current['warnings']
    return {'before':before,'after':after,'corrections':records,'basis':'Bounded sampled glyph review; does not guarantee all-frame or artistic quality.'}
