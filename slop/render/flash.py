"""Flash-safety check (WCAG 2.3.1 general flash threshold) — port of the reference pipeline's flashcheck.py, unchanged.

A flash is a PAIR of opposing changes in relative luminance of at least `delta` (10 % of the range) where the darker
state is below 0.8, over at least `area` (25 %) of the frame. Any 1-second window holding more than `max` (3) flashes
fails. The video is read at 96×54, 24 fps, in linear-light relative luminance. (An early version paired every transition
with the next, so one strobe dark → white → dark counted twice; each change now belongs to one pair only.)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import SlopError


def luminance_frames(path: Path, w: int = 96, h: int = 54, fps: int = 24):
    import numpy as np
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    except FileNotFoundError as e:
        raise SlopError("ffmpeg not found on PATH") from e
    except subprocess.CalledProcessError as e:
        raise SlopError(f"ffmpeg could not read {path}: {e.stderr.decode(errors='replace')[-300:]}") from e
    x = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32) / 255
    lin = np.where(x <= .04045, x / 12.92, ((x + .055) / 1.055) ** 2.4)
    return lin @ np.array([.2126, .7152, .0722], np.float32)          # relative luminance per pixel


def count_flashes(L, fps: int = 24, max_per_s: int = 3, area: float = .25, delta: float = .10) -> dict:
    import numpy as np
    n = len(L)
    if n < 2:
        return {"seconds": round(n / fps, 2), "flashes": 0, "worst_per_second": 0, "limit": max_per_s, "fails": [],
                "pass": True, "flash_times": []}
    # per frame, the share of pixels whose luminance rose / fell by >= delta (with the darker side < .8) since the last frame
    d = L[1:] - L[:-1]
    dark = np.minimum(L[1:], L[:-1]) < .8
    up = ((d >= delta) & dark).mean(axis=(1, 2))
    dn = ((d <= -delta) & dark).mean(axis=(1, 2))
    ev = np.zeros(n - 1, int)
    ev[up >= area] = 1
    ev[dn >= area] = -1                                                   # transitions over a quarter of the frame
    # a flash = a PAIR of opposing changes; same-direction steps with no opposing change between them are one change
    alt: list[int] = []
    for i in np.nonzero(ev)[0]:
        if not alt or ev[alt[-1]] != ev[i]:
            alt.append(int(i))
    tt = (np.array(alt, dtype=float) + 1) / fps                           # the alternating transitions' times
    flashes = tt[::2]                                                     # each flash at its first transition
    worst, fails = 0, []
    for s in np.arange(0, n / fps, 1 / fps):
        c = int(((tt >= s) & (tt < s + 1)).sum()) // 2
        worst = max(worst, c)
        if c > max_per_s and (not fails or s - fails[-1][0] >= 1):
            fails.append((round(float(s), 2), c))
    return {"seconds": round(n / fps, 2), "flashes": int(len(flashes)), "worst_per_second": worst, "limit": max_per_s,
            "fails": fails, "pass": not fails, "flash_times": [round(float(t), 3) for t in flashes]}


def flashcheck(path: Path, max_per_s: int = 3, area: float = .25, delta: float = .10) -> dict:
    path = Path(path)
    if not path.is_file():
        raise SlopError(f"no video at {path} — run `slop render encode` first (or pass --video FILE)")
    out = count_flashes(luminance_frames(path), 24, max_per_s, area, delta)
    out["video"] = str(path)
    return out
