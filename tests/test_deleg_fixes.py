"""Tests for the deleg fixer pass on runner/deleg.mjs: gates on job.json fields (the approval card shows only the command
line), chapter wiring (`wire`: stubs + engine/ch/_index.js, locked merge, --check), chapter jobs wired before the engine
starts and collecting only their own files, the toolkit runtime check ("requires", doctor --render), STATUS on every
run/wait exit, `new --force` / re-sent job files starting a clean run, job files copied to the home folder, banned words
from the project contract, `unpack` refusing to overwrite a running job's project, one "render" job at a time, and
`preflight claude --workflow`. Driven through runner/fake-engine.mjs (no model call). Needs `node` (skipped otherwise)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from test_deleg_runner import (FAKE, NODE, ROOT, RUNNER, calls, cleanup, deleg, env, make_job, out, read,  # noqa: F401 (cleanup is a fixture)
                               status, wait_state)

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def make_project(tmp_path: Path, name: str = "song", **pj) -> Path:
    proj = tmp_path / name
    (proj / "analysis").mkdir(parents=True, exist_ok=True)
    (proj / "project.json").write_text(json.dumps({"name": name, "title": "T", **pj}), encoding="utf-8")
    (proj / "analysis" / "beats.json").write_text(json.dumps({"duration": 60, "beats": [0, 0.5, 1, 1.5], "downbeats": [0],
                                                               "tempo": [{"t": 0, "bpm": 120}], "sections": []}), encoding="utf-8")
    return proj


def fake_bin(scenario: str = "ok") -> str:
    return json.dumps(["node", str(FAKE), "--as", "claude", "--scenario", scenario])


def last_status(r) -> dict:
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith("STATUS "), r.stdout[-500:]
    return json.loads(last[len("STATUS "):])


def strip_engine_bin(j: Path) -> None:
    job = json.loads((j / "job.json").read_text(encoding="utf-8"))
    job.pop("engine_bin")
    (j / "job.json").write_text(json.dumps(job), encoding="utf-8")


# ------------------------------------------------------------------------------------------------------------- gates
def test_gates_refuse_elevated_job_fields_without_their_flag(tmp_path, cleanup):
    """job.json comes from the bot's computer; the approval card shows only the command line"""
    j = make_job(tmp_path, "rawgate")
    r = out(deleg("start", j, "--no-auto-raw"))
    assert r["ok"] is False and "--allow-raw" in r["fix"] and "engine_bin" in r["error"]
    assert status(j) == {} and not calls(j), "nothing may start"
    spend = make_job(tmp_path, "spend", allow_spend=True)
    cleanup.append(spend)
    r = out(deleg("start", spend))   # --allow-raw only
    assert r["ok"] is False and "--allow-spend" in r["fix"] and "Higgsfield" in r["error"]
    out(deleg("start", spend, "--allow-spend"))
    st = wait_state(spend)
    assert st["state"] == "done" and "--disallowedTools" not in st["argv"]
    first = read(spend / "progress.log").splitlines()[0]
    assert "gates:" in first and "spend ON" in first and "raw ON" in first and "api-billing off" in first
    assert "Deliverables go exactly where the brief says" in read(spend / "prompt-1.md")
    assert "Deliverables go where the brief says" in st["argv"][st["argv"].index("-p") + 1]
    assert "--allow-api-billing" in out(deleg("start", make_job(tmp_path, "bill", allow_api_billing=True)))["fix"]
    assert "--pass-env OPENROUTER_API_KEY" in out(deleg("start", make_job(tmp_path, "sec", pass_env=["OPENROUTER_API_KEY"])))["fix"]
    for i, extra in enumerate(({"permission_mode": "bypassPermissions"}, {"env": {"X": "1"}}, {"extra_allowed_tools": ["mcp__claude_ai_Gmail__send"]},
                               {"sandbox": "danger-full-access"}, {"slop_cmd": "evil"}, {"add_dirs": [str(tmp_path)]}, {"cwd": str(tmp_path.parent)})):
        k = make_job(tmp_path, f"raw{i}", **extra)
        strip_engine_bin(k)   # only the field under test trips the gate (the env override keeps any real engine away)
        r = out(deleg("start", k, "--no-auto-raw", DELEG_CLAUDE_BIN=fake_bin()))
        assert r["ok"] is False and "--allow-raw" in r["fix"], extra
    plain = make_job(tmp_path, "plain")
    strip_engine_bin(plain)
    cleanup.append(plain)
    assert out(deleg("start", plain, "--no-auto-raw", DELEG_CLAUDE_BIN=fake_bin()))["ok"], "a plain job needs no flag"
    assert wait_state(plain)["state"] == "done"


