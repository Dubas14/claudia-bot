"""Fixes track: `slop job selftest --start` / `--check ID`, the two-call detach test the box needs (critic P0: the
one-call selftest cannot see a computer that kills a call's processes when the call or the turn ends). Call A starts
the test job and returns at once; call B (a separate process, like the bot's next tool call) must say RUNNING; a later
check must say PASS; a job killed between calls must say FAIL with the stop-and-report line."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from slop import cli, job

ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = ["slop.core_cli", "slop.job", "slop.fetch"]
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX job control (the box and the parity env are Linux)")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    home, projects = tmp_path / "home", tmp_path / "projects"
    monkeypatch.setenv("SLOP_HOME", str(home))
    monkeypatch.setenv("SLOP_PROJECTS", str(projects))
    monkeypatch.setenv("SLOP_MODULES", ",".join(CORE_MODULES))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY", "SLOP_FREE_ONLY", "SLOP_PROGRESS_FILE", "SLOP_WAIT_MAX"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "MODULES", list(CORE_MODULES))
    yield {"home": home}
    for f in (home / "jobs").glob("*.json"):
        if f.name.endswith(".progress.json"):
            continue
        rec = json.loads(f.read_text())
        if rec.get("state") not in job.TERMINAL:
            job.stop_job(f, rec, grace=2)


def run(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main(["--json", *argv])
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


def other_call(*argv) -> dict:
    """a separate `slop` process: the bot's NEXT tool call."""
    r = subprocess.run([sys.executable, "-m", "slop", "--json", *argv], capture_output=True, text=True,
                       env=dict(os.environ), timeout=60)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_two_call_selftest_running_then_pass(capsys, env):
    rc, a = run(capsys, "job", "selftest", "--start", "--seconds", "3")
    assert rc == 0 and a["phase"] == "started" and a["next"] == f"slop job selftest --check {a['id']}", a
    assert "NEXT tool call" in a["text"] and "end the turn" in a["text"]
    b = other_call("job", "selftest", "--check", a["id"])
    assert b["ok"] and b["phase"] == "running" and b["passed"] is None and "RUNNING" in b["text"], b
    t_end = time.monotonic() + 30
    while True:
        rc, c = run(capsys, "job", "selftest", "--check")                # default: the last --start job
        if c["phase"] != "running" or time.monotonic() > t_end:
            break
        time.sleep(.5)
    assert rc == 0 and c["passed"] is True and c["seen_running"] and "PASS" in c["text"], c
    st = json.loads((env["home"] / "run" / "selftest.json").read_text())
    assert st["id"] == a["id"] and [x["state"] for x in st["checks"]][0] == "running"


def test_two_call_selftest_reports_a_killed_job(capsys, env):
    rc, a = run(capsys, "job", "selftest", "--start", "--seconds", "60")
    assert rc == 0
    path, rec = job.find_job(a["id"], None)
    for _ in range(50):
        rec = job._read(path) or rec
        if rec.get("pid") and rec.get("supervisor_pid"):
            break
        time.sleep(.1)
    for pid in (rec.get("pid"), rec.get("supervisor_pid")):          # the computer kills the call's processes
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, TypeError):
            pass
    time.sleep(.5)
    rc, b = run(capsys, "job", "selftest", "--check", a["id"])
    assert rc == 1 and b["ok"] is False and b["passed"] is False and "FAIL" in b["error"], b
    assert "Stop the setup here" in b["error"]


def test_check_needs_a_started_test_and_flags_exclude(capsys, env):
    rc, out = run(capsys, "job", "selftest", "--check")
    assert rc == 1 and "slop job selftest --start" in out["error"]
    with pytest.raises(SystemExit) as e:                               # argparse usage error
        cli.main(["--json", "job", "selftest", "--start", "--check", "x"])
    cap = capsys.readouterr()
    assert e.value.code == 2 and "not allowed with" in cap.out + cap.err
