"""`slop job` tests: detached background jobs (POSIX: double fork + setsid). No network, no spend.

Children run `python -m slop` with SLOP_MODULES limited to core + job + fetch, so other modules' work in progress
cannot break these tests. Every job here is `slop job _sleep` (the hidden test step).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from slop import cli, core_cli, job, ledger
from slop.config import SlopError

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
    started: list[Path] = []
    yield {"home": home, "projects": projects, "tmp": tmp_path, "started": started}
    # never leave a sleeping job behind
    for store in [home / "jobs", *projects.glob("*/jobs")]:
        for f in store.glob("*.json"):
            if f.name.endswith(".progress.json"):
                continue
            rec = json.loads(f.read_text())
            if rec.get("state") not in job.TERMINAL:
                job.stop_job(f, rec, grace=2)


def run(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main(["--json", *argv])
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


def new_project(capsys, name: str) -> Path:
    rc, out = run(capsys, "new", name)
    assert rc == 0, out
    return Path(out["project"])


def rec_of(p: Path | None, jid: str, env) -> tuple[Path, dict]:
    store = (p / "jobs") if p else env["home"] / "jobs"
    path = store / f"{jid}.json"
    return path, json.loads(path.read_text())


def until(cond, timeout: float = 10.0, step: float = 0.05) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return cond()


# ---------------------------------------------------------------- the core promise
def test_job_outlives_the_process_that_started_it(capsys, env):
    p = new_project(capsys, "jp")
    t0 = time.monotonic()
    cp = subprocess.run([sys.executable, "-m", "slop", "--json", "-p", "jp", "job", "start", "--", "job", "_sleep",
                         "3", "--steps", "3"], capture_output=True, text=True, timeout=60, env=dict(os.environ))
    parent_s = time.monotonic() - t0
    assert cp.returncode == 0, cp.stdout + cp.stderr
    out = json.loads(cp.stdout.strip().splitlines()[-1])
    jid = out["id"]
    assert out["state"] == "running" and "job wait " + jid in out["next"] and out["existing"] is False
    assert parent_s < 3.0, parent_s  # the starting process returned before the step could have finished
    path, rec = rec_of(p, jid, env)
    # the parent process is gone; the job is still alive, in its own session, not a child of this test process
    assert job.alive(rec["pid"], rec["pid_start"]) and job.alive(rec["supervisor_pid"], rec["supervisor_start"])
    assert os.getsid(rec["supervisor_pid"]) != os.getsid(0)
    ppid = int(Path(f"/proc/{rec['supervisor_pid']}/stat").read_text().rsplit(")", 1)[1].split()[1])
    assert ppid != os.getpid()
    assert rec["argv"] == ["job", "_sleep", "3", "--steps", "3"] and rec["cmd"] == "slop --project jp job _sleep 3 --steps 3"
    rc, w = run(capsys, "-p", "jp", "job", "wait", jid, "--max", "20")
    assert rc == 0 and w["state"] == "done" and w["ok"] is True and w["timed_out"] is False
    rec = json.loads(path.read_text())
    assert rec["exit"] == 0 and rec["result"]["slept"] == 3.0 and rec["result"]["job_id"] == jid
    assert rec["progress"]["done"] == rec["progress"]["total"] == 3
    assert 2.5 <= rec["elapsed_s"] < 15 and rec["seen"] is True
    assert "start: slop --project jp job _sleep 3" in Path(rec["log"]).read_text()
    assert until(lambda: not job.alive(rec["pid"], rec["pid_start"])
                 and not job.alive(rec["supervisor_pid"], rec["supervisor_start"]), 5)


def test_job_survives_the_shell_being_killed_with_its_whole_group(capsys, env):
    """What a tool timeout does: SIGKILL to the shell's process group (and SIGHUP to the session)."""
    p = new_project(capsys, "jg")
    out_f = env["tmp"] / "start.json"
    script = (f"{sys.executable} -m slop --json -p jg job start -- job _sleep 3 --steps 3 > {out_f}; sleep 60")
    sh = subprocess.Popen(["bash", "-c", script], start_new_session=True, env=dict(os.environ))
    assert until(lambda: out_f.is_file() and out_f.read_text().strip().endswith("}"), 20)
    os.killpg(sh.pid, signal.SIGHUP)
    os.killpg(sh.pid, signal.SIGKILL)
    sh.wait(timeout=10)
    jid = json.loads(out_f.read_text().strip().splitlines()[-1])["id"]
    path, rec = rec_of(p, jid, env)
    assert job.alive(rec["pid"], rec["pid_start"]), "the job died with the shell"
    rc, w = run(capsys, "-p", "jg", "job", "wait", jid, "--max", "20")
    assert rc == 0 and w["state"] == "done" and w["job"]["exit"] == 0


