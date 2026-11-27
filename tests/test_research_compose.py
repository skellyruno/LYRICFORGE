import pytest
from studio_research_compose import compose, collect, model_chapters
import studio_visual_sources as visuals

A={'title':'Pitch correction','url':'https://en.wikipedia.org/w/index.php?oldid=123','revision':123,'extract':'Pitch correction adjusts the pitch of recorded audio signals. It enables engineers to repair inaccurate notes in vocal performances. Pitch correction can be used creatively in musical recording and production.'}
B={'title':'Pitch correction history','url':'https://en.wikipedia.org/w/index.php?oldid=456','revision':456,'extract':'Pitch correction history includes early analog recording equipment. Pitch correction became more accessible when digital signal processing was introduced. Recording engineers use pitch correction in many musical styles.'}
P={'title':'Pitch correction study','url':'https://doi.org/10.1234/test','kind':'bibliography','year':2024}
def gathered(topic,focus):return collect(topic,focus,wiki=lambda q:B if 'history' in q or 'applications' in q else A,papers=lambda q:[P],scholarly=lambda q:[])
def test_multiple_sources_and_bibliography():
    d=compose('Pitch correction',90,gather=gathered)
    assert len(d['sources'])==3
    assert {c['source_url'] for c in d['chapters']}=={A['url'],B['url']}
    assert not any(c['source_url']==P['url'] for c in d['chapters'])
def test_revision_model_options_and_evidence():
    def writer(model,topic,seconds,evidence,instruction,prior):
        assert instruction=='Change the ending' and prior
        return {'chapters':[{'title':'Recording','narration':'Pitch correction adjusts pitch.','evidence_id':'A1'}],'format':'square','delivery':'energetic','sound_design':False,'command':'never execute'}
    d=compose('Pitch correction',60,model='local',instruction='Change the ending',prior=[{'narration':'Prior'}],gather=gathered,writer=writer)
    assert d['options']=={'format':'square','delivery':'energetic','sound_design':False}
    assert d['chapters'][0]['source_url']==A['url']
def test_invalid_model_citation():
    e,_=gathered('Pitch correction','')
    with pytest.raises(ValueError):model_chapters({'chapters':[{'narration':'Claim','evidence_id':'P1'}]},e)
def test_video_rejects_unknown_license(monkeypatch):
    import json
    p={'query':{'pages':[{'pageid':1,'title':'File:Pitch correction video','imageinfo':[{'mime':'video/webm','url':'https://upload.wikimedia.org/test.webm','descriptionurl':'https://commons.wikimedia.org/wiki/File:test','size':20000,'extmetadata':{'LicenseShortName':{'value':'CC BY'}}}]}]}}
    monkeypatch.setattr(visuals,'read_url',lambda *a:json.dumps(p).encode())
    assert visuals.video_search('pitch correction')==[]
    p['query']['pages'][0]['imageinfo'][0]['extmetadata']['LicenseShortName']['value']='CC0'
    assert len(visuals.video_search('pitch correction'))==1

def test_import_and_render_video(tmp_path,monkeypatch):
    import shutil,subprocess
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    import server
    from test_scene_director import project
    import studio_director as director
    p,c=project(tmp_path,monkeypatch)
    video=tmp_path/'visual.webm'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=24:d=3','-c:v','libvpx-vp9','-an',str(video)],check=True,timeout=90)
    folder=server.director_folder(p.name)
    item={'id':123,'url':'https://upload.wikimedia.org/test.webm','ext':'.webm','title':'Depth signal','source':{'provider':'Wikimedia Commons','page':'https://commons.wikimedia.org/wiki/File:test','license':'CC0','query':'depth signal'}}
    monkeypatch.setattr(visuals,'read_url',lambda *a:video.read_bytes())
    key,_=visuals.import_video(folder,item)
    assert (folder/key).is_file()
    assert director.assets_for(folder)[0]['kind']=='video'
    monkeypatch.setattr(visuals,'query_for',lambda scene:'depth signal')
    monkeypatch.setattr(server.executor,'submit',lambda fn,*a:fn(*a))
    r=c.post(f'/api/projects/{p.name}/director/render',json={'preset':'doc','preview':True})
    assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    plan=c.get(job['outputs']['plan']).json()
    assert any(s.get('asset')==key and s['type']=='broll' for s in plan['scenes'])
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_audio'] and info['has_video']


def test_open_abstract_license(monkeypatch):
    import json,studio_research_compose as rc
    data={'resultList':{'result':[{'isOpenAccess':'Y','license':'cc by','pmcid':'PMC123','title':'Pitch correction study','authorString':'Example authors','abstractText':'Pitch correction research '+('tests and results '*30)}]}}
    monkeypatch.setattr(visuals,'read_url',lambda *a:json.dumps(data).encode())
    assert rc.abstracts('Pitch correction')[0]['abstract_only']
    data['resultList']['result'][0]['license']='cc by nc'
    assert rc.abstracts('Pitch correction')==[]
