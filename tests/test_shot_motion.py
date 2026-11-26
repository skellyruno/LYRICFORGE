import shutil,subprocess,json
import pytest
from PIL import Image,ImageDraw
import studio_shot_motion as motion

def test_action_is_not_diagram_intent():
    assert motion.prefer_diagram('A frequency-selective response creates space','','Spectral ducking')
    assert not motion.prefer_diagram('Turn the amount knob and watch the spectrum','','Spectral ducking')
    assert not motion.prefer_diagram('Listen before and after','','Compression')
    assert motion.transition_mode({'type':'document'},{'type':'diagram'},'auto')=='wipeleft'

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
@pytest.mark.parametrize('camera',('push','pull'))
def test_eased_camera_actual_video_clock(tmp_path,camera):
    src=tmp_path/'still.png';im=Image.new('RGB',(320,180),'#142019');d=ImageDraw.Draw(im)
    for x in range(0,320,12):d.line((x,0,x,179),fill='#a0f58c',width=2)
    im.save(src);out=tmp_path/'motion.mp4'
    graph=motion.camera_filter(320,180,24,48,camera,(.2,.7))
    subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-threads','1','-framerate','24','-i',str(src),'-filter_threads','1','-vf',graph,'-frames:v','48','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(out)],check=True,timeout=30)
    stream=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_streams','-of','json',str(out)]))['streams'][0]
    assert stream['nb_frames']=='48'
    assert float(stream['duration'])==pytest.approx(2,abs=.001)
    hashes=subprocess.check_output(['ffmpeg','-v','error','-threads','1','-i',str(out),'-f','framemd5','-'],timeout=30).splitlines()
    assert len({r.split(b',')[-1].strip() for r in hashes if not r.startswith(b'#')})>10

def test_4k_camera_memory_bound():
    assert motion.camera_filter(3840,2160,24,72,'push').startswith('scale=3840:2160,')
    with pytest.raises(ValueError):motion.camera_filter(1920,1080,24,0,'push')
