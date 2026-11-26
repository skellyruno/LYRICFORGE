"""Music videos, animation templates and livestream scenes through the server: upload validation, the jobs, the files
they write, and keeping them out of the song library. Real FFmpeg; nothing is faked."""
import asyncio
import io
import shutil
import subprocess
import time

import pytest
from starlette.datastructures import UploadFile

import server
import studio_clips as clips
import studio_edit as edit

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
FAST = {"performanceMode": "balanced", "renderSpeed": "fast", "encoder": "cpu"}


def flat(image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def make_song(path, seconds=14, period=.5):
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc='0.7*sin(2*PI*900*t)*exp(-40*mod(t,{period}))+0.05*sin(2*PI*110*t)':d={seconds}:s=48000", str(path))


def make_footage(path, color, seconds=12):
    ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=15:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", str(path))


def upload(path, name=None):
    return UploadFile(file=io.BytesIO(path.read_bytes()), filename=name or path.name)


class Inline:  # runs submitted jobs right away so a test can look at the result
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


def post_mv(**kw):
    args = dict(song=None, footage=[], intensity="medium", aspect="landscape", resolution="720p", title="", artist="",
                watermark=False, endcard=False)
    args.update(kw)
    return asyncio.run(server.create_music_video(**args))


@needs_ffmpeg
def test_music_video_upload_validation(data):
    song = data / "song.wav"
    make_song(song, 14)
    clip = data / "a.mp4"
    make_footage(clip, "red", 4)
    with pytest.raises(server.HTTPException) as e:
        post_mv(song=upload(data / "a.mp4", "song.exe"), footage=[upload(clip)])
    assert e.value.status_code == 400
    with pytest.raises(server.HTTPException):
        post_mv(song=upload(song), footage=[])
    with pytest.raises(server.HTTPException):
        post_mv(song=upload(song), footage=[upload(song, "notvideo.txt")])
    with pytest.raises(server.HTTPException) as e:
        post_mv(song=upload(song), footage=[upload(clip)] * (server.MV_MAX_CLIPS + 1))
    assert "1 to" in e.value.detail
    short = data / "short.wav"
    make_song(short, 4)
    with pytest.raises(server.HTTPException) as e:
        post_mv(song=upload(short), footage=[upload(clip)])
    assert "between" in e.value.detail
    assert not list((data / "data").glob("upload-*")), "failed uploads must not leave temp folders behind"
    assert server.list_saved_projects()["projects"] == []


@needs_ffmpeg
def test_music_video_job_cuts_between_clips_on_the_beat_and_stays_out_of_the_library(data):
    song = data / "song.wav"
    make_song(song, 14)
    colors = {"red": "red", "green": "0x00C000", "blue": "blue"}
    for name, color in colors.items():
        make_footage(data / f"{name}.mp4", color, 12)
    out = post_mv(song=upload(song), footage=[upload(data / f"{n}.mp4") for n in colors], title="Night Drive", artist="Skelly",
                  intensity="hype")
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")
    pid = out["id"]
    p = data / "data" / pid
    video = p / "music_video.mp4"
    info = clips.probe_media(video)
    assert info["has_audio"] and (info["width"], info["height"]) == (1280, 720) and info["duration"] == pytest.approx(14, abs=.7)
    assert job["outputs"]["bpm"] == pytest.approx(120, abs=2) and job["outputs"]["clips"] == 3 and job["outputs"]["cuts"] >= 8
    assert job["outputs"]["confidence"] >= .8 and job["outputs"]["warning"] is None
    assert (p / "mv_title.ass").read_text(encoding="utf-8-sig").count("Night Drive") == 1
    assert not (p / "music_video_raw.mp4").exists() and not list(p.glob("graph-*.txt"))
    seen = set()
    for t in (1.2, 2.7, 4.2, 5.7, 7.2):
        edit.extract_frame(video, t, data / "f.png")
        from PIL import Image
        px = Image.open(data / "f.png").convert("RGB").getpixel((640, 120))
        seen.add(max(range(3), key=lambda i: px[i]))
    assert len(seen) >= 2, "different footage should appear in different cuts"
    assert server.download_generated_file(pid, "music_video.mp4").path.name == "music_video.mp4"
    assert pid not in [i["id"] for i in server.list_saved_projects()["projects"]]
    assert pid not in [i["id"] for i in server.list_saved_projects()["drafts"]]
    import zipfile
    with zipfile.ZipFile(server.download_bundle(pid).path) as z:
        assert "music_video.mp4" in z.namelist()


@needs_ffmpeg
def test_music_video_without_a_usable_beat_fails_with_a_clear_message(data, monkeypatch):
    monkeypatch.setattr(server.beat, "plan_cuts", lambda *a, **k: [])  # what the planner returns when it finds under 8 beats
    song = data / "drone.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=14", str(song))
    make_footage(data / "a.mp4", "red", 5)
    out = post_mv(song=upload(song), footage=[upload(data / "a.mp4")])
    job = server.jobs[out["job_id"]]
    assert job["status"] == "error" and "steady beat" in job["error"]


