"""engine-devices: the data-driven default renderer (engine/src/shots.js) and the device library
(engine/src/devices/**), exercised in headless Chromium on the real engine page (engine/index.html through
slop.render's page spec) with a synthetic project (tests/fixtures/engine_devices/synth.py).

Checks: every registered device draws for sample params over a range of t without throwing (and puts ink on the frame);
same t → same pixels (devices and whole frames, also against a fresh page); the timing grammar (W/B/H/F/T) on an
accelerating beat map, numbers given as strings and words that are not sung in their shot; the per-frame element budget
(micro rows too); the flash rule (planned around the transitions); treatments never repeat back to back (on the family that
really draws); a transition that repeats the previous shot's is demoted; every sung token is drawn on its time (the lyric
gate); portrait frames keep the lyric and the devices inside the UI-safe margins; a project without detection boxes (what
`slop edit export` writes) still finds its subject; plate memos stay bounded; and `slop render info --json` reports every
repair the plan made and every device that throws.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"


def _synth():
    spec = importlib.util.spec_from_file_location("engine_devices_synth", ROOT / "tests" / "fixtures" / "engine_devices" / "synth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_engine():
    for f in ("index.html", "src/core.js", "src/timeline.js", "src/kinetic.js", "src/media.js", "src/shots.js", "src/devices/index.js"):
        if not (ENGINE / f).is_file():
            pytest.skip(f"engine file missing: engine/{f}")
    pytest.importorskip("PIL")
    pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    _need_engine()
    return _synth().build(tmp_path_factory.mktemp("devproj"))


def _open(p, pdir, **kw):
    from slop.render.browser import EnginePage
    from slop.render.project import page_spec
    try:
        return EnginePage(p, page_spec(pdir, **kw))
    except Exception as e:  # noqa: BLE001 — no browser on this machine
        pytest.skip(f"no headless browser: {e}")


@pytest.fixture(scope="module")
def pw():
    _need_engine()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def ep(pw, project):
    page = _open(pw, project["dir"])
    yield page
    page.close()


def js(ep, code, arg=None):
    return ep.page.evaluate(code, arg)


def _sh(project, sid):
    s = next(s for s in project["shots"] if s["id"] == sid)
    return {"id": s["id"], "t0": s["t0"], "t1": s["t1"], "lines": s["lines"], "framing": s.get("framing", "")}


# ------------------------------------------------------------------------------------------------- the library ---
def test_library_loads_and_claims_the_renderer(ep):
    info = js(ep, """() => ({kinds: DEV.kinds(), roles: Object.fromEntries(DEV.kinds().map(k => [k, DEV.get(k).role])),
        renderer: ENGINE.shotsRenderer, engineDevices: Object.keys(ENGINE.devices || {}), errors: window.DEV_ERRORS || [],
        scenes: SCENES.map(s => s.name)})""")
    assert info["renderer"] == "devices-v1", "shots.js must claim ENGINE.shotsRenderer (else the engine's stub renders)"
    drawable = [k for k, r in info["roles"].items() if r != "camera"]
    assert len(drawable) >= 30, f"only {len(drawable)} drawable devices: {drawable}"
    assert {"cam.punch", "cam.shake", "cam.ride", "cam.impact", "cam.whip", "cam.snap"} <= set(info["kinds"])
    missing = [k for k in drawable if k not in info["engineDevices"]]
    assert not missing, f"devices not registered with ENGINE.registerDevice: {missing}"
    assert info["scenes"][:13] == [f"s{i:02d}" for i in range(1, 14)] and "gap01" in info["scenes"], info["scenes"]
    assert not ep.errors, ep.errors


def test_aliases_and_engine_registry_interop(ep, project):
    r = js(ep, """async (sh) => {
      const kinds = DEV.kinds(), clash = Object.keys(DEV.ALIAS).filter(a => kinds.includes(a));
      const st = k => DEV.instance({kind: k}, sh).p;
      const c = document.createElement('canvas'); c.width = W; c.height = H; const o = c.getContext('2d', {willReadFrequently: true});
      const B = document.createElement('canvas'); B.width = W; B.height = H; const b = B.getContext('2d', {willReadFrequently: true});
      b.fillStyle = '#222'; b.fillRect(0, 0, W, H);
      await ENGINE.drawDevice({kind: 'thermo', params: {value: 120, max: 100, done: 'PINNED'}, at: {t0: sh.t0}}, {o, b, t: sh.t0 + .8, shot: sh, m: null, look: {}, accent: '#D97757'});
      const d = o.getImageData(0, 0, W, H).data; let n = 0; for (let i = 3; i < d.length; i += 16) if (d[i] > 8) n++;
      return {clash, thermo: st('thermo').style, dial: st('dial').style, receipt: st('receipt').style, ruler: st('ruler').style, beam: st('spec.beam').style,
        card: st('card').kind, det: st('det').style, viaEngine: n, unknown: DEV.instance({kind: 'no.such'}, sh).err || ''};
    }""", _sh(project, "s02"))
    assert not r["clash"], f"aliases shadowing a kind: {r['clash']}"
    assert (r["thermo"], r["dial"], r["receipt"], r["ruler"], r["beam"], r["card"], r["det"]) == ("thermo", "half", "receipt", "ruler", "beam", "card", "det")
    assert r["viaEngine"] > 50, "ENGINE.drawDevice must draw a library device"
    assert "DEVICES.md" in r["unknown"], "an unknown kind must say where the list is"


def test_kit_adapters_draw_synchronously(ep):
    """The second video's kit names (CV.lock/tag, UI.chip/chatbar, FLASH, TR, LY) work as SP chapter code calls them."""
    r = js(ep, """() => {
      const c = DEV.mk(W, H), o = c.getContext('2d', {willReadFrequently: true});
      const ink = () => { const d = o.getImageData(0, 0, W, H).data; let n = 0; for (let i = 3; i < d.length; i += 64) if (d[i] > 8) n++; o.clearRect(0, 0, W, H); return n; };
      const out = {fns: ['CV.bracket', 'CV.lock', 'CV.tag', 'UI.rr', 'UI.chip', 'UI.chatbar', 'FLASH.mono', 'FLASH.ok', 'TR.whip', 'TR.through', 'TR.flashCut', 'LY.sub']
        .filter(n => { const [a, b] = n.split('.'); return typeof window[a] !== 'object' || typeof window[a][b] !== 'function'; })};
      CV.lock(o, [800, 300, 200, 300], 5.0, 4.0, 4.5, {rows: ['MATCH', 'ID']}); out.lock = ink();
      CV.tag(o, 900, 500, ['ROW ONE'], 6.0, 4.0, {}); out.tag = ink();
      const box = UI.chip(o, 100, 100, 'LIVE', 5.0, 4.5, {}); out.chip = ink(); out.chipBox = box;
      UI.chatbar(o, 100, 800, 700, 'hello', 5.0, 4.0, 6.0, {}); out.chatbar = ink();
      out.alpha = o.globalAlpha; out.align = o.textAlign; out.transform = [...Object.values(o.getTransform().toJSON())].slice(0, 6);
      return out; }""")
    assert not r["fns"], f"kit names missing: {r['fns']}"
    assert r["lock"] > 20 and r["tag"] > 5 and r["chip"] > 5 and r["chatbar"] > 50, r
    assert r["chipBox"][0] == 100 and r["chipBox"][1] == 100
    assert r["alpha"] == 1 and r["align"] == "start", "the adapters must restore the canvas state before they return"


