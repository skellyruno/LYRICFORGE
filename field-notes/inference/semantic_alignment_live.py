"""Live model checks for semantic montage and recognized speech clocks."""
import argparse, hashlib, importlib.util, json, os, subprocess, time
from pathlib import Path
from PIL import Image,ImageDraw


def write(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def vision(out,models):
    import studio_sequence_semantic as film
    import studio_sequence as seq
    import studio_sequence_render as renderer
    from studio_director_intelligence import ai_request
    spec=importlib.util.spec_from_file_location('proof','field-notes/inference/prove.py')
    proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
    model,provenance=proof.prepare_model('vision',models)
    write(out/'model-provenance.json',provenance)
    assets={}
    for name,kind in [('source','plain'),('shot-a','diagram'),('shot-b','hardware'),('shot-c','unrelated')]:
        p=out/(name+'.png');im=Image.new('RGB',(384,216),'#1c2530');d=ImageDraw.Draw(im)
        if kind=='diagram':
            for x in range(40,360,40):d.line((x,20,x,180),fill='#506070')
            for y in range(20,200,40):d.line((40,y,360,y),fill='#506070')
            d.line([(40,155),(100,153),(140,70),(220,67),(350,155)],fill='#69d1e0',width=5)
        elif kind=='hardware':
            d.rectangle((25,22,359,194),fill='#d7bb75');d.rectangle((38,38,346,176),fill='#23232a')
            for x in range(65,320,55):d.ellipse((x,65,x+42,107),fill='#c7c7c7',outline='white',width=2)
            d.rectangle((65,120,314,155),fill='#575962')
            for x in range(70,315,23):d.rectangle((x,125,x+10,150),fill='#2fbc71')
        elif kind=='unrelated':
            d.rectangle((0,0,384,216),fill='#84c9f0');d.ellipse((295,16,335,56),fill='yellow')
            d.polygon([(0,216),(140,40),(260,216)],fill='#366f46');d.polygon([(120,216),(300,80),(384,216)],fill='#29452c')
        else:d.rectangle((45,55,340,160),fill='#414141')
        im.save(p);dest=out/(name+'.mp4');duration=14 if name=='source' else 4
        subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(p),'-t',str(duration),'-r','30','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(dest)],check=True)
        assets[name]={'path':dest,'duration':duration,'has_video':True,'has_audio':False,'keywords':[]}
    phrases=[(2.,3.5,'frequency response graph with an equalizer curve'),(8.,9.5,'audio mixing console with rotary knobs and meters')]
    windows=[(k,assets[k]['path'],0,90) for k in ('shot-a','shot-b','shot-c')]
    captured={}
    def traced(body,timeout):
        response=ai_request(body,timeout=timeout);captured.update(texts=body['texts'],scores=response['scores']);return response
    rows=film.match(windows,phrases,model,traced)
    write(out/'actual-semantic-evidence.json',{'matches':rows,'raw_model':captured,'expected':['shot-a','shot-b'],'scope':'Generated unlabelled controls, not a broad professional footage benchmark.'})
    assert [r['asset'] for r in rows]==['shot-a','shot-b'],rows
    words=[]
    for a,b,text in phrases:
        tokens=text.split()
        words.extend({'text':t+('.' if i==len(tokens)-1 else ''),'start':a+(b-a)*i/len(tokens),'end':a+(b-a)*(i+1)/len(tokens)} for i,t in enumerate(tokens))
    # Use actual model evidence to drive the application proposal. Keep the
    # shot measurements deterministic here; other tests exercise real decoding.
    actual_visual=film.creative.visual
    film.creative.visual=lambda a:{'quality':.85,'motion':.04,'sample_quality':[.85]*8}
    try:result=film.propose(seq.initial(assets),assets,words,'cinematic',model=model,request=traced)
    finally:film.creative.visual=actual_visual
    write(out/'proposal.json',result)
    assert result['suggestions'],result
    state=seq.apply(seq.initial(assets),result['suggestions'][0]['action'],assets)
    assert [x['asset'] for x in state['layers']]==['shot-a','shot-b']
    stats=renderer.render(state,assets,out/'semantic-proof.mp4',width=384,height=216)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(out/'semantic-proof.mp4'),'-f','null','-'],check=True)
    write(out/'result.json',{'passed':True,'render':stats})


def voice(out,models):
    import studio_creator as creator
    import studio_voice_alignment as alignment
    from faster_whisper import WhisperModel
    spec=importlib.util.spec_from_file_location('media_proof','packaging/shared-media/shared_media_proof.py')
    proof=importlib.util.module_from_spec(spec);spec.loader.exec_module(proof)
    model_dir=models/'whisper'
    proof.download_model(model_dir)
    model=WhisperModel(str(model_dir),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1,local_files_only=True)
    text='Shape the sound. Every choice is yours.'
    comparisons={}
    for direction in ('detail','reveal','close'):
        path=out/(direction+'.wav')
        result=creator.narration([{'title':'Product film','narration':text,'voice_direction':direction}],path,'kokoro',delivery='cinematic')
        segments,_=model.transcribe(str(path),language='en',word_timestamps=True,beam_size=3,best_of=1,temperature=0,vad_filter=False,condition_on_previous_text=False)
        recognized=[{'words':[{'text':w.word.strip(),'start':float(w.start),'end':float(w.end),'probability':float(w.probability)} for w in s.words or []]} for s in segments]
        aligned=alignment.align(result,recognized)
        comparisons[direction]={'seconds':result['duration'],'recognized':recognized,'estimated':result['lines'],'aligned':aligned}
        write(out/'alignment-evidence.json',comparisons)
    assert all(x['aligned'] is not None for x in comparisons.values()),'Recognition did not match the original script'
    assert all(' '.join(r['text'] for r in x['aligned']['lines'])==text for x in comparisons.values())
    assert comparisons['close']['seconds']>comparisons['detail']['seconds']
    write(out/'result.json',{'passed':True,'provider':'Kokoro + pinned Whisper Small','directions':{k:v['seconds'] for k,v in comparisons.items()},'scope':'Exact text reconciliation to ASR timestamps; not phoneme-level forced alignment or emotional acting.'})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['vision','voice']);p.add_argument('out',type=Path);p.add_argument('models',type=Path);args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    try:globals()[args.kind](args.out,args.models)
    except Exception as exc:
        write(args.out/'result.json',{'passed':False,'error':str(exc)[:1500]});raise
