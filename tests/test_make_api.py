"""HTTP-level checks for the Make routes, presets, B-roll, post text and proofreading: validation, auth, path safety, and
one real upload-to-download run through multipart form data. Needs the real FastAPI (TestClient) and FFmpeg."""
import base64
import io
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

import server

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    return TestClient(server.app)


def media(tmp_path, name, *args):
    path = tmp_path / name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, str(path)], check=True)
    return path


def wait_for(c, job_id, seconds=180):
    end = time.time() + seconds
    while time.time() < end:
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(.5)
    raise AssertionError("job did not finish")


ROUTES = [("post", "/api/music-video"), ("post", "/api/animation"), ("post", "/api/livestream"), ("post", "/api/ab"),
          ("post", "/api/visualizer"), ("get", "/api/presets"), ("get", "/api/brand/broll"), ("post", "/api/brand/broll"),
          ("get", "/api/projects/" + "a" * 32 + "/transcript"), ("post", "/api/projects/" + "a" * 32 + "/posts"),
          ("post", "/api/quick/mute"), ("post", "/api/quick/zoom"), ("post", "/api/quick/banner"), ("post", "/api/quick/dropclip"), ("post", "/api/quick/songcard"), ("post", "/api/fade"), ("post", "/api/loop"), ("post", "/api/extract-audio"), ("post", "/api/frame"), ("post", "/api/swap-audio"),
          ("post", "/api/speed"), ("post", "/api/trim"), ("post", "/api/shrink"), ("post", "/api/contact-sheet"), ("post", "/api/quote-card"),
          ("get", "/api/capabilities"), ("delete", "/api/makes"),
          ("post", "/api/gif"), ("post", "/api/enhance"), ("post", "/api/lower-third"),
          ("post", "/api/projects/" + "a" * 32 + "/repurpose"), ("post", "/api/projects/" + "a" * 32 + "/thumbnails")]


