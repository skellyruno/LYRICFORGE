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


# Explicit settings already supported by the real uploaded-video editor.
VIDEO_SWITCHES={'trim_silence','loudness','watermark','endcard','captions','sfx','callouts','chapter_titles','music','intro_outro','intro_card','broll'}
VIDEO_ENUMS={'zoom':['off','subtle','medium','strong'],'resolution':['720p','1080p'],'voice_cleanup':['off','light','medium','strong'],'fillers':['off','basic','more'],'zoom_mode':['motion','ui']}
VIDEO_LABELS={'silence':'trim_silence','dead air':'trim_silence','silence removal':'trim_silence','loudness':'loudness','normalization':'loudness','watermark':'watermark','end card':'endcard','captions':'captions','subtitles':'captions','sound effects':'sfx','callouts':'callouts','chapter titles':'chapter_titles','music':'music','background music':'music','intro and outro':'intro_outro','title card':'intro_card','b-roll':'broll'}

def validate_video_settings(value):
    fields=VIDEO_SWITCHES|set(VIDEO_ENUMS)|{'shorts'}
    if not isinstance(value,dict) or set(value)!=fields:raise ValueError('Invalid video settings')
    if any(type(value[k]) is not bool for k in VIDEO_SWITCHES):raise ValueError('Invalid editing switch')
    if any(not isinstance(value[k],str) or value[k] not in choices for k,choices in VIDEO_ENUMS.items()):raise ValueError('Invalid editing option')
    if type(value['shorts']) is not int or value['shorts'] not in (0,1,3,5):raise ValueError('Unsupported Shorts count')
    return dict(value)

def direct_video_settings(current,instruction):
    result=validate_video_settings(current)
    clauses=[s.strip().casefold().rstrip('.') for s in re.split(r'[;\n]+',instruction) if s.strip()]
    if not clauses or len(clauses)>12:raise ValueError('Enter up to 12 edits separated by semicolons')
    for text in clauses:
        match=re.fullmatch(r'(?:turn |set )?(.+?) (on|off)',text)
        if match and match[1] in VIDEO_LABELS:
            result[VIDEO_LABELS[match[1]]]=match[2]=='on';continue
        match=re.fullmatch(r'(add|enable|remove|disable) (.+)',text)
        if match and match[2] in VIDEO_LABELS:
            result[VIDEO_LABELS[match[2]]]=match[1] in ('add','enable');continue
        if text in ('remove silence','trim silence','trim dead air'):result['trim_silence']=True;continue
        if text in ('keep silence','keep dead air'):result['trim_silence']=False;continue
        match=re.fullmatch(r'(?:set |change )?(zoom|voice cleanup|resolution|fillers|zoom mode) (?:to )?([a-z0-9]+)',text)
        if match:
            key=match[1].replace(' ','_')
            if match[2] in VIDEO_ENUMS[key]:result[key]=match[2];continue
        match=re.fullmatch(r'(?:make |shorts )?(0|1|3|5)(?: shorts)?',text)
        if match:result['shorts']=int(match[1]);continue
        if text in ('no shorts','skip shorts'):result['shorts']=0;continue
        if text in ('remove filler words','cut filler words'):result['fillers']='basic';continue
        if text in ('keep filler words','keep fillers'):result['fillers']='off';continue
        raise ValueError('Unsupported direct video edit: '+text[:100]+'. Select a local writing model for broader instructions.')
    return result

def suggest_video_settings(current,instruction,model=''):
    current=validate_video_settings(current)
    if not instruction.strip():raise ValueError('Enter an editing instruction')
    if model:
        from studio_research_compose import MODEL_NAME,ollama_json
        import json
        if not MODEL_NAME.fullmatch(model):raise ValueError('Select an installed writing model')
        props={k:{'type':'boolean'} for k in sorted(VIDEO_SWITCHES)}
        props.update({k:{'type':'string','enum':v} for k,v in VIDEO_ENUMS.items()})
        props['shorts']={'type':'integer','enum':[0,1,3,5]}
        schema={'type':'object','additionalProperties':False,'properties':props,'required':list(props)}
        payload={'model':model,'stream':False,'format':schema,'options':{'temperature':0,'num_predict':600,'num_ctx':4096},
                 'messages':[{'role':'system','content':'Translate editing requests into the available video settings. Copy every existing setting unless explicitly asked to change it. Only return the complete JSON settings object; never execute commands. Unsupported requests leave settings unchanged.'},{'role':'user','content':json.dumps({'current':current,'request':instruction})}]}
        response=ollama_json('/api/chat',payload,timeout=120)
        try:result=validate_video_settings(json.loads(response['message']['content']))
        except (ValueError,TypeError,KeyError,AttributeError) as exc:raise ValueError('Model did not return valid video settings') from exc
    else:result=direct_video_settings(current,instruction)
    changes=[{'setting':k,'before':current[k],'after':result[k]} for k in sorted(result) if current[k]!=result[k]]
    if not changes:raise ValueError('No supported settings changed. Try a more specific instruction.')
    return {'settings':result,'changes':changes}

class VideoEditRequest(BaseModel):
    current:dict
    instruction:str=Field(min_length=1,max_length=1000)
    model:str=Field(default='',max_length=120)

@router.post('/api/creator/video-edit-instruction')
def video_instruction(body:VideoEditRequest):
    try:return suggest_video_settings(body.current,body.instruction,body.model)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:raise HTTPException(422,str(exc)[:300]) from exc
