"""Actual PCM edge cases for the lyric editor's waveform display pipeline."""
from array import array
import json
import math
import time

import pytest

from studio_performance import waveform_envelope


def test_peak_and_silent_bins():
    peaks = waveform_envelope(array("f", [0, 1, 0, 0, 0, .5, 0, 0]), 4)
    assert peaks == [1.0, 0.0, round(.5 ** .65, 3), 0.0]
    assert waveform_envelope(array("f", [0] * 100), 10) == [0.0] * 10


def test_nonfinite_denormal_and_clipped_source_are_safe():
    raw = array("f", [float("nan"), float("inf"),
                      -float("inf"), 1e-40,
                      -4.0, 4.0, -0.25, 0.0])
    peaks = waveform_envelope(raw, 4)
    assert peaks[0] == 0.0
    assert peaks[1] == 0.0
    assert all(math.isfinite(x) and 0.0 <= x <= 1.0 for x in peaks)
    assert peaks[2] == 1.0
    assert "NaN" not in json.dumps({"peaks": peaks}, allow_nan=False)


def test_full_sample_coverage_and_exact_output_length():
    # Legacy stride=len(raw)//points silently omitted the final tail.
    raw = array("f", [0.0] * 1003)
    raw[-1] = 1.0
    result = waveform_envelope(raw, 100)
    assert len(result) == 100
    assert result[-1] == 1.0


def test_empty_or_tiny_audio_and_invalid_bin_counts():
    assert waveform_envelope([], 4) == [0.0] * 4
    assert len(waveform_envelope([0.5], 100)) == 100
    with pytest.raises(ValueError):
        waveform_envelope([1.0], 0)
    with pytest.raises(ValueError):
        waveform_envelope([1.0], 9000)


def test_maximum_15_minute_song_has_bounded_work():
    # 1 kHz mono analysis samples for a full 15-minute song. Ensures O(n)
    # behavior and numeric stability without relying on a machine-specific
    # real-time benchmark threshold.
    raw = array("f", [0.0]) * (900 * 1000)
    raw[1234] = 1.0
    raw[-2] = -0.7
    started = time.perf_counter()
    peaks = waveform_envelope(raw, 1200)
    elapsed = time.perf_counter() - started
    assert len(peaks) == 1200
    assert max(peaks) == 1.0
    assert peaks[-1] > 0.0
    assert all(math.isfinite(v) for v in peaks)
    print(f"15min waveform envelope CPU duration: {elapsed:.3f}s")
