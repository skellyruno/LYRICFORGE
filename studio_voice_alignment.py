"""Reconcile recognized word timestamps to the original script; never rewrite captions."""
import copy,math,unicodedata


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',str(text)).casefold() if c.isalnum())


def align(result,recognized,pronunciation=None):
    import studio_voice as voice
    replacements=getattr(voice,'speech_dictionary',voice.dictionary)(pronunciation or {});out=copy.deepcopy(result)
    words=[]
    for line in recognized:
        for w in line['words']:
            text=normalized(w['text']);a,b=float(w['start']),float(w['end']);p=w.get('probability',1.)
            if not text:continue
            if not math.isfinite(a+b) or not 0<=a<b<=result['duration']+.02 or (words and a<words[-1][2]-.02) or not isinstance(p,(int,float)) or not math.isfinite(p) or p<.35:return None
            words.append((text,a,b))
    cursor=0
    for line in out['lines']:
        matched=[]
        for w in line['words']:
            expected=normalized(voice.spoken(w['text'],replacements));literal=normalized(w['text']);combined='';first=cursor
            if not expected:return None
            while cursor<len(words) and cursor-first<8:
                combined+=words[cursor][0];cursor+=1
                if combined in (expected,literal):break
                if not (expected.startswith(combined) or literal.startswith(combined)):return None
            if combined not in (expected,literal) or first==cursor:return None
            a,b=words[first][1],min(result['duration'],words[cursor-1][2]);matched.append({**w,'start':a,'end':b})
        if not matched:return None
        line['words']=matched;line['start']=matched[0]['start'];line['end']=matched[-1]['end']
    if cursor!=len(words):return None
    out['word_timing']='Whisper recognition timestamps reconciled exactly to original script; review before publication';out['alignment']={'status':'matched','recognized_words':len(words),'script_words':sum(len(x['words']) for x in out['lines'])}
    return out
