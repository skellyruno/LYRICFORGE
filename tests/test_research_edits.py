import pytest
from studio_research_edits import revise
from studio_research_compose import writing_schema,installed_models,local_write
import studio_research_compose as compose
from copy import deepcopy
U='https://en.wikipedia.org/w/index.php?oldid=123'
ROWS=[{'title':'Intro','narration':'The first scene.','source_url':U},{'title':'Next','narration':'The second scene.','source_url':U},{'title':'Sources and credits','narration':'Credits.','source_url':U}]
def test_direct_transaction_and_credits():
    previous=deepcopy(ROWS)
    result=revise(ROWS,'move scene 2 to 1; set scene 1 visual to A sound wave; format square; sound design off')
    assert result['chapters'][0]['title']=='Next'
    assert result['chapters'][0]['visual_hint']=='A sound wave'
    assert result['chapters'][-1]['title']=='Sources and credits'
    assert result['options']=={'format':'square','sound_design':False}
    assert ROWS==previous
def test_atomic_failure():
    previous=deepcopy(ROWS)
    with pytest.raises(ValueError):revise(ROWS,'remove scene 1; remove scene 1')
    assert ROWS==previous
    with pytest.raises(ValueError):revise(ROWS,'remove scene 3')
    with pytest.raises(ValueError):revise(ROWS,'format square; execute unknown command')
def test_model_discovery():
    assert installed_models(lambda p:{'models':[{'name':'qwen2.5:1.5b','size':123},{'name':'bad name'},{'name':'other'}]})==[{'name':'qwen2.5:1.5b','size_bytes':123},{'name':'other','size_bytes':None}]
def test_model_schema_retry(monkeypatch):
    evidence=[{'id':'A1','kind':'article','url':U,'extract':'Evidence'},{'id':'P1','kind':'bibliography'}]
    assert writing_schema(evidence)['properties']['chapters']['items']['properties']['evidence_id']['enum']==['A1']
    calls=[]
    def request(path,payload=None,timeout=5):
        import json
        calls.append(payload)
        value={} if len(calls)==1 else {'chapters':[{'title':'Intro','narration':'A scene.','visual_hint':'Wave','evidence_id':'A1'}],'delivery':'energetic','format':'square','sound_design':False,'title_motion':True}
        return {'message':{'content':json.dumps(value)}}
    monkeypatch.setattr(compose,'ollama_json',request)
    assert local_write('local','Pitch correction',30,evidence,'',[])['format']=='square'
    assert len(calls)==2 and isinstance(calls[0]['format'],dict)
def test_model_fails_closed(monkeypatch):
    monkeypatch.setattr(compose,'ollama_json',lambda *a,**k:{'message':{'content':'{}'}})
    with pytest.raises(ValueError,match='valid source-linked script'):
        local_write('local','Pitch correction',30,[{'kind':'article','id':'A1','url':U}], '',[])
