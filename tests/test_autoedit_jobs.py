"""Auto-edit, brand kit, translation, hook ideas, the headless path and the watch folder, run for real.

Only Whisper and the Claude API are replaced; every render, cut, zoom, caption, thumbnail and file step is production code.
"""
import json
import shutil
import subprocess
import time

import pytest

import server
import studio_clips as clips
import studio_edit as edit

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
PID = "c" * 32
FAST = {"performanceMode": "balanced", "renderSpeed": "fast", "encoder": "cpu"}


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def speech(spans, tag="talk"):
    words = []
    for a, b in spans:
        for k in range(8):
            words.append({"text": f"{tag}{k}" + ("." if k == 7 else ""), "start": round(a + (b - a) * k / 8, 3),
                          "end": round(a + (b - a) * (k + 1) / 8 - .03, 3)})
    return words


def make_video(path, seconds=26):
    ffmpeg("-f", "lavfi", "-i", f"color=c=0x203040:s=1280x720:r=15:d={seconds}",
           "-f", "lavfi", "-i", f"color=c=white:s=90x90:r=15:d={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds},volume=-20dB",
           "-filter_complex", "[0:v][1:v]overlay=x='900+mod(t*5,60)':y=300[v]", "-map", "[v]", "-map", "2:a",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))


def setup(tmp_path, monkeypatch, words, seconds=26):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    p = tmp_path / PID
    p.mkdir()
    make_video(p / "source.mp4", seconds)
    server.save_project(p, {"id": PID, "kind": "clip_source", "title": "Plugin walkthrough", "audio_file": "source.mp4",
                            "source_file": "source.mp4", "duration": float(seconds), "status": "transcribing",
                            "draft_lyrics": "", "original_words": [], "lines": [], "settings": {}, "save_state": "saved",
                            "use_ai": False})

    def fake_transcribe(project_id):
        d = json.loads((server.DATA / project_id / "project.json").read_text(encoding="utf-8"))
        d.update(original_words=words, transcription_stage="complete" if words else "error", status="review")
        server.save_project(server.DATA / project_id, d)
    monkeypatch.setattr(server, "transcribe_project", fake_transcribe)
    return p


def add_brand(logo_color=(255, 0, 0, 255)):
    from PIL import Image
    src = server.brand_dir() / "src.png"
    Image.new("RGBA", (120, 120), logo_color).save(src)
    edit.process_logo(src, server.brand_dir() / "logo.png")
    src.unlink()
    server.put_brand(server.BrandRequest(brand={"name": "Skelly Audio", "endcard": {"title": "Get SkellyTune",
                                                                                     "url": "skelly.example", "seconds": 2}}))


def run_edit(opts):
    settings = server.sanitize_settings({"aspect": "landscape", **FAST})
    job = server.register_job(PID, "autoedit", settings)
    server.run_autoedit(PID, job, server.autoedit_options(server.AutoEditRequest(**opts)), settings)
    return server.jobs[job]


@needs_ffmpeg
def test_auto_edit_produces_a_complete_youtube_package(tmp_path, monkeypatch):
    words = speech([(0.5, 8.0), (16.0, 24.0)])  # 8 s of dead air in the middle
    p = setup(tmp_path, monkeypatch, words)
    add_brand()
    server.analyze_clip_source(PID)
    assert server.read_project(PID)["status"] == "ready"
    result = run_edit({"zoom": "medium", "captions": True, "resolution": "720p", "shorts": 1})
    assert result["status"] == "done", result.get("error")
    out = result["outputs"]
    info = clips.probe_media(p / "autoedit.mp4")
    assert (info["width"], info["height"]) == (1280, 720) and info["has_audio"]
    assert out["removed_seconds"] > 5 and info["duration"] == pytest.approx(out["seconds"], abs=.8)
    assert info["duration"] < 26 - 5 + 2 + 1  # cut the gap, added the 2 s end card
    from PIL import Image
    with Image.open(p / "thumbnail.jpg") as thumb:
        assert thumb.size == (1280, 720)
    text = (p / "youtube.txt").read_text(encoding="utf-8")
    assert text.startswith("TITLE\nPlugin walkthrough") and "Skelly Audio | skelly.example" in text
    srt = (p / "captions.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,") and "talk0" in srt
    cues = json.loads((p / "captions.json").read_text(encoding="utf-8"))
    assert cues[-1]["end"] < 17.6  # captions follow the CUT timeline (24 s of source ended at about 16.6)
    assert out["captions"]["srt"].endswith("/files/captions.srt") and out["zoomed"] in (True, False)
    shorts = out["shorts"]
    assert shorts and clips.probe_media(p / "clip_1.mp4")["height"] == 1280
    zipped = server.download_bundle(PID).path
    import zipfile
    names = zipfile.ZipFile(zipped).namelist()
    assert {"autoedit.mp4", "thumbnail.jpg", "youtube.txt", "captions.srt", "clip_1.mp4"} <= set(names)


