"""slop review: the take list and 3x2 scan sheets from the edit, the findings record (validated against the
safety-scan workflow's schema, merged per take), and the verdict."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")


def _take(path: Path, seconds: float = 2.0, color: str = "red") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=320x180:rate=24:duration={seconds}", "-vf", f"drawbox=c={color}:t=8",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.fixture()
def proj(tmp_path) -> Path:
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    (d / "clips").mkdir()
    for cid, n in (("c01", 2), ("c02", 1)):
        rec = {"id": cid, "kind": "motion", "song_t0": 0.0, "body": {"duration": 2},
               "takes": [{"file": f"clips/{cid}/take-{k + 1}.mp4", "status": "delivered"} for k in range(n)]}
        (d / "clips" / f"{cid}.json").write_text(json.dumps(rec), encoding="utf-8")
    edl = {"s001": {"segs": [{"t0": 0.0, "clip": "c01-t2", "in": 0.0}]},
           "s002": {"segs": [{"t0": 3.0, "clip": "c02-t1", "in": 0.0}, {"t0": 4.0, "clip": "c01-t2", "in": 1.0}]},
           "s003": {"plate": "grad-c"}}
    (d / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    return d


def test_schema_matches_the_workflow_file():
    from slop.review import scan as S
    js = S.schema_from_workflow()
    assert js is not None, "could not read SCHEMA from templates/workflows/safety-scan.js"
    assert js == S.SCHEMA                      # the fallback copy is the workflow's schema, exactly


def test_js_object_literal():
    from slop.review.scan import js_object_to_json
    assert js_object_to_json("{ a: 'x', b: [1, 2.5,], c: { d: true, 'e f': \"g\", h: 'it\\'s' }, }") == \
        {"a": "x", "b": [1, 2.5], "c": {"d": True, "e f": "g", "h": "it's"}}


def test_validate_reports_each_problem():
    from slop.review.scan import SCHEMA, validate
    ok = {"findings": [{"clip": "c01-t2", "time": 1.2, "severity": "fix", "kind": "glitch", "what": "a sixth finger"}],
          "checked": ["c01-t2"], "given": 1}
    assert validate(ok, SCHEMA) == []
    bad = {"findings": [{"clip": "", "severity": "high", "kind": "x"}, "nope"], "checked": "c01", "given": "1"}
    errs = validate(bad, SCHEMA)
    joined = "\n".join(errs)
    assert "$.findings[0] is missing \"what\"" in joined and "$.findings[0].clip must be a non-empty string" in joined
    assert "$.findings[0].severity must be one of block · fix · note" in joined
    assert "$.findings[1] must be an object" in joined and "$.checked must be a list" in joined
    assert "$.given must be a number" in joined


def test_used_takes_from_the_edit(proj):
    from slop.review.scan import used_plates, used_takes
    takes, probs = used_takes(proj)
    assert probs == []
    assert [(t["clip"], t["file"], t["shots"]) for t in takes] == [
        ("c01-t2", "clips/c01/take-2.mp4", ["s001", "s002"]), ("c02-t1", "clips/c02/take-1.mp4", ["s002"])]
    assert used_plates(proj) == [{"plate": "grad-c", "file": "plates/grad-c.jpg", "shots": ["s003"]}]


@needs_ffmpeg
def test_scan_sheets(proj):
    from PIL import Image
    from slop.review.scan import FRACS, LABEL_H, scan_sheets
    _take(proj / "clips" / "c01" / "take-2.mp4", 2.0)
    _take(proj / "clips" / "c02" / "take-1.mp4", 1.5, "blue")
    r = scan_sheets(proj, plates=True)
    assert r["ok"] and r["total"] == 2 and r["made"] == 2, r["text"]
    sheet = proj / "render" / "scan" / "c01-t2.jpg"
    assert Image.open(sheet).size == (3 * 640, 2 * (360 + LABEL_H))
    row = next(x for x in r["takes"] if x["clip"] == "c01-t2")
    assert row["times"] == [round(row["dur"] * f, 3) for f in FRACS] and row["sheet"] == "render/scan/c01-t2.jpg"
    lst = json.loads((proj / "render" / "scan-list.json").read_text(encoding="utf-8"))
    assert [x["clip"] for x in lst] == ["c01-t2", "c02-t1"] and lst[0]["file"] == "clips/c01/take-2.mp4"
    assert (proj / "render" / "scan" / "plates-01.jpg").is_file() and r["plates"][0]["plates"] == ["grad-c"]
    tpl = json.loads((proj / "render" / "scan" / "findings-template.json").read_text(encoding="utf-8"))
    # nothing is checked until someone looks: the names to look at are under to_check
    assert {k: tpl[k] for k in ("to_check", "findings", "checked", "given")} == {
        "to_check": ["c01-t2", "c02-t1", "plate:grad-c"], "findings": [], "checked": [], "given": 3}
    assert "render/scan/findings.json" in tpl["how"] and "only after you looked" in tpl["how"]
    again = scan_sheets(proj)
    assert again["made"] == 0 and again["kept"] == 2
    assert "slop review record render/scan/findings.json" in r["text"]
    assert f"cp {(proj / 'render/scan/findings-template.json').as_posix()} " in r["text"]      # absolute: any cwd works
    # a re-made take (its file changed) gets a new sheet, whatever the clock says
    _take(proj / "clips" / "remade.mp4", 1.0, "green")
    shutil.move(str(proj / "clips" / "remade.mp4"), str(proj / "clips" / "c02" / "take-1.mp4"))
    third = scan_sheets(proj)
    assert third["made"] == 1 and third["kept"] == 1


@needs_ffmpeg
def test_scan_sheets_reports_a_missing_take(proj):
    from slop.review.scan import scan_sheets
    _take(proj / "clips" / "c01" / "take-2.mp4", 1.0)
    r = scan_sheets(proj)
    assert not r["ok"] and any("c02-t1" in p and "missing" in p for p in r["problems"])
    assert "NOT SHEETED" in r["text"]


def _write(p: Path, doc) -> Path:
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_record_merge_and_verdict(proj, tmp_path):
    from slop.review.scan import record, status, used_takes
    from slop.util import atomic_write_json
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    assert not status(proj)["recorded"] and "no scan recorded yet" in status(proj)["text"]
    first = _write(tmp_path / "a.json", {"findings": [
        {"clip": "c01-t2", "time": 1.1, "severity": "block", "kind": "text", "what": "a readable logo on the cup"},
        {"clip": "c01-t2", "time": .4, "severity": "note", "kind": "soft", "what": "soft focus"}],
        "checked": ["c01-t2"], "given": 1})
    r = record(proj, first)
    assert r["ok"] and r["counts"] == {"block": 1, "fix": 0, "note": 1} and r["unchecked"] == ["c02-t1"]
    assert not r["release_ok"] and "NOT CLEAN" in r["text"] and "not checked yet" in r["text"]
    second = _write(tmp_path / "b.json", {"findings": [], "checked": ["c02-t1"], "given": 1})
    r = record(proj, second)
    assert r["checked"] == 2 and r["unchecked"] == [] and r["counts"]["block"] == 1
    assert "NOT CLEAN: 1 block" in r["text"] and "readable logo" in r["text"]
    # the re-scan of the re-made take replaces its findings
    fixed = _write(tmp_path / "c.json", {"findings": [
        {"clip": "c01-t2", "severity": "fix", "kind": "canon", "what": "earring on the wrong ear"}], "checked": ["c01-t2"], "given": 1})
    r = record(proj, fixed)
    assert r["counts"] == {"block": 0, "fix": 1, "note": 0} and r["release_ok"] and r["text"].endswith("(docs/80 §9.4) — the scan gate for the final render is met")
    scan = json.loads((proj / "render" / "scan" / "scan.json").read_text(encoding="utf-8"))
    assert len(scan["records"]) == 3 and all(f.get("id") for f in scan["findings"])
    st = status(proj)
    assert st["release_ok"] and st["checked"] == 2 and "CLEAN" in st["text"]


def _edl(proj: Path, edl: dict) -> None:
    (proj / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")


def test_record_the_workflow_result_and_stale_findings(proj, tmp_path):
    from slop.review.scan import record, status, used_takes
    from slop.util import atomic_write_json
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    wf = _write(tmp_path / "wf.json", {"ok": True, "error": None, "checked": 2, "of": 2, "counts": {"block": 1, "fix": 0, "note": 0},
                                       "unchecked": [], "findings": [
                                           {"clip": "c01-t2", "severity": "block", "kind": "text", "what": "a logo"}]})
    r = record(proj, wf)
    assert r["checked"] == 2 and r["unchecked"] == [] and r["complete"] and r["counts"]["block"] == 1
    # the edit cuts c01-t2 (it plays c02-t1 only): its block becomes stale and never counts as open
    _edl(proj, {"s002": {"segs": [{"t0": 3.0, "clip": "c02-t1", "in": 0.0}]}})
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    st = status(proj)
    assert st["counts"]["block"] == 0 and st["stale"] == 1 and st["release_ok"], st["text"]
    short = _write(tmp_path / "short.json", {"ok": False, "checked": 1, "of": 2, "unchecked": [{"slice": 1, "missing": 1}],
                                             "findings": []})
    r = record(proj, short)
    assert not r["complete"] and "did not check everything" in r["text"]


def test_a_workflow_result_from_a_smaller_list_clears_only_what_it_names(proj, tmp_path):
    """Reviewer repro: 2 takes in the list, a result {checked: 1, of: 1} used to clear both."""
    from slop.review.scan import record, status, used_takes
    from slop.util import atomic_write_json
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    old = _write(tmp_path / "old.json", {"ok": True, "checked": 1, "of": 1, "findings": [], "unchecked": []})
    r = record(proj, old)
    assert r["checked"] == 0 and r["unchecked"] == ["c01-t2", "c02-t1"] and not r["release_ok"] and not r["complete"]
    assert "covers 1 take(s), the edit plays 2" in r["text"] and "total 2" in r["text"] and "NOT CLEAN" in r["text"]
    named = _write(tmp_path / "named.json", {"ok": True, "checked": 1, "of": 1, "unchecked": [], "findings": [
        {"clip": "c02-t1", "severity": "note", "kind": "soft", "what": "soft focus"}]})
    r = record(proj, named)
    assert r["unchecked"] == ["c01-t2"] and not r["release_ok"]          # only the take its findings name
    # a result from a list that is not the edit's: a finding on a take the edit does not play
    other = _write(tmp_path / "other.json", {"ok": True, "checked": 2, "of": 2, "unchecked": [], "findings": [
        {"clip": "c07-t1", "severity": "note", "kind": "x", "what": "y"}]})
    r = record(proj, other)
    assert r["unchecked"] == ["c01-t2"] and "does not play" in r["text"]
    # a result that names the takes it covered counts exactly those
    full = _write(tmp_path / "full.json", {"ok": True, "checked": 2, "of": 2, "unchecked": [], "findings": [],
                                           "takes": ["c01-t2", "c02-t1"]})
    r = record(proj, full)
    assert r["unchecked"] == [] and r["release_ok"] and status(proj)["release_ok"]


def test_the_template_is_never_a_record(proj, tmp_path):
    """Reviewer repro: recording render/scan/findings-template.json unchanged passed the gate."""
    from slop.config import SlopError
    from slop.review.scan import FINDINGS, TEMPLATE, record, used_takes
    from slop.util import atomic_write_json
    takes = used_takes(proj)[0]
    atomic_write_json(proj / "render" / "scan-list.json", takes)
    tpl = {"how": "copy this file", "to_check": [t["clip"] for t in takes], "findings": [], "checked": [], "given": 2}
    atomic_write_json(proj / TEMPLATE, tpl)
    with pytest.raises(SlopError) as e:
        record(proj, proj / TEMPLATE)
    assert "is the template" in str(e.value) and f"cp {TEMPLATE} {FINDINGS}" in str(e.value)
    copy = _write(proj / FINDINGS, tpl)
    with pytest.raises(SlopError, match="unchanged copy of the template"):
        record(proj, copy)
    _write(proj / FINDINGS, {**tpl, "how": "edited"})
    with pytest.raises(SlopError, match='"checked" is empty'):
        record(proj, proj / FINDINGS)
    assert not (proj / "render" / "scan" / "scan.json").exists()
    # a copy with one take looked at records exactly that take
    r = record(proj, _write(proj / FINDINGS, {**tpl, "checked": ["c01-t2"]}))
    assert r["unchecked"] == ["c02-t1"] and not r["complete"] and not r["release_ok"]


def test_status_follows_the_edit_not_the_sheet_list(proj, tmp_path):
    """Reviewer repro: after the EDL moved from c01-t2 to the unscanned c01-t1, `review status` still said CLEAN while
    `slop status` said not scanned. Both now judge the edit as it is."""
    from slop import core_cli
    from slop.review.scan import record, status, used_takes
    from slop.util import atomic_write_json
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    r = record(proj, _write(tmp_path / "a.json", {"findings": [], "checked": ["c01-t2", "c02-t1"], "given": 2}))
    assert r["release_ok"] and status(proj)["release_ok"]
    assert core_cli.scan_state(proj)["problem"] is None
    edl = json.loads((proj / "edit" / "edl.json").read_text(encoding="utf-8"))
    edl["s001"]["segs"][0]["clip"] = "c01-t1"
    edl["s002"]["segs"][1]["clip"] = "c01-t1"
    _edl(proj, edl)
    st = status(proj)
    assert not st["release_ok"] and st["list_stale"] and st["step"] == "sheets", st["text"]
    assert "NOT CLEAN" in st["text"] and "slop review scan-sheets" in st["text"] and "new: c01-t1" in st["text"]
    assert core_cli.scan_state(proj)["problem"] is not None
    # re-sheeted (the list matches the edit again): c01-t1 is simply not checked yet
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    st = status(proj)
    assert not st["release_ok"] and st["unchecked"] == ["c01-t1"] and st["step"] == "record"
    assert core_cli.scan_state(proj)["problem"] is not None


def test_a_take_re_made_after_its_check_is_unchecked(proj, tmp_path):
    from slop.review.scan import record, status, used_takes
    from slop.util import atomic_write_json
    for rel in ("clips/c01/take-2.mp4", "clips/c02/take-1.mp4"):
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_bytes(b"take" * 100)
    atomic_write_json(proj / "render" / "scan-list.json", used_takes(proj)[0])
    r = record(proj, _write(tmp_path / "a.json", {"findings": [], "checked": ["c01-t2", "c02-t1"], "given": 2}))
    assert r["release_ok"]
    (proj / "clips" / "c02" / "take-1.mp4").write_bytes(b"a re-made take" * 50)        # same name, new file
    st = status(proj)
    assert not st["release_ok"] and st["remade"] == ["c02-t1"] and st["step"] == "sheets"
    assert "re-made after they were checked" in st["text"]
    r = record(proj, _write(tmp_path / "b.json", {"findings": [], "checked": ["c02-t1"], "given": 1}))
    assert r["release_ok"] and r["remade"] == []


def test_record_refuses_a_bad_file(proj, tmp_path):
    from slop.config import SlopError
    from slop.review.scan import record
    bad = _write(tmp_path / "bad.json", {"findings": [{"clip": "c01-t2", "severity": "critical", "kind": "x", "what": "y"}],
                                         "checked": ["c01-t2"]})
    with pytest.raises(SlopError) as e:
        record(proj, bad)
    msg = str(e.value)
    assert "does not match the scan schema" in msg and "severity must be one of block · fix · note" in msg
    assert 'missing "given"' in msg and "slop review record" in msg
    assert not (proj / "render" / "scan" / "scan.json").exists()
    (tmp_path / "broken.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(SlopError, match="not valid JSON"):
        record(proj, tmp_path / "broken.json")
    with pytest.raises(SlopError, match="cp render/scan/findings-template.json render/scan/findings.json"):
        record(proj, tmp_path / "absent.json")


def test_cli_register_and_router(proj, capsys, monkeypatch):
    from slop.review import cli
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--project", "-p")
    cli.register(ap.add_subparsers(dest="cmd"))
    a = ap.parse_args(["review", "status", "--project", str(proj)])
    out = a.func(a)
    assert out["ok"] and not out["recorded"] and "text" in out
    with pytest.raises(Exception, match="choose a step"):
        a = ap.parse_args(["review"])
        a.func(a)
    from slop import cli as router
    if "slop.review.cli" in router.MODULES:
        rc = router.main(["--json", "review", "status", "--project", str(proj)])
        d = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert rc == 0 and d["ok"] and d["takes"] == 2
