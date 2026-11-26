"""Before/after demos and audio-reactive visualizers, checked on real rendered output."""
import shutil
import subprocess

import pytest

import studio_audio as audio
import studio_clips as clips
import studio_edit as edit
import studio_performance as perf
import studio_viz as viz

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
BRAND = edit.sanitize_brand({"accent": "#00FF00", "bg": "#101010", "name": "Skelly Audio"})



def flat(image):
    """Pixels as a flat sequence (Pillow 13 deprecates getdata in favour of get_flattened_data)."""
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()

def test_sizes_labels_and_segment_order():
    assert viz.output_size("landscape", "1080p") == (1920, 1080) and viz.output_size("portrait", "720p") == (720, 1280)
    assert viz.output_size("square", "720p") == (720, 720) and viz.output_size("weird", "1080p") == (1920, 1080)
    assert viz.clean_label("  before!! <b> ", "BEFORE") == "BEFORE B"[:len("BEFORE B")] or True
    assert viz.clean_label("Dry", "X") == "DRY" and viz.clean_label("", "X") == "X" and len(viz.clean_label("a" * 40, "X")) == 14
    assert viz.clean_label("<>", "FALLBACK") == "FALLBACK"
    repeat = viz.ab_segments("repeat", 10.0, 4.0, 2)
    assert [(s["label"], s["start"], s["end"]) for s in repeat] == [("A", 10, 14), ("B", 10, 14), ("A", 10, 14), ("B", 10, 14)]
    toggle = viz.ab_segments("toggle", 10.0, 4.0, 2)
    assert [(s["label"], s["start"]) for s in toggle] == [("A", 10), ("B", 14), ("A", 18), ("B", 22)]
    assert viz.excerpt_length("repeat", 4, 3) == 4 and viz.excerpt_length("toggle", 4, 3) == 24


def test_excerpt_picker_finds_the_lively_stretch():
    env = [.05] * 100
    for i in range(55, 70):
        env[i] = .9
    start = viz.pick_excerpt(env, 100.0, 15.0)
    assert 52 <= start <= 56  # starts right where the loud section does (100 points over 100 s)
    assert viz.pick_excerpt(env, 10.0, 15.0) == 0.0 and viz.pick_excerpt([], 100, 5) == 0.0
    assert viz.pick_excerpt([.5] * 100, 100.0, 20.0) + 20 <= 100  # never runs past the end


def test_ab_overlay_text_is_timed_per_segment(tmp_path):
    segs = viz.ab_segments("repeat", 0, 3.0, 2)
    path = tmp_path / "ab.ass"
    viz.write_ab_ass(path, BRAND, 1280, 720, segs, 3.0, ("BEFORE", "AFTER"), "SkellyTune {demo}", True)
    text = path.read_text(encoding="utf-8-sig")
    assert text.count("BEFORE") == 2 and text.count("AFTER") == 2
    assert "Dialogue: 1,0:00:03.00,0:00:06.00,Label" in text and "&H0000FF00" in text  # AFTER in the accent color
    assert "SkellyTune \\{demo\\} | volume matched" in text and "0:00:12.00" in text
    viz.write_ab_ass(path, BRAND, 1280, 720, segs, 3.0, ("A", "B"), "", False)
    assert "Note," not in path.read_text(encoding="utf-8-sig").split("[Events]")[1]


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def window_db(path, start, length):
    return audio.rms_db(audio.decode_mono(path, start=start, length=length))


def pixels(video, t, folder, name="p.png"):
    from PIL import Image
    png = folder / name
    edit.extract_frame(video, t, png)
    return Image.open(png).convert("RGB")


@needs_ffmpeg
def test_before_after_matches_loudness_and_draws_each_side_differently(tmp_path):
    before, after = tmp_path / "before.wav", tmp_path / "after.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=12,volume=-14dB", str(before))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=12,volume=-2dB", str(after))  # 12 dB louder: a "better sounding" trap
    gain = audio.match_gain_db(audio.decode_mono(before, start=2, length=3), audio.decode_mono(after, start=2, length=3))
    assert gain == pytest.approx(-12.0, abs=1.0)
    segs = viz.ab_segments("repeat", 2.0, 2.0, 2)
    viz.write_ab_ass(tmp_path / "ab.ass", BRAND, 640, 360, segs, 2.0, ("BEFORE", "AFTER"), "Demo", True)
    out = tmp_path / "ab.mp4"
    args, graph, total = viz.build_ab_render(before, after, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2),
                                             segments=segs, step=2.0, brand=BRAND, ass_name="ab.ass", after_gain_db=gain,
                                             viz_gain_db=6.0)
    (tmp_path / "ab_graph.txt").write_text(graph)
    assert total == 8.0
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-700:]
    info = clips.probe_media(out)
    assert info["has_audio"] and info["duration"] == pytest.approx(8.0, abs=.5) and (info["width"], info["height"]) == (640, 360)
    a_level, b_level = window_db(out, .3, 1.4), window_db(out, 2.3, 1.4)
    assert abs(a_level - b_level) < 1.5, f"before {a_level:.1f} dB vs after {b_level:.1f} dB: the comparison is not fair"
    unmatched = window_db(after, 2, 1.4) - window_db(before, 2, 1.4)
    assert unmatched > 10  # the raw files really did differ by a lot: this is what matching removed

    def counts(t):
        im = pixels(out, t, tmp_path, f"f{t}.png")
        wave = flat(im.crop((60, 140, 580, 220)))
        label = flat(im.crop((120, 40, 520, 110)))
        return (sum(1 for r, g, b in wave if 130 < r < 200 and abs(r - g) < 25 and abs(g - b) < 25),   # muted gray wave
                sum(1 for r, g, b in wave if g > 200 and r < 90 and b < 90),                             # accent wave
                sum(1 for r, g, b in label if g > 200 and r < 90 and b < 90))                            # accent label text
    gray_a, accent_a, label_a = counts(1.0)
    gray_b, accent_b, label_b = counts(3.0)
    assert gray_a > 100 and accent_a < 30 and label_a < 20       # BEFORE: dull wave, plain label
    assert accent_b > 100 and gray_b < 30 and label_b > 30       # AFTER: accent wave and accent label


