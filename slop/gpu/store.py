"""The box's GPU state on disk ($SLOP_HOME/gpu): the durable FIFO job queue, the pairing codes and the worker's
last heartbeat. Every change to a job happens under one cross-process lock (gpu/queue.lock), so the job server's
threads, `slop gpu ...` commands and a waiting `slop analyze` never step on each other.

  gpu/config.json   {"mode": "paired"|"direct"|"none"}  gpu/pairing.json {"codes": [{"sha256", "created", "kind"}]}
  gpu/worker.json   the worker's last heartbeat (GPUs, profiles, state, measured network speed; never secrets)
  gpu/jobs/<id>/job.json + in/ (inputs, deleted when the job ends) + out/ (outputs)

Job states: queued -> assigned -> running -> succeeded | failed | cancelled | interrupted | timed_out. A job whose
worker stops heartbeating for LEASE_S goes back to the queue (at most MAX_ATTEMPTS tries), then ends "interrupted".
Job ids are 32 hex digits; every command also takes a unique first 6 or more (the progress lines show 8).

Pairing: codes are stored ONLY as sha256 digests. `slop gpu pair` prints a BOOTSTRAP code once (kind "boot"): it can
only fetch the installer and the worker code and say hello. The hello trades it for the worker's own secret (kind
"worker", kept on the PC in its private pairing.json only), and the worker's first poll with that secret retires the
bootstrap code - the copy left in the user's shell history stops working within seconds. An unused bootstrap code
expires after BOOT_TTL_S.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

from ..config import SlopError, slop_home
from . import proto
from .proto import ACTIVE, TERMINAL, atomic_json, read_json

LEASE_S = 120
MAX_ATTEMPTS = 2
WORKER_FRESH_S = 60
KEEP_JOBS = 60
KEEP_DAYS = 7
BOOT_TTL_S = 24 * 3600              # an unused pairing line works this long


def gdir() -> Path:
    d = slop_home() / "gpu"
    d.mkdir(parents=True, exist_ok=True)
    return d


def gpath() -> Path:
    """$SLOP_HOME/gpu WITHOUT creating it: read-only checks (status, routing) leave no trace on a box with no GPU."""
    return slop_home() / "gpu"


def jobs_dir() -> Path:
    d = gdir() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def job_dir(jid: str) -> Path:
    return jobs_dir() / proto.valid_id(jid)


@contextmanager
def locked(timeout: float = 20.0):
    path = gdir() / "queue.lock"
    fh = open(path, "a+b")
    t_end = time.monotonic() + timeout
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > t_end:
                    raise SlopError("the GPU queue is locked by another process for too long; retry in a minute")
                time.sleep(0.02)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        fh.close()


# ------------------------------------------------------------------------------------------------ config + pairing
def config() -> dict:
    return read_json(gpath() / "config.json", {}) or {}


def save_config(**kw) -> dict:
    c = config()
    c.update(kw)
    atomic_json(gdir() / "config.json", c)
    return c


def mode() -> str:
    return config().get("mode") or "none"


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _codes() -> list[dict]:
    return (read_json(gpath() / "pairing.json", {}) or {}).get("codes") or []


def _save_codes(codes: list[dict]) -> None:
    p = gdir() / "pairing.json"
    atomic_json(p, {"codes": codes})
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _live(c: dict, now: float | None = None) -> bool:
    if c.get("kind", "boot") != "boot":
        return True
    return (now or time.time()) - float(c.get("created") or 0) <= BOOT_TTL_S


def new_code() -> str:
    """A fresh BOOTSTRAP code for the one line the user pastes. It replaces every earlier code AND the paired worker's
    secret (one paired computer at a time: the old worker is refused on its next poll, so its last heartbeat is
    dropped too - status must not call a cut-off worker healthy). Only its hash is kept."""
    code = secrets.token_urlsafe(24)
    with locked():
        _save_codes([{"sha256": _digest(code), "created": time.time(), "kind": "boot"}])
        (gdir() / "worker.json").unlink(missing_ok=True)
    return code


def new_worker_secret(worker_id: str) -> str:
    """/gpu/api/hello with a bootstrap code: mint the worker's own secret (it replaces an earlier worker secret)."""
    secret = secrets.token_urlsafe(32)
    with locked():
        codes = [c for c in _codes() if c.get("kind", "boot") == "boot" and _live(c)]
        codes.append({"sha256": _digest(secret), "created": time.time(), "kind": "worker", "worker_id": worker_id})
        _save_codes(codes)
    return secret


