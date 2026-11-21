"""Voice cleanup and filler-word removal for the auto-editor, plus loudness matching for A/B demos.

Pure Python plus FFmpeg. Nothing here needs Whisper itself; fillers only get cut when the transcript contains them,
so the transcription step is asked (via a prompt) to keep them.
"""
from __future__ import annotations

import math
import re
import subprocess
from array import array
from pathlib import Path

import studio_clips as clips
import studio_performance as perf

CLEANUP_LEVELS = ("off", "light", "medium", "strong")
_CLEANUP = {
    # two cascaded rumble filters (24 dB/octave), FFT noise reduction (nr = dB of reduction, nf = assumed noise floor), gentle compression
    "light": ["highpass=f=70", "highpass=f=70", "afftdn=nr=9:nf=-45", "acompressor=threshold=0.2:ratio=2:attack=20:release=250:makeup=1.2"],
    "medium": ["highpass=f=80", "highpass=f=80", "afftdn=nr=15:nf=-40", "acompressor=threshold=0.15:ratio=3:attack=15:release=250:makeup=1.6"],
    "strong": ["highpass=f=90", "highpass=f=90", "afftdn=nr=24:nf=-35", "acompressor=threshold=0.1:ratio=4:attack=10:release=200:makeup=2"],
}


def voice_cleanup_filters(level: str) -> list[str]:
    """FFmpeg audio filters that clean up narration, or [] for "off" and anything unknown."""
    return list(_CLEANUP.get(level, []))


# Whisper tends to leave fillers out of transcripts. A prompt that contains some nudges it to keep them.
FILLER_PROMPT = "Umm, let me think, uh, like, hmm... Okay, so, um, here's what I mean, you know, uh."

FILLER_LEVELS = ("off", "basic", "more")
_BASIC = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "eh", "hmm", "hm", "mm", "mhm"}
_PHRASES = [("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z']", "", str(text).lower())


def filler_ranges(words: list[dict], level: str, pad_before: float = .03, pad_after: float = .05) -> list[tuple[float, float]]:
    """Time ranges to delete for filler words. "basic" is um/uh-style sounds; "more" adds "you know", "I mean",
    "sort of" and "kind of". Ordinary words such as "like" are never touched."""
    if level not in ("basic", "more"):
        return []
    ranges: list[tuple[float, float]] = []
    i = 0
    while i < len(words):
        w = words[i]
        text = _norm(w.get("text", ""))
        s, e = clips._clean_float(w.get("start")), clips._clean_float(w.get("end"))
        if text in _BASIC and e > s:
            ranges.append((max(0.0, s - pad_before), e + pad_after))
            i += 1
            continue
        if level == "more" and i + 1 < len(words):
            nxt = words[i + 1]
            pair = (text, _norm(nxt.get("text", "")))
            ns, ne = clips._clean_float(nxt.get("start")), clips._clean_float(nxt.get("end"))
            if pair in _PHRASES and ns - e < .4 and ne > ns:
                ranges.append((max(0.0, s - pad_before), ne + pad_after))
                i += 2
                continue
        i += 1
    return ranges


def subtract_ranges(segments: list[tuple[float, float]], ranges: list[tuple[float, float]],
                    min_piece: float = .15) -> list[tuple[float, float]]:
    """Segments with the given ranges cut out. Slivers shorter than `min_piece` seconds are dropped."""
    result: list[tuple[float, float]] = []
    cuts = sorted(ranges)
    for a, b in segments:
        pieces = [(a, b)]
        for cs, ce in cuts:
            nxt: list[tuple[float, float]] = []
            for pa, pb in pieces:
                if ce <= pa or cs >= pb:
                    nxt.append((pa, pb))
                    continue
                if cs > pa:
                    nxt.append((pa, cs))
                if ce < pb:
                    nxt.append((ce, pb))
            pieces = nxt
        result += [(round(pa, 3), round(pb, 3)) for pa, pb in pieces if pb - pa >= min_piece]
    return result


# ------------------------------------------------------------- loudness matching (A/B demos)

def decode_mono(path: Path, rate: int = 16000, start: float | None = None, length: float | None = None,
                timeout: int = 600) -> array:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error"]
    if start:
        cmd += ["-ss", f"{start:.3f}"]
    if length:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          **perf.windows_child_options(low_priority=True))
    if proc.returncode:
        raise RuntimeError((proc.stderr or b"FFmpeg failed").decode("utf-8", "replace")[-300:])
    data = array("f")
    data.frombytes(proc.stdout[:len(proc.stdout) // 4 * 4])
    return data


def rms_db(samples: array) -> float:
    """Level in dBFS of the audible parts (silence below -60 dB is ignored so pauses do not skew it)."""
    loud = [x * x for x in samples if abs(x) > .001]
    return 10 * math.log10(sum(loud) / len(loud)) if loud else -90.0


def match_gain_db(reference: array, other: array, limit: float = 12.0) -> float:
    """dB to apply to `other` so it sounds as loud as `reference` (clamped, so a silent file cannot explode)."""
    return max(-limit, min(limit, rms_db(reference) - rms_db(other)))
