from pathlib import Path
import hashlib, json, subprocess, shutil
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from threading import Lock
import studio_sequence as seq
import studio_sequence_creative as creative
import studio_sequence_render as renderer
import studio_sequence_api as api

@pytest.fixture
def assets(tmp_path):
    result={}
    for k in ('source','city','music'):
        p=tmp_path/(k+'.mp4');p.write_bytes(k.encode());result[k]={'path':p,'duration':12.,'has_video':k!='music','has_audio':True,'music':k=='music'}
    return result

def visual(at=60,n=45):return {'op':'put','layer':{'id':'v','kind':'visual','asset':'city','at':at,'length':n,'fade':5}}
def music():return {'op':'put','layer':{'id':'m','kind':'music','asset':'music','at':0,'length':120,'gain':.14,'fade_in':12,'fade_out':12,'duck':True}}

def test_persistent_history_revision(tmp_path,assets):
    store=seq.Store(tmp_path,assets);assert store.get()['revision']==0
    a=store.mutate(0,{'op':'base','instruction':'cut 1 to 2'});assert a['state']['base']['frames']==330
    a=store.mutate(1,visual());assert a['can_undo'] and not a['can_redo']
    store=seq.Store(tmp_path,assets);assert len(store.get()['state']['layers'])==1
    with pytest.raises(seq.Conflict):store.mutate(1,{'op':'undo'})
    a=store.mutate(2,{'op':'undo'});assert not a['state']['layers'] and a['can_redo']
    a=store.mutate(3,{'op':'redo'});assert len(a['state']['layers'])==1
    a=store.mutate(4,music());assert len(a['state']['layers'])==2 and not a['can_redo']
    assert 'media' not in a['state']

def test_atomic_rejection_and_stale_media(tmp_path,assets):
    s=seq.Store(tmp_path,assets);s.mutate(0,visual());before=s.path.read_bytes()
    for action in [visual(350),{'op':'base','instruction':'cut 1 to 2'}, {'op':'put','layer':{'id':'bad','kind':'music','asset':'music','at':0,'length':50,'gain':float('nan')}}]:
        with pytest.raises(ValueError):s.mutate(1,action)
        assert s.path.read_bytes()==before
    assets['city']['path'].write_bytes(b'changed');assert s.get()['media_error']
    with pytest.raises(ValueError):s.snapshot(1)
    assert s.mutate(1,{'op':'reset'})['state']['layers']==[]

def test_transitions_and_music_overlap(assets):
    s=seq.apply(seq.initial(assets),{'op':'base','instruction':'cut 1 to 2'},assets)
    with pytest.raises(ValueError):seq.apply(s,{'op':'transition','kind':'dip','at':20,'half':3},assets)
    s=seq.apply(s,{'op':'transition','kind':'dip','at':30,'half':6},assets)
    s=seq.apply(s,music(),assets);x=music();x['layer']['id']='other'
    with pytest.raises(ValueError):seq.apply(s,x,assets)
    assert seq.apply(s,{'op':'transition','kind':'cut','at':30},assets)['transitions']==[]

def test_creative_rank_and_reveal(assets,monkeypatch):
    monkeypatch.setattr(creative,'visual',lambda a:{'quality':.9,'motion':.04,'detail':.12,'contrast':.25})
    monkeypatch.setattr(creative,'music',lambda a:{'bpm':90,'confidence':.9,'beats':[0,1,2,3,4,5,6,7],'rms_db':-20})
    state=seq.initial(assets);r=creative.suggest(state,assets,[],'make cinematic; build tension before reveal at 5')
    assert {x['action']['layer']['kind'] for x in r['suggestions'] if x.get('action')}=={'music','visual','sfx'}
    assert {x['action']['layer'].get('effect') for x in r['suggestions'] if x.get('action')} >= {'riser','impact'}
    r=creative.suggest(state,assets,[],'build tension before reveal');assert any('Specify the reveal' in x['reason'] for x in r['suggestions'])
    assert state['layers']==[]
    assert all(x['action']['layer']['at']+x['action']['layer']['length']<=150 for x in creative.suggest(state,assets,[],'build tension before reveal at 5')['suggestions'] if x.get('action',{}).get('layer',{}).get('kind')=='visual')

