"""`slop agents status [--limits]`, engine discovery and the environment the agent CLIs get (fake CLIs; no network:
the Claude usage read goes through util.http_json, which is mocked here)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX fake CLIs (shell wrappers)")


def test_status_rows_and_next_steps(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=("claude", "codex"), logged=("claude",))
    rc, out = K.run("agents", "status")
    assert rc == 0
    rows = {r["engine"]: r for r in out["agents"]}
    assert rows["claude"]["installed"] and rows["claude"]["version"] == "2.1.287" and rows["claude"]["logged_in"]
    assert rows["claude"]["via"] == "slop_home/bin" and rows["claude"]["next"] == "slop agents test claude"
    assert rows["codex"]["logged_in"] is False and rows["codex"]["next"] == "slop agents login codex"
    assert rows["muse"]["installed"] is False and rows["muse"]["next"] == "slop agents install muse"
    assert out["ready"] == ["claude"] and out["next"] == "slop agents login codex"
    assert "plan max" in out["text"] and "home computer" in out["text"]
    rc, one = K.run("agents", "status", "chatgpt")             # alias
    assert [r["engine"] for r in one["agents"]] == ["codex"]
    rc, bad = K.run("agents", "status", "copilot")
    assert rc == 1 and "unknown agent" in bad["error"]


def test_bare_agents_shows_status(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=())
    rc, out = K.run("agents")
    assert rc == 0 and len(out["agents"]) == 4 and all(not r["installed"] for r in out["agents"])


def test_a_dangling_link_counts_as_not_installed(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, engines=())
    (env["bin"] / "codex").symlink_to(env["sh"] / "npm" / "bin" / "codex")       # target wiped
    rc, out = K.run("agents", "status", "codex")
    assert out["agents"][0]["installed"] is False


def test_secrets_are_named_never_printed(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, logged=("claude", "codex"))
    vals = {"ANTHROPIC_API_KEY": "sk-ant-api03-" + "a" * 24, "OPENAI_API_KEY": "sk-proj-" + "b" * 24}
    for k, v in vals.items():
        monkeypatch.setenv(k, v)
    rc, out = K.run("agents", "status", "--limits")
    blob = json.dumps(out)
    for v in vals.values():
        assert v not in blob
    rows = {r["engine"]: r for r in out["agents"]}
    assert any("ANTHROPIC_API_KEY" in n for n in rows["claude"]["notes"])
    assert any("OPENAI_API_KEY" in n for n in rows["codex"]["notes"])


def test_base_env_strips_billing_and_toolkit_secrets(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch)
    from slop.agents import engines as E
    for k in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",
              "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "META_API_KEY",
              "CLAUDE_LOGIN_CODE", "GEMINI_LOGIN_CODE"):
        monkeypatch.setenv(k, "x")
    e = E.base_env("codex")
    assert "OPENAI_API_KEY" not in e and "CODEX_API_KEY" not in e and "OPENROUTER_API_KEY" not in e
    assert "CLAUDECODE" not in e and "CLAUDE_CODE_ENTRYPOINT" not in e
    # another vendor's agent never sees the Claude plan token, other engines' keys or a one-time sign-in code
    for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "META_API_KEY",
              "CLAUDE_LOGIN_CODE", "GEMINI_LOGIN_CODE"):
        assert k not in e, k
    assert e["PATH"].split(os.pathsep)[0] == str(E.bin_dir()) and e["MUSE_NO_AUTO_UPDATE"] == "1"
    c = E.base_env("claude")
    assert "ANTHROPIC_API_KEY" not in c and "OPENAI_API_KEY" not in c and "GEMINI_API_KEY" not in c
    assert c["CLAUDE_CODE_OAUTH_TOKEN"] == "x"                 # the plan token is Claude's own sign-in, not a bill
    assert "CLAUDE_LOGIN_CODE" not in c                        # codes go through the keeper's FIFO only
    g = E.base_env("gemini")
    assert g["GEMINI_API_KEY"] == "x" and "GOOGLE_API_KEY" not in g   # Gemini's key is one of its two sign-ins
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in g and "CLAUDE_CODE_OAUTH_TOKEN" not in E.base_env("muse")
    assert "OPENAI_API_KEY" in E.base_env("codex", plan_only=False)
    assert "ANTHROPIC_API_KEY" not in E.base_env("codex", plan_only=False)


def test_node_scripts_run_through_node(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, engines=())
    if not env["node"]:
        pytest.skip("node not installed")
    from slop.agents import engines as E
    js = env["sh"] / "npm" / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    js.parent.mkdir(parents=True)
    js.write_text("#!/usr/bin/env node\nconsole.log('codex-cli 0.160.0')\n"); js.chmod(0o755)
    (env["sh"] / "npm" / "bin").mkdir(parents=True)
    (env["sh"] / "npm" / "bin" / "codex").symlink_to(js)
    f = E.find("codex")
    assert f["via"] == "slop_home/npm" and f["argv"] == [env["node"], str(js.resolve())]
    assert E.version("codex") == "0.160.0"


def test_claude_limits_from_the_usage_endpoint(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, logged=("claude",))
    cred = env["home"] / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-" + "z" * 20, "expiresAt": 4102444800000,
                                                  "subscriptionType": "max"}}))
    seen = {}
    from slop import util

    def fake_http(url, headers=None, timeout=20, method="GET"):
        seen.update(url=url, headers=headers)
        return 200, {"five_hour": {"utilization": 12.0, "resets_at": "2026-10-01T20:00:00Z"},
                     "seven_day": {"utilization": 41.5, "resets_at": "2026-10-05T00:00:00Z"},
                     "seven_day_opus": None}, None
    monkeypatch.setattr(util, "http_json", fake_http)
    rc, out = K.run("agents", "status", "claude", "--limits")
    lim = out["agents"][0]["limits"]
    assert lim["available"] and [w["window"] for w in lim["windows"]] == ["5-hour", "weekly"]
    assert lim["windows"][1]["used_percent"] == 41.5
    assert seen["url"] == "https://api.anthropic.com/api/oauth/usage"
    assert seen["headers"]["anthropic-beta"] == "oauth-2025-04-20"
    assert "z" * 20 not in json.dumps(out) and "weekly 41.5%" in out["text"]
    monkeypatch.setattr(util, "http_json", lambda *a, **k: (401, {"error": {"message": "Invalid bearer token"}}, "x"))
    rc, out = K.run("agents", "status", "claude", "--limits")
    assert out["agents"][0]["limits"]["available"] is False and "--force" in out["agents"][0]["limits"]["why"]


def test_claude_limits_list_shape_and_expired_token(tmp_path, monkeypatch):
    from slop.agents import status
    w = status.parse_claude_usage({"limits": [
        {"kind": "session", "percent": 7, "resets_at": "t1"},
        {"kind": "x", "group": "weekly", "percent": 33.3, "scope": {"model": {"display_name": "Opus"}}}]})
    assert [x["window"] for x in w] == ["5-hour", "weekly (Opus)"] and w[1]["used_percent"] == 33.3
    env = K.setup(tmp_path, monkeypatch, logged=("claude",))
    cred = env["home"] / ".claude" / ".credentials.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(json.dumps({"claudeAiOauth": {"accessToken": "t", "expiresAt": 1000}}))
    lim = status.claude_limits()
    assert lim["available"] is False and "expired" in lim["why"]


def test_codex_plan_and_limits_from_app_server(tmp_path, monkeypatch):
    env = K.setup(tmp_path, monkeypatch, engines=("codex",), logged=("codex",))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-be-removed")
    rc, out = K.run("agents", "status", "codex", "--limits")
    row = out["agents"][0]
    assert row["auth"] == "chatgpt" and row["plan"] == "pro" and row["account"] == "u***@e***.com"
    lim = row["limits"]
    assert lim["available"] and lim["plan"] == "pro"
    assert {w["window"]: w["used_percent"] for w in lim["windows"]} == {"5-hour": 18.0, "weekly": 42.5}
    srv = [c for c in K.calls(env["state"], "codex")]
    assert srv == [] or all("OPENAI_API_KEY" not in c["env_present"] for c in srv)


def test_codex_limits_when_logged_out(tmp_path, monkeypatch):
    K.setup(tmp_path, monkeypatch, engines=("codex",))
    from slop.agents import status
    lim = status.codex_limits()
    assert lim["available"] is False and "authentication required" in lim["why"]


def test_muse_and_gemini_have_no_account_level_limits(tmp_path, monkeypatch):
    from slop.agents import status
    assert status.read_limits("muse")["available"] is False
    assert "inside a session" in status.read_limits("gemini")["why"]
