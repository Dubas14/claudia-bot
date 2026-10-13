// trans.js — transitions centred on a cut time (the storyboard puts cuts on beats or hits) and base-layer effects.
// A scene's ENTRY transition is scene.trans = {type, dur, ...}; timeline.js plays it from t0 − dur/2 to t0 + dur/2.
// Built-in types (timeline.js): cut · dither (ordered-dither dissolve in the print pass; a crossfade in 'native') · flap
// (split-flap tiles flip over the frame) · smear (xerox scan band drags the image) · whip (horizontal motion smear) ·
// flash (1-frame paper flash). Custom presets {type: 'custom', dur, draw: FX.T.<name>(params)}: iris, zoom, match, push,
// luma, bands, through (push through a point of A and out of a point of B), wrap (a whip pan that wraps — no black edge),
// flashCut (a hard cut whose first frame is B in inverted mono). ENGINE.transitions is the registry (make/register/set).
// A transition is an idea (the graphic of one shot becomes the frame of the next), lands on a beat, and never repeats
// the same device twice in a row; most cuts stay hard cuts.
// Port notes (engine-core v1): FX.T.match now lands B's subject exactly on A's (centre lerped; scale in [1, 1.6]: the
// subject-box ratio, raised just enough to make room for the offset) and clamps the translation so the frame edge never
// shows (it drifted off target by bx·(s−1)·(1−k) and could expose the edge; a smaller subject in A shrank B below 1×); iris draws its spark locally (no dependency on a graphics library); through / wrap / flashCut
// are generic presets ported from the second reference video's kit.
'use strict';
const FX = (() => {
  const SWC = { willReadFrequently: true };   // software-backed canvases (timeline.js note)
  const tmp = document.createElement('canvas'); tmp.width = W; tmp.height = H; const tx = tmp.getContext('2d', SWC);
  // xerox scan smear: a band of rows is dragged sideways with streaks, k 0..1 (peak at .5)
  function smear(ctx, k, t, o = {}) {
    if (k <= 0) return; tx.clearRect(0, 0, W, H); tx.drawImage(ctx.canvas, 0, 0);
    const n = o.bands || 7, amp = (o.amp ?? 220) * Math.sin(k * Math.PI);
    for (let i = 0; i < n; i++) { const y = Math.floor(hash2(i, Math.floor(t * 24)) * H), h = 6 + Math.floor(hash2(i + 9, 3) * 60);
      const dx = (hash2(i, 7) - .5) * 2 * amp; ctx.drawImage(tmp, 0, y, W, h, dx, y, W, h); }
    // one bright scan line sweeping down the frame
    const sy = k * H; ctx.fillStyle = 'rgba(244,242,236,.55)'; ctx.fillRect(0, sy - 2, W, 4);
  }
  // whip: horizontal motion blur by stacking offset copies
  function whip(ctx, k, dir = 1) {
    if (k <= 0) return; tx.clearRect(0, 0, W, H); tx.drawImage(ctx.canvas, 0, 0);
    const amp = 260 * Math.sin(k * Math.PI), n = 10; ctx.globalAlpha = 1 / n;
    for (let i = 0; i < n; i++) ctx.drawImage(tmp, dir * amp * (i / n - .5), 0);
    ctx.globalAlpha = 1;
  }
  // split-flap wipe on the overlay: a grid of tiles flips closed before the cut and open after (p 0..1, cut at .5)
  function flap(ctx, p, o = {}) {
    if (p <= 0 || p >= 1) return; const cols = o.cols || 16, rows = o.rows || 9, cw = W / cols, ch = H / rows, col = o.color || '#161719';
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const d = (c / cols) * .35 + hash2(r, c) * .15;                        // left-to-right stagger
      const q = p < .5 ? clamp((p * 2 - d) / (1 - .5)) : 1 - clamp(((p - .5) * 2 - d) / (1 - .5));
      if (q <= 0) continue;
      const hgt = ch * q; ctx.fillStyle = col; ctx.fillRect(c * cw + 1, r * ch + (ch - hgt) / 2, cw - 2, hgt);
      ctx.fillStyle = 'rgba(0,0,0,.6)'; ctx.fillRect(c * cw + 1, r * ch + ch / 2 - 1, cw - 2, 2);
    }
  }
  // the spark outline (an irregular multi-ray burst) used by iris({shape: 'spark'})
  function sparkPath(ctx, x, y, r, o = {}) {
    const n = o.rays || 12, rot = o.rot || 0, wr = r * (o.width ?? .075);
    ctx.beginPath();
    for (let i = 0; i < n; i++) {
      const a = rot + i / n * TAU, L = r * (o.even ? 1 : .72 + .28 * hash(i * 7.7 + (o.seed || 1)));
      const cx = Math.cos(a), sy = Math.sin(a), px = -sy * wr, py = cx * wr;
      ctx.moveTo(x + px * .6, y + py * .6); ctx.lineTo(x + cx * L + px, y + sy * L + py);
      ctx.arc(x + cx * L, y + sy * L, wr, a + Math.PI / 2, a - Math.PI / 2, true);
      ctx.lineTo(x - px * .6, y - py * .6); ctx.closePath();
    }
  }
  // a mono flash frame: the source in inverted (or plain) high-contrast black and white, full frame
  function monoFlash(ctx, src, o = {}) {
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
    ctx.filter = `grayscale(1) contrast(${o.contrast ?? 1.6})${o.invert === false ? '' : ' invert(1)'}`; ctx.drawImage(src, 0, 0); ctx.restore();
  }
  // ---- composable transitions for {type: 'custom', dur, draw: FX.T.<name>(...)} (timeline.js). Each draw gets
  // p 0..1 (the cut at .5) and {a, ao, b, bo: shot canvases, base, over: output, la, lb: looks (focus = subject box), t, A, B}.
  const ctr = (bx, d) => bx ? [bx[0] + bx[2] / 2, bx[1] + bx[3] / 2] : d;
  const both = (c, fnA, fnB) => { c.over.save(); fnA(c.over, c.ao); c.over.restore(); c.over.save(); fnB(c.over, c.bo); c.over.restore(); };
  const lumaC = document.createElement('canvas'); lumaC.width = Math.ceil(W / 4); lumaC.height = Math.ceil(H / 4); const lumaG = lumaC.getContext('2d', SWC);
  const T = {
    // B revealed through a growing shape (spark or circle) centred on A's subject (or a given point)
    iris(o = {}) { return (p, c) => {
      const [cx, cy] = o.at || ctr(c.la.focus, [W / 2, H / 2]), e = easeInOut(p), r = e * Math.hypot(W, H) * .75;
      c.base.drawImage(c.a, 0, 0); c.base.save(); c.base.beginPath();
      if (o.shape === 'spark') sparkPath(c.base, cx, cy, Math.max(1, r), o); else c.base.arc(cx, cy, Math.max(1, r), 0, Math.PI * 2);
      c.base.clip(); c.base.drawImage(c.b, 0, 0); c.base.restore();
      c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; }; },
    // push into A's subject until it fills the frame, then emerge from B's subject (a zoom-through match)
    zoom(o = {}) { return (p, c) => {
      const zin = (img, bx, k) => { const [cx, cy] = ctr(bx, [W / 2, H / 2]), z = 1 + k * (o.depth || 5);
        c.base.setTransform(z, 0, 0, z, cx - cx * z, cy - cy * z); c.base.drawImage(img, 0, 0); c.base.setTransform(1, 0, 0, 1, 0, 0); };
      if (p < .5) zin(c.a, c.la.focus, easeIn(p * 2)); else zin(c.b, c.lb.focus, 1 - easeOut((p - .5) * 2));
      c.over.globalAlpha = Math.abs(p - .5) * 2; c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); c.over.globalAlpha = 1; return p < .5 ? c.la : c.lb; }; },
    // match cut: B is scaled/offset so its subject box starts exactly where A's was, then eases to rest (after the cut).
    // (fix) the centre is lerped (B's subject lands ON A's); the scale is the subject-box ratio (clamped to [1, 1.6]) or,
    // when the move needs room, just enough zoom that the offset never uncovers a frame edge (also capped at 1.6); the
    // translation is clamped to the frame. Only when even 1.6× cannot reach A's spot does B land as close as it can.
    match(o = {}) { return (p, c) => {
      if (p < .5 || !c.la.focus || !c.lb.focus) { c.base.drawImage(p < .5 ? c.a : c.b, 0, 0); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; }
      const SMAX = o.maxScale ?? 1.6, k = 1 - easeOut((p - .5) * 2), A = c.la.focus, B = c.lb.focus, [ax, ay] = ctr(A), [bx, by] = ctr(B);
      const cx = lerp(bx, ax, k), cy = lerp(by, ay, k);
      // the least scale s that lets B's centre b sit at c with B still covering [0, L]: s·b ≥ c and s·(L − b) ≥ L − c
      const room = (cc, bb, L) => Math.max(bb > 1 ? cc / bb : 1, bb < L - 1 ? (L - cc) / (L - bb) : 1);
      const want = 1 + k * (clamp(A[3] / Math.max(1, B[3]), 1 / SMAX, SMAX) - 1);
      const s = clamp(Math.max(1, want, room(cx, bx, W), room(cy, by, H)), 1, SMAX);
      const tx2 = clamp(cx - s * bx, W - W * s, 0), ty2 = clamp(cy - s * by, H - H * s, 0);
      c.base.setTransform(s, 0, 0, s, tx2, ty2); c.base.drawImage(c.b, 0, 0); c.base.setTransform(1, 0, 0, 1, 0, 0);
      c.over.drawImage(c.bo, 0, 0); return c.lb; }; },
    // B pushes A out along dir (±1 horizontal, ±2 vertical) with motion streaks at the seam
    push(o = {}) { return (p, c) => {
      const d = o.dir || 1, e = easeInOut(p), horiz = Math.abs(d) === 1, sg = Math.sign(d), L = horiz ? W : H;
      const off = e * L * sg, ax = horiz ? -off : 0, ay = horiz ? 0 : -off, bx = horiz ? L * sg - off : 0, by = horiz ? 0 : L * sg - off;
      c.base.drawImage(c.a, ax, ay); c.base.drawImage(c.b, bx, by);
      const amp = 90 * Math.sin(p * Math.PI); c.base.globalAlpha = .25;
      for (let i = 1; i <= 3; i++) { c.base.drawImage(c.b, bx - (horiz ? sg * amp * i / 3 : 0), by - (horiz ? 0 : sg * amp * i / 3)); } c.base.globalAlpha = 1;
      both(c, (g, im) => g.drawImage(im, ax, ay), (g, im) => g.drawImage(im, bx, by)); return p < .5 ? c.la : c.lb; }; },
    // xerox threshold: B burns in through A's darkest tones first (a luma key sweeping up the tonal range)
    luma(o = {}) { return (p, c) => {
      c.base.drawImage(c.b, 0, 0); const sm = lumaC, g = lumaG;
      g.globalCompositeOperation = 'copy'; g.drawImage(c.a, 0, 0, sm.width, sm.height); g.globalCompositeOperation = 'source-over';
      const im = g.getImageData(0, 0, sm.width, sm.height), th = easeInOut(p) * 255;
      for (let i = 0; i < im.data.length; i += 4) { const l = .3 * im.data[i] + .59 * im.data[i + 1] + .11 * im.data[i + 2]; im.data[i + 3] = (o.invert ? 255 - l : l) > th ? 255 : 0; }
      g.putImageData(im, 0, 0); c.base.imageSmoothingEnabled = false; c.base.drawImage(sm, 0, 0, W, H); c.base.imageSmoothingEnabled = true;
      c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; }; },
    // label bands: B arrives in n horizontal (or vertical) stripes in a stepped order, one hairline leading each
    bands(o = {}) { return (p, c) => {
      const n = o.n || 6, vert = !!o.vertical; c.base.drawImage(c.a, 0, 0);
      for (let i = 0; i < n; i++) { const d = (o.order === 'random' ? hash2(i, 5) : i / n) * .5, q = clamp((p - d) / .5); if (q <= 0) continue;
        const s = (vert ? W : H) / n, x = vert ? i * s : 0, y = vert ? 0 : i * s, w = vert ? s : W * q, h = vert ? H * q : s;
        c.base.save(); c.base.beginPath(); c.base.rect(x, y, w, h); c.base.clip(); c.base.drawImage(c.b, 0, 0); c.base.restore();
        if (q < 1) { c.over.fillStyle = o.color || INK.accent; if (vert) c.over.fillRect(x, y + h - 2, s, 3); else c.over.fillRect(x + w - 2, y, 3, s); } }
      c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; }; },
    // push through a point of A (o.a, default A's subject centre) and out of a point of B (o.b): pupil → cloud gap
    through(o = {}) { return (p, c) => {
      const [ax, ay] = o.a || ctr(c.la.focus, [W / 2, H / 2]), [bx, by] = o.b || ctr(c.lb.focus, [W / 2, H / 2]), z = o.depth ?? 6;
      if (p < .5) { const k = 1 + (z - 1) * easeIn(p * 2); c.base.setTransform(k, 0, 0, k, ax - ax * k, ay - ay * k); c.base.drawImage(c.a, 0, 0); }
      else { const k = 1 + (z - 1) * (1 - easeOut((p - .5) * 2)); c.base.setTransform(k, 0, 0, k, bx - bx * k, by - by * k); c.base.drawImage(c.b, 0, 0); }
      c.base.setTransform(1, 0, 0, 1, 0, 0); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; }; },
    // a whip pan through the cut along o.dir (radians, 0 = right): the frame wraps (a panorama strip) so the slide never
    // uncovers black; the motion smear hides the seam (two passes avoid banding)
    wrap(o = {}) { return (p, c) => {
      const ang = o.dir ?? 0, D = o.dist ?? 700, ux = Math.cos(ang), uy = Math.sin(ang);
      const d = p < .5 ? D * easeIn(p * 2) : -D * (1 - easeOut((p - .5) * 2)), img = p < .5 ? c.a : c.b, ov = p < .5 ? c.ao : c.bo;
      const s = 1 + .06 * Math.sin(p * Math.PI);                                       // a little overscan
      for (const k of [-1, 0, 1]) { c.base.save(); c.base.translate(W / 2 + ux * (d + k * W * s), H / 2 + uy * (d + k * H * s)); c.base.scale(s, s); c.base.translate(-W / 2, -H / 2); c.base.drawImage(img, 0, 0); c.base.restore(); }
      const L = (o.blur ?? 260) * Math.sin(p * Math.PI);
      if (L > 1 && window.CAM) { CAM.smear(c.base, L, ang, 16); CAM.smear(c.base, L / 15, ang, 8); }
      c.over.globalAlpha = Math.abs(p * 2 - 1); c.over.drawImage(ov, ux * d, uy * d); c.over.globalAlpha = 1;
      return p < .5 ? c.la : c.lb; }; },
    // a hard cut at B's t0 (or o.at) whose first o.frames frames show B as an inverted mono flash (counts as a flash: ≤ 3/s)
    flashCut(o = {}) { return (p, c) => {
      const cut = o.at ?? c.B.t0, pre = c.t < cut - 1e-6; c.base.drawImage(pre ? c.a : c.b, 0, 0);
      if (!pre && c.t < cut + (o.frames ?? 1) / FPS - 1e-6) monoFlash(c.over, c.b, { invert: o.invert !== false });
      else c.over.drawImage(pre ? c.ao : c.bo, 0, 0);
      return pre ? c.la : c.lb; }; },
  };
  return { smear, whip, flap, T, sparkPath, monoFlash };
})();

