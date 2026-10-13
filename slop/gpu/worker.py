"""`slopgpu`: the Claudia GPU worker on the user's own computer (stdlib only; Windows, Linux, macOS; Python 3.10+).

Installed by bin/gpu-worker.ps1 (Windows) or bin/gpu-worker.sh (macOS/Linux) into ~/.claudia-gpu (SLOPGPU_HOME):
  app/        this package (worker.zip from the box)        envs/<profile>/  one uv venv per GPU profile
  python/     uv-managed CPython 3.12 (never the system one) cache/{uv,hf,torch}  downloads and model weights
  bin/uv      pinned uv                                    work/<job id>/   one sandbox folder per job
  pairing.json  box URL + this worker's secret (private)    config.json      settings (GPU pin, busy thresholds)
  logs/worker.log, state.json, inbox/ + outbox/ (direct mode)

Commands (`slopgpu.cmd` on Windows, `~/.claudia-gpu/slopgpu` elsewhere):
  status | gpus | start | stop | run | logs [--lines N]
  pair --url URL [--token-env SLOPGPU_TOKEN]   trade the pasted one-time code (read from that env var, never argv)
                                               for this worker's own secret and store it
  url URL                                      the box restarted its tunnel: point the worker at the new URL
  unpair                                       forget the pairing and stop
  pin UUID|INDEX|auto                          use only that GPU (auto: the free GPU with the most memory)
  install PROFILE [--accept-licence] [--force] [--detach]
  run-bundle JOB [--detach] | bundle-status JOB  direct mode (files moved by the bot with CopyFromBox/CopyToBox)

Safety: the worker runs ONLY the toolkit's own entrypoints (proto.ENTRIES) with validated parameters; the box can not
send a command line, a package or a model name. Inputs and outputs are plain file names inside the job folder, size-
capped and checksummed. A job runs in its own process group (Windows: a Job Object that kills every descendant), is
killed on cancel/timeout/stop, and never starts on a busy GPU (gpus.py) unless forced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from . import gpus as G
from . import profiles as P
from .proto import (CHUNK, PART, PROTO, ManifestError, atomic_json, list_outputs, read_json, safe_extract,
                    safe_name, sha256_file, split_file, join_parts, valid_id, validate_manifest)

# Windows: console subprocesses started from pythonw (no console) pop up a visible window each time.
# Every helper process the worker runs must pass NOWIN (CREATE_NO_WINDOW on Windows, nothing elsewhere).
NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}

WORKER_FILES = ["__init__.py", "proto.py", "profiles.py", "gpus.py", "worker.py", "entry.py", "entries/__init__.py",
                "entries/audio.py", "entries/matte.py", "entries/interp.py", "entries/lipsync.py"]
UA = "claudia-gpu/1"
IS_WIN = os.name == "nt"


def console_python() -> str:
    """python.exe next to this interpreter (never pythonw.exe). Started with CREATE_NO_WINDOW it owns a HIDDEN console
    that its children inherit: no child opens a window, and the std handles we pass are the ones it really uses."""
    exe = Path(sys.executable)
    if IS_WIN and exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").is_file():
        return str(exe.with_name("python.exe"))
    return str(exe)


def home() -> Path:
    return Path(os.environ.get("SLOPGPU_HOME") or Path.home() / ".claudia-gpu")


def code_hash(pkg_dir: Path | None = None) -> str:
    """sha256 over the worker-side files: the box compares it with its own copy (out-of-date worker -> re-pair)."""
    pkg_dir = Path(pkg_dir or Path(__file__).resolve().parent)
    h = hashlib.sha256()
    for rel in WORKER_FILES:
        p = pkg_dir / rel
        h.update(rel.encode() + b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n") if p.is_file() else b"-")
    return h.hexdigest()[:16]


# ------------------------------------------------------------------------------------------------ settings + log
DEFAULTS = {"gpu_uuid": None, "busy_mib": G.BUSY_MIB, "busy_util": G.BUSY_UTIL, "force": False}


def cfg() -> dict:
    return {**DEFAULTS, **(read_json(home() / "config.json", {}) or {})}


def save_cfg(c: dict) -> None:
    atomic_json(home() / "config.json", {k: c.get(k) for k in DEFAULTS})


def pairing() -> dict:
    return read_json(home() / "pairing.json", {}) or {}


def save_pairing(p: dict) -> None:
    path = home() / "pairing.json"
    atomic_json(path, p)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


_LOG_LOCK = threading.Lock()


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    d = home() / "logs"
    with _LOG_LOCK:
        try:
            d.mkdir(parents=True, exist_ok=True)
            f = d / "worker.log"
            if f.is_file() and f.stat().st_size > 5 << 20:
                os.replace(f, d / "worker.previous.log")
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
    if os.environ.get("SLOPGPU_ECHO", "1") == "1" and sys.stdout and not getattr(sys.stdout, "closed", False):
        try:
            print(line, flush=True)
        except (OSError, ValueError):
            pass


def set_state(**kw) -> None:
    st = read_json(home() / "state.json", {}) or {}
    st.update(kw, updated=time.time())
    atomic_json(home() / "state.json", st)


# ------------------------------------------------------------------------------------------------ the box API
class Unpaired(Exception):
    pass


class Unreachable(Exception):
    pass


class RateLimited(Unreachable):
    """HTTP 429: the box throttles an address that sent many bad codes. Retried with back-off like Unreachable."""


class ApiError(Exception):
    pass


def check_box_url(url: str) -> str:
    """The box URL the worker may send its code to: https://, or plain http only to this computer (tests)."""
    url = (url or "").strip().rstrip("/")
    u = urllib.parse.urlsplit(url)
    local = u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1")
    if not ((u.scheme == "https" and u.hostname) or local):
        raise SystemExit("the box URL must be https:// (or a localhost http URL for tests); got "
                         f"{url[:80]!r}. Copy the line from `slop gpu pair` (or `slop gpu pair --refresh`) again")
    return url


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        if ctx.cert_store_stats().get("x509_ca", 0) == 0:
            for ca in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
                if os.path.isfile(ca):
                    ctx.load_verify_locations(ca)
                    break
    except (ssl.SSLError, OSError):
        pass
    return ctx


