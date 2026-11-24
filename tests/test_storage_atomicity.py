"""Failure injection for shared storage and consolidated render paths."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import threading
import time

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image

import server
import studio_performance as perf


def test_atomic_json_writers_use_distinct_staging_files(tmp_path, monkeypatch):
    target = tmp_path / "project.json"
    perf.atomic_write_json(target, {"old": True})
    workers = 4
    rendezvous = threading.Barrier(workers)
    observed = []
    original = Path.replace
    def synchronized_replace(self, destination):
        if destination == target:
            observed.append(self)
            rendezvous.wait(timeout=5)
        return original(self, destination)
    monkeypatch.setattr(Path, "replace", synchronized_replace)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda i: server.save_project(tmp_path, {"value": i, "text": "lyric é"}), range(workers)))
    assert len(set(observed)) == workers
    assert json.loads(target.read_text(encoding="utf-8"))["value"] in range(workers)
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_json_failure_preserves_old_data(tmp_path, monkeypatch):
    target = tmp_path / "project.json"
    perf.atomic_write_json(target, {"lyrics": "original"})
    original = target.read_bytes()
    def reject(self, destination):
        raise OSError("simulated publication failure")
    monkeypatch.setattr(Path, "replace", reject)
    with pytest.raises(OSError, match="publication failure"):
        server.save_project(tmp_path, {"lyrics": "new"})
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("payload,status", [(b"", 400), (b"oversized", 413)])
def test_rejected_upload_preserves_existing_file(tmp_path, payload, status):
    target = tmp_path / "song.wav"
    target.write_bytes(b"original")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(server.save_upload(UploadFile(io.BytesIO(payload)), target, limit=4))
    assert caught.value.status_code == status
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]


def test_interrupted_upload_cleans_staging(tmp_path):
    target = tmp_path / "song.wav"
    target.write_bytes(b"original")
    class BrokenStream:
        calls = 0
        async def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return b"partial"
            raise OSError("connection interrupted")
    with pytest.raises(OSError, match="connection interrupted"):
        asyncio.run(server.save_upload(BrokenStream(), target))
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]
    asyncio.run(server.save_upload(UploadFile(io.BytesIO(b"valid replacement")), target))
    assert target.read_bytes() == b"valid replacement"


@pytest.mark.parametrize("native", [False, True])
def test_invalid_draft_background_preserves_prior_image(tmp_path, monkeypatch, native):
    monkeypatch.setattr(server, "DATA", tmp_path)
    pid = "a" * 32
    folder = tmp_path / pid
    folder.mkdir()
    original = folder / "background.png"
    Image.new("RGB", (128, 72), "green").save(original)
    previous_bytes = original.read_bytes()
    server.save_project(folder, {"id": pid, "save_state": "draft", "background_file": original.name})
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    if native:
        with pytest.raises(ValueError):
            server.import_desktop_background_file(pid, broken)
    else:
        response = TestClient(server.app).post(f"/api/projects/{pid}/background",
            files={"file": ("broken.png", broken.read_bytes(), "image/png")})
        assert response.status_code == 400
    assert original.read_bytes() == previous_bytes
    assert server.read_project(pid)["background_file"] == original.name
    assert {p.name for p in folder.iterdir()} == {"project.json", original.name}
    good = tmp_path / "good.png"
    Image.new("RGB", (128, 72), "blue").save(good)
    result = server.import_desktop_background_file(pid, good)
    assert (folder / result["name"]).read_bytes() == good.read_bytes()
    assert not original.exists()


def test_brand_asset_copy_failure_preserves_old_media(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "workspace")
    folder = server.brand_dir()
    old = folder / "music.wav"
    old.write_bytes(b"old media")
    new = tmp_path / "replacement.mp3"
    new.write_bytes(b"replacement")
    monkeypatch.setattr(server.clips, "probe_media", lambda _: {"has_audio": True})
    def failed_copy(source, target):
        Path(target).write_bytes(b"incomplete copy")
        raise OSError("disk full")
    original_copy = server.shutil.copy2
    monkeypatch.setattr(server.shutil, "copy2", failed_copy)
    with pytest.raises(OSError, match="disk full"):
        server.store_brand_asset("music", new)
    assert old.read_bytes() == b"old media"
    assert list(folder.iterdir()) == [old]
    monkeypatch.setattr(server.shutil, "copy2", original_copy)
    server.store_brand_asset("music", new)
    assert server.brand_asset("music").read_bytes() == b"replacement"
    assert not old.exists()
    assert len(list(folder.iterdir())) == 1


def test_empty_library_reads_do_not_create_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    client = TestClient(server.app)
    for route in ("/api/brand", "/api/brand/broll", "/api/presets"):
        assert client.get(route).status_code == 200
    assert not list(tmp_path.iterdir())


def test_invalid_brand_json_shape_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    folder = server.brand_dir()
    (folder / "brand.json").write_text("[]", encoding="utf-8")
    (folder / "presets.json").write_text("null", encoding="utf-8")
    assert TestClient(server.app).get("/api/brand").status_code == 200
    assert TestClient(server.app).get("/api/presets").status_code == 200
    assert (folder / "brand.json").read_text() == "[]"


def test_locked_old_background_does_not_break_published_replacement(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    pid = "b" * 32
    folder = tmp_path / pid
    folder.mkdir()
    old = folder / "background.png"
    Image.new("RGB", (128, 72), "green").save(old)
    server.save_project(folder, {"id": pid, "save_state": "draft", "background_file": old.name})
    new = tmp_path / "replacement.png"
    Image.new("RGB", (128, 72), "blue").save(new)
    original_unlink = Path.unlink
    def locked(self, *args, **kwargs):
        if self == old:
            raise PermissionError("in use")
        return original_unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    result = server.import_desktop_background_file(pid, new)
    assert old.is_file()
    assert (folder / result["name"]).read_bytes() == new.read_bytes()
    assert server.read_project(pid)["background_file"] == result["name"]


def test_shorts_and_full_render_choose_same_pending_background(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    pid = "c" * 32
    folder = tmp_path / pid
    folder.mkdir()
    saved = folder / "background.png"
    pending = folder / ("background-pending-" + "d" * 32 + ".png")
    saved.write_bytes(b"saved")
    pending.write_bytes(b"pending")
    data = {"id": pid, "background_file": saved.name}
    server.save_project(folder, data)
    perf.atomic_write_json(folder / "recovery.json", {"pending_background": pending.name})
    settings = server.sanitize_settings({"background": "custom"})
    assert server.selected_background(folder, data, settings) == pending
    assert server.resolve_background(pid, data, settings) == (pending, False, pending)
    pending.unlink()
    assert server.selected_background(folder, data, settings) == saved


def test_malformed_broll_index_cannot_delete_unrelated_file(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    folder = server.broll_dir()
    unrelated = tmp_path / "protected.mp4"
    unrelated.write_bytes(b"do not delete")
    (folder / "bad.mp4").write_bytes(b"bad metadata")
    perf.atomic_write_json(folder / "index.json", {
        "evil": {"file": "../../protected.mp4", "duration": 3, "keywords": ["evil"]},
        "bad": {"file": "bad.mp4", "duration": "NaN", "keywords": ["bad"]},
        "broken": None,
    })
    client = TestClient(server.app)
    assert client.get("/api/brand/broll").json()["clips"] == []
    assert client.delete("/api/brand/broll/evil").status_code == 404
    assert unrelated.read_bytes() == b"do not delete"


def test_failed_parent_releases_child_job(monkeypatch):
    work = {"parent": {"status": "rendering"},
            "child": {"parent": "parent", "status": "rendering"},
            "unrelated": {"status": "rendering"}}
    monkeypatch.setattr(server, "jobs", work)
    server.fail_job("parent", RuntimeError("encoder failed"), time.monotonic())
    assert work["parent"]["status"] == work["child"]["status"] == "error"
    assert work["unrelated"]["status"] == "rendering"
