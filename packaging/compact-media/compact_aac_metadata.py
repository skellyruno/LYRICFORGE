"""Research: inspect first AAC packet using the existing FFmpeg binary.

Never use ambiguous or missing metadata to trim audio. This parser is tied to
one verified FFmpeg build and is not a production decoder or general MP4 parser.
"""
import re
import subprocess
from pathlib import Path

_SKIP = re.compile(r'^\[mov,mp4,m4a,3gp,3g2,mj2 @ (?:0x)?[0-9a-fA-F]+\] demuxer injecting skip (\d+) / discard (\d+)\s*$', re.M)
_STREAM = re.compile(r'^\s*Stream #0:\d+[^\n]*?: Audio: ([^\s,]+)', re.M)


def priming_from_debug(log):
    before_mapping = log.split('Stream mapping:', 1)[0]
    if not re.search(r'^Input #0, mov,mp4,m4a,3gp,3g2,mj2, from ', before_mapping, re.M):
        raise ValueError('Unsupported container')
    if _STREAM.findall(before_mapping) != ['aac']:
        raise ValueError('Expected exactly one AAC audio stream')
    values = _SKIP.findall(before_mapping)
    if len(values) != 1:
        raise ValueError('Missing or ambiguous AAC skip metadata')
    skip, discard = map(int, values[0])
    if not 0 <= skip <= 8192 or discard != 0:
        raise ValueError('Unsupported AAC edit list')
    return skip


def read_priming(exe, media):
    result = subprocess.run([str(Path(exe).resolve()), '-hide_banner', '-nostdin',
        '-loglevel', 'debug', '-i', str(Path(media).resolve()), '-map', '0:a:0',
        '-c', 'copy', '-frames:a', '1', '-f', 'null', '-'],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if len(result.stderr) > 2*1024*1024:
        raise ValueError('Excessive metadata output')
    return priming_from_debug(result.stderr.decode(errors='replace'))
