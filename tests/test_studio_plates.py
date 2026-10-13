"""Studio-tier live run fixes, plates track (e2e/STUDIO-E2E.md defects 2, 3 and 6):

1. sung shots: every sung plate's prompt carries "her mouth fully visible, nothing in front of her mouth (no
   microphone, hand or hair)" (plates book, Midjourney and API), and `board audit` warns when a sung shot's prompt puts
   a microphone or a hand at her mouth;
2. a motion clip made after the board (c08, made for s001-s002) is linked with `board set SHOT --tier motion --clip
   c08`, validated, and `edit edl` plays it;
3. a change to an approved board prints one warning line: the board gate is stale, re-approve.

Synthetic projects only; no network, no paid call."""
from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop import cli, core_cli  # noqa: E402
from slop.board import audit, draft, plates, shotedit  # noqa: E402
from slop.board.common import (board_gate_stale, clip_kinds, mouth_blockers, mouth_clause,  # noqa: E402
                               sung_shot_ids)
from slop.config import SlopError  # noqa: E402
from slop.edit import edl  # noqa: E402

MOUTH = "her mouth fully visible, nothing in front of her mouth (no microphone, hand or hair)"
MJ_MOUTH = "her mouth fully visible, nothing in front of her mouth"          # Midjourney: no object named
HEADSET = ("her mouth fully visible, nothing in front of her mouth (the headset microphone at her cheek, clear of her "
           "lips; no hand or hair)")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


def _board(p: Path) -> dict:
    return synth.load(p, "board/shots.json")


def _filled(tmp_path: Path, **kw) -> tuple[Path, dict]:
    p = synth.make_project(tmp_path, **kw)
    draft.run(p)
    S = synth.fill_todos(_board(p))
    synth.write_json(p / "board/shots.json", S)
    return p, S


def _picked(tmp_path: Path, **kw) -> tuple[Path, dict]:
    p, S = _filled(tmp_path, **kw)
    for i, key in enumerate(sorted({s["plate"] for s in S["shots"] if s.get("plate")})):
        synth.make_image(tmp_path / "dl" / f"{key}-1.png", 320, 180, seed=i)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [], all_first=True)
    return p, _board(p)


def _sung_plates(S: dict) -> set[str]:
    return {s["plate"] for s in S["shots"] if s["motion_tier"] == "sung"}


# ------------------------------------------------------------------------------------------------ 1. sung plates
def test_mouth_blockers_finds_mics_and_hands_but_not_negations():
    assert mouth_blockers("close-up of her singing into a handheld microphone, red light") == ["handheld microphone"]
    assert mouth_blockers("medium shot, she holds a mic, smoke") == ["mic"]
    assert mouth_blockers("one hand pressed to her lips, eyes closed") == ["hand pressed to her lips"]
    assert mouth_blockers("fingers at her mouth") == ["fingers at her mouth"]
    assert mouth_blockers("her palms pressed against her lips") == ["palms pressed against her lips"]
    assert mouth_blockers("fingertips to his lips") == ["fingertips to his lips"]
    assert mouth_blockers("a hand-held camera follows her, her hand on her chest") == []
    assert mouth_blockers("a silk scarf pulled over her mouth") == ["over her mouth"]
    assert mouth_blockers("a shouting man with a megaphone") == ["megaphone"]
    for clean in (MOUTH, "no microphone or hand near her mouth", "without a mic, mouth open",
                  "a thin headset microphone at her cheek", "her hands in her pockets, mouth wide open",
                  "nothing in front of her mouth", "a comic-book panel", ""):
        assert mouth_blockers(clean) == [], clean
    assert mouth_blockers("a thin headset microphone, singing") == ["headset microphone"]   # no cheek: at the mouth
    assert mouth_clause({"lead": {"pronoun": "he"}}) == MOUTH.replace("her", "his")
    assert mouth_clause({}) == MOUTH
    assert mouth_clause({}, mj=True) == MJ_MOUTH                # MJ draws what a prompt names: no object words
    # a canon headset is a prop that stays: the clause says where, never "no microphone"
    assert mouth_clause({}, "close-up of her, a thin headset microphone at her cheek, singing") == HEADSET
    for clause in (MOUTH, MJ_MOUTH, HEADSET):
        assert mouth_blockers(clause) == [], clause