def test_devices_md_documents_every_kind_and_default(ep):
    doc = (ENGINE / "DEVICES.md").read_text(encoding="utf-8")
    reg = js(ep, "() => DEV.kinds().map(k => ({kind: k, defaults: Object.keys(DEV.get(k).defaults || {})}))")
    missing = []
    for r in reg:
        head = f"### `{r['kind']}`"
        if head not in doc:
            missing.append(head)
            continue
        sec = doc.split(head, 1)[1].split("\n### ", 1)[0]
        missing += [f"{r['kind']}.{k}" for k in r["defaults"] if f"`{k}`" not in sec and f"{k}`" not in sec]
    assert not missing, f"DEVICES.md is out of date: {missing}"
    for fam in js(ep, "() => DEV.treat.FAMS"):
        assert f"`{fam}`" in doc, fam
    for pre in js(ep, "() => Object.keys(DEV.trans.PRESETS).filter(p => p !== 'cut')"):
        assert f"`{pre}`" in doc, pre
    assert "lyrics-gate" not in doc and "slop render lyrics`" in doc, "the gate's command is `slop render lyrics`"
    assert "subject_uv" in doc and "detects no boxes by itself" in doc and "slop plates box" in doc


DRAW_ALL = """async (sh) => {
  const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
  const B = mk(), O = mk(), b = B.getContext('2d', {willReadFrequently: true}), o = O.getContext('2d', {willReadFrequently: true});
  const small = document.createElement('canvas'); small.width = 192; small.height = 108; const sg = small.getContext('2d', {willReadFrequently: true});
  const ink = () => { sg.clearRect(0, 0, 192, 108); sg.drawImage(O, 0, 0, 192, 108); const d = sg.getImageData(0, 0, 192, 108).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 8) n++; return n; };
  const out = {};
  for (const kind of DEV.kinds()) {
    const spec = DEV.get(kind), inst = DEV.instance(Object.assign({kind}, spec.example || {}), sh);
    if (inst.err) { out[kind] = {err: inst.err}; continue; }
    const ts = [inst.t0 - .1, inst.t0, inst.t0 + .5 / FPS, inst.t0 + 1 / FPS + .01, inst.t0 + .12, inst.t0 + .3, inst.t0 + .6, inst.t0 + 1.1,
      (sh.t0 + sh.t1) / 2, Math.min(inst.t1, sh.t1) - .01, sh.t1 + .3];
    let inked = 0, err = null;
    for (const t of ts) {
      b.reset(); o.reset(); b.fillStyle = '#000'; b.fillRect(0, 0, W, H); DEV.begin(t);
      const m = await MEDIA.drawShot(b, sh.id, t, {zoom: 1.06, cx: .5, cy: .5, flat: true});   // flat: the backdrop only
      const X = DEV.frame({t, sh, m, b, o, accent: '#D97757', flashOk: () => true}); X.lead = DEV.leadOf(m);
      try { await DEV.draw(o, b, inst, t, X); } catch (e) { err = String(e && e.stack || e); break; }
      inked += ink();
    }
    out[kind] = err ? {err} : {inked, role: spec.role, t0: inst.t0, t1: inst.t1, warn: inst.warn};
  }
  return out;
}"""


