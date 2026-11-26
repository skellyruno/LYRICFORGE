"""Optional isolated local AI process. Never downloads a model or runs remote code."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_DATASETS_OFFLINE']='1'


def run(request):
    import torch
    from PIL import Image
    model=Path(request['model']).resolve(strict=True)
    if not model.is_dir(): raise ValueError('Model must be an installed local directory')
    device='cuda' if torch.cuda.is_available() else 'cpu'
    if request['operation']=='generate':
        from diffusers import StableDiffusionPipeline
        pipe=StableDiffusionPipeline.from_pretrained(str(model),local_files_only=True,use_safetensors=True,
                    torch_dtype=torch.float16 if device=='cuda' else torch.float32).to(device)
        # No disable-safety override. Require a model with its safety checker.
        if pipe.safety_checker is None: raise ValueError('Choose a model with a safety checker')
        result=pipe(str(request['prompt'])[:200],negative_prompt='text, logos, product screenshot, watermark',
                    width=512,height=512,num_inference_steps=20,generator=torch.Generator(device=device).manual_seed(int(request['seed'])))
        if any(result.nsfw_content_detected or []): raise ValueError('Model rejected image')
        result.images[0].convert('RGB').save(request['output'],format='PNG')
        return {'ok':True}
    if request['operation']=='match':
        from transformers import CLIPModel, CLIPProcessor
        pipe=CLIPModel.from_pretrained(str(model),local_files_only=True,use_safetensors=True).to(device).eval()
        processor=CLIPProcessor.from_pretrained(str(model),local_files_only=True)
        images=[]
        for file in request['images'][:12]:
            with Image.open(file) as image: images.append(image.convert('RGB'))
        # Single forward pass for bounded image/text pairs; CLIP returns
        # calibrated-to-its-own-model relative logits, not probabilities of truth.
        texts=[str(t)[:220] for t in request['texts'][:64]]
        if not images or not texts: return {'scores':[]}
        inputs=processor(text=texts,images=images,return_tensors='pt',padding=True,truncation=True)
        with torch.inference_mode():
            scores=pipe(**{k:v.to(device) for k,v in inputs.items()}).logits_per_text
        return {'scores':scores.float().cpu().tolist()}
    raise ValueError('Unknown AI operation')


if __name__=='__main__':
    try:
        result=run(json.load(sys.stdin));print(json.dumps(result,allow_nan=False))
    except Exception as exc:
        print(json.dumps({'error':str(exc)[:200]}));sys.exit(1)
