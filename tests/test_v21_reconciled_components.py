import shutil, wave
import numpy as np
import pytest
import studio_voice as voice
import studio_director_intelligence as intel
import studio_visual_sources as sources

def test_metadata_preserved_together():
    chapter={'title':'Evidence','narration':'Observe this signal.','visual_hint':'chart','source_url':'https://example.com','graphic':{'kind':'wave'}}
    rows,_=voice.recording_lines([chapter],2,[0],lambda text:[text])
    assert rows[0]['source_url']==chapter['source_url'] and rows[0]['graphic']==chapter['graphic']
    assert voice.presenter_pace('Compare frequency',1.)[0]<1

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_recording_without_script(tmp_path):
    import subprocess
    source=tmp_path/'source.wav';target=tmp_path/'voice.wav'
    x=(3000*np.sin(2*np.pi*220*np.arange(48000)/24000)).astype('<i2')
    with wave.open(str(source),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(x.tobytes())
    def run(args,**kwargs):subprocess.run(args,check=True,capture_output=True)
    def transcriber(path,duration,cancel):
        assert path.is_file() and duration==2
        return [{'text':'Hello','start':.2,'end':1.,'words':[{'text':'Hello','start':.2,'end':1.}]}]
    r=voice.prepare_recording(source,target,[],[],run,lambda text:[text],transcriber=transcriber)
    assert target.exists() and 'speech recognition' in r['word_timing'] and r['lines'][0]['text']=='Hello'
    with pytest.raises(ValueError):voice.prepare_recording(source,tmp_path/'no.wav',[],[0],run,lambda text:[text],transcriber=transcriber)
    assert not (tmp_path/'no.wav').exists()

def test_authored_graphics_protected(tmp_path,monkeypatch):
    p={'preset':'doc','scenes':[{'type':'big_text','text':'original','editorial':'graphic','captions':[{'text':'frequency'}]}]}
    monkeypatch.setattr(intel,'semantic_scores',lambda *a:{'frequency':{'a':1.,'b':0.}})
    monkeypatch.setattr(intel,'generate_local',lambda *a:pytest.fail('authored visual must not be replaced'))
    monkeypatch.setattr(sources,'search',lambda *a:pytest.fail('authored visual must not be replaced'))
    intel.apply_semantic(p,tmp_path,[{'id':'a','kind':'image','name':'A'},{'id':'b','kind':'image','name':'B'}]);intel.fill_generated(p,tmp_path,True);sources.fill_missing(p,tmp_path,True)
    assert p['scenes'][0]['text']=='original' and p['scenes'][0]['editorial']=='graphic'

def test_semantic_replacement_preserves_disabled_and_clears_provenance(tmp_path,monkeypatch):
    scene={'type':'broll','asset':'old','source':{'license':'old'},'asset_start':2,'asset_role':'plugin_state','spatial_motion':True,'editorial':'broll','captions':[{'text':'frequency'}]}
    p={'preset':'doc','scenes':[scene]};monkeypatch.setattr(intel,'semantic_scores',lambda *a:{'frequency':{'disabled':1.,'new':.85}})
    intel.apply_semantic(p,tmp_path,[{'id':'disabled','disabled':True,'kind':'image','name':'A'},{'id':'new','kind':'image','name':'B'}]);assert scene['asset']=='new'
    assert not any(k in scene for k in ('source','asset_start','asset_role','spatial_motion','editorial'))

def test_creator_text_and_source_validation():
    import studio_creator as c
    text='First sentence. Second sentence.\n\n'+('word '*130)
    rows=c.chapters_from_text(text)
    assert ' '.join(r['narration'] for r in rows).split()==text.split()
    graphic={'kind':'quote','title':'A','source':'Original','quote':'Exact sentence.'}
    row=c.validate_script([{'narration':'A claim.','source_url':'https://example.com','graphic':graphic}],production_mode='research')[0]
    assert row['graphic']==graphic and row['source_url']=='https://example.com'

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_creator_audio_only_api_preserves_research_gate(tmp_path,monkeypatch):
    import io,json,server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    rows=[{'id':'fixture','text':'Hello world','start':.1,'end':1.,'words':[{'text':'Hello','start':.1,'end':.5},{'text':'world','start':.5,'end':1.}],'chapter_title':'Hello world','visual_hint':'Hello world'}]
    monkeypatch.setattr(server,'recognize_creator_recording',lambda path,duration,cancel:rows)
    buf=io.BytesIO();x=(3000*np.sin(2*np.pi*220*np.arange(48000)/24000)).astype('<i2')
    with wave.open(buf,'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(x.tobytes())
    client=TestClient(server.app);p={'product':'Test','voice':'recorded','auto_render':False}
    def post(payload):return client.post('/api/creator/create',data={'payload':json.dumps(payload)},files={'recording':('voice.wav',buf.getvalue(),'audio/wav')})
    assert post({**p,'production_mode':'research'}).status_code==400
    r=post(p);assert r.status_code==200,r.text
    j=server.jobs[r.json()['job_id']];assert j['status']=='done',j
    data=server.read_project(r.json()['project_id']);assert data['creator_script'][0]['narration']=='Hello world' and data['lines'][0]['start']==.1
