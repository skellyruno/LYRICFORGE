"""Generate fresh neural narration, then derive a frame-exact, beat-aligned clock.
The authored text is not shortened, the generated speech is not stretched, and
no phrase is truncated. Only chapter lengths may increase.
"""
import argparse,ast,hashlib,json,math,subprocess,sys,wave
from pathlib import Path
import numpy as np
RATE=24000; FPS=60; BPM=88; SAMPLES_PER_FRAME=RATE//FPS
LEAD=RATE//3; TAIL=RATE//4

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read_script(candidate):
    tree=ast.parse((candidate/'examples/frequency_documentary.py').read_text(encoding='utf-8'))
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCRIPT' for t in n.targets):
            script=ast.literal_eval(n.value)
            if isinstance(script,list) and len(script)==5 and all(isinstance(t,str) and t for t in script):return script
    raise ValueError('Missing exact five-chapter script')

def allocate(lengths):
    """Extend chapters on the score's four-beat grid; never shorten the 16-beat originals."""
    if len(lengths)!=5 or any(not isinstance(n,int) or not 0<n<=RATE*50 for n in lengths):raise ValueError('Invalid phrase lengths')
    cuts=[0]; beats=[0]
    for n in lengths:
        b=beats[-1]+16
        while (round(b*60/BPM*FPS)-cuts[-1])*SAMPLES_PER_FRAME < n+LEAD+TAIL:
            b+=4
        beats.append(b);cuts.append(round(b*60/BPM*FPS))
    return cuts,beats

def assemble(root,script):
    root=Path(root);phrases=[];paths=[]
    if len(script)!=5:raise ValueError('Expected five chapters')
    for i in range(len(script)):
        p=root/f'neural-{i:04d}.wav'
        with wave.open(str(p),'rb') as f:
            if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,RATE):raise ValueError('Unexpected phrase format')
            if not 0<f.getnframes()<=RATE*50:raise ValueError('Invalid phrase length')
            x=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
        if not x.size or np.max(np.abs(x.astype(np.int32)))<30:raise ValueError('Silent phrase')
        phrases.append(x);paths.append(p)
    cuts,beats=allocate([len(x) for x in phrases]);out=np.zeros(cuts[-1]*SAMPLES_PER_FRAME,dtype='<i2');rows=[]
    for i,(phrase,x,p) in enumerate(zip(script,phrases,paths)):
        start=cuts[i]*SAMPLES_PER_FRAME+LEAD;end=start+len(x)
        if end>cuts[i+1]*SAMPLES_PER_FRAME-TAIL:raise RuntimeError('Chapter allocation mismatch')
        out[start:end]=x;rows.append({'chapter':i+1,'text':phrase,'start':start/RATE,'end':end/RATE,'start_frame':cuts[i],'end_frame':cuts[i+1],'start_beat':beats[i],'end_beat':beats[i+1],'phrase_samples':len(x),'sha256':sha(p)})
    target=root/'narration.wav'
    if target.exists():raise FileExistsError(target)
    with wave.open(str(target),'wb') as f:f.setparams((1,2,RATE,0,'NONE','not compressed'));f.writeframes(out.tobytes())
    return {'duration':len(out)/RATE,'frames':cuts[-1],'fps':FPS,'sample_rate':RATE,'chapter_frames':cuts,'chapter_beats':beats,'chapters':rows,'sha256':sha(target),'requires_picture_retime':cuts!=[round(b*60/BPM*FPS) for b in range(0,81,16)]}

def main():
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path);p.add_argument('model',type=Path);p.add_argument('voices',type=Path);p.add_argument('out',type=Path);a=p.parse_args();script=read_script(a.candidate)
    a.out.mkdir(parents=True,exist_ok=False);take=a.out/'take-1.00';take.mkdir();speed=1.0
    req={'phrases':script,'voice':'am_michael','speed':speed}
    subprocess.run([sys.executable,str(a.candidate/'studio_kokoro_worker.py'),str(a.model.resolve()),str(a.voices.resolve()),str(take.resolve())],input=json.dumps(req),text=True,check=True,timeout=900)
    report=assemble(take,script)
    report.update({'provider':'Kokoro','voice':'am_michael','model_sha256':sha(a.model),'voices_sha256':sha(a.voices),'speed':speed,'take':take.name})
    (a.out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'duration':report['duration'],'chapter_frames':report['chapter_frames'],'requires_picture_retime':report['requires_picture_retime']}),flush=True)
if __name__=='__main__':main()
