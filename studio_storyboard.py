"""Deterministic candidate selection for source-backed comparisons, not a vision model."""
from copy import deepcopy
from studio_layers import validate

def choose_comparison(spec,aspects):
    """Compare balanced, lead-detail, and stacked compositions. Score visible
    aspect-fit area and balance, no changes to source trim or timing."""
    rows=[]
    designs=[('balanced',[(.265,.49,.43,.58),(.735,.49,.43,.58)],[(.265,.815),(.735,.815)]),
             ('lead-detail',[(.30,.49,.54,.58),(.77,.49,.34,.58)],[(.30,.815),(.77,.815)]),
             ('detail-lead',[(.23,.49,.34,.58),(.70,.49,.54,.58)],[(.23,.815),(.70,.815)]),
             ('stacked',[(.5,.34,.72,.29),(.5,.68,.72,.29)],[(.5,.51),(.5,.85)])]
    for name,panes,labels in designs:
        trial=deepcopy(spec);fit=[]
        for i,(x,y,w,h) in enumerate(panes):
            layer=next(l for l in trial['layers'] if l['id']==f'media-{i}');label=next(l for l in trial['layers'] if l['id']==f'label-{i}')
            layer.update(width=w,height=h,track=[[t,x,y,s,a] for t,_,_,s,a in layer['track']]);lx,ly=labels[i];label.update(width=w,height=.065,track=[[t,lx,ly,s,a] for t,_,_,s,a in label['track']]);ratio=aspects[i];pane=w*16/9/h;fit.append(w*h*min(ratio/pane,pane/ratio))
        value=sum(fit)+.6*min(fit)-.1*abs(fit[0]-fit[1]);rows.append((value,name,validate(trial)))
    rows.sort(key=lambda r:(-r[0],r[1]));return rows[0][2],{'selected':rows[0][1],'candidates':[{'name':n,'score':round(v,5)} for v,n,_ in rows],'basis':'Aspect-fit area and visual balance; not artistic or semantic approval.'}