def test_run_always_ends_with_a_status_line(tmp_path):
    jobs = tmp_path / "proj" / "jobs"
    jobs.mkdir(parents=True)
    (tmp_path / "proj" / "project.json").write_text('{"name": "proj"}', encoding="utf-8")
    jf = jobs / "20261001-beef-x.job.json"
    jf.write_text(json.dumps({"id": "20261001-beef-x", "engine": "claude", "brief": "x", "allow_spend": True,
                              "engine_bin": ["node", str(FAKE), "--as", "claude"]}), encoding="utf-8")
    r = deleg("run", jf, "--no-auto-raw", timeout=30)
    s = last_status(r)
    assert r.returncode == 1 and s["ok"] is False and "--allow-spend" in s["fix"] and "--allow-raw" in s["fix"]
    assert not calls(jobs / "20261001-beef-x")
    gone = deleg("run", tmp_path / "nope", timeout=30)
    assert last_status(gone)["ok"] is False and gone.returncode == 1
    w = deleg("wait", tmp_path / "nope", 1, timeout=30)
    assert last_status(w)["ok"] is False


# ------------------------------------------------------------------------------------------------- new / adopting jobs
def test_new_reports_gates_and_the_user_side_command(tmp_path):
    proj = make_project(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"allow_spend": True, "pass_env": ["ARENA_TOKEN"]}), encoding="utf-8")
    r = out(deleg("new", "auto", "--project", proj, "--brief", "storyboard-panel", "--spec", spec))
    j = Path(r["job_dir"])
    assert r["gates_needed"] == ["--allow-spend", "--pass-env ARENA_TOKEN"] and "ask the user" in r["gates_note"]
    assert r["user_run_command"] == f'node "<TK>/runner/deleg.mjs" run "<PROJ>/jobs/{j.name}.job.json" --allow-spend --pass-env ARENA_TOKEN'
    assert r["copy_from_box"].endswith(f"{j.name}/job.json") and r["next"].startswith("CopyFromBox ") and "<PROJ>/jobs/" in r["next"]
    assert json.loads(read(j / "job.json"))["project_name"] == "song"


def test_new_force_archives_the_previous_run(tmp_path, cleanup):
    proj = make_project(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"engine_bin": ["node", str(FAKE), "--as", "claude", "--scenario", "workflow"], "requires": []}), encoding="utf-8")
    r = out(deleg("new", "auto", "--project", proj, "--brief", "storyboard-panel", "--spec", spec))
    j = Path(r["job_dir"])
    cleanup.append(j)
    deleg("start", j, FAKE_GAP_MS=50)
    assert wait_state(j)["state"] == "done"
    r2 = out(deleg("new", j, "--project", proj, "--brief", "storyboard-panel", "--spec", spec, "--set", "OWNER_QUOTES=new notes", "--force"))
    assert r2["ok"] and r2["archived_previous_run"].endswith("history/1")
    assert not (j / "status.json").exists() and (j / "history" / "1" / "status.json").exists() and (j / "history" / "1" / "outbox").is_dir()
    run = deleg("run", j, timeout=60, FAKE_GAP_MS=50)
    assert run.returncode == 0 and "not starting it again" not in run.stdout and status(j)["attempt"] == 1
    assert "new notes" in read(j / "BRIEF.md")


