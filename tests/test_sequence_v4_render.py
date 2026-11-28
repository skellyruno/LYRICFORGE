import json,shutil,subprocess,pytest
import numpy as np
import studio_sequence as seq
import studio_sequence_render as renderer

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
def test_render_sfx_slice_and_hardware_fallback(tmp_path,monkeypatch):
    src=tmp_path/'src.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=160x90:r=30:d=3','-c:v','libx264','-threads','1',str(src)],check=True)
    a={'source':{'path':src,'duration':3.,'has_video':True,'has_audio':False}}
    s=seq.apply(seq.initial(a),{'op':'put','layer':{'id':'fx','kind':'sfx','at':15,'length':45,'effect':'riser','gain':.5}},a)
    ref=tmp_path/'original.mp4';renderer.render(s,a,ref,width=160,height=90)
    s=seq.apply(s,{'op':'ripple','instruction':'cut 1 to 1.5'},a)
    assert s['layers'][1]['offset']==30
    run=renderer.run;calls=[]
    monkeypatch.setattr(renderer.perf,'available_gpu_encoders',lambda:('h264_qsv',))
    def fail_gpu(args,*rest,**kw):
        calls.append(args)
        if 'h264_qsv' in args:raise RuntimeError('simulated encoder failure')
        return run(args,*rest,**kw)
    monkeypatch.setattr(renderer,'run',fail_gpu)
    out=tmp_path/'cut.mp4';stats=renderer.render(s,a,out,width=160,height=90,encoder='auto')
    assert stats['encoder']=='libx264' and 'h264_qsv' in stats['fallback'] and len(calls)==2
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=duration,nb_frames','-of','json',str(out)]));assert all(float(x['duration'])==2.5 for x in probe['streams'])
    def audio(path):return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vn','-ac','1','-ar','48000','-f','f32le','pipe:1']),dtype=np.float32)
    orig=audio(ref);cut=audio(out)
    # After the edit, retained SFX samples are shifted by exactly 0.5s, not restarted.
    aa=orig[74400:90000];bb=cut[50400:66000];assert np.corrcoef(aa,bb)[0,1]>.98


@pytest.mark.parametrize("major,expected", [(6,"-filter_complex_script"),(7,"-/filter_complex"),(8,"-/filter_complex")])
def test_sequence_graph_file_compatibility(major, expected, monkeypatch):
    monkeypatch.setattr(renderer.edit, "ffmpeg_major", lambda: major)
    assert renderer.edit.graph_file_args("graph with spaces.txt") == [expected,"graph with spaces.txt"]