def test_wait_max_returns_in_time_and_stop_stops(capsys, env):
    p = new_project(capsys, "jw")
    rc, out = run(capsys, "-p", "jw", "job", "start", "--", "job", "_sleep", "60")
    assert rc == 0 and out["state"] == "running"
    jid = out["id"]
    t0 = time.monotonic()
    rc, w = run(capsys, "-p", "jw", "job", "wait", jid, "--max", "2")
    took = time.monotonic() - t0
    assert rc == 0 and w["state"] == "running" and w["timed_out"] is True and w["running"] is True
    assert 1.9 <= took < 3.5, took
    assert w["next"].endswith(f"job wait {jid} --max 25") and "still running" in w["text"]
    t0 = time.monotonic()
    rc, w = run(capsys, "-p", "jw", "job", "wait", jid, "--max", "0")
    assert time.monotonic() - t0 < 1.0 and w["state"] == "running"
    rc, s = run(capsys, "-p", "jw", "job", "status", "last")
    assert rc == 0 and s["id"] == jid and s["state"] == "running" and s["job"]["progress"]["total"] == 4
    path, rec = rec_of(p, jid, env)
    rc, st = run(capsys, "-p", "jw", "job", "stop", jid, "--grace", "5")
    assert rc == 0 and st["state"] == "stopped" and st["ok"] is True
    rec = json.loads(path.read_text())
    assert rec["state"] == "stopped" and not job.alive(rec["pid"], rec["pid_start"])
    assert not job.alive(rec["supervisor_pid"], rec["supervisor_start"])
    rc, again = run(capsys, "-p", "jw", "job", "stop", jid)
    assert rc == 0 and "already ended" in again["text"]


def test_env_wait_default(monkeypatch):
    assert job.default_wait() == 25.0
    monkeypatch.setenv("SLOP_WAIT_MAX", "8")
    assert job.default_wait() == 8.0
    monkeypatch.setenv("SLOP_WAIT_MAX", "nonsense")
    assert job.default_wait() == 25.0


def test_killed_job_is_reported_failed(capsys, env):
    p = new_project(capsys, "jk")
    rc, out = run(capsys, "-p", "jk", "job", "start", "--", "job", "_sleep", "60")
    path, rec = rec_of(p, out["id"], env)
    os.killpg(rec["pgid"], signal.SIGKILL)  # the box killed everything (timeout, out of memory, restart)
    assert until(lambda: not job.alive(rec["pid"], rec["pid_start"])
                 and not job.alive(rec["supervisor_pid"], rec["supervisor_start"]))
    rc, st = run(capsys, "-p", "jk", "status")
    assert rc == 0 and st["jobs"] and st["jobs"][0]["state"] == "failed"
    assert "FAILED" in st["text"] and f"job status {out['id']}" in st["text"]
    rc, s = run(capsys, "-p", "jk", "job", "status", out["id"])
    assert rc == 1 and s["ok"] is False and s["state"] == "failed"
    assert "ended without recording an exit" in s["error"] and "start it again" in s["text"]
    assert json.loads(path.read_text())["state"] == "failed"
    rc, st = run(capsys, "-p", "jk", "status")
    assert st["jobs"] == []  # read once: no longer listed by status


def test_step_killed_alone_is_reported_failed_by_its_supervisor(capsys, env):
    p = new_project(capsys, "jo")
    rc, out = run(capsys, "-p", "jo", "job", "start", "--", "job", "_sleep", "60")
    path, rec = rec_of(p, out["id"], env)
    os.kill(rec["pid"], signal.SIGKILL)  # e.g. the out-of-memory killer took the step only
    rc, w = run(capsys, "-p", "jo", "job", "wait", out["id"], "--max", "10")
    assert rc == 1 and w["state"] == "failed" and "killed by signal 9" in w["error"]
    assert json.loads(path.read_text())["exit"] == -9


def test_failing_step_reports_its_own_error(capsys, env):
    new_project(capsys, "jf")
    rc, out = run(capsys, "-p", "jf", "job", "start", "--wait", "15", "--", "job", "_sleep", "0.1", "--fail")
    assert rc == 1 and out["ok"] is False and out["state"] == "failed"
    assert "failing on purpose" in out["error"] and out["job"]["exit"] == 1
    assert out["result"]["ok"] is False


