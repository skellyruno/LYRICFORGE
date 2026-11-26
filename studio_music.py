"""Song analysis for the Make tools: find the drop, the best clip window, the tempo and the loudness (pure Python).

Ideas from the music-video poster project, rebuilt without numpy or librosa so the app stays light:
the drop is the biggest sustained rise in energy (quiet build, then a loud, bass-heavy section), and the clip
starts a few seconds before it. Energy is mostly bass (a low-passed copy of the song) plus overall loudness.
"""
from __future__ import annotations

import math
import re
import subprocess
from array import array
from pathlib import Path

import studio_audio as audio
import studio_beat as beat
import studio_edit as edit
import studio_performance as perf
from studio_quick import FAST, QUIET, X264, Quick, _audio, _even, _pick

RATE = beat.RATE                 # 11025 Hz: plenty for a 200 Hz bass band and what the tempo finder expects
FRAME = 0.25                     # seconds per energy frame
MAX_ANALYSIS_SECONDS = 900.0     # pure Python reads every sample: 15 minutes is a few seconds of work, an hour would not be
BEFORE, AFTER = 4.0, 6.0         # the rise is the loudness of the next 6 s against the 4 s before
CLIP_LENGTHS = ("15", "30", "45", "60")
PRE_ROLL = ("3", "5", "8")


# ------------------------------------------------------------------------------------------------------- analysis
def _lowpass(samples: array, hz: float = 200.0) -> list[float]:
    """Two one-pole low-pass stages: keeps the kick and the bass, drops everything above roughly 200 Hz."""
    a = 1 - math.exp(-2 * math.pi * hz / RATE)
    y1 = y2 = 0.0
    out = []
    for x in samples:
        y1 += a * (x - y1)
        y2 += a * (y1 - y2)
        out.append(y2)
    return out


def _norm(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    return [(v - lo) / (hi - lo) for v in values] if hi - lo > 1e-12 else [0.0] * len(values)


def _smooth(values: list[float], k: int) -> list[float]:
    if k <= 1 or len(values) < k:
        return values
    out, run = [], sum(values[:k])
    half = k // 2
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def energy_curve(samples: array) -> list[float]:
    """One 0..1 score per quarter second: bass 50%, loudness 30%, sudden change 20%, smoothed over about a second."""
    step = int(RATE * FRAME)
    bass = _lowpass(samples)
    rms, low = [], []
    for s in range(0, max(1, len(samples) - step + 1), step):
        chunk, deep = samples[s:s + step], bass[s:s + step]
        rms.append(math.sqrt(sum(x * x for x in chunk) / step))
        low.append(math.sqrt(sum(x * x for x in deep) / step))
    if len(rms) < 8:
        return [0.0] * len(rms)
    flux = [0.0] + [max(0.0, rms[i] - rms[i - 1]) for i in range(1, len(rms))]
    mixed = [.5 * b + .3 * r + .2 * f for b, r, f in zip(_norm(low), _norm(rms), _norm(flux))]
    return _smooth(mixed, 4)


def find_drop(curve: list[float], pre: float, clip: float) -> float:
    """The moment with the biggest rise from the few seconds before to the few seconds after (seconds).
    Falls back to the loudest point when nothing rises clearly, and always leaves room for the clip."""
    fps = 1 / FRAME
    total = len(curve) * FRAME
    bw, aw = int(BEFORE * fps), int(AFTER * fps)
    lo, hi = pre, max(pre, total - (clip - pre))
    prefix = [0.0]
    for v in curve:
        prefix.append(prefix[-1] + v)
    best, best_rise = None, -1e9
    for i in range(len(curve)):
        t = i * FRAME
        if t < lo or t > hi:
            continue
        a, b = max(0, i - bw), min(len(curve), i + aw)
        if i - a < 1 or b - i < 1:
            continue
        rise = (prefix[b] - prefix[i]) / (b - i) - (prefix[i] - prefix[a]) / (i - a)
        if rise > best_rise:
            best, best_rise = t, rise
    if best is None:
        window = [(i * FRAME, v) for i, v in enumerate(curve) if lo <= i * FRAME <= hi]
        best = max(window, key=lambda p: p[1])[0] if window else lo
    return round(best, 2)


def clip_window(total: float, drop: float, pre: float, clip: float) -> tuple[float, float]:
    """(start, length) of a clip that starts `pre` seconds before the drop and stays inside the song."""
    length = min(clip, total)
    start = min(max(0.0, drop - pre), max(0.0, total - length))
    return round(start, 2), round(length, 2)


def loudness(path: Path) -> dict:
    """Integrated loudness (LUFS), loudness range (LU) and true peak (dBTP) as FFmpeg's ebur128 reports them; {} if it cannot."""
    try:
        done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                              capture_output=True, text=True, timeout=300, **perf.windows_child_options(low_priority=True))
    except (OSError, subprocess.SubprocessError):
        return {}
    tail = done.stderr[done.stderr.rfind("Summary:"):] if "Summary:" in done.stderr else ""
    found = {}
    for key, pattern in (("lufs", r"I:\s+(-?[\d.]+)\s+LUFS"), ("lra", r"LRA:\s+(-?[\d.]+)\s+LU"), ("peak", r"Peak:\s+(-?[\d.]+)\s+dBFS")):
        m = re.search(pattern, tail)
        if m:
            found[key] = float(m.group(1))
    return found


