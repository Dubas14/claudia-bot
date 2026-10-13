"""--gpu auto|off|require: send a heavy step to the paired home GPU, or keep it on the box's CPU.

Used by the routing hooks in slop/audio/stems.py (stems), slop/audio/align.py (wav2vec2 emissions) and
slop/edit/depth.py (plate depth maps). The mode comes from `--gpu` on `slop analyze` / `slop edit export` (default
auto there), else $SLOP_GPU, else off (library calls and tests never touch a GPU unless asked).

  auto     use the GPU when `slop gpu status` is healthy for that profile (server up, worker seen in the last minute,
           profile installed, GPU not busy) and no other GPU job is ahead in the queue; otherwise run on the CPU and
           add a note saying why. A GPU job that fails, or waits on a busy GPU, also falls back to the CPU. A step
           whose results would take longer to come back over the PC's measured uplink than the CPU needs stays on
           the CPU. A profile that is missing gets an install job queued, so the NEXT run uses the GPU (not again
           for AUTO_INSTALL_RETRY_S after a failed install: the note shows that error).
  require  the GPU or an error with the next step (direct mode: the job waits for the bot to run it on the PC).
  off      the CPU, silently.
A waiting step that is stopped (Ctrl-C, or SIGTERM from `slop job stop`) cancels its GPU job, so it never keeps the
PC's single GPU slot.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from ..config import SlopError
from . import proto, store

MODES = ("auto", "off", "require")
_MODE: list[str | None] = [None]
NOTES: list[str] = []
USED: list[dict] = []
AUTO_QUEUE_WAIT_S = 120          # auto: a job still queued after this (PC gone, GPU busy) -> CPU
AUTO_MIN_DEPTH = 8               # auto: fewer plates than this stay on the CPU (measured: a cold GPU host costs ~7 s,
                                 # Depth-Anything-V2-Small on a CPU ~0.5-0.8 s a plate + 3.7 s to load) - only when
                                 # the box CAN run depth (torch + transformers installed)
AUTO_INSTALL_RETRY_S = 6 * 3600  # auto: after a failed profile install, do not queue another one for this long
GPU_OVERHEAD_S = 8.0             # auto transfer check: cold worker start + compute, on top of the transfer time
DIRECT_WAIT_S = 6 * 3600         # require + direct mode: the bot has this long to run the job on the PC
SERVE_HINT = "`slop gpu serve`, then paste the line from `slop gpu pair --refresh` on the PC"


def mode() -> str:
    m = _MODE[0] or os.environ.get("SLOP_GPU", "").strip().lower() or "off"
    if m not in MODES:
        raise SlopError(f"--gpu / SLOP_GPU must be one of {', '.join(MODES)} (got {m!r})")
    return m


@contextmanager
def session(m: str | None):
    """Set the mode for one command (the CLI wrappers) and collect its notes."""
    prev = _MODE[0]
    _MODE[0] = (m or "").lower() or None
    mode()
    NOTES.clear()
    USED.clear()
    try:
        yield
    finally:
        _MODE[0] = prev


def note(msg: str) -> None:
    if msg not in NOTES:
        NOTES.append(msg)
        try:
            print(f"[slop gpu] {msg}", file=sys.stderr, flush=True)
        except (OSError, ValueError):
            pass


def health(profile: str | None = None) -> dict:
    """{ok, configured, mode, why, next, worker}. Cheap: local files + one localhost request."""
    from . import service
    m = store.mode()
    w = store.worker()
    out = {"ok": False, "configured": m != "none", "mode": m, "why": "", "next": "", "worker": w,
           "installable": False}
    if m == "none":
        out.update(why="no home GPU is set up", next="`slop gpu serve` then `slop gpu pair` (or direct mode: "
                                                     "`slop gpu direct-plan`)")
        return out
    if m == "direct":
        if store.has_code() and w.get("fresh"):
            out.update(why="direct mode is on, but the paired worker is online (it gets no jobs in direct mode)",
                       next="`slop gpu mode paired`")
        else:
            out.update(why="direct mode: GPU jobs wait for the bot to run them on the PC",
                       next="use `--gpu require` to queue the step for the PC, then `slop gpu direct-plan JOB`")
        return out
    sv = service.status()
    if not sv["server"]:
        out.update(why="the GPU job server is not running on the box",
                   next=SERVE_HINT if store.has_code() else "`slop gpu serve` then `slop gpu pair`")
    elif not store.has_code():
        out.update(why="no computer is paired", next="`slop gpu pair`")
    elif not w.get("seen"):
        out.update(why="the pairing line was not used on the PC yet",
                   next="the user pastes the line from `slop gpu pair` on the PC (lost it? `slop gpu pair` prints a "
                        "new one)")
    elif not w.get("fresh"):
        age = w.get("age_s")
        out.update(why="the paired computer has not checked in" + (f" for {age:.0f} s" if age else "") +
                   " (asleep, worker stopped, or the tunnel URL changed)",
                   next="on the PC run `slopgpu start`, or paste the line from `slop gpu pair --refresh`")
    elif "gpu_ok" not in w:
        out.update(why="the worker just paired and has not asked for work yet",
                   next="`slop gpu status` again in a few seconds")
    elif profile and not ((w.get("profiles") or {}).get(profile) or {}).get("ready"):
        p = (w.get("profiles") or {}).get(profile) or {}
        if p and not p.get("supported", True):
            out.update(why=f"the {profile} profile is not supported on that computer ({w.get('backend')})",
                       next="use --gpu off")
        else:
            out.update(why=f"the {profile} profile is not installed on the PC yet", next=f"`slop gpu install {profile}`",
                       installable=True)
    elif not w.get("gpu_ok"):
        out.update(why=w.get("why") or "the GPU is busy", next="free the GPU (close the other GPU program) or use --gpu off")
    else:
        out["ok"] = True
    return out


def _job_what(j: dict) -> str:
    return j.get("entry") or f"install {j.get('profile')}"


def plan(entry: str, label: str = "", out_mb: float = 0.0, cpu_s: float | None = None) -> bool:
    """True = this step should go to the GPU. In auto mode a no comes with a note (only when a GPU is set up).
    out_mb / cpu_s (auto only): the size of the results the PC must send back and the CPU's estimated time - when
    the PC's measured uplink makes the GPU route slower than that, the step stays on the CPU."""
    m = mode()
    if m == "off":
        return False
    label = label or entry
    profile = proto.ENTRIES[entry]["profile"]
    h = health(profile)
    if h["ok"]:
        if m == "require":
            return True
        ahead = [j for j in store.all_jobs()
                 if j["state"] in proto.ACTIVE or (j["state"] == "queued" and j.get("mode") != "direct")]
        if ahead:
            j = ahead[0]
            note(f"{label} ran on the CPU: the GPU is busy with another Claudia job ({_job_what(j)}, {j['state']}, "
                 f"job {j['id'][:8]}; `slop gpu jobs`)")
            return False
        up = ((h["worker"].get("net") or {}).get("upload_MBps"))
        if out_mb and cpu_s and isinstance(up, (int, float)) and up > 0:
            gpu_s = out_mb / up + GPU_OVERHEAD_S
            if gpu_s > cpu_s:
                note(f"{label} ran on the CPU: sending ~{out_mb:.0f} MB of results back over the PC's uplink (measured "
                     f"{up:.1f} MB/s) takes ~{gpu_s:.0f} s, longer than the box's CPU (~{cpu_s:.0f} s); --gpu "
                     "require forces the GPU")
                return False
        return True
    if m == "require":
        if h["mode"] == "direct":
            return True
        raise SlopError(f"--gpu require: {label} cannot run on the GPU: {h['why']}. Next: {h['next']}")
    if h["configured"]:
        note(f"{label} ran on the CPU: {h['why']}")
        if h["installable"]:
            _auto_install(profile)
    return False


