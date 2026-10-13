"""Onboarding state ($SLOP_HOME/onboard.json): marks, settings, the agents preference API, unlock memory, the lock,
and the no-secrets rule. No network."""
from __future__ import annotations

import json
import os
import time

import pytest

from slop.config import SlopError
from slop.onboard import state as st

FAKE_KEY = "sk-or-v1-THISISAFAKEKEYFORTESTSONLY0123"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    return tmp_path


def test_empty_state_needs_no_file():
    d = st.load()
    assert d["marks"] == {} and d["settings"] == {} and d["tier"] is None and "agents" not in d
    assert not st.path().exists()


def test_marks_and_settings_round_trip_and_keep_unknown_keys():
    st.update(lambda d: d.update(other_module={"x": 1}))          # another module's own key
    st.set_mark("higgsfield", "done", "  plan:   creator \n")
    st.set_setting("tier", "studio")
    st.set_setting("suno-plan", "PRO")
    d = json.loads(st.path().read_text(encoding="utf-8"))
    assert d["marks"]["higgsfield"]["state"] == "done" and d["marks"]["higgsfield"]["note"] == "plan: creator"
    assert d["tier"] == "studio" and d["settings"]["suno_plan"] == "pro"
    assert d["other_module"] == {"x": 1}, "a write must keep keys it does not know"
    assert d["version"] == 1 and d["updated"]
    st.set_mark("higgsfield", "todo")
    assert "higgsfield" not in st.load()["marks"]
    st.set_setting("suno-plan", None)
    assert "suno_plan" not in st.load()["settings"]


@pytest.mark.parametrize("bad", [FAKE_KEY, "token eyJhbGciOiJIUzI1NiJ9abcdef", "x" * 40,
                                 "-----BEGIN PRIVATE KEY-----", "ghp_" + "a1" * 10])
def test_a_note_that_looks_like_a_secret_is_refused_and_nothing_is_written(bad):
    with pytest.raises(SlopError, match="secret"):
        st.set_mark("home-claude", "done", f"logged in {bad}")
    assert not st.path().exists()


@pytest.mark.parametrize("bad,why", [
    ("signed in as bob.smith@example.com", "account"),
    ("signed in as bob.smith@example.com password hunter2", "account"),
    ("password hunter2", "password"),
    ("pw: Tr0ub4dor&3", "pw"),
    ("otp 123456 worked", "otp"),
    ("the token is abc", "token"),
    ("Passcode 4711", "Passcode"),
])
def test_a_note_with_an_account_address_or_a_password_is_refused(bad, why):
    with pytest.raises(SlopError, match=why) as e:
        st.set_mark("home-codex", "done", bad)
    assert "NOT saved" in str(e.value) and "hunter2" not in str(e.value) and not st.path().exists()


@pytest.mark.parametrize("ok", [
    "Max plan, Windows laptop, approved Always allow",
    "studio-tier-with-higgsfield-creator-plan",          # hyphen-joined words are not a token
    "used claude setup-token on the laptop",              # the command's name, not a token
    "key given through the secure secret card",
    "RTX 3090 Ti 24 GB, pinned to GPU 1",
])
def test_ordinary_notes_pass(ok):
    st.set_mark("home-claude", "done", ok)
    assert st.load()["marks"]["home-claude"]["note"] == ok


def test_a_long_note_is_cut_at_a_whole_word_then_checked():
    note = "plan pro on the studio laptop " * 12                     # 360 characters of plain words
    st.set_mark("home-claude", "done", note)
    saved = st.load()["marks"]["home-claude"]["note"]
    flat = " ".join(note.split())
    assert len(saved) <= st.NOTE_MAX and flat.startswith(saved) and flat[len(saved)] == " ", "never half a word"


def test_coding_agents_setting():
    assert st.coding_agents() is None
    st.set_setting("coding-agents", "ChatGPT, Claude and chatgpt")
    assert st.coding_agents() == ["codex", "claude"], "main first, no repeats, plan words map to engines"
    st.set_setting("coding-agents", "none")
    assert st.coding_agents() == []
    with pytest.raises(SlopError, match="claude, codex"):
        st.set_setting("coding-agents", "copilot")
    assert st.coding_agents() == [], "a bad value changes nothing"
    st.set_setting("coding-agents", None)
    assert st.coding_agents() is None


