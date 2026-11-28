"""Original, deterministic musical underscore; independent of speech and foley.
No audio samples, downloads or third-party compositions. Block-streamed synthesis.
"""
import math
import wave
import numpy as np

# Original eight-bar minor-key progression, voiced as soft piano/strings.
DOC_BPM=88
CHORDS=((45,52,57,60,64),(41,48,53,57,64),(48,55,60,64,67),(43,50,55,59,62),
        (45,52,57,60,67),(41,48,53,57,60),(48,55,60,64,69),(43,50,55,59,65))


def hz(note):return 440.*2.**((note-69)/12.)


def smooth(x):
    x=np.clip(x,0.,1.);return x*x*(3.-2.*x)


def piano(t,note):
    q=np.maximum(0.,t);f=hz(note);env=(1-np.exp(-q*110))*np.exp(-q*2.8)*(t>=0)*smooth((5.-q)/.5)
    return env*(np.sin(2*np.pi*f*q)+.34*np.sin(2*np.pi*f*2.003*q)+.12*np.sin(2*np.pi*f*3.01*q))


def music_block(t, duration, *, gain=1., energetic=False):
    beat=60/(108 if energetic else DOC_BPM);bar=4*beat
    arc=.52+.48*smooth(t/max(2.,duration*.28))-.25*smooth((t-duration*.78)/max(1.,duration*.16))
    left=np.zeros_like(t);right=np.zeros_like(t)
    first=max(0,int(t[0]/bar)-4);last=int(t[-1]/bar)+1
    for k in range(first,last+1):
        d=t-k*bar;chord=CHORDS[k%len(CHORDS)]
        # Crossfade sustained chord voices across bar boundaries.
        envelope=smooth(d/.55)*smooth((bar+.55-d)/.55)
        for j,note in enumerate(chord[1:]):
            f=hz(note);phase=2*np.pi*f*d
            value=(np.sin(phase+.16*np.sin(2*np.pi*.27*d+j))+.13*np.sin(2*phase)+.07*np.sin(3*phase))*envelope*.014
            left+=value*(1-.16*j);right+=value*(.60+.12*j)
        # Piano figure, intentional syncopation, independent ringing tails.
        for j,(at,idx) in enumerate(((0,1),(1.5,3),(2.5,2),(3.25,4))):
            x=d-at*beat;v=piano(x,chord[idx]+12)*(.029 if j==0 else .018)
            echo=piano(x-.19,chord[idx]+12)*.005
            left+=v*(.9 if j%2==0 else .55)+echo*.5
            right+=v*(.58 if j%2==0 else .9)+echo
        for at in (0.,2.):
            q=d-at*beat;env=smooth(q/.025)*np.exp(-np.maximum(q,0)*1.9)*smooth((7.-q)/.5)
            bass=.034*np.sin(2*np.pi*hz(chord[0]-12)*q)*env
            left+=bass;right+=bass
        # Original counter-melody enters after the first musical phrase, with a distinct release.
        if not energetic and k>=2:
            for at,idx in ((.75,4),(2.75,3)):
                q=d-at*beat;v=piano(q,chord[idx]+12)*.010*smooth((t-duration*.18)/max(1.,duration*.18))
                left+=v*.65;right+=v*.93
        if not energetic:
            # A warm string counterline and a brushed rhythmic pulse arrive as the
            # musical phrase develops. Absolute phase and bounded tails make this
            # independent of block boundaries.
            phrase=smooth((t-duration*.24)/max(1.,duration*.14))
            q=d;env=smooth(q/.7)*smooth((bar+.7-q)/.7)
            f=hz(chord[3]+12);lead=(np.sin(2*np.pi*f*q+.30*np.sin(2*np.pi*4.6*q))+.16*np.sin(2*np.pi*f*2*q))*env*.010*phrase
            left+=lead*.8;right+=lead
            for at in (1.,3.):
                q=d-at*beat;x=np.maximum(0.,q);brush=(np.sin(2*np.pi*1831*x)+.5*np.sin(2*np.pi*2699*x)+.4*np.sin(2*np.pi*3371*x))*smooth(q/.012)*np.exp(-x*26)*smooth((.30-x)/.08)*.0028*phrase
                left+=brush;right+=brush*.72
        if not energetic:
            # A longer melodic arc, rather than identical arpeggios every bar.
            # Absolute event clock and compact support keep streaming deterministic.
            progress=np.clip(t/duration,0,1);rise=smooth((progress-.16)/.24);resolve=smooth((progress-.78)/.20)
            melody=((0.,2,12),(1.5,3,12),(3.,4,12)) if k%4 in (0,2) else ((.5,4,12),(2.,3,12),(3.5,2,12))
            for at,idx,octave in melody:
                q=d-at*beat;v=piano(q,chord[idx]+octave)*.012*rise*(1-.55*resolve)
                tail=piano(q-.28,chord[idx]+octave)*.003*rise
                left+=v*.87+tail*.40;right+=v*.65+tail
            # Low warm sustained voice and soft bowed harmonics expand the middle.
            q=d;env=smooth(q/.8)*smooth((bar+.8-q)/.8);f=hz(chord[1]-12)
            warm=(np.sin(2*np.pi*f*q)+.21*np.sin(2*np.pi*2*f*q))*env*.013*rise*(1-.8*resolve)
            left+=warm*.95;right+=warm
            # On the last phrase a more exposed piano voice provides resolution.
            if k>=2:
                q=d-beat*2.;v=piano(q,chord[2]+12)*.017*resolve
                left+=v*.83;right+=v*.75
        # Quiet rounded kick, no shrill synthetic transition chirps.
        for at in ((0.,1.5,2.5) if energetic else (0.,2.)):
            q=d-at*beat;x=np.maximum(0,q);v=.020*np.sin(2*np.pi*(47*x+1.5*(1-np.exp(-x*24))))*np.exp(-x*15)*smooth(q/.008)*smooth((1.5-x)/.2)
            left+=v;right+=v
    if not energetic:
        # Four-part arrangement: exposed opening, gradual rise, sustained climax,
        # then release. Absolute event timing preserves streaming equivalence.
        progress=np.clip(t/duration,0,1)
        lift=smooth((progress-.19)/.23)*(1-.70*smooth((progress-.72)/.23))
        for k in range(first,last+1):
            d=t-k*bar;chord=CHORDS[k%len(CHORDS)];q=np.maximum(d,0)
            env=smooth(d/.65)*smooth((bar+.65-d)/.65)
            f=hz(chord[2]-12);phase=2*np.pi*f*q+.18*np.sin(2*np.pi*4.1*q)
            bowed=sum(np.sin(phase*j)/(j**1.7) for j in range(1,7))*.014*env*lift
            left+=bowed*.86;right+=bowed*.70
            # Delayed quiet resonance creates a larger stereo space without a chirp.
            for at,idx in ((0.,3),(2.5,4)):
                x=d-at*beat
                res=piano(x-.11,chord[idx]+12)*.004*lift+piano(x-.32,chord[idx]+12)*.0025*lift
                left+=res*.55;right+=res
        # A deliberate breath before the final cadence, not a cut in narration.
        breath=1-.36*smooth((progress-.73)/.05)*(1-smooth((progress-.82)/.08))
        left*=breath;right*=breath
    fade=smooth(t/.8)*smooth((duration-t)/1.2)
    return np.column_stack((left,right))*((2.05 if energetic else 2.55)*gain*fade[:,None]*(1. if energetic else arc[:,None]))


