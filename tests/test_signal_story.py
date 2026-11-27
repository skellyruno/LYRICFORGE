import numpy as np
import pytest
from PIL import ImageFont
from studio_signal_story import decay_example, measure_decay, validate_trace, draw_trace, pause_gain


def test_measured_decay():
    x,sr=decay_example();p=np.array(measure_decay(x,sr))
    assert len(p)==40 and p[0,1]==0
    assert np.allclose(np.diff(p[:30,1]),-3,atol=.01)


def test_trace_validation_and_render():
    p=measure_decay(*decay_example());f=lambda n,b:ImageFont.truetype('DejaVuSans.ttf',n)
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


def test_score_rests_end_to_end(tmp_path):
    import wave
    from studio_cinematic import original_bed
    p={'duration':3.,'preset':'doc','scenes':[],'score_rests':[[1,2,.2]]}
    out=original_bed(p,tmp_path/'rest.wav',rate=24000)
    with wave.open(str(out),'rb') as f:x=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,2)
    assert len(x)==72000 and not np.any(x[24000:48000])
    assert np.any(x[:20000]) and np.any(x[50000:])
