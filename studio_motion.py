"""Animation templates drawn with subtitle-style vector text: kinetic text and countdowns.

No frames are rendered by hand: each template is an ASS script over the brand background, so a finished clip takes
seconds. Sound effects are the app's own synthesized ones.
"""
from __future__ import annotations

import re
from pathlib import Path

import studio_clips as clips
import studio_edit as edit

STYLES = ("pop", "slide", "typewriter")
WORD_GAP, CHAR_GAP = .28, .045


def parse_words(line: str) -> list[tuple[str, bool]]:
    """Words of a line. *Words in asterisks* are emphasized (drawn in the accent color)."""
    out, emphasis = [], False
    for token in re.findall(r"\*?[^\s*]+\*?|\*", line):
        starts, ends = token.startswith("*"), token.endswith("*") and len(token) > 1
        word = token.strip("*")
        if starts and not ends and not emphasis:
            emphasis = True
        if word:
            out.append((word, emphasis or (starts and ends)))
        if ends and emphasis:
            emphasis = False
    return out


def line_seconds(words: list[tuple[str, bool]], style: str) -> float:
    reveal = len(words) * WORD_GAP if style == "pop" else (sum(len(w) + 1 for w, _ in words) * CHAR_GAP if style == "typewriter" else .45)
    return round(max(1.8, reveal + 1.1), 2)


def _size(words: int, height: int) -> int:
    return round(height * (.10 if words <= 3 else .078 if words <= 7 else .06))


def _header(brand: dict, width: int, height: int, size: int) -> str:
    margin = round(width * .08)
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: Main,{brand['font']},{size},{edit.ass_color(brand['text'])},{edit.ass_color(brand['text'])},"
            f"&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{max(2, size // 22)},{max(1, size // 30)},5,{margin},{margin},10,1\n"
            "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def kinetic_script(lines: list[str], style: str, width: int, height: int, brand: dict) -> tuple[str, float, list[tuple[float, str, float]]]:
    """(ASS text, total seconds, sound effect events) for lines of text animated in the chosen style."""
    style = style if style in STYLES else "pop"
    parsed = [parse_words(l) for l in lines if l.strip()]
    parsed = [p for p in parsed if p][:12]
    if not parsed:
        raise ValueError("Add at least one line of text")
    accent = edit.ass_color(brand["accent"])
    size = _size(max(len(p) for p in parsed), height)
    body, sfx, t = "", [], .3
    for words in parsed:
        dur = line_seconds(words, style)
        cx, cy = width // 2, height // 2
        if style == "pop":
            pieces = []
            for i, (word, hot) in enumerate(words):
                a = round(i * WORD_GAP * 1000)
                color = f"\\1c{accent}" if hot else ""
                pieces.append(f"{{\\alpha&HFF&\\fscx60\\fscy60{color}\\t({a},{a + 1},\\alpha&H00&)\\t({a},{a + 170},\\fscx112\\fscy112)"
                              f"\\t({a + 170},{a + 300},\\fscx100\\fscy100)}}{edit._ass_text(word)}")
            text = f"{{\\an5\\pos({cx},{cy})\\fad(0,250)}}" + " ".join(pieces)
            sfx.append((t, "pop", .7))
        elif style == "slide":
            plain = " ".join((f"{{\\1c{accent}}}{edit._ass_text(w)}{{\\1c{edit.ass_color(brand['text'])}}}" if hot else edit._ass_text(w)) for w, hot in words)
            text = f"{{\\an5\\move({cx},{cy + round(height * .09)},{cx},{cy},0,450)\\fad(250,250)}}" + plain
            sfx.append((t, "swoosh", .7))
        else:
            pieces, k = [], 0
            for w, hot in words:
                for ch in w + " ":
                    a = round(k * CHAR_GAP * 1000)
                    color = f"\\1c{accent}" if hot else ""
                    pieces.append(f"{{\\alpha&HFF&{color}\\t({a},{a + 1},\\alpha&H00&)}}{edit._ass_text(ch) if ch != ' ' else ' '}")
                    k += 1
            text = f"{{\\an5\\pos({cx},{cy})\\fad(0,250)}}" + "".join(pieces)
            sfx.append((t, "pop", .5))
        body += f"Dialogue: 1,{clips.asstime(t)},{clips.asstime(t + dur)},Main,,0,0,0,,{text}\n"
        t += dur
    return _header(brand, width, height, size) + body, round(t + .3, 2), sfx