def check_code(code: str | None) -> str | None:
    """-> "boot" | "worker" for a valid code (constant-time compare), else None (bad, revoked or expired)."""
    if not code:
        return None
    digest = _digest(code)
    now = time.time()
    for c in _codes():
        if hmac.compare_digest(digest, c.get("sha256", "")):
            return c.get("kind", "boot") if _live(c, now) else None
    return None


def retire_boot() -> None:
    """The worker polled with its own secret: the bootstrap code (still in the user's shell history) stops working."""
    if not any(c.get("kind", "boot") == "boot" for c in _codes()):
        return                                    # the usual case: nothing to write, no lock taken
    with locked():
        codes = _codes()
        keep = [c for c in codes if c.get("kind", "boot") != "boot"]
        if len(keep) != len(codes):
            _save_codes(keep)


def has_code() -> bool:
    """A computer is paired, or a pairing line is still waiting to be used."""
    now = time.time()
    return any(_live(c, now) for c in _codes())


def note_refused(worker_id: str) -> None:
    """The server refused this worker's code: it now knows it is unpaired and stops (newest 16 workers kept)."""
    p = gdir() / "refused.json"
    d = read_json(p, {}) or {}
    d[worker_id] = time.time()
    atomic_json(p, dict(sorted(d.items(), key=lambda kv: kv[1])[-16:]))


def refused_since(worker_id: str, since: float) -> bool:
    return float((read_json(gpath() / "refused.json", {}) or {}).get(worker_id) or 0) >= since


def revoke() -> bool:
    p = gdir() / "pairing.json"
    had = has_code()
    if p.exists():
        p.unlink()
    w = gdir() / "worker.json"
    if w.exists():
        w.unlink()
    return had


# ------------------------------------------------------------------------------------------------ worker heartbeat
def save_worker(worker_id: str, info: dict, **extra) -> None:
    info = dict(info or {})
    keep = {k: info.get(k) for k in ("proto", "code", "os", "arch", "python", "backend", "pinned", "gpus", "profiles",
                                     "busy_mib", "busy_util", "net")}
    w = read_json(gdir() / "worker.json", {}) or {}
    w.update({k: v for k, v in keep.items() if v is not None})
    w.update(worker_id=worker_id, seen=time.time(), **extra)
    atomic_json(gdir() / "worker.json", w)


def touch_worker(worker_id: str, **extra) -> None:
    w = read_json(gdir() / "worker.json", {}) or {}
    w.update(worker_id=worker_id, seen=time.time(), **extra)
    atomic_json(gdir() / "worker.json", w)


def worker() -> dict:
    w = read_json(gpath() / "worker.json", {}) or {}
    if w.get("seen"):
        w["age_s"] = round(time.time() - w["seen"], 1)
        w["fresh"] = w["age_s"] <= WORKER_FRESH_S
    return w


# ------------------------------------------------------------------------------------------------ jobs
def resolve(jid: str) -> str:
    """A job id as typed: the full 32 hex digits, or a unique first 6 or more (the progress lines show 8). -> full id."""
    s = str(jid or "").strip().lower()
    if proto.ID_RE.match(s):
        return s
    if not re.match(r"^[0-9a-f]{6,31}$", s):
        raise SlopError(f"no GPU job {str(jid)[:40]!r}: a job id is 32 hex digits (a unique first 6 or more also "
                        "works); `slop gpu jobs` lists them")
    jd = gpath() / "jobs"
    hits = sorted(p.name for p in jd.glob(s + "*") if proto.ID_RE.match(p.name)) if jd.is_dir() else []
    if not hits:
        raise SlopError(f"no GPU job starting with {s}: `slop gpu jobs --all` lists them (finished jobs are pruned "
                        f"after {KEEP_DAYS} days)")
    if len(hits) > 1:
        raise SlopError(f"{s} matches {len(hits)} GPU jobs ({', '.join(h[:12] for h in hits[:4])}): give more digits "
                        "(`slop gpu jobs` lists the full ids)")
    return hits[0]


