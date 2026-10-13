"""Studio-tier E2E fixes, engine track (e2e/STUDIO-E2E.md defects 5 and 7):

  * the tuck rule — occlusion tucks an edge, never a glyph (s005: a line passing behind a near laptop lost "Do" of
    "Don't"): occ.js's glyph guard, on hand-made masks (letters that touch tuck only their outer letter; ink below the
    block's box is guarded too) and on a synthetic depth plate with a near object over the lyric;
  * a lifted glyph sits ON the subject: it takes the ink that reads there, the rest the ink of the ground off the subject
    (a split along the matte — subtitle and coverline);
  * "graphics type larger than the lyric" (s009, s017): the plan caps a hero's type at the lyric's size unless the
    device IS the line, and says so;
  (the 9:16 cut's full-quality default is in test_studio_engine_vertical.py: its CLI runs need no page open here).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"


def _synth():
    spec = importlib.util.spec_from_file_location("engine_devices_synth", ROOT / "tests" / "fixtures" / "engine_devices" / "synth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_engine():
    for f in ("index.html", "src/occ.js", "src/shots.js", "src/devices/type.js"):
        if not (ENGINE / f).is_file():
            pytest.skip(f"engine file missing: engine/{f}")
    pytest.importorskip("PIL")
    pytest.importorskip("playwright.sync_api")


# the near object of the synthetic plate: a laptop in the lower middle, over the right part of the subtitle (image space)
LAPTOP = (0.20, 0.70, 0.70, 1.0)


def _laptop_plate(eng: Path) -> None:
    """p-laptop: a dark stage with a grey laptop at the bottom; its depth map has the laptop NEAR (1.0) and the
    stage far (.3) — what Depth-Anything gives for a prop in front of the camera."""
    from PIL import Image, ImageDraw
    w, h = 960, 540
    u0, v0, u1, v1 = LAPTOP
    img = Image.new("RGB", (w, h), (24, 22, 30))
    ImageDraw.Draw(img).rectangle([u0 * w, v0 * h, u1 * w, v1 * h], fill=(150, 152, 160))
    img.save(eng / "assets" / "plates" / "p-laptop.jpg", quality=90)
    dw, dh = w // 4, h // 4
    dep = Image.new("L", (dw, dh), 77)
    ImageDraw.Draw(dep).rectangle([u0 * dw, v0 * dh, u1 * dw, v1 * dh], fill=255)
    dep.save(eng / "assets" / "plates" / "p-laptop.depth.png")


def _tweak(shots):
    """s02: the second line as a subtitle tucked behind by depth, on the laptop plate (push); two more heroes: a flap
    board that sets bigger type than the lyric (capped) and a stamp that IS the line (kept)."""
    sh = next(s for s in shots if s["id"] == "s02")
    sh["treatment"] = "push"
    sh["type"] = [{"line": 1, "mode": "subtitle", "behind": "depth"}]
    sh["devices"] = sh["devices"] + [{"kind": "flap", "key": "B", "params": {"beat": 1, "ch": 120, "rows": [{"text": "ON", "prev": "NO"}]}},
                                     {"kind": "stamp", "key": "B", "params": {"beat": 3, "size": 200, "text": "BOXES", "is_line": True}}]


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    _need_engine()
    pr = _synth().build(tmp_path_factory.mktemp("studio-engine"), tweak=_tweak)
    d = Path(pr["dir"])
    eng = d / "engine"
    _laptop_plate(eng)
    pl = (eng / "plates.js").read_text(encoding="utf-8")
    meta = json.loads(pl[pl.index("=") + 1:].strip().rstrip(";"))
    meta["p-laptop"] = {"boxes": {}, "w": 960, "subject_depth": .86, "depth_model": "depth-anything-v2-small"}
    (eng / "plates.js").write_text("window.PLATES = " + json.dumps(meta) + ";\n", encoding="utf-8")
    edl = json.loads((d / "edit" / "edl.json").read_text(encoding="utf-8"))
    edl["s02"] = {"plate": "p-laptop"}
    (d / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    return pr


@pytest.fixture(scope="module")
def pw():
    _need_engine()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def ep(pw, project):
    from slop.render.browser import EnginePage
    from slop.render.project import page_spec
    try:
        page = EnginePage(pw, page_spec(project["dir"]))
    except Exception as e:  # noqa: BLE001 — no browser on this machine
        pytest.skip(f"no headless browser: {e}")
    yield page
    page.close()


def js(ep, code, arg=None):
    return ep.page.evaluate(code, arg)


def _s02(project):
    s = next(s for s in project["shots"] if s["id"] == "s02")
    return {"id": s["id"], "t0": s["t0"], "t1": s["t1"], "lines": s["lines"]}


# ---------------------------------------------------------------------------------------------- the tuck rule ---
GUARD_JS = """async () => {
  const mkc = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
  const font = '700 120px "Space Grotesk"', X0 = 300, Y = 520, txt = 'WORD';
  const draw = g => { g.font = font; g.fillStyle = '#fff'; g.textBaseline = 'alphabetic'; g.fillText(txt, X0, Y); };
  const ref = mkc(); draw(ref.getContext('2d'));
  const mc = mkc().getContext('2d'); mc.font = font;
  const xs = [...txt].map((_, i) => X0 + mc.measureText(txt.slice(0, i)).width), ws = [...txt].map(ch => mc.measureText(ch).width);
  const glyph = i => [Math.floor(xs[i]), Y - 110, Math.ceil(ws[i]), 140];
  const maskOf = rects => { const c = document.createElement('canvas'); c.width = W >> 1; c.height = H >> 1; const g = c.getContext('2d');
    g.fillStyle = '#000'; rects.forEach(([x, y, w, h]) => g.fillRect(x / 2, y / 2, w / 2, h / 2)); return c; };
  const lost = (out, [x, y, w, h]) => { const a = ref.getContext('2d').getImageData(x, y, w, h).data, b = out.getContext('2d').getImageData(x, y, w, h).data;
    let s = 0, l = 0; for (let i = 3; i < a.length; i += 4) { s += a[i]; l += Math.max(0, a[i] - b[i]); } return +(l / Math.max(1, s)).toFixed(3); };
  const run = async (rects, guard) => { const o = mkc(), m = { matte: async () => maskOf(rects) }; OCC.begin(0);
    await OCC.behind(o.getContext('2d'), m, draw, Object.assign({ mode: 'matte' }, guard ? { glyphs: { region: [X0 - 10, Y - 110, 700, 140] } } : {}));
    return { o, rec: OCC.guarded() }; };
  const out = {};
  const inner = [[xs[2] - 2, Y - 140, ws[2] + 4, 180]];                                      // the whole R (an inner glyph)
  for (const g of [false, true]) { const r = await run(inner, g); out['inner_' + g] = { R: lost(r.o, glyph(2)), O: lost(r.o, glyph(1)), rec: r.rec }; }
  const nick = [[xs[3] + ws[3] * .82, Y - 140, ws[3] * .18 + 40, 180]];                    // a nick off the D (the end glyph)
  { const r = await run(nick, true); out.nick = { D: lost(r.o, glyph(3)), rec: r.rec }; }
  const most = [[xs[3] + ws[3] * .25, Y - 140, ws[3] * .75 + 40, 180]];                    // most of the D
  { const r = await run(most, true); out.most = { D: lost(r.o, glyph(3)), rec: r.rec }; }
  const all = [[X0 - 20, Y - 140, xs[3] + ws[3] - X0 + 60, 180]];                         // the whole word
  { const r = await run(all, true); out.all = { lost: [0, 1, 2, 3].map(i => lost(r.o, glyph(i))), rec: r.rec }; }
  const none = [[X0, Y + 200, 300, 60]];                                                  // the subject nowhere near the type
  { const r = await run(none, true); out.none = { rec: r.rec }; }
  out.TUCK = OCC.TUCK;
  return out; }"""


def test_glyph_guard_on_hand_made_masks(ep):
    r = js(ep, GUARD_JS)
    tuck = r["TUCK"]
    assert 0 < tuck <= .5
    # without the guard the occluder eats the inner glyph (the s005 defect); with it the glyph is drawn whole
    assert r["inner_false"]["R"] > .9, r["inner_false"]
    assert r["inner_true"]["R"] < .02 and r["inner_true"]["O"] < .02, r["inner_true"]
    assert r["inner_true"]["rec"]["kept"] >= 1 and r["inner_true"]["rec"]["cover"] <= tuck, r["inner_true"]
    # an edge tucks: a nick off the end glyph stays cut (bounded by the tuck share)
    assert .02 < r["nick"]["D"] <= tuck + .02, r["nick"]
    assert r["nick"]["rec"]["tucked"] + r["nick"]["rec"]["eased"] >= 1 and r["nick"]["rec"]["kept"] == 0, r["nick"]
    # ... but never the glyph: most of the end glyph behind the subject → drawn whole
    assert r["most"]["D"] < .02 and r["most"]["rec"]["kept"] >= 1, r["most"]
    # the subject over the whole word: every glyph whole
    assert max(r["all"]["lost"]) < .02 and r["all"]["rec"]["kept"] >= 4, r["all"]
    # nothing reached: no record, nothing lifted
    assert r["none"]["rec"] is None, r["none"]


MERGED_JS = """async () => {
  const mkc = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
  const maskOf = rects => { const c = document.createElement('canvas'); c.width = W >> 1; c.height = H >> 1; const g = c.getContext('2d');
    g.fillStyle = '#000'; rects.forEach(([x, y, w, h]) => g.fillRect(x / 2, y / 2, w / 2, h / 2)); return c; };
  const lostIn = (ref, out, [x, y, w, h]) => { const a = ref.getContext('2d').getImageData(x, y, w, h).data, b = out.getContext('2d').getImageData(x, y, w, h).data;
    let s = 0, l = 0; for (let i = 3; i < a.length; i += 4) { s += a[i]; l += Math.max(0, a[i] - b[i]); } return +(l / Math.max(1, s)).toFixed(3); };
  const run = async (draw, rects, region) => { const ref = mkc(); draw(ref.getContext('2d')); const o = mkc(); OCC.begin(0);
    await OCC.behind(o.getContext('2d'), { matte: async () => maskOf(rects) }, draw, { mode: 'matte', glyphs: { region } });
    return { ref, o, rec: OCC.guarded() }; };
  const out = {};
  // touching letters: NNNN tracked in until the letters overlap — one connected run of ink, a whole word wide
  const font = '700 120px "Space Grotesk"', X0 = 300, Y = 520, sp = -36;
  const m = mkc().getContext('2d'); m.font = font;
  const nn = g => { g.font = font; g.letterSpacing = sp + 'px'; g.fillStyle = '#fff'; g.textBaseline = 'alphabetic'; g.fillText('NNNN', X0, Y); g.letterSpacing = '0px'; };
  // the ink's real right edge (measureText's width ends a letter-spacing short of it) and one N's ink width
  const probe = mkc(), pg = probe.getContext('2d'); nn(pg); const pd = pg.getImageData(0, Y - 110, W, 140).data; let xr = 0;
  for (let i = 3; i < pd.length; i += 4) if (pd[i] > 24) xr = Math.max(xr, ((i - 3) / 4) % W);
  const one = mkc(), og = one.getContext('2d'); og.font = font; og.fillStyle = '#fff'; og.fillText('N', X0, Y); const od = og.getImageData(0, Y - 110, W, 140).data;
  let o0 = W, o1 = 0; for (let i = 3; i < od.length; i += 4) if (od[i] > 24) { const x = ((i - 3) / 4) % W; o0 = Math.min(o0, x); o1 = Math.max(o1, x); }
  const wN = o1 - o0 + 1, lastN = [xr - wN, Y - 110, wN + 4, 140], reg = [X0 - 10, Y - 110, xr - X0 + 40, 140];
  out.geom = { xr, wN };
  { const r = await run(nn, [[xr - wN - 6, Y - 140, 400, 180]], reg); out.whole = { lost: lostIn(r.ref, r.o, lastN), rec: r.rec }; }       // the last N, all of it
  { const r = await run(nn, [[xr - Math.round(wN * .12), Y - 140, 400, 180]], reg); out.nick = { lost: lostIn(r.ref, r.o, lastN), rec: r.rec }; } // a nick off its edge
  // a masthead set in lower case (upper: false): the y's descender hangs below the word's box (type.js: baseline + .08 size)
  const big = '700 300px "Space Grotesk"', yb = 760;
  const cm = g => { g.font = big; g.fillStyle = '#fff'; g.textBaseline = 'alphabetic'; g.fillText('say', 200, yb); };
  m.font = big; const xc = 200 + m.measureText('sa').width, tail = [Math.floor(xc), yb + 40, Math.ceil(m.measureText('y').width) + 10, 80];
  { const r = await run(cm, [[xc - 6, yb - 300, 600, 500]], [190, yb - 300 * .78, m.measureText('say').width + 20, 300 * .86]); out.tail = { lost: lostIn(r.ref, r.o, tail), rec: r.rec }; }
  out.TUCK = OCC.TUCK;
  return out; }"""


def test_touching_letters_tuck_only_their_outer_letter(ep):
    """Connected ink is not always one letter: letters that touch (tight tracking, a masthead's accent block) form one run.
    Tucking a share of the run would take whole letters ('Do' of "Don't" again): only its outer letter's worth may tuck,
    an occluder reaching past it lifts the run whole. Ink below the block's box (a lower-case masthead's descender) is
    guarded too."""
    r = js(ep, MERGED_JS)
    assert r["whole"]["rec"]["glyphs"] == 1, f"the tracked-in NNNN must be one connected run for this test: {r['whole']}"
    assert r["whole"]["lost"] < .02 and r["whole"]["rec"]["kept"] == 1, f"a whole letter of a run was tucked: {r['whole']}"
    assert .01 < r["nick"]["lost"] <= r["TUCK"], f"an edge of the run still tucks: {r['nick']}"
    assert r["nick"]["rec"]["tucked"] + r["nick"]["rec"]["eased"] == 1, r["nick"]
    assert r["tail"]["lost"] < .02, f"the descender under the masthead's box was cut: {r['tail']}"


def test_lyric_never_loses_a_glyph_behind_a_near_object(ep, project):
    """A synthetic depth plate with a near laptop over the subtitle: the depth key alone would hide a large share of the
    line (control); the lyric drawn `behind: 'depth'` loses no glyph, and the frame's record says what the guard did."""
    ln = next(x for x in project["lines"] if x["line"] == 1)
    sh = _s02(project)
    t = round(ln["tokens"][-2]["t0"] + .05, 3)          # four of the five words up, well before the next shot's transition
    r = js(ep, """async ([sh, t]) => {
      const mk = () => DEV.mk(W, H).getContext('2d', { willReadFrequently: true });
      const b = mk(), m = await MEDIA.drawPlate(b, 'p-laptop', { zoom: 1.06 }, t), dep = m.depth ? await m.depth() : null;
      const X = { m, sh, accent: '#D97757', lightGround: false };
      const o1 = mk(), o2 = mk(), o3 = mk();
      OCC.begin(t);
      const box = await DEV.type.entry(o1, b, { line: 1, mode: 'subtitle', behind: 'depth' }, t, X);
      const rec = OCC.guarded();
      await DEV.type.entry(o2, b, { line: 1, mode: 'subtitle' }, t, X);                                   // uncut
      await OCC.behind(o3, m, g => DEV.type.entry(g, b, { line: 1, mode: 'subtitle' }, t, X), { mode: 'depth' });   // no guard
      const [x, y, w, h] = box.map(Math.round), A = o2.getImageData(x, y, w, h).data;
      const lost = o => { const B = o.getImageData(x, y, w, h).data; let s = 0, l = 0; for (let i = 3; i < A.length; i += 4) { s += A[i]; l += Math.max(0, A[i] - B[i]); } return +(l / Math.max(1, s)).toFixed(3); };
      return { depth: !!dep, box, rec, guarded: lost(o1), unguarded: lost(o3), tuck: OCC.TUCK }; }""",
           [sh, t])
    assert r["depth"], "the synthetic plate's depth map must load (Depth-Anything-V2-Small label)"
    assert r["unguarded"] > .25, f"control: the near object over the block hides its glyphs by depth key alone (s005): {r}"
    assert r["guarded"] < .03, f"the lyric lost glyphs behind the near object: {r}"
    assert r["rec"] and r["rec"]["kept"] >= 3 and r["rec"]["cover"] <= r["tuck"], r


