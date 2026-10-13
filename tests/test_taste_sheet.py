"""slop.taste.sheet: the no-tunnel fallback — numbered pair sheets for the chat and `slop taste record`."""
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.taste import embed as E  # noqa: E402
from slop.taste import model as M  # noqa: E402
from slop.taste import sheet as SH  # noqa: E402
from slop.taste.embed import load_store  # noqa: E402
from slop.taste.store import live_events, read_events, read_jsonl, split_events, taps_path  # noqa: E402


def run(capsys, *args):
    code = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    return S.make_project(tmp_path)


@pytest.mark.parametrize("text,want", [
    ("1a 2b 3a", [(1, "a"), (2, "b"), (3, "a")]),
    ("1A,2B; 3 a", [(1, "a"), (2, "b"), (3, "a")]),
    ("1:left 2-right 3 t 4x 5=", [(1, "a"), (2, "b"), (3, "tie"), (4, "skip"), (5, "tie")]),
    ("1a2b10a", [(1, "a"), (2, "b"), (10, "a")]),
    ("  12 b\n13 skip ", [(12, "b"), (13, "skip")]),
])
def test_parse_answers(text, want):
    assert SH.parse_answers(text) == want


@pytest.mark.parametrize("text", ["1a 2c", "hello", "", "1a and 2b", "a1 b2"])
def test_parse_answers_rejects_anything_unread(text):
    with pytest.raises(SlopError, match="nothing was recorded"):
        SH.parse_answers(text)


def test_sheets_are_numbered_small_and_pair_different_images(proj):
    ids, labs = S.fake_pool(proj, clusters=4, per=30)
    S.write_images(proj / "taste" / "pool" / "images", {"grey": 3}, start_seed=7)   # a few real files, the rest missing
    r = SH.make_sheets(proj, pairs=12, per_sheet=4, seed=3)
    assert r["pairs"] == 12 and len(r["files"]) == 3 and all(Path(f).is_file() for f in r["files"])
    assert all(b <= SH.MAX_BYTES for b in r["bytes"]) and "1a" in r["message"] and "slop taste record" in r["text"]
    from PIL import Image
    im = Image.open(r["files"][0])
    assert im.format == "JPEG" and im.width == SH.W
    sheet = json.loads((proj / "taste" / "sheets" / r["sheet"] / "sheet.json").read_text(encoding="utf-8"))
    items = [x for p in sheet["pairs"] for x in (p["a"], p["b"])]
    assert len(items) == len(set(items)) == 24 and [p["n"] for p in sheet["pairs"]] == list(range(1, 13))
    _, X, _ = load_store(proj)
    index = {i: k for k, i in enumerate(ids)}
    Xn = X / np.linalg.norm(X, axis=1, keepdims=True)
    assert all(float(Xn[index[p["a"]]] @ Xn[index[p["b"]]]) < M.PAIR_LOOKALIKE for p in sheet["pairs"])
    assert {p["why"] for p in sheet["pairs"]} <= {"cold", "explore"}          # no model yet
    # a second sheet before the first is answered (--new) never reuses its images
    r2 = SH.make_sheets(proj, pairs=8, seed=4, new=True)
    s2 = json.loads((proj / "taste" / "sheets" / r2["sheet"] / "sheet.json").read_text(encoding="utf-8"))
    assert not ({x for p in s2["pairs"] for x in (p["a"], p["b"])} & set(items))


def test_a_noisy_full_size_sheet_stays_under_2_mb(proj):
    from PIL import Image
    from slop.taste.pool import PoolWriter, add_dir
    d = proj.parent / "noise"
    d.mkdir()
    rng = np.random.default_rng(0)
    for k in range(8):                                      # worst case for JPEG: pure noise at full size
        Image.fromarray(rng.integers(0, 255, (1024, 1024, 3), dtype=np.uint8)).save(d / f"n{k}.png")
    add_dir(PoolWriter(proj), d)
    r = SH.make_sheets(proj, pairs=4, per_sheet=4, seed=0)
    assert r["bytes"][0] <= SH.MAX_BYTES and Path(r["files"][0]).stat().st_size <= 2_000_000


