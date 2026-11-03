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


def test_native_runtime_failure_is_checked_by_windows_ci():
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    launcher = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8")
    assert "--native-self-test" in workflow
    assert 'def native_runtime_self_test() -> int:' in launcher
    assert "import clr" in launcher
    assert 'from System import Environment' in launcher
    assert 'Python.Runtime.dll' in workflow
    assert "pythonnet==3.0.5" in workflow
    assert "clr-loader==0.2.7.post0" in workflow


def test_opt_in_runtime_repair_is_packaged_and_targets_only_pythonnet_dll():
    script = (ROOT / "Repair-SkellyMotion.cmd").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    assert r"_internal\pythonnet\runtime\Python.Runtime.dll" in script
    assert "Zone.Identifier" in script
    assert "Read-Host" in script
    assert "Unblock-File -LiteralPath $dll" in script
    assert "Unblock-File -Path *" not in script
    assert "Repair-SkellyMotion.cmd" in workflow


def test_error_diagnostic_is_about_pythonnet_not_just_webview2():
    import desktop_launcher
    message = desktop_launcher.desktop_runtime_error(
        RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize from bundled DLL"))
    assert "Python.NET" in message
    assert "Python.Runtime.dll" in message
    assert "Unblock" in message
    assert "Repair-SkellyMotion.cmd" in message
    generic = desktop_launcher.desktop_runtime_error(RuntimeError("Missing WebView2"))
    assert "WebView2 Runtime" in generic


def test_windows_download_marker_preflight_requires_explicit_consent(tmp_path, monkeypatch):
    import ctypes
    import io
    import desktop_launcher

    dll = tmp_path / "Python.Runtime.dll"
    dll.write_bytes(b"verified packaged DLL placeholder")
    marker = Path(str(dll) + ":Zone.Identifier")
    marker.write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    class FakeMessageBox:
        def __init__(self, answer):
            self.answer = answer
            self.shown = 0
        def MessageBoxW(self, *args):
            self.shown += 1
            return self.answer

    fake_sys = SimpleNamespace(frozen=True, stderr=io.StringIO())
    fake_os = SimpleNamespace(name="nt", remove=lambda name: Path(name).unlink())
    monkeypatch.setattr(desktop_launcher, "os", fake_os)
    monkeypatch.setattr(desktop_launcher, "sys", fake_sys)
    monkeypatch.setattr(desktop_launcher, "bundled_python_runtime", lambda: dll)

    denied = FakeMessageBox(7)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=denied), raising=False)
    assert desktop_launcher.offer_download_marker_repair() is False
    assert marker.is_file()
    assert denied.shown == 1

    accepted = FakeMessageBox(6)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=accepted), raising=False)
    assert desktop_launcher.offer_download_marker_repair() is True
    assert not marker.exists()
    assert dll.is_file()
    assert accepted.shown == 1
    assert desktop_launcher.offer_download_marker_repair() is False
    assert accepted.shown == 1


def test_windows_download_marker_preflight_skips_unmarked_dll(tmp_path, monkeypatch):
    import desktop_launcher
    dll = tmp_path / "Python.Runtime.dll"
    dll.write_bytes(b"some dll")
    monkeypatch.setattr(desktop_launcher, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(desktop_launcher, "sys", SimpleNamespace(frozen=True))
    monkeypatch.setattr(desktop_launcher, "bundled_python_runtime", lambda: dll)
    assert desktop_launcher.offer_download_marker_repair() is False
