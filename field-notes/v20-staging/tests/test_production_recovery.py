from pathlib import Path
import sys,zipfile,wave
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from examples.frequency_narration import assemble, allocate, RATE, SAMPLES_PER_FRAME, LEAD, TAIL
from tools.reconcile_creator import archive_files, propose

def test_exact_and_extended_chapters(tmp_path):
    lengths=[RATE*7,RATE*12,RATE*15,RATE*5,RATE*11]
    cuts,beats=allocate(lengths)
    assert beats[0]==0 and all((b-a)%4==0 and b-a>=16 for a,b in zip(beats,beats[1:]))
    for i,n in enumerate(lengths):
        x=np.full(n,123+i,dtype='<i2')
        with wave.open(str(tmp_path/f'neural-{i:04d}.wav'),'wb') as f:f.setparams((1,2,RATE,0,'NONE','not compressed'));f.writeframes(x.tobytes())
    r=assemble(tmp_path,['a','b','c','d','e'])
    with wave.open(str(tmp_path/'narration.wav'),'rb') as f:y=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2')
    assert len(y)==cuts[-1]*SAMPLES_PER_FRAME and r['requires_picture_retime']
    for i,n in enumerate(lengths):
        start=cuts[i]*SAMPLES_PER_FRAME+LEAD;end=start+n
        assert np.all(y[start:end]==123+i) and not np.any(y[end:cuts[i+1]*SAMPLES_PER_FRAME])
        assert cuts[i+1]*SAMPLES_PER_FRAME-end>=TAIL
    with pytest.raises(FileExistsError):assemble(tmp_path,['a','b','c','d','e'])

def test_archive_known_legacy_evidence(tmp_path):
    z=tmp_path/'legacy.zip'
    with zipfile.ZipFile(z,'w') as f:
        f.writestr('LYRICFORGE-main/server.py','old');f.writestr('verification/python-tests.log','evidence')
    with pytest.raises(ValueError):archive_files(z)
    assert archive_files(z,legacy_evidence=True)=={'server.py':b'old'}
    with zipfile.ZipFile(z) as f:assert f.read('verification/python-tests.log')==b'evidence'

@pytest.mark.parametrize('name',['../bad','LYRICFORGE-main/../../bad','C:/bad','verification/unknown','LYRICFORGE-main\\bad'])
def test_archive_reject_unsafe_even_in_legacy_mode(tmp_path,name):
    z=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(z,'w') as f:f.writestr(name,'bad')
    with pytest.raises(ValueError):archive_files(z,legacy_evidence=True)
