"""The board written with commands (board set / fill / device), the device schema and the devices gate, the engine's
treatment vocabulary in the audit, tier paces, plates ingest --url / plates box, look fonts, the style tail, and the
approval recorded with its coverage. Synthetic projects only; no network (the URL download is stubbed)."""
from __future__ import annotations

import bisect
import io
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop import cli  # noqa: E402
from slop.board import audit, devices, draft, plates, shotedit, vocab  # noqa: E402
from slop.board.common import engine_treatment, is_code  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.edit import export, look  # noqa: E402


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


def _drafted(tmp_path, pace=None, **kw):
    p = synth.make_project(tmp_path, **kw)
    draft.run(p, pace=pace)
    return p


def _board(p):
    return synth.load(p, "board/shots.json")


def _bytes(p):
    return (p / "board/shots.json").read_bytes()


# ------------------------------------------------------------------------------------------------ the 3-minute song
SECTIONS3 = [("intro", 0, 10), ("verse1", 10, 38), ("pre1", 38, 46), ("chorus1", 46, 68), ("verse2", 68, 92),
             ("pre2", 92, 100), ("chorus2", 100, 122), ("bridge", 122, 136), ("chorus3", 136, 164), ("outro", 164, 180)]


def song3(root: Path, tier: str, n_lines: int = 39, step: float = 4.6) -> Path:
    """A synthetic 3-minute song with 39 lyric lines (one every ≈ 4.6 s, like EV), EV-like sections."""
    p = synth.make_project(Path(root), name=f"song3-{tier}", tier=tier, duration=180.0)
    beats = synth.beat_grid(180.0)
    B = synth.load(p, "analysis/beats.json")
    B["sections"] = [{"name": n, "t0": a, "t1": b, "energy": .5} for n, a, b in SECTIONS3]
    synth.write_json(p / "analysis/beats.json", B)
    words, lines, i = [], [], 0
    for li in range(n_lines):
        t = beats[bisect.bisect_left(beats, 3.0 + li * step)] + 0.02
        ws = [{"i": i + m, "w": synth.VERSE_WORDS[(m + li) % 8], "line": li, "t0": round(t + m * .3, 3),
               "t1": round(t + m * .3 + .24, 3), "conf": .9, "src": "w2v"} for m in range(6)]
        i += 6
        words += ws
        lines.append({"line": li, "text": " ".join(w["w"] for w in ws), "t0": ws[0]["t0"], "t1": ws[-1]["t1"]})
    synth.write_json(p / "analysis/words.json", {"words": words, "lines": lines, "gaps": []})
    return p


def test_tier_pace_defaults_on_a_three_minute_song(tmp_path):
    got = {}
    for tier in ("quick", "studio", "director"):
        p = song3(tmp_path, tier)
        r = draft.run(p)
        got[tier] = r["stats"]
        assert r["stats"]["pace"]["name"] == tier and "pace:" in r["text"], r["text"]       # the draft prints its pace
        if tier != "director":
            assert f"tier {tier} default (docs/40 §6.1)" in r["text"]
    # docs/40 §6.1: quick ≈ 44 shots, studio ≈ 59, director ≈ 82 (synthetic 3-min, 39 lines)
    assert 36 <= got["quick"]["shots"] <= 50, got["quick"]["shots"]
    assert 52 <= got["studio"]["shots"] <= 66, got["studio"]["shots"]
    assert 76 <= got["director"]["shots"] <= 92, got["director"]["shots"]
    assert got["quick"]["shots"] < got["studio"]["shots"] < got["director"]["shots"]
    assert got["quick"]["mean_s"] >= 3.8 and 2.7 <= got["studio"]["mean_s"] <= 3.6 and got["director"]["mean_s"] <= 2.4
    # the floor: one shot per lyric line wherever a beat allows it
    assert got["quick"]["shots"] >= 39


