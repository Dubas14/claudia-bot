"""Locks for the skills fixes after the live Studio-tier run inside a real Grok Bot (e2e/STUDIO-E2E.md: PASS with a
lip-sync caveat; 92 s chorus excerpt, 31 shots, 7 sung clips, ~16 user turns of which 8 were "continue").

1. Turn cuts: Grok Bot ends a turn silently ~5-6 min into a long tool call, so THE TURN RULE (profile, once) makes the
   bot post the status, the time left and the continue line FIRST, before any wait over ~2 min, then keep waiting and
   give the result when it returns (or on "continue").
2. Sung clips use the SHORT sung template (sung head quoting every word, <= 1 line of framing and light, <= 1-2 timed
   beats, no cuts, no head turns); the timestamped screenplay is for motion clips and the board. Measured: c01 0 % ->
   78 %, c04 13 % -> 29 % in sync. Sung plates keep the mouth clear (a mic at her mouth held c06 to 26 %). A window that
   did not copy on a long prompt is retaken short before it is re-routed.
3. A board changed after the owner approved it (the layer-check fix): one line saying so, then re-approval.
4. Higgsfield credits: only what `transactions` charged; a failed or refused finalize counts 0 (the project log said
   114 credits, the real spend was 66).

From the adversarial pass over those fixes (each found by running the skill's own commands):
- clips step 14 linked a clip made after the board with `board set SHOT --tier motion --clip CLIP`, which refuses a
  sung clip; `board set SHOT --clip CLIP` takes the clip's kind, so one command fits both;
- clips step 9 told the bot to "do the next step it prints" after recording a request the connector rejected before it
  had a job id; for a refused finalize that printed advice re-locks and resubmits the clip as a NEW paid draft. A
  rejection now gets `--failed 'rejected: ...'` (what the request file's REJECTED step and `slop status` expect), a line
  to the owner, and a stop; a failed or refused finalize is retried only on the owner's yes;
- clips step 13 pointed to ARCHITECTURE §7b (no short-first step there; a bare §8 would have read as docs/60 §8, the
  cost section): it names docs/61 §8, which has the full order; "never a third OpenRouter try" counts short-form takes
  (the c01 short retake that reached 78 % was its third OpenRouter take);
- step 6's "never resubmit a clip that has a job id" read as "no retake ever" next to step 13's same-provider retake;
- the audit lists sung-shot mouth warnings first, but warnings are not gates and storyboard step 4 fixed only gates;
  `plates pick --all-first` can pick a plate with a microphone at her mouth (c06): both steps now check the mouth.

The skills sit a few bytes under their budgets, so a later trim must not silently undo any of these. No network.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
sys.path.insert(0, str(ROOT))

from slop import cli, ledger, util  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_recipe_studio", SKILLS / "build_recipe.py")
BR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BR)

SKILL = {s: SKILLS / s / "SKILL.md" for s in BR.ORDER + BR.PRODUCTION + BR.PARKED}
SOURCES = list(SKILL.values()) + [SKILLS / "profile.md", SKILLS / "memory.md"] + sorted((SKILLS / "routines").glob("*.md"))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def profile() -> str:
    return BR.front_matter(read(SKILLS / "profile.md"))[1]


def line_with(text: str, needle: str) -> str:
    return next(ln for ln in text.splitlines() if needle in ln)


def in_order(text: str, *parts: str) -> bool:
    idx = [text.index(p) for p in parts]
    return idx == sorted(idx)


def cmds(line: str) -> list[str]:
    """The `slop --json -p NAME ...` commands of one skill line, in order (what follows `-p NAME`)."""
    return re.findall(r"`slop --json -p NAME ([^`]+)`", line)


def _slop(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


def parses(cmd: str, fill: dict[str, str]) -> bool:
    for k, v in fill.items():
        cmd = cmd.replace(k, v)
    try:
        cli.build_parser().parse_args(util.hoist_global_flags(["--json", "-p", "demo", *shlex.split(cmd)]))
    except SystemExit:
        return False
    return True


# ---------------------------------------------------------------- 1. the continue line comes BEFORE a long wait
def test_the_turn_rule_posts_the_continue_line_before_a_long_wait():
    rule = line_with(profile(), "THE TURN RULE")
    for must in ("Turns end silently ~5 min in", "before any wait over ~2 min", "FIRST post the status and the time left",
                 'ending: Say "continue" and I carry on', "Then wait:", 'Done (or on "continue"): the result first'):
        assert must in rule, must
    assert in_order(rule, "before any wait over ~2 min", 'Say "continue" and I carry on',
                    "`slop --json relay read --wait 200`", "the result first"), \
        "the owner sees the continue line before the wait the platform may cut"
    assert "Still running: the time left, then end with" not in rule, "the old order: the line only after the waits"


def test_every_long_wait_in_the_skills_runs_by_the_turn_rule():
    """The waits that run past ~2 min (clip polls 70-130 s a clip, Higgsfield renders 4-11 min, frames 15-30 min) are
    waits of the profile's rule, so the continue line goes out first; none restates its own ending."""
    clips = read(SKILL["clips"])
    assert "turn rule (70-130 s a clip)" in line_with(clips, "clip poll --wait 300")
    assert "a wait of the profile's turn rule (renders take 4-11 min)" in line_with(clips, "jobs_wait (timeout_seconds 15)")
    assert "wait by the profile's turn rule" in line_with(read(SKILL["render-and-review"]), "Long steps are jobs")
    assert "wait by the profile's turn rule" in line_with(read(SKILL["mv-studio"]), "7. Long runs")


