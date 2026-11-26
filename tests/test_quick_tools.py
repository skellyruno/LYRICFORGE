"""The fifteen quick Make tools (studio_quick.py), end to end through the server's shared path with real FFmpeg."""
import asyncio
import io
import shutil
import subprocess

import pytest
from PIL import Image, ImageChops
from starlette.datastructures import UploadFile

import server
import studio_clips as clips
import studio_edit as edit
import studio_quick as quick

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
FAST = {"performanceMode": "balanced", "renderSpeed": "fast", "encoder": "cpu"}


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def make_video(path, seconds=4, audio=True, size="640x360", volume=None, pattern="testsrc"):
    args = ["-f", "lavfi", "-i", f"{pattern}=s={size}:r=15:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=220:d={seconds}:sample_rate=48000"]
        if volume:
            args += ["-af", f"volume={volume}"]
    ffmpeg(*args, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), str(path))
    return path


def make_audio(path, seconds=4, freq=330):
    ffmpeg("-f", "lavfi", "-i", f"sine=f={freq}:d={seconds}:sample_rate=48000", str(path))
    return path


def up(path, name=None):
    return UploadFile(file=io.BytesIO(path.read_bytes()), filename=name or path.name)


class Inline:
    def submit(self, fn, *a):
        fn(*a)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(server, "executor", Inline())
    monkeypatch.setattr(server, "sanitize_settings", lambda d, _orig=server.sanitize_settings: _orig({**d, **FAST}))
    server.jobs.clear()
    return tmp_path


def run_tool(data, tool, uploads, **fields):
    out = asyncio.run(server.quick_start(tool, fields, uploads))
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")
    return data / "data" / out["id"] / quick.QUICK[tool].out, job, out


def rejected(tool, uploads, fields=None, status=400):
    with pytest.raises(server.HTTPException) as e:
        asyncio.run(server.quick_start(tool, fields or {}, uploads))
    assert e.value.status_code == status
    return e.value.detail


def loudness(path):
    text = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(text.rsplit("I:", 1)[1].split("LUFS")[0])


def pixel_frame(path, t, png):
    edit.extract_frame(path, t, png)
    return Image.open(png).convert("RGB")


def mean(img):
    return sum(sum(px) for px in pixels(img.resize((16, 9)))) / (16 * 9 * 3)


def pixels(img):
    return list(img.get_flattened_data()) if hasattr(img, "get_flattened_data") else list(img.getdata())