def _auto_install(profile: str) -> None:
    """auto: queue the missing profile's install once - not while one is pending, and not again for
    AUTO_INSTALL_RETRY_S after one failed (a full disk or an old driver would fail every time; the note says why)."""
    inst = [j for j in store.all_jobs() if j["kind"] == "install" and j.get("profile") == profile]
    last = inst[-1] if inst else None
    if last and last["state"] not in proto.TERMINAL:
        return
    if last and last["state"] in ("failed", "interrupted", "timed_out") and \
            time.time() - float(last.get("finished") or 0) < AUTO_INSTALL_RETRY_S:
        mins = (time.time() - float(last.get("finished") or 0)) / 60
        note(f"the last install of the {profile} profile failed {mins:.0f} min ago ({(last.get('error') or '')[:200]}); "
             f"fix that on the PC, then `slop gpu install {profile}` (auto mode does not retry it for "
             f"{AUTO_INSTALL_RETRY_S // 3600} h)")
        return
    store.submit(kind="install", profile=profile, origin="auto (first use)")
    note(f"queued the install of the {profile} profile on the PC (first use, several minutes): the next run "
         "uses the GPU - watch it with `slop gpu status`")


STEMS_OUT_MB_PER_S = 0.57       # measured: 34 MB of 24-bit FLAC stems per 60 s of song (184 MB for 5:06)
STEMS_CPU_S_PER_S = 0.3         # measured: htdemucs on 8-32 CPU threads, 0.25-0.3 s per second of song


