"""Regression coverage for karaoke pauses in ASS/libass MP4 exports."""
from pathlib import Path
import server


def karaoke_event(tmp_path: Path, words: list[dict]) -> str:
    output = tmp_path / "karaoke.ass"
    server.create_ass(
        [{"text": "Hello world", "start": 0.0, "end": 3.0, "words": words}],
        server.sanitize_settings({"mode": "karaoke", "animation": "none"}),
        720, 1280, output,
    )
    return next(line for line in output.read_text(encoding="utf-8-sig").splitlines()
                if line.startswith("Dialogue:"))


def test_karaoke_preserves_leading_and_between_word_silence(tmp_path):
    event = karaoke_event(tmp_path, [
        {"text": "Hello", "start": 0.5, "end": 1.0},
        {"text": "world", "start": 2.0, "end": 2.5},
    ])
    # ASS \k timing is sequential. Empty time must be a separate syllable
    # with a space glyph, not part of the next word's highlight.
    assert r"{\k50} {\k50}Hello{\k100} {\k50}world" in event
    assert r"{\k150}world" not in event


def test_contiguous_words_add_no_fake_pause(tmp_path):
    event = karaoke_event(tmp_path, [
        {"text": "Hello", "start": 0.0, "end": 1.0},
        {"text": "world", "start": 1.0, "end": 2.0},
    ])
    assert r"{\k100}Hello {\k100}world" in event


def test_overlapping_word_times_do_not_reverse_karaoke_clock(tmp_path):
    event = karaoke_event(tmp_path, [
        {"text": "Hello", "start": 0.1, "end": 1.5},
        {"text": "world", "start": 1.2, "end": 2.3},
    ])
    # Sequential ASS karaoke can't express overlap; clip the second word
    # to the prior syllable's end rather than extending total export timing.
    assert r"{\k10} {\k140}Hello {\k80}world" in event
