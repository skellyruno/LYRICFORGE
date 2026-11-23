"""SkellyMotion: local-first lyric video editor and renderer."""
from __future__ import annotations

import difflib
import gc
import hashlib
import base64
import secrets
import tempfile
import sys
from urllib.parse import urlsplit
from array import array
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import studio_performance as perf
import studio_clips as clips
import studio_audio as sa
import studio_broll as broll_lib
import studio_focus as focus
import studio_post as posts_lib
import studio_viz as viz_lib
import studio_proof as proof
import studio_edit as edit

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
DATA = Path(os.environ.get("LYRICFORGE_DATA", ROOT / "workspace")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
STATIC = ROOT / "static"
MAX_UPLOAD = 250 * 1024 * 1024
MAX_DURATION = 15 * 60
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm", ".mp4"}
BG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"}
PRESETS = {
    "midnight": ("#101418", "#020605", "#6fff87"),
    "acid": ("#15372b", "#07120f", "#72ff68"),
    "violet": ("#35244a", "#0e0c1c", "#bb8cfa"),
    "crimson": ("#4b1d2d", "#130911", "#fb5d88"),
    "ocean": ("#16445d", "#06121f", "#6be4ff"),
    "noir": ("#282b31", "#050505", "#b3b8bc"),
    "sunset": ("#4a2449", "#170c23", "#ffad7a"),
    "arctic": ("#234c61", "#071c29", "#a7edff"),
}
FONTS = {"Arial", "DejaVu Sans", "Liberation Sans", "Impact", "Georgia", "Courier New"}
ANIMATIONS = {"fade", "pop", "slide", "typewriter", "zoom", "bounce", "blur", "pulse", "none"}
MODES = {"line", "word", "karaoke"}
SIZES = {"portrait": (720, 1280), "landscape": (1280, 720), "square": (720, 720)}
executor = ThreadPoolExecutor(max_workers=2)
ai_executor = ThreadPoolExecutor(max_workers=1)  # Do not run two CPU-heavy AI passes at once.
model_lock = threading.Lock()
model_request = threading.local()  # First model load uses the selected CPU profile.
transcript_cache_lock = threading.Lock()
_model: Any = None
jobs: dict[str, dict[str, Any]] = {}
job_lock = threading.Lock()
app = FastAPI(title="SkellyMotion", version="0.9.0")


@app.middleware("http")
async def owner_only_http_basic(request: Request, call_next):
    """Fail closed on the hosted website; local Windows app stays loopback-only.

    Railway terminates TLS; never expose the host directly using plain HTTP.
    Basic Auth is intentional for a single-owner MVP, NOT a multi-user SaaS.
    """
    if request.url.path == "/health":
        return await call_next(request)
    if os.environ.get("LYRICFORGE_REQUIRE_AUTH") == "1":
        expected_user = os.environ.get("LYRICFORGE_AUTH_USER", "")
        expected_password = os.environ.get("LYRICFORGE_AUTH_PASSWORD", "")
        if not expected_user or not expected_password or len(expected_password) < 12:
            return PlainTextResponse("Owner credentials are not configured", status_code=503)
        token = request.headers.get("authorization", "")
        try:
            scheme, encoded = token.split(" ", 1)
            if scheme.lower() != "basic":
                raise ValueError("Not basic auth")
            supplied = base64.b64decode(encoded, validate=True).decode("utf-8")
            user, separator, password = supplied.partition(":")
            valid = bool(separator) and secrets.compare_digest(user, expected_user) and secrets.compare_digest(password, expected_password)
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            return PlainTextResponse("Sign in to SkellyMotion", status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="SkellyMotion"', "Cache-Control": "no-store"})
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            # Block credentialed cross-site writes (GitHub / Railway do not need cross-origin access).
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() != request.headers.get("host", "").lower():
                    return PlainTextResponse("Cross-site request denied", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}



def project_dir(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", project_id):
        raise HTTPException(404, "Project not found")
    p = DATA / project_id
    if not (p / "project.json").exists():
        raise HTTPException(404, "Project not found")
    return p


def read_project(project_id: str) -> dict:
    return json.loads((project_dir(project_id) / "project.json").read_text(encoding="utf-8"))


def save_project(p: Path, data: dict) -> None:
    tmp = p / "project.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p / "project.json")


def silent_subprocess_flags() -> dict:
    """Never show cmd/FFmpeg windows from the packaged Windows GUI app."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                            **silent_subprocess_flags())
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1200:])
    return result


def media_duration(path: Path) -> float:
    """Read media duration with PyAV or the existing FFmpeg binary, not FFprobe.

    Full desktop/AI builds keep the accurate PyAV path. Lightweight source
    installations without the AI stack can still inspect media with FFmpeg.
    """
    try:
        import av
    except ImportError:
        seconds = clips.probe_media(path)["duration"]
        if math.isfinite(seconds) and seconds > 0:
            return seconds
        raise ValueError("The uploaded audio/video has no readable duration")
    try:
        container = av.open(str(path))
    except Exception as exc:
        # A corrupt file raises PyAV InvalidDataError (not ValueError).
        # Normalize only container-open errors so the API can return HTTP 400.
        raise ValueError("The uploaded audio/video has no readable duration") from exc
    with container as media:
        if media.duration is not None and media.duration > 0:
            duration = float(media.duration) / float(av.time_base)
            if math.isfinite(duration):
                return duration
        values = []
        for stream in media.streams:
            if stream.duration is not None and stream.time_base is not None:
                seconds = float(stream.duration * stream.time_base)
                if math.isfinite(seconds) and seconds > 0:
                    values.append(seconds)
        if values:
            return max(values)
    raise ValueError("The uploaded audio/video has no readable duration")


def video_stream_width(path: Path) -> int:
    """Check a picture/video stream with PyAV or existing FFmpeg if unavailable."""
    try:
        import av
    except ImportError:
        info = clips.probe_media(path)
        if info["has_video"] and info["width"] > 0 and info["height"] > 0:
            return info["width"]
        raise ValueError("Background file has no readable video/image stream")
    try:
        container = av.open(str(path))
    except Exception as exc:
        raise ValueError("Background file has no readable video/image stream") from exc
    with container as media:
        for stream in media.streams:
            if stream.type == "video":
                width = int(stream.codec_context.width or 0)
                height = int(stream.codec_context.height or 0)
                if width > 0 and height > 0:
                    return width
    raise ValueError("Background file has no readable video/image stream")


async def save_upload(file: UploadFile, dest: Path, limit: int | None = None) -> None:
    size = 0
    cap = limit or MAX_UPLOAD
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > cap:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {cap // (1024 * 1024)} MB limit")
            out.write(chunk)
    if not size:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Empty upload")


def load_model():
    global _model
    with model_lock:
        if _model is None:
            from faster_whisper import WhisperModel  # loads only if transcription is requested
            name = os.getenv("WHISPER_MODEL", "small")
            device = os.getenv("WHISPER_DEVICE", "cpu")
            compute = "float16" if device == "cuda" else "int8"
            options = {"device": device, "compute_type": compute}
            if device == "cpu":
                # The first transcription selects CPU threading; the model stays
                # warm afterward to avoid expensive reloads between songs.
                profile = getattr(model_request, "profile", "balanced")
                options["cpu_threads"] = perf.profile_config(profile)["threads"]
                options["num_workers"] = 1
            _model = WhisperModel(name, **options)
    return _model


def audio_digest(path: Path) -> str:
    """Stream-hash an uploaded song without loading it fully into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcription_cache_key(audio: Path, options: dict) -> str:
    data = {"version": 1, "audio": audio_digest(audio),
            "model": os.getenv("WHISPER_MODEL", "small"),
            "device": os.getenv("WHISPER_DEVICE", "cpu"),
            "mode": options.get("recognition_mode", "balanced"),
            "language": options.get("language_hint", "auto"),
            "vocabulary": options.get("vocabulary_hint", "")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def lookup_transcript(data: dict, audio: Path) -> bool:
    """Reuse machine-generated timings only; never copy another project's manual edits."""
    key = transcription_cache_key(audio, data)
    data["transcription_cache_key"] = key
    with transcript_cache_lock:
        entry = perf.read_cache(DATA / "transcription_cache.json").get(key)
    if not isinstance(entry, dict) or not isinstance(entry.get("words"), list):
        return False
    words = entry["words"]
    if not words or len(words) > 10000:
        return False
    data["original_words"] = words
    data["draft_lyrics"] = "\n".join(line["text"] for line in build_lines(words))
    data["review_uncertain"] = perf.uncertain_words(words)
    data["language"] = entry.get("language")
    data["status"] = "review"
    data["transcription_stage"] = "cached"
    data["transcription_progress"] = 100
    data["transcription_cached"] = True
    return True


def remember_transcript(data: dict) -> None:
    key = data.get("transcription_cache_key")
    words = data.get("original_words") or []
    if not isinstance(key, str) or not isinstance(words, list) or not words:
        return
    with transcript_cache_lock:
        cache = perf.read_cache(DATA / "transcription_cache.json")
        cache[key] = {"words": words, "language": data.get("language"),
                      "created": time.time()}
        if len(cache) > 40:
            for obsolete in sorted(cache, key=lambda k: cache[k].get("created", 0))[:-40]:
                cache.pop(obsolete, None)
        try:
            perf.store_cache(DATA / "transcription_cache.json", cache)
        except OSError:
            pass


def build_lines(words: list[dict], max_words: int = 6) -> list[dict]:
    """Group recognized words by gaps and punctuation, maintaining timestamps."""
    result: list[dict] = []
    group: list[dict] = []
    for w in words:
        if group and (len(group) >= max_words or float(w["start"]) - float(group[-1]["end"]) > 0.7):
            result.append(line_from_words(group))
            group = []
        group.append(w)
        if re.search(r"[.!?]$", w["text"]) and len(group) >= 3:
            result.append(line_from_words(group))
            group = []
    if group:
        result.append(line_from_words(group))
    return result


def line_from_words(words: list[dict]) -> dict:
    return {"id": uuid.uuid4().hex[:10], "start": round(float(words[0]["start"]), 3),
            "end": round(float(words[-1]["end"]), 3), "text": " ".join(w["text"] for w in words),
            "words": words}


def tokenize(text: str) -> list[str]:
    return re.findall(r"\S+", text.strip())


def normalize_word(word: str) -> str:
    return re.sub(r"[^\w]", "", word, flags=re.UNICODE).lower()


def align_confirmed(lyrics: str, old_words: list[dict], duration: float) -> list[dict]:
    """Transfer ASR timings to corrected text, interpolate additions/replacements.

    This is timing *estimation*, not acoustic forced alignment. Users can fine-tune.
    """
    raw_lines = [tokenize(line) for line in lyrics.splitlines() if tokenize(line)]
    if not raw_lines:
        raise ValueError("Enter at least one lyric line")
    if sum(map(len, raw_lines)) > 2000:
        raise ValueError("Maximum 2,000 words per project")
    new_text = [w for ln in raw_lines for w in ln]
    if not old_words:
        # Manual workflow: spread lines over the song; these timings are rough.
        interval = duration / max(1, len(new_text))
        old_words = []
        for i, word in enumerate(new_text):
            start = min(duration - 0.05, i * interval)
            old_words.append({"text": word, "start": max(0, start), "end": min(duration, start + interval * 0.85)})
    matcher = difflib.SequenceMatcher(None,
        [normalize_word(w["text"]) for w in old_words],
        [normalize_word(w) for w in new_text], autojunk=False)
    aligned: list[dict | None] = [None] * len(new_text)
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == "equal":
            for old_i, new_i in zip(range(a, b), range(c, d)):
                old = old_words[old_i]
                aligned[new_i] = {"text": new_text[new_i], "start": float(old["start"]), "end": float(old["end"]),
                                  **({"probability": old["probability"]} if "probability" in old else {})}
        elif tag in ("replace", "insert") and d > c:
            # Prefer source speech region for substitutions; insertions use local neighboring bounds.
            left = float(old_words[a]["start"]) if a < b else (float(old_words[a - 1]["end"]) if a else 0)
            right = float(old_words[b - 1]["end"]) if a < b else (float(old_words[a]["start"]) if a < len(old_words) else duration)
            if right - left < .08 * (d - c):
                right = min(duration, left + .12 * (d - c))
            for i in range(c, d):
                s = left + (right - left) * (i - c) / (d - c)
                e = left + (right - left) * (i - c + 1) / (d - c)
                aligned[i] = {"text": new_text[i], "start": s, "end": e}
    # Clamp times to valid, nonnegative values and preserve word ordering.
    final_words = []
    for i, item in enumerate(aligned):
        item = item or {"text": new_text[i], "start": 0, "end": .2}
        s = max(0, min(float(item["start"]), duration - .01))
        e = max(s + .03, min(float(item["end"]), duration))
        final_words.append({"text": item["text"], "start": round(s, 3), "end": round(e, 3),
                            **({"probability": item["probability"]} if "probability" in item else {})})
    lines = []
    offset = 0
    for raw in raw_lines:
        group = final_words[offset:offset + len(raw)]
        lines.append(line_from_words(group))
        offset += len(raw)
    return lines


RECOGNITION_MODES = {"fast": 1, "balanced": 3, "accurate": 5}
RECOGNITION_LANGUAGES = {"auto", "en", "es", "fr", "pt", "de", "it", "ja", "ko"}


def recognition_options(mode: str, language: str, vocabulary: str = "",
                        performance_mode: str = "balanced") -> dict:
    """Same-model decoding effort and bounded user-supplied vocabulary hints."""
    return {
        "recognition_mode": mode if isinstance(mode, str) and mode in RECOGNITION_MODES else "balanced",
        "language_hint": language if isinstance(language, str) and language in RECOGNITION_LANGUAGES else "auto",
        **({"vocabulary_hint": " ".join(vocabulary.split())[:300]} if vocabulary else {}),
        **({"performanceMode": performance_mode} if performance_mode in perf.PROFILES
           and performance_mode != "balanced" else {}),
    }


def transcription_beam_size() -> int:
    """Faster decoding on the SAME Whisper small model, with an accuracy override."""
    try:
        return max(1, min(5, int(os.getenv("SKELLYMOTION_BEAM_SIZE", "3"))))
    except (TypeError, ValueError):
        return 3


def update_transcription_stage(project_path: Path, stage: str, progress: int) -> None:
    """Publish real audio-position progress; no invented ETA."""
    data = json.loads((project_path / "project.json").read_text(encoding="utf-8"))
    if data.get("status") != "transcribing":
        return
    data["transcription_stage"] = stage
    data["transcription_progress"] = max(0, min(99, int(progress)))
    save_project(project_path, data)


def transcribe_project(project_id: str) -> None:
    p = DATA / project_id
    d = json.loads((p / "project.json").read_text(encoding="utf-8"))
    try:
        update_transcription_stage(p, "loading_model", 0)
        model_request.profile = d.get("performanceMode", "balanced")
        model = load_model()
        update_transcription_stage(p, "recognizing", 0)
        # Beam search 3 (previously 5), one decoding temperature and one
        # candidate: less CPU work without changing model size, word timestamps,
        # or the ability to correct lyrics after transcription.
        mode = d.get("recognition_mode")
        # Keep SKELLYMOTION_BEAM_SIZE working for Balanced and legacy projects.
        beam = 1 if mode == "fast" else 5 if mode == "accurate" else transcription_beam_size()
        language = d.get("language_hint")
        vocabulary = str(d.get("vocabulary_hint") or "")[:300]
        started = time.monotonic()
        segs, info = model.transcribe(
            str(p / d["audio_file"]), word_timestamps=True,
            beam_size=beam, best_of=1, temperature=0,
            language=language if language in RECOGNITION_LANGUAGES and language != "auto" else None,
            hotwords=vocabulary or None,
            **({"initial_prompt": sa.FILLER_PROMPT} if d.get("keep_fillers") else {}),
            vad_filter=False, condition_on_previous_text=False)
        words = []
        duration = max(0.1, float(d.get("duration", 1)))
        last_pct, last_update = 0, time.monotonic()
        for seg in segs:
            for w in seg.words or []:
                word = w.word.strip()
                if word:
                    item = {"text": word, "start": round(float(w.start), 3),
                            "end": round(float(w.end), 3)}
                    probability = getattr(w, "probability", None)
                    if isinstance(probability, (float, int)) and math.isfinite(probability):
                        item["probability"] = round(float(probability), 3)
                    words.append(item)
            pct = min(99, round(max(0, float(seg.end)) / duration * 100))
            now = time.monotonic()
            if pct >= last_pct + 5 and now - last_update >= 0.5:
                update_transcription_stage(p, "recognizing", pct)
                last_pct, last_update = pct, now
        d = json.loads((p / "project.json").read_text(encoding="utf-8"))
        d["original_words"] = words
        d["review_uncertain"] = perf.uncertain_words(words)
        d["transcription_seconds"] = round(time.monotonic() - started, 2)
        d["draft_lyrics"] = "\n".join(ln["text"] for ln in build_lines(words))
        d["status"] = "review"
        d["transcription_stage"] = "complete"
        d["transcription_progress"] = 100
        d["language"] = info.language
    except Exception as exc:
        d = json.loads((p / "project.json").read_text(encoding="utf-8"))
        d["status"] = "review"
        d["transcription_stage"] = "error"
        d["transcription_error"] = str(exc)[:600]
        d["draft_lyrics"] = ""
    save_project(p, d)
    if d.get("transcription_stage") == "complete":
        remember_transcript(d)


def refine_uncertain_project(project_id: str, job_id: str) -> None:
    """Optional targeted second Whisper pass, with NO automatic changes to lyrics."""
    started = time.monotonic()
    try:
        p = project_dir(project_id)
        data = read_project(project_id)
        if data.get("status") != "review":
            raise ValueError("Refinement is only available before you confirm lyrics")
        original = data.get("original_words") or []
        regions = perf.uncertain_windows(original, float(data["duration"]), max_regions=4)
        if not regions:
            with job_lock:
                jobs[job_id].update(status="done", progress=100, suggestions=[],
                                    elapsed_seconds=0, stage="no_uncertainty")
            return
        model_request.profile = data.get("performanceMode", "balanced")
        model = load_model()  # Same already downloaded Whisper small model.
        vocabulary = str(data.get("vocabulary_hint") or "")[:300]
        language = data.get("language_hint")
        source = p / data["audio_file"]
        proposals = []
        all_words = list(original)
        with tempfile.TemporaryDirectory(prefix="lyric-refine-", dir=p) as folder:
            folder_path = Path(folder)
            for index, (start, end) in enumerate(regions):
                extracted = folder_path / f"region-{index}.wav"
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                     "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
                     "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                     "-c:a", "pcm_s16le", str(extracted)])
                segments, _ = model.transcribe(
                    str(extracted), beam_size=5, best_of=1, temperature=0,
                    word_timestamps=True, vad_filter=False,
                    condition_on_previous_text=False,
                    language=language if language in RECOGNITION_LANGUAGES and language != "auto" else None,
                    hotwords=vocabulary or None)
                candidates = []
                for segment in segments:
                    for word in segment.words or []:
                        text = word.word.strip()
                        if not text:
                            continue
                        ws = round(max(start, start + float(word.start)), 3)
                        we = round(min(end, start + float(word.end)), 3)
                        if we <= ws:
                            continue
                        item = {"text": text, "start": ws, "end": we}
                        confidence = getattr(word, "probability", None)
                        if isinstance(confidence, (float, int)) and math.isfinite(confidence):
                            item["probability"] = round(float(confidence), 3)
                        candidates.append(item)
                if candidates:
                    baseline = [w for w in original
                                if start <= (float(w["start"]) + float(w["end"])) / 2 <= end]
                    proposals.append({"start": round(start, 2), "end": round(end, 2),
                                      "before": " ".join(w["text"] for w in baseline),
                                      "suggested": " ".join(w["text"] for w in candidates)})
                    all_words = [w for w in all_words
                                 if not start <= (float(w["start"]) + float(w["end"])) / 2 <= end]
                    all_words.extend(candidates)
                with job_lock:
                    jobs[job_id].update(progress=round((index + 1) / len(regions) * 99),
                                        stage="refining")
        if read_project(project_id).get("status") != "review":
            raise ValueError("Lyrics were confirmed before refinement finished")
        all_words.sort(key=lambda w: (float(w["start"]), float(w["end"])))
        data = read_project(project_id)
        data["refinement_proposal"] = {
            "words": all_words,
            "draft": "\n".join(ln["text"] for ln in build_lines(all_words)),
            "suggestions": proposals,
        }
        save_project(p, data)
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100,
                                suggestions=proposals,
                                elapsed_seconds=round(time.monotonic() - started, 2))
    except Exception as exc:
        with job_lock:
            jobs[job_id].update(status="error", stage="error", error=str(exc)[:500])


@app.post("/api/projects/{project_id}/refine")
def request_refine(project_id: str):
    data = read_project(project_id)
    if data.get("status") != "review":
        raise HTTPException(409, "Refinement is available before confirming lyrics")
    with job_lock:
        if any(j.get("project_id") == project_id and j.get("status") == "refining"
               for j in jobs.values()):
            raise HTTPException(409, "Refinement is already running")
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"id": job_id, "project_id": project_id, "status": "refining",
                        "stage": "queued", "progress": 0, "created": time.time()}
    ai_executor.submit(refine_uncertain_project, project_id, job_id)
    return {"job_id": job_id}


@app.post("/api/projects/{project_id}/refine/apply")
def accept_refine(project_id: str):
    data = read_project(project_id)
    proposal = data.get("refinement_proposal")
    if data.get("status") != "review" or not isinstance(proposal, dict):
        raise HTTPException(409, "No refinement proposal awaiting review")
    if not proposal.get("words"):
        raise HTTPException(409, "No refined words to apply")
    data["original_words"] = proposal["words"]
    data["review_uncertain"] = perf.uncertain_words(proposal["words"])
    data["draft_lyrics"] = proposal["draft"]
    del data["refinement_proposal"]
    save_project(project_dir(project_id), data)
    return {"draft_lyrics": data["draft_lyrics"],
            "review_uncertain": data["review_uncertain"], "applied": True}


class ConfirmRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=30000)


class SaveRequest(BaseModel):
    lines: list[dict]
    settings: dict


class RecoveryRequest(BaseModel):
    lines: list[dict] = []
    settings: dict = {}
    draft_lyrics: str = ""


class BulkDeleteRequest(BaseModel):
    project_ids: list[str]
    confirm: bool = False


class RenderRequest(BaseModel):
    settings: dict
    lines: list[dict]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/projects")
def list_saved_projects():
    """Only explicitly saved projects go in the main library.

    New uploads live as recoverable drafts until Save is pressed. Old
    projects with no save_state are treated as saved for compatibility.
    """
    recent, drafts = [], []
    if not DATA.exists():
        return {"projects": [], "drafts": []}
    for folder in DATA.iterdir():
        if not folder.is_dir() or folder.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}", folder.name):
            continue
        manifest = folder / "project.json"
        if not manifest.is_file() or manifest.is_symlink():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("kind") in ("ab", "viz"):
                continue  # one-off demo videos live in storage but not in the song library
            recovery = folder / "recovery.json"
            item = {
                "id": folder.name,
                "title": str(data.get("title") or "Untitled project")[:100],
                "duration": float(data.get("duration") or 0),
                "status": str(data.get("status") or "unknown")[:30],
                "updated_at": max(manifest.stat().st_mtime,
                                  recovery.stat().st_mtime if recovery.is_file() else 0),
                "lines": len(data.get("lines") or []),
                "save_state": "draft" if data.get("save_state") == "draft" else "saved",
                "has_recovery": recovery.is_file(),
                "kind": "clip_source" if data.get("kind") == "clip_source" else "song",
            }
            (drafts if item["save_state"] == "draft" else recent).append(item)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    recent.sort(key=lambda item: item["updated_at"], reverse=True)
    drafts.sort(key=lambda item: item["updated_at"], reverse=True)
    return {"projects": recent[:250], "drafts": drafts[:250]}


