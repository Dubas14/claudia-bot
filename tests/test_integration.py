"""Integration regressions: contract mismatches between modules found while wiring the toolkit end to end.

Each test pins one fix (see e2e/INTEGRATION.md): the router's global flags and JSON usage errors, the ledger's spend
freeze and precision, shots without a picture, `slop brief`, idempotent `plates pick --all-first`, the audit's
graphic-note TODO and engine-family treatment comparison, the draft's sung-window and print-texture rules, the display
starter's |n, gen's per-clip prompt approval and its past-the-end window refusal, and every command line the README
documents existing in the real argparse tree. Synthetic fixtures only; no network, no browser.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop import cli, core_cli, ledger, util  # noqa: E402
from slop.board import audit, draft, plates  # noqa: E402
from slop.board.common import engine_treatment, is_code  # noqa: E402
from slop.config import SlopError  # noqa: E402


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    for v in ("SLOP_PROJECT", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)


def run(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main(list(argv))
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


# ---------------------------------------------------------------- router
def test_global_flags_work_after_the_command_for_every_module(capsys, tmp_path):
    rc, out = run(capsys, "--json", "new", "flags-song")
    assert rc == 0 and out["ok"]
    # board/render/gen/taste parsers: --json and -p after the subcommand
    for argv in (["status", "--json", "-p", "flags-song"], ["plates", "status", "--json", "-p", "flags-song"],
                 ["clip", "list", "--json", "--project", "flags-song"], ["spend", "--offline", "--json", "-p", "flags-song"]):
        rc, out = run(capsys, *argv)
        assert "ok" in out, argv


def test_usage_errors_are_json_with_json_flag(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--json", "clip", "new"])
    assert e.value.code == 2
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["ok"] is False and "required" in out["error"] and out["usage"].startswith("usage: slop clip new")


def test_every_readme_command_parses():
    """Every `slop ...` line in the README's command tables parses with the real router (placeholders filled)."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    ap = cli.build_parser()
    lines = re.findall(r"^\| `(slop [^`]+)`", text, flags=re.M)
    assert len(lines) > 60
    fill = {"FILE": "x.wav", "CLIP": "c01", "SHOT": "s001", "SRC": "in.png", "OUT": "out.png", "VIDEO": "v.mp4",
            "REF": "r.wav", "QUERY": "q", "NAME": "n", "TEXT": "t", "ID": "i", "ACTION": "start", "FILES": "a.png",
            "PAIRS": "p001", "PLATES": "p001"}
    bad = []
    for ln in lines:
        ln = ln.replace("\\|", "|")
        while re.search(r"\[[^\[\]]*\]", ln):                              # optional parts dropped, innermost first
            ln = re.sub(r"\[[^\[\]]*\]", "", ln)                            # (`[--anchor PLATE[:K]]` nests)
        ln = re.sub(r"(?<![-\w])([\w.-]+)(\|[\w.-]+)+", r"\1", ln)        # a|b-c|d choices -> the first one
        ln = re.sub(r"\b[A-Z][A-Z0-9_]+\b", lambda m: fill.get(m.group(0), "1"), ln)
        words = shlex.split(ln)[1:]
        try:
            ap.parse_args(util.hoist_global_flags(words))
        except SystemExit:
            bad.append(ln)
    assert not bad, bad


# ---------------------------------------------------------------- ledger
def test_spend_freeze_blocks_every_paid_call_and_precision(tmp_path):
    p = synth.make_project(tmp_path)
    ledger.check_budget(p, "openrouter", add_usd=0.01)
    proj = json.loads((p / "project.json").read_text())
    proj["budget"]["frozen"] = {"at": "2026-10-01", "reason": "grey takes"}
    (p / "project.json").write_text(json.dumps(proj))
    with pytest.raises(SlopError, match="frozen.*grey takes"):
        ledger.check_budget(p, "openrouter", add_usd=0.01, yes=True)
    with pytest.raises(SlopError, match="frozen"):
        ledger.check_budget(p, "higgsfield", add_credits=1, yes=True)
    row = ledger.record(p, provider="openrouter", model="m", kind="audio", est_usd=0.0000417)
    assert row["est_usd"] == 0.000042 and ledger.spent_usd(p) == 0.000042


# ---------------------------------------------------------------- the board <-> engine vocabulary
def test_engine_treatment_names_and_code_shots():
    assert engine_treatment({"treatment": "layer-separation"}) == engine_treatment({"treatment": "layers"}) == "layers"
    assert engine_treatment({"treatment": "push"}) != engine_treatment({"treatment": "rack"})
    assert is_code({"treatment": "motion"}) and is_code({"treatment": "pure-motion"})


def test_audit_repeat_across_vocabularies_and_graphic_note_clears(tmp_path):
    p = synth.make_project(tmp_path)
    draft.run(p)
    d0 = synth.load(p, "board/shots.json")
    assert any("explaining graphic" in (s.get("notes") or "") for s in d0["shots"]), "the draft writes the reminder"
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    for s, s0 in zip(S["shots"], d0["shots"]):
        s["notes"] = s0.get("notes", "")        # keep the draft's reminders: the graphics gate clears them
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["gates"]["graphics"]["ok"], rep["gates"]["graphics"]
    assert rep["gates"]["todo"]["ok"], rep["gates"]["todo"]
    idx = [i for i, s in enumerate(S["shots"]) if s["motion_tier"] == "plate3d"]
    a, b = idx[0], idx[1]                       # consecutive 2.5D shots as the audit sees them
    S["shots"][a]["treatment"], S["shots"][b]["treatment"] = "layer-separation", "layers"
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert not rep["gates"]["treatments"]["ok"]
    assert any(S["shots"][a]["id"] in m and S["shots"][b]["id"] in m for m in rep["gates"]["treatments"]["fails"])


