"""Tests for opt-in cleanup and additional lyric animation options."""
from fastapi.testclient import TestClient
import server


def test_storage_cleanup_preserves_source_and_current_export(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    old = tmp_path / ("a" * 32)
    active = tmp_path / ("b" * 32)
    for folder in (old, active):
        folder.mkdir()
        (folder / "project.json").write_text("{}")
        (folder / "song.mp3").write_bytes(b"source audio")
        (folder / "background.png").write_bytes(b"original background")
        (folder / "lyric_video.mp4").write_bytes(b"render")
        (folder / "captions.ass").write_bytes(b"caption")
    client = TestClient(server.app)
    report = client.get("/api/storage", params={"keep_project_id": active.name})
    assert report.status_code == 200
    assert report.json()["cleanup_files"] == 2
    assert client.post("/api/storage/cleanup", json={"keep_project_id": active.name}).status_code == 400
    result = client.post("/api/storage/cleanup",
                         json={"keep_project_id": active.name, "confirm": True})
    assert result.status_code == 200, result.text
    assert result.json()["removed_files"] == 2
    assert (old / "song.mp3").exists()
    assert (old / "background.png").exists()
    assert (old / "project.json").exists()
    assert (active / "lyric_video.mp4").exists()
    assert (active / "captions.ass").exists()


def test_extended_animations_generate_valid_captions(tmp_path):
    for name in ("zoom", "bounce", "blur"):
        setting = server.sanitize_settings({"animation": name})
        assert setting["animation"] == name
        file = tmp_path / (name + ".ass")
        server.create_ass([{"start": 0.0, "end": 1.0,
                            "text": "Hello", "words": []}], setting, 720, 1280, file)
        assert "Dialogue:" in file.read_text(encoding="utf-8-sig")
