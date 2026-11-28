"""Lossless repair of the specific legacy 60fps / AAC priming mux defect.
Not a generic video retimer: rejects nonmatching streams and packet clocks.
"""
import json
import subprocess
from pathlib import Path
from uuid import uuid4


def probe(path, args):
    return json.loads(subprocess.check_output(['ffprobe','-v','error',*args,'-of','json',str(path)]))


def packet_hashes(path, kind):
    data=probe(path,['-select_streams',kind,'-show_packets','-show_data_hash','sha256','-show_entries','packet=data_hash'])
    return [p['data_hash'] for p in data['packets']]


def repair_legacy_master(src,dst):
    src,dst=Path(src),Path(dst)
    if dst.exists() or dst.is_symlink():raise FileExistsError(dst)
    streams=probe(src,['-show_streams'])['streams']
    if len(streams)!=2:raise ValueError('Expected exactly one video and audio stream')
    v,a=streams;n=int(v['nb_frames']);duration=n/60
    if (v['codec_name'],v['r_frame_rate'],v['time_base'],v['has_b_frames'],a['codec_name'],a['time_base'])!=('h264','60/1','1/60000',0,'aac','1/48000') or any(abs(float(s['start_time']))>1e-6 for s in streams) or any(abs(float(s['duration'])-duration-1024/48000)>.000002 for s in streams):
        raise ValueError('Not the known legacy priming defect')
    packets=probe(src,['-select_streams','v:0','-show_packets','-show_entries','packet=pts,dts,duration'])['packets']
    if len(packets)!=n or any((p['pts'],p['dts'],p['duration'])!=(0,0,2280) if i==0 else (p['pts'],p['dts'],p['duration'])!=(i*1000+1280,i*1000+1280,1000) for i,p in enumerate(packets)):
        raise ValueError('Unexpected legacy video packet clock')
    dst.parent.mkdir(parents=True,exist_ok=True);temp=dst.parent/(uuid4().hex+'.mp4')
    try:
        subprocess.run(['ffmpeg','-v','error','-nostdin','-y','-i',str(src),'-map','0:v:0','-map','0:a:0','-c','copy','-bsf:v','setts=pts=N*1000:dts=N*1000:duration=1000:time_base=1/60000','-bsf:a','setts=pts=PTS-1024:dts=DTS-1024','-use_editlist','1','-movie_timescale','240000','-video_track_timescale','60000','-movflags','+faststart',str(temp)],check=True,capture_output=True)
        out=probe(temp,['-show_streams'])['streams']
        if out[0]['avg_frame_rate']!='60/1' or int(out[0]['nb_frames'])!=n or any(abs(float(s['duration'])-duration)>1e-6 or abs(float(s['start_time']))>1e-6 for s in out):raise RuntimeError('Remaster clock verification failed')
        for kind in ('v:0','a:0'):
            if packet_hashes(src,kind)!=packet_hashes(temp,kind):raise RuntimeError('Encoded payload changed')
        if dst.exists():raise FileExistsError(dst)
        temp.rename(dst)
        return {'frames':n,'duration':duration,'fps':60,'video_and_audio_packet_payloads_identical':True}
    finally:temp.unlink(missing_ok=True)
