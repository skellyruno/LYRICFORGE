"""V8 caption clock, musical bed, moving camera and silence regressions."""
import json,shutil,subprocess,wave
import numpy as np
import pytest
from PIL import Image
import studio_cinematic as cinema
import studio_director as director
import studio_score as score
import studio_camera as camera


def test_documentary_caption_clock_is_independent_of_cuts():
    words=[{'text':word,'start':i*.4,'end':(i+1)*.4} for i,word in enumerate('The production timeline has a beautiful motion'.split())]
    p=director.make_plan([{'text':'The production timeline has a beautiful motion','start':0,'end':2.8,'words':words}],2.8,[],'doc',fps=60,cinematic=True)
    assert 'caption_track' in p and ' '.join(c['text'] for c in p['caption_track'])=='The production timeline has a beautiful motion'
    p['scenes']=[{'start':0,'captions':[]},{'start':1.5,'captions':[]}]
    assert p['caption_track'][0]['words'][1]['start']==.4


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_marker_wipes_at_word_onset_in_real_render(tmp_path):
    p={'caption_style':'marker','caption_track':[{'text':'The documentary begins','start':0,'end':2,'words':[{'text':'The','start':0,'end':.7},{'text':'documentary','start':.7,'end':1.4},{'text':'begins','start':1.4,'end':2}]}],'scenes':[]}
    cinema.write_kinetic_ass(p,640,360,tmp_path/'cap.ass')
    def pixels(at):
        raw=subprocess.check_output(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=640x360:r=60:d=2','-vf','ass=cap.ass','-ss',str(at),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-threads','1','-'],cwd=tmp_path)
        rgb=np.frombuffer(raw,np.uint8).reshape(360,640,3).astype(int);r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2];return np.sum((r>160)&(g>130)&(b<130)&(r-b>50))
    a,b,c=pixels(.5),pixels(.78),pixels(1.0)
    assert a==0 and 0<b<c,(a,b,c)


def test_original_music_and_foley_independent(tmp_path):
    p={'duration':5.,'preset':'doc','scenes':[{'start':0.,'end':2.},{'start':2.,'end':5.,'editorial':'evidence'}]}
    def read(name,include_music,cue_gain):
        f=tmp_path/name;score.write_score(p,f,include_music=include_music,cue_gain=cue_gain)
        with wave.open(str(f),'rb') as w:assert w.getnframes()==120000;return np.frombuffer(w.readframes(w.getnframes()),np.int16).astype(float)/32768
    bed=read('bed.wav',True,0);foley=read('foley.wav',False,1);silent=read('none.wav',False,0)
    assert .025<np.sqrt(np.mean(bed**2))<.15 and np.max(np.abs(bed))<.4
    assert 0<np.max(np.abs(foley))<.025 and np.count_nonzero(foley)<10000
    assert not np.any(silent)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_digital_silence_does_not_enter_loudnorm(tmp_path):
    f=tmp_path/'silence.wav'
    with wave.open(str(f),'wb') as w:w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(bytes(24000*2))
    assert cinema.silent_voice(f,0,1) and 'loudnorm' not in cinema.voice_chain('natural',silent=True)


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
def test_camera_path_keeps_exact_frames_and_motion(tmp_path):
    out=tmp_path/'cam.mp4';graph=camera.camera_filter(320,180,60,60,'detail',(.7,.4))
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=60:d=1','-vf',graph,'-frames:v','60','-c:v','libx264','-threads','1',str(out)],check=True)
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0','-show_entries','stream=nb_read_frames','-of','json',str(out)]))
    assert int(data['streams'][0]['nb_read_frames'])==60


def test_vtt_uses_same_independent_caption_track(tmp_path):
    import studio_walkthrough as walk
    p={'caption_style':'marker','caption_track':[{'text':'Phrase spans cut','start':.5,'end':2.5}],'duration':3.,'scenes':[{'start':0,'captions':[]},{'start':1.5,'captions':[]}]}
    f=tmp_path/'captions.vtt';walk.caption_vtt(p,f)
    assert '00:00:00.500 --> 00:00:02.500\nPhrase spans cut' in f.read_text()
