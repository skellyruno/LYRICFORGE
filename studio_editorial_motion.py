"""Frame-clocked editorial animation primitives, composable with any Director plan.
Graphics are explicitly authored data, not facts inferred from narration.
"""
from __future__ import annotations
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageFilter
import studio_editorial as ed

INK='#24262a'; PAPER='#f0eee7'; YELLOW='#f5d64e'; DARK='#15181b'
MOTION_REVISION=17

def ease(t):
    t=max(0.,min(1.,float(t)));return t*t*(3-2*t)

def phase(t,start,end):return ease((t-start)/max(.001,end-start))

def validate_graphic(g):
    if isinstance(g,dict) and g.get('kind')=='composition':
        from studio_layers import validate
        return validate(g)
    if not isinstance(g,dict) or g.get('kind') not in ('chart','timeline','quote','process','network','route'):raise ValueError('Unknown editorial graphic')
    def txt(v,n):
        if not isinstance(v,str) or not v.strip() or len(v)>n:raise ValueError('Invalid editorial graphic text')
        return v.strip()
    out={'kind':g['kind'],'title':txt(g.get('title'),100),'source':txt(g.get('source'),140)}
    if g['kind']=='quote':
        out['quote']=txt(g.get('quote'),280);return out
    rows=g.get('items');limit=5 if g['kind'] in ('timeline','network','route') else 4
    if not isinstance(rows,list) or not 2<=len(rows)<=limit:raise ValueError('Editorial graphic requires 2–'+str(limit)+' items')
    out['items']=[]
    for r in rows:
        if not isinstance(r,dict):raise ValueError('Invalid graphic item')
        item={'label':txt(r.get('label'),36)}
        if g['kind']=='chart':
            value=r.get('value')
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1e12:raise ValueError('Chart values must be finite and nonnegative')
            item['value']=value
        elif g['kind']=='timeline':item['date']=txt(r.get('date'),20)
        elif g['kind']=='route':
            for key,bound in (('lat',90),('lon',180)):
                v=r.get(key)
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or abs(v)>bound:raise ValueError('Invalid route coordinate')
                item[key]=v
        out['items'].append(item)
    if g['kind']=='network':
        links=g.get('links');n=len(rows)
        if not isinstance(links,list) or not 1<=len(links)<=10:raise ValueError('Network requires authored links')
        if any(not isinstance(link,(list,tuple)) or len(link)!=2 or any(type(i) is not int or not 0<=i<n for i in link) or link[0]==link[1] for link in links):raise ValueError('Invalid network link')
        out['links']=[list(link) for link in links]
    if g['kind']=='chart':
        if max(r['value'] for r in out['items'])==0:raise ValueError('Chart needs a positive value')
        out['unit']=txt(g.get('unit'),16)
    return out

def text(draw,xy,value,font,size,color,limit,bold=True,anchor='lt'):
    f=font(max(11,round(size)),bold)
    while f.getlength(value)>limit and size>11:
        size-=1;f=font(max(11,round(size)),bold)
    draw.text(tuple(map(round,xy)),value,font=f,fill=color,anchor=anchor)

def paste(im,source,x,y,alpha=1.):
    x,y=round(x),round(y)
    if alpha>=.999:im.paste(source,(x,y));return
    if alpha>0:im.paste(source,(x,y),Image.new('L',source.size,round(alpha*255)))

def blend(a,b,p):
    if p<=0:return a
    if p>=1:return b
    return Image.blend(a,b,p)

