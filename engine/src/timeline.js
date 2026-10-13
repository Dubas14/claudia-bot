// timeline.js — scene registry, transitions, the frame entry point used by the renderer, and the rest of window.ENGINE
// (the stable API for src/shots.js, src/devices/** and chapter code — documented in engine/README.md).
//   window.frame(t, q) → JPEG data URL of the frame at song time t     window.drawn(t) → lyric tokens drawn at t (QA)
//   window.booted (Promise) — fonts loaded and the print pass initialised (set by the page: ENGINE.boot())
// Port notes (engine-core v1): ENGINE.prepareData() normalises the project data (BEATS → SONG, SHOTS → SHOTLIST, HITS
// forms, CLIPS → SEQ, accent and fonts from PROJECT); fonts load from fonts/fonts.js (FontFace API, absolute URLs);
// a 'flash' transition in a native look flashes the overlay (the print pass's lift does not exist there);
// ENGINE.defaultShots() is a minimal stand-in used only when src/shots.js (engine-devices) is absent; ENGINE.checkMedia()
// decodes every declared media file up front and ENGINE.info() reports missingMedia / depthUnlabelled.
'use strict';
const SCENES = [];   // {name, t0, t1, prep(t) -> Promise (load assets), draw(b, o, t, lt, dur) -> look, trans}
function scene(name, t0, t1, draw, prep) { const sc = { name, t0, t1, draw, prep }; SCENES.push(sc); SCENES.sort((a, b) => a.t0 - b.t0); return sc; }
const cvOut = document.getElementById('out'), cvB = document.getElementById('base'), cvO = document.getElementById('over');
// Every 2D canvas is SOFTWARE-backed (willReadFrequently). With Chromium's GPU-backed 2D canvas (SwiftShader, headless),
// heavy frames (dense text + graphics) left the previous frame's overlay stuck — clearRect, reset() and even width
// reassignment stopped taking effect — so a frame's pixels depended on which frame the worker rendered before
// (`slop render check` compares out-of-order renders with fresh ones). Software canvases are history-independent.
const SW = { willReadFrequently: true };
const cB = cvB.getContext('2d', SW), cO = cvO.getContext('2d', SW);
let READY = false;
// a scene may declare trans: {type: 'cut'|'dither'|'flap'|'smear'|'whip'|'flash'|'custom', dur} for its ENTRY (centred on its t0)
const cvB2 = document.createElement('canvas'); cvB2.width = W; cvB2.height = H; const cB2 = cvB2.getContext('2d', SW);
const cvO2 = document.createElement('canvas'); cvO2.width = W; cvO2.height = H; const cO2 = cvO2.getContext('2d', SW);
const cvXB = document.createElement('canvas'); cvXB.width = W; cvXB.height = H; const cXB = cvXB.getContext('2d', SW);   // custom transition output
const cvXO = document.createElement('canvas'); cvXO.width = W; cvXO.height = H; const cXO = cvXO.getContext('2d', SW);
// every frame starts from a fresh context: reset() also drops leaked save() stacks, dashes, letterSpacing, textAlign,
// smoothing, filters and shadows that a previous frame (another scene, rendered first by this worker) left behind
function fresh(c) { if (c.reset) { c.reset(); return; }
  c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = 'source-over'; c.setLineDash([]); c.lineDashOffset = 0;
  c.letterSpacing = '0px'; c.textAlign = 'start'; c.textBaseline = 'alphabetic'; c.imageSmoothingEnabled = true; c.filter = 'none'; c.shadowBlur = 0;
  c.shadowColor = 'rgba(0,0,0,0)'; }
function clear(b, o) { fresh(b); b.fillStyle = '#000'; b.fillRect(0, 0, W, H); fresh(o); o.clearRect(0, 0, W, H); }
async function drawScene(sc, b, o, t) { const lt = Math.max(0, t - sc.t0), dur = sc.t1 - sc.t0; if (sc.prep) await sc.prep(t, lt, dur); clear(b, o); return (await sc.draw(b, o, t, lt, dur)) || {}; }
// a look without a mode gets the project's default look (native projects never fall into the print pass by accident)
const lookOf = L => (L && L.mode ? L : Object.assign(ENGINE.look(), L || {}));
const sceneAt = t => { let i = SCENES.findIndex(s => t >= s.t0 && t < s.t1);
  if (i < 0) { i = 0; SCENES.forEach((s, k) => { if (s.t0 <= t) i = k; }); } return SCENES[i] || null; };