class Api:
    """The box's API over one kept-alive HTTPS connection per thread (a new TLS handshake through the tunnel costs
    a few hundred ms; the heartbeat thread has its own connection)."""

    def __init__(self, url: str, token: str, worker_id: str):
        self.url, self.token, self.worker_id = url.rstrip("/"), token, worker_id
        u = urllib.parse.urlsplit(self.url)
        self.https = u.scheme == "https"
        self.host, self.port = u.hostname or "", u.port
        self.base = u.path.rstrip("/")
        self.ctx = ssl_context() if self.https else None
        self._local = threading.local()

    def _conn(self, timeout: float):
        import http.client
        c = getattr(self._local, "conn", None)
        if c is None:
            c = (http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=self.ctx) if self.https
                 else http.client.HTTPConnection(self.host, self.port, timeout=timeout))
            self._local.conn = c
        c.timeout = timeout
        if c.sock is not None:
            c.sock.settimeout(timeout)
        return c

    def _drop(self) -> None:
        c = getattr(self._local, "conn", None)
        self._local.conn = None
        if c is not None:
            try:
                c.close()
            except OSError:
                pass

    def call(self, method: str, path: str, body=None, headers: dict | None = None, timeout: float = 40,
             raw: bool = False):
        import http.client
        h = {"Authorization": f"Bearer {self.token}", "X-Slopgpu-Worker": self.worker_id, "User-Agent": UA,
             "Connection": "keep-alive"}
        data = None
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
            h["Content-Type"] = "application/octet-stream"
        elif body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if data is not None or method in ("POST", "PUT"):
            h["Content-Length"] = str(len(data or b""))
        h.update(headers or {})
        for attempt in (0, 1):                    # a kept-alive connection the far end closed: one fresh retry
            try:
                c = self._conn(timeout)
                c.request(method, self.base + path, body=data, headers=h)
                r = c.getresponse()
                payload = r.read()
                status = r.status
                if r.getheader("Connection", "").lower() == "close":
                    self._drop()
                break
            except (http.client.RemoteDisconnected, http.client.BadStatusLine, BrokenPipeError,
                    ConnectionResetError, ConnectionAbortedError) as e:
                self._drop()
                if attempt:
                    raise Unreachable(str(e)[:200]) from None
            except (OSError, ssl.SSLError, http.client.HTTPException) as e:
                self._drop()
                raise Unreachable(str(e)[:200]) from None
        if status == 401:
            raise Unpaired("the box refused this worker's code (revoked with `slop gpu unpair`, or a new pairing was "
                           "made). Ask the bot for a new pairing line (`slop gpu pair --new`) and paste it here.")
        if status in (502, 503, 504, 530):
            raise Unreachable(f"HTTP {status} from the tunnel (the box server is down?)")
        if status == 429:
            raise RateLimited("rate limited by the box (HTTP 429: too many bad pairing codes from this address)")
        if status >= 400:
            msg = payload[:400].decode("utf-8", "replace")
            try:
                msg = json.loads(msg).get("error", msg)
            except (ValueError, AttributeError):
                pass
            raise ApiError(f"HTTP {status}: {msg}")
        return payload if raw else (json.loads(payload) if payload else {})


def retry(fn, what: str, tries: int = 4):
    for i in range(tries):
        try:
            return fn()
        except Unreachable as e:
            if i == tries - 1:
                raise
            log(f"{what}: {e}; retrying")
            time.sleep((15 if isinstance(e, RateLimited) else 2) * (i + 1))


# the last measured transfer speeds to/from the box (MB/s): the box's --gpu auto weighs them against its CPU
NET: dict = {}
NET_MIN_BYTES = 4 << 20             # smaller transfers are dominated by latency: not a speed measurement


def note_speed(kind: str, nbytes: int, seconds: float) -> float | None:
    if nbytes < NET_MIN_BYTES or seconds <= 0:
        return None
    v = round(nbytes / seconds / 1e6, 2)
    NET[f"{kind}_MBps"] = v
    NET["measured"] = round(time.time())
    return v


def worker_info(c: dict, rows: list[dict], backend: str) -> dict:
    return {"proto": PROTO, "code": code_hash(), "os": platform.system().lower(), "arch": platform.machine().lower(),
            "python": platform.python_version(), "backend": backend, "pinned": bool(c.get("gpu_uuid")),
            "gpus": rows, "profiles": P.status(home(), backend), "busy_mib": c["busy_mib"], "busy_util": c["busy_util"],
            "net": dict(NET) or None}


