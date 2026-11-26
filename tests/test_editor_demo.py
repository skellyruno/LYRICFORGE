"""Synthetic fixtures only: actual JUCE capture is an independent SkellCore gate."""
import csv,json,shutil,wave
import numpy as np
import pytest
from PIL import Image,ImageDraw
import studio_editor_demo as demo


def fixture(root):
    root.mkdir();n=2000;count=24;dry=np.full(count*n,2000,dtype='<i2');wet=dry.copy()
    meta={'schema':'skell.demo.editor.v1','origin':'offline_juce_editor','product':'Skell Quickstart','revision':'a'*40,'parameter':'gain','fps':24,'frame_count':count,'sample_rate':48000,'samples':count*n,'width':480,'height':330}
    (root/'capture.json').write_text(json.dumps(meta))
    with (root/'editor.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(demo.FIELDS)
        for i in range(count):
            gain=.5+i*.05;v=round(2000*gain);wet[i*n:(i+1)*n]=v
            writer.writerow([i,i*n,'gain',gain/2,gain,2000/32768,v/32768,2000/32768,v/32768])
            im=Image.new('RGB',(480,330),(12,17,14));d=ImageDraw.Draw(im)
            for j in range(24):d.rectangle((j*20,0,j*20+19,165),fill=(j*10,45,80))
            d.rectangle((10+i*18,190,28+i*18,300),fill=(100,250,100));im.save(root/f'frame_{i:06}.png')
    for name,x in [('dry.wav',dry),('processed.wav',wet)]:
        with wave.open(str(root/name),'wb') as f:f.setparams((1,2,48000,0,'NONE','not compressed'));f.writeframes(x.tobytes())
    return root


def test_editor_seal_and_tamper(tmp_path):
    root=fixture(tmp_path/'capture');assert demo.seal(root)['distinct_frames']==24
    assert demo.validate(root)['gain_range']==pytest.approx([.5,1.65])
    (root/'frame_000000.png').write_bytes((root/'frame_000001.png').read_bytes())
    with pytest.raises(ValueError,match='integrity'):demo.validate(root)


def test_editor_rejects_audio_mismatch(tmp_path):
    root=fixture(tmp_path/'capture');p=root/'editor.csv';s=p.read_text().replace('0.5,0.06103515625','0.5,0.5',1);p.write_text(s)
    with pytest.raises(ValueError,match='meter/audio'):demo.seal(root)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_editor_render_fixture(tmp_path):
    root=fixture(tmp_path/'capture');demo.seal(root);path=demo.render(root,tmp_path/'out');assert path.stat().st_size>1024
    report=json.loads((path.parent/'editor_demo_report.json').read_text())
    assert report['meta']['frame_count']==24 and report['max_meter_error']<=.0001
    assert (path.parent/'dry_reference.wav').read_bytes()==(root/'dry.wav').read_bytes()
    assert (path.parent/'processed_reference.wav').read_bytes()==(root/'processed.wav').read_bytes()


def test_native_double_resolution_capture_contract(tmp_path):
    root=fixture(tmp_path/'capture');meta=json.loads((root/'capture.json').read_text());meta.update(width=960,height=660)
    (root/'capture.json').write_text(json.dumps(meta))
    # Synthetic fixture checks importer bounds only, not native capture fidelity.
    for path in root.glob('frame_*.png'):
        with Image.open(path) as image: enlarged=image.resize((960,660))
        enlarged.save(path)
    result=demo.seal(root)
    assert result['meta']['width']==960 and result['distinct_frames']==24
