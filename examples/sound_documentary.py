"""Original music-led educational short; no reference footage or private media.
Run from the source root with a new output directory: python examples/sound_documentary.py OUT
Optional LYRICFORGE_SOUNDFONT uses a licensed local instrument bank.
"""
import json,sys,subprocess,wave,math
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_director as d
import studio_director_intelligence as intel
import studio_layers as layers
import studio_score as score
FPS=60

def track(*rows):return [list(row) for row in rows]
def L(ident,kind,x,y,w,h,*,keys=None,color='white',depth=0,**kw):
    return dict(id=ident,type=kind,width=w,height=h,color=color,depth=depth,track=keys or track((0,x,y,1,1)),**kw)
def T(ident,text,x,y,size=.058,*,w=.82,h=.15,keys=None,color='white',depth=0):return L(ident,'text',x,y,w,h,text=text,size=size,keys=keys,color=color,depth=depth)
def A(x,y,delay=.05,end=.17,*,s=1):return track((0,x,y+.025,s,0),(max(.0001,delay),x,y+.025,s,0),(end,x,y,s,1),(1,x,y,s,1))
def header(n,title,sub=None):
    a=[T('section'+n,'0'+n+'  /  '+title,.5,.105,.037,h=.075,color='gold',keys=A(.5,.105,0,.12))]
    if sub:a.append(T('sub'+n,sub,.5,.20,.059,h=.14,keys=A(.5,.20,.04,.20)))
    return a

def data():
    # Actual FFT of a one-second synthesized example. Integer bins, no leakage.
    sr=24000;t=np.arange(sr)/sr;freqs=[440,880,1320];amps=[1,.5,.25];signal=sum(a*np.sin(2*np.pi*f*t) for a,f in zip(amps,freqs));fft=np.abs(np.fft.rfft(signal))*2/sr
    return [{'label':f'{f} Hz','value':round(float(fft[f]/fft.max()),6)} for f in freqs]