# ------------------------------------------------------------------------------------------------ job execution
class Reporter:
    """Heartbeats while a job runs: phase, progress, log tail, VRAM. send(dict) -> {"cancel": bool} | None."""

    def __init__(self, send, logfile: Path):
        self.send, self.logfile = send, logfile
        self.phase, self.progress, self.extra = "starting", None, {}
        self.cancel = False
        self._stop = threading.Event()
        self._kick = threading.Event()
        self._th = threading.Thread(target=self._loop, daemon=True)

    def tail(self, n: int = 2500) -> str:
        try:
            with open(self.logfile, "rb") as f:
                f.seek(max(0, self.logfile.stat().st_size - n))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def line(self, msg: str) -> None:
        try:
            with open(self.logfile, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError:
            pass

    def set(self, phase: str | None = None, progress: float | None = None, **extra) -> None:
        if phase:
            self.phase = phase
        self.progress = progress
        self.extra.update(extra)
        self._kick.set()

    def snapshot(self) -> dict:
        return {"phase": self.phase, "progress": self.progress, "log_tail": self.tail(), **self.extra}

    def beat(self) -> None:
        try:
            r = self.send(self.snapshot())
            if isinstance(r, dict) and r.get("cancel"):
                self.cancel = True
        except Unpaired:
            self.cancel = True
        except Exception as e:  # noqa: BLE001 - a missed heartbeat is not fatal
            log(f"heartbeat failed: {e}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.beat()
            self._kick.wait(8)
            self._kick.clear()

    def __enter__(self):
        self._th.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._kick.set()
        self._th.join(timeout=20)


def keep_awake(on: bool) -> None:
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if on else 0x80000000)
        except (AttributeError, OSError):
            pass


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30, **NOWIN)
        else:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            for _ in range(50):
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass


HOST_IDLE_S = 60.0
_HOST: list = [None]


class Host:
    """The warm profile process (`python -m slop.gpu.entry --serve`) bound to one GPU; one at a time. It keeps torch,
    CUDA and the models loaded between jobs (models parked in CPU memory, the CUDA cache emptied after each job) and
    is stopped after HOST_IDLE_S without work, which frees its CUDA context. Cancel/timeout kill its whole process
    tree (Windows: a kill-on-close Job Object; POSIX: its own process group); the next job starts a fresh one."""

    def __init__(self, profile: str, gpu: dict):
        self.profile, self.gpu, self.uuid = profile, gpu, gpu["uuid"]
        self.base = G.used_mib(self.uuid) if gpu["kind"] == "cuda" else None   # before our CUDA context exists
        self.own_mib = 0.0
        self.jobs = 0
        self.last_used = time.monotonic()
        (home() / "logs").mkdir(parents=True, exist_ok=True)
        cmd = [str(P.env_python(home() / "envs" / profile)), "-u", "-m", "slop.gpu.entry", "--serve"]
        kw: dict = {"cwd": str(home()), "env": job_env(gpu), "stdin": subprocess.PIPE,
                    "stdout": open(home() / "logs" / f"host-{profile}.log", "ab"), "stderr": subprocess.STDOUT}
        if IS_WIN:
            cmd = [console_python(), "-m", "slop.gpu.worker", "_jobproc", "--", *cmd]
            kw["creationflags"] = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        self.proc = subprocess.Popen(cmd, **kw)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def send(self, entry: str, wd: Path) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps({"entry": entry, "jobdir": str(wd)}) + "\n").encode())
        self.proc.stdin.flush()
        self.jobs += 1

    def close(self) -> None:
        """An idle host exits at once when its stdin closes; one that does not (stuck) is killed."""
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            kill_tree(self.proc)

    def kill(self) -> None:
        kill_tree(self.proc)


def own_usage() -> dict:
    h = _HOST[0]
    return {h.uuid: h.own_mib} if h is not None and h.alive() and h.own_mib else {}


def get_host(profile: str, gpu: dict) -> "Host":
    h = _HOST[0]
    if h is not None and (not h.alive() or h.profile != profile or h.uuid != gpu["uuid"]):
        h.close()
        h = _HOST[0] = None
    if h is None:
        h = _HOST[0] = Host(profile, gpu)
    return h


def close_host(force: bool = False) -> None:
    h = _HOST[0]
    if h is not None and (force or not h.alive() or time.monotonic() - h.last_used > HOST_IDLE_S):
        h.close()
        _HOST[0] = None


def job_env(gpu: dict | None) -> dict:
    env = dict(os.environ)
    for k in ("PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONDONTWRITEBYTECODE"):
        env.pop(k, None)
    h = home()
    env.update(PYTHONPATH=str(h / "app"), HF_HOME=str(h / "cache" / "hf"), TORCH_HOME=str(h / "cache" / "torch"),
               SLOPGPU_HOME=str(h), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", HF_HUB_DISABLE_TELEMETRY="1",
               TOKENIZERS_PARALLELISM="false")
    if gpu and gpu.get("kind") == "cuda":
        env.update(CUDA_VISIBLE_DEVICES=gpu["uuid"], CUDA_DEVICE_ORDER="PCI_BUS_ID")
    return env


def ensure_profile(m: dict, rep: Reporter, backend: str) -> None:
    st = P.status(home(), backend).get(m["profile"], {})
    if st.get("ready"):
        return
    close_host(force=True)
    rep.set("installing", None, profile=m["profile"])
    rep.line(f"installing profile {m['profile']} (first use; several minutes) ...")
    P.install(m["profile"], home(), uv_path(), backend, log=rep.line, accept_licence=bool(m.get("accept_licence")),
              app_dir=home() / "app")


