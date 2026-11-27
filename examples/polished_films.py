"""Director editions: caller-supplied original plans and media, preserved in place."""
import argparse,json,subprocess,sys,wave
from pathlib import Path
from copy import deepcopy
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_director as d
import studio_director_intelligence as intel
import studio_layers as layers
import studio_score as score
from examples.sound_documentary import L,track

def rounded_cube_mesh(n=5):
    v=[];uv=[];faces=[];target=[]
    for axis in range(3):
        for side in (-1,1):
            start=len(v);uaxis=(axis+1)%3;vaxis=(axis+2)%3
            for y in range(n+1):
                for x in range(n+1):
                    p=np.zeros(3);p[axis]=side;p[uaxis]=2*x/n-1;p[vaxis]=2*y/n-1
                    sphere=p/np.linalg.norm(p);v.append((.88*p+.12*sphere).tolist());target.append(sphere.tolist());uv.append([x/n,1-y/n])
            for y in range(n):
                for x in range(n):
                    a=start+y*(n+1)+x;b=a+1;c=a+n+1;e=c+1
                    faces.extend([[a,b,e],[a,e,c]] if side==1 else [[a,e,b],[a,c,e]])
    return {'vertices':v,'uv':uv,'faces':faces,'target':target}

def polish(base,kind):
    p=deepcopy(base);p['version']=d.VERSION;p['score_arc']='cinematic';p['auto_repair_layout']=True
    p['music_gain']=1.75;p['cue_gain']=0.;p['caption_style']='off';p['caption_track']=[]
    for i,s in enumerate(p['scenes']):
        g=s['graphic']
        for l in g['layers']:
            if len(l['track'])>2:l['curve']='continuous'
            if l['type']=='text' and kind=='sound':
                ident=l['id']
                if ident.startswith('section') or ident=='credit':l['face']='mono'
                if ident.startswith('sub') or ident in ('opening','final'):l['face']='serif'
        if kind=='sound' and i==0:
            next(x for x in g['layers'] if x['id']=='opening').update(text='The Shape of Sound',size=.102)
            g['layers'].append(L('episode','text',.5,.19,.68,.07,text='FIELD NOTES  /  01',size=.032,face='mono',color='gold',keys=track((0,.5,.20,1,0),(.12,.5,.19,1,1),(.36,.5,.19,1,1),(.48,.5,.17,1,0),(1,.5,.17,1,0)),depth=-.1))
        if kind=='sound' and i==4:
            next(x for x in g['layers'] if x['id']=='final')['text']='From motion to music.'
            next(x for x in g['layers'] if x['id']=='credit')['text']='SKELLYMOTION  /  FIELD NOTES'
        if kind=='image' and i==4:
            orb=next(x for x in g['layers'] if x['id']=='orb');orb.update(type='mesh',mesh=rounded_cube_mesh(),metal=.12,roughness=.34,spin=.42,shutter=.016,morph=[[0,0],[.26,0],[.78,1],[1,1]],curve='continuous')
            g['source']='24 × 12 AVERAGED SOURCE COLORS, DISPLAY GAMMA LIFTED  /  UV-TEXTURED MESH MORPH'
            next(x for x in g['layers'] if x['id']=='texture-explain')['text']='One texture. A changing 3D surface.'
        s['graphic']=layers.validate(g)
    d.configure_spatial(p['scenes'],p['fps']);return p

def run(kind,plan_path,assets,root,size=(1280,720)):
    root.mkdir(parents=True,exist_ok=False);p=polish(json.loads(plan_path.read_text()),kind);audio=root/'silence.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(round(p['duration']*24000)*2))
    def enc(args,cwd,length,stage,*_):
        print('ENCODE',stage,length,flush=True);r=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=300)
        if r.returncode:raise RuntimeError(r.stderr[-5000:])
    output=root/'film.mp4';print('START',kind,p['frames'],flush=True)
    result=d.render(p,audio,assets,root/'cache',output,{'fps':p['fps']},size,lambda rows,path:path.write_text(''),enc,lambda:None,lambda *a:print('SCENES',a,flush=True));report=intel.review(p)
    (root/'plan.json').write_text(json.dumps(p,indent=2));(root/'report.json').write_text(json.dumps({'render':result,'review':report,'score':'original cinematic arc, music-led'},indent=2));print('RESULT',result,report,flush=True)
    score.write_score(p,root/'score.wav',music_gain=p['music_gain'],cue_gain=0.)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('kind',choices=['sound','image']);a.add_argument('plan',type=Path);a.add_argument('assets',type=Path);a.add_argument('out',type=Path);a.add_argument('--height',type=int,default=720);o=a.parse_args();run(o.kind,o.plan,o.assets,o.out,(o.height*16//9,o.height))