def test_every_device_renders_over_a_range_of_t(ep, project):
    res = js(ep, DRAW_ALL, _sh(project, "s02"))                       # a plate shot with lead/face/phone boxes and line 1
    errs = {k: v["err"] for k, v in res.items() if "err" in v}
    assert not errs, errs
    blank = [k for k, v in res.items() if v["role"] != "camera" and v["inked"] == 0]
    assert not blank, f"devices that never drew anything with their example params: {blank}"
    noisy = {k: v["warn"] for k, v in res.items() if v.get("warn")}
    assert not noisy, f"the registered examples must be clean entries: {noisy}"
    assert not ep.errors, ep.errors


DET = """async ([sh, kinds]) => {
  const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
  const B = mk(), O = mk(), b = B.getContext('2d', {willReadFrequently: true}), o = O.getContext('2d', {willReadFrequently: true});
  const fnv = c => { const d = c.getContext('2d').getImageData(0, 0, W, H).data; let h = 2166136261 >>> 0; for (let i = 0; i < d.length; i += 3) { h ^= d[i]; h = Math.imul(h, 16777619) >>> 0; } return h; };
  const shot = async (inst, t) => { b.reset(); o.reset(); b.fillStyle = '#000'; b.fillRect(0, 0, W, H); DEV.begin(t);
    const m = await MEDIA.drawShot(b, sh.id, t, {zoom: 1.06, flat: true}); const X = DEV.frame({t, sh, m, b, o, accent: '#D97757', flashOk: () => true}); X.lead = DEV.leadOf(m);
    await DEV.draw(o, b, inst, t, X); return [fnv(B), fnv(O)].join(':'); };
  const out = {};
  for (const kind of kinds) {
    const spec = DEV.get(kind), inst = DEV.instance(Object.assign({kind}, spec.example || {}), sh);
    const ta = inst.t0 + .27, tb = inst.t0 + 1.13;
    const a1 = await shot(inst, ta), _ = await shot(inst, tb), a2 = await shot(inst, ta), b1 = await shot(inst, tb);
    out[kind] = a1 === a2 && b1 === _ ? 'same' : `differs ${a1} ${a2} / ${_} ${b1}`;
  }
  return out;
}"""


def test_devices_are_deterministic(ep, project):
    kinds = js(ep, "() => DEV.kinds().filter(k => DEV.get(k).role !== 'camera')")
    res = js(ep, DET, [_sh(project, "s02"), kinds])
    bad = {k: v for k, v in res.items() if v != "same"}
    assert not bad, bad