@needs_ffmpeg
def test_animation_templates_render_with_sound_and_validate_the_text(data):
    out = server.create_animation(template="kinetic", text="Meet *SkellyTune*\nTone you can shape", style="slide", count=5,
                                  aspect="portrait", resolution="720p", sfx=True)
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")
    p = data / "data" / out["id"]
    info = clips.probe_media(p / "animation.mp4")
    assert (info["width"], info["height"]) == (720, 1280) and info["has_audio"]
    assert info["duration"] == pytest.approx(job["outputs"]["seconds"], abs=.5)
    quiet = server.create_animation(template="countdown", text="", style="pop", count=3, aspect="square", resolution="720p", sfx=False)
    done = server.jobs[quiet["job_id"]]
    assert done["status"] == "done", done.get("error")
    assert not clips.probe_media(data / "data" / quiet["id"] / "animation.mp4")["has_audio"]
    assert done["outputs"]["seconds"] == pytest.approx(4.7, abs=.1)  # 3, 2, 1, GO!
    with pytest.raises(server.HTTPException) as e:
        server.create_animation(template="kinetic", text="  \n ", style="pop", count=5, aspect="landscape", resolution="720p", sfx=True)
    assert e.value.status_code == 400
    ids = [i["id"] for i in server.list_saved_projects()["projects"]]
    assert out["id"] not in ids and quiet["id"] not in ids


@needs_ffmpeg
def test_livestream_pack_makes_each_scene_and_only_the_chosen_ones(data):
    out = server.create_livestream(title="SkellyTune", subtitle="Live mixing", scenes="intro, brb brb nonsense", resolution="720p")
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")
    scenes = job["outputs"]["scenes"]
    assert [s["scene"] for s in scenes] == ["intro", "brb"] and [s["loop"] for s in scenes] == [False, True]
    p = data / "data" / out["id"]
    intro, brb = clips.probe_media(p / "stream_intro.mp4"), clips.probe_media(p / "stream_brb.mp4")
    assert intro["has_audio"] and not brb["has_audio"]
    assert intro["duration"] == pytest.approx(5.0, abs=.3) and brb["duration"] == pytest.approx(8.0, abs=.3)
    assert (brb["width"], brb["height"]) == (1280, 720)
    assert not (p / "stream_starting.mp4").exists() and not (p / "stream_sfx.wav").exists()
    assert server.download_generated_file(out["id"], "stream_brb.mp4").path.name == "stream_brb.mp4"
    with pytest.raises(server.HTTPException):
        server.download_generated_file(out["id"], "stream_other.mp4")
    with pytest.raises(server.HTTPException):
        server.create_livestream(title="x", subtitle="", scenes="nothing valid", resolution="720p")
    assert out["id"] not in [i["id"] for i in server.list_saved_projects()["projects"]]
    import zipfile
    with zipfile.ZipFile(server.download_bundle(out["id"]).path) as z:
        assert sorted(z.namelist()) == ["stream_brb.mp4", "stream_intro.mp4"]


def test_every_demo_kind_is_pruned_after_three_days(data):
    import os
    import time
    ids = {k: server.demo_project(k, k, {}, {"options": {}}) for k in server.DEMO_KINDS}
    old = time.time() - 4 * 86400
    for pid in ids.values():
        os.utime(server.DATA / pid / "project.json", (old, old))
    server.prune_demo_projects()
    assert not any((server.DATA / pid).exists() for pid in ids.values())


# ---- cancelling ---------------------------------------------------------------------------------------------------------------------------
def _run_in_thread(fn, *args):
    import threading
    t = threading.Thread(target=fn, args=args, daemon=True)
    t.start()
    return t


