// devices/trans.js — entry transitions for shots.json transition_in, as timeline custom transitions
// ({type: 'custom', dur, draw(p, c)}: p 0..1 with the cut at .5; c = {a, ao, b, bo (each shot's base/overlay), base, over
// (the output), t, la, lb (the looks; .focus = the subject box), A, B (the scenes)}). Each lands on its cut (a beat).
//   through   push through a point of A (its subject) and come out of a point of B — a match cut on shape
//   whip      a whip pan: A leaves along dir with a motion smear, B arrives from the other side (the frame wraps: no black)
//   flashCut  a hard cut whose first frame is B in inverted black and white (counts toward the ≤ 3 flashes/s rule)
//   dither    an ordered-dither dissolve (Bayer 8 × 8 at 1/4 resolution; overlay and look switch at the cut) — a print-look
//             texture: in a clean (native) look it is drawn as `fade`, as the engine's own dither is
//   fade      a plain crossfade (overlay and look switch at the cut)
//   flap      the frame flips like a split-flap board: 16 × 9 tiles, a wave from the upper left
//   smear     a photocopier scan band drags rows sideways through the cut (a print-look texture: the plan warns in a clean look)
//   match     a match cut: B's subject starts where A's was and eases to rest
//   flash     a one-frame paper flash on the cut (counts toward the flash rule) · iris · push · cut
// Any other name the engine's registry knows (ENGINE.transitions: luma, bands, zoom, wrap, and whatever a project
// registers) is played through it; a name nobody knows is a hard cut AND a plan warning (never silent).
// Ports, fixed: match = the first video's private matchCut (the engine's FX.T.match leaked the scale into the centre so B's
// subject landed off target and the edge could show: here the centre is lerped, the scale clamped to [1/1.6, 1.6] and the
// translation clamped so no edge shows); whip = the second video's cleanWhip (two smear passes: no banding) and whipV (a
// mirrored vertical wrap: no seam); flap = the first video's flapWipe (both layers flip; the engine's FX.flap only dropped
// dark tiles over the overlay); dither/smear/flash are canvas-only (no dependency on the print pass).
// Prose is matched most specific first; prose that starts with "cut" is a cut ("cut into the chorus" is not a push-through).
'use strict';
(() => {
  const D = window.DEV; if (!D || D.trans) return;
  const C = D.C;
  const PRESETS = { through: { dur: .3, depth: 5 }, whip: { dur: .3, dir: 0, dist: 760, blur: 340 }, flashCut: { dur: .2, invert: true, frames: 1 }, dither: { dur: .45 },
    flap: { dur: .5, cols: 16, rows: 9 }, smear: { dur: .3, bands: 7, amp: 220 }, match: { dur: .5 }, flash: { dur: .2, frames: 1 }, iris: { dur: .5, shape: 'circle' },
    push: { dur: .4, dir: 1 }, fade: { dur: .4 }, cut: { dur: 0 } };
  const ALIAS = { 'flash-cut': 'flashCut', flashcut: 'flashCut', 'flash cut': 'flashCut', invert: 'flashCut', 'push-through': 'through', 'zoom-through': 'through', 'zoom through': 'through',
    'push through': 'through', 'match-cut': 'match', 'match cut': 'match', matchcut: 'match', dissolve: 'dither', 'split-flap': 'flap', splitflap: 'flap', scan: 'smear', xerox: 'smear',
    'whip-pan': 'whip', 'whip pan': 'whip', 'hard cut': 'cut', none: 'cut', paper: 'flash', 'white flash': 'flash', circle: 'iris', slide: 'push',
    crossfade: 'fade', 'cross-fade': 'fade', 'cross fade': 'fade', mix: 'fade' };
  const DIRS = { right: 0, left: Math.PI, down: Math.PI / 2, up: -Math.PI / 2 };
  // transition_in (string prose or {preset, …opts}) → {preset, opts} · null (a hard cut) · {preset: null, unknown} (a name
  // nobody knows: the plan warns and cuts) · {preset, engine: true, opts} (played through ENGINE.transitions)
  const ENG = () => (typeof ENGINE !== 'undefined' && ENGINE.transitions && ENGINE.transitions.registry) || null;
  function prose(s) {
    if (/^(hard |straight |clean )?cut\b/.test(s) || /^none\b/.test(s)) return 'cut';
    if (/flash ?-?cut|invert/.test(s)) return 'flashCut';
    if (/match/.test(s)) return 'match';
    if (/\bthrough\b|\b(push|pushes|zoom|zooms|dive|dives) into\b/.test(s)) return 'through';
    if (/whip/.test(s)) return 'whip';
    if (/dither|dissolve/.test(s)) return 'dither';
    if (/cross-? ?fade|\bfade\b/.test(s)) return 'fade';
    if (/flap/.test(s)) return 'flap';
    if (/smear|\bscan\b|xerox/.test(s)) return 'smear';
    if (/iris/.test(s)) return 'iris';
    if (/\bpush\b|\bslide\b/.test(s)) return 'push';
    if (/flash/.test(s)) return 'flash';
    return null;
  }
  function parse(v) {
    if (v == null || v === '' || v === false) return null;
    let o = typeof v === 'string' ? {} : Object.assign({}, v), s = String(typeof v === 'string' ? v : (v.preset || v.type || v.kind || '')).toLowerCase().trim();
    if (!s) return { preset: null, unknown: v };
    let preset = PRESETS[s] ? s : ALIAS[s] || (s === 'flashcut' ? 'flashCut' : null);
    if (!preset) {
      const reg = ENG();
      if (reg && reg[s] && !/^(cut|flashcut)$/.test(s)) { delete o.preset; delete o.type; delete o.kind; return { preset: s, engine: true, opts: o }; }
      preset = prose(s);
      const dm = s.match(/\b(left|right|up|down)\b/); if (preset && dm && o.dir == null) o.dir = DIRS[dm[1]];
      if (!preset && reg && typeof ENGINE.transitions.fromProse === 'function') { const e = ENGINE.transitions.fromProse(s); if (e && e !== 'cut' && reg[e]) { delete o.preset; delete o.type; delete o.kind; return { preset: e, engine: true, opts: o }; } }
      if (!preset) return { preset: null, unknown: v };
    }
    if (typeof o.dir === 'string') o.dir = DIRS[o.dir.toLowerCase()] ?? (isFinite(+o.dir) ? +o.dir : 0);
    if (preset === 'cut') return null;
    delete o.preset; delete o.type; delete o.kind;
    ['dur', 'depth', 'dist', 'blur', 'frames', 'cols', 'rows', 'bands', 'amp'].forEach(k => { if (typeof o[k] === 'string' && isFinite(+o[k])) o[k] = +o[k]; });
    return { preset, opts: Object.assign({}, PRESETS[preset], o) };
  }
  // the full-frame flashes a transition makes (for the flash budget): flashCut and flash fire on B's first frame (they can
  // be dropped); every other designed transition is a big frame change the master's flash check can count — a fixed event
  // the droppable flashes are planned around
  const flashTimes = (tr, cut) => tr && tr.preset && (tr.preset === 'flashCut' || tr.preset === 'flash') ? [cut] : [];
  const fixedTimes = (tr, cut) => tr && tr.preset && tr.preset !== 'flashCut' && tr.preset !== 'flash' && tr.preset !== 'fade' ? [cut] : [];

  const ctr = (bx, d) => bx ? [bx[0] + bx[2] / 2, bx[1] + bx[3] / 2] : d;
  const smear = (g, len, ang, n = 10) => { if (D.has.CAM()) return CAM.smear(g, len, ang, n); if (!(len > .5)) return;
    const s = D.scratch(W, H); s.getContext('2d').drawImage(g.canvas, 0, 0); g.save(); g.setTransform(1, 0, 0, 1, 0, 0); const ux = Math.cos(ang), uy = Math.sin(ang);
    for (let k = 0; k < n; k++) { const q = (k / (n - 1) - .5) * len; g.globalAlpha = 1 / (k + 1); g.drawImage(s, ux * q, uy * q); } g.restore(); };
  const FPS_ = () => (typeof FPS !== 'undefined' ? FPS : 24);

  const T = {
    through: o => (p, c) => {
      const [ax, ay] = o.a || ctr(c.la && c.la.focus, [W / 2, H / 2]), [bx, by] = o.b || ctr(c.lb && c.lb.focus, [W / 2, H / 2]), z = o.depth ?? 5;
      if (p < .5) { const k = 1 + (z - 1) * easeIn(p * 2); c.base.setTransform(k, 0, 0, k, ax - ax * k, ay - ay * k); c.base.drawImage(c.a, 0, 0); }
      else { const k = 1 + (z - 1) * (1 - easeOut((p - .5) * 2)); c.base.setTransform(k, 0, 0, k, bx - bx * k, by - by * k); c.base.drawImage(c.b, 0, 0); }
      c.base.setTransform(1, 0, 0, 1, 0, 0); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; },
    whip: o => (p, c) => {
      const ang = o.dir ?? 0, D_ = o.dist ?? 760, ux = Math.cos(ang), uy = Math.sin(ang), img = p < .5 ? c.a : c.b, ov = p < .5 ? c.ao : c.bo;
      const vertical = Math.abs(uy) > .7;
      if (vertical) {                                                         // whipV: mirrored wrap tiles, no seam
        const off = (p < .5 ? -D_ * easeIn(p * 2) : D_ * (1 - easeOut((p - .5) * 2))) * Math.sign(uy || 1);
        for (const k of [-1, 0, 1]) { c.base.save(); c.base.translate(0, off + k * H); if (k) { c.base.translate(0, H); c.base.scale(1, -1); } c.base.drawImage(img, 0, 0); c.base.restore(); }
        const L = (o.blur ?? 150) * Math.sin(p * Math.PI); if (L > 1) smear(c.base, L, Math.PI / 2, 30);
        c.over.globalAlpha = Math.abs(p * 2 - 1); c.over.drawImage(ov, 0, off); c.over.globalAlpha = 1; return p < .5 ? c.la : c.lb;
      }
      const d = p < .5 ? D_ * easeIn(p * 2) : -D_ * (1 - easeOut((p - .5) * 2)), s = 1 + .06 * Math.sin(p * Math.PI);
      for (const k of [-1, 0, 1]) { c.base.save(); c.base.translate(W / 2 + ux * (d + k * W * s), H / 2 + uy * (d + k * H * s)); c.base.scale(s, s); c.base.translate(-W / 2, -H / 2); c.base.drawImage(img, 0, 0); c.base.restore(); }
      const L = (o.blur ?? 340) * Math.sin(p * Math.PI); if (L > 1) { smear(c.base, L, ang, 16); smear(c.base, L / 15, ang, 8); }      // cleanWhip: two passes
      c.over.globalAlpha = Math.abs(p * 2 - 1); c.over.drawImage(ov, ux * d, uy * d); c.over.globalAlpha = 1; return p < .5 ? c.la : c.lb; },
    flashCut: o => (p, c) => {
      const cut = c.B ? c.B.t0 : c.t, pre = c.t < cut - 1e-6; c.base.drawImage(pre ? c.a : c.b, 0, 0);
      if (!pre && c.t < cut + (o.frames ?? 1) / FPS_() - 1e-6 && (!o.flashOk || o.flashOk(cut))) D.mono(c.over, c.b, { invert: o.invert !== false });
      else c.over.drawImage(pre ? c.ao : c.bo, 0, 0);
      return pre ? c.la : c.lb; },
    flash: o => (p, c) => {
      const cut = c.B ? c.B.t0 : c.t, pre = c.t < cut - 1e-6; c.base.drawImage(pre ? c.a : c.b, 0, 0); c.over.drawImage(pre ? c.ao : c.bo, 0, 0);
      if (!pre && c.t < cut + (o.frames ?? 1) / FPS_() - 1e-6 && (!o.flashOk || o.flashOk(cut))) { c.over.fillStyle = 'rgba(244,242,236,.92)'; c.over.fillRect(0, 0, W, H); }
      return pre ? c.la : c.lb; },
    dither: o => (p, c) => {
      const th = ease(p) * 64, s = D.scratch(480, 270), g = s.getContext('2d', { willReadFrequently: true }), I = g.createImageData(480, 270), d = I.data;
      for (let y = 0, i = 3; y < 270; y++) for (let x = 0; x < 480; x++, i += 4) d[i] = BAY8[(y & 7) * 8 + (x & 7)] < th ? 255 : 0;
      g.putImageData(I, 0, 0);
      const bb = D.scratch(W, H), bg = bb.getContext('2d'); bg.drawImage(c.b, 0, 0); bg.globalCompositeOperation = 'destination-in'; bg.imageSmoothingEnabled = false; bg.drawImage(s, 0, 0, W, H);
      c.base.drawImage(c.a, 0, 0); c.base.drawImage(bb, 0, 0); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; },
    flap: o => (p, c) => {
      const cols = o.cols || 16, rows = o.rows || 9, cw = W / cols, ch = H / rows;
      const flip = (g, A, B) => { for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) {
        const d = (k / cols * .62 + r / rows * .38) * .56 + hash2(r, k) * .07, q = clamp((p - d) / .34), x = k * cw, y = r * ch, hy = y + ch / 2;
        if (q <= 0) { g.drawImage(A, x, y, cw, ch, x, y, cw, ch); continue; }
        if (q >= 1) { g.drawImage(B, x, y, cw, ch, x, y, cw, ch); continue; }
        if (q < .5) { const s = 1 - 2 * q; g.drawImage(B, x, y, cw, ch / 2, x, y, cw, ch / 2); g.drawImage(A, x, hy, cw, ch / 2, x, hy, cw, ch / 2);
          g.drawImage(A, x, y, cw, ch / 2, x, hy - ch / 2 * s, cw, Math.max(.5, ch / 2 * s)); if (g === c.base) { g.fillStyle = `rgba(0,0,0,${.55 * (1 - s)})`; g.fillRect(x, hy - ch / 2 * s, cw, ch / 2 * s); g.fillStyle = 'rgba(244,242,236,.7)'; g.fillRect(x, hy - ch / 2 * s - 1, cw, 2); } }
        else { const s = 2 * q - 1; g.drawImage(B, x, y, cw, ch / 2, x, y, cw, ch / 2); g.drawImage(A, x, hy, cw, ch / 2, x, hy, cw, ch / 2);
          g.drawImage(B, x, hy, cw, ch / 2, x, hy, cw, Math.max(.5, ch / 2 * s)); if (g === c.base) { g.fillStyle = `rgba(0,0,0,${.5 * (1 - s)})`; g.fillRect(x, hy, cw, ch / 2 * s); } }
        if (g === c.base) { g.fillStyle = 'rgba(0,0,0,.7)'; g.fillRect(x, hy - 1.5, cw, 3); g.fillRect(x, y, 2, ch); } } };
      flip(c.base, c.a, c.b); flip(c.over, c.ao, c.bo); return p < .5 ? c.la : c.lb; },
    smear: o => (p, c) => {
      const k = p < .5 ? p * 2 : (1 - p) * 2, src = p < .5 ? c.a : c.b; c.base.drawImage(src, 0, 0);
      const n = o.bands || 7, amp = (o.amp ?? 220) * Math.sin(k * Math.PI), f = Math.floor(c.t * FPS_());
      for (let i = 0; i < n; i++) { const y = Math.floor(hash2(i, f) * H), h = 6 + Math.floor(hash2(i + 9, 3) * 60), dx = (hash2(i, 7) - .5) * 2 * amp; c.base.drawImage(src, 0, y, W, h, dx, y, W, h); }
      c.base.fillStyle = 'rgba(244,242,236,.55)'; c.base.fillRect(0, k * H - 2, W, 4); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; },
    match: o => (p, c) => {
      const A = c.la && c.la.focus, B = c.lb && c.lb.focus;
      if (p < .5 || !A || !B) { c.base.drawImage(p < .5 ? c.a : c.b, 0, 0); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; }
      const k = 1 - easeOut((p - .5) * 2), ax = A[0] + A[2] / 2, ay = A[1] + A[3] / 2, bx = B[0] + B[2] / 2, by = B[1] + B[3] / 2;
      // (a scale under 1 would uncover the frame edge, so B is never shrunk: it starts at most 1.6× and settles to 1)
      const s = Math.max(1, 1 + k * (clamp(A[3] / Math.max(1, B[3]), 1 / 1.6, 1.6) - 1));
      const tx = clamp(lerp(bx, ax, k) - s * bx, W - W * s, 0), ty = clamp(lerp(by, ay, k) - s * by, H - H * s, 0);      // never expose the edge
      c.base.setTransform(s, 0, 0, s, tx, ty); c.base.drawImage(c.b, 0, 0); c.base.setTransform(1, 0, 0, 1, 0, 0);
      c.over.drawImage(c.bo, 0, 0); return c.lb; },
    iris: o => (p, c) => {
      const [cx, cy] = o.at || ctr(c.la && c.la.focus, [W / 2, H / 2]), r = easeInOut(p) * Math.hypot(W, H) * .75;
      c.base.drawImage(c.a, 0, 0); c.base.save(); c.base.beginPath();
      if (o.shape === 'spark' && D.sparkPath) D.sparkPath(c.base, cx, cy, Math.max(1, r)); else c.base.arc(cx, cy, Math.max(1, r), 0, TAU);
      c.base.clip(); c.base.drawImage(c.b, 0, 0); c.base.restore(); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; },
    fade: o => (p, c) => {
      const k = ease(p); c.base.drawImage(c.a, 0, 0); c.base.globalAlpha = k; c.base.drawImage(c.b, 0, 0); c.base.globalAlpha = 1;
      c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; },
    push: o => (p, c) => {
      const d = o.dir || 1, e = easeInOut(p), horiz = Math.abs(d) === 1, sg = Math.sign(d), L = horiz ? W : H, off = e * L * sg;
      const ax = horiz ? -off : 0, ay = horiz ? 0 : -off, bx = horiz ? L * sg - off : 0, by = horiz ? 0 : L * sg - off;
      c.base.drawImage(c.a, ax, ay); c.base.drawImage(c.b, bx, by);
      const amp = 90 * Math.sin(p * Math.PI); c.base.globalAlpha = .25; for (let i = 1; i <= 3; i++) c.base.drawImage(c.b, bx - (horiz ? sg * amp * i / 3 : 0), by - (horiz ? 0 : sg * amp * i / 3)); c.base.globalAlpha = 1;
      c.over.drawImage(c.ao, ax, ay); c.over.drawImage(c.bo, bx, by); return p < .5 ? c.la : c.lb; },
  };
  const BAY8 = (() => { const m = [0, 32, 8, 40, 2, 34, 10, 42, 48, 16, 56, 24, 50, 18, 58, 26, 12, 44, 4, 36, 14, 46, 6, 38, 60, 28, 52, 20, 62, 30, 54, 22,
    3, 35, 11, 43, 1, 33, 9, 41, 51, 19, 59, 27, 49, 17, 57, 25, 15, 47, 7, 39, 13, 45, 5, 37, 63, 31, 55, 23, 61, 29, 53, 21]; return m; })();

  // a timeline transition object for a parsed preset (the draw looks the preset up at call time)
  function make(tr, extra = {}) {
    if (!tr || !tr.preset) return null;
    if (tr.engine) {                                  // a preset from the engine's registry (ENGINE.transitions)
      let r = null; try { r = ENGINE.transitions.make(Object.assign({ preset: tr.preset }, tr.opts || {}), extra.t0); } catch (e) { r = null; }
      if (!r || r.type !== 'custom' || typeof r.draw !== 'function') return null;
      return { type: 'custom', dur: Math.max(1 / FPS_(), +r.dur || .3), draw: r.draw, preset: tr.preset, engine: true };
    }
    const o = Object.assign({}, tr.opts, extra), f = (T[tr.preset] || T.through)(o);
    return { type: 'custom', dur: Math.max(1 / FPS_(), +o.dur || .3), draw: f, preset: tr.preset }; }
  // the names a storyboard may use (this library's presets, then the engine registry's)
  const names = () => Object.keys(PRESETS).filter(k => k !== 'cut').concat(Object.keys(ENG() || {}).filter(k => !PRESETS[k] && !/^(cut|flashcut)$/.test(k)));
  D.trans = { PRESETS, ALIAS, parse, make, flashTimes, fixedTimes, names, T };
  D.alias('TR', { whip: o => T.whip(o || {}), through: o => T.through(o || {}), flashCut: o => T.flashCut(o || {}) });
})();
