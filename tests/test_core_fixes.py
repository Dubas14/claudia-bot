"""Core fixes after review: the router loads `review`; frames judged by the render fingerprint; long steps shown as
jobs first; `next` does not restart a step whose last job changed nothing, waits for the sections before the board,
and keeps to a time budget; job ordering by sequence number; `job stop` before the step started; `job start` refuses
`next` and command groups; fetch hints are shell-quoted; Drive resource keys; the project-less spend lock.
No network, no spend."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

from slop import cli, core_cli, fetch, job, ledger
from slop.config import SlopError

ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = ["slop.core_cli", "slop.job", "slop.fetch"]
T0 = time.time() - 10_000
posix = pytest.mark.skipif(os.name == "nt", reason="POSIX job control (the box and the parity env are Linux)")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("SLOP_MODULES", ",".join(CORE_MODULES))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY", "SLOP_FREE_ONLY", "SLOP_PROGRESS_FILE", "SLOP_WAIT_MAX",
              "SLOP_JOB_ID"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "MODULES", list(CORE_MODULES))
    yield tmp_path
    for f in (tmp_path / "projects").glob("*/jobs/*.json"):
        if not f.name.endswith(".progress.json"):
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


def write(path: Path, data, t: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    if t is not None:
        os.utime(path, (T0 + t, T0 + t))
    return path


def stages(p: Path) -> dict:
    return {s["stage"]: s for s in core_cli.project_status(p)["stages"]}


def _fake_stages(monkeypatch, make):
    monkeypatch.setattr(core_cli, "evaluate_stages", lambda pdir, proj: make(pdir))


# ---------------------------------------------------------------- router (blocker)
def test_router_loads_the_review_module(monkeypatch):
    """The FULL module list (no SLOP_MODULES): `review` is registered, so the scan stage's commands exist."""
    import importlib
    monkeypatch.delenv("SLOP_MODULES", raising=False)
    real = importlib.reload(cli)  # the module list as shipped (the fixture patched cli.MODULES)
    try:
        assert real.MODULES.index("slop.render.cli") < real.MODULES.index("slop.review.cli")
        tree = core_cli.command_tree()
        assert tree is not None and "review" in tree, sorted(tree or {})
        assert {"scan-sheets", "record", "status"} <= set(tree["review"])
        assert core_cli.command_available("slop --project x review scan-sheets", tree) is True
    finally:
        monkeypatch.setattr(cli, "MODULES", list(CORE_MODULES))


def test_review_status_runs_through_the_router(capsys, monkeypatch):
    mods = CORE_MODULES + ["slop.review.cli"]
    monkeypatch.setattr(cli, "MODULES", mods)
    monkeypatch.setenv("SLOP_MODULES", ",".join(mods))
    p = new_project(capsys, "rv")
    write(p / "edit/edl.json", {"s001": {"plate": "p1"}})
    rc, out = run(capsys, "-p", "rv", "review", "status")
    assert rc == 0 and out["recorded"] is False and "review scan-sheets" in out["text"]


# ---------------------------------------------------------------- frames by fingerprint (major)
def _frames_project(capsys, name: str) -> Path:
    p = new_project(capsys, name)
    write(p / "analysis/beats.json", {"duration": 0.5}, 20)  # 12 frames at 24 fps
    for n in ("beats", "lyrics", "shots", "edl", "plates"):
        write(p / f"engine/assets/{n}.js", f"window.X_{n} = 1;", 70)
    for i in range(12):
        write(p / f"render/frames/f{i:05d}.jpg", "j", 80)
    return p


def _record_fingerprint(p: Path, t: float = 80, **extra) -> None:
    from slop.render import project as RP
    fp = RP.inputs_fingerprint(p, RP.page_spec(p))
    fp.update(extra)
    RP.write_fingerprint(p / "render/frames", fp)
    os.utime(p / "render/frames/.inputs.json", (T0 + t, T0 + t))


