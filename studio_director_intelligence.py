"""Independent director intelligence: bounded visual analysis, beat grid, QA and optional local AI.

No remote downloads, network calls, or arbitrary code execution. Optional trusted
local diffusion model is installed separately by the user; not part of the EXE.
"""
from __future__ import annotations
import hashlib
import math
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat
import studio_performance as perf
import studio_audio as audio
import studio_beat as beat

FORMATS = {'youtube': ('landscape', None, False), 'reel15': ('portrait', 15., False),
           'reel30': ('portrait', 30., False), 'square': ('square', None, False),
           'canvas': ('portrait', 7.5, True)}
VARIATIONS = ('clean', 'mirror', 'reverse', 'grade', 'mirror_reverse', 'vignette')


def beat_info(path: Path, duration: float, start: float = 0.) -> dict:
    # Analyze a bounded excerpt. Grid is a steady-tempo estimate, not a claim
    # of perfect tracking for variable tempo material.
    length = min(duration, 90.)
    samples = audio.decode_mono(path, rate=beat.RATE, start=start, length=length)
    result = beat.analyze(samples, length)
    if duration > length:
        result['limited'] = True
    return result


def cut_boundaries(analysis: dict, duration: float, fps: int, lines: list[dict], intensity: str) -> list[int]:
    end = max(1, round(duration*fps))
    if analysis.get('confidence',0) < beat.LOW_CONFIDENCE or len(analysis.get('beats',[])) < 8:
        return []
    cuts = beat.plan_cuts(analysis, duration, intensity)
    candidates = sorted({round(c['start']*fps) for c in cuts if 0<c['start']<duration})
    lyric_ends = [round(float(x['end'])*fps) for x in lines]
    # Keep beat alignment, but avoid splitting right beside a lyric boundary;
    # move to an adjacent beat when that beat is closer to the phrase end.
    grid = sorted({round(t*fps) for t in analysis['beats'] if 0<t<duration})
    result = [0]; minimum = max(1,round(.75*fps))
    for point in candidates:
        near = [x for x in lyric_ends if abs(x-point)<=round(.20*fps)]
        if near:
            proposed = min(grid, key=lambda g: abs(g-near[0]))
            if abs(proposed-point)<=round(.25*fps): point=proposed
        if point-result[-1]>=minimum and end-point>=minimum: result.append(point)
    # For very long tracks, don't extrapolate the estimated grid past the
    # analyzed portion; keep bounded rhythmic fallback shots instead.
    while end-result[-1]>8*fps: result.append(result[-1]+4*fps)
    return result[1:]+[end]


def frame_features(image: Image.Image) -> dict:
    im=ImageOps.exif_transpose(image).convert('RGB'); w,h=im.size
    sample=im.resize((64,64)); grey=sample.convert('L'); stat=ImageStat.Stat(grey)
    edge=ImageStat.Stat(grey.filter(ImageFilter.FIND_EDGES)).mean[0]/255
    hsv=ImageStat.Stat(sample.convert('HSV')).mean
    small=grey.resize((9,8)); pix=list(small.tobytes())
    bits=sum(int(pix[r*9+c]>pix[r*9+c+1]) << (r*8+c) for r in range(8) for c in range(8))
    # Weighted edge centroid: simple saliency proxy, not face/object detection.
    e=list(grey.filter(ImageFilter.FIND_EDGES).tobytes()); total=1.; sx=sy=0.
    for y in range(4,60):
        for x in range(4,60):
            weight=e[y*64+x]; total+=weight; sx+=weight*x; sy+=weight*y
    exposure=1-min(1,abs(stat.mean[0]-128)/128)
    return {'width':w,'height':h,'brightness':round(stat.mean[0]/255,3),'contrast':round(stat.stddev[0]/128,3),
            'saturation':round(hsv[1]/255,3),'detail':round(edge,3),'quality':round(.65*exposure+.35*min(1,stat.stddev[0]/48),3),
            'focus':[round(max(.15,min(.85,sx/total/64)),3),round(max(.15,min(.85,sy/total/64)),3)],'hash':f'{bits:016x}'}


def analyze_asset(path: Path) -> dict:
    if path.suffix.lower() in {'.jpg','.jpeg','.png','.webp'}:
        with Image.open(path) as image: return frame_features(image)
    # Two tiny decoded samples, no full-video decoding/buffering.
    from studio_clips import probe_media
    info=probe_media(path); duration=float(info.get('duration',0))
    if duration<=0: return {}
    frames=[]
    for t in (min(duration*.15,2),min(duration*.65,12)):
        r=subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',f'{t:.3f}','-i',str(path),'-frames:v','1','-vf','scale=96:96:force_original_aspect_ratio=decrease,pad=96:96:(ow-iw)/2:(oh-ih)/2','-f','image2pipe','-vcodec','png','-'],capture_output=True,timeout=12,**perf.windows_child_options(False))
        if r.returncode==0 and r.stdout:
            import io
            with Image.open(io.BytesIO(r.stdout)) as im: frames.append(im.convert('RGB'))
    if not frames: return {}
    features=frame_features(frames[0]); features.update(width=info.get('width',96),height=info.get('height',96),duration=duration)
    features['motion']=round(ImageStat.Stat(ImageChops.difference(frames[0],frames[-1])).mean[0]/255,3)
    return features


