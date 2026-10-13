"""The starter deck (`slop taste pool add --starter`): a cold-start pool for a user who has no references yet.

Research 11-gap-5 §6.5 Tier 3 asks for a shipped, licensed, deliberately diverse starter deck that includes
anti-modes (neon, y2k, chrome type) so the owner can pass on them. This toolkit GENERATES the deck locally instead
of shipping or downloading images: museum / archive sets need per-source licence checks, the box's network
allow-list is narrow, and binary assets bloat the template. The deck is deterministic (seeded), drawn with OFL
fonts from engine/fonts only (synth.py), and is CC0 by construction (no third-party image content).

16 templates x 20 variants = 320 images (research: a 150-tap session needs ~300-400 candidates), written in
round-robin template order so any `--max N` prefix stays stratified. The pool's near-duplicate rule drops ~20 of the
sparsest swatches (minimal fields, flat colour fields), leaving ~300; rendering takes ~10 s, SigLIP 2 base on CPU
embeds them in ~1 min (measured: 299 images, 5 img/s on 16 threads). Each template varies ground (dark / light /
colour), colour restraint (mono, mono + one accent, limited, colourful), density and type. Anti-modes included:
neon-flyer, y2k-chrome, glossy-3d, pastel-playful, dense-collage. Items get kind `composed` (their own intercept in
the model, so the swatches' like-rate does not bias the user's real references) and group `starter:<template>`
(so `slop taste tokens` can report a template the owner keeps passing as an anti-source).

What it can and cannot measure: colour restraint, ground, density, type style and the broad "modes" — the
system-level tokens. It cannot stand in for real references (imagery, subject matter, craft): ask the user for
their own Are.na channels or a folder of saved references as soon as they have them.
"""
from __future__ import annotations

import io
import math

import numpy as np

from . import synth as Y

PER_TEMPLATE = 20
SIZES = [(1024, 768), (816, 1024), (1024, 1024), (1024, 576)]
ACCENTS = [0.0, 0.03, 0.08, 0.13, 0.33, 0.55, 0.6, 0.83, 0.92]          # red, red-orange, orange, yellow, green, ...
PAPER = [(242, 238, 228), (250, 250, 248), (232, 228, 216), (222, 222, 220)]
INK = [(18, 18, 18), (30, 30, 34), (14, 16, 22)]


def _palette(rng, scheme: str, dark: bool):
    bg = INK[int(rng.integers(len(INK)))] if dark else PAPER[int(rng.integers(len(PAPER)))]
    fg = Y.ink_for(bg)
    acc = Y.hsv(ACCENTS[int(rng.integers(len(ACCENTS)))], rng.uniform(0.75, 0.95), rng.uniform(0.8, 0.95))
    if scheme == "mono":
        cols = [fg, (128, 128, 128)]
    elif scheme == "accent":
        cols = [fg, acc]
    elif scheme == "limited":
        h = rng.random()
        cols = [fg, Y.hsv(h, 0.7, 0.85), Y.hsv(h + 0.5, 0.6, 0.8)]
    else:
        cols = [Y.hsv(rng.random(), rng.uniform(0.6, 1), rng.uniform(0.7, 1)) for _ in range(5)]
    return bg, fg, acc, cols


def _scheme(rng) -> str:
    return ["mono", "accent", "accent", "limited", "colourful"][int(rng.integers(5))]


# ---------------------------------------------------------------- templates: (rng, size) -> PIL image

