"""slop board sheet (contact sheet JPG + PDF) and the whole board -> plates -> edit chain through the CLI."""
import io
import json
import math
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop import cli  # noqa: E402
from slop.board import draft, plates, sheet  # noqa: E402


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


def test_sheet_pages_pdf_and_thumbnails(tmp_path):
    p = synth.make_project(tmp_path)
    draft.run(p)
    S = synth.load(p, "board/shots.json")
    key = S["shots"][0]["plate"]
    synth.make_image(tmp_path / "dl" / f"{key}-1.png", 640, 360, accent=True)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [key, "1"])
    r = sheet.build(p)
    n = len(S["shots"])
    assert r["pages"] == 1 + math.ceil(n / 12) and len(r["jpgs"]) == r["pages"]
    assert (p / "board/board.pdf").read_bytes()[:5] == b"%PDF-"
    from PIL import Image
    pg = Image.open(p / "board/board-p01.jpg")
    assert pg.size == (sheet.PW, sheet.PH)
    # the first card shows the picked plate (not the grey "PLATE PENDING" box)
    x, y = sheet.M + 30, sheet.M + 60
    assert pg.getpixel((x, y)) != (220, 218, 212)
    assert (p / "board/board.jpg").is_file()


@pytest.mark.skipif(not synth.have_ffmpeg(), reason="ffmpeg not installed")
def test_full_chain_through_the_cli(tmp_path):
    p = synth.make_project(tmp_path, look={"mode": "clean-grade", "accent": "#D97757", "hero_plate": None})
    P = str(p)
    code, out = _run("-p", P, "board", "draft")
    assert code == 0 and out["ok"]
    S = synth.fill_todos(synth.load(p, "board/shots.json"), framing="cycle")
    synth.write_json(p / "board/shots.json", S)
    code, out = _run("-p", P, "plates", "book", "--batch", "b01")
    assert code == 0 and out["mj_jobs"] > 0
    jobs = synth.load(p, "plates/mj/b01.json")["jobs"]
    for i, j in enumerate(jobs):
        for k in (1, 2):
            synth.make_image(tmp_path / "mj" / f"{j['plate']}-{k}.png", 320, 180, color=(40 + i, 90, 110), seed=k)
    code, out = _run("-p", P, "plates", "ingest", str(tmp_path / "mj"), "--batch", "b01")
    assert code == 0 and sum(len(v) for v in out["added"].values()) == 2 * len(jobs)
    code, out = _run("-p", P, "plates", "pick", "--all-first")
    assert code == 0 and not out["unpicked"]
    code, out = _run("-p", P, "plates", "vary")
    assert code == 0
    code, out = _run("-p", P, "board", "audit")
    assert code == 0 and out["ok"], out["text"]
    code, out = _run("-p", P, "board", "approve")
    assert code == 0 and synth.load(p, "project.json")["gates"]["board_approved"] is True
    code, out = _run("-p", P, "edit", "look", "set", "--hero", jobs[0]["plate"])
    assert code == 0 and out["ok"]
    code, out = _run("-p", P, "board", "sheet")
    assert code == 0 and Path(out["pdf"]).is_file()
    c = next(c for c in S["seedance"] if c["kind"] == "sung")
    synth.make_video(p / "clips" / c["clip"] / "take-1.mp4", seconds=1.0, size="160x90")
    synth.write_json(p / "clips" / f"{c['clip']}.json", {
        "id": c["clip"], "kind": "sung", "status": "delivered", "song_t0": c["song_t0"], "body": {"duration": 1},
        "takes": [{"file": f"clips/{c['clip']}/take-1.mp4", "status": "delivered",
                   "sync": {"lag_s": 0.0, "ncc": 0.5, "mode": "copy", "synced": [[c["song_t0"], c["song_t0"] + 0.9]]}}]})
    code, out = _run("-p", P, "edit", "export", "--depth", "off")
    assert code == 0 and out["ok"] and not out["missing_shots"], out["text"]
    clips_js = (p / "engine/assets/clips.js").read_text(encoding="utf-8")
    assert f'"{c["clip"]}-t1"' in clips_js and '"graded": true' in clips_js
    assert (p / f"engine/assets/clips/{c['clip']}-t1/grade.cube").is_file()
    plates_js = json.loads((p / "engine/assets/plates.js").read_text(encoding="utf-8").split("=", 1)[1].strip().rstrip(";"))
    assert all(v.get("graded") for v in plates_js.values())
    code, out = _run("-p", P, "edit", "look")
    assert code == 0 and out["mode"] == "clean-grade"
