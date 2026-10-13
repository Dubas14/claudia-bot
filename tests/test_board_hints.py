"""Review fixes for the board commands: next-step hints that cannot pass the gates when pasted word for word, placeholder
text refused everywhere, numeric `word` params, the engine's anchor/time grammar, tier paces for docs/40 §6.1 blocks,
`board fill --check` / TSV quoting, the audit's mtime after a clock jump, plates/look hints and font checks.
Synthetic projects only; no network."""
from __future__ import annotations

import bisect
import io
import json
import os
import re
import shlex
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop import cli  # noqa: E402
from slop.board import audit, devices, draft, plates, shotedit  # noqa: E402
from slop.board.common import TIER_PACE, placeholder  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.edit import look  # noqa: E402


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue())


def _board(p):
    return synth.load(p, "board/shots.json")


def _bytes(p):
    return (p / "board/shots.json").read_bytes()


def _filled(tmp_path, **kw):
    p = synth.make_project(tmp_path, **kw)
    draft.run(p)
    S = synth.fill_todos(_board(p))
    synth.write_json(p / "board/shots.json", S)
    return p, S


def commands_in(text: str) -> list[str]:
    """Every `slop -p …` command a hint text prints, cut where the prose resumes (outside quotes: a backtick, ' (' or
    ' — ', or the end of the line)."""
    out = []
    for m in re.finditer(r"slop -p ", text):
        s, q, i = text[m.start():], None, 0
        while i < len(s):
            c = s[i]
            if q:
                q = None if c == q else q
            elif c in "'\"":
                q = c
            elif c in "`\n" or s.startswith(" (", i) or s.startswith(" — ", i) or s.startswith("; ", i):
                break
            i += 1
        out.append(s[:i].rstrip(" .;"))
    return list(dict.fromkeys(out))


def run_cmd(cmd: str) -> tuple[int, dict]:
    argv = shlex.split(cmd)
    assert argv[0] == "slop", cmd
    return _run(*argv[1:])


