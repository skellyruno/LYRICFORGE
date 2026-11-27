import pytest
from PIL import Image
import studio_director as director
import studio_editorial as editorial
import studio_creator as creator

def test_both_director_paths():
    lines=[{'text':'Measured evidence','start':0.,'end':3.,'chapter_title':'Evidence'}]
    doc=director.make_plan(lines,3.,[],'doc',cinematic=True)
    assert doc['editorial_engine']=='v20' and doc['scenes'][0]['editorial']=='chapter'
    research=director.make_plan(lines,3.,[],'doc',cinematic=True,editorial_style='reference',visual_theme='clean')
    assert research.get('editorial_engine') is None and research['visual_theme']=='clean'
    plugin=director.make_plan(lines,3.,[],'plugin',cinematic=True,visual_theme='skelly_neon')
    assert plugin.get('editorial_engine') is None and plugin['visual_theme']=='skelly_neon'
    music=director.make_plan(lines,3.,[],'music')
    assert music.get('editorial_engine') is None
    assert sum(s['frames'] for s in doc['scenes'])==doc['frames']

def test_editorial_primitives_and_creator_evidence_coexist():
    assert editorial.marker_layout('Read the source',960,540)
    assert callable(editorial.artwork) and callable(editorial.evidence_card)
    assert callable(director.configure_spatial)

def test_no_implicit_draft_when_explicitly_disallowed(monkeypatch):
    monkeypatch.setattr(creator,'voice_options',lambda:{'draft':True})
    with pytest.raises(ValueError):creator.resolve_voice('auto',allow_draft=False)
    assert creator.resolve_voice('draft',allow_draft=False)=='draft'
