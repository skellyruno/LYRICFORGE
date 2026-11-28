import numpy as np
import pytest
from studio_motion_envelope import energy

def test_frame_clock_and_bounded_attack_release():
    sr=44100; x=np.zeros((sr*3,2),np.float32);x[sr:sr*2,0]=.2;x[sr:sr*2,1]=-.2
    e=energy(x,sr,30);assert len(e)==90 and np.all(e[:30]==0)
    assert 0<e[30]<e[35]<=1 and e[59]>e[60]>e[70]>=0
    assert np.all((0<=e)&(e<=1))
    assert np.allclose(e,energy(x,sr,30))

def test_invalid_and_partial_clock():
    assert len(energy(np.zeros(48001),48000,30))==31
    with pytest.raises(ValueError):energy([float('nan')])
    with pytest.raises(ValueError):energy([1.],fps=0)
