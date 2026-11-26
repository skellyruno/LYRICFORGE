"""Auto music-video editor: cut your footage to the beat of a song.

Pure Python plus FFmpeg. studio_beat finds the cuts; this module chooses which footage goes in each one and builds
the render. Footage is used in order (a clip's later cuts always come from later in that clip), which keeps FFmpeg
reading each file once from start to finish instead of buffering.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import studio_edit as edit

MAX_PASSES = 6  # times one file may be re-opened for a second run through its footage


def motion_level(activity: list[float], start: float, length: float) -> float:
    if not activity:
        return 0.0
    a, b = max(0, int(start)), min(len(activity), max(int(start) + 1, int(math.ceil(start + length))))
    chunk = activity[a:b]
    return sum(chunk) / len(chunk) if chunk else 0.0


def pick_segments(cuts: list[dict], sources: list[dict], seed: int = 7) -> tuple[list[dict], list[dict]]:
    """Footage for every cut. `sources` are {"path", "duration", "activity": per-second motion or []}.

    Returns (segments, passes). A pass is one run through a file; passes are what become FFmpeg inputs. Never uses
    the same file for two cuts in a row (when there are two or more), spreads use evenly, and prefers livelier
    moments within a few seconds of where it left off.
    """
    rng = random.Random(seed)
    cursor = [0.0] * len(sources)
    pass_no = [0] * len(sources)
    uses = [0] * len(sources)
    passes: dict[tuple[int, int], dict] = {}
    segments: list[dict] = []
    last = -1
    for cut in cuts:
        length = max(.12, cut["end"] - cut["start"])
        order = sorted(range(len(sources)), key=lambda i: (uses[i] + rng.random() * .5))
        choices = [i for i in order if i != last] or order
        pick = choices[0]
        src = sources[pick]
        dur = float(src["duration"])
        room = dur - length - .05
        if room < 0:  # footage shorter than this cut: play it all and hold the last frame
            start, hold = 0.0, length - dur
            pass_no[pick] += 1
        else:
            hold = 0.0
            if cursor[pick] > room:  # ran out of footage: start another pass from near the beginning
                if pass_no[pick] + 1 >= MAX_PASSES:
                    cursor[pick] = 0.0
                    pass_no[pick] = MAX_PASSES - 1
                else:
                    pass_no[pick] += 1
                    cursor[pick] = rng.uniform(0, min(1.0, room))
            best, best_level = cursor[pick], -1.0
            s = cursor[pick]
            while s <= min(room, cursor[pick] + 3.0):
                level = motion_level(src.get("activity") or [], s, length)
                if level > best_level + 1e-9:
                    best, best_level = s, level
                s += 1.0
            start = min(best, room)
            cursor[pick] = start + length + .3
        key = (pick, pass_no[pick])
        passes.setdefault(key, {"source": pick, "path": src["path"], "first": start})
        passes[key]["first"] = min(passes[key]["first"], start)
        segments.append({"pass": key, "source": pick, "start": round(start, 3), "length": round(length, 3), "hold": round(hold, 3),
                         "flash": bool(cut.get("flash")), "strong": bool(cut.get("strong"))})
        uses[pick] += 1
        last = pick
    return segments, [{"key": k, **v} for k, v in sorted(passes.items())]


def build_mv_render(song: Path, segments: list[dict], passes: list[dict], out_w: int, out_h: int, fps: int, output: Path,
                    encode: list[str], *, duration: float, ass_name: str | None = None, seed: int = 7,
                    script_name: str = "mv_graph.txt") -> tuple[list[str], str, float]:
    """One FFmpeg pass: every cut trimmed from its footage, punched in on strong beats, white-flashed at the drops."""
    rng = random.Random(seed + 1)
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin", "-progress", "pipe:1", "-y", "-i", str(song)]
    parts: list[str] = []
    index_of: dict[tuple, int] = {}
    per_pass = {p["key"]: [i for i, s in enumerate(segments) if s["pass"] == p["key"]] for p in passes}
    for n, p in enumerate(passes, start=1):
        ss = max(0.0, p["first"] - .3)
        args += ["-ss", f"{ss:.3f}", "-i", str(p["path"])]
        index_of[p["key"]] = n
        users = per_pass[p["key"]]
        outs = "".join(f"[r{n}_{j}]" for j in range(len(users)))
        base = (f"[{n}:v]fps={fps},scale={out_w}:{out_h}:force_original_aspect_ratio=increase:flags=bicubic,crop={out_w}:{out_h},"
                f"setsar=1,format=yuv420p")
        parts.append(base + (f",split={len(users)}{outs}" if len(users) > 1 else f"[r{n}_0]"))
    seen: dict[tuple, int] = {}
    labels = []
    for k, seg in enumerate(segments):
        n = index_of[seg["pass"]]
        j = seen.get(seg["pass"], 0)
        seen[seg["pass"]] = j + 1
        ss = max(0.0, next(p for p in passes if p["key"] == seg["pass"])["first"] - .3)
        a = seg["start"] - ss
        chain = [f"trim=start={a:.3f}:end={a + seg['length'] - seg['hold']:.3f}", "setpts=PTS-STARTPTS"]
        if seg["hold"] > .02:
            chain.append(f"tpad=stop_mode=clone:stop_duration={seg['hold']:.3f}")
        zoom = 1.14 if seg["strong"] else (1.06 if rng.random() < .35 else 1.0)
        if zoom > 1.0:
            fx, fy = rng.random(), rng.random()
            chain.append(f"scale=iw*{zoom}:ih*{zoom},crop={out_w}:{out_h}:(iw-{out_w})*{fx:.2f}:(ih-{out_h})*{fy:.2f}")
        chain.append("setsar=1")  # zooming nudges the pixel aspect ratio and concat refuses mismatches
        if seg["flash"]:
            chain.append("fade=t=in:st=0:d=0.09:color=white")
        parts.append(f"[r{n}_{j}]" + ",".join(chain) + f"[v{k}]")
        labels.append(f"[v{k}]")
    tail = ",ass=" + ass_name if ass_name else ""
    parts.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=0[vc]")
    parts.append(f"[vc]format=yuv420p{tail}[vout]")
    args += [*edit.graph_file_args(script_name), "-map", "[vout]", "-map", "0:a", "-t", f"{duration:.3f}", "-r", str(fps), *encode,
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    return args, ";".join(parts), duration
