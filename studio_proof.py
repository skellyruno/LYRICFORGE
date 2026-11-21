"""Transcript proofreading: surface the words Whisper was unsure about, and apply corrections safely.

Corrections keep the original timing (a split word shares its slot), so cuts, captions and clip suggestions
stay in sync with the audio.
"""
from __future__ import annotations

import re
from typing import Any

import studio_clips as clips

MAX_EDITS, MAX_REPLACEMENTS, MAX_WORD = 500, 50, 80
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean_text(value: Any, limit: int = MAX_WORD) -> str:
    return re.sub(r"\s+", " ", _CONTROL.sub(" ", str(value or ""))).strip()[:limit]


def uncertain_words(words: list[dict], threshold: float = .6, limit: int = 60, context: int = 4) -> list[dict]:
    """The lowest-confidence words with surrounding context, in transcript order."""
    scored = []
    for i, w in enumerate(words):
        prob = w.get("probability")
        text = str(w.get("text", ""))
        if isinstance(prob, (int, float)) and prob < threshold and re.search(r"[A-Za-z0-9]", text) and not w.get("edited"):
            scored.append((float(prob), i))
    rows = []
    for prob, i in sorted(scored)[:limit]:
        rows.append({"i": i, "text": str(words[i]["text"]).strip(), "prob": round(prob, 2),
                     "start": round(clips._clean_float(words[i].get("start")), 2),
                     "before": " ".join(str(w["text"]).strip() for w in words[max(0, i - context):i]),
                     "after": " ".join(str(w["text"]).strip() for w in words[i + 1:i + 1 + context])})
    return sorted(rows, key=lambda r: r["i"])


def _tokens(text: str) -> list[str]:
    return [t for t in clean_text(text).split(" ") if t]


def _spread(start: float, end: float, tokens: list[str], base: dict) -> list[dict]:
    """New words sharing the timing slot [start, end] in proportion to their length."""
    total = sum(len(t) for t in tokens) or 1
    out, cursor = [], start
    for k, token in enumerate(tokens):
        span = (end - start) * len(token) / total
        out.append({**base, "text": token, "start": round(cursor, 3),
                    "end": round(end if k == len(tokens) - 1 else cursor + span, 3), "probability": 1.0, "edited": True})
        cursor += span
    return out


def apply_edits(words: list[dict], edits: list[dict] | None = None,
                replacements: list[dict] | None = None) -> tuple[list[dict], int]:
    """Return (corrected words, number of words changed). Never mutates the input.

    edits: [{"i": index, "text": new text}]. Empty text deletes the word; several words split its time slot.
    replacements: [{"find": "scaly tune", "with": "SkellyTune", "case": False}] across the whole transcript;
    `find` may be several words. Punctuation after the last matched word is kept.
    """
    result = [dict(w) for w in words]
    changed = 0
    usable = []
    for e in (edits or [])[:MAX_EDITS]:
        if isinstance(e, dict) and isinstance(e.get("i"), int) and 0 <= e["i"] < len(result):
            usable.append((e["i"], clean_text(e.get("text"))))
    seen = set()
    for i, text in sorted(usable, reverse=True):  # later indexes first so earlier ones do not shift
        if i in seen:
            continue
        seen.add(i)
        w = result[i]
        if text == str(w.get("text", "")).strip():
            continue
        s, e_ = clips._clean_float(w.get("start")), clips._clean_float(w.get("end"))
        result[i:i + 1] = _spread(s, e_, _tokens(text), {k: v for k, v in w.items() if k not in ("text", "start", "end")})
        changed += 1
    for rule in (replacements or [])[:MAX_REPLACEMENTS]:
        if not isinstance(rule, dict):
            continue
        find, new = _tokens(rule.get("find")), _tokens(rule.get("with"))
        if not find:
            continue
        key = (lambda t: t) if rule.get("case") else (lambda t: t.lower())
        norm = [key(re.sub(r"^[^\w]+|[^\w]+$", "", t)) for t in find]
        out: list[dict] = []
        i = 0
        while i < len(result):
            window = result[i:i + len(find)]
            same = len(window) == len(find) and all(
                key(re.sub(r"^[^\w]+|[^\w]+$", "", str(w.get("text", "")))) == n for w, n in zip(window, norm))
            if not same:
                out.append(result[i])
                i += 1
                continue
            tail = re.search(r"[.,!?;:]+$", str(window[-1].get("text", "")))
            tokens = list(new)
            if tokens and tail:
                tokens[-1] += tail.group(0)
            if tokens:
                base = {k: v for k, v in window[0].items() if k not in ("text", "start", "end")}
                out += _spread(clips._clean_float(window[0].get("start")), clips._clean_float(window[-1].get("end")), tokens, base)
            changed += 1
            i += len(find)
        result = out
    return result, changed
