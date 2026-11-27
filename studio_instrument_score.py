"""Optional local sampled-instrument score, using a trusted SoundFont.
Original MIDI arrangement; no downloaded models or bundled instrument samples.
A system FluidSynth library is required only when explicitly configured.
"""
from __future__ import annotations
import ctypes as C
import ctypes.util
import math
import os
from pathlib import Path
import tempfile
import wave
import numpy as np


def arrange(duration,bpm,chords,rate):
    """Absolute sample clock; note-off sorts before a same-tick note-on."""
    events=[];beat=60/bpm;bar=beat*4;total=round(duration*rate)
    def note(ch,at,seconds,pitch,vel):
        a=max(0,round(at*rate));b=min(total,round((at+seconds)*rate))
        if a>=total or b<=a:return
        events.extend(((a,1,ch,pitch,max(1,min(127,round(vel)))),(b,0,ch,pitch,0)))
    bars=math.ceil(duration/bar)
    for k in range(bars):
        start=k*bar;chord=chords[k%len(chords)];p=start/duration
        end=(k==bars-1);chord=chords[0] if end else chord
        growth=min(1,p/.40);resolve=max(0,(p-.73)/.27);accent=1+.20*growth-.18*resolve
        # Natural, deliberately unequal velocities, held pedal-like overlap.
        pattern=((0,1,64),(1.5,3,47),(2.5,2,53),(3.25,4,42))
        if k%2:pattern=((0,2,59),(1,4,45),(2.25,3,54),(3.5,2,40))
        if end:pattern=((0,2,58),(1.5,3,43),(2.5,1,35))
        for at,idx,velocity in pattern:
            note(0,start+at*beat,beat*(1.7 if at==0 else .95),chord[idx]+12,velocity*accent)
        if k==0:
            note(0,start,bar*.9,chord[0],42)
        else:
            for at in (0.,2.):note(2,start+at*beat,beat*1.65,chord[0]-12,(40+12*growth)*(1-.45*resolve))
            for j,n in enumerate(chord[1:4]):
                note(1,start+(.10+j*.07)*beat,bar*.94,n,30+22*growth-10*resolve)
        if k>=2 and not end:
            # A countermelody, not simply a louder repetition of the arpeggio.
            phrase=((.5,3,12),(1.75,4,12),(3.,2,12)) if k%2 else ((0.,2,12),(2.,3,12))
            for at,idx,octave in phrase:note(3,start+at*beat,beat*1.25,chord[idx]+octave,38+14*growth)
        if k>=3 and not end and p<.73:
            for at in (1.,3.):note(4,start+at*beat,beat*.28,chord[2]+24,24+10*growth)
        if end:
            for j,n in enumerate(chords[0][1:]):note(0,start+j*.055, min(bar*.9,max(.15,duration-start-.15)),n,44-j*3)
    return sorted(events)


