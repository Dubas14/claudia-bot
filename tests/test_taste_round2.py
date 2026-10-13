"""Taste track, review round 2: verdict semantics (texture / accent / question ids / faces / style frame), one open pair
sheet at a time, chat endings, the text-free check on small pools, the project style tail, the Feed's fixed root,
the status helper for core, the server token and the BLAS cap."""
import json
import os
import random
import shlex
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.cli import main  # noqa: E402
from slop.config import SlopError, load_project  # noqa: E402
from slop.taste import apply as A  # noqa: E402
from slop.taste import embed as E  # noqa: E402
from slop.taste import sheet as SH  # noqa: E402
from slop.taste import textfree as TF  # noqa: E402
from slop.taste import tokens as T  # noqa: E402
from slop.taste import verdicts as VD  # noqa: E402
from slop.taste.embed import embed_pool, load_store  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402
from slop.taste.profile import ensure_link, status_stage  # noqa: E402
from slop.taste.store import (append_jsonl, new_eid, read_events, read_jsonl, taps_path, taste_dir,  # noqa: E402
                              user_profile_dir)


def run(capsys, *args):
    code = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


def tap(p, items, like_kinds=("grey", "dark", "red")):
    for iid, it in items.items():
        kind = it["title"].split("-")[0]
        append_jsonl(taps_path(p), {"eid": new_eid(), "t": "2026-10-01T00:00:00", "item": iid,
                                    "action": "like" if kind in like_kinds else "pass", "kind": "human",
                                    "dwell_ms": 900, "why": "cold", "score": None})


@pytest.fixture
def tapped(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    p = S.make_project(tmp_path, "song-a")
    ensure_link(p)
    S.write_images(tmp_path / "refs", {"grey": 24, "dark": 8, "red": 6, "colour": 18, "stripes": 10, "blue": 6})
    add_dir(PoolWriter(p), tmp_path / "refs")
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    monkeypatch.setattr(E, "text_embedder_for", lambda *a, **k: fe)
    tap(p, load_pool(p))
    return p, fe


# ---------------------------------------------------------------- verdicts

def test_texture_verdict_follows_the_owners_words_whatever_the_lean(tapped, capsys):
    p, fe = tapped
    t = T.build_tokens(p, embedder=fe)
    lean = t["texture"]["lean"]
    q = next(q for q in t["open_questions"] if q["id"] == "texture")
    assert q["rule"] == "texture" and q["answers"]["no grain"].startswith("slop taste verdict texture rejected")
    for forced_lean in ("clean", "grain/texture", "unclear"):           # the answer never depends on the lean
        tt = json.loads(json.dumps(t))
        tt["texture"]["lean"] = forced_lean
        VD.honour(tt, [{"vid": "x", "t": "2026-10-01T00:00:01", "level": "rule", "rule": "texture",
                        "value": VD.rules(tt)[4]["value"], "status": "rejected", "project": "song-a"}], "song-a")
        assert tt["texture"]["apply"] is False
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "texture", "rejected", "--note", "no grain")
    assert code == 0 and j["meaning"] == "no grain" and "no grain" in j["text"]
    assert "TASTE texture grain: REJECTED = no grain ('no grain')" in (p / "DECISIONS.md").read_text(encoding="utf-8")
    t = T.build_tokens(p, embedder=fe)
    assert t["texture"]["apply"] is False and "Texture: **none** (your verdict)" in \
        (p / "taste" / "look-bible.md").read_text(encoding="utf-8")
    assert "fine film grain" not in A.apply(p)["set"]["style_tail"]
    VD.record(p, "texture", "confirmed", note="yes, grain")
    assert T.build_tokens(p, embedder=fe)["texture"]["apply"] is True
    r = VD.record(p, "grain", "confirmed", value="no")                   # alias + an explicit no: stored canonically
    assert r["verdict"]["rule"] == "texture" and r["verdict"]["value"] == "grain" and r["verdict"]["status"] == "rejected"
    assert T.build_tokens(p, embedder=fe)["texture"]["apply"] is False
    n = len(read_jsonl(p / "taste" / "verdicts.jsonl"))
    with pytest.raises(SlopError, match="double negative"):
        VD.record(p, "texture", "rejected", value="clean")
    assert len(read_jsonl(p / "taste" / "verdicts.jsonl")) == n           # nothing recorded
    # the builder-era row (value = the measured lean "clean", rejected, the owner said "no grain") reads as no grain
    tt = json.loads(json.dumps(t))
    VD.honour(tt, [{"vid": "y", "t": "2026-10-01T00:00:02", "level": "rule", "rule": "texture", "value": "clean",
                    "status": "rejected", "project": "song-a"}], "song-a")
    assert tt["texture"]["apply"] is False
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "--list")
    assert "confirmed = YES, add grain; rejected = NO grain" in j["text"] and lean in j["text"]