def test_pace_sources_override_order(tmp_path):
    p = song3(tmp_path, "quick")
    r = draft.run(p, pace="director")
    assert r["stats"]["pace"]["name"] == "director" and "--pace director" in r["stats"]["pace"]["source"]
    pj = synth.load(p, "project.json")
    pj["board"] = {"pace": "studio"}
    synth.write_json(p / "project.json", pj)
    r = draft.run(p, force=True)
    assert r["stats"]["pace"]["name"] == "studio" and 'board.pace "studio"' in r["stats"]["pace"]["source"]
    pj["board"] = {"pace": {"verse": 9}}
    synth.write_json(p / "project.json", pj)
    r = draft.run(p, force=True)
    assert r["stats"]["pace"]["name"] == "custom" and r["stats"]["pace"]["values"]["verse"] == 9
    from slop.board.common import TIER_PACE
    assert r["stats"]["pace"]["values"]["intro"] == TIER_PACE["quick"]["intro"]   # the tier's preset for the rest
    for bad in ({"pace": {"verse": "fast"}}, {"pace": {"versse": 2}}, {"pace": "slow"}):
        pj["board"] = bad
        synth.write_json(p / "project.json", pj)
        with pytest.raises(SlopError, match="pace"):
            draft.run(p, force=True)
    code, out = _run("-p", str(p), "board", "draft", "--force", "--pace", "quick")
    assert code == 0 and out["stats"]["pace"]["name"] == "quick"


# ------------------------------------------------------------------------------------------------ board set
def test_set_validates_writes_and_is_idempotent(tmp_path):
    p = _drafted(tmp_path, tier="quick")
    S = _board(p)
    s1, s2 = S["shots"][0]["id"], S["shots"][1]["id"]
    r = shotedit.cmd_set(p, s1, {"set": "a glass lobby at night", "framing": "close-up", "action": "she turns to the lens",
                                 "img_prompt": "close-up of {lead}, a glass lobby at night, the left third empty",
                                 "camera": "slow push", "treatment": "LS (rack)", "transition_in": "whip left",
                                 "lead": "yes", "subject_uv": "0.4,0.1,0.3,0.8"})
    sh = _board(p)["shots"][0]
    assert sh["framing"] == "CU" and sh["set"] == "a glass lobby at night" and sh["treatment"] == "LS (rack)"
    assert sh["transition_in"] == "whip left" and sh["lead_on_screen"] is True and sh["subject_uv"] == [0.4, 0.1, 0.3, 0.8]
    assert "mj_prompt" not in sh and sh["img_prompt"].startswith("close-up of {lead}")
    assert set(r["changed"][s1]) >= {"set", "framing", "action", "img_prompt", "treatment"}
    again = shotedit.cmd_set(p, s1, {"framing": "CU", "set": "a glass lobby at night"})
    assert again["changed"] == {} and "no change" in again["text"]
    before = _bytes(p)
    for bad, msg in (({"framing": "XL"}, "framing 'XL'"), ({"treatment": "sparkles"}, "not one the engine knows"),
                     ({"transition_in": "teleport"}, "transition 'teleport'"), ({"lead": "maybe"}, "not yes/no"),
                     ({"subject_uv": "1,1,1,1"}, "u,v,w,h"), ({"set": "TODO later"}, "TODO"),
                     ({"img_prompt": "close-up of {a|b}"}, "brace"),
                     ({"img_prompt": "x", "mj_prompt": "y"}, "not both")):
        with pytest.raises(SlopError, match=re.escape(msg)):
            shotedit.cmd_set(p, s2, {"set": "fine", **bad})
        assert _bytes(p) == before, bad                                      # a failed command changes nothing
    # several shots at once (a range), but never one prompt on several shots
    ids = [s["id"] for s in S["shots"][2:5]]
    r = shotedit.cmd_set(p, f"{ids[0]}-{ids[-1]}", {"camera": "static", "lead": False})
    assert r["shots"] == ids and all(_board(p)["shots"][k]["camera"] == "static" for k in (2, 3, 4))
    with pytest.raises(SlopError, match="one shot at a time"):
        shotedit.cmd_set(p, f"{ids[0]},{ids[1]}", {"img_prompt": "wide shot of a hall"})
    with pytest.raises(SlopError, match="no shot 's999'"):
        shotedit.cmd_set(p, "s999", {"set": "x"})
    with pytest.raises(SlopError, match="nothing to set"):
        shotedit.cmd_set(p, s1, {})