def foley_block(t,events):
    """Only soft, brief page/contact accents. No ascending electronic sweeps."""
    out=np.zeros_like(t)
    for at,kind in events:
        q=t-at;sel=(q>=0)&(q<.18)
        if not np.any(sel):continue
        x=q[sel];env=smooth(x/.012)*np.exp(-x*(30 if kind=='contact' else 18))
        # Deterministic band-limited inharmonic texture rather than a pitched beep.
        texture=sum(np.sin(2*np.pi*f*x+p) for f,p in ((179,.2),(311,1.7),(487,2.1),(719,1.3),(1021,2.4)))/5
        out[sel]+=(.009*texture+.006*np.sin(2*np.pi*83*x))*env
    return np.column_stack((out,out*.85))


def write_score(plan,path,*,rate=24000,include_music=True,check_cancel=lambda:None,music_gain=1.,cue_gain=1.):
    duration=float(plan['duration']);total=max(1,round(duration*rate))
    if not math.isfinite(duration) or not 0<duration<=1800:raise ValueError('Invalid score duration')
    scenes=plan.get('scenes',[]);doc=plan.get('preset')=='doc'
    events=[(float(s['start'])+.12,'page') for s in scenes[1:] if not doc or s.get('editorial') in ('evidence','chapter')]
    events.extend((float(s['start'])+1.55,'contact') for s in scenes if s.get('editorial')=='evidence' and s.get('evidence_focus') and s['end']-s['start']>2.4)
    # Explicit local configuration: no sample bank or runtime is bundled,
    # no network access and no silent substitution on configured failure.
    import os
    bank=os.getenv('LYRICFORGE_SOUNDFONT')
    if doc and include_music and bank:
        from studio_instrument_score import write_sample_score
        return write_sample_score(plan,path,bank,rate,DOC_BPM,CHORDS,music_gain,cue_gain,events,foley_block,check_cancel)
    from studio_signal_story import pause_gain
    rests=plan.get('score_rests',[])
    pause_gain(np.array([0.]),rests)
    with wave.open(str(path),'wb') as wav:
        wav.setparams((2,2,rate,0,'NONE','not compressed'))
        for pos in range(0,total,rate):
            check_cancel();t=(pos+np.arange(min(rate,total-pos),dtype=np.float64))/rate
            mix=music_block(t,duration,gain=music_gain,energetic=not doc) if include_music else np.zeros((len(t),2))
            mix+=foley_block(t,events)*cue_gain
            if rests:mix*=pause_gain(t,rests)[:,None]
            wav.writeframes(np.rint(np.clip(mix,-.98,.98)*32767).astype('<i2').tobytes())
    return path
