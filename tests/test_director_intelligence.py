import io
import math
import os
import shutil
import subprocess
import wave
from array import array
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
import studio_director_intelligence as intel
import studio_director as director
import server
from test_scene_director import project


def test_visual_content_and_duplicates():
    plain=Image.new('RGB',(160,90),'black'); rich=Image.new('RGB',(160,90),'#8796a1')
    d=ImageDraw.Draw(rich);d.rectangle((104,15,145,75),fill='white');d.line((107,30,145,70),fill='black',width=4)
    a,b=intel.frame_features(plain),intel.frame_features(rich)
    assert b['quality']>a['quality'] and b['contrast']>a['contrast']
    assert b['focus'][0]>.55 and intel.diversity(b,b)==0
    assert intel.diversity(a,b)>0


def test_caption_repair_and_review():
    rows=[{'text':'one two three four five six seven eight nine ten eleven twelve','start':0,'end':3}, {'text':'another phrase','start':2,'end':4}]
    p=director.make_plan(rows,4,[],'doc')
    assert p['caption_repairs']==1 and p['review']['errors']==0
    assert all(a['end']<=b['start'] for a,b in zip(p['scenes'][0]['captions'],p['scenes'][0]['captions'][1:]))
    p['scenes'][0]['captions'][1]['start']=0
    assert intel.review(p)['caption_overlaps']>0


def test_beat_boundaries_and_repetition():
    beats=[i*.5 for i in range(28)];analysis={'beats':beats,'confidence':.9,'bpm':120,'downbeat':0,'bars':[]}
    assets=[{'id':'a'*32+'.mp4','name':'footage','kind':'video','features':{}}]
    p=director.make_plan([],12,assets,'music',analysis=analysis,motion='pingpong',transitions=True)
    assert p['beat_aligned'] and p['review']['errors']==0 and p['review']['repeated_shots']>0
    assert all(abs(s['start']*2-round(s['start']*2))<.001 for s in p['scenes'])
    assert sum(s['frames'] for s in p['scenes'])==360
    assert intel.cut_boundaries({**analysis,'confidence':.1},12,30,[],'medium')==[]


def test_generated_model_optional_and_cached(tmp_path,monkeypatch):
    monkeypatch.delenv('SKELLYMOTION_IMAGE_MODEL',raising=False)
    p=director.make_plan([{'text':'night forest','start':0,'end':4}],4,[],'doc')
    intel.fill_generated(p,tmp_path/'assets',True)
    assert p['scenes'][0]['type']=='big_text' and 'unavailable' in p['warnings'][-1]
    calls=[]
    def fixture(prompt,seed): calls.append(seed);return Image.new('RGB',(512,512),'#385850')
    monkeypatch.setattr(intel,'generate_local',fixture)
    intel.fill_generated(p,tmp_path/'assets',True)
    assert p['scenes'][0]['source']['provider']=='Local AI' and p['generated_images']==1
    other=director.make_plan([{'text':'night forest','start':0,'end':4}],4,[],'doc')
    intel.fill_generated(other,tmp_path/'assets',True)
    assert other['scenes'][0]['asset']==p['scenes'][0]['asset'] and len(calls)==1


def render_case(p,c,monkeypatch,body):
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    r=c.post(f'/api/projects/{p.name}/director/render',json=body);assert r.status_code==200,r.text
    j=server.jobs[r.json()['job_id']];assert j['status']=='done',j
    return c.get(j['outputs']['plan']).json(),p/('director_preview.mp4' if body.get('preview',True) else 'director.mp4')


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_audio_only_canvas_and_start_offset(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,duration=10.)
    plan,out=render_case(p,c,monkeypatch,{'preset':'music','preview':True,'output_format':'canvas','start_seconds':1})
    info=server.clips.probe_media(out)
    assert info['has_video'] and not info['has_audio'] and abs(info['duration']-7.5)<.07
    assert info['height']>info['width'] and plan['audio_start']==1 and plan['review']['errors']==0
    assert all(s['type']=='visualizer' for s in plan['scenes'])
    if os.getenv('LF_EVIDENCE'): shutil.copyfile(out,Path(os.environ['LF_EVIDENCE'])/'music_canvas.mp4')


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_animated_diagram_export(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,duration=4.2)
    plan,out=render_case(p,c,monkeypatch,{'preset':'plugin','preview':True,'lines':[{'text':'Compression controls the signal','start':0,'end':4.2}]})
    assert plan['scenes'][0]['type']=='diagram'
    assert server.clips.probe_media(out)['has_audio']
    a=subprocess.check_output(['ffmpeg','-v','error','-ss','0.5','-i',str(out),'-frames:v','1','-f','image2pipe','-vcodec','png','-'])
    b=subprocess.check_output(['ffmpeg','-v','error','-ss','2.5','-i',str(out),'-frames:v','1','-f','image2pipe','-vcodec','png','-'])
    assert a!=b
    if os.getenv('LF_EVIDENCE'): shutil.copyfile(out,Path(os.environ['LF_EVIDENCE'])/'animated_dsp.mp4')


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_short_footage_repeated_and_variations(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,duration=8.)
    footage=tmp_path/'tiny.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','0.6','-c:v','libx264','-threads','1',str(footage)],check=True)
    r=c.post(f'/api/projects/{p.name}/director/assets',files={'file':('motion.mp4',footage.read_bytes(),'video/mp4')});assert r.status_code==200,r.text
    assert r.json()['assets'][0]['features']['motion']>=0
    plan,out=render_case(p,c,monkeypatch,{'preset':'music','preview':True,'motion':'pingpong','transitions':True,'output_format':'square'})
    assert len(plan['scenes'])>=3 and any(s.get('variation')=='reverse' for s in plan['scenes'])
    info=server.clips.probe_media(out);assert info['has_video'] and info['has_audio'] and info['width']==info['height']
    assert abs(info['duration']-8)<.1
    if os.getenv('LF_EVIDENCE'): shutil.copyfile(out,Path(os.environ['LF_EVIDENCE'])/'looped_footage.mp4')


