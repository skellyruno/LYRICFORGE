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
    r=film.propose(s,a,[],'cinematic');action=r['suggestions'][0]['action']
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
    assert not film.propose(s,a,[],'cinematic')['suggestions']
