"""The production's effort (0.2.9): every turn passes the person's level to Claude Code (--effort) or Codex
(model_reasoning_effort), xhigh by default; `slop relay effort` is the slider; a level the engine turns down falls back
to its own default for that turn and is not passed again until a new level is set."""
from __future__ import annotations

import json
from pathlib import Path

from slop import relay

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K


def test_each_engine_gets_its_own_effort_flag(tmp_path):
    argv, _ = relay.engine_argv("claude", ["claude"], "hi", "hi", "opus", None, tmp_path, "xhigh")
    assert argv[argv.index("--effort") + 1] == "xhigh"
    argv, _ = relay.engine_argv("codex", ["codex"], "hi", "hi", None, "S1", tmp_path, "high")
    assert 'model_reasoning_effort="high"' in argv and argv[argv.index('model_reasoning_effort="high"') - 1] == "-c"
    for eng in ("claude", "codex"):
        argv, _ = relay.engine_argv(eng, [eng], "hi", "hi", None, None, tmp_path, None)
        assert "--effort" not in argv and not any("reasoning_effort" in a for a in argv)


def test_the_effort_slider(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch)
    monkeypatch.delenv("SLOP_CLAUDE_EFFORT", raising=False)
    monkeypatch.delenv("SLOP_CODEX_EFFORT", raising=False)
    assert K.run("relay", "setup")[0] == 0
    rc, out = K.run("relay", "effort")
    assert rc == 0 and out["engine"] == "claude" and out["effort"] == "xhigh" and out["default"] == "xhigh", out
    assert out["levels"] == ["low", "medium", "high", "xhigh", "max"] and out["engines"]["codex"]["effort"] == "xhigh"
    rc, out = K.run("relay", "effort", "max")
    assert rc == 0 and out["changed"] == "max" and out["effort"] == "max" and "next turn" in out["text"]
    rc, out = K.run("relay", "effort", "high", "--engine", "codex")
    assert rc == 0 and out["engine"] == "codex" and out["engines"] == {
        "claude": {"effort": "max", "source": "slop relay effort"},
        "codex": {"effort": "high", "source": "slop relay effort"}}
    rc, out = K.run("relay", "effort", "very hard")
    assert rc == 2 or (rc == 1 and "one word" in out["error"]), out
    rc, out = K.run("relay", "effort", "auto")
    assert rc == 0 and out["effort"] == "auto"
    rc, out = K.run("relay", "effort", "default")
    assert rc == 0 and out["effort"] == "xhigh"
    monkeypatch.setenv("SLOP_CLAUDE_EFFORT", "low")
    rc, out = K.run("relay", "effort")
    assert out["effort"] == "low" and "SLOP_CLAUDE_EFFORT" in out["text"]
    assert "effort: low" in K.run("relay", "status")[1]["text"]


def test_claude_codes_own_levels_win(monkeypatch):
    from slop.agents import engines as E
    help_text = ("  --effort <level>    Effort level for the current session\n"
                 "                      (low, medium, high, xhigh, max, ultra)\n")
    monkeypatch.setattr(E, "run_cli", lambda eng, args, timeout=30, **kw: (0, help_text, ""))
    assert relay.effort_levels("claude") == (["low", "medium", "high", "xhigh", "max", "ultra"], "claude --help")
    monkeypatch.setattr(E, "run_cli", lambda eng, args, timeout=30, **kw: (1, "", "not installed"))
    assert relay.effort_levels("claude")[1] == "the usual levels"


def test_turns_pass_the_effort_and_fall_back_when_it_is_turned_down(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    monkeypatch.delenv("SLOP_CLAUDE_EFFORT", raising=False)
    assert K.run("relay", "setup")[0] == 0
    K.run("relay", "send", "first")
    RT.collect(lambda it, r: any("heard #1" in i["text"] for i in it) and r["production"]["state"] == "idle")
    argv = RT.relay_calls(env)[-1]["argv"]
    assert argv[argv.index("--effort") + 1] == "xhigh"
    monkeypatch.setenv("FAKE_REJECT_EFFORT", "1")                 # e.g. an older Claude Code without --effort
    K.run("relay", "send", "second")
    RT.collect(lambda it, r: any("heard #2" in i["text"] for i in it) and r["production"]["state"] == "idle")
    calls = RT.relay_calls(env)
    assert "--effort" in calls[-2]["argv"] and "--effort" not in calls[-1]["argv"], "ran again at the default"
    data = json.loads((env["rd"] / "effort.json").read_text(encoding="utf-8"))
    assert data["rejected"] == {"claude": "xhigh"} and "unknown option" in data["rejected_why"]["claude"]
    n = len(RT.relay_calls(env))
    K.run("relay", "send", "third")
    RT.collect(lambda it, r: any("heard #3" in i["text"] for i in it) and r["production"]["state"] == "idle")
    assert len(RT.relay_calls(env)) == n + 1 and "--effort" not in RT.relay_calls(env)[-1]["argv"]
    rc, out = K.run("relay", "effort")
    assert out["effort"] == "auto" and "turned down" in out["text"]
    rc, out = K.run("relay", "effort", "high")                    # a new level is tried again
    assert out["effort"] == "high"
    assert not json.loads((env["rd"] / "effort.json").read_text(encoding="utf-8")).get("rejected")


def test_codex_turns_down_a_level_its_model_lacks(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch, logged=("codex",))
    monkeypatch.delenv("SLOP_CODEX_EFFORT", raising=False)
    assert K.run("relay", "setup", "--engine", "codex")[0] == 0
    monkeypatch.setenv("FAKE_REJECT_EFFORT", "1")
    K.run("relay", "send", "hello")
    RT.collect(lambda it, r: any("heard #1" in i["text"] for i in it) and r["production"]["state"] == "idle")
    calls = [c for c in K.calls(env["state"], "codex") if c.get("relay")]
    assert any("reasoning_effort" in a for a in calls[-2]["argv"])
    assert not any("reasoning_effort" in a for a in calls[-1]["argv"])
    assert "reasoning.effort" in json.loads((env["rd"] / "effort.json").read_text())["rejected_why"]["codex"]


def test_grok_knows_the_slider():
    root = Path(__file__).resolve().parents[1]
    text = (root / "skills/claudia-relay/SKILL.md").read_text(encoding="utf-8")
    assert "slop --json relay effort" in text and "--engine codex" in text and "question widget" in text
