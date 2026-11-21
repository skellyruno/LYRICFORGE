"""Focus on UI events: detection on synthetic screens, zoom planning, and the animated ring in a real render."""
import shutil
import subprocess

import pytest

import studio_clips as clips
import studio_edit as edit
import studio_focus as focus
import studio_performance as perf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def sample(t, level=0.0, cx=.5, cy=.5, spread=1.0):
    return {"t": t, "level": level, "cx": cx, "cy": cy, "spread": spread}


def track_with(events, n=60, fps=5):
    pts = [sample(i / fps) for i in range(1, n)]
    for t, cx, cy in events:
        i = round(t * fps) - 1
        pts[i] = sample(pts[i]["t"], .004, cx, cy, .05)
    return pts


def test_events_are_onsets_of_compact_changes_only():
    track = track_with([(2.0, .75, .3), (6.0, .2, .7)])
    found = focus.detect_ui_events(track)
    assert [(e["t"], e["cx"], e["cy"]) for e in found] == [(2.0, .75, .3), (6.0, .2, .7)]
    # a full-screen change (a scene cut) is not a click
    cut = [sample(i / 5) for i in range(1, 30)]
    cut[10] = sample(2.2, .5, .5, .5, .4)
    assert focus.detect_ui_events(cut) == []
    # continuous motion (a video playing) produces no onsets after its first moment
    busy = [sample(i / 5, .004, .6, .5, .05) for i in range(1, 40)]
    assert len(focus.detect_ui_events(busy)) == 0  # never quiet first, so never an onset
    close = track_with([(2.0, .5, .5), (2.6, .7, .7)])
    assert len(focus.detect_ui_events(close)) == 1  # inside min_gap: one event, not two


def test_zoom_plan_glides_in_holds_out_and_pans_between_close_events():
    one = focus.plan_ui_zoom([{"t": 3.0, "cx": .8, "cy": .3}], "medium")
    assert one[0][1] == 1.0 and max(k[1] for k in one) == pytest.approx(1.7) and one[-1][1] == 1.0
    times = [k[0] for k in one]
    assert times == sorted(times) and len(set(times)) == len(times)
    peak = max(one, key=lambda k: k[1])
    assert peak[2] == pytest.approx(min(.8, 1 - .5 / 1.7), abs=.01) and peak[3] == pytest.approx(max(.3, .5 / 1.7), abs=.01)
    two = focus.plan_ui_zoom([{"t": 3.0, "cx": .8, "cy": .3}, {"t": 5.0, "cx": .2, "cy": .7}], "medium")
    zoom_levels = [k[1] for k in two]
    assert min(zoom_levels[1:-2]) > 1.6  # stayed zoomed and panned instead of zooming out between them
    far = focus.plan_ui_zoom([{"t": 3.0, "cx": .8, "cy": .3}, {"t": 12.0, "cx": .2, "cy": .7}], "medium")
    assert any(k[1] == 1.0 and 5 < k[0] < 11 for k in far)  # far apart: back to the wide shot in between
    assert focus.plan_ui_zoom([], "medium") == [] and focus.plan_ui_zoom([{"t": 1, "cx": .5, "cy": .5}], "off") == []


def test_keyframe_evaluation_and_ring_positions():
    keys = [(0.0, 1.0, .5, .5), (1.0, 2.0, .75, .25), (3.0, 2.0, .75, .25)]
    assert focus.eval_keys(keys, 0.5) == pytest.approx((1.5, .625, .375)) and focus.eval_keys(keys, 9) == (2.0, .75, .25)
    assert focus.eval_keys([], 1) == (1.0, .5, .5)
    events = [{"t": 0.5, "cx": .75, "cy": .25}, {"t": 10.0, "cx": .5, "cy": .5}]  # the first lands mid-glide
    marks = focus.ring_marks(events, keys, [(0.0, 8.0)], 30.0)
    assert len(marks) == 1  # the second event falls in a removed part of the video
    assert marks[0]["x2"] == pytest.approx(.5, abs=.01) and marks[0]["y2"] == pytest.approx(.5, abs=.01)  # settles centered on it
    assert (marks[0]["x"], marks[0]["y"]) != (marks[0]["x2"], marks[0]["y2"])  # and travels there with the picture
    shifted = focus.ring_marks([{"t": 6.0, "cx": .5, "cy": .5}], [], [(4.0, 9.0)], 30.0)
    assert shifted[0]["t"] == pytest.approx(2.2)  # re-timed to the cut video
    assert focus.ring_marks([{"t": 29.5, "cx": .5, "cy": .5}], [], [(0, 30)], 30.0) == []


