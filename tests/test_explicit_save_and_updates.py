"""Explicit Save, crash recovery, selective deletion, native MP4 Save As and update safety."""
import hashlib
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
import pytest

import desktop_launcher
import server
import studio_updater as updater


def make_project(tmp, identity, saved=False):
    directory = tmp / identity
    directory.mkdir(parents=True)
    (directory / "song.wav").write_bytes(b"audio source copy")
    (directory / "project.json").write_text(json.dumps({
        "id": identity, "title": "Song " + identity[0], "status": "editor",
        "duration": 12, "audio_file": "song.wav",
        "save_state": "saved" if saved else "draft",
        "lines": [], "settings": {},
    }))
    return directory


def test_auto_recovery_does_not_permanently_save_or_change_saved_lyrics(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    folder = make_project(tmp_path, "a" * 32, saved=True)
    client = TestClient(server.app)
    draft = {"lines": [{"text": "Changed lyric", "start": 1, "end": 3, "words": []}],
             "settings": {"font": "Arial"}, "draft_lyrics": ""}
    result = client.put("/api/projects/" + folder.name + "/recovery", json=draft)
    assert result.status_code == 200, result.text
    assert result.json() == {"recovered": True, "saved": False}
    assert server.read_project(folder.name)["lines"] == []
    assert (folder / "recovery.json").exists()
    assert client.get("/api/projects/" + folder.name + "/recovery").json()["lines"][0]["text"] == "Changed lyric"

    # Explicit Save commits a new version, clearing the crash draft.
    saved = client.put("/api/projects/" + folder.name, json=draft)
    assert saved.status_code == 200
    assert saved.json()["save_state"] == "saved"
    assert not (folder / "recovery.json").exists()
    assert server.read_project(folder.name)["lines"][0]["text"] == "Changed lyric"


def test_old_projects_are_preserved_and_new_drafts_are_listed_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    make_project(tmp_path, "a" * 32, saved=True)
    make_project(tmp_path, "b" * 32, saved=False)
    legacy = make_project(tmp_path, "c" * 32)
    data = json.loads((legacy / "project.json").read_text())
    del data["save_state"]
    (legacy / "project.json").write_text(json.dumps(data))
    data = TestClient(server.app).get("/api/projects").json()
    assert {p["id"] for p in data["projects"]} == {"a" * 32, "c" * 32}
    assert [d["id"] for d in data["drafts"]] == ["b" * 32]


def test_discard_saved_only_recovery_but_discard_draft_deletes_it(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    saved = make_project(tmp_path, "a" * 32, saved=True)
    draft = make_project(tmp_path, "b" * 32, saved=False)
    for p in (saved, draft):
        (p / "recovery.json").write_text("{}")
    client = TestClient(server.app)
    a = client.post("/api/projects/" + saved.name + "/discard")
    assert a.status_code == 200
    assert a.json()["kept_saved_project"] is True
    assert saved.is_dir() and (saved / "song.wav").is_file()
    assert not (saved / "recovery.json").exists()
    b = client.post("/api/projects/" + draft.name + "/discard")
    assert b.status_code == 200
    assert b.json()["deleted"] is True
    assert not draft.exists()


def test_delete_only_checked_projects_and_protect_model_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "workspace")
    server.DATA.mkdir()
    keep = make_project(server.DATA, "a" * 32, saved=True)
    remove = make_project(server.DATA, "b" * 32, saved=True)
    model = tmp_path / "models" / "whisper-small"
    model.mkdir(parents=True)
    (model / "config.json").write_text("model unchanged")
    client = TestClient(server.app)
    no_confirm = client.post("/api/projects/bulk-delete", json={
        "project_ids": [remove.name], "confirm": False})
    assert no_confirm.status_code == 400
    attempted = client.post("/api/projects/bulk-delete", json={
        "project_ids": ["../models"], "confirm": True})
    assert attempted.status_code in (400, 404)
    success = client.post("/api/projects/bulk-delete", json={
        "project_ids": [remove.name], "confirm": True})
    assert success.status_code == 200, success.text
    assert keep.exists() and not remove.exists()
    assert (model / "config.json").read_text() == "model unchanged"


def test_export_does_not_implicitly_save(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    folder = make_project(tmp_path, "d" * 32)
    monkeypatch.setattr(server.executor, "submit", lambda *args: None)
    body = {"lines": [{"text": "new line", "start": 1, "end": 3, "words": []}],
            "settings": {}}
    client = TestClient(server.app)
    result = client.post("/api/projects/" + folder.name + "/render", json=body)
    assert result.status_code == 200
    try:
        data = server.read_project(folder.name)
        assert data["save_state"] == "draft"
        assert data["lines"] == []
    finally:
        server.jobs.pop(result.json()["job_id"], None)


def test_native_mp4_saves_outside_app_without_webview_download(tmp_path, monkeypatch):
    project = make_project(tmp_path / "workspace", "e" * 32)
    output = project / "lyric_video.mp4"
    output.write_bytes(b"MP4" * 4096)
    monkeypatch.setattr(server, "DATA", project.parent)
    destination = tmp_path / "my rendered video.mp4"
    import sys
    fake_webview = SimpleNamespace(FileDialog=SimpleNamespace(SAVE=20))
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    def pick(**kwargs):
        assert kwargs["dialog_type"] == 20
        assert "MP4 video" in kwargs["file_types"][0]
        return [str(destination)]

    picker = desktop_launcher.DesktopFilePicker()
    picker._window = SimpleNamespace(create_file_dialog=pick)
    assert not hasattr(picker, 'window')  # Native window must not leak through JS bridge
    result = picker.save_video(project.name)
    assert result["status"] == "saved"
    assert destination.read_bytes() == output.read_bytes()
    assert output.is_file()


def test_release_validation_requires_newer_version_and_verified_digest():
    sha = "a" * 64
    release = {"tag_name": "v0.9.1", "draft": False, "prerelease": False,
               "html_url": "https://github.com/skellyruno/LYRICFORGE/releases/tag/v0.9.1",
               "assets": [{"name": updater.ASSET_NAME, "size": 345678901,
                           "id": 11, "digest": "sha256:" + sha}]}
    assert updater.validate_release(release)["status"] == "update"
    assert updater.validate_release(release)["sha256"] == sha
    assert updater.validate_release({**release, "tag_name": "v0.8.9"})["status"] == "current"
    assert updater.validate_release({**release, "assets": [{**release["assets"][0],
                                     "digest": None}]})["status"] == "unavailable"
    assert updater.validate_release({**release, "prerelease": True})["status"] == "unavailable"


def test_zip_extraction_blocks_traversal_and_preserves_nonapp_files(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("SkellyMotion/../secrets.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe"):
        updater.verified_zip_extract(bad, tmp_path / "bad-unpacked")
    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as z:
        z.writestr("SkellyMotion/SkellyMotion.exe", "fake executable")
        z.writestr("SkellyMotion/_internal/config.json", "{}")
    prepared = updater.verified_zip_extract(good, tmp_path / "good-unpacked")
    assert (prepared / "SkellyMotion.exe").is_file()
    assert (prepared / "_internal").is_dir()
    assert not (tmp_path / "secrets.txt").exists()


def test_private_release_without_auth_shows_prerequisite_without_token(monkeypatch):
    monkeypatch.setattr(updater, "sys", SimpleNamespace(frozen=True))
    monkeypatch.setattr(updater, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(updater, "latest_release", lambda: (None, "needs_auth"))
    data = updater.check_for_updates()
    assert data["status"] == "needs_auth"
    assert "gh auth login" in data["reason"]
    assert "token" in data["reason"].lower()
