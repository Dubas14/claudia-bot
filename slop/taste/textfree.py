"""Text-free check for mood-board references (`slop taste board` -> refs.json, for Midjourney --sref).

"A reference with lettering teaches Midjourney to letter" (research 05 §5.5, gotcha #17). The retired inspo.py used
EasyOCR CRAFT boxes; the toolkit judges lettering with the pool's own embedder (no OCR dependency).

THE DEFAULT (`assess`, since the real-image validation of the taste-profile track): an IN-POOL PAIRED PROBE.
  1. pick up to 48 backgrounds from the user's own pool — its least text-like FIFTH (a third for pools under 120
     images, 40 % for pools of 40-59), spread over it, ranked by the mean rank of the zero-shot score below and a
     ridge trained on the rendered probes (the zero-shot score alone calls type on flat gradients text-free): a
     background that already carries lettering teaches the probe that lettering is clean (typography-heavy pools);
  2. render a lettered copy of each (a headline, a lyric line in the lower third, or a micro-text block, OFL faces,
     ink from the local luminance; deterministic per image, cached under $SLOP_HOME/cache/textprobe/);
  3. embed the copies with the store's model (cached per image under $SLOP_HOME/cache/embed/<tag>/letter-v1/);
  4. fit a ridge linear probe (dual form, λ = 1) on the embeddings: backgrounds = 0, lettered copies = 1; every pool
     image gets score = probe output (≈ 0 clean … ≈ 1 lettered);
  5. cutoff = the STRICTER of the leave-one-PAIR-out midpoint of the two classes and the leave-one-pair-out 90th
     percentile of the backgrounds (a copy is nearly its background, so plain leave-one-out would predict each row
     from its twin); refs are the images below it.
  Measured with SigLIP 2 base (taste-profile track, 2026-10-01) on 636 real Midjourney images prompted "no text"
  and 166 real lettered images. Read these numbers with care: 127 of the 166 (43 headlines, 42 lower-third lyric
  lines, 42 micro-text blocks over held-out Midjourney plates) were rendered with the SAME generators, OFL fonts and
  ink rule as `render_lettered` (synth.text_block / headline / micro_line), so they flatter the probe; only the 20
  typographic pages and 19 real engine frames with lyric type are independent, and the background-selection rule
  was tuned on those same 19 engine frames:
    * the score: held-out AUC 0.995 (the zero-shot score: 0.758; on the engine frames 1.0 vs 0.30);
    * end to end through `assess` (pool add -> embed -> probe): a text-free pool of 506 kept 74 % (374 refs
      available); a pool with 25 % lettering kept 74 % of the clean images and excluded 100 % of the lettered ones;
      a typography-heavy pool (62 % lettered) kept 89 % and excluded 96 % (headlines and pages 100 %, lyric lines
      93 %, micro text 95 %, engine frames 89 %); the probe step took 3-20 s (24-48 copies embedded once, cached);
    * the zero-shot calibration it replaces put its cutoff (−0.0458) below EVERY real photograph (0 of 509 kept):
      `slop taste board` returned no references at all for a photographic pool.
  An INDEPENDENT re-measure (review round 2: 300 clean Midjourney images; lettering in other fonts — system faces —
  and other forms: centred, vertical, labels, perspective signs, subtitles, script, paragraphs, corner captions)
  holds up: AUC 0.978 with 96 lettered images in the pool and 0.993 with 24 (zero-shot 0.80); 97.9 % / 100 % of the
  lettered images excluded; 70.9 % / 73.9 % of the clean ones kept. THE WEAK CASE is small corner captions and
  watermarks: only 83 % excluded (2 lettered refs among 214) — look at the refs before using them.
  A fourth "corner caption" kind for the copies was tried (fixer round 2, 3 seeds of 300 clean + 40 independent
  corner captions / watermarks in Windows system fonts, some semi-transparent, + 30 centred lines): captions AUC 0.93
  -> 0.97, excluded 95.8 -> 96.7 %, clean kept 63 -> 78 %; but on the builder's pools above it let 1-2 more lyric /
  micro images through (mixed 25 %: 100 -> 99.4 % excluded; typography-heavy: 98.8 -> 97.6 / 98.8 %) and kept fewer
  clean images in a 68-image pool (87 -> 78 %). Not a clear win, so the three kinds stay.
  Small pools (40-71 images, round 2: 40 % backgrounds), with the builder's lettered set above (so partly flattering),
  4 seeds each: 68 = 60 clean + 8
  lettered kept 82.5 % / excluded 100 % (the zero-shot fallback they used before kept 0 %); 46 = 40 + 6: 86.7 % /
  100 %; 50 with 24 % lettering: 90.8 % / 93.8 % (3 lettered refs among 141); 64 with 38 %: 90.6 % / 96.8 % (3 of
  148).
  Fallback: a pool under 40 images (fewer than 16 backgrounds), or copies that cannot be embedded -> the zero-shot
  policy below (`cutoff`), which is safe but strict: on photographs it can leave no refs at all (the board says so,
  prints the score range and a suggested value). An explicit `--text-max X` is an absolute cutoff on the score in
  use (probe: about 0 clean, about 1 lettered; zero-shot: about −0.05..+0.05) and is refused when it would let
  lettering through: zero-shot above the pool's least text-like third, probe at or above the lettered copies'
  median score (review round 2: "--text-max 0.5" on the zero-shot scale put 8 of 8 lettered images into refs.json).

The zero-shot score (kept for picking the backgrounds, the fallback and the functions below):

  score = max cosine to the text prompts − max cosine to the no-text prompts      (higher = more text-like)

Review round 1 found that the score separates lettered from clean images perfectly (AUC 1.0 on rendered headline /
micro-text images with SigLIP 2 base) but sits below 0 for nearly all of them (medians −0.019 / −0.022 vs −0.046), so
the old fixed cutoff "< 0" let 86-95 % of lettered images through. The cutoff is now the STRICTER of
  * a calibrated cutoff: the lowest score among rendered lettered probes (headline and micro-text blocks in OFL
    faces on blurred grounds with shapes, 2 x 12 images) embedded by the same model, so even the faintest probe
    lettering falls above it; computed once per embedding model and cached under $SLOP_HOME/cache/embed/<tag>/.
    Measured with SigLIP 2 base on a separate rendered set (64 px headlines, 18 px micro blocks): 100 % of the
    lettered images excluded, 95 % of the clean ones kept (the 5th percentile instead let 2 % of lettering through);
  * a pool-relative cutoff: the least text-like third of the user's pool (`POOL_SHARE`), so a pool that is mostly
    typography still yields only its cleanest images.
If the probes cannot be embedded, the pool-relative cutoff alone is used at the stricter `FALLBACK_SHARE`.
(`cutoff` keeps this zero-shot policy for direct callers; `slop taste board` uses `assess`.) refs.json records the
cutoff and how it was chosen.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import synth as Y

TEXT_PROBES = ["text", "letters and words", "typography", "a poster with a headline", "a page of printed text",
               "a sign with writing"]
NOTEXT_PROBES = ["a photograph with no text", "an abstract image without any writing", "a landscape", "a texture",
                 "a picture of an object"]
PROBE_VERSION = 1
PROBES_PER_KIND = 12
PROBE_SIZE = (1024, 640)
CAL_QUANTILE = 0.0           # every lettered probe scores at or above the calibrated cutoff (the faintest one)
POOL_SHARE = 1 / 3           # refs come from the pool's least text-like third at most
FALLBACK_SHARE = 0.2         # ... or its least text-like fifth when calibration is unavailable


def text_free_scores(Xn: np.ndarray, meta: dict, embedder=None, pdir=None, yes: bool = False) -> np.ndarray:
    """max cosine to text prompts minus max cosine to no-text prompts (higher = more lettering)"""
    from .embed import text_vectors
    T = text_vectors(meta, TEXT_PROBES + NOTEXT_PROBES, embedder=embedder, pdir=pdir, yes=yes)
    T = T / (np.linalg.norm(T, axis=1, keepdims=True) + 1e-12)
    S = Xn @ T.T
    return S[:, :len(TEXT_PROBES)].max(1) - S[:, len(TEXT_PROBES):].max(1)


def render_probe(kind: str, seed: int, size=PROBE_SIZE):
    """kind: headline | micro | none — blurred colour ground + a few shapes, plus lettering for the first two"""
    from PIL import ImageDraw
    rng = np.random.default_rng(10_000 + seed * 7 + {"headline": 1, "micro": 2, "none": 3}[kind])
    dark = rng.random() < 0.5
    hue = rng.random()
    cols = [Y.hsv(hue + rng.uniform(-0.15, 0.15), rng.uniform(0.0, 0.7), rng.uniform(0.05, 0.3) if dark else
                  rng.uniform(0.6, 0.95)) for _ in range(4)]
    im = Y.ground_blur(rng, size, cols)
    d = ImageDraw.Draw(im)
    Y.shapes(d, rng, size, cols + [Y.hsv(rng.random(), 0.8, 0.9)], outline_only=rng.random() < 0.5)
    bg = tuple(int(x) for x in np.asarray(im).reshape(-1, 3).mean(0))
    ink = Y.ink_for(bg)
    w, h = size
    if kind == "headline":
        style = ["grotesk", "condensed", "serif", "din", "display"][int(rng.integers(5))]
        sz = int(rng.integers(48, 112))
        lines = [Y.headline(rng, case="upper" if rng.random() < 0.6 else "title") for _ in range(int(rng.integers(1, 3)))]
        Y.text_block(d, rng, (rng.uniform(0.04, 0.3) * w, rng.uniform(0.1, 0.6) * h), lines, style, sz, ink, leading=1.05)
    elif kind == "micro":
        for _ in range(int(rng.integers(1, 3))):
            sz = int(rng.integers(12, 23))
            lines = [Y.micro_line(rng) for _ in range(int(rng.integers(3, 9)))]
            Y.text_block(d, rng, (rng.uniform(0.03, 0.6) * w, rng.uniform(0.05, 0.7) * h), lines, "mono", sz, ink,
                         leading=1.35)
    return im


def probe_paths() -> dict[str, list[Path]]:
    """render (once) and return the probe set under $SLOP_HOME/cache/textprobe/v<N>/"""
    from ..config import cache_dir
    d = cache_dir("textprobe") / f"v{PROBE_VERSION}"
    d.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[Path]] = {}
    for kind in ("headline", "micro", "none"):
        out[kind] = []
        for k in range(PROBES_PER_KIND):
            p = d / f"{kind}-{k:02d}.jpg"
            if not p.exists():
                tmp = p.with_name(p.stem + ".tmp.jpg")
                render_probe(kind, k).save(tmp, quality=90)
                tmp.replace(p)
            out[kind].append(p)
    return out


def calibrate(meta: dict, embedder=None, pdir=None, yes: bool = False) -> dict:
    """embed the probes with the store's model -> {cutoff, text/no-text score summaries}; cached per model tag"""
    from ..config import cache_dir
    from .embed import BATCH, text_embedder_for
    cf = cache_dir("embed") / meta["tag"] / f"textprobe-v{PROBE_VERSION}.json"
    if cf.exists():
        try:
            return json.loads(cf.read_text(encoding="utf-8"))
        except ValueError:
            pass
    emb = embedder or text_embedder_for(meta, pdir, yes=yes)
    paths = probe_paths()
    flat = [(k, p) for k in ("headline", "micro", "none") for p in paths[k]]
    vecs: list = []
    for s in range(0, len(flat), BATCH):
        vecs += list(emb.embed_images([p for _, p in flat[s:s + BATCH]]))
    if any(v is None for v in vecs):
        raise ValueError("some probe images could not be embedded")
    V = np.stack([np.asarray(v, dtype="float32") for v in vecs])
    V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-12)
    sc = text_free_scores(V, meta, embedder=emb, pdir=pdir, yes=yes)
    kinds = np.array([k for k, _ in flat])
    lettered = sc[kinds != "none"]
    clean = sc[kinds == "none"]
    cut = float(np.quantile(lettered, CAL_QUANTILE))
    out = {"version": PROBE_VERSION, "tag": meta["tag"], "cutoff": round(cut, 5), "quantile": CAL_QUANTILE,
           "lettered": {"n": int(len(lettered)), "min": round(float(lettered.min()), 5),
                        "median": round(float(np.median(lettered)), 5)},
           "headline_median": round(float(np.median(sc[kinds == "headline"])), 5),
           "micro_median": round(float(np.median(sc[kinds == "micro"])), 5),
           "clean": {"n": int(len(clean)), "median": round(float(np.median(clean)), 5),
                     "max": round(float(clean.max()), 5), "kept_share": round(float((clean < cut).mean()), 3)}}
    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def cutoff(scores: np.ndarray, meta: dict, embedder=None, pdir=None, text_max: float | None = None,
           yes: bool = False) -> dict:
    """-> {cutoff, method, ...}: refs are the images with score < cutoff"""
    scores = np.asarray(scores, dtype=float)
    if text_max is not None:
        c = float(text_max)
        return {"cutoff": c, "method": "--text-max (absolute)", "clean_share": round(float((scores < c).mean()), 3)}
    pool_cut = float(np.quantile(scores, POOL_SHARE))
    try:
        cal = calibrate(meta, embedder=embedder, pdir=pdir, yes=yes)
    except Exception as e:  # noqa: BLE001 — a missing / failing image path in the embedder: be stricter instead
        from ..config import SlopError
        if isinstance(e, SlopError) and ("budget" in str(e) or "--yes" in str(e)):
            raise
        c = float(np.quantile(scores, FALLBACK_SHARE))
        return {"cutoff": round(c, 5), "method": f"pool least-text {FALLBACK_SHARE:.0%} (probe calibration failed: "
                f"{type(e).__name__}: {str(e)[:120]})", "pool_share": FALLBACK_SHARE,
                "clean_share": round(float((scores < c).mean()), 3)}
    c = min(pool_cut, float(cal["cutoff"]))
    return {"cutoff": round(c, 5), "method": "stricter of: calibrated on rendered lettering probes, pool least-text third",
            "calibrated_cutoff": cal["cutoff"], "pool_cutoff": round(pool_cut, 5), "pool_share": round(POOL_SHARE, 3),
            "probe": {k: cal[k] for k in ("lettered", "clean", "headline_median", "micro_median")},
            "clean_share": round(float((scores < c).mean()), 3)}


