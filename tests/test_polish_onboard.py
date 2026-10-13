"""Tier readiness after the live Quick run (owner decision 2026-10-02, e2e/QUICK-E2E.md):

- Quick is READY with no account at all: stills from Grok's own image tool (GenerateImage), motion = 2.5D + devices,
  the song = the user's upload (Lyria only when OpenRouter exists).
- Studio is READY with OpenRouter OR Higgsfield (item `video`; both recommended: OpenRouter is cheaper per second,
  Higgsfield copies the vocals more reliably on stubborn windows); the last route left is required.
- Director additionally needs one coding agent signed in, on the box or on the user's own computer.
- `routes` says what works now; `install` says whether the toolkit is ready (probe before announcing an install).
Probe results are fed in directly: no network, no child processes, no spend."""
from __future__ import annotations

import json
import shlex

import pytest

from slop import cli, util
from slop.onboard import items as I
from slop.onboard import probes
from slop.onboard import state as st

NO_KEY = {"present": False, "checked": False, "valid": False}
PROJECT = {"name": "my-song", "tier": "quick", "mj_profile_set": False, "mj_plan": "standard", "broken": False,
           "mtime": 1.0}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("HOME", str(tmp_path / "user"))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY", "ARENA_TOKEN", "HIGGSFIELD_API_KEY", "SLOP_PROFILE",
              "SLOP_MODULES", "SLOP_WAIT_MAX", "GEMINI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def data(**over) -> dict:
    """A box with the toolkit (full profile) installed and NO account: no OpenRouter key, no Higgsfield."""
    d = {"tk": {"version": "0.1.0", "profile": "full", "installed": True, "env_sh": "/w/.claudia/env.sh",
                "shim": "/w/.claudia/bin/slop", "slop_home": "/w/.claudia", "toolkit": "/w/claudia",
                "on_path": True, "shell_rc": [], "on_box": True},
         "doc": {"ok": True, "fails": [], "warns": [], "passed": 12, "deps_full": "ok"},
         "key": dict(NO_KEY), "env": {"ARENA_TOKEN": False, "HIGGSFIELD_API_KEY": False},
         "agents": {"available": False, "engines": {}}, "gpu": {"available": False},
         "taste": {"available": True, "taps": 0, "images": 0, "meter": None}, "projects": [], "running": []}
    for k, v in over.items():
        d[k] = {**d[k], **v} if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    return d


KEY = {"present": True, "checked": True, "valid": True, "limit": 25.0, "limit_remaining": 20.0, "usage": 5.0}


def rep(tier="quick", **over):
    st.set_setting("tier", tier)
    return I.report(tier=tier, data=data(**over))


def item(r, iid):
    return next(i for i in r["items"] if i["id"] == iid)


def engines(**rows):
    return {"available": True, "ok": True, "engines": rows}


# ---------------------------------------------------------------- Quick: no account at all
def test_quick_is_ready_with_no_openrouter_and_no_higgsfield():
    r = rep("quick")
    assert r["tiers"]["quick"] == {"ready": True, "missing": []} and r["ready"]
    assert not r["tiers"]["studio"]["ready"] and r["tiers"]["studio"]["missing"] == ["video"]
    assert r["routes"] == {"stills": ["grok-image"], "clips": [], "song": ["upload"],
                           "text": "stills from Grok's image tool, 2.5D motion with devices, the song from your own "
                                   "upload"}
    assert ("Quick tier ready: stills from Grok's image tool, 2.5D motion with devices, the song from your own upload, "
            "render and master here") in r["unlocked"]
    for rid in ("openrouter", "higgsfield"):           # offered (recommended), never required for Quick
        it = item(r, rid)
        assert it["state"] == "todo" and it["need"] == "recommended", it
        assert "Quick needs no account" in it["why"] and "Grok's image tool" in it["why"]
    assert "not wanted: slop onboard mark openrouter --skip" in item(r, "openrouter")["do"]
    ai, vid, ly = item(r, "api-images"), item(r, "video"), item(r, "lyria")
    assert ai["state"] == "blocked" and ai["need"] == "recommended" and "GenerateImage" in ai["why"]
    assert vid["state"] == "blocked" and vid["any_of"] and "2.5D motion and devices" in vid["why"]
    assert ly["state"] == "blocked" and "user's own upload" in ly["why"], "Lyria only with OpenRouter"
    assert "Works now: stills from Grok's image tool" in I.render_status(r)


