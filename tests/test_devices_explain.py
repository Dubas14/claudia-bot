"""devices track: the explaining devices ported from the reference videos' chapter code (engine/src/devices/explain.js) —
print-on-quad (homography), the rope of type, streamlines, the molecule / network graph and powers of ten — on the real
engine page with the synthetic project (tests/fixtures/engine_devices/synth.py).

Checks: every variant draws over a range of t without throwing and puts ink on the frame; same t → same pixels (the base
and the overlay, rendered in a different order); the 9:16 cut keeps every placed block inside the UI-safe margins and turns
a quad the crop cuts into a panel; the homography maps the corners exactly; streamlines never cross the lyric block;
powers of ten paints its map on the base only (so the lyric's adaptive ink and the print pass read it; the overlay does not
carry it); a perspective panel's drawn corners stay inside the 9:16 margins even at its swing-in; the registry, aliases
and DEVICES.md entries. (Malformed params and the print look: tests/test_devices_params.py.)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
NEW = ["quad", "rope", "streamlines", "molecule", "powers"]

# every variant worth exercising: (name, device entry); anchors are slots / uv / the lead box (s02 has boxes and depth)
VARIANTS = [
    ("quad.sign.pinned", {"kind": "quad", "key": "B", "params": {"content": "sign", "quad": [[.55, .12], [.85, .14], [.85, .36], [.55, .36]], "title": "EXIT 4", "lines": ["HARBOUR", "LAST FERRY"]}}),
    ("quad.screen.panel", {"kind": "quad", "anchor": {"slot": "top-right"}, "key": "B", "params": {"content": "screen", "title": "queue", "status": "live", "rows": ["ONE · DONE", "TWO · RUNNING"]}}),
    ("quad.paper.behind", {"kind": "quad", "key": "B", "params": {"content": "paper", "quad": [[.2, .3], [.5, .28], [.52, .7], [.18, .72]], "title": "notice", "rows": [["A", "1"], ["B", "2"]], "behind": True}}),
    ("sign.face", {"kind": "sign.face", "anchor": {"slot": "top-left"}, "key": "B", "params": {"lines": ["NORTH"]}}),
    ("rope", {"kind": "rope", "anchor": "lead", "key": "B", "params": {"text": "HOLD ON", "height": .5}}),
    ("rope.uv", {"kind": "rope", "anchor": {"uv": [.2, .2, .3, .6]}, "key": "B", "params": {"turns": 2, "behind": False}}),
    ("streamlines", {"kind": "streamlines", "key": "B", "params": {"attractors": [{"uv": [.3, .3], "k": 1.4, "label": "A"}, {"uv": [.8, .3], "k": 1.8, "label": "B", "at": {"beats": 1}}], "seeds": 12}}),
    ("flow.points", {"kind": "flow", "key": "B", "params": {"attractors": [{"uv": [.5, .5], "k": 2}], "points": [[.1, .9], [.2, .1], [.9, .8]], "drift": [0, 0], "behind": True}}),
    ("molecule", {"kind": "molecule", "anchor": {"slot": "top-right"}, "key": "B", "params": {"chain": 9, "rings": 2, "label": "ILLUSTRATIVE"}}),
    ("network", {"kind": "network", "key": "B", "params": {"count": 12, "labels": ["YOU", "", "THEM"]}}),
    ("graph.custom", {"kind": "bonds", "anchor": {"slot": "bottom-right"}, "key": "B", "params": {"nodes": [{"x": 0, "y": 0, "label": "A"}, {"x": 1, "y": 0, "label": "B"}, {"x": .5, "y": .8}], "edges": [["A", "B", 2], [1, 2], [2, 0]]}}),
    ("powers", {"kind": "powers", "key": "B", "params": {"levels": ["10 M", "100 M", "1 KM"], "label": "HERE"}}),
    ("powers.point", {"kind": "zoom10", "key": "B", "params": {"point": [.3, .6], "beats": .5, "ground": "paper", "factor": 4}}),
]


def _synth():
    spec = importlib.util.spec_from_file_location("engine_devices_synth", ROOT / "tests" / "fixtures" / "engine_devices" / "synth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_engine():
    for f in ("index.html", "src/shots.js", "src/devices/index.js", "src/devices/explain.js"):
        if not (ENGINE / f).is_file():
            pytest.skip(f"engine file missing: engine/{f}")
    pytest.importorskip("PIL")
    pytest.importorskip("playwright.sync_api")


def _open(p, pdir, **kw):
    from slop.render.browser import EnginePage
    from slop.render.project import page_spec
    try:
        return EnginePage(p, page_spec(pdir, **kw))
    except Exception as e:  # noqa: BLE001 — no headless browser on this machine
        pytest.skip(f"no headless browser: {e}")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    _need_engine()
    return _synth().build(tmp_path_factory.mktemp("explainproj"))


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


def _sh(project, sid="s02"):
    s = next(s for s in project["shots"] if s["id"] == sid)
    return {"id": s["id"], "t0": s["t0"], "t1": s["t1"], "lines": s["lines"], "framing": s.get("framing", "")}


# one instance drawn at t on fresh base/overlay canvases (the footage of the shot under it): ink on the overlay, a hash of
# both canvases, the placed boxes, the frame's margins
DRAW = """async ([sh, spec, ts, avoid]) => {
  const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
  const B = mk(), O = mk(), b = B.getContext('2d', {willReadFrequently: true}), o = O.getContext('2d', {willReadFrequently: true});
  const fnv = c => { const d = c.getContext('2d').getImageData(0, 0, W, H).data; let h = 2166136261 >>> 0; for (let i = 0; i < d.length; i += 7) { h ^= d[i]; h = Math.imul(h, 16777619) >>> 0; } return h; };
  const inkIn = (r) => { const d = o.getImageData(0, 0, W, H).data; let n = 0, x0 = W, y0 = H, x1 = -1, y1 = -1;
    for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) { if (d[(y * W + x) * 4 + 3] <= 8) continue; n++;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    let inR = 0; if (r) for (let y = Math.max(0, r[1]); y < Math.min(H, r[1] + r[3]); y += 2) for (let x = Math.max(0, r[0]); x < Math.min(W, r[0] + r[2]); x += 2) if (d[(y * W + x) * 4 + 3] > 8) inR++;
    return {n, box: n ? [x0, y0, x1 - x0, y1 - y0] : null, inR}; };
  const inst = DEV.instance(spec, sh); if (inst.err) return {err: inst.err};
  const out = [];
  for (const dt of ts) {
    const t = inst.t0 + dt;
    b.reset(); o.reset(); b.fillStyle = '#000'; b.fillRect(0, 0, W, H); DEV.begin(t);
    const m = await MEDIA.drawShot(b, sh.id, t, {zoom: 1.06, cx: .5, cy: .5, flat: true});
    const baseBefore = fnv(B);
    const X = DEV.frame({t, sh, m, b, o, accent: '#D97757', flashOk: () => true}); X.lead = DEV.leadOf(m); if (avoid) X.avoid = [avoid];
    try { await DEV.draw(o, b, inst, t, X); } catch (e) { return {err: String(e && e.stack || e), t}; }
    out.push(Object.assign({t, hb: fnv(B), ho: fnv(O), baseChanged: fnv(B) !== baseBefore, boxes: X.boxes.map(q => ({kind: q.kind, box: q.box.map(Math.round)}))}, inkIn(avoid)));
  }
  return {frames: out, warn: inst.warn, mg: DEV.MG(), W, H};
}"""
TS = [-.1, 0, 1 / 24, .12, .3, .6, 1.1, 1.6, 2.2]


def _draw(ep, project, spec, ts=TS, avoid=None):
    return ep.page.evaluate(DRAW, [_sh(project), spec, ts, avoid])


# ------------------------------------------------------------------------------------------------- the library ---
def test_registered_aliased_and_documented(ep):
    r = ep.page.evaluate("""() => ({kinds: DEV.kinds(), roles: Object.fromEntries(['quad', 'rope', 'streamlines', 'molecule', 'powers'].map(k => [k, DEV.get(k) && DEV.get(k).role])),
      engine: ['quad', 'rope', 'streamlines', 'molecule', 'powers', 'network', 'homography', 'flow', 'zoom10'].filter(k => !(ENGINE.devices || {})[k]),
      network: DEV.instance({kind: 'network'}, {id: '', t0: 0, t1: 9}).p.preset, sign: DEV.instance({kind: 'sign.face'}, {id: '', t0: 0, t1: 9}).p.content,
      helpers: [typeof DEV.homog, typeof DEV.drawQuad, typeof DEV.treat.planes],
      pinned: ['streamlines', 'rope'].map(k => DEV.get(k).pinned({})).concat([DEV.get('quad').pinned({}), DEV.get('quad').pinned({quad: [[0, 0], [1, 0], [1, 1], [0, 1]]})])})""")
    assert set(NEW) <= set(r["kinds"]), r["kinds"]
    assert all(v == "hero" for v in r["roles"].values()), r["roles"]
    assert not r["engine"], f"not registered with ENGINE.registerDevice: {r['engine']}"
    assert r["network"] == "network" and r["sign"] == "sign"
    assert r["helpers"] == ["function", "function", "function"]
    assert r["pinned"] == [True, True, False, True]
    doc = (ENGINE / "DEVICES.md").read_text(encoding="utf-8")
    for k in NEW:
        assert f"### `{k}`" in doc, k
    assert "`multiplane`" in doc and "`tiles`" in doc and "ENGINE.frameLayers()" in doc and "chapterScenes" in doc
    assert "ENGINE.info().layers" not in doc, "one layer counter: ENGINE.frameLayers()"
    assert "Keys: W B H F T. The map" in doc, "powers' documented keys match the registry (W B H F T)"


@pytest.mark.parametrize("name,spec", VARIANTS, ids=[v[0] for v in VARIANTS])
def test_variant_draws_over_t_without_throwing(ep, project, name, spec):
    r = _draw(ep, project, spec)
    assert "err" not in r, r
    fr = r["frames"]
    assert fr[0]["n"] == 0 and not fr[0]["baseChanged"], f"{name} drew before its start: {fr[0]}"
    printed = spec["kind"] == "quad" and "quad" in spec["params"]          # a quad pinned to the plate prints INTO the footage
    if printed:
        assert any(f["baseChanged"] for f in fr), f"{name} never printed on the footage"
    else:
        assert max(f["n"] for f in fr) > 50, f"{name} never put ink on the overlay"
    assert not r["warn"], f"{name}: the entry must be clean: {r['warn']}"
    assert not ep.errors, ep.errors


@pytest.mark.parametrize("name,spec", VARIANTS, ids=[v[0] for v in VARIANTS])
def test_variant_is_deterministic(ep, project, name, spec):
    a = _draw(ep, project, spec, ts=[.27, 1.13, .27])
    b = _draw(ep, project, spec, ts=[1.13, .27])
    fa, fb = a["frames"], b["frames"]
    key = lambda f: (f["hb"], f["ho"])  # noqa: E731
    assert key(fa[0]) == key(fa[2]) == key(fb[1]), f"{name}: same t, different pixels"
    assert key(fa[1]) == key(fb[0]), f"{name}: same t, different pixels"


def test_homography_maps_the_corners_and_draws_inside(ep):
    r = ep.page.evaluate("""() => {
      const q = [[300, 200], [900, 260], [860, 700], [340, 640]], Hm = DEV.homog([[0, 0], [400, 0], [400, 300], [0, 300]], q);
      const err = [[0, 0], [400, 0], [400, 300], [0, 300]].map(([x, y], i) => Math.hypot(Hm(x, y)[0] - q[i][0], Hm(x, y)[1] - q[i][1]));
      const src = DEV.mk(400, 300), sg = src.getContext('2d'); sg.fillStyle = '#fff'; sg.fillRect(0, 0, 400, 300);
      const c = DEV.mk(W, H), g = c.getContext('2d', {willReadFrequently: true}); DEV.drawQuad(g, src, q, {strips: 24});
      const a = (x, y) => g.getImageData(x, y, 1, 1).data[3];
      return {err: Math.max(...err), inside: a(600, 450), outside: [a(250, 150), a(1000, 450), a(600, 760)], gaps: (() => { let n = 0;
        for (let x = 420; x < 820; x += 3) if (a(x, 450) < 200) n++; return n; })()};
    }""")
    assert r["err"] < 1e-6
    assert r["inside"] > 250 and max(r["outside"]) == 0
    assert r["gaps"] == 0, "the strips must join without seams"


def test_streamlines_never_cross_the_lyric(ep, project):
    spec = dict(VARIANTS[6][1])
    rect = [600, 380, 700, 260]
    r = _draw(ep, project, spec, ts=[1.6], avoid=rect)
    free = _draw(ep, project, spec, ts=[1.6])
    assert "err" not in r and "err" not in free
    # (the attractor rings and labels are not lines: the test rectangle is clear of them)
    assert free["frames"][0]["n"] > r["frames"][0]["n"], "clearing the lyric's region must remove line ink"
    assert r["frames"][0]["inR"] <= 6, f"lines drawn across the lyric block: {r['frames'][0]['inR']} px"


def test_powers_paints_the_map_on_the_base(ep, project):
    r = _draw(ep, project, VARIANTS[11][1], ts=[0, 1.5])
    f0, f1 = r["frames"]
    assert not f0["baseChanged"], "at its start the frame is the footage itself"
    assert f1["baseChanged"], "mid-zoom the map replaces the footage on the base (the lyric's ink must read the map)"
    # the map is NOT copied onto the overlay (the overlay skips the print pass: a copy would show the map unscreened)
    assert f1["n"] < .2 * (r["W"] // 2) * (r["H"] // 2), f"the overlay carries the map ({f1['n']} inked samples)"
    lum = ep.page.evaluate("""async (sh) => { const inst = DEV.instance({kind: 'powers', key: 'B', params: {levels: ['A', 'B', 'C']}}, sh), t = inst.t0 + 1.5;
      const c = DEV.mk(W, H), b = c.getContext('2d', {willReadFrequently: true}), O = DEV.mk(W, H), o = O.getContext('2d', {willReadFrequently: true});
      b.fillStyle = '#e8e8e8'; b.fillRect(0, 0, W, H); DEV.begin(t);
      await DEV.draw(o, b, inst, t, DEV.frame({t, sh, b, o, flashOk: () => true}));
      const d = b.getImageData(0, 0, W, H).data; let s = 0; for (let i = 0; i < d.length; i += 400) s += d[i]; return s / (d.length / 400); }""", _sh(project))
    assert lum < 90, f"the night map should darken a light base (mean {lum:.0f})"


# --------------------------------------------------------------------------------------------------- the 9:16 cut --
def test_portrait_blocks_inside_the_safe_margins(pw, project):
    page = _open(pw, project["dir"], w=1080, h=1920)
    try:
        bad, rope = [], None
        for name, spec in VARIANTS:
            r = page.page.evaluate(DRAW, [_sh(project), spec, [.6, 1.6], None])
            assert "err" not in r, (name, r)
            mg, W, H = r["mg"], r["W"], r["H"]
            for f in r["frames"]:
                for b in f["boxes"]:
                    x, y, w, h = b["box"]
                    if x < mg["l"] - 1 or y < mg["t"] - 1 or x + w > W - mg["r"] + 1 or y + h > H - mg["b"] + 1:
                        bad.append((name, b))
                    if b["kind"] == "rope":
                        rope = b
        assert not bad, bad
        assert rope, "the rope reports its block"
        # a quad the 9:16 crop cuts (its right half is outside the portrait frame) becomes a panel in a free slot
        q = page.page.evaluate(DRAW, [_sh(project), {"kind": "quad", "key": "B", "params": {"content": "sign", "quad": [[.7, .1], [.98, .1], [.98, .3], [.7, .3]], "lines": ["X"]}}, [.6], None])
        assert q["frames"][0]["boxes"] and q["frames"][0]["boxes"][0]["kind"] == "quad", q["frames"][0]
        assert any(b["kind"] == "quad.panel" for b in q["frames"][0]["boxes"]), "the panel records the box it actually covers"
        # a panel against the bottom of the safe area: its near edge grows with the perspective (most at the swing-in),
        # and what is drawn — not just the placed block — stays above the 420-px platform UI
        mg = q["mg"]
        for slot in ("bottom-left", "bottom-right", "top-left"):
            for big in (False, True):
                spec = {"kind": "quad", "anchor": {"slot": slot}, "key": "B", "params": {"content": "screen", "rows": ["A"], **({"w": 1400, "h": 900} if big else {})}}
                f = page.page.evaluate(DRAW, [_sh(project), spec, [0.0, .02, .08, .6], None])
                assert "err" not in f, f
                for fr in f["frames"]:
                    pan = [b for b in fr["boxes"] if b["kind"] == "quad.panel"]
                    assert pan, (slot, fr)
                    x, y, w, h = pan[0]["box"]
                    assert x >= mg["l"] - 1 and y >= mg["t"] - 1 and x + w <= f["W"] - mg["r"] + 1 and y + h <= f["H"] - mg["b"] + 1, (slot, big, fr["t"], pan[0], mg)
                    # the drawn ink stays inside it (2-px samples; the outline's anti-aliasing allowed)
                    if fr["box"]:
                        bx, by, bw, bh = fr["box"]
                        assert bx >= x - 3 and by >= y - 3 and bx + bw <= x + w + 3 and by + bh <= y + h + 3, (slot, big, fr["t"], fr["box"], pan[0])
        assert not page.errors, page.errors
    finally:
        page.close()


def test_whole_frames_with_the_new_devices(pw, tmp_path):
    """The new devices on real storyboard shots through the default renderer: frames render in both cuts with no device
    error, the budget holds (one hero), and the boot dry run reports nothing for them."""
    def tweak(shots):
        by = {s["id"]: s for s in shots}
        by["s01"]["devices"] = [VARIANTS[4][1]]                      # rope on the lead (layers treatment)
        by["s02"]["devices"] = [VARIANTS[0][1]]                      # a sign printed on the plate
        by["s04"]["devices"] = [VARIANTS[6][1]]                      # streamlines
        by["s05"]["devices"] = [VARIANTS[8][1]]                      # molecule
        by["s06"]["devices"] = [VARIANTS[11][1]]                     # powers of ten
        by["s09"]["devices"] = [VARIANTS[9][1]]                      # network
    proj = _synth().build(tmp_path / "newdev", tweak=tweak)
    for w, h in ((1920, 1080), (1080, 1920)):
        page = _open(pw, proj["dir"], w=w, h=h)
        try:
            warn = page.page.evaluate("() => ENGINE.info().deviceWarnings")
            mine = [x for x in warn if any(k in x for k in ("'quad'", "'rope'", "'streamlines'", "'molecule'", "'powers'", "'network'", "throws"))]
            assert not mine, mine
            shots = {s["id"]: s for s in proj["shots"]}
            for sid in ("s01", "s02", "s04", "s05", "s06", "s09"):
                s = shots[sid]
                for t in ((s["t0"] + s["t1"]) / 2, s["t1"] - .1):
                    page.frame_jpeg(t)
                    st = page.page.evaluate("() => Object.assign({}, window.DEV_FRAME, {errors: (window.DEV_ERRORS || []).slice(), L: ENGINE.frameLayers()})")
                    assert not st["errors"], (sid, t, st["errors"])
                    assert len(st["hero"]) <= 1, st
                    assert st["L"]["count"] >= 3, (sid, t, st["L"])
            assert not page.errors, page.errors
        finally:
            page.close()
