"""`slop lyrics check`: heard-vs-sheet diff per line (pure), and the command with the Whisper call mocked (no paid
calls): ledger, cache reuse, --yes over the confirm threshold, --write / --apply."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "audio"))

import synth  # noqa: E402

from slop.audio import check as ck  # noqa: E402
from slop.audio import whisper as wh  # noqa: E402
from slop.cli import main  # noqa: E402


def slop(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


def heard(text: str, t0: float, step: float = 0.4) -> list[dict]:
    return [{"w": w, "t0": round(t0 + k * step, 3), "t1": round(t0 + k * step + 0.3, 3)} for k, w in enumerate(text.split())]


def by_line(res: dict) -> dict[int, dict]:
    return {r["line"]: r for r in res["lines"]}


# ---------------------------------------------------------------- the diff
def test_matching_take_is_all_ok_with_numbers_and_letters():
    lines = ["Feel the A G I, feel it coming fast", "P doom's at ten"]
    res = ck.diff_sheet(lines, heard("Feel the AGI, feel it coming fast.", 1.0) + heard("P doom's at 10", 6.0))
    assert [r["status"] for r in res["lines"]] == ["ok", "ok"] and not res["extra"]


def test_changed_words_get_a_proposed_line_with_the_sheet_punctuation():
    lines = ["Why would I deceive you?", "You don't have to die.", "TIE ME TO THE MAST!"]
    h = heard("Why would I deceive you?", 1.0) + heard("You will never die.", 4.0) + heard("Tie me to the mast!", 7.0)
    res = ck.diff_sheet(lines, h)
    L = by_line(res)
    assert L[1]["status"] == "ok" and L[3]["status"] == "ok"
    assert L[2]["status"] == "changed" and L[2]["changed"] == [{"sheet": "don't have to", "heard": "will never"}]
    assert L[2]["proposed"] == "You will never die."


def test_spelling_variants_are_kept():
    res = ck.diff_sheet(["Dahrio said to slow it down."], heard("Dario said to slow it down.", 1.0))
    r = res["lines"][0]
    assert r["status"] == "spelling" and "proposed" not in r and r["spelling"][0]["heard"] == "Dario"


def test_extra_words_inside_a_line_and_missing_words():
    lines = ["Lock in, baby, foot down on the gas", "Tie me to the mast"]
    res = ck.diff_sheet(lines, heard("lock in yeah baby foot down on the gas", 1.0) + heard("tie me to mast", 6.0))
    L = by_line(res)
    assert L[1]["status"] == "extra" and L[1]["extra"] == ["yeah"]
    assert L[1]["proposed"] == "Lock in, yeah baby, foot down on the gas" or L[1]["proposed"] == "Lock in yeah, baby, foot down on the gas"
    assert L[2]["status"] == "missing" and L[2]["missing"] == ["the"] and L[2]["if_dropped"] == "Tie me to mast"
    assert "proposed" not in L[2]                      # a word not heard is not proposed for deletion


def test_not_heard_lines_and_extra_vocals_between_lines():
    lines = ["one two three four", "TIE ME TO THE MAST!", "five six seven eight"]
    h = heard("one two three four", 1.0) + heard("five six seven eight", 12.0) + heard("oh yeah oh yeah", 20.0)
    res = ck.diff_sheet(lines, h)
    L = by_line(res)
    assert L[2]["status"] == "not-heard" and "proposed" not in L[2]
    assert L[1]["status"] == "ok" and L[3]["status"] == "ok"
    assert res["extra"] and res["extra"][0]["heard"] == "oh yeah oh yeah" and res["extra"][0]["after_line"] == 3
    # an ad-lib between two lines, far from both
    h = heard("one two three four", 1.0) + heard("oh yeah", 6.0) + heard("TIE ME TO THE MAST", 10.0) +         heard("five six seven eight", 14.0)
    res = ck.diff_sheet(lines, h)
    assert [r["status"] for r in res["lines"]] == ["ok", "ok", "ok"]
    assert res["extra"] == [{"t0": 6.0, "t1": 6.7, "heard": "oh yeah", "after_line": 1}]
    # a different line sung where the sheet has one: "changed", with the heard line proposed
    h = heard("one two three four", 1.0) + heard("oh yeah oh yeah", 5.0) + heard("five six seven eight", 12.0)
    L = by_line(ck.diff_sheet(lines, h))
    assert L[2]["status"] == "changed" and L[2]["proposed"] == "OH YEAH OH YEAH!"     # a shout stays in capitals
    assert L[2]["confidence"] == "unsure"


def test_confidence_tiers_on_misheard_lines():
    """Calibrated on a real take: shouts, repeats heard as written elsewhere, letters, small words and echoes are
    UNSURE; a real word change on a one-off line is LIKELY."""
    lines = ["Tie me to the mast!", "TIE ME TO THE MAST!", "You don't have to die.", "Your P doom went up.",
             "Mixing hormone with a guy.", "Everybody's asking what he heard.", "Tie me to the mast!"]
    h = (heard("tie me to the mast", 1.0) + heard("talk me to the mast", 4.0) + heard("you will never die", 7.0)
         + heard("your peak doom went up", 10.0) + heard("mixing hormone with the guy", 13.0)
         + heard("everybody's asking what he heard heard", 16.0) + heard("sonic to the mast", 20.0))
    L = by_line(ck.diff_sheet(lines, h))
    assert L[1]["status"] == "ok"
    assert L[2]["confidence"] == "unsure" and any(w.startswith("shout") for w in L[2]["why"])
    assert L[3]["confidence"] == "likely" and L[3]["proposed"] == "You will never die."
    assert L[4]["confidence"] == "unsure" and any(w.startswith("letter") for w in L[4]["why"])
    assert L[5]["confidence"] == "unsure" and any(w.startswith("small-words") for w in L[5]["why"])
    assert L[6]["status"] == "extra" and L[6]["confidence"] == "unsure" and any(w.startswith("echo") for w in L[6]["why"])
    assert L[7]["confidence"] == "unsure" and any("heard as written at line 1" in w for w in L[7]["why"])
    # a letter sung by name is a spelling, not a change
    r = ck.diff_sheet(["Your P doom went down."], heard("your pee doom went down", 1.0))["lines"][0]
    assert r["status"] == "spelling" and "proposed" not in r


def test_rebuild_line_keeps_punctuation_and_case():
    assert ck.rebuild_line("You don't have to die.", {1: ["will", "never"], 2: [], 3: []}, {}) == "You will never die."
    assert ck.rebuild_line("Tie me, to the mast!", {}, {1: ["now"]}) == "Tie me now, to the mast!"
    assert ck.rebuild_line("go", {}, {-1: ["oh"]}) == "oh go"
    assert ck.rebuild_line("They replied: ugh, it sucks.", {2: []}, {}) == "They replied: it sucks."
    assert ck.rebuild_line("IT WAS THAT GOOD!", {3: []}, {}) == "IT WAS THAT!"


def test_rebuild_line_keeps_the_sheets_own_characters():
    """Only the replaced words change: curly apostrophes, accents and ligatures elsewhere stay as written."""
    assert ck.rebuild_line("Don\u2019t stop, Beyonc\u00e9!", {1: ["go"]}, {}) == "Don\u2019t go, Beyonc\u00e9!"
    assert ck.rebuild_line("Cafe\u0301 au lait, ma\u00f1ana", {2: ["noir"]}, {}) == "Cafe\u0301 au noir, ma\u00f1ana"
    assert ck.rebuild_line("the \ufb01ne print, d\u00e9j\u00e0 vu", {}, {0: ["very"]}) == \
        "the very \ufb01ne print, d\u00e9j\u00e0 vu"
    assert ck.rebuild_line("Na\u00efve \u2018kid\u2019 here", {0: ["Brave"]}, {}) == "Brave \u2018kid\u2019 here"


def test_aligned_and_half_heard_mark_a_garbled_line_unsure():
    """Calibrated on the real take's one remaining LIKELY false positive: the sheet words of the line were placed by
    wav2vec2 with good confidence, and the heard words are not in the song but sound partly like the sheet's."""
    lines = ["Peptide rave in San Francisco.", "You don't have to die."]
    h = heard("Hatsai Raven San Francisco.", 1.0) + heard("You will never die.", 6.0)
    L = by_line(ck.diff_sheet(lines, h))
    assert L[1]["confidence"] == "unsure" and any(w.startswith("half-heard") for w in L[1]["why"])
    assert L[2]["confidence"] == "likely"                       # a real change: unrelated words, not half-heard
    conf = [0.04, 0.81, 0.59, 1.0, 1.0] + [0.9, 0.02, 0.03, 0.01, 0.95]
    L = by_line(ck.diff_sheet(lines, h, aligned=conf, conf_min=0.5))
    assert any(w.startswith("aligned") and "rave 0.81" in w for w in L[1]["why"])
    assert L[2]["confidence"] == "likely"                       # its replaced words aligned badly: still likely
    conf2 = [0.04, 0.81, 0.59, 1.0, 1.0] + [0.9, 0.8, 0.9, 0.7, 0.95]
    L = by_line(ck.diff_sheet(lines, h, aligned=conf2, conf_min=0.5))
    assert L[2]["confidence"] == "unsure" and any(w.startswith("aligned") for w in L[2]["why"])
    L = by_line(ck.diff_sheet(lines, h, aligned=[0.9, 0.9], conf_min=0.5))      # wrong length: ignored
    assert L[2]["confidence"] == "likely"


