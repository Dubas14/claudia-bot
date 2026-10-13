"""Synthetic fixtures for the taste tests: tiny projects, generated images, a deterministic fake embedder,
fake OpenType fonts (a 'name' table only) and a simulated tapper. Nothing here touches the network."""
from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

DIM = 32


def make_project(root: Path, name: str = "demo") -> Path:
    p = Path(root) / name
    (p / "lyrics").mkdir(parents=True, exist_ok=True)
    (p / "project.json").write_text(json.dumps({"name": name, "title": name, "tier": "quick", "look": {}}), encoding="utf-8")
    return p


def image(kind: str, seed: int, size=(640, 480)) -> Image.Image:
    """kinds: grey (near-mono, quiet), red (red accent), colour (saturated multi-hue), stripes (text-like rows),
    blue, dark, light"""
    rng = np.random.default_rng(seed)
    w, h = size
    if kind == "grey":
        v = 90 + 60 * rng.random()
        arr = np.clip(rng.normal(v, 18, (h, w, 1)).repeat(3, 2), 0, 255)
        im = Image.fromarray(arr.astype("uint8"))
        d = ImageDraw.Draw(im)
        for _ in range(3):
            x0, y0 = int(rng.integers(0, w - 80)), int(rng.integers(0, h - 80))
            d.rectangle([x0, y0, x0 + 60, y0 + 50], outline=(220, 220, 220), width=2)
        return im
    if kind == "red":
        base = 40 + 20 * rng.random()
        arr = np.full((h, w, 3), base)
        y0, x0 = int(rng.integers(0, h * 2 // 3)), int(rng.integers(0, w * 2 // 3))
        arr[y0: y0 + h // 8, x0: x0 + w // 3] = [210, 30 + 20 * rng.random(), 30]
        return Image.fromarray(np.clip(arr + rng.normal(0, 6, arr.shape), 0, 255).astype("uint8"))
    if kind == "colour":
        arr = np.zeros((h, w, 3))
        hues = rng.random(4)
        for k, hu in enumerate(hues):
            c = np.array(Image.new("HSV", (1, 1), (int(hu * 255), 230, 230)).convert("RGB").getpixel((0, 0)), float)
            arr[:, k * w // 4:(k + 1) * w // 4] = c
        return Image.fromarray(np.clip(arr + rng.normal(0, 8, arr.shape), 0, 255).astype("uint8"))
    if kind == "blue":
        arr = np.full((h, w, 3), [30, 60, 200], float)
        return Image.fromarray(np.clip(arr + rng.normal(0, 10, arr.shape), 0, 255).astype("uint8"))
    if kind == "stripes":
        im = Image.new("RGB", size, (235, 232, 225))
        d = ImageDraw.Draw(im)
        for r in range(20, h - 20, 14):
            x = 30
            while x < w - 60:
                ln = int(rng.integers(10, 50))
                d.rectangle([x, r, x + ln, r + 6], fill=(20, 20, 20))
                x += ln + 8
        return im
    if kind == "dark":
        return Image.fromarray(np.clip(rng.normal(25, 8, (h, w, 3)), 0, 255).astype("uint8"))
    if kind == "light":
        return Image.fromarray(np.clip(rng.normal(225, 8, (h, w, 3)), 0, 255).astype("uint8"))
    raise ValueError(kind)


def write_images(d: Path, spec: dict[str, int], start_seed: int = 0) -> list[Path]:
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    out, s = [], start_seed
    for kind, n in spec.items():
        for k in range(n):
            p = d / f"{kind}-{k:03d}.png"
            image(kind, s).save(p)
            out.append(p)
            s += 1
    return out


class FakeEmbedder:
    """deterministic 'vision model': colour / saturation / stripe-energy / fine-detail features + a fixed random
    projection of a thumbnail. Text: known words map onto the matching feature directions (lettering words onto the
    stripe and fine-detail directions, so rendered type reads as text)."""
    provider = "local"

    def __init__(self, model: str = "fake-siglip", tag: str | None = None):
        self.model = model
        self.tag = tag or f"local-{model}-p576"
        self.calib = None
        self.rng = np.random.default_rng(123)
        self.P = self.rng.normal(0, 1, (8 * 8 * 3, DIM - 9))
        self.image_calls = 0
        self.text_calls = 0

    def _feat(self, im: Image.Image) -> np.ndarray:
        im = im.convert("RGB")
        a = np.asarray(im.resize((64, 64)), dtype=float) / 255
        hsv = np.asarray(im.resize((64, 64)).convert("HSV"), dtype=float) / 255
        sat = hsv[..., 1].mean()
        r, g, b = a[..., 0].mean(), a[..., 1].mean(), a[..., 2].mean()
        rows = np.abs(np.diff(a.mean(2), axis=0)).mean()
        from PIL import ImageFilter
        gim = im.convert("L").resize((512, max(1, round(512 * im.height / max(1, im.width)))))
        hp = np.abs(np.asarray(gim, dtype=float) - np.asarray(gim.filter(ImageFilter.GaussianBlur(1.5)), dtype=float))
        detail = float((hp > 25).mean()) * 8                      # dense strong strokes (lettering), not pixel noise
        f = np.array([r - (g + b) / 2, b - (r + g) / 2, sat, rows * 4, a.mean(), 1 - sat, g - (r + b) / 2, 0.2, detail])
        th = np.asarray(im.resize((8, 8)), dtype=float).ravel() / 255 - 0.5
        v = np.concatenate([f * 3, 0.6 * th @ self.P / 8])
        return v / (np.linalg.norm(v) + 1e-12)

    def embed_images(self, paths):
        self.image_calls += 1
        return [self._feat(Image.open(p)) for p in paths]

    def embed_texts(self, texts):
        self.text_calls += 1
        out = []
        for t in texts:
            v = np.zeros(DIM)
            tl = t.lower()
            if "no text" in tl or "without" in tl or tl in ("a landscape", "a texture", "a picture of an object"):
                v[7] = 1                                   # the constant direction: a text-free baseline
                out.append(v)
                continue
            if "red" in tl:
                v[0] = 1
            if "blue" in tl:
                v[1] = 1
            if "colorful" in tl or "neon" in tl:
                v[2] = 1
            if re.search(r"\b(text|letter\w*|typograph\w*|headline|writing|words)\b", tl):
                v[3] = 1
                v[8] = 1
            if "black and white" in tl or "grainy" in tl:
                v[5] = 1
            if not v.any():
                h = int(hashlib.sha1(tl.encode()).hexdigest(), 16) % (DIM - 9)   # stable across runs
                v[9 + h] = 1
                v[4] = 0.3
            out.append(v / np.linalg.norm(v))
        return np.stack(out)


def fake_font(path: Path, family: str, style: str = "Regular") -> Path:
    """a minimal sfnt with only a Windows-platform 'name' table (enough for slop.taste.fonts.sfnt_names)"""
    recs = [(1, family), (2, style)]
    strings = b""
    rows = []
    for nid, s in recs:
        b = s.encode("utf-16-be")
        rows.append(struct.pack(">HHHHHH", 3, 1, 0x409, nid, len(b), len(strings)))
        strings += b
    name = struct.pack(">HHH", 0, len(recs), 6 + 12 * len(recs)) + b"".join(rows) + strings
    off = 12 + 16
    data = struct.pack(">4sHHHH", b"\x00\x01\x00\x00", 1, 16, 0, 0) + \
        struct.pack(">4sIII", b"name", 0, off, len(name)) + name
    Path(path).write_bytes(data)
    return Path(path)


def simulate_taps(feed, prefer, n: int, rng=None, pair_rule=None, flip: float = 0.0) -> list[dict]:
    """answer n feed cards: like iff prefer(item_id) (with probability `flip` of a random flip)"""
    import random
    rng = rng or random.Random(0)
    log = []
    queue: list[dict] = []
    while len(log) < n:
        if not queue:
            queue = feed.next([])["cards"]
            if not queue:
                break
        c = queue.pop(0)
        if c["type"] == "single":
            like = prefer(c["item"])
            if rng.random() < flip:
                like = not like
            feed.record_tap({"item": c["item"], "action": "like" if like else "pass", "why": c["why"],
                             "score": c["score"], "dwell_ms": 900})
            log.append(c)
        else:
            a, b = c["a"]["id"], c["b"]["id"]
            pa, pb = prefer(a), prefer(b)
            w = "a" if pa and not pb else ("b" if pb and not pa else rng.choice(["a", "b"]))
            feed.record_pair({"a": a, "b": b, "winner": w, "shown": "ab", "layout": "row"})
            log.append(c)
        feed.refit()
    return log


def fake_pool(pdir: Path, clusters: int = 4, per: int = 40, d: int = DIM, seed: int = 0, spread: float = 0.5,
              unembedded: int = 0):
    """pool rows + a vector store without image files (fast feed tests). -> (ids, cluster labels)"""
    from slop.taste.embed import save_store
    from slop.taste.store import append_jsonl, pool_index
    rng = np.random.default_rng(seed)
    C = rng.normal(size=(clusters, d))
    ids, labs, vecs = [], [], []
    for c in range(clusters):
        for k in range(per):
            iid = f"img-c{c}-{k:03d}"
            v = C[c] + spread * rng.normal(size=d)
            ids.append(iid)
            labs.append(c)
            vecs.append(v / np.linalg.norm(v))
            append_jsonl(pool_index(pdir), {"id": iid, "kind": "human", "src": "dir", "w": 800, "h": 600,
                                            "sha1": f"{c}{k:039d}", "title": f"c{c}"})
    for k in range(unembedded):
        append_jsonl(pool_index(pdir), {"id": f"img-new-{k:03d}", "kind": "human", "src": "dir", "w": 600, "h": 800,
                                        "sha1": f"n{k:039d}"})
    save_store(pdir, ids, np.stack(vecs), {"provider": "local", "model": "fake", "tag": "local-fake-p576", "dim": d})
    return ids, np.array(labs)