def test_identical_reexport_keeps_the_frames_current(capsys):
    pytest.importorskip("slop.render.project")
    p = _frames_project(capsys, "fp1")
    _record_fingerprint(p)
    st = stages(p)
    assert st["render"]["cmd"].endswith("render encode --review") and st["master"]["cmd"].endswith("render encode")
    for n in ("beats", "lyrics", "shots", "edl", "plates"):  # `edit export` again, nothing changed: new file times only
        os.utime(p / f"engine/assets/{n}.js", (T0 + 200, T0 + 200))
    st = stages(p)
    assert st["render"]["cmd"].endswith("render encode --review"), st["render"]
    assert st["master"]["cmd"].endswith("render encode")
    write(p / "out/review.mp4", "v", 90)  # encoded from these frames before the re-export: still current
    st = stages(p)
    assert st["render"]["done"], st["render"]
    write(p / "engine/assets/shots.js", "window.X_shots = 2;", 210)  # a real change
    st = stages(p)
    assert st["render"]["cmd"].endswith("render frames") and "STALE" in st["render"]["detail"]
    assert st["master"]["cmd"].endswith("render frames")


def test_frames_fallback_without_the_render_module(capsys, monkeypatch):
    p = _frames_project(capsys, "fp2")
    write(p / "render/frames/.inputs.json", {"hash": "abc"}, 65)  # an older run: before the last export
    monkeypatch.setattr(core_cli, "_render_project", lambda: None)
    assert not core_cli.frames_ready(p, {})  # .inputs.json older than the engine data
    os.utime(p / "render/frames/.inputs.json", (T0 + 85, T0 + 85))  # `render frames` ran (a no-op run rewrites it)
    st = stages(p)
    assert core_cli.frames_ready(p, {}) and st["render"]["cmd"].endswith("render encode --review")
    os.utime(p / "engine/assets/edl.js", (T0 + 90, T0 + 90))
    assert not core_cli.frames_ready(p, {})


def test_placeholder_frames_point_at_render_info(capsys):
    pytest.importorskip("slop.render.project")
    p = _frames_project(capsys, "fp3")
    _record_fingerprint(p, placeholders=True)
    fs = core_cli.frames_state(p, {})
    assert fs["complete"] and fs["current"] and fs["placeholders"] and not fs["ready"]
    st = stages(p)
    assert st["render"]["cmd"].endswith("render info") and not st["render"]["auto"]
    assert "--allow-missing" in st["render"]["do"]


# ---------------------------------------------------------------- `slop next`: no restart without a change (minor)
@posix
def test_next_does_not_restart_a_long_step_that_changed_nothing(capsys, monkeypatch):
    p = new_project(capsys, "nr1")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("job",)})
    monkeypatch.setattr(core_cli, "LONG_STEPS", core_cli.LONG_STEPS | {("job",)})
    detail = {"v": "frames missing"}
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("render", False, detail["v"], "render the frames",
                                                         core_cli._pcmd(d, "job _sleep 0.1 --steps 1"), auto=True)])
    rc, out = run(capsys, "-p", "nr1", "next")
    jid = out["ran"][0]["job"]["id"]
    assert out["stopped"] == "job-started"
    assert json.loads((p / "jobs" / f"{jid}.json").read_text())["status_sig"]
    rc, w = run(capsys, "-p", "nr1", "job", "wait", jid, "--max", "15")
    assert w["state"] == "done"
    rc, out = run(capsys, "-p", "nr1", "next")
    assert out["ran"] == [] and out["stopped"] == "last-no-progress", out["text"]
    assert f"job status {jid}" in out["text"] and "running it again would not help" in out["why"]
    rc, st = run(capsys, "-p", "nr1", "status")
    assert st["next"]["repeat"] == "last-no-progress" and f"last run: job {jid} finished" in st["text"]
    assert "let slop run it" not in st["text"]
    rc, out = run(capsys, "-p", "nr1", "next", "--retry")  # the operator decides to run it again anyway
    assert out["stopped"] == "job-started" and out["ran"][0]["job"]["id"] != jid
    run(capsys, "-p", "nr1", "job", "wait", out["ran"][0]["job"]["id"], "--max", "15")
    detail["v"] = "frames missing (the owner replaced a plate)"  # something changed: next may start it again
    rc, out = run(capsys, "-p", "nr1", "next")
    assert out["stopped"] == "job-started"
    run(capsys, "-p", "nr1", "job", "wait", out["ran"][0]["job"]["id"], "--max", "15")