def stems_estimate(song: Path) -> tuple[float, float]:
    """(MB of stems the PC sends back, the box CPU's estimated seconds) for a song; (0, 0) when unknown."""
    try:
        import soundfile as sf
        secs = float(sf.info(str(song)).duration)
    except Exception:  # noqa: BLE001 - no estimate: the transfer check is skipped
        return 0.0, 0.0
    cpus = os.cpu_count() or 8
    return secs * STEMS_OUT_MB_PER_S, secs * STEMS_CPU_S_PER_S * max(1.0, 8 / cpus)


class Result:
    def __init__(self, job: dict):
        self.job = job
        self.id = job["id"]
        self.out_dir = store.job_dir(self.id) / "out"
        self.result = job.get("result") or {}
        self.metrics = job.get("metrics") or {}
        self.gpu = (job.get("gpu") or {}).get("name") or self.metrics.get("gpu")

    def file(self, name: str) -> Path:
        p = self.out_dir / proto.safe_name(name)
        if not p.is_file():
            raise SlopError(f"GPU job {self.id} has no output {name}: `slop gpu show {self.id}`")
        return p


@contextmanager
def _stop_on_sigterm():
    """While a CLI step waits for its GPU job: SIGTERM (`slop job stop`) exits through Python's unwinding, so the
    caller's except/finally cancels the GPU job instead of leaving it holding the PC's single GPU slot."""
    if not hasattr(signal, "SIGTERM") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def on_term(signum, _frame):
        raise SystemExit(128 + int(signum))
    try:
        prev = signal.signal(signal.SIGTERM, on_term)
    except (ValueError, OSError):
        yield
        return
    try:
        yield
    finally:
        try:
            signal.signal(signal.SIGTERM, prev if prev is not None else signal.SIG_DFL)
        except (ValueError, OSError, TypeError):
            pass


def execute(entry: str, inputs: dict, params: dict | None = None, label: str = "") -> Result | None:
    """Submit and wait. -> Result, or None (auto mode: fall back to the CPU; a note says why)."""
    m = mode()
    j = store.submit(entry, inputs, params or {}, origin=label or entry)
    direct = store.mode() == "direct"
    if direct:
        store.mark_direct(j["id"])
        note(f"{label or entry}: queued GPU job {j['id']} for your PC (direct mode): run "
             f"`slop gpu direct-plan {j['id']}` and follow its steps; this command waits for it")
    try:
        with _stop_on_sigterm():
            return _wait(j["id"], m, label or entry, direct)
    except BaseException:
        try:
            if store.get(j["id"])["state"] not in proto.TERMINAL:
                store.cancel(j["id"])
        except SlopError:
            pass
        raise


