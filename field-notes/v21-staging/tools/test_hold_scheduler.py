import asyncio
from pathlib import Path
import pytest
import server
import studio_quick2 as q
from test_quick_tools import data,make_video,up,needs_ffmpeg

def test_hold_commands_have_independent_streams(tmp_path):
    p={'video':tmp_path/'input.mp4'}
    o=q.hold_prepare({'start':'1','end':'2'},{'video':{'duration':3,'fps':15,'has_audio':True}})
    picture=q.hold_build(p,o,tmp_path/'picture.mp4',False)
    audio=q.hold_audio_build(p,o,tmp_path/'audio.m4a')
    mux=q.hold_mux_build(tmp_path/'picture.mp4',tmp_path/'audio.m4a',tmp_path/'out.mp4')
    assert '-an' in picture and '-af' not in picture
    assert '-vn' in audio and '-vf' not in audio
    assert mux[mux.index('-c')+1]=='copy' and '-shortest' not in mux

@needs_ffmpeg
def test_hold_stage_failure_cleans_private_scratch(data,monkeypatch):
    source=make_video(data/'source.mp4',2)
    original=server.run_one_ffmpeg
    stages=[]
    def fail(project_id,job_id,stage,args,out,seconds):
        stages.append(stage)
        if stage=='hold_audio':
            out.write_bytes(b'partial')
            raise RuntimeError('injected audio stage failure')
        return original(project_id,job_id,stage,args,out,seconds)
    monkeypatch.setattr(server,'run_one_ffmpeg',fail)
    result=asyncio.run(server.quick_start('hold',{'start':'1','end':'0'},{'video':[up(source)]}))
    project=data/'data'/result['id']
    assert stages==['hold_picture','hold_audio']
    assert server.jobs[result['job_id']]['status']=='error'
    assert not (project/'held.mp4').exists()
    assert not list(project.glob('hold-*'))
