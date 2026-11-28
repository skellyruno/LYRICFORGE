"""Adapter for LYRICFORGE's existing project, B-roll and job registries."""
from pathlib import Path
import hashlib, json, re, time, shutil, tempfile, uuid, os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import studio_timeline as timeline
import studio_timeline_assistant as assistant
import studio_edit as edit

class TimelineRequest(BaseModel):
    instruction: str = Field(min_length=1,max_length=1000)
    fingerprint: str = Field(default='',max_length=64)
    format: str = Field(default='720p',pattern=r'^(720p|1080p|portrait|square)$')
    editable_copy: bool = False

class CreativeRequest(BaseModel):
    instruction: str = Field(default='',max_length=1000)
    goal: str = Field(default='balanced',max_length=40)
    model: str = Field(default='',max_length=120)

FORMATS={'720p':(1280,720),'1080p':(1920,1080),'portrait':(720,1280),'square':(720,720)}

def create_editable_copy(root,data,output,plan,words):
    # Stage a fully populated independent project before publishing its directory.
    if any(p['audio'] not in (None,'source') for p in plan['pieces']):
        raise ValueError('Footage audio requires fresh transcription; export then re-upload for Auto-edit')
    pid=uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='.timeline-project-',dir=root.parent) as tmp:
        stage=Path(tmp)/pid;stage.mkdir()
        shutil.copy2(output,stage/'source.mp4')
        title=(str(data.get('title') or 'Video')[:82]+' — timeline edit')[:100]
        info={'id':pid,'kind':'clip_source','title':title,'audio_file':'source.mp4','source_file':'source.mp4',
              'duration':plan['duration'],'status':'ready','draft_lyrics':'','original_words':words,'lines':[],
              'settings':data.get('settings') or {},'language':data.get('language'),'transcription_stage':'complete',
              'transcription_progress':100,'save_state':'saved','use_ai':False,'keep_fillers':True,
              'clip_suggestions':[],'clip_envelope':[],'scene_times':[], 'timeline_parent':root.name,
              'timeline_transcript_note':'Mapped complete words only; review cut boundaries before publishing.'}
        (stage/'project.json').write_text(json.dumps(info,ensure_ascii=False),encoding='utf-8')
        os.rename(stage,root.parent/pid)
    return pid


