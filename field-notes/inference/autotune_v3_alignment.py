"""ASR timestamps from the actual V2 Kokoro sources; no private audio."""
import hashlib,importlib.util,json,sys
from pathlib import Path
from faster_whisper import WhisperModel
def main():
    src=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('proof','packaging/shared-media/shared_media_proof.py')
    p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
    model=Path('whisper-model');p.download_model(model)
    w=WhisperModel(str(model.resolve()),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    m=json.loads((src/'manifest.json').read_text());rows=[]
    for r in m['phrases']:
        f=src/r['file'];assert hashlib.sha256(f.read_bytes()).hexdigest()==r['sha256']
        segs,_=w.transcribe(str(f),language='en',beam_size=5,word_timestamps=True,vad_filter=False,condition_on_previous_text=False,temperature=0.)
        words=[{'text':x.word.strip(),'start':float(x.start),'end':float(x.end),'probability':float(x.probability)} for s in segs for x in s.words or []]
        rows.append({'file':r['file'],'source_sha256':r['sha256'],'script':r['text'],'words':words})
        print(r['file'],len(words),flush=True)
    assert len(rows)==13 and all(r['words'] for r in rows)
    (out/'recognition.json').write_text(json.dumps({'model_sha256':p.MODEL_SHA,'phrases':rows},indent=2))
if __name__=='__main__':main()
