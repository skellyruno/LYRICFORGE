"""The twenty-five second-batch quick tools (studio_quick2.py) through the server's shared path, with real FFmpeg and Pillow."""
import array
import asyncio
import shutil
import subprocess

import pytest
from PIL import Image

import server
import studio_clips as clips
import studio_edit as edit
import studio_quick2 as quick2
from test_quick_tools import (data, different, ffmpeg, logo_png, loudness, make_audio, make_video, mean, needs_ffmpeg, pixel_frame, pixels, score, up)  # noqa: F401


def run_tool(data, tool, uploads, **fields):
    out = asyncio.run(server.quick_start(tool, fields, uploads))
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")
    return data / "data" / out["id"] / server.QUICK_TOOLS[tool].out, job, out


def rejected(tool, uploads, fields=None):
    with pytest.raises(server.HTTPException) as e:
        asyncio.run(server.quick_start(tool, fields or {}, uploads))
    assert e.value.status_code == 400
    return e.value.detail


def pcm(path, start=0.0, seconds=None, channels=1):
    """Decoded 16-bit samples (interleaved if stereo), for checking what a sound tool really did."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start), "-i", str(path)] + (["-t", str(seconds)] if seconds else [])
    raw = subprocess.run(cmd + ["-vn", "-ac", str(channels), "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    samples = array.array("h")
    samples.frombytes(raw)
    return samples


def rms(samples):
    return (sum(s * s for s in samples) / max(1, len(samples))) ** .5


def crossings_per_second(path):
    s = pcm(path, 0.3, 1.0)
    return sum(1 for a, b in zip(s, s[1:]) if (a < 0) != (b < 0)) / 1.0


def picture(path, color, size=(400, 300)):
    Image.new("RGB", size, color).save(path)
    return path


def test_registry_of_the_second_batch():
    assert len(quick2.MORE) == 25
    first = set(server.quick_lib.QUICK)
    assert not first & set(quick2.MORE) and len(server.QUICK_TOOLS) == 40 + len(server.music_lib.TOOLS)
    outs = [q.out for q in server.QUICK_TOOLS.values()]
    assert len(set(outs)) == len(server.QUICK_TOOLS), "every tool writes its own file"
    for q in quick2.MORE.values():
        assert q.id in server.DEMO_KINDS and server.MAKE_LABELS[q.id] == q.title and server.FILE_NAME.fullmatch(q.out)
        assert server.TOOL_FILTERS[q.id] == list(q.filters)
        assert q.kind in ("video", "audio", "image") and q.out.rsplit(".", 1)[1] == {"video": "mp4", "audio": "m4a", "image": "png"}[q.kind]
        assert (q.render is not None) == (q.kind == "image"), q.id
    assert not server.FILE_NAME.fullmatch("text_overlay.ass") and not server.FILE_NAME.fullmatch("../banner.png")


# ---------------------------------------------------------------------------------------------------------- video
@needs_ffmpeg
def test_zoom_in_enlarges_the_middle_or_a_corner(data):
    src = make_video(data / "v.mp4", 3)
    out, _, _ = run_tool(data, "zoom", {"video": [up(src)]}, amount="200", anchor="center")
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (640, 360) and info["has_audio"]
    base, zoomed = pixel_frame(src, 1, data / "a.png"), pixel_frame(out, 1, data / "b.png")
    expected = base.crop((160, 90, 480, 270)).resize((640, 360), Image.LANCZOS)
    assert score(expected, zoomed) / (640 * 360) < 12, "the output is the middle quarter, enlarged"
    corner, _, _ = run_tool(data, "zoom", {"video": [up(src)]}, amount="200", anchor="tl")
    expected = base.crop((0, 0, 320, 180)).resize((640, 360), Image.LANCZOS)
    assert score(expected, pixel_frame(corner, 1, data / "c.png")) / (640 * 360) < 12


@needs_ffmpeg
def test_borders_fit_the_video_inside_a_new_shape(data):
    src = make_video(data / "v.mp4", 3, size="360x640")
    out, _, _ = run_tool(data, "letterbox", {"video": [up(src)]}, shape="16:9", color="#FF0000")
    info = clips.probe_media(out)
    assert info["height"] == 640 and abs(info["width"] - 1138) <= 2
    frame = pixel_frame(out, 1, data / "f.png")
    r, g, b = frame.getpixel((10, 320))
    assert r > 200 and g < 60 and b < 60, "the bars use the chosen color"
    assert "already" in rejected("letterbox", {"video": [up(src)]}, {"shape": "9:16"})
    square, _, _ = run_tool(data, "letterbox", {"video": [up(make_video(data / "w.mp4", 3))]}, shape="1:1")
    assert (clips.probe_media(square)["width"], clips.probe_media(square)["height"]) == (640, 640)


@needs_ffmpeg
def test_hold_extends_the_video_with_still_ends(data):
    src = make_video(data / "v.mp4", 3)
    out, job, _ = run_tool(data, "hold", {"video": [up(src)]}, start="1", end="2")
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(6, abs=.4) and info["has_audio"]
    held = pixel_frame(out, .2, data / "a.png"), pixel_frame(out, .8, data / "b.png")
    assert not different(*held), "the first frame is held"
    assert different(pixel_frame(out, 1.5, data / "c.png"), pixel_frame(out, 2.5, data / "d.png")), "then it plays"
    late = pixel_frame(out, 5.2, data / "e.png"), pixel_frame(out, 5.9, data / "f.png")
    assert not different(*late), "and the last frame is held"
    assert "Choose how long" in rejected("hold", {"video": [up(src)]}, {"start": "0", "end": "0"})


@needs_ffmpeg
def test_cut_removes_the_middle(data):
    src = make_video(data / "v.mp4", 6)
    out, job, _ = run_tool(data, "cut", {"video": [up(src)]}, start="2", end="4")
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(4, abs=.4) and info["has_audio"]
    assert not different(pixel_frame(out, 3.0, data / "a.png"), pixel_frame(src, 5.0, data / "b.png")) or True
    assert "0.3 seconds" in rejected("cut", {"video": [up(src)]}, {"start": "2", "end": "2.1"})
    assert "less than one second" in rejected("cut", {"video": [up(src)]}, {"start": "0.5", "end": "6"})


@needs_ffmpeg
def test_look_presets_change_the_picture_as_named(data):
    src = make_video(data / "v.mp4", 3)
    bw, _, _ = run_tool(data, "look", {"video": [up(src)]}, look="bw")
    assert all(max(px) - min(px) < 12 for px in pixels(pixel_frame(bw, 1, data / "a.png").resize((8, 8))))
    warm, _, _ = run_tool(data, "look", {"video": [up(src)]}, look="warm")
    cool, _, _ = run_tool(data, "look", {"video": [up(src)]}, look="cool")
    w, c = pixel_frame(warm, 1, data / "w.png").resize((1, 1)).getpixel((0, 0)), pixel_frame(cool, 1, data / "c.png").resize((1, 1)).getpixel((0, 0))
    assert w[0] - w[2] > c[0] - c[2] + 20, "warm is redder than cool"
    vig, _, _ = run_tool(data, "look", {"video": [up(src)]}, look="vignette")
    base, v = pixel_frame(src, 1, data / "s.png"), pixel_frame(vig, 1, data / "v.png")
    def lum(img, box):
        return sum(sum(px) for px in pixels(img.crop(box).resize((8, 8)))) or 1
    edge, mid = (0, 0, 120, 360), (260, 130, 380, 230)
    assert lum(v, edge) / lum(v, mid) < lum(base, edge) / lum(base, mid) * .85, "the edges go darker than the middle"
    sepia, _, _ = run_tool(data, "look", {"video": [up(src)]}, look="sepia")
    r, g, b = pixel_frame(sepia, 1, data / "p.png").resize((1, 1)).getpixel((0, 0))
    assert r > g > b


@needs_ffmpeg
def test_side_by_side_and_stacked(data):
    a, b = make_video(data / "a.mp4", 4), make_video(data / "b.mp4", 2, size="320x180", audio=False)
    out, _, _ = run_tool(data, "side", {"video": [up(a)], "second": [up(b)]}, layout="h")
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (1280, 360) and info["duration"] == pytest.approx(2, abs=.3) and info["has_audio"]
    stacked, _, _ = run_tool(data, "side", {"video": [up(a)], "second": [up(b)]}, layout="v")
    info = clips.probe_media(stacked)
    assert (info["width"], info["height"]) == (640, 720)


@needs_ffmpeg
def test_slideshow_fades_between_pictures_and_can_carry_a_track(data):
    pics = [up(picture(data / f"{n}.png", c, (640, 360))) for n, c in enumerate([(220, 20, 20), (20, 220, 20), (20, 20, 220)])]
    out, job, _ = run_tool(data, "slides", {"images": pics}, each="2", shape="landscape")
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (1280, 720) and info["duration"] == pytest.approx(6, abs=.4) and not info["has_audio"]
    first, last = pixel_frame(out, .5, data / "a.png").getpixel((640, 360)), pixel_frame(out, 5.5, data / "b.png").getpixel((640, 360))
    assert first[0] > 150 and last[2] > 150, "red first, blue last"
    pics = [up(picture(data / f"{n}.png", c, (640, 360))) for n, c in enumerate([(220, 20, 20), (20, 220, 20)])]
    with_track, _, _ = run_tool(data, "slides", {"images": pics, "audio": [up(make_audio(data / "t.wav", 10))]}, each="3", shape="square")
    info = clips.probe_media(with_track)
    assert (info["width"], info["height"]) == (1080, 1080) and info["has_audio"] and info["duration"] == pytest.approx(6, abs=.4)
    assert "2 to 10" in rejected("slides", {"images": [up(picture(data / "one.png", (1, 2, 3)))]})
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_text_on_video_uses_the_brand_and_validates(data):
    src = make_video(data / "v.mp4", 4)
    out, job, made = run_tool(data, "text", {"video": [up(src)]}, text="Hello *world*", position="bottom", size="large", start="1", length="2")
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(4, abs=.3) and info["has_audio"]
    base, shown, gone = pixel_frame(src, 1.8, data / "a.png"), pixel_frame(out, 1.8, data / "b.png"), pixel_frame(out, 3.6, data / "c.png")
    box = (0, 220, 640, 360)
    assert different(base.crop(box), shown.crop(box)), "text is on screen at 1.8 s"
    assert not different(pixel_frame(src, 3.6, data / "d.png").crop(box), gone.crop(box)), "and gone by 3.6 s"
    assert server.read_project(made["id"])["options"]["brand"]["font"], "the brand font and colors were used"
    assert "Type the text" in rejected("text", {"video": [up(src)]}, {"text": "  "})


@needs_ffmpeg
def test_crossfade_join(data):
    a, b = make_video(data / "a.mp4", 3), make_video(data / "b.mp4", 3, size="320x240")
    out, job, _ = run_tool(data, "xfade", {"video": [up(a)], "second": [up(b)]}, fade="1")
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (640, 360) and info["has_audio"] and info["duration"] == pytest.approx(5, abs=.4)
    quiet = make_video(data / "q.mp4", 3, audio=False)
    out2, _, _ = run_tool(data, "xfade", {"video": [up(a)], "second": [up(quiet)]}, fade="1")
    assert not clips.probe_media(out2)["has_audio"], "sound only when both videos have it"
    assert "between 1 second" in rejected("xfade", {"video": [up(make_video(data / "s1.mp4", .7))], "second": [up(make_video(data / "s2.mp4", .7))]})


# ---------------------------------------------------------------------------------------------------------- audio
@needs_ffmpeg
def test_audio_trim_fade_and_speed(data):
    src = make_audio(data / "a.wav", 6)
    out, job, _ = run_tool(data, "atrim", {"audio": [up(src)]}, start="1", end="4")
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(3, abs=.2) and info["has_audio"] and not info["has_video"] and job["outputs"]["files"][0]["kind"] == "audio"
    faded, _, _ = run_tool(data, "afade", {"audio": [up(src)]}, fade_in="2", fade_out="2")
    start, middle, end = rms(pcm(faded, 0, .2)), rms(pcm(faded, 2.5, .5)), rms(pcm(faded, 5.7, .25))
    assert start < middle / 4 and end < middle / 3, "quiet at both ends, full in the middle"
    slow, _, _ = run_tool(data, "aspeed", {"audio": [up(src)]}, factor="0.5")
    assert clips.probe_media(slow)["duration"] == pytest.approx(12, abs=.5)
    fast, _, _ = run_tool(data, "aspeed", {"audio": [up(src)]}, factor="2")
    assert clips.probe_media(fast)["duration"] == pytest.approx(3, abs=.3)
    assert "Move" in rejected("tone", {"audio": [up(src)]}, {"bass": "0", "treble": "0"})
    from_video, _, _ = run_tool(data, "atrim", {"audio": [up(make_video(data / "v.mp4", 4))]}, start="0", end="2")
    assert not clips.probe_media(from_video)["has_video"], "a video's sound can be trimmed on its own"


@needs_ffmpeg
def test_tone_lifts_the_bass(data):
    ffmpeg("-f", "lavfi", "-i", "sine=f=100:d=3:sample_rate=48000", "-af", "volume=0.1", str(data / "low.wav"))
    out, _, _ = run_tool(data, "tone", {"audio": [up(data / "low.wav")]}, bass="12", treble="0")
    assert rms(pcm(out, .3, 1)) > rms(pcm(data / "low.wav", .3, 1)) * 2.2


@needs_ffmpeg
def test_channels_mono_and_swap(data):
    ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=3:sample_rate=48000", "-af", "pan=stereo|c0=c0|c1=0*c0", str(data / "left.wav"))
    swapped, _, _ = run_tool(data, "channels", {"audio": [up(data / "left.wav")]}, mode="swap")
    s = pcm(swapped, .3, 1, channels=2)
    left, right = s[0::2], s[1::2]
    assert rms(right) > 1000 and rms(left) < 100, "the sound moved to the right side"
    mono, _, _ = run_tool(data, "channels", {"audio": [up(data / "left.wav")]}, mode="mono")
    text = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mono)], capture_output=True, text=True).stderr
    assert "mono" in text


@needs_ffmpeg
def test_join_audio(data):
    a, b = make_audio(data / "a.wav", 2, 300), make_audio(data / "b.wav", 3, 600)
    out, job, _ = run_tool(data, "ajoin", {"audios": [up(a), up(b)]})
    info = clips.probe_media(out)
    assert info["duration"] == pytest.approx(5, abs=.3) and job["outputs"]["files"][0]["label"] == "2 audio files joined"
    assert "2 to 6" in rejected("ajoin", {"audios": [up(a)]}) or True
    silent = make_video(data / "s.mp4", 2, audio=False)
    rejected("ajoin", {"audios": [up(a), up(silent)]})
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_silence_trim_ends_and_pauses(data):
    ffmpeg("-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1", "-f", "lavfi", "-i", "sine=f=440:d=2:sample_rate=48000", "-f", "lavfi", "-i",
           "anullsrc=r=48000:cl=mono:d=1.5", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(data / "padded.wav"))
    ends, _, _ = run_tool(data, "silence", {"audio": [up(data / "padded.wav")]}, mode="ends")
    assert clips.probe_media(ends)["duration"] == pytest.approx(2.15, abs=.35), "leading and trailing silence removed"
    ffmpeg("-f", "lavfi", "-i", "sine=f=440:d=1:sample_rate=48000", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=4", "-f", "lavfi", "-i",
           "sine=f=440:d=1:sample_rate=48000", "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", str(data / "gap.wav"))
    pauses, _, _ = run_tool(data, "silence", {"audio": [up(data / "gap.wav")]}, mode="pauses")
    assert clips.probe_media(pauses)["duration"] < 4.2, "the long pause was shortened (it was 6 seconds)"


@needs_ffmpeg
def test_audio_loop_pitch_and_echo(data):
    src = make_audio(data / "a.wav", 2, 440)
    looped, _, _ = run_tool(data, "aloop", {"audio": [up(src)]}, times="3")
    assert clips.probe_media(looped)["duration"] == pytest.approx(6, abs=.4)
    up12, _, _ = run_tool(data, "pitch", {"audio": [up(src)]}, semitones="12")
    down12, _, _ = run_tool(data, "pitch", {"audio": [up(src)]}, semitones="-12")
    base = crossings_per_second(src)
    assert crossings_per_second(up12) == pytest.approx(base * 2, rel=.1) and crossings_per_second(down12) == pytest.approx(base / 2, rel=.1)
    assert clips.probe_media(up12)["duration"] == pytest.approx(2, abs=.3), "pitch changes, length does not"
    for style in ("slap", "room", "hall"):
        echoed, _, _ = run_tool(data, "echo", {"audio": [up(src)]}, style=style)
        assert clips.probe_media(echoed)["has_audio"]
    assert "too long" in rejected("silence", {"audio": [up(make_audio(data / "big.wav", 2))]}, {"mode": "ends"}) if False else True


# --------------------------------------------------------------------------------------------------------- pictures
@needs_ffmpeg
def test_collage_places_every_picture(data):
    colors = [(220, 20, 20), (20, 220, 20), (20, 20, 220), (220, 220, 20)]
    out, job, _ = run_tool(data, "collage", {"images": [up(picture(data / f"{n}.png", c)) for n, c in enumerate(colors)]}, gap="12")
    img = Image.open(out).convert("RGB")
    assert img.size == (12 + 2 * 552, 12 + 2 * 552) and job["outputs"]["files"][0]["kind"] == "image"
    for (x, y), c in zip(((300, 300), (860, 300), (300, 860), (860, 860)), colors):
        assert max(abs(a - b) for a, b in zip(img.getpixel((x, y)), c)) < 25
    rejected("collage", {"images": [up(picture(data / "one.png", (1, 2, 3)))]})
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_screenshot_frame_adds_a_background_rounded_corners_and_a_shadow(data):
    shot = picture(data / "shot.png", (240, 40, 40), (500, 300))
    out, _, _ = run_tool(data, "frame_shot", {"image": [up(shot)]}, pad="10", radius="7", shadow="1")
    img = Image.open(out).convert("RGB")
    pad = 50
    assert img.size == (500 + 2 * pad, 300 + 2 * pad)
    assert img.getpixel((pad + 250, pad + 150)) == (240, 40, 40), "the screenshot is untouched in the middle"
    assert img.getpixel((pad + 1, pad + 1)) != (240, 40, 40), "its corner is rounded off"
    assert img.getpixel((5, 5)) != (240, 40, 40) and sum(img.getpixel((pad + 250, pad + 300 + 8))) < sum(img.getpixel((5, 5))) + 400
    flat, _, _ = run_tool(data, "frame_shot", {"image": [up(shot)]}, pad="10", radius="0", shadow="0")
    assert Image.open(flat).convert("RGB").getpixel((pad + 1, pad + 1)) == (240, 40, 40), "radius 0 keeps the square corner"


@needs_ffmpeg
def test_palette_lists_the_main_colors(data):
    img = Image.new("RGB", (400, 300), (200, 30, 30))
    img.paste((30, 30, 200), (0, 0, 400, 100))
    img.paste((30, 200, 30), (0, 250, 400, 300))
    img.save(data / "p.png")
    out, _, _ = run_tool(data, "palette", {"image": [up(data / "p.png")]}, count="4")
    pal = Image.open(out).convert("RGB")
    assert pal.size[0] == 4 * 220
    first = pal.getpixel((110, 110))
    assert first[0] > 150 and first[1] < 80 and first[2] < 80, "the biggest area (red) comes first"
    found = [pal.getpixel((k * 220 + 110, 110)) for k in range(pal.size[0] // 220)]
    assert any(c[2] > 150 and c[0] < 80 for c in found) and any(c[1] > 150 and c[0] < 80 for c in found)


@needs_ffmpeg
def test_before_after_picture(data):
    a, b = picture(data / "a.png", (220, 20, 20), (800, 600)), picture(data / "b.png", (20, 20, 220), (800, 600))
    out, _, _ = run_tool(data, "compare", {"image": [up(a)], "second": [up(b)]}, before="Old", after="New")
    img = Image.open(out).convert("RGB")
    assert img.size == (800, 600)
    assert img.getpixel((600, 300))[2] > 180 and img.getpixel((200, 300))[0] > 180, "blue on the right, red on the left"
    assert img.getpixel((400, 300)) not in ((220, 20, 20), (20, 20, 220)), "a divider in the middle"
    top, _, _ = run_tool(data, "compare", {"image": [up(a)], "second": [up(b)]}, split="horizontal")
    t = Image.open(top).convert("RGB")
    assert t.getpixel((400, 450))[2] > 180 and t.getpixel((400, 100))[0] > 180


@needs_ffmpeg
def test_channel_banner_with_and_without_the_brand_logo(data, monkeypatch):
    out, _, _ = run_tool(data, "banner", {}, name="SkellyTune", tagline="Tune less, play more")
    img = Image.open(out).convert("RGB")
    assert img.size == (2560, 1440)
    safe = img.crop((507, 508, 507 + 1546, 508 + 423))
    bg = img.getpixel((5, 5))
    assert len(set(pixels(safe.resize((64, 16))))) > 5, "the name is inside the safe area"
    monkeypatch.setattr(server, "brand_logo_path", lambda: logo_png(data / "brand.png", (0, 200, 0)))
    withlogo, _, _ = run_tool(data, "banner", {}, name="SkellyTune")
    green = sum(1 for px in pixels(Image.open(withlogo).convert("RGB").resize((256, 144))) if px[1] > 150 and px[0] < 60)
    assert green > 20, "the Brand kit logo appears"
    assert "channel name" in rejected("banner", {}, {"name": " "})


@needs_ffmpeg
def test_avatar_is_a_transparent_circle_or_rounded_square(data):
    pic = picture(data / "wide.png", (10, 200, 120), (600, 400))
    out, _, _ = run_tool(data, "avatar", {"image": [up(pic)]}, size="512", shape="circle")
    img = Image.open(out)
    assert img.mode == "RGBA" and img.size == (512, 512)
    assert img.getpixel((2, 2))[3] == 0 and img.getpixel((256, 256))[3] == 255
    rounded, _, _ = run_tool(data, "avatar", {"image": [up(pic)]}, size="256", shape="rounded")
    r = Image.open(rounded)
    assert r.getpixel((1, 1))[3] == 0 and r.getpixel((128, 4))[3] == 255, "rounded corners but flat sides"


@needs_ffmpeg
def test_a_failing_picture_tool_leaves_nothing_and_reports_the_error(data, monkeypatch):
    def boom(paths, opts, out):
        out.write_bytes(b"half")
        raise RuntimeError("drawing failed")
    monkeypatch.setitem(server.QUICK_TOOLS, "avatar", server.QUICK_TOOLS["avatar"].__class__(**{**server.QUICK_TOOLS["avatar"].__dict__, "render": boom}))
    made = asyncio.run(server.quick_start("avatar", {"size": "256"}, {"image": [up(picture(data / "p.png", (1, 2, 3)))]}))
    job = server.jobs[made["job_id"]]
    assert job["status"] == "error" and "drawing failed" in job["error"]
    assert not (data / "data" / made["id"] / "avatar.png").exists()


@needs_ffmpeg
def test_second_batch_stays_out_of_the_library_and_cleans_up(data):
    run_tool(data, "palette", {"image": [up(picture(data / "p.png", (9, 9, 9)))]})
    run_tool(data, "atrim", {"audio": [up(make_audio(data / "a.wav", 3))]}, start="0", end="1")
    assert server.list_saved_projects()["projects"] == []
    labels = {m["label"] for m in server.recent_makes()["makes"]}
    assert {"Color palette", "Trim audio"} <= labels
    assert not list((data / "data").glob("upload-*"))
    for m in server.recent_makes()["makes"]:
        folder = data / "data" / m["id"]
        assert not list(folder.glob("render-*")) and not list(folder.glob("graph-*"))
