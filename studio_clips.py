"""Autonomous Shorts and clip helpers for SkellyMotion.

Pure Python plus FFmpeg. This module never imports FastAPI, Whisper or any
heavy optional package, so it can be tested on its own and imported cheaply.

Honesty notes (also shown in the README):
  * Picking is heuristic. Every suggestion carries human-readable reasons and
    must be approved by a person before export.
  * Word timing for sung vocals is only as good as Whisper's word timestamps.
  * The optional LLM rerank is opt-in (needs ANTHROPIC_API_KEY) and always
    falls back to the heuristic score when it is unavailable or fails.
"""
from __future__ import annotations

import difflib
import json
import math
import os
import re
import subprocess
import urllib.request
import uuid
from array import array
from pathlib import Path
from typing import Any, Callable

import studio_performance as perf

SHORT_MIN, SHORT_MAX = 15.0, 45.0
CLIP_MIN, CLIP_MAX = 20.0, 60.0
STOPWORDS = frozenset(
    "a an and are as at be but by for from had has have he her his i if in into is it its just "
    "me my not of on or our she so that the their them then there they this to was we were what "
    "when which who will with you your yeah like got gonna wanna um uh oh about because around "
    "does every anyway know think tell really would could should going thing things people "
    "very much more some than also only over under after before while where how why all any "
    "can did get make way want let say said one two out up down too even still".split())
HOOK_WORDS = frozenset(
    "never secret how why stop mistake best free new finally watch here's heres worst biggest "
    "easy fast actually truth nobody everyone need".split())


# ---------------------------------------------------------------- text utils

def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", str(text).lower())).strip()


