"""The code the worker starts inside a profile's venv:

  python -m slop.gpu.entry --serve            the warm host: reads {"entry", "jobdir"} lines on stdin and runs one job
                                              at a time (torch, CUDA and the models stay loaded between jobs)
  python -m slop.gpu.entry ENTRY JOBDIR       run one job and exit (direct use, debugging)
  python -m slop.gpu.entry --prefetch PROFILE download the profile's default model weights (install step)

A job reads JOBDIR/manifest.json (validated again here), its inputs in JOBDIR/in, and writes its outputs to
JOBDIR/out (+ out/result.json with the metrics); the host then writes JOBDIR/host-done.json {"ok", "error"?}.
ENTRY must be one of proto.ENTRIES. The device is the one the worker picked: CUDA_VISIBLE_DEVICES holds that GPU's
UUID, so it is cuda:0 here; on Apple Silicon it is mps.

VRAM between jobs: models are parked in CPU memory and the CUDA cache is emptied after every job, so an idle host
holds only the CUDA context (a few hundred MB); the worker stops an idle host after 60 s, which frees that too.
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from .proto import ENTRIES, atomic_json, read_json, validate_manifest


class Ctx:
    _models: dict = {}                     # per process: models survive between jobs in the warm host
    _lock = threading.Lock()               # a background prewarm and a job never load the same model twice

    def __init__(self):
        self.device = None
        self.on_gpu: list = []

    def log(self, msg: str) -> None:
        print(f"[entry] {msg}", flush=True)

    def torch_device(self):
        import torch
        if torch.cuda.is_available():
            self.device = "cuda"
            torch.backends.cuda.matmul.allow_tf32 = False      # same maths as the CPU path (fp32)
            torch.backends.cudnn.allow_tf32 = False
            return torch.device("cuda:0")
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            self.device = "mps"
            return torch.device("mps")
        if os.environ.get("SLOPGPU_ALLOW_CPU") == "1":          # tests only
            self.device = "cpu"
            return torch.device("cpu")
        raise RuntimeError("no CUDA or MPS device is visible to this job (driver problem, or the GPU was taken)")

    def model(self, key: str, loader, to_device: bool = True):
        """A cached model (loaded once per host process), moved to this job's device; parked on the CPU after."""
        with Ctx._lock:
            m = Ctx._models.get(key)
            if m is None:
                m = Ctx._models[key] = loader()
        if to_device and self.device in ("cuda", "mps") and hasattr(m, "to"):
            import torch
            m = m.to(torch.device("cuda:0" if self.device == "cuda" else "mps"))
            Ctx._models[key] = m
            self.on_gpu.append(key)
        return m

    def release(self) -> None:
        for key in self.on_gpu:
            m = Ctx._models.get(key)
            if m is not None and hasattr(m, "to"):
                Ctx._models[key] = m.to("cpu")
        self.on_gpu.clear()
        if "torch" in sys.modules:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def _metrics(ctx: Ctx, t0: float) -> dict:
    m = {"seconds": round(time.monotonic() - t0, 2), "device": ctx.device}
    if "torch" in sys.modules:
        import torch
        if ctx.device == "cuda" and torch.cuda.is_available():
            m.update(gpu=torch.cuda.get_device_name(0),
                     vram_peak_alloc_mib=round(torch.cuda.max_memory_allocated() / 2**20, 1),
                     vram_peak_reserved_mib=round(torch.cuda.max_memory_reserved() / 2**20, 1),
                     torch=torch.__version__, cuda=torch.version.cuda)
        else:
            m["torch"] = torch.__version__
    return m


def run_job(entry: str, jobdir: Path) -> dict:
    t0 = time.monotonic()
    jobdir = Path(jobdir)
    m = validate_manifest(read_json(jobdir / "manifest.json"))
    if m["entry"] != entry:
        raise RuntimeError(f"manifest entry {m['entry']} != {entry}")
    out = jobdir / "out"
    out.mkdir(parents=True, exist_ok=True)
    mod_name, fn_name = entry.split(".", 1)
    fn = getattr(importlib.import_module(f"slop.gpu.entries.{mod_name}"), fn_name)
    ctx = Ctx()
    if "torch" in sys.modules:
        import torch
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    try:
        res = fn(jobdir / "in", out, m["params"], ctx) or {}
        res["metrics"] = _metrics(ctx, t0)
    finally:
        ctx.release()
    res["entry"] = entry
    atomic_json(out / "result.json", res)
    return res


def run(entry: str, jobdir: Path) -> int:
    res = run_job(entry, jobdir)
    print(json.dumps({"done": entry, "seconds": res["metrics"]["seconds"]}), flush=True)
    return 0


def serve() -> int:
    """The warm host loop (stdin: one JSON line per job; the worker closes stdin or kills us to stop)."""
    print(json.dumps({"host": "ready", "pid": os.getpid()}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            entry, jobdir = req["entry"], Path(req["jobdir"])
            if entry not in ENTRIES:
                raise ValueError(f"unknown entry {entry!r}")
        except (ValueError, KeyError, TypeError) as e:
            print(json.dumps({"bad_request": str(e)[:200]}), flush=True)
            continue
        status: dict
        with open(jobdir / "log.txt", "a", encoding="utf-8", errors="replace") as log, \
                contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                res = run_job(entry, jobdir)
                status = {"ok": True, "seconds": res["metrics"]["seconds"]}
            except BaseException as e:  # noqa: BLE001 - report every failure to the worker
                traceback.print_exc()
                status = {"ok": False, "error": f"{type(e).__name__}: {e}"[:1500]}
                if isinstance(e, KeyboardInterrupt):
                    atomic_json(jobdir / "host-done.json", status)
                    raise
        atomic_json(jobdir / "host-done.json", status)
        if status["ok"]:
            prewarm_after(entry)
    return 0


def prewarm_after(entry: str) -> None:
    """While the box unpacks this job's result, load what the NEXT job of the same command usually needs (e.g. the
    alignment model after stems) in the background, into CPU memory only."""
    mod_name, fn_name = entry.split(".", 1)
    try:
        mod = importlib.import_module(f"slop.gpu.entries.{mod_name}")
    except ImportError:
        return
    fn = getattr(mod, "prewarm_after", None)
    if fn is not None:
        threading.Thread(target=lambda: _quiet(fn, fn_name), daemon=True).start()


def _quiet(fn, name: str) -> None:
    try:
        fn(name, Ctx())
    except Exception:  # noqa: BLE001 - a failed prewarm only costs the time it would have saved
        pass


def prefetch(profile: str) -> int:
    mods = sorted({e.split(".")[0] for e, spec in ENTRIES.items() if spec["profile"] == profile})
    for name in mods:
        mod = importlib.import_module(f"slop.gpu.entries.{name}")
        if hasattr(mod, "prefetch"):
            mod.prefetch(Ctx())
    print(json.dumps({"prefetched": profile}), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--serve"]:
        return serve()
    if len(argv) == 2 and argv[0] == "--prefetch":
        return prefetch(argv[1])
    if len(argv) != 2 or argv[0] not in ENTRIES:
        print(f"usage: python -m slop.gpu.entry --serve | ENTRY JOBDIR | --prefetch PROFILE  (ENTRY: "
              f"{', '.join(sorted(ENTRIES))})", file=sys.stderr)
        return 2
    return run(argv[0], Path(argv[1]))


if __name__ == "__main__":
    sys.exit(main())
