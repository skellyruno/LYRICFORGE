"""Conservative automatic multi-media editorial compositions.
Only use positively matched, locally supplied B-roll/documents; never retime a
recorded plugin demo or infer evidence from a filename. Authored graphics win.
"""
import re,math
from studio_media_layers import PATTERN,VIDEO
from studio_layers import validate

def plan(text,hint,title,assets,terms,seconds):
    if seconds<3 or not re.search(r'\b(?:collage|side.by.side|compare|comparison|evidence together|source documents)\b',hint+' '+text,re.I):return None
    candidates=[];seen=set()
    for a in assets:
        if not isinstance(a,dict) or a.get('source') or a.get('disabled') or a.get('role') not in ('document','broll') or a.get('id') in seen:continue
        key=a.get('id');kind=a.get('kind');role=a.get('role')
        if not isinstance(key,str) or not PATTERN.fullmatch(key) or (kind=='video')!=(key[key.rfind('.'):] in VIDEO):continue
        if role=='document' and kind!='image':continue
        vocabulary=terms(str(a.get('name',''))+' '+str(a.get('description','')));overlap=len(terms(text)&vocabulary)+2*len(terms(hint)&vocabulary)
        if overlap<2:continue
        if kind=='video':
            try:
                duration=float(a.get('features',{}).get('duration',0));start=float(a.get('trim_start',0) or 0);end=min(duration,float(a.get('trim_end') or duration),start+min(20,seconds))
                if not all(math.isfinite(x) for x in (duration,start,end)) or start<0 or end-start<.5 or end>1800:continue
            except (ValueError,TypeError):continue
        else:start=end=0
        candidates.append((overlap,key,a,start,end));seen.add(key)
    if len(candidates)<2:return None
    chosen=sorted(candidates,key=lambda x:(-x[0],x[1]))[:2]
    # Responsive side-by-side in landscape, stacked in portrait via authored
    # normalized geometry adjusted in composition constructor (not needed here:
    # 2 equal media panes are deliberately centered and fit, never cropped).
    rows=[dict(id='heading',type='text',text=title or 'Source comparison',face='serif',size=.061,width=.86,height=.16,track=[[0,.5,.135,1,1]],depth=-.5)]
    for i,(_,key,a,start,end) in enumerate(chosen):
        x=.265+.47*i;role=a['role'];kind='footage' if a['kind']=='video' else 'document' if role=='document' else 'image'
        rows.append(dict(id='media-'+str(i),type=kind,asset=key,width=.43,height=.58,depth=.2,fit='contain',track=[[0,x,.49,.91,0],[.20+.07*i,x,.49,1,1],[1,x,.49,1,1]],**({'trim':[start,end]} if kind=='footage' else {})))
        label=str(a.get('name','Source')).rsplit('.',1)[0][:60].strip() or 'Source'
        rows.append(dict(id='label-'+str(i),type='text',text=label,face='mono',size=.028,width=.41,height=.085,color='gold',track=[[0,x,.815,1,0],[.30+.07*i,x,.815,1,1]],depth=-.4))
    spec=validate(dict(kind='composition',title=(title or 'Source comparison')[:100],source='USER-SUPPLIED VISUALS  /  EDITORIAL COMPARISON · VERIFY CLAIMS AGAINST ORIGINALS',layers=rows))
    from studio_storyboard import choose_comparison
    aspects=[]
    for _,_,a,_,_ in chosen:
        f=a.get('features',{})
        try:ratio=float(f.get('width',0))/float(f.get('height',0));ratio=ratio if math.isfinite(ratio) and .2<=ratio<=5 else 16/9
        except (ValueError,TypeError,ZeroDivisionError):ratio=16/9
        aspects.append(ratio)
    selected,report=choose_comparison(spec,aspects);selected['storyboard']=report;return selected
