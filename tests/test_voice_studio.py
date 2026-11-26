import io,json,math,os,shutil,wave
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
import server,studio_voice as vs,studio_creator as c

CHAPTERS=[{'title':'First','narration':'SkellyTune corrects pitch.','visual_hint':'retune knob'},{'title':'Second','narration':'Listen to the result.','visual_hint':'note selection'}]

def wav_bytes(duration=4.,silence=False):
    rate=24000;t=np.arange(round(duration*rate))/rate
    x=np.zeros(len(t)) if silence else .12*np.sin(2*np.pi*220*t)
    buf=io.BytesIO()
    with wave.open(buf,'wb') as f:f.setparams((1,2,rate,0,'NONE','not compressed'));f.writeframes((x*32767).astype('<i2').tobytes())
    return buf.getvalue()


def test_pronunciation_and_story():
    d=vs.dictionary({'SkellyTune':'Skelly Tune','DSP':'D S P','Tune':'tune'})
    assert vs.spoken('SkellyTune and DSP, not SkellyTunes.',d)=='Skelly Tune and D S P, not SkellyTunes.'
    with pytest.raises(ValueError):vs.dictionary({'test':'x\ny'})
    with pytest.raises(ValueError):vs.delivery('unknown',1)
    facts=['Retune speed controls correction smoothing.']
    drafts=[c.draft_script('Test','',facts,90,story) for story in sorted(vs.FORMATS)]
    assert len({x['chapters'][0]['narration'] for x in drafts})==4
    assert all(x['chapters'][1]['narration']==facts[0] for x in drafts)


def test_recording_timing_checks():
    lines,origin=vs.recording_lines(CHAPTERS,4,[0,1.5],c.split_phrases)
    assert lines[0]['end']==lines[1]['start']==1.5 and lines[-1]['end']==4
    assert 'manual' in origin
    for marks in ([1,2],[0,0],[0,4],[0,float('nan')],[0]):
        with pytest.raises(ValueError):vs.recording_lines(CHAPTERS,4,marks,c.split_phrases)
    assert 'estimated' in vs.recording_lines(CHAPTERS,4,[],c.split_phrases)[1]


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_real_recorded_voice_upload(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args));cl=TestClient(server.app)
    payload={'product':'Test plugin','voice':'recorded','chapters':CHAPTERS,'chapter_starts':[0,1.5],'auto_render':False}
    assert cl.post('/api/creator/create',data={'payload':json.dumps(payload)}).status_code==400
    r=cl.post('/api/creator/create',data={'payload':json.dumps(payload)},files={'recording':('voice.wav',wav_bytes(),'audio/wav')});assert r.status_code==200,r.text
    pid=r.json()['project_id'];job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    p=server.read_project(pid);assert p['creator_metadata']['provider']=='recorded';assert p['lines'][1]['start']==1.5
    assert p['creator_metadata']['peak_dbfs']<0 and p['creator_metadata']['clipped_samples']==0
    assert (tmp_path/pid/'narration_source').read_bytes()==wav_bytes()
    assert (tmp_path/pid/'voice.wav').is_file()
    r=cl.post('/api/creator/create',data={'payload':json.dumps(payload)},files={'recording':('silence.wav',wav_bytes(silence=True),'audio/wav')});assert r.status_code==200
    assert server.jobs[r.json()['job_id']]['status']=='error'
    assert server.read_project(r.json()['project_id'])['status']=='creator_failed'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not(shutil.which('espeak') or shutil.which('espeak-ng')),reason='local speech and FFmpeg required')
def test_delivery_and_caption_spelling(tmp_path):
    a=c.narration(CHAPTERS,tmp_path/'neutral.wav','draft',delivery='neutral',pronunciation={'SkellyTune':'Skelly Tune'})
    b=c.narration(CHAPTERS,tmp_path/'slow.wav','draft',delivery='documentary',pronunciation={'SkellyTune':'Skelly Tune'})
    assert b['duration']>a['duration'] and b['delivery']=='documentary'
    assert a['lines'][0]['text']=='SkellyTune corrects pitch.' and a['lines'][0]['words'][0]['text']=='SkellyTune'


@pytest.mark.skipif(os.name!='nt' or not shutil.which('ffmpeg'),reason='Windows SAPI and FFmpeg required')
def test_real_windows_system_narration(tmp_path):
    if not c.voice_options()['system']:pytest.skip('System speech unavailable')
    result=c.narration([{'title':'Windows voice','narration':'This is a Windows speech test.'}],tmp_path/'system.wav','system',delivery='tutorial')
    assert result['duration']>0.5 and result['provider']=='system'


def test_motion_titles_selectable(tmp_path):
    import studio_cinematic as cinema
    for style,tag in [('slide',r'\move('),('fade',r'\pos('),('pop',r'\fscx90')]:
        p=tmp_path/(style+'.ass');cinema.write_kinetic_ass({'title_motion':True,'title_style':style,'caption_style':'off','scenes':[{'type':'big_text','text':'Motion title','start':0,'end':3}]},960,540,p)
        text=p.read_text(encoding='utf-8-sig');assert tag in text and 'MOTION TITLE' in text


def test_compare_cli_inputs(tmp_path):
    import studio_cli as cli
    args=cli.build_parser().parse_args(['compare','a.wav','b.wav','--out',str(tmp_path/'output'),'--start','1.5'])
    assert args.start==1.5 and args.command=='compare'
    with pytest.raises(ValueError):cli.compare_from_files(args)


def test_voice_trims_only_exterior_silence_and_respects_overrides():
    import numpy as np
    rate=24000
    audio=np.r_[np.zeros(rate),np.full(6000,2000),np.zeros(3000),np.full(6000,-2000),np.zeros(rate)].astype("<i2")
    trimmed=np.frombuffer(vs.phrase_pcm(audio.tobytes(),rate),dtype="<i2")
    assert len(trimmed)==15000+round(.055*rate)+round(.080*rate)
    assert np.count_nonzero(trimmed)==12000
    assert vs.spoken("DSP and VST3",vs.speech_dictionary({"DSP":"digital signal processing"}))=="digital signal processing and V S T three"
    assert vs.pause_after("a clause,",.2,.4,False)<vs.pause_after("a sentence.",.2,.4,False)<vs.pause_after("chapter.",.2,.4,True)


def test_piper_uses_native_pace_when_supported(tmp_path,monkeypatch):
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setattr(c.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='--length-scale FLOAT',stderr=''))
    monkeypatch.setenv('LYRICFORGE_PIPER_EXE','test-piper')
    monkeypatch.setenv('LYRICFORGE_PIPER_MODEL','fixture.onnx')
    monkeypatch.setattr(c,'run_checked',lambda args,**kwargs:calls.append(args))
    c.piper_length_flag.cache_clear()
    try:
        assert c.synthesize_phrase('A test',tmp_path/'voice.wav','piper',.8,lambda:None)
        assert calls[-1][-2:]==['--length-scale','1.25000']
        monkeypatch.setattr(c.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='old CLI',stderr=''))
        c.piper_length_flag.cache_clear()
        assert not c.synthesize_phrase('A test',tmp_path/'voice.wav','piper',.8,lambda:None)
        assert '--length-scale' not in calls[-1]
    finally:c.piper_length_flag.cache_clear()