def test_start_validates_the_command_first(capsys, env):
    p = new_project(capsys, "jv")
    for argv, needle in ((["analyse"], "not a valid command"), ([], "name the slop command"),
                         (["job", "wait", "x"], "cannot start, wait for or stop jobs"),
                         (["status", "--help"], "--help does not run as a job"),
                         (["runs"], "not a valid command")):
        rc, out = run(capsys, "-p", "jv", "job", "start", "--", *argv)
        assert rc == 1 and needle in out["error"], (argv, out)
    assert not (p / "jobs").exists() or not list((p / "jobs").glob("*.json"))
    rc, out = run(capsys, "-p", "jv", "job", "status", "nope-zzzz")
    assert rc == 1 and "job list" in out["error"]
    rc, out = run(capsys, "-p", "jv", "job", "status", "last")
    assert rc == 1 and "no jobs yet" in out["error"]
    rc, out = run(capsys, "-p", "jv", "job", "status", "../etc")
    assert rc == 1 and "bad job id" in out["error"]


def test_same_command_is_not_started_twice(capsys, env):
    new_project(capsys, "jd")
    rc, a = run(capsys, "-p", "jd", "job", "start", "--", "job", "_sleep", "30")
    rc, b = run(capsys, "-p", "jd", "job", "start", "job", "_sleep", "30")  # without the -- too
    assert rc == 0 and b["existing"] is True and b["id"] == a["id"] and "already running" in b["text"]
    rc, c = run(capsys, "-p", "jd", "job", "start", "--again", "--", "job", "_sleep", "30")
    assert c["existing"] is False and c["id"] != a["id"]
    rc, li = run(capsys, "-p", "jd", "job", "list", "--running")
    assert li["count"] == 2 and {r["id"] for r in li["jobs"]} == {a["id"], c["id"]}
    for jid in (a["id"], c["id"]):
        assert run(capsys, "-p", "jd", "job", "stop", jid, "--grace", "3")[1]["state"] == "stopped"


def test_project_flag_inside_the_child_command_and_projectless_jobs(capsys, env):
    p = new_project(capsys, "jx")
    rc, out = run(capsys, "job", "start", "--wait", "15", "--", "slop", "-p", "jx", "--json", "job", "_sleep", "0.1")
    assert rc == 0 and out["state"] == "done" and out["job"]["project"] == str(p)
    assert out["job"]["argv"] == ["job", "_sleep", "0.1"] and (p / "jobs" / f"{out['id']}.json").is_file()
    rc, g = run(capsys, "job", "start", "--wait", "15", "--", "job", "_sleep", "0.1")  # no project anywhere
    assert rc == 0 and g["state"] == "done" and g["job"]["project"] is None
    assert (env["home"] / "jobs" / f"{g['id']}.json").is_file() and g["job"]["wait"].startswith("slop job wait")
    rc, s = run(capsys, "-p", "jx", "job", "status", g["id"])  # found in the global store from a project context
    assert rc == 0 and s["id"] == g["id"]
    rc, s = run(capsys, "job", "status", out["id"])  # and a project's job without naming the project
    assert rc == 0 and s["id"] == out["id"]
    rc, li = run(capsys, "job", "list", "--all")
    assert {out["id"], g["id"]} <= {r["id"] for r in li["jobs"]}
    rc, lg = run(capsys, "job", "log", g["id"])
    assert rc == 0 and "start: slop job _sleep 0.1" in lg["tail"]


def test_status_shows_running_jobs_and_waits_for_the_step(capsys, env, monkeypatch):
    new_project(capsys, "js")
    rc, out = run(capsys, "-p", "js", "job", "start", "--", "job", "_sleep", "30")
    jid = out["id"]
    rc, st = run(capsys, "-p", "js", "status")
    assert st["jobs_running"] == 1 and st["jobs"][0]["id"] == jid and st["jobs"][0]["state"] == "running"
    assert "background jobs:" in st["text"] and f"job wait {jid}" in st["text"]
    assert st["next"]["stage"] == "brief"  # an unrelated job does not change the next step
    rc, pr = run(capsys, "projects")
    assert pr["projects"][0]["jobs_running"] == 1 and "1 job running" in pr["projects"][0]["next"]

    real = core_cli.evaluate_stages

    def fake(pdir, proj):  # the next step IS what the job runs
        return [core_cli._stage("render", False, "frames missing", "render the frames",
                                core_cli._pcmd(pdir, "job _sleep 30"), auto=True)] + real(pdir, proj)
    monkeypatch.setattr(core_cli, "evaluate_stages", fake)
    rc, st = run(capsys, "-p", "js", "status")
    nx = st["next"]
    assert nx["running_job"] == jid and nx["cmd"].endswith(f"job wait {jid} --max 25")
    assert nx["step_cmd"].endswith("job _sleep 30") and "wait for job" in nx["do"]
    rc, n = run(capsys, "-p", "js", "next")
    assert rc == 0 and n["stopped"] == "job-running" and n["ran"] == []
    run(capsys, "-p", "js", "job", "stop", jid, "--grace", "3")


