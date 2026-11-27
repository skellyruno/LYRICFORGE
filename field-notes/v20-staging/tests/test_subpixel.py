import numpy as np
from PIL import Image,ImageDraw
from studio_subpixel import composite,raster_size
from studio_layers import Composition
from studio_director import font

def centroid(im):
    a=np.asarray(im)[...,3].astype(float);return float((a*np.arange(a.shape[1])).sum()/a.sum())

def test_fractional_centroid_and_no_pixel_holds():
    t=Image.new('RGBA',(160,80));ImageDraw.Draw(t).rectangle((30,15,120,65),fill='white')
    xs=[]
    for i in range(21):
        dst=Image.new('RGBA',(200,100));composite(dst,t,15+i*.13,10,80,40);xs.append(centroid(dst))
    delta=np.diff(xs);assert delta.min()>.04 and delta.max()<.22

def test_text_raster_stays_invariant_during_zoom(monkeypatch):
    g={'title':'Test','source':'Test','layers':[{'id':'t','type':'text','text':'Stable typography, stable wrapping','width':.8,'height':.2,'size':.075,'track':[[0,.5,.5,.92,1],[1,.52,.5,1.12,1]]}]}
    c=Composition(g,640,360,2,font);seen=[];orig=c._tile
    def tile(l,w,h,t):seen.append((w,h));return orig(l,w,h,t)
    monkeypatch.setattr(c,'_tile',tile)
    for i in range(20):c.render(i/10)
    assert len(seen)==1

def test_clipping_and_alpha():
    dst=Image.new('RGBA',(40,40),(0,0,0,255));t=Image.new('RGBA',(30,30),(255,255,255,128));composite(dst,t,-4.2,8.4,20,20,.5)
    assert 55<=dst.getpixel((5,15))[0]<=70
    composite(dst,t,100,100,20,20)
