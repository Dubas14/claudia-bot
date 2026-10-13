"""slop/progress.py: $SLOP_PROGRESS_FILE reports (atomic JSON, rate limit, end states, thread-safe counter)."""
from __future__ import annotations

import json
import threading

import pytest


@pytest.fixture()
def prog(tmp_path, monkeypatch):
    from slop import progress
    f = tmp_path / "sub" / "progress.json"
    monkeypatch.setenv("SLOP_PROGRESS_FILE", str(f))
    monkeypatch.setattr(progress, "_state", {"stage": None, "t0": 0.0, "last": 0.0, "done0": 0})
    return progress, f


def _read(f):
    return json.loads(f.read_text(encoding="utf-8"))


def test_noop_without_env(monkeypatch, tmp_path):
    from slop import progress
    monkeypatch.delenv("SLOP_PROGRESS_FILE", raising=False)
    assert progress.report(1, 10, "x", stage="s", force=True) is None
    assert progress.read() is None
    assert not list(tmp_path.iterdir())


def test_report_writes_atomic_json(prog):
    progress, f = prog
    r = progress.report(0, 100, "starting", stage="render frames", force=True)
    assert r and f.is_file()
    d = json.loads(f.read_text(encoding="utf-8"))
    assert d["stage"] == "render frames" and d["done"] == 0 and d["total"] == 100 and d["pct"] == 0.0
    assert d["state"] == "running" and d["msg"] == "starting"
    assert not [p for p in f.parent.iterdir() if p.name.endswith(".tmp")]       # no temp files left behind
    assert progress.read() == d


def test_rate_limit_and_end_states(prog, monkeypatch):
    progress, f = prog
    clock = [100.0]
    monkeypatch.setattr(progress.time, "monotonic", lambda: clock[0])
    assert progress.report(0, 10, stage="a", force=True)
    clock[0] += .1
    assert progress.report(3, 10) is None                    # within 0.5 s: skipped
    clock[0] += .6
    r = progress.report(4, 10)
    assert r and r["done"] == 4 and r["rate_per_s"] == pytest.approx(4 / .7, rel=1e-3) and r["eta_s"] == 1
    end = progress.end(7, 10, "stopped short")               # always written, even inside the interval
    assert end["state"] == "stopped" and json.loads(f.read_text())["done"] == 7
    assert progress.end(10, 10)["state"] == "done"
    r = progress.report(1, 5, stage="b", force=True)          # a new stage restarts the clock
    assert r["stage"] == "b" and r["elapsed_s"] == 0


def test_counter_is_thread_safe(prog):
    progress, f = prog
    c = progress.Counter(400, "render lyrics")
    ts = [threading.Thread(target=lambda: [c.add(1) for _ in range(100)]) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    c.finish()
    d = json.loads(f.read_text(encoding="utf-8"))
    assert c.n == 400 and d["done"] == 400 and d["state"] == "done" and d["pct"] == 100.0


def test_report_never_raises(prog, monkeypatch):
    progress, f = prog
    monkeypatch.setattr(progress, "_write", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert progress.report(1, 2, stage="x", force=True) is None


def test_a_command_of_several_stages_is_done_only_at_its_end(prog):
    """`render vertical` (frames, then encode) and `encode --share` (pass 1, then 2) used to write state "done" after
    their first stage: a bot polling `jq .state` stopped there."""
    progress, f = prog
    with progress.command("render vertical", steps=2) as c:
        cnt = progress.Counter(10, "render vertical frames")
        cnt.add(10)
        cnt.finish()
        d = _read(f)
        assert d["state"] == "stage_done" and d["command"] == "render vertical" and d["step"] == "1/2"
        assert d["state"] not in progress.ENDED
        progress.report(0, 5, "starting", stage="encode master vertical", force=True)
        d = _read(f)
        assert d["state"] == "running" and d["step"] == "2/2" and d["stage"] == "encode master vertical"
        progress.end(5, 5, stage="encode master vertical")
        assert _read(f)["state"] == "stage_done"
        c.ok = True
    d = _read(f)
    assert d["state"] == "done" and d["step"] == "2/2" and d["done"] == d["total"] == 5 and d["eta_s"] == 0


def test_a_command_that_fails_or_ends_short(prog):
    progress, f = prog
    with pytest.raises(RuntimeError):
        with progress.command("render frames"):
            progress.Counter(10, "render frames").add(3)
            raise RuntimeError("the page crashed")
    d = _read(f)
    assert d["state"] == "failed" and "the page crashed" in d["msg"] and d["command"] == "render frames"
    with progress.command("render lyrics") as c:
        cnt = progress.Counter(4, "render lyrics")
        cnt.add(2)
        cnt.finish()
        assert _read(f)["state"] == "stage_stopped"
        c.ok = False
    assert _read(f)["state"] == "stopped"


def test_nested_commands_join_the_outer_one(prog):
    progress, f = prog
    with progress.command("render vertical", steps=2):
        with progress.command("render frames"):           # an inner command never ends the outer one
            progress.end(3, 3, stage="render vertical frames")
        assert _read(f)["state"] == "stage_done"
        progress.end(2, 2, stage="encode master vertical")
    d = _read(f)
    assert d["state"] == "done" and d["command"] == "render vertical"


def test_stage_ends_outside_a_command_keep_the_old_states(prog):
    progress, f = prog
    assert progress.end(4, 4, stage="x")["state"] == "done" and progress.end(1, 4, stage="x")["state"] == "stopped"
    assert _read(f)["command"] == "x" and _read(f)["step"] == "1/1"


def test_cli_wraps_commands(prog, monkeypatch):
    """slop/render/cli.py runs each long step inside progress.command (the step count fits the command)."""
    progress, f = prog
    from slop.render import cli
    seen = {}

    def fake():
        seen["depth"] = progress._state.get("depth")
        progress.end(1, 1, stage="encode share pass 1/2")
        progress.end(1, 1, stage="encode share pass 2/2")
        return {"ok": True}
    assert cli._tracked("render encode --share", 2, fake) == {"ok": True}
    d = _read(f)
    assert seen["depth"] == 1 and d["state"] == "done" and d["step"] == "2/2" and d["command"] == "render encode --share"
