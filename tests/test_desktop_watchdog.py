"""Guard against false-positive Windows Not Responding recovery prompts."""
import pytest

from desktop_watchdog import ConsecutiveFailureDetector, windows_ui_responding


def test_failures_must_be_consecutive():
    detector = ConsecutiveFailureDetector(threshold=3)
    assert not detector.observe(False)
    assert not detector.observe(False)
    assert not detector.observe(True)  # a responding frame resets the counter
    assert not detector.observe(False)
    assert not detector.observe(False)
    assert detector.observe(False)
    assert not detector.observe(False)  # only one user recovery prompt


def test_missing_or_inconclusive_window_is_not_a_hang():
    detector = ConsecutiveFailureDetector(threshold=2)
    assert not detector.observe(False)
    assert not detector.observe(None)
    assert not detector.observe(False)
    assert detector.observe(False)


def test_positive_threshold_required():
    with pytest.raises(ValueError):
        ConsecutiveFailureDetector(threshold=0)


def test_non_windows_native_probe_is_inconclusive():
    import os
    if os.name != "nt":
        assert windows_ui_responding("SkellyMotion | Lyric video studio") is None
