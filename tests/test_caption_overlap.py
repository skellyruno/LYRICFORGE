"""Regression tests for lyrics that flash briefly during export."""
from pathlib import Path
import server


def test_overlap_is_trimmed_and_short_flash_suppressed(tmp_path: Path) -> None:
    source = [
        {"start": 0.5, "end": 3.0, "text": "Old lyric",
         "words": [{"text": "Old", "start": 0.5, "end": 1.0}]},
        {"start": 2.0, "end": 2.06, "text": "Stray flash", "words": []},
        {"start": 2.06, "end": 4.0, "text": "Correct lyric",
         "words": [{"text": "Correct", "start": 2.06, "end": 3.0}]},
    ]
    stable = server.prepare_render_lines(source)
    assert [x["text"] for x in stable] == ["Old lyric", "Correct lyric"]
    assert stable[0]["end"] == 2.0
    assert source[0]["end"] == 3.0  # Saved project data untouched
    output = tmp_path / "captions.ass"
    server.create_ass(source, server.sanitize_settings({"animation": "pop"}),
                      720, 1280, output)
    lines = [line for line in output.read_text(encoding="utf-8-sig").splitlines()
             if line.startswith("Dialogue:")]
    assert len(lines) == 2
    assert "0:00:02.00" in lines[0]
    assert not any("Stray flash" in line for line in lines)


def test_no_changes_to_clean_caption_sequence() -> None:
    lines = [{"start": 1.0, "end": 2.5, "text": "One", "words": []},
             {"start": 2.5, "end": 4.0, "text": "Two", "words": []}]
    result = server.prepare_render_lines(lines)
    assert [(line["start"], line["end"]) for line in result] == [(1.0, 2.5), (2.5, 4.0)]
