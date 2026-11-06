"""Regression coverage for precision-sync and template upgrades."""
from pathlib import Path

from server import ANIMATIONS, PRESETS, animation_tags, create_ass, sanitize_settings, validate_lines


def test_new_scenes_and_pulse_are_supported():
    assert {"sunset", "arctic"}.issubset(PRESETS)
    assert "pulse" in ANIMATIONS
    settings = sanitize_settings({
        "background": "arctic", "animation": "pulse", "mode": "karaoke",
        "aspect": "portrait", "resolution": "1080p",
    })
    assert settings["background"] == "arctic"
    assert settings["animation"] == "pulse"
    assert settings["resolution"] == "1080p"
    assert r"\fad" in animation_tags("pulse", 720, 1280, 650)


def test_explicit_word_times_survive_server_validation():
    lines = validate_lines([{
        "id": "line1", "text": "a bright sky", "start": 1.0, "end": 3.0,
        "words": [
            {"text": "a", "start": 1.0, "end": 1.25},
            {"text": "bright", "start": 1.28, "end": 2.1},
            {"text": "sky", "start": 2.12, "end": 2.9},
        ],
    }], duration=5.0)
    assert [word["start"] for word in lines[0]["words"]] == [1.0, 1.28, 2.12]
    assert [word["end"] for word in lines[0]["words"]] == [1.25, 2.1, 2.9]


def test_pulse_export_uses_word_onsets(tmp_path: Path):
    settings = sanitize_settings({"animation": "pulse", "mode": "line"})
    rows = validate_lines([{
        "id": "clip", "text": "hello world", "start": 1.0, "end": 2.5,
        "words": [
            {"text": "hello", "start": 1.0, "end": 1.5},
            {"text": "world", "start": 1.72, "end": 2.4},
        ],
    }], duration=4.0)
    output = tmp_path / "pulse.ass"
    create_ass(rows, settings, 720, 1280, output)
    ass = output.read_text(encoding="utf-8-sig")
    assert r"\t(0,65,\fscx108\fscy108)" in ass
    assert r"\t(720,785,\fscx108\fscy108)" in ass
    assert "hello world" in ass