@needs_ffmpeg
def test_auto_edit_options_off_and_no_speech(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch, speech([(0.5, 20.0)]))
    server.analyze_clip_source(PID)
    result = run_edit({"trim_silence": False, "loudness": False, "watermark": False, "endcard": False,
                       "resolution": "720p"})
    assert result["status"] == "done", result.get("error")
    assert result["outputs"]["removed_seconds"] == 0
    assert clips.probe_media(p / "autoedit.mp4")["duration"] == pytest.approx(26.0, abs=.8)


@needs_ffmpeg
def test_polished_short_is_trimmed_watermarked_and_louder(tmp_path, monkeypatch):
    words = speech([(1.0, 6.0), (13.0, 19.0)])  # a 7 s pause inside the clip
    p = setup(tmp_path, monkeypatch, words)
    add_brand()
    server.analyze_clip_source(PID)
    settings = server.short_settings({**FAST, "resolution": "540p"})
    item = {"start": 0.0, "end": 22.0, "hook": "Watch this", "title": "t", "description": "", "tags": [], "score": .5,
            "reasons": []}
    job = server.register_job(PID, "clips", settings)
    server.run_clips(PID, job, [item], settings, "center", {"loudness": True, "watermark": True, "trim_silence": True})
    assert server.jobs[job]["status"] == "done", server.jobs[job].get("error")
    info = clips.probe_media(p / "clip_1.mp4")
    assert info["duration"] < 22 - 4 and (info["width"], info["height"]) == (540, 960)
    plain = server.register_job(PID, "clips", settings)
    server.run_clips(PID, plain, [item], settings, "center", None)  # unchanged behaviour without polish
    assert clips.probe_media(p / "clip_1.mp4")["duration"] == pytest.approx(22.0, abs=.8)


def test_brand_kit_round_trip_and_logo_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    assert server.get_brand()["brand"]["has_logo"] is False
    saved = server.put_brand(server.BrandRequest(brand={"name": "Acme", "accent": "nonsense", "has_logo": True}))["brand"]
    assert saved["name"] == "Acme" and saved["accent"] == edit.DEFAULT_BRAND["accent"] and saved["has_logo"] is False
    add_brand()
    assert server.get_brand()["brand"]["has_logo"] is True and server.get_brand_logo().path.name == "logo.png"
    assert server.delete_brand_logo()["brand"]["has_logo"] is False
    with pytest.raises(server.HTTPException) as caught:
        server.get_brand_logo()
    assert caught.value.status_code == 404
    assert server.list_saved_projects()["projects"] == []  # the brand folder never shows up as a project


def test_generated_files_are_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    (tmp_path / PID).mkdir()
    (tmp_path / PID / "captions.es.srt").write_text("x", encoding="utf-8")
    (tmp_path / PID / "project.json").write_text("{}", encoding="utf-8")
    assert server.download_generated_file(PID, "captions.es.srt").path.name == "captions.es.srt"
    for bad in ("project.json", "../project.json", "captions.srt", "captions.EN.srt", "autoedit.mp4.bak", "source.mp4"):
        with pytest.raises(server.HTTPException) as caught:
            server.download_generated_file(PID, bad)
        assert caught.value.status_code == 404