# ---------------------------------------------------------------- the in-pool paired probe (the default for boards)

POOL_PROBE_VERSION = 1
PROBE_MAX = 48               # backgrounds (= lettered copies to embed once per pool image; cached)
PROBE_MIN = 16               # fewer backgrounds (a pool under 40 images) -> the zero-shot fallback
# backgrounds: the pool's least text-like fifth when it holds >= 24, else its third (>= 24; both validated on real
# images, pools of 72+), else its least text-like 40 % (>= 16: pools of 40-71, review round 2)
BG_TIERS = ((0.2, 24), (1 / 3, 24), (0.4, PROBE_MIN))
POOL_MIN = 40                # the smallest pool the paired probe calibrates (40 % of 40 = 16 backgrounds)
PROBE_LAMBDA = 1.0
PROBE_CLEAN_Q = 0.9          # the leave-one-out 90th percentile of the backgrounds' scores
LETTER_KINDS = ("headline", "lyric", "micro")
_HEX = set("0123456789abcdef")


def _ink_for_box(im, box) -> tuple[int, int, int]:
    reg = np.asarray(im.crop(box).convert("L"), dtype=float).mean() / 255
    return (243, 241, 234) if reg < 0.55 else (18, 18, 18)


def render_lettered(im, kind: str, seed: int):
    """a lettered copy of a pool image: a headline, a lower-third lyric line or a micro-text block (OFL faces)"""
    from PIL import ImageDraw
    im = im.convert("RGB").copy()
    w, h = im.size
    r = np.random.default_rng(seed)
    d = ImageDraw.Draw(im)
    if kind == "headline":
        sz = max(12, int(w * r.uniform(0.05, 0.10)))
        x, y = w * r.uniform(0.05, 0.3), h * r.uniform(0.1, 0.6)
        style = ["grotesk", "condensed", "serif"][int(r.integers(3))]
        box = (int(x), int(y), int(min(w - 1, x + w * 0.5)), int(min(h - 1, y + sz * 1.2)))
        Y.text_block(d, r, (x, y), [Y.headline(r, 2, "upper")], style, sz, _ink_for_box(im, box))
    elif kind == "lyric":
        sz = max(10, int(w * r.uniform(0.028, 0.045)))
        x, y = w * 0.07, h * r.uniform(0.72, 0.86)
        box = (int(x), int(y), int(min(w - 1, x + w * 0.5)), int(min(h - 1, y + sz * 1.2)))
        line = " ".join(Y.word(r, "lower") for _ in range(int(r.integers(3, 6))))
        Y.text_block(d, r, (x, y), [line], "grotesk", sz, _ink_for_box(im, box))
    else:
        sz = max(9, int(int(r.integers(14, 22)) * max(0.5, w / 1024)))
        x, y = w * r.uniform(0.04, 0.6), h * r.uniform(0.05, 0.65)
        box = (int(x), int(y), int(min(w - 1, x + 240)), int(min(h - 1, y + sz * 8)))
        Y.text_block(d, r, (x, y), [Y.micro_line(r) for _ in range(int(r.integers(3, 7)))], "mono", sz,
                     _ink_for_box(im, box), leading=1.35)
    return im


