"""Single-command Make tools that share one upload, validate and run path in the server (POST /api/quick/{id}).

Each tool is a `Quick`: which uploads it takes, `prepare` (validate the form and the probed media, return plain JSON options)
and `build` (turn the options into one FFmpeg command). Nothing here touches the disk except through FFmpeg, so every tool is
testable on its own. Limits and wording are deliberately conservative: a tool says no early rather than failing late."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import studio_clips as clips
from studio_tools import QUIET, X264

FAST = ["-movflags", "+faststart"]
MAX_JOIN, MAX_TOTAL_SECONDS = 6, 3600.0


# ------------------------------------------------------------------------------------------------------------ helpers
def _num(f: dict, name: str, lo: float, hi: float, default: float) -> float:
    return min(hi, max(lo, clips._clean_float(f.get(name), default)))


def _pick(f: dict, name: str, allowed, default: str) -> str:
    value = str(f.get(name, default)).strip()
    return value if value in allowed else default


def _even(n: float) -> int:
    return max(2, int(round(n)) // 2 * 2)


def _hex(value, default: str) -> str:
    """A colour from the form as six hex digits; anything else falls back, so nothing odd reaches an FFmpeg filter string."""
    text = str(value or "").strip().lstrip("#")
    return text.upper() if re.fullmatch(r"[0-9a-fA-F]{6}", text) else default


def _audio(has_audio: bool) -> list[str]:
    return ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]


def _reencode(src: Path, vf: str | None, has_audio: bool, out: Path, af: str | None = None) -> list[str]:
    args = [*QUIET, "-y", "-i", str(src), "-map", "0:v:0"] + (["-vf", vf] if vf else [])
    if has_audio and af:
        args += ["-af", af]
    return args + _audio(has_audio) + [*X264, *FAST, str(out)]


def _needs_audio(info: dict, what: str = "This video") -> None:
    if not info["has_audio"]:
        raise ValueError(f"{what} has no audio")


@dataclass(frozen=True)
class Quick:
    id: str
    title: str
    out: str
    kind: str                                  # what the result is: video, audio or image
    inputs: tuple[tuple[str, str, bool], ...]  # (form field, video | audio | image | videos, required)
    prepare: Callable[[dict, dict], dict]
    build: Callable[[dict, dict, Path, bool], list[str]]
    label: Callable[[dict], str]
    filters: tuple[str, ...] = ()
    fallback: bool = False                     # retry with build(..., safe=True) if the fast command fails
    render: Callable[[dict, dict, Path], None] | None = None  # a tool drawn in Python (Pillow) instead of FFmpeg: render(paths, opts, out)
    brand: bool = False                        # needs the Brand kit colors and font (the server adds them to the options)


# ----------------------------------------------------------------------------------------------------------------- mute
def mute_prepare(f, i):
    _needs_audio(i["video"])
    return {"seconds": i["video"]["duration"]}


def mute_build(p, o, out, safe):
    if safe:
        return _reencode(p["video"], None, False, out)
    return [*QUIET, "-y", "-i", str(p["video"]), "-map", "0:v:0", "-an", "-c:v", "copy", *FAST, str(out)]


# --------------------------------------------------------------------------------------------------------------- rotate
ROTATIONS = {"cw": ("transpose=1", "Rotated right"), "ccw": ("transpose=2", "Rotated left"), "180": ("hflip,vflip", "Turned upside down"),
             "hflip": ("hflip", "Mirrored left to right"), "vflip": ("vflip", "Flipped top to bottom")}


def rotate_prepare(f, i):
    return {"mode": _pick(f, "mode", ROTATIONS, "cw"), "seconds": i["video"]["duration"], "has_audio": i["video"]["has_audio"]}


def rotate_build(p, o, out, safe):
    return _reencode(p["video"], ROTATIONS[o["mode"]][0], o["has_audio"], out)


# --------------------------------------------------------------------------------------------------------------- resize
HEIGHTS = ("360", "480", "720", "1080", "1440")


def resize_prepare(f, i):
    height = int(_pick(f, "height", HEIGHTS, "720"))
    if height >= i["video"]["height"]:
        raise ValueError(f"This video is already {i['video']['height']} px tall: pick a smaller size")
    return {"height": height, "seconds": i["video"]["duration"], "has_audio": i["video"]["has_audio"]}


def resize_build(p, o, out, safe):
    return _reencode(p["video"], f"scale=-2:{o['height']}:flags=lanczos", o["has_audio"], out)


# ----------------------------------------------------------------------------------------------------------- frame rate
FPS_CHOICES = ("24", "25", "30", "50", "60")


def fps_prepare(f, i):
    return {"fps": int(_pick(f, "fps", FPS_CHOICES, "30")), "seconds": i["video"]["duration"], "has_audio": i["video"]["has_audio"]}


def fps_build(p, o, out, safe):
    return _reencode(p["video"], f"fps={o['fps']}", o["has_audio"], out)


# ----------------------------------------------------------------------------------------------------------- reverse
REVERSE_MAX_SECONDS = 20.0  # FFmpeg holds every frame in memory to play them backwards


def reverse_prepare(f, i):
    v = i["video"]
    if v["duration"] > REVERSE_MAX_SECONDS:
        raise ValueError(f"Reverse works on up to {int(REVERSE_MAX_SECONDS)} seconds (it holds every frame in memory). Trim the video first")
    return {"seconds": v["duration"], "has_audio": v["has_audio"], "scale": v["height"] > 720}


def reverse_build(p, o, out, safe):
    vf = ("scale=-2:720:flags=lanczos," if o["scale"] else "") + "reverse"
    return _reencode(p["video"], vf, o["has_audio"], out, af="areverse")


# ------------------------------------------------------------------------------------------------------------ volume
VOLUME_CHOICES = ("-20", "-12", "-6", "6", "12", "20")


def volume_prepare(f, i):
    _needs_audio(i["video"])
    return {"db": int(_pick(f, "db", VOLUME_CHOICES, "6")), "seconds": i["video"]["duration"]}


def volume_build(p, o, out, safe):
    af = f"volume={o['db']}dB" + (",alimiter=limit=0.97" if o["db"] > 0 else "")  # the limiter stops boosted peaks from clipping
    if safe:
        return _reencode(p["video"], None, True, out, af=af)
    return [*QUIET, "-y", "-i", str(p["video"]), "-map", "0:v:0", "-map", "0:a:0", "-af", af, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", *FAST, str(out)]


# ---------------------------------------------------------------------------------------------------------- watermark
CORNERS = {"tl": "x={m}:y={m}", "tr": "x=W-w-{m}:y={m}", "bl": "x={m}:y=H-h-{m}", "br": "x=W-w-{m}:y=H-h-{m}", "center": "x=(W-w)/2:y=(H-h)/2"}


def watermark_prepare(f, i):
    v = i["video"]
    logo = i.get("logo")
    if logo is None:
        raise ValueError("Upload a logo image, or add one in the Brand kit first")
    width = _even(v["width"] * _num(f, "size", 5, 50, 15) / 100)
    return {"corner": _pick(f, "corner", CORNERS, "br"), "width": width, "opacity": round(_num(f, "opacity", 20, 100, 80) / 100, 2),
            "margin": max(4, round(v["width"] * .03)), "seconds": v["duration"], "has_audio": v["has_audio"]}


def watermark_build(p, o, out, safe):
    position = CORNERS[o["corner"]].format(m=o["margin"])
    graph = (f"[1:v]scale={o['width']}:-2,format=rgba,colorchannelmixer=aa={o['opacity']}[wm];"
             f"[0:v][wm]overlay={position}:format=auto,format=yuv420p[v]")
    args = [*QUIET, "-y", "-i", str(p["video"]), "-i", str(p["logo"]), "-filter_complex", graph, "-map", "[v]"]
    return args + _audio(o["has_audio"]) + [*X264, *FAST, str(out)]


# --------------------------------------------------------------------------------------------------------------- crop
SHAPES = {"1:1": (1, 1), "4:5": (4, 5), "9:16": (9, 16), "16:9": (16, 9)}


def crop_prepare(f, i):
    v = i["video"]
    shape = _pick(f, "shape", SHAPES, "1:1")
    rw, rh = SHAPES[shape]
    if abs(v["width"] / v["height"] - rw / rh) < .01:
        raise ValueError(f"This video is already {shape}")
    if v["width"] / v["height"] > rw / rh:      # wider than the target: trim the sides
        h = _even(v["height"])
        w = _even(h * rw / rh)
    else:                                       # taller: trim the top and bottom
        w = _even(v["width"])
        h = _even(w * rh / rw)
    return {"shape": shape, "w": w, "h": h, "seconds": v["duration"], "has_audio": v["has_audio"]}


def crop_build(p, o, out, safe):
    return _reencode(p["video"], f"crop={o['w']}:{o['h']},setsar=1", o["has_audio"], out)


# -------------------------------------------------------------------------------------------------------------- grade
def grade_prepare(f, i):
    b, c, s = (_num(f, k, -50, 50, 0) for k in ("brightness", "contrast", "saturation"))
    if b == c == s == 0:
        raise ValueError("Move at least one slider away from 0")
    return {"brightness": b, "contrast": c, "saturation": s, "seconds": i["video"]["duration"], "has_audio": i["video"]["has_audio"]}


def grade_build(p, o, out, safe):
    eq = f"eq=brightness={o['brightness'] / 250:.4f}:contrast={1 + o['contrast'] / 100:.4f}:saturation={1 + o['saturation'] / 50:.4f}"
    return _reencode(p["video"], eq, o["has_audio"], out)


# ------------------------------------------------------------------------------------------------------------ cleanup
DENOISE = {"off": None, "light": "hqdn3d=2:1.5:3:2.5", "medium": "hqdn3d=4:3:6:4.5", "strong": "hqdn3d=7:5:9:7"}
SHARPEN = {"off": None, "light": "unsharp=5:5:0.4:5:5:0", "medium": "unsharp=5:5:0.8:5:5:0", "strong": "unsharp=5:5:1.3:5:5:0"}


def cleanup_prepare(f, i):
    d, s = _pick(f, "denoise", DENOISE, "light"), _pick(f, "sharpen", SHARPEN, "off")
    if d == s == "off":
        raise ValueError("Choose a denoise or sharpen level")
    return {"denoise": d, "sharpen": s, "seconds": i["video"]["duration"], "has_audio": i["video"]["has_audio"]}


def cleanup_build(p, o, out, safe):
    vf = ",".join(x for x in (DENOISE[o["denoise"]], SHARPEN[o["sharpen"]]) if x)
    return _reencode(p["video"], vf, o["has_audio"], out)


# ----------------------------------------------------------------------------------------------------------- waveform
WAVE_SIZES = {"wide": (1600, 400), "banner": (1600, 200), "square": (1000, 1000)}


def waveform_prepare(f, i):
    a = i["audio"]
    _needs_audio(a, "That file")
    return {"shape": _pick(f, "shape", WAVE_SIZES, "wide"), "bg": _hex(f.get("bg"), "101510"), "fg": _hex(f.get("fg"), "7CE870"), "seconds": a["duration"]}


def waveform_build(p, o, out, safe):
    w, h = WAVE_SIZES[o["shape"]]
    bg, fg = "0x" + o["bg"], "0x" + o["fg"]
    graph = (f"[0:a]aformat=channel_layouts=mono,showwavespic=s={w}x{h}:colors={fg}[w];[1:v][w]overlay=format=auto,format=rgb24[v]")
    return [*QUIET, "-y", "-i", str(p["audio"]), "-f", "lavfi", "-i", f"color=c={bg}:s={w}x{h}", "-filter_complex", graph,
            "-map", "[v]", "-frames:v", "1", str(out)]


# ---------------------------------------------------------------------------------------------------------- image + audio
STILL_SIZES = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (1080, 1080)}


def still_prepare(f, i):
    a = i["audio"]
    _needs_audio(a, "That file")
    if a["duration"] > MAX_TOTAL_SECONDS:
        raise ValueError("The audio is over an hour long. Trim it first")
    return {"shape": _pick(f, "shape", STILL_SIZES, "landscape"), "zoom": _pick(f, "zoom", ("none", "slow"), "slow") == "slow",
            "seconds": a["duration"]}


def still_build(p, o, out, safe):
    w, h = STILL_SIZES[o["shape"]]
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    if o["zoom"]:  # an eased push-in: the picture is drawn at twice the size so the zoom stays smooth
        fit = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=decrease:flags=lanczos,pad={w * 2}:{h * 2}:(ow-iw)/2:(oh-ih)/2:color=black,"
               f"zoompan=z='min(1+0.0004*on,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps=25,setsar=1")
    return [*QUIET, "-y", "-loop", "1", "-framerate", "25", "-i", str(p["image"]), "-i", str(p["audio"]), "-vf", fit + ",format=yuv420p",
            "-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k", "-t", f"{o['seconds']:.3f}", "-r", "25", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", "-tune", "stillimage", *FAST, str(out)]


# ----------------------------------------------------------------------------------------------------- background music
MUSIC_LEVELS = ("-30", "-24", "-18", "-12", "-6")


def music_prepare(f, i):
    music = i["music"]
    _needs_audio(music, "That music file")
    return {"db": int(_pick(f, "db", MUSIC_LEVELS, "-18")), "duck": str(f.get("duck", "1")) not in ("0", "false", "off", ""),
            "speech": bool(i["video"]["has_audio"]), "seconds": i["video"]["duration"]}


def music_build(p, o, out, safe):
    if o["speech"] and o["duck"]:  # the music dips whenever the voice is speaking
        audio = (f"[1:a]volume={o['db']}dB[m];[0:a]asplit=2[s][sc];[m][sc]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=400[md];"
                 f"[s][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]")
    elif o["speech"]:
        audio = f"[1:a]volume={o['db']}dB[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]"
    else:
        audio = "[1:a]volume=-6dB[a]"  # no voice to sit under: the level setting is for under speech, so just play it at a sensible level
    args = [*QUIET, "-y", "-i", str(p["video"]), "-stream_loop", "-1", "-i", str(p["music"]), "-filter_complex", audio, "-map", "0:v:0", "-map", "[a]"]
    args += ["-c:v", "copy"] if not safe else [*X264]
    return args + ["-c:a", "aac", "-b:a", "192k", "-t", f"{o['seconds']:.3f}", *FAST, str(out)]


# ---------------------------------------------------------------------------------------------------------------- join
def join_prepare(f, i):
    videos = i["videos"]
    if not 2 <= len(videos) <= MAX_JOIN:
        raise ValueError(f"Choose 2 to {MAX_JOIN} videos to join")
    total = sum(v["duration"] for v in videos)
    if total > MAX_TOTAL_SECONDS:
        raise ValueError("Together these are over an hour long")
    first = videos[0]
    return {"width": _even(min(first["width"], 1920)), "height": _even(min(first["height"], 1080)), "count": len(videos),
            "audio": [bool(v["has_audio"]) for v in videos], "durations": [v["duration"] for v in videos], "seconds": total}


def join_build(p, o, out, safe):
    w, h, n = o["width"], o["height"], o["count"]
    args, graph, concat, extra = [*QUIET, "-y"], [], [], n
    for path in p["videos"]:
        args += ["-i", str(path)]
    for k in range(n):
        graph.append(f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p[v{k}]")
        if o["audio"][k]:
            graph.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{k}]")
        else:  # a clip with no sound gets silence of its own length so the sound stays in step
            args += ["-f", "lavfi", "-t", f"{o['durations'][k]:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            graph.append(f"[{extra}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{k}]")
            extra += 1
        concat.append(f"[v{k}][a{k}]")
    graph.append("".join(concat) + f"concat=n={n}:v=1:a=1[v][a]")
    return args + ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", *X264, "-c:a", "aac", "-b:a", "192k", *FAST, str(out)]


# --------------------------------------------------------------------------------------------------- picture in picture
PIP_CORNERS = {"br": "x=W-w-{m}:y=H-h-{m}", "bl": "x={m}:y=H-h-{m}", "tr": "x=W-w-{m}:y={m}", "tl": "x={m}:y={m}"}


def pip_prepare(f, i):
    main, small = i["video"], i["overlay"]
    return {"corner": _pick(f, "corner", PIP_CORNERS, "br"), "width": _even(main["width"] * _num(f, "size", 15, 40, 25) / 100),
            "margin": max(6, round(main["width"] * .02)), "seconds": main["duration"], "has_audio": main["has_audio"]}


def pip_build(p, o, out, safe):
    position = PIP_CORNERS[o["corner"]].format(m=o["margin"])
    graph = f"[1:v]scale={o['width']}:-2,setsar=1[p];[0:v][p]overlay={position}:eof_action=pass,format=yuv420p[v]"
    args = [*QUIET, "-y", "-i", str(p["video"]), "-i", str(p["overlay"]), "-filter_complex", graph, "-map", "[v]"]
    return args + _audio(o["has_audio"]) + ["-t", f"{o['seconds']:.3f}", *X264, *FAST, str(out)]


V = (("video", "video", True),)
QUICK: dict[str, Quick] = {q.id: q for q in (
    Quick("mute", "Remove audio", "muted.mp4", "video", V, mute_prepare, mute_build, lambda o: "Video without sound", (), True),
    Quick("rotate", "Rotate / flip", "rotated.mp4", "video", V, rotate_prepare, rotate_build, lambda o: ROTATIONS[o["mode"]][1],
          ("transpose", "hflip", "vflip")),
    Quick("resize", "Resize", "resized.mp4", "video", V, resize_prepare, resize_build, lambda o: f"{o['height']}p video", ("scale",)),
    Quick("fps", "Frame rate", "retimed.mp4", "video", V, fps_prepare, fps_build, lambda o: f"{o['fps']} frames per second", ("fps",)),
    Quick("reverse", "Reverse", "reversed.mp4", "video", V, reverse_prepare, reverse_build, lambda o: "Reversed video", ("reverse", "areverse", "scale")),
    Quick("volume", "Volume", "volume.mp4", "video", V, volume_prepare, volume_build,
          lambda o: f"{o['db']:+d} dB", ("volume", "alimiter"), True),
    Quick("watermark", "Watermark", "watermarked.mp4", "video", (("video", "video", True), ("logo", "image", False)), watermark_prepare,
          watermark_build, lambda o: "Video with watermark", ("scale", "format", "colorchannelmixer", "overlay")),
    Quick("crop", "Crop to shape", "cropped.mp4", "video", V, crop_prepare, crop_build, lambda o: f"Cropped to {o['shape']}", ("crop", "setsar")),
    Quick("grade", "Color", "graded.mp4", "video", V, grade_prepare, grade_build, lambda o: "Color adjusted video", ("eq",)),
    Quick("cleanup", "Clean up picture", "cleaned.mp4", "video", V, cleanup_prepare, cleanup_build, lambda o: "Cleaned-up video",
          ("hqdn3d", "unsharp")),
    Quick("waveform", "Waveform picture", "waveform.png", "image", (("audio", "audio", True),), waveform_prepare, waveform_build,
          lambda o: "Waveform", ("showwavespic", "aformat", "overlay", "color")),
    Quick("still", "Image + audio", "still_video.mp4", "video", (("image", "image", True), ("audio", "audio", True)), still_prepare, still_build,
          lambda o: "Video from a picture and a track", ("scale", "pad", "zoompan", "setsar")),
    Quick("music", "Background music", "music_mix.mp4", "video", (("video", "video", True), ("music", "audio", True)), music_prepare, music_build,
          lambda o: "Video with background music", ("volume", "asplit", "sidechaincompress", "amix", "alimiter"), True),
    Quick("join", "Join videos", "joined.mp4", "video", (("videos", "videos", True),), join_prepare, join_build, lambda o: f"{o['count']} videos joined",
          ("scale", "pad", "setsar", "fps", "format", "aformat", "concat", "anullsrc")),
    Quick("pip", "Picture in picture", "pip.mp4", "video", (("video", "video", True), ("overlay", "video", True)), pip_prepare, pip_build,
          lambda o: "Picture in picture", ("scale", "setsar", "overlay", "format")),
)}
