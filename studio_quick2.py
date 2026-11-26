"""Twenty-five more quick Make tools, on the same shared path as studio_quick.py: nine video tools, ten audio tools and six picture tools.

Video and audio tools build one FFmpeg command. Picture tools set `render` and draw with Pillow (no FFmpeg, so they work on any build).
The same rule applies as before: say no early, with a plain reason, rather than failing late."""
from __future__ import annotations

from pathlib import Path

import studio_clips as clips
import studio_edit as edit
import studio_tools as tools
from studio_quick import (FAST, MAX_JOIN, MAX_TOTAL_SECONDS, QUIET, X264, Quick, _audio, _even, _hex, _needs_audio, _num, _pick, _reencode)

MAX_IMAGES = 10
AUDIO_LIMIT_SECONDS = 1200.0  # reversing (silence trim) holds the audio in memory


def _aout(src: Path, af: str | None, out: Path, pre: tuple = (), post: tuple = ()) -> list[str]:
    """An audio-only result: the picture is dropped and the sound is written as AAC in an .m4a."""
    return [*QUIET, "-y", *pre, "-i", str(src), *post, "-vn", "-map", "0:a:0", *(["-af", af] if af else []), "-c:a", "aac", "-b:a", "192k", "-f", "mp4", str(out)]


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def _brand_colors(brand: dict) -> tuple[tuple, tuple, tuple]:
    return _rgb(brand["bg"]), _rgb(brand["accent"]), _rgb(brand["text"])


V = (("video", "video", True),)
A = (("audio", "audio", True),)


# ======================================================================================================== VIDEO TOOLS
# ---- zoom in
ZOOMS = {"110": 1.1, "125": 1.25, "150": 1.5, "200": 2.0}
ANCHORS = ("center", "tl", "tr", "bl", "br")


