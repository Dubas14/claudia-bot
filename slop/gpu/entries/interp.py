"""interp profile: FILM frame interpolation (Google's FILM, Apache-2.0, TorchScript export of the Apache-2.0 PyTorch
port; the file is pinned by sha256 in profiles.py and downloaded at install).

Input frames.zip: PNG frames in name order (the box extracts them from a clip with ffmpeg). Output frames.zip:
factor x (n - 1) + 1 frames named 000000.png ...; the box re-encodes them at factor x the frame rate. Each in-between
frame is made by recursive midpoints (t = 0.5, then 0.25 / 0.75 ...), as FILM was trained for.
"""
from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path


def _model_path() -> Path:
    home = Path(os.environ.get("SLOPGPU_HOME") or Path.home() / ".claudia-gpu")
    p = home / "models" / "film" / "film_net_fp32.pt"
    if not p.is_file():
        raise RuntimeError("FILM weights are missing: reinstall the interp profile (slop gpu install interp)")
    return p


def film(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from slop.gpu.proto import safe_extract
    dev = ctx.torch_device()
    t = time.monotonic()
    model = torch.jit.load(str(_model_path()), map_location="cpu").eval()
    half = bool(params["half"]) and ctx.device == "cuda"
    model = (model.half() if half else model.float()).to(dev)
    work = out_dir.parent / "frames-in"
    names = sorted(n for n in safe_extract(in_dir / "frames.zip", work) if n.lower().endswith(".png"))
    if len(names) < 2:
        raise RuntimeError("frames.zip needs at least 2 PNG frames")
    t_load = time.monotonic() - t

    def load(name):
        a = np.asarray(Image.open(work / name).convert("RGB"), np.float32) / 255.0
        h, w = a.shape[:2]
        ph, pw = (-h) % 64, (-w) % 64
        a = np.pad(a, ((ph // 2, ph - ph // 2), (pw // 2, pw - pw // 2), (0, 0)))
        x = torch.from_numpy(a).permute(2, 0, 1)[None].to(dev)
        return (x.half() if half else x), (ph // 2, pw // 2, h, w)

    def mid(x0, x1):
        dt = x0.new_full((1, 1), 0.5)
        with torch.no_grad():
            return model(x0, x1, dt).clamp(0, 1)

    def between(x0, x1, depth):
        if depth == 0:
            return []
        m = mid(x0, x1)
        return between(x0, m, depth - 1) + [m] + between(m, x1, depth - 1)

    levels = {2: 1, 4: 2, 8: 3}[int(params["factor"])]
    frames_out = out_dir.parent / "frames-out"
    frames_out.mkdir(exist_ok=True)
    k = 0
    prev, crop = load(names[0])

    def save(x, crop):
        nonlocal k
        y0, x0, h, w = crop
        a = (x[0].float().permute(1, 2, 0).cpu().numpy()[y0:y0 + h, x0:x0 + w] * 255).round().astype(np.uint8)
        Image.fromarray(a).save(frames_out / f"{k:06d}.png")
        k += 1

    save(prev, crop)
    for name in names[1:]:
        nxt, crop = load(name)
        for m in between(prev, nxt, levels):
            save(m, crop)
        save(nxt, crop)
        prev = nxt
    with zipfile.ZipFile(out_dir / "frames.zip", "w", compression=zipfile.ZIP_STORED) as z:
        for p in sorted(frames_out.glob("*.png")):
            z.write(p, p.name)
    return {"model": "FILM film_net_fp32 (TorchScript)", "frames_in": len(names), "frames_out": k,
            "factor": int(params["factor"]), "load_s": round(t_load, 2), "seconds": round(time.monotonic() - t, 2)}
