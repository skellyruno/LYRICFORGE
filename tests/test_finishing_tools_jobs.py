"""Repurpose, thumbnails, GIF, audio enhance and lower thirds through the server: upload validation, the jobs, the files
they write, cancellation, and keeping them out of the song library. Real FFmpeg; nothing is faked."""
import asyncio
import io
import shutil
import subprocess
import threading
import time

import pytest
from starlette.datastructures import UploadFile

import server
import studio_clips as clips

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
FAST = {"performanceMode": "balanced", "renderSpeed": "fast", "encoder": "cpu"}


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def make_talk(path, seconds=6, audio=True, size="640x360"):
    args = ["-f", "lavfi", "-i", f"testsrc=s={size}:r=15:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=f=220:d={seconds}:sample_rate=48000"]
    ffmpeg(*args, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), str(path))


def upload(path, name=None):
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


def edited_project(data, seconds=6, audio=True):
    """A project that already has an Auto-edit result."""
    pid = server.demo_project("autoedit", "Edited", {}, {"options": {}})
    make_talk(data / "data" / pid / "autoedit.mp4", seconds, audio)
    return pid


def run_async(coro):
    return asyncio.run(coro)


def done(out):
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")
    return job


@needs_ffmpeg
def test_repurpose_makes_vertical_and_square_versions_of_the_edit(data):
    pid = edited_project(data)
    out = server.create_repurpose(pid, server.RepurposeRequest(formats=["portrait", "square", "portrait", "bogus"], resolution="720p"))
    job = done(out)
    files = job["outputs"]["files"]
    assert [f["name"] for f in files] == ["autoedit_9x16.mp4", "autoedit_1x1.mp4"], "duplicates and unknown formats are dropped"
    p = data / "data" / pid
    sizes = {f["name"]: clips.probe_media(p / f["name"]) for f in files}
    assert (sizes["autoedit_9x16.mp4"]["width"], sizes["autoedit_9x16.mp4"]["height"]) == (720, 1280)
    assert (sizes["autoedit_1x1.mp4"]["width"], sizes["autoedit_1x1.mp4"]["height"]) == (720, 720)
    assert all(i["has_audio"] and i["duration"] == pytest.approx(6, abs=.6) for i in sizes.values())
    assert (p / "autoedit.mp4").exists(), "the original edit is untouched"
    assert not list(p.glob("render-*.mp4")) and not list(p.glob("graph-*.txt"))
    assert all(j["status"] == "done" for j in server.jobs.values()), "child jobs finish too"


def test_repurpose_needs_a_result_and_a_valid_choice(data):
    pid = server.demo_project("ab", "x", {}, {"options": {}})
    with pytest.raises(server.HTTPException) as e:
        server.create_repurpose(pid, server.RepurposeRequest())
    assert e.value.status_code == 409 and "Auto-edit" in e.value.detail
    with pytest.raises(server.HTTPException) as e:
        server.create_repurpose(pid, server.RepurposeRequest(formats=["bogus"]))
    assert e.value.status_code == 400
    with pytest.raises(server.HTTPException) as e:
        server.create_repurpose("0" * 32, server.RepurposeRequest())
    assert e.value.status_code == 404


@needs_ffmpeg
def test_thumbnail_variants_are_three_different_jpegs(data):
    from PIL import Image
    pid = edited_project(data, 8)
    out = server.create_thumbnails(pid, server.ThumbnailsRequest(title="  My *great* demo  "))
    job = done(out)
    files = job["outputs"]["files"]
    assert [f["name"] for f in files] == ["thumbnail_a.jpg", "thumbnail_b.jpg", "thumbnail_c.jpg"]
    assert [f["label"] for f in files] == ["Bold title", "Split layout", "Centered title"]
    assert all(f["kind"] == "image" and f["url"].endswith(f["name"]) for f in files)
    p = data / "data" / pid
    images = [Image.open(p / f["name"]).convert("RGB") for f in files]
    assert all(i.size == (1280, 720) for i in images)
    assert len({i.tobytes() for i in images}) == 3, "each layout is its own picture"
    assert not list(p.glob("thumb_frame_*.png"))