def test_a_new_job_file_with_the_same_id_is_a_new_run(tmp_path, cleanup):
    jobs = tmp_path / "proj" / "jobs"
    jobs.mkdir(parents=True)
    (tmp_path / "proj" / "project.json").write_text('{"name": "proj"}', encoding="utf-8")
    jf = jobs / "20261001-abcd-t.job.json"
    base = {"id": "20261001-abcd-t", "engine": "claude", "brief": "# one\n", "engine_bin": ["node", str(FAKE), "--as", "claude"]}
    jf.write_text(json.dumps(base), encoding="utf-8")
    j = jobs / "20261001-abcd-t"
    cleanup.append(j)
    assert deleg("run", jf, timeout=60).returncode == 0
    jf.write_text(json.dumps(dict(base, brief="# two\n")), encoding="utf-8")
    r = deleg("run", jf, timeout=60)
    assert r.returncode == 0 and "not starting it again" not in r.stdout, r.stdout
    assert read(j / "BRIEF.md").startswith("# two") and (j / "history" / "1" / "status.json").exists()


def test_a_job_file_copied_to_home_finds_its_project(tmp_path, cleanup):
    projects = tmp_path / "projects"
    make_project(projects)
    home = tmp_path / "home"
    home.mkdir()
    jf = home / "20261001-0001-t.job.json"
    jf.write_text(json.dumps({"id": "20261001-0001-t", "engine": "claude", "brief": "# b\n", "project_name": "song", "project_dir": "../..",
                              "engine_bin": ["node", str(FAKE), "--as", "claude"]}), encoding="utf-8")
    j = projects / "song" / "jobs" / "20261001-0001-t"
    cleanup.append(j)
    r = deleg("run", jf, timeout=60, SLOP_PROJECTS=projects)
    assert r.returncode == 0, r.stdout
    assert Path(last_status(r)["job"]).resolve() == j.resolve() and calls(j)[0]["slop_project"]


def test_new_needs_a_real_project(tmp_path):
    (tmp_path / "notaproject").mkdir()
    r = out(deleg("new", "auto", "--project", tmp_path / "notaproject", "--brief", "storyboard-panel"))
    assert r["ok"] is False and "project.json" in r["error"] and "not a slop project" in r["fix"]


