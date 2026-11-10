"""SkellyMotion performance helpers. Pure decisions with small, bounded hardware checks.

Hardware encoders are tested with actual output: appearing in -encoders is not proof
that a compatible GPU/driver is present. GPU acceleration is limited to H.264 encoding;
libass, text layout and some video filters still run on the CPU.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

def waveform_envelope(pcm, points: int) -> list[float]:
    """Bounded, finite display envelope for decoded mono PCM (not audio output).

    Every source sample contributes to one bin. Ignore malformed NaN/Inf and
    near-zero denormals so the editor never receives invalid JSON. This runs
    only in the background waveform worker, not in a realtime audio callback.
    """
    points = int(points)
    if not 1 <= points <= 8192:
        raise ValueError("waveform point count must be between 1 and 8192")
    count = len(pcm)
    if count == 0:
        return [0.0] * points
    peaks = []
    for i in range(points):
        start, end = (i * count) // points, ((i + 1) * count) // points
        amplitude = 0.0
        for j in range(start, end):
            sample = float(pcm[j])
            if not math.isfinite(sample) or abs(sample) < 1e-30:
                continue
            amplitude = max(amplitude, abs(sample))
        peaks.append(amplitude)
    reference = max(1e-5, sorted(peaks)[round((len(peaks) - 1) * .98)])
    return [round(min(1.0, (peak / reference) ** .65), 3)
            for peak in peaks]


PROFILES = ("eco", "balanced", "turbo")
ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf")


def profile_config(name: str, cores: int | None = None) -> dict:
    cores = max(1, int(cores if cores is not None else os.cpu_count() or 4))
    name = name if name in PROFILES else "balanced"
    threads = {"eco": max(1, min(2, cores // 2)),
               "balanced": max(1, min(6, cores - 2 if cores > 3 else cores)),
               "turbo": min(12, cores)}[name]
    return {"name": name, "threads": threads, "preview_fps": {"eco": 15, "balanced": 30, "turbo": 30}[name],
            "low_priority": name == "eco"}


def windows_child_options(low_priority: bool = False) -> dict:
    if os.name != "nt":
        return {}
    flags = subprocess.CREATE_NO_WINDOW
    if low_priority:
        flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
    return {"creationflags": flags}


@functools.lru_cache(maxsize=4)
def available_gpu_encoders(ffmpeg_executable: str = "ffmpeg") -> tuple[str, ...]:
    """Actual 3-frame encode checks with 5s limits. Cached per process."""
    binary = shutil.which(ffmpeg_executable)
    if not binary:
        return ()
    working = []
    for encoder in ENCODERS:
        args = [binary, "-hide_banner", "-loglevel", "error", "-nostdin",
                "-f", "lavfi", "-i", "color=c=black:s=160x96:r=6:d=0.5",
                "-frames:v", "3", "-pix_fmt", "nv12",
                "-c:v", encoder, "-b:v", "1M", "-f", "null", "-"]
        try:
            proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=5, **windows_child_options())
            if proc.returncode == 0:
                working.append(encoder)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return tuple(working)


def choose_encoder(mode: str, installed: tuple[str, ...]) -> str:
    if mode == "cpu":
        return "libx264"
    return installed[0] if installed else "libx264"


def encode_args(encoder: str, speed: str, width: int, height: int, threads: int) -> list[str]:
    if encoder == "libx264":
        preset, crf = {"fast": ("superfast", "22"),
                       "balanced": ("veryfast", "21"),
                       "quality": ("medium", "19")}.get(speed, ("veryfast", "21"))
        return ["-c:v", encoder, "-preset", preset, "-crf", crf,
                "-threads", str(max(1, threads)), "-pix_fmt", "yuv420p"]
    # HW encoders differ in their private rate-control options. A generic,
    # bounded bitrate is compatible with NVENC/QSV/AMF and avoids invalid presets.
    megapixels = (width * height) / 1_000_000
    bitrate = round(max(1.5, min(12.0, megapixels * (4.0 if speed == "fast" else
                                                    5.5 if speed == "balanced" else 7.0))), 1)
    return ["-c:v", encoder, "-b:v", f"{bitrate}M",
            "-maxrate", f"{round(bitrate * 1.5, 1)}M", "-bufsize", f"{round(bitrate * 3, 1)}M",
            "-pix_fmt", "nv12"]


def render_fingerprint(lines: list[dict], settings: dict, audio: Path,
                       background: Path | None, preview: bool = False) -> str:
    """Stable across restarts; invalidated by source replacement or settings edits."""
    def stamp(path: Path | None) -> tuple | None:
        if path is None or not path.is_file():
            return None
        info = path.stat()
        return (path.name, info.st_size, info.st_mtime_ns)
    payload = {"version": 3, "lines": lines, "settings": settings,
               "audio": stamp(audio), "background": stamp(background), "preview": preview}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def read_cache(path: Path) -> dict:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def store_cache(path: Path, cache: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def uncertain_words(words: list[dict], threshold: float = .60, limit: int = 45) -> list[dict]:
    """Heuristics for review prioritization; not calibrated confidence percentages."""
    uncertain = []
    for word in words:
        prob = word.get("probability")
        if isinstance(prob, (int, float)) and 0 <= prob < threshold:
            uncertain.append({"text": str(word.get("text", ""))[:70],
                              "start": round(float(word.get("start", 0)), 3),
                              "end": round(float(word.get("end", 0)), 3),
                              "probability": round(float(prob), 3)})
            if len(uncertain) >= limit:
                break
    return uncertain


def uncertain_windows(words: list[dict], duration: float, max_regions: int = 4) -> list[tuple[float, float]]:
    """Bound targeted re-analysis to a few regions, never an entire song by accident."""
    flagged = uncertain_words(words, limit=200)
    spans = []
    for item in flagged:
        start = max(0.0, item["start"] - 3.0)
        end = min(duration, item["end"] + 3.0)
        if end - start < .25:
            continue
        if spans and start <= spans[-1][1] + 1.0 and end - spans[-1][0] <= 24:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    spans.sort(key=lambda x: x[0])
    return spans[:max_regions]


_process = None


def resource_snapshot() -> dict:
    """Nullable measurements are preferable to invented CPU or GPU percentages."""
    result: dict[str, Any] = {"cpu_percent": None, "ram_mb": None,
                               "logical_cores": os.cpu_count() or 1}
    global _process
    try:
        import psutil
        if _process is None:
            _process = psutil.Process(os.getpid())
            _process.cpu_percent(None)
        result["cpu_percent"] = round(_process.cpu_percent(None) / max(1, os.cpu_count() or 1), 1)
        result["ram_mb"] = round(_process.memory_info().rss / 1024**2, 1)
        children = _process.children(recursive=True)
        result["child_ram_mb"] = round(sum(child.memory_info().rss for child in children
                                             if child.is_running()) / 1024**2, 1)
    except (ImportError, OSError, ValueError, RuntimeError):
        result["child_ram_mb"] = None
    return result
