"""devices track: operator safety of the explaining devices (engine/src/devices/explain.js) and their print look.

A weaker model writes shots.json by hand, so a malformed param is never replaced silently: every repair is a line in
`slop render info`'s deviceWarnings that names the param, what was drawn instead and the exact shape to write — a quad
given as a string or with 3 points, attractors written {x, y}, a powers point "somewhere", empty levels (which used to
throw), molecule nodes without edges, an unknown content or preset. The documented shapes ([u, v, k] attractor rows,
"center" / "lead" points, a quad quoted as a JSON string) are read without a warning or with a "read as" one.

In a print look, powers of ten's map and a quad printed on the plate go through the print pass like footage (the screen
is in them; the overlay does not carry them), and while the map is up the CV marks and the stills strip wait.
A subtitle over mixed ground keeps the line's ink on a word until that ink stops reading over it (no flip on a drift).
"""
from __future__ import annotations

import importlib.util
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
def pw():
    _need_engine()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


QUAD_OK = [[.6, .2], [.9, .2], [.9, .4], [.6, .4]]
# (shot, device entry, what deviceWarnings must say about it — every substring, prefixed with the shot id)
BAD = [
    ("s01", {"kind": "quad", "key": "B", "params": {"quad": "0.6, 0.2, 0.9, 0.2"}},
     ["quad.params.quad needs 4 [u, v] corners", "like [[.6, .2], [.9, .2], [.9, .4], [.6, .4]]", "drew a panel in a free slot instead"]),
    ("s02", {"kind": "quad", "key": "B", "params": {"quad": [[.1, .1], [.2, .1], [.2, .2]], "content": "banner"}},
     ["quad.params.quad needs 4 [u, v] corners", "quad.params.content 'banner' is not one of sign · screen · paper — drew a sign"]),
    ("s04", {"kind": "streamlines", "key": "B", "params": {"attractors": [{"x": .3, "y": .4}, {"x": 640, "y": 300}]}},
     ["streamlines.params.attractors[0]: read {\"x\": 0.3, \"y\": 0.4} as image space {\"uv\": [0.3, 0.4]}",
      "streamlines.params.attractors[1] ", "has no image-space point — dropped; write {\"uv\": [u, v], \"k\": 1.4}"]),
    ("s05", {"kind": "streamlines", "key": "B", "params": {"attractors": [{"x": 900, "y": 20}], "points": [[.1, .2], "x"]}},
     ["streamlines has no attractor it can read — it draws nothing; write \"attractors\": [{\"uv\": [.3, .4]",
      "streamlines.params.points: 1 of 2 not [u, v] pairs — dropped"]),
    ("s06", {"kind": "powers", "key": "B", "params": {"levels": "", "point": "somewhere"}},
     ["powers.params.levels is empty — drew the default levels", "write one label per level like [\"10 M\", \"100 M\", \"1 KM\"]",
      "powers.params.point should be [u, v] in image space like [.5, .4] (or \"center\", or \"lead\") — got somewhere; zoomed out from the lead instead"]),
    ("s07", {"kind": "molecule", "key": "B", "params": {"nodes": [{"x": 0, "y": 0, "label": "A"}, {"x": 1, "y": 0, "label": "B"}]}},
     ["molecule.params.nodes has no \"edges\" — drew the stock molecule instead; add \"edges\": [[0, 1], [1, 2]]"]),
    ("s09", {"kind": "network", "key": "B", "params": {"nodes": [[0, 0, "A"], [1, 0, "B"]], "edges": [[0, 1], [0, 5], ["A", "Z"]]}},
     ["molecule.params.edges: 2 of 3 edge(s) name a node that does not exist or join a node to itself — dropped"]),
    ("s10", {"kind": "molecule", "key": "B", "params": {"preset": "star"}},
     ["molecule.params.preset star is not molecule · network — drew a molecule"]),
]
# shapes that are fine as written (no warning at all)
GOOD = [
    {"kind": "streamlines", "key": "B", "params": {"attractors": [[.3, .4, 1.4], [.7, .35, 1.6, "B"]]}},
    {"kind": "powers", "key": "B", "params": {"point": "centre"}},
    {"kind": "powers", "key": "B", "params": {"point": "lead", "ground": "Paper"}},
    {"kind": "quad", "key": "B", "params": {"quad": QUAD_OK, "content": "Screen"}},
]