def test_the_accent_verdict_needs_a_value(tapped, tmp_path, capsys):
    p, fe = tapped
    T.build_tokens(p, embedder=fe)
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "palette.accent", "confirmed", "--note", "yes, the orange")
    assert code == 1 and "--value" in j["error"] and "nothing was recorded" in j["error"]
    assert not (p / "taste" / "verdicts.jsonl").exists() and not (p / "DECISIONS.md").exists()
    VD.record(p, "accent", "confirmed", value="#d97757", note="the orange")             # question id as the rule
    b = S.make_project(tmp_path, "song-b")
    ensure_link(b)
    T.build_tokens(b, embedder=fe)
    with pytest.raises(SlopError, match=r"last time \(song-a\): #D97757"):
        VD.record(b, "palette.accent", "confirmed")
    with pytest.raises(SlopError, match="hex colour"):
        VD.record(b, "palette.accent", "confirmed", value="the orange")
    r = VD.record(b, "palette.accent", "confirmed", value="none", note="no accent this time")
    assert r["verdict"]["value"] is None
    t = T.build_tokens(b, embedder=fe)
    assert t["palette"]["accent"] is None and t["palette"]["accent_source"] == "owner verdict"
    assert "accent" not in [q["id"] for q in t["open_questions"]]
    assert {q["id"]: q["answer"] for q in t["answered_questions"]}["accent"] == "none"


def _answer_cmd(q):
    """the first answer's printed command, with the placeholders filled in the way the bot would"""
    ans = next(iter(q["answers"].values()))
    cmd = ans.split("   (")[0].replace('"#RRGGBB"', '"#D97757"').replace("--value N", "--value 2") \
        .replace('"FAMILY"', '"Space Grotesk"')
    return shlex.split(cmd)[1:]                                            # drop "slop"


def test_every_question_can_be_closed_with_its_printed_command(tapped, capsys):
    p, fe = tapped
    code, j = run(capsys, "-p", str(p), "taste", "tokens", "--no-words")
    assert code == 0 and "accent = ask the owner" in j["text"]
    qs = j["questions"]
    assert {q["id"] for q in qs} >= {"accent", "footage_grade", "faces", "texture", "style_frame"}
    fg = next(q for q in qs if q["id"] == "footage_grade")
    assert "mono" not in fg["ask"] and "clean-grade" in fg["ask"] and set(fg["grades"]) == set(VD.GRADES)
    for q in qs:
        assert q["rule"] and q["answers"] and all(c.startswith("slop taste ") for c in q["answers"].values())
        args = _answer_cmd(q)
        code, out = run(capsys, "-p", str(p), *args)
        assert code == 0, (q["id"], args, out)
    code, j = run(capsys, "-p", str(p), "taste", "tokens", "--no-words")
    assert code == 0 and j["questions"] == [] and "every question is answered" in j["text"]
    assert "accent #D97757 (owner verdict)" in j["text"] and "footage grade native (owner verdict)" in j["text"]
    assert "ask the owner" not in j["text"] and "faces: show (owner verdict)" in j["text"]
    t = json.loads((p / "taste" / "taste-tokens.json").read_text(encoding="utf-8"))
    ans = {q["id"]: q["answer"] for q in t["answered_questions"]}
    assert ans["faces"] == "show faces" and ans["style_frame"].startswith("2") and ans["texture"] == "yes, grain"
    assert t["look_suggestion"]["faces"] is True and t["look_suggestion"]["style_frame"] == "2"
    # the question ids and natural words work as rule names; a wrong grade lists every grade with its meaning
    for name in ("footage_grade", "grade", "type", "frame", "face"):
        assert VD.rule_id(name) in VD.OWNER_RULES
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "footage_grade", "confirmed", "--value", "mono")
    assert code == 1 and all(g in j["error"] for g in VD.GRADES) and "halftone" in j["error"]
    with pytest.raises(SlopError, match="frame the owner picked"):
        VD.record(p, "style_frame", "confirmed")


