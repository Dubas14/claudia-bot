"""Studio-tier E2E fix (e2e/STUDIO-E2E.md defect 7): the 9:16 cut renders at FULL quality by default — also the
--from/--to stretch that is posted (the hook first came out at draft quality) — and says which profile it used; a
preview only when the frames are sampled (--every) or drawn with placeholders. Through the real CLI on the 8-second
demo project (a separate module: the CLI starts its own Playwright, which cannot run inside another module's page loop).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
sys.path.insert(0, str(FIX))
pytestmark = [pytest.mark.slow]


def _cli(capsys, *args) -> dict:
    from slop.cli import main
    rc = main(["--json", *args])
    d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    if rc != 0 and "could not start a browser" in str(d.get("error", "")):
        pytest.skip(d["error"])
    d["_rc"] = rc
    return d


@pytest.fixture
def demo(tmp_path, monkeypatch) -> Path:
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg not installed")
    from slop.render import project as P
    monkeypatch.setattr(P, "engine_code_hash", lambda: "pinned-for-studio")     # other modules edit engine/src meanwhile
    import make_demo
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    make_demo.write_audio(d / "audio" / "song.wav")
    return d


def test_vertical_stretch_is_full_quality_and_says_so(demo, capsys):
    """The hook: `render vertical --from A --to B` is the cut that is posted — master profile, out/vertical.mp4, its own
    frames and the song from its first frame, recorded as a stretch (clean and the share copy read it)."""
    r = _cli(capsys, "--project", str(demo), "render", "vertical", "--from", "2", "--to", "3", "--workers", "2")
    assert r["_rc"] == 0 and r["ok"], r.get("text") or r.get("error")
    assert r["profile"] == "master" and not r["preview"] and r["profile_why"] is None, r
    assert Path(r["out"]).name == "vertical.mp4" and r["span_s"] == [2.0, 3.0], r
    assert "profile master: full quality (x264 CRF 16" in r["text"] and "the stretch 2.00–3.00 s" in r["text"], r["text"]
    e = r["encode"]
    assert e["profile"] == "master" and e["start_frame"] == 48 and e["span"] == [48, 72], e
    v = e["verify"]
    assert v["ok"] and (v["width"], v["height"]) == (1080, 1920) and v["frames"] == 24 and v["audio"], v
    made = json.loads((demo / "out" / "vertical.mp4.inputs.json").read_text(encoding="utf-8"))
    assert made["span"] == [48, 72] and made["frames"] == 24, made
    from slop.render.clean import _verify_deliverable
    from slop.render.encode import _share_source
    ok, why = _verify_deliverable(demo, demo / "out" / "vertical.mp4", demo / "render" / "frames-vertical", True)
    assert ok and "the stretch 2.00–3.00 s" in why, why
    src = _share_source(demo, True, None)
    assert src["kind"] == "master" and src["start"] == 48 and src["frames"] == 24, src
    assert src["stretch"] == [48, 72] and src["stale"] is None, src
    # the project changes after the stretch was encoded: the share copy still comes from the stretch, and says it is stale
    pl = demo / "engine" / "plates.js"
    pl.write_text(pl.read_text(encoding="utf-8") + "\n// a later edit\n", encoding="utf-8")
    src = _share_source(demo, True, None)
    assert src.get("stretch") == [48, 72] and src["stale"] and "changed" in src["stale"], src
    # a later encode to out/vertical.mp4 that is not a verified master (here a preview of the frames on disk) replaces
    # the file AND its record: clean and the share copy no longer read the new file as the earlier stretch
    from slop.render.encode import encode, read_made_from
    e2 = encode(demo, frames=demo / "render" / "frames-vertical", out=demo / "out" / "vertical.mp4", profile="draft",
                allow_gaps=True, vertical=True)
    assert e2["ok"] and read_made_from(demo / "out" / "vertical.mp4") is None, e2
    ok, why = _verify_deliverable(demo, demo / "out" / "vertical.mp4", demo / "render" / "frames-vertical", True)
    assert not ok and "stretch" not in why, why
    assert not _share_source(demo, True, None).get("stretch")


def test_vertical_stretch_is_exactly_the_frames_drawn(tmp_path, monkeypatch):
    """vertical() hands encode the frame range render_frames drew (not one re-derived from the rounded seconds, which
    can ask for a frame that was never drawn), and a --from/--to that still covers the whole song is the film."""
    from slop.render import vertical as V
    d = tmp_path / "p"
    (d / "out").mkdir(parents=True)
    (d / "project.json").write_text(json.dumps({"name": "p", "fps": 24, "size": [1920, 1080]}), encoding="utf-8")
    seen = {}

    def frames(pdir, **kw):
        a, b = kw.get("t_from") or 0.0, 8.0 if kw.get("t_to") is None else kw["t_to"]
        lo, hi = int(round(a * 24)), int(-(-(b * 24 - 1e-6) // 1))
        return {"ok": True, "range": [round(a, 3), round(b, 3)], "span": [lo, hi], "duration": 8.0, "text": "frames"}

    def enc(pdir, **kw):
        seen["span"] = kw["span"]
        sp = kw["span"]
        return {"ok": True, "out": str(kw["out"]), "span": list(sp) if sp else None, "text": "encoded"}
    monkeypatch.setattr(V, "render_frames", frames)
    monkeypatch.setattr(V, "encode", enc)
    # --to 3.04166: drawn [48, 73); the rounded 3.042 s would ask for f00073 (3.042 × 24 = 73.008 → 74)
    r = V.vertical(d, t_from=2, t_to=3.04166)
    assert seen["span"] == (48, 73) and r["profile"] == "master" and r["span_s"] == [2.0, 3.042], (seen, r)
    # --from 0 (or a --to past the end): the whole song — an ordinary master, not a stretch
    r = V.vertical(d, t_from=0)
    assert seen["span"] is None and r["span_s"] is None and "stretch" not in r["text"], (seen, r["text"])


def test_vertical_preview_only_when_sampled(demo, capsys):
    r = _cli(capsys, "--project", str(demo), "render", "vertical", "--from", "1", "--to", "2", "--every", "6", "--workers", "2")
    assert r["ok"] and r["preview"] and r["profile"] == "draft", r.get("text")
    assert Path(r["out"]).name == "vertical-draft.mp4" and "--every 6 samples the frames" in r["profile_why"], r
    assert "profile draft: a PREVIEW" in r["text"] and "PREVIEW ONLY" in r["text"], r["text"]
    assert r["encode"]["start_frame"] == 24 and r["encode"]["verify"]["frames"] == 24, r["encode"]
    assert not (demo / "out" / "vertical.mp4").exists()
