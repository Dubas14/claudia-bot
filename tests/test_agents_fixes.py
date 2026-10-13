"""Review fixes for the agents track: installs that survive a box wipe (Claude Code kept under $SLOP_HOME), the director
preference that really applies (workflow briefs run without the Claude workflow), credentials that stay with their
engine, a rejected sign-in that does not loop, box-wide job slots, Gemini API-key jobs through the pass-env gate, the
images preference, codex image runs one at a time. Fakes only (fakecli.py, runner/fake-engine.mjs): no network."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "runner" / "deleg.mjs"
FAKE = ROOT / "runner" / "fake-engine.mjs"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX fake CLIs and links")

FAKE_NPM = r'''#!/bin/sh
echo "$@" >> "$FAKE_STATE/npm-calls.txt"
prefix=""; pkg=""
while [ $# -gt 0 ]; do case "$1" in --prefix) prefix="$2"; shift;; @*) pkg="$1";; esac; shift; done
case "$pkg" in
  @openai/codex@*) name=codex;; @google/gemini-cli@*) name=gemini;; @anthropic-ai/claude-code@*) name=claude;; *) exit 3;;
esac
mkdir -p "$prefix/bin"
printf '#!/bin/sh\nexec "%s" "%s" %s "$@"\n' "$FAKE_PY" "$FAKE_CLI" "$name" > "$prefix/bin/$name"
chmod 755 "$prefix/bin/$name"
'''


def need_node(env):
    if not env["node"]:
        pytest.skip("node is not installed")


def node(*args, timeout=60, env=None):
    p = subprocess.run([shutil.which("node"), str(RUNNER), *map(str, args)], capture_output=True, text=True,
                       timeout=timeout, env=env or dict(os.environ))
    lines = [ln for ln in p.stdout.strip().splitlines() if ln.strip()]
    st = [ln for ln in lines if ln.startswith("STATUS ")]
    last = st[-1] if st else (lines[-1] if lines else "{}")
    return json.loads(last[7:] if last.startswith("STATUS ") else last)


@pytest.fixture
def kit(tmp_path, monkeypatch):
    """Fake npm + fake vendor installers (claude writes ~/.local/bin/claude, muse writes $MUSE_INSTALL_DIR/muse)."""
    e = K.setup(tmp_path, monkeypatch, engines=())
    tools = tmp_path / "tools"; tools.mkdir()
    (tools / "npm").write_text(FAKE_NPM); (tools / "npm").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_PY", sys.executable)
    monkeypatch.setenv("FAKE_CLI", str(K.FAKECLI))
    from slop.agents import engines as E
    from slop.agents import install
    monkeypatch.setattr(E, "node_info", lambda: {"path": "/usr/bin/node", "version": "v20.20.2", "major": 20})
    shim = f'printf \'#!/bin/sh\\nexec "{sys.executable}" "{K.FAKECLI}" %s "$@"\\n\''
    bodies = {"claude": f'mkdir -p "$HOME/.local/bin"; {shim % "claude"} > "$HOME/.local/bin/claude"; '
                        'chmod 755 "$HOME/.local/bin/claude"',
              "muse": f'mkdir -p "$MUSE_INSTALL_DIR"; {shim % "muse"} > "$MUSE_INSTALL_DIR/muse"; '
                      'chmod 755 "$MUSE_INSTALL_DIR/muse"'}
    e["downloads"] = []

    def dl(url, dst):
        e["downloads"].append(url)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("#!/bin/bash\nset -e\n" + bodies["claude" if "claude" in url else "muse"] + "\n")
        return dst
    monkeypatch.setattr(install, "_download", dl)
    return e


# ------------------------------------------------------------------------------------------------- box wipe
def test_installs_survive_a_wiped_home_on_the_box(kit, monkeypatch):
    from slop.agents import engines as E
    monkeypatch.setattr(E, "on_box", lambda: True)
    rc, out = K.run("agents", "install", "all", "--foreground")
    assert rc == 0, out
    claude = next(r for r in out["installed"] if r["engine"] == "claude")
    kept = kit["sh"] / "claude" / "versions" / "2.1.287" / "claude"
    assert claude["kept_copy"] == str(kept) and kept.is_file() and os.access(kept, os.X_OK)
    assert os.readlink(kit["sh"] / "bin" / "claude") == str(kept)
    shutil.rmtree(kit["home"])                       # the computer update: everything outside /workspace is gone
    rc, st = K.run("agents", "status")
    assert rc == 0
    rows = {r["engine"]: r for r in st["agents"]}
    assert all(rows[e]["installed"] for e in E.ENGINES), {e: rows[e].get("detail") for e in E.ENGINES}
    assert rows["claude"]["version"] == "2.1.287" and rows["claude"]["bin"] == str(kit["sh"] / "bin" / "claude")
    assert "signin_note" in st and "slop agents login" in st["signin_note"]
    if kit["node"]:
        d = node("doctor")
        assert d["engines"]["claude"]["found"] and d["engines"]["claude"]["cmd"] == str(kit["sh"] / "bin" / "claude")


def test_box_copies_a_claude_found_only_in_home_without_downloading(kit, monkeypatch):
    from slop.agents import engines as E
    rc, out = K.run("agents", "install", "claude", "--foreground")          # the user's own computer: stays in ~/.local
    assert rc == 0 and out["installed"][0]["kept_copy"] is None
    assert os.readlink(kit["sh"] / "bin" / "claude") == str(kit["home"] / ".local" / "bin" / "claude")
    assert E.survives_update(str(kit["home"] / ".local" / "bin" / "claude")) is True       # off the box: always kept
    monkeypatch.setattr(E, "on_box", lambda: True)
    assert E.survives_update(str(kit["home"] / ".local" / "bin" / "claude")) is False
    assert E.survives_update(str(kit["sh"] / "npm" / "bin" / "codex")) is True
    n = len(kit["downloads"])
    rc, out = K.run("agents", "install", "claude", "--foreground")
    row = out["installed"][0]
    assert rc == 0 and row["skipped"] and row["kept_copy"] and len(kit["downloads"]) == n
    assert os.readlink(kit["sh"] / "bin" / "claude") == row["kept_copy"]
    rc, out = K.run("agents", "install", "claude", "--foreground")          # third run: nothing to do
    assert out["installed"][0]["skipped"] and out["installed"][0]["kept_copy"] is None


def test_box_status_says_where_sign_ins_live(kit, monkeypatch):
    from slop.agents import engines as E
    rc, st = K.run("agents", "status", "codex")
    assert "signin_note" not in st
    monkeypatch.setattr(E, "on_box", lambda: True)
    rc, st = K.run("agents", "status", "codex")
    assert "home folder" in st["signin_note"] and "slop agents login ENGINE" in st["text"]


def test_windows_dry_run_names_the_manual_muse_install(kit, monkeypatch):
    from slop.agents import engines as E
    from slop.agents import install
    monkeypatch.setattr(E, "WIN", True)
    p = install.plan("muse")
    assert p["manual"] and p["link"] is None and "dev.meta.ai" in p["command"] and "bash" not in p["command"]
    assert install.plan("codex")["link"] is None
    with pytest.raises(install.SlopError, match="dev.meta.ai"):
        install.install_one("muse")


# ------------------------------------------------------------------------------------------------- the director preference
def _new(tmp_path, name, *extra):
    r = node("new", tmp_path / "jobs" / name, *extra)
    assert r.get("ok"), r
    return r, json.loads((tmp_path / "jobs" / name / "job.json").read_text())


def test_codex_as_director_runs_workflow_briefs_without_the_workflow(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("codex",))
    need_node(env)
    (env["sh"] / "onboard.json").write_text(json.dumps({"agents": {"use": {"director": "codex"}}}))
    r, job = _new(tmp_path, "sb", "--brief", "storyboard-panel", "--set", "TITLE=Song", "--set", "DURATION=100")
    assert job["engine"] == "codex" and job["workflow"] is None and "workflow_args" not in job
    assert "storyboard" in r["engine_note"] and "--engine claude" in r["engine_note"]
    assert "slop agents use codex --for director" in r["engine_from"]
    r, job = _new(tmp_path, "rl", "--brief", "research-lyrics", "--set", "TITLE=Song", "--set", "TODAY=2026-10-01",
                  "--set", "CONCEPT=x")
    assert job["engine"] == "codex" and job["workflow"] is None and job["network"] is True
    r, job = _new(tmp_path, "ss", "--brief", "safety-scan", "--set", "TITLE=Song", "--set", "TOTAL=3",
                  "--set", "LEAD_CANON=x")                               # review role -> director
    assert job["engine"] == "codex" and job["workflow"] is None
    # an explicit --workflow needs Claude: the preference yields, and says so
    gv = tmp_path / "g.json"
    gv.write_text(json.dumps({k: "x" for k in ("TASK", "ROLE", "GOAL", "CHECK", "FILES", "RULES", "CHEATS", "FIRST",
                                               "METHOD", "BUDGET", "DONT")}))
    r, job = _new(tmp_path, "wf", "--brief", "generic", "--vars", gv, "--workflow", "safety-scan")
    assert job["engine"] == "claude" and job["workflow"] == "safety-scan" and "--workflow none" in r["engine_note"]
    # the preference is honoured, never silently: a brief that does not list muse stays on claude with a note
    (env["sh"] / "onboard.json").write_text(json.dumps({"agents": {"use": {"director": "muse"}}}))
    r, job = _new(tmp_path, "rl2", "--brief", "research-lyrics", "--set", "TITLE=Song", "--set", "TODAY=2026-10-01",
                  "--set", "CONCEPT=x")
    assert job["engine"] == "claude" and job["workflow"] == "research-lyrics"
    assert "does not list it" in r["engine_note"] and "muse" in r["engine_note"]
    r, job = _new(tmp_path, "sb2", "--brief", "storyboard-panel", "--set", "TITLE=Song", "--set", "DURATION=100")
    assert job["engine"] == "muse" and job["workflow"] is None
    # an explicit non-Claude engine drops the template's default workflow too (only Claude has the Workflow tool)
    r, job = _new(tmp_path, "sb3", "--brief", "storyboard-panel", "--set", "TITLE=Song", "--set", "DURATION=100",
                  "--engine", "codex")
    assert job["engine"] == "codex" and job["workflow"] is None and "step by step" in r["engine_note"]
    r, job = _new(tmp_path, "sb4", "--brief", "storyboard-panel", "--set", "TITLE=Song", "--set", "DURATION=100",
                  "--engine", "claude")
    assert job["workflow"] == "storyboard" and "engine_note" not in r


def test_use_names_exactly_which_briefs_follow(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, logged=("claude", "codex"))
    f = tmp_path / "home" / ".config" / "muse" / "auth.json"
    f.parent.mkdir(parents=True); f.write_text(json.dumps({"providers": {"meta": {"access_token": "x"}}}))
    rc, out = K.run("agents", "use", "codex", "--for", "director")
    b = out["briefs"]
    assert rc == 0 and {"generic", "prompt-book"} <= set(b["as_is"])
    assert {"storyboard-panel", "research-lyrics", "chapter-motion"} <= set(b["in_sequence"])
    assert "WITHOUT the Claude workflow" in out["text"] and "Review briefs follow" in out["text"]
    rc, out = K.run("agents", "use", "muse", "--for", "director")
    assert {"research-lyrics", "prompt-book", "chapter-motion"} <= set(out["briefs"]["claude"])
    assert "still Claude Code" in out["text"]
    rc, out = K.run("agents", "use", "muse", "--for", "review")
    assert set(out["briefs"]["as_is"]) == {"review"} and set(out["briefs"]["in_sequence"]) == {"safety-scan"}


def test_gemini_is_refused_as_director_and_review(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch)
    for role in ("director", "review"):
        rc, out = K.run("agents", "use", "gemini", "--for", role)
        assert rc == 1 and "no brief lists it" in out["error"] and "--engine gemini" in out["error"]
    assert not (tmp_path / "sh" / "onboard.json").exists()


def test_use_writes_under_the_onboarding_lock(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("codex",))
    ob = env["sh"] / "onboard.json"
    ob.write_text(json.dumps({"tier": "studio", "marks": {"keys": {"state": "done"}}}))
    lock = env["sh"] / "onboard.json.lock"
    lock.write_text("12345")                           # another slop command holds it for 0.6 s
    t = threading.Timer(0.6, lambda: lock.unlink())
    t.start()
    t0 = time.monotonic()
    rc, out = K.run("agents", "use", "codex", "--for", "director")
    t.join()
    assert rc == 0 and time.monotonic() - t0 >= 0.5, "set_use must wait for the onboarding lock"
    d = json.loads(ob.read_text())
    assert d["agents"]["use"] == {"director": "codex"} and d["tier"] == "studio" and d["marks"]["keys"]["state"] == "done"
    from slop.onboard import state
    assert state.agent_use("director") == "codex"


# ------------------------------------------------------------------------------------------------- credentials
def _fake_job(tmp_path, name, engine, **extra):
    J = tmp_path / "jobs" / name
    J.mkdir(parents=True)
    (J / "job.json").write_text(json.dumps({"engine": engine, "brief": "# t\nSay OK.\n", "timeout_s": 60,
                                            "engine_bin": ["node", str(FAKE), "--as", engine], **extra}))
    return J


def test_the_claude_plan_token_and_login_codes_stay_out_of_other_engines(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-" + "t" * 30)
    monkeypatch.setenv("CLAUDE_LOGIN_CODE", "code#" + "c" * 20)
    monkeypatch.setenv("GEMINI_LOGIN_CODE", "4/" + "g" * 20)
    seen = {}
    for eng in ("codex", "muse", "gemini", "claude"):
        J = _fake_job(tmp_path, f"cred-{eng}", eng)
        st = node("run", J, "--allow-raw", timeout=90)
        assert st.get("state") == "done", st
        call = json.loads((J / "fake-calls.jsonl").read_text().splitlines()[-1])
        seen[eng] = call["env_present"]
        full = json.loads((J / "status.json").read_text())
        assert "CLAUDE_LOGIN_CODE" in full["env_stripped"] and "t" * 30 not in json.dumps(full)
    for eng in ("codex", "muse", "gemini"):
        assert "CLAUDE_CODE_OAUTH_TOKEN" not in seen[eng], eng
    assert "CLAUDE_CODE_OAUTH_TOKEN" in seen["claude"]
    assert not any(k in v for v in seen.values() for k in ("CLAUDE_LOGIN_CODE", "GEMINI_LOGIN_CODE"))


def test_code_from_env_reads_only_the_engines_own_code_secret(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-" + "k" * 40)
    for name in ("OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GEMINI_LOGIN_CODE", "ANTHROPIC_API_KEY"):
        rc, out = K.run("agents", "login", "claude", "--code-from-env", name)
        assert rc == 1 and "reads only CLAUDE_LOGIN_CODE" in out["error"] and "k" * 40 not in json.dumps(out)
    rc, out = K.run("agents", "login", "gemini", "--code-from-env", "CLAUDE_LOGIN_CODE")
    assert rc == 1 and "reads only GEMINI_LOGIN_CODE" in out["error"]


def test_gemini_key_only_from_gemini_api_key_and_jobs_need_the_pass_env_gate(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-google-0123456789")
    rc, out = K.run("agents", "login", "gemini", "--key-from-env", "GOOGLE_API_KEY")
    assert rc == 1 and "GEMINI_API_KEY" in out["error"]
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-gemini-0123456789")
    rc, out = K.run("agents", "login", "gemini", "--key-from-env", "GEMINI_API_KEY")
    assert rc == 0 and "--pass-env GEMINI_API_KEY" in out["text"] and "AIza" not in json.dumps(out)
    need_node(env)
    gv = tmp_path / "g.json"
    gv.write_text(json.dumps({k: "x" for k in ("TASK", "ROLE", "GOAL", "CHECK", "FILES", "RULES", "CHEATS", "FIRST",
                                               "METHOD", "BUDGET", "DONT")}))
    r, job = _new(tmp_path, "gk", "--brief", "generic", "--vars", gv, "--engine", "gemini")
    assert job["pass_env"] == ["GEMINI_API_KEY"] and "--pass-env GEMINI_API_KEY" in r["gates_needed"]
    assert any("--pass-env GEMINI_API_KEY" in n for n in r["notes"])
    J = tmp_path / "jobs" / "gk"
    job["engine_bin"] = ["node", str(FAKE), "--as", "gemini"]
    (J / "job.json").write_text(json.dumps(job))
    st = node("run", J, "--allow-raw", timeout=60)              # without the gate: refused before anything starts
    assert st.get("ok") is False and "--pass-env GEMINI_API_KEY" in st["fix"]
    st = node("run", J, "--allow-raw", "--pass-env", "GEMINI_API_KEY", timeout=90)
    assert st.get("state") == "done", st
    call = json.loads((J / "fake-calls.jsonl").read_text().splitlines()[-1])
    assert "GEMINI_API_KEY" in call["env_present"] and "GOOGLE_API_KEY" not in call["env_present"]
    # a brief whose checks run shell commands gets the [unverified] no-shell warning; allowed_tools is passed through
    rv = tmp_path / "r.json"
    rv.write_text(json.dumps({"TITLE": "Song", "TARGET": "the cut", "T0": "0", "T1": "10"}))
    r, job = _new(tmp_path, "gr", "--brief", "review", "--vars", rv, "--engine", "gemini")
    assert any("shell commands" in n for n in r["notes"])
    J2 = _fake_job(tmp_path, "gtools", "gemini", allowed_tools=["run_shell_command"])
    st = node("run", J2, "--allow-raw", timeout=90)
    a = json.loads((J2 / "fake-calls.jsonl").read_text().splitlines()[-1])["argv"]
    assert a[a.index("--allowed-tools") + 1] == "run_shell_command"


# ------------------------------------------------------------------------------------------------- a rejected sign-in
def test_a_rejected_sign_in_points_at_a_new_sign_in_not_back_at_status(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("claude",))
    need_node(env)
    monkeypatch.setenv("FAKE_ROUTE_ENGINE", "1")
    monkeypatch.setenv("FAKE_SCENARIO", "auth")
    rc, out = K.run("agents", "test", "claude")
    assert rc == 1 and out["signin_rejected"] and out["next"] == "slop agents login claude --force"
    assert "success:" not in out["error"] and "401" in out["error"]
    (env["state"] / "claude_logged_in").unlink()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-" + "b" * 30)
    rc, out = K.run("agents", "test", "claude")
    assert rc == 1 and out["next"] == "slop agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN"
    assert "claude setup-token" in out["ask_user"] and "b" * 30 not in json.dumps(out)
    rc, out = K.run("agents", "login", "claude", "--force")       # a new sign-in cannot beat the env token
    assert rc == 1 and "CLAUDE_CODE_OAUTH_TOKEN is set" in out["error"] and "setup-token" in out["error"]


def test_claude_limits_401_with_a_token_asks_for_a_new_token(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-" + "z" * 30)
    from slop import util
    from slop.agents import status
    monkeypatch.setattr(util, "http_json", lambda *a, **k: (401, None, "401"))
    r = status.claude_limits()
    assert r["signin_rejected"] and "setup-token" in r["why"] and r["next"].endswith("CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    monkeypatch.setattr(status, "_claude_token", lambda: ("tok", "credentials file"))
    assert status.claude_limits()["next"] == "slop agents login claude --force"


# ------------------------------------------------------------------------------------------------- box-wide slots
def test_box_wide_slots_span_every_jobs_folder(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    need_node(env)
    monkeypatch.setenv("DELEG_BOX_SLOTS", "1")
    a = tmp_path / "projA" / "jobs" / "a"; b = tmp_path / "projB" / "jobs" / "b"
    for J in (a, b):
        J.mkdir(parents=True)
        (J / "job.json").write_text(json.dumps({"engine": "claude", "brief": "# t\n", "timeout_s": 120,
                                                "engine_bin": ["node", str(FAKE), "--as", "claude", "--scenario", "slow"]}))
    try:
        assert node("start", a, "--allow-raw").get("ok") is not False
        _wait(a, ("running",))
        node("start", b, "--allow-raw")
        st = _wait(b, ("queued",))
        assert st["state"] == "queued" and "box-wide" in (b / "progress.log").read_text()
        assert json.loads((env["sh"] / "agents" / "slots" / "slot-0.lock").read_text())["job"].endswith("/a")
        node("stop", a, timeout=40)
        assert _wait(b, ("running",), 40)["state"] == "running"
    finally:
        for J in (a, b):
            node("stop", J, "--force", timeout=40)
    _wait(b, ("stopped", "failed", "done"), 30)
    time.sleep(0.5)
    assert not list((env["sh"] / "agents" / "slots").glob("slot-*.lock"))     # released


def _wait(J, states, secs=30):
    t0 = time.monotonic()
    st = {}
    while time.monotonic() - t0 < secs:
        try:
            st = json.loads((J / "status.json").read_text())
        except (OSError, ValueError):
            st = {}
        if st.get("state") in states:
            return st
        time.sleep(0.2)
    return st


# ------------------------------------------------------------------------------------------------- images
def test_images_preference_routes_gen_image_to_codex_unless_api_flags(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("codex",))
    from slop.gen import codex_image
    got = []
    monkeypatch.setattr(codex_image, "cmd_image", lambda a: got.append(a.provider) or {"ok": True, "text": "started"})
    rc, out = K.run("gen", "image", "a hall", "--plate", "p1")
    assert rc == 1 and not got                                   # no preference: the OpenRouter path (needs a project)
    (env["sh"] / "onboard.json").write_text(json.dumps({"agents": {"use": {"images": "codex"}}}))
    rc, out = K.run("gen", "image", "a hall", "--plate", "p1")
    assert rc == 0 and got == ["codex"] and "slop agents use codex --for images" in out["provider_note"]
    rc, out = K.run("gen", "image", "a hall", "--plate", "p1", "--model", "openai/gpt-image-2")
    assert got == ["codex"]                                      # --model picks the API path
    rc, out = K.run("gen", "image", "a hall", "--plate", "p1", "--provider", "openrouter")
    assert got == ["codex"]


def test_codex_image_fallback_stays_in_the_runs_own_folder(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch)
    from slop.gen import codex_image
    root = env["home"] / ".codex" / "generated_images"
    (root / "t-mine").mkdir(parents=True); (root / "t-other").mkdir(parents=True)
    since = time.time()
    mine = root / "t-mine" / "ig_1.png"; mine.write_bytes(b"x")
    time.sleep(0.05)
    other = root / "t-other" / "ig_9.png"; other.write_bytes(b"y")       # newer, from another run
    assert codex_image._new_images(since, "t-mine") == [mine]
    assert codex_image._new_images(since, None)[-1] == other           # no thread id: the old behaviour


def test_codex_image_runs_one_at_a_time_and_cleans_its_scratch(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, engines=("codex",), logged=("codex",))
    from slop.gen import codex_image
    order = []
    real = codex_image._run_codex

    def slow(prompt, refs, timeout):
        order.append("in")
        time.sleep(0.4)
        r = real(prompt, refs, timeout)
        order.append("out")
        return r
    monkeypatch.setattr(codex_image, "_run_codex", slow)
    res = []
    ts = [threading.Thread(target=lambda: res.append(codex_image.run_codex("p", [], 60))) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert order == ["in", "out", "in", "out"] and len(res) == 2
    proj = tmp_path / "proj"; (proj).mkdir()
    (proj / "project.json").write_text(json.dumps({"name": "proj"}))
    g = codex_image.generate_one(proj, prompt="a hall", out=proj / "a.png")
    assert Path(g["file"]).is_file()
    left = [p.name for p in (env["sh"] / "agents" / "imagegen").iterdir() if p.is_dir()]
    assert len(left) == 2                                    # the two direct runs above kept theirs; generate_one did not


def test_a_consumed_sign_in_code_is_refused_before_it_reaches_the_vendor(tmp_path, monkeypatch):
    """The secure-card secret outlives its sign-in: re-feeding the old code must stop with 'ask for the NEW code'."""
    import hashlib
    import pytest
    from slop.agents import login as L
    from slop.config import SlopError
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_LOGIN_CODE", "abc123-OLD")
    monkeypatch.setattr(L, "read_state", lambda engine: {"alive": True, "state": "waiting_code"})
    sent = []
    monkeypatch.setattr(L, "put_code", lambda engine, code: sent.append(code))
    used = L._used_codes_file("claude")
    used.parent.mkdir(parents=True, exist_ok=True)
    used.write_text(hashlib.sha256(b"abc123-OLD").hexdigest() + "\n", encoding="utf-8")
    with pytest.raises(SlopError) as e:
        L.send_code("claude", "CLAUDE_LOGIN_CODE", wait=0)
    assert "EARLIER sign-in" in str(e.value) and "NEW code" in str(e.value)
    assert sent == []                                     # nothing was typed into the waiting sign-in
    assert "abc123-OLD" not in used.read_text(encoding="utf-8")   # hashes only
