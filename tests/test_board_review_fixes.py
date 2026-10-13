"""Regression tests for the board/edit review findings: the clip plan reaches gen, shot validation, the audit report
path, the graphics gate, plate listing, approvals logged, pace, treatments, cost, plates book/ingest/pick, look, depth,
export contract names."""
import io
import json
import shlex
import sys
import types
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop import cli  # noqa: E402
from slop.board import audit, draft, plates  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.edit import depth, edl, export, look  # noqa: E402


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """No user cache (OpenRouter listings, HF weights) leaks in or out."""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


def _filled(tmp_path, **kw):
    p = synth.make_project(tmp_path, **kw)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    synth.write_json(p / "board/shots.json", S)
    return p, S


def _with_picks(tmp_path, n=2, **kw):
    p, S = _filled(tmp_path, **kw)
    for i, key in enumerate(s["plate"] for s in S["shots"] if s.get("mj_prompt") or s.get("img_prompt")):
        for k in range(1, n + 1):
            synth.make_image(tmp_path / "dl" / f"{key}-{k}.png", 160, 90, seed=100 * k + i)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [], all_first=True)
    return p, S


# ------------------------------------------------------------------------------------------------ shot validation
@pytest.mark.parametrize("shot,msg", [({"id": "s001", "t0": 0}, "s001: t1 is missing"),
                                      ({"id": "s001", "t0": "0", "t1": 2}, "s001: t0 is '0', not a number"),
                                      ({"t0": 0, "t1": 2}, "shots[0]: id is missing")])
def test_bad_shots_are_named_not_tracebacks(tmp_path, shot, msg):
    p = synth.make_project(tmp_path)
    synth.write_json(p / "board/shots.json", {"shots": [shot]})
    with pytest.raises(SlopError, match=msg.replace("[", r"\[").replace("]", r"\]")):
        audit.run(p)
    for argv in (("board", "audit"), ("board", "sheet"), ("edit", "edl")):
        code, out = _run("-p", str(p), *argv)
        assert code == 1 and msg in out["error"] and "traceback" not in out, argv


# ------------------------------------------------------------------------------------------------ clip plan -> gen
def test_board_clip_cmd_creates_the_planned_clip_in_gen(tmp_path):
    p, S = _with_picks(tmp_path)
    c = next(c for c in S["seedance"] if c["kind"] == "sung" and len(c["shots"]) > 1)
    argv = shlex.split(c["cmd"])
    assert argv[:3] == ["slop", "-p", str(p)]
    code, out = _run(*argv[1:])
    assert code == 0 and out["clip_id"] == c["clip"], out
    cj = synth.load(p, f"clips/{c['clip']}.json")
    assert cj["shot"] == c["shots"][0] and cj["kind"] == "sung"
    assert cj["song_t0"] == pytest.approx(c["song_t0"], abs=1e-3) and cj["body"]["duration"] == c["duration"]
    assert cj["needed"] == pytest.approx(c["needed"], abs=1e-3)
    # the EDL finds it for every shot of the window; the audit now counts the made clip and stops re-printing its cmd
    ed = edl.Edit(p)
    for sid in c["shots"]:
        sh = next(s for s in S["shots"] if s["id"] == sid)
        assert c["clip"] in ed.candidates(sh)
    rep = audit.audit(p)
    assert rep["gates"]["clip_windows"]["ok"], rep["gates"]["clip_windows"]["fails"]
    assert rep["gates"]["motion_budget"]["info"]["made"] == 1
    assert c["clip"] not in {x["clip"] for x in rep["clip_cmds"]}
    assert len(rep["clip_cmds"]) == len(S["seedance"]) - 1
    # idempotent: running the same command again changes nothing
    code, out = _run(*argv[1:])
    assert code == 0 and out["created"] is False


