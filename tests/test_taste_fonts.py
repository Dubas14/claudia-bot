"""slop.taste.fonts: discovery (OFL only), counterbalanced schedule, session, position-corrected Bradley–Terry."""
import itertools
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.config import SlopError  # noqa: E402
from slop.taste import fonts as F  # noqa: E402
from slop.taste.store import append_jsonl  # noqa: E402

FACES = [("SpaceGrotesk-Medium.ttf", "Space Grotesk", "Medium"), ("Geist-Regular.ttf", "Geist", "Regular"),
         ("DINish-Bold.ttf", "DINish", "Bold"), ("BarlowCondensed-Regular.ttf", "Barlow Condensed", "Regular"),
         ("BarlowCondensed-Medium.ttf", "Barlow Condensed", "Medium"), ("IBMPlexMono-Regular.ttf", "IBM Plex Mono", "Regular"),
         ("JetBrainsMono-Regular.ttf", "JetBrains Mono", "Regular"), ("ShareTechMono-Regular.ttf", "Share Tech Mono", "Regular"),
         ("InstrumentSerif-Italic.ttf", "Instrument Serif", "Italic"), ("InstrumentSerif-Regular.ttf", "Instrument Serif", "Regular"),
         ("Audiowide-Regular.ttf", "Audiowide", "Regular"),
         ("NimbusSans-Bold.otf", "Nimbus Sans", "Bold"), ("PilcrowRounded.ttf", "Pilcrow Rounded", "Regular"),
         ("Junicode-Regular.ttf", "Junicode", "Regular")]


@pytest.fixture
def fontdir(tmp_path, monkeypatch):
    d = tmp_path / "fonts"
    d.mkdir()
    for fn, fam, st in FACES:
        S.fake_font(d / fn, fam, st)
    monkeypatch.setattr(F, "font_dirs", lambda extra=None: [d])
    return d


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    (p / "lyrics" / "display.txt").write_text("[Verse 1]\nSignals. Systems. *Strangers.*\nwe ship it at +25%|3 tonight\n"
                                              "go\nthe long room holds its breath again\n[note: not a lyric line]\n"
                                              "orbit reached tonight\n",
                                              encoding="utf-8")
    (p / "plates").mkdir()
    S.image("light", 4, (1920, 1080)).save(p / "plates" / "hero.jpg")
    pj = json.loads((p / "project.json").read_text())
    pj["look"] = {"hero_plate": "plates/hero.jpg"}
    (p / "project.json").write_text(json.dumps(pj))
    return p


def test_sfnt_names_and_ofl_only_discovery(fontdir):
    assert F.sfnt_names(fontdir / "SpaceGrotesk-Medium.ttf") == {"family": "Space Grotesk", "style": "Medium", "variable": False}
    fams = {f["family"] for f in F.scan_fonts([fontdir])}
    assert "Nimbus Sans" not in fams and "Pilcrow Rounded" not in fams and "Junicode" not in fams
    faces = F.pick_faces(F.scan_fonts([fontdir]), F.DEFAULT_FAMILIES)
    assert [f["family"] for f in faces] == F.DEFAULT_FAMILIES
    barlow = next(f for f in faces if f["family"] == "Barlow Condensed")
    assert barlow["file"] == "BarlowCondensed-Medium.ttf" and barlow["weight"] == 500
    serif = next(f for f in faces if f["family"] == "Instrument Serif")
    assert serif["file"] == "InstrumentSerif-Regular.ttf"                 # never the italic
    assert "Audiowide" in F.DEFAULT_FAMILIES and "Instrument Serif" in F.DEFAULT_FAMILIES   # a serif + a display face


@pytest.mark.parametrize("n_fonts", [2, 3, 5, 7, 9])
def test_schedule_counterbalanced(n_fonts):
    cards = F.schedule(n_fonts, 4, seed=n_fonts)
    n_pairs = n_fonts * (n_fonts - 1) // 2
    assert len(cards) == 2 * n_pairs and [c["card"] for c in cards] == list(range(len(cards)))
    by = {}
    for pos, c in enumerate(cards):
        by.setdefault((c["a"], c["b"]), []).append((pos, c))
    assert set(by) == set(itertools.combinations(range(n_fonts), 2))
    for (a, b), shows in by.items():
        assert len(shows) == 2
        (p1, c1), (p2, c2) = shows
        assert {c1["shown"], c2["shown"]} == {"ab", "ba"} and c1["line"] == c2["line"]
        assert p2 - p1 >= min(F.MIN_GAP, n_pairs)
    firsts = sum(1 for c in cards if c["shown"] == "ab")
    assert firsts == n_pairs                              # each family is first exactly as often as second


