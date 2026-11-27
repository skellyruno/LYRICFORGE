"""Field Notes 04 — original music-led short about additive color."""
import argparse,json,sys,wave,subprocess
from pathlib import Path
import numpy as np
from PIL import ImageFont
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_director as d
import studio_director_intelligence as intel
import studio_layers as layers
import studio_score as score
from studio_render_review import select_shot
from examples.sound_documentary import L,T,A,track
FPS=60

def title(ident,text,x,y,size=.07,**kw):
    l=T(ident,text,x,y,size,**kw);l['face']='serif';l['curve']='continuous';return l

def comp(name,source,ls):
    return layers.validate(dict(kind='composition',title=name,source=source,layers=ls,camera=[[0,0,0,1],[.5,0,0,1.025],[1,0,0,1]]))

def tag(s):return L('tag','text',.5,.10,.84,.07,text=s,size=.033,face='mono',color='gold',keys=A(.5,.10,0,.14))

def plan_for():
    beats=[0,12,24,36,48,60];cuts=[round(b*60/score.DOC_BPM*FPS) for b in beats]
    def fluid(seed,x=.5,y=.52,scale=1):return L('dye','fluid',x,y,.92,.78,depth=.5,seed=seed,keys=track((0,x,y,scale,.85),(.48,x,y,scale*1.06,1),(1,x,y,scale,1)),curve='continuous')
    def opening(seed):return comp('The Science of Color','FIELD NOTES / ORIGINAL COMPUTED FLOW · STYLIZED DYE, NOT AN OPTICAL EXPERIMENT',[
        fluid(seed,.5,.52,1.05),tag('FIELD NOTES   /   04'),title('opening','The Science of Color',.5,.35,.10,h=.22,keys=A(.5,.35,.05,.25)),title('sub','Light becomes information.',.5,.82,.052,h=.12,keys=A(.5,.82,.3,.48))])
    font=d.font
    opts={f'seed-{seed}':opening(seed) for seed in (7,18,39)};candidates=[]
    for name,g in opts.items():
        c=layers.Composition(g,480,270,(cuts[1]-cuts[0])/FPS,font)
        candidates.append((name,[c.render(t) for t in (1.5,3.5,5.5,7.5)],0))
    selected,review=select_shot(candidates)
    comps=[opts[selected],comp('Different wavelengths','SCHEMATIC WAVELENGTH COMPARISON / APPROXIMATE DISPLAY COLORS, NOT CALIBRATED',[
        tag('01  /  LIGHT'),title('h','Color starts with light.',.5,.23,.067,h=.15,keys=A(.5,.23,.02,.2)),L('bands','light_waves',.5,.53,.86,.43,depth=.4,keys=A(.5,.53,.05,.22)),title('f','Different wavelengths can produce different color sensations.',.5,.82,.045,h=.13,keys=A(.5,.82,.30,.55))]),
        comp('Three channels','IDEAL ADDITIVE RGB MODEL / NOT SUBTRACTIVE PIGMENT MIXING',[
        tag('02  /  ADDITIVE LIGHT'),title('h','Three channels. Many colors.',.5,.22,.065,h=.14,keys=A(.5,.22,.02,.18)),L('mix','additive',.5,.54,.71,.48,keys=A(.5,.54,.04,.18)),title('f','Red, green and blue light combine.',.5,.83,.049,h=.10,keys=A(.5,.83,.34,.55))]),
        comp('Equal light','IDEAL RGB / EQUAL FULL INTENSITY IN EACH CHANNEL',[
        tag('03  /  THE MIX'),title('h','Together, they can make white.',.5,.23,.064,h=.14,keys=A(.5,.23,.02,.2)),L('mix-channels','light_channels',.5,.54,.84,.48,keys=A(.5,.54,.02,.19)),title('f','That is the principle behind RGB displays.',.5,.86,.043,h=.09,keys=A(.5,.86,.44,.64))]),
        comp('Light becomes an image','FIELD NOTES / ORIGINAL COMPUTED FLOW · ARTISTIC VISUALIZATION',[
        fluid(39,.5,.52,1.03),tag('04  /  THE IMAGE'),title('end','A world made of light.',.5,.35,.085,h=.2,keys=A(.5,.35,.12,.32)),L('credit','text',.5,.83,.76,.07,text='SKELLYMOTION   /   FIELD NOTES',size=.033,face='mono',color='gold',keys=A(.5,.83,.52,.72))])]
    scenes=[dict(type='big_text',text=g['title'],start=a/FPS,end=b/FPS,frames=b-a,captions=[],camera='still',cinematic_finish=True,brand='SKELLYMOTION',chapter=i+1,editorial='graphic',editorial_look='midnight',graphic=g) for i,(a,b,g) in enumerate(zip(cuts,cuts[1:],comps))]
    p=dict(version=d.VERSION,preset='doc',fps=FPS,duration=cuts[-1]/FPS,frames=cuts[-1],scenes=scenes,director='local',audio_start=0.,silent=False,cinematic_finish=True,caption_style='off',caption_track=[],crossfades=False,sound_design=True,music_gain=1.75,cue_gain=0.,voice_style='off',score_arc='chromatic',score_rests=[[0.0,0.32,0.15]],auto_repair_layout=True)
    d.configure_spatial(scenes,FPS);return p,review

def main():
    a=argparse.ArgumentParser();a.add_argument('out',type=Path);a.add_argument('--height',type=int,default=540);args=a.parse_args();root=args.out.resolve();root.mkdir(parents=True,exist_ok=False);assets=root/'assets';assets.mkdir();p,review=plan_for();audio=root/'source.wav'
    (root/'storyboard.json').write_text(json.dumps(review,indent=2));(root/'plan.json').write_text(json.dumps(p,indent=2))
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(round(p['duration']*24000)*2))
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,round(length,3),flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    stats=d.render(p,audio,assets,root/'cache',root/'film.mp4',{'fps':FPS},(args.height*16//9,args.height),lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True));(root/'report.json').write_text(json.dumps({'render':stats,'review':intel.review(p),'storyboard':review},indent=2));score.write_score(p,root/'score.wav',music_gain=p['music_gain'],cue_gain=0.);print('RESULT',stats,flush=True)
if __name__=='__main__':main()
