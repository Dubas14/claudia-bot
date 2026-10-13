"""`slop song sections --set/--clear` and `slop song bars --phase/--method`: project.json, rebuilt analysis, the report,
DECISIONS.md and the stale mark on a storyboard draft."""
from __future__ import annotations

import io
import json
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "audio"))

import synth  # noqa: E402

from slop.audio import overrides as ov  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402


def slop(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


@pytest.fixture(scope="module")
def analysed(tmp_path_factory):
    """A synthetic song with a real beat map + sections + hits, fake word timing and a tagged sheet (built once)."""
    song = synth.make_song(dur=40.0, phase=1, drop_at=20.0)
    root = synth.write_project(tmp_path_factory.mktemp("ov") / "base", song)
    syl = song["syllables"]
    words = []
    for li, (p0, p1) in enumerate(((4, 7), (12, 15.5), (24, 27), (32, 35))):
        for s0, s1 in [s for s in syl if p0 <= s[0] < p1][:3]:
            words.append({"i": len(words), "w": "la", "line": li, "t0": s0, "t1": s1, "conf": 0.9, "src": "w2v"})
    (root / "analysis").mkdir(parents=True, exist_ok=True)
    from slop.audio.merge import finish
    (root / "analysis" / "words.json").write_text(json.dumps(finish(words, ["la la la"] * 4)))
    (root / "lyrics").mkdir(exist_ok=True)
    (root / "lyrics" / "lyrics.txt").write_text("[Intro]\nla la la\n[Verse 1]\nla la la\n[Chorus]\nla la la\n"
                                                "[Outro]\nla la la\n", encoding="utf-8")
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats,sections,hits")
    assert rc == 0, out
    return root, song, words


@pytest.fixture()
def proj(analysed, tmp_path):
    root = tmp_path / "p"
    shutil.copytree(analysed[0], root)
    return root, analysed[1], analysed[2]


def _board(root: Path, draft: bool) -> Path:
    p = root / "board" / "shots.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "draft": draft, "duration": 40.0, "chapters": [], "shots": [],
                             "seedance": [], "plates": []}), encoding="utf-8")
    return p


def test_parse_spec_forms():
    got = ov.parse_spec("Intro@0, verse 1@bar8 ,chorus1@line9,bridge@1:42.5, outro@200.25s")
    assert got == [{"name": "intro", "t0": 0.0}, {"name": "verse-1", "bar": 8}, {"name": "chorus1", "line": 9},
                   {"name": "bridge", "t0": 102.5}, {"name": "outro", "t0": 200.25}]
    for bad, msg in (("verse1", "NAME@START"), ("verse1@soon", "seconds"), ("a@0,a@10", "used twice"),
                     ("x@line0", "count from 1"), ("", "NAME@START"), ("@3", "NAME@START")):
        with pytest.raises(SlopError, match=msg):
            ov.parse_spec(bad)


