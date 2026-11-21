"""Voice cleanup, filler removal, click-free cuts and loudness matching, checked on real audio."""
import math
import shutil
import subprocess
from array import array

import pytest

import studio_audio as audio
import studio_edit as edit

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


# ---------------------------------------------------------------- fillers
def test_basic_fillers_are_found_but_ordinary_words_are_not():
    words = [w("So", 0, .3), w("um,", .4, .8), w("this", 1.0, 1.3), w("is", 1.3, 1.5), w("like", 1.5, 1.8), w("Uh", 2.0, 2.3),
             w("you", 2.4, 2.6), w("know", 2.6, 2.9), w("what", 3.0, 3.3)]
    basic = audio.filler_ranges(words, "basic")
    assert basic == [(pytest.approx(.37), pytest.approx(.85)), (pytest.approx(1.97), pytest.approx(2.35))]
    more = audio.filler_ranges(words, "more")
    assert len(more) == 3 and more[2][0] == pytest.approx(2.37) and more[2][1] == pytest.approx(2.95)  # "you know"
    assert audio.filler_ranges(words, "off") == [] and audio.filler_ranges(words, "nonsense") == []
    # "like" and "know" on their own are real words; "you ... know" across a long pause is not a phrase
    far = [w("you", 0, .2), w("know", 1.5, 1.8)]
    assert audio.filler_ranges(far, "more") == []
    assert audio.filler_ranges([w("Hmm.", 1, 1.4), w("mhm", 2, 2.2)], "basic") != []


def test_ranges_are_subtracted_from_segments():
    segs = [(0.0, 10.0), (20.0, 30.0)]
    out = audio.subtract_ranges(segs, [(3.0, 3.5), (9.0, 21.0), (29.95, 31.0)])
    assert out == [(0.0, 3.0), (3.5, 9.0), (21.0, 29.95)] or out == [(0.0, 3.0), (3.5, 9.0), (21.0, 29.95)][:3]
    assert audio.subtract_ranges(segs, []) == segs
    assert audio.subtract_ranges([(0, 5)], [(0, 5)]) == []
    assert audio.subtract_ranges([(0, 5)], [(2.0, 4.9)]) == [(0.0, 2.0)]  # the 0.1 s sliver is dropped


def test_cleanup_levels():
    assert audio.voice_cleanup_filters("off") == [] and audio.voice_cleanup_filters("bogus") == []
    light, strong = audio.voice_cleanup_filters("light"), audio.voice_cleanup_filters("strong")
    assert light[0].startswith("highpass") and any(f.startswith("afftdn") for f in light) and any(f.startswith("acompressor") for f in light)
    nr = lambda fs: float([f for f in fs if f.startswith("afftdn")][0].split("nr=")[1].split(":")[0])
    assert nr(strong) > nr(light)
    assert audio.CLEANUP_LEVELS == ("off", "light", "medium", "strong") and audio.FILLER_LEVELS == ("off", "basic", "more")
    assert "um" in audio.FILLER_PROMPT.lower()


def test_loudness_matching_math():
    loud = array("f", [0.4 * math.sin(i / 7) for i in range(16000)])
    quiet = array("f", [0.1 * math.sin(i / 7) for i in range(16000)])
    gain = audio.match_gain_db(loud, quiet)
    assert gain == pytest.approx(12.0, abs=.1)  # 4x amplitude is 12 dB
    assert audio.match_gain_db(quiet, loud) == pytest.approx(-12.0, abs=.1)
    assert audio.match_gain_db(loud, array("f", [0.0] * 1000)) == 12.0  # silence is clamped, not infinite
    assert audio.rms_db(array("f", [0.0] * 100)) == -90.0


# ------------------------------------------------------------ real audio
def ffmpeg(*a):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *a], check=True)


def level(path):
    return audio.rms_db(audio.decode_mono(path))


