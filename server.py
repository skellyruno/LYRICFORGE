"""SkellyMotion: local-first lyric video editor and renderer."""
from __future__ import annotations

import difflib
import base64
import secrets
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

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageFilter

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
model_lock = threading.Lock()
_model: Any = None
jobs: dict[str, dict[str, Any]] = {}
job_lock = threading.Lock()
app = FastAPI(title="SkellyMotion", version="0.3.0")


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


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
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
            _model = WhisperModel(name, device=device, compute_type=compute)
    return _model


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
                aligned[new_i] = {"text": new_text[new_i], "start": float(old["start"]), "end": float(old["end"])}
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
        final_words.append({"text": item["text"], "start": round(s, 3), "end": round(e, 3)})
    lines = []
    offset = 0
    for raw in raw_lines:
        group = final_words[offset:offset + len(raw)]
        lines.append(line_from_words(group))
        offset += len(raw)
    return lines


def transcribe_project(project_id: str) -> None:
    p = DATA / project_id
    d = json.loads((p / "project.json").read_text(encoding="utf-8"))
    try:
        model = load_model()
        segs, info = model.transcribe(str(p / d["audio_file"]), word_timestamps=True,
            beam_size=5, vad_filter=False, condition_on_previous_text=False)
        words = []
        for seg in segs:
            for w in seg.words or []:
                word = w.word.strip()
                if word:
                    words.append({"text": word, "start": round(float(w.start), 3),
                                  "end": round(float(w.end), 3)})
        d = json.loads((p / "project.json").read_text(encoding="utf-8"))
        d["original_words"] = words
        d["draft_lyrics"] = "\n".join(ln["text"] for ln in build_lines(words))
        d["status"] = "review"
        d["language"] = info.language
    except Exception as exc:
        d = json.loads((p / "project.json").read_text(encoding="utf-8"))
        d["status"] = "review"
        d["transcription_error"] = str(exc)[:600]
        d["draft_lyrics"] = ""
    save_project(p, d)


class ConfirmRequest(BaseModel):
    lyrics: str = Field(min_length=1, max_length=30000)


class SaveRequest(BaseModel):
    lines: list[dict]
    settings: dict


class RenderRequest(BaseModel):
    settings: dict
    lines: list[dict]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...)):
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
                "draft_lyrics": "", "original_words": [], "lines": [], "settings": {}, "language": None}
        save_project(p, data)
        executor.submit(transcribe_project, project_id)
        return {"id": project_id, "duration": duration, "status": "transcribing"}
    except Exception:
        shutil.rmtree(p, ignore_errors=True)
        raise


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return read_project(project_id)


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
    cmd = ["ffmpeg", "-v", "error", "-i", str(p / d["audio_file"]),
           "-vn", "-ac", "1", "-ar", "1000", "-f", "f32le", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120)
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
    save_project(project_dir(project_id), d)
    return {"saved": True}


@app.post("/api/projects/{project_id}/background")
async def upload_background(project_id: str, file: UploadFile = File(...)):
    p = project_dir(project_id)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in BG_EXT:
        raise HTTPException(400, "Background must be JPG, PNG, WebP, MP4, MOV or WebM")
    dest = p / ("background" + ext)
    await save_upload(file, dest)
    # Probe whether it is actually an image/video, not only a renamed arbitrary file.
    try:
        probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width", "-of", "csv=p=0", str(dest)])
        if not probe.stdout.strip().isdigit():
            raise RuntimeError("No readable video or image stream")
    except Exception:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "Cannot read background file")
    d = read_project(project_id)
    if d.get("background_file") and d["background_file"] != dest.name:
        (p / d["background_file"]).unlink(missing_ok=True)
    d["background_file"] = dest.name
    save_project(p, d)
    return {"background_url": f"/api/projects/{project_id}/background", "name": dest.name}


@app.get("/api/projects/{project_id}/background")
def get_background(project_id: str):
    d = read_project(project_id)
    if not d.get("background_file"):
        raise HTTPException(404, "No custom background")
    return FileResponse(project_dir(project_id) / d["background_file"])


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
        "resolution": "1080p" if d.get("resolution") == "1080p" else "720p",
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
        cleaned.append({"id": str(row.get("id", uuid.uuid4().hex[:10]))[:20], "text": text,
                        "start": start, "end": end, "words": good_words})
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


