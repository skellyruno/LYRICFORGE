from pathlib import Path
import json, subprocess, shutil
import pytest
import studio_timeline as t

A={'source':{'duration':10.,'has_audio':True},'city':{'duration':5.,'has_audio':False},'forest':{'duration':4.,'has_audio':True}}

def test_compound_ripple_and_preserve_audio():
    p=t.plan(A,'cut 2s to 4s; insert city at 2s for 1s; replace 4s to 6s with forest from 1s')
    assert p['frames']==270
    assert p['pieces'][1]['audio'] is None
    assert p['pieces'][2]['asset']=='source'
    assert p['pieces'][3]['asset']=='forest' and p['pieces'][3]['audio']=='source'
    assert p['pieces'][3]['audio_start']==150
    assert p['pieces'][4]['start']==210

@pytest.mark.parametrize('text',['cut 0 to 10','cut 8 to 2','cut 4 to 20','insert missing at 0 for 1','insert city at 0 for 9','replace 0 to 3 with city from 4','cut 0 to 1; nonsense','cut 0:61 to 70','insert ../secret at 0 for 1'])
def test_rejections(text):
    with pytest.raises(ValueError):t.plan(A,text)

def test_words_survive_visual_replacement():
    p=t.plan(A,'replace 2 to 4 with city; cut 6 to 8')
    words=[{'text':'cross','start':1.9,'end':2.1},{'text':'lost','start':6.2,'end':6.4},{'text':'kept','start':8.2,'end':8.4}]
    assert [(x['text'],x['start']) for x in t.remap_words(words,p)]==[('cross',1.9),('kept',6.2)]

def test_suggestions_do_not_mutate():
    p=t.plan(A,'cut 9 to 10');before=json.dumps(p)
    s=t.suggestions(p,[{'start':1,'end':2},{'start':4,'end':5}],{})
    assert s[0]['kind']=='pacing' and json.dumps(p)==before

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg and ffprobe required')
def test_real_render(tmp_path):
    def make(name,color,hz,duration):
        p=tmp_path/name
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color={color}:s=160x90:r=30:d={duration}','-f','lavfi','-i',f'sine=f={hz}:sample_rate=48000:d={duration}','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(p)],check=True)
        return {'path':p,'duration':float(duration),'has_audio':True}
    a={'source':make('source.mp4','red',440,4),'city':make('city.mp4','blue',880,3)}
    p=t.plan(a,'cut 1 to 2; insert city at 1 for 1 muted; replace 2 to 3 with city')
    out=tmp_path/'result.mp4';t.render(p,a,out,width=160,height=90)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(out)]))
    v=next(s for s in probe['streams'] if s['codec_type']=='video');audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert int(v['nb_read_frames'])==120 and abs(float(audio['duration'])-4)<.06
    import numpy as np
    frames=subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-vf','scale=2:2','-pix_fmt','rgb24','-f','rawvideo','-'])
    rgb=np.frombuffer(frames,dtype=np.uint8).reshape(-1,4,3).mean(axis=1)
    assert rgb[15,0]>200 and rgb[45,2]>200 and rgb[75,2]>200 and rgb[105,0]>200
    pcm=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(out),'-ac','1','-ar','48000','-f','f32le','-']),dtype=np.float32)
    for second in (.5,2.5,3.5):
        x=pcm[int((second-.2)*48000):int((second+.2)*48000)]
        assert abs(np.argmax(abs(np.fft.rfft(x)))*48000/len(x)-440)<5
    assert np.max(np.abs(pcm[57600:86400]))<.005


def test_tag_matched_cutaway_is_explicit_and_preserves_audio():
    p=t.plan(A,'cut 9 to 10')
    words=[{'text':'city','start':2,'end':2.4}]
    hints=t.suggestions(p,words,{'city':{'duration':5.,'keywords':['city']}})
    assert hints[0]['kind']=='relevant cutaway'
    assert hints[0]['instruction'].endswith('with city keep audio')
    assert t.plan(A,hints[0]['instruction'])['duration']==10
    assert p['duration']==9