@needs_ffmpeg
def test_cleanup_removes_rumble_and_improves_signal_to_noise(tmp_path):
    rumble = tmp_path / "rumble.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=35:duration=4,volume=8dB", str(rumble))
    out = tmp_path / "rumble_clean.wav"
    ffmpeg("-i", str(rumble), "-af", ",".join(audio.voice_cleanup_filters("medium")), str(out))
    assert level(rumble) - level(out) > 15, "35 Hz rumble should be removed by at least 15 dB"
    # A speech-level tone over a realistic room-noise floor: measured as signal-to-noise, because the
    # compressor's make-up gain lifts everything and would hide the effect in a plain level comparison.
    tone, noise = tmp_path / "tone.wav", tmp_path / "noise.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=5,volume=-2dB", str(tone))
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=a=0.01:c=white:d=5:r=48000", str(noise))
    before = level(tone) - level(noise)
    gains = {}
    for lvl in ("light", "medium", "strong"):
        chain = ",".join(audio.voice_cleanup_filters(lvl))
        ffmpeg("-i", str(tone), "-af", chain, str(tmp_path / "t.wav"))
        ffmpeg("-i", str(noise), "-af", chain, str(tmp_path / "n.wav"))
        gains[lvl] = level(tmp_path / "t.wav") - level(tmp_path / "n.wav") - before
    assert gains["light"] > 3 and gains["medium"] > 6 and gains["strong"] > 10
    assert gains["light"] < gains["medium"] < gains["strong"]  # each step really does more
    # Voice-range content keeps its level: 'light' must not mangle a 300 Hz tone.
    ffmpeg("-i", str(tone), "-af", ",".join(audio.voice_cleanup_filters("light")), str(tmp_path / "kept.wav"))
    assert abs(level(tone) - level(tmp_path / "kept.wav")) < 6.0


@needs_ffmpeg
def test_cuts_are_faded_so_joins_do_not_click(tmp_path):
    tone, out = tmp_path / "tone.wav", tmp_path / "cut.wav"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=4,volume=12dB", str(tone))
    segs = [(0.0, 1.013), (1.337, 2.0), (2.411, 3.5)]  # odd offsets so the join phases are awkward
    parts = edit.audio_cut_parts(segs)
    ffmpeg("-i", str(tone), "-filter_complex", ";".join(parts), "-map", "[acut]", "-ar", "16000", str(out))
    data = audio.decode_mono(out)
    expected = sum(b - a for a, b in segs)
    assert len(data) / 16000 == pytest.approx(expected, abs=.06)
    for join in (1.013, 1.013 + (2.0 - 1.337)):
        i = int(join * 16000)
        window = data[i - 80:i + 80]
        jump = max(abs(window[k + 1] - window[k]) for k in range(len(window) - 1))
        assert jump < .12, f"audible discontinuity at {join:.2f}s ({jump:.3f})"
    peak = max(abs(x) for x in data)
    assert .3 < peak < 1.0  # the audio between joins is untouched
    assert edit.audio_cut_parts([(0.5, 2.0)])[0].startswith("[0:a]atrim=start=0.500")  # a single piece needs no asplit


@needs_ffmpeg
def test_render_graph_applies_cleanup_before_loudness_and_cuts_with_fades(tmp_path):
    src = tmp_path / "v.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=320x180:r=15:d=6", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
    import studio_performance as perf
    args, graph, seconds = edit.build_render(
        src, 320, 180, 15, tmp_path / "o.mp4", perf.encode_args("libx264", "fast", 320, 180, 2), duration=6.0,
        segments=[(0.0, 2.0), (3.0, 6.0)], loudness=-14, voice_filters=audio.voice_cleanup_filters("light"))
    assert graph.index("highpass") < graph.index("loudnorm") and "atrim=start=0.000" in graph and "aselect" not in graph
    (tmp_path / "graph.txt").write_text(graph)
    assert subprocess.run(args, cwd=tmp_path, capture_output=True).returncode == 0
    assert seconds == 5.0
