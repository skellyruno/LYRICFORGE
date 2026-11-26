"""Voice Studio: explicit delivery, pronunciation and timing for recorded narration.
Speech substitutions affect synthesis only; displayed captions retain the script.
No network, microphone access or external model download occurs in this module.
"""
from __future__ import annotations
import math
import re
import tempfile
import uuid
import wave
from pathlib import Path
import numpy as np
import studio_performance as perf

DELIVERY = {
    'neutral': (1.0, .12, .23, 43),
    'tutorial': (.96, .18, .36, 43),
    'energetic': (1.07, .09, .18, 49),
    'documentary': (.91, .22, .40, 38),
}
FORMATS = {'tutorial', 'review', 'advertisement', 'documentary'}
# Common audio initialisms only; owner-supplied pronunciations override these.
TECH_SPEECH = {'dsp':'D S P', 'vst':'V S T', 'vst3':'V S T three',
               'daw':'D A W', 'gui':'G U I', 'cpu':'C P U',
               'rms':'R M S', 'lufs':'L U F S', 'fft':'F F T'}

def speech_dictionary(values):
    return {**TECH_SPEECH, **dictionary(values)}

def phrase_pcm(pcm, rate):
    """Remove only surplus exterior silence; retain quiet phoneme safety margins."""
    samples=np.frombuffer(pcm,dtype='<i2')
    if not samples.size: raise RuntimeError('Narrator generated empty audio')
    magnitude=np.abs(samples.astype(np.int32))
    peak=int(magnitude.max())
    if peak<5: raise RuntimeError('Narrator generated silent audio')
    active=np.flatnonzero(magnitude>max(30,peak*.006))
    if not len(active): return pcm
    start=max(0,int(active[0])-round(.055*rate))
    end=min(len(samples),int(active[-1])+1+round(.080*rate))
    # Keep short or very quiet material intact; do not gate internal pauses.
    if end-start<round(.12*rate): return pcm
    if start<round(.04*rate): start=0
    if len(samples)-end<round(.04*rate): end=len(samples)
    return samples[start:end].tobytes()

def pause_after(text, phrase_gap, chapter_gap, final_phrase):
    if final_phrase:return chapter_gap
    if text.rstrip().endswith((',', ';', ':')):return phrase_gap*.65
    if text.rstrip().endswith(('?', '!')):return phrase_gap*1.15
    if text.rstrip().endswith('.'):return phrase_gap
    return phrase_gap*.45


def delivery(name, speed):
    if name not in DELIVERY: raise ValueError('Unknown narration delivery')
    if not math.isfinite(float(speed)) or not .8 <= float(speed) <= 1.2: raise ValueError('Narration speed must be 0.8–1.2')
    factor, phrase_gap, chapter_gap, pitch = DELIVERY[name]
    return min(1.25,max(.75,float(speed)*factor)), phrase_gap, chapter_gap, pitch


def dictionary(values):
    if not isinstance(values, dict) or len(values)>40: raise ValueError('Use up to 40 pronunciation replacements')
    result={}
    for term, replacement in values.items():
        if not isinstance(term,str) or not isinstance(replacement,str): raise ValueError('Pronunciation entries must be text')
        term, replacement=term.strip(),replacement.strip()
        if not term or not replacement or len(term)>64 or len(replacement)>100 or any(ord(ch)<32 for ch in term+replacement): raise ValueError('Invalid pronunciation replacement')
        result[term.casefold()]=replacement
    return result


def spoken(text, values):
    if not values: return text
    # Single-pass longest match, so replacements are not recursively expanded.
    pattern=r'(?<!\w)(?:'+'|'.join(re.escape(k) for k in sorted(values,key=len,reverse=True))+r')(?!\w)'
    result=re.sub(pattern,lambda m:values.get(m.group(0).casefold(),m.group(0)),text,flags=re.IGNORECASE)
    if len(result)>1800: raise ValueError('Pronunciation expansion is too long')
    return result


