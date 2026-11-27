"""Field Notes 06: original measured illustrations. Narration script is separate."""
import sys,json,subprocess,wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from examples.color_documentary import comp,tag,title
from examples.sound_documentary import L,A,track,data
import studio_director as d,studio_director_intelligence as intel,studio_score as score
FPS=60
SCRIPT=[
 'Everything that repeats has a frequency. It describes how often a cycle occurs. In sound, those cycles are pressure variations traveling through a medium.',
 'Frequency is measured in hertz, or cycles per second. Double the frequency of a periodic tone, and its period becomes half as long.',
 'Real sounds rarely contain a single frequency. This synthetic example combines four hundred forty, eight hundred eighty, and thirteen hundred twenty hertz, with successively smaller amplitudes.',
 'The relationship between frequencies creates patterns. The moving dye here is a visual metaphor for interaction, not a simulation of sound waves.',
 'When we separate a sound into its frequency components, we gain a new way to understand it. Frequency is a language for describing change.'
]
def plan_for():
    def chapter(n,heading,kind,foot,source):
        return comp(heading,source,[tag(n),title('heading',heading,.5,.20,.068,h=.15,keys=A(.5,.20,.02,.18)),L('visual',kind,.5,.52,.91,.49,depth=.3,keys=A(.5,.52,.06,.24)),title('foot',foot,.5,.84,.044,h=.14,keys=A(.5,.84,.35,.55))])
    comps=[comp('The Language of Frequency','FIELD NOTES / ORIGINAL MULTI-OBJECT ANALYTICAL RAY TRACING',[
        L('optics','ray_scene',.5,.53,.98,.76,depth=.28,keys=track((0,.5,.53,1,1),(1,.5,.57,1.06,1)),curve='continuous'),tag('FIELD NOTES  /  06'),title('opening','The Language of Frequency',.5,.22,.079,h=.18,keys=A(.5,.22,.04,.22)),title('sub','Everything that repeats has a frequency.',.5,.85,.042,h=.12,keys=A(.5,.85,.38,.56))]),
        chapter('01 / THE CYCLE','How often does it repeat?','frequency_pair','Frequency = cycles per second.','SCHEMATIC PERIODIC WAVES / THE LOWER ROW HAS TWICE THE FREQUENCY'),
        comp('One signal. Three frequencies.','MEASURED FFT OF AN ORIGINAL SYNTHETIC SIGNAL / NORMALIZED MAGNITUDES',[
            tag('02 / THE COMPONENTS'),title('heading','One signal. Three frequencies.',.5,.20,.067,h=.14,keys=A(.5,.20,.02,.18)),L('wave','wave',.50,.39,.79,.23,color='mint',harmonics=1.,keys=A(.50,.39,.07,.23)),L('spectrum','spectrum',.5,.65,.77,.30,values=data(),color='gold',keys=A(.5,.65,.26,.50)),title('foot','440 Hz    /    880 Hz    /    1320 Hz',.5,.85,.047,h=.10,keys=A(.5,.85,.35,.55))]),
        chapter('03 / THE RELATIONSHIP','Patterns emerge from interaction.','fluid_obstacle','A visual metaphor for interacting motion.','ORIGINAL DYE FLOW AROUND A SOLID / NOT A SOUND WAVE SIMULATION'),
        chapter('04 / THE LANGUAGE','Frequency makes change visible.','time_trajectory','Different frequencies draw a different path.','SCHEMATIC 2:3 LISSAJOUS TRAJECTORY / ORIGINAL PROCEDURAL GRAPHIC')]
    cuts=[round(b*60/score.DOC_BPM*FPS) for b in range(0,81,16)]
    scenes=[dict(type='big_text',text=g['title'],start=a/FPS,end=b/FPS,frames=b-a,captions=[],camera='still',cinematic_finish=True,brand='SKELLYMOTION',chapter=i+1,editorial='graphic',editorial_look='midnight',graphic=g) for i,(a,b,g) in enumerate(zip(cuts,cuts[1:],comps))]
    p=dict(version=d.VERSION,preset='doc',fps=FPS,duration=cuts[-1]/FPS,frames=cuts[-1],scenes=scenes,director='local',audio_start=0.,silent=False,cinematic_finish=True,caption_style='off',caption_track=[],crossfades=False,sound_design=True,music_gain=1.75,cue_gain=0.,voice_style='off',score_arc='chromatic',auto_repair_layout=True)
    d.configure_spatial(scenes,FPS);return p

def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False);assets=root/'assets';assets.mkdir();p=plan_for();audio=root/'source.wav';(root/'plan.json').write_text(json.dumps(p,indent=2));(root/'script.json').write_text(json.dumps(SCRIPT,indent=2))
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(round(p['duration']*24000)*2))
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,round(length,3),flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=600)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    stats=d.render(p,audio,assets,root/'cache',root/'film.mp4',{'fps':FPS},(960,540),lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True));(root/'report.json').write_text(json.dumps({'render':stats,'review':intel.review(p)},indent=2));score.write_score(p,root/'score.wav',music_gain=p['music_gain'],cue_gain=0.);print('RESULT',stats,flush=True)
if __name__=='__main__':main()
