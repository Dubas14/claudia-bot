"""Per-image colour / luminance / composition statistics for the taste tokens (cached in taste/stats.json).

Colour code is the EV taste audit's own (recovered verbatim in research 11-gap-5 §2.3):
  * 64x64 RGB (PIL resize) -> PIL HSV on 0-255; mean saturation = S.mean()/255; near-mono <=> < 0.12;
  * colour pixels: S > 90 and V > 60 (0-255); an image "shows colour" if they are >= 2 % of its pixels;
  * hue histogram edges [0,15,40,65,150,190,250,285,330,360] -> red (first + last bin), orange, yellow, green, cyan,
    blue, purple, magenta; the dominant hue = argmax;
  * Rec.709 luminance on the 64x64 image: mean, std (contrast), share < 0.2 (dark fraction);
  * ground luminance = mean of an L-mode 128-px draft / 255 (canon.py); dark < 0.35, light > 0.65.
Composition features (new, descriptive, always status "hypothesis"): edge energy, quiet share (negative space),
centre of visual mass, left-right symmetry and the share of edge energy per third, on a 128-px greyscale.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

HUE_EDGES = [0, 15, 40, 65, 150, 190, 250, 285, 330, 360]
HUE_NAMES = ["red", "orange", "yellow", "green", "cyan", "blue", "purple", "magenta"]
NEAR_MONO = 0.12
COLOUR_S, COLOUR_V, COLOUR_MIN = 90, 60, 0.02
DARK, LIGHT = 0.35, 0.65
VERSION = 1


def _hex(rgb) -> str:
    r, g, b = (int(max(0, min(255, round(float(x))))) for x in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def compute(path: Path) -> dict:
    from PIL import Image
    im = Image.open(path).convert("RGB")
    small = im.resize((64, 64))
    hsv = np.asarray(small.convert("HSV"), dtype=float)
    a = np.asarray(small, dtype=float) / 255
    L = a @ np.array([.2126, .7152, .0722])
    S, V = hsv[..., 1], hsv[..., 2]
    h = hsv[..., 0] / 255 * 360
    m = (S > COLOUR_S) & (V > COLOUR_V)
    colour_frac = float(m.mean())
    out = {"v": VERSION, "sat": round(float(S.mean() / 255), 4), "sat_frac": round(float((S / 255 > 0.35).mean()), 4),
           "colour_frac": round(colour_frac, 4), "coloured": colour_frac >= COLOUR_MIN,
           "lum": round(float(L.mean()), 4), "lum_std": round(float(L.std()), 4),
           "dark_frac": round(float((L < 0.2).mean()), 4), "hue": None, "hue_counts": None, "accent_hex": None}
    if m.any():
        c = np.histogram(h[m], bins=HUE_EDGES)[0]
        c = np.array([c[0] + c[8], c[1], c[2], c[3], c[4], c[5], c[6], c[7]])
        out["hue_counts"] = [int(x) for x in c]
        out["red_share"] = round(float(c[0] / max(1, c.sum())), 4)
        out["orange_share"] = round(float(c[1] / max(1, c.sum())), 4)
        if out["coloured"]:
            k = int(np.argmax(c))
            out["hue"] = HUE_NAMES[k]
            lo, hi = HUE_EDGES[k], HUE_EDGES[k + 1]
            sel = m & (((h >= lo) & (h < hi)) | (((h >= 330) | (h < 15)) if k == 0 else False))
            if sel.any():
                out["accent_hex"] = _hex(np.median(np.asarray(small, dtype=float)[sel], axis=0))
    # ground luminance: an L-mode 128-px draft (canon.py lum)
    g_im = Image.open(path)
    g_im.draft("L", (128, 128))
    g = np.asarray(g_im.convert("L").resize((128, 128)), dtype=float) / 255
    out["ground_lum"] = round(float(g.mean()), 4)
    # paper / ink candidates (graphics only): the light and dark ends of the image
    rgb = np.asarray(small, dtype=float)
    light, dark = L > 0.8, L < 0.15
    out["light_hex"] = _hex(rgb[light].mean(0)) if light.mean() > 0.05 else None
    out["dark_hex"] = _hex(rgb[dark].mean(0)) if dark.mean() > 0.05 else None
    # composition (descriptive)
    gx = np.abs(np.diff(g, axis=1))[:-1, :]
    gy = np.abs(np.diff(g, axis=0))[:, :-1]
    e = gx + gy
    tot = float(e.sum()) + 1e-9
    out["edge"] = round(float(e.mean()), 4)
    cells = e[:120, :120].reshape(15, 8, 15, 8).mean(axis=(1, 3))
    out["quiet"] = round(float((cells < 0.02).mean()), 4)
    ys, xs = np.mgrid[0:e.shape[0], 0:e.shape[1]]
    out["mass_x"] = round(float((e * xs).sum() / tot / e.shape[1]), 4)
    out["mass_y"] = round(float((e * ys).sum() / tot / e.shape[0]), 4)
    out["symmetry"] = round(float(1 - np.abs(g - g[:, ::-1]).mean()), 4)
    t = e.shape[0] // 3
    out["thirds_v"] = [round(float(e[i * t:(i + 1) * t].sum() / tot), 3) for i in range(3)]
    t2 = e.shape[1] // 3
    out["thirds_h"] = [round(float(e[:, i * t2:(i + 1) * t2].sum() / tot), 3) for i in range(3)]
    out["aspect"] = round(im.width / max(1, im.height), 4)
    return out


def stats_for(pdir: Path, items: dict, ids: list[str]) -> dict[str, dict]:
    """cached per id+sha1 in taste/stats.json"""
    from .pool import image_path
    from .store import read_json, taste_dir, write_json
    cf = taste_dir(pdir) / "stats.json"
    cache = read_json(cf, {}) or {}
    out, dirty = {}, False
    for i in ids:
        it = items.get(i)
        if not it:
            continue
        key = f"{i}:{it.get('sha1', '')}"
        s = cache.get(key)
        if not s or s.get("v") != VERSION:
            p = image_path(pdir, it)
            if not p.exists():
                continue
            try:
                s = compute(p)
            except Exception:  # noqa: BLE001 — a broken file must not stop the report
                continue
            cache[key] = s
            dirty = True
        out[i] = s
    if dirty:
        write_json(cf, cache)
    return out
