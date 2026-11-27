"""Reference storytelling grammar from human-confirmed shot annotations.
No automatic semantic understanding or fabricated source content.
"""
import math,re
from collections import Counter
ROLES={'hook','context','evidence','explanation','comparison','resolution','demonstration'}
TECHNIQUES={'footage','document','diagram','typography','product','collage','hold'}

def grammar(notes):
    if not isinstance(notes,list) or not 1<=len(notes)<=120:raise ValueError('Reference notes need 1–120 observations')
    transitions=Counter();byrole={};last=None;last_time=-1
    for n in notes:
        if not isinstance(n,dict):raise ValueError('Invalid reference observation')
        t=n.get('time');role=n.get('role');tech=n.get('technique')
        if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or not last_time<t<=1800 or t<0 or not isinstance(role,str) or not isinstance(tech,str) or role not in ROLES or tech not in TECHNIQUES:raise ValueError('Invalid reference observation')
        byrole.setdefault(role,Counter())[tech]+=1
        if last:transitions[last+'>'+role]+=1
        last=role;last_time=t
    return {'observations':len(notes),'techniques':{k:dict(v) for k,v in byrole.items()},'role_transitions':dict(transitions),'basis':'Human-confirmed reference observations; no automated semantic recognition.'}

def role_for(text,hint,graphic=None):
    s=(hint+' '+text).lower()
    if graphic and isinstance(graphic,dict):
        if graphic.get('kind')=='chart':return 'comparison'
        if graphic.get('kind')=='quote':return 'evidence'
        return 'explanation'
    for role,pattern in [('evidence',r'\b(evidence|source document|article|quotation|excerpt|proof)\b'),('comparison',r'\b(compare|comparison|versus|difference)\b'),('demonstration',r'\b(demonstration|demo|watch|interface|control)\b'),('resolution',r'\b(conclusion|resolution|finally|closing)\b'),('explanation',r'\b(how|mechanism|diagram|process|illustration)\b'),('hook',r'\b(hook|opening|question)\b')]:
        if re.search(pattern,s):return role
    return 'context'

def bonus(profile,role,asset):
    # Only call as a tie-break AFTER positive semantic metadata overlap.
    if not isinstance(profile,dict):return 0.
    profile_grammar=profile.get('story_grammar');weight=.65
    if not isinstance(profile_grammar,dict):
        # Never treat uncertain frame labels as verified evidence. A local model's
        # provisional style hypotheses can nudge relevant existing media only.
        predicted=profile.get('vision_hypotheses');rows=predicted.get('observations',[]) if isinstance(predicted,dict) else []
        filtered=[r for r in rows[:12] if isinstance(r,dict) and all(isinstance(r.get(k),(int,float)) and math.isfinite(r[k]) and r[k]>=1. for k in ('technique_margin','role_margin'))] if isinstance(rows,list) else []
        try:profile_grammar=grammar(filtered) if filtered else None
        except ValueError:profile_grammar=None
        weight=.15
    counts=profile_grammar.get('techniques') if isinstance(profile_grammar,dict) else None
    counts=counts.get(role) if isinstance(counts,dict) else None
    if not isinstance(counts,dict):return 0.
    safe={k:v for k,v in counts.items() if k in TECHNIQUES and type(v) is int and 0<v<=120};total=sum(safe.values())
    tech='document' if asset.get('role')=='document' else 'product' if asset.get('role') in ('plugin_state','plugin_recording') else 'footage' if asset.get('kind')=='video' else 'hold'
    return weight*safe.get(tech,0)/max(1,total)