def test_setup_session_lines_frame_and_idempotence(proj, fontdir):
    r = F.setup(proj, seed=1)
    s = r["session"]
    assert r["created"] and len(s["fonts"]) == 8 and len(s["cards"]) == 56
    assert "we ship it at +25% tonight" in s["lines"] and "go" not in s["lines"]
    assert "Signals. Systems. Strangers." in s["lines"]                 # style markers stripped
    assert not any(line.startswith("[") or line.startswith("#") for line in s["lines"])
    assert s["frame_source"] == "project.json look.hero_plate" and s["provisional"] is False
    assert s["ink"] == "#121212"                          # light ground -> dark ink (composer rule)
    assert (proj / "taste" / "fonts" / "frame.jpg").exists()
    again = F.setup(proj)
    assert again["created"] is False and again["session"]["id"] == s["id"]
    new = F.setup(proj, reset=True, families=["Geist", "DINish", "IBM Plex Mono"], texts=["a b c"])
    assert new["session"]["id"] != s["id"] and len(new["session"]["cards"]) == 6


def test_setup_errors_are_actionable(proj, fontdir, tmp_path):
    with pytest.raises(SlopError, match="fonts"):
        F.setup(proj, families=["Nimbus Sans", "Comic Neue"], reset=True)
    bare = S.make_project(tmp_path, "bare")
    with pytest.raises(SlopError, match="lyrics"):
        F.setup(bare)
    r = F.setup(bare, texts=["hold still", "open circuit now"], seed=2)
    assert r["session"]["provisional"] is True and r["session"]["ink"] == "#f3f1ea"


def test_session_next_record_undo(proj, fontdir):
    F.setup(proj, seed=3)
    fs = F.FontSession(proj)
    nxt = fs.next([])
    c = nxt["cards"][0]
    assert c["first"]["family"] != c["second"]["family"] and c["line"] in fs.sess["lines"]
    rec = fs.record({"card": c["card"], "winner": "first", "layout": "row", "dwell_ms": 4000})
    assert rec[rec["winner"]] == c["first"]["family"] and rec["first"] == c["first"]["family"]
    assert rec["shown"] == c["shown"] and rec["layout"] == "row"
    assert fs.progress()["answered"] == 1 and fs.progress()["first_slot_wins"] == 1
    assert fs.next([])["cards"][0]["card"] != c["card"]
    fs.undo(rec["eid"])
    assert fs.progress()["answered"] == 0
    with pytest.raises(ValueError):
        fs.record({"card": 999, "winner": "first"})
    assert fs.font_path(fs.sess["fonts"][0]["file"]) is not None and fs.font_path("../../etc/passwd") is None


def simulate(proj, theta, gamma, n_rounds, seed=0, session="s1"):
    rng = random.Random(seed)
    fams = list(theta)
    for r in range(n_rounds):
        for a, b in itertools.combinations(fams, 2):
            for shown in ("ab", "ba"):
                first, second = (a, b) if shown == "ab" else (b, a)
                p = 1 / (1 + math.exp(-(theta[first] - theta[second] + gamma)))
                w_first = rng.random() < p
                winner_family = first if w_first else second
                append_jsonl(F.taps_file(proj), {"eid": f"{session}{r}{a}{b}{shown}", "session": session, "card": 0,
                                                 "a": a, "b": b, "first": first, "second": second, "shown": shown,
                                                 "layout": "stack", "winner": "a" if winner_family == a else "b",
                                                 "line": 0})


def test_bt_with_first_slot_term_recovers_gamma_and_order(proj):
    theta = {"Geist": 1.0, "DINish": 0.5, "Space Grotesk": 0.0, "IBM Plex Mono": -0.5, "Share Tech Mono": -1.0}
    simulate(proj, theta, 0.86, n_rounds=30)
    r = F.rank(proj)
    assert r["gamma"] == pytest.approx(0.86, abs=0.25)
    assert r["first_slot_rate"] > 0.6 and r["binom_p"] < 0.05
    order = [x["family"] for x in r["fonts"]]
    assert order[0] == "Geist" and order[-1] == "Share Tech Mono"
    assert r["recommendation"]["lyric"] == "Geist"
    assert r["sessions"]["s1"]["gated"] is True and r["sessions"]["s1"]["weight"] < 1
    # every decisive game came from a gated session: a lead, and the advice is better options, not more pairs
    assert r["recommendation"]["status"] == "lead" and r["recommendation"]["action"] == "show better options"
    assert "better options" in r["text"]
    assert r["counterbalanced"]["pairs_both_orders"] > 0
    assert (proj / "taste" / "fonts" / "ranking.json").exists() and "γ" in r["text"]


