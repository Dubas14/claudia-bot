"""Status + `slop next` hardening: the scan stage, the sections hint, clip-only prompt approvals, frames -> encode,
the auto flag, and `slop next` (runs free steps, starts long ones as jobs, never runs gates/manual/paid steps).
No network, no spend."""
from __future__ import annotations

import importlib
import json
import os
import time
from pathlib import Path

import pytest

from slop import cli, core_cli, job

ROOT = Path(__file__).resolve().parents[1]
CORE_MODULES = ["slop.core_cli", "slop.job", "slop.fetch"]
T0 = time.time() - 10_000


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("SLOP_MODULES", ",".join(CORE_MODULES))
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY", "SLOP_FREE_ONLY", "SLOP_PROGRESS_FILE"):
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


def new_project(capsys, name: str, *extra) -> Path:
    rc, out = run(capsys, "new", name, *extra)
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


def _clip(p: Path, cid: str, status: str, t: float = 60, **extra) -> None:
    c = {"id": cid, "status": status, "kind": extra.pop("kind", "motion"), "provider": "openrouter",
         "model": "bytedance/seedance-2.5", "start": f"plates/{cid}.jpg", "body": {"prompt": f"{cid} prompt",
                                                                                 "duration": 5}, **extra}
    write(p / f"clips/{cid}.json", c, t)


# ---------------------------------------------------------------- scan stage
def _v1_ready(p: Path) -> None:
    for n in ("beats", "lyrics", "shots", "edl", "plates"):
        write(p / f"engine/assets/{n}.js", f"window.X_{n} = {{}};", 70)
    write(p / "render/lyrics-report.json", {"checked": 4, "drawn": 4, "missing": []}, 80)
    write(p / "out/review.mp4", "\0" * 10, 90)


def _record(p: Path, findings: list, checked: list, t: float | None = None) -> None:
    """Write render/scan/scan.json the way the review module does (slop.review.scan.record)."""
    from slop.review.scan import record
    f = write(p / "render/scan/findings.json", {"findings": findings, "checked": checked, "given": len(checked)})
    record(p, f)
    if t is not None:
        os.utime(p / core_cli.SCAN_FILE, (T0 + t, T0 + t))


def _sheets(p: Path) -> None:
    """What `review scan-sheets` leaves behind for core: render/scan-list.json (no ffmpeg needed here)."""
    from slop.review.scan import used_takes
    write(p / core_cli.SCAN_LIST, used_takes(p)[0])


def test_scan_stage_only_when_the_edit_plays_clips(capsys):
    p = new_project(capsys, "scan")
    write(p / "edit/edl.json", {"s001": {"plate": "p1"}}, 60)
    assert "scan" not in stages(p)  # plates only: nothing generated to scan
    take = {"n": 1, "status": "delivered", "file": "clips/SD01/take-1.mp4"}
    _clip(p, "SD01", "delivered", takes=[take])
    write(p / "clips/SD01/take-1.mp4", "x", 55)
    write(p / "edit/edl.json", {"s001": {"segs": [{"t0": 0, "clip": "SD01-t1", "in": 0}]}, "s002": {"plate": "p1"}}, 60)
    st = stages(p)
    names = list(st)
    assert names.index("render") < names.index("scan") < names.index("gate:v1") < names.index("master")
    assert not st["scan"]["done"] and "1 generated take(s)" in st["scan"]["detail"]
    assert st["scan"]["auto"] is True and st["scan"]["cmd"] == "slop --project scan review scan-sheets"
    _v1_ready(p)
    rc, out = run(capsys, "-p", "scan", "gate", "v1", "--approve")
    assert rc == 1 and "safety-scanned" in out["error"] and "--force" in out["error"]
    assert "next: slop --project scan review scan-sheets" in out["error"]
    _sheets(p)
    st = stages(p)
    assert st["scan"]["auto"] is False and st["scan"]["cmd"].endswith("review record render/scan/findings.json")
    assert "findings-template.json" in st["scan"]["do"]
    _record(p, [{"clip": "SD01-t1", "time": 1.0, "severity": "block", "kind": "nudity", "what": "x"},
                {"clip": "SD01-t1", "time": 2.0, "severity": "fix", "kind": "canon", "what": "y"}], ["SD01-t1"], 100)
    st = stages(p)
    assert not st["scan"]["done"] and "1 open block finding(s): SD01-t1 @1.0: x" in st["scan"]["detail"]
    assert st["scan"]["cmd"].endswith("review status") and "re-make" in st["scan"]["do"]
    rc, out = run(capsys, "-p", "scan", "gate", "v1", "--approve")
    assert rc == 1 and "open block" in out["error"] and "review status" in out["error"]
    _record(p, [{"clip": "SD01-t1", "time": 2.0, "severity": "fix", "kind": "canon", "what": "y"}], ["SD01-t1"], 100)
    st = stages(p)  # a clean re-scan of the same take replaces its findings
    assert st["scan"]["done"] and "0 open blocks" in st["scan"]["detail"]
    rc, out = run(capsys, "-p", "scan", "gate", "v1", "--approve")
    assert rc == 0, out
    # a re-made take that the edit now plays: the sheets are made again first, then it is checked
    _clip(p, "SD01", "delivered", takes=[take, {**take, "n": 2, "file": "clips/SD01/take-2.mp4"}])
    write(p / "edit/edl.json", {"s001": {"segs": [{"t0": 0, "clip": "SD01-t2", "in": 0}]}}, 60)
    st = stages(p)
    assert not st["scan"]["done"] and "the edit changed after the scan sheets were made (new: SD01-t2" in \
        st["scan"]["detail"] and st["scan"]["cmd"].endswith("review scan-sheets")
    _sheets(p)
    st = stages(p)
    assert "not in the recorded scan: SD01-t2" in st["scan"]["detail"] and st["scan"]["cmd"].endswith(
        "review record render/scan/findings.json")


