"""Bounded local reference study; no reference footage enters the production."""
import argparse,json,math,subprocess,os
from pathlib import Path
import numpy as np

def profile_frames(frames,fps):
    if not math.isfinite(fps) or fps<=0 or len(frames)<2:raise ValueError('Insufficient samples')
    gray=np.asarray(frames,dtype=np.float32).mean(axis=3)/255
    delta=np.abs(gray[1:]-gray[:-1]).mean(axis=(1,2));threshold=max(.12,float(np.median(delta))*3.4)
    cuts=[0]
    for i in np.where(delta>threshold)[0]+1:
        if (i-cuts[-1])/fps>=.8:cuts.append(int(i))
    cuts.append(len(gray));gaps=np.diff(cuts)/fps;noncut=delta[delta<=threshold]
    return {'sample_fps':fps,'sample_count':len(gray),'sample_seconds':len(gray)/fps,'estimated_changes':len(cuts)-2,'median_shot_seconds':round(float(np.median(gaps)),3),'motion_proxy':round(float(np.median(noncut)) if len(noncut) else 0.,4),'median_luma':round(float(np.median(gray.mean(axis=(1,2)))),4),'median_contrast':round(float(np.median(gray.std(axis=(1,2)))),4),'confidence':'Approximate; sampling can miss cuts or confuse fast motion with edits.'}

def analyze(path,seconds=600,notes=None):
    path=Path(path).resolve()
    if not path.is_file() or not 2<=seconds<=600:raise ValueError('Invalid reference or analysis limit')
    p=subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-i',str(path),'-t',str(seconds),'-an','-vf','fps=2,scale=80:45','-pix_fmt','rgb24','-f','rawvideo','-threads','1','pipe:1'],capture_output=True,timeout=120,check=True)
    result=profile_frames(np.frombuffer(p.stdout,dtype=np.uint8).reshape(-1,45,80,3),2.)
    if notes is not None:
        from studio_story import grammar
        result['story_grammar']=grammar(notes)
    elif os.getenv('SKELLYMOTION_VISION_MODEL'):
        from studio_reference_vision import infer
        try:
            base=np.frombuffer(p.stdout,dtype=np.uint8).reshape(-1,45,80,3)
            result['vision_hypotheses']=infer(base,2.,reference=path)
        except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as exc:
            result['vision_warning']=str(exc)[:200]
    return result

def pacing(profile,base,maximum):
    if not profile:return base,maximum
    v=profile.get('median_shot_seconds');n=profile.get('estimated_changes',0)
    if not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 or not isinstance(n,int) or n<3:return base,maximum
    pace=max(2.5,min(8.,base*.4+min(9.,v)*.6));return pace,max(pace+1.,min(12.,maximum*.4+pace*1.65*.6))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reference');p.add_argument('--seconds',type=int,default=600);p.add_argument('--notes',type=Path);args=p.parse_args();print(json.dumps(analyze(args.reference,args.seconds,json.loads(args.notes.read_text()) if args.notes else None),indent=2))