def test_sections_show_and_set_and_clear(proj):
    root, song, words = proj
    rc, out = slop("-p", str(root), "song", "sections")
    assert rc == 0, out
    assert out["from"].startswith("lyrics tags") and not out["changed"]
    board = _board(root, draft=True)
    rc, out = slop("-p", str(root), "song", "sections", "--set", "intro@0,verse1@bar4,chorus1@line3,outro@36.5")
    assert rc == 0, out
    assert out["changed"] and out["from"] == "project.json"
    pj = json.loads((root / "project.json").read_text())
    assert pj["audio"]["sections"] == [{"name": "intro", "t0": 0.0}, {"name": "verse1", "bar": 4},
                                       {"name": "chorus1", "line": 3}, {"name": "outro", "t0": 36.5}]
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert [s["name"] for s in B["sections"]] == ["intro", "verse1", "chorus1", "outro"]
    assert all(s["source"] == "set" for s in B["sections"])
    assert B["sections"][1]["t0"] == pytest.approx(B["downbeats"][4], abs=1e-3)
    near = min([0.0] + B["downbeats"], key=lambda d: abs(d - 36.5))         # seconds snap to the nearest bar line
    assert B["sections"][3]["t0"] == pytest.approx(near, abs=1e-3)
    assert any(x.startswith("outro: 36.50 s -> bar ") for x in out["snapped"]) and "snapped: outro" in out["text"]
    dec = (root / "DECISIONS.md").read_text(encoding="utf-8")
    assert "sections set: intro@0.00s" in dec and "[slop song sections]" in dec
    S = json.loads(board.read_text())                 # an untouched (empty) draft: marked stale, re-draft is the fix
    assert S["stale"] and "board draft --force" in S["stale"][-1]["fix"] and "sections set" in S["stale"][-1]["why"]
    assert "marked stale" in out["text"] and "board draft --force" in out["text"]
    assert all(f"{s['name']}@" in out["text"] for s in B["sections"])     # each section's --set START is shown
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "set by the owner" in rep and "UNCONFIRMED:" not in rep
    # the same set again: no new decision line (core dedups), still fine
    rc, out = slop("-p", str(root), "song", "sections", "--clear")
    assert rc == 0 and out["changed"]
    assert "sections" not in json.loads((root / "project.json").read_text())["audio"]
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["sections_from"].startswith("lyrics tags")
    assert "override cleared" in (root / "DECISIONS.md").read_text(encoding="utf-8")
    rc, out = slop("-p", str(root), "song", "sections", "--clear")           # nothing to clear: no change
    assert rc == 0 and not out["changed"]


def test_sections_set_errors_change_nothing(proj):
    root, *_ = proj
    before = (root / "project.json").read_text()
    for spec, msg in (("intro@0,verse1@bar999", "--set: bar 999 is outside"), ("intro@0,verse1@500", "outside the song"),
                      ("intro@0,chorus1@line99", "--set: lyric line 99 has no aligned word"), ("a@10,b@10", "same time"),
                      ("intro@bar4,verse1@line3", 'already uses the name "intro"'),
                      ("verse1@bar4,intro@bar6", 'already uses the name "intro"')):
        rc, out = slop("-p", str(root), "song", "sections", "--set", spec)
        assert rc == 1 and msg in out["error"], (spec, out)
        assert "`slop " not in out["error"] or "--project" in out["error"], out["error"]
    assert (root / "project.json").read_text() == before
    assert not (root / "DECISIONS.md").exists() or "sections set" not in (root / "DECISIONS.md").read_text()


def _real_board(root: Path) -> Path:
    rc, out = slop("-p", str(root), "board", "draft", "--force")
    assert rc == 0, out
    return root / "board" / "shots.json"


def test_an_edited_draft_board_is_never_written(proj):
    """`board draft` writes "draft": true and the board module keeps it through every edit: an edited board must be
    left alone (no stale mark, no `board draft --force` advice), with the shots on moved boundaries listed."""
    root, *_ = proj
    board = _real_board(root)
    assert json.loads(board.read_text())["draft"] is True
    rc, out = slop("-p", str(root), "board", "set", "s001", "--set", "a rooftop at dusk under sodium lamps",
                   "--framing", "MS", "--action", "she turns toward the city as the beat drops")
    assert rc == 0, out
    S = json.loads(board.read_text())
    assert S["draft"] is True                                  # the flag survives the edit
    before = board.read_bytes()
    rc, out = slop("-p", str(root), "song", "sections", "--set", "intro@0,verse1@bar3,chorus1@line3,outro@bar16")
    assert rc == 0, out
    assert board.read_bytes() == before                        # not written (a board approval covers its sha1)
    b = out["board"]
    assert b["untouched"] is False and b["marked"] is False and "s001 has its set written" in b["why_kept"]
    assert "board draft --force" not in out["text"] and "do NOT re-draft" in out["text"]
    assert "board draft --out" in out["text"] and "shots.redraft.json" in out["text"] and "--project" in out["text"]
    assert b["shots"] and all({"id", "t0", "t1", "why"} <= set(x) for x in b["shots"])
    assert not (root / "board" / "shots.redraft.json").exists()
    ph = json.loads((root / "analysis" / "beats.json").read_text())["downbeat_phase"]
    rc, out = slop("-p", str(root), "song", "bars", "--phase", str((ph + 1) % 4))
    assert rc == 0, out
    assert board.read_bytes() == before and out["board"]["marked"] is False
    assert "board draft --force" not in out["text"]
    rc, out = slop("-p", str(root), "song", "sections", "--clear")
    assert rc == 0 and board.read_bytes() == before and "board draft --force" not in out["text"]


