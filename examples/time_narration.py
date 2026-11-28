"""Explicit neural narration production for Field Notes 05. No implicit downloads."""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys,wave
from pathlib import Path
import numpy as np

BPM=88;FPS=60;RATE=24000
SCRIPT=[
    'We cannot see time itself. We notice it when something changes. A shadow moves, a sound fades, a moment passes.',
    'A repeated movement gives us a way to count time. Each complete cycle can become a unit, and each unit can be divided.',
    'A moving image samples a continuous world. Twenty-four frames and sixty frames divide the same second into different numbers of observations.',
    'Rhythm is the spacing between events. Change that spacing, and the very same movement can feel calm, urgent, or almost still.',
    'Combine two periodic motions, and their relationship draws a new shape. A simple ratio of frequencies can make a surprisingly intricate path.',
    'A picture captures an instant. A sequence captures change. Time is the dimension that lets those separate moments become a story.'
]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def assemble(root,phrases=SCRIPT):
    root=Path(root);cuts=[round(b*60/BPM*FPS)*RATE//FPS for b in range(0,97,16)];out=np.zeros(cuts[-1],dtype='<i2');rows=[]
    for i,phrase in enumerate(phrases):
        p=root/f'neural-{i:04d}.wav'
        with wave.open(str(p),'rb') as w:
            if (w.getnchannels(),w.getsampwidth(),w.getframerate())!=(1,2,RATE):raise ValueError('Unexpected neural phrase format')
            x=np.frombuffer(w.readframes(w.getnframes()),dtype='<i2')
        if not x.size or np.max(np.abs(x.astype(np.int32)))<30:raise ValueError('Empty or silent phrase')
        start=cuts[i]+RATE//2;end=start+len(x)
        if end>cuts[i+1]-RATE//4:raise ValueError(f'Chapter {i+1} needs a longer shot; refusing to truncate narration')
        out[start:end]=x;rows.append({'chapter':i+1,'text':phrase,'start':start/RATE,'end':end/RATE,'sha256':sha(p)})
    target=root/'narration.wav'
    with wave.open(str(target),'wb') as w:w.setparams((1,2,RATE,0,'NONE','not compressed'));w.writeframes(out.tobytes())
    return {'duration':len(out)/RATE,'sample_rate':RATE,'chapters':rows,'sha256':sha(target)}

def main():
    p=argparse.ArgumentParser();p.add_argument('model',type=Path);p.add_argument('voices',type=Path);p.add_argument('out',type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    worker=Path(__file__).resolve().parents[1]/'studio_kokoro_worker.py'
    req={'phrases':SCRIPT,'voice':'am_michael','speed':1.04}
    subprocess.run([sys.executable,str(worker),str(a.model.resolve()),str(a.voices.resolve()),str(a.out.resolve())],input=json.dumps(req),text=True,check=True,timeout=900)
    report=assemble(a.out);report.update({'provider':'Kokoro','voice':'am_michael','model_sha256':sha(a.model),'voices_sha256':sha(a.voices),'speed':req['speed']});(a.out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
if __name__=='__main__':main()