def test_audit_counts_made_clips_and_uses_the_clean_window_rule(tmp_path):
    p, S = _filled(tmp_path)
    W = synth.load(p, "analysis/words.json")
    c = next(c for c in S["seedance"] if c["kind"] == "sung")
    tok = draft.word_tokens(draft.load_words(p))
    w0 = next(w for w in W["words"] if w["t0"] > c["song_t0"] + .5)
    t0 = round(w0["t0"] - .03, 3)                         # 30 ms before a word: inside [t0 - .02, t0 + .05)
    clean_words = draft.words_in(tok, t0, t0 + 6, .05)
    assert _norm(clean_words) != _norm(draft.words_in(tok, t0, t0 + 6))       # the two rules differ here
    synth.write_json(p / "clips" / f"{c['clip']}.json", {
        "id": c["clip"], "shot": c["shots"][0], "kind": "sung", "status": "draft", "song_t0": t0, "words": clean_words,
        "needed": c["needed"], "window": {"t0": t0, "t1": t0 + 6, "mode": "clean"}, "body": {"duration": 6},
        "takes": []})
    synth.write_json(p / "clips/W09.json", {"id": "W09", "shot": S["shots"][8]["id"], "kind": "motion", "status": "draft",
                                            "song_t0": S["shots"][8]["t0"], "body": {"duration": 5}, "takes": []})
    synth.write_json(p / "clips/W09c1.json", {"id": "W09c1", "parent": c["clip"], "kind": "sung", "song_t0": t0 + 3,
                                              "body": {"duration": 4}, "takes": []})
    synth.write_json(p / "clips/W10.json", {"id": "W10", "shot": "s999", "kind": "motion", "status": "failed",
                                            "body": {"duration": 5}, "takes": []})
    rep = audit.audit(p)
    assert rep["gates"]["clip_windows"]["ok"], rep["gates"]["clip_windows"]["fails"]
    mb = rep["gates"]["motion_budget"]["info"]
    planned = sum(x["duration"] for x in S["seedance"]) - c["duration"] + 6 + 5
    assert mb["sung_s"] + mb["motion_s"] == pytest.approx(planned) and mb["covers_s"] == 4 and mb["made"] == 2
    pj = synth.load(p, "project.json")
    pj["budget"]["motion_s"] = planned - 1
    synth.write_json(p / "project.json", pj)
    assert not audit.audit(p)["gates"]["motion_budget"]["ok"]
    # a made clip on a shot the plan gives to another clip is flagged
    W11 = {"id": "W11", "shot": c["shots"][0], "kind": "sung", "status": "draft", "song_t0": c["song_t0"],
           "words": c["words"], "body": {"duration": c["duration"]}, "takes": []}
    synth.write_json(p / "clips/W11.json", W11)
    assert any("W11" in w and "plan" in w for w in audit.audit(p)["warnings"])


def _norm(s):
    return audit._norm(s)


def test_default_clip_cap_is_evs_45(tmp_path, monkeypatch):
    p, S = _filled(tmp_path)
    assert audit.DEFAULT_MAX_CLIPS == 45
    assert audit.audit(p)["gates"]["motion_budget"]["info"]["max_clips"] == 45
    monkeypatch.setattr(audit, "DEFAULT_MAX_CLIPS", 2)
    rep = audit.audit(p)
    assert not rep["gates"]["motion_budget"]["ok"] and "EV's cap" in rep["gates"]["motion_budget"]["fails"][0]


# ------------------------------------------------------------------------------------------------ audit report path
def test_audit_of_another_file_never_writes_board_audit_json(tmp_path):
    p = synth.make_project(tmp_path)
    draft.run(p)                                          # board/shots.json: the unfilled draft (fails)
    draft.run(p, out=str(p / "board/v2.json"))
    synth.write_json(p / "board/v2.json", synth.fill_todos(synth.load(p, "board/v2.json")))
    r = audit.run(p, str(p / "board/v2.json"))
    assert r["ok"] and not r["main_board"] and Path(r["path"]) == p / "board/v2.audit.json"
    assert not (p / "board/audit.json").exists() and "board/audit.json" in r["text"]
    from slop import core_cli
    assert core_cli.board_audit_problem(p) == "not audited yet"
    code, out = _run("-p", str(p), "gate", "board", "--approve")
    assert code == 1 and not synth.load(p, "project.json")["gates"]["board_approved"]
    r = audit.run(p)                                      # the real board still fails
    assert not r["ok"] and Path(r["path"]) == p / "board/audit.json"