class InstrumentEngine:
    def __init__(self,bank,rate):
        path=Path(bank).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in ('.sf2','.sf3'):raise ValueError('Configure an existing local SF2/SF3 instrument bank')
        lib=os.getenv('LYRICFORGE_FLUIDSYNTH_LIB') or ctypes.util.find_library('fluidsynth')
        if not lib:raise RuntimeError('Sampled score selected but the local FluidSynth library is unavailable')
        try:self.lib=C.CDLL(lib)
        except OSError as exc:raise RuntimeError('Cannot load configured FluidSynth runtime') from exc
        self.settings=None;self.synth=None
        l=self.lib;P=C.c_void_p;I=C.c_int;S=C.c_char_p;D=C.c_double
        def sig(name,ret,*args):f=getattr(l,name);f.restype=ret;f.argtypes=list(args);return f
        sig('new_fluid_settings',P);sig('delete_fluid_settings',None,P);sig('fluid_settings_setnum',I,P,S,D);sig('fluid_settings_setint',I,P,S,I)
        sig('new_fluid_synth',P,P);sig('delete_fluid_synth',None,P);sig('fluid_synth_sfload',I,P,S,I);sig('fluid_synth_program_select',I,P,I,I,I,I);sig('fluid_synth_cc',I,P,I,I,I);sig('fluid_synth_noteon',I,P,I,I,I);sig('fluid_synth_noteoff',I,P,I,I);sig('fluid_synth_write_float',I,P,I,P,I,I,P,I,I)
        try:
            self.settings=l.new_fluid_settings()
            if not self.settings:raise RuntimeError('FluidSynth settings allocation failed')
            l.fluid_settings_setnum(self.settings,b'synth.sample-rate',rate);l.fluid_settings_setnum(self.settings,b'synth.gain',.65);l.fluid_settings_setint(self.settings,b'synth.polyphony',64);l.fluid_settings_setint(self.settings,b'synth.cpu-cores',1)
            self.synth=l.new_fluid_synth(self.settings)
            if not self.synth:raise RuntimeError('FluidSynth allocation failed')
            sf=l.fluid_synth_sfload(self.synth,os.fsencode(path),1)
            if sf<0:raise RuntimeError('Unable to load local instrument bank')
            # General MIDI: acoustic grand, strings, finger bass, cello, celesta.
            for ch,(program,pan,volume) in enumerate(((0,48,93),(48,76,79),(33,64,75),(42,48,75),(8,85,53))):
                if l.fluid_synth_program_select(self.synth,ch,sf,0,program)!=0:raise RuntimeError('Required GM instrument missing from bank')
                l.fluid_synth_cc(self.synth,ch,10,pan);l.fluid_synth_cc(self.synth,ch,7,volume);l.fluid_synth_cc(self.synth,ch,91,30)
        except BaseException:self.close();raise
    def event(self,on,ch,pitch,vel):
        if on:self.lib.fluid_synth_noteon(self.synth,ch,pitch,vel)
        else:self.lib.fluid_synth_noteoff(self.synth,ch,pitch)
    def block(self,n):
        x=np.empty((n,2),dtype=np.float32);ptr=C.c_void_p(x.ctypes.data)
        if self.lib.fluid_synth_write_float(self.synth,n,ptr,0,2,ptr,1,2)!=0:raise RuntimeError('FluidSynth render failed')
        if not np.isfinite(x).all():raise RuntimeError('Invalid sample output')
        return x
    def close(self):
        if self.synth:self.lib.delete_fluid_synth(self.synth);self.synth=None
        if self.settings:self.lib.delete_fluid_settings(self.settings);self.settings=None


def write_sample_score(plan,path,bank,rate,bpm,chords,music_gain,cue_gain,events,foley,check_cancel):
    duration=float(plan['duration']);total=round(duration*rate);notes={"cinematic":arrange_arc,"chromatic":arrange_chromatic}.get(plan.get("score_arc"),arrange)(duration,bpm,chords,rate)
    from studio_signal_story import pause_gain
    rests=plan.get('score_rests',[])
    pause_gain(np.array([0.]),rests)
    engine=InstrumentEngine(bank,rate);index=0;pos=0;peak=0.;energy=0.
    try:
        # Bounded block render to temporary PCM; measure before setting mix gain.
        with tempfile.TemporaryFile() as tmp:
            while pos<total:
                check_cancel()
                while index<len(notes) and notes[index][0]<=pos:
                    _,on,ch,pitch,vel=notes[index];engine.event(on,ch,pitch,vel);index+=1
                end=min(total,pos+rate,notes[index][0] if index<len(notes) else total)
                if end<=pos:continue
                x=engine.block(end-pos);t=(pos+np.arange(len(x)))/rate
                def smooth(q):q=np.clip(q,0,1);return q*q*(3-2*q)
                p=t/duration;arc=(.73+.27*smooth((p-.12)/.35))*(1-.30*smooth((p-.72)/.07)*(1-smooth((p-.82)/.08)))
                x*=((smooth(t/.5)*smooth((duration-t)/1.1)*arc)[:,None]).astype(np.float32)
                peak=max(peak,float(np.max(np.abs(x))));energy+=float(np.sum(x.astype(np.float64)**2));tmp.write(x.tobytes());pos=end
            rms=math.sqrt(energy/(total*2))
            if rms<1e-8:raise RuntimeError('Sampled instrument score is silent')
            gain=min(10**(-25/20)/rms,.38/max(peak,1e-8))*music_gain
            tmp.seek(0);pos=0
            with wave.open(str(path),'wb') as wav:
                wav.setparams((2,2,rate,0,'NONE','not compressed'))
                while pos<total:
                    check_cancel();x=np.frombuffer(tmp.read(min(rate,total-pos)*8),dtype=np.float32).reshape(-1,2).astype(np.float64)*gain
                    t=(pos+np.arange(len(x)))/rate;x+=foley(t,events)*cue_gain
                    if rests:x*=pause_gain(t,rests)[:,None]
                    wav.writeframes(np.rint(np.clip(x,-.98,.98)*32767).astype('<i2').tobytes());pos+=len(x)
        return path
    finally:engine.close()


