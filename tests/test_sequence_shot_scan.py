import shutil,subprocess
import pytest
import studio_sequence_shot_scan as scout

def test_allocation_and_full_range():
    assert scout.allocate([['a1','a2'],['b1','b2'],['c1','c2']],4)==['a1','b1','c1','a2']
    assert scout.offsets(120,90)[-1]==3510
    assert len(scout.offsets(120,90))==4

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_real_late_shot(tmp_path):
    p=tmp_path/'long.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=black:s=160x90:r=30:d=25','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=15','-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0','-c:v','libx264','-threads','1',str(p)],check=True)
    result=scout.scan(p,40.,90)
    assert result and all(at>=25*30 and at+90<=1200 for q,at in result),result
    assert all(q>=.35 for q,at in result)
    hits=scout._cached.cache_info().hits
    assert scout.scan(p,40.,90)==result and scout._cached.cache_info().hits==hits+1
