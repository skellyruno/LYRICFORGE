"""Prompt-to-video orchestration. Local fact-based draft, explicit agent scripts,
optional operator-installed voice providers. No implicit network or model downloads.
"""
from __future__ import annotations
import json, os, re, shutil, subprocess, tempfile, time, uuid, wave
from pathlib import Path
import numpy as np
import studio_performance as perf
import studio_voice as vs

MAX_CHAPTERS=120
MAX_SCRIPT_WORDS=3300
VOICES={'auto','piper','system','draft'}

def clean(value, limit):
    return ' '.join(str(value or '').split())[:limit]

def draft_script(product, brief, facts, target_seconds=90, story="tutorial"):
    """No claim generation from a product name or filename. Facts are supplied by the owner."""
    product=clean(product,80);brief=clean(brief,1000)
    if not product: raise ValueError('Enter a plugin or subject name')
    if not isinstance(facts,list) or len(facts)>100: raise ValueError('Provide up to 100 confirmed facts')
    rows=[clean(f,280) for f in facts if isinstance(f,str) and clean(f,280)]
    if not rows: raise ValueError('Add at least one confirmed product fact or supply a script. The creator does not invent features from images.')
    target_seconds=max(15,min(1200,int(target_seconds)))
    if story not in vs.FORMATS: raise ValueError('Unknown story format')
    openings={'tutorial':f'Here is a closer look at {product}.','review':f'Let us examine {product}, one documented feature at a time.','advertisement':f'Meet {product}. Here is what to explore.','documentary':f'This is the story of how {product} works, starting with its documented features.'}
    endings={'tutorial':'Try the controls with your own material, and listen to the result in context.','review':'Compare the sound using the same source and level before drawing a conclusion.','advertisement':'Explore the controls with your own material and decide if they fit your workflow.','documentary':'These are the documented features. The next step is to see and hear them in context.'}
    # Allocate the requested length to real facts rather than artificial silence/repetition.
    budget=round(target_seconds*2.35)
    chapters=[{'title':product,'narration':openings[story],'visual_hint':product}]
    words=len(chapters[0]['narration'].split())
    for fact in rows:
        if words+len(fact.split())>budget and len(chapters)>1: break
        title=' '.join(fact.split()[:5]).rstrip('.,;:')[:52]
        chapters.append({'title':title,'narration':fact.rstrip('.!?')+'.','visual_hint':fact[:180]})
        words+=len(fact.split())
    chapters.append({'title':'Try it in context','narration':endings[story],'visual_hint':product+' overview'})
    result=validate_script(chapters)
    estimate=round(sum(len(r['narration'].split()) for r in result)/2.35+len(result)*.18,1)
    return {'product':product,'brief':brief,'chapters':result,'target_seconds':target_seconds,'estimated_seconds':estimate,'origin':'local fact-based draft','story':story,'warnings':(['Not enough confirmed material for the requested length. Add facts or have an agent supply a longer approved script.'] if estimate<target_seconds*.75 else [])}

def validate_script(chapters):
    if not isinstance(chapters,list) or not 1<=len(chapters)<=MAX_CHAPTERS: raise ValueError('Script needs 1–120 chapters')
    out=[];count=0
    for row in chapters:
        if not isinstance(row,dict):raise ValueError('Each chapter must be an object')
        raw=row.get('narration')
        if not isinstance(raw,str) or not raw.strip() or len(raw)>1200:raise ValueError('Chapter narration must contain 1–1200 characters')
        text=clean(raw,1200);count+=len(text.split())
        title=clean(row.get('title'),80) or ' '.join(text.split()[:5])
        out.append({'title':title,'narration':text,'visual_hint':clean(row.get('visual_hint'),300)})
    if count>MAX_SCRIPT_WORDS:raise ValueError('Script exceeds 3300 words')
    return out

def voice_options():
    # Return capabilities, not private executable/model paths.
    exe=os.environ.get('LYRICFORGE_PIPER_EXE') or shutil.which('piper')
    model=os.environ.get('LYRICFORGE_PIPER_MODEL','')
    piper=bool(exe and (Path(exe).is_file() or shutil.which(exe)) and model and Path(model).is_file() and Path(model+'.json').is_file())
    return {'piper':piper,'system':os.name=='nt' and bool(shutil.which('powershell.exe')),'draft':bool(shutil.which('espeak-ng') or shutil.which('espeak'))}

def resolve_voice(voice):
    if voice not in VOICES:raise ValueError('Unknown narration provider')
    options=voice_options()
    if voice=='auto':
        voice=next((name for name in ('piper','system','draft') if options[name]),'')
    if not options.get(voice):raise ValueError('Requested narrator is unavailable. Install a local Piper voice or choose another available provider; recorded narration is supported by the regular editor.')
    return voice

def run_checked(args, *, input_text=None, check_cancel=lambda:None, timeout=120):
    # File-backed stdin/stderr avoids pipe deadlocks and permits prompt cancellation.
    with tempfile.TemporaryFile() as source,tempfile.TemporaryFile() as err:
        if input_text is not None:source.write(input_text.encode('utf-8'));source.seek(0)
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0
        with subprocess.Popen(args,stdin=source,stdout=subprocess.DEVNULL,stderr=err,creationflags=flags) as proc:
            deadline=time.monotonic()+timeout
            try:
                while proc.poll() is None:
                    check_cancel()
                    if time.monotonic()>deadline:raise TimeoutError('Narration process timed out')
                    time.sleep(.05)
                if proc.returncode:raise RuntimeError(f'Narration/media process failed (exit {proc.returncode})')
            finally:
                if proc.poll() is None:proc.kill();proc.wait()

