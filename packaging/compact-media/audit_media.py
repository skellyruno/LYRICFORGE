"""Compare the original and candidate decoders on identical reference media."""
import argparse, hashlib, json, math, os, re, subprocess, time
from pathlib import Path
import numpy as np

def run(exe,args,timeout=120):
    p=subprocess.run([str(exe),'-hide_banner','-nostdin',*args],capture_output=True,timeout=timeout)
    if p.returncode: raise RuntimeError(f'{exe} {args}: {p.stderr.decode(errors="replace")[-3000:]}')
    return p.stdout

def features(exe,kind):
    lines=run(exe,['-'+kind]).decode(errors='replace').splitlines()
    if kind=='filters':
        return {m.group(1) for l in lines if (m:=re.match(r'^\s*(?:[A-Z.]{2,3}\s+)?([A-Za-z0-9_]+)\s+[AVN|]+->[AVN|]+(?:\s|$)',l))}
    return {m.group(1) for l in lines if (m:=re.match(r'^\s*[VAS][A-Z.]{5}\s+([A-Za-z0-9_]+)\s+',l))}

def compare(a,b,dtype):
    x=np.frombuffer(a,dtype=dtype).astype(np.float64); y=np.frombuffer(b,dtype=dtype).astype(np.float64)
    if len(x)!=len(y) or not len(x):raise ValueError(f'decoded size differs {len(x)} != {len(y)}')
    err=float(np.mean((x-y)**2)); signal=float(np.mean(x*x))
    ref=255**2 if dtype=='uint8' else max(signal,1.)
    score=120. if err==0 else 10*math.log10(ref/err)
    return {'decoded_values':len(x),'exact':a==b,'psnr_or_snr_db':round(score,3)}

def audit(old,new,out):
    old,new,out=Path(old).resolve(),Path(new).resolve(),Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'baseline_bytes':old.stat().st_size,'candidate_bytes':new.stat().st_size,'baseline_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(new.read_bytes()).hexdigest(),'cases':[]}
    def save(): (out/'media-compatibility.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    save()
    from server import QUICK_TOOLS,TOOL_FILTERS
    required=set().union(*(set(t.filters) for t in QUICK_TOOLS.values()),*(set(t) for t in TOOL_FILTERS.values()))
    required.update('ass fps scale format tpad trim adelay apad atrim asetpts setpts concat xfade volumedetect ebur128 palettegen paletteuse atempo loudnorm'.split())
    report['missing_filters']=sorted(required-features(new,'filters'))
    required_encoders={'libx264','aac','rawvideo','png','mjpeg','gif','pcm_s16le','pcm_s24le','pcm_f32le','libvpx','h264_nvenc','h264_qsv','h264_amf'}
    if os.name!='nt': required_encoders -= {'h264_nvenc','h264_qsv','h264_amf'}
    report['missing_encoders']=sorted(required_encoders-features(new,'encoders'));save()
    if report['missing_filters'] or report['missing_encoders']:raise RuntimeError('Required capabilities missing')
    video_cases=[('h264.mp4','libx264',[]),('hevc.mp4','libx265',['-preset','ultrafast']),('vp8.webm','libvpx',['-deadline','realtime']),('vp9.webm','libvpx-vp9',['-deadline','realtime']),('av1.mkv','libaom-av1',['-cpu-used','8']),('prores.mov','prores_ks',[]),('mpeg4.m4v','mpeg4',[])]
    audio_cases=[('source.mp3','libmp3lame'),('source.flac','flac'),('source.wav','pcm_s24le'),('source.m4a','aac'),('source.aac','aac'),('source.ogg','libvorbis'),('source.opus','libopus')]
    for kind,cases in [('video',video_cases),('audio',audio_cases)]:
        for case in cases:
            path=out/case[0];codec=case[1]
            if kind=='video':
                run(old,['-v','error','-y','-f','lavfi','-i','testsrc2=s=160x96:r=12:d=1','-an','-c:v',codec,'-threads','2',*case[2],str(path)])
                decode=['-v','error','-threads','1','-i',str(path),'-map','0:v:0','-an','-pix_fmt','rgb24','-c:v','rawvideo','-threads','1','-f','rawvideo','pipe:1'];dtype='uint8';threshold=40.
            else:
                run(old,['-v','error','-y','-f','lavfi','-i','sine=f=440:d=1:sample_rate=48000','-c:a',codec,str(path)])
                decode=['-v','error','-threads','1','-i',str(path),'-vn','-map','0:a:0','-ac','1','-ar','48000','-c:a','pcm_s16le','-f','s16le','pipe:1'];dtype='<i2';threshold=35.
            a=run(old,decode);start=time.monotonic();b=run(new,decode);sec=time.monotonic()-start
            result=compare(a,b,dtype); result.update(name=case[0],codec=codec,seconds=round(sec,4),passed=result['psnr_or_snr_db']>=threshold);report['cases'].append(result);save();print(result,flush=True)
            if not result['passed']:raise RuntimeError('Decoded quality below threshold: '+case[0])
    report['passed']=True;save()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('candidate');p.add_argument('out');a=p.parse_args();audit(a.baseline,a.candidate,a.out)