def test_first_slot_only_winners_are_flagged_never_preferred(proj):
    # (first slot, second slot, winner): Geist wins twice, both times from the first slot
    rows = [("Geist", "DINish", "Geist"), ("Geist", "IBM Plex Mono", "Geist"),
            ("DINish", "IBM Plex Mono", "IBM Plex Mono"), ("IBM Plex Mono", "DINish", "IBM Plex Mono")]
    for k, (first, second, w) in enumerate(rows):
        a, b = sorted((first, second))
        append_jsonl(F.taps_file(proj), {"eid": f"e{k}", "session": "s", "card": k, "a": a, "b": b, "first": first,
                                         "second": second, "shown": "ab" if first == a else "ba", "layout": "row",
                                         "winner": "a" if w == a else "b", "line": 0})
    r = F.rank(proj)
    g = next(x for x in r["fonts"] if x["family"] == "Geist")
    assert g["wins"] == 2 and g["wins_second"] == 0 and g["flag"] == "first-slot-only wins" and not g["preferred"]
    plex = next(x for x in r["fonts"] if x["family"] == "IBM Plex Mono")
    assert plex["wins_second"] == 1
    assert r["recommendation"]["status"] == "lead"


def test_rank_empty(proj):
    r = F.rank(proj)
    assert r["decisive"] == 0 and "no decisive" in r["text"]


def test_bt_naive_matches_retired_optimizer_behaviour():
    th = F.bt_naive([(0, 1), (0, 1), (0, 1)], 2)
    assert th[0] > 0 > th[1] and abs(th[0] + th[1]) < 1e-9
    theta, gamma = F.bt_fit([(0, 1, 1.0)] * 10 + [(1, 0, 1.0)] * 10, 2)
    assert abs(theta[0] - theta[1]) < 1e-6 and gamma > 1.5          # all wins from the first slot = pure bias
    assert np.all(np.isfinite(theta))


def test_unbiased_session_is_measured(proj):
    theta = {"Geist": 1.0, "DINish": 0.5, "Space Grotesk": 0.0, "IBM Plex Mono": -0.5, "Share Tech Mono": -1.0}
    simulate(proj, theta, 0.0, n_rounds=12, seed=3)
    r = F.rank(proj)
    assert r["sessions"]["s1"]["gated"] is False and abs(r["gamma"]) < 0.5
    assert r["recommendation"]["status"] == "measured" and r["recommendation"]["lyric"] in ("Geist", "DINish")
    assert r["fonts"][-1]["family"] == "Share Tech Mono" and "action" not in r["recommendation"]


def test_split_votes_are_ties_in_the_tallies(proj):
    # Geist vs DINish shown in both orders, the first slot wins both times -> a split = a tie;
    # Geist vs Plex in both orders, Geist wins both -> agreement, real wins
    rows = [("Geist", "DINish", "Geist"), ("DINish", "Geist", "DINish"),
            ("Geist", "IBM Plex Mono", "Geist"), ("IBM Plex Mono", "Geist", "Geist")]
    for k, (first, second, w) in enumerate(rows):
        a, b = sorted((first, second))
        append_jsonl(F.taps_file(proj), {"eid": f"t{k}", "session": "s", "card": k, "a": a, "b": b, "first": first,
                                         "second": second, "shown": "ab" if first == a else "ba", "layout": "row",
                                         "winner": "a" if w == a else "b", "line": 0})
    r = F.rank(proj)
    g = next(x for x in r["fonts"] if x["family"] == "Geist")
    d = next(x for x in r["fonts"] if x["family"] == "DINish")
    assert r["counterbalanced"] == {"pairs_both_orders": 2, "agree": 1, "split_ties": 1, "self_agreement": 0.5}
    assert (g["wins"], g["losses"], g["split_ties"]) == (2, 0, 1) and g["wins_second"] == 1 and g["preferred"]
    assert (d["wins"], d["losses"], d["split_ties"]) == (0, 0, 1) and d["flag"] is None
    assert r["decisive"] == 4 and r["decisive_games"] == 2 and r["split_ties"] == 1


def test_clean_line_strips_display_markers():
    assert F.clean_line("we *left* the _ground_ at ~dawn~ +25%|4") == "we left the ground at dawn +25%"
    assert F.clean_line("keep snake_case and 3*4 as is ->|0") == "keep snake_case and 3*4 as is ->"


def test_font_page_prefers_side_by_side_and_anchor_tracking():
    static = Path(F.__file__).parent / "static"
    js = (static / "fonts.js").read_text(encoding="utf-8")
    assert "function layout() { return 'row'; }" in js and "sideways" in js
    css = (static / "app.css").read_text(encoding="utf-8")
    assert "letter-spacing:-.03em" in css