def test_malformed_params_are_reported_with_the_shape_to_write(pw, tmp_path):
    def tweak(shots):
        by = {s["id"]: s for s in shots}
        for sid, dev, _ in BAD:
            by[sid]["devices"] = [dev]
    proj = _synth().build(tmp_path / "bad", tweak=tweak)
    page = _open(pw, proj["dir"])
    try:
        warn = page.page.evaluate("() => ENGINE.info().deviceWarnings")
        text = "\n".join(warn)
        for sid, dev, wants in BAD:
            mine = "\n".join(w for w in warn if w.startswith(f"{sid}: "))
            for want in wants:
                assert want in mine, f"{sid} {dev['kind']}: no warning saying {want!r}\n{mine}"
        assert "throws" not in text, [w for w in warn if "throws" in w]          # empty levels used to throw in the boot dry run
        # the instances as the renderer holds them: repaired to a shape that draws (or to nothing, said so)
        r = page.page.evaluate("""([bad, good, shots]) => { const sh = id => shots.find(s => s.id === id);
          const I = (spec, s) => DEV.instance(spec, s);
          const out = {bad: bad.map(([sid, spec]) => { const i = I(spec, sh(sid)); return {sid, kind: i.kind, p: {quad: i.p.quad ?? null, content: i.p.content ?? null,
              attractors: i.p.attractors ?? null, levels: i.p.levels ?? null, point: i.p.point ?? null, preset: i.p.preset ?? null}}; }),
            good: good.map(spec => { const i = I(spec, sh('s02')); return {kind: i.kind, warn: i.warn, p: {quad: i.p.quad ?? null, content: i.p.content ?? null,
              attractors: i.p.attractors ?? null, point: i.p.point ?? null, ground: i.p.ground ?? null}, pinned: !!(i.spec.pinned && i.spec.pinned(i.p))}; }),
            json: (() => { const i = I({kind: 'quad', key: 'B', params: {quad: JSON.stringify([[.6, .2], [.9, .2], [.9, .4], [.6, .4]])}}, sh('s02')); return {quad: i.p.quad, warn: i.warn}; })() };
          return out; }""", [[[b[0], b[1]] for b in BAD], GOOD, proj["shots"]])
        bad = {x["sid"]: x for x in r["bad"]}
        assert bad["s01"]["p"]["quad"] is None and bad["s02"]["p"]["content"] == "sign"
        assert bad["s04"]["p"]["attractors"] == [{"x": .3, "y": .4, "uv": [.3, .4]}], bad["s04"]
        assert bad["s05"]["p"]["attractors"] == []
        assert bad["s06"]["p"]["levels"] == ["10 M", "100 M", "1 KM", "10 KM", "100 KM"] and bad["s06"]["p"]["point"] is None
        assert bad["s10"]["p"]["preset"] == "molecule"
        for g in r["good"]:
            assert not g["warn"], g
        assert [a["uv"] for a in r["good"][0]["p"]["attractors"]] == [[.3, .4], [.7, .35]] and r["good"][0]["p"]["attractors"][0]["k"] == 1.4
        assert r["good"][1]["p"]["point"] == [.5, .5] and r["good"][2]["p"]["point"] is None and r["good"][2]["p"]["ground"] == "paper"
        assert r["good"][3]["pinned"] and r["good"][3]["p"]["content"] == "screen"
        assert r["json"]["quad"] == QUAD_OK and any("read" in w for w in r["json"]["warn"]), r["json"]
        # every shot still renders, with no device error; streamlines with nothing to draw is no hero on its frame
        shots = {s["id"]: s for s in proj["shots"]}
        for sid, dev, _ in BAD:
            s = shots[sid]
            page.frame_jpeg((s["t0"] + s["t1"]) / 2)
            st = page.page.evaluate("() => ({hero: (window.DEV_FRAME || {}).hero, errors: (window.DEV_ERRORS || []).slice()})")
            assert not st["errors"], (sid, st["errors"])
            if sid == "s05":
                assert st["hero"] == [], st
        assert not page.errors, page.errors
    finally:
        page.close()


# ------------------------------------------------------------------------------------------------- the print look --
POW = {"kind": "powers", "key": "B", "params": {"levels": ["10 M", "100 M", "1 KM"]}}
QUAD = {"kind": "quad", "key": "B", "params": {"content": "sign", "quad": [[.55, .12], [.85, .14], [.85, .36], [.55, .36]], "lines": ["NORTH"]}}

# after the frame at t: the share of the overlay that is inked, and the median high-frequency energy (mean |∇ luma|, 8-bit)
# of the final frame in 40-px patches of `region` where the overlay is empty (only the base, after the print pass, shows)
MEASURE = """async ([t, region]) => { await window.renderAt(t);
  const read = cv => { const c = document.createElement('canvas'); c.width = cv.width; c.height = cv.height; const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(cv, 0, 0); return g.getImageData(0, 0, c.width, c.height).data; };
  const d = read(ENGINE.layers.out), a = read(ENGINE.layers.over), W = ENGINE.W, H = ENGINE.H, P = 40, res = [];
  let cov = 0; for (let i = 3; i < a.length; i += 16) if (a[i] > 8) cov++; cov /= a.length / 16;
  const [rx, ry, rw, rh] = region || [0, 0, W, H], L = i => .3 * d[i] + .59 * d[i + 1] + .11 * d[i + 2];
  for (let y = ry; y + P <= ry + rh; y += P) for (let x = rx; x + P <= rx + rw; x += P) {
    let empty = true; for (let yy = y; yy < y + P && empty; yy += 2) for (let xx = x; xx < x + P; xx += 2) if (a[(yy * W + xx) * 4 + 3] > 0) { empty = false; break; }
    if (!empty) continue;
    let e = 0, n = 0; for (let yy = y; yy < y + P - 1; yy++) for (let xx = x; xx < x + P - 1; xx++) { const i = (yy * W + xx) * 4; e += Math.abs(L(i) - L(i + 4)) + Math.abs(L(i) - L(i + W * 4)); n++; }
    res.push(e / n); }
  res.sort((p, q) => p - q); const f = window.DEV_FRAME || {};
  return {cov, n: res.length, med: res.length ? res[res.length >> 1] : null, covered: f.covered, hero: f.hero, cv: f.cv, strip: f.strip, errors: (window.DEV_ERRORS || []).slice()}; }"""


