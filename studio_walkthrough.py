"""Plugin-agnostic walkthrough direction. Real recordings are preferred.
Captured state replays preserve original pixels; overlays are explicitly editorial.
"""
from __future__ import annotations
import math
import re
import hashlib
import subprocess
from uuid import uuid4
import studio_performance as perf
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageChops
import numpy as np

ROLES={'auto','plugin_state','plugin_recording','broll','document'}
TRANSITIONS={'auto','dissolve','slide','wipe','cut'}
CAPTIONS={'karaoke','word','clean','off'}
VOICE={'natural','present','off'}
MAX_CAPTURE_SECONDS=60


def metadata(role='auto', group='', order=0, focus_x=None, focus_y=None, trim_start=0., trim_end=0.):
    if role not in ROLES: raise ValueError('Unknown asset role')
    group=' '.join(str(group).split())[:64]
    if not math.isfinite(float(order)) or not 0<=int(order)<=999: raise ValueError('Invalid state order')
    if (focus_x is None)!=(focus_y is None): raise ValueError('Both focus coordinates are required')
    focus=None if focus_x is None else [float(focus_x),float(focus_y)]
    if focus and not all(math.isfinite(v) and 0<=v<=1 for v in focus): raise ValueError('Focus must be inside the screenshot')
    start,end=float(trim_start),float(trim_end)
    if not all(math.isfinite(v) and 0<=v<=3600 for v in (start,end)) or (end and end<=start): raise ValueError('Invalid recording trim')
    return {'role':role,'group':group,'order':int(order),'focus_point':focus,'trim_start':start,'trim_end':end}


def content_digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def is_plugin_asset(asset):
    return not asset.get('source') and asset.get('role','auto') not in ('broll','document')


def choose_recording(assets, words, term_fn, used):
    """Never promote an arbitrary B-roll video to a real recording."""
    pool=[a for a in assets if is_plugin_asset(a) and a['kind']=='video' and a.get('role')=='plugin_recording']
    if not pool:return None
    scored=[(len(term_fn(words)&term_fn(a['name']+' '+a.get('description',''))),-used.count(a['id']),a['id'],a) for a in pool]
    best=max(scored,key=lambda v:v[:3]);return best[3] if best[0]>0 else None


def recording_window(asset, length, uses):
    duration=float((asset.get('features') or {}).get('duration',0) or 0)
    start=max(0.,float(asset.get('trim_start',0) or 0));end=float(asset.get('trim_end',0) or duration)
    if duration>0:end=min(end,duration);start=min(start,max(0,end-.05))
    if end<=start:return start, max(.05,length)
    span=end-start;offset=min(max(0.,span-min(length,span)),uses*length)
    return round(start+offset,6),round(min(length,max(.05,end-start-offset)),6)


def pair_for(asset, assets):
    if not asset or asset.get('role')!='plugin_state' or not asset.get('group'):return None
    same=sorted([a for a in assets if a.get('role')=='plugin_state' and a['kind']=='image' and a.get('group')==asset['group'] and a['id']!=asset['id']],key=lambda a:(a.get('order',0),a['id']))
    prior=[a for a in same if a.get('order',0)<asset.get('order',0)]
    return prior[-1] if prior else None


