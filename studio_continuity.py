"""Continuity editing for documentary plans. Preserve the speech clock and real source trims."""
from copy import deepcopy

REVISION=1

def connect(scenes, fps, *, max_seconds=16):
    """Join adjacent shots of the same composition rather than replaying entrances.
    A differing graphic, source, chapter, or noncontiguous media window is a cut.
    """
    out=[]
    for src in scenes:
        s=deepcopy(src)
        p=out[-1] if out else None
        same=bool(p and abs(p['end']-s['start'])<1e-6 and p['frames']+s['frames']<=fps*max_seconds and all(p.get(k)==s.get(k) for k in ('type','graphic','asset','chapter','hero_title','evidence_focus','asset_role','before_asset')) and not p.get('guided_replay') and not s.get('guided_replay'))
        if same and p.get('editorial')!=s.get('editorial') and not (p.get('editorial') in ('chapter','statement') and s.get('editorial') in ('chapter','statement')):same=False
        if same and not s.get('asset') and not s.get('graphic'):
            same=bool(s.get('hero_title') and s.get('editorial') in ('chapter','statement'))
        if same and s.get('editorial') not in ('graphic','evidence','chapter','statement') and not s.get('asset'):same=False
        if same and str(s.get('asset','')).lower().endswith(('.mp4','.mov','.mkv','.webm','.m4v')) and not ('editorial_seconds' in p and 'editorial_seconds' in s):same=False
        if same and ('editorial_seconds' in s or 'editorial_seconds' in p):
            same=abs(float(p.get('asset_start',0))+float(p.get('editorial_seconds',0))-float(s.get('asset_start',0)))<=1/fps and float(p.get('editorial_seconds',0))>=p['frames']/fps-1/fps
        if same:
            offset=p['frames']/fps
            p['captions'].extend({**c,'start':c['start']+offset,'end':c['end']+offset,'words':[{**w,'start':w['start']+offset,'end':w['end']+offset} for w in c.get('words',[])]} for c in s.get('captions',[]))
            p['frames']+=s['frames'];p['end']=s['end'];p['continuity_segments']=p.get('continuity_segments',1)+1
            if 'editorial_seconds' in p:p['editorial_seconds']+=s['editorial_seconds']
        else:out.append(s)
    return out