def test_thumbnails_need_a_video(data):
    pid = server.demo_project("ab", "x", {}, {"options": {}})
    with pytest.raises(server.HTTPException) as e:
        server.create_thumbnails(pid, server.ThumbnailsRequest())
    assert e.value.status_code == 409


@needs_ffmpeg
def test_gif_is_made_from_the_chosen_moment_and_stays_out_of_the_library(data):
    from PIL import Image
    src = data / "talk.mp4"
    make_talk(src, 8)
    out = run_async(server.create_gif(file=upload(src), start=2.0, seconds=3.0, width=320, fps=10))
    job = done(out)
    p = data / "data" / out["id"]
    gif = Image.open(p / "preview.gif")
    assert gif.format == "GIF" and gif.size[0] == 320 and getattr(gif, "n_frames", 1) >= 20
    assert job["outputs"]["files"][0]["kind"] == "image" and job["outputs"]["bytes"] == (p / "preview.gif").stat().st_size
    assert job["outputs"]["warning"] is None
    assert server.list_saved_projects()["projects"] == []
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_gif_validation(data):
    src = data / "talk.mp4"
    make_talk(src, 4)
    audio_only = data / "a.mp4"  # a video container with no picture
    ffmpeg("-f", "lavfi", "-i", "sine=f=300:d=3", "-c:a", "aac", str(audio_only))
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_gif(file=upload(audio_only), start=0, seconds=3, width=320, fps=10))
    assert e.value.status_code == 400 and "no video" in e.value.detail
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_gif(file=upload(src, "talk.txt"), start=0, seconds=3, width=320, fps=10))
    assert e.value.status_code == 400
    assert not list((data / "data").glob("upload-*")), "failed uploads must not leave temp folders behind"
    assert server.jobs == {}


@needs_ffmpeg
def test_gif_start_and_length_are_clamped_to_the_video(data):
    src = data / "talk.mp4"
    make_talk(src, 5)
    out = run_async(server.create_gif(file=upload(src), start=4.0, seconds=60, width=99999, fps=500))
    job = done(out)
    assert job["outputs"]["seconds"] <= 1.6 and job["outputs"]["width"] in tools_widths() and job["outputs"]["fps"] <= 20


def tools_widths():
    import studio_tools as t
    return set(t.GIF_WIDTHS)


@needs_ffmpeg
def test_enhance_audio_only_gives_an_m4a_at_the_target_loudness(data):
    src = data / "voice.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=f=300:d=6:sample_rate=48000", "-af", "volume=0.05", str(src))
    out = run_async(server.create_enhance(file=upload(src), level="medium", loudness=-16))
    job = done(out)
    f = job["outputs"]["files"][0]
    assert f["name"] == "enhanced.m4a" and f["kind"] == "audio"
    p = data / "data" / out["id"]
    info = clips.probe_media(p / "enhanced.m4a")
    assert info["has_audio"] and not info["has_video"]
    measured = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p / "enhanced.m4a"), "-af", "ebur128", "-f", "null", "-"],
                              capture_output=True, text=True).stderr
    integrated = float(measured.rsplit("I:", 1)[1].split("LUFS")[0])
    assert integrated == pytest.approx(-16, abs=1.5)
    assert server.list_saved_projects()["projects"] == []


@needs_ffmpeg
def test_enhance_video_keeps_the_picture_and_validates_choices(data):
    src = data / "talk.mp4"
    make_talk(src, 5)
    out = run_async(server.create_enhance(file=upload(src), level="off", loudness=-14))
    job = done(out)
    result = job["outputs"]["files"][0]
    assert result.pop("bytes") == (data / "data" / out["id"] / "enhanced.mp4").stat().st_size
    assert result == {"label": "Enhanced video", "name": "enhanced.mp4", "kind": "video", "url": f"/api/projects/{out['id']}/files/enhanced.mp4"}
    info = clips.probe_media(data / "data" / out["id"] / "enhanced.mp4")
    assert info["has_video"] and info["has_audio"] and (info["width"], info["height"]) == (640, 360)
    with pytest.raises(server.HTTPException) as e:  # nothing selected
        run_async(server.create_enhance(file=upload(src), level="off", loudness=0))
    assert e.value.status_code == 400
    with pytest.raises(server.HTTPException):
        run_async(server.create_enhance(file=upload(src, "x.exe"), level="medium", loudness=-14))


