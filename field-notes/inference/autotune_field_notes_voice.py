import json,sys,subprocess,wave,hashlib
from pathlib import Path
LINES=[[0,8,"Baba! Your vocal just missed the note. Is it cooked? Not yet. Welcome to Skell Science: the skeleton's guide to pitch correction."],[8,19,"In nineteen ninety-seven, Andy Hildebrand introduced Auto-Tune. His background was seismic analysis, the math behind finding oil. Bro went from digging underground to digging vocals out of the grave."],[19,29,"Then Cher's nineteen ninety-eight hit, Believe, made the robotic effect famous. Fast correction turned a repair tool into an instrument. The glitch was the sauce."],[29,40,"Here's the science. The detector estimates the fundamental frequency, the rate at which a voiced sound repeats. A target selector chooses an allowed note. Then a pitch shifter moves the sound toward it."],[40,51,"Choose the song's key and scale first. Otherwise your correction can confidently send you to the wrong note. That's not sauce, that's a skeleton in the wrong graveyard."],[51,59,"Retune speed controls how fast correction responds. Slow gives you more glide. Fast gives you the snap. Hear this original synthetic vowel melody, dry, gentle, then hard tuned."],[75,85,"Notice how the slow version keeps more movement, and the hard version locks onto the notes. Humanize can relax correction during sustained notes, leaving a little life in the bones."],[85,96,"Formants are resonances shaped by the vocal tract. They help give voices their character. Pitch and formant control are different. Moving pitch alone needn't turn your singer into a cartoon."],[96,108,"For a natural vocal, start with the correct scale and a moderate speed. Listen in the mix. For the hard tuned sound, go faster. Don't mistake pitch correction for timing, diction, or actual emotion."],[108,115,"The takeaway? Auto-Tune isn't a talent button. It's a tool, and sometimes an instrument. Get the take right, then dial in the sauce."],[115,120,"Skell Science. Stay in key. Stay spooky."]]
def main():
    model,voices,out=map(Path,sys.argv[1:])
    out.mkdir(parents=True,exist_ok=False)
    phrases=[r[2] for r in LINES]
    subprocess.run([sys.executable,'studio_kokoro_worker.py',str(model.resolve()),str(voices.resolve()),str(out.resolve())],input=json.dumps({'phrases':phrases,'voice':'am_michael','speed':1.10,'speeds':[1.08,1.14,1.08,1.12,1.09,1.08,1.1,1.11,1.14,1.1,.98]}),text=True,check=True,timeout=600)
    records=[]
    for i,(start,end,text) in enumerate(LINES):
        p=out/f'neural-{i:04d}.wav'
        with wave.open(str(p)) as w:duration=w.getnframes()/w.getframerate()
        records.append({'file':p.name,'start':start,'end':end,'text':text,'duration':duration,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (out/'manifest.json').write_text(json.dumps({'engine':'Kokoro ONNX','voice':'am_michael','phrases':records},indent=2))
if __name__=='__main__':main()