def asstime(seconds: float) -> str:
    cs = round(max(0.0, seconds) * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def _clean_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


# ------------------------------------------------------------- audio helpers

def audio_envelope(path: Path, points: int = 600, timeout: int = 300) -> list[float]:
    """Peak envelope (0..1) of the first audio stream, decoded at 1 kHz mono."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-threads", "1",
           "-i", str(path), "-vn", "-ac", "1", "-ar", "1000", "-f", "f32le", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          **perf.windows_child_options(low_priority=True))
    if proc.returncode:
        raise RuntimeError((proc.stderr or b"FFmpeg failed").decode("utf-8", "replace")[-300:])
    raw = array("f")
    raw.frombytes(proc.stdout[:len(proc.stdout) // 4 * 4])
    return perf.waveform_envelope(raw, max(10, points))


def envelope_mean(envelope: list[float], duration: float, start: float, end: float) -> float:
    if not envelope or duration <= 0 or end <= start:
        return 0.0
    n = len(envelope)
    a = max(0, min(n - 1, int(start / duration * n)))
    b = max(a + 1, min(n, int(math.ceil(end / duration * n))))
    chunk = envelope[a:b]
    return sum(chunk) / len(chunk) if chunk else 0.0


# ----------------------------------------------------- song Shorts (lyric mode)

def repetition_counts(lines: list[dict]) -> list[int]:
    """For each lyric line, how many OTHER lines are the same or nearly the same."""
    norm = [normalize(ln.get("text", "")) for ln in lines]
    exact: dict[str, int] = {}
    for text in norm:
        if len(text.split()) >= 2:
            exact[text] = exact.get(text, 0) + 1
    counts = []
    for i, text in enumerate(norm):
        if len(text.split()) < 2:
            counts.append(0)
            continue
        total = exact[text] - 1
        for j, other in enumerate(norm):
            if i == j or other == text or len(other.split()) < 2:
                continue
            matcher = difflib.SequenceMatcher(None, text, other)
            if matcher.real_quick_ratio() >= .82 and matcher.quick_ratio() >= .82 and matcher.ratio() >= .82:
                total += 1
        counts.append(total)
    return counts


def pick_short_segments(lines: list[dict], envelope: list[float], duration: float, count: int = 3,
                        min_len: float = SHORT_MIN, max_len: float = SHORT_MAX,
                        max_gap: float = 8.0) -> list[dict]:
    """Suggest the best 15 to 45 second windows of a song, cut only on line edges."""
    rows = sorted((ln for ln in lines if str(ln.get("text", "")).strip()
                   and _clean_float(ln.get("end")) > _clean_float(ln.get("start"))),
                  key=lambda ln: _clean_float(ln.get("start")))
    if not rows or duration <= 0:
        return []
    starts = [_clean_float(r["start"]) for r in rows]
    ends = [_clean_float(r["end"]) for r in rows]
    reps = repetition_counts(rows)
    overall = envelope_mean(envelope, duration, 0, duration) or 1e-6
    intro_edge = min(8.0, duration * .08)
    outro_edge = max(0.0, duration - min(6.0, duration * .06))

    windows: set[tuple[int, int]] = set()
    for i in range(len(rows)):
        first = last = None
        near, near_gap = None, 1e9
        for k in range(i, len(rows)):
            length = ends[k] - starts[i]
            # Never let a Short swallow a long instrumental break.
            if length > max_len or (k > i and starts[k] - ends[k - 1] > max_gap):
                break
            if length >= min_len:
                first = k if first is None else first
                last = k
                if abs(length - 30.0) < near_gap:
                    near, near_gap = k, abs(length - 30.0)
        for k in (first, last, near):
            if k is not None:
                windows.add((i, k))
    if not windows:  # Short song: offer the whole sung span as one option.
        span = ends[-1] - starts[0]
        if span >= 3.0:
            windows.add((0, len(rows) - 1))

    scored = []
    for i, k in windows:
        start, end = starts[i], ends[k]
        length = end - start
        group = range(i, k + 1)
        avg_rep = sum(reps[g] for g in group) / len(group)
        words = sum(len(rows[g].get("words") or str(rows[g]["text"]).split()) for g in group)
        wps = words / max(length, .1)
        loud = envelope_mean(envelope, duration, start, end) / overall
        repeat_s = min(1.0, avg_rep / 3.0)
        loud_s = min(1.5, loud) / 1.5
        dens_s = min(1.0, wps / 3.0)
        score = .45 * repeat_s + .30 * loud_s + .25 * dens_s
        reasons = []
        if avg_rep >= 1:
            reasons.append(f"lines repeat about {round(avg_rep) + 1} times in the song (likely chorus)")
        if loud >= 1.1:
            reasons.append("louder than the song average")
        if wps >= 2.2:
            reasons.append("dense vocals")
        if start < intro_edge:
            score -= .15
            reasons.append("starts near the intro (small penalty)")
        if end > outro_edge:
            score -= .10
            reasons.append("ends near the outro (small penalty)")
        if not reasons:
            reasons.append("steady vocals")
        scored.append({"start": round(start, 3), "end": round(end, 3), "score": round(score, 3),
                       "reasons": reasons, "hook": str(rows[i]["text"]).strip()[:80],
                       "line_ids": [rows[g].get("id") for g in group if rows[g].get("id")]})
    return _pick_non_overlapping(scored, count)


def _pick_non_overlapping(scored: list[dict], count: int, tolerance: float = .25) -> list[dict]:
    chosen: list[dict] = []
    for item in sorted(scored, key=lambda s: (-s["score"], s["start"])):
        clash = False
        for other in chosen:
            overlap = min(item["end"], other["end"]) - max(item["start"], other["start"])
            shorter = min(item["end"] - item["start"], other["end"] - other["start"])
            if overlap > tolerance * shorter:
                clash = True
                break
        if not clash:
            chosen.append(item)
        if len(chosen) >= max(1, count):
            break
    return sorted(chosen, key=lambda s: s["start"])


def shift_lines(lines: list[dict], start: float, end: float) -> list[dict]:
    """Lines inside [start, end], re-timed so the segment begins at 0 s."""
    shifted = []
    for line in lines:
        s, e = _clean_float(line.get("start")), _clean_float(line.get("end"))
        if e <= start or s >= end:
            continue
        words = []
        for w in line.get("words") or []:
            ws = max(_clean_float(w.get("start")), start) - start
            we = min(_clean_float(w.get("end")), end) - start
            if we > ws + .01:
                words.append({**w, "start": round(ws, 3), "end": round(we, 3)})
        shifted.append({**line, "start": round(max(s, start) - start, 3),
                        "end": round(min(e, end) - start, 3), "words": words})
    return shifted


def add_hook_to_ass(path: Path, hook: str, width: int, height: int, seconds: float = 1.5,
                    font: str = "Arial") -> bool:
    """Append a top-of-frame hook card to an existing ASS file. False if no hook."""
    text = re.sub(r"\s+", " ", str(hook or "")).strip()[:80]
    if not text:
        return False
    content = path.read_text(encoding="utf-8-sig")
    size = round(54 * width / 720)
    margin = round(height * .12)
    style = (f"Style: Hook,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00101511,&HB0000000,"
             f"-1,0,0,0,100,100,0,0,3,10,0,8,40,40,{margin},1\n")
    marker = "\n[Events]"
    if marker not in content:
        return False
    head, tail = content.split(marker, 1)
    if not head.endswith("\n"):
        head += "\n"
    escaped = text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    event = f"Dialogue: 1,{asstime(0)},{asstime(seconds)},Hook,,0,0,0,,{{\\fad(150,250)}}{escaped}\n"
    path.write_text(head + style + marker + tail.rstrip("\n") + "\n" + event, encoding="utf-8-sig")
    return True


# ------------------------------------------------------ long video auto-clipper

def split_sentences(words: list[dict], gap: float = .7, max_words: int = 40) -> list[dict]:
    """Group Whisper words into sentences at punctuation and speaking pauses."""
    sentences, group = [], []

    def flush():
        if group:
            sentences.append({"start": round(_clean_float(group[0]["start"]), 3),
                              "end": round(_clean_float(group[-1]["end"]), 3),
                              "text": " ".join(str(w["text"]) for w in group).strip(),
                              "words": list(group)})
            group.clear()

    for i, word in enumerate(words):
        if not str(word.get("text", "")).strip():
            continue
        group.append(word)
        text = str(word["text"]).strip()
        nxt = words[i + 1] if i + 1 < len(words) else None
        pause = nxt is not None and _clean_float(nxt["start"]) - _clean_float(word["end"]) > gap
        if re.search(r"[.!?…]$", text) or pause or len(group) >= max_words or nxt is None:
            flush()
    return sentences


def candidate_windows(sentences: list[dict], min_len: float = CLIP_MIN,
                      max_len: float = CLIP_MAX, max_gap: float = 6.0) -> list[tuple[int, int]]:
    found: set[tuple[int, int]] = set()
    for i in range(len(sentences)):
        first = last = None
        near, near_gap = None, 1e9
        for k in range(i, len(sentences)):
            length = sentences[k]["end"] - sentences[i]["start"]
            # A clip must not span dead air (a break in the talk, a cut-away).
            if length > max_len or (k > i and sentences[k]["start"] - sentences[k - 1]["end"] > max_gap):
                break
            if length >= min_len:
                first = k if first is None else first
                last = k
                if abs(length - 35.0) < near_gap:
                    near, near_gap = k, abs(length - 35.0)
        for k in (first, last, near):
            if k is not None:
                found.add((i, k))
    return sorted(found)


def hook_strength(text: str) -> tuple[float, list[str]]:
    words = normalize(text).split()
    if not words:
        return 0.0, []
    score, reasons = .25, []
    if text.strip().endswith("?"):
        score += .3
        reasons.append("opens with a question")
    if re.search(r"\d", text):
        score += .15
        reasons.append("opens with a number")
    if any(w in HOOK_WORDS for w in words):
        score += .2
        reasons.append("opens with a strong hook word")
    if 4 <= len(words) <= 18:
        score += .1
    return min(1.0, score), reasons


def score_window(sentences: list[dict], i: int, k: int, envelope: list[float], duration: float,
                 scene_times: list[float]) -> dict:
    start, end = sentences[i]["start"], sentences[k]["end"]
    length = max(end - start, .1)
    group = sentences[i:k + 1]
    words = sum(len(s["words"]) for s in group)
    wps = words / length
    hook_s, reasons = hook_strength(group[0]["text"])
    pace_s = 1 - min(1.0, abs(wps - 2.75) / 2.75)
    overall = envelope_mean(envelope, duration, 0, duration) or 1e-6
    energy = envelope_mean(envelope, duration, start, end) / overall if envelope else 1.0
    energy_s = min(1.5, energy) / 1.5
    changes = sum(1 for t in scene_times if start <= t < end)
    scene_s = min(1.0, (changes / (length / 10.0)) / .6) if scene_times else 0.0
    ends_clean = bool(re.search(r"[.!?…]$", group[-1]["text"].strip()))
    complete_s = 1.0 if ends_clean else .5
    silence = sum(max(0.0, group[n + 1]["start"] - group[n]["end"] - 1.5) for n in range(len(group) - 1))
    silence_ratio = min(1.0, silence / length)
    score = (.28 * hook_s + .20 * pace_s + .20 * energy_s + .12 * scene_s
             + .20 * complete_s - .30 * silence_ratio)
    if 2.0 <= wps <= 3.6:
        reasons.append("good speaking pace")
    if energy >= 1.1:
        reasons.append("louder, more energetic section")
    if changes:
        reasons.append(f"{changes} visual scene change{'s' if changes != 1 else ''}")
    if ends_clean:
        reasons.append("ends on a complete sentence")
    if silence_ratio > .15:
        reasons.append("long pauses (penalty)")
    if not reasons:
        reasons.append("steady speech")
    text = " ".join(s["text"] for s in group)
    return {"start": round(start, 3), "end": round(end, 3), "score": round(score, 3),
            "reasons": reasons, "text": text, "hook": group[0]["text"].strip()[:90]}


def suggest_clips(words: list[dict], envelope: list[float], duration: float,
                  scene_times: list[float] | None = None, count: int = 5,
                  min_len: float = CLIP_MIN, max_len: float = CLIP_MAX) -> list[dict]:
    sentences = split_sentences(words)
    if not sentences:
        return []
    windows = candidate_windows(sentences, min_len, max_len)
    if not windows:  # Short source: one clip covering everything that was said.
        span = sentences[-1]["end"] - sentences[0]["start"]
        if span >= 3.0:
            windows = [(0, len(sentences) - 1)]
    scored = [score_window(sentences, i, k, envelope, duration, scene_times or [])
              for i, k in windows]
    picks = _pick_non_overlapping(scored, count)
    for pick in picks:
        pick.update(heuristic_metadata(pick["text"], pick["hook"]))
        pick["id"] = uuid.uuid4().hex[:10]
    return picks


def heuristic_metadata(text: str, hook: str) -> dict:
    title = re.sub(r"[\s.,;:!-]+$", "", hook.strip())[:70] or "Clip"
    counts: dict[str, int] = {}
    for token in normalize(text).split():
        if len(token) > 3 and token not in STOPWORDS and not token.isdigit():
            counts[token] = counts.get(token, 0) + 1
    tags = [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[:6]]
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    description = " ".join(sentences[:2])[:200].strip()
    return {"title": title, "description": description, "tags": tags}


# ------------------------------------------------------------ optional LLM rerank

def default_post(url: str, headers: dict, payload: dict, timeout: int = 60) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https URL)
        return json.loads(response.read().decode("utf-8"))


def llm_rerank(candidates: list[dict], api_key: str, model: str,
               post: Callable[..., dict] | None = None, limit: int = 15) -> dict[str, dict] | None:
    """Ask Claude to rank candidates. Returns {id: {...}} or None on ANY failure."""
    if not api_key or not candidates:
        return None
    top = candidates[:limit]
    listing = "\n\n".join(f"ID {c['id']} ({c['end'] - c['start']:.0f}s): {c['text'][:700]}" for c in top)
    prompt = ("You pick the best short-form video clips from transcript excerpts. Rate each excerpt "
              "0-10 for how well it works as a standalone Short (strong opening, self-contained, "
              "interesting). Reply with ONLY a JSON array of objects with keys: id, rating, hook "
              "(max 80 chars, punchy), title (max 70 chars), description (max 200 chars).\n\n" + listing)
    payload = {"model": model, "max_tokens": 1500,
               "messages": [{"role": "user", "content": prompt}]}
    headers = {"content-type": "application/json", "x-api-key": api_key,
               "anthropic-version": "2023-06-01"}
    try:
        data = (post or default_post)("https://api.anthropic.com/v1/messages", headers, payload)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        match = re.search(r"\[.*\]", text, re.S)
        rows = json.loads(match.group(0)) if match else None
        if not isinstance(rows, list):
            return None
        valid = {c["id"] for c in top}
        out = {}
        for row in rows:
            if isinstance(row, dict) and row.get("id") in valid:
                rating = _clean_float(row.get("rating"), -1)
                if 0 <= rating <= 10:
                    out[row["id"]] = row
        return out or None
    except Exception:  # Network, auth, quota, malformed JSON: always fall back.
        return None


def apply_llm_rerank(candidates: list[dict], ranked: dict[str, dict] | None) -> list[dict]:
    if not ranked:
        return candidates
    for c in candidates:
        row = ranked.get(c["id"])
        if not row:
            continue
        c["score"] = round(.5 * c["score"] + .5 * _clean_float(row["rating"]) / 10.0, 3)
        for key, limit in (("hook", 80), ("title", 70), ("description", 200)):
            if isinstance(row.get(key), str) and row[key].strip():
                c[key] = row[key].strip()[:limit]
        c["reasons"] = list(c["reasons"]) + ["ranked with AI assistance"]
    return sorted(candidates, key=lambda c: -c["score"])


# ----------------------------------------------------------- video probing

def scene_changes(video: Path, threshold: float = .3, timeout: int = 3600) -> list[float]:
    """Timestamps of visual scene changes across the whole video (low-res pass)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-nostats", "-i", str(video), "-an",
           "-vf", f"scale=160:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL, **perf.windows_child_options(low_priority=True))
    except (subprocess.TimeoutExpired, OSError):
        return []
    return [float(m) for m in re.findall(r"pts_time:([0-9.]+)", proc.stderr or "")]


def video_size(video: Path) -> tuple[int, int]:
    proc = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(video)],
                          capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    match = re.search(r"(\d+)x(\d+)", proc.stdout or "")
    if proc.returncode or not match:
        raise RuntimeError("Cannot read video size")
    return int(match.group(1)), int(match.group(2))


