"""Before/after comparison videos and audio-reactive visualizers.

Both are drawn by FFmpeg from the audio itself (showwaves / showfreqs), in the brand colors, so there is no
footage to record. A/B demos match the loudness of the two files first, because the louder one always sounds
"better" and an unfair comparison is the fastest way to lose a viewer's trust.
"""
from __future__ import annotations

import re
from pathlib import Path

import studio_clips as clips
import studio_edit as edit

ASPECTS = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
STYLES = ("bars", "wave", "both")
MUTED = "0xA3ADA8"  # the "before" waveform: deliberately dull next to the accent-colored "after"


def output_size(aspect: str, resolution: str) -> tuple[int, int]:
    w, h = ASPECTS.get(aspect, ASPECTS["landscape"])
    scale = 2 / 3 if resolution == "720p" else 1.0
    return round(w * scale / 2) * 2, round(h * scale / 2) * 2


def clean_label(text: str, default: str) -> str:
    out = re.sub(r"[^\w .&'+-]+", "", str(text or "")).strip()[:14]
    return out.upper() or default


# --------------------------------------------------------------------------- planning
def ab_segments(mode: str, start: float, step: float, rounds: int) -> list[dict]:
    """The play order. "repeat": the same moment, before then after, each round. "toggle": one continuous stretch
    of music whose source switches every `step` seconds, so you hear the change happen live."""
    segs: list[dict] = []
    for r in range(rounds):
        for k, label in enumerate(("A", "B")):
            s = start if mode == "repeat" else start + (r * 2 + k) * step
            segs.append({"label": label, "start": round(s, 3), "end": round(s + step, 3)})
    return segs


def excerpt_length(mode: str, step: float, rounds: int) -> float:
    return step if mode == "repeat" else step * rounds * 2


def pick_excerpt(envelope: list[float], duration: float, length: float) -> float:
    """Start time of the liveliest stretch of `length` seconds (skipping the first and last 5 percent)."""
    if not envelope or duration <= length + .5:
        return 0.0
    n = len(envelope)
    span = max(1, round(length / duration * n))
    lo, hi = int(n * .05), max(int(n * .05) + 1, int(n * .95) - span)
    best, best_score = lo, -1.0
    for i in range(lo, hi + 1):
        score = sum(envelope[i:i + span])
        if score > best_score:
            best, best_score = i, score
    return round(min(best / n * duration, duration - length - .1), 2)


# ------------------------------------------------------------------------- A/B video
def write_ab_ass(path: Path, brand: dict, width: int, height: int, segments: list[dict], step: float,
                 labels: tuple[str, str], title: str, matched: bool) -> None:
    font, big, small = brand["font"], round(height * .11), round(height * .036)
    styles = (f"Style: Label,{font},{big},{edit.ass_color(brand['text'])},{edit.ass_color(brand['text'])},&H00000000,"
              f"&H00000000,-1,0,0,0,100,100,2,0,1,0,0,5,10,10,10,1\n"
              f"Style: Note,{font},{small},{edit.ass_color(brand['text'], 0x55)},{edit.ass_color(brand['text'], 0x55)},"
              f"&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,0,0,5,10,10,10,1\n")
    header = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n[V4+ Styles]\n"
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
              "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
              "MarginR, MarginV, Encoding\n" + styles + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
              "MarginR, MarginV, Effect, Text\n")
    events = ""
    cx, ly = width // 2, round(height * .2)
    for k, seg in enumerate(segments):
        text = edit._ass_text(labels[0] if seg["label"] == "A" else labels[1])
        color = edit.ass_color(brand["text"], 0x40) if seg["label"] == "A" else edit.ass_color(brand["accent"])
        start, end = k * step, (k + 1) * step
        events += (f"Dialogue: 1,{clips.asstime(start)},{clips.asstime(end)},Label,,0,0,0,,"
                   f"{{\\an5\\pos({cx},{ly})\\c{color}\\fad(60,60)\\fscx92\\fscy92\\t(0,160,\\fscx100\\fscy100)}}{text}\n")
    note = " | ".join(x for x in (edit._clip_text(title, 60), "volume matched" if matched else "") if x)
    if note:
        total = len(segments) * step
        events += (f"Dialogue: 1,{clips.asstime(0)},{clips.asstime(total)},Note,,0,0,0,,"
                   f"{{\\an5\\pos({cx},{round(height * .9)})}}{edit._ass_text(note)}\n")
    path.write_text(header + events, encoding="utf-8-sig")


