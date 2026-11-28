import json,shutil,subprocess
import pytest
from studio_sequence_deep_review import parse,review


def test_measurement_contract():
    progress='frame=60\nprogress=end\n'
    data={'input_i':'-16.0','input_tp':'-1.2','input_lra':'3.0'}
    assert not parse(progress,json.dumps(data),60)['needs_review']
    data['input_tp']='-0.2'
    assert parse(progress,json.dumps(data),60)['needs_review']
    data.update(input_i='-inf',input_tp='-inf')
    assert parse(progress,json.dumps(data),60)['integrated_lufs'] is None
    with pytest.raises(RuntimeError):parse(progress,json.dumps(data),61)
    with pytest.raises(RuntimeError):parse('frame=60\nprogress=continue\n',json.dumps(data),60)
    with pytest.raises(RuntimeError):parse(progress,'',60)

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_real_decode_review(tmp_path):
    path=tmp_path/'take.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=2','-f','lavfi','-i','sine=r=48000:d=2','-c:v','libx264','-threads','1','-c:a','aac','-ac','2',str(path)],check=True)
    before=path.read_bytes();r=review(path,60)
    assert r['decoded_frames']==60 and r['integrated_lufs'] is not None and r['true_peak_dbtp'] is not None
    assert path.read_bytes()==before
    with pytest.raises(RuntimeError):review(path,61)
    broken=tmp_path/'broken.mp4';broken.write_bytes(before[:100])
    with pytest.raises(RuntimeError):review(broken,60)
