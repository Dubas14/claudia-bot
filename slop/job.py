"""Background jobs: run any long `slop` step DETACHED, so it survives the shell call that started it.

The Grok Bot computer's shell has a foreground timeout (unknown length; local exec is 30 s), and the long steps take
minutes: analyze, edit export, render frames / vertical / lyrics / encode / check, taste embed. Start them as jobs:

  slop --project NAME job start -- analyze          prints the job id at once (e.g. analyze-k3f9); the step runs on
  slop --project NAME job wait analyze-k3f9         blocks at most --max seconds (default 25), then says "running" or
                                                    gives the step's own result; call it again until it is finished
  slop --project NAME job status last               same, without waiting ("last" = the newest job)
  slop --project NAME job list                      this project's jobs
  slop --project NAME job stop ID                   stops it (SIGTERM to its process group, SIGKILL after --grace s)
  slop --project NAME job log ID                    the tail of its log (stderr of the step)
  slop job selftest                                 proves that a job outlives the shell that started it (~5 s)
  slop job selftest --start                         THE BOX TEST (two calls): starts a 150 s test job and returns at once;
  slop job selftest --check [ID]                    in the NEXT tool call it must say RUNNING; end the turn; in a later
                                                    turn (>= 150 s on) it must say PASS. `selftest` alone runs inside one
                                                    shell call, so it cannot catch a computer that kills a call's (or a
                                                    turn's) processes when it ends; this one can. State:
                                                    $SLOP_HOME/run/selftest.json

Files (contract), in <project>/jobs/ (or $SLOP_HOME/jobs/ for a command without a project):
  <id>.json           {id, project, argv, cmd, cwd, started, started_ts, pid, pid_start, supervisor_pid, pgid, state,
                       progress{done,total,eta,msg}, exit, finished, elapsed_s, result, error, log, out, progress_file}
                      state: starting | running | done | failed | stopped. `result` = the step's own --json output.
  <id>.log            the step's stderr + the supervisor's own lines
  <id>.out            the step's stdout (its one JSON object)
  <id>.progress.json  progress the step MAY write: the step finds the path in env SLOP_PROGRESS_FILE and writes
                      {"done": n, "total": n, "eta_s": seconds|null, "msg": "...", "stage": "..."} through
                      slop/progress.py (the shared writer the render steps use; write_progress() below wraps it;
                      "eta" is read too). `slop analyze` progress is read from analysis/progress.json when the step
                      writes nothing here.
  <id>.stop           written by `job stop` (so a stopped job is reported "stopped", not "failed")

How it detaches: POSIX = double fork + setsid (the supervisor is reparented to init, has no controlling terminal and
ignores SIGHUP; its process group holds the step and everything the step starts); Windows = DETACHED_PROCESS +
CREATE_NEW_PROCESS_GROUP (+ CREATE_BREAKAWAY_FROM_JOB when allowed). The supervisor runs `python -m slop --json
--project <abs path> <argv>`, waits for it and records exit + result. A job whose processes are gone without a
recorded exit (killed, out of memory, computer restarted) is reported "failed" (pid reuse is caught by comparing the
process start time on Linux).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import util
from .config import SlopError, resolve_project, slop_home, toolkit_root

TERMINAL = ("done", "failed", "stopped")
ID_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
DEFAULT_WAIT = 25.0
MAX_RESULT_CHARS = 200_000
START_CONFIRM_S = 10.0         # how long `job start` waits for the supervisor to report the step's pid
UNSEEN_WINDOW_S = 24 * 3600    # finished jobs nobody has read yet are shown by `slop status` for a day


def default_wait() -> float:
    """--max default: 25 s (under the bot shell's foreground timeout); SLOP_WAIT_MAX overrides it on a known box."""
    try:
        return max(0.0, float(os.environ.get("SLOP_WAIT_MAX", DEFAULT_WAIT)))
    except ValueError:
        return DEFAULT_WAIT


# ====================================================================== progress (for the step itself)
def write_progress(done: float | None = None, total: float | None = None, msg: str | None = None,
                   eta: float | None = None, final: bool = False, stage: str | None = None) -> None:
    """Called by a long step to report progress; a no-op unless env SLOP_PROGRESS_FILE is set (it is, in a job).
    Goes through slop/progress.py (the shared writer: rate-limited, ETA per stage) when it is installed."""
    path = os.environ.get("SLOP_PROGRESS_FILE")
    if not path:
        return
    try:
        from . import progress as shared
    except ImportError:
        shared = None
    if shared is not None and hasattr(shared, "report"):
        try:
            if final and hasattr(shared, "end"):
                shared.end(done or 0, total or 0, msg or "", stage=stage)
            else:
                shared.report(done or 0, total or 0, msg or "", stage=stage)
        except Exception:  # noqa: BLE001 - progress is advisory
            pass
        return
    d = {"done": done, "total": total, "eta": eta, "msg": msg, "updated": round(time.time(), 3)}
    try:
        util.atomic_write_json(Path(path), d, indent=None)
    except OSError:
        pass


# ====================================================================== stores and records
def jobs_dir(pdir: Path | None) -> Path:
    return (Path(pdir) / "jobs") if pdir else slop_home() / "jobs"


def _project_or_none(name: str | None) -> Path | None:
    """The project named by --project / $SLOP_PROJECT / the cwd, or None (a job without a project is allowed)."""
    try:
        return resolve_project(name)
    except SlopError:
        if name or os.environ.get("SLOP_PROJECT"):
            raise
        return None


def _rec_path(store: Path, jid: str) -> Path:
    return store / f"{jid}.json"


def _read(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write(path: Path, rec: dict) -> None:
    util.atomic_write_json(path, rec)


def _all_stores(pdir: Path | None) -> list[Path]:
    """Where to look for a job id: the selected project, the global store, then every project's store."""
    from .config import projects_root
    out: list[Path] = []
    if pdir:
        out.append(jobs_dir(pdir))
    out.append(jobs_dir(None))
    root = projects_root()
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if (d / "jobs").is_dir():
                out.append(d / "jobs")
    seen, uniq = set(), []
    for s in out:
        k = str(s.resolve()) if s.exists() else str(s)
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return uniq


def order_key(rec: dict) -> tuple:
    """Oldest -> newest within one job folder: the sequence number `job start` takes (it only goes up, so a clock
    that steps backwards - a VM resumed from a snapshot - cannot reorder jobs), then the start time."""
    try:
        seq = int(rec.get("seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return seq, float(rec.get("started_ts") or 0)


def _records(store: Path) -> list[tuple[Path, dict]]:
    if not store.is_dir():
        return []
    out = []
    for f in store.glob("*.json"):
        if f.name.endswith(".progress.json"):
            continue
        r = _read(f)
        if r and r.get("id") == f.stem:
            out.append((f, r))
    out.sort(key=lambda fr: order_key(fr[1]))
    return out


def next_seq(store: Path, records: list[tuple[Path, dict]] | None = None) -> int:
    """The next job sequence number of a job folder, taken atomically (O_EXCL marker jobs/.seq/N; only the newest few
    markers are kept). Never below the records' own numbers, so a deleted .seq folder cannot restart the count."""
    sd = store / ".seq"
    sd.mkdir(parents=True, exist_ok=True)
    marks = [int(f.name) for f in sd.iterdir() if f.name.isdigit()]
    have = [order_key(r)[0] for _, r in (records if records is not None else _records(store))]
    n = max(marks + have + [0]) + 1
    for _ in range(10_000):
        try:
            fd = os.open(str(sd / str(n)), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        for m in marks:
            if m < n - 8:
                try:
                    (sd / str(m)).unlink()
                except OSError:
                    pass
        return n
    raise SlopError(f"could not number a job in {store}")  # pragma: no cover


def last_job(pdir: Path, argv: list[str]) -> dict | None:
    """The newest job of this project whose command is exactly argv (refreshed), or None."""
    want = list(argv or [])
    if not want:
        return None
    for path, rec in reversed(_records(jobs_dir(pdir))):
        if list(rec.get("argv") or []) == want:
            rec = refresh(path, rec)
            return {**summary(rec), "status_sig": rec.get("status_sig"), "finished": rec.get("finished")}
    return None


def find_job(jid: str, pdir: Path | None) -> tuple[Path, dict]:
    """The record of job `jid` ("last" = the newest one; a bare number N = the Nth newest is not supported)."""
    jid = (jid or "").strip()
    if not jid:
        raise SlopError("name the job: slop job status ID (ids are printed by `slop job start`; `slop job list` "
                        "shows them; `last` = the newest)")
    stores = _all_stores(pdir)
    if jid == "last":  # the newest by sequence number in each folder; across folders by start time
        cands = [recs[-1] for s in (stores[:1] if pdir else stores) if (recs := _records(s))]
        if not cands:
            raise SlopError("no jobs yet" + (f" in {jobs_dir(pdir)}" if pdir else "") +
                            ": start one with  slop --project NAME job start -- <command>")
        return max(cands, key=lambda fr: float(fr[1].get("started_ts") or 0))
    if not ID_RE.fullmatch(jid):
        raise SlopError(f"bad job id {jid!r}: ids look like analyze-k3f9 (see: slop job list)")
    for s in stores:
        p = _rec_path(s, jid)
        r = _read(p)
        if r:
            return p, r
    raise SlopError(f"no job {jid!r}" + (f" in {jobs_dir(pdir)}" if pdir else "") + " or any other job folder: "
                    "list them with  slop --project NAME job list")


# ====================================================================== processes
def _proc_stat(pid: int) -> dict | None:
    try:
        data = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    rest = data[data.rfind(")") + 2:].split()
    return {"state": rest[0], "start": rest[19]} if len(rest) > 19 else None


def proc_start(pid: int | None) -> str | None:
    """A token that changes when the pid is reused (Linux start time in clock ticks; None elsewhere)."""
    if not pid or os.name == "nt":
        return None
    st = _proc_stat(pid)
    return st["start"] if st else None


def _win_alive(pid: int) -> bool:  # pragma: no cover - Windows only
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def alive(pid: int | None, start: str | None = None) -> bool:
    if not pid:
        return False
    if os.name == "nt":  # pragma: no cover
        return _win_alive(pid)
    st = _proc_stat(pid)
    if st is not None:
        if st["state"] in ("Z", "X", "x"):
            return False
        return not (start and st["start"] != str(start))
    if Path("/proc/self/stat").exists():  # Linux, and no /proc entry: gone
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _child_env(extra: dict) -> dict:
    env = dict(os.environ)
    root = str(toolkit_root())
    pp = env.get("PYTHONPATH", "")
    if root not in pp.split(os.pathsep):
        env["PYTHONPATH"] = root + (os.pathsep + pp if pp else "")
    env["PYTHONUNBUFFERED"] = "1"
    env.update({k: str(v) for k, v in extra.items() if v is not None})
    return env


def _spawn_detached(argv: list[str], env: dict, cwd: str, log: Path) -> None:
    """Start argv fully detached from this process (double fork + setsid on POSIX)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":  # pragma: no cover - Windows only
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        with open(log, "ab") as lf:
            kw = {"stdin": subprocess.DEVNULL, "stdout": lf, "stderr": subprocess.STDOUT, "cwd": cwd, "env": env,
                  "close_fds": True}
            try:
                subprocess.Popen(argv, creationflags=flags | 0x01000000, **kw)  # + CREATE_BREAKAWAY_FROM_JOB
            except OSError:
                subprocess.Popen(argv, creationflags=flags, **kw)
        return
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # first child: new session, fork again, exit (the grandchild is reparented to init)
        code = 0
        try:
            os.close(r)
            os.setsid()
            if os.fork() == 0:  # the grandchild: becomes the supervisor
                try:
                    os.close(w)
                    fd = os.open(str(log), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
                    nul = os.open(os.devnull, os.O_RDONLY)
                    os.dup2(nul, 0)
                    os.dup2(fd, 1)
                    os.dup2(fd, 2)
                    os.closerange(3, 1024)
                    os.chdir(cwd)
                    os.execve(argv[0], argv, env)
                except BaseException as e:  # noqa: BLE001 - must never return into the caller's code
                    try:
                        os.write(2, f"[job] could not start the supervisor: {e}\n".encode())
                    finally:
                        os._exit(127)
            os.write(w, b"ok")
        except BaseException:  # noqa: BLE001
            code = 1
        finally:
            os._exit(code)
    os.close(w)
    try:
        while os.read(r, 64):
            pass
    finally:
        os.close(r)
    os.waitpid(pid, 0)


def _signal_group(rec: dict, sig: int) -> None:
    if os.name == "nt":  # pragma: no cover
        for pid in (rec.get("supervisor_pid"), rec.get("pid")):
            if pid:
                util.run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=30)
        return
    pg = rec.get("pgid")
    live = alive(rec.get("supervisor_pid"), rec.get("supervisor_start")) or alive(rec.get("pid"), rec.get("pid_start"))
    if pg and live:
        try:
            os.killpg(int(pg), sig)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    for key, start in (("pid", "pid_start"), ("supervisor_pid", "supervisor_start")):
        if alive(rec.get(key), rec.get(start)):
            try:
                os.kill(int(rec[key]), sig)
            except OSError:
                pass


# ====================================================================== state
def _parse_result(out: Path) -> dict | None:
    try:
        text = out.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed([ln for ln in text.splitlines() if ln.strip()]):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            return d
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else None
    except ValueError:
        return None


def _clip_result(res: dict | None, out: Path) -> dict | None:
    if res is None:
        return None
    s = json.dumps(res, ensure_ascii=False, default=str)
    if len(s) <= MAX_RESULT_CHARS:
        return res
    keep = {k: res[k] for k in ("ok", "error", "hint") if k in res}
    keep.update(text=str(res.get("text", ""))[:4000], truncated=True, full_result=str(out))
    return keep


def log_tail(rec: dict, lines: int = 15) -> str:
    try:
        text = Path(rec["log"]).read_text(encoding="utf-8", errors="replace")
    except (OSError, KeyError, TypeError):
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def read_progress(rec: dict) -> dict | None:
    """{done, total, eta, msg} from the job's progress file (or analysis/progress.json for analyze)."""
    d = _read(Path(rec["progress_file"])) if rec.get("progress_file") else None
    prog = None
    if d:
        prog = {"done": _num(d.get("done")), "total": _num(d.get("total")),
                "eta": _num(d.get("eta", d.get("eta_s"))),
                "msg": d.get("msg") or d.get("message") or d.get("step") or d.get("stage")}
    elif rec.get("project") and (rec.get("argv") or [None])[0] == "analyze":
        a = _read(Path(rec["project"]) / "analysis/progress.json")
        p = Path(rec["project"]) / "analysis/progress.json"
        try:
            fresh = p.stat().st_mtime + 2 >= float(rec.get("started_ts") or 0)
        except OSError:
            fresh = False
        if a and fresh and isinstance(a.get("steps"), list):
            done = len(a.get("done") or {})
            prog = {"done": done, "total": len(a["steps"]), "eta": None,
                    "msg": (f"step {a['step']}" if a.get("step") else None)}
    if prog is None:
        return rec.get("progress") if isinstance(rec.get("progress"), dict) else None
    if prog["eta"] is None and prog["done"] and prog["total"] and prog["done"] < prog["total"] \
            and rec.get("state") not in TERMINAL:
        el = max(1e-3, time.time() - float(rec.get("started_ts") or time.time()))
        prog["eta"] = round((prog["total"] - prog["done"]) * el / prog["done"], 1)
    return prog


def refresh(path: Path, rec: dict, mark_seen: bool = False) -> dict:
    """Bring a record up to date: live progress; a job whose processes are gone without a recorded exit is
    finalized as failed (or stopped, when `job stop` asked for it). Writes the record back when that changes it."""
    changed = False
    state = rec.get("state")
    stop_marker = path.with_suffix(".stop")
    if state not in TERMINAL:
        sup = alive(rec.get("supervisor_pid"), rec.get("supervisor_start"))
        wrk = alive(rec.get("pid"), rec.get("pid_start"))
        if not sup and not wrk:
            age = time.time() - float(rec.get("started_ts") or 0)
            if state == "starting" and not rec.get("supervisor_pid") and \
                    age < (START_CONFIRM_S if stop_marker.exists() else START_CONFIRM_S * 2):
                pass  # the supervisor may still be booting
            else:
                rec = _read(path) or rec  # the supervisor may have finalized it just now
                if rec.get("state") not in TERMINAL:
                    res = _parse_result(Path(rec["out"])) if rec.get("out") else None
                    if stop_marker.exists():
                        rec.update(state="stopped", error="stopped by `slop job stop`")
                    elif res is not None and res.get("ok", True) is not False:
                        rec.update(state="done", error=None, note="finished, but its exit code was not recorded")
                    else:
                        rec.update(state="failed", error=(res or {}).get("error") or
                                   "the job's processes ended without recording an exit (killed, out of memory, or "
                                   "the computer restarted)")
                    rec.update(exit=rec.get("exit"), finished=util.iso_now(),
                               elapsed_s=round(time.time() - float(rec.get("started_ts") or time.time()), 1),
                               result=_clip_result(res, Path(rec["out"])) if rec.get("out") else None)
                    changed = True
    prog = read_progress(rec)
    if prog is not None and prog != rec.get("progress"):
        rec["progress"] = prog
        changed = changed or rec.get("state") in TERMINAL
    if mark_seen and rec.get("state") in TERMINAL and not rec.get("seen"):
        rec["seen"] = True
        changed = True
    if changed:
        try:
            _write(path, rec)
        except OSError:
            pass
    return rec


def elapsed(rec: dict) -> float:
    if rec.get("elapsed_s") is not None and rec.get("state") in TERMINAL:
        return float(rec["elapsed_s"])
    return max(0.0, time.time() - float(rec.get("started_ts") or time.time()))


def dur(s: float | None) -> str:
    if s is None:
        return "?"
    s = max(0, round(s))
    if s < 90:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60:02d} s"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def progress_text(p: dict | None) -> str:
    if not p:
        return ""
    parts = []
    if p.get("done") is not None and p.get("total"):
        parts.append(f"{p['done']:g}/{p['total']:g}")
    elif p.get("done") is not None:
        parts.append(f"{p['done']:g} done")
    if p.get("msg"):
        parts.append(str(p["msg"])[:80])
    if p.get("eta") and not (p.get("total") and p.get("done") is not None and p["done"] >= p["total"]):
        parts.append(f"eta {dur(p['eta'])}")
    return ", ".join(parts)


def _cmd_ref(rec: dict) -> str:
    """How the bot reaches this job again (the project flag spelled out)."""
    if rec.get("project"):
        from .core_cli import project_ref
        return f"slop --project {project_ref(Path(rec['project']))} job"
    return "slop job"


def wait_cmd(rec: dict, mx: float | None = None) -> str:
    return f"{_cmd_ref(rec)} wait {rec['id']} --max {int(mx if mx is not None else default_wait())}"


def summary(rec: dict) -> dict:
    return {"id": rec["id"], "state": rec.get("state"), "cmd": rec.get("cmd"), "argv": rec.get("argv"),
            "project": rec.get("project"), "started": rec.get("started"), "elapsed_s": round(elapsed(rec), 1),
            "progress": rec.get("progress"), "exit": rec.get("exit"), "error": rec.get("error"),
            "seen": bool(rec.get("seen")), "wait": wait_cmd(rec)}


def project_jobs(pdir: Path, unseen: bool = True) -> list[dict]:
    """Running jobs of a project (+ finished ones nobody has read yet, from the last day) - for `slop status`."""
    out = []
    now = time.time()
    for path, rec in _records(jobs_dir(pdir)):
        if rec.get("state") not in TERMINAL:
            rec = refresh(path, rec)
        st = rec.get("state")
        if st not in TERMINAL or (unseen and not rec.get("seen")
                                  and now - float(rec.get("started_ts") or 0) < UNSEEN_WINDOW_S):
            out.append(summary(rec))
    return out


def command_words(argv: list[str]) -> list[str]:
    """The command path of a slop argv: leading words up to the first flag (['render', 'frames'])."""
    out = []
    for w in argv:
        if w.startswith("-") or not re.fullmatch(r"[a-z_][a-z0-9_-]*", w):
            break
        out.append(w)
    return out


# ====================================================================== child argv
def strip_globals(words: list[str]) -> tuple[str | None, list[str]]:
    """Remove --json and --project/-p X from a child argv; returns (project or None, the rest)."""
    words = list(words)
    if words[:1] == ["--"]:
        words = words[1:]
    if words[:1] in (["slop"], ["python"]):
        words = words[1:]
        if words[:2] == ["-m", "slop"]:
            words = words[2:]
    proj, rest, i = None, [], 0
    while i < len(words):
        a = words[i]
        if a == "--":
            rest += words[i:]
            break
        if a == "--json":
            pass
        elif a in ("--project", "-p") and i + 1 < len(words):
            proj = words[i + 1]
            i += 1
        elif a.startswith("--project="):
            proj = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    return proj, rest


def check_argv(words: list[str]) -> argparse.Namespace:
    """Parse a child argv with the real router; a typo is a SlopError now, not a failed job later."""
    if not words:
        raise SlopError("name the slop command to run: slop --project NAME job start -- analyze")
    if any(w in ("-h", "--help") for w in words):
        raise SlopError("--help does not run as a job: run `slop " + " ".join(command_words(words))
                        + " --help` directly")
    path = command_words(words)
    if path[:1] == ["job"] and path[1:2] != ["_sleep"]:
        raise SlopError("a job cannot start, wait for or stop jobs: run `slop job ...` directly")
    if path[:1] == ["next"]:
        raise SlopError("`next` does not run as a job (it starts long steps as jobs itself): run "
                        "`slop --project NAME next` directly")
    from .cli import build_parser
    ap = build_parser()

    def patch(p: argparse.ArgumentParser) -> None:
        def err(message: str, _p=p) -> None:
            raise SlopError(f"`slop {' '.join(words)}` is not a valid command ({_p.prog}: {message}); "
                            f"see: {_p.prog} --help")
        p.error = err
        for act in p._actions:
            if isinstance(act, argparse._SubParsersAction):
                for sp in act.choices.values():
                    patch(sp)
    patch(ap)
    try:
        ns = ap.parse_args(words)
    except SystemExit:
        raise SlopError(f"`slop {' '.join(words)}` is not a runnable command") from None
    group = _group_without_step(ap, path)
    if not getattr(ns, "func", None) or group:
        g = group or words[0]
        raise SlopError(f"`slop {' '.join(words)}` names a command group, not a command: choose a step (see: slop {g} "
                        "--help)")
    return ns


def _group_without_step(ap: argparse.ArgumentParser, path: list[str]) -> str | None:
    """'render' for ['render'] (a parser with sub-commands and none chosen), None when path reaches a command."""
    p, i, seen = ap, 0, []
    while True:
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs:
            return None
        word = path[i] if i < len(path) else None
        if word is None or word not in subs[0].choices:
            return " ".join(seen) or None
        p, i = subs[0].choices[word], i + 1
        seen.append(word)


def _cwd() -> str:
    try:
        return os.getcwd()
    except OSError:  # the shell's folder was deleted: run from home
        return str(Path.home())


def _new_id(store: Path, words: list[str]) -> tuple[str, Path]:
    slug = "-".join(command_words(words)[:2]).replace("_", "") or "job"
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")[:24] or "job"
    store.mkdir(parents=True, exist_ok=True)
    rnd = random.SystemRandom()
    for _ in range(200):
        jid = f"{slug}-{''.join(rnd.choice(ID_CHARS) for _ in range(4))}"
        p = _rec_path(store, jid)
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            continue
        os.close(fd)
        return jid, p
    raise SlopError(f"could not create a job id in {store}")  # pragma: no cover


# ====================================================================== start
def start(words: list[str], project: str | None = None, again: bool = False, free_only: bool = False,
          cwd: str | None = None, status_sig: str | None = None) -> dict:
    """Start `slop <words>` as a detached job; returns {"job": summary, "existing": bool}.

    The record keeps the project's status signature at the start (core_cli.status_signature; computed here when the
    caller has none): when the job has ended and status still reads the same, the job changed nothing."""
    child_proj, rest = strip_globals(words)
    pdir = _project_or_none(child_proj or project)
    check_argv(rest)
    store = jobs_dir(pdir)
    recs = _records(store)
    if not again:
        for path, rec in recs:
            if rec.get("argv") == rest and rec.get("state") not in TERMINAL:
                rec = refresh(path, rec)
                if rec.get("state") not in TERMINAL:
                    return {"job": summary(rec), "existing": True}
    if pdir and status_sig is None:
        from .core_cli import project_signature
        status_sig = project_signature(pdir)
    jid, path = _new_id(store, rest)
    seq = next_seq(store, recs)
    if pdir:
        from .core_cli import project_ref
        cmd = f"slop --project {project_ref(pdir)} " + " ".join(shlex.quote(w) for w in rest)
    else:
        cmd = "slop " + " ".join(shlex.quote(w) for w in rest)
    rec = {"id": jid, "project": str(pdir) if pdir else None, "argv": rest, "cmd": cmd,
           "cwd": str(Path(cwd or _cwd()).resolve()), "started": util.iso_now(), "started_ts": round(time.time(), 3),
           "state": "starting", "pid": None, "pid_start": None, "supervisor_pid": None, "supervisor_start": None,
           "pgid": None, "progress": None, "exit": None, "finished": None, "elapsed_s": None, "result": None,
           "error": None, "free_only": bool(free_only), "seq": seq, "status_sig": status_sig,
           "log": str(store / f"{jid}.log"),
           "out": str(store / f"{jid}.out"), "progress_file": str(store / f"{jid}.progress.json")}
    _write(path, rec)
    env = _child_env({"SLOP_JOB_ID": jid, "SLOP_PROGRESS_FILE": rec["progress_file"], "SLOP_JOB_FILE": str(path),
                      **({"SLOP_FREE_ONLY": "1"} if free_only else {})})
    try:
        _spawn_detached([sys.executable, "-m", "slop.job", "_supervise", str(path)], env, rec["cwd"], Path(rec["log"]))
    except OSError as e:
        rec.update(state="failed", error=f"could not start the job: {e}", finished=util.iso_now())
        _write(path, rec)
        raise SlopError(f"could not start the job: {e}") from None
    t0 = time.monotonic()
    while time.monotonic() - t0 < START_CONFIRM_S:  # wait until the supervisor reports the step's pid
        r = _read(path) or rec
        if r.get("pid") or r.get("state") in TERMINAL:
            rec = r
            break
        time.sleep(0.05)
    rec = refresh(path, _read(path) or rec)
    return {"job": summary(rec), "existing": False}


# ====================================================================== supervisor (runs detached)
def supervise(path: Path) -> int:
    rec = _read(path)
    if not rec:
        print(f"[job] no job record at {path}", file=sys.stderr)
        return 2
    if os.name != "nt":
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    rec.update(supervisor_pid=os.getpid(), supervisor_start=proc_start(os.getpid()),
               pgid=os.getpgid(0) if os.name != "nt" else None)
    stop_marker = path.with_suffix(".stop")
    if stop_marker.exists():  # `job stop` came while the job was still starting: never run the step
        rec.update(state="stopped", error="stopped by `slop job stop` before the step started", exit=None,
                   finished=util.iso_now(), elapsed_s=0.0)
        _write(path, rec)
        print(f"[job] {util.stamp()} stopped before the step started", file=sys.stderr, flush=True)
        return 0
    argv = [sys.executable, "-m", "slop", "--json"] + (["--project", rec["project"]] if rec.get("project") else []) \
        + list(rec.get("argv") or [])
    t0 = time.monotonic()
    print(f"[job] {util.stamp()} start: {rec.get('cmd')}", file=sys.stderr, flush=True)
    stop = {"sig": None}
    try:
        with open(rec["out"], "wb") as out:
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}  # CREATE_NO_WINDOW
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=None, cwd=rec.get("cwd"), **kw)
    except OSError as e:
        rec.update(state="failed", error=f"could not run the step: {e}", finished=util.iso_now(), exit=None)
        _write(path, rec)
        return 1

    def on_signal(signum, _frame):
        stop["sig"] = signum
        try:
            p.send_signal(signum)
        except OSError:
            pass
    for s in ("SIGTERM", "SIGINT"):
        if hasattr(signal, s):
            signal.signal(getattr(signal, s), on_signal)
    rec.update(pid=p.pid, pid_start=proc_start(p.pid), state="running")
    _write(path, rec)
    if stop_marker.exists():  # the stop came while the step was being started (its pid was not recorded yet)
        on_signal(signal.SIGTERM, None)
    rc = p.wait()
    el = round(time.monotonic() - t0, 1)
    res = _parse_result(Path(rec["out"]))
    stopped = stop["sig"] is not None or path.with_suffix(".stop").exists()
    if rc == 0 and (res is None or res.get("ok", True) is not False):
        state, err = "done", None
    elif stopped:
        state, err = "stopped", "stopped by `slop job stop`"
    else:
        state = "failed"
        err = (res or {}).get("error") or (f"killed by signal {-rc}" if rc < 0 else f"exit code {rc}")
    rec = _read(path) or rec
    rec.update(state=state, exit=rc, finished=util.iso_now(), elapsed_s=el, error=err,
               result=_clip_result(res, Path(rec["out"])))
    prog = read_progress(rec)
    if prog is not None:
        rec["progress"] = prog
    _write(path, rec)
    print(f"[job] {util.stamp()} {state} (exit {rc}) after {el} s", file=sys.stderr, flush=True)
    return 0


# ====================================================================== commands
def _job_text(rec: dict, waited: float | None = None) -> str:
    st = rec.get("state")
    head = f"job {rec['id']}: {st}"
    if st in TERMINAL:
        head += f" after {dur(elapsed(rec))}" + (f" (exit {rec['exit']})" if rec.get("exit") is not None else "")
    else:
        head += f" for {dur(elapsed(rec))}"
    lines = [head, f"  {rec.get('cmd')}"]
    pt = progress_text(rec.get("progress"))
    if pt:
        lines.append(f"  progress: {pt}")
    if st == "done":
        res = rec.get("result") or {}
        if isinstance(res.get("text"), str) and res["text"].strip():
            lines.append(res["text"].rstrip())
        if rec.get("note"):
            lines.append(f"  note: {rec['note']}")
    elif st == "failed":
        lines.append(f"  error: {rec.get('error')}")
        tail = log_tail(rec, 12)
        if tail:
            lines.append("  log tail:\n" + "\n".join("    " + ln for ln in tail.splitlines()))
        lines.append(f"  fix the cause, then start it again:  {_cmd_ref(rec)} start -- "
                     + " ".join(shlex.quote(w) for w in rec.get("argv") or []))
    elif st == "stopped":
        lines.append(f"  stopped. Start it again with:  {_cmd_ref(rec)} start -- "
                     + " ".join(shlex.quote(w) for w in rec.get("argv") or []))
    else:
        lines.append("  still running" + (f" after a {dur(waited)} wait" if waited is not None else "") +
                     f". Next:  {wait_cmd(rec)}")
    return "\n".join(lines)


def _job_out(rec: dict, waited: float | None = None, timed_out: bool | None = None) -> dict:
    out = {"job": summary(rec), "id": rec["id"], "state": rec.get("state"), "running": rec.get("state") not in TERMINAL,
           "result": rec.get("result"), "log": rec.get("log"), "text": _job_text(rec, waited)}
    if waited is not None:
        out["waited_s"] = round(waited, 2)
        out["timed_out"] = bool(timed_out)
    if rec.get("state") in ("failed", "stopped"):
        out["ok"] = False
        out["error"] = f"job {rec['id']} {rec['state']}: {rec.get('error')}"
        out["log_tail"] = log_tail(rec, 30)
    elif rec.get("state") == "done":
        out["ok"] = True
    else:
        out["next"] = wait_cmd(rec)
    return out


def cmd_start(args) -> dict:
    words = list(args.argv or [])
    r = start(words, project=args.project, again=args.again, free_only=args.free_only)
    s = r["job"]
    path, rec = find_job(s["id"], Path(s["project"]) if s.get("project") else None)
    if args.wait and rec.get("state") not in TERMINAL:
        return _wait(path, rec, args.wait)
    if r["existing"]:
        text = (f"already running as job {s['id']} (started {s['started']}, {dur(s['elapsed_s'])} ago) - not started "
                f"twice (--again starts another). Next:  {s['wait']}")
    elif rec.get("state") in TERMINAL:
        return _job_out(refresh(path, rec, mark_seen=True))
    elif not rec.get("pid"):  # the supervisor has not reported yet (a very busy machine): do not start it again
        text = (f"job {s['id']} is starting but has not confirmed yet ({s['cmd']}). Do NOT start it again; "
                f"next:  {s['wait']}   (its log: {_cmd_ref(rec)} log {s['id']})")
    else:
        text = (f"started job {s['id']}: {s['cmd']}\n  it runs in the background; this shell can end. "
                f"Next:  {s['wait']}")
    return {"job": summary(rec), "id": s["id"], "state": rec.get("state"), "existing": r["existing"],
            "next": s["wait"], "text": text}


def _wait(path: Path, rec: dict, mx: float) -> dict:
    mx = max(0.0, min(float(mx), 3600.0))
    t0 = time.monotonic()
    while True:
        rec = refresh(path, _read(path) or rec)
        if rec.get("state") in TERMINAL:
            rec = refresh(path, rec, mark_seen=True)
            return _job_out(rec, time.monotonic() - t0, False)
        left = mx - (time.monotonic() - t0)
        if left <= 0:
            return _job_out(rec, time.monotonic() - t0, True)
        time.sleep(min(0.5, left))


def cmd_status(args) -> dict:
    pdir = _project_or_none(args.project)
    path, rec = find_job(args.id, pdir)
    return _job_out(refresh(path, rec, mark_seen=True))


def cmd_wait(args) -> dict:
    pdir = _project_or_none(args.project)
    path, rec = find_job(args.id, pdir)
    return _wait(path, rec, default_wait() if args.max is None else args.max)


def cmd_list(args) -> dict:
    pdir = _project_or_none(args.project)
    stores = _all_stores(None) if (args.all or pdir is None) else [jobs_dir(pdir)]
    rows = []
    for s in stores:
        for path, rec in _records(s):  # each folder in sequence order
            rows.append(summary(refresh(path, rec)))
    if len(stores) > 1:
        rows.sort(key=lambda r: r.get("started") or "")
    if args.running:
        rows = [r for r in rows if r["state"] not in TERMINAL]
    if args.last:
        rows = rows[-args.last:]
    if not rows:
        return {"jobs": [], "count": 0, "text": "no jobs" + (" running" if args.running else "") +
                ". Start one with:  slop --project NAME job start -- <command>"}
    tbl = util.table([[r["id"], r["state"], dur(r["elapsed_s"]), progress_text(r.get("progress"))[:40],
                       (r.get("cmd") or "")[:70]] for r in rows], ["id", "state", "time", "progress", "command"])
    return {"jobs": rows, "count": len(rows), "running": sum(r["state"] not in TERMINAL for r in rows), "text": tbl}


def stop_job(path: Path, rec: dict, grace: float = 10.0) -> dict:
    rec = refresh(path, rec)
    if rec.get("state") in TERMINAL:
        return rec
    try:
        path.with_suffix(".stop").write_text(util.iso_now() + "\n", encoding="utf-8")
    except OSError:
        pass
    rec = _read(path) or rec  # re-read AFTER the marker: either the supervisor sees the marker, or we see its pids
    if not rec.get("pgid") and not rec.get("pid"):  # still starting: the supervisor reads the marker and stops
        t0 = time.monotonic()
        while time.monotonic() - t0 < START_CONFIRM_S:
            rec = _read(path) or rec
            if rec.get("state") in TERMINAL or rec.get("pgid") or rec.get("pid"):
                break
            time.sleep(0.05)
        if rec.get("state") in TERMINAL:
            return refresh(path, rec, mark_seen=True)
    _signal_group(rec, signal.SIGTERM if os.name != "nt" else 0)
    t0 = time.monotonic()
    while time.monotonic() - t0 < grace:
        if not alive(rec.get("pid"), rec.get("pid_start")) and \
                not alive(rec.get("supervisor_pid"), rec.get("supervisor_start")):
            break
        time.sleep(0.1)
    else:
        if os.name != "nt":
            _signal_group(rec, signal.SIGKILL)
            t1 = time.monotonic()
            while time.monotonic() - t1 < 3 and (alive(rec.get("pid"), rec.get("pid_start")) or
                                                alive(rec.get("supervisor_pid"), rec.get("supervisor_start"))):
                time.sleep(0.1)
    t1 = time.monotonic()
    while time.monotonic() - t1 < 2:  # give the supervisor a moment to record the exit
        r = _read(path) or rec
        if r.get("state") in TERMINAL:
            break
        time.sleep(0.05)
    return refresh(path, _read(path) or rec, mark_seen=True)


def cmd_stop(args) -> dict:
    pdir = _project_or_none(args.project)
    path, rec = find_job(args.id, pdir)
    was = rec.get("state")
    rec = stop_job(path, rec, grace=args.grace)
    out = _job_out(rec)
    if was in TERMINAL:
        out.update(ok=True, error=None, text=f"job {rec['id']} had already ended ({was}); nothing to stop")
    elif rec.get("state") == "stopped":
        out.update(ok=True, error=None)
    return out


def cmd_log(args) -> dict:
    pdir = _project_or_none(args.project)
    path, rec = find_job(args.id, pdir)
    tail = log_tail(rec, args.lines)
    return {"id": rec["id"], "log": rec.get("log"), "tail": tail,
            "text": tail or f"(the log {rec.get('log')} is empty)"}


def cmd_sleep(args) -> dict:
    """Hidden test step: sleeps, reporting progress (used by `job selftest` and the tests)."""
    n = max(1, int(args.steps))
    for k in range(n):
        write_progress(k, n, f"sleeping {k}/{n}")
        time.sleep(max(0.0, float(args.seconds)) / n)
    write_progress(n, n, "slept", final=True)
    if args.fail:
        raise SlopError("failing on purpose (job _sleep --fail)")
    return {"slept": float(args.seconds), "free_only": os.environ.get("SLOP_FREE_ONLY") == "1",
            "job_id": os.environ.get("SLOP_JOB_ID"), "text": f"slept {float(args.seconds):g} s"}


def _start_test_job(secs: float) -> tuple[str, float]:
    """`slop job start -- job _sleep SECS --steps 4` from a separate `slop` process that exits at once (project-less
    job store). Returns (job id, seconds the starting process took)."""
    home = slop_home()
    home.mkdir(parents=True, exist_ok=True)
    env = _child_env({})
    env.pop("SLOP_PROJECT", None)
    t0 = time.monotonic()
    rc, out, err = util.run([sys.executable, "-m", "slop", "--json", "job", "start", "--", "job", "_sleep", f"{secs:g}",
                             "--steps", "4"], timeout=60, env=env, cwd=str(home))
    parent_s = time.monotonic() - t0
    try:
        started = json.loads(out.strip().splitlines()[-1])
        return started["id"], parent_s
    except (ValueError, IndexError, KeyError, TypeError):
        raise SlopError(f"`slop job start` failed (exit {rc}): {(err or out).strip()[-400:]}") from None


SELFTEST_STATE = "selftest.json"
TWO_CALL_SECONDS = 150.0


def _selftest_state_path() -> Path:
    d = slop_home() / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d / SELFTEST_STATE


def _two_call_start(secs: float) -> dict:
    jid, parent_s = _start_test_job(secs)
    st = {"id": jid, "seconds": secs, "started": util.iso_now(), "started_ts": time.time(), "checks": []}
    util.atomic_write_json(_selftest_state_path(), st)
    nxt = f"slop job selftest --check {jid}"
    text = (f"two-call job test started: job {jid} sleeps {secs:g} s in the background (this call took {parent_s:.1f} s).\n"
            f"  call B - in your NEXT tool call run:  {nxt}   (it must say RUNNING)\n"
            f"  then end the turn; in a later turn, {secs:g} s or more from now, run it again (it must say PASS)")
    return {"id": jid, "phase": "started", "seconds": secs, "next": nxt, "text": text}


def _two_call_check(jid: str) -> dict:
    sp = _selftest_state_path()
    st = util.read_json(sp, default=None) or {}
    if jid in ("", "last"):
        jid = st.get("id") or ""
        if not jid:
            raise SlopError("no two-call test was started on this computer: run  slop job selftest --start  first")
    if st.get("id") != jid:
        st = {"id": jid, "seconds": TWO_CALL_SECONDS, "started_ts": None, "checks": []}
    path, rec = find_job(jid, None)
    rec = refresh(path, rec)
    state = rec.get("state")
    el = elapsed(rec)
    secs = float(st.get("seconds") or TWO_CALL_SECONDS)
    prog = rec.get("progress") or {}
    st.setdefault("checks", []).append({"at": util.iso_now(), "state": state, "elapsed_s": round(el, 1)})
    seen_running = any(c.get("state") not in TERMINAL for c in st["checks"])
    st["seen_running"] = seen_running
    util.atomic_write_json(sp, st)
    nxt = f"slop job selftest --check {jid}"
    out = {"id": jid, "state": state, "elapsed_s": round(el, 1), "seconds": secs, "seen_running": seen_running}
    if state not in TERMINAL:
        left = max(0.0, secs - el)
        late = el > secs + 120
        text = (f"two-call job test: RUNNING after {dur(el)} in a later call - the job survived the end of the call that "
                f"started it. Now end the turn; in a later turn (in about {dur(left + 10)}) run:  {nxt}  - it must say "
                "PASS." if not late else
                f"two-call job test: still running after {dur(el)} (the test job sleeps {secs:g} s): check again in a "
                f"minute ({nxt}); if it still runs after 5 minutes, tell the owner the job runner is stuck "
                f"(its log: slop job log {jid}).")
        return {**out, "ok": True, "phase": "running", "passed": None, "next": nxt, "text": text}
    if state == "done" and prog.get("done") == prog.get("total") == 4:
        text = (f"two-call job test: PASS - job {jid} ran to the end ({dur(rec.get('elapsed_s') or el)}) although the "
                "call that started it ended" + (" and a later call saw it running" if seen_running else
                                                 " (no later call saw it running, but it finished, which proves the same)")
                + ". Long steps (analyze, render) can run as background jobs on this computer.")
        return {**out, "ok": True, "phase": "done", "passed": True, "text": text}
    why = rec.get("error") or f"ended '{state}'"
    text = (f"two-call job test: FAIL - job {jid} {why} after {dur(el)}: on this computer a background job does not "
            "survive the end of the shell call or turn that started it. Stop the setup here and tell the owner this "
            "line; do not start long steps (analyze, edit export, render) as jobs until it is fixed.")
    return {**out, "ok": False, "phase": state, "passed": False, "error": text, "log_tail": log_tail(rec, 12),
            "text": text}


def cmd_selftest(args) -> dict:
    """Start a short job from a separate `slop` process that exits at once; check the job outlives it.
    --start / --check ID: the same across two tool calls and a turn end (the box test)."""
    if getattr(args, "start", False) and getattr(args, "check", None) is not None:
        raise SlopError("give --start (call A) or --check ID (call B and later), not both")
    if getattr(args, "start", False):
        return _two_call_start(float(args.seconds) if args.seconds is not None else TWO_CALL_SECONDS)
    if getattr(args, "check", None) is not None:
        return _two_call_check(str(args.check).strip())
    secs = float(args.seconds) if args.seconds is not None else 3.0
    jid, parent_s = _start_test_job(secs)
    path, rec = find_job(jid, None)
    outlived = alive(rec.get("pid"), rec.get("pid_start")) or alive(rec.get("supervisor_pid"),
                                                                      rec.get("supervisor_start"))
    res = _wait(path, rec, secs + 20)
    rec = _read(path) or rec
    prog = rec.get("progress") or {}
    ok = bool(outlived and rec.get("state") == "done" and prog.get("done") == prog.get("total") == 4)
    checks = {"parent_exit_s": round(parent_s, 2), "outlived_parent": outlived, "state": rec.get("state"),
              "job_s": rec.get("elapsed_s"), "progress_seen": prog.get("done") == 4}
    if ok:
        for f in path.parent.glob(f"{jid}.*"):
            try:
                f.unlink()
            except OSError:
                pass
    text = (f"job selftest: {'PASS' if ok else 'FAIL'} - the starting process exited after {parent_s:.2f} s; the job "
            f"{'kept running' if outlived else 'was NOT running'} after that and ended '{rec.get('state')}' "
            f"after {rec.get('elapsed_s')} s; progress {'seen' if checks['progress_seen'] else 'NOT seen'}")
    out_d = {"ok": ok, "checks": checks, "job": jid, "text": text}
    if not ok:
        out_d["error"] = text + ("; log: " + log_tail(rec, 8) if log_tail(rec, 8) else "")
        out_d["wait"] = res
    return out_d


# ====================================================================== register
def register(sub) -> None:
    p = sub.add_parser("job", help="run long steps in the background (start, wait, status, list, stop)",
                       description="Long steps (analyze, edit export, render frames/vertical/lyrics/encode/check, "
                                   "taste embed) run past the shell's time limit: start them as a job, then wait in "
                                   "short calls. Example: slop --project my-song job start -- analyze ; it prints the "
                                   "job id (e.g. analyze-k3f9) and its wait command: slop --project my-song job wait "
                                   "analyze-k3f9   (repeat until it is not running; `last` = the newest job)")
    js = p.add_subparsers(dest="job_cmd", metavar="start|wait|status|list|stop|log|selftest", required=True)
    mine = [p]

    def add(name: str, **kw) -> argparse.ArgumentParser:
        sp = js.add_parser(name, **kw)
        util.add_common_flags(sp)
        mine.append(sp)
        return sp

    s = add("start", help="run `slop <command>` detached; prints the job id at once",
            description="Everything after -- is the slop command to run (without `slop`), e.g. "
                        "`slop --project my-song job start -- render frames --workers 4`. The job keeps running after "
                        "this shell call ends. Prints the job id and the wait command.")
    s.add_argument("--wait", type=float, default=0, metavar="S",
                   help="also wait up to S seconds (quick steps then finish in this call)")
    s.add_argument("--again", action="store_true", help="start even if the same command is already running")
    s.add_argument("--free-only", action="store_true",
                   help="lock spending inside the job: any paid call is refused (SLOP_FREE_ONLY=1)")
    s.add_argument("argv", nargs=argparse.REMAINDER, help="-- then the slop command and its options")
    s.set_defaults(func=cmd_start)

    w = add("wait", help="wait up to --max seconds for a job, then report it",
            description="Blocks at most --max seconds (default 25, below the bot shell's time limit; env SLOP_WAIT_MAX "
                        "changes the default). Still running: call it again. Finished: shows the step's own result "
                        "(ok false when the job failed).")
    w.add_argument("id", help="job id (from `job start`/`job list`), or `last`")
    w.add_argument("--max", type=float, default=None, metavar="S", help="seconds to wait at most (default 25)")
    w.set_defaults(func=cmd_wait)

    st = add("status", help="a job's state, progress and result (no waiting)")
    st.add_argument("id", help="job id, or `last`")
    st.set_defaults(func=cmd_status)

    li = add("list", help="this project's jobs (all job folders with --all)")
    li.add_argument("--all", action="store_true", help="every project's jobs and the project-less ones")
    li.add_argument("--running", action="store_true", help="only jobs still running")
    li.add_argument("--last", type=int, default=0, help="only the newest N")
    li.set_defaults(func=cmd_list)

    sp = add("stop", help="stop a running job (its whole process group)")
    sp.add_argument("id", help="job id, or `last`")
    sp.add_argument("--grace", type=float, default=10.0, help="seconds between SIGTERM and SIGKILL (default 10)")
    sp.set_defaults(func=cmd_stop)

    lg = add("log", help="the tail of a job's log")
    lg.add_argument("id", help="job id, or `last`")
    lg.add_argument("--lines", type=int, default=40)
    lg.set_defaults(func=cmd_log)

    se = add("selftest", help="check that a job outlives the shell call that started it (~5 s); on a new computer use "
                              "the two-call test: --start, then --check ID in the next call and after the turn",
             description="Without flags: one call (~5 s). The box test needs TWO calls and a turn end: call A `slop job "
                         "selftest --start` (returns at once with the id); call B, the NEXT tool call: `slop job selftest "
                         "--check ID` must say RUNNING; end the turn; later (>= 150 s): `--check ID` again must say PASS.")
    se_g = se.add_mutually_exclusive_group()
    se_g.add_argument("--start", action="store_true", help="call A: start the 150 s test job and return at once")
    se_g.add_argument("--check", nargs="?", const="last", metavar="ID",
                      help="call B and later: RUNNING / PASS / FAIL for the --start job (default: the last one)")
    se.add_argument("--seconds", type=float, default=None, help=argparse.SUPPRESS)
    se.set_defaults(func=cmd_selftest)

    sl = add("_sleep")  # no help= : hidden from the command list (test step)
    sl.add_argument("seconds", type=float)
    sl.add_argument("--steps", type=int, default=4)
    sl.add_argument("--fail", action="store_true")
    sl.set_defaults(func=cmd_sleep)
    for q in mine:
        util.json_usage_errors(q)


def _main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "_supervise":
        return supervise(Path(argv[1]))
    print("usage: python -m slop.job _supervise JOBFILE   (internal; use `slop job start`)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