def build_ab_render(before: Path, after: Path, out_w: int, out_h: int, fps: int, output: Path, encode: list[str], *,
                    segments: list[dict], step: float, brand: dict, ass_name: str, after_gain_db: float = 0.0,
                    viz_gain_db: float = 0.0, script_name: str = "ab_graph.txt") -> tuple[list[str], str, float]:
    """Pass one: the alternating audio and its waveform on the brand background, with BEFORE/AFTER labels."""
    n = len(segments)
    total = n * step
    wave_w = round(out_w * (.84 if out_w >= out_h else .88) / 2) * 2
    wave_h = round(out_h * (.28 if out_w >= out_h else .16) / 2) * 2
    stereo = "aformat=sample_fmts=fltp:channel_layouts=stereo"
    f = max(.004, min(.012, step / 4))
    count = {"A": sum(s["label"] == "A" for s in segments), "B": sum(s["label"] == "B" for s in segments)}
    parts: list[str] = []
    for label, idx in (("A", 0), ("B", 1)):
        if count[label] > 1:
            parts.append(f"[{idx}:a]asplit={count[label]}" + "".join(f"[src{label}{i}]" for i in range(count[label])))
    seen = {"A": 0, "B": 0}
    wave_labels, audio_labels = [], []
    for k, seg in enumerate(segments):
        lab = seg["label"]
        src = f"src{lab}{seen[lab]}" if count[lab] > 1 else f"{0 if lab == 'A' else 1}:a"
        seen[lab] += 1
        gain = f",volume={after_gain_db:.2f}dB" if lab == "B" and abs(after_gain_db) > .05 else ""
        parts.append(f"[{src}]atrim=start={seg['start']:.3f}:end={seg['end']:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:st=0:d={f:.3f},afade=t=out:st={step - f:.3f}:d={f:.3f},aresample=48000,{stereo}{gain}[s{k}]")
        parts.append(f"[s{k}]asplit=2[o{k}][v{k}]")
        color = MUTED if lab == "A" else brand["accent"].replace("#", "0x")
        parts.append(f"[v{k}]volume={viz_gain_db:.2f}dB,showwaves=s={wave_w}x{wave_h}:mode=cline:draw=full:scale=sqrt:rate={fps}:"
                     f"colors={color},format=rgba,colorkey=black:0.12:0.1,setpts=PTS-STARTPTS[w{k}]")
        wave_labels.append(f"[w{k}]")
        audio_labels.append(f"[o{k}]")
    parts.append("".join(wave_labels) + f"concat=n={n}:v=1:a=0[wall]")
    parts.append("".join(audio_labels) + f"concat=n={n}:v=0:a=1[aout]")
    parts.append(f"[2:v][wall]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2:shortest=1,format=yuv420p,ass={ass_name}[vout]")
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin", "-progress", "pipe:1", "-y",
            "-i", str(before), "-i", str(after), "-f", "lavfi", "-i",
            f"color=c={brand['bg'].replace('#', '0x')}:s={out_w}x{out_h}:r={fps}:d={total:.3f}",
            *edit.graph_file_args(script_name), "-map", "[vout]", "-map", "[aout]", "-r", str(fps), *encode,
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    return args, ";".join(parts), total