# ---------------------------------------------------------------- the command (Whisper mocked)
@pytest.fixture()
def cproj(tmp_path, monkeypatch):
    song = synth.make_song(dur=12.0, drop_at=6.0, vocal_phrases=[(1.0, 4.0), (7.0, 10.0)])
    root = synth.write_project(tmp_path / "chk", song)
    pj = json.loads((root / "project.json").read_text())
    pj["budget"] = {"openrouter_usd": 5, "confirm_over_usd": 2}
    (root / "project.json").write_text(json.dumps(pj))
    (root / "lyrics").mkdir()
    (root / "lyrics" / "lyrics.txt").write_text("[Verse]\nWhy would I deceive you?\n[Chorus]\nYou don't have to die.\n",
                                                encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.setattr(wh, "plan_windows", lambda R, **k: [(0.0, 11.0)])
    return root


def _take(payload, key):
    assert payload["timestamp_granularities"] == ["word"] and payload["response_format"] == "verbose_json"
    words = heard("Why would I deceive you?", 1.0) + heard("You will never die.", 7.0)
    return {"text": "...", "usage": {"cost": 0.0000825}, "_request_id": "req-1",
            "words": [{"word": w["w"], "start": w["t0"], "end": w["t1"]} for w in words]}


def test_check_pays_once_ledgers_and_proposes(cproj, monkeypatch):
    calls = []
    monkeypatch.setattr(wh, "_post", lambda p, k: calls.append(1) or _take(p, k))
    rc, out = slop("-p", str(cproj), "lyrics", "check", "--write")
    assert rc == 0, out
    assert len(calls) == 1 and out["paid"] and out["cost_usd"] == pytest.approx(0.0000825)
    rows = [json.loads(x) for x in (cproj / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["provider"] == "openrouter" and rows[0]["kind"] == "stt" and rows[0]["status"] == "ok"
    L = {r["line"]: r for r in out["lines"]}
    assert L[1]["status"] == "ok" and L[2]["status"] == "changed" and L[2]["proposed"] == "You will never die."
    assert (cproj / "analysis" / "lyrics-check.json").exists()
    prop = (cproj / "lyrics" / "lyrics.proposed.txt").read_text(encoding="utf-8")
    assert prop == "[Verse]\nWhy would I deceive you?\n[Chorus]\nYou will never die.\n"
    assert "don't have to" in (cproj / "lyrics" / "lyrics.txt").read_text(encoding="utf-8")   # sheet untouched
    assert "lyrics check --apply" in out["text"] and "analyze --steps align" in out["text"]
    # --apply after the owner agreed: free (cached transcription), sheet changed, backup kept
    monkeypatch.setattr(wh, "_post", lambda p, k: pytest.fail("a cached transcription must not be paid again"))
    monkeypatch.delenv("OPENROUTER_API_KEY")
    rc, out = slop("-p", str(cproj), "lyrics", "check", "--apply")
    assert rc == 0, out
    assert not out["paid"] and out["cost_usd"] == 0
    assert (cproj / "lyrics" / "lyrics.txt").read_text(encoding="utf-8").endswith("You will never die.\n")
    baks = sorted((cproj / "lyrics").glob("lyrics.txt.*.bak"))
    assert len(baks) == 1 and "don't have to" in baks[0].read_text(encoding="utf-8")
    assert out["backup"] == f"lyrics/{baks[0].name}" and baks[0].name in out["text"]
    assert len((cproj / "ledger.jsonl").read_text().splitlines()) == 1
    assert out["applied"] == [2]
    rc, out = slop("-p", str(cproj), "lyrics", "check")                 # the new sheet matches the take
    assert rc == 0 and out["summary"] == {"ok": 2} and "matches the take" in out["text"]


def test_apply_lines_takes_exactly_the_confirmed_lines(cproj, monkeypatch):
    sheet = ["[Chorus]", "TIE ME TO THE MAST!", "You don't have to die."]
    (cproj / "lyrics" / "lyrics.txt").write_text("\n".join(sheet) + "\n", encoding="utf-8")

    def take(payload, key):
        words = heard("talk me to the mast", 1.0) + heard("you will never die", 7.0)
        return {"text": "...", "usage": {"cost": 0.00008},
                "words": [{"word": w["w"], "start": w["t0"], "end": w["t1"]} for w in words]}
    monkeypatch.setattr(wh, "_post", take)
    rc, out = slop("-p", str(cproj), "lyrics", "check", "--apply")       # the likely one only
    assert rc == 0, out
    assert out["proposals"] == {"likely": [2], "unsure": [1]} and out["applied"] == [2]
    got = (cproj / "lyrics" / "lyrics.txt").read_text(encoding="utf-8").splitlines()
    assert got == ["[Chorus]", "TIE ME TO THE MAST!", "You will never die."]
    assert "--apply-lines" in out["text"]
    rc, out = slop("-p", str(cproj), "lyrics", "check", "--apply-lines", "1")   # the owner heard "Talk me": apply it
    assert rc == 0 and out["applied"] == [1]
    assert (cproj / "lyrics" / "lyrics.txt").read_text(encoding="utf-8").splitlines()[1] == "TALK ME TO THE MAST!"
    baks = sorted((cproj / "lyrics").glob("lyrics.txt.*.bak"))   # each apply keeps its own backup: the original stays
    assert len(baks) == 2
    texts = [b.read_text(encoding="utf-8") for b in baks]
    assert any("You don't have to die." in t and "TIE ME" in t for t in texts)
    assert any("You will never die." in t and "TIE ME" in t for t in texts)
    rc, out = slop("-p", str(cproj), "lyrics", "check", "--apply-lines", "2")
    assert rc == 1 and "no proposal for line(s) 2" in out["error"]


def test_check_reuses_the_analyze_whisper_cache(cproj, monkeypatch):
    calls = []
    monkeypatch.setattr(wh, "_post", lambda p, k: calls.append(1) or _take(p, k))
    wh.transcribe(cproj, [(0.0, 11.0)])                                 # as `analyze --whisper-fallback` would
    assert len(calls) == 1
    rc, out = slop("-p", str(cproj), "lyrics", "check")
    assert rc == 0 and len(calls) == 1 and not out["paid"]


def test_check_errors_say_what_to_do(cproj, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    rc, out = slop("-p", str(cproj), "lyrics", "check")
    assert rc == 1 and "OPENROUTER_API_KEY" in out["error"] and "secure secret card" in out["error"]
    (cproj / "audio" / "stems" / "vocals.wav").unlink()
    rc, out = slop("-p", str(cproj), "lyrics", "check")
    assert rc == 1 and "analyze --steps stems" in out["error"]
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as ex:            # argparse: mutually exclusive options
        main(["--json", "-p", str(cproj), "lyrics", "check", "--write", "--apply"])
    assert ex.value.code == 2 and "not allowed with" in json.loads(buf.getvalue().strip().splitlines()[-1])["error"]
    (cproj / "lyrics" / "lyrics.txt").write_text("[notes only]\n", encoding="utf-8")
    rc, out = slop("-p", str(cproj), "lyrics", "check")
    assert rc == 1 and "no lyric lines" in out["error"]


def test_check_over_the_confirm_threshold_needs_yes(cproj, monkeypatch):
    pj = json.loads((cproj / "project.json").read_text())
    pj["budget"]["confirm_over_usd"] = 0.00001                          # the owner wants to confirm every cent
    (cproj / "project.json").write_text(json.dumps(pj))
    calls = []
    monkeypatch.setattr(wh, "_post", lambda p, k: calls.append(1) or _take(p, k))
    rc, out = slop("-p", str(cproj), "lyrics", "check")
    assert rc == 1 and "--yes" in out["error"] and not calls
    rc, out = slop("-p", str(cproj), "lyrics", "check", "--yes")
    assert rc == 0 and len(calls) == 1
