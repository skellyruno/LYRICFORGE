"""Re-render the real V20 Field Notes 06 composition on its measured speech clock."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
from fractions import Fraction
from mix_narration import mix,sha

def render(candidate,neural,out):
    candidate,neural,out=map(lambda p:Path(p).resolve(),(candidate,neural,out))
    out.mkdir(parents=True,exist_ok=False);assets=out/'assets';assets.mkdir()
    sys.path.insert(0,str(candidate))
    from examples.frequency_documentary import plan_for,SCRIPT
    import studio_director as director
    import studio_score as score
    clock=json.loads((neural/'report.json').read_text())
    if [c['text'] for c in clock['chapters']]!=SCRIPT:raise ValueError('Speech and script differ')
    cuts=clock['chapter_frames'];p=plan_for()
    if p['fps']!=60 or len(p['scenes'])!=5 or len(cuts)!=6 or cuts[0]!=0 or cuts[-1]!=clock['frames']:raise ValueError('Chapter clock mismatch')
    p['frames']=cuts[-1];p['duration']=cuts[-1]/60
    for i,(a,b) in enumerate(zip(cuts,cuts[1:])):
        if b<=a:raise ValueError('Invalid chapter boundary')
        p['scenes'][i].update(start=a/60,end=b/60,frames=b-a)
    director.configure_spatial(p['scenes'],60)
    score_path=out/'score.wav'
    score.write_score(p,score_path,rate=24000,music_gain=1.,cue_gain=0.)
    mastered=out/'mastered.wav';mix_report=mix(neural,score_path,mastered)
    p.update(sound_design=False,voice_style='off',caption_style='off',crossfades=False,audio_start=0.,silent=False)
    (out/'plan.json').write_text(json.dumps(p,indent=2))
    (out/'mix-report.json').write_text(json.dumps(mix_report,indent=2))
    def encode(args,cwd,*_):
        result=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=1800)
        if result.returncode:raise RuntimeError(result.stderr[-4000:])
    target=out/'Field-Notes-06-Narrated-Extended.mp4'
    stats=director.render(p,mastered,assets,out/'cache',target,{'fps':60},(960,540),lambda rows,path:path.write_text(''),encode,lambda:None,lambda *a:print('Scene',a,flush=True))
    streams=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(target)]))['streams']
    if len(streams)!=2:raise ValueError('Expected one audio and one picture stream')
    v=next(s for s in streams if s['codec_type']=='video');a=next(s for s in streams if s['codec_type']=='audio')
    if v['avg_frame_rate']!='60/1' or int(v['nb_frames'])!=p['frames'] or any(int(s['duration_ts'])*Fraction(s['time_base'])!=Fraction(p['frames'],60) or Fraction(s['start_time'])!=0 for s in (v,a)):raise ValueError('Encoded stream clock drift')
    (out/'report.json').write_text(json.dumps({'render':stats,'sha256':sha(target),'frames':p['frames'],'duration':p['duration'],'fps':60,'speech_source_sha256':clock['sha256']},indent=2))
    for i,(a,b) in enumerate(zip(cuts,cuts[1:])):
        subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',str((a+b)/120),'-i',str(target),'-frames:v','1',str(out/f'chapter-{i+1}.png')],check=True,timeout=60)
    result=subprocess.run(['ffmpeg','-hide_banner','-nostdin','-i',str(target),'-vn','-af','ebur128=peak=true','-f','null','-'],capture_output=True,text=True,check=True,timeout=120)
    (out/'loudness.log').write_text(result.stderr[-4000:])
    print('Exact narrated picture master verified',p['frames'],p['duration'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('candidate');p.add_argument('neural');p.add_argument('output');a=p.parse_args();render(a.candidate,a.neural,a.output)