@posix
def test_next_does_not_restart_a_failed_or_stopped_long_step(capsys, monkeypatch):
    new_project(capsys, "nr2")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("job",)})
    monkeypatch.setattr(core_cli, "LONG_STEPS", core_cli.LONG_STEPS | {("job",)})
    cmd = {"c": "job _sleep 0 --fail"}
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("render", False, "x", "render", core_cli._pcmd(d, cmd["c"]),
                                                         auto=True)])
    rc, out = run(capsys, "-p", "nr2", "next")
    jid = out["ran"][0]["job"]["id"]
    run(capsys, "-p", "nr2", "job", "wait", jid, "--max", "15")
    rc, out = run(capsys, "-p", "nr2", "next")
    assert out["stopped"] == "last-failed" and out["ran"] == [] and "failing on purpose" in out["text"]
    cmd["c"] = "job _sleep 30"
    rc, out = run(capsys, "-p", "nr2", "next")
    jid = out["ran"][0]["job"]["id"]
    run(capsys, "-p", "nr2", "job", "stop", jid, "--grace", "3")
    rc, out = run(capsys, "-p", "nr2", "next")
    assert out["stopped"] == "last-stopped" and out["ran"] == []


def test_status_signature_follows_the_project(capsys):
    p = new_project(capsys, "sig")
    sig = core_cli.project_signature(p)
    assert sig and sig == core_cli.project_status(p, tree=None)["signature"]
    write(p / "lyrics/lyrics.txt", "a new line\n")
    assert core_cli.project_signature(p) != sig


# ---------------------------------------------------------------- sections before the board (minor)
def test_next_confirms_the_sections_before_board_draft(capsys, monkeypatch):
    p = new_project(capsys, "secb")
    write(p / "analysis/beats.json", {"duration": 60, "sections": [
        {"name": "verse1", "t0": 0, "t1": 30, "source": "heuristic", "unconfirmed": True},
        {"name": "chorus1", "t0": 30, "t1": 60, "source": "heuristic", "unconfirmed": True}]})
    tree = {"board": {"draft": {}}, "song": {"sections": {}}, "next": {}, "status": {}}
    monkeypatch.setattr(core_cli, "command_tree", lambda: tree)
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("board", False, "no board/shots.json", "draft the board",
                                                         core_cli._pcmd(d, "board draft"), auto=True)])
    rc, out = run(capsys, "-p", "secb", "next")
    confirm = "slop --project secb song sections --set verse1@0,chorus1@30"
    assert out["stopped"] == "sections" and out["ran"] == [] and out["next"]["first"] == confirm
    assert "FIRST: " in out["text"] and confirm in out["text"]
    rc, st = run(capsys, "-p", "secb", "status")
    lines = st["text"].splitlines()
    assert lines.index(f"      {confirm}") < lines.index("      slop --project secb board draft")
    assert "let slop run it" not in st["text"]


# ---------------------------------------------------------------- time budget of one `next` call (minor)
def test_next_stops_starting_inline_steps_after_the_time_budget(capsys, monkeypatch):
    p = new_project(capsys, "tb")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("decide",)})
    monkeypatch.setenv("SLOP_WAIT_MAX", "0")

    def make(d):
        log = (d / "DECISIONS.md").read_text()
        return [core_cli._stage(f"s{k}", f"step-{k}" in log, "", "", core_cli._pcmd(d, f"decide step-{k}"), auto=True)
                for k in (1, 2, 3)]
    _fake_stages(monkeypatch, make)
    rc, out = run(capsys, "-p", "tb", "next", "--steps", "3")
    assert [r["stage"] for r in out["ran"]] == ["s1"] and out["stopped"] == "time"
    assert "run `next` again to continue" in out["text"]
    assert "step-2" not in (p / "DECISIONS.md").read_text()


