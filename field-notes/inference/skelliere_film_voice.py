"""Generate original neural product narration using Motion's existing Kokoro worker."""
import json, os, sys, subprocess, wave, hashlib
from pathlib import Path
PHRASES=[[0,6,"Skelliere. One rack. A world of sound."],[6,13,"Build your own signal chain. Eight slots, each with a dedicated processor."],[13,19,"Switch between studio and edit views. Refine the details without losing the bigger picture."],[19,26,"Shape the envelope. From smooth compression to fast transient control."],[26,32,"Divide the signal into frequency regions, with independent multiband controls."],[32,38,"Focus the correction with floating bands. Keep the rest of the signal intact."],[38,42,"Listen to the same signal, before and after."],[50,56,"Bring out detail, add harmonics, or control the peaks with Emerald Clip."],[59,65,"Explore movement, repeats, and texture with flanging, delay, and glitch."],[65,71,"Two independent doubled voices. Control their pitch, delay, level, and pan."],[71,75,"Now hear that difference in stereo."],[83,90,"Shape pitch and transients in the same rack, around the needs of the performance."],[90,98,"Dynamics, tone, color, and space. Choose the processors that serve the sound."],[98,106,"Start with a focused chain. Build on it as your ideas evolve."],[106,114,"Every processor is part of your signal path. Every choice is yours."],[114,120,"Skelliere. Shape the sound."]]
def main():
    model,voices,out=map(Path,sys.argv[1:])
    out.mkdir(parents=True,exist_ok=False)
    phrases=[row[2].replace('Skelliere','Skell ee air') for row in PHRASES]+['One voice. One signal. A wider space.']
    request={'phrases':phrases,'voice':'am_michael','speed':1.04}
    subprocess.run([sys.executable,'studio_kokoro_worker.py',str(model.resolve()),str(voices.resolve()),str(out.resolve())],input=json.dumps(request),text=True,check=True,timeout=600)
    records=[]
    for i,line in enumerate(phrases):
        p=out/f'neural-{i:04d}.wav'
        with wave.open(str(p)) as w:
            duration=w.getnframes()/w.getframerate()
        records.append({'file':p.name,'text':PHRASES[i][2] if i<len(PHRASES) else line,'window':PHRASES[i][:2] if i<len(PHRASES) else [0,4],'seconds':duration,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps({'engine':'Kokoro ONNX 1.0','voice':'am_michael','speed':1.04,'phrases':records,'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'voices_sha256':hashlib.sha256(voices.read_bytes()).hexdigest()},indent=2))
    print(json.dumps(records,indent=2),flush=True)
if __name__=='__main__':main()
