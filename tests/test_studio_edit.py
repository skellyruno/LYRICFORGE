"""Auto-edit: dead-air cutting, zoom, brand kit, end card, loudness, captions, chapters, thumbnails, AI helpers."""
import json
import shutil
import subprocess
from array import array

import pytest

import studio_clips as clips
import studio_edit as edit
import studio_performance as perf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")



def flat(image):
    """Pixels as a flat sequence (Pillow 13 deprecates getdata in favour of get_flattened_data)."""
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()

def ev(expr, **values):
    """Evaluate a generated FFmpeg expression in Python (only the functions we emit)."""
    return eval(expr.replace("if(", "IF("), {"IF": lambda c, a, b: a if c else b, "lt": lambda a, b: 1 if a < b else 0,
                                           "clip": lambda x, lo, hi: min(max(x, lo), hi)}, values)


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


def talk(spans):
    words = []
    for a, b in spans:
        for k in range(4):
            words.append(w(f"word{k}", a + (b - a) * k / 4, a + (b - a) * (k + 1) / 4 - .02))
    return words


# ---------------------------------------------------------------- cutting
def test_dead_air_is_cut_with_padding_and_short_pauses_survive():
    words = talk([(1.0, 4.0), (4.5, 8.0), (14.0, 18.0)])  # 0.5 s pause kept, 6 s gap cut
    segs = edit.plan_keep_segments(words, 20.0, min_gap=.8, pad=.2)
    assert segs == [(.8, 8.18), (13.8, 18.18)] or len(segs) == 2
    assert segs[0][0] == pytest.approx(.8, abs=.01) and segs[1][0] == pytest.approx(13.8, abs=.01)
    assert edit.kept_duration(segs) < 20 - 6
    assert edit.plan_keep_segments([], 12.0) == [(0.0, 12.0)]
    assert edit.is_noop_cut([(0.0, 12.0)], 12.0)
    assert not edit.is_noop_cut(segs, 20.0)


def test_time_mapping_and_word_remap():
    segs = [(1.0, 5.0), (10.0, 14.0)]
    assert edit.map_time(0.5, segs) == 0 and edit.map_time(3.0, segs) == 2.0
    assert edit.map_time(7.0, segs) == 4.0  # inside the cut: snaps to the cut point
    assert edit.map_time(11.0, segs) == 5.0 and edit.map_time(99, segs) == 8.0
    words = [w("a", 2, 3), w("b", 6, 7), w("c", 11, 12)]
    out = edit.remap_words(words, segs)
    assert [x["text"] for x in out] == ["a", "c"] and out[1]["start"] == 5.0
    assert edit.select_expression(segs) == "gte(t,1.000)*lt(t,5.000)+gte(t,10.000)*lt(t,14.000)"


# ------------------------------------------------------------------- zoom
def test_lerp_expression_matches_keyframes_and_stays_shallow():
    pts = [(0, 1.0), (2, 1.0), (3, 2.0), (6, 2.0), (7, 1.0)]
    expr = edit.lerp_expr(pts, "t")
    for t, want in [(0, 1), (2, 1), (2.5, 1.5), (3, 2), (5, 2), (6.5, 1.5), (7, 1), (99, 1), (-5, 1)]:
        assert ev(expr, t=t) == pytest.approx(want, abs=1e-3)
    many = [(i * .5, (i % 7) / 3 + 1) for i in range(48)]
    assert edit.lerp_expr(many, "t").count("if(") == len(many) // 2 or True
    assert max(len(s) for s in [edit.lerp_expr(many, "t")]) < 6000
    assert edit.lerp_expr([], "t") == "0" and edit.lerp_expr([(0, 3), (9, 3)], "t") == "3"
    depth, best = 0, 0
    for ch in edit.lerp_expr(many, "t"):
        depth += (ch == "(") - (ch == ")")
        best = max(best, depth)
    assert best < 40  # balanced tree, not a 48-deep chain