def test_record_partial_repeat_redo_and_errors(proj):
    S.fake_pool(proj, clusters=3, per=20)
    r = SH.make_sheets(proj, pairs=6, seed=1)
    out = SH.record(proj, "1a 2b 3t", meter=False)
    assert out["recorded"] == [1, 2, 3] and out["missing"] == [4, 5, 6] and "4a" in out["text"]
    rows = [e for e in read_events(taps_path(proj)) if e.get("via") == "sheet"]
    assert len(rows) == 3 and {e["layout"] for e in rows} == {"sheet"} and {e["shown"] for e in rows} == {"ab"}
    assert rows[0]["sheet"] == r["sheet"] and rows[2]["winner"] == "tie"
    out = SH.record(proj, "3a 4b 5b 6a", meter=False)                   # the newest sheet with open pairs
    assert out["recorded"] == [4, 5, 6] and out["already"] == [3] and out["missing"] == []
    out = SH.record(proj, "3a", redo=True, meter=False)
    assert out["recorded"] == [3]
    ev = read_events(taps_path(proj))
    assert len(ev) == 6 and next(e for e in ev if e.get("n") == 3)["winner"] == "a"   # undone, not duplicated
    assert sum(1 for x in read_jsonl(taps_path(proj)) if "undo" in x) == 1
    with pytest.raises(SlopError, match="pairs 1-6"):
        SH.record(proj, "7a", meter=False)
    with pytest.raises(SlopError, match="answered twice"):
        SH.record(proj, "1a 1b", redo=True, meter=False)
    with pytest.raises(SlopError, match="no sheet"):
        SH.record(proj, "1a", sheet="nope", meter=False)
    assert len(read_events(taps_path(proj))) == 6                          # errors record nothing


def test_sheets_alone_teach_the_model_and_measure_self_agreement(proj):
    ids, labs = S.fake_pool(proj, clusters=4, per=30, spread=0.45)      # 120 images: sheets 6+ reuse seen images
    lab = dict(zip(ids, labs))
    like = lambda i: lab[i] in (0, 1)                                       # the user likes clusters 0 and 1
    rng = random.Random(0)
    whys = []
    for k in range(9):
        r = SH.make_sheets(proj, pairs=12, seed=k)
        sheet = json.loads((proj / "taste" / "sheets" / r["sheet"] / "sheet.json").read_text(encoding="utf-8"))
        ans = []
        for p in sheet["pairs"]:
            whys.append(p["why"])
            la, lb = like(p["a"]), like(p["b"])
            w = "a" if la and not lb else ("b" if lb and not la else rng.choice("ab"))
            if p["why"] == "repeat":                                        # answer a repeat as before
                prev = next(e for e in read_events(taps_path(proj)) if {e.get("a"), e.get("b")} == {p["a"], p["b"]})
                w = "a" if prev[prev["winner"]] == p["a"] else "b"
            ans.append(f"{p['n']}{w}")
        out = SH.record(proj, " ".join(ans), meter=(k == 8))
    assert "model" in whys and "repeat" in whys and "cold" in whys and "reuse" in whys
    assert out["self_agreement"] == 1.0 and out["repeats"] >= 1
    assert out["meter"] and out["meter"]["accuracy"] > 0.7 and "picks the one you prefer" in out["text"]
    assert out["meter_seconds"] is not None and out["meter_seconds"] < 30
    _, pairs = split_events(read_events(taps_path(proj)))
    assert len(pairs) >= 100


def test_sheet_and_record_through_the_cli(proj, capsys, monkeypatch):
    fe = S.FakeEmbedder()
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    S.write_images(proj.parent / "refs", {"grey": 10, "colour": 10, "red": 4})
    code, j = run(capsys, "-p", str(proj), "taste", "pool", "add", "--dir", str(proj.parent / "refs"))
    assert code == 0
    code, j = run(capsys, "-p", str(proj), "taste", "sheet", "--pairs", "4")
    assert code == 0 and j["pairs"] == 4 and len(j["files"]) == 1 and Path(j["files"][0]).is_file()
    code, j = run(capsys, "-p", str(proj), "taste", "record", "1a 2b 3a 4b")
    assert code == 0 and j["recorded"] == [1, 2, 3, 4] and j["taps"] == 4
    assert j["vectors"] is False and "slop taste embed" in j["text"] and "meter starts" not in j["text"]
    code, j = run(capsys, "-p", str(proj), "taste", "record", "1 maybe")
    assert code == 1 and "could not read" in j["error"]
    code, j = run(capsys, "-p", str(proj), "taste", "status")
    assert code == 0 and j["pairs"] == 4 and "slop taste sheet" in j["text"]


def test_sheet_on_an_empty_pool_is_actionable(proj, capsys):
    code, j = run(capsys, "-p", str(proj), "taste", "sheet")
    assert code == 1 and "pool add" in j["error"]
    code, j = run(capsys, "-p", str(proj), "taste", "record", "1a")
    assert code == 1 and "slop taste sheet" in j["error"]
    assert live_events([]) == []