def test_faces_and_style_frame_are_per_video(tapped, tmp_path):
    p, fe = tapped
    T.build_tokens(p, embedder=fe)
    VD.record(p, "faces", "rejected", note="keep her face hidden")
    VD.record(p, "style_frame", "rejected", note="all too busy")
    t = T.build_tokens(p, embedder=fe)
    assert t["faces"]["show"] is False and "faces" not in [q["id"] for q in t["open_questions"]]
    sf = next(q for q in t["open_questions"] if q["id"] == "style_frame")   # none close: still open, new frames
    assert "render 3 new frames" in sf["proposal"] and "all too busy" in sf["proposal"]
    b = S.make_project(tmp_path, "song-b")
    ensure_link(b)
    t = T.build_tokens(b, embedder=fe)
    q = next(q for q in t["open_questions"] if q["id"] == "faces")
    assert t.get("faces") is None and q["proposal"].startswith("last time (song-a): hide faces")
    assert "render 3 frames" in next(q for q in t["open_questions"] if q["id"] == "style_frame")["proposal"]


# ---------------------------------------------------------------- pair sheets

@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    return S.make_project(tmp_path, "song-a")


def test_one_open_sheet_at_a_time(proj, tmp_path, capsys):
    S.fake_pool(proj, clusters=3, per=20)
    r1 = SH.make_sheets(proj, pairs=6, seed=1)
    meta = json.loads(Path(r1["files"][0]).parent.joinpath("sheet.json").read_text(encoding="utf-8"))
    assert meta["project"] == "song-a" and r1["record"] == f'slop taste record --sheet {r1["sheet"]} "<the reply>"'
    assert r1["record"] in r1["text"]
    again = SH.make_sheets(proj, pairs=6, seed=2)                         # a retry shows the same sheet again
    assert again["reprinted"] and again["sheet"] == r1["sheet"] and again["files"] == r1["files"]
    assert "No new sheet was made" in again["text"] and "--new" in again["text"] and r1["record"] in again["text"]
    r2 = SH.make_sheets(proj, pairs=6, seed=3, new=True)
    assert r2["sheet"] != r1["sheet"] and r1["sheet"] in r2["text"]
    with pytest.raises(SlopError) as e:                                   # which sheet? -> refuse, list both
        SH.record(proj, "1a 2b 3a 4b 5a 6b", meter=False)
    msg = str(e.value)
    assert "nothing was recorded" in msg and r1["sheet"] in msg and r2["sheet"] in msg and "--sheet" in msg
    assert "from project song-a" in msg and read_events(taps_path(proj)) == []
    out = SH.record(proj, "1a 2b 3a 4b 5a 6b", sheet=r1["sheet"], meter=False)
    assert out["sheet"] == r1["sheet"] and {e["sheet"] for e in read_events(taps_path(proj))} == {r1["sheet"]}
    out = SH.record(proj, "1b 2b 3b 4b 5b 6b", meter=False)                # now only r2 is open
    assert out["sheet"] == r2["sheet"]
    r3 = SH.make_sheets(proj, pairs=4, seed=5)                            # nothing open: a new sheet
    assert not r3.get("reprinted")
    code, j = run(capsys, "-p", str(proj), "taste", "sheet", "--discard", r3["sheet"])
    assert code == 0 and j["discarded"] and j["unanswered"] == [1, 2, 3, 4]
    r4 = SH.make_sheets(proj, pairs=4, seed=6)
    assert r4["sheet"] != r3["sheet"] and not r4.get("reprinted")
    late = SH.record(proj, "1a 2a 3a 4a", sheet=r3["sheet"], meter=False)        # a late reply still counts
    assert late["sheet"] == r3["sheet"] and late["recorded"] == [1, 2, 3, 4]
    code, j = run(capsys, "-p", str(proj), "taste", "record", "--sheet", "nope", "1a")
    assert code == 1 and "no sheet 'nope'" in j["error"]


