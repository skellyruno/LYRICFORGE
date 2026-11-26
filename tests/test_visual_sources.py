"""Fixture-backed network tests; no external requests in CI."""
import io
import json
import shutil
from pathlib import Path
import pytest
from PIL import Image
import studio_visual_sources as vs
import studio_director as director
from test_scene_director import project
import server


def payload(license='Public domain', *, url='https://upload.wikimedia.org/wikipedia/commons/thumb/a/b/Depth.png', required='false', restriction=''):
    return {'query':{'pages':[{'pageid':123,'title':'File:Depth signal.png','imageinfo':[{
        'thumburl':url,'descriptionurl':'https://commons.wikimedia.org/wiki/File:Depth_signal.png','mime':'image/png',
        'thumbwidth':960,'thumbheight':540,'extmetadata':{k:{'value':v} for k,v in {
          'LicenseShortName':license,'AttributionRequired':required,'Restrictions':restriction,'Artist':'<b>Test author</b>',
          'ImageDescription':'Depth changes the signal compare result'}.items()}}]}]}}


def fixture_bytes():
    buf=io.BytesIO(); Image.new('RGB',(960,540),'#3d576a').save(buf,format='PNG'); return buf.getvalue()


def plan():
    return director.make_plan([{'text':'Depth changes the signal','start':0,'end':4}],4,[],'plugin')


@pytest.mark.parametrize('license,required,restriction,url',[
    ('CC BY-SA 4.0','false','','https://upload.wikimedia.org/x'),
    ('Unknown','false','','https://upload.wikimedia.org/x'),
    ('Public domain','true','','https://upload.wikimedia.org/x'),
    ('Public domain','false','personality rights','https://upload.wikimedia.org/x'),
    ('Public domain','false','','http://upload.wikimedia.org/x'),
    ('Public domain','false','','https://upload.wikimedia.org.example.com/x'),
    ('Public domain','false','','https://upload.wikimedia.org@evil.example/x'),
])
def test_reject_ineligible_images(license,required,restriction,url):
    assert vs.candidates(payload(license,required=required,restriction=restriction,url=url),'depth signal')==[]


def test_only_meaningful_queries_and_metadata():
    assert vs.query_for({'captions':[{'text':'I am here and you know'}]})==''
    candidate=vs.candidates(payload(),'depth signal')[0]
    assert candidate['source']['creator']=='Test author'
    assert vs.candidates(payload(),'moon rover')==[]


def test_opt_in_download_reuse_and_provenance(tmp_path,monkeypatch):
    folder=tmp_path/'assets'; requests=[]
    def get(url,host,cap):
        requests.append((url,host,cap))
        return json.dumps(payload()).encode() if host=='commons.wikimedia.org' else fixture_bytes()
    monkeypatch.setattr(vs,'read_url',get)
    offline=vs.fill_missing(plan(),folder)
    assert offline['scenes'][0]['type']=='big_text' and not folder.exists() and not requests
    first=vs.fill_missing(plan(),folder,True)
    assert first['visual_sources']['downloaded']==1 and len(requests)==2
    scene=first['scenes'][0]; assert scene['type']=='broll' and scene['source']['license']=='Public domain'
    assert (folder/scene['asset']).is_file()
    second=vs.fill_missing(plan(),folder)
    assert second['visual_sources']['cached']==1 and len(requests)==2
    assert second['scenes'][0]['asset']==scene['asset']
    assert director.make_plan([{'text':'Depth signal','start':0,'end':4}],4,director.assets_for(folder),'plugin')['scenes'][0]['type']=='big_text'


def test_unavailable_network_falls_back_without_deleting_assets(tmp_path,monkeypatch):
    def fail(*args): raise TimeoutError('offline')
    monkeypatch.setattr(vs,'read_url',fail)
    result=vs.fill_missing(plan(),tmp_path/'assets',True)
    assert result['scenes'][0]['type']=='big_text'
    assert result['warnings'] and not (tmp_path/'assets').exists()


def test_bad_image_does_not_publish(tmp_path,monkeypatch):
    monkeypatch.setattr(vs,'read_url',lambda *args:b'invalid')
    candidate=vs.candidates(payload(),'depth signal')[0]
    with pytest.raises(OSError): vs.import_picture(tmp_path/'assets',candidate)
    assert not (tmp_path/'assets').exists()


