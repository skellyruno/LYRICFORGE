"""Startup/desktop import regressions for the SkellyMotion Windows UI."""
from pathlib import Path
import re
import json
import pytest

import server


def test_frontend_selectors_and_file_picker_wiring():
    html = (server.STATIC / "index.html").read_text(encoding="utf-8")
    js = (server.STATIC / "app.js").read_text(encoding="utf-8")
    css = (server.STATIC / "style.css").read_text(encoding="utf-8")
    # $() resolves an element ID, $$() resolves selectors. A mix-up crashes
    # wireUI() before it can attach the upload handler (the reported bug).
    invalid = re.findall(r"(?<!\$)\$\(['\"](?:\.|#|\[)[^'\"]+['\"]\)", js)
    assert not invalid, f"CSS selectors passed to getElementById: {invalid}"
    assert "$$('.rail-item').forEach" in js
    assert "$$('[data-preset]').forEach" in js
    assert "$('heroUpload').addEventListener('click',chooseSong)" in js
    assert "$('backgroundUploadTrigger').addEventListener('click',chooseBackground)" in js
    assert "bridge.choose_audio(" in js
    assert "bridge.choose_background(state.id)" in js
    assert '<button type="button" class="hero-upload" id="heroUpload">' in html
    assert 'id="audioFile" type="file"' in html
    assert 'id="backgroundUploadTrigger"' in html
    assert 'id="backgroundFile" type="file"' in html
    assert "desktop-mode" in html
    assert "transform:scale(.65)" in css


def test_desktop_import_keeps_original_source_and_creates_project(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "workspace")
    server.DATA.mkdir()
    monkeypatch.setattr(server, "media_duration", lambda path: 3.75)
    # Do not launch an actual Whisper job in this focused import test.
    submitted = []
    monkeypatch.setattr(server.ai_executor, "submit", lambda fn, *args: submitted.append((fn, args)))
    source = tmp_path / "My demo song.mp3"
    source.write_bytes(b"dummy audio bytes")
    new_song = server.import_desktop_audio_file(source)
    assert len(new_song["id"]) == 32
    assert new_song["title"] == "My demo song"
    assert new_song["duration"] == 3.75
    assert new_song["status"] == "transcribing"
    project = server.DATA / new_song["id"]
    assert (project / "song.mp3").read_bytes() == source.read_bytes()
    assert source.exists()
    saved = json.loads((project / "project.json").read_text(encoding="utf-8"))
    assert saved["audio_file"] == "song.mp3"
    assert submitted and submitted[0][1] == (new_song["id"],)


def test_desktop_import_rejects_wrong_extension_before_creating_project(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    bad = tmp_path / "not-a-song.exe"
    bad.write_bytes(b"hello")
    with pytest.raises(ValueError, match="Choose an MP3"):
        server.import_desktop_audio_file(bad)
    assert not any(p.is_dir() for p in tmp_path.iterdir())


def test_native_background_import_preserves_source_and_replaces_old(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(server, "DATA", tmp_path / "workspace")
    server.DATA.mkdir()
    project_id = "a" * 32
    folder = server.DATA / project_id
    folder.mkdir()
    (folder / "project.json").write_text(
        json.dumps({"id": project_id, "background_file": "background_old.jpg"}),
        encoding="utf-8")
    (folder / "background_old.jpg").write_bytes(b"old")
    selected = tmp_path / "scene.png"
    selected.write_bytes(b"test png fixture")
    monkeypatch.setattr(server, "run", lambda cmd: SimpleNamespace(stdout="1280\n"))
    result = server.import_desktop_background_file(project_id, selected)
    assert result["name"] == "background.png"
    assert selected.exists() and selected.read_bytes() == b"test png fixture"
    assert (folder / "background.png").read_bytes() == selected.read_bytes()
    assert not (folder / "background_old.jpg").exists()
    assert not (folder / "background_pending.png").exists()
    assert json.loads((folder / "project.json").read_text())["background_file"] == "background.png"