// ---- the transitions registry: name → factory(params, t0) → scene.trans ----
ENGINE.transitions = (() => {
  const custom = (fn, dur) => (p = {}) => ({ type: 'custom', dur: +(p.dur ?? dur), draw: fn(p), preset: true });
  const registry = {
    cut: () => null,
    dither: (p = {}) => ({ type: 'dither', dur: +(p.dur ?? .45) }),
    flap: (p = {}) => ({ type: 'flap', dur: +(p.dur ?? .3), cols: p.cols, rows: p.rows, color: p.color }),
    smear: (p = {}) => ({ type: 'smear', dur: +(p.dur ?? .3) }),
    whip: (p = {}) => ({ type: 'whip', dur: +(p.dur ?? .3), dir: p.dir ?? 1 }),
    flash: (p = {}) => ({ type: 'flash', dur: +(p.dur ?? .3) }),
    iris: custom(FX.T.iris, .5), zoom: custom(FX.T.zoom, .4), match: custom(FX.T.match, .5), push: custom(FX.T.push, .5),
    luma: custom(FX.T.luma, .44), bands: custom(FX.T.bands, .5), through: custom(FX.T.through, .3), wrap: custom(FX.T.wrap, .3),
    flashcut: custom(FX.T.flashCut, .3),
  };
  const alias = { dissolve: 'dither', crossfade: 'dither', 'flash-cut': 'flashcut', flash_cut: 'flashcut', 'whip-wrap': 'wrap', whipwrap: 'wrap',
    'push-through': 'through', 'zoom-through': 'through', 'split-flap': 'flap', 'hard': 'cut', 'none': 'cut' };
  // free text (a storyboard's prose transition) → a registry name
  const fromProse = s => {
    const d = String(s).toLowerCase();
    if (/flash[ -]?cut|invert/.test(d)) return 'flashcut';
    if (/dither|dissolve|crossfade|cross-fade/.test(d)) return 'dither';
    if (/flap/.test(d)) return 'flap';
    if (/smear|scan|xerox/.test(d)) return 'smear';
    if (/match/.test(d)) return 'match';
    if (/iris|spark/.test(d)) return 'iris';
    if (/through|into the|push into/.test(d)) return 'through';
    if (/zoom/.test(d)) return 'zoom';
    if (/whip/.test(d)) return 'whip';
    if (/luma|burn|threshold/.test(d)) return 'luma';
    if (/band|stripe|barcode|wipe/.test(d)) return 'bands';
    if (/push|slide/.test(d)) return 'push';
    if (/flash/.test(d)) return 'flash';
    return 'cut';
  };
  const warned = new Set();
  function make(spec, t0) {
    if (spec == null || spec === '' || spec === false) return null;
    let name, params = {};
    if (typeof spec === 'string') { const k = spec.trim().toLowerCase(); name = registry[k] ? k : alias[k] || fromProse(k); }
    else if (typeof spec === 'object') { params = spec; const k = String(spec.preset || spec.type || spec.kind || 'cut').toLowerCase(); name = registry[k] ? k : alias[k] || (k === 'custom' ? 'custom' : fromProse(k)); }
    else return null;
    if (name === 'custom') return typeof params.draw === 'function' ? { type: 'custom', dur: +(params.dur ?? .5), draw: params.draw } : null;
    const f = registry[name];
    if (!f) { if (!warned.has(name)) { warned.add(name); console.warn(`[engine] unknown transition '${name}' — hard cut`); } return null; }
    const tr = f(params, t0);
    if (tr && !(tr.dur > 0)) tr.dur = .3;
    return tr;
  }
  function register(name, factory) { if (typeof factory !== 'function') throw new Error('ENGINE.transitions.register: factory must be a function'); registry[String(name).toLowerCase()] = factory; }
  function set(sc, spec) { const s = typeof sc === 'string' ? (ENGINE.scenes || []).find(x => x.name === sc) : sc; if (!s) return null; s.trans = make(spec, s.t0); return s.trans; }
  return { registry, register, make, set, fromProse };
})();
