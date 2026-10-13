"""The engine page in headless Chromium (SwiftShader): boot, data normalisation, the fixed bugs, registries, purity.

One booted page per module (the stub renderer, so engine-core is tested on its own); each test is a JS probe.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
sys.path.insert(0, str(FIX))
pytest.importorskip("playwright.sync_api")


def _open(pw, pdir: Path, w=None, h=None, shots=False):
    from slop.config import SlopError
    from slop.render import project as P
    from slop.render.browser import EnginePage
    try:
        return EnginePage(pw, P.page_spec(pdir, w, h, shots=shots))
    except SlopError as e:
        pytest.skip(f"no browser: {e}")


@pytest.fixture(scope="module")
def pw():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    yield p
    p.stop()


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("engine") / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    return d


@pytest.fixture(scope="module")
def page(pw, demo_dir):
    pg = _open(pw, demo_dir)
    yield pg
    pg.close()


def js(pg, expr, arg=None):
    return pg.page.evaluate(expr, arg)


def test_boot_info(page):
    info = page.info()
    assert not info["page_errors"], info["page_errors"]
    assert (info["W"], info["H"], info["FPS"]) == (1920, 1080, 24)
    assert info["duration"] == 8 and info["beats"] == 17 and info["sections"] == 3
    assert info["lyrics"] == 2 and info["tokens"] == 6 and info["shots"] == 3
    assert info["shotsRenderer"] == "engine-stub" and info["scenes"] >= 3
    assert info["fontsFailed"] == [] and info["ready"]


def test_fonts_loaded(page):
    fams = ["Space Grotesk", "IBM Plex Mono", "Barlow Condensed", "DINish Condensed", "Share Tech Mono", "Instrument Serif"]
    res = js(page, "(fams) => fams.map(f => document.fonts.check(`700 40px \"${f}\"`) && document.fonts.check(`400 12px \"${f}\"`))", fams)
    assert all(res), dict(zip(fams, res))
    assert js(page, "() => F.grotesk") == '"Space Grotesk"'


def test_data_normalised(page):
    d = js(page, """() => ({bpm60: SONG.bpm, accent: INK.accent, shots: SHOTLIST.shots.length, sections: SONG.sections.map(s => s.name),
      impact: HITS.impact, ride: HITS.ride, fill: HITS.fill, vox: HITS.vox_on, env: Object.keys(HITS.env).sort(),
      seq: Object.keys(SEQ).length, plates: Object.keys(PLATES).sort()})""")
    assert d["accent"] == "#D97757" and d["shots"] == 3 and d["sections"] == ["intro", "verse1", "chorus"]
    assert d["impact"] == [{"t": 6.0, "s": 0.9}] and d["ride"] == [[5.0, 6.0]] and d["fill"] == [[5.5, 6.0]]
    assert d["vox"] == [1.0, 4.0] and d["env"] == ["bass", "drums", "mix", "vocals"]
    assert d["plates"] == ["grad-a", "grad-b", "grad-c"]


def test_clock_is_the_beat_map(page):
    r = js(page, "() => [bpOf(1.25), beatAt(4), barAt(2), KIN.beatLen(3.1), ENGINE.time.beatsSince(2.0, 1.0)]")
    assert r == pytest.approx([2.5, 2.0, 4.0, 0.5, 2.0])


def test_time_resolve(page):
    r = js(page, """() => { const R = ENGINE.time.resolve, sh = {t0: 3, t1: 6};
      return [R({word: [1, 0]}), R({word_end: [0, -1]}), R({beat: 4}), R({bar: 2}), R('shot.t1', sh), R({beats_after: [{beat: 2}, 1.5]}),
              R({eighth_after: ['shot.t0', 1]}, sh), R({hit: 'kick', near: 1.03}), R({hit: 'impact', near: 5.95}), R({frame_nearest: 2}), R({add: [1, .5]}), R({nope: 1})]; }""")
    assert r[:11] == pytest.approx([4.0, 2.6, 2.0, 4.0, 6.0, 1.75, 3.25, 1.0, 6.0, 2 - .5 / 24, 1.5])
    assert r[11] is None


def test_match_cut_lands_on_target_and_never_shows_the_edge(page):
    r = js(page, """() => {
      const rec = [], mk = () => ({ setTransform(...a) { rec.push(a); }, drawImage() {}, save() {}, restore() {} });
      const c = { a: {}, b: {}, ao: {}, bo: {}, base: mk(), over: mk(), la: { focus: [800, 400, 200, 200] }, lb: { focus: [1000, 500, 100, 100] } };
      const f = FX.T.match(), out = [];
      for (const p of [.5001, .6, .75, .9]) { rec.length = 0; f(p, c); const [s, , , , tx, ty] = rec[0]; out.push([p, s, tx, ty]); }
      // B's subject centre lands on A's at the cut; near the frame edge the translation is clamped
      rec.length = 0; f(.5001, Object.assign({}, c, { la: { focus: [0, 0, 300, 300] } })); out.push(rec[0]);
      return out; }""")
    for p, s, tx, ty in r[:4]:
        assert 1 <= s <= 1.6 + 1e-9
        assert 1920 - 1920 * s - 1e-6 <= tx <= 1e-6 and 1080 - 1080 * s - 1e-6 <= ty <= 1e-6
    p, s, tx, ty = r[0]
    assert s * 1050 + tx == pytest.approx(900, abs=1) and s * 550 + ty == pytest.approx(500, abs=1)
    s, _, _, _, tx, ty = r[4]
    assert tx <= 1e-6 and ty <= 1e-6 and tx >= 1920 - 1920 * s - 1e-6 and ty >= 1080 - 1080 * s - 1e-6


def test_match_cut_lands_when_a_subject_is_smaller(page):
    """A's subject smaller than B's: the box ratio alone would shrink B (< 1×, edge shows) — the old fix degenerated to a
    hard cut here. Now the scale rises just enough to make room, and B's subject still lands on A's."""
    r = js(page, """() => {
      const rec = [], mk = () => ({ setTransform(...a) { rec.push(a); }, drawImage() {}, save() {}, restore() {} });
      const c = { a: {}, b: {}, ao: {}, bo: {}, base: mk(), over: mk(), la: { focus: [800, 400, 100, 100] }, lb: { focus: [1000, 500, 200, 200] } };
      const f = FX.T.match(), out = [];
      for (const p of [.5001, .6, .8, .99, 1]) { rec.length = 0; f(p, c); const [s, , , , tx, ty] = rec[0]; out.push([p, s, tx, ty]); }
      return out; }""")
    k = lambda p: 1 - (1 - (1 - (p - .5) * 2) ** 3)       # noqa: E731 — 1 − easeOut((p − .5)·2)
    for p, s, tx, ty in r:
        assert 1 - 1e-9 <= s <= 1.6 + 1e-9
        assert 1920 - 1920 * s - 1e-6 <= tx <= 1e-6 and 1080 - 1080 * s - 1e-6 <= ty <= 1e-6       # never an edge
        want_x, want_y = 1100 + (850 - 1100) * k(p), 600 + (450 - 600) * k(p)                     # lerp(B, A, k)
        assert s * 1100 + tx == pytest.approx(want_x, abs=1) and s * 600 + ty == pytest.approx(want_y, abs=1), (p, s, tx, ty)
    assert r[0][1] > 1.25                       # the move needed room: zoomed in, not a hard cut
    assert r[-1][1:] == pytest.approx([1, 0, 0])  # at rest: identity


def test_ruler_bar_numbers_never_negative(page):
    r = js(page, """() => {
      const texts = [], ctx = new Proxy(document.createElement('canvas').getContext('2d'), { get(t, k) {
        if (k === 'fillText') return (s, ...a) => { texts.push(String(s)); };
        const v = t[k]; return typeof v === 'function' ? v.bind(t) : v; }, set(t, k, v) { t[k] = v; return true; } });
      for (const t of [0, .2, 1.1, 3.3, 7.9]) ANN.ruler(ctx, 30, t, {});
      return { texts: [...new Set(texts)], bars: [-4, 0, 1, 4, 8, 12, 16, 99].map(ANN.barOfBeat) }; }""")
    assert r["bars"] == [None, 1, None, 2, 3, 4, 5, None]
    assert r["texts"] and all(t.isdigit() and len(t) == 3 for t in r["texts"]), r["texts"]


def test_flapboard_does_not_leak_text_state(page):
    r = js(page, """() => { const g = document.createElement('canvas').getContext('2d');
      g.textAlign = 'right'; g.textBaseline = 'top'; flapBoard(g, 0, 0, 4, 'GO', 'NO', 0, .1, {});
      return [g.textAlign, g.textBaseline]; }""")
    assert r == ["right", "top"]


def test_mass_flickers_on_the_beat_map(page):
    r = js(page, """() => {
      const run = () => { const calls = [], g = new Proxy(document.createElement('canvas').getContext('2d'), { get(t, k) {
          if (k === 'fillText') return (s, x, y) => calls.push([s, y, t.globalAlpha.toFixed(3)]);
          const v = t[k]; return typeof v === 'function' ? v.bind(t) : v; }, set(t, k, v) { t[k] = v; return true; } });
        mass(g, ['a', 'b', 'c'], 0, 0, 3.3, 1.0, { rows: 12 }); return JSON.stringify(calls); };
      const keep = [SONG.beats, SONG.bpm];
      SONG.beats = [0, .4, .9, 1.5, 2.2, 3.0, 3.9, 4.9]; SONG.bpm = 60; const a = run(); SONG.bpm = 400; const b = run();
      SONG.beats = null; SONG.bpm = 60; const c = run(); SONG.bpm = 400; const d = run();
      [SONG.beats, SONG.bpm] = keep; return [a === b, c === d, a.length > 2]; }""")
    assert r[0], "with a beat map, mass() must not depend on a fixed BPM"
    assert not r[1] and r[2]


def test_depth_licence_rule(page):
    r = js(page, """() => { const ok = m => ENGINE.depthOK(m);
      const a = [ok({depth_model: 'depth-anything/Depth-Anything-V2-Small-hf'}), ok({depth_model: 'depth-anything-v2-small'}),
        ok({depth_model: 'Depth Anything V2 Small'}),
        ok({depth_model: 'depth-anything/Depth-Anything-V2-Large-hf'}), ok({depth_model: 'Depth-Anything-V2-Base'}),
        ok({depth_model: 'midas-small'}), ok({depth_model: 'zoedepth-small'}), ok({depth_model: 'depth-anything-v1-small'}),
        ok({}), ok(null)];
      // unlabelled depth is unknown — unless the project says all its depth is V2-Small
      const P = window.PROJECT, keep = P.depth_model; P.depth_model = 'Depth-Anything-V2-Small';
      a.push(ok({}), ok({depth_model: 'depth-anything/Depth-Anything-V2-Large-hf'})); P.depth_model = keep;
      return a; }""")
    assert r == [True, True, True, False, False, False, False, False, False, False, True, False]
    info = page.info()
    assert info["depthUnlabelled"] == [] and info["missingMedia"] == []


def test_large_depth_is_refused(page):
    r = js(page, """async () => {
      const keep = PLATES['grad-b'].depth_model; PLATES['grad-b'].depth_model = 'depth-anything/Depth-Anything-V2-Large-hf';
      const g = document.createElement('canvas').getContext('2d', { willReadFrequently: true }); g.canvas.width = W; g.canvas.height = H;
      const big = await MEDIA.plate('grad-b'); PLATES['grad-b'].depth_model = keep; const ok = await MEDIA.plate('grad-b');
      return [big.dep === null, !!ok.dep]; }""")
    assert r == [True, True]


def test_occ_is_a_noop_without_data(page):
    r = js(page, """async () => {
      const mk = () => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c.getContext('2d', { willReadFrequently: true }); };
      const b = mk(), o = mk(), o2 = mk();
      const m = await MEDIA.drawPlate(b, 'grad-a', { zoom: 1.06 }, 1.0);           // grad-a: no matte, no depth
      const draw = g => { g.fillStyle = '#fff'; g.fillRect(100, 100, 50, 50); };
      const mk1 = await OCC.behind(o, m, draw), mk2 = await OCC.over(o2, m, draw);
      const px = (g) => g.getImageData(120, 120, 1, 1).data[3];
      return [mk1 === null, px(o), mk2 === null, px(o2), await m.matte(), await m.depth()]; }""")
    assert r == [True, 255, True, 0, None, None]


def test_transitions_registry(page):
    r = js(page, """() => { const T = ENGINE.transitions, d = x => { const t = T.make(x, 3); return t && [t.type, +t.dur.toFixed(2), !!t.draw]; };
      return [d('Match cut: her pupil = the gap in the clouds.'), d('dissolve'), d({preset: 'whip-wrap', dur: .4}), d('cut'), d(null),
              d('flash-cut'), d({type: 'flap'}), d('push through the phone'), d('iris'), d('totally-unknown-but-object' && {preset: 'zzz'})]; }""")
    assert r[0] == ["custom", 0.5, True] and r[1] == ["dither", 0.45, False] and r[2] == ["custom", 0.4, True]
    assert r[3] is None and r[4] is None and r[5] == ["custom", 0.3, True] and r[6][0] == "flap"
    assert r[7][0] == "custom" and r[8][0] == "custom" and r[9] is None


def test_type_registry_never_loses_a_word(page):
    r = js(page, """() => { const g = document.createElement('canvas').getContext('2d'); const out = {};
      for (const mode of ['subtitle', 'cover', 'mast', 'stack', 'mass', 'no-such-mode']) {
        DRAWN.clear(); ENGINE.type.draw(mode, g, KIN.byLine(1), 5.1, {}, {}); out[mode] = [...DRAWN].sort(); }
      return out; }""")
    for mode, keys in r.items():
        assert "5.00" in keys, (mode, keys)


def test_device_registry(page):
    r = js(page, """async () => { const seen = [];
      ENGINE.registerDevice('probe.dev', (o, env) => { seen.push([env.t0, env.t1, env.anchor, env.params.k]); return 'ok'; });
      const g = document.createElement('canvas').getContext('2d');
      const sh = SHOTLIST.shots[0], m = await MEDIA.drawShot(document.createElement('canvas').getContext('2d'), sh.id, 1, { zoom: 1.06 });
      const a = await ENGINE.drawDevice({ kind: 'probe.dev', anchor: { xy: [10, 20] }, params: { k: 7 }, at: { t0: { word: [0, 1] } } }, { o: g, t: 1.6, shot: sh, m });
      const b = await ENGINE.drawDevice({ kind: 'nope' }, { o: g, t: 1, shot: sh });
      ENGINE.registerDevice('probe.boom', () => { throw new Error('kaboom'); });
      const c = await ENGINE.drawDevice({ kind: 'probe.boom' }, { o: g, t: 1, shot: sh });
      const lead = ENGINE.anchor('lead', m);
      return { a, b, c, seen, lead }; }""")
    assert r["a"] == "ok" and r["b"] is None and r["c"] is None
    assert r["seen"] == [[1.5, 3.0, [10, 20], 7]]
    assert r["lead"] and len(r["lead"]) == 4


def test_print_look_and_accent_keep(page):
    r = js(page, """() => {
      const P = window.PROJECT, keep = P.look.mode; P.look.mode = 'print';
      const looks = [ENGINE.look('chorus'), ENGINE.lookFor({section: 'chorus', t0: 6.5}), ENGINE.look({section: 'verse 2'}), ENGINE.look('chorus', {mode: 'native'})];
      // the print pass on a half accent / half grey base: accentKeep 1 keeps the accent half continuous (no screen)
      const b = document.createElement('canvas'); b.width = W; b.height = H; const g = b.getContext('2d', { willReadFrequently: true });
      g.fillStyle = INK.accent; g.fillRect(0, 0, W / 2, H); g.fillStyle = '#7a7a7a'; g.fillRect(W / 2, 0, W / 2, H);
      const ov = document.createElement('canvas'); ov.width = W; ov.height = H;
      const sd = (keepA) => { POST.run(b, ov, Object.assign(ENGINE.look('verse1'), { screen: .9, grain: 0, accentKeep: keepA }), 1);
        const r = document.createElement('canvas'); r.width = 200; r.height = 200; const rg = r.getContext('2d', { willReadFrequently: true });
        rg.drawImage(ENGINE.layers.out, 400, 400, 200, 200, 0, 0, 200, 200); const d = rg.getImageData(0, 0, 200, 200).data;
        let s = 0, s2 = 0, n = 0; for (let i = 0; i < d.length; i += 4) { const y = .3 * d[i] + .59 * d[i + 1] + .11 * d[i + 2]; s += y; s2 += y * y; n++; }
        return Math.sqrt(s2 / n - (s / n) ** 2); };
      const res = [looks.map(l => [l.mode, l.section || null]), sd(0), sd(1)];
      P.look.mode = keep; return res; }""")
    modes, sd0, sd1 = r
    assert modes[0] == ["line", "chorus"] and modes[1] == ["line", "chorus"] and modes[2] == ["grain", "verse2"]
    assert modes[3][0] == "native"
    assert sd0 > 8 and sd1 < sd0 / 3, (sd0, sd1)


def test_native_project_looks(page):
    r = js(page, "() => [ENGINE.look('chorus'), ENGINE.look('drop', {lift: .9, accent: '#00ff00'})]")
    assert r[0] == {"mode": "native", "accent": "#D97757"} and r[1] == {"mode": "native", "accent": "#00ff00"}


def test_lyric_tokens_drawn_at_their_time(page):
    toks = page.lyric_tokens()
    assert [t["key"] for t in toks] == ["1.00", "1.50", "2.00", "4.00", "4.50", "5.00"]
    for tk in toks:
        assert tk["key"] in page.drawn(tk["t"]), tk
    assert page.drawn(0.5) == []


def test_frames_are_pure_functions_of_t(page):
    import hashlib
    h = lambda t: hashlib.md5(page.frame_jpeg(t)).hexdigest()   # noqa: E731
    first = {t: h(t) for t in (5.2, 1.3)}
    for t in (7.1, 2.97, 3.0, 6.02, 4.4):                     # transitions, 2.5D, cuts in between
        h(t)
    assert {t: h(t) for t in (5.2, 1.3)} == first


def test_portrait_layout(pw, demo_dir):
    pg = _open(pw, demo_dir, 1080, 1920)
    try:
        r = js(pg, "() => [W, H, PORTRAIT, M, ENGINE.M === M, ENGINE.info().scenes]")
        assert r[:3] == [1080, 1920, True] and r[3]["b"] > 300 and r[4] and r[5] >= 3
        assert not pg.errors
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(pg.frame_jpeg(4.7)))
        assert im.size == (1080, 1920)
        # the subject (a dark disc at u = .30 in the plate) is pulled to the frame's centre in portrait
        g = im.convert("L").resize((108, 192))
        cols = [sum(g.getpixel((x, y)) for y in range(60, 130)) for x in range(108)]
        dark = min(range(108), key=lambda x: cols[x])
        assert 25 <= dark <= 83, dark
    finally:
        pg.close()


def test_every_transition_renders_through_renderAt(page):
    names = ["dither", "flap", "smear", "whip", "flash", "iris", "zoom", "match", "push", "luma", "bands", "through", "wrap", "flashcut"]
    r = js(page, """async (names) => {
      const sc = ENGINE.findScene('s002'), keep = sc.trans, out = {};
      for (const n of names) {
        const tr = ENGINE.transitions.set(sc, n === 'iris' ? { preset: 'iris', shape: 'spark' } : n);
        const ts = [sc.t0 - tr.dur / 3, sc.t0 - 1e-3, sc.t0, sc.t0 + 1 / 24, sc.t0 + tr.dur / 3];
        const urls = []; for (const t of ts) urls.push((await window.frame(t, .5)).length);
        out[n] = [tr.type, urls.every(u => u > 1000)];
      }
      sc.trans = keep; return out; }""", names)
    assert not page.errors, page.errors
    for n in names:
        assert r[n][1], (n, r[n])
    assert r["dither"][0] == "dither" and r["match"][0] == "custom"


def test_print_look_with_full_chrome_renders(page):
    r = js(page, """async () => {
      const P = window.PROJECT, keep = [P.look.mode, P.chrome]; P.look.mode = 'print'; P.chrome = { ticker: ['DEMO TICKER'] };
      const sizes = []; for (const t of [0.4, 2.2, 4.1, 6.5, 7.9]) sizes.push((await window.frame(t, .6)).length);
      // the chrome stack draws its pieces on the overlay without throwing
      const g = document.createElement('canvas'); g.width = W; g.height = H; const o = g.getContext('2d', { willReadFrequently: true });
      ENGINE.chrome(o, 3.3, { style: 'full' }); ENGINE.chrome(o, 3.3, { style: 'minimal' }); ENGINE.chrome(o, 3.3, { style: 'none' });
      countdown(o, 100, 100, '12', '13', 3.0, 3.2, {}); garmentTag(o, 400, 100, { title: 'TAG', rows: [['a', 1], ['b', 2]], reveal: .5 });
      departures(o, [{ label: 'one', value: 'ok', tFlip: 3.0, accent: true }], 3.3, {});
      [P.look.mode, P.chrome] = keep;
      return sizes; }""")
    assert not page.errors, page.errors
    assert all(s > 1000 for s in r)


def test_camera_moves_play_the_track(page):
    r = js(page, """async () => {
      const f = t => CAM.fx(t, { punch: { amp: .02 }, shake: { amp: 6 }, ride: { amp: .06 }, impact: { amp: .06 }, whip: { at: 6.0 } });
      const a = f(1.0 + .02), b = f(1.0 + .4), c = f(5.9), d = f(6.0 + .01);
      const g = document.createElement('canvas'); g.width = W; g.height = H; const bctx = g.getContext('2d', { willReadFrequently: true });
      const m = await CAM.shot(bctx, 's002', 4.2, { zoom: 1.08 }, { shake: { amp: 5 }, punch: .02 });
      return { a: a.z, b: b.z, ride: c.parts.ride, impact: d.parts.impact.flash, whip: d.blur, box: m && m.box('subject'),
               finite: [a, b, c, d].every(x => [x.z, x.dx, x.dy, x.rot].every(Number.isFinite)) }; }""")
    assert r["finite"] and r["a"] > r["b"] > 1.0 - 1e-9      # a punch right after a kick decays by the next half beat
    assert r["ride"] > 0 and r["impact"] is True and r["whip"] > 0
    assert r["box"] and len(r["box"]) == 4


def test_print_section_accents(page):
    r = js(page, """() => {
      const P = window.PROJECT, keep = [P.look.mode, P.look.section_accents]; P.look.mode = 'print';
      const a = [ENGINE.look('verse2').accent, ENGINE.look('bridge').accent, ENGINE.look('chorus').accent, INK.ember,
                 ENGINE.deepen('#D97757'), ENGINE.look('verse2', {accent: '#00ff00'}).accent];
      P.look.section_accents = false; a.push(ENGINE.look('verse2').accent, ENGINE.look('bridge').accent);
      [P.look.mode, P.look.section_accents] = keep; return a; }""")
    assert r == ["#db5c34", "#9a9a96", "#D97757", "#db5c34", "#db5c34", "#00ff00", "#D97757", "#D97757"]


def test_portrait_brackets_stay_in_frame(pw, demo_dir):
    pg = _open(pw, demo_dir, 1080, 1920)
    try:
        r = js(pg, """() => {
          const texts = [], lines = [], g = new Proxy(document.createElement('canvas').getContext('2d'), { get(t, k) {
            if (k === 'fillText') return (s, x, y) => { texts.push([String(s), x, y, t.measureText(String(s)).width]); };
            if (k === 'lineTo' || k === 'moveTo') return (x, y) => { lines.push([x, y]); return t[k](x, y); };
            const v = t[k]; return typeof v === 'function' ? v.bind(t) : v; }, set(t, k, v) { t[k] = v; return true; } });
          const safe = ENGINE.safeRect();
          const wide = ENGINE.fitBox([-200, 300, 1500, 1300]), cut = ENGINE.fitBox([-40, 100, 600, 900, .9]);
          const m = { box: l => (l === 'subject' ? [-40, 100, 600, 900] : null), score: () => .93 };
          ENGINE.leadKit(g, m, 5, 1, { label: 'LEAD · 01' });
          return { safe, M, wide, cut, texts, lines, land: ENGINE.fitBox([-200, 300, 1500, 1300], {}) }; }""")
    finally:
        pg.close()
    x0, y0, x1, y1 = r["safe"]
    assert r["wide"] is None                                     # wider than 90 % of the frame: no body brackets
    assert r["cut"][:4] == [x0, y0, 600 - 40 - x0, 900 + 100 - y0] and r["cut"][4] == .9
    assert r["texts"], "the lead kit drew no label"
    for s, x, y, w in r["texts"]:
        assert x0 - 1 <= x and x + w <= x1 + 1 and y >= y0, (s, x, y, w)
    assert all(x0 - 30 <= x <= x1 + 30 and y0 - 30 <= y <= y1 + 30 for x, y in r["lines"])   # brackets (+ jitter) inside


def test_missing_media_is_reported(pw, tmp_path):
    """A deleted plate: checkMedia lists it, a frame that needs it is marked, info reports it (it used to be silent)."""
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    (d / "plates" / "grad-a.jpg").unlink()
    pg = _open(pw, d)
    try:
        before = pg.page.evaluate("() => ENGINE.missingMedia")
        missing = pg.check_media()
        data, miss = pg.frame_checked(1.0)
        _, miss_ok = pg.frame_checked(4.5)                 # s002 uses grad-b: nothing missing
        info = pg.info()
        errs = [c for c in pg.console if "[media] missing" in c]
    finally:
        pg.close()
    assert before == []                                    # nothing drawn yet
    assert [m["src"].rsplit("/", 1)[-1] for m in missing] == ["grad-a.jpg"] and "plate 'grad-a'" in missing[0]["why"]
    assert len(data) > 1000 and miss and miss[0].endswith("plates/grad-a.jpg") and miss_ok == []
    assert info["missingMedia"] and len(errs) == 1         # one console.error per file, not per frame


def test_clip_without_frames_is_reported(pw, tmp_path):
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    edl = json.loads((d / "edit" / "edl.json").read_text(encoding="utf-8"))
    edl["s003"] = {"segs": [{"t0": 6.0, "clip": "SD09-t1", "in": 0.0}]}
    (d / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    pg = _open(pw, d)
    try:
        missing = pg.check_media()
        _, miss = pg.frame_checked(7.0)
    finally:
        pg.close()
    assert [m["src"] for m in missing] == ["clip:SD09-t1"] and "clips.js" in missing[0]["why"]
    assert miss == ["clip:SD09-t1"]