def analyze_track(path: Path, duration: float, pre: float = 5.0, clip: float = 30.0, with_tempo: bool = True) -> dict:
    """Everything the tools need from one pass over the song."""
    samples = audio.decode_mono(path, RATE, timeout=300)
    total = len(samples) / RATE or duration
    curve = energy_curve(samples)
    drop = find_drop(curve, pre, clip)
    start, length = clip_window(total, drop, pre, clip)
    result = {"duration": round(total, 2), "drop": drop, "start": start, "length": length, "curve": curve}
    if with_tempo:
        found = beat.analyze(samples, total)
        result.update(bpm=found["bpm"], confidence=round(found["confidence"], 2))
    return result


def check_length(info: dict, what: str = "This song") -> None:
    if info["duration"] > MAX_ANALYSIS_SECONDS:
        raise ValueError(f"{what} is longer than {int(MAX_ANALYSIS_SECONDS // 60)} minutes. Trim it first, then find the drop")
    if info["duration"] < 8:
        raise ValueError(f"{what} is too short to find a drop in. It needs at least 8 seconds")


# ------------------------------------------------------------------------------------------------------- tools
def _drop_options(f: dict) -> tuple[float, float]:
    return float(_pick(f, "length", CLIP_LENGTHS, "30")), float(_pick(f, "pre", PRE_ROLL, "5"))


def dropclip_prepare(f, i):
    v = i["video"]
    if not v["has_audio"]:
        raise ValueError("This video has no sound, so there is no drop to find")
    check_length(v, "This video")
    clip, pre = _drop_options(f)
    shape = _pick(f, "shape", ("9:16", "1:1", "original"), "9:16")
    w, h = v["width"], v["height"]
    if shape == "original":
        cw, ch = w, h
    else:
        rw, rh = (9, 16) if shape == "9:16" else (1, 1)
        if w / h > rw / rh:
            ch = _even(h); cw = _even(ch * rw / rh)
        else:
            cw = _even(w); ch = _even(cw * rh / rw)
    return {"clip": clip, "pre": pre, "shape": shape, "cw": cw, "ch": ch, "has_audio": True, "duration": v["duration"], "seconds": min(clip, v["duration"])}


def dropclip_build(p, o, out, safe):
    found = analyze_track(p["video"], o["duration"], o["pre"], o["clip"], with_tempo=False)
    o.update(drop=found["drop"], start=found["start"], seconds=found["length"])
    vf = ("crop=%d:%d," % (o["cw"], o["ch"]) if o["shape"] != "original" else "") + "scale='min(iw,1080)':-2,setsar=1"
    fade = f"afade=t=in:d=0.3,afade=t=out:st={max(0.0, found['length'] - .6):.2f}:d=0.6"
    return [*QUIET, "-y", "-ss", f"{found['start']:.3f}", "-t", f"{found['length']:.3f}", "-i", str(p["video"]), "-map", "0:v:0", "-vf", vf, "-af", fade,
            *_audio(True), *X264, *FAST, str(out)]


def dropaudio_prepare(f, i):
    a = i["audio"]
    check_length(a)
    clip, pre = _drop_options(f)
    return {"clip": clip, "pre": pre, "duration": a["duration"], "seconds": min(clip, a["duration"])}