# ---------------------------------------------------------------- 2. sung clips: the short template; mouth clear
def test_sung_clips_use_the_short_template_and_motion_the_screenplay():
    step = line_with(read(SKILL["clips"]), "2. Timing for each clip")
    for must in ("Screenplay for acting and motion, short for copy.", "Sung clips: the short sung form (§4.0, template "
                 "in §5)", "the head quoting every word", "one line of framing and light", "at most 2 timed beats",
                 "no cuts, no head turns", "about 90 words", "a long prompt makes the model re-sing instead of copy",
                 "the drama goes in the entry's story line",
                 "Motion clips: the screenplay (§4.1), timestamps to 0.01 s on real word and kick times"):
        assert must in step, must
    assert in_order(step, "Sung clips:", "Motion clips:")
    sung = step[step.index("Sung clips:"):step.index("Motion clips:")]
    assert "timestamps" not in sung and "0.01 s" not in sung, "no screenplay timing in the sung part"
    for p in SOURCES:                               # nothing tells the bot to write sung clips as screenplays any more
        assert not re.search(r"(?i)screenplay prompt book|sung (?:clips?|windows?)[^.]*as (?:a )?screenplays?", read(p)), p
    studio = line_with(read(SKILL["mv-studio"]), "6. Sung clips")
    assert ("screenplay for acting and motion, short for copy: every sung window takes the short sung form "
            "(docs/60-clips.md §4.0)") in studio
    doc = read(ROOT / "docs" / "60-clips.md")
    assert "@Image1 sings @Audio1." in doc and "short for copy" in doc, "the docs/60 wording the skills follow"


def test_sung_plates_keep_the_mouth_clear():
    clear = "nothing in front of"
    what = "(no microphone, hand or hair)"
    for slug, needle in (("clips", "2. Timing for each clip"), ("mv-studio", "6. Sung clips"),
                         ("storyboard", "- Prompts:")):
        ln = line_with(read(SKILL[slug]), needle)
        assert clear in ln and what in ln, slug
    assert "else re-pick or re-roll it first (skill plates)" in line_with(read(SKILL["clips"]), "2. Timing")
    from slop.board import common                    # the words the plate book writes into every sung plate prompt
    if hasattr(common, "mouth_clause"):
        assert what in common.mouth_clause({}) and "mouth fully visible" in common.mouth_clause({})


