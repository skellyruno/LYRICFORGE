"""Stable raster sizes and premultiplied, fractional-pixel layer placement.
All coordinates are continuous; only the destination tile bounds are integers.
"""
import math
from PIL import Image

VECTOR={'text','paper','line','spectrum','wave','samples','particles','rings','surface','decay_trace','time_orbit','time_samples','time_trajectory','light_waves','light_channels','frequency_pair'}
def raster_size(w,h,kind):
    factor=2 if kind in VECTOR else 1
    # Bound memory independently of the requested animated zoom.
    factor=min(factor,2880/max(1,w),2160/max(1,h))
    return max(2,round(w*factor)),max(2,round(h*factor))

def project(canvas,tile,x,y,w,h,opacity=1.):
    if opacity<=0 or w<=0 or h<=0:return
    # An extra two pixels allow the bicubic kernel to resolve the edge.
    left=max(0,math.floor(x)-2);top=max(0,math.floor(y)-2)
    right=min(canvas.width,math.ceil(x+w)+2);bottom=min(canvas.height,math.ceil(y+h)+2)
    if right<=left or bottom<=top:return
    # Work in premultiplied RGBA to prevent dark fringes on transparent edges.
    # Supersample the output rather than changing the input raster size each frame.
    # This prevents resampling-kernel changes at scale thresholds.
    prem=tile.convert('RGBa');sx,sy=prem.width/w,prem.height/h
    dw,dh=right-left,bottom-top
    factor=2 if dw*dh<=2_000_000 else 1
    mapped=prem.transform((dw*factor,dh*factor),Image.Transform.AFFINE,(sx/factor,0,(left-x)*sx,0,sy/factor,(top-y)*sy),resample=Image.Resampling.BICUBIC)
    if factor>1:mapped=mapped.resize((dw,dh),Image.Resampling.LANCZOS)
    mapped=mapped.convert('RGBA')
    if opacity<.999:mapped.putalpha(mapped.getchannel('A').point(lambda k:round(k*max(0,min(1,opacity)))))
    return mapped,(left,top)

def composite(canvas,tile,x,y,w,h,opacity=1.):
    result=project(canvas,tile,x,y,w,h,opacity)
    if result is not None:canvas.alpha_composite(*result)