def diversity(a: dict, b: dict) -> float:
    try: return (int(a['hash'],16)^int(b['hash'],16)).bit_count()/64
    except (KeyError,ValueError,TypeError): return .5


def diagram_kind(text: str) -> str | None:
    t=set(re.findall(r'[a-z]+',text.lower()))
    if 'piano' in t or ('key' in t and 'scale' in t): return 'Note selection'
    if ('gain' in t and 'reduction' in t) or ('attack' in t and 'release' in t): return 'Compression'
    for keys,name in [({'limiter','limiting','ceiling'},'Limiter'),({'saturation','saturator','waveshaping','harmonics'},'Saturation'),({'compressor','compression','threshold','ratio'},'Compression'),({'equalizer','eq','frequency','filter'},'Equalization'),({'delay','echo','feedback'},'Delay'),({'reverb','reverberation'},'Reverb'),({'pitch','formant','autotune','retune'},'Pitch processing')]:
        if t & keys: return name
    return None


def technical_topic(text: str) -> tuple[str | None, str]:
    kind=diagram_kind(text)
    speed='fast' if kind=='Pitch processing' and re.search(r'\b(?:zero|fast|hard)\b',text.lower()) else 'smooth'
    return kind,speed if kind=='Pitch processing' else ''


def captions_for(lines, start, end):
    """One caption at a time. Keep the original words; split long phrases by time."""
    rows=[]; cursor=0.; repairs=0
    for row in sorted(lines,key=lambda x:(float(x['start']),float(x['end']))):
        a=max(start,float(row['start']))-start; b=min(end,float(row['end']))-start
        if b<=a: continue
        if a<cursor: a=cursor; repairs+=1
        if b-a<.05: continue
        raw=row.get('words') or []
        words=str(row['text']).split()
        if not raw:
            span=float(row['end'])-float(row['start'])
            raw=[{'text':word,'start':float(row['start'])+span*i/len(words),'end':float(row['start'])+span*(i+1)/len(words)} for i,word in enumerate(words)]
        # Assign each timed word to exactly one shot using its midpoint.
        chosen=[word for word in raw if start<=(float(word['start'])+float(word['end']))/2<end and float(word['end'])>start+a]
        chunks=[];part=[]
        for word in chosen:
            if part and (len(part)>=9 or len(' '.join(str(v['text']) for v in part+[word]))>52): chunks.append(part);part=[]
            part.append(word)
        if part: chunks.append(part)
        prev=a
        for j,chunk in enumerate(chunks):
            t0=max(prev,float(chunk[0]['start'])-start,a)
            t1=min(b,float(chunk[-1]['end'])-start)
            if j+1<len(chunks): t1=min(t1,float(chunks[j+1][0]['start'])-start)
            if t1-t0>=.025:
                rows.append({'text':' '.join(str(v['text']) for v in chunk),'start':t0,'end':t1,'words':[{**v,'start':max(t0,float(v['start'])-start),'end':min(t1,float(v['end'])-start)} for v in chunk if min(t1,float(v['end'])-start)>max(t0,float(v['start'])-start)]});prev=t1
        cursor=b
    return rows,repairs


def coalesce_visualizers(plan: dict):
    """Keep continuous audio visualization continuous; retain caption timestamps.

    Bounded 30s segments keep cache and cancellation granularity predictable.
    Run only after web/local AI sourcing, so no photo opportunities are lost.
    """
    merged=[];fps=plan['fps']
    for scene in plan['scenes']:
        if (merged and scene['type']=='visualizer' and merged[-1]['type']=='visualizer'
                and merged[-1]['frames']+scene['frames']<=30*fps):
            prev=merged[-1];shift=prev['frames']/fps
            prev['captions'].extend({**c,'start':c['start']+shift,'end':c['end']+shift,'words':[{**v,'start':v['start']+shift,'end':v['end']+shift} for v in c.get('words',[])]} for c in scene['captions'])
            prev['frames']+=scene['frames'];prev['end']=scene['end']
            prev.pop('dip_out',None)
            if scene.get('dip_out'): prev['dip_out']=True
        else: merged.append(scene)
    plan['scenes']=merged
    if len(merged)==1 and merged[0]['type']=='visualizer':
        plan['beat_aligned']=False
        plan['continuous_visualizer']=True
    return plan