SPLIT_JS = """async ([sh, t, en]) => {
  const mk = () => DEV.mk(W, H).getContext('2d', { willReadFrequently: true });
  const b = mk(), m = await MEDIA.drawPlate(b, 'p-laptop', { zoom: 1.06 }, t);
  const X = { m, sh, accent: '#D97757', lightGround: false }, o = mk();
  OCC.begin(t);
  const box = await DEV.type.entry(o, b, en, t, X), rec = OCC.guarded();
  const sub = await OCC.mask(m, { mode: 'depth' }), sd = sub.getContext('2d').getImageData(0, 0, sub.width, sub.height).data;
  const [x, y, w, h] = box.map(Math.round), d = o.getImageData(x, y, w, h).data, L = v => { v /= 255; return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
  const acc = { on: [0, 0], off: [0, 0] };
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) { const k = (j * w + i) * 4; if (d[k + 3] < 230) continue;
    const r = d[k], g = d[k + 1], bl = d[k + 2]; if (Math.max(r, g, bl) - Math.min(r, g, bl) > 40) continue;          // the accent word
    const a = sd[(((y + j) >> 1) * sub.width + ((x + i) >> 1)) * 4 + 3], side = a > 220 ? 'on' : a < 30 ? 'off' : null; if (!side) continue;
    acc[side][0] += .2126 * L(r) + .7152 * L(g) + .0722 * L(bl); acc[side][1]++; }
  return { rec, on: acc.on[1] ? +(acc.on[0] / acc.on[1]).toFixed(3) : null, off: acc.off[1] ? +(acc.off[0] / acc.off[1]).toFixed(3) : null, n: [acc.on[1], acc.off[1]] }; }"""


