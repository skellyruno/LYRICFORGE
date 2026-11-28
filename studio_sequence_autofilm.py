"""Bounded, reviewable autonomous cutaway montage for the real sequence editor.
Only owner-provided assets; no guessed object identity or destructive edits.
"""
import math
import re
import subprocess
import studio_sequence as seq
import studio_timeline as tl
import studio_sequence_creative as creative
import studio_sequence_film_schedule as schedule


def tokens(value):
    return set(re.findall(r'[a-z0-9]{3,}', str(value).casefold()))


def propose(state, assets, words, instruction):
    seq.validate(state, assets)
    total = state['base']['frames']
    fast = bool(tokens(instruction) & {'fast', 'energetic', 'punchy', 'hype'})
    target = 60 if fast else 90
    actions, evidence = [], []
    budget = min(6, seq.MAX_LAYERS-len(state['layers']))
    spoken = tl.remap_words(words, state['base'])
    if not spoken and any(p['audio'] for p in state['base']['pieces']) and not re.search(r'\bvisual[- ]only\b',instruction,re.I):
        return {'suggestions':[],'warning':'Audio is present but no aligned transcript is available. Analyze speech first, or explicitly request visual-only montage for non-narrative material.'}
    occupied=schedule.protected_intervals(state,spoken)
    candidates=[]; scanned=0
    for key,a in sorted(assets.items()):
        if scanned>=12: break
        if key=='source' or not a.get('has_video') or a.get('music'): continue
        if {str(t).casefold() for t in a.get('keywords',[])} & {'finished','captioned','baked-subtitles','baked-titles','a-b-proof'}:continue
        scanned+=1
        try:
            v=creative.visual(a)
            q=v.get('sample_quality') or [v['quality']]
            m=v.get('sample_motion') or [v['motion']]
            n=min(target,tl.duration_frames(a['duration']))
            if n<30: continue
            count=max(1, math.ceil(n/15))
            windows=[]
            for i in range(max(0,len(q)-count+1)):
                off=i*15
                if off+n>tl.duration_frames(a['duration']):continue
                quality=sum(q[i:i+count])/count
                motion=sum(m[i:i+count])/count
                if not math.isfinite(quality+motion) or quality<.35:continue
                if any(off/30<t<(off+n)/30 for t in v.get('scene_changes',[])):continue
                score=.8*quality+.2*max(0,1-abs(motion-(.10 if fast else .045))/.16)
                windows.append((score,off,quality,motion))
            if windows:candidates.append((key,n,max(windows),tokens(' '.join(map(str,a.get('keywords',[])))+' '+key)))
        except (ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.TimeoutExpired):continue
    if budget<=0 or not candidates:return {'suggestions':[],'warning':'No available layer budget or suitable decoded shot windows.'}
    # Spread shots over the edited clock, while preserving existing visuals.
    # Avoid repeated assets and footage unrelated to nearby speech when tags exist.
    used=set(); ids={x['id'] for x in state['layers']}
    count=min(budget,len(candidates),max(1,total//(target+45)))
    if spoken:
        grid=[]
        for layer in state['layers']:
            if layer['kind']!='music':continue
            try:
                info=creative.music(assets[layer['asset']])
                if info['confidence']>=.65:
                    grid.extend(round(t*30)-layer['offset']+layer['at'] for t in info['beats'] if layer['offset']<=round(t*30)<layer['offset']+layer['length'])
            except (ValueError,RuntimeError,OSError,KeyError,TypeError,subprocess.TimeoutExpired):continue
        selected=schedule.schedule(candidates,spoken,total,occupied,budget,grid)
    else:
        selected=[]
        for i in range(count):
            center=round((i+1)*total/(count+1)); options=[]
            for key,n,(score,off,q,m),tags in candidates:
                if key in used:continue
                nominal=max(15,min(total-n-15,center-n//2))
                if nominal<15 or nominal+n>total-15 or any(nominal<b and nominal+n>a for a,b in occupied):continue
                options.append((score,key,n,nominal,off,q,m,[]))
            if not options:continue
            row=max(options,key=lambda x:(x[0],x[1],-x[3]))
            selected.append(row);used.add(row[1]);occupied.append((row[3],row[3]+row[2]))
    for _,key,n,at,off,q,m,matches in selected:
        ident=next('film-'+str(k) for k in range(1,1000) if 'film-'+str(k) not in ids)
        ids.add(ident);used.add(key);occupied.append((at,at+n))
        actions.append({'op':'put','layer':{'id':ident,'kind':'visual','asset':key,'at':at,'length':n,'offset':off,'fade':3 if not fast else 0}})
        evidence.append({'asset':key,'at_seconds':at/30,'offset_seconds':off/30,'quality':round(q,3),'motion':round(m,3),'matching_tags':matches})
    if not actions:return {'suggestions':[],'warning':'No unoccupied shot windows matched the narration. Add relevant tagged footage; existing picture and audio are unchanged.'}
    action={'op':'batch','actions':actions};candidate=seq.apply(state,action,assets)
    return {'suggestions':[{'reason':f'Compose {len(actions)} distinct cutaways from measured shot windows; preserve the original narration and timing.', 'action':action,'preview':{'before_frames':total,'after_frames':candidate['base']['frames'],'layers':candidate['layers'],'transitions':candidate['transitions']},'evidence':evidence}], 'warning':'Automatic montage, not semantic proof. Review subject relevance and embedded text before applying. Narration cues use discriminative owner tags and bounded non-overlapping scheduling. Existing picture edits, transitions and known A/B regions are protected; untagged baked text is not detected.'}
