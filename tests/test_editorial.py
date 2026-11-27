from pathlib import Path
import shutil
import subprocess
import pytest
from PIL import Image
import studio_editorial as ed
import studio_director as director
import studio_cinematic as cinema
import server
from test_scene_director import project


def test_marker_layout_preserves_words_and_fits():
    text='A carefully selected documentary highlight explains the evidence.'
    for w,h in [(960,540),(540,960),(540,540)]:
        layout=ed.marker_layout(text,w,h)
        assert ' '.join(x[0] for x in layout)==text
        assert 1<=sum(x[1] for x in layout)<=2
        assert all(0<x[2]-x[5]/2<x[2]+x[5]/2<w for x in layout)
    assert ed.emphasis(['the','and','a'])==set()


def test_document_role_explicit_focus_and_legacy_plugin():
    a={'id':'a'*32+'.png','name':'analysis.png','description':'actual evidence','role':'document','kind':'image','focus_point':[.9,.8]}
    lines=[{'text':'actual evidence','start':0,'end':4,'chapter_title':'Proof'}]
    p=director.make_plan(lines,4,[a],'doc',cinematic=True)
    assert p['scenes'][0]['editorial']=='evidence' and p['scenes'][0]['evidence_focus']==[.9,.8]
    legacy=director.make_plan(lines,4,[a],'plugin',cinematic=True)
    assert 'editorial' not in legacy['scenes'][0] and not legacy['scenes'][0].get('asset')
    p=director.make_plan(lines,4,[],'doc',cinematic=True,title_motion=True)
    assert p['scenes'][0]['editorial']=='chapter' and not p['scenes'][0].get('title_motion')


def test_editorial_evidence_crop_handles_edge_and_preserves_whole_source(tmp_path):
    src=Image.new('RGB',(100,200),'#3344cc')
    for w,h in [(960,540),(540,960)]:
        im=ed.artwork({'editorial':'evidence','evidence_focus':[1,1],'asset_name':'evidence.png'},w,h,src,director.font)
        assert im.size==(w,h)
        assert (51,68,204) in {color for _,color in im.getcolors(w*h)}


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_marker_real_render(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch)
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    r=c.post(f'/api/projects/{p.name}/director/render',json={'preset':'doc','cinematic_finish':True,'caption_style':'auto','preview':True});assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    plan=c.get(job['outputs']['plan']).json();assert plan['caption_style']=='marker'
    assert all(s.get('editorial')=='statement' for s in plan['scenes'])
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_audio'] and info['has_video'] and abs(info['duration']-4.2)<.13


def test_light_chapter_marker_uses_dark_text(tmp_path):
    p={'caption_style':'marker','scenes':[{'type':'big_text','editorial':'chapter','start':0,'captions':[{'text':'Read the source','start':0,'end':1}]}]}
    out=tmp_path/'caps.ass';cinema.write_kinetic_ass(p,960,540,out)
    text=out.read_text(encoding='utf-8-sig')
    assert r'\1c&H00191817&' in text and r'\3c&H00EAF0F1&' in text


@pytest.mark.skipif(not shutil.which('espeak') or not shutil.which('ffmpeg'),reason='local draft voice and FFmpeg required')
def test_creator_story_routes_to_documentary(tmp_path,monkeypatch):
    import json
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    c=TestClient(server.app)
    payload={'product':'Essay','story':'documentary','voice':'draft','preview':True,'chapters':[{'title':'Opening','narration':'Evidence matters. Show the source.'}]}
    r=c.post('/api/creator/create',data={'payload':json.dumps(payload)});assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    plan=c.get(job['outputs']['plan']).json()
    assert plan['preset']=='doc' and plan['caption_style']=='marker' and plan['transition_style']=='cut'


def test_explicit_chapter_is_not_replaced_by_auto_sourcing(tmp_path,monkeypatch):
    import studio_visual_sources as sources
    import studio_director_intelligence as intel
    lines=[{'text':'Read this chapter','start':0,'end':3,'chapter_title':'A new chapter'}]
    p=director.make_plan(lines,3,[],'doc',cinematic=True)
    monkeypatch.setattr(sources,'search',lambda *_:pytest.fail('Chapter must never be searched'))
    monkeypatch.setattr(intel,'generate_local',lambda *_:pytest.fail('Chapter must never generate an image'))
    sources.fill_missing(p,tmp_path,allow_network=True)
    intel.fill_generated(p,tmp_path,enabled=True)
    assert p['scenes'][0]['editorial']=='chapter' and not p['scenes'][0].get('asset')