def fake_llm(monkeypatch, handler):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(edit, "llm_text", lambda prompt, key, model, post=None, max_tokens=2000: handler(prompt))


def wait_done(job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        if server.jobs[job_id]["status"] != "rendering":
            return server.jobs[job_id]
        time.sleep(.05)
    raise AssertionError("job did not finish")


def test_translation_job_writes_timed_caption_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    p = tmp_path / PID
    p.mkdir()
    server.save_project(p, {"id": PID, "kind": "clip_source", "title": "t", "duration": 30.0, "status": "ready"})
    with pytest.raises(server.HTTPException) as caught:  # nothing to translate yet
        server.start_translate(PID, server.TranslateRequest(languages=["es"]))
    assert caught.value.status_code == 409
    cues = [{"start": i * 2.0, "end": i * 2.0 + 1.5, "text": f"hello {i}"} for i in range(5)]
    (p / "captions.json").write_text(json.dumps(cues), encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(server.HTTPException) as caught:  # no key
        server.start_translate(PID, server.TranslateRequest(languages=["es"]))
    assert caught.value.status_code == 409 and "ANTHROPIC_API_KEY" in caught.value.detail
    fake_llm(monkeypatch, lambda prompt: json.dumps([f"hola {t}" for t in json.loads(prompt.split("\n\n")[-1])]))
    with pytest.raises(server.HTTPException):
        server.start_translate(PID, server.TranslateRequest(languages=["xx", "zz"]))
    job = server.start_translate(PID, server.TranslateRequest(languages=["es", "es", "fr", "xx"]))["job_id"]
    result = wait_done(job)
    assert result["status"] == "done", result.get("error")
    assert [f["lang"] for f in result["outputs"]["files"]] == ["es", "fr"]
    srt = (p / "captions.es.srt").read_text(encoding="utf-8")
    assert "00:00:02,000 --> 00:00:03,500\nhola hello 1" in srt
    assert (p / "captions.fr.vtt").read_text(encoding="utf-8").startswith("WEBVTT")


def test_hook_ideas_need_a_key_and_degrade_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    (tmp_path / PID).mkdir()
    (tmp_path / PID / "project.json").write_text(json.dumps({"id": PID}), encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(server.HTTPException) as caught:
        server.clip_hook_variants(PID, server.VariantsRequest(text="some words"))
    assert caught.value.status_code == 409
    fake_llm(monkeypatch, lambda prompt: json.dumps([{"hook": "Stop guessing", "title": "Mix better"}]))
    assert server.clip_hook_variants(PID, server.VariantsRequest(text="some words"))["variants"][0]["hook"] == "Stop guessing"
    fake_llm(monkeypatch, lambda prompt: "garbage")
    with pytest.raises(server.HTTPException) as caught:
        server.clip_hook_variants(PID, server.VariantsRequest(text="some words"))
    assert caught.value.status_code == 502


@needs_ffmpeg
def test_headless_path_turns_a_file_into_a_finished_package(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    server.jobs.clear()
    monkeypatch.setattr(server, "media_duration", lambda path: clips.probe_media(path)["duration"])
    monkeypatch.setattr(server, "transcribe_project", lambda pid: _fake_words(pid, speech([(0.5, 6.0), (14.0, 22.0)])))
    inbox = tmp_path / "in"
    inbox.mkdir()
    make_video(inbox / "My Demo.mp4", 24)
    out = server.process_video_file(inbox / "My Demo.mp4", tmp_path / "out",
                                    {"resolution": "720p", "endcard": False, "watermark": False}, log=lambda m: None)
    assert out.name == "My Demo"
    assert {f.name for f in out.iterdir()} == {"video.mp4", "thumbnail.jpg", "youtube.txt", "captions.srt", "captions.vtt"}
    leftovers = [d.name for d in (tmp_path / "data").iterdir() if d.is_dir() and d.name != "_brand"]
    assert not leftovers  # the working copy of the video is removed
    with pytest.raises(ValueError):
        server.import_video_file(inbox / "My Demo.mp4".replace(".mp4", ".txt"))


def _fake_words(project_id, words):
    d = json.loads((server.DATA / project_id / "project.json").read_text(encoding="utf-8"))
    d.update(original_words=words, transcription_stage="complete", status="review")
    server.save_project(server.DATA / project_id, d)


@needs_ffmpeg
def test_watch_folder_processes_moves_and_reports_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("SKELLYMOTION_WATCH", "1")
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(server, "WATCH_POLL_SECONDS", .05)
    monkeypatch.setattr(server, "WATCH_STABLE_SECONDS", .1)
    inbox, out = tmp_path / "inbox", tmp_path / "out"
    inbox.mkdir()
    (inbox / "good.mp4").write_bytes(b"x")
    (inbox / "bad.mkv").write_bytes(b"y")
    (inbox / "notes.txt").write_text("ignore me")

    def fake_process(src, out_root, opts, **kw):
        if src.name == "bad.mkv":
            raise RuntimeError("could not read")
        (out_root / src.stem).mkdir(parents=True)
        return out_root / src.stem
    monkeypatch.setattr(server, "process_video_file", fake_process)
    status = server.watch_start(server.WatchRequest(folder=str(inbox), out=str(out)))
    assert status["running"] and status["enabled"]
    end = time.time() + 10
    while time.time() < end and not ((inbox / "processed" / "good.mp4").exists() and (inbox / "failed" / "bad.mkv").exists()):
        time.sleep(.05)
    assert (inbox / "processed" / "good.mp4").exists() and (inbox / "failed" / "bad.mkv").exists()
    assert (inbox / "notes.txt").exists()
    assert any("Failed: bad.mkv" in e["message"] for e in server.watch_status()["events"])
    server.watch_stop()
    server.WATCH["thread"].join(3)
    assert not server.watch_status()["running"]


def test_watch_is_desktop_only_and_validates_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.delenv("SKELLYMOTION_WATCH", raising=False)
    with pytest.raises(server.HTTPException) as caught:
        server.watch_start(server.WatchRequest(folder=str(tmp_path), out=str(tmp_path / "o")))
    assert caught.value.status_code == 403
    monkeypatch.setenv("SKELLYMOTION_WATCH", "1")
    with pytest.raises(server.HTTPException) as caught:
        server.watch_start(server.WatchRequest(folder=str(tmp_path / "missing"), out=str(tmp_path / "o")))
    assert caught.value.status_code == 400
    with pytest.raises(server.HTTPException) as caught:  # may not read or write inside the app's own workspace
        server.watch_start(server.WatchRequest(folder=str(tmp_path / "data"), out=str(tmp_path / "o")))
    assert caught.value.status_code == 400


# ============================================ the director: clips, music, sound effects, animations
def solid(path, color, seconds, audio=True):
    cmd = ["-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=15:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=500:duration={seconds}", "-c:a", "aac", "-shortest"]
    ffmpeg(*cmd, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path))


def sentence_words(rows):
    words = []
    for text, start, end in rows:
        parts = text.split()
        for k, w in enumerate(parts):
            words.append({"text": w, "start": round(start + (end - start) * k / len(parts), 3),
                          "end": round(start + (end - start) * (k + 1) / len(parts) - .03, 3)})
    return words


def test_brand_assets_are_validated_stored_and_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    music, intro, long_clip = tmp_path / "m.wav", tmp_path / "i.mp4", tmp_path / "l.mp4"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=4", str(music))
    solid(intro, "red", 3)
    solid(long_clip, "green", 25, audio=False)
    assert server.load_brand()["has_music"] is False
    server.store_brand_asset("music", music)
    server.store_brand_asset("intro", intro)
    brand = server.load_brand()
    assert brand["has_music"] and brand["has_intro"] and not brand["has_outro"]
    assert server.brand_asset("music").name == "music.wav" and server.brand_asset("outro") is None
    with pytest.raises(ValueError, match="at most 20 seconds"):
        server.store_brand_asset("outro", long_clip)
    audio_only = tmp_path / "audio_only.mp4"  # a valid video extension, but nothing to see
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(music), "-c:a", "aac", str(audio_only)], check=True)
    with pytest.raises(ValueError, match="no video"):
        server.store_brand_asset("intro", audio_only)
    with pytest.raises(ValueError, match="Unsupported"):
        server.store_brand_asset("intro", music)  # a .wav is not a video file type
    with pytest.raises(ValueError, match="no audio"):
        _silent_as_music(tmp_path)
    with pytest.raises(ValueError, match="Unsupported"):
        (tmp_path / "x.txt").write_text("hi")
        server.store_brand_asset("music", tmp_path / "x.txt")
    server.store_brand_asset("music", music)  # replacing keeps exactly one file
    assert len(list(server.brand_dir().glob("music.*"))) == 1
    assert server.delete_brand_asset("music")["brand"]["has_music"] is False
    with pytest.raises(server.HTTPException):
        server.delete_brand_asset("virus")


def _silent_as_music(tmp_path):
    video = tmp_path / "silent.mp4"
    solid(video, "gray", 2, audio=False)
    silent = tmp_path / "silent.m4a"  # an allowed music extension whose content has no audio stream
    shutil.copy2(video, silent)
    server.store_brand_asset("music", silent)


@needs_ffmpeg
def test_auto_edit_places_clips_music_sfx_and_animations_without_being_told_where(tmp_path, monkeypatch):
    rows = [("Welcome to this quick tour of the plugin.", 0.5, 4.5), ("Remember to always check the input level first.", 5.0, 9.5),
            ("Now open the main window and look around.", 10.0, 14.0), ("Here is a pro tip that saves a lot of time.", 20.0, 24.5)]
    p = setup(tmp_path, monkeypatch, sentence_words(rows), 26)
    add_brand()
    music, intro, outro = tmp_path / "m.wav", tmp_path / "i.mp4", tmp_path / "o.mp4"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=5", str(music))
    solid(intro, "red", 3)
    solid(outro, "blue", 2, audio=False)
    for kind, path in (("music", music), ("intro", intro), ("outro", outro)):
        server.store_brand_asset(kind, path)
    server.analyze_clip_source(PID)
    result = run_edit({"resolution": "720p"})  # only the defaults: the director decides everything else
    assert result["status"] == "done", result.get("error")
    out = result["outputs"]
    extras = out["extras"]
    assert extras["callouts"] >= 1 and extras["sfx"] >= 1 and extras["music"] and extras["intro_clip"] and extras["outro_clip"]
    assert not extras["intro_card"]  # off unless asked for
    info = clips.probe_media(p / "autoedit.mp4")
    main = out["seconds"] - 3 - 2 - 2  # intro clip, outro clip, end card (2 s from the brand)
    assert main < 26 - 4 and info["duration"] == pytest.approx(out["seconds"], abs=.8)
    from PIL import Image
    png = p / "frame.png"
    edit.extract_frame(p / "autoedit.mp4", 1.0, png)
    r, g, b = Image.open(png).convert("RGB").getpixel((320, 180))
    assert r > 200 and g < 60 and b < 60  # intro clip first
    first = (p / "captions.srt").read_text(encoding="utf-8").splitlines()[1]
    assert first.startswith("00:00:03,") or first.startswith("00:00:04,")  # captions are shifted past the 3 s intro
    # Every switch off: a plain edit with none of the extras.
    plain = run_edit({"resolution": "720p", "sfx": False, "callouts": False, "chapter_titles": False, "music": False,
                      "intro_outro": False, "endcard": False, "watermark": False})
    assert plain["status"] == "done", plain.get("error")
    extras_off = plain["outputs"]["extras"]
    assert {k: extras_off[k] for k in ("callouts", "lower_thirds", "sfx", "music", "intro_clip", "outro_clip", "intro_card")} == {
        "callouts": 0, "lower_thirds": 0, "sfx": 0, "music": False, "intro_clip": False, "outro_clip": False,
        "intro_card": False}
    assert (extras_off["fillers_removed"], extras_off["broll"], extras_off["rings"]) == (0, 0, 0)
    assert extras_off["voice_cleanup"] == "off" and extras_off["zoom_mode"] == "off"
    assert plain["outputs"]["seconds"] < out["seconds"] - 5
    titled = run_edit({"resolution": "720p", "intro_outro": False, "intro_card": True, "title": "Quick Tour"})
    assert titled["status"] == "done", titled.get("error")
    assert titled["outputs"]["extras"]["intro_card"] and clips.probe_media(p / "autoedit.mp4")["duration"] > 2.5 + 3


# ============================================================ translated Shorts (burned-in captions per language)
def translating(prompt):
    items = json.loads(prompt.split("\n\n")[-1])
    if "French" in prompt:
        raise OSError("quota exceeded")
    return json.dumps([f"hola {t}" for t in items])


@needs_ffmpeg
def test_translated_clips_get_their_own_captions_and_a_failed_language_loses_nothing(tmp_path, monkeypatch):
    rows = [("Remember to check the level first today.", 1.0, 5.0), ("Then open the main window and look around.", 6.0, 11.0)]
    p = setup(tmp_path, monkeypatch, sentence_words(rows), 14)
    server.analyze_clip_source(PID)
    fake_llm(monkeypatch, translating)
    settings = server.short_settings({**FAST, "resolution": "540p"})
    item = {"start": 0.0, "end": 12.0, "hook": "Check the level", "title": "t", "description": "", "tags": [], "score": .5,
            "reasons": []}
    job = server.register_job(PID, "clips", settings)
    server.run_clips(PID, job, [item], settings, "center", None, ["es", "fr", "es", "xx"])
    assert server.jobs[job]["status"] == "done", server.jobs[job].get("error")
    entry = server.jobs[job]["outputs"]["clips"][0]
    assert [t["lang"] for t in entry["translations"]] == ["es"] and entry["translations"][0]["url"].endswith("/clips/1/es")
    assert [e["lang"] for e in entry["translation_errors"]] == ["fr"]
    assert "Translation to French failed" in entry["translation_errors"][0]["error"]  # a readable message, not a stack trace
    assert (p / "clip_1.mp4").is_file() and (p / "clip_1.es.mp4").is_file() and not (p / "clip_1.fr.mp4").exists()
    assert clips.probe_media(p / "clip_1.es.mp4")["height"] == 960
    ass = (p / "clip_1_es.ass").read_text(encoding="utf-8-sig")
    assert "hola" in ass and "Hook" in ass  # translated captions and the translated hook card
    assert "hola Check the level" in ass
    original = (p / "clip_1.ass").read_text(encoding="utf-8-sig")
    assert "hola" not in original  # the original-language clip is untouched
    assert server.download_translated_clip(PID, 1, "es").path.name == "clip_1.es.mp4"
    for bad in ((1, "xx"), (99, "es")):
        with pytest.raises(server.HTTPException):
            server.download_translated_clip(PID, *bad)
    import zipfile
    names = zipfile.ZipFile(server.download_bundle(PID).path).namelist()
    assert "clip_1.mp4" in names and "clip_1.es.mp4" in names


def test_translated_clips_need_a_key_before_any_work_starts(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch, sentence_words([("Hello there everyone today.", 1.0, 4.0)]), 8)
    data = server.read_project(PID)
    data["status"] = "ready"
    server.save_project(p, data)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(server.HTTPException) as caught:
        server.render_clips(PID, server.ClipsRenderRequest(clips=[{"start": 0, "end": 7}], languages=["es"]))
    assert caught.value.status_code == 409 and not server.jobs
    assert edit.cue_lines([{"start": 0, "end": 2, "text": "hola amigos"}])[0]["words"][1]["start"] == 1.0
    assert len(edit.cue_lines([{"start": 0, "end": 2, "text": "こんにちは世界こんにちは"}])[0]["words"]) == 3  # no spaces: chunked
