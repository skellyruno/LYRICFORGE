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
    """Source builds need import/preview without installing the entire ASR engine."""
    import builtins
    original_import = builtins.__import__

    def missing_av(name, *args, **kwargs):
        if name == "av":
            raise ModuleNotFoundError("No module named 'av'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_av)
    sample = tmp_path / "song.wav"
    with wave.open(str(sample), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * 16000)
    assert server.media_duration(sample) == pytest.approx(1.0, abs=.02)
    image = tmp_path / "bg.png"
    Image.new("RGB", (320, 180)).save(image)
    assert server.video_stream_width(image) == 320
    bad = tmp_path / "corrupt.mp4"
    bad.write_bytes(b"not a media stream")
    with pytest.raises(ValueError):
        server.media_duration(bad)
    with pytest.raises(ValueError):
        server.video_stream_width(bad)


def test_invalid_audio_upload_is_400_and_cleans_partial_project(tmp_path, monkeypatch):
    """Corrupted/renamed media must not create a phantom song in the library."""
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server, "DATA", tmp_path)
    response = TestClient(server.app).post(
        "/api/projects",
        files={"file": ("corrupt.wav", b"not a WAV file", "audio/wav")},
    )
    assert response.status_code == 400, response.text
    assert "Cannot read" in response.json()["detail"]
    assert not any(tmp_path.iterdir())


def test_corrupt_media_when_pyav_is_installed_still_returns_400(tmp_path, monkeypatch):
    """PyAV InvalidDataError must not turn a malformed song into HTTP 500."""
    import sys
    from types import SimpleNamespace
    from fastapi.testclient import TestClient

    class InvalidDataError(Exception):
        pass

    fake_av = SimpleNamespace(open=lambda _: (_ for _ in ()).throw(InvalidDataError("bad container")))
    monkeypatch.setitem(sys.modules, "av", fake_av)
    monkeypatch.setattr(server, "DATA", tmp_path)
    response = TestClient(server.app).post(
        "/api/projects", files={"file": ("bad.wav", b"corrupt", "audio/wav")})
    assert response.status_code == 400, response.text
    assert not list(tmp_path.iterdir())
    bad_background = tmp_path / "bad.png"
    bad_background.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="no readable video"):
        server.video_stream_width(bad_background)
