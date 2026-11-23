"""FFprobe-free media probing tests: keep audio imports and backgrounds intact."""
from io import BytesIO
from pathlib import Path
import wave

import pytest
from PIL import Image

import server


def test_wav_duration_without_external_ffprobe(tmp_path, monkeypatch):
    audio = tmp_path / "song.wav"
    with wave.open(str(audio), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 16000)
    # No shell probing allowed; PyAV must read WAV container metadata.
    monkeypatch.setattr(server, "run",
                        lambda *args, **kwargs: (_ for _ in ()).throw(
                            AssertionError("External FFprobe call is forbidden")))
    assert server.media_duration(audio) == pytest.approx(1.0, abs=.02)


@pytest.mark.parametrize("format,extension", [("PNG", ".png"), ("JPEG", ".jpg")])
def test_background_probe_handles_real_images(tmp_path, format, extension):
    picture = tmp_path / ("background" + extension)
    Image.new("RGB", (320, 180), (12, 75, 41)).save(picture, format=format)
    assert server.video_stream_width(picture) == 320


def test_reject_invalid_media_without_using_ffprobe(tmp_path):
    invalid = tmp_path / "corrupt.mp4"
    invalid.write_bytes(b"not a valid video stream")
    with pytest.raises(Exception):
        server.media_duration(invalid)
    with pytest.raises(Exception):
        server.video_stream_width(invalid)


def test_portable_build_excludes_ffprobe_but_retains_ffmpeg_and_av():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/windows-release.yml").read_text(encoding="utf-8")
    assert '--add-binary "vendor/ffmpeg/ffmpeg.exe;tools"' in workflow
    assert '--add-binary "vendor/ffmpeg/ffprobe.exe;tools"' not in workflow
    assert "--collect-all av" in workflow
    launcher = (Path(__file__).resolve().parents[1] / "desktop_launcher.py").read_text()
    assert 'server.media_duration(root / "check.mp4")' in launcher
    assert 'server.video_stream_width(root / "check.mp4")' in launcher

    
def test_source_install_can_probe_with_ffmpeg_only(tmp_path, monkeypatch):
    """The source editor can read media metadata without the AI stack."""
    import builtins
    original_import = builtins.__import__

    def missing_av(name, *args, **kwargs):
        if name == "av":
            raise ModuleNotFoundError("No module named 'av'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_av)
    song = tmp_path / "song.wav"
    with wave.open(str(song), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 16000)
    assert server.media_duration(song) == pytest.approx(1.0, abs=.02)
    bg = tmp_path / "bg.png"
    Image.new("RGB", (320, 180)).save(bg)
    assert server.video_stream_width(bg) == 320
    bad = tmp_path / "corrupt.mp4"
    bad.write_bytes(b"not a media stream")
    with pytest.raises(ValueError):
        server.media_duration(bad)
    with pytest.raises(ValueError):
        server.video_stream_width(bad)


def test_invalid_audio_upload_is_400_and_cleans_partial_project(tmp_path, monkeypatch):
    """Corrupt uploads cannot create half-finished projects."""
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "DATA", tmp_path)
    response = TestClient(server.app).post(
        "/api/projects",
        files={"file": ("corrupt.wav", b"not a WAV file", "audio/wav")},
    )
    assert response.status_code == 400, response.text
    assert "Cannot read" in response.json()["detail"]
    assert not any(tmp_path.iterdir())
