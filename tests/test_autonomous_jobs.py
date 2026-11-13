"""Autopilot, song Shorts and the long-video clipper, run for real through FFmpeg.

Only Whisper is replaced (injected word timings); every render, crop, caption,
cache and manifest step is the production code path.
"""
import json
import shutil
import subprocess
import time

import pytest

import server
import studio_clips as clips

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
PID_SONG, PID_VIDEO = "a" * 32, "b" * 32
FAST = {"resolution": "540p", "renderSpeed": "fast", "encoder": "cpu"}


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def song_words(seconds=30):
    texts = ["we are burning bright forever", "never gonna let this fire die"] * 4
    words, t = [], 1.0
    for text in texts:
        parts = text.split()
        for k, w in enumerate(parts):
            words.append({"text": w, "start": round(t + 3.0 * k / len(parts), 3),
                          "end": round(t + 3.0 * (k + 1) / len(parts) - .05, 3), "probability": .95})
        t += 3.4
    return words, seconds


def make_song(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()  # the job table is process-global; start each test clean
    words, duration = song_words()
    p = tmp_path / PID_SONG
    p.mkdir()
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency=330:duration={duration}", str(p / "song.wav"))
    server.save_project(p, {"id": PID_SONG, "title": "Test Song", "audio_file": "song.wav", "duration": duration,
                            "status": "review", "draft_lyrics": "", "original_words": words, "lines": [],
                            "settings": {}, "save_state": "draft"})
    return p


@needs_ffmpeg
def test_autopilot_builds_full_video_and_vertical_shorts(tmp_path, monkeypatch):
    p = make_song(tmp_path, monkeypatch)
    settings = server.sanitize_settings({"aspect": "landscape", **FAST})
    job = server.register_job(PID_SONG, "autopilot", settings)
    server.run_autopilot(PID_SONG, job, settings, 1, True)
    result = server.jobs[job]
    assert result["status"] == "done", result.get("error")
    assert clips.video_size(p / "lyric_video.mp4") == (960, 540)
    assert clips.video_size(p / "short_1.mp4") == (540, 960)
    manifest = json.loads((p / "shorts.json").read_text(encoding="utf-8"))
    assert manifest[0]["title"].startswith("Test Song | ") and "shorts" in manifest[0]["tags"]
    assert result["outputs"]["shorts"][0]["url"].endswith("/shorts/1")
    saved = server.read_project(PID_SONG)
    assert saved["auto_confirmed"] is True and saved["status"] == "editor"
    assert saved["save_state"] == "saved" and saved["lines"]  # survives "Don't Save"
    # An identical second run reuses the render instead of re-encoding.
    before = (p / "short_1.mp4").stat().st_mtime_ns
    again = server.register_job(PID_SONG, "shorts", server.short_settings(settings))
    segment = {"start": manifest[0]["start"], "end": manifest[0]["end"], "hook": manifest[0]["hook"]}
    server.render_shorts_batch(PID_SONG, again, [segment], server.short_settings(settings), saved["lines"])
    assert (p / "short_1.mp4").stat().st_mtime_ns == before


@needs_ffmpeg
def test_stale_shorts_are_removed_when_fewer_are_rendered(tmp_path, monkeypatch):
    p = make_song(tmp_path, monkeypatch)
    lines = server.build_lines(server.read_project(PID_SONG)["original_words"])
    shorts = server.short_settings(FAST)
    picks = clips.pick_short_segments(lines, [], 30.0, 2, min_len=8, max_len=14)
    assert len(picks) >= 2
    job = server.register_job(PID_SONG, "shorts", shorts)
    server.render_shorts_batch(PID_SONG, job, picks[:2], shorts, lines)
    assert (p / "short_2.mp4").is_file()
    server.jobs[job]["status"] = "done"  # the HTTP handler does this after the batch returns
    job2 = server.register_job(PID_SONG, "shorts", shorts)
    server.render_shorts_batch(PID_SONG, job2, picks[:1], shorts, lines)
    assert not (p / "short_2.mp4").exists()


def test_only_one_job_per_project_at_a_time(tmp_path, monkeypatch):
    make_song(tmp_path, monkeypatch)
    settings = server.sanitize_settings({})
    first = server.register_job(PID_SONG, "autopilot", settings)
    with pytest.raises(server.HTTPException) as caught:
        server.register_job(PID_SONG, "shorts", settings)
    assert caught.value.status_code == 409
    server.jobs[first]["status"] = "done"
    assert server.register_job(PID_SONG, "shorts", settings)


def test_short_and_clip_requests_are_validated(tmp_path, monkeypatch):
    make_song(tmp_path, monkeypatch)
    with pytest.raises(server.HTTPException) as caught:  # a 2 second "Short"
        server.render_shorts(PID_SONG, server.ShortsRenderRequest(segments=[{"start": 1, "end": 3}]))
    assert caught.value.status_code == 400
    with pytest.raises(server.HTTPException) as caught:  # songs have no clip renderer
        server.render_clips(PID_SONG, server.ClipsRenderRequest(clips=[{"start": 0, "end": 20}]))
    assert caught.value.status_code == 409


def test_autopilot_refuses_while_transcribing_or_without_lyrics(tmp_path, monkeypatch):
    p = make_song(tmp_path, monkeypatch)
    data = server.read_project(PID_SONG)
    data["status"] = "transcribing"
    server.save_project(p, data)
    with pytest.raises(server.HTTPException) as caught:
        server.start_autopilot(PID_SONG, server.AutopilotRequest())
    assert caught.value.status_code == 409
    data.update(status="review", original_words=[])
    server.save_project(p, data)
    with pytest.raises(server.HTTPException) as caught:
        server.start_autopilot(PID_SONG, server.AutopilotRequest())
    assert caught.value.status_code == 400


def make_clip_source(tmp_path, monkeypatch, words, seconds=80):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    p = tmp_path / PID_VIDEO
    p.mkdir()
    ffmpeg("-f", "lavfi", "-i", f"color=c=0x203040:s=1280x720:r=15:d={seconds}",
           "-f", "lavfi", "-i", f"color=c=white:s=90x90:r=15:d={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
           "-filter_complex", "[0:v][1:v]overlay=x='50+mod(t*40,1100)':y=300[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           str(p / "source.mp4"))
    server.save_project(p, {"id": PID_VIDEO, "kind": "clip_source", "title": "Walkthrough", "audio_file": "source.mp4",
                            "source_file": "source.mp4", "duration": float(seconds), "status": "transcribing",
                            "draft_lyrics": "", "original_words": [], "lines": [], "settings": {},
                            "save_state": "saved", "use_ai": False})

    def fake_transcribe(project_id):  # Whisper is the only thing replaced
        d = json.loads((server.DATA / project_id / "project.json").read_text(encoding="utf-8"))
        d.update(original_words=words, transcription_stage="complete" if words else "error", status="review")
        server.save_project(server.DATA / project_id, d)
    monkeypatch.setattr(server, "transcribe_project", fake_transcribe)
    return p


def talk_words():
    sentences = [("Why does nobody explain these 3 mixing tricks to you?", 0.0, 6.0),
                 ("Because most people copy presets and never learn why they work.", 6.5, 13.0),
                 ("Start with the low end because everything else sits on top of it.", 13.4, 20.0),
                 ("Then carve space for the vocal around two thousand hertz.", 20.3, 27.0),
                 ("That is the whole idea and it takes about five minutes.", 27.4, 33.0)]
    words = []
    for text, start, end in sentences:
        parts = text.split()
        for k, w in enumerate(parts):
            words.append({"text": w, "start": round(start + (end - start) * k / len(parts), 3),
                          "end": round(start + (end - start) * (k + 1) / len(parts) - .02, 3)})
    return words


@needs_ffmpeg
def test_clip_source_is_analyzed_then_rendered_center_and_follow(tmp_path, monkeypatch):
    p = make_clip_source(tmp_path, monkeypatch, talk_words())
    server.analyze_clip_source(PID_VIDEO)
    data = server.read_project(PID_VIDEO)
    assert data["status"] == "ready" and data["clip_envelope"] and data["clip_suggestions"]
    best = data["clip_suggestions"][0]
    assert best["title"] and best["reasons"] and clips.CLIP_MIN <= best["end"] - best["start"] <= clips.CLIP_MAX
    settings = server.short_settings(FAST)
    for reframe in ("center", "follow"):
        job = server.register_job(PID_VIDEO, "clips", settings)
        server.run_clips(PID_VIDEO, job, data["clip_suggestions"][:1], settings, reframe)
        assert server.jobs[job]["status"] == "done", server.jobs[job].get("error")
        assert clips.video_size(p / "clip_1.mp4") == (540, 960)
    entry = json.loads((p / "clips.json").read_text(encoding="utf-8"))[0]
    assert entry["file"] == "clip_1.mp4" and entry["tags"] and entry["url"].endswith("/clips/1")
    assert server.jobs[job]["outputs"]["clips"][0]["title"] == entry["title"]


@needs_ffmpeg
def test_clip_source_without_speech_fails_cleanly(tmp_path, monkeypatch):
    make_clip_source(tmp_path, monkeypatch, [], seconds=6)
    server.analyze_clip_source(PID_VIDEO)
    data = server.read_project(PID_VIDEO)
    assert data["status"] == "failed" and data["clip_error"]
    with pytest.raises(server.HTTPException) as caught:
        server.render_clips(PID_VIDEO, server.ClipsRenderRequest(clips=[{"start": 0, "end": 20}]))
    assert caught.value.status_code == 409


def test_clip_source_limits_come_from_environment(monkeypatch):
    monkeypatch.setenv("SKELLYMOTION_MAX_CLIP_SOURCE_MB", "10")
    monkeypatch.setenv("SKELLYMOTION_MAX_CLIP_SOURCE_MINUTES", "2")
    assert server.max_clip_source_bytes() == 10 * 1024 * 1024
    assert server.max_clip_source_seconds() == 120
    monkeypatch.setenv("SKELLYMOTION_MAX_CLIP_SOURCE_MB", "nonsense")
    assert server.max_clip_source_bytes() == 2048 * 1024 * 1024