def arrange_arc(duration,bpm,chords,rate):
    """Original score with four deliberate sections and a returning motif.
    Same sample clock as the director; no changes to plugin soundtrack path."""
    beat=60/bpm;bar=4*beat;total=round(duration*rate);events=[];bars=math.ceil(duration/bar)
    def note(ch,at,length,pitch,vel):
        a=max(0,round(at*rate));b=min(total,round((at+length)*rate))
        if a<b:events.extend([(a,1,ch,pitch,int(vel)),(b,0,ch,pitch,0)])
    for i in range(bars):
        p=i/max(1,bars-1);t=i*bar;ending=i==bars-1
        # Quiet question -> expanding register -> tension -> return home.
        chord=chords[0] if ending else chords[(i+(1 if .42<p<.72 else 0))%len(chords)]
        motif=[(0,2,0,60),(1.5,3,0,47),(2.5,4,0,55),(3.25,3,0,40)]
        if .3<=p<.7:motif=[(0,1,12,65),(.75,3,0,48),(1.5,4,0,61),(2.5,2,12,54),(3.25,3,12,45)]
        if .7<=p<.85:motif=[(0,2,0,45),(2.5,3,0,35)]
        if ending:motif=[(0,2,0,53),(1.5,3,0,43)]
        for at,j,octave,vel in motif:note(0,t+at*beat,beat*1.15,chord[j]+12+octave,vel)
        note(2,t,bar*.84,chord[0]-12,38 if p<.3 or p>.8 else 58)
        if .16<p<.84:
            for j in (1,2,3):note(1,t+(j-1)*.11*beat,bar*.92,chord[j],40+int(23*math.sin(p*math.pi)))
        if .30<p<.74:
            for at,j in [(0,3),(2,2)]:note(3,t+at*beat,beat*1.9,chord[j],53)
            if p>.44:
                for at,j in [(1,3),(3,4)]:note(4,t+at*beat,beat*.28,chord[j]+24,34)
        if ending:
            for j,n in enumerate(chords[0][1:]):note(0,t+j*.08,bar*.90,n,44-j*3)
    return sorted(events)


def arrange_chromatic(duration,bpm,chords,rate):
    """Original luminous palette: minor question, major lift, suspended resolution.
    A different melodic identity without changing other score plans."""
    beat=60/bpm;bar=beat*4;total=round(duration*rate);events=[];bars=math.ceil(duration/bar)
    harmony=[(50,57,62,65,69),(46,53,58,62,69),(48,55,60,64,67),(45,52,57,60,64),
             (53,60,65,69,72),(48,55,60,64,69),(50,57,62,65,72),(55,62,67,71,74)]
    def note(ch,at,length,pitch,vel):
        a=max(0,round(at*rate));b=min(total,round((at+length)*rate))
        if a<b:events.extend([(a,1,ch,pitch,int(vel)),(b,0,ch,pitch,0)])
    for i in range(bars):
        p=i/max(1,bars-1);t=i*bar;end=i==bars-1
        chord=harmony[0] if end else harmony[i%len(harmony)]
        motif=[(0,2,0,62),(1.5,3,0,53),(2.75,4,0,47)] if p<.25 else [(0,2,12,64),(.75,1,12,43),(1.5,3,0,54),(2.5,4,0,59),(3.25,3,12,41)]
        if end:motif=[(0,4,0,55),(1.5,3,0,43),(2.5,2,0,35)]
        for at,k,octave,vel in motif:note(0,t+at*beat,beat*.68,chord[k]+12+octave,vel)
        if .08<p<.89:
            for k in (1,2,3):note(1,t+(.07*k)*beat,bar*.87,chord[k],round(34+22*math.sin(p*math.pi)))
        note(2,t,bar*.75,chord[0]-12,42 if p<.32 or p>.8 else 56)
        if .25<p<.75:
            for at,k in ((.5,2),(2.25,3)):note(3,t+at*beat,beat*1.3,chord[k],46)
            if p>.40:
                for at,k in ((1,4),(3,2)):note(4,t+at*beat,beat*.27,chord[k]+24,39)
        if end:
            for j,n in enumerate(chord[1:]):note(0,t+j*.10,bar*.88,n,47-j*4)
    return sorted(events)
