"""Adversarial review of the onboard tier-readiness polish (e2e/QUICK-E2E.md; owner decision 2026-10-02).

- An EXPIRED OpenRouter key still passes the free key check (valid: true), but it cannot make a call: it is not a
  clip route, so Studio is not ready on it, and Lyria / API stills / `routes` do not count it.
- A full install that is broken AND being re-run right now says "installing" (never a second `setup.sh --full`).
- Quick with both routes skipped: video, API stills and Lyria are declined (optional), not "blocked" forever;
  Studio keeps `video` blocked, so its `stuck` reason still names both skips.
- A FREE-tier OpenRouter key: clips and API stills through it carry a warning (paid models fail until credits).
- The last route left names the way back to the other one; every command in a warning parses.
Probe results are fed in directly: no network, no child processes, no spend."""
from __future__ import annotations

import json
import re
import shlex

import pytest

from slop import cli, util
from slop.onboard import items as I
from slop.onboard import probes
from slop.onboard import state as st

NO_KEY = {"present": False, "checked": False, "valid": False}
KEY = {"present": True, "checked": True, "valid": True, "limit": 25.0, "limit_remaining": 20.0, "usage": 5.0}
EXPIRED = {**KEY, "expires_at": "2026-09-29T00:00:00Z", "days_left": -3.0}


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
    """A box with the toolkit (full profile) installed and NO account."""
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


def rep(tier="quick", **over):
    st.set_setting("tier", tier)
    return I.report(tier=tier, data=data(**over))


def item(r, iid):
    return next(i for i in r["items"] if i["id"] == iid)


def parses(cmd: str) -> None:
    cli.build_parser().parse_args(util.hoist_global_flags(shlex.split(cmd)[1:]))


# ---------------------------------------------------------------- an expired key is no route
def test_an_expired_key_does_not_open_studio_or_count_as_a_route():
    r = rep("studio", key=EXPIRED)
    o = item(r, "openrouter")
    assert o["state"] == "error" and "EXPIRED" in o["why"] and r["next_item"] == "openrouter"
    assert not r["tiers"]["studio"]["ready"] and r["tiers"]["studio"]["missing"] == ["video"]
    assert item(r, "video")["state"] == "blocked" and item(r, "api-images")["state"] == "blocked"
    assert item(r, "lyria")["state"] != "done"
    assert r["routes"]["clips"] == [] and "openrouter" not in r["routes"]["stills"] and \
        "lyria" not in r["routes"]["song"]
    assert not any(u.startswith("Studio tier unlocked") for u in r["unlocked"])
    # the same key before its expiry date is a route
    r = rep("studio", key={**EXPIRED, "days_left": 3.0})
    assert r["tiers"]["studio"]["ready"] and r["routes"]["clips"] == ["openrouter"]


def test_an_expired_key_with_higgsfield_skipped_is_the_required_route_to_renew():
    st.set_mark("higgsfield", "skip")
    r = rep("studio", key=EXPIRED)
    o = item(r, "openrouter")
    assert o["state"] == "error" and o["need"] == "required" and "expired" in o["do"]
    assert r["next_item"] == "openrouter" and "mark openrouter --skip" not in I.render_next(o, r)


# ---------------------------------------------------------------- the full install re-run
def test_a_broken_full_install_being_rerun_is_installing_not_broken():
    r = rep("studio", doc={"deps_full": "fail"}, running=[{"pid": 7, "full": True}])
    fp = item(r, "full-profile")
    assert fp["state"] == "error" and fp.get("running") and "running again" in fp["why"]
    assert r["install"]["state"] == "installing", "never announce (or start) a second setup.sh --full"
    assert "full-profile" in r["running"]
    todo = [i["id"] for i in r["items"] if i["state"] in ("todo", "error") and i["id"] != "full-profile"]
    assert I.pick_next(r["items"], exclude=todo, order=r["priority"]) is None, "a running install is passed over"
    # not running: broken, and the re-run is the step
    r = rep("studio", doc={"deps_full": "fail"})
    assert r["install"]["state"] == "broken" and not item(r, "full-profile").get("running")