def test_book_adds_the_mouth_line_to_sung_plates_only_midjourney(tmp_path):
    p, S = _filled(tmp_path)                                   # studio: a Midjourney board
    sung = _sung_plates(S)
    assert sung, "the synthetic studio board plans sung windows"
    r = plates.book(p)
    jobs = {j["plate"]: j for j in synth.load(p, "plates/mj/b01.json")["jobs"]}
    for key, j in jobs.items():
        if key in sung:
            # MJ draws what a prompt names, "no microphone" included: the positive clause only
            assert j.get("sung") is True and j["prompt"].count(MJ_MOUTH) == 1, j["prompt"]
            assert j["prompt"].endswith(MJ_MOUTH + ", no text, no letters, no logos")     # before the closer
            assert "microphone" not in j["prompt"] and "hand" not in j["prompt"], j["prompt"]
        else:
            assert "sung" not in j and "mouth fully visible" not in j["prompt"], key
    paste = "".join((p / "plates/mj" / Path(b["file"]).name).read_text(encoding="utf-8") for b in r["blocks"])
    assert MJ_MOUTH.replace(",", "\\,") in paste               # the permutation paste escapes its comma
    book = (p / "plates/prompts.md").read_text(encoding="utf-8")
    assert "· sung (mouth fully visible)" in book and "sung plates (" in r["text"] and MJ_MOUTH in r["text"]
    # a prompt that already says it is not doubled; re-booking is stable
    owner = next(s for s in S["shots"] if s["plate"] in sung and s.get("mj_prompt"))
    owner["mj_prompt"] = "close-up of {lead} singing, her mouth fully visible, a white hall"
    synth.write_json(p / "board/shots.json", S)
    plates.book(p)
    j = next(j for j in synth.load(p, "plates/mj/b01.json")["jobs"] if j["plate"] == owner["plate"])
    assert j["prompt"].lower().count("mouth fully visible") == 1


def test_a_canon_headset_is_kept_on_sung_plates(tmp_path):
    """docs/50 §5's canon carries "a thin headset microphone at her cheek": a sung plate never tells the model "no
    microphone" (it would drop a canon prop): the API clause says where the headset stays."""
    for tier, where in (("studio", "plates/mj/b01.json"), ("quick", "plates/jobs.json")):
        p, S = _filled(tmp_path / tier, tier=tier)
        pj = synth.load(p, "project.json")
        pj["lead"]["canon"] += ", a thin headset microphone at her cheek"
        synth.write_json(p / "project.json", pj)
        r = plates.book(p)
        sung = _sung_plates(S)
        jobs = {j["plate"]: j for j in synth.load(p, where)["jobs"]}
        lead_sung = [k for k in sung if "headset" in jobs[k]["prompt"]]
        assert lead_sung, tier
        for k in lead_sung:
            if tier == "studio":
                assert MJ_MOUTH in jobs[k]["prompt"] and "no microphone" not in jobs[k]["prompt"], jobs[k]
            else:
                assert HEADSET in jobs[k]["prompt"] and "no microphone" not in jobs[k]["prompt"], jobs[k]["prompt"]
        assert not any("sung plate" in w for w in r["warnings"]), r["warnings"]          # at her cheek: clear


