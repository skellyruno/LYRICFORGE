import json,pytest
import studio_sequence as seq
import studio_sequence_model as model
from test_studio_sequence import assets,visual

@pytest.fixture
def no_decode(monkeypatch):
    monkeypatch.setattr(model.creative,'visual',lambda a:{'quality':.8,'motion':.05})
    monkeypatch.setattr(model.creative,'music',lambda a:{'bpm':90,'confidence':.9,'beats':[0,1]})

def mock(actions,reason='Make a visual cutaway'):
    def get(path,payload=None,timeout=4):
        if path=='/api/tags':return {'models':[{'name':'test:3b'}]}
        context=json.loads(payload['messages'][1]['content']);assert 'path' not in json.dumps(context);assert context['fps']==30
        return {'message':{'content':json.dumps({'reason':reason,'actions':actions})}}
    return get

def layer():return {'op':'put','layer':{'id':'ai-cutaway','kind':'visual','asset':'city','at':30,'length':45,'offset':0,'fade':4}}

def test_model_proposal_and_atomic_undo(tmp_path,assets,no_decode):
    store=seq.Store(tmp_path,assets);state=store.snapshot(0);before=store.path.read_bytes()
    result=model.propose(state,assets,[],'give it an elegant visual rhythm','test:3b',mock([layer(),{'op':'put','layer':{'id':'ai-score','kind':'music','asset':'music','at':0,'length':120}}]))
    assert before==store.path.read_bytes();assert len(result['preview']['layers'])==2
    assert len(store.mutate(0,result['action'])['state']['layers'])==2
    assert store.mutate(1,{'op':'undo'})['state']['layers']==[]

def test_invalid_or_overlapping_model_actions(assets,no_decode):
    state=seq.initial(assets)
    for actions in [[{'op':'reset'}],[{'op':'ripple','instruction':'cut 0 to 1'}],[{'op':'put','layer':{**layer()['layer'],'asset':'/etc/passwd'}}],[layer(),layer()]]:
        with pytest.raises(ValueError):model.propose(state,assets,[],'make this elegant','test:3b',mock(actions))
    with pytest.raises(ValueError):model.propose(state,assets,[],'make this elegant','unknown',mock([layer()]))
    state=seq.apply(state,visual(30),assets)
    with pytest.raises(ValueError,match='cover an existing'):model.propose(state,assets,[],'more cinematic','test:3b',mock([layer()]))

def test_invalid_batch_leaves_store_unchanged(tmp_path,assets):
    s=seq.Store(tmp_path,assets);s.get();before=s.path.read_bytes()
    with pytest.raises(ValueError):s.mutate(0,{'op':'batch','actions':[layer(),{'op':'transition','at':1,'kind':'dip','half':1}]})
    assert before==s.path.read_bytes()


def test_visual_only_schema_retry_preserves_clock(assets,no_decode):
    state=seq.initial(assets);calls=[]
    def get(path,payload=None,timeout=4):
        if path=='/api/tags':return {'models':[{'name':'test:3b'}]}
        calls.append(len(payload['messages']))
        item=payload['format']['properties']['actions']['items']
        assert item['properties']['op']['enum']==['put']
        assert item['properties']['layer']['properties']['kind']['enum']==['visual']
        assert 'asset' in item['properties']['layer']['required']
        if len(calls)==1:actions=[{'op':'transition','at':30,'kind':'dip','half':5}]
        else:
            assert 'Visual-only request' in payload['messages'][-1]['content']
            actions=[layer()]
        return {'message':{'content':json.dumps({'reason':'review','actions':actions})}}
    r=model.propose(state,assets,[],'Insert a visual layer and keep the original timing','test:3b',get)
    assert calls==[2,3] and r['preview']['before_frames']==r['preview']['after_frames']
    assert len(r['preview']['layers'])==1 and state['layers']==[]


def test_timing_lock_rejects_ripple(assets,no_decode):
    state=seq.initial(assets)
    with pytest.raises(ValueError,match='after retry'):
        model.propose(state,assets,[],'Insert footage but keep original duration','test:3b',mock([{'op':'ripple','instruction':'cut 0 to 1'}]))


def test_missing_and_malformed_model_fields_rejected(assets,no_decode):
    state=seq.initial(assets)
    for bad in [{'id':'ai-bad','kind':'visual','asset':'city','length':45}, {**layer()['layer'],'at':'30'}]:
        with pytest.raises(ValueError,match='Unexpected model layer field'):
            model.propose(state,assets,[],'make cinematic','test:3b',mock([{'op':'put','layer':bad}]))
