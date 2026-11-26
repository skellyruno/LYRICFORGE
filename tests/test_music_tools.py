"""Drop finding and the three song tools (studio_music.py), with real FFmpeg."""
import asyncio

import pytest
from PIL import Image

import server
import studio_clips as clips
import studio_music as music
from test_quick_tools import data, ffmpeg, make_audio, make_video, needs_ffmpeg, up  # noqa: F401
from test_quick_tools2 import rejected, run_tool


def build_track(path, quiet=25.0, loud=35.0):
    """A quiet build-up followed by a loud, bass-heavy section: the drop is at `quiet` seconds."""
    ffmpeg("-f", "lavfi", "-i", f"sine=f=90:d={quiet}:sample_rate=44100", "-f", "lavfi", "-i", f"sine=f=55:d={loud}:sample_rate=44100",
           "-f", "lavfi", "-i", f"sine=f=1200:d={loud}:sample_rate=44100",
           "-filter_complex", "[0]volume=0.04[a];[1]volume=0.7[b];[2]volume=0.15[c];[b][c]amix=inputs=2:normalize=0[loud];[a][loud]concat=n=2:v=0:a=1",
           str(path))
    return path


# ------------------------------------------------------------------------------------------------- pure functions
def test_the_rise_is_found_on_a_synthetic_curve():
    curve = [.2] * 160 + [.8] * 240          # 40 s quiet, 60 s loud at 4 frames per second
    assert abs(music.find_drop(curve, 5, 30) - 40) <= 1.5
    assert music.clip_window(100, 40, 5, 30) == (35.0, 30.0)
    assert music.clip_window(100, 98, 5, 30) == (70.0, 30.0), "the clip is pulled back so it stays inside the song"
    assert music.clip_window(20, 10, 5, 30) == (0.0, 20.0), "a short song gives a shorter clip"
    flat = [.5] * 400
    assert 5 <= music.find_drop(flat, 5, 30) <= 75, "nothing rises: still a usable answer"


def test_the_loudness_summary_is_parsed(monkeypatch):
    class Done:
        stderr = "junk\n  Summary:\n\n  Integrated loudness:\n    I:         -14.2 LUFS\n    Threshold: -24.3 LUFS\n\n  Loudness range:\n    LRA:         6.1 LU\n\n  True peak:\n    Peak:       -1.3 dBFS\n"
    monkeypatch.setattr(music.subprocess, "run", lambda *a, **k: Done())
    assert music.loudness("x.wav") == {"lufs": -14.2, "lra": 6.1, "peak": -1.3}
    monkeypatch.setattr(music.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no ffmpeg")))
    assert music.loudness("x.wav") == {}


@needs_ffmpeg
def test_analysis_of_a_real_track(data):
    track = build_track(data / "track.wav")
    found = music.analyze_track(track, 60, with_tempo=False)
    assert found["duration"] == pytest.approx(60, abs=.3)
    assert abs(found["drop"] - 25) <= 2, found["drop"]
    assert found["start"] == pytest.approx(found["drop"] - 5, abs=.01) and found["length"] == 30
    assert music.loudness(track).get("lufs") is not None


# ------------------------------------------------------------------------------------------------------- the tools
@needs_ffmpeg
def test_drop_clip_is_a_vertical_clip_that_starts_before_the_drop(data):
    track = build_track(data / "track.wav")
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=60", "-i", str(track), "-t", "60", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-shortest", str(data / "mv.mp4"))
    out, job, made = run_tool(data, "dropclip", {"video": [up(data / "mv.mp4")]}, length="30", pre="5", shape="9:16")
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(30, abs=.5) and info["has_audio"]
    assert info["width"] == 202 or info["width"] == 204 or abs(info["width"] / info["height"] - 9 / 16) < .02
    assert info["height"] == 360
    label = job["outputs"]["files"][0]["label"]
    assert label.startswith("30 s clip, drop at 0:2"), label
    square, _, _ = run_tool(data, "dropclip", {"video": [up(data / "mv.mp4")]}, length="15", shape="1:1")
    s = clips.probe_media(square)
    assert s["width"] == s["height"] and s["duration"] == pytest.approx(15, abs=.5)
    orig, _, _ = run_tool(data, "dropclip", {"video": [up(data / "mv.mp4")]}, shape="original")
    assert clips.probe_media(orig)["width"] == 640
    assert "no sound" in rejected("dropclip", {"video": [up(make_video(data / "mute.mp4", 12, audio=False))]})
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_best_part_of_a_song_is_audio_only_and_contains_the_loud_part(data):
    track = build_track(data / "track.wav")
    out, job, _ = run_tool(data, "dropaudio", {"audio": [up(track)]}, length="15", pre="3")
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(15, abs=.5) and not info["has_video"]
    from test_quick_tools2 import pcm, rms
    assert rms(pcm(out, 5, 3)) > rms(pcm(out, 0.4, 2)) * 4, "quiet build first, then the loud part"
    assert "drop at 0:2" in job["outputs"]["files"][0]["label"]


@needs_ffmpeg
def test_song_card_is_a_picture_with_the_graph(data):
    track = build_track(data / "track.wav")
    out, job, _ = run_tool(data, "songcard", {"audio": [up(track)]})
    img = Image.open(out).convert("RGB")
    assert img.size == (1600, 900) and job["outputs"]["files"][0]["kind"] == "image"
    brand = server.load_brand()
    accent = tuple(int(brand["accent"].lstrip("#")[k:k + 2], 16) for k in (0, 2, 4))
    near = lambda px: max(abs(a - b) for a, b in zip(px, accent)) < 40  # noqa: E731
    graph = [img.getpixel((x, y)) for x in range(80, 1520, 10) for y in range(560, 820, 6)]
    assert sum(near(px) for px in graph) > 60, "the energy bars are drawn in the accent color"


@needs_ffmpeg
def test_long_or_tiny_songs_are_refused_clearly(data, monkeypatch):
    with pytest.raises(ValueError, match="longer than 15 minutes"):
        music.check_length({"duration": 1000})
    with pytest.raises(ValueError, match="at least 8 seconds"):
        music.check_length({"duration": 3})
    assert "at least 8 seconds" in rejected("songcard", {"audio": [up(make_audio(data / "tiny.wav", 3))]})


def test_registry_includes_the_song_tools():
    for tool_id in ("dropclip", "dropaudio", "songcard"):
        q = server.QUICK_TOOLS[tool_id]
        assert tool_id in server.DEMO_KINDS and server.MAKE_LABELS[tool_id] == q.title and server.FILE_NAME.fullmatch(q.out)
        assert server.TOOL_FILTERS[tool_id] == list(q.filters)
    assert len(server.QUICK_TOOLS) == 43 and len({q.out for q in server.QUICK_TOOLS.values()}) == 43


def test_common_failures_get_plain_wording_and_other_errors_pass_through():
    assert "disk is full" in server.friendly_error("[Errno 28] No space left on device")
    assert "could not be read" in server.friendly_error("x.mp4: Invalid data found when processing input")
    assert "missing a feature" in server.friendly_error("No such filter: 'xfade'")
    assert server.friendly_error("Something unusual") == "Something unusual"


@needs_ffmpeg
def test_results_report_their_file_size(data):
    out, job, _ = run_tool(data, "palette", {"image": [up(data / "p.png")]}) if (data / "p.png").exists() else (None, None, None)
    if job is None:
        Image.new("RGB", (64, 64), (9, 9, 9)).save(data / "p.png")
        out, job, _ = run_tool(data, "palette", {"image": [up(data / "p.png")]})
    assert job["outputs"]["files"][0]["bytes"] == out.stat().st_size > 0