@pytest.mark.parametrize("en", [{"line": 1, "mode": "subtitle", "behind": "depth"},
                                {"line": 1, "mode": "coverline", "behind": "depth", "y": 960, "size": 84}],
                         ids=["subtitle", "coverline"])
def test_lifted_glyphs_take_the_ink_that_reads_on_the_subject(ep, project, en):
    """A glyph the guard lifts sits ON the subject: a light laptop on a dark stage takes dark ink on the laptop and light
    ink on the stage — even within one word at the laptop's edge (a split along the matte; s005 was a coverline, one ink
    per block, so the glyphs it showed on the stage were dark on dark)."""
    ln = next(x for x in project["lines"] if x["line"] == 1)
    t = round(ln["tokens"][-2]["t0"] + .05, 3)
    r = js(ep, SPLIT_JS, [_s02(project), t, en])
    assert r["rec"] and r["rec"]["kept"] >= 3, r
    assert min(r["n"]) > 200, f"the line must cross the laptop's edge for this test: {r}"
    assert r["on"] < .05 and r["off"] > .6, f"the ink does not follow the matte (on the laptop: dark; on the stage: light): {r}"


def test_frame_record_of_the_tuck(ep, project):
    """The default renderer draws s02 with its lyric `behind: 'depth'` on the laptop plate: DEV_FRAME.occ records the
    guard (glyphs reached, kept whole, cover ≤ the tuck share) and the frame draws without device errors."""
    ln = next(x for x in project["lines"] if x["line"] == 1)
    sh = _s02(project)
    t = round(ln["tokens"][-2]["t0"] + .05, 3)          # four of the five words up, well before the next shot's transition
    data = ep.frame_jpeg(t)
    st = js(ep, "() => ({f: Object.assign({}, window.DEV_FRAME || {}), errors: (window.DEV_ERRORS || []).slice(), tuck: OCC.TUCK})")
    f = st["f"]
    assert data and f["shot"] == "s02" and f["treatment"] == "push", f
    assert f["lyric"] and f["lyric"]["line"] == 1, f
    occ = f["occ"]
    assert occ and occ["glyphs"] >= 3 and occ["kept"] >= 3 and occ["cover"] <= st["tuck"], occ
    assert not st["errors"], st["errors"]
    # a frame of a shot with no `behind` type records nothing
    s01 = next(s for s in project["shots"] if s["id"] == "s01")
    ep.frame_jpeg(round((s01["t0"] + s01["t1"]) / 2, 3))
    assert js(ep, "() => (window.DEV_FRAME || {}).occ") is None