def test_set_type_mode_holds_across_cuts(tmp_path):
    p = _drafted(tmp_path)
    S = _board(p)
    by_line: dict = {}
    for s in S["shots"]:
        for t in s["type"]:
            by_line.setdefault(t["line"], []).append(s["id"])
    li, sids = next((k, v) for k, v in by_line.items() if len(v) > 1)
    r = shotedit.cmd_set(p, sids[0], {"line": li, "type_mode": "mast", "type_placement": "right"})
    for s in _board(p)["shots"]:
        for t in s["type"]:
            if t["line"] == li:
                assert t["mode"] == "masthead" and t["placement"] == "right", s["id"]
    assert any("also changed" in n for n in r["notes"])
    multi = next((s for s in S["shots"] if len(s["type"]) > 1), None)
    if multi:
        with pytest.raises(SlopError, match="--line N"):
            shotedit.cmd_set(p, multi["id"], {"type_mode": "stack"})
    with pytest.raises(SlopError, match="type mode 'wobble'"):
        shotedit.cmd_set(p, sids[0], {"line": li, "type_mode": "wobble"})


# ------------------------------------------------------------------------------------------------ board fill
def _tsv(rows: list[dict], cols: list[str]) -> str:
    return "\n".join(["\t".join(cols)] + ["\t".join(str(r.get(c, "")) for c in cols) for r in rows]) + "\n"


FR = ["MS", "CU", "WS", "MCU", "FS", "MWS"]
WORDS = {"MS": "medium shot of", "CU": "close-up of", "WS": "wide shot of", "MCU": "medium close-up of",
         "FS": "full-length shot of", "MWS": "medium wide shot of"}


def fill_rows(S: dict) -> list[dict]:
    rows = []
    for i, s in enumerate(S["shots"]):
        fr = FR[i % len(FR)]
        who = "{far}" if fr in ("FS", "WS", "MWS") else "{lead}"
        subj = f"{who} standing in" if s["lead_on_screen"] else "an empty"
        rows.append({"id": s["id"], "set": f"a white hall, bay {i + 1}", "framing": fr,
                     "action": "she turns to the lens on the downbeat" if s["lead_on_screen"] else "the lights change",
                     "prompt": f"{WORDS[fr]} {subj} a vast white hall, bay {i + 1}, the right third empty, soft light"
                     if (s.get("img_prompt") or s.get("mj_prompt")) else "", "camera": "slow push"})
    return rows


def test_fill_tsv_is_atomic_and_jsonl_carries_devices(tmp_path):
    p = _drafted(tmp_path, tier="quick")
    S = _board(p)
    rows = fill_rows(S)
    cols = ["id", "set", "framing", "action", "prompt", "camera"]
    bad = [dict(r) for r in rows]
    bad[3]["framing"] = "SIDEWAYS"
    bad[5]["id"] = "s404"
    f = tmp_path / "fill.tsv"
    f.write_text(_tsv(bad, cols), encoding="utf-8")
    before = _bytes(p)
    with pytest.raises(SlopError) as e:
        shotedit.cmd_fill(p, str(f))
    msg = str(e.value)
    assert "nothing was changed" in msg and "row 5" in msg and "SIDEWAYS" in msg and "s404" in msg
    assert _bytes(p) == before
    f.write_text(_tsv(rows, cols), encoding="utf-8")
    r = shotedit.cmd_fill(p, str(f), check=True)
    assert r["check"] and _bytes(p) == before and r["rows"] == len(rows)
    code, out = _run("-p", str(p), "board", "fill", str(f))
    assert code == 0 and out["todo_shots"] == 0, out["text"]
    S2 = _board(p)
    assert all(s["set"].startswith("a white hall") and s["framing"] in FR for s in S2["shots"])
    assert all("TODO" not in (s.get("img_prompt") or "") for s in S2["shots"])
    # JSONL: one object per line, devices validated with the shot
    sid = S2["shots"][0]["id"]
    j = tmp_path / "fill.jsonl"
    j.write_text(json.dumps({"id": sid, "devices": [{"kind": "flap", "key": "W", "params": {"txt": "LATE"}}]}) + "\n",
                 encoding="utf-8")
    with pytest.raises(SlopError, match="param 'txt' is not read"):
        shotedit.cmd_fill(p, str(j))
    j.write_text("# the lead's graphics\n" + json.dumps({"id": sid, "transition": "match cut", "devices": [
        {"kind": "flap", "key": "B", "params": {"rows": [{"text": "LATE", "prev": "ON TIME"}]}}]}) + "\n", encoding="utf-8")
    r = shotedit.cmd_fill(p, str(j))
    sh = _board(p)["shots"][0]
    assert sh["transition_in"] == "match cut" and sh["devices"][0]["kind"] == "flap"
    j.write_text(json.dumps({"id": sid, "colour": "red"}) + "\n", encoding="utf-8")
    with pytest.raises(SlopError, match="unknown field"):
        shotedit.cmd_fill(p, str(j))


