import io,json,shutil,wave
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
import server,studio_creator as c,studio_cinematic as cinema,studio_director as director


def script():
    return [{'title':'Retune controls','narration':'Choose a retune speed. Listen to your vocal.','visual_hint':'retune speed knob'}]


def test_fact_grounding_and_target_warning():
    result=c.draft_script('Test plugin','cinematic walkthrough',['The mix control is adjustable.'],90)
    assert result['warnings'] and result['estimated_seconds']<90
    assert any(r['narration']=='The mix control is adjustable.' for r in result['chapters'])
    with pytest.raises(ValueError,match='invent'):c.draft_script('Plugin','',[],60)
    with pytest.raises(ValueError):c.validate_script([{'narration':' '}])
    with pytest.raises(ValueError):c.validate_script([{'narration':'a'*1201}])


def test_neural_provider_explicit_failure(monkeypatch):
    monkeypatch.setattr(c,'voice_options',lambda:{'piper':False,'system':False,'draft':True})
    assert c.resolve_voice('auto')=='draft'
    with pytest.raises(ValueError):c.resolve_voice('piper')


def test_agent_chapter_and_hint_match(tmp_path):
    rows=[{'text':'Listen closely','start':0,'end':2,'chapter_title':'First chapter','visual_hint':'retune knob'},{'text':'Try it now','start':2.1,'end':4.5,'chapter_title':'First chapter','visual_hint':'retune knob'},{'text':'Inspect this','start':4.6,'end':7,'chapter_title':'Analyzer','visual_hint':'analyzer'}]
    assets=[{'id':'a'*32+'.png','name':'retune knob','kind':'image'},{'id':'b'*32+'.png','name':'analyzer','kind':'image'}]
    p=director.make_plan(rows,7.2,assets,'plugin',fps=24,cinematic=True,title_motion=True)
    assert len(p['scenes'])==2 and p['scenes'][0]['asset']==assets[0]['id'] and p['scenes'][1]['asset']==assets[1]['id']
    assert p['scenes'][0]['hero_title']=='First chapter'
    p['caption_style']='off';ass=tmp_path/'title.ass';cinema.write_kinetic_ass(p,960,540,ass)
    text=ass.read_text(encoding='utf-8-sig');assert 'FIRST CHAPTER' in text and '\\move(' in text and 'Dialogue: 0,' not in text


@pytest.mark.skipif(not (shutil.which('espeak') or shutil.which('espeak-ng')) or not shutil.which('ffmpeg'),reason='local draft voice and FFmpeg required')
def test_real_creator_narration(tmp_path):
    result=c.narration(script(),tmp_path/'voice.wav','draft')
    assert result['provider']=='draft' and result['duration']>1
    assert result['word_timing'].startswith('estimated')
    assert len(result['lines'])==2 and result['lines'][0]['end']<result['lines'][1]['start']
    with wave.open(str(tmp_path/'voice.wav')) as f:assert abs(f.getnframes()/f.getframerate()-result['duration'])<.001


def test_creator_http_draft_and_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path);client=TestClient(server.app)
    assert client.post('/api/creator/script',json={'product':'X','facts':[]}).status_code==400
    monkeypatch.setattr(c,'voice_options',lambda:{'piper':False,'system':False,'draft':True})
    assert client.post('/api/creator/create',data={'payload':json.dumps({'product':'X','chapters':script(),'voice':'piper'})}).status_code==400
    assert not list(tmp_path.iterdir())
    assert client.post('/api/creator/create',data={'payload':json.dumps({'product':'X','chapters':script(),'voice':'draft','visual_roles':[{'order':'bad'}]})},files={'files':('test.png',b'bad','image/png')}).status_code==400
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(not (shutil.which('espeak') or shutil.which('espeak-ng')) or not shutil.which('ffmpeg'),reason='local draft voice and FFmpeg required')
def test_actual_creator_video_and_project(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*a:fn(*a))
    client=TestClient(server.app);b=io.BytesIO();Image.new('RGB',(432,414),'#456c5b').save(b,format='PNG')
    payload={'product':'Test plugin','chapters':script(),'voice':'draft','auto_render':True,'preview':True,'visual_roles':[{'role':'plugin_state','description':'retune speed knob'}]}
    r=client.post('/api/creator/create',data={'payload':json.dumps(payload)},files={'files':('Retune knob.png',b.getvalue(),'image/png')});assert r.status_code==200,r.text
    data=r.json();p=tmp_path/data['project_id'];job=server.jobs[data['job_id']];assert job['status']=='done',job
    project=client.get('/api/projects/'+p.name).json();assert project['status']=='editor' and project['creator_metadata']['provider']=='draft'
    plan=client.get(job['outputs']['plan']).json();assert plan['title_motion'] and plan['scenes'][0]['hero_title']=='Retune controls'
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_audio'] and info['has_video']

@pytest.mark.skipif(not (shutil.which('espeak') or shutil.which('espeak-ng')) or not shutil.which('ffmpeg'),reason='local draft voice required')
def test_audition_and_agent_focus_metadata(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*a:fn(*a))
    client=TestClient(server.app)
    r=client.post('/api/creator/voice-preview',json={'text':'Short voice check.','voice':'draft'})
    assert r.status_code==200 and r.content[:4]==b'RIFF' and r.headers['x-skelly-voice']=='draft'
    b=io.BytesIO();Image.new('RGB',(432,414),'#456c5b').save(b,format='PNG')
    payload={'product':'Test plugin','chapters':script(),'voice':'draft','auto_render':False,'visual_roles':[{'role':'plugin_state','group':'retune','order':1,'description':'retune knob','focus_x':.5,'focus_y':.53}]}
    r=client.post('/api/creator/create',data={'payload':json.dumps(payload)},files={'files':('Retune.png',b.getvalue(),'image/png')});assert r.status_code==200,r.text
    assets=client.get('/api/projects/'+r.json()['project_id']+'/director/assets').json()['assets'];assert assets[0]['focus_point']==[.5,.53]