# ------------------------------------------------------------------------------------------------ hints word for word
def test_hints_pasted_word_for_word_never_pass_the_gates(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    r = draft.run(p)
    before = _bytes(p)
    tried: set[str] = set()
    hint_texts = [r["text"]]
    for _round in range(3):
        code, rep = _run("-p", str(p), "board", "audit")
        assert code == 1 and not rep["ok"]
        full = json.loads((p / "board/audit.json").read_text(encoding="utf-8"))
        hint_texts += [f for g in full["gates"].values() for f in g["fails"]]
        cmds = [c for t in hint_texts for c in commands_in(t)        # (the lead-share note's --no-lead is a real fix)
                if re.search(r" board (set|device add) ", c) and c not in tried and not c.endswith("--no-lead")]
        if not cmds:
            break
        for c in cmds:
            tried.add(c)
            assert "<" in c, c                              # every hint carries a <…> marker to replace
            code, out = run_cmd(c)
            assert code == 1, (c, out)                      # …which is refused as it stands
            assert _bytes(p) == before, c                   # and nothing was written
            hint_texts.append(out.get("error", ""))
        hint_texts += [shotedit.todo_summary(shotedit.Ctx(p))[2]]
    kinds = {re.search(r" board (set|device add) ", c).group(1) for c in tried}
    assert kinds == {"set", "device add"}, tried            # both the todo and the graphics hints were tried
    code, rep = _run("-p", str(p), "board", "approve", "--note", "pasted hints")
    assert code == 1 and "todo" in rep["error"] and "graphics" in rep["error"]


def test_placeholder_text_is_refused_by_set_fill_device_and_the_audit(tmp_path):
    p, S = _filled(tmp_path, tier="quick")
    assert audit.audit(p)["ok"]
    sid = S["shots"][1]["id"]
    before = _bytes(p)
    for bad in ({"set": "…"}, {"set": "..."}, {"action": "<what happens, one sentence>"}, {"set": "TODO"},
                {"img_prompt": "medium shot of {lead} in <the place>"}, {"framing": "<ECU|CU|MS|WS>"},
                {"type_placement": "<left|right>", "line": S["shots"][1]["lines"][0] if S["shots"][1]["lines"] else 0},
                {"camera": "…"}, {"treatment": "<family>"}):
        with pytest.raises(SlopError):
            shotedit.cmd_set(p, sid, bad)
        assert _bytes(p) == before, bad
    for rows in (["…"], ["<row 1>"], ["REAL", "..."]):
        code, out = _run("-p", str(p), "board", "device", "add", sid, "--kind", "callout", "--param",
                         "rows=" + json.dumps(rows))
        assert code == 1 and "placeholder" in out["error"], rows
    assert _bytes(p) == before
    f = tmp_path / "fill.jsonl"
    f.write_text(json.dumps({"id": sid, "set": "…"}) + "\n", encoding="utf-8")
    with pytest.raises(SlopError, match="placeholder"):
        shotedit.cmd_fill(p, str(f))
    # the same text written straight into shots.json: the todo and devices gates fail with the shot named
    S = _board(p)
    S["shots"][1]["set"] = "…"
    S["shots"][2]["action"] = "<what happens>"
    S["shots"][3]["devices"] = [{"kind": "callout", "key": "B", "params": {"beat": 1, "rows": ["…"]}}]
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    todo = " | ".join(rep["gates"]["todo"]["fails"])
    assert not rep["gates"]["todo"]["ok"] and f"{sid}.set" in todo and S["shots"][2]["id"] + ".action" in todo
    assert rep["gates"]["todo"]["info"]["placeholders"] == 2
    assert not rep["gates"]["devices"]["ok"] and S["shots"][3]["id"] in rep["gates"]["devices"]["fails"][0]
    # the catalogue example's own text is no graphic for this song
    S["shots"][3]["devices"] = [{"kind": "callout", "key": "B", "params": {"beat": 1, "rows": ["KEY · BRASS", "Ø 24 MM"]}}]
    S["shots"][1]["set"], S["shots"][2]["action"] = "a hall", "she turns"
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["gates"]["todo"]["ok"] and "catalogue example" in rep["gates"]["devices"]["fails"][0]
    assert placeholder("she waits…") is None and placeholder("a 5\" screen") is None      # real text passes


# ------------------------------------------------------------------------------------------------ numeric words
def test_word_params_stay_text_and_numbers_are_checked():
    pp = devices.parse_params(["word=13", "word_end=walk", "at=9.1", "until=shot.t1", "size=64", "rows=[\"A\"]",
                               "word=[4, 2]"])
    assert pp["word"] == [4, 2] and pp["word_end"] == "walk" and pp["at"] == "9.1" and pp["until"] == "shot.t1"
    assert pp["size"] == 64 and pp["rows"] == ["A"]
    assert devices.parse_params(["word=13"])["word"] == "13"
    assert devices.parse_params(['word="13"'])["word"] == "13"
    for bad in ("size=NaN", "size=Infinity", "x=-Infinity", "rows=[1, NaN]"):
        with pytest.raises(SlopError, match="NaN"):
            devices.parse_params([bad])
    e, w = devices.check_device({"kind": "callout", "key": "W", "params": {"word": 13, "rows": ["X"]}}, lines={0, 1, 2})
    assert e and "lyric line 13" in e[0] and "--param word=13" in e[0]
    e, w = devices.check_device({"kind": "callout", "key": "W", "params": {"word": 2, "rows": ["X"]}}, lines={0, 1, 2})
    assert not e and any("line 2's first word" in x for x in w)
    e, w = devices.check_device({"kind": "callout", "params": {"size": float("nan"), "rows": ["X"]}})
    assert any("NaN" in x for x in e)


def test_word_13_is_the_sung_word_on_the_board(tmp_path):
    """EV's "13 Mac minis": the aligner hears "Thirteen", lyrics/display.txt shows "13" — the engine matches the
    display token, and so does the check (no false "not sung in this shot")."""
    p = synth.make_project(tmp_path, tier="quick")
    W = synth.load(p, "analysis/words.json")
    w0 = W["words"][3]
    w0["w"] = "Thirteen"
    synth.write_json(p / "analysis/words.json", W)
    rows: dict = {}
    for w in W["words"]:
        rows.setdefault(w["line"], []).append("13" if w is w0 else w["w"])
    (p / "lyrics").mkdir(exist_ok=True)
    (p / "lyrics/display.txt").write_text("\n".join(" ".join(r) for _, r in sorted(rows.items())) + "\n",
                                          encoding="utf-8")
    draft.run(p)
    S = _board(p)
    sh = next(s for s in S["shots"] if s["t0"] <= w0["t0"] < s["t1"])
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "counter", "--param", "word=13",
                     "--param", "to=13", "--param", "label=MAC MINIS")
    assert code == 0, out
    d = _board(p)["shots"][S["shots"].index(sh)]["devices"][0]
    assert d["params"]["word"] == "13" and d["key"] == "W" and not any("not sung" in x for x in out["warnings"])
    rep = audit.audit(p)
    assert not any("not sung" in x and sh["id"] in x for x in rep["warnings"]), rep["warnings"]


