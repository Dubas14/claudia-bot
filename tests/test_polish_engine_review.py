"""engine track, adversarial review: the defects found by exercising the collision rule and the face-safe camera on a real
project and on boards built to break them, each pinned here (both orientations where it matters).

* the `stills` contact strip gives way to the devices: it moved off the lyric onto a counter in 9:16 (and sat under
  typed rows in its bottom-right spot in 16:9) — now a device box or label on its spot leaves it out of that frame;
* the chrome never leaves ink on the lyric block, at every frame (the cut tested the block's fractional edge, the ink
  count whole pixels: a ruler number one row above the block stayed) — and a chrome item of any height goes whole;
* the face stays in frame under `cam.impact` + `cam.shake` (their overscan and burst cut a face near the plate's edge
  by a third: no framing makes room for a shake) — the shake is calmed just enough, every family, both orientations;
* PLATE3D.safeCam says whether the face fits through the screen-space camera (`fits`), framing a shake for its worst;
* a panel with no room off the lyric is reported (it covered the lyric silently); leaders keep a clear way.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920)}
FRAME = ("async t => { await window.renderAt(t); return Object.assign({}, window.DEV_FRAME, "
         "{errors: (window.DEV_ERRORS || []).slice()}); }")


def _synth():
    spec = importlib.util.spec_from_file_location("engine_devices_synth", ROOT / "tests" / "fixtures" / "engine_devices" / "synth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pw():
    for f in ("index.html", "src/shots.js", "src/plate3d.js", "src/devices/_base.js", "src/devices/cv.js", "src/devices/treat.js"):
        if not (ENGINE / f).is_file():
            pytest.skip(f"engine file missing: engine/{f}")
    pytest.importorskip("PIL")
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


def _open(p, pdir, **kw):
    from slop.render.browser import EnginePage
    from slop.render.project import page_spec
    try:
        return EnginePage(p, page_spec(pdir, **kw))
    except Exception as e:  # noqa: BLE001 — no headless browser on this machine
        pytest.skip(f"no headless browser: {e}")


def _hit(a, b) -> bool:
    return min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]) > 0 and min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]) > 0


def _board(root: Path, shots: list[dict], plates: list[str]) -> None:
    S = _synth()
    (root / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": S.DUR, "chapters": [], "shots": shots}), encoding="utf-8")
    (root / "edit" / "edl.json").write_text(json.dumps({s["id"]: {"plate": pl} for s, pl in zip(shots, plates)}), encoding="utf-8")


def _shots(beats, specs):
    out = []
    for k, kw in enumerate(specs):
        a, b = (0.0 if k == 0 else beats[4 * k]), beats[4 * (k + 1)]
        d = {"id": f"r{k + 1:02d}", "t0": round(a, 4), "t1": round(b, 4), "section": "verse", "lines": [k], "lead_on_screen": False,
             "framing": "MS", "camera": "slow push in", "type": [{"line": k, "mode": "subtitle"}], "devices": [], "treatment": "push",
             "transition_in": "cut"}
        d.update(kw)
        out.append(d)
    return out


# ------------------------------------------------------------------------------------- the strip and the devices ---
@pytest.mark.parametrize("orient", ["landscape", "portrait"])
def test_stills_strip_gives_way_to_devices(pw, tmp_path, orient):
    root = tmp_path / orient
    proj = _synth().build(root, boxes=False)
    shots = _shots(proj["beats"], [dict(treatment={"family": "stills", "loop": True}, devices=[
        {"kind": "counter", "anchor": "top-right", "key": "B", "params": {"beat": 0, "from": 0, "to": 13, "beats": 1, "label": "BOXES", "size": 40}},
        {"kind": "typed", "anchor": "bottom-right", "key": "B", "params": {"beat": 1, "rows": ["SRC · ROWS ON THE RIGHT", "TWO"]}}])])
    _board(root, shots, ["p-a"])
    W, H = SIZES[orient]
    page = _open(pw, root, w=W, h=H)
    try:
        sh, drawn, gave = shots[0], 0, 0
        for i in range(10):
            t = sh["t0"] + (sh["t1"] - sh["t0"]) * (i + .5) / 10
            f = page.page.evaluate(FRAME, t)
            assert not f["errors"], f["errors"]
            strip = [lab for lab in f["labels"] if lab["kind"] == "stills:strip"]
            assert len(strip) == 1, f["labels"]
            busy = [b["box"] for b in f["boxes"]] + [r for lab in f["labels"] if lab["kind"] != "stills:strip" and lab["spot"] >= 0 for r in lab["rects"]]
            if strip[0]["spot"] >= 0:
                drawn += 1
                assert f["strip"] is True
                assert not any(_hit(strip[0]["box"], q) for q in busy), (round(t, 2), strip[0], f["boxes"])
                assert not any(_hit(strip[0]["box"], q["rect"]) for q in f["lyricBlocks"]), "the strip keeps off the lyric"
            else:
                assert f["strip"] is False
                gave += any(b["kind"] in ("counter", "typed") for b in f["boxes"])
        assert gave > 0, "a device on the strip's spot must take it"
        if orient == "landscape":
            assert drawn > 0, "before the typed rows come in the strip draws at its spot (bottom-right)"
        assert not page.errors, page.errors
    finally:
        page.close()


# ------------------------------------------------------------------------------------------- chrome off the lyric ---
@pytest.mark.parametrize("orient", ["landscape", "portrait"])
def test_chrome_ink_never_left_on_the_lyric(pw, tmp_path, orient):
    """A 'full' chrome (its ruler's bar numbers scroll past the subtitle's padded block): every frame of the shot, no
    chrome pixel is left on the block, whatever row a number lands on."""
    root = tmp_path / orient
    proj = _synth().build(root, boxes=False)
    shots = _shots(proj["beats"], [{"chrome": "full"}, {"chrome": "full", "type": [{"line": 1, "mode": "coverline", "placement": "top"}]}])
    _board(root, shots, ["p-a", "p-b"])
    W, H = SIZES[orient]
    page = _open(pw, root, w=W, h=H)
    try:
        cuts = n = 0
        for sh in shots:
            t = sh["t0"] + .02
            while t < sh["t1"]:
                f = page.page.evaluate(FRAME, t)
                if f.get("chrome") is not None and f.get("lyric"):
                    n += 1
                    assert f["chrome"]["ink"] == 0, (sh["id"], round(t, 4), f["chrome"])
                    cuts += f["chrome"]["cut"] > 0
                t += 1 / 24
        assert n > 40 and cuts > 0, (n, cuts)
        assert not page.errors, page.errors
    finally:
        page.close()


def test_chrome_item_of_any_height_goes_whole(pw, tmp_path):
    """A project chrome with a full-height line through the lyric block: the whole line is taken out (not just the part
    near the block), the rest of the chrome stays."""
    from PIL import Image
    root = tmp_path / "tall"
    proj = _synth().build(root, boxes=False)
    shots = _shots(proj["beats"], [{"chrome": "min"}])
    _board(root, shots, ["p-a"])
    page = _open(pw, root, w=960, h=540)
    try:
        sh = shots[0]
        t = proj["lines"][0]["tokens"][-1]["t0"] + .1
        x = page.page.evaluate("""async t => { await window.renderAt(t); const r = DEV_FRAME.lyricRect, x = Math.round(r[0] + r[2] / 2);
          window.chrome = (g, tt, o) => { ENGINE.chrome(g, tt, o); g.save(); g.fillStyle = '#00ff00'; g.fillRect(x - 2, 0, 5, H); g.fillRect(W - 60, 10, 40, 6); g.restore(); };
          return x; }""", t)
        f = page.page.evaluate(FRAME, t)
        assert f["chrome"]["cut"] >= 1 and f["chrome"]["ink"] == 0, f["chrome"]
        im = Image.open(io.BytesIO(page.frame_jpeg(t))).convert("RGB")
        green = lambda p: p[1] > 180 and p[0] < 110 and p[2] < 110  # noqa: E731
        col = [im.getpixel((x, y)) for y in range(0, 540, 3)]
        assert not any(green(p) for p in col), "the full-height line must go whole, above and below the block too"
        assert green(im.getpixel((960 - 40, 13))), "the chrome items away from the block stay"
        assert sh["id"] == f["shot"]
        assert not page.errors, page.errors
    finally:
        page.close()


# ------------------------------------------------------------------------------------------ face-safe and shake ---
EDGE = [0.04, 0.05, 0.12, 0.22]        # a face near the plate's LEFT and TOP edges


def _edge_plate(eng: Path):
    from PIL import Image, ImageDraw
    w, h = 960, 540
    img = Image.new("RGB", (w, h), (60, 80, 120))
    d = ImageDraw.Draw(img)
    d.rectangle([0, .25 * h, .2 * w, h], fill=(150, 96, 120))
    d.rectangle([EDGE[0] * w, EDGE[1] * h, (EDGE[0] + EDGE[2]) * w - 1, (EDGE[1] + EDGE[3]) * h - 1], fill=(20, 235, 40))
    img.save(eng / "assets" / "plates" / "p-edge.jpg", quality=95)
    dep = Image.new("L", (w // 4, h // 4), 50)
    ImageDraw.Draw(dep).rectangle([0, .05 * h / 4, .2 * w / 4, h / 4], fill=235)
    dep.save(eng / "assets" / "plates" / "p-edge.depth.png")
    js = (eng / "plates.js").read_text(encoding="utf-8")
    meta = json.loads(js[js.index("=") + 1:].strip().rstrip(";"))
    meta["p-edge"] = {"boxes": {"a face": EDGE + [0.95]}, "w": w, "subject_depth": 0.92, "depth_model": "depth-anything-v2-small"}
    (eng / "plates.js").write_text("window.PLATES = " + json.dumps(meta) + ";\n", encoding="utf-8")


SHAKE = [{"kind": "cam.impact", "params": {"amp": .12, "minS": 0}}, {"kind": "cam.shake", "params": {"amp": 10}}, {"kind": "cam.punch", "params": {"amp": .05}}]


@pytest.mark.parametrize("orient", ["landscape", "portrait"])
def test_face_stays_in_under_impact_and_shake(pw, tmp_path, orient):
    root = tmp_path / orient
    proj = _synth().build(root, boxes=False)
    _edge_plate(root / "engine")
    beats = proj["beats"]
    fams = [("push", True), ("relight", True), ({"family": "push", "face_safe": False}, False), ("stills", True), ("multiplane", True)]
    shots = []
    for i, (tr, safe) in enumerate(fams):
        a, b = beats[2 + 4 * i], beats[2 + 4 * (i + 1)]
        shots.append({"id": f"k{i + 1:02d}", "t0": a, "t1": b, "section": "verse", "lines": [], "lead_on_screen": False, "framing": "MS",
                      "camera": "pan left" if i % 2 == 0 else "tilt up", "type": [], "devices": [dict(c, key="B") for c in SHAKE],
                      "treatment": tr, "transition_in": "cut", "chrome": "off", "safe": safe})
    _board(root, shots, ["p-edge"] * len(shots))
    W, H = (960, 540) if orient == "landscape" else (540, 960)
    page = _open(pw, root, w=W, h=H)
    try:
        calmed, cut_unsafe = 0, False
        for sh in shots:
            n = max(2, int(round((sh["t1"] - sh["t0"]) * 24)))
            for i in range(0, n, 2):
                t = sh["t0"] + (i + .5) / 24
                f = page.page.evaluate(FRAME, t)
                assert not f["errors"], (sh["id"], f["errors"])
                if not sh["safe"]:
                    assert f["face"] is None, "face_safe: false switches the guard off"
                    continue
                x, y, w, h = f["face"]
                inside = x >= -1 and y >= -1 and x + w <= W + 1 and y + h <= H + 1
                outside = x + w <= 1 or y + h <= 1 or x >= W - 1 or y >= H - 1
                if sh["treatment"] == "stills":
                    assert inside or outside, f"{sh['id']} t={t:.3f}: a crop cuts the face {f['face']}"
                else:
                    assert inside, f"{sh['id']} t={t:.3f}: the face {f['face']} leaves the {W}x{H} frame (calm {f['faceCalm']})"
                calmed += f["faceCalm"] is not None and f["faceCalm"] < 1
        assert calmed > 0, "the shake must have been calmed somewhere (the case is real)"
        # the guard off: the same moves cut the face (the face's own pixels touch the frame edge)
        from PIL import Image
        sh = next(s for s in shots if not s["safe"])
        for i in range(0, max(2, int(round((sh["t1"] - sh["t0"]) * 24))), 3):
            im = Image.open(io.BytesIO(page.frame_jpeg(sh["t0"] + (i + .5) / 24))).convert("RGB")
            px = im.load()
            g = [(x, y) for y in range(0, H, 2) for x in range(0, W, 2) if px[x, y][1] > 150 and px[x, y][0] < 120 and px[x, y][2] < 120]
            if g and (min(p[0] for p in g) <= 2 or min(p[1] for p in g) <= 2):
                cut_unsafe = True
                break
        assert cut_unsafe, "without the guard the shake must cut the face (the test case is real)"
        assert not page.errors, page.errors
    finally:
        page.close()


def test_safe_cam_fits_and_helpers(pw, tmp_path):
    proj = _synth().build(tmp_path / "s", boxes=False)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate("""() => {
          const ia = 16 / 9, sv = (c, f, o) => PLATE3D.safeCam(c, ia, f, o || {}), out = {};
          const edge = [.04, .05, .12, .22], mid = [.45, .35, .1, .18];
          out.plain = sv({zoom: 1.1, cx: .5, cy: .5}, edge).fits;
          out.shaken = sv({zoom: 1.1, cx: .5, cy: .5}, edge, {outer: {s: 1.1, jx: 24, jy: 22, jr: .008}}).fits;
          const m = sv({zoom: 1.2, cx: .5, cy: .5}, mid, {outer: {s: 1.08, jx: 20, jy: 20}}); out.mid = m.fits;
          // the face's screen box at the shake's worst offsets, through the outer zoom
          const c = m.cam, z = c.zoom, v = 1 / z, ox = Math.min(Math.max(c.cx, v / 2 + .01), 1 - v / 2 - .01), oy = Math.min(Math.max(c.cy, v / 2 + .01), 1 - v / 2 - .01);
          const S = (p, o, d) => .5 + (((p - o) * z + .5) - .5) * 1.08 + d;
          out.worst = [S(mid[0], ox, -20 / W), S(mid[1], oy, -20 / H), S(mid[0] + mid[2], ox, 20 / W), S(mid[1] + mid[3], oy, 20 / H)];
          const X = {avoid: [[100, 100, 200, 100]]};
          out.lines = [DEV.lineHits(X.avoid, [0, 150, 400, 150]), DEV.lineHits(X.avoid, [0, 50, 400, 50]), DEV.lineHits(X.avoid, [0, 0, 400, 400]),
            DEV.clearPath(X, [150, 150, 400, 150]), DEV.clearPath(X, [50, 150, 400, 150])];
          return out; }""")
        assert r["plain"] == "face", r
        assert r["shaken"] is False, "a face at the plate's edge cannot fit a 10 % overscan and a shake"
        assert r["mid"] == "face" and min(r["worst"]) >= -1e-6 and max(r["worst"]) <= 1 + 1e-6, r
        assert r["lines"] == [True, False, True, True, False], r["lines"]
        assert not page.errors, page.errors
    finally:
        page.close()


# --------------------------------------------------------------------------------------- reports and leaders -------
def test_no_room_off_the_lyric_is_reported(pw, tmp_path):
    root = tmp_path / "full"
    proj = _synth().build(root, boxes=False)
    shots = _shots(proj["beats"], [{}, {"type": [{"line": 1, "mode": "stack", "fit": 900}], "devices": [{"kind": "chart", "key": "B", "params": {"beat": 0}}]}])
    _board(root, shots, ["p-a", "p-b"])
    page = _open(pw, root, w=1080, h=1920)
    try:
        sh = shots[1]
        f = page.page.evaluate(FRAME, (sh["t0"] + sh["t1"]) / 2)
        assert any(b["kind"] == "chart" for b in f["boxes"]), f["boxes"]
        assert any("'chart' finds no room off the lyric block" in c for c in page.console), page.console
        assert not page.errors, page.errors
    finally:
        page.close()


def test_leaders_keep_a_clear_way_and_gauge_anchor(pw, tmp_path):
    """Devices drawn alone (DEV.draw) against a lyric block [600, 200, 400, 200]:
    * a leader whose chip fits nowhere, and a cv.tag whose rows fit nowhere, aimed INTO the block: the bare line takes the
      way that stays clear of it (before: it ran up to the block's edge, clipped there);
    * a gauge tag with every flip blocked, moved by x.place to the one hole and shrunk to .8 there: its anchor ring is
      still drawn on the anchor (before: in the shrunk space, 50-odd px off)."""
    proj = _synth().build(tmp_path / "u", boxes=False)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate("""async () => {
          const sh = {id: 'u', t0: 0, t1: 10}, t = 2, mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
          const green = (o, x0, y0, x1, y1) => { const d = o.getImageData(x0, y0, x1 - x0, y1 - y0).data; let n = 0;
            for (let i = 0; i < d.length; i += 4) if (d[i + 1] > 180 && d[i] < 100 && d[i + 2] < 100 && d[i + 3] > 100) n++; return n; };
          const run = async (spec, avoid) => { DEV.begin(t); const B = mk(), O = mk(), b = B.getContext('2d', {willReadFrequently: true}), o = O.getContext('2d', {willReadFrequently: true});
            b.fillStyle = '#444'; b.fillRect(0, 0, W, H); const inst = DEV.instance(Object.assign({key: 'F', at: 0, until: 10}, spec), sh);
            const X = DEV.frame({t, sh, b, o}); X.avoidNow = avoid; X.avoid = avoid.slice(); X.avoidFor = () => avoid;
            await DEV.draw(o, b, inst, t, X); return {o, X}; };
          const block = [[600, 200, 400, 200]], out = {};
          let R = await run({kind: 'leader', anchor: {xy: [400, 300]}, params: {dx: 300, dy: 0, color: '#00ff00', label: 'X'.repeat(120)}}, block);
          out.leader = {right: green(R.o, 410, 290, 600, 310), left: green(R.o, 100, 290, 390, 310), chip: R.X.labels.map(l => l.spot)};
          R = await run({kind: 'cv.tag', anchor: {xy: [400, 300]}, params: {dx: 300, dy: 0, color: '#00ff00', rows: ['R'.repeat(160)]}}, block);
          out.tag = {right: green(R.o, 410, 290, 600, 310), left: green(R.o, 60, 290, 390, 310), rows: R.X.labels.map(l => l.spot)};
          // the gauge: a hole [1130, 300, 190, 80] (too small for its 214 x 92 tag, room at .8), everything else blocked
          const hole = [[0, 0, W, 300], [0, 380, W, H - 380], [0, 300, 1130, 80], [1320, 300, W - 1320, 80]];
          R = await run({kind: 'gauge', anchor: {rect: [600, 300, 500, 400]}, params: {style: 'tag', value: 4, max: 10, label: 'LOAD', color: '#00ff00'}}, hole);
          out.gauge = {boxes: R.X.boxes.map(e => ({box: e.box.map(Math.round), scale: e.scale})), tag: R.X.labels.map(l => l.spot),
            ring: green(R.o, 840, 490, 861, 511), old: green(R.o, 896, 450, 917, 471)};
          return out; }""")
        assert r["leader"]["chip"] == [-1], r["leader"]
        assert r["leader"]["right"] == 0 and r["leader"]["left"] > 20, f"the bare leader must go the clear way: {r['leader']}"
        assert r["tag"]["rows"] == [-1], r["tag"]
        assert r["tag"]["right"] == 0 and r["tag"]["left"] > 20, f"the bare tag leader must go the clear way: {r['tag']}"
        g = r["gauge"]
        assert g["tag"] == [-1] and len(g["boxes"]) == 1 and abs(g["boxes"][0]["scale"] - .8) < 1e-6, g
        assert g["ring"] > 6, f"the anchor ring must be on the anchor (850, 500): {g}"
        assert not page.errors, page.errors
    finally:
        page.close()