def test_new_fills_banned_words_from_a_slop_project(tmp_path):
    """the project contract keeps banned words in "banned" / board.banned (slop board audit) and lyrics.banned (lint)"""
    root = tmp_path / "projects"
    r = subprocess.run([sys.executable, "-m", "slop", "--json", "new", "my-song", "--root", str(root)], cwd=ROOT, capture_output=True,
                       text=True, timeout=120, env=env(PYTHONPATH=str(ROOT)), encoding="utf-8")
    if r.returncode != 0:
        pytest.skip(f"slop new does not run in this interpreter: {(r.stdout + r.stderr)[-300:]}")
    proj = root / "my-song"
    pj = json.loads(read(proj / "project.json"))
    pj.update({"banned": ["catwalkx"], "board": {"banned": ["zebrafoo"]}, "lyrics": {"banned": {"lolcat": "a meme we retired"}}})
    (proj / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    (proj / "analysis").mkdir(exist_ok=True)
    (proj / "analysis" / "beats.json").write_text(json.dumps({"duration": 95.5}), encoding="utf-8")
    sb = out(deleg("new", "auto", "--project", proj, "--brief", "storyboard-panel"))
    job = json.loads(read(Path(sb["job_dir"]) / "job.json"))
    assert job["workflow_args"]["banned_words"] == ["catwalkx", "zebrafoo", "lolcat"]
    assert "banned words never appear anywhere: catwalkx, zebrafoo, lolcat" in job["brief"]
    rl = out(deleg("new", "auto", "--project", proj, "--brief", "research-lyrics", "--set", "TODAY=2026-10-01", "--set", "CONCEPT=c"))
    rj = json.loads(read(Path(rl["job_dir"]) / "job.json"))
    assert rj["workflow_args"]["banned_words"] == ["catwalkx", "zebrafoo", "lolcat"] and "catwalkx" in rj["brief"]


# ----------------------------------------------------------------------------------------------------- chapter wiring
def test_wire_creates_stubs_merges_the_index_and_checks(tmp_path):
    proj = make_project(tmp_path)
    ch = proj / "engine" / "ch"
    idx = ch / "_index.js"
    r1 = out(deleg("wire", proj, "--chapters", json.dumps([{"id": "C2", "file": "02_b.js", "t0": 20, "t1": 40, "shots": ["s010", "s011"]}])))
    assert r1["ok"] and r1["mode"] == "created" and r1["created"] == ["02_b.js"]
    jobfile = tmp_path / "job.json"
    jobfile.write_text(json.dumps({"workflow_args": {"chapters": [{"id": "C1", "file": "01_a.js", "t0": 0, "t1": 20, "shots": ["s001"]}]}}), encoding="utf-8")
    r2 = out(deleg("wire", proj, "--chapters", jobfile))
    assert r2["mode"] == "merged" and r2["added"] == ["01_a.js"]
    text = read(idx)
    assert text.index('"01_a.js"') < text.index('"02_b.js"'), "time order"
    assert "document.write" in text and read(ch / "01_a.js").startswith("// slop:chapter-stub")
    again = out(deleg("wire", proj, "--chapters", jobfile))
    assert again["added"] == [] and again["created"] == [] and read(idx) == text, "idempotent"
    chk = out(deleg("wire", proj, "--check", "--file", "01_a.js", "--shots", "s001"))
    assert chk["ok"] is False and chk["text"].startswith("NOT WIRED") and "stub" in chk["text"]
    (ch / "01_a.js").write_text("(() => {\n  const ID = 's001';\n  scene(ID, 0, 20, async (b, o, t) => ENGINE.look());\n})();\n", encoding="utf-8")
    chk = out(deleg("wire", proj, "--check", "--file", "01_a.js", "--shots", "s001,s002"))
    assert chk["ok"] and chk["text"].startswith("WIRED 01_a 01_a.js") and "names 1/2 shots" in chk["text"] and "s002" in chk["text"]
    assert out(deleg("wire", proj, "--check", "--chapters", jobfile))["ok"], "a job.json works for --check too"
    (ch / "01_a.js").write_text("scene('s001', 0, 20, async () => {\n", encoding="utf-8")
    assert "does not parse" in out(deleg("wire", proj, "--check", "--file", "01_a.js"))["text"]
    (ch / "03_c.js").write_text("scene('s020', 40, 50, async () => ENGINE.look());\n", encoding="utf-8")
    assert "does not list it" in out(deleg("wire", proj, "--check", "--file", "03_c.js"))["text"]
    mine = "// a chapter someone already wrote\nscene('s030', 50, 60, async () => ENGINE.look());\n"
    (ch / "04_d.js").write_text(mine, encoding="utf-8")
    out(deleg("wire", proj, "--chapters", json.dumps([{"id": "C4", "file": "04_d.js", "t0": 50, "t1": 60}])))
    assert read(ch / "04_d.js") == mine, "wire never overwrites a chapter file"
    assert out(deleg("wire", proj, "--chapters", json.dumps([{"id": "C9", "file": "../x.js"}])))["ok"] is False
    assert out(deleg("wire", proj, "--chapters", json.dumps([{"id": "C9", "file": "_index.js"}])))["ok"] is False
    # a hand-written _index.js is kept; missing files are appended
    hand = make_project(tmp_path, "hand")
    (hand / "engine" / "ch").mkdir(parents=True)
    (hand / "engine" / "ch" / "_index.js").write_text("['01_x.js'].forEach(f => document.write(`<script src=\"ch/${f}\"><\\/script>`));\n", encoding="utf-8")
    r = out(deleg("wire", hand, "--chapters", json.dumps([{"id": "C1", "file": "01_x.js"}, {"id": "C9", "file": "09_y.js"}])))
    assert r["mode"] == "appended" and r["added"] == ["09_y.js"] and read(hand / "engine" / "ch" / "_index.js").startswith("['01_x.js']")
    # a damaged generated index is refused with the fix
    idx.write_text("// slop:chapters-index v1\nwindow.SLOP_CHAPTER_FILES = /*BEGIN*/[oops/*END*/;\n", encoding="utf-8")
    bad = out(deleg("wire", proj, "--chapters", jobfile))
    assert bad["ok"] is False and "damaged" in bad["error"] and "Delete" in bad["fix"]
    assert out(deleg("wire", tmp_path / "nowhere", "--chapters", jobfile))["ok"] is False


def test_wire_is_safe_for_jobs_side_by_side(tmp_path):
    proj = make_project(tmp_path)
    procs = [subprocess.Popen([NODE, str(RUNNER), "wire", str(proj), "--chapters", json.dumps([{"id": f"C{i}", "file": f"{i:02d}_c.js", "t0": i, "t1": i + 1}])],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
    for p in procs:
        p.communicate(timeout=60)
        assert p.returncode == 0
    m = re.search(r"/\*BEGIN\*/(.*?)/\*END\*/", read(proj / "engine" / "ch" / "_index.js"), re.S)
    assert [e["file"] for e in json.loads(m.group(1))] == [f"{i:02d}_c.js" for i in range(8)], "no entry lost"


def test_a_wired_chapter_is_loaded_by_the_engine_page(tmp_path):
    """the integration the chapters workflow depends on: a file listed in engine/ch/_index.js runs in the page; an
    unlisted file does not (its code would never render)"""
    pytest.importorskip("playwright")
    proj = make_project(tmp_path, "smoke", size=[320, 180], fps=24)
    out(deleg("wire", proj, "--chapters", json.dumps([{"id": "C1", "file": "01_a.js", "t0": 0, "t1": 2}])))
    ch = proj / "engine" / "ch"
    (ch / "01_a.js").write_text("throw new Error('chapter C1 was loaded');\n", encoding="utf-8")
    (ch / "02_b.js").write_text("throw new Error('chapter C2 was loaded');\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "slop", "--json", "--project", str(proj), "render", "info", "--size", "320x180"], cwd=ROOT,
                       capture_output=True, text=True, timeout=180, env=env(PYTHONPATH=str(ROOT)), encoding="utf-8")
    info = json.loads(r.stdout.strip().splitlines()[-1])
    if "browser" in str(info.get("error", "")):
        pytest.skip(f"no browser here: {info['error'][:200]}")
    warnings = " ".join(info.get("warnings") or [])
    assert "chapter C1 was loaded" in warnings, info
    assert "chapter C2 was loaded" not in warnings


def test_a_chapter_job_is_wired_before_the_engine_starts(tmp_path, cleanup):
    proj = make_project(tmp_path)
    (proj / "engine" / "ch").mkdir(parents=True)
    (proj / "engine" / "ch" / "07_other.js").write_text("// another job's chapter\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"engine_bin": ["node", str(FAKE), "--as", "claude", "--scenario", "workflow"], "requires": []}), encoding="utf-8")
    chs = [{"id": "C1", "file": "01_a.js", "name": "A", "t0": 0, "t1": 12.5, "shots": ["s001"]}]
    r = out(deleg("new", "auto", "--project", proj, "--brief", "chapter-motion", "--set", f"CHAPTERS={json.dumps(chs)}", "--spec", spec))
    j = Path(r["job_dir"])
    cleanup.append(j)
    assert r["collect"] == ["engine/ch/01_a.js"] and r["gates_needed"] == ["--allow-raw"]
    deleg("start", j, FAKE_GAP_MS=50)
    st = wait_state(j)
    assert st["state"] == "done", st
    assert '"01_a.js"' in read(proj / "engine" / "ch" / "_index.js") and json.loads(read(j / "wf" / "args.json"))["wired"] is True
    files = j / "outbox" / "files" / "engine" / "ch"
    assert (files / "01_a.js").exists() and not (files / "07_other.js").exists(), "a chapter job collects only its own files"
    assert "wired 1 chapter file" in read(j / "progress.log")
    assert not list((proj / "jobs").glob(".queue-*.lock")), "the render group lock is released at the end"


# ---------------------------------------------------------------------------------------------- toolkit runtime checks
def test_requires_fails_fast_when_the_toolkit_does_not_run(tmp_path, cleanup):
    j = make_job(tmp_path, "needs", requires=["slop"], slop_cmd="no-such-slop-cli-xyz")
    cleanup.append(j)
    deleg("start", j)
    st = wait_state(j, timeout=90)
    assert st["state"] == "failed" and "toolkit CLI does not run" in st["error"] and ("setup.sh" in st["error"] or "uv venv" in st["error"])
    assert not calls(j), "the engine never started"
    good = make_job(tmp_path, "needs-ok", requires=["slop"], slop_cmd=f'"{sys.executable}" -m slop')
    cleanup.append(good)
    deleg("start", good, PYTHONPATH=str(ROOT))
    st = wait_state(good, timeout=90)
    if st["state"] == "failed" and "toolkit CLI does not run" in (st.get("error") or ""):
        pytest.skip(f"the toolkit does not import in this interpreter: {st['error'][:200]}")
    assert st["state"] == "done" and st["toolkit"]["slop_ok"] is True


def test_doctor_checks_the_toolkit_runtime(tmp_path):
    bad = out(deleg("doctor", timeout=120, SLOP_CMD="no-such-slop-cli-xyz"))
    assert bad["slop_ok"] is False and bad["ok"] is False and bad["toolkit_error"] and bad["toolkit_fix"]
    pytest.importorskip("playwright")
    d = out(deleg("doctor", "--render", timeout=240, SLOP_CMD=f'"{sys.executable}" -m slop', PYTHONPATH=str(ROOT)))
    if d.get("toolkit_error") and "browser" in d["toolkit_error"]:
        pytest.skip(f"no browser here: {d['toolkit_error'][:200]}")
    assert d["slop_ok"] is True and d["render_ok"] is True, d.get("toolkit_error")


# ------------------------------------------------------------------------------------------------ transfer and queue
def test_unpack_refuses_while_a_job_of_that_project_runs(tmp_path):
    box = tmp_path / "box"
    make_project(box)
    archive = tmp_path / "song.tgz"
    with tarfile.open(archive, "w:gz") as t:
        t.add(box / "song", arcname="song")
    dest = tmp_path / "projects"
    j1 = dest / "song" / "jobs" / "j1"
    j1.mkdir(parents=True)
    (dest / "song" / "project.json").write_text("{}", encoding="utf-8")
    (j1 / "job.json").write_text('{"engine": "claude"}', encoding="utf-8")
    (j1 / "status.json").write_text(json.dumps({"state": "running", "supervisor_pid": os.getpid()}), encoding="utf-8")
    r = out(deleg("unpack", archive, dest))
    assert r["ok"] is False and "j1" in r["error"] and "running: 0" in r["fix"]
    (j1 / "status.json").write_text(json.dumps({"state": "done"}), encoding="utf-8")
    r = out(deleg("unpack", archive, dest))
    assert r["ok"] and json.loads(read(dest / "song" / "project.json"))["name"] == "song"


def test_queue_group_runs_one_render_job_at_a_time(tmp_path, cleanup):
    a = make_job(tmp_path, "ga", scenario="slow", queue_group="render")
    b = make_job(tmp_path, "gb", scenario="slow", queue_group="render")
    c = make_job(tmp_path, "gc", scenario="slow")   # no group: not held back
    cleanup.extend([a, b, c])

    def until(cond, secs, msg=""):
        t0 = time.monotonic()
        while not cond():
            assert time.monotonic() - t0 < secs, msg
            time.sleep(0.2)
    deleg("start", a)
    until(lambda: calls(a), 20)
    deleg("start", b)
    deleg("start", c)
    assert wait_state(b, states=("queued",), timeout=20)["state"] == "queued"
    until(lambda: calls(c), 20, "a job outside the group must not wait")
    assert 'one "render" job at a time' in read(b / "progress.log")
    deleg("stop", a, timeout=40)
    until(lambda: calls(b), 30, read(b / "progress.log"))
    deleg("stop", b, timeout=40)
    deleg("stop", c, timeout=40)


def test_preflight_workflow_proves_subagent_tools(tmp_path):
    r = out(deleg("preflight", "claude", "--workflow", "--dir", tmp_path, timeout=120, DELEG_CLAUDE_BIN=fake_bin("workflow"), FAKE_GAP_MS=50))
    assert r["ok"] and r["subagent_tools_ok"] and r["workflow_ran"] and r["state"] == "done", r
    job = Path(r["job"])
    assert (job / "wf" / "preflight-wf.js").exists() and json.loads(read(job / "wf" / "args.json"))["dir"].endswith("/outbox")
    again = out(deleg("preflight", "claude", "--job", job, timeout=60))
    assert again["subagent_tools_ok"] is True, "--job re-reads a preflight job"
    bad = out(deleg("preflight", "claude", "--workflow", "--dir", tmp_path, timeout=120, DELEG_CLAUDE_BIN=fake_bin("workflow-nobash"), FAKE_GAP_MS=50))
    assert bad["ok"] is False and bad["subagent_tools_ok"] is False and "Bash" in bad["error"] and bad["fix"]
