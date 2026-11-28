import numpy as np
import pytest
from PIL import Image
import studio_reference as ref
import studio_material as mat
import studio_editorial_motion as em
import studio_director as director
import studio_score as score

def test_reference_pacing_bounded_and_opt_in():
    frames=np.zeros((24,8,8,3),np.uint8);frames[4:8]=255;frames[12:16]=255;frames[20:]=255
    p=ref.profile_frames(frames,2);assert p['estimated_changes']==5
    assert ref.pacing(p,5,10)[0]<5 and ref.pacing({},5,10)==(5,10)
    lines=[{'start':0.,'end':14.,'text':'An explanation.'}]
    a=director.make_plan(lines,14,[],'doc',cinematic=True,reference_profile=p)
    assert a['reference_pacing']['pace']<5 and sum(s['frames'] for s in a['scenes'])==a['frames']
    assert 'reference_pacing' not in director.make_plan(lines,14,[],'plugin',cinematic=True,reference_profile=p)

def test_material_is_finite_and_view_dependent():
    a=mat.shade([0,-1,0],[0,-1,-1],0);b=mat.shade([0,-1,0],[1,-1,-.1],1)
    assert all(0<=v<=255 for v in a+b) and a!=b
    assert len(mat.shade([0,0,1],[0,0,-1],.5))==3

@pytest.mark.parametrize('kind',['network','route'])
@pytest.mark.parametrize('size',[(640,360),(360,640)])
def test_new_graphics_render_and_validate(kind,size):
    g={'kind':kind,'title':'Author supplied data','source':'Test fixture','items':[{'label':'Origin','lat':0,'lon':179},{'label':'Middle','lat':1,'lon':-179},{'label':'Destination','lat':2,'lon':-178}],'links':[[0,1],[1,2]]}
    shot=em.EditorialShot({'start':0,'end':4,'editorial':'graphic','editorial_look':'midnight','graphic':g},*size,None,director.font)
    assert np.mean(np.abs(np.array(shot.render(0),dtype=float)-np.array(shot.render(3),dtype=float)))>0.2
    if kind=='route':g['items'][0]['lat']=100
    else:g['links']=[[0,4]]
    with pytest.raises(ValueError):em.validate_graphic(g)

def test_score_streaming_and_breath():
    t=np.arange(0,24,.000125);a=score.music_block(t,24);b=np.concatenate([score.music_block(x,24) for x in np.array_split(t,24)])
    assert np.max(np.abs(a-b))<1e-5 and np.max(np.abs(a))<.6
    def rms(x):return np.sqrt(np.mean(x*x))
    assert rms(a[(t>10)&(t<15)])>rms(a[(t>1)&(t<5)])

def test_reverse_handoff_from_real_encoded_footage(tmp_path):
    import subprocess,shutil,wave
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    assets=tmp_path/'assets';assets.mkdir();clip='f'*32+'.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24','-t','3','-c:v','libx264','-threads','1',str(assets/clip)],check=True)
    g={'kind':'network','title':'Authored connection','source':'Test fixture','items':[{'label':'Source'},{'label':'Result'}],'links':[[0,1]]}
    base={'type':'broll','text':'','captions':[],'camera':'still','cinematic_finish':True,'brand':'TEST'}
    p={'preset':'doc','fps':24,'duration':6.,'frames':144,'scenes':[{**base,'start':0,'end':3,'frames':72,'asset':clip,'asset_role':'broll','asset_start':0,'editorial_seconds':3.},{**base,'type':'big_text','start':3,'end':6,'frames':72,'editorial':'graphic','graphic':g}], 'silent':True,'cinematic_finish':True,'crossfades':False,'caption_style':'off','caption_track':[],'sound_design':False}
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(24000*6*2))
    out=tmp_path/'out.mp4';director.render(p,audio,assets,tmp_path/'cache',out,{'fps':24},(320,180),lambda rows,path:path.write_text(''),lambda args,cwd,*_:subprocess.run(args,cwd=cwd,check=True,capture_output=True),lambda:None,lambda *_:None)
    assert director.encoded_frames(out)==144 and p['scenes'][1]['footage_bridge_seconds']>0
    assert p['scenes'][0]['asset_start']==0 and p['scenes'][0]['editorial_seconds']==3
    p['scenes'][0].update(asset_role='plugin_recording',recorded_demo=True);director.configure_spatial(p['scenes'],24);assert 'footage_bridge_seconds' not in p['scenes'][1]

def test_original_sampled_instrument_arrangement(monkeypatch,tmp_path):
    import studio_instrument_score as si
    import wave,os,ctypes.util
    from pathlib import Path
    events=si.arrange(23.8,88,score.CHORDS,24000)
    assert events==sorted(events) and events[-1][0]<=round(23.8*24000)
    assert {e[2] for e in events if e[1]}=={0,1,2,3,4}
    monkeypatch.setenv('LYRICFORGE_SOUNDFONT',str(tmp_path/'missing.sf2'))
    with pytest.raises(ValueError):score.write_score({'duration':3.,'preset':'doc'},tmp_path/'bad.wav')
    # The plugin branch ignores the optional documentary instrument bank.
    score.write_score({'duration':1.,'preset':'plugin'},tmp_path/'plugin.wav')
    bank=Path('/usr/share/sounds/sf2/TimGM6mb.sf2')
    if not bank.is_file() or not ctypes.util.find_library('fluidsynth'):pytest.skip('Local sampled instrument runtime unavailable')
    monkeypatch.setenv('LYRICFORGE_SOUNDFONT',str(bank))
    out=tmp_path/'sampled.wav';score.write_score({'duration':4.0,'preset':'doc'},out,cue_gain=0)
    with wave.open(str(out),'rb') as f:
        assert f.getnframes()==96000 and f.getnchannels()==2
        a=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(float)/32768
    assert .005<np.sqrt(np.mean(a*a))<.15 and np.max(np.abs(a))<.45
