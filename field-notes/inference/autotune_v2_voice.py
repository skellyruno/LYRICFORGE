import json,sys,subprocess,wave,hashlib
from pathlib import Path
LINES=[[0,4,"Baba, that note is fighting for its life. Listen."],[10,16,"Same vowel melody. One off key, one snapped to a scale. That is the basic idea behind pitch correction."],[16,26,"Andy Hildebrand introduced Auto-Tune in nineteen ninety-seven. His earlier work involved seismic analysis for oil exploration. Bro went from digging underground to digging vocals out of the grave."],[26,35,"In nineteen ninety-eight, Cher's Believe made the hard tuned effect famous. What began as a repair tool became a creative instrument."],[35,43,"Pitch begins with repetition. The faster a voiced sound repeats, the higher its fundamental frequency."],[43,52,"The detector estimates that frequency. The target selector picks an allowed note. The pitch shifter moves the sound toward it."],[52,59,"Pick the right key and scale. Otherwise, you can tune perfectly into the wrong dimension. Baba. Wrong graveyard."],[59,65,"Retune speed controls how quickly correction responds. Hear our original synthetic melody: dry, gentle, then hard."],[80,89,"The gentle curve keeps more movement. The hard curve locks to notes. Humanize can relax correction on sustained notes."],[89,99,"Formants are resonances shaped by the vocal tract. Pitch and formants are different. That is why pitch shifting and changing vocal character are separate jobs."],[99,110,"For a natural sound, start with the correct scale and moderate correction. For the robot effect, go faster. Listen in the mix."],[110,116,"Auto-Tune is not a talent button. Get the take right. Then add the sauce."],[116,120,"Skell Science. Stay in key. Stay spooky."]]
def main():
    model,voices,out=map(Path,sys.argv[1:])
    out.mkdir(parents=True,exist_ok=False)
    phrases=[r[2] for r in LINES]
    subprocess.run([sys.executable,'studio_kokoro_worker.py',str(model.resolve()),str(voices.resolve()),str(out.resolve())],input=json.dumps({'phrases':phrases,'voice':'am_michael','speed':1.04,'speeds':[.98,1.08,1.09,1.03,1.03,1.05,.99,1.03,1.04,1.04,1.05,.99,.94]}),text=True,check=True,timeout=600)
    records=[]
    for i,(start,end,text) in enumerate(LINES):
        p=out/f'neural-{i:04d}.wav'
        with wave.open(str(p)) as w:duration=w.getnframes()/w.getframerate()
        records.append({'file':p.name,'start':start,'end':end,'text':text,'duration':duration,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps({'engine':'Kokoro ONNX','voice':'am_michael','phrases':records},indent=2))
if __name__=='__main__':main()