def _wait(jid: str, m: str, label: str, direct: bool) -> Result | None:
    t0 = time.monotonic()
    last_say = last_lease = 0.0
    while True:
        if time.monotonic() - last_lease > 10:          # a worker that died mid-job polls no more: expire it here
            last_lease = time.monotonic()
            with store.locked():
                store.expire_leases()
        j = store.get(jid)
        st = j["state"]
        if st == "succeeded":
            r = Result(j)
            USED.append({"step": label, "job": jid, "gpu": r.gpu, "seconds": round(time.monotonic() - t0, 1),
                         "gpu_seconds": r.metrics.get("seconds"), "vram_job_mib": r.metrics.get("vram_job_mib"),
                         "vram_peak_reserved_mib": r.metrics.get("vram_peak_reserved_mib")})
            return r
        if st in proto.TERMINAL:
            msg = f"{label}: GPU job {jid[:8]} {st}: {(j.get('error') or '')[:300]}"
            if m == "require":
                raise SlopError(msg + f". Details: `slop gpu show {jid}`. Retry, or run the step with --gpu off.")
            note(msg + " - ran on the CPU instead")
            return None
        waited = time.monotonic() - t0
        if m == "auto" and st == "queued":
            w = store.worker()
            why = j.get("blocked") or (None if w.get("fresh") else "the PC stopped checking in")
            if why or waited > AUTO_QUEUE_WAIT_S:
                store.cancel(jid)
                note(f"{label} ran on the CPU: " + (why or f"the GPU job waited {waited:.0f} s in the queue"))
                return None
        if direct and waited > DIRECT_WAIT_S:
            store.cancel(jid)
            raise SlopError(f"{label}: the direct-mode GPU job {jid} was not run on the PC within "
                            f"{DIRECT_WAIT_S // 3600} h; cancelled")
        if time.monotonic() - last_say > 15:
            last_say = time.monotonic()
            ph = j.get("phase") or st
            pr = j.get("progress")
            extra = f" {pr * 100:.0f} %" if isinstance(pr, (int, float)) else ""
            hint = f" (run `slop gpu direct-plan {jid}`)" if direct else ""
            if j.get("blocked"):
                hint += f" - waiting: {j['blocked'][:160]}"
            try:
                print(f"[slop gpu] {label}: GPU job {jid[:8]} {ph}{extra} ({waited:.0f} s){hint}", file=sys.stderr,
                      flush=True)
            except (OSError, ValueError):
                pass
        time.sleep(0.5 if not direct else 3)


def summary() -> list[str]:
    lines = []
    for u in USED:
        v = u.get("vram_peak_reserved_mib") or u.get("vram_job_mib")
        lines.append(f"gpu: {u['step']} ran on {u['gpu'] or 'the GPU'} (job {u['job'][:8]}, {u['seconds']} s end to end"
                     + (f", {v:.0f} MiB VRAM" if v else "") + ")")
    return lines + [f"note: {n}" for n in NOTES]


# ------------------------------------------------------------------------------------------------ depth (batched)
def cpu_depth_ok() -> bool:
    """Can the box itself run Depth-Anything (torch + transformers importable)? Checked without importing them."""
    try:
        return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))
    except (ImportError, ValueError):
        return False


def _depth_cache() -> Path:
    d = store.gdir() / "cache" / "depth"
    d.mkdir(parents=True, exist_ok=True)
    return d


def image_key(im) -> str:
    h = hashlib.sha256(f"{im.mode}|{im.size}|{proto.ENTRIES['matte.depth']['what']}".encode())
    h.update(im.tobytes())
    return h.hexdigest()[:32]


def depth_lookup(small):
    """The GPU's raw predicted depth for this exact model input (prefetched), or None."""
    import numpy as np
    p = _depth_cache() / f"{image_key(small)}.npy"
    if p.is_file():
        return np.load(p)
    return None


def depth_batch(images: list, label: str = "depth") -> int:
    """Run Depth-Anything-V2-Small for many prepared model inputs in ONE GPU job; cache the raw depth by content.
    -> how many were computed (0 = CPU fallback or nothing to do)."""
    import tempfile
    todo, seen = [], set()
    for im in images:
        k = image_key(im)
        if k not in seen and not (_depth_cache() / f"{k}.npy").is_file():
            seen.add(k)
            todo.append((k, im))
    if not todo:
        return 0
    cpu_ok = cpu_depth_ok()
    if mode() == "auto" and len(todo) < AUTO_MIN_DEPTH and cpu_ok:
        if health("matte")["ok"]:
            note(f"{label}: {len(todo)} plate(s) ran on the CPU (as fast as a cold GPU below {AUTO_MIN_DEPTH} plates; "
                 "--gpu require forces the GPU)")
        return 0
    if not plan("matte.depth", label):
        return 0
    with tempfile.TemporaryDirectory(prefix="slop-depth-") as td:
        inputs = {}
        for i, (k, im) in enumerate(todo[:256]):
            p = Path(td) / f"img-{i:03d}.png"
            im.save(p)
            inputs[p.name] = p
        r = execute("matte.depth", inputs, {}, label=f"{label} ({len(inputs)} images)")
    if r is None:
        if not cpu_ok:
            note(f"{label}: this box has no torch/transformers for CPU depth (bin/setup.sh installs them), so plates "
                 "without a GPU depth map render flat")
        return 0
    n = 0
    for i, (k, _) in enumerate(todo[:256]):
        src = r.out_dir / f"img-{i:03d}.npy"
        if src.is_file():
            os.replace(src, _depth_cache() / f"{k}.npy")
            n += 1
    return n
