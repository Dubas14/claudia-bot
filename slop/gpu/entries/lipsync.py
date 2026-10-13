"""lipsync profile (OPT-IN): LatentSync 1.6 - code Apache-2.0 at one pinned commit, weights CreativeML OpenRAIL++-M
(use restrictions; the user accepts them with `slop gpu install lipsync --accept-licence`).

Claudia's default stays "no lip-sync-model fallbacks: cut away instead" (ARCHITECTURE section 7 rule 6). This entry
exists for users who choose it. Not exercised by the toolkit's own tests on real hardware (needs about 18 GB VRAM).
It runs the project's own inference script on video.mp4 + audio.wav and returns out.mp4 (needs ffmpeg on PATH).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def latentsync(in_dir: Path, out_dir: Path, params: dict, ctx) -> dict:
    from huggingface_hub import snapshot_download
    from slop.gpu.profiles import HF_REVISIONS
    home = Path(os.environ.get("SLOPGPU_HOME") or Path.home() / ".claudia-gpu")
    src = home / "src" / "LatentSync"
    if not (src / "scripts" / "inference.py").is_file():
        raise RuntimeError("LatentSync source missing: reinstall the lipsync profile")
    ctx.torch_device()
    ck = src / "checkpoints"
    snapshot_download("ByteDance/LatentSync-1.6", revision=HF_REVISIONS["ByteDance/LatentSync-1.6"], local_dir=str(ck),
                      allow_patterns=["latentsync_unet.pt", "whisper/tiny.pt"])
    cmd = [sys.executable, "-m", "scripts.inference", "--unet_config_path", "configs/unet/stage2_512.yaml",
           "--inference_ckpt_path", str(ck / "latentsync_unet.pt"), "--inference_steps", str(params["steps"]),
           "--guidance_scale", str(params["guidance"]), "--enable_deepcache", "--seed", str(params["seed"]),
           "--video_path", str(in_dir / "video.mp4"), "--audio_path", str(in_dir / "audio.wav"),
           "--video_out_path", str(out_dir / "out.mp4")]
    r = subprocess.run(cmd, cwd=str(src), stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not (out_dir / "out.mp4").is_file():
        raise RuntimeError(f"LatentSync inference failed (exit {r.returncode}); see the job log")
    return {"model": "LatentSync 1.6", "steps": params["steps"], "guidance": params["guidance"]}
