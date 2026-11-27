import numpy as np
import pytest
from PIL import ImageFont
from studio_signal_story import decay_example, measure_decay, validate_trace, draw_trace, pause_gain


def test_measured_decay():
    x,sr=decay_example();p=np.array(measure_decay(x,sr))
    assert len(p)==40 and p[0,1]==0
    assert np.allclose(np.diff(p[:30,1]),-3,atol=.01)


def test_trace_validation_and_render():
    from studio_director import font as f
    p=measure_decay(*decay_example())
    a=draw_trace(640,260,p,.1,f,'#efce77');b=draw_trace(640,260,p,1,f,'#efce77')
    assert a.size==b.size and a.tobytes()!=b.tobytes()
    with pytest.raises(ValueError):validate_trace([[1,0],[0,-5]])


def test_rest_exact_and_block_independent():
    t=np.arange(100000)/24000;w=[(1,3,.25)]
    g=pause_gain(t,w)
    assert np.all(g[(t>=1)&(t<=3)]==0) and g[0]==1
    assert np.array_equal(g,np.concatenate([pause_gain(t[:11111],w),pause_gain(t[11111:],w)]))
    assert np.max(np.abs(np.diff(g)))<.001
    with pytest.raises(ValueError):pause_gain(t,[(3,1,.25)])


def test_score_rests_end_to_end(tmp_path,monkeypatch):
    import wave
    from studio_score import write_score
    monkeypatch.delenv('LYRICFORGE_SOUNDFONT',raising=False)
    p={'duration':3.,'preset':'doc','scenes':[],'score_rests':[[1,2,.2]]}
    out=write_score(p,tmp_path/'rest.wav',rate=24000)
    with wave.open(str(out),'rb') as f:x=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,2)
    assert len(x)==72000 and not np.any(x[24000:48000])
    assert np.any(x[:20000]) and np.any(x[50000:])


def test_silence_film_plan():
    from examples.silence_documentary import make_plan
    p,t,points=make_plan();assert sum(s['frames'] for s in p['scenes'])==p['frames']
    assert p['score_rests'][0][0]<t<t+2<p['score_rests'][0][1]
    assert p['scenes'][1]['graphic']['layers'][2]['points']==points


def test_bridge_never_overlaps_unmatched_text():
    from studio_layers import Composition
    from studio_director import font
    def spec(text):return {'title':text,'source':'Test','layers':[{'id':'title','type':'text','text':text,'track':[[0,.5,.5,1,1]]}]}
    a,b=(Composition(spec(t),640,360,3,font) for t in ('Old title','New title'))
    b._draw=lambda rows,source:[(l['text'],s[3]) for l,s,_ in rows if l['type']=='text' and s[3]>.002]
    for t in np.linspace(.001,.999,100):assert len(b.bridge(a,float(t),1))<=1