# ------------------------------------------------------------------------------------------------ devices
def test_device_registry_is_read_from_the_engine():
    reg = devices.registry()
    ks = devices.kinds()
    ddir = ROOT / "engine/src/devices"
    loaded = re.findall(r"'([\w.-]+\.js)'", (ddir / "index.js").read_text(encoding="utf-8"))
    registered = {m for f in loaded for m in re.findall(r"D\.register\('([^']+)'", (ddir / f).read_text(encoding="utf-8"))}
    assert set(ks) == registered | {f"cam.{c}" for c in ("punch", "shake", "ride", "impact", "whip", "snap")}
    assert len(ks) >= 41 and {"flap", "sheet", "cv.bracket", "callout", "cam.punch", "gauge"} <= set(ks)
    assert reg["readout"]["kind"] == "gauge" and reg["camera.punch"]["kind"] == "cam.punch"
    assert "txt" not in devices.allowed_params(reg["flap"]) and "rows" not in devices.allowed_params(reg["readout"])
    assert reg["flap"]["defaults"]["cw"] == 40 and reg["cam.punch"]["defaults"]["amp"] == 0.02
    assert reg["title.knockout"]["word_param"] is False
    # every device example in the storyboard and motion-design docs and the catalogue is one the engine draws
    fence = "`" * 3
    n = 0
    for doc in ("docs/40-storyboard.md", "docs/70-motion-design.md", "engine/DEVICES.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for b in re.findall(fence + r"json\n(.*?)\n" + fence, text, flags=re.S):
            try:
                d = json.loads(b)
            except ValueError:
                continue
            for dev in (d.get("devices") if "devices" in d else [d] if d.get("kind") else []) if isinstance(d, dict) else []:
                n += 1
                errs, _ = devices.check_device(dev)
                assert not errs, (doc, dev, errs)
    assert n >= 40


def test_check_device_errors_and_warnings():
    e, w = devices.check_device({"kind": "flap", "key": "Q", "word": "late", "params": {"txt": "A", "rows": [{"txt": 1}]},
                                 "at": {"beatz": 2}, "line": "1"}, lines={0, 1})
    joined = " | ".join(e)
    for frag in ("param 'txt'", "rows[].txt", "key 'Q'", "top-level field 'word'", "put it inside params", "beatz",
                 "line must be"):
        assert frag in joined, frag
    e, w = devices.check_device({"kind": "sparkles"})
    assert e and "unknown device kind" in e[0]
    e, w = devices.check_device({"kind": "cv.bracket", "anchor": "the phone", "key": "W", "params": {"word": "walk"}},
                                lines={0}, boxes={}, shot_words=["robots"])
    assert not e and any("the phone" in x for x in w) and any("not sung in this shot" in x for x in w)
    e, w = devices.check_device({"kind": "cv.bracket", "anchor": {"box": "the phone"}}, boxes={"the phone": [0, 0, .1, .1]})
    assert not e and not w
    assert devices.is_graphic({"kind": "callout"}) and not devices.is_graphic({"kind": "cam.punch"})


def test_device_add_rm_list_kinds(tmp_path):
    p = _drafted(tmp_path, tier="quick")
    S = _board(p)
    W = synth.load(p, "analysis/words.json")
    first = W["words"][0]
    li = first["line"]
    sh = next(s for s in S["shots"] if s["t0"] <= first["t0"] < s["t1"])
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "callout", "--line", str(li),
                     "--anchor", "uv:0.62,0.42", "--param", "rows=[\"LINE 01\", \"ROBOTS\"]")
    assert code == 0 and out["changed"], out
    dev = _board(p)["shots"][S["shots"].index(sh)]["devices"][0]
    assert dev["kind"] == "callout" and dev["line"] == li and dev["anchor"] == {"uv": [0.62, 0.42]}
    assert dev["params"]["word"] == [li, 0] and dev["key"] == "W"                       # enters on the line's first word
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "callout", "--line", str(li),
                     "--anchor", "uv:0.62,0.42", "--param", "rows=[\"LINE 01\", \"ROBOTS\"]")
    assert code == 0 and out["changed"] is False                                          # idempotent
    before = _bytes(p)
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "flap", "--param", "txt=LATE")
    assert code == 1 and "param 'txt'" in out["error"] and "flap · role hero" in out["error"]
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "callout", "--key", "X")
    assert code == 1 and "key 'X'" in out["error"]
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "callout", "--line", "99")
    assert code == 1 and "line 99" in out["error"]
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "callou")
    assert code == 1 and "did you mean 'callout'" in out["error"]
    assert _bytes(p) == before
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "counter", "--example")
    assert code == 1 and "catalogue example" in out["error"] and "label" in out["error"]   # its text is not this song's
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "counter", "--example", "--param",
                     "label=ROBOTS COUNTED")
    assert code == 0 and _board(p)["shots"][S["shots"].index(sh)]["devices"][1]["params"]["to"] == 2400
    code, out = _run("-p", str(p), "board", "device", "list", sh["id"])
    assert code == 0 and "callout" in out["text"] and "counter" in out["text"] and "ERROR" not in out["text"]
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--replace", "1", "--kind", "counter", "--param",
                     "to=13", "--param", "size=40")                                       # change a device's params
    devs = _board(p)["shots"][S["shots"].index(sh)]["devices"]
    assert code == 0 and out["index"] == 1 and len(devs) == 2 and devs[1]["params"] == {"to": 13, "size": 40}
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--replace", "7", "--kind", "counter")
    assert code == 1 and "--replace 7" in out["error"]
    code, out = _run("-p", str(p), "board", "device", "rm", sh["id"], "--kind", "odometer")       # an alias of counter
    assert code == 0 and [d["kind"] for d in out["removed"]] == ["counter"]
    code, out = _run("-p", str(p), "board", "device", "rm", sh["id"])
    assert code == 1 and "--index" in out["error"]
    code, out = _run("board", "device", "kinds")
    assert code == 0 and len(out["kinds"]) == len(devices.kinds()) >= 41 and "cv.bracket" in out["text"]
    code, out = _run("board", "device", "kinds", "--kind", "readout")
    assert code == 0 and out["kind"] == "gauge" and "value" in out["defaults"]


