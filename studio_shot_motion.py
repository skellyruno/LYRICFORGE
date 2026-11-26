"""Bounded editorial camera moves. Never simulate plugin control operation."""
import math
import re

def camera_filter(width,height,fps,frames,camera,focus=(.5,.5)):
    if (type(width) is not int or type(height) is not int or width%2 or height%2
            or not 2<=width<=3840 or not 2<=height<=3840 or fps not in (24,30,60)
            or type(frames) is not int or not 1<=frames<=30*fps or camera not in ('push','pull')):
        raise ValueError('Invalid editorial camera geometry or clock')
    if not isinstance(focus,(list,tuple)) or len(focus)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in focus):
        focus=(.5,.5)
    fx,fy=(max(0.,min(1.,float(v))) for v in focus)
    u=f'min(1,on/{max(1,frames-1)})'
    ease=f'({u})*({u})*(3-2*({u}))'
    z=f'1+0.10*{ease}' if camera=='push' else f'1.10-0.10*{ease}'
    factor=min(1.5,3840/max(width,height))
    sw=max(width,round(width*factor/2)*2);sh=max(height,round(height*factor/2)*2)
    return (f"scale={sw}:{sh},zoompan=z='{z}':x='(iw-iw/zoom)*{fx:.6f}':"
            f"y='(ih-ih/zoom)*{fy:.6f}':d={frames}:s={width}x{height}:fps={fps},setsar=1")

def prefer_diagram(text,hint,kind):
    if not kind:return False
    source=(text+' '+hint).casefold()
    if re.search(r'\b(click|drag|turn|toggle|adjust|set|move|listen|bypass|before|after|watch|demo|demonstrat\w*)\b',source):return False
    return bool(re.search(r'\b(conceptually|illustration|conceptual|simulation|mechanism|transfer|response|spectrum|frequency-selective|works by|how it works|why it works|signal flow)\b',source))

def shot_intent(text,hint='',diagram=None):
    """Choose a shot role from narrative intent, not keywords alone.
    A requested listening or control demonstration never becomes a fabricated UI.
    """
    source=(str(text)+' '+str(hint)).casefold()
    if re.search(r'\b(listen|compare|before and after|audio proof|a/b)\b',source):return 'audio_comparison'
    if re.search(r'\b(click|drag|turn|toggle|adjust|set|move|watch|demonstrat\w*|recorded control)\b',source):return 'real_control'
    if prefer_diagram(text,hint,diagram):return 'mechanism'
    if re.search(r'\b(result|outcome|benefit|creates room|difference|conclusion)\b',source):return 'result'
    return 'overview'


def transition_mode(previous,current,style):
    if style!='auto':return {'dissolve':'fade','slide':'slideleft','wipe':'wipeleft'}.get(style,'fade')
    if current['type']==previous['type']=='broll' and float(current.get('features',{}).get('motion',0) or 0)>.12:return 'slideleft'
    if current['type']=='diagram' and previous['type'] in ('broll','big_text','document'):return 'wipeleft'
    return 'fade'
