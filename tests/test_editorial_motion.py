import hashlib, json, math, shutil, wave
from pathlib import Path
import pytest
import numpy as np
from PIL import Image,ImageChops
import studio_creator as creator
import studio_director as director
import studio_editorial_motion as motion
import studio_visual_sources as sources
import studio_director_intelligence as intel
import studio_voice
import server

CHART={'kind':'chart','title':'Matched excerpts','source':'Verified test report','unit':'s','items':[{'label':'Dry','value':3},{'label':'Wet','value':3}]}
TIMELINE={'kind':'timeline','title':'Historical dates','source':'Author supplied dates','items':[{'label':'First capture','date':'Nov 23, 2026'},{'label':'Second capture','date':'Nov 26, 2026'}]}

@pytest.mark.parametrize('shape',[(960,540),(540,960),(540,540)])
@pytest.mark.parametrize('g',[CHART,TIMELINE,{'kind':'quote','title':'Quotation','source':'Original source','quote':'Read the original source and check the facts.'},{'kind':'process','title':'Workflow','source':'Author supplied sequence','items':[{'label':'Import'},{'label':'Edit'},{'label':'Export'}]}])
def test_graphic_animates_and_respects_shape(shape,g):
    shot=motion.EditorialShot({'editorial':'graphic','graphic':g,'start':0,'end':4},*shape,None,director.font)
    a,b=shot.render(.05),shot.render(2.8)
    assert a.size==b.size==shape and ImageChops.difference(a,b).getbbox()

@pytest.mark.parametrize('v',[-1,float('nan'),float('inf'),True,'3'])
def test_bad_chart_rejected(v):
    with pytest.raises(ValueError):motion.validate_graphic({**CHART,'items':[{'label':'A','value':v},{'label':'B','value':3}]})

def test_evidence_moves_and_retains_source():
    im=Image.new('RGB',(600,400),'#3155cf')
    shot=motion.EditorialShot({'editorial':'evidence','asset_name':'Source.png','evidence_focus':[.9,.8],'start':0,'end':4},960,540,im,director.font)
    a,b=shot.render(.7),shot.render(3.0)
    assert ImageChops.difference(a,b).getbbox() and (49,85,207) in {color for _,color in b.getcolors(960*540)}
    assert shot.crop_rect[0]+shot.crop_rect[2]<=im.width

def test_graphic_cues_preserved_and_do_not_autosource(tmp_path,monkeypatch):
    script=creator.validate_script([{'title':'Compare','narration':'Three seconds on each side.','graphic':CHART}]);assert script[0]['graphic']==CHART
    lines,_=studio_voice.recording_lines(script,3,[],creator.split_phrases);assert lines[0]['graphic']==CHART
    p=director.make_plan(lines,3,[],'doc',cinematic=True,fps=60)
    assert p['fps']==60 and p['frames']==180 and p['scenes'][0]['graphic']==CHART
    monkeypatch.setattr(sources,'search',lambda *_:pytest.fail('Explicit graphics must never be searched'))
    monkeypatch.setattr(intel,'generate_local',lambda *_:pytest.fail('Explicit graphics must never be generated'))
    sources.fill_missing(p,tmp_path,allow_network=True);intel.fill_generated(p,tmp_path,enabled=True)
    assert p['scenes'][0]['graphic']==CHART

def test_kokoro_preference_and_no_implicit_draft(monkeypatch):
    monkeypatch.setattr(creator,'voice_options',lambda:{'kokoro':True,'piper':True,'system':False,'draft':True})
    assert creator.resolve_voice('auto')=='kokoro'
    monkeypatch.setattr(creator,'voice_options',lambda:{'kokoro':False,'piper':False,'system':False,'draft':True})
    with pytest.raises(ValueError):creator.resolve_voice('auto',allow_draft=False)
    with pytest.raises(ValueError):creator.resolve_voice('kokoro')
    assert creator.resolve_voice('draft',allow_draft=False)=='draft'

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='ffmpeg required')
def test_kokoro_batch_adapter_with_fake_runtime(tmp_path,monkeypatch):
    monkeypatch.setattr(creator,'voice_options',lambda:{'kokoro':True})
    seen=[]
    def fake_batch(phrases,root,voice,speed,check_cancel):
        seen.append((phrases,voice,speed));out=[]
        for i,phrase in enumerate(phrases):
            dst=root/f'neural-{i:04d}.wav';samples=np.rint(5000*np.sin(np.arange(12000)*.07)).astype('<i2')
            with wave.open(str(dst),'wb') as w:w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(samples.tobytes())
            out.append(dst)
        return iter(out)
    monkeypatch.setattr(creator,'kokoro_batch',fake_batch)
    monkeypatch.setattr(creator,'synthesize_phrase',lambda *a:pytest.fail('No fallback'))
    result=creator.narration([{'title':'Proof','narration':'First phrase. Second phrase.','graphic':CHART}],tmp_path/'voice.wav','kokoro')
    assert len(seen)==1 and len(seen[0][0])==2 and result['provider']=='kokoro' and len(result['lines'])==2
    assert all(r['graphic']==CHART for r in result['lines'])

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='ffmpeg/ffprobe required')
def test_mixed_recording_and_graphics_exact_decoded_clock(tmp_path):
    import subprocess
    fps=60; assets=tmp_path/'assets'; assets.mkdir(); name='a'*32+'.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=320x180:r=30:d=0.7','-c:v','libx264','-threads','1',str(assets/name)],check=True)
    base={'type':'big_text','text':'','captions':[],'camera':'still','cinematic_finish':True,'brand':'TEST'}
    scenes=[{**base,'start':0,'end':43/fps,'frames':43,'type':'broll','asset':name,'asset_start':0,'editorial_seconds':.7}, {**base,'start':43/fps,'end':90/fps,'frames':47,'graphic':CHART,'editorial':'graphic'}]
    plan={'preset':'doc','fps':fps,'duration':90/fps,'frames':90,'scenes':scenes,'silent':False,'cinematic_finish':True,'crossfades':False,'caption_style':'off'}
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(np.rint(5000*np.sin(np.arange(36000)*.07)).astype('<i2').tobytes())
    def encode(args,cwd,*_):subprocess.run(args,cwd=cwd,check=True,capture_output=True)
    out=tmp_path/'out.mp4';director.render(plan,audio,assets,tmp_path/'cache',out,{'fps':fps},(320,180),lambda rows,path:path.write_text(''),encode,lambda:None,lambda *_:None)
    p=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames','-of','json',str(out)]))
    assert int(p['streams'][0]['nb_read_frames'])==90
