import numpy as np
import pytest
from PIL import Image
import studio_layers as l
import studio_story as story
import studio_reference as ref
import studio_editorial_motion as em
import studio_director as d
import studio_creator as creator

def spec():
    return {'kind':'composition','title':'Test','source':'Authored test','layers':[{'id':'line','type':'wave','width':.7,'height':.24,'color':'mint','track':[[0,.5,.4,1,1],[1,.5,.6,1,1]]},{'id':'text','type':'text','text':'Signal','width':.8,'height':.18,'track':[[0,.5,.20,1,0],[1,.5,.20,1,1]]}]}

def test_composition_schema_and_determinism():
    a=em.validate_graphic(spec());assert a==em.validate_graphic(a)
    assert creator.validate_script([{'title':'Test','narration':'Look at the signal.','graphic':a}])[0]['graphic']==a
    s=l.Composition(a,640,360,5,d.font);assert np.array_equal(s.render(2),s.render(2));assert not np.array_equal(s.render(0),s.render(4))
    assert l.sample([[0,0],[1,1]],.5)==[.5]
    assert l.sample([[.3,.1],[.8,.9]],0)==[.1]

@pytest.mark.parametrize('bad',['duplicate','unsorted','nan','too_many','invalid_spectrum','color'])
def test_invalid_composition(bad):
    g=spec()
    if bad=='duplicate':g['layers'].append(g['layers'][0])
    elif bad=='unsorted':g['layers'][0]['track'].reverse()
    elif bad=='nan':g['layers'][0]['depth']=float('nan')
    elif bad=='too_many':g['layers']*=17
    elif bad=='invalid_spectrum':g['layers'][0].update(type='spectrum',values=[{'label':'a','value':1.1},{'label':'b','value':.2}])
    else:g['layers'][0]['color']='javascript:alert(1)'
    with pytest.raises(ValueError):l.validate(g)

@pytest.mark.parametrize('size',[(640,360),(360,640)])
def test_all_primitives_and_portrait(size):
    g=spec();g['layers']+=[{'id':'primitive-'+k,'type':k,'width':.45,'height':.18,'text':'440 Hz  1.00','label':'FFT','values':[{'label':'440 Hz','value':1},{'label':'880 Hz','value':.5}]} for k in ['paper','particles','spectrum','surface','samples','rings','line']]
    shot=l.Composition(g,*size,4,d.font);im=shot.render(3);assert im.size==size and im.mode=='RGB';assert np.asarray(im).max()>180

def test_shared_identity_transition_endpoints_and_positions():
    old=spec();new=spec();new['layers'][0]['track']=[[0,.7,.6,1,1],[1,.7,.6,1,1]];new['layers'][1]['text']='Next'
    a=l.Composition(old,640,360,4,d.font,0);b=l.Composition(new,640,360,4,d.font,4)
    assert np.array_equal(a.render(4),b.bridge(a,0,1));assert np.array_equal(b.render(1),b.bridge(a,1,1))
    assert not np.array_equal(b.bridge(a,.5,1),a.render(4))
    assert a._states(4)['line'][1][:2]==[.5,.6] and b._states(0)['line'][1][:2]==[.7,.6]

def test_story_annotation_bounded_and_affects_only_relevant_media():
    n=[{'time':0,'role':'hook','technique':'footage'},{'time':3,'role':'evidence','technique':'document'},{'time':5,'role':'explanation','technique':'diagram'}];p={'story_grammar':story.grammar(n)}
    assert p['story_grammar']['role_transitions']=={'hook>evidence':1,'evidence>explanation':1}
    assert story.bonus(p,'evidence',{'role':'document','kind':'image'})>.5
    assert story.bonus(p,'hook',{'role':'document','kind':'image'})==0
    with pytest.raises(ValueError):story.grammar(list(reversed(n)))
    lines=[{'start':0,'end':4,'text':'Show the source document as evidence','visual_hint':'source document'}]
    plan=d.make_plan(lines,4,[],'doc',cinematic=True,reference_profile=p)
    assert plan['scenes'][0]['narrative_role']=='evidence'

def test_new_documentary_is_original_and_has_correct_fft():
    from examples.sound_documentary import plan_for,data
    p=plan_for();assert p['duration']==45 and p['frames']==2700;assert len(p['scenes'])==5
    assert sum(s['frames'] for s in p['scenes'])==2700
    assert data()==[{'label':'440 Hz','value':1.0},{'label':'880 Hz','value':.5},{'label':'1320 Hz','value':.25}]
    assert all(not s.get('asset') for s in p['scenes'])