def uv_path() -> Path:
    """Only the worker's own pinned uv (never another uv on PATH)."""
    p = home() / "bin" / ("uv.exe" if IS_WIN else "uv")
    if p.is_file():
        return p
    raise RuntimeError("uv is missing from ~/.claudia-gpu/bin: run the installer line again")


def execute(m: dict, wd: Path, rep: Reporter, c: dict, backend: str) -> dict:
    """Run one validated job whose inputs are already in wd/in. -> {"state", "error"?, "result"?, "metrics"}."""
    t0 = time.monotonic()
    if m["kind"] == "install":
        close_host(force=True)
        rep.set("installing", None, profile=m["profile"])
        chosen, _ = G.pick(G.detect(1), pin=c.get("gpu_uuid"), force=True)
        r = P.install(m["profile"], home(), uv_path(), backend, log=rep.line, accept_licence=m["accept_licence"],
                      app_dir=home() / "app", gpu_uuid=chosen["uuid"] if chosen and chosen["kind"] == "cuda" else None)
        return {"state": "succeeded", "result": r, "metrics": {"seconds": round(time.monotonic() - t0, 1)}}
    ensure_profile(m, rep, backend)
    chosen, rows = G.pick(G.detect(1), pin=c.get("gpu_uuid"), force=m["force_gpu"] or bool(c.get("force")),
                          busy_mib=c["busy_mib"], busy_util=c["busy_util"], own=own_usage())
    if chosen is None:
        return {"state": "blocked", "error": G.blocked_text(rows, c.get("gpu_uuid"))}
    (wd / "out").mkdir(exist_ok=True)
    (wd / "host-done.json").unlink(missing_ok=True)
    atomic_json(wd / "manifest.json", m)
    rep.set("running", None, gpu={"name": chosen["name"], "index": chosen["index"], "total_mib": chosen.get("total_mib")})
    keep_awake(True)
    host = get_host(m["profile"], chosen)
    warm = host.jobs > 0
    base = host.base
    host.send(m["entry"], wd)
    peak, reason, last_sample, done = base, None, 0.0, None
    try:
        while True:
            time.sleep(0.2)
            done = read_json(wd / "host-done.json")
            if done:
                break
            if not host.alive():
                reason = "died"
                break
            if chosen["kind"] == "cuda" and time.monotonic() - last_sample > 2:
                u = G.used_mib(chosen["uuid"])
                last_sample = time.monotonic()
                if u is not None and (peak is None or u > peak):
                    peak = u
                    rep.extra["vram_used_peak_mib"] = peak
            if rep.cancel or (home() / "stop").exists():
                reason = "cancelled"
            elif time.monotonic() - t0 > m["timeout_s"]:
                reason = "timed_out"
            if reason:
                rep.line(f"[worker] {reason}: killing the job's process tree")
                host.kill()
                _HOST[0] = None
                break
    finally:
        keep_awake(False)
    if reason is None and host.alive():
        host.last_used = time.monotonic()
        after = G.used_mib(chosen["uuid"]) if chosen["kind"] == "cuda" else None
        if after is not None and base is not None:
            host.own_mib = max(0.0, min(4096.0, after - base))
    metrics = {"seconds": round(time.monotonic() - t0, 2), "gpu": chosen["name"], "gpu_index": chosen["index"],
               "warm_host": warm, "vram_before_mib": base, "vram_used_peak_mib": peak,
               "vram_job_mib": round(peak - base, 1) if peak is not None and base is not None else None,
               "vram_idle_host_mib": round(host.own_mib, 1) if _HOST[0] is host else 0.0}
    if reason == "died":
        _HOST[0] = None
        return {"state": "failed", "error": f"the GPU process exited (code {host.proc.returncode}): "
                                            + rep.tail(600).strip()[-500:], "metrics": metrics}
    if reason:
        return {"state": reason, "error": f"job {reason}", "metrics": metrics}
    if not done.get("ok"):
        return {"state": "failed", "error": str(done.get("error"))[:800] + " | " + rep.tail(400).strip()[-300:],
                "metrics": metrics}
    result = read_json(wd / "out" / "result.json", {}) or {}
    metrics.update({k: v for k, v in (result.get("metrics") or {}).items() if k not in metrics or k == "seconds"})
    metrics["seconds_total"] = round(time.monotonic() - t0, 2)
    return {"state": "succeeded", "result": result, "metrics": metrics}


# ------------------------------------------------------------------------------------------------ paired mode
def download_inputs(api: Api, m: dict, wd: Path, rep: Reporter) -> None:
    ind = wd / "in"
    ind.mkdir(parents=True, exist_ok=True)
    total = sum(f["size"] for f in m["inputs"]) or 1
    done = 0
    for f in m["inputs"]:
        name = safe_name(f["name"])
        dest = ind / name
        with open(dest, "wb") as fh:
            off = 0
            while off < f["size"]:
                end = min(f["size"], off + CHUNK) - 1
                q = urllib.parse.quote(name)
                data = retry(lambda: api.call("GET", f"/gpu/api/jobs/{m['id']}/in/{q}",
                                              headers={"Range": f"bytes={off}-{end}"}, raw=True, timeout=180),
                             f"download {name}")
                if not data:
                    raise ApiError(f"empty download for {name} at {off}")
                fh.write(data)
                off += len(data)
                done += len(data)
                rep.set("downloading", round(done / total, 3))
        if dest.stat().st_size != f["size"] or sha256_file(dest) != f["sha256"]:
            raise ApiError(f"input {name} arrived damaged (size/checksum mismatch)")