@needs_ffmpeg
def test_lower_third_is_burned_in_only_while_it_shows(data):
    src = data / "talk.mp4"
    make_talk(src, 8)
    out = run_async(server.create_lower_third(file=upload(src), name="Skelly Dev", role="Plugin author", start=1.0, duration=3.0, every=0.0))
    job = done(out)
    assert job["outputs"]["appearances"] == 1
    p = data / "data" / out["id"]
    assert (p / "lowerthird.mp4").is_file() and "Skelly Dev" in (p / "lowerthird.ass").read_text(encoding="utf-8-sig")
    info = clips.probe_media(p / "lowerthird.mp4")
    assert info["has_audio"] and info["duration"] == pytest.approx(8, abs=.6) and (info["width"], info["height"]) == (640, 360)
    import studio_edit as edit
    edit.extract_frame(p / "lowerthird.mp4", 2.0, data / "with.png")
    edit.extract_frame(p / "lowerthird.mp4", 6.5, data / "without.png")
    edit.extract_frame(src, 2.0, data / "orig.png")
    from PIL import Image, ImageChops
    def diff(a, b):
        return ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB")).getbbox()
    assert diff(data / "with.png", data / "orig.png") is not None, "the name is on screen at 2 s"
    assert server.list_saved_projects()["projects"] == []


@needs_ffmpeg
def test_lower_third_validation(data):
    src = data / "talk.mp4"
    make_talk(src, 4)
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_lower_third(file=upload(src), name="  ", role="", start=1, duration=3, every=0))
    assert e.value.status_code == 400
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_lower_third(file=upload(src), name="A", role="", start=99, duration=3, every=0))
    assert e.value.status_code == 400 and "past the end" in e.value.detail
    assert not list((data / "data").glob("upload-*")) and server.jobs == {}


@needs_ffmpeg
def test_cancelling_a_lower_third_leaves_no_half_written_video(data, monkeypatch):
    src = data / "talk.mp4"
    make_talk(src, 30, size="1280x720")
    monkeypatch.setattr(server, "executor", type("Hold", (), {"submit": lambda self, fn, *a: None})())
    out = run_async(server.create_lower_third(file=upload(src), name="Skelly", role="", start=1, duration=3, every=0))
    pid, job_id = out["id"], out["job_id"]
    opts = server.read_project(pid)["options"]
    worker = threading.Thread(target=server.run_lower_third, args=(pid, job_id, opts, server.sanitize_settings({})))
    worker.start()
    end = time.time() + 60
    while time.time() < end and not any(j.get("parent") == job_id and j.get("progress", 0) > 0 for j in server.jobs.values()):
        time.sleep(.05)
    assert server.cancel_job(job_id)["cancelled"] is True
    worker.join(60)
    assert not worker.is_alive()
    job = server.jobs[job_id]
    assert job["status"] == "error" and job["cancelled"] is True
    p = data / "data" / pid
    assert not (p / "lowerthird.mp4").exists() and not list(p.glob("render-*.mp4")) and not list(p.glob("graph-*.txt"))


