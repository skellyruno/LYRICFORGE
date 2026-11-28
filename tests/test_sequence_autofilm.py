import copy
from pathlib import Path
import studio_sequence as seq
import studio_sequence_autofilm as film


def setup(tmp_path):
    assets={}
    for key in ('source','rack','doubler','filter','tape','delay'):
        p=tmp_path/(key+'.mp4');p.write_bytes(key.encode())
        assets[key]={'path':p,'duration':40.,'has_video':True,'has_audio':key=='source','keywords':[key]}
    return assets


def test_montage_is_atomic_diverse_and_clock_safe(tmp_path,monkeypatch):
    a=setup(tmp_path);s=seq.initial(a);before=copy.deepcopy(s)
    monkeypatch.setattr(film.creative,'visual',lambda a:{'quality':.8,'motion':.045,'sample_quality':[.8]*24,'sample_motion':[.045]*24})
    r=film.propose(s,a,[],'cinematic visual-only');action=r['suggestions'][0]['action']
    x=seq.apply(s,action,a);assert x['base']==s['base'] and s==before
    assert len(x['layers'])==5 and len({y['asset'] for y in x['layers']})==5
    spans=sorted((y['at'],y['at']+y['length']) for y in x['layers'])
    assert all(b<=c for (a,b),(c,d) in zip(spans,spans[1:]))
    store=seq.Store(tmp_path,a);store.get();store.mutate(0,action)
    assert not store.mutate(1,{'op':'undo'})['state']['layers']


def test_unrelated_transcript_or_bad_footage_is_rejected(tmp_path,monkeypatch):
    a=setup(tmp_path);s=seq.initial(a)
    monkeypatch.setattr(film.creative,'visual',lambda a:{'quality':.8,'motion':.045,'sample_quality':[.8]*24,'sample_motion':[.045]*24})
    assert not film.propose(s,a,[{'text':'unrelated','start':4.,'end':5.}],'cinematic')['suggestions']
    monkeypatch.setattr(film.creative,'visual',lambda a:{'quality':.01,'motion':0.,'sample_quality':[.01]*24,'sample_motion':[0.]*24})
    assert not film.propose(s,a,[],'cinematic visual-only')['suggestions']


def test_audio_without_transcript_and_finished_footage_guard(tmp_path,monkeypatch):
    a=setup(tmp_path);s=seq.initial(a)
    monkeypatch.setattr(film.creative,'visual',lambda a:{'quality':.8,'motion':.045,'sample_quality':[.8]*24,'sample_motion':[.045]*24})
    assert not film.propose(s,a,[],'cinematic')['suggestions']
    a['rack']['keywords'].append('finished');a['tape']['keywords'].append('baked-titles')
    r=film.propose(s,a,[],'cinematic visual-only')
    assert not ({'rack','tape'} & {x['asset'] for x in r['suggestions'][0]['evidence']})


def test_cue_order_and_common_tags(tmp_path,monkeypatch):
    a=setup(tmp_path);s=seq.initial(a)
    for key in a:a[key]['keywords'].append('plugin')
    monkeypatch.setattr(film.creative,'visual',lambda a:{'quality':.8,'motion':.045,'sample_quality':[.8]*24,'sample_motion':[.045]*24})
    words=[{'text':w,'start':t,'end':t+.4} for w,t in [('tape',2.),('doubler',10.),('filter',22.),('plugin',30.)]]
    result=film.propose(s,a,words,'cinematic')['suggestions'][0]['evidence']
    assert [x['asset'] for x in result]==['tape','doubler','filter']
    for row,t in zip(result,[2.,10.,22.]):assert row['at_seconds']<=t<=row['at_seconds']+3


def test_scheduler_preserves_long_demo_and_existing_picture():
    import studio_sequence_film_schedule as fs
    state={'base':{'pieces':[{'asset':'source','audio':'source','start':0,'audio_start':0,'length':300},{'asset':'cutaway','audio':'source','start':30,'audio_start':300,'length':90}]},'layers':[],'transitions':[{'at':300,'half':6}]}
    spans=fs.protected_intervals(state,[{'text':'before','start':2.,'end':2.4},{'text':'after','start':8.,'end':8.4}])
    assert (300,390) in spans and (294,306) in spans
    assert any(a<=60 and b>=372 for a,b in spans)


def test_silent_source_still_supports_montage(tmp_path,monkeypatch):
    a=setup(tmp_path);a['source']['has_audio']=False;s=seq.initial(a)
    monkeypatch.setattr(film.creative,'visual',lambda a:{'quality':.8,'motion':.045,'sample_quality':[.8]*24,'sample_motion':[.045]*24})
    assert film.propose(s,a,[],'cinematic')['suggestions']