# ------------------------------------------------------------------------------------------- the timing grammar ---
def test_timing_keys_on_an_accelerating_beat_map(ep, project):
    beats = project["beats"]
    s02, s03 = _sh(project, "s02"), _sh(project, "s03")
    ln1 = project["lines"][1]
    r = js(ep, """([s2, s3]) => {
      const kicks = (window.HITS.kick || []).filter(k => k >= s2.t0 - 1e-3 && k < s2.t1);
      const inst = DEV.instance({kind: 'gauge', key: 'T', params: {keys: [[0.25, 1], [0.75, 5]]}}, s3);
      const roundTrip = [3.3, 9.71, 17.02, 26.5].map(x => Math.abs(DEV.tAtBeat(bpOf(x)) - x));
      return {
        word: DEV.time('boxes', s2), wordIdx: DEV.time({word: [1, 1]}, s2), wordEnd: DEV.time({word_end: [1, -1]}, s2),
        beat10: DEV.time({beat: 10}, s2), beats2: DEV.time({beats: 2}, s2), bar3: DEV.time({bar: 3}, s2),
        hit1: DEV.time({hit: 'kick', n: 1}, s2), kick1: kicks[1], nearHit: DEV.time({hit: 'kick', near: s2.t0 + .05}, s2),
        take: DEV.time({take: .5}, s3), keysT: inst.keys.map(k => k[0]), kW: DEV.instance({kind: 'spark', key: 'W', params: {word: 'humming'}}, s2).t0,
        kB: DEV.instance({kind: 'spark', key: 'B'}, s2).t0, kH: DEV.instance({kind: 'spark', key: 'H', params: {hit: 'snare'}}, s2).t0,
        kF: DEV.instance({kind: 'spark', key: 'F', params: {t: 5.25}}, s2).t0, roundTrip, beatLenA: DEV.bl(1.0), beatLenB: DEV.bl(28.0),
        // numbers written as strings (hand-written JSON) are numbers, never concatenated
        beatsStr: DEV.time({beats: '2'}, s2), beatStr: DEV.time({beat: '10'}, s2), keyBStr: DEV.instance({kind: 'spark', key: 'B', params: {beat: '2'}}, s2).t0,
        keyB2: DEV.instance({kind: 'spark', key: 'B', params: {beat: 2}}, s2).t0, lineStr: (DEV.line('1') || {}).line,
        // a word sung outside the shot: a warning and the shot start (the device would never show); a word never sung: a warning
        outside: (() => { const i = DEV.instance({kind: 'spark', key: 'W', params: {word: 'tide'}}, s2); return {t0: i.t0, warn: i.warn}; })(),
        nowhere: (() => { const i = DEV.instance({kind: 'spark', key: 'W', params: {word: 'zeppelin'}}, s2); return {t0: i.t0, warn: i.warn}; })(),
        badBeats: (() => { const i = DEV.instance({kind: 'spark', at: {beats: 'two'}}, s2); return {t0: i.t0, warn: i.warn}; })(),
        coerced: (() => { const i = DEV.instance({kind: 'sheet', params: {rows: 'BASE: 1 | TOKENS: 2', w: '400'}}, s2); return {rows: i.p.rows, w: i.p.w, warn: i.warn}; })(),
        badShape: (() => { const i = DEV.instance({kind: 'ui.chat', params: {msgs: ['hi', {who: 'ai', text: 'yo'}]}}, s2); return {n: i.p.msgs.length, warn: i.warn}; })(),
      };
    }""", [s02, s03])
    toks = ln1["tokens"]
    assert r["word"] == pytest.approx(toks[1]["t0"]) and r["wordIdx"] == pytest.approx(toks[1]["t0"])
    assert r["wordEnd"] == pytest.approx(toks[-1]["t1"])
    assert r["beat10"] == pytest.approx(beats[10])
    i0 = next(i for i, b in enumerate(beats) if b >= s02["t0"] - 1e-3)
    assert r["beats2"] == pytest.approx(beats[i0 + 2], abs=1e-3)
    assert r["bar3"] == pytest.approx(beats[12])
    assert r["hit1"] == pytest.approx(r["kick1"]) and r["nearHit"] == pytest.approx(beats[i0], abs=1e-3)
    assert r["take"] == pytest.approx(s03["t0"] + .5)
    assert r["keysT"] == pytest.approx([s03["t0"] + .25, s03["t0"] + .75])
    assert r["kW"] == pytest.approx(toks[2]["t0"]) and r["kB"] == pytest.approx(beats[i0], abs=1e-3)
    snares = [b for b in beats[1::2] if b >= s02["t0"] - 1e-3]
    assert r["kH"] == pytest.approx(snares[0]) and r["kF"] == pytest.approx(5.25)
    assert max(r["roundTrip"]) < 1e-6
    assert r["beatLenA"] > r["beatLenB"], "the beat map accelerates: beats get shorter (never a fixed BPM)"
    assert r["beatsStr"] == pytest.approx(r["beats2"]) and r["beatStr"] == pytest.approx(beats[10]), "string numbers must not concatenate"
    assert r["keyBStr"] == pytest.approx(r["keyB2"]) and r["lineStr"] == 1
    assert r["outside"]["t0"] == pytest.approx(s02["t0"]) and any("outside the shot" in w for w in r["outside"]["warn"]), r["outside"]
    assert r["nowhere"]["t0"] == pytest.approx(s02["t0"]) and any("not a sung word" in w for w in r["nowhere"]["warn"]), r["nowhere"]
    assert any("beats is not a number" in w for w in r["badBeats"]["warn"]), r["badBeats"]
    assert r["coerced"]["rows"] == [["BASE", "1"], ["TOKENS", "2"]] and r["coerced"]["w"] == 400 and r["coerced"]["warn"], r["coerced"]
    assert r["badShape"]["n"] == 1 and r["badShape"]["warn"], r["badShape"]