def synthesize_phrase(text, target, voice, speed, check_cancel, pitch=43):
    if voice=='piper':
        exe=os.environ.get('LYRICFORGE_PIPER_EXE') or shutil.which('piper')
        model=os.environ['LYRICFORGE_PIPER_MODEL']
        run_checked([exe,'-m',model,'-f',str(target)],input_text=text+'\n',check_cancel=check_cancel)
    elif voice=='system':
        # PowerShell script is fixed. The text and output are paths, never interpolated into code.
        script=target.with_suffix('.ps1');txt=target.with_suffix('.txt');txt.write_text(text,encoding='utf-8-sig')
        script.write_text('param([string]$InputPath,[string]$OutputPath,[int]$Rate)\nAdd-Type -AssemblyName System.Speech\n$s=New-Object System.Speech.Synthesis.SpeechSynthesizer\ntry { $s.Rate=$Rate; $s.SetOutputToWaveFile($OutputPath); $s.Speak([IO.File]::ReadAllText($InputPath)) } finally { $s.Dispose() }\n',encoding='utf-8-sig')
        run_checked(['powershell.exe','-NoProfile','-NonInteractive','-File',str(script),str(txt),str(target),str(round((speed-1)*10))],check_cancel=check_cancel)
    else:
        exe=shutil.which('espeak-ng') or shutil.which('espeak')
        run_checked([exe,'-v','en-us+m3','-s',str(round(150*speed)),'-p',str(pitch),'-a','95','-w',str(target),'--stdin'],input_text=text,check_cancel=check_cancel)

def split_phrases(text):
    """Bound clip text below editor's 300-char limit and keep natural pauses."""
    result=[]
    for sentence in re.split(r'(?<=[.!?])\s+',text):
        current=[]
        for word in sentence.split():
            if len(word)>100:raise ValueError('Script contains an excessively long word')
            if current and (len(' '.join(current+[word]))>240 or len(current)>=30):result.append(' '.join(current));current=[]
            current.append(word)
            if len(current)>=12 and word.endswith((',', ';', ':')):
                result.append(' '.join(current));current=[]
        if current:result.append(' '.join(current))
    return result

def narration(chapters, output, voice='auto', speed=1., check_cancel=lambda:None, progress=lambda i,n:None, *, delivery='neutral', pronunciation=None):
    chapters=validate_script(chapters);voice=resolve_voice(voice)
    speed,phrase_gap,chapter_gap,pitch=vs.delivery(delivery,speed);pronunciation=vs.speech_dictionary(pronunciation or {})
    rate=24000;lines=[];cursor=0;output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='creator-',dir=output.parent) as root:
        root=Path(root);staged=root/'voice.wav'
        with wave.open(str(staged),'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
            for i,chapter in enumerate(chapters):
                check_cancel();progress(i,len(chapters));phrases=split_phrases(chapter['narration'])
                for j,phrase in enumerate(phrases):
                    src=root/'phrase.wav';dst=root/'pcm.wav';src.unlink(missing_ok=True);dst.unlink(missing_ok=True)
                    synthesize_phrase(vs.spoken(phrase,pronunciation),src,voice,speed,check_cancel,pitch)
                    run_checked(['ffmpeg','-v','error','-nostdin','-y','-i',str(src),'-ac','1','-ar',str(rate),*(['-af',f'atempo={speed:.3f}'] if voice=='piper' and speed!=1. else []),'-c:a','pcm_s16le',str(dst)],check_cancel=check_cancel)
                    with wave.open(str(dst),'rb') as reader:
                        n=reader.getnframes()
                        if not 0<n<=rate*100:raise ValueError('Invalid synthesized phrase length')
                        pcm=reader.readframes(n)
                    pcm=vs.phrase_pcm(pcm,rate);n=len(pcm)//2
                    if cursor+n+rate>rate*1800:raise ValueError('Narration exceeds 30 minutes')
                    samples=np.frombuffer(pcm,dtype='<i2');peak=float(np.max(np.abs(samples.astype(np.float32))))
                    if peak<5:raise RuntimeError('Narrator generated silent audio')
                    # Align phrase to measured audio. Word locations within phrase are estimates,
                    # not forced alignment or ASR evidence.
                    active=np.flatnonzero(np.abs(samples.astype(np.int32))>max(100,peak*.015))
                    a=(cursor+(int(active[0]) if len(active) else 0))/rate;b=(cursor+(int(active[-1])+1 if len(active) else n))/rate
                    if b-a<.08:a=cursor/rate;b=(cursor+n)/rate
                    tokens=phrase.split();weights=np.array([max(1,len(vs.spoken(x,pronunciation).strip('.,!?;:').replace(' ',''))) for x in tokens],dtype=float);edges=np.r_[0,np.cumsum(weights)/sum(weights)]
                    words=[{'text':t,'start':float(a+(b-a)*edges[k]),'end':float(a+(b-a)*edges[k+1])} for k,t in enumerate(tokens)]
                    if len(lines)>=500:raise ValueError('Narration exceeds 500 editor clips')
                    lines.append({'id':uuid.uuid4().hex[:12],'text':phrase,'start':a,'end':b,'words':words,'chapter_title':chapter['title'],'visual_hint':chapter['visual_hint']})
                    wav.writeframes(pcm);cursor+=n
                    gap=round(rate*vs.pause_after(phrase,phrase_gap,chapter_gap,j+1==len(phrases)));wav.writeframes(b'\0\0'*gap);cursor+=gap
        check_cancel();perf.publish_staged_file(staged,output)
    return {'duration':cursor/rate,'lines':lines,'provider':voice,'delivery':delivery,'word_timing':'estimated within measured phrase audio','warnings':(['Draft synthesizer, not neural narration.'] if voice=='draft' else ['System voice quality depends on installed Windows speech voices.'] if voice=='system' else [])}
