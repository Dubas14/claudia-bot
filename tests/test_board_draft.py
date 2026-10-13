"""slop board draft / audit on synthetic projects (variable tempo, sections, aligned words)."""
import bisect
import io
import json
import statistics
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop.board import audit, draft  # noqa: E402
from slop.config import SlopError  # noqa: E402


@pytest.fixture()
def proj(tmp_path):
    return synth.make_project(tmp_path)


def _beats(p):
    B = synth.load(p, "analysis/beats.json")
    return sorted(B["beats"]), B


def test_draft_tiles_on_beats_with_paced_sections(proj):
    out = draft.run(proj, pace="director")          # EV's measured cut (a studio project now drafts at the Studio pace)
    S = synth.load(proj, "board/shots.json")
    shots = S["shots"]
    beats, B = _beats(proj)
    assert shots[0]["t0"] == 0 and abs(shots[-1]["t1"] - B["duration"]) < 1e-6
    for a, b in zip(shots, shots[1:]):
        assert abs(a["t1"] - b["t0"]) < 1e-9
        i = bisect.bisect_left(beats, b["t0"])
        near = min(abs(beats[j] - b["t0"]) for j in (i - 1, i) if 0 <= j < len(beats))
        assert near <= 0.03 + 1e-9, b["id"]
    durs = [s["t1"] - s["t0"] for s in shots]
    bar = out["stats"]["bar_s"]
    assert 0.6 * bar <= statistics.median(durs) <= 1.4 * bar          # median ~ one bar

    def mean(prefix):
        d = [s["t1"] - s["t0"] for s in shots if s["section"].startswith(prefix)]
        return statistics.mean(d)
    assert mean("intro") <= 1.7 and mean("drop") <= 1.8 and mean("verse1") <= 1.9   # fast hook / verse 1 / drop
    assert mean("chorus1") >= 2.2                                                  # long sung windows
    assert mean("outro") > mean("chorus1")
    assert S["version"] == 1 and set(S) >= {"duration", "chapters", "shots", "seedance", "plates"}


def test_draft_lines_lead_tiers_budget(proj):
    out = draft.run(proj)
    S = synth.load(proj, "board/shots.json")
    shots = S["shots"]
    W = synth.load(proj, "analysis/words.json")
    # every line's first word starts inside a shot that types it; the first shot of each line carries a TODO graphic
    starts = [s["t0"] for s in shots]
    for line in W["lines"]:
        sh = shots[bisect.bisect_right(starts, line["t0"]) - 1]
        assert line["line"] in [t["line"] for t in sh["type"]]
    assert all(s["lines"] == sorted({t["line"] for t in s["type"]}) for s in shots)
    # lead share inside the 70-85 % band, first frame has her, sung shots have her
    share = out["stats"]["lead_share"]
    assert 0.70 <= share <= 0.85
    assert shots[0]["lead_on_screen"]
    assert all(s["lead_on_screen"] for s in shots if s["motion_tier"] == "sung")
    # tiers: sung only in choruses, motion only in intro/drop/chorus, 2.5D elsewhere
    for s in shots:
        if s["motion_tier"] == "sung":
            assert s["section"].startswith("chorus")
        if s["motion_tier"] == "motion":
            assert s["section"].split("1")[0] in ("intro", "drop", "chorus")
    assert any(s["motion_tier"] == "sung" for s in shots) and any(s["motion_tier"] == "motion" for s in shots)
    # budget: planned clip seconds + 60 % cover allowance on sung <= budget
    st = out["stats"]
    assert st["planned_clip_s"] + st["cover_allowance_s"] <= st["budget_motion_s"] + 1e-6
    for c in S["seedance"]:
        assert 4 <= c["duration"] <= 8
        assert "TODO" not in json.dumps(c)                 # gen drafts the screenplay; the board holds the command
        assert c["cmd"].startswith("slop -p ") and f" clip new {c['shots'][0]} --kind {c['kind']} --id {c['clip']} " in c["cmd"]
        assert f"--song-t0 {round(c['song_t0'], 4)} --duration {c['duration']}" in c["cmd"]
        assert f"--t0 {round(c['needed'][0], 4)} --t1 {round(c['needed'][1], 4)}" in c["cmd"]
        if c["kind"] == "sung":
            assert c["words"]
            assert all(not (w["t0"] + .01 < c["song_t0"] < w["t1"] - .01) for w in W["words"])
        ids = c["shots"]
        assert all(next(s for s in shots if s["id"] == i)["clip"] == c["clip"] for i in ids)
    # 2.5D treatments never repeat back to back; TODO markers for the lead
    fam = [s["treatment"] for s in shots if s["motion_tier"] == "plate3d"]
    assert all(f for f in fam) and all(a != b for a, b in zip(fam, fam[1:]))
    assert all(s["framing"] == "TODO" and s["set"] == "TODO" for s in shots)


def test_draft_is_deterministic_and_never_clobbers(proj):
    draft.run(proj)
    first = (proj / "board/shots.json").read_text(encoding="utf-8")
    with pytest.raises(SlopError, match="already exists"):
        draft.run(proj)
    r = draft.run(proj, force=True)
    assert r["backup"] and Path(r["backup"]).is_file()
    assert (proj / "board/shots.json").read_text(encoding="utf-8") == first