def test_book_adds_the_mouth_line_to_api_jobs_and_lints_a_mic(tmp_path):
    p, S = _filled(tmp_path, tier="quick")                     # quick: an API-images board
    sung = _sung_plates(S)
    owner = next(s for s in S["shots"] if s["plate"] in sung and s.get("img_prompt"))
    owner["img_prompt"] = "close-up of {lead} singing into a handheld mic, a white hall, the left third empty"
    synth.write_json(p / "board/shots.json", S)
    r = plates.book(p)
    jobs = {j["plate"]: j for j in synth.load(p, "plates/jobs.json")["jobs"]}
    assert {k for k, j in jobs.items() if j.get("sung")} == sung
    for key in sung:
        assert MOUTH in jobs[key]["prompt"]
        assert MOUTH in (p / "plates/api" / f"{key}.txt").read_text(encoding="utf-8")
    assert not any(MOUTH in j["prompt"] for k, j in jobs.items() if k not in sung)
    assert any(owner["plate"] in w and "'handheld mic'" in w and "sung plate" in w for w in r["warnings"]), r["warnings"]
    # the lead's pronoun picks the possessive
    pj = synth.load(p, "project.json")
    pj["lead"]["pronoun"] = "he"
    synth.write_json(p / "project.json", pj)
    plates.book(p)
    his = {j["plate"] for j in synth.load(p, "plates/jobs.json")["jobs"] if MOUTH.replace("her", "his") in j["prompt"]}
    assert his == sung


def test_a_sung_primary_clip_makes_a_shot_sung(tmp_path):
    S = {"shots": [{"id": "s001", "t0": 0, "t1": 2, "motion_tier": "seedance", "clip": "c01", "plate": "p1"},
                   {"id": "s002", "t0": 2, "t1": 4, "motion_tier": "sung", "clip": "c02", "plate": "p2~2"},
                   {"id": "s003", "t0": 4, "t1": 6, "motion_tier": "motion", "clip": "c03", "plate": "p3"},
                   {"id": "s004", "t0": 6, "t1": 8, "motion_tier": "plate3d", "plate": "p4"},
                   {"id": "s005", "t0": 8, "t1": 10, "motion_tier": "motion", "clip": "c01", "plate": "p5"},
                   {"id": "s006", "t0": 10, "t1": 12, "motion_tier": "plate3d", "clips": ["c01"], "plate": "p6"}],
         "seedance": [{"clip": "c01", "kind": "sung", "shots": ["s001"]}, {"clip": "c03", "kind": "motion"}],
         "plates": []}
    kinds = clip_kinds(None, S)
    # a motion shot on a sung clip is lip-synced by the edit; a plate shot shows its plate whatever it lists
    assert sung_shot_ids(S, kinds) == {"s001", "s002", "s005"}
    assert plates.sung_plates(None, S) == {"p1", "p2", "p5"}    # a variant folds to its base plate


def test_audit_warns_first_about_a_mic_at_a_sung_mouth(tmp_path):
    p, S = _filled(tmp_path)
    rep = audit.audit(p)
    assert rep["stats"]["sung_shots"] > 0 and rep["stats"]["mouth_warnings"] == 0
    assert not any("sung shot" in w for w in rep["warnings"])
    sung = next(s for s in S["shots"] if s["motion_tier"] == "sung" and s.get("mj_prompt"))
    plain = next(s for s in S["shots"] if s["motion_tier"] == "plate3d" and s.get("mj_prompt"))
    sung["mj_prompt"] = "close-up of {lead} singing into a handheld microphone in a vast white hall, the left third empty"
    plain["mj_prompt"] = "medium shot of a vintage microphone on a stand in a vast white hall"      # not sung: fine
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["warnings"][0].startswith(f"{sung['id']} is a sung shot") and "'handheld microphone'" in rep["warnings"][0]
    assert not any(w.startswith(plain["id"]) for w in rep["warnings"])
    assert rep["ok"]                                                   # a warning, never a gate
    # every sung shot cut from that plate (one continuous take) is named: the plate is their common start frame
    on_plate = [s["id"] for s in S["shots"] if s["plate"] == sung["plate"] and s["motion_tier"] == "sung"]
    assert rep["stats"]["mouth_warnings"] == len(on_plate)
    assert [w.split(" ", 1)[0] for w in rep["warnings"][:len(on_plate)]] == on_plate
    # the fix names the shot whose prompt the book reads, never a shot that only shares the plate
    assert len(on_plate) > 1
    for w in rep["warnings"][1:len(on_plate)]:
        assert f"board set {sung['id']} --mj-prompt" in w and f"from {sung['id']}" in w, w
        assert f"board set {w.split(' ', 1)[0]} --mj-prompt" not in w, w
    # a hand at the lips in the action counts too; the mouth line itself does not
    sung["mj_prompt"] = f"close-up of {{lead}} in a vast white hall, {MOUTH}"
    sung["action"] = "she sings with one hand over her mouth, then drops it on the downbeat"
    synth.write_json(p / "board/shots.json", S)
    w = audit.audit(p)["warnings"][0]
    assert w.startswith(sung["id"]) and "action mentions" in w and "'hand over her mouth'" in w
    # a lead canon with a microphone at her mouth: one warning naming the sung shots
    sung["action"] = "she sings to the lens"
    synth.write_json(p / "board/shots.json", S)
    pj = synth.load(p, "project.json")
    pj["lead"]["canon"] += ", a thin headset microphone"
    synth.write_json(p / "project.json", pj)
    ws = audit.audit(p)["warnings"]
    canon = [x for x in ws if x.startswith("the lead canon")]
    assert len(canon) == 1 and "lead.canon" in canon[0] and sung["id"] in canon[0]
    pj["lead"]["canon"] = pj["lead"]["canon"].replace("headset microphone", "headset microphone at her cheek")
    synth.write_json(p / "project.json", pj)
    assert not any(x.startswith("the lead canon") for x in audit.audit(p)["warnings"])