@needs_ffmpeg
def test_tool_outputs_are_served_only_by_exact_name(data):
    pid = edited_project(data)
    assert all(server.FILE_NAME.fullmatch(n) for n in ("autoedit_9x16.mp4", "autoedit_1x1.mp4", "thumbnail_a.jpg", "thumbnail_c.jpg",
                                                       "preview.gif", "enhanced.mp4", "enhanced.m4a", "lowerthird.mp4"))
    assert not any(server.FILE_NAME.fullmatch(n) for n in ("thumbnail_d.jpg", "../preview.gif", "autoedit_16x9.mp4", "lowerthird.ass",
                                                            "enhanced.wav", "preview.gif.txt", "input.mp4"))
    assert server.FILE_TYPES[".gif"] == "image/gif" and server.FILE_TYPES[".m4a"] == "audio/mp4"
    for n in ("preview.gif", "enhanced.m4a"):
        (data / "data" / pid / n).write_bytes(b"x")
    names = [m for m in server.recent_makes()["makes"]]
    assert names == [], "only project kinds made by Make are listed: an edited video is not one"
    zipped = server.download_bundle(pid)
    import zipfile
    with zipfile.ZipFile(zipped.path) as z:
        assert {"preview.gif", "enhanced.m4a", "autoedit.mp4"} <= set(z.namelist())


@needs_ffmpeg
def test_make_kinds_for_the_new_tools_are_listed_labelled_and_pruned(data):
    src = data / "talk.mp4"
    make_talk(src, 4)
    out = run_async(server.create_gif(file=upload(src), start=0, seconds=2, width=320, fps=10))
    done(out)
    makes = server.recent_makes()["makes"]
    assert makes[0]["label"] == "GIF" and makes[0]["files"][0]["type"] == "image"
    assert {"gif", "enhance", "lower"} <= set(server.DEMO_KINDS)
    import os
    old = time.time() - 4 * 86400
    for name in ("project.json",):
        os.utime(data / "data" / out["id"] / name, (old, old))
    server.prune_demo_projects()
    assert not (data / "data" / out["id"]).exists()


# ------------------------------------------------------------------------------------------------ second batch of tools
@needs_ffmpeg
def test_repurpose_fill_option_reaches_the_render(data):
    pid = edited_project(data)
    out = server.create_repurpose(pid, server.RepurposeRequest(formats=["portrait"], resolution="720p", fit="fill"))
    done(out)
    p = data / "data" / pid
    img_info = clips.probe_media(p / "autoedit_9x16.mp4")
    assert (img_info["width"], img_info["height"]) == (720, 1280)
    assert server.read_project(pid)  # still a readable project


@needs_ffmpeg
def test_speed_makes_a_faster_video_and_rejects_1x(data):
    src = data / "talk.mp4"
    make_talk(src, 6)
    out = run_async(server.create_speed(file=upload(src), factor=2.0))
    job = done(out)
    info = clips.probe_media(data / "data" / out["id"] / "speed.mp4")
    assert info["duration"] == pytest.approx(3, abs=.4) and info["has_audio"]
    assert job["outputs"]["files"][0]["label"] == "2x speed" and job["outputs"]["seconds"] == 3.0
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_speed(file=upload(src), factor=1.0))
    assert e.value.status_code == 400
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_speed_works_on_a_silent_video(data):
    src = data / "silent.mp4"
    make_talk(src, 4, audio=False)
    out = run_async(server.create_speed(file=upload(src), factor=.5))
    done(out)
    info = clips.probe_media(data / "data" / out["id"] / "speed.mp4")
    assert info["duration"] == pytest.approx(8, abs=.6) and not info["has_audio"]


@needs_ffmpeg
def test_trim_cuts_the_chosen_part_and_validates(data):
    src = data / "talk.mp4"
    make_talk(src, 8)
    out = run_async(server.create_trim(file=upload(src), start=2.0, end=5.0))
    job = done(out)
    info = clips.probe_media(data / "data" / out["id"] / "trimmed.mp4")
    assert info["duration"] == pytest.approx(3, abs=.25) and job["outputs"]["seconds"] == 3.0
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_trim(file=upload(src), start=4.0, end=4.1))
    assert e.value.status_code == 400 and "half a second" in e.value.detail
    assert not list((data / "data").glob("upload-*"))
    assert server.list_saved_projects()["projects"] == []