# ------------------------------------------------------------------------------------------------ anchors / time keys
def test_anchor_and_time_grammar_follow_the_engine():
    g = devices.engine_grammar()
    assert g["source"].endswith("_base.js") and "center" in g["slots"] and "centre" not in g["slots"]
    assert "t" in g["time_keys"] and "t0" not in g["time_keys"] and {"label", "w", "h"} <= g["anchor_keys"]
    assert devices.parse_anchor("centre") == "center" and devices.parse_anchor("Top Left") == "top-left"
    assert devices.parse_anchor("label:the laptop") == {"label": "the laptop"}
    e, w = devices.check_device({"kind": "callout", "anchor": "centre", "params": {"rows": ["X"]}})
    assert not e and "write 'center'" in w[0]
    e, w = devices.check_device({"kind": "callout", "anchor": {"uv": [1.4, 1.2]}, "params": {"rows": ["X"]}})
    assert not e and "outside the image" in w[0]
    e, w = devices.check_device({"kind": "callout", "anchor": {"label": "a face", "w": 200, "h": 90},
                                 "at": {"t": 9.1}, "params": {"rows": ["X"]}})
    assert not e and not w
    for label in ("the lead", "her", "him", "singer", "the face", "head", "a woman"):
        e, w = devices.check_device({"kind": "cv.bracket", "anchor": label, "params": {"label": "X"}}, boxes={})
        assert not w, (label, w)
    e, w = devices.check_device({"kind": "cv.bracket", "anchor": "the phone", "params": {"label": "X"}}, boxes={})
    assert w and "plates box" in w[0]


# ------------------------------------------------------------------------------------------------ device add
def test_device_add_camera_line_example_key_and_hints(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    draft.run(p)
    S = _board(p)
    W = synth.load(p, "analysis/words.json")
    first = W["words"][0]
    sh = next(s for s in S["shots"] if s["t0"] <= first["t0"] < s["t1"])
    before = _bytes(p)
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "cam.punch", "--line",
                     str(first["line"]), "--param", "amp=0.02")
    assert code == 1 and "camera move" in out["error"] and "--line" in out["error"] and _bytes(p) == before
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "cam.punch", "--param", "amp=0.02")
    assert code == 0 and "the graphic for line" not in out["text"]
    # --example keeps the example's timing key (B) and says how to time it to the word instead
    code, out = _run("-p", str(p), "board", "device", "add", sh["id"], "--kind", "callout", "--example", "--line",
                     str(first["line"]), "--param", "rows=[\"LINE 01\", \"ROBOTS\"]")
    assert code == 0, out
    d = out["device"]
    assert d["key"] == "B" and d["params"]["beat"] == 1 and "word" not in d["params"]
    assert any("--key W" in n for n in out["notes"])
    # the next step: the next line's graphic (a <…> marker), and export before render stills
    assert "edit export --no-frames" in out["text"] and "render stills" in out["text"]
    assert out["text"].index("edit export --no-frames") < out["text"].index("render stills")
    assert "<what line" in out["next"]


# ------------------------------------------------------------------------------------------------ fill
def test_fill_check_next_is_the_fill_and_tsv_quoting(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    draft.run(p)
    S = _board(p)
    s0, s1, s2 = (s["id"] for s in S["shots"][:3])
    d = tmp_path / "my fills"
    d.mkdir()
    f = d / "board fill.tsv"
    f.write_text(f'id\tset\taction\n{s0}\t"a hall, quoted"\t"she says ""hi"""\n{s1}\ta 5" screen\tshe turns\n',
                 encoding="utf-8")
    r = shotedit.cmd_fill(p, str(f), check=True)
    assert r["next"] == f"{r['next'].split(' board fill ')[0]} board fill {shlex.quote(str(f))}"
    assert f"next: `{r['next']}`" in r["text"] and "<" not in r["next"]
    code, out = run_cmd(r["next"])                         # the hint runs as printed (a path with spaces)
    assert code == 0, out
    B = _board(p)
    assert B["shots"][0]["set"] == "a hall, quoted" and B["shots"][0]["action"] == 'she says "hi"'
    assert B["shots"][1]["set"] == 'a 5" screen'
    # every bad row is listed, the cell-count ones too
    f.write_text(f"id\tset\n{s0}\ta\tb\n{s1}\tc\td\n{s2}\t…\n", encoding="utf-8")
    with pytest.raises(SlopError) as e:
        shotedit.cmd_fill(p, str(f))
    msg = str(e.value)
    assert "row 2:" in msg and "row 3:" in msg and "row 4" in msg and "3 problem(s)" in msg
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit):
        cli.main(["board", "fill", "--help"])
    assert "REPLACES" in buf.getvalue()                    # the help says a devices column replaces the list


