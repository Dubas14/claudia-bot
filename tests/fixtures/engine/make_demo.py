"""Regenerate the synthetic media of tests/fixtures/engine/demo-project (plates, depth map) and write its song.

    python tests/fixtures/engine/make_demo.py            # rewrite plates/*.jpg + plates/grad-b.depth.png
    write_audio(path)                                    # (tests) an 8 s 120 BPM click track + sine "vocal" notes

Everything is deterministic and synthetic: gradients with one soft dark disc as the "subject", a radial depth map
(near = bright) at the disc, clicks on every beat (accented downbeats) and a sine tone under each sung word.
"""
from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path

DEMO = Path(__file__).resolve().parent / "demo-project"
SR = 44100
DUR = 8.0
BPM = 120.0
PLATES = {  # name: (top colour, bottom colour, subject centre u, v, radius as a fraction of height)
    "grad-a": ((214, 112, 72), (40, 24, 60), .64, .48, .30),
    "grad-b": ((40, 92, 168), (230, 214, 190), .30, .52, .28),
    "grad-c": ((22, 70, 52), (210, 220, 120), .52, .45, .24),
}
SIZE = (1280, 720)


def _plate(top, bot, u, v, r):
    from PIL import Image, ImageDraw, ImageFilter
    w, h = SIZE
    img = Image.new("RGB", SIZE)
    px = img.load()
    for y in range(h):
        k = y / (h - 1)
        for x in range(w):
            q = .85 * k + .15 * x / (w - 1)
            px[x, y] = tuple(int(top[i] + (bot[i] - top[i]) * q) for i in range(3))
    disc = Image.new("L", SIZE, 0)
    ImageDraw.Draw(disc).ellipse([u * w - r * h, v * h - r * h, u * w + r * h, v * h + r * h], fill=255)
    disc = disc.filter(ImageFilter.GaussianBlur(6))
    dark = Image.new("RGB", SIZE, (18, 16, 20))
    return Image.composite(dark, img, disc)


def _depth(u, v, r):
    from PIL import Image
    w, h = SIZE[0] // 2, SIZE[1] // 2
    img = Image.new("L", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = math.hypot(x / w - u, (y / h - v) * h / w) / (r * h / w * 1.4)
            px[x, y] = int(255 * max(.12, min(1.0, 1.05 - .75 * d)) * (.55 + .45 * y / h))
    return img


def write_plates(root: Path = DEMO) -> None:
    (root / "plates").mkdir(parents=True, exist_ok=True)
    for name, (top, bot, u, v, r) in PLATES.items():
        _plate(top, bot, u, v, r).save(root / "plates" / f"{name}.jpg", quality=86)
    _, _, u, v, r = PLATES["grad-b"]
    _depth(u, v, r).save(root / "plates" / "grad-b.depth.png")


def write_audio(path: Path, words: dict | None = None) -> Path:
    """8 s stereo 16-bit 44.1 kHz: a click on every beat at 120 BPM (downbeats louder) + a sine note per sung word."""
    if words is None:
        words = json.loads((DEMO / "analysis" / "words.json").read_text(encoding="utf-8"))
    n = int(SR * DUR)
    sig = [0.0] * n
    beat = 60.0 / BPM
    for b in range(int(DUR / beat) + 1):
        t0 = b * beat
        amp = .55 if b % 4 == 0 else .3
        for i in range(int(.03 * SR)):
            j = int(t0 * SR) + i
            if j < n:
                sig[j] += amp * math.exp(-i / (.006 * SR)) * math.sin(2 * math.pi * 1800 * i / SR)
    notes = [220.0, 261.6, 293.7, 329.6, 392.0]
    for k, wd in enumerate(words.get("words", [])):
        f = notes[k % len(notes)]
        a, b = int(wd["t0"] * SR), min(n, int(wd["t1"] * SR))
        for j in range(a, b):
            env = min(1.0, (j - a) / (.02 * SR), (b - j) / (.02 * SR))
            sig[j] += .22 * env * math.sin(2 * math.pi * f * (j - a) / SR)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wv:
        wv.setnchannels(2)
        wv.setsampwidth(2)
        wv.setframerate(SR)
        frames = bytearray()
        for s in sig:
            v = int(max(-1.0, min(1.0, s)) * 32000)
            frames += struct.pack("<hh", v, v)
        wv.writeframes(bytes(frames))
    return path


if __name__ == "__main__":
    write_plates()
    print("plates written to", DEMO / "plates")