def test_word_timestamp_boundaries_and_visualizer_continuity():
    row={'text':'one two three four five six seven eight','start':0.,'end':8.}
    plan=director.make_plan([row],8,[],'music',transitions=True)
    assert ' '.join(c['text'] for s in plan['scenes'] for c in s['captions'])==row['text']
    assert all('transition' not in s and 'dip_out' not in s for s in plan['scenes'])


def test_semantic_reselection_and_plugin_protection(tmp_path,monkeypatch):
    assets=[{'id':'a'*32+'.png','name':'A','kind':'image'},{'id':'b'*32+'.png','name':'B','kind':'image'}]
    lines=[{'text':'night forest','start':0,'end':4}]
    monkeypatch.setattr(intel,'semantic_scores',lambda *args:{'night forest':{assets[0]['id']:0.,assets[1]['id']:1.}})
    plan=director.make_plan(lines,4,assets,'doc')
    intel.apply_semantic(plan,tmp_path,assets)
    assert plan['scenes'][0]['asset']==assets[1]['id'] and plan['semantic_changes']==1
    plan=director.make_plan(lines,4,assets,'plugin');original=plan['scenes'][0]['asset']
    intel.apply_semantic(plan,tmp_path,assets)
    assert plan['scenes'][0]['asset']==original


def test_coalesce_retains_global_caption_time():
    plan=director.make_plan([{'text':'one two three four five six seven eight','start':0.,'end':8.}],8,[],'music')
    intel.coalesce_visualizers(plan)
    assert len(plan['scenes'])==1 and plan['scenes'][0]['frames']==240
    assert plan['continuous_visualizer'] and intel.review(plan)['errors']==0
    assert ' '.join(c['text'] for c in plan['scenes'][0]['captions'])=='one two three four five six seven eight'


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_detect_actual_steady_click_grid(tmp_path):
    source=tmp_path/'click.wav'; rate=11025; seconds=12
    with wave.open(str(source),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate)
        f.writeframes(array('h',(round(18000*math.sin(2*math.pi*2500*i/rate)) if (i%(round(rate*.5)))<120 else 0 for i in range(rate*seconds))).tobytes())
    info=intel.beat_info(source,seconds)
    assert abs(info['bpm']-120)<2 and info['confidence']>=.5
    plan=director.make_plan([],seconds,[],'music',analysis=info)
    assert plan['beat_aligned']
    assert all(min(abs(s['start']-b) for b in info['beats'])<1/30+.001 for s in plan['scenes'][1:])


def test_local_worker_missing_model_falls_back(tmp_path,monkeypatch):
    monkeypatch.setenv('SKELLYMOTION_VISION_MODEL',str(tmp_path/'missing'))
    with pytest.raises(RuntimeError,match='not configured'):intel.semantic_scores(tmp_path,[],[])


def test_disabled_assets_do_not_return_through_semantic_reranking(tmp_path,monkeypatch):
    assets=[{'id':'a'*32+'.png','name':'forest','kind':'image'}, {'id':'b'*32+'.png','name':'forest','kind':'image','disabled':True}]
    monkeypatch.setattr(intel,'semantic_scores',lambda *args:{'forest':{assets[0]['id']:.8,assets[1]['id']:1.}})
    plan=director.make_plan([{'text':'forest','start':0,'end':4}],4,assets,'doc')
    intel.apply_semantic(plan,tmp_path,assets)
    assert plan['scenes'][0]['asset']==assets[0]['id']
