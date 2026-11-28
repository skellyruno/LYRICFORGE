"""Opt-in CI proof. Model downloads are explicit; inference is then offline.
No fabricated model output, private user content, or implicit fallback.
"""
import argparse, hashlib, json, math, os, re, subprocess, sys, time
from pathlib import Path

MODELS={'whisper':'Systran/faster-whisper-tiny.en','vision':'openai/clip-vit-base-patch32'}

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def download(root):
    from huggingface_hub import HfApi, snapshot_download
    result={}
    for key,repo in MODELS.items():
        revision=HfApi().model_info(repo).sha
        patterns=['*.json','*.txt','model.bin'] if key=='whisper' else ['*.json','*.txt','model.safetensors']
        path=Path(snapshot_download(repo,revision=revision,allow_patterns=patterns,local_dir=root/key)).resolve()
        weight=path/('model.bin' if key=='whisper' else 'model.safetensors')
        if not weight.is_file():raise RuntimeError('Required model weights unavailable: '+repo)
        result[key]={'repo':repo,'revision':revision,'path':str(path),'weight_sha256':sha(weight)}
    return result

def words(s):return re.findall(r"[a-z0-9']+",s.lower())

def wer(reference,observed):
    a,b=words(reference),words(observed);row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        next_row=[i]
        for j,y in enumerate(b,1):next_row.append(min(next_row[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=next_row
    return row[-1]/max(1,len(a))

def run(candidate,neural,out,models):
    from PIL import Image,ImageDraw
    candidate,neural,out,models=map(lambda p:Path(p).resolve(),(candidate,neural,out,models))
    out.mkdir(parents=True,exist_ok=False)
    manifest=download(models)
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',
                      WHISPER_MODEL=manifest['whisper']['path'],WHISPER_DEVICE='cpu',
                      LYRICFORGE_DATA=str(out/'workspace'),OMP_NUM_THREADS='2')
    sys.path.insert(0,str(candidate))
    import server
    clock=json.loads((neural/'report.json').read_text())
    source=neural/clock['take']/'neural-0000.wav'
    reference=clock['chapters'][0]['text']
    if sha(source)!=clock['chapters'][0]['sha256']:raise ValueError('Narration source changed')
    start=time.monotonic()
    model=server.load_model()
    segments,_=model.transcribe(str(source),language='en',beam_size=3,word_timestamps=True,vad_filter=False)
    segments=list(segments);observed=' '.join(s.text.strip() for s in segments)
    timed=[{'word':w.word,'start':w.start,'end':w.end} for s in segments for w in (s.words or [])]
    error=wer(reference,observed)
    speech={'reference':reference,'observed':observed,'wer':error,'words':timed,'seconds':time.monotonic()-start}
    (out/'whisper.json').write_text(json.dumps(speech,indent=2))
    if not timed or error>.30 or any(not math.isfinite(w['start']) or not math.isfinite(w['end']) or not 0<=w['start']<w['end']<=clock['chapters'][0]['phrase_samples']/clock['sample_rate']+.2 for w in timed):
        raise RuntimeError('Real Whisper timing/recognition gate failed')
    paths=[]
    for color in ('red','blue'):
        im=Image.new('RGB',(320,320),'#ffffff');ImageDraw.Draw(im).rectangle((40,40,280,280),fill=color)
        path=out/(color+'.png');im.save(path);paths.append(str(path))
    # Use a genuine Creator-rendered technical diagram as an additional
    # diagnostic; unlike the color controls, its semantic score is review-only.
    from studio_editorial import technical_frame
    diagram=out/'technical-diagram.png';technical_frame('Spectral ducking',.5).save(diagram);paths.append(str(diagram))
    prompts=['a red square on a white background','a blue square on a white background','a scientific frequency graph with a curve']
    request={'operation':'match','model':manifest['vision']['path'],'images':paths,'texts':prompts}
    start=time.monotonic()
    raw=subprocess.run([sys.executable,str(candidate/'studio_ai_worker.py')],input=json.dumps(request),text=True,capture_output=True,check=True,timeout=600)
    scores=json.loads(raw.stdout)['scores']
    if len(scores)!=3 or any(len(r)!=3 or not all(math.isfinite(x) for x in r) for r in scores):raise RuntimeError('Invalid actual vision inference scores')
    (out/'vision.json').write_text(json.dumps({'prompts':prompts,'scores':scores,'seconds':time.monotonic()-start,'diagram_semantics':'review-only'},indent=2))
    (out/'model-provenance.json').write_text(json.dumps(manifest,indent=2))
    if not (scores[0][0]>scores[1][0] and scores[1][1]>scores[0][1]):raise RuntimeError('Real vision control ranking failed')
    print('Actual Whisper and CLIP model inference passed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('candidate');p.add_argument('neural');p.add_argument('out');p.add_argument('models');a=p.parse_args()
    run(a.candidate,a.neural,a.out,a.models)
