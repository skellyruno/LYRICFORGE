"""Actual local neural voice direction proof, using the integrated Creator."""
import json,os,sys,wave
from pathlib import Path
import studio_creator as c

def main():
    out=Path('voice-proof');out.mkdir()
    text='Skelliere. Shape the sound. Listen to the same signal.'
    for direction in ('reveal','detail','compare','close'):
        result=c.narration([{'title':'Product film','narration':text,'voice_direction':direction}],out/(direction+'.wav'),'kokoro',delivery='cinematic',pronunciation={'Skelliere':'Skell ee air'})
        assert result['provider']=='kokoro'
        assert all('Skell ee air' not in row['text'] for row in result['lines'])
        assert ' '.join(row['text'] for row in result['lines'])==text
        (out/(direction+'.json')).write_text(json.dumps(result,indent=2))
    def duration(name):
        with wave.open(str(out/(name+'.wav'))) as w:return w.getnframes()/w.getframerate()
    lengths={k:duration(k) for k in ('reveal','detail','compare','close')}
    assert lengths['compare']>lengths['detail'] and lengths['close']>lengths['detail'],lengths
    (out/'report.json').write_text(json.dumps({'provider':'kokoro','direction_durations':lengths,'pronunciation_caption_preserved':True,'passed':True},indent=2))
    print(lengths)
if __name__=='__main__':main()
