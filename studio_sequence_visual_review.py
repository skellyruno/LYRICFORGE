"""Bounded decoded-output review: catch wrong picture/offset, not judge aesthetics."""
import subprocess,time
from pathlib import Path
import numpy as np
import studio_performance as perf

W,H=96,54


def frame(path,at,width,height,*,source=False):
    filters=[]
    if source:filters.extend([f'scale={width}:{height}:force_original_aspect_ratio=decrease',f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2','setsar=1'])
    filters.extend([f'scale={W}:{H}','format=rgb24'])
    args=['ffmpeg','-v','error','-nostdin','-threads','1','-ss',f'{at/30:.9f}','-i',str(path),'-an','-frames:v','1','-vf',','.join(filters),'-threads','1','-f','rawvideo','pipe:1']
    r=subprocess.run(args,capture_output=True,timeout=12,**perf.windows_child_options(True))
    if r.returncode or len(r.stdout)!=W*H*3:raise ValueError('Could not decode sampled frame')
    return np.frombuffer(r.stdout,np.uint8).reshape(H,W,3).astype(np.float32)/255


def compare(actual,expected):
    # The same decoded source may differ slightly due to the export codec and
    # subsampling. Use a conservative error threshold, not exact pixel equality.
    mae=float(np.mean(np.abs(actual-expected)))
    gray=expected @ np.array([.2126,.7152,.0722],np.float32)
    contrast=float(gray.std());detail=float(np.abs(np.diff(gray,axis=0)).mean()+np.abs(np.diff(gray,axis=1)).mean())
    actual_gray=actual @ np.array([.2126,.7152,.0722],np.float32)
    expected_black=bool(gray.mean()<.025 and contrast<.025)
    black=bool(actual_gray.mean()<.025 and actual_gray.std()<.025)
    if black and not expected_black:status='unexpected_black'
    elif mae>.085:status='mismatch'
    elif contrast<.025 or detail<.006:status='weak_visual_evidence'
    else:status='consistent'
    return {'status':status,'normalized_mae':round(mae,5),'expected_contrast':round(contrast,4),'expected_detail':round(detail,4)}


def review(path,state,assets,width,height,*,cancel=lambda:None):
    started=time.monotonic();rows=[];visuals=[x for x in state['layers'] if x['kind']=='visual']
    for i,x in enumerate(visuals[:6]):
        lo=x['at']+x.get('fade_in',x['fade'])+1;hi=x['at']+x['length']-x.get('fade_out',x['fade'])-1
        # Do not compare during intentional fades, covered layers or transitions.
        occupied=[(y['at'],y['at']+y['length']) for y in visuals[i+1:]]+[(t['at']-t['half'],t['at']+t['half']) for t in state['transitions']]
        points=sorted({lo+(hi-lo)//3,lo+2*(hi-lo)//3}) if hi>lo else []
        points=[at for at in points if not any(a<=at<b for a,b in occupied)]
        samples=[]
        for at in points:
            cancel();off=x['offset']+at-x['at']
            try:
                actual=frame(path,at,width,height);expected=frame(assets[x['asset']]['path'],off,width,height,source=True)
                samples.append({'at_seconds':round(at/30,3),'source_seconds':round(off/30,3),**compare(actual,expected)})
            except (OSError,ValueError,subprocess.TimeoutExpired):samples.append({'at_seconds':round(at/30,3),'status':'unavailable'})
        rows.append({'layer':x['id'],'asset':x['asset'],'samples':samples})
    counts={k:sum(s['status']==k for r in rows for s in r['samples']) for k in ('consistent','mismatch','unexpected_black','weak_visual_evidence','unavailable')}
    return {'scope':'Two decoded sample frames per selected visual layer, up to six layers; not full decode or aesthetic certification.','layers':rows,'counts':counts,'unreviewed_layers':max(0,len(visuals)-6),'seconds':round(time.monotonic()-started,3),'needs_review':bool(counts['mismatch'] or counts['unexpected_black'] or counts['unavailable'] or counts['weak_visual_evidence'] or len(visuals)>6 or any(not r['samples'] for r in rows))}