# --------------------------------------------------------------------------- visualizer
def build_visualizer_render(audio: Path, out_w: int, out_h: int, fps: int, output: Path, encode: list[str], *,
                            duration: float, style: str, brand: dict, viz_gain_db: float = 0.0, with_audio: bool = True,
                            ass_name: str | None = None, logo: Path | None = None, watermark: bool = False,
                            script_name: str = "viz_graph.txt") -> tuple[list[str], str, float]:
    """A finished audio-reactive video (or, with with_audio=False, a picture-only background for lyric videos)."""
    style = style if style in STYLES else "bars"
    accent = brand["accent"].replace("#", "0x")
    key = "format=rgba,colorkey=black:0.12:0.1"
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin", "-progress", "pipe:1", "-y",
            "-i", str(audio), "-f", "lavfi", "-i", f"color=c={brand['bg'].replace('#', '0x')}:s={out_w}x{out_h}:r={fps}:d={duration:.3f}"]
    wm_i = None
    if watermark and logo:
        args += ["-loop", "1", "-framerate", str(fps), "-i", str(logo)]
        wm_i = 2
    drawers = {"bars": 1, "wave": 1, "both": 2}[style]
    outs = ["vizA", "vizB"][:drawers] + (["aout"] if with_audio else [])
    parts = [f"[0:a]aresample=48000,asplit={len(outs)}" + "".join(f"[{o}]" for o in outs)]
    bar_h, margin = round(out_h * (.34 if style == "bars" else .26) / 2) * 2, round(out_h * .06)
    layers: list[tuple[str, str]] = []  # (label, overlay position)
    if style in ("bars", "both"):
        parts.append(f"[vizA]volume={viz_gain_db:.2f}dB,showfreqs=s={round(out_w * .9 / 2) * 2}x{bar_h}:mode=bar:ascale=sqrt:"
                     f"fscale=log:win_size=4096:rate={fps}:colors={accent},{key}[bars]")
        layers.append(("bars", f"(main_w-overlay_w)/2:main_h-overlay_h-{margin}"))
    if style in ("wave", "both"):
        src = "vizB" if style == "both" else "vizA"
        color = "0xFFFFFF" if style == "both" else accent
        wh = round(out_h * (.22 if style == "both" else .3) / 2) * 2
        parts.append(f"[{src}]volume={viz_gain_db:.2f}dB,showwaves=s={round(out_w * .9 / 2) * 2}x{wh}:mode=cline:draw=full:scale=sqrt:"
                     f"rate={fps}:colors={color},{key}[wave]")
        layers.append(("wave", "(main_w-overlay_w)/2:(main_h-overlay_h)/2-" + str(round(out_h * .1) if style == "both" else 0)))
    cur = "1:v"
    for i, (label, pos) in enumerate(layers):
        parts.append(f"[{cur}][{label}]overlay={pos}:shortest=1[l{i}]")
        cur = f"l{i}"
    if wm_i is not None:
        wm = brand["watermark"]
        lw = max(16, round(out_w * wm["size"] / 100))
        parts.append(f"[{wm_i}:v]format=rgba,scale={lw}:-1,colorchannelmixer=aa={wm['opacity']}[wm]")
        parts.append(f"[{cur}][wm]overlay={edit.overlay_position(wm['position'], round(out_w * .03))}:shortest=1[lw]")
        cur = "lw"
    tail = f"format=yuv420p" + (f",ass={ass_name}" if ass_name else "")
    parts.append(f"[{cur}]{tail}[vout]")
    args += [*edit.graph_file_args(script_name), "-map", "[vout]"]
    args += ["-map", "[aout]"] if with_audio else ["-an"]
    args += ["-r", str(fps), *encode]
    if with_audio:
        args += ["-c:a", "aac", "-b:a", "192k"]
    args += ["-movflags", "+faststart", str(output)]
    return args, ";".join(parts), duration


def write_title_ass(path: Path, brand: dict, width: int, height: int, title: str, artist: str, seconds: float) -> None:
    """Song title and artist, lower left, fading in."""
    font, big, small = brand["font"], round(height * .052), round(height * .034)
    styles = (f"Style: Title,{font},{big},{edit.ass_color(brand['text'])},{edit.ass_color(brand['text'])},&H00000000,&H00000000,"
              f"-1,0,0,0,100,100,0,0,1,0,0,1,10,10,10,1\n"
              f"Style: Artist,{font},{small},{edit.ass_color(brand['accent'])},{edit.ass_color(brand['accent'])},&H00000000,"
              f"&H00000000,-1,0,0,0,100,100,0,0,1,0,0,1,10,10,10,1\n")
    header = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 2\n\n[V4+ Styles]\n"
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
              "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
              "MarginR, MarginV, Encoding\n" + styles + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
              "MarginR, MarginV, Effect, Text\n")
    x, y = round(width * .05), round(height * .91)
    events = ""
    if title:
        events += (f"Dialogue: 1,{clips.asstime(.3)},{clips.asstime(seconds)},Title,,0,0,0,,"
                   f"{{\\an1\\pos({x},{y - round(height * .045)})\\fad(500,300)}}{edit._ass_text(edit._clip_text(title, 70))}\n")
    if artist:
        events += (f"Dialogue: 1,{clips.asstime(.5)},{clips.asstime(seconds)},Artist,,0,0,0,,"
                   f"{{\\an1\\pos({x},{y})\\fad(500,300)}}{edit._ass_text(edit._clip_text(artist, 60))}\n")
    path.write_text(header + events, encoding="utf-8-sig")
