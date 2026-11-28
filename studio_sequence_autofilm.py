"""Bounded, reviewable autonomous cutaway montage for the real sequence editor.
Only owner-provided assets; no guessed object identity or destructive edits.
"""
import math
import re
import subprocess
import studio_sequence as seq
import studio_timeline as tl
import studio_sequence_creative as creative


def tokens(value):
    return set(re.findall(r'[a-z0-9]{3,}', str(value).casefold()))


def propose(state, assets, words, instruction):
    seq.validate(state, assets)
    total = state['base']['frames']
    fast = bool(tokens(instruction) & {'fast', 'energetic', 'punchy', 'hype'})
    target = 60 if fast else 90
    actions, evidence, occupied = [], [], [(x['at'], x['at']+x['length']) for x in state['layers'] if x['kind']=='visual']
    budget = min(6, seq.MAX_LAYERS-len(state['layers']))
    spoken = tl.remap_words(words, state['base'])
    if not spoken and any(p['audio'] for p in state['base']['pieces']) and not re.search(r'\bvisual[- ]only\b',instruction,re.I):
        return {'suggestions':[],'warning':'Audio is present but no aligned transcript is available. Analyze speech first, or explicitly request visual-only montage for non-narrative material.'}
    # Demonstration narration is a conservative cue to leave its picture alone.
    for w in spoken:
        if tokens(w.get('text')) & {'listen', 'compare', 'before', 'after', 'dry', 'wet'}:
            occupied.append((max(0, round(float(w['start'])*30)-30), min(total,round(float(w['end'])*30)+120)))
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
    for i in range(count):
        center=round((i+1)*total/(count+1)); options=[]
        for key,n,(score,off,q,m),tags in candidates:
            if key in used:continue
            nominal=max(15,min(total-n-15,center-n//2))
            anchors={nominal,*(round(float(w['end'])*30) for w in spoken if abs(round(float(w['end'])*30)-nominal)<=30)}
            for at in sorted(anchors):
                if at<15 or at+n>total-15 or any(at<b and at+n>a for a,b in occupied):continue
                nearby=set().union(*(tokens(w.get('text')) for w in spoken if abs(float(w['start'])*30-(at+n/2))<=120))
                matches=sorted(tags & nearby)
                if spoken and not matches:continue
                value=score+.12*min(3,len(matches))-.001*abs(at-nominal)
                options.append((value,key,n,at,off,q,m,matches))
        if not options:continue
        _,key,n,at,off,q,m,matches=max(options,key=lambda x:(x[0],x[1],-x[3]))
        ident=next('film-'+str(k) for k in range(1,1000) if 'film-'+str(k) not in ids)
        ids.add(ident);used.add(key);occupied.append((at,at+n))
        actions.append({'op':'put','layer':{'id':ident,'kind':'visual','asset':key,'at':at,'length':n,'offset':off,'fade':3 if not fast else 0}})
        evidence.append({'asset':key,'at_seconds':at/30,'offset_seconds':off/30,'quality':round(q,3),'motion':round(m,3),'matching_tags':matches})
    if not actions:return {'suggestions':[],'warning':'No unoccupied shot windows matched the narration. Add relevant tagged footage; existing picture and audio are unchanged.'}
    action={'op':'batch','actions':actions};candidate=seq.apply(state,action,assets)
    return {'suggestions':[{'reason':f'Compose {len(actions)} distinct cutaways from measured shot windows; preserve the original narration and timing.', 'action':action,'preview':{'before_frames':total,'after_frames':candidate['base']['frames'],'layers':candidate['layers'],'transitions':candidate['transitions']},'evidence':evidence}], 'warning':'Automatic montage, not semantic proof. Review subject relevance and embedded text before applying. Known A/B speech cue regions and existing picture layers are protected; untagged baked text is not detected.'}