# --------------------------------------------------------------------------------------------------- the plan ---
def test_plan_treatments_transitions_flashes(ep):
    p = js(ep, """() => { const P = SHOTS_PLAN(); return {
      list: P.list.map(S => ({id: S.id, fam: S.treat.family, base: S.treat.base, auto: !!S.treat.auto, flash: S.treat.params.flash ?? null, tr: S.tr ? S.tr.preset : null})),
      warn: P.warn, accepted: P.flash.accepted.map(f => ({t: f.t, fixed: !!f.fixed, src: f.src})), rejected: P.flash.rejected.length,
      ok: DEV.flashOk(P.flash.accepted.map(f => f.t)), clean: P.clean }; }""")
    seq = [s for s in p["list"] if s["base"] in ("plate", "none") and not s["id"].startswith("gap")]
    for a, b in zip(seq, seq[1:]):
        if a["base"] == "plate" and b["base"] == "plate":
            assert a["fam"] != b["fam"], f"{a['id']} and {b['id']} share the treatment {a['fam']}"
    w = "\n".join(p["warn"])
    assert "s06: treatment 'rack' repeats" in w
    assert "s12: transition 'whip' repeats" in w and next(s for s in p["list"] if s["id"] == "s12")["tr"] is None
    assert "unknown device kind 'nonexistent.device'" in w
    assert p["ok"] and p["rejected"] > 0, "a flash every 16th must be cut down to ≤ 3 per second"
    assert "flashes from flash dropped" in w
    # the designed transitions are fixed events in the flash budget (the droppable flashes fit around them)
    fixed = [f for f in p["accepted"] if f["fixed"]]
    assert {f["src"] for f in fixed} >= {"trans:whip", "trans:match", "trans:through"}, fixed
    trs = {s["id"]: s["tr"] for s in p["list"]}
    assert p["clean"], "the synthetic project is a native (clean) look"
    assert trs["s02"] == "whip" and trs["s03"] == "flashCut" and trs["s04"] == "match" and trs["s05"] == "fade", "dither is a crossfade in a clean look"
    assert trs["s06"] == "flap" and trs["s07"] == "through" and trs["s08"] == "smear" and trs["s09"] == "iris"
    assert "s08: transition 'smear' is a print-look texture" in w
    # a stills treatment that was not asked for fires no crop flashes
    for s in p["list"]:
        if s["fam"] == "stills" and s["auto"]:
            assert s["flash"] is False, s
    assert "s02: 'counter' sets 120 px type over a 46 px lyric" in w, "the lyric is the biggest type unless the device is the line"


# --------------------------------------------------------------------------------------------- whole frames -----
def _frame(ep, t):
    data = ep.frame_jpeg(t)
    st = js(ep, "() => Object.assign({}, window.DEV_FRAME || {}, {errors: (window.DEV_ERRORS || []).slice()})")
    return data, st


def test_frames_render_with_the_element_budget(ep, project):
    shots = {s["id"]: s for s in project["shots"]}
    times = []
    for s in project["shots"]:
        times += [s["t0"] + .02, (s["t0"] + s["t1"]) / 2, s["t1"] - .05]
    times += [29.0]                                                     # the gap scene at the end
    stats = {}
    for t in times:
        _, st = _frame(ep, t)
        assert not st["errors"], (t, st["errors"])
        assert len(st.get("hero", [])) <= 1 and len(st.get("cv", [])) <= 2 and len(st.get("micro", [])) <= 2, (t, st)
        assert st.get("microRows", 0) <= 3, (t, st)
        assert st.get("accents", 0) <= 2, (t, st)
        stats[round(t, 3)] = st
    # three heroes at once in s02 → the newest (the counter, entering two beats in) is the one drawn
    s2 = shots["s02"]                                                   # (clear of s03's flash-cut window: .2 s centred on the cut)
    _, st = _frame(ep, s2["t1"] - .2)
    assert st["hero"] == ["counter"], st
    # five CV marks + the lead's mark in s03 → the two newest
    s3 = shots["s03"]                                                   # (clear of s04's match window: .5 s centred on the cut)
    _, st = _frame(ep, s3["t1"] - .3)
    assert len(st["cv"]) == 2 and "cv.lead" not in st["cv"], st
    assert st["suppressed"] >= 3, st
    assert stats[round(29.0, 3)]["shot"].startswith("gap")
    assert not ep.errors, ep.errors


def test_card_flash_is_the_line(ep, project):
    ln = project["lines"][3]
    tk = next(t for t in ln["tokens"] if t["txt"].lower().startswith("rope"))
    t = tk["t0"] + .01
    _, st = _frame(ep, t)
    assert st["flash"] == ["flash"] and st["lyric"] is None, st
    assert st["hero"] == [] and st["cv"] == [] and st["micro"] == [], "nothing is drawn on the footage a full-frame card hides"
    assert f"{tk['t0']:.2f}" in ep.drawn(t)


def test_lyric_gate_every_token_on_its_time(ep):
    toks = ep.lyric_tokens()
    assert len(toks) >= 30
    missing = [(tk["line"], tk["txt"], tk["t0"]) for tk in toks if tk["key"] not in ep.drawn(tk["t"])]
    assert not missing, f"tokens not drawn on their time: {missing}"


