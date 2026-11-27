import numpy as np
from PIL import Image
import studio_spatial as spatial
import studio_director as d
import studio_musical_edit as m

def test_homography_and_perspective():
    im=Image.new('RGB',(300,200),'#00bb55');s=spatial.SpatialShot(im,640,360,{'start':0,'end':5},d.font)
    p,v,r=s.geometry(0);q,_,_=s.geometry(5)
    assert np.ptp(v[:,2])>.2 and abs(p[0,1]-p[1,1])>5
    assert abs(q[0,1]-q[1,1])<1e-8 and np.max(np.abs(p-q))>10
    assert np.all(np.isfinite(p)) and np.all(v[:,2]>0)
    a=np.asarray(s.render(0));b=np.asarray(s.render(5));assert np.mean(np.abs(a.astype(float)-b))>2
    assert np.all(b[153,320]==[0,187,85])
    c=Image.new('RGB',(640,360),'red');assert np.array_equal(np.asarray(s.bridge(c,0,.8)),b)
    assert np.array_equal(np.asarray(s.bridge(c,.8,.8)),np.asarray(c))
    assert not np.array_equal(np.asarray(s.bridge(c,.4,.8)),b)

def test_beat_snap_preserves_narration_and_total():
    p={'fps':60,'frames':840,'caption_style':'marker','caption_track':[{'start':1,'end':4,'text':'test'}], 'scenes':[
       {'start':0,'end':6.7,'frames':402,'spatial_motion':True}, {'start':6.7,'end':14,'frames':438,'editorial':'graphic','bridge_scene':{'start':0,'end':6.7}}]}
    q=m.align_generated_cuts(p);assert q['beat_locked_cuts'] and sum(x['frames'] for x in q['scenes'])==840
    assert q['caption_track']==p['caption_track'] and p['scenes'][0]['end']==6.7
    assert q['scenes'][1]['start']==q['scenes'][0]['end']==q['scenes'][1]['bridge_scene']['end']
    assert abs(q['scenes'][0]['end']-q['beat_locked_cuts'][0]['beat']*60/88)<=1/60
    p['scenes'][0]['recorded_demo']=True;assert not m.align_generated_cuts(p)['beat_locked_cuts']

def test_bridge_provenance_recomputed():
    s=[{'start':0,'end':4,'frames':240,'asset':'a'*32+'.png','asset_role':'plugin_state','product_motion':True}, {'start':4,'end':8,'frames':240,'graphic':{'kind':'process'}}]
    d.configure_spatial(s,60);assert s[1]['spatial_bridge']==s[0]['asset']
    s[0]['asset_role']='broll';d.configure_spatial(s,60);assert 'spatial_motion' not in s[0] and 'spatial_bridge' not in s[1]

def test_beat_retimed_scene_captions_review():
    p={'fps':60,'frames':720,'caption_style':'marker','caption_track':[{'start':6.3,'end':7.1,'text':'keep the original speech clock','words':[{'text':'keep','start':6.3,'end':6.6},{'text':'clock','start':6.6,'end':7.1}]}], 'scenes':[
       {'start':0,'end':6.7,'frames':402,'spatial_motion':True,'captions':[]}, {'start':6.7,'end':12,'frames':318,'editorial':'graphic','captions':[]}]}
    q=m.align_generated_cuts(p)
    import studio_director_intelligence as intel
    assert intel.review(q)['errors']==0
    assert q['caption_track']==p['caption_track']
    assert q['scenes'][0]['captions'][0]['end']<=q['scenes'][0]['frames']/60

def test_spatial_bridge_render_exact_clock(tmp_path):
    import shutil, subprocess, wave, json, pytest
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg required')
    fps=24;assets=tmp_path/'assets';assets.mkdir();key='a'*32+'.png'
    Image.new('RGB',(480,300),'#00bb55').save(assets/key)
    n=65;total=132;boundary=n/fps;duration=total/fps
    base={'type':'broll','text':'','captions':[],'camera':'still','cinematic_finish':True,'brand':'TEST'}
    g={'kind':'process','title':'Production flow','source':'Test fixture','items':[{'label':'One'},{'label':'Two'}]}
    plan={'preset':'doc','fps':fps,'duration':duration,'frames':total,'scenes':[{**base,'start':0,'end':boundary,'frames':n,'asset':key,'asset_role':'plugin_state','product_motion':True},{**base,'type':'big_text','start':boundary,'end':duration,'frames':total-n,'graphic':g,'editorial':'graphic','editorial_look':'midnight'}],'silent':False,'cinematic_finish':True,'crossfades':False,'caption_style':'off','caption_track':[],'sound_design':True,'cue_gain':0.}
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(np.rint(5000*np.sin(np.arange(round(duration*24000))*.07)).astype('<i2').tobytes())
    out=tmp_path/'out.mp4'
    stats=d.render(plan,audio,assets,tmp_path/'cache',out,{'fps':fps},(320,180),lambda rows,path:path.write_text(''),lambda args,cwd,*_:subprocess.run(args,cwd=cwd,check=True,capture_output=True),lambda:None,lambda *_:None)
    assert stats['spatial_shots']==1 and stats['beat_locked_cuts']
    assert plan['scenes'][1]['spatial_bridge']==key
    assert d.encoded_frames(out)==total
    stream=json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=avg_frame_rate,duration","-of","json",str(out)]))["streams"][0]
    assert stream["avg_frame_rate"]==f"{fps}/1" and abs(float(stream["duration"])-duration)<.00001


def test_beat_retime_drops_tiny_local_fragments_only():
    p={'fps':60,'frames':840,'caption_style':'marker','caption_track':[{'start':6.817,'end':8.0,'text':'keep the original sentence'}], 'scenes':[{'start':0,'end':6.7,'frames':402,'spatial_motion':True,'captions':[]},{'start':6.7,'end':14,'frames':438,'editorial':'graphic','captions':[]}]}
    q=m.align_generated_cuts(p)
    assert q['beat_locked_cuts'] and q['scenes'][0]['captions']==[]
    assert q['caption_track']==p['caption_track'] and q['scenes'][1]['captions']