@pytest.mark.parametrize("text,want", [
    ("1a 2b 12a.", [(1, "a"), (2, "b"), (12, "a")]),
    ("1a 2b ... thanks!", [(1, "a"), (2, "b")]),
    ("Here you go: 1a, 2b", [(1, "a"), (2, "b")]),
    ("1a. 2b. 3t.", [(1, "a"), (2, "b"), (3, "tie")]),
    ("1a 2b 👍", [(1, "a"), (2, "b")]),
    ("1a 🙏🏽 2b xx", [(1, "a"), (2, "b")]),
    ("1A 2B\nthank you so much!!", [(1, "a"), (2, "b")]),
])
def test_chat_endings_are_ignored(text, want):
    assert SH.parse_answers(text) == want


@pytest.mark.parametrize("text", ["1a 2b maybe", "1a thanks 2b", "1a 2b 3", "1a 2b and 3c", "thanks 4", "ok 1a 2"])
def test_anything_that_could_be_an_answer_is_still_an_error(text):
    with pytest.raises(SlopError, match="nothing was recorded"):
        SH.parse_answers(text)


def test_a_pool_without_vectors_says_run_embed(proj):
    S.write_images(proj.parent / "refs", {"grey": 6, "colour": 6})
    add_dir(PoolWriter(proj), proj.parent / "refs")
    r = SH.make_sheets(proj, pairs=4, seed=0)
    assert r["vectors"] is False and "slop taste embed" in r["text"]
    out = SH.record(proj, "1a 2b 3a 4b", sheet=r["sheet"])
    assert "slop taste embed" in out["text"] and "meter starts" not in out["text"] and out["meter"] is None


def test_seen_images_are_paired_again_but_never_the_same_pair(proj):
    ids, labs = S.fake_pool(proj, clusters=4, per=12, spread=0.45)       # 48 images: unseen run out after 2 sheets
    lab = dict(zip(ids, labs))
    rng = random.Random(0)
    whys, asked = [], []
    for k in range(7):
        r = SH.make_sheets(proj, pairs=12, seed=k)
        sheet = json.loads(Path(r["files"][0]).parent.joinpath("sheet.json").read_text(encoding="utf-8"))
        ans = []
        for p in sheet["pairs"]:
            whys.append((k, p["why"]))
            if p["why"] != "repeat":
                asked.append(frozenset((p["a"], p["b"])))
            la, lb = lab[p["a"]] in (0, 1), lab[p["b"]] in (0, 1)
            ans.append(f"{p['n']}{'a' if la and not lb else 'b' if lb and not la else rng.choice('ab')}")
        SH.record(proj, " ".join(ans), sheet=r["sheet"], meter=False)
    late = [w for k, w in whys if k >= 4]
    assert late.count("reuse") >= 8                                       # the pool ran out: seen images again
    assert len(asked) == len(set(asked))                                  # never the same pair twice


# ---------------------------------------------------------------- text-free check

