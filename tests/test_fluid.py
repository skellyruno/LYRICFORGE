import numpy as np
from studio_fluid import Fluid, project, additive

def test_projection():
    rng=np.random.default_rng(3);u=rng.normal(size=(32,32));v=rng.normal(size=(32,32));a,b=project(u,v);c,d=project(a,b)
    assert np.max(abs(a-c))<1e-12 and np.max(abs(b-d))<1e-12

def test_fluid_seek_and_interpolation():
    f=Fluid(7,48);a=f.render(240,180,1);b=f.render(240,180,1+1/60);c=f.render(240,180,1)
    assert a.tobytes()==c.tobytes() and a.tobytes()!=b.tobytes()
    assert np.isfinite(f.u).all() and 0<=f.dye.min()<=f.dye.max()<=1
    assert len(f.frames)<35

def test_additive_mixing():
    a=np.asarray(additive(320,240,1));rgb=a[...,:3];opaque=a[...,3]==255
    for color in ([255,255,255],[255,255,0],[0,255,255],[255,0,255]):assert np.any(opaque & np.all(rgb==color,axis=-1))


def test_corrected_transport_and_optics():
    from studio_fluid import advect_corrected,optical_surface,light_study
    y,x=np.mgrid[:32,:32];a=np.exp(-((x-16)**2+(y-16)**2)/10);u=np.ones_like(a)*.7;v=np.ones_like(a)*.3
    b=advect_corrected(a,u,v,.7,x,y)
    assert b.min()>=a.min() and b.max()<=a.max()
    from studio_fluid import advect
    assert b.max()>=advect(a,u,v,.7,x,y).max()
    rgb,alpha=optical_surface(np.zeros((32,32,3)))
    assert np.isfinite(rgb).all() and not np.any(alpha)
    im=np.asarray(light_study(320,240,1));assert np.any(np.all(im==[255,255,255,255],axis=-1))
