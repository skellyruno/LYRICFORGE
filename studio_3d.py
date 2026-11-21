"""3D-style logo animations and livestream scenes, drawn by a small software renderer (Pillow + FFmpeg).

What this is: a flat logo (or title) is extruded into stacked depth layers, tilted in true perspective, lit with a moving
highlight and flown in with a camera dolly. Frames are piped straight into FFmpeg. What it is not: a 3D engine. It
cannot load models or render arbitrary 3D scenes; it makes logo and text badges look solid and spin convincingly.
"""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path
from typing import Callable

import studio_edit as edit
import studio_performance as perf

SCENES = ("intro", "starting", "brb", "ending")
SCENE_TEXT = {"starting": "STARTING SOON", "brb": "BE RIGHT BACK", "ending": "THANKS FOR WATCHING"}
INTRO_SECONDS, LOOP_SECONDS = 5.0, 8.0
LAYERS = 12


# ------------------------------------------------------------------------------------ math
def solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve a small linear system by Gaussian elimination with partial pivoting."""
    n = len(vector)
    m = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("degenerate transform")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def perspective_coeffs(dst: list[tuple[float, float]], src: list[tuple[float, float]]) -> list[float]:
    """Coefficients for Pillow's PERSPECTIVE transform: each output point (dst) is looked up at a source point."""
    rows, vec = [], []
    for (X, Y), (x, y) in zip(dst, src):
        rows.append([X, Y, 1, 0, 0, 0, -X * x, -Y * x])
        vec.append(x)
        rows.append([0, 0, 0, X, Y, 1, -X * y, -Y * y])
        vec.append(y)
    return solve(rows, vec)


def rotate(point: tuple[float, float, float], yaw: float, pitch: float, roll: float) -> tuple[float, float, float]:
    x, y, z = point
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    cr, sr = math.cos(roll), math.sin(roll)
    x, y = x * cr - y * sr, x * sr + y * cr
    return x, y, z


def project(point: tuple[float, float, float], focal: float, cx: float, cy: float) -> tuple[float, float]:
    x, y, z = point
    k = focal / max(focal + z, 1.0)
    return cx + x * k, cy + y * k


def ease_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------------- poses
def pose_intro(t: float) -> dict:
    """Fly in from deep behind the screen while spinning, slam into place, then float. All angles in radians."""
    fly = 1.6
    if t < fly:
        k = ease_out(t / fly)
        return {"yaw": (1 - k) * 3 * math.pi, "pitch": (1 - k) * -.5, "roll": (1 - k) * .4, "z": (1 - k) * 5200,
                "scale": 1.0, "alpha": smooth(t / .35), "flash": 0.0, "shake": 0.0}
    u = t - fly
    flash = max(0.0, 1 - u / .28) * .4
    shake = max(0.0, 1 - u / .35)
    sway = math.sin(u / 3.4 * math.tau)
    return {"yaw": .24 * sway, "pitch": .1 * math.sin(u / 3.4 * math.tau + 1.0), "roll": .02 * sway,
            "z": 40 * math.sin(u / 2.4 * math.tau), "scale": 1.0 + .015 * math.sin(u * 2), "alpha": 1.0,
            "flash": flash, "shake": shake}


def pose_loop(t: float, period: float = LOOP_SECONDS) -> dict:
    """A gentle float that ends exactly where it began, so the video loops without a visible seam."""
    a = t / period * math.tau
    return {"yaw": .42 * math.sin(a), "pitch": .13 * math.sin(a + 1.3), "roll": .03 * math.sin(2 * a), "z": 60 * math.sin(2 * a + .5),
            "scale": 1.0, "alpha": 1.0, "flash": 0.0, "shake": 0.0}


# ------------------------------------------------------------------------------- drawing
def hex_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def mix(a: tuple[int, int, int], b: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * f) for i in range(3))


