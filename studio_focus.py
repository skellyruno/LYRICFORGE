"""Focus on UI events: find the moments a small part of the screen suddenly changes (a click landing, a menu opening),
zoom to that spot and mark it with an animated ring.

The app cannot see your mouse pointer. It sees where the picture changes, so this is a heuristic that works best on
clean screen recordings and can be fooled by busy animation (use the motion zoom or turn it off there).
"""
from __future__ import annotations

from pathlib import Path

import studio_clips as clips
import studio_edit as edit


def detect_ui_events(track: list[dict], *, min_level: float = .0003, max_level: float = .06, max_spread: float = .14,
                     quiet_level: float = .0002, quiet_samples: int = 2, min_gap: float = 1.2) -> list[dict]:
    """Onsets of small, compact changes after a quiet moment. Continuous motion (video, animation) is ignored."""
    events: list[dict] = []
    for i, p in enumerate(track):
        if not (min_level <= p["level"] <= max_level and p["spread"] <= max_spread):
            continue
        prior = track[max(0, i - quiet_samples):i]
        if len(prior) < quiet_samples or any(q["level"] > quiet_level for q in prior):
            continue  # not an onset: something was already moving
        if events and p["t"] - events[-1]["t"] < min_gap:
            continue
        events.append({"t": round(p["t"], 3), "cx": round(p["cx"], 4), "cy": round(p["cy"], 4)})
    return events


def plan_ui_zoom(events: list[dict], strength: str = "medium", hold: float = 1.8) -> list[tuple[float, float, float, float]]:
    """Zoom keyframes (t, zoom, cx, cy): glide in on each event, hold, glide out. Close events pan instead of zooming out."""
    z = edit.ZOOM_LEVELS.get(strength)
    if not z or not events:
        return []

    def clamp(v: float) -> float:
        return round(min(max(v, .5 / z), 1 - .5 / z), 4)

    keys: list[tuple[float, float, float, float]] = []
    for n, ev in enumerate(events):
        cx, cy = clamp(ev["cx"]), clamp(ev["cy"])
        t_in = max(0.0, ev["t"] - .15)
        nxt = events[n + 1] if n + 1 < len(events) else None
        hold_end = ev["t"] + hold
        if not keys or keys[-1][1] <= 1.001:
            keys += [(round(t_in, 3), 1.0, cx, cy), (round(t_in + .45, 3), z, cx, cy)]
        else:  # still zoomed from the previous event: pan across
            keys.append((round(max(keys[-1][0] + .05, t_in + .1), 3), z, cx, cy))
        if nxt is not None and nxt["t"] - hold_end < 1.0:
            keys.append((round(max(keys[-1][0] + .05, min(hold_end, nxt["t"] - .5)), 3), z, cx, cy))
            continue
        keys += [(round(max(keys[-1][0] + .05, hold_end), 3), z, cx, cy), (round(hold_end + .55, 3), 1.0, cx, cy)]
    mono = [keys[0]]
    for k in keys[1:]:
        mono.append((round(max(k[0], mono[-1][0] + .02), 3), *k[1:]))
    return mono


def eval_keys(keys: list[tuple[float, float, float, float]], t: float) -> tuple[float, float, float]:
    """(zoom, cx, cy) at time t, linearly between keyframes (the same rule the render graph uses)."""
    if not keys:
        return 1.0, .5, .5
    if t <= keys[0][0]:
        return keys[0][1:]
    for a, b in zip(keys, keys[1:]):
        if t <= b[0]:
            f = (t - a[0]) / max(b[0] - a[0], 1e-6)
            return tuple(a[k] + (b[k] - a[k]) * f for k in (1, 2, 3))
    return keys[-1][1:]


def _view_pos(ev: dict, keys: list, t: float) -> tuple[float, float]:
    zoom, zx, zy = eval_keys(keys, t)
    return ((ev["cx"] - (zx - .5 / zoom)) * zoom, (ev["cy"] - (zy - .5 / zoom)) * zoom)


def ring_marks(events: list[dict], keys: list, segments: list[tuple[float, float]], main_len: float) -> list[dict]:
    """Rings on the OUTPUT timeline. A ring starts where the event is in the frame at that moment and glides to
    where it ends up once the zoom settles, so it stays on the spot while the picture moves under it."""
    clamp = lambda v: round(min(max(v, .04), .96), 4)
    marks = []
    for ev in events:
        inside = any(a <= ev["t"] <= b for a, b in segments)
        t_out = edit.map_time(ev["t"], segments)
        if not inside or t_out > main_len - .8:
            continue
        # Start once the zoom is mostly in (the picture moves fast during the first moments, and a ring that lags
        # behind it looks wrong), then follow it the rest of the way.
        x1, y1 = _view_pos(ev, keys, ev["t"] + .2)
        x2, y2 = _view_pos(ev, keys, ev["t"] + .5)
        marks.append({"t": round(t_out + .2, 3), "x": clamp(x1), "y": clamp(y1), "x2": clamp(x2), "y2": clamp(y2)})
    return marks


def write_ring_ass(path: Path, marks: list[dict], width: int, height: int, color_hex: str, seconds: float = .75) -> None:
    """An expanding, fading ring at each mark (an ASS vector circle animated with \\t)."""
    header = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
              "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
              "MarginL, MarginR, MarginV, Encoding\nStyle: Ring,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00000000,0,0,0,0,"
              "100,100,0,0,1,0,0,5,10,10,10,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
              "Effect, Text\n")
    r = max(10, round(height * .035))
    k = round(r * .55)
    # Coordinates stay positive (0..2r): libass aligns a drawing by its box, and negative points shift it off-centre.
    circle = (f"m {r} 0 b {r + k} 0 {2 * r} {r - k} {2 * r} {r} b {2 * r} {r + k} {r + k} {2 * r} {r} {2 * r} "
              f"b {r - k} {2 * r} 0 {r + k} 0 {r} b 0 {r - k} {r - k} 0 {r} 0")
    bgr = f"&H00{color_hex[5:7]}{color_hex[3:5]}{color_hex[1:3]}".upper()
    ms = round(seconds * 1000)
    events = ""
    for m in marks:
        x, y = round(m["x"] * width), round(m["y"] * height)
        x2, y2 = round(m.get("x2", m["x"]) * width), round(m.get("y2", m["y"]) * height)
        place = f"\\move({x},{y},{x2},{y2},0,300)" if (x, y) != (x2, y2) else f"\\pos({x},{y})"
        events += (f"Dialogue: 3,{clips.asstime(m['t'])},{clips.asstime(m['t'] + seconds)},Ring,,0,0,0,,"
                   f"{{\\an5{place}\\1a&HFF&\\3c{bgr}\\bord{max(3, round(height * .007))}\\shad0"
                   f"\\fscx40\\fscy40\\t(0,{ms},\\fscx230\\fscy230\\3a&HFF&)\\p1}}{circle}{{\\p0}}\n")
    path.write_text(header + events, encoding="utf-8-sig")
