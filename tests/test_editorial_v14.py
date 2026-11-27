import json, shutil, subprocess, wave
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
import studio_layers as layers
import studio_media_layers as media
import studio_reference_vision as vision
import studio_quality as quality
import studio_director as d

PIC='a'*32+'.png';MOV='b'*32+'.mp4'
def spec(*ls):return {'kind':'composition','title':'Media study','source':'Authored fixture','layers':list(ls)}
def layer(kind,key=None,**kw):return dict(id=kind,type=kind,**({'asset':key} if key else {}),width=.7,height=.65,**kw)

@pytest.mark.parametrize('bad',['../a.png','https://example.com/a.png','a'*32+'.mp4','a'*32+'.pdf'])
def test_media_rejects_unsafe_or_wrong_ids(bad):
    with pytest.raises(ValueError):layers.validate(spec(layer('image',bad)))

def test_media_stamps_disabled_and_symlink(tmp_path):
    p=tmp_path/PIC;Image.new('RGB',(40,40),'red').save(p);s={'graphic':layers.validate(spec(layer('image',PIC)))}
    a=media.stamps(s,tmp_path);Image.new('RGB',(50,40),'blue').save(p);assert a!=media.stamps(s,tmp_path)
    (tmp_path/'index.json').write_text(json.dumps({PIC:{'disabled':True}}))
    with pytest.raises(ValueError,match='disabled'):media.stamps(s,tmp_path)
    (tmp_path/'index.json').unlink();p.unlink();(tmp_path/'other.png').touch();p.symlink_to(tmp_path/'other.png')
    with pytest.raises(ValueError):media.stamps(s,tmp_path)

@pytest.mark.parametrize('size',[(640,360),(360,640)])
def test_layer_media_and_typography(tmp_path,size):
    p=tmp_path/PIC;Image.new('RGB',(80,40),'red').save(p)
    g=spec(layer('image',PIC,track=[[0,.28,.50,1,1],[1,.68,.50,.8,1]]),layer('text',text='A long title with an independent face',face='serif',align='left',size=.12,track=[[0,.5,.20,1,1]]))
    with media.MediaBank(tmp_path) as bank:
        s=layers.Composition(g,*size,3,d.font,media_bank=bank);assert s.render(1).size==size;assert not np.array_equal(s.render(0),s.render(2))
    assert not Path(bank.tmp.name).exists()

def test_sphere_perspective_texture_and_full_silhouette():
    t=np.zeros((64,128,3),np.uint8);t[:,:64]=[220,40,30];t[:,64:]=[20,190,130]
    sphere=media.TexturedSphere(Image.fromarray(t));a=np.asarray(sphere.render(180,180,0));b=np.asarray(sphere.render(180,180,2))
    assert np.max(a[[0,-1],:,3])==0 and np.max(a[:,[0,-1],3])==0
    assert a[90,90,3]==255 and np.mean(np.abs(a[:,:,:3].astype(float)-b[:,:,:3]))>5

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_footage_real_frames_trim_hold_and_composition_bridge(tmp_path):
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=30','-t','2','-c:v','libx264','-threads','1',str(tmp_path/MOV)],check=True)
    g=spec(layer('footage',MOV,trim=[.2,1.1],delay=.1));l=layers.validate(g)['layers'][0]
    with media.MediaBank(tmp_path) as bank:
        x=bank.frame(l,0);y=bank.frame(l,.6);z=bank.frame(l,10);assert not np.array_equal(x,y);assert np.array_equal(z,bank.frame(l,20))
        a=layers.Composition(g,320,180,2,d.font,0,bank);b=layers.Composition(spec(layer('text',text='Next')),320,180,2,d.font,2,bank)
        assert np.array_equal(a.render(2),b.bridge(a,0,.7));assert b.bridge(a,.3,.7).size==(320,180)

@pytest.mark.parametrize('bad',[[0,21],[3,2],[-1,2],None])
def test_footage_trim_bounds(bad):
    with pytest.raises(ValueError):layers.validate(spec(layer('footage',MOV,trim=bad)))

def test_quality_detects_empty_and_static_without_false_artistic_approval():
    x=np.zeros((5,20,30,3),np.uint8);r=quality.review_samples(x,list(range(5)));assert r['near_empty']==5 and r['warnings']==6
    x=np.random.default_rng(14).integers(20,230,x.shape,dtype=np.uint8);r=quality.review_samples(x,list(range(5)));assert not r['warnings'] and r['static_pair_fraction']==0

def test_local_vision_contract_and_unconfigured_model(tmp_path):
    f=np.random.default_rng(0).integers(0,255,(24,45,80,3),dtype=np.uint8)
    with pytest.raises(RuntimeError):vision.infer(f,2,model=tmp_path)
    (tmp_path/'config.json').write_text('{}')
    def request(r):
        assert len(r['images'])<=12 and all(Path(p).is_file() for p in r['images'])
        x=np.zeros((len(r['texts']),len(r['images'])));x[1]=4;x[len(vision.TECHNIQUES)+2]=4
        return {'scores':x.tolist()}
    v=vision.infer(f,2,model=tmp_path,request=request);assert v['review_required'];assert all(r['technique']=='document' and r['role']=='evidence' for r in v['observations'])
    with pytest.raises(ValueError):vision.infer(f,2,model=tmp_path,request=lambda r:{'scores':[[float('nan')]]})