def get(jid: str) -> dict:
    jid = resolve(jid)
    j = read_json(job_dir(jid) / "job.json")
    if not j:
        raise SlopError(f"no GPU job {jid} (list them with `slop gpu jobs`)")
    return j


def _save(j: dict) -> dict:
    j["updated"] = time.time()
    atomic_json(job_dir(j["id"]) / "job.json", j)
    return j


def _next_seq() -> int:
    p = gdir() / "seq"
    try:
        n = int(p.read_text().strip()) + 1
    except (OSError, ValueError):
        n = 1
    p.write_text(str(n))
    return n


def submit(entry: str | None = None, inputs: dict | None = None, params: dict | None = None, kind: str = "run",
           profile: str | None = None, force_gpu: bool = False, timeout_s: int | None = None, origin: str = "",
           accept_licence: bool = False) -> dict:
    """Queue a job. inputs: {name: local Path}; the files are copied into the job folder (the queue owns them)."""
    jid = proto.new_id()
    d = jobs_dir() / jid
    (d / "in").mkdir(parents=True)
    (d / "out").mkdir()
    files = []
    try:
        for name, src in (inputs or {}).items():
            proto.safe_name(name)
            src = Path(src)
            if not src.is_file():
                raise SlopError(f"input {name}: no file {src}")
            dst = d / "in" / name
            try:
                os.link(src, dst)
            except OSError:
                shutil.copyfile(src, dst)
            files.append(proto.file_entry(dst, name))
        if kind == "install":
            from .profiles import PROFILES
            if profile not in PROFILES:
                raise SlopError(f"unknown profile {profile!r}; choose from {', '.join(PROFILES)}")
            m = {"v": proto.PROTO, "id": jid, "kind": "install", "profile": profile, "timeout_s": timeout_s or 4 * 3600,
                 "accept_licence": accept_licence}
        else:
            if entry not in proto.ENTRIES:
                raise SlopError(f"unknown GPU entry {entry!r}; choose from {', '.join(sorted(proto.ENTRIES))}")
            m = {"v": proto.PROTO, "id": jid, "kind": "run", "entry": entry, "params": params or {}, "inputs": files,
                 "timeout_s": timeout_s or proto.ENTRIES[entry]["timeout"], "force_gpu": force_gpu}
        mm = proto.validate_manifest(m)
    except proto.ManifestError as e:
        shutil.rmtree(d, ignore_errors=True)
        raise SlopError(f"bad GPU job: {e}") from None
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    with locked():
        j = {**mm, "state": "queued", "seq": _next_seq(), "created": time.time(), "origin": origin, "attempts": 0,
             "phase": None, "progress": None, "events": []}
        if kind == "install":
            j["accept_licence"] = accept_licence
        _save(j)
    prune()
    return j


def manifest(j: dict) -> dict:
    keys = ("v", "id", "kind", "entry", "profile", "params", "inputs", "timeout_s", "force_gpu", "accept_licence")
    return {k: j[k] for k in keys if k in j and j[k] is not None}


def all_jobs() -> list[dict]:
    out = []
    for p in (gpath() / "jobs").glob("*/job.json"):
        j = read_json(p)
        if j and proto.ID_RE.match(j.get("id", "")):
            out.append(j)
    return sorted(out, key=lambda j: j.get("seq", 0))