def test_an_untouched_draft_is_marked_and_an_approved_one_is_not(proj):
    root, *_ = proj
    board = _real_board(root)
    rc, out = slop("-p", str(root), "song", "sections", "--set", "intro@0,verse1@bar3,chorus1@line3")
    assert rc == 0, out
    S = json.loads(board.read_text())
    assert out["board"]["marked"] and S["stale"] and "board draft --force" in out["text"]
    board = _real_board(root)                                  # a re-draft clears the mark
    assert "stale" not in json.loads(board.read_text())
    pj = json.loads((root / "project.json").read_text())       # approved untouched draft: still never written
    pj.setdefault("gates", {})["board_approved"] = True
    (root / "project.json").write_text(json.dumps(pj))
    before = board.read_bytes()
    rc, out = slop("-p", str(root), "song", "sections", "--clear")
    assert rc == 0, out
    assert board.read_bytes() == before and out["board"]["approved"] and "ask the owner again" in out["text"]


def test_analyze_and_lyrics_fix_check_the_board_when_sections_move(proj):
    root, *_ = proj
    board = _real_board(root)
    sheet = root / "lyrics" / "lyrics.txt"
    sheet.write_text(sheet.read_text(encoding="utf-8").replace("[Verse 1]", "[Bridge]"), encoding="utf-8")
    rc, out = slop("-p", str(root), "analyze", "--steps", "sections")
    assert rc == 0, out
    assert out["board"] and out["board"]["marked"] and json.loads(board.read_text())["stale"]
    assert any("board/shots.json was built on the old ones" in n for n in out["next"])
    board = _real_board(root)
    rc, _ = slop("-p", str(root), "board", "set", "s002", "--framing", "WS")
    assert rc == 0
    before = board.read_bytes()
    rc, out = slop("-p", str(root), "lyrics", "fix", "--line", "3", "--shift", "2.2")   # the chorus's line moves
    assert rc == 0, out
    assert board.read_bytes() == before
    assert out["board"] and out["board"]["marked"] is False and "board draft --force" not in out["text"]
    assert "Sections re-placed from the lyric tags" in out["text"]


def test_sections_need_the_analysis(tmp_path):
    root = synth.write_project(tmp_path / "bare")
    rc, out = slop("-p", str(root), "song", "sections", "--set", "intro@0")
    assert rc == 1 and "analyze" in out["error"]
    rc, out = slop("-p", str(root), "song", "bars")
    assert rc == 1 and "analyze" in out["error"]


