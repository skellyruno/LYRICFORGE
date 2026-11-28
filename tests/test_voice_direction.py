import pytest
import studio_voice as v
import studio_creator as c

def test_explicit_direction_and_original_spelling():
    rows=c.validate_script([{'title':'Intro','narration':'Skelliere. Shape the sound.','voice_direction':'reveal'}])
    assert rows[0]['voice_direction']=='reveal' and rows[0]['narration']=='Skelliere. Shape the sound.'
    assert v.spoken(rows[0]['narration'],v.speech_dictionary({'Skelliere':'Skell ee air'}))=='Skell ee air. Shape the sound.'
    assert v.directed_pace('Listen to the result.',1.,'Proof','cinematic')[0]<v.directed_pace('Detail.',1.,'Detail','cinematic','steady')[0]
    assert v.directed_pace('End.',1.,'End','neutral','close')[1]>1
    with pytest.raises(ValueError):c.validate_script([{'narration':'Hello.','voice_direction':'bad'}])
