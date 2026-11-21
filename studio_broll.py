"""B-roll from your own library: keywords from file names, and where in the video each clip goes.

Only your own footage is ever used, so there is nothing to license. A clip is cut in (picture only; your voice keeps
playing) when you say one of its keywords.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import studio_clips as clips

GENERIC = frozenset("clip clips broll roll video videos footage final copy new old mov mp4 mkv webm screen recording "
                    "capture untitled export render shot take part scene".split())
MAX_KEYWORDS, MAX_LIBRARY = 12, 40


def stem(word: str) -> str:
    """Tiny, predictable singularizer so "knobs" matches "knob" and "reverbs" matches "reverb"."""
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def keywords_from_name(filename: str) -> list[str]:
    """"knob-close-up_v2.mp4" gives ["knob", "close"]; camelCase and numbers are handled; generic words are dropped."""
    stem_part = Path(filename).stem
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem_part)
    out: list[str] = []
    for token in re.split(r"[^A-Za-z0-9]+", spaced):
        s = stem(token)
        if len(s) >= 3 and not s.isdigit() and s not in clips.STOPWORDS and s not in GENERIC and s not in ("up", "out"):
            if s not in out:
                out.append(s)
    return out[:MAX_KEYWORDS]


def sanitize_keywords(text: Any) -> list[str]:
    """Comma-separated keywords typed by the person, cleaned and stemmed."""
    raw = text if isinstance(text, list) else re.split(r"[,;\s]+", str(text or ""))
    out: list[str] = []
    for item in raw:
        s = stem(str(item).strip()[:24])
        if len(s) >= 2 and s not in out:
            out.append(s)
    return out[:MAX_KEYWORDS]


def slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")[:40]
    return base or "clip"


def plan_broll(words: list[dict], library: list[dict], main_len: float, *, min_gap: float = 18.0,
               max_len: float = 3.5, max_share: float = .12, max_uses: int = 2) -> list[dict]:
    """Where to cut B-roll in, on the output timeline.

    `words` are the spoken words (output timeline); `library` items are {"name", "path", "duration", "keywords"}.
    Spaced out (one per `min_gap` seconds at most), never more than `max_share` of the video once there is one clip in, each clip used at most
    `max_uses` times, and never in the first 3 seconds or last 2.
    """
    index: dict[str, list[dict]] = {}
    for item in library:
        for kw in item.get("keywords", []):
            index.setdefault(stem(kw), []).append(item)
    if not index:
        return []
    plan: list[dict] = []
    used: dict[str, int] = {}
    last_end, covered = -1e9, 0.0
    cap = max(1, min(12, int(main_len // 25)))
    for w in sorted(words, key=lambda x: clips._clean_float(x.get("start"))):
        if len(plan) >= cap:
            break
        candidates = index.get(stem(str(w.get("text", ""))))
        if not candidates:
            continue
        start = max(0.0, clips._clean_float(w.get("start")) - .15)
        if start < 3.0 or start > main_len - 2.0 or start - last_end < min_gap:
            continue
        item = min((c for c in candidates if used.get(c["name"], 0) < max_uses),
                   key=lambda c: used.get(c["name"], 0), default=None)
        if item is None:
            continue
        length = min(max_len, float(item.get("duration") or max_len), main_len - start - .5)
        if length < 1.2 or (plan and covered + length > max_share * main_len):  # the first clip is always allowed
            continue
        plan.append({"start": round(start, 2), "length": round(length, 2), "path": item["path"], "name": item["name"],
                     "keyword": stem(str(w["text"]))})
        used[item["name"]] = used.get(item["name"], 0) + 1
        last_end, covered = start + length, covered + length
    return plan