def recovery_file(project_id: str) -> Path:
    return project_dir(project_id) / "recovery.json"


@app.get("/api/projects/{project_id}/recovery")
def read_recovery(project_id: str):
    record = recovery_file(project_id)
    if not record.is_file() or record.is_symlink():
        raise HTTPException(404, "No crash-recovery draft")
    try:
        value = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Not a recovery draft")
        return value
    except (ValueError, OSError):
        raise HTTPException(422, "Recovery draft is unreadable")


@app.put("/api/projects/{project_id}/recovery")
def store_recovery(project_id: str, body: RecoveryRequest):
    """Crash protection ONLY; never commits saved project content."""
    data = read_project(project_id)
    path = recovery_file(project_id)
    previous = perf.read_cache(path)
    values = {
        "lines": validate_lines(body.lines, data["duration"]),
        "settings": sanitize_settings(body.settings),
        "draft_lyrics": body.draft_lyrics[:60000],
        "updated_at": time.time(),
    }
    if previous.get("pending_background"):
        values["pending_background"] = previous["pending_background"]
    staging = path.with_suffix(".tmp")
    staging.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    staging.replace(path)
    return {"recovered": True, "saved": False}


def assert_can_delete_project(project_id: str) -> Path:
    folder = project_dir(project_id)
    if folder.is_symlink():
        raise HTTPException(400, "Cannot delete linked project folders")
    with job_lock:
        if any(job.get("project_id") == project_id
               and job.get("status") in {"rendering", "refining"} for job in jobs.values()):
            raise HTTPException(409, "Finish the active render/refinement before deleting")
    # Transcription may still have files open; keep the draft until AI finishes.
    if read_project(project_id).get("status") == "transcribing":
        raise HTTPException(409, "Finish lyric detection before deleting this draft")
    return folder


@app.post("/api/projects/bulk-delete")
def bulk_delete_projects(body: BulkDeleteRequest):
    if not body.confirm:
        raise HTTPException(400, "Confirm deletion of the selected projects")
    ids = body.project_ids
    if not ids or len(ids) > 250 or len(ids) != len(set(ids)):
        raise HTTPException(400, "Select between 1 and 250 unique projects")
    folders = [assert_can_delete_project(i) for i in ids]
    for path in folders:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise HTTPException(500, "Could not delete " + path.name + ": " + str(exc))
    return {"deleted_ids": ids, "count": len(ids),
            "model_cache_untouched": True}


@app.post("/api/projects/{project_id}/discard")
def discard_working_project(project_id: str):
    data = read_project(project_id)
    if data.get("save_state") == "draft":
        folder = assert_can_delete_project(project_id)
        shutil.rmtree(folder)
        return {"deleted": True, "kept_saved_project": False}
    # Don't Save on a previously saved project retains its last Save.
    pending = perf.read_cache(recovery_file(project_id)).get("pending_background")
    recovery_file(project_id).unlink(missing_ok=True)
    if isinstance(pending, str) and pending.startswith("background-pending-"):
        (project_dir(project_id) / pending).unlink(missing_ok=True)
    return {"deleted": False, "kept_saved_project": True}


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), recognition: str = Form("balanced"),
                         language: str = Form("auto"), vocabulary: str = Form(""),
                         performance_mode: str = Form("balanced")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(400, "Upload MP3, WAV, M4A, FLAC, OGG, AAC, MP4 or WebM")
    project_id = uuid.uuid4().hex
    p = DATA / project_id
    p.mkdir(parents=True)
    name = "song" + ext
    try:
        await save_upload(file, p / name)
        try:
            duration = media_duration(p / name)
        except (ValueError, OSError) as exc:
            raise HTTPException(400, "Cannot read audio/video file") from exc
        if not 0.25 < duration <= MAX_DURATION:
            raise HTTPException(400, "Audio length must be between 0.25 seconds and 15 minutes")
        data = {"id": project_id, "title": Path(file.filename or "My Song").stem[:100],
                "audio_file": name, "duration": duration, "status": "transcribing",
                "draft_lyrics": "", "original_words": [], "lines": [], "settings": {}, "language": None,
                "transcription_stage": "queued", "transcription_progress": 0,
                "save_state": "draft",
                **recognition_options(recognition, language, vocabulary, performance_mode)}
        reused = lookup_transcript(data, p / name)
        save_project(p, data)
        if not reused:
            ai_executor.submit(transcribe_project, project_id)
        return {"id": project_id, "duration": duration,
                "status": data["status"], "transcription_cached": reused}
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


def import_desktop_audio_file(source: Path, recognition: str = "balanced",
                              language: str = "auto", vocabulary: str = "",
                              performance_mode: str = "balanced") -> dict:
    """Import only the file explicitly selected in the native Windows dialog.

    This is a Python-only function, not an HTTP endpoint, so a web page cannot
    ask the local server to read arbitrary files from the user's computer.
    """
    source = Path(source)
    ext = source.suffix.lower()
    if ext not in AUDIO_EXT:
        raise ValueError("Choose an MP3, WAV, M4A, FLAC, OGG, AAC, MP4 or WebM song")
    if not source.is_file():
        raise ValueError("The selected song was not found")
    if not 0 < source.stat().st_size <= MAX_UPLOAD:
        raise ValueError("Song must be between 1 byte and 250 MB")
    project_id = uuid.uuid4().hex
    p = DATA / project_id
    p.mkdir(parents=True)
    name = "song" + ext
    try:
        shutil.copyfile(source, p / name)
        duration = media_duration(p / name)
        if not 0.25 < duration <= MAX_DURATION:
            raise ValueError("Audio length must be between 0.25 seconds and 15 minutes")
        title = source.stem[:100]
        data = {"id": project_id, "title": title, "audio_file": name,
                "duration": duration, "status": "transcribing",
                "draft_lyrics": "", "original_words": [], "lines": [],
                "settings": {}, "language": None,
                "transcription_stage": "queued", "transcription_progress": 0,
                "save_state": "draft",
                **recognition_options(recognition, language, vocabulary, performance_mode)}
        reused = lookup_transcript(data, p / name)
        save_project(p, data)
        if not reused:
            ai_executor.submit(transcribe_project, project_id)
        return {"id": project_id, "duration": duration,
                "status": data["status"], "title": title,
                "transcription_cached": reused}
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


def background_destination(project_id: str, ext: str) -> Path:
    d = read_project(project_id)
    prefix = "background" if d.get("save_state") == "draft" else "background-pending-" + uuid.uuid4().hex
    return project_dir(project_id) / (prefix + ext)


def register_background(project_id: str, dest: Path) -> dict:
    """Record imported background as a recovery-only edit for saved projects."""
    p = project_dir(project_id)
    d = read_project(project_id)
    if d.get("save_state") != "draft":
        path = recovery_file(project_id)
        recovery = perf.read_cache(path)
        previous = recovery.get("pending_background")
        recovery["pending_background"] = dest.name
        recovery["updated_at"] = time.time()
        staged = path.with_suffix(".tmp")
        staged.write_text(json.dumps(recovery, ensure_ascii=False), encoding="utf-8")
        staged.replace(path)
        if isinstance(previous, str) and previous != dest.name and previous.startswith("background-pending-"):
            (p / previous).unlink(missing_ok=True)
        return {"background_url": f"/api/projects/{project_id}/background?pending=1",
                "name": dest.name}
    previous = d.get("background_file")
    d["background_file"] = dest.name
    save_project(p, d)
    if previous and previous != dest.name:
        (p / previous).unlink(missing_ok=True)
    return {"background_url": f"/api/projects/{project_id}/background",
            "name": dest.name}