def countdown_script(count: int, width: int, height: int, brand: dict) -> tuple[str, float, list[tuple[float, str, float]]]:
    """Numbers popping once a second with an expanding ring, then GO!"""
    count = max(2, min(10, int(count)))
    accent = edit.ass_color(brand["accent"])
    size = round(height * .34)
    r = round(height * .16)
    k = round(r * .55)
    circle = (f"m {r} 0 b {r + k} 0 {2 * r} {r - k} {2 * r} {r} b {2 * r} {r + k} {r + k} {2 * r} {r} {2 * r} "
              f"b {r - k} {2 * r} 0 {r + k} 0 {r} b 0 {r - k} {r - k} 0 {r} 0")
    cx, cy = width // 2, height // 2
    body, sfx = "", []
    for i in range(count):
        t0 = i * 1.0 + .2
        body += (f"Dialogue: 2,{clips.asstime(t0)},{clips.asstime(t0 + .95)},Main,,0,0,0,,{{\\an5\\pos({cx},{cy})\\fs{size}\\fscx150\\fscy150"
                 f"\\t(0,220,\\fscx100\\fscy100)\\fad(0,220)}}{count - i}\n")
        body += (f"Dialogue: 1,{clips.asstime(t0)},{clips.asstime(t0 + .9)},Main,,0,0,0,,{{\\an5\\pos({cx},{cy})\\1a&HFF&\\3c{accent}"
                 f"\\bord{max(3, round(height * .008))}\\shad0\\fscx60\\fscy60\\t(0,900,\\fscx260\\fscy260\\3a&HFF&)\\p1}}{circle}{{\\p0}}\n")
        sfx.append((t0, "pop", .6))
    t_go = count * 1.0 + .2
    body += (f"Dialogue: 2,{clips.asstime(t_go)},{clips.asstime(t_go + 1.3)},Main,,0,0,0,,{{\\an5\\pos({cx},{cy})\\fs{round(size * 1.1)}"
             f"\\1c{accent}\\fscx60\\fscy60\\t(0,180,\\fscx118\\fscy118)\\t(180,320,\\fscx100\\fscy100)\\fad(0,300)}}GO!\n")
    sfx.append((t_go, "ding", .8))
    return _header(brand, width, height, size) + body, round(t_go + 1.5, 2), sfx


def build_card_render(ass_name: str, brand: dict, out_w: int, out_h: int, fps: int, seconds: float, output: Path,
                      encode: list[str], sfx_wav: Path | None, script_name: str = "motion_graph.txt") -> tuple[list[str], str, float]:
    """The brand background with an ASS animation on top and the sound effects underneath."""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-nostdin", "-progress", "pipe:1", "-y", "-f", "lavfi", "-i",
            f"color=c={brand['bg'].replace('#', '0x')}:s={out_w}x{out_h}:r={fps}:d={seconds:.3f}"]
    parts = [f"[0:v]format=yuv420p,ass={ass_name}[vout]"]
    if sfx_wav is not None:
        args += ["-i", str(sfx_wav)]
        parts.append("[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")
    args += [*edit.graph_file_args(script_name), "-map", "[vout]"] + (["-map", "[aout]"] if sfx_wav is not None else ["-an"])
    args += ["-r", str(fps), *encode] + (["-c:a", "aac", "-b:a", "192k"] if sfx_wav is not None else [])
    args += ["-t", f"{seconds:.3f}", "-movflags", "+faststart", str(output)]
    return args, ";".join(parts), seconds
