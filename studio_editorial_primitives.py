"""Reusable editorial primitives. Source evidence remains intact; marker choices
are editorial heuristics, never inferred factual significance or source claims."""
from __future__ import annotations
import math
import re
from PIL import Image, ImageDraw, ImageFont

ACCENT = '#f5d64e'
STOP = set('the a an and or but to for of in on at by with from as is are was were be been it its this that these those they them you your we our i he she not do does did can could would should have has had will so then than there here into about made make makes lets let shows show showing change changes changed using use used from into hundred thousand million billion nine eight seven six five four three two one'.split())


def emphasis(words):
    """At most two adjacent content words, not a karaoke effect."""
    tokens=[re.sub(r'[^\w-]','',str(w)).casefold() for w in words]
    eligible=[i for i,w in enumerate(tokens) if (len(w)>=4 or bool(re.search(r'\d',w))) and w not in STOP]
    if not eligible:return set()
    i=max(eligible,key=lambda j:(bool(re.search(r'\d',tokens[j])),len(tokens[j]),-j))
    return {i,i+1} if i+1 in eligible and len(tokens[i])+len(tokens[i+1])<=17 else {i}


def marker_font(size):
    for name in (r"C:\Windows\Fonts\arial.ttf", "Arial.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:return ImageFont.truetype(name,size)
        except OSError:pass
    return ImageFont.load_default(size=size)

def marker_layout(text,width,height,scale=1.):
    """Measure the exact text, preserving every word; fit up to two lines."""
    words=str(text).split(); hot=emphasis(words)
    if not words:return []
    size=max(12,round(min(height*.041,width*.055)*scale))
    limit=width*.84
    while True:
        f=marker_font(size); lines=[]; row=[]; used=0; gap=f.getlength(' ')+1
        for i,word in enumerate(words):
            span=f.getlength(word)+(max(2,size*.065)*2 if i in hot else 0)
            if row and used+gap+span>limit:lines.append(row);row=[];used=0
            row.append((i,word,span));used+=span+(gap if len(row)>1 else 0)
        if row:lines.append(row)
        if (len(lines)<=2 and all(sum(v[2] for v in r)+gap*(len(r)-1)<=limit for r in lines)) or size<=10:break
        size-=1
    out=[]
    for j,row in enumerate(lines):
        total=sum(v[2] for v in row)+gap*(len(row)-1);x=(width-total)/2;y=height*.90-(len(lines)-1-j)*size*1.42
        for i,word,span in row:
            out.append((word,i in hot,round(x+span/2),round(y),size,round(span),round(size*1.18)))
            x+=span+gap
    return out


def fit_text(draw,text,font_fn,size,max_width,max_lines=4):
    words=str(text).split();size=max(12,int(size))
    while size>=12:
        f=font_fn(size,True); rows=[]; row=''
        for word in words:
            trial=(row+' '+word).strip()
            if row and draw.textlength(trial,font=f)>max_width:rows.append(row);row=word
            else:row=trial
        if row:rows.append(row)
        if len(rows)<=max_lines and all(draw.textlength(r,font=f)<=max_width for r in rows):return f,rows,size
        size-=1
    return font_fn(12,True),[' '.join(words)[:60]],12


def artwork(scene,w,h,image,font):
    """Paper evidence, editorial focus, or chapter/statement composition.
    No fabricated quotes, highlights over guessed source words, or generated data."""
    bg=Image.new('RGB',(w,h),'#151719');d=ImageDraw.Draw(bg)
    kind=scene.get('editorial')
    if kind=='evidence' and image is not None:
        # Keep the complete original source on screen. A user-marked point can
        # add a separate focus panel; never obscure or edit the source itself.
        point=scene.get('evidence_focus'); valid=isinstance(point,(list,tuple)) and len(point)==2 and all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in point)
        split=valid and w/h>=1.4
        maxw=round(w*(.49 if split else .83));maxh=round(h*.66)
        scale=min(maxw/image.width,maxh/image.height);tw,th=max(1,round(image.width*scale)),max(1,round(image.height*scale))
        tile=image.resize((tw,th),Image.Resampling.LANCZOS);x=round(w*.055) if split else (w-tw)//2;y=round(h*.45-th/2)
        pad=max(5,h//80);d.rectangle((x-pad,y-pad,x+tw+pad,y+th+pad),fill='#f4f2ed');bg.paste(tile,(x,y))
        if split:
            fx,fy=point;cw=max(1,round(image.width*.42));ch=max(1,round(image.height*.30));cx=min(image.width-cw,max(0,round(fx*image.width-cw/2)));cy=min(image.height-ch,max(0,round(fy*image.height-ch/2)))
            crop=image.crop((cx,cy,cx+cw,cy+ch));sc=min(w*.38/cw,h*.40/ch);crop=crop.resize((max(1,round(cw*sc)),max(1,round(ch*sc))),Image.Resampling.LANCZOS)
            xx=round(w*.58);yy=round(h*.24);d.rectangle((xx-pad,yy-pad,xx+crop.width+pad,yy+crop.height+pad),fill=ACCENT);bg.paste(crop,(xx,yy))
            # Outline is an editorial callout, not a claim of text recognition.
            d.rectangle((x+round(cx*scale),y+round(cy*scale),x+round((cx+cw)*scale),y+round((cy+ch)*scale)),outline=ACCENT,width=max(2,h//180))
            d.text((xx,yy+crop.height+pad*2),'SOURCE DETAIL',font=font(max(11,h//42),True),fill=ACCENT)
        name=re.sub(r'\.[A-Za-z0-9]{2,5}$','',str(scene.get('asset_name','Supplied document'))).replace('_',' ').replace('-',' ')[:80];f,rows,sz=fit_text(d,name,font,h*.028,w*.86,2)
        for j,row in enumerate(rows):d.text((round(w*.06),round(h*.05+j*sz*1.2)),row,font=f,fill='#e3e1db')
        return bg
    if kind=='chapter':
        bg=Image.new('RGB',(w,h),'#f1f0ea');d=ImageDraw.Draw(bg);fg='#202124'
        d.text((round(w*.095),round(h*.20)),f'CHAPTER {int(scene.get("chapter",1)):02d}',font=font(max(12,h//32),True),fill='#515b64')
        text=scene.get('hero_title') or scene.get('text','')
    else:
        fg='#f7f5ef';text=scene.get('text','');d.line((round(w*.095),round(h*.25),round(w*.17),round(h*.25)),fill=ACCENT,width=max(2,h//130))
    f,rows,sz=fit_text(d,text,font,min(h*.095,w*.10),w*.80,4)
    y=round(h*.37) if kind=='chapter' else round(h*.46-(len(rows)-1)*sz*.60)
    for j,row in enumerate(rows):
        xx=round(w*.095);yy=y+round(j*sz*1.18)
        if j==len(rows)-1:
            box=d.textbbox((xx,yy),row,font=f,anchor='lt');d.rectangle((box[0]-4,box[1]-4,box[2]+4,box[3]+4),fill=ACCENT);color='#171819'
        else:color=fg
        d.text((xx,yy),row,font=f,fill=color,anchor='lt')
    return bg
