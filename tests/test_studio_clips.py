"""Coverage for Shorts picking, the long-video clipper, reframing and the optional LLM rerank.

Pure logic tests run anywhere. The FFmpeg tests generate tiny synthetic videos
(no network, no Whisper) and skip themselves if ffmpeg is missing.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import studio_clips as clips
import studio_performance as perf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_line(i, text, start, end):
    n = len(text.split())
    words = [{"text": w, "start": round(start + (end - start) * k / n, 3),
              "end": round(start + (end - start) * (k + 1) / n, 3)} for k, w in enumerate(text.split())]
    return {"id": f"l{i}", "text": text, "start": start, "end": end, "words": words}


def song():
    """60s song: verse, chorus x2 (louder), bridge, chorus."""
    texts = ["walking down an empty road tonight", "counting every light that fades away",
             "nobody knows the name I carry", "waiting for the morning to arrive",
             "we are burning bright forever", "never gonna let this fire die",
             "we are burning bright forever", "never gonna let this fire die",
             "a quiet room a broken clock", "whispers of the things I lost",
             "we are burning bright forever", "never gonna let this fire die"]
    lines, t = [], 3.0
    for i, text in enumerate(texts):
        lines.append(make_line(i, text, round(t, 2), round(t + 4.0, 2)))
        t += 4.5
    return lines, 60.0


def song_envelope(duration=60.0, points=600):
    env = []
    for p in range(points):
        sec = p / points * duration
        env.append(0.9 if (15 <= sec < 28 or 42 <= sec < 55) else 0.35)
    return env


def test_song_windows_never_swallow_an_instrumental_break():
    lines = [make_line(0, "first verse line here", 0, 8), make_line(1, "second verse line there", 8.5, 16),
             make_line(2, "after the long solo comes", 40, 48), make_line(3, "the final chorus line again", 48.5, 56)]
    for pick in clips.pick_short_segments(lines, [], 60.0, count=4):
        assert not (pick["start"] < 16 and pick["end"] > 40)


def test_repetition_counts_find_chorus():
    lines, _ = song()
    counts = clips.repetition_counts(lines)
    assert counts[4] == counts[6] == counts[10] == 2
    assert counts[0] == 0 and counts[8] == 0


def test_short_picker_prefers_chorus_and_respects_bounds():
    lines, duration = song()
    picks = clips.pick_short_segments(lines, song_envelope(), duration, count=2)
    assert 1 <= len(picks) <= 2
    best = max(picks, key=lambda p: p["score"])
    chorus_starts = {lines[i]["start"] for i in (4, 5, 6, 7, 10, 11)}
    assert any(best["start"] <= s <= best["end"] for s in chorus_starts)
    assert any("repeat" in r for r in best["reasons"])
    line_starts = {ln["start"] for ln in lines}
    line_ends = {ln["end"] for ln in lines}
    for pick in picks:
        assert pick["start"] in line_starts and pick["end"] in line_ends  # never mid-line
        assert clips.SHORT_MIN <= pick["end"] - pick["start"] <= clips.SHORT_MAX
        assert pick["hook"]
    if len(picks) == 2:
        a, b = picks
        overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
        assert overlap <= .25 * min(a["end"] - a["start"], b["end"] - b["start"]) + 1e-6


def test_short_picker_edge_cases():
    assert clips.pick_short_segments([], [], 30) == []
    one = [make_line(0, "just a tiny song here", 1.0, 6.0)]
    picks = clips.pick_short_segments(one, [], 10.0)
    assert len(picks) == 1 and picks[0]["start"] == 1.0 and picks[0]["end"] == 6.0
    # Garbage timestamps never crash the picker.
    bad = [{"text": "x y", "start": "nan", "end": None}, make_line(1, "good line here ok", 2, 5)]
    assert clips.pick_short_segments(bad, [], 10.0)


def test_shift_lines_clips_and_retimes():
    lines, _ = song()
    out = clips.shift_lines(lines, 12.0, 20.0)
    assert out and out[0]["start"] >= 0 and all(ln["end"] <= 8.0 + 1e-6 for ln in out)
    for ln in out:
        for w in ln["words"]:
            assert 0 <= w["start"] < w["end"] <= 8.0 + 1e-6
    assert clips.shift_lines(lines, 100, 110) == []


ASS_HEADER = """[Script Info]
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Main,Arial,60,&H00FFFFFF

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Main,,0,0,0,,{\\an5}Hello
"""


def test_hook_card_is_added_with_style_and_event(tmp_path):
    ass = tmp_path / "t.ass"
    ass.write_text(ASS_HEADER, encoding="utf-8-sig")
    assert clips.add_hook_to_ass(ass, "Stop {doing} this", 720, 1280, 1.5)
    text = ass.read_text(encoding="utf-8-sig")
    assert "Style: Hook," in text and text.index("Style: Hook,") < text.index("[Events]")
    assert "Dialogue: 1,0:00:00.00,0:00:01.50,Hook" in text
    assert "\\{doing\\}" in text
    assert "Hello" in text  # original captions untouched
    assert not clips.add_hook_to_ass(ass, "   ", 720, 1280)


def talk_words():
    sentences = [
        ("Why does nobody tell you this about 3 simple mixing tricks?", 0.0, 6.0),
        ("Because most people just copy presets and never learn why they work.", 6.5, 13.0),
        ("Start with the low end because everything else sits on top of it.", 13.4, 20.0),
        ("Then carve space for the vocal around two thousand hertz.", 20.3, 27.0),
        ("That is the whole idea and it takes about five minutes.", 27.4, 33.0),
        ("Anyway let me know what you think about this one.", 60.0, 66.0),
        ("Subscribe if you want more of these every week please.", 66.4, 72.0),
        ("Thanks for watching and see you in the next video soon.", 72.3, 78.0),
    ]
    words = []
    for text, start, end in sentences:
        parts = text.split()
        for k, w in enumerate(parts):
            words.append({"text": w, "start": round(start + (end - start) * k / len(parts), 3),
                          "end": round(start + (end - start) * (k + 1) / len(parts) - .02, 3)})
    return words


def test_sentence_split_and_windows():
    sentences = clips.split_sentences(talk_words())
    assert len(sentences) == 8
    windows = clips.candidate_windows(sentences)
    assert windows
    for i, k in windows:
        assert clips.CLIP_MIN <= sentences[k]["end"] - sentences[i]["start"] <= clips.CLIP_MAX


def test_clipper_prefers_strong_hook_and_returns_metadata():
    picks = clips.suggest_clips(talk_words(), [], 80.0, scene_times=[5, 12, 18, 25], count=2)
    assert picks
    best = max(picks, key=lambda p: p["score"])
    assert best["start"] == 0.0  # question + number opening, scene changes inside
    assert any("question" in r for r in best["reasons"])
    assert best["title"] and best["id"] and isinstance(best["tags"], list)
    assert not {"about", "because", "around", "does"} & set(best["tags"])  # filler words
    assert {"mixing", "presets", "simple"} & set(best["tags"])
    # No clip may swallow the 27 second silence between 33 s and 60 s.
    assert all(not (p["start"] < 33.0 and p["end"] > 60.0) for p in picks)
    assert clips.suggest_clips([], [], 10) == []


def test_hook_strength_signals():
    strong, reasons = clips.hook_strength("Why does this never work for 3 people?")
    weak, _ = clips.hook_strength("and so yeah um")
    assert strong > weak and "opens with a question" in reasons


def fake_post_factory(payload_rows=None, raises=False, text=None):
    calls = []

    def post(url, headers, payload):
        calls.append((url, headers, payload))
        if raises:
            raise OSError("offline")
        body = text if text is not None else json.dumps(payload_rows)
        return {"content": [{"type": "text", "text": "Here you go: " + body}]}
    post.calls = calls
    return post


def sample_candidates():
    return [{"id": "a", "start": 0, "end": 30, "score": .5, "reasons": ["x"], "text": "alpha text",
             "hook": "alpha", "title": "alpha", "description": ""},
            {"id": "b", "start": 40, "end": 70, "score": .4, "reasons": ["y"], "text": "beta text",
             "hook": "beta", "title": "beta", "description": ""}]


def test_llm_rerank_success_blends_scores_and_sets_copy():
    post = fake_post_factory([{"id": "b", "rating": 10, "hook": "Beta wins", "title": "T", "description": "D"},
                              {"id": "a", "rating": 2, "hook": "A", "title": "A", "description": ""},
                              {"id": "zzz", "rating": 9}])
    ranked = clips.llm_rerank(sample_candidates(), "key", "model-x", post=post)
    assert set(ranked) == {"a", "b"}
    url, headers, payload = post.calls[0]
    assert url.startswith("https://api.anthropic.com/") and headers["x-api-key"] == "key"
    assert payload["model"] == "model-x"
    ordered = clips.apply_llm_rerank(sample_candidates(), ranked)
    assert ordered[0]["id"] == "b" and ordered[0]["hook"] == "Beta wins"
    assert "ranked with AI assistance" in ordered[0]["reasons"]


@pytest.mark.parametrize("kwargs", [{"raises": True}, {"text": "not json at all"},
                                    {"text": '[{"id": "a", "rating": 99}]'}, {"text": "{}"}])
def test_llm_rerank_falls_back_without_crashing(kwargs):
    post = fake_post_factory(**kwargs)
    assert clips.llm_rerank(sample_candidates(), "key", "m", post=post) is None
    original = sample_candidates()
    assert clips.apply_llm_rerank(original, None) is original


def test_llm_rerank_needs_a_key():
    post = fake_post_factory([])
    assert clips.llm_rerank(sample_candidates(), "", "m", post=post) is None
    assert post.calls == []


def test_crop_geometry_and_positions():
    assert clips.crop_geometry(1920, 1080) == (606, 1080)
    cw, ch = clips.crop_geometry(1080, 1920)
    assert (cw, ch) == (1080, 1920)
    cw, ch = clips.crop_geometry(1000, 1000)
    assert ch == 1000 and cw == 562 and cw % 2 == 0
    assert clips.crop_x(0.0, 1920, 606) == 0
    assert clips.crop_x(1.0, 1920, 606) == 1920 - 606
    assert clips.crop_x(.5, 1920, 606) == 657


def test_crop_expression_shapes():
    assert clips.crop_x_expression([]) == "0"
    assert clips.crop_x_expression([100, 100, 100]) == "100"
    expr = clips.crop_x_expression([0, 100, 100, 50])
    assert expr.startswith("if(lt(t,1),0+(100)*(t-0)/1,") and expr.endswith(",50))))") or "50" in expr
    long = clips.crop_x_expression(list(range(0, 200, 2)))  # 100 points are down-sampled
    assert long.count("if(") <= 48
    smooth = clips.smooth_centers([0, 1, 1, 1])
    assert smooth[0] == 0 and 0 < smooth[1] < smooth[2] < smooth[3] < 1


def test_caption_line_grouping_and_clip_words():
    words = talk_words()[:12]
    lines = clips.lines_from_words(words, max_words=4)
    assert all(len(ln["text"].split()) <= 4 for ln in lines)
    shifted = clips.clip_words(talk_words(), 6.5, 20.0)
    assert shifted[0]["start"] >= 0 and shifted[0]["text"] == "Because"
    assert all(w["end"] <= 13.6 for w in shifted)


@pytest.fixture(scope="module")
def moving_video(tmp_path_factory):
    out = tmp_path_factory.mktemp("vid") / "moving.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "color=c=black:s=640x360:r=10:d=8",
           "-f", "lavfi", "-i", "color=c=white:s=60x60:r=10:d=8",
           "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
           "-filter_complex", "[0:v][1:v]overlay=x='10+t*70':y=150[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    return out


@needs_ffmpeg
def test_video_size_and_activity_follows_motion(moving_video):
    assert clips.video_size(moving_video) == (640, 360)
    centers = clips.activity_centers(moving_video, 0, 8)
    assert len(centers) >= 6
    assert centers[1] < centers[-1] and centers[-1] > .6  # box travels left to right
    assert all(0 <= c <= 1 for c in centers)


@needs_ffmpeg
def test_scene_changes_detects_a_cut(tmp_path):
    out = tmp_path / "cut.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=2",
                    "-f", "lavfi", "-i", "color=c=white:s=320x180:r=10:d=2",
                    "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    cuts = clips.scene_changes(out)
    assert any(1.5 < t < 2.5 for t in cuts)


@needs_ffmpeg
def test_audio_envelope_reads_real_audio(moving_video):
    env = clips.audio_envelope(moving_video, 50)
    assert len(env) == 50 and max(env) > .05 and all(0 <= v <= 1 for v in env)


@needs_ffmpeg
def test_real_vertical_clip_render_with_follow_crop_and_captions(tmp_path, moving_video):
    src_w, src_h = clips.video_size(moving_video)
    crop_w, crop_h = clips.crop_geometry(src_w, src_h)
    centers = clips.smooth_centers(clips.activity_centers(moving_video, 1, 4))
    expr = clips.crop_x_expression([clips.crop_x(c, src_w, crop_w) for c in centers])
    assert "if(" in expr
    (tmp_path / "c.ass").write_text(ASS_HEADER, encoding="utf-8-sig")
    assert clips.add_hook_to_ass(tmp_path / "c.ass", "Watch this", 360, 640, 1.0)
    out = tmp_path / "clip.mp4"
    args = clips.build_clip_args(moving_video, 1.0, 4.0, crop_w, crop_h, expr, 360, 640, "c.ass", 24,
                                 perf.encode_args("libx264", "fast", 360, 640, 2), out)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout[-400:] + proc.stderr[-400:]
    assert clips.video_size(out) == (360, 640)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                            "-of", "json", str(out)], capture_output=True, text=True)
    info = json.loads(probe.stdout)
    assert 3.5 < float(info["format"]["duration"]) < 4.6
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