def import_desktop_background_file(project_id: str, source: Path) -> dict:
    """Native background picker, with same crash-recovery handling as web uploads."""
    source = Path(source)
    ext = source.suffix.lower()
    if ext not in BG_EXT or not source.is_file():
        raise ValueError("Choose a JPG, PNG, WebP, MP4, MOV or WebM background")
    if not 0 < source.stat().st_size <= MAX_UPLOAD:
        raise ValueError("Background must be between 1 byte and 250 MB")
    dest = background_destination(project_id, ext)
    try:
        shutil.copyfile(source, dest)
        video_stream_width(dest)
        return register_background(project_id, dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    data = read_project(project_id)
    data["save_state"] = "draft" if data.get("save_state") == "draft" else "saved"
    data["has_recovery"] = recovery_file(project_id).is_file()
    return data


@app.get("/api/projects/{project_id}/audio")
def get_audio(project_id: str):
    d = read_project(project_id)
    return FileResponse(project_dir(project_id) / d["audio_file"])


@app.get("/api/projects/{project_id}/waveform")
def get_waveform(project_id: str):
    """Calculate actual mono audio peak envelopes, cached per uploaded song."""
    d = read_project(project_id)
    p = project_dir(project_id)
    cache = p / "waveform.json"
    if cache.exists():
        # Older cached files may contain NaN after decoding malformed float
        # audio. JSON encoders reject that; regenerate instead of crashing UI.
        try:
            stored = json.loads(cache.read_text(encoding="utf-8"))
            peaks = stored.get("peaks") if isinstance(stored, dict) else None
            if (isinstance(peaks, list) and 0 < len(peaks) <= 1200
                    and all(type(value) in (int, float)
                            and math.isfinite(value) and 0 <= value <= 1
                            for value in peaks)):
                return stored
        except (OSError, ValueError, TypeError):
            pass
    # Waveform display is nonessential work: limit decode threads to one
    # and deprioritize the worker so it cannot saturate CPU during UI startup.
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-threads", "1",
           "-i", str(p / d["audio_file"]),
           "-vn", "-ac", "1", "-ar", "1000", "-f", "f32le", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120,
                              stdin=subprocess.DEVNULL,
                              **perf.windows_child_options(low_priority=True))
        if proc.returncode:
            raise RuntimeError((proc.stderr or b"FFmpeg failed").decode("utf-8", "replace")[-350:])
        raw = array("f")
        raw.frombytes(proc.stdout[:len(proc.stdout)//4*4])
        samples = min(1200, max(150, round(d["duration"] * 3)))
        result = {"peaks": perf.waveform_envelope(raw, samples)}
        # Unique temp file avoids collisions when two waveform requests for
        # the same song complete at the same time. Replace is atomic.
        temp_name = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", dir=p, prefix="waveform-", suffix=".tmp",
                    delete=False, encoding="utf-8") as handle:
                temp_name = Path(handle.name)
                json.dump(result, handle, allow_nan=False)
            temp_name.replace(cache)
        finally:
            if temp_name is not None:
                temp_name.unlink(missing_ok=True)
        return result
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(500, f"Cannot create waveform: {exc}") from exc


@app.post("/api/projects/{project_id}/confirm")
def confirm(project_id: str, body: ConfirmRequest):
    d = read_project(project_id)
    try:
        lines = align_confirmed(body.lyrics, d.get("original_words", []), float(d["duration"]))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    d["lines"] = lines
    d["status"] = "editor"
    save_project(project_dir(project_id), d)
    return {"lines": lines}


@app.put("/api/projects/{project_id}")
def save_edit(project_id: str, body: SaveRequest):
    d = read_project(project_id)
    d["lines"] = validate_lines(body.lines, d["duration"])
    d["settings"] = sanitize_settings(body.settings)
    staging = perf.read_cache(recovery_file(project_id))
    pending = staging.get("pending_background")
    if isinstance(pending, str) and re.fullmatch(r"background-pending-[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|mp4|mov|webm)", pending):
        if (project_dir(project_id) / pending).is_file():
            d["background_file"] = pending
    d["save_state"] = "saved"
    old_background = read_project(project_id).get("background_file")
    save_project(project_dir(project_id), d)
    recovery_file(project_id).unlink(missing_ok=True)
    if old_background and old_background != d.get("background_file"):
        (project_dir(project_id) / old_background).unlink(missing_ok=True)
    return {"saved": True, "save_state": "saved"}


@app.post("/api/projects/{project_id}/background")
async def upload_background(project_id: str, file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in BG_EXT:
        raise HTTPException(400, "Background must be JPG, PNG, WebP, MP4, MOV or WebM")
    dest = background_destination(project_id, ext)
    await save_upload(file, dest)
    try:
        video_stream_width(dest)
        return register_background(project_id, dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Cannot read or save background file")


@app.get("/api/projects/{project_id}/background")
def get_background(project_id: str, pending: bool = False):
    d = read_project(project_id)
    p = project_dir(project_id)
    filename = d.get("background_file")
    if pending:
        changed = perf.read_cache(recovery_file(project_id)).get("pending_background")
        if changed and re.fullmatch(r"background-pending-[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|mp4|mov|webm)", str(changed)):
            filename = changed
    if not filename:
        raise HTTPException(404, "No custom background")
    return FileResponse(p / filename)


def clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        val = float(value)
        return round(max(low, min(high, val)), 3) if math.isfinite(val) else default
    except (ValueError, TypeError):
        return default


def sanitize_settings(d: dict) -> dict:
    if not isinstance(d, dict):
        d = {}
    color = lambda key, fallback: d.get(key, fallback) if re.fullmatch(r"#[0-9a-fA-F]{6}", str(d.get(key, ""))) else fallback
    return {
        "aspect": d.get("aspect") if d.get("aspect") in SIZES else "portrait",
        "resolution": d.get("resolution") if d.get("resolution") in {"540p", "720p", "1080p"} else "720p",
        "renderSpeed": d.get("renderSpeed") if d.get("renderSpeed") in {"fast", "balanced", "quality"} else "balanced",
        "performanceMode": d.get("performanceMode") if d.get("performanceMode") in perf.PROFILES else "balanced",
        "encoder": d.get("encoder") if d.get("encoder") in {"auto", "cpu", "gpu"} else "auto",
        "fps": 24 if str(d.get("fps")) == "24" else 30,
        "mode": d.get("mode") if d.get("mode") in MODES else "line",
        "animation": d.get("animation") if d.get("animation") in ANIMATIONS else "pop",
        "font": d.get("font") if d.get("font") in FONTS else "Arial",
        "fontSize": clamp(d.get("fontSize"), 22, 116, 60),
        "textColor": color("textColor", "#FFFFFF"),
        "accentColor": color("accentColor", "#81FF71"),
        "outline": clamp(d.get("outline"), 0, 8, 2.5),
        "position": clamp(d.get("position"), 15, 85, 55),
        "background": d.get("background") if d.get("background") in (set(PRESETS) | {"custom"}) else "midnight",
        "dim": clamp(d.get("dim"), 0, 0.8, 0.15),
        "upper": bool(d.get("upper", False)),
    }


def validate_lines(lines: list[dict], duration: float) -> list[dict]:
    if len(lines) > 500:
        raise HTTPException(400, "Too many lyric clips (max 500)")
    cleaned = []
    for row in lines:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            continue
        text = row["text"].strip()[:300]
        if not text:
            continue
        start = clamp(row.get("start"), 0, duration, 0)
        end = clamp(row.get("end"), 0, duration, duration)
        if end - start < .05:
            end = min(duration, start + .08)
        words = row.get("words") if isinstance(row.get("words"), list) else []
        good_words = []
        # If text was edited in clip editor, evenly reflow the words across the clip.
        if [w.get("text") for w in words if isinstance(w, dict)] != tokenize(text):
            words = []
        if not words:
            pieces = tokenize(text)
            for i, word in enumerate(pieces):
                left = start + (end - start) * i / len(pieces)
                right = start + (end - start) * (i + 1) / len(pieces)
                good_words.append({"text": word, "start": round(left, 3), "end": round(right, 3)})
        else:
            for w in words[:100]:
                if not isinstance(w, dict):
                    continue
                ws = clamp(w.get("start"), start, end, start)
                we = clamp(w.get("end"), ws, end, end)
                good_words.append({"text": str(w.get("text", ""))[:100], "start": ws, "end": we})
        # Optional per-clip motion and placement. Missing values inherit the
        # original project-wide style so old saved projects render unchanged.
        cleaned_row = {"id": str(row.get("id", uuid.uuid4().hex[:10]))[:20], "text": text,
                       "start": start, "end": end, "words": good_words}
        if row.get("animation") in ANIMATIONS:
            cleaned_row["animation"] = row["animation"]
        if row.get("effectMs") is not None:
            cleaned_row["effectMs"] = int(clamp(row.get("effectMs"), 120, 650, 230))
        for coordinate in ("x", "y"):
            if row.get(coordinate) is not None:
                cleaned_row[coordinate] = clamp(row[coordinate], 8, 92, 50 if coordinate == "x" else 55)
        cleaned.append(cleaned_row)
    cleaned.sort(key=lambda ln: ln["start"])
    if not cleaned:
        raise HTTPException(400, "No lyrics to export")
    return cleaned


def asstime(seconds: float) -> str:
    cs = round(max(0, seconds) * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def ass_color(hexcolor: str) -> str:
    c = hexcolor.lstrip("#")
    return f"&H00{c[4:6]}{c[2:4]}{c[0:2]}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_event(start: float, end: float, tags: str, text: str) -> str:
    if end <= start + .01:
        return ""
    return f"Dialogue: 0,{asstime(start)},{asstime(end)},Main,,0,0,0,,{{{tags}}}{ass_escape(text)}\n"


def animation_tags(name: str, W: int, H: int, y: int,
                   x: int | None = None, enter_ms: int = 230) -> str:
    r"""Valid ASS animation overrides; slide supplies \move instead of \pos."""
    center = W // 2 if x is None else x
    ms = max(120, min(650, int(enter_ms)))
    fade = min(180, round(ms * .45))
    if name == "fade":
        return rf"\fad({fade},{fade})"
    if name == "pop":
        return rf"\fscx80\fscy80\t(0,{ms},\fscx100\fscy100)\fad({min(90,fade)},120)"
    if name == "slide":
        offset = max(24, round(H * .052))
        return rf"\move({center},{y + offset},{center},{y},0,{ms})\fad({min(100,fade)},150)"
    if name == "zoom":
        return rf"\fscx125\fscy125\t(0,{ms},\fscx100\fscy100)\fad({min(90,fade)},130)"
    if name == "bounce":
        first = round(ms * .42)
        return rf"\fscx65\fscy65\t(0,{first},\fscx115\fscy115)\t({first},{ms},\fscx100\fscy100)\fad(40,100)"
    if name == "blur":
        return rf"\blur6\t(0,{ms},\blur0.5)\fad({min(170,fade)},140)"
    if name == "pulse":
        return r"\fad(30,100)"
    return ""


def prepare_render_lines(lines: list[dict]) -> list[dict]:
    """Prevent overlapping ASS captions and momentary ASR flash cues.

    This affects exported subtitles only: saved lyric edits remain untouched.
    """
    ordered = sorted((dict(item) for item in lines if item.get("text", "").strip()),
                     key=lambda item: float(item["start"]))
    result = []
    for idx, item in enumerate(ordered):
        start = max(0., float(item["start"]))
        end = float(item["end"])
        if idx + 1 < len(ordered):
            end = min(end, float(ordered[idx + 1]["start"]))
        if end - start < 0.10:
            continue
        item["start"], item["end"] = start, end
        kept_words = []
        for word in item.get("words", []):
            ws = max(start, float(word["start"]))
            we = min(end, float(word["end"]))
            if we > ws + 0.01:
                kept_words.append({**word, "start": ws, "end": we})
        item["words"] = kept_words
        result.append(item)
    return result


def create_ass(lines: list[dict], settings: dict, W: int, H: int, target: Path) -> None:
    s = settings
    font = s["font"]
    size = round(s["fontSize"] * W / 720)
    y = round(H * s["position"] / 100)
    main = ass_color(s["textColor"])
    accent = ass_color(s["accentColor"])
    outline = round(s["outline"] * W / 720, 1)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},{size},{main},{accent},&H00101511,&H66000000,-1,0,0,0,100,100,0,0,1,{outline},1,5,25,25,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    output = [header]
    for line in prepare_render_lines(lines):
        start, end = line["start"], line["end"]
        text = line["text"].upper() if s["upper"] else line["text"]
        mode = s["mode"]
        motion = line.get("animation") if line.get("animation") in ANIMATIONS else s["animation"]
        ms = int(clamp(line.get("effectMs"), 120, 650, 230))
        cx = round(W * clamp(line.get("x"), 8, 92, 50) / 100)
        cy = round(H * clamp(line.get("y"), 8, 92, s["position"]) / 100)
        # Do not combine \pos and \move, which conflicts on some ASS renderers.
        base = rf"\an5" + ("" if motion == "slide" else rf"\pos({cx},{cy})")
        effect = animation_tags(motion, W, H, cy, cx, ms)
        if motion == "pulse" and mode != "word":
            # Timed to word starts, including hand-adjusted timings. ASS uses
            # subtitle-relative transitions rather than extra video frames.
            for word in line.get("words", [])[:80]:
                tick = round((word["start"] - start) * 1000)
                if 0 <= tick < (end - start) * 1000:
                    rise = min(tick + 65, round((end - start) * 1000))
                    fall = min(tick + 185, round((end - start) * 1000))
                    effect += (rf"\t({tick},{rise},\fscx108\fscy108)"
                               rf"\t({rise},{fall},\fscx100\fscy100)")
        tags = base + effect
        if mode == "word" and line["words"]:
            for word in line["words"]:
                wtext = word["text"].upper() if s["upper"] else word["text"]
                output.append(ass_event(word["start"], word["end"], tags, wtext))
        elif mode == "karaoke" and line["words"]:
            # ASS \k durations are sequential. Silence must be its own
            # (space-only) syllable: adding it to the next word makes the
            # exported highlight start early, unlike the canvas preview.
            spans = []
            cursor = start
            for word in line["words"]:
                word_start = max(cursor, float(word["start"]))
                word_end = float(word["end"])
                if word_end <= word_start + .01:
                    continue  # An overlapping word cannot go back in ASS time.
                gap_cs = max(0, round((word_start - cursor) * 100))
                duration_cs = max(1, round((word_end - word_start) * 100))
                if gap_cs:
                    spans.append(r"{\k" + str(gap_cs) + "} ")
                elif spans:
                    spans.append(" ")
                spans.append(r"{\k" + str(duration_cs) + "}" +
                             ass_escape(word["text"].upper() if s["upper"] else word["text"]))
                cursor = word_end
            output.append(f"Dialogue: 0,{asstime(start)},{asstime(end)},Main,,0,0,0,,"
                          f"{{{base}\\1c{accent}\\2c{main}{effect}}}" + "".join(spans) + "\n")
        elif motion == "typewriter" and mode == "line":
            pieces = tokenize(text)
            if pieces:
                for i in range(len(pieces)):
                    t = start + (end - start) * i / len(pieces)
                    u = start + (end - start) * (i + 1) / len(pieces)
                    output.append(ass_event(t, u, base, " ".join(pieces[:i+1])))
        else:
            output.append(ass_event(start, end, tags, text))
    target.write_text("".join(output), encoding="utf-8-sig")


def rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i+2], 16) for i in (1, 3, 5))


def create_gradient(name: str, target: Path) -> None:
    from PIL import Image  # Only import imaging code when an export needs a new background.
    top, bottom, glow = [rgb(h) for h in PRESETS[name]]
    # Render a smooth, low-frequency gradient at half resolution then upscale.
    # This cuts per-pixel Python math ~4x without changing final MP4 dimensions.
    w, h = 360, 640
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        for x in range(w):
            radial = max(0.0, 1 - math.sqrt(((x-w*.48)/(w*.75))**2 + ((y-h*.32)/(h*.58))**2))
            a = min(1, radial * .42)
            px[x,y] = tuple(int((top[k]*(1-t) + bottom[k]*t)*(1-a) + glow[k]*a) for k in range(3))
    img.resize((720, 1280), Image.Resampling.LANCZOS).save(target)


def ffmpeg_seconds(value: str) -> float:
    """Parse FFmpeg's HH:MM:SS output clock; no frame-rate assumptions."""
    try:
        h, m, sec = value.split(":")
        return max(0.0, int(h) * 3600 + int(m) * 60 + float(sec))
    except (ValueError, AttributeError):
        return 0.0


def render_with_progress(args: list[str], folder: Path, job_id: str, duration: float) -> None:
    """Read incremental FFmpeg progress, keeping stderr diagnostics and no CMD popups."""
    with job_lock:
        mode = jobs.get(job_id, {}).get("performance_mode", "balanced")
    child_options = perf.windows_child_options(
        perf.profile_config(mode)["low_priority"])
    process = subprocess.Popen(args, cwd=folder, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1,
                               stdin=subprocess.DEVNULL, **child_options)
    started = time.monotonic()
    frames = 0
    watchdog = threading.Timer(1800, process.kill)
    watchdog.daemon = True
    watchdog.start()
    progress_seconds = 0.0
    error_tail = []
    try:
        assert process.stdout is not None
        for line in process.stdout:
            row = line.strip()
            if row.startswith("out_time="):
                progress_seconds = ffmpeg_seconds(row.partition("=")[2])
            elif row.startswith("frame="):
                try:
                    frames = max(0, int(row.partition("=")[2]))
                except ValueError:
                    pass
            elif row.startswith("progress="):
                percent = max(0, min(99, int(progress_seconds / max(.1, duration) * 100)))
                elapsed = max(.001, time.monotonic() - started)
                with job_lock:
                    if job_id in jobs:
                        jobs[job_id].update(stage="encoding", progress=percent,
                                            encode_fps=round(frames / elapsed, 1),
                                            speed_ratio=round(progress_seconds / elapsed, 2))
                        # Autonomous jobs run several renders; mirror each child's
                        # progress into its parent's overall progress bar.
                        weight = jobs[job_id].get("weight")
                        parent = jobs.get(jobs[job_id].get("parent") or "")
                        if parent is not None and isinstance(weight, list) and len(weight) == 2:
                            parent["progress"] = int(weight[0] + weight[1] * percent / 100)
            elif row:
                error_tail.append(row)
                if len(error_tail) > 25:
                    error_tail.pop(0)
        code = process.wait()
        if code:
            raise RuntimeError("FFmpeg exited with code " + str(code) +
                               ": " + " | ".join(error_tail)[-1400:])
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
        if process.stdout:
            process.stdout.close()


def render_project(project_id: str, job_id: str, settings: dict,
                   lines: list[dict], preview: bool = False) -> None:
    p = project_dir(project_id)
    started = time.monotonic()
    output = p / ("lyric_preview.mp4" if preview else "lyric_video.mp4")
    try:
        d = read_project(project_id)
        w, h = SIZES[settings["aspect"]]
        if settings["resolution"] == "1080p":
            w, h = round(w * 1.5), round(h * 1.5)
        elif settings["resolution"] == "540p":
            w, h = round(w * .75), round(h * .75)
        fps = settings.get("fps", 30)
        length = min(15.0, float(d["duration"])) if preview else float(d["duration"])
        audio = p / d["audio_file"]
        user_bg = None
        use_bg_video = False
        if settings["background"] == "custom":
            pending = perf.read_cache(recovery_file(project_id)).get("pending_background")
            if pending and re.fullmatch(r"background-pending-[0-9a-f]{32}\.(?:jpg|jpeg|png|webp|mp4|mov|webm)", str(pending)) and (p / pending).is_file():
                user_bg = p / pending
            elif d.get("background_file"):
                user_bg = p / d["background_file"]
            if user_bg:
                use_bg_video = user_bg.suffix.lower() in {".mp4", ".mov", ".webm"}
        cache_path = p / "render_cache.json"
        cache_slot = "preview" if preview else "full"
        fingerprint = perf.render_fingerprint(lines, settings, audio, user_bg, preview)
        cached = perf.read_cache(cache_path)
        if (cached.get(cache_slot) == fingerprint and output.is_file()
                and output.stat().st_size > 1024):
            with job_lock:
                jobs[job_id].update(status="done", stage="cached", progress=100, cached=True,
                                    elapsed_seconds=round(time.monotonic() - started, 2),
                                    download=f"/api/projects/{project_id}/" +
                                    ("preview-video" if preview else "export"))
            return

        if user_bg is None:
            bg_file = p / "generated_bg.png"
            palette_file = p / "generated_bg.palette"
            style = settings["background"] if settings["background"] in PRESETS else "midnight"
            if not bg_file.is_file() or not palette_file.is_file() or palette_file.read_text() != style:
                create_gradient(style, bg_file)
                palette_file.write_text(style)
        else:
            bg_file = user_bg

        # Preview renders the FIRST 15 seconds, using the same absolute ASS timings.
        # No trim offsets or side effects to the saved video/corrected lyrics.
        ass_file = p / ("preview_captions.ass" if preview else "captions.ass")
        create_ass(lines, settings, w, h, ass_file)
        filters = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h},setsar=1,format=yuv420p,"
                   f"eq=brightness={-settings['dim'] * .45:.3f},ass={ass_file.name}[v]")
        background_input = (["-stream_loop", "-1", "-i", str(bg_file)] if use_bg_video
                            else ["-loop", "1", "-framerate", str(fps), "-i", str(bg_file)])
        profile = perf.profile_config(settings.get("performanceMode", "balanced"))
        preference = settings.get("encoder", "auto")
        with job_lock:
            jobs[job_id].update(stage="checking_encoder", progress=0)
        available = perf.available_gpu_encoders() if preference != "cpu" else ()
        encoder = perf.choose_encoder(preference, available)

        def arguments(codec: str, target: Path) -> list[str]:
            return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin",
                    "-stats_period", "0.5", "-progress", "pipe:1",
                    "-filter_complex_threads", str(profile["threads"]),
                    "-y", *background_input, "-i", str(audio),
                    "-filter_complex", filters, "-map", "[v]", "-map", "1:a:0",
                    "-t", f"{length:.3f}", "-r", str(fps),
                    *perf.encode_args(codec, settings["renderSpeed"], w, h, profile["threads"]),
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(target)]

        temporary = p / ("render-" + job_id + ".mp4")
        try:
            with job_lock:
                jobs[job_id].update(stage="encoding", encoder_used=encoder,
                                    gpu_available=list(available))
            try:
                render_with_progress(arguments(encoder, temporary), p, job_id, length)
            except Exception:
                # Hardware can disappear or fail partway through an export. Use
                # CPU instead of losing the user's video.
                if encoder == "libx264":
                    raise
                temporary.unlink(missing_ok=True)
                with job_lock:
                    jobs[job_id].update(stage="cpu_fallback", progress=0, encoder_used="libx264",
                                        hardware_fallback=True)
                render_with_progress(arguments("libx264", temporary), p, job_id, length)
            if not temporary.is_file() or temporary.stat().st_size < 1024:
                raise RuntimeError("Encoder completed without a usable video")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)

        # Rendering cache is advisory. Losing this manifest never loses an MP4.
        cached[cache_slot] = fingerprint
        try:
            perf.store_cache(cache_path, cached)
        except OSError:
            pass
        elapsed = max(.001, time.monotonic() - started)
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100,
                                cached=False, elapsed_seconds=round(elapsed, 2),
                                speed_ratio=round(length / elapsed, 2),
                                download=f"/api/projects/{project_id}/" +
                                ("preview-video" if preview else "export"))
    except Exception as exc:
        with job_lock:
            jobs[job_id].update(status="error", stage="error", error=str(exc)[:1800],
                                elapsed_seconds=round(time.monotonic() - started, 2))


def queue_render(project_id: str, body: RenderRequest, preview: bool = False) -> dict:
    d = read_project(project_id)
    settings = sanitize_settings(body.settings)
    lines = validate_lines(body.lines, d["duration"])
    with job_lock:
        # Avoid accumulating completed render results forever in a long session.
        if len(jobs) > 250:
            finished = sorted(
                (key for key, item in jobs.items()
                 if item.get("status") in {"done", "error"}),
                key=lambda key: jobs[key].get("created", 0))
            for stale in finished[:max(0, len(jobs) - 180)]:
                jobs.pop(stale, None)
        # Two simultaneous renders of the same project would share ASS/assets.
        if any(item.get("project_id") == project_id and item.get("status") == "rendering"
               for item in jobs.values()):
            raise HTTPException(409, "This project's export is still running")
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"id": job_id, "project_id": project_id, "preview": preview,
                        "status": "rendering", "stage": "preparing", "progress": 0,
                        "created": time.time(), "encoder_used": None,
                        "performance_mode": settings["performanceMode"]}
    # Exporting must never silently Save changes to an editable project.
    executor.submit(render_project, project_id, job_id, settings, lines, preview)
    return {"job_id": job_id, "preview": preview}


