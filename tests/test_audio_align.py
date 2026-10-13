"""Alignment: sheet lint, CTC Viterbi on synthetic emissions, align-merge rules, manual fixes, CLI end to end
(the wav2vec2 model is replaced by synthetic emissions - no download, no torch inference)."""
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

from slop.audio import align as al  # noqa: E402
from slop.audio import merge as mg  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402

# the wav2vec2-960h character vocabulary layout
VOCAB = {"<pad>": 0, "<s>": 1, "</s>": 2, "<unk>": 3, "|": 4, "E": 5, "T": 6, "A": 7, "O": 8, "N": 9, "I": 10, "H": 11,
         "S": 12, "R": 13, "D": 14, "L": 15, "U": 16, "M": 17, "W": 18, "C": 19, "F": 20, "G": 21, "Y": 22, "P": 23,
         "B": 24, "V": 25, "K": 26, "'": 27, "X": 28, "J": 29, "Q": 30, "Z": 31}


def fake_emissions(schedule: list[tuple[str, float, float]], dur: float, hi: float = .97) -> np.ndarray:
    """log-posteriors at 50 fps: blank everywhere, each word's letters spread over [t0, t1), '|' right after it."""
    T = int(dur * 50)
    E = np.full((T, len(VOCAB)), np.log(.001), np.float32)
    E[:, 0] = np.log(hi)
    for w, t0, t1 in schedule:
        chars = [c for c in w.upper() if c in VOCAB]
        f0, f1 = min(T, int(round(t0 * 50))), min(T, int(round(t1 * 50)))
        span = max(1, (f1 - f0) // len(chars))
        for k, c in enumerate(chars):
            for f in range(f0 + k * span, min(f1, f0 + (k + 1) * span)):
                E[f, 0] = np.log(.001)
                E[f, VOCAB[c]] = np.log(hi)
        if f1 < T:
            E[f1, 0] = np.log(.001)
            E[f1, VOCAB["|"]] = np.log(hi)
    return E


SHEET = ["Hello world, this is", "a test of the aligner"]
SCHED = [("Hello", 1.0, 1.4), ("world", 1.5, 1.9), ("this", 2.4, 2.6), ("is", 2.7, 2.8),
         ("a", 4.0, 4.06), ("test", 4.2, 4.5), ("of", 4.6, 4.7), ("the", 4.8, 4.9), ("aligner", 5.0, 5.6)]


def test_viterbi_finds_word_starts():
    E = fake_emissions(SCHED, 7.0)
    words = al.viterbi_align(E, VOCAB, SHEET)
    assert [w["w"] for w in words] == [s[0] for s in SCHED]
    for w, (_, t0, t1) in zip(words, SCHED):
        assert w["t0"] == pytest.approx(t0, abs=0.021)
        assert w["t1"] == pytest.approx(t1, abs=0.06)
        assert w["score"] > 0.9
    assert [w["line"] for w in words] == [0, 0, 0, 0, 1, 1, 1, 1, 1]


def test_greedy_transcript():
    E = fake_emissions([("Hi", 1.0, 1.2), ("world", 1.5, 1.9)], 3.0)
    tw = al.greedy_transcript(E, VOCAB)
    assert [w["w"] for w in tw] == ["HI", "WORLD"]          # (a doubled letter needs a blank between: CTC)
    assert tw[0]["t0"] == pytest.approx(1.0, abs=0.02)


def test_sheet_too_long_is_an_error():
    E = fake_emissions(SCHED, 0.3)
    with pytest.raises(SlopError, match="more characters"):
        al.viterbi_align(E, VOCAB, SHEET * 3)


def test_sheet_lint_digits_symbols_letterless():
    lines = ["Look 04. Shoes off", "+25% = -17%", "Feel the AGI tonight", "plain words here"]
    probs = al.lint_sheet(lines)
    kinds = {(p["line"], p["level"]) for p in probs}
    assert (0, "error") in kinds and (1, "error") in kinds and (2, "warn") in kinds
    assert not any(p["line"] == 3 for p in probs)
    p0 = next(p for p in probs if p["line"] == 0)
    assert "four" in p0["fix"]
    with pytest.raises(SlopError, match="spelled as sung"):
        al.check_sheet(lines)
    al.check_sheet(lines, allow_digits=True)


def test_split_words_matches_aligner_counting():
    assert al.split_words("Plus twenty-five is minus seventeen.") == ["Plus", "twenty", "five", "is", "minus", "seventeen"]
    assert al.split_words("Jensen’s café (so) 01") == ["Jensen's", "cafe", "so"]


# ---------------------------------------------------------------- merge rules
def _w2v(items):
    return [{"w": w, "line": li, "t0": t0, "t1": t1, "score": sc} for w, li, t0, t1, sc in items]


def test_whisper_tokens_split_and_merge():
    sheet = ["a", "g", "i", "era", "ten", "supernova", "three", "am"]
    wh = [{"w": "AGI", "t0": 1.0, "t1": 1.6}, {"w": "era.", "t0": 1.7, "t1": 2.0}, {"w": "10", "t0": 2.1, "t1": 2.4},
          {"w": "super", "t0": 3.0, "t1": 3.3}, {"w": "nova", "t0": 3.3, "t1": 4.0}, {"w": "3am", "t0": 5.0, "t1": 5.6}]
    toks = mg.whisper_tokens(wh, sheet)
    assert [t["n"] for t in toks] == ["a", "g", "i", "era", "ten", "supernova", "three", "am"]
    assert toks[0]["t0"] == 1.0 and toks[1]["t0"] == pytest.approx(1.2)
    assert toks[5]["t0"] == 3.0 and toks[5]["t1"] == 4.0
    assert [t["n"] for t in mg.whisper_tokens([{"w": "Mario", "t0": 0, "t1": 1}], ["dario"], {"mario": ["dario"]})] == ["dario"]


def test_merge_rules():
    lines = ["one two three four five"]
    w2v = _w2v([("one", 0, 1.0, 1.2, .95), ("two", 0, 1.3, 1.5, .2), ("three", 0, 5.0, 5.1, .1),
                ("four", 0, 2.6, 2.8, .3), ("five", 0, 3.0, 3.3, .9)])
    R = np.zeros(1000, np.float32)
    R[180:240] = 1.0                       # "three" really starts at 1.8 s (whisper says 1.6)
    wh = [{"w": "one", "t0": 0.9, "t1": 1.2}, {"w": "two", "t0": 1.25, "t1": 1.5},
          {"w": "three", "t0": 1.6, "t1": 2.3}, {"w": "five", "t0": 3.0, "t1": 3.3}]
    W = mg.merge(w2v, lines, wh, R)
    ws = W["words"]
    assert ws[0]["src"] == "w2v" and ws[0]["t0"] == 1.0                      # confident w2v kept
    assert ws[1]["src"] == "whisper" and ws[1]["t0"] == 1.3                  # w2v start inside the Whisper word wins
    assert ws[2]["src"] == "whisper" and ws[2]["t0"] == pytest.approx(1.8, abs=0.011)   # energy onset
    assert ws[3]["src"] == "interp" and ws[2]["t1"] <= ws[3]["t0"] <= ws[4]["t0"]        # unmatched -> interpolated
    assert ws[4]["src"] == "w2v"
    assert W["stats"] == {"w2v": 2, "whisper": 2, "interp": 1}
    assert W["lines"][0]["conf"] == "check"


def test_merge_without_whisper_keeps_w2v_times_and_finds_gaps():
    lines = ["a b c", "d"]
    w2v = _w2v([("a", 0, 1.0, 1.1, .9), ("b", 0, 1.2, 1.3, .2), ("c", 0, 3.0, 3.2, .8), ("d", 1, 6.0, 6.3, .9)])
    W = mg.merge(w2v, lines)
    assert [w["src"] for w in W["words"]] == ["w2v"] * 4
    assert W["words"][1]["t0"] == 1.2 and W["words"][1]["conf"] == 0.2
    assert W["lines"][0]["conf"] == "w2v-low" and W["lines"][1]["conf"] == "w2v"
    g = {(x["after_word"], x["in_line"]) for x in W["gaps"]}
    assert (1, True) in g and (2, False) in g


def test_manual_fixes_survive():
    lines = ["a b c"]
    w2v = _w2v([("a", 0, 1.0, 1.1, .9), ("b", 0, 1.2, 1.3, .2), ("c", 0, 3.0, 3.2, .8)])
    prev = mg.merge(w2v, lines)
    prev["words"][1].update(t0=2.0, t1=2.2, src="manual", conf=1.0)
    W = mg.merge(w2v, lines, previous=prev)
    assert W["words"][1]["src"] == "manual" and W["words"][1]["t0"] == 2.0


def test_word_without_frames_is_placed_next_to_neighbour():
    w2v = _w2v([("a", 0, 1.0, 1.1, .9), ("b", 0, None, None, 0.0)])
    W = mg.merge(w2v, ["a b"])
    assert W["words"][1]["src"] == "interp" and W["words"][1]["t0"] == pytest.approx(1.1)


# ---------------------------------------------------------------- CLI end to end with fake emissions
def slop(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


@pytest.fixture()
def aproj(tmp_path, monkeypatch):
    song = synth.make_song(dur=8.0, drop_at=4.0, vocal_phrases=[(1.0, 3.0), (4.0, 5.8)])
    root = synth.write_project(tmp_path / "al", song)
    (root / "lyrics").mkdir()
    (root / "lyrics" / "lyrics.txt").write_text("[Verse 1: spoken]\n" + "\n".join(SHEET) + "\n", encoding="utf-8")
    calls = []

    def fake(vocals):
        calls.append(str(vocals))
        return fake_emissions(SCHED, 8.0), dict(VOCAB)

    monkeypatch.setattr(al, "compute_emissions", fake)
    return root, calls


def test_cli_align_display_fix_cycle(aproj):
    root, calls = aproj
    rc, out = slop("-p", str(root), "analyze", "--steps", "align")
    assert rc == 0, out
    W = json.loads((root / "analysis" / "words.json").read_text())
    assert [w["w"] for w in W["words"]] == [s[0] for s in SCHED]
    assert W["words"][5]["t0"] == pytest.approx(4.2, abs=0.021) and W["words"][5]["src"] == "w2v"
    assert set(W) >= {"words", "lines", "gaps"} and W["lines"][1]["text"] == SHEET[1]
    assert (root / "analysis" / "transcript.json").exists() and (root / "analysis" / "report.md").exists()
    # in-line gap > 1 s ("is" 2.8 -> next line is another line; none in line 0 > 1 s) and the report mentions EAR CHECK
    assert "EAR CHECK" in (root / "analysis" / "report.md").read_text(encoding="utf-8")
    # idempotent: second run is up to date and does not recompute emissions
    rc, out = slop("-p", str(root), "analyze", "--steps", "align")
    assert out["steps"]["align"]["status"] == "up-to-date" and len(calls) == 1
    # manual fix, then a forced re-analysis keeps it (emissions come from the cache)
    rc, out = slop("-p", str(root), "lyrics", "fix", "--word", "1", "--t0", "1.55", "--t1", "1.95")
    assert rc == 0 and out["changed"][0]["t0"] == 1.55
    rc, out = slop("-p", str(root), "lyrics", "fix", "--line", "2", "--shift", "0.5")
    assert rc == 0 and len(out["changed"]) == 5
    rc, out = slop("-p", str(root), "analyze", "--steps", "align", "--force")
    assert rc == 0
    W = json.loads((root / "analysis" / "words.json").read_text())
    assert W["words"][1]["src"] == "manual" and W["words"][1]["t0"] == 1.55
    assert W["words"][4]["src"] == "manual" and W["words"][4]["t0"] == pytest.approx(4.5, abs=0.03)
    # display tokens: start from the sheet, then build the engine LYR list
    rc, out = slop("-p", str(root), "lyrics", "display", "--init")
    assert rc == 0 and out["created"] and out["lyr_lines"] == 2
    (root / "lyrics" / "display.txt").write_text("*Hello|1 world,|1 this|0 is|2\nA|1 test|2 of the ALIGNER\n", encoding="utf-8")
    rc, out = slop("-p", str(root), "lyrics", "display")
    assert rc == 1 and "consumes" in out["error"]
    (root / "lyrics" / "display.txt").write_text("*Hello|1 world,|1 this|0 is|2\n[chorus]\nA|1 test|1 of|1 the|1 ALIGNER|1\n",
                                                 encoding="utf-8")
    rc, out = slop("-p", str(root), "lyrics", "display")
    assert rc == 0, out
    L = json.loads((root / "analysis" / "lyrics-display.json").read_text())
    t0 = L[0]["tokens"]
    assert t0[0]["st"] == "accent" and t0[0]["txt"] == "Hello" and t0[2]["t0"] == t0[3]["t0"]   # |0 rides on the next


def test_cli_align_refuses_digits(aproj):
    root, _ = aproj
    (root / "lyrics" / "lyrics.txt").write_text("Plus 25 is minus 17\n", encoding="utf-8")
    rc, out = slop("-p", str(root), "analyze", "--steps", "align")
    assert rc == 1 and "twenty five" in out["error"]


def test_cli_whisper_fallback_needs_key(aproj, monkeypatch):
    root, _ = aproj
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rc, out = slop("-p", str(root), "analyze", "--steps", "align", "--whisper-fallback")
    assert rc == 1 and "OPENROUTER_API_KEY" in out["error"]


def test_ear_check_kinds_and_order():
    from slop.audio.report import ear_check
    lines = ["one two three", "four five", "+25%"]
    words = [{"w": "one", "line": 0, "t0": 1.0, "t1": 1.2, "conf": .9, "src": "w2v"},
             {"w": "two", "line": 0, "t0": 2.5, "t1": 2.7, "conf": .05, "src": "w2v"},       # 1.3 s in-line gap, very low
             {"w": "three", "line": 0, "t0": 2.8, "t1": 4.4, "conf": .3, "src": "w2v"},      # 1.6 s long, low
             {"w": "four", "line": 1, "t0": 2.6, "t1": 2.9, "conf": .9, "src": "w2v"},       # before "three"
             {"w": "five", "line": 1, "t0": None, "t1": None, "conf": 0, "src": "interp"}]
    W = mg.finish(words, lines)
    items = ear_check(W, lines)
    kinds = [i["kind"] for i in items]
    assert kinds[0] == "letters" and "missing" in kinds and "order" in kinds and "gap" in kinds
    assert "verylow" in kinds and "length" in kinds and "lowconf" in kinds
    assert kinds.index("gap") < kinds.index("verylow") < kinds.index("lowconf")
    gap = next(i for i in items if i["kind"] == "gap")
    assert gap["listen"].startswith("slop audio window") and "--word 0" in gap["fix"]


def test_ear_check_groups_rank_and_project_flag(tmp_path):
    from slop.audio.report import LISTEN_TOP, ear_check, group_items
    lines = [f"line {k} words here" for k in range(30)]
    words = []
    for li in range(30):
        for j, w in enumerate(("line", "words", "here")):
            words.append({"w": w, "line": li, "t0": li * 4.0 + j * 0.3, "t1": li * 4.0 + j * 0.3 + 0.2,
                          "conf": 0.9, "src": "w2v"})
    for li in range(25):                                  # 25 lines with a very-low word, confidence falling with li
        words[li * 3 + 1]["conf"] = round(0.09 - li * 0.003, 3)
    words[29 * 3 + 2]["t0"], words[29 * 3 + 2]["t1"] = 200.0, 200.2         # a word far after its line: in-line gap
    words[28 * 3 + 1]["conf"] = 0.3                                          # lowconf only: "if time allows"
    W = mg.finish(words, lines)
    root = tmp_path / "proj"
    root.mkdir()
    items = ear_check(W, lines, pdir=root)
    assert all("--project" in i["listen"] and i["listen"].endswith("--mode mix --listen") for i in items if "listen" in i)
    groups = group_items(items, W, root)
    assert len({g["line"] for g in groups}) == len(groups)                    # one entry per line
    urgent = [g for g in groups if g["urgent"]]
    assert len(urgent) == 26 and [g["line"] for g in groups if not g["urgent"]] == [28]
    assert urgent[0]["line"] == 24                     # the lowest confidence first (verylow lines rank by confidence)
    assert all("--project" in g["fix"] for g in groups)
    assert LISTEN_TOP == 20


def test_report_caps_the_list_and_listen_goes_to_analysis(aproj):
    root, _ = aproj
    rc, out = slop("-p", str(root), "analyze", "--steps", "align")
    assert rc == 0, out
    W = json.loads((root / "analysis" / "words.json").read_text())
    for k, w in enumerate(W["words"]):
        w["conf"] = 0.01 if k % 2 else w["conf"]
    W2 = mg.finish(W["words"], [L["text"] for L in W["lines"]])
    W.update(W2)
    (root / "analysis" / "words.json").write_text(json.dumps(W))
    rc, out = slop("-p", str(root), "lyrics", "fix", "--word", "0", "--t0", "1.0", "--t1", "1.4")
    assert rc == 0, out
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "### Listen first" in rep and f"--project {root}" in rep.replace("'", "")
    listen = next(ln for ln in rep.splitlines() if "listen: `" in ln).split("`")[1]
    import shlex
    argv = shlex.split(listen)[1:]
    rc, out = slop(*argv)
    assert rc == 0, out
    assert out["file"].startswith("analysis/listen/") and (root / out["file"]).exists()
    assert not list((root / "audio").rglob("chk-*"))                        # never in the clip-window folder


def test_lyrics_fix_refuses_impossible_times(aproj):
    root, _ = aproj
    rc, out = slop("-p", str(root), "analyze", "--steps", "align")
    assert rc == 0, out
    rc, out = slop("-p", str(root), "lyrics", "fix", "--word", "2", "--shift", "-100")
    assert rc == 1 and "0 <= t0 < t1 <=" in out["error"] and "8.00" in out["error"]
    rc, out = slop("-p", str(root), "lyrics", "fix", "--word", "2", "--t0", "3.0", "--t1", "2.0")
    assert rc == 1 and "0 <= t0 < t1" in out["error"]
    rc, out = slop("-p", str(root), "lyrics", "fix", "--word", "2", "--t0", "7.9", "--t1", "9.5")
    assert rc == 1 and "8.00" in out["error"]
    rc, out = slop("-p", str(root), "lyrics", "fix", "--line", "2", "--shift", "3.0")       # "aligner" would end at 8.6
    assert rc == 1 and "inside the song" in out["error"]
    W = json.loads((root / "analysis" / "words.json").read_text())
    assert all(w["src"] == "w2v" for w in W["words"])                       # nothing was half-applied
    rc, out = slop("-p", str(root), "lyrics", "fix", "--word", "2", "--t0", "2.40", "--t1", "2.62")
    assert rc == 0 and out["changed"][0]["t0"] == 2.4


def test_lint_counts_alignment_sheet_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.setenv("SLOP_OFFLINE", "1")
    f = tmp_path / "sung.txt"
    f.write_text("[Verse 1: spoken]\nLook 04 we hit +25%\nplain words here tonight\n", encoding="utf-8")
    rc, out = slop("lyrics", "lint", str(f))
    assert rc == 0, out
    assert out["summary"]["sheet_errors"] >= 2 and out["summary"]["errors"] >= out["summary"]["sheet_errors"]
    assert "alignment sheet: must fix before slop analyze" in out["text"] and "twenty five percent" in out["text"]
