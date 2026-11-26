import csv,json,math,shutil,wave
from pathlib import Path
import numpy as np
import pytest
import studio_demo as demo


def fixture(root):
    root.mkdir();rate=8000;frames=8000;block=400
    dry=np.tile(np.array([1000,-1000],dtype='<i2'),frames//2);wet=dry//2
    for name,x in [('dry.wav',dry),('processed.wav',wet),('sidechain.wav',dry)]:
        with wave.open(str(root/name),'wb') as f:f.setparams((1,2,rate,0,'NONE','not compressed'));f.writeframes(x.astype('<i2').tobytes())
    (root/'capture.json').write_text(json.dumps({'schema':'skell.demo.capture.v1','origin':'offline_core','revision':'a'*40,'product':'Fixture','stimulus':'synthetic fixture','parameter':'amount','meter':'LiveMultibandDucker.copyDisplayBands channel 0','sample_rate':rate,'frames':frames,'engine_latency_samples':0}))
    (root/'events.csv').write_text('sample,parameter,normalized\n0,amount,0\n4000,amount,0.5\n')
    with (root/'meters.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(demo.METER_FIELDS)
        for pos in range(0,frames,block):w.writerow([pos,block,1000/32768,500/32768,1000/32768,500/32768,*([6]*10)])
    return root


def test_seal_verify_and_no_overwrite(tmp_path):
    root=fixture(tmp_path/'test');assert len(demo.seal(root)['meters'])==20
    assert demo.validate(root)['events']==[(0,0),(4000,.5)]
    with pytest.raises(FileExistsError):demo.seal(root)
    (root/'events.csv').write_text('sample,parameter,normalized\n0,amount,1\n')
    with pytest.raises(ValueError,match='integrity'):demo.validate(root)


@pytest.mark.parametrize('filename,old,new,pattern',[
    ('meters.csv','0,400,','1,400,','sample clock'),
    ('meters.csv','0.030517578125','0.5','Meter/audio'),
    ('events.csv','4000,amount,0.5','4001,amount,0.5','event'),
    ('events.csv','4000,amount,0.5','4000,amount,nan','event'),
    ('events.csv','4000,amount,0.5','4000,notamount,0.5','event'),
])
def test_invalid_capture(tmp_path,filename,old,new,pattern):
    root=fixture(tmp_path/'test');p=root/filename;s=p.read_text();assert old in s;p.write_text(s.replace(old,new,1))
    with pytest.raises(ValueError,match=pattern):demo.seal(root)


def test_truncated_pcm(tmp_path):
    root=fixture(tmp_path/'test');p=root/'processed.wav';p.write_bytes(p.read_bytes()[:-16])
    with pytest.raises(ValueError,match='Truncated'):demo.seal(root)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_actual_render(tmp_path):
    root=fixture(tmp_path/'test');demo.seal(root);out=tmp_path/'render';p=demo.render(root,out)
    assert p.stat().st_size>1024
    report=json.loads((out/'measurement_report.json').read_text());assert report['video_frames']==24 and report['meter_blocks']==20
    with pytest.raises(FileExistsError):demo.render(root,out)
