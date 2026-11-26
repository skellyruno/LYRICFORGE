import io,json,shutil,subprocess,wave
import numpy as np
import pytest
from PIL import Image,ImageDraw
import studio_walkthrough as w
import studio_director as d
import studio_cinematic as c
import server
from test_scene_director import project


def test_metadata_rejects_invalid():
    for kw in ({'role':'fake'},{'focus_x':.2},{'focus_x':1.2,'focus_y':.2},{'trim_start':2,'trim_end':1},{'order':1000},{'trim_start':float('nan')}):
        with pytest.raises(ValueError):w.metadata(**kw)
    assert w.metadata('plugin_state','  knob    test  ',2,.2,.3)['group']=='knob test'


def fixture_asset(key,kind='image',**kw):
    return {'id':key*32+('.png' if kind=='image' else '.mp4'),'name':'retune speed knob','kind':kind,'description':'retune speed knob','features':{},**kw}


def test_group_and_recording_priority():
    a=fixture_asset('a',role='plugin_state',group='knob',order=0);b=fixture_asset('b',role='plugin_state',group='knob',order=1,focus_point=[.5,.5]);b['description']='retune speed knob hard response';a['description']='retune speed knob slow response';other=fixture_asset('c',role='plugin_state',group='other',order=0)
    assert w.pair_for(b,[a,b,other])==a
    assert w.pair_for(a,[a,b,other]) is None
    video=fixture_asset('d','video',role='plugin_recording');video['features']={'duration':2}
    bad=fixture_asset('e','video',role='broll')
    plan=d.make_plan([{'text':'retune speed knob hard response','start':0,'end':4}],4,[a,b,video,bad],'plugin',cinematic=True,guided_replay=True)
    assert plan['scenes'][0]['recorded_demo'] and plan['scenes'][0]['asset']==video['id']
    assert plan['scenes'][0]['recorded_seconds']==2
    plan=d.make_plan([{'text':'retune speed knob hard response','start':0,'end':4}],4,[a,b,other,bad],'plugin',cinematic=True,guided_replay=True)
    assert plan['scenes'][0]['before_asset']==a['id'] and plan['scenes'][0]['guided_replay']


def test_recording_trim_and_advance():
    a=fixture_asset('a','video');a.update(features={'duration':10},trim_start=2,trim_end=8)
    assert w.recording_window(a,2,0)==(2,2)
    assert w.recording_window(a,2,1)==(4,2)
    assert w.recording_window(a,5,9)==(3,5)


def test_focus_refuses_ambiguous_and_replay_changes_real_pixels(tmp_path):
    a=Image.new('RGB',(200,200),'#101010');b=a.copy();ImageDraw.Draw(b).rectangle((90,95,115,120),fill='white')
    assert w.state_focus(a,a) is None
    assert w.state_focus(a,Image.new('RGB',(200,200),'white')) is None
    assert w.state_focus(a,Image.new('RGB',(300,200),'white')) is None
    point=w.state_focus(a,b);assert .4<point[0]<.6 and .4<point[1]<.65
    ap=tmp_path/'a.png';bp=tmp_path/'b.png';a.save(ap);b.save(bp)
    frames=tmp_path/'frames';bg=Image.new('RGB',(640,360),'#101010');scene={'frames':48,'focus_point':point}
    rate=w.replay_frames(scene,ap,bp,bg,frames,24,lambda:None);assert rate==12 and len(list(frames.glob('*.jpg')))==24
    x,y,tw,th=w.panel_geometry(640,360,200,200)
    with Image.open(frames/'00000.jpg') as first,Image.open(frames/'00023.jpg') as last:
        q=(x+int(.52*tw),y+int(.54*th));assert max(first.getpixel(q))<60 and min(last.getpixel(q))>180


def test_token_boundary_timing_preserved():
    raw=[{'text':'Skelly','start':.2,'end':.45},{'text':'Tune','start':.6,'end':.8},{'text':'mini','start':1.2,'end':1.5}]
    result=w.reconcile_words(['SkellyTune','Mini.'],raw);assert result[0]['start']==.2 and result[0]['end']==.8 and result[1]['start']==1.2
    assert not w.reconcile_words(['other','mini'],raw)
    assert w.reconcile_words(['Skelly','Tune'],[{'text':'SkellyTune','start':0,'end':1}])[1]['end']==1