def test_board_set_warns_on_a_mic_in_a_sung_shots_prompt(tmp_path):
    p, S = _filled(tmp_path)
    sung = next(s for s in S["shots"] if s["motion_tier"] == "sung" and s.get("mj_prompt"))
    r = shotedit.cmd_set(p, sung["id"], {"mj_prompt": "close-up of {lead} with a mic at her lips, a white hall"})
    assert any("sung plate" in w and "'mic'" in w for w in r["warnings"]), r["warnings"]
    plain = next(s for s in S["shots"] if s["motion_tier"] == "plate3d" and s.get("mj_prompt"))
    r = shotedit.cmd_set(p, plain["id"], {"mj_prompt": "close-up of {lead} with a mic at her lips, a white hall"})
    assert not any("sung plate" in w for w in r["warnings"])
    # turning that shot sung warns about the mic already in its prompt
    r = shotedit.cmd_set(p, plain["id"], {"tier": "sung"})
    assert any("sings now" in w and "'mic'" in w for w in r["warnings"]), r["warnings"]


# ------------------------------------------------------------------------------------------------ 2. link a clip
def _c08(p: Path, S: dict, **kw) -> dict:
    """c08: a motion clip `slop clip new s001 --kind motion --t0 <s001.t0> --t1 <s002.t1> --id c08` made after the
    board was approved, with one delivered take."""
    s1, s2 = S["shots"][0], S["shots"][1]
    f = p / "clips/c08/take-1.mp4"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\x00" * 16)
    c = {"id": "c08", "shot": "s001", "kind": "motion", "status": "delivered", "provider": "openrouter",
         "song_t0": 0.0, "needed": [s1["t0"], s2["t1"]], "body": {"duration": 6},
         "start": "plates/cands/p001/1.jpg",
         "takes": [{"file": "clips/c08/take-1.mp4", "status": "delivered", "sync": {}}], **kw}
    synth.write_json(p / "clips/c08.json", c)
    return c