@needs_ffmpeg
def test_cancel_stops_a_running_music_video_cleanly(data, monkeypatch):
    song = data / "song.wav"
    make_song(song, 14)
    make_footage(data / "a.mp4", "red", 12)
    monkeypatch.setattr(server, "executor", type("Hold", (), {"submit": lambda self, fn, *a: None})())  # we start the job ourselves
    out = post_mv(song=upload(song), footage=[upload(data / "a.mp4")], resolution="720p", intensity="hype")
    pid, job_id = out["id"], out["job_id"]
    opts = server.read_project(pid)["options"]
    worker = _run_in_thread(server.run_music_video, pid, job_id, opts, server.sanitize_settings({"aspect": "landscape"}))
    import time
    end = time.time() + 60
    while time.time() < end and not any(j.get("parent") == job_id and j.get("progress", 0) > 0 for j in server.jobs.values()):
        time.sleep(.05)
    answer = server.cancel_job(job_id)
    assert answer == {"cancelled": True, "status": "rendering"}
    worker.join(60)
    assert not worker.is_alive()
    job = server.jobs[job_id]
    assert job["status"] == "error" and job["cancelled"] is True and job["error"] == "Cancelled by you."
    assert all(j["status"] != "rendering" for j in server.jobs.values()), "no child job may be left running"
    folder = data / "data" / pid
    assert not (folder / "music_video.mp4").exists() and not list(folder.glob("render-*.mp4")) and not list(folder.glob("graph-*.txt"))
    server.register_job(pid, "mv", server.sanitize_settings({}))  # the project is free again
    assert server.cancel_job(job_id) == {"cancelled": False, "status": "error"}
    with pytest.raises(server.HTTPException):
        server.cancel_job("0" * 32)


@needs_ffmpeg
def test_cancelling_a_livestream_removes_the_half_written_scene(data):
    opts = {"scenes": ["starting", "brb"], "title": "T", "subtitle": "", "resolution": "720p"}
    pid = server.demo_project("stream", "T", {}, {"options": opts})
    settings = server.sanitize_settings({})
    job_id = server.register_job(pid, "stream", settings)
    worker = _run_in_thread(server.run_livestream, pid, job_id, opts, settings)
    import time
    end = time.time() + 60
    while time.time() < end and server.jobs[job_id]["progress"] < 4:
        time.sleep(.02)
    server.cancel_job(job_id)
    worker.join(60)
    assert server.jobs[job_id]["status"] == "error" and server.jobs[job_id]["cancelled"]
    folder = data / "data" / pid
    assert not list(folder.glob("stream_*.mp4")), "a cancelled scene must not leave a partial file"


def test_failed_renders_do_not_leave_the_project_busy(data):
    pid = server.demo_project("mv", "x", {}, {"options": {}})
    settings = server.sanitize_settings({})
    job_id = server.register_job(pid, "mv", settings)
    child = server.new_child_job(job_id, pid, settings, 10, 50)
    server.fail_job(job_id, RuntimeError("boom"), time.monotonic())
    assert server.jobs[child]["status"] == "error" and server.jobs[child]["error"] == "boom"
    server.register_job(pid, "mv", settings)


@needs_ffmpeg
def test_music_video_warns_when_the_song_has_no_steady_beat(data):
    song = data / "drift.wav"
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.7*sin(2*PI*900*t)*exp(-40*mod(t*(1+t/30),0.55))+0.05*sin(2*PI*110*t)':d=20:s=48000", str(song))
    make_footage(data / "a.mp4", "red", 8)
    out = post_mv(song=upload(song), footage=[upload(data / "a.mp4")], resolution="720p")
    job = server.jobs[out["job_id"]]
    assert job["status"] == "done", job.get("error")  # still renders: a warning, not a refusal
    assert job["outputs"]["confidence"] < .5 and "no clear, steady beat" in job["outputs"]["warning"]


