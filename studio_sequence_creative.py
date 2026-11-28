"""Bounded measured image/audio features and explainable edit proposals."""
from pathlib import Path
from functools import lru_cache
import re, subprocess, math, os
import numpy as np
import studio_sequence as seq
import studio_timeline as tl
import studio_audio as audio
import studio_beat as beat

@lru_cache(maxsize=80)
def visual_cached(path,size,mtime,duration):
    # Sample a bounded 24-second window at 2 fps, not a semantic vision model.
    p=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-i',path,'-t',str(min(duration,24)),'-an','-vf','fps=2,scale=96:54,format=rgb24','-f','rawvideo','-threads','1','pipe:1'],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
    if p.returncode:raise ValueError('Could not analyze footage')
    raw=np.frombuffer(p.stdout,dtype=np.uint8); count=len(raw)//(96*54*3)
    if not count:raise ValueError('No visual samples')
    rgb=raw[:count*96*54*3].reshape(count,54,96,3).astype(np.float32)/255
    gray=rgb @ np.array([.2126,.7152,.0722],dtype=np.float32)
    edge=np.abs(np.diff(gray,axis=2)).mean(axis=(1,2))+np.abs(np.diff(gray,axis=1)).mean(axis=(1,2))
    motion=np.abs(np.diff(gray,axis=0)).mean(axis=(1,2)) if count>1 else np.array([0.])
    means=gray.mean(axis=(1,2));contrast=gray.std(axis=(1,2));clip=((gray<.025)|(gray>.975)).mean(axis=(1,2))
    # Gradient-weighted center is a composition proxy, not object recognition.
    gx=np.abs(np.diff(gray,axis=2)).mean(axis=(0,1));gy=np.abs(np.diff(gray,axis=1)).mean(axis=(0,2));
    center=[float((gx*np.linspace(0,1,len(gx))).sum()/gx.sum()) if gx.sum()>1e-6 else .5,float((gy*np.linspace(0,1,len(gy))).sum()/gy.sum()) if gy.sum()>1e-6 else .5]
    quality=float(np.clip(.4*(1-clip.mean())+.3*min(1,contrast.mean()/.18)+.3*min(1,edge.mean()/.15),0,1))
    return {'samples':count,'sample_seconds':min(duration,24),'brightness':round(float(means.mean()),3),'contrast':round(float(contrast.mean()),3),'detail':round(float(edge.mean()),3),'motion':round(float(np.median(motion)),3),'clipped':round(float(clip.mean()),3),'focus':[round(v,3) for v in center],'quality':round(quality,3),'scene_changes':[round((i+1)/2,2) for i,v in enumerate(motion) if v>.22], 'sample_quality':[round(float(q),3) for q in (.4*(1-clip)+.3*np.minimum(1,contrast/.18)+.3*np.minimum(1,edge/.15))], 'sample_motion':[0.]+[round(float(v),3) for v in motion[:count-1]]}

def visual(a):return visual_cached(*seq.version(a),float(a['duration']))

@lru_cache(maxsize=30)
def music_cached(path,size,mtime,duration):
    length=min(duration,40.); samples=audio.decode_mono(Path(path),rate=beat.RATE,length=length,timeout=20)
    if not samples:raise ValueError('No audio samples')
    a=beat.analyze(samples,len(samples)/beat.RATE); rms=audio.rms_db(samples)
    return {'bpm':a['bpm'],'confidence':a['confidence'],'beats':a['beats'] if a['confidence']>=beat.LOW_CONFIDENCE else [],'seconds':round(len(samples)/beat.RATE,3),'rms_db':round(rms,2)}

def music(a):return music_cached(*seq.version(a),float(a['duration']))