def animation_tags(name: str, W: int, H: int, y: int) -> str:
    if name == "fade":
        return r"\fad(180,180)"
    if name == "pop":
        return r"\fscx80\fscy80\t(0,160,\fscx100\fscy100)\fad(65,120)"
    if name == "slide":
        return rf"\move({W//2},{y + 65},{W//2},{y},0,200)\fad(100,150)"
    if name == "zoom":
        return r"\fscx125\fscy125\t(0,300,\fscx100\fscy100)\fad(90,130)"
    if name == "bounce":
        return r"\fscx65\fscy65\t(0,110,\fscx115\fscy115)\t(110,260,\fscx100\fscy100)\fad(40,100)"
    if name == "blur":
        return r"\blur6\t(0,280,\blur0.5)\fad(170,140)"
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
        base = rf"\an5\pos({W//2},{y})"
        tags = base + animation_tags(s["animation"], W, H, y)
        if s["mode"] == "word" and line["words"]:
            for word in line["words"]:
                wtext = word["text"].upper() if s["upper"] else word["text"]
                output.append(ass_event(word["start"], word["end"], tags, wtext))
        elif s["mode"] == "karaoke" and line["words"]:
            # Karaoke secondary = inactive; primary = active; word durations track timestamps.
            # For gaps, hold previous highlight until the next word.
            spans = []
            cursor = start
            for word in line["words"]:
                gap_cs = max(0, round((word["start"] - cursor) * 100))
                duration_cs = max(1, round((word["end"] - word["start"]) * 100))
                spans.append(r"{\k" + str(gap_cs + duration_cs) + "}" + ass_escape(word["text"].upper() if s["upper"] else word["text"]))
                cursor = word["end"]
            # ASS tags are already encoded, so do not escape karaoke markup.
            output.append(f"Dialogue: 0,{asstime(start)},{asstime(end)},Main,,0,0,0,,{{{base}\\1c{accent}\\2c{main}{animation_tags(s['animation'], W, H, y)}}}" + " ".join(spans) + "\n")
        elif s["animation"] == "typewriter":
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
    top, bottom, glow = [rgb(h) for h in PRESETS[name]]
    w, h = 720, 1280
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / (h - 1)
        for x in range(w):
            radial = max(0.0, 1 - math.sqrt(((x-w*.48)/(w*.75))**2 + ((y-h*.32)/(h*.58))**2))
            a = min(1, radial * .42)
            px[x,y] = tuple(int((top[k]*(1-t) + bottom[k]*t)*(1-a) + glow[k]*a) for k in range(3))
    img.save(target)


def render_project(project_id: str, job_id: str, settings: dict, lines: list[dict]):
    p = project_dir(project_id)
    try:
        d = read_project(project_id)
        w, h = SIZES[settings["aspect"]]
        if settings["resolution"] == "1080p":
            w, h = round(w * 1.5), round(h * 1.5)
        ass_file = p / "captions.ass"
        create_ass(lines, settings, w, h, ass_file)
        bg_file = None
        use_bg_video = False
        if settings["background"] == "custom" and d.get("background_file"):
            bg_file = p / d["background_file"]
            use_bg_video = bg_file.suffix.lower() in {".mp4", ".mov", ".webm"}
        if bg_file is None:
            bg_file = p / "generated_bg.png"
            create_gradient(settings["background"] if settings["background"] in PRESETS else "midnight", bg_file)
        audio = p / d["audio_file"]
        output = p / "lyric_video.mp4"
        # Relative ASS filter path prevents Windows drive-letter parsing issues.
        filters = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h},setsar=1,format=yuv420p,"
                   f"eq=brightness={-settings['dim'] * .45:.3f},ass=captions.ass[v]")
        background_input = (["-stream_loop", "-1", "-i", str(bg_file)] if use_bg_video
                            else ["-loop", "1", "-framerate", "30", "-i", str(bg_file)])
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *background_input,
                "-i", str(audio), "-filter_complex", filters, "-map", "[v]", "-map", "1:a:0",
                "-t", str(d["duration"]), "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "21", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(output)]
        proc = subprocess.run(args, cwd=p, capture_output=True, text=True, timeout=1800)
        if proc.returncode:
            raise RuntimeError((proc.stderr or "FFmpeg error")[-1600:])
        with job_lock:
            jobs[job_id].update(status="done", download=f"/api/projects/{project_id}/export")
    except Exception as exc:
        with job_lock:
            jobs[job_id].update(status="error", error=str(exc)[:1800])


@app.post("/api/projects/{project_id}/render")
def render(project_id: str, body: RenderRequest):
    d = read_project(project_id)
    settings = sanitize_settings(body.settings)
    lines = validate_lines(body.lines, d["duration"])
    d["settings"] = settings
    d["lines"] = lines
    save_project(project_dir(project_id), d)
    job_id = uuid.uuid4().hex
    with job_lock:
        jobs[job_id] = {"id": job_id, "status": "rendering", "created": time.time()}
    executor.submit(render_project, project_id, job_id, settings, lines)
    return {"job_id": job_id}


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
        for filename in ("lyric_video.mp4", "captions.ass", "generated_bg.png"):
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
                    if path.name == "lyric_video.mp4":
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
