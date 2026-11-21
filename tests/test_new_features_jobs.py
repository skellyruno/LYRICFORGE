"""Fillers, voice cleanup, B-roll, UI-zoom rings, presets, post text, proofreading, before/after and visualizers,
run end to end against real FFmpeg. Only Whisper and the Claude API are replaced."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import server
import studio_audio as sa
import studio_clips as clips
import studio_edit as edit

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
PID = "d" * 32
FAST = {"performanceMode": "balanced", "renderSpeed": "fast", "encoder": "cpu"}
PLAIN = {"resolution": "720p", "sfx": False, "callouts": False, "chapter_titles": False, "music": False,
         "intro_outro": False, "endcard": False, "watermark": False, "broll": False, "trim_silence": False}


def flat(image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def words_from(rows):
    out = []
    for text, start, end in rows:
        parts = text.split()
        for k, w in enumerate(parts):
            out.append({"text": w, "start": round(start + (end - start) * k / len(parts), 3),
                        "end": round(start + (end - start) * (k + 1) / len(parts) - .03, 3), "probability": .95})
    return out


def screen_video(path, seconds=26, flashes=False):
    if flashes:  # a quiet screen with small white squares appearing briefly at known spots
        ffmpeg("-f", "lavfi", "-i", f"color=c=black:s=640x360:r=15:d={seconds}", "-f", "lavfi", "-i", f"color=c=white:s=40x40:r=15:d={seconds}",
               "-f", "lavfi", "-i", f"color=c=white:s=40x40:r=15:d={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds},volume=-15dB",
               "-filter_complex", "[0:v][1:v]overlay=x=460:y=80:enable='between(t,3,3.6)'[a];[a][2:v]overlay=x=130:y=240:enable='between(t,8,8.6)'[v]",
               "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))
    else:
        ffmpeg("-f", "lavfi", "-i", f"color=c=0x203040:s=640x360:r=15:d={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds},volume=-15dB",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path))


def setup(tmp_path, monkeypatch, words, seconds=26, flashes=False):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    p = tmp_path / PID
    p.mkdir()
    screen_video(p / "source.mp4", seconds, flashes)
    server.save_project(p, {"id": PID, "kind": "clip_source", "title": "Demo", "audio_file": "source.mp4", "source_file": "source.mp4",
                            "duration": float(seconds), "status": "transcribing", "draft_lyrics": "", "original_words": [], "lines": [],
                            "settings": {}, "save_state": "saved", "use_ai": False, "keep_fillers": True})

    def fake(project_id):
        d = json.loads((server.DATA / project_id / "project.json").read_text(encoding="utf-8"))
        d.update(original_words=words, transcription_stage="complete", status="review")
        server.save_project(server.DATA / project_id, d)
    monkeypatch.setattr(server, "transcribe_project", fake)
    server.analyze_clip_source(PID)
    return p


def run_edit(opts):
    settings = server.sanitize_settings({"aspect": "landscape", **FAST})
    job = server.register_job(PID, "autoedit", settings)
    server.run_autoedit(PID, job, server.autoedit_options(server.AutoEditRequest(**opts)), settings)
    result = server.jobs[job]
    assert result["status"] == "done", result.get("error")
    return result["outputs"]


def frame(video, t, folder, name="f.png"):
    from PIL import Image
    edit.extract_frame(video, t, folder / name)
    return Image.open(folder / name).convert("RGB")


# ----------------------------------------------------------------------------- fillers + cleanup
@needs_ffmpeg
def test_filler_removal_shortens_the_video_by_the_fillers_and_cleans_the_captions(tmp_path, monkeypatch):
    rows = [("So um this is the plugin we are looking at.", 1.0, 6.0), ("Then uh you turn the drive knob up slowly.", 7.0, 12.0),
            ("And that is basically all of it for today.", 13.0, 18.0)]
    words = words_from(rows)
    p = setup(tmp_path, monkeypatch, words, 22)
    removed = sum(b - a for a, b in sa.filler_ranges(words, "basic"))
    assert 0.4 < removed < 3
    off = run_edit({**PLAIN, "fillers": "off"})
    srt_off = (p / "captions.srt").read_text(encoding="utf-8")
    on = run_edit({**PLAIN, "fillers": "basic"})
    srt_on = (p / "captions.srt").read_text(encoding="utf-8")
    assert on["extras"]["fillers_removed"] == 2 and off["extras"]["fillers_removed"] == 0
    assert off["seconds"] - on["seconds"] == pytest.approx(removed, abs=.6)
    assert " um " in srt_off and " uh " in srt_off and " um" not in srt_on and " uh" not in srt_on
    assert "plugin" in srt_on  # real words stay
    assert clips.probe_media(p / "autoedit.mp4")["duration"] == pytest.approx(on["seconds"], abs=.8)


@needs_ffmpeg
def test_voice_cleanup_runs_and_is_reported(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, words_from([("Hello and welcome to the plugin tour.", 1.0, 5.0)]), 12)
    for level in ("light", "strong"):
        assert run_edit({**PLAIN, "voice_cleanup": level})["extras"]["voice_cleanup"] == level
    assert run_edit({**PLAIN, "voice_cleanup": "bogus"})["extras"]["voice_cleanup"] == "off"  # unknown values fall back safely


# ------------------------------------------------------------------------------------ B-roll
def make_broll_clip(path, color="red", seconds=3):
    ffmpeg("-f", "lavfi", "-i", f"color=c={color}:s=480x270:r=15:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))


def test_broll_library_validates_and_manages_clips(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    red, long_clip, audio_only = tmp_path / "r.mp4", tmp_path / "l.mp4", tmp_path / "a.wav"
    make_broll_clip(red)
    make_broll_clip(long_clip, "green", 35)
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=2", str(audio_only))
    assert server.list_broll()["clips"] == []
    added = server.store_broll(red, "Knob Close-Up.mp4")
    assert added["name"] == "knob-close-up" and added["keywords"] == ["knob", "close"]
    again = server.store_broll(red, "Knob Close-Up.mp4", "dial, rotary knob")
    assert again["name"] == "knob-close-up-2" and again["keywords"] == ["dial", "rotary", "knob"]
    for bad, message in ((long_clip, "at most 30 seconds"), (audio_only, "Unsupported")):
        with pytest.raises(ValueError, match=message):
            server.store_broll(bad, "x.mp4")
    with pytest.raises(ValueError, match="no video"):
        (tmp_path / "x.mp4").write_bytes(b"not a video")
        server.store_broll(tmp_path / "x.mp4", "x.mp4")
    with pytest.raises(ValueError, match="keyword"):
        server.store_broll(red, "clip_001.mp4")  # a name with nothing to match on
    library = server.broll_library()
    assert [i["name"] for i in library] == ["knob-close-up", "knob-close-up-2"] and library[0]["duration"] == pytest.approx(3, abs=.3)
    assert server.update_broll_keywords("knob-close-up", server.BrollKeywords(keywords="Reverbs, tails"))["clips"][0]["keywords"] == ["reverb", "tail"]
    with pytest.raises(server.HTTPException):
        server.update_broll_keywords("knob-close-up", server.BrollKeywords(keywords=" , "))
    for bad_name in ("nope", "../x", "UPPER"):
        with pytest.raises(server.HTTPException):
            server.delete_broll(bad_name)
    assert [c["name"] for c in server.delete_broll("knob-close-up")["clips"]] == ["knob-close-up-2"]
    assert not (tmp_path / "_brand" / "broll" / "knob-close-up.mp4").exists()
    monkeypatch.setattr(server.broll_lib, "MAX_LIBRARY", 1)
    with pytest.raises(ValueError, match="at most 1"):
        server.store_broll(red, "another.mp4")


@needs_ffmpeg
def test_broll_appears_when_its_keyword_is_spoken(tmp_path, monkeypatch):
    rows = [("Welcome to this quick tour of the plugin today.", 0.5, 5.0), ("Now turn the knob slowly to the right.", 7.0, 11.0),
            ("That is all for now thanks for watching.", 16.0, 20.0)]
    p = setup(tmp_path, monkeypatch, words_from(rows), 24)
    red = tmp_path / "red.mp4"
    make_broll_clip(red, "red", 3)
    server.store_broll(red, "knob.mp4")
    out = run_edit({**PLAIN, "broll": True})
    assert out["extras"]["broll"] == 1
    knob = next(w for w in words_from(rows) if w["text"] == "knob")
    inside, outside = frame(p / "autoedit.mp4", knob["start"] + 1.0, tmp_path), frame(p / "autoedit.mp4", knob["start"] + 5.0, tmp_path, "g.png")
    assert inside.getpixel((320, 180))[0] > 200 and inside.getpixel((320, 180))[2] < 60   # the red B-roll
    assert outside.getpixel((320, 180))[2] > outside.getpixel((320, 180))[0]            # back to the original picture
    off = run_edit({**PLAIN, "broll": False})
    assert off["extras"]["broll"] == 0


# ------------------------------------------------------------------------- UI-event zoom + rings
@needs_ffmpeg
def test_ui_zoom_mode_zooms_to_events_and_draws_rings(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch, words_from([("Click the button here and then the other one.", 1.0, 12.0)]), 14, flashes=True)
    out = run_edit({**PLAIN, "zoom": "medium", "zoom_mode": "ui", "sfx": True})
    extras = out["extras"]
    assert extras["zoom_mode"] == "ui" and extras["rings"] == 2 and out["zoomed"]
    assert (p / "rings.ass").read_text(encoding="utf-8-sig").count("Dialogue:") == 2
    assert extras["sfx"] >= 2  # a soft tick for each ring
    motion = run_edit({**PLAIN, "zoom": "medium", "zoom_mode": "motion"})
    assert motion["extras"]["rings"] == 0 and motion["extras"]["zoom_mode"] in ("motion", "off")


# --------------------------------------------------------------------------------------- presets
def test_presets_save_normalize_and_protect_built_ins(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    assert [p["name"] for p in server.get_presets()["presets"]][:2] == ["Tutorial", "Plugin showcase"]
    saved = server.save_preset("My weekly", server.PresetRequest(options={"zoom": "ludicrous", "fillers": "more", "sfx": False,
                                                                           "title": "SECRET", "evil": "<x>", "shorts": 99}))
    mine = [p for p in saved["presets"] if p["name"] == "My weekly"][0]
    assert not mine["builtin"] and mine["options"]["zoom"] == "off" and mine["options"]["fillers"] == "more"
    assert "title" not in mine["options"] and "evil" not in mine["options"] and mine["options"]["sfx"] is False
    for bad in ("", "Tutorial", "../x", "a" * 40):
        with pytest.raises(server.HTTPException):
            server.save_preset(bad, server.PresetRequest(options={}))
    assert (tmp_path / "_brand" / "presets.json").is_file()
    assert [p["name"] for p in server.delete_preset("My weekly")["presets"]][-1] == "Minimal"
    with pytest.raises(server.HTTPException):
        server.delete_preset("Tutorial")  # built-ins are not deletable
    monkeypatch.setattr(server.posts_lib, "MAX_USER_PRESETS", 2)
    server.save_preset("One", server.PresetRequest(options={}))
    server.save_preset("Two", server.PresetRequest(options={}))
    with pytest.raises(server.HTTPException):
        server.save_preset("Three", server.PresetRequest(options={}))
    server.save_preset("One", server.PresetRequest(options={"sfx": False}))  # updating an existing one is always allowed
    for p in server.get_presets()["presets"]:  # every built-in is a valid set of options
        assert server.normalize_options(p["options"])["fillers"] == p["options"].get("fillers", "off")


# ------------------------------------------------------------------------------- platform posts
def test_posts_endpoint_validates_and_can_use_ai(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    (tmp_path / PID).mkdir()
    (tmp_path / PID / "project.json").write_text(json.dumps({"id": PID}), encoding="utf-8")
    plain = server.make_posts(PID, server.PostsRequest(title="Fix your vocal chain", text="First open the window. Then turn it.",
                                                      tags=["mixing", "eq tips"], link="https://skelly.example/tune"))
    assert plain["ai"] is False and plain["posts"]["x"]["chars"] <= 280 and "skelly.example/tune" in plain["posts"]["x"]["text"]
    with pytest.raises(server.HTTPException):
        server.make_posts(PID, server.PostsRequest(title="t", link="javascript:alert(1)"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert server.make_posts(PID, server.PostsRequest(title="t", use_ai=True))["ai"] is False  # no key: templates
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(edit, "llm_text", lambda *a, **k: json.dumps({"tiktok": "AI wrote this #mixing", "instagram": "ig", "x": "x text",
                                                                       "youtube_shorts_title": "AI title", "youtube_shorts_description": "d"}))
    smart = server.make_posts(PID, server.PostsRequest(title="t", use_ai=True))
    assert smart["ai"] is True and smart["posts"]["tiktok"]["text"] == "AI wrote this #mixing"


@needs_ffmpeg
def test_auto_edit_writes_post_text_for_every_platform(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch, words_from([("Today we look at the plugin and how it shapes tone.", 1.0, 6.0)]), 10)
    out = run_edit(PLAIN)
    assert set(out["posts"]) == {"youtube_shorts", "tiktok", "instagram", "x"}
    text = (p / "posts.txt").read_text(encoding="utf-8")
    assert "=== TikTok ===" in text and "=== X ===" in text and out["posts"]["x"]["chars"] <= 280
    assert server.download_generated_file(PID, "posts.txt").path.name == "posts.txt"


# ----------------------------------------------------------------------------- proofreading
def test_transcript_proofreading_flows_through_to_suggestions(tmp_path, monkeypatch):
    rows = [("Open the scaly tune window and look around the screen.", 1.0, 9.0), ("Then turn the drive up and listen to it.", 10.0, 18.0),
            ("That is the whole idea and it takes minutes only.", 19.0, 27.0)]
    words = words_from(rows)
    words[2]["probability"], words[3]["probability"] = .3, .25
    p = setup(tmp_path, monkeypatch, words, 30)
    uncertain = server.get_transcript(PID)
    assert uncertain["words"] == len(words) and [u["text"] for u in uncertain["uncertain"]] == ["scaly", "tune"]
    result = server.edit_transcript(PID, server.TranscriptEdits(replace=[{"find": "scaly tune", "with": "SkellyTune"}]))
    assert result["changed"] == 1 and result["uncertain"] == []
    saved = server.read_project(PID)
    assert "SkellyTune" in " ".join(w["text"] for w in saved["original_words"])
    assert any("SkellyTune" in s["text"] for s in saved["clip_suggestions"] + [{"text": ""}]) or result["suggestions"]
    assert server.edit_transcript(PID, server.TranscriptEdits(edits=[{"i": 0, "text": "Open"}]))["changed"] == 0  # no-op
    server.jobs["x"] = {"project_id": PID, "status": "rendering"}
    with pytest.raises(server.HTTPException) as caught:  # never rewrite words under a running render
        server.edit_transcript(PID, server.TranscriptEdits(edits=[{"i": 0, "text": "Hey"}]))
    assert caught.value.status_code == 409
    server.jobs.clear()
    data = server.read_project(PID)
    data["status"] = "transcribing"
    server.save_project(p, data)
    with pytest.raises(server.HTTPException):
        server.get_transcript(PID)


# ------------------------------------------------------------------- Whisper keeps the "um"s
class FakeModel:
    def __init__(self):
        self.options = None

    def transcribe(self, path, **kwargs):
        self.options = kwargs
        return iter([SimpleNamespace(end=2.0, words=[SimpleNamespace(word="Hello", start=0.5, end=1.2, probability=.9)])]), SimpleNamespace(language="en")


@pytest.mark.parametrize("keep", [True, False])
def test_filler_prompt_is_sent_only_for_videos_that_ask_for_it(tmp_path, monkeypatch, keep):
    monkeypatch.setattr(server, "DATA", tmp_path)
    p = tmp_path / PID
    p.mkdir()
    (p / "project.json").write_text(json.dumps({"id": PID, "status": "transcribing", "duration": 5.0, "audio_file": "a.wav",
                                                "keep_fillers": keep}), encoding="utf-8")
    model = FakeModel()
    monkeypatch.setattr(server, "load_model", lambda: model)
    server.transcribe_project(PID)
    if keep:
        assert model.options["initial_prompt"] == sa.FILLER_PROMPT
    else:
        assert "initial_prompt" not in model.options  # songs and old projects behave exactly as before


def test_imported_videos_ask_whisper_to_keep_fillers_and_demo_projects_stay_out_of_the_library(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "talk.mp4"
    screen_video(src, 6)
    monkeypatch.setattr(server, "media_duration", lambda path: clips.probe_media(path)["duration"])
    pid = server.import_video_file(src)
    assert server.read_project(pid)["keep_fillers"] is True
    demo = server.demo_project("ab", "Demo", {"before": src}, {"options": {}})
    ids = [item["id"] for item in server.list_saved_projects()["projects"] + server.list_saved_projects()["drafts"]]
    assert pid in ids and demo not in ids
    old = (tmp_path / "data" / demo / "project.json")
    os.utime(old, (time.time() - 5 * 86400,) * 2)
    server.prune_demo_projects()
    assert not (tmp_path / "data" / demo).exists() and (tmp_path / "data" / pid).exists()  # only stale demos are cleared


# ---------------------------------------------------------------------------- before / after
@needs_ffmpeg
def test_before_after_job_is_fair_and_stays_out_of_the_library(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    server.jobs.clear()
    before, after = tmp_path / "before.wav", tmp_path / "after.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=220:duration=14,volume=-14dB", str(before))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=14,volume=-2dB", str(after))
    opts = {**server.demo_options({"aspect": "portrait", "resolution": "720p", "title": "SkellyTune", "watermark": False}),
            "mode": "repeat", "step": 2.0, "rounds": 2, "match": True, "labels": ["BEFORE", "AFTER"], "start": 3.0}
    pid = server.demo_project("ab", "SkellyTune", {"before": before, "after": after}, {"options": opts})
    settings = server.sanitize_settings({"aspect": "landscape", **FAST})
    job = server.register_job(pid, "ab", settings)
    server.run_before_after(pid, job, opts, settings)
    result = server.jobs[job]
    assert result["status"] == "done", result.get("error")
    out = result["outputs"]
    assert out["gain_db"] == pytest.approx(-12, abs=1.5) and out["matched"] and out["seconds"] == 8.0
    video = tmp_path / "data" / pid / "ab.mp4"
    info = clips.probe_media(video)
    assert (info["width"], info["height"]) == (720, 1280) and info["has_audio"]  # a vertical A/B Short
    a = sa.rms_db(sa.decode_mono(video, start=.3, length=1.4))
    b = sa.rms_db(sa.decode_mono(video, start=2.3, length=1.4))
    assert abs(a - b) < 2.0, f"before {a:.1f} vs after {b:.1f}"
    assert not (tmp_path / "data" / pid / "ab_raw.mp4").exists()
    assert server.download_generated_file(pid, "ab.mp4").path.name == "ab.mp4"
    assert pid not in [i["id"] for i in server.list_saved_projects()["projects"]]
    short = server.register_job(pid, "ab", settings)
    server.jobs[short]["status"] = "done"
    tiny = {**opts, "mode": "toggle", "step": 10.0, "rounds": 4}
    failing = server.register_job(pid, "ab", settings)
    server.run_before_after(pid, failing, tiny, settings)
    assert server.jobs[failing]["status"] == "error" and "at least" in server.jobs[failing]["error"]  # too short for 80 seconds


# ------------------------------------------------------------------------------- visualizers
def noisy_track(path, seconds=8):
    ffmpeg("-f", "lavfi", "-i", f"aevalsrc='(random(0)-0.5)*1.4*lt(mod(t,2),1)':d={seconds}:s=48000", str(path))


@needs_ffmpeg
def test_standalone_visualizer_job_makes_a_titled_video_with_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    server.jobs.clear()
    track = tmp_path / "track.wav"
    noisy_track(track, 6)
    opts = {**server.demo_options({"aspect": "landscape", "resolution": "720p", "title": "Night Drive", "watermark": False}),
            "style": "both", "artist": "Skelly Audio"}
    pid = server.demo_project("viz", "Night Drive", {"track": track}, {"options": opts})
    settings = server.sanitize_settings({"aspect": "landscape", **FAST})
    job = server.register_job(pid, "viz", settings)
    server.run_visualizer(pid, job, opts, settings)
    assert server.jobs[job]["status"] == "done", server.jobs[job].get("error")
    video = tmp_path / "data" / pid / "visualizer.mp4"
    info = clips.probe_media(video)
    assert info["has_audio"] and (info["width"], info["height"]) == (1280, 720) and info["duration"] == pytest.approx(6.0, abs=.5)
    loud = sum(1 for r, g, b in flat(frame(video, .5, tmp_path)) if g > r + 60 and g > b + 60)
    quiet = sum(1 for r, g, b in flat(frame(video, 1.5, tmp_path, "q.png")) if g > r + 60 and g > b + 60)
    assert loud > 800 and loud > quiet * 10  # reacts to the sound
    assert (tmp_path / "data" / pid / "viz_title.ass").read_text(encoding="utf-8-sig").count("Night Drive") == 1
    assert server.download_generated_file(pid, "visualizer.mp4").path.name == "visualizer.mp4"


@needs_ffmpeg
def test_song_visualizer_becomes_the_background_of_the_lyric_video(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DATA", tmp_path)
    server.jobs.clear()
    p = tmp_path / PID
    p.mkdir()
    noisy_track(p / "song.wav", 14)
    lines = server.build_lines(words_from([("We are burning bright tonight", 1.0, 4.0), ("Never gonna let it fade away", 5.0, 9.0)]))
    server.save_project(p, {"id": PID, "title": "Test Song", "audio_file": "song.wav", "duration": 14.0, "status": "editor",
                            "draft_lyrics": "", "original_words": words_from([("We are burning bright tonight", 1.0, 4.0)]),
                            "lines": lines, "settings": {}, "save_state": "saved"})
    settings = server.sanitize_settings({"aspect": "landscape", "resolution": "540p", **FAST})
    job = server.register_job(PID, "viz", settings)
    server.run_song_visualizer(PID, job, "bars", True, settings)
    assert server.jobs[job]["status"] == "done", server.jobs[job].get("error")
    assert server.jobs[job]["outputs"]["lyrics"] is True
    assert server.read_project(PID)["background_file"] == "visualizer_bg.mp4"
    bg, lyric = p / "visualizer_bg.mp4", p / "lyric_video.mp4"
    assert not clips.probe_media(bg)["has_audio"] and clips.probe_media(lyric)["has_audio"]
    lit = sum(1 for r, g, b in flat(frame(lyric, 0.5, tmp_path)) if g > r + 60 and g > b + 60)
    assert lit > 500, "the audio-reactive background should be visible behind the lyrics"
    instrumental = server.register_job(PID, "viz", settings)
    server.jobs[job]["status"] = "done"
    data = server.read_project(PID)
    data["lines"], data["original_words"] = [], []
    server.save_project(p, data)
    server.run_song_visualizer(PID, instrumental, "wave", True, settings)
    assert server.jobs[instrumental]["outputs"]["lyrics"] is False and (p / "visualizer.mp4").is_file()