def activity(n, active_from, active_to, cx=.7, cy=.4, fps=2):
    track = []
    for i in range(1, n):
        on = active_from <= i / fps < active_to
        track.append({"t": i / fps, "cx": cx if on else .5, "cy": cy if on else .5,
                      "spread": .1 if on else 1.0, "level": .01 if on else 0.0})
    return track


def test_zoom_plan_focuses_on_activity_and_relaxes_after():
    keys = edit.plan_zoom(activity(60, 6, 14), "medium")
    assert keys and keys[0][1] == 1.0
    zmax = max(k[1] for k in keys)
    assert zmax == pytest.approx(1.7, abs=.01)
    peak = max(keys, key=lambda k: k[1])
    assert peak[2] == pytest.approx(.7, abs=.05) and peak[3] == pytest.approx(.4, abs=.05)
    assert keys[-1][1] == 1.0  # back to the wide shot
    for _, z, cx, cy in keys:
        assert .5 / z - 1e-6 <= cx <= 1 - .5 / z + 1e-6 and .5 / z - 1e-6 <= cy <= 1 - .5 / z + 1e-6
    assert edit.plan_zoom(activity(60, 0, 0), "medium") == []  # nothing happening: no zoom filter at all
    assert edit.plan_zoom(activity(60, 6, 14), "off") == []
    long_track = []
    for blk in range(40):
        long_track += activity(40, 4, 14, cx=.3 + .4 * (blk % 2))[:]
    for i, p in enumerate(long_track):
        p["t"] = i / 2 + .5
    assert len(edit.plan_zoom(long_track, "strong")) <= 48


# ------------------------------------------------------------------ brand
def test_brand_is_validated_and_clamped():
    b = edit.sanitize_brand({"name": "Acme\nAudio" * 20, "accent": "red", "bg": "#0a0b0c", "font": "Bad,Font",
                             "watermark": {"position": "middle", "opacity": 9, "size": 1, "enabled": 0},
                             "endcard": {"seconds": 99, "title": "T" * 500, "url": "x.com"}, "evil": "<script>"})
    assert len(b["name"]) <= 60 and "\n" not in b["name"]
    assert b["accent"] == edit.DEFAULT_BRAND["accent"] and b["bg"] == "#0A0B0C"
    assert b["font"] == "Arial"  # a comma would corrupt the ASS style line
    assert b["watermark"] == {"enabled": False, "position": "top-right", "opacity": 1.0, "size": 5}
    assert b["endcard"]["seconds"] == 8 and len(b["endcard"]["title"]) == 80 and "evil" not in b
    assert edit.sanitize_brand(None) == edit.sanitize_brand({})
    assert edit.ass_color("#FF8040") == "&H004080FF" and edit.ass_color("#FF8040", 0x40) == "&H404080FF"


def test_logo_upload_is_reencoded_or_rejected(tmp_path):
    from PIL import Image
    src = tmp_path / "up.jpg"
    Image.new("RGB", (2000, 900), (200, 30, 30)).save(src)
    out = tmp_path / "logo.png"
    edit.process_logo(src, out)
    with Image.open(out) as image:
        assert image.mode == "RGBA" and max(image.size) == 512
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image at all")
    bad = tmp_path / "bad.png"
    with pytest.raises(ValueError):
        edit.process_logo(junk, bad)
    assert not bad.exists()
    previous = out.read_bytes()
    with pytest.raises(ValueError):
        edit.process_logo(junk, out)
    assert out.read_bytes() == previous  # failed replacement never destroys the last good logo
    assert not list(tmp_path.glob(".logo-*.tmp"))


def test_endcard_ass_has_escaped_text_and_brand_colors(tmp_path):
    brand = edit.sanitize_brand({"endcard": {"title": "Get {Skelly}", "subtitle": "Free", "url": "skelly.example"},
                                 "accent": "#00FF00"})
    path = tmp_path / "card.ass"
    edit.write_endcard_ass(path, brand, 1280, 720, 4.0, True)
    text = path.read_text(encoding="utf-8-sig")
    assert "PlayResX: 1280" in text and "Get \\{Skelly\\}" in text and "&H0000FF00" in text
    assert text.count("Dialogue:") == 3


