"""Optional local Kokoro worker. No bundled weights, network calls or shell commands."""
import json,sys,wave
from pathlib import Path


def main():
    if len(sys.argv)!=4:raise ValueError('Expected local model, voices, output directory')
    request=json.loads(sys.stdin.read(1024*1024+1))
    phrases=request['phrases'];voice=request['voice'];speed=float(request['speed'])
    if not isinstance(phrases,list) or not 1<=len(phrases)<=500 or any(not isinstance(t,str) or not 1<=len(t)<=1800 for t in phrases):
        raise ValueError('Invalid phrase list')
    if voice not in ('am_michael','am_adam','af_sarah') or not .75<=speed<=1.25:
        raise ValueError('Invalid local voice or speed')
    root=Path(sys.argv[3])
    if not root.is_dir() or root.is_symlink():raise ValueError('Invalid output directory')
    import numpy as np
    from kokoro_onnx import Kokoro
    engine=Kokoro(sys.argv[1],sys.argv[2])
    total_seconds=0.
    for i,text in enumerate(phrases):
        samples,rate=engine.create(text,voice=voice,speed=speed,lang='en-us')
        x=np.asarray(samples,dtype=np.float32)
        if x.ndim!=1 or not 8000<=rate<=48000 or not 0<x.size<=rate*50 or not np.isfinite(x).all():
            raise ValueError('Invalid neural audio')
        total_seconds+=x.size/rate
        if total_seconds>1800:raise ValueError('Narration exceeds 30 minutes')
        if np.max(np.abs(x))<1e-5:raise ValueError('Silent neural phrase')
        target=root/f'neural-{i:04d}.wav'
        if target.exists():raise ValueError('Refusing to overwrite neural output')
        with wave.open(str(target),'wb') as out:
            out.setparams((1,2,int(rate),0,'NONE','not compressed'))
            out.writeframes(np.rint(np.clip(x,-1.,1.)*32767).astype('<i2').tobytes())
    return 0


if __name__=='__main__':raise SystemExit(main())