def test_a_long_prompt_non_copy_is_retaken_short_before_rerouting():
    clips = read(SKILL["clips"])
    step = line_with(clips, "13. Routing for a sung window")
    assert in_order(step, "takes from a long prompt that did not copy: rewrite it short and retake on the same provider "
                    "first (steps 2-4)", "two OpenRouter takes of the short form that do not copy the lips",
                    "Higgsfield 480p draft", "else cut away", "Never a third short OpenRouter try")
    # the order lives in docs/61-lipsync.md §8 (short first, then the routing rule, then cut away); a bare § in a skill
    # belongs to the last doc named before it (step 12 names docs/61), and ARCHITECTURE §7b has no short-first step
    assert step.startswith("13. Routing for a sung window (docs/61 §8):")
    assert re.findall(r"docs/[\w.-]+\.md", clips[:clips.index("13. Routing")])[-1] == "docs/61-lipsync.md"
    lip = read(ROOT / "docs" / "61-lipsync.md")
    sec8 = lip[lip.index("## 8."):]
    assert in_order(sec8, "Try the short form first", "Then the routing rule", "Then cut away")
    studio = line_with(read(SKILL["mv-studio"]), "6. Sung clips")
    assert "Takes from a long prompt that did not copy: retake short on the same provider before any re-route." in studio
    # a retake is a new request: the resubmit rule must not read as "a clip with a take never goes again"
    six = line_with(clips, "6. `slop --json -p NAME clip submit CLIP --dry-run`")
    assert "Never resubmit a request that got a job id." in six and "a clip that has a job id" not in six


# ---------------------------------------------------------------- 3. a board changed after G4 asks again
def test_a_board_change_after_approval_is_said_and_re_approved():
    approve = "`slop --json -p NAME board approve --note '<their words>'`"
    layers = line_with(read(SKILL["render-and-review"]), "render check --layers")
    assert in_order(layers, "fix any shot under 3 layers at the source", "A fix that changes the approved board",
                    "say so in one line", "ask the owner to re-approve", "on their yes " + approve)
    g4 = line_with(read(SKILL["storyboard"]), "7. The owner's yes")
    assert "Any later board change: say so in one line, ask them to re-approve." in g4
    link = line_with(read(SKILL["clips"]), "14. ")              # a clip linked after the board changes the board too
    assert in_order(link, "`slop --json -p NAME board set SHOT --clip CLIP`", "the owner re-approves", "edit edl")
    assert "--tier motion" not in link, "the tier follows the clip's kind: --tier motion refuses a sung clip"


