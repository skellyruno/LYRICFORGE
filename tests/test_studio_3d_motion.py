"""The 3D-style logo renderer, livestream scenes, and the kinetic text / countdown templates."""
import math
import shutil
import subprocess

import pytest

import studio_3d as d3
import studio_clips as clips
import studio_edit as edit
import studio_motion as motion
import studio_performance as perf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
BRAND = edit.sanitize_brand({"name": "SkellyTune", "accent": "#00FF00", "bg": "#101010"})


def flat(image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


# ------------------------------------------------------------------------------- the maths
def test_linear_solver_and_perspective_transform_round_trip():
    assert d3.solve([[2, 1], [1, 3]], [5, 10]) == pytest.approx([1, 3])
    with pytest.raises(ValueError):
        d3.solve([[1, 2], [2, 4]], [1, 2])
    from PIL import Image
    img = Image.new("RGB", (100, 80))
    for x in range(100):
        for y in range(80):
            img.putpixel((x, y), (x * 2, y * 3, 50))
    square = [(0, 0), (100, 0), (100, 80), (0, 80)]
    same = img.transform((100, 80), Image.PERSPECTIVE, d3.perspective_coeffs(square, square), Image.BILINEAR)
    assert same.getpixel((40, 30)) == img.getpixel((40, 30))
    shifted = [(10, 5), (110, 5), (110, 85), (10, 85)]  # the picture moved 10 right and 5 down
    moved = img.transform((120, 90), Image.PERSPECTIVE, d3.perspective_coeffs(shifted, square), Image.BILINEAR)
    assert moved.getpixel((50, 35)) == img.getpixel((40, 30))
    skew = [(0, 0), (100, 10), (100, 70), (0, 80)]  # a true perspective (keystone) mapping puts the corners where asked
    c = d3.perspective_coeffs(skew, square)
    for (X, Y), (x, y) in zip(skew, square):
        den = c[6] * X + c[7] * Y + 1
        assert (c[0] * X + c[1] * Y + c[2]) / den == pytest.approx(x, abs=1e-6) and (c[3] * X + c[4] * Y + c[5]) / den == pytest.approx(y, abs=1e-6)


def test_rotation_projection_and_easing():
    x, y, z = d3.rotate((100, 0, 0), math.pi / 2, 0, 0)  # a quarter turn about the vertical axis swings x into depth
    assert (round(x, 6), round(y, 6)) == (0, 0) and abs(z) == pytest.approx(100)
    assert d3.rotate((1, 2, 3), 0, 0, 0) == pytest.approx((1, 2, 3))
    assert d3.project((0, 0, 0), 1000, 640, 360) == (640, 360)
    near, far = d3.project((100, 0, -500), 1000, 0, 0), d3.project((100, 0, 1000), 1000, 0, 0)
    assert near[0] > 100 > far[0]  # closer to the camera looks bigger, farther looks smaller
    assert d3.ease_out(0) == 0 and d3.ease_out(1) == 1 and d3.ease_out(.5) > .5 and d3.smooth(.5) == .5 and d3.smooth(-1) == 0


def test_intro_pose_flies_in_lands_then_floats_and_loops_are_seamless():
    start, landed, later = d3.pose_intro(0.0), d3.pose_intro(1.6), d3.pose_intro(4.0)
    assert start["z"] > 5000 and start["alpha"] == 0 and abs(start["yaw"]) > 8
    assert landed["z"] == pytest.approx(0, abs=1) and abs(landed["yaw"]) < .01 and landed["flash"] > .3 and landed["alpha"] == 1
    assert d3.pose_intro(1.9)["flash"] == 0 or d3.pose_intro(1.9)["flash"] < landed["flash"]
    assert abs(later["yaw"]) < .3 and later["flash"] == 0  # a gentle float, no more flash
    a, b = d3.pose_loop(0.0), d3.pose_loop(d3.LOOP_SECONDS)
    for key in ("yaw", "pitch", "roll", "z"):
        assert a[key] == pytest.approx(b[key], abs=1e-6), f"{key} does not return to its start: the loop would jump"
    assert d3.scene_plan("intro", "T", "s", BRAND)["seconds"] == 5.0 and d3.scene_plan("brb", "", "", BRAND)["loop"] is True
    assert d3.scene_plan("starting", "", "", BRAND)["headline"] == "STARTING SOON"
    with pytest.raises(ValueError):
        d3.scene_plan("nope", "", "", BRAND)
    events = d3.intro_sfx_events()
    assert [e[1] for e in events] == ["riser", "whoosh", "impact", "ding"]
    assert abs(next(t for t, k, _ in events if k == "impact") - 1.6) < .1  # the boom lands with the logo


def test_sound_effects_for_the_stinger_exist():
    for kind in ("impact", "riser"):
        samples = edit.synth_sfx(kind)
        assert 20000 < max(abs(x) for x in samples) <= 32767 and samples == edit.synth_sfx(kind)


# --------------------------------------------------------------------------- real renders
def logo_file(tmp_path, color=(255, 0, 0, 255)):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([20, 20, 280, 280], radius=50, fill=color)
    path = tmp_path / "logo.png"
    img.save(path)
    return path


def frame(video, t, folder, name="f.png"):
    from PIL import Image
    edit.extract_frame(video, t, folder / name)
    return Image.open(folder / name).convert("RGB")


def count(image, test):
    return sum(1 for p in flat(image) if test(p))


@needs_ffmpeg
def test_intro_scene_flies_in_extrudes_and_has_sound(tmp_path):
    logo = logo_file(tmp_path)
    sfx = tmp_path / "sfx.wav"
    edit.write_sfx_track(sfx, [(t, k, g) for t, k, g in d3.intro_sfx_events()], 5.0)
    out = tmp_path / "intro.mp4"
    progress = []
    info = d3.render_scene("intro", out, width=480, height=270, brand=BRAND, logo=logo, title="SKELLYTUNE", subtitle="Live now",
                           sfx_wav=sfx, on_progress=progress.append)
    probe = clips.probe_media(out)
    assert info["frames"] == 150 and probe["duration"] == pytest.approx(5.0, abs=.3) and probe["has_audio"]
    assert (probe["width"], probe["height"]) == (480, 270) and progress and progress[-1] > .9
    red = lambda p: p[0] > 170 and p[1] < 70 and p[2] < 70
    far, landed = count(frame(out, .3, tmp_path), red), count(frame(out, 4.0, tmp_path, "g.png"), red)
    assert landed > 1500 and landed > far * 8, f"the logo should grow as it flies in ({far} -> {landed} pixels)"
    mid = frame(out, 1.0, tmp_path, "m.png")
    assert count(mid, red) > 50  # visible and spinning mid-flight
    title = frame(out, 4.0, tmp_path, "t.png").crop((100, 195, 380, 245))
    assert count(title, lambda p: min(p) > 200) > 80, "the title should be on screen once the logo has landed"
    assert count(frame(out, .3, tmp_path, "e.png").crop((100, 195, 380, 245)), lambda p: min(p) > 200) < 10  # not yet
    boom = frame(out, 1.7, tmp_path, "b.png")
    assert sum(sum(p) for p in flat(boom)) / (480 * 270 * 3) > sum(sum(p) for p in flat(frame(out, 4.0, tmp_path, "c.png"))) / (480 * 270 * 3)  # the flash


@needs_ffmpeg
def test_loop_scene_returns_to_where_it_started_and_a_text_only_badge_works(tmp_path):
    out = tmp_path / "starting.mp4"
    info = d3.render_scene("starting", out, width=320, height=180, brand=BRAND, logo=None, title="SKELLY", subtitle="Back in a minute")
    probe = clips.probe_media(out)
    assert info["loop"] and probe["duration"] == pytest.approx(8.0, abs=.3) and not probe["has_audio"]
    first, last = frame(out, 0.0, tmp_path, "a.png"), frame(out, 7.9, tmp_path, "z.png")
    diff = sum(abs(a - b) for pa, pb in zip(flat(first), flat(last)) for a, b in zip(pa, pb)) / (320 * 180 * 3)
    assert diff < 6, f"first and last frames differ by {diff:.1f}: the loop would visibly jump"
    assert count(first, lambda p: min(p) > 200) > 100  # the big "STARTING SOON" headline and the badge text


# ------------------------------------------------------------------------------ kinetic text
def test_emphasis_and_timing():
    assert motion.parse_words("Turn the *drive* up") == [("Turn", False), ("the", False), ("drive", True), ("up", False)]
    assert motion.parse_words("*two words* here") == [("two", True), ("words", True), ("here", False)]
    assert motion.parse_words("   ") == [] and motion.parse_words("**") == []
    assert motion.line_seconds(motion.parse_words("Hi"), "pop") == 1.8
    assert motion.line_seconds(motion.parse_words("a b c d e f g h"), "pop") > motion.line_seconds(motion.parse_words("a b"), "pop")


@pytest.mark.parametrize("style", motion.STYLES)
def test_each_style_animates_with_timed_tags_and_emphasis(style):
    text, total, sfx = motion.kinetic_script(["Turn the *drive* up", "Then listen"], style, 1280, 720, BRAND)
    dialogue = [l for l in text.splitlines() if l.startswith("Dialogue:")]
    assert len(dialogue) == 2 and "&H0000FF00" in text and sfx and sfx[0][0] == .3
    assert total > sfx[1][0] + 1.5 and sfx[1][0] == pytest.approx(.3 + motion.line_seconds(motion.parse_words("Turn the *drive* up"), style))
    if style == "pop":
        assert text.count("\\t(") >= 8 and "\\fscx112" in text and sfx[0][1] == "pop"
    if style == "slide":
        assert "\\move(640," in text and sfx[0][1] == "swoosh"
    if style == "typewriter":
        assert text.count("\\alpha&HFF&") > 20 and sfx[0][1] == "pop"
    assert "PlayResX: 1280" in text and "Style: Main,Arial," in text


def test_kinetic_validation_and_escaping():
    with pytest.raises(ValueError):
        motion.kinetic_script(["  ", ""], "pop", 640, 360, BRAND)
    text, _, _ = motion.kinetic_script(["Use {braces} and \\ slashes"], "slide", 640, 360, BRAND)
    assert "\\{braces\\}" in text
    many, _, _ = motion.kinetic_script([f"line {i}" for i in range(30)], "pop", 640, 360, BRAND)
    assert many.count("Dialogue:") == 12  # capped
    fallback, _, _ = motion.kinetic_script(["hi"], "bogus", 640, 360, BRAND)
    assert "\\fscx112" in fallback


def test_countdown_numbers_rings_and_go():
    text, total, sfx = motion.countdown_script(3, 1280, 720, BRAND)
    shown = [l.rsplit("}", 1)[-1] for l in text.splitlines() if "\\fs" in l and l.startswith("Dialogue: 2")]
    assert shown == ["3", "2", "1", "GO!"] and text.count("\\p1") == 3 and total == pytest.approx(3.2 + 1.5)
    assert [k for _, k, _ in sfx] == ["pop", "pop", "pop", "ding"]
    assert motion.countdown_script(99, 640, 360, BRAND)[0].count("\\p1") == 10 and motion.countdown_script(0, 640, 360, BRAND)[0].count("\\p1") == 2


@needs_ffmpeg
@pytest.mark.parametrize("style", ["pop", "typewriter"])
def test_kinetic_text_renders_and_builds_up_over_time(tmp_path, style):
    text, total, sfx = motion.kinetic_script(["Make *every* second count"], style, 480, 270, BRAND)
    (tmp_path / "m.ass").write_text(text, encoding="utf-8-sig")
    track = tmp_path / "sfx.wav"
    edit.write_sfx_track(track, sfx, total)
    out = tmp_path / "k.mp4"
    args, graph, seconds = motion.build_card_render("m.ass", BRAND, 480, 270, 15, total, out, perf.encode_args("libx264", "fast", 480, 270, 2), track)
    (tmp_path / "motion_graph.txt").write_text(graph)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-500:]
    info = clips.probe_media(out)
    assert info["has_audio"] and info["duration"] == pytest.approx(total, abs=.5)
    white = lambda p: min(p) > 200
    early, later = count(frame(out, .35, tmp_path), white), count(frame(out, 1.6, tmp_path, "g.png"), white)
    assert early > 0 and later > early * 1.15 and later > early + 25, f"{style}: the text should build up ({early} -> {later})"
    assert count(frame(out, 1.6, tmp_path, "h.png"), lambda p: p[1] > 200 and p[0] < 90 and p[2] < 90) > 30  # the emphasized word


@needs_ffmpeg
def test_countdown_renders_a_number_a_ring_then_go(tmp_path):
    text, total, sfx = motion.countdown_script(3, 480, 270, BRAND)
    (tmp_path / "c.ass").write_text(text, encoding="utf-8-sig")
    out = tmp_path / "c.mp4"
    args, graph, _ = motion.build_card_render("c.ass", BRAND, 480, 270, 15, total, out, perf.encode_args("libx264", "fast", 480, 270, 2), None)
    (tmp_path / "motion_graph.txt").write_text(graph)
    assert subprocess.run(args, cwd=tmp_path, capture_output=True).returncode == 0
    assert not clips.probe_media(out)["has_audio"] and clips.probe_media(out)["duration"] == pytest.approx(total, abs=.5)
    big = frame(out, .5, tmp_path).crop((150, 50, 330, 230))
    assert count(big, lambda p: min(p) > 200) > 400  # the big "3"
    go = frame(out, 3.6, tmp_path, "go.png")
    assert count(go, lambda p: p[1] > 200 and p[0] < 90 and p[2] < 90) > 400  # GO! in the accent color
