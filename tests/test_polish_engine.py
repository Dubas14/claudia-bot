"""engine track (Quick E2E polish): the collision rule and face-safe 2.5D, on the real engine page.

* THE COLLISION RULE — a lyric block is measured on every frame (DEV.type.measure, the mode's own layout) and nothing else
  covers it, in 16:9 and in 9:16: the lead's CV label ("LEAD · 01 0.97", the live defect: it sat under a lyric word)
  flips to another corner of its box; a cv.tag's / callout's rows flip; a panel asked onto the lyric (params x/y, a named
  slot) moves off it and is reported; the chrome items that would land on it are taken out (none of its ink is left there);
* FACE-SAFE 2.5D — a push with punch and snap zooms on a plate whose face sits near the image's top keeps the whole face
  box inside the frame, with headroom, at every frame (the engine's own mapper, and the face's pixels in the rendered
  frame); the same shot with `face_safe: false` does crop it (the case is real); layers / relight / stills / multiplane
  too, and the 9:16 cut;
* PLATE3D.safeCam on its own (the solver): untouched when safe, the framing moves first, the zoom is held only when it
  must be, a plate with no room above the head, a screen-space zoom after it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
MARGINS = {"landscape": {"l": 72, "t": 56, "r": 96, "b": 84}, "portrait": {"l": 72, "t": 180, "r": 150, "b": 420}}
SIZES = {"landscape": (1920, 1080), "portrait": (1080, 1920)}


def _synth():
    spec = importlib.util.spec_from_file_location("engine_devices_synth", ROOT / "tests" / "fixtures" / "engine_devices" / "synth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pw():
    for f in ("index.html", "src/shots.js", "src/plate3d.js", "src/devices/_base.js", "src/devices/type.js", "src/devices/cv.js", "src/devices/treat.js"):
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


FRAME = "async t => { await window.renderAt(t); return Object.assign({}, window.DEV_FRAME, {errors: (window.DEV_ERRORS || []).slice()}); }"


# ------------------------------------------------------------------------------------------- the collision rule ---
def _collision_board(root: Path, orient: str) -> dict:
    """Four shots on the synthetic project, one lyric line each (subtitles), built so the default layout collides:
    c01 the lead's mark with its label right on the subtitle block · c02 a cv.tag and a callout whose rows would sit on it ·
    c03 a terminal asked onto it (params x/y) and typed rows in the bottom-left slot (the subtitle raised into the slot) ·
    c04 a subtitle set up into the
    chrome's top row."""
    S = _synth()
    proj = S.build(root, boxes=False)
    beats = proj["beats"]
    bounds = [(0.0 if k == 0 else beats[4 * k], beats[4 * (k + 1)]) for k in range(4)]
    W, H = SIZES[orient]
    M = MARGINS[orient]
    base = H - M["b"] - 40                                            # the subtitle baseline (type.js DEF.sub)
    lead_uv = [0.1, 0.86, 0.6, 0.13] if orient == "landscape" else [0.38, 0.74, 0.24, 0.26]

    def shot(k, **kw):
        a, b = bounds[k]
        d = {"id": f"c{k + 1:02d}", "t0": round(a, 4), "t1": round(b, 4), "section": "verse", "lines": [k], "lead_on_screen": False,
             "framing": "WS", "camera": "static", "type": [{"line": k, "mode": "subtitle"}], "devices": [], "treatment": "push" if k % 2 == 0 else "stills",
             "transition_in": "cut"}
        d.update(kw)
        return d

    shots = [
        shot(0, lead_on_screen=True, subject_uv=lead_uv),
        shot(1, treatment={"family": "stills", "strip": False}, devices=[
            {"kind": "cv.tag", "anchor": {"xy": [180, base - 76]}, "key": "B", "params": {"beat": 0, "rows": ["UNIT 07 · ONLINE", "LOAD · 0.97"], "dx": 90, "dy": 50}},
            {"kind": "callout", "anchor": {"xy": [700, base - 96]}, "key": "B", "params": {"beat": 0, "rows": ["CORE · HOT"], "dx": -140, "dy": 90}}]),
        shot(2, type=[{"line": 2, "mode": "subtitle", "y": base - 60}], devices=[
            {"kind": "terminal", "key": "B", "params": {"beat": 0, "x": 80, "y": base - 200}},
            {"kind": "typed", "anchor": "bottom-left", "key": "B", "params": {"beat": 0, "rows": ["SRC · TEST ROWS", "PARAPHRASE"]}}]),
        shot(3, type=[{"line": 3, "mode": "subtitle", "y": M["t"] + 34}]),
    ]
    (root / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": S.DUR, "chapters": [], "shots": shots}), encoding="utf-8")
    (root / "edit" / "edl.json").write_text(json.dumps({s["id"]: {"plate": "p-flat"} for s in shots}), encoding="utf-8")
    return {"dir": root, "shots": shots, "lines": proj["lines"], "W": W, "H": H}


@pytest.mark.parametrize("orient", ["landscape", "portrait"])
def test_nothing_covers_the_lyric_block(pw, tmp_path, orient):
    proj = _collision_board(tmp_path / orient, orient)
    W, H = proj["W"], proj["H"]
    page = _open(pw, proj["dir"], w=W, h=H)
    try:
        seen = {"lead": [], "tag": [], "callout": [], "chrome": [], "panels": []}
        for k, sh in enumerate(proj["shots"]):
            ln = proj["lines"][k]
            for t in (ln["t0"] + .05, ln["t0"] + .3, (ln["t0"] + ln["t1"]) / 2, ln["t1"] - .02, min(sh["t1"] - .02, ln["t1"] + .4)):
                f = page.page.evaluate(FRAME, t)
                assert not f["errors"], (sh["id"], t, f["errors"])
                assert f["shot"] == sh["id"], (t, f["shot"])
                if not (f.get("lyric") and f["lyric"].get("box")):
                    continue
                rect, box = f["lyricRect"], f["lyric"]["box"]
                assert rect and _hit(rect, box) and rect[0] <= box[0] and rect[1] <= box[1] and rect[0] + rect[2] >= box[0] + box[2] \
                    and rect[1] + rect[3] >= box[1] + box[3], f"the measured block must hold the drawn one: {rect} vs {box}"
                blocks = [b["rect"] for b in f["lyricBlocks"]]
                # labels (CV labels, rows, chips, the strip): every rect off every block of the shot, inside the frame
                for lab in f["labels"]:
                    for r in lab["rects"]:
                        assert not any(_hit(r, q) for q in blocks), (sh["id"], round(t, 2), lab, blocks)
                        assert 0 <= r[0] and 0 <= r[1] and r[0] + r[2] <= W and r[1] + r[3] <= H, (sh["id"], lab)
                # panels (x.place): off the block drawn now
                for b in f["boxes"]:
                    assert not _hit(b["box"], rect), (sh["id"], round(t, 2), b, rect)
                    seen["panels"].append(b["kind"])
                if f["chrome"] is not None:
                    assert f["chrome"]["ink"] == 0, f"chrome ink left on the lyric block: {f['chrome']}"
                    seen["chrome"].append(f["chrome"]["cut"])
                for lab in f["labels"]:
                    for key in ("lead", "tag", "callout"):
                        if lab["kind"].startswith({"lead": "cv.lead", "tag": "cv.tag", "callout": "callout"}[key]):
                            seen[key].append(lab["spot"])
        # the live defect's case: the lead's label was right on the block; it is drawn, at another corner of its box
        assert seen["lead"] and all(s > 0 for s in seen["lead"]), f"the lead label must flip off the subtitle: {seen['lead']}"
        assert seen["tag"] and all(s > 0 for s in seen["tag"]), seen["tag"]
        assert seen["callout"] and all(s > 0 for s in seen["callout"]), seen["callout"]
        assert {"terminal", "typed"} <= set(seen["panels"]), seen["panels"]
        assert max(seen["chrome"]) >= 1, "the subtitle set into the chrome's top row must take that chrome item out"
        warn = [c for c in page.console if "would cover the lyric block" in c]
        assert any("'terminal' at its params x/y" in c for c in warn) and any("'typed' at its slot 'bottom-left'" in c for c in warn), warn
        assert not page.errors, page.errors
    finally:
        page.close()


def test_measure_matches_every_mode(pw, tmp_path):
    """DEV.type.measure holds what each mode really draws, over the line's whole time on screen (a masthead word by word,
    a coverline with its kicker and micro rows, a stack, a mass line), and draws nothing."""
    proj = _synth().build(tmp_path / "m", boxes=False)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate("""async () => {
          const D = DEV, out = {}, sh = {id: 'x', t0: 0, t1: 1e9};
          const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; };
          const modes = {sub: {line: 0, mode: 'subtitle'}, cover: {line: 1, mode: 'coverline', kicker: 'THE KICKER', micro: ['SRC · ONE', 'SRC · TWO']},
            mast: {line: 2, mode: 'masthead'}, macc: {line: 3, mode: 'masthead', accumulate: true, placement: 'right'}, stack: {line: 4, mode: 'stack', fit: 520},
            top: {line: 6, mode: 'subtitle', placement: 'top'}};
          for (const [k, en] of Object.entries(modes)) {
            const ln = D.line(en.line), X = D.frame({t: 0, sh, lead: [W * .6, H * .2, W * .2, H * .6]});
            const m = await D.type.measure({en, ln}, X); let worst = 0, n = 0;
            for (const tk of ln.tokens) for (const dt of [.001, .05, .2]) {
              const O = mk(), o = O.getContext('2d', {willReadFrequently: true}), t = tk.t0 + dt;
              const box = await D.type.entry(o, null, en, t, X); if (!box) continue; n++;
              const d = o.getImageData(0, 0, W, H).data; let x0 = W, y0 = H, x1 = -1, y1 = -1;
              for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) if (d[(y * W + x) * 4 + 3] > 24) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
              if (x1 < 0) continue;
              const out_ = Math.max(m[0] - x0, m[1] - y0, x1 - (m[0] + m[2]), y1 - (m[1] + m[3])); worst = Math.max(worst, out_);
            }
            out[k] = {m: m && m.map(Math.round), worst, n};
          }
          // a mass line's block is its sung line (the wall behind is its ground); the measure draws nothing
          const ln5 = D.line(5), X5 = D.frame({t: 0, sh});
          out.mass = {same: JSON.stringify(await D.type.measure({en: {line: 5, mode: 'mass'}, ln: ln5}, X5)) === JSON.stringify(await D.type.measure({auto: true, ln: ln5}, X5))};
          const before = (window.DRAWN && window.DRAWN.size) || 0; await D.type.measure({en: {line: 0, mode: 'coverline'}, ln: D.line(0)}, X5);
          out.marks = ((window.DRAWN && window.DRAWN.size) || 0) - before;
          return out; }""")
        assert r.pop("mass")["same"], "a mass line measures as its sung line"
        assert r.pop("marks") == 0, "measuring marks no lyric token (the gate counts drawn words only)"
        for k, v in r.items():
            assert v["m"] and v["n"] > 0, (k, v)
            assert v["worst"] <= 4, f"{k}: ink {v['worst']} px outside the measured block {v['m']}"
        assert not page.errors, page.errors
    finally:
        page.close()


# ------------------------------------------------------------------------------------------------ face-safe 2.5D ---
FACE = [0.44, 0.06, 0.12, 0.2]          # the face box (u, v, w, h): its top 6 % below the image's top edge
GREEN = (20, 235, 40)


def _face_plate(eng: Path):
    from PIL import Image, ImageDraw
    w, h = 960, 540
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            k = y / (h - 1)
            px[x, y] = (int(40 + 120 * k), int(48 + 60 * k), int(90 + 90 * k))
    d = ImageDraw.Draw(img)
    d.rectangle([0.36 * w, 0.2 * h, 0.64 * w, h], fill=(150, 96, 120))                    # the body
    d.rectangle([FACE[0] * w, FACE[1] * h, (FACE[0] + FACE[2]) * w - 1, (FACE[1] + FACE[3]) * h - 1], fill=GREEN)
    img.save(eng / "assets" / "plates" / "p-face.jpg", quality=95)
    dep = Image.new("L", (w // 4, h // 4), 50)
    dd = ImageDraw.Draw(dep)
    dd.rectangle([0.36 * w / 4, 0.2 * h / 4, 0.64 * w / 4, h / 4], fill=230)
    dd.rectangle([FACE[0] * w / 4, FACE[1] * h / 4, (FACE[0] + FACE[2]) * w / 4, (FACE[1] + FACE[3]) * h / 4], fill=240)
    dep.save(eng / "assets" / "plates" / "p-face.depth.png")
    js = (eng / "plates.js").read_text(encoding="utf-8")
    meta = json.loads(js[js.index("=") + 1:].strip().rstrip(";"))
    meta["p-face"] = {"boxes": {"a face": FACE + [0.95], "a woman": [0.36, 0.06, 0.28, 0.94, 0.9]}, "w": w, "subject_depth": 0.92,
                      "depth_model": "depth-anything-v2-small"}
    (eng / "plates.js").write_text("window.PLATES = " + json.dumps(meta) + ";\n", encoding="utf-8")


CAMS = [{"kind": "cam.punch", "params": {"amp": .04}}, {"kind": "cam.snap", "params": {"amp": .09}}]


def _face_board(root: Path) -> dict:
    S = _synth()
    proj = S.build(root, boxes=False)
    _face_plate(root / "engine")
    beats = proj["beats"]
    fams = [("push", True), ("layers", True), ({"family": "push", "face_safe": False}, False), ("relight", True), ("stills", True),
            ("multiplane", True)]
    shots, edl = [], {}
    for i, (tr, safe) in enumerate(fams):
        a, b = beats[2 + 4 * i], beats[2 + 4 * (i + 1)]
        sid = f"f{i + 1:02d}"
        shots.append({"id": sid, "t0": a, "t1": b, "section": "verse", "lines": [], "lead_on_screen": False, "framing": "MS",
                      "camera": "slow push in", "type": [], "devices": [dict(c, key="B") for c in CAMS], "treatment": tr,
                      "transition_in": "cut", "chrome": "off", "safe": safe})
        edl[sid] = {"plate": "p-face"}
    (root / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": S.DUR, "chapters": [], "shots": shots}), encoding="utf-8")
    (root / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    return {"dir": root, "shots": shots}


def _green_box(jpeg: bytes):
    from PIL import Image
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    w, h = im.size
    px = im.load()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if g > 150 and r < 120 and b < 120 and g - max(r, b) > 70:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys), len(xs)) if xs else None


@pytest.mark.parametrize("orient", ["landscape", "portrait"])
def test_push_keeps_the_face_in_frame(pw, tmp_path, orient):
    proj = _face_board(tmp_path / orient)
    W, H = (960, 540) if orient == "landscape" else (540, 960)
    page = _open(pw, proj["dir"], w=W, h=H)
    try:
        info = page.page.evaluate("() => ENGINE.info().treatments")
        fam = {t["id"]: t["drawn"] for t in info}
        assert fam["f01"] == "push" and fam["f03"] == "push" and fam["f02"] == "layers", fam
        cut_unsafe, whole, none = False, 0, 0
        for sh in proj["shots"]:
            n = max(2, int(round((sh["t1"] - sh["t0"]) * 24)))
            step = 1 if sh["id"] == "f01" else 2                                 # the push: every frame
            for i in range(0, n, step):
                t = sh["t0"] + (i + .5) / 24
                f = page.page.evaluate(FRAME, t)
                assert not f["errors"], (sh["id"], t, f["errors"])
                if not sh["safe"]:
                    assert f["face"] is None, "face_safe: false switches the guard off"
                    continue
                fb = f["face"]
                assert fb, (sh["id"], t, "the face box must be reported")
                x, y, w, h = fb
                inside = x >= -1 and y >= -1 and x + w <= W + 1 and y + h <= H + 1
                outside = x + w <= 1 or y + h <= 1 or x >= W - 1 or y >= H - 1
                if sh["id"] == "f05":                                            # stills: a crop shows all of the face or none of it
                    assert inside or outside, f"{sh['id']} t={t:.3f}: a crop cuts the face {fb}"
                    whole += inside
                    none += outside
                    continue
                assert inside, f"{sh['id']} t={t:.3f}: the face box {fb} leaves the {W}x{H} frame"
                if sh["id"] in ("f01", "f02"):
                    # headroom: the plate has 6 % above the face; the guard keeps it (less the snap's overscan)
                    assert y >= .03 * H, f"{sh['id']} t={t:.3f}: no headroom above the face ({fb})"
        # pixels: the face's own green in the rendered frame is whole (its top row below the frame's top) on the guarded
        # push at its tightest, and cut by the frame's top on the same push with face_safe: false
        for sh in proj["shots"]:
            if sh["id"] not in ("f01", "f03"):
                continue
            for t in (sh["t1"] - .5 / 24, sh["t0"] + (sh["t1"] - sh["t0"]) * .55):
                g = _green_box(page.frame_jpeg(t))
                assert g, (sh["id"], t, "the face must be in the frame")
                if sh["safe"]:
                    assert g[1] > 2 and g[0] > 2 and g[2] < W - 3 and g[3] < H - 3, f"{sh['id']} t={t:.3f}: the face pixels touch the frame edge {g}"
                elif g[1] <= 2:
                    cut_unsafe = True
        assert whole > 0, "the stills crops must show the face (wide, face, mid)"
        if orient == "landscape":
            assert cut_unsafe, "without the guard the push must crop the face (the test case is real)"
        assert not page.errors, page.errors
    finally:
        page.close()


def test_safe_cam_solver(pw, tmp_path):
    proj = _synth().build(tmp_path / "s", boxes=False)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate("""() => {
          const ia = 16 / 9, sv = (c, f, o) => PLATE3D.safeCam(c, ia, f, o || {});
          // the face's screen box (fractions) for a cam: plateMap's maths
          const scr = (c, f) => { const z = c.zoom, v = 1 / z, ox = Math.min(Math.max(c.cx, v / 2 + .01), 1 - v / 2 - .01), oy = Math.min(Math.max(c.cy, v / 2 + .01), 1 - v / 2 - .01);
            return [(f[0] - ox) * z + .5, (f[1] - oy) * z + .5, (f[0] + f[2] - ox) * z + .5, (f[1] + f[3] - oy) * z + .5]; };
          const out = {};
          const mid = [.45, .35, .1, .18]; out.safe = sv({zoom: 1.2, cx: .5, cy: .5}, mid);
          const top = [.45, .1, .1, .2]; out.top = sv({zoom: 1.3, cx: .5, cy: .5}, top); out.topScr = scr(out.top.cam, top);
          const tall = [.4, .1, .2, .8]; out.tall = sv({zoom: 1.6, cx: .5, cy: .5}, tall); out.tallScr = scr(out.tall.cam, tall);
          const edge = [.45, 0, .1, .2]; out.edge = sv({zoom: 1.3, cx: .5, cy: .5}, edge); out.edgeScr = scr(out.edge.cam, [.45, .01, .1, .19]);
          const side = [.85, .3, .09, .2]; out.side = sv({zoom: 1.4, cx: .5, cy: .5}, side); out.sideScr = scr(out.side.cam, side);
          const hi = [.45, .15, .1, .2]; out.outer = sv({zoom: 1.2, cx: .5, cy: .5}, hi, {outer: {s: 1.15, dx: 0, dy: 0, rot: 0}});
          const c = out.outer.cam, oy = c.cy, z = c.zoom; out.outerTop = .5 + 1.15 * ((hi[1] - Math.max(oy, .5 / z + .01)) * z);
          return out; }""")
        assert r["safe"]["ok"] and not r["safe"]["moved"], r["safe"]
        assert r["top"]["ok"] and not r["top"]["held"] and r["top"]["cam"]["cy"] < .5, "the framing moves up to the face first"
        assert r["topScr"][1] >= .06 - 1e-6 and r["topScr"][3] <= .97 + 1e-6, r["topScr"]
        assert r["tall"]["held"] and r["tall"]["cam"]["zoom"] < 1.6 and r["tallScr"][1] >= -1e-6 and r["tallScr"][3] <= 1 + 1e-6, r["tall"]
        assert r["edge"]["ok"] and r["edgeScr"][1] >= -1e-6 and r["edgeScr"][3] <= 1, "a head at the image's top edge: inside, with the headroom the plate has"
        assert r["side"]["ok"] and r["sideScr"][2] <= .97 + 1e-6 and r["sideScr"][0] >= 0, r["sideScr"]
        assert r["outer"]["ok"] and r["outerTop"] >= .06 - 1e-6, f"a screen-space zoom after the camera is framed for too: {r['outerTop']}"
        assert all(math.isfinite(v) for v in r["outer"]["cam"].values() if isinstance(v, (int, float)))
        assert not page.errors, page.errors
    finally:
        page.close()
