"""Scansion / lint (`slop lyrics lint`) with a small CMUdict subset fixture (offline), display tokens, and a scrub check
that nothing in slop/audio carries private names, hosts or profile codes."""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slop.audio import display as D  # noqa: E402
from slop.audio import pron  # noqa: E402
from slop.audio import scansion as S  # noqa: E402
from slop.cli import main  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "audio"


@pytest.fixture(autouse=True)
def mini_dict(tmp_path, monkeypatch):
    home = tmp_path / "slophome"
    (home / "cache" / "cmudict").mkdir(parents=True)
    shutil.copy(FIX / "cmudict-mini.dict", home / "cache" / "cmudict" / "cmudict.dict")
    monkeypatch.setenv("SLOP_HOME", str(home))
    monkeypatch.setenv("SLOP_OFFLINE", "1")
    monkeypatch.setitem(sys.modules, "cmudict", None)          # never the installed package
    pron.cmu.cache_clear()
    S.configure({})
    yield
    pron.cmu.cache_clear()


def test_dictionary_loaded_from_cache():
    d = pron.cmu()
    assert "deceive" in d and d["deceive"][0] == ["D", "IH0", "S", "IY1", "V"]
    assert pron.cmu_status().startswith("cmudict")


def test_num_words_and_spelling():
    assert pron.num_words("2077") == "twenty seventy seven"
    assert pron.num_words("157") == "one fifty seven"
    assert pron.num_words("11.2") == "eleven point two"
    assert pron.num_words("2000000") == "two million"
    assert pron.spell_numbers("Three a.m., at 10%") == "Three a.m., at ten percent"


def test_score_line_spoken_and_letters():
    r = S.score_line("Look one. A G I era. Not unreasonable.", "spoken")
    assert r["n"] == 12 and 1.5 <= r["bars"] <= 3.5 and 0 < r["score"] <= 100
    letters = [s for s in r["syl"] if s["word"] in "AGI"]
    assert [s["v"] for s in letters] == ["EY", "IY", "AY"]          # spaced capitals are letter names
    assert r["guessed"] == []


def test_flow_two_bar_slot():
    f = S.flow_line("Peptide rave in San Francisco. Chrome from head to toe.", "spoken")
    assert f["bars"] == 2 and 10 <= f["n"] <= 13
    assert 4 <= f["entry"] <= 8 and 24 <= f["last_at"] <= 32        # enters near the "&" of 2, lands near beat 4 of bar 2
    assert f["rk"] == "OW"
    g = S.groove("It went down. It was that good.")
    assert g["groove"] >= 90


def test_lint_tells_banned_and_fixes():
    out = S.lint("It is not just a neon dream, it is P(doom) at 10%", "sung")
    msgs = " | ".join(m for _, m in out)
    assert "P doom" in msgs and "digits" in msgs and "neon" in msgs
    assert not any(lv == "ERROR" and "banned" in m for lv, m in out)
    S.configure({"banned": {"catwalk": "the director's rule"}, "callbacks": [r"so back"]})
    out = S.lint("We walk the catwalk, we are so back", "spoken")
    assert any(lv == "ERROR" and "catwalk" in m for lv, m in out)
    assert any("callback" in m for _, m in out)
    S.configure({"banned": ["tonight"]})
    assert any(lv == "ERROR" for lv, _ in S.lint("We walk tonight", "spoken"))
    fx, fixed = S.fixes("Three a.m., P(doom) at 10%")
    assert fixed == "Three a.m., P doom at ten percent" and [f["kind"] for f in fx] == ["parentheses", "numbers"]


def test_no_person_specific_default_ban():
    S.configure({})
    assert S.banned() == {}


def test_cli_lint_file_without_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    f = tmp_path / "draft.md"
    f.write_text("[Verse 1: spoken, deadpan]\nLook one. A G I era. Not unreasonable.\nHalf your pay in tokens, or 10% alarmed.\n"
                 "[Chorus: sung]\nFeel the A G I, feel it coming fast\nEscape velocity\n", encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", "lyrics", "lint", str(f), "--write-fixed"])
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert rc == 0, out
    assert [s["mode"] for s in out["sections"]] == ["spoken", "sung"]
    assert out["sections"][0]["flow"]["flow"] > 0 and out["sections"][1]["groove"] is not None
    line2 = out["sections"][0]["lines"][1]
    assert any(x["level"] == "warn" and "digits" in x["msg"] for x in line2["lint"]) and line2["fixes"]
    assert any(p["level"] == "error" for p in out["sheet"])                 # the aligner would drop "10%"
    fixed = Path(out["fixed_file"]).read_text(encoding="utf-8")
    assert "ten percent" in fixed and "[Chorus: sung]" in fixed
    assert "syl" not in out["sections"][0]["lines"][0]                      # per-syllable data stays out of JSON


def test_cli_lint_single_line_text_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["lyrics", "lint", "--line", "Why would I deceive you?", "--mode", "sung", "--grid"])
    assert rc == 0 and "deceive" in buf.getvalue()


