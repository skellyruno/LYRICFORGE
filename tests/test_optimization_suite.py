"""Deterministic SkellyMotion v0.7+0.8 checks. No GPU or external AI download."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
import studio_performance as perf


def project(tmp_path, identity="a" * 32):
    folder = tmp_path / identity
    folder.mkdir()
    (folder / "song.wav").write_bytes(b"audio" * 10)
    (folder / "project.json").write_text(json.dumps({
        "id": identity, "title": "My Song", "duration": 30.0,
        "audio_file": "song.wav", "status": "editor",
        "lines": [], "settings": {},
    }))
    return folder


def example_lines():
    return [{"id": "1", "text": "I am still here", "start": 0.5, "end": 4,
             "words": [], "animation": "pop"}]


def test_profiles_gpu_choice_and_settings():
    assert perf.profile_config("eco", 8)["threads"] <= perf.profile_config("balanced", 8)["threads"]
    assert perf.profile_config("turbo", 8)["threads"] >= perf.profile_config("balanced", 8)["threads"]
    assert perf.profile_config("eco", 8)["low_priority"] is True
    assert perf.choose_encoder("cpu", ("h264_nvenc",)) == "libx264"
    assert perf.choose_encoder("auto", ()) == "libx264"
    assert perf.choose_encoder("auto", ("h264_qsv",)) == "h264_qsv"
    software = perf.encode_args("libx264", "quality", 1280, 720, 4)
    assert software[software.index("-c:v") + 1] == "libx264"
    assert "-crf" in software
    hardware = perf.encode_args("h264_nvenc", "fast", 1280, 720, 4)
    assert "-b:v" in hardware and "-crf" not in hardware
    config = server.sanitize_settings({
        "performanceMode": "eco", "fps": "24", "encoder": "auto",
    })
    assert config["fps"] == 24 and config["performanceMode"] == "eco"
    assert server.sanitize_settings({"fps": "garbage"})["fps"] == 30
    assert server.sanitize_settings({"encoder": "bogus"})["encoder"] == "auto"


def test_real_hardware_probe_uses_encode_not_just_listing(monkeypatch):
    perf.available_gpu_encoders.cache_clear()
    monkeypatch.setattr(perf.shutil, "which", lambda name: "/tmp/fake-ffmpeg")
    seen = []
    def fake_run(command, **kwargs):
        seen.append(command)
        # Simulate NVIDIA works but the other drivers are missing.
        return SimpleNamespace(returncode=0 if "h264_nvenc" in command else 1)
    monkeypatch.setattr(perf.subprocess, "run", fake_run)
    result = perf.available_gpu_encoders()
    assert result == ("h264_nvenc",)
    assert len(seen) == 3 and all("-frames:v" in command for command in seen)
    perf.available_gpu_encoders.cache_clear()


def test_fingerprint_changes_for_source_and_settings(tmp_path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"first")
    lines = example_lines()
    settings = server.sanitize_settings({})
    key = perf.render_fingerprint(lines, settings, audio, None)
    assert key == perf.render_fingerprint(lines, settings, audio, None)
    assert key != perf.render_fingerprint(lines, settings, audio, None, preview=True)
    changed = dict(settings, fps=24)
    assert key != perf.render_fingerprint(lines, changed, audio, None)
    audio.write_bytes(b"updated source audio")
    assert key != perf.render_fingerprint(lines, settings, audio, None)


def test_cached_render_and_15_second_preview(tmp_path, monkeypatch):
    folder = project(tmp_path)
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server.perf, "available_gpu_encoders", lambda: ())
    monkeypatch.setattr(server, "create_gradient", lambda style, path: path.write_bytes(b"png"))
    calls = []
    def fake_render(args, working_dir, job_id, duration):
        calls.append((list(args), duration))
        Path(args[-1]).write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(server, "render_with_progress", fake_render)
    settings = server.sanitize_settings({})
    lines = server.validate_lines(example_lines(), 30)
    try:
        server.jobs["full"] = {"status": "rendering", "performance_mode": "balanced"}
        server.render_project(folder.name, "full", settings, lines)
        assert server.jobs["full"]["status"] == "done"
        assert server.jobs["full"]["cached"] is False
        assert (folder / "lyric_video.mp4").exists()
        server.jobs["repeat"] = {"status": "rendering", "performance_mode": "balanced"}
        server.render_project(folder.name, "repeat", settings, lines)
        assert server.jobs["repeat"]["cached"] is True
        assert len(calls) == 1
        server.jobs["preview"] = {"status": "rendering", "performance_mode": "balanced"}
        server.render_project(folder.name, "preview", settings, lines, preview=True)
        assert server.jobs["preview"]["status"] == "done"
        assert (folder / "lyric_preview.mp4").exists()
        assert len(calls) == 2 and calls[1][1] == 15.0
        args = calls[1][0]
        assert args[args.index("-t") + 1] == "15.000"
    finally:
        for name in ["full", "repeat", "preview"]:
            server.jobs.pop(name, None)


def test_hardware_failure_automatically_falls_back_to_cpu(tmp_path, monkeypatch):
    folder = project(tmp_path, "b" * 32)
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server.perf, "available_gpu_encoders", lambda: ("h264_nvenc",))
    monkeypatch.setattr(server, "create_gradient", lambda style, path: path.write_bytes(b"png"))
    encoders = []
    def fake_render(args, working_dir, job_id, duration):
        encoder = args[args.index("-c:v") + 1]
        encoders.append(encoder)
        if encoder == "h264_nvenc":
            raise RuntimeError("driver not usable")
        Path(args[-1]).write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(server, "render_with_progress", fake_render)
    server.jobs["gpu"] = {"status": "rendering", "performance_mode": "eco"}
    try:
        server.render_project(folder.name, "gpu", server.sanitize_settings({}),
                              server.validate_lines(example_lines(), 30))
        assert encoders == ["h264_nvenc", "libx264"]
        assert server.jobs["gpu"]["status"] == "done"
        assert server.jobs["gpu"]["hardware_fallback"] is True
        assert server.jobs["gpu"]["encoder_used"] == "libx264"
    finally:
        server.jobs.pop("gpu", None)


def test_render_api_rejects_simultaneous_same_project(tmp_path, monkeypatch):
    folder = project(tmp_path, "c" * 32)
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server.executor, "submit", lambda *args, **kwargs: None)
    settings = server.sanitize_settings({})
    client = TestClient(server.app)
    body = {"settings": settings, "lines": example_lines()}
    result = client.post("/api/projects/" + folder.name + "/preview", json=body)
    assert result.status_code == 200
    job_id = result.json()["job_id"]
    try:
        second = client.post("/api/projects/" + folder.name + "/render", json=body)
        assert second.status_code == 409
        assert not (folder / "lyric_video.mp4").exists()
    finally:
        server.jobs.pop(job_id, None)


def test_uncertainty_flags_and_bounded_refinement_spans():
    words = [
        {"text": "unclear", "start": 10.2, "end": 10.5, "probability": .35},
        {"text": "normal", "start": 13.1, "end": 13.4, "probability": .95},
        {"text": "other", "start": 28, "end": 28.4, "probability": .45},
    ]
    low = perf.uncertain_words(words)
    assert [w["text"] for w in low] == ["unclear", "other"]
    windows = perf.uncertain_windows(words, 60, max_regions=4)
    assert len(windows) == 2
    assert all(b - a <= 24 for a, b in windows)
    assert perf.uncertain_windows([], 60) == []


def test_refinement_only_applies_after_explicit_acceptance(tmp_path, monkeypatch):
    folder = project(tmp_path, "d" * 32)
    monkeypatch.setattr(server, "DATA", tmp_path)
    data = json.loads((folder / "project.json").read_text())
    data.update(status="review", original_words=[
        {"text": "wrong", "start": 1, "end": 1.7, "probability": .22},
        {"text": "word", "start": 1.8, "end": 2.4, "probability": .3},
    ], draft_lyrics="wrong word")
    (folder / "project.json").write_text(json.dumps(data))
    def fake_run(args):
        Path(args[-1]).write_bytes(b"wav bytes")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    class FakeModel:
        def transcribe(self, path, **options):
            segment = SimpleNamespace(words=[SimpleNamespace(
                word="corrected", start=1.0, end=1.8, probability=.95)])
            return iter([segment]), SimpleNamespace(language="en")
    monkeypatch.setattr(server, "run", fake_run)
    monkeypatch.setattr(server, "load_model", lambda: FakeModel())
    server.jobs["ref"] = {"status": "refining", "progress": 0}
    try:
        server.refine_uncertain_project(folder.name, "ref")
        assert server.jobs["ref"]["status"] == "done"
        unchanged = json.loads((folder / "project.json").read_text())
        assert unchanged["draft_lyrics"] == "wrong word"
        assert "refinement_proposal" in unchanged
        applied = TestClient(server.app).post("/api/projects/" + folder.name + "/refine/apply")
        assert applied.status_code == 200, applied.text
        assert "corrected" in applied.json()["draft_lyrics"]
        new_data = json.loads((folder / "project.json").read_text())
        assert "refinement_proposal" not in new_data
    finally:
        server.jobs.pop("ref", None)


def test_performance_endpoint_does_not_probe_gpu_unprompted(monkeypatch):
    monkeypatch.setattr(server.perf, "resource_snapshot", lambda: {"cpu_percent": 4.2,
                       "ram_mb": 88.0, "logical_cores": 8, "child_ram_mb": 22.0})
    monkeypatch.setattr(server.perf, "available_gpu_encoders",
                        lambda: (_ for _ in ()).throw(AssertionError("unexpected probe")))
    result = TestClient(server.app).get("/api/performance")
    assert result.status_code == 200
    assert result.json()["gpu_encoders"] is None
    assert result.json()["resources"]["cpu_percent"] == 4.2
