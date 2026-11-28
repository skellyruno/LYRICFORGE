import numpy as np
from PIL import ImageFont
from studio_optics import hit_sphere,reflect,refract,render,orbit,timeline

def test_intersection():
    o=np.array([[0,0,3.],[0,0,3.],[0,0,0.]])
    d=np.array([[0,0,-1.],[1,0,0.],[0,0,1.]])
    assert np.allclose(hit_sphere(o,d,[0,0,0],1)[[0,2]],[2,1]);assert np.isinf(hit_sphere(o,d,[0,0,0],1)[1])

def test_snell_and_reflection():
    d=np.array([[.5,0,-np.sqrt(.75)]]);n=np.array([[0.,0,1.]])
    q,ok=refract(d,n,1/1.5);assert ok[0] and np.isclose(q[0,0],1/3);assert np.isclose(np.linalg.norm(q),1)
    assert np.allclose(reflect(d,n),[[.5,0,np.sqrt(.75)]])
    q,ok=refract(np.array([[.9,0,-np.sqrt(.19)]]),n,1.5);assert not ok[0] and q[0,2]>0

def test_frame_deterministic_and_materials():
    a=np.asarray(render(320,180,1));b=np.asarray(render(320,180,1));c=np.asarray(render(320,180,3));m=np.asarray(render(320,180,1,glass=False))
    assert np.array_equal(a,b) and not np.array_equal(a,c) and not np.array_equal(a,m);assert a.std()>12

def test_time_illustrations():
    from studio_director import font
    for fn in (orbit,timeline):assert fn(400,220,0,font).tobytes()!=fn(400,220,1,font).tobytes()

def test_narration_assembly_uses_exact_chapter_clock(tmp_path):
    import wave
    from examples.time_narration import assemble, SCRIPT, RATE
    for i in range(6):
        with wave.open(str(tmp_path/f'neural-{i:04d}.wav'),'wb') as f:
            f.setparams((1,2,RATE,0,'NONE','not compressed'));f.writeframes(np.full(RATE,200,dtype='<i2').tobytes())
    report=assemble(tmp_path);assert len(report['chapters'])==6 and report['chapters'][0]['start']==.5
    assert all(a['end']<b['start'] for a,b in zip(report['chapters'],report['chapters'][1:]))
    with wave.open(str(tmp_path/'narration.wav'),'rb') as f:assert f.getnframes()==round(report['duration']*RATE)

def test_trajectory_and_time_plan():
    from studio_optics import trajectory
    from studio_director import font
    from examples.time_documentary import plan_for
    p=plan_for();assert sum(x['frames'] for x in p['scenes'])==p['frames'] and len(p['scenes'])==6
    assert trajectory(500,240,0,font).tobytes()!=trajectory(500,240,1,font).tobytes()

def test_reference_abstention_and_segments(tmp_path):
    import studio_reference_vision as v
    (tmp_path/'config.json').write_text('{}')
    frames=np.zeros((20,32,48,3),dtype=np.uint8)
    def request(r):
        scores=np.zeros((len(r['texts']),len(r['images'])));scores[0,:2]=2;scores[len(v.TECHNIQUES),:2]=2
        return {'scores':scores.tolist()}
    result=v.infer(frames,2,model=tmp_path,request=request)
    assert result['review_required'] and result['sampled_segments'][0]['labels']==['footage','hook']
    assert result['sampled_segments'][-1]['labels']==['uncertain','uncertain']