def activity_centers(video: Path, start: float, length: float, fps: int = 1,
                     timeout: int = 600) -> list[float]:
    """Horizontal centre (0..1) of on-screen motion, one value per sampled frame."""
    w, h = 64, 36
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.3f}",
           "-t", f"{length:.3f}", "-i", str(video), "-an",
           "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          **perf.windows_child_options(low_priority=True))
    if proc.returncode:
        raise RuntimeError((proc.stderr or b"FFmpeg failed").decode("utf-8", "replace")[-300:])
    frames = [proc.stdout[i:i + w * h] for i in range(0, len(proc.stdout) - w * h + 1, w * h)]
    centers: list[float] = []
    last = .5
    for index in range(1, len(frames)):
        weights = [0] * w
        a, b = frames[index - 1], frames[index]
        for pos in range(w * h):
            diff = abs(a[pos] - b[pos])
            if diff > 12:
                weights[pos % w] += diff
        total = sum(weights)
        if total > 400:
            last = sum(x * v for x, v in enumerate(weights)) / total / (w - 1)
        centers.append(last)
    if not centers:
        centers = [last]
    return [centers[0]] + centers if len(frames) > 1 else centers


def smooth_centers(values: list[float], alpha: float = .35) -> list[float]:
    out: list[float] = []
    for value in values:
        out.append(value if not out else out[-1] + alpha * (value - out[-1]))
    return out