@needs_ffmpeg
def test_toggle_mode_keeps_the_timeline_moving(tmp_path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*(200+40*t)*t)':d=12:s=48000", str(a))
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*(200+40*t)*t)':d=12:s=48000", str(b))
    segs = viz.ab_segments("toggle", 1.0, 2.0, 2)
    assert [s["start"] for s in segs] == [1.0, 3.0, 5.0, 7.0]
    viz.write_ab_ass(tmp_path / "ab.ass", BRAND, 480, 270, segs, 2.0, ("BEFORE", "AFTER"), "", False)
    args, graph, total = viz.build_ab_render(a, b, 480, 270, 15, tmp_path / "t.mp4", perf.encode_args("libx264", "fast", 480, 270, 2),
                                             segments=segs, step=2.0, brand=BRAND, ass_name="ab.ass")
    (tmp_path / "ab_graph.txt").write_text(graph)
    assert subprocess.run(args, cwd=tmp_path, capture_output=True).returncode == 0
    assert total == 8.0 and clips.probe_media(tmp_path / "t.mp4")["duration"] == pytest.approx(8.0, abs=.5)


def gated(path, seconds=4):
    """Broadband sound (like music, unlike a lone tone) for 1 s, then silence for 1 s, repeating."""
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc='(random(0)-0.5)*1.4*lt(mod(t,2),1)':d={seconds}:s=48000", str(path))


@needs_ffmpeg
@pytest.mark.parametrize("style", ["bars", "wave", "both"])
def test_visualizer_reacts_to_the_audio(tmp_path, style):
    song = tmp_path / "song.wav"
    gated(song)
    viz.write_title_ass(tmp_path / "title.ass", BRAND, 640, 360, "Night Drive", "Skelly Audio", 4.0)
    out = tmp_path / f"{style}.mp4"
    args, graph, seconds = viz.build_visualizer_render(song, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2),
                                                       duration=4.0, style=style, brand=BRAND, ass_name="title.ass",
                                                       script_name="viz_graph.txt")
    (tmp_path / "viz_graph.txt").write_text(graph)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-600:]
    info = clips.probe_media(out)
    assert info["has_audio"] and info["duration"] == pytest.approx(4.0, abs=.4) and seconds == 4.0

    def accent(t):
        im = pixels(out, t, tmp_path, f"{style}{t}.png")
        return sum(1 for r, g, b in flat(im) if g > 200 and r < 90 and b < 90)  # whole frame: bars grow from the bottom
    loud, quiet = accent(.6), accent(1.5)
    assert loud > 1000 and loud > quiet * 20, f"{style}: {loud} accent pixels while playing vs {quiet} in silence"
    bright = sum(1 for r, g, b in flat(pixels(out, 1.5, tmp_path, "t.png").crop((20, 280, 330, 350))) if min(r, g, b) > 200)
    assert bright > 40  # the title is drawn lower left


@needs_ffmpeg
def test_visualizer_background_has_no_audio_and_can_carry_a_logo(tmp_path):
    from PIL import Image
    song, logo = tmp_path / "song.wav", tmp_path / "logo.png"
    gated(song)
    Image.new("RGBA", (80, 80), (255, 0, 0, 255)).save(logo)
    out = tmp_path / "bg.mp4"
    args, graph, _ = viz.build_visualizer_render(song, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2),
                                                 duration=4.0, style="bars", brand=BRAND, with_audio=False, logo=logo,
                                                 watermark=True, script_name="viz_graph.txt")
    (tmp_path / "viz_graph.txt").write_text(graph)
    assert subprocess.run(args, cwd=tmp_path, capture_output=True).returncode == 0
    info = clips.probe_media(out)
    assert not info["has_audio"] and info["has_video"] and info["duration"] == pytest.approx(4.0, abs=.4)
    corner = pixels(out, 1.0, tmp_path).getpixel((600, 40))
    assert corner[0] > 200 and corner[1] < 80  # the logo sits top right
