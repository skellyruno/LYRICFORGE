"""Isolated optional emotion-conditioned TTS. No model download or reference voice input."""
import json,math,os,sys,wave
from pathlib import Path

DIRECTIONS={'steady':(.50,.50),'detail':(.35,.50),'reveal':(.72,.36),'compare':(.42,.45),'close':(.62,.32)}
FILES=('ve.safetensors','t3_cfg.safetensors','s3gen.safetensors','tokenizer.json','conds.pt')


def validate(request):
    if not isinstance(request,dict) or set(request)!={'phrases','directions'}:raise ValueError('Expected phrases and voice directions')
    phrases,directions=request['phrases'],request['directions']
    if not isinstance(phrases,list) or not 1<=len(phrases)<=120 or any(not isinstance(s,str) or not s.strip() or len(s)>240 or any(ord(c)<32 for c in s) for s in phrases):raise ValueError('Invalid narration phrases')
    if not isinstance(directions,list) or len(directions)!=len(phrases) or any(not isinstance(s,str) or s not in DIRECTIONS for s in directions):raise ValueError('Invalid expressive directions')
    return list(zip(phrases,directions))


def run(model_dir,output,request):
    rows=validate(request);model_dir=Path(model_dir).resolve(strict=True);output=Path(output)
    if not model_dir.is_dir() or not output.is_dir() or output.is_symlink() or any(not (model_dir/f).is_file() for f in FILES):raise ValueError('Missing local model or output directory')
    if any((output/f'expressive-{i:04d}.wav').exists() for i in range(len(rows))):raise ValueError('Refusing to overwrite narration')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    import inspect,time,numpy as np,torch
    from chatterbox.tts import ChatterboxTTS,Conditionals
    # The built-in voice's conditionals are a small tensor-only checkpoint.
    # Do not use an older unsafe deserializer or caller-provided voice files.
    if 'weights_only=True' not in ''.join(inspect.getsource(Conditionals.load).split()):raise RuntimeError('Require tensor-only conditional loader')
    torch.set_num_threads(min(4,max(1,os.cpu_count() or 1)))
    device='cuda' if torch.cuda.is_available() else 'cpu'
    engine=ChatterboxTTS.from_local(model_dir,device=device)
    if engine.conds is None:raise RuntimeError('Missing built-in voice')
    report=[];total=0.
    for i,(text,direction) in enumerate(rows):
        ex,cfg=DIRECTIONS[direction];torch.manual_seed(1731+i)
        start=time.monotonic()
        with torch.inference_mode():audio=engine.generate(text,exaggeration=ex,cfg_weight=cfg,temperature=.55)
        x=audio.detach().cpu().numpy().astype(np.float32).reshape(-1);rate=int(engine.sr)
        if not 8000<=rate<=48000 or not 0<x.size<=rate*50 or not np.isfinite(x).all():raise ValueError('Invalid expressive output')
        peak=float(np.max(np.abs(x)));duration=x.size/rate;total+=duration
        if peak<1e-5 or total>1800:raise ValueError('Silent or oversized narration')
        if peak>.98:x=x*(.98/peak)
        target=output/f'expressive-{i:04d}.wav'
        with wave.open(str(target),'wb') as f:f.setparams((1,2,rate,0,'NONE','not compressed'));f.writeframes(np.rint(x*32767).astype('<i2').tobytes())
        report.append({'file':target.name,'direction':direction,'exaggeration':ex,'cfg_weight':cfg,'duration':duration,'generation_seconds':time.monotonic()-start,'peak':float(np.max(np.abs(x))),'rms':float(np.sqrt(np.mean(x*x))),'device':device})
    return report


if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('Expected local model and output directory')
    payload=sys.stdin.read(128*1024+1)
    if len(payload)>128*1024:raise SystemExit('Oversized request')
    print(json.dumps(run(sys.argv[1],sys.argv[2],json.loads(payload)),allow_nan=False))
