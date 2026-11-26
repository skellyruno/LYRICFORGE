"""Optional local Kokoro worker. No bundled weights, network calls or shell commands."""
import json,sys,wave
from pathlib import Path


def main():
    if len(sys.argv)!=4:raise ValueError('Expected local model, voices, output directory')
    request=json.loads(sys.stdin.read(1024*1024+1))
    phrases=request['phrases'];voice=request['voice'];speed=float(request['speed'])
    if not isinstance(phrases,list) or not 1<=len(phrases)<=500 or any(not isinstance(t,str) or not 1<=len(t)<=1800 for t in phrases):
        raise ValueError('Invalid phrase list')
    if voice not in ('am_michael','am_adam','af_sarah') or not .70<=speed<=1.30:
        raise ValueError('Invalid local voice or speed')
    root=Path(sys.argv[3])
    if not root.is_dir() or root.is_symlink():raise ValueError('Invalid output directory')
    import numpy as np
    from kokoro_onnx import Kokoro
    # Explicit CPU-only audition budget; leave ordinary operator-configured
    # providers alone. Modern Kokoro handles the model's actual input dtype.
    import os
    if os.environ.get('LYRICFORGE_KOKORO_THREADS') and hasattr(Kokoro,'from_session'):
        import onnxruntime as ort
        options=ort.SessionOptions()
        options.intra_op_num_threads=max(1,min(4,int(os.environ['LYRICFORGE_KOKORO_THREADS'])))
        options.inter_op_num_threads=1
        session=ort.InferenceSession(sys.argv[1],sess_options=options,providers=['CPUExecutionProvider'])
        engine=Kokoro.from_session(session,sys.argv[2])
    else:
        engine=Kokoro(sys.argv[1],sys.argv[2])
    total_seconds=0.
    for i,text in enumerate(phrases):
        samples,rate=engine.create(text,voice=voice,speed=speed,lang='en-us')
        x=np.asarray(samples,dtype=np.float32)
        if x.ndim==2 and 1 in x.shape:x=x.reshape(-1)
        if x.ndim!=1 or not 8000<=rate<=48000 or not 0<x.size<=rate*50 or not np.isfinite(x).all():
            raise ValueError('Invalid neural audio')
        total_seconds+=x.size/rate
        if total_seconds>1800:raise ValueError('Narration exceeds 30 minutes')
        peak=float(np.max(np.abs(x)))
        if peak<1e-5:raise ValueError('Silent neural phrase')
        # Preserve an unclipped waveform if an exported model overshoots 0 dBFS.
        if peak>.98:x=x*(.98/peak)
        target=root/f'neural-{i:04d}.wav'
        if target.exists():raise ValueError('Refusing to overwrite neural output')
        with wave.open(str(target),'wb') as out:
            out.setparams((1,2,int(rate),0,'NONE','not compressed'))
            out.writeframes(np.rint(np.clip(x,-1.,1.)*32767).astype('<i2').tobytes())
    return 0


if __name__=='__main__':raise SystemExit(main())