def test_board_set_links_a_clip_made_after_the_board_and_the_edit_plays_it(tmp_path):
    p, S = _picked(tmp_path)
    s1, s2 = S["shots"][0], S["shots"][1]
    assert (s1["id"], s2["id"]) == ("s001", "s002") and s2["motion_tier"] == "plate3d"
    planned = s1["clip"]                                       # the draft planned c01 (never made) on s001
    assert planned and planned != "c08"
    _c08(p, S)
    rep = audit.audit(p)
    before = {g: v["ok"] for g, v in rep["gates"].items()}
    # unlinked, the plan's c01 (never made) and the made c08 both claim p001's picked frame, and c08 is off the plan
    assert any("start from the same frame" in f for f in rep["gates"]["plates_unique"]["fails"])
    assert any(w.startswith("clip c08 (made for s001) is not on the board's clip plan") and "--clip c08" in w
               for w in rep["warnings"]), rep["warnings"]
    edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s002"] == {"plate": "p002"}                      # the defect: c08 never reached s002
    code, out = _run("-p", str(p), "board", "set", "s001-s002", "--tier", "motion", "--clip", "c08")
    assert code == 0, out
    assert set(out["changed"]) == {"s001", "s002"} and out["linked"] == {"s001": "c08", "s002": "c08"}
    assert "edit edl" in out["text"]
    B = _board(p)
    b1, b2 = B["shots"][0], B["shots"][1]
    assert b1["clip"] == b2["clip"] == "c08" and b1["motion_tier"] == b2["motion_tier"] == "motion"
    assert b2["treatment"] is None and b2["plate"] == "p002"   # a clip shot: no 2.5D look; the plate stays as stand-in
    assert planned not in {c["clip"] for c in B["seedance"]}   # the never-made plan entry went with its last shot
    assert any(f"{planned} dropped" in n for n in out["notes"])
    r = edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s001"] == {"segs": [{"t0": 0.0, "clip": "c08-t1", "in": 0.0}]}
    assert E["s002"] == {"segs": [{"t0": round(s2["t0"], 3), "clip": "c08-t1", "in": round(s2["t0"], 3)}]}
    assert {x["id"]: x["src"] for x in r["rows"]}["s002"] == "clip c08 x1"
    rep = audit.audit(p)
    assert rep["ok"] and all(before[g] <= v["ok"] for g, v in rep["gates"].items()), rep["gates"]   # linked: all pass
    assert not any("c08" in w for w in rep["warnings"]), rep["warnings"]
    again = shotedit.cmd_set(p, "s001-s002", {"tier": "motion", "clip": "c08"})
    assert again["changed"] == {} and "no change" in again["text"]


def test_board_set_clip_validation_changes_nothing_on_a_bad_link(tmp_path):
    p, S = _picked(tmp_path)
    _c08(p, S)
    synth.write_json(p / "clips/c09.json", {"id": "c09", "shot": "s010", "kind": "sung", "status": "draft",
                                            "song_t0": 22.676, "body": {"duration": 8}, "takes": []})
    synth.write_json(p / "clips/c08-c1.json", {"id": "c08-c1", "parent": "c08", "kind": "motion", "song_t0": 1.0,
                                               "body": {"duration": 4}, "takes": []})
    late = next(s for s in S["shots"] if s["t0"] > 20 and s["motion_tier"] == "plate3d")
    before = (p / "board/shots.json").read_bytes()
    for fields, sid, msg in (
            ({"tier": "plate3d", "clip": "c08"}, "s002", "plays its plate, never a clip"),
            ({"tier": "sung", "clip": "c08"}, "s002", "a sung shot needs a sung clip"),
            ({"tier": "motion", "clip": "c09"}, "s010", "a motion shot plays a motion clip"),
            ({"clip": "c99"}, "s002", "neither made (clips/c99.json) nor on the board's clip plan"),
            ({"clip": "c08-c1"}, "s002", "is a divergence cover of c08"),
            ({"clip": "c08"}, late["id"], "shows nothing in this shot"),
            ({"tier": "teleport"}, "s002", "tier 'teleport' is not one of")):
        with pytest.raises(SlopError, match=re.escape(msg)):
            shotedit.cmd_set(p, sid, fields)
        assert (p / "board/shots.json").read_bytes() == before, fields
    # --clip alone takes the clip's kind as the tier; a partial cover warns
    r = shotedit.cmd_set(p, "s003", {"clip": "c08"})
    assert _board(p)["shots"][2]["motion_tier"] == "motion"
    assert any("motion_tier plate3d -> motion" in n for n in r["notes"])
    assert any("c08 covers 0.00–6.00 s" in w for w in r["warnings"]), r["warnings"]
    # a sung clip on a sung shot: linked, with the note that it has no delivered take yet
    r = shotedit.cmd_set(p, "s010", {"tier": "sung", "clip": "c09"})
    assert _board(p)["shots"][9]["clip"] == "c09" and any("no delivered take" in n for n in r["notes"])
    # --tier plate3d unlinks the clip; without a treatment it warns (the treatments gate needs one)
    r = shotedit.cmd_set(p, "s003", {"tier": "plate3d"})
    sh = _board(p)["shots"][2]
    assert sh["motion_tier"] == "plate3d" and sh["clip"] is None and any("unlinked c08" in n for n in r["notes"])
    assert any("without a treatment" in w for w in r["warnings"])
    r = shotedit.cmd_set(p, "s003", {"treatment": "relight"})
    assert _board(p)["shots"][2]["treatment"] == "relight"
    # --clip none on a clip shot unlinks it and names the fallback the edit would find
    shotedit.cmd_set(p, "s002", {"clip": "c08"})
    r = shotedit.cmd_set(p, "s002", {"clip": "none"})
    assert _board(p)["shots"][1]["clip"] is None and any("c08" in n and "made for it" in n for n in r["notes"])


