"""slop update: the newest release from the toolkit's origin (a daily check), one quiet reminder per new release on
`relay read`, and the one-step update (fetch, check out the newest tag, notes from CHANGELOG.md, the skills step for
Grok). A real git origin in a temp folder; the setup check and the brief refresh are skipped."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from slop import update as U
from slop.config import SlopError


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return r.stdout


def release(work: Path, version: str, note: str) -> None:
    (work / "slop").mkdir(parents=True, exist_ok=True)
    (work / "slop" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    log = work / "CHANGELOG.md"
    old = log.read_text() if log.exists() else "# Changelog\n"
    head, _, rest = old.partition("\n")
    log.write_text(f"{head}\n\n## {version}\n- {note}\n{rest}")
    git(work, "add", "-A")
    git(work, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", version)
    git(work, "tag", "v" + version)
    git(work, "push", "-q", "origin", "HEAD:main", "--tags")


@pytest.fixture()
def box(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    git(work, "remote", "add", "origin", str(origin))
    release(work, "0.2.5", "the tunnel fix")
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    git(checkout, "checkout", "-q", "v0.2.5")
    monkeypatch.setenv("SLOP_UPDATE_ROOT", str(checkout))
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_UPDATE_SKIP_SETUP", "1")
    monkeypatch.delenv("SLOP_UPDATE_CHECK", raising=False)
    monkeypatch.setattr(U, "_production_state", lambda: None)
    monkeypatch.setattr(U, "_refresh_brief", lambda: {"skipped": True})
    return {"work": work, "checkout": checkout}


def test_check_finds_a_newer_release_and_caches_it_for_a_day(box):
    r = U.check()
    assert r["current"] == "0.2.5" and r["latest"] == "0.2.5" and not r["newer"] and not r["cached"]
    release(box["work"], "0.2.6", "updates")
    assert U.check()["cached"] and not U.check()["newer"], "the daily answer is reused"
    r = U.check(force=True)
    assert r["latest"] == "0.2.6" and r["newer"] and not r["cached"]


def test_the_reminder_comes_once_per_new_release(box, monkeypatch):
    release(box["work"], "0.2.6", "updates")
    U.check(force=True)
    first = U.reminder()
    assert first and first["latest"] == "0.2.6" and "Say update" in first["line"]
    assert U.reminder() is None, "shown once"
    release(box["work"], "0.2.7", "more")
    U.check(force=True)
    assert U.reminder()["latest"] == "0.2.7", "a newer release reminds again"
    monkeypatch.setenv("SLOP_UPDATE_CHECK", "0")
    release(box["work"], "0.2.8", "even more")
    U.check(force=True)
    assert U.reminder() is None, "SLOP_UPDATE_CHECK=0 turns it off"


def test_apply_checks_out_the_newest_release_with_its_notes(box):
    release(box["work"], "0.2.6", "updates in one step")
    release(box["work"], "0.2.7", "a later fix")
    out = U.cmd_apply(type("A", (), {"to": None, "force": False})())
    assert out["updated"] and out["from"] == "0.2.5" and out["to"] == "0.2.7"
    assert out["notes"] == ["- a later fix", "- updates in one step"]
    assert U.current() == (0, 2, 7) and git(box["checkout"], "describe", "--tags").strip() == "v0.2.7"
    assert "recipe.json" in out["next"] and "byte for byte" in out["next"]
    st = json.loads(U.state_path().read_text())
    assert st["latest"] == st["notified"] == "0.2.7", "no reminder for what is installed"
    again = U.cmd_apply(type("A", (), {"to": None, "force": False})())
    assert again["updated"] is False and "nothing to update" in again["text"]


def test_apply_waits_for_the_production_and_keeps_local_changes(box, monkeypatch):
    release(box["work"], "0.2.6", "updates")
    monkeypatch.setattr(U, "_production_state", lambda: "working")
    with pytest.raises(SlopError, match="Opus is working"):
        U.cmd_apply(type("A", (), {"to": None, "force": False})())
    monkeypatch.setattr(U, "_production_state", lambda: "idle")
    (box["checkout"] / "slop" / "__init__.py").write_text('__version__ = "0.2.5"\n# edited\n')
    with pytest.raises(SlopError, match="local changes"):
        U.cmd_apply(type("A", (), {"to": None, "force": False})())
    assert U.current() == (0, 2, 5)


def test_notes_since_takes_only_newer_versions():
    text = "# Changelog\n\n## 0.2.7\n- c\n\n## 0.2.6\n- b\n- b2\n\n## 0.2.5\n- a\n"
    assert U.notes_since(text, (0, 2, 5)) == ["- c", "- b", "- b2"]
    assert U.notes_since(text, (0, 2, 7)) == []