@pytest.mark.parametrize('style',['karaoke','word','clean','off'])
def test_caption_modes(tmp_path,style):
    path=tmp_path/'a.ass';plan={'caption_style':style,'scenes':[{'start':0,'captions':[{'text':'hello world','start':0,'end':1,'words':[{'text':'hello','start':0,'end':.5},{'text':'world','start':.5,'end':1}]}]}]}
    c.write_kinetic_ass(plan,640,360,path);text=path.read_text('utf-8-sig')
    assert text.count('Dialogue:')=={'karaoke':1,'word':2,'clean':1,'off':0}[style]


def test_vtt_escaped_and_timed(tmp_path):
    path=tmp_path/'x.vtt';w.caption_vtt({'duration':2,'scenes':[{'start':0,'captions':[{'text':'<b> &','start':0,'end':1},{'text':'next','start':.8,'end':2}]}]},path)
    assert '&lt;b&gt; &amp;' in path.read_text() and '00:00:01.000 --> 00:00:02.000' in path.read_text()


def test_asset_edit_disable_duplicate_and_validation(tmp_path,monkeypatch):
    p,client=project(tmp_path,monkeypatch);route=f'/api/projects/{p.name}/director/assets';buf=io.BytesIO();Image.new('RGB',(320,200),'#424242').save(buf,'PNG');raw=buf.getvalue()
    assert client.post(route,files={'file':('a.png',raw,'image/png')},data={'role':'plugin_recording'}).status_code==400
    r=client.post(route,files={'file':('a.png',raw,'image/png')},data={'role':'plugin_state','group':'knob','order':'1'});assert r.status_code==200,r.text
    asset=r.json()['assets'][0];key=asset['id'];assert asset['role']=='plugin_state'
    r=client.post(route,files={'file':('a.png',raw,'image/png')},data={'role':'plugin_state','group':'knob','order':'1'});assert r.json()['duplicate'] and len(r.json()['assets'])==1
    body={'role':'plugin_state','group':'knob','order':1,'focus_x':.5,'focus_y':.5,'description':'depth signal','disabled':True}
    r=client.put(route+'/'+key,json=body);assert r.status_code==200,r.text
    assert r.json()['assets'][0]['disabled'] and (p/'director_assets'/key).is_file() and not d.assets_for(p/'director_assets')
    body['disabled']=False;assert client.put(route+'/'+key,json=body).status_code==200
    assert d.assets_for(p/'director_assets')[0]['focus_point']==[.5,.5]
    assert client.get(route+'/'+key).status_code==200
    assert client.put(route+'/'+key,json={**body,'focus_x':None}).status_code==400
    assert client.post(f'/api/projects/{p.name}/director/plan',json={'transition_style':'script'}).status_code==400


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg required')
def test_real_recording_export_does_not_loop(tmp_path,monkeypatch):
    p,client=project(tmp_path,monkeypatch,duration=4.2);src=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=1.6','-c:v','libx264','-threads','1',str(src)],check=True)
    route=f'/api/projects/{p.name}/director/assets';r=client.post(route,files={'file':('depth signal.mp4',src.read_bytes(),'video/mp4')},data={'role':'plugin_recording','description':'depth signal compare result'});assert r.status_code==200,r.text
    key=r.json()['assets'][0]['id'];assert client.get(route+'/'+key).status_code==200
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    r=client.post(f'/api/projects/{p.name}/director/render',json={'preset':'plugin','cinematic_finish':True,'guided_replay':True,'transition_style':'wipe','voice_style':'off','caption_style':'word'});assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    assert job['outputs']['recorded_scenes']>=1 and client.get(job['outputs']['captions']).status_code==200
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_video'] and abs(info['duration']-4.2)<.15


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg required')
def test_webm_repair_and_bad_cache(tmp_path):
    src=tmp_path/'stream.webm';subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=160x120:rate=24:duration=1','-c:v','libvpx','-f','webm','-live','1',str(src)],check=True)
    info=w.repair_recording_container(src,server.clips.probe_media);assert .9<=info['duration']<=1.1
    bad=tmp_path/'bad.mp4';bad.write_bytes(b'0'*1500);assert not w.valid_scene_clip(bad,1,24,server.clips.probe_media)
