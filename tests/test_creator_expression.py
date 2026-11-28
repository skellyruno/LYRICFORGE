import shutil,wave
import numpy as np
import pytest
import studio_creator as c
import studio_voice as v

def test_explicit_provider_does_not_change_auto(monkeypatch):
    monkeypatch.delenv('LYRICFORGE_EXPRESSION_PYTHON',raising=False)
    monkeypatch.delenv('LYRICFORGE_EXPRESSION_MODEL',raising=False)
    assert not c.voice_options()['expressive']
    with pytest.raises(ValueError):c.resolve_voice('expressive')
    monkeypatch.setattr(c,'expression_config',lambda:('python','worker','model'))
    monkeypatch.setattr(c,'kokoro_config',lambda:('python','worker','model','voices'))
    assert c.resolve_voice('auto')=='kokoro' and c.resolve_voice('expressive')=='expressive'
    assert v.expression_direction('Listen to the sound.','Proof','neutral')=='compare'
    assert v.expression_direction('Listen to the sound.','Proof','neutral','close')=='close'

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_expression_preserves_original_caption(monkeypatch,tmp_path):
    monkeypatch.setattr(c,'expression_config',lambda:('python','worker','model'))
    received={}
    def fake(phrases,root,directions,check_cancel):
        received.update(phrases=phrases,directions=directions)
        files=[]
        for i,p in enumerate(phrases):
            path=root/f'expressive-{i:04d}.wav'
            samples=(6000*np.sin(2*np.pi*220*np.arange(24000)/24000)).astype('<i2')
            with wave.open(str(path),'wb') as f:f.setparams((1,2,24000,0,'NONE',''));f.writeframes(samples.tobytes())
            files.append(path)
        return files
    monkeypatch.setattr(c,'expressive_batch',fake)
    out=tmp_path/'voice.wav'
    r=c.narration([{'title':'Intro','narration':'Skelliere sounds different.','voice_direction':'reveal'}],out,'expressive',delivery='cinematic',pronunciation={'Skelliere':'Skell ee air'})
    assert received=={'phrases':['Skell ee air sounds different.'],'directions':['reveal']}
    assert r['provider']=='expressive' and r['lines'][0]['text']=='Skelliere sounds different.'
    assert out.is_file() and r['duration']>1.

def test_expression_batch_fails_closed(monkeypatch,tmp_path):
    monkeypatch.setattr(c,'expression_config',lambda:('python','worker','model'))
    def fail(*a,**k):raise RuntimeError('Not run')
    monkeypatch.setattr(c,'run_checked',fail)
    with pytest.raises(ValueError):c.expressive_batch(['a']*61,tmp_path,['steady']*61,lambda:None)
    with pytest.raises(ValueError):c.expressive_batch(['a'*241],tmp_path,['steady'],lambda:None)
    with pytest.raises(RuntimeError):c.expressive_batch(['test'],tmp_path,['steady'],lambda:None)
