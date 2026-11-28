import json
import shutil
import subprocess
import pytest
import studio_sequence_vision as vision
import studio_sequence_model as planner
import studio_sequence as seq
from test_sequence_model import no_decode, mock, layer
from test_studio_sequence import assets

@pytest.fixture
def media(tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('FFmpeg required')
    path=tmp_path/'clip.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=s=160x90:r=30:d=2','-c:v','libx264','-threads','1',str(path)],check=True)
    model=tmp_path/'model';model.mkdir();(model/'config.json').write_text('{}')
    return {'source':{'path':path,'duration':2.,'has_video':True}},model

def test_not_configured(monkeypatch):
    monkeypatch.delenv('SKELLYMOTION_VISION_MODEL',raising=False)
    assert vision.evidence({},'make cinematic')['status']=='not_configured'

def test_real_frame_sampling_and_mock_semantic_worker(media):
    a,model=media
    from pathlib import Path
    def request(body,timeout):
        assert body['operation']=='match' and len(body['images'])==2
        assert all(Path(p).is_file() for p in body['images'])
        n=len(body['texts']);return {'scores':[[float(i),float(n-i)] for i in range(n)]}
    r=vision.evidence(a,'make cinematic',model=model,request=request)
    assert r['status']=='sampled' and len(r['observations'])==2
    assert [x['second'] for x in r['observations']]==[.4,1.5]
    assert 'path' not in json.dumps(r)
    assert all(x['technique']!='uncertain' for x in r['observations'])
    assert vision.evidence(a,'test',model=model,request=lambda *a,**k:{'scores':[[float('nan')]]})['status']=='inference_failed'

def test_vision_context_to_model(assets,no_decode,monkeypatch):
    monkeypatch.setattr(vision,'evidence',lambda *a,**k:{'status':'sampled','observations':[{'asset':'city','second':2.,'role':'context'}]})
    def get(path,payload=None,timeout=4):
        if path=='/api/tags':return {'models':[{'name':'test:3b'}]}
        context=json.loads(payload['messages'][1]['content']);assert context['semantic_evidence']['observations'][0]['asset']=='city'
        return {'message':{'content':json.dumps({'reason':'Use reviewed context','actions':[layer()]})}}
    result=planner.propose(seq.initial(assets),assets,[],'make cinematic','test:3b',get)
    assert 'Vision: sampled' in result['warning']