def test_api(tmp_path,assets,monkeypatch):
    jobs={'a'*32:{}};job='a'*32
    class Inline:
        def submit(self,f):f()
    monkeypatch.setattr(renderer,'render',lambda s,a,out,**kw:out.write_bytes(b'video'))
    app=FastAPI();app.include_router(api.build_router(project_dir=lambda p:tmp_path,read_project=lambda p:{'kind':'clip_source','status':'ready','source_file':'source.mp4'},broll_library=lambda:[{'name':'city','path':assets['city']['path'],'keywords':['city']}],brand_asset=lambda k:assets['music']['path'],probe_media=lambda p:assets.get(p.stem,assets['music']),register_job=lambda *a:job,executor=Inline(),jobs=jobs,job_lock=Lock(),fail_job=lambda *a:None,check_cancel=lambda j:None,sanitize_settings=lambda a:{}))
    c=TestClient(app);url='/api/projects/test/sequence';assert c.get(url).json()['revision']==0
    assert c.post(url+'/edit',json={'revision':0,'action':visual()}).status_code==200
    assert c.post(url+'/edit',json={'revision':0,'action':{'op':'undo'}}).status_code==409
    assert c.post(url+'/render',json={'revision':0}).status_code==409
    preview=c.post(url+'/preview-edit',json={'revision':1,'action':{'op':'ripple','instruction':'cut 0 to 1'}});assert preview.status_code==200 and preview.json()['state']['layers'][0]['at']==30
    assert c.get(url).json()['state']['layers'][0]['at']==60 and c.get(url).json()['revision']==1
    assert c.post(url+'/preview-edit',json={'revision':0,'action':{'op':'ripple','instruction':'cut 0 to 1'}}).status_code==409
    assert c.post(url+'/render',json={'revision':1}).status_code==200
    assert jobs[job]['status']=='done' and c.get(jobs[job]['outputs']['video']).content==b'video'
    track=c.post(url+'/music',files={'file':('soundtrack.wav',b'fixture','audio/wav')});assert track.status_code==200
    assert any(a['id']==track.json()['id'] for a in c.get(url).json()['assets'])
    assert c.post(url+'/music',files={'file':('bad.exe',b'no','application/octet-stream')}).status_code==422

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg tools required')
def test_real_render_and_metrics(tmp_path):
    def ff(*args):return subprocess.run(['ffmpeg','-v','error','-y',*args],check=True,capture_output=True).stdout
    src=tmp_path/'source.mp4';city=tmp_path/'city.mp4';song=tmp_path/'music.wav';out=tmp_path/'out.mp4'
    ff('-f','lavfi','-i','color=c=red:s=160x90:r=30:d=6','-f','lavfi','-i','sine=f=440:r=48000:d=6','-c:v','libx264','-threads','1','-c:a','aac',str(src))
    ff('-f','lavfi','-i','testsrc2=s=160x90:r=30:d=6','-c:v','libx264','-threads','1',str(city))
    ff('-f','lavfi','-i',"aevalsrc=0.3*sin(2*PI*120*t)*lt(mod(t\\,0.5)\\,0.04):s=48000:d=6",str(song))
    a={'source':{'path':src,'duration':6.,'has_video':True,'has_audio':True},'city':{'path':city,'duration':6.,'has_video':True,'has_audio':False},'music':{'path':song,'duration':6.,'has_video':False,'has_audio':True,'music':True}}
    original=hashlib.sha256(src.read_bytes()).hexdigest()
    assert creative.visual(a['city'])['quality']>creative.visual(a['source'])['quality']
    assert creative.music(a['music'])['confidence']>=.5
    s=seq.apply(seq.initial(a),{'op':'base','instruction':'cut 1 to 2'},a)
    s=seq.apply(s,{'op':'transition','kind':'dip','at':30,'half':6},a);s=seq.apply(s,visual(),a);s=seq.apply(s,music(),a)
    s=seq.apply(s,{'op':'put','layer':{'id':'fx','kind':'sfx','effect':'impact','at':120,'length':20,'gain':.08}},a)
    renderer.render(s,a,out,width=160,height=90)
    raw=ff('-i',str(out),'-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1');frames=np.frombuffer(raw,dtype=np.uint8).reshape(-1,90,160,3)
    assert len(frames)==150 and frames[30].mean()<5 and frames[45,45,80,0]>220
    assert np.abs(frames[80].astype(float)-frames[45]).mean()>20
    assert frames[110,45,80,0]>220
    audio=ff('-i',str(out),'-vn','-ac','1','-ar','48000','-f','f32le','pipe:1');samples=np.frombuffer(audio,dtype=np.float32)
    assert np.isfinite(samples).all() and np.abs(samples).max()<1.01 and len(samples)>=240000
    assert hashlib.sha256(src.read_bytes()).hexdigest()==original
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type,duration,nb_frames,avg_frame_rate','-of','json',str(out)]))
    assert all(float(x['duration'])==5.0 for x in probe['streams'])
    assert probe['streams'][0]['avg_frame_rate']=='30/1'

    # Controlled soundtrack ducking: use the same test sources and compare
    # spectral energy with the narration tone held constant.
    mixed=seq.apply(seq.initial(a),{'op':'put','layer':{'id':'m','kind':'music','asset':'music','at':0,'length':180,'gain':.3,'duck':True}},a)
    values=[]
    for duck in (True,False):
        mixed['layers'][0]['duck']=duck;target=tmp_path/('duck.mp4' if duck else 'plain.mp4')
        renderer.render(mixed,a,target,width=160,height=90)
        samples=np.frombuffer(ff('-i',str(target),'-vn','-ac','1','-ar','48000','-f','f32le','pipe:1'),dtype=np.float32)[:288000]
        spectrum=np.abs(np.fft.rfft(samples*np.hanning(len(samples))));freq=np.fft.rfftfreq(len(samples),1/48000)
        values.append((np.sqrt((spectrum[(freq>=100)&(freq<=140)]**2).sum()),spectrum[np.argmin(abs(freq-440))]))
    assert values[0][0]<.6*values[1][0]
    assert abs(values[0][1]/values[1][1]-1)<.02