def expire_leases(now: float | None = None) -> list[str]:
    """Jobs whose worker went silent: back to the queue, or 'interrupted' after MAX_ATTEMPTS. Call under the lock."""
    now = now or time.time()
    moved = []
    for j in all_jobs():
        if j["state"] in ACTIVE and now - j.get("updated", now) > LEASE_S:
            j["attempts"] = j.get("attempts", 0) + 1
            if j["attempts"] >= MAX_ATTEMPTS or j.get("mode") == "direct":
                j.update(state="interrupted", finished=now,
                         error=f"the worker stopped reporting for {LEASE_S} s (PC asleep, worker stopped or tunnel down)")
                _cleanup_inputs(j["id"])
            else:
                j.update(state="queued", phase=None, worker_id=None, progress=None)
            _event(j, "lease expired")
            _save(j)
            moved.append(j["id"])
    return moved


def _event(j: dict, text: str) -> None:
    ev = j.setdefault("events", [])
    ev.append([round(time.time(), 1), text[:200]])
    del ev[:-25]


def next_job(worker_id: str, gpu_ok: bool, why: str | None = None) -> dict | None:
    """FIFO: the oldest queued job this worker may take now. A run job needs a free GPU (gpu_ok) unless forced;
    an install job does not. Jobs that must wait record why (`slop gpu status` / the waiting analyze show it)."""
    with locked():
        expire_leases()
        for j in all_jobs():                  # this worker asks for work, so it is not running anything: a job it
            if j["state"] in ACTIVE and j.get("worker_id") == worker_id:     # held died with it (restart/crash)
                j["attempts"] = j.get("attempts", 0) + 1
                if j["attempts"] >= MAX_ATTEMPTS:
                    j.update(state="interrupted", finished=time.time(), error="the worker restarted during the job")
                    _cleanup_inputs(j["id"])
                else:
                    j.update(state="queued", phase=None, worker_id=None, progress=None)
                _event(j, "worker restarted")
                _save(j)
        if any(j["state"] in ACTIVE for j in all_jobs()):
            return None                       # one job at a time on the GPU
        for j in all_jobs():
            if j["state"] != "queued" or j.get("mode") == "direct":
                continue
            if j["kind"] == "run" and not gpu_ok and not j.get("force_gpu"):
                if j.get("blocked") != why:
                    j["blocked"] = why
                    _save(j)
                continue
            j.update(state="assigned", worker_id=worker_id, assigned=time.time(), blocked=None, phase="assigned")
            _event(j, "assigned to the worker")
            _save(j)
            return j
    return None


def _owned(j: dict, worker_id: str) -> None:
    if j.get("worker_id") != worker_id or j["state"] not in ACTIVE:
        raise SlopError(f"job {j['id'][:8]} is not running on this worker (state {j['state']})")


def event(jid: str, worker_id: str, body: dict) -> dict:
    with locked():
        j = get(jid)
        if j["state"] in TERMINAL:
            return {"cancel": True, "state": j["state"]}
        _owned(j, worker_id)
        if body.get("release"):                       # the worker found every GPU busy: back to the queue
            j.update(state="queued", worker_id=None, phase=None, blocked=str(body.get("why") or "GPU busy")[:400])
            _event(j, "handed back: GPU busy")
            _save(j)
            return {"cancel": False}
        ph = str(body.get("phase") or "running")[:20]
        if ph != j.get("phase"):
            _event(j, f"phase {ph}")
        j.update(state="running", phase=ph, progress=body.get("progress"))
        if j.get("started") is None and ph in ("downloading", "installing", "running"):
            j["started"] = time.time()
        for k in ("gpu", "vram_used_peak_mib", "profile"):
            if body.get(k) is not None:
                j[k] = body[k]
        if body.get("log_tail"):
            j["log_tail"] = str(body["log_tail"])[-3000:]
        _save(j)
        return {"cancel": bool(j.get("cancel_requested"))}


def out_part(jid: str, name: str) -> Path:
    return job_dir(jid) / "out" / (proto.safe_name(name) + ".part")


