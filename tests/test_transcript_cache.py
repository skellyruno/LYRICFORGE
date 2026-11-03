"""Exact-song transcription reuse must never borrow corrected words or the wrong model."""
import json

from fastapi.testclient import TestClient
import server


def test_identical_upload_reuses_transcript_but_not_manual_edits(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.setattr(server, "media_duration", lambda path: 9.0)
    submitted = []
    monkeypatch.setattr(server.ai_executor, "submit", lambda *args: submitted.append(args))
    client = TestClient(server.app)
    payload = b"repeatable-audio-file"
    request = lambda vocabulary="": client.post(
        "/api/projects", files={"file": ("vocal.wav", payload, "audio/wav")},
        data={"recognition": "balanced", "language": "en", "vocabulary": vocabulary})

    first = request()
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "transcribing"
    assert len(submitted) == 1
    path = tmp_path / first.json()["id"]
    data = json.loads((path / "project.json").read_text())
    assert isinstance(data["transcription_cache_key"], str)
    original_words = [
        {"text": "Hello", "start": .2, "end": .5, "probability": .9},
        {"text": "world", "start": .6, "end": 1, "probability": .4},
    ]
    data.update({"original_words": original_words, "language": "en",
                 "draft_lyrics": "Hello world", "status": "review",
                 "transcription_stage": "complete"})
    server.remember_transcript(data)
    # Edit a different project's lyric draft: it must not enter the shared cache.
    data["draft_lyrics"] = "User's corrected private lyrics"
    (path / "project.json").write_text(json.dumps(data))

    second = request()
    assert second.status_code == 200
    assert second.json()["transcription_cached"] is True
    assert second.json()["status"] == "review"
    assert len(submitted) == 1
    new_manifest = json.loads((tmp_path / second.json()["id"] / "project.json").read_text())
    assert new_manifest["draft_lyrics"] == "Hello world"
    assert new_manifest["original_words"] == original_words

    other_vocabulary = request("SkellyMotion unique nickname")
    assert other_vocabulary.json()["transcription_cached"] is False
    assert len(submitted) == 2


def test_cache_is_invalidated_on_song_change(tmp_path):
    a = tmp_path / "song.wav"
    a.write_bytes(b"first track")
    defaults = {"recognition_mode": "balanced", "language_hint": "en"}
    first_key = server.transcription_cache_key(a, defaults)
    a.write_bytes(b"another track")
    assert server.transcription_cache_key(a, defaults) != first_key


def test_desktop_import_retains_hints_and_workers(tmp_path, monkeypatch):
    work = tmp_path / "workspace"
    work.mkdir()
    monkeypatch.setattr(server, "DATA", work)
    monkeypatch.setattr(server, "media_duration", lambda path: 10.0)
    tasks = []
    monkeypatch.setattr(server.ai_executor, "submit", lambda *args: tasks.append(args))
    source = tmp_path / "source.wav"
    source.write_bytes(b"voice bytes")
    result = server.import_desktop_audio_file(source, recognition="accurate",
                                               language="en",
                                               vocabulary="Skelly",
                                               performance_mode="eco")
    assert result["status"] == "transcribing"
    saved = json.loads((work / result["id"] / "project.json").read_text())
    assert saved["vocabulary_hint"] == "Skelly"
    assert saved["recognition_mode"] == "accurate"
    assert saved["performanceMode"] == "eco"
    assert len(tasks) == 1