@needs_ffmpeg
def test_shrink_reports_size_and_refuses_the_impossible(data, monkeypatch):
    src = data / "talk.mp4"
    make_talk(src, 8, size="1280x720")
    out = run_async(server.create_shrink(file=upload(src), size=8))
    job = done(out)
    f = data / "data" / out["id"] / "shrunk.mp4"
    assert f.is_file() and job["outputs"]["bytes"] == f.stat().st_size <= 8 * 1048576
    assert job["outputs"]["warning"] is None and "MB" in job["outputs"]["files"][0]["label"]
    real = clips.probe_media
    monkeypatch.setattr(server.clips, "probe_media", lambda path: {**real(path), "duration": 2.5 * 3600.0} if "input" in str(path) else real(path))
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_shrink(file=upload(src), size=8))
    assert e.value.status_code == 400 and "cannot fit" in e.value.detail
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_contact_sheet_job_makes_one_image_and_cleans_up(data):
    from PIL import Image
    src = data / "talk.mp4"
    make_talk(src, 9)
    out = run_async(server.create_contact_sheet(file=upload(src), cols=3, rows=2, title="My demo"))
    job = done(out)
    p = data / "data" / out["id"]
    img = Image.open(p / "contact_sheet.jpg")
    assert job["outputs"]["frames"] == 6 and img.size == (job["outputs"]["width"], job["outputs"]["height"])
    assert not list(p.glob("sheet_frame_*.png"))
    assert server.list_saved_projects()["projects"] == []


def test_quote_card_job_and_validation(data):
    from PIL import Image
    with pytest.raises(server.HTTPException) as e:
        server.create_quote_card(quote="   ", author="", aspect="square")
    assert e.value.status_code == 400
    out = server.create_quote_card(quote="Tune less, play more.", author="Skelly", aspect="portrait")
    job = done(out)
    img = Image.open(data / "data" / out["id"] / "quote_card.png")
    assert img.size == (1080, 1350) and job["outputs"]["files"][0]["kind"] == "image"
    assert server.list_saved_projects()["projects"] == []
    out2 = server.create_quote_card(quote="x", author="", aspect="nope")
    assert done(out2)["outputs"]["width"] == 1080


def test_capabilities_reports_missing_filters(monkeypatch):
    monkeypatch.setattr(server, "available_filters", lambda: {"scale", "split", "setpts"})
    caps = server.capabilities()
    assert caps["ffmpeg"] is True
    assert caps["tools"]["speed"] == {"ok": False, "missing": ["atempo"]}
    assert caps["tools"]["trim"] == {"ok": True, "missing": []} and caps["tools"]["shrink"]["ok"] is True
    assert "palettegen" in caps["tools"]["gif"]["missing"]
    monkeypatch.setattr(server, "available_filters", lambda: None)
    caps = server.capabilities()
    assert caps["ffmpeg"] is False and all(t["ok"] for t in caps["tools"].values()), "unknown means do not block anything"


@needs_ffmpeg
def test_capabilities_against_the_real_ffmpeg():
    server._filter_cache.clear()
    names = server.available_filters()
    assert names and {"scale", "split"} <= names and "ass" in names


def test_clear_makes_removes_only_make_results(data):
    keep = server.demo_project("autoedit", "Edited", {}, {"options": {}})
    gone = [server.demo_project(k, k, {}, {"options": {}}) for k in ("gif", "quote", "mv")]
    busy = server.demo_project("viz", "busy", {}, {"options": {}})
    server.jobs["j"] = {"id": "j", "project_id": busy, "status": "rendering"}
    result = server.clear_makes()
    assert result == {"deleted": 3, "skipped": 1}
    root = data / "data"
    assert (root / keep).exists() and (root / busy).exists() and not any((root / g).exists() for g in gone)


def test_new_outputs_are_allowlisted():
    for n in ("speed.mp4", "trimmed.mp4", "shrunk.mp4", "contact_sheet.jpg", "quote_card.png"):
        assert server.FILE_NAME.fullmatch(n)
    assert not any(server.FILE_NAME.fullmatch(n) for n in ("speed.mov", "quote_card.jpg", "../speed.mp4", "trimmed.mp4.txt"))
    assert server.FILE_TYPES[".png"] == "image/png"
    assert {"speed", "trim", "shrink", "sheet", "quote"} <= set(server.DEMO_KINDS) and set(server.DEMO_KINDS) <= set(server.MAKE_LABELS)


