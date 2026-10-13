"""Plate depth maps for 2.5D on CPU (the CPU part of prep.py).

Model: Depth-Anything-V2-Small (`depth-anything/Depth-Anything-V2-Small-hf`), licence Apache-2.0 — the only depth
weights this toolkit may use. Never the Large/Base checkpoints (CC-BY-NC-4.0: not allowed in a monetised template).
Weights are cached under $HF_HOME (default $SLOP_HOME/cache/hf, the same cache bin/setup.sh and the taste module use)
on first use (~100 MB download from huggingface.co).

Post-processing kept from prep.py: depth min-max normalised (near = bright), resized to the plate (bicubic), 8-bit,
MaxFilter(9) + GaussianBlur(1.5) so foreground edges extend over the background (the parallax then stretches the
background, not the subject); subject_depth = median of the nearest 12 % of pixels (auto-focus).
Change from the source: runs locally on CPU at <= 1024 px instead of a GPU job on a worker machine; no Grounding DINO
boxes (plates.js "boxes" stays empty; the engine falls back to un-anchored marks).
GPU route: with a paired home GPU (`slop gpu`), `slop edit export --gpu auto|require` sends every picked plate's model
input to the GPU in ONE job first (gpu_prefetch); estimate() then takes the GPU's raw depth and post-processes it here
exactly like the CPU result. --gpu off, or no healthy GPU in auto mode: the CPU, as before.
"""
from __future__ import annotations

import os
from pathlib import Path

MODEL = "depth-anything/Depth-Anything-V2-Small-hf"   # Apache-2.0
_PIPE = None


def available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except ImportError:
        return _gpu_ready()        # no torch on the box: a healthy paired home GPU can make the depth maps


def _gpu_ready() -> bool:
    try:
        from ..gpu import route
        return route.mode() != "off" and route.health("matte")["ok"]
    except Exception:  # noqa: BLE001 - routing is optional
        return False


def _pipe():
    global _PIPE
    if _PIPE is None:
        from ..config import cache_dir
        os.environ.setdefault("HF_HOME", str(cache_dir("hf")))
        from transformers import pipeline
        _PIPE = pipeline("depth-estimation", model=MODEL, device="cpu")
    return _PIPE


def prepare(im):
    """The model input: RGB, at most 1024 px wide (one function for the CPU and the GPU paths)."""
    from PIL import Image
    small = im.convert("RGB")
    if small.width > 1024:
        small = small.resize((1024, round(small.height * 1024 / small.width)), Image.LANCZOS)
    return small


def estimate(im):
    """PIL image -> float32 array (H, W) in 0..1, near = bright."""
    import numpy as np
    from PIL import Image
    small = prepare(im)
    d = _gpu_predict(small)        # routing hook (--gpu auto|require): raw depth from the paired home GPU, or None
    if d is None:
        out = _pipe()(small)
        pred = out.get("predicted_depth")
        if pred is not None:
            d = pred.squeeze().detach().cpu().numpy().astype(np.float32)
        else:
            d = np.asarray(out["depth"], np.float32)
    d = np.asarray(d, np.float32)
    d = (d - d.min()) / max(1e-6, float(d.max() - d.min()))
    return np.asarray(Image.fromarray(d, mode="F").resize(im.size, Image.BICUBIC), np.float32).clip(0, 1)


def depth_png(d, out: Path) -> float:
    """Post-process a 0..1 depth array (near = bright) into the engine's .depth.png; returns subject_depth."""
    import numpy as np
    from PIL import Image, ImageFilter
    d8 = Image.fromarray((np.clip(d, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9)) \
        .filter(ImageFilter.GaussianBlur(1.5))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    d8.save(out)
    a = np.asarray(d8).astype(np.float32) / 255
    near = a[a >= np.quantile(a, .88)]
    return round(float(np.median(near)), 3)


# ------------------------------------------------------------------------------------------------ GPU routing hook
def _gpu_predict(small):
    """The paired GPU's raw predicted depth for this exact model input: from the batch `gpu_prefetch` made (the
    `slop edit export` wrapper calls it first), or one GPU job for this image in --gpu require - and in auto when the
    box cannot run depth itself (no torch/transformers). None = CPU."""
    try:
        from ..gpu import route
    except ImportError:
        return None
    if route.mode() == "off":
        return None
    d = route.depth_lookup(small)
    if d is None and (route.mode() == "require" or not route.cpu_depth_ok()):
        route.depth_batch([small], "depth")
        d = route.depth_lookup(small)
    return d


def gpu_prefetch(pdir: Path) -> int:
    """Every picked plate's depth in ONE GPU job (same plate loading as edit/export.py: RGB, at most PLATE_MAX_W wide,
    then prepare()). Cached by content, so unchanged plates are never sent twice. -> plates computed now."""
    from PIL import Image
    from ..board.common import read_json, resolve_file
    from ..gpu import route
    from .export import PLATE_MAX_W
    picks = read_json(Path(pdir) / "plates/picks.json", default={}) or {}
    ims = []
    for _name, v in sorted(picks.items()):
        f = resolve_file(Path(pdir), (v or {}).get("file"))
        if not (f and f.is_file()):
            continue
        im = Image.open(f).convert("RGB")
        if im.width > PLATE_MAX_W:
            im = im.resize((PLATE_MAX_W, round(im.height * PLATE_MAX_W / im.width)), Image.LANCZOS)
        ims.append(prepare(im))
    return route.depth_batch(ims, "depth") if ims else 0