def test_draft_zero_budget_quick_tier(tmp_path):
    p = synth.make_project(tmp_path, tier="quick", motion_s=0)
    draft.run(p)
    S = synth.load(p, "board/shots.json")
    assert not S["seedance"]
    assert all(s["motion_tier"] == "plate3d" for s in S["shots"])
    assert all("img_prompt" in s and "mj_prompt" not in s for s in S["shots"])


def test_draft_instrumental_without_sections_or_words(tmp_path):
    p = synth.make_project(tmp_path, hits=False)
    (p / "analysis/words.json").unlink()
    B = synth.load(p, "analysis/beats.json")
    B["sections"] = []
    synth.write_json(p / "analysis/beats.json", B)
    out = draft.run(p)
    S = synth.load(p, "board/shots.json")
    assert S["shots"] and all(not s["type"] for s in S["shots"]) and "warning" in out["text"]
    rep = audit.audit(p)
    assert all(rep["gates"][g]["ok"] for g in ("tile", "cuts", "words_typed", "lead_share", "treatments"))


def test_audit_draft_fails_only_todo_then_passes_when_filled(proj):
    draft.run(proj)
    r = audit.run(proj)
    assert not r["ok"] and r["failed"] == ["graphics", "todo"]
    rep = synth.load(proj, "board/audit.json")
    assert rep["gates"]["todo"]["fails"] and rep["gates"]["cuts"]["ok"]
    S = synth.fill_todos(synth.load(proj, "board/shots.json"))
    (proj / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    r = audit.run(proj)
    assert r["ok"], r["text"]
    assert "ALL GATES PASS" in r["text"]


def _filled(proj):
    draft.run(proj)
    S = synth.fill_todos(synth.load(proj, "board/shots.json"))
    return S


def _audit_with(proj, S):
    (proj / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    return audit.audit(proj)


def test_audit_catches_each_gate(proj):
    base = _filled(proj)
    shots = base["shots"]

    S = json.loads(json.dumps(base))           # off-beat cut + gap
    S["shots"][5]["t0"] += 0.2
    rep = _audit_with(proj, S)
    assert not rep["gates"]["cuts"]["ok"] and not rep["gates"]["tile"]["ok"]

    S = json.loads(json.dumps(base))           # a line's words not typed
    i = next(k for k, s in enumerate(shots) if s["type"])
    S["shots"][i]["type"] = []
    assert not _audit_with(proj, S)["gates"]["words_typed"]["ok"]

    S = json.loads(json.dumps(base))           # lead share
    for s in S["shots"]:
        s["lead_on_screen"] = False
    assert not _audit_with(proj, S)["gates"]["lead_share"]["ok"]

    S = json.loads(json.dumps(base))           # treatments: missing and repeated
    p3 = [s for s in S["shots"] if s["motion_tier"] == "plate3d"]
    p3[1]["treatment"] = p3[0]["treatment"]
    p3[2]["treatment"] = None
    fails = _audit_with(proj, S)["gates"]["treatments"]["fails"]
    assert any("same treatment" in f for f in fails) and any("needs a treatment" in f for f in fails)

    S = json.loads(json.dumps(base))           # a plate on two separate moments
    p3 = [s for s in S["shots"] if s["motion_tier"] == "plate3d"]
    p3[4]["plate"] = p3[0]["plate"]
    assert not _audit_with(proj, S)["gates"]["plates_unique"]["ok"]

    S = json.loads(json.dumps(base))           # clip window words and length
    c = next(c for c in S["seedance"] if c["kind"] == "sung")
    c["words"] = "something else entirely"
    c["duration"] = 11
    fails = _audit_with(proj, S)["gates"]["clip_windows"]["fails"]
    assert any("exactly the words" in f for f in fails) and any("must be 4-8" in f for f in fails)

    S = json.loads(json.dumps(base))           # TODO left
    S["shots"][3]["action"] = "TODO later"
    assert not _audit_with(proj, S)["gates"]["todo"]["ok"]


def test_audit_budget_and_banned_words(tmp_path):
    p = synth.make_project(tmp_path, motion_s=60, banned=["catwalkz"])
    S = _filled(p)
    S["shots"][2]["action"] = "she walks the Catwalkz at dawn"
    pj = synth.load(p, "project.json")
    pj["budget"]["motion_s"] = 10
    (p / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    rep = _audit_with(p, S)
    assert not rep["gates"]["motion_budget"]["ok"]
    assert not rep["gates"]["banned"]["ok"] and "s003.action" in rep["gates"]["banned"]["fails"][0]


def test_cli_json_contract(proj, monkeypatch):
    from slop import cli
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", "--project", str(proj), "board", "draft"])
    out = json.loads(buf.getvalue())
    assert code == 0 and out["ok"] and out["stats"]["shots"] > 10 and "text" in out
    buf = io.StringIO()
    with redirect_stdout(buf):                 # flags after the action work too; a failing gate exits 1
        code = cli.main(["board", "audit", "-p", str(proj), "--json"])
    out = json.loads(buf.getvalue())
    assert code == 1 and out["ok"] is False and out["failed"] == ["graphics", "todo"]
