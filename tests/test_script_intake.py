import json, io, wave
import numpy as np
import pytest
from types import SimpleNamespace as S
from fastapi.testclient import TestClient
import studio_creator as c
import server

def test_written_prose_preserves_words():
    text=('Frequency describes cycles per second. '*45)+'\n\nA new paragraph.'
    out=c.chapters_from_text(text)
    assert ' '.join(r['narration'] for r in out).split()==text.split()
    assert len(out)>2 and all(len(r['narration'])<=1200 for r in out)

def test_audio_only_pipeline_with_injected_recognizer(monkeypatch,tmp_path):
    # Test integration and timestamp propagation, not actual model accuracy.
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*a:fn(*a))
    class Model:
        def transcribe(self,*a,**kw):
            assert kw['word_timestamps'];return iter([S(words=[S(word='Frequency',start=.2,end=.65,probability=.9),S(word=' matters.',start=.7,end=1.1,probability=.8)])]),None
    monkeypatch.setattr(server,'load_model',lambda:Model())
    f=io.BytesIO()
    with wave.open(f,'wb') as w:
        w.setparams((1,2,24000,0,'NONE',''));w.writeframes(np.int16(np.sin(np.arange(48000)*.1)*1000).tobytes())
    client=TestClient(server.app);r=client.post('/api/creator/create',data={'payload':json.dumps({'product':'Audio only','voice':'recorded','auto_render':False,'story':'documentary'})},files={'recording':('voice.wav',f.getvalue(),'audio/wav')})
    assert r.status_code==200,r.text
    row=server.read_project(r.json()['project_id']);assert row['status']=='editor';assert row['creator_script'][0]['narration']=='Frequency matters.';assert row['lines'][0]['start']==.2