@app.post("/api/projects/{project_id}/render")
def render(project_id: str, body: RenderRequest):
    return queue_render(project_id, body, preview=False)


@app.post("/api/projects/{project_id}/preview")
def render_preview(project_id: str, body: RenderRequest):
    return queue_render(project_id, body, preview=True)


@app.get("/api/projects/{project_id}/preview-video")
def get_preview_video(project_id: str):
    path = project_dir(project_id) / "lyric_preview.mp4"
    if not path.is_file():
        raise HTTPException(404, "No preview video yet")
    return FileResponse(path, filename="SkellyMotion-preview.mp4", media_type="video/mp4")


@app.get("/api/performance")
def performance_info(check_gpu: bool = False):
    """Process metrics and confirmed GPU encoders; no device claims from list-only checks."""
    stats = perf.resource_snapshot()
    with job_lock:
        active = [dict(job) for job in jobs.values() if job.get("status") == "rendering"]
        past = [dict(job) for job in jobs.values() if job.get("status") == "done"]
    last = max(past, key=lambda j: j.get("created", 0)) if past else None
    return {"resources": stats, "gpu_encoders": list(perf.available_gpu_encoders())
            if check_gpu else None,
            "active": active[-3:], "last_render": last,
            "same_model": True, "hardware_tests_ran": bool(check_gpu)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with job_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown render job")
    return job



def derived_files(keep_project_id: str | None = None) -> list[Path]:
    """Only generated files, never uploads, saved edits, or AI models."""
    if not DATA.exists():
        return []
    results = []
    for directory in DATA.iterdir():
        if not directory.is_dir() or directory.is_symlink() or not re.fullmatch(r"[0-9a-f]{32}", directory.name):
            continue
        if directory.name == keep_project_id or not (directory / "project.json").is_file():
            continue
        for filename in ("lyric_video.mp4", "lyric_preview.mp4",
                         "captions.ass", "preview_captions.ass",
                         "generated_bg.png", "generated_bg.palette", "render_cache.json"):
            candidate = directory / filename
            if candidate.is_file() and not candidate.is_symlink():
                results.append(candidate)
    return results


def storage_overview(keep_project_id: str | None = None) -> dict:
    """Cheap workspace accounting; never recursively scan downloaded AI models."""
    project_count = 0
    workspace_bytes = 0
    exports_bytes = 0
    if DATA.exists():
        for directory in DATA.iterdir():
            if not directory.is_dir() or directory.is_symlink() or not (directory / "project.json").is_file():
                continue
            project_count += 1
            for path in directory.iterdir():
                if path.is_file() and not path.is_symlink():
                    size = path.stat().st_size
                    workspace_bytes += size
                    if path.name in {"lyric_video.mp4", "lyric_preview.mp4"}:
                        exports_bytes += size
    candidates = derived_files(keep_project_id)
    return {"projects": project_count, "workspace_bytes": workspace_bytes,
            "exports_bytes": exports_bytes, "cleanup_files": len(candidates),
            "cleanup_bytes": sum(path.stat().st_size for path in candidates),
            "model_cache_unchanged": True}


class CleanupRequest(BaseModel):
    keep_project_id: str | None = None
    confirm: bool = False


@app.get("/api/storage")
def storage_info(keep_project_id: str | None = None):
    if keep_project_id is not None and not re.fullmatch(r"[0-9a-f]{32}", keep_project_id):
        raise HTTPException(400, "Invalid project ID")
    return storage_overview(keep_project_id)


@app.post("/api/storage/cleanup")
def cleanup_old_renders(body: CleanupRequest):
    """Explicit, opt-in cleanup. Retain the open project's export and source files."""
    if not body.confirm:
        raise HTTPException(400, "Explicit confirmation is required")
    if body.keep_project_id is not None and not re.fullmatch(r"[0-9a-f]{32}", body.keep_project_id):
        raise HTTPException(400, "Invalid project ID")
    with job_lock:
        if any(job["status"] == "rendering" for job in jobs.values()):
            raise HTTPException(409, "Wait until active video renders finish")
        candidates = derived_files(body.keep_project_id)
        freed = 0
        removed = 0
        for path in candidates:
            try:
                size = path.stat().st_size
                path.unlink()
                freed += size
                removed += 1
            except OSError:
                continue
    return {"removed_files": removed, "freed_bytes": freed,
            "model_cache_unchanged": True, "source_audio_untouched": True}


@app.get("/api/projects/{project_id}/export")
def download_export(project_id: str):
    f = project_dir(project_id) / "lyric_video.mp4"
    if not f.exists():
        raise HTTPException(404, "No exported video")
    return FileResponse(f, media_type="video/mp4", filename="SkellyMotion-video.mp4")



# ---------------------------------------------------------------------------
# Autonomous mode: auto-Shorts from a song, autopilot, and the long-video
# auto-clipper. The scoring/reframing logic lives in studio_clips.py; this
# section is the job, file and HTTP glue around the existing render pipeline.
# ---------------------------------------------------------------------------
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
AUTOPILOT_PRESETS = {
    "classic": {"mode": "line", "animation": "fade"},
    "bold": {"mode": "word", "animation": "pop", "upper": True, "fontSize": 84},
    "karaoke": {"mode": "karaoke", "animation": "none"},
    "project": {},  # keep whatever style the project already has
}


def env_number(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) and value > 0 else default
    except (TypeError, ValueError):
        return default


def max_clip_source_bytes() -> int:
    return int(env_number("SKELLYMOTION_MAX_CLIP_SOURCE_MB", 2048) * 1024 * 1024)


def max_clip_source_seconds() -> float:
    return env_number("SKELLYMOTION_MAX_CLIP_SOURCE_MINUTES", 180) * 60


def short_settings(base: dict) -> dict:
    """Vertical 9:16 caption style for Shorts and clips (word-by-word pop)."""
    merged = {**(base if isinstance(base, dict) else {}), "aspect": "portrait", "mode": "word",
              "animation": "pop", "fontSize": 84, "position": 62, "upper": True}
    return sanitize_settings(merged)


def output_size(settings: dict) -> tuple[int, int]:
    w, h = SIZES[settings["aspect"]]
    if settings["resolution"] == "1080p":
        return round(w * 1.5), round(h * 1.5)
    if settings["resolution"] == "540p":
        return round(w * .75), round(h * .75)
    return w, h


def new_child_job(parent_id: str, project_id: str, settings: dict, base: int, span: int) -> str:
    child = uuid.uuid4().hex
    with job_lock:
        jobs[child] = {"id": child, "project_id": project_id, "preview": False, "status": "rendering",
                       "stage": "preparing", "progress": 0, "created": time.time(),
                       "encoder_used": None, "performance_mode": settings["performanceMode"],
                       "parent": parent_id, "weight": [base, span]}
    return child


def finish_child(child: str) -> None:
    with job_lock:
        job = jobs.get(child, {})
        if job.get("status") == "error":
            raise RuntimeError(job.get("error") or "A render failed")
        job.update(status="done", progress=100)


def encode_with_fallback(job_id: str, settings: dict, length: float, folder: Path,
                         build_args, temporary: Path) -> None:
    """Pick an encoder like render_project does, retrying on CPU if hardware fails."""
    preference = settings.get("encoder", "auto")
    available = perf.available_gpu_encoders() if preference != "cpu" else ()
    encoder = perf.choose_encoder(preference, available)
    with job_lock:
        jobs[job_id].update(stage="encoding", encoder_used=encoder, gpu_available=list(available))
    try:
        try:
            render_with_progress(build_args(encoder, temporary), folder, job_id, length)
        except Exception:
            if encoder == "libx264":
                raise
            temporary.unlink(missing_ok=True)
            with job_lock:
                jobs[job_id].update(stage="cpu_fallback", progress=0, encoder_used="libx264",
                                    hardware_fallback=True)
            render_with_progress(build_args("libx264", temporary), folder, job_id, length)
        if not temporary.is_file() or temporary.stat().st_size < 1024:
            raise RuntimeError("Encoder completed without a usable video")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def resolve_background(project_id: str, data: dict, settings: dict) -> tuple[Path, bool, Path | None]:
    """(background file, is a video, user background or None) for Shorts."""
    p = project_dir(project_id)
    user_bg = None
    if settings["background"] == "custom" and data.get("background_file"):
        candidate = p / data["background_file"]
        if candidate.is_file():
            user_bg = candidate
    if user_bg is not None:
        return user_bg, user_bg.suffix.lower() in {".mp4", ".mov", ".webm"}, user_bg
    bg_file, palette_file = p / "generated_bg.png", p / "generated_bg.palette"
    style = settings["background"] if settings["background"] in PRESETS else "midnight"
    if not bg_file.is_file() or not palette_file.is_file() or palette_file.read_text() != style:
        create_gradient(style, bg_file)
        palette_file.write_text(style)
    return bg_file, False, None


def cached_output(folder: Path, slot: str, fingerprint: str, output: Path) -> bool:
    cached = perf.read_cache(folder / "render_cache.json")
    return cached.get(slot) == fingerprint and output.is_file() and output.stat().st_size > 1024


def remember_output(folder: Path, slot: str, fingerprint: str) -> None:
    cache_path = folder / "render_cache.json"
    cached = perf.read_cache(cache_path)
    cached[slot] = fingerprint
    try:
        perf.store_cache(cache_path, cached)
    except OSError:
        pass


def render_short(project_id: str, job_id: str, n: int, segment: dict, settings: dict,
                 lines: list[dict]) -> Path:
    """Render one vertical Short of a song: same captions, trimmed audio, hook card."""
    p = project_dir(project_id)
    data = read_project(project_id)
    duration = float(data["duration"])
    start = clamp(segment.get("start"), 0, duration, 0)
    end = clamp(segment.get("end"), 0, duration, duration)
    length = end - start
    if not 3 <= length <= 90:
        raise ValueError("A Short must be between 3 and 90 seconds long")
    hook = re.sub(r"\s+", " ", str(segment.get("hook") or ""))[:80]
    w, h = output_size(settings)
    shifted = clips.shift_lines(lines, start, end)
    if not shifted:
        raise RuntimeError("No lyrics fall inside this Short")
    audio = p / data["audio_file"]
    bg_file, use_bg_video, user_bg = resolve_background(project_id, data, settings)
    output = p / f"short_{n}.mp4"
    fingerprint = perf.render_fingerprint(
        shifted + [{"hook": hook, "start": start, "end": end}], settings, audio, user_bg, False)
    if cached_output(p, f"short_{n}", fingerprint, output):
        with job_lock:
            jobs[job_id].update(stage="cached", cached=True)
        return output
    ass_file = p / f"short_{n}.ass"
    create_ass(shifted, settings, w, h, ass_file)
    clips.add_hook_to_ass(ass_file, hook, w, h, 1.5, settings["font"])
    filters = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
               f"format=yuv420p,eq=brightness={-settings['dim'] * .45:.3f},ass={ass_file.name}[v]")
    background_input = (["-stream_loop", "-1", "-i", str(bg_file)] if use_bg_video
                        else ["-loop", "1", "-framerate", str(settings["fps"]), "-i", str(bg_file)])
    profile = perf.profile_config(settings["performanceMode"])

    def build(codec: str, target: Path) -> list[str]:
        return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin",
                "-stats_period", "0.5", "-progress", "pipe:1",
                "-filter_complex_threads", str(profile["threads"]), "-y", *background_input,
                "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(audio),
                "-filter_complex", filters, "-map", "[v]", "-map", "1:a:0",
                "-t", f"{length:.3f}", "-r", str(settings["fps"]),
                *perf.encode_args(codec, settings["renderSpeed"], w, h, profile["threads"]),
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target)]

    temporary = p / f"render-{job_id}.mp4"
    encode_with_fallback(job_id, settings, length, p, build, temporary)
    temporary.replace(output)
    remember_output(p, f"short_{n}", fingerprint)
    return output


def song_lines_for(data: dict) -> list[dict]:
    """Saved lyric lines, or lines built straight from the transcript (no review)."""
    lines = data.get("lines") or []
    if lines:
        return lines
    words = data.get("original_words") or []
    return build_lines(words) if words else []


def short_manifest_entry(data: dict, n: int, segment: dict, text: str) -> dict:
    meta = clips.heuristic_metadata(text, segment.get("hook") or data.get("title") or "")
    title = f"{data.get('title', 'Song')} | {meta['title']}"[:100]
    tags = list(dict.fromkeys(meta["tags"] + ["shorts", "lyrics", "lyricvideo"]))
    return {"n": n, "file": f"short_{n}.mp4", "start": round(float(segment["start"]), 2),
            "end": round(float(segment["end"]), 2), "hook": segment.get("hook", ""),
            "title": title, "description": f"{meta['description']}\n\n#shorts #lyrics",
            "tags": tags, "score": segment.get("score"), "reasons": segment.get("reasons", [])}


def render_shorts_batch(project_id: str, job_id: str, segments: list[dict], settings: dict,
                        lines: list[dict], base: int = 0, span: int = 100) -> list[dict]:
    data = read_project(project_id)
    p = project_dir(project_id)
    manifest = []
    for old in p.glob("short_*.mp4"):
        match = re.fullmatch(r"short_(\d+)\.mp4", old.name)
        if match and int(match.group(1)) > len(segments):
            old.unlink(missing_ok=True)
    for index, segment in enumerate(segments, start=1):
        with job_lock:
            jobs[job_id].update(stage=f"short_{index}_of_{len(segments)}")
        child = new_child_job(job_id, project_id, settings,
                              base + span * (index - 1) // len(segments), span // len(segments))
        render_short(project_id, child, index, segment, settings, lines)
        finish_child(child)
        text = " ".join(ln["text"] for ln in clips.shift_lines(lines, segment["start"], segment["end"]))
        manifest.append(short_manifest_entry(data, index, segment, text))
    (p / "shorts.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


class AutopilotRequest(BaseModel):
    preset: str = "classic"
    shorts: int = Field(default=3, ge=0, le=6)
    aspect: str = "landscape"
    hooks: bool = True
    lines: list[dict] | None = None  # the editor's current lines, when it has any


class ShortSuggestRequest(BaseModel):
    lines: list[dict] | None = None
    count: int = Field(default=3, ge=1, le=8)


class ShortsRenderRequest(BaseModel):
    segments: list[dict]
    settings: dict = Field(default_factory=dict)
    lines: list[dict] | None = None


def reject_if_busy(project_id: str) -> None:
    if any(item.get("project_id") == project_id and item.get("status") == "rendering"
           for item in jobs.values()):
        raise HTTPException(409, "This project already has a job running")


def register_job(project_id: str, kind: str, settings: dict) -> str:
    with job_lock:
        reject_if_busy(project_id)
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"id": job_id, "project_id": project_id, "kind": kind, "preview": False,
                        "status": "rendering", "stage": "preparing", "progress": 0,
                        "created": time.time(), "encoder_used": None,
                        "performance_mode": settings["performanceMode"]}
    return job_id


def fail_job(job_id: str, exc: Exception, started: float) -> None:
    with job_lock:
        jobs[job_id].update(status="error", stage="error", error=str(exc)[:1800],
                            elapsed_seconds=round(time.monotonic() - started, 2))


def song_envelope(project_id: str) -> list[float]:
    p = project_dir(project_id)
    data = read_project(project_id)
    try:
        return clips.audio_envelope(p / data["audio_file"], 600)
    except Exception:
        return []  # Loudness is only one signal; picking still works without it.


@app.post("/api/projects/{project_id}/shorts/suggestions")
def suggest_shorts(project_id: str, body: ShortSuggestRequest):
    data = read_project(project_id)
    if data.get("kind") == "clip_source":
        raise HTTPException(400, "Use the clip suggestions for video projects")
    lines = validate_lines(body.lines, data["duration"]) if body.lines else song_lines_for(data)
    if not lines:
        raise HTTPException(400, "No lyrics yet. Finish transcription first.")
    picks = clips.pick_short_segments(lines, song_envelope(project_id), float(data["duration"]), body.count)
    return {"suggestions": sorted(picks, key=lambda s: -s["score"])}


@app.post("/api/projects/{project_id}/shorts/render")
def render_shorts(project_id: str, body: ShortsRenderRequest):
    data = read_project(project_id)
    if data.get("kind") == "clip_source":
        raise HTTPException(400, "Use the clip renderer for video projects")
    if not 1 <= len(body.segments) <= 8:
        raise HTTPException(400, "Choose between 1 and 8 Shorts")
    lines = validate_lines(body.lines, data["duration"]) if body.lines else song_lines_for(data)
    if not lines:
        raise HTTPException(400, "No lyrics to render")
    settings = short_settings({**(data.get("settings") or {}), **(body.settings or {})})
    segments = []
    for row in body.segments:
        if not isinstance(row, dict):
            continue
        start = clamp(row.get("start"), 0, data["duration"], 0)
        end = clamp(row.get("end"), 0, data["duration"], data["duration"])
        if 3 <= end - start <= 90:
            segments.append({"start": start, "end": end, "hook": str(row.get("hook") or "")[:80],
                             "score": row.get("score"), "reasons": row.get("reasons") or []})
    if not segments:
        raise HTTPException(400, "Each Short must be between 3 and 90 seconds")
    job_id = register_job(project_id, "shorts", settings)

    def work():
        started = time.monotonic()
        try:
            manifest = render_shorts_batch(project_id, job_id, segments, settings, lines)
            with job_lock:
                jobs[job_id].update(status="done", stage="complete", progress=100,
                                    elapsed_seconds=round(time.monotonic() - started, 2),
                                    outputs={"shorts": [{**m, "url": f"/api/projects/{project_id}/shorts/{m['n']}"}
                                                        for m in manifest]})
        except Exception as exc:
            fail_job(job_id, exc, started)

    executor.submit(work)
    return {"job_id": job_id}


@app.post("/api/projects/{project_id}/autopilot")
def start_autopilot(project_id: str, body: AutopilotRequest):
    data = read_project(project_id)
    if data.get("kind") == "clip_source":
        raise HTTPException(400, "Autopilot is for songs. Video projects use the clipper.")
    if data.get("status") == "transcribing":
        raise HTTPException(409, "Transcription is still running. Try again when it finishes.")
    if not data.get("lines") and not data.get("original_words"):
        raise HTTPException(400, "No lyrics were detected. Add lyrics in the editor first.")
    preset = body.preset if body.preset in AUTOPILOT_PRESETS else "classic"
    aspect = body.aspect if body.aspect in SIZES else "landscape"
    style = {**(data.get("settings") or {}), **AUTOPILOT_PRESETS[preset], "aspect": aspect}
    settings = sanitize_settings(style)
    supplied = validate_lines(body.lines, data["duration"]) if body.lines else None
    job_id = register_job(project_id, "autopilot", settings)
    executor.submit(run_autopilot, project_id, job_id, settings, body.shorts, body.hooks, supplied)
    return {"job_id": job_id}


def run_autopilot(project_id: str, job_id: str, settings: dict, short_count: int, hooks: bool,
                  supplied_lines: list[dict] | None = None) -> None:
    started = time.monotonic()
    try:
        p = project_dir(project_id)
        with job_lock:
            jobs[job_id].update(stage="autopilot_prepare", progress=2)
        data = read_project(project_id)
        auto_confirmed = not supplied_lines and not data.get("lines")
        lines = supplied_lines or validate_lines(song_lines_for(data), data["duration"])
        fresh = read_project(project_id)
        fresh["lines"] = lines
        fresh["status"] = "editor"
        fresh["save_state"] = "saved"  # deliberate action with deliverables: never auto-discard
        if auto_confirmed:
            fresh["auto_confirmed"] = True
        if not fresh.get("settings"):
            fresh["settings"] = settings
        save_project(p, fresh)

        with job_lock:
            jobs[job_id].update(stage="autopilot_full_render")
        child = new_child_job(job_id, project_id, settings, 5, 50 if short_count else 90)
        render_project(project_id, child, settings, lines)
        finish_child(child)
        outputs: dict[str, Any] = {"full": f"/api/projects/{project_id}/export",
                                   "auto_confirmed": auto_confirmed,
                                   "uncertain_words": len(fresh.get("review_uncertain") or [])}

        if short_count:
            with job_lock:
                jobs[job_id].update(stage="autopilot_shorts", progress=56)
            picks = clips.pick_short_segments(lines, song_envelope(project_id),
                                              float(data["duration"]), short_count)
            if not hooks:
                for pick in picks:
                    pick["hook"] = ""
            vertical = short_settings(settings)
            manifest = render_shorts_batch(project_id, job_id, picks, vertical, lines, 56, 42)
            outputs["shorts"] = [{**m, "url": f"/api/projects/{project_id}/shorts/{m['n']}"} for m in manifest]
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100, outputs=outputs,
                                elapsed_seconds=round(time.monotonic() - started, 2))
    except Exception as exc:
        fail_job(job_id, exc, started)


