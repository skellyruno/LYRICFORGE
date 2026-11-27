"""Bounded, subpixel-safe editorial camera paths over genuine recorded footage."""
import math


def camera_filter(w,h,frames,fps,move='push',focus=(.5,.5)):
    if not 2<=w<=3840 or not 2<=h<=3840 or w%2 or h%2 or not 1<=frames<=1800*60 or fps not in (24,30,60):raise ValueError('Invalid camera geometry')
    if move not in ('push','pull','detail'):raise ValueError('Invalid camera path')
    if not isinstance(focus,(tuple,list)) or len(focus)!=2 or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in focus):focus=(.5,.5)
    fx,fy=[max(0.,min(1.,float(x))) for x in focus]
    u=f'(on/{max(1,frames-1)})';ease=f'({u}*{u}*(3-2*{u}))'
    # Use floating-point zoom on an oversampled source; avoid integer-pixel jumps.
    factor=max(1.,min(2.,3840/max(w,h)));sw=round(w*factor/2)*2;sh=round(h*factor/2)*2
    zoom=f'1.02+0.065*{ease}' if move=='push' else f'1.085-0.065*{ease}' if move=='pull' else f'1.06+0.24*{ease}'
    return (f'scale={sw}:{sh}:flags=lanczos,zoompan=z=\'{zoom}\':x=\'(iw-iw/zoom)*{fx:.5f}\':y=\'(ih-ih/zoom)*{fy:.5f}\':d=1:s={w}x{h}:fps={fps},setsar=1')
