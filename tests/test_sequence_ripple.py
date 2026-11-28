import pytest
import studio_sequence as seq
from test_studio_sequence import assets,visual,music

def put(s,a,op):return seq.apply(s,op,a)
def test_cut_splits_and_moves(assets):
    s=put(seq.initial(assets),assets,visual(30,120));s=put(s,assets,music())
    s=put(s,assets,{'op':'ripple','instruction':'cut 2 to 3'})
    assert s['base']['frames']==330
    rows=[x for x in s['layers'] if x['kind']=='visual'];assert [(x['at'],x['length'],x['offset']) for x in rows]==[(30,30,0),(60,60,60)]
    assert len(set(x['id'] for x in s['layers']))==len(s['layers'])
    m=[x for x in s['layers'] if x['kind']=='music'];assert [(x['at'],x['length'],x['offset']) for x in m]==[(0,60,0),(60,30,90)]
    assert s['ripple_report']
    assert [(x['fade_in'],x['fade_out']) for x in rows]==[(5,0),(0,5)]
def test_insert_and_compound_current_clock(assets):
    s=put(seq.initial(assets),assets,visual(60,45));s=put(s,assets,{'op':'ripple','instruction':'cut 0 to 1; insert city at 1 for 1 muted'})
    assert s['base']['frames']==360 and s['layers'][0]['at']==60
    s=put(s,assets,{'op':'ripple','instruction':'insert city at 2.5 for 1 muted'})
    assert [(x['at'],x['length'],x['offset']) for x in s['layers']]==[(60,15,0),(105,30,15)]
def test_replacement_keeps_layers(assets):
    s=put(seq.initial(assets),assets,visual(60));old=s['layers']
    s=put(s,assets,{'op':'ripple','instruction':'replace 1 to 3 with city keep audio'});assert s['layers']==old and s['base']['frames']==360

def test_undo_redo_and_sfx_source_offset(tmp_path,assets):
    store=seq.Store(tmp_path,assets);store.mutate(0,visual());store.mutate(1,{'op':'put','layer':{'id':'fx','kind':'sfx','at':120,'length':60,'effect':'impact'}})
    a=store.mutate(2,{'op':'ripple','instruction':'cut 4.5 to 5.5'})
    fx=[x for x in a['state']['layers'] if x['kind']=='sfx'];assert [(x['at'],x['length'],x['offset']) for x in fx]==[(120,15,0),(135,15,45)]
    assert store.mutate(3,{'op':'undo'})['state']['layers'][1]['length']==60
    assert store.mutate(4,{'op':'redo'})['state']['layers'][-1]['offset']==45

def test_transition_shift_and_remove(assets):
    s=put(seq.initial(assets),assets,{'op':'base','instruction':'cut 4 to 5'});s=put(s,assets,{'op':'transition','kind':'dip','at':120,'half':5})
    s=put(s,assets,{'op':'ripple','instruction':'cut 0 to 1'});assert s['transitions']==[{'kind':'dip','at':90,'half':5}]
    s=put(s,assets,{'op':'ripple','instruction':'insert city at 3 for 1 muted'});assert not s['transitions']
