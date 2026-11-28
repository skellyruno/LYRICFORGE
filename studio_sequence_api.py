"""Project-scoped persistent sequence endpoints; reuses the app's job lifecycle."""
from pathlib import Path
import re,time,os,tempfile,uuid,shutil
from fastapi import APIRouter,HTTPException,UploadFile,File
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
import studio_sequence as seq
import studio_sequence_creative as creative
import studio_sequence_render as renderer
import studio_timeline as tl
import studio_edit as edit
from studio_timeline_api import FORMATS

class Mutation(BaseModel):
    revision:int=Field(ge=0)
    action:dict
class Request(BaseModel):
    revision:int=Field(ge=0)
    instruction:str=Field(default='',max_length=500)
    model:str=Field(default='',max_length=120)
    mode:str=Field(default='direct',pattern=r'^(direct|film|semantic)$')
    review_picture:bool=False
    deep_review:bool=False
    encoder:str=Field(default='auto',pattern=r'^(auto|cpu|gpu)$')
    format:str=Field(default='720p',pattern=r'^(720p|1080p|portrait|square)$')

def build_router(*,project_dir,read_project,broll_library,brand_asset,probe_media,register_job,executor,jobs,job_lock,fail_job,check_cancel,sanitize_settings):
    router=APIRouter(prefix='/api/projects/{pid}/sequence')
    def context(pid):
        data=read_project(pid);root=project_dir(pid)
        if data.get('kind')!='clip_source' or data.get('status')!='ready':raise HTTPException(409,'Finish recording analysis first')
        source=root/data['source_file']
        if source.resolve().parent!=root.resolve():raise ValueError('Invalid source path')
        def asset(path,keys=(),music=False):
            path=Path(path)
            if not path.is_file() or path.is_symlink():raise ValueError('Missing media')
            info=probe_media(path)
            if not info.get('has_audio') and not info.get('has_video'):raise ValueError('Unreadable media')
            return {'path':path,'duration':float(info['duration']),'has_audio':bool(info.get('has_audio')),'has_video':bool(info.get('has_video')),'music':music,'keywords':list(keys)}
        assets={'source':asset(source)}
        for item in broll_library():
            k=item['name'];keys=item.get('keywords') or []
            if k in ('source','brand-music') or not re.fullmatch('[a-z0-9][a-z0-9_-]{0,39}',k):continue
            try:assets[k]=asset(item['path'],keys,any(v.casefold() in ('music','soundtrack','score','instrumental') for v in keys))
            except (ValueError,OSError,RuntimeError):continue
        folder=root/'sequence-music'
        if folder.is_dir() and not folder.is_symlink():
            for track in sorted(folder.iterdir())[:8]:
                if re.fullmatch(r'music-[a-z0-9-]{1,30}\.(wav|mp3|m4a|aac|ogg|flac)',track.name) and track.is_file() and not track.is_symlink():
                    try:assets[track.stem]=asset(track,music=True)
                    except (ValueError,OSError,RuntimeError):continue
        track=brand_asset('music')
        if track:
            try:assets['brand-music']=asset(track,music=True)
            except (ValueError,OSError,RuntimeError):pass
        return root,data,assets,seq.Store(root,assets)
    def respond(fn):
        try:return fn()
        except seq.Conflict as exc:raise HTTPException(409,str(exc)) from exc
        except (ValueError,OSError,RuntimeError,KeyError,TypeError,IndexError) as exc:raise HTTPException(422,str(exc)[:300]) from exc
    @router.get('')
    def get(pid:str):
        def f():
            _,_,a,store=context(pid);return {**store.get(),'assets':[{**{k:v for k,v in x.items() if k!='path'},'id':k} for k,x in a.items()]}
        return respond(f)
    @router.post('/music')
    def upload_music(pid:str,file:UploadFile=File(...)):
        def f():
            root,data,_,store=context(pid)
            ext=Path(file.filename or '').suffix.lower()
            if ext not in {'.wav','.mp3','.m4a','.aac','.ogg','.flac'}:raise ValueError('Choose an audio file: WAV, MP3, M4A, AAC, OGG, FLAC')
            folder=root/'sequence-music';folder.mkdir(exist_ok=True)
            if folder.is_symlink() or folder.resolve().parent!=root.resolve():raise ValueError('Invalid music directory')
            name=re.sub('[^a-z0-9]+','-',Path(file.filename or '').stem.lower()).strip('-')[:20] or 'track'
            key='music-'+name+'-'+uuid.uuid4().hex[:8]
            # Validate before publication. All files stay in the project, never sent to a model.
            with seq.LOCK:
                if len(list(folder.iterdir()))>=8:raise ValueError('At most 8 project music tracks')
                fd,tmp=tempfile.mkstemp(prefix='.music-',suffix=ext,dir=root)
                try:
                    with os.fdopen(fd,'wb') as out:
                        total=0
                        while chunk:=file.file.read(1024*1024):
                            total+=len(chunk)
                            if total>40*1024*1024:raise ValueError('Music file exceeds 40 MiB')
                            out.write(chunk)
                    info=probe_media(Path(tmp))
                    if not info.get('has_audio') or not 0<float(info['duration'])<=1800:raise ValueError('Choose readable audio up to 30 minutes')
                    os.replace(tmp,folder/(key+ext))
                finally:Path(tmp).unlink(missing_ok=True)
            return {'id':key,'duration':float(info['duration'])}
        try:return respond(f)
        finally:file.file.close()
    @router.post('/preview-edit')
    def preview(pid:str,body:Mutation):
        def f():
            _,_,a,store=context(pid);state=store.snapshot(body.revision)
            if body.action.get('op')!='ripple':raise ValueError('Preview supports ripple edits')
            candidate=seq.apply(state,body.action,a);candidate.pop('media',None)
            return {'revision':body.revision,'state':candidate}
        return respond(f)
    @router.post('/edit')
    def mutate(pid:str,body:Mutation):return respond(lambda:context(pid)[3].mutate(body.revision,body.action))
    @router.post('/creative')
    def suggest(pid:str,body:Request):
        def f():
            _,data,a,store=context(pid);s=store.snapshot(body.revision)
            if body.mode=='semantic':
                from studio_sequence_semantic import propose
                return {**propose(s,a,data.get('original_words') or [],body.instruction),'revision':body.revision}
            if body.mode=='film':
                from studio_sequence_autofilm import propose
                return {**propose(s,a,data.get('original_words') or [],body.instruction),'revision':body.revision}
            if body.model:
                from studio_sequence_model import propose
                proposal=propose(s,a,data.get('original_words') or [],body.instruction,body.model)
                return {'suggestions':[{'reason':proposal['reason'],'action':proposal['action'],'preview':proposal['preview']}],'warning':proposal['warning'],'revision':body.revision}
            return {**creative.suggest(s,a,data.get('original_words') or [],body.instruction),'revision':body.revision}
        return respond(f)
    @router.post('/render')
    def render(pid:str,body:Request):
        def f():
            root,data,a,store=context(pid);s=store.snapshot(body.revision);settings=sanitize_settings(data.get('settings') or {});job=register_job(pid,'sequence',settings);out=root/f'sequence-{job}.mp4'
            def worker():
                started=time.monotonic()
                try:
                    def progress(n):
                        with job_lock:jobs[job].update(stage='timeline_render',progress=min(99,n))
                    w,h=FORMATS[body.format];encoding=renderer.render(s,a,out,width=w,height=h,cancel=lambda:check_cancel(job),progress=progress,encoder=body.encoder)
                    if not isinstance(encoding,dict):encoding={}
                    if body.review_picture:
                        from studio_sequence_visual_review import review
                        encoding['visual_review']=review(out,s,a,w,h,cancel=lambda:check_cancel(job))
                    if body.deep_review:
                        from studio_sequence_deep_review import review as deep_review
                        with job_lock:jobs[job].update(stage='export_quality_review',progress=99)
                        encoding['deep_review']=deep_review(out,s['base']['frames'],cancel=lambda:check_cancel(job))
                    check_cancel(job);words=tl.remap_words(data.get('original_words') or [],s['base']);caption=out.with_suffix('.vtt');temp=caption.with_suffix('.tmp')
                    try:temp.write_text(edit.to_vtt(edit.cues_from_words(words)),encoding='utf-8');os.replace(temp,caption)
                    finally:temp.unlink(missing_ok=True)
                    with job_lock:jobs[job].update(status='done',stage='complete',progress=100,outputs={'video':f'/api/projects/{pid}/sequence/output/{job}.mp4','captions':f'/api/projects/{pid}/sequence/output/{job}.vtt','revision':body.revision,'seconds':s['base']['frames']/30,**encoding})
                except Exception as exc:fail_job(job,exc,started)
            try:executor.submit(worker)
            except Exception as exc:fail_job(job,exc,time.monotonic());raise HTTPException(503,'Could not start render') from exc
            return {'job_id':job}
        return respond(f)
    @router.get('/output/{filename}')
    def output(pid:str,filename:str):
        if not re.fullmatch('[a-f0-9]{32}\\.(mp4|vtt)',filename):raise HTTPException(404,'Unknown export')
        p=project_dir(pid)/('sequence-'+filename)
        if not p.is_file() or p.is_symlink():raise HTTPException(404,'Export is not ready')
        return FileResponse(p,media_type='video/mp4' if p.suffix=='.mp4' else 'text/vtt',filename='SkellyMotion-Sequence'+p.suffix)
    return router
