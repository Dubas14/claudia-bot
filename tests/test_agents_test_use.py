"""`slop agents test` (a tiny run through runner/deleg.mjs preflight, against runner/fake-engine.mjs), `slop agents use`
(preferences in $SLOP_HOME/onboard.json) and the runner's box tweaks: engines in $SLOP_HOME/bin first, node scripts run
through node, the Gemini engine (verified stream-json schema), and the preferred engine for `new`."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "runner" / "deleg.mjs"
FAKE = ROOT / "runner" / "fake-engine.mjs"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX fake CLIs")


def need_node(env):
    if not env["node"]:
        pytest.skip("node is not installed")


def node(env, *args, timeout=60):
    p = subprocess.run([env["node"], str(RUNNER), *args], capture_output=True, text=True, timeout=timeout,
                       env=dict(os.environ))
    return json.loads(p.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------------------------------------------- slop agents test
def test_test_is_skipped_when_not_installed_or_not_signed_in(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=("codex",))
    rc, out = K.run("agents", "test", "claude")
    assert rc == 1 and out["skipped"] and out["next"] == "slop agents install claude"
    rc, out = K.run("agents", "test", "codex")
    assert rc == 1 and out["skipped"] and out["next"] == "slop agents login codex"


@pytest.mark.parametrize("engine", ["claude", "codex", "muse"])
def test_test_runs_a_tiny_job_through_the_runner(tmp_path, monkeypatch, engine):
    env = K.setup(tmp_path, monkeypatch, logged=("claude", "codex"))
    need_node(env)
    if engine == "muse":
        f = env["home"] / ".config" / "muse" / "auth.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"providers": {"meta": {"access_token": "x"}}}))
    monkeypatch.setenv("FAKE_ROUTE_ENGINE", "1")
    monkeypatch.setenv("FAKE_REPLY", "PREFLIGHT-OK fake-model")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-must-not-reach-the-engine")
    rc, out = K.run("agents", "test", engine)
    assert rc == 0, out
    assert out["preflight_ok"] is True and out["state"] == "done" and "works" in out["text"]
    assert out["next"] == f"slop agents use {engine} --for director"
    job = Path(out["job"])
    assert job.parent == env["sh"] / "agents" / "tests"
    fc = [json.loads(x) for x in (job / "fake-calls.jsonl").read_text().splitlines()]
    assert fc and "OPENAI_API_KEY" not in fc[-1]["env_present"]
    if engine == "codex":
        assert 'forced_login_method="chatgpt"' in fc[-1]["argv"] and fc[-1]["stdin_len"] > 0


def test_gemini_test_with_an_api_key_passes_the_billing_gate(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-0123456789")
    monkeypatch.setenv("FAKE_ROUTE_ENGINE", "1")
    monkeypatch.setenv("FAKE_REPLY", "PREFLIGHT-OK fake-gemini")
    rc, out = K.run("agents", "test", "gemini")
    assert rc == 0 and out["preflight_ok"], out
    fc = [json.loads(x) for x in (Path(out["job"]) / "fake-calls.jsonl").read_text().splitlines()]
    assert "GEMINI_API_KEY" in fc[-1]["env_present"]
    assert fc[-1]["approval"] == "plan" and fc[-1]["skip_trust"] is True and fc[-1]["stdin_len"] == 0
    st = json.loads((Path(out["job"]) / "status.json").read_text())
    assert "api-billing ON" in st["gates"] and "AIza-test" not in json.dumps(st)


def test_failed_test_reports_the_engine_error(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("codex",))
    need_node(env)
    monkeypatch.setenv("FAKE_ROUTE_ENGINE", "1")
    monkeypatch.setenv("FAKE_SCENARIO", "error")
    rc, out = K.run("agents", "test", "codex")
    assert rc == 1 and "usage limit" in out["error"] and out["preflight_ok"] is False


# ------------------------------------------------------------------------------------------------- slop agents use
def test_use_records_preferences_and_keeps_other_onboarding_keys(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("claude", "codex"))
    ob = env["sh"] / "onboard.json"
    ob.write_text(json.dumps({"tier": "director", "items": {"toolkit": "done"}}))
    rc, out = K.run("agents", "use", "codex", "--for", "director")
    assert rc == 0 and out["use"] == {"director": "codex"}
    rc, out = K.run("agents", "use", "codex", "--for", "images")
    assert "--provider codex" in out["text"]
    rc, out = K.run("agents", "use", "claude", "--for", "images")
    assert rc == 1 and "only codex makes images" in out["error"]
    d = json.loads(ob.read_text())
    assert d["tier"] == "director" and d["items"] == {"toolkit": "done"}
    assert d["agents"]["use"] == {"director": "codex", "images": "codex"}
    rc, out = K.run("agents", "use")
    assert out["use"]["director"] == "codex" and "director" in out["text"]
    rc, out = K.run("agents", "use", "muse", "--for", "review")
    assert rc == 0 and "not signed in" in out["text"]
    rc, out = K.run("agents", "use", "codex")
    assert rc == 1 and "--for" in out["error"]


def test_use_refuses_an_engine_that_is_not_installed(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=())
    rc, out = K.run("agents", "use", "muse", "--for", "director")
    assert rc == 1 and "slop agents install muse" in out["error"]


# ------------------------------------------------------------------------------------------------- runner on the box
def test_runner_finds_engines_in_slop_home_bin_first(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    other = tmp_path / "elsewhere"; other.mkdir()
    K.add_fake(other, "claude")
    monkeypatch.setenv("PATH", f"{other}{os.pathsep}{os.environ['PATH']}")
    r = node(env, "_resolve", "claude")
    assert r["cmd"] == str(env["bin"] / "claude")
    js = env["sh"] / "npm" / "lib" / "node_modules" / "@google" / "gemini-cli" / "bundle" / "gemini.js"
    js.parent.mkdir(parents=True); js.write_text("console.log('0.62.0')\n")
    (env["bin"] / "gemini").unlink(); (env["bin"] / "gemini").symlink_to(js)
    r = node(env, "_resolve", "gemini")
    assert r["via"] == "node-script" and r["cmd"] == env["node"] and r["pre"] == [str(js.resolve())]
    (env["bin"] / "muse").unlink()
    (env["sh"] / "muse").mkdir(); K.add_fake(env["sh"] / "muse", "muse")
    assert node(env, "_resolve", "muse")["cmd"] == str(env["sh"] / "muse" / "muse")
    d = node(env, "doctor")
    assert set(d["engines"]) == {"claude", "codex", "muse", "gemini"} and d["engines"]["gemini"]["found"]


def _job(tmp_path, spec: dict) -> Path:
    J = tmp_path / "jobs" / f"g-{int(time.time() * 1000)}"
    J.mkdir(parents=True)
    (J / "job.json").write_text(json.dumps({"engine": "gemini", "brief": "# t\nSay OK.\n", "timeout_s": 60, **spec}))
    return J


def _run_job(env, J, *gates):
    out = subprocess.run([env["node"], str(RUNNER), "run", str(J), *gates], capture_output=True, text=True, timeout=90,
                         env=dict(os.environ))
    last = [ln for ln in out.stdout.splitlines() if ln.startswith("STATUS ")]
    return json.loads(last[-1][7:]) if last else {"raw": out.stdout + out.stderr}


def test_gemini_job_through_the_runner(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-strip-me")
    J = _job(tmp_path, {"engine_bin": ["node", str(FAKE), "--as", "gemini"]})
    st = _run_job(env, J, "--allow-raw")
    assert st["state"] == "done", st
    full = json.loads((J / "status.json").read_text())
    assert full["result_text"] == "Done: wrote outbox/report.md" and full["tokens"]["input"] == 110
    assert "GEMINI_API_KEY" in full["env_stripped"]
    call = json.loads((J / "fake-calls.jsonl").read_text().splitlines()[-1])
    a = call["argv"]
    assert a[a.index("-o") + 1] == "stream-json" and "--skip-trust" in a and call["approval"] == "auto_edit"
    assert call["stdin_len"] == 0 and "GEMINI_API_KEY" not in call["env_present"]
    assert str(J) in call["include"]
    assert "tool write_file" in (J / "progress.log").read_text()


def test_gemini_error_result_fails_the_job(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    J = _job(tmp_path, {"engine_bin": ["node", str(FAKE), "--as", "gemini", "--scenario", "error"]})
    st = _run_job(env, J, "--allow-raw")
    assert st["state"] == "failed" and "API key not valid" in st["error"]


def test_gemini_yolo_needs_allow_raw(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    J = _job(tmp_path, {"approval_mode": "yolo"})
    st = _run_job(env, J)
    assert st.get("ok") is False and "yolo" in st["error"] and "--allow-raw" in st["fix"]


def test_offline_parse_of_the_verified_gemini_stream(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    f = tmp_path / "g.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in [
        {"type": "init", "timestamp": "t", "session_id": "ac326553-859e-4850-9357-689419277454", "model": "auto"},
        {"type": "message", "timestamp": "t", "role": "user", "content": "Reply exactly OK"},
        {"type": "result", "timestamp": "t", "status": "error",
         "error": {"type": "unknown", "message": "[API Error: API key not valid. Please pass a valid API key.]"}}]) + "\n")
    r = node(env, "_parse", "gemini", str(f))
    assert r["status"]["session_id"] == "ac326553-859e-4850-9357-689419277454"
    assert r["status"]["final"]["is_error"] is True and "API key not valid" in r["status"]["final"]["text"]


def test_new_uses_the_preferred_engine_when_the_template_allows_it(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    (env["sh"] / "onboard.json").write_text(json.dumps({"agents": {"use": {"director": "codex", "review": "muse"}}}))
    gv = tmp_path / "generic.json"
    gv.write_text(json.dumps({k: "x" for k in ("TASK", "ROLE", "GOAL", "CHECK", "FILES", "RULES", "CHEATS", "FIRST",
                                               "METHOD", "BUDGET", "DONT")}))
    rv = tmp_path / "review.json"
    rv.write_text(json.dumps({"TITLE": "Song", "TARGET": "the cut", "T0": "0", "T1": "10"}))

    def engine_of(name, *extra):
        r = node(env, "new", str(tmp_path / name), *extra)
        assert r["ok"], r
        return json.loads((tmp_path / name / "job.json").read_text())["engine"]
    assert engine_of("j1", "--brief", "generic", "--vars", str(gv)) == "codex"            # director preference
    assert engine_of("j2", "--brief", "review", "--vars", str(rv)) == "muse"              # review preference
    assert engine_of("j3", "--brief", "generic", "--vars", str(gv), "--engine", "claude") == "claude"
    assert engine_of("j4", "--brief", "generic", "--vars", str(gv), "--workflow", "safety-scan") == "claude"
    (env["sh"] / "onboard.json").write_text(json.dumps({"agents": {"use": {"director": "gemini"}}}))
    assert engine_of("j5", "--brief", "generic", "--vars", str(gv)) == "claude"           # not listed by the template