def test_every_make_route_sits_behind_owner_auth(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    monkeypatch.setenv("LYRICFORGE_REQUIRE_AUTH", "1")
    monkeypatch.setenv("LYRICFORGE_AUTH_USER", "demo")
    monkeypatch.setenv("LYRICFORGE_AUTH_PASSWORD", "a-long-test-password")
    for method, path in ROUTES:
        assert getattr(c, method)(path).status_code == 401, path
    token = base64.b64encode(b"demo:a-long-test-password").decode()
    assert c.get("/api/presets", headers={"Authorization": "Basic " + token}).status_code == 200


def test_make_routes_reject_bad_input_without_creating_projects(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/music-video").status_code == 422  # song and clips are required
    bad = c.post("/api/music-video", files=[("song", ("song.txt", io.BytesIO(b"x"), "text/plain")),
                                            ("clips", ("a.mp4", io.BytesIO(b"x"), "video/mp4"))])
    assert bad.status_code == 400
    assert c.post("/api/animation", data={"template": "kinetic", "text": "  "}).status_code == 400
    assert c.post("/api/livestream", data={"scenes": "nope"}).status_code == 400
    assert not [d for d in tmp_path.iterdir() if d.is_dir()], "failed requests must leave nothing behind"


def test_generated_files_are_served_only_from_the_allowlist(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    pid = server.demo_project("stream", "x", {}, {"options": {}})
    (tmp_path / pid / "stream_brb.mp4").write_bytes(b"\x00\x00")
    (tmp_path / pid / "secret.txt").write_text("no")
    assert c.get(f"/api/projects/{pid}/files/stream_brb.mp4").status_code == 200
    for name in ("secret.txt", "stream_other.mp4", "..%2Fproject.json", "stream_brb.mp4%00.txt", "music_video.mp4"):
        assert c.get(f"/api/projects/{pid}/files/{name}").status_code == 404, name


def test_presets_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    names = [p["name"] for p in c.get("/api/presets").json()["presets"]]
    assert {"Tutorial", "Plugin showcase"} <= set(names)
    saved = c.put("/api/presets/My%20weekly", json={"options": {"voice_cleanup": "medium", "shorts": 99, "unknown": 1}})
    assert saved.status_code == 200
    mine = [p for p in saved.json()["presets"] if p["name"] == "My weekly"][0]
    assert mine["options"]["voice_cleanup"] == "medium" and mine["options"]["shorts"] <= 6 and "unknown" not in mine["options"]
    assert c.delete("/api/presets/Tutorial").status_code in (400, 403, 404), "built-in presets are not deletable"
    assert c.delete("/api/presets/My%20weekly").status_code == 200


@needs_ffmpeg
def test_animation_end_to_end_over_http_and_hidden_from_the_library(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    started = c.post("/api/animation", data={"template": "countdown", "count": "3", "aspect": "square", "resolution": "720p", "sfx": "false"})
    assert started.status_code == 200, started.text
    job = wait_for(c, started.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    pid = started.json()["id"]
    video = c.get(f"/api/projects/{pid}/files/animation.mp4")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and len(video.content) > 1000
    assert pid not in [p["id"] for p in c.get("/api/projects").json()["projects"]]
    assert c.get(f"/api/projects/{pid}/bundle.zip").status_code == 200


@needs_ffmpeg
def test_music_video_multipart_with_several_clips_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    song = media(tmp_path, "song.wav", "-f", "lavfi", "-i", "aevalsrc='0.7*sin(2*PI*900*t)*exp(-40*mod(t,0.5))':d=14:s=48000")
    clips = [media(tmp_path, f"{n}.mp4", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=15:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p")
             for n, color in (("a", "red"), ("b", "blue"))]
    files = [("song", ("song.wav", song.read_bytes(), "audio/wav"))] + [("clips", (p.name, p.read_bytes(), "video/mp4")) for p in clips]
    started = c.post("/api/music-video", files=files, data={"intensity": "hype", "resolution": "720p", "title": "Night Drive", "watermark": "false"})
    assert started.status_code == 200, started.text
    job = wait_for(c, started.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["outputs"]["clips"] == 2 and job["outputs"]["intensity"] == "hype"
    assert c.get(f"/api/projects/{started.json()['id']}/files/music_video.mp4").status_code == 200


def talk(tmp_path, name="talk.mp4", seconds=6):
    return media(tmp_path, name, "-f", "lavfi", "-i", f"testsrc=s=640x360:r=15:d={seconds}", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac")


def test_finishing_tool_routes_reject_bad_input_without_leaving_files(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/gif").status_code == 422
    assert c.post("/api/gif", files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 400
    assert c.post("/api/lower-third", files={"file": ("x.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"name": " "}).status_code == 400
    assert c.post("/api/enhance", files={"file": ("x.exe", io.BytesIO(b"x"), "application/octet-stream")}).status_code == 400
    pid = server.demo_project("autoedit", "x", {}, {"options": {}})
    assert c.post(f"/api/projects/{pid}/repurpose", json={}).status_code == 409  # no Auto-edit result yet
    assert c.post(f"/api/projects/{pid}/repurpose", json={"formats": ["bogus"]}).status_code == 400
    assert c.post(f"/api/projects/{pid}/thumbnails", json={}).status_code == 409
    assert c.post("/api/projects/" + "0" * 32 + "/repurpose", json={}).status_code == 404
    assert [d.name for d in tmp_path.iterdir() if d.is_dir()] == [pid], "failed requests leave no upload folders behind"


def test_new_output_files_are_served_with_the_right_type_and_only_by_exact_name(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    pid = server.demo_project("gif", "x", {}, {"options": {}})
    for name in ("preview.gif", "enhanced.m4a", "thumbnail_a.jpg", "autoedit_9x16.mp4", "lowerthird.ass", "thumbnail_d.jpg"):
        (tmp_path / pid / name).write_bytes(b"GIF89a" if name.endswith("gif") else b"\x00\x00\x00")
    kinds = {"preview.gif": "image/gif", "enhanced.m4a": "audio/mp4", "thumbnail_a.jpg": "image/jpeg", "autoedit_9x16.mp4": "video/mp4"}
    for name, kind in kinds.items():
        r = c.get(f"/api/projects/{pid}/files/{name}")
        assert r.status_code == 200 and r.headers["content-type"].startswith(kind), name
    for name in ("lowerthird.ass", "thumbnail_d.jpg", "..%2Fproject.json"):
        assert c.get(f"/api/projects/{pid}/files/{name}").status_code == 404, name


@needs_ffmpeg
def test_gif_end_to_end_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    src = talk(tmp_path)
    started = c.post("/api/gif", files={"file": ("talk.mp4", src.read_bytes(), "video/mp4")}, data={"start": "1", "seconds": "2", "width": "320", "fps": "10"})
    assert started.status_code == 200, started.text
    job = wait_for(c, started.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    url = job["outputs"]["files"][0]["url"]
    r = c.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/gif" and r.content[:3] == b"GIF"
    assert started.json()["id"] not in [p["id"] for p in c.get("/api/projects").json()["projects"]]
    assert [m["label"] for m in c.get("/api/makes").json()["makes"]] == ["GIF"]


@needs_ffmpeg
def test_repurpose_and_thumbnails_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    pid = server.demo_project("autoedit", "Edited", {}, {"options": {}})
    (tmp_path / pid / "autoedit.mp4").write_bytes(talk(tmp_path, "edit.mp4", 6).read_bytes())
    started = c.post(f"/api/projects/{pid}/repurpose", json={"formats": ["portrait"], "resolution": "720p"})
    assert started.status_code == 200, started.text
    job = wait_for(c, started.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert [f["name"] for f in job["outputs"]["files"]] == ["autoedit_9x16.mp4"]
    assert c.get(job["outputs"]["files"][0]["url"]).status_code == 200
    started = c.post(f"/api/projects/{pid}/thumbnails", json={"title": "Demo"})
    job = wait_for(c, started.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert len(job["outputs"]["files"]) == 3 and all(c.get(f["url"]).status_code == 200 for f in job["outputs"]["files"])


def test_second_batch_routes_validate_input(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/quote-card", data={"quote": "   "}).status_code == 400
    for path in ("/api/speed", "/api/trim", "/api/shrink", "/api/contact-sheet"):
        assert c.post(path).status_code == 422, path
        assert c.post(path, files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 400, path
    assert [d.name for d in tmp_path.iterdir() if d.is_dir()] == [], "rejected requests leave nothing behind"
    caps = c.get("/api/capabilities").json()
    assert set(caps) == {"ffmpeg", "tools"} and "speed" in caps["tools"] and "missing" in caps["tools"]["gif"]


def test_quote_card_and_clear_all_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    started = c.post("/api/quote-card", data={"quote": "Tune less, play more.", "author": "Skelly", "aspect": "portrait"})
    assert started.status_code == 200, started.text
    job = wait_for(c, started.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    r = c.get(job["outputs"]["files"][0]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"
    keep = server.demo_project("autoedit", "Edited", {}, {"options": {}})
    cleared = c.delete("/api/makes")
    assert cleared.status_code == 200 and cleared.json()["deleted"] == 1
    assert (tmp_path / keep).exists(), "an edited video is not a Make result and is never cleared"
    assert c.get("/api/makes").json()["makes"] == []


@needs_ffmpeg
def test_trim_and_shrink_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    src = talk(tmp_path, seconds=6)
    sent = c.post("/api/trim", files={"file": ("talk.mp4", src.read_bytes(), "video/mp4")}, data={"start": "1", "end": "4"})
    job = wait_for(c, sent.json()["job_id"])
    assert job["status"] == "done" and c.get(job["outputs"]["files"][0]["url"]).headers["content-type"] == "video/mp4"
    sent = c.post("/api/shrink", files={"file": ("talk.mp4", src.read_bytes(), "video/mp4")}, data={"size": "8"})
    job = wait_for(c, sent.json()["job_id"])
    assert job["status"] == "done" and job["outputs"]["bytes"] <= 8 * 1048576


def test_third_batch_routes_validate_input(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    for path in ("/api/fade", "/api/loop", "/api/extract-audio", "/api/frame"):
        assert c.post(path).status_code == 422, path
        assert c.post(path, files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 400, path
    assert c.post("/api/swap-audio", files={"file": ("x.mp4", io.BytesIO(b"x"), "video/mp4")}).status_code == 422
    assert [d.name for d in tmp_path.iterdir() if d.is_dir()] == []


@needs_ffmpeg
def test_frame_and_swap_audio_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    src = talk(tmp_path, seconds=5)
    sent = c.post("/api/frame", files={"file": ("talk.mp4", src.read_bytes(), "video/mp4")}, data={"at": "2"})
    job = wait_for(c, sent.json()["job_id"])
    assert job["status"] == "done"
    r = c.get(job["outputs"]["files"][0]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    track = media(tmp_path, "t.m4a", "-f", "lavfi", "-i", "sine=f=500:d=8", "-c:a", "aac")
    sent = c.post("/api/swap-audio", files={"file": ("talk.mp4", src.read_bytes(), "video/mp4"), "audio": ("t.m4a", track.read_bytes(), "audio/mp4")})
    job = wait_for(c, sent.json()["job_id"])
    assert job["status"] == "done" and c.get(job["outputs"]["files"][0]["url"]).status_code == 200


def test_quick_route_rejects_unknown_tools_and_bad_files(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/quick/nonsense", data={"x": "1"}).status_code == 404
    assert c.post("/api/quick/mute").status_code == 400
    assert c.post("/api/quick/mute", files={"video": ("x.txt", io.BytesIO(b"x"), "text/plain")}).status_code == 400
    assert c.post("/api/quick/join", files=[("videos", ("a.mp4", io.BytesIO(b"x"), "video/mp4"))]).status_code == 400
    assert [d.name for d in tmp_path.iterdir() if d.is_dir()] == []


@needs_ffmpeg
def test_join_and_picture_in_picture_over_http(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    a, b = talk(tmp_path, "a.mp4", 3), talk(tmp_path, "b.mp4", 2)
    sent = c.post("/api/quick/join", files=[("videos", ("a.mp4", a.read_bytes(), "video/mp4")), ("videos", ("b.mp4", b.read_bytes(), "video/mp4"))])
    assert sent.status_code == 200, sent.text
    job = wait_for(c, sent.json()["job_id"])
    assert job["status"] == "done", job.get("error")
    r = c.get(job["outputs"]["files"][0]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    sent = c.post("/api/quick/pip", files=[("video", ("a.mp4", a.read_bytes(), "video/mp4")), ("overlay", ("b.mp4", b.read_bytes(), "video/mp4"))],
                  data={"corner": "tl", "size": "30"})
    job = wait_for(c, sent.json()["job_id"])
    assert job["status"] == "done", job.get("error")