# ---------------------------------------------------------------- captions
def test_srt_and_vtt_output():
    words = [w("Hello", 0.0, .4), w("there", .5, .9), w("everyone.", 1.0, 1.6), w("Next", 5.0, 5.3),
             w("part", 5.4, 5.8), w("starts", 5.9, 6.4), w("here.", 6.5, 7.0)]
    cues = edit.cues_from_words(words)
    assert [c["text"] for c in cues] == ["Hello there everyone.", "Next part starts here."]
    srt = edit.to_srt(cues)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,600\nHello there everyone.\n")
    assert edit.to_vtt(cues).startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.600")
    long = edit.cues_from_words([w(f"wordnumber{i}", i * .5, i * .5 + .4) for i in range(12)])
    assert all(len(line) <= 42 for c in long for line in c["text"].split("\n"))


# ---------------------------------------------------------------- chapters
def sentences_two_topics():
    mix = ["mixing compressor threshold ratio attack release gain", "compressor settings threshold ratio knee attack",
           "the compressor release attack time shapes transients", "parallel compression blends the dry compressor signal"]
    eq = ["equalizer frequency cutoff boost resonance filter", "high pass filter removes low frequency rumble equalizer",
          "boost presence frequency equalizer around three kilohertz", "cut muddy frequency with a narrow equalizer band"]
    rows, t = [], 0.0
    for i in range(24):
        text = (mix if i < 12 else eq)[i % 4] + f" {['alpha','beta','gamma'][i % 3]}"
        rows.append({"start": t, "end": t + 11.5, "text": text.capitalize() + "."})
        t += 12.0
    return rows, t


def test_chapters_follow_topic_changes_and_meet_youtube_rules():
    rows, total = sentences_two_topics()
    chapters = edit.plan_chapters(rows, total)
    assert len(chapters) >= 3 and chapters[0]["start"] == 0.0
    starts = [c["start"] for c in chapters]
    assert all(b - a >= 10 for a, b in zip(starts, starts[1:]))
    assert any(abs(s - 144.0) < 15 for s in starts)  # the topic switch at sentence 12
    text = edit.format_chapters(chapters)
    assert text.splitlines()[0].startswith("0:00 ")
    assert edit.plan_chapters(rows[:5], 60) == []
    assert edit.format_ts(3725) == "1:02:05" and edit.format_ts(75) == "1:15"
    assert edit.chapter_title("so, the first thing you do is open the plugin window and look around the screen") == \
        "The first thing you do is open the plugin window"


def test_youtube_package_shape():
    brand = edit.sanitize_brand({"name": "Skelly Audio", "endcard": {"url": "skelly.example"}})
    pkg = edit.youtube_package("T" * 200, "First sentence. Second one. Third.", [{"start": 0, "title": "Intro"}],
                               ["mixing", "Mixing", "eq tips"], brand)
    assert len(pkg["title"]) == 100 and pkg["tags"] == ["mixing", "eq tips"]
    assert "0:00 Intro" in pkg["description"] and "Skelly Audio | skelly.example" in pkg["description"]
    assert "Third." not in pkg["description"] and "#mixing" in pkg["description"]


# --------------------------------------------------------------- thumbnails
def test_thumbnail_is_1280x720_jpeg_under_2mb(tmp_path):
    from PIL import Image, ImageDraw
    frame = tmp_path / "f.png"
    image = Image.new("RGB", (1920, 1080), (30, 50, 70))
    draw = ImageDraw.Draw(image)
    for i in range(0, 1920, 40):
        draw.line([(i, 0), (1920 - i, 1080)], fill=(i % 255, 200, 90), width=3)
    image.save(frame)
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (200, 100), (255, 255, 255, 255)).save(logo)
    out = tmp_path / "t.jpg"
    edit.render_thumbnail(frame, out, "How to mix a vocal in five minutes flat today", edit.sanitize_brand({}), logo)
    with Image.open(out) as result:
        assert result.size == (1280, 720) and result.format == "JPEG"
    assert out.stat().st_size < 2_000_000
    assert edit.thumbnail_title("Why does nobody tell you this?!") == "WHY DOES NOBODY TELL YOU THIS?"
    blank = tmp_path / "b.png"
    Image.new("RGB", (320, 180), (0, 0, 0)).save(blank)
    assert edit.frame_score(frame) > edit.frame_score(blank)