def test_scan_verdict_follows_the_review_module_through_remake_and_cut(capsys, monkeypatch):
    """Interop: scan.json written by slop.review.scan.record(); core agrees with `review status` in both triage
    paths (re-make the take = a new take name; cut it from the edit), with and without the review module."""
    from slop.review.scan import status as review_status
    p = new_project(capsys, "scan3")
    for cid, n in (("c01", 2), ("c02", 1)):
        _clip(p, cid, "delivered", takes=[{"n": k, "status": "delivered", "file": f"clips/{cid}/take-{k}.mp4"}
                                          for k in range(1, n + 1)])
        for k in range(1, n + 1):
            write(p / f"clips/{cid}/take-{k}.mp4", "x", 50)
    edl = {"s001": {"segs": [{"t0": 0, "clip": "c01-t1", "in": 0}]}, "s002": {"segs": [{"t0": 2, "clip": "c02-t1"}]}}
    write(p / "edit/edl.json", edl, 60)
    _sheets(p)
    _record(p, [{"clip": "c01-t1", "time": 0.5, "severity": "block", "kind": "hands", "what": "six fingers"},
                {"clip": "c02-t1", "time": 0.5, "severity": "block", "kind": "text", "what": "garbled sign"}],
            ["c01-t1", "c02-t1"], 100)
    assert "2 open block" in stages(p)["scan"]["detail"] and not review_status(p)["release_ok"]

    # path 1: re-make c01 (take 2), the edit plays c01-t2; path 2: cut c02 from the edit
    edl = {"s001": {"segs": [{"t0": 0, "clip": "c01-t2", "in": 0}]}, "s002": {"plate": "p1"}}
    write(p / "edit/edl.json", edl, 60)
    st = stages(p)["scan"]
    assert not st["done"] and st["cmd"].endswith("review scan-sheets") and "no longer played: c01-t1, c02-t1" in \
        st["detail"]
    _sheets(p)
    st = stages(p)["scan"]
    assert not st["done"] and "not in the recorded scan: c01-t2" in st["detail"] and "open block" not in st["detail"]
    _record(p, [], ["c01-t2"], 110)
    rs = review_status(p)
    assert rs["release_ok"] is True and rs["stale"] == 2  # the old blocks are stale, not open
    st = stages(p)["scan"]
    assert st["done"] and "0 open blocks" in st["detail"]
    monkeypatch.setattr(core_cli, "_review_scan", lambda: None)  # same verdict without the review module
    assert stages(p)["scan"]["done"]
    write(p / "edit/edl.json", {**edl, "s003": {"segs": [{"t0": 4, "clip": "c02-t1"}]}}, 60)
    _sheets(p)  # c02-t1 is back in the edit: its old block counts again
    st = stages(p)["scan"]
    assert not st["done"] and "1 open block finding(s): c02-t1 @0.5: garbled sign" in st["detail"]
    assert st["cmd"].endswith("review status")