def test_quick_with_both_routes_skipped_still_hands_off():
    st.set_setting("coding-agents", "none")
    for iid in ("openrouter", "higgsfield", "gpu"):
        st.set_mark(iid, "skip")
    r = rep("quick", projects=[PROJECT])
    assert r["ready"] and r["next_item"] is None and r["stuck"] == [] and r["hand_off"] == "claudia-relay"
    text = I.render_next(None, r)
    assert "Everything the quick tier needs is set up." in text and "Make something with Claudia: skill claudia-relay" in text
    assert "Works now: stills from Grok's image tool, 2.5D motion with devices" in text
    assert item(r, "openrouter")["need"] == "recommended", "skipping a route never makes the other required in Quick"


def test_an_openrouter_key_adds_lyria_api_stills_and_cheap_clips():
    r = rep("quick", key=KEY)
    assert r["routes"]["stills"] == ["openrouter", "grok-image"] and r["routes"]["clips"] == ["openrouter"]
    assert r["routes"]["song"] == ["upload", "lyria"]
    assert ("Quick tier ready: stills from OpenRouter or Grok's image tool, 2.5D motion with devices plus OpenRouter "
            "clips, the song from your own upload or Lyria, render and master here") in r["unlocked"]
    st.set_setting("suno-plan", "pro")
    st.set_setting("mj-plan", "standard")
    r = rep("quick", key=KEY)
    assert r["routes"]["song"] == ["upload", "suno", "lyria"]
    assert r["routes"]["stills"] == ["openrouter", "midjourney", "grok-image"]


# ---------------------------------------------------------------- Studio: OpenRouter OR Higgsfield
def test_studio_is_ready_with_openrouter_alone():
    r = rep("studio", key=KEY)
    assert r["tiers"]["studio"] == {"ready": True, "missing": []}
    v = item(r, "video")
    assert v["state"] == "done" and v["data"]["via"] == ["OpenRouter"]
    assert "Higgsfield is recommended too: it copies the vocals more reliably" in v["why"]
    hf = item(r, "higgsfield")
    assert hf["state"] == "todo" and hf["need"] == "recommended" and r["next_item"] == "higgsfield"
    assert "OpenRouter already makes the clips; Higgsfield is recommended too" in hf["why"]
    assert ("Studio tier unlocked: sung clips with measured lip sync via OpenRouter, full analysis install"
            in r["unlocked"])


def test_studio_is_ready_with_higgsfield_alone():
    st.set_mark("higgsfield", "done")
    r = rep("studio")
    assert r["tiers"]["studio"]["ready"] and item(r, "video")["data"]["via"] == ["Higgsfield"]
    o = item(r, "openrouter")
    assert o["state"] == "todo" and o["need"] == "recommended"
    assert "Higgsfield already makes the clips; OpenRouter is recommended too: cheaper per second" in o["why"]
    assert "OpenRouter is recommended too: cheaper per second" in item(r, "video")["why"]
    assert any(u.endswith("via Higgsfield, full analysis install") for u in r["unlocked"])
    assert r["routes"]["clips"] == ["higgsfield"] and r["routes"]["song"] == ["upload"], "no Lyria without OpenRouter"
    # a Higgsfield API key counts like the connector
    st.set_mark("higgsfield", "todo")
    r = rep("studio", env={"HIGGSFIELD_API_KEY": True})
    assert r["tiers"]["studio"]["ready"] and item(r, "higgsfield")["state"] == "done"


def test_studio_with_both_routes_names_both_and_the_routing_rule():
    st.set_mark("higgsfield", "done")
    r = rep("studio", key=KEY)
    v = item(r, "video")
    assert v["data"]["via"] == ["OpenRouter", "Higgsfield"] and "after 2 OpenRouter misses" in v["why"]
    assert "via OpenRouter and Higgsfield" in " ".join(r["unlocked"])