def suggest(state,assets,words,instruction):
    intent=instruction.casefold();total=state['base']['frames']; suggestions=[]; analyses={};scores=[]
    cinematic=bool(re.search(r'cinematic|film|dramatic|tension|reveal',intent)); tension=bool(re.search(r'tension|reveal|suspense',intent)); energetic=bool(re.search(r'energetic|hype|fast|punch',intent))
    match=re.search(r'(?:reveal|at)\s+(?:at\s+)?('+tl.TIME+r')',intent) if tension else None
    reveal=tl.time_frame(match[1]) if match else None
    if reveal is not None and not 6<reveal<total:reveal=None
    if not cinematic and not energetic and not re.search(r'variety|music|beat|sound',intent):raise ValueError('Supported creative intentions: cinematic, build tension, energetic, visual variety, music or beat sync')
    def add(reason,action):
        row=action.get('layer',{})
        if row.get('kind')=='sfx' and any(x['kind']=='sfx' and x['effect']==row['effect'] and abs(x['at']-row['at'])<5 for x in state['layers']):return
        try:seq.apply(state,action,assets)
        except (ValueError,KeyError):return
        suggestions.append({'reason':reason,'action':action})
    # Only explicit user-designated music assets participate; no online sourcing.
    music_results={}
    for k,a in [(k,a) for k,a in sorted(assets.items()) if a.get('music')][:6]:
        if a.get('music'):
            try:music_results[k]=music(a)
            except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired):continue
    current=next((x for x in state['layers'] if x['kind']=='music'),None);grid=[]
    if current:
        m=music_results.get(current['asset'],{})
        grid=[round(t*30)-current['offset']+current['at'] for t in m.get('beats',[]) if current['offset']<=round(t*30)<current['offset']+current['length']]
    elif music_results:
        target=135 if energetic else 85 if tension else 100
        choices=[(k,m) for k,m in music_results.items() if m['rms_db']>-55]
        if choices:
            k,m=max(choices,key=lambda v:(.4*v[1]['confidence']+.6*max(0,1-abs(v[1]['bpm']-target)/100) if v[1]['confidence']>=.5 else .15,v[0]))
            n=min(total,tl.duration_frames(assets[k]['duration']));f=min(n//3,30)
            add(f'Use local music {k}: measured {m["bpm"]} BPM, confidence {m["confidence"]:.2f}; duck under narration. Tempo is a heuristic, not genre recognition.',{'op':'put','layer':{'id':'creative-music','kind':'music','asset':k,'at':0,'length':n,'gain':.15,'fade_in':f,'fade_out':f,'duck':True}})
    for k,a in [(k,a) for k,a in sorted(assets.items()) if a.get('has_video') and not a.get('music')][:8]:
        if a.get('has_video') and not a.get('music'):
            try:analyses[k]=visual(a)
            except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired):continue
    spoken=tl.remap_words(words,state['base']); regions=[];cursor=0
    existing_ids={x['id'] for x in state['layers']}
    def fresh_id(stem):
        return next((f'{stem}-{n}' for n in range(1,100) if f'{stem}-{n}' not in existing_ids),stem)
    for p in state['base']['pieces']:
        if p['asset']=='source' and p['audio_start']==p['start']:regions.append((cursor,cursor+p['length']))
        cursor+=p['length']
    # Rank actual shot windows, not just filename tags. Prefer a phrase boundary
    # and a confident beat when they fit, but never slide an existing layer.
    occupied=[(x['at'],x['at']+x['length']) for x in state['layers'] if x['kind']=='visual']
    for k,v in analyses.items():
        if k=='source':continue
        n=min(75 if cinematic else 45,tl.duration_frames(assets[k]['duration']))
        if n<24:continue
        q=v.get('sample_quality') or [v['quality']];motion=v.get('sample_motion') or [v['motion']]
        window=max(1,math.ceil(n/15));offsets=[i*15 for i in range(max(1,len(q)-window+1)) if i*15+n<=tl.duration_frames(assets[k]['duration'])]
        if not offsets:continue
        def window_score(o):
            i=o//15; qualities=q[i:i+window]; movement=motion[i:i+window]; target=.12 if energetic else .035
            quality=sum(qualities)/len(qualities); move=sum(movement)/len(movement)
            # Penalize internal hard cuts in a candidate cutaway.
            changes=sum(o/30<t<(o+n)/30 for t in v.get('scene_changes',[]))
            return .72*quality+.28*max(0,1-abs(move-target)/.18)-.2*min(2,changes)
        offset=max(offsets,key=window_score)
        for lo,hi in regions:
            # End a pre-reveal cutaway before the specified reveal, rather
            # than covering the reveal with unrelated imagery.
            if reveal is not None:hi=min(hi,reveal)
            if hi-lo<n+15:continue
            nominal=max(lo+5,min(hi-n-5,total//3))
            anchors=[nominal]+[round(float(w['end'])*30) for w in spoken if abs(round(float(w['end'])*30)-nominal)<=24]
            for anchor in anchors:
                nearest=min(grid,key=lambda g:abs(g-anchor),default=anchor)
                positions=[(anchor,anchor in grid)]
                if grid and abs(nearest-anchor)<=8 and nearest!=anchor:positions.append((nearest,True))
                for a,aligned in positions:
                    if not(lo+5<=a and a+n<=hi-5) or any(a<e and a+n>b for b,e in occupied):continue
                    # Context is secondary to decoded quality, and never asserted as semantics.
                    tags={str(t).lower() for t in assets[k].get('keywords',[])}
                    nearby={x for w in spoken if abs(float(w['start'])*30-a)<=60 for x in re.findall(r'[a-z0-9]+',str(w.get('text','')).lower())}
                    score=window_score(offset)+.08*min(2,len(tags&nearby))+(.10 if aligned else 0)-.03*abs(a-nominal)/30
                    scores.append((score,k,a,n,offset,aligned,v))
    if scores:
        _,k,a,n,offset,aligned,v=max(scores,key=lambda x:(x[0],x[1],-x[2]))
        add(f'Cutaway {k} from {offset/30:.2f}s: measured detail {v["detail"]:.3f}, motion {v["motion"]:.3f}, contrast {v["contrast"]:.3f}; '+('beat-aligned. ' if aligned else '')+'Visual-quality proxy only; review subject relevance.',{'op':'put','layer':{'id':fresh_id('creative-cutaway'),'kind':'visual','asset':k,'at':a,'length':n,'offset':offset,'fade':min(8,n//2) if cinematic else 0}})
    cuts=[];cursor=0
    for a,b in zip(state['base']['pieces'],state['base']['pieces'][1:]):
        cursor+=a['length'];h=min(9,a['length']//2,b['length']//2)
        if h>=2 and cinematic and not any(t['at']==cursor for t in state['transitions']):cuts.append((cursor,h))
    if cuts:
        a,h=cuts[0];add('Dip to black across an existing edit boundary; keeps the narration clock unchanged.',{'op':'transition','kind':'dip','at':a,'half':h})
    if tension:
        if reveal is not None:
            n=min(45,reveal);add('Build a rising sound immediately before the specified reveal.',{'op':'put','layer':{'id':fresh_id('creative-riser'),'kind':'sfx','effect':'riser','at':reveal-n,'length':n,'gain':.10}})
            add('Land a restrained impact on the reveal frame.',{'op':'put','layer':{'id':fresh_id('creative-impact'),'kind':'sfx','effect':'impact','at':reveal,'length':min(30,total-reveal),'gain':.10}})
        else:suggestions.append({'reason':'Specify the reveal time, e.g. build tension before reveal at 0:12; no reveal is guessed.'})
    return {'suggestions':suggestions,'visual':analyses,'music':music_results,'warning':'Measured low-resolution samples and tempo heuristics; no semantic scene recognition. Suggestions are individually reviewable, never applied automatically.'}
