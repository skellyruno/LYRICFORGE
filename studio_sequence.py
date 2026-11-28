"""Versioned, non-destructive sequence and independent visual/audio layers.
Frame units throughout; server asset identifiers only. No user paths or filters.
"""
from __future__ import annotations
import copy, json, math, os, re, tempfile, threading
from pathlib import Path
import studio_timeline as tl

SCHEMA=1
HISTORY=24
MAX_LAYERS=12
LOCK=threading.RLock()
SFX={'pop','whoosh','riser','impact'}

def integer(n,lo,hi):
    if type(n) is not int or not lo<=n<=hi: raise ValueError(f'Expected integer between {lo} and {hi}')
    return n

def gain(n):
    if type(n) not in (int,float) or not math.isfinite(n) or not 0<=n<=1: raise ValueError('Gain must be 0–1')
    return float(n)

def version(asset):
    p=Path(asset['path']); s=p.stat()
    if not p.is_file() or p.is_symlink():raise ValueError('Invalid media')
    return [str(p.resolve()),s.st_size,s.st_mtime_ns]

def initial(assets):
    base=tl.plan({'source':assets['source']},'keep original')
    return {'base':base,'layers':[],'transitions':[],'media':{'source':version(assets['source'])}}

def used(state):
    return {x for p in state['base']['pieces'] for x in (p['asset'],p['audio']) if x} | {x['asset'] for x in state['layers'] if x['kind']!='sfx'}

