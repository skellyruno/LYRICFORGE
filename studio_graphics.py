"""Authored relationship networks and coordinate-based route diagrams.
No generated locations, relationships or geographical boundary data.
"""
import math
from PIL import Image,ImageDraw,ImageFilter

def smooth(x):
    x=max(0.,min(1.,x));return x*x*x*(10+x*(-15+6*x))

def _label(d,xy,label,font,size,width,color,anchor='mm'):
    size=max(10,round(size));f=font(size,True)
    while size>10 and f.getlength(label)>width:size-=1;f=font(size,True)
    d.text(tuple(map(round,xy)),label,font=f,fill=color,anchor=anchor)

def draw_network(im,g,t,font,premium):
    w,h=im.size;d=ImageDraw.Draw(im);n=len(g['items']);cx,cy=w*.5,h*.48;rx,ry=w*.32,h*.15
    fg='#e8e9e1' if premium else '#24262a';muted='#768d85' if premium else '#9b9f98';gold='#f5d64e'
    # Hub and spokes or arbitrary supplied connections. Layout is schematic.
    center=(cx,cy);pts=[center]+[(cx+rx*math.sin(2*math.pi*i/(n-1)),cy-ry*math.cos(2*math.pi*i/(n-1))) for i in range(n-1)]
    # A sequential graph gets a flowing zig-zag, a hub graph gets radial layout.
    chain=all(set(edge)=={i,i+1} for i,edge in enumerate(g['links'])) and len(g['links'])==n-1
    if chain:
        pts=[(w*(.14+.72*i/max(1,n-1)),h*(.43+.10*(i%2))) for i in range(n)] if w/h>=1.25 else [(w*(.40+.20*(i%2)),h*(.31+.31*i/max(1,n-1))) for i in range(n)]
    radii=[h*(.046 if i==0 else .027) for i in range(n)]
    for i,(a,b) in enumerate(g['links']):
        x,y=pts[a];u,v=pts[b];length=max(.001,math.hypot(u-x,v-y));dx,dy=(u-x)/length,(v-y)/length
        x+=dx*radii[a]*1.1;y+=dy*radii[a]*1.1;u-=dx*radii[b]*1.1;v-=dy*radii[b]*1.1
        p=smooth((t-.18-i*.16)/.8);d.line((x,y,u,v),fill=muted,width=max(1,h//400));d.line((x,y,x+(u-x)*p,y+(v-y)*p),fill=gold,width=max(2,h//240))
        if 0<p<1:
            xx=x+(u-x)*p;yy=y+(v-y)*p;r=h*.008;d.ellipse((xx-r,yy-r,xx+r,yy+r),fill=gold)
    for i,((x,y),row) in enumerate(zip(pts,g['items'])):
        p=smooth((t-.12-i*.13)/.65);r=h*(.046 if i==0 else .027)*(.7+.3*p)
        d.ellipse((x-r*1.6,y-r*1.6,x+r*1.6,y+r*1.6),outline=muted,width=1)
        d.ellipse((x-r,y-r,x+r,y+r),fill='#172922' if premium else '#f7f6ef',outline=gold if p>.15 else muted,width=max(1,h//250))
        if p>.1:
            _label(d,(x,y),str(i+1).zfill(2),font,h*.028,r*1.75,gold if premium else '#463d13')
            above=(i%2==0) if chain and w/h>=1.25 else bool(i and y<cy)
            ytext=y-r*1.8-h*.009 if above else y+r*1.8+h*.009
            _label(d,(x,ytext),row['label'],font,min(h*.033,w*.032),w*(.22 if chain and w/h>=1.25 else .31 if i else .26),fg,'mb' if above else 'mt')
    return im

def draw_route(im,g,t,font,premium):
    w,h=im.size;d=ImageDraw.Draw(im);items=g['items'];fg='#e8e9e1' if premium else '#24262a';muted='#526960' if premium else '#b7bdb7';gold='#f5d64e'
    # Equirectangular local route schematic; not a street map or measured journey.
    # Unwrap longitude relative to first location for antimeridian routes.
    origin=items[0]['lon'];lng=[origin+((r['lon']-origin+180)%360-180) for r in items];lat=[r['lat'] for r in items];mean=sum(lat)/len(lat);lng=[v*max(.1,math.cos(math.radians(mean))) for v in lng]
    spanx=max(.01,max(lng)-min(lng));spany=max(.01,max(lat)-min(lat));scale=min(w*.65/spanx,h*.30/spany)
    cx=(max(lng)+min(lng))/2;cy=(max(lat)+min(lat))/2;pts=[(w*.5+(x-cx)*scale,h*.47-(y-cy)*scale) for x,y in zip(lng,lat)]
    for i in range(6):
        x=w*(.10+.16*i);d.line((x,h*.26,x,h*.68),fill=muted,width=1)
    for i in range(5):
        y=h*(.27+.10*i);d.line((w*.10,y,w*.90,y),fill=muted,width=1)
    for i,(a,b) in enumerate(zip(pts,pts[1:])):
        p=smooth((t-.18-i*.36)/.75);d.line((*a,*b),fill=muted,width=max(1,h//300));d.line((*a,a[0]+(b[0]-a[0])*p,a[1]+(b[1]-a[1])*p),fill=gold,width=max(2,h//170))
    for i,(x,y) in enumerate(pts):
        p=smooth((t-.12-i*.35)/.45);r=max(3,h*.014*p);d.ellipse((x-r,y-r,x+r,y+r),fill=gold,outline=fg,width=1)
        if p>.05:
            label=str(i+1)+' · '+items[i]['label'];size=max(10,round(min(h*.025,w*.033)));face=font(size,True)
            while face.getlength(label)>w*.30 and size>10:size-=1;face=font(size,True)
            lw=face.getlength(label);gap=h*.028
            # Place label opposite the closest segment, clamp to safe area.
            # An opaque small backing keeps the text clear of crossing paths.
            yy=y-gap if i%2==0 else y+gap
            xx=max(w*.095+lw/2,min(w*.905-lw/2,x));anchor='mb' if i%2==0 else 'mt'
            box=d.textbbox((round(xx),round(yy)),label,font=face,anchor=anchor);pad=max(2,h//240)
            d.rectangle((box[0]-pad,box[1]-pad,box[2]+pad,box[3]+pad),fill='#101612' if premium else '#f0eee7')
            d.text((round(xx),round(yy)),label,font=face,fill=fg,anchor=anchor)
    _label(d,(w*.90,h*.705),'COORDINATE SCHEMATIC · NOT ROAD DIRECTIONS',font,h*.019,w*.8,fg,'rt')
    return im