def test_transitions_render_inside_their_windows(ep, project):
    for s in project["shots"][1:]:
        if not s.get("transition_in"):
            continue
        for dt in (-.06, -.01, .0, 1 / 24 + .005, .06):
            _, st = _frame(ep, s["t0"] + dt)
            assert not st["errors"], (s["id"], dt, st["errors"])
    assert not ep.errors, ep.errors


def test_frames_are_deterministic_and_history_independent(ep, pw, project):
    shots = {s["id"]: s for s in project["shots"]}
    ts = [shots["s01"]["t0"] + .7, shots["s05"]["t0"] + .9, shots["s08"]["t0"] + .3, shots["s10"]["t0"] + 1.0]
    first = [ep.frame_jpeg(t) for t in ts]
    again = [ep.frame_jpeg(t) for t in reversed(ts)][::-1]
    assert first == again, "same t must give the same pixels whatever was rendered before"
    fresh = _open(pw, project["dir"])
    try:
        assert [fresh.frame_jpeg(t) for t in ts[::-1]][::-1] == first, "a fresh page must render the same pixels"
    finally:
        fresh.close()


def _inside(box, mg, w, h, tol=12):
    x, y, bw, bh = box
    return x >= mg["l"] - tol and y >= mg["t"] - tol and x + bw <= w - mg["r"] + tol and y + bh <= h - mg["b"] + tol


def test_portrait_frames_keep_lyric_and_devices_in_the_margins(pw, project):
    """The 9:16 cut (slop render vertical): the lyric and every placed device stay inside the portrait's UI-safe margins;
    a device wider than the safe area is scaled down to fit."""
    page = _open(pw, project["dir"], w=1080, h=1920)
    try:
        mg = page.page.evaluate("() => DEV.MG()")
        assert mg["b"] > 200, "portrait margins (engine-core chrome.js) must clear the platform UI"
        bad, scaled, lyr = [], [], 0
        for s in project["shots"]:
            for t in (s["t0"] + .6, (s["t0"] + s["t1"]) / 2, s["t1"] - .3):
                page.frame_jpeg(t)
                st = page.page.evaluate("() => Object.assign({}, window.DEV_FRAME, {errors: (window.DEV_ERRORS || []).slice()})")
                assert not st["errors"], (s["id"], st["errors"])
                if st.get("lyric") and st["lyric"].get("box"):
                    lyr += 1
                    if not _inside(st["lyric"]["box"], mg, 1080, 1920):
                        bad.append((s["id"], round(t, 2), "lyric", st["lyric"]))
                for b in st.get("boxes", []):
                    if b["scale"] < 1:
                        scaled.append(b["kind"])
                    if not _inside(b["box"], mg, 1080, 1920, tol=1):
                        bad.append((s["id"], round(t, 2), b["kind"], b["box"]))
        assert lyr >= 8, "the portrait frames must draw lyric blocks"
        assert not bad, bad
        assert "departures" in scaled, f"the departures board (≈1016 px) must be scaled into the 858 px portrait safe area: {scaled}"
        assert not page.errors, page.errors
    finally:
        page.close()


def test_without_hits_and_in_a_print_look(pw, tmp_path):
    """No window.HITS (H keys and camera moves fall back to the beat map) and a print look (light grounds, ink)."""
    proj = _synth().build(tmp_path / "nohits", hits_json=False, look="print")
    page = _open(pw, proj["dir"])
    try:
        assert page.page.evaluate("() => !window.HITS || !(window.HITS.kick || []).length")
        trs = page.page.evaluate("() => Object.fromEntries(SHOTS_PLAN().list.map(S => [S.id, S.tr ? S.tr.preset : null]))")
        assert trs["s05"] == "dither", "a print look keeps the ordered-dither dissolve"
        for s in proj["shots"]:
            for t in (s["t0"] + .03, (s["t0"] + s["t1"]) / 2):
                page.frame_jpeg(t)
                st = page.page.evaluate("() => Object.assign({}, window.DEV_FRAME, {errors: (window.DEV_ERRORS || []).slice()})")
                assert not st["errors"], (s["id"], t, st["errors"])
                assert len(st["hero"]) <= 1 and len(st["cv"]) <= 2 and st["accents"] <= 2, st
        missing = [tk["key"] for tk in page.lyric_tokens() if tk["key"] not in page.drawn(tk["t"])]
        assert not missing, missing
        assert not page.errors, page.errors
    finally:
        page.close()


