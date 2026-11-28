"""Explicit real inference proof using pinned local vision weights and an actual Ollama model.
Only generated test fixtures are used; never upload private footage or model weights.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

from PIL import Image,ImageDraw
import studio_sequence as sequence
import studio_sequence_vision as vision
import studio_sequence_model as planner

def write(path,obj):
    path.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')

def run(kind, out, models):
    out.mkdir(parents=True,exist_ok=True)
    def fixture(name,diagram):
        path=out/(name+'.png')
        im=Image.new('RGB',(384,216),'#1c2530');d=ImageDraw.Draw(im)
        if diagram:
            for x in range(40,360,40):d.line((x,20,x,180),fill='#3a4752')
            for y in range(20,200,40):d.line((40,y,360,y),fill='#3a4752')
            d.line([(40,155),(100,153),(140,70),(220,67),(350,155)],fill='#69d1e0',width=5)
            d.text((42,12),'Frequency response',fill='white')
        else:
            d.rectangle((35,30,345,170),fill='#d7bb75');d.rectangle((60,50,320,140),fill='#23232a')
            for x in range(80,305,38):d.ellipse((x,76,x+25,101),fill='#dddddd')
            d.text((60,154),'Audio processor',fill='black')
        im.save(path)
        dest=out/(name+'.mp4')
        subprocess.run(['ffmpeg','-v','error','-y','-loop','1','-i',str(path),'-t','4','-r','30','-c:v','libx264','-threads','1','-pix_fmt','yuv420p',str(dest)],check=True)
        return {'path':dest,'duration':4.,'has_video':True,'has_audio':False,'music':False,'keywords':[name]}
    assets={'source':fixture('source',False),'diagram':fixture('diagram',True)}
    start=time.monotonic()
    try:
        if kind=='vision':
            spec=importlib.util.spec_from_file_location('model_proof',Path('field-notes/inference/prove.py'))
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            path,provenance=mod.prepare_model('vision',models)
            write(out/'model-provenance.json',provenance)
            # Load the real model in the existing isolated worker, then run
            # the same sequence evidence function shipped in V5.
            r=vision.evidence(assets,'show the frequency response diagram',model=path)
            write(out/'vision-evidence.json',r)
            assert r['status']=='sampled' and len(r['observations'])==4,r
            # Report labels and scores; only the path/shape is gated here.
            # The existing pinned-model checker separately tests color controls.
            mod.vision(Path.cwd(),out,path)
        else:
            from studio_timeline_assistant import local_json
            tags=local_json('/api/tags');write(out/'model-provenance.json',tags)
            state=sequence.initial(assets)
            attempts=[]
            def traced(path,payload=None,timeout=4):
                response=local_json(path,payload,timeout)
                if path=='/api/chat':
                    attempts.append(response.get('message',{}).get('content',''))
                    write(out/'model-attempts.json',attempts)
                return response
            r=planner.propose(state,assets,[],'Insert the diagram as a visual layer at 1 second for 1 second. Keep the original audio and timing. Use asset diagram.','qwen2.5:3b',traced)
            write(out/'planning-evidence.json',r)
            assert r['preview']['before_frames']==r['preview']['after_frames']==120
            assert len(r['preview']['layers'])==1 and not r['preview']['transitions'],r
            assert any(x['kind']=='visual' and x['asset']=='diagram' and x['at']==30 and x['length']==30 for x in r['preview']['layers']),r
            result=sequence.apply(state,r['action'],assets)
            assert result['layers'] and not state['layers']
        write(out/'result.json',{'status':'passed','kind':kind,'seconds':time.monotonic()-start,'scope':'Generated controls, not professional creative-quality proof.'})
    except Exception as e:
        write(out/'result.json',{'status':'failed','kind':kind,'error':str(e)[:1500],'seconds':time.monotonic()-start})
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['vision','planner']);p.add_argument('out',type=Path);p.add_argument('models',type=Path);a=p.parse_args()
    run(a.kind,a.out,a.models)
