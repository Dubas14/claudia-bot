"""End to end on the 8-second demo project through the real CLI: lyric gate, frames, master encode (BT.709 tags),
flash + history checks, contact sheet, and the 9:16 cut. Marked slow (≈ 1–2 min on 4 cores)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
sys.path.insert(0, str(FIX))
pytest.importorskip("playwright.sync_api")
pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")]


def slop(capsys, *args) -> dict:
    from slop.cli import main
    rc = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(out)
    if rc != 0 and "could not start a browser" in str(d.get("error", "")):
        pytest.skip(d["error"])
    d["_rc"] = rc
    return d


@pytest.fixture(autouse=True)
def _pin_engine_hash(monkeypatch):
    """Other modules edit engine/src while these tests run; a changed engine (correctly) makes every frame stale, which
    would turn "resumable" assertions into races. The engine part of the fingerprint is pinned here; that engine edits
    invalidate frames is tested in test_engine_render_unit.py::test_fingerprint_sees_engine_code."""
    from slop.render import project as P
    monkeypatch.setattr(P, "engine_code_hash", lambda: "pinned-for-e2e")


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    import make_demo
    d = tmp_path_factory.mktemp("e2e") / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    make_demo.write_audio(d / "audio" / "song.wav")
    return d


@pytest.mark.parametrize("renderer", ["stub", "default"])
def test_lyric_gate(demo, capsys, monkeypatch, renderer):
    if renderer == "stub":
        monkeypatch.setenv("SLOP_ENGINE_SHOTS", "0")
    r = slop(capsys, "--project", str(demo), "render", "lyrics")
    assert r["_rc"] == 0 and r["ok"], r.get("text")
    assert r["gate"] == "6/6" and r["missing"] == []
    assert json.loads((demo / "render" / "lyrics-report.json").read_text())["drawn"] == 6


def test_info(demo, capsys):
    r = slop(capsys, "--project", str(demo), "render", "info")
    assert r["ok"] and r["info"]["scenes"] >= 3 and not r["info"]["page_errors"]
    assert set(r["fallbacks"]) == {"BEATS", "HITS", "SHOTS", "EDL"}


def test_master_end_to_end(demo, capsys):
    r = slop(capsys, "--project", str(demo), "render", "frames", "--workers", "2")
    assert r["ok"] and r["total"] == 192 and r["complete"], r.get("text")
    again = slop(capsys, "--project", str(demo), "render", "frames", "--workers", "2")      # resumable / idempotent
    assert again["ok"] and again["rendered"] == 0 and again["skipped"] == 192, again.get("text")
    e = slop(capsys, "--project", str(demo), "render", "encode")
    assert e["_rc"] == 0 and e["ok"], e.get("text")
    v = e["verify"]
    assert v["tags"] == {"codec_name": "h264", "pix_fmt": "yuv420p", "color_space": "bt709", "color_primaries": "bt709",
                         "color_transfer": "iec61966-2-1", "color_range": "tv"}
    assert (v["width"], v["height"], v["frames"], v["audio"]) == (1920, 1080, 192, "aac")
    assert abs(v["duration"] - 8.0) < .1 and Path(e["out"]) == demo / "out" / "master.mp4"
    c = slop(capsys, "--project", str(demo), "render", "check", "--pairs", "6.9:1.2,1.2:4.6")
    assert c["ok"], c.get("text")
    assert c["flash"]["pass"] and c["flash"]["worst_per_second"] <= 3
    assert all(p["pixels_over"] == 0 for p in c["history"]["pairs"])


def test_sheet(demo, capsys):
    r = slop(capsys, "--project", str(demo), "render", "sheet")
    assert r["ok"] and Path(r["sheet"]).is_file() and len(r["times"]) == 3      # one per shot mid-point
    from PIL import Image
    assert Image.open(r["sheet"]).size == (3 * 480, 270 + 18)


def test_vertical_rerender(demo, capsys):
    r = slop(capsys, "--project", str(demo), "render", "vertical", "--every", "6", "--workers", "2")
    assert r["ok"], r.get("text")
    v = r["encode"]["verify"]
    assert (v["width"], v["height"]) == (1080, 1920) and v["tags"]["color_primaries"] == "bt709"
    assert Path(r["out"]).name == "vertical-draft.mp4"


def test_vertical_layout_can_be_gated(demo, capsys):
    r = slop(capsys, "--project", str(demo), "render", "lyrics", "--vertical")
    assert r["ok"] and r["gate"] == "6/6" and r["size"] == [1080, 1920], r.get("text")
    assert Path(r["report"]).name == "lyrics-report-vertical.json"
    s = slop(capsys, "--project", str(demo), "render", "sheet", "--vertical")
    assert s["ok"] and Path(s["sheet"]).name == "sheet-vertical.jpg"
    from PIL import Image
    assert Image.open(s["sheet"]).size == (3 * 480, 853 + 18)


def test_vertical_crop_is_a_preview(demo, capsys):
    """--method crop cuts left-hung type: it must never be written as the deliverable out/vertical.mp4."""
    r = slop(capsys, "--project", str(demo), "render", "vertical", "--method", "crop")
    assert r["ok"] and r["preview"] and Path(r["out"]).name == "vertical-crop.mp4", r.get("text")
    assert r["encode"]["profile"] == "draft" and "PREVIEW" in r["text"]
    assert (r["encode"]["verify"]["width"], r["encode"]["verify"]["height"]) == (1080, 1920)


def _copy(tmp_path) -> Path:
    import make_demo
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    make_demo.write_audio(d / "audio" / "song.wav")
    return d


def test_partial_frames_never_make_a_master(tmp_path, capsys):
    """The reviewer's repro: `frames --from 2`, then `encode` made a 6 s master with every word 2 s early."""
    d = _copy(tmp_path)
    r = slop(capsys, "--project", str(d), "render", "frames", "--from", "2", "--to", "3", "--workers", "2")
    assert r["ok"] and r["total"] == 24, r.get("text")
    e = slop(capsys, "--project", str(d), "render", "encode")
    assert e["_rc"] == 1 and not e["ok"] and "first: f00000" in e["error"] and "168 of 192" in e["error"], e
    dr = slop(capsys, "--project", str(d), "render", "encode", "--draft")
    assert dr["ok"] and dr["start_frame"] == 48 and dr["verify"]["frames"] == 24, dr.get("text")