def test_treatment_and_transition_names_from_storyboards(ep):
    """The board's family names, the guide's codes and storyboard prose all resolve (a weaker model writes all three)."""
    r = js(ep, """() => ({
      t: ['layer-separation', 'depth-as-image', 'diagram-over-image', 'stills-in-rhythm', 'reproduction', 'pure-motion', 'code',
          'DI+LS', 'LS (rack)', 'SR', 'thermal', {family: 'layers', amount: .05}, 'auto', null, 'DI: contours', 'LS (relight)'].map(v => { const p = DEV.treat.parse(v); return p ? [p.family, p.params.kind || null] : null; }),
      bad: DEV.treat.parse('glitter').unknown,
      tr: ['whip left', 'flash cut', 'Match cut: her pupil = the gap in the clouds', 'push through the monitor', 'dissolve', 'cut', '',
           {preset: 'whip', dir: 'up'}, 'iris', 'split-flap wipe', 'cut into the chorus', 'crossfade'].map(v => { const p = DEV.trans.parse(v); return p ? [p.preset, p.opts.dir ?? null] : null; }),
      eng: ['luma', 'bands', 'zoom', 'wrap', 'barcode wipe'].map(v => { const p = DEV.trans.parse(v); const m = DEV.trans.make(p, {t0: 3}); return [p.preset, !!p.engine, !!(m && typeof m.draw === 'function')]; }),
      unknown: ['tear', 'shutter'].map(v => { const p = DEV.trans.parse(v); return [p.preset, p.unknown]; }),
    })""")
    assert r["t"] == [["layers", None], ["relight", None], ["diagram", None], ["stills", None], ["xerox", None], ["motion", None],
                      ["motion", None], ["relight", None], ["rack", None], ["stills", None], ["xerox", "thermal"], ["layers", None], None, None,
                      ["contours", None], ["relight", None]]
    assert r["bad"] == "glitter"
    assert r["tr"][0] == ["whip", pytest.approx(math.pi)] and r["tr"][1][0] == "flashCut" and r["tr"][2][0] == "match"
    assert r["tr"][3][0] == "through" and r["tr"][4][0] == "dither" and r["tr"][5] is None and r["tr"][6] is None
    assert r["tr"][7] == ["whip", pytest.approx(-math.pi / 2)] and r["tr"][8][0] == "iris" and r["tr"][9][0] == "flap"
    assert r["tr"][10] is None, "prose that starts with 'cut' is a cut, not a push-through"
    assert r["tr"][11][0] == "fade"
    assert all(e[1] and e[2] for e in r["eng"]), f"engine-registry transitions must play through ENGINE.transitions: {r['eng']}"
    assert [e[0] for e in r["eng"]] == ["luma", "bands", "zoom", "wrap", "bands"]
    assert r["unknown"] == [[None, "tear"], [None, "shutter"]]


# ------------------------------------------------------------------------------- the real pipeline: no boxes -----
def test_a_project_without_detection_boxes_finds_its_subject(pw, tmp_path):
    """`slop edit export` writes `boxes: {}` and no clip tracks: the lead mark, 'lead' / person anchors and the
    subject-based transitions use the depth map's subject or the shot's subject_uv; shots with neither say so."""
    proj = _synth().build(tmp_path / "noboxes", boxes=False)
    page = _open(pw, proj["dir"])
    try:
        shots = {s["id"]: s for s in proj["shots"]}
        r = page.page.evaluate("""async () => { const P = SHOTS_PLAN(), out = {warn: P.warn, uv: {}};
          for (const id of ['s01', 's02', 's04', 's08', 's03']) out.uv[id] = await DEV.subjectUV(P.byId[id].sh);
          out.autoLead = Object.fromEntries(P.list.map(S => [S.id, S.devices.some(d => d.auto)])); return out; }""")
        # the depth plates: the nearest region contains the subject disc; the flat plate: the hand-written box
        plates = _synth().PLATES
        for sid, plate in (("s01", "p-a"), ("s02", "p-b"), ("s04", "p-c")):
            u, v = plates[plate][2], plates[plate][3]
            box = r["uv"][sid]
            assert box and box[0] <= u <= box[0] + box[2] and box[1] <= v <= box[1] + box[3], (sid, box, (u, v))
        assert r["uv"]["s08"] == pytest.approx([0.33, 0.28, 0.24, 0.46]) and r["uv"]["s03"] is None
        assert r["autoLead"]["s01"] and r["autoLead"]["s08"] and not r["autoLead"]["s03"]
        w = "\n".join(r["warn"])
        assert "no lead mark on 2 lead_on_screen shot(s)" in w and "s03" in w and "s12" in w and "subject_uv" in w, w
        assert "s01: cv.bracket: anchor" not in w, "a face / person label falls back to the subject box when there is one"
        assert "s03: cv.tag: anchor 'a woman': no detection box" in w, "…and says so when there is none"
        assert "s03: cv.lock: anchor 'lead' has nothing to resolve to" in w, w
        # frames: the lead mark sits on the subject; the through/match/iris transitions find it; nothing throws
        for sid in ("s01", "s02", "s08"):
            s = shots[sid]
            page.frame_jpeg((s["t0"] + s["t1"]) / 2)
            st = page.page.evaluate("() => Object.assign({}, window.DEV_FRAME, {errors: (window.DEV_ERRORS || []).slice()})")
            assert not st["errors"], st["errors"]
            assert st["lead"], (sid, st)
        for sid in ("s04", "s07", "s09"):
            for dt in (-.05, .0, .05):
                page.frame_jpeg(shots[sid]["t0"] + dt)
        assert not page.page.evaluate("() => (window.DEV_ERRORS || []).slice()")
        missing = [tk["key"] for tk in page.lyric_tokens() if tk["key"] not in page.drawn(tk["t"])]
        assert not missing, missing
        assert not page.errors, page.errors
    finally:
        page.close()


