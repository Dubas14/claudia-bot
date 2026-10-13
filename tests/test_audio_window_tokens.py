"""make_window(tokens=...): explicit words for a clean window (a her-words chain cannot match an earlier repeat)."""
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

from slop.audio.common import load_mono  # noqa: E402
from slop.audio.window import make_window, parse_token_list  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402

SR = 44100


def slop(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


@pytest.fixture()
def chain(tmp_path):
    """'you' sung twice inside one cover window: 1.0 s (the end of the parent's line) and 2.4 s (her chain's word)."""
    voc = np.zeros(SR * 6, np.float32)
    for t, f in ((1.0, 220), (1.6, 247), (2.4, 262), (3.0, 294), (4.6, 330)):
        sig = synth.tone(0.4, f, 0.2)
        voc[int(t * SR):int(t * SR) + len(sig)] = sig
    song = {"stems": {"vocals": voc, "drums": voc * 0, "bass": voc * 0, "other": voc * 0}, "mix": voc}
    root = synth.write_project(tmp_path / "chain", song)
    words = [{"i": 0, "w": "you", "line": 0, "t0": 1.0, "t1": 1.4}, {"i": 1, "w": "and", "line": 1, "t0": 1.6, "t1": 2.0},
             {"i": 2, "w": "you", "line": 1, "t0": 2.4, "t1": 2.8}, {"i": 3, "w": "know", "line": 1, "t0": 3.0, "t1": 3.4},
             {"i": 4, "w": "it", "line": 1, "t0": 4.6, "t1": 5.0}]
    for w in words:
        w.update(conf=0.9, src="w2v")
    (root / "analysis").mkdir()
    (root / "analysis" / "words.json").write_text(json.dumps({"words": words, "lines": [], "gaps": []}))
    (root / "lyrics").mkdir()
    (root / "lyrics" / "adlibs.json").write_text(json.dumps([{"text": "(hey)", "t0": 4.0, "t1": 4.3}]))
    return root


def _peak(root: Path, clip: str, a: float, b: float, t0: float) -> float:
    y = load_mono(root / "audio" / "windows" / f"{clip}.wav", SR)
    return float(np.abs(y[int((a - t0) * SR):int((b - t0) * SR)]).max())


def test_quote_matcher_is_greedy_tokens_are_exact(chain):
    old = make_window(chain, "C1q", 0.5, 4.2, quoted="you know")             # the backward-compatible path
    assert [w["t0"] for w in old["words"]] == [1.0, 3.0]                       # the EARLIER "you" (the bug)
    new = make_window(chain, "C1t", 0.5, 4.2, tokens=[[2.4, 2.8, "you"], [3.0, 3.4, "know"]])
    assert [w["t0"] for w in new["words"]] == [2.4, 3.0] and new["sung"] == "you know" and new["tokens"] == [2, 3]
    assert _peak(chain, "C1t", 1.05, 1.35, 0.5) < 1e-4                         # the other "you" is muted
    assert _peak(chain, "C1t", 2.45, 2.75, 0.5) > 0.05                         # hers is kept
    meta = json.loads((chain / "audio" / "windows" / "C1t.json").read_text())
    assert meta["tokens"] == [2, 3]
    both = make_window(chain, "C1b", 0.5, 4.2, quoted="you know", tokens=[2, 3])    # tokens + the quote they spell
    assert [w["t0"] for w in both["words"]] == [2.4, 3.0] and both["quoted"] == "you know"


def test_token_forms(chain):
    a = make_window(chain, "F1", 0.5, 4.2, tokens=[3, 2, 2])                         # indices: time order, deduped
    b = make_window(chain, "F2", 0.5, 4.2, tokens=[{"i": 2}, {"t0": 3.0, "t1": 3.4, "w": "know"}])
    c = make_window(chain, "F3", 0.5, 4.2, tokens=[(2.405, 2.8), [3.0, 3.4, "Know,"]])   # +-11 ms, punctuation ignored
    assert [w["t0"] for w in a["words"]] == [w["t0"] for w in b["words"]] == [w["t0"] for w in c["words"]] == [2.4, 3.0]
    d = make_window(chain, "F4", 0.5, 4.5, tokens=[[4.0, 4.3, "hey"], 3])            # an ad-lib from adlibs.json
    assert [w["w"] for w in d["words"]] == ["know", "hey"] and d["tokens"] == [3, None]


def test_token_errors(chain):
    with pytest.raises(SlopError, match="no word 9"):
        make_window(chain, "E1", 0.5, 4.2, tokens=[9])
    with pytest.raises(SlopError, match="outside the words this window can keep"):
        make_window(chain, "E2", 0.5, 4.2, tokens=[4])                       # "it" starts at 4.6, past t1 - .08
    with pytest.raises(SlopError, match="timing changed since the clip was drafted"):
        make_window(chain, "E3", 0.5, 4.2, tokens=[[2.5, 2.9, "you"]])       # a stale her_words span
    with pytest.raises(SlopError, match="timing changed"):
        make_window(chain, "E4", 0.5, 4.2, tokens=[[2.4, 2.8, "me"]])        # right time, other word
    with pytest.raises(SlopError, match="spell"):
        make_window(chain, "E5", 0.5, 4.2, quoted="and you", tokens=[2, 3])
    with pytest.raises(SlopError, match="--mode clean"):
        make_window(chain, "E6", 0.5, 4.2, mode="mix", tokens=[2])
    with pytest.raises(SlopError, match="empty"):
        make_window(chain, "E7", 0.5, 4.2, tokens=[])
    assert not (chain / "audio" / "windows" / "E1.mp3").exists()
    W = json.loads((chain / "analysis" / "words.json").read_text())       # an untimed word: the fix names --project
    W["words"][3].update(t0=None, t1=None)
    (chain / "analysis" / "words.json").write_text(json.dumps(W))
    with pytest.raises(SlopError, match=r"slop --project \S+ lyrics fix --word 3 --t0 <start> --t1 <end>"):
        make_window(chain, "E8", 0.5, 4.2, tokens=[3])
    (chain / "audio" / "stems" / "vocals.wav").unlink()
    with pytest.raises(SlopError, match=r"slop --project \S+ analyze --steps stems"):
        make_window(chain, "E9", 0.5, 4.2, tokens=[2])


def test_parse_token_list():
    assert parse_token_list("41, 42,45-47") == [41, 42, 45, 46, 47]
    for bad in ("", "a", "5-2", "1-500"):
        with pytest.raises(SlopError):
            parse_token_list(bad)


def test_cli_tokens(chain):
    rc, out = slop("-p", str(chain), "audio", "window", "K1", "--t0", "0.5", "--t1", "4.2", "--tokens", "2-3")
    assert rc == 0, out
    assert out["sung"] == "you know" and out["tokens"] == [2, 3]
    rc, out = slop("-p", str(chain), "audio", "window", "K2", "--t0", "0.5", "--t1", "4.2", "--tokens", "x")
    assert rc == 1 and "word indices" in out["error"]
    (chain / "analysis" / "words.json").unlink()
    rc, out = slop("-p", str(chain), "audio", "window", "K3", "--t0", "0.5", "--t1", "4.2", "--tokens", "2")
    assert rc == 1 and "slop --project" in out["error"] and "analyze" in out["error"]
