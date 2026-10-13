// glass.js — liquid glass that bends real light over the footage. Loaded by the engine page on every project; it costs
// nothing until a scene draws a glass shape (GLASS.used() stays false and post.js skips the glass pass).
//
// How it works. A scene draws glass SHAPES into the per-frame GLASS FIELD — three small software-backed 2D canvases
// (W/4 × H/4, opaque black, wiped by GLASS.begin(t) at the start of every frame from timeline.js, so a frame never sees
// another frame's glass). Each shape paints its coverage and its optical parameters into the colour channels:
//   A = coverage · frost · refract     B = dispersion · tint · presence     C = ripple · specular · bevel
// At the print pass (post.js) GLASS.field() blurs every channel in float (three box passes ≈ a Gaussian of σ = soft):
// the blurred coverage is the SMOOTH FIELD (shapes that come within ~1.4σ of each other sum past the threshold and
// merge like liquid — metaballs — and split again when they part), the blurred parameters divided by the blurred
// coverage give each pixel the parameters of the shape(s) it belongs to (blended where shapes merge). Its gradient is
// the surface slope. post.js then thresholds the field at ½ (the silhouette, antialiased from the gradient), builds a
// height field (a rounded bevel of width `bevel` at the rim + optional analytic domes for blobs and lenses), and bends
// the footage behind through it with Snell's law — R, G and B with slightly different indices, so chromatic
// aberration appears only where the glass bends light — with a frosted blur, Fresnel reflection, a soft specular from a
// slowly moving light, a faint inner shadow and a soft contact shadow. Overlay type composites after, crisp. Only the
// 32-px tiles that hold glass (or its shadow) run the glass shader. Because this file is loaded, 2.5D plates are handed
// to the base through a CPU readback (plate3d.js), so type drawn on the base — which the glass refracts — stays
// history-independent.
// API: GLASS.pane(x, y, w, h, r, o) · capsule · blob(cx, cy, r, o) · lens(cx, cy, r, {mag}) · path(build, o) ·
// text(str, x, y, cssFont, o) · set({soft, ior, thick, gap, shadow, env, rim}) · light(t, {angle, elev, drift}) ·
// GLASS.look.{clear, frost, deep, smoke, milk, liquid, crystal} (spread into o).
// Port notes: unchanged maths; rounded rects fall back to a local path when ctx.roundRect is missing (was GFX.roundRect).
'use strict';
const GLASS = (() => {
  const S = 4, FW = Math.ceil(W / S), FH = Math.ceil(H / S), N = FW * FH;
  const SW = { willReadFrequently: true };                      // software-backed: history-independent (timeline.js note)
  const cvs = [0, 1, 2].map(() => { const c = document.createElement('canvas'); c.width = FW; c.height = FH; return c; });
  const CX = cvs.map(c => c.getContext('2d', SW));
  // channel ranges: the 8-bit field stores value / range
  const RANGE = { frost: 48, refract: 2, spec: 2, bevel: 96, tint: .3 };
  // per-shape defaults: clear glass that lenses at the rim (a "clear" UI material)
  const DEF = { frost: 0, refract: 1, disp: .4, tint: 0, alpha: 1, ripple: 0, spec: 1, bevel: 24 };
  // per-frame globals: soft (σ px of the liquid field: merge reach ≈ 1.4σ), ior, thick (bevel height / bevel width),
  // gap (px the glass floats above the image: more = stronger, inverting lensing), shadow (contact-shadow depth),
  // shOff (shadow offset px along the light), env (Fresnel reflection of the surroundings), rim (rim-light strength)
  const GDEF = { soft: 12, ior: 1.5, thick: 1, gap: 18, shadow: .14, shOff: 14, env: 1, rim: 1, dispK: .045, rimBlur: 1 };
  let used = false, box = null, domes = [], G = Object.assign({}, GDEF), L = [0, 0, 1], LI = 1, T = 0;
  const vals = {};                                               // per channel: the set of values drawn this frame
  const channels = ['frost', 'refract', 'disp', 'tint', 'alpha', 'ripple', 'spec', 'bevel'];

  function wipe(c) {
    if (c.reset) c.reset(); else { c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = 1; c.globalCompositeOperation = 'source-over'; c.filter = 'none'; }
    c.fillStyle = '#000'; c.fillRect(0, 0, FW, FH);
  }
  // a new frame: empty field, default globals, the default light for t
  function begin(t) {
    T = t; CX.forEach(wipe); used = false; box = null; domes = []; G = Object.assign({}, GDEF);
    channels.forEach(k => vals[k] = new Set()); light(t);
  }
  function set(o = {}) { Object.assign(G, o); return G; }
  // the light: a direction toward the light (x right, y down, z toward the viewer). By default it comes from the upper
  // left and sways ±0.5 rad over 41 s (slow, never on the beat). o.angle (radians, 0 = from the right, -π/2 = from above),
  // o.elev (0 grazing … π/2 overhead, default .62), o.drift (sway, radians), o.period (s), o.spin (rad/s), o.intensity.
  function light(t, o = {}) {
    const a = (o.angle ?? -2.25) + (o.drift ?? .5) * Math.sin(TAU * t / (o.period ?? 41)) + (o.spin ?? 0) * t;
    const e = o.elev ?? .62, c = Math.cos(e);
    L = [Math.cos(a) * c, Math.sin(a) * c, Math.sin(e)]; LI = o.intensity ?? 1; return L;
  }
  const byte = v => Math.round(clamp(v) * 255);
  const grow = b => { if (!b) { box = [0, 0, W, H]; return; } const [x, y, w, h] = b;
    box = box ? [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x + w), Math.max(box[3], y + h)] : [x, y, x + w, y + h]; };
  // the core: paint a shape (build(ctx) adds a path in full-res px; or fills it itself and returns true) with its params.
  // o.box = [x, y, w, h] (full-res px) bounds the work; without it the whole frame is processed.
  function shape(build, o = {}) {
    const p = Object.assign({}, DEF, o); if (o.presence != null) p.alpha = o.presence; if (p.alpha <= 0) return;
    channels.forEach(k => vals[k].add(p[k]));
    const cols = [[1, p.frost / RANGE.frost, p.refract / RANGE.refract], [p.disp, .5 + p.tint / RANGE.tint, p.alpha],
      [p.ripple, p.spec / RANGE.spec, p.bevel / RANGE.bevel]];
    CX.forEach((c, k) => {
      c.save(); c.setTransform(1 / S, 0, 0, 1 / S, 0, 0);
      c.fillStyle = `rgb(${cols[k].map(byte).join(',')})`; c.beginPath();
      if (!build(c)) c.fill();
      c.restore();
    });
    used = true; grow(o.box);
  }
  const rrPath = (c, x, y, w, h, r) => { c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };
  const rrect = (c, x, y, w, h, r) => { r = Math.max(0, Math.min(r, w / 2, h / 2)); c.roundRect ? c.roundRect(x, y, w, h, r) : rrPath(c, x, y, w, h, r); };
  const rotAbout = (c, cx, cy, a) => { if (a) { c.translate(cx, cy); c.rotate(a); c.translate(-cx, -cy); } };
  const rotBox = (x, y, w, h, a) => { if (!a) return [x, y, w, h]; const cx = x + w / 2, cy = y + h / 2, R = Math.hypot(w, h) / 2; return [cx - R, cy - R, 2 * R, 2 * R]; };
  // ---- shapes ----
  // a rounded-rect pane (a UI card). o.rot rotates it about its centre.
  function pane(x, y, w, h, r = 28, o = {}) {
    shape(c => { rotAbout(c, x + w / 2, y + h / 2, o.rot); rrect(c, x, y, w, h, r); }, Object.assign({}, o, { box: o.box || rotBox(x, y, w, h, o.rot) }));
  }
  // a capsule (pill): a pane with fully round ends
  function capsule(x, y, w, h, o = {}) { pane(x, y, w, h, Math.min(w, h) / 2, o); }
  // a liquid droplet: a disc (o.sx/o.sy squash, o.rot) with a soft dome (o.dome 0..1 of its radius, default .25)
  // that sums with other blobs' domes — two blobs that approach merge into one body and split again.
  function blob(cx, cy, r, o = {}) {
    const sx = o.sx ?? 1, sy = o.sy ?? 1, a = o.presence ?? o.alpha ?? 1; if (a <= 0 || r <= 0) return;
    shape(c => { c.ellipse(cx, cy, r * sx, r * sy, o.rot || 0, 0, TAU); }, Object.assign({ bevel: Math.min(40, r * .5) }, o, { box: [cx - r * Math.max(sx, sy), cy - r * Math.max(sx, sy), 2 * r * Math.max(sx, sy), 2 * r * Math.max(sx, sy)] }));
    const d = o.dome ?? .25; if (d > 0 && domes.length < 16) domes.push([cx, cy, r * Math.sqrt(sx * sy), d * r * a, 0]);
  }
  // a magnifying lens: a clear disc with a paraboloid dome giving o.mag× at its centre (default 1.5) and a crisp rim
  function lens(cx, cy, r, o = {}) {
    const a = o.presence ?? o.alpha ?? 1; if (a <= 0 || r <= 0) return;
    shape(c => { c.arc(cx, cy, r, 0, TAU); }, Object.assign({ bevel: Math.min(22, r * .15), disp: .4, spec: 1.1 }, o, { box: [cx - r, cy - r, 2 * r, 2 * r] }));
    // a thin lens floating gap = 4r above the image: a paraboloid of sag A shifts the ray by ≈ (1 - 1/n)·(2A·ρ/r²)·gap at
    // radius ρ, i.e. a uniform magnification M when (1 - 1/n)·2A·gap/r² = 1 - 1/M
    const mag = Math.max(1.001, o.mag ?? 1.5), n = G.ior, k = 1 - 1 / mag, gap = 4 * r, A = k * r * r / (2 * (1 - 1 / n) * gap);
    if (domes.length < 16) domes.push([cx, cy, r, A, gap * a]);
  }
  // free-form glass: build(ctx) adds any path in full-res px (rings, waveforms) or fills itself (text) and returns true
  function path(build, o = {}) { shape(build, o); }
  // glass type: str in the CSS font fnt (strokes must be ≳ 2·soft px thick to survive the field — heavy weights, big sizes;
  // GLASS.set({soft: 6–8}) for type). o.align, o.baseline, o.tracking (px).
  function text(str, x, y, fnt, o = {}) {
    const c0 = CX[0]; c0.save(); c0.font = fnt; if (o.tracking) c0.letterSpacing = `${o.tracking}px`;
    const m = c0.measureText(str), size = parseFloat((fnt.match(/(\d+(\.\d+)?)px/) || [0, 100])[1]); c0.restore();
    const w = m.width, x0 = o.align === 'center' ? x - w / 2 : o.align === 'right' ? x - w : x;
    shape(c => { c.font = fnt; c.textBaseline = o.baseline || 'alphabetic'; c.textAlign = o.align || 'left';
      if (o.tracking) c.letterSpacing = `${o.tracking}px`; c.fillText(str, x, y); return true; },
      Object.assign({ bevel: 10 }, o, { box: o.box || [x0 - 8, y - size * 1.1, w + 16, size * 1.5] }));
  }

  // ---- the field (called by post.js once per frame when used()) ----
  const PL = channels.length + 1;                               // coverage + 8 parameter planes
  let planes = [], tmp = null, wideC = null, F1 = new Float32Array(N * 4), F2 = new Float32Array(N * 4), F3 = new Float32Array(N * 4);
  function boxesFor(sigma) {                                     // three box widths whose convolution ≈ Gaussian(σ)
    const n = 3, wI = Math.sqrt(12 * sigma * sigma / n + 1); let wl = Math.floor(wI); if (wl % 2 === 0) wl--;
    const wu = wl + 2, m = Math.round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4));
    return [0, 1, 2].map(i => ((i < m ? wl : wu) - 1) / 2);
  }
  function blurRows(src, dst, w, h, r) {                         // zero outside the rect (the padded box is wider than 3σ)
    if (r < 1) { dst.set(src.subarray(0, w * h)); return; }
    const inv = 1 / (2 * r + 1);
    for (let y = 0; y < h; y++) { const o = y * w; let acc = 0;
      for (let x = 0; x <= r && x < w; x++) acc += src[o + x];
      for (let x = 0; x < w; x++) { dst[o + x] = acc * inv; const a = x + r + 1, b = x - r; if (a < w) acc += src[o + a]; if (b >= 0) acc -= src[o + b]; } }
  }
  function blurCols(src, dst, w, h, r) {
    if (r < 1) { dst.set(src.subarray(0, w * h)); return; }
    const inv = 1 / (2 * r + 1);
    for (let x = 0; x < w; x++) { let acc = 0;
      for (let y = 0; y <= r && y < h; y++) acc += src[y * w + x];
      for (let y = 0; y < h; y++) { dst[y * w + x] = acc * inv; const a = y + r + 1, b = y - r; if (a < h) acc += src[a * w + x]; if (b >= 0) acc -= src[b * w + x]; } }
  }
  function gauss(p, w, h, rs) { for (const r of rs) { blurRows(p, tmp, w, h, r); blurCols(tmp, p, w, h, r); } }
  function field() {
    // the height field reads the inside distance from a blur wide enough for the widest bevel drawn this frame (σh ≥
    // bevel / 3.2, else the distance saturates inside the bevel and the rim creases); the silhouette stays on σ = soft
    const soft = Math.max(1, G.soft), sigHpx = Math.max(soft, Math.max(0, ...vals.bevel) / 3.2), wide = sigHpx > soft * 1.05;
    const sig = soft / S, rs = boxesFor(sig), pad = Math.ceil(3.2 * sigHpx / S + (G.shOff + 8) / S) + 2;
    const bx = box || [0, 0, W, H];
    const x0 = clamp(Math.floor(bx[0] / S) - pad, 0, FW), y0 = clamp(Math.floor(bx[1] / S) - pad, 0, FH);
    const x1 = clamp(Math.ceil(bx[2] / S) + pad, 0, FW), y1 = clamp(Math.ceil(bx[3] / S) + pad, 0, FH);
    const w = x1 - x0, h = y1 - y0, n = w * h;
    F1.fill(0); F2.fill(0); F3.fill(0);
    if (w <= 2 || h <= 2) return null;
    if (!tmp || tmp.length < n) { tmp = new Float32Array(n); planes = Array.from({ length: PL }, () => new Float32Array(n)); wideC = new Float32Array(n); }
    const img = CX.map(c => c.getImageData(x0, y0, w, h).data);
    if (wide) { const D = img[0]; for (let i = 0; i < n; i++) wideC[i] = D[i * 4] / 255; gauss(wideC, w, h, boxesFor(sigHpx / S)); }
    // planes: 0 coverage, then the parameters premultiplied by coverage (so blur(P)/blur(C) = the shape's value)
    const src = [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [2, 0], [2, 1], [2, 2]];   // [canvas, channel] per plane
    const constant = {}; channels.forEach(k => { if (vals[k].size === 1) constant[k] = [...vals[k]][0]; });
    for (let k = 0; k < PL; k++) {
      if (k > 0 && constant[channels[k - 1]] !== undefined) continue;          // one value this frame: no blur needed
      const P = planes[k], D = img[src[k][0]], ch = src[k][1];
      for (let i = 0; i < n; i++) P[i] = D[i * 4 + ch] / 255;
      gauss(P, w, h, rs);
    }
    // pack: F1 = [field f, ∂h/∂x, ∂h/∂y, presence] · F2 = [frost px, refract, disp, tint] · F3 = [ripple, spec, bevel px, h]
    // (h = the height-field blur: f itself, or the wide blur when a bevel needs it; gradients per full-res px)
    const C = planes[0], Hc = wide ? wideC : planes[0], sc = [RANGE.frost, RANGE.refract, 1, RANGE.tint, 1, 1, RANGE.spec, RANGE.bevel], off = [0, 0, 0, -.5, 0, 0, 0, 0];
    const Pk = channels.map((k, i) => constant[k] === undefined ? planes[i + 1] : null), Ck = channels.map(k => constant[k] ?? 0);
    const par = (k, i, ic) => Pk[k] ? (Pk[k][i] * ic + off[k]) * sc[k] : Ck[k];
    for (let yy = 0; yy < h; yy++) {
      const row = (yy + y0) * FW + x0;
      for (let xx = 0; xx < w; xx++) {
        const i = yy * w + xx, c = C[i], j = (row + xx) * 4;
        F1[j] = c; F1[j + 1] = ((xx + 1 < w ? Hc[i + 1] : 0) - (xx > 0 ? Hc[i - 1] : 0)) / (2 * S);
        F1[j + 2] = ((yy + 1 < h ? Hc[i + w] : 0) - (yy > 0 ? Hc[i - w] : 0)) / (2 * S);
        if (c < 1e-3) continue;
        F3[j + 3] = Hc[i];
        const ic = 1 / c;
        F1[j + 3] = par(4, i, ic);
        F2[j] = par(0, i, ic); F2[j + 1] = par(1, i, ic); F2[j + 2] = par(2, i, ic); F2[j + 3] = par(3, i, ic);
        F3[j] = par(5, i, ic); F3[j + 1] = par(6, i, ic); F3[j + 2] = par(7, i, ic);
      }
    }
    const dm = new Float32Array(16 * 4), dk = new Float32Array(16); domes.forEach((d, i) => { dm.set(d.slice(0, 4), i * 4); dk[i] = d[4]; });
    return { F1, F2, F3, fw: FW, fh: FH, box: [x0 * S, y0 * S, x1 * S, y1 * S], domes: dm, kinds: dk, nd: domes.length,
      sig: soft, sigH: sigHpx, G, L, LI, t: T, tiles: tiles(C, x0, y0, w, h) };
  }
  // the glass pass only shades TILES (32 px) where the field (or the tail that carries the contact shadow) is non-zero:
  // SwiftShader pays for a big shader's arithmetic on every pixel it runs on, taken branch or not. Returned as triangles
  // (clip space, top-down rows) for runs of tiles along each tile row.
  const TS = 32, TF = TS / S;
  function tiles(C, x0, y0, w, h) {
    const tx0 = Math.floor(x0 / TF), ty0 = Math.floor(y0 / TF), tx1 = Math.ceil((x0 + w) / TF), ty1 = Math.ceil((y0 + h) / TF), v = [];
    const X = px => px / W * 2 - 1, Y = py => py / H * 2 - 1;
    for (let ty = ty0; ty < ty1; ty++) {
      let run = -1;
      for (let tx = tx0; tx <= tx1; tx++) {
        let on = false;
        if (tx < tx1) for (let yy = Math.max(ty * TF - y0, 0); yy < Math.min((ty + 1) * TF - y0, h) && !on; yy++)
          for (let xx = Math.max(tx * TF - x0, 0); xx < Math.min((tx + 1) * TF - x0, w); xx++) if (C[yy * w + xx] > .002) { on = true; break; }
        if (on && run < 0) run = tx;
        if (!on && run >= 0) { const a = X(run * TS), b = X(Math.min(tx * TS, W)), c = Y(ty * TS), d = Y(Math.min((ty + 1) * TS, H));
          v.push(a, c, b, c, a, d, a, d, b, c, b, d); run = -1; }
      }
    }
    return new Float32Array(v);
  }
  const api = { begin, set, light, shape, pane, capsule, blob, lens, path, text, field, used: () => used,
    // look recipes (spread into opts): clear (clear UI glass), frost (the frosted card), smoke/milk (a faint neutral tint),
    // liquid (a moving surface), crystal (strong lensing + dispersion)
    look: { clear: {}, frost: { frost: 14, refract: .8, disp: .25 }, deep: { frost: 26, refract: .7, disp: .2, spec: .8 },
      smoke: { frost: 10, tint: -.08, disp: .25 }, milk: { frost: 18, tint: .07, disp: .2 }, liquid: { ripple: .6, disp: .55 },
      crystal: { refract: 1.5, disp: .9, spec: 1.3 } },
    get canvases() { return cvs; }, S, FW, FH };
  window.GLASS = api;
  return api;
})();
ENGINE.glass = GLASS;