@pytest.fixture
def letter_pool(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    p = S.make_project(tmp_path)
    d = tmp_path / "refs"
    S.write_images(d, {"grey": 24, "dark": 12, "light": 12, "red": 12, "colour": 12, "blue": 12})
    for k in range(16):
        TF.render_lettered(S.image(["grey", "colour", "blue", "dark"][k % 4], 900 + k), "headline", 40 + k) \
            .save(d / f"lettered-{k:03d}.png")
    add_dir(PoolWriter(p), d)
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    items = load_pool(p)
    ids, X, meta = load_store(p)
    return p, fe, items, ids, X / np.linalg.norm(X, axis=1, keepdims=True), meta


def test_pools_of_40_to_71_images_use_the_paired_probe(letter_pool):
    p, fe, items, ids, X, meta = letter_pool
    let = [k for k, i in enumerate(ids) if items[i]["title"].startswith("lettered")]
    clean = [k for k, i in enumerate(ids) if k not in set(let)]
    sel = clean[:52] + let[:8]                                             # 60 images, 8 lettered (the review's case)
    s, info = TF.assess(p, [ids[k] for k in sel], X[sel], items, meta, embedder=fe)
    assert info["score"] == "paired-probe" and info["backgrounds"] >= TF.PROBE_MIN
    is_let = np.array([items[ids[k]]["title"].startswith("lettered") for k in sel])
    assert (s[is_let] >= info["cutoff"]).mean() >= 0.85
    assert info["lettered_median"] > info["cutoff"] and info["score_range"][0] < info["score_range"][1]


def test_text_max_that_lets_lettering_through_is_refused(letter_pool):
    p, fe, items, ids, X, meta = letter_pool
    few = list(range(36))                                                  # zero-shot (under 40 images)
    with pytest.raises(SlopError, match=r"too loose for this pool.*not 0\.\.1"):
        TF.assess(p, [ids[k] for k in few], X[few], items, meta, embedder=fe, text_max=0.5)
    s, info = TF.assess(p, [ids[k] for k in few], X[few], items, meta, embedder=fe)
    ok = info["suggested_text_max"]
    _, info2 = TF.assess(p, [ids[k] for k in few], X[few], items, meta, embedder=fe, text_max=ok)
    assert info2["cutoff"] == ok and info2["score"] == "zero-shot"
    _, pr = TF.assess(p, ids, X, items, meta, embedder=fe)                 # the probe: refuse at the lettered median
    with pytest.raises(SlopError, match="lettered copies"):
        TF.assess(p, ids, X, items, meta, embedder=fe, text_max=pr["lettered_median"] + 0.01)


def test_the_board_prints_the_score_range(letter_pool, monkeypatch):
    p, fe, items, ids, X, meta = letter_pool
    monkeypatch.setattr(E, "text_embedder_for", lambda *a, **k: fe)
    r = T.board(p, "a quiet field", n=6, n_refs=4, embedder=fe)
    assert "scores here run" in r["text"] and "paired-probe scale" in r["text"]


# ---------------------------------------------------------------- the project style tail

def test_the_tail_has_no_light_and_no_unconfirmed_warm_note(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    p = S.make_project(tmp_path, "song")
    pj = json.loads((p / "project.json").read_text(encoding="utf-8"))
    pj["look"] = {"mode": "native", "accent": "#D97757"}                # the template default, never asked
    (p / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    ensure_link(p)
    (p / "taste").mkdir(exist_ok=True)
    (p / "taste" / "taste-tokens.json").write_text(json.dumps({
        "palette": {"restraint": "mono+1", "status": "measured", "accent": None, "accent_source": "ask-owner",
                    "ink": "#181e15", "paper": "#eeede8", "footage_grade": "native"},
        "ground": {"likes_dark": 20, "likes_light": 2, "status": "lead"}, "texture": {"apply": None},
        "type": {}}), encoding="utf-8")
    r = A.apply(p)
    tail = r["set"]["style_tail"]
    assert tail.startswith("green-black #181e15") and "warm note" not in tail and "#D97757" not in tail
    assert "night" not in tail and "light" not in tail.replace("light as", "")
    assert any(a.startswith("accent") for a in r["asks"]) and "time of day" in r["text"]
    VD.record(p, "palette.accent", "confirmed", value="#D97757", note="the orange")    # tokens not rebuilt
    VD.record(p, "texture", "rejected", note="no grain")
    r = A.apply(p, yes=True)
    assert r["sources"]["accent"] == "owner verdict" and r["sources"]["texture"] == "owner verdict"
    look = load_project(p)["look"]
    assert "one small clay-orange #D97757 light as the only warm note" in look["style_tail"]
    assert "grain" not in look["style_tail"] and "slop board plates" in r["text"]


# ---------------------------------------------------------------- the Feed's root, status for core, server, threads

def test_a_feed_keeps_the_root_it_started_with(tmp_path, monkeypatch, capsys):
    from slop.taste.feed import Feed
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    p = S.make_project(tmp_path, "song")
    ensure_link(p)
    S.fake_pool(p, clusters=3, per=12)
    f = Feed(p, seed=0)
    home_taste = tmp_path / "home" / "taste"
    assert f.root == user_profile_dir() == home_taste
    run(capsys, "-p", str(p), "taste", "use", "--profile", "project")          # relinked while the Feed lives
    assert taste_dir(p) == p / "taste"
    iid = next(iter(f.pool))
    f.record_tap({"item": iid, "action": "like"})
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "elsewhere"))               # a test restoring SLOP_HOME
    f.measure(f.X, f.index, [(i, 1.0, "human") for i in f.ids[:12]] + [(i, 0.0, "human") for i in f.ids[24:36]], [])
    assert len(read_events(home_taste / "taps.jsonl")) == 1 and (home_taste / "meter.jsonl").is_file()
    assert not (p / "taste" / "taps.jsonl").exists() and not (tmp_path / "elsewhere" / "taste").exists()
    assert f.wait_idle(5)


def test_status_stage_for_core_sees_the_shared_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    a = S.make_project(tmp_path, "first")
    ensure_link(a)
    S.fake_pool(a, clusters=2, per=10)
    tap(a, load_pool(a), like_kinds=("c0",))
    append_jsonl(taste_dir(a) / "meter.jsonl", {"t": "2026-10-01T00:00:00", "accuracy": 0.61, "margin": 0.1, "n": 20})
    b = S.make_project(tmp_path, "second")
    st = status_stage(b)
    assert st["done"] is False and st["next"] == "slop taste tokens" and st["taps"] == 20
    assert "shared taste profile: 20 taps, meter 61 %" in st["detail"]
    assert not (b / "taste").exists()                                          # nothing created
    (b / "taste").mkdir()
    (b / "taste" / "taste-tokens.json").write_text("{}", encoding="utf-8")
    assert status_stage(b)["done"] is True


def test_a_server_token_starting_with_a_dash(tmp_path, monkeypatch):
    from slop.taste import server as SV
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    S.write_images(tmp_path / "refs", {"grey": 4, "colour": 4})
    add_dir(PoolWriter(p), tmp_path / "refs")
    monkeypatch.setattr(SV.secrets, "token_urlsafe", lambda n: "-dash" + "x" * 20)
    r = SV.serve(p, embed=False)
    try:
        assert r["running"] and "/-dash" in r["urls"]["local"]
    finally:
        SV.stop(p)


def test_small_blas_and_the_child_environment(monkeypatch):
    from slop.taste import threads as TH
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "2")
    monkeypatch.delenv("MKL_NUM_THREADS", raising=False)
    assert TH.blas_env() == {"MKL_NUM_THREADS": "4"}                          # the user's own setting is kept
    with TH.small_blas():
        a = np.random.default_rng(0).normal(size=(64, 64))
        assert np.linalg.solve(a @ a.T + np.eye(64), np.ones(64)).shape == (64,)