def test_settings_are_validated():
    with pytest.raises(SlopError, match="one of"):
        st.set_setting("suno-plan", "platinum")
    with pytest.raises(SlopError, match="one of"):
        st.set_setting("tier", "ultra")
    with pytest.raises(SlopError, match="unknown setting"):
        st.set_setting("password", "x")
    with pytest.raises(SlopError, match="3-40 letters"):
        st.set_setting("mj-profile", "has space")
    st.set_setting("mj-profile", "--profile abc123x")               # pasted with the flag
    assert st.load()["settings"]["mj_profile"] == "abc123x"
    assert st.mask("abc123x") == "ab… (7 characters)" and st.mask(None) is None


def test_broken_file_says_how_to_recover():
    st.path().parent.mkdir(parents=True)
    st.path().write_text("{not json", encoding="utf-8")
    with pytest.raises(SlopError, match=r"mv .*onboard\.json"):
        st.load()
    st.path().write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(SlopError, match="one JSON object"):
        st.load()


def test_wrong_types_inside_are_reset_not_fatal():
    st.path().parent.mkdir(parents=True)
    st.path().write_text(json.dumps({"marks": [], "settings": "x", "tier": "mega"}), encoding="utf-8")
    d = st.load()
    assert d["marks"] == {} and d["settings"] == {} and d["tier"] is None


def test_the_agents_preference_is_read_from_the_agents_modules_key():
    """slop.agents owns onboard.json "agents" ({"use": {role: engine}}); onboarding only reads it and keeps it."""
    assert st.agent_use("director") is None
    st.update(lambda d: d.update(agents={"use": {"director": "codex", "images": "codex"}, "updated": "x"}))
    assert st.agent_use("director") == "codex" and st.agent_use("review") is None
    st.set_mark("higgsfield", "done")
    assert st.load()["agents"]["use"] == {"director": "codex", "images": "codex"}, "a mark keeps their key"
    st.update(lambda d: d["agents"]["use"].update(director="nonsense"))
    assert st.agent_use("director") is None
    st.update(lambda d: d.update(agents="broken"))
    assert st.agent_use("director") is None


def test_interop_with_slop_agents_use():
    """When this toolkit has slop.agents: its writer and ours share onboard.json without losing each other's keys."""
    prefs = pytest.importorskip("slop.agents.prefs")
    st.set_mark("higgsfield", "done", "creator plan")
    prefs.set_use("claude", "director")
    assert st.agent_use("director") == "claude"
    assert st.load()["marks"]["higgsfield"]["note"] == "creator plan"
    st.set_setting("tier", "director")
    assert prefs.get_use().get("director") == "claude"


def test_unlocks_are_new_only_once():
    new = st.record_unlocks(["tier:quick", "item:openrouter"])
    assert set(new) == {"tier:quick", "item:openrouter"}
    mtime = st.path().stat().st_mtime_ns
    assert st.record_unlocks(["tier:quick", "item:openrouter"]) == {}
    assert st.path().stat().st_mtime_ns == mtime, "nothing new: the file is not rewritten"
    assert set(st.record_unlocks(["tier:quick", "tier:studio"])) == {"tier:studio"}


def test_lock_busy_then_stale(monkeypatch):
    st.path().parent.mkdir(parents=True)
    lock = st.path().with_name("onboard.json.lock")
    lock.write_text("123")
    monkeypatch.setattr(st, "LOCK_STALE_S", 3600.0)   # a VM clock correction must not make a fresh lock look stale
    with pytest.raises(SlopError, match="held by another slop command"):
        with st._locked(timeout=0.2):
            pass
    old = time.time() - 2 * 3600
    os.utime(lock, (old, old))
    st.set_mark("drive", "skip")                                   # a stale lock is taken over
    assert st.load()["marks"]["drive"]["state"] == "skip" and not lock.exists()
