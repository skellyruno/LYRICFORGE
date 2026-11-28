"""Render independent picture and sound tracks against the fixed sequence clock."""
from pathlib import Path
import os, subprocess, tempfile, time, wave, array, sys
import studio_timeline as tl
import studio_sequence as seq
import studio_edit as edit
import studio_performance as perf

def run(args, cancel, timeout=1800):
    with tempfile.TemporaryFile() as err:
        p=subprocess.Popen(['ffmpeg','-hide_banner','-nostdin','-v','error','-y',*args],stdout=subprocess.DEVNULL,stderr=err,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
        try:
            end=time.monotonic()+timeout
            while p.poll() is None:
                cancel()
                if time.monotonic()>end:raise TimeoutError('Sequence render timed out')
                time.sleep(.05)
            if p.returncode:
                err.seek(0,2);err.seek(max(0,err.tell()-1000));raise RuntimeError(err.read().decode('utf-8','replace'))
        finally:
            if p.poll() is None:p.kill();p.wait()

def render(state,assets,target,*,width=1280,height=720,cancel=lambda:None,progress=lambda n:None,encoder="cpu"):
    seq.validate(state,assets);total=state['base']['frames'];seconds=total/30; samples=total*1600
    target=Path(target)
    def media(key):return str(Path(assets[key]['path']).resolve())
    with tempfile.TemporaryDirectory(prefix='sequence-',dir=target.parent) as tmp:
        tmp=Path(tmp);base=tmp/'base.mp4'
        tl.render(state['base'],assets,base,width=width,height=height,check_cancel=cancel,progress=lambda n,t:progress(round(65*n/t)))
        args=['-i',str(base)]; filters=['[0:v]setpts=PTS-STARTPTS[v0]','[0:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=N/SR/TB,apad,atrim=end_sample='+str(samples)+'[voice]'];video='v0';idx=1;audio=[];music=[]
        for i,x in enumerate(state['layers']):
            n=x['length'];at=x['at'];dur=n/30;label=f'l{i}'
            if x['kind']=='visual':
                args+=['-ss',f"{x['offset']/30:.9f}",'-i',media(x['asset'])]
                f=f'[{idx}:v]fps=30,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuva420p,trim=end_frame={n},setpts=PTS-STARTPTS'
                fi=x.get('fade_in',x['fade']);fo=x.get('fade_out',x['fade'])
                if fi:f+=f',fade=t=in:s=0:n={fi}:alpha=1'
                if fo:f+=f',fade=t=out:s={n-fo}:n={fo}:alpha=1'
                filters.append(f+f',setpts=PTS+{at}/30/TB[{label}]')
                filters.append(f'[{video}][{label}]overlay=eof_action=pass:repeatlast=0:enable=gte(t\\,{at}/30)*lt(t\\,{at+n}/30)[v{i+1}]');video=f'v{i+1}'
            else:
                if x['kind']=='music':args+=['-ss',f"{x['offset']/30:.9f}",'-i',media(x['asset'])]
                else:
                    path=tmp/f'sfx-{i}.wav';a=array.array('h',edit.synth_sfx(x['effect']))
                    if sys.byteorder=='big':a.byteswap()
                    with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(edit.SFX_RATE);w.writeframes(a.tobytes())
                    args+=['-i',str(path)]
                f=f'[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=N/SR/TB,apad'
                if x['kind']=='sfx' and x.get('offset',0):f+=f',atrim=start_sample={x["offset"]*1600},asetpts=N/SR/TB'
                f+=f',atrim=end_sample={n*1600},volume={x["gain"]:.6f}'
                if x['kind']=='music':
                    if x['fade_in']:f+=f",afade=t=in:ss=0:ns={x['fade_in']*1600}"
                    if x['fade_out']:f+=f",afade=t=out:ss={(n-x['fade_out'])*1600}:ns={x['fade_out']*1600}"
                f+=f',adelay={at*1600}S:all=1,apad,atrim=end_sample={samples}[{label}]';filters.append(f)
                if x['kind']=='music' and x['duck']:music.append(label)
                else:audio.append(label)
            idx+=1
        for i,t in enumerate(state['transitions']):
            a,h=t['at'],t['half'];label=f't{i}'
            filters.append(f'[{video}]fade=t=out:st={(a-h)/30:.9f}:d={h/30:.9f}:enable=gte(t\\,{a-h}/30)*lt(t\\,{a}/30),fade=t=in:st={a/30:.9f}:d={h/30:.9f}:enable=gte(t\\,{a}/30)*lt(t\\,{a+h}/30)[{label}]');video=label
        voice='voice'
        if music:
            filters.append('[voice]asplit=2[voiceout][key]');voice='voiceout'
            if len(music)>1:filters.append(''.join(f'[{x}]' for x in music)+f'amix=inputs={len(music)}:normalize=0[bed]');bed='bed'
            else:bed=music[0]
            filters.append(f'[{bed}][key]sidechaincompress=threshold=0.025:ratio=5:attack=20:release=250[ducked]');audio.append('ducked')
        mix=[voice]+audio
        filters.append(''.join(f'[{x}]' for x in mix)+f'amix=inputs={len(mix)}:normalize=0,alimiter=limit=0.95:level=0:latency=1,aresample=48000,apad,atrim=end_sample={samples},asetpts=N/SR/TB[aout]')
        filters.append(f'[{video}]format=yuv420p,trim=end_frame={total},settb=1/30,setpts=N[vout]')
        out=tmp/'result.mp4';graph=tmp/'graph.txt';graph.write_text(';'.join(filters),encoding='utf-8')
        # Only the final H.264 encode can be accelerated. Base decoding,
        # compositing and the audio mix remain on CPU. Reuse the app's real
        # encoder probe; an advertised codec is not a working GPU.
        installed=perf.available_gpu_encoders() if encoder!='cpu' else ()
        selected=perf.choose_encoder(encoder,installed);fallback=''
        if encoder=='gpu' and selected=='libx264':fallback='No working hardware encoder detected'
        cpu_args=['-c:v','libx264','-crf','18','-preset','veryfast','-threads','2']
        def encode(codec):
            opts=cpu_args if codec=='libx264' else perf.encode_args(codec,'quality',width,height,2)
            run([*args,'-filter_complex_threads','1','-filter_complex_script',str(graph),'-map','[vout]','-map','[aout]',*opts,'-c:a','aac','-b:a','192k','-r','30','-fps_mode','cfr','-video_track_timescale','30000','-movflags','+faststart',str(out)],cancel)
        try:encode(selected)
        except RuntimeError as exc:
            cancel()
            if selected=='libx264':raise
            fallback=f'{selected} failed during sequence encoding; retried on CPU'
            out.unlink(missing_ok=True);selected='libx264';encode(selected)
        cancel();seq.validate(state,assets);os.replace(out,target);progress(100)
        return {"encoder":selected,"fallback":fallback,"gpu_scope":"Final H.264 encoding only"}
