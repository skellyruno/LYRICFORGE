"""Reference-inspired original editorial layouts and explicit educational diagrams."""
from __future__ import annotations
import math
from urllib.parse import urlsplit
from PIL import Image,ImageDraw,ImageFont


def wrap(draw,text,font,width):
    rows=[];line=''
    for word in str(text).split():
        # Break untrusted long tokens without losing their content.
        parts=[]
        while draw.textlength(word,font=font)>width and len(word)>1:
            n=max(1,int(len(word)*width/draw.textlength(word,font=font)))
            parts.append(word[:n]);word=word[n:]
        parts.append(word)
        for part in parts:
            candidate=(line+' '+part).strip()
            if line and draw.textlength(candidate,font=font)>width:rows.append(line);line=part
            else:line=candidate
    if line:rows.append(line)
    return rows


def evidence_card(scene,w,h,font):
    from studio_theme import palette,label as editorial_label
    colors=palette(scene.get('visual_theme','legacy')) or palette('clean')
    im=Image.new('RGB',(w,h),colors['paper_bg']);d=ImageDraw.Draw(im)
    x,y=round(w*.10),round(h*.17);right,bottom=round(w*.90),round(h*.73)
    d.rounded_rectangle((x+6,y+8,right+6,bottom+8),radius=max(6,h//65),fill=colors['shadow'])
    d.rounded_rectangle((x,y,right,bottom),radius=max(6,h//65),fill=colors['panel'])
    margin=round(w*.045);left=x+margin
    d.rectangle((x,y,x+max(3,w//300),bottom),fill=colors['accent'])
    limit=right-left-margin
    heading=editorial_label(scene,'RESEARCH / AUTHOR-SUPPLIED CLAIM')
    label_size=max(12,min(h//39,w//32));label=font(label_size,True)
    while label_size>10 and d.textlength(heading,font=label)>limit:
        label_size-=1;label=font(label_size,True)
    d.text((left,y+round(h*.045)),heading,font=label,fill=colors['paper_muted'])
    body=str(scene.get('evidence_text') or scene.get('text') or '')
    size=max(16,min(round(h*.067),round(w*.064)))
    while True:
        f=font(size,True);rows=wrap(d,body,f,limit)
        line_height=max(1,round(size*1.2))
        if (len(rows)*line_height<=h*.32 and all(d.textlength(word,font=f)<=limit for word in body.split())) or size<=12:break
        size-=2
    if len(rows)*line_height>h*.32:
        count=max(1,int(h*.32/line_height));rows=rows[:count]
        rows[-1]=rows[-1][:-1]+'…'
    top=y+round(h*.13)
    # The yellow accent is editorial emphasis, not a marked quotation.
    if rows:
        first=rows[0].split()[:3];highlight=' '.join(first)
        d.rectangle((left-3,top-2,left+round(d.textlength(highlight,font=f))+3,top+line_height),fill=colors['highlight'])
    for i,row in enumerate(rows):d.text((left,top+i*line_height),row,font=f,fill=colors['paper_ink'])
    hosts=', '.join(dict.fromkeys(urlsplit(u).hostname or '' for u in scene.get('claim_sources',[])))
    src='Source supplied: '+hosts
    source_size=label_size;source_font=label
    while source_size>10 and d.textlength(src,font=source_font)>limit:
        source_size-=1;source_font=font(source_size,True)
    while len(src)>18 and d.textlength(src,font=source_font)>limit:src=src[:-5]+'…'
    d.text((left,bottom-round(h*.065)),src,font=source_font,fill=colors['paper_muted'])
    return im


def technical_frame(kind,t,theme='legacy'):
    """Educational model only; do not label mathematical graphics as measured plugin response."""
    from studio_theme import palette
    colors=palette(theme) or {'background':'#101216','accent':'#f5b942','ink':'#e9eae8','muted':'#b1b6b9'}
    im=Image.new('RGB',(960,540),colors['background']);d=ImageDraw.Draw(im)
    def f(size):
        try:return ImageFont.truetype('DejaVuSans.ttf',size)
        except OSError:return ImageFont.load_default()
    def txt(x,y,s,size=20,color=None,anchor='la'):d.text((x,y),s,font=f(size),fill=color or colors['ink'],anchor=anchor)
    txt(48,34,kind.upper(),31,colors['accent']);txt(912,46,'ILLUSTRATIVE MODEL',13,colors['muted'],'ra')
    if kind=='Spectral ducking':
        x0,y0,x1,y1=72,115,888,380
        for k in range(5):
            y=y0+(y1-y0)*k/4;d.line((x0,y,x1,y),fill='#343b40');txt(x0-9,y,str(-6*k),12,colors['muted'],'rm')
        center=.5+.22*math.sin(t*.8);depth=4+14*(.5+.5*math.sin(t*1.1))
        curve=[]
        for i in range(361):
            x=i/360;cut=depth*math.exp(-((x-center)/.13)**2)
            curve.append((x0+x*(x1-x0),y0+cut/24*(y1-y0)))
        d.polygon([(x0,y0),*curve,(x1,y0)],fill='#393325')
        d.line(curve,fill=colors['accent'],width=4)
        d.line((x0,y0,x1,y0),fill='#a9b7bd',width=2)
        for hz in (20,100,1000,10000,20000):
            x=x0+math.log10(hz/20)/3*(x1-x0);txt(x,y1+12,f'{hz/1000:g}k' if hz>=1000 else str(hz),13,colors['muted'],'ma')
        txt(480,450,'Only overlapping frequencies are reduced.',24,colors['accent'],'mm')
    else:
        width=.15+.75*(.5+.5*math.sin(t*.8));cx=480
        for i in range(7):
            y=125+i*36;span=width*(1-i/7)*360
            d.line((cx-span,y,cx+span,y),fill=colors['accent'],width=6)
            d.ellipse((cx-4,y-4,cx+4,y+4),fill=colors['ink'])
        d.line((cx,106,cx,376),fill='#8f9ba1',width=2)
        txt(70,415,'LEFT',14,colors['muted']);txt(890,415,'RIGHT',14,colors['muted'],'ra')
        txt(480,450,'Illustrated frequency-dependent stereo width',22,colors['accent'],'mm')
    return im
