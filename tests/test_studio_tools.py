"""Repurpose, GIF, thumbnail variants, audio enhance and lower thirds: real FFmpeg on synthetic media, measured results."""
import re
import shutil
import subprocess

import pytest
from PIL import Image

import studio_clips as clips
import studio_edit as edit
import studio_tools as tools

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
BRAND = edit.sanitize_brand({"name": "SkellyTune", "accent": "#7CFF6B", "bg": "#101814", "text": "#FFFFFF"})
ENCODE = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-pix_fmt", "yuv420p"]


def flat(image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def run(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def video(path, color="0xC86432", seconds=4, size="320x180", audio=True):
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={size}:r=15:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    run(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), "-shortest", str(path))


def frame(path, t, out):
    run("-ss", str(t), "-i", str(path), "-frames:v", "1", str(out))
    return Image.open(out).convert("RGB")


def loudness(path):
    done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", done.stderr)[-1])


def render(builder, tmp_path, *a, **k):
    args, graph, seconds = builder(*a, **k, script_name="g.txt")
    (tmp_path / "g.txt").write_text(graph)
    subprocess.run(args, cwd=tmp_path, check=True, capture_output=True)
    return seconds


# ---- repurpose --------------------------------------------------------------------------------------------------------------
@needs_ffmpeg
@pytest.mark.parametrize("fmt,size", [("portrait", (360, 640)), ("square", (360, 360))])
def test_repurpose_fits_the_picture_over_a_darkened_blur(tmp_path, fmt, size):
    src = tmp_path / "in.mp4"
    video(src)
    out = tmp_path / tools.repurpose_name(fmt)
    seconds = render(tools.repurpose_render, tmp_path, src, True, 4.0, size[0], size[1], out, ENCODE)
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == size and info["has_audio"] and info["duration"] == pytest.approx(seconds, abs=.4)
    img = frame(out, 1.0, tmp_path / "f.png")
    centre = img.getpixel((size[0] // 2, size[1] // 2))
    assert all(abs(a - b) <= 14 for a, b in zip(centre, (200, 100, 50))), f"the picture itself should be untouched, got {centre}"
    if fmt == "portrait":
        corner = img.getpixel((4, 4))  # background: darkened to about 55 percent
        assert all(abs(a - b) <= 14 for a, b in zip(corner, (110, 55, 28))), corner
    assert tools.repurpose_name("portrait") == "autoedit_9x16.mp4" and tools.repurpose_name("square") == "autoedit_1x1.mp4"


@needs_ffmpeg
def test_repurpose_handles_silent_sources_and_odd_aspect(tmp_path):
    src = tmp_path / "in.mp4"
    video(src, audio=False, size="400x160")
    out = tmp_path / "o.mp4"
    render(tools.repurpose_render, tmp_path, src, False, 4.0, 360, 640, out, ENCODE)
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (360, 640) and not info["has_audio"]


# ---- GIF --------------------------------------------------------------------------------------------------------------------
def test_gif_settings_are_clamped_to_sensible_values():
    s = tools.gif_settings(-5, 99, 500, 100, duration=30)
    assert s == {"start": 0.0, "seconds": 12.0, "width": 480, "fps": 20}
    short = tools.gif_settings(28, 10, 1200, 2, duration=30)
    assert short["start"] == 28 and short["seconds"] == 2.0 and short["width"] == 960 and short["fps"] == 6
    assert tools.gif_settings("x", None, None, None, duration=3)["seconds"] == 3.0
    tries = list(tools.gif_attempts({"start": 0, "seconds": 5, "width": 480, "fps": 12}))
    assert [t["width"] for t in tries] == [480, 320, 240, 240] and [t["fps"] for t in tries] == [12, 9, 6, 6]


@needs_ffmpeg
def test_gif_is_a_looping_palette_gif_of_the_requested_window(tmp_path):
    src = tmp_path / "in.mp4"
    run("-f", "lavfi", "-i", "testsrc=s=320x180:r=15:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
    settings = tools.gif_settings(1, 3, 240, 10, duration=6)
    out = tmp_path / "p.gif"
    subprocess.run(tools.gif_args(src, settings, out), check=True, capture_output=True)
    gif = Image.open(out)
    assert gif.format == "GIF" and gif.size == (240, 136) and gif.info.get("loop") == 0
    assert 28 <= gif.n_frames <= 31 and out.stat().st_size < tools.GIF_MAX_BYTES
    assert len(gif.getpalette()) > 30, "a real palette, not the default 216-color one only"


# ---- thumbnails ---------------------------------------------------------------------------------------------------------------
def test_thumbnail_times_are_three_different_moments():
    for duration, best in ((120, 40), (30, 29.9), (10, .0), (2, 1)):
        times = tools.thumbnail_times(duration, best)
        assert len(times) == 3 and all(.2 <= t <= max(.5, duration - .5) for t in times)
    spread = tools.thumbnail_times(120, 40)
    assert len(set(spread)) == 3 and min(abs(a - b) for a in spread for b in spread if a != b) > 10


def test_thumbnail_variants_are_distinct_valid_jpegs(tmp_path):
    frame_png = tmp_path / "frame.png"
    Image.effect_mandelbrot((640, 360), (-2.2, -1.2, 1.0, 1.2), 40).convert("RGB").save(frame_png)
    outs = {}
    for style in tools.THUMB_STYLES:
        outs[style] = tmp_path / f"{style}.jpg"
        tools.render_thumbnail_variant(style, frame_png, outs[style], "Meet SkellyTune: shape your tone in minutes", BRAND, None)
        img = Image.open(outs[style])
        assert img.size == (1280, 720) and img.format == "JPEG" and outs[style].stat().st_size < 2_000_000
    pixels = {k: list(flat(Image.open(v).convert("L").resize((16, 9)))) for k, v in outs.items()}
    assert len({tuple(v) for v in pixels.values()}) == 3, "each layout must look different"
    split = Image.open(outs["split"]).convert("RGB")
    assert split.getpixel((10, 360)) == pytest.approx((16, 24, 20), abs=6), "the split layout has a brand-colored text panel"
    with pytest.raises(ValueError):
        tools.render_thumbnail_variant("nope", frame_png, tmp_path / "x.jpg", "t", BRAND)


# ---- audio enhance -------------------------------------------------------------------------------------------------------------
@needs_ffmpeg
def test_enhance_brings_quiet_audio_to_the_target_and_leaves_the_picture_alone(tmp_path):
    quiet = tmp_path / "quiet.mp4"
    run("-f", "lavfi", "-i", "color=c=0x336699:s=320x180:r=15:d=8", "-f", "lavfi", "-i",
        "aevalsrc='0.02*sin(2*PI*220*t)*(1+sin(2*PI*1.5*t))+0.005*sin(2*PI*5000*t)':d=8:s=48000", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(quiet))
    assert loudness(quiet) < -30
    out = tmp_path / "enhanced.mp4"
    subprocess.run(tools.enhance_args(quiet, True, "medium", -14, out), check=True, capture_output=True)
    assert loudness(out) == pytest.approx(-14, abs=1.5)
    before, after = clips.probe_media(quiet), clips.probe_media(out)
    assert (after["width"], after["height"]) == (320, 180) and after["has_audio"] and after["duration"] == pytest.approx(8, abs=.3)
    done = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
    assert "Video: h264" in done
    assert frame(out, 2, tmp_path / "f.png").getpixel((50, 50)) == pytest.approx((51, 102, 153), abs=8)
    assert before["has_audio"]


@needs_ffmpeg
def test_enhance_cleanup_reduces_hum_and_audio_only_input_gives_audio_only_output(tmp_path):
    hum = tmp_path / "hum.wav"
    run("-f", "lavfi", "-i", "aevalsrc='0.3*sin(2*PI*50*t)+0.1*sin(2*PI*300*t)':d=6:s=48000", str(hum))
    out = tmp_path / "clean.m4a"
    subprocess.run(tools.enhance_args(hum, False, "strong", None, out), check=True, capture_output=True)
    info = clips.probe_media(out)
    assert info["has_audio"] and not info["has_video"]

    def band_rms(path, low, high):
        done = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", f"highpass=f={low},lowpass=f={high},astats=metadata=0",
                               "-f", "null", "-"], capture_output=True, text=True).stderr
        return float(re.findall(r"RMS level dB: (-?[\d.]+)", done)[-1])
    assert band_rms(out, 20, 70) < band_rms(hum, 20, 70) - 15, "the 50 Hz hum should drop a lot"
    with pytest.raises(ValueError):
        tools.enhance_args(hum, False, "off", None, out)


# ---- lower thirds ------------------------------------------------------------------------------------------------------------------
def test_lower_third_times():
    assert tools.lower_third_times(1, 5, 0, 60) == [(1.0, 6.0)]
    assert tools.lower_third_times(1, 5, 20, 70) == [(1.0, 6.0), (21.0, 26.0), (41.0, 46.0), (61.0, 66.0)]
    assert len(tools.lower_third_times(0, 4, 8, 600)) == 6, "capped"
    assert tools.lower_third_times(1, 5, 3, 60) == [(1.0, 6.0)], "a repeat shorter than the duration would overlap itself"
    assert tools.lower_third_times(59.5, 5, 0, 60) == [], "nothing when there is less than a second left"
    assert tools.lower_third_times(0, 99, 0, 60) == [(0.0, 10.0)]


def test_lower_third_ass_has_positive_coordinates_escaped_text_and_the_right_times(tmp_path):
    path = tmp_path / "l.ass"
    tools.write_lower_third_ass(path, BRAND, 1280, 720, "Jo {Skelly}\\N Smith", "Founder, SkellyTune", [(1.0, 6.0), (31.0, 36.0)])
    text = path.read_text(encoding="utf-8-sig")
    assert text.count("Dialogue:") == 6 and "0:00:01.00,0:00:06.00" in text and "0:00:31.00,0:00:36.00" in text
    assert "{Skelly}" not in text, "braces must be escaped so they cannot inject ASS override tags"
    drawing = re.search(r"\\p1\}(m [^{]+)", text).group(1)
    assert all(int(n) >= 0 for n in re.findall(r"-?\d+", drawing)), "drawing coordinates must be positive"
    moves = re.findall(r"\\move\((-?\d+),(-?\d+),(-?\d+),(-?\d+)", text)
    assert moves and all(int(m[3]) > 0 for m in moves)
    tools.write_lower_third_ass(path, BRAND, 1280, 720, "Jo", "", [(1.0, 6.0)])
    assert path.read_text(encoding="utf-8-sig").count("Dialogue:") == 2, "no role line when there is no role"


@needs_ffmpeg
def test_lower_third_appears_only_during_its_window(tmp_path):
    src = tmp_path / "in.mp4"
    video(src, color="0x202020", seconds=8, size="640x360")
    ass = tmp_path / "l.ass"
    tools.write_lower_third_ass(ass, BRAND, 640, 360, "Jo Smith", "Founder", tools.lower_third_times(2, 3, 0, 8))
    out = tmp_path / "o.mp4"
    render(tools.lower_third_render, tmp_path, src, "l.ass", True, 8.0, out, ENCODE)
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (640, 360) and info["has_audio"]
    region = (20, 250, 420, 340)

    def changed(t):
        a = frame(src, t, tmp_path / "a.png").crop(region)
        b = frame(out, t, tmp_path / "b.png").crop(region)
        return sum(abs(x - y) for p, q in zip(flat(a), flat(b)) for x, y in zip(p, q)) / (region[2] - region[0]) / (region[3] - region[1])
    assert changed(.5) < 2 and changed(6.5) < 2, "outside the window the picture is untouched"
    assert changed(3.2) > 6, "inside it the lower third is drawn"


# ------------------------------------------------------------------------------------------------ second batch of tools
@needs_ffmpeg
def test_repurpose_fill_crops_instead_of_adding_bars(tmp_path):
    src = tmp_path / "src.mp4"
    run("-f", "lavfi", "-i", "testsrc=s=640x360:r=15:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
    out = tmp_path / "fill.mp4"
    args, graph, _ = tools.repurpose_render(src, False, 2, 360, 640, out, ENCODE, "g.txt", fit="fill")
    (tmp_path / "g.txt").write_text(graph)
    assert "boxblur" not in graph and "crop=360:640" in graph
    subprocess.run([a for a in args if a not in ("-progress", "pipe:1")], cwd=tmp_path, check=True)
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (360, 640)
    # testsrc has a bright bar pattern across the full width: with a crop the middle is picture all the way down, no dark bands
    img = frame(out, 1, tmp_path / "f.png")
    top, bottom = img.getpixel((180, 8)), img.getpixel((180, 631))
    assert max(top) > 60 and max(bottom) > 60, "no black bar at the top or bottom"


def test_speed_chain_covers_the_whole_range_and_clamps():
    assert tools.atempo_chain(1.0) == ["atempo=1.00000"]
    assert tools.atempo_chain(4.0) == ["atempo=2.00000", "atempo=2.00000"]
    assert tools.atempo_chain(.25) == ["atempo=0.50000", "atempo=0.50000"]
    assert all(.5 <= float(x.split("=")[1]) <= 2 for f in (.3, .7, 1.5, 3, 3.9) for x in tools.atempo_chain(f))
    assert tools.clean_speed(99) == 4.0 and tools.clean_speed(0) == .25 and tools.clean_speed("junk") == 1.0 and tools.clean_speed(float("nan")) == 1.0


@needs_ffmpeg
@pytest.mark.parametrize("factor,expected", [(2.0, 2.0), (.5, 8.0), (4.0, 1.0)])
def test_speed_changes_the_length_and_keeps_pitch(tmp_path, factor, expected):
    src = tmp_path / "s.mp4"
    video(src, seconds=4)
    out = tmp_path / "o.mp4"
    subprocess.run(tools.speed_args(src, True, factor, out), check=True)
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(expected, abs=.35) and info["has_audio"]


def test_trim_settings_validate():
    assert tools.trim_settings(2, 0, 10) == {"start": 2.0, "end": 10.0, "seconds": 8.0}
    assert tools.trim_settings(-5, 99, 10)["start"] == 0.0 and tools.trim_settings(1, 99, 10)["end"] == 10.0
    assert tools.trim_settings(20, 0, 10)["start"] == 9.5
    with pytest.raises(ValueError):
        tools.trim_settings(5, 5.2, 10)


@needs_ffmpeg
def test_trim_is_frame_accurate_and_keeps_audio(tmp_path):
    src = tmp_path / "t.mp4"
    video(src, seconds=6)
    out = tmp_path / "o.mp4"
    subprocess.run(tools.trim_args(src, True, tools.trim_settings(1.5, 4.0, 6), out), check=True)
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(2.5, abs=.2) and info["has_audio"] and info["has_video"]


def test_shrink_plan_scales_with_the_budget():
    big = tools.shrink_plan(100, 60, True, 1080)
    small = tools.shrink_plan(8, 120, True, 1080)
    assert big["height"] == 1080 and big["video_bps"] > 5_000_000
    assert small["height"] in (360, 480) and small["target_mb"] == 8
    assert tools.shrink_plan(25, 60, True, 1080, attempt=1)["video_bps"] < tools.shrink_plan(25, 60, True, 1080)["video_bps"]
    assert tools.shrink_plan(25, 60, True, 360)["height"] == 360, "never scales up"
    assert tools.shrink_plan(30, 60, True, 1080)["target_mb"] == 25, "snaps to the nearest offered size"
    with pytest.raises(ValueError, match="cannot fit"):
        tools.shrink_plan(8, 3 * 3600, True, 1080)


@needs_ffmpeg
def test_shrink_lands_under_the_target_size(tmp_path):
    src = tmp_path / "big.mp4"
    run("-f", "lavfi", "-i", "testsrc2=s=1280x720:r=24:d=8", "-f", "lavfi", "-i", "sine=f=330:d=8", "-c:v", "libx264", "-crf", "10",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(src))
    assert src.stat().st_size > 1_500_000
    out = tmp_path / "small.mp4"
    plan = tools.shrink_plan(8, 8, True, 720)
    # an 8 MB budget over 8 s is generous; use a deliberately tight one by shrinking the "duration" the plan believes in
    plan = tools.shrink_plan(8, 8 * 12, True, 720)
    subprocess.run(tools.shrink_args(src, True, plan, 720, out), check=True)
    assert out.stat().st_size < src.stat().st_size * .6
    assert clips.probe_media(out)["has_audio"]


def test_sheet_helpers():
    assert tools.sheet_grid(3, 3) == (3, 3) and tools.sheet_grid(99, 0) == (5, 2) and tools.sheet_grid("x", None) == (3, 3)
    assert tools.sheet_times(100, 4) == [12.5, 37.5, 62.5, 87.5]
    assert [tools.stamp(s) for s in (5, 65, 3725)] == ["0:05", "1:05", "1:02:05"]


@needs_ffmpeg
def test_contact_sheet_has_every_frame_in_a_grid(tmp_path):
    src = tmp_path / "v.mp4"
    run("-f", "lavfi", "-i", "testsrc=s=320x180:r=15:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
    frames = []
    for n, t in enumerate(tools.sheet_times(6, 6)):
        png = tmp_path / f"f{n}.png"
        edit.extract_frame(src, t, png)
        frames.append((png, t))
    out = tmp_path / "sheet.jpg"
    width, height = tools.render_contact_sheet(frames, out, 3, "My *demo*", 6, BRAND, cell_w=240)
    img = Image.open(out)
    assert img.size == (width, height) == (14 + 3 * 254, 96 + 2 * (134 + 14))
    bg = tuple(int(BRAND["bg"][i:i + 2], 16) for i in (1, 3, 5))
    cell = img.convert("RGB").crop((14, 96, 14 + 240, 96 + 134))
    assert len(set(flat(cell))) > 50, "a real picture, not a blank cell"


def test_quote_card_sizes_text_and_rejects_empty(tmp_path):
    for aspect, size in (("square", (1080, 1080)), ("portrait", (1080, 1350)), ("landscape", (1280, 720)), ("bogus", (1080, 1080))):
        out = tmp_path / f"{aspect}.png"
        assert tools.render_quote_card(out, "Pitch correction is a tool, not a crutch.", "Skelly", aspect, BRAND) == size
        assert Image.open(out).size == size
    long = tmp_path / "long.png"
    tools.render_quote_card(long, "word " * 200, "", "square", BRAND)  # clipped to the limit and still fits
    assert Image.open(long).size == (1080, 1080)
    with pytest.raises(ValueError):
        tools.render_quote_card(tmp_path / "x.png", "   ", "a", "square", BRAND)
    img = Image.open(tmp_path / "square.png").convert("RGB")
    accent = tuple(int(BRAND["accent"][i:i + 2], 16) for i in (1, 3, 5))
    assert img.getpixel((500, 5)) == accent, "accent bar across the top"
    assert len(set(flat(img))) > 10


# ------------------------------------------------------------------------------------------------ third batch of tools
def test_fade_settings_clamp_and_never_overlap():
    assert tools.fade_settings(1, 1, 10) == {"fade_in": 1.0, "fade_out": 1.0, "seconds": 10}
    assert tools.fade_settings(99, 0, 10)["fade_in"] == 5.0
    s = tools.fade_settings(5, 5, 6)
    assert s["fade_in"] + s["fade_out"] == pytest.approx(6) and s["fade_in"] == s["fade_out"]
    with pytest.raises(ValueError):
        tools.fade_settings(0, 0, 10)
    with pytest.raises(ValueError):
        tools.fade_settings("x", -3, 10)


@needs_ffmpeg
def test_fades_start_and_end_dark_and_silent_but_not_the_middle(tmp_path):
    src = tmp_path / "s.mp4"
    video(src, color="0xC86432", seconds=6)
    out = tmp_path / "o.mp4"
    subprocess.run(tools.fade_args(src, True, tools.fade_settings(1.5, 1.5, 6), out), check=True)
    first, mid, last = (frame(out, t, tmp_path / f"{t}.png") for t in (0, 3, 5.8))
    bright = lambda im: sum(im.getpixel((10, 10)))
    assert bright(first) < 60 and bright(last) < 120 and bright(mid) > 300
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(6, abs=.3) and info["has_audio"]


@needs_ffmpeg
def test_extract_audio_drops_the_picture(tmp_path):
    src = tmp_path / "s.mp4"
    video(src, seconds=3)
    out = tmp_path / "a.m4a"
    subprocess.run(tools.extract_audio_args(src, out), check=True)
    info = clips.probe_media(out)
    assert info["has_audio"] and not info["has_video"] and info["duration"] == pytest.approx(3, abs=.3)


def test_loop_settings_limits():
    assert tools.loop_settings(3, 10) == {"times": 3, "seconds": 30}
    assert tools.loop_settings(1, 10)["times"] == 2 and tools.loop_settings(99, 10)["times"] == 10
    with pytest.raises(ValueError, match="minutes"):
        tools.loop_settings(10, 600)


@needs_ffmpeg
def test_loop_repeats_the_video(tmp_path):
    src = tmp_path / "s.mp4"
    video(src, seconds=2)
    out = tmp_path / "l.mp4"
    subprocess.run(tools.loop_args(src, True, tools.loop_settings(3, 2), out), check=True)
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(6, abs=.4) and info["has_audio"]


@needs_ffmpeg
def test_swap_audio_replaces_the_sound_and_keeps_the_length(tmp_path):
    src = tmp_path / "v.mp4"
    video(src, seconds=4, audio=True)
    track = tmp_path / "t.wav"
    run("-f", "lavfi", "-i", "sine=f=880:d=10", str(track))
    for copy in (True, False):
        out = tmp_path / f"o{copy}.mp4"
        subprocess.run(tools.swap_audio_args(src, track, 4, out, copy), check=True)
        info = clips.probe_media(out)
        assert info["has_video"] and info["has_audio"] and info["duration"] == pytest.approx(4, abs=.3), "a longer track is cut to the video"
