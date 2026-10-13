"""Tests for runner/deleg.mjs — the delegation runner — driven through runner/fake-engine.mjs (a free stand-in that emits
each engine's real stream format; no model call, no network). Needs `node` on PATH (skipped otherwise)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "runner" / "deleg.mjs"
FAKE = ROOT / "runner" / "fake-engine.mjs"
FIX = ROOT / "tests" / "fixtures" / "deleg"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
WIN = sys.platform == "win32"


def env(**extra):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("FAKE_", "DELEG_"))}
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "META_API_KEY", "OPENROUTER_API_KEY", "CLAUDECODE"):
        e.pop(k, None)
    e.update({k: str(v) for k, v in extra.items()})
    return e


def deleg(*args, timeout=60, **envx):
    """run deleg.mjs; start/run/resume get --allow-raw (the test jobs run the fake engine through engine_bin, a gated
    field) unless the call passes "--no-auto-raw" (the gate tests)"""
    a = [str(x) for x in args]
    if "--no-auto-raw" in a:
        a.remove("--no-auto-raw")
    elif a and a[0] in ("start", "run", "resume"):
        a.append("--allow-raw")
    return subprocess.run([NODE, str(RUNNER), *a], capture_output=True, text=True, timeout=timeout,
                          env=env(**envx), encoding="utf-8")


def out(r):
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    assert lines, f"no output; stderr: {r.stderr}"
    last = lines[-1]
    return json.loads(last[len("STATUS "):] if last.startswith("STATUS ") else last)


def make_job(root: Path, name: str, engine: str = "claude", scenario: str = "ok", **extra) -> Path:
    j = root / "jobs" / name
    j.mkdir(parents=True, exist_ok=True)
    job = {"engine": engine, "kind": "test", "brief": "# Test brief\nDo the thing. Nobody answers questions.\n",
           "engine_bin": ["node", str(FAKE), "--as", engine, "--scenario", scenario], "timeout_s": 120, **extra}
    (j / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    return j


def status(j: Path) -> dict:
    try:
        return json.loads((j / "status.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def wait_state(j: Path, states=("done", "failed", "stopped"), timeout=40.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        st = status(j)
        if st.get("state") in states:
            return st
        time.sleep(0.2)
    raise AssertionError(f"timeout waiting for {states}; status={status(j)}; progress={read(j / 'progress.log')}")


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def calls(j: Path) -> list[dict]:
    return [json.loads(l) for l in read(j / "fake-calls.jsonl").splitlines() if l.strip()]


def pid_alive(pid) -> bool:
    if not pid:
        return False
    if WIN:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie is dead for our purposes
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


@pytest.fixture
def cleanup():
    jobs: list[Path] = []
    yield jobs
    for j in jobs:
        if status(j).get("state") in ("running", "queued", "starting"):
            deleg("stop", j, "--force", timeout=30)


# --------------------------------------------------------------------------------------------- offline stream parsing
def test_parse_claude_workflow_stream_keeps_the_second_result():
    r = out(deleg("_parse", "claude", FIX / "claude_workflow.jsonl"))
    st = r["status"]
    assert len(st["results"]) == 2, "both result events must be recorded"
    assert st["results"][1]["origin"] == "task-notification"
    assert "workflow finished" in st["final"]["text"], "the final text is the LAST result, after the workflow"
    assert st["workflow_runs"] == ["wf_0a1b2c3d-4e5"]
    assert st["tasks"]["wfake01"]["status"] == "completed"
    assert st["has_workflow_tool"] is True and st["session_id"]
    assert any("workflow launched wf_0a1b2c3d-4e5" in p for p in r["progress"])
    assert all(len(p) <= 240 for p in r["progress"])


def test_parse_codex_and_muse_streams():
    c = out(deleg("_parse", "codex", FIX / "codex_resume.jsonl"))
    assert c["status"]["thread_id"] == "00000000-0000-7000-8000-00000000c0de"
    assert c["status"]["final"] == {"subtype": "success", "is_error": False, "text": "DONE"}
    assert c["status"]["tokens"]["input"] == 48771
    assert any(p.startswith("ran ") and p.endswith("-> 0") for p in c["progress"])
    f = out(deleg("_parse", "codex", FIX / "codex_failed.jsonl"))
    assert f["status"]["final"]["is_error"] is True and "usage limit" in f["status"]["final"]["text"]
    m = out(deleg("_parse", "muse", FIX / "muse_ok.jsonl"))
    assert m["status"]["session_id"] == "00000000-0000-7000-8000-0000000003e5"
    assert m["status"]["final"]["subtype"] == "completed" and m["status"]["final"]["text"] == "OK"
    assert any(p.startswith("retry:") for p in m["progress"])


def test_parse_flags_missing_workflow_tool(tmp_path):
    jf = tmp_path / "job.json"
    jf.write_text(json.dumps({"engine": "claude", "workflow": "storyboard"}), encoding="utf-8")
    stream = tmp_path / "s.jsonl"
    stream.write_text(json.dumps({"type": "system", "subtype": "init", "session_id": "s", "tools": ["Read"], "apiKeySource": "none"}) + "\n", encoding="utf-8")
    st = out(deleg("_parse", "claude", stream, jf))["status"]
    assert st["has_workflow_tool"] is False and "workflows_env" in st["_fatal"]


# ------------------------------------------------------------------------------------------------ live (fake engine)
def test_claude_workflow_job_waits_for_process_exit(tmp_path, cleanup):
    j = make_job(tmp_path, "wf", scenario="workflow")
    cleanup.append(j)
    r = out(deleg("start", j, FAKE_GAP_MS=2500))
    assert r["ok"] and r["state"] == "starting" and "wait" in r["next"]
    # after the FIRST result the job must still be running (the workflow's result has not arrived yet)
    t0 = time.monotonic()
    while "(turn)" not in read(j / "progress.log"):
        assert time.monotonic() - t0 < 30, read(j / "progress.log")
        time.sleep(0.1)
    assert status(j)["state"] == "running"
    st = wait_state(j)
    assert st["state"] == "done", st
    for k in ("state", "engine", "started", "last_event", "tokens", "result_text", "error"):
        assert k in st, f"normalised status field {k} missing"
    assert st["engine"] == "claude" and st["error"] is None
    assert "workflow finished" in st["result_text"]
    assert st["workflow_runs"] == ["wf_0a1b2c3d-4e5"]
    assert any("failed" in w for w in st["warnings"]), "a dead workflow agent must surface as a warning"
    argv = st["argv"]
    for a in ("-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "default", "--permission-prompts", "none", "--session-id"):
        assert a in argv
    assert "Workflow" in argv[argv.index("--allowedTools") + 1].split(",")
    assert "mcp__claude_ai_Higgsfield" in argv[argv.index("--disallowedTools") + 1]
    assert (j / "runs" / "wfake01.output.json").exists()
    assert (j / "outbox.tgz").exists() and st["outbox"]["archive"] == "outbox.tgz"
    assert "wf_0a1b2c3d-4e5" in read(j / "RUNS.md")
    assert (j / "raw-1.jsonl").stat().st_size > 0 and (j / "BRIEF.md").exists()
    assert json.loads(read(j / "outbox" / "_status.json"))["state"] == "done"


def test_api_keys_and_toolkit_secrets_are_stripped(tmp_path, cleanup):
    keys = dict(ANTHROPIC_API_KEY="a", OPENAI_API_KEY="b", CODEX_API_KEY="c", META_API_KEY="d", OPENROUTER_API_KEY="e", CLAUDECODE="1")
    j = make_job(tmp_path, "strip")
    cleanup.append(j)
    deleg("start", j, **keys)
    st = wait_state(j)
    assert st["state"] == "done"
    assert calls(j)[0]["env_present"] == []
    assert set(st["env_stripped"]) >= {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "META_API_KEY", "OPENROUTER_API_KEY"}
    # --allow-api-billing keeps the engine keys; the toolkit secret still needs pass_env AND --pass-env on the command line
    j2 = make_job(tmp_path, "billing", pass_env=["OPENROUTER_API_KEY"])
    cleanup.append(j2)
    deleg("start", j2, "--allow-api-billing", "--pass-env", "OPENROUTER_API_KEY", **keys)
    wait_state(j2)
    seen = set(calls(j2)[0]["env_present"])
    assert {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"} <= seen and "CLAUDECODE" not in seen


def test_codex_stdin_closed_then_resume_in_same_thread(tmp_path, cleanup):
    j = make_job(tmp_path, "codex", engine="codex")
    cleanup.append(j)
    deleg("start", j)
    st = wait_state(j, timeout=30)  # the fake hangs forever if the runner leaves stdin open
    assert st["state"] == "done" and st["result_text"] == "DONE"
    c = calls(j)[0]
    assert c["stdin_len"] > 0 and "Nobody answers" in c["stdin_head"]
    a = c["argv"]
    assert a[:2] == ["exec", "--json"] and a[-1] == "-" and "workspace-write" in a and "-C" in a
    assert 'forced_login_method="chatgpt"' in a
    assert st["thread_id"] == "00000000-0000-7000-8000-00000000c0de"
    r = out(deleg("resume", j))
    assert r["ok"] and r["session"] == st["thread_id"]
    t0 = time.monotonic()
    while (status(j).get("attempt") != 2 or status(j).get("state") not in ("done", "failed")) and time.monotonic() - t0 < 30:
        time.sleep(0.2)
    st2 = status(j)
    assert st2["state"] == "done" and st2["attempt"] == 2 and st2["result_text"] == "DONE (resumed)"
    a2 = calls(j)[1]["argv"]
    assert a2[:2] == ["exec", "resume"] and 'sandbox_mode="workspace-write"' in a2 and a2[-2:] == [st["thread_id"], "-"]
    assert "-s" not in a2 and "-C" not in a2


def test_muse_no_auto_update_and_session_resume(tmp_path, cleanup):
    j = make_job(tmp_path, "muse", engine="muse")
    cleanup.append(j)
    deleg("start", j)
    st = wait_state(j)
    assert st["state"] == "done" and st["result_text"] == "OK"
    c = calls(j)[0]
    assert c["muse_no_auto_update"] == "1"
    a = c["argv"]
    assert a[:2] == ["exec", "--json"] and "--prompt-file" in a and a[a.index("--approval-mode") + 1] == "never"
    assert "--session-id" not in a and c["prompt_len"] > 0
    deleg("resume", j)
    t0 = time.monotonic()
    while (status(j).get("attempt") != 2 or status(j).get("state") not in ("done", "failed")) and time.monotonic() - t0 < 30:
        time.sleep(0.2)
    a2 = calls(j)[1]["argv"]
    assert a2[a2.index("--session-id") + 1] == st["session_id"]
    assert status(j)["result_text"] == "OK again"


def test_claude_resume_uses_resume_flag_and_workflow_prompt(tmp_path, cleanup):
    j = make_job(tmp_path, "cres", scenario="workflow", workflow="storyboard")
    cleanup.append(j)
    deleg("start", j, FAKE_GAP_MS=50)
    st = wait_state(j)
    assert st["state"] == "done" and (j / "wf" / "storyboard.js").exists() and (j / "wf" / "args.json").exists()
    r = out(deleg("resume", j, FAKE_GAP_MS=50))
    text = read(j / r["resume_prompt"])
    assert "resumeFromRunId" in text and "wf_0a1b2c3d-4e5" in text and "storyboard.js" in text
    t0 = time.monotonic()
    while (status(j).get("attempt") != 2 or status(j).get("state") not in ("done", "failed")) and time.monotonic() - t0 < 30:
        time.sleep(0.2)
    a2 = calls(j)[1]["argv"]
    assert a2[a2.index("--resume") + 1] == st["session_id"] and "--session-id" not in a2


@pytest.mark.parametrize("scenario,needle,job_extra", [
    ("noworkflow", "workflows_env", {"workflow": "storyboard"}),
    ("apikey", "API key", {}),
    ("error", "something broke", {}),
])
def test_claude_failures_fail_fast_with_a_fix(tmp_path, cleanup, scenario, needle, job_extra):
    j = make_job(tmp_path, scenario, scenario=scenario, **job_extra)
    cleanup.append(j)
    t0 = time.monotonic()
    deleg("start", j)
    st = wait_state(j, timeout=30)
    assert st["state"] == "failed" and needle in st["error"], st.get("error")
    assert time.monotonic() - t0 < 25
    s = out(deleg("status", j))
    assert s["state"] == "failed" and "resume" in s["next"]


def test_stop_kills_the_engine_process_tree(tmp_path, cleanup):
    j = make_job(tmp_path, "slow", scenario="slow")
    cleanup.append(j)
    deleg("start", j)
    t0 = time.monotonic()
    while not (status(j).get("engine_pid") and status(j).get("events", 0) > 0 and calls(j)):
        assert time.monotonic() - t0 < 20
        time.sleep(0.2)
    st = status(j)
    grand = calls(j)[0]["grandchild_pid"]
    assert pid_alive(st["engine_pid"]) and pid_alive(grand)
    r = out(deleg("stop", j, timeout=40))
    assert r["ok"] and r["state"] == "stopped"
    time.sleep(1.0)
    assert not pid_alive(st["engine_pid"]) and not pid_alive(grand)
    assert status(j)["state"] == "stopped"
    assert out(deleg("stop", j))["note"] == "not running"   # idempotent


def test_timeout_and_usage_guard(tmp_path, cleanup):
    j = make_job(tmp_path, "timeout", scenario="slow", timeout_s=2)
    k = make_job(tmp_path, "guard", scenario="ratelimit", stop_above_utilization=0.9)
    cleanup.extend([j, k])
    deleg("start", j)
    deleg("start", k)
    st = wait_state(j, timeout=30)
    assert st["state"] == "failed" and "timeout" in st["error"]
    sk = wait_state(k, timeout=30)
    assert sk["state"] == "stopped" and "usage" in sk["error"]


def test_run_follows_until_done_and_is_idempotent(tmp_path, cleanup):
    j = make_job(tmp_path, "run")
    cleanup.append(j)
    r = deleg("run", j, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.strip().splitlines()
    assert lines[-1].startswith("STATUS ") and out(r)["state"] == "done"
    assert any("result success" in l for l in lines) and all(len(l) < 300 for l in lines[:-1])
    again = deleg("run", j, timeout=30)
    assert again.returncode == 0 and "not starting it again" in again.stdout
    assert status(j)["attempt"] == 1
    st = out(deleg("start", j))
    assert st["ok"] is False and "fresh" in st["fix"]
    out(deleg("start", j, "--fresh"))
    t0 = time.monotonic()
    while (status(j).get("attempt") != 2 or status(j).get("state") != "done") and time.monotonic() - t0 < 30:
        time.sleep(0.2)
    assert status(j)["attempt"] == 2 and status(j)["history"]


def test_job_survives_killing_the_follower_shell(tmp_path, cleanup):
    """Grok Bot kills its background shells when its daemon restarts: the detached supervisor must keep the job alive."""
    j = make_job(tmp_path, "survive", scenario="workflow")
    cleanup.append(j)
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WIN else {"start_new_session": True}
    follower = subprocess.Popen([NODE, str(RUNNER), "run", str(j), "--allow-raw"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=env(FAKE_GAP_MS=3000), **kw)
    t0 = time.monotonic()
    while "workflow launched" not in read(j / "progress.log"):
        assert time.monotonic() - t0 < 30, read(j / "progress.log")
        time.sleep(0.1)
    if WIN:
        subprocess.run(["taskkill", "/PID", str(follower.pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        os.killpg(follower.pid, signal.SIGKILL)
    follower.wait(timeout=10)
    assert status(j)["state"] == "running"
    st = wait_state(j, timeout=40)
    assert st["state"] == "done" and "workflow finished" in st["result_text"]
    r = deleg("run", j, timeout=30)   # re-attaching with the same command never starts it twice
    assert r.returncode == 0 and status(j)["attempt"] == 1


def test_wait_status_lost_and_list(tmp_path, cleanup):
    j = make_job(tmp_path, "w")
    cleanup.append(j)
    deleg("start", j)
    r = deleg("wait", j, 20)
    assert r.stdout.strip().splitlines()[-1].startswith("STATUS ")
    wait_state(j)
    lost = make_job(tmp_path, "lost")
    (lost / "status.json").write_text(json.dumps({"state": "running", "supervisor_pid": 999999, "engine": "claude"}), encoding="utf-8")
    s = out(deleg("status", lost))
    assert s["state"] == "lost" and "resume" in s["next"]
    lst = out(deleg("list", tmp_path))
    states = {x["id"]: x["state"] for x in lst["jobs"]}
    assert states["w"] == "done" and states["lost"] == "lost" and lst["count"] == 2


def test_job_file_is_adopted_into_a_folder(tmp_path, cleanup):
    jobs = tmp_path / "proj" / "jobs"
    jobs.mkdir(parents=True)
    jf = jobs / "20261001-abcd-test.job.json"
    jf.write_text(json.dumps({"id": "20261001-abcd-test", "engine": "claude", "brief": "# from a single file\n",
                              "engine_bin": ["node", str(FAKE), "--as", "claude"]}), encoding="utf-8")
    cleanup.append(jobs / "20261001-abcd-test")
    r = deleg("run", jf, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    j = jobs / "20261001-abcd-test"
    assert (j / "job.json").exists() and read(j / "BRIEF.md").startswith("# from a single file")
    assert out(r)["job"].endswith("20261001-abcd-test")


def test_queue_respects_max_parallel(tmp_path, cleanup):
    a = make_job(tmp_path, "qa", scenario="slow", max_parallel=1)
    b = make_job(tmp_path, "qb", scenario="slow", max_parallel=1)
    cleanup.extend([a, b])
    deleg("start", a)
    wait_state(a, states=("running",), timeout=20)
    deleg("start", b)
    assert wait_state(b, states=("queued",), timeout=20)["state"] == "queued"
    deleg("stop", a, timeout=40)
    assert wait_state(b, states=("running",), timeout=30)["state"] == "running"
    deleg("stop", b, timeout=40)


def test_errors_are_helpful(tmp_path):
    bad = tmp_path / "jobs" / "bad"
    bad.mkdir(parents=True)
    (bad / "job.json").write_text('{"engine": "claude", "cwd": "C:\\Users\\x"}', encoding="utf-8")  # one backslash: invalid JSON
    r = out(deleg("start", bad))
    assert r["ok"] is False and "forward slashes" in r["fix"]
    r = out(deleg("status", tmp_path / "nope"))
    assert r["ok"] is False and "new" in r["fix"]
    miss = make_job(tmp_path, "miss", engine_bin=str(tmp_path / "no-such-engine.exe"))
    (miss / "job.json").write_text(json.dumps({"engine": "claude", "brief": "x", "engine_bin": str(tmp_path / "no-such-engine")}), encoding="utf-8")
    deleg("start", miss)
    st = wait_state(miss, timeout=20)
    assert st["state"] == "failed" and "not found" in st["error"]
    r = out(deleg("frobnicate"))
    assert r["ok"] is False and "run" in r["fix"]


def test_pack_unpack_in_parts(tmp_path):
    j = make_job(tmp_path, "pack")
    (j / "outbox" / "sub").mkdir(parents=True)
    (j / "outbox" / "sub" / "big.bin").write_bytes(os.urandom(300_000))
    (j / "outbox" / "report.md").write_text("# r\n", encoding="utf-8")
    r = out(deleg("pack", j, DELEG_PART_BYTES=100_000))
    assert r["ok"] and len(r["parts"]) >= 3 and r["archive"] is None
    dest = tmp_path / "dest"
    u = out(deleg("unpack", j / r["parts"][0], dest))
    assert u["ok"] and (dest / "outbox" / "sub" / "big.bin").stat().st_size == 300_000


def test_new_builds_a_self_contained_job_from_a_template(tmp_path):
    proj = tmp_path / "song"
    (proj / "analysis").mkdir(parents=True)
    (proj / "project.json").write_text(json.dumps({"name": "song", "title": "Test Song", "lead": {"canon": "a woman with a bob"},
                                                    "banned_words": ["foo", "bar"]}), encoding="utf-8")
    (proj / "analysis" / "beats.json").write_text(json.dumps({"duration": 123.456}), encoding="utf-8")
    r = out(deleg("new", "auto", "--project", proj, "--brief", "storyboard-panel", "--set", "OWNER_QUOTES=dense, on the beat"))
    assert r["ok"] and r["workflow"] == "storyboard", r
    j = Path(r["job_dir"])
    job = json.loads(read(j / "job.json"))
    assert job["project_dir"] == "../.." and job["engine"] == "claude" and job["kind"] == "storyboard"
    assert "Test Song" in job["brief"] and "123.46" in job["brief"] and "foo, bar" in job["brief"]
    assert "{{TITLE" not in job["brief"] and "{{WORKFLOW_PATH}}" in job["brief"]   # runtime tokens wait for the run
    assert job["workflow_args"]["banned_words"] == ["foo", "bar"] and job["workflow_args"]["duration"] == 123.46
    assert job["workflow_args"]["owner_quotes"] == "dense, on the beat"
    assert (j / "wf" / "storyboard.js").exists() and "board/shots.json" in job["collect"]
    # same inputs again = no-op; different inputs refuse without --force
    again = out(deleg("new", j, "--project", proj, "--brief", "storyboard-panel", "--set", "OWNER_QUOTES=dense, on the beat"))
    assert again["ok"]
    diff = out(deleg("new", j, "--project", proj, "--brief", "storyboard-panel", "--set", "OWNER_QUOTES=other"))
    assert diff["ok"] is False and "--force" in diff["fix"]
    # a missing variable is named, with how to set it
    miss = out(deleg("new", tmp_path / "x" / "jobs" / "y", "--brief", "research-lyrics"))
    assert miss["ok"] is False and "TODAY" in miss["error"] and "--set TODAY=" in miss["fix"]


def test_runtime_tokens_are_filled_on_the_running_machine(tmp_path, cleanup):
    proj = tmp_path / "song"
    (proj / "analysis").mkdir(parents=True)
    (proj / "project.json").write_text(json.dumps({"name": "song", "title": "T"}), encoding="utf-8")
    (proj / "analysis" / "beats.json").write_text(json.dumps({"duration": 60}), encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"engine_bin": ["node", str(FAKE), "--as", "claude", "--scenario", "workflow"]}), encoding="utf-8")
    r = out(deleg("new", "auto", "--project", proj, "--brief", "storyboard-panel", "--spec", spec))
    j = Path(r["job_dir"])
    cleanup.append(j)
    (j / "BRIEF.md").unlink()   # as if only job.json had been copied to this computer
    deleg("start", j, FAKE_GAP_MS=50)
    st = wait_state(j)
    assert st["state"] == "done", st
    brief = read(j / "BRIEF.md")
    assert "{{" not in brief and (j / "wf" / "storyboard.js").as_posix() in brief.replace("\\", "/")
    args = json.loads(read(j / "wf" / "args.json"))
    assert Path(args["project_dir"]) == proj.resolve() and Path(args["out_dir"]) == (j / "outbox").resolve()
    assert json.loads(read(j / "prompt-1.md").split("Workflow({scriptPath: ")[1].split(", args: ")[1].split("})`")[0]) == args


def test_selftest_and_doctor_and_templates():
    r = out(deleg("selftest", timeout=90))
    assert r["ok"], r["checks"]
    d = out(deleg("doctor", timeout=90))
    assert d["node"] and "engines" in d and set(d["engines"]) == {"claude", "codex", "muse", "gemini"}
    t = out(deleg("templates"))
    assert {b["name"] for b in t["briefs"]} >= {"research-lyrics", "storyboard-panel", "prompt-book", "chapter-motion", "review", "safety-scan"}
    assert {w["file"] for w in t["workflows"]} >= {"storyboard", "chapters", "research-lyrics"}
    h = out(deleg("help"))
    assert "node deleg.mjs run" in h["usage"]