# ---------------------------------------------------------------- job start refuses `next` and command groups (minor)
def test_job_start_refuses_next_and_command_groups(capsys, monkeypatch):
    mods = CORE_MODULES + ["slop.review.cli"]
    monkeypatch.setattr(cli, "MODULES", mods)
    monkeypatch.setenv("SLOP_MODULES", ",".join(mods))
    p = new_project(capsys, "grp")
    for argv, needle in ((["next"], "does not run as a job"), (["review"], "names a command group"),
                         (["review", "--json"], "names a command group")):
        rc, out = run(capsys, "-p", "grp", "job", "start", "--", *argv)
        assert rc == 1 and needle in out["error"], (argv, out)
    assert not list((p / "jobs").glob("*.json"))
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="c")
    g = sub.add_parser("render")
    g.set_defaults(func=lambda a: {})
    gs = g.add_subparsers(dest="step")
    gs.add_parser("frames")
    sub.add_parser("decide")
    assert job._group_without_step(ap, ["render"]) == "render"
    assert job._group_without_step(ap, ["render", "frames"]) is None
    assert job._group_without_step(ap, ["decide", "step-1"]) is None


def test_status_never_waits_for_its_own_job(monkeypatch):
    jobs = [{"id": "x-aaaa", "state": "running"}, {"id": "y-bbbb", "state": "done"}]
    assert [j["id"] for j in core_cli._running(jobs)] == ["x-aaaa"]
    monkeypatch.setenv("SLOP_JOB_ID", "x-aaaa")
    assert core_cli._running(jobs) == []


# ---------------------------------------------------------------- `last` by sequence, not wall clock (minor)
@posix
def test_last_is_the_newest_by_sequence_even_when_the_clock_stepped_back(capsys):
    p = new_project(capsys, "seq")
    rc, a = run(capsys, "-p", "seq", "job", "start", "--wait", "15", "--", "job", "_sleep", "0.05", "--steps", "1")
    rc, b = run(capsys, "-p", "seq", "job", "start", "--wait", "15", "--", "job", "_sleep", "0.1", "--steps", "1")
    ra = json.loads((p / "jobs" / f"{a['id']}.json").read_text())
    rb = json.loads((p / "jobs" / f"{b['id']}.json").read_text())
    assert rb["seq"] == ra["seq"] + 1
    rb["started_ts"] = ra["started_ts"] - 80  # the clock stepped back ~80 s between the two starts
    (p / "jobs" / f"{b['id']}.json").write_text(json.dumps(rb))
    rc, s = run(capsys, "-p", "seq", "job", "status", "last")
    assert s["id"] == b["id"]
    rc, li = run(capsys, "-p", "seq", "job", "list")
    assert [r["id"] for r in li["jobs"]] == [a["id"], b["id"]]
    import shutil
    shutil.rmtree(p / "jobs" / ".seq")  # the counter folder lost: numbering continues from the records
    assert job.next_seq(p / "jobs") == rb["seq"] + 1


def test_next_seq_is_unique_and_prunes_markers(tmp_path):
    store = tmp_path / "jobs"
    got = [job.next_seq(store) for _ in range(20)]
    assert got == list(range(1, 21))
    assert len(list((store / ".seq").iterdir())) <= 10