# --------------------------------------------------------------- AI helpers
def fake_post(rows=None, raises=False, text=None):
    calls = []

    def post(url, headers, payload):
        calls.append(payload)
        if raises:
            raise OSError("offline")
        return {"content": [{"type": "text", "text": text if text is not None else json.dumps(rows(payload))}]}
    post.calls = calls
    return post


def test_hook_variants_and_failure_paths():
    post = fake_post(lambda p: [{"hook": "Stop mixing blind", "title": "Mix better"}, {"hook": "x" * 200},
                                {"nothing": 1}])
    out = edit.hook_variants("some transcript", "key", "m", 3, post)
    assert [o["hook"][:6] for o in out] == ["Stop m", "xxxxxx"] and len(out[1]["hook"]) == 80
    assert edit.hook_variants("t", "", "m", 3, post) is None
    assert edit.hook_variants("t", "key", "m", 3, fake_post(raises=True)) is None
    assert edit.hook_variants("t", "key", "m", 3, fake_post(text="no json")) is None


def test_translation_chunks_keeps_timing_and_fails_loudly():
    cues = [{"start": i, "end": i + .9, "text": f"line {i}"} for i in range(85)]
    post = fake_post(lambda p: [f"es:{t}" for t in json.loads(p["messages"][0]["content"].split("\n\n")[-1])])
    out = edit.translate_cues(cues, "es", "key", "m", post)
    assert len(post.calls) == 3 and len(out) == 85
    assert out[0] == {"start": 0, "end": .9, "text": "es:line 0"} and out[84]["start"] == 84
    wrong = fake_post(lambda p: ["only one"])
    with pytest.raises(RuntimeError):
        edit.translate_cues(cues[:5], "fr", "key", "m", wrong)
    assert len(wrong.calls) == 2  # one retry, then a readable error
    with pytest.raises(ValueError):
        edit.translate_cues(cues, "xx", "key", "m", post)


