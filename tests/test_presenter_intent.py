import pytest
import studio_voice as voice
import studio_shot_motion as shot

def test_presenter_pacing_is_context_aware_and_bounded():
    fast=voice.presenter_pace('Create your own visual identity with a professional creative workspace.',1.)
    proof=voice.presenter_pace('Listen to the difference.',1.)
    assert proof[0]<fast[0] and proof[1]>fast[1]
    for speed in (.75,1.25):
        assert .75<=voice.presenter_pace('Watch the amount control.',speed)[0]<=1.25
    assert voice.delivery('presenter',1.)[:3]==(1.,.14,.33)

@pytest.mark.parametrize('text,hint,kind,intent',[
 ('Turn the amount knob and watch the response.','','Spectral ducking','real_control'),
 ('Listen to the before and after.','','Spectral ducking','audio_comparison'),
 ('The frequency-selective response creates room.','conceptual explanation','Spectral ducking','mechanism'),
 ('This is the result of the edit.','','','result'),
 ('Welcome to the studio.','','','overview'),
])
def test_shot_intent(text,hint,kind,intent):
    assert shot.shot_intent(text,hint,kind)==intent

def test_native_sixty_fps_clock():
    from studio_director import make_plan
    from server import DirectorRequest,CreatorRequest
    plan=make_plan([{'text':'Welcome to the studio.','start':0.,'end':2.}],2.,[],'doc',fps=60)
    assert plan['fps']==60 and sum(s['frames'] for s in plan['scenes'])==120
    assert DirectorRequest(output_fps=60).output_fps==60
    assert CreatorRequest(product='Test',output_fps=60).output_fps==60
    assert DirectorRequest().output_fps is None
    assert 'fps=60' in shot.camera_filter(1920,1080,60,960,'push')
    with pytest.raises(ValueError):shot.camera_filter(1920,1080,60,1801,'push')
