"""GPU profiles: pinned Python environments the worker installs on the user's computer (stdlib only).

Every profile is its own uv venv under <worker home>/envs/<name> (Python 3.12, lipsync 3.10; uv-managed, never the
system Python), torch 2.11.0 from the PyTorch cu128 index on NVIDIA (Windows and Linux: CUDA 12.8 wheels run on RTX
20xx..50xx) or from PyPI on Apple Silicon (MPS). `uv pip install --torch-backend cu128` keeps torch, torchvision and torchaudio on the
CUDA index and everything else on PyPI; torch is pinned on the same line, so no dependency can move it.
A profile is installed atomically (<name>.new, then a rename), with a smoke test (CUDA really works) and a marker
file holding the fingerprint of these pins: change a pin here and the worker re-installs that profile on next use.

Licences (KITOUT section 3; ARCHITECTURE section 7 rule 11):
  audio   Demucs htdemucs (code MIT; the weights carry no separate licence tag - FLAGGED, tell the user before
          commercial use), wav2vec2-large-960h-lv60-self (Apache-2.0), faster-whisper large-v3 (MIT).
  matte   Depth-Anything-V2-Small ONLY (Apache-2.0; never Base/Large, CC-BY-NC-4.0), BiRefNet_HR (MIT; its model code
          comes from the Hugging Face repo, pinned to one revision), SAM 2.1 hiera-small (Apache-2.0).
  interp  FILM (Google, Apache-2.0) as the TorchScript export of the Apache-2.0 PyTorch port, pinned by sha256.
          RIFE (MIT code) was not chosen: its weights are only distributed through a file-sharing link.
  lipsync LatentSync 1.6 (code Apache-2.0, weights CreativeML OpenRAIL++-M with use restrictions): OPT-IN ONLY, the
          user accepts the licence explicitly (`slop gpu install lipsync --accept-licence`). The toolkit's rule stays:
          no lip-sync-model fallbacks by default (cut away instead) - this profile exists for users who choose it.
  video-local  experimental, documented only (open-weight video models such as Wan 2.x through diffusers need about
          24 GB of VRAM and their own licences); not installable from here.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Windows: every helper process the worker starts passes NOWIN (CREATE_NO_WINDOW), so none can open a console window.
NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}

PY = "3.12"
TORCH = "2.11.0"
TORCHVISION = "0.26.0"
CUDA_BACKEND = "cu128"
HF_REVISIONS = {                                   # model repos pinned to one revision
    "depth-anything/Depth-Anything-V2-Small-hf": "5426e4f0f36572d16453bbda7a8389317b1bef99",
    "ZhengPeng7/BiRefNet_HR": "a7a562f6fd16021180f2f4348f4de003a2d3d1e1",
    "facebook/sam2.1-hiera-small": "ee5bba1d82bb8749febdf90f45e84b687142ba03",
    "Systran/faster-whisper-large-v3": "edaa852ec7e145841d8ffdb056a99866b5f0a478",
    "ByteDance/LatentSync-1.6": "c42c7e6c8e9c213626389fa7d9a3c444b8536353",
}
FILM_URL = "https://github.com/dajes/frame-interpolation-pytorch/releases/download/v1.0.2/film_net_fp32.pt"
FILM_SHA256 = "f810cada26d0c288e50a27eac43af74446eb84b857ccbc77a22bb006f4d27240"
LATENTSYNC_SRC = ("https://github.com/bytedance/LatentSync/archive/a229c3948406bc2cf6eaf4873e662e70c6a04746.zip",
                  "LatentSync-a229c3948406bc2cf6eaf4873e662e70c6a04746")

PROFILES: dict[str, dict] = {
    "audio": {
        "what": "song analysis: htdemucs stems, wav2vec2 alignment emissions, faster-whisper large-v3 word times",
        "entries": ["audio.stems", "audio.align", "audio.whisper"],
        "backends": ["cuda", "mps"], "vram_gib": 4, "download_gib": 4.5,
        "torch": [f"torch=={TORCH}"],
        "packages": ["demucs==4.1.0", "transformers==5.17.0", "soundfile==0.14.0", "numpy==2.5.2",
                     "faster-whisper==1.2.1", "safetensors==0.8.0"],
        "licences": {"htdemucs": "code MIT; weights without a separate licence tag (FLAGGED)",
                     "wav2vec2-large-960h-lv60-self": "Apache-2.0", "faster-whisper-large-v3": "MIT"},
        "tested": True},
    "matte": {
        "what": "plates: Depth-Anything-V2-Small depth, BiRefNet_HR mattes, SAM 2.1 box masks",
        "entries": ["matte.depth", "matte.birefnet", "matte.sam2"],
        "backends": ["cuda", "mps"], "vram_gib": 6, "download_gib": 4.0,
        "torch": [f"torch=={TORCH}", f"torchvision=={TORCHVISION}"],
        "packages": ["transformers==5.17.0", "pillow==12.3.0", "numpy==2.5.2", "timm==1.0.30", "kornia==0.8.3",
                     "einops==0.8.2", "safetensors==0.8.0", "accelerate==1.15.0"],
        "licences": {"Depth-Anything-V2-Small": "Apache-2.0 (Small only)", "BiRefNet_HR": "MIT",
                     "SAM 2.1 hiera-small": "Apache-2.0"},
        "tested": True},
    "interp": {
        "what": "frame interpolation: FILM (x2/x4/x8)",
        "entries": ["interp.film"],
        "backends": ["cuda"], "vram_gib": 6, "download_gib": 3.0,
        "torch": [f"torch=={TORCH}"],
        "packages": ["numpy==2.5.2", "pillow==12.3.0"],
        "licences": {"FILM (TorchScript port)": "Apache-2.0"},
        "tested": True},
    "lipsync": {
        "what": "LatentSync 1.6 lip sync - OPT-IN (openrail++ weights); the default rule is still: cut away",
        "entries": ["lipsync.latentsync"],
        "backends": ["cuda"], "vram_gib": 18, "download_gib": 12.0, "python": "3.10",
        "torch": [f"torch=={TORCH}", f"torchvision=={TORCHVISION}"],
        "packages": ["diffusers==0.32.2", "transformers==4.48.0", "decord==0.6.0", "accelerate==0.26.1",
                     "einops==0.7.0", "omegaconf==2.3.0", "opencv-python==4.9.0.80", "mediapipe==0.10.11",
                     "python_speech_features==0.6", "librosa==0.10.1", "scenedetect==0.6.1", "ffmpeg-python==0.2.0",
                     "imageio==2.31.1", "imageio-ffmpeg==0.5.1", "lpips==0.1.4", "face-alignment==1.4.1",
                     "huggingface-hub==0.30.2", "numpy==1.26.4", "kornia==0.8.0", "insightface==0.7.3",
                     "onnxruntime-gpu==1.21.0", "DeepCache==0.1.1"],
        "licences": {"LatentSync code": "Apache-2.0", "LatentSync 1.6 weights": "CreativeML OpenRAIL++-M"},
        "opt_in": "openrail++", "tested": False,
        # insightface 0.7.3 ships only a source archive: pip builds it, which needs a C++ compiler on the PC. torch
        # 2.11 (cu128, needed for RTX 50xx) differs from LatentSync's own 2.5.1: an untested combination.
        "build_from_source": ["insightface"],
        "needs": "a C++ compiler (insightface builds from source): Windows - Visual Studio Build Tools with the "
                 "'Desktop development with C++' workload; Linux - g++ (Debian/Ubuntu: build-essential). Untested: "
                 "torch 2.11 with LatentSync's transformers 4.48 / diffusers 0.32 pins"},
    "video-local": {
        "what": "EXPERIMENTAL, documented only: open-weight video generation (e.g. Wan 2.x via diffusers), >= 24 GB VRAM",
        "entries": [], "backends": ["cuda"], "vram_gib": 24, "download_gib": 40.0,
        "torch": [], "packages": [], "licences": {"varies": "each model's own licence"},
        "document_only": True, "tested": False},
}


class InstallError(RuntimeError):
    pass


def fingerprint(name: str, backend: str) -> str:
    p = PROFILES[name]
    blob = json.dumps({"v": 3, "py": p.get("python", PY), "torch": p["torch"], "pk": p["packages"], "be": backend,
                       "hf": HF_REVISIONS, "film": FILM_SHA256}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def env_python(env: Path) -> Path:
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def marker(home: Path, name: str) -> dict:
    try:
        return json.loads((Path(home) / "envs" / name / "slopgpu-profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status(home: Path, backend: str) -> dict:
    """{name: {ready, installed, stale, installed_at, seconds}} for the worker's heartbeat."""
    out = {}
    for name, p in PROFILES.items():
        m = marker(home, name)
        installed = bool(m) and env_python(Path(home) / "envs" / name).is_file()
        stale = installed and m.get("fingerprint") != fingerprint(name, backend)
        out[name] = {"ready": installed and not stale, "installed": installed, "stale": stale,
                     "installed_at": m.get("installed_at"), "seconds": m.get("seconds"),
                     "supported": backend in p["backends"] and not p.get("document_only")}
    return out


