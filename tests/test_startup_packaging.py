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
    assert "- uses: actions/upload-artifact@v" in workflow
    artifact = workflow.split("- uses: actions/upload-artifact@v", 1)[1].split(
        "- name: Publish GitHub Release", 1)[0]
    assert "name: SkellyMotion-Windows-x64" in artifact
    assert "path: dist/SkellyMotion/" in artifact
    assert "if: github.event_name == 'workflow_dispatch'" in artifact
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


def test_native_runtime_validates_webview2_managed_dependencies():
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    launcher = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8")
    assert "--native-self-test" in workflow
    assert 'def native_runtime_self_test() -> int:' in launcher
    assert "import clr" in launcher
    assert "clr.AddReference(str(path))" in launcher
    assert "Microsoft.Web.WebView2.Core.dll" in workflow
    assert "Microsoft.Web.WebView2.WinForms.dll" in workflow
    assert "pythonnet==3.0.5" in workflow
    assert "clr-loader==0.2.7.post0" in workflow


def test_runtime_repair_is_packaged_and_uses_narrow_allowlist():
    script = (ROOT / "Repair-SkellyMotion.cmd").read_text(encoding="utf-8")
    launcher = (ROOT / "desktop_launcher.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    assert "--repair-runtime" in script
    assert "MANAGED_UI_DLL_PATHS" in launcher
    assert '"Python.Runtime.dll"' in launcher
    assert '"Microsoft.Web.WebView2.Core.dll"' in launcher
    assert '"Microsoft.Web.WebView2.WinForms.dll"' in launcher
    assert "Zone.Identifier" in launcher
    assert "if response != 6:" in launcher
    assert "Repair-SkellyMotion.cmd" in workflow
    assert "loadFromRemoteSources" not in launcher
    assert "Unblock-File -Path *" not in script


def test_error_diagnostic_identifies_actual_webview_dll_failure():
    import desktop_launcher
    message = desktop_launcher.desktop_runtime_error(
        RuntimeError("Could not load Microsoft.Web.WebView2.Core.dll: 0x80131515"))
    assert "WebView2" in message
    assert "Repair-SkellyMotion.cmd" in message
    assert "Unblock" in message
    clr_message = desktop_launcher.desktop_runtime_error(
        RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize from bundled DLL"))
    assert "Python.NET" in clr_message
    generic = desktop_launcher.desktop_runtime_error(RuntimeError("Missing WebView2"))
    assert "WebView2 Runtime" in generic


def test_windows_repair_requires_approval_for_pythonnet_and_webview2(tmp_path, monkeypatch):
    import ctypes
    import io
    import desktop_launcher

    # Simulate Windows alternate data streams as colon-suffixed files on Linux.
    python_dll = tmp_path / "pythonnet" / "runtime" / "Python.Runtime.dll"
    core_dll = tmp_path / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll"
    winforms_dll = tmp_path / "webview" / "lib" / "Microsoft.Web.WebView2.WinForms.dll"
    for dll in (python_dll, core_dll, winforms_dll):
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.write_bytes(b"trusted code placeholder")
    for dll in (python_dll, core_dll):
        Path(str(dll) + ":Zone.Identifier").write_text(
            "[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")

    class FakeUser32:
        def __init__(self, decision):
            self.decision = decision
            self.shown = 0
            self.message = ""

        def MessageBoxW(self, _hwnd, message, _title, _flags):
            self.shown += 1
            self.message = message
            return self.decision

    fake_sys = SimpleNamespace(frozen=True, stderr=io.StringIO())
    fake_os = SimpleNamespace(name="nt", remove=lambda filename: Path(filename).unlink())
    monkeypatch.setattr(desktop_launcher, "os", fake_os)
    monkeypatch.setattr(desktop_launcher, "sys", fake_sys)
    monkeypatch.setattr(desktop_launcher, "runtime_dir", lambda: tmp_path)

    marked = desktop_launcher.blocked_managed_assemblies()
    assert set(marked) == {python_dll, core_dll}
    declined = FakeUser32(7)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=declined),
                        raising=False)
    assert desktop_launcher.offer_download_marker_repair() is False
    assert declined.shown == 1
    assert "Microsoft.Web.WebView2.Core.dll" in declined.message
    assert all(Path(str(d) + ":Zone.Identifier").exists() for d in marked)

    approved = FakeUser32(6)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=approved),
                        raising=False)
    assert desktop_launcher.offer_download_marker_repair() is True
    assert approved.shown == 1
    assert all(not Path(str(d) + ":Zone.Identifier").exists() for d in marked)
    assert all(d.is_file() for d in (python_dll, core_dll, winforms_dll))
    assert desktop_launcher.blocked_managed_assemblies() == []
    assert desktop_launcher.offer_download_marker_repair() is False
    assert approved.shown == 1


