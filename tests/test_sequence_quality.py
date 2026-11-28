import json,shutil,subprocess
import pytest
import studio_sequence as seq
import studio_sequence_render as renderer
import studio_sequence_quality as q

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg tools required')
def test_picture_copy_requires_exact_clock_and_preserves_packets(tmp_path):
    src=tmp_path/'normalized.mp4';out=tmp_path/'out.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=2','-f','lavfi','-i','sine=r=48000:d=2','-ac','2','-c:v','libx264','-bf','0','-threads','1','-c:a','aac','-video_track_timescale','30000',str(src)],check=True)
    assets={'source':{'path':src,'duration':2.,'has_video':True,'has_audio':True}}
    state=seq.initial(assets);assert q.picture_copy_source(state,assets,160,90)==src.resolve()
    r=renderer.render(state,assets,out,width=160,height=90);assert r['encoder']=='copy' and r['review']['frames']==60
    def packet_hashes(path):return [p['data_hash'] for p in q.probe(path,'-select_streams','v:0','-show_packets','-show_data_hash','sha256','-show_entries','packet=data_hash')['packets']]
    assert packet_hashes(src)==packet_hashes(out)
    assert q.picture_copy_source(state,assets,320,180) is None
    edit=seq.apply(state,{'op':'ripple','instruction':'cut 0 to 0.5'},assets)
    assert q.picture_copy_source(edit,assets,160,90) is None
    with pytest.raises(RuntimeError,match='clock') : q.verify(out,61,160,90)
