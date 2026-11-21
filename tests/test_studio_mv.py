"""The music-video editor: footage choice rules, and a real render cut on the beat."""
import shutil
import subprocess

import pytest

import studio_audio as sa
import studio_beat as beat
import studio_clips as clips
import studio_edit as edit
import studio_mv as mv
import studio_performance as perf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def src(name, duration, activity=None):
    return {"path": f"/x/{name}.mp4", "duration": duration, "activity": activity or []}


def cuts_of(n, length=2.0, strong_every=4):
    return [{"start": i * length, "end": (i + 1) * length, "beats": 4, "strong": i % strong_every == 0, "flash": i == 3} for i in range(n)]


def test_footage_is_spread_evenly_and_never_repeats_back_to_back():
    sources = [src("a", 60), src("b", 60), src("c", 60)]
    segments, passes = mv.pick_segments(cuts_of(24), sources)
    assert len(segments) == 24
    picks = [s["source"] for s in segments]
    assert all(a != b for a, b in zip(picks, picks[1:]))
    counts = [picks.count(i) for i in range(3)]
    assert max(counts) - min(counts) <= 1  # even use
    for s, c in zip(segments, cuts_of(24)):
        assert s["length"] == pytest.approx(c["end"] - c["start"], abs=.001)
    assert [s["flash"] for s in segments].count(True) == 1 and segments[0]["strong"]


def test_each_run_through_a_file_moves_forward_so_ffmpeg_never_has_to_go_back():
    segments, passes = mv.pick_segments(cuts_of(40, 2.0), [src("a", 30), src("b", 25)])
    by_pass = {}
    for s in segments:
        by_pass.setdefault(s["pass"], []).append(s["start"])
    for key, starts in by_pass.items():
        assert starts == sorted(starts), f"{key} goes backwards: {starts}"
    assert len(passes) > 2  # 40 cuts of 2 s need more footage than 55 s: files are re-opened for further passes
    for s in segments:
        dur = {0: 30, 1: 25}[s["source"]]
        assert s["start"] + s["length"] <= dur + 1e-6 or s["hold"] > 0


def test_lively_moments_are_preferred_and_short_footage_holds_its_last_frame():
    quiet_then_busy = [0.0] * 2 + [0.9] * 3 + [0.0] * 23  # the busy stretch is within the 3 s it looks ahead
    segments, _ = mv.pick_segments(cuts_of(1, 2.0), [src("a", 28, quiet_then_busy)])
    assert 2.0 <= segments[0]["start"] <= 3.0 and mv.motion_level(quiet_then_busy, segments[0]["start"], 2.0) > .8
    far = [0.0] * 8 + [0.9] * 3 + [0.0] * 17  # beyond its reach: it stays where the footage left off instead of jumping
    assert mv.pick_segments(cuts_of(1, 2.0), [src("a", 28, far)])[0][0]["start"] <= 3.0
    short, _ = mv.pick_segments(cuts_of(1, 4.0), [src("tiny", 1.5)])
    assert short[0]["start"] == 0.0 and short[0]["hold"] == pytest.approx(2.5)
    assert mv.pick_segments([], [src("a", 10)]) == ([], [])
    assert mv.motion_level([], 0, 2) == 0.0


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def pixels_at(video, t, folder):
    from PIL import Image
    edit.extract_frame(video, t, folder / f"f{t:.2f}.png")
    return Image.open(folder / f"f{t:.2f}.png").convert("RGB").getpixel((120, 70))


def dominant(px):
    return max(range(3), key=lambda i: px[i])  # 0 = red, 1 = green, 2 = blue


@needs_ffmpeg
def test_a_real_music_video_cuts_on_the_beat_of_the_song(tmp_path):
    for name, color in (("red", "red"), ("green", "0x00C000"), ("blue", "blue")):
        ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=480x270:r=15:d=20", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               str(tmp_path / f"{name}.mp4"))
    song = tmp_path / "song.wav"
    period = .5
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc='0.7*sin(2*PI*900*t)*exp(-40*mod(t,{period}))+0.05*sin(2*PI*110*t)':d=14:s=48000", str(song))
    analysis = beat.analyze(sa.decode_mono(song, rate=beat.RATE), 14.0)
    assert analysis["bpm"] == pytest.approx(120, abs=2)
    cuts = beat.plan_cuts(analysis, 14.0, "medium")
    assert len(cuts) >= 4
    sources = [{"path": tmp_path / f"{n}.mp4", "duration": 20.0, "activity": []} for n in ("red", "green", "blue")]
    segments, passes = mv.pick_segments(cuts, sources)
    out = tmp_path / "mv.mp4"
    args, graph, seconds = mv.build_mv_render(song, segments, passes, 480, 270, 15, out, perf.encode_args("libx264", "fast", 480, 270, 2),
                                              duration=14.0)
    (tmp_path / "mv_graph.txt").write_text(graph)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-800:]
    info = clips.probe_media(out)
    assert info["has_audio"] and info["duration"] == pytest.approx(14.0, abs=.6) and (info["width"], info["height"]) == (480, 270)
    boundaries = [c["start"] for c in cuts[1:6]]
    changed = 0
    for t in boundaries:
        before, after = dominant(pixels_at(out, t - .14, tmp_path)), dominant(pixels_at(out, t + .14, tmp_path))
        changed += before != after
    assert changed >= len(boundaries) - 1, "the picture should change exactly where the beat-grid cuts fall"
    mid = [dominant(pixels_at(out, (c["start"] + c["end"]) / 2, tmp_path)) for c in cuts[1:5]]
    assert len(set(mid)) >= 2  # different footage in different cuts