def make_badge(size: tuple[int, int], logo: Path | None, text: str, brand: dict):
    """The flat artwork that gets extruded: your logo, or the text in the brand font when there is no logo."""
    from PIL import Image, ImageDraw
    w, h = size
    badge = Image.new("RGBA", size, (0, 0, 0, 0))
    if logo and logo.is_file():
        with Image.open(logo) as mark:
            mark = mark.convert("RGBA")
            mark.thumbnail((round(w * .86), round(h * .86)))
            badge.paste(mark, ((w - mark.width) // 2, (h - mark.height) // 2), mark)
        return badge
    draw = ImageDraw.Draw(badge)
    words = (text or "LIVE").upper().split()
    size_px = round(h * (.42 if len(words) <= 1 else .3))
    while True:
        font = edit.find_font(brand["font"], size_px)
        lines, cur = [], ""
        for word in words:
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=font) > w * .92 and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
        widest = max(draw.textlength(line, font=font) for line in lines)
        if (widest <= w * .94 and len(lines) * size_px * 1.1 <= h * .92) or size_px < 18:
            break
        size_px = round(size_px * .9)
    y = (h - len(lines) * size_px * 1.1) / 2
    for line in lines:
        draw.text(((w - draw.textlength(line, font=font)) / 2, y), line, font=font, fill=hex_rgb(brand["text"]) + (255,))
        y += size_px * 1.1
    return badge


class Scene:
    """Everything that does not change from frame to frame, built once."""

    def __init__(self, width: int, height: int, brand: dict, logo: Path | None, title: str, subtitle: str, headline: str,
                 loop: bool):
        from PIL import Image, ImageDraw, ImageFilter, ImageChops
        self.w, self.h, self.loop = width, height, loop
        self.brand = brand
        self.accent, self.bg, self.text = hex_rgb(brand["accent"]), hex_rgb(brand["bg"]), hex_rgb(brand["text"])
        k = height / 1080
        self.focal = 1500 * k
        bw, bh = round(width * .34), round(height * .5)
        self.size = (bw, bh)
        self.badge = make_badge((bw, bh), logo, title or brand["name"], brand)
        # extrusion: dark silhouettes of the artwork, a little darker the deeper they sit
        alpha = self.badge.getchannel("A")
        self.depth = round(bw * .09)
        self.layers = []
        for i in range(LAYERS - 1, 0, -1):
            f = i / (LAYERS - 1)
            shade = mix(mix(self.accent, self.bg, .55), (0, 0, 0), .35 + .5 * f)
            layer = Image.new("RGBA", (bw, bh), shade + (0,))
            layer.putalpha(alpha)
            self.layers.append((self.depth * f, layer))  # +z is away from the camera: the extrusion sits behind the face
        self.front = self.badge
        self.alpha = alpha
        band = Image.new("L", (bw, bh), 0)
        d = ImageDraw.Draw(band)
        d.polygon([(bw * .38, 0), (bw * .56, 0), (bw * .36, bh), (bw * .18, bh)], fill=255)
        self.band = band.filter(ImageFilter.GaussianBlur(bw * .035))
        # background: soft radial glow in the accent color, drifting bokeh dots
        base = Image.new("RGB", (width, height), self.bg)
        glow = Image.new("RGB", (width, height), mix(self.bg, self.accent, .32))
        mask = Image.radial_gradient("L").resize((width, height)).point(lambda v: max(0, 255 - round(v * 1.45)))
        self.backdrop = Image.composite(glow, base, mask.point(lambda v: round(v * .75)))
        rng = random.Random(5)
        dots = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        dd = ImageDraw.Draw(dots)
        for _ in range(26):
            r = rng.uniform(.01, .045) * height
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            dd.ellipse([x - r, y - r, x + r, y + r], fill=self.accent + (rng.randint(22, 60),))
        self.bokeh = dots.filter(ImageFilter.GaussianBlur(height * .006))
        halo = Image.new("RGBA", (round(bw * 1.9), round(bh * 1.9)), (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        hd.ellipse([halo.width * .18, halo.height * .18, halo.width * .82, halo.height * .82], fill=self.accent + (120,))
        self.halo = halo.filter(ImageFilter.GaussianBlur(bw * .16))
        self.headline = self._text_layer(headline, round(height * .075), True) if headline else None
        self.subtitle = self._text_layer(subtitle, round(height * .04), False) if subtitle else None

    def _text_layer(self, text: str, size_px: int, bold: bool):
        from PIL import Image, ImageDraw
        font = edit.find_font(self.brand["font"], size_px)
        probe = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        width = min(round(self.w * .9), max(10, round(probe.textlength(text, font=font)) + 20))
        layer = Image.new("RGBA", (width, round(size_px * 1.5)), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        color = self.text if bold else mix(self.text, self.bg, .25)
        d.text((10, size_px * .1), text, font=font, fill=color + (255,), stroke_width=max(1, size_px // 24), stroke_fill=(0, 0, 0, 160))
        return layer

    def badge_quad(self, pose: dict, z_offset: float) -> list[tuple[float, float]]:
        w, h = self.size
        cx, cy = self.w / 2, self.h * (.44 if self.headline else .5)
        corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
        out = []
        for x, y in corners:
            p = rotate((x * pose["scale"], y * pose["scale"], z_offset), pose["yaw"], pose["pitch"], pose["roll"])
            out.append(project((p[0], p[1], p[2] + pose["z"]), self.focal, cx, cy))
        return out

    def frame(self, t: float, pose: dict, fade_in_text_at: float | None):
        from PIL import Image, ImageChops
        W, H = self.w, self.h
        canvas = self.backdrop.copy()
        drift = (t / (LOOP_SECONDS if self.loop else 10.0)) * W * (1 if self.loop else .35)
        canvas.paste(ImageChops.offset(self.bokeh, round(drift) % W, 0), (0, 0), ImageChops.offset(self.bokeh, round(drift) % W, 0))
        shake = pose["shake"] * H * .012
        ox = round(math.sin(t * 90) * shake)
        oy = round(math.cos(t * 70) * shake)
        if pose["alpha"] > .01:
            hw, hh = self.halo.size
            halo = self.halo
            canvas.paste(halo, (round(W / 2 - hw / 2) + ox, round(H * (.44 if self.headline else .5) - hh / 2) + oy), halo)
            sweep = ((t * (.5 if self.loop else .42)) % 1.0)
            dx = round((sweep * 2.2 - 1.0) * self.size[0])
            band = ImageChops.offset(self.band, dx, 0)
            lit = Image.new("RGBA", self.size, (255, 255, 255, 0))
            lit.putalpha(ImageChops.multiply(band, self.alpha).point(lambda v: round(v * .8)))
            front = Image.alpha_composite(self.front, lit)
            draws = [(z, layer) for z, layer in self.layers] + [(0.0, front)]
            rendered = []
            for z, layer in draws:
                quad = self.badge_quad(pose, z)
                depth = sum(rotate((0, 0, z), pose["yaw"], pose["pitch"], pose["roll"])[2:]) + pose["z"]
                rendered.append((depth, quad, layer))
            rendered.sort(key=lambda r: -r[0])  # farthest first
            xs = [p[0] for _, q, _ in rendered for p in q]
            ys = [p[1] for _, q, _ in rendered for p in q]
            x0, y0 = max(0, math.floor(min(xs)) - 4), max(0, math.floor(min(ys)) - 4)
            x1, y1 = min(W, math.ceil(max(xs)) + 4), min(H, math.ceil(max(ys)) + 4)
            if x1 > x0 and y1 > y0:
                region = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
                w, h = self.size
                src = [(0, 0), (w, 0), (w, h), (0, h)]
                for _, quad, layer in rendered:
                    dst = [(px - x0, py - y0) for px, py in quad]
                    try:
                        coeffs = perspective_coeffs(dst, src)
                    except ValueError:
                        continue
                    warped = layer.transform(region.size, Image.PERSPECTIVE, coeffs, Image.BILINEAR)
                    region = Image.alpha_composite(region, warped)
                if pose["alpha"] < 1:
                    region.putalpha(region.getchannel("A").point(lambda v, a=pose["alpha"]: round(v * a)))
                canvas.paste(region, (x0 + ox, y0 + oy), region)
        if self.headline is not None:
            self._paste_text(canvas, self.headline, H * .80, 1.0 if self.loop else smooth((t - (fade_in_text_at or 0)) / .5))
        if self.subtitle is not None:
            lag = .25
            self._paste_text(canvas, self.subtitle, H * .895, 1.0 if self.loop else smooth((t - (fade_in_text_at or 0) - lag) / .5))
        if pose["flash"] > .01:
            canvas = Image.blend(canvas, Image.new("RGB", (W, H), (255, 255, 255)), min(1.0, pose["flash"]))
        return canvas

    def _paste_text(self, canvas, layer, y: float, opacity: float) -> None:
        if opacity <= .01:
            return
        lift = round((1 - opacity) * self.h * .02)
        shown = layer if opacity >= 1 else layer.copy()
        if opacity < 1:
            shown.putalpha(layer.getchannel("A").point(lambda v, o=opacity: round(v * o)))
        canvas.paste(shown, (round((self.w - layer.width) / 2), round(y - layer.height / 2) + lift), shown)


# --------------------------------------------------------------------------------- scenes
def scene_plan(kind: str, title: str, subtitle: str, brand: dict) -> dict:
    if kind == "intro":
        return {"seconds": INTRO_SECONDS, "loop": False, "headline": title or brand["name"] or "", "sub": subtitle,
                "pose": pose_intro, "text_at": 1.9}
    if kind in SCENE_TEXT:
        return {"seconds": LOOP_SECONDS, "loop": True, "headline": SCENE_TEXT[kind], "sub": subtitle,
                "pose": pose_loop, "text_at": 0.0}
    raise ValueError(f"Unknown scene: {kind}")


def intro_sfx_events() -> list[tuple[float, str, float]]:
    """Riser into the impact when the logo lands, a whoosh as it flies in, a chime as the text arrives."""
    return [(.05, "riser", .7), (.15, "whoosh", .6), (1.58, "impact", 1.0), (2.1, "ding", .35)]


def render_scene(kind: str, output: Path, *, width: int, height: int, brand: dict, logo: Path | None, title: str = "",
                 subtitle: str = "", fps: int = 30, sfx_wav: Path | None = None,
                 on_progress: Callable[[float], None] | None = None) -> dict:
    """Render one scene to an MP4. Intro scenes carry sound if sfx_wav is given; loop scenes are silent."""
    plan = scene_plan(kind, title, subtitle, brand)
    scene = Scene(width, height, brand, logo, title or brand["name"], plan["sub"], plan["headline"], plan["loop"])
    frames = round(plan["seconds"] * fps)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"]
    if sfx_wav is not None:
        cmd += ["-i", str(sfx_wav)]
    cmd += ["-map", "0:v"] + (["-map", "1:a", "-c:a", "aac", "-b:a", "192k"] if sfx_wav is not None else ["-an"])
    cmd += [*perf.encode_args("libx264", "fast", width, height, 2), "-pix_fmt", "yuv420p", "-t", f"{plan['seconds']:.3f}",
            "-movflags", "+faststart", str(output)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **perf.windows_child_options(low_priority=True))
    try:
        for n in range(frames):
            t = n / fps
            image = scene.frame(t, plan["pose"](t), plan["text_at"])
            proc.stdin.write(image.tobytes())
            if on_progress and n % 6 == 0:
                on_progress(n / frames)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() != 0:
            raise RuntimeError(err[-400:] or "FFmpeg failed")
    except BrokenPipeError:
        raise RuntimeError(proc.stderr.read().decode("utf-8", "replace")[-400:] or "FFmpeg stopped early")
    finally:
        if proc.poll() is None:
            proc.kill()
    return {"seconds": plan["seconds"], "frames": frames, "loop": plan["loop"]}
