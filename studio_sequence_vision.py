"""Bounded semantic evidence for the sequence planner, using the existing local CLIP worker.

No downloads or model installation, no cloud requests. Labels are relative
hypotheses about sampled frames, never a verified account of the whole video.
"""
from pathlib import Path
import math
import os
import subprocess
import tempfile
from studio_director_intelligence import ai_request
from studio_reference_vision import TECHNIQUES, ROLES
import studio_performance as perf

MAX_FRAMES = 12


def evidence(assets, instruction, *, model=None, request=None):
    raw = str(model or os.getenv('SKELLYMOTION_VISION_MODEL', ''))
    if not raw:
        return {'status': 'not_configured', 'observations': []}
    model = Path(raw).expanduser()
    if not model.is_dir() or not (model / 'config.json').is_file():
        return {'status': 'unavailable', 'observations': []}
    if request is None:
        request = ai_request
    candidates = [(k,a) for k,a in sorted(assets.items(),key=lambda x:(x[0]!='source',x[0]))
                  if a.get('has_video') and not a.get('music')][:6]
    if not candidates:
        return {'status': 'no_video', 'observations': []}
    texts = [*TECHNIQUES.values(), *ROLES.values(), 'A shot suitable for this editing direction: '+str(instruction)[:160]]
    with tempfile.TemporaryDirectory(prefix='sequence-vision-') as directory:
        files = []
        # Two samples spread across each source, not just the opening seconds.
        for key, asset in candidates:
            duration = float(asset['duration'])
            if not math.isfinite(duration) or duration <= 0:
                continue
            points = sorted({round(min(duration*.2,max(0,duration-.1)),3),round(min(duration*.75,max(0,duration-.1)),3)})
            for second in points[:MAX_FRAMES-len(files)]:
                target = Path(directory) / f'{len(files)}.png'
                try:
                    p = subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss',str(second),'-i',str(asset['path']),'-frames:v','1','-vf','scale=384:384:force_original_aspect_ratio=decrease','-threads','1',str(target)],capture_output=True,timeout=12,**perf.windows_child_options(True))
                    if p.returncode == 0 and target.is_file():
                        files.append((key,second,str(target)))
                except (OSError, subprocess.TimeoutExpired):
                    continue
        if not files:
            return {'status': 'no_frames', 'observations': []}
        try:
            scores = request({'operation':'match','model':str(model.resolve()),'images':[p for _,_,p in files],'texts':texts},timeout=180).get('scores')
            if not isinstance(scores,list) or len(scores)!=len(texts) or any(not isinstance(row,list) or len(row)!=len(files) or any(type(x) not in (float,int) or not math.isfinite(x) for x in row) for row in scores):
                raise ValueError('Unexpected vision score shape')
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
            return {'status':'inference_failed','observations':[]}
    def classify(labels, start, col):
        ranked=sorted(((scores[start+i][col],label) for i,label in enumerate(labels)),reverse=True)
        margin=ranked[0][0]-ranked[1][0]
        return (ranked[0][1] if margin>=.25 else 'uncertain',round(margin,3))
    observations=[]
    direction=scores[-1]
    span=max(direction)-min(direction)
    for i,(key,second,_) in enumerate(files):
        technique,tm=classify(list(TECHNIQUES),0,i)
        role,rm=classify(list(ROLES),len(TECHNIQUES),i)
        observations.append({'asset':key,'second':second,'technique':technique,'role':role,
                             'technique_margin':tm,'role_margin':rm,
                             'relative_direction_match':round((direction[i]-min(direction))/span,3) if span>.01 else None})
    return {'status':'sampled','observations':observations,'basis':'Local CLIP relative scores on sampled stills, not calibrated confidence or full-video understanding.'}
