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
