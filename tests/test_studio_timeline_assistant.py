import json
from pathlib import Path
import pytest
import studio_timeline as t
import studio_timeline_assistant as a
import studio_timeline_api as api

ASSETS={'source':{'duration':12.,'has_audio':True},'city':{'duration':5.,'has_audio':True,'keywords':['city']}}
WORDS=[{'text':'city','start':2.,'end':2.5},{'text':'next','start':5.,'end':5.5}]

def test_original_and_aliases():
    assert t.plan(ASSETS,'keep original')['frames']==360
    assert t.plan(ASSETS,'trim out 1 to 2; swap footage from 2 to 3 with city keep narration')['frames']==330
    with pytest.raises(ValueError):t.plan(ASSETS,'keep original; cut 1 to 2')

def test_creative_filters_and_validates():
    for goal in ('tighter pacing','more visual variety','balanced'):
        r=a.creative(ASSETS,WORDS,goal,'keep original')
        assert r['suggestions']
        for row in r['suggestions']:
            if row.get('instruction'):assert t.plan(ASSETS,row['instruction'])['duration']==row['duration']
    assert all(s['kind']=='pacing' for s in a.creative(ASSETS,WORDS,'tighter pacing')['suggestions'])
    assert all(s['kind']!='pacing' for s in a.creative(ASSETS,WORDS,'more visual variety')['suggestions'])
    r=a.creative(ASSETS,WORDS,'balanced','cut 10 to 11')
    assert all(s['instruction'].startswith('cut 10 to 11;') for s in r['suggestions'] if s.get('instruction'))

@pytest.mark.parametrize('answer,valid',[('cut 1 to 2',True),('insert missing at 1 for 2',False),('cut 0 to 12',False),('run shell command',False),('',False)])
def test_local_model_proposal_is_validated(answer,valid):
    def fake(path,payload=None,timeout=4):
        if path=='/api/tags':return {'models':[{'name':'test:1b'}]}
        assert path=='/api/chat' and payload['stream'] is False
        assert 'source_duration' in payload['messages'][1]['content']
        return {'message':{'content':json.dumps({'commands':answer})}}
    if valid:assert a.translate(ASSETS,'tighten','test:1b',WORDS,fake)==answer
    else:
        with pytest.raises(ValueError):a.translate(ASSETS,'tighten','test:1b',WORDS,fake)
    with pytest.raises(ValueError):a.translate(ASSETS,'tighten','unknown',WORDS,fake)

def test_setup_offline(tmp_path):
    def offline(*args,**kwargs):raise ValueError('offline')
    s=a.setup_status(tmp_path,offline)
    assert not s['connected'] and s['models']==[] and s['project_disk_free_bytes']>0
    assert 'ollama pull' in s['example_command']

def test_copy_is_independent(tmp_path):
    root=tmp_path/'original';root.mkdir();output=root/'edited.mp4';output.write_bytes(b'video')
    p=t.plan(ASSETS,'replace 2 to 4 with city')
    pid=api.create_editable_copy(root,{'title':'Test'},output,p,t.remap_words(WORDS,p))
    info=json.loads((tmp_path/pid/'project.json').read_text())
    assert info['status']=='ready' and info['duration']==12 and len(info['original_words'])==2
    assert (tmp_path/pid/'source.mp4').read_bytes()==b'video'
    output.write_bytes(b'new');assert (tmp_path/pid/'source.mp4').read_bytes()==b'video'
    with pytest.raises(ValueError):api.create_editable_copy(root,{},output,t.plan(ASSETS,'insert city at 1 for 2'),[])

def test_recommendations_protect_user_edits_and_align_shot_boundary():
    r=t.plan(ASSETS,'insert city at 3 for 2 muted')
    assert not any(x['kind']=='pacing' for x in t.suggestions(r,WORDS,{}))
    orig=t.plan(ASSETS,'keep original')
    hints=t.suggestions(orig,WORDS,{'city':ASSETS['city']},[1.9])
    cutaway=next(x for x in hints if x['kind']=='relevant cutaway')
    assert cutaway['start']==1.9 and 'scene boundary' in cutaway['reason']
    p=t.plan(ASSETS,'replace 1 to 5 with city keep audio')
    assert not any(x['kind']=='relevant cutaway' for x in t.suggestions(p,WORDS,{'city':ASSETS['city']}))

def test_derived_audio_clock_graph(tmp_path):
    import studio_edit as edit
    _,graph,duration=edit.build_render(tmp_path/'source.mp4',1280,720,30,tmp_path/'out.mp4',[],duration=4.2,loudness=-14,lock_audio_clock=True)
    assert duration==4.2 and 'apad=whole_len=201600,atrim=end_sample=201600,asetpts=N/SR/TB[clocked]' in graph
    _,legacy,_=edit.build_render(tmp_path/'source.mp4',1280,720,30,tmp_path/'out.mp4',[],duration=4.2,loudness=-14)
    assert '[clocked]' not in legacy
