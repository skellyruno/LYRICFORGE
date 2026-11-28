"""GGX microfacet housing shading with two light sources; UI pixels ungraded."""
import numpy as np

def unit(v):
    a=np.asarray(v,dtype=float);return a/max(1e-9,np.linalg.norm(a))

def shade(normal,view,phase,roughness=.34,metallic=.72):
    n=unit(normal);v=unit(view);nv=float(n@v)
    if nv<0:n=-n;nv=-nv
    nv=max(.001,nv);roughness=float(np.clip(roughness,.12,1));a2=roughness**4
    base=np.array([.17,.20,.23]);f0=.04*(1-metallic)+base*metallic;result=base*.17
    for l,c in [(unit([-.72+.35*phase,-.76,-.6]),np.array([1.,.78,.52])*2.8),(unit([.86,-.30,-.45]),np.array([.44,.75,1.])*2.)]:
        nl=max(0.,float(n@l));h=unit(l+v);nh=max(0.,float(n@h));vh=max(0.,float(v@h));F=f0+(1-f0)*(1-vh)**5
        D=a2/(np.pi*(nh*nh*(a2-1)+1)**2);k=(roughness+1)**2/8;G=(nv/(nv*(1-k)+k))*(nl/max(.001,nl*(1-k)+k))
        result+=((1-F)*(1-metallic)*base/np.pi+D*G*F/max(.001,4*nv*nl))*c*nl
    mapped=result/(1+result);return tuple(np.uint8(np.clip(mapped**(1/2.2)*255,0,255)).tolist())