# ------------------------------------------------------------------------------------------------ third batch of tools
@needs_ffmpeg
def test_fade_job(data):
    src = data / "talk.mp4"
    make_talk(src, 5)
    out = run_async(server.create_fade(file=upload(src), fade_in=1.0, fade_out=1.0))
    job = done(out)
    assert clips.probe_media(data / "data" / out["id"] / "faded.mp4")["duration"] == pytest.approx(5, abs=.3)
    assert job["outputs"]["fade_in"] == 1.0
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_fade(file=upload(src), fade_in=0, fade_out=0))
    assert e.value.status_code == 400 and not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_loop_job_uses_the_total_length_and_validates(data, monkeypatch):
    src = data / "talk.mp4"
    make_talk(src, 3)
    out = run_async(server.create_loop(file=upload(src), times=3))
    done(out)
    assert clips.probe_media(data / "data" / out["id"] / "looped.mp4")["duration"] == pytest.approx(9, abs=.5)
    real = clips.probe_media
    monkeypatch.setattr(server.clips, "probe_media", lambda path: {**real(path), "duration": 2000.0} if "input" in str(path) else real(path))
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_loop(file=upload(src), times=10))
    assert e.value.status_code == 400 and "minutes" in e.value.detail


@needs_ffmpeg
def test_extract_audio_job_and_rejects_silent_video(data):
    src = data / "talk.mp4"
    make_talk(src, 4)
    out = run_async(server.create_extract_audio(file=upload(src)))
    job = done(out)
    assert job["outputs"]["files"][0]["kind"] == "audio"
    info = clips.probe_media(data / "data" / out["id"] / "audio.m4a")
    assert info["has_audio"] and not info["has_video"]
    silent = data / "silent.mp4"
    make_talk(silent, 3, audio=False)
    with pytest.raises(server.HTTPException) as e:
        run_async(server.create_extract_audio(file=upload(silent)))
    assert e.value.status_code == 400 and "no audio" in e.value.detail
    assert not list((data / "data").glob("upload-*"))


@needs_ffmpeg
def test_frame_job_grabs_the_picture_at_the_time(data):
    from PIL import Image
    src = data / "talk.mp4"
    make_talk(src, 5)
    out = run_async(server.create_frame(file=upload(src), at=2.0))
    job = done(out)
    img = Image.open(data / "data" / out["id"] / "frame.png")
    assert img.size == (640, 360) and job["outputs"]["files"][0]["label"] == "Frame at 0:02"
    far = run_async(server.create_frame(file=upload(src), at=999))
    assert done(far)["outputs"]["at"] <= 4.8, "a time past the end is pulled back inside the video"


@needs_ffmpeg
def test_swap_audio_job(data):
    src = data / "talk.mp4"
    make_talk(src, 4)
    track = data / "track.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=f=660:d=7", str(track))
    out = run_async(server.create_swap_audio(file=upload(src), audio=upload(track)))
    job = done(out)
    info = clips.probe_media(data / "data" / out["id"] / "swapped.mp4")
    assert info["has_video"] and info["has_audio"] and info["duration"] == pytest.approx(4, abs=.4)
    assert job["outputs"]["files"][0]["name"] == "swapped.mp4"
    silent = data / "silent.mp4"
    make_talk(silent, 3, audio=False)
    with pytest.raises(server.HTTPException) as e:  # a "track" with no audio in it
        run_async(server.create_swap_audio(file=upload(src), audio=upload(silent)))
    assert e.value.status_code == 400
    assert not list((data / "data").glob("upload-*"))
    assert server.list_saved_projects()["projects"] == []


def test_third_batch_is_registered():
    for n in ("faded.mp4", "audio.m4a", "looped.mp4", "frame.png", "swapped.mp4"):
        assert server.FILE_NAME.fullmatch(n)
    assert {"fade", "extract", "loop", "frame", "swap"} <= set(server.DEMO_KINDS) <= set(server.MAKE_LABELS)
    assert set(server.DEMO_KINDS) <= set(server.TOOL_FILTERS) | {"mv"}