# ------------------------------------------------------------------------------------------------ audit
def _filled(tmp_path, **kw):
    p = synth.make_project(tmp_path, **kw)
    draft.run(p)
    S = synth.fill_todos(_board(p))
    synth.write_json(p / "board/shots.json", S)
    return p, S


def test_devices_gate(tmp_path):
    p, S = _filled(tmp_path)
    rep = audit.audit(p)
    assert rep["gates"]["devices"]["ok"] and rep["gates"]["devices"]["info"]["devices"] > 0
    i = next(k for k, s in enumerate(S["shots"]) if s["devices"])
    S["shots"][i]["devices"] = [{"kind": "flap", "key": "W", "params": {"txt": "LATE"}},
                                {"kind": "hologram", "params": {}}, {"kind": "callout", "key": "Z", "params": {}}]
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    fails = " | ".join(rep["gates"]["devices"]["fails"])
    assert not rep["gates"]["devices"]["ok"] and "param 'txt'" in fails and "hologram" in fails and "key 'Z'" in fails
    assert fails.startswith(S["shots"][i]["id"])
    # a camera move is no explaining graphic
    S = synth.fill_todos(_board(p))
    for s in S["shots"]:
        s["devices"] = [{"kind": "cam.punch", "params": {"amp": 0.02}}] if s["lines"] else []
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["gates"]["devices"]["ok"] and not rep["gates"]["graphics"]["ok"]
    assert "board device add" in rep["gates"]["graphics"]["fails"][0]