def test_board_fill_links_clips_too(tmp_path):
    p, S = _picked(tmp_path)
    _c08(p, S)
    f = tmp_path / "link.jsonl"
    f.write_text('{"id": "s001", "tier": "motion", "clip": "c08"}\n{"id": "s002", "motion_tier": "motion", '
                 '"clip": "c08"}\n', encoding="utf-8")
    code, out = _run("-p", str(p), "board", "fill", str(f), "--check")
    assert code == 0 and out["check"] and _board(p)["shots"][1]["motion_tier"] == "plate3d"
    code, out = _run("-p", str(p), "board", "fill", str(f))
    assert code == 0, out
    assert [_board(p)["shots"][i]["clip"] for i in (0, 1)] == ["c08", "c08"]
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "s004", "tier": "sung", "clip": "c08"}\n', encoding="utf-8")
    code, out = _run("-p", str(p), "board", "fill", str(bad))
    assert code != 0 and "a sung shot needs a sung clip" in out["error"]


def test_audit_names_a_made_clip_the_edit_plays_nowhere(tmp_path):
    """The Studio run's defect: motion clips made after the board for plate3d shots never reached the edit, and every
    gate passed. The audit names such a clip with the exact link command; following it puts the clip in the edit."""
    p, S = _picked(tmp_path)
    s5, s6 = S["shots"][4], S["shots"][5]
    assert s5["motion_tier"] == s6["motion_tier"] == "plate3d" and not s5.get("clip")
    f = p / "clips/c09/take-1.mp4"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\x00" * 16)
    synth.write_json(p / "clips/c09.json", {
        "id": "c09", "shot": s5["id"], "kind": "motion", "status": "delivered", "song_t0": s5["t0"],
        "needed": [s5["t0"], s6["t1"]], "body": {"duration": 6},
        "takes": [{"file": "clips/c09/take-1.mp4", "status": "delivered", "sync": {}}]})
    rep = audit.audit(p)
    ws = [w for w in rep["warnings"] if "c09" in w]
    rng = f"{s5['id']}-{s6['id']}"
    assert len(ws) == 1 and "plays on no shot" in ws[0] and f"board set {rng} --tier motion --clip c09" in ws[0], ws
    code, out = _run("-p", str(p), "board", "set", rng, "--tier", "motion", "--clip", "c09")
    assert code == 0, out
    rows = {x["id"]: x["src"] for x in edl.build(p)["rows"]}
    assert rows[s5["id"]] == rows[s6["id"]] == "clip c09 x1"
    assert not any("c09" in w for w in audit.audit(p)["warnings"])


