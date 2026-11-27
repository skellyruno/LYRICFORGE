import numpy as np
from PIL import ImageFont
from studio_color_light import rgb_ramp,linear_to_srgb,wave_bands,channel_mixer
from studio_instrument_score import arrange_chromatic


def test_linear_light_and_channel_order():
    assert np.allclose(linear_to_srgb([0,1]),[0,1])
    assert np.isclose(linear_to_srgb(.5),.735356983,atol=1e-7)
    assert np.all(rgb_ramp(0)==0) and np.all(rgb_ramp(1)==1)
    assert np.all(rgb_ramp(.2)[1:]==0)
    assert (np.diff([rgb_ramp(t) for t in np.linspace(0,1,100)],axis=0)>=0).all()


def test_real_diagram_renders():
    from studio_director import font as f
    for fn in (wave_bands,channel_mixer):
        a=fn(640,260,0,f);b=fn(640,260,1,f)
        assert a.size==b.size==(640,260) and a.tobytes()!=b.tobytes()
        assert np.any(np.asarray(b)[...,3]>0)


def test_chromatic_score_complete_note_pairs():
    a=arrange_chromatic(40.9166667,88,None,24000);active=set()
    for t,on,ch,pitch,v in a:
        assert 0<=t<=982000 and 0<=pitch<=127
        k=(ch,pitch)
        if on:assert k not in active;active.add(k)
        else:assert k in active;active.remove(k)
    assert not active and len(a)>150