def test_draft_out_never_overwrites_without_force(tmp_path):
    p = synth.make_project(tmp_path)
    out = p / "board/alt.json"
    draft.run(p, out=str(out))
    out.write_text("{\"hand\": \"edited\"}", encoding="utf-8")
    with pytest.raises(SlopError, match="already exists"):
        draft.run(p, out=str(out))
    r = draft.run(p, out=str(out), force=True)
    assert Path(r["backup"]).read_text(encoding="utf-8") == "{\"hand\": \"edited\"}"
    assert synth.load(p, "board/alt.json")["shots"]


# ------------------------------------------------------------------------------------------------ graphics gate
def test_graphics_gate_one_explaining_graphic_per_line(tmp_path):
    p, S = _filled(tmp_path)
    assert audit.audit(p)["gates"]["graphics"]["ok"]
    W = synth.load(p, "analysis/words.json")
    for s in S["shots"]:
        s["devices"] = []
        s["notes"] = ""                                   # deleting the TODO note is not a way out
    synth.write_json(p / "board/shots.json", S)
    g = audit.audit(p)["gates"]["graphics"]
    n_lines = len({w["line"] for w in W["words"]})
    assert not g["ok"] and len(g["fails"]) == n_lines and "add a devices[] entry to s" in g["fails"][0]
    # one tagged device anywhere serves its line; an untagged one serves one line only
    S["shots"][-1]["devices"] = [{"kind": "counter", "anchor": "screen", "params": {}, "key": "W", "line": 0}]
    first = {}
    for w in W["words"]:
        first.setdefault(w["line"], w["t0"])
    starts = [s["t0"] for s in S["shots"]]
    import bisect
    i1 = bisect.bisect_right(starts, first[1]) - 1
    S["shots"][i1]["devices"] = [{"kind": "callout", "anchor": "subject", "params": {}, "key": "W"}]
    synth.write_json(p / "board/shots.json", S)
    g = audit.audit(p)["gates"]["graphics"]
    assert len(g["fails"]) == n_lines - 2 and not any(f.startswith(("line 0 ", "line 1 ")) for f in g["fails"])
    # a code-drawn shot typing the line is itself the graphic
    i2 = bisect.bisect_right(starts, first[2]) - 1
    S["shots"][i2].update(code=True, motion_tier="still", treatment="pure-motion")
    synth.write_json(p / "board/shots.json", S)
    assert not any(f.startswith("line 2 ") for f in audit.audit(p)["gates"]["graphics"]["fails"])


# ------------------------------------------------------------------------------------------------ plates listing
def test_plates_listed_and_unused_entries(tmp_path):
    p, S = _filled(tmp_path)
    S["plates"] = [e for e in S["plates"] if e["plate"] != S["shots"][7]["plate"]]
    S["plates"].append({"plate": "p900", "lead": False, "aspect": "16:9", "used_by": []})
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    fails = rep["gates"]["plates_unique"]["fails"]
    assert any(f"plate {S['shots'][7]['plate']} (used by {S['shots'][7]['id']}) is not listed" in f for f in fails)
    assert any("p900" in w for w in rep["warnings"])
    assert "p900" not in {e["plate"] for e in plates.plate_entries(S, synth.load(p, "project.json"))}


# ------------------------------------------------------------------------------------------------ approval
def test_approve_goes_through_the_core_gate_and_logs_it(tmp_path):
    p, S = _filled(tmp_path)
    code, out = _run("-p", str(p), "board", "approve", "--note", "owner: ship it")
    assert code == 0 and out["approved"] and synth.load(p, "project.json")["gates"]["board_approved"] is True
    dec = (p / "DECISIONS.md").read_text(encoding="utf-8")
    assert "GATE board_approved approved" in dec and "owner: ship it" in dec
    code, out = _run("-p", str(p), "board", "approve")
    assert code == 0 and out["changed"] is False