def test_treatments_use_the_engines_vocabulary(tmp_path):
    assert vocab.treatments()["source"].endswith("treat.js")
    assert vocab.treatment_parse("LS (rack)") == ("rack", False) and vocab.treatment_parse("DI: contours")[0] == "contours"
    assert vocab.treatment_parse("DI+LS")[0] == "relight" and vocab.treatment_parse("sparkles") == ("push", True)
    assert engine_treatment({"treatment": "motion"}) == "motion" and is_code({"treatment": "none"})
    assert is_code({"treatment": "PM"}) and not is_code({"treatment": "push"})
    p, S = _filled(tmp_path)
    p3 = [s for s in S["shots"] if s["motion_tier"] == "plate3d"]
    # 'motion' (the engine's name) is a code-drawn shot: no plate needed, no false plates_unique failure
    p3[0]["treatment"], p3[0]["plate"] = "motion", None
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert not any(p3[0]["id"] in f for f in rep["gates"]["plates_unique"]["fails"]), rep["gates"]["plates_unique"]
    # prose and names that draw the same family back to back are a repeat
    p3[1]["treatment"], p3[2]["treatment"] = "LS (rack)", "rack-focus"
    synth.write_json(p / "board/shots.json", S)
    fails = audit.audit(p)["gates"]["treatments"]["fails"]
    assert any(p3[1]["id"] in f and p3[2]["id"] in f and "rack" in f for f in fails), fails
    # a name the engine does not know draws a push: a warning, not a failure (unless it repeats a push)
    p3[2]["treatment"] = "sparkles"
    p3[3]["treatment"] = "scan"
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["gates"]["treatments"]["ok"], rep["gates"]["treatments"]
    assert any("sparkles" in w and "push" in w for w in rep["warnings"])


def test_full_board_written_with_commands_passes_and_approval_records_coverage(tmp_path):
    p = _drafted(tmp_path, tier="quick")
    S = _board(p)
    f = tmp_path / "fill.tsv"
    f.write_text(_tsv(fill_rows(S), ["id", "set", "framing", "action", "prompt", "camera"]), encoding="utf-8")
    code, out = _run("-p", str(p), "board", "fill", str(f))
    assert code == 0, out
    W = synth.load(p, "analysis/words.json")
    starts = [s["t0"] for s in S["shots"]]
    firsts = {}
    for w in W["words"]:
        firsts.setdefault(w["line"], w)
    for li, w in sorted(firsts.items()):
        sid = S["shots"][bisect.bisect_right(starts, w["t0"]) - 1]["id"]
        code, out = _run("-p", str(p), "board", "device", "add", sid, "--kind", "cv.tag", "--line", str(li),
                         "--anchor", "uv:0.6,0.4", "--param", f"word={w['w']}", "--param",
                         f"rows=[\"LINE {li + 1:02d}\"]")
        assert code == 0, out
    code, out = _run("-p", str(p), "board", "audit")
    assert code == 0 and out["ok"], out["text"]
    assert out["gates"]["devices"] == "PASS" and out["gates"]["todo"] == "PASS"
    code, out = _run("-p", str(p), "board", "approve", "--note", "owner: go")
    assert code == 0 and out["approved"] and "board/shots.json" in out["covers"], out
    pj = synth.load(p, "project.json")
    assert pj["gates"]["board_approved"] is True
    assert pj["gates_meta"]["board_approved"]["covers"]["board/shots.json"] == out["covers"]["board/shots.json"]
    assert "owner: go" in (p / "DECISIONS.md").read_text(encoding="utf-8")
    # a later change makes the approval stale (coverage), and the board must pass again before it is re-recorded
    code, out = _run("-p", str(p), "board", "set", S["shots"][0]["id"], "--camera", "static")
    assert code == 0
    code, out = _run("-p", str(p), "gate", "board")
    assert code == 0 and out["current"] is False and out["stale"]


def test_audit_report_is_newer_than_the_board_even_when_the_clock_jumps_back(tmp_path):
    import os
    import time
    from slop import core_cli
    p, S = _filled(tmp_path)
    shots = p / "board/shots.json"
    future = time.time() + 120                     # the board was saved before the wall clock jumped back 2 minutes
    os.utime(shots, (future, future))
    r = audit.run(p)
    assert r["ok"], r["text"]
    rep = synth.load(p, "board/audit.json")
    assert (p / "board/audit.json").stat().st_mtime > shots.stat().st_mtime
    assert rep["shots_sig"] and core_cli.board_audit_problem(p) is None


# ------------------------------------------------------------------------------------------------ plates
def _with_picks(tmp_path, **kw):
    p, S = _filled(tmp_path, **kw)
    for i, key in enumerate(sorted({s["plate"] for s in S["shots"] if s.get("plate")})):
        synth.make_image(tmp_path / "dl" / f"{key}-1.png", 320, 180, seed=i)
    plates.ingest(p, str(tmp_path / "dl"))
    plates.pick(p, [], all_first=True)
    return p, S