def upload_outputs(api: Api, m: dict, wd: Path, rep: Reporter) -> list[dict]:
    files = list_outputs(wd / "out")
    total = sum(f["size"] for f in files) or 1
    done = 0
    for f in files:
        p = wd / "out" / f["name"]
        q = urllib.parse.quote(f["name"])
        with open(p, "rb") as fh:
            off = 0
            while True:
                chunk = fh.read(CHUNK)
                if not chunk and off > 0:
                    break
                retry(lambda: api.call("PUT", f"/gpu/api/jobs/{m['id']}/out/{q}?offset={off}", body=chunk,
                                       timeout=300), f"upload {f['name']}")
                off += len(chunk)
                done += len(chunk)
                rep.set("uploading", round(done / total, 3))
                if len(chunk) < CHUNK:
                    break
    return files


def handle_job(api: Api, job: dict, c: dict, backend: str) -> None:
    jid = job.get("id", "?")
    try:
        m = validate_manifest(job, known_profiles=P.PROFILES)
    except ManifestError as e:
        log(f"refused job {jid}: {e}")
        try:
            valid_id(jid)
            api.call("POST", f"/gpu/api/jobs/{jid}/done", {"state": "failed", "error": f"worker refused: {e}"})
        except Exception:  # noqa: BLE001
            pass
        return
    wd = home() / "work" / m["id"]
    shutil.rmtree(wd, ignore_errors=True)
    (wd / "in").mkdir(parents=True)
    log(f"job {m['id'][:8]} {m['kind']} {m.get('entry') or m['profile']}")
    set_state(state="job", job=m["id"], entry=m.get("entry"), since=time.time())

    def send(snap):
        return api.call("POST", f"/gpu/api/jobs/{m['id']}/event", snap, timeout=30)

    rep = Reporter(send, wd / "log.txt")
    res: dict = {}
    net: dict = {}

    def timed(kind: str, nbytes: int, t0: float) -> None:
        secs = time.monotonic() - t0
        net.update({f"{kind}_MB": round(nbytes / 1e6, 2), f"{kind}_s": round(secs, 2)})
        v = note_speed(kind, nbytes, secs)
        if v is not None:
            net[f"{kind}_MBps"] = v

    with rep:
        try:
            if m["kind"] == "run":
                rep.set("downloading", 0.0)
                t0 = time.monotonic()
                download_inputs(api, m, wd, rep)
                timed("download", sum(f["size"] for f in m["inputs"]), t0)
            res = execute(m, wd, rep, c, backend)
            if res["state"] == "blocked":
                log(f"job {m['id'][:8]} handed back: {res['error']}")
                api.call("POST", f"/gpu/api/jobs/{m['id']}/event", {"phase": "blocked", "release": True,
                                                                    "why": res["error"]})
                return
            outputs = []
            if res["state"] == "succeeded" and m["kind"] == "run":
                t0 = time.monotonic()
                outputs = upload_outputs(api, m, wd, rep)
                timed("upload", sum(f["size"] for f in outputs), t0)
        except Unpaired:
            raise
        except Exception as e:  # noqa: BLE001 - report every failure to the box
            res = {"state": "failed", "error": f"{type(e).__name__}: {e}"[:1500], "metrics": res.get("metrics")}
            outputs = []
    if net:
        res["metrics"] = {**(res.get("metrics") or {}), **net}
    body = {"state": res["state"], "error": res.get("error"), "result": res.get("result"), "outputs": outputs,
            "metrics": res.get("metrics"), "log_tail": rep.tail(4000)}
    retry(lambda: api.call("POST", f"/gpu/api/jobs/{m['id']}/done", body, timeout=120), "report done")
    log(f"job {m['id'][:8]} {res['state']}" + (f": {res.get('error')}" if res.get("error") else ""))
    set_state(state="idle", job=None, last_job=m["id"], last_state=res["state"])
    for sub in ("in", "out", "frames-in", "frames-out"):
        shutil.rmtree(wd / sub, ignore_errors=True)


class SingleInstance:
    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+b")
        try:
            if IS_WIN:
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("the worker is already running (`slopgpu status`; stop it with `slopgpu stop`)") from None
        return self

    def __exit__(self, *a):
        try:
            self.fh.close()
        except OSError:
            pass


