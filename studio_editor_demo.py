"""Import genuine sample-clocked offline JUCE editor captures. No live DAW access.
A sealed manifest provides integrity, not cryptographic proof of origin.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
import shutil
from pathlib import Path
import numpy as np
from PIL import Image
from studio_demo import safe, digest, read_json, pcm, table

FIELDS = ('frame','sample','parameter','normalized','actual','input_rms','output_rms','input_peak','output_peak')


def validate(root, sealed=True):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Capture must be a real directory')
    meta = read_json(safe(root,'capture.json',16384))
    if (meta.get('schema') != 'skell.demo.editor.v1' or meta.get('origin') != 'offline_juce_editor'
            or meta.get('product') != 'Skell Quickstart' or meta.get('parameter') != 'gain'
            or not re.fullmatch('[a-f0-9]{40}',str(meta.get('revision','')))):
        raise ValueError('Unsupported editor capture adapter')
    fps, count, rate, samples, w, h = (meta.get(k) for k in ('fps','frame_count','sample_rate','samples','width','height'))
    if (any(type(v) != int for v in (fps,count,rate,samples,w,h)) or fps != 24 or rate != 48000
            or not 24 <= count <= 720 or samples != count * (rate//fps) or (w,h) not in ((480,330),(960,660))):
        raise ValueError('Invalid capture clock or dimensions')
    names = ['capture.json','editor.csv','dry.wav','processed.wav'] + [f'frame_{i:06}.png' for i in range(count)]
    files = {name: safe(root,name,4*1024*1024 if name.endswith('.png') else 32*1024*1024) for name in names}
    if sum(p.stat().st_size for p in files.values()) > (400 if w==960 else 200)*1024*1024:
        raise ValueError('Editor capture too large')
    if {p.name for p in root.glob('frame_*.png')} != set(names[4:]):
        raise ValueError('Unexpected editor frames')
    hashes = {name:digest(p) for name,p in files.items()}
    if sealed and read_json(safe(root,'editor_bundle.json',256*1024)) != {'schema':'skell.demo.editor.bundle.v1','sha256':hashes}:
        raise ValueError('Editor capture integrity check failed')
    pixels=set()
    import hashlib
    for name in names[4:]:
        with Image.open(files[name]) as im:
            if im.format != 'PNG' or im.size != (w,h): raise ValueError('Invalid editor frame format or dimensions')
            rgb=im.convert('RGB')
            if len(rgb.resize((24,16)).getcolors(384) or [])<12: raise ValueError('Blank editor frame')
            pixels.add(hashlib.sha256(rgb.tobytes()).hexdigest())
    if len(pixels)<12: raise ValueError('Editor capture has insufficient distinct frames')
    dry,wet=(pcm(files[name],rate,samples) for name in ('dry.wav','processed.wav'))
    rows=table(files['editor.csv'],FIELDS,count)
    if len(rows)!=count: raise ValueError('Incomplete editor trace')
    n=rate//fps;values=[];max_meter_error=0.
    for i,row in enumerate(rows):
        if int(row['frame'])!=i or int(row['sample'])!=i*n or row['parameter']!='gain': raise ValueError('Editor trace clock mismatch')
        nums=[float(row[k]) for k in FIELDS[3:]]
        if not all(math.isfinite(v) for v in nums) or not 0<=nums[0]<=1 or not 0<=nums[1]<=2 or abs(nums[1]-2*nums[0])>.002 or any(not 0<=v<=1 for v in nums[2:]):
            raise ValueError('Invalid parameter readback or measured levels')
        a,b=dry[i*n:(i+1)*n],wet[i*n:(i+1)*n]
        expected=(float(np.sqrt(np.mean(a*a))),float(np.sqrt(np.mean(b*b))),float(np.max(np.abs(a))),float(np.max(np.abs(b))))
        error=max(abs(x-y) for x,y in zip(nums[2:],expected))
        max_meter_error=max(max_meter_error,error)
        if error>.0001: raise ValueError('Editor meter/audio mismatch')
        values.append(nums[1])
    if max(values)-min(values)<.1: raise ValueError('Parameter readback never changes')
    return {'meta':meta,'hashes':hashes,'distinct_frames':len(pixels),'gain_range':[min(values),max(values)],
            'max_meter_error':max_meter_error,'duration_seconds':samples/rate}


def seal(root):
    result=validate(root,sealed=False)
    with (Path(root)/'editor_bundle.json').open('x',encoding='utf-8') as f:
        json.dump({'schema':'skell.demo.editor.bundle.v1','sha256':result['hashes']},f,indent=2)
    return result


def render(root,out):
    result=validate(root);meta=result['meta'];root=Path(root).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    video=out/'editor_demo.mp4'
    # Native capture is the full picture. No reconstructed widgets or artificial cursor.
    width,height=(1920,1080) if meta['width']==960 else (1280,720)
    panel_width=round(height*meta['width']/meta['height']/2)*2
    args=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-filter_threads','1','-threads','1','-framerate','24','-start_number','0','-i',str(root/'frame_%06d.png'),'-i',str(root/'processed.wav'),'-map','0:v:0','-map','1:a:0','-vf',f'scale={panel_width}:{height}:flags=lanczos,pad={width}:{height}:(ow-iw)/2:0:color=0x0d1412,setsar=1','-frames:v',str(meta['frame_count']),'-t',str(meta['frame_count']/24),'-c:v','libx264','-threads','2','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(video)]
    try:
        subprocess.run(args,check=True,capture_output=True,timeout=180)
        if not video.is_file() or video.stat().st_size<1024:raise RuntimeError('Missing rendered editor clip')
    except (subprocess.SubprocessError,OSError,RuntimeError):
        video.unlink(missing_ok=True);raise
    # Export the original aligned A/B pair losslessly for independent listening.
    references={}
    for source,name in [('dry.wav','dry_reference.wav'),('processed.wav','processed_reference.wav')]:
        target=out/name
        shutil.copyfile(root/source,target)
        actual=digest(target)
        if actual!=result['hashes'][source]:raise RuntimeError('Capture reference changed during export')
        references[name]=actual
    (out/'editor_demo_report.json').write_text(json.dumps({**result,'video_sha256':digest(video),'audio_references':references,'note':'Offline programmatic JUCE slider demonstration; not a live DAW recording. Original processed test audio.'},indent=2),encoding='utf-8')
    return video


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','verify','render']);p.add_argument('capture',type=Path);p.add_argument('--out',type=Path);a=p.parse_args(argv)
    try:
        if a.action=='render':
            if a.out is None:raise ValueError('--out required')
            print(render(a.capture,a.out))
        else:
            result=seal(a.capture) if a.action=='seal' else validate(a.capture)
            print(f"Verified {result['meta']['frame_count']} frames and actual gain readback {result['gain_range']}")
        return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:p.exit(1,f'Editor capture error: {exc}\n')

if __name__=='__main__':raise SystemExit(main())