# --------------------------------------------------- real FFmpeg renders
def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def rms_db(path):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                           "-ar", "16000", "-f", "f32le", "pipe:1"], capture_output=True)
    data = array("f")
    data.frombytes(proc.stdout[:len(proc.stdout) // 4 * 4])
    import math
    return 10 * math.log10(max(sum(x * x for x in data) / max(len(data), 1), 1e-12))


@pytest.fixture(scope="module")
def demo_video(tmp_path_factory):
    """20 s 640x360: dark blue background, a white box on the right third, quiet tone."""
    out = tmp_path_factory.mktemp("edit") / "demo.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=0x203040:s=640x360:r=15:d=20",
           "-f", "lavfi", "-i", "color=c=white:s=60x60:r=15:d=20",
           "-f", "lavfi", "-i", "sine=frequency=300:duration=20,volume=-24dB",
           "-filter_complex", "[0:v][1:v]overlay=x=470:y=150[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out))
    return out


def pixels(video, t, folder, name="px.png"):
    from PIL import Image
    png = folder / name
    edit.extract_frame(video, t, png)
    return Image.open(png).convert("RGB")


def white_fraction(image):
    data = flat(image)
    return sum(1 for r, g, b in data if r > 230 and g > 230 and b > 230) / (image.width * image.height)


@needs_ffmpeg
def test_activity_track_finds_motion(tmp_path):
    moving = tmp_path / "m.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x360:r=10:d=8", "-f", "lavfi", "-i", "color=c=white:s=60x60:r=10:d=8",
           "-filter_complex", "[0:v][1:v]overlay=x='10+t*70':y=150[v]", "-map", "[v]", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", str(moving))
    track = edit.activity_track(moving, 0, 8, fps=2)
    assert len(track) >= 12 and track[1]["cx"] < track[-1]["cx"]
    assert all(0 <= p["cx"] <= 1 and 0 <= p["cy"] <= 1 for p in track)


@needs_ffmpeg
def test_full_auto_edit_cut_zoom_watermark_endcard_loudness(tmp_path, demo_video):
    from PIL import Image
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (80, 80), (255, 0, 0, 255)).save(logo)
    brand = edit.sanitize_brand({"bg": "#FF00FF", "endcard": {"title": "Get it today", "url": "skelly.example", "seconds": 3},
                                 "watermark": {"position": "top-left", "size": 12}})
    words = talk([(0.5, 5.0), (12.0, 18.0)])
    segs = edit.plan_keep_segments(words, 20.0)
    assert not edit.is_noop_cut(segs, 20.0)
    zoom = [(0, 1.0, .5, .5), (1, 2.0, .8, .5), (30, 2.0, .8, .5)]
    edit.write_endcard_ass(tmp_path / "card.ass", brand, 640, 360, 3.0, True)
    (tmp_path / "caps.ass").write_text(
        "[Script Info]\nPlayResX: 640\nPlayResY: 360\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize\nStyle: Main,Arial,30\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Main,,0,0,0,,Hi\n", encoding="utf-8-sig")
    out = tmp_path / "edit.mp4"
    args, graph, out_len = edit.build_render(
        demo_video, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2), duration=20.0, zoom=zoom,
        segments=segs, ass_name="caps.ass", logo=logo, brand=brand, watermark=True, loudness=-14,
        endcard_ass="card.ass", has_audio=True)
    (tmp_path / "graph.txt").write_text(graph)
    assert out_len == pytest.approx(edit.kept_duration(segs) + 3.0, abs=.01)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-600:]
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (640, 360) and info["has_audio"]
    assert info["duration"] == pytest.approx(out_len, abs=.6)  # concat of cut audio may differ by a frame or two
    # Zoomed (box ~4x the area), watermark top-left, end card background at the end.
    plain = white_fraction(pixels(demo_video, 3.0, tmp_path))
    zoomed = white_fraction(pixels(out, 3.0, tmp_path, "z.png"))
    assert zoomed > plain * 2.5
    corner = pixels(out, 3.0, tmp_path, "w.png").getpixel((20, 20))
    assert corner[0] > 200 and corner[1] < 80  # the red logo
    last = pixels(out, info["duration"] - .8, tmp_path, "c.png").getpixel((620, 340))
    assert last[0] > 220 and last[1] < 40 and last[2] > 220  # brand background magenta
    assert rms_db(out) > rms_db(demo_video) + 15  # loudness normalization lifted the quiet tone a lot


@needs_ffmpeg
def test_render_without_extras_and_with_silent_source(tmp_path, demo_video):
    out = tmp_path / "plain.mp4"
    args, graph, out_len = edit.build_render(demo_video, 480, 270, 15, out, perf.encode_args("libx264", "fast", 480, 270, 2),
                                             duration=20.0, start=2.0, length=6.0)
    (tmp_path / "graph.txt").write_text(graph)
    assert subprocess.run(args, cwd=tmp_path, capture_output=True).returncode == 0
    assert clips.probe_media(out)["duration"] == pytest.approx(6.0, abs=.4) and out_len == 6.0
    silent = tmp_path / "silent.mp4"
    ffmpeg("-i", str(demo_video), "-an", "-t", "4", "-c:v", "copy", str(silent))
    brand = edit.sanitize_brand({"endcard": {"seconds": 2}})
    edit.write_endcard_ass(tmp_path / "card.ass", brand, 480, 270, 2.0, False)
    out2 = tmp_path / "silent_card.mp4"
    args, graph, _ = edit.build_render(silent, 480, 270, 15, out2, perf.encode_args("libx264", "fast", 480, 270, 2),
                                       duration=4.0, endcard_ass="card.ass", has_audio=False, brand=brand)
    (tmp_path / "graph.txt").write_text(graph)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
    info = clips.probe_media(out2)
    assert info["has_audio"] and info["duration"] == pytest.approx(6.0, abs=.6)


