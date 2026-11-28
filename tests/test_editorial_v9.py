import numpy as np
from PIL import Image
import studio_continuity as continuity
import studio_director as director
import studio_product_motion as product
import studio_score as score

def scene(start,end,**kwargs):
    return {'start':start,'end':end,'frames':round((end-start)*60),'type':'broll','asset':'a'*32+'.mp4','chapter':1,'captions':[{'start':0,'end':1,'text':'word','words':[{'text':'word','start':0,'end':1}]}],**kwargs}

def test_join_contiguous_real_video_and_keep_caption_clock():
    a=scene(0,4,asset_start=2,editorial_seconds=4);b=scene(4,7,asset_start=6,editorial_seconds=3)
    s=continuity.connect([a,b],60)
    assert len(s)==1 and s[0]['frames']==420 and s[0]['editorial_seconds']==7
    assert s[0]['captions'][1]['words'][0]['start']==4 and a['frames']==240

def test_no_join_discontinuous_source_or_chapter():
    a=scene(0,4,asset_start=2,editorial_seconds=4);b=scene(4,7,asset_start=5,editorial_seconds=3)
    assert len(continuity.connect([a,b],60))==2
    b.update(asset_start=6,chapter=2);assert len(continuity.connect([a,b],60))==2

def test_product_motion_is_continuous_and_safe():
    img=Image.new('RGB',(400,220),'red');shot=product.ProductShot(img,640,360,{'start':0,'end':6},director.font)
    a=np.asarray(shot.render(0));b=np.asarray(shot.render(3));c=np.asarray(shot.render(5.9))
    assert np.mean(np.abs(a.astype(float)-b))>2 and np.mean(np.abs(b.astype(float)-c))>2
    assert not np.any(c[300:,:,0]>200)
    assert np.all(c[150,320]==[255,0,0])
    assert np.array_equal(c,np.asarray(shot.render(6)))

def test_doc_plan_uses_real_capture_motion_but_not_plugin_plan():
    a={'id':'a'*32+'.png','name':'editor workspace','kind':'image','role':'plugin_state','description':'editor workspace'}
    l=[{'text':'editor workspace','start':0,'end':4,'chapter_title':'Workspace'}]
    assert director.make_plan(l,4,[a],'doc',cinematic=True,fps=60)['scenes'][0]['product_motion']
    assert not director.make_plan(l,4,[a],'plugin',cinematic=True)['scenes'][0].get('product_motion')

def test_musical_development_bounded_and_chunk_consistent():
    t=np.arange(24000*12,dtype=float)/24000
    a=score.music_block(t,18);b=np.vstack([score.music_block(t[i:i+24000],18) for i in range(0,len(t),24000)])
    assert np.max(np.abs(a-b))<1e-5 and np.max(np.abs(a))<.45
    assert np.sqrt(np.mean(a[144000:192000]**2))>np.sqrt(np.mean(a[:48000]**2))

def test_semantic_replacement_cannot_inherit_capture_provenance(monkeypatch,tmp_path):
    import studio_director_intelligence as intel
    a={'id':'a'*32+'.png','kind':'image','name':'capture','role':'plugin_state'};b={'id':'b'*32+'.png','kind':'image','name':'photo','role':'broll'}
    s=scene(0,4);s.update(asset=a['id'],asset_role='plugin_state',product_motion=True,editorial_footage_label='ACTUAL CAPTURE')
    p={'scenes':[s],'preset':'doc','cinematic_finish':True}
    monkeypatch.setattr(intel,'semantic_scores',lambda *args:{'word':{a['id']:0.,b['id']:1.}})
    intel.apply_semantic(p,tmp_path,[a,b]);assert s['asset']==b['id'] and s['asset_role']=='broll' and 'product_motion' not in s and 'editorial_footage_label' not in s

def test_no_join_video_without_verified_trim_window():
    assert len(continuity.connect([scene(0,3),scene(3,6)],60))==2
