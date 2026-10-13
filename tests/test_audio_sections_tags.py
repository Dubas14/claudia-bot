"""Sections from lyric tags: tag parsing, first-word snapping (incl. pickups), heuristic spans marked unconfirmed, the
override with @line, the report and the analyze step order (sections after align)."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "audio"))

import synth  # noqa: E402

from slop.audio import sections as sec  # noqa: E402
from slop.cli import main  # noqa: E402


def slop(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


# ---------------------------------------------------------------- pure functions
@pytest.mark.parametrize("tag,kind", [
    ("[Intro]", "intro"), ("[Verse 1: spoken]", "verse"), ("[Verse 2 - spoken, deadpan, bouncy]", "verse"),
    ("[Pre-Chorus - spoken, strings swell]", "prechorus"), ("[Chorus - sung, trance lift]", "chorus"),
    ("[Final Chorus - sung, key change up]", "chorus"), ("[Post-Chorus]", "postchorus"), ("[Hook]", "hook"),
    ("[Bridge - kick and strings only]", "bridge"), ("[Break - spoken over the kick]", "break"),
    ("[Breakdown]", "break"), ("[Drop - chanted, stacked voices]", "drop"), ("[Instrumental]", "inst"),
    ("[Guitar Solo]", "inst"), ("[Outro - music falls away]", "outro"), ("[End]", "outro"), ("[Rap Verse]", "verse"),
])
def test_tag_kind_recognises_section_tags(tag, kind):
    assert sec.tag_kind(tag) == kind


@pytest.mark.parametrize("note", [
    "[lyrics.txt: the words AS SUNG, one lyric line per line]",
    '[Lines starting with "[" are ignored: section tags like [Verse 1] or [Chorus], and these notes. Full rules]',
    "[Replace these notes with the song's lyrics, then check them: slop lyrics lint]",
    "[Whispered]", "[spoken]", "[female vocal, close mic]", "not a tag",
])
def test_notes_and_delivery_cues_are_not_tags(note):
    assert sec.tag_kind(note) is None


def test_parse_blocks_counts_lines_like_the_aligner(tmp_path):
    from slop.audio.align import read_sheet
    p = tmp_path / "lyrics.txt"
    p.write_text("[notes: words as sung]\nhello there\n\n[Verse 1 - spoken]\none two\n[Whispered]\nthree four\n"
                 "[Instrumental]\n[Chorus]\nla la\n[End]\n", encoding="utf-8")
    B = sec.parse_blocks(p)
    assert [(b["kind"], b["lines"]) for b in B] == [(None, [0]), ("verse", [1, 2]), ("inst", []), ("chorus", [3]),
                                                     ("outro", [])]
    assert len(read_sheet(p)) == 4                         # same line numbering as the aligner and words.json
    assert sec.has_tags(p)
    p.write_text("just\nlines\n", encoding="utf-8")
    assert not sec.has_tags(p)


def test_snap_start_at_or_before_with_pickup():
    beats = np.arange(0.0, 40.0, 0.5)
    down = beats[::4]                                       # bars every 2 s
    assert sec.PICKUP_BEATS == 0.1                          # the measured default: jitter only
    assert sec.snap_start(12.3, down, beats) == 12.0        # inside the bar: the bar line at or before
    assert sec.snap_start(12.0, down, beats) == 12.0        # on the bar line
    assert sec.snap_start(13.97, down, beats) == 14.0       # 30 ms (< 0.1 beat) before a bar line: alignment jitter
    assert sec.snap_start(13.8, down, beats) == 12.0        # 0.2 s before: a sung pickup stays in the bar before
    assert sec.snap_start(13.8, down, beats, pickup_beats=0.5) == 14.0     # opt-in: pickups start the next bar
    assert sec.snap_start(13.7, down, beats, pickup_beats=0.5) == 12.0     # 0.3 s before: still the bar before
    assert sec.snap_start(13.99, down, beats, pickup_beats=0.0) == 12.0    # off: strictly at or before
    assert sec.snap_start(0.3, down, beats) == 0.0


def _words(spans: list[tuple[int, float, float]]) -> list[dict]:
    return [{"i": k, "w": "la", "line": li, "t0": a, "t1": b} for k, (li, a, b) in enumerate(spans)]


def test_tag_sections_starts_gaps_and_names():
    beats = np.arange(0.0, 60.0, 0.5)
    down = beats[::4]
    dur = 60.0
    ev = np.zeros(int(dur * 24))
    spans = [(0, 4.1, 4.5), (0, 5.0, 6.8), (1, 12.4, 13.0), (1, 14.0, 15.5), (2, 23.97, 24.6), (2, 25.0, 27.0),
             (3, 40.2, 41.0), (3, 41.5, 43.0)]
    for _, a, b in spans:
        ev[int(a * 24):int(b * 24)] = 1.0
    blocks = [{"tag": "[Intro]", "kind": "intro", "lines": [0]}, {"tag": "[Verse 1]", "kind": "verse", "lines": [1]},
              {"tag": "[Chorus]", "kind": "chorus", "lines": [2]}, {"tag": "[Instrumental]", "kind": "inst", "lines": []},
              {"tag": "[Chorus]", "kind": "chorus", "lines": [3]}]
    segs, notes = sec.tag_sections(blocks, _words(spans), beats, down, dur, ev)
    got = [(s.get("kind"), s["t0"], s["t1"], s["source"]) for s in segs]
    assert got[0] == ("intro", 0.0, 12.0, "lyrics-tag")             # an intro tag starts the song
    assert got[1] == ("verse", 12.0, 16.0, "lyrics-tag")
    assert got[2][0] is None and got[2][1:] == (16.0, 24.0, "heuristic")   # 8 s without vocals after the verse
    assert got[3] == ("chorus", 24.0, 28.0, "lyrics-tag")            # 23.97: jitter before the bar line at 24
    assert got[4] == ("inst", 28.0, 40.0, "lyrics-tag")             # the empty [Instrumental] tag names the gap
    assert got[5] == ("chorus", 40.0, 44.0, "lyrics-tag")
    assert got[6][0] is None and got[6][1:] == (44.0, 60.0, "heuristic")   # the ring-out after the last word
    assert not notes


def test_untagged_head_and_inner_gap():
    beats = np.arange(0.0, 80.0, 0.5)
    down = beats[::4]
    ev = np.zeros(80 * 24)
    spans = [(0, 20.2, 22.0), (1, 30.1, 32.0), (2, 50.3, 52.0)]     # a 16 s hole inside the verse block (lines 1-2)
    for _, a, b in spans:
        ev[int(a * 24):int(b * 24)] = 1.0
    blocks = [{"tag": "[Verse]", "kind": "verse", "lines": [0, 1, 2]}]
    segs, _ = sec.tag_sections(blocks, _words(spans), beats, down, 80.0, ev)
    got = [(s.get("kind"), s["t0"], s["t1"], s["source"], s["lines"]) for s in segs]
    assert got[0] == (None, 0.0, 20.0, "heuristic", [])             # the span before the first tag
    assert got[1] == ("verse", 20.0, 34.0, "lyrics-tag", [0, 1])
    assert got[2][:4] == (None, 34.0, 50.0, "heuristic")             # >= 4 bars without vocals inside the block
    assert got[3] == ("verse", 50.0, 54.0, "lyrics-tag", [2])
    assert got[4][:4] == (None, 54.0, 80.0, "heuristic")


# ---------------------------------------------------------------- on a synthetic project (CLI)
@pytest.fixture()
def tproj(tmp_path):
    song = synth.make_song(dur=40.0, phase=1, drop_at=20.0)
    root = synth.write_project(tmp_path / "tags", song)
    beats = [round(float(b), 4) for b in song["beats"]]
    down = [round(float(b), 4) for b in song["downbeats"]]
    a = root / "analysis"
    a.mkdir(parents=True, exist_ok=True)
    (a / "beats.json").write_text(json.dumps({"duration": 40.0, "beats": beats, "downbeats": down, "sections": [],
                                              "downbeat_phase": 1, "notes": []}), encoding="utf-8")
    (root / "lyrics").mkdir(exist_ok=True)
    # one sheet line per synthetic vocal phrase (4-7, 12-15.5, 24-27, 32-35 s); words at the phrase syllables
    syl = song["syllables"]
    groups = [[s for s in syl if p0 <= s[0] < p1] for p0, p1 in ((4, 7), (12, 15.5), (24, 27), (32, 35))]
    words = []
    for li, g in enumerate(groups):
        for s0, s1 in g[:3]:
            words.append({"i": len(words), "w": "la", "line": li, "t0": s0, "t1": s1, "conf": 0.9, "src": "w2v"})
    from slop.audio.merge import finish
    (a / "words.json").write_text(json.dumps(finish(words, ["la la la"] * 4)), encoding="utf-8")
    return root, song, words


def _sheet(root: Path, text: str) -> None:
    (root / "lyrics" / "lyrics.txt").write_text(text, encoding="utf-8")


def test_sections_from_tags_on_a_project(tproj):
    root, song, words = tproj
    _sheet(root, "[Intro - spoken]\nla la la\n[Verse 1 - spoken]\nla la la\n[Chorus - sung]\nla la la\n"
                 "[Outro]\nla la la\n")
    rc, out = slop("-p", str(root), "analyze", "--steps", "sections")
    assert rc == 0, out
    B = json.loads((root / "analysis" / "beats.json").read_text())
    S = B["sections"]
    assert B["sections_from"].startswith("lyrics tags")
    down = np.array(B["downbeats"])
    by = {s["name"]: s for s in S}
    assert by["intro"]["t0"] == 0.0 and by["intro"]["source"] == "lyrics-tag" and by["intro"]["tag"] == "[Intro - spoken]"
    first = {li: min(w["t0"] for w in words if w["line"] == li) for li in range(4)}
    for name, li in (("verse1", 1), ("chorus1", 2), ("outro", 3)):
        s = by[name]
        assert s["source"] == "lyrics-tag" and "unconfirmed" not in s
        assert s["t0"] == pytest.approx(sec.snap_start(first[li], down, np.array(B["beats"])), abs=1e-3)
        assert s["t0"] <= first[li] + 0.3 and any(abs(s["t0"] - d) < 1e-3 for d in down)
        assert s["lines"] == [li, li]
    # the 16-24 s stretch without vocals after the verse is its own section, a guess
    gap = [s for s in S if s["source"] == "heuristic"]
    assert gap and all(s["unconfirmed"] for s in gap) and gap[0]["name"].startswith("break")
    for a_, b_ in zip(S, S[1:]):
        assert a_["t1"] == pytest.approx(b_["t0"])
    assert S[-1]["t1"] == pytest.approx(40.0)
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "lyrics tag [Chorus - sung]" in rep and "UNCONFIRMED guess" in rep and "(unconfirmed)" in rep
    assert "song sections --set" in rep
    assert any("?" in n for n in [out["text"]])                      # the step line marks the guess


def test_without_tags_every_name_is_unconfirmed(tproj):
    root, *_ = tproj
    _sheet(root, "la la la\nla la la\nla la la\nla la la\n")
    rc, out = slop("-p", str(root), "analyze", "--steps", "sections")
    assert rc == 0, out
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["sections_from"] == "heuristic"
    assert B["sections"] and all(s["source"] == "heuristic" and s["unconfirmed"] for s in B["sections"])
    assert any("are a guess" in n and "song sections --set" in n for n in out["next"])
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "UNCONFIRMED:" in rep


def test_tags_without_word_timing_fall_back_with_a_note(tproj):
    root, *_ = tproj
    (root / "analysis" / "words.json").unlink()
    _sheet(root, "[Verse]\nla la la\n[Chorus]\nla la la\n")
    rc, out = slop("-p", str(root), "analyze", "--steps", "sections")
    assert rc == 0, out
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["sections_from"] == "heuristic"
    assert any("no word timing yet" in n for n in B["notes"])


def test_override_with_line_and_bar(tproj):
    root, song, words = tproj
    _sheet(root, "la la la\nla la la\nla la la\nla la la\n")
    pj = json.loads((root / "project.json").read_text())
    pj["audio"] = {"sections": [{"name": "intro", "t0": 0}, {"name": "verse1", "bar": 5}, {"name": "chorus1", "line": 3}]}
    (root / "project.json").write_text(json.dumps(pj))
    rc, out = slop("-p", str(root), "analyze", "--steps", "sections")
    assert rc == 0, out
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["sections_from"] == "project.json"
    by = {s["name"]: s for s in B["sections"]}
    assert all(s["source"] == "set" and "unconfirmed" not in s for s in B["sections"])
    assert by["verse1"]["t0"] == pytest.approx(B["downbeats"][5], abs=1e-3)
    first3 = min(w["t0"] for w in words if w["line"] == 2)
    assert by["chorus1"]["t0"] <= first3 + 0.3 and any(abs(by["chorus1"]["t0"] - d) < 1e-3 for d in B["downbeats"])


def test_analyze_runs_sections_after_align_for_a_tagged_sheet(tproj, monkeypatch):
    """`analyze --steps align` re-places tagged sections in the same run (their starts come from the words)."""
    from slop.audio import analyze as an
    root, *_ = tproj
    _sheet(root, "[Verse]\nla la la\nla la la\n[Chorus]\nla la la\nla la la\n")
    assert an.ALL_STEPS.index("align") < an.ALL_STEPS.index("sections")

    def fake_align(pdir, paths, lines, *a, **k):
        return {"status": "done", "words": 12, "lines": len(lines), "sources": {}, "notes": []}
    monkeypatch.setattr(an, "run_align", fake_align)
    rc, out = slop("-p", str(root), "analyze", "--steps", "align")
    assert rc == 0, out
    assert "sections" in out["steps"] and out["steps"]["sections"]["status"] == "done"
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["sections_from"].startswith("lyrics tags")