def run_loop(once: bool = False) -> int:
    pr = pairing()
    if not pr.get("url") or not pr.get("token"):
        log("not paired: run the pairing line from `slop gpu pair` (on the box) first")
        return 3
    (home() / "stop").unlink(missing_ok=True)
    with SingleInstance(home() / "worker.lock"):
        set_state(state="starting", pid=os.getpid(), job=None)
        api = Api(pr["url"], pr["token"], pr["worker_id"])
        backoff = 0.0
        log(f"worker {code_hash()} polling {urllib.parse.urlparse(pr['url']).netloc}")
        while not (home() / "stop").exists():
            c = cfg()
            gl = G.detect()
            backend = G.backend(gl)
            chosen, rows = G.pick(gl, pin=c.get("gpu_uuid"), busy_mib=c["busy_mib"], busy_util=c["busy_util"],
                                  own=own_usage())
            info = worker_info(c, rows, backend)
            why = None if chosen else G.blocked_text(rows, c.get("gpu_uuid"))
            try:
                r = api.call("POST", "/gpu/api/next", {"info": info, "gpu_ok": chosen is not None, "why": why},
                             timeout=45)
                if backoff:
                    log("box reachable again")
                backoff = 0.0
                set_state(state="idle" if chosen else "gpu-busy", box_ok=True, why=why, seen=time.time())
            except Unpaired as e:
                log(str(e))
                close_host(force=True)
                set_state(state="unpaired", why=str(e))
                return 4
            except (Unreachable, ApiError) as e:
                limited = isinstance(e, RateLimited)
                backoff = min(60.0, backoff * 2 or (15.0 if limited else 2.0))
                set_state(state="rate-limited" if limited else "box-unreachable", why=str(e)[:200])
                if limited:
                    log(f"{e}; retry in {backoff:.0f} s (someone is trying wrong codes against the box's URL)")
                else:
                    log(f"box unreachable ({e}); retry in {backoff:.0f} s. If the bot restarted `slop gpu serve`, "
                        "run the re-pair line from `slop gpu pair --refresh`.")
                t_end = time.monotonic() + backoff
                while time.monotonic() < t_end and not (home() / "stop").exists():
                    time.sleep(0.5)
                continue
            job = r.get("job") if isinstance(r, dict) else None
            if not job:
                close_host()                       # idle for HOST_IDLE_S: free the CUDA context
            if job:
                try:
                    handle_job(api, job, c, backend)
                except Unpaired as e:
                    log(str(e))
                    close_host(force=True)
                    set_state(state="unpaired", why=str(e))
                    return 4
                except Exception as e:  # noqa: BLE001 - the loop must survive
                    log(f"job crashed the handler: {type(e).__name__}: {e}")
                    set_state(state="idle", job=None)
                if once:
                    return 0
            elif not chosen:
                for _ in range(20):                # GPU busy: look again in 10 s (stop stays responsive)
                    if (home() / "stop").exists():
                        break
                    time.sleep(0.5)
        close_host(force=True)
        set_state(state="stopped", pid=None)
        log("stopped")
    return 0


# ------------------------------------------------------------------------------------------------ direct mode
def run_bundle(jid: str) -> dict:
    valid_id(jid)
    h = home()
    parts = sorted((h / "inbox").glob(f"{jid}.zip.[0-9][0-9][0-9]"))
    if not parts:
        raise SystemExit(f"no {jid}.zip.001 in {h / 'inbox'}: copy the parts there first (CopyFromBox)")
    wd = h / "work" / jid
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    ob = h / "outbox" / jid
    shutil.rmtree(ob, ignore_errors=True)
    ob.mkdir(parents=True)

    def send(snap):
        atomic_json(ob / "status.json", {"id": jid, "state": "running", **snap, "updated": time.time()})
        return {"cancel": (h / "outbox" / jid / "cancel").exists()}

    rep = Reporter(send, wd / "log.txt")
    res: dict = {"state": "failed"}
    with rep:
        try:
            bundle = join_parts(parts, wd / "bundle.zip")
            safe_extract(bundle, wd)
            bundle.unlink()
            m = validate_manifest(read_json(wd / "manifest.json"), known_profiles=P.PROFILES)
            if m["id"] != jid:
                raise ManifestError("bundle id does not match")
            for f in m["inputs"]:
                p = wd / "in" / f["name"]
                if not p.is_file() or p.stat().st_size != f["size"] or sha256_file(p) != f["sha256"]:
                    raise ManifestError(f"input {f['name']} is missing or damaged")
            c = cfg()
            res = execute(m, wd, rep, c, G.backend())
        except Exception as e:  # noqa: BLE001
            res = {"state": "failed", "error": f"{type(e).__name__}: {e}"[:1500]}
        finally:
            close_host(force=True)
    out = wd / "out"
    out.mkdir(exist_ok=True)
    status = {"id": jid, "state": res["state"], "error": res.get("error"), "metrics": res.get("metrics"),
              "result": res.get("result"), "log_tail": rep.tail(4000)}
    z = ob / f"{jid}-out.zip"
    with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr("status.json", json.dumps(status, default=str))
        if res["state"] == "succeeded":
            for f in list_outputs(out):
                zf.write(out / f["name"], f["name"])
    plist = [{"name": p.name, "size": p.stat().st_size, "sha256": sha256_file(p)} for p in split_file(z, PART)]
    z.unlink()
    done = {"id": jid, "state": res["state"], "error": res.get("error"), "parts": plist,
            "folder": str(ob), "metrics": res.get("metrics")}
    atomic_json(ob / "done.json", done)
    (ob / "status.json").unlink(missing_ok=True)
    for sub in ("in", "out", "frames-in", "frames-out"):
        shutil.rmtree(wd / sub, ignore_errors=True)
    return done


def bundle_status(jid: str) -> dict:
    valid_id(jid)
    ob = home() / "outbox" / jid
    done = read_json(ob / "done.json")
    if done:
        return {**done, "finished": True}
    st = read_json(ob / "status.json")
    if st:
        st.pop("log_tail", None)
        return {**st, "finished": False}
    return {"id": jid, "finished": False, "state": "not-started",
            "hint": f"run: slopgpu run-bundle {jid} --detach (after copying {jid}.zip.001... into {home() / 'inbox'})"}