# ------------------------------------------------------------------------------------------------ pace
SECTIONS3 = [("intro", 0, 10), ("verse1", 10, 38), ("pre1", 38, 46), ("chorus1", 46, 68), ("verse2", 68, 92),
             ("pre2", 92, 100), ("chorus2", 100, 122), ("bridge", 122, 136), ("chorus3", 136, 164), ("outro", 164, 180)]
# docs/40 §6.1 as the review found it (the blocks leave out chorus_mid / chorus_last)
DOCS_QUICK = {"intro": 4, "hook": 4, "verse": 5, "verse_late": 5, "pre": 5, "chorus": 6, "post": 5, "bridge": 5,
              "break": 5, "drop": 4, "inst": 5, "outro": 7, "other": 5}
DOCS_STUDIO = {"intro": 2.5, "hook": 2.5, "verse": 2.5, "verse_late": 3, "pre": 2.5, "chorus": 3.5, "post": 3,
               "bridge": 3, "break": 3, "drop": 2.5, "inst": 3, "outro": 5, "other": 3}


def song3(root: Path, tier: str) -> Path:
    p = synth.make_project(Path(root), name=f"song3-{tier}", tier=tier, duration=180.0)
    beats = synth.beat_grid(180.0)
    B = synth.load(p, "analysis/beats.json")
    B["sections"] = [{"name": n, "t0": a, "t1": b, "energy": .5} for n, a, b in SECTIONS3]
    synth.write_json(p / "analysis/beats.json", B)
    words, lines, i = [], [], 0
    for li in range(39):
        t = beats[bisect.bisect_left(beats, 3.0 + li * 4.6)] + 0.02
        ws = [{"i": i + m, "w": synth.VERSE_WORDS[(m + li) % 8], "line": li, "t0": round(t + m * .3, 3),
               "t1": round(t + m * .3 + .24, 3), "conf": .9, "src": "w2v"} for m in range(6)]
        i += 6
        words += ws
        lines.append({"line": li, "text": " ".join(w["w"] for w in ws), "t0": ws[0]["t0"], "t1": ws[-1]["t1"]})
    synth.write_json(p / "analysis/words.json", {"words": words, "lines": lines, "gaps": []})
    return p


def test_docs_pace_blocks_give_the_tier_default(tmp_path):
    for tier, block in (("quick", DOCS_QUICK), ("studio", DOCS_STUDIO)):
        p = song3(tmp_path / tier, tier)
        default = draft.run(p)["stats"]
        pj = synth.load(p, "project.json")
        pj["board"] = {"pace": block}
        synth.write_json(p / "project.json", pj)
        r = draft.run(p, force=True)
        assert r["stats"]["pace"]["name"] == tier and "equals the preset" in r["stats"]["pace"]["source"]
        assert r["stats"]["shots"] == default["shots"], (tier, r["stats"]["shots"], default["shots"])
        assert r["stats"]["pace"]["values"]["chorus_mid"] == TIER_PACE[tier]["chorus"]
        # a block with its own chorus paces every chorus with it; other keys from the tier
        pj["board"] = {"pace": {"chorus": 4.5}}
        synth.write_json(p / "project.json", pj)
        r = draft.run(p, force=True)
        v = r["stats"]["pace"]["values"]
        assert v["chorus"] == v["chorus_mid"] == v["chorus_last"] == 4.5 and v["verse"] == TIER_PACE[tier]["verse"]
        pj["board"] = {"pace": tier}
        synth.write_json(p / "project.json", pj)
        assert draft.run(p, force=True)["stats"]["shots"] == default["shots"]
    # Director keeps EV's value for keys a block leaves out
    p = song3(tmp_path / "director", "director")
    pj = synth.load(p, "project.json")
    pj["board"] = {"pace": {"chorus": 3}}
    synth.write_json(p / "project.json", pj)
    v = draft.run(p)["stats"]["pace"]["values"]
    assert v["chorus"] == 3 and v["chorus_mid"] == draft.PACE["chorus_mid"]