def test_draft_keeps_print_texture_out_of_native_and_sung_windows_have_words(tmp_path):
    p = synth.make_project(tmp_path)
    draft.run(p)
    S = synth.load(p, "board/shots.json")
    assert "reproduction" not in {s.get("treatment") for s in S["shots"]}
    W = synth.load(p, "analysis/words.json")["words"]
    byid = {s["id"]: s for s in S["shots"]}
    for c in S["seedance"]:
        if c["kind"] != "sung":
            continue
        a, b = byid[c["shots"][0]]["t0"], byid[c["shots"][-1]]["t1"]
        assert any(a - .02 <= w["t0"] < b - .08 for w in W), f"{c['clip']}: a sung window with no word in its shots"


# ---------------------------------------------------------------- shots without a picture
def test_shots_without_picture_reach_status(capsys, tmp_path):
    p = synth.make_project(tmp_path)
    draft.run(p)
    assert util.shots_without_picture(p) is None                     # no EDL yet
    S = synth.load(p, "board/shots.json")
    code_id = S["shots"][1]["id"]
    S["shots"][1]["treatment"] = "pure-motion"
    synth.write_json(p / "board/shots.json", S)
    synth.write_json(p / "edit/edl.json", {S["shots"][0]["id"]: {"plate": "p001"}})
    blank = util.shots_without_picture(p)
    assert S["shots"][0]["id"] not in blank and code_id not in blank and S["shots"][2]["id"] in blank
    st = {x["stage"]: x for x in core_cli.evaluate_stages(p, json.loads((p / "project.json").read_text()))}
    assert not st["edit"]["done"] and "no picture" in st["edit"]["detail"]


# ---------------------------------------------------------------- brief
def test_brief_command_fills_the_ask_once(capsys):
    rc, out = run(capsys, "--json", "new", "brief-song")
    pdir = Path(out["project"])
    st = {x["stage"]: x for x in core_cli.evaluate_stages(pdir, json.loads((pdir / "project.json").read_text()))}
    assert not st["brief"]["done"] and "brief" in st["brief"]["cmd"]
    rc, out = run(capsys, "--json", "-p", "brief-song", "brief", "make it feel like a launch event", "--date", "2026-10-01")
    assert rc == 0 and out["added"]
    rc, out = run(capsys, "--json", "-p", "brief-song", "brief", "make it feel like a launch event")
    assert rc == 0 and not out["added"]
    assert core_cli.brief_ask(pdir).count("launch event") == 1 and "2026-10-01" in core_cli.brief_ask(pdir)
    st = {x["stage"]: x for x in core_cli.evaluate_stages(pdir, json.loads((pdir / "project.json").read_text()))}
    assert st["brief"]["done"]


# ---------------------------------------------------------------- plates
def test_pick_all_first_is_idempotent(tmp_path):
    p = synth.make_project(tmp_path)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    synth.write_json(p / "board/shots.json", S)
    for i, key in enumerate(sorted({s["plate"] for s in S["shots"] if s.get("plate")})):
        synth.make_image(tmp_path / "dl" / f"{key}-1.png", 160, 90, seed=i)
    plates.ingest(p, str(tmp_path / "dl"))
    first = plates.pick(p, [], all_first=True)
    assert first["picked"]
    again = plates.pick(p, [], all_first=True)
    assert again["picked"] == [] and "nothing new to pick" in again["text"]
    with pytest.raises(SlopError, match="nothing to pick"):
        plates.pick(p, [], all_first=False)


# ---------------------------------------------------------------- display starter
def test_display_starter_counts_hyphenated_words():
    from slop.audio.align import split_words
    from slop.audio.display import starter_line
    line = "Plus twenty-five is minus seventeen at nine a.m., A G I era"
    out = starter_line(line)
    assert "twenty-five|2" in out and "AGI|3" in out
    total = sum(int(t.split("|")[1]) if "|" in t else 1 for t in out.split())
    assert total == len(split_words(line))


# ---------------------------------------------------------------- gen
def test_gate_ok_needs_the_approval_to_cover_this_clip():
    from slop.gen.clips import gate_ok
    clip = {"id": "c01", "kind": "sung", "model": "m", "provider": "openrouter", "start": "a.jpg", "words": "hi",
            "body": {"prompt": "p", "duration": 5}}
    proj = {"gates": {"prompts_approved": True}, "gates_meta": {"prompts_approved": {"covers": {
        "clips/c01.json": core_cli.clip_prompt_sig(clip)}}}}
    assert gate_ok(proj, clip)
    changed = {**clip, "body": {"prompt": "rewritten after the approval", "duration": 5}}
    assert not gate_ok(proj, changed)
    assert not gate_ok({"gates": {"prompts_approved": False}}, clip)


def test_cut_window_past_the_song_end_is_fatal(tmp_path, monkeypatch):
    from slop.gen import clips
    import slop.audio.window as W

    def boom(*a, **k):
        raise SlopError("window 40.00-48.00 s ends past the song (duration 45.00 s; only 5.00 s of audio)")
    monkeypatch.setattr(W, "make_window", boom)
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio/song.wav").write_bytes(b"")
    with pytest.raises(SlopError, match="ends inside the song"):
        clips.cut_window(tmp_path, "c09", 40.0, 8.0, "motion")
