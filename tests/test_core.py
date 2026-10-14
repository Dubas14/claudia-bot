"""Core module tests: new / status / gate / decide / runs / spend / doctor / util. No network, no spend.

Every HTTP call is mocked (slop.util.http_json) except one test that talks to a local http.server.
The router is restricted to the core module so other modules' work-in-progress cannot break these tests.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from slop import cli, core_cli, doctor, util
from slop.config import SlopError

FAKE_KEY = "sk-or-v1-THISISAFAKEKEYFORTESTS0123456789"
ALL_MODULES = list(cli.MODULES)  # before the fixture restricts the router to core


# ---------------------------------------------------------------- fixtures / helpers
@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    home, projects = tmp_path / "home", tmp_path / "projects"
    monkeypatch.setenv("SLOP_HOME", str(home))
    monkeypatch.setenv("SLOP_PROJECTS", str(projects))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY", "SLOP_PROFILE", "SLOP_BROWSER_CHANNEL", "HIGGSFIELD_API_KEY",
              "ARENA_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "MODULES", ["slop.core_cli"])
    return {"home": home, "projects": projects, "tmp": tmp_path}


def run(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main(["--json", *argv])
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


def make_wav(path: Path, seconds: float = 0.2, sr: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * 2 * int(sr * seconds))


def new_project(capsys, name="my-song", *extra) -> Path:
    rc, out = run(capsys, "new", name, *extra)
    assert rc == 0 and out["ok"], out
    return Path(out["project"])


def fake_http(responses: dict):
    """responses: {url_suffix: (status, json)}; records calls."""
    calls = []

    def _http(url, headers=None, timeout=20, method="GET"):
        calls.append({"url": url, "headers": dict(headers or {})})
        for suf, (st, data) in responses.items():
            if url.endswith(suf):
                return st, data, (None if st == 200 else f"HTTP {st}")
        return 0, None, "network error: test"
    _http.calls = calls
    return _http


KEY_OK = {"data": {"label": "sk-or-v1-abc...xyz", "limit": 80, "limit_remaining": 79.5, "usage": 0.5,
                   "usage_daily": 0.25, "usage_weekly": 0.5, "usage_monthly": 0.5, "is_free_tier": False,
                   "limit_reset": None, "creator_user_id": "user_123", "workspace_id": "ws_9"}}
CREDITS_OK = {"data": {"total_credits": 100, "total_usage": 30.25}}


# ---------------------------------------------------------------- new
def test_new_creates_contract_project(capsys, env):
    p = new_project(capsys, "my-song", "--title", "My Song")
    assert p == (env["projects"] / "my-song").resolve()
    proj = json.loads((p / "project.json").read_text())
    for k in ("name", "title", "tier", "song", "fps", "size", "lead", "look", "mj", "models", "budget", "gates"):
        assert k in proj, k
    assert proj["name"] == "my-song" and proj["title"] == "My Song" and proj["tier"] == "quick"
    assert proj["song"] == "audio/song.wav" and proj["fps"] == 24 and proj["size"] == [1920, 1080]
    assert {"canon", "far", "possessive"} <= set(proj["lead"]) and proj["lead"]["canon"] == ""
    assert "pin" in proj["lead"]["note"] and "face image" in proj["lead"]["note"]
    assert proj["mj"]["profile"] == "" and "--profile" not in proj["mj"]["params"]
    assert proj["look"]["accent"] == "#D97757" and set(proj["look"]["fonts"]) == {"lyric", "micro", "display"}
    assert set(proj["models"]) == {"image", "video", "video_cheap", "edit", "pin"} and proj["models"]["pin"] is False
    assert proj["budget"] == core_cli.TIER_BUDGETS["quick"]
    assert proj["gates"] == {"board_approved": False, "prompts_approved": False, "v1_approved": False}
    for d in core_cli.DIRS:
        assert (p / d).is_dir(), d
    for f in ("DECISIONS.md", "RUNS.md", "README.md", "lyrics/lyrics.txt", "lyrics/display.txt", "lyrics/README.md",
              "BRIEF.md", "PLAN.md", "NOTES.md", "bible/LEAD.md", "lyrics/SOURCES.md"):
        text = (p / f).read_text()
        assert "{{" not in text, f
    assert "My Song" in (p / "README.md").read_text()
    assert "project created (tier quick)" in (p / "DECISIONS.md").read_text()
    assert core_cli.RUNS_HEADER.splitlines()[0] in (p / "RUNS.md").read_text()
    # templates hold only comments/examples: no lyric lines yet
    assert util.read_lyric_lines(p / "lyrics/lyrics.txt") == []
    assert util.read_lyric_lines(p / "lyrics/display.txt") == []


@pytest.mark.parametrize("tier", ["quick", "studio", "director"])
def test_new_tier_budgets(capsys, tier):
    p = new_project(capsys, f"song-{tier}", "--tier", tier)
    proj = json.loads((p / "project.json").read_text())
    assert proj["tier"] == tier and proj["budget"] == core_cli.TIER_BUDGETS[tier]


def test_new_is_idempotent_and_non_destructive(capsys):
    p = new_project(capsys, "again", "--title", "First")
    proj = json.loads((p / "project.json").read_text())
    proj["title"] = "Edited"
    (p / "project.json").write_text(json.dumps(proj))
    (p / "README.md").unlink()
    (p / "lyrics/lyrics.txt").write_text("hello world\n")
    rc, out = run(capsys, "new", "again", "--title", "Other", "--tier", "director")
    assert rc == 0 and out["created"] is False
    assert out["files_added"] == ["README.md"]
    assert any("kept the existing title" in n for n in out["notes"])
    assert any("kept the existing tier" in n for n in out["notes"])
    proj2 = json.loads((p / "project.json").read_text())
    assert proj2["title"] == "Edited" and proj2["tier"] == "quick"
    assert (p / "lyrics/lyrics.txt").read_text() == "hello world\n"
    assert "Edited" in (p / "README.md").read_text()


@pytest.mark.parametrize("bad", ["My-Song", "_x", "a b", "", "x" * 64, "../evil", "a_b"])
def test_new_rejects_bad_names(capsys, env, bad):
    rc, out = run(capsys, "new", bad)
    assert rc == 1 and out["ok"] is False and "NAME" in out["error"]
    assert not env["projects"].exists() or not any(env["projects"].iterdir())


def test_new_refuses_foreign_folder(capsys, env):
    d = env["projects"] / "taken"
    d.mkdir(parents=True)
    (d / "notes.txt").write_text("not a project")
    rc, out = run(capsys, "new", "taken")
    assert rc == 1 and "not a slop project" in out["error"]
    assert not (d / "project.json").exists()


def test_new_with_root_gives_path_reference(capsys, env):
    root = env["tmp"] / "elsewhere"
    rc, out = run(capsys, "new", "side", "--root", str(root))
    assert rc == 0 and Path(out["project"]).parent == root.resolve()
    assert f"slop --project {root.resolve() / 'side'}" in out["text"]  # --project must be the path, not the bare name
    rc, st = run(capsys, "--project", out["project"], "status")
    assert str(root.resolve()) in next(s for s in st["stages"] if s["stage"] == "song")["cmd"]
    rc, st = run(capsys, "--project", out["project"], "status")
    assert rc == 0 and st["name"] == "side"


# ---------------------------------------------------------------- status
def test_status_requires_a_project(capsys):
    rc, out = run(capsys, "status")
    assert rc == 1 and out["ok"] is False and "--project" in out["error"]
    rc, out = run(capsys, "--project", "nope", "status")
    assert rc == 1 and "slop new" in out["error"]


def test_status_flags_after_subcommand(capsys):
    new_project(capsys, "flags")
    rc = cli.main(["status", "--json", "-p", "flags"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["name"] == "flags"
    rc = cli.main(["--json", "-p", "flags", "status"])
    assert rc == 0 and json.loads(capsys.readouterr().out)["name"] == "flags"


T0 = time.time() - 10_000  # explicit mtimes: every stage file is "written" later than what it depends on


def at(path: Path, seconds: float) -> Path:
    os.utime(path, (T0 + seconds, T0 + seconds))
    return path


def write(path: Path, text: str, t: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return at(path, t) if t is not None else path


def fill_brief(p: Path) -> None:
    text = (p / "BRIEF.md").read_text(encoding="utf-8")
    (p / "BRIEF.md").write_text(text.replace("\n>\n", '\n> 2026-10-01: "make it feel like a launch, loud and dense"\n', 1),
                                encoding="utf-8")


LYRICS = "[Verse 1]\nladies gentlemen agents\n\nwe shipped it plus twenty five percent\n"
WORDS = {"words": [{"i": i} for i in range(7)], "gaps": [{"t0": 1, "t1": 2.5}],
         "lines": [{"line": 0, "text": "ladies gentlemen agents"},
                   {"line": 1, "text": "we shipped it plus twenty five percent"}]}


def analysed_project(capsys, name: str, tier: str = "quick") -> Path:
    """A project with brief, song, lyrics, analysis and validated display (mtimes in dependency order)."""
    p = new_project(capsys, name, "--tier", tier)
    fill_brief(p)
    make_wav(p / "audio/song.wav")
    at(p / "audio/song.wav", 10)
    write(p / "lyrics/lyrics.txt", LYRICS, 10)
    for f in ("beats", "hits"):
        write(p / f"analysis/{f}.json", "{}", 20)
    write(p / "analysis/words.json", json.dumps(WORDS), 20)
    write(p / "lyrics/display.txt", "Ladies. Gentlemen. *Agents.*\nWe shipped it +25%|4\n", 30)
    write(p / "analysis/lyrics-display.json", "[]", 31)
    return p


def stages_of(capsys, name: str) -> tuple[str | None, dict, dict]:
    rc, st = run(capsys, "-p", name, "status")
    assert rc == 0, st
    return (st["next"] or {}).get("stage"), st, {s["stage"]: s for s in st["stages"]}


def export_assets(p: Path, t: float) -> None:
    for n in ("beats", "lyrics", "shots", "edl", "plates"):
        write(p / f"engine/assets/{n}.js", f"window.X_{n} = {{}};", t)


def test_status_walks_the_stages(capsys, monkeypatch):
    p = new_project(capsys, "walk")
    monkeypatch.setenv("SLOP_PROJECT", "walk")

    def nxt():
        rc, st = run(capsys, "status")
        assert rc == 0
        stages = {s["stage"]: s for s in st["stages"]}
        return (st["next"] or {}).get("stage"), st, stages

    stage, st, stages = nxt()
    assert stage == "brief" and "verbatim" in st["next"]["do"].lower() and "--project walk brief " in st["next"]["cmd"]
    assert core_cli.brief_ask(p) == ""  # the template's guidance and empty quote marker do not count
    fill_brief(p)
    stage, st, stages = nxt()
    assert stage == "song" and "--project walk" in st["next"]["cmd"] and stages["brief"]["done"]
    assert st["next"]["cmd_available"] is False  # only core is registered in this test
    (p / "audio/upload.mp3").write_bytes(b"ID3")
    stage, st, stages = nxt()
    assert "found audio/upload.mp3" in stages["song"]["detail"]
    make_wav(p / "audio/song.wav")
    at(p / "audio/song.wav", 10)
    stage, st, stages = nxt()
    assert stage == "lyrics"
    tpl_lyrics = (p / "lyrics/lyrics.txt").read_text()
    write(p / "lyrics/lyrics.txt", tpl_lyrics + LYRICS, 10)
    stage, st, stages = nxt()
    assert stage == "analysis" and stages["lyrics"]["done"] and "2 lyric lines" in stages["lyrics"]["detail"]
    for f in ("beats", "hits"):
        write(p / f"analysis/{f}.json", "{}", 20)
    write(p / "analysis/words.json", json.dumps(WORDS), 20)
    stage, st, stages = nxt()
    assert stages["analysis"]["done"] and "7 aligned words, 1 gaps" in stages["analysis"]["detail"]
    assert stage == "display" and st["next"]["cmd"].endswith("lyrics display --init --force")  # template = notes only
    write(p / "lyrics/display.txt", "Ladies. Gentlemen. *Agents.*\n", 30)
    stage, st, stages = nxt()
    assert stage == "display" and "must" in stages["display"]["detail"]
    write(p / "lyrics/display.txt", "Ladies. Gentlemen. *Agents.*\n[a note]\nWe shipped it +25%|4\n", 30)
    stage, st, stages = nxt()
    assert stage == "display" and "not validated" in stages["display"]["detail"]
    assert st["next"]["cmd"].endswith("lyrics display")
    write(p / "analysis/lyrics-display.json", "[]", 31)
    stage, st, stages = nxt()
    assert stages["display"]["done"] and stage == "board"  # taste optional; quick tier without lead shots: lead optional
    assert stages["taste"]["optional"] and not stages["taste"]["done"] and "taste serve" in stages["taste"]["cmd"]
    assert stages["lead"]["optional"] and not stages["lead"]["done"]
    assert st["next"]["cmd"].endswith("board draft")
    shots = {"version": 1, "shots": [{"id": "s001", "lead_on_screen": True}, {"id": "s002"}]}
    write(p / "board/shots.json", json.dumps(shots), 40)
    stage, st, stages = nxt()
    assert stage == "lead" and "1 shots have the lead" in stages["lead"]["detail"]  # the board put her on screen
    assert 'lead --canon "TEXT"' in st["next"]["cmd"]
    rc, out = run(capsys, "lead", "--canon", "a woman in her mid-twenties with pale skin", "--far", "a young woman")
    assert rc == 0 and out["changed"] == ["canon", "far"]
    stage, st, stages = nxt()
    assert stages["lead"]["done"] and stage == "board" and st["next"]["cmd"].endswith("board audit")
    write(p / "board/audit.json", json.dumps({"ok": False}), 41)
    stage, st, stages = nxt()
    assert "FAILED" in stages["board"]["detail"]
    write(p / "board/audit.json", json.dumps({"ok": True}), 41)
    stage, st, stages = nxt()
    assert stage == "gate:board" and st["next"]["cmd"].endswith("gate board --approve")
    assert "board sheet" in st["next"]["do"]
    assert run(capsys, "gate", "board", "--approve")[0] == 0
    stage, st, stages = nxt()
    assert stage == "prompts" and st["next"]["cmd"].endswith("plates book")
    write(p / "plates/prompts.md", "# prompts\n", 50)
    assert nxt()[0] == "gate:prompts"
    rc, out = run(capsys, "gate", "prompts", "--approve")
    assert rc == 0 and out["standing"] is False  # the plate book alone is no standing yes for clip submits
    assert json.loads((p / "project.json").read_text())["gates"]["prompts_approved"] is False
    stage, st, stages = nxt()
    assert stage == "plates" and "plate book" in stages["gate:prompts"]["detail"]
    write(p / "plates/picks.json", json.dumps({"p01": {"file": "plates/cands/p01/1.jpg"}}), 51)
    stage, st, stages = nxt()
    assert stage == "edit" and stages["clips"]["optional"]  # quick tier: clips optional
    write(p / "clips/SD01.json", json.dumps({"id": "SD01", "status": "locked", "kind": "motion",
                                             "body": {"prompt": "she turns"}}), 52)
    stage, st, stages = nxt()
    assert stage == "gate:prompts" and "SD01 (new)" in stages["gate:prompts"]["detail"]  # unread clip prompt
    assert "1 locked" in stages["clips"]["detail"] and not stages["clips"]["done"]
    rc, out = run(capsys, "gate", "prompts", "--approve", "--note", "owner: go")
    assert rc == 0 and out["changed"] and out["standing"] is True and "clips/SD01.json" in out["covers"]
    assert json.loads((p / "project.json").read_text())["gates"]["prompts_approved"] is True
    assert nxt()[0] == "edit"
    write(p / "edit/edl.json", "{}", 60)
    stage, st, stages = nxt()   # an EDL that gives the board's shots no picture keeps the edit open (integration)
    assert stage == "edit" and "no picture" in stages["edit"]["detail"] and "s001" in stages["edit"]["detail"]
    write(p / "edit/edl.json", json.dumps({"s001": {"plate": "p01"}, "s002": {"plate": "p01"}}), 60)
    stage, st, stages = nxt()
    assert stage == "export" and "no exported data" in stages["export"]["detail"]
    export_assets(p, 70)
    stage, st, stages = nxt()
    assert stage == "lyric-gate" and st["next"]["cmd"].endswith("render lyrics")
    write(p / "render/lyrics-report.json", json.dumps({"checked": 12, "drawn": 12, "missing": []}), 80)
    stage, st, stages = nxt()
    assert stage == "render" and "12/12" in stages["lyric-gate"]["detail"]
    (p / "out/review.mp4").write_bytes(b"\0" * 10)
    at(p / "out/review.mp4", 90)
    assert nxt()[0] == "gate:v1"
    assert run(capsys, "gate", "v1", "--approve")[0] == 0
    assert nxt()[0] == "master"
    (p / "out/master.mp4").write_bytes(b"\0" * 10)
    at(p / "out/master.mp4", 100)
    stage, st, stages = nxt()
    assert stage == "checks" and st["next"]["cmd"].endswith("render check")
    write(p / "render/check.json", json.dumps({"flash": {"pass": True, "worst_per_second": 1, "limit": 3},
                                               "history": {"ok": True}}), 110)
    stage, st, stages = nxt()
    assert stage == "vertical" and st["next"]["cmd"].endswith("render vertical")
    (p / "out/vertical.mp4").write_bytes(b"\0" * 10)
    at(p / "out/vertical.mp4", 120)
    stage, st, stages = nxt()
    assert stage is None and st["next"] is None
    text = core_cli.cmd_status(type("A", (), {"project": "walk"})())["text"]
    assert "all stages done" in text and "AI-generated" in text
    log = (p / "DECISIONS.md").read_text()
    assert "lead canon = " in log and "GATE prompts_approved approved (plate book only)" in log
    assert "GATE prompts_approved approved (plate book + 1 clip prompts) - re-approved after: SD01 (new)" in log


def test_analysis_and_display_go_stale(capsys):
    p = analysed_project(capsys, "stale")
    assert stages_of(capsys, "stale")[2]["analysis"]["done"]
    write(p / "lyrics/lyrics.txt", LYRICS + "[a note added later]\n", 25)  # a note only: the sheet is unchanged
    assert stages_of(capsys, "stale")[2]["analysis"]["done"]
    write(p / "lyrics/lyrics.txt", LYRICS.replace("agents", "robots"), 25)
    stage, st, stages = stages_of(capsys, "stale")
    assert stage == "analysis" and "line 1 differs" in stages["analysis"]["detail"]
    write(p / "lyrics/lyrics.txt", LYRICS + "one more line\n", 25)
    assert "has 2 lines but lyrics.txt has 3" in stages_of(capsys, "stale")[2]["analysis"]["detail"]
    write(p / "lyrics/lyrics.txt", LYRICS, 10)
    at(p / "audio/song.wav", 25)  # a new take ingested after the analysis
    stage, st, stages = stages_of(capsys, "stale")
    assert stage == "analysis" and "audio/song.wav changed after the analysis" in stages["analysis"]["detail"]
    assert st["next"]["cmd"].endswith("analyze")
    at(p / "audio/song.wav", 10)
    write(p / "lyrics/display.txt", "Ladies. Gentlemen. *Robots.*\nWe shipped it +25%|4\n", 40)
    stage, st, stages = stages_of(capsys, "stale")
    assert stage == "display" and "display.txt changed after the last validation" in stages["display"]["detail"]
    at(p / "lyrics/display.txt", 30)
    at(p / "analysis/words.json", 35)  # re-aligned (e.g. an ear-check fix) after the display was validated
    assert "words.json changed" in stages_of(capsys, "stale")[2]["display"]["detail"]


def test_lead_command_and_studio_requires_lead(capsys):
    p = analysed_project(capsys, "leady", "studio")
    stage, st, stages = stages_of(capsys, "leady")
    assert stage == "lead" and not stages["lead"]["optional"]  # studio: a lead is expected even before the board
    rc, out = run(capsys, "-p", "leady", "lead")
    assert rc == 0 and out["lead"]["canon"] == "" and "bible/LEAD.md" in out["text"]
    rc, out = run(capsys, "-p", "leady", "lead", "--canon", "a man  in his thirties,\nshaved head", "--pronoun", "HE",
                  "--by", "owner")
    assert rc == 0 and out["lead"]["canon"] == "a man in his thirties, shaved head" and out["lead"]["pronoun"] == "He"
    rc, out = run(capsys, "-p", "leady", "lead", "--canon", "a man in his thirties, shaved head")
    assert out["changed"] == [] and out["decision"] is None and "no change" in out["text"]
    proj = json.loads((p / "project.json").read_text())
    assert proj["lead"]["canon"].startswith("a man") and proj["lead"]["note"]  # the guidance note is kept
    assert (p / "DECISIONS.md").read_text().count("[owner] lead canon") == 1
    stage, st, stages = stages_of(capsys, "leady")
    assert stages["lead"]["done"] and "no lead.far" in stages["lead"]["detail"] and stage == "board"


def test_lead_none_is_an_explicit_owner_decision(capsys):
    p = analysed_project(capsys, "nolead", "director")
    rc, out = run(capsys, "-p", "nolead", "lead", "--none", "--canon", "x")
    assert rc == 1 and "not both" in out["error"]
    rc, out = run(capsys, "-p", "nolead", "lead", "--none", "--by", "owner")
    assert rc == 0 and out["none"] is True and "board.lead_min" in out["text"]
    assert "[owner] no lead character in this video" in (p / "DECISIONS.md").read_text()
    stage, st, stages = stages_of(capsys, "nolead")
    assert stages["lead"]["done"] and "owner's decision" in stages["lead"]["detail"] and stage == "board"
    write(p / "board/shots.json", json.dumps({"shots": [{"id": "s001", "lead_on_screen": True}]}), 40)
    stage, st, stages = stages_of(capsys, "nolead")
    assert stage == "lead" and "lead.none is set but 1 shots" in stages["lead"]["detail"]
    rc, out = run(capsys, "-p", "nolead", "lead", "--canon", "a robot with a brass face")
    assert out["none"] is False and stages_of(capsys, "nolead")[2]["lead"]["done"]


def test_status_studio_requires_clips(capsys):
    p = new_project(capsys, "studio-song", "--tier", "studio")
    st = core_cli.project_status(p)
    clips = next(s for s in st["stages"] if s["stage"] == "clips")
    assert clips["optional"] is False


def test_status_survives_corrupt_files(capsys):
    p = new_project(capsys, "corrupt")
    (p / "board/shots.json").write_text("{not json")
    (p / "ledger.jsonl").write_text('{"provider":"openrouter","status":"submitted","est_usd":1}\nGARBAGE\n')
    rc, st = run(capsys, "--project", "corrupt", "status")
    assert rc == 0
    board = next(s for s in st["stages"] if s["stage"] == "board")
    assert "not valid JSON" in board["detail"]
    assert st["spend"]["bad_lines"] == 1 and st["spend"]["by_provider"]["openrouter"]["est_usd"] == 1


def test_every_suggested_command_exists_in_the_full_cli(capsys, monkeypatch):
    """Every `slop ...` command that status suggests (cmd, and inside do/detail texts) is registered by its module."""
    p = analysed_project(capsys, "suggest", "studio")
    write(p / "plates/prompts.md", "# book\n", 50)
    _clip(p, "SD01", "delivered", kind="sung", takes=[{"n": 1, "status": "delivered", "file": "x.mp4"}])
    states = [core_cli.project_status(p)]
    (p / "out").mkdir(exist_ok=True)
    (p / "out/master.mp4").write_bytes(b"\0")
    states.append(core_cli.project_status(p))
    monkeypatch.setattr(cli, "MODULES", ALL_MODULES)
    tree = core_cli.command_tree()
    assert tree is not None
    cmds = set()
    for st in states:
        for s in st["stages"]:
            for text in (s["cmd"], s["do"], s["detail"]):
                cmds.update(m.group(0) for m in re.finditer(r"slop --project \S+ [a-z][a-z -]*[a-z]", text or ""))
    cmds |= {core_cli._pcmd(p, x) for x in ("spend --unfreeze", "clip sync SD01", 'lead --canon "T"',
                                            "render encode --review", "clip list", "board sheet", "render sheet")}
    checked = 0
    for c in sorted(cmds):
        first = c.split()[3]
        if first not in tree:  # that module is not installed in this environment
            continue
        assert core_cli.command_available(c, tree) is True, c
        checked += 1
    assert checked >= 15, cmds


def test_command_available_walks_tree():
    tree = {"board": {"audit": {}}, "status": {}, "song": {}}
    assert core_cli.command_available("slop --project x board audit", tree) is True
    assert core_cli.command_available("slop --project x board draft", tree) is False
    assert core_cli.command_available("slop -p x song ingest PATH/TO/song.wav", tree) is True
    assert core_cli.command_available("slop --project x analyze", tree) is False
    assert core_cli.command_available("slop analyze", None) is None


# ---------------------------------------------------------------- gate
def _passing_board(p: Path) -> None:
    (p / "board/shots.json").write_text(json.dumps({"shots": [{"id": "s001"}]}))
    (p / "board/audit.json").write_text(json.dumps({"ok": True}))
    st = (p / "board/shots.json").stat()
    os.utime(p / "board/audit.json", (st.st_atime + 5, st.st_mtime + 5))


def test_gate_preconditions_and_force(capsys):
    p = new_project(capsys, "pre")
    rc, out = run(capsys, "-p", "pre", "gate", "board")
    assert out["ready"] is False and "no board/shots.json" in out["problem"]
    rc, out = run(capsys, "-p", "pre", "gate", "board", "--approve")
    assert rc == 1 and "cannot record approval" in out["error"] and "--force" in out["error"]
    _passing_board(p)
    (p / "board/audit.json").write_text(json.dumps({"ok": False}))
    st = (p / "board/shots.json").stat()
    os.utime(p / "board/audit.json", (st.st_atime + 5, st.st_mtime + 5))
    rc, out = run(capsys, "-p", "pre", "gate", "board", "--approve")
    assert rc == 1 and "FAILED" in out["error"]
    _passing_board(p)
    os.utime(p / "board/shots.json", (st.st_atime + 60, st.st_mtime + 60))  # edited after the audit
    rc, out = run(capsys, "-p", "pre", "gate", "board", "--approve")
    assert rc == 1 and "changed after the last audit" in out["error"]
    rc, st_ = run(capsys, "-p", "pre", "status")
    assert next(s for s in st_["stages"] if s["stage"] == "board")["done"] is False
    rc, out = run(capsys, "-p", "pre", "gate", "board", "--approve", "--force", "--note", "owner insisted")
    assert rc == 0 and out["approved"]
    assert "FORCED: board not ready" in (p / "DECISIONS.md").read_text()
    rc, out = run(capsys, "-p", "pre", "gate", "prompts", "--approve")
    assert rc == 1 and "plates/prompts.md" in out["error"]
    rc, out = run(capsys, "-p", "pre", "gate", "v1", "--approve")
    assert rc == 1 and "review.mp4" in out["error"]
    rc, out = run(capsys, "-p", "pre", "gate", "v1", "--revoke")  # revoking never needs a precondition
    assert rc == 0 and out["changed"] is False


def test_gate_approve_revoke_and_log(capsys):
    p = new_project(capsys, "gates")
    rc, out = run(capsys, "-p", "gates", "gate")
    assert out["gates"] == {"board_approved": False, "prompts_approved": False, "v1_approved": False}
    _passing_board(p)
    rc, out = run(capsys, "-p", "gates", "gate", "board", "--approve", "--note", "owner: love it")
    assert rc == 0 and out["changed"] and out["approved"]
    assert json.loads((p / "project.json").read_text())["gates"]["board_approved"] is True
    rc, out = run(capsys, "-p", "gates", "gate", "board_approved", "--approve")
    assert out["changed"] is False
    rc, out = run(capsys, "-p", "gates", "gate", "Board")
    assert out["approved"] is True
    rc, out = run(capsys, "-p", "gates", "gate", "board", "--revoke")
    assert out["changed"] and out["approved"] is False
    log = (p / "DECISIONS.md").read_text()
    assert log.count("GATE board_approved approved - owner: love it") == 1
    assert log.count("GATE board_approved revoked") == 1
    rc, out = run(capsys, "-p", "gates", "gate", "nope", "--approve")
    assert rc == 1 and "board, prompts, v1" in out["error"]
    rc, out = run(capsys, "-p", "gates", "gate", "--approve")
    assert rc == 1 and "name the gate" in out["error"]


def test_gate_flags_are_exclusive(capsys):
    new_project(capsys, "excl")
    with pytest.raises(SystemExit):
        cli.main(["-p", "excl", "gate", "board", "--approve", "--revoke"])


# ---------------------------------------------------------------- decide
def test_decide_append_dedupe_supersede_list(capsys):
    p = new_project(capsys, "dec")
    rc, out = run(capsys, "-p", "dec", "decide", "she", "sings", "most", "lines")
    assert rc == 0 and out["recorded"] and re.fullmatch(util.STAMP_RE.pattern, out["entry"]["when"])
    rc, out = run(capsys, "-p", "dec", "decide", "she sings most lines")
    assert out["recorded"] is False and out["duplicate"] is True
    rc, out = run(capsys, "-p", "dec", "decide", "--supersedes", "2026-10-01 14:03 UTC", "--by", "owner",
                  "budget is now $60\nnot $40")
    assert out["entry"]["text"] == "UPDATE (supersedes 2026-10-01 14:03 UTC) - [owner] budget is now $60 / not $40"
    rc, out = run(capsys, "-p", "dec", "decide", "--list")
    texts = [d["text"] for d in out["decisions"]]
    assert texts[0].startswith("project created") and texts[1] == "she sings most lines" and len(texts) == 3
    rc, out = run(capsys, "-p", "dec", "decide", "--list", "--last", "1")
    assert len(out["decisions"]) == 1 and out["count"] == 3
    rc, out = run(capsys, "-p", "dec", "decide")
    assert rc == 1 and "nothing to record" in out["error"]
    log = (p / "DECISIONS.md").read_text()
    assert log.count("she sings most lines") >= 1 and log.endswith("\n")


def test_decide_recreates_missing_log_without_fake_creation_line(capsys):
    p = new_project(capsys, "dec2")
    (p / "DECISIONS.md").unlink()
    run(capsys, "-p", "dec2", "decide", "native colour only")
    log = (p / "DECISIONS.md").read_text()
    assert "project created" not in log and "native colour only" in log and "{{" not in log


# ---------------------------------------------------------------- runs
def test_runs_add_list_dedupe_and_escape(capsys):
    p = new_project(capsys, "runs")
    rc, out = run(capsys, "-p", "runs", "runs", "add", "wf_1a2b", "--what", "storyboard | panel",
                  "--resume", "args: board/args.json")
    assert rc == 0 and out["recorded"]
    rc, out = run(capsys, "-p", "runs", "runs", "add", "wf_1a2b", "--what", "storyboard | panel",
                  "--resume", "args: board/args.json")
    assert out["recorded"] is False and out["duplicate"]
    run(capsys, "-p", "runs", "runs", "add", "wf_1a2b", "--what", "storyboard | panel", "--status", "done",
        "--resume", "args: board/args.json")
    run(capsys, "-p", "runs", "runs", "add", "render-v1", "--kind", "render")
    rc, out = run(capsys, "-p", "runs", "runs", "list")
    assert out["count"] == 3 and out["runs"][0]["what"] == "storyboard | panel"
    assert out["runs"][0]["resume"] == "args: board/args.json"
    rc, out = run(capsys, "-p", "runs", "runs", "list", "--latest")
    assert {r["id"]: r["status"] for r in out["runs"]} == {"wf_1a2b": "done", "render-v1": "running"}
    assert "storyboard \\| panel" in (p / "RUNS.md").read_text()
    rc, out = run(capsys, "-p", "runs", "runs", "list", "--last", "1")
    assert [r["id"] for r in out["runs"]] == ["render-v1"]


def test_runs_restores_table_header(capsys):
    p = new_project(capsys, "runs2")
    (p / "RUNS.md").write_text("# my notes without a table")
    run(capsys, "-p", "runs2", "runs", "add", "job-1", "--kind", "deleg")
    rows = core_cli.read_runs(p)
    assert [r["id"] for r in rows] == ["job-1"]
    (p / "RUNS.md").unlink()
    run(capsys, "-p", "runs2", "runs", "add", "job-2")
    assert [r["id"] for r in core_cli.read_runs(p)] == ["job-2"]


# ---------------------------------------------------------------- spend
def _ledger(p: Path, rows: list[dict]) -> None:
    with (p / "ledger.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


LEDGER = [
    {"provider": "openrouter", "model": "bytedance/seedance-2.5", "kind": "video", "est_usd": 1.16, "status": "submitted"},
    {"provider": "openrouter", "model": "bytedance/seedance-2.5", "kind": "video", "est_usd": 1.16, "status": "delivered"},
    {"provider": "openrouter", "model": "bytedance/seedance-2.5", "kind": "video", "est_usd": 1.16, "status": "declined"},
    {"provider": "openrouter", "model": "openai/gpt-image-2", "kind": "image", "est_usd": 0.2, "status": "failed"},
    {"provider": "higgsfield", "model": "seedance_2_5", "kind": "video", "est_usd": 0, "credits": 35, "status": "submitted"},
]


def test_spend_offline_ledger(capsys):
    p = new_project(capsys, "money")
    _ledger(p, LEDGER)
    rc, out = run(capsys, "-p", "money", "spend", "--offline")
    assert rc == 0
    by = out["ledger"]["by_provider"]
    assert by["openrouter"]["est_usd"] == pytest.approx(2.32)
    assert by["openrouter"]["declined"] == 1 and by["openrouter"]["failed"] == 1 and by["openrouter"]["calls"] == 4
    assert by["higgsfield"]["credits"] == 35
    assert out["ledger"]["budget"]["openrouter_left_usd"] == pytest.approx(20 - 2.32)
    assert out["ledger"]["budget"]["higgsfield_left"] == 265
    assert out["openrouter"] == {"checked": False}


def test_spend_real_openrouter_never_leaks_key(capsys, monkeypatch):
    p = new_project(capsys, "money2")
    _ledger(p, LEDGER)
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    fh = fake_http({"/key": (200, KEY_OK), "/credits": (200, CREDITS_OK)})
    monkeypatch.setattr(util, "http_json", fh)
    rc = cli.main(["-p", "money2", "spend"])  # human text
    text = capsys.readouterr().out
    rc2, out = run(capsys, "-p", "money2", "spend")
    assert rc == 0 and rc2 == 0
    blob = text + json.dumps(out)
    assert FAKE_KEY not in blob and "abc...xyz" not in blob and "user_123" not in blob and "ws_9" not in blob
    k = out["openrouter"]["key"]
    assert k["limit"] == 80 and k["usage"] == 0.5 and k["limit_remaining"] == 79.5 and k["ok"]
    assert out["openrouter"]["credits"]["balance"] == pytest.approx(69.75)
    assert "used $0.50 of key limit $80.00" in text and "balance $69.75" in text
    assert all(c["headers"]["Authorization"] == f"Bearer {FAKE_KEY}" for c in fh.calls)
    assert {c["url"] for c in fh.calls} == {"https://openrouter.ai/api/v1/key", "https://openrouter.ai/api/v1/credits"}


def test_spend_warns_when_key_limit_below_budget(capsys, monkeypatch):
    new_project(capsys, "money3", "--tier", "director")
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    low = {"data": {**KEY_OK["data"], "limit": 10, "limit_remaining": 9.5}}
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, low), "/credits": (200, CREDITS_OK)}))
    rc, out = run(capsys, "-p", "money3", "spend")
    assert rc == 0 and "403" in out["text"] and "key's own limit" in out["text"]
    assert out["ledger"]["budget"]["openrouter_usd"] == 150


def test_spend_without_project_and_bad_key(capsys, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (401, {"error": {"message": "No auth"}})}))
    rc, out = run(capsys, "spend")
    # a rejected key means real spend was NOT read: ok false, exit 1, so the bot never quotes the ledger as real
    assert rc == 1 and out["ok"] is False and out["project"] is None and out["real_spend_checked"] is False
    assert out["openrouter"]["key"]["ok"] is False and "rejected the key" in out["openrouter"]["key"]["error"]
    assert "real OpenRouter spend could not be read" in out["error"]
    assert FAKE_KEY not in json.dumps(out)
    monkeypatch.setattr(util, "http_json", fake_http({}))  # openrouter.ai unreachable
    rc, out = run(capsys, "spend")
    assert rc == 1 and out["ok"] is False and "unreachable" in out["error"]
    rc, out = run(capsys, "--project", "missing", "spend")
    assert rc == 1  # a NAMED project that does not exist is an error, never a silent fallback


def test_spend_freeze_and_unfreeze(capsys):
    p = new_project(capsys, "frozen")
    rc, out = run(capsys, "-p", "frozen", "spend", "--freeze", " ")
    assert rc == 1 and "say why" in out["error"]
    rc, out = run(capsys, "-p", "frozen", "spend", "--freeze", "owner: the faces look wrong")
    assert rc == 0 and out["changed"] and "SPENDING FROZEN" in out["text"]
    assert json.loads((p / "project.json").read_text())["budget"]["frozen"]["reason"] == "owner: the faces look wrong"
    rc, out = run(capsys, "-p", "frozen", "spend", "--freeze", "owner: the faces look wrong")
    assert out["changed"] is False
    rc, st = run(capsys, "-p", "frozen", "status")
    assert st["frozen"]["reason"].startswith("owner:") and "SPENDING FROZEN" in st["text"]
    rc, out = run(capsys, "-p", "frozen", "spend", "--offline")
    assert out["frozen"] and out["text"].startswith("SPENDING FROZEN")
    rc, out = run(capsys, "-p", "frozen", "spend", "--unfreeze", "--note", "owner: fixed")
    assert rc == 0 and out["changed"] and "frozen" not in json.loads((p / "project.json").read_text())["budget"]
    log = (p / "DECISIONS.md").read_text()
    assert "SPEND FROZEN - owner: the faces look wrong" in log and "SPEND unfrozen" in log and "owner: fixed" in log
    rc, out = run(capsys, "-p", "frozen", "spend", "--unfreeze")
    assert out["changed"] is False
    with pytest.raises(SystemExit):
        cli.main(["-p", "frozen", "spend", "--freeze", "x", "--unfreeze"])


def test_clip_prompt_approved_matches_the_recorded_prompt(capsys):
    p = new_project(capsys, "cpa")
    write(p / "plates/prompts.md", "# book\n", 50)
    _clip(p, "SD01", "locked")
    clip = json.loads((p / "clips/SD01.json").read_text())
    assert core_cli.clip_prompt_approved(json.loads((p / "project.json").read_text()), clip) is False
    run(capsys, "-p", "cpa", "gate", "prompts", "--approve")
    proj = json.loads((p / "project.json").read_text())
    assert core_cli.clip_prompt_approved(proj, clip) is True
    assert core_cli.clip_prompt_approved(proj, {**clip, "body": {"prompt": "rewritten", "duration": 5}}) is False
    assert core_cli.clip_prompt_approved(proj, {**clip, "id": "SD02"}) is False


def test_spend_no_key(capsys):
    rc, out = run(capsys, "spend")
    assert rc == 0 and out["openrouter"]["key"]["present"] is False and out["real_spend_checked"] is False
    assert "secure secret card" in out["text"] and "NOT read" in out["text"]


def test_spend_notes_balance_below_budget_and_key_expiry(capsys, monkeypatch):
    new_project(capsys, "money4", "--tier", "director")
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 7 * 86400))
    key = {"data": {**KEY_OK["data"], "limit": None, "limit_remaining": None, "expires_at": soon}}
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, key), "/credits": (200, CREDITS_OK)}))
    rc, out = run(capsys, "-p", "money4", "spend")
    assert rc == 0 and out["real_spend_checked"] is True
    assert any("balance $69.75 is below the project's remaining budget $150.00" in n for n in out["notes"])
    assert any("expires" in n for n in out["notes"]) and "402" in out["text"]
    rich = {"data": {"total_credits": 500, "total_usage": 1}}
    later = {"data": {**KEY_OK["data"], "limit": None, "limit_remaining": None, "expires_at": None}}
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, later), "/credits": (200, rich)}))
    rc, out = run(capsys, "-p", "money4", "spend")
    assert rc == 0 and out["notes"] == []


# ---------------------------------------------------------------- doctor
def test_doctor_offline_quick_structure(capsys):
    rc, out = run(capsys, "doctor", "--quick", "--offline")
    names = [c["name"] for c in out["checks"]]
    for n in ("python", "paths", "deps:minimal", "deps:full", "lyrics:lint-data", "ffmpeg", "chromium", "cloudflared",
              "openrouter", "ram", "cpu"):
        assert n in names, n
    assert all(c["status"] in ("ok", "warn", "fail", "skip") for c in out["checks"])
    assert out["ok"] == (out["summary"]["fail"] == 0) and rc == (0 if out["ok"] else 1)
    orc = next(c for c in out["checks"] if c["name"] == "openrouter")
    assert orc["status"] == "warn" and "secret card" in orc["fix"]
    paths = next(c for c in out["checks"] if c["name"] == "paths")
    assert paths["status"] == "warn"  # no env.sh in the temp SLOP_HOME


def test_doctor_openrouter_states(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, KEY_OK)}))
    c = doctor.check_openrouter()
    assert c["status"] == "ok" and "$80.00" in c["detail"] and FAKE_KEY not in json.dumps(c)
    assert "label" not in c["data"]
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (403, None)}))
    assert doctor.check_openrouter()["status"] == "fail"
    monkeypatch.setattr(util, "http_json", fake_http({}))
    c = doctor.check_openrouter()
    assert c["status"] == "warn" and "unreachable" in c["detail"]
    free = {"data": {**KEY_OK["data"], "is_free_tier": True}}
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, free)}))
    assert doctor.check_openrouter()["status"] == "warn"
    nolim = {"data": {**KEY_OK["data"], "limit": None, "limit_remaining": None}}
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, nolim)}))
    c = doctor.check_openrouter()
    assert c["status"] == "ok" and "no key spend limit" in c["detail"]
    assert doctor.check_openrouter(offline=True)["status"] == "skip"


def test_doctor_ffmpeg_parsing(monkeypatch):
    monkeypatch.setattr(util, "find_tool", lambda n: f"/x/{n}")

    def fake_run(cmd, timeout=60, env=None, cwd=None):
        if "-version" in cmd:
            return 0, "ffmpeg version 7.1.5-0+deb13u1 Copyright\n", ""
        return 0, " V....D libx264              libx264 H.264 / AVC\n", ""
    monkeypatch.setattr(util, "run", fake_run)
    c = doctor.check_ffmpeg()
    assert c["status"] == "ok" and c["data"]["version"] == "7.1.5-0+deb13u1"
    monkeypatch.setattr(util, "run", lambda cmd, **k: (0, "ffmpeg version 6.0\n", "") if "-version" in cmd
                        else (0, " V..... libopenh264 OpenH264\n", ""))
    c = doctor.check_ffmpeg()
    assert c["status"] == "fail" and "libx264" in c["detail"]
    monkeypatch.setattr(util, "find_tool", lambda n: None)
    assert doctor.check_ffmpeg()["status"] == "fail"


def test_doctor_deps_profiles(monkeypatch):
    def probe(deps, timeout=300):
        res = {m: {"ok": True, "version": "1.0"} for m, _, _ in deps}
        res["playwright"] = {"ok": True, "version": "1.60.0"}
        for m in ("torch", "demucs"):
            res[m] = {"ok": False, "error": "ModuleNotFoundError"}
        return res
    monkeypatch.setattr(doctor, "import_probe", probe)
    checks = {c["name"]: c for c in doctor.check_deps("minimal")}
    assert checks["deps:minimal"]["status"] == "ok"
    assert checks["deps:full"]["status"] == "warn"  # partially installed, not required
    checks = {c["name"]: c for c in doctor.check_deps("full")}
    assert checks["deps:full"]["status"] == "fail" and "torch" in checks["deps:full"]["detail"]
    monkeypatch.setattr(doctor, "import_probe", lambda deps, timeout=300: {
        m: ({"ok": False, "error": "x"} if (m, p, w) in doctor.FULL_DEPS else {"ok": True, "version": w or "1"})
        for m, p, w in deps})
    checks = {c["name"]: c for c in doctor.check_deps("minimal")}
    assert checks["deps:full"]["status"] == "skip"


def test_doctor_import_probe_real():
    res = doctor.import_probe([("json", "json", None), ("no_such_mod_xyz", "nope", None)], timeout=60)
    assert res["json"]["ok"] is True
    assert res["no_such_mod_xyz"]["ok"] is False and "ModuleNotFoundError" in res["no_such_mod_xyz"]["error"]


def test_doctor_chromium_fallback(monkeypatch):
    import importlib.util as iu
    if iu.find_spec("playwright") is None:
        pytest.skip("playwright not installed")
    monkeypatch.setattr(doctor, "try_browser", lambda ch, timeout=120: {"ok": ch == "chrome", "channel": ch,
                                                                        "version": "140", "error": "boom"})
    c = doctor.check_chromium()
    assert c["status"] == "warn" and c["data"]["channel"] == "chrome" and "SLOP_BROWSER_CHANNEL=chrome" in c["fix"]
    monkeypatch.setenv("SLOP_BROWSER_CHANNEL", "chrome")
    assert doctor.check_chromium()["status"] == "ok"
    monkeypatch.setattr(doctor, "try_browser", lambda ch, timeout=120: {"ok": False, "channel": ch, "error": "x"})
    assert doctor.check_chromium()["status"] == "fail"


def test_doctor_chromium_real_launch():
    """The launch snippet really starts headless chromium (parity env has playwright 1.60 + chromium-1223)."""
    import importlib.util as iu
    if iu.find_spec("playwright") is None:
        pytest.skip("playwright not installed")
    r = doctor.try_browser("chromium", timeout=90)
    err = r.get("error") or ""
    if not r["ok"] and ("not downloaded" in err or "missing" in err):
        pytest.skip(f"chromium cannot start in this environment: {err}")
    assert r["ok"], r


def test_launch_error_extraction():
    log = ("<launching> /x/chrome-headless-shell --flags\n[pid=9][err] /x/chrome-headless-shell: error while loading "
           "shared libraries: libnspr4.so: cannot open shared object file\n  - [pid=9] starting temporary directories "
           "cleanup\n  - [pid=9] <gracefully close end>")
    assert doctor.launch_error(log) == "system library libnspr4.so is missing (Chromium's OS dependencies)"
    assert "not downloaded" in doctor.launch_error("Executable doesn't exist at /h/ms-playwright/chromium-1223/x\n")
    assert doctor.launch_error("", 124) == "launch timed out"
    assert doctor.launch_error("Error: something odd\n  - [pid=1] starting temporary directories cleanup") == \
        "Error: something odd"


def test_doctor_net_probe_mocked(monkeypatch):
    monkeypatch.setattr(util, "http_reachable",
                        lambda url, timeout=8: (("huggingface" not in url), 200, None if "huggingface" not in url
                                                else "network error: blocked"))
    checks = {c["name"]: c for c in doctor.check_net()}
    assert checks["net:huggingface.co"]["status"] == "warn" and "--minimal" in checks["net:huggingface.co"]["fix"]
    assert checks["net:pypi.org"]["status"] == "ok"


def test_doctor_profile_from_marker(env, monkeypatch):
    env["home"].mkdir(parents=True)
    (env["home"] / "profile").write_text("full\n")
    assert doctor.active_profile() == "full"
    monkeypatch.setenv("SLOP_PROFILE", "minimal")
    assert doctor.active_profile() == "minimal"
    assert doctor.active_profile("full") == "full"


# ---------------------------------------------------------------- gates: what was approved, staleness, standing yes
def _clip(p: Path, cid: str, status: str, t: float = 60, **extra) -> None:
    c = {"id": cid, "status": status, "kind": extra.pop("kind", "motion"), "provider": "openrouter",
         "model": "bytedance/seedance-2.5", "start": f"plates/{cid}.jpg", "body": {"prompt": f"{cid} prompt",
                                                                                 "duration": 5}, **extra}
    write(p / f"clips/{cid}.json", json.dumps(c), t)


def test_board_gate_goes_stale_when_the_board_changes(capsys):
    p = new_project(capsys, "bstale")
    _passing_board(p)
    assert run(capsys, "-p", "bstale", "gate", "board", "--approve")[0] == 0
    proj = json.loads((p / "project.json").read_text())
    meta = proj["gates_meta"]["board_approved"]
    assert util.STAMP_RE.fullmatch(meta["at"]) and meta["covers"]["board/shots.json"].startswith("sha1:")
    os.utime(p / "board/shots.json")  # touched, same content: the approval still covers it
    st = core_cli.project_status(p)
    assert st["gate_state"]["board_approved"]["current"] is True
    (p / "board/shots.json").write_text(json.dumps({"shots": [{"id": "s001"}, {"id": "s002"}]}))
    a = (p / "board/audit.json").stat().st_mtime
    os.utime(p / "board/shots.json", (a + 10, a + 10))  # edited after the audit
    _, st, stages = stages_of(capsys, "bstale")
    assert stages["gate:board"]["done"] is False and "changed since the approval" in stages["gate:board"]["detail"]
    assert st["gate_state"]["board_approved"]["label"].startswith("STALE")
    rc, out = run(capsys, "-p", "bstale", "gate", "board")
    assert out["approved"] is True and out["current"] is False and out["stale"]
    rc, out = run(capsys, "-p", "bstale", "gate", "board", "--approve")
    assert rc == 1 and "changed after the last audit" in out["error"]  # re-audit first
    _passing_board(p)
    (p / "board/shots.json").write_text(json.dumps({"shots": [{"id": "s001"}, {"id": "s002"}]}))
    st_ = (p / "board/shots.json").stat()
    os.utime(p / "board/audit.json", (st_.st_atime + 5, st_.st_mtime + 5))
    rc, out = run(capsys, "-p", "bstale", "gate", "board", "--approve", "--note", "owner: ok again")
    assert rc == 0 and out["changed"] is True
    assert "re-approved after: board/shots.json changed since the approval" in (p / "DECISIONS.md").read_text()
    assert stages_of(capsys, "bstale")[2]["gate:board"]["done"] is True
    rc, out = run(capsys, "-p", "bstale", "gate", "board", "--approve")
    assert out["changed"] is False  # idempotent


def test_unrecorded_gate_counts_but_says_so(capsys):
    p = new_project(capsys, "legacy")
    proj = json.loads((p / "project.json").read_text())
    proj["gates"]["board_approved"] = True  # e.g. set by `slop board approve` or by hand
    (p / "project.json").write_text(json.dumps(proj))
    stage = next(s for s in core_cli.project_status(p)["stages"] if s["stage"] == "gate:board")
    assert stage["done"] is True and "not recorded" in stage["detail"]


def test_prompts_gate_standing_yes_needs_read_clip_prompts(capsys):
    p = new_project(capsys, "pgate", "--tier", "studio")
    write(p / "plates/prompts.md", "# book\n", 50)
    _clip(p, "SD01", "locked")
    _clip(p, "SD02", "draft")
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts", "--approve")
    assert rc == 0 and out["standing"] is False and "SD02" in out["text"] and "--yes" in out["text"]
    assert set(out["covers"]) == {"plates/prompts.md", "clips/SD01.json"}
    assert json.loads((p / "project.json").read_text())["gates"]["prompts_approved"] is False
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts")
    assert out["approved"] and out["current"] and out["drafts"] == ["SD02"] and "clips/SD01.json" in out["covers"]
    _clip(p, "SD02", "locked")  # the draft is locked: the owner has not read it
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts")
    assert out["current"] is False and out["stale"] == ["SD02 (new)"]
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts", "--approve")
    assert rc == 0 and out["standing"] is True and out["changed"]
    assert json.loads((p / "project.json").read_text())["gates"]["prompts_approved"] is True
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts", "--approve")
    assert out["changed"] is False
    _clip(p, "SD01", "locked", body={"prompt": "SD01 a rewritten prompt", "duration": 5})
    stage = next(s for s in core_cli.project_status(p)["stages"] if s["stage"] == "gate:prompts")
    assert stage["done"] is False and "SD01 (prompt changed)" in stage["detail"] and "clip list" in stage["do"]
    _clip(p, "SD01", "submitted", body={"prompt": "SD01 a rewritten prompt", "duration": 5})  # spent with --yes
    _clip(p, "SD02", "delivered")
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts", "--approve")
    assert out["changed"] is False and out["standing"] is True  # nothing left to read; the yes is not downgraded
    write(p / "plates/prompts.md", "# book v2\n", 70)
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts")
    assert out["current"] is False and "plates/prompts.md changed since the approval" in out["stale"]
    rc, out = run(capsys, "-p", "pgate", "gate", "prompts", "--revoke")
    assert out["changed"] and json.loads((p / "project.json").read_text())["gates"]["prompts_approved"] is False
    assert "prompts_approved" not in json.loads((p / "project.json").read_text())["gates_meta"]


def test_clips_stage_needs_decisions_and_measured_sync(capsys):
    p = new_project(capsys, "clipsy", "--tier", "studio")
    shots = {"shots": [{"id": "s001", "clip": "SD01"}, {"id": "s002", "clip": "SD02"}, {"id": "s003", "clip": "SD03"}]}
    write(p / "board/shots.json", json.dumps(shots), 40)
    take = {"n": 1, "status": "delivered", "file": "clips/SD01/take-1.mp4"}
    _clip(p, "SD01", "delivered", kind="sung", takes=[take])
    _clip(p, "SD02", "declined")
    _clip(p, "SD03", "delivered", kind="motion", takes=[take])
    _clip(p, "SD09", "failed")  # not on the board any more: cut away, ignored
    stage = next(s for s in core_cli.project_status(p)["stages"] if s["stage"] == "clips")
    assert not stage["done"] and "needs a decision: SD02 declined" in stage["detail"]
    assert "UNALTERED" in stage["do"] and "not on the board (ignored): SD09" in stage["detail"]
    shots["shots"][1]["clip"] = None  # the owner chose to cut away: a plate on that shot
    write(p / "board/shots.json", json.dumps(shots), 41)
    stage = next(s for s in core_cli.project_status(p)["stages"] if s["stage"] == "clips")
    assert not stage["done"] and "lip sync not measured: SD01" in stage["detail"]
    assert stage["cmd"].endswith("clip sync SD01")
    _clip(p, "SD01", "delivered", kind="sung", takes=[{**take, "sync": {"lag_s": 0.02, "ncc": 0.6, "mode": "copy"}}])
    _clip(p, "SD01c1", "delivered", kind="sung", parent="SD01",
          takes=[{**take, "sync": {"mode": "copy"}}, {**take, "n": 2, "rejected": True}])  # a cover; rejected take 2
    stage = next(s for s in core_cli.project_status(p)["stages"] if s["stage"] == "clips")
    assert stage["done"], stage
    (p / "clips/SD04.json").write_text("{broken")
    stage = next(s for s in core_cli.project_status(p)["stages"] if s["stage"] == "clips")
    assert not stage["done"] and "unreadable: SD04" in stage["detail"]


def test_lyric_gate_checks_and_v1_preconditions(capsys):
    p = new_project(capsys, "qa")
    export_assets(p, 70)
    (p / "out/review.mp4").write_bytes(b"\0" * 10)
    at(p / "out/review.mp4", 90)
    rc, out = run(capsys, "-p", "qa", "gate", "v1", "--approve")
    assert rc == 1 and "lyric gate has not run" in out["error"] and "render lyrics" in out["error"]
    write(p / "render/lyrics-report.json", json.dumps({"checked": 12, "drawn": 11, "missing": [{"line": 3}]}), 80)
    rc, out = run(capsys, "-p", "qa", "gate", "v1", "--approve")
    assert rc == 1 and "1 of 12 sung tokens not on screen" in out["error"]
    write(p / "render/lyrics-report.json", json.dumps({"checked": 12, "drawn": 12, "missing": []}), 60)
    assert "engine data changed after the last lyric gate" in core_cli.lyric_gate_problem(p)
    write(p / "render/lyrics-report.json", json.dumps({"checked": 0, "missing": []}), 80)
    assert "0 tokens" in core_cli.lyric_gate_problem(p)
    write(p / "render/lyrics-report.json", json.dumps({"checked": 12, "drawn": 12, "missing": []}), 80)
    assert core_cli.lyric_gate_problem(p) is None
    rc, out = run(capsys, "-p", "qa", "gate", "v1", "--approve")
    assert rc == 0 and "out/review.mp4" in out["covers"]
    (p / "out/review.mp4").write_bytes(b"\1" * 12)  # a new review copy: the owner has not watched it
    at(p / "out/review.mp4", 95)
    stages = {s["stage"]: s for s in core_cli.project_status(p)["stages"]}
    assert not stages["gate:v1"]["done"] and "out/review.mp4 changed" in stages["gate:v1"]["detail"]
    at(p / "out/review.mp4", 65)  # older than the engine data
    assert "STALE" in {s["stage"]: s for s in core_cli.project_status(p)["stages"]}["render"]["detail"]
    (p / "out/master.mp4").write_bytes(b"\0" * 10)
    at(p / "out/master.mp4", 100)
    write(p / "render/check.json", json.dumps({"flash": {"pass": False, "worst_per_second": 5, "limit": 3},
                                               "history": {"ok": True}}), 110)
    checks = {s["stage"]: s for s in core_cli.project_status(p)["stages"]}["checks"]
    assert not checks["done"] and "flash check FAILED (worst 5/s" in checks["detail"]
    write(p / "render/check.json", json.dumps({"history": {"ok": True}}), 110)  # --skip-flash
    assert "flash check not run" in {s["stage"]: s for s in core_cli.project_status(p)["stages"]}["checks"]["detail"]
    write(p / "render/check.json", json.dumps({"flash": {"pass": True}, "history": {"ok": True}}), 110)
    at(p / "out/master.mp4", 120)  # re-encoded after the check
    checks = {s["stage"]: s for s in core_cli.project_status(p)["stages"]}["checks"]
    assert not checks["done"] and "changed after the last check" in checks["detail"]
    at(p / "out/master.mp4", 100)
    assert {s["stage"]: s for s in core_cli.project_status(p)["stages"]}["checks"]["done"]
    write(p / "engine/assets/shots.js", "window.SHOTLIST = {};", 130)  # re-exported after the master
    stages = {s["stage"]: s for s in core_cli.project_status(p)["stages"]}
    assert "STALE" in stages["master"]["detail"] and not stages["lyric-gate"]["done"]
    write(p / "board/shots.json", "{}", 140)  # an input changed after the export
    prob = core_cli.export_problem(p)
    assert "board/shots.json" in prob and prob.endswith("changed after the last export")


# ---------------------------------------------------------------- robustness, discovery, flags
def test_corrupt_project_json_is_a_clear_error(capsys):
    p = new_project(capsys, "broken")
    (p / "project.json").write_text('{"name": "broken",, }')
    for argv in (["status"], ["gate"], ["decide", "x"], ["lead"], ["spend", "--offline"]):
        rc, out = run(capsys, "-p", "broken", *argv)
        assert rc == 1 and "project.json is not valid JSON" in out["error"], (argv, out)
        assert "line 1" in out["error"] and "templates" in out["error"] and "traceback" not in out
    rc, out = run(capsys, "new", "broken")
    assert rc == 1 and "not valid JSON" in out["error"]
    rc, out = run(capsys, "projects")
    row = next(r for r in out["projects"] if r["name"] == "broken")
    assert row["next"] == "broken" and "not valid JSON" in row["next_do"]


def test_projects_listing_and_hint_without_project(capsys, env):
    rc, out = run(capsys, "projects")
    assert rc == 0 and out["count"] == 0 and "slop new" in out["text"]
    rc, out = run(capsys, "status")
    assert rc == 1 and "No projects" in out["error"] and "slop new NAME" in out["error"]
    new_project(capsys, "alpha", "--title", "Alpha Song")
    p = new_project(capsys, "beta", "--tier", "studio")
    fill_brief(p)
    rc, out = run(capsys, "projects")
    assert rc == 0 and [r["name"] for r in out["projects"]] == ["alpha", "beta"]
    rows = {r["name"]: r for r in out["projects"]}
    assert rows["alpha"]["next"] == "brief" and rows["beta"]["next"] == "song" and rows["beta"]["tier"] == "studio"
    assert rows["alpha"]["title"] == "Alpha Song" and "alpha" in out["text"]
    rc, out = run(capsys, "status")
    assert rc == 1 and "--project" in out["error"] and "alpha, beta" in out["error"] and "slop projects" in out["error"]
    rc, out = run(capsys, "-p", "gamma", "gate")
    assert rc == 1 and "slop new" in out["error"] and "alpha, beta" in out["error"]


def test_hoist_global_flags():
    h = util.hoist_global_flags
    assert h(["status", "--json", "-p", "x"]) == ["--json", "-p", "x", "status"]
    assert h(["analyze", "--project=my", "--steps", "beats"]) == ["--project=my", "analyze", "--steps", "beats"]
    assert h(["--json", "lyrics", "lint", "--project", "a b"]) == ["--json", "--project", "a b", "lyrics", "lint"]
    assert h(["decide", "--", "--json", "-p"]) == ["decide", "--", "--json", "-p"]  # after --: left alone
    assert h(["status", "-p"]) == ["status", "-p"]  # no value: argparse reports it
    assert h([]) == []
    ap = cli.build_parser()  # the hoisted form parses for the core commands
    a = ap.parse_args(h(["status", "--json", "-p", "x"]))
    assert a.json is True and a.project == "x" and a.func is core_cli.cmd_status


@pytest.mark.parametrize("argv, needle", [
    (["new"], "the following arguments are required: name"),
    (["new", "x", "--tier", "bogus"], "invalid choice: 'bogus'"),
    (["runs"], "the following arguments are required"),
    (["gate", "board", "--approve", "--revoke"], "not allowed with argument"),
])
def test_core_usage_errors_print_json(capsys, monkeypatch, argv, needle):
    monkeypatch.setattr(sys, "argv", ["slop", "--json", *argv])
    with pytest.raises(SystemExit) as e:
        cli.main(["--json", *argv])
    assert e.value.code == 2
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is False and needle in out["error"] and out["usage"].startswith("usage:")
    monkeypatch.setattr(sys, "argv", ["slop", *argv])  # without --json: plain argparse usage on stderr
    with pytest.raises(SystemExit):
        cli.main(argv)
    cap = capsys.readouterr()
    assert cap.out.strip() == "" and "usage:" in cap.err


def test_template_restores_the_source_files(capsys):
    p = new_project(capsys, "tpl")
    plan = (p / "PLAN.md").read_text()
    heads = [ln for ln in plan.splitlines() if ln.startswith("## ")]
    assert len(heads) == 12 and heads[0].startswith("## 0. Method") and heads[-1].startswith("## 8. Decisions")
    lead = (p / "bible/LEAD.md").read_text()
    assert "Midjourney drifts otherwise" in lead and "## Never" in lead and "slop --project tpl lead" in lead
    assert "| line | words (as sung) | reference |" in (p / "lyrics/SOURCES.md").read_text()
    assert "newest last" in (p / "NOTES.md").read_text()
    assert core_cli.brief_ask(p) == "" and "verbatim" in (p / "BRIEF.md").read_text()
    readme = (p / "README.md").read_text()
    for needle in ("BRIEF.md", "PLAN.md", "bible/LEAD.md", "NOTES.md", "lyrics/SOURCES.md", "render check",
                   "AI-generated", "audio.downbeat_phase", "board.lead_min", "budget.motion_s"):
        assert needle in readme, needle
    (p / "BRIEF.md").unlink()
    rc, out = run(capsys, "new", "tpl")
    assert "BRIEF.md" in out["files_added"]


# ---------------------------------------------------------------- doctor extras
def test_doctor_warns_on_key_expiry(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3 * 86400))
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, {"data": {**KEY_OK["data"], "expires_at": soon}})}))
    c = doctor.check_openrouter()
    assert c["status"] == "warn" and "EXPIRES" in c["detail"] and "new OpenRouter key" in c["fix"]
    later = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 90 * 86400))
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, {"data": {**KEY_OK["data"], "expires_at": later}})}))
    assert doctor.check_openrouter()["status"] == "ok"
    assert util.parse_iso("2026-10-08") is not None and util.parse_iso("soon") is None and util.parse_iso(None) is None


def test_doctor_lyric_lint_data(env, monkeypatch):
    monkeypatch.setattr(doctor, "spec_probe", lambda deps: {"wordfreq": {"ok": False, "error": "not installed"}})
    c = doctor.check_lyric_tools("minimal", quick=True)
    assert c["status"] == "skip"
    c = doctor.check_lyric_tools("full", quick=True)
    assert c["status"] == "warn" and "wordfreq" in c["detail"] and "--full" in c["fix"]
    f = doctor.cmudict_cache()
    f.parent.mkdir(parents=True)
    f.write_bytes(b"a AH0\n" * 200_000)
    monkeypatch.setattr(doctor, "spec_probe", lambda deps: {"wordfreq": {"ok": True, "version": "3.1.1"}})
    assert doctor.check_lyric_tools("full", quick=True)["status"] == "ok"
    hosts = {u.split("/")[2] for u, _, _ in doctor.NET_HOSTS}
    assert {"raw.githubusercontent.com", "api.are.na", "api.github.com"} <= hosts


# ---------------------------------------------------------------- util
def test_load_env_file(tmp_path, monkeypatch):
    f = tmp_path / "x.env"
    f.write_text('# comment\nexport A_KEY="quoted value"\nB=plain\nbad line\nC=\'single\'\nA_KEY2 = spaced \n')
    monkeypatch.setenv("B", "from-env")
    monkeypatch.delenv("A_KEY", raising=False)
    got = util.load_env_file(f)
    assert got == {"A_KEY": "quoted value", "B": "plain", "C": "single", "A_KEY2": "spaced"}
    assert os.environ["A_KEY"] == "quoted value" and os.environ["B"] == "from-env"  # env wins
    util.load_env_file(f, override=True)
    assert os.environ["B"] == "plain"
    assert util.load_env_file(tmp_path / "missing.env") == {}


def test_read_lyric_lines(tmp_path):
    f = tmp_path / "l.txt"
    f.write_text("[a note]\n[Chorus]\n  hello there  \n\n#AI|2 wins\n[Verse 2: spoken\n  [indented note]\n")
    lines = util.read_lyric_lines(f)
    assert lines == ["hello there", "#AI|2 wins"]  # same rule as the audio module's read_sheet
    assert util.read_lyric_lines(tmp_path / "none.txt") == []


def test_template_fonts_are_engine_families():
    fj = core_cli.toolkit_root() / "engine" / "fonts" / "fonts.js"
    if not fj.is_file():
        pytest.skip("engine fonts not present")
    body = fj.read_text(encoding="utf-8").split("window.ENGINE_FONTS =", 1)[1].lstrip()
    data, _ = json.JSONDecoder().raw_decode(body)
    families = {f["family"] for f in data["faces"]}
    fonts = json.loads((core_cli.template_dir() / "project.json").read_text())["look"]["fonts"]
    assert set(fonts) == {"lyric", "micro", "display"}
    for role, fam in fonts.items():
        assert fam in families, (role, fam)


def test_lyric_templates_are_ignored_by_every_reader():
    """The template notes must never count as sung lines - for core, the audio aligner and the display reader."""
    tpl = core_cli.template_dir() / "lyrics"
    assert util.read_lyric_lines(tpl / "lyrics.txt") == [] and util.read_lyric_lines(tpl / "display.txt") == []
    try:
        from slop.audio.align import read_sheet
        from slop.audio.display import read_display
    except Exception:  # audio module not merged / deps missing
        pytest.skip("audio module not importable here")
    assert read_sheet(tpl / "lyrics.txt") == [] and read_display(tpl / "display.txt") == []


def test_validate_name_and_stamp():
    assert util.validate_name("my-song-2") == "my-song-2"
    with pytest.raises(SlopError):
        util.validate_name("My Song")
    s = util.stamp(0)
    assert s == "1970-01-01 00:00 UTC" and util.STAMP_RE.fullmatch(s)
    assert util.STAMP_RE.fullmatch(util.today())


def test_table_and_money():
    t = util.table([["a", 1], ["bbb", None]], ["x", "y"])
    assert t.splitlines()[0].startswith("x") and "---" in t.splitlines()[1]
    assert util.money(1234.5) == "$1,234.50" and util.money(None) == "?"
    assert util.human_bytes(1536) == "1.5 KB"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/ok":
            body, code = b'{"data": {"limit": 5, "usage": 1}}', 200
        elif self.path == "/auth":
            body, code = b'{"error": {"message": "No auth credentials found"}}', 401
        else:
            body, code = b"<html>nope</html>", 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_http_json_against_local_server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert util.http_json(base + "/ok") == (200, {"data": {"limit": 5, "usage": 1}}, None)
        st, data, err = util.http_json(base + "/auth")
        assert st == 401 and err == "No auth credentials found"
        st, data, err = util.http_json(base + "/html")
        assert st == 200 and data is None and "not JSON" in err
        assert util.http_reachable(base + "/auth")[0] is True
    finally:
        srv.shutdown()
    st, data, err = util.http_json("http://127.0.0.1:9/never", timeout=2)
    assert st == 0 and err.startswith("network error")


def test_openrouter_key_info_parsing(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.setattr(util, "http_json", fake_http({"/key": (200, {"data": {"limit": 10, "usage": 2.5,
                                                                              "label": "secret-ish"}})}))
    info = util.openrouter_key_info()
    assert info["ok"] and info["limit_remaining"] == 7.5 and "label" not in info
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert util.openrouter_key_info()["present"] is False
    assert util.openrouter_credits()["ok"] is False


def test_browser_kwargs(monkeypatch):
    assert util.browser_launch_kwargs() == {"headless": True}
    monkeypatch.setenv("SLOP_BROWSER_CHANNEL", "chrome")
    assert util.browser_launch_kwargs() == {"headless": True, "channel": "chrome"}
    monkeypatch.setenv("SLOP_BROWSER_CHANNEL", "weird")
    assert util.browser_channel() == "chromium"


def test_machine_facts():
    m, c = util.mem_info(), util.cpu_info()
    assert c["count"] and c["usable"]
    if sys.platform.startswith("linux"):
        assert m["total"] and m["total"] > 0
    d = util.disk_info(Path("/definitely/not/here/x"))
    assert d["free"] is None or d["free"] > 0