def test_scan_remade_file_and_broken_record(capsys):
    p = new_project(capsys, "scan2")
    _clip(p, "c01", "delivered", takes=[{"n": 1, "status": "delivered", "file": "clips/c01/take-1.mp4"}])
    write(p / "clips/c01/take-1.mp4", "x", 50)
    write(p / "edit/edl.json", {"s001": {"segs": [{"t0": 0, "clip": "c01-t1", "in": 0}]}}, 60)
    _sheets(p)
    _record(p, [], ["c01-t1"], 100)
    assert stages(p)["scan"]["done"]
    write(p / "clips/c01/take-1.mp4", "y", 120)  # the take file was re-made after the scan
    st = stages(p)["scan"]
    assert "re-made after the last scan: c01-t1" in st["detail"] and st["cmd"].endswith("review scan-sheets")
    write(p / core_cli.SCAN_FILE, "{broken", 130)
    st = stages(p)["scan"]
    assert "not valid JSON" in st["detail"] and "scan.broken.json" in st["do"] and not st["auto"]


# ---------------------------------------------------------------- sections hint
def test_sections_hint(capsys):
    p = new_project(capsys, "secs")
    beats = {"duration": 60, "sections": [
        {"name": "intro", "t0": 0, "t1": 15.2, "source": "lyrics-tag"},
        {"name": "chorus1", "t0": 15.2, "t1": 60, "source": "heuristic", "unconfirmed": True}]}
    write(p / "analysis/beats.json", beats, 20)
    rc, st = run(capsys, "-p", "secs", "status")
    h = st["hints"][0]
    assert h["kind"] == "sections" and h["guessed"] == 1 and h["total"] == 2
    assert "chorus1? 15-60 s" in h["text"] and "project.json audio.sections" in h["text"]
    assert "hint: sections unconfirmed" in st["text"]
    tree = {"song": {"sections": {}, "ingest": {}}}
    h = core_cli.sections_hint(p, tree)  # the audio module's `song sections --set` is installed
    assert h["cmd"] == "slop --project secs song sections --set intro@0,chorus1@15.2"
    assert "confirm them as they are" in h["text"] and h["show"].endswith("song sections")
    for s in beats["sections"]:
        s["source"], s["unconfirmed"] = "set", False
    write(p / "analysis/beats.json", beats, 20)
    assert core_cli.sections_hint(p, tree) is None
    beats["sections_from"] = "heuristic"
    for s in beats["sections"]:
        s.pop("source")
    write(p / "analysis/beats.json", beats, 20)
    assert core_cli.sections_hint(p, None)["guessed"] == 2  # the file-level marker


def test_sections_hint_shows_on_a_done_analysis(capsys):
    p = new_project(capsys, "secs2")
    write(p / "lyrics/lyrics.txt", "hello there\n", 10)
    write(p / "analysis/beats.json", {"sections": [{"name": "verse1", "t0": 0, "t1": 9, "source": "heuristic"}]}, 20)
    write(p / "analysis/hits.json", {}, 20)
    write(p / "analysis/words.json", {"words": [], "lines": [{"text": "hello there"}]}, 20)
    assert "sections unconfirmed" in stages(p)["analysis"]["detail"] and stages(p)["analysis"]["done"]


# ---------------------------------------------------------------- prompts gate without a plate book
def test_clip_only_prompt_approval_without_a_plate_book(capsys):
    p = new_project(capsys, "noplate", "--tier", "studio")
    rc, out = run(capsys, "-p", "noplate", "gate", "prompts", "--approve")
    assert rc == 1 and "nothing for the owner to read" in out["error"] and "plates/prompts.md" in out["error"]
    _clip(p, "SD01", "draft")
    st = stages(p)
    assert not st["gate:prompts"]["done"] and "not locked yet: SD01" in st["gate:prompts"]["detail"]
    _clip(p, "SD01", "locked")
    rc, out = run(capsys, "-p", "noplate", "gate", "prompts", "--approve", "--note", "owner: go")
    assert rc == 0 and out["standing"] is True and "clips/SD01.json" in out["covers"]
    assert out["covers"]["plates/prompts.md"] is None
    proj = json.loads((p / "project.json").read_text())
    assert proj["gates"]["prompts_approved"] is True
    assert core_cli.clip_prompt_approved(proj, json.loads((p / "clips/SD01.json").read_text()))
    assert "(1 clip prompts; no plate book)" in (p / "DECISIONS.md").read_text()
    st = stages(p)
    assert st["gate:prompts"]["done"] and "no plate book" in st["gate:prompts"]["detail"]
    write(p / "plates/prompts.md", "# book\n", 70)  # a book written later: the owner has not read it
    st = stages(p)
    assert not st["gate:prompts"]["done"] and "was written after the approval" in st["gate:prompts"]["detail"]