def test_ring_ass_is_an_animated_vector_circle(tmp_path):
    path = tmp_path / "ring.ass"
    focus.write_ring_ass(path, [{"t": 2.0, "x": .5, "y": .25}], 1280, 720, "#00FF88")
    text = path.read_text(encoding="utf-8-sig")
    assert "Dialogue: 3,0:00:02.00,0:00:02.75,Ring" in text and "\\pos(640,180)" in text  # no travel: a fixed position
    focus.write_ring_ass(path, [{"t": 2.0, "x": .5, "y": .25, "x2": .6, "y2": .5}], 1280, 720, "#00FF88")
    assert "\\move(640,180,768,360,0,300)" in path.read_text(encoding="utf-8-sig")
    focus.write_ring_ass(path, [{"t": 2.0, "x": .5, "y": .25}], 1280, 720, "#00FF88")
    assert "&H0088FF00" in text and "\\t(0,750," in text and "m 25 0 b" in text


def flashes(path):
    """Black 640x360 screen; a small white square appears briefly at (480,100) around 3 s and (150,260) around 7 s."""
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=15:d=10",
                    "-f", "lavfi", "-i", "color=c=white:s=40x40:r=15:d=10", "-f", "lavfi", "-i", "color=c=white:s=40x40:r=15:d=10",
                    "-filter_complex", "[0:v][1:v]overlay=x=460:y=80:enable='between(t,3,3.6)'[a];"
                    "[a][2:v]overlay=x=130:y=240:enable='between(t,7,7.6)'[v]", "-map", "[v]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


@needs_ffmpeg
def test_events_found_in_a_real_recording_then_zoomed_and_ringed(tmp_path):
    from PIL import Image
    video = tmp_path / "screen.mp4"
    flashes(video)
    track = edit.activity_track(video, 0, 10, fps=5)
    found = focus.detect_ui_events(track)
    assert len(found) == 2, found
    (a, b) = found
    assert a["t"] == pytest.approx(3.0, abs=.45) and (a["cx"], a["cy"]) == pytest.approx((480 / 640, 100 / 360), abs=.08)
    assert b["t"] == pytest.approx(7.0, abs=.45) and (b["cx"], b["cy"]) == pytest.approx((150 / 640, 260 / 360), abs=.08)
    keys = focus.plan_ui_zoom(found, "medium")
    marks = focus.ring_marks(found, keys, [(0.0, 10.0)], 10.0)
    focus.write_ring_ass(tmp_path / "ring.ass", marks, 640, 360, "#00FF00")
    out = tmp_path / "o.mp4"
    args, graph, _ = edit.build_render(video, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2), duration=10.0,
                                       zoom=keys, ass_name="ring.ass", has_audio=False, script_name="g.txt")
    (tmp_path / "g.txt").write_text(graph)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
    png = tmp_path / "f.png"
    edit.extract_frame(out, marks[0]["t"] + .12, png)
    image = Image.open(png).convert("RGB")
    px = [(x, y, image.getpixel((x, y))) for y in range(360) for x in range(640)]
    greens = [(x, y) for x, y, p in px if p[1] > 150 and p[0] < 110 and p[2] < 110]
    whites = [(x, y) for x, y, p in px if min(p) > 235]
    assert len(greens) > 100, "the ring should be visible"
    assert whites, "the flash should still be on screen"
    gx, gy = sum(g[0] for g in greens) / len(greens), sum(g[1] for g in greens) / len(greens)
    wx, wy = sum(w[0] for w in whites) / len(whites), sum(w[1] for w in whites) / len(whites)
    assert abs(gx - wx) < 18 and abs(gy - wy) < 18, f"ring ({gx:.0f},{gy:.0f}) is not on the flash ({wx:.0f},{wy:.0f})"