def test_tier_alone_never_leaves_a_shot_on_a_clip_of_the_other_kind(tmp_path):
    p, S = _picked(tmp_path)
    sung = next(s for s in S["shots"] if s["motion_tier"] == "sung" and s.get("clip"))
    before = (p / "board/shots.json").read_bytes()
    with pytest.raises(SlopError, match=re.escape(f"--tier motion: {sung['id']} plays {sung['clip']}, a sung clip")):
        shotedit.cmd_set(p, sung["id"], {"tier": "motion"})
    assert (p / "board/shots.json").read_bytes() == before
    motion = next(s for s in S["shots"] if s["motion_tier"] == "motion" and s.get("clip"))
    with pytest.raises(SlopError, match="a sung shot needs a sung clip"):
        shotedit.cmd_set(p, motion["id"], {"tier": "sung"})
    # EV's "seedance" tier reads as the clip's kind; with no clip to read it from it asks which
    assert shotedit.cmd_set(p, sung["id"], {"tier": "seedance"})["changed"] == {}
    plain = next(s for s in S["shots"] if s["motion_tier"] == "plate3d" and not s.get("clip"))
    with pytest.raises(SlopError, match="use --tier motion or --tier sung"):
        shotedit.cmd_set(p, plain["id"], {"tier": "seedance"})
    assert (p / "board/shots.json").read_bytes() == before
    # with --clip none the switch goes through; the plan follows (the shot leaves its sung window)
    r = shotedit.cmd_set(p, sung["id"], {"tier": "motion", "clip": "none"})
    sh = next(s for s in _board(p)["shots"] if s["id"] == sung["id"])
    assert sh["motion_tier"] == "motion" and sh["clip"] is None and any("unlinked" in n for n in r["notes"])
    assert sung["id"] not in next(c for c in _board(p)["seedance"] if c["clip"] == sung["clip"])["shots"]


def test_a_take_file_missing_on_disk_is_not_a_delivered_take(tmp_path):
    p, S = _picked(tmp_path)
    _c08(p, S)
    (p / "clips/c08/take-1.mp4").unlink()
    r = shotedit.cmd_set(p, "s002", {"clip": "c08"})
    assert any("no delivered take the edit can play" in n for n in r["notes"]), r["notes"]


def test_a_dropped_plan_entry_says_how_to_make_it_after_all(tmp_path):
    p, S = _picked(tmp_path)
    _c08(p, S)
    planned = S["shots"][0]["clip"]
    cmd = next(c for c in S["seedance"] if c["clip"] == planned)["cmd"]
    r = shotedit.cmd_set(p, "s001", {"clip": "c08"})
    assert any(n.startswith(f"{planned} dropped") and cmd in n for n in r["notes"]), r["notes"]


def test_audit_warns_about_a_linked_clip_that_does_not_fit(tmp_path):
    p, S = _filled(tmp_path)
    S["shots"][3]["motion_tier"], S["shots"][3]["clip"] = "motion", "c77"
    sung = next(s for s in S["shots"] if s["motion_tier"] == "sung")
    sung["motion_tier"] = "motion"                         # a motion shot on its sung clip
    synth.write_json(p / "board/shots.json", S)
    ws = audit.audit(p)["warnings"]
    assert any(w.startswith("s004 links clip c77") for w in ws), ws
    assert any(w.startswith(f"{sung['id']} is a motion shot but its clip {sung['clip']} is a sung clip") for w in ws), ws


# ------------------------------------------------------------------------------------------------ 3. stale board gate
def _stale_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "board gate is now stale" in ln]


