"""Retry independent real-model checks against a verified staged application.
Explicit downloads only during setup. Never use pickle vision weights or mock inference.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import wave

MODELS = {
    'whisper': {
        'repo': 'Systran/faster-whisper-tiny.en', 'revision': '0d3d19a',
        'weight': 'model.bin', 'sha256': '1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a',
        'files': ['config.json','model.bin','tokenizer.json','vocabulary.txt'],
    },
    'vision': {
        'repo': 'laion/CLIP-ViT-B-32-laion2B-s34B-b79K',
        'revision': '1a25a446712ba5ee05982a381eed697ef9b435cf',
        'weight': 'model.safetensors', 'sha256': '74813fbcdc750f235c9784c367ca1394d2a5c25eb0aac92761752ac239db7cff',
        'files': ['config.json','model.safetensors','preprocessor_config.json','tokenizer_config.json','tokenizer.json','special_tokens_map.json','merges.txt','vocab.json'],
    },
}

def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()

def verify_files(path,spec):
    missing=[name for name in spec['files'] if not (path/name).is_file()]
    if missing:raise ValueError('Missing model files: '+', '.join(missing))
    actual=sha(path/spec['weight'])
    if actual!=spec['sha256']:raise ValueError('Model weight checksum mismatch')
    return actual

def prepare_model(kind,root):
    from huggingface_hub import HfApi, snapshot_download
    spec=MODELS[kind]
    revision=HfApi().model_info(spec['repo'],revision=spec['revision']).sha
    path=Path(snapshot_download(spec['repo'],revision=revision,allow_patterns=spec['files'],local_dir=root/kind)).resolve()
    weight=verify_files(path,spec)
    return path,{'repo':spec['repo'],'revision':revision,'weight_sha256':weight}

def words(text):
    return re.findall(r"[a-z0-9']+",text.lower())

def word_error_rate(reference,observed):
    a,b=words(reference),words(observed)
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        nxt=[i]
        for j,y in enumerate(b,1):
            nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=nxt
    return row[-1]/max(1,len(a))

def valid_timing(timed,duration):
    if not timed or not math.isfinite(duration) or duration<=0:return False
    previous=0.
    for w in timed:
        a,b=w['start'],w['end']
        if not all(map(math.isfinite,(a,b))) or not 0<=a<b<=duration+.2 or a<previous-.05:return False
        previous=a
    return True

def valid_vision(scores):
    return (len(scores)==3 and all(len(r)==3 and all(math.isfinite(x) for x in r) for r in scores)
            and scores[0][0]>scores[0][1] and scores[1][1]>scores[1][0]
            and scores[0][0]>scores[1][0] and scores[1][1]>scores[0][1])

def write(path,data):
    path.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')

def speech(candidate,neural,out,path):
    os.environ.update(WHISPER_MODEL=str(path),WHISPER_DEVICE='cpu',LYRICFORGE_DATA=str(out/'workspace'))
    sys.path.insert(0,str(candidate))
    import server
    clock=json.loads((neural/'report.json').read_text())
    reports=[]
    model=server.load_model()
    for i,chapter in enumerate(clock['chapters']):
        source=neural/clock['take']/f'neural-{i:04d}.wav'
        if sha(source)!=chapter['sha256']:raise ValueError('Narration source checksum mismatch')
        with wave.open(str(source)) as f:duration=f.getnframes()/f.getframerate()
        start=time.monotonic()
        segments,_=model.transcribe(str(source),language='en',beam_size=3,word_timestamps=True,vad_filter=False)
        segments=list(segments)
        observed=' '.join(s.text.strip() for s in segments)
        timed=[{'word':w.word,'start':float(w.start),'end':float(w.end)} for s in segments for w in (s.words or [])]
        error=word_error_rate(chapter['text'],observed)
        reports.append({'chapter':i+1,'reference':chapter['text'],'observed':observed,'wer':error,'words':timed,
                        'valid_timing':valid_timing(timed,duration),'seconds':time.monotonic()-start,'audio_seconds':duration})
        write(out/'whisper.json',reports)
    if len(reports)!=5 or any(not r['valid_timing'] or r['wer']>.30 for r in reports):
        raise RuntimeError('Actual Whisper chapter recognition or timing failed')

def vision(candidate,out,path):
    from PIL import Image,ImageDraw
    sys.path.insert(0,str(candidate))
    from studio_editorial import technical_frame
    paths=[]
    for color in ('red','blue'):
        im=Image.new('RGB',(320,320),'white')
        ImageDraw.Draw(im).rectangle((40,40,280,280),fill=color)
        dest=out/(color+'.png');im.save(dest);paths.append(str(dest))
    diagram=out/'technical-diagram.png'
    technical_frame('Spectral ducking',.5).save(diagram);paths.append(str(diagram))
    prompts=['a red square on a white background','a blue square on a white background','a scientific frequency graph with a curve']
    request={'operation':'match','model':str(path),'images':paths,'texts':prompts}
    start=time.monotonic()
    raw=subprocess.run([sys.executable,str(candidate/'studio_ai_worker.py')],input=json.dumps(request),text=True,capture_output=True,timeout=600)
    if raw.returncode:raise RuntimeError('Actual vision worker failed: '+raw.stdout[-1000:]+' '+raw.stderr[-1000:])
    scores=json.loads(raw.stdout)['scores']
    write(out/'vision.json',{'prompts':prompts,'scores':scores,'seconds':time.monotonic()-start,'diagram_semantics':'review-only'})
    if not valid_vision(scores):raise RuntimeError('Actual vision controls failed ranking gate')

def run(kind,candidate,neural,out,models):
    candidate,neural,out,models=map(lambda p:Path(p).resolve(),(candidate,neural,out,models))
    out.mkdir(parents=True,exist_ok=False)
    try:
        path,manifest=prepare_model(kind,models)
        write(out/'model-provenance.json',manifest)
        os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',OMP_NUM_THREADS='2')
        if kind=='whisper':speech(candidate,neural,out,path)
        else:vision(candidate,out,path)
        write(out/'result.json',{'kind':kind,'status':'passed'})
    except Exception as e:
        write(out/'result.json',{'kind':kind,'status':'failed','error':str(e)})
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('kind',choices=MODELS);p.add_argument('candidate');p.add_argument('neural');p.add_argument('out');p.add_argument('models')
    a=p.parse_args();run(a.kind,a.candidate,a.neural,a.out,a.models)
