"""devices track: the default renderer's 2.5D treatments and its QA hooks, on the real engine page.

* a board that leaves `treatment` empty gets one picked for every 2.5D shot, never the same family back to back, and any
  run of five picked shots covers the guide's five families (LS DI RP SR DG) — in the native look (reproduction as the
  clean mosaic / tiles) and in the print look; without depth maps the four families a flat plate supports; an asked
  treatment is never rotated away by a pick; a shot whose hero is pinned into the picture never gets stills;
* the new families draw: multiplane (its subject plane is m.matte(); no exposed frame edge while the planes drift) and
  tiles (split-flap reproduction), deterministically;
* clean or print is decided per shot (a `screen: "native"` shot in a print film is clean, and the reverse); a reproduction
  kind nobody knows is reported and drawn as the look's own; warnings quote the board's own treatment value;
* a multiplane plate with no subject plane is reported at boot (and its neighbour when that draws layers too), and the
  plan's treatments say it draws layers;
* one layer counter: ENGINE.info() has no `layers` of its own; core's ENGINE.frameLayers() agrees with what DEV_FRAME
  says drew (a device whose params leave it nothing to draw is no layer);
* ENGINE.info().chapterScenes / chapterShots: scenes registered by bespoke chapter code.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
FIVE = {"LS", "DI", "RP", "SR", "DG"}


def _synth():
    spec = importlib.util.spec_from_file_location("engine_devices_synth", ROOT / "tests" / "fixtures" / "engine_devices" / "synth.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _need_engine():
    for f in ("index.html", "src/shots.js", "src/devices/index.js", "src/devices/treat.js"):
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
def pw():
    _need_engine()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


def _board(root: Path, plates, asked=None, devices=None, look="native", layer_js=None, beats_per_shot=3):
    """The synthetic project (accelerating beat map, plates with/without depth), its board replaced by `len(plates)` shots
    of `beats_per_shot` beats each with no treatment (unless asked[i]), one plate per shot."""
    S = _synth()
    proj = S.build(root, look=look)
    beats, _ = S.beat_map()
    shots, edl = [], {}
    for i, pl in enumerate(plates):
        a, b = (0.0 if i == 0 else beats[i * beats_per_shot]), beats[(i + 1) * beats_per_shot]
        sh = {"id": f"t{i + 1:02d}", "t0": a, "t1": b, "section": "verse", "lines": [], "lead_on_screen": False, "framing": "MS",
              "camera": "slow push in", "type": [], "devices": list((devices or {}).get(i, [])), "transition_in": "cut"}
        if asked and asked.get(i) is not None:
            sh["treatment"] = asked[i]
        shots.append(sh)
        edl[sh["id"]] = {"plate": pl} if pl else {"segs": [{"t0": a, "clip": "c1", "in": 0.0}]}
    (root / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": S.DUR, "chapters": [], "shots": shots}), encoding="utf-8")
    (root / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    if layer_js:
        (root / "engine" / "scenes.js").write_text(layer_js, encoding="utf-8")
    return {"dir": root, "shots": shots, "beats": beats}


PLAN = """() => { const P = SHOTS_PLAN(); return {warn: P.warn, clean: P.clean,
  list: P.list.filter(S => !S.sh.gap).map(S => ({id: S.id, fam: S.treat.family, kind: S.treat.params.kind || null, code: S.treat.code, base: S.treat.base, auto: !!S.treat.auto,
    flash: S.treat.params.flash ?? null})), info: ENGINE.info().treatments}; }"""


def _runs_cover(seq, k=5):
    return all(len({c for c in seq[i:i + k]}) == k for i in range(len(seq) - k + 1))


@pytest.mark.parametrize("look", ["native", "print"])
def test_auto_pick_covers_the_five_families(pw, tmp_path, look):
    plates = ["p-a", "p-b", "p-c"] * 5 + ["p-a", "p-b"]                 # 17 depth plates, 3 beats each, no treatment asked
    proj = _board(tmp_path / look, plates, look=look)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate(PLAN)
        L = r["list"]
        assert len(L) == 17 and all(s["auto"] for s in L), L
        fams, codes = [s["fam"] for s in L], [s["code"] for s in L]
        assert all(a != b for a, b in zip(fams, fams[1:])), fams
        assert all(a != b for a, b in zip(codes, codes[1:])), codes
        assert set(codes) == FIVE and _runs_cover(codes), codes
        rp = {s["kind"] for s in L if s["code"] == "RP"}
        if look == "native":
            assert r["clean"] and rp <= {"mosaic", "tiles"} and len(rp) == 2, rp
        else:
            assert not r["clean"] and rp <= {"xerox", "thermal", "mosaic", "tiles"} and len(rp) >= 2, rp
        assert {s["fam"] for s in L if s["code"] == "LS"} == {"layers", "multiplane", "rack"}
        assert {s["fam"] for s in L if s["code"] == "DI"} == {"relight", "scan", "contours"}
        assert all(s["flash"] is False for s in L if s["fam"] == "stills"), "picked stills cut without the crop flash"
        assert not any("treatment" in w for w in r["warn"]), r["warn"]
        assert [(t["id"], t["family"], t["code"], t["auto"]) for t in r["info"]] == [(s["id"], s["fam"], s["code"], True) for s in L]
        # every picked treatment renders
        for s in proj["shots"][:10]:
            page.frame_jpeg((s["t0"] + s["t1"]) / 2)
            st = page.page.evaluate("() => ({f: window.DEV_FRAME, e: (window.DEV_ERRORS || []).slice()})")
            assert not st["e"], (s["id"], st["e"])
        assert not page.errors, page.errors
    finally:
        page.close()


def test_without_depth_and_with_asked_treatments(pw, tmp_path):
    # flat plates (no depth): LS is a push, DI is out → the four families a flat plate supports, no repeats
    flat = _board(tmp_path / "flat", ["p-flat"] * 10)
    page = _open(pw, flat["dir"])
    try:
        L = page.page.evaluate(PLAN)["list"]
        codes = [s["code"] for s in L]
        assert set(codes) == {"LS", "RP", "SR", "DG"} and _runs_cover(codes, 4), codes
        assert all(a != b for a, b in zip(codes, codes[1:]))
    finally:
        page.close()
    # asked treatments: kept as asked (the pick before never takes the next shot's asked family), clips break no rule,
    # and a shot whose hero is pinned into the picture (streamlines) never gets stills
    asked = {2: "relight", 3: "stills", 7: "layer-separation", 9: {"family": "reproduction", "kind": "tiles"}}
    pin = {"kind": "streamlines", "key": "B", "params": {"seeds": 6}}
    mixed = _board(tmp_path / "mixed", ["p-a", "p-b", "p-c", "p-a", None, "p-b", "p-c", "p-a", "p-b", "p-c", "p-a", "p-b"], asked=asked,
                   devices={i: [pin] for i in (0, 1, 5, 6, 10, 11)})
    page = _open(pw, mixed["dir"])
    try:
        r = page.page.evaluate(PLAN)
        L = {s["id"]: s for s in r["list"]}
        assert L["t03"]["fam"] == "relight" and L["t04"]["fam"] == "stills" and L["t08"]["fam"] == "layers"
        assert L["t10"]["fam"] == "xerox" and L["t10"]["kind"] == "tiles"
        assert not any("repeats" in w for w in r["warn"]), r["warn"]
        assert L["t05"]["base"] == "clip"
        for i in (0, 1, 5, 6, 10, 11):
            assert L[f"t{i + 1:02d}"]["fam"] != "stills", (i, L[f"t{i + 1:02d}"])
        seq = [s for s in r["list"] if s["base"] == "plate"]
        assert all(a["fam"] != b["fam"] for a, b in zip(seq, seq[1:])), [s["fam"] for s in seq]
    finally:
        page.close()


def test_multiplane_and_tiles_draw(pw, tmp_path):
    proj = _board(tmp_path / "mp", ["p-a", "p-b", "p-c", "p-a"], asked={0: "multiplane", 1: {"family": "reproduction", "kind": "tiles"},
                                                                         2: {"family": "multiplane", "dir": "v", "amount": .05}, 3: "planes"}, beats_per_shot=6)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate("""async () => { const P = SHOTS_PLAN(), out = [];
          for (const S of P.list.filter(S => !S.sh.gap)) {
            const c = DEV.mk(W, H), b = c.getContext('2d', {willReadFrequently: true}), O = DEV.mk(W, H), o = O.getContext('2d', {willReadFrequently: true});
            const res = {id: S.id, fam: S.treat.family, kind: S.treat.params.kind || null, edgeBlack: 0, matte: null};
            for (const k of [0, .25, .5, .75, .99]) { const t = S.t0 + (S.t1 - S.t0) * k; b.reset(); b.fillStyle = '#000'; b.fillRect(0, 0, W, H); DEV.begin(t);
              const X = DEV.frame({t, sh: S.sh, b, o, flashOk: () => true});
              const m = await DEV.treat.draw(b, o, S, t, {zoom: 1.06, cx: .5, cy: .5, x: .01}, {}, X);
              if (S.treat.family === 'multiplane') { const d = b.getImageData(0, 0, W, H).data, black = (x, y) => { const i = (y * W + x) * 4; return d[i] + d[i + 1] + d[i + 2] < 6; };
                for (const y of [0, 1, H - 2, H - 1]) for (let x = 0; x < W; x++) if (black(x, y)) res.edgeBlack++;      // whole border rows
                for (const x of [0, 1, W - 2, W - 1]) for (let y = 0; y < H; y++) if (black(x, y)) res.edgeBlack++;      // and columns
                if (k === .5 && m && m.matte) { const mt = await m.matte(); if (mt) { const md = mt.getContext('2d').getImageData(0, 0, mt.width, mt.height).data; let n = 0; for (let i = 3; i < md.length; i += 16) if (md[i] > 128) n++; res.matte = n / (md.length / 16); } } }
            }
            out.push(res);
          }
          return {out, errs: (window.DEV_ERRORS || []).slice(), warn: P.warn}; }""")
        assert not r["errs"], r["errs"]
        mp = [x for x in r["out"] if x["fam"] == "multiplane"]
        assert len(mp) == 2 and any("t04: treatment 'planes' (draws as multiplane) repeats" in w for w in r["warn"]), (r["out"], r["warn"])   # 'planes' = multiplane: a repeat, quoted as written
        for x in mp:
            assert x["edgeBlack"] == 0, f"{x['id']}: a plane's drift exposed the frame edge"
            assert x["matte"] is not None and .005 < x["matte"] < .8, f"{x['id']}: the subject plane is the matte ({x['matte']})"
        assert any(x["kind"] == "tiles" for x in r["out"])
        # deterministic whole frames (out of order, and against a fresh page)
        ts = [(s["t0"] + s["t1"]) / 2 for s in proj["shots"]] + [proj["shots"][2]["t0"] + .3]
        first = [page.frame_jpeg(t) for t in ts]
        again = [page.frame_jpeg(t) for t in reversed(ts)][::-1]
        assert first == again, "same t must give the same pixels whatever was rendered before"
    finally:
        page.close()
    fresh = _open(pw, proj["dir"])
    try:
        assert [fresh.frame_jpeg(t) for t in ts] == first, "a fresh page must render the same pixels"
    finally:
        fresh.close()


CHAPTER = """// a bespoke chapter scene over the second shot (test fixture)
(() => { const sh = (window.SHOTS || window.SHOTLIST || {}).shots[1];
  scene('chapter-one', sh.t0, sh.t1, async (b, o, t) => { b.fillStyle = '#334'; b.fillRect(0, 0, W, H); return {}; }); })();
