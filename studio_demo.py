"""SkellCore measured demo bridge. Trusted local folders only; no live host access.
Validate a bounded, sample-clocked capture against the PCM and its digests before
rendering. Recorded measurements are not cryptographic proof of plugin origin.
"""
from __future__ import annotations
import argparse, bisect, csv, hashlib, json, math, re, subprocess, tempfile, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FILES=('capture.json','events.csv','meters.csv','dry.wav','processed.wav','sidechain.wav')
BANDS=(75,155,280,520,960,1770,3270,6060,11300,18000)
METER_FIELDS=('sample','frames','input_rms','output_rms','input_peak','output_peak',*(f'cut{i}' for i in range(10)))
MAX_FRAMES=192000*120
MAX_BYTES=128*1024*1024


def safe(root,name,cap=MAX_BYTES):
    p=root/name
    if root.is_symlink() or p.is_symlink() or not p.is_file() or p.stat().st_size>cap:
        raise ValueError(f'Missing, linked or oversized capture file: {name}')
    return p


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def read_json(p):
    v=json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(v,dict):raise ValueError('Expected JSON object')
    return v


def pcm(p,rate,frames):
    with wave.open(str(p),'rb') as f:
        if (f.getnchannels(),f.getsampwidth(),f.getframerate(),f.getnframes(),f.getcomptype())!=(1,2,rate,frames,'NONE'):
            raise ValueError('All capture audio must be mono PCM16, with identical sample clocks')
        raw=f.readframes(frames)
    if len(raw)!=frames*2:raise ValueError('Truncated PCM')
    return np.frombuffer(raw,dtype='<i2').astype(np.float32)/32768


def table(p,fields,limit):
    with p.open(newline='',encoding='utf-8') as f:
        rows=csv.DictReader(f)
        if tuple(rows.fieldnames or [])!=fields:raise ValueError('Invalid capture CSV fields')
        result=[]
        for r in rows:
            if len(result)>=limit or None in r or any(v is None for v in r.values()):raise ValueError('Invalid or oversized CSV')
            result.append(r)
    if not result:raise ValueError('Empty capture CSV')
    return result


def validate(root,*,sealed=True):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('Capture must be a real directory')
    paths={name:safe(root,name,128*1024 if name=='capture.json' else MAX_BYTES) for name in FILES}
    hashes={name:digest(p) for name,p in paths.items()}
    if sealed:
        seal=read_json(safe(root,'bundle.json',16384))
        if seal!={'schema':'skell.demo.bundle.v1','sha256':hashes}:raise ValueError('Capture integrity check failed')
    meta=read_json(paths['capture.json'])
    if (meta.get('schema')!='skell.demo.capture.v1' or meta.get('origin')!='offline_core' or
        not re.fullmatch('[a-f0-9]{40}',str(meta.get('revision',''))) or meta.get('parameter')!='amount' or
        meta.get('meter')!='LiveMultibandDucker.copyDisplayBands channel 0'):
        raise ValueError('Unsupported capture schema or adapter')
    for key in ('product','stimulus'):
        if not isinstance(meta.get(key),str) or not 1<=len(meta[key])<=120 or any(ord(c)<32 for c in meta[key]):raise ValueError('Invalid capture label')
    rate,frames,latency=meta.get('sample_rate'),meta.get('frames'),meta.get('engine_latency_samples')
    if type(rate)!=int or not 8000<=rate<=192000 or type(frames)!=int or not rate<=frames<=min(MAX_FRAMES,rate*120) or type(latency)!=int or not 0<=latency<frames:
        raise ValueError('Unsupported capture timing')
    dry,wet,side=(pcm(paths[name],rate,frames) for name in ('dry.wav','processed.wav','sidechain.wav'))
    rows=table(paths['meters.csv'],METER_FIELDS,24000)
    measured=[];cursor=0
    for r in rows:
        pos,n=int(r['sample']),int(r['frames'])
        if pos!=cursor or not 1<=n<=rate or pos+n>frames:raise ValueError('Meter blocks must cover the sample clock exactly')
        vals=[float(r[k]) for k in METER_FIELDS[2:]]
        if not all(math.isfinite(v) for v in vals) or any(not 0<=v<=1 for v in vals[:4]) or any(not 0<=v<=24.0001 for v in vals[4:]):raise ValueError('Out-of-range meter')
        a,b=dry[pos:pos+n],wet[pos:pos+n]
        expected=(float(np.sqrt(np.mean(a*a))),float(np.sqrt(np.mean(b*b))),float(np.max(np.abs(a))),float(np.max(np.abs(b))))
        # Float capture vs PCM16 quantization: allow only rounding-scale differences.
        if max(abs(x-y) for x,y in zip(vals[:4],expected))>0.0001:raise ValueError('Meter/audio mismatch')
        measured.append((pos,n,*vals));cursor+=n
    if cursor!=frames:raise ValueError('Incomplete meter trace')
    events=[];starts={r[0] for r in measured}
    for r in table(paths['events.csv'],('sample','parameter','normalized'),256):
        pos=int(r['sample']);value=float(r['normalized'])
        if pos not in starts or (events and pos<=events[-1][0]) or r['parameter']!='amount' or not math.isfinite(value) or not 0<=value<=1:
            raise ValueError('Invalid or out-of-order amount event')
        events.append((pos,value))
    if events[0][0]!=0:raise ValueError('Capture requires initial parameter event')
    return {'meta':meta,'hashes':hashes,'meters':measured,'events':events,'audio':paths['processed.wav']}