# ------------------------------------------------------------------------------------------------ pace / treatments / cost
def test_pace_is_evs_measured_cut():
    P = draft.PACE
    assert (P["intro"], P["verse"], P["chorus"], P["verse_late"], P["chorus_mid"], P["bridge"], P["drop"],
            P["chorus_last"], P["outro"]) == (1.33, 1.62, 2.69, 2.63, 1.67, 2.25, 1.58, 2.38, 4.40)
    assert draft._pace("chorus", 1, False, P, "first") == 2.69
    assert draft._pace("chorus", 2, False, P, "mid") == 1.67
    assert draft._pace("hook", 3, False, P, "last") == 2.38
    assert draft._pace("pre", 2, False, P) == 2.63 and draft._pace("intro", 1, True, P) == 1.33


def test_five_treatment_families_and_chapter_warning(tmp_path):
    p, S = _filled(tmp_path, look={"mode": "print", "accent": "#D97757", "hero_plate": None})
    fam = [s["treatment"] for s in S["shots"] if s["motion_tier"] == "plate3d"]
    assert set(fam) == set(draft.TREATMENTS) and "reproduction" in fam
    rep = audit.audit(p)
    assert not any("treatments over" in w for w in rep["warnings"])
    two = ["layer-separation", "depth-as-image"]
    for k, s in enumerate(x for x in S["shots"] if x["motion_tier"] == "plate3d"):
        s["treatment"] = two[k % 2]
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["gates"]["treatments"]["ok"] and any("at least five" in w for w in rep["warnings"])
    q = synth.make_project(tmp_path / "clean", look={"mode": "clean-grade", "accent": "#D97757", "hero_plate": None})
    draft.run(q)
    assert "reproduction" not in {s["treatment"] for s in synth.load(q, "board/shots.json")["shots"]}
    n = synth.make_project(tmp_path / "native")          # native = clean for the engine: no print texture either
    draft.run(n)
    assert "reproduction" not in {s["treatment"] for s in synth.load(n, "board/shots.json")["shots"]}


