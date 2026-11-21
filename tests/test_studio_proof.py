"""Transcript proofreading: low-confidence words and safe corrections that keep timing."""
import pytest

import studio_proof as proof


def w(text, start, end, prob=.95):
    return {"text": text, "start": start, "end": end, "probability": prob}


WORDS = [w("Open", 0, .4), w("the", .4, .6), w("scaly", .7, 1.1, .31), w("tune,", 1.1, 1.5, .28), w("window", 1.6, 2.0),
         w("and", 2.1, 2.3), w("turn", 2.3, 2.6, .55), w("it", 2.6, 2.7), w("up.", 2.7, 3.0)]


def test_uncertain_words_come_back_with_context_in_order():
    rows = proof.uncertain_words(WORDS, threshold=.6)
    assert [r["i"] for r in rows] == [2, 3, 6]
    assert rows[0]["text"] == "scaly" and rows[0]["before"] == "Open the" and rows[0]["after"].startswith("tune,")
    assert rows[1]["prob"] == .28
    assert proof.uncertain_words(WORDS, threshold=.3)[0]["text"] == "tune,"
    assert len(proof.uncertain_words(WORDS, threshold=.99, limit=2)) == 2
    assert proof.uncertain_words([{"text": "..."}, {"text": "?", "probability": .1}]) == []  # punctuation only, no data


def test_single_word_edit_keeps_timing_and_marks_confidence():
    out, n = proof.apply_edits(WORDS, edits=[{"i": 6, "text": "TURN"}])
    assert n == 1 and out[6] == {"text": "TURN", "start": 2.3, "end": 2.6, "probability": 1.0, "edited": True}
    assert WORDS[6]["text"] == "turn"  # the input list is never mutated
    again = proof.uncertain_words(out, threshold=.99)
    assert all(r["i"] != 6 for r in again)  # a fixed word is not flagged again
    assert proof.apply_edits(WORDS, edits=[{"i": 6, "text": "turn"}])[1] == 0  # no-op edits are not counted


def test_split_and_delete_edits_share_the_slot_and_do_not_shift_each_other():
    out, n = proof.apply_edits(WORDS, edits=[{"i": 2, "text": "Skelly Tune"}, {"i": 0, "text": ""}, {"i": 8, "text": "up!"}])
    assert n == 3 and [x["text"] for x in out][:4] == ["the", "Skelly", "Tune", "tune,"]
    skelly, tune = out[1], out[2]
    assert skelly["start"] == .7 and tune["end"] == 1.1 and skelly["end"] == pytest.approx(tune["start"], abs=.001)
    assert skelly["end"] - skelly["start"] > .1 and out[-1]["text"] == "up!"
    starts = [x["start"] for x in out]
    assert starts == sorted(starts)


def test_replacements_work_across_words_keep_punctuation_and_ignore_case():
    out, n = proof.apply_edits(WORDS, replacements=[{"find": "Scaly Tune", "with": "SkellyTune"}])
    assert n == 1 and [x["text"] for x in out][2:4] == ["SkellyTune,", "window"]
    assert out[2]["start"] == .7 and out[2]["end"] == 1.5  # spans both original words
    same, n = proof.apply_edits(WORDS, replacements=[{"find": "scaly tune", "with": "X", "case": True}])
    assert n == 1  # lower-case matches exactly
    none, n = proof.apply_edits(WORDS, replacements=[{"find": "Scaly Tune", "with": "X", "case": True}])
    assert n == 0 and [x["text"] for x in none] == [x["text"] for x in WORDS]
    gone, n = proof.apply_edits(WORDS, replacements=[{"find": "the", "with": ""}])
    assert n == 1 and "the" not in [x["text"] for x in gone]
    multi, _ = proof.apply_edits(WORDS, replacements=[{"find": "turn it", "with": "crank it up a bit"}])
    assert [x["text"] for x in multi][6:10] == ["crank", "it", "up", "a"]


def test_bad_input_is_ignored_and_text_is_cleaned():
    out, n = proof.apply_edits(WORDS, edits=[{"i": 99, "text": "x"}, {"i": -1, "text": "x"}, {"i": "2", "text": "x"}, "junk",
                                             {"i": 4, "text": "  wind\x00ow\n\tpane  "}],
                               replacements=[{"find": "", "with": "x"}, "junk", {"find": "   ", "with": "y"}])
    assert n == 1 and [x["text"] for x in out][4:6] == ["wind", "ow"] or out[4]["text"].startswith("wind")
    long, _ = proof.apply_edits(WORDS, edits=[{"i": 0, "text": "x" * 500}])
    assert len(long[0]["text"]) == proof.MAX_WORD
    dup, n = proof.apply_edits(WORDS, edits=[{"i": 0, "text": "A"}, {"i": 0, "text": "B"}])
    assert n == 1 and dup[0]["text"] in ("A", "B")
    big = [{"i": 0, "text": str(k)} for k in range(2000)]
    assert proof.apply_edits(WORDS, edits=big)[1] <= 1