def test_smoke_the_re_approval_command_clears_a_stale_board(tmp_path, monkeypatch):
    """The layer-check fix as the live run did it: the approved board changes (a `board set`), the board gate goes
    stale, and the skill's own re-approval command (render-and-review step 3) makes it current again."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))
    sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "board"))
    import board_synth as synth
    from slop.board import draft
    p = synth.make_project(tmp_path)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    synth.write_json(p / "board/shots.json", S)
    code, out = _slop("-p", str(p), "board", "approve", "--note", "owner: go")
    assert code == 0 and out["approved"], out
    code, out = _slop("-p", str(p), "board", "set", S["shots"][0]["id"], "--camera", "static")
    assert code == 0, out
    code, out = _slop("-p", str(p), "gate", "board")
    assert code == 0 and out["current"] is False and out["stale"], out
    cmd = [c for c in cmds(line_with(read(SKILL["render-and-review"]), "render check --layers"))
           if c.startswith("board approve")]
    assert len(cmd) == 1
    code, out = _slop("-p", str(p), *shlex.split(cmd[0].replace("<their words>", "yes, the fix is fine")))
    assert code == 0 and out["approved"], out
    code, out = _slop("-p", str(p), "gate", "board")
    assert code == 0 and out["current"] is True and not out["stale"], out
    assert "yes, the fix is fine" in (p / "DECISIONS.md").read_text(encoding="utf-8")


def test_smoke_clips_made_after_the_board_play_once_linked(tmp_path, monkeypatch):
    """Defect 3 of the live run (motion clips made, never in the edit), run with the clips skill's step-14 command on
    an approved board: a motion clip over two shots and a sung clip each get linked by the SAME command (the tier
    follows the clip's kind; the first draft of this line said `--tier motion`, which refuses a sung clip), the board
    gate goes stale, the edit plays the motion clip, and the render-and-review re-approval makes the gate current."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))
    sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "board"))
    import board_synth as synth
    from slop.board import draft, plates
    p = synth.make_project(tmp_path)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    synth.write_json(p / "board/shots.json", S)
    for i, key in enumerate(sorted({s["plate"] for s in S["shots"] if s.get("plate")})):
        synth.make_image(tmp_path / "dl" / f"{key}-1.png", 320, 180, seed=i)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [], all_first=True)
    code, out = _slop("-p", str(p), "board", "approve", "--note", "owner: go")
    assert code == 0 and out["approved"], out
    S = synth.load(p, "board/shots.json")
    s1, s2 = S["shots"][0], S["shots"][1]
    uses = [s.get("plate") for s in S["shots"]]
    late = next(s for s in S["shots"] if s["t0"] > s2["t1"] + 6 and s["motion_tier"] == "plate3d"   # a shot of its own
                and s.get("plate") and uses.count(s["plate"]) == 1 and s["t1"] - s["t0"] < 7)
    (p / "clips/c08").mkdir(parents=True)
    (p / "clips/c08/take-1.mp4").write_bytes(b"\x00" * 16)
    synth.write_json(p / "clips/c08.json", {
        "id": "c08", "shot": s1["id"], "kind": "motion", "status": "delivered", "provider": "openrouter",
        "song_t0": 0.0, "needed": [s1["t0"], s2["t1"]], "body": {"duration": 6}, "start": "plates/cands/p001/1.jpg",
        "takes": [{"file": "clips/c08/take-1.mp4", "status": "delivered", "sync": {}}]})
    link = cmds(line_with(read(SKILL["clips"]), "14. "))[0]
    assert link == "board set SHOT --clip CLIP"

    def linked(shot, clip):
        return _slop("-p", str(p), *shlex.split(link.replace("SHOT", shot).replace("CLIP", clip)))

    code, out = linked(f"{s1['id']}-{s2['id']}", "c08")              # a motion clip over two shots
    assert code == 0 and out["linked"] == {s1["id"]: "c08", s2["id"]: "c08"} and out["gate_stale"], out
    code, out = _slop("-p", str(p), "gate", "board")
    assert code == 0 and out["current"] is False and out["stale"], "a link is a board change: the owner re-approves"
    code, out = _slop("-p", str(p), "edit", "edl")
    assert code == 0, out
    assert synth.load(p, "edit/edl.json")[s2["id"]]["segs"][0]["clip"] == "c08-t1", "the edit plays the linked clip"
    approve = next(c for c in cmds(line_with(read(SKILL["render-and-review"]), "render check --layers"))
                   if c.startswith("board approve"))
    code, out = _slop("-p", str(p), *shlex.split(approve.replace("<their words>", "yes, play c08 there")))
    assert code == 0 and out["approved"], out
    code, out = _slop("-p", str(p), "gate", "board")
    assert code == 0 and out["current"] is True, out
    # a sung clip made after the board: the old `--tier motion` form refuses it, the skill's command links it
    synth.write_json(p / "clips/c09.json", {"id": "c09", "shot": late["id"], "kind": "sung", "status": "draft",
                                            "song_t0": round(late["t0"] - .3, 3), "body": {"duration": 8}, "takes": []})
    code, out = _slop("-p", str(p), "board", "set", late["id"], "--tier", "motion", "--clip", "c09")
    assert code != 0 and "a motion shot plays a motion clip" in out["error"], out
    code, out = linked(late["id"], "c09")
    assert code == 0 and out["linked"] == {late["id"]: "c09"} and out["gate_stale"], out
    assert next(s for s in synth.load(p, "board/shots.json")["shots"] if s["id"] == late["id"])["motion_tier"] == "sung"