def test_stale_frames_are_redrawn(tmp_path, capsys):
    d = _copy(tmp_path)
    a = slop(capsys, "--project", str(d), "render", "frames", "--every", "24", "--workers", "2")
    assert a["ok"] and a["rendered"] == 8
    b = slop(capsys, "--project", str(d), "render", "frames", "--every", "24", "--workers", "2")
    assert b["ok"] and b["rendered"] == 0 and not b["stale_discarded"]
    lj = d / "engine" / "lyrics.js"
    src = lj.read_text(encoding="utf-8")
    assert '"Hello"' in src, "the fixture's first token changed: pick another word to edit"
    # fix a lyric (a real content change: rewriting the file alone must not count; with CRLF fixtures it used to)
    lj.write_text(src.replace('"Hello"', '"HELLO"'), encoding="utf-8")
    c = slop(capsys, "--project", str(d), "render", "frames", "--every", "24", "--workers", "2")
    assert c["ok"] and c["stale_discarded"] and c["rendered"] == 8, c.get("text")
    assert "data:engine/lyrics.js" in c["text"]


def test_missing_media_stops_the_render(tmp_path, capsys):
    d = _copy(tmp_path)
    (d / "plates" / "grad-a.jpg").unlink()
    i = slop(capsys, "--project", str(d), "render", "info")
    assert not i["ok"] and any(m.endswith("grad-a.jpg") for m in i["missing_media"]) and "grad-a.jpg" in i["text"]
    f = slop(capsys, "--project", str(d), "render", "frames", "--every", "24")
    assert f["_rc"] == 1 and "grad-a.jpg" in f["error"] and "--allow-missing" in f["error"] and "slop edit export" in f["error"]
    assert not list((d / "render" / "frames").glob("f*.jpg"))
    s = slop(capsys, "--project", str(d), "render", "stills", "--times", "1")
    assert s["_rc"] == 1 and "grad-a.jpg" in s["error"]
    p = slop(capsys, "--project", str(d), "render", "frames", "--every", "24", "--allow-missing", "--workers", "2")
    assert p["ok"] and p["rendered"] == 8 and any("allow-missing" in w for w in p["warnings"]), p.get("text")
    e = slop(capsys, "--project", str(d), "render", "encode")
    assert e["_rc"] == 1 and "allow-missing" in e["error"]


def test_timemap_renders_the_final_song(tmp_path, capsys):
    d = _copy(tmp_path)
    (d / "edit" / "timemap.json").write_text(json.dumps({"segments": [[0, 4, 0, 4], [4, 10, 4, 8]]}), encoding="utf-8")
    r = slop(capsys, "--project", str(d), "render", "frames", "--timemap", "--from", "7.5", "--to", "10", "--every", "12",
             "--out", str(d / "render" / "frames-tm"))
    assert r["ok"] and r["range"] == [7.5, 10.0] and r["duration"] == 10.0 and r["total"] == 5, r.get("text")
    assert not any("past the end" in w for w in r["warnings"])
    r2 = slop(capsys, "--project", str(d), "render", "frames", "--timemap", "--from", "9.5", "--to", "12", "--every", "12",
              "--out", str(d / "render" / "frames-tm"))
    assert r2["range"] == [9.5, 10.0] and any("past the end" in w for w in r2["warnings"]) and "past the end" in r2["text"]


def test_untimed_word_fails_the_gate(tmp_path, capsys):
    d = _copy(tmp_path)
    (d / "engine" / "lyrics.js").unlink()
    words = json.loads((d / "analysis" / "words.json").read_text(encoding="utf-8"))
    words["words"][4]["t0"] = None
    (d / "analysis" / "words.json").write_text(json.dumps(words), encoding="utf-8")
    r = slop(capsys, "--project", str(d), "render", "lyrics")
    assert r["_rc"] == 1 and r["gate"] == "5/6" and r["untimed"] == 1, r.get("text")
    m = [x for x in r["missing"] if x["t0"] is None]
    assert len(m) == 1 and "no t0" in m[0]["why"] and "analysis/words.json" in r["text"]


def test_failed_font_stops_the_render(tmp_path, capsys):
    d = _copy(tmp_path)
    pj = json.loads((d / "project.json").read_text(encoding="utf-8"))
    pj["font_files"] = [{"family": "Nope Sans", "file": "fonts/nope.ttf", "project": True}]
    (d / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    i = slop(capsys, "--project", str(d), "render", "info")
    assert not i["ok"] and "fonts/nope.ttf" in i["text"]
    s = slop(capsys, "--project", str(d), "render", "stills", "--times", "1")
    assert s["_rc"] == 1 and "font file(s) failed" in s["error"] and "nope.ttf" in s["error"]