class EditorialShot:
    def __init__(self,scene,w,h,image,font,media_bank=None):
        self.scene,self.w,self.h,self.font=scene,w,h,font;self.image=image
        self.duration=max(.1,float(scene.get('end',4))-float(scene.get('start',0)));self.kind=scene.get('editorial');self.graphic=validate_graphic(scene['graphic']) if scene.get('graphic') else None
        self.premium=scene.get('editorial_look')=='midnight'
        self.light=(self.kind=='chapter' or bool(self.graphic)) and not self.premium
        self.bg=Image.new('RGB',(w,h),PAPER if self.light else '#101612' if self.premium else DARK)
        d=ImageDraw.Draw(self.bg)
        # Subtle stationery rules are independent from the content animation.
        if self.light:
            for x in range(round(w*.075),round(w*.94),max(24,w//24)):d.line((x,h*.07,x,h*.79),fill='#e9e7df',width=1)
        else:
            d.rectangle((round(w*.055),round(h*.07),round(w*.945),round(h*.79)),outline='#2c3033',width=1)
        self.src=None
        if self.kind=='evidence' and image:
            self.point=scene.get('evidence_focus');self.point=self.point if isinstance(self.point,(list,tuple)) and len(self.point)==2 and all(isinstance(v,(float,int)) and math.isfinite(v) and 0<=v<=1 for v in self.point) else None
            self.src=image.copy();self.full=ImageOps.contain(image,(round(w*.83),round(h*.60)),Image.Resampling.LANCZOS)
            self.left=ImageOps.contain(image,(round(w*.43),round(h*.57)),Image.Resampling.LANCZOS)
            # Upscale genuine source pixels if necessary, never synthesize detail.
            if self.point:
                fx,fy=self.point;cw=max(1,round(image.width*.44));ch=max(1,round(image.height*.34));cx=max(0,min(image.width-cw,round(fx*image.width-cw/2)));cy=max(0,min(image.height-ch,round(fy*image.height-ch/2)))
                self.crop_rect=(cx,cy,cw,ch);crop=image.crop((cx,cy,cx+cw,cy+ch));scale=min(w*.40/cw,h*.41/ch)
                self.detail=crop.resize((max(1,round(cw*scale)),max(1,round(ch*scale))),Image.Resampling.LANCZOS)
        self.title=str(scene.get('hero_title') or scene.get('text') or '')
        self.serif_cache={}
        self.composition=None
        if self.graphic and self.graphic['kind']=='composition':
            from studio_layers import Composition
            self.composition=Composition(self.graphic,w,h,self.duration,font,float(scene.get('start',0)),media_bank)
    def title_font(self,size,bold=False):
        from PIL import ImageFont
        k=(size,bold)
        if k not in self.serif_cache:
            for name in (r'C:\Windows\Fonts\georgia.ttf','DejaVuSerif.ttf','LiberationSerif-Regular.ttf'):
                try:self.serif_cache[k]=ImageFont.truetype(name,max(12,int(size)));break
                except OSError:pass
            else:self.serif_cache[k]=self.font(size,bold)
        return self.serif_cache[k]
    def render(self,t):
        w,h,f=self.w,self.h,self.font;im=self.bg.copy();d=ImageDraw.Draw(im)
        if self.composition:return self.composition.render(t)
        if self.graphic:return self.draw_graphic(im,t*min(2.5,3.5/self.duration))
        if self.src is not None:return self.draw_evidence(im,t)
        fg=INK if self.light else '#f4f2ed';muted='#62615c' if self.light else '#a2a6a5'
        label=f'CHAPTER {int(self.scene.get("chapter",1)):02d}' if self.light else 'THE STORY'
        text(d,(w*.095,h*.16),label,f,h*.028,muted,w*.8)
        p=phase(t,.05,.65);d.rectangle((w*.095,h*.25,w*.095+w*.11*p,h*.255),fill=YELLOW)
        face,rows,sz=ed.fit_text(d,self.title,self.title_font if self.premium else f,min(h*.115,w*.105),w*.80,4)
        y=h*.37-(len(rows)-1)*sz*.25
        for j,row in enumerate(rows):
            progress=phase(t,.13+j*.12,.75+j*.12);yy=y+j*sz*1.18+12*(1-progress);xx=w*.095
            layer=im.copy();ld=ImageDraw.Draw(layer)
            if j==len(rows)-1:
                box=ld.textbbox((round(xx),round(yy)),row,font=face,anchor='lt');q=phase(t,.55+j*.12,1.20+j*.12)
                ld.rectangle((box[0]-4,box[1]-4,box[0]+(box[2]-box[0]+4)*q,box[3]+5),fill=YELLOW)
            ld.text((round(xx),round(yy)),row,font=face,fill=INK if self.light else fg,anchor='lt')
            # Dark title gets a dark word on the yellow marker only after the sweep.
            if not self.light and j==len(rows)-1:
                if q>.98:ld.text((round(xx),round(yy)),row,font=face,fill=INK,anchor='lt')
                else:
                    # Clip a dark duplicate to the actual moving marker rectangle.
                    mask=Image.new('L',(w,h),0);md=ImageDraw.Draw(mask);md.rectangle((box[0]-4,box[1]-4,box[0]+(box[2]-box[0]+4)*q,box[3]+5),fill=255)
                    dark=layer.copy();ImageDraw.Draw(dark).text((round(xx),round(yy)),row,font=face,fill=INK,anchor='lt');layer.paste(dark,(0,0),mask)
            im=blend(im,layer,progress)
        d=ImageDraw.Draw(im);d.rectangle((w*.095,h*.70,w*.095+w*.16*phase(t,.9,max(1.0,self.duration*.85)),h*.704),fill=YELLOW)
        return im
    def draw_evidence(self,im,t):
        w,h,f=self.w,self.h,self.font;d=ImageDraw.Draw(im)
        name=str(self.scene.get('asset_name','Source document')).rsplit('.',1)[0].replace('_',' ')
        text(d,(w*.07,h*.09),name,f,h*.032,'#e4e3dd',w*.86)
        p=phase(t,.06,.63);q=phase(t,1.05,2.05) if self.point and w/h>=1.35 else 0.
        # Move the whole source aside, then reveal an independently animated crop.
        a,b=self.full,self.left;tw=round(a.width+(b.width-a.width)*q);th=round(a.height+(b.height-a.height)*q)
        tile=self.src.resize((max(1,tw),max(1,th)),Image.Resampling.LANCZOS)
        drift=phase(t,2.35,max(2.36,self.duration));x=(w-tw)/2*(1-q)+w*.075*q-w*.009*drift*q;y=h*.45-th/2+h*.05*(1-p)-h*.008*drift*q
        layer=im.copy();ld=ImageDraw.Draw(layer);pad=max(4,h//90)
        ld.rectangle((x-pad+5,y-pad+8,x+tw+pad+5,y+th+pad+8),fill='#090b0e');ld.rectangle((x-pad,y-pad,x+tw+pad,y+th+pad),fill='#f3f1eb');paste(layer,tile,x,y)
        if q>0:
            cx,cy,cw,ch=self.crop_rect;xx=x+tw*cx/self.src.width;yy=y+th*cy/self.src.height;xe=xx+tw*cw/self.src.width;ye=yy+th*ch/self.src.height
            z=phase(t,1.15,1.82);ld.line((xx,yy,xx+(xe-xx)*z,yy),fill=YELLOW,width=max(2,h//160));ld.line((xx,yy,xx,yy+(ye-yy)*z),fill=YELLOW,width=max(2,h//160))
            if z>.98:ld.rectangle((xx,yy,xe,ye),outline=YELLOW,width=max(2,h//160))
            r=phase(t,1.55,2.35);detail=self.detail;dx=w*.55+(1-r)*w*.05+w*.007*drift;dy=h*.43-detail.height/2-h*.012*drift
            call=layer.copy();cd=ImageDraw.Draw(call);cd.line((xe,(yy+ye)/2,dx-pad,dy+detail.height/2),fill=YELLOW,width=max(1,h//360));cd.rectangle((dx-pad,dy-pad,dx+detail.width+pad,dy+detail.height+pad),fill=YELLOW);paste(call,detail,dx,dy)
            text(cd,(dx,dy+detail.height+pad*2),'SOURCE DETAIL',f,h*.025,YELLOW,w*.40);layer=blend(layer,call,r)
        return blend(im,layer,p)
    def draw_graphic(self,im,t):
        w,h,f=self.w,self.h,self.font;g=self.graphic;d=ImageDraw.Draw(im);ink='#e9e7dc' if self.premium else INK
        muted='#9aab9d' if self.premium else '#535651';rule='#36483b' if self.premium else '#bbbcb2'
        panel='#19231d' if self.premium else '#faf9f3';outline='#415244' if self.premium else '#c1c1b5'
        shade='#0a110e' if self.premium else '#d7d5cd';track='#28342c' if self.premium else '#d9d8d0'
        bar_color='#abbbaa' if self.premium else '#41464a';rail='#506255' if self.premium else '#c4c4bb'
        text(d,(w*.075,h*.075),{'chart':'DATA / COMPARISON','timeline':'CHRONOLOGY','process':'THE PROCESS','quote':'FROM THE SOURCE','network':'RELATIONSHIPS','route':'GEOGRAPHY / ROUTE'}[g['kind']],f,h*.025,muted,w*.85)
        text(d,(w*.075,h*.135),g['title'],self.title_font if self.premium else f,min(h*.076,w*.075),ink,w*.85)
        d.line((w*.075,h*.233,w*.925,h*.233),fill=rule,width=max(1,h//360))
        text(d,(w*.075,h*.745),g['source'],f,h*.027,muted,w*.85,False)
        if g['kind'] in ('network','route'):
            from studio_graphics import draw_network,draw_route
            return (draw_network if g['kind']=='network' else draw_route)(im,g,t,f,self.premium)
        if g['kind']=='quote':
            face,rows,sz=ed.fit_text(d,g['quote'],f,min(h*.065,w*.075),w*.78,5)
            for i,row in enumerate(rows):
                q=phase(t,.15+i*.24,.75+i*.24);y=h*.28+i*sz*1.22
                layer=im.copy();dd=ImageDraw.Draw(layer);dd.rectangle((w*.075,y-3,w*.075+face.getlength(row)*q+5,y+sz*1.12),fill=YELLOW);dd.text((w*.075,y),row,font=face,fill=INK,anchor='lt');im=blend(im,layer,q)
            return im
        items=g['items'];n=len(items);x0=w*.075;x1=w*.92;y0=h*.29;y1=h*.71
        if g['kind']=='chart':
            maxv=max(i['value'] for i in items);rowh=(y1-y0)/n;labelw=w*.28;barw=w*.44
            for i,row in enumerate(items):
                y=y0+i*rowh;q=phase(t,.20+i*.18,1.35+i*.18)
                if w/h<1.25:
                    text(d,(x0,y),row['label'],f,min(h*.036,rowh*.30),ink,w*.55)
                    if q>.98:text(d,(x1,y),f"{row['value']:g} {g['unit']}",f,min(h*.036,rowh*.30),ink,w*.25,anchor='rt')
                    bx,by,bw,bh=x0,y+rowh*.36,x1-x0,rowh*.35
                else:
                    text(d,(x0,y+rowh*.19),row['label'],f,min(h*.052,rowh*.43),ink,labelw*.96)
                    if q>.98:text(d,(x1,y+rowh*.19),f"{row['value']:g} {g['unit']}",f,min(h*.052,rowh*.43),ink,w*.15,anchor='rt')
                    bx,by,bw,bh=x0+labelw,y+rowh*.1,barw,rowh*.52
                d.rectangle((bx,by,bx+bw,by+bh),fill=track)
                d.rectangle((bx,by,bx+bw*(row['value']/maxv)*q,by+bh),fill=YELLOW if i==n-1 else bar_color)
        elif g['kind']=='process':
            if self.premium and w/h>=1.25:
                # One continuous network instead of disconnected cards.
                xs=[w*(.135+.73*i/(n-1)) for i in range(n)];y=h*.45;radius=h*.048
                d.line((xs[0],y,xs[-1],y),fill=rail,width=max(1,h//240))
                q=phase(t,.12,2.05);head=xs[0]+(xs[-1]-xs[0])*q
                d.line((xs[0],y,head,y),fill=YELLOW,width=max(2,h//150))
                if 0<q<.999:
                    r=max(3,h*.010);d.ellipse((head-r,y-r,head+r,y+r),fill='#fff0aa')
                # Small secondary wave traverses the existing connectors after the reveal.
                # Timing is illustrative only, never measured signal data.
                if t>2.05:
                    k=phase(t,2.05,3.5);px=xs[0]+(xs[-1]-xs[0])*k
                    if k<.999:
                        r=h*.007;d.ellipse((px-r,y-r,px+r,y+r),fill='#fff0aa')
                for i,(x,row) in enumerate(zip(xs,items)):
                    q=phase(t,.1+1.8*i/(n-1),.55+1.8*i/(n-1));r=radius*(.65+.35*q)
                    d.ellipse((x-radius*1.27,y-radius*1.27,x+radius*1.27,y+radius*1.27),outline=rail,width=1)
                    d.ellipse((x-r,y-r,x+r,y+r),fill=shade,outline=YELLOW if q>.15 else rail,width=max(1,h//240))
                    text(d,(x,y),f'{i+1:02d}',f,h*.039,YELLOW if q>.15 else muted,r*1.65,anchor='mm')
                    if q>0:
                        layer=im.copy();dd=ImageDraw.Draw(layer);label_y=y+h*.108+(1-q)*h*.026
                        text(dd,(x,label_y),row['label'],f,h*.038,ink,w*.70/n,anchor='mt')
                        im=blend(im,layer,q);d=ImageDraw.Draw(im)
                return im
            horizontal=w/h>=1.25
            if horizontal:
                gap=w*.018;cw=(x1-x0-gap*(n-1))/n;ch=h*.36
                for i,row in enumerate(items):
                    q=phase(t,.08+i*.27,.78+i*.27);x=x0+i*(cw+gap);y=h*.36+(1-q)*h*.035
                    layer=im.copy();dd=ImageDraw.Draw(layer)
                    dd.rectangle((x+4,y+6,x+cw+4,y+ch+6),fill=shade)
                    dd.rectangle((x,y,x+cw,y+ch),fill=panel,outline=outline,width=max(1,h//360))
                    dd.rectangle((x,y,x+cw*q,y+h*.008),fill=YELLOW)
                    text(dd,(x+cw*.09,y+h*.025),f'{i+1:02d}',f,h*.078,ink,cw*.82)
                    text(dd,(x+cw*.09,y+ch*.66),row['label'],f,h*.043,ink,cw*.82)
                    im=blend(im,layer,q)
            else:
                rowh=(y1-y0)/n
                for i,row in enumerate(items):
                    q=phase(t,.08+i*.27,.78+i*.27);y=y0+i*rowh;layer=im.copy();dd=ImageDraw.Draw(layer)
                    dd.rectangle((x0,y,x1,y+rowh*.84),fill=panel,outline=outline);dd.rectangle((x0,y,x0+w*.014,y+rowh*.84),fill=YELLOW)
                    text(dd,(x0+w*.04,y+rowh*.13),f'{i+1:02d}   {row["label"]}',f,min(h*.035,rowh*.42),ink,w*.78);im=blend(im,layer,q)
        else:
            horizontal=w/h>=1.25
            if horizontal:
                xs=[x0+(x1-x0)*(i+.5)/n for i in range(n)];y=h*.48
                d.line((xs[0],y,xs[-1],y),fill=rail,width=max(3,h//150))
                d.line((xs[0],y,xs[0]+(xs[-1]-xs[0])*phase(t,.1,2.3),y),fill=ink,width=max(3,h//150))
                for i,(x,row) in enumerate(zip(xs,items)):
                    q=phase(t,.16+i*.38,.74+i*.38);r=max(3,h*.020*q);d.ellipse((x-r,y-r,x+r,y+r),fill=YELLOW if q>.1 else rail,outline=ink,width=max(1,h//360))
                    if q>.02:
                        above=i%2==0;yy=y-h*.155 if above else y+h*.09
                        layer=im.copy();dd=ImageDraw.Draw(layer);dd.line((x,y,x,yy+h*.09 if above else yy),fill='#797c75',width=max(1,h//300))
                        text(dd,(x,yy),row['date'],f,h*.052,ink,(x1-x0)/n*.93,anchor='mt')
                        text(dd,(x,yy+h*.062),row['label'],f,h*.036,ink,(x1-x0)/n*.93,False,anchor='mt');im=blend(im,layer,q);d=ImageDraw.Draw(im)
            else:
                for i,row in enumerate(items):
                    y=y0+(y1-y0)*i/n;q=phase(t,.14+i*.28,.74+i*.28)
                    if q>.02:
                        layer=im.copy();dd=ImageDraw.Draw(layer);dd.ellipse((x0,y,x0+h*.025,y+h*.025),fill=YELLOW,outline=ink)
                        text(dd,(x0+h*.04,y),row['date']+'  '+row['label'],f,h*.029,ink,w*.78);im=blend(im,layer,q)
        return im

def write_frames(scene,w,h,asset,folder,fps,font,check_cancel=lambda:None,*,bridge=None,editorial_bridge=None,footage_previous=None,assets_folder=None):
    from studio_media_layers import MediaBank
    with MediaBank(assets_folder,fps) as bank:
        return _write_frames(scene,w,h,asset,folder,fps,font,check_cancel,bridge=bridge,editorial_bridge=editorial_bridge,footage_previous=footage_previous,bank=bank)

def _write_frames(scene,w,h,asset,folder,fps,font,check_cancel,*,bridge,editorial_bridge,footage_previous,bank):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);image=None
    if asset:
        with Image.open(asset) as src:image=ImageOps.exif_transpose(src).convert('RGB')
    shot=EditorialShot(scene,w,h,image,font,bank)
    previous=None
    if bridge and scene.get('bridge_scene'):
        from studio_spatial import SpatialShot
        with Image.open(bridge) as src:previous=SpatialShot(ImageOps.exif_transpose(src),w,h,scene['bridge_scene'],font)
    from studio_spatial import editorial_previous,editorial_handoff
    prior=editorial_previous(scene,w,h,font,editorial_bridge,media_bank=bank)
    prior_composition=None
    old=scene.get('editorial_bridge_scene') or {}
    if shot.composition and (old.get('graphic') or {}).get('kind')=='composition':
        prior_composition=EditorialShot(old,w,h,None,font,bank).composition
    for i in range(scene['frames']):
        if i%12==0:check_cancel()
        frame=shot.render(i/fps)
        if previous and i/fps<scene['bridge_seconds']:frame=previous.bridge(frame,i/fps,scene['bridge_seconds'])
        if prior_composition and i/fps<scene['editorial_bridge_seconds']:frame=shot.composition.bridge(prior_composition,i/fps,scene['editorial_bridge_seconds'])
        elif prior is not None and i/fps<scene['editorial_bridge_seconds']:frame=editorial_handoff(prior,frame,i/fps,scene['editorial_bridge_seconds'])
        if footage_previous is not None and i/fps<scene['footage_bridge_seconds']:frame=editorial_handoff(footage_previous,frame,i/fps,scene['footage_bridge_seconds'])
        frame.save(folder/f'{i+1:05d}.jpg',quality=94,subsampling=0)
    return fps