@pytest.fixture(scope="module")
def looks(pw, tmp_path_factory):
    """The same board in the native and the print look: powers on s06 (chorus: a line screen) and s12 (stills), a sign quad
    measured on s02's plate (verse: grain)."""
    def tweak(shots):
        by = {s["id"]: s for s in shots}
        by["s06"]["devices"] = [POW]
        by["s12"]["devices"] = [POW]
        by["s02"]["devices"] = [QUAD]
    out = {}
    for look in ("native", "print"):
        proj = _synth().build(tmp_path_factory.mktemp(f"look-{look}"), look=look, tweak=tweak)
        page = _open(pw, proj["dir"])
        sh = {s["id"]: s for s in proj["shots"]}
        mid = lambda s: (s["t0"] + s["t1"]) / 2  # noqa: E731
        try:
            out[look] = {"powers": page.page.evaluate(MEASURE, [mid(sh["s06"]), None]),
                         "quad": page.page.evaluate(MEASURE, [mid(sh["s02"]), [1180, 120, 400, 220]]),
                         "stills": page.page.evaluate(MEASURE, [mid(sh["s12"]), None]),
                         "errors": list(page.errors)}
        finally:
            page.close()
    return out


def test_powers_map_goes_through_the_print_pass(looks):
    nat, prt = looks["native"]["powers"], looks["print"]["powers"]
    for r in (nat, prt):
        assert r["covered"] == "powers" and r["hero"] == ["powers"], r
        assert r["cv"] == [], f"the lead's CV mark is held while the map hides the footage it marks: {r}"
        assert r["cov"] < .1, f"the overlay carries the map ({r['cov']:.0%} inked): it would skip the print pass"
        assert not r["errors"], r["errors"]
    assert nat["n"] > 50 and prt["n"] > 50
    # the map's flat areas: smooth in the native look, the print screen and grain in the print look
    assert prt["med"] > 4 * nat["med"] and prt["med"] > 8, (nat["med"], prt["med"])
    assert not looks["native"]["errors"] and not looks["print"]["errors"]


def test_quad_on_the_plate_goes_through_the_print_pass(looks):
    nat, prt = looks["native"]["quad"], looks["print"]["quad"]
    assert nat["hero"] == ["quad"] and prt["hero"] == ["quad"], (nat, prt)
    assert nat["n"] >= 10 and prt["n"] >= 10, "the quad's face is on the base, not the overlay"
    assert prt["med"] > 2.5 * nat["med"], (nat["med"], prt["med"])


def test_powers_holds_the_stills_strip(looks):
    for look in ("native", "print"):
        r = looks[look]["stills"]
        assert r["covered"] == "powers" and r["strip"] is False and not r["errors"], (look, r)


# ------------------------------------------------------------------------------------------ the subtitle's ink ----
def test_subtitle_word_ink_holds_until_it_stops_reading(pw, tmp_path):
    proj = _synth().build(tmp_path / "ink")
    page = _open(pw, proj["dir"])
    try:
        r = page.page.evaluate("""() => {
          const c = DEV.mk(W, H), b = c.getContext('2d', {willReadFrequently: true}), box = [100, 800, 1200, 120];
          const paint = (left, word) => { b.fillStyle = left; b.fillRect(0, 0, W, H); b.fillStyle = '#000'; b.fillRect(900, 0, W - 900, H); b.fillStyle = word; b.fillRect(500, 800, 200, 120); };
          const run = (left, word) => { paint(left, word); const f = DEV.type.wordInks(b, box); return f ? {mid: f([520, 820, 160, 80]), dark: f([950, 820, 200, 80]), light: f([150, 820, 200, 80])} : null; };
          return {drift: [run('#bdbdbd', '#707070'), run('#bdbdbd', '#7e7e7e')], darkLine: [run('#303030', '#707070'), run('#303030', '#7e7e7e')],
                  even: (() => { b.fillStyle = '#808080'; b.fillRect(0, 0, W, H); return DEV.type.wordInks(b, box); })(), light: DEV.C.light, dark: DEV.C.dark};
        }""")
        L, D = r["light"], r["dark"]
        # a light-ground line (dark ink): the word over black takes light ink; a mid-grey word keeps the line's ink on both
        # sides of the old midpoint (#707070 / #7e7e7e straddle it: the old per-word pick flipped there)
        for k in r["drift"]:
            assert k["light"] == D and k["dark"] == L and k["mid"] == D, r["drift"]
        assert r["darkLine"][0]["mid"] == r["darkLine"][1]["mid"], r["darkLine"]
        assert r["even"] is None, "an even ground needs no per-word ink"
        assert not page.errors, page.errors
    finally:
        page.close()
