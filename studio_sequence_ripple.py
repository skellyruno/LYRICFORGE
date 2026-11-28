"""Map independent tracks through explicit, frame-clock edits of the current base.
Overlapping picture/music/SFX clips are split or trimmed with source offsets
intact. All changes are previewable.
"""
from copy import deepcopy
import hashlib
import studio_timeline as tl


def ripple(state, instruction, assets):
    events=[]
    base=tl.plan({k:v for k,v in assets.items() if v.get('has_video')},instruction,current=state['base'],events=events)
    layers=deepcopy(state['layers']); transitions=deepcopy(state['transitions']); report=[]
    reserved={x['id'] for x in layers}
    def new_id(old):
        for n in range(1000):
            key='split-'+hashlib.sha256(f'{old}:{n}'.encode()).hexdigest()[:24]
            if key not in reserved:
                reserved.add(key);return key
        raise ValueError('Too many split clips')
    def fragment(x,lo,hi,at,*,second=False):
        y={**x,'at':at,'length':hi-lo}
        if second:y['id']=new_id(x['id'])
        y['offset']=x.get('offset',0)+lo-x['at']
        if x['kind']=='visual':y['fade']=0
        if x['kind'] in ('music','visual'):
            fi=x.get('fade_in',x.get('fade',0));fo=x.get('fade_out',x.get('fade',0))
            y['fade_in']=min(fi if lo==x['at'] else 0,y['length'])
            y['fade_out']=min(fo if hi==x['at']+x['length'] else 0,y['length']-y['fade_in'])
        return y
    for op,a,b in events:
        if op=='replace':
            # Clock unchanged. Keep layers anchored; affected transitions are
            # checked against new base boundaries below.
            report.append(f'Replaced picture range {a}–{b}; independent layers retain timing')
            continue
        out=[]
        for x in layers:
            lo,hi=x['at'],x['at']+x['length']; name=x['id']
            if op=='insert':
                if hi<=a:out.append(x)
                elif lo>=a:out.append({**x,'at':lo+b});report.append(f'Moved {name} by +{b} frames')
                else:
                    out.extend([fragment(x,lo,a,lo),fragment(x,a,hi,a+b,second=True)])
                    report.append(f'Split {name} around inserted footage ({b} frames)')
            else:
                delta=b-a
                if hi<=a:out.append(x)
                elif lo>=b:out.append({**x,'at':lo-delta});report.append(f'Moved {name} by -{delta} frames')
                else:
                    spans=[]
                    if lo<a:spans.append((lo,a,lo))
                    if hi>b:spans.append((b,hi,a))
                    for i,(left,right,at) in enumerate(spans):out.append(fragment(x,left,right,at,second=i>0))
                    report.append(f'{"Split" if len(spans)==2 else "Trimmed" if spans else "Removed"} {name}: {min(hi,b)-max(lo,a)} frames cut')
        layers=out
        remaining=[]
        for t in transitions:
            at=t['at'];h=t['half']
            if op=='insert':
                if at-h<=a<=at+h:report.append(f'Removed transition at {at}: insertion intersects its extent');continue
                if at>a:t={**t,'at':at+b}
            else:
                if a<=at+h and b>=at-h:report.append(f'Removed transition at {at}: cut intersects its extent');continue
                if at>=b:t={**t,'at':at-(b-a)}
            remaining.append(t)
        transitions=remaining
    bounds={};cursor=0
    for p,q in zip(base['pieces'],base['pieces'][1:]):
        cursor+=p['length'];bounds[cursor]=min(p['length'],q['length'])//2
    final=[]
    for t in transitions:
        h=min(t['half'],bounds.get(t['at'],0))
        if not h:report.append(f'Removed transition at {t["at"]}: no valid base cut remains')
        else:
            if h!=t['half']:report.append(f'Shortened transition at {t["at"]} to {2*h} frames')
            final.append({**t,'half':h})
    return {**deepcopy(state),'base':base,'layers':layers,'transitions':final,'ripple_report':report}
