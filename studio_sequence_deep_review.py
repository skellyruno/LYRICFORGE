"""Opt-in, read-only decoded-stream QC; never changes or normalizes the export."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


def parse(progress, diagnostics, expected_frames):
    if not re.search(r'^progress=end\s*$', progress, re.M):
        raise RuntimeError('Incomplete export decode progress')
    frames = re.findall(r'^frame=\s*(\d+)\s*$', progress, re.M)
    if not frames or int(frames[-1]) != expected_frames:
        raise RuntimeError('Decoded video frame count differs from the timeline')
    reports = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', diagnostics, re.S)
    if len(reports) != 1:
        raise RuntimeError('Missing or ambiguous audio loudness measurements')
    data = json.loads(reports[0])
    def metric(key, allow_silence=False):
        value = float(data[key])
        if allow_silence and value == -math.inf:
            return None
        if not math.isfinite(value):
            raise RuntimeError('Invalid decoded audio measurement')
        return value
    loudness = metric('input_i', True)
    peak = metric('input_tp', True)
    lra = metric('input_lra')
    warnings = []
    if loudness is None:
        warnings.append('Audio below the integrated loudness measurement floor; review intentional silence.')
    elif loudness < -24 or loudness > -10:
        warnings.append('Audio loudness is outside the suggested promotional-video range (-24 to -10 LUFS).')
    if peak is not None and peak > -1:
        warnings.append('Decoded true peak exceeds -1 dBTP; review output headroom.')
    return {'decoded_frames':expected_frames,'integrated_lufs':loudness,'true_peak_dbtp':peak,'loudness_range_lu':lra,'warnings':warnings,'needs_review':bool(warnings),'scope':'Complete stream decode and input loudness measurements; not a normalization pass or a perceptual quality guarantee.'}


def review(path, expected_frames, *, cancel=lambda:None, timeout=1800):
    if not isinstance(expected_frames,int) or not 1<=expected_frames<=54000:
        raise ValueError('Invalid expected video frame count')
    path = Path(path).resolve(strict=True)
    start = time.monotonic()
    # Capture bounded logs on disk instead of buffering video or audio in RAM.
    args=['ffmpeg','-hide_banner','-nostdin','-v','info','-xerror','-threads','2','-i',str(path),'-map','0:v:0','-map','0:a:0','-af','loudnorm=I=-16:TP=-1:LRA=11:print_format=json','-threads','2','-progress','pipe:1','-nostats','-f','null','-']
    with tempfile.TemporaryFile() as progress,tempfile.TemporaryFile() as diagnostics:
        with subprocess.Popen(args,stdout=progress,stderr=diagnostics,stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0) as proc:
            try:
                while proc.poll() is None:
                    cancel()
                    if time.monotonic()-start>timeout:raise TimeoutError('Export review timed out')
                    if progress.tell()>8*1024*1024 or diagnostics.tell()>8*1024*1024:raise RuntimeError('Excessive export review diagnostics')
                    time.sleep(.05)
                cancel()
                if proc.returncode:raise RuntimeError('Export decode or audio measurement failed')
                progress.seek(0);diagnostics.seek(0)
                result=parse(progress.read(8*1024*1024).decode('utf-8','replace'),diagnostics.read(8*1024*1024).decode('utf-8','replace'),expected_frames)
            finally:
                if proc.poll() is None:proc.kill();proc.wait()
    result['seconds']=round(time.monotonic()-start,3)
    return result