async function renderAt(t) {
  _FRAME_MISSING.clear();                      // the required media this frame asks for and cannot load (core.js)
  if (window.GLASS) GLASS.begin(t);           // an empty glass field and the light for t, every frame
  if (window.OCC) OCC.begin(t);               // rewind the per-frame pool of mask canvases
  if (!SCENES.length) { clear(cB, cO); POST.run(cvB, cvO, ENGINE.look ? ENGINE.look() : {}, t); return null; }   // nothing registered: a blank frame
  const sc = sceneAt(t), i = SCENES.indexOf(sc);      // in a gap or past the end: the scene that just ended
  // transition window: the entry transition of this scene (after the cut) or of the next one (before the cut)
  const nx = SCENES[i + 1], pv = SCENES[i - 1];
  let A = sc, Bsc = null, p = 0, tr = null;
  if (nx && nx.trans && nx.trans.type !== 'cut' && t >= nx.t0 - nx.trans.dur / 2) { tr = nx.trans; Bsc = nx; p = (t - (nx.t0 - tr.dur / 2)) / tr.dur; }
  else if (sc.trans && sc.trans.type !== 'cut' && pv && t < sc.t0 + sc.trans.dur / 2) { tr = sc.trans; Bsc = sc; A = pv; p = (t - (sc.t0 - tr.dur / 2)) / tr.dur; }
  let look;
  if (tr && tr.type === 'custom' && typeof tr.draw === 'function') {
    // a composed transition: both shots are drawn, tr.draw composites them into (cvXB, cvXO) and may return the look to
    // print with. A scene can report its subject box as look.focus = [x, y, w, h] (screen px).
    const la = await drawScene(A, cB, cO, t), lb = await drawScene(Bsc, cB2, cO2, t);
    fresh(cXB); cXB.fillStyle = '#000'; cXB.fillRect(0, 0, W, H); fresh(cXO); cXO.clearRect(0, 0, W, H);
    const lk = tr.draw(p, { a: cvB, ao: cvO, b: cvB2, bo: cvO2, base: cXB, over: cXO, t, la, lb, A, B: Bsc }) || (p < .5 ? la : lb);
    POST.run(cvXB, cvXO, lookOf(lk), t);
    dropCache(); return sc.name;
  }
  if (tr && tr.type === 'dither') {
    const la = await drawScene(A, cB, cO, t), lb = await drawScene(Bsc, cB2, cO2, t);
    // base: ordered-dither dissolve A -> B in the print pass (a crossfade in 'native'); overlay and look switch at the cut
    POST.run(cvB, p < .5 ? cvO : cvO2, lookOf(p < .5 ? la : lb), t, cvB2, ease(p));
  } else {
    const cur = tr && p >= .5 ? Bsc : (tr ? A : sc);
    look = lookOf(await drawScene(cur, cB, cO, t));
    if (tr) {
      const k = p < .5 ? p * 2 : (1 - p) * 2;           // 0 → 1 at the cut → 0
      if (tr.type === 'smear') FX.smear(cB, k, t);
      if (tr.type === 'whip') FX.whip(cB, k, tr.dir || 1);
      if (tr.type === 'flap') FX.flap(cO, p, tr);
      if (tr.type === 'flash' && Math.abs(t - Bsc.t0) < 1.5 / FPS) {
        if (look.mode === 'native') { cO.save(); cO.setTransform(1, 0, 0, 1, 0, 0); cO.globalAlpha = .92; cO.fillStyle = INK.paper; cO.fillRect(0, 0, W, H); cO.restore(); }
        else look = Object.assign({}, look, { lift: .92 });
      }
    }
    POST.run(cvB, cvO, look, t);
  }
  dropCache();
  return sc.name;
}
window.renderAt = renderAt;
window.sceneAt = t => { const s = sceneAt(t); return s ? s.name : null; };
window.frame = async (t, q = .92) => { window.DRAWN && window.DRAWN.clear(); await renderAt(t); return cvOut.toDataURL('image/jpeg', q); };
window.drawn = async t => { window.DRAWN && window.DRAWN.clear(); await renderAt(t); return [...(window.DRAWN || [])]; };   // lyric QA