# ---------------------------------------------------------------- Quick: declined, not blocked
def test_quick_with_both_routes_skipped_declines_what_follows_from_them():
    for rid in I.ROUTES:
        st.set_mark(rid, "skip")
    r = rep("quick")
    for iid in ("video", "api-images", "lyria"):
        it = item(r, iid)
        assert it["state"] == "optional" and it.get("skipped"), it
        assert "blocked_by" not in it
    assert "both skipped" in item(r, "video")["why"] and "GenerateImage" in item(r, "api-images")["why"]
    assert r["counts"]["blocked"] == sum(1 for i in r["items"] if i["state"] == "blocked")
    assert not {"video", "api-images", "lyria"} & set(I.extras_text(r).replace(",", " ").replace(";", " ").split())
    # Studio keeps video blocked (and required), so `stuck` names both skips
    r = rep("studio")
    v = item(r, "video")
    assert v["state"] == "blocked" and v["need"] == "required" and not v.get("skipped")
    # only OpenRouter skipped in Quick: Higgsfield can still bring API stills and clips; Lyria is declined
    st.set_mark("higgsfield", "todo")
    r = rep("quick")
    assert item(r, "video")["state"] == "blocked" and item(r, "api-images")["state"] == "blocked"
    assert item(r, "lyria")["state"] == "optional" and item(r, "lyria").get("skipped")


# ---------------------------------------------------------------- free-tier key
def test_a_free_tier_key_warns_on_clips_and_api_stills():
    free = {**KEY, "is_free_tier": True, "limit": None}
    r = rep("studio", key=free)
    assert "FREE tier" in item(r, "openrouter")["warn"]
    assert "clips through it fail until the user adds credits" in item(r, "video")["warn"]
    assert "API stills through it fail" in item(r, "api-images")["warn"]
    st.set_mark("higgsfield", "done")
    r = rep("studio")
    assert "warn" not in item(r, "video"), "no OpenRouter in the route: nothing to warn about"
    r = rep("studio", key=KEY)
    assert "warn" not in item(r, "video")


# ---------------------------------------------------------------- the last route left, and the words
def test_the_last_route_left_names_the_way_back_to_the_other_one():
    st.set_mark("higgsfield", "skip")
    r = rep("studio")
    o = item(r, "openrouter")
    assert o["need"] == "required" and "slop onboard mark higgsfield --todo" in o["why"]
    parses("slop onboard mark higgsfield --todo")
    st.set_mark("higgsfield", "todo")
    st.set_mark("openrouter", "skip")
    hf = item(rep("studio"), "higgsfield")
    assert hf["need"] == "required" and "slop onboard mark openrouter --todo" in hf["why"]


def test_quick_route_words_match_the_need():
    r = rep("quick")
    for rid in I.ROUTES:
        it = item(r, rid)
        assert it["need"] == "recommended" and "recommended, not required" in it["why"]
        assert "optional:" not in it["why"]


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


def test_every_command_in_the_both_skipped_warning_parses(capsys, router):
    run(capsys, "onboard", "set", "tier", "director")
    run(capsys, "onboard", "mark", "higgsfield", "--skip")
    rc, out = run(capsys, "onboard", "mark", "openrouter", "--skip")
    assert rc == 0 and "both are skipped" in out["warn"] and "director tier" in out["warn"]
    cmds = re.findall(r"slop onboard [a-z]+ [a-z-]+ [a-z-]+", out["warn"])
    assert {"slop onboard mark higgsfield --todo", "slop onboard mark openrouter --todo",
            "slop onboard set tier quick"} <= set(cmds)
    for c in cmds:
        parses(c)


def test_status_json_keeps_its_contract_with_routes_and_install(capsys, router):
    rc, out = run(capsys, "onboard", "status", "--offline")
    assert rc == 0 and set(out["routes"]) == {"stills", "clips", "song", "text"}
    assert set(out["install"]) == {"state", "text"} and out["install"]["state"] in (
        "ready", "installing", "minimal", "broken", "missing")
    assert len(out["items"]) == len(I.CATALOG) and {i["id"] for i in out["items"]} == set(I.ITEM_IDS)
