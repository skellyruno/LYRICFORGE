"""Choose among explicitly authored shots using rendered samples, not imagined quality.
Scores are heuristics; visual/semantic approval still requires review."""
import numpy as np


def select_shot(candidates):
    """Each candidate is (name, sequence of RGB images, layout-warning count).
    Favor legibility-safe layouts, visible tonal range, coherent motion. Never
    prefer a blank or clipped candidate merely for contrast."""
    if not 2<=len(candidates)<=8:raise ValueError('Need 2–8 rendered candidates')
    report=[]
    for name,frames,warnings in candidates:
        if not isinstance(name,str) or not name or not 2<=len(frames)<=12 or type(warnings) is not int or warnings<0:raise ValueError('Invalid candidate')
        a=np.stack([np.asarray(f.convert('RGB').resize((160,90)),dtype=np.float32)/255 for f in frames]);l=a@np.array([.2126,.7152,.0722]);lo,hi=np.percentile(l,[5,95]);dynamic=float(hi-lo);motion=float(np.abs(np.diff(l,axis=0)).mean());visible=float(np.mean(l>.045));blown=float(np.mean(l>.97));blank=int(np.sum(np.percentile(l,95,axis=(1,2))<.06))
        score=2*dynamic+min(.20,motion)*2+min(.6,visible)*.4-blown*.5-3*warnings-4*blank
        report.append(dict(name=name,score=round(score,6),layout_warnings=warnings,near_empty=blank,tonal_range=round(dynamic,4),motion=round(motion,4)))
    report.sort(key=lambda x:(-x['score'],x['name']))
    return report[0]['name'],{'candidates':report,'basis':'Rendered-frame contrast, motion, empty-frame and supplied layout checks; not semantic or artistic approval.'}
