import shutil
import subprocess
import wave
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parent))
from finalize_master import finalize

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg tools required')

@pytest.fixture(scope='module')
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp('media')
    cuts = [0, 3, 8, 15, 24, 35]
    clips = []
    for i, (a,b) in enumerate(zip(cuts,cuts[1:])):
        p = root/f'clip-{i}.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'color=c={i*111111+111111}:s=160x90:r=60', '-frames:v',str(b-a),'-c:v','libx264','-pix_fmt','yuv420p','-bf','0','-video_track_timescale','60000',str(p)],check=True,capture_output=True)
        clips.append(p)
    mix = root/'mix.wav'
    with wave.open(str(mix),'wb') as f:
        f.setparams((2,2,48000,0,'NONE','not compressed'));f.writeframes(bytes(35*800*4))
    return dict(fps=60,frames=35,chapter_frames=cuts),clips,mix

def test_exact_lossless_picture(media,tmp_path):
    clock,clips,mix=media
    out=tmp_path/'master.mp4'
    r=finalize(clock,clips,mix,out)
    assert r['frames']==35 and r['audio_input_samples']==28000 and r['video_packet_hashes_identical'] and out.exists()
    with pytest.raises(ValueError,match='new MP4'):finalize(clock,clips,mix,out)

def test_reject_short_mix(media,tmp_path):
    clock,clips,_=media
    mix=tmp_path/'short.wav'
    with wave.open(str(mix),'wb') as f:f.setparams((2,2,48000,0,'NONE','not compressed'));f.writeframes(bytes(100*4))
    with pytest.raises(ValueError,match='mix length'):finalize(clock,clips,mix,tmp_path/'bad.mp4')
    assert not (tmp_path/'bad.mp4').exists()

def test_reject_wrong_scene_clock(media,tmp_path):
    clock,clips,mix=media
    with pytest.raises(ValueError,match='scene format or clock'):finalize(clock,[clips[1],clips[0],*clips[2:]],mix,tmp_path/'bad.mp4')
    assert not (tmp_path/'bad.mp4').exists()

def test_reject_bad_clock(media,tmp_path):
    clock,clips,mix=media
    with pytest.raises(ValueError,match='narration clock'):finalize({**clock,'chapter_frames':[0,3,8,8,24,35]},clips,mix,tmp_path/'bad.mp4')