# ----------------------------------------------------------- 9:16 reframing

def crop_geometry(src_w: int, src_h: int, aspect_w: int = 9, aspect_h: int = 16) -> tuple[int, int]:
    """Largest even-sized crop with the target aspect that fits inside the source."""
    target = aspect_w / aspect_h
    if src_w / src_h >= target:
        ch = src_h
        cw = int(src_h * target)
    else:
        cw = src_w
        ch = int(src_w / target)
    cw, ch = min(src_w, cw - cw % 2), min(src_h, ch - ch % 2)
    return max(2, cw), max(2, ch)


def crop_x(center: float, src_w: int, crop_w: int) -> int:
    x = round(center * src_w - crop_w / 2)
    return int(max(0, min(src_w - crop_w, x)))


def crop_x_expression(xs: list[int], step: float = 1.0, max_points: int = 48) -> str:
    """FFmpeg crop x expression: linear glide between per-second positions."""
    if not xs:
        return "0"
    if len(xs) > max_points:
        stride = math.ceil(len(xs) / max_points)
        xs, step = xs[::stride], step * stride
    if len(xs) == 1 or len(set(xs)) == 1:
        return str(xs[0])
    expr = str(xs[-1])
    for i in range(len(xs) - 2, -1, -1):
        a, b = xs[i], xs[i + 1]
        t0 = round(i * step, 3)
        lerp = f"{a}+({b - a})*(t-{t0})/{step:g}"
        expr = f"if(lt(t,{round((i + 1) * step, 3)}),{lerp},{expr})"
    return expr