def test_windows_repair_skips_unmarked_and_outside_paths(tmp_path, monkeypatch):
    import desktop_launcher
    bundled = tmp_path / "webview" / "lib" / "Microsoft.Web.WebView2.Core.dll"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"good assembly")
    outside = tmp_path.parent / "not-ours.dll"
    # The function never scans arbitrary DLLs outside the packaged allowlist.
    monkeypatch.setattr(desktop_launcher, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(desktop_launcher, "sys", SimpleNamespace(frozen=True))
    monkeypatch.setattr(desktop_launcher, "runtime_dir", lambda: tmp_path)
    assert desktop_launcher.blocked_managed_assemblies() == []
    assert desktop_launcher.offer_download_marker_repair() is False
    assert outside not in desktop_launcher.bundled_managed_assemblies()


# ---- packaging guards: a module or script that is left out of an image or build only fails after release ----------------------------------
def _covered(pattern_lines, name):
    import fnmatch
    return any(fnmatch.fnmatch(name, p) for p in pattern_lines)


def test_docker_image_ships_every_module_the_server_imports():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    modules = {m.name for m in root.glob("studio_*.py")}
    imported = set(re.findall(r"^import (studio_\w+)", (root / "server.py").read_text(encoding="utf-8"), re.M))
    assert imported and all(f"{name}.py" in modules for name in imported)
    copies = [line.split()[1:-1] for line in (root / "Dockerfile").read_text().splitlines() if line.startswith("COPY ") and "studio_" in line]
    shipped = [item for line in copies for item in line]
    missing = sorted(f"{name}.py" for name in imported if not _covered(shipped, f"{name}.py"))
    assert not missing, f"Dockerfile COPY does not ship: {missing}"


def test_windows_release_workflow_rebuilds_on_any_module_change():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    block = text.split("paths:", 1)[1].split("tags:", 1)[0]
    patterns = re.findall(r"- '([^']+)'", block)
    missing = sorted(m.name for m in root.glob("studio_*.py") if not _covered(patterns, m.name))
    assert not missing, f"windows-release.yml path filter misses: {missing}"


def test_every_page_script_exists_parses_and_is_checked_in_ci():
    import re
    import shutil
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    scripts = re.findall(r'<script src="/static/([\w.-]+\.js)"', (root / "static/index.html").read_text(encoding="utf-8"))
    assert "make.js" in scripts and "autoclip.js" in scripts
    for workflow in ("test.yml", "windows-release.yml"):
        text = (root / ".github/workflows" / workflow).read_text(encoding="utf-8")
        for script in scripts:
            assert f"node --check static/{script}" in text, f"{workflow} does not syntax-check {script}"
    for script in scripts:
        assert (root / "static" / script).is_file()
        if shutil.which("node"):
            done = subprocess.run(["node", "--check", str(root / "static" / script)], capture_output=True, text=True)
            assert done.returncode == 0, done.stderr


def test_html_has_no_duplicate_ids():
    import re
    from collections import Counter
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "static/index.html").read_text(encoding="utf-8")
    dupes = [k for k, v in Counter(re.findall(r'\bid="([^"]+)"', html)).items() if v > 1]
    assert not dupes, dupes


def test_initial_window_geometry_fits_compact_windows_work_area():
    import desktop_launcher
    assert desktop_launcher.initial_window_geometry(1920, 1040) == (960, 623, (800, 520))
    assert desktop_launcher.initial_window_geometry(1024, 720) == (860, 561, (800, 520))
    assert desktop_launcher.initial_window_geometry(896, 574) == (800, 520, (800, 520))
    assert desktop_launcher.initial_window_geometry(780, 520) == (756, 496, (756, 496))