# ------------------------------------------------------------------------------------------------ process control
def detach(args: list[str], logname: str) -> int:
    h = home()
    (h / "logs").mkdir(parents=True, exist_ok=True)
    out = open(h / "logs" / logname, "ab")
    exe = console_python()
    env = dict(os.environ, SLOPGPU_ECHO="0", PYTHONPATH=str(h / "app"))
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT, "env": env, "cwd": str(h)}
    if IS_WIN:
        # python.exe in a hidden console of its own (CREATE_NO_WINDOW; NOT pythonw/DETACHED_PROCESS, whose console
        # children each open a visible window): it outlives the terminal that started it, and nvidia-smi, uv and the
        # GPU host it runs share that hidden console
        flags = 0x00000200 | 0x08000000                           # NEW_PROCESS_GROUP | NO_WINDOW
        try:
            p = subprocess.Popen([exe, "-m", "slop.gpu.worker", *args], creationflags=flags | 0x01000000, **kw)
        except OSError:                                           # breakaway from a parent job not allowed
            p = subprocess.Popen([exe, "-m", "slop.gpu.worker", *args], creationflags=flags, **kw)
    else:
        p = subprocess.Popen([exe, "-m", "slop.gpu.worker", *args], start_new_session=True, **kw)
    return p.pid


def pid_alive(pid) -> bool:
    if not pid:
        return False
    if IS_WIN:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True, **NOWIN)
        return str(int(pid)) in r.stdout
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def running_pid() -> int | None:
    st = read_json(home() / "state.json", {}) or {}
    pid = st.get("pid")
    if pid and pid_alive(pid) and st.get("state") not in ("stopped", "unpaired"):
        return int(pid)
    return None


def stop() -> dict:
    h = home()
    (h / "stop").write_text("stop", encoding="utf-8")
    pid = running_pid()
    for _ in range(60):
        if not running_pid():
            break
        time.sleep(0.5)
    if running_pid():
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, **NOWIN)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(1)
    if not running_pid():
        set_state(state="stopped", pid=None)
    return {"stopped": bool(pid), "running": bool(running_pid())}


def hello(url: str, token: str, worker_id: str, wait_s: float = 90) -> dict:
    url = check_box_url(url)
    api = Api(url, token, worker_id)
    c = cfg()
    gl = G.detect()
    _, rows = G.pick(gl, pin=c.get("gpu_uuid"), busy_mib=c["busy_mib"], busy_util=c["busy_util"])
    t_end = time.monotonic() + wait_s
    while True:
        try:
            return api.call("POST", "/gpu/api/hello", {"info": worker_info(c, rows, G.backend(gl))}, timeout=30)
        except Unpaired:
            raise SystemExit("the box refused this pairing code (expired, already used by another computer, or "
                             "replaced): on the box run `slop gpu pair --new` and paste the new line here") from None
        except Unreachable as e:          # a new quick-tunnel hostname can take a few seconds to resolve
            if time.monotonic() > t_end:
                raise SystemExit(f"cannot reach the box at {url}: {e}. Is `slop gpu serve` still running on the box? "
                                 "Get a fresh line with `slop gpu pair --refresh`.") from None
            time.sleep(3)


def pair_with(url: str, token: str, worker_id: str) -> dict:
    """hello with the pasted bootstrap code -> store the worker's own secret (never the pasted code) in pairing.json."""
    url = check_box_url(url)
    r = hello(url, token, worker_id)
    secret = r.get("secret") if isinstance(r, dict) else None
    save_pairing({"url": url, "token": secret or token, "worker_id": worker_id, "paired_at": time.time()})
    return r