def zoom_prepare(f, i):
    v = i["video"]
    z, anchor = ZOOMS[_pick(f, "amount", ZOOMS, "125")], _pick(f, "anchor", ANCHORS, "center")
    w, h = _even(v["width"]), _even(v["height"])
    cw, ch = _even(w / z), _even(h / z)
    x = {"tl": 0, "bl": 0, "tr": w - cw, "br": w - cw}.get(anchor, (w - cw) // 2)
    y = {"tl": 0, "tr": 0, "bl": h - ch, "br": h - ch}.get(anchor, (h - ch) // 2)
    return {"w": w, "h": h, "cw": cw, "ch": ch, "x": x, "y": y, "zoom": z, "seconds": v["duration"], "has_audio": v["has_audio"]}


def zoom_build(p, o, out, safe):
    return _reencode(p["video"], f"crop={o['cw']}:{o['ch']}:{o['x']}:{o['y']},scale={o['w']}:{o['h']}:flags=lanczos,setsar=1", o["has_audio"], out)


# ---- letterbox
SHAPES = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": .8}


def letterbox_prepare(f, i):
    v = i["video"]
    shape = _pick(f, "shape", SHAPES, "16:9")
    r = SHAPES[shape]
    if abs(v["width"] / v["height"] - r) < .01:
        raise ValueError(f"This video is already {shape}")
    if v["width"] / v["height"] > r:
        tw, th = _even(v["width"]), _even(v["width"] / r)
    else:
        th, tw = _even(v["height"]), _even(v["height"] * r)
    return {"shape": shape, "w": tw, "h": th, "color": _hex(f.get("color"), "000000"), "seconds": v["duration"], "has_audio": v["has_audio"]}


def letterbox_build(p, o, out, safe):
    vf = (f"scale={o['w']}:{o['h']}:force_original_aspect_ratio=decrease:flags=lanczos,pad={o['w']}:{o['h']}:(ow-iw)/2:(oh-ih)/2:color=0x{o['color']},setsar=1")
    return _reencode(p["video"], vf, o["has_audio"], out)


# ---- hold the first or last frame
HOLD_MAX = 10.0


def _edit_fps(info):
    """Normalize to a finite CFR before timing filters; FRAME_RATE may be undefined for VFR."""
    return min(120.0, max(1.0, clips._clean_float(info.get("fps"), 30.0) or 30.0))


def hold_prepare(f, i):
    a, b = _num(f, "start", 0, HOLD_MAX, 0), _num(f, "end", 0, HOLD_MAX, 2)
    if a <= 0 and b <= 0:
        raise ValueError("Choose how long to hold the first frame, the last frame, or both")
    v = i["video"]
    return {"start": round(a, 2), "end": round(b, 2), "seconds": v["duration"] + a + b, "has_audio": v["has_audio"], "fps": _edit_fps(v)}


def hold_build(p, o, out, safe):
    fps = o.get("fps", 30.0)
    # Integer frame counts avoid tpad's duration rounding and unbounded pads.
    vf = (f"setpts=PTS-STARTPTS,fps={fps:g},"
          f"tpad=start_mode=clone:start={round(o['start']*fps)}:stop_mode=clone:stop={round(o['end']*fps)}")
    af = (f"adelay={round(o['start'] * 1000)}:all=1," if o["start"] else "") + f"apad=whole_dur={o['seconds']},atrim=duration={o['seconds']}"
    args = _reencode(p["video"], vf, o["has_audio"], out, af=af)
    return [*args[:-1], "-t", str(o["seconds"]), args[-1]]


# ---- cut out a section
def cut_prepare(f, i):
    v = i["video"]
    s, e = _num(f, "start", 0, 1e6, 0), _num(f, "end", 0, 1e6, 0)
    e = min(e, v["duration"])
    if e - s < .3:
        raise ValueError("Choose a start and an end at least 0.3 seconds apart")
    kept = v["duration"] - (e - s)
    if kept < 1:
        raise ValueError("That would leave less than one second of video")
    return {"start": round(s, 3), "end": round(e, 3), "seconds": kept, "has_audio": v["has_audio"], "fps": _edit_fps(v)}


def cut_build(p, o, out, safe):
    fps = o.get("fps", 30.0)
    # Preserve a defined frame clock even when the decoder's FRAME_RATE is NaN.
    gone = f"lt(t,{o['start']})+gte(t,{o['end']})"
    args = _reencode(p["video"], f"setpts=PTS-STARTPTS,fps={fps:g},select='{gone}',setpts=N/({fps:g}*TB)", o["has_audio"], out, af=f"asetpts=PTS-STARTPTS,aselect='{gone}',asetpts=N/SR/TB")
    return [*args[:-1], "-t", str(o["seconds"]), args[-1]]


# ---- look presets
LOOKS = {
    "bw": ("eq=saturation=0", "Black and white"),
    "sepia": ("colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131", "Sepia"),
    "warm": ("colorchannelmixer=rr=1.1:gg=1.0:bb=0.85", "Warm"),
    "cool": ("colorchannelmixer=rr=0.88:gg=1.0:bb=1.12", "Cool"),
    "vivid": ("eq=saturation=1.5:contrast=1.1", "Vivid"),
    "faded": ("eq=contrast=0.85:brightness=0.04:saturation=0.8", "Faded"),
    "vignette": ("vignette=angle=PI/4", "Vignette"),
}


def look_prepare(f, i):
    return {"look": _pick(f, "look", LOOKS, "warm"), "seconds": i["video"]["duration"], "has_audio": i["video"]["has_audio"]}


def look_build(p, o, out, safe):
    return _reencode(p["video"], LOOKS[o["look"]][0], o["has_audio"], out)


# ---- side by side
def side_prepare(f, i):
    a, b = i["video"], i["second"]
    layout = _pick(f, "layout", ("h", "v"), "h")
    seconds = min(a["duration"], b["duration"])
    return {"layout": layout, "w": _even(min(a["width"], 1280)), "h": _even(min(a["height"], 720)), "seconds": seconds, "has_audio": bool(a["has_audio"])}


def side_build(p, o, out, safe):
    if o["layout"] == "h":
        graph = f"[0:v]scale=-2:{o['h']},setsar=1[l];[1:v]scale=-2:{o['h']},setsar=1[r];[l][r]hstack=inputs=2:shortest=1,format=yuv420p[v]"
    else:
        graph = f"[0:v]scale={o['w']}:-2,setsar=1[t];[1:v]scale={o['w']}:-2,setsar=1[b];[t][b]vstack=inputs=2:shortest=1,format=yuv420p[v]"
    args = [*QUIET, "-y", "-i", str(p["video"]), "-i", str(p["second"]), "-filter_complex", graph, "-map", "[v]"]
    return args + _audio(o["has_audio"]) + ["-t", f"{o['seconds']:.3f}", *X264, *FAST, str(out)]


# ---- slideshow
SLIDE_SIZES = {"landscape": (1280, 720), "portrait": (720, 1280), "square": (1080, 1080)}
FADE = .6


def slides_prepare(f, i):
    images = i["images"]
    if not 2 <= len(images) <= 10:
        raise ValueError("Choose 2 to 10 pictures")
    each = _num(f, "each", 2, 8, 4)
    audio = i.get("audio")
    if audio is not None:
        _needs_audio(audio, "That audio file")
    return {"count": len(images), "each": round(each, 2), "shape": _pick(f, "shape", SLIDE_SIZES, "landscape"), "has_track": audio is not None,
            "seconds": len(images) * each}


def slides_build(p, o, out, safe):
    w, h, n, each = *SLIDE_SIZES[o["shape"]], o["count"], o["each"]
    args = [*QUIET, "-y"]
    for path in p["images"]:
        args += ["-loop", "1", "-framerate", "25", "-t", f"{each + FADE:.2f}", "-i", str(path)]
    if o["has_track"]:
        args += ["-i", str(p["audio"])]
    graph = [f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=25,format=yuv420p[s{k}]"
             for k in range(n)]
    last = "s0"
    for k in range(1, n):  # each picture fades into the next one, starting as the previous one reaches its time
        graph.append(f"[{last}][s{k}]xfade=transition=fade:duration={FADE}:offset={k * each:.2f}[x{k}]")
        last = f"x{k}"
    args += ["-filter_complex", ";".join(graph), "-map", f"[{last}]"]
    args += ["-map", f"{n}:a:0", "-c:a", "aac", "-b:a", "192k"] if o["has_track"] else ["-an"]
    return args + ["-t", f"{o['seconds']:.2f}", *X264, *FAST, str(out)]


# ---- text on a video
TEXT_SIZES = {"small": .05, "medium": .075, "large": .11}
TEXT_ALIGN = {"top": 8, "center": 5, "bottom": 2}


def write_text_ass(path: Path, brand: dict, width: int, height: int, text: str, position: str, size: str, start: float, end: float) -> None:
    font, fs = brand["font"], max(14, round(height * TEXT_SIZES[size]))
    pad = round(fs * .25)
    style = (f"Style: T,{font},{fs},{edit.ass_color(brand['text'])},{edit.ass_color(brand['text'])},{edit.ass_color(brand['bg'], 0x30)},&H00000000,-1,0,0,0,100,100,0,0,3,"
             f"{pad},0,{TEXT_ALIGN[position]},{round(width * .06)},{round(width * .06)},{round(height * .07)},1\n")
    header = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n[V4+ Styles]\n"
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
              "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n" + style +
              "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    path.write_text(header + f"Dialogue: 0,{clips.asstime(start)},{clips.asstime(end)},T,,0,0,0,,{{\\fad(250,250)}}{edit._ass_text(text)}\n", encoding="utf-8-sig")


def text_prepare(f, i):
    v = i["video"]
    text = edit._clip_text(f.get("text"), 140)
    if not text:
        raise ValueError("Type the text to show")
    start = min(_num(f, "start", 0, 1e6, 0), max(0.0, v["duration"] - 1))
    length = _num(f, "length", 0, 600, 0)
    end = v["duration"] if length <= 0 else min(v["duration"], start + max(1.0, length))
    return {"text": text, "position": _pick(f, "position", TEXT_ALIGN, "bottom"), "size": _pick(f, "size", TEXT_SIZES, "medium"), "start": round(start, 2),
            "end": round(end, 2), "w": _even(v["width"]), "h": _even(v["height"]), "seconds": v["duration"], "has_audio": v["has_audio"]}


def text_build(p, o, out, safe):
    ass = out.with_name("text_overlay.ass")  # written next to the result; FFmpeg runs in the project folder so the name alone is enough
    write_text_ass(ass, o["brand"], o["w"], o["h"], o["text"], o["position"], o["size"], o["start"], o["end"])
    return _reencode(p["video"], f"ass={ass.name},format=yuv420p", o["has_audio"], out)


# ---- crossfade join
def xfade_prepare(f, i):
    a, b = i["video"], i["second"]
    fade = min(_num(f, "fade", .5, 3, 1), min(a["duration"], b["duration"]) - .5)
    if fade < .3:
        raise ValueError("The videos are too short to crossfade")
    both = bool(a["has_audio"] and b["has_audio"])
    return {"fade": round(fade, 2), "w": _even(min(a["width"], 1920)), "h": _even(min(a["height"], 1080)), "first": a["duration"], "audio": both,
            "seconds": a["duration"] + b["duration"] - fade}


def xfade_build(p, o, out, safe):
    w, h, fade = o["w"], o["h"], o["fade"]
    fit = f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
    graph = f"[0:v]{fit}[a];[1:v]{fit}[b];[a][b]xfade=transition=fade:duration={fade}:offset={o['first'] - fade:.3f}[v]"
    if o["audio"]:
        graph += (";[0:a]aformat=sample_rates=48000:channel_layouts=stereo[x];[1:a]aformat=sample_rates=48000:channel_layouts=stereo[y];"
                  f"[x][y]acrossfade=d={fade}[a]")
    args = [*QUIET, "-y", "-i", str(p["video"]), "-i", str(p["second"]), "-filter_complex", graph, "-map", "[v]"]
    return args + (["-map", "[a]", "-c:a", "aac", "-b:a", "192k"] if o["audio"] else ["-an"]) + [*X264, *FAST, str(out)]


# ======================================================================================================== AUDIO TOOLS
def atrim_prepare(f, i):
    a = i["audio"]
    s = _num(f, "start", 0, 1e6, 0)
    e = _num(f, "end", 0, 1e6, 0)
    e = a["duration"] if e <= 0 or e > a["duration"] else e
    if e - s < .5:
        raise ValueError("The end must be at least half a second after the start")
    return {"start": round(s, 3), "seconds": round(e - s, 3)}


def atrim_build(p, o, out, safe):
    return _aout(p["audio"], None, out, pre=("-ss", f"{o['start']:.3f}"), post=("-t", f"{o['seconds']:.3f}"))


def afade_prepare(f, i):
    a = i["audio"]
    s = tools.fade_settings(f.get("fade_in", 2), f.get("fade_out", 2), a["duration"])
    return {"fade_in": s["fade_in"], "fade_out": s["fade_out"], "seconds": a["duration"]}


def afade_build(p, o, out, safe):
    d, a, b = o["seconds"], o["fade_in"], o["fade_out"]
    af = ",".join(([f"afade=t=in:st=0:d={a}"] if a else []) + ([f"afade=t=out:st={max(0.0, d - b):.3f}:d={b}"] if b else []))
    return _aout(p["audio"], af, out)


SPEEDS = ("0.5", "0.75", "1.25", "1.5", "2")


def aspeed_prepare(f, i):
    factor = float(_pick(f, "factor", SPEEDS, "1.25"))
    return {"factor": factor, "seconds": i["audio"]["duration"] / factor}


def aspeed_build(p, o, out, safe):
    return _aout(p["audio"], ",".join(tools.atempo_chain(o["factor"])), out)


def tone_prepare(f, i):
    bass, treble = _num(f, "bass", -12, 12, 0), _num(f, "treble", -12, 12, 0)
    if bass == 0 and treble == 0:
        raise ValueError("Move the bass or the treble away from 0")
    return {"bass": bass, "treble": treble, "seconds": i["audio"]["duration"]}


def tone_build(p, o, out, safe):
    parts = ([f"bass=g={o['bass']:g}:f=110"] if o["bass"] else []) + ([f"treble=g={o['treble']:g}:f=3500"] if o["treble"] else [])
    return _aout(p["audio"], ",".join(parts + ["alimiter=limit=0.97"]), out)


CHANNELS = {"mono": ("pan=mono|c0=0.5*c0+0.5*c1", "Mono"), "swap": ("pan=stereo|c0=c1|c1=c0", "Left and right swapped")}


def channels_prepare(f, i):
    return {"mode": _pick(f, "mode", CHANNELS, "mono"), "seconds": i["audio"]["duration"]}


def channels_build(p, o, out, safe):
    return _aout(p["audio"], CHANNELS[o["mode"]][0], out)


def ajoin_prepare(f, i):
    tracks = i["audios"]
    if not 2 <= len(tracks) <= MAX_JOIN:
        raise ValueError(f"Choose 2 to {MAX_JOIN} audio files to join")
    for t in tracks:
        _needs_audio(t, "One of the files")
    total = sum(t["duration"] for t in tracks)
    if total > MAX_TOTAL_SECONDS:
        raise ValueError("Together these are over an hour long")
    return {"count": len(tracks), "seconds": total}


def ajoin_build(p, o, out, safe):
    n = o["count"]
    args = [*QUIET, "-y"]
    for path in p["audios"]:
        args += ["-i", str(path)]
    graph = ";".join(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{k}]" for k in range(n))
    graph += ";" + "".join(f"[a{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[a]"
    return args + ["-filter_complex", graph, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-f", "mp4", str(out)]


SILENCE_LEVELS = ("-40", "-50", "-60")


def silence_prepare(f, i):
    a = i["audio"]
    if a["duration"] > AUDIO_LIMIT_SECONDS:
        raise ValueError(f"This works on up to {int(AUDIO_LIMIT_SECONDS // 60)} minutes. Trim it first")
    return {"mode": _pick(f, "mode", ("ends", "pauses"), "ends"), "level": int(_pick(f, "level", SILENCE_LEVELS, "-50")), "seconds": a["duration"]}


def silence_build(p, o, out, safe):
    t = f"{o['level']}dB"
    if o["mode"] == "ends":  # the start, then the end by flipping the sound round and trimming its start
        one = f"silenceremove=start_periods=1:start_threshold={t}:start_silence=0.15"
        af = f"{one},areverse,{one},areverse"
    else:  # every pause longer than a second and a half is cut down
        af = f"silenceremove=stop_periods=-1:stop_duration=1.5:stop_threshold={t}:stop_silence=0.4"
    return _aout(p["audio"], af, out)


def aloop_prepare(f, i):
    times = int(_pick(f, "times", ("2", "3", "5", "10"), "3"))
    total = i["audio"]["duration"] * times
    if total > MAX_TOTAL_SECONDS:
        raise ValueError("That would be over an hour long. Pick fewer repeats")
    return {"times": times, "seconds": total}


def aloop_build(p, o, out, safe):
    return _aout(p["audio"], None, out, pre=("-stream_loop", str(o["times"] - 1)), post=("-t", f"{o['seconds']:.3f}"))


SEMITONES = tuple(str(n) for n in range(-12, 13) if n)


def pitch_prepare(f, i):
    return {"semitones": int(_pick(f, "semitones", SEMITONES, "2")), "seconds": i["audio"]["duration"]}


def pitch_build(p, o, out, safe):
    r = 2 ** (o["semitones"] / 12)  # raise or lower the pitch by resampling, then restore the original speed
    af = f"aresample=48000,asetrate={round(48000 * r)},aresample=48000," + ",".join(tools.atempo_chain(1 / r))
    return _aout(p["audio"], af, out)


ECHOES = {"slap": ("aecho=0.8:0.9:120:0.3", "Slapback echo"), "room": ("aecho=0.8:0.88:60|110:0.4|0.3", "Small room"),
          "hall": ("aecho=0.8:0.9:500|700:0.4|0.3", "Large hall")}


def echo_prepare(f, i):
    return {"style": _pick(f, "style", ECHOES, "room"), "seconds": i["audio"]["duration"]}


def echo_build(p, o, out, safe):
    return _aout(p["audio"], ECHOES[o["style"]][0] + ",alimiter=limit=0.97", out)


# ====================================================================================================== PICTURE TOOLS
def _open(path: Path):
    from PIL import Image
    img = Image.open(path)
    img.load()
    return img.convert("RGBA")


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple):
    from PIL import Image
    w, h = size
    column = Image.new("RGB", (1, h))
    column.putdata([tuple(round(top[c] + (bottom[c] - top[c]) * y / max(1, h - 1)) for c in range(3)) for y in range(h)])
    return column.resize((w, h))


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(round(a[c] + (b[c] - a[c]) * t) for c in range(3))


def collage_prepare(f, i):
    n = len(i["images"])
    if not 2 <= n <= MAX_IMAGES:
        raise ValueError(f"Choose 2 to {MAX_IMAGES} pictures")
    return {"count": n, "gap": int(_pick(f, "gap", ("0", "12", "28"), "12")), "seconds": 0}


COLLAGE_COLS = {2: 2, 3: 3, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 3}


def collage_render(p, o, out):
    from PIL import Image, ImageOps
    n, gap, cell = o["count"], o["gap"], 540
    cols = COLLAGE_COLS[n]
    rows = -(-n // cols)
    bg, accent, _ = _brand_colors(o["brand"])
    sheet = Image.new("RGB", (gap + cols * (cell + gap), gap + rows * (cell + gap)), bg)
    for k, path in enumerate(p["images"]):
        with Image.open(path) as img:
            tile = ImageOps.fit(img.convert("RGB"), (cell, cell), Image.LANCZOS)
        sheet.paste(tile, (gap + (k % cols) * (cell + gap), gap + (k // cols) * (cell + gap)))
    sheet.save(out, "PNG", optimize=True)


RADII = {"0": 0, "2": .02, "4": .04, "7": .07}


def frame_prepare(f, i):
    return {"pad": _num(f, "pad", 3, 20, 8), "radius": _pick(f, "radius", RADII, "4"), "shadow": str(f.get("shadow", "1")) not in ("0", "false", "off", ""), "seconds": 0}


def frame_render(p, o, out):
    """A screenshot in a rounded window on a soft brand-colored background with a shadow: ready for a post or a README."""
    from PIL import Image, ImageDraw, ImageFilter
    shot = _open(p["image"])
    w, h = shot.size
    pad = max(40, round(max(w, h) * o["pad"] / 100))
    bg, accent, _ = _brand_colors(o["brand"])
    canvas = _gradient((w + 2 * pad, h + 2 * pad), _mix(bg, accent, .06), _mix(bg, accent, .32)).convert("RGBA")
    radius = round(min(w, h) * RADII[o["radius"]])
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    if o["shadow"]:
        shade = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(shade).rounded_rectangle([pad, pad + pad // 5, pad + w, pad + pad // 5 + h], radius=radius, fill=150)
        canvas.paste((0, 0, 0, 255), (0, 0), shade.filter(ImageFilter.GaussianBlur(max(6, pad // 3))))
    canvas.paste(shot, (pad, pad), Image.composite(shot.getchannel("A"), Image.new("L", (w, h), 0), mask))
    canvas.convert("RGB").save(out, "PNG", optimize=True)


def palette_prepare(f, i):
    return {"count": int(_pick(f, "count", ("4", "5", "6", "8"), "5")), "seconds": 0}


def palette_render(p, o, out):
    """The main colors of a picture as labelled swatches, most common first, so a brand color can be copied from a logo or a screenshot."""
    from PIL import Image, ImageDraw
    with Image.open(p["image"]) as img:
        small = img.convert("RGB")
        small.thumbnail((200, 200))
    quant = small.quantize(colors=o["count"], method=Image.Quantize.MEDIANCUT)
    raw = quant.getpalette() or []
    found = sorted(quant.getcolors() or [], reverse=True)
    colors = [tuple(raw[idx * 3: idx * 3 + 3]) for _, idx in found][: o["count"]]
    sw = 220
    sheet = Image.new("RGB", (sw * len(colors), sw + 70), (18, 20, 18))
    draw = ImageDraw.Draw(sheet)
    font = edit.find_font(o["brand"]["font"], 28)
    for k, rgb in enumerate(colors):
        draw.rectangle([k * sw, 0, (k + 1) * sw - 1, sw], fill=rgb)
        label = "#%02X%02X%02X" % rgb
        draw.text((k * sw + 16, sw + 18), label, font=font, fill=(235, 235, 235))
    sheet.save(out, "PNG", optimize=True)


def compare_prepare(f, i):
    return {"split": _pick(f, "split", ("vertical", "horizontal"), "vertical"), "before": edit._clip_text(f.get("before"), 20) or "Before",
            "after": edit._clip_text(f.get("after"), 20) or "After", "seconds": 0}


def compare_render(p, o, out):
    """Two pictures as one: half of the first and half of the second with a divider, labelled, for before and after shots."""
    from PIL import Image, ImageDraw, ImageOps
    a, b = _open(p["image"]).convert("RGB"), _open(p["second"]).convert("RGB")
    if a.width > 1600:
        a = a.resize((1600, round(a.height * 1600 / a.width)), Image.LANCZOS)
    b = ImageOps.fit(b, a.size, Image.LANCZOS)
    w, h = a.size
    _, accent, text = _brand_colors(o["brand"])
    merged = a.copy()
    vertical = o["split"] == "vertical"
    merged.paste(b.crop((w // 2, 0, w, h)) if vertical else b.crop((0, h // 2, w, h)), (w // 2, 0) if vertical else (0, h // 2))
    draw = ImageDraw.Draw(merged)
    t = max(4, round(min(w, h) * .006))
    if vertical:
        draw.rectangle([w // 2 - t // 2, 0, w // 2 + t // 2, h], fill=accent)
    else:
        draw.rectangle([0, h // 2 - t // 2, w, h // 2 + t // 2], fill=accent)
    font = edit.find_font(o["brand"]["font"], max(20, round(min(w, h) * .04)))
    pad = round(min(w, h) * .02)
    for label, at in ((o["before"], (pad, pad)), (o["after"], (w - pad - draw.textlength(o["after"], font=font) - 2 * pad, h - pad - font.size - 2 * pad)
                                                  if vertical else (pad, h - pad - font.size - 2 * pad))):
        box = [at[0], at[1], at[0] + draw.textlength(label, font=font) + 2 * pad, at[1] + font.size + 2 * pad]
        draw.rounded_rectangle(box, radius=pad, fill=(0, 0, 0))
        draw.text((box[0] + pad, box[1] + pad // 2), label, font=font, fill=text)
    merged.save(out, "PNG", optimize=True)


def banner_prepare(f, i):
    name = edit._clip_text(f.get("name"), 40)
    if not name:
        raise ValueError("Type the channel name")
    return {"name": name, "tagline": edit._clip_text(f.get("tagline"), 70), "seconds": 0}


def banner_render(p, o, out):
    """YouTube channel art (2560 x 1440). The name sits inside the centre 1546 x 423 area that every device shows."""
    from PIL import Image, ImageDraw
    w, h = 2560, 1440
    bg, accent, text = _brand_colors(o["brand"])
    img = _gradient((w, h), _mix(bg, accent, .05), _mix(bg, accent, .22))
    draw = ImageDraw.Draw(img, "RGBA")
    for k in range(5):  # soft diagonal bands: they stay outside the safe area's text
        x = -300 + k * 700
        draw.polygon([(x, h), (x + 220, h), (x + 220 + 520, 0), (x + 520, 0)], fill=(*accent, 22))
    safe_w, safe_h = 1546, 423
    cx, cy = w // 2, h // 2
    size = 190
    while size > 60:
        font = edit.find_font(o["brand"]["font"], size)
        if draw.textlength(o["name"], font=font) <= safe_w - (330 if p.get("logo") else 40):
            break
        size -= 8
    tag_font = edit.find_font(o["brand"]["font"], max(40, size // 3))
    name_w, tag_h = draw.textlength(o["name"], font=font), (tag_font.size + 24 if o["tagline"] else 0)
    block_h = size + tag_h
    left = cx - name_w / 2
    if p.get("logo"):
        logo = _open(p["logo"])
        logo.thumbnail((260, 260))
        left += (logo.width + 40) / 2
        img.paste(logo, (round(left - logo.width - 40), round(cy - logo.height / 2)), logo)
    top = cy - block_h / 2
    draw.text((left, top), o["name"], font=font, fill=text)
    if o["tagline"]:
        draw.text((left + 6, top + size + 14), o["tagline"], font=tag_font, fill=accent)
    img.save(out, "PNG", optimize=True)


AVATAR_SIZES = ("256", "512", "1024")


def avatar_prepare(f, i):
    return {"size": int(_pick(f, "size", AVATAR_SIZES, "512")), "shape": _pick(f, "shape", ("circle", "rounded"), "circle"), "seconds": 0}


def avatar_render(p, o, out):
    """A square crop from the middle, as a circle or rounded square with a transparent background: for profile pictures and logos."""
    from PIL import Image, ImageDraw, ImageOps
    s = o["size"]
    img = ImageOps.fit(_open(p["image"]), (s, s), Image.LANCZOS)
    mask = Image.new("L", (s * 4, s * 4), 0)  # drawn large and shrunk, so the edge is smooth
    draw = ImageDraw.Draw(mask)
    if o["shape"] == "circle":
        draw.ellipse([0, 0, s * 4 - 1, s * 4 - 1], fill=255)
    else:
        draw.rounded_rectangle([0, 0, s * 4 - 1, s * 4 - 1], radius=s, fill=255)
    img.putalpha(mask.resize((s, s), Image.LANCZOS))
    img.save(out, "PNG", optimize=True)


# ================================================================================================================ registry
def _t(id, title, out, kind, inputs, prepare, build, label, filters=(), **kw):
    return Quick(id, title, out, kind, inputs, prepare, build, label, tuple(filters), **kw)


MORE: dict[str, Quick] = {q.id: q for q in (
    _t("zoom", "Zoom in", "zoomed.mp4", "video", V, zoom_prepare, zoom_build, lambda o: f"Zoomed in {o['zoom']:g}x", ("crop", "scale", "setsar")),
    _t("letterbox", "Add borders", "bordered.mp4", "video", V, letterbox_prepare, letterbox_build, lambda o: f"Fitted into {o['shape']}",
       ("scale", "pad", "setsar")),
    _t("hold", "Hold first / last frame", "held.mp4", "video", V, hold_prepare, hold_build, lambda o: "Video with held frames", ("fps", "setpts", "tpad", "adelay", "apad", "atrim")),
    _t("cut", "Cut out a section", "cut.mp4", "video", V, cut_prepare, cut_build, lambda o: "Video with a section removed",
       ("fps", "select", "setpts", "aselect", "asetpts")),
    _t("look", "Look", "looked.mp4", "video", V, look_prepare, look_build, lambda o: f"{LOOKS[o['look']][1]} look",
       ("eq", "colorchannelmixer", "vignette")),
    _t("side", "Side by side", "side_by_side.mp4", "video", (("video", "video", True), ("second", "video", True)), side_prepare, side_build,
       lambda o: "Videos side by side" if o["layout"] == "h" else "Videos stacked", ("scale", "setsar", "hstack", "vstack", "format")),
    _t("slides", "Slideshow", "slideshow.mp4", "video", (("images", "images", True), ("audio", "audio", False)), slides_prepare, slides_build,
       lambda o: f"Slideshow of {o['count']} pictures", ("scale", "pad", "setsar", "fps", "format", "xfade")),
    _t("text", "Text on video", "text_video.mp4", "video", V, text_prepare, text_build, lambda o: "Video with text", ("ass", "format"), brand=True),
    _t("xfade", "Crossfade join", "crossfade.mp4", "video", (("video", "video", True), ("second", "video", True)), xfade_prepare, xfade_build,
       lambda o: "Videos joined with a crossfade", ("scale", "pad", "setsar", "fps", "format", "xfade", "aformat", "acrossfade")),
    _t("atrim", "Trim audio", "trimmed_audio.m4a", "audio", A, atrim_prepare, atrim_build, lambda o: "Trimmed audio"),
    _t("afade", "Audio fades", "faded_audio.m4a", "audio", A, afade_prepare, afade_build, lambda o: "Audio with fades", ("afade",)),
    _t("aspeed", "Audio speed", "speed_audio.m4a", "audio", A, aspeed_prepare, aspeed_build, lambda o: f"Audio at {o['factor']:g}x", ("atempo",)),
    _t("tone", "Bass and treble", "toned.m4a", "audio", A, tone_prepare, tone_build, lambda o: "Audio with new tone", ("bass", "treble", "alimiter")),
    _t("channels", "Mono / swap sides", "channels.m4a", "audio", A, channels_prepare, channels_build, lambda o: CHANNELS[o["mode"]][1], ("pan",)),
    _t("ajoin", "Join audio", "joined_audio.m4a", "audio", (("audios", "audios", True),), ajoin_prepare, ajoin_build, lambda o: f"{o['count']} audio files joined",
       ("aformat", "concat")),
    _t("silence", "Trim silence", "trimmed_silence.m4a", "audio", A, silence_prepare, silence_build, lambda o: "Audio without the silences",
       ("silenceremove", "areverse")),
    _t("aloop", "Loop audio", "looped_audio.m4a", "audio", A, aloop_prepare, aloop_build, lambda o: f"Audio looped {o['times']} times"),
    _t("pitch", "Pitch shift", "pitch_shift.m4a", "audio", A, pitch_prepare, pitch_build, lambda o: f"Pitch {o['semitones']:+d} semitones",
       ("aresample", "asetrate", "atempo")),
    _t("echo", "Echo", "echo.m4a", "audio", A, echo_prepare, echo_build, lambda o: ECHOES[o["style"]][1], ("aecho", "alimiter")),
    _t("collage", "Collage", "collage.png", "image", (("images", "images", True),), collage_prepare, lambda *a: [], lambda o: f"Collage of {o['count']} pictures",
       render=collage_render, brand=True),
    _t("frame_shot", "Screenshot frame", "framed.png", "image", (("image", "image", True),), frame_prepare, lambda *a: [], lambda o: "Framed screenshot",
       render=frame_render, brand=True),
    _t("palette", "Color palette", "palette.png", "image", (("image", "image", True),), palette_prepare, lambda *a: [], lambda o: "Color palette",
       render=palette_render, brand=True),
    _t("compare", "Before / after picture", "compare.png", "image", (("image", "image", True), ("second", "image", True)), compare_prepare, lambda *a: [],
       lambda o: "Before and after", render=compare_render, brand=True),
    _t("banner", "Channel banner", "banner.png", "image", (), banner_prepare, lambda *a: [], lambda o: "Channel banner (2560 x 1440)", render=banner_render,
       brand=True),
    _t("avatar", "Round avatar", "avatar.png", "image", (("image", "image", True),), avatar_prepare, lambda *a: [], lambda o: f"Avatar {o['size']} px",
       render=avatar_render),
)}