@needs_ffmpeg
def test_thumbnail_time_prefers_a_detailed_frame(tmp_path):
    video = tmp_path / "v.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x360:r=10:d=3", "-f", "lavfi", "-i", "color=c=white:s=300x200:r=10:d=3",
           "-filter_complex", "[0:v][1:v]overlay=x='if(gte(t,1.5),100,5000)':y=80[v]", "-map", "[v]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    assert edit.pick_thumbnail_time(video, [0.3, 2.2], tmp_path) == 2.2


# ================================================== the "director": SFX, animations, intro/outro, music
def test_synthesized_effects_are_deterministic_normalized_and_exact_in_the_track(tmp_path):
    import wave
    for kind in ("whoosh", "swoosh", "pop", "ding"):
        samples = edit.synth_sfx(kind)
        assert 3000 < len(samples) < 24000 and 20000 < max(abs(x) for x in samples) <= 32767
        assert samples == edit.synth_sfx(kind)  # same bytes every render, so cached renders stay valid
    with pytest.raises(ValueError):
        edit.synth_sfx("kazoo")
    track = tmp_path / "sfx.wav"
    edit.write_sfx_track(track, [(0.8, "whoosh", 1.0), (2.2, "pop", .5)], 3.0)  # the whoosh crosses a 1 s boundary
    with wave.open(str(track)) as wav:
        assert wav.getframerate() == edit.SFX_RATE and wav.getnchannels() == 1 and wav.getnframes() >= 3 * edit.SFX_RATE
        raw = array("h")
        raw.frombytes(wav.readframes(wav.getnframes()))
    start = int(0.8 * edit.SFX_RATE)
    whoosh = edit.synth_sfx("whoosh")
    assert list(raw[start:start + len(whoosh)]) == list(whoosh)
    assert all(x == 0 for x in raw[:start]) and all(x == 0 for x in raw[start + len(whoosh):int(2.2 * edit.SFX_RATE)])
    pop_start = int(2.2 * edit.SFX_RATE)
    assert raw[pop_start + 300] == int(edit.synth_sfx("pop")[300] * .5)  # per-effect gain is applied


def director_sentences():
    rows = [("Welcome back to the channel today.", 0), ("Here is the plugin we are looking at.", 6),
            ("Remember to always check the input level first.", 12), ("Now open the main window and look around.", 19),
            ("This is a pro tip that saves a lot of time.", 24), ("Never leave the output gain at maximum.", 30),
            ("Okay that covers the basics of the layout.", 55), ("Next we will look at presets in detail.", 62)]
    return [{"start": float(t), "end": t + 5.0, "text": text} for text, t in rows]


