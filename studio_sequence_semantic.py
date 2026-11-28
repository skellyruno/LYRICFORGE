"""Optional, contrastive CLIP matching of actual shot windows to speech cues.
No automatic download. Scores are relative evidence, not semantic certainty.
"""
import math,os,subprocess,tempfile
from pathlib import Path
from studio_director_intelligence import ai_request
import studio_performance as perf
from studio_sequence_film_schedule import protected_intervals,terms
import studio_sequence as seq
import studio_timeline as tl
import studio_sequence_creative as creative


def cues(words):
    out=[];group=[]
    for w in words:
        if group and (float(w['start'])-float(group[-1]['end'])>.55 or len(group)>=12 or float(w['end'])-float(group[0]['start'])>4.):
            out.append(group);group=[]
        group.append(w)
        if str(w['text']).endswith(('.', '?','!')):out.append(group);group=[]
    if group:out.append(group)
    return [(float(g[0]['start']),float(g[-1]['end']),' '.join(str(w['text']) for w in g)) for g in out if len(terms(' '.join(str(w['text']) for w in g)))>=2][:16]


def match(windows, phrases, model, request=None):
    request=request or ai_request
    # Two frames per window, exact source offsets rather than asset-level scores.
    if not windows or not phrases:return []
    if len(windows)>6 or len(phrases)>16:raise ValueError('Semantic inference budget exceeded')
    with tempfile.TemporaryDirectory(prefix='semantic-shots-') as folder:
        files=[];valid=[]
        for index,(key,path,offset,length) in enumerate(windows):
            pair=[]
            for frac in (.20,.80):
                p=Path(folder)/f'{index}-{frac}.png'
                try:
                    r=subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss',f'{(offset+length*frac)/30:.6f}','-i',str(path),'-frames:v','1','-vf','scale=384:384:force_original_aspect_ratio=decrease','-threads','1',str(p)],capture_output=True,timeout=12,**perf.windows_child_options(True))
                    if r.returncode==0 and p.is_file():pair.append(str(p))
                except (OSError,subprocess.TimeoutExpired):pass
            if len(pair)==2:valid.append((key,offset,length));files.extend(pair)
        if len(valid)<2:return [] # no meaningful competitor
        texts=['A relevant illustration of: '+p[2][:180] for p in phrases]+['A blank screen, unrelated decorative image, or generic background']
        scores=request({'operation':'match','model':str(Path(model).resolve()),'images':files,'texts':texts},timeout=180).get('scores')
        if not isinstance(scores,list) or len(scores)!=len(texts) or any(not isinstance(row,list) or len(row)!=len(files) or any(type(x) not in (int,float) or not math.isfinite(x) for x in row) for row in scores):raise ValueError('Invalid semantic scores')
    result=[]
    for i,(start,end,text) in enumerate(phrases):
        row=scores[i];ranked=sorted(((min(row[2*j:2*j+2]),j) for j in range(len(valid))),reverse=True)
        score,j=ranked[0];margin=score-ranked[1][0]
        negative=min(row[2*j+k]-scores[-1][2*j+k] for k in range(2))
        if margin<.7 or negative<.5:continue
        # Also reject if the same window scores better against a different cue.
        cue_margin=min(row[2*j+k]-max((scores[h][2*j+k] for h in range(len(phrases)) if h!=i),default=-100) for k in range(2))
        if cue_margin<.25:continue
        key,off,n=valid[j];result.append({'asset':key,'offset':off,'length':n,'start':start,'end':end,'cue':text,'competitor_margin':round(margin,3),'negative_margin':round(negative,3),'cue_margin':round(cue_margin,3)})
    return result


def propose(state,assets,words,instruction,*,model=None,request=None):
    seq.validate(state,assets);total=state['base']['frames'];spoken=tl.remap_words(words,state['base'])
    model=model or os.getenv('SKELLYMOTION_VISION_MODEL','')
    def empty(reason):return {'suggestions':[],'warning':reason}
    if not model or not (Path(model)/'config.json').is_file():return empty('Install and configure the optional local vision model first. No tag-based fallback in semantic mode.')
    phrases=cues(spoken)
    if not phrases:return empty('Semantic montage needs a usable timed transcript.')
    windows=[];scanned=0
    for key,a in sorted(assets.items()):
        if scanned>=6:break
        if key=='source' or a.get('music') or not a.get('has_video') or {str(x).casefold() for x in a.get('keywords',[])}&{'finished','captioned','baked-titles','baked-subtitles','a-b-proof'}:continue
        scanned+=1
        n=min(60 if terms(instruction)&{'fast','energetic','punchy'} else 90,tl.duration_frames(a['duration']))
        if n<30:continue
        try:v=creative.visual(a)
        except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired):continue
        q=v.get('sample_quality') or [v['quality']];count=max(1,math.ceil(n/15));ranges=[(sum(q[i:i+count])/count,i*15) for i in range(max(0,len(q)-count+1)) if i*15+n<=tl.duration_frames(a['duration']) and not any(i*.5<t<(i*15+n)/30 for t in v.get('scene_changes',[]))]
        if ranges:
            quality,off=max(ranges)
            if math.isfinite(quality) and quality>=.35:windows.append((key,a['path'],off,n))
    try:matches=match(windows,phrases,model,request)
    except (ValueError,RuntimeError,OSError,TypeError,AttributeError,subprocess.TimeoutExpired):return empty('Local semantic inference failed; original edit preserved.')
    occupied=protected_intervals(state,spoken);used=set();ids={x['id'] for x in state['layers']};actions=[];evidence=[]
    for row in sorted(matches,key=lambda r:(-r['competitor_margin'],r['start'])):
        if len(actions)>=min(6,seq.MAX_LAYERS-len(state['layers'])):break
        key,n=row['asset'],row['length'];at=max(15,min(total-n-15,round(row['start']*30)-6))
        if key in used or at+n>total-15 or at<15 or not at<=round(row['start']*30)<at+n or any(at<hi+6 and at+n+6>lo for lo,hi in occupied):continue
        ident=next('semantic-'+str(i) for i in range(1,1000) if 'semantic-'+str(i) not in ids);ids.add(ident);used.add(key);occupied.append((at,at+n))
        actions.append({'op':'put','layer':{'id':ident,'kind':'visual','asset':key,'at':at,'length':n,'offset':row['offset'],'fade':3}});evidence.append({**row,'at_seconds':at/30})
    if not actions:return empty('No sufficiently distinct semantic match outside protected regions. No changes proposed.')
    action={'op':'batch','actions':sorted(actions,key=lambda a:a['layer']['at'])};candidate=seq.apply(state,action,assets)
    return {'suggestions':[{'reason':'Compose cutaways using contrastive local vision evidence from two frames per selected source window.','action':action,'preview':{'before_frames':total,'after_frames':candidate['base']['frames'],'layers':candidate['layers'],'transitions':candidate['transitions']},'evidence':sorted(evidence,key=lambda r:r['at_seconds'])}],'warning':'Local CLIP relative matches, not verified object identity or full temporal understanding. Review cue relevance and embedded text; no filename or tag matching used for selection.'}