// ================================ the rest of window.ENGINE ================================
(() => {
  const E = ENGINE;
  E.scene = scene; E.scenes = SCENES; E.findScene = name => SCENES.find(s => s.name === name) || null;
  E.covered = (a, b, tol = .05) => SCENES.some(s => s.t0 < b - tol && s.t1 > a + tol);
  E.layers = { out: cvOut, base: cvB, over: cvO };
  E.data = {
    get song() { return SONG; }, get lyrics() { return window.LYR || []; }, get shots() { return window.SHOTLIST || { shots: [] }; },
    get edl() { return window.EDL || {}; }, get plates() { return window.PLATES || {}; }, get clips() { return window.CLIPS || {}; },
    get hits() { return window.HITS || {}; }, get track() { return window.TRACK || {}; },
  };
  // ---- time ----
  const timeAtBeat = bp => { const B = SONG.beats; if (!B || B.length < 2) return SONG.offset + bp * BEAT();
    const i = clamp(Math.floor(bp), 0, B.length - 2), f = bp - i; return B[i] + (B[i + 1] - B[i]) * f; };
  function resolve(key, shot) {
    if (key == null) return null;
    if (typeof key === 'number') return isFinite(key) ? key : null;
    if (typeof key === 'string') { if (key === 'shot.t0') return shot ? shot.t0 : null; if (key === 'shot.t1') return shot ? shot.t1 : null;
      const n = parseFloat(key); return isFinite(n) ? n : null; }
    if (typeof key !== 'object') return null;
    const tok = (spec, end) => { const [li, ti] = spec; const ln = KIN.byLine(li); if (!ln || !ln.tokens.length) return null;
      const tk = ln.tokens[ti < 0 ? ln.tokens.length + ti : ti]; return tk ? (end ? tk.t1 : tk.t0) : null; };
    if (key.word) return tok(key.word, false);
    if (key.word_end) return tok(key.word_end, true);
    if (key.beat != null) return beatAt(key.beat);
    if (key.bar != null) return barAt(key.bar);
    if (key.beats_after) { const r = resolve(key.beats_after[0], shot); return r == null ? null : timeAtBeat(bpOf(r) + (+key.beats_after[1] || 0)); }
    if (key.eighth_after) { const r = resolve(key.eighth_after[0], shot); return r == null ? null : timeAtBeat(bpOf(r) + (+key.eighth_after[1] || 0) / 2); }
    if (key.hit) { const near = resolve(key.near ?? 'shot.t0', shot); return near == null ? null : HIT.snap(near, key.hit, key.win ?? .12); }
    if (key.frame_nearest != null) { const r = resolve(key.frame_nearest, shot); return r == null ? null : r - .5 / FPS; }
    if (key.add) { const r = resolve(key.add[0], shot); return r == null ? null : r + (+key.add[1] || 0); }
    if (key.t != null) return resolve(key.t, shot);
    return null;
  }
  E.time = { bpOf, beatAt, barAt, timeAtBeat, beatLen: t => KIN.beatLen(t), beatsSince: (t, t0) => bpOf(t) - bpOf(t0), kick: KIN.kick, kickBar: KIN.kickBar,
    pulse, pulse8, exitOf: ln => KIN.exitOf(ln), sectionAt: t => (E.sectionAt(t).s || null), sectionIndex: t => E.sectionAt(t).i, resolve };
  // ---- anchors (device placement) ----
  E.anchor = function (spec, m) {
    if (spec == null) return null;
    const hasBox = m && typeof m.box === 'function';
    if (typeof spec === 'string') {
      if (spec === 'lead' || spec === 'subject') { const l = hasBox ? E.leadLabel(m) : null; return l ? m.box(l) : null; }
      if (spec === 'face') return hasBox ? m.box('a face') : null;
      return hasBox ? m.box(spec) : null;
    }
    if (Array.isArray(spec)) return spec.length >= 4 ? spec.slice(0, 4) : spec.slice(0, 2);
    if (spec.rect) return spec.rect.slice(0, 4);
    if (spec.xy) return spec.xy.slice(0, 2);
    if (spec.frac) return [spec.frac[0] * W, spec.frac[1] * H];
    if (spec.box) return hasBox ? m.box(spec.box) : null;
    if (spec.track) return hasBox ? m.box(spec.track) : null;
    if (spec.uv) return m && m.map ? m.map(spec.uv[0], spec.uv[1]) : [spec.uv[0] * W, spec.uv[1] * H];
    return null;
  };
  // ---- devices ----
  const DEVICES = E.devices = E.devices || {};
  const warned = new Set();
  E.registerDevice = function (kind, fn) {
    if (!kind || typeof fn !== 'function') throw new Error('ENGINE.registerDevice(kind, fn): kind must be a string and fn a function');
    DEVICES[String(kind)] = fn; return fn;
  };
  E.drawDevice = async function (spec, env = {}) {
    if (!spec) return null;
    const kind = spec.kind || spec.device, fn = kind && DEVICES[kind];
    if (!fn) { if (!warned.has(kind)) { warned.add(kind); console.warn(`[engine] no device registered for kind '${kind}' — skipped`); } return null; }
    const shot = env.shot || null, at = spec.at || {};
    const t0 = resolve(spec.t0 ?? at.t0 ?? 'shot.t0', shot) ?? (shot ? shot.t0 : env.t);
    const t1 = resolve(spec.t1 ?? at.t1 ?? 'shot.t1', shot) ?? (shot ? shot.t1 : Infinity);
    const e = Object.assign({}, env, { params: spec.params || {}, spec, anchor: spec.anchor != null ? E.anchor(spec.anchor, env.m) : null, t0, t1, key: spec.key || null });
    const o = env.o;
    if (o) o.save();
    try { return await fn(o, e); }
    catch (err) { console.error(`[device] '${kind}' failed at t=${(+env.t).toFixed(3)}: ${err && err.message}`); return null; }
    finally { if (o) o.restore(); }
  };
  // ---- looks for shots, overlay ink ----
  const fam = n => /pre/.test(n) ? 'pre' : /chorus/.test(n) ? 'chorus' : /verse/.test(n) ? 'verse' : n;
  E.lookFor = function (sh = {}) {
    const over = {}; if (sh.accent) over.accent = sh.accent; if (sh.screen) over.mode = sh.screen; if (sh.lift != null) over.lift = sh.lift;
    let name = sh.section; const t0 = +sh.t0 || 0;
    if (!name) { const s = E.sectionAt(t0 + 1e-3).s; name = s && s.name; }
    const f = fam(String(name || '').toLowerCase());
    let ord = 1; if (f === 'chorus' || f === 'verse') ord = (SONG.sections || []).filter(s => fam(String(s.name || '').toLowerCase()) === f && s.t0 <= t0 + 1e-3).length || 1;
    return E.look({ section: name, ordinal: ord }, over);
  };
  E.inkFor = function (L = {}) {
    const light = L.mode !== 'native' && ((L.lift || 0) > .4 || L.mode === 'bit' || L.mode === 'dot');
    return { light, color: light ? INK.ink : INK.white, accent: L.accent || INK.accent };
  };
  // the 'ember' variant of an accent: the reference accent → ember shift in HSL (hue −0.4°, saturation +.068, lightness −.065)
  E.deepen = function (hex) {
    const [r, g, b] = rgb(hex), mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
    let h = 0, s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
    if (d) h = mx === r ? ((g - b) / d + 6) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h = ((h * 60 - .4) % 360 + 360) % 360; s = clamp(s + .068); const L2 = clamp(l - .065);
    const C = (1 - Math.abs(2 * L2 - 1)) * s, X = C * (1 - Math.abs((h / 60) % 2 - 1)), m0 = L2 - C / 2;
    const [r1, g1, b1] = h < 60 ? [C, X, 0] : h < 120 ? [X, C, 0] : h < 180 ? [0, C, X] : h < 240 ? [0, X, C] : h < 300 ? [X, 0, C] : [C, 0, X];
    return '#' + [r1, g1, b1].map(v => Math.round(clamp(v + m0) * 255).toString(16).padStart(2, '0')).join('');
  };
  // ---- data normalisation (the page calls this once, after the data scripts and the engine have loaded) ----
  E.prepareData = function () {
    const S = window.SLOP || {}, D = S.data || {};
    ['BEATS', 'LYR', 'HITS', 'SHOTS', 'SHOTLIST', 'EDL', 'PLATES', 'CLIPS', 'TRACK', 'FXSEQ', 'SPECTRUM'].forEach(k => { if (window[k] === undefined && D[k] !== undefined && D[k] !== null) window[k] = D[k]; });
    const PJ = window.PROJECT = window.PROJECT || {};
    if (!window.SHOTLIST && window.SHOTS) window.SHOTLIST = window.SHOTS;
    if (Array.isArray(window.SHOTLIST)) window.SHOTLIST = { shots: window.SHOTLIST };
    if (window.SHOTLIST && !Array.isArray(window.SHOTLIST.shots)) window.SHOTLIST.shots = [];
    // lyrics: every line has kind + tokens with numeric t0/t1
    window.LYR = (Array.isArray(window.LYR) ? window.LYR : []).filter(ln => ln && Array.isArray(ln.tokens)).map(ln => {
      const toks = ln.tokens.filter(tk => tk && isFinite(+tk.t0)).map(tk => Object.assign({}, tk, { txt: String(tk.txt ?? tk.w ?? ''), t0: +tk.t0, t1: isFinite(+tk.t1) ? +tk.t1 : +tk.t0 + .2, st: tk.st || '' }));
      return Object.assign({}, ln, { kind: ln.kind || 'lyric', tokens: toks, t0: isFinite(+ln.t0) ? +ln.t0 : (toks[0] ? toks[0].t0 : 0), t1: isFinite(+ln.t1) ? +ln.t1 : (toks.length ? toks[toks.length - 1].t1 : 0) });
    });
    // the clock
    const BT = window.BEATS || {};
    Object.assign(SONG, BT);
    if (!Array.isArray(SONG.beats) || SONG.beats.length < 2) { SONG.beats = null; const tp = (BT.tempo || [])[0]; SONG.bpm = (tp && +tp.bpm) || +BT.bpm || +PJ.bpm || 120; }
    if (!Array.isArray(SONG.downbeats)) SONG.downbeats = null;
    SONG.sections = (Array.isArray(SONG.sections) ? SONG.sections : []).map(s => ({ ...s, name: s.name ?? s.label ?? '', t0: +(s.t0 ?? s.start ?? 0), t1: +(s.t1 ?? s.end ?? 0) }))
      .filter(s => isFinite(s.t0)).sort((a, b) => a.t0 - b.t0);
    const shots = (window.SHOTLIST || {}).shots || [];
    SONG.duration = +SONG.duration || +((window.SHOTLIST || {}).duration) || +PJ.duration
      || Math.max(0, ...shots.map(s => +s.t1 || 0), ...window.LYR.map(l => l.t1 + 2)) || 0;
    if (window.CLIPS) Object.assign(SEQ, window.CLIPS);
    if (window.HITS) window.HITS = HIT.normalize(window.HITS);
    // project accent and type
    const PL = PJ.look || {};
    if (PL.accent) { INK.accent = INK.clay = INK.red = PL.accent; if (rgb(PL.accent).join() !== rgb('#D97757').join()) INK.ember = E.deepen(PL.accent); }
    const q = f => (/^["']/.test(f) ? f : `"${f}"`), fonts = PL.fonts || {};
    if (fonts.lyric) F.grotesk = F.round = q(fonts.lyric);
    if (fonts.micro) F.mono = q(fonts.micro);
    if (fonts.display) F.display = q(fonts.display);
    E.prepared = true;
  };
  // ---- the fallback base when a shot has no media yet: a quiet gradient (never a black hole) ----
  E.fallbackBase = function (b, t, L = {}) {
    const light = E.inkFor(L).light, g = b.createLinearGradient(0, 0, W * .3, H);
    if (light) { g.addColorStop(0, INK.paper); g.addColorStop(1, INK.paper2); } else { g.addColorStop(0, '#1b1f26'); g.addColorStop(1, INK.night); }
    b.fillStyle = g; b.fillRect(0, 0, W, H);
  };
  // ---- the minimal default renderer (only when src/shots.js is absent or did not claim ENGINE.shotsRenderer) ----
  const place = (p, mode) => {
    const s = String(p || '').toLowerCase(), o = {}, yAt = px => Math.round(H * px / 1080);
    if (/right/.test(s)) { o.x = PORTRAIT ? W - M.r : W * .56; o.align = 'right'; } else o.x = M.l;
    if (/top|upper/.test(s)) o.y = mode === 'masthead' ? Math.max(yAt(300), M.t + 200) : Math.max(yAt(250), M.t + 120);
    else if (/bottom|lower/.test(s)) o.y = H - Math.max(220, M.b + 60); else o.y = mode === 'masthead' ? yAt(640) : yAt(560);
    if (/cent/.test(s) && !/left|right/.test(s)) { o.x = W / 2; o.align = 'center'; }
    return o;
  };
  E.defaultShots = function () {
    const SL = window.SHOTLIST || {}, shots = (SL.shots || []).filter(s => s && isFinite(+s.t0) && isFinite(+s.t1) && +s.t1 > +s.t0)
      .map(s => Object.assign({}, s, { t0: +s.t0, t1: +s.t1 })).sort((a, b) => a.t0 - b.t0);
    const dur = SONG.duration || (shots.length ? shots[shots.length - 1].t1 : 0) || 8;
    let n = 0;
    const draw = sh => async (b, o, t, lt, d) => {
      const cam = MEDIA.camFrom(sh.camera || '', clamp(lt / d), { t, amt: 1 });
      cam.zoom = (cam.zoom || 1.06) + .018 * KIN.kickBar(t);
      const m = sh.id ? await MEDIA.drawShot(b, sh.id, t, cam) : null;
      const L = Object.assign({}, E.lookFor(sh)), ink = E.inkFor(L);
      if (!m) E.fallbackBase(b, t, L);
      const lead = m ? E.leadLabel(m) : null, leadBox = lead ? m.box(lead) : null;
      if (sh.lead_on_screen && m) E.leadKit(o, m, t, sh.t0, { face: /\b(E?CU|MCU)\b/.test(String(sh.framing || '')), color: ink.color });
      const done = new Set(), common = { accent: ink.accent, color: ink.color };
      (Array.isArray(sh.type) ? sh.type : []).forEach(ty => {
        const ln = ty && ty.line != null ? KIN.byLine(ty.line) : null; if (!ln) return; done.add(ln.line);
        const p = place(ty.placement, ty.mode), opts = Object.assign({}, common, p);
        if (/cover/.test(String(ty.mode))) Object.assign(opts, { avoid: leadBox, micro: [`L${String(ln.line).padStart(2, '0')} · ${KIN.tc(ln.t0)}`, sh.meme_visual ? String(sh.meme_visual).slice(0, 48) : ''] });
        E.type.draw(ty.mode || 'subtitle', o, ln, t, opts, { shot: sh, m, b, t0: sh.t0 });
      });
      // never lose a word: every other line on screen now is drawn as a subtitle
      KIN.active(t).forEach(ln => { if (!done.has(ln.line)) KIN.subtitle(o, ln, t, common); });
      for (const dv of (Array.isArray(sh.devices) ? sh.devices : [])) await E.drawDevice(dv, { o, b, t, lt, dur: d, shot: sh, m, look: L, color: ink.color, accent: ink.accent });
      E.chrome(o, t, { color: ink.color, accent: ink.accent });
      if (leadBox) L.focus = leadBox;
      return L;
    };
    shots.forEach(sh => {
      if (E.covered(sh.t0, sh.t1)) return;
      const sc = scene(sh.id || `shot${n}`, sh.t0, sh.t1, draw(sh)); n++;
      const tr = sh.transition_in ?? sh.trans_in ?? sh.trans;
      if (tr) E.transitions.set(sc, tr);
    });
    // fill every gap (no storyboard yet, or holes in it) so the film renders end to end
    const spans = SCENES.map(s => [s.t0, s.t1]).sort((a, b) => a[0] - b[0]); let cur = 0; const gaps = [];
    spans.forEach(([a, b2]) => { if (a - cur > .5 / FPS) gaps.push([cur, a]); cur = Math.max(cur, b2); });
    if (dur - cur > .5 / FPS) gaps.push([cur, dur]);
    gaps.forEach(([a, b2], k) => { scene(`fill${k}`, a, b2, draw({ id: null, t0: a, t1: b2 })); n++; });
    if (n) E.stubScenes = n;
    E.shotsRenderer = E.shotsRenderer || (n ? 'engine-stub' : null);
    return n;
  };
  // ---- boot: fonts (bundled + project), the print pass ----
  E.boot = async function () {
    if (!E.prepared) E.prepareData();
    POST.init(cvOut);
    const base = E.urls.engine || '', faces = ((window.ENGINE_FONTS || {}).faces || []).concat((window.PROJECT || {}).font_files || []);
    const failed = [];
    await Promise.all(faces.map(f => {
      try {
        const url = /^(file|https?|data):/.test(f.file) ? f.file : (f.project ? E.url(f.file) : `${base}fonts/${f.file}`);
        const ff = new FontFace(f.family, `url("${url}")`, { weight: String(f.weight || '400'), style: f.style || 'normal' });
        document.fonts.add(ff); return ff.load().catch(() => failed.push(f.file));
      } catch (e) { failed.push(f.file); return null; }
    }));
    if (failed.length) console.error('[engine] fonts failed to load: ' + failed.join(', '));
    await Promise.all(((window.PROJECT || {}).preload || []).map(f => document.fonts.load(f).catch(() => null)));
    E.fontsFailed = failed; READY = true;
    return true;
  };
  // ---- media preflight: every file the film declares (PLATES, EDL plates and clips, CLIPS first/last frames, declared
  // depth and mattes) is decoded once — nothing is cached — so a missing plate fails BEFORE thousands of frames are
  // drawn over a placeholder. Resolves to ENGINE.missingMedia (also filled by every failed load while drawing).
  E.checkMedia = async function () {
    const PL = window.PLATES || {}, ED = window.EDL || {}, CL = window.CLIPS || {}, jobs = [], plates = new Set(Object.keys(PL)), clips = new Set();
    Object.values(ED).forEach(e => { if (!e || typeof e !== 'object') return; if (e.plate) plates.add(e.plate);
      (Array.isArray(e.segs) ? e.segs : []).forEach(sg => { if (sg && sg.clip) clips.add(sg.clip); }); });
    const probe = (src, why) => jobs.push(async () => { const im = new Image(); im.src = src;
      try { await im.decode(); } catch (e) { E.noteMissing(src, why); } });
    plates.forEach(n => { const m = PL[n] || {}, f = (typeof m.file === 'string' && m.file) || (typeof m.src === 'string' && m.src) || `assets/plates/${n}.jpg`;
      probe(f, `plate '${n}'`);
      if (typeof m.depth === 'string' && E.depthOK(m)) probe(m.depth, `depth of plate '${n}'`);
      if (m.matte) probe(typeof m.matte === 'string' ? m.matte : `assets/plates/${n}.matte.png`, `matte of plate '${n}'`); });
    clips.forEach(n => { const c = CL[n];
      if (!c || !c.n) { E.noteMissing('clip:' + n, 'used by the EDL but not in window.CLIPS (engine/clips.js) — run `slop edit export`'); return; }
      [1, c.n].forEach(i => probe(`${c.dir}/f${String(i).padStart(5, '0')}.jpg`, `clip '${n}' frame ${i}/${c.n}`)); });
    for (let i = 0; i < jobs.length; i += 6) await Promise.all(jobs.slice(i, i + 6).map(j => j()));   // a few at a time: bounded memory
    _FRAME_MISSING.clear();
    return E.missingMedia;
  };
  // plates whose declared depth map is not labelled Depth-Anything-V2-Small (drawn flat; `slop render info` warns)
  E.depthUnlabelled = () => Object.entries(window.PLATES || {}).filter(([, m]) => m && typeof m.depth === 'string' && !E.depthOK(m)).map(([n]) => n);
  E.info = () => ({ W, H, FPS, portrait: PORTRAIT, duration: SONG.duration, beats: (SONG.beats || []).length, sections: (SONG.sections || []).length,
    lyrics: (window.LYR || []).length, tokens: (window.LYR || []).reduce((a, l) => a + l.tokens.length, 0), shots: ((window.SHOTLIST || {}).shots || []).length,
    scenes: SCENES.length, stubScenes: E.stubScenes || 0, shotsRenderer: E.shotsRenderer || null,
    devices: Object.keys(DEVICES).concat(Object.keys((window.DEV && window.DEV.REG) || {})), fontsFailed: E.fontsFailed || [], ready: READY,
    missingMedia: E.missingMedia, depthUnlabelled: E.depthUnlabelled(),
    look: ((window.PROJECT || {}).look || {}).mode || 'native' });
})();
