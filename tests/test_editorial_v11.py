import numpy as np
from PIL import Image
import studio_spatial as spatial
import studio_director as director
import studio_score as score
import studio_musical_edit as musical


def test_two_plane_rack_focus_preserves_full_capture():
    src=Image.new('RGB',(800,480),'#118d52');shot=spatial.SpatialShot(src,640,360,{'start':0,'end':6},director.font)
    assert shot.detail_amount(1.2)>.9 and shot.detail_amount(6)==0
    assert np.asarray(shot.detail_layer(1.2))[:,:,3].max()>240
    assert np.asarray(shot.detail_layer(6))[:,:,3].max()==0
    assert np.all(np.asarray(shot.render(6))[153,320]==[17,141,82])
    assert np.max(np.abs(shot.geometry(1.2)[0]-shot.geometry(6)[0]))>20
    assert not spatial.SpatialShot(src,360,640,{'start':0,'end':6},director.font).multiple


def test_complete_composition_handoff_endpoints():
    a=Image.new('RGB',(640,360),'#10a05f');b=Image.new('RGB',(640,360),'#e8e3d6')
    assert np.array_equal(np.asarray(spatial.editorial_handoff(a,b,0,1)),np.asarray(a))
    assert np.array_equal(np.asarray(spatial.editorial_handoff(a,b,1,1)),np.asarray(b))
    mid=np.asarray(spatial.editorial_handoff(a,b,.5,1));assert np.any(mid[:,:,1]==227) and np.any(mid[:,:,1]<220)


def test_document_and_graphic_handoffs_provenance():
    a={'start':0,'end':4,'frames':240,'editorial':'evidence','asset':'a'*32+'.png','asset_name':'Source article'}
    b={'start':4,'end':8,'frames':240,'editorial':'graphic','graphic':{'kind':'process'}}
    c={'start':8,'end':12,'frames':240,'asset':'b'*32+'.png','asset_role':'plugin_state','product_motion':True}
    director.configure_spatial([a,b,c],60)
    assert b['editorial_bridge_asset']==a['asset'] and c['editorial_bridge_scene']['graphic']==b['graphic']
    assert 'editorial_bridge_scene' not in c['editorial_bridge_scene']
    a['asset']='a'*32+'.mp4';director.configure_spatial([a,b,c],60);assert 'editorial_bridge_scene' not in b


def test_score_arc_and_chunk_consistency():
    t=np.arange(24000*10,dtype=float)/24000
    a=score.music_block(t,18);b=np.concatenate([score.music_block(x,18) for x in np.array_split(t,10)])
    assert np.max(np.abs(a-b))<1e-5 and np.max(np.abs(a))<.5
    assert np.sqrt(np.mean(a[-24000:]**2))>np.sqrt(np.mean(a[:24000]**2))


def test_retimed_editorial_bridge_sync():
    p={'fps':60,'frames':840,'caption_track':[],'caption_style':'marker','scenes':[{'start':0,'end':6.7,'frames':402,'editorial':'graphic'},{'start':6.7,'end':14,'frames':438,'spatial_motion':True,'editorial_bridge_scene':{'start':0,'end':6.7}}]}
    q=musical.align_generated_cuts(p);assert q['beat_locked_cuts'] and q['scenes'][1]['editorial_bridge_scene']['end']==q['scenes'][0]['end']


def test_authored_document_to_real_footage_exact_clock(tmp_path):
    import subprocess,shutil,wave,pytest
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg required')
    assets=tmp_path/'assets';assets.mkdir();doc='d'*32+'.png';clip='f'*32+'.mp4'
    Image.new('RGB',(480,300),'#bcbb91').save(assets/doc)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','3','-c:v','libx264','-threads','1',str(assets/clip)],check=True)
    fps=24;duration=6.;base={'type':'broll','text':'','captions':[],'camera':'still','cinematic_finish':True,'brand':'TEST'}
    p={'preset':'doc','fps':fps,'duration':duration,'frames':144,'scenes':[{**base,'type':'document','start':0,'end':3,'frames':72,'editorial':'evidence','asset':doc,'asset_name':'Test document','asset_role':'document','evidence_focus':[.5,.5]}, {**base,'start':3,'end':6,'frames':72,'asset':clip,'asset_role':'broll','asset_start':0,'editorial_seconds':3.}], 'silent':False,'cinematic_finish':True,'crossfades':False,'caption_style':'off','caption_track':[],'sound_design':False}
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(np.rint(5000*np.sin(np.arange(144000)*.07)).astype('<i2').tobytes())
    out=tmp_path/'out.mp4';director.render(p,audio,assets,tmp_path/'cache',out,{'fps':fps},(320,180),lambda rows,path:path.write_text(''),lambda args,cwd,*_:subprocess.run(args,cwd=cwd,check=True,capture_output=True),lambda:None,lambda *_:None)
    assert p['scenes'][1]['editorial_bridge_asset']==doc and director.encoded_frames(out)==144
    assert p['scenes'][1]['asset_start']==0 and p['scenes'][1]['editorial_seconds']==3
    # Explicit recorded demonstration must not get the authored overlay.
    p['scenes'][1].update(asset_role='plugin_recording',recorded_demo=True);director.configure_spatial(p['scenes'],fps);assert 'editorial_bridge_scene' not in p['scenes'][1]
