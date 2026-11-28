"""Score-aware bounded visual retiming; speech and footage clocks are untouched."""
from copy import deepcopy
from studio_score import DOC_BPM

def align_generated_cuts(plan):
    result=deepcopy(plan);scenes=result['scenes'];fps=result['fps'];locked=[]
    result['score_bpm']=DOC_BPM
    if result.get('caption_track') is None or result.get('caption_style') not in ('marker','off'):return result
    def safe(s):
        # Never stretch recorded footage, a guided replay, or a source document.
        return (s.get('spatial_motion') or (not s.get('asset') and s.get('editorial') in ('graphic','chapter','statement'))) and not s.get('recorded_demo') and not s.get('guided_replay')
    for a,b in zip(scenes,scenes[1:]):
        if not (safe(a) and safe(b)):continue
        old=round(a['end']*fps);beat=round(old/fps*DOC_BPM/60);new=round(beat*60/DOC_BPM*fps);delta=new-old
        if abs(delta)>round(.24*fps) or a['frames']+delta<fps*2 or b['frames']-delta<fps*2:continue
        a['frames']+=delta;b['frames']-=delta;a['end']=b['start']=new/fps
        if b.get('bridge_scene'):b['bridge_scene']['end']=a['end']
        if b.get('editorial_bridge_scene'):b['editorial_bridge_scene']['end']=a['end']
        locked.append({'frame':new,'beat':beat,'shift_frames':delta})
    # Preserve the independent speech clock and regenerate scene-local captions.
    if locked:
        for s in scenes:
            rows=[]
            for c in result['caption_track']:
                lo=max(s['start'],c['start']);hi=min(s['end'],c['end'])
                if hi-lo<.025:continue
                words=[{**w,'start':max(lo,w['start'])-s['start'],'end':min(hi,w['end'])-s['start']} for w in c.get('words',[]) if min(hi,w['end'])>max(lo,w['start'])]
                rows.append({**c,'start':lo-s['start'],'end':hi-s['start'],'words':words})
            s['captions']=rows
    result['beat_locked_cuts']=locked
    return result