def test_ingest_url_downloads_https_results(tmp_path, monkeypatch):
    p, S = _filled(tmp_path)
    key = S["shots"][0]["plate"]
    img = synth.make_image(tmp_path / "src.png", 320, 180, seed=7)
    seen = []

    def fake(url, dest, timeout=60.0):
        seen.append(url)
        dest.write_bytes(img.read_bytes())
        return dest, "image/png"
    monkeypatch.setattr(plates, "_download", fake)
    url = "https://d111.cloudfront.example/results/abc.png?Signature=SECRET&Key-Pair-Id=K"
    code, out = _run("-p", str(p), "plates", "ingest", "--url", url, "--plate", key)
    assert code == 0 and out["added"] == {key: [1]}, out
    idx = synth.load(p, "plates/cands/index.json")[key]["1"]
    assert idx["url"] == "https://d111.cloudfront.example/results/abc.png" and "SECRET" not in json.dumps(idx)
    assert "SECRET" not in json.dumps(out)
    code, out = _run("-p", str(p), "plates", "ingest", "--url", url, "--plate", key)
    assert code == 0 and out["duplicates"] == 1                                           # same bytes: skipped
    code, out = _run("-p", str(p), "plates", "ingest", "--url", "http://example.com/a.png", "--plate", key)
    assert code == 1 and "https" in out["error"]
    code, out = _run("-p", str(p), "plates", "ingest", "--url", url, "--plate", "p999")
    assert code == 1 and "not a plate" in out["error"]
    code, out = _run("-p", str(p), "plates", "ingest", "--url", url)
    assert code == 1 and "--plate" in out["error"]
    assert len(seen) == 2
    one = synth.make_image(tmp_path / "result (3).webp", 320, 180, seed=9)             # one local file for one plate
    code, out = _run("-p", str(p), "plates", "ingest", str(one), "--plate", key)
    assert code == 0 and out["added"] == {key: [2]}, out
    code, out = _run("-p", str(p), "plates", "ingest")
    assert code == 1 and "--url" in out["error"]


def test_box_reaches_window_plates(tmp_path):
    p, S = _with_picks(tmp_path)
    key = S["shots"][0]["plate"]
    code, out = _run("-p", str(p), "plates", "box", key, "--label", "a face", "--uv", "0.42,0.18,0.16,0.22")
    assert code == 0 and out["box"] == [0.42, 0.18, 0.16, 0.22]
    code, out = _run("-p", str(p), "plates", "box", key, "--label", "subject", "--uv", "0.35,0.1,0.3,0.85", "--score", "0.9")
    assert code == 0 and "subject box" in out["text"]
    for bad in (["--label", "x", "--uv", "0.9,0.9,0.5,0.5"], ["--label", "x"], ["--uv", "0.1,0.1,0.1,0.1"]):
        code, out = _run("-p", str(p), "plates", "box", key, *bad)
        assert code == 1, bad
    code, out = _run("-p", str(p), "plates", "box", key)
    assert code == 0 and set(out["boxes"]) == {"a face", "subject"}
    export.run(p, depth="off", frames=False)
    js = (p / "engine/assets/plates.js").read_text(encoding="utf-8")
    P = json.loads(js[js.index("=") + 1:].strip().rstrip(";"))
    assert P[key]["boxes"]["a face"] == [0.42, 0.18, 0.16, 0.22] and P[key]["subject_uv"] == [0.35, 0.1, 0.3, 0.85]
    # the audit and device add know the box: a label anchor resolves on that plate
    sh = next(s for s in _board(p)["shots"] if s.get("plate") == key)
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "cv.bracket", "--anchor", "box:a face",
                     "--param", "label=FACE")
    assert code == 0 and not out["warnings"], out
    code, out = _run("-p", str(p), "plates", "box", key, "--label", "a face", "--rm")
    assert code == 0 and out["changed"] and "a face" not in out["boxes"]


