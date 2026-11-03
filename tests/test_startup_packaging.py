"""Regressions for startup responsiveness and single-extraction Windows distribution."""
import json
import subprocess
from array import array
from pathlib import Path
from types import SimpleNamespace

import server


ROOT = Path(__file__).resolve().parents[1]


def test_actions_artifact_contains_program_not_zip_inside_zip():
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    artifact = workflow.split("- uses: actions/upload-artifact@v4", 1)[1].split(
        "- name: Publish GitHub Release", 1)[0]
    assert "name: SkellyMotion-Windows-x64" in artifact
    assert "path: dist/SkellyMotion/" in artifact
    assert "path: dist/SkellyMotion-Windows-x64.zip" not in artifact
    # Public release assets still need their own distributable ZIP.
    assert "- name: Package GitHub Release ZIP" in workflow
    zip_step = workflow.split("- name: Package GitHub Release ZIP", 1)[1]
    assert "if: startsWith(github.ref, 'refs/tags/v')" in zip_step
    assert "Compress-Archive" in zip_step


def test_desktop_starts_on_lightweight_welcome_with_resume_button():
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "static/app.js").read_text(encoding="utf-8")
    launcher = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8")
    assert 'id="resumeLastBtn"' in html
    assert "restore(true)" in js
    assert "if(lastSession&&!document.documentElement.classList.contains('desktop-mode'))" in js
    assert "setTimeout(()=>{if(state.id===project.id)loadWaveform();},450)" in js
    assert "log_stage(\"native window created; initializing WebView2\")" in launcher
    assert 'preload="metadata"' in html


def test_waveform_jobs_get_one_cpu_thread_and_low_priority(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    identity = "a" * 32
    folder = tmp_path / identity
    folder.mkdir()
    (folder / "project.json").write_text(json.dumps({
        "id": identity, "audio_file": "song.wav", "duration": 8.5
    }), encoding="utf-8")
    (folder / "song.wav").write_bytes(b"audio")
    jobs = []
    priorities = []

    def fake_flags(low_priority=False):
        priorities.append(low_priority)
        return {}

    def fake_run(cmd, **kwargs):
        jobs.append((cmd, kwargs))
        sample_data = array("f", [0.1, -0.4, .3, .8] * 100).tobytes()
        return SimpleNamespace(returncode=0, stdout=sample_data, stderr=b"")

    monkeypatch.setattr(server.perf, "windows_child_options", fake_flags)
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    result = server.get_waveform(identity)
    assert result["peaks"]
    command, options = jobs[0]
    assert command[command.index("-threads") + 1] == "1"
    assert "-nostdin" in command
    assert options["stdin"] is subprocess.DEVNULL
    assert priorities == [True]
    # Reopening should use the cached peaks without touching FFmpeg.
    assert server.get_waveform(identity) == result
    assert len(jobs) == 1