def state_focus(before, after):
    """Infer a localized changed region; refuse diffuse or incompatible changes."""
    a=ImageOps.exif_transpose(before).convert('RGB');b=ImageOps.exif_transpose(after).convert('RGB')
    if abs(a.width/a.height-b.width/b.height)>.04:return None
    a=a.resize((160,160),Image.Resampling.BILINEAR);b=b.resize((160,160),Image.Resampling.BILINEAR)
    diff=np.max(np.abs(np.asarray(a,dtype=np.int16)-np.asarray(b,dtype=np.int16)),axis=2)
    # Strong pixels only; ignore anti-aliasing and compression noise.
    mask=diff>35;fraction=float(mask.mean())
    if fraction<.00025 or fraction>.28:return None
    ys,xs=np.where(mask); weights=diff[ys,xs].astype(float)
    # Weighted block peak rejects a dispersed text or skin change.
    hist=np.zeros((10,10));np.add.at(hist,(ys//16,xs//16),weights)
    cy,cx=np.unravel_index(np.argmax(hist),hist.shape)
    near=(abs(xs//16-cx)<=1)&(abs(ys//16-cy)<=1)
    if weights[near].sum()<weights.sum()*.42:return None
    return [round(float(np.average(xs[near],weights=weights[near]))/159,3),round(float(np.average(ys[near],weights=weights[near]))/159,3)]


def smooth(x):
    x=max(0.,min(1.,x));return x*x*(3-2*x)


def panel_geometry(w,h,iw,ih):
    wide=w/h>=1.5
    aw,ah=(w*.59,h*.77) if wide else (w*.92,h*.65)
    s=min(aw/iw,ah/ih);tw,th=max(1,round(iw*s)),max(1,round(ih*s))
    return round(w*(.71 if wide else .5)-tw/2),round(h*.435-th/2),tw,th


def replay_hit(duration):
    return min(1.35,duration*.42)


def replay_frames(scene, before_path, after_path, background, folder, fps, check_cancel):
    """Animate a guide pointer over original screenshots, switching only to a real captured state.
    Static pixels are never synthesized into fake control values. Bounded 12fps source.
    """
    with Image.open(after_path) as im:after=ImageOps.exif_transpose(im).convert('RGB')
    before=None
    if before_path:
        with Image.open(before_path) as im:before=ImageOps.exif_transpose(im).convert('RGB')
        if abs(before.width/before.height-after.width/after.height)>.04:before=None
    focus=scene.get('focus_point') or (state_focus(before,after) if before else None)
    if focus is None: return None
    w,h=background.size;x,y,tw,th=panel_geometry(w,h,after.width,after.height)
    a=(before or after).resize((tw,th),Image.Resampling.LANCZOS);b=after.resize((tw,th),Image.Resampling.LANCZOS)
    canvas=background.copy();folder.mkdir(exist_ok=True)
    fps0=min(fps,12);duration=scene['frames']/fps;n=max(1,math.ceil(duration*fps0));hit=replay_hit(duration);approach=max(.06,hit-.5)
    cx=x+focus[0]*tw;cy=y+focus[1]*th;scale=max(.65,h/720)
    label='CAPTURED UI · EDITORIAL FOCUS'
    try:font=ImageFont.truetype('DejaVuSans-Bold.ttf',max(12,round(h*.024)))
    except OSError:font=ImageFont.truetype(r'C:\Windows\Fonts\arialbd.ttf',max(12,round(h*.024))) if Path(r'C:\Windows\Fonts\arialbd.ttf').exists() else ImageFont.load_default(size=max(12,round(h*.024)))
    for i in range(n):
        if i%6==0:check_cancel()
        t=i/fps0;im=canvas.copy();im.paste(a if before and t<hit else b,(x,y));d=ImageDraw.Draw(im)
        if before:label='GUIDED REPLAY · BEFORE' if t<hit else 'GUIDED REPLAY · AFTER'
        # Short label outside the actual plugin, and animated pointer/halo.
        d.rounded_rectangle((max(4,x),max(4,y-round(h*.046)),min(w-4,x+int(d.textlength(label,font=font))+18),max(20,y-3)),radius=4,fill='#101b15')
        d.text((max(8,x+7),max(6,y-round(h*.043))),label,font=font,fill='#a0f58c')
        q=smooth((t-approach)/max(.06,hit-approach));px=cx+(min(tw*.18,80*scale))*(1-q);py=cy+min(th*.18,60*scale)*(1-q)
        if t<hit+.75:
            if t>=approach:
                d.polygon([(px,py),(px,py+22*scale),(px+6*scale,py+16*scale),(px+12*scale,py+27*scale),(px+17*scale,py+24*scale),(px+10*scale,py+13*scale),(px+22*scale,py+13*scale)],fill='#f2f8ef',outline='#101511',width=max(1,round(scale*2)))
            if hit<=t<hit+.5:
                q2=(t-hit)/.5;r=(12+24*q2)*scale;d.ellipse((cx-r,cy-r,cx+r,cy+r),outline='#a0f58c',width=max(2,round(3*scale)))
        im.save(folder/f'{i:05d}.jpg',quality=93,subsampling=0)
    return fps0


def caption_vtt(plan,target):
    def clock(t):
        ms=max(0,round(float(t)*1000));return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d}.{ms%1000:03d}'
    lines=['WEBVTT',''];last=0.
    caption_scenes=[{'start':0.,'captions':plan['caption_track']}] if plan.get('caption_style')=='marker' and plan.get('caption_track') is not None else plan['scenes']
    for scene in caption_scenes:
        for row in scene.get('captions',[]):
            a=max(last,float(scene['start'])+float(row['start']));b=min(float(plan['duration']),float(scene['start'])+float(row['end']))
            if b<=a:continue
            text=str(row['text']).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\r',' ').replace('\n',' ')
            lines.extend([f'{clock(a)} --> {clock(b)}',text,'']);last=b
    target.write_text('\n'.join(lines),encoding='utf-8')


def repair_recording_container(path, probe):
    """MediaRecorder WebM may omit duration; remux streams, never re-encode pixels.
    Only called on a newly staged user upload, bounded to one minute plus a margin.
    """
    info=probe(path)
    if info.get('duration',0)>0 or path.suffix!='.webm' or not info.get('has_video'):return info
    stage=path.with_name('.capture-'+uuid4().hex+'.webm')
    try:
        proc=subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(path),'-map','0:v:0','-an','-t','61','-c:v','copy',str(stage)],capture_output=True,timeout=35,**perf.windows_child_options(True))
        if proc.returncode or not stage.is_file():raise ValueError('Screen recording could not be finalized')
        fixed=probe(stage)
        if not fixed.get('has_video') or not 0<fixed.get('duration',0)<=61.2:raise ValueError('Invalid screen recording duration')
        perf.publish_staged_file(stage,path);return fixed
    finally:stage.unlink(missing_ok=True)


def valid_scene_clip(path, seconds, fps, probe):
    if not path.is_file() or path.is_symlink() or path.stat().st_size<=1024:return False
    try:
        info=probe(path)
        return bool(info.get('has_video') and not info.get('has_audio') and abs(float(info.get('duration',0))-seconds)<=max(.05,1.1/fps))
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):return False


def reconcile_words(tokens, words):
    """Only preserve timing when normalized character stream is identical.
    Merged/split tokens use the matching character intervals; semantic edits still reflow.
    """
    def norm(v):return ''.join(ch for ch in str(v).casefold() if ch.isalnum())
    if not words or len(words)>150 or not all(isinstance(w,dict) and isinstance(w.get('text'),str) for w in words):return []
    a=[norm(w['text']) for w in words];b=[norm(t) for t in tokens]
    if not all(a) or not all(b) or ''.join(a)!=''.join(b):return []
    timing=[]
    try:
        for item,part in zip(words,a):
            start,end=float(item['start']),float(item['end'])
            if not math.isfinite(start) or not math.isfinite(end) or end<start:return []
            for i in range(len(part)): timing.append((start+(end-start)*i/len(part),start+(end-start)*(i+1)/len(part)))
    except (TypeError,ValueError,KeyError):return []
    pos=0;out=[]
    for token,part in zip(tokens,b):
        out.append({'text':token,'start':timing[pos][0],'end':timing[pos+len(part)-1][1]});pos+=len(part)
    return out

CAPTIONS.update({'marker','auto'})
