"""End-to-end ASS, motion, audio and H.264 encode parity on identical input."""
import argparse, json, statistics, time
from pathlib import Path
from audit_media import run, compare

ASS='''[Script Info]
ScriptType: v4.00+
PlayResX: 640
PlayResY: 360
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,32,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,2,10,10,14,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.20,0:00:02.80,Default,,0,0,0,,SKELLYMOTION | Encoding parity
'''

def audit(old,new,out):
    old,new,out=Path(old).resolve(),Path(new).resolve(),Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    ass=out/'parity.ass';ass.write_text(ASS,encoding='utf-8')
    # Use a relative subtitle path so Windows drive colons never enter the filter parser.
    import os
    previous=Path.cwd();os.chdir(out)
    try:
        run(old,['-v','error','-y','-f','lavfi','-i','testsrc2=s=640x360:r=30:d=3','-f','lavfi','-i','sine=f=440:d=3:sample_rate=48000','-c:v','libx264','-preset','fast','-threads','2','-c:a','aac','fixture.mp4'])
        command=['-v','error','-y','-threads','2','-filter_threads','1','-i','fixture.mp4','-vf','scale=640:360,eq=contrast=1.1:brightness=0.02,ass=parity.ass,format=yuv420p','-af','highpass=f=80,acompressor=threshold=0.1:ratio=2,volume=0.8','-c:v','libx264','-preset','fast','-crf','20','-threads','2','-c:a','aac','-b:a','192k','-movflags','+faststart']
        times={};paths={}
        for label,exe in [('baseline',old),('candidate',new)]:
            path=label+'.mp4';paths[label]=path;elapsed=[]
            for _ in range(3):
                start=time.perf_counter();run(exe,[*command,path]);elapsed.append(time.perf_counter()-start)
            times[label]={'median_seconds':round(statistics.median(elapsed),4),'runs_seconds':[round(x,4) for x in elapsed],'bytes':Path(path).stat().st_size}
        video=lambda p:run(old,['-v','error','-threads','1','-i',p,'-an','-c:v','rawvideo','-pix_fmt','rgb24','-threads','1','-f','rawvideo','pipe:1'])
        audio=lambda p:run(old,['-v','error','-threads','1','-i',p,'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le','-f','s16le','pipe:1'])
        v=compare(video(paths['baseline']),video(paths['candidate']),'uint8');a=compare(audio(paths['baseline']),audio(paths['candidate']),'<i2')
        result={'video':v,'audio':a,'encode':times,'passed':v['psnr_or_snr_db']>=35 and a['psnr_or_snr_db']>=30,'note':'Synthetic ASS/filter/encode fixture; no claim about GPU performance.'}
        (out/'render-parity.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
        if not result['passed']:raise RuntimeError('Rendered output parity failed')
    finally:os.chdir(previous)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('candidate');p.add_argument('out');a=p.parse_args();audit(a.baseline,a.candidate,a.out)