def safe_media_response(project_id: str, filename: str, download: str):
    f = project_dir(project_id) / filename
    if not f.is_file():
        raise HTTPException(404, "That file has not been rendered yet")
    return FileResponse(f, media_type="video/mp4", filename=download)


@app.get("/api/projects/{project_id}/shorts/{n}")
def download_short(project_id: str, n: int):
    if not 1 <= n <= 8:
        raise HTTPException(404, "Unknown Short")
    return safe_media_response(project_id, f"short_{n}.mp4", f"SkellyMotion-short-{n}.mp4")


@app.get("/api/projects/{project_id}/source")
def get_clip_source_video(project_id: str):
    data = read_project(project_id)
    if data.get("kind") != "clip_source":
        raise HTTPException(404, "This project has no source video")
    source = project_dir(project_id) / data["source_file"]
    if not source.is_file():
        raise HTTPException(404, "Source video is missing")
    return FileResponse(source)


@app.get("/api/projects/{project_id}/clips/{n}/{lang}")
def download_translated_clip(project_id: str, n: int, lang: str):
    if not 1 <= n <= 12 or lang not in edit.LANGUAGES:
        raise HTTPException(404, "Unknown clip")
    return safe_media_response(project_id, f"clip_{n}.{lang}.mp4", f"SkellyMotion-clip-{n}-{lang}.mp4")


@app.get("/api/projects/{project_id}/clips/{n}")
def download_clip(project_id: str, n: int):
    if not 1 <= n <= 12:
        raise HTTPException(404, "Unknown clip")
    return safe_media_response(project_id, f"clip_{n}.mp4", f"SkellyMotion-clip-{n}.mp4")


@app.get("/api/projects/{project_id}/bundle.zip")
def download_bundle(project_id: str):
    """Everything rendered so far for this project, with titles/descriptions/tags."""
    import zipfile
    p = project_dir(project_id)
    names = [n for n in ["lyric_video.mp4", "autoedit.mp4", "thumbnail.jpg", "youtube.txt", "shorts.json", "clips.json"]
             if (p / n).is_file()]
    names += sorted(f.name for f in p.glob("captions*.*") if FILE_NAME.fullmatch(f.name))
    names += sorted(f.name for f in p.glob("short_*.mp4") if re.fullmatch(r"short_\d+\.mp4", f.name))
    names += sorted(f.name for f in p.glob("clip_*.mp4") if re.fullmatch(r"clip_\d+(\.[a-z]{2})?\.mp4", f.name))
    if not names:
        raise HTTPException(404, "Nothing has been rendered yet")
    target = p / "bundle.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for name in names:
            archive.write(p / name, name)
    return FileResponse(target, media_type="application/zip", filename="SkellyMotion-bundle.zip")


# ---- Long video -> clips -----------------------------------------------------
@app.post("/api/clip-sources")
async def create_clip_source(file: UploadFile = File(...), recognition: str = Form("balanced"),
                             language: str = Form("auto"), vocabulary: str = Form(""),
                             performance_mode: str = Form("balanced"), use_ai: bool = Form(False),
                             keep_fillers: bool = Form(True)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, "Upload an MP4, MOV, MKV, M4V or WebM video")
    project_id = uuid.uuid4().hex
    p = DATA / project_id
    p.mkdir(parents=True)
    name = "source" + ext
    try:
        await save_upload(file, p / name, max_clip_source_bytes())
        duration = media_duration(p / name)
        if not 3 < duration <= max_clip_source_seconds():
            raise HTTPException(400, "Video length must be between 3 seconds and "
                                     f"{round(max_clip_source_seconds() / 60)} minutes")
        data = {"id": project_id, "kind": "clip_source", "title": Path(file.filename or "My video").stem[:100],
                "audio_file": name, "source_file": name, "duration": duration, "status": "transcribing",
                "draft_lyrics": "", "original_words": [], "lines": [], "settings": {}, "language": None,
                "transcription_stage": "queued", "transcription_progress": 0, "save_state": "saved",
                "use_ai": bool(use_ai), "keep_fillers": bool(keep_fillers),
                **recognition_options(recognition, language, vocabulary, performance_mode)}
        save_project(p, data)
        ai_executor.submit(analyze_clip_source, project_id)
        return {"id": project_id, "duration": duration, "status": "transcribing", "kind": "clip_source"}
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


def clip_suggestions_for(data: dict, project_id: str, count: int, use_ai: bool,
                         min_len: float = clips.CLIP_MIN, max_len: float = clips.CLIP_MAX) -> list[dict]:
    pool = clips.suggest_clips(data.get("original_words") or [], data.get("clip_envelope") or [],
                               float(data["duration"]), data.get("scene_times") or [],
                               count=15 if use_ai else count, min_len=min_len, max_len=max_len)
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if use_ai and key and pool:
        model = os.environ.get("SKELLYMOTION_LLM_MODEL", "claude-haiku-5-5")
        pool = clips.apply_llm_rerank(pool, clips.llm_rerank(pool, key, model))
    return sorted(pool, key=lambda c: -c["score"])[:count]


def analyze_clip_source(project_id: str) -> None:
    """Transcribe, probe loudness and scene changes, then suggest clips."""
    p = DATA / project_id
    try:
        transcribe_project(project_id)
        data = json.loads((p / "project.json").read_text(encoding="utf-8"))
        if data.get("transcription_stage") != "complete" or not data.get("original_words"):
            data["status"] = "failed"
            data["clip_error"] = data.get("transcription_error") or "No speech was detected in this video."
            save_project(p, data)
            return
        data["status"] = "analyzing"
        data["transcription_stage"] = "analyzing"
        save_project(p, data)
        source = p / data["source_file"]
        try:
            data["clip_envelope"] = clips.audio_envelope(source, 600, timeout=1800)
        except Exception:
            data["clip_envelope"] = []
        data["scene_times"] = [round(t, 2) for t in clips.scene_changes(source)][:5000]
        data["clip_suggestions"] = clip_suggestions_for(data, project_id, 8, bool(data.get("use_ai")))
        data["status"] = "ready"
        data["transcription_stage"] = "complete"
        save_project(p, data)
    except Exception as exc:
        try:
            data = json.loads((p / "project.json").read_text(encoding="utf-8"))
            data.update(status="failed", clip_error=str(exc)[:600])
            save_project(p, data)
        except (OSError, ValueError):
            pass


class ClipSuggestRequest(BaseModel):
    count: int = Field(default=8, ge=1, le=12)
    min_seconds: float = Field(default=clips.CLIP_MIN, ge=10, le=90)
    max_seconds: float = Field(default=clips.CLIP_MAX, ge=15, le=120)
    use_ai: bool = False


class ClipsRenderRequest(BaseModel):
    clips: list[dict]
    settings: dict = Field(default_factory=dict)
    reframe: str = "center"
    polish: dict = Field(default_factory=dict)  # loudness, watermark, trim_silence, min_gap, voice_cleanup
    languages: list[str] = Field(default_factory=list)  # burn translated captions into extra copies (needs an API key)


@app.post("/api/projects/{project_id}/clips/suggestions")
def regenerate_clip_suggestions(project_id: str, body: ClipSuggestRequest):
    data = read_project(project_id)
    if data.get("kind") != "clip_source" or data.get("status") != "ready":
        raise HTTPException(409, "This video is not ready for clip suggestions")
    if body.max_seconds < body.min_seconds + 5:
        raise HTTPException(400, "Maximum length must be at least 5 seconds above the minimum")
    suggestions = clip_suggestions_for(data, project_id, body.count, body.use_ai,
                                       body.min_seconds, body.max_seconds)
    fresh = read_project(project_id)
    fresh["clip_suggestions"] = suggestions
    save_project(project_dir(project_id), fresh)
    return {"suggestions": suggestions}


@app.post("/api/projects/{project_id}/clips/render")
def render_clips(project_id: str, body: ClipsRenderRequest):
    data = read_project(project_id)
    if data.get("kind") != "clip_source" or data.get("status") != "ready":
        raise HTTPException(409, "This video is not ready to clip")
    if not 1 <= len(body.clips) <= 12:
        raise HTTPException(400, "Choose between 1 and 12 clips")
    picked = []
    for row in body.clips:
        if not isinstance(row, dict):
            continue
        start = clamp(row.get("start"), 0, data["duration"], 0)
        end = clamp(row.get("end"), 0, data["duration"], data["duration"])
        if 3 <= end - start <= 120:
            picked.append({"start": start, "end": end,
                           "hook": str(row.get("hook") or "")[:80],
                           "title": str(row.get("title") or row.get("hook") or "Clip")[:100],
                           "description": str(row.get("description") or "")[:500],
                           "tags": [str(t)[:30] for t in (row.get("tags") or [])[:12]],
                           "score": row.get("score"), "reasons": row.get("reasons") or []})
    if not picked:
        raise HTTPException(400, "Each clip must be between 3 and 120 seconds")
    settings = short_settings({**(data.get("settings") or {}), **(body.settings or {})})
    reframe = body.reframe if body.reframe in {"center", "follow"} else "center"
    polish = {"loudness": bool(body.polish.get("loudness")), "watermark": bool(body.polish.get("watermark")),
              "trim_silence": bool(body.polish.get("trim_silence")),
              "min_gap": clamp(body.polish.get("min_gap"), .4, 3, .8),
              "voice_cleanup": body.polish.get("voice_cleanup") if body.polish.get("voice_cleanup") in sa.CLEANUP_LEVELS else "off"}
    languages = [x for x in dict.fromkeys(body.languages) if x in edit.LANGUAGES][:3]
    if languages and not llm_key_and_model()[0]:
        raise HTTPException(409, "Translated clips need ANTHROPIC_API_KEY set on this computer")
    job_id = register_job(project_id, "clips", settings)
    executor.submit(run_clips, project_id, job_id, picked, settings, reframe, polish, languages)
    return {"job_id": job_id}


def brand_dir() -> Path:
    folder = DATA / "_brand"  # not a 32-hex id, so project listing and cleanup never touch it
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def brand_logo_path() -> Path | None:
    # Read-only brand checks must not create storage on invalid requests.
    logo = DATA / "_brand" / "logo.png"
    return logo if logo.is_file() else None


ASSET_EXTENSIONS = {"music": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}, "intro": VIDEO_EXT, "outro": VIDEO_EXT}
ASSET_LIMITS = {"music": 40 * 1024 * 1024, "intro": 200 * 1024 * 1024, "outro": 200 * 1024 * 1024}


def brand_asset(kind: str) -> Path | None:
    if kind not in ASSET_EXTENSIONS:
        return None
    return next(iter(sorted((DATA / "_brand").glob(f"{kind}.*"))), None)


def store_brand_asset(kind: str, src: Path) -> None:
    """Validate and keep your background music or intro/outro clip. Raises ValueError with a readable reason."""
    if kind not in ASSET_EXTENSIONS:
        raise ValueError("Unknown brand asset")
    ext = src.suffix.lower()
    allowed = ASSET_EXTENSIONS[kind]
    known_media_ext = any(ext in extensions for extensions in ASSET_EXTENSIONS.values())
    # Reject arbitrary files before probing, but inspect known media from the
    # other asset category so users get the useful media-type error (e.g. an
    # audio-only WAV selected as an intro should say it has no video).
    if ext not in allowed and not known_media_ext:
        raise ValueError("Unsupported file type: " + ", ".join(sorted(allowed)))
    info = clips.probe_media(src)
    if kind == "music" and not info["has_audio"]:
        raise ValueError("That file has no audio")
    if kind != "music":
        if not info["has_video"] or not info["width"]:
            raise ValueError("That file has no video")
        if ext not in allowed:
            raise ValueError("Unsupported file type: " + ", ".join(sorted(allowed)))
        if info["duration"] > 20.5:
            raise ValueError("Intro and outro clips can be at most 20 seconds")
    elif ext not in allowed:
        raise ValueError("Unsupported file type: " + ", ".join(sorted(allowed)))
    for old in brand_dir().glob(f"{kind}.*"):
        old.unlink(missing_ok=True)
    shutil.copy2(src, brand_dir() / f"{kind}{ext}")