def _ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = PROBE_LAMBDA):
    """ridge regression in the dual form (n << dim) -> (w, b)"""
    mu = X.mean(0)
    Xc = X - mu
    ym = float(y.mean())
    w = Xc.T @ np.linalg.solve(Xc @ Xc.T + lam * np.eye(len(X)), y - ym)
    return w, ym - float(mu @ w)


def _ridge_dual(X: np.ndarray, y: np.ndarray, lam: float = PROBE_LAMBDA):
    """-> (w, b, leave-one-PAIR-out predictions). Rows are k backgrounds then their k lettered copies; a copy is
    nearly its background, so plain leave-one-out would predict each left-out row from its twin (wrong label)."""
    k = len(X) // 2
    w, b = _ridge_fit(X, y, lam)
    out = np.zeros(len(X))
    for i in range(k):
        keep = np.r_[np.arange(0, i), np.arange(i + 1, k + i), np.arange(k + i + 1, 2 * k)]
        wi, bi = _ridge_fit(X[keep], y[keep], lam)
        out[i], out[k + i] = X[i] @ wi + bi, X[k + i] @ wi + bi
    return w, b, out


def _auc(pos, neg) -> float:
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return float("nan")
    return float((pos[:, None] > neg[None, :]).mean() + 0.5 * (pos[:, None] == neg[None, :]).mean())