def lines_from_words(words: list[dict], max_words: int = 4, gap: float = .6) -> list[dict]:
    """Short caption lines (few words each) for vertical clips."""
    result, group = [], []

    def flush():
        if group:
            result.append({"id": uuid.uuid4().hex[:10], "start": round(_clean_float(group[0]["start"]), 3),
                           "end": round(_clean_float(group[-1]["end"]), 3),
                           "text": " ".join(str(w["text"]) for w in group), "words": list(group)})
            group.clear()

    for word in words:
        if not str(word.get("text", "")).strip():
            continue
        if group and (len(group) >= max_words or _clean_float(word["start"]) - _clean_float(group[-1]["end"]) > gap):
            flush()
        group.append(word)
        if re.search(r"[.!?]$", str(word["text"]).strip()):
            flush()
    flush()
    return result


def build_clip_args(source: Path, start: float, length: float, crop_w: int, crop_h: int,
                    x_expr: str, out_w: int, out_h: int, ass_name: str, fps: int,
                    encode: list[str], output: Path) -> list[str]:
    vf = (f"crop={crop_w}:{crop_h}:x='{x_expr}':y=0,scale={out_w}:{out_h},"
          f"setsar=1,format=yuv420p,ass={ass_name}")
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin",
            "-progress", "pipe:1", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
            "-i", str(source), "-vf", vf, "-r", str(fps), *encode,
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(output)]


def clip_words(words: list[dict], start: float, end: float) -> list[dict]:
    """Words inside [start, end], re-timed to begin at 0 s."""
    return [{**w, "start": round(_clean_float(w["start"]) - start, 3),
             "end": round(min(_clean_float(w["end"]), end) - start, 3)}
            for w in words if _clean_float(w.get("start")) >= start - .01
            and _clean_float(w.get("end")) <= end + .5 and str(w.get("text", "")).strip()]
