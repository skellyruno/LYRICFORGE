from __future__ import annotations
import io
import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import server


def test_timing_edit_and_karaoke(tmp_path):
    old = [
        {"text": "I", "start": .5, "end": .7},
        {"text": "fly", "start": .75, "end": 1.1},
        {"text": "high", "start": 1.12, "end": 1.6},
    ]
    aligned = server.align_confirmed("I fly\nso high", old, 5)
    assert len(aligned) == 2
    assert aligned[0]["start"] == .5
    assert aligned[1]["words"][-1]["end"] == 1.6
    assert server.sanitize_settings({"font": "bogus", "textColor": "red"})["textColor"] == "#FFFFFF"
    assert server.sanitize_settings({"background": "custom"})["background"] == "custom"
    f = tmp_path / "captions.ass"
    config = server.sanitize_settings({"mode": "karaoke", "animation": "slide"})
    server.create_ass(aligned, config, 720, 1280, f)
    text = f.read_text(encoding="utf-8-sig")
    assert "\\k" in text
    assert "Dialogue: " in text


def test_roundtrip_audio_background_render(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    # Model inference is optional for tests; inject known ASR output while testing pipeline.
    def fake_asr(project_id):
        d = server.read_project(project_id)
        d["original_words"] = [
            {"text":"Hello", "start":0.2,"end":0.6},
            {"text":"world", "start":0.65,"end":1.0},
        ]
        d["draft_lyrics"] = "Hello world"
        d["status"] = "review"
        server.save_project(server.project_dir(project_id), d)
    monkeypatch.setattr(server, "transcribe_project", fake_asr)
    # The integration test verifies file import, timing and a real MP4 export;
    # run the stub transcription synchronously rather than queueing behind AI jobs.
    monkeypatch.setattr(server.ai_executor, "submit", lambda fn, *args: fn(*args))
    path = tmp_path / 'sample.wav'
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.7", str(path)], check=True)
    client=TestClient(server.app)
    response = client.post('/api/projects', files={'file': ('test.wav', path.read_bytes(), 'audio/wav')})
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    for _ in range(40):
        p = client.get('/api/projects/'+pid).json()
        if p['status']=='review': break
        time.sleep(.05)
    assert p['status']=='review'
    wave = client.get(f'/api/projects/{pid}/waveform')
    assert wave.status_code == 200, wave.text
    assert len(wave.json()['peaks']) >= 150
    assert max(wave.json()['peaks']) > .1
    response=client.post(f'/api/projects/{pid}/confirm', json={'lyrics':'Hello\nbeautiful world'})
    assert response.status_code==200, response.text
    lines=response.json()['lines']
    assert len(lines)==2
    settings={'background':'midnight','mode':'line','aspect':'landscape','animation':'pop','fontSize':40}
    response=client.post(f'/api/projects/{pid}/render',json={'settings':settings,'lines':lines})
    assert response.status_code==200, response.text
    jid=response.json()['job_id']
    for _ in range(200):
        job=client.get('/api/jobs/'+jid).json()
        if job['status']!='rendering':break
        time.sleep(.15)
    assert job['status']=='done', job
    video=tmp_path/pid/'lyric_video.mp4'
    assert video.exists() and video.stat().st_size>10000
    assert client.get(f'/api/projects/{pid}/export').status_code==200