def uv_env(home: Path) -> dict:
    env = dict(os.environ)
    env.update(UV_PYTHON_INSTALL_DIR=str(Path(home) / "python"), UV_CACHE_DIR=str(Path(home) / "cache" / "uv"),
               UV_PYTHON_PREFERENCE="only-managed", UV_NO_CONFIG="1", PYTHONUTF8="1")
    for k in ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME", "PYTHONPATH", "UV_TORCH_BACKEND", "UV_INDEX_URL",
              "UV_EXTRA_INDEX_URL", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PYTHONDONTWRITEBYTECODE"):
        env.pop(k, None)
    return env


SMOKE = {
    "cuda": ("import torch,json;ok=torch.cuda.is_available();a=torch.randn(512,512,device='cuda') if ok else None;"
             "s=float((a@a).mean()) if ok else None;torch.cuda.synchronize() if ok else None;"
             "print(json.dumps({'torch':torch.__version__,'cuda':torch.version.cuda,'ok':ok,"
             "'device':torch.cuda.get_device_name(0) if ok else None}))"),
    "mps": ("import torch,json;ok=torch.backends.mps.is_available();a=torch.randn(512,512,device='mps') if ok else None;"
            "s=float((a@a).mean()) if ok else None;"
            "print(json.dumps({'torch':torch.__version__,'cuda':None,'ok':ok,'device':'mps' if ok else None}))"),
}