def compositions():
    vals=data();wave_args=dict(color='mint',harmonics=0.0,depth=.12);wave_complex=dict(color='mint',harmonics=1.,depth=.12)
    # Moving illustrations have explicit titles and source annotations. Only the
    # measured spectrum uses numerical evidence; the waveform animation is schematic.
    comps=[]
    def add(title,source,ls,cam=None):comps.append(layers.validate(dict(kind='composition',title=title,source=source,layers=ls,camera=cam or [[0,0,0,1],[1,0,0,1]])))
    add('The shape of sound','SKELLYMOTION  /  ORIGINAL VISUAL STUDY  ·  PARTICLE MOTION ILLUSTRATION',[
      L('rings','rings',.50,.48,.78,.78,color='gold',depth=1.2,keys=track((0,.5,.48,1,.7),(.45,.5,.48,1.2,.35),(.72,.5,.48,1.35,0),(1,.5,.48,1.35,0))),
      L('mesh','surface',.5,.60,1.04,.50,color='mint',depth=.75,keys=track((0,.5,.59,1.08,.85),(.40,.5,.61,1,.85),(.62,.5,.56,1,0),(1,.5,.56,1,0))),
      T('opening','THE SHAPE OF SOUND',.5,.38,.103,h=.22,keys=track((0,.5,.40,.94,0),(.18,.5,.38,1,1),(.37,.5,.38,1,1),(.48,.5,.20,.76,0),(1,.5,.20,.76,0))),
      T('opening-sub','Everything begins with motion.',.5,.61,.051,h=.13,keys=track((0,.5,.64,1,0),(.23,.5,.64,1,0),(.34,.5,.61,1,1),(.49,.5,.82,1,0),(1,.5,.82,1,0))),
      L('air','particles',.50,.48,.85,.37,color='mint',depth=.35,keys=track((0,.5,.49,1,0),(.43,.5,.49,1,0),(.63,.5,.49,1,1),(.88,.5,.49,1,1),(1,.5,.49,1,.85))),
      T('air-label','Air particles vibrate around their resting positions.',.5,.79,.049,h=.16,keys=track((0,.5,.8,1,0),(.52,.5,.8,1,0),(.72,.5,.79,1,1),(1,.5,.79,1,1))),
      L('wave','wave',.5,.52,.82,.34,keys=track((0,.5,.54,1,0),(.68,.5,.54,1,0),(.92,.5,.50,1,.85),(1,.5,.50,1,1)),**wave_args)
      ],[[0,0,0,1.02],[.45,0,0,1],[1,0,0,1]])
    add('Pressure over time','ILLUSTRATION  /  A PERIODIC WAVEFORM, NOT A LIVE RECORDING',header('1','THE WAVE','Pressure becomes a pattern.')+[
      L('air','particles',.5,.48,.85,.37,color='mint',depth=.35,keys=track((0,.5,.49,1,.85),(.36,.5,.42,1,0),(1,.5,.42,1,0))),
      L('wave','wave',.5,.50,.82,.34,keys=track((0,.5,.5,1,1),(.34,.5,.51,1,1),(.7,.5,.51,1.07,1),(1,.5,.51,1,1)),**wave_args),
      T('time','TIME  →',.5,.73,.031,color='muted',h=.07,keys=A(.5,.73,.15,.30)),
      T('pattern','A repeating cycle is a periodic wave.',.5,.83,.045,h=.11,keys=A(.5,.83,.33,.49))
      ])
    add('A sound can contain many frequencies','ILLUSTRATION + MEASURED FFT OF AN ORIGINAL SYNTHETIC TEST SIGNAL',header('2','THE SPECTRUM','One sound. Many frequencies.')+[
      L('wave','wave',.5,.40,.82,.34,keys=track((0,.5,.51,1,1),(.30,.5,.37,.65,0),(1,.5,.37,.65,0)),**wave_args),
      L('complex','wave',.5,.40,.82,.31,keys=track((0,.5,.43,.86,0),(.24,.5,.40,.86,0),(.43,.5,.37,.70,1),(1,.5,.37,.70,1)),**wave_complex),
      L('spec','spectrum',.5,.64,.77,.32,values=vals,color='gold',keys=track((0,.5,.68,1,0),(.32,.5,.68,1,0),(.55,.5,.64,1,1),(1,.5,.64,1,1))),
      T('spectext','A spectrum separates a signal by frequency.',.5,.84,.046,h=.12,keys=A(.5,.84,.45,.64))
      ])
    add('Measurement makes the invisible visible','MEASUREMENT  /  ONE-SECOND SYNTHETIC SIGNAL  ·  NORMALIZED FFT MAGNITUDES',header('3','THE EVIDENCE','We can measure those components.')+[
      L('spec','spectrum',.5,.64,.77,.32,values=vals,color='gold',keys=track((0,.5,.64,1,1),(.32,.31,.48,.66,1),(.9,.31,.48,.66,1),(1,.31,.48,.66,1))),
      L('paper1','paper',.75,.36,.34,.17,text='440 Hz  ·  1.00',label='FUNDAMENTAL',depth=.25,keys=A(.75,.36,.16,.32)),
      L('paper2','paper',.75,.53,.34,.17,text='880 Hz  ·  0.50',label='SECOND HARMONIC',depth=.10,keys=A(.75,.53,.31,.47)),
      L('paper3','paper',.75,.70,.34,.17,text='1320 Hz  ·  0.25',label='THIRD HARMONIC',depth=-.05,keys=A(.75,.70,.46,.62)),
      T('measured','Three peaks. One combined waveform.',.5,.84,.046,h=.11,keys=A(.5,.84,.52,.70))
      ])
    add('From continuous motion to digital audio','ILLUSTRATION  /  SAMPLING AT DISCRETE INSTANTS  ·  NOT TO SCALE',[
      T('section4','04  /  THE RECORDING',.5,.105,.037,h=.075,color='gold',keys=track((0,.5,.12,1,0),(.12,.5,.105,1,1),(.68,.5,.105,1,1),(.83,.5,.08,1,0),(1,.5,.08,1,0))),
      T('sub4','A digital recording stores measurements.',.5,.20,.059,h=.14,keys=track((0,.5,.22,1,0),(.18,.5,.20,1,1),(.68,.5,.20,1,1),(.83,.5,.16,1,0),(1,.5,.16,1,0))),
      L('complex','wave',.5,.48,.82,.31,keys=track((0,.5,.48,1,1),(.27,.5,.48,1,1),(.52,.5,.48,1,.35),(.69,.5,.48,1,0),(1,.5,.48,1,0)),**wave_complex),
      L('samples','samples',.5,.48,.82,.31,color='gold',harmonics=1.,keys=track((0,.5,.48,1,0),(.18,.5,.48,1,0),(.42,.5,.48,1,1),(.70,.5,.48,1,1),(1,.5,.48,1,.20))),
      T('samples-label','Each point records the signal at a moment in time.',.5,.77,.047,h=.14,keys=track((0,.5,.77,1,0),(.25,.5,.77,1,0),(.48,.5,.77,1,1),(.69,.5,.77,1,1),(.83,.5,.77,1,0),(1,.5,.77,1,0))),
      T('final','FROM MOTION TO MUSIC',.5,.48,.086,h=.21,keys=track((0,.5,.51,.95,0),(.72,.5,.51,.95,0),(.87,.5,.48,1,1),(1,.5,.48,1,1)),color='white',depth=-.3),
      T('credit','SKELLYMOTION',.5,.70,.034,h=.08,color='gold',keys=track((0,.5,.72,1,0),(.76,.5,.72,1,0),(.93,.5,.70,1,1),(1,.5,.70,1,1)))
      ])
    return comps

def plan_for():
    # Cut positions match the original score's absolute beat clock.
    beats=[0,12,24,38,50,66];cuts=[round(b*60/score.DOC_BPM*FPS) for b in beats];scenes=[]
    for i,(a,b,g) in enumerate(zip(cuts,cuts[1:],compositions())):
        scenes.append(dict(type='big_text',text=g['title'],start=a/FPS,end=b/FPS,frames=b-a,captions=[],camera='still',cinematic_finish=True,brand='SKELLYMOTION',chapter=i+1,editorial='graphic',editorial_look='midnight',graphic=g))
    p=dict(version=d.VERSION,preset='doc',fps=FPS,duration=cuts[-1]/FPS,frames=cuts[-1],scenes=scenes,director='local',audio_start=0.,silent=False,cinematic_finish=True,caption_style='off',caption_track=[],crossfades=False,sound_design=True,music_gain=1.8,cue_gain=0.,voice_style='natural')
    d.configure_spatial(scenes,FPS);return p

def main():
    root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=False);assets=root/'assets';assets.mkdir();p=plan_for();audio=root/'silent-source.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(round(p['duration']*24000)*2))
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,round(length,3),flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    output=root/'The-Shape-of-Sound.mp4';print('START',p['duration'],p['frames'],flush=True)
    stats=d.render(p,audio,assets,root/'cache',output,{'fps':FPS},(960,540),lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True));report=intel.review(p)
    (root/'plan.json').write_text(json.dumps(p,indent=2));(root/'report.json').write_text(json.dumps({'render':stats,'review':report,'fft':data()},indent=2));score.write_score(p,root/'score.wav',music_gain=1.8,cue_gain=0.);print('RESULT',stats,report,flush=True)
if __name__=='__main__':main()