def test_changes_after_the_approval_warn_that_the_board_gate_is_stale(tmp_path):
    p, S = _filled(tmp_path)
    sid = S["shots"][2]["id"]
    r = shotedit.cmd_set(p, sid, {"camera": "static"})         # not approved yet: no warning
    assert not r["gate_stale"] and not _stale_lines(r["text"])
    core_cli.record_gate(p, "board_approved", True, note="owner: go", force=True)
    assert board_gate_stale(p) is None                          # approved and unchanged
    r = shotedit.cmd_set(p, sid, {"camera": "static"})         # a no-op changes nothing: no warning
    assert r["changed"] == {} and not r["gate_stale"]
    code, out = _run("-p", str(p), "board", "set", sid, "--camera", "slow push in")
    assert code == 0 and out["gate_stale"]
    lines = _stale_lines(out["text"])
    assert len(lines) == 1 and lines[0].startswith("warning: the board changed after the owner approved it")
    assert "board approve --note '<their words>'" in lines[0] and "board sheet" in lines[0]   # the skills' command
    assert out["warnings"][0] == lines[0][len("warning: "):]
    # device add / rm and fill say it too; fill --check writes nothing and says nothing
    code, out = _run("-p", str(p), "board", "device", "add", sid, "--kind", "counter", "--anchor", "uv:0.6,0.4",
                     "--key", "B")
    assert code == 0 and out["gate_stale"] and len(_stale_lines(out["text"])) == 1, out
    code, out = _run("-p", str(p), "board", "device", "rm", sid, "--index", str(out["index"]))
    assert code == 0 and out["gate_stale"] and len(_stale_lines(out["text"])) == 1, out
    f = tmp_path / "f.jsonl"
    f.write_text(json.dumps({"id": sid, "camera": "handheld"}) + "\n", encoding="utf-8")
    code, out = _run("-p", str(p), "board", "fill", str(f), "--check")
    assert code == 0 and not out["gate_stale"] and not _stale_lines(out["text"])
    code, out = _run("-p", str(p), "board", "fill", str(f))
    assert code == 0 and out["gate_stale"] and len(_stale_lines(out["text"])) == 1, out
    code, st = _run("-p", str(p), "gate", "board")
    assert code == 0 and st["current"] is False                 # core agrees: the approval is stale
    # re-approved: current again, no warning until the next change
    core_cli.record_gate(p, "board_approved", True, force=True)
    assert board_gate_stale(p) is None
    assert not shotedit.cmd_set(p, sid, {"camera": "handheld"})["gate_stale"]
    assert shotedit.cmd_set(p, sid, {"camera": "static"})["gate_stale"]
    # a change back to exactly what the owner approved is covered by that approval again
    assert not shotedit.cmd_set(p, sid, {"camera": "handheld"})["gate_stale"]
    # revoked: nothing to go stale
    core_cli.record_gate(p, "board_approved", False)
    assert not shotedit.cmd_set(p, sid, {"camera": "slow push in"})["gate_stale"]


def test_redraft_and_plates_vary_after_the_approval_warn_too(tmp_path):
    p, S = _picked(tmp_path)
    # two shots on one plate that are not one continuous moment: vary gives the later one a variant plate
    S["shots"][4]["plate"] = S["shots"][2]["plate"]
    synth.write_json(p / "board/shots.json", S)
    for k in (2, 3):
        synth.make_image(p / "plates/cands" / S["shots"][2]["plate"] / f"{k}.jpg", 320, 180, seed=40 + k)
    core_cli.record_gate(p, "board_approved", True, force=True)
    r = plates.vary(p, dry=True)
    assert r["changes"] and not r["gate_stale"] and not _stale_lines(r["text"])        # a dry run writes nothing
    r = plates.vary(p)
    assert r["changes"] and r["gate_stale"] and len(_stale_lines(r["text"])) == 1, r["text"]
    core_cli.record_gate(p, "board_approved", True, force=True)
    r = plates.vary(p)                                          # nothing left to vary: no change, no warning
    assert not r["changes"] and not r["gate_stale"]
    r = draft.run(p, force=True)
    assert r["gate_stale"] and len(_stale_lines(r["text"])) == 1
    r = draft.run(p, out="board/alt.json")                      # a draft elsewhere leaves the approved board alone
    assert not r["gate_stale"]


def test_a_flag_only_approval_never_covers_a_change(tmp_path):
    p, S = _filled(tmp_path)
    pj = synth.load(p, "project.json")
    pj["gates"]["board_approved"] = True                        # set by hand: what it covered was never recorded
    synth.write_json(p / "project.json", pj)
    r = shotedit.cmd_set(p, S["shots"][1]["id"], {"camera": "static"})
    assert r["gate_stale"] and "board approve --note" in r["warnings"][0]


def test_cli_parses_the_new_flags(tmp_path):
    p, S = _picked(tmp_path)
    _c08(p, S)
    code, out = _run("-p", str(p), "board", "set", "s002", "--clip", "c08")
    assert code == 0 and out["linked"] == {"s002": "c08"}
    code, out = _run("-p", str(p), "board", "set", "s002", "--tier", "plate3d", "--treatment", "relight")
    assert code == 0 and _board(p)["shots"][1]["clip"] is None and _board(p)["shots"][1]["treatment"] == "relight"