def test_sweep_removes_only_stale_leftovers_and_never_touches_a_running_project(data):
    import os
    root = data / "data"
    old = time.time() - 8 * 3600
    stale_upload = root / "upload-abc"
    stale_upload.mkdir()
    fresh_upload = root / "upload-new"
    fresh_upload.mkdir()
    brand = root / "_brand"
    brand.mkdir()
    (brand / "upload-123.tmp").write_bytes(b"x")
    (brand / "logo.png").write_bytes(b"keep")
    quiet = server.demo_project("mv", "q", {}, {"options": {}})
    busy = server.demo_project("mv", "b", {}, {"options": {}})
    for pid in (quiet, busy):
        for name in ("render-aa.mp4", "graph-aa.txt", "stream_sfx.wav", "music_video.mp4"):
            (root / pid / name).write_bytes(b"x")
    fresh = root / quiet / "render-fresh.mp4"
    fresh.write_bytes(b"x")
    for path in (stale_upload, brand / "upload-123.tmp", *(root / pid / n for pid in (quiet, busy) for n in ("render-aa.mp4", "graph-aa.txt", "stream_sfx.wav"))):
        os.utime(path, (old, old))
    server._last_sweep = time.monotonic()  # the hourly automatic sweep already ran; this test calls it directly
    server.register_job(busy, "mv", server.sanitize_settings({}))  # running: its scratch files must be left alone
    removed = server.sweep_leftovers()
    assert removed == 5  # stale upload folder, brand temp, and the quiet project's three scratch files
    assert not stale_upload.exists() and fresh_upload.exists() and not (brand / "upload-123.tmp").exists() and (brand / "logo.png").exists()
    assert not (root / quiet / "render-aa.mp4").exists() and fresh.exists() and (root / quiet / "music_video.mp4").exists()
    assert (root / busy / "render-aa.mp4").exists(), "a project with a running job keeps its files"


def test_the_sweep_runs_by_itself_when_a_job_starts_and_only_once_an_hour(data):
    import os
    stale = data / "data" / "upload-old"
    stale.mkdir()
    old = time.time() - 9 * 3600
    os.utime(stale, (old, old))
    server._last_sweep = 0.0
    pid = server.demo_project("mv", "q", {}, {"options": {}})
    server.register_job(pid, "mv", server.sanitize_settings({}))
    assert not stale.exists(), "starting a job sweeps leftovers"
    again = data / "data" / "upload-old2"
    again.mkdir()
    os.utime(again, (old, old))
    server.jobs.clear()
    server.register_job(pid, "mv", server.sanitize_settings({}))
    assert again.exists(), "but only once an hour"


@needs_ffmpeg
def test_recent_makes_lists_finished_work_newest_first_and_deletes_only_make_projects(data):
    import os
    first = server.create_animation(template="countdown", text="", style="pop", count=3, aspect="square", resolution="720p", sfx=False)
    second = server.create_livestream(title="T", subtitle="", scenes="brb", resolution="720p")
    assert server.jobs[first["job_id"]]["status"] == "done" and server.jobs[second["job_id"]]["status"] == "done"
    old = time.time() - 3600
    os.utime(data / "data" / first["id"] / "project.json", (old, old))
    empty = server.demo_project("mv", "failed run", {}, {"options": {}})  # produced nothing
    lyric = "b" * 32
    (data / "data" / lyric).mkdir()
    (data / "data" / lyric / "project.json").write_text('{"id": "%s", "kind": "lyric", "title": "My song"}' % lyric)
    makes = server.recent_makes()["makes"]
    assert [m["id"] for m in makes] == [second["id"], first["id"]], "newest first; nothing for the empty run or the lyric project"
    assert makes[0]["label"] == "Livestream pack" and makes[0]["files"][0] == {
        "name": "stream_brb.mp4", "url": f"/api/projects/{second['id']}/files/stream_brb.mp4", "type": "video"}
    assert not any(f["name"].startswith("graph") for m in makes for f in m["files"])
    with pytest.raises(server.HTTPException) as e:
        server.delete_make(lyric)
    assert e.value.status_code == 404 and (data / "data" / lyric / "project.json").exists(), "song projects are never deleted here"
    assert server.delete_make(first["id"]) == {"deleted": first["id"]}
    assert not (data / "data" / first["id"]).exists()
    assert [m["id"] for m in server.recent_makes()["makes"]] == [second["id"]]
    assert empty  # untouched
    job_id = server.register_job(second["id"], "stream", server.sanitize_settings({}))
    with pytest.raises(server.HTTPException) as e:
        server.delete_make(second["id"])
    assert e.value.status_code == 409 and job_id
