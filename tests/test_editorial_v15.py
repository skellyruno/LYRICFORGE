import json,shutil,subprocess
from copy import deepcopy
import numpy as np
import pytest
from PIL import Image
import studio_layers as layers
import studio_mesh as mesh
import studio_director as d
import studio_quality as quality
import studio_media_layers as media
import studio_storyboard as sb
from studio_instrument_score import arrange,arrange_arc
from studio_score import CHORDS,DOC_BPM
from examples.polished_films import rounded_cube_mesh,polish
from examples.sound_documentary import plan_for


def test_mesh_geometry_texture_and_morph():
    spec=rounded_cube_mesh();assert len(spec['vertices'])==216 and len(spec['faces'])==300
    tex=np.zeros((64,64,3),np.uint8);tex[:,:32]=[230,85,40];tex[:,32:]=[25,160,190]
    m=mesh.Mesh(spec,Image.fromarray(tex));a=np.array(m.render(180,180,.45,0));b=np.array(m.render(180,180,.45,1))
    assert a.shape==b.shape==(180,180,4);assert np.count_nonzero(a[:,:,3])>2000 and np.count_nonzero(b[:,:,3])>1000
    assert np.mean(np.abs(a.astype(float)-b.astype(float)))>3;assert np.all(a[[0,-1],:,3]==0)
    assert np.array_equal(a,np.array(m.render(180,180,.45,0)))
    assert len(mesh.validate_mesh({'vertices':[[0,0,0],[1,0,0],[0,1,0]],'uv':[[0,0],[1,0],[0,1]],'faces':[[0,1,2]]})['faces'])==1

@pytest.mark.parametrize('change',['nan','badface','target','uv','degenerate'])
def test_bad_mesh(change):
    m=rounded_cube_mesh(2)
    if change=='nan':m['vertices'][0][0]=float('nan')
    elif change=='badface':m['faces'][0][0]=999
    elif change=='target':m['target'].pop()
    elif change=='uv':m['uv'][0][0]=-1
    elif change=='degenerate':m['vertices'][m['faces'][0][0]]=m['vertices'][m['faces'][0][1]].copy()
    with pytest.raises(ValueError):mesh.validate_mesh(m)


def test_motion_curve_monotone_and_continuous():
    k=[[0,0],[.35,.3],[.7,.8],[1,1]];v=np.array([layers.sample(k,x,'continuous')[0] for x in np.linspace(0,1,2001)])
    assert v[0]==0 and v[-1]==1 and np.min(np.diff(v))>=-1e-8
    h=1e-5;a=layers.sample(k,.35-h,'continuous')[0];b=layers.sample(k,.35,'continuous')[0];c=layers.sample(k,.35+h,'continuous')[0];assert abs((b-a)/h-(c-b)/h)<.001


def test_layout_repair_preserves_text_and_opt_out():
    p={'fps':30,'scenes':[{'frames':90,'graphic':{'kind':'composition','title':'Test','source':'Fixture','layers':[{'id':'text','type':'text','text':'VISIBLE TEXT','width':.4,'height':.16,'track':[[0,.06,.5,1,1],[1,.06,.5,1,1]]}]}}]}
    baseline=deepcopy(p);r=quality.repair_layout(p,(640,360),d.font);assert not r['corrections'] and p==baseline
    p['auto_repair_layout']=True;r=quality.repair_layout(p,(640,360),d.font)
    assert r['before']==1 and r['after']==0 and r['corrections'];assert p['scenes'][0]['graphic']['layers'][0]['text']=='VISIBLE TEXT';assert p['scenes'][0]['frames']==90


def test_competing_storyboards_and_no_original_mutation():
    from studio_auto_composition import plan
    a=[{'id':'a'*32+'.png','name':'Camera image source','description':'camera image comparison','kind':'image','role':'document','features':{'width':1920,'height':1080}}, {'id':'b'*32+'.png','name':'Camera image crop','description':'camera image comparison','kind':'image','role':'broll','features':{'width':400,'height':800}}]
    g=plan('Compare camera image','camera image comparison','Comparison',a,d.terms,5);r=g['storyboard'];assert len(r['candidates'])==4;assert r['selected']==r['candidates'][0]['name'];assert r['candidates'][0]['score']>=r['candidates'][-1]['score'];assert {l.get('asset') for l in g['layers'] if l.get('asset')}=={x['id'] for x in a}


def test_original_arrangement_has_development_and_bounded_events():
    x=arrange_arc(45,DOC_BPM,CHORDS,24000);assert x!=arrange(45,DOC_BPM,CHORDS,24000)
    assert x==sorted(x) and all(0<=a<=45*24000 and 0<=p<=127 and 0<=v<=127 for a,o,c,p,v in x)
    early={c for a,o,c,p,v in x if o and a<3*24000};middle={c for a,o,c,p,v in x if o and 20*24000<a<30*24000};assert len(middle)>len(early)


def test_director_edition_preserves_duration_and_original():
    p=plan_for();before=deepcopy(p);q=polish(p,'sound');assert p==before and q['frames']==2700 and q['score_arc']=='cinematic';assert q['auto_repair_layout'];assert q['scenes'][0]['graphic']['layers'][-1]['text']=='FIELD NOTES  /  01'

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_60fps_media_preserves_native_frame_clock(tmp_path):
    key='b'*32+'.mp4';subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=60','-t','1','-c:v','libx264','-threads','1',str(tmp_path/key)],check=True)
    l={'asset':key,'type':'footage','trim':[0,1],'delay':0}
    with media.MediaBank(tmp_path,60) as bank:
        a=bank.frame(l,0);b=bank.frame(l,1/60);assert len(next(iter(bank.strips.values())))==60;assert not np.array_equal(a,b)


def test_new_documentary_score_default_without_changing_plugins():
    lines=[{'start':0,'end':4,'text':'Explain this image.'}]
    assert d.make_plan(lines,4,[],'doc',cinematic=True)['score_arc']=='cinematic'
    assert 'score_arc' not in d.make_plan(lines,4,[],'plugin',cinematic=True)
    assert 'score_arc' not in d.make_plan(lines,4,[],'doc',cinematic=False)