def build_router(*,project_dir,read_project,broll_library,probe_media,register_job,executor,jobs,job_lock,fail_job,check_cancel,sanitize_settings):
    router=APIRouter()
    def context(pid):
        data=read_project(pid); root=project_dir(pid)
        if data.get('kind')!='clip_source' or data.get('status')!='ready':
            raise HTTPException(409,'Add a recording and finish its analysis first')
        source=root/data['source_file']
        if source.resolve().parent!=root.resolve():raise ValueError('Invalid project source path')
        def asset(path):
            path=Path(path)
            if not path.is_file() or path.is_symlink():raise ValueError('Media missing')
            info=probe_media(path)
            if not info.get('has_video'):raise ValueError('Asset does not contain video')
            return {'path':path,'duration':float(info['duration']),'has_audio':bool(info.get('has_audio'))}
        assets={'source':asset(source)}
        for item in broll_library():
            name=item['name']
            if name=='source' or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,39}',name):continue
            try:assets[name]={**asset(item['path']),'keywords':list(item.get('keywords') or [])}
            except (ValueError,OSError,RuntimeError):continue
        return root,data,assets
    def prepare(pid,body):
        try:
            root,data,assets=context(pid);p=timeline.plan(assets,body.instruction)
            used={v for x in p['pieces'] for v in (x['asset'],x['audio']) if v}
            versions={k:[str(assets[k]['path'].resolve()),assets[k]['path'].stat().st_size,assets[k]['path'].stat().st_mtime_ns] for k in sorted(used)}
            if body.editable_copy and any(x['audio'] not in (None,'source') for x in p['pieces']):raise ValueError('Editable copy requires original narration or muted footage. For footage audio, export and re-upload for transcription.')
            if body.editable_copy and body.format in ('portrait','square'):raise ValueError('Editable copy requires landscape; existing Auto-edit uses landscape output.')
            fingerprint=hashlib.sha256(json.dumps([p,versions,body.format,body.editable_copy],sort_keys=True).encode()).hexdigest()
            return root,data,assets,p,fingerprint
        except (ValueError,OSError,RuntimeError,KeyError) as exc:raise HTTPException(422,str(exc)[:300]) from exc
    @router.get('/api/projects/{pid}/timeline/assets')
    def list_assets(pid:str):
        try:
            _,_,assets=context(pid)
            return {'assets':[{'id':k,'duration':v['duration'],'has_audio':v['has_audio'],'keywords':v.get('keywords',[])} for k,v in assets.items()]}
        except (ValueError,OSError,RuntimeError,KeyError) as exc:raise HTTPException(422,str(exc)[:300]) from exc
    @router.get('/api/projects/{pid}/timeline/model-setup')
    def model_setup(pid:str):
        return assistant.setup_status(project_dir(pid))
    @router.post('/api/projects/{pid}/timeline/creative')
    def creative(pid:str,body:CreativeRequest):
        try:
            _,data,assets=context(pid);words=data.get('original_words') or []
            if body.model:
                return {'proposal':assistant.translate(assets,body.instruction,body.model,words), 'warning':'AI proposal only. Preview and review every edit before export.'}
            return assistant.creative(assets,words,body.goal,body.instruction,data.get('scene_times') or [])
        except (ValueError,OSError,RuntimeError,KeyError) as exc:raise HTTPException(422,str(exc)[:300]) from exc
    @router.post('/api/projects/{pid}/timeline/plan')
    def preview(pid:str,body:TimelineRequest):
        _,data,assets,p,fingerprint=prepare(pid,body)
        words=data.get('original_words') or []
        if any(x['audio'] not in (None,'source') for x in p['pieces']):p['warnings'].append('Captions include original speech only. Re-transcribe new footage audio before publishing.')
        return {**p,'format':body.format,'editable_copy':body.editable_copy,'fingerprint':fingerprint,'words':timeline.remap_words(words,p),'suggestions':timeline.suggestions(p,words,{k:v for k,v in assets.items() if k!='source'},data.get('scene_times') or [])}
    @router.post('/api/projects/{pid}/timeline/render')
    def render(pid:str,body:TimelineRequest):
        root,data,assets,p,fingerprint=prepare(pid,body)
        if body.fingerprint!=fingerprint:raise HTTPException(409,'Preview the exact edit again before rendering')
        settings=sanitize_settings(data.get('settings') or {})
        job=register_job(pid,'timeline',settings)
        target=root/f'timeline-{job}.mp4'
        def progress(n,total):
            with job_lock:jobs[job].update(stage='timeline_render',progress=min(99,round(100*n/total)))
        def worker():
            started=time.monotonic()
            try:
                width,height=FORMATS[body.format]
                timeline.render(p,assets,target,width=width,height=height,check_cancel=lambda:check_cancel(job),progress=progress)
                check_cancel(job)
                words=timeline.remap_words(data.get('original_words') or [],p)
                subtitle=target.with_suffix('.vtt');temp=subtitle.with_suffix('.tmp')
                try:
                    temp.write_text(edit.to_vtt(edit.cues_from_words(words)),encoding='utf-8');os.replace(temp,subtitle)
                finally:temp.unlink(missing_ok=True)
                outputs={'video':f'/api/projects/{pid}/timeline/output/{job}','captions':f'/api/projects/{pid}/timeline/captions/{job}','seconds':p['duration']}
                if body.editable_copy:outputs['editable_project_id']=create_editable_copy(root,data,target,p,words)
                with job_lock:jobs[job].update(status='done',stage='complete',progress=100,outputs=outputs)
            except Exception as exc:fail_job(job,exc,started)
        try:executor.submit(worker)
        except Exception as exc:fail_job(job,exc,time.monotonic());raise HTTPException(503,'Could not start timeline render') from exc
        return {'job_id':job}
    @router.get('/api/projects/{pid}/timeline/output/{job}')
    def download(pid:str,job:str):
        if not re.fullmatch(r'[0-9a-f]{32}',job):raise HTTPException(404,'Unknown timeline output')
        p=project_dir(pid)/f'timeline-{job}.mp4'
        if not p.is_file() or p.is_symlink():raise HTTPException(404,'Timeline output is not ready')
        return FileResponse(p,media_type='video/mp4',filename='SkellyMotion-Timeline.mp4')
    @router.get('/api/projects/{pid}/timeline/captions/{job}')
    def captions(pid:str,job:str):
        if not re.fullmatch(r'[0-9a-f]{32}',job):raise HTTPException(404,'Unknown timeline output')
        p=project_dir(pid)/f'timeline-{job}.vtt'
        if not p.is_file() or p.is_symlink():raise HTTPException(404,'Timeline captions are not ready')
        return FileResponse(p,media_type='text/vtt',filename='SkellyMotion-Timeline.vtt')
    return router
