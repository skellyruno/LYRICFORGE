"""Regression checks: faster decoding, truthful progress, preserved model choice."""
import json
from pathlib import Path
from types import SimpleNamespace

import server


class FakeModel:
    def __init__(self):
        self.options = None

    def transcribe(self, path, **kwargs):
        self.options = kwargs
        parts = [
            SimpleNamespace(end=2.0, words=[SimpleNamespace(word="Hello", start=0.5, end=1.2)]),
            SimpleNamespace(end=5.0, words=[SimpleNamespace(word="there", start=2.3, end=3.0)]),
        ]
        return iter(parts), SimpleNamespace(language="en")


def test_transcription_fast_settings_and_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    monkeypatch.delenv("SKELLYMOTION_BEAM_SIZE", raising=False)
    project_id = "a" * 32
    path = tmp_path / project_id
    path.mkdir()
    (path / "project.json").write_text(json.dumps({
        "id": project_id, "status": "transcribing", "duration": 5.0,
        "audio_file": "song.wav",
    }))
    model = FakeModel()
    monkeypatch.setattr(server, "load_model", lambda: model)
    server.transcribe_project(project_id)
    data = json.loads((path / "project.json").read_text())
    assert data["status"] == "review"
    assert data["transcription_stage"] == "complete"
    assert data["transcription_progress"] == 100
    assert "Hello" in data["draft_lyrics"]
    assert model.options["beam_size"] == 3
    assert model.options["best_of"] == 1
    assert model.options["temperature"] == 0
    assert model.options["word_timestamps"] is True
    assert model.options["vad_filter"] is False


def test_transcription_beam_override_for_accuracy(monkeypatch):
    monkeypatch.setenv("SKELLYMOTION_BEAM_SIZE", "5")
    assert server.transcription_beam_size() == 5
    monkeypatch.setenv("SKELLYMOTION_BEAM_SIZE", "invalid")
    assert server.transcription_beam_size() == 3
    monkeypatch.setenv("SKELLYMOTION_BEAM_SIZE", "1000")
    assert server.transcription_beam_size() == 5


def test_progress_only_updates_active_transcriptions(tmp_path):
    project = tmp_path / ("b" * 32)
    project.mkdir()
    (project / "project.json").write_text(json.dumps({"status": "review", "transcription_progress": 100}))
    server.update_transcription_stage(project, "recognizing", 20)
    assert json.loads((project / "project.json").read_text())["transcription_progress"] == 100