def test_plates_from_the_owner_need_no_book(capsys):
    p = new_project(capsys, "ownplates")
    write(p / "plates/picks.json", {"p01": {"file": "plates/cands/p01/1.jpg"}}, 51)
    st = stages(p)
    assert st["prompts"]["done"] and "made without a book" in st["prompts"]["detail"]
    assert st["gate:prompts"]["done"] and "nothing to approve" in st["gate:prompts"]["detail"]


# ---------------------------------------------------------------- render: frames -> encode
def test_render_and_master_point_at_encode_once_frames_are_current(capsys):
    p = new_project(capsys, "frames")
    write(p / "analysis/beats.json", {"duration": 0.5}, 20)  # 12 frames at 24 fps
    for n in ("beats", "lyrics", "shots", "edl", "plates"):
        write(p / f"engine/assets/{n}.js", "x", 70)
    st = stages(p)
    assert st["render"]["cmd"].endswith("render frames") and st["render"]["auto"]
    assert st["master"]["cmd"].endswith("render frames")
    for i in range(11):
        write(p / f"render/frames/f{i:05d}.jpg", "j", 80)
    assert stages(p)["render"]["cmd"].endswith("render frames")  # 11 of 12
    write(p / "render/frames/f00011.jpg", "j", 80)
    st = stages(p)
    assert st["render"]["cmd"].endswith("render encode --review") and "frames are rendered" in st["render"]["detail"]
    assert st["master"]["cmd"].endswith("render encode")
    write(p / "engine/assets/shots.js", "y", 90)  # the engine data changed after the frames
    assert stages(p)["render"]["cmd"].endswith("render frames")


def test_song_stage_auto_ingests_a_single_upload(capsys):
    p = new_project(capsys, "upl")
    (p / "BRIEF.md").write_text((p / "BRIEF.md").read_text().replace("\n>\n", "\n> 2026-10-01: make it loud\n", 1))
    write(p / "audio/my song.mp3", "ID3")
    st = stages(p)
    assert st["song"]["auto"] and st["song"]["cmd"].endswith(f"song ingest '{p / 'audio' / 'my song.mp3'}'")
    assert "fetch URL --to audio" in st["song"]["do"]
    write(p / "audio/other.wav", "RIFF")
    st = stages(p)
    assert not st["song"]["auto"] and "PATH/TO" in st["song"]["cmd"]


def test_status_marks_long_steps_with_the_job_form(capsys):
    p = new_project(capsys, "longs")
    (p / "BRIEF.md").write_text((p / "BRIEF.md").read_text().replace("\n>\n", "\n> 2026-10-01: make it loud\n", 1))
    write(p / "audio/song.wav", "RIFF", 10)
    write(p / "lyrics/lyrics.txt", "hello there\n", 10)
    rc, st = run(capsys, "-p", "longs", "status")
    nx = st["next"]
    assert nx["stage"] == "analysis" and nx["long"] and nx["auto"]
    # the command a weaker operator runs IS the job form; the plain step stays in step_cmd
    assert nx["cmd"] == nx["job_cmd"] == "slop --project longs job start -- analyze"
    assert nx["step_cmd"] == "slop --project longs analyze"
    lines = st["text"].splitlines()
    i = lines.index(f"next: {nx['do']}")
    # printed first, right under next: (the audio module is not loaded in these tests: "not installed" is right)
    assert lines[i + 1].strip().startswith("slop --project longs job start -- analyze")
    assert "prints the job id and its wait command" in lines[i + 2]
    assert "job wait last" not in st["text"] and "slop --project longs analyze\n" not in st["text"] + "\n"
    s = {x["stage"]: x for x in st["stages"]}
    assert s["analysis"]["job_cmd"] == "slop --project longs job start -- analyze"
    assert core_cli.next_blocker({**nx, "cmd_available": True}) is None  # `next` still knows the plain step


