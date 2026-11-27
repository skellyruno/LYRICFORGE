"""Network and actual local-model verification, with explicit evidence status."""
import argparse,json,sys,time
from pathlib import Path
from urllib.request import urlopen
import studio_research_compose as compose
import studio_topic_research as basic
import studio_visual_sources as visuals

def network(out):
    report={}
    def save():Path(out).write_text(json.dumps(report,indent=2),encoding='utf-8')
    def check(name,fn):
        try:
            value=fn()
            report[name]={'status':'passed' if value else 'no_results','result':value}
        except Exception as exc:
            report[name]={'status':'failed','error':type(exc).__name__+': '+str(exc)[:180]}
        save()
    topic='Photosynthesis'
    check('wikipedia',lambda:{k:v for k,v in basic.source(topic).items() if k!='extract'})
    check('crossref',lambda:compose.bibliography(topic))
    check('europe_pmc',lambda:[{k:v for k,v in x.items() if k!='extract'} for x in compose.abstracts(topic)])
    check('commons_video_candidates',lambda:[{'title':x['title'],'source':x['source']} for x in visuals.video_search('Earth orbit')])
    check('commons_images',lambda:[{'title':x['title'],'source':x['source']} for x in visuals.search('Earth orbit')])
    def combined():
        d=compose.compose(topic,45)
        return {'chapters':len(d['chapters']),'source_links':d['sources'],'warnings':d['warnings'],'estimated_seconds':d['estimated_seconds']}
    check('combined',combined)
    print(json.dumps(report,indent=2))
    if any(report[k]['status']!='passed' for k in ('wikipedia','crossref','combined')):
        raise RuntimeError('Live core source verification did not pass')

def model(out,name):
    a={'id':'A1','kind':'article','title':'Pitch correction','revision':123,'url':'https://en.wikipedia.org/w/index.php?oldid=123','extract':'Pitch correction changes the pitch of a recorded audio signal. Engineers use it to correct inaccurate vocal notes. It may also be used as a creative effect.'}
    def fixture(topic,focus):return [a],[]
    report={'model':name,'source_fixture':True,'actual_inference':False}
    def save():Path(out).write_text(json.dumps(report,indent=2),encoding='utf-8')
    with urlopen('http://127.0.0.1:11434/api/tags',timeout=20) as response:
        report['installed_models']=json.load(response).get('models',[])
    save()
    first=compose.compose('Pitch correction',30,model=name,gather=fixture)
    report['initial']=first;save()
    second=compose.compose('Pitch correction',30,model=name,instruction='Make the opening more concise and use an energetic delivery in square format.',prior=first['chapters'],gather=fixture)
    report['revision']=second;report['actual_inference']=True;save()
    if second['options'].get('format')!='square' or second['options'].get('delivery')!='energetic':
        raise RuntimeError('Actual model did not follow supported revision controls')
    report['passed']=True;save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['network','model']);p.add_argument('out');p.add_argument('--model',default='qwen2.5:1.5b');a=p.parse_args()
    if a.mode=='network':network(a.out)
    else:model(a.out,a.model)
