"""slop edit export: engine assets in the EV window.* formats, LYR from words + display.txt, frames, plates, depth."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop.board import draft, plates  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.edit import depth, export  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not synth.have_ffmpeg(), reason="ffmpeg not installed")


def _js(path: Path):
    s = path.read_text(encoding="utf-8")
    assert s.endswith(";\n")
    name, _, rest = s.splitlines()[0].partition("=")          # shots.js adds a second line: the SHOTLIST alias
    return name.strip(), json.loads(rest.strip().rstrip(";"))


def _ready(tmp_path, **kw):
    """A drafted, filled, picked board with one delivered sung clip (a real 2 s mp4)."""
    p = synth.make_project(tmp_path, **kw)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    synth.write_json(p / "board/shots.json", S)
    owners = [s["plate"] for s in S["shots"] if s.get("mj_prompt")]
    for i, key in enumerate(owners):
        synth.make_image(tmp_path / "dl" / f"{key}-1.png", 3000 if i == 0 else 320, 1688 if i == 0 else 180, seed=i)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [], all_first=True)
    c = next(c for c in S["seedance"] if c["kind"] == "sung")
    if synth.have_ffmpeg():
        synth.make_video(p / "clips" / c["clip"] / "take-1.mp4", seconds=2.0)
        synth.write_json(p / "clips" / f"{c['clip']}.json", {
            "id": c["clip"], "kind": "sung", "status": "delivered", "song_t0": c["song_t0"], "body": {"duration": 2},
            "takes": [{"file": f"clips/{c['clip']}/take-1.mp4", "status": "delivered",
                       "sync": {"lag_s": 0.0, "ncc": 0.5, "mode": "copy",
                                "synced": [[c["song_t0"], c["song_t0"] + 1.9]]}}]})
    return p, S, c


@needs_ffmpeg
def test_export_writes_every_engine_asset(tmp_path):
    p, S, c = _ready(tmp_path)
    W = synth.load(p, "analysis/words.json")
    # display.txt: line 0 shows "ROBOTS walk|2 …" (two sung words on one token) with an accent
    rows = [l["text"] for l in W["lines"]]
    words0 = [w["w"] for w in W["words"] if w["line"] == 0]
    rows[0] = f"*{words0[0].upper()} {words0[1]}|2 " + " ".join(words0[3:]) + " +|0"
    (p / "lyrics/display.txt").write_text("[Verse]\n" + "\n".join(rows) + "\n", encoding="utf-8")
    r = export.run(p, depth="off")
    A = p / "engine/assets"
    names = {f: _js(A / f)[0] for f in ("beats.js", "lyrics.js", "hits.js", "shots.js", "edl.js", "plates.js", "clips.js")}
    assert names == {"beats.js": "window.BEATS", "lyrics.js": "window.LYR", "hits.js": "window.HITS",
                     "shots.js": "window.SHOTS", "edl.js": "window.EDL", "plates.js": "window.PLATES",
                     "clips.js": "window.CLIPS"}
    _, B = _js(A / "beats.js")
    assert {"beats", "downbeats", "duration", "sections", "tempo_start", "tempo_end", "rms24", "lines", "words"} <= set(B)
    assert B["sections"][0]["name"] == "intro" and B["sections"][1]["t0"] == 8.0 and B["sections_t"][1] == 8.0
    assert B["tempo_start"] < B["tempo_end"]
    assert set(B["words"][0]) == {"w", "line", "t0", "t1", "s"} and len(B["rms24"]) > 100
    _, L = _js(A / "lyrics.js")
    assert [l["line"] for l in L] == sorted(l["line"] for l in L) and all(l["kind"] == "lyric" for l in L)
    l0 = L[0]
    assert l0["tokens"][0] == {"txt": words0[0].upper(), "t0": W["words"][0]["t0"], "t1": W["words"][0]["t1"],
                               "st": "accent", "n": 1}
    assert l0["tokens"][1]["n"] == 2 and l0["tokens"][1]["t1"] == [w for w in W["words"] if w["line"] == 0][2]["t1"]
    assert l0["tokens"][-1]["txt"] == "+" and l0["tokens"][-1]["n"] == 0          # rides on a neighbour's time
    assert set(l0) == {"line", "kind", "text", "t0", "t1", "tokens"}
    _, H = _js(A / "hits.js")
    assert {"fps", "kick", "kick_s", "snare", "hat", "impact", "riser", "ride", "fill", "vox_on", "env"} <= set(H)
    assert H["impact"][0] == {"t": 8.0, "s": 0.8} and H["ride"] == [[22.0, 24.0]]
    _, SL = _js(A / "shots.js")
    assert SL["shots"] == synth.load(p, "board/shots.json")["shots"]
    assert set(SL) >= {"duration", "chapters", "shots", "seedance", "plates"}          # contract §3.2: the board
    assert (A / "shots.js").read_text(encoding="utf-8").splitlines()[1] == "window.SHOTLIST = window.SHOTS;"
    assert H["impact_all"] == H["impact"]                  # no hits_all in this analysis: the top hits stand in
    assert r["text"].splitlines()[1].startswith("edit: ") and " shots · " in r["text"].splitlines()[1]
    _, E = _js(A / "edl.js")
    assert E == synth.load(p, "edit/edl.json")
    assert any(g["clip"] == f"{c['clip']}-t1" for e in E.values() for g in e.get("segs", []))
    _, C = _js(A / "clips.js")
    ce = C[f"{c['clip']}-t1"]
    assert ce["fps"] == 24 and ce["dir"] == f"assets/clips/{c['clip']}-t1" and 47 <= ce["n"] <= 49
    assert (A / "clips" / f"{c['clip']}-t1" / "f00001.jpg").is_file()
    _, PL = _js(A / "plates.js")
    big = S["shots"][0]["plate"]
    from PIL import Image
    assert Image.open(A / "plates" / f"{big}.jpg").width == 2400 and PL[big]["w"] == 2400
    assert PL[big]["boxes"] == {} and "subject_depth" not in PL[big] and PL[big]["depth"] is False
    assert r["plates"]["made"] == len(PL) and r["clips"]["made"] == 1
    r2 = export.run(p, depth="off")                       # idempotent: nothing rebuilt
    assert r2["plates"]["made"] == 0 and r2["clips"]["made"] == 0 and r2["clips"]["kept"] == 1


def test_fallback_lyr_matches_the_audio_parser(tmp_path, monkeypatch):
    p = synth.make_project(tmp_path)
    W = synth.load(p, "analysis/words.json")
    rows = [l["text"] for l in W["lines"]]
    ws = [w["w"] for w in W["words"] if w["line"] == 1]
    rows[1] = f"~{ws[0]}~ {ws[1]}|2 _{ws[3]}_ " + " ".join(ws[4:]) + " +|0"
    (p / "lyrics/display.txt").write_text("[Verse]\n\n" + "\n".join(rows) + "\n", encoding="utf-8")
    from slop.board.common import load_words
    W = load_words(p)
    first, _ = export.build_lyr(p, W)
    monkeypatch.setitem(sys.modules, "slop.audio.display", None)       # the audio module absent -> the local copy
    second, _ = export.build_lyr(p, W)
    assert first == second
    assert second[1]["tokens"][0]["st"] == "strike" and second[1]["tokens"][2]["st"] == "mono"


def test_display_txt_must_consume_every_word(tmp_path):
    p, S, c = _ready(tmp_path)
    W = synth.load(p, "analysis/words.json")
    rows = [l["text"] for l in W["lines"]]
    rows[2] = "TOO FEW"
    (p / "lyrics/display.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(SlopError, match=r"line \d+: .*consumes 2 of"):
        export.build_lyr(p, W)
    (p / "lyrics/display.txt").write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(SlopError, match="one row per lyric line"):
        export.build_lyr(p, W)


def test_rms24_from_the_song_and_hits_conversion(tmp_path):
    p = synth.make_project(tmp_path, hits=False)
    if synth.have_ffmpeg():
        synth.make_wav(p / "audio/song.wav", seconds=3.0)
        rms = export.rms24_from_song(p, synth.load(p, "project.json"))
        assert 70 <= len(rms) <= 73 and max(rms) > 0.1
    H = export.build_hits({"kick": [{"t": 1.0, "s": .5}], "hits": [{"t": 2.0, "score": .9}],
                           "risers": [{"t0": 3, "t1": 4, "land": 4.1}], "fills": [{"t0": 5, "t1": 5.5}],
                           "vocal_entries": [0.5], "env24": {"mix": [0.1]}, "extra": 1}, 10.0)
    assert H["kick"] == [1.0] and H["kick_s"] == [.5] and H["impact"] == [{"t": 2.0, "s": .9}]
    assert H["riser"] == [[3, 4]] and H["ride"] == [[3, 4.1]] and H["fill"] == [[5, 5.5]]
    assert H["vox_on"] == [0.5] and H["env"] == {"mix": [0.1]} and H["extra"] == 1


def test_depth_postprocess_and_export_with_a_stub_model(tmp_path, monkeypatch):
    import numpy as np
    d = np.tile(np.linspace(0, 1, 200, dtype=np.float32), (100, 1))
    sd = depth.depth_png(d, tmp_path / "x.depth.png")
    from PIL import Image
    im = Image.open(tmp_path / "x.depth.png")
    assert im.mode == "L" and im.size == (200, 100) and 0.85 <= sd <= 1.0
    p = synth.make_project(tmp_path / "proj")
    draft.run(p)
    key = synth.load(p, "board/shots.json")["shots"][0]["plate"]
    synth.make_image(tmp_path / "dl" / f"{key}-1.png", 320, 180)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [key, "1"])
    monkeypatch.setattr(depth, "available", lambda: True)
    monkeypatch.setattr(depth, "estimate", lambda im: np.tile(np.linspace(0, 1, im.width, dtype=np.float32), (im.height, 1)))
    r = export.run(p, depth="auto", frames=False)
    _, PL = _js(p / "engine/assets/plates.js")
    assert PL[key]["subject_depth"] > 0.8 and (p / f"engine/assets/plates/{key}.depth.png").is_file()
    assert "small" in PL[key]["depth_model"].lower() and "depth" not in PL[key]
    assert r["plates"]["depth"] == 1
    monkeypatch.setattr(depth, "available", lambda: False)
    r = export.run(p, depth="auto", frames=False)
    assert any("no depth maps" in w for w in r["warnings"])
    with pytest.raises(SlopError, match="torch"):
        export.run(p, depth="on", frames=False)


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("SLOP_TEST_DEPTH"), reason="set SLOP_TEST_DEPTH=1 to download and run the model")
def test_depth_anything_v2_small_real_model(tmp_path):
    from PIL import Image
    im = Image.open(synth.make_image(tmp_path / "a.png", 320, 180))
    d = depth.estimate(im)
    assert d.shape == (180, 320) and 0 <= d.min() and d.max() <= 1
