import numpy as np
from studio_ray_scene import objects,nearest,trace,render,visibility
from studio_fluid import Fluid

def test_ground_secondary_rays_see_objects():
    d=np.array([[0,1.,0]]);o=np.array([[.82,-.729,.28]])
    _,ids=nearest(o,d,objects(0));assert ids[0]==1
    assert not np.allclose(trace(o,d,objects(0),1),trace(o,d,[],1))

def test_ray_scene_deterministic_and_motion():
    a=np.array(render(320,180,0));b=np.array(render(320,180,2));assert a.shape==(180,320,4) and np.array_equal(a,np.array(render(320,180,0))) and not np.array_equal(a,b)

def test_obstacle_excludes_dye_and_velocity():
    f=Fluid(2,64,obstacle=True);a=f.render(240,160,1.2);assert a.size==(240,160);assert np.all(f.dye[f.solid]==0) and np.all(f.u[f.solid]==0) and np.all(f.v[f.solid]==0);assert f.dye.sum()>0
