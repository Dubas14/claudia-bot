"""matte profile: depth (Depth-Anything-V2-Small ONLY), birefnet (BiRefNet_HR mattes), sam2 (SAM 2.1 box masks).

depth returns the RAW predicted depth per image (.npy float32 at the model's resolution); the box normalises it and
resizes it to the plate exactly as its CPU path does (slop/edit/depth.py), so GPU and CPU depth maps match.
BiRefNet_HR's model code is fetched from its Hugging Face repo at ONE pinned revision (trust_remote_code is limited
to that revision; MIT licence).
"""
from __future__ import annotations

import time
from pathlib import Path

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"     # Apache-2.0; never Base/Large (CC-BY-NC-4.0)
BIREFNET = "ZhengPeng7/BiRefNet_HR"                            # MIT
SAM2 = "facebook/sam2.1-hiera-small"                           # Apache-2.0


def _rev(repo: str):
    from slop.gpu.profiles import HF_REVISIONS
    return HF_REVISIONS.get(repo)


def _images(in_dir: Path) -> list[Path]:
    return sorted(Path(in_dir).glob("img-[0-9][0-9][0-9].png"))


def _sync(ctx) -> None:
    if ctx.device == "cuda":
        import torch
        torch.cuda.synchronize()


def depth(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    import numpy as np
    from PIL import Image
    from transformers import pipeline
    dev = ctx.torch_device()
    t = time.monotonic()
    pipe = ctx.model("depth-pipe", lambda: pipeline("depth-estimation", model=DEPTH_MODEL, revision=_rev(DEPTH_MODEL),
                                                    device=dev), to_device=False)   # ~100 MB: stays on the GPU
    t_load = time.monotonic() - t
    per = []
    for p in _images(in_dir):
        t1 = time.monotonic()
        im = Image.open(p).convert("RGB")
        o = pipe(im)
        pred = o.get("predicted_depth")
        d = pred.squeeze().detach().float().cpu().numpy() if pred is not None else np.asarray(o["depth"], np.float32)
        np.save(str(out_dir / f"{p.stem}.npy"), d.astype(np.float32))
        _sync(ctx)
        per.append(round(time.monotonic() - t1, 3))
    return {"model": DEPTH_MODEL, "images": len(per), "load_s": round(t_load, 2), "per_image_s": per}


def birefnet(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    import torch
    from PIL import Image
    from torchvision import transforms
    from transformers import AutoModelForImageSegmentation
    dev = ctx.torch_device()
    t = time.monotonic()
    half = bool(params["half"]) and ctx.device == "cuda"
    model = ctx.model(f"birefnet-{half}", lambda: AutoModelForImageSegmentation.from_pretrained(
        BIREFNET, revision=_rev(BIREFNET), trust_remote_code=True).eval())
    model = model.half() if half else model.float()
    torch.set_float32_matmul_precision("high")
    size = int(params["size"])
    tf = transforms.Compose([transforms.Resize((size, size)), transforms.ToTensor(),
                             transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])
    t_load = time.monotonic() - t
    per = []
    for p in _images(in_dir):
        t1 = time.monotonic()
        im = Image.open(p).convert("RGB")
        x = tf(im).unsqueeze(0).to(dev)
        if half:
            x = x.half()
        with torch.no_grad():
            pred = model(x)[-1].sigmoid().float().cpu()[0].squeeze()
        mask = transforms.ToPILImage()(pred).resize(im.size, Image.BILINEAR)
        mask.save(out_dir / f"{p.stem}.mask.png")
        per.append(round(time.monotonic() - t1, 3))
    return {"model": BIREFNET, "size": size, "half": half, "images": len(per), "load_s": round(t_load, 2),
            "per_image_s": per}


def sam2(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from transformers import Sam2Model, Sam2Processor
    dev = ctx.torch_device()
    t = time.monotonic()
    proc = ctx.model("sam2-proc", lambda: Sam2Processor.from_pretrained(SAM2, revision=_rev(SAM2)), to_device=False)
    model = ctx.model("sam2", lambda: Sam2Model.from_pretrained(SAM2, revision=_rev(SAM2)).eval())
    t_load = time.monotonic() - t
    boxes = params.get("boxes") or []
    per, scores = [], []
    for i, p in enumerate(_images(in_dir)):
        t1 = time.monotonic()
        im = Image.open(p).convert("RGB")
        w, h = im.size
        b = boxes[i] if i < len(boxes) else [0.25, 0.25, 0.75, 0.75]
        inputs = proc(images=im, input_boxes=[[[b[0] * w, b[1] * h, b[2] * w, b[3] * h]]], return_tensors="pt").to(dev)
        with torch.no_grad():
            out = model(**inputs, multimask_output=False)
        masks = proc.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"])[0]
        m = np.asarray(masks).reshape(-1, h, w)[0]
        Image.fromarray((m > 0.5).astype(np.uint8) * 255).save(out_dir / f"{p.stem}.mask.png")
        sc = getattr(out, "iou_scores", None)
        scores.append(round(float(sc.flatten()[0]), 3) if sc is not None else None)
        per.append(round(time.monotonic() - t1, 3))
    return {"model": SAM2, "images": len(per), "load_s": round(t_load, 2), "per_image_s": per, "iou_scores": scores}


def prefetch(ctx) -> None:
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    AutoImageProcessor.from_pretrained(DEPTH_MODEL, revision=_rev(DEPTH_MODEL))
    AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL, revision=_rev(DEPTH_MODEL))