def test_draft_prices_the_clip_plan_offline(tmp_path, monkeypatch):
    from slop.gen import openrouter
    monkeypatch.setattr(openrouter.OpenRouter, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    p = synth.make_project(tmp_path)
    r = draft.run(p)
    st = r["stats"]
    assert st["clips"] and st["est_usd"] > 0 and st["est_usd_with_covers"] > st["est_usd"]
    assert f"${st['est_usd']:.2f}" in r["text"]
    q = synth.make_project(tmp_path / "q", motion_s=0)
    assert draft.run(q)["stats"]["est_usd"] == 0.0


# ------------------------------------------------------------------------------------------------ plates book
def test_book_subset_reroll_keeps_the_full_book(tmp_path):
    p, S = _filled(tmp_path)
    r = plates.book(p, batch="b01")
    full = (p / "plates/prompts.md").read_text(encoding="utf-8")
    assert r["gpu_minutes"] == pytest.approx(1.3 * r["mj_jobs"]) and "Fast GPU-minutes" in full
    assert "Never more than 10 queued jobs" in full
    key = synth.load(p, "plates/mj/b01.json")["jobs"][0]["plate"]
    with pytest.raises(SlopError, match="--batch b02"):
        plates.book(p, batch="b01", only=[key])
    r = plates.book(p, batch="b02", only=[key])
    assert r["book"] == "plates/prompts-b02.md" and r["subset"] and r["mj_jobs"] == 1
    assert (p / "plates/prompts.md").read_text(encoding="utf-8") == full
    assert plates.book(p, batch="b02", only=[key])["mj_jobs"] == 1               # re-running the re-roll is fine
    pro = plates._book_md({}, p, "x", "pro", 40, [{"plate": "a", "prompt": "x", "params": "", "irefs": [], "shots": []}],
                          [], [{"text": "{x}", "expect": 1, "plates": ["a"]}], [], [], 1.3)
    assert "Never more than 10" not in pro and "1.3 Fast GPU-minutes" in pro              # the queue rule: Basic/Standard


def test_book_api_jobs_merge_and_project_flag(tmp_path):
    p, S = _filled(tmp_path, tier="quick")
    plates.book(p)
    jobs = synth.load(p, "plates/jobs.json")["jobs"]
    n = len(jobs)
    assert all(j["cmd"].startswith(f"slop -p {shlex.quote(str(p))} gen image --plate ") for j in jobs)
    plates.book(p, batch="b02", only=[jobs[0]["plate"]])
    jobs2 = synth.load(p, "plates/jobs.json")["jobs"]
    assert len(jobs2) == n and {j["plate"] for j in jobs2} == {j["plate"] for j in jobs}


def test_book_far_variant_lint(tmp_path):
    p, S = _filled(tmp_path)
    owner = next(s for s in S["shots"] if s.get("mj_prompt") and s["lead_on_screen"] and s["motion_tier"] == "plate3d")
    owner["framing"] = "WS"
    owner["mj_prompt"] = "wide shot of {lead} standing in a vast white hall, the right third empty"
    synth.write_json(p / "board/shots.json", S)
    r = plates.book(p)
    assert any(owner["plate"] in w and "{far}" in w for w in r["warnings"])
    owner["mj_prompt"] = "wide shot of {far} standing in a vast white hall, the right third empty"
    synth.write_json(p / "board/shots.json", S)
    assert not any(owner["plate"] in w and "{far}" in w for w in plates.book(p)["warnings"])


# ------------------------------------------------------------------------------------------------ plates ingest
def _mj_words(prompt, chars=120):
    import re
    return re.sub(r"[^a-z0-9 ]", "", prompt.lower())[:chars].strip().replace(" ", "_")


def test_ingest_map_names_targets_and_loose_names(tmp_path):
    p, S = _filled(tmp_path)
    plates.book(p, batch="b01")
    jobs = synth.load(p, "plates/mj/b01.json")["jobs"]
    plain = [j for j in jobs if not j["lead"]]
    dl = tmp_path / "dl"
    synth.make_image(dl / "random_name.png", 160, 90, seed=1)
    with pytest.raises(SlopError, match="not a plate of this board"):
        plates.ingest(p, str(dl), batch="b01", maps=["random_name.png=typo"])
    assert not (p / "plates/cands/typo").exists()
    r = plates.ingest(p, str(dl), batch="b01", maps=[f"random_name.png={plain[0]['plate']}"])
    assert r["added"] == {plain[0]["plate"]: [1]}
    # no uuid: "<user with_underscores>_<prompt words>_<hash>.png" and "<...>_<hash>_<n>.png"
    dl2 = tmp_path / "dl2"
    for n in range(2):
        synth.make_image(dl2 / f"some_user_x_{_mj_words(plain[1]['prompt'])}_a1b2c3d4_{n}.png", 160, 90, seed=10 + n)
    synth.make_image(dl2 / f"user_{_mj_words(plain[2]['prompt'])}_9f8e7d6c.png", 160, 90, seed=20)
    r = plates.ingest(p, str(dl2), batch="b01")
    assert sorted(r["added"][plain[1]["plate"]]) == [1, 2] and r["added"][plain[2]["plate"]] == [1]
    # originals are kept byte for byte
    orig = p / "plates/mj/b01/orig" / f"user_{_mj_words(plain[2]['prompt'])}_9f8e7d6c.png"
    assert orig.read_bytes() == (dl2 / orig.name).read_bytes()
    idx = synth.load(p, "plates/cands/index.json")
    assert idx[plain[2]["plate"]]["1"]["orig"].endswith(orig.name)


def test_ingest_exif_prompt_and_group_count(tmp_path):
    from PIL import Image
    p, S = _filled(tmp_path)
    plates.book(p, batch="b01")
    jobs = synth.load(p, "plates/mj/b01.json")["jobs"]
    lead = [j for j in jobs if j["lead"]]
    dl = tmp_path / "dl"
    uid = "0a1b2c3d-1111-4222-8333-944455556666"
    for n in range(3):                                    # 3 of 4 images, JPEG with EXIF ImageDescription
        f = dl / f"u_{_mj_words(lead[1]['prompt'], 40)}_{uid}_{n}.jpg"
        f.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGB", (160, 90), (10 * n, 80, 90))
        ex = Image.Exif()
        ex[270] = lead[1]["prompt"] + " --ar 16:9 --v 8.2"
        im.save(f, exif=ex.tobytes())
    r = plates.ingest(p, str(dl), batch="b01")
    assert sorted(r["added"][lead[1]["plate"]]) == [1, 2, 3]
    assert r["group_warnings"] and "has 3 image(s), expected 4" in r["group_warnings"][0]


# ------------------------------------------------------------------------------------------------ pick
def test_pick_refuses_a_variants_candidate(tmp_path):
    p, S = _with_picks(tmp_path, n=3)
    S = synth.load(p, "board/shots.json")
    p3 = [s for s in S["shots"] if s["motion_tier"] == "plate3d"]
    p3[3]["plate"] = p3[0]["plate"]
    synth.write_json(p / "board/shots.json", S)
    plates.vary(p)
    base = p3[0]["plate"]
    assert synth.load(p, "plates/picks.json")[f"{base}~2"]["cand_k"] == 2
    with pytest.raises(SlopError, match=r"already the image of .*~2.*free: #1, #3"):
        plates.pick(p, [base, "2"])
    plates.pick(p, [base, "3"])
    assert audit.audit(p)["gates"]["plates_unique"]["ok"]
    picks = synth.load(p, "plates/picks.json")           # a hand-edited clash: the audit says how to fix it
    picks[base]["file"] = picks[f"{base}~2"]["file"]
    synth.write_json(p / "plates/picks.json", picks)
    fails = audit.audit(p)["gates"]["plates_unique"]["fails"]
    assert any("same image" in f and "slop plates pick" in f for f in fails)


# ------------------------------------------------------------------------------------------------ look / depth / export
def _look_proj(tmp_path):
    p = synth.make_project(tmp_path)
    synth.make_image(p / "plates/cands/p002/1.jpg", 320, 180, color=(150, 120, 60), accent=True)
    synth.write_json(p / "plates/picks.json", {"p002": {"file": "plates/cands/p002/1.jpg", "cand_k": 1, "shot_ids": []}})
    return p


def test_look_set_validates_before_saving_and_warns_instead_of_failing(tmp_path):
    p = _look_proj(tmp_path)
    before = (p / "project.json").read_text(encoding="utf-8")
    for kw, msg in (({"strength": 1.5}, "between 0 and 1"), ({"contrast": -0.1}, "between 0 and 1"),
                    ({"hero": "p999", "mode": "clean-grade"}, "not a picked plate"), ({"accent": "orange"}, "hex")):
        with pytest.raises(SlopError, match=msg):
            look.cmd_set(p, **kw)
        assert (p / "project.json").read_text(encoding="utf-8") == before, kw
    out = look.cmd_set(p, mode="clean-grade")
    assert out["ok"] and out["saved"] and not out["ready"] and "hero" in out["warning"]
    assert synth.load(p, "project.json")["look"]["mode"] == "clean-grade"
    code, out = _run("-p", str(p), "edit", "look")
    assert code == 0 and out["ok"] and out["warning"]
    code, out = _run("-p", str(p), "edit", "look", "set", "--hero", "p002")
    assert code == 0 and out["ready"] and "warning" not in out


def test_depth_weights_go_to_the_shared_hf_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", "placeholder")          # recorded, so teardown restores the real value
    monkeypatch.delenv("HF_HOME")
    seen = {}
    fake = types.ModuleType("transformers")
    fake.pipeline = lambda task, model, device: seen.update(task=task, model=model, device=device) or "PIPE"
    monkeypatch.setitem(sys.modules, "transformers", fake)
    monkeypatch.setattr(depth, "_PIPE", None)
    assert depth._pipe() == "PIPE"
    import os
    assert Path(os.environ["HF_HOME"]) == tmp_path / "slophome" / "cache" / "hf"
    assert seen == {"task": "depth-estimation", "model": "depth-anything/Depth-Anything-V2-Small-hf", "device": "cpu"}
    monkeypatch.setattr(depth, "_PIPE", None)


def test_hits_all_becomes_impact_all():
    H = export.build_hits({"hits": [{"t": 2.0, "score": .9}],
                           "hits_all": [{"t": 1.0, "score": .4}, {"t": 2.0, "score": .9}, {"t": 3.0, "score": .6}]}, 10.0)
    assert H["impact"] == [{"t": 2.0, "s": .9}]
    assert H["impact_all"] == [{"t": 1.0, "s": .4}, {"t": 2.0, "s": .9}, {"t": 3.0, "s": .6}] and "hits_all" not in H