def test_bars_show_set_and_back_to_the_vote(proj):
    from slop.audio import beatmap
    root, song, _ = proj
    rc, out = slop("-p", str(root), "song", "bars")
    assert rc == 0, out
    voted = out["downbeat_phase"]
    assert "bar 0 (the first bar line) starts at" in out["text"] and "bar 1 " not in out["text"]
    assert len(out["evidence"]) == 4 and sum(e["kick_blocks"] for e in out["evidence"]) >= 1
    assert out["evidence"][voted]["first_bar"] == pytest.approx(out["first_bar"], abs=1e-3)
    assert "kick votes" in out["text"] and "--phase N" in out["text"] and "<- now" in out["text"]
    B0 = json.loads((root / "analysis" / "beats.json").read_text())
    new = (voted + 2) % 4
    board = _board(root, draft=True)
    calls = []
    real_build = beatmap.build

    def spy(*a, **k):
        calls.append(1)
        return real_build(*a, **k)
    beatmap.build = spy
    try:
        rc, out = slop("-p", str(root), "song", "bars", "--phase", str(new))
    finally:
        beatmap.build = real_build
    assert rc == 0, out
    assert not calls                                   # the fast path: no audio re-analysis
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["downbeat_phase"] == new and B["downbeat_method"] == "project.json"
    assert B["downbeats"] == [round(b, 4) for b in B0["beats"][new::4]] and B["beats"] == B0["beats"]
    assert json.loads((root / "project.json").read_text())["audio"]["downbeat_phase"] == new
    assert out["rebuilt"]["sections"] == "done" and out["rebuilt"]["hits"] == "done"
    assert B["sections"] and all(any(abs(s["t0"] - d) < 1e-3 for d in [0.0] + B["downbeats"]) for s in B["sections"])
    dec = (root / "DECISIONS.md").read_text(encoding="utf-8")
    assert f"bar phase {new} (set)" in dec and "[slop song bars]" in dec
    assert json.loads(board.read_text())["stale"]
    # the state stays consistent: a plain analyze run does not redo the beat map
    rc, out2 = slop("-p", str(root), "analyze", "--steps", "beats")
    assert rc == 0 and out2["steps"]["beats"]["status"] == "up-to-date", out2["steps"]
    rc, out = slop("-p", str(root), "song", "bars", "--phase", "auto")
    assert rc == 0, out
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["downbeat_phase"] == voted and B["downbeats"] == B0["downbeats"]
    assert "downbeat_phase" not in json.loads((root / "project.json").read_text())["audio"]
    rc, out = slop("-p", str(root), "song", "bars", "--phase", "7")
    assert rc == 1 and "0, 1, 2 or 3" in out["error"]


def test_bars_method_uses_the_stored_votes(proj):
    root, *_ = proj
    B0 = json.loads((root / "analysis" / "beats.json").read_text())
    rc, out = slop("-p", str(root), "song", "bars", "--method", "harmony")
    assert rc == 0, out
    assert json.loads((root / "project.json").read_text())["audio"]["downbeat_method"] == "harmony"
    B = json.loads((root / "analysis" / "beats.json").read_text())
    H = B0["downbeat_votes"]["harmony"]
    assert B["downbeat_phase"] == (H["phase"] if H else B0["downbeat_phase"])
    rc, out = slop("-p", str(root), "song", "bars", "--method", "kick")
    assert rc == 0 and "downbeat_method" not in json.loads((root / "project.json").read_text())["audio"]


def test_log_decision_without_core(tmp_path, monkeypatch):
    root = synth.write_project(tmp_path / "nocore")
    monkeypatch.setitem(sys.modules, "slop.core_cli", None)          # core module absent: plain append
    r = ov.log_decision(root, "sections set: intro@0.00s [slop song sections]")
    assert r["recorded"]
    txt = (root / "DECISIONS.md").read_text(encoding="utf-8")
    assert txt.startswith("# decisions") and "- " in txt and "sections set: intro@0.00s" in txt


def test_bars_count_from_0_in_every_command(proj):
    root, *_ = proj
    rc, bars = slop("-p", str(root), "song", "bars")
    assert rc == 0, bars
    rc, out = slop("-p", str(root), "song", "sections", "--set", "intro@0,verse1@bar0,chorus1@bar2")
    assert rc == 0, out
    B = json.loads((root / "analysis" / "beats.json").read_text())
    v = next(s for s in B["sections"] if s["name"] == "verse1")
    assert v["t0"] == pytest.approx(bars["first_bar"], abs=1e-3) and v["bar0"] == 0   # what `song bars` calls bar 0
    assert "verse1@bar0" in out["text"] and "chorus1@bar2" in out["text"]
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "verse1@bar0" in rep and "Bars count from 0" in rep


