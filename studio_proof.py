"""Explicit matched-timestamp audio evidence for Creator; no independent source identity claim."""
from __future__ import annotations
import hashlib, math, os, tempfile, uuid, wave
from pathlib import Path

RATE=48000
CHANNELS=2
WIDTH=3
FRAME=CHANNELS*WIDTH


def append_proof(voice, before, after, result, start, seconds, run_checked, check_cancel=lambda:None):
    """Append equal playback-gain dry/wet excerpts; retain original uploaded bytes.

    Caller must use the same source take and compensate any plugin latency.
    Decode both to stereo PCM24 at a fixed clock, without normalization or mixing.
    Video labels and audio intervals share the same exact sample clock.
    """
    voice,before,after=map(Path,(voice,before,after))
    if not math.isfinite(start) or not 0<=start<=1800 or not math.isfinite(seconds) or not 2<=seconds<=10:
        raise ValueError('Listening comparison needs a nonnegative start and 2–10 seconds per version')
    if len(result['lines'])>498:raise ValueError('Leave room for two listening clips')
    if result['duration']+2*seconds+.5>1800:raise ValueError('Creator audio exceeds 30 minutes')
    if any(p.is_symlink() or not p.is_file() or p.stat().st_size>150*1024*1024 for p in (before,after)):
        raise ValueError('Missing or oversized comparison source')
    def digest(path):
        with path.open('rb') as src:return hashlib.file_digest(src,'sha256').hexdigest()
    hashes=[digest(p) for p in (before,after)]
    if hashes[0]==hashes[1]:raise ValueError('Before and after files must differ')
    # 8000 samples = 1/6s, common boundary for both supported video frame clocks.
    count=round(seconds*6)*8000;offset=round(start*RATE)
    with tempfile.TemporaryDirectory(prefix='proof-',dir=voice.parent) as name:
        root=Path(name);staged=root/'combined.wav'
        # FFmpeg raw PCM avoids dependence on WAVE_FORMAT_EXTENSIBLE parsing.
        def raw(source,target,extra=()):
            run_checked(['ffmpeg','-v','error','-nostdin','-y','-threads','1','-i',str(source),*extra,'-vn','-ac','2','-ar',str(RATE),'-f','s24le',str(target)],check_cancel=check_cancel,timeout=180)
        base=root/'narration.pcm';raw(voice,base,('-t','1801'))
        if base.stat().st_size%FRAME:raise RuntimeError('Invalid narration PCM')
        n=base.stat().st_size//FRAME
        if not 0<n<=RATE*1800:raise ValueError('Invalid narration duration')
        # Half-second breath before the listening demonstration; round to 1/6s.
        cursor=((n+RATE//2+7999)//8000)*8000
        if cursor+2*count>RATE*1800:raise ValueError('Creator audio exceeds 30 minutes')
        clips=[]
        for i,source in enumerate((before,after)):
            check_cancel();path=root/f'proof-{i}.pcm'
            raw(source,path,('-ss',f'{offset/RATE:.9f}','-t',f'{count/RATE:.9f}'))
            if path.stat().st_size!=count*FRAME:raise ValueError('Both source files must cover the complete comparison excerpt')
            clips.append(path)
        def copy_pcm(path,out):
            with path.open('rb') as src:
                while True:
                    check_cancel();buf=src.read(FRAME*RATE)
                    if not buf:break
                    out.writeframesraw(buf)
        rows=[]
        with wave.open(str(staged),'wb') as out:
            out.setparams((CHANNELS,WIDTH,RATE,0,'NONE','not compressed'))
            copy_pcm(base,out);out.writeframesraw(bytes((cursor-n)*FRAME))
            for label,path in zip(('DRY / BEFORE','PROCESSED / AFTER'),clips):
                a=cursor/RATE;copy_pcm(path,out);cursor+=count;b=cursor/RATE
                rows.append({'id':uuid.uuid4().hex[:12],'text':label,'start':a,'end':b,'words':[], 'chapter_title':label,'visual_hint':'Actual supplied audio comparison','proof_label':label})
        check_cancel();os.replace(staged,voice)
    return {**result,'duration':cursor/RATE,'lines':[ *result['lines'],*rows],
            'audio_proof':{'source_sha256':hashes,'source_start':offset/RATE,'seconds_each':count/RATE,'sample_rate':RATE,'channels':2,'playback_gain':'unchanged','alignment':'same requested timestamps; source identity and latency must be verified by author','segments':[{k:r[k] for k in ('id','text','start','end','proof_label')} for r in rows]},
            'warnings':[ *result.get('warnings',[]),'Comparison uses unchanged playback gain and same requested timestamps; verify source identity and plugin latency.']}
