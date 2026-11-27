"""Deterministic non-destructive research scene revisions without a model.

Only explicit supported instructions are executed; a compound request is
atomic, and the previous draft remains available if any clause is unsupported.
"""
from copy import deepcopy
import re
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel,Field
import studio_creator as creator

router=APIRouter()

def revise(chapters,instruction):
    original=creator.validate_script(chapters,'research')
    scenes=[deepcopy(c) for c in original if c['title']!='Sources and credits']
    credits=[deepcopy(c) for c in original if c['title']=='Sources and credits']
    if not scenes:raise ValueError('No editable scenes')
    changes=[];options={}
    def index(value):
        number=int(value)
        if not 1<=number<=len(scenes):raise ValueError('Scene number is outside the current draft')
        return number-1
    clauses=[s.strip() for s in re.split(r'[;\n]+',instruction) if s.strip()]
    if not clauses or len(clauses)>12:raise ValueError('Enter up to 12 edits separated by semicolons')
    for clause in clauses:
        normalized=clause.casefold().strip().rstrip('.')
        match=re.fullmatch(r'(?:remove|delete) (?:scene|chapter) (\d+)',normalized)
        if match:
            if len(scenes)<=1:raise ValueError('Keep at least one scene')
            i=index(match[1]);scenes.pop(i);changes.append(f'Removed scene {i+1}');continue
        match=re.fullmatch(r'move (?:scene|chapter) (\d+) to (?:position |scene |chapter )?(\d+)',normalized)
        if match:
            i,j=index(match[1]),index(match[2]);scenes.insert(j,scenes.pop(i));changes.append(f'Moved scene {i+1} to {j+1}');continue
        match=re.fullmatch(r'(?:set|change) (?:scene|chapter) (\d+) (title|visual|narration) to (.+)',clause,re.I)
        if match:
            i=index(match[1]);field={'title':'title','visual':'visual_hint','narration':'narration'}[match[2].casefold()]
            value=match[3].strip().strip('"')
            if not value or len(value)>{'title':80,'visual_hint':300,'narration':1200}[field]:raise ValueError('Scene text is empty or too long')
            scenes[i][field]=value
            changes.append(f'Changed scene {i+1} {match[2].casefold()}');continue
        match=re.fullmatch(r'(?:set |change )?(?:format|aspect ratio) (?:to )?(square|vertical|landscape|youtube|shorts)',normalized)
        if match:
            options['format']={'square':'square','vertical':'reel30','shorts':'reel30','landscape':'youtube','youtube':'youtube'}[match[1]]
            changes.append('Changed output format');continue
        match=re.fullmatch(r'(?:set |change )?(?:delivery|narration pace) (?:to )?(calm|documentary|energetic|neutral|tutorial|presenter)',normalized)
        if match:
            options['delivery']='documentary' if match[1]=='calm' else match[1]
            changes.append('Changed narration delivery');continue
        match=re.fullmatch(r'(?:turn |set )?(sound design|title motion|automatic footage) (on|off)',normalized)
        if match:
            options[{'sound design':'sound_design','title motion':'title_motion','automatic footage':'auto_pictures'}[match[1]]]=match[2]=='on'
            changes.append(f'{match[1].capitalize()} {match[2]}');continue
        raise ValueError('Unsupported direct edit. Use explicit scene commands, or select an installed writing model for broader revisions.')
    # Credit scenes cannot be edited or removed by these commands.
    result=creator.validate_script(scenes+credits,'research')
    return {'chapters':result,'options':options,'changes':changes,
            'warnings':['User-edited narration retains its previous source link; review factual claims before publishing.']}

class EditRequest(BaseModel):
    chapters:list[dict]=Field(min_length=1,max_length=120)
    instruction:str=Field(min_length=1,max_length=1000)

@router.post('/api/creator/research-edit')
def edit(body:EditRequest):
    try:return revise(body.chapters,body.instruction)
    except (ValueError,TypeError,KeyError) as exc:raise HTTPException(422,str(exc)[:300]) from exc