# ---------------------------------------------------------------- display tokens (unit)
def test_display_tokens_and_lyr():
    assert D.tokens("AGI|3 era. +25%|3 =|1 KM/S.|0") == [["AGI", 3], ["era.", None], ["+25%", 3], ["=", 1], ["KM/S.", 0]]
    assert D.consumed("Look|1 01.|1 AGI|3 era.") == 6
    assert D.consumed("— Escape velocity…") == 2
    assert D.starter_line("Look one. A G I era.") == "Look one. AGI|3 era."
    assert D.starter_line("C S I: Miami.") == "CSI:|3 Miami."
    words = [{"w": w, "line": 0, "t0": t, "t1": t + .2} for w, t in (("a", 1.0), ("g", 1.3), ("i", 1.6), ("era", 2.0))]
    L = D.build_lyr(words, ["*AGI|3 era. 11.2|0"], [{"text": "so so", "t0": 5.0, "t1": 6.0},
                                                    {"kind": "zeros", "text": "", "t0": 7, "t1": 8, "each": [7.0, 7.5]}])
    tok = L[0]["tokens"]
    assert tok[0] == {"txt": "AGI", "t0": 1.0, "t1": 1.8, "st": "accent", "n": 3}
    assert tok[2]["t0"] == tok[1]["t0"] == 2.0                              # a trailing |0 token takes the previous time
    assert [x["kind"] for x in L] == ["lyric", "adlib", "zeros"] and L[2]["text"] == "0 0"
    with pytest.raises(Exception, match="consumes 2 of 4"):
        D.build_lyr(words, ["AGI|1 era"])
    probs = D.validate(["one two", "three"], ["one|2"])
    assert probs and "1 lyric lines" in probs[0]["msg"]


# ---------------------------------------------------------------- scrub
def test_module_is_scrubbed():
    """No private word in the audio module, its tests or fixtures (hashed list + scanner: tests/scrublist.py)."""
    import scrublist
    files = [f for f in (ROOT / "slop" / "audio").rglob("*") if "__pycache__" not in f.parts] +         list((ROOT / "tests").glob("test_audio*.py")) + [ROOT / "tests" / "bench_audio_ev.py"] + list(FIX.glob("*"))
    bad = []
    for f in files:
        if f.is_dir() or f.suffix not in (".py", ".dict", ".json", ".txt", ".md"):
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        bad += [f"{f.name}: {h}" for h in scrublist.private_hits(txt)]
        if "/" + "opt/" in txt:
            bad.append(f"{f.name}: a private /opt path")
    assert not bad, bad


def test_glued_parentheses_rule_is_generic():
    out = S.lint("We plot f(x) tonight", "spoken")
    assert any(lv == "ERROR" and '"f x"' in m for lv, m in out)
    assert S.fixes("We plot f(x) tonight")[1] == "We plot f x tonight"
    assert not any(lv == "ERROR" for lv, m in S.lint("I (really) want it", "spoken"))   # backing vocal: info only


def test_names_come_from_the_project_not_a_built_in_list():
    assert S.NAMES == set()
    S.configure({})
    a = S.flow_line("ada said turing knew and lovelace knew it too", "spoken")
    S.configure({"names": ["ada", "turing", "lovelace"]})
    b = S.flow_line("ada said turing knew and lovelace knew it too", "spoken")
    assert a["names"] == 0 and b["names"] == 3
    S.configure({})
    c = S.flow_line("so Ada said it, and Turing knew it", "spoken")     # capitalised inside a sentence
    assert c["names"] == 2


def test_example_pronunciations_ship_as_project_data():
    ex = json.loads((ROOT / "slop" / "audio" / "examples" / "pron.json").read_text(encoding="utf-8"))
    assert ex and all(re.fullmatch(r"[A-Z]+[012]?( [A-Z]+[012]?)*", v) for v in ex.values())
    assert not set(ex) & set(S.PRON)                                   # not built in any more
    for w in ex:
        assert w not in S.PRON