def _key_kind_seed(key: str) -> tuple[str, int]:
    seed = int(key[:8], 16) if len(key) >= 8 and set(key[:8]) <= _HEX else sum(map(ord, key))
    return LETTER_KINDS[seed % len(LETTER_KINDS)], seed


def _rank(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    r = np.empty(len(v))
    r[np.argsort(v, kind="stable")] = np.arange(len(v))
    return r / max(1, len(v) - 1)


def synthetic_ridge(meta: dict, embedder):
    """a ridge probe on the rendered probe set (24 lettered vs 12 clean synthetic images), vectors cached per model"""
    from ..config import cache_dir
    cf = cache_dir("embed") / meta["tag"] / f"textprobe-v{PROBE_VERSION}-vecs.npz"
    V = y = None
    if cf.exists():
        try:
            z = np.load(cf, allow_pickle=False)
            V, y = z["V"].astype("float32"), z["y"].astype("float64")
        except (OSError, ValueError, KeyError):
            V = None
    if V is None:
        pp = probe_paths()
        flat = [(1.0, q) for q in pp["headline"] + pp["micro"]] + [(0.0, q) for q in pp["none"]]
        vecs: list = []
        for s0 in range(0, len(flat), 8):
            vecs += list(embedder.embed_images([q for _, q in flat[s0:s0 + 8]]))
        if any(v is None for v in vecs):
            raise ValueError("some probe images could not be embedded")
        V = np.stack([np.asarray(v, dtype="float32") for v in vecs])
        V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-12)
        y = np.array([t for t, _ in flat])
        np.savez(cf, V=V.astype("float16"), y=y)
    return _ridge_fit(V, y)


