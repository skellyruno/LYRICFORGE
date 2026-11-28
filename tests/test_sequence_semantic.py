import subprocess,shutil
import pytest
import studio_sequence_semantic as semantic

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_contrastive_two_frame_gate(tmp_path):
    path=tmp_path/'fixture.mp4';subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=160x90:r=30:d=3','-c:v','libx264','-threads','1',str(path)],check=True)
    windows=[('a',path,0,60),('b',path,15,60)]
    phrases=[(1.,2.,'frequency response diagram'),(5.,6.,'audio processor knobs')]
    def request(body,timeout):
        assert len(body['images'])==4 and len(body['texts'])==3
        return {'scores':[[25,24,17,17],[15,16,24,23],[12,12,12,12]]}
    assert [r['asset'] for r in semantic.match(windows,phrases,tmp_path,request)]==['a','b']
    assert not semantic.match(windows,phrases,tmp_path,lambda *a,**k:{'scores':[[20,20,20,20]]*3})
    assert not semantic.match(windows[:1],phrases,tmp_path,request)
    with pytest.raises(ValueError):semantic.match(windows,phrases,tmp_path,lambda *a,**k:{'scores':[[float('nan')]*4]*3})


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_alternate_windows_compare_distinct_sources(tmp_path):
    path=tmp_path/'fixture.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=8','-c:v','libx264','-threads','1',str(path)],check=True)
    windows=[('a',path,0,60),('a',path,150,60),('b',path,0,60)]
    def req(body,timeout):
        return {'scores':[[24,24,25,25,19,19],[10,10,10,10,10,10]]}
    rows=semantic.match(windows,[(1.,2.,'closeup knobs')],tmp_path,req)
    assert len(rows)==1 and rows[0]['asset']=='a' and rows[0]['offset']==150 and rows[0]['competitor_margin']==6.
    assert not semantic.match(windows[:2],[(1.,2.,'closeup knobs')],tmp_path,req)
