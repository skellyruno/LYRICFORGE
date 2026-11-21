"""Tempo and beat detection on synthetic songs with a known tempo, and cut planning."""
import shutil
import subprocess

import pytest

import studio_audio as sa
import studio_beat as beat

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def click_track(path, bpm, seconds=24, offset=0.0, accent=True):
    """A pulse every beat (louder on beat 1 of each bar) over a quiet drone, so it behaves like real music."""
    period = 60.0 / bpm
    expr = (f"(0.7*sin(2*PI*900*t)*exp(-40*mod(t-{offset},{period:.5f}))*(1+{1 if accent else 0}*lt(mod(floor((t-{offset})/{period:.5f}),4),1))*gte(t,{offset})"
            f"+0.05*sin(2*PI*110*t))")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':d={seconds}:s=48000", str(path)], check=True)


@needs_ffmpeg
@pytest.mark.parametrize("bpm", [100, 120, 128, 140])
def test_tempo_and_beat_positions_are_found(tmp_path, bpm):
    path = tmp_path / "t.wav"
    click_track(path, bpm, 24, offset=.31)
    samples = sa.decode_mono(path, rate=beat.RATE)
    result = beat.analyze(samples, 24.0)
    assert result["bpm"] == pytest.approx(bpm, abs=2.0), f"asked for {bpm}, heard {result['bpm']}"
    period = 60.0 / bpm
    # every detected beat lands on a real pulse (within 45 ms), and none are missed in the middle of the song
    truth = [.31 + k * period for k in range(int((24 - .31) / period) + 1)]
    mid = [t for t in result["beats"] if 3 < t < 20]
    assert len(mid) >= int(17 / period) - 1
    for t in mid:
        assert min(abs(t - x) for x in truth) < .045, f"beat at {t:.3f}s is off the grid"
    assert 0 <= result["downbeat"] < 4 and result["bars"]


@needs_ffmpeg
def test_downbeat_is_the_accented_beat(tmp_path):
    path = tmp_path / "d.wav"
    click_track(path, 120, 24, offset=.2)
    result = beat.analyze(sa.decode_mono(path, rate=beat.RATE), 24.0)
    accented = [.2 + 2.0 * k for k in range(12)]  # the accent falls on every fourth beat: every 2.0 s at 120 BPM
    downs = [result["beats"][i] for i in range(result["downbeat"], len(result["beats"]), 4)]
    assert sum(min(abs(d - a) for a in accented) < .08 for d in downs) >= len(downs) - 1


def test_silence_and_noise_do_not_crash():
    from array import array
    assert beat.analyze(array("f", [0.0] * 5000), 0.5)["beats"] == []
    assert beat.estimate_tempo([], 86) == 0.0 and beat.beat_grid([], 86, 0, 10) == ([], 0)
    flat = array("f", [0.3] * (beat.RATE * 8))
    assert isinstance(beat.analyze(flat, 8.0)["bpm"], float)  # no beats in a flat tone: no exception


def fake_analysis(beats_n=33, bpm=120, loud_from=16):
    period = 60 / bpm
    beats = [round(i * period, 3) for i in range(beats_n)]
    bars = [{"first_beat": i, "start": beats[i], "end": beats[i + 4], "energy": 1.0 if i >= loud_from else .3}
            for i in range(0, beats_n - 4, 4)]
    return {"bpm": bpm, "beats": beats, "downbeat": 0, "bars": bars}


def test_loud_bars_cut_faster_and_flash_at_the_drop():
    analysis = fake_analysis()
    cuts = beat.plan_cuts(analysis, 16.0, "medium")
    quiet = [c for c in cuts if c["start"] < 8.0]
    loud = [c for c in cuts if c["start"] >= 8.0]
    assert all(c["beats"] == 4 for c in quiet) and all(c["beats"] == 2 for c in loud)
    assert [c["start"] for c in cuts if c["flash"]] == [8.0]  # one flash, where the loud section starts
    assert cuts[0]["start"] == 0.0 and cuts[-1]["end"] == 16.0
    assert all(abs(a["end"] - b["start"]) < 1e-6 for a, b in zip(cuts, cuts[1:]))  # no gaps, no overlaps
    hype, calm = beat.plan_cuts(analysis, 16.0, "hype"), beat.plan_cuts(analysis, 16.0, "calm")
    assert len(hype) > len(cuts) > len(calm)
    assert beat.plan_cuts({"beats": [0, .5], "bars": [], "downbeat": 0}, 3.0) == []
    assert sum(c["strong"] for c in cuts) >= 2


def test_leading_gap_before_the_first_beat_is_covered():
    analysis = fake_analysis()
    shifted = {**analysis, "beats": [b + .8 for b in analysis["beats"]]}
    cuts = beat.plan_cuts(shifted, 17.0)
    assert cuts[0]["start"] == 0.0 and cuts[0]["end"] == pytest.approx(.8) and cuts[0]["beats"] == 0