def test_cancel_before_network(tmp_path,monkeypatch):
    def cancel(): raise RuntimeError('cancelled')
    monkeypatch.setattr(vs,'read_url',lambda *args:pytest.fail('network called after cancellation'))
    with pytest.raises(RuntimeError,match='cancelled'):vs.fill_missing(plan(),tmp_path/'assets',True,cancel)


@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_actual_auto_picture_render(tmp_path,monkeypatch):
    p,c=project(tmp_path,monkeypatch)
    calls=[]
    def get(url,host,cap):
        calls.append(host)
        return json.dumps(payload()).encode() if host=='commons.wikimedia.org' else fixture_bytes()
    monkeypatch.setattr(vs,'read_url',get)
    monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    route=f'/api/projects/{p.name}/director/render'
    r=c.post(route,json={'preset':'doc','preview':True,'auto_pictures':True}); assert r.status_code==200,r.text
    job=server.jobs[r.json()['job_id']];assert job['status']=='done',job
    final=c.get(job['outputs']['plan']).json();scene=final['scenes'][0]
    assert scene['source']['provider']=='Wikimedia Commons' and scene['type']=='broll'
    assert c.get(f'/api/projects/{p.name}/director/assets/{scene["asset"]}').status_code==200
    info=server.clips.probe_media(p/'director_preview.mp4');assert info['has_audio'] and info['has_video']
    r=c.post(route,json={'preset':'doc','preview':True});assert r.status_code==200,r.text
    assert len(calls)==2
    assert server.jobs[r.json()['job_id']]['outputs']['cached']>=1
    import os
    if os.getenv('LF_EVIDENCE'):
        shutil.copyfile(p/'director_preview.mp4',Path(os.environ['LF_EVIDENCE'])/'auto_picture_test.mp4')
        shutil.copyfile(p/'director_preview_plan.json',Path(os.environ['LF_EVIDENCE'])/'auto_picture_test_plan.json')


@pytest.mark.parametrize('damage', ['disabled', 'invalid_license', 'missing_name'])
def test_network_does_not_revive_rejected_cached_picture(tmp_path, monkeypatch, damage):
    folder = tmp_path / 'assets'
    requests = []
    def get(url, host, cap):
        requests.append(host)
        return json.dumps(payload()).encode() if host == 'commons.wikimedia.org' else fixture_bytes()
    monkeypatch.setattr(vs, 'read_url', get)
    first = vs.fill_missing(plan(), folder, True)
    key = first['scenes'][0]['asset']
    index_path = folder / 'index.json'
    index = json.loads(index_path.read_text())
    if damage == 'disabled':
        index[key]['disabled'] = True
    elif damage == 'invalid_license':
        index[key]['source']['license'] = 'Unknown'
    else:
        del index[key]['name']
    index_path.write_text(json.dumps(index))
    original = (folder / key).read_bytes()
    for online in (False, True):
        result = vs.fill_missing(plan(), folder, online)
        assert result['scenes'][0]['type'] == 'big_text'
        assert result['visual_sources']['downloaded'] == 0
    assert requests.count('upload.wikimedia.org') == 1
    assert (folder / key).read_bytes() == original
    assert json.loads(index_path.read_text()) == index


def test_disabled_during_picture_download_is_not_replaced(tmp_path, monkeypatch):
    folder = tmp_path / 'assets'
    folder.mkdir()
    item = vs.candidates(payload(), 'depth signal')[0]
    key = vs.hashlib.sha256(('commons:' + str(item['id'])).encode()).hexdigest()[:32] + '.jpg'
    def get(*args):
        (folder / key).write_bytes(b'existing')
        (folder / 'index.json').write_text(json.dumps({key: {
            'name': 'Disabled', 'source': item['source'], 'disabled': True
        }}))
        return fixture_bytes()
    monkeypatch.setattr(vs, 'read_url', get)
    with pytest.raises(ValueError):
        vs.import_picture(folder, item)
    assert (folder / key).read_bytes() == b'existing'
