"""Sample-clocked motion envelope for music-driven graphics.
This is an energy envelope, not beat detection. No lookahead or retiming.
"""
import math
import numpy as np


def energy(pcm, sample_rate=48000, fps=30, attack=.035, release=.20, reference=.12):
    if (type(sample_rate)!=int or type(fps)!=int or not 1<=fps<=120 or sample_rate<fps or sample_rate>384000
            or any(not math.isfinite(x) or x<=0 for x in (attack,release,reference))):
        raise ValueError('Invalid envelope configuration')
    data=np.asarray(pcm,dtype=np.float32)
    if data.ndim not in (1,2) or (data.ndim==2 and not 1<=data.shape[1]<=8) or not np.isfinite(data).all():
        raise ValueError('Expected finite mono or multichannel PCM')
    frames=(len(data)*fps+sample_rate-1)//sample_rate
    if frames>60*60*fps:raise ValueError('Audio exceeds one hour')
    result=np.zeros(frames,dtype=np.float32);value=0.
    aa=math.exp(-1/(fps*attack));ar=math.exp(-1/(fps*release))
    for f in range(frames):
        start=f*sample_rate//fps;end=min(len(data),(f+1)*sample_rate//fps)
        block=data[start:end]
        raw=min(1.,math.sqrt(float(np.mean(block.astype(np.float64)**2)))/reference) if len(block) else 0.
        coef=aa if raw>value else ar;value=coef*value+(1-coef)*raw
        result[f]=value
    return result
