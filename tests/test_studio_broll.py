"""B-roll: keywords from names, the placement plan, and the real overlay (picture only, text stays on top)."""
import shutil
import subprocess

import pytest

import studio_broll as broll
import studio_clips as clips
import studio_edit as edit
import studio_performance as perf

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")



def flat(image):
    """Pixels as a flat sequence (Pillow 13 deprecates getdata in favour of get_flattened_data)."""
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()

def test_keywords_from_file_names():
    assert broll.keywords_from_name("knob-close-up.mp4") == ["knob", "close"]
    assert broll.keywords_from_name("ReverbTails_final_v2 (copy).mov") == ["reverb", "tail"]
    assert broll.keywords_from_name("Compressors and Limiters.mp4") == ["compressor", "limiter"]
    assert broll.keywords_from_name("clip_001.mp4") == [] and broll.keywords_from_name("final-footage-new.webm") == []
    assert broll.keywords_from_name("waveform.mp4") == ["waveform"]
    assert broll.sanitize_keywords("Knobs, reverb ;  EQ,knob\nlimiters") == ["knob", "reverb", "eq", "limiter"]
    assert broll.sanitize_keywords("rotary knob, dial") == ["rotary", "knob", "dial"]  # a space separates keywords too
    assert len(broll.sanitize_keywords(",".join(f"word{i}" for i in range(40)))) == 12
    assert broll.stem("Glass") == "glass" and broll.stem("studies") == "study" and broll.stem("boxes") == "box"
    assert broll.slug("My Clip (1).MP4") == "my-clip-1" and broll.slug("???") == "clip"


def lib():
    return [{"name": "knob", "path": "/x/knob.mp4", "duration": 6.0, "keywords": ["knob"]},
            {"name": "wave", "path": "/x/wave.mp4", "duration": 2.0, "keywords": ["waveform", "scope"]}]


def spoken(*pairs):
    return [{"text": t, "start": s, "end": s + .4} for t, s in pairs]


def test_plan_places_clips_on_keywords_with_spacing_and_limits():
    words = spoken(("knob", 1.0), ("Turn", 5.0), ("the", 5.3), ("knobs", 10.0), ("waveform", 25.0), ("knob", 30.0),
                   ("knob", 60.0), ("knob", 90.0), ("scope", 95.0))
    plan = broll.plan_broll(words, lib(), 120.0)
    assert [p["name"] for p in plan] == ["knob", "wave", "knob"] or len(plan) >= 2
    starts = [p["start"] for p in plan]
    assert all(s >= 3.0 for s in starts)  # nothing in the first 3 seconds (the 1.0 s "knob" is skipped)
    assert all(b - a >= 18 for a, b in zip(starts, starts[1:]))
    assert all(1.2 <= p["length"] <= 3.5 for p in plan)
    wave = [p for p in plan if p["name"] == "wave"]
    assert wave and wave[0]["length"] == 2.0  # never longer than the clip itself
    assert sum(p["name"] == "knob" for p in plan) <= 2  # variety: each clip is used at most twice
    assert sum(p["length"] for p in plan) <= .12 * 120.0 + 3.5  # past the first clip, never over 12 percent of the video


def test_plan_edge_cases():
    assert broll.plan_broll(spoken(("knob", 10.0)), [], 60.0) == []
    assert broll.plan_broll([], lib(), 60.0) == []
    assert broll.plan_broll(spoken(("hello", 10.0)), lib(), 60.0) == []
    assert broll.plan_broll(spoken(("knob", 59.0)), lib(), 60.0) == []  # too close to the end
    short = broll.plan_broll(spoken(("knob", 10.0), ("knob", 11.0)), lib(), 40.0)
    assert len(short) == 1 and short[0]["start"] == pytest.approx(9.85)
    assert broll.plan_broll(spoken(("knob", 10.0)), [{"name": "tiny", "path": "p", "duration": .6, "keywords": ["knob"]}], 60) == []
    assert len(broll.plan_broll(spoken(*[("knob", 10.0 + 20 * i) for i in range(10)]), lib(), 60.0)) <= 2  # cap by length
    one = broll.plan_broll(spoken(("knob", 10.0)), lib(), 24.0)  # a short video still gets its one clip
    assert len(one) == 1 and one[0]["length"] == 3.5


def solid(path, color, seconds=4):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c={color}:s=480x270:r=15:d={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


@needs_ffmpeg
def test_broll_replaces_the_picture_only_inside_its_window_and_text_stays_on_top(tmp_path):
    from PIL import Image
    src = tmp_path / "main.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:r=15:d=10",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=10,volume=-12dB", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    red = tmp_path / "red.mp4"
    solid(red, "red")
    brand = edit.sanitize_brand({"accent": "#00FF00"})
    edit.write_motion_ass(tmp_path / "motion.ass", brand, 640, 360, [(3.0, 6.5, "Pro tip: look here")], [])
    out = tmp_path / "o.mp4"
    args, graph, seconds = edit.build_render(
        src, 640, 360, 15, out, perf.encode_args("libx264", "fast", 640, 360, 2), duration=10.0, ass_name="motion.ass",
        brand=brand, broll=[{"path": red, "start": 4.0, "length": 2.5}], script_name="g.txt")
    (tmp_path / "g.txt").write_text(graph)
    proc = subprocess.run(args, cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-600:]
    assert seconds == 10.0 and clips.probe_media(out)["duration"] == pytest.approx(10.0, abs=.4)

    def at(t):
        png = tmp_path / f"f{t}.png"
        edit.extract_frame(out, t, png)
        return Image.open(png).convert("RGB")

    before, during, after = at(3.5).getpixel((320, 300)), at(5.0).getpixel((320, 300)), at(7.0).getpixel((320, 300))
    assert before[2] > before[0] and abs(before[0] - 0x20) < 12          # original picture
    assert during[0] > 220 and during[1] < 40 and during[2] < 40          # B-roll (red) fills the frame
    assert after[2] > after[0] and abs(after[0] - 0x20) < 12              # and the picture comes back
    box = at(5.0).crop((0, 0, 320, 110))
    green = sum(1 for r, g, b in flat(box) if g > 200 and r < 80 and b < 80)
    assert green > 300, "the callout must be drawn on top of the B-roll"
    assert clips.probe_media(out)["has_audio"] is True