def score(a, b):
    return sum(pixels(ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")))


def different(a, b):
    """Visibly different: the average pixel moved by more than compression noise would explain."""
    return score(a, b) / (a.width * a.height) > 2.0


def test_registry_is_complete_and_consistent():
    assert len(quick.QUICK) == 15
    outs = [q.out for q in quick.QUICK.values()]
    assert len(set(outs)) == 15, "every tool writes its own file name"
    for q in quick.QUICK.values():
        assert server.FILE_NAME.fullmatch(q.out) and q.id in server.DEMO_KINDS and server.MAKE_LABELS[q.id] == q.title
        assert server.TOOL_FILTERS[q.id] == list(q.filters) and q.out in server.BUNDLE_FILES if hasattr(server, "BUNDLE_FILES") else True
    assert not server.FILE_NAME.fullmatch("../joined.mp4") and not server.FILE_NAME.fullmatch("joined.mp4.txt")


def test_hex_colours_are_sanitised():
    assert quick._hex("#7ce870", "000000") == "7CE870" and quick._hex("red", "101510") == "101510" and quick._hex("7CE870;rm", "101510") == "101510"


@needs_ffmpeg
def test_unknown_tool_and_missing_files(data):
    rejected("nope", {}, status=404)
    rejected("mute", {})
    rejected("still", {"image": [up(make_audio(data / "a.wav"))]})
    assert not list((data / "data").glob("upload-*")) and server.jobs == {}


@needs_ffmpeg
def test_mute_removes_the_sound_and_leaves_the_picture(data):
    src = make_video(data / "v.mp4", 4)
    out, job, _ = run_tool(data, "mute", {"video": [up(src)]})
    info = clips.probe_media(out)
    assert info["has_video"] and not info["has_audio"] and info["duration"] == pytest.approx(4, abs=.3)
    rejected("mute", {"video": [up(make_video(data / "s.mp4", 3, audio=False))]})
    assert server.list_saved_projects()["projects"] == [] and not list((data / "data").glob("upload-*"))


@needs_ffmpeg
@pytest.mark.parametrize("mode,size", [("cw", (360, 640)), ("ccw", (360, 640)), ("180", (640, 360)), ("hflip", (640, 360)), ("vflip", (640, 360))])
def test_rotate_and_flip(data, mode, size):
    out, job, _ = run_tool(data, "rotate", {"video": [up(make_video(data / "v.mp4", 3))]}, mode=mode)
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == size and info["has_audio"]


@needs_ffmpeg
def test_flip_really_mirrors_the_picture(data):
    src = make_video(data / "v.mp4", 3)
    out, _, _ = run_tool(data, "rotate", {"video": [up(src)]}, mode="hflip")
    a, b = pixel_frame(src, 1, data / "a.png"), pixel_frame(out, 1, data / "b.png")
    assert score(b, a.transpose(Image.FLIP_LEFT_RIGHT)) < score(b, a) / 3, "the picture is mirrored left to right"


@needs_ffmpeg
def test_resize_and_its_validation(data):
    src = make_video(data / "v.mp4", 3, size="1280x720")
    out, _, _ = run_tool(data, "resize", {"video": [up(src)]}, height="360")
    assert (clips.probe_media(out)["width"], clips.probe_media(out)["height"]) == (640, 360)
    assert "already" in rejected("resize", {"video": [up(src)]}, {"height": "1080"})
    assert "already" in rejected("resize", {"video": [up(make_video(data / "s.mp4", 3, size="320x240"))]}, {"height": "360"})


@needs_ffmpeg
def test_frame_rate(data):
    out, _, _ = run_tool(data, "fps", {"video": [up(make_video(data / "v.mp4", 3))]}, fps="24")
    assert clips.probe_media(out)["fps"] == pytest.approx(24, abs=.5)


@needs_ffmpeg
def test_reverse_plays_backwards_and_has_a_limit(data, monkeypatch):
    src = make_video(data / "v.mp4", 4)
    out, _, _ = run_tool(data, "reverse", {"video": [up(src)]})
    assert clips.probe_media(out)["duration"] == pytest.approx(4, abs=.4)
    first_out, last_src, first_src = (pixel_frame(out, 0.1, data / "o.png"), pixel_frame(src, 3.8, data / "l.png"), pixel_frame(src, 0.1, data / "f.png"))
    assert score(first_out, last_src) < score(first_out, first_src), "the first frame out is nearer the last frame in"
    real = clips.probe_media
    monkeypatch.setattr(server.clips, "probe_media", lambda path: {**real(path), "duration": 45.0})
    assert "up to 20 seconds" in rejected("reverse", {"video": [up(src)]})


@needs_ffmpeg
def test_volume_changes_the_loudness_both_ways(data):
    src = make_video(data / "v.mp4", 4, volume="0.1")
    before = loudness(src)
    louder, _, _ = run_tool(data, "volume", {"video": [up(src)]}, db="12")
    quieter, _, _ = run_tool(data, "volume", {"video": [up(src)]}, db="-12")
    assert loudness(louder) == pytest.approx(before + 12, abs=2.5) and loudness(quieter) == pytest.approx(before - 12, abs=2.5)
    assert clips.probe_media(louder)["has_video"]
    rejected("volume", {"video": [up(make_video(data / "s.mp4", 3, audio=False))]})


def logo_png(path, color=(255, 0, 0)):
    Image.new("RGB", (200, 100), color).save(path)
    return path


@needs_ffmpeg
def test_watermark_lands_in_the_chosen_corner(data):
    src = make_video(data / "v.mp4", 3)
    base = pixel_frame(src, 1, data / "a.png")
    out, _, _ = run_tool(data, "watermark", {"video": [up(src)], "logo": [up(logo_png(data / "logo.png"))]}, corner="br", size="20", opacity="100")
    marked = pixel_frame(out, 1, data / "b.png")
    assert marked.getpixel((560, 320))[0] > 200 and marked.getpixel((560, 320))[1] < 60, "solid red in the bottom-right"
    assert score(base.crop((0, 0, 200, 100)), marked.crop((0, 0, 200, 100))) < 200 * 100 * 3, "the rest of the picture is untouched"


@needs_ffmpeg
def test_watermark_needs_a_logo_and_can_use_the_brand_kit(data, monkeypatch):
    src = make_video(data / "v.mp4", 3)
    assert "logo" in rejected("watermark", {"video": [up(src)]}).lower()
    logo = logo_png(data / "brand.png", (0, 255, 0))
    monkeypatch.setattr(server, "brand_logo_path", lambda: logo)
    out, _, _ = run_tool(data, "watermark", {"video": [up(src)]}, corner="center", size="30")
    assert pixel_frame(out, 1, data / "c.png").getpixel((320, 180))[1] > 180
    assert logo.exists(), "the brand logo is copied, never moved"


@needs_ffmpeg
def test_crop_shapes(data):
    src = make_video(data / "v.mp4", 3)
    for shape, size in (("1:1", (360, 360)), ("9:16", (202, 360)), ("4:5", (288, 360))):
        out, _, _ = run_tool(data, "crop", {"video": [up(src)]}, shape=shape)
        info = clips.probe_media(out)
        assert (info["width"], info["height"]) == size, shape
    assert "already" in rejected("crop", {"video": [up(src)]}, {"shape": "16:9"})
    portrait = make_video(data / "p.mp4", 3, size="360x640")
    out, _, _ = run_tool(data, "crop", {"video": [up(portrait)]}, shape="1:1")
    assert (clips.probe_media(out)["width"], clips.probe_media(out)["height"]) == (360, 360)


@needs_ffmpeg
def test_color_adjust(data):
    src = make_video(data / "v.mp4", 3)
    bright, _, _ = run_tool(data, "grade", {"video": [up(src)]}, brightness="40", contrast="0", saturation="0")
    grey, _, _ = run_tool(data, "grade", {"video": [up(src)]}, brightness="0", contrast="0", saturation="-50")
    assert mean(pixel_frame(bright, 1, data / "b.png")) > mean(pixel_frame(src, 1, data / "s.png")) + 10
    g = pixel_frame(grey, 1, data / "g.png")
    assert all(max(px) - min(px) < 12 for px in pixels(g.resize((8, 8)))), "saturation -50 is black and white"
    assert "slider" in rejected("grade", {"video": [up(src)]}, {"brightness": "0"})


@needs_ffmpeg
def test_cleanup_denoises_and_sharpens(data):
    src = make_video(data / "v.mp4", 3, pattern="testsrc")
    out, _, _ = run_tool(data, "cleanup", {"video": [up(src)]}, denoise="medium", sharpen="light")
    assert (clips.probe_media(out)["width"], clips.probe_media(out)["height"]) == (640, 360)
    assert "level" in rejected("cleanup", {"video": [up(src)]}, {"denoise": "off", "sharpen": "off"})


@needs_ffmpeg
def test_waveform_picture(data):
    out, job, _ = run_tool(data, "waveform", {"audio": [up(make_audio(data / "a.wav", 3))]}, shape="banner", fg="#FF0000", bg="#000000")
    img = Image.open(out).convert("RGB")
    assert img.size == (1600, 200) and job["outputs"]["files"][0]["kind"] == "image"
    reds = sum(1 for px in pixels(img) if px[0] > 200 and px[1] < 60)
    assert reds > 500 and img.getpixel((2, 2)) == (0, 0, 0)
    from_video, _, _ = run_tool(data, "waveform", {"audio": [up(make_video(data / "v.mp4", 3))]})
    assert Image.open(from_video).size == (1600, 400)
    rejected("waveform", {"audio": [up(make_video(data / "s.mp4", 3, audio=False))]})


@needs_ffmpeg
def test_image_plus_audio_makes_a_video_with_and_without_zoom(data):
    pic = data / "cover.png"
    img = Image.new("RGB", (800, 800), (20, 20, 20))
    for x in range(100, 700, 100):
        for y in range(100, 700, 100):
            img.paste((200, 60 + x // 4, 60 + y // 4), (x, y, x + 50, y + 50))
    img.save(pic)
    track = make_audio(data / "t.wav", 4)
    flat, _, _ = run_tool(data, "still", {"image": [up(pic)], "audio": [up(track)]}, shape="landscape", zoom="none")
    info = clips.probe_media(flat)
    assert (info["width"], info["height"]) == (1280, 720) and info["duration"] == pytest.approx(4, abs=.3) and info["has_audio"]
    assert not different(pixel_frame(flat, .3, data / "f1.png"), pixel_frame(flat, 3.5, data / "f2.png")), "no zoom: a still picture"
    zoomed, _, _ = run_tool(data, "still", {"image": [up(pic)], "audio": [up(track)]}, shape="square", zoom="slow")
    info = clips.probe_media(zoomed)
    assert (info["width"], info["height"]) == (1080, 1080)
    assert different(pixel_frame(zoomed, .3, data / "z1.png"), pixel_frame(zoomed, 3.5, data / "z2.png")), "slow zoom: the picture moves"
    assert "could not be read" in rejected("still", {"image": [up(data / "t.wav", "x.png")], "audio": [up(track)]})
    assert "Upload" in rejected("still", {"image": [up(pic, "x.gif")], "audio": [up(track)]})
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_background_music_under_speech(data):
    speech = make_video(data / "v.mp4", 5, volume="0.3")
    music = make_audio(data / "m.wav", 2, 660)
    for duck in ("1", "0"):
        out, _, _ = run_tool(data, "music", {"video": [up(speech)], "music": [up(music)]}, db="-12", duck=duck)
        info = clips.probe_media(out)
        assert info["has_video"] and info["has_audio"] and info["duration"] == pytest.approx(5, abs=.4), "a short track loops to the video's length"
    silent = make_video(data / "s.mp4", 4, audio=False)
    out, _, _ = run_tool(data, "music", {"video": [up(silent)], "music": [up(music)]})
    assert clips.probe_media(out)["has_audio"], "a silent video gains the music"
    rejected("music", {"video": [up(speech)], "music": [up(make_video(data / "s2.mp4", 3, audio=False))]})


@needs_ffmpeg
def test_join_matches_sizes_and_fills_silence(data):
    a = make_video(data / "a.mp4", 3)
    b = make_video(data / "b.mp4", 2, size="320x240", audio=False)
    c = make_video(data / "c.mp4", 2, size="1280x720")
    out, job, _ = run_tool(data, "join", {"videos": [up(a), up(b), up(c)]})
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (640, 360) and info["has_audio"] and info["duration"] == pytest.approx(7, abs=.5)
    assert job["outputs"]["files"][0]["label"] == "3 videos joined"
    assert "2 to 6" in rejected("join", {"videos": [up(a)]})
    assert "2 to 6" in rejected("join", {"videos": [up(a)] * 7})
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_picture_in_picture(data):
    main = make_video(data / "m.mp4", 4)
    small = make_video(data / "s.mp4", 2, size="320x180", pattern="smptebars", audio=False)
    out, _, _ = run_tool(data, "pip", {"video": [up(main)], "overlay": [up(small)]}, corner="tl", size="30")
    info = clips.probe_media(out)
    assert (info["width"], info["height"]) == (640, 360) and info["has_audio"] and info["duration"] == pytest.approx(4, abs=.3)
    base, marked = pixel_frame(main, 1, data / "a.png"), pixel_frame(out, 1, data / "b.png")
    assert different(base.crop((0, 0, 150, 80)), marked.crop((0, 0, 150, 80))), "the small video is in the top-left"
    assert not different(base.crop((400, 250, 600, 340)), marked.crop((400, 250, 600, 340))), "and nowhere else"
    late_base, late = pixel_frame(main, 3.5, data / "c.png"), pixel_frame(out, 3.5, data / "d.png")
    assert not different(late_base.crop((0, 0, 150, 80)), late.crop((0, 0, 150, 80))), "after the small video ends, it disappears"


@needs_ffmpeg
def test_quick_jobs_clean_up_and_stay_out_of_the_library(data):
    run_tool(data, "mute", {"video": [up(make_video(data / "v.mp4", 3))]})
    assert server.list_saved_projects()["projects"] == []
    assert server.recent_makes()["makes"][0]["label"] == "Remove audio"
    assert not list((data / "data").glob("upload-*"))
    pid = server.recent_makes()["makes"][0]["id"]
    assert not list((data / "data" / pid).glob("render-*")) and not list((data / "data" / pid).glob("graph-*"))


@needs_ffmpeg
def test_a_failed_fast_copy_falls_back_to_a_re_encode(data, monkeypatch):
    calls = []
    real = quick.QUICK["mute"].build

    def flaky(p, o, out, safe):
        calls.append(safe)
        return real(p, o, out, safe) if safe else [*quick.QUIET, "-y", "-i", str(p["video"]), "-c:v", "nonexistent_codec", str(out)]
    monkeypatch.setitem(server.QUICK_TOOLS, "mute", quick.Quick(**{**quick.QUICK["mute"].__dict__, "build": flaky}))
    out, _, _ = run_tool(data, "mute", {"video": [up(make_video(data / "v.mp4", 3))]})
    assert calls == [False, True] and clips.probe_media(out)["has_video"]