# ---------------------------------------------------------------- slop next
def _fake_stages(monkeypatch, make):
    monkeypatch.setattr(core_cli, "evaluate_stages", lambda pdir, proj: make(pdir))


def test_next_never_runs_gates_manual_or_unknown_steps(capsys, monkeypatch):
    p = new_project(capsys, "nx")
    rc, out = run(capsys, "-p", "nx", "next")
    assert rc == 0 and out["ran"] == [] and out["stopped"] == "manual" and out["next"]["stage"] == "brief"
    assert "needs your work first" in out["text"]
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("gate:board", False, "not approved", "send the sheet",
                                                         core_cli._pcmd(d, "gate board --approve"), auto=True)])
    rc, out = run(capsys, "-p", "nx", "next")
    assert out["stopped"] == "owner-gate" and out["ran"] == [] and "OWNER's decision" in out["text"]
    assert not json.loads((p / "project.json").read_text())["gates"]["board_approved"]
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("clips", False, "1 locked", "submit",
                                                         core_cli._pcmd(d, "decide paid"), auto=True)])
    rc, out = run(capsys, "-p", "nx", "next")  # `decide` is not on the free list
    assert out["stopped"] == "not-free" and out["ran"] == []
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("runs", False, "", "record",
                                                         core_cli._pcmd(d, "runs add ID --kind other"), auto=True)])
    assert run(capsys, "-p", "nx", "next")[1]["stopped"] == "manual"  # a placeholder is never run
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("song", False, "no song", "ingest",
                                                         core_cli._pcmd(d, "song ingest PATH/TO/song.wav"), auto=True)])
    assert run(capsys, "-p", "nx", "next")[1]["stopped"] == "not-installed"  # no audio module in this test


def test_next_runs_free_steps_in_a_row_and_stops_without_progress(capsys, monkeypatch):
    p = new_project(capsys, "nr")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("decide",)})

    def make(d):
        log = (d / "DECISIONS.md").read_text()
        out = []
        for k in (1, 2):
            out.append(core_cli._stage(f"step{k}", f"step-{k}" in log, "", "record", core_cli._pcmd(d, f"decide step-{k}"),
                                       auto=True))
        out.append(core_cli._stage("stuck", False, "", "", core_cli._pcmd(d, "decide stuck"), auto=True))
        return out
    _fake_stages(monkeypatch, make)
    rc, out = run(capsys, "-p", "nr", "next", "--steps", "5")
    assert rc == 0 and [r["stage"] for r in out["ran"]] == ["step1", "step2", "stuck"]
    assert all(r["ok"] for r in out["ran"]) and out["stopped"] == "no-progress"
    log = (p / "DECISIONS.md").read_text()
    assert "step-1" in log and "step-2" in log and log.count("stuck") == 1  # not run twice
    assert "ran (stage step1): slop --project nr decide step-1" in out["text"]
    rc, out = run(capsys, "-p", "nr", "next", "--dry-run")
    assert out["ran"] == [] and "would run: slop --project nr decide stuck" in out["text"]


def test_next_starts_long_steps_as_a_job_and_honours_free_only(capsys, monkeypatch):
    new_project(capsys, "nl")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("job",)})
    monkeypatch.setattr(core_cli, "LONG_STEPS", core_cli.LONG_STEPS | {("job",)})
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("render", False, "", "render",
                                                         core_cli._pcmd(d, "job _sleep 0.3"), auto=True)])
    rc, out = run(capsys, "-p", "nl", "next", "--free-only")
    assert rc == 0 and out["stopped"] == "job-started" and out["ran"][0]["mode"] == "job"
    jid = out["ran"][0]["job"]["id"]
    assert f"job wait {jid}" in out["text"] and out["free_only"] is True
    rc, w = run(capsys, "-p", "nl", "job", "wait", jid, "--max", "15")
    assert w["state"] == "done" and w["result"]["free_only"] is True  # the spend lock reached the step
    monkeypatch.setattr(core_cli, "LONG_STEPS", core_cli.LONG_STEPS - {("job",)})
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("render", False, "", "render",
                                                         core_cli._pcmd(d, "job _sleep 0.2"), auto=True)])
    rc, out = run(capsys, "-p", "nl", "next", "--free-only")  # short now: inline, same lock
    assert out["ran"][0]["mode"] == "inline" and out["ran"][0]["result"]["free_only"] is True
    rc, out = run(capsys, "-p", "nl", "next")
    assert out["ran"][0]["result"]["free_only"] is False


