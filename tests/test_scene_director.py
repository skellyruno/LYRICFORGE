import io
import json
import math
import shutil
import subprocess
import wave
from pathlib import Path
from array import array

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import server
import studio_director as director


def project(tmp, monkeypatch, *, status='editor', duration=4.2):
    monkeypatch.setattr(server,'DATA',tmp)
    pid='a'*32; p=tmp/pid; p.mkdir()
    lines=[{'text':'Depth changes the signal','start':0,'end':2.1,'words':[]},
           {'text':'Compare the result','start':2.1,'end':duration,'words':[]}]
    with wave.open(str(p/'voice.wav'),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000)
        out.writeframes(array('h',(round(4500*math.sin(2*math.pi*220*i/16000)) for i in range(round(duration*16000)))).tobytes())
    server.save_project(p,{'id':pid,'title':'Demo','status':status,'duration':duration,'audio_file':'voice.wav','lines':lines if status=='editor' else [],'save_state':'draft','settings':{},'draft_lyrics':'Before edits'})
    return p,TestClient(server.app)


def test_plan_is_contiguous_and_uses_real_assets():
    lines=[{'text':'depth knob','start':i,'end':i+1} for i in range(0,28,2)]
    assets=[{'id':'a'*32+'.png','name':'Depth knob.png','kind':'image','description':'depth knob'},
            {'id':'b'*32+'.mp4','name':'Screen recording.mp4','kind':'video','description':''}]
    for style in director.PRESETS:
        plan=director.make_plan(lines,28.17,assets,style,fps=24)
        assert plan['scenes'][0]['start']==0
        assert sum(s['frames'] for s in plan['scenes'])==round(28.17*24)
        assert all(a['end']==b['start'] for a,b in zip(plan['scenes'],plan['scenes'][1:]))
        assert all(s.get('asset') in {None,*[a['id'] for a in assets]} for s in plan['scenes'])
        assert all(s['frames']>0 for s in plan['scenes'])
        assert plan==director.make_plan(lines,28.17,assets,style,fps=24)
    preview=director.make_plan(lines,28.17,[], 'doc', preview=True)
    assert preview['duration']==15 and preview['warnings']
    assert all(s['type'] in ('big_text','outro') for s in preview['scenes'])


def test_director_import_validates_and_stays_read_only(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch)
    route=f'/api/projects/{p.name}/director/assets'
    assert c.get(route).json()=={'assets':[]}
    assert not (p/'director_assets').exists()
    assert c.post(route,files={'file':('bad.svg',b'<svg/>','image/svg+xml')}).status_code==400
    assert c.post(route,files={'file':('bad.png',b'invalid','image/png')}).status_code==400
    buf=io.BytesIO();Image.new('RGB',(320,200),'#487568').save(buf,format='PNG')
    r=c.post(route,files={'file':('Depth knob.png',buf.getvalue(),'image/png')},data={'description':'depth signal'})
    assert r.status_code==200,r.text
    key=r.json()['assets'][0]['id']
    assert director.asset_path(p/'director_assets',key).is_file()
    assert director.asset_path(p/'director_assets','../voice.wav') is None
    assert c.post(f'/api/projects/{p.name}/director/plan',json={'preset':'plugin'}).json()['scenes'][0]['asset']==key


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_actual_director_render_and_cache(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch)
    buf=io.BytesIO();Image.new('RGB',(640,360),'#244e52').save(buf,format='PNG')
    assert c.post(f'/api/projects/{p.name}/director/assets',files={'file':('Depth plugin.png',buf.getvalue(),'image/png')}).status_code==200
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    route=f'/api/projects/{p.name}/director/render'
    r=c.post(route,json={'preset':'plugin','preview':True});assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']]
    assert job['status']=='done',job
    assert job['outputs']['render_elapsed_seconds']>=0
    assert 'peak_encoder_rss_mib' in job['outputs']
    out=p/'director_preview.mp4';assert out.stat().st_size>1024
    info=server.clips.probe_media(out);assert info['has_audio'] and info['has_video']
    assert abs(info['duration']-4.2)<.12
    assert c.get(job['outputs']['plan']).status_code==200
    assert c.get(job['outputs']['video']).status_code==200
    r=c.post(route,json={'preset':'plugin','preview':True});assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    assert job['outputs']['cached']==job['outputs']['scenes']
    assert server.read_project(p.name)['save_state']=='draft'
    # Retain evidence generated using synthetic audio and a simple test asset.
    import os
    dest=os.getenv('LF_EVIDENCE')
    if dest:
        shutil.copyfile(out,Path(dest)/'director_preview.mp4')
        shutil.copyfile(p/'director_preview_plan.json',Path(dest)/'director_preview_plan.json')


def test_unsaved_review_can_recover_and_save_empty_timeline(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,status='review')
    payload={'lines':[],'settings':{},'draft_lyrics':'Corrected without confirming'}
    r=c.put(f'/api/projects/{p.name}/recovery',json=payload)
    assert r.status_code==200,r.text
    assert json.loads((p/'recovery.json').read_text())['draft_lyrics']==payload['draft_lyrics']
    assert server.read_project(p.name)['save_state']=='draft'
    r=c.put(f'/api/projects/{p.name}',json=payload)
    assert r.status_code==200,r.text
    assert server.read_project(p.name)['draft_lyrics']==payload['draft_lyrics']
    assert server.read_project(p.name)['save_state']=='saved'
    assert not (p/'recovery.json').exists()
    # Empty lyrics must not weaken render validation.
    r=c.post(f'/api/projects/{p.name}/render',json=payload)
    assert r.status_code==400


def test_transcribing_draft_can_preserve_recovery_without_deletion(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,status='transcribing')
    r=c.put(f'/api/projects/{p.name}/recovery',json={'lines':[],'settings':{}})
    assert r.status_code==200,r.text
    r=c.post(f'/api/projects/{p.name}/discard');assert r.status_code==409
    assert (p/'voice.wav').is_file() and (p/'recovery.json').is_file()

@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg required')
def test_director_video_asset_and_music_bed(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,duration=4.2)
    footage=tmp_path/'test.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','1.0','-c:v','libx264','-threads','1',str(footage)],check=True)
    r=c.post(f'/api/projects/{p.name}/director/assets',files={'file':('Depth result.mp4',footage.read_bytes(),'video/mp4')})
    assert r.status_code==200,r.text
    music=server.brand_dir()/'music.wav';shutil.copyfile(p/'voice.wav',music)
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    r=c.post(f'/api/projects/{p.name}/director/render',json={'preset':'plugin','preview':True,'music':True})
    assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_audio'] and info['has_video'] and abs(info['duration']-4.2)<.12


def test_document_selection_is_grounded_in_asset_description():
    a={'id':'a'*32+'.png','name':'source article.png','description':'depth explanation','kind':'image'}
    plan=director.make_plan([{'text':'source article','start':0,'end':4}],4,[a],'doc')
    assert plan['scenes'][0]['type']=='document'
    assert 'redact' not in plan['scenes'][0]  # no fabricated coordinates
