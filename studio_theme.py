"""Optional production palette; never recolor imported footage, source text or audio."""
from __future__ import annotations

THEMES={
 'legacy':None,
 'clean':{'background':'#15181c','accent':'#e8bf55','ink':'#f4f4f2','muted':'#bac1c7','panel':'#ffffff','paper_bg':'#e8e7e3','paper_ink':'#20211f','paper_muted':'#5b5c58','highlight':'#ffe17b','shadow':'#c8c7c3'},
 'skelly_neon':{'background':'#08090b','accent':'#36ff17','ink':'#edf8e9','muted':'#a4b6a1','panel':'#152019','paper_bg':'#090f0b','paper_ink':'#edf8e9','paper_muted':'#acbba8','highlight':'#385e27','shadow':'#050805'},
 'skelly_bone':{'background':'#181713','accent':'#dac5a1','ink':'#f2e8d6','muted':'#c3b6a0','panel':'#eae0cd','paper_bg':'#292720','paper_ink':'#29251d','paper_muted':'#5e5548','highlight':'#ccb18a','shadow':'#11100e'},
}
TERMS={
 'ui_demo':'SKELL LAB / CONTROL STUDY',
 'diagram':'SKELL LAB / SIGNAL ANATOMY',
 'proof':'SKELL LAB / AUDIO PROOF',
 'evidence':'SKELL ARCHIVE / AUTHOR-SUPPLIED CLAIM',
 'big_text':'SKELL NOTES',
 'document':'SKELL ARCHIVE',
 'outro':'SKELL WORLD',
}
def validate(name):
    if not isinstance(name,str) or name not in THEMES:raise ValueError('Unknown production theme')
    return name

def palette(name):
    return THEMES[validate(name)]

def ass_color(rgb):
    return '&H00'+rgb[5:7]+rgb[3:5]+rgb[1:3]

def label(scene,default):
    return TERMS.get(scene.get('type'),default) if scene.get('skell_terminology') else default