def test_next_waits_for_any_running_job_first(capsys, monkeypatch):
    p = new_project(capsys, "nw")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("decide",)})
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("x", False, "", "", core_cli._pcmd(d, "decide x"), auto=True)])
    rc, j = run(capsys, "-p", "nw", "job", "start", "--", "job", "_sleep", "30")
    rc, out = run(capsys, "-p", "nw", "next")
    assert rc == 0 and out["stopped"] == "job-running" and out["ran"] == []
    assert f"job {j['id']}" in out["text"] and "wait for it first" in out["text"]
    assert "- x" not in (p / "DECISIONS.md").read_text().splitlines()[-1]
    run(capsys, "-p", "nw", "job", "stop", j["id"], "--grace", "3")
    rc, out = run(capsys, "-p", "nw", "next")
    assert out["ran"] and out["ran"][0]["ok"] and out["stopped"] == "steps"


def test_next_reports_a_failed_step(capsys, monkeypatch):
    new_project(capsys, "nf")
    monkeypatch.setattr(core_cli, "FREE_STEPS", core_cli.FREE_STEPS | {("job",)})
    _fake_stages(monkeypatch, lambda d: [core_cli._stage("x", False, "", "", core_cli._pcmd(d, "job _sleep 0 --fail"),
                                                         auto=True)])
    rc, out = run(capsys, "-p", "nf", "next")
    assert rc == 1 and out["ok"] is False and out["stopped"] == "failed" and "failing on purpose" in out["error"]


def test_next_ingests_the_uploaded_song_for_real(capsys, monkeypatch, tmp_path):
    try:
        importlib.import_module("slop.audio.cli")
        import soundfile  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("the audio module (or soundfile) is not importable here")
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg missing")
    mods = CORE_MODULES + ["slop.audio.cli"]
    monkeypatch.setattr(cli, "MODULES", mods)
    monkeypatch.setenv("SLOP_MODULES", ",".join(mods))
    p = new_project(capsys, "realsong")
    (p / "BRIEF.md").write_text((p / "BRIEF.md").read_text().replace("\n>\n", "\n> 2026-10-01: make it loud\n", 1))
    import wave
    with wave.open(str(p / "audio" / "upload.wav"), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x01\x00\xff\xff" * 48000 * 5)  # ingest refuses a 1 s "song"
    rc, out = run(capsys, "-p", "realsong", "next")
    assert rc == 0 and out["ran"][0]["stage"] == "song" and out["ran"][0]["ok"], out
    assert (p / "audio/song.wav").is_file() and out["next"]["stage"] == "lyrics"
    assert out["stopped"] == "steps"


def test_next_blocker_units():
    nb = core_cli.next_blocker
    assert nb(None) == "done"
    base = {"stage": "analysis", "cmd": "slop --project x analyze", "cmd_available": True, "auto": True}
    assert nb(base) is None
    assert nb({**base, "auto": False}) == "manual"
    assert nb({**base, "cmd_available": False}) == "not-installed"
    assert nb({**base, "running_job": "analyze-abcd"}) == "job-running"
    assert nb({**base, "stage": "gate:v1", "cmd": "slop --project x gate v1 --approve"}) == "owner-gate"
    assert nb({**base, "cmd": "slop --project x lead --canon TEXT"}) == "manual"
    assert nb({**base, "cmd": "slop --project x clip lock ID"}) == "manual"
    assert core_cli.is_long("slop --project x render frames --workers 4") and not core_cli.is_long("slop -p x edit edl")
    assert core_cli.cmd_words("slop --project 'my dir' --json render frames") == ["render", "frames"]
    assert core_cli.job_cmd(Path("/tmp/x"), "slop --project x render encode --review").endswith(
        "job start -- render encode --review")
