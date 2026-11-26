"""Beat and tempo analysis for the music-video editor (pure Python).

Finds a steady tempo from the audio's loudness changes, lays a beat grid on it, and measures how energetic each bar
is so cuts can be faster in the loud parts. Assumes a fairly steady tempo, which is true of most produced music; live
recordings that speed up and slow down will drift off the grid.
"""
from __future__ import annotations

import math
from array import array

RATE = 11025
WINDOW, HOP = 256, 128  # about 23 ms windows every 11.6 ms


def onset_envelope(samples: array) -> list[float]:
    """How much louder each moment is than the one before it (positive jumps in log energy)."""
    n = len(samples)
    if n < WINDOW * 4:
        return []
    prefix = [0.0] * (n + 1)
    total = 0.0
    for i, x in enumerate(samples):
        total += x * x
        prefix[i + 1] = total
    energy = [math.log1p(2000 * (prefix[i + WINDOW] - prefix[i]) / WINDOW) for i in range(0, n - WINDOW, HOP)]
    flux = [0.0] + [max(0.0, energy[i] - energy[i - 1]) for i in range(1, len(energy))]
    # subtract a short moving average so steady loud sections do not swamp the beats
    out, window = [], 24
    run = sum(flux[:window])
    for i, v in enumerate(flux):
        lo, hi = max(0, i - window // 2), min(len(flux), i + window // 2)
        mean = sum(flux[lo:hi]) / max(1, hi - lo)
        out.append(max(0.0, v - mean))
    return out


def estimate_tempo(env: list[float], fps: float, low: float = 70, high: float = 170) -> float:
    """BPM from autocorrelation of the onset envelope, refined between frames and nudged toward common tempos."""
    if len(env) < fps * 4:
        return 0.0
    lags = range(int(fps * 60 / high) - 1, int(fps * 60 / low) + 2)
    mean = sum(env) / len(env)
    centered = [x - mean for x in env]
    scores = {}
    for lag in lags:
        s = sum(centered[i] * centered[i - lag] for i in range(lag, len(centered)))
        bpm = 60 * fps / lag
        prior = math.exp(-0.5 * ((math.log2(bpm / 120.0)) / .6) ** 2)  # people make music near 120 more often than 70 or 170
        scores[lag] = s * (.6 + .4 * prior) / (len(centered) - lag)
    best = max(scores, key=scores.get)
    a, b, c = scores.get(best - 1, scores[best]), scores[best], scores.get(best + 1, scores[best])
    denom = a - 2 * b + c
    shift = .5 * (a - c) / denom if denom else 0.0  # parabolic refinement of the peak
    return 60 * fps / (best + max(-.5, min(.5, shift)))


def tempo_confidence(env: list[float], fps: float, bpm: float) -> float:
    """0..1: how strongly the onset envelope repeats at the detected beat period. Steady clicks score 0.8+, noise, a drifting
    tempo or random hits score under 0.1, and a track with no onsets at all (a drone) scores 0."""
    if bpm <= 0 or not env or max(env) < .15:
        return 0.0
    lag, n = fps * 60 / bpm, len(env)
    mean = sum(env) / n
    centered = [x - mean for x in env]
    base = sum(x * x for x in centered)
    if base <= 0:
        return 0.0

    def corr(shift: int) -> float:
        return sum(centered[i] * centered[i - shift] for i in range(shift, n)) / base * (n / max(1, n - shift))

    r = max(corr(max(1, int(round(lag)) + d)) for d in (-1, 0, 1))
    return round(max(0.0, min(1.0, r / .45)), 2)


LOW_CONFIDENCE = .5


def beat_grid(env: list[float], fps: float, bpm: float, duration: float) -> tuple[list[float], int]:
    """Beat times (seconds) aligned to the strongest onsets, and which of the four beats in a bar is the downbeat."""
    if bpm <= 0:
        return [], 0
    period = fps * 60 / bpm
    best_offset, best_score = 0.0, -1.0
    steps = max(8, int(period))
    for k in range(steps):
        offset = period * k / steps
        score, pos = 0.0, offset
        while pos < len(env) - 1:
            i = int(round(pos))
            score += env[i] + .5 * (env[i - 1] if i > 0 else 0) + .5 * (env[i + 1] if i + 1 < len(env) else 0)
            pos += period
        if score > best_score:
            best_offset, best_score = offset, score
    beats, pos = [], best_offset
    while pos / fps < duration:
        beats.append(round(pos / fps, 3))
        pos += period
    phase_scores = [0.0] * 4  # the downbeat is usually the strongest of the four beats
    for n, t in enumerate(beats):
        i = min(len(env) - 1, int(round(t * fps)))
        phase_scores[n % 4] += env[i]
    return beats, max(range(4), key=lambda p: phase_scores[p])


def bar_energy(samples: array, beats: list[float], down: int, rate: int = RATE) -> list[dict]:
    """Loudness per bar (four beats), 0..1 relative to the loudest bar."""
    bars = []
    for first in range(down, len(beats) - 4, 4):
        a, b = int(beats[first] * rate), int(beats[first + 4] * rate)
        chunk = samples[a:b]
        rms = math.sqrt(sum(x * x for x in chunk) / max(1, len(chunk)))
        bars.append({"start": beats[first], "end": beats[first + 4], "first_beat": first, "rms": rms})
    peak = max((b["rms"] for b in bars), default=0.0) or 1.0
    for b in bars:
        b["energy"] = round(b["rms"] / peak, 3)
    return bars


def analyze(samples: array, duration: float) -> dict:
    env = onset_envelope(samples)
    fps = RATE / HOP
    bpm = estimate_tempo(env, fps)
    beats, down = beat_grid(env, fps, bpm, duration)
    return {"bpm": round(bpm, 1), "beats": beats, "downbeat": down, "bars": bar_energy(samples, beats, down),
            "confidence": tempo_confidence(env, fps, bpm)}


INTENSITY = {"calm": (4, 8), "medium": (2, 4), "hype": (1, 2)}  # beats per cut: (loud sections, quiet sections)


def plan_cuts(analysis: dict, duration: float, intensity: str = "medium") -> list[dict]:
    """Cut intervals on the beat grid. Loud bars cut faster. Each cut says whether it starts a loud section (flash)."""
    beats, bars = analysis["beats"], analysis["bars"]
    if len(beats) < 8:
        return []
    fast, slow = INTENSITY.get(intensity, INTENSITY["medium"])
    energies = sorted(b["energy"] for b in bars) or [0.5]
    threshold = energies[len(energies) // 2]
    bar_of = {}
    for bar in bars:
        for k in range(4):
            bar_of[bar["first_beat"] + k] = bar
    cuts, i, prev_loud = [], analysis["downbeat"] if analysis["downbeat"] < len(beats) else 0, False
    first = beats[i]
    if first > .3:
        cuts.append({"start": 0.0, "end": round(first, 3), "beats": 0, "strong": False, "flash": False, "energy": 0.0})
    while i < len(beats) - 1:
        bar = bar_of.get(i)
        loud = bool(bar and bar["energy"] >= threshold)
        step = fast if loud else slow
        j = min(i + step, len(beats) - 1)
        end = beats[j]
        if i + step >= len(beats):
            end = duration
        cuts.append({"start": round(beats[i], 3), "end": round(end, 3), "beats": j - i, "strong": (i - analysis["downbeat"]) % 4 == 0,
                     "flash": loud and not prev_loud, "energy": bar["energy"] if bar else 0.0})
        prev_loud = loud
        if end >= duration:
            break
        i = j
    if cuts and cuts[-1]["end"] < duration - .05:
        cuts[-1]["end"] = round(duration, 3)
    return [c for c in cuts if c["end"] - c["start"] > .12]
