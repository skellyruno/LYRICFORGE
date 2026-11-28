"""Field Notes 05: original music-led film, geometric illustrations of time."""
import sys,json,subprocess,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from examples.color_documentary import comp,tag,title
from examples.sound_documentary import L,A,track
import studio_director as d,studio_director_intelligence as intel,studio_score as score
FPS=60

def plan_for():
    def chapter(n,heading,kind,footer,source):
        return comp(heading,source,[tag(n),title('heading',heading,.5,.23,.067,h=.15,keys=A(.5,.23,.02,.18)),L('visual',kind,.5,.54,.88,.47,depth=.3,keys=A(.5,.54,.06,.24)),title('footer',footer,.5,.85,.046,h=.12,keys=A(.5,.85,.35,.55))])
    comps=[comp('The Geometry of Time','FIELD NOTES / ORIGINAL ANALYTIC RAY-TRACED SCULPTURE',[
        L('glass','optical_glass',.5,.53,.92,.75,depth=.45,keys=track((0,.5,.52,1,1),(1,.5,.56,1.10,1)),curve='continuous'),tag('FIELD NOTES   /   05'),title('opening','The Geometry of Time',.5,.25,.085,h=.16,keys=A(.5,.25,.04,.20)),title('sub','We see time through change.',.5,.84,.048,h=.12,keys=A(.5,.84,.35,.55))]),
        chapter('01  /  THE CYCLE','A repeating motion becomes a clock.','time_orbit','A cycle can be divided into smaller intervals.','SCHEMATIC PERIODIC MOTION / NOT A MODEL OF PLANETARY ORBITS'),
        chapter('02  /  THE INTERVAL','A continuous motion leaves discrete traces.','time_samples','24 and 60 samples in the same one-second interval.','ILLUSTRATIVE SAMPLING / SAME CONTINUOUS SIGNAL AT TWO CADENCES'),
        comp('Time has a rhythm.','SCHEMATIC PERIODIC WAVE / NOT AN ACTUAL TIME MEASUREMENT',[
            tag('03  /  THE RHYTHM'),title('heading','Time has a rhythm.',.5,.23,.08,h=.15,keys=A(.5,.23,.03,.20)),L('wave','surface',.5,.53,.96,.48,color='mint',depth=.6,keys=A(.5,.53,.05,.20)),title('foot','The spacing between events shapes how we feel motion.',.5,.84,.046,h=.14,keys=A(.5,.84,.35,.55))]),
        chapter('04  /  THE PATTERN','Two rhythms. One intricate path.','time_trajectory','Combining periodic motions creates new patterns.','SCHEMATIC LISSAJOUS CURVE / 2:3 FREQUENCY RATIO'),
        comp('The Geometry of Time','FIELD NOTES / ORIGINAL COMPUTED METAL SCULPTURE',[
            L('metal','optical_metal',.5,.53,.91,.73,depth=.5,keys=track((0,.5,.53,1,1),(1,.5,.56,1.08,1)),curve='continuous'),tag('05  /  THE MOMENT'),title('closing','Time is not the picture.',.5,.25,.076,h=.16,keys=A(.5,.25,.04,.24)),title('end','It is the change between pictures.',.5,.83,.048,h=.13,keys=A(.5,.83,.36,.56))])]
    beats=[0,16,32,48,64,80,96];cuts=[round(b*60/score.DOC_BPM*FPS) for b in beats]
    scenes=[dict(type='big_text',text=g['title'],start=a/FPS,end=b/FPS,frames=b-a,captions=[],camera='still',cinematic_finish=True,brand='SKELLYMOTION',chapter=i+1,editorial='graphic',editorial_look='midnight',graphic=g) for i,(a,b,g) in enumerate(zip(cuts,cuts[1:],comps))]
    p=dict(version=d.VERSION,preset='doc',fps=FPS,duration=cuts[-1]/FPS,frames=cuts[-1],scenes=scenes,director='local',audio_start=0.,silent=False,cinematic_finish=True,caption_style='off',caption_track=[],crossfades=False,sound_design=True,music_gain=1.75,cue_gain=0.,voice_style='off',score_arc='cinematic',auto_repair_layout=True)
    d.configure_spatial(scenes,FPS);return p

def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False);assets=root/'assets';assets.mkdir();p=plan_for();audio=root/'source.wav';(root/'plan.json').write_text(json.dumps(p,indent=2))
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(round(p['duration']*24000)*2))
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,round(length,3),flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    stats=d.render(p,audio,assets,root/'cache',root/'film.mp4',{'fps':FPS},(960,540),lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True));(root/'report.json').write_text(json.dumps({'render':stats,'review':intel.review(p)},indent=2));score.write_score(p,root/'score.wav',music_gain=p['music_gain'],cue_gain=0.);print('RESULT',stats,flush=True)
if __name__=='__main__':main()
