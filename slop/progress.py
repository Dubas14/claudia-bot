"""Progress of long steps, for a bot that polls a file instead of waiting on a 30-minute command.

    with command("render vertical", steps=2) as c:     # the whole command (slop/render/cli.py wraps every long step)
        report(done, total, msg="", stage=None)         # inside it, each stage (frames, then the encode)
        c.ok = result["ok"]

When $SLOP_PROGRESS_FILE is set, writes one JSON object to that file (atomically: a temp file in the same folder,
then os.replace — a reader never sees half a file):

    {"command": "render vertical", "step": "1/2", "stage": "render vertical frames", "done": 1200, "total": 7344,
     "pct": 16.3, "msg": "…", "elapsed_s": 410.2, "eta_s": 2100, "rate_per_s": 2.93, "pid": 1234,
     "ts": 1790000000.0, "state": "running"}

"state" tells whether the COMMAND is over:
  running        a stage is working (pct / eta_s are for this stage — "step" says which stage of how many)
  stage_done     one stage finished and the command goes on with the next (NOT the end: keep polling)
  stage_stopped  one stage ended short; the command goes on or ends — keep polling
  done           the command ended and did its job                        } only these three mean the command is over
  stopped        the command ended short (its own output says what to do) }
  failed         the command ended with an error ("msg" has it)          }
The authoritative end of a background step is `slop job wait ID` (its exit state); this file is for the percent and
the time left while it runs. Outside command() (a library call), the end of a stage writes done / stopped as before.

Used by `slop render frames | vertical | lyrics | sheet | check --layers | encode`. The bot reads it with
`cat "$SLOP_PROGRESS_FILE"` (or `jq .state`) while the command runs in the background. When the variable is not set,
nothing is written. Writes are rate-limited to one every 0.5 s (stage ends and the command's end are always written);
report() never raises: progress is advisory and must not break a render. Thread-safe (render workers are threads).
stdlib only.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time

ENV = "SLOP_PROGRESS_FILE"
MIN_INTERVAL = 0.5
ENDED = ("done", "stopped", "failed")          # the states that mean the command is over

_lock = threading.Lock()
_state: dict = {"stage": None, "t0": 0.0, "last": 0.0, "done0": 0}


def path() -> str | None:
    p = os.environ.get(ENV, "").strip()
    return p or None


def _write(p: str, obj: dict) -> None:
    d = os.path.dirname(os.path.abspath(p))
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".{os.path.basename(p)}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False))
    os.replace(tmp, p)


def _step_text() -> str:
    k, n = int(_state.get("step") or 0), int(_state.get("steps") or 0)
    return f"{max(1, k)}/{max(1, n, k)}"


def report(done: int | float, total: int | float, msg: str = "", stage: str | None = None, force: bool = False,
           ended: bool = False) -> dict | None:
    """Record progress. `stage` starts a new clock when it changes (ETA is per stage; inside a command() it is also
    the command's next step). Returns what was written (None when nothing was: no $SLOP_PROGRESS_FILE,
    rate-limited, or an I/O error)."""
    p = path()
    if not p:
        return None
    try:
        now = time.monotonic()
        with _lock:
            st = stage or _state.get("stage") or "slop"
            in_cmd = int(_state.get("depth") or 0) > 0
            if st != _state.get("stage"):
                _state.update(stage=st, t0=now, last=0.0, done0=float(done or 0))
                if in_cmd:
                    _state["step"] = int(_state.get("step") or 0) + 1
            finished = bool(total) and float(done) >= float(total)
            if not (force or ended) and now - float(_state.get("last") or 0.0) < MIN_INTERVAL:
                return None
            _state["last"] = now
            el = now - float(_state.get("t0") or now)
            moved = float(done or 0) - float(_state.get("done0") or 0)
            rate = moved / el if el > 0 and moved > 0 else None
            left = (float(total) - float(done)) if total else None
            if ended:
                state = ("stage_done" if finished else "stage_stopped") if in_cmd else ("done" if finished else "stopped")
                _state["last_end"] = {"done": done, "total": total, "finished": finished, "msg": str(msg)[:300]}
            else:
                state = "running"
            obj = {"command": (_state.get("command") if in_cmd else None) or st, "step": _step_text() if in_cmd else "1/1",
                   "stage": st, "done": done, "total": total,
                   "pct": round(100.0 * float(done) / float(total), 1) if total else None,
                   "msg": str(msg)[:300], "elapsed_s": round(el, 1),
                   "eta_s": round(left / rate) if (rate and left is not None and left > 0) else (0 if finished else None),
                   "rate_per_s": round(rate, 3) if rate else None, "pid": os.getpid(), "ts": round(time.time(), 1),
                   "state": state}
            _write(p, obj)
            return obj
    except Exception:  # noqa: BLE001 — progress must never break the step it reports on
        return None


def end(done: int | float, total: int | float, msg: str = "", stage: str | None = None) -> dict | None:
    """The final report of a stage (always written): "done" / "stopped" outside a command(), "stage_done" /
    "stage_stopped" inside one (the command's own end writes done / stopped / failed)."""
    return report(done, total, msg, stage=stage, force=True, ended=True)


class _Command:
    """What command() yields: set .ok to the command's verdict (result["ok"]) before the block ends."""
    ok: bool | None = None
    msg: str = ""


def _final(state: str, msg: str) -> dict | None:
    """The command's last record (caller holds no lock)."""
    p = path()
    if not p:
        return None
    try:
        with _lock:
            le = _state.get("last_end") or {}
            done, total = le.get("done"), le.get("total")
            if state == "done":
                _state["steps"] = max(int(_state.get("steps") or 0), int(_state.get("step") or 0))
                _state["step"] = _state["steps"]
            el = time.monotonic() - float(_state.get("cmd_t0") or time.monotonic())
            obj = {"command": _state.get("command"), "step": _step_text(), "stage": _state.get("stage"),
                   "done": done, "total": total,
                   "pct": round(100.0 * float(done) / float(total), 1) if (total and done is not None) else None,
                   "msg": str(msg)[:300], "elapsed_s": round(el, 1), "eta_s": 0 if state == "done" else None,
                   "rate_per_s": None, "pid": os.getpid(), "ts": round(time.time(), 1), "state": state}
            _write(p, obj)
            return obj
    except Exception:  # noqa: BLE001
        return None


@contextlib.contextmanager
def command(name: str, steps: int = 1):
    """One whole command: its stages report "stage_done" between them, and only its end writes done / stopped /
    failed. Nested command() blocks (render vertical → render frames) join the outer one."""
    with _lock:
        depth = int(_state.get("depth") or 0)
        outer = depth == 0
        _state["depth"] = depth + 1
        if outer:
            _state.update(command=name, steps=max(1, int(steps or 1)), step=0, stage=None, last_end=None,
                          cmd_t0=time.monotonic())
    c = _Command()
    try:
        yield c
    except KeyboardInterrupt:
        if outer:
            _final("stopped", f"{name}: interrupted")
        raise
    except BaseException as e:  # noqa: BLE001 — recorded, then re-raised
        if outer:
            _final("failed", f"{name} failed: {str(e) or type(e).__name__}")
        raise
    else:
        if outer:
            le = _state.get("last_end") or {}
            ok = c.ok if c.ok is not None else le.get("finished", True)
            _final("done" if ok else "stopped",
                   c.msg or (f"{name}: done" if ok else f"{name}: ended short — its output says what to run next"))
    finally:
        with _lock:
            _state["depth"] = max(0, int(_state.get("depth") or 1) - 1)
            if outer:
                _state["command"] = None


def read(p: str | None = None) -> dict | None:
    """The last progress record (None when there is none or it is unreadable)."""
    p = p or path()
    if not p:
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.loads(f.read())
    except (OSError, ValueError):
        return None


class Counter:
    """A shared done-counter for parallel workers: Counter(total, stage).add(n=1, msg='')."""

    def __init__(self, total: int, stage: str, start: int = 0, msg: str = ""):
        self.total, self.stage, self.n = int(total), stage, int(start)
        self._lk = threading.Lock()
        report(self.n, self.total, msg or f"{stage}: starting", stage=stage, force=True)

    def add(self, k: int = 1, msg: str = "") -> None:
        with self._lk:
            self.n += k
            n = self.n
        report(n, self.total, msg or f"{self.stage}: {n}/{self.total}", stage=self.stage)

    def finish(self, msg: str = "") -> None:
        end(self.n, self.total, msg or f"{self.stage}: {self.n}/{self.total}", stage=self.stage)