def seal(root):
    v=validate(root,sealed=False)
    target=Path(root)/'bundle.json'
    with target.open('x',encoding='utf-8') as f:json.dump({'schema':'skell.demo.bundle.v1','sha256':v['hashes']},f,indent=2)
    return v


def font(size,bold=False):
    for p in (('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),(r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf')):
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default(size=size)


def render(root,out,*,fps=24,size=(1280,720)):
    capture=validate(root);meta=capture['meta'];rate=meta['sample_rate'];frames=meta['frames']
    rows=capture['meters'];events=capture['events'];starts=[r[0] for r in rows];event_starts=[e[0] for e in events]
    w,h=size
    if size!=(1280,720) or fps not in (24,30):raise ValueError('Unsupported demo output dimensions')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    total=round(frames*fps/rate)
    if abs(total/fps-frames/rate)>1/fps:raise ValueError('Invalid video timing')
    bg='#0d1412';panel='#17221f';accent='#a1f5a1';muted='#96a69d';white='#eff8f1';blue='#84c6ff'
    f14,f18,f22,f26,f34,f44=(font(n,n>=26) for n in (14,18,22,26,34,44))
    base=Image.new('RGB',size,bg);d=ImageDraw.Draw(base)
    d.text((38,24),'SKELLCORE  /  MEASURED DSP',font=f18,fill=accent)
    d.text((38,53),'Multiband sidechain ducking',font=f44,fill=white)
    d.text((40,112),'Real offline engine · Synthetic three-tone test · Channel 1',font=f18,fill=muted)
    d.rounded_rectangle((36,155,914,607),16,fill=panel);d.rounded_rectangle((934,155,1244,607),16,fill=panel)
    d.text((58,174),'MEASURED BAND ATTENUATION',font=f22,fill=white)
    for db in (0,6,12,18,24):
        y=240+db/24*254;d.line((100,y,891,y),fill='#34463e',width=1);d.text((52,y-10),f'{db} dB',font=f14,fill=muted)
    for i,hz in enumerate(BANDS):
        x=106+i*79;label=str(hz) if hz<1000 else f'{hz/1000:g}k';d.text((x+35,544),label,font=f14,fill=muted,anchor='mm')
    d.text((58,577),'Band cuts from the engine’s own display telemetry',font=f18,fill=muted)
    d.text((958,176),'AMOUNT',font=f22,fill=white)
    d.text((958,320),'INPUT RMS',font=f18,fill=blue);d.text((958,402),'OUTPUT RMS',font=f18,fill=accent)
    d.text((958,509),'ENGINE LATENCY',font=f18,fill=muted);d.text((958,538),f"{meta['engine_latency_samples']} samples",font=f26,fill=white)
    d.text((40,637),'OFFLINE CORE CAPTURE · NOT A LIVE DAW RECORDING',font=f18,fill=muted)
    d.text((40,670),f"Source {meta['revision'][:12]} · Input/output level is not loudness matched",font=f14,fill=muted)
    path=out/'measured_demo.mp4'
    # The video uses the original processed PCM; no gain matching or synthetic narration.
    args=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r',str(fps),'-i','pipe:0','-i',str(capture['audio']),'-map','0:v','-map','1:a','-frames:v',str(total),'-t',str(frames/rate),'-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(path)]
    def db(x):return max(-90,20*math.log10(max(x,1e-9)))
    with tempfile.TemporaryFile() as err:
        with subprocess.Popen(args,stdin=subprocess.PIPE,stderr=err) as proc:
            try:
                for frame in range(total):
                    sample=min(frames-1,round(frame*rate/fps));i=max(0,bisect.bisect_right(starts,sample)-1);row=rows[i];amount=events[bisect.bisect_right(event_starts,sample)-1][1]
                    im=base.copy();d=ImageDraw.Draw(im)
                    for band,cut in enumerate(row[6:]):
                        x=110+band*79;bottom=240+max(.18,min(24,cut))/24*254
                        d.rounded_rectangle((x,240,x+58,bottom+1),3,fill=accent if band==4 else '#53966d')
                        d.text((x+29,min(514,bottom+13)),f'{abs(cut):.1f}',font=f14,fill=white,anchor='mm')
                    d.text((958,211),f'{amount*100:.0f}%',font=f44,fill=accent)
                    d.rounded_rectangle((958,276,1220,290),7,fill='#34463e')
                    if amount>0:d.rounded_rectangle((958,276,958+262*amount,290),7,fill=accent)
                    for y,val,col in ((352,row[2],blue),(434,row[3],accent)):
                        d.text((958,y),f'{db(val):.1f} dBFS',font=f26,fill=col)
                    d.line((954,490,1225,490),fill='#34463e',width=1)
                    d.rounded_rectangle((40,616,1240,623),3,fill='#33473d');end=40+1200*sample/frames
                    d.rectangle((40,616,max(41,end),623),fill=accent)
                    d.text((1240,663),f'{sample/rate:05.2f} / {frames/rate:.2f}s',font=f18,fill=white,anchor='ra')
                    proc.stdin.write(im.tobytes())
                proc.stdin.close();code=proc.wait(timeout=90)
                if code:err.seek(0);raise RuntimeError(err.read().decode(errors='replace')[-2000:])
            except BaseException:
                if proc.poll() is None:proc.kill();proc.wait()
                path.unlink(missing_ok=True);raise
    info={'source':meta,'capture_sha256':capture['hashes'],'events':[{'sample':a,'amount':b} for a,b in events], 'meter_blocks':len(rows),'maximum_band_cut_db':max(max(r[6:]) for r in rows),'video_frames':total,'fps':fps,'video_sha256':digest(path)}
    (out/'measurement_report.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    return path


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    for action in ('seal','verify','render'):
        s=sub.add_parser(action);s.add_argument('capture',type=Path)
        if action=='render':s.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    try:
        if a.command=='render':print(render(a.capture,a.out))
        else:
            result=seal(a.capture) if a.command=='seal' else validate(a.capture)
            print(f"Verified {len(result['meters'])} measured blocks and {len(result['events'])} events")
        return 0
    except (ValueError,OSError,RuntimeError,TimeoutError) as exc:p.exit(1,f'Capture error: {exc}\n')

if __name__=='__main__':raise SystemExit(main())