# ---------------------------------------------------------------- `job stop` while starting (minor)
@posix
def test_supervisor_honours_a_stop_that_came_before_the_step(capsys, tmp_path):
    p = new_project(capsys, "stp")
    store = p / "jobs"
    store.mkdir(exist_ok=True)
    path = store / "job-sleep-zzzz.json"
    rec = {"id": "job-sleep-zzzz", "project": str(p), "argv": ["job", "_sleep", "30"], "cmd": "slop job _sleep 30",
           "cwd": str(tmp_path), "started": "now", "started_ts": time.time(), "state": "starting", "pid": None,
           "log": str(store / "job-sleep-zzzz.log"), "out": str(store / "job-sleep-zzzz.out"),
           "progress_file": str(store / "job-sleep-zzzz.progress.json")}
    path.write_text(json.dumps(rec))
    path.with_suffix(".stop").write_text("now\n")
    t0 = time.monotonic()
    cp = subprocess.run([sys.executable, "-m", "slop.job", "_supervise", str(path)], capture_output=True, text=True,
                        timeout=60, env={**os.environ, "PYTHONPATH": str(ROOT)})
    assert cp.returncode == 0 and time.monotonic() - t0 < 20
    r = json.loads(path.read_text())
    assert r["state"] == "stopped" and r["pid"] is None and "before the step started" in r["error"]
    assert not Path(rec["out"]).exists()  # the step never ran


def test_stop_of_a_job_whose_supervisor_never_came_up(monkeypatch, tmp_path):
    monkeypatch.setattr(job, "START_CONFIRM_S", 0.5)
    store = tmp_path / "jobs"
    store.mkdir()
    path = store / "x-abcd.json"
    rec = {"id": "x-abcd", "argv": ["job", "_sleep", "1"], "cmd": "slop job _sleep 1", "state": "starting",
           "started_ts": time.time() - 0.7, "pid": None, "supervisor_pid": None, "out": str(store / "x-abcd.out"),
           "log": str(store / "x-abcd.log")}
    path.write_text(json.dumps(rec))
    r = job.stop_job(path, rec, grace=0.2)
    assert r["state"] == "stopped" and path.with_suffix(".stop").exists()


# ---------------------------------------------------------------- fetch (major + minor)
def test_fetch_hints_are_shell_quoted():
    dest = Path("/tmp/rev/f1/audio/My Song (final).wav")
    h = fetch._next_hint(dest, "f1")
    assert shlex.split(h) == ["slop", "--project", "f1", "song", "ingest", str(dest)]
    z = fetch._next_hint(Path("/tmp/rev/stems (v2).zip"), None)
    words = shlex.split(z.split(": ", 1)[1])
    assert words[-2:] == ["/tmp/rev/stems (v2).zip", "/tmp/rev/stems (v2)"]
    im = fetch._next_hint(Path("/tmp/my plates/p 1.png"), "'my proj'")
    assert shlex.split(im.split("then: ", 1)[1])[-1] == "/tmp/my plates"


@pytest.mark.parametrize("url, rk", [
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp_qr-st/view?usp=drive_link&resourcekey=0-XyZ", "0-XyZ"),
    ("https://drive.google.com/u/0/uc?id=1AbCdEfGhIjKlMnOp_qr-st&export=download", None),
    ("https://drive.google.com/u/1/open?id=1AbCdEfGhIjKlMnOp_qr-st&resourcekey=0-a_b", "0-a_b"),
])
def test_drive_link_forms(url, rk):
    kind, dl = fetch.classify(url)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(dl).query))
    assert kind == "drive" and q["id"] == "1AbCdEfGhIjKlMnOp_qr-st" and q["export"] == "download"
    assert q.get("resourcekey") == rk


# ---------------------------------------------------------------- the spend lock without a project (minor)
def test_spend_lock_needs_no_project(capsys, monkeypatch):
    ledger.assert_spend_allowed("openrouter")  # no lock, no project: allowed
    monkeypatch.setenv("SLOP_FREE_ONLY", "1")
    with pytest.raises(SlopError, match="SLOP_FREE_ONLY"):
        ledger.assert_spend_allowed("openrouter")
    monkeypatch.delenv("SLOP_FREE_ONLY")
    p = new_project(capsys, "frz")
    run(capsys, "-p", "frz", "spend", "--freeze", "owner: faces look wrong")
    with pytest.raises(SlopError, match="frozen"):
        ledger.assert_spend_allowed("openrouter", p)
    with pytest.raises(SlopError, match="frozen"):
        ledger.check_budget(p, "openrouter", 0.01)