def test_book_appends_the_style_tail(tmp_path):
    p, S = _filled(tmp_path, tier="quick")
    pj = synth.load(p, "project.json")
    pj["look"]["style_tail"] = ["muted teal and clay palette", "35mm film grain --stylize 200"]
    synth.write_json(p / "project.json", pj)
    r = plates.book(p)
    jobs = synth.load(p, "plates/jobs.json")["jobs"]
    assert jobs and all(j["prompt"].endswith("muted teal and clay palette, 35mm film grain, no text, no letters, no logos")
                        for j in jobs), jobs[0]["prompt"]
    assert all(j["prompt"].count("35mm film grain") == 1 and "--stylize" not in j["prompt"] for j in jobs)
    assert r["style_tail"].startswith("muted teal") and any("'--' parameters" in w for w in r["warnings"])
    pj["look"]["style_tail"] = "muted teal and clay palette"
    synth.write_json(p / "project.json", pj)
    S = _board(p)
    S["shots"][0]["img_prompt"] = "medium shot of {lead} in a hall, muted teal and clay palette"
    synth.write_json(p / "board/shots.json", S)
    plates.book(p)
    j0 = next(j for j in synth.load(p, "plates/jobs.json")["jobs"] if j["plate"] == S["shots"][0]["plate"])
    assert j0["prompt"].count("muted teal and clay palette") == 1


# ------------------------------------------------------------------------------------------------ look fonts
def test_look_set_fonts(tmp_path):
    p = synth.make_project(tmp_path)
    code, out = _run("-p", str(p), "edit", "look", "set", "--font-lyric", "instrument serif", "--font-micro",
                     "JetBrainsMono-Regular.ttf", "--font-display", "DINish Condensed")
    assert code == 0, out
    f = synth.load(p, "project.json")["look"]["fonts"]
    assert f == {"lyric": "Instrument Serif", "micro": "JetBrains Mono", "display": "DINish Condensed"}
    assert "Instrument Serif" in out["text"]
    before = (p / "project.json").read_bytes()
    code, out = _run("-p", str(p), "edit", "look", "set", "--font-lyric", "Helvetica", "--accent", "#112233")
    assert code == 1 and "Helvetica" in out["error"] and "Space Grotesk" in out["error"]
    assert (p / "project.json").read_bytes() == before                        # nothing saved
    code, out = _run("-p", str(p), "edit", "look", "set", "--font-micro", "")
    assert code == 0 and "micro" not in synth.load(p, "project.json")["look"]["fonts"]
    pj = synth.load(p, "project.json")
    pj["font_files"] = [{"family": "My Grotesk", "file": "fonts/MyGrotesk.ttf", "project": True}]
    synth.write_json(p / "project.json", pj)
    code, out = _run("-p", str(p), "edit", "look", "set", "--font-lyric", "my grotesk")
    assert code == 1 and "does not exist" in out["error"]                          # the file must be there
    (p / "fonts").mkdir()
    (p / "fonts/MyGrotesk.ttf").write_bytes((ROOT / "engine/fonts/SpaceGrotesk-Variable.ttf").read_bytes())  # OFL
    code, out = _run("-p", str(p), "edit", "look", "set", "--font-lyric", "my grotesk")
    assert code == 0 and synth.load(p, "project.json")["look"]["fonts"]["lyric"] == "My Grotesk"


def test_cli_parses_every_new_command(tmp_path):
    from slop.cli import build_parser
    from slop.util import hoist_global_flags
    ap = build_parser()
    for line in ("board set s001 --set x --framing MS --action y --img-prompt z --camera push --treatment layers "
                 "--transition-in whip --lead --line 0 --type-mode subtitle --type-text t --type-placement left "
                 "--subject-uv 0,0,1,1 --notes n",
                 "board set s001 --no-lead --mj-prompt z", "board fill f.tsv --check",
                 "board device add s001 --kind callout --line 1 --anchor lead --key W --param a=1 --param b=2 "
                 "--params {} --at 1 --until 2 --priority 1 --example --replace 0",
                 "board device rm s001 --index 0 --all", "board device list", "board device kinds --kind flap",
                 "board draft --force --pace quick", "plates ingest --url https://x/y.png --plate p001",
                 "plates box p001 --label a --uv 0,0,1,1 --score 0.5 --rm",
                 "edit look set --font-lyric a --font-micro b --font-display c"):
        ap.parse_args(hoist_global_flags(["-p", str(tmp_path)] + line.split()))
