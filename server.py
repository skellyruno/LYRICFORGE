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
}
FONTS = {"Arial", "DejaVu Sans", "Liberation Sans", "Impact", "Georgia", "Courier New"}
ANIMATIONS = {"fade", "pop", "slide", "typewriter", "zoom", "bounce", "blur", "none"}
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
    result = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(path)])
    return float(result.stdout.strip())


async def save_upload(file: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File exceeds 250 MB limit")
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
        duration = media_duration(p / name)
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
        probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width", "-of", "csv=p=0", str(dest)])
        if not probe.stdout.strip().isdigit():
            raise ValueError("Cannot read the selected image or video")
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
        return json.loads(cache.read_text(encoding="utf-8"))
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
        stride = max(1, len(raw) // samples)
        peaks = []
        for i in range(samples):
            chunk = raw[i * stride:(i + 1) * stride]
            peaks.append(max(map(abs, chunk), default=0.0))
        high = sorted(peaks)[round((len(peaks)-1)*.98)] if peaks else 1.0
        high = max(.00001, high)
        result = {"peaks": [round(min(1, (p / high) ** .65), 3) for p in peaks]}
        cache.write_text(json.dumps(result), encoding="utf-8")
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
        probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width", "-of", "csv=p=0", str(dest)])
        if not probe.stdout.strip().isdigit():
            raise RuntimeError("No readable video or image stream")
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
        tags = base + effect
        if mode == "word" and line["words"]:
            for word in line["words"]:
                wtext = word["text"].upper() if s["upper"] else word["text"]
                output.append(ass_event(word["start"], word["end"], tags, wtext))
        elif mode == "karaoke" and line["words"]:
            spans = []
            cursor = start
            for word in line["words"]:
                gap_cs = max(0, round((word["start"] - cursor) * 100))
                duration_cs = max(1, round((word["end"] - word["start"]) * 100))
                spans.append(r"{\k" + str(gap_cs + duration_cs) + "}" +
                             ass_escape(word["text"].upper() if s["upper"] else word["text"]))
                cursor = word["end"]
            output.append(f"Dialogue: 0,{asstime(start)},{asstime(end)},Main,,0,0,0,,"
                          f"{{{base}\\1c{accent}\\2c{main}{effect}}}" + " ".join(spans) + "\n")
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


app.mount("/static", StaticFiles(directory=STATIC), name="static")
