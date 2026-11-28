"""Skelly Motion non-destructive, frame-clock editing for uploaded recordings.

No model, network, or shell execution is required to interpret edit instructions.
The caller owns the asset registry; user input never supplies filesystem paths.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import math, re, subprocess, tempfile, os, time

FPS = 30
MAX_FRAMES = 30 * 60 * FPS
MAX_PIECES = 96
TIME = r'(?:\d{1,3}:\d{2}(?:\.\d{1,3})?|\d{1,5}(?:\.\d{1,3})?s?)'
ASSET = r'([a-zA-Z0-9][a-zA-Z0-9_-]{0,39})'

@dataclass(frozen=True)
class Piece:
    asset: str
    start: int
    length: int
    audio: str | None
    audio_start: int = 0


def time_frame(value: str) -> int:
    value = value.rstrip('s')
    if ':' in value:
        m, s = value.split(':')
        if Decimal(s) >= 60:
            raise ValueError('Seconds in a timestamp must be below 60')
        seconds = Decimal(m)*60 + Decimal(s)
    else:
        seconds = Decimal(value)
    return int((seconds*FPS).to_integral_value(rounding=ROUND_HALF_UP))


def duration_frames(seconds) -> int:
    if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Invalid media duration')
    return math.floor(seconds*FPS+1e-7)


def split(pieces: list[Piece], at: int) -> tuple[list[Piece], list[Piece]]:
    if not 0 <= at <= sum(p.length for p in pieces):
        raise ValueError('Edit timestamp is outside the current timeline')
    left, right = [], []
    for p in pieces:
        if at >= p.length:
            left.append(p); at -= p.length
        elif at <= 0:
            right.append(p)
        else:
            left.append(replace(p, length=at))
            right.append(replace(p, start=p.start+at, length=p.length-at,
                                 audio_start=p.audio_start+at if p.audio else 0))
            at = 0
    return left, right


def plan(assets: dict, instruction: str, *, current=None, events=None) -> dict:
    """Each clause addresses the timeline resulting from preceding clauses."""
    if 'source' not in assets or not isinstance(instruction, str) or len(instruction)>1000:
        raise ValueError('Provide a source and an editing instruction of up to 1000 characters')
    lengths = {k: duration_frames(v['duration']) for k,v in assets.items()}
    if not 0 < lengths['source'] <= MAX_FRAMES:
        raise ValueError('Source must be between one frame and 30 minutes')
    source_audio = 'source' if assets['source'].get('has_audio') else None
    pieces = [Piece(**p) for p in current['pieces']] if current is not None else [Piece('source', 0, lengths['source'], source_audio)]
    changes = []
    clauses = [s.strip().rstrip('.').strip() for s in re.split(r'[;\n]+',instruction) if s.strip()]
    if not 1 <= len(clauses) <= 12:
        raise ValueError('Enter 1–12 edits, separated by semicolons')
    def footage(name, offset, n, mode, original=None):
        name = name.lower()
        if name not in lengths or name == 'source':
            raise ValueError('Choose an uploaded footage ID from the library')
        if n<=0 or offset<0 or offset+n>lengths[name]:
            raise ValueError('Footage is too short for the requested range')
        if mode in ('keep audio','keep narration'):
            return [Piece(name, offset+sum(p.length for p in original[:i]), p.length, p.audio, p.audio_start)
                    for i,p in enumerate(original)]
        return [Piece(name,offset,n,name if mode!='muted' and assets[name].get('has_audio') else None,offset if mode!='muted' and assets[name].get('has_audio') else 0)]
    for clause in clauses:
        if clause.casefold() == 'keep original':
            if current is not None: raise ValueError('Use Reset sequence to restore the original')
            if len(clauses) != 1: raise ValueError('Keep original must be the only instruction')
            changes.append('Keep original timeline'); continue
        m = re.fullmatch(rf'(?:cut|remove|delete|trim out) (?:from )?({TIME}) (?:to|through|-) ({TIME})', clause, re.I)
        if m:
            a,b=map(time_frame,m.groups()); before,tail=split(pieces,a)
            if b<=a: raise ValueError('Cut end must be after start')
            _,after=split(tail,b-a); pieces=before+after
            changes.append(f'Cut frames {a}–{b}')
            if events is not None: events.append(('cut',a,b))
        else:
            m = re.fullmatch(rf'(?:insert|add) {ASSET} at ({TIME}) for ({TIME})(?: from ({TIME}))?(?: (muted|with audio))?',clause,re.I)
            if m:
                name,at,n,offset,mode=m.groups();at,n,offset=time_frame(at),time_frame(n),time_frame(offset or '0')
                before,after=split(pieces,at);pieces=before+footage(name,offset,n,(mode or 'with audio').lower())+after
                changes.append(f'Inserted {name} at frame {at} for {n} frames')
                if events is not None: events.append(('insert',at,n))
            else:
                m = re.fullmatch(rf'(?:replace|swap) (?:footage )?(?:from )?({TIME}) (?:to|-) ({TIME}) with {ASSET}(?: from ({TIME}))?(?: (keep audio|keep narration|muted|with audio))?',clause,re.I)
                if not m: raise ValueError('Unsupported edit. Use cut, insert, or replace with explicit timestamps and footage IDs.')
                a,b,name,offset,mode=m.groups();a,b,offset=time_frame(a),time_frame(b),time_frame(offset or '0')
                if b<=a: raise ValueError('Replacement end must be after start')
                before,tail=split(pieces,a);removed,after=split(tail,b-a)
                pieces=before+footage(name,offset,b-a,(mode or 'keep audio').lower(),removed)+after
                changes.append(f'Replaced frames {a}–{b} with {name}')
                if events is not None: events.append(('replace',a,b))
        total=sum(p.length for p in pieces)
        if not 0<total<=MAX_FRAMES or len(pieces)>MAX_PIECES:
            raise ValueError('Edit would create an empty, oversized or overly complex timeline')
    return {'fps':FPS,'frames':sum(p.length for p in pieces),'duration':sum(p.length for p in pieces)/FPS,'pieces':[asdict(p) for p in pieces], 'changes':changes,
            'clock':'Each clause uses the current edited timeline; timestamps snap to nearest 30 fps frame.',
            'warnings':['Hard cuts only; audio and video are re-encoded. Existing source and projects are unchanged.']}


def remap_words(words: list[dict], timeline: dict) -> list[dict]:
    """Keep complete original spoken words, map only pieces retaining source audio."""
    result=[];cursor=0
    # Coalesce adjacent source-audio ranges even across picture-only edits.
    spans=[]
    for p in timeline['pieces']:
        if p['audio']=='source':
            a,b=p['audio_start'],p['audio_start']+p['length']
            if spans and spans[-1][1]==a and spans[-1][2]+spans[-1][1]-spans[-1][0]==cursor:
                spans[-1]=(spans[-1][0],b,spans[-1][2])
            else:spans.append((a,b,cursor))
        cursor+=p['length']
    for a,b,out in spans:
        for w in words:
            try:s,e=float(w['start'])*FPS,float(w['end'])*FPS
            except (ValueError,TypeError,KeyError):continue
            if a<=s<e<=b:
                result.append({**w,'start':round((out+s-a)/FPS,6),'end':round((out+e-a)/FPS,6)})
    return result


def suggestions(timeline:dict, words:list[dict], library:dict, scene_times=()) -> list[dict]:
    """Rank suggestions using transcript timing, user tags and known scene boundaries.

    Never recommend cutting/replacing already-edited footage. Scene times and
    word timings are estimates, not semantic visual or acoustic verification.
    """
    result=[];duration=timeline['duration'];spoken=sorted(remap_words(words,timeline),key=lambda w:w['start'])
    # Only recommend changes within an uninterrupted untouched source region.
    regions=[];cursor=0;scene_points=[]
    for p in timeline['pieces']:
        end=cursor+p['length']
        if p['asset']=='source' and p['audio']=='source' and p['start']==p['audio_start']:
            regions.append((cursor/FPS,end/FPS))
            for t in scene_times:
                if isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t) and p['start']<=t*FPS<p['start']+p['length']:
                    scene_points.append((cursor+t*FPS-p['start'])/FPS)
        cursor=end
    def untouched(a,b):return any(lo<=a+1e-6 and b<=hi+1e-6 for lo,hi in regions)
    for prev,nxt in zip(spoken,spoken[1:]):
        gap=nxt['start']-prev['end']
        if gap>=1.2 and prev['end']>.5 and nxt['start']<duration-.5:
            a,b=round(prev['end']+.25,3),round(nxt['start']-.25,3)
            if not untouched(a,b):continue
            # Leave a breathing margin; never label transcript gaps as silence.
            result.append({'kind':'pacing','start':a,'end':b,'reason':f'{gap:.2f}s gap between timed spoken words; preserve a 250ms margin at both ends and audition before cutting.', 'instruction':f'cut {a:.3f} to {b:.3f}', 'priority':min(3.5,gap)})
    def tokens(value):return set(re.findall(r'[a-z0-9]+',str(value).lower()))
    candidates=[]
    for i,w in enumerate(spoken):
        at=float(w['start'])
        if at<1 or at>duration-1.5:continue
        nearby=set().union(*(tokens(x.get('text','')) for x in spoken[max(0,i-2):i+3] if abs(float(x['start'])-at)<=1.5))
        anchor=tokens(w.get('text',''))
        for name,asset in library.items():
            keys=set().union(*(tokens(k) for k in asset.get('keywords',[])))
            overlap=nearby & keys;direct=anchor & keys
            if not direct or asset['duration']<1.5:continue
            a=max(0,at-.15);b=min(a+2.5,duration, a+asset['duration'])
            # If an existing shot boundary is nearby, prefer it without moving
            # away from the matching phrase. Keep narration and the shot's fit.
            near=[x for x in scene_points if abs(x-a)<=.20]
            aligned=False
            if near:
                proposed=min(near,key=lambda x:abs(x-a))
                end=min(proposed+2.5,duration,proposed+asset['duration'])
                if end-proposed>=1.5 and untouched(proposed,end):a,b=proposed,end;aligned=True
            a,b=round(a,3),round(b,3)
            if b-a<1.5 or not untouched(a,b):continue
            reason=f'Footage {name} matches tagged narration ({", ".join(sorted(overlap))}); preserve narration.'
            if aligned:reason+=' Start aligned to a detected source scene boundary.'
            candidates.append({'kind':'relevant cutaway','start':a,'end':b,'reason':reason+' Review visual fit.', 'instruction':f'replace {a:.3f} to {b:.3f} with {name} keep audio','priority':2.4+min(1.2,.4*len(overlap))+(.25 if aligned else 0),'asset':name})
    selected=[];used=set()
    for c in sorted(candidates,key=lambda x:(-x['priority'],x['start'],x['asset'])):
        if c['asset'] in used or any(c['start']<v['end']+3 and c['end']+3>v['start'] for v in selected):continue
        selected.append(c);used.add(c['asset'])
        if len(selected)>=3:break
    result.extend(selected)
    if any(hi-lo>=12 for lo,hi in regions) and library:
        result.append({'kind':'visual variety','reason':'Unedited source shot exceeds 12 seconds; consider a relevant uploaded cutaway.','priority':1.0})
    return [{k:v for k,v in item.items() if k not in ('priority','asset')} for item in sorted(result,key=lambda x:-x['priority'])[:6]]


def render(timeline:dict, assets:dict, output:Path, *, width=1280,height=720,timeout=1800,check_cancel=lambda:None,progress=lambda n,total:None):
    """Render checked, server-generated plan; stage segments then atomically publish.

    Segments use independent video/audio trims. 48 kHz is divisible by 30 fps.
    Matroska/PCM staging avoids per-piece AAC priming; encode AAC once at publish.
    """
    if width%2 or height%2 or min(width,height)<16: raise ValueError('Invalid dimensions')
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    def run(args):
        check_cancel()
        with tempfile.TemporaryFile() as err:
            with subprocess.Popen(['ffmpeg','-hide_banner','-nostdin','-v','error','-y',*args],stdout=subprocess.DEVNULL,stderr=err,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0) as proc:
                deadline=time.monotonic()+timeout
                try:
                    while proc.poll() is None:
                        check_cancel()
                        if time.monotonic()>deadline:raise TimeoutError('Timeline render timed out')
                        time.sleep(.05)
                    if proc.returncode:
                        err.seek(0,2);err.seek(max(0,err.tell()-500));raise RuntimeError(err.read().decode('utf-8','replace'))
                finally:
                    if proc.poll() is None:proc.kill();proc.wait()
    def path(name):
        p=Path(assets[name]['path'])
        if not p.is_file() or p.is_symlink():raise ValueError('Media is missing or invalid')
        return str(p.resolve())
    with tempfile.TemporaryDirectory(prefix='timeline-',dir=output.parent) as tmp:
        root=Path(tmp);files=[]
        for i,p in enumerate(timeline['pieces']):
            n=p['length']; start=p['start']/FPS; length=n/FPS; samples=n*1600
            args=['-ss',f'{start:.9f}','-i',path(p['asset'])]
            if p['audio'] is not None:args+=['-ss',f"{p['audio_start']/FPS:.9f}",'-i',path(p['audio'])]
            else:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            vf=f'[0:v]fps=30,scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration={length:.9f},trim=end_frame={n},setpts=PTS-STARTPTS[v]'
            af=f'[1:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,apad,atrim=end_sample={samples},asetpts=PTS-STARTPTS[a]'
            target=root/f'part-{i:03d}.mkv'
            run([*args,'-filter_complex_threads','1','-filter_complex',vf+';'+af,'-map','[v]','-map','[a]','-c:v','libx264','-preset','veryfast','-crf','18','-threads','2','-c:a','pcm_s16le','-t',f'{length:.9f}',str(target)])
            files.append(target);progress(i+1,len(timeline['pieces'])+1)
        # The manifest uses generated basenames only, no user path interpolation.
        manifest=root/'concat.txt';manifest.write_text(''.join(f"file '{p.name}'\n" for p in files),encoding='utf-8')
        staged=root/'result.mp4';run(['-f','concat','-safe','1','-i',str(manifest),'-map','0:v:0','-map','0:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(staged)])
        if not staged.is_file() or not staged.stat().st_size:raise RuntimeError('Timeline output was not created')
        check_cancel();os.replace(staged,output);progress(len(files)+1,len(files)+1)
