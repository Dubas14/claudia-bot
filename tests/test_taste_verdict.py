"""slop.taste.verdicts: owner verdicts on taste rules -> taste/verdicts.jsonl + DECISIONS.md; tokens honour them."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.taste import embed as E  # noqa: E402
from slop.taste import tokens as T  # noqa: E402
from slop.taste import verdicts as VD  # noqa: E402
from slop.taste.embed import embed_pool  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402
from slop.taste.profile import ensure_link  # noqa: E402
from slop.taste.store import append_jsonl, new_eid, read_jsonl, taps_path, user_profile_dir  # noqa: E402


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
    ensure_link(p)                                          # the CLI default: the user profile
    S.write_images(tmp_path / "refs", {"grey": 24, "dark": 8, "red": 6, "colour": 18, "stripes": 10, "blue": 6})
    add_dir(PoolWriter(p), tmp_path / "refs")
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    monkeypatch.setattr(E, "text_embedder_for", lambda *a, **k: fe)
    tap(p, load_pool(p))
    return p, fe


def test_verdict_confirms_a_rule_in_tokens_decisions_and_the_profile(tapped, capsys):
    p, fe = tapped
    t0 = T.build_tokens(p, embedder=fe)
    assert t0["palette"]["restraint"] == "mono+1" and t0["verdicts"]["applied"] == []
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "palette.restraint", "confirmed", "--note", "yes, this")
    assert code == 0 and j["verdict"]["value"] == "mono+1" and j["shared"] is True and "DECISIONS.md" in j["text"]
    rows = read_jsonl(p / "taste" / "verdicts.jsonl")
    assert rows[-1]["level"] == "rule" and rows[-1]["status"] == "confirmed" and rows[-1]["owner"]["note"] == "yes, this"
    assert read_jsonl(user_profile_dir() / "verdicts.jsonl")[-1]["vid"] == rows[-1]["vid"]
    dec = (p / "DECISIONS.md").read_text(encoding="utf-8")
    assert "TASTE palette.restraint mono+1: CONFIRMED ('yes, this')" in dec and "[owner]" in dec
    t = T.build_tokens(p, embedder=fe)
    pal = t["palette"]
    assert pal["status"] == "confirmed" and pal["stat_status"] in ("measured", "lead")
    assert any(r["id"] == "palette.restraint" and r["status"] == "confirmed" for r in t["rules"])
    md = (p / "taste" / "look-bible.md").read_text(encoding="utf-8")
    assert "Your verdicts" in md and "palette.restraint = mono+1: **confirmed**" in md


def test_texture_and_owner_rules_answer_their_questions(tapped):
    p, fe = tapped
    T.build_tokens(p, embedder=fe)
    VD.record(p, "texture", "rejected", note="no grain please")             # "Add grain?" -> no: NO grain
    VD.record(p, "palette.accent", "confirmed", value="d97757", note="use the orange")
    VD.record(p, "palette.footage_grade", "confirmed", value="print")
    t = T.build_tokens(p, embedder=fe)
    assert t["texture"]["status"] == "rejected" and t["texture"]["apply"] is False
    assert t["look_suggestion"]["texture"] is False
    assert t["palette"]["accent"] == "#D97757" and t["palette"]["footage_grade"] == "print"
    open_ids = [q["id"] for q in t["open_questions"]]
    assert "accent" not in open_ids and "texture" not in open_ids and "footage_grade" not in open_ids
    ans = {q["id"]: q["answer"] for q in t["answered_questions"]}
    assert ans["accent"] == "#D97757" and ans["footage_grade"] == "print"
    assert t["look_suggestion"]["look.accent"] == "#D97757" and t["look_suggestion"]["look.mode"] == "print"
    # a frame-level verdict (the hand-appended kind, docs/30 §5) answers the style-frame question
    append_jsonl(p / "taste" / "verdicts.jsonl", {"t": "2026-10-02", "level": "frame", "artifact": "frames/2.jpg",
                                                  "owner": {"verdict": "pick", "note": "this one"}})
    t = T.build_tokens(p, embedder=fe)
    assert "style_frame" not in [q["id"] for q in t["open_questions"]]


def test_a_verdict_binds_to_the_value_it_judged(tapped):
    p, fe = tapped
    T.build_tokens(p, embedder=fe)
    append_jsonl(p / "taste" / "verdicts.jsonl", {"vid": "old1", "t": "2026-09-01T00:00:00", "level": "rule",
                                                  "rule": "palette.restraint", "value": "colourful",
                                                  "status": "confirmed", "owner": {"verdict": "accept"},
                                                  "project": "song-a"})
    t = T.build_tokens(p, embedder=fe)
    assert t["palette"]["status"] in ("measured", "lead")                   # not confirmed: the taps say mono+1 now
    st = t["verdicts"]["stale"]
    assert st and st[0]["rule"] == "palette.restraint" and "ask again" in st[0]["why"] and st[0]["now"] == "mono+1"
    assert "Verdicts to ask again" in (p / "taste" / "look-bible.md").read_text(encoding="utf-8")


def test_verdicts_carry_to_the_next_project_and_own_verdicts_win(tapped, tmp_path):
    p, fe = tapped
    T.build_tokens(p, embedder=fe)
    VD.record(p, "palette.restraint", "confirmed", note="first song")
    b = S.make_project(tmp_path, "song-b")
    ensure_link(b)
    t = T.build_tokens(b, embedder=fe)
    v = next(v for v in t["verdicts"]["applied"] if v["rule"] == "palette.restraint")
    assert t["palette"]["status"] == "confirmed" and v["carried"] is True and v["project"] == "song-a"
    VD.record(b, "palette.restraint", "rejected", note="not for this one")
    t = T.build_tokens(b, embedder=fe)
    assert t["palette"]["status"] == "rejected" and t["look_suggestion"]["graphics_palette"]["restraint"] is None
    assert T.build_tokens(p, embedder=fe)["palette"]["status"] == "confirmed"     # song-a keeps its own verdict


def test_the_accent_is_per_video_but_proposed_again_next_time(tapped, tmp_path):
    p, fe = tapped
    T.build_tokens(p, embedder=fe)
    VD.record(p, "palette.accent", "confirmed", value="#D97757", note="use the orange")
    VD.record(p, "texture", "confirmed", value="yes")
    b = S.make_project(tmp_path, "song-b")
    ensure_link(b)
    t = T.build_tokens(b, embedder=fe)
    assert t["palette"]["accent"] is None and t["look_suggestion"]["look.accent"] is None      # not applied …
    q = next(q for q in t["open_questions"] if q["id"] == "accent")
    assert q["proposal"].startswith("last time (song-a): #D97757") and q["previous"]["value"] == "#D97757"  # … proposed
    assert t["verdicts"]["previous"]["palette.accent"]["project"] == "song-a"
    assert t["texture"]["apply"] is True and "texture" not in [x["id"] for x in t["open_questions"]]  # taste carries
    with pytest.raises(SlopError, match="yes/no question"):
        VD.record(b, "texture", "confirmed", value="lots")


def test_rejected_lyric_font_falls_to_the_next_and_avoid_sources(tapped):
    p, fe = tapped
    t = T.build_tokens(p, embedder=fe)
    t["type"] = {"lyric": "Geist", "shortlist": ["Geist", "DINish"], "status": "lead"}
    t["anti_sources"] = [{"source": "dir:junk", "taps": 8, "like_rate": 0.0, "p": 0.01}]
    t["open_questions"].append({"id": "avoid:dir:junk", "ask": "?", "evidence": "", "proposal": "", "answer": None})
    rows = [{"vid": "1", "t": "2026-10-01T00:00:01", "level": "rule", "rule": "type.lyric", "value": "Geist",
             "status": "rejected", "project": "song-a"},
            {"vid": "2", "t": "2026-10-01T00:00:02", "level": "rule", "rule": "avoid:dir:junk", "value": "banned",
             "status": "confirmed", "project": "song-a"}]
    VD.honour(t, rows, "song-a")
    assert t["type"]["lyric"] == "DINish" and t["type"]["rejected"] == ["Geist"]
    assert t["anti_sources"][0]["banned"] is True and "avoid:dir:junk" not in [q["id"] for q in t["open_questions"]]


def test_verdict_errors_and_listing(tapped, capsys):
    p, fe = tapped
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "--list")
    assert code == 0 and j["tokens"] is False and "palette.accent" in j["text"]
    with pytest.raises(SlopError, match="slop taste tokens"):
        VD.record(p, "palette.restraint", "confirmed")                     # no tokens yet: only the owner's rules
    T.build_tokens(p, embedder=fe)
    code, j = run(capsys, "-p", str(p), "taste", "verdict")
    assert code == 0 and j["tokens"] is True and any(r["id"] == "palette.restraint" for r in j["rules"])
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "palette.nonsense", "confirmed")
    assert code == 1 and "unknown rule" in j["error"] and "--list" in j["error"]
    code, j = run(capsys, "-p", str(p), "taste", "verdict", "palette.restraint")
    assert code == 1 and "confirmed or rejected" in j["error"]
    with pytest.raises(SlopError, match="hex colour"):
        VD.record(p, "palette.accent", "confirmed", value="orange")
    with pytest.raises(SlopError, match="footage grade"):
        VD.record(p, "palette.footage_grade", "confirmed", value="mono")
    with pytest.raises(SlopError, match="no value yet"):
        VD.record(p, "type.lyric", "confirmed")
