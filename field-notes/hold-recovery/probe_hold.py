"""Bounded diagnostic of exact Hold filter graph and a simpler single-tpad candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

def run_cmd(args,timeout):
    started=time.monotonic()
    try:
        p=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=timeout)
        return {'args':args,'returncode':p.returncode,'stdout':p.stdout[-12000:],'stderr':p.stderr[-12000:],'seconds':round(time.monotonic()-started,3)}
    except subprocess.TimeoutExpired as e:
        def tail(v):return (v.decode('utf-8','replace') if isinstance(v,bytes) else v or '')[-12000:]
        return {'args':args,'returncode':None,'timeout':timeout,'stdout':tail(e.stdout),'stderr':tail(e.stderr),'seconds':round(time.monotonic()-started,3)}

def patch_tpad(candidate):
    path=candidate/'studio_quick2.py'
    s=path.read_text(encoding='utf-8')
    old='''    # Single finite decoder; duplicate only the first cached frame, then reset
    # timestamps before the finite trailing pad. Avoid two-input concat stalls.
    if first: base+=f",loop=loop={first}:size=1:start=0,setpts=N/({fps:g}*TB)"
    if last: base+=f",tpad=stop_mode=clone:stop={last}"
'''
    new='''    # One finite clone-pad filter, no cached-frame loop or parallel decoder.
    base+=f",tpad=start_mode=clone:start={first}:stop_mode=clone:stop={last}"
'''
    if s.count(old)!=1:raise ValueError('Unexpected candidate Hold source')
    s=s.replace(old,new,1).replace('"setpts", "loop", "tpad"','"setpts", "tpad"')
    compile(s,str(path),'exec')
    path.write_text(s,encoding='utf-8')
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(candidate,out,variant):
    candidate,out=Path(candidate).resolve(),Path(out).resolve()
    out.mkdir(parents=True,exist_ok=False)
    if variant=='tpad':source_sha=patch_tpad(candidate)
    else:source_sha=hashlib.sha256((candidate/'studio_quick2.py').read_bytes()).hexdigest()
    sys.path.insert(0,str(candidate))
    import studio_quick2 as q
    import studio_clips as clips
    rows=[]
    report={'variant':variant,'source_sha256':source_sha,'version':run_cmd(['ffmpeg','-version'],10),'cases':rows}
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    for rate,audio in [(15,True),(15,False),(1,True),(1,False)]:
        source=out/f'input-{rate}-{audio}.mp4'
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-f','lavfi','-i',f'testsrc=s=320x180:r={rate}:d=2']
        if audio:cmd+=['-f','lavfi','-i','sine=f=220:d=2:sample_rate=48000']
        cmd+=['-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-threads','2']
        if audio:cmd+=['-c:a','aac']
        fixture=run_cmd(cmd+[str(source)],20)
        if fixture['returncode']!=0:
            rows.append({'rate':rate,'audio':audio,'phase':'fixture','result':fixture,'passed':False});save();continue
        metadata=clips.probe_media(source)
        for first,last in [(1.,0.),(.25,.25),(0.,1.)]:
            options=q.hold_prepare({'start':first,'end':last},{'video':metadata})
            target=out/f'output-{rate}-{audio}-{first}-{last}.mp4'
            args=q.hold_build({'video':source},options,target,True)
            args[args.index('-y'):args.index('-y')]=['-progress','pipe:1','-stats_period','0.5']
            result=run_cmd(args,20)
            row={'rate':rate,'audio':audio,'start':first,'end':last,'options':options,'result':result,'passed':False}
            if result['returncode']==0:
                probe=run_cmd(['ffprobe','-v','error','-show_streams','-of','json',str(target)],10)
                row['probe']=probe
                if probe['returncode']==0:
                    streams=json.loads(probe['stdout'])['streams']
                    v=next(s for s in streams if s['codec_type']=='video')
                    a=next((s for s in streams if s['codec_type']=='audio'),None)
                    row['passed']=(int(v['nb_frames'])==options['frames'] and bool(a)==audio and
                                   abs(float(v['duration'])-options['seconds'])<.002 and
                                   (not a or abs(float(a['duration'])-float(v['duration']))<.002))
            rows.append(row);save()
            print(rate,audio,first,last,'PASS' if row['passed'] else 'FAIL',result['seconds'],flush=True)
    if len(rows)!=12 or not all(row['passed'] for row in rows):raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('candidate');p.add_argument('out');p.add_argument('variant',choices=['loop','tpad']);a=p.parse_args()
    run(a.candidate,a.out,a.variant)