def load_brand() -> dict:
    try:
        raw = json.loads((DATA / "_brand" / "brand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    raw["has_logo"] = brand_logo_path() is not None
    for kind in ASSET_EXTENSIONS:
        raw[f"has_{'music' if kind == 'music' else kind}"] = brand_asset(kind) is not None
    return edit.sanitize_brand(raw)


def save_brand_json(brand: dict) -> None:
    (brand_dir() / "brand.json").write_text(json.dumps(brand, indent=2), encoding="utf-8")


def brand_signature(brand: dict, logo: Path | None) -> dict:
    return {"brand": brand, "logo": [logo.stat().st_size, logo.stat().st_mtime_ns] if logo else None}


def encode_graph(job_id: str, settings: dict, folder: Path, build, temporary: Path) -> float:
    """Run a filter-graph render (graph kept in a file: long expressions exceed Windows' command-line limit).

    `build(codec, target, script_name)` returns (ffmpeg args, graph text, output seconds).
    """
    graph_file = folder / f"graph-{job_id[:12]}.txt"
    state: dict[str, Any] = {}

    def args_for(codec: str, target: Path) -> list[str]:
        args, graph, seconds = build(codec, target, graph_file.name)
        state.update(graph=graph, seconds=seconds)
        return args

    args_for("libx264", temporary)  # learn the output length and graph before encoding starts
    graph_file.write_text(state["graph"], encoding="utf-8")
    try:
        encode_with_fallback(job_id, settings, state["seconds"], folder, args_for, temporary)
    finally:
        graph_file.unlink(missing_ok=True)
    return state["seconds"]


def clip_caption_plan(data: dict, item: dict, polish: dict | None) -> tuple[list[dict], list | None, float]:
    """(caption words on the clip's own timeline, silence-trim segments or None, clip length)."""
    polish = polish or {}
    start, end = item["start"], item["end"]
    length = end - start
    words = clips.clip_words(data.get("original_words") or [], start, end)
    segments = None
    if polish.get("trim_silence"):
        segments = edit.plan_keep_segments(words, length, clamp(polish.get("min_gap"), .4, 3, .8))
        if edit.is_noop_cut(segments, length):
            segments = None
    return (edit.remap_words(words, segments) if segments else words), segments, length


def render_one_clip(project_id: str, job_id: str, n: int, item: dict, settings: dict,
                    reframe: str, media: dict, polish: dict | None = None, variant: dict | None = None) -> None:
    """Render one vertical clip. With `variant` ({"lang", "cues", "hook"}) the captions and hook card are the
    translated ones and the file is clip_<n>.<lang>.mp4."""
    polish = polish or {}
    p = project_dir(project_id)
    data = read_project(project_id)
    source = p / data["source_file"]
    start, end = item["start"], item["end"]
    w, h = output_size(settings)
    src_w, src_h = media["width"], media["height"]
    crop_w, crop_h = clips.crop_geometry(src_w, src_h)
    tag = f".{variant['lang']}" if variant else ""
    slot = f"clip_{n}_{variant['lang']}" if variant else f"clip_{n}"
    output = p / f"clip_{n}{tag}.mp4"
    caption_words, segments, length = clip_caption_plan(data, item, polish)
    hook = variant["hook"] if variant else item["hook"]
    brand = load_brand()
    logo = brand_logo_path() if polish.get("watermark") and brand["watermark"]["enabled"] else None
    fingerprint = perf.render_fingerprint(
        [{"clip": hook, "start": start, "end": end, "reframe": reframe, "words": caption_words,
          "lang": variant["lang"] if variant else None, "cues": variant["cues"] if variant else None,
          "polish": {k: polish.get(k) for k in ("loudness", "watermark", "trim_silence", "min_gap")},
          "brand": brand_signature(brand, logo) if logo else None}], settings, source, None, False)
    if cached_output(p, slot, fingerprint, output):
        with job_lock:
            jobs[job_id].update(stage="cached", cached=True)
        return
    if reframe == "follow":
        centers = clips.smooth_centers(clips.activity_centers(source, start, length))
        x_expr = clips.crop_x_expression([clips.crop_x(c, src_w, crop_w) for c in centers])
    else:
        x_expr = str(clips.crop_x(.5, src_w, crop_w))
    ass_file = p / f"{slot}.ass"
    if variant:  # translated captions are whole lines (there are no word timings for them)
        line_style = sanitize_settings({**settings, "mode": "line", "animation": "fade", "fontSize": 46, "position": 68})
        create_ass(edit.cue_lines(variant["cues"]), line_style, w, h, ass_file)
    else:
        create_ass(clips.lines_from_words(caption_words), settings, w, h, ass_file)
    clips.add_hook_to_ass(ass_file, hook, w, h, 1.5, settings["font"])
    profile = perf.profile_config(settings["performanceMode"])
    fps = settings["fps"]

    def build(codec: str, target: Path, script: str):
        return edit.build_render(
            source, w, h, fps, target, perf.encode_args(codec, settings["renderSpeed"], w, h, profile["threads"]),
            duration=length, start=start, length=length, crop=(crop_w, crop_h, x_expr), segments=segments,
            ass_name=ass_file.name, logo=logo, brand=brand, watermark=logo is not None,
            loudness=-14.0 if polish.get("loudness") else None, has_audio=media["has_audio"], script_name=script,
            voice_filters=sa.voice_cleanup_filters(polish.get("voice_cleanup", "off")))

    temporary = p / f"render-{job_id}.mp4"
    encode_graph(job_id, settings, p, build, temporary)
    temporary.replace(output)
    remember_output(p, slot, fingerprint)


def translated_variant(data: dict, item: dict, polish: dict | None, lang: str, key: str, model: str) -> dict:
    """Translate one clip's captions and hook (raises RuntimeError if the model cannot do it faithfully)."""
    caption_words, _, _ = clip_caption_plan(data, item, polish)
    cues = edit.cues_from_words(caption_words, max_chars=34)[:60]
    if not cues:
        raise RuntimeError("This clip has no speech to translate")
    translated = edit.translate_cues(cues, lang, key, model)
    hook = item.get("hook", "")
    if hook.strip():
        hook = edit.translate_cues([{"start": 0, "end": 1, "text": hook}], lang, key, model)[0]["text"][:80]
    return {"lang": lang, "cues": translated, "hook": hook}


def render_clips_batch(project_id: str, job_id: str, items: list[dict], settings: dict, reframe: str,
                       polish: dict | None = None, base: int = 2, span: int = 96,
                       languages: list[str] | None = None) -> list[dict]:
    p = project_dir(project_id)
    for old in p.glob("clip_*.mp4"):
        if re.fullmatch(r"clip_(\d+)(\.[a-z]{2})?\.mp4", old.name) and int(re.match(r"clip_(\d+)", old.name).group(1)) > len(items):
            old.unlink(missing_ok=True)
    languages = [x for x in dict.fromkeys(languages or []) if x in edit.LANGUAGES][:3]
    key, model = llm_key_and_model()
    with job_lock:
        jobs[job_id].update(stage="analyzing_video")
    media = clips.probe_media(p / read_project(project_id)["source_file"])
    if not media["width"]:
        raise RuntimeError("Cannot read this video")
    manifest = []
    units = len(items) * (1 + len(languages))
    done = 0
    for index, item_in in enumerate(items, start=1):
        item = {**item_in}
        with job_lock:
            jobs[job_id].update(stage=f"clip_{index}_of_{len(items)}")
        child = new_child_job(job_id, project_id, settings, base + span * done // units, max(1, span // units))
        render_one_clip(project_id, child, index, item, settings, reframe, media, polish)
        finish_child(child)
        done += 1
        entry = {"n": index, "file": f"clip_{index}.mp4", "start": round(item["start"], 2), "end": round(item["end"], 2),
                 "hook": item["hook"], "title": item["title"], "description": item["description"], "tags": item["tags"],
                 "score": item["score"], "reasons": item["reasons"], "url": f"/api/projects/{project_id}/clips/{index}",
                 "translations": [], "translation_errors": []}
        for lang in languages:
            with job_lock:
                jobs[job_id].update(stage=f"clip_{index}_of_{len(items)}_{edit.LANGUAGES[lang]}")
            try:
                variant = translated_variant(read_project(project_id), item, polish, lang, key, model)
                child = new_child_job(job_id, project_id, settings, base + span * done // units, max(1, span // units))
                render_one_clip(project_id, child, index, item, settings, reframe, media, polish, variant)
                finish_child(child)
                entry["translations"].append({"lang": lang, "language": edit.LANGUAGES[lang],
                                              "file": f"clip_{index}.{lang}.mp4",
                                              "url": f"/api/projects/{project_id}/clips/{index}/{lang}"})
            except Exception as exc:  # one language failing must not lose the clip that already rendered
                entry["translation_errors"].append({"lang": lang, "error": str(exc)[:160]})
            done += 1
        manifest.append(entry)
    (p / "clips.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def run_clips(project_id: str, job_id: str, items: list[dict], settings: dict, reframe: str,
              polish: dict | None = None, languages: list[str] | None = None) -> None:
    started = time.monotonic()
    try:
        manifest = render_clips_batch(project_id, job_id, items, settings, reframe, polish, languages=languages)
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100,
                                elapsed_seconds=round(time.monotonic() - started, 2), outputs={"clips": manifest})
    except Exception as exc:
        fail_job(job_id, exc, started)


# ---- Brand kit ---------------------------------------------------------------------------------
class BrandRequest(BaseModel):
    brand: dict


@app.get("/api/brand")
def get_brand():
    return {"brand": load_brand(), "languages": edit.LANGUAGES}


@app.put("/api/brand")
def put_brand(body: BrandRequest):
    brand = edit.sanitize_brand({**body.brand, "has_logo": brand_logo_path() is not None})
    (brand_dir() / "brand.json").write_text(json.dumps(brand, indent=2), encoding="utf-8")
    return {"brand": brand}


@app.post("/api/brand/logo")
async def upload_brand_logo(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        raise HTTPException(400, "Upload a PNG, JPG, WebP or GIF image")
    raw = brand_dir() / f"upload-{uuid.uuid4().hex}.tmp"
    try:
        await save_upload(file, raw, 5 * 1024 * 1024)
        try:
            edit.process_logo(raw, brand_dir() / "logo.png")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        raw.unlink(missing_ok=True)
    brand = load_brand()
    (brand_dir() / "brand.json").write_text(json.dumps(brand, indent=2), encoding="utf-8")
    return {"brand": brand}


@app.get("/api/brand/logo")
def get_brand_logo():
    logo = brand_logo_path()
    if logo is None:
        raise HTTPException(404, "No logo yet")
    return FileResponse(logo, media_type="image/png")


@app.delete("/api/brand/logo")
def delete_brand_logo():
    (brand_dir() / "logo.png").unlink(missing_ok=True)
    brand = load_brand()
    (brand_dir() / "brand.json").write_text(json.dumps(brand, indent=2), encoding="utf-8")
    return {"brand": brand}


@app.post("/api/brand/asset/{kind}")
async def upload_brand_asset(kind: str, file: UploadFile = File(...)):
    if kind not in ASSET_EXTENSIONS:
        raise HTTPException(404, "Unknown brand asset")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ASSET_EXTENSIONS[kind]:
        raise HTTPException(400, "Unsupported file type: " + ", ".join(sorted(ASSET_EXTENSIONS[kind])))
    raw = brand_dir() / f"upload-{uuid.uuid4().hex}{ext}"
    try:
        await save_upload(file, raw, ASSET_LIMITS[kind])
        try:
            store_brand_asset(kind, raw)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        raw.unlink(missing_ok=True)
    brand = load_brand()
    save_brand_json(brand)
    return {"brand": brand}


@app.delete("/api/brand/asset/{kind}")
def delete_brand_asset(kind: str):
    if kind not in ASSET_EXTENSIONS:
        raise HTTPException(404, "Unknown brand asset")
    for old in brand_dir().glob(f"{kind}.*"):
        old.unlink(missing_ok=True)
    brand = load_brand()
    save_brand_json(brand)
    return {"brand": brand}


# ---- B-roll library (your own clips, matched to what you say) -------------------------------------
BROLL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def broll_dir() -> Path:
    folder = brand_dir() / "broll"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def broll_index() -> dict[str, dict]:
    try:
        data = json.loads((broll_dir() / "index.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_broll_index(index: dict) -> None:
    (broll_dir() / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")


def broll_library() -> list[dict]:
    """Library clips that still exist on disk, ready for the planner."""
    items = []
    for name, entry in sorted(broll_index().items()):
        path = broll_dir() / str(entry.get("file", ""))
        if BROLL_NAME.fullmatch(name) and path.is_file() and entry.get("keywords"):
            items.append({"name": name, "path": path, "duration": float(entry.get("duration") or 0),
                          "keywords": list(entry["keywords"])})
    return items


def store_broll(src: Path, original_name: str, keywords_text: str = "") -> dict:
    """Add a clip to the B-roll library. Keywords come from what you typed, else from the file name."""
    ext = src.suffix.lower()
    if ext not in VIDEO_EXT:
        raise ValueError("Unsupported file type: " + ", ".join(sorted(VIDEO_EXT)))
    index = broll_index()
    if len(index) >= broll_lib.MAX_LIBRARY:
        raise ValueError(f"The library holds at most {broll_lib.MAX_LIBRARY} clips. Remove one first.")
    info = clips.probe_media(src)
    if not info["has_video"] or not info["width"]:
        raise ValueError("That file has no video")
    if info["duration"] > 30.5:
        raise ValueError("B-roll clips can be at most 30 seconds")
    keywords = broll_lib.sanitize_keywords(keywords_text) or broll_lib.keywords_from_name(original_name)
    if not keywords:
        raise ValueError("Add at least one keyword (the word you say when this clip should appear)")
    base = broll_lib.slug(original_name)
    name, n = base, 1
    while name in index:
        n += 1
        name = f"{base}-{n}"[:40]
    filename = f"{name}{ext}"
    shutil.copy2(src, broll_dir() / filename)
    index[name] = {"file": filename, "keywords": keywords, "duration": round(info["duration"], 2)}
    save_broll_index(index)
    return {"name": name, "keywords": keywords, "duration": index[name]["duration"]}


def broll_listing() -> list[dict]:
    return [{"name": i["name"], "keywords": i["keywords"], "duration": round(i["duration"], 1)} for i in broll_library()]


@app.get("/api/brand/broll")
def list_broll():
    return {"clips": broll_listing(), "max": broll_lib.MAX_LIBRARY}


@app.post("/api/brand/broll")
async def upload_broll(file: UploadFile = File(...), keywords: str = Form("")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, "Upload an MP4, MOV, MKV, M4V or WebM clip")
    raw = brand_dir() / f"upload-{uuid.uuid4().hex}{ext}"
    try:
        await save_upload(file, raw, 120 * 1024 * 1024)
        try:
            added = store_broll(raw, file.filename or "clip", keywords)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
    finally:
        raw.unlink(missing_ok=True)
    return {"added": added, "clips": broll_listing()}


class BrollKeywords(BaseModel):
    keywords: str


@app.put("/api/brand/broll/{name}")
def update_broll_keywords(name: str, body: BrollKeywords):
    index = broll_index()
    if not BROLL_NAME.fullmatch(name) or name not in index:
        raise HTTPException(404, "Unknown clip")
    cleaned = broll_lib.sanitize_keywords(body.keywords)
    if not cleaned:
        raise HTTPException(400, "Add at least one keyword")
    index[name]["keywords"] = cleaned
    save_broll_index(index)
    return {"clips": broll_listing()}


@app.delete("/api/brand/broll/{name}")
def delete_broll(name: str):
    index = broll_index()
    if not BROLL_NAME.fullmatch(name) or name not in index:
        raise HTTPException(404, "Unknown clip")
    (broll_dir() / str(index[name].get("file", ""))).unlink(missing_ok=True)
    del index[name]
    save_broll_index(index)
    return {"clips": broll_listing()}


# ---- Presets: one-click bundles of the auto-edit options -----------------------------------------------
class PresetRequest(BaseModel):
    options: dict


def load_user_presets() -> dict[str, dict]:
    try:
        data = json.loads((brand_dir() / "presets.json").read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if posts_lib.valid_preset_name(k) and isinstance(v, dict)}
    except (OSError, ValueError, AttributeError):
        return {}


def normalize_options(raw: dict) -> dict:
    """Normalize saved options, dropping unknown keys and clamping bounded values."""
    known = {k: v for k, v in (raw or {}).items() if k in AutoEditRequest.__annotations__}
    if "min_gap" in known:
        known["min_gap"] = clamp(known["min_gap"], .4, 3, .8)
    if "shorts" in known:
        known["shorts"] = int(clamp(known["shorts"], 0, 6, 0))
    try:
        return autoedit_options(AutoEditRequest(**known))
    except Exception as exc:
        raise HTTPException(400, "Invalid option value in the preset") from exc


@app.get("/api/presets")
def get_presets():
    return {"presets": posts_lib.list_presets(load_user_presets())}


@app.put("/api/presets/{name}")
def save_preset(name: str, body: PresetRequest):
    if not posts_lib.valid_preset_name(name):
        raise HTTPException(400, "Use 1-30 letters, numbers, spaces, - _ & or '")
    if name in posts_lib.BUILTIN_PRESETS:
        raise HTTPException(400, "That name belongs to a built-in preset. Pick another.")
    user = load_user_presets()
    if name not in user and len(user) >= posts_lib.MAX_USER_PRESETS:
        raise HTTPException(400, f"You can save up to {posts_lib.MAX_USER_PRESETS} presets")
    user[name] = {k: v for k, v in normalize_options(body.options).items() if k != "title"}
    (brand_dir() / "presets.json").write_text(json.dumps(user, indent=2), encoding="utf-8")
    return {"presets": posts_lib.list_presets(user)}


@app.delete("/api/presets/{name}")
def delete_preset(name: str):
    user = load_user_presets()
    if name not in user:
        raise HTTPException(404, "No such saved preset")
    del user[name]
    (brand_dir() / "presets.json").write_text(json.dumps(user, indent=2), encoding="utf-8")
    return {"presets": posts_lib.list_presets(user)}


# ---- Post text for each platform -----------------------------------------------------------------------------
class PostsRequest(BaseModel):
    title: str
    text: str = ""
    tags: list[str] = Field(default_factory=list)
    hook: str = ""
    link: str = ""
    use_ai: bool = False


@app.post("/api/projects/{project_id}/posts")
def make_posts(project_id: str, body: PostsRequest):
    read_project(project_id)
    link = body.link.strip()
    if link and not re.fullmatch(r"https?://[^\s]{3,200}", link):
        raise HTTPException(400, "The link must start with http:// or https://")
    brand = load_brand()
    tags = [str(t)[:40] for t in body.tags[:15]]
    key, model = llm_key_and_model()
    use_ai = bool(body.use_ai and key)
    args = (body.title[:200], body.text[:4000], tags, brand)
    kwargs = {"link": link or None, "hook": body.hook[:120] or None}
    social = (posts_lib.llm_posts(*args, key, model, **kwargs) if use_ai else posts_lib.build_posts(*args, **kwargs))
    return {"posts": social, "ai": use_ai}


# ---- Transcript proofreading (fix names and jargon before anything is rendered) -----------------------------
class TranscriptEdits(BaseModel):
    edits: list[dict] = Field(default_factory=list)
    replace: list[dict] = Field(default_factory=list)


def require_ready_video(project_id: str) -> dict:
    data = read_project(project_id)
    if data.get("kind") != "clip_source" or data.get("status") != "ready":
        raise HTTPException(409, "This video is not ready for proofreading")
    return data


@app.get("/api/projects/{project_id}/transcript")
def get_transcript(project_id: str):
    data = require_ready_video(project_id)
    words = data.get("original_words") or []
    return {"words": len(words), "uncertain": proof.uncertain_words(words)}


@app.post("/api/projects/{project_id}/transcript")
def edit_transcript(project_id: str, body: TranscriptEdits):
    data = require_ready_video(project_id)
    if len(body.edits) > proof.MAX_EDITS or len(body.replace) > proof.MAX_REPLACEMENTS:
        raise HTTPException(400, "Too many corrections in one go")
    with job_lock:
        reject_if_busy(project_id)
    words, changed = proof.apply_edits(data.get("original_words") or [], body.edits, body.replace)
    fresh = read_project(project_id)
    suggestions = fresh.get("clip_suggestions") or []
    if changed:
        fresh["original_words"] = words
        suggestions = clip_suggestions_for(fresh, project_id, 8, False)
        fresh["clip_suggestions"] = suggestions
        save_project(project_dir(project_id), fresh)
    return {"changed": changed, "uncertain": proof.uncertain_words(words), "suggestions": suggestions}


# ---- Before/after demos and audio-reactive visualizers ---------------------------------------------------------
DEMO_AUDIO_EXT = ASSET_EXTENSIONS["music"] | VIDEO_EXT
DEMO_KINDS = ("ab", "viz")


def prune_demo_projects(max_age_days: float = 3.0) -> None:
    """One-off demo projects are not part of the library, so they are cleared out after a few days."""
    cutoff = time.time() - max_age_days * 86400
    if not DATA.exists():
        return
    for folder in DATA.iterdir():
        manifest = folder / "project.json"
        if not (folder.is_dir() and re.fullmatch(r"[0-9a-f]{32}", folder.name) and manifest.is_file()):
            continue
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("kind") in DEMO_KINDS and manifest.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except (OSError, ValueError):
            continue


def demo_project(kind: str, title: str, files: dict[str, Path], extra: dict) -> str:
    """Copy source files into a fresh demo project folder. Returns its id."""
    prune_demo_projects()
    project_id = uuid.uuid4().hex
    p = DATA / project_id
    p.mkdir(parents=True)
    try:
        saved = {}
        for label, src in files.items():
            target = p / f"{label}{src.suffix.lower()}"
            shutil.copy2(src, target)
            saved[label] = target.name
        save_project(p, {"id": project_id, "kind": kind, "title": title[:100] or "Demo", "status": "working",
                         "save_state": "saved", "duration": 0, "files": saved, **extra})
        return project_id
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


def demo_options(raw: dict) -> dict:
    """Validated, clamped options shared by the before/after and visualizer jobs."""
    out = {"aspect": raw.get("aspect") if raw.get("aspect") in viz_lib.ASPECTS else "landscape",
           "resolution": "720p" if raw.get("resolution") == "720p" else "1080p",
           "title": edit._clip_text(raw.get("title"), 70), "watermark": bool(raw.get("watermark", True)),
           "endcard": bool(raw.get("endcard", False))}
    return out


def finish_with_brand(p: Path, job_id: str, settings: dict, raw: Path, final: Path, W: int, H: int, fps: int,
                      seconds: float, opts: dict, brand: dict, logo: Path | None, base: int, span: int) -> None:
    """Optional second pass: logo watermark and brand end card on top of a finished demo render."""
    watermark = bool(opts["watermark"] and brand["watermark"]["enabled"] and logo)
    card = None
    if opts["endcard"] and brand["endcard"]["enabled"]:
        edit.write_endcard_ass(p / "endcard.ass", brand, W, H, brand["endcard"]["seconds"], logo is not None)
        card = "endcard.ass"
    if not watermark and not card:
        raw.replace(final)
        return
    child = new_child_job(job_id, p.name, settings, base, span)
    profile = perf.profile_config(settings["performanceMode"])
    temporary = p / f"render-{child}.mp4"

    def build(codec: str, target: Path, script: str):
        return edit.build_render(raw, W, H, fps, target, perf.encode_args(codec, settings["renderSpeed"], W, H, profile["threads"]),
                                 duration=seconds, logo=logo, brand=brand, watermark=watermark, endcard_ass=card,
                                 has_audio=True, script_name=script)
    encode_graph(child, settings, p, build, temporary)
    temporary.replace(final)
    finish_child(child)
    raw.unlink(missing_ok=True)


@app.post("/api/ab")
async def create_before_after(before: UploadFile = File(...), after: UploadFile = File(...), mode: str = Form("repeat"),
                              step: float = Form(4.0), rounds: int = Form(2), aspect: str = Form("landscape"),
                              resolution: str = Form("1080p"), match_loudness: bool = Form(True), title: str = Form(""),
                              label_before: str = Form("BEFORE"), label_after: str = Form("AFTER"),
                              start: str = Form(""), watermark: bool = Form(True), endcard: bool = Form(False)):
    for upload in (before, after):
        if Path(upload.filename or "").suffix.lower() not in DEMO_AUDIO_EXT:
            raise HTTPException(400, "Upload audio (MP3, WAV, M4A...) or a video recording for both files")
    mode = mode if mode in ("repeat", "toggle") else "repeat"
    step = float(min(10.0, max(2.0, clamp(step, 2, 10, 4.0))))
    rounds = int(min(4, max(1, rounds)))
    tmp = DATA / f"upload-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True)
    try:
        paths = {}
        for label, upload in (("before", before), ("after", after)):
            dest = tmp / f"{label}{Path(upload.filename or '').suffix.lower()}"
            await save_upload(upload, dest, 150 * 1024 * 1024)
            info = clips.probe_media(dest)
            if not info["has_audio"] or info["duration"] < step + .5:
                raise HTTPException(400, f"The {label} file needs audio and must be at least {step + .5:.0f} seconds long")
            paths[label] = dest
        opts = {**demo_options({"aspect": aspect, "resolution": resolution, "title": title, "watermark": watermark,
                                "endcard": endcard}),
                "mode": mode, "step": step, "rounds": rounds, "match": bool(match_loudness),
                "labels": [viz_lib.clean_label(label_before, "BEFORE"), viz_lib.clean_label(label_after, "AFTER")],
                "start": clamp(start, 0, 36000, -1.0) if str(start).strip() else None}
        project_id = demo_project("ab", opts["title"] or "Before and after", paths, {"options": opts})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    settings = sanitize_settings({"aspect": "landscape"})
    job_id = register_job(project_id, "ab", settings)
    executor.submit(run_before_after, project_id, job_id, opts, settings)
    return {"job_id": job_id, "id": project_id}


def run_before_after(project_id: str, job_id: str, opts: dict, settings: dict) -> None:
    started = time.monotonic()
    try:
        p = project_dir(project_id)
        files = read_project(project_id)["files"]
        before, after = p / files["before"], p / files["after"]
        info_a, info_b = clips.probe_media(before), clips.probe_media(after)
        step, rounds, mode = opts["step"], opts["rounds"], opts["mode"]
        length = viz_lib.excerpt_length(mode, step, rounds)
        usable = min(info_a["duration"], info_b["duration"])
        if usable < length + .2:
            raise RuntimeError(f"Both files need at least {length + .2:.0f} seconds for these settings (shortest is {usable:.0f})")
        with job_lock:
            jobs[job_id].update(stage="ab_analyze", progress=3)
        start = opts["start"]
        if start is None or start < 0:
            start = viz_lib.pick_excerpt(clips.audio_envelope(before, 600), info_a["duration"], length)
        start = min(max(0.0, start), usable - length - .1)
        ref = sa.decode_mono(before, start=start, length=length)
        other = sa.decode_mono(after, start=start, length=length)
        gain = sa.match_gain_db(ref, other) if opts["match"] else 0.0
        viz_gain = max(0.0, min(18.0, -18.0 - sa.rms_db(ref)))
        W, H = viz_lib.output_size(opts["aspect"], opts["resolution"])
        fps = 30
        brand, logo = load_brand(), brand_logo_path()
        segments = viz_lib.ab_segments(mode, start, step, rounds)
        viz_lib.write_ab_ass(p / "ab.ass", brand, W, H, segments, step, tuple(opts["labels"]), opts["title"], opts["match"])
        profile = perf.profile_config(settings["performanceMode"])
        child = new_child_job(job_id, project_id, settings, 6, 70)
        temporary = p / f"render-{child}.mp4"

        def build(codec: str, target: Path, script: str):
            return viz_lib.build_ab_render(
                before, after, W, H, fps, target, perf.encode_args(codec, settings["renderSpeed"], W, H, profile["threads"]),
                segments=segments, step=step, brand=brand, ass_name="ab.ass", after_gain_db=gain, viz_gain_db=viz_gain,
                script_name=script)
        seconds = encode_graph(child, settings, p, build, temporary)
        temporary.replace(p / "ab_raw.mp4")
        finish_child(child)
        finish_with_brand(p, job_id, settings, p / "ab_raw.mp4", p / "ab.mp4", W, H, fps, seconds, opts, brand, logo, 78, 20)
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100,
                                elapsed_seconds=round(time.monotonic() - started, 2),
                                outputs={"video": file_url(project_id, "ab.mp4"), "seconds": round(seconds, 1),
                                         "gain_db": round(gain, 1), "start": round(start, 1), "mode": mode,
                                         "matched": opts["match"]})
    except Exception as exc:
        fail_job(job_id, exc, started)


def render_visualizer_video(project_id: str, job_id: str, audio_path: Path, opts: dict, settings: dict, *,
                            with_audio: bool, out_name: str, title: str = "", artist: str = "", base: int = 4,
                            span: int = 70) -> float:
    """Render an audio-reactive video next to the project. Returns its length in seconds."""
    p = project_dir(project_id)
    info = clips.probe_media(audio_path)
    if not info["has_audio"] or info["duration"] < 1:
        raise RuntimeError("That file has no audio")
    W, H = viz_lib.output_size(opts["aspect"], opts["resolution"])
    fps = 30
    brand, logo = load_brand(), brand_logo_path()
    gain = max(0.0, min(18.0, -18.0 - sa.rms_db(sa.decode_mono(audio_path))))
    ass_name = None
    if with_audio and (title or artist):
        viz_lib.write_title_ass(p / "viz_title.ass", brand, W, H, title, artist or brand["name"], info["duration"])
        ass_name = "viz_title.ass"
    profile = perf.profile_config(settings["performanceMode"])
    child = new_child_job(job_id, project_id, settings, base, span)
    temporary = p / f"render-{child}.mp4"

    def build(codec: str, target: Path, script: str):
        return viz_lib.build_visualizer_render(
            audio_path, W, H, fps, target, perf.encode_args(codec, settings["renderSpeed"], W, H, profile["threads"]),
            duration=info["duration"], style=opts["style"], brand=brand, viz_gain_db=gain, with_audio=with_audio,
            ass_name=ass_name, logo=logo, watermark=bool(with_audio and opts.get("watermark") and brand["watermark"]["enabled"]),
            script_name=script)
    seconds = encode_graph(child, settings, p, build, temporary)
    temporary.replace(p / out_name)
    finish_child(child)
    return seconds


@app.post("/api/visualizer")
async def create_visualizer(audio_file: UploadFile = File(...), style: str = Form("bars"), aspect: str = Form("landscape"),
                            resolution: str = Form("1080p"), title: str = Form(""), artist: str = Form(""),
                            watermark: bool = Form(True)):
    if Path(audio_file.filename or "").suffix.lower() not in DEMO_AUDIO_EXT:
        raise HTTPException(400, "Upload an audio file (MP3, WAV, M4A...) or a video")
    tmp = DATA / f"upload-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True)
    try:
        dest = tmp / ("track" + Path(audio_file.filename or "").suffix.lower())
        await save_upload(audio_file, dest, 250 * 1024 * 1024)
        info = clips.probe_media(dest)
        if not info["has_audio"]:
            raise HTTPException(400, "That file has no audio")
        if info["duration"] > 20 * 60:
            raise HTTPException(400, "Visualizer videos can be at most 20 minutes long")
        opts = {**demo_options({"aspect": aspect, "resolution": resolution, "title": title, "watermark": watermark}),
                "style": style if style in viz_lib.STYLES else "bars", "artist": edit._clip_text(artist, 60)}
        project_id = demo_project("viz", opts["title"] or "Visualizer", {"track": dest}, {"options": opts})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    settings = sanitize_settings({"aspect": "landscape"})
    job_id = register_job(project_id, "viz", settings)
    executor.submit(run_visualizer, project_id, job_id, opts, settings)
    return {"job_id": job_id, "id": project_id}


def run_visualizer(project_id: str, job_id: str, opts: dict, settings: dict) -> None:
    started = time.monotonic()
    try:
        p = project_dir(project_id)
        track = p / read_project(project_id)["files"]["track"]
        with job_lock:
            jobs[job_id].update(stage="viz_render", progress=3)
        seconds = render_visualizer_video(project_id, job_id, track, opts, settings, with_audio=True,
                                          out_name="visualizer.mp4", title=opts["title"], artist=opts["artist"], span=90)
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100,
                                elapsed_seconds=round(time.monotonic() - started, 2),
                                outputs={"video": file_url(project_id, "visualizer.mp4"), "seconds": round(seconds, 1)})
    except Exception as exc:
        fail_job(job_id, exc, started)


class SongVisualizerRequest(BaseModel):
    style: str = "bars"
    lyrics: bool = True  # draw the lyrics over it with the normal lyric renderer


@app.post("/api/projects/{project_id}/visualizer")
def song_visualizer(project_id: str, body: SongVisualizerRequest):
    data = read_project(project_id)
    if data.get("kind") in ("clip_source", "ab", "viz") or data.get("status") == "transcribing":
        raise HTTPException(409, "Open a song that has finished transcribing")
    style = body.style if body.style in viz_lib.STYLES else "bars"
    settings = sanitize_settings({**(data.get("settings") or {})})
    job_id = register_job(project_id, "viz", settings)
    executor.submit(run_song_visualizer, project_id, job_id, style, bool(body.lyrics), settings)
    return {"job_id": job_id}


def run_song_visualizer(project_id: str, job_id: str, style: str, lyrics: bool, settings: dict) -> None:
    started = time.monotonic()
    try:
        p = project_dir(project_id)
        data = read_project(project_id)
        lines = song_lines_for(data) if lyrics else []
        opts = {"style": style, "aspect": settings["aspect"], "resolution": settings["resolution"], "watermark": False}
        with job_lock:
            jobs[job_id].update(stage="viz_render", progress=3)
        if not lines:  # no lyrics to draw: a finished music-visualizer video with the song's title
            seconds = render_visualizer_video(project_id, job_id, p / data["audio_file"], opts, settings, with_audio=True,
                                              out_name="visualizer.mp4", title=data.get("title", ""), span=90)
            outputs = {"video": file_url(project_id, "visualizer.mp4"), "seconds": round(seconds, 1), "lyrics": False}
        else:
            render_visualizer_video(project_id, job_id, p / data["audio_file"], opts, settings, with_audio=False,
                                    out_name="visualizer_bg.mp4", span=40)
            fresh = read_project(project_id)
            fresh["background_file"] = "visualizer_bg.mp4"
            save_project(p, fresh)
            lyric_settings = sanitize_settings({**settings, "background": "custom"})
            with job_lock:
                jobs[job_id].update(stage="viz_lyrics", progress=48)
            child = new_child_job(job_id, project_id, lyric_settings, 48, 50)
            render_project(project_id, child, lyric_settings, validate_lines(lines, data["duration"]))
            finish_child(child)
            outputs = {"video": f"/api/projects/{project_id}/export", "lyrics": True}
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100,
                                elapsed_seconds=round(time.monotonic() - started, 2), outputs=outputs)
    except Exception as exc:
        fail_job(job_id, exc, started)


# ---- Auto-edit: one button that turns a recording into a finished, uploadable video ---------------
class AutoEditRequest(BaseModel):
    trim_silence: bool = True
    min_gap: float = Field(default=.8, ge=.4, le=3)
    zoom: str = "off"  # off | subtle | medium | strong
    loudness: bool = True
    captions: bool = False  # burn captions into the picture (SRT/VTT files are always written)
    watermark: bool = True
    endcard: bool = True
    resolution: str = "1080p"
    shorts: int = Field(default=0, ge=0, le=6)
    shorts_reframe: str = "center"
    title: str | None = None
    # Added automatically by the "director" (all optional, all on by default)
    sfx: bool = True  # synthesized whooshes/pops at titles, callouts, jump cuts and zooms
    callouts: bool = True  # animated callout boxes when you say "tip", "never", "remember"...
    chapter_titles: bool = True  # sliding lower-third at each chapter
    music: bool = True  # your background track from the brand kit, ducked under your voice
    intro_outro: bool = True  # your intro/outro clips from the brand kit
    intro_card: bool = False  # an animated title card at the start (when there is no intro clip)
    voice_cleanup: str = "off"  # off | light | medium | strong: rumble, noise and gentle compression on narration
    fillers: str = "off"  # off | basic (um, uh) | more (also "you know", "I mean", "sort of", "kind of")
    zoom_mode: str = "motion"  # motion: follow what moves | ui: zoom to small sudden changes and mark them with a ring
    broll: bool = True  # cut in clips from your B-roll library when you say their keywords


FILE_NAME = re.compile(r"autoedit\.mp4|thumbnail\.jpg|youtube\.txt|posts\.txt|ab\.mp4|visualizer\.mp4|captions(\.[a-z]{2})?\.(srt|vtt)")
FILE_TYPES = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".txt": "text/plain; charset=utf-8",
              ".srt": "application/x-subrip", ".vtt": "text/vtt; charset=utf-8"}


def autoedit_options(body: AutoEditRequest) -> dict:
    return {"trim_silence": bool(body.trim_silence), "min_gap": float(body.min_gap),
            "zoom": body.zoom if body.zoom in edit.ZOOM_LEVELS else "off", "loudness": bool(body.loudness),
            "captions": bool(body.captions), "watermark": bool(body.watermark), "endcard": bool(body.endcard),
            "resolution": "720p" if body.resolution == "720p" else "1080p", "shorts": int(body.shorts),
            "shorts_reframe": "follow" if body.shorts_reframe == "follow" else "center",
            "title": (body.title or "").strip()[:100] or None, "sfx": bool(body.sfx), "callouts": bool(body.callouts),
            "chapter_titles": bool(body.chapter_titles), "music": bool(body.music),
            "intro_outro": bool(body.intro_outro), "intro_card": bool(body.intro_card),
            "voice_cleanup": body.voice_cleanup if body.voice_cleanup in sa.CLEANUP_LEVELS else "off",
            "fillers": body.fillers if body.fillers in sa.FILLER_LEVELS else "off",
            "zoom_mode": "ui" if body.zoom_mode == "ui" else "motion", "broll": bool(body.broll)}


def file_url(project_id: str, name: str) -> str:
    return f"/api/projects/{project_id}/files/{name}"


@app.get("/api/projects/{project_id}/files/{name}")
def download_generated_file(project_id: str, name: str):
    if not FILE_NAME.fullmatch(name):
        raise HTTPException(404, "Unknown file")
    f = project_dir(project_id) / name
    if not f.is_file():
        raise HTTPException(404, "That file has not been created yet")
    return FileResponse(f, media_type=FILE_TYPES[f.suffix], filename=f"SkellyMotion-{name}")


@app.post("/api/projects/{project_id}/autoedit")
def start_autoedit(project_id: str, body: AutoEditRequest):
    data = read_project(project_id)
    if data.get("kind") != "clip_source" or data.get("status") != "ready":
        raise HTTPException(409, "Add a video and wait for the analysis to finish first")
    opts = autoedit_options(body)
    settings = sanitize_settings({**(data.get("settings") or {}), "aspect": "landscape"})
    job_id = register_job(project_id, "autoedit", settings)
    executor.submit(run_autoedit, project_id, job_id, opts, settings)
    return {"job_id": job_id}


def source_time_at(out_t: float, segments: list[tuple[float, float]]) -> float:
    """Inverse of edit.map_time: where an output-timeline moment came from in the source."""
    acc = 0.0
    for a, b in segments:
        if out_t <= acc + (b - a):
            return a + max(0.0, out_t - acc)
        acc += b - a
    return segments[-1][1]


def clip_info(path: Path | None) -> dict | None:
    """Intro/outro clip details for the render graph, or None if it is missing or unreadable."""
    if path is None or not path.is_file():
        return None
    info = clips.probe_media(path)
    if not info["has_video"] or not info["width"]:
        return None
    return {"path": path, "duration": info["duration"], "has_audio": info["has_audio"]}


def run_autoedit(project_id: str, job_id: str, opts: dict, settings: dict) -> None:
    started = time.monotonic()
    try:
        p = project_dir(project_id)
        data = read_project(project_id)
        source = p / data["source_file"]
        words = data.get("original_words") or []
        duration = float(data["duration"])
        media = clips.probe_media(source)
        if not media["width"]:
            raise RuntimeError("Cannot read this video")
        brand, logo = load_brand(), brand_logo_path()
        W, H = (1280, 720) if opts["resolution"] == "720p" else (1920, 1080)
        fps = int(min(30, max(15, round(media["fps"] or 30))))
        profile = perf.profile_config(settings["performanceMode"])

        with job_lock:
            jobs[job_id].update(stage="autoedit_plan", progress=2)
        segments = (edit.plan_keep_segments(words, duration, opts["min_gap"])
                    if opts["trim_silence"] and words else [(0.0, duration)])
        filler_cuts = sa.filler_ranges(words, opts["fillers"])
        if filler_cuts:
            segments = sa.subtract_ranges(segments, filler_cuts) or segments
        zoom, ui_events = [], []
        if opts["zoom"] != "off":
            with job_lock:
                jobs[job_id].update(stage="autoedit_zoom", progress=4)
            if opts["zoom_mode"] == "ui":
                ui_events = focus.detect_ui_events(edit.activity_track(source, 0, duration, fps=5))
                zoom = focus.plan_ui_zoom(ui_events, opts["zoom"])
            else:
                zoom = edit.plan_zoom(edit.activity_track(source, 0, duration), opts["zoom"])
        out_words = edit.remap_words(words, segments)
        main_len = edit.kept_duration(segments)
        title = opts["title"] or data.get("title") or "My video"
        transcript = " ".join(w["text"] for w in words)
        sentences = clips.split_sentences(out_words)
        chapters = edit.plan_chapters(sentences, main_len)

        # The director: clips, music, animations and sound effects, chosen from what is said and where cuts fall.
        music = None
        if opts["music"] and brand_asset("music"):
            music = {"path": brand_asset("music"), "volume": brand["audio"]["music_volume"]}
        intro_clip = clip_info(brand_asset("intro")) if opts["intro_outro"] else None
        outro_clip = clip_info(brand_asset("outro")) if opts["intro_outro"] else None
        intro_card, intro_secs = None, 0.0
        if opts["intro_card"] and not intro_clip:
            intro_secs, intro_card = 2.5, "intro.ass"
            edit.write_intro_card_ass(p / intro_card, brand, W, H, intro_secs, logo is not None, title)
        lead = (min(intro_clip["duration"], 20.0) if intro_clip else 0.0) + intro_secs
        plan = edit.plan_enhancements(sentences, chapters, segments, zoom, main_len, sfx=opts["sfx"],
                                      callouts=opts["callouts"], chapter_titles=opts["chapter_titles"])

        rings = focus.ring_marks(ui_events, zoom, segments, main_len) if ui_events and zoom else []
        if rings and opts["sfx"]:  # a soft tick on each ring, still spaced out like every other effect
            merged = sorted(plan["sfx"] + [(r["t"], "pop", .4) for r in rings])
            plan["sfx"] = [e for i, e in enumerate(merged) if i == 0 or e[0] - merged[i - 1][0] >= .9]
        broll_plan = []
        if opts["broll"]:
            library = broll_library()
            broll_plan = broll_lib.plan_broll(out_words, library, main_len) if library else []

        cues = edit.cues_from_words(out_words)
        published = edit.shift_cues(cues, lead)  # captions for the finished file include the intro
        (p / "captions.json").write_text(json.dumps(published, ensure_ascii=False), encoding="utf-8")
        (p / "captions.srt").write_text(edit.to_srt(published), encoding="utf-8")
        (p / "captions.vtt").write_text(edit.to_vtt(published), encoding="utf-8")

        ass_names: list[str] = []
        if opts["captions"] and out_words:
            caption_style = sanitize_settings({"aspect": "landscape", "mode": "line", "animation": "fade",
                                               "fontSize": 24, "position": 86})
            create_ass(clips.lines_from_words(out_words, max_words=7), caption_style, W, H, p / "autoedit.ass")
            ass_names.append("autoedit.ass")
        if plan["callouts"] or plan["lower_thirds"]:
            edit.write_motion_ass(p / "motion.ass", brand, W, H, plan["callouts"], plan["lower_thirds"])
            ass_names.append("motion.ass")
        if rings:
            focus.write_ring_ass(p / "rings.ass", rings, W, H, brand["accent"])
            ass_names.append("rings.ass")
        sfx_path = None
        if plan["sfx"] and brand["audio"]["sfx_volume"] > 0:
            sfx_path = p / "sfx.wav"
            edit.write_sfx_track(sfx_path, plan["sfx"], main_len)
        card = None
        if opts["endcard"] and brand["endcard"]["enabled"]:
            edit.write_endcard_ass(p / "endcard.ass", brand, W, H, brand["endcard"]["seconds"], logo is not None)
            card = "endcard.ass"
        watermark = bool(opts["watermark"] and brand["watermark"]["enabled"] and logo)

        with job_lock:
            jobs[job_id].update(stage="autoedit_render", progress=6)
        child = new_child_job(job_id, project_id, settings, 6, 66 if opts["shorts"] else 80)
        temporary = p / f"render-{child}.mp4"

        def build(codec: str, target: Path, script: str):
            return edit.build_render(
                source, W, H, fps, target, perf.encode_args(codec, settings["renderSpeed"], W, H, profile["threads"]),
                duration=duration, zoom=zoom or None, segments=segments, ass_name=ass_names or None, logo=logo,
                brand=brand, watermark=watermark, loudness=-14.0 if opts["loudness"] else None, endcard_ass=card,
                has_audio=media["has_audio"], script_name=script, intro_ass=intro_card, intro_seconds=intro_secs,
                intro_clip=intro_clip, outro_clip=outro_clip, music=music, sfx_track=sfx_path,
                sfx_volume=brand["audio"]["sfx_volume"], voice_filters=sa.voice_cleanup_filters(opts["voice_cleanup"]),
                broll=[{"path": b["path"], "start": b["start"], "length": b["length"]} for b in broll_plan] or None)

        total_len = encode_graph(child, settings, p, build, temporary)
        temporary.replace(p / "autoedit.mp4")
        finish_child(child)

        with job_lock:
            jobs[job_id].update(stage="autoedit_package", progress=88 if opts["shorts"] else 90)
        yt_chapters = edit.shift_chapters(chapters, lead)
        tags = clips.heuristic_metadata(transcript, title)["tags"]
        package = edit.youtube_package(title, transcript, yt_chapters, tags, brand)
        (p / "youtube.txt").write_text(package["text"], encoding="utf-8")
        (p / "youtube.json").write_text(json.dumps({**package, "chapters": yt_chapters}, ensure_ascii=False), encoding="utf-8")
        social = posts_lib.build_posts(package["title"], transcript, tags, brand, link=brand["endcard"]["url"] or None)
        (p / "posts.txt").write_text(posts_lib.posts_text(social), encoding="utf-8")
        candidates = [source_time_at(main_len * f, segments) for f in (.08, .18, .28, .38, .5, .62, .74, .86)]
        best = edit.pick_thumbnail_time(source, candidates, p)
        frame = p / "thumb_frame.png"
        edit.extract_frame(source, best, frame)
        edit.render_thumbnail(frame, p / "thumbnail.jpg", package["title"], brand, logo)
        frame.unlink(missing_ok=True)

        outputs: dict[str, Any] = {
            "video": file_url(project_id, "autoedit.mp4"), "thumbnail": file_url(project_id, "thumbnail.jpg"),
            "youtube": {**package, "chapters": yt_chapters, "file": file_url(project_id, "youtube.txt")},
            "captions": {"srt": file_url(project_id, "captions.srt"), "vtt": file_url(project_id, "captions.vtt")},
            "seconds": round(total_len, 1), "removed_seconds": round(duration - main_len, 1),
            "zoomed": bool(zoom), "cues": len(cues), "posts": social,
            "extras": {"fillers_removed": len(filler_cuts), "voice_cleanup": opts["voice_cleanup"], "broll": len(broll_plan),
                       "rings": len(rings), "zoom_mode": opts["zoom_mode"] if zoom else "off", "callouts": len(plan["callouts"]), "lower_thirds": len(plan["lower_thirds"]),
                       "sfx": len(plan["sfx"]) if sfx_path else 0, "music": music is not None,
                       "intro_clip": intro_clip is not None, "outro_clip": outro_clip is not None,
                       "intro_card": intro_card is not None}}
        if opts["shorts"]:
            with job_lock:
                jobs[job_id].update(stage="autoedit_shorts", progress=72)
            picks = (read_project(project_id).get("clip_suggestions") or [])[:opts["shorts"]]
            items = [{"start": c["start"], "end": c["end"], "hook": c.get("hook", ""), "title": c.get("title", "Clip"),
                      "description": c.get("description", ""), "tags": c.get("tags", []), "score": c.get("score"),
                      "reasons": c.get("reasons", [])} for c in picks]
            if items:
                polish = {"loudness": opts["loudness"], "watermark": opts["watermark"],
                          "trim_silence": opts["trim_silence"], "min_gap": opts["min_gap"]}
                outputs["shorts"] = render_clips_batch(project_id, job_id, items, short_settings(settings),
                                                       opts["shorts_reframe"], polish, 72, 26)
        with job_lock:
            jobs[job_id].update(status="done", stage="complete", progress=100, outputs=outputs,
                                elapsed_seconds=round(time.monotonic() - started, 2))
    except Exception as exc:
        fail_job(job_id, exc, started)


# ---- Reach: translated captions and hook ideas (both opt-in, both need ANTHROPIC_API_KEY) ------------
class TranslateRequest(BaseModel):
    languages: list[str]


def llm_key_and_model() -> tuple[str, str]:
    return os.environ.get("ANTHROPIC_API_KEY", ""), os.environ.get("SKELLYMOTION_LLM_MODEL", "claude-haiku-5-5")


@app.post("/api/projects/{project_id}/translate")
def start_translate(project_id: str, body: TranslateRequest):
    read_project(project_id)
    p = project_dir(project_id)
    if not (p / "captions.json").is_file():
        raise HTTPException(409, "Run Auto-edit first so there are captions to translate")
    key, model = llm_key_and_model()
    if not key:
        raise HTTPException(409, "Translation needs ANTHROPIC_API_KEY set on this computer")
    languages = [x for x in dict.fromkeys(body.languages) if x in edit.LANGUAGES][:6]
    if not languages:
        raise HTTPException(400, "Choose at least one supported language")
    cues = json.loads((p / "captions.json").read_text(encoding="utf-8"))
    if len(cues) > 3000:
        raise HTTPException(400, "This video has too many captions to translate in one go")
    job_id = register_job(project_id, "translate", sanitize_settings({}))

    def work():
        started = time.monotonic()
        try:
            files = []
            for index, lang in enumerate(languages):
                with job_lock:
                    jobs[job_id].update(stage=f"translating_{edit.LANGUAGES[lang]}", progress=int(100 * index / len(languages)))
                translated = edit.translate_cues(cues, lang, key, model)
                (p / f"captions.{lang}.srt").write_text(edit.to_srt(translated), encoding="utf-8")
                (p / f"captions.{lang}.vtt").write_text(edit.to_vtt(translated), encoding="utf-8")
                files.append({"lang": lang, "language": edit.LANGUAGES[lang],
                              "srt": file_url(project_id, f"captions.{lang}.srt"),
                              "vtt": file_url(project_id, f"captions.{lang}.vtt")})
            with job_lock:
                jobs[job_id].update(status="done", stage="complete", progress=100, outputs={"files": files},
                                    elapsed_seconds=round(time.monotonic() - started, 2))
        except Exception as exc:
            fail_job(job_id, exc, started)

    executor.submit(work)
    return {"job_id": job_id}


class VariantsRequest(BaseModel):
    text: str
    count: int = Field(default=3, ge=2, le=5)


@app.post("/api/projects/{project_id}/clips/variants")
def clip_hook_variants(project_id: str, body: VariantsRequest):
    read_project(project_id)
    key, model = llm_key_and_model()
    if not key:
        raise HTTPException(409, "Hook ideas need ANTHROPIC_API_KEY set on this computer")
    variants = edit.hook_variants(body.text[:1500], key, model, body.count)
    if not variants:
        raise HTTPException(502, "Could not get hook ideas right now. Try again in a moment.")
    return {"variants": variants}


# ---- Hands-off: files in, finished videos out (CLI and watch folder share this) ---------------------
def import_video_file(src: Path, recognition: str = "balanced", language: str = "auto",
                      vocabulary: str = "", performance_mode: str = "balanced", use_ai: bool = False) -> str:
    """Copy a video into a new clip-source project (no HTTP upload). Returns the project id."""
    if src.suffix.lower() not in VIDEO_EXT or not src.is_file():
        raise ValueError(f"Not a supported video file: {src.name}")
    if src.stat().st_size > max_clip_source_bytes():
        raise ValueError(f"{src.name} is larger than the {max_clip_source_bytes() // (1024 * 1024)} MB limit")
    project_id = uuid.uuid4().hex
    p = DATA / project_id
    p.mkdir(parents=True)
    try:
        name = "source" + src.suffix.lower()
        shutil.copy2(src, p / name)
        duration = media_duration(p / name)
        if not 3 < duration <= max_clip_source_seconds():
            raise ValueError("Video length must be between 3 seconds and "
                             f"{round(max_clip_source_seconds() / 60)} minutes")
        save_project(p, {"id": project_id, "kind": "clip_source", "title": src.stem[:100], "audio_file": name,
                         "source_file": name, "duration": duration, "status": "transcribing", "draft_lyrics": "",
                         "original_words": [], "lines": [], "settings": {}, "language": None,
                         "transcription_stage": "queued", "transcription_progress": 0, "save_state": "saved",
                         "use_ai": bool(use_ai), "keep_fillers": True,
                         **recognition_options(recognition, language, vocabulary, performance_mode)})
        return project_id
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


def process_video_file(src: Path, out_root: Path, opts: dict, *, language: str = "auto", recognition: str = "balanced",
                       keep_project: bool = False, log=print) -> Path:
    """Video in, finished package out: edited video, thumbnail, YouTube text, captions and optional Shorts."""
    out_dir = out_root / re.sub(r"[^\w .-]+", "_", src.stem).strip(" .")[:80]
    project_id = import_video_file(src, recognition=recognition, language=language)
    try:
        log(f"Transcribing {src.name}")
        analyze_clip_source(project_id)
        data = read_project(project_id)
        if data.get("status") != "ready":
            raise RuntimeError(data.get("clip_error") or "Could not analyze this video")
        body = AutoEditRequest(**opts)
        settings = sanitize_settings({"aspect": "landscape"})
        job_id = register_job(project_id, "autoedit", settings)
        log("Editing")
        run_autoedit(project_id, job_id, autoedit_options(body), settings)
        job = jobs[job_id]
        if job["status"] != "done":
            raise RuntimeError(job.get("error") or "Editing failed")
        p = project_dir(project_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, target in (("autoedit.mp4", "video.mp4"), ("thumbnail.jpg", "thumbnail.jpg"),
                             ("youtube.txt", "youtube.txt"), ("captions.srt", "captions.srt"),
                             ("captions.vtt", "captions.vtt")):
            shutil.copy2(p / name, out_dir / target)
        shorts = job["outputs"].get("shorts") or []
        if shorts:
            (out_dir / "shorts").mkdir(exist_ok=True)
            for m in shorts:
                shutil.copy2(p / m["file"], out_dir / "shorts" / m["file"])
            shutil.copy2(p / "clips.json", out_dir / "shorts" / "shorts.json")
        log(f"Done: {out_dir}")
        return out_dir
    finally:
        if not keep_project:
            shutil.rmtree(DATA / project_id, ignore_errors=True)


WATCH_POLL_SECONDS, WATCH_STABLE_SECONDS = 5.0, 12.0  # tests shrink these
WATCH: dict[str, Any] = {"thread": None, "stop": threading.Event(), "folder": None, "out": None, "events": [], "busy": None}


def watch_log(message: str) -> None:
    WATCH["events"] = (WATCH["events"] + [{"time": time.time(), "message": message}])[-60:]


def watch_enabled() -> bool:
    return os.environ.get("SKELLYMOTION_WATCH") == "1"


def watch_loop(folder: Path, out_root: Path, opts: dict, language: str, recognition: str) -> None:
    pending: dict[Path, tuple[tuple[int, int], float]] = {}
    while not WATCH["stop"].wait(WATCH_POLL_SECONDS):
        try:
            candidates = [f for f in sorted(folder.iterdir())
                          if f.is_file() and not f.is_symlink() and f.suffix.lower() in VIDEO_EXT and not f.name.startswith(".")]
        except OSError as exc:
            watch_log(f"Cannot read the folder: {exc}")
            continue
        now = time.monotonic()
        for f in candidates:
            if WATCH["stop"].is_set():
                return
            stat = f.stat()
            sig = (stat.st_size, stat.st_mtime_ns)
            if f not in pending or pending[f][0] != sig:
                pending[f] = (sig, now)  # still being copied or recorded
                continue
            if now - pending[f][1] < WATCH_STABLE_SECONDS:
                continue
            WATCH["busy"] = f.name
            try:
                process_video_file(f, out_root, opts, language=language, recognition=recognition, log=watch_log)
                dest = folder / "processed"
            except Exception as exc:
                watch_log(f"Failed: {f.name}: {str(exc)[:200]}")
                dest = folder / "failed"
            finally:
                WATCH["busy"] = None
            dest.mkdir(exist_ok=True)
            target = dest / f.name
            if target.exists():
                target = dest / f"{f.stem}-{int(time.time())}{f.suffix}"
            try:
                f.replace(target)
            except OSError as exc:
                watch_log(f"Could not move {f.name}: {exc}")
            pending.pop(f, None)


class WatchRequest(BaseModel):
    folder: str
    out: str
    options: AutoEditRequest = Field(default_factory=AutoEditRequest)
    language: str = "auto"
    recognition: str = "balanced"


def require_watch() -> None:
    if not watch_enabled():
        raise HTTPException(403, "Watch folders are only available in the desktop app")


@app.get("/api/watch/status")
def watch_status():
    running = bool(WATCH["thread"] and WATCH["thread"].is_alive())
    return {"enabled": watch_enabled(), "running": running, "folder": WATCH["folder"], "out": WATCH["out"],
            "busy": WATCH["busy"], "events": WATCH["events"][-20:]}


@app.post("/api/watch/start")
def watch_start(body: WatchRequest):
    require_watch()
    folder, out = Path(body.folder).expanduser(), Path(body.out).expanduser()
    if not folder.is_dir():
        raise HTTPException(400, "The folder to watch does not exist")
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise HTTPException(400, "Cannot create the output folder")
    folder, out = folder.resolve(), out.resolve()
    if DATA in (folder, out) or DATA in folder.parents or DATA in out.parents:
        raise HTTPException(400, "Choose folders outside the SkellyMotion workspace")
    if WATCH["thread"] and WATCH["thread"].is_alive():
        raise HTTPException(409, "A folder is already being watched. Stop it first.")
    WATCH["stop"] = threading.Event()
    WATCH.update(folder=str(folder), out=str(out), events=[], busy=None)
    opts = body.options.model_dump() if hasattr(body.options, "model_dump") else body.options.dict()
    thread = threading.Thread(target=watch_loop, args=(folder, out, opts, body.language, body.recognition), daemon=True)
    WATCH["thread"] = thread
    thread.start()
    watch_log(f"Watching {folder}")
    return watch_status()


@app.post("/api/watch/stop")
def watch_stop():
    require_watch()
    WATCH["stop"].set()
    watch_log("Stopped")
    return watch_status()


@app.get("/api/clips/capabilities")
def clip_capabilities():
    return {"ai_rerank": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "max_source_mb": max_clip_source_bytes() // (1024 * 1024),
            "max_source_minutes": round(max_clip_source_seconds() / 60),
            "presets": [k for k in AUTOPILOT_PRESETS],
            "ai_text": bool(os.environ.get("ANTHROPIC_API_KEY")), "watch": watch_enabled(),
            "cleanup_levels": list(sa.CLEANUP_LEVELS), "filler_levels": list(sa.FILLER_LEVELS),
            "languages": edit.LANGUAGES}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