"""


FRAME = """() => { const d = window.DEV_FRAME || {}, L = ENGINE.frameLayers() || {};
  return {shot: d.shot, hero: d.hero || [], flash: d.flash || [], cv: d.cv || [], micro: d.micro || [], treatment: d.treatment,
          drawnAs: d.drawnAs || null, L: L.layers || [], count: L.count, Lshot: L.shot ?? null, errors: (window.DEV_ERRORS || []).slice()}; }"""


def _agree(st):
    """What DEV_FRAME says drew and what the one layer counter (core's ENGINE.frameLayers) counts agree."""
    L = set(st["L"])
    if st["hero"] or st["flash"]:
        assert "graphic" in L, st
    assert ("annotation" in L) == bool(st["cv"]), st
    assert ("micro" in L) == bool(st["micro"]), st


def _rewrite(pdir: Path, fn):
    f = pdir / "board" / "shots.json"
    S = json.loads(f.read_text(encoding="utf-8"))
    fn(S["shots"])
    f.write_text(json.dumps(S), encoding="utf-8")


def test_one_layer_counter_and_chapter_scenes(pw, tmp_path):
    hero = {"kind": "chart", "key": "B", "params": {"beats": 2}}
    empty = {"kind": "streamlines", "key": "B", "params": {"attractors": [{"x": 5, "y": 9}]}}       # unreadable: it draws nothing
    good = {"kind": "streamlines", "key": "B", "params": {"attractors": [[.3, .4, 1.4]], "seeds": 6}}  # a [u, v, k] row is fine
    proj = _board(tmp_path / "layers", ["p-a", "p-b", "p-c", "p-a", "p-b", "p-c"], asked={0: "layers", 2: "relight", 3: "diagram", 4: "layers", 5: "relight"},
                  devices={0: [hero], 4: [empty], 5: [good]}, layer_js=CHAPTER, beats_per_shot=6)

    def chrome_off(shots):
        for i in (2, 4, 5):
            shots[i]["chrome"] = "off"
    _rewrite(proj["dir"], chrome_off)
    page = _open(pw, proj["dir"])
    try:
        info = page.page.evaluate("() => { const i = ENGINE.info(); return {keys: Object.keys(i), cs: i.chapterScenes, csh: i.chapterShots, warn: i.deviceWarnings}; }")
        assert "layers" not in info["keys"], "one layer counter: ENGINE.frameLayers(), not a second one in ENGINE.info()"
        assert [c["name"] for c in info["cs"]] == ["chapter-one"], info["cs"]
        assert info["csh"] == ["t02"], info["csh"]
        assert any("t05: streamlines has no attractor it can read — it draws nothing" in w for w in info["warn"]), info["warn"]
        assert any("t05: streamlines.params.attractors[0]" in w and "dropped" in w for w in info["warn"]), info["warn"]
        assert not any(w.startswith("t06: streamlines") for w in info["warn"]), "a [u, v, k] attractor row is a documented shape"
        shots = proj["shots"]
        mid = lambda s: (s["t0"] + s["t1"]) / 2  # noqa: E731

        page.frame_jpeg(shots[0]["t1"] - .3)                              # the chart (hero) is up, chrome on
        st = page.page.evaluate(FRAME)
        assert st["shot"] == "t01" and st["hero"] == ["chart"], st
        assert {"media", "graphic", "chrome"} <= set(st["L"]) and st["count"] >= 3, st
        _agree(st)
        page.frame_jpeg(mid(shots[1]))                                    # the chapter's frame: no default shot drew it
        st = page.page.evaluate(FRAME)
        assert st["Lshot"] is None, st
        page.frame_jpeg(mid(shots[2]))                                    # chrome off, no device: below the rule
        st = page.page.evaluate(FRAME)
        assert st["count"] < 3 and "graphic" not in st["L"] and "chrome" not in st["L"], st
        _agree(st)
        page.frame_jpeg(mid(shots[3]))                                    # the diagram treatment's measuring marks
        st = page.page.evaluate(FRAME)
        assert "graphic" in st["L"], st
        _agree(st)
        page.frame_jpeg(mid(shots[4]))                                    # streamlines that draw nothing: no layer
        st = page.page.evaluate(FRAME)
        assert st["hero"] == [] and "graphic" not in st["L"], st
        _agree(st)
        page.frame_jpeg(mid(shots[5]))                                    # the same device with a readable attractor
        st = page.page.evaluate(FRAME)
        assert st["hero"] == ["streamlines"] and "graphic" in st["L"], st
        _agree(st)
        assert not st["errors"] and not page.errors, (st["errors"], page.errors)
    finally:
        page.close()


def test_per_shot_looks_and_reproduction_kinds(pw, tmp_path):
    """A print film whose even shots (the first one too) are `screen: "native"`: clean is decided per shot."""
    asked = {2: {"family": "xerox", "kind": "banana"}, 5: {"family": "xerox", "kind": "banana"}, 8: {"family": "xerox", "kind": "thermal"},
             10: "tiles", 11: {"family": "reproduction", "kind": "mosaic"}}
    proj = _board(tmp_path / "mixed", ["p-a", "p-b", "p-c"] * 4, asked=asked, look="print")

    def native_even(shots):
        for i, sh in enumerate(shots):
            if i % 2 == 0:
                sh["screen"] = "native"
    _rewrite(proj["dir"], native_even)
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate(PLAN)
        L = {s["id"]: s for s in r["list"]}
        clean = {t["id"]: t["clean"] for t in r["info"]}
        assert [clean[f"t{i + 1:02d}"] for i in range(12)] == [i % 2 == 0 for i in range(12)], clean
        for s in r["list"]:
            if s["code"] == "RP" and s["auto"] and clean[s["id"]]:
                assert s["kind"] in ("mosaic", "tiles"), f"print texture picked for a clean shot: {s}"
        w = "\n".join(r["warn"])
        # a kind nobody knows: the clean reproduction on a clean shot, the photocopy on a print one — reported
        assert L["t03"]["kind"] == "mosaic" and "t03: reproduction kind 'banana' is not one of xerox · thermal · mosaic · tiles → 'mosaic'" in w, w
        assert L["t06"]["kind"] == "xerox" and "t06: reproduction kind 'banana' is not one of xerox · thermal · mosaic · tiles → 'xerox'" in w, w
        # print texture asked on a clean shot of a print film: kept and reported (it was silent when the film's look decided)
        assert L["t09"]["kind"] == "thermal" and "t09: treatment 'xerox' kind 'thermal' is a print-look texture" in w, w
        # a repeat is reported in the board's own words
        assert "t12: treatment 'reproduction' kind 'mosaic' (draws as xerox kind mosaic) repeats the previous 2.5D shot" in w, w
        assert L["t11"]["kind"] == "tiles" and L["t12"]["fam"] != "xerox", (L["t11"], L["t12"])
    finally:
        page.close()


def _add_even_plate(pdir: Path):
    """p-even: p-a's picture with a perfectly even depth map (no figure stands nearer than the rest)."""
    from PIL import Image
    pl = pdir / "engine" / "assets" / "plates"
    Image.open(pl / "p-a.jpg").save(pl / "p-even.jpg", quality=90)
    Image.new("L", Image.open(pl / "p-a.depth.png").size, 128).save(pl / "p-even.depth.png")
    f = pdir / "engine" / "plates.js"
    js = f.read_text(encoding="utf-8")
    meta = json.loads(js[js.index("=") + 1:].strip().rstrip(";"))
    meta["p-even"] = dict(meta["p-a"])
    f.write_text("window.PLATES = " + json.dumps(meta) + ";\n", encoding="utf-8")


def test_multiplane_without_a_subject_plane_is_reported(pw, tmp_path):
    proj = _board(tmp_path / "even", ["p-even", "p-a", "p-b"], asked={0: "multiplane", 1: "layers", 2: "relight"}, beats_per_shot=4)
    _add_even_plate(proj["dir"])
    page = _open(pw, proj["dir"])
    try:
        info = page.page.evaluate("() => { const i = ENGINE.info(); return {warn: i.deviceWarnings, tr: i.treatments}; }")
        w = "\n".join(info["warn"])
        assert "t01: treatment 'multiplane' found no subject plane in plate 'p-even'" in w and "→ drew 'layers' instead" in w, w
        assert "t01 and t02 both draw 'layers'" in w, w
        t01 = next(t for t in info["tr"] if t["id"] == "t01")
        assert t01["family"] == "multiplane" and t01["drawn"] == "layers", t01
        s = proj["shots"][0]
        page.frame_jpeg((s["t0"] + s["t1"]) / 2)
        st = page.page.evaluate(FRAME)
        assert st["shot"] == "t01" and st["drawnAs"] == "layers" and not st["errors"], st
        assert not page.errors, page.errors
    finally:
        page.close()
