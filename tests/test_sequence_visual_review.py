import subprocess,shutil
import pytest
import studio_sequence as seq
import studio_sequence_render as renderer
import studio_sequence_visual_review as review

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
def test_actual_cutaway_and_wrong_source_review(tmp_path):
    src=tmp_path/'base.mp4';shot=tmp_path/'shot.mp4';out=tmp_path/'render.mp4'
    def ff(*a):subprocess.run(['ffmpeg','-v','error','-y',*map(str,a)],check=True)
    ff('-f','lavfi','-i','color=c=red:s=160x90:r=30:d=4','-c:v','libx264','-threads','1',src)
    ff('-f','lavfi','-i','testsrc2=s=160x90:r=30:d=4','-c:v','libx264','-threads','1',shot)
    assets={'source':{'path':src,'duration':4.,'has_video':True,'has_audio':False},'shot':{'path':shot,'duration':4.,'has_video':True,'has_audio':False}}
    s=seq.apply(seq.initial(assets),{'op':'put','layer':{'id':'a','kind':'visual','asset':'shot','at':30,'length':60,'offset':15,'fade':3}},assets)
    renderer.render(s,assets,out,width=160,height=90)
    r=review.review(out,s,assets,160,90);assert r['counts']['consistent']==2 and not r['needs_review'],r
    r=review.review(src,s,assets,160,90);assert r['counts']['mismatch']==2 and r['needs_review'],r