def review(plan: dict) -> dict:
    issues=[]; prev=0; fps=plan['fps']; repeats=0; last=None; run=0; overlap=0
    for i,s in enumerate(plan['scenes']):
        if round(s['start']*fps)!=prev or s['frames']<=0 or round(s['end']*fps)!=prev+s['frames']:
            issues.append({'scene':i+1,'severity':'error','message':'Non-contiguous scene timing'})
        prev+=s['frames']; end=s['frames']/fps; last_end=0.
        if end<.5 and len(plan['scenes'])>1: issues.append({'scene':i+1,'severity':'warning','message':'Very short shot'})
        if s.get('recorded_demo') and s.get('recorded_seconds',end)<end-.25:issues.append({'scene':i+1,'severity':'warning','message':'Recording is shorter than the scene; final real frame will hold'})
        if s.get('asset') and s.get('asset')==last:
            run+=1
            if run>=3: repeats+=1; issues.append({'scene':i+1,'severity':'warning','message':'Repeated source footage; variation may not hide repetition'})
        else: run=1
        last=s.get('asset')
        for c in s['captions']:
            if c['start']<last_end-.001 or c['end']>end+.02 or c['start']<0 or c['end']<=c['start']:
                overlap+=1; issues.append({'scene':i+1,'severity':'error','message':'Caption overlaps or exceeds scene'})
            if len(c['text'])>65 or (len(c['text'].split())>2 and c['end']-c['start']<.55):
                issues.append({'scene':i+1,'severity':'warning','message':'Caption may be difficult to read'})
            last_end=c['end']
    if prev!=plan['frames']: issues.append({'scene':0,'severity':'error','message':'Incorrect total frame count'})
    if plan.get('beat_confidence',1)<beat.LOW_CONFIDENCE: issues.append({'scene':0,'severity':'warning','message':'Low beat confidence; using phrase/timed cuts'})
    return {'errors':sum(i['severity']=='error' for i in issues),'warnings':sum(i['severity']=='warning' for i in issues),'caption_overlaps':overlap,'repeated_shots':repeats,'issues':issues[:100]}


def ai_request(request: dict, timeout: int = 180) -> dict:
    """Run optional AI in its own Python environment, including frozen EXE mode."""
    import sys
    import json
    runtime=os.getenv('SKELLYMOTION_AI_PYTHON','')
    if not runtime:
        if getattr(sys,'frozen',False): raise RuntimeError('Configure SKELLYMOTION_AI_PYTHON for the local AI runtime')
        runtime=sys.executable
    worker=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'studio_ai_worker.py'
    result=subprocess.run([runtime,str(worker)],input=json.dumps(request),text=True,encoding='utf-8',capture_output=True,
                          timeout=timeout,**perf.windows_child_options(True))
    if result.returncode: raise RuntimeError('Local AI worker failed; check model and Python environment')
    payload=json.loads(result.stdout.strip().splitlines()[-1])
    if not isinstance(payload,dict) or payload.get('error'): raise RuntimeError('Local AI worker returned no valid result')
    return payload


def generate_local(prompt: str, seed: int) -> Image.Image:
    """Explicitly configured local Stable Diffusion model, no model downloads."""
    import tempfile
    raw=os.getenv('SKELLYMOTION_IMAGE_MODEL',''); path=Path(raw).expanduser() if raw else None
    if not path or not path.is_dir() or not (path/'model_index.json').is_file():
        raise RuntimeError('Set SKELLYMOTION_IMAGE_MODEL to a trusted installed Stable Diffusion model directory')
    with tempfile.TemporaryDirectory(prefix='skelly-ai-') as tmp:
        target=Path(tmp)/'result.png'
        ai_request({'operation':'generate','model':str(path.resolve()),'prompt':prompt,'seed':seed,'output':str(target)})
        with Image.open(target) as im:
            if im.size!=(512,512): raise ValueError('Unexpected generated image size')
            return im.convert('RGB')


