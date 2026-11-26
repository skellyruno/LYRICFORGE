import math
from pathlib import Path
import pytest
import studio_live_diagrams as live
import studio_director as director


def test_level_model_moves_and_ratio_one_is_transparent():
    unity=live.simulate_compression(4,ratio=1)
    assert all(a==b and g==0 for a,b,g in unity)
    active=live.simulate_compression(4)
    assert max(r[2] for r in active)>6
    assert max(r[2] for r in active)<18
    assert all(math.isclose(a-b,g,abs_tol=1e-8) and g>=0 for a,b,g in active)
    assert min(r[2] for r in active)<.1


def test_compressor_control_direction_and_release():
    mild=live.simulate_compression(3,threshold=-8,ratio=2)
    strong=live.simulate_compression(3,threshold=-24,ratio=8)
    assert max(r[2] for r in strong)>max(r[2] for r in mild)+5
    fast=live.simulate_compression(3,attack_ms=1,release_ms=20)
    slow=live.simulate_compression(3,attack_ms=500,release_ms=2000)
    assert fast[350][2]>slow[350][2]
    assert fast[1000][2]<slow[1000][2]


def test_pitch_model_zero_and_smooth():
    fast=live.simulate_pitch(4,retune_ms=0)
    slow=live.simulate_pitch(4,retune_ms=70)
    assert all(math.isclose(b,c,abs_tol=1e-8) for a,b,c in fast)
    assert any(abs(b-c)>5 for a,b,c in slow)
    assert all(math.isfinite(x) for row in slow for x in row)


def test_live_frame_changes_and_cancellation(tmp_path):
    rows=live.simulate_compression(3)
    a=live.frame('Compression',rows,250)
    b=live.frame('Compression',rows,1500)
    assert a.tobytes()!=b.tobytes()
    assert a.size==(960,540)
    def cancel():raise RuntimeError('cancelled')
    with pytest.raises(RuntimeError,match='cancelled'):
        live.write_frames('Compression',2,tmp_path,30,cancel)
    assert not list(tmp_path.iterdir())


def test_technical_topic_cuts_do_not_mix_fast_slow():
    lines=[{'text':'Slow pitch retune retains movement','start':0,'end':5}, {'text':'Zero milliseconds retune removes smoothing','start':5,'end':10}, {'text':'Choose key and scale with piano','start':10,'end':15}]
    p=director.make_plan(lines,15,[],'plugin',diagrams=True)
    assert [(s['text'],s.get('retune_demo_ms')) for s in p['scenes']]==[('Pitch processing',70.),('Pitch processing',0.),('Note selection',None)]
    assert p['review']['errors']==0


def test_control_limits_and_default():
    from server import CompressorDemo
    from pydantic import ValidationError
    assert CompressorDemo().ratio==4
    with pytest.raises(ValidationError):CompressorDemo(ratio=0)


def test_unrelated_screenshot_does_not_hide_technical_diagram():
    assets=[{'id':'a'*32+'.png','name':'logo image','kind':'image','description':'brand artwork'}]
    p=director.make_plan([{'text':'Compression threshold and ratio','start':0,'end':4}],4,assets,'plugin',diagrams=True)
    assert p['scenes'][0]['type']=='diagram'
    assets[0]['description']='compression threshold and ratio'
    p=director.make_plan([{'text':'Compression threshold and ratio','start':0,'end':4}],4,assets,'plugin',diagrams=True)
    assert p['scenes'][0]['type']=='ui_demo'