def test_a_hand_written_override_that_starts_late_gets_intro0(proj):
    root, *_ = proj
    pj = json.loads((root / "project.json").read_text())
    pj.setdefault("audio", {})["sections"] = [{"name": "intro", "bar": 4}, {"name": "verse1", "bar": 8}]
    (root / "project.json").write_text(json.dumps(pj))
    rc, out = slop("-p", str(root), "analyze", "--steps", "sections")
    assert rc == 0, out
    names = [s["name"] for s in json.loads((root / "analysis" / "beats.json").read_text())["sections"]]
    assert names == ["intro0", "intro", "verse1"]


def test_guess_hints_never_print_a_runnable_example(proj):
    """The report / analyze / song sections tell how to confirm a guess without a ready-to-run --set with made-up
    values; a guessed no-vocal stretch of a tagged sheet gets the empty-tag-line fix."""
    from slop.audio import sections
    root, *_ = proj
    B = json.loads((root / "analysis" / "beats.json").read_text())
    secs = [dict(s) for s in B["sections"]]
    tagged = [s for s in secs if s.get("lines")]
    assert len(tagged) >= 2
    k = secs.index(tagged[0])
    gap = {"name": "break1", "t0": tagged[0]["t1"] - 2.0, "t1": tagged[0]["t1"], "source": "heuristic",
           "unconfirmed": True, "vocals": 0.0, "energy": 0.5}
    fake = {"sections_from": "lyrics tags + heuristic", "downbeats": B["downbeats"],
            "sections": secs[:k + 1] + [gap] + secs[k + 1:]}
    hints = sections.confirm_hints(fake, root)
    assert any("empty tag line" in h and "[Instrumental]" in h and f"lyric line {tagged[0]['lines'][1] + 1}" in h
               for h in hints), hints
    assert any("REPLACES ALL sections" in h and "NAME@START" in h for h in hints)
    assert not any("intro@0" in h or "verse1@bar8" in h for h in hints)
    assert all("--project" in h for h in hints)
    untagged = sections.confirm_hints({**fake, "sections_from": "heuristic"}, root)
    assert "section tags" in untagged[0] and "NAME@START" in untagged[-1]
    for f in ("report.py", "analyze.py"):
        src = (ROOT / "slop" / "audio" / f).read_text(encoding="utf-8")
        assert "SET_EXAMPLE" not in src and "verse1@bar8,chorus1@line9" not in src, f


def test_unused_trailing_tag_is_noted():
    from slop.audio import sections
    import numpy as np
    down = np.arange(0.0, 40.0, 2.0)
    beats = np.arange(0.0, 40.0, 0.5)
    blocks = [{"tag": "[Verse 1]", "kind": "verse", "lines": [0]}, {"tag": "[End]", "kind": "outro", "lines": []}]
    words = [{"line": 0, "t0": 4.0 + k * 0.4, "t1": 4.3 + k * 0.4} for k in range(3)] + \
            [{"line": 0, "t0": 38.0, "t1": 38.5}]                    # sung to the end: [End] has nothing to name
    ev = np.ones(40 * 24, np.float32)                              # vocals everywhere
    segs, notes = sections.tag_sections(blocks, words, beats, down, 40.0, ev, pdir=None)
    assert any("[End] after the last lyric line names nothing" in n and "REPLACES ALL" in n for n in notes), notes


def test_phase_notes_and_report_name_the_bars_command(proj):
    """No note or report line tells the operator to hand-edit audio.downbeat_phase: they name `song bars --phase`."""
    from slop.audio import beatmap
    root, *_ = proj
    kick = {"phase": 1, "blocks": [1, 2, 1, 3], "share": 0.4}
    H = {"phase": 3, "share": 0.9, "significant": True}
    _, _, _, notes = beatmap.decide_phase({}, kick, H, root)
    assert any("kick vote is split" in n and "song bars --phase N" in n and "--project" in n for n in notes), notes
    assert any(n.startswith("second opinion:") and "song bars --phase 3" in n for n in notes), notes
    assert not any("audio.downbeat_phase" in n for n in notes)
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "song bars --phase N" in rep and "set `audio.downbeat_phase`" not in rep
