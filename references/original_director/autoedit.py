#!/usr/bin/env python3
"""
autoedit.py - autonomous explainer / plugin-demo video editor.

  voiceover.wav + assets/   ->  words.json   (Whisper, word timestamps)
                            ->  plan.json    (Claude as "director": scene-by-scene edit plan)
                            ->  final.mp4    (Pillow draws the cards/captions, ffmpeg does camera + assembly)

Two looks are built in, modelled on the reference videos:
  --preset doc     documentary essay: b-roll, highlighted screenshots, year stamps, quote/stat cards
  --preset plugin  product walkthrough: plugin UI shots, gold caps titles, diagrams, branded outro

Typical use:
  python autoedit.py make --audio vo.wav --assets ./assets --preset plugin --out final.mp4
  (edit work_vo/plan.json by hand if you like)
  python autoedit.py render --plan work_vo/plan.json --audio vo.wav --assets ./assets --preset plugin --out final.mp4

Requirements: ffmpeg + ffprobe on PATH, `pip install pillow numpy`.
For `make`/`transcribe`: `pip install faster-whisper`.  For `make`/`direct`: `pip install anthropic`
and set ANTHROPIC_API_KEY.  Optional: rsvg-convert (or cairosvg / ImageMagick) for diagram scenes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
CFG = dict(w=1920, h=1080, fps=30, x264_preset="veryfast", crf=18, font=None, font_bold=None)
CACHE_VER = 3        # bump when rendering code changes so cached clips/layers are rebuilt
IMG_Z = 2.0         # stills are prepared at 2x output size so slow zooms stay sharp
VIDEO_MAX_ZOOM = 1.5
IMG_MAX_ZOOM = 2.0
MIN_SCENE = 1.0
VID_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SCENE_TYPES = {"broll", "document", "quote", "big_text", "stat", "ui_demo", "diagram", "outro"}
NEEDS_ASSET = {"document", "ui_demo"}

PRESETS = {
    "doc": dict(
        bg=(18, 18, 20), card_bg=(243, 243, 241), ink=(24, 24, 26), muted=(110, 110, 114),
        text=(255, 255, 255), accent=(37, 99, 235),
        hl_mode="marker", hl_fill=(255, 225, 77), hl_ink=(20, 20, 20),
        caption_size=0.042, title_size=0.072, sub_size=0.042, stamp_size=0.075,
        title_color=(255, 255, 255), title_caps=False, caption_bold=False,
        default_pos=dict(broll="bottom", document="bottom", ui_demo="bottom", diagram="bottom"),
    ),
    "plugin": dict(
        bg=(11, 11, 14), card_bg=(18, 18, 22), ink=(240, 240, 240), muted=(150, 150, 158),
        text=(255, 255, 255), accent=(245, 185, 66),
        hl_mode="color", hl_fill=(245, 185, 66), hl_ink=(11, 11, 14),
        caption_size=0.036, title_size=0.058, sub_size=0.034, stamp_size=0.06,
        title_color=(245, 185, 66), title_caps=True, caption_bold=False,
        default_pos=dict(broll="bottom", document="bottom", ui_demo="top", diagram="bottom"),
    ),
}
POS = {
    "bottom": dict(x0=0.10, x1=0.90, y=0.90, v="bottom", align="center"),
    "bottom_left": dict(x0=0.06, x1=0.62, y=0.90, v="bottom", align="left"),
    "top": dict(x0=0.10, x1=0.90, y=0.06, v="top", align="center"),
    "top_left": dict(x0=0.06, x1=0.62, y=0.07, v="top", align="left"),
    "center": dict(x0=0.15, x1=0.85, y=0.50, v="middle", align="center"),
}


def fw() -> int: return CFG["w"]
def fh() -> int: return CFG["h"]
def fs(frac: float) -> int: return max(10, int(CFG["h"] * frac))


def die(msg: str):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join(r.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"command failed: {' '.join(cmd[:3])} ...\n{tail}")
    return r


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", str(path)])
    j = json.loads(r.stdout)
    st = (j.get("streams") or [{}])[0]
    return dict(w=st.get("width"), h=st.get("height"), dur=float(j["format"].get("duration") or 0))


def audio_duration(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    return float(r.stdout.strip())


# --------------------------------------------------------------------------- fonts & text

def _fc(pattern: str) -> str | None:
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True, timeout=5).stdout.strip()
        return out or None
    except Exception:
        return None


@lru_cache(maxsize=None)
def get_font(size: int, bold: bool) -> ImageFont.FreeTypeFont:
    path = CFG["font_bold"] if bold else CFG["font"]
    path = path or os.environ.get("AUTOEDIT_FONT_BOLD" if bold else "AUTOEDIT_FONT")
    if not path:
        path = _fc("Lato,Inter,DejaVu Sans:bold" if bold else "Lato,Inter,DejaVu Sans")
    try:
        f = ImageFont.truetype(path, size)
    except Exception:
        f = ImageFont.load_default(size)
    if bold:
        try:
            f.set_variation_by_name("Bold")
        except Exception:
            pass
    return f


def tokenize(text: str):
    """'a **b** c.' -> [(token, highlighted, glued_to_previous)]; **...** marks a highlight."""
    out, hl, prev_space = [], False, True
    for part in re.split(r"(\*\*)", text):
        if part == "**":
            hl = not hl
            continue
        if not part:
            continue
        for m in re.finditer(r"\S+", part):
            # only the first token of a part can be glued to the previous part (no space between them)
            glued = m.start() == 0 and not prev_space and bool(out)
            out.append((m.group(), hl, glued))
        prev_space = part[-1].isspace()
    return out


class TextLayout:
    def __init__(self, text: str, font: ImageFont.FreeTypeFont, max_w: float, line_h: float = 1.3, caps: bool = False):
        self.font = font
        self.lines, cur, curw = [], [], 0.0
        space = font.getlength(" ")
        for tok, hl, glued in tokenize(text):
            wd = font.getlength(tok.upper() if caps else tok)
            sp = 0 if (glued or not cur) else space
            if cur and curw + sp + wd > max_w:
                self.lines.append((cur, curw))
                cur, curw, sp = [], 0.0, 0
            x = curw + sp
            cur.append((tok, hl, x, wd))
            curw = x + wd
        if cur:
            self.lines.append((cur, curw))
        self.lh = int(font.size * line_h)
        self.w = max((l[1] for l in self.lines), default=0)
        self.h = self.lh * len(self.lines)

    def draw(self, img: Image.Image, x: float, y: float, *, align="left", fill=(255, 255, 255),
             hl_mode="marker", hl_fill=(255, 225, 77), hl_ink=(20, 20, 20), shadow=False, caps=False):
        asc, _ = self.font.getmetrics()
        size = self.font.size
        if shadow:
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sd = ImageDraw.Draw(sh)
            for li, (line, lw) in enumerate(self.lines):
                ox = x + {"left": 0, "center": (self.w - lw) / 2, "right": self.w - lw}[align]
                base = y + li * self.lh + asc
                for tok, hl, tx, _ in line:
                    sd.text((ox + tx, base + size * 0.05), tok.upper() if caps else tok, font=self.font, fill=(0, 0, 0, 200), anchor="ls")
            sh = sh.filter(ImageFilter.GaussianBlur(max(2, size * 0.09)))
            img.alpha_composite(sh)
        d = ImageDraw.Draw(img)
        for li, (line, lw) in enumerate(self.lines):
            ox = x + {"left": 0, "center": (self.w - lw) / 2, "right": self.w - lw}[align]
            base = y + li * self.lh + asc
            if hl_mode == "marker":
                run_start = None
                for i, (tok, hl, tx, wd) in enumerate(line):
                    if hl and run_start is None:
                        run_start = tx
                    last = i == len(line) - 1 or not line[i + 1][1]
                    if hl and last:
                        pad = size * 0.14
                        d.rounded_rectangle((ox + run_start - pad, base - size * 0.88, ox + tx + wd + pad, base + size * 0.26),
                                            radius=size * 0.08, fill=hl_fill)
                        run_start = None
            for tok, hl, tx, _ in line:
                color = fill
                if hl:
                    color = hl_ink if hl_mode == "marker" else hl_fill
                d.text((ox + tx, base), tok.upper() if caps else tok, font=self.font, fill=color, anchor="ls")


# --------------------------------------------------------------------------- images

def placeholder(w: int, h: int, label: str, P: dict) -> Image.Image:
    y = np.linspace(0, 1, h)[:, None, None]
    top, bot = np.array(P["bg"], float), np.array(P["bg"], float) * 0.55 + 14
    arr = (top * (1 - y) + bot * y) * np.ones((1, w, 1))
    img = Image.fromarray(arr.clip(0, 255).astype("uint8"), "RGB").convert("RGBA")
    d = ImageDraw.Draw(img)
    d.text((w * 0.04, h * 0.94), label, font=get_font(max(14, h // 45), False), fill=(120, 120, 128, 255), anchor="ls")
    return img.convert("RGB")


class Placement:
    """Maps normalised source coords (0..1) -> normalised canvas coords."""
    def __init__(self, sw, sh, bw, bh, mode="contain", anchor=(0.5, 0.5), margin=0.0):
        self.sw, self.sh, self.bw, self.bh = sw, sh, bw, bh
        if mode == "cover":
            self.scale = max(bw / sw, bh / sh)
            self.ox = -(sw * self.scale - bw) * anchor[0]
            self.oy = -(sh * self.scale - bh) * anchor[1]
        else:
            m = margin * bh
            self.scale = min((bw - 2 * m) / sw, (bh - 2 * m) / sh)
            self.ox = (bw - sw * self.scale) / 2
            self.oy = (bh - sh * self.scale) / 2

    def pt(self, xn: float, yn: float):
        return ((xn * self.sw * self.scale + self.ox) / self.bw, (yn * self.sh * self.scale + self.oy) / self.bh)

    def rect(self, r):
        x0, y0 = self.pt(r[0], r[1])
        x1, y1 = self.pt(r[0] + r[2], r[1] + r[3])
        x0, y0, x1, y1 = (min(max(v, 0), 1) for v in (x0, y0, x1, y1))
        return x0, y0, x1, y1


def compose(src: Image.Image, canvas: Image.Image, pl: Placement, shadow=False):
    new = (max(1, round(pl.sw * pl.scale)), max(1, round(pl.sh * pl.scale)))
    res = src.resize(new, Image.LANCZOS)
    pos = (round(pl.ox), round(pl.oy))
    if shadow:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle((pos[0], pos[1] + 14, pos[0] + new[0], pos[1] + new[1] + 14), fill=(0, 0, 0, 110))
        sh = sh.filter(ImageFilter.GaussianBlur(24))
        c = canvas.convert("RGBA")
        c.alpha_composite(sh)
        canvas.paste(c.convert("RGB"))
    if res.mode == "RGBA":
        canvas.paste(res, pos, res)
    else:
        canvas.paste(res, pos)


def apply_marks(src: Image.Image, highlights, redact) -> Image.Image:
    src = src.convert("RGB")
    w, h = src.size

    def box(r):
        x0, y0 = int(max(0, r[0]) * w), int(max(0, r[1]) * h)
        x1, y1 = int(min(1, r[0] + r[2]) * w), int(min(1, r[1] + r[3]) * h)
        return (x0, y0, max(x1, x0 + 1), max(y1, y0 + 1))

    for r in redact or []:
        b = box(r)
        reg = src.crop(b).filter(ImageFilter.GaussianBlur(max(8, (b[3] - b[1]) * 0.5)))
        src.paste(reg, b[:2])
    for r in highlights or []:
        b = box(r)
        reg = src.crop(b)
        src.paste(ImageChops.multiply(reg, Image.new("RGB", reg.size, (255, 226, 77))), b[:2])
    return src


def svg_to_png(svg_path: Path, w: int, h: int, out: Path):
    if shutil.which("rsvg-convert"):
        run(["rsvg-convert", "-w", str(w), "-h", str(h), "--keep-aspect-ratio", str(svg_path), "-o", str(out)])
        return
    try:
        import cairosvg  # type: ignore
        cairosvg.svg2png(url=str(svg_path), write_to=str(out), output_width=w, output_height=h)
        return
    except ImportError:
        pass
    im = shutil.which("magick") or shutil.which("convert")
    if im:
        run([im, "-background", "none", "-density", "192", str(svg_path), "-resize", f"{w}x{h}", str(out)])
        return
    raise RuntimeError("diagram scenes need rsvg-convert, cairosvg or ImageMagick to turn SVG into PNG")


def gradient_layer(bottom=0.0, top=0.0, flat=0.0) -> Image.Image:
    w, h = fw(), fh()
    y = np.linspace(0, 1, h)[:, None]
    a = np.full((h, 1), flat)
    if bottom:
        a = a + np.clip((y - 0.45) / 0.55, 0, 1) ** 1.4 * bottom
    if top:
        a = a + np.clip((0.32 - y) / 0.32, 0, 1) ** 1.4 * top
    arr = np.zeros((h, w, 4), np.uint8)
    arr[..., 3] = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


# --------------------------------------------------------------------------- scene bases

class Ctx:
    def __init__(self, preset: str, assets: Path, work: Path):
        self.name, self.P, self.assets, self.work = preset, PRESETS[preset], assets, work


def find_asset(ctx: Ctx, name):
    if not name:
        return None
    p = Path(name)
    if not p.is_absolute():
        p = ctx.assets / name
    return p if p.exists() else None


def load_visual(ctx: Ctx, name, label=""):
    """-> ('image', PIL.Image) | ('video', Path, info) | ('missing', None)"""
    p = find_asset(ctx, name)
    if p is None:
        return ("missing", None, label or str(name))
    ext = p.suffix.lower()
    if ext in IMG_EXT:
        return ("image", Image.open(p).convert("RGB"), p)
    if ext in VID_EXT:
        return ("video", p, probe(p))
    if ext == ".svg":
        out = ctx.work / "svg" / (p.stem + f"_{fw()}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        svg_to_png(p, int(fw() * 0.9), int(fh() * 0.78), out)
        return ("image", Image.open(out).convert("RGBA"), p)
    return ("missing", None, f"unsupported asset type: {p.name}")


def stage_base(ctx: Ctx, sc: dict):
    """Returns (base, placement, bw, bh). base is a PIL image or ('video', path, start, prefilter)."""
    t = sc["type"]
    P = ctx.P
    W, H = fw(), fh()
    Z = IMG_Z
    if t in ("big_text", "outro", "stat", "quote"):
        return card_base(ctx, sc), None, W, H

    if t == "broll":
        kind, v, info = load_visual(ctx, sc.get("asset"), sc.get("want") or sc.get("asset") or "b-roll placeholder")
        anchor = tuple(sc.get("anchor", (0.5, 0.5)))
        if kind == "video":
            bw, bh = W, H
            pl = Placement(info["w"], info["h"], bw, bh, "cover", anchor)
            return ("video", v, float(sc.get("asset_start", 0)), video_prefilter(pl, bw, bh, "cover", P, sc.get("blur"))), pl, bw, bh
        bw, bh = int(W * Z), int(H * Z)
        if kind == "missing":
            return placeholder(bw, bh, f"[ b-roll wanted ] {info}", P), None, bw, bh
        pl = Placement(v.width, v.height, bw, bh, "cover", anchor)
        canvas = Image.new("RGB", (bw, bh), P["bg"])
        compose(v.convert("RGB"), canvas, pl)
        if sc.get("blur"):
            canvas = canvas.filter(ImageFilter.GaussianBlur(bh * 0.018))
        return canvas, pl, bw, bh

    if t == "document":
        kind, v, info = load_visual(ctx, sc["asset"])
        if kind != "image":
            raise RuntimeError(f"document scenes need an image asset (got {kind}: {info})")
        bw, bh = int(W * Z), int(H * Z)
        marks = apply_marks(v, sc.get("highlights"), sc.get("redact"))
        mode = sc.get("fit", "cover")
        anchor = sc.get("anchor")
        if anchor is None and sc.get("highlights"):
            r = sc["highlights"][0]
            anchor = (0.5, min(1, max(0, r[1] + r[3] / 2)))
        pl = Placement(marks.width, marks.height, bw, bh, mode, tuple(anchor or (0.5, 0.0)), margin=0.05)
        canvas = Image.new("RGB", (bw, bh), P["card_bg"])
        compose(marks, canvas, pl, shadow=(mode == "contain"))
        return canvas, pl, bw, bh

    if t in ("ui_demo", "diagram"):
        svg = sc.get("svg")
        if svg:
            f = ctx.work / "svg" / f"inline_{hashlib.sha1(svg.encode()).hexdigest()[:10]}.svg"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(svg)
            sc = dict(sc, asset=str(f.resolve()))
        kind, v, info = load_visual(ctx, sc.get("asset"), sc.get("want") or "diagram")
        margin = 0.02 if t == "ui_demo" else 0.08
        if kind == "video":
            bw, bh = W, H
            pl = Placement(info["w"], info["h"], bw, bh, "contain", margin=margin)
            return ("video", v, float(sc.get("asset_start", 0)), video_prefilter(pl, bw, bh, "contain", P, False)), pl, bw, bh
        bw, bh = int(W * Z), int(H * Z)
        if kind == "missing":
            if t == "ui_demo":
                raise RuntimeError(f"ui_demo asset not found: {sc.get('asset')}")
            return placeholder(bw, bh, f"[ diagram missing ] {info}", P), None, bw, bh
        pl = Placement(v.width, v.height, bw, bh, "contain", margin=margin)
        canvas = Image.new("RGB", (bw, bh), P["bg"])
        compose(v, canvas, pl)
        return canvas, pl, bw, bh
    raise RuntimeError(f"unknown scene type {t}")


def video_prefilter(pl: Placement, bw, bh, mode, P, blur) -> str:
    ow, oh = max(2, round(pl.sw * pl.scale) // 2 * 2), max(2, round(pl.sh * pl.scale) // 2 * 2)
    f = f"fps={CFG['fps']},scale={ow}:{oh}"
    if mode == "cover":
        f += f",crop={bw}:{bh}:{max(0, round(-pl.ox))}:{max(0, round(-pl.oy))}"
    else:
        col = "0x%02x%02x%02x" % tuple(P["bg"])
        f += f",pad={bw}:{bh}:{round(pl.ox)}:{round(pl.oy)}:color={col}"
    if blur:
        f += ",gblur=sigma=18"
    return f + ","


def card_base(ctx: Ctx, sc: dict) -> Image.Image:
    P, W, H, t = ctx.P, fw(), fh(), sc["type"]
    light = t in ("quote", "stat") or (t == "big_text" and sc.get("bg") == "light")
    img = Image.new("RGBA", (W, H), P["card_bg"] if light else P["bg"])
    ink = P["ink"] if light else P["text"]
    muted = P["muted"]
    hlkw = dict(hl_mode="marker", hl_fill=(255, 225, 77), hl_ink=(20, 20, 20)) if (light or P["hl_mode"] == "marker") \
        else dict(hl_mode="color", hl_fill=P["hl_fill"], hl_ink=P["hl_ink"])

    if t in ("big_text", "outro"):
        big_caps = t == "outro" and ctx.name == "plugin"
        big = TextLayout(sc.get("text", ""), get_font(fs(0.095 if t == "outro" else 0.085), True), W * 0.78, 1.18, caps=big_caps)
        sub = TextLayout(sc["sub"], get_font(fs(0.042), False), W * 0.7, 1.3) if sc.get("sub") else None
        gap = fs(0.035)
        total = big.h + (gap + sub.h if sub else 0)
        y = (H - total) / 2
        big.draw(img, (W - big.w) / 2, y, align="center", fill=ink, caps=big_caps, **hlkw)
        if sub:
            sub.draw(img, (W - sub.w) / 2, y + big.h + gap, align="center", fill=(P["accent"] if t == "outro" else muted), **hlkw)
    elif t == "stat":
        label = TextLayout(sc.get("label", ""), get_font(fs(0.034), True), W * 0.7, 1.2, caps=True)
        val = TextLayout(str(sc.get("value", "")), get_font(fs(0.17), True), W * 0.85, 1.1)
        note = TextLayout(sc["note"], get_font(fs(0.032), False), W * 0.6, 1.3) if sc.get("note") else None
        total = label.h + fs(0.03) + val.h + (fs(0.03) + note.h if note else 0)
        y = (H - total) / 2
        label.draw(img, (W - label.w) / 2, y, align="center", fill=muted, caps=True)
        val.draw(img, (W - val.w) / 2, y + label.h + fs(0.03), align="center", fill=ink, **hlkw)
        if note:
            note.draw(img, (W - note.w) / 2, y + label.h + val.h + fs(0.06), align="center", fill=muted)
    elif t == "quote":
        portrait = None
        if sc.get("portrait"):
            k, v, _ = load_visual(ctx, sc["portrait"])
            portrait = v if k == "image" else None
        card_w = W * (0.56 if portrait else 0.62)
        pad = fs(0.05)
        q = TextLayout(sc.get("quote", ""), get_font(fs(0.05), True), card_w - 2 * pad - 14, 1.28)
        who = TextLayout(sc["attribution"], get_font(fs(0.028), False), card_w - 2 * pad, 1.3) if sc.get("attribution") else None
        card_h = q.h + 2 * pad + (who.h + fs(0.025) if who else 0)
        cx = W * (0.60 if portrait else 0.5)
        x0, y0 = cx - card_w / 2, (H - card_h) / 2
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 14, x0 + card_w, y0 + card_h + 14), 14, fill=(0, 0, 0, 70))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(22)))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x0, y0, x0 + card_w, y0 + card_h), 14, fill=(255, 255, 255, 255))
        d.rectangle((x0, y0 + 10, x0 + 8, y0 + card_h - 10), fill=P["accent"] if ctx.name == "doc" else (245, 185, 66))
        q.draw(img, x0 + pad + 14, y0 + pad, fill=(24, 24, 26), hl_mode="marker", hl_fill=(255, 225, 77), hl_ink=(20, 20, 20))
        if who:
            who.draw(img, x0 + pad + 14, y0 + pad + q.h + fs(0.02), fill=muted)
        if portrait is not None:
            pw = int(W * 0.17)
            ph = int(pw * 1.2)
            pl = Placement(portrait.width, portrait.height, pw, ph, "cover", (0.5, 0.2))
            tile = Image.new("RGB", (pw, ph), (200, 200, 200))
            compose(portrait, tile, pl)
            img.paste(tile, (int(x0 - pw - W * 0.03), int(H / 2 - ph / 2)))
    return img.convert("RGB")


# --------------------------------------------------------------------------- camera

def resolve_camera(sc: dict, idx: int, pl: Placement | None, video: bool) -> dict:
    t = sc["type"]
    zmax = VIDEO_MAX_ZOOM if video else IMG_MAX_ZOOM
    cam = sc.get("camera") or {}
    move = cam.get("move") if isinstance(cam, dict) else cam
    z0, z1, c0, c1 = 1.0, 1.03, (0.5, 0.5), (0.5, 0.5)
    if t == "broll":
        move = move or ("push", "pull", "pan_left", "pan_right")[idx % 4]
    elif t == "document":
        z1 = 1.06
    if move == "push":
        z0, z1 = 1.0, 1.12
    elif move == "pull":
        z0, z1 = 1.12, 1.0
    elif move == "pan_left":
        z0 = z1 = 1.14; c0, c1 = (0.57, 0.5), (0.43, 0.5)
    elif move == "pan_right":
        z0 = z1 = 1.14; c0, c1 = (0.43, 0.5), (0.57, 0.5)
    elif move == "still":
        z0 = z1 = 1.0
    focus = sc.get("focus")
    if focus and pl is not None:
        x0, y0, x1, y1 = pl.rect(focus)
        cw, ch = max(x1 - x0, 0.05), max(y1 - y0, 0.05)
        z1 = max(1.15, min(0.85 / cw, 0.85 / ch, zmax))
        c1 = ((x0 + x1) / 2, (y0 + y1) / 2)
        z0, c0 = 1.0, (0.5, 0.5)
    if isinstance(cam, dict):
        z0, z1 = cam.get("z0", z0), cam.get("z1", z1)
        c0, c1 = tuple(cam.get("c0", c0)), tuple(cam.get("c1", c1))
    z0, z1 = (min(max(z, 1.0), zmax) for z in (z0, z1))
    return dict(z0=z0, z1=z1, c0=c0, c1=c1)


def zoompan_filter(cam: dict, frames: int) -> str:
    n = max(frames - 1, 1)
    p = f"(3*pow(min(on/{n},1),2)-2*pow(min(on/{n},1),3))"
    z = f"{cam['z0']:.4f}+({cam['z1'] - cam['z0']:.4f})*{p}"
    cx = f"{cam['c0'][0]:.4f}+({cam['c1'][0] - cam['c0'][0]:.4f})*{p}"
    cy = f"{cam['c0'][1]:.4f}+({cam['c1'][1] - cam['c0'][1]:.4f})*{p}"
    return (f"zoompan=z='{z}':x='max(0,min(iw-iw/zoom,({cx})*iw-iw/zoom/2))':"
            f"y='max(0,min(ih-ih/zoom,({cy})*ih-ih/zoom/2))':d=1:s={fw()}x{fh()}:fps={CFG['fps']}")


# --------------------------------------------------------------------------- overlays

def stack_layer(ctx: Ctx, item: dict, scene_type: str) -> Image.Image:
    P, W, H = ctx.P, fw(), fh()
    role = item.get("role", "caption")
    pos = POS[item.get("pos") or (("top_left" if role == "stamp" else "top") if role in ("stamp",) else
                                  P["default_pos"].get(scene_type, "bottom"))]
    on_footage = scene_type in ("broll", "document", "ui_demo", "diagram")
    hlkw = dict(hl_mode=P["hl_mode"], hl_fill=P["hl_fill"], hl_ink=P["hl_ink"])
    max_w = (pos["x1"] - pos["x0"]) * W
    parts = []   # (TextLayout, fill, caps)
    text, sub = item.get("text", ""), item.get("sub")
    if role == "stamp":
        parts.append((TextLayout(text, get_font(fs(P["stamp_size"]), True), max_w, 1.15), P["text"], False))
    elif role == "title":
        parts.append((TextLayout(text, get_font(fs(P["title_size"]), True), max_w, 1.15, caps=P["title_caps"]), P["title_color"], P["title_caps"]))
        if sub:
            parts.append((TextLayout(sub, get_font(fs(P["sub_size"]), False), max_w, 1.3), P["text"], False))
    else:
        parts.append((TextLayout(text, get_font(fs(P["caption_size"]), P["caption_bold"]), max_w, 1.3), P["text"], False))
        if sub:
            parts.append((TextLayout(sub, get_font(fs(P["sub_size"] * 0.85), False), max_w, 1.3), P["text"], False))
    gap = fs(0.012)
    total = sum(p[0].h for p in parts) + gap * (len(parts) - 1)
    y = {"top": pos["y"] * H, "bottom": pos["y"] * H - total, "middle": pos["y"] * H - total / 2}[pos["v"]]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for tl, fill, caps in parts:
        x = {"left": pos["x0"] * W, "center": (pos["x0"] + pos["x1"]) / 2 * W - tl.w / 2}[pos["align"]]
        tl.draw(layer, x, y, align=pos["align"], fill=fill, shadow=on_footage, caps=caps, **hlkw)
        y += tl.h + gap
    return layer


def build_layers(ctx: Ctx, sc: dict, D: float):
    """-> list of (png_path, rel_start, rel_end)"""
    t, work = sc["type"], ctx.work / "layers"
    work.mkdir(parents=True, exist_ok=True)
    layers = []
    items = [dict(i) for i in (sc.get("captions") or [])]
    if sc.get("title"):
        items.append(dict(text=sc["title"], sub=sc.get("sub"), role="title", at=sc["start"] + 0.1))
    if sc.get("stamp"):
        items.append(dict(text=sc["stamp"], role="stamp", at=sc["start"] + 0.15))

    # scrims keep text legible on footage
    has_bottom = any((i.get("pos") or ctx.P["default_pos"].get(t, "bottom")).startswith("bottom") and i.get("role") != "title"
                     for i in items) and t in ("broll", "document", "ui_demo", "diagram")
    has_top = any((i.get("role") in ("title", "stamp")) for i in items) and t in ("broll", "ui_demo", "diagram", "document")
    if has_bottom or has_top:
        key = f"scrim_{fw()}_{int(has_bottom)}{int(has_top)}_{t == 'broll'}"
        f = work / f"{key}.png"
        if not f.exists():
            gradient_layer(bottom=0.7 if has_bottom else 0, top=0.55 if has_top else 0,
                           flat=0.18 if t == "broll" else 0).save(f)
        layers.append((f, 0.0, D))

    unplaced = [i for i in items if i.get("at") is None]
    for k, it in enumerate(unplaced):
        it["at"] = sc["start"] + (D / len(unplaced)) * k
    items.sort(key=lambda i: i["at"])
    for n, it in enumerate(items):
        a = max(0.0, it["at"] - sc["start"])
        nxt = items[n + 1]["at"] - sc["start"] if n + 1 < len(items) else D
        b = it.get("until")
        b = (b - sc["start"]) if b is not None else (nxt if it.get("role") not in ("title", "stamp") else D)
        b = min(max(b, a + 0.4), D)
        if a >= D - 0.2:
            continue
        h = hashlib.sha1(json.dumps([CACHE_VER, it.get("text"), it.get("sub"), it.get("role"), it.get("pos"), ctx.name, t, fw()]).encode()).hexdigest()[:12]
        f = work / f"txt_{h}.png"
        if not f.exists():
            stack_layer(ctx, it, t).save(f)
        layers.append((f, a, b))
    return layers


# --------------------------------------------------------------------------- render

def scene_hash(ctx: Ctx, sc: dict) -> str:
    key = dict(sc=sc, preset=ctx.name, w=fw(), h=fh(), fps=CFG["fps"], crf=CFG["crf"], v=CACHE_VER)
    for k in ("asset", "portrait"):
        p = find_asset(ctx, sc.get(k))
        if p:
            key[k] = [p.name, p.stat().st_size, int(p.stat().st_mtime)]
    return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()[:10]


def render_scene(ctx: Ctx, idx: int, sc: dict, out: Path):
    fps = CFG["fps"]
    frames = sc["frames"]
    D = frames / fps
    base, pl, bw, bh = stage_base(ctx, sc)
    is_video = isinstance(base, tuple)
    cam = resolve_camera(sc, idx, pl, is_video)
    layers = build_layers(ctx, sc, D)

    cmd = ["ffmpeg", "-y", "-v", "error"]
    if is_video:
        _, vpath, vstart, pre = base
        cmd += ["-stream_loop", "-1", "-ss", f"{vstart:.3f}", "-t", f"{D:.4f}", "-i", str(vpath)]
    else:
        bp = ctx.work / "bases" / f"base_{idx:03d}_{scene_hash(ctx, sc)}.png"
        bp.parent.mkdir(parents=True, exist_ok=True)
        base.save(bp)
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{D:.4f}", "-i", str(bp)]
        pre = ""
    for png, _, _ in layers:
        cmd += ["-loop", "1", "-framerate", str(fps), "-t", f"{D:.4f}", "-i", str(png)]

    parts = [f"[0:v]{pre}{zoompan_filter(cam, frames)}[v0]"]
    prev = "v0"
    for k, (png, a, b) in enumerate(layers, 1):
        fo = f",fade=t=out:st={max(a, b - 0.15):.3f}:d=0.15:alpha=1" if b < D - 0.05 else ""
        parts.append(f"[{k}:v]format=rgba,fade=t=in:st={a:.3f}:d=0.2:alpha=1{fo}[l{k}]")
        parts.append(f"[{prev}][l{k}]overlay=0:0:format=auto[o{k}]")
        prev = f"o{k}"
    parts.append(f"[{prev}]format=yuv420p[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-frames:v", str(frames), "-r", str(fps),
            "-c:v", "libx264", "-preset", CFG["x264_preset"], "-crf", str(CFG["crf"]), "-pix_fmt", "yuv420p", "-an", str(out)]
    run(cmd)


def normalise(scenes: list[dict], dur: float) -> list[dict]:
    fps = CFG["fps"]
    scenes = sorted((dict(s) for s in scenes), key=lambda s: float(s["start"]))
    t = 0.0
    for i, s in enumerate(scenes):
        s["start"] = t
        end = float(s["end"]) if i < len(scenes) - 1 else dur
        s["end"] = max(end, s["start"] + MIN_SCENE) if i < len(scenes) - 1 else max(end, s["start"] + 0.5)
        t = s["end"]
    cum = 0
    for s in scenes:
        f_end = round(s["end"] * fps)
        s["frames"] = max(2, f_end - cum)
        cum += s["frames"]
    return scenes


def mux_audio(video: Path, audio: Path, music: Path | None, dur: float, out: Path, music_db: float):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        vol = 10 ** (music_db / 20)
        fc = (f"[1:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11,asplit=2[vo][key];"
              f"[2:a]aresample=48000,atrim=duration={dur:.3f},volume={vol:.4f},afade=t=in:d=2,afade=t=out:st={max(0, dur - 3):.3f}:d=3[m];"
              f"[m][key]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=450[duck];"
              f"[vo][duck]amix=inputs=2:duration=first:normalize=0[a]")
        cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-filter_complex", "[1:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11[a]", "-map", "0:v", "-map", "[a]"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(out)]
    run(cmd)


def render(plan: dict, audio: Path, assets: Path, preset: str, out: Path, work: Path, music: Path | None = None,
           music_db: float = -20.0, force: bool = False):
    ctx = Ctx(preset, assets, work)
    dur = audio_duration(audio)
    errors, warns = validate_plan(plan, assets, dur)
    for w in warns:
        print("  warn:", w)
    if errors:
        die("plan has problems:\n  - " + "\n  - ".join(errors))
    scenes = normalise(plan["scenes"], dur)
    clips_dir = work / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    listing, made, reused = [], 0, 0
    for i, sc in enumerate(scenes):
        clip = clips_dir / f"clip_{i:03d}_{scene_hash(ctx, dict(sc))}.mp4"
        if clip.exists() and not force:
            reused += 1
        else:
            try:
                render_scene(ctx, i, sc, clip)
            except Exception as e:
                die(f"scene {i} ({sc['type']}, {sc['start']:.1f}-{sc['end']:.1f}s) failed: {e}")
            made += 1
        listing.append(clip)
        print(f"\r  scenes {i + 1}/{len(scenes)} (new {made}, cached {reused})", end="", flush=True)
    print()
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{c.resolve()}'\n" for c in listing))
    silent = work / "video_silent.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)])
    mux_audio(silent, audio, music, dur, out, music_db)
    print(f"done -> {out}  ({dur:.1f}s, {len(scenes)} scenes)")


# --------------------------------------------------------------------------- plan validation

def validate_plan(plan: dict, assets: Path, dur: float):
    errors, warns = [], []
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or not scenes:
        return ["plan needs a non-empty 'scenes' list"], warns
    prev_end = 0.0
    for i, s in enumerate(scenes):
        tag = f"scene {i}"
        if s.get("type") not in SCENE_TYPES:
            errors.append(f"{tag}: type must be one of {sorted(SCENE_TYPES)} (got {s.get('type')!r})")
            continue
        try:
            a, b = float(s["start"]), float(s["end"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{tag}: needs numeric start and end")
            continue
        if b <= a:
            errors.append(f"{tag}: end must be after start")
        if a < prev_end - 0.25 or a > prev_end + 0.5:
            warns.append(f"{tag}: starts at {a:.2f}s but previous scene ended {prev_end:.2f}s (will be snapped)")
        prev_end = b
        if b - a < MIN_SCENE and i < len(scenes) - 1:
            warns.append(f"{tag}: shorter than {MIN_SCENE}s, will be stretched")
        t = s["type"]
        if t in NEEDS_ASSET and not (s.get("asset") and (Path(s["asset"]).is_absolute() and Path(s["asset"]).exists() or (assets / s["asset"]).exists())):
            errors.append(f"{tag}: {t} needs an existing asset, '{s.get('asset')}' not found in {assets}")
        if t == "broll" and not s.get("asset"):
            warns.append(f"{tag}: b-roll has no asset; a placeholder will render ('want': {s.get('want')!r})")
        elif t == "broll" and not (assets / s["asset"]).exists() and not Path(s["asset"]).exists():
            warns.append(f"{tag}: b-roll asset '{s['asset']}' missing, placeholder will render")
        if t == "diagram":
            if not s.get("svg") and not s.get("asset"):
                errors.append(f"{tag}: diagram needs 'svg' (inline) or 'asset'")
            if s.get("svg"):
                try:
                    ET.fromstring(s["svg"])
                except ET.ParseError as e:
                    errors.append(f"{tag}: inline svg is not valid XML ({e})")
        if t == "quote" and not s.get("quote"):
            errors.append(f"{tag}: quote needs 'quote'")
        if t in ("big_text", "outro") and not s.get("text"):
            errors.append(f"{tag}: {t} needs 'text'")
        if t == "stat" and not s.get("value"):
            errors.append(f"{tag}: stat needs 'value'")
        for key in ("highlights", "redact"):
            for r in s.get(key) or []:
                if not (isinstance(r, list) and len(r) == 4 and all(isinstance(v, (int, float)) for v in r)):
                    errors.append(f"{tag}: {key} entries must be [x, y, w, h] fractions")
        f = s.get("focus")
        if f is not None and not (isinstance(f, list) and len(f) == 4):
            errors.append(f"{tag}: focus must be [x, y, w, h] fractions of the asset")
        for c in s.get("captions") or []:
            if not c.get("text"):
                errors.append(f"{tag}: caption without text")
            if c.get("pos") and c["pos"] not in POS:
                errors.append(f"{tag}: caption pos must be one of {sorted(POS)}")
    if scenes and abs(float(scenes[-1].get("end", 0)) - dur) > 3:
        warns.append(f"last scene ends at {scenes[-1].get('end')}s but audio is {dur:.1f}s (last scene will be stretched/trimmed)")
    return errors, warns


# --------------------------------------------------------------------------- transcription

def transcribe(audio: Path, model_size: str = "small") -> list[dict]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        die("transcription needs `pip install faster-whisper` (or pass --words words.json)")
    model = WhisperModel(model_size, compute_type="int8")
    segs, _ = model.transcribe(str(audio), word_timestamps=True, vad_filter=True)
    words = [dict(w=w.word.strip(), s=round(w.start, 2), e=round(w.end, 2)) for seg in segs for w in (seg.words or [])]
    if not words:
        die("no speech found in the audio")
    return words


def sentences_from_words(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = (words[i + 1]["s"] - w["e"]) if i + 1 < len(words) else 99
        if re.search(r"[.?!]['\")]?$", w["w"]) or gap > 0.8:
            out.append(dict(i=len(out), start=cur[0]["s"], end=cur[-1]["e"], text=" ".join(x["w"] for x in cur)))
            cur = []
    if cur:
        out.append(dict(i=len(out), start=cur[0]["s"], end=cur[-1]["e"], text=" ".join(x["w"] for x in cur)))
    return out


# --------------------------------------------------------------------------- director (Claude)

def list_assets(assets: Path) -> list[dict]:
    out = []
    for p in sorted(assets.rglob("*")):
        ext = p.suffix.lower()
        if ext not in IMG_EXT | VID_EXT | {".svg"}:
            continue
        info = dict(file=str(p.relative_to(assets)), kind="video" if ext in VID_EXT else ("svg" if ext == ".svg" else "image"))
        try:
            if ext in IMG_EXT:
                with Image.open(p) as im:
                    info.update(w=im.width, h=im.height)
            elif ext in VID_EXT:
                pr = probe(p)
                info.update(w=pr["w"], h=pr["h"], seconds=round(pr["dur"], 1))
        except Exception:
            pass
        note = p.with_suffix(".txt")
        info["description"] = note.read_text().strip()[:300] if note.exists() else re.sub(r"[_\-]+", " ", p.stem)
        out.append(info)
    return out


def extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("no JSON object in reply")
    return json.loads(text[a:b + 1])


def direct(words: list[dict], assets: Path, preset: str, brief: str, dur: float, model: str) -> dict:
    try:
        import anthropic  # type: ignore
    except ImportError:
        die("the director needs `pip install anthropic` and ANTHROPIC_API_KEY (or pass --plan plan.json)")
    system = (HERE / "director_prompt.md").read_text()
    payload = dict(style=preset, brief=brief or "", audio_seconds=round(dur, 2),
                   sentences=sentences_from_words(words), assets=list_assets(assets))
    msgs = [dict(role="user", content="Edit this video. Input:\n" + json.dumps(payload, ensure_ascii=False))]
    client = anthropic.Anthropic()
    max_tokens = int(os.environ.get("AUTOEDIT_MAX_TOKENS", "32000"))
    plan = None
    for attempt in range(3):
        with client.messages.stream(model=model, max_tokens=max_tokens, system=system, messages=msgs) as stream:
            reply = stream.get_final_text()
        try:
            plan = extract_json(reply)
            errors, warns = validate_plan(plan, assets, dur)
        except Exception as e:
            plan, errors, warns = None, [f"reply was not valid JSON: {e}"], []
        if not errors:
            for w in warns:
                print("  warn:", w)
            return plan
        print(f"  director attempt {attempt + 1}: {len(errors)} problem(s), asking for a fix")
        msgs += [dict(role="assistant", content=reply),
                 dict(role="user", content="Fix these problems and return the full corrected JSON only:\n- " + "\n- ".join(errors[:25]))]
    die("the director could not produce a valid plan; last problems:\n  - " + "\n  - ".join(errors[:10]))


# --------------------------------------------------------------------------- CLI

def apply_common(args):
    if args.res:
        w, h = (int(x) for x in args.res.lower().split("x"))
        CFG.update(w=w, h=h)
    if getattr(args, "preview", False):
        CFG.update(w=960, h=540, x264_preset="ultrafast", crf=28)
    CFG["fps"] = args.fps
    CFG["font"], CFG["font_bold"] = args.font, args.font_bold
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            die(f"{tool} not found on PATH")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--audio", type=Path)
        p.add_argument("--assets", type=Path, default=Path("assets"))
        p.add_argument("--preset", choices=sorted(PRESETS), default="doc")
        p.add_argument("--work", type=Path, help="working folder (default: work_<audio name>)")
        p.add_argument("--res", help="output size, e.g. 1920x1080 (default) or 1280x720")
        p.add_argument("--fps", type=int, default=30)
        p.add_argument("--font", help="regular font file (.ttf/.otf)")
        p.add_argument("--font-bold", help="bold font file")
        p.add_argument("--preview", action="store_true", help="fast 960x540 draft render")

    for name in ("make", "render"):
        p = sub.add_parser(name)
        common(p)
        p.add_argument("--out", type=Path, default=Path("final.mp4"))
        p.add_argument("--music", type=Path)
        p.add_argument("--music-db", type=float, default=-20.0, help="music level under the voice (default -20)")
        p.add_argument("--plan", type=Path)
        p.add_argument("--force", action="store_true", help="re-render every scene")
        if name == "make":
            p.add_argument("--words", type=Path)
            p.add_argument("--brief", default="", help="one paragraph about the video: topic, audience, tone, brand name")
            p.add_argument("--whisper", default="small", help="faster-whisper model size")
            p.add_argument("--model", default=os.environ.get("AUTOEDIT_MODEL", "claude-sonnet-5-5"))
            p.add_argument("--redirect", action="store_true", help="ask the director for a new plan even if plan.json exists")
    p = sub.add_parser("transcribe"); common(p); p.add_argument("--whisper", default="small"); p.add_argument("--out", type=Path)
    p = sub.add_parser("direct"); common(p)
    p.add_argument("--words", type=Path, required=True); p.add_argument("--brief", default="")
    p.add_argument("--model", default=os.environ.get("AUTOEDIT_MODEL", "claude-sonnet-5-5")); p.add_argument("--out", type=Path)
    p = sub.add_parser("validate"); common(p); p.add_argument("--plan", type=Path, required=True)

    args = ap.parse_args()
    apply_common(args)
    if args.cmd != "validate" and not args.audio:
        die("--audio is required")
    work = args.work or (Path("work_" + args.audio.stem) if args.audio else Path("work"))
    work.mkdir(parents=True, exist_ok=True)

    if args.cmd == "transcribe":
        words = transcribe(args.audio, args.whisper)
        out = args.out or work / "words.json"
        out.write_text(json.dumps(words, indent=1))
        print(f"{len(words)} words -> {out}")
    elif args.cmd == "direct":
        words = json.loads(args.words.read_text())
        plan = direct(words, args.assets, args.preset, args.brief, audio_duration(args.audio), args.model)
        out = args.out or work / "plan.json"
        out.write_text(json.dumps(plan, indent=1, ensure_ascii=False))
        print(f"{len(plan['scenes'])} scenes -> {out}")
    elif args.cmd == "validate":
        plan = json.loads(args.plan.read_text())
        dur = audio_duration(args.audio) if args.audio else float(plan["scenes"][-1]["end"])
        errs, warns = validate_plan(plan, args.assets, dur)
        print("\n".join([f"error: {e}" for e in errs] + [f"warn:  {w}" for w in warns]) or "plan looks fine")
        sys.exit(1 if errs else 0)
    elif args.cmd == "render":
        plan_path = args.plan or work / "plan.json"
        if not plan_path.exists():
            die(f"{plan_path} not found; run `make` or `direct` first")
        render(json.loads(plan_path.read_text()), args.audio, args.assets, args.preset, args.out, work,
               args.music, args.music_db, args.force)
    elif args.cmd == "make":
        wpath = args.words or work / "words.json"
        if wpath.exists():
            words = json.loads(wpath.read_text())
        else:
            print("transcribing...")
            words = transcribe(args.audio, args.whisper)
            wpath.write_text(json.dumps(words, indent=1))
        plan_path = args.plan or work / "plan.json"
        if plan_path.exists() and not args.redirect:
            print(f"using existing {plan_path} (pass --redirect for a fresh plan)")
            plan = json.loads(plan_path.read_text())
        else:
            print("directing...")
            plan = direct(words, args.assets, args.preset, args.brief, audio_duration(args.audio), args.model)
            plan_path.write_text(json.dumps(plan, indent=1, ensure_ascii=False))
            print(f"plan saved -> {plan_path}")
        render(plan, args.audio, args.assets, args.preset, args.out, work, args.music, args.music_db, args.force)


if __name__ == "__main__":
    main()
