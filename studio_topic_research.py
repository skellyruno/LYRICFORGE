"""Topic-only, attributed public-source video drafts. No API key or invented facts."""
from __future__ import annotations
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import studio_creator as creator

router = APIRouter()
LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/4.0/'
API = 'https://en.wikipedia.org/w/api.php'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected source redirect')

def request(params):
    url = API + '?' + urlencode({'format':'json','formatversion':2,**params})
    req = Request(url, headers={'User-Agent':'SkellyMotion/0.9 (https://github.com/skellyruno/LYRICFORGE; topic research)', 'Accept':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=12) as response:
        data = response.read(1024*1024+1)
    if len(data)>1024*1024: raise ValueError('Source response too large')
    result = json.loads(data)
    if result.get('error'): raise ValueError('Public source search unavailable')
    return result

def terms(text):
    return set(re.findall(r'\b[a-z0-9]{3,}\b',text.casefold()))-{'the','and','for','with','about','from','what','how','does','make','video','research','into'}

def source(topic, get=request):
    hits = get({'action':'query','list':'search','srsearch':topic,'srlimit':5,'srnamespace':0}).get('query',{}).get('search',[])
    ids = [str(h['pageid']) for h in hits if isinstance(h.get('pageid'),int)][:5]
    if not ids: raise ValueError('No public article matched this topic. Try a more specific topic.')
    for pid in ids[:3]:
        pages = get({'action':'query','pageids':pid,'prop':'extracts|revisions|pageprops','explaintext':1,'exsectionformat':'wiki','rvprop':'ids','rvlimit':1}).get('query',{}).get('pages',[])
        for p in pages:
            if str(p.get('pageid'))!=pid or 'disambiguation' in p.get('pageprops',{}): continue
            title = creator.clean(p.get('title'),80); extract=p.get('extract',''); revisions=p.get('revisions',[])
            if not title or not isinstance(extract,str) or not revisions: continue
            rev=revisions[0].get('revid')
            if not isinstance(rev,int) or rev<=0 or len(extract.split())<20: continue
            if not terms(topic)&terms(title+' '+extract[:3000]): continue
            return {'title':title,'url':f'https://en.wikipedia.org/w/index.php?oldid={rev}','revision':rev,'extract':extract[:40000]}
    raise ValueError('No sufficiently relevant article was found. Try a clearer topic.')

def draft(topic, seconds=60, focus='', *, get=request):
    topic=creator.clean(topic,80); focus=creator.clean(focus,160)
    if not topic: raise ValueError('Enter a research topic')
    page=source(topic,get)
    sections=[]; heading=page['title']
    for line in page['extract'].splitlines():
        line=line.strip()
        if not line: continue
        h=re.fullmatch(r'=+\s*(.*?)\s*=+',line)
        if h:
            heading=creator.clean(h.group(1),80)
            if heading.casefold() in {'references','see also','external links','further reading','notes','bibliography','sources'}: break
            continue
        if len(line.split())>=8: sections.append((heading,line))
    if not sections: raise ValueError('Source lacks usable narration')
    if focus:
        query=terms(focus)
        if not query: raise ValueError('Specify a concrete focus, such as an application or historical period')
        relevant=[x for x in sections if query&terms(x[0]+' '+x[1])]
        if not relevant: raise ValueError('The retrieved article does not support that focus. Try a more specific topic.')
        sections=relevant
    budget=max(25,round(seconds*2.1)-15); used=0; chapters=[]
    for heading,paragraph in sections:
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])',paragraph):
            sentence=creator.clean(re.sub(r'\[\d+\]','',sentence),2000)
            n=len(sentence.split())
            if not n or len(sentence)>1200 or n>100: continue
            if used+n>budget and chapters: break
            chapters.append({'title':heading,'narration':sentence,'visual_hint':heading,'source_url':page['url']})
            used+=n
            if used>=budget or len(chapters)>=18: break
        if used>=budget or len(chapters)>=18 or (chapters and used>=budget*.8): break
    if not chapters: raise ValueError('Insufficient supported material')
    grouped=[]
    for c in chapters:
        if grouped and grouped[-1]['title']==c['title'] and len((grouped[-1]['narration']+' '+c['narration']).split())<=55 and len(grouped[-1]['narration'])+len(c['narration'])<1199:
            grouped[-1]['narration']+=' '+c['narration']
        else: grouped.append(dict(c))
    grouped.append({'title':'Sources and credits','narration':f'Source: Wikipedia contributors, {page["title"]}. Text adapted under Creative Commons Attribution Share Alike 4.0. See the scene plan for the article revision.','visual_hint':'Source credits','source_url':page['url']})
    rows=creator.validate_script(grouped,'research')
    return {'product':page['title'],'chapters':rows,'source':{k:v for k,v in page.items() if k!='extract'},'license_url':LICENSE_URL,'estimated_seconds':round(sum(len(c['narration'].split()) for c in rows)/2.35,1),'warnings':['Single encyclopedia source; review factual claims before publishing. Text-based motion graphics are illustrative, not real event footage.']}

class TopicRequest(BaseModel):
    topic: str = Field(min_length=1,max_length=80)
    target_seconds: int = Field(default=60,ge=15,le=180)
    focus: str = Field(default='',max_length=160)

@router.post('/api/creator/research-topic')
def research_topic(body: TopicRequest):
    try: return draft(body.topic,body.target_seconds,body.focus)
    except ValueError as exc: raise HTTPException(422,str(exc)[:300]) from exc
    except (OSError,TimeoutError) as exc: raise HTTPException(503,'Public research source is unavailable. Check your internet connection and retry.') from exc