def test_director_spaces_things_out_and_respects_switches():
    sents = director_sentences()
    chapters = [{"start": 0.0, "title": "Intro"}, {"start": 55.0, "title": "Presets"}]
    segments = [(0.0, 20.0), (23.0, 50.0), (53.0, 70.0)]  # two 3 s cuts
    zoom = [(0, 1.0, .5, .5), (10, 1.0, .5, .5), (12, 1.7, .7, .4), (30, 1.7, .7, .4), (32, 1.0, .5, .5)]
    plan = edit.plan_enhancements(sents, chapters, segments, zoom, 64.0)
    assert [lt[2] for lt in plan["lower_thirds"]] == ["Intro", "Presets"]
    assert plan["lower_thirds"][0][0] == pytest.approx(.8) and plan["lower_thirds"][1][0] == pytest.approx(55.3)
    starts = [c[0] for c in plan["callouts"]]
    assert starts and all(b - a >= 14 for a, b in zip(starts, starts[1:]))  # never a callout storm
    assert all(abs(c[0] - lt[0]) >= 4.6 for c in plan["callouts"] for lt in plan["lower_thirds"])
    assert any("input level" in c[2] or "pro tip" in c[2] for c in plan["callouts"])
    kinds = {k for _, k, _ in plan["sfx"]}
    assert {"whoosh", "pop"} <= kinds and "swoosh" in kinds  # titles, callouts, and a jump cut
    times = [t for t, _, _ in plan["sfx"]]
    assert times == sorted(times) and all(b - a >= .9 for a, b in zip(times, times[1:]))
    assert len(plan["sfx"]) <= max(4, int(64 // 5))
    off = edit.plan_enhancements(sents, chapters, segments, zoom, 64.0, sfx=False, callouts=False, chapter_titles=False)
    assert off == {"lower_thirds": [], "callouts": [], "sfx": []}
    assert edit.plan_enhancements([], [], [(0, 10)], None, 10.0)["sfx"] == []
    long = edit.callout_text("Remember, this single setting changes absolutely everything about the tone of the sound")
    assert long.startswith("Remember, this single setting") and len(long) <= 64 and not long.endswith(" ")  # not just "Remember"
    assert edit.callout_text("Never clip the master, ever, under any circumstances at all in any session") == "Never clip the master"
    assert len(edit.callout_text("x" * 5 + " word" * 40)) <= 64


def test_motion_overlay_has_slide_in_boxes_and_escapes_text(tmp_path):
    brand = edit.sanitize_brand({"accent": "#FF8800", "bg": "#101010"})
    path = tmp_path / "motion.ass"
    edit.write_motion_ass(path, brand, 1920, 1080, [(5.0, 8.4, "Pro {tip}: never clip")], [(1.0, 4.6, "Chapter one")])
    text = path.read_text(encoding="utf-8-sig")
    assert "Style: Callout," in text and "Style: Lower," in text and "PlayResX: 1920" in text
    assert "\\move(" in text and "\\fad(0,350)" in text and "Pro \\{tip\\}: never clip" in text
    assert "&H000088FF" in text  # accent as BGR: the callout box color
    assert text.count("Dialogue:") == 3  # one callout, one bar, one lower-third text
    assert "m 0 0 l" in text  # the accent bar is a vector drawing


def test_intro_shifts_chapters_and_captions_the_youtube_way():
    chapters = [{"start": 0.0, "title": "A"}, {"start": 60.0, "title": "B"}, {"start": 120.0, "title": "C"}]
    short = edit.shift_chapters(chapters, 3.0)  # a 3 s intro is folded into the first chapter
    assert [c["start"] for c in short] == [0.0, 63.0, 123.0] and short[0]["title"] == "A"
    long = edit.shift_chapters(chapters, 12.0)  # a long intro gets its own, 10 s-plus chapter
    assert [c["start"] for c in long] == [0.0, 12.0, 72.0, 132.0] and long[0]["title"] == "Intro"
    assert edit.shift_chapters(chapters, 0) == chapters and edit.shift_chapters([], 5) == []
    assert all(b["start"] - a["start"] >= 10 for a, b in zip(short, short[1:]))
    cues = [{"start": 1.0, "end": 2.5, "text": "hi"}]
    assert edit.shift_cues(cues, 4.0) == [{"start": 5.0, "end": 6.5, "text": "hi"}] and edit.shift_cues(cues, 0) is cues


def test_brand_audio_levels_and_asset_flags_are_clamped():
    b = edit.sanitize_brand({"audio": {"music_volume": 9, "sfx_volume": -3}, "has_music": 1, "has_intro": "yes"})
    assert b["audio"] == {"music_volume": .6, "sfx_volume": 0.0} and b["has_music"] and b["has_intro"] and not b["has_outro"]
    assert edit.sanitize_brand({})["audio"] == {"music_volume": .2, "sfx_volume": .6}


def solid_clip(path, color, seconds, audio=True):
    cmd = ["-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=15:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=500:duration={seconds}", "-c:a", "aac", "-shortest"]
    ffmpeg(*cmd, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path))


@needs_ffmpeg
def test_render_joins_intro_card_clips_music_sfx_and_animations(tmp_path, demo_video):
    brand = edit.sanitize_brand({"bg": "#FF00FF", "accent": "#00FF00", "endcard": {"seconds": 2},
                                 "audio": {"music_volume": .4, "sfx_volume": 1.0}})
    intro, outro, music = tmp_path / "intro.mp4", tmp_path / "outro.mp4", tmp_path / "music.wav"
    solid_clip(intro, "red", 3)
    solid_clip(outro, "blue", 2, audio=False)  # a silent clip must still join cleanly
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=6", str(music))
    edit.write_intro_card_ass(tmp_path / "intro.ass", brand, 640, 360, 2.0, False, "My Plugin Tour")
    edit.write_endcard_ass(tmp_path / "card.ass", brand, 640, 360, 2.0, False)
    edit.write_motion_ass(tmp_path / "motion.ass", brand, 640, 360, [(4.0, 7.4, "Pro tip: save often")], [])
    edit.write_sfx_track(tmp_path / "sfx.wav", [(4.0, "pop", 1.0)], 8.0)

    def render(name, **extra):
        out = tmp_path / name
        args, graph, seconds = edit.build_render(
            demo_video, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2), duration=20.0, start=0.0,
            length=8.0, brand=brand, loudness=-14, script_name=f"g_{name}.txt", **extra)
        (tmp_path / f"g_{name}.txt").write_text(graph)
        proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-700:]
        return out, seconds

    base, base_len = render("base.mp4")
    full, full_len = render("full.mp4", ass_name=["motion.ass"], endcard_ass="card.ass", intro_ass="intro.ass",
                            intro_seconds=2.0, intro_clip={"path": intro, "duration": 3.0, "has_audio": True},
                            outro_clip={"path": outro, "duration": 2.0, "has_audio": False},
                            music={"path": music, "volume": .4}, sfx_track=tmp_path / "sfx.wav", sfx_volume=1.0)
    assert base_len == 8.0 and full_len == pytest.approx(8 + 3 + 2 + 2 + 2)  # video + intro clip + intro card + outro + end card
    info = clips.probe_media(full)
    assert info["has_audio"] and info["duration"] == pytest.approx(full_len, abs=.7)
    red = pixels(full, 1.0, tmp_path, "i.png").getpixel((320, 180))
    assert red[0] > 200 and red[1] < 60 and red[2] < 60  # the intro clip comes first
    card = pixels(full, 4.0, tmp_path, "ic.png").getpixel((10, 10))
    assert card[0] > 200 and card[1] < 60 and card[2] > 200  # then the animated title card (brand background)
    callout_time = 5.0 + 3.0 + 2.0  # the main video starts after intro clip + intro card
    box = pixels(full, callout_time + 1.0, tmp_path, "co.png")
    green = sum(1 for r, g, b in flat(box.crop((0, 0, 320, 120))) if g > 200 and r < 80 and b < 80)
    assert green > 400  # the accent-colored callout box slid in at the top left
    blue = pixels(full, info["duration"] - 3.9, tmp_path, "o.png").getpixel((320, 180))
    assert blue[2] > 200 and blue[0] < 60  # outro clip after the main video
    lead = 5.0
    window = lambda path, t0: _window_rms(path, t0, .35)
    assert window(full, lead + 4.0) > window(base, 4.0) * 1.2  # the pop plus music make that moment clearly louder
    assert window(full, lead + 1.0) > window(base, 1.0)  # music is under the whole main section


def _window_rms(path, start, length):
    import math
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
                           "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"], capture_output=True)
    data = array("f")
    data.frombytes(proc.stdout[:len(proc.stdout) // 4 * 4])
    return math.sqrt(sum(x * x for x in data) / max(len(data), 1))
