"""Exercise the installed multitrack renderer, without requiring any AI models."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import studio_sequence as seq
import studio_sequence_render as renderer


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(fixtures, output):
    fixtures, output = Path(fixtures).resolve(), Path(output).resolve()
    video, music = fixtures / 'video.mp4', fixtures / 'pcm24.wav'
    sources = {str(p): digest(p) for p in (video, music)}
    assets = {
        'source': {'path': video, 'duration': 8., 'has_video': True, 'has_audio': True},
        'cutaway': {'path': video, 'duration': 8., 'has_video': True, 'has_audio': True},
        'music': {'path': music, 'duration': 8., 'has_video': False, 'has_audio': True, 'music': True},
    }
    state = seq.initial(assets)
    for action in (
        {'op': 'put', 'layer': {'id': 'picture', 'kind': 'visual', 'asset': 'cutaway', 'at': 60, 'length': 60, 'offset': 90, 'fade': 4}},
        {'op': 'put', 'layer': {'id': 'score', 'kind': 'music', 'asset': 'music', 'at': 0, 'length': 210, 'gain': .12, 'duck': True}},
        {'op': 'put', 'layer': {'id': 'impact', 'kind': 'sfx', 'effect': 'impact', 'at': 150, 'length': 20, 'gain': .08}},
        {'op': 'ripple', 'instruction': 'cut 1 to 2'},
        {'op': 'transition', 'kind': 'dip', 'at': 30, 'half': 5},
    ):
        state = seq.apply(state, action, assets)
    if state['base']['frames'] != 210 or len(state['layers']) < 3:
        raise RuntimeError('Unexpected ripple sequence')
    with tempfile.TemporaryDirectory(prefix='installed-sequence-') as folder:
        target = Path(folder) / 'render.mp4'
        stats = renderer.render(state, assets, target, width=320, height=180)
        info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,duration,nb_frames,avg_frame_rate', '-of', 'json', str(target)], timeout=30))
        streams = {row['codec_type']: row for row in info['streams']}
        if set(streams) != {'audio', 'video'} or any(abs(float(x['duration']) - 7.) > .001 for x in streams.values()) or int(streams['video']['nb_frames']) != 210:
            raise RuntimeError('Installed sequence clock mismatch: ' + repr(streams))
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(target), '-f', 'null', '-'], check=True, timeout=60)
    if any(digest(Path(path)) != value for path, value in sources.items()):
        raise RuntimeError('Source media changed')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'passed': True, 'frames': 210, 'seconds': 7., 'layer_count': len(state['layers']), 'streams': streams, 'render': stats, 'sources_preserved': True}, indent=2), encoding='utf-8')