def write_chunk(jid: str, worker_id: str, name: str, offset: int, data: bytes) -> int:
    j = get(jid)
    _owned(j, worker_id)
    p = out_part(jid, name)
    size = p.stat().st_size if p.exists() else 0
    if offset < 0 or offset > size:          # offset < size = a retried piece: it is written again
        raise SlopError(f"upload of {name}: expected offset {size}, got {offset}")
    if offset + len(data) > proto.MAX_FILE:
        raise SlopError(f"upload of {name} exceeds the per-file cap")
    total = sum(f.stat().st_size for f in (job_dir(jid) / "out").glob("*") if f.is_file())
    if total + len(data) > proto.MAX_TOTAL:
        raise SlopError("outputs exceed the per-job cap")
    with open(p, "r+b" if p.exists() and offset else "wb") as f:
        f.seek(offset)
        f.write(data)
        f.truncate()
    return offset + len(data)


def finish(jid: str, worker_id: str | None, body: dict) -> dict:
    """The worker's final report (or direct-ingest). Outputs are checked against their size and sha256."""
    with locked():
        j = get(jid)
        if j["state"] in TERMINAL:
            return j
        if worker_id is not None:
            _owned(j, worker_id)
        state = body.get("state")
        if state not in TERMINAL:
            state = "failed"
        outs = []
        err = body.get("error")
        if state == "succeeded":
            try:
                outs = _accept_outputs(jid, body.get("outputs") or [])
            except (SlopError, proto.ManifestError) as e:
                state, err = "failed", f"outputs did not arrive intact: {e}"
        j.update(state=state, finished=time.time(), outputs=outs, error=(str(err)[:2000] if err else None),
                 result=body.get("result"), metrics=body.get("metrics"), phase=None, progress=None)
        if body.get("log_tail"):
            j["log_tail"] = str(body["log_tail"])[-4000:]
        _event(j, f"finished: {state}")
        _save(j)
        _cleanup_inputs(jid)
        return j


def _accept_outputs(jid: str, listed: list) -> list[dict]:
    out = job_dir(jid) / "out"
    good = []
    for f in listed:
        name = proto.safe_name(f.get("name"))
        part = out / (name + ".part")
        final = out / name
        src = part if part.exists() else final
        if not src.exists():
            raise SlopError(f"{name} missing")
        if src.stat().st_size != f.get("size") or proto.sha256_file(src) != f.get("sha256"):
            raise SlopError(f"{name} size/checksum mismatch")
        if src is part:
            os.replace(part, final)
        good.append({"name": name, "size": f["size"], "sha256": f["sha256"]})
    for stray in out.glob("*.part"):
        stray.unlink()
    return good


def _cleanup_inputs(jid: str) -> None:
    shutil.rmtree(job_dir(jid) / "in", ignore_errors=True)


def cancel(jid: str) -> dict:
    jid = resolve(jid)
    with locked():
        j = get(jid)
        if j["state"] in TERMINAL:
            return j
        if j["state"] == "queued":
            j.update(state="cancelled", finished=time.time())
            _cleanup_inputs(jid)
        else:
            j["cancel_requested"] = True
        _event(j, "cancel requested")
        return _save(j)


def cancel_open() -> list[str]:
    """Cancel every job that has not ended (unpair): queued ones at once, running ones on the worker's next beat."""
    out = []
    for j in all_jobs():
        if j["state"] not in TERMINAL:
            cancel(j["id"])
            out.append(j["id"])
    return out


def mark_direct(jid: str) -> dict:
    jid = resolve(jid)
    with locked():
        j = get(jid)
        if j["state"] == "queued":
            j.update(mode="direct", phase="waiting-for-pc")
            _event(j, "handed to direct mode")
            _save(j)
        return j


def prune(keep: int = KEEP_JOBS, days: float = KEEP_DAYS) -> int:
    """Delete finished jobs beyond the newest `keep` or older than `days` (their folders hold stems and maps)."""
    done = [j for j in all_jobs() if j["state"] in TERMINAL]
    old = time.time() - days * 86400
    drop = done[:-keep] if len(done) > keep else []
    drop += [j for j in done[-keep:] if (j.get("finished") or 0) < old]
    for j in drop:
        shutil.rmtree(jobs_dir() / j["id"], ignore_errors=True)
    return len(drop)