def recording_lines(chapters, duration, chapter_starts, split_phrases):
    if not math.isfinite(duration) or not 0.5 <= duration <= 1800: raise ValueError('Recording must be between 0.5 seconds and 30 minutes')
    if chapter_starts:
        if len(chapter_starts)!=len(chapters): raise ValueError('Provide one timestamp for each chapter, starting at zero')
        starts=[float(t) for t in chapter_starts]
        if any(not math.isfinite(x) for x in starts) or abs(starts[0])>.05 or any(b-a<.08 for a,b in zip(starts,starts[1:])) or starts[-1]>=duration-.08: raise ValueError('Chapter timestamps must increase within the recording')
        starts[0]=0.
        origin='manual chapter timestamps; words estimated within chapters'
    else:
        weights=np.array([max(1,len(c['narration'].split())) for c in chapters],dtype=float)
        starts=list(duration*np.r_[0,np.cumsum(weights[:-1])]/weights.sum())
        origin='estimated from script length; review timing against recording'
    rows=[]
    for chapter,a,b in zip(chapters,starts,[*starts[1:],duration]):
        phrases=split_phrases(chapter['narration']);tokens=[p.split() for p in phrases]
        weight=sum(len(t) for t in tokens);offset=0
        for phrase,words in zip(phrases,tokens):
            s=a+(b-a)*offset/weight;offset+=len(words);e=a+(b-a)*offset/weight
            if e-s<.05: raise ValueError('Recording too short for script; shorten the script or add a longer take')
            points=np.linspace(s,e,len(words)+1)
            rows.append({'id':uuid.uuid4().hex[:12],'text':phrase,'start':s,'end':e,'words':[{'text':w,'start':float(points[i]),'end':float(points[i+1])} for i,w in enumerate(words)],'chapter_title':chapter['title'],'visual_hint':chapter['visual_hint'],**({'source_url':chapter['source_url']} if chapter.get('source_url') else {})})
    if len(rows)>500: raise ValueError('Recording script exceeds 500 clips')
    return rows,origin


def prepare_recording(source, target, chapters, chapter_starts, run_checked, split_phrases, check_cancel=lambda:None):
    target=Path(target);rate=24000
    with tempfile.TemporaryDirectory(prefix='recorded-voice-',dir=target.parent) as temp:
        wav=Path(temp)/'voice.wav'
        # Read at most 30m+1s; reject longer recordings rather than silently truncate.
        run_checked(['ffmpeg','-v','error','-nostdin','-y','-i',str(source),'-t','1801','-vn','-ac','1','-ar',str(rate),'-c:a','pcm_s16le',str(wav)],check_cancel=check_cancel,timeout=180)
        with wave.open(str(wav),'rb') as reader:
            n=reader.getnframes();duration=n/rate
            if not .5<=duration<=1800: raise ValueError('Recording must be between 0.5 seconds and 30 minutes')
            peak=0;total=0.;clipped=0
            while True:
                check_cancel();samples=np.frombuffer(reader.readframes(rate),dtype='<i2').astype(np.float64)
                if not samples.size:break
                peak=max(peak,float(np.abs(samples).max()));total+=float(samples@samples);clipped+=int(np.count_nonzero(np.abs(samples)>=32760))
        if peak<30 or total/n<4:raise ValueError('Recording contains no usable narration')
        lines,origin=recording_lines(chapters,duration,chapter_starts,split_phrases)
        check_cancel();perf.publish_staged_file(wav,target)
    warnings=['Review estimated word timing against the recording before publishing.']
    if clipped:warnings.append('Recording contains clipped samples; consider recording another take.')
    return {'duration':duration,'lines':lines,'provider':'recorded','word_timing':origin,'peak_dbfs':round(20*math.log10(peak/32768),2),'rms_dbfs':round(10*math.log10(total/n/32768**2),2),'clipped_samples':clipped,'warnings':warnings}
