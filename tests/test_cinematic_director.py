"""Finishing and exact-frame dissolve regressions; no network or model required."""
import json
import subprocess
import wave
import shutil
import numpy as np
import pytest
from PIL import Image
import studio_cinematic as cinema
import studio_director as director
import studio_director_intelligence as intel
import server
from test_scene_director import project


def test_word_timings_survive_scene_clipping_and_ass(tmp_path):
    rows=[{'text':'first second third','start':0.,'end':2.,'words':[{'text':'first','start':.1,'end':.4},{'text':'second','start':.55,'end':.9},{'text':'third','start':1.2,'end':1.9}]}]
    captions,_=intel.captions_for(rows,0.,2.)
    assert captions[0]['words'][1]['start']==.55
    plan={'scenes':[{'start':0,'captions':captions}]}
    out=tmp_path/'captions.ass';cinema.write_kinetic_ass(plan,1920,1080,out)
    text=out.read_text(encoding='utf-8-sig');assert r'\kf30' in text and r'\kf35' in text and r'\move(' in text
    assert 'second' in text and 'third' in text


def test_original_bed_is_deterministic_bounded_and_exact(tmp_path):
    plan={'duration':3.1,'scenes':[{'start':0},{'start':1.5}]}
    a=tmp_path/'a.wav';b=tmp_path/'b.wav';c=tmp_path/'c.wav'
    cinema.original_bed(plan,a);cinema.original_bed(plan,b);cinema.original_bed(plan,c,include_music=False)
    assert a.read_bytes()==b.read_bytes()
    with wave.open(str(a),'rb') as f:
        assert f.getnframes()==round(3.1*24000);assert f.getnchannels()==2
        data=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2');assert 100<np.max(np.abs(data.astype(float)))<5000
    with wave.open(str(c),'rb') as f:
        x=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,2);assert np.all(x[:20000]==0);assert np.any(x[33000:42000]!=0)


def test_actual_ui_and_diagram_are_both_selected():
    asset={'id':'a'*32+'.png','name':'plugin retune speed knob','kind':'image','description':'retune speed knob zero milliseconds'}
    lines=[{'text':'Turn the retune speed knob','start':0,'end':4}, {'text':'Conceptually pitch correction moves toward a target note','start':4,'end':8}]
    p=director.make_plan(lines,8,[asset],'plugin',diagrams=True,cinematic=True,transitions=True)
    assert [s['type'] for s in p['scenes']]==['ui_demo','diagram'];assert p['crossfades'] and p['review']['errors']==0


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg required')
def test_overlap_is_not_black_and_frame_count_is_exact(tmp_path):
    clips=[];fps=24
    for i,color in enumerate(('red','blue')):
        p=tmp_path/f'c{i}.mp4';subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color=c={color}:s=320x180:r={fps}:d=2','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(p)],check=True);clips.append(p)
    scenes=[{'type':'ui_demo','frames':48},{'type':'diagram','frames':48}]
    def encode(args,cwd,*_):subprocess.run(args,cwd=cwd,check=True,capture_output=True)
    rendered,count=cinema.crossfade_clips(clips,scenes,fps,tmp_path,encode,lambda:None,4.)
    assert count==1
    f=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','json',str(rendered[1])]))
    assert int(f['streams'][0]['nb_read_frames'])==48
    raw=subprocess.check_output(['ffmpeg','-v','error','-ss','0.125','-i',str(rendered[1]),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-']);rgb=np.frombuffer(raw,np.uint8).reshape(-1,3).mean(0)
    assert rgb[0]>40 and rgb[2]>40 and rgb[1]<35,rgb


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg required')
def test_cinematic_export_with_music_and_sfx(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch,duration=4.2)
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    route=f'/api/projects/{p.name}/director/render';r=c.post(route,json={'preset':'plugin','preview':True,'cinematic_finish':True,'transitions':True,'sound_design':True});assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_audio'] and info['has_video'] and abs(info['duration']-4.2)<.15
    assert job['outputs']['crossfades']==1
