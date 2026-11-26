import numpy as np
import studio_effect_visuals as fx
import studio_live_diagrams as live
import studio_director_intelligence as intel
import pytest


def test_equalizer_center_matches_gain():
    for g in (-9,0,6):assert np.isclose(fx.bell_response([1000],1000,g)[0],g,atol=.001)


def test_limiter_ceiling_and_recovery():
    x=fx.limiter_levels([-20,-1,-20,-20]);assert np.max(x[:,1])<=-6+1e-10;assert x[1,2]==5 and x[2,2]<5


def test_saturation_measured_harmonic_increase():
    assert fx.saturation(5)[-1]>fx.saturation(1)[-1]


def test_feedback_and_reverb_decay():
    t,a=fx.delay_taps();assert np.allclose(np.diff(t),.25);assert np.allclose(a[1:]/a[:-1],.58)
    x=fx.reverb_impulse();assert np.max(abs(x[-400:]))<np.max(abs(x[:400]))*.01

@pytest.mark.parametrize('kind',sorted(fx.KINDS))
def test_all_live_models_change_frames(kind,tmp_path):
    a=fx.render_frame(kind,.1);b=fx.render_frame(kind,.8);assert a.size==(960,540) and a.tobytes()!=b.tobytes()
    assert live.write_frames(kind,.15,tmp_path,24)==15;assert len(list(tmp_path.glob('*.jpg')))==3


def test_new_technical_topics():
    assert intel.diagram_kind('peak limiter ceiling')=='Limiter';assert intel.diagram_kind('saturation adds harmonics')=='Saturation'
