"""Per-lyric animation, motion persistence, render choices and child process checks."""
from pathlib import Path

import server


def test_legacy_lyrics_use_project_wide_animation(tmp_path):
    lines = server.validate_lines([
        {"id": "legacy", "text": "Old lyric here", "start": 0, "end": 2, "words": []}
    ], 4)
    assert "animation" not in lines[0]
    assert "x" not in lines[0]
    settings = server.sanitize_settings({"animation": "fade", "position": 60})
    path = tmp_path / "legacy.ass"
    server.create_ass(lines, settings, 720, 1280, path)
    dialog = next(line for line in path.read_text(encoding="utf-8-sig").splitlines()
                  if line.startswith("Dialogue:"))
    assert r"\fad(" in dialog
    assert r"\pos(360,768)" in dialog


def test_per_line_fx_and_positions_export_to_ass(tmp_path):
    rows = [
        {"id": "first", "text": "I float up", "start": .5, "end": 2.0, "words": [],
         "animation": "slide", "x": 25, "y": 32, "effectMs": 470},
        {"id": "second", "text": "Then I bounce", "start": 2.0, "end": 4.0,
         "words": [], "animation": "bounce", "x": 73, "y": 68, "effectMs": 300},
    ]
    lines = server.validate_lines(rows, 5)
    assert len(lines) == 2
    assert lines[0]["x"] == 25
    assert lines[0]["effectMs"] == 470
    output = tmp_path / "captions.ass"
    server.create_ass(lines, server.sanitize_settings({}), 720, 1280, output)
    events = [line for line in output.read_text(encoding="utf-8-sig").splitlines()
              if line.startswith("Dialogue:")]
    assert len(events) == 2
    assert r"\move(180," in events[0] and ",470)" in events[0]
    assert r"\pos(" not in events[0]  # ASS does not allow pos + move together
    assert r"\pos(526,870)" in events[1]
    assert r"\fscx65" in events[1]


def test_bad_clip_overrides_are_sanitized():
    valid = server.validate_lines([{
        "text": "One word", "start": 0, "end": 2,
        "x": -999, "y": 200, "effectMs": 9999,
        "animation": "untrusted",
    }], 4)[0]
    assert valid["x"] == 8
    assert valid["y"] == 92
    assert valid["effectMs"] == 650
    assert "animation" not in valid


def test_quality_presets_and_recognition_dont_change_model():
    assert server.sanitize_settings({})["resolution"] == "720p"
    assert server.sanitize_settings({})["renderSpeed"] == "balanced"
    assert server.sanitize_settings({"resolution": "540p", "renderSpeed": "fast"})["resolution"] == "540p"
    assert server.sanitize_settings({"renderSpeed": "quality"})["renderSpeed"] == "quality"
    assert server.recognition_options("fast", "en") == {
        "recognition_mode": "fast", "language_hint": "en"
    }
    assert server.recognition_options("invalid", "invalid") == {
        "recognition_mode": "balanced", "language_hint": "auto"
    }
    assert server.RECOGNITION_MODES == {"fast": 1, "balanced": 3, "accurate": 5}


def test_parse_real_ffmpeg_progress():
    assert server.ffmpeg_seconds("00:00:12.500000") == 12.5
    assert server.ffmpeg_seconds("00:01:05.250000") == 65.25
    assert server.ffmpeg_seconds("bad progress") == 0


def test_ffmpeg_progress_job_updates(tmp_path, monkeypatch):
    class FakeProcess:
        stdout = iter(["out_time=00:00:02.000\n", "progress=continue\n",
                       "out_time=00:00:04.000\n", "progress=end\n"])
        def wait(self): return 0
        def poll(self): return 0
        def kill(self): return None
    # Expose close() on FakeProcess.stdout as a real file-like object.
    import io
    def start(*args, **kwargs):
        process = FakeProcess()
        process.stdout = io.StringIO("out_time=00:00:02.000\nprogress=continue\n"
                                     "out_time=00:00:04.000\nprogress=end\n")
        return process
    monkeypatch.setattr(server.subprocess, "Popen", start)
    job = "smoke-progress"
    server.jobs[job] = {"status": "rendering", "progress": 0}
    try:
        server.render_with_progress(["ffmpeg"], tmp_path, job, 4)
        assert server.jobs[job]["stage"] == "encoding"
        assert server.jobs[job]["progress"] == 99
    finally:
        server.jobs.pop(job, None)
