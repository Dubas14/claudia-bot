"""GPU detection and the busy rule (stdlib only; runs on the user's computer).

NVIDIA (Windows, Linux): `nvidia-smi --query-gpu=...` -> index, uuid, name, VRAM total/used/free, utilisation, display.
Apple Silicon: one "mps" device (audio and matte profiles only). AMD: ROCm on Linux is not wired up yet - an AMD GPU is
reported as found but unsupported (amd_present), never silently used on the CPU.

The busy rule (a common GPU-queue rule): a GPU is BUSY when more than 1 GiB of its memory is in use, or its
utilisation is above 10 %, before our job starts - somebody else (a game, a render, another queue, the desktop of a
display GPU) is using it, and we do not disturb other workloads. Utilisation is the median of three samples. A busy
GPU is skipped; if every GPU is busy the job waits (the box falls back to the CPU in --gpu auto) unless the job or
the worker settings say force. The pick: the usable GPU with the most free memory, non-display GPUs first. A pinned
GPU (worker setting gpu_uuid) is the only candidate.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time

# Windows: every helper process the worker starts passes NOWIN (CREATE_NO_WINDOW), so none can open a console window
# even when the worker was started without one (worker.py runs python.exe in a hidden console).
NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}

BUSY_MIB = 1024
BUSY_UTIL = 10
QUERY = "index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu,display_active,driver_version"


def _num(x: str):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def nvidia_smi() -> str | None:
    w = shutil.which("nvidia-smi")
    if w:
        return w
    for p in (r"C:\Windows\System32\nvidia-smi.exe", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
              "/usr/bin/nvidia-smi", "/usr/lib/wsl/lib/nvidia-smi"):
        if os.path.isfile(p):
            return p
    return None


def parse_nvidia(text: str) -> list[dict]:
    keys = QUERY.split(",")
    gpus = []
    for line in text.strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < len(keys):
            continue
        d = dict(zip(keys, parts))
        gpus.append({
            "kind": "cuda", "index": int(_num(d["index"]) or 0), "uuid": d["uuid"], "name": d["name"],
            "total_mib": _num(d["memory.total"]), "used_mib": _num(d["memory.used"]),
            "free_mib": _num(d["memory.free"]), "util": _num(d["utilization.gpu"]),
            "display": d["display_active"].lower() == "enabled", "driver": d["driver_version"]})
    return gpus


def nvidia_gpus(samples: int = 3, gap: float = 0.3) -> list[dict]:
    exe = nvidia_smi()
    if not exe:
        return []
    runs = []
    for i in range(max(1, samples)):
        try:
            r = subprocess.run([exe, f"--query-gpu={QUERY}", "--format=csv,noheader,nounits"], capture_output=True,
                               text=True, timeout=20, **NOWIN)
        except (OSError, subprocess.SubprocessError):
            return []
        if r.returncode != 0:
            return []
        runs.append(parse_nvidia(r.stdout))
        if i + 1 < samples:
            time.sleep(gap)
    gpus = runs[-1]
    for g in gpus:                                   # median utilisation / max memory over the samples
        utils = sorted(x["util"] for run in runs for x in run if x["uuid"] == g["uuid"] and x["util"] is not None)
        used = [x["used_mib"] for run in runs for x in run if x["uuid"] == g["uuid"] and x["used_mib"] is not None]
        if utils:
            g["util"] = utils[len(utils) // 2]
        if used:
            g["used_mib"] = max(used)
    return gpus


def apple_mps() -> list[dict]:
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "aarch64"):
        return []
    mem = None
    try:
        mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=10,
                                 **NOWIN).stdout) / 2**20
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return [{"kind": "mps", "index": 0, "uuid": "mps", "name": "Apple Silicon (MPS)", "total_mib": mem,
             "used_mib": None, "free_mib": mem, "util": None, "display": True, "driver": platform.mac_ver()[0]}]


def detect(samples: int = 3) -> list[dict]:
    return nvidia_gpus(samples) or apple_mps()


def backend(gpus: list[dict] | None = None) -> str:
    """'cuda' | 'mps' | 'none' for this computer."""
    gpus = detect() if gpus is None else gpus
    if any(g["kind"] == "cuda" for g in gpus):
        return "cuda"
    if any(g["kind"] == "mps" for g in gpus):
        return "mps"
    return "none"


def busy_reason(g: dict, busy_mib: float = BUSY_MIB, busy_util: float = BUSY_UTIL, own_mib: float = 0.0) -> str | None:
    """own_mib: memory our own idle warm host holds on this GPU (not somebody else's work)."""
    if g["kind"] != "cuda":
        return None
    used, util = g.get("used_mib"), g.get("util")
    if used is not None and own_mib:
        used = max(0.0, used - own_mib)
    why = []
    if used is not None and used > busy_mib:
        why.append(f"{used / 1024:.1f} GiB in use by other programs")
    if util is not None and util > busy_util:
        why.append(f"{util:.0f} % busy")
    if not why:
        return None
    return ", ".join(why) + (" (it drives a display)" if g.get("display") else "")


def pick(gpus: list[dict], pin: str | None = None, force: bool = False, busy_mib: float = BUSY_MIB,
         busy_util: float = BUSY_UTIL, own: dict | None = None) -> tuple[dict | None, list[dict]]:
    """-> (the GPU to use or None, one row per GPU {index, name, busy, picked, why}). own: {uuid: MiB held by our own
    idle warm host} - subtracted before the busy rule."""
    rows, cands = [], []
    for g in gpus:
        why = busy_reason(g, busy_mib, busy_util, (own or {}).get(g["uuid"], 0.0))
        pinned_out = bool(pin) and g["uuid"] != pin
        rows.append({"index": g["index"], "name": g["name"], "kind": g["kind"], "total_mib": g.get("total_mib"),
                     "free_mib": g.get("free_mib"), "display": g.get("display"), "busy": why,
                     "pinned_out": pinned_out, "picked": False})
        if pinned_out:
            continue
        if why and not force:
            continue
        cands.append(g)
    cands.sort(key=lambda g: (bool(g.get("display")), -(g.get("free_mib") or 0)))
    chosen = cands[0] if cands else None
    for r in rows:
        r["picked"] = bool(chosen) and r["index"] == chosen["index"] and r["kind"] == chosen["kind"]
    return chosen, rows


def amd_present() -> bool:
    """An AMD GPU with ROCm on Linux: found, so the worker can say it is not supported instead of 'no GPU'."""
    return platform.system() == "Linux" and any((shutil.which("rocm-smi"), shutil.which("amd-smi"),
                                                 os.path.exists("/dev/kfd")))


def blocked_text(rows: list[dict], pin: str | None = None) -> str:
    if not rows:
        if amd_present():
            return ("an AMD GPU (ROCm) was found, but Claudia's GPU profiles support NVIDIA (CUDA) and Apple Silicon "
                    "only so far: the box keeps using its CPU")
        return "no NVIDIA GPU (nvidia-smi not found) and no Apple Silicon GPU on this computer"
    parts = []
    for r in rows:
        if r["pinned_out"]:
            continue
        parts.append(f"GPU {r['index']} {r['name']}: {r['busy'] or 'free'}")
    msg = "; ".join(parts) or "the pinned GPU was not found"
    return ("every usable GPU is busy - " + msg + ". The job waits until the GPU is free (the box uses its CPU "
            "meanwhile in --gpu auto); close the other GPU program, or force it with `slop gpu submit ... --force-gpu`"
            + (" (this worker is pinned to one GPU: `slopgpu pin auto` lets it use any)" if pin else ""))


def used_mib(uuid: str) -> float | None:
    """Current memory use of one GPU (one quick sample) - the worker samples it while a job runs (VRAM peak)."""
    exe = nvidia_smi()
    if not exe or uuid == "mps":
        return None
    try:
        r = subprocess.run([exe, f"--id={uuid}", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, **NOWIN)
        return _num(r.stdout.strip().splitlines()[0]) if r.returncode == 0 and r.stdout.strip() else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None