def swiss_grid(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg, fg, acc, cols = _palette(rng, _scheme(rng), rng.random() < 0.3)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    nx = int(rng.integers(4, 9))
    for i in range(1, nx):
        d.line([i * w / nx, 0, i * w / nx, h], fill=tuple(int(x * 0.6 + y * 0.4) for x, y in zip(bg, fg)), width=1)
    bx = int(rng.integers(0, nx - 1)) * w / nx
    d.rectangle([bx, h * rng.uniform(0.05, 0.5), bx + w / nx * int(rng.integers(1, 3)), h * rng.uniform(0.55, 0.95)],
                fill=cols[-1] if len(cols) > 2 else acc)
    Y.text_block(d, rng, (w * 0.05, h * rng.uniform(0.05, 0.6)), [Y.headline(rng, 1), Y.headline(rng, 1)],
                 "grotesk", int(w * rng.uniform(0.07, 0.13)), fg, leading=1.0)
    Y.text_block(d, rng, (w * 0.05, h * 0.86), [Y.micro_line(rng) for _ in range(3)], "mono", int(w * 0.013), fg)
    return im


def spec_label(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    yellow = rng.random() < 0.3
    bg = (236, 196, 40) if yellow else PAPER[int(rng.integers(len(PAPER)))]
    if rng.random() < 0.25:
        bg = INK[0]
    fg = Y.ink_for(bg)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    m = w * 0.06
    d.rectangle([m, m, w - m, h - m], outline=fg, width=max(2, w // 300))
    y = m * 1.5
    for _ in range(int(rng.integers(3, 6))):
        d.line([m, y + h * 0.1, w - m, y + h * 0.1], fill=fg, width=max(1, w // 600))
        Y.text_block(d, rng, (m * 1.3, y), [Y.micro_line(rng)], "mono", int(w * rng.uniform(0.016, 0.03)), fg)
        y += h * 0.13
    x = m * 1.3
    while x < w * 0.6:                                    # a barcode
        bw = int(rng.integers(1, 6))
        d.rectangle([x, h - m * 2.6, x + bw, h - m * 1.3], fill=fg)
        x += bw + int(rng.integers(2, 6))
    if rng.random() < 0.6:
        cx, cy, r = w * 0.8, h - m * 2.2, w * 0.06
        d.polygon([(cx, cy - r), (cx + r, cy + r * 0.8), (cx - r, cy + r * 0.8)], outline=fg, width=3)
    return im


def data_diagram(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg, fg, acc, cols = _palette(rng, _scheme(rng), rng.random() < 0.55)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = w * 0.1, h * 0.12, w * 0.92, h * 0.82
    d.line([x0, y1, x1, y1], fill=fg, width=2)
    d.line([x0, y0, x0, y1], fill=fg, width=2)
    for t in range(6):
        tx = x0 + (x1 - x0) * t / 5
        d.line([tx, y1, tx, y1 + 8], fill=fg, width=1)
        d.text((tx - 6, y1 + 12), f"{t * 20}", font=Y.font("mono", int(w * 0.015)), fill=fg)
    kind = int(rng.integers(3))
    n = int(rng.integers(8, 30))
    vals = np.cumsum(rng.normal(0, 1, n))
    vals = (vals - vals.min()) / (np.ptp(vals) + 1e-9)
    xs = x0 + (x1 - x0) * np.linspace(0.02, 0.98, n)
    ys = y1 - (y1 - y0) * (0.1 + 0.8 * vals)
    c = cols[1] if len(cols) > 1 else acc
    if kind == 0:
        d.line(list(zip(xs, ys)), fill=c, width=max(2, w // 300))
    elif kind == 1:
        bw = (x1 - x0) / n * 0.6
        for x, y, k in zip(xs, ys, range(n)):
            d.rectangle([x - bw / 2, y, x + bw / 2, y1], fill=cols[k % len(cols)] if len(cols) > 3 else c)
    else:
        for x, y in zip(xs, ys + rng.normal(0, 20, n)):
            r = rng.uniform(3, 10)
            d.ellipse([x - r, y - r, x + r, y + r], fill=c)
    Y.text_block(d, rng, (x0, h * 0.03), [Y.micro_line(rng)], "mono", int(w * 0.02), fg)
    return im


def technical_drawing(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    blue = rng.random() < 0.4
    bg = (24, 52, 110) if blue else PAPER[int(rng.integers(len(PAPER)))]
    fg = (225, 232, 245) if blue else (40, 40, 44)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    cx, cy = w * rng.uniform(0.35, 0.6), h * rng.uniform(0.35, 0.6)
    for r in sorted(rng.uniform(0.05, 0.3, int(rng.integers(2, 5))) * w):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fg, width=1)
    d.line([cx - w * 0.4, cy, cx + w * 0.4, cy], fill=fg, width=1)
    d.line([cx, cy - h * 0.4, cx, cy + h * 0.4], fill=fg, width=1)
    yy = h * 0.88
    d.line([w * 0.15, yy, w * 0.85, yy], fill=fg, width=1)
    for xx, s in ((w * 0.15, 1), (w * 0.85, -1)):
        d.polygon([(xx, yy), (xx + s * 14, yy - 5), (xx + s * 14, yy + 5)], fill=fg)
    d.text((w * 0.47, yy - 24), f"{int(rng.integers(20, 400))}.{int(rng.integers(0, 9))}", font=Y.font("mono", int(w * 0.016)), fill=fg)
    Y.text_block(d, rng, (w * 0.04, h * 0.04), [Y.micro_line(rng) for _ in range(2)], "mono", int(w * 0.014), fg)
    return Y.add_grain(im, rng, 4)


def minimal_field(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    dark = rng.random() < 0.5
    bg = INK[int(rng.integers(len(INK)))] if dark else PAPER[int(rng.integers(len(PAPER)))]
    if rng.random() < 0.3:
        bg = Y.hsv(rng.random(), rng.uniform(0.2, 0.6), rng.uniform(0.3, 0.8))
    fg = Y.ink_for(bg)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    x, y = w * rng.uniform(0.1, 0.85), h * rng.uniform(0.1, 0.85)
    k = int(rng.integers(3))
    if k == 0:
        r = w * 0.012
        d.ellipse([x - r, y - r, x + r, y + r], fill=fg)
    elif k == 1:
        d.line([x, y, x + w * rng.uniform(0.05, 0.2), y], fill=fg, width=2)
    else:
        d.text((x, y), Y.word(rng, "lower"), font=Y.font("mono", int(w * 0.018)), fill=fg)
    return im


def colour_field(rng, size):
    scheme = _scheme(rng)
    if scheme == "mono":
        g = rng.uniform(0.1, 0.9)
        cols = [Y.hsv(0, 0, max(0.0, min(1.0, g + rng.uniform(-0.3, 0.3)))) for _ in range(4)]
    else:
        h = rng.random()
        spread = 0.08 if scheme in ("accent", "limited") else 0.5
        cols = [Y.hsv(h + rng.uniform(-spread, spread), rng.uniform(0.3, 0.9), rng.uniform(0.3, 1)) for _ in range(5)]
    im = Y.ground_blur(rng, size, cols, radius_frac=rng.uniform(0.05, 0.14))
    return Y.add_grain(im, rng, rng.uniform(0, 9))


def photo_landscape(rng, size):
    from PIL import ImageDraw, ImageFilter
    w, h = size
    dusk = rng.random() < 0.5
    sky1 = Y.hsv(rng.uniform(0.55, 0.65), 0.5, 0.9) if not dusk else Y.hsv(rng.uniform(0.0, 0.1), 0.6, 0.9)
    sky2 = Y.hsv(rng.uniform(0.55, 0.62), 0.3, 1.0) if not dusk else Y.hsv(rng.uniform(0.7, 0.8), 0.5, 0.4)
    im = Y.ground_gradient(size, sky2, sky1)
    d = ImageDraw.Draw(im)
    hz = h * rng.uniform(0.45, 0.75)
    for layer in range(3):
        pts = [(0, h)]
        for x in np.linspace(0, w, 12):
            pts.append((x, hz + layer * h * 0.06 + rng.normal(0, h * 0.04)))
        pts.append((w, h))
        v = 0.15 + 0.15 * layer
        d.polygon(pts, fill=Y.hsv(rng.uniform(0.25, 0.4), 0.3, v))
    im = im.filter(ImageFilter.GaussianBlur(rng.uniform(1, 6)))
    return Y.add_grain(im, rng, 7)


def editorial_serif(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg = PAPER[int(rng.integers(len(PAPER)))]
    fg = (24, 22, 20)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    Y.text_block(d, rng, (w * 0.07, h * 0.06), [Y.headline(rng, 2, "title")], "serif", int(w * rng.uniform(0.07, 0.11)), fg)
    cols = int(rng.integers(2, 4))
    cw = w * 0.86 / cols
    for c in range(cols):
        y = h * 0.3
        while y < h * 0.92:
            ln = cw * rng.uniform(0.6, 0.95)
            d.rectangle([w * 0.07 + c * cw, y, w * 0.07 + c * cw + ln, y + h * 0.006], fill=(110, 106, 100))
            y += h * 0.022
    if rng.random() < 0.6:
        x = w * 0.07 + int(rng.integers(cols)) * cw
        d.rectangle([x, h * 0.32, x + cw * 0.9, h * 0.55], fill=Y.hsv(rng.random(), 0.25, 0.6))
    return im


def neon_flyer(rng, size):
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    w, h = size
    im = Image.new("RGB", size, (6, 4, 12))
    d = ImageDraw.Draw(im)
    neon = [Y.hsv(x, 1.0, 1.0) for x in (0.83, 0.5, 0.15, 0.95, 0.33)]
    for _ in range(int(rng.integers(5, 12))):
        c = neon[int(rng.integers(len(neon)))]
        x0, y0 = rng.uniform(0, w), rng.uniform(0, h)
        d.line([x0, y0, x0 + rng.uniform(-w, w) * 0.5, y0 + rng.uniform(-h, h) * 0.5], fill=c, width=int(rng.integers(4, 14)))
    Y.text_block(d, rng, (w * 0.06, h * rng.uniform(0.2, 0.6)), [Y.headline(rng, 1), Y.headline(rng, 1)], "display",
                 int(w * rng.uniform(0.09, 0.15)), neon[int(rng.integers(len(neon)))], leading=1.0)
    glow = im.filter(ImageFilter.GaussianBlur(w * 0.012))
    return ImageChops.add(im, glow)


def y2k_chrome(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    im = Y.ground_gradient(size, Y.hsv(rng.uniform(0.75, 0.9), 0.35, 1), Y.hsv(rng.uniform(0.45, 0.55), 0.4, 1))
    d = ImageDraw.Draw(im)
    for _ in range(int(rng.integers(3, 7))):                 # glossy bubbles
        r = w * rng.uniform(0.03, 0.12)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        d.ellipse([x - r, y - r, x + r, y + r], fill=Y.hsv(rng.uniform(0.5, 0.9), 0.3, 1))
        d.ellipse([x - r * 0.5, y - r * 0.7, x - r * 0.1, y - r * 0.4], fill=(255, 255, 255))
    # chrome type: a vertical metallic gradient masked by the text
    fs = int(w * rng.uniform(0.1, 0.16))
    mask = Image.new("L", size, 0)
    md = ImageDraw.Draw(mask)
    Y.text_block(md, rng, (w * 0.06, h * rng.uniform(0.25, 0.5)), [Y.headline(rng, 1)], "display", fs, 255)
    t = np.linspace(0, 1, h)[:, None]
    band = 140 + 115 * np.cos(t * math.pi * 6)
    chrome = Image.fromarray(np.clip(np.repeat(np.stack([band, band, band + 10], -1), w, 1), 0, 255).astype("uint8"))
    im.paste(chrome, (0, 0), mask)
    for _ in range(int(rng.integers(4, 10))):               # sparkles
        x, y, r = rng.uniform(0, w), rng.uniform(0, h), w * rng.uniform(0.005, 0.015)
        d.polygon([(x, y - 3 * r), (x + r, y), (x, y + 3 * r), (x - r, y)], fill=(255, 255, 255))
    return im


def glossy_3d(rng, size):
    from PIL import Image
    w, h = size
    im = Y.ground_gradient(size, Y.hsv(rng.random(), 0.5, 0.9), Y.hsv(rng.random(), 0.6, 0.4))
    arr = np.asarray(im, dtype=float).copy()
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(int(rng.integers(1, 4))):
        r = min(w, h) * rng.uniform(0.12, 0.3)
        cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h
        dist2 = ((xx - cx) ** 2 + (yy - cy) ** 2) / r ** 2
        inside = dist2 < 1
        nz = np.sqrt(np.clip(1 - dist2, 0, 1))
        nx_, ny_ = (xx - cx) / r, (yy - cy) / r
        diff = np.clip(0.6 * nz - 0.4 * nx_ - 0.5 * ny_, 0, 1)
        spec = np.clip(nz * 0.7 - 0.5 * nx_ - 0.5 * ny_, 0, 1) ** 24
        base = np.array(Y.hsv(rng.random(), rng.uniform(0.4, 0.9), 0.95), float)
        shade = base[None, None, :] * (0.25 + 0.75 * diff[..., None]) + 255 * spec[..., None]
        arr[inside] = shade[inside]
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def pastel_playful(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg = Y.hsv(rng.random(), 0.15, 1.0)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    for _ in range(int(rng.integers(5, 10))):
        c = Y.hsv(rng.random(), rng.uniform(0.25, 0.45), 1.0)
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        rw, rh = w * rng.uniform(0.05, 0.2), h * rng.uniform(0.05, 0.2)
        d.rounded_rectangle([x, y, x + rw, y + rh], radius=min(rw, rh) / 2, fill=c)
    for _ in range(2):                                      # wavy lines
        y0 = rng.uniform(0.2, 0.8) * h
        pts = [(x, y0 + h * 0.03 * math.sin(x / w * 12 + rng.random() * 6)) for x in np.linspace(0, w, 60)]
        d.line(pts, fill=Y.hsv(rng.random(), 0.5, 0.9), width=8)
    Y.text_block(d, rng, (w * 0.1, h * 0.4), [Y.word(rng, "lower") + "!"], "display", int(w * 0.1),
                 Y.hsv(rng.random(), 0.6, 0.7))
    return im


def halftone_print(rng, size):
    w, h = size
    src = Y.ground_blur(rng, size, [Y.hsv(0, 0, rng.uniform(0, 1)) for _ in range(4)], radius_frac=0.06)
    ink = INK[0] if rng.random() < 0.6 else Y.hsv(ACCENTS[int(rng.integers(len(ACCENTS)))], 0.85, 0.8)
    return Y.halftone(src, rng, cell=int(rng.integers(8, 16)), ink=ink, paper=PAPER[int(rng.integers(len(PAPER)))])


def dense_collage(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg, fg, acc, cols = _palette(rng, "colourful" if rng.random() < 0.6 else "limited", rng.random() < 0.4)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    for _ in range(int(rng.integers(18, 40))):
        c = cols[int(rng.integers(len(cols)))]
        x, y = rng.uniform(-0.1, 0.95) * w, rng.uniform(-0.1, 0.95) * h
        d.rectangle([x, y, x + w * rng.uniform(0.05, 0.3), y + h * rng.uniform(0.03, 0.25)], fill=c)
    for _ in range(int(rng.integers(4, 9))):
        tile = Image.new("RGBA", (int(w * 0.5), int(h * 0.12)), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        td.text((4, 4), Y.headline(rng, 2), font=Y.font(["grotesk", "serif", "mono", "display"][int(rng.integers(4))],
                                                         int(h * rng.uniform(0.03, 0.07))), fill=fg)
        tile = tile.rotate(rng.uniform(-30, 30), expand=True)
        im.paste(tile, (int(rng.uniform(0, w * 0.7)), int(rng.uniform(0, h * 0.85))), tile)
    return Y.add_grain(im, rng, 6)


def big_type(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg, fg, acc, cols = _palette(rng, _scheme(rng), rng.random() < 0.5)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    style = ["grotesk", "condensed", "din", "serif", "mono"][int(rng.integers(5))]
    single = rng.random() < 0.4
    text = Y.word(rng)[0] if single else Y.word(rng)
    fs = int(h * (0.9 if single else rng.uniform(0.22, 0.4)))
    colour = acc if rng.random() < 0.35 else fg
    d.text((w * rng.uniform(-0.05, 0.1), h * rng.uniform(-0.05, 0.3)), text, font=Y.font(style, fs), fill=colour)
    return im


def pattern(rng, size):
    from PIL import Image, ImageDraw
    w, h = size
    bg, fg, acc, cols = _palette(rng, _scheme(rng), rng.random() < 0.5)
    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    k = int(rng.integers(4))
    c2 = cols[1] if len(cols) > 1 else fg
    if k == 0:                                               # dot grid
        s = int(rng.integers(18, 48))
        for y in range(s // 2, h, s):
            for x in range(s // 2, w, s):
                r = s * rng.uniform(0.12, 0.3)
                d.ellipse([x - r, y - r, x + r, y + r], fill=fg)
    elif k == 1:                                             # stripes
        s = int(rng.integers(10, 40))
        for x in range(-h, w, s * 2):
            d.polygon([(x, 0), (x + s, 0), (x + s + h, h), (x + h, h)], fill=c2)
    elif k == 2:                                             # concentric circles
        cx, cy = w * rng.uniform(0.3, 0.7), h * rng.uniform(0.3, 0.7)
        for r in range(10, int(max(w, h)), int(rng.integers(12, 30))):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fg, width=2)
    else:                                                    # waveforms
        rows = int(rng.integers(8, 20))
        for row in range(rows):
            y0 = h * (0.05 + 0.9 * row / rows)
            f = rng.uniform(4, 20)
            pts = [(x, y0 + h * 0.015 * math.sin(x / w * f + row)) for x in np.linspace(0, w, 120)]
            d.line(pts, fill=c2 if row % 3 == 0 else fg, width=2)
    return im


TEMPLATES = [("swiss-grid", swiss_grid), ("spec-label", spec_label), ("data-diagram", data_diagram),
             ("technical-drawing", technical_drawing), ("minimal-field", minimal_field), ("colour-field", colour_field),
             ("photo-landscape", photo_landscape), ("editorial-serif", editorial_serif), ("neon-flyer", neon_flyer),
             ("y2k-chrome", y2k_chrome), ("glossy-3d", glossy_3d), ("pastel-playful", pastel_playful),
             ("halftone-print", halftone_print), ("dense-collage", dense_collage), ("big-type", big_type),
             ("pattern", pattern)]
ANTI_MODES = ("neon-flyer", "y2k-chrome", "glossy-3d", "pastel-playful", "dense-collage")


def deck(n: int | None = None):
    """yield (id, template name, variant) in round-robin template order (any prefix is stratified)"""
    total = len(TEMPLATES) * PER_TEMPLATE
    for k in range(min(total, n if n is not None else total)):
        t, v = k % len(TEMPLATES), k // len(TEMPLATES)
        yield f"starter-{TEMPLATES[t][0]}-{v:02d}", TEMPLATES[t][0], v


def render(name: str, variant: int):
    t = next(k for k, (nm, _) in enumerate(TEMPLATES) if nm == name)
    rng = np.random.default_rng(7919 * (t + 1) + 104729 * variant)
    size = SIZES[int(rng.integers(len(SIZES)))]
    return dict(TEMPLATES)[name](rng, size).convert("RGB")


def add_starter(writer, limit: int | None = None) -> dict:
    """add the generated deck to the pool (PoolWriter); idempotent (ids are fixed), stratified for any --max"""
    n0 = writer.stats["added"]
    made = 0
    for iid, name, v in deck():
        if limit is not None and writer.stats["added"] - n0 >= limit:
            break
        if writer.known_id(iid):
            writer.stats["duplicate"] += 1
            continue
        buf = io.BytesIO()
        render(name, v).save(buf, "JPEG", quality=90)
        made += 1
        writer.add(buf.getvalue(), {"src": "starter", "kind": "composed", "origin": f"starter:{name}",
                                    "title": f"{name} {v:02d}", "group": f"starter:{name}"}, iid=iid)
    return {"templates": len(TEMPLATES), "deck_size": len(TEMPLATES) * PER_TEMPLATE, "rendered": made,
            "anti_modes": list(ANTI_MODES), "licence": "CC0 (generated locally; OFL fonts)"}
