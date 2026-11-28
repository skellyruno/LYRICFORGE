"""Real Creator expressive audition using the already verified optional model."""
import json,os,sys,time,hashlib
from pathlib import Path
import studio_creator as creator
from studio_expression_worker import DIRECTIONS

def main():
    folder=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(exist_ok=True,parents=True)
    os.environ.update(LYRICFORGE_EXPRESSION_PYTHON=sys.executable,LYRICFORGE_EXPRESSION_MODEL=str(folder))
    assert creator.voice_options()['expressive']
    text='Shape the sound. Every choice is yours.'
    takes={}
    for direction in ('detail','reveal','close'):
        start=time.monotonic();target=out/(direction+'.wav')
        r=creator.narration([{'title':'Product film','narration':text,'voice_direction':direction}],target,'expressive',delivery='cinematic')
        assert r['provider']=='expressive' and ' '.join(x['text'] for x in r['lines'])==text
        takes[direction]={'result':r,'seconds':time.monotonic()-start,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'native_condition':DIRECTIONS[direction]}
        (out/'creator-report.json').write_text(json.dumps(takes,indent=2))
    assert len({r['sha256'] for r in takes.values()})==3

if __name__=='__main__':main()
