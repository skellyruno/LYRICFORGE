import pytest
from studio_motion_handles import plan,sample

def test_exact_handles_and_protected_audio():
    spans=[(0,90),(90,180),(180,330),(330,390),(390,480)]
    h=plan(spans,{2},{1:'wipe',4:'depth'})
    assert [x.boundary for x in h]==[90,390]
    for x in h:
        rows=[sample(x,f) for f in range(x.boundary-x.half,x.boundary+x.half)]
        assert rows[0]==(x.boundary-x.half,x.boundary,0.)
        assert rows[-1]==(x.boundary-1,x.boundary+x.half-1,1.)
        assert all(a[0]<=b[0] and a[1]<=b[1] and a[2]<=b[2] for a,b in zip(rows,rows[1:]))

def test_short_shots_and_bad_inputs():
    h=plan([(0,9),(9,18),(18,27)])
    assert h[0].boundary+h[0].half<=h[1].boundary-h[1].half
    with pytest.raises(ValueError):plan([(0,10),(11,20)])
    with pytest.raises(ValueError):plan([(0,10),(10,20)],half=-1)
    with pytest.raises(ValueError):sample(h[0],0)
