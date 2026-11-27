"""Lossless picture assembly for a five-chapter, frame-exact 60 fps master.
Supply the actual narration clock, completed scene clips and a finished PCM mix.
Never stretch narration, truncate audio, re-encode picture or overwrite a master.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import wave
from fractions import Fraction

FPS = 60


def file_hash(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def probe(path, *args):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', *args,
                                               '-of', 'json', str(path)], timeout=180))


def picture(path, frames):
    streams = probe(path, '-show_streams', '-show_data_hash', 'sha256')['streams']
    if len(streams) != 1 or streams[0]['codec_type'] != 'video':
        raise ValueError('Scene must be a video-only clip: ' + str(path))
    v = streams[0]
    tick = Fraction(v['time_base'])
    if (v['codec_name'] != 'h264' or v['has_b_frames'] != 0 or v['avg_frame_rate'] != '60/1'
            or Fraction(v['start_time']) != 0 or int(v['nb_frames']) != frames
            or int(v['duration_ts']) * tick != Fraction(frames, FPS)):
        raise ValueError('Unexpected scene format or clock: ' + str(path))
    packets = probe(path, '-select_streams', 'v:0', '-show_packets', '-show_data_hash', 'sha256',
                    '-show_entries', 'packet=pts,dts,duration,data_hash,flags')['packets']
    if len(packets) != frames or 'K' not in packets[0]['flags'] or any(
            p['pts'] * tick != Fraction(i, FPS) or p['dts'] * tick != Fraction(i, FPS)
            or p['duration'] * tick != Fraction(1, FPS) for i, p in enumerate(packets)):
        raise ValueError('Scene packet clock is not contiguous: ' + str(path))
    signature = tuple(v[k] for k in ('width', 'height', 'pix_fmt', 'profile', 'level', 'extradata_hash'))
    return signature, [p['data_hash'] for p in packets]


def read_clock(clock):
    cuts = clock['chapter_frames']
    if (clock['fps'] != FPS or len(cuts) != 6 or any(type(n) is not int for n in cuts)
            or cuts[0] != 0 or cuts[-1] != clock['frames'] or cuts[-1] > FPS * 600
            or any(a >= b for a, b in zip(cuts, cuts[1:]))):
        raise ValueError('Invalid five-chapter narration clock')
    return cuts


def finalize(clock, clips, mix, output):
    cuts = read_clock(clock)
    clips = [Path(p).resolve(strict=True) for p in clips]
    mix, output = Path(mix).resolve(strict=True), Path(output)
    if len(clips) != 5 or len(set(clips)) != 5:
        raise ValueError('Exactly five distinct scene clips required')
    if output.exists() or output.is_symlink() or output.suffix.lower() != '.mp4':
        raise ValueError('Output must be a new MP4 path')
    signatures, expected_hashes = [], []
    for p, a, b in zip(clips, cuts, cuts[1:]):
        sig, hashes = picture(p, b - a)
        signatures.append(sig)
        expected_hashes.extend(hashes)
    if len(set(signatures)) != 1:
        raise ValueError('Scene encoders differ; lossless concat not safe')
    with wave.open(str(mix), 'rb') as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        samples = wav.getnframes()
        if (rate not in (24000, 48000) or channels not in (1, 2) or width not in (2, 3, 4)
                or samples * FPS != cuts[-1] * rate):
            raise ValueError('PCM mix length must match the complete picture exactly')
        actual_bytes = 0
        while chunk := wav.readframes(65536):
            actual_bytes += len(chunk)
        if actual_bytes != samples * channels * width:
            raise ValueError('Truncated PCM mix')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='skell-final-', dir=output.parent) as directory:
        root = Path(directory)
        names = []
        for i, clip in enumerate(clips):
            name = f'scene-{i:02d}.mp4'
            try:
                os.link(clip, root / name)
            except OSError:
                shutil.copyfile(clip, root / name)
            names.append(name)
        listing = root / 'scenes.ffconcat'
        listing.write_text('ffconcat version 1.0\n' + ''.join(f"file '{name}'\n" for name in names), encoding='ascii')
        temp = root / 'master.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '1', '-auto_convert', '0',
                        '-i', str(listing), '-i', str(mix), '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                        '-bsf:v', 'setts=pts=N*1000:dts=N*1000:duration=1000:time_base=1/60000',
                        '-c:a', 'aac', '-b:a', '320k', '-ar', '48000', '-use_editlist', '1',
                        '-movie_timescale', '240000', '-video_track_timescale', '60000', '-movflags', '+faststart',
                        str(temp)], check=True, capture_output=True, timeout=600)
        streams = probe(temp, '-show_streams')['streams']
        if len(streams) != 2:
            raise RuntimeError('Master stream count mismatch')
        v, a = streams
        if ((v['codec_name'], a['codec_name']) != ('h264', 'aac') or v['avg_frame_rate'] != '60/1'
                or int(v['nb_frames']) != cuts[-1] or a['channels'] != channels
                or any(Fraction(s['start_time']) != 0 or int(s['duration_ts']) * Fraction(s['time_base']) != Fraction(cuts[-1], FPS) for s in streams)):
            raise RuntimeError('Master stream clock mismatch')
        packets = probe(temp, '-select_streams', 'v:0', '-show_packets', '-show_data_hash', 'sha256',
                        '-show_entries', 'packet=pts,dts,duration,data_hash')['packets']
        if [p['data_hash'] for p in packets] != expected_hashes or any(
                (p['pts'], p['dts'], p['duration']) != (i * 1000, i * 1000, 1000) for i, p in enumerate(packets)):
            raise RuntimeError('Master picture payload or packet clock changed')
        report = {'frames': cuts[-1], 'fps': FPS, 'chapter_frames': cuts, 'duration': cuts[-1] / FPS,
                  'audio_input_samples': samples, 'audio_input_rate': rate,
                  'video_packet_hashes_identical': True, 'master_sha256': file_hash(temp),
                  'scene_sha256': [file_hash(p) for p in clips], 'mix_sha256': file_hash(mix)}
        # Exclusive publication: no replacement even if another process created the target.
        os.link(temp, output)
        return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('clock', type=Path)
    p.add_argument('mix', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('scenes', nargs=5, type=Path)
    a = p.parse_args()
    print(json.dumps(finalize(json.loads(a.clock.read_text()), a.scenes, a.mix, a.output), indent=2))
