"""Exact-length voice-led mix. No speech time stretch or source modification."""
from pathlib import Path
import argparse,hashlib,json,subprocess,tempfile,wave
import numpy as np

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def decode(path,channels):
    return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-nostdin','-i',str(path),'-vn','-ar','48000','-ac',str(channels),'-f','f32le','-'],timeout=180),dtype='<f4').reshape(-1,channels)

def mix(root,score,out):
    root,score,out=Path(root),Path(score),Path(out)
    if out.exists():raise FileExistsError(out)
    report=json.loads((root/'report.json').read_text());source=root/report['take']/'narration.wav'
    if sha(source)!=report['sha256']:raise ValueError('Narration checksum mismatch')
    for i,c in enumerate(report['chapters']):
        if sha(source.parent/f'neural-{i:04d}.wav')!=c['sha256']:raise ValueError('Phrase checksum mismatch')
    if report['fps']!=60 or report['frames']*800!=round(report['duration']*48000):raise ValueError('Invalid frame clock')
    count=report['frames']*800
    with tempfile.TemporaryDirectory() as tmp:
        voice_path=Path(tmp)/'voice.wav'
        subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(source),'-af','highpass=f=70,acompressor=threshold=0.063:ratio=2.5:attack=12:release=140:makeup=2.2,volume=4dB','-ar','48000','-ac','1','-c:a','pcm_f32le',str(voice_path)],check=True,timeout=180)
        voice=decode(voice_path,1)[:,0];bed=decode(score,2)
    if len(voice)!=count or len(bed)!=count or not np.isfinite(voice).all() or not np.isfinite(bed).all():raise ValueError('Audio streams must match the exact picture clock')
    hop=480;n=(count+hop-1)//hop
    if n<7:raise ValueError('Narration is too short')
    rms=np.sqrt(np.mean(np.pad(voice,(0,n*hop-count)).reshape(n,hop)**2,axis=1))
    target=np.clip(20*np.log10(np.maximum(rms,1e-6)/.025),0,9)
    target=np.maximum.reduce([np.pad(target[i:],(0,i),mode='edge') for i in range(7)])
    duck=np.zeros(n);state=0.
    for i,v in enumerate(target):
        alpha=np.exp(-.01/(.025 if v>state else .38));state=alpha*state+(1-alpha)*v;duck[i]=state
    env=np.interp(np.arange(count),np.arange(n)*hop,duck)
    music=bed*10**((-7-env[:,None])/20)
    combined=voice[:,None]+music
    peak=float(np.max(np.abs(combined)));gain=min(1.,.80/max(peak,1e-12));combined*=gain
    with out.open('xb') as stream,wave.open(stream,'wb') as w:
        w.setparams((2,2,48000,0,'NONE','not compressed'));w.writeframes(np.rint(combined*32767).astype('<i2').tobytes())
    return {'source_sha256':report['sha256'],'score_sha256':sha(score),'output_sha256':sha(out),'frames':report['frames'],'samples':count,'sample_rate':48000,'duration':count/48000,'max_duck_db':float(duck.max()),'master_gain_db':float(20*np.log10(gain)),'speech_stretched':False,'voice_rms_dbfs':float(20*np.log10(np.sqrt(np.mean(voice**2)))),'ducked_music_rms_dbfs':float(20*np.log10(np.sqrt(np.mean(music**2))))}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('neural',type=Path);p.add_argument('score',type=Path);p.add_argument('output',type=Path);a=p.parse_args();print(json.dumps(mix(a.neural,a.score,a.output),indent=2))
