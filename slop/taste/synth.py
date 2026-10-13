"""Deterministic image synthesis for the taste module — no downloads, no shipped image files.

Used by
  * textfree.py — the rendered text / no-text probes that calibrate the text-free check for `slop taste board`
    (refs for Midjourney --sref must carry no lettering);
  * starter.py  — the generated starter deck (`slop taste pool add --starter`) for users with no references yet.

Fonts: only OFL faces from engine/fonts (Space Grotesk, IBM Plex Mono, JetBrains Mono, Share Tech Mono, Barlow
Condensed, DINish, Instrument Serif, Audiowide, Pilowlava); Nimbus Sans, Junicode, Pilcrow Rounded and Alchimia are
never loaded. When a face is missing (fonts not installed yet) Pillow's built-in default face is used. Every image
is a pure function of its seed, so the same deck / probe set is produced on every machine.
"""
from __future__ import annotations

import colorsys
from functools import lru_cache

import numpy as np

FONT_FILES = {
    "grotesk": ["SpaceGrotesk-Variable.ttf", "Geist-Variable.ttf"],
    "mono": ["IBMPlexMono-Regular.ttf", "JetBrainsMono-Regular.ttf", "ShareTechMono-Regular.ttf"],
    "condensed": ["BarlowCondensed-Medium.ttf", "DINishCondensed-Bold.ttf", "BarlowCondensed-SemiBold.ttf"],
    "din": ["DINish-Bold.ttf"],
    "serif": ["InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf"],
    "display": ["Audiowide-Regular.ttf", "Pilowlava-Regular.otf"],
}
BANNED = ("nimbus", "junicode", "pilcrow", "alchimia")

WORDS = ["signal", "system", "index", "field", "volume", "transit", "archive", "module", "vector", "relay", "static",
         "harbor", "lumen", "north", "cipher", "atlas", "pulse", "meridian", "echo", "kernel", "drift", "parallel",
         "frame", "matter", "station", "circuit", "glass", "season", "radius", "column", "quiet", "metric", "garden",
         "summer", "night", "chorus", "fold", "carbon", "window", "public"]
MICRO = ["REF {a:02d}-{b:03d}", "TOL ±0.{a:02d}", "{a}.{b} MM", "FIG. {a} — SECTION {L}-{L}", "LOT {b}{a} · BATCH {a:02d}",
         "SPEC {a}.{b} / REV {L}", "{a:02d}:{b:02d}:{a:02d}", "N {a}°{b:02d}′ E {b}°{a:02d}′", "ITEM {b} OF {a}",
         "VOL. {a} NO. {b}", "{L}{L}-{b:03d}", "SCALE 1:{b}"]


def font_path(style: str):
    """the first available OFL face of a style, or None"""
    from ..config import engine_dir
    d = engine_dir() / "fonts"
    for name in FONT_FILES.get(style, []):
        p = d / name
        if p.is_file() and not any(b in name.lower() for b in BANNED):
            return p
    return None


@lru_cache(maxsize=256)
def font(style: str, size: int):
    from PIL import ImageFont
    p = font_path(style)
    if p is not None:
        try:
            return ImageFont.truetype(str(p), int(size))
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=int(size))
    except TypeError:          # Pillow < 10.1: fixed-size bitmap face
        return ImageFont.load_default()


def hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


def word(rng, case: str = "upper") -> str:
    w = WORDS[int(rng.integers(len(WORDS)))]
    return w.upper() if case == "upper" else (w.title() if case == "title" else w)


def headline(rng, n_words: int | None = None, case: str = "upper") -> str:
    n = n_words or int(rng.integers(1, 4))
    return " ".join(word(rng, case) for _ in range(n))


def micro_line(rng) -> str:
    t = MICRO[int(rng.integers(len(MICRO)))]
    L = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return t.format(a=int(rng.integers(1, 60)), b=int(rng.integers(10, 999)), L=L[int(rng.integers(len(L)))])


# ---------------------------------------------------------------- grounds

def ground_blur(rng, size, colours, base=None, radius_frac=0.09):
    """soft colour blobs on a base colour, heavily blurred (a 'photographic' out-of-focus ground)"""
    from PIL import Image, ImageDraw, ImageFilter
    w, h = size
    base = base or colours[0]
    im = Image.new("RGB", size, tuple(base))
    d = ImageDraw.Draw(im)
    for _ in range(int(rng.integers(3, 7))):
        c = colours[int(rng.integers(len(colours)))]
        rx, ry = rng.uniform(0.15, 0.45) * w, rng.uniform(0.15, 0.5) * h
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=tuple(c))
    return im.filter(ImageFilter.GaussianBlur(max(2, radius_frac * w)))


def ground_gradient(size, c1, c2, vertical: bool = True):
    from PIL import Image
    w, h = size
    t = np.linspace(0, 1, h if vertical else w)
    ramp = (np.array(c1, float)[None, :] * (1 - t)[:, None] + np.array(c2, float)[None, :] * t[:, None])
    arr = np.repeat(ramp[:, None, :], w, 1) if vertical else np.repeat(ramp[None, :, :], h, 0)
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def add_grain(im, rng, amount: float = 10.0):
    from PIL import Image
    a = np.asarray(im, dtype=float)
    a = a + rng.normal(0, amount, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


def halftone(im, rng, cell: int = 10, ink=(20, 20, 20), paper=(240, 236, 226)):
    """a dot screen of the image's luminance"""
    from PIL import Image, ImageDraw
    g = np.asarray(im.convert("L"), dtype=float) / 255
    out = Image.new("RGB", im.size, paper)
    d = ImageDraw.Draw(out)
    h, w = g.shape
    for y in range(cell // 2, h, cell):
        for x in range(cell // 2, w, cell):
            r = (1 - g[y, x]) * cell * 0.62
            if r > 0.4:
                d.ellipse([x - r, y - r, x + r, y + r], fill=ink)
    return out


# ---------------------------------------------------------------- shapes and type

def shapes(d, rng, size, colours, n: int | None = None, outline_only: bool = False):
    w, h = size
    for _ in range(n if n is not None else int(rng.integers(2, 5))):
        c = tuple(colours[int(rng.integers(len(colours)))])
        k = int(rng.integers(3))
        x0, y0 = rng.uniform(0, w * 0.8), rng.uniform(0, h * 0.8)
        x1, y1 = x0 + rng.uniform(0.08, 0.35) * w, y0 + rng.uniform(0.08, 0.35) * h
        if k == 0:
            d.rectangle([x0, y0, x1, y1], outline=c if outline_only else None, fill=None if outline_only else c,
                        width=max(1, int(w / 400)))
        elif k == 1:
            d.ellipse([x0, y0, x0 + (x1 - x0), y0 + (x1 - x0)], outline=c if outline_only else None,
                      fill=None if outline_only else c, width=max(1, int(w / 400)))
        else:
            d.line([x0, y0, x1, y1], fill=c, width=max(1, int(rng.integers(1, 5))))


def text_block(d, rng, xy, lines: list[str], style: str, size: int, fill, leading: float = 1.25, track: int = 0):
    f = font(style, size)
    x, y = xy
    for ln in lines:
        if track:
            cx = x
            for ch in ln:
                d.text((cx, y), ch, font=f, fill=fill)
                cx += d.textlength(ch, font=f) + track
        else:
            d.text((x, y), ln, font=f, fill=fill)
        y += int(size * leading)
    return y


def luminance(c) -> float:
    r, g, b = (x / 255 for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ink_for(bg) -> tuple[int, int, int]:
    return (243, 241, 234) if luminance(bg) < 0.55 else (18, 18, 18)
