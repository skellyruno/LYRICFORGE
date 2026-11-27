"""Optional local CLIP reference hypotheses; no unreviewed semantic claims."""
from pathlib import Path
import os,tempfile,subprocess
from PIL import Image
import numpy as np
TECHNIQUES={'footage':'a live action cinematic camera shot of the real world','document':'a close up of a written document, article or highlighted evidence','diagram':'an animated explanatory graph, chart or scientific diagram','typography':'a designed title card with large typography','product':'a close up of a product or software interface','collage':'a collage of overlapping photographs or documents','hold':'a simple static illustration or background'}
ROLES={'hook':'a dramatic opening shot that introduces a topic','context':'a contextual establishing shot of a subject or place','evidence':'a source document or factual measurement shown as evidence','explanation':'a technical diagram illustrating a process','comparison':'a comparison of two items or measured data','resolution':'a closing title or visual resolution','demonstration':'a product or software interface demonstration'}

def infer(frames,fps,model=None,request=None,reference=None):
    model=Path(model or os.getenv('SKELLYMOTION_VISION_MODEL','')).expanduser()
    if not (model/'config.json').is_file():raise RuntimeError('Local vision model is not configured')
    frames=np.asarray(frames)
    if frames.ndim!=4 or frames.shape[-1]!=3 or not 2<=len(frames)<=20000 or not 0<fps<=60 or frames.nbytes>256*1024*1024:raise ValueError('Invalid or oversized reference frames')
    if request is None:
        from studio_director_intelligence import ai_request
        request=ai_request
    stride=max(1,frames.shape[1]//90,frames.shape[2]//160)
    reduced=frames[:,::stride,::stride];delta=np.empty(len(frames)-1,dtype=np.float32)
    previous=reduced[0].astype(np.float32).mean(axis=2)
    for j,frame in enumerate(reduced[1:]):
        current=frame.astype(np.float32).mean(axis=2);delta[j]=np.abs(current-previous).mean();previous=current
    indices=set(np.linspace(0,len(frames)-1,min(8,len(frames)),dtype=int).tolist())
    for i in np.argsort(delta)[::-1]:
        if len(indices)>=min(12,len(frames)):break
        if all(abs(int(i)+1-j)>=fps for j in indices):indices.add(int(i)+1)
    indices=sorted(indices);labels=[*TECHNIQUES,*ROLES];prompts=[*TECHNIQUES.values(),*ROLES.values()]
    with tempfile.TemporaryDirectory(prefix='skell-reference-') as root:
        files=[]
        for i in indices:
            p=Path(root)/f'{i}.png'
            if reference:
                subprocess.run(['ffmpeg','-v','error','-nostdin','-threads','1','-ss',str(i/fps),'-i',str(reference),'-frames:v','1','-vf','scale=384:384:force_original_aspect_ratio=decrease','-threads','1',str(p)],capture_output=True,timeout=12,check=True)
                if not p.is_file():continue
            else:Image.fromarray(frames[i]).save(p)
            files.append((i,str(p)))
        if not files:raise RuntimeError('No reference frames decoded')
        raw=request({'operation':'match','model':str(model.resolve()),'images':[p for _,p in files],'texts':prompts}).get('scores')
    scores=np.asarray(raw,dtype=float)
    if scores.shape!=(len(labels),len(files)) or not np.isfinite(scores).all():raise ValueError('Invalid local vision scores')
    observations=[];k=len(TECHNIQUES)
    for col,(i,_) in enumerate(files):
        tech=np.argsort(scores[:k,col]);role=np.argsort(scores[k:,col]);tm=float(scores[tech[-1],col]-scores[tech[-2],col]);rm=float(scores[k+role[-1],col]-scores[k+role[-2],col]);observations.append({'time':i/fps,'technique':labels[tech[-1]],'role':labels[k+role[-1]],'technique_margin':round(tm,3),'role_margin':round(rm,3)})
    segments=[]
    for obs in observations:
        confident=obs['technique_margin']>=.25 and obs['role_margin']>=.25
        label=(obs['technique'],obs['role']) if confident else ('uncertain','uncertain')
        if segments and tuple(segments[-1]['labels'])==label:segments[-1]['last_sample']=obs['time'];segments[-1]['samples']+=1
        else:segments.append({'labels':list(label),'first_sample':obs['time'],'last_sample':obs['time'],'samples':1})
    return {'observations':observations,'sampled_segments':segments,'basis':'Local CLIP relative similarity; provisional frame-level role hypotheses, not verified story meaning.','review_required':True}
