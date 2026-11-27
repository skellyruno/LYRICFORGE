"""Generate a fresh Field Notes 06 narration from the exact archived script."""
import argparse,ast,hashlib,json,subprocess,sys,wave
from pathlib import Path
import numpy as np
RATE=24000;FPS=60;BPM=88

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read_script(candidate):
    tree=ast.parse((candidate/'examples/frequency_documentary.py').read_text(encoding='utf-8'))
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCRIPT' for t in n.targets):
            script=ast.literal_eval(n.value)
            if isinstance(script,list) and len(script)==5 and all(isinstance(t,str) and t for t in script):return script
    raise ValueError('Missing exact five-chapter script')
def assemble(root,script):
    root=Path(root);cuts=[round(b*60/BPM*FPS)*RATE//FPS for b in range(0,81,16)];out=np.zeros(cuts[-1],dtype='<i2');rows=[]
    if len(script)!=5:raise ValueError('Expected five chapters')
    for i,phrase in enumerate(script):
        p=root/f'neural-{i:04d}.wav'
        with wave.open(str(p),'rb') as f:
            if (f.getnchannels(),f.getsampwidth(),f.getframerate())!=(1,2,RATE):raise ValueError('Unexpected phrase format')
            x=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
        if not x.size or np.max(np.abs(x.astype(np.int32)))<30:raise ValueError('Silent phrase')
        start=cuts[i]+RATE//3;end=start+len(x)
        if end>cuts[i+1]-RATE//4:raise ValueError(f'Chapter {i+1} exceeds shot; refusing truncation')
        out[start:end]=x;rows.append({'chapter':i+1,'text':phrase,'start':start/RATE,'end':end/RATE,'sha256':sha(p)})
    target=root/'narration.wav'
    if target.exists():raise FileExistsError(target)
    with wave.open(str(target),'wb') as f:f.setparams((1,2,RATE,0,'NONE','not compressed'));f.writeframes(out.tobytes())
    return {'duration':len(out)/RATE,'sample_rate':RATE,'chapters':rows,'sha256':sha(target)}
def main():
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path);p.add_argument('model',type=Path);p.add_argument('voices',type=Path);p.add_argument('out',type=Path);a=p.parse_args();script=read_script(a.candidate)
    # Retry with a modest faster delivery only if a chapter exceeds its allocated clock.
    a.out.mkdir(parents=True,exist_ok=False)
    for speed in (1.08,1.16,1.24):
        take=a.out/f'take-{speed:.2f}';take.mkdir()
        req={'phrases':script,'voice':'am_michael','speed':speed}
        subprocess.run([sys.executable,str(a.candidate/'studio_kokoro_worker.py'),str(a.model.resolve()),str(a.voices.resolve()),str(take.resolve())],input=json.dumps(req),text=True,check=True,timeout=900)
        try:report=assemble(take,script)
        except ValueError as exc:
            if 'exceeds shot' not in str(exc):raise
            print(str(exc),flush=True);continue
        report.update({'provider':'Kokoro','voice':'am_michael','model_sha256':sha(a.model),'voices_sha256':sha(a.voices),'speed':speed,'take':take.name})
        (a.out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return
    raise ValueError('All neural takes exceed chapter clock; extend shots instead of truncating')
if __name__=='__main__':main()
