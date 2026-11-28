import io,json,math,struct,wave
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
import server
from test_quick_tools import needs_ffmpeg

def png():
    b=io.BytesIO();Image.new('RGB',(320,180),'#527087').save(b,format='PNG');return b.getvalue()

def recording():
    b=io.BytesIO()
    with wave.open(b,'wb') as f:
        f.setparams((1,2,24000,0,'NONE','not compressed'))
        f.writeframes(b''.join(struct.pack('<h',int(4000*math.sin(2*math.pi*220*i/24000))) for i in range(48000)))
    return b.getvalue()

def request(indices=(0,)):
    g={'kind':'composition','title':'Media study','source':'Authored fixture','layers':[{'id':f'image-{i}','type':'image','upload_index':idx,'width':.7,'height':.65} for i,idx in enumerate(indices)]}
    return {'product':'Media study','story':'documentary','voice':'recorded','auto_render':False,'chapters':[{'title':'Evidence','narration':'This is a source image.','graphic':g}]}

@needs_ffmpeg
def test_recorded_creator_binds_duplicate_uploads_and_plans_actual_layers(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    body=request((0,1));image=png()
    files=[('recording',('voice.wav',recording(),'audio/wav')),('files',('first.png',image,'image/png')),('files',('second.png',image,'image/png'))]
    c=TestClient(server.app);r=c.post('/api/creator/create',data={'payload':json.dumps(body)},files=files)
    assert r.status_code==200,r.text
    result=r.json();pid=result['project_id'];p=server.read_project(pid)
    assert server.jobs[result['job_id']]['status']=='done',server.jobs[result['job_id']]
    layers=p['creator_script'][0]['graphic']['layers'];keys=[l['asset'] for l in layers]
    assert len(keys)==2 and keys[0]==keys[1] and (server.director_folder(pid)/keys[0]).is_file()
    assert keys[0]!='0'*32+'.png'
    assert p['creator_cues'][0]['graphic']['layers'][0]['asset']==keys[0]
    _,_,plan=server.prepare_director(pid,server.DirectorRequest(preset='doc',cinematic_finish=True,preview=True))
    assert any(scene.get('graphic') and scene['graphic']['layers'][0].get('asset')==keys[0] for scene in plan['scenes'])

def test_creator_rejects_invalid_upload_index_before_project_creation(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path)
    c=TestClient(server.app);r=c.post('/api/creator/create',data={'payload':json.dumps(request((1,)))},files=[('recording',('voice.wav',recording(),'audio/wav')),('files',('a.png',png(),'image/png'))])
    assert r.status_code==400 and 'upload_index' in r.text and not list(tmp_path.iterdir())

@needs_ffmpeg
def test_creator_invalid_visual_removes_unpublished_project(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path)
    c=TestClient(server.app);r=c.post('/api/creator/create',data={'payload':json.dumps(request())},files=[('recording',('voice.wav',recording(),'audio/wav')),('files',('a.png',png(),'image/png')),('files',('broken.png',b'not a png','image/png'))])
    assert r.status_code==400 and not list(tmp_path.iterdir())
