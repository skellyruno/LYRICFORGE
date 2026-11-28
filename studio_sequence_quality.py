"""Conservative packet-copy and export checks for the 30 fps sequence engine."""
import json
import math
import subprocess
from pathlib import Path
import studio_performance as perf


def probe(path, *args):
    raw = subprocess.check_output(['ffprobe','-v','error',*args,'-of','json',str(path)], timeout=60, **perf.windows_child_options(True))
    if len(raw)>16*1024*1024:raise ValueError('Excessive render metadata')
    return json.loads(raw)


def streams(path):
    return probe(path,'-show_entries','stream=codec_type,codec_name,width,height,pix_fmt,time_base,avg_frame_rate,nb_frames,start_pts,duration_ts,has_b_frames,sample_rate,channels')['streams']


def picture_copy_source(state, assets, width, height):
    # Only a complete, already-normalized single video with its own audio.
    # Never bypass a cut, trim, overlay, transition, rotation or other picture edit.
    if state['transitions'] or any(x['kind']=='visual' for x in state['layers']) or len(state['base']['pieces'])!=1:return None
    p=state['base']['pieces'][0];n=state['base']['frames']
    if p['start'] or p['audio_start'] or p['asset']!=p['audio'] or p['length']!=n:return None
    path=Path(assets[p['asset']]['path'])
    try:
        ss=streams(path)
        if len(ss)!=2 or {s['codec_type'] for s in ss}!={'video','audio'}:return None
        v=next(s for s in ss if s['codec_type']=='video');a=next(s for s in ss if s['codec_type']=='audio')
        if not (v['codec_name']=='h264' and v['width']==width and v['height']==height and v['pix_fmt']=='yuv420p' and v['time_base']=='1/30000' and v['avg_frame_rate']=='30/1' and int(v['nb_frames'])==n and int(v['start_pts'])==0 and int(v['duration_ts'])==n*1000 and v['has_b_frames']==0):return None
        if not (a['codec_name']=='aac' and a['sample_rate']=='48000' and a['channels']==2 and a['time_base']=='1/48000' and int(a['start_pts'])==0 and int(a['duration_ts'])==n*1600):return None
        side=probe(path,'-select_streams','v:0','-show_entries','stream_side_data=rotation','-show_streams')['streams'][0]
        if any(float(x.get('rotation',0))!=0 for x in side.get('side_data_list',[])):return None
        packets=probe(path,'-select_streams','v:0','-show_packets','-show_entries','packet=pts,dts,duration')['packets']
        if len(packets)!=n or any(int(x['pts'])!=i*1000 or int(x['dts'])!=i*1000 or int(x['duration'])!=1000 for i,x in enumerate(packets)):return None
        return path.resolve()
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,TypeError,IndexError,StopIteration):return None


def verify(path, frames, width, height):
    ss=streams(path)
    if len(ss)!=2 or {s['codec_type'] for s in ss}!={'video','audio'}:raise RuntimeError('Export must contain one video and one audio stream')
    v=next(s for s in ss if s['codec_type']=='video');a=next(s for s in ss if s['codec_type']=='audio')
    from fractions import Fraction
    seconds=frames/30
    durations=[float(Fraction(s['time_base'])*int(s['duration_ts'])) for s in (v,a)]
    if int(v['nb_frames'])!=frames or v['avg_frame_rate']!='30/1' or (v['width'],v['height'])!=(width,height) or any(not math.isfinite(d) or abs(d-seconds)>.001 for d in durations):raise RuntimeError('Export clock or dimensions failed verification')
    return {'frames':frames,'seconds':seconds,'av_delta_ms':round(abs(durations[0]-durations[1])*1000,3),'width':width,'height':height,'scope':'Container stream metadata; not a perceptual review'}
