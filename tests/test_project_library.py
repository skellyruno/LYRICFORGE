"""Project-library regression tests. No music files or AI inference needed."""
import json
import os

from fastapi.testclient import TestClient
import server


def test_saved_project_library_is_recent_first_and_private(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    entries = [("a" * 32, "Older song", 100), ("b" * 32, "Latest song", 200)]
    for identity, title, timestamp in entries:
        folder = tmp_path / identity
        folder.mkdir()
        manifest = folder / "project.json"
        manifest.write_text(json.dumps({
            "id": identity, "title": title, "duration": 182.5,
            "status": "editor", "audio_file": "private-song.wav",
            "original_words": [{"text": "private lyrics"}],
            "lines": [{"text": "sample"}], "settings": {"font": "Arial"},
        }))
        os.utime(manifest, (timestamp, timestamp))

    response = TestClient(server.app).get("/api/projects")
    assert response.status_code == 200, response.text
    data = response.json()["projects"]
    assert len(data) == 2
    assert [item["title"] for item in data] == ["Latest song", "Older song"]
    assert data[0]["id"] == "b" * 32
    assert data[0]["lines"] == 1
    assert all("audio_file" not in item for item in data)
    assert all("original_words" not in item for item in data)


def test_library_skips_broken_or_unrecognized_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    (tmp_path / "random-folder").mkdir()
    bad = tmp_path / ("c" * 32)
    bad.mkdir()
    (bad / "project.json").write_text("not json!")
    response = TestClient(server.app).get("/api/projects")
    assert response.status_code == 200
    assert response.json()["projects"] == []