def dropaudio_build(p, o, out, safe):
    found = analyze_track(p["audio"], o["duration"], o["pre"], o["clip"], with_tempo=False)
    o.update(drop=found["drop"], start=found["start"], seconds=found["length"])
    fade = f"afade=t=in:d=0.3,afade=t=out:st={max(0.0, found['length'] - .6):.2f}:d=0.6"
    return [*QUIET, "-y", "-ss", f"{found['start']:.3f}", "-t", f"{found['length']:.3f}", "-i", str(p["audio"]), "-vn", "-map", "0:a:0", "-af", fade,
            "-c:a", "aac", "-b:a", "192k", "-f", "mp4", str(out)]


def songcard_prepare(f, i):
    check_length(i["audio"])
    return {"duration": i["audio"]["duration"], "seconds": 0}


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def songcard_render(p, o, out):
    """A picture of what the song is like: tempo, loudness, where the drop is, which 30 seconds are best, and its energy over time."""
    from PIL import Image, ImageDraw
    found = analyze_track(p["audio"], o["duration"])
    loud = loudness(p["audio"])
    brand = o["brand"]
    rgb = lambda c: tuple(int(c.lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))  # noqa: E731
    bg, accent, text = rgb(brand["bg"]), rgb(brand["accent"]), rgb(brand["text"])
    muted = tuple(int(c * .6 + b * .4) for c, b in zip(text, bg))
    w, h = 1600, 900
    sheet = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(sheet)
    big, mid, small = (edit.find_font(brand["font"], n) for n in (96, 40, 28))
    stats = [("Tempo", f"{found['bpm']:g} BPM" + ("" if found["confidence"] >= .35 else " (unsure)")),
             ("Length", _clock(found["duration"])),
             ("Loudness", f"{loud['lufs']:g} LUFS" if "lufs" in loud else "n/a"),
             ("Peak", f"{loud['peak']:g} dB" if "peak" in loud else "n/a"),
             ("The drop", _clock(found["drop"])),
             ("Best 30 s", f"{_clock(found['start'])} to {_clock(found['start'] + found['length'])}")]
    draw.text((80, 60), "Song analysis", font=big, fill=accent)
    for k, (name, value) in enumerate(stats):
        x, y = 80 + (k % 3) * 500, 230 + (k // 3) * 150
        draw.text((x, y), name.upper(), font=small, fill=muted)
        draw.text((x, y + 36), value, font=mid, fill=text)
    gx, gy, gw, gh = 80, 560, w - 160, 260
    draw.rectangle([gx, gy, gx + gw, gy + gh], outline=muted, width=2)
    curve, total = found["curve"], max(found["duration"], 1)
    x_of = lambda t: gx + gw * min(1.0, t / total)  # noqa: E731
    draw.rectangle([x_of(found["start"]), gy + 2, x_of(found["start"] + found["length"]), gy + gh - 2], fill=tuple(int(a * .25 + b * .75) for a, b in zip(accent, bg)))
    columns = min(len(curve), gw // 4)
    for c in range(columns):
        lo, hi = int(c * len(curve) / columns), max(int(c * len(curve) / columns) + 1, int((c + 1) * len(curve) / columns))
        v = max(curve[lo:hi]) if curve else 0
        x = gx + 2 + c * (gw - 4) / columns
        draw.rectangle([x, gy + gh - 4 - v * (gh - 12), x + max(1, (gw - 4) / columns - 1), gy + gh - 4], fill=accent)
    dx = x_of(found["drop"])
    draw.line([dx, gy - 14, dx, gy + gh], fill=text, width=3)
    draw.text((min(dx + 10, w - 200), gy - 48), "drop " + _clock(found["drop"]), font=small, fill=text)
    sheet.save(out, "PNG", optimize=True)


def _t(id, title, out, kind, inputs, prepare, build, label, filters=(), **kw):
    return Quick(id, title, out, kind, inputs, prepare, build, label, tuple(filters), **kw)


V = (("video", "video", True),)
A = (("audio", "audio", True),)

TOOLS: dict[str, Quick] = {q.id: q for q in (
    _t("dropclip", "Clip around the drop", "drop_clip.mp4", "video", V, dropclip_prepare, dropclip_build,
       lambda o: f"{o['seconds']:g} s clip, drop at {_clock(o['drop'])}", ("crop", "scale", "setsar", "afade")),
    _t("dropaudio", "Best part of a song", "drop_audio.m4a", "audio", A, dropaudio_prepare, dropaudio_build,
       lambda o: f"{o['seconds']:g} s around the drop at {_clock(o['drop'])}", ("afade",)),
    _t("songcard", "Song analysis", "song_analysis.png", "image", A, songcard_prepare, lambda *a: [], lambda o: "Song analysis", ("ebur128",),
       render=songcard_render, brand=True),
)}
