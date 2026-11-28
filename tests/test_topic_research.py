import json, shutil
import pytest
from fastapi.testclient import TestClient
import studio_topic_research as research
import server

TEXT='Pitch correction changes the pitch of an audio signal. It is used in vocal production to adjust the intonation of a recorded performance.\n== History ==\nEarly correction methods used studio equipment and required manual intervention. Later digital tools enabled automatic tuning of recorded voices.\n== References ==\nThis section should not become narration.'
def fixture(params):
    if params.get('list')=='search':return {'query':{'search':[{'pageid':12}]}}
    return {'query':{'pages':[{'pageid':12,'title':'Pitch correction','extract':TEXT,'revisions':[{'revid':12345}]}]}}

def test_topic_only_and_attribution():
    d=research.draft('Pitch correction',30,get=fixture)
    assert d['source']['revision']==12345
    assert d['chapters'][-1]['title']=='Sources and credits'
    for c in d['chapters'][:-1]:
        assert c['narration'] in TEXT
        assert c['source_url'].endswith('12345')
    assert 'References' not in str(d['chapters'])

def test_focus_rejects_unsupported_material():
    d=research.draft('Pitch correction',30,'history',get=fixture)
    assert d['chapters'][0]['title']=='History'
    with pytest.raises(ValueError,match='does not support'):research.draft('Pitch correction',30,'quantum astronomy',get=fixture)

def test_no_invented_source():
    with pytest.raises(ValueError):research.draft('Unrecognized topic',get=lambda p:{'query':{'search':[]}})

def test_route_topic_only(monkeypatch):
    original=research.draft
    monkeypatch.setattr(research,'draft',lambda *args:original(*args,get=fixture))
    r=TestClient(server.app).post('/api/creator/research-topic',json={'topic':'Pitch correction','target_seconds':30})
    assert r.status_code==200,r.text
    assert r.json()['chapters']

@pytest.mark.skipif(not shutil.which('espeak') or not shutil.which('ffmpeg'),reason='local voice and renderer required')
def test_topic_to_real_narration_without_media(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda f,*a:f(*a))
    d=research.draft('Pitch correction',15,get=fixture)
    client=TestClient(server.app)
    payload={'product':d['product'],'chapters':d['chapters'],'production_mode':'research','voice':'draft','story':'documentary','auto_render':True,'preview':True,'output_fps':24}
    r=client.post('/api/creator/create',data={'payload':json.dumps(payload)})
    assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    p=tmp_path/r.json()['project_id'];info=server.clips.probe_media(p/'director_preview.mp4')
    assert info['has_audio'] and info['has_video']
    assert client.get(job['outputs']['plan']).status_code==200
