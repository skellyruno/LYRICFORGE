"""Explicit neural voice audition. Use a verified local runtime and model."""
import argparse,hashlib,json,math,os,sys,time,wave
from pathlib import Path
import numpy as np
import studio_creator as creator

MODEL_SHA='beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a'
VOICES_SHA='bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d'
SCRIPT=[
{'title':'Plugin demonstration','narration':'Your vocal needs room to breathe. Skell Spacer uses a sidechain signal to shape frequencies in the main track. Turn the amount control and listen to the difference.','visual_hint':'Native plugin operation'},
{'title':'Research explanation','narration':'A good explanation starts with evidence. Show the original source, highlight the important detail, and connect the picture to the narration. Let the viewer hear the result before moving on.','visual_hint':'Source card and diagram'}]

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def run(model,voices,out):
    model,voices,out=map(lambda x:Path(x).resolve(),(model,voices,out))
    if digest(model)!=MODEL_SHA or digest(voices)!=VOICES_SHA:raise ValueError('Kokoro asset checksum mismatch')
    out.mkdir(parents=True,exist_ok=False)
    os.environ.update(LYRICFORGE_KOKORO_PYTHON=sys.executable,LYRICFORGE_KOKORO_MODEL=str(model),LYRICFORGE_KOKORO_VOICES=str(voices))
    rows=[]
    for voice in ('kokoro','kokoro_smooth','kokoro_clear'):
        start=time.monotonic();raw=out/(voice+'-original.wav')
        result=creator.narration(SCRIPT,raw,voice=voice,speed=1.,delivery='tutorial',pronunciation={'Skell':'Skell','SkellyMotion':'Skelly Motion'})
        elapsed=time.monotonic()-start
        if result['provider']!=voice:raise RuntimeError('Neural voice unexpectedly fell back')
        with wave.open(str(raw),'rb') as wav:
            if wav.getnchannels()!=1 or wav.getsampwidth()!=2:raise RuntimeError('Invalid audition format')
            rate=wav.getframerate();samples=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float64)/32768.
        peak=float(np.max(np.abs(samples)));rms=float(np.sqrt(np.mean(samples*samples)))
        if not 0<rms<=peak<=1. or np.count_nonzero(np.abs(samples)>=.9999):raise RuntimeError('Silent or clipped audition')
        gain=min(10**(-22/20)/rms,10**(-1/20)/peak)
        target=out/(voice+'-matched.wav');x=np.rint(samples*gain*32768).astype('<i2')
        with wave.open(str(target),'wb') as wav:
            wav.setparams((1,2,rate,0,'NONE','not compressed'));wav.writeframes(x.tobytes())
        rows.append({'voice':voice,'model_voice':creator.KOKORO_VOICES[voice],'seconds':len(samples)/rate,'synthesis_seconds':elapsed,'rms_dbfs':20*math.log10(rms),'peak_dbfs':20*math.log10(peak),'matched_gain_db':20*math.log10(gain),'original_sha256':digest(raw),'matched_sha256':digest(target),'timing':result['word_timing']})
    report={'model_sha256':MODEL_SHA,'voices_sha256':VOICES_SHA,'script':SCRIPT,'voices':rows,'matching':'RMS target -22 dBFS, peak cap -1 dBFS; not LUFS normalization','approval':'Unapproved. Listening required.'}
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model');p.add_argument('voices');p.add_argument('output')
    a=p.parse_args();print(json.dumps(run(a.model,a.voices,a.output),indent=2))