def test_studio_with_neither_route_asks_for_one_both_recommended():
    r = rep("studio")
    assert r["tiers"]["studio"]["missing"] == ["video"] and r["next_item"] == "openrouter"
    v = item(r, "video")
    assert v["state"] == "blocked" and v["need"] == "required" and v["blocked_by"] == ["openrouter", "higgsfield"]
    assert "needs OpenRouter or Higgsfield" in v["why"] and "both recommended" in v["why"]
    for rid in I.ROUTES:
        it = item(r, rid)
        assert it["need"] == "recommended" and "studio tier needs OpenRouter or Higgsfield" in it["why"]
    assert "studio needs video (OpenRouter or Higgsfield)" in I.render_status(r)


def test_studio_still_needs_the_full_analysis_install():
    st.set_mark("higgsfield", "done")
    r = rep("studio", tk={"profile": "minimal"}, doc={"deps_full": "skip"})
    assert r["tiers"]["studio"]["missing"] == ["full-profile"] and r["tiers"]["quick"]["ready"]
    assert "song analysis" in item(r, "full-profile")["why"]


def test_the_last_route_left_becomes_required_in_studio_only():
    st.set_mark("higgsfield", "skip")
    r = rep("studio")
    o = item(r, "openrouter")
    assert o["need"] == "required" and "Higgsfield is skipped, so the studio tier needs OpenRouter" in o["why"]
    assert "mark openrouter --skip" not in I.render_next(o, r), "the footer never offers to skip the last route"
    assert item(rep("quick"), "openrouter")["need"] == "recommended"
    st.set_mark("higgsfield", "todo")
    st.set_mark("openrouter", "skip")
    r = rep("studio")
    assert item(r, "higgsfield")["need"] == "required" and item(r, "openrouter")["state"] == "optional"
    # a working route is never "the last one left": a skipped OpenRouter with a valid key still counts
    r = rep("studio", key=KEY)
    assert item(r, "openrouter")["state"] == "done" and item(r, "higgsfield")["need"] == "recommended"


# ---------------------------------------------------------------- Director: + one coding agent (box or home)
def test_director_needs_one_signed_in_agent_on_the_box_or_at_home():
    st.set_mark("higgsfield", "done")
    st.set_setting("coding-agents", "claude")
    r = rep("director", agents=engines(claude={"installed": True, "logged_in": False}))
    assert r["tiers"]["studio"]["ready"] and r["tiers"]["director"]["missing"] == ["agent-claude"]
    assert I.DIRECTOR_NEEDS in item(r, "agent-claude")["why"]
    r = rep("director", agents=engines(claude={"installed": True, "logged_in": True}))
    assert r["tiers"]["director"]["ready"] and "Director tier unlocked: Claude Code logged in on the box" in \
        r["unlocked"]
    # no slop agents here: the user's own computer is the route, and a signed-in agent there is enough
    r = rep("director")
    assert r["tiers"]["director"]["missing"] == ["home-claude"] and I.DIRECTOR_NEEDS in item(r, "home-claude")["why"]
    st.set_mark("home-claude", "done", "Max plan")
    r = rep("director")
    assert r["tiers"]["director"]["ready"] and r["tiers"]["director"]["agents"] == ["claude (home)"]


def test_director_on_higgsfield_only_needs_no_openrouter():
    st.set_mark("higgsfield", "done")
    st.set_mark("home-codex", "done")
    r = rep("director")
    assert r["tiers"]["director"] == {"ready": True, "missing": [], "agents": ["codex (home)"]}
    assert item(r, "openrouter")["need"] == "recommended" and r["hand_off"] == "claudia-relay"


def test_director_without_any_route_lists_both_requirements():
    r = rep("director", agents=engines())
    assert r["tiers"]["director"]["missing"] == ["video", "coding-agents"]


def test_tier_question_says_what_each_tier_needs():
    q, s, d = I.TIER_ASK.split("Studio:")[0], I.TIER_ASK.split("Studio:")[1].split("Director:")[0], \
        I.TIER_ASK.split("Director:")[1]
    assert "needs no account" in q and "image tool" in q and "your own song" in q
    assert "OpenRouter or Higgsfield" in s
    assert "signed in, on my computer or yours" in d and "Gemini" not in d