def validate(state,assets,*,check_versions=True):
    base=state['base']; total=integer(base['frames'],1,tl.MAX_FRAMES)
    if base['fps']!=tl.FPS or len(base['pieces'])>tl.MAX_PIECES or sum(p['length'] for p in base['pieces'])!=total:raise ValueError('Invalid base clock')
    if len(state['layers'])>MAX_LAYERS or len(state['transitions'])>32:raise ValueError('Too many layers or transitions')
    def bounds(asset,start,n,kind):
        if asset not in assets or not assets[asset].get(kind):raise ValueError(f'Missing or incompatible asset: {asset}')
        integer(start,0,tl.MAX_FRAMES);integer(n,1,tl.MAX_FRAMES)
        if start+n>tl.duration_frames(assets[asset]['duration']):raise ValueError('Media range exceeds available footage')
    for p in base['pieces']:
        bounds(p['asset'],p['start'],p['length'],'has_video')
        if p['audio']:bounds(p['audio'],p['audio_start'],p['length'],'has_audio')
    ids=set()
    for x in state['layers']:
        if not re.fullmatch('[a-z0-9_-]{1,40}',x['id']) or x['id'] in ids:raise ValueError('Invalid or duplicate layer ID')
        ids.add(x['id']); start=integer(x['at'],0,total-1);n=integer(x['length'],1,total-start)
        if x['kind']=='visual':
            bounds(x['asset'],x['offset'],n,'has_video');integer(x['fade'],0,n//2)
            fi=integer(x.get('fade_in',x['fade']),0,n);integer(x.get('fade_out',x['fade']),0,n-fi)
        elif x['kind']=='music':
            bounds(x['asset'],x['offset'],n,'has_audio');gain(x['gain']);integer(x['fade_in'],0,n);integer(x['fade_out'],0,n-x['fade_in'])
            if type(x['duck']) is not bool:raise ValueError('Duck must be boolean')
        elif x['kind']=='sfx':
            if x['effect'] not in SFX:raise ValueError('Unsupported effect')
            gain(x['gain']);integer(x.get('offset',0),0,tl.MAX_FRAMES-n)
        else:raise ValueError('Unknown track kind')
    # One music bed at any instant; multiple independently editable clips allowed.
    music=sorted((x['at'],x['at']+x['length']) for x in state['layers'] if x['kind']=='music')
    if any(a[1]>b[0] for a,b in zip(music,music[1:])):raise ValueError('Music clips must not overlap')
    cursor=0; boundaries={}
    pieces=base['pieces']
    for i,p in enumerate(pieces[:-1]):
        cursor+=p['length'];boundaries[cursor]=min(p['length'],pieces[i+1]['length'])//2
    seen=set()
    for t in state['transitions']:
        at=integer(t['at'],1,total-1)
        if at not in boundaries or at in seen or t['kind']!='dip':raise ValueError('Transition must be on a unique base cut')
        integer(t['half'],1,boundaries[at]);seen.add(at)
    if check_versions:
        for k in used(state):
            if k not in assets or state['media'].get(k)!=version(assets[k]):raise ValueError(f'Media changed or missing: {k}; restore it or reset sequence')
    return state

def update_media(state,assets):
    # Existing used assets must have been validated before mutation.
    state['media']={k:version(assets[k]) for k in sorted(used(state))}

def apply(state,action,assets):
    s=copy.deepcopy(state);s.pop('ripple_report',None);kind=action.get('op');total=s['base']['frames']
    if kind=='batch':
        actions=action.get('actions')
        if not isinstance(actions,list) or not 1<=len(actions)<=6 or any(not isinstance(x,dict) or x.get('op') not in ('ripple','put','transition') for x in actions):raise ValueError('Invalid sequence batch')
        reports=[]
        for item in actions:
            s=apply(s,item,assets);reports.extend(s.get('ripple_report',[]))
        if reports:s['ripple_report']=reports
    elif kind=='ripple':
        from studio_sequence_ripple import ripple
        s=ripple(s,action['instruction'],assets)
    elif kind=='base':
        # Avoid silent movement of separately timed layers. Visual-only replacement
        # can preserve the clock, but rebuilding a base is an explicit operation.
        if s['layers'] or s['transitions']:raise ValueError('Remove independent layers/transitions before rebuilding the base timeline')
        s['base']=tl.plan({k:v for k,v in assets.items() if v.get('has_video')},action['instruction'])
    elif kind=='put':
        x=action['layer']; typ=x['kind']
        common={'id':x['id'],'kind':typ,'at':x['at'],'length':x['length']}
        if typ=='visual': row={**common,'asset':x['asset'],'offset':x.get('offset',0),'fade':x.get('fade',0),**{k:x[k] for k in ('fade_in','fade_out') if k in x}}
        elif typ=='music': row={**common,'asset':x['asset'],'offset':x.get('offset',0),'gain':x.get('gain',.15),'fade_in':x.get('fade_in',0),'fade_out':x.get('fade_out',0),'duck':x.get('duck',True)}
        elif typ=='sfx': row={**common,'effect':x['effect'],'gain':x.get('gain',.12),'offset':x.get('offset',0)}
        else:raise ValueError('Unknown track kind')
        found=next((i for i,v in enumerate(s['layers']) if v['id']==row['id']),None)
        if found is None:s['layers'].append(row)
        else:s['layers'][found]=row
    elif kind=='remove':
        old=len(s['layers']);s['layers']=[x for x in s['layers'] if x['id']!=action['id']]
        if len(s['layers'])==old:raise ValueError('Unknown layer')
    elif kind=='transition':
        at=integer(action['at'],1,total-1);s['transitions']=[t for t in s['transitions'] if t['at']!=at]
        if action.get('kind')!='cut':s['transitions'].append({'at':at,'kind':action['kind'],'half':action['half']})
    elif kind=='reset':return initial(assets)
    else:raise ValueError('Unknown sequence action')
    validate(s,assets,check_versions=False);update_media(s,assets);return s

class Store:
    """Atomic JSON commits with optimistic revision checks and bounded undo/redo."""
    def __init__(self,folder,assets):self.path=Path(folder)/'sequence-v3.json';self.assets=assets
    def _load(self):
        if self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_size>4_000_000:raise ValueError('Invalid sequence storage')
            d=json.loads(self.path.read_text(encoding='utf-8'))
            if d.get('schema')!=SCHEMA:raise ValueError('Unsupported sequence schema')
            return d
        d={'schema':SCHEMA,'revision':0,'state':initial(self.assets),'undo':[],'redo':[]}
        self._write(d)
        return d
    def _write(self,d):
        fd,tmp=tempfile.mkstemp(prefix='.sequence-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False,allow_nan=False);f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:Path(tmp).unlink(missing_ok=True)
    def view(self,d):
        # Paths are internal and not exposed to the browser.
        s=copy.deepcopy(d['state']);s.pop('media',None)
        try:validate(d['state'],self.assets);error=''
        except ValueError as e:error=str(e)
        return {'revision':d['revision'],'state':s,'can_undo':bool(d['undo']),'can_redo':bool(d['redo']),'media_error':error}
    def get(self):
        with LOCK:return self.view(self._load())
    def snapshot(self,revision):
        with LOCK:
            d=self._load()
            if d['revision']!=revision:raise Conflict('Sequence changed; refresh')
            return copy.deepcopy(validate(d['state'],self.assets))
    def mutate(self,revision,action):
        with LOCK:
            d=self._load()
            if d['revision']!=revision:raise Conflict('Sequence changed; refresh')
            s=d['state'];op=action.get('op')
            if op in ('undo','redo'):
                other='redo' if op=='undo' else 'undo'
                if not d[op]:raise ValueError('No '+op+' available')
                candidate=d[op][-1];validate(candidate,self.assets)
                d[op].pop();d[other].append(s);d['state']=candidate
            else:
                if op!='reset':validate(s,self.assets)
                d['state']=apply(s,action,self.assets);d['undo']=(d['undo']+[s])[-HISTORY:];d['redo']=[]
            d['revision']+=1
            self._write(d)
            return self.view(d)

class Conflict(ValueError):pass