def test_narrated_clock_handles_multiple_phrases_per_chapter():
    from examples.image_documentary import plan_for
    result={'duration':60,'lines':[{'chapter_title':str(i),'start':i*10+j*2} for i in range(6) for j in range(2)]}
    p=plan_for({'width':100,'height':100,'pixels':10000},result);assert p['frames']==3600 and len(p['scenes'])==6 and all(s['frames']==600 for s in p['scenes'])

def test_creator_upload_binding_no_paths_and_duplicate_actual_ids():
    g=spec(layer('image',upload_index=0));chapters=[{'title':'A','narration':'A genuine image.', 'graphic':g}]
    from studio_creator import validate_script
    pre=validate_script(media.bind_uploads(chapters,['.png']));assert pre[0]['graphic']['layers'][0]['asset']=='0'*32+'.png'
    actual=validate_script(media.bind_uploads(chapters,['.png'],[PIC]));assert actual[0]['graphic']['layers'][0]['asset']==PIC
    assert chapters[0]['graphic']['layers'][0]['upload_index']==0
    with pytest.raises(ValueError):media.bind_uploads(chapters,['.mp4'])
    with pytest.raises(ValueError):media.bind_uploads(chapters,[])

@pytest.mark.skipif(not (shutil.which('espeak') or shutil.which('espeak-ng')) or not shutil.which('ffmpeg'),reason='Local draft voice and FFmpeg required for API integration test')
def test_creator_media_upload_endpoint_persists_actual_asset(tmp_path,monkeypatch):
    import io,server
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server,'DATA',tmp_path);monkeypatch.setattr(server.executor,'submit',lambda fn,*args:fn(*args))
    b=io.BytesIO();Image.new('RGB',(320,180),'#527087').save(b,format='PNG')
    body={'product':'Media study','story':'documentary','voice':'draft','auto_render':False,'chapters':[{'title':'Evidence','narration':'This is a source image.','graphic':spec(layer('image',upload_index=0))}]}
    c=TestClient(server.app);r=c.post('/api/creator/create',data={'payload':json.dumps(body)},files={'files':('source.png',b.getvalue(),'image/png')});assert r.status_code==200,r.text
    p=server.read_project(r.json()['project_id']);k=p['creator_script'][0]['graphic']['layers'][0]['asset'];assert (server.director_folder(r.json()['project_id'])/k).is_file();assert p['creator_cues'][0]['graphic']['layers'][0]['asset']==k

def test_automatic_collage_positive_match_only_and_protected_demos():
    from studio_auto_composition import plan
    a=[{'id':PIC,'name':'Image source document','description':'camera image comparison','kind':'image','role':'document'}, {'id':MOV,'name':'Camera image footage','description':'camera image comparison','kind':'video','role':'broll','features':{'duration':8}}, {'id':'c'*32+'.png','name':'Camera image comparison capture','description':'camera image comparison','kind':'image','role':'plugin_state'}]
    g=plan('Compare the camera image','camera image comparison','Source comparison',a,d.terms,5);assert g and {l.get('asset') for l in g['layers'] if l.get('asset')}=={PIC,MOV}
    assert plan('A totally unrelated comparison','compare trees','Other',a,d.terms,5) is None
    assert plan('camera image','camera image','Other',a,d.terms,5) is None
    assert plan('Compare the camera image','camera image comparison','Source comparison',a[:1]+a[2:],d.terms,5) is None
    p=d.make_plan([{'start':0,'end':5,'text':'Compare the camera image','visual_hint':'camera image comparison'}],5,a[:2],'doc',cinematic=True)
    assert p['scenes'][0]['automatic_collage'] and p['scenes'][0]['graphic']['kind']=='composition' and 'asset' not in p['scenes'][0]

def test_quality_layout_actual_glyph_bounds():
    g=spec(layer('text',text='VISIBLE TEXT',track=[[0,.02,.5,1,1]]));p={'fps':30,'scenes':[{'frames':90,'graphic':g}]}
    r=quality.review_layout(p,(640,360),d.font);assert r['checked_text_samples']==5 and r['warnings']==1

@pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg required')
def test_actual_layered_export_quality_gate_and_cache_invalidation(tmp_path):
    assets=tmp_path/'assets';assets.mkdir();Image.new('RGB',(200,120),'#647f9f').save(assets/PIC)
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x90:rate=30','-t','2','-c:v','libx264','-threads','1',str(assets/MOV)],check=True)
    g=spec(layer('image',PIC,track=[[0,.25,.5,.6,1]]),layer('footage',MOV,trim=[0,1.8],track=[[0,.75,.5,.6,1]]))
    p={'preset':'doc','fps':24,'duration':2.,'frames':48,'scenes':[{'type':'big_text','text':'Evidence','start':0,'end':2,'frames':48,'captions':[],'camera':'still','cinematic_finish':True,'brand':'TEST','editorial':'graphic','graphic':g}], 'silent':True,'cinematic_finish':True,'crossfades':False,'caption_style':'off','caption_track':[],'sound_design':False}
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as f:f.setparams((1,2,24000,0,'NONE','not compressed'));f.writeframes(bytes(24000*2*2))
    def render(name):return d.render(p,audio,assets,tmp_path/'cache',tmp_path/name,{'fps':24},(320,180),lambda rows,path:path.write_text(''),lambda args,cwd,*_:subprocess.run(args,cwd=cwd,check=True,capture_output=True),lambda:None,lambda *_:None)
    r=render('one.mp4');assert r['rendered']==1 and r['picture_review']['samples']>0 and r['picture_review']['layout']['warnings']==0
    assert render('two.mp4')['cached']==1
    Image.new('RGB',(201,120),'#bfa24a').save(assets/PIC)
    assert render('three.mp4')['rendered']==1
