import shutil,subprocess,wave
import pytest
import studio_audio_proof as proof


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_audio_proof_preserves_aligned_pcm(tmp_path):
    source=[]
    for label,frequency,duration in [('voice',220,1),('dry',330,4),('wet',440,4)]:
        path=tmp_path/(label+'.wav')
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=f={frequency}:d={duration}:r=48000','-c:a','pcm_s24le',str(path)],check=True)
        source.append(path)
    voice,before,after=source
    run=lambda args,**kw:subprocess.run(args,check=True,timeout=kw['timeout'])
    result=proof.append_proof(voice,before,after,{'duration':1.,'lines':[{'text':'Narration','start':0,'end':1}]},1,2,run)
    assert result['duration']==5.5
    with wave.open(str(voice)) as wav:
        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(48000,2,3)
        wav.setpos(72000)
        for path in (before,after):
            expected=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-ss','1','-t','2','-ac','2','-ar','48000','-f','s24le','-'])
            assert wav.readframes(96000)==expected
    assert result['audio_proof']['playback_gain']=='unchanged'