def semantic_scores(folder: Path, assets: list[dict], scenes: list[dict]) -> dict:
    """Optional local CLIP ranking of actual image content or sampled video frames."""
    import tempfile
    raw=os.getenv('SKELLYMOTION_VISION_MODEL',''); model=Path(raw).expanduser() if raw else None
    if not model or not model.is_dir() or not (model/'config.json').is_file():
        raise RuntimeError('Local vision model is not configured')
    from studio_director import asset_path, IMAGE_EXT
    texts=list(dict.fromkeys(' '.join(c['text'] for c in scene['captions'])[:220] for scene in scenes))[:64]
    texts=[t for t in texts if t]
    if not texts: return {}
    with tempfile.TemporaryDirectory(prefix='skelly-vision-') as tmp:
        paths=[]; keys=[]
        for item in [a for a in assets if not a.get('source')][:12]:
            path=asset_path(folder,item['id'])
            if not path: continue
            target=Path(tmp)/(str(len(paths))+'.png')
            try:
                if path.suffix in IMAGE_EXT:
                    with Image.open(path) as im:
                        tile=ImageOps.exif_transpose(im).convert('RGB');tile.thumbnail((384,384));tile.save(target)
                else:
                    t=min(2.,float(item.get('features',{}).get('duration',1))*.35)
                    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-ss',str(t),'-i',str(path),'-frames:v','1','-vf','scale=384:384:force_original_aspect_ratio=decrease',str(target)],capture_output=True,timeout=12,**perf.windows_child_options(True))
                if target.is_file(): paths.append(str(target));keys.append(item['id'])
            except (OSError,ValueError,subprocess.TimeoutExpired): continue
        if not paths: return {}
        raw=ai_request({'operation':'match','model':str(model.resolve()),'images':paths,'texts':texts},timeout=180).get('scores')
        if not isinstance(raw,list) or len(raw)!=len(texts): raise ValueError('Unexpected vision response')
        result={}
        for text,row in zip(texts,raw):
            if not isinstance(row,list) or len(row)!=len(keys) or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in row):
                raise ValueError('Unexpected vision score')
            lo,hi=min(row),max(row)
            result[text]={key:(score-lo)/(hi-lo) if hi-lo>.01 else .5 for key,score in zip(keys,row)}
        return result


def apply_semantic(plan, folder, assets):
    """Re-rank B-roll, never replace documentary evidence or plugin UI with unrelated photos."""
    scores=semantic_scores(folder,assets,plan['scenes']); changed=0;previous=None
    for scene in plan['scenes']:
        if scene['type'] not in ('broll','visualizer','big_text') or plan['preset']=='plugin': continue
        key=' '.join(c['text'] for c in scene['captions'])[:220]; ranking=scores.get(key,{})
        if not ranking or len(ranking)<2: continue
        eligible=[a for a in assets if a['id'] in ranking and not a.get('source')]
        if not eligible: continue
        best=max(eligible,key=lambda a:ranking[a['id']]-.18*int(a['id']==previous)+.15*float(a.get('features',{}).get('quality',.5)))
        if ranking[best['id']]<.6: continue
        changed+=int(scene.get('asset')!=best['id']);previous=best['id']
        scene.update(type='broll',asset=best['id'],asset_name=best['name'],features=best.get('features',{}),camera='push' if best['kind']=='image' else 'still',text='')
        scene.pop('source',None);scene.pop('asset_start',None)
    plan['semantic_changes']=changed
    plan['semantic_review']='Local model relative similarity (not verified factual relevance)'


def fill_generated(plan: dict, folder: Path, enabled=False, check_cancel=lambda:None):
    if not enabled: return
    import studio_visual_sources as sources
    done=0; warning=False
    if folder.is_symlink(): raise ValueError('Linked asset folder')
    for s in plan['scenes']:
        if s['type'] not in ('big_text','visualizer') or s.get('asset'): continue
        check_cancel(); query=sources.query_for(s)
        if not query: continue
        model=os.getenv('SKELLYMOTION_IMAGE_MODEL','')
        key=hashlib.sha256(('local-diffusion-v1|'+model+'|'+query).encode()).hexdigest()[:32]+'.jpg'
        target=folder/key; meta={'name':'Generated illustration','description':query,'source':{'provider':'Local AI','license':'Model-dependent','creator':'Generated illustration','query':query}}
        try:
            if target.is_symlink(): raise ValueError('Linked generated image')
            with sources.INDEX_LOCK:
                index=perf.read_cache(folder/'index.json'); cached=target.is_file() and not target.is_symlink() and key in index
                if cached and isinstance(index[key],dict) and index[key].get('disabled'):continue
                if not cached and (len(index)>=40 or done>=2): continue
            if not cached:
                image=generate_local('Atmospheric cinematic editorial illustration, no lettering: '+query,int(key[:8],16));check_cancel()
                folder.mkdir(exist_ok=True); tmp=folder/('.ai-'+uuid4().hex+'.tmp')
                try:
                    image.save(tmp,format='JPEG',quality=90)
                    with sources.INDEX_LOCK:
                        index=perf.read_cache(folder/'index.json')
                        if len(index)>=40 or target.exists(): continue
                        perf.publish_staged_file(tmp,target)
                        try: index[key]=meta;perf.atomic_write_json(folder/'index.json',index)
                        except Exception: target.unlink(missing_ok=True);raise
                    done+=1
                finally: tmp.unlink(missing_ok=True)
            s.update(type='broll',asset=key,asset_name=meta['name'],source=meta['source'],camera='push',text='')
        except (ImportError,OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):
            check_cancel();warning=True;break
    plan['generated_images']=done
    if warning: plan.setdefault('warnings',[]).append('Local AI image model unavailable or generation failed; safe fallback retained.')
