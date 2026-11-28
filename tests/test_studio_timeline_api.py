from pathlib import Path
from threading import Lock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import studio_timeline_api as api
import studio_timeline as timeline

def test_preview_render_and_stale_media(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'original')
    city=tmp_path/'city.mp4';city.write_bytes(b'footage')
    job='a'*32;jobs={job:{}}
    class Inline:
        def submit(self,f):f()
    def fake_render(plan,assets,target,**kw):
        assert plan['duration']==3
        target.write_bytes(b'edited');kw['progress'](1,1)
    monkeypatch.setattr(timeline,'render',fake_render)
    app=FastAPI();app.include_router(api.build_router(project_dir=lambda p:tmp_path,read_project=lambda p:{'kind':'clip_source','status':'ready','source_file':source.name},broll_library=lambda:[{'name':'city','path':city}],probe_media=lambda p:{'has_video':True,'has_audio':True,'duration':4},register_job=lambda *a:job,executor=Inline(),jobs=jobs,job_lock=Lock(),fail_job=lambda *a:None,check_cancel=lambda j:None,sanitize_settings=lambda a:{}))
    c=TestClient(app);prefix='/api/projects/test/timeline';body={'instruction':'cut 1 to 2; replace 0 to 1 with city'}
    assert c.get(prefix+'/assets').status_code==200
    preview=c.post(prefix+'/plan',json=body);assert preview.status_code==200
    assert c.post(prefix+'/render',json=body).status_code==409
    body['fingerprint']=preview.json()['fingerprint']
    assert c.post(prefix+'/render',json={**body,'format':'1080p'}).status_code==409
    assert c.post(prefix+'/render',json={**body,'editable_copy':True}).status_code==409
    assert c.post(prefix+'/plan',json={**body,'format':'portrait','editable_copy':True}).status_code==422
    assert c.post(prefix+'/plan',json={'instruction':'insert city at 1 for 1','editable_copy':True}).status_code==422
    city.write_bytes(b'changed footage')
    assert c.post(prefix+'/render',json=body).status_code==409
    body['fingerprint']=c.post(prefix+'/plan',json=body).json()['fingerprint']
    assert c.post(prefix+'/render',json=body).status_code==200
    assert jobs[job]['status']=='done' and source.read_bytes()==b'original'
    assert c.get(jobs[job]['outputs']['video']).content==b'edited'
    assert c.get(jobs[job]['outputs']['captions']).text.startswith('WEBVTT')