def _run(cmd: list, env: dict, log, cwd: Path | None = None, timeout: float = 3600) -> str:
    log("+ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""))
    p = subprocess.Popen([str(c) for c in cmd], **NOWIN, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                         cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                         errors="replace")
    lines = []
    t0 = time.monotonic()
    assert p.stdout is not None
    for line in p.stdout:
        line = line.rstrip()
        lines.append(line)
        if line:
            log(line[:300])
        if time.monotonic() - t0 > timeout:
            p.kill()
            raise InstallError(f"timed out after {timeout:.0f} s: {cmd[0]} {cmd[1] if len(cmd) > 1 else ''}")
    rc = p.wait()
    if rc != 0:
        tail = "\n".join(lines[-15:])
        raise InstallError(f"command failed (exit {rc}): {' '.join(str(c) for c in cmd[:4])} ...\n{tail}")
    return "\n".join(lines)


def download(url: str, dest: Path, sha256: str | None, log) -> Path:
    dest = Path(dest)
    if dest.is_file() and sha256 and _sha(dest) == sha256:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    log(f"downloading {url.rsplit('/', 1)[-1]}")
    req = urllib.request.Request(url, headers={"User-Agent": "claudia-gpu"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    if sha256 and _sha(tmp) != sha256:
        tmp.unlink(missing_ok=True)
        raise InstallError(f"checksum mismatch for {url} - refusing it")
    os.replace(tmp, dest)
    return dest


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def install(name: str, home: Path, uv: Path, backend: str, log=print, accept_licence: bool = False,
            force: bool = False, app_dir: Path | None = None, gpu_uuid: str | None = None) -> dict:
    """Install (or reuse) one profile. -> {"status": "installed"|"up-to-date", "seconds", "smoke"}."""
    if name not in PROFILES:
        raise InstallError(f"unknown profile {name!r}; known: {', '.join(PROFILES)}")
    p = PROFILES[name]
    if p.get("document_only"):
        raise InstallError(f"profile {name} is documented only ({p['what']}); it cannot be installed from Claudia yet")
    if backend not in p["backends"]:
        raise InstallError(f"profile {name} needs {' or '.join(p['backends'])}; this computer has "
                           f"{'no supported GPU' if backend == 'none' else backend}")
    if p.get("opt_in") and not accept_licence:
        raise InstallError(f"profile {name} uses weights under the {p['opt_in']} licence (use restrictions): the user "
                           "must accept it first - on the box: `slop gpu install lipsync --accept-licence`")
    if p.get("build_from_source"):
        missing = compiler_missing()
        if missing:
            raise InstallError(f"profile {name} builds {', '.join(p['build_from_source'])} from source, and this "
                               f"computer has no C++ compiler. Install {missing}, then run the install again")
    home = Path(home)
    fp = fingerprint(name, backend)
    env_dir = home / "envs" / name
    st = status(home, backend)[name]
    if st["ready"] and not force:
        return {"status": "up-to-date", "profile": name, "fingerprint": fp}
    t0 = time.monotonic()
    env = uv_env(home)
    if gpu_uuid:                                     # the smoke test touches only the GPU the worker would use
        env.update(CUDA_VISIBLE_DEVICES=gpu_uuid, CUDA_DEVICE_ORDER="PCI_BUS_ID")
    new = home / "envs" / (name + ".new")
    shutil.rmtree(new, ignore_errors=True)
    new.parent.mkdir(parents=True, exist_ok=True)
    _run([uv, "venv", new, "--python", p.get("python", PY), "--no-project"], env, log)
    py = env_python(new)
    cmd = [uv, "pip", "install", "--python", py, "--compile-bytecode"]   # .pyc now: torch/transformers import
    if backend == "cuda":                                                # in seconds, not 10 s, on every cold start
        cmd += ["--torch-backend", CUDA_BACKEND]
    _run(cmd + p["torch"] + p["packages"], env, log, timeout=4 * 3600)
    if name == "interp":
        download(FILM_URL, home / "models" / "film" / "film_net_fp32.pt", FILM_SHA256, log)
    if name == "lipsync":
        _latentsync_src(home, log)
    smoke = _run([py, "-c", SMOKE["cuda" if backend == "cuda" else "mps"]], env, log, timeout=600)
    try:
        sm = json.loads(smoke.strip().splitlines()[-1])
    except (ValueError, IndexError):
        sm = {"ok": False, "raw": smoke[-300:]}
    if not sm.get("ok"):
        raise InstallError(f"profile {name}: torch installed but the {backend} device does not work: {sm}. Update the "
                           "NVIDIA driver (CUDA 12.8 needs driver 570 or newer) and run the install again.")
    if app_dir is not None:                          # fetch the default model weights now: the first job is then fast
        env2 = dict(env)
        env2.update(PYTHONPATH=str(app_dir), HF_HOME=str(home / "cache" / "hf"),
                    TORCH_HOME=str(home / "cache" / "torch"), SLOPGPU_HOME=str(home))
        _run([py, "-m", "slop.gpu.entry", "--prefetch", name], env2, log, timeout=3 * 3600)
    secs = round(time.monotonic() - t0, 1)
    (new / "slopgpu-profile.json").write_text(json.dumps(
        {"profile": name, "fingerprint": fp, "backend": backend, "python": p.get("python", PY), "smoke": sm,
         "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": secs}, indent=1), encoding="utf-8")
    old = None
    if env_dir.exists():
        old = home / "envs" / f"{name}.old-{int(time.time())}"
        os.replace(env_dir, old)
    os.replace(new, env_dir)
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)
    return {"status": "installed", "profile": name, "fingerprint": fp, "seconds": secs, "smoke": sm}


def compiler_missing() -> str | None:
    """None when a C++ compiler for building wheels is present; else what to install (named for the user)."""
    if os.name == "nt":
        if shutil.which("cl"):
            return None
        vswhere = Path(os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles") or "") /             "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if vswhere.is_file():
            try:
                r = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                                    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"],
                                   capture_output=True, text=True, timeout=60, **NOWIN)
                if r.returncode == 0 and r.stdout.strip():
                    return None
            except (OSError, subprocess.SubprocessError):
                pass
        return "Visual Studio Build Tools (free, from Microsoft) with the 'Desktop development with C++' workload"
    if any(shutil.which(c) for c in ("c++", "g++", "clang++")):
        return None
    return "a C++ compiler (macOS: xcode-select --install; Debian/Ubuntu: sudo apt install build-essential)"


def _latentsync_src(home: Path, log) -> Path:
    import zipfile
    url, top = LATENTSYNC_SRC
    dest = Path(home) / "src" / "LatentSync"
    if (dest / "scripts" / "inference.py").is_file():
        return dest
    z = download(url, Path(home) / "src" / "latentsync.zip", None, log)
    with zipfile.ZipFile(z) as zf:
        for it in zf.infolist():
            if ".." in it.filename or it.filename.startswith("/"):
                raise InstallError("unsafe path in the LatentSync archive")
        zf.extractall(Path(home) / "src")
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(Path(home) / "src" / top, dest)
    return dest


def describe() -> list[dict]:
    rows = []
    for name, p in PROFILES.items():
        rows.append({"profile": name, "what": p["what"], "entries": p["entries"], "backends": p["backends"],
                     "vram_gib": p["vram_gib"], "download_gib": p["download_gib"], "licences": p["licences"],
                     "opt_in": p.get("opt_in"), "document_only": bool(p.get("document_only")),
                     "tested_for_real": p["tested"], "python": None if p.get("document_only") else p.get("python", PY),
                     "needs": p.get("needs")})
    return rows


if __name__ == "__main__":  # pragma: no cover - debugging aid
    json.dump(describe(), sys.stdout, indent=1)