def test_sung_mouth_checks_at_the_audit_and_the_pick():
    """The plate is the lip-sync start frame (c06: a microphone at her mouth held 26 % with either prompt). The audit
    lists sung-shot mouth warnings first, but warnings are not gates: the storyboard skill fixes them in the audit loop,
    and the plates skill checks every sung pick before a clip is drafted on it."""
    audit_step = line_with(read(SKILL["storyboard"]), "board audit`. Fix exactly the gates it names")
    assert in_order(audit_step, "Fix exactly the gates it names", "and every mouth warning it lists first (a sung shot)",
                    "Repeat until every gate passes")
    pick = line_with(read(SKILL["plates"]), "plates pick --all-first")
    assert in_order(pick, "plates pick --all-first", "Then check each sung shot's pick: the whole mouth, nothing in "
                    "front of it (no microphone, hand or hair); else pick another.")
    from slop.board import audit                       # the warning the storyboard step means, and where it sits
    src = read(ROOT / "slop" / "board" / "audit.py")
    if "_mouth_warnings" in src:
        assert "warnings[:0] = mouth" in src and hasattr(audit, "_mouth_warnings")


# ---------------------------------------------------------------- 4. Higgsfield: only the credits charged
def test_higgsfield_credits_are_the_charged_ones():
    clips = read(SKILL["clips"])
    poll = line_with(clips, "jobs_wait (timeout_seconds 15)")
    assert "`slop --json -p NAME clip ingest CLIP --url 'URL' --job-id ID --credits CREDITS` (CREDITS = what " \
           "`transactions` charged for that job)" in poll
    assert in_order(poll, "Failed: `slop --json -p NAME clip ingest CLIP --failed '<the reason, verbatim>'` (its credits "
                    "come off the log), then the next step it prints.",
                    "Rejected, no job id (how_to_run's REJECTED step): `slop --json -p NAME clip ingest CLIP --failed "
                    "'rejected: <the reply, verbatim>'`, tell the owner, stop.")
    assert "do the next step it prints" not in poll, "a rejection's printed retry advice is for a new take: it stops"
    fin = line_with(clips, "10. Finalize a kept 480p draft")
    assert "the same steps 8-9" in fin
    assert ("A failed or refused finalize counts 0 and the draft stays; a retry, or a second finalize of one draft "
            "(`--again`), only on the owner's yes.") in fin
    assert "Higgsfield: only what `transactions` charged (the project log is an estimate)" in line_with(clips, "14. ")
    for c in cmds(poll):
        assert parses(c, {"CLIP": "W01", "'URL'": "https://x.test/a.mp4", "ID": "j1", "CREDITS": "12",
                          "'<the reason, verbatim>'": "'filter'", "<the reply, verbatim>": "balance too low"}), c
    hf = read(ROOT / "slop" / "gen" / "higgsfield.py")          # the request file's own REJECTED step says the same
    assert "REJECTED" in hf and "rejected: " in hf


_H = ROOT / "tests" / "fixtures" / "gen" / "helpers.py"
_hs = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_hs); sys.modules.setdefault("gen_test_helpers", H); _hs.loader.exec_module(H)
H = sys.modules["gen_test_helpers"]
DRAFT_JOB = "0f8fad5b-d9cb-469f-a165-70867728950e"


@pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
def test_smoke_a_refused_finalize_counts_no_credits(tmp_path, monkeypatch):
    """The live run's ledger: a 480p draft (charged 15 per `transactions`, the file said 12), kept and finalized
    (~48 credits expected), the connector refused the finalize before it got a job id. Run as the clips skill says:
    a submit the connector rejects (no job id) goes in with the step-9 Rejected line and can go again once the owner
    says so; the ingest takes the charged credits; the refused finalize goes in with the same Rejected line; and the
    project log then counts only the 15 credits really charged."""
    from slop.gen import hosting, store
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.setattr(hosting, "status", lambda: {"running": False, "url": None})
    H.write_cache(tmp_path / "home")
    env = H.make_project(tmp_path / "projects", audio=True)

    def run(*argv):
        return _slop("--project", str(env), *argv)

    code, out = run("clip", "new", "s002", "--kind", "sung", "--id", "W01", "--provider", "higgsfield")
    assert code == 0, out
    c = store.load(env, "W01")
    short = (f'@Image1 sings @Audio1. She lip-syncs to @Audio1 exactly, every word in time: "{c["words"]}". '
             "Close-up of the woman from @Image1 singing softly into the lens. Soft window light. "
             "Locked camera, no cuts, no head turns.")
    f = tmp_path / "W01.txt"
    f.write_text(short, encoding="utf-8")
    assert run("clip", "set", "W01", "--prompt-file", str(f))[0] == 0
    code, out = run("clip", "lock", "W01")
    assert code == 0, out
    clips = read(SKILL["clips"])
    done = cmds(line_with(clips, "jobs_wait (timeout_seconds 15)"))
    rejected = next(x for x in done if "'rejected: <the reply, verbatim>'" in x)

    def rejected_cmd(reply):
        return shlex.split(rejected.replace("CLIP", "W01").replace("<the reply, verbatim>", reply))

    # a draft the connector rejects before it has a job id (the balance was too low): nothing charged, the clip can go
    # again once the owner says so
    assert run("clip", "submit", "W01", "--yes", "--res", "480p")[0] == 0
    assert ledger.spent_credits(env) == 12, "the request is ledgered at the file's estimate"
    code, out = run(*rejected_cmd("insufficient credits"))
    assert code == 0, out
    assert ledger.spent_credits(env) == 0, "a rejected request was never charged"
    assert store.load(env, "W01")["takes"][0]["status"] == "failed"
    assert run("clip", "submit", "W01", "--yes", "--res", "480p")[0] == 0
    mp4 = H.make_mp4(tmp_path / "take1.mp4", env / store.load(env, "W01")["window"]["wav"], duration=4)
    assert run("clip", "ingest", "W01", "--job-id", DRAFT_JOB, "--pending")[0] == 0
    fill = {"CLIP": "W01", "--url": "--file", "URL": str(mp4), "ID": DRAFT_JOB, "CREDITS": "15"}
    ingest_ok = [fill.get(w, w) for w in shlex.split(next(x for x in done if "--credits CREDITS" in x))]
    code, out = run(*ingest_ok)
    assert code == 0, out
    assert ledger.spent_credits(env) == 15, "the draft counts what transactions charged, not the file's 12"
    c = store.load(env, "W01")
    draft = c["takes"][-1]
    assert draft["status"] == "delivered" and draft["n"] == 2
    draft["sync"] = {"mode": "copy", "ncc": .49, "lag_s": .475, "synced": [[10.0, 11.5]]}
    store.save(env, c)
    fill["TAKE"] = str(draft["n"])
    fin = cmds(line_with(clips, "10. Finalize a kept 480p draft"))[0]
    code, out = run(*[fill.get(w, w) for w in shlex.split(fin)])
    assert code == 0 and out["expected_credits"] == 48, out
    assert ledger.spent_credits(env) == 63, "the finalize request is ledgered as an estimate until it is settled"
    code, out = run(*rejected_cmd("draft is not eligible for finalization"))
    assert code == 0, out
    assert ledger.spent_credits(env) == 15, "a refused finalize was never charged: it must not count"
    c = store.load(env, "W01")
    assert c["takes"][-1]["status"] == "failed" and c["takes"][-1]["finalize_of"] == draft["n"]
    assert c["takes"][-2]["status"] == "delivered", "the draft stays the clip's take"
    code, st = run("clip", "status", "W01")
    assert code == 0 and "rejected" in st["text"], st