# ------------------------------------------------------------------------------- graphics type vs the lyric ---
def test_device_type_is_capped_at_the_lyric_unless_it_is_the_line(ep, project):
    r = js(ep, """() => { const P = SHOTS_PLAN(), S = P.byId.s02, d = k => S.devices.find(x => x.kind === k);
      return { warn: P.warn.filter(w => w.startsWith('s02:')), counter: d('counter').p.size, flap: [d('flap').p.ch, d('flap').p.cw],
        flapType: DEV.get('flap').typeSize(d('flap').p), stamp: d('stamp').p.size, capped: S.devices.filter(x => x.capped).map(x => [x.kind, x.capped.from, x.capped.to]) }; }""")
    w = "\n".join(r["warn"])
    assert "s02: 'counter' sets 120 px type over a 46 px lyric → capped at 46 px" in w, w
    assert "s02: 'flap' sets 94 px type over a 46 px lyric → capped at 46 px" in w, w
    assert "'stamp'" not in w, "a device that IS the line keeps its size"
    assert r["counter"] == pytest.approx(46, abs=.01) and r["flapType"] == pytest.approx(46, abs=.01), r
    assert r["flap"][1] == pytest.approx(40 * 46 / (120 * .78), abs=.01), "the flap's cells scale with its type"
    assert r["stamp"] == 200
    assert sorted(r["capped"]) == [["counter", 120, 46], ["flap", 94, 46]], r["capped"]
    # the capped devices still draw (the boot lint drew every device once; nothing threw)
    info = js(ep, "() => ENGINE.info()")
    assert not [x for x in info["deviceWarnings"] if "throws" in x and x.startswith("s02")], info["deviceWarnings"]