def pool_probe(Xn: np.ndarray, paths: list, keys: list[str], zscores: np.ndarray, meta: dict, embedder) -> dict:
    """fit the paired probe on the pool -> {w, b, cutoff, k, loo_auc, ...}; raises ValueError when it cannot"""
    from PIL import Image
    from ..config import cache_dir
    ok = [k for k in range(len(Xn)) if paths[k] is not None and Path(paths[k]).is_file()]
    if len(ok) < PROBE_MIN:
        raise ValueError(f"only {len(ok)} pool images with files (need {PROBE_MIN})")
    # rank by the zero-shot score AND a ridge trained on the rendered probes: the zero-shot score alone calls type on
    # flat gradients "text-free" (real engine frames: AUC 0.30), which put lettered frames among the backgrounds
    sel = _rank(zscores)
    try:
        ws, bs = synthetic_ridge(meta, embedder)
        sel = (sel + _rank(Xn @ ws + bs)) / 2
    except Exception:  # noqa: BLE001 — the probes cannot be embedded: the zero-shot ranking alone
        pass
    order = sorted(ok, key=lambda k: float(sel[k]))
    # backgrounds must be text-free: a background that already carries lettering teaches the probe that lettering is
    # clean (a typography-heavy pool) -> the least text-like FIFTH, a third for smaller pools, 40 % for 40-59 images
    cand = next((order[: int(len(order) * f)] for f, m in BG_TIERS if int(len(order) * f) >= m), None)
    if cand is None:
        raise ValueError(f"{len(order)} pool images are too few for the paired probe (its least text-like "
                         f"{BG_TIERS[-1][0]:.0%} must hold >= {PROBE_MIN}; {POOL_MIN}+ images)")
    bg = cand[:: max(1, len(cand) // PROBE_MAX)][:PROBE_MAX]
    idir = cache_dir("textprobe") / f"pool-v{POOL_PROBE_VERSION}"
    vdir = cache_dir("embed") / meta["tag"] / f"letter-v{POOL_PROBE_VERSION}"
    idir.mkdir(parents=True, exist_ok=True)
    vdir.mkdir(parents=True, exist_ok=True)
    vecs: dict[int, np.ndarray] = {}
    todo = []
    for k in bg:
        kind, seed = _key_kind_seed(keys[k])
        vf = vdir / f"{keys[k]}-{kind}.npy"
        if vf.exists():
            try:
                vecs[k] = np.load(vf).astype("float32")
                continue
            except (OSError, ValueError):
                pass
        img = idir / f"{keys[k]}-{kind}.jpg"
        if not img.exists():
            tmp = img.with_name(img.stem + ".tmp.jpg")
            render_lettered(Image.open(paths[k]), kind, seed).save(tmp, quality=88)
            tmp.replace(img)
        todo.append((k, img, vf))
    for s in range(0, len(todo), 8):
        part = todo[s:s + 8]
        vs = embedder.embed_images([img for _, img, _ in part])
        for (k, _, vf), v in zip(part, vs):
            if v is None:
                continue
            v = np.asarray(v, dtype="float16")             # the cached precision, so a rerun gives the same probe
            np.save(vf, v)
            vecs[k] = v.astype("float32")
    bg = [k for k in bg if k in vecs]
    if len(bg) < PROBE_MIN:
        raise ValueError(f"only {len(bg)} lettered copies could be embedded (need {PROBE_MIN})")
    L = np.stack([vecs[k] for k in bg])
    L = L / (np.linalg.norm(L, axis=1, keepdims=True) + 1e-12)
    X = np.vstack([Xn[bg], L])
    y = np.r_[np.zeros(len(bg)), np.ones(len(bg))]
    w, b, loo = _ridge_dual(X, y)
    lc, ll = loo[: len(bg)], loo[len(bg):]
    mid = float((lc.mean() + ll.mean()) / 2)
    q90 = float(np.quantile(lc, PROBE_CLEAN_Q))
    return {"w": w, "b": b, "cutoff": min(mid, q90), "midpoint": round(mid, 4), "clean_q90": round(q90, 4),
            "lettered_median": round(float(np.median(ll)), 4), "k": len(bg), "loo_auc": round(_auc(ll, lc), 4),
            "embedded_now": len(todo), "version": POOL_PROBE_VERSION}


def _range(scores) -> list[float]:
    return [round(float(np.min(scores)), 4), round(float(np.max(scores)), 4)] if len(scores) else [0.0, 0.0]


def _check_text_max(text_max: float, scores: np.ndarray, info: dict) -> None:
    """refuse a --text-max that would let lettered images into the refs (review round 2: on the zero-shot scale,
    about -0.05..+0.05, the help's "0.5" let every lettered image of a small pool into refs.json)"""
    from ..config import SlopError
    lo, hi = _range(scores)
    sug = info.get("suggested_text_max")
    if info["score"] == "zero-shot":
        top = round(float(np.quantile(scores, POOL_SHARE)), 4) if len(scores) else hi
        if text_max > top:
            raise SlopError(
                f"--text-max {text_max:g} is too loose for this pool: with under {POOL_MIN} images the check uses the "
                f"zero-shot score, which runs from {lo:+.4f} to {hi:+.4f} here (not 0..1), and anything above "
                f"{top:+.4f} (the least text-like third) would let lettered images into the refs. Try --text-max "
                f"{sug:+.4f} (the least text-like fifth) and look at the refs before using them, or add references "
                f"(at {POOL_MIN}+ images the check calibrates itself on lettered copies of your own images); nothing "
                "was written")
    else:
        lm = info.get("lettered_median")
        if lm is not None and text_max >= lm:
            raise SlopError(
                f"--text-max {text_max:g} is at or above where lettered copies of your own images score (median "
                f"{lm:.3f}; this pool's scores run from {lo:+.3f} to {hi:+.3f}): half the lettering would pass into "
                f"the refs. Use a value below {lm:.3f}"
                + (f", e.g. {sug:.3f} (the probe's class boundary)" if sug is not None else "")
                + "; nothing was written")


def assess(pdir, ids: list[str], Xn: np.ndarray, items: dict, meta: dict, embedder=None, text_max: float | None = None,
           yes: bool = False) -> tuple[np.ndarray, dict]:
    """-> (a text score for every pool image, the cutoff info); refs are the images with score < info["cutoff"].
    info also carries the score in use, its range in this pool and a suggested looser --text-max."""
    from .pool import image_path
    z = text_free_scores(Xn, meta, embedder=embedder, pdir=pdir, yes=yes)
    paths = [image_path(pdir, items[i]) if i in items else None for i in ids]
    keys = [str((items.get(i) or {}).get("sha1") or i) for i in ids]
    try:
        emb = embedder
        if emb is None:
            from .embed import text_embedder_for
            emb = text_embedder_for(meta, pdir, yes=yes)
        pr = pool_probe(Xn, paths, keys, z, meta, emb)
    except Exception as e:  # noqa: BLE001 — a small pool / copies that cannot be embedded: the zero-shot fallback
        from ..config import SlopError
        if isinstance(e, SlopError) and ("budget" in str(e) or "--yes" in str(e)):
            raise
        why = f"{type(e).__name__}: {str(e)[:120]}"
        sug = round(float(np.quantile(z, FALLBACK_SHARE)), 4) if len(z) else 0.0
        pre = {"score": "zero-shot", "suggested_text_max": sug}
        if text_max is not None:
            _check_text_max(float(text_max), z, pre)
        info = cutoff(z, meta, embedder=embedder, pdir=pdir, text_max=text_max, yes=yes)
        info.update(pre, score_range=_range(z))
        info["method"] += f" — the per-pool paired probe was unavailable ({why})"
        if text_max is None and info["clean_share"] < 0.05:
            info["hint"] = (f"the zero-shot check is strict on photographs (its scores run from {_range(z)[0]:+.4f} "
                            f"to {_range(z)[1]:+.4f} here, not 0..1); with {POOL_MIN}+ images in the pool the "
                            f"per-pool probe calibrates itself: add references, or look at the board and pass "
                            f"--text-max {sug:+.4f} (the least text-like fifth)")
        return z, info
    s = Xn @ pr["w"] + pr["b"]
    info = {"score": "paired-probe", "backgrounds": pr["k"], "loo_auc": pr["loo_auc"], "midpoint": pr["midpoint"],
            "clean_q90": pr["clean_q90"], "lettered_median": pr["lettered_median"], "embedded_now": pr["embedded_now"],
            "score_range": _range(s),
            "suggested_text_max": pr["midpoint"] if pr["midpoint"] > pr["cutoff"] + 1e-4 else None}
    if text_max is not None:
        _check_text_max(float(text_max), s, info)
        c = float(text_max)
        info["method"] = "--text-max (absolute, on the paired-probe score: about 0 clean, about 1 lettered)"
        if c > pr["midpoint"]:
            info["warning"] = (f"--text-max {c:g} is above the probe's class boundary ({pr['midpoint']:.3f}): some "
                               "lettered images may pass — look at every ref before using it")
    else:
        c = round(float(pr["cutoff"]), 5)
        info["method"] = (f"paired probe: {pr['k']} of your own images vs lettered copies of them; the stricter of "
                          "the leave-one-out midpoint and the backgrounds' 90th percentile")
    info.update(cutoff=c, clean_share=round(float((s < c).mean()), 3))
    return s, info