def test_plate_memos_are_bounded(ep):
    """Per-plate slices/grids/thumbs are kept for the last 3 plates only (a worker renders the whole film interleaved)."""
    r = ep.page.evaluate("""async () => {
      const base = PLATES['p-a'], seen = [];
      for (let k = 0; k < 7; k++) PLATES['lru' + k] = Object.assign({}, base, {file: 'assets/plates/p-a.jpg', depth: 'assets/plates/p-a.depth.png'});
      let one = 0;
      for (let k = 0; k < 7; k++) { const s = await DEV.treat.slices('lru' + k); await DEV.treat.depthGrid('lru' + k); await new Promise(r => setTimeout(r, 0));
        const st = DEV.memoStats(); seen.push(st.owners.length); if (k === 0) one = st.px; if (!s.L.length) return {err: 'no depth slices'}; }
      const st = DEV.memoStats(); return {seen, owners: st.owners, px: st.px, one, limit: st.limit, entries: st.entries};
    }""")
    assert "err" not in r, r
    assert max(r["seen"]) <= r["limit"] == 3, r
    assert r["owners"][-3:] == ["lru4", "lru5", "lru6"] and not any(o in r["owners"] for o in ("lru0", "lru1", "lru2", "lru3")), r
    assert r["one"] > 0 and r["px"] <= 3 * r["one"] * 1.05 + 4e6, r


# ------------------------------------------------------------------------- the operator sees every repair ------
def _variant(shots):
    by = {s["id"]: s for s in shots}
    by["s03"]["transition_in"] = "cut"                      # whip · cut · whip is allowed (the rule compares neighbours)
    by["s04"]["transition_in"] = "whip"
    by["s05"]["transition_in"] = "tear"                     # nobody's preset: a warning and a cut
    by["s07"]["transition_in"] = "luma"                     # the engine registry's preset
    by["s09"]["transition_in"] = "cut into the chorus"      # prose that starts with "cut": a cut, no warning
    by["s06"]["devices"].append({"kind": "sheet", "key": "B", "params": {"rows": "RENT: 1 | FOOD: 2"}})
    by["s02"]["devices"] += [{"kind": "terminal", "key": "B", "params": {"script": [{"b": 0, "k": "prompt", "s": 5}]}},   # throws at draw
                             {"kind": "spark", "key": "W", "params": {"word": "zeppelin"}},
                             {"kind": "callout", "anchor": {"box": "a lamp"}, "key": "B", "params": {"rows": ["LAMP"]}}]
    by["s02"]["type"].append({"line": "1", "mode": "coverline", "size": "60", "placement": "right"})


def test_render_info_reports_every_repair(tmp_path):
    """`slop --json render info` must show what the renderer changed or could not draw (the plan's warnings and the
    boot dry run), so a weaker model driving the CLI learns its storyboard was repaired."""
    _need_engine()
    proj = _synth().build(tmp_path / "variant", tweak=_variant)
    env = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    out = subprocess.run([sys.executable, "-m", "slop", "--json", "render", "info", "--project", str(proj["dir"])],
                         capture_output=True, text=True, cwd=ROOT, env=env, timeout=240)
    if out.returncode and "could not start a browser" in (out.stdout + out.stderr):
        pytest.skip("no headless browser")
    d = json.loads(out.stdout)
    assert d["ok"], d
    dw = d["info"]["deviceWarnings"]
    w = "\n".join(dw)
    assert "s13: unknown device kind 'nonexistent.device'" in w
    assert "s12: transition 'whip' repeats the previous shot's transition" in w
    assert "s04: transition 'whip' repeats" not in w, "whip · cut · whip is allowed"
    assert "s05: transition \"tear\" is not a preset" in w and "s07: transition" not in w, "luma is the engine registry's"
    assert "s09: transition" not in w
    assert "s06: sheet.params.rows should be a list" in w
    assert "s02: device 'terminal' throws with these params" in w, w
    assert "s02: spark: word zeppelin" in w and "not a sung word" in w
    assert "s02: callout: anchor 'a lamp': no detection box" in w
    assert not d["info"]["deviceErrors"], d["info"]["deviceErrors"]
    console = "\n".join(d["info"]["console"])
    assert "[devices] s13: unknown device kind" in console, "the warnings go to the page console, which `slop render info` returns"
    # the variant's string fields work: the coverline on line "1" sized "60" renders (no type error at boot)
    assert "type entry" not in w, w