def test_free_only_lock_reaches_the_step(capsys, env, tmp_path, monkeypatch):
    new_project(capsys, "jl")
    rc, out = run(capsys, "-p", "jl", "job", "start", "--free-only", "--wait", "15", "--", "job", "_sleep", "0.1")
    assert rc == 0 and out["result"]["free_only"] is True
    rc, out = run(capsys, "-p", "jl", "job", "start", "--again", "--wait", "15", "--", "job", "_sleep", "0.1")
    assert out["result"]["free_only"] is False
    pdir = env["projects"] / "jl"
    monkeypatch.setenv("SLOP_FREE_ONLY", "1")
    with pytest.raises(SlopError, match="spending is locked"):
        ledger.check_budget(pdir, "openrouter", add_usd=0.01, yes=True)
    monkeypatch.setenv("SLOP_FREE_ONLY", "0")
    ledger.check_budget(pdir, "openrouter", add_usd=0.01, yes=True)  # 0 = off


def test_selftest_passes(capsys, env):
    rc, out = run(capsys, "job", "selftest", "--seconds", "2")
    assert rc == 0 and out["ok"] is True, out
    c = out["checks"]
    assert c["outlived_parent"] is True and c["state"] == "done" and c["progress_seen"] is True
    assert c["parent_exit_s"] < 3.0
    assert not list((env["home"] / "jobs").glob(f"{out['job']}.*"))  # a passing selftest cleans up


# ---------------------------------------------------------------- units
def test_progress_reader_accepts_the_shared_format(tmp_path):
    pf = tmp_path / "x.progress.json"
    rec = {"id": "render-frames-abcd", "state": "running", "started_ts": time.time() - 100, "progress_file": str(pf),
           "argv": ["render", "frames"], "project": None}
    assert job.read_progress(rec) is None
    pf.write_text(json.dumps({"stage": "render frames", "done": 1200, "total": 4800, "pct": 25.0, "msg": "",
                              "eta_s": 300, "state": "running"}))
    pr = job.read_progress(rec)
    assert pr == {"done": 1200, "total": 4800, "eta": 300, "msg": "render frames"}
    pf.write_text(json.dumps({"done": 10, "total": 40, "msg": "downloading"}))
    pr = job.read_progress(rec)
    assert pr["eta"] is not None and 250 <= pr["eta"] <= 350  # computed from the elapsed time: 30 left at 0.1/s
    assert job.progress_text(pr).startswith("10/40, downloading, eta ")


def test_analyze_progress_fallback(tmp_path):
    (tmp_path / "analysis").mkdir()
    (tmp_path / "analysis/progress.json").write_text(json.dumps(
        {"running": True, "steps": ["stems", "align", "beats", "hits", "sections"], "step": "beats",
         "done": {"stems": {}, "align": {}}}))
    rec = {"id": "analyze-abcd", "state": "running", "started_ts": time.time() - 5,
           "progress_file": str(tmp_path / "none.json"), "argv": ["analyze"], "project": str(tmp_path)}
    pr = job.read_progress(rec)
    assert pr["done"] == 2 and pr["total"] == 5 and pr["msg"] == "step beats"


def test_write_progress_is_a_noop_without_the_env(tmp_path, monkeypatch):
    job.write_progress(1, 2, "x")  # SLOP_PROGRESS_FILE unset: nothing happens, nothing raises
    pf = tmp_path / "p.json"
    monkeypatch.setenv("SLOP_PROGRESS_FILE", str(pf))
    job.write_progress(3, 3, "done", final=True)
    d = json.loads(pf.read_text())
    assert d["done"] == 3 and d["total"] == 3


def test_strip_globals_and_command_words():
    assert job.strip_globals(["--", "-p", "x", "--json", "render", "frames", "--workers", "4"]) == \
        ("x", ["render", "frames", "--workers", "4"])
    assert job.strip_globals(["slop", "--project=y", "analyze"]) == ("y", ["analyze"])
    assert job.strip_globals(["python", "-m", "slop", "analyze"]) == (None, ["analyze"])
    assert job.command_words(["render", "frames", "--workers", "4"]) == ["render", "frames"]
    assert job.command_words(["job", "_sleep", "3"]) == ["job", "_sleep"]
    assert job.dur(42) == "42 s" and job.dur(200) == "3 min 20 s" and job.dur(7300) == "2 h 01 min"


def test_alive_and_pid_reuse_guard():
    me = os.getpid()
    assert job.alive(me) and job.alive(me, job.proc_start(me))
    assert not job.alive(me, "1")  # same pid, another start time: a reused pid is not our job
    assert not job.alive(None) and not job.alive(2 ** 22 + 12345)
