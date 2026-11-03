"""Startup recovery tests: safe WebView2 profile, usable browser fallback and idle UI."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import desktop_launcher


class DummyEvent:
    def __init__(self):
        self.callbacks = []

    def __iadd__(self, handler):
        self.callbacks.append(handler)
        return self


class FakeWindow:
    def __init__(self):
        self.events = SimpleNamespace(shown=DummyEvent(), loaded=DummyEvent(), closing=DummyEvent())


class FakeUvicorn:
    class Config:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

    class Server:
        def __init__(self, config):
            self.should_exit = False

        def run(self):
            return None


def test_safe_mode_uses_separate_profile_and_software_gpu_only_by_request(
        tmp_path, monkeypatch):
    fake = FakeWindow()
    calls = []
    fake_webview = SimpleNamespace(
        create_window=lambda *args, **kw: fake,
        start=lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop_launcher, "offer_download_marker_repair", lambda: False)
    monkeypatch.setattr(desktop_launcher, "available_port", lambda: 44201)
    monkeypatch.setattr(desktop_launcher, "wait_until_ready", lambda *args: True)
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)

    assert desktop_launcher.run_desktop(tmp_path, safe_mode=True) == 0
    assert calls[0]["gui"] == "edgechromium"
    assert calls[0]["storage_path"] == str(tmp_path / "webview_safe")
    assert "--disable-gpu" in desktop_launcher.os.environ[
        "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
    assert (tmp_path / "webview_safe").is_dir()
    assert len(fake.events.shown.callbacks) == 1
    assert len(fake.events.loaded.callbacks) == 1
    # Existing project/song/model folders must remain untouched.
    assert not (tmp_path / "workspace").exists()


def test_normal_mode_preserves_gpu_and_existing_webview_profile(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=lambda *args, **kw: FakeWindow(),
        start=lambda **kw: calls.append(kw)))
    monkeypatch.setattr(desktop_launcher, "offer_download_marker_repair", lambda: False)
    monkeypatch.setattr(desktop_launcher, "available_port", lambda: 44201)
    monkeypatch.setattr(desktop_launcher, "wait_until_ready", lambda *args: True)
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)

    assert desktop_launcher.run_desktop(tmp_path) == 0
    assert calls[0]["storage_path"] == str(tmp_path / "webview")
    assert "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" not in desktop_launcher.os.environ


def test_browser_fallback_avoids_embedded_webview(tmp_path, monkeypatch):
    urls = []
    messages = []
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)
    monkeypatch.setitem(sys.modules, "webbrowser", SimpleNamespace(
        open=lambda url, new=0: urls.append((url, new)) or True))
    # A browser-only fallback should never load the blocked UI bridge.
    monkeypatch.setitem(sys.modules, "webview", None)
    monkeypatch.setattr(desktop_launcher, "available_port", lambda: 45009)
    monkeypatch.setattr(desktop_launcher, "wait_until_ready", lambda *args: True)
    monkeypatch.setattr(desktop_launcher, "native_notice", messages.append)

    assert desktop_launcher.run_browser_mode(tmp_path) == 0
    assert urls == [("http://127.0.0.1:45009/", 1)]
    assert "default browser" in messages[0].lower()


def test_recovery_launchers_are_packaged_and_point_to_exe():
    root = Path(__file__).resolve().parents[1]
    build = (root / ".github/workflows/windows-release.yml").read_text()
    for mode, command in (("SafeMode", "--safe-mode"),
                          ("BrowserMode", "--browser-mode")):
        file = root / f"SkellyMotion-{mode}.cmd"
        contents = file.read_text(encoding="utf-8")
        assert command in contents
        assert "SkellyMotion.exe" in contents
        assert f"Copy-Item -LiteralPath 'SkellyMotion-{mode}.cmd'" in build
    script = (root / "static/app.js").read_text()
    assert "if(covered&&!state.playing&&!state.lines.length)return;" in script