# ---------------------------------------------------------------- install: probe first, say "ready"
@pytest.mark.parametrize("over,state", [
    ({}, "ready"),
    ({"tk": {"profile": "minimal"}, "doc": {"deps_full": "skip"}}, "minimal"),
    ({"tk": {"profile": "minimal"}, "doc": {"deps_full": "skip"}, "running": [{"pid": 7, "full": True}]},
     "installing"),
    ({"tk": {"installed": False, "profile": "minimal"}, "running": [{"pid": 7, "full": True}]}, "installing"),
    ({"tk": {"installed": False, "profile": "minimal"}}, "missing"),
    ({"doc": {"deps_full": "fail"}}, "broken"),
])
def test_install_summary(over, state):
    r = rep("quick", **over)
    assert r["install"]["state"] == state, r["install"]
    if state == "ready":
        assert "nothing to install" in r["install"]["text"] and "15-25" not in r["install"]["text"]
    if state in ("minimal", "missing", "broken"):
        assert "about 5 min" in r["install"]["text"] and "15-25" not in r["install"]["text"]   # 2-3 min measured


# ---------------------------------------------------------------- through the real router
@pytest.fixture
def router(monkeypatch):
    monkeypatch.setattr(cli, "MODULES", ["slop.core_cli", "slop.onboard.cli"])
    monkeypatch.setattr(probes, "doctor", lambda: {"ok": True, "fails": [], "warns": [], "passed": 9,
                                                   "deps_full": "ok"})
    monkeypatch.setattr(probes, "agents", lambda: {"available": False, "engines": {}})
    monkeypatch.setattr(probes, "gpu", lambda: {"available": False})
    monkeypatch.setattr(probes, "setup_running", lambda: [])
    monkeypatch.setattr(probes, "toolkit", lambda: data()["tk"])


def run(capsys, *argv) -> tuple[int, dict]:
    try:
        rc = cli.main(["--json", *argv])
    except SystemExit as e:
        rc = e.code
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_next_json_carries_routes_and_install(capsys, router):
    run(capsys, "onboard", "set", "tier", "quick")
    rc, out = run(capsys, "onboard", "next", "--offline")
    assert rc == 0 and out["ready"] and out["install"]["state"] == "ready"
    assert out["routes"]["stills"] == ["grok-image"] and out["routes"]["clips"] == []
    assert any(u.startswith("Quick tier ready: stills from Grok's image tool") for u in out["new_unlocks"])
    rc, out = run(capsys, "onboard", "status", "--offline", "--group", "connectors")
    assert rc == 0 and [i["id"] for i in out["items"]] == ["higgsfield", "drive", "video"]
    assert out["routes"]["song"] == ["upload"] and "Works now: stills from Grok's image tool" in out["text"]


def test_skipping_both_routes_warns_in_studio_only(capsys, router):
    run(capsys, "onboard", "set", "tier", "quick")
    for rid in I.ROUTES:
        rc, out = run(capsys, "onboard", "mark", rid, "--skip")
        assert rc == 0 and "warn" not in out, "Quick needs neither"
    for rid in I.ROUTES:
        run(capsys, "onboard", "mark", rid, "--todo")
    run(capsys, "onboard", "set", "tier", "studio")
    rc, out = run(capsys, "onboard", "mark", "openrouter", "--skip")
    assert rc == 0 and "warn" not in out, "Higgsfield can still come"
    rc, out = run(capsys, "onboard", "mark", "hf", "--skip")
    assert rc == 0 and "both are skipped" in out["warn"]
    parser = cli.build_parser()
    for c in ("slop onboard mark openrouter --todo", "slop onboard set tier quick"):
        assert c in out["warn"]
        parser.parse_args(util.hoist_global_flags(shlex.split(c)[1:]))
    rc, out = run(capsys, "onboard", "next", "--offline")
    assert not out["ready"] and not out["all_set"]
    rc, out = run(capsys, "onboard", "mark", "higgsfield", "--done")
    assert rc == 0
    rc, out = run(capsys, "onboard", "next", "--offline")
    assert out["ready"], "Higgsfield alone opens Studio"


def test_derived_items_cannot_be_marked_done(capsys, router):
    rc, out = run(capsys, "onboard", "mark", "clips", "--done")
    assert rc == 1 and "video follows openrouter or higgsfield" in out["error"] and "--skip" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "lyria", "--done")
    assert rc == 1 and "lyria follows openrouter: it is done as soon as that is" in out["error"]
    rc, out = run(capsys, "onboard", "mark", "toolkit", "--done")
    assert rc == 1 and "checked automatically" in out["error"]
