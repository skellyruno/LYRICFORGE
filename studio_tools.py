"""Finishing tools: repurpose a video to vertical/square, GIF previews, thumbnail variants, audio enhance and lower thirds.

Stdlib + FFmpeg (Pillow only for thumbnails). Every function builds arguments or files; the server runs them as jobs.
Graphs are written to a file by the caller (edit.graph_file_args) so long expressions never hit Windows' command-line limit.
"""
from __future__ import annotations

from pathlib import Path

import studio_audio as sa
import studio_clips as clips
import studio_edit as edit

QUIET = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin"]

# ----------------------------------------------------------------------------------------------------- repurpose
FORMATS = {"portrait": ("9x16", "Vertical 9:16"), "square": ("1x1", "Square 1:1")}


def repurpose_name(fmt: str) -> str:
    return f"autoedit_{FORMATS[fmt][0]}.mp4"


REPURPOSE_FITS = ("blur", "fill")


def repurpose_render(src: Path, has_audio: bool, seconds: float, width: int, height: int, target: Path, encode: list[str],
                     script_name: str = "repurpose_graph.txt", fit: str = "blur") -> tuple[list[str], str, float]:
    """The whole picture, fitted inside the new frame, over a darkened, blurred copy of itself that fills it.

    The background is shrunk before it is blurred (a quarter of the size) and scaled back up: the same look for a sixteenth of the work.
    """
    sw, sh = max(2, width // 4), max(2, height // 4)
    if fit == "fill":  # crop the sides instead: no bars, but the edges of the picture are lost
        graph = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height},setsar=1,format=yuv420p[vout]"
    else:
        graph = (f"[0:v]split=2[bgsrc][fgsrc];"
                 f"[bgsrc]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},boxblur=6:2,"
                 f"colorchannelmixer=rr=0.55:gg=0.55:bb=0.55,scale={width}:{height},setsar=1[bg];"
                 f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1[fg];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p,setsar=1[vout]")
    args = [*QUIET, "-progress", "pipe:1", "-y", "-i", str(src), *edit.graph_file_args(script_name), "-map", "[vout]"]
    args += ["-map", "0:a:0", "-c:a", "copy"] if has_audio else ["-an"]
    args += [*encode, "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(target)]
    return args, graph, seconds


# ----------------------------------------------------------------------------------------------------------- GIF
GIF_WIDTHS = (240, 320, 480, 640, 800, 960)
GIF_MAX_SECONDS = 12.0
GIF_MAX_BYTES = 12 * 1024 * 1024  # GitHub READMEs and most chat apps accept a GIF this size


def gif_settings(start, seconds, width, fps, duration: float) -> dict:
    """Clamp everything to values that make a sensible GIF and to the source's own length."""
    start = min(max(0.0, clips._clean_float(start)), max(0.0, duration - 1.0))
    seconds = min(max(1.0, clips._clean_float(seconds, 5.0)), GIF_MAX_SECONDS, max(1.0, duration - start))
    width = min(GIF_WIDTHS, key=lambda w: abs(w - clips._clean_float(width, 480.0)))
    fps = int(min(20, max(6, round(clips._clean_float(fps, 12.0)))))
    return {"start": round(start, 2), "seconds": round(seconds, 2), "width": width, "fps": fps}


def gif_args(src: Path, settings: dict, output: Path) -> list[str]:
    """Two-pass palette GIF in one command: a palette built from this clip's own colors, then dithered against it."""
    vf = (f"fps={settings['fps']},scale={settings['width']}:-2:flags=lanczos,split[a][b];"
          f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    return [*QUIET, "-y", "-ss", f"{settings['start']:.3f}", "-t", f"{settings['seconds']:.3f}", "-i", str(src), "-an", "-vf", vf,
            "-loop", "0", str(output)]


def gif_attempts(settings: dict):
    """The settings to try in turn: as asked, then smaller and slower until the file is small enough to share."""
    yield settings
    width, fps = settings["width"], settings["fps"]
    for _ in range(3):
        smaller = [w for w in GIF_WIDTHS if w < width]
        width = smaller[-1] if smaller else width
        fps = max(6, fps - 3)
        yield {**settings, "width": width, "fps": fps}


# --------------------------------------------------------------------------------------------- thumbnail variants
THUMB_STYLES = ("bold", "split", "center")


def _wrap(draw, text: str, font, max_width: float, max_lines: int) -> list[str]:
    lines, current = [], ""
    for word in text.split():
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines[:max_lines]


def _save_small(image, out_jpg: Path) -> None:
    for quality in (90, 82, 74, 66, 58):
        image.save(out_jpg, "JPEG", quality=quality, optimize=True)
        if out_jpg.stat().st_size <= 1_900_000:
            break


def _paste_logo(image, logo: Path | None, box: tuple[int, int], anchor: str = "right") -> None:
    from PIL import Image
    if not (logo and logo.is_file()):
        return
    with Image.open(logo) as mark:
        mark = mark.convert("RGBA")
        mark.thumbnail(box)
        x = image.width - mark.width - round(image.width * .03) if anchor == "right" else round(image.width * .035)
        y = round(image.height * .05)
        image.paste(mark, (x, y), mark)


def render_thumbnail_variant(style: str, frame_png: Path, out_jpg: Path, title: str, brand: dict, logo: Path | None = None,
                             size: tuple[int, int] = (1280, 720)) -> None:
    """One thumbnail in one of three layouts: bold (title over a shaded frame), split (text panel | picture) or center."""
    from PIL import Image, ImageDraw, ImageOps
    if style == "bold":
        edit.render_thumbnail(frame_png, out_jpg, title, brand, logo, size)
        return
    if style not in THUMB_STYLES:
        raise ValueError("Unknown thumbnail style")
    w, h = size
    text = edit.thumbnail_title(title)
    accent = tuple(int(brand["accent"][i:i + 2], 16) for i in (1, 3, 5))
    panel = tuple(int(brand["bg"][i:i + 2], 16) for i in (1, 3, 5))
    with Image.open(frame_png) as src:
        frame = src.convert("RGB")
    if style == "split":
        split_x = round(w * .46)
        image = Image.new("RGB", size, panel)
        image.paste(ImageOps.fit(frame, (w - split_x, h), Image.LANCZOS), (split_x, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle([split_x - 8, 0, split_x, h], fill=accent)
        font_size = round(h * .13)
        font = edit.find_font(brand["font"], font_size)
        lines = _wrap(draw, text, font, split_x - round(w * .09), 4)
        line_h = round(font_size * 1.1)
        y = (h - len(lines) * line_h) // 2
        for line in lines:
            draw.text((round(w * .04), y), line, font=font, fill=(255, 255, 255))
            y += line_h
        draw.rectangle([round(w * .04), y + 10, round(w * .04) + round(w * .12), y + 22], fill=accent)
        _paste_logo(image, logo, (round(w * .12), round(h * .15)), "left")
    else:  # center
        image = ImageOps.fit(frame, size, Image.LANCZOS)
        image = Image.blend(image, Image.new("RGB", size, (0, 0, 0)), .45)
        draw = ImageDraw.Draw(image)
        font_size = round(h * .16)
        font = edit.find_font(brand["font"], font_size)
        lines = _wrap(draw, text, font, w * .84, 3)
        line_h = round(font_size * 1.1)
        y = (h - len(lines) * line_h) // 2 - round(h * .02)
        for line in lines:
            x = (w - draw.textlength(line, font=font)) / 2
            draw.text((x, y), line, font=font, fill=(255, 255, 255), stroke_width=max(3, font_size // 18), stroke_fill=(0, 0, 0))
            y += line_h
        draw.rectangle([w // 2 - round(w * .09), y + 8, w // 2 + round(w * .09), y + 20], fill=accent)
        _paste_logo(image, logo, (round(w * .11), round(h * .14)), "right")
    _save_small(image, out_jpg)


def thumbnail_times(duration: float, best: float) -> list[float]:
    """Three different moments: the best-scoring frame plus two others well away from it (and from the very start and end)."""
    last = max(.5, duration - .5)
    picks = [min(max(.2, best), last)]
    for fraction in (.25, .65, .45, .85):
        t = min(max(.2, duration * fraction), last)
        if all(abs(t - p) > max(1.0, duration * .12) for p in picks):
            picks.append(t)
        if len(picks) == 3:
            break
    while len(picks) < 3:  # a very short video: repeat the best frame rather than fail
        picks.append(picks[0])
    return [round(p, 2) for p in picks]


# --------------------------------------------------------------------------------------------------- audio enhance
LOUDNESS_TARGETS = (-14, -16, -23)  # YouTube and streaming, podcasts, broadcast
ENHANCE_LEVELS = ("off", "light", "medium", "strong")


def enhance_filters(level: str, loudness: float | None) -> list[str]:
    chain = sa.voice_cleanup_filters(level)
    if loudness:
        chain.append(f"loudnorm=I={loudness:g}:LRA=11:TP=-1.5")
    return chain + ["aresample=48000"] if chain else []


def enhance_args(src: Path, has_video: bool, level: str, loudness: float | None, output: Path, copy_video: bool = True) -> list[str]:
    """Cleaned and levelled audio. A video keeps its picture untouched (stream copy) unless that cannot be put in an MP4."""
    chain = enhance_filters(level, loudness)
    if not chain:
        raise ValueError("Pick a voice cleanup level or loudness target")
    args = [*QUIET, "-y", "-i", str(src)]
    if has_video:
        args += ["-map", "0:v:0", "-c:v", "copy"] if copy_video else ["-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        args += ["-vn"]
    args += ["-map", "0:a:0", "-af", ",".join(chain), "-c:a", "aac", "-b:a", "192k", "-f", "mp4"]
    if has_video:
        args += ["-movflags", "+faststart"]
    return args + [str(output)]


# --------------------------------------------------------------------------------------------------- lower thirds
LOWER_MAX_APPEARANCES = 6


def lower_third_times(start: float, duration: float, every: float, total: float) -> list[tuple[float, float]]:
    """When the lower third is on screen: once, or again every `every` seconds (up to 6 times) while the video runs."""
    start = max(0.0, clips._clean_float(start, 1.0))
    duration = min(10.0, max(2.0, clips._clean_float(duration, 5.0)))
    every = clips._clean_float(every, 0.0)
    out, t = [], start
    while t + 1.0 <= total and len(out) < LOWER_MAX_APPEARANCES:
        out.append((round(t, 2), round(min(total, t + duration), 2)))
        if every < duration + 2:  # 0 means "just once"; anything shorter would overlap itself
            break
        t += every
    return out


def write_lower_third_ass(path: Path, brand: dict, width: int, height: int, name: str, role: str,
                          times: list[tuple[float, float]]) -> None:
    """A name and title that slide in beside an accent bar and fade out, in the brand font and colors."""
    font = brand["font"]
    nsize, rsize = max(18, round(height * .055)), max(14, round(height * .035))
    pad = round(height * .012)
    styles = (f"Style: Name,{font},{nsize},{edit.ass_color(brand['text'])},{edit.ass_color(brand['text'])},{edit.ass_color(brand['bg'], 0x30)},"
              f"&H00000000,-1,0,0,0,100,100,0,0,3,{pad},0,7,10,10,10,1\n"
              f"Style: Role,{font},{rsize},{edit.ass_color(brand['accent'])},{edit.ass_color(brand['accent'])},{edit.ass_color(brand['bg'], 0x30)},"
              f"&H00000000,-1,0,0,0,100,100,0,0,3,{pad},0,7,10,10,10,1\n")
    header = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n"
              "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
              "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, "
              "Encoding\n" + styles + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lx, ny = round(width * .05), round(height * .76)
    ry = ny + round(nsize * 1.5)
    bar_w, bar_h = max(4, round(width * .006)), round(nsize * 1.5 + rsize * 1.5 + 2 * pad)
    tx, slide = lx + bar_w + round(width * .012), round(width * .18)
    events = ""
    for start, end in times:
        a, b = clips.asstime(start), clips.asstime(end)
        events += (f"Dialogue: 1,{a},{b},Name,,0,0,0,,{{\\an7\\move({lx - slide},{ny - pad},{lx},{ny - pad},0,420)\\fad(0,350)"
                   f"\\bord0\\shad0\\1c{edit.ass_color(brand['accent'])}\\p1}}m 0 0 l {bar_w} 0 l {bar_w} {bar_h} l 0 {bar_h}{{\\p0}}\n")
        events += (f"Dialogue: 2,{a},{b},Name,,0,0,0,,{{\\an7\\move({tx - slide},{ny},{tx},{ny},0,420)\\fad(0,350)}}{edit._ass_text(name)}\n")
        if role:
            events += (f"Dialogue: 2,{a},{b},Role,,0,0,0,,{{\\an7\\move({tx - slide},{ry},{tx},{ry},0,420)\\fad(0,350)}}{edit._ass_text(role)}\n")
    path.write_text(header + events, encoding="utf-8-sig")


def lower_third_render(src: Path, ass_name: str, has_audio: bool, seconds: float, target: Path, encode: list[str],
                       script_name: str = "lower_graph.txt") -> tuple[list[str], str, float]:
    graph = f"[0:v]ass={ass_name},format=yuv420p[vout]"
    args = [*QUIET, "-progress", "pipe:1", "-y", "-i", str(src), *edit.graph_file_args(script_name), "-map", "[vout]"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]  # re-encoded: any source audio fits an MP4
    args += [*encode, "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(target)]
    return args, graph, seconds


# ---------------------------------------------------------------------------------------------------------- speed
SPEED_MIN, SPEED_MAX = .25, 4.0
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def clean_speed(value) -> float:
    return round(min(SPEED_MAX, max(SPEED_MIN, clips._clean_float(value, 1.0))), 3)


def atempo_chain(factor: float) -> list[str]:
    """atempo only accepts 0.5 to 2 per stage, so 4x is two 2x stages and 0.25x is two 0.5x stages. Pitch is preserved."""
    stages = []
    while factor > 2.0 + 1e-9:
        stages.append(2.0)
        factor /= 2.0
    while factor < .5 - 1e-9:
        stages.append(.5)
        factor /= .5
    stages.append(factor)
    return [f"atempo={x:.5f}" for x in stages]


def speed_args(src: Path, has_audio: bool, factor: float, output: Path) -> list[str]:
    factor = clean_speed(factor)
    args = [*QUIET, "-y", "-i", str(src), "-map", "0:v:0", "-vf", f"setpts=PTS/{factor:.5f}"]
    args += ["-map", "0:a:0", "-af", ",".join(atempo_chain(factor)), "-c:a", "aac", "-b:a", "160k"] if has_audio else ["-an"]
    return args + [*X264, "-movflags", "+faststart", str(output)]


# ----------------------------------------------------------------------------------------------------------- trim
def trim_settings(start, end, duration: float) -> dict:
    start = min(max(0.0, clips._clean_float(start)), max(0.0, duration - .5))
    end = clips._clean_float(end, 0.0)
    end = duration if end <= 0 or end > duration else end
    if end - start < .5:
        raise ValueError("The end must be at least half a second after the start")
    return {"start": round(start, 3), "end": round(end, 3), "seconds": round(end - start, 3)}


def trim_args(src: Path, has_audio: bool, settings: dict, output: Path) -> list[str]:
    """Frame-accurate cut (re-encoded, so it never starts on the wrong frame the way a stream copy can)."""
    args = [*QUIET, "-y", "-ss", f"{settings['start']:.3f}", "-i", str(src), "-t", f"{settings['seconds']:.3f}", "-map", "0:v:0"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]
    return args + [*X264, "-movflags", "+faststart", str(output)]


# ---------------------------------------------------------------------------------------------------------- shrink
SHRINK_TARGETS = (8, 25, 50, 100)  # MB: Discord (old and new limits), email-ish, and "just smaller"
SHRINK_MIN_VIDEO_BPS = 120_000


def shrink_plan(target_mb, seconds: float, has_audio: bool, src_height: int, attempt: int = 0) -> dict:
    """Pick a video bitrate and height that should land under the size. Later attempts aim lower to absorb encoder overshoot."""
    target = min(SHRINK_TARGETS, key=lambda t: abs(t - clips._clean_float(target_mb, 25.0)))
    audio = 96_000 if has_audio else 0
    video = target * 1024 * 1024 * 8 * .93 * (.85 ** attempt) / max(1.0, seconds) - audio
    if video < SHRINK_MIN_VIDEO_BPS:
        raise ValueError(f"A {seconds / 60:.0f} minute video cannot fit in {target} MB. Choose a bigger size or trim it first")
    height = 1080 if video >= 2_500_000 else 720 if video >= 1_000_000 else 480 if video >= 400_000 else 360
    return {"target_mb": target, "video_bps": int(video), "audio_bps": audio, "height": min(height, max(2, src_height // 2 * 2))}


def shrink_args(src: Path, has_audio: bool, plan: dict, src_height: int, output: Path) -> list[str]:
    args = [*QUIET, "-y", "-i", str(src), "-map", "0:v:0"]
    if src_height > plan["height"]:
        args += ["-vf", f"scale=-2:{plan['height']}:flags=lanczos"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", f"{plan['audio_bps']}"] if has_audio else ["-an"]
    v = plan["video_bps"]
    return args + ["-c:v", "libx264", "-preset", "veryfast", "-b:v", str(v), "-maxrate", str(round(v * 1.25)), "-bufsize", str(v * 2),
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]


# ------------------------------------------------------------------------------------------------------ contact sheet
def sheet_grid(cols, rows) -> tuple[int, int]:
    return int(min(5, max(2, round(clips._clean_float(cols, 3.0))))), int(min(5, max(2, round(clips._clean_float(rows, 3.0)))))


def sheet_times(duration: float, count: int) -> list[float]:
    """The middle of `count` equal slices, so the first and last frames are never black fade-ins and fade-outs."""
    return [round(duration * (i + .5) / count, 2) for i in range(count)]


def stamp(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def render_contact_sheet(frames: list[tuple[Path, float]], out_jpg: Path, cols: int, title: str, duration: float, brand: dict,
                         cell_w: int = 480) -> tuple[int, int]:
    """A storyboard: every frame in a grid with its time stamp, a title and the total length above it."""
    from PIL import Image, ImageDraw, ImageOps
    rows = -(-len(frames) // cols)
    first = Image.open(frames[0][0])
    cell_h = round(cell_w * first.height / first.width) // 2 * 2
    first.close()
    gap, head = 14, 96
    bg = tuple(int(brand["bg"][i:i + 2], 16) for i in (1, 3, 5))
    accent = tuple(int(brand["accent"][i:i + 2], 16) for i in (1, 3, 5))
    width, height = gap + cols * (cell_w + gap), head + rows * (cell_h + gap)
    sheet = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(sheet)
    big, small = edit.find_font(brand["font"], 40), edit.find_font(brand["font"], 22)
    draw.text((gap + 6, 16), edit._clip_text(title, 60) or "Contact sheet", font=big, fill=(255, 255, 255))
    draw.text((gap + 6, 64), f"{stamp(duration)} · {len(frames)} frames", font=small, fill=accent)
    for n, (png, t) in enumerate(frames):
        x, y = gap + (n % cols) * (cell_w + gap), head + (n // cols) * (cell_h + gap)
        with Image.open(png) as img:
            sheet.paste(ImageOps.fit(img.convert("RGB"), (cell_w, cell_h), Image.LANCZOS), (x, y))
        label = stamp(t)
        box_w = round(draw.textlength(label, font=small)) + 16
        draw.rectangle([x, y + cell_h - 34, x + box_w, y + cell_h], fill=(0, 0, 0))
        draw.text((x + 8, y + cell_h - 31), label, font=small, fill=(255, 255, 255))
    for quality in (90, 82, 74, 66):
        sheet.save(out_jpg, "JPEG", quality=quality, optimize=True)
        if out_jpg.stat().st_size <= 4_000_000:
            break
    return width, height


# --------------------------------------------------------------------------------------------------------- quote card
QUOTE_ASPECTS = {"square": ("Square 1:1", (1080, 1080)), "portrait": ("Portrait 4:5", (1080, 1350)), "landscape": ("Landscape 16:9", (1280, 720))}
QUOTE_MAX_CHARS = 280


def render_quote_card(out_png: Path, quote: str, author: str, aspect: str, brand: dict, logo: Path | None = None) -> tuple[int, int]:
    """A shareable picture of a quote or a tip in the brand colors. The type shrinks until the whole text fits."""
    from PIL import Image, ImageDraw
    quote = edit._clip_text(quote, QUOTE_MAX_CHARS)
    if not quote:
        raise ValueError("Type the quote or tip to show")
    author = edit._clip_text(author, 60)
    w, h = QUOTE_ASPECTS.get(aspect, QUOTE_ASPECTS["square"])[1]
    bg = tuple(int(brand["bg"][i:i + 2], 16) for i in (1, 3, 5))
    accent = tuple(int(brand["accent"][i:i + 2], 16) for i in (1, 3, 5))
    text_color = tuple(int(brand["text"][i:i + 2], 16) for i in (1, 3, 5))
    image = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(image)
    margin = round(w * .1)
    draw.rectangle([0, 0, w, round(h * .018)], fill=accent)
    size = round(h * (.085 if h < w else .062))
    while True:
        font = edit.find_font(brand["font"], size)
        lines = _wrap(draw, quote, font, w - 2 * margin, 40)
        line_h = round(size * 1.28)
        if len(lines) * line_h <= h * .56 or size <= 24:
            break
        size -= 3
    mark_font = edit.find_font(brand["font"], round(h * .22))
    draw.text((margin - 6, round(h * .06)), "\u201c", font=mark_font, fill=accent)
    y = round(h * .30) if len(lines) * line_h < h * .4 else round(h * .24)
    for line in lines:
        draw.text((margin, y), line, font=font, fill=text_color)
        y += line_h
    if author:
        y += round(h * .03)
        draw.rectangle([margin, y, margin + round(w * .08), y + 6], fill=accent)
        draw.text((margin, y + 22), author, font=edit.find_font(brand["font"], max(22, round(size * .6))), fill=accent)
    _paste_logo(image, logo, (round(w * .2), round(h * .1)), "right")
    image.save(out_png, "PNG", optimize=True)
    return w, h


# ---------------------------------------------------------------------------------------------------------- fades
FADE_MAX = 5.0


def fade_settings(fade_in, fade_out, duration: float) -> dict:
    a = min(FADE_MAX, max(0.0, clips._clean_float(fade_in, 0.0)))
    b = min(FADE_MAX, max(0.0, clips._clean_float(fade_out, 0.0)))
    if a <= 0 and b <= 0:
        raise ValueError("Choose a fade in, a fade out, or both")
    if a + b > duration:  # never let the two overlap: shrink them in proportion
        a, b = a * duration / (a + b), b * duration / (a + b)
    return {"fade_in": round(a, 3), "fade_out": round(b, 3), "seconds": duration}


def fade_args(src: Path, has_audio: bool, settings: dict, output: Path) -> list[str]:
    """Fade the picture from black (and the sound up) at the start, and back down at the end."""
    d, a, b = settings["seconds"], settings["fade_in"], settings["fade_out"]
    vf = ([f"fade=t=in:st=0:d={a:.3f}"] if a else []) + ([f"fade=t=out:st={max(0.0, d - b):.3f}:d={b:.3f}"] if b else [])
    af = ([f"afade=t=in:st=0:d={a:.3f}"] if a else []) + ([f"afade=t=out:st={max(0.0, d - b):.3f}:d={b:.3f}"] if b else [])
    args = [*QUIET, "-y", "-i", str(src), "-map", "0:v:0", "-vf", ",".join(vf)]
    args += ["-map", "0:a:0", "-af", ",".join(af), "-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]
    return args + [*X264, "-movflags", "+faststart", str(output)]


# ------------------------------------------------------------------------------------------------------ extract audio
def extract_audio_args(src: Path, output: Path) -> list[str]:
    return [*QUIET, "-y", "-i", str(src), "-vn", "-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", "-f", "mp4", str(output)]


# ---------------------------------------------------------------------------------------------------------- loop
LOOP_MAX_TIMES, LOOP_MAX_SECONDS = 10, 3600.0


def loop_settings(times, duration: float) -> dict:
    times = int(min(LOOP_MAX_TIMES, max(2, round(clips._clean_float(times, 2.0)))))
    if duration * times > LOOP_MAX_SECONDS:
        raise ValueError(f"{times} loops would be over {int(LOOP_MAX_SECONDS // 60)} minutes. Pick fewer loops or use a shorter video")
    return {"times": times, "seconds": round(duration * times, 3)}


def loop_args(src: Path, has_audio: bool, settings: dict, output: Path) -> list[str]:
    args = [*QUIET, "-y", "-stream_loop", str(settings["times"] - 1), "-i", str(src), "-t", f"{settings['seconds']:.3f}", "-map", "0:v:0"]
    args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] if has_audio else ["-an"]
    return args + [*X264, "-movflags", "+faststart", str(output)]


# ------------------------------------------------------------------------------------------------------ swap audio
def swap_audio_args(video: Path, audio: Path, seconds: float, output: Path, copy_video: bool = True) -> list[str]:
    """The video's own sound replaced by another track, cut to the video's length. The picture is copied when it can be."""
    args = [*QUIET, "-y", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0"]
    args += ["-c:v", "copy"] if copy_video else X264
    return args + ["-c:a", "aac", "-b:a", "192k", "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(output)]