# ------------------------------------------------------------------------------------------------ CLI
def _status() -> dict:
    c, pr = cfg(), pairing()
    gl = G.detect()
    backend = G.backend(gl)
    chosen, rows = G.pick(gl, pin=c.get("gpu_uuid"), busy_mib=c["busy_mib"], busy_util=c["busy_util"])
    st = read_json(home() / "state.json", {}) or {}
    return {"home": str(home()), "paired": bool(pr.get("token")),
            "box": urllib.parse.urlparse(pr.get("url", "")).netloc or None, "running": bool(running_pid()),
            "state": st.get("state"), "why": st.get("why"), "job": st.get("job"), "backend": backend, "gpus": rows,
            "picked": chosen["name"] if chosen else None, "pinned": bool(c.get("gpu_uuid")),
            "profiles": {k: v for k, v in P.status(home(), backend).items() if v["supported"]}, "code": code_hash()}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_jobproc"]:
        return _jobproc(argv[2:] if argv[1:2] == ["--"] else argv[1:])
    ap = argparse.ArgumentParser(prog="slopgpu", description="Claudia GPU worker")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    sub.add_parser("gpus")
    sub.add_parser("start")
    sub.add_parser("stop")
    r = sub.add_parser("run")
    r.add_argument("--once", action="store_true")
    lg = sub.add_parser("logs")
    lg.add_argument("--lines", type=int, default=40)
    p = sub.add_parser("pair")
    p.add_argument("--url", required=True)
    p.add_argument("--token-env", default="SLOPGPU_TOKEN")
    p.add_argument("--no-start", action="store_true")
    u = sub.add_parser("url")
    u.add_argument("url")
    sub.add_parser("unpair")
    pn = sub.add_parser("pin")
    pn.add_argument("gpu", help="a GPU UUID, an index from `slopgpu gpus`, or auto")
    i = sub.add_parser("install")
    i.add_argument("profile")
    i.add_argument("--accept-licence", action="store_true")
    i.add_argument("--force", action="store_true")
    i.add_argument("--detach", action="store_true")
    b = sub.add_parser("run-bundle")
    b.add_argument("job")
    b.add_argument("--detach", action="store_true")
    bs = sub.add_parser("bundle-status")
    bs.add_argument("job")
    a = ap.parse_args(argv)
    h = home()
    h.mkdir(parents=True, exist_ok=True)
    out: dict
    if a.cmd in (None, "status"):
        out = _status()
    elif a.cmd == "gpus":
        c = cfg()
        gl = G.detect()
        chosen, rows = G.pick(gl, pin=c.get("gpu_uuid"), busy_mib=c["busy_mib"], busy_util=c["busy_util"])
        out = {"gpus": [{**r, "uuid": g["uuid"]} for r, g in zip(rows, gl)], "picked": chosen["name"] if chosen else None,
               "blocked": None if chosen else G.blocked_text(rows, c.get("gpu_uuid"))}
    elif a.cmd == "start":
        if running_pid():
            out = {"running": True, "pid": running_pid(), "note": "already running"}
        else:
            pid = detach(["run"], "worker.out.log")
            time.sleep(2)
            out = {"running": pid_alive(pid), "pid": pid, "log": str(h / "logs" / "worker.log")}
    elif a.cmd == "stop":
        out = stop()
    elif a.cmd == "run":
        return run_loop(once=a.once)
    elif a.cmd == "logs":
        f = h / "logs" / "worker.log"
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-a.lines:] if f.is_file() else []
        print("\n".join(lines))
        return 0
    elif a.cmd == "pair":
        tok = os.environ.get(a.token_env, "").strip()
        if not tok:
            raise SystemExit(f"set {a.token_env} to the pairing code first (the line from `slop gpu pair` does this)")
        url = check_box_url(a.url)
        wid = pairing().get("worker_id") or hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        r = pair_with(url, tok, wid)
        out = {"paired": True, "box": urllib.parse.urlparse(url).netloc, "worker_id": wid, "server": r.get("server")}
        if not a.no_start:
            stop() if running_pid() else None
            out["pid"] = detach(["run"], "worker.out.log")
    elif a.cmd == "url":
        pr = pairing()
        if not pr.get("token"):
            raise SystemExit("not paired yet: run the full pairing line from `slop gpu pair`")
        url = check_box_url(a.url)
        hello(url, pr["token"], pr["worker_id"])
        pr["url"] = url
        save_pairing(pr)
        if running_pid():
            stop()
        out = {"paired": True, "box": urllib.parse.urlparse(url).netloc, "pid": detach(["run"], "worker.out.log")}
    elif a.cmd == "unpair":
        stop()
        (h / "pairing.json").unlink(missing_ok=True)
        out = {"unpaired": True}
    elif a.cmd == "pin":
        c = cfg()
        if a.gpu == "auto":
            c["gpu_uuid"] = None
        else:
            gl = G.detect()
            g = next((x for x in gl if x["uuid"] == a.gpu or str(x["index"]) == a.gpu), None)
            if not g:
                raise SystemExit(f"no GPU {a.gpu!r}; see `slopgpu gpus`")
            c["gpu_uuid"] = g["uuid"]
        save_cfg(c)
        out = {"pinned": c["gpu_uuid"] is not None}
    elif a.cmd == "install":
        if a.detach:
            args = ["install", a.profile] + (["--accept-licence"] if a.accept_licence else []) + \
                   (["--force"] if a.force else [])
            out = {"started": True, "pid": detach(args, f"install-{a.profile}.log"),
                   "log": str(h / "logs" / f"install-{a.profile}.log")}
        else:
            out = P.install(a.profile, h, uv_path(), G.backend(), log=log, accept_licence=a.accept_licence,
                            force=a.force, app_dir=h / "app")
    elif a.cmd == "run-bundle":
        if a.detach:
            out = {"started": True, "pid": detach(["run-bundle", a.job], f"bundle-{a.job[:8]}.log"),
                   "poll": f"slopgpu bundle-status {a.job}"}
        else:
            out = run_bundle(a.job)
    elif a.cmd == "bundle-status":
        out = bundle_status(a.job)
    else:
        ap.print_help()
        return 2
    print(json.dumps(out, default=str))
    return 0


def _jobproc(cmd: list[str]) -> int:
    """Windows: put this process in a Job Object that kills all descendants when it closes, then run cmd."""
    _handle = None
    try:
        _handle = _job_object()
    except OSError as e:
        print(f"[worker] no Job Object ({e}); the job still runs, cancel uses taskkill /T", flush=True)
    # pass our std handles EXPLICITLY: with none given, a console child of a console-less parent gets a NEW console's
    # handles - the warm host would then never see the jobs written to our stdin pipe
    try:
        return subprocess.run(cmd, stdin=0, stdout=1, stderr=2, **NOWIN).returncode
    except (OSError, ValueError):
        return subprocess.run(cmd, **NOWIN).returncode


def _job_object():
    import ctypes
    from ctypes import wintypes as w

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class EXT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateJobObjectW.restype = w.HANDLE
    k.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    k.GetCurrentProcess.restype = w.HANDLE
    h = k.CreateJobObjectW(None, None)
    info = EXT()
    info.BasicLimitInformation.LimitFlags = 0x2000                 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not h or not k.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info)) \
            or not k.AssignProcessToJobObject(h, k.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    return h


if __name__ == "__main__":
    sys.exit(main())