def test_draft_notes_a_lead_share_above_the_band(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    r = draft.run(p)
    if r["stats"]["lead_share"] > 0.85:
        assert "above the 70–85 % band" in r["text"] and "--no-lead" in r["stats"]["lead_note"]
        cmd = commands_in(r["stats"]["lead_note"])[0]
        code, out = run_cmd(cmd)
        assert code == 0, out
        S = _board(p)
        share = sum(s["t1"] - s["t0"] for s in S["shots"] if s["lead_on_screen"]) / S["duration"]
        assert 0.70 <= share < r["stats"]["lead_share"]
    else:
        assert "lead_note" not in r["stats"]
    assert draft.lead_note(p, {"shots": [{"t0": 0, "t1": 1, "lead_on_screen": True}]}, {}) is not None
    assert draft.lead_note(p, {"shots": [{"t0": 0, "t1": 1, "lead_on_screen": True},
                                         {"t0": 1, "t1": 4, "lead_on_screen": False}]}, {}) is None


# ------------------------------------------------------------------------------------------------ audit mtime
def test_audit_after_a_clock_jump_fails_safe(tmp_path):
    from slop import core_cli
    p, S = _filled(tmp_path)
    shots = p / "board/shots.json"
    future = time.time() + 80                       # the board was saved before the wall clock jumped back
    os.utime(shots, (future, future))
    assert audit.run(p)["ok"]
    assert core_cli.board_audit_problem(p) is None  # the fresh audit counts
    assert (p / "board/audit.json").stat().st_mtime <= time.time() + 0.01      # never stamped in the future
    time.sleep(0.01)
    shotedit.cmd_set(p, S["shots"][0]["id"], {"camera": "static"})   # an edit AFTER the audit…
    assert core_cli.board_audit_problem(p) == "board/shots.json changed after the last audit"     # …is not audited
    assert core_cli.gate_problem(p, "board_approved")


# ------------------------------------------------------------------------------------------------ plates / look
def test_plates_hints_carry_the_project(tmp_path, monkeypatch):
    p, S = _filled(tmp_path)
    key = S["shots"][0]["plate"]
    big = synth.make_image(tmp_path / "src.png", 1280, 720, seed=3)      # wide, < 2000 px: Midjourney's SD warning

    def fake(url, dest, timeout=60.0):
        dest.write_bytes(big.read_bytes())
        return dest, "image/png"
    monkeypatch.setattr(plates, "_download", fake)
    r = plates.ingest_urls(p, ["https://cdn.example/r/a.png?sig=X"], key)
    assert "HD off" not in r["text"] and f"slop -p {shlex.quote(str(p))} plates sheet" in r["text"]
    r = plates.box(p, key, label="the laptop", uv="0.1,0.62,0.18,0.14")
    cmds = commands_in(r["text"])
    assert cmds and all(c.startswith("slop -p ") for c in cmds) and "edit export --no-frames" in cmds[0]
    assert "--anchor 'box:the laptop'" in r["text"]


def test_look_font_files_must_exist_and_be_ofl(tmp_path):
    p = synth.make_project(tmp_path)
    pj = synth.load(p, "project.json")
    pj["font_files"] = [{"family": "Ghost Sans", "file": "fonts/nope.ttf", "project": True}]
    synth.write_json(p / "project.json", pj)
    before = (p / "project.json").read_bytes()
    with pytest.raises(SlopError, match="does not exist"):
        look.cmd_set(p, font_lyric="ghost sans")
    (p / "fonts").mkdir()
    (p / "fonts/nope.ttf").write_bytes(b"\x00\x01\x00\x00not a licensed font")
    with pytest.raises(SlopError, match="Open Font License"):
        look.cmd_set(p, font_lyric="ghost sans")
    assert (p / "project.json").read_bytes() == before
    (p / "fonts/OFL.txt").write_text("Copyright 2026\nThis Font Software is licensed under the SIL Open Font License, "
                                     "Version 1.1.\n", encoding="utf-8")
    look.cmd_set(p, font_lyric="ghost sans")
    assert synth.load(p, "project.json")["look"]["fonts"]["lyric"] == "Ghost Sans"
