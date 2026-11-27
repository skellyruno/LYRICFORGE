"""Field Notes 03: original music-led study, measured tone and genuine rest."""
import argparse,json,subprocess,sys,wave
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_director as d
import studio_director_intelligence as intel
import studio_layers as layers
import studio_score as score
from studio_signal_story import decay_example,measure_decay
from examples.sound_documentary import L,T,A,track
FPS=60

def title(ident,text,x,y,size=.07,**kw):
    l=T(ident,text,x,y,size,**kw);l['face']='serif';l['curve']='continuous';return l

def make_plan():
    cuts=[round(b*60/score.DOC_BPM*FPS) for b in (0,10,20,30,40)]
    start=cuts[1]/FPS;tone_at=start+1.8;end=cuts[-1]/FPS
    points=measure_decay(*decay_example())
    def comp(name,source,ls):return layers.validate(dict(kind='composition',title=name,source=source,layers=ls,camera=[[0,0,0,1],[.5,0,0,1.015],[1,0,0,1]]))
    def tag(text):return L('tag','text',.5,.10,.84,.065,text=text,size=.034,face='mono',color='gold',keys=A(.5,.10,0,.14))
    def reveal(x,y,a,b):return track((0,x,y,1,0),(a,x,y,1,0),(b,x,y,1,1),(1,x,y,1,1))
    comps=[comp('The Architecture of Silence','FIELD NOTES / ORIGINAL VISUAL STUDY · WAVE ILLUSTRATION',[
       L('echo','rings',.5,.48,1.1,.75,depth=1.5,color='mint',keys=track((0,.5,.48,.72,.2),(.42,.5,.48,1.05,.8),(.83,.5,.48,1.24,.25),(1,.5,.48,1.24,0))),
       L('surface','surface',.5,.69,1.1,.40,depth=.8,color='mint',keys=track((0,.5,.72,.92,0),(.22,.5,.69,1,1),(.7,.5,.66,1.1,.8),(1,.5,.66,1.05,0)),curve='continuous'),
       tag('FIELD NOTES   /   03'),title('opening','The Architecture of Silence',.5,.38,.104,h=.29,keys=A(.5,.38,.02,.19)),title('subtitle','What happens when sound disappears?',.5,.80,.049,h=.10,keys=reveal(.5,.80,.44,.64))]),
       comp('Sound fades','FLOATING-POINT 440 HZ EXAMPLE · 50 MS RMS WINDOWS · NOT A ROOM MEASUREMENT',[
       tag('01  /  DECAY'),title('heading','Sound does not always stop at once.',.5,.20,.062,h=.13,keys=A(.5,.20,.01,.16)),
       L('trace','decay_trace',.5,.52,.86,.47,points=points,trace_delay=1.8,trace_seconds=2,color='gold',keys=A(.5,.52,.02,.20)),title('proof','A tone with a designed 60 dB/s decay.',.5,.84,.043,h=.10,keys=reveal(.5,.84,.10,.25))]),
       comp('A moment of quiet','ILLUSTRATION  /  ZERO PCM SAMPLES  ·  A DELIBERATE REST IN THE SCORE',[
       tag('02  /  SILENCE'),L('quiet','line',.5,.49,.75,.025,color='mint',keys=track((0,.5,.49,.88,.5),(.25,.5,.49,1,1),(.66,.5,.49,1,1),(1,.5,.49,1,.4)),curve='continuous'),
       title('quiet-label','Digital silence.',.5,.33,.085,h=.18,keys=A(.5,.33,0,.17)),title('zero','In digital silence, every PCM sample is zero.',.5,.69,.055,h=.14,keys=reveal(.5,.69,.16,.32)),L('zero-code','text',.5,.79,.62,.07,text='0   0   0   0   0   0   0',size=.033,face='mono',color='muted',keys=reveal(.5,.79,.34,.5))]),
       comp('Contrast gives sound meaning','FIELD NOTES  /  ORIGINAL MOTION STUDY',[
       L('quiet','line',.5,.49,.75,.025,color='mint',keys=track((0,.5,.49,1,.4),(.25,.5,.49,1,0),(1,.5,.49,1,0))),L('surface','surface',.5,.65,.96,.46,depth=.8,color='mint',keys=track((0,.5,.69,.94,0),(.31,.5,.65,1,1),(.68,.5,.64,1.08,.7),(1,.5,.64,1.08,.25)),curve='continuous'),tag('03  /  CONTRAST'),title('final','Silence gives sound its shape.',.5,.36,.08,h=.24,keys=A(.5,.36,.08,.31)),L('credit','text',.5,.83,.76,.07,text='SKELLYMOTION   /   FIELD NOTES',size=.033,face='mono',color='gold',keys=reveal(.5,.83,.56,.78))])]
    scenes=[dict(type='big_text',text=g['title'],start=a/FPS,end=b/FPS,frames=b-a,captions=[],camera='still',cinematic_finish=True,brand='SKELLYMOTION',chapter=i+1,editorial='graphic',editorial_look='midnight',graphic=g) for i,(a,b,g) in enumerate(zip(cuts,cuts[1:],comps))]
    p=dict(version=d.VERSION,preset='doc',fps=FPS,duration=end,frames=cuts[-1],scenes=scenes,director='local',audio_start=0.,silent=False,cinematic_finish=True,caption_style='off',caption_track=[],crossfades=False,sound_design=True,music_gain=1.75,cue_gain=0.,voice_style='off',score_arc='cinematic',auto_repair_layout=True,score_rests=[[tone_at-.6,cuts[2]/FPS+2.,.65]])
    d.configure_spatial(scenes,FPS);return p,tone_at,points

def main():
    a=argparse.ArgumentParser();a.add_argument('out',type=Path);a.add_argument('--height',type=int,default=540);args=a.parse_args();root=args.out.resolve();root.mkdir(parents=True,exist_ok=False);assets=root/'assets';assets.mkdir();p,tone_at,points=make_plan()
    signal,sr=decay_example();audio=np.zeros(round(p['duration']*sr));at=round(tone_at*sr);audio[at:at+len(signal)]=signal*.55
    with wave.open(str(root/'demonstration.wav'),'wb') as f:f.setparams((1,2,sr,0,'NONE','not compressed'));f.writeframes(np.rint(audio*32767).astype('<i2').tobytes())
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,round(length,3),flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    stats=d.render(p,root/'demonstration.wav',assets,root/'cache',root/'film.mp4',{'fps':FPS},(args.height*16//9,args.height),lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True))
    (root/'plan.json').write_text(json.dumps(p,indent=2));(root/'report.json').write_text(json.dumps({'render':stats,'review':intel.review(p),'tone_at':tone_at,'measurements':points},indent=2));score.write_score(p,root/'score.wav',music_gain=p['music_gain'],cue_gain=0.);print('RESULT',stats,flush=True)
if __name__=='__main__':main()
