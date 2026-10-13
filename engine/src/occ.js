// occ.js — rotoscope and depth occlusion: type and graphics that sit BEHIND the subject or between depth planes.
// Loaded by the engine page; media.js / timeline.js call into it. WITHOUT matte/depth data it is a no-op: m.matte() and
// m.depth() return null, OCC.behind/between draw the layer uncut, OCC.over/contours/outline draw nothing.
//
// Every MEDIA draw result (drawPlate, drawClip, drawShot) gains
//   await m.matte() → a canvas whose ALPHA is the subject: the rotoscope matte (plates: PLATES[name].matte as a path, or
//                     assets/plates/<name>.matte.png when matte is true; clips: <dir>/matte/fNNNNN.png when CLIPS[name].matte)
//                     drawn through the SAME camera as the footage — 2.5D parallax, cover framing and any screen
//                     transform on the base context (CAM.shot) included; null when the media has no matte
//   await m.depth() → a canvas with depth in R, G, B (near = bright), drawn through the same camera; null without depth.
//                     Depth is used only when it is Depth-Anything-V2-Small derived (ENGINE.depthOK: a depth_model naming
//                     any other model — e.g. the CC-BY-NC Large/Base weights — is ignored).
// Both are half resolution (W/2 × H/2; draw them with drawImage(c, 0, 0, W, H)); computed once per frame per shot.
//
//   OCC.mask(m, {mode: 'auto'|'matte'|'depth', near, soft, feather, invert}) → the subject as an alpha canvas: the matte,
//        or (mode 'depth', or 'auto' without a matte) a depth key: alpha = smoothstep(near − soft, near + soft, depth)
//   OCC.behind(o, m, draw, opts)   draw(g) paints a layer; the subject is cut out of it; the rest composites into o.
//        The base under the subject shows through, so the layer reads as sitting behind them
//   OCC.between(o, m, draw, {plane, soft})   the layer at a depth plane: everything nearer than `plane` covers it
//   OCC.over(o, m, draw, opts)     the reverse: the layer only ON the subject (a label printed on a body)
//   OCC.depthMask(m, near, soft)   the depth key alone
//   OCC.contours(o, m, {levels, color, lw, alpha, step, reveal})   iso-depth lines of the real depth map (topography)
//   OCC.outline(o, m, {color, lw, alpha, dash, level})              the matte's edge as a CV segmentation outline
// Rule: place a block so it TUCKS (an edge, a word end) behind the subject — never so most of it disappears.
// THE TUCK RULE, enforced ("occlusion tucks an edge, never a glyph"; Studio E2E s005: a line passing behind a near laptop
// lost "Do" of "Don't"): OCC.behind(o, m, draw, {glyphs: {region, tuck}}) — every lyric mode passes it (devices/type.js) —
// reads the layer's ink as glyphs (connected ink at half resolution: a letter, or letters that touch) set in rows, and
// measures the share of each glyph's ink the occluder would hide. A glyph at a row's END (the block's edge; in a masthead
// or a stack, the word's end) may tuck up to `tuck` (.4) of its ink, easing back to whole between .6·tuck and tuck; every
// other glyph the occluder reaches is drawn whole (the occluder is lifted off its box for that frame). Ink that is
// several letters (letters that touch) tucks only its outer letter's worth (a band .8 × the row's height on the end
// side); an occluder reaching past that band lifts it whole. Pure per frame. A lifted glyph sits ON the subject:
// {glyphs: {over: g => …}} draws the layer again in the ink that reads on the subject, and the lifted parts take that
// (a split along the matte — ink.js's advice; devices/type.js passes it); OCC.ground(b, mk, box, on) → the base's
// luminance under a box on (or off) the subject, which those inks are picked from.
// OCC.guarded() → this frame's record {glyphs (reached), kept (drawn whole), eased, tucked, cover (the largest share of
// an end letter's ink left hidden: < tuck)} or null; the default renderer copies it into DEV_FRAME.occ.
// Port notes: matte/depth paths may be given in PLATES/CLIPS metadata; the depth licence rule is enforced here; a DECLARED
// matte/depth file that does not load is reported (ENGINE.noteMissing → ENGINE.missingMedia), never silently skipped.
'use strict';
const OCC = (() => {
  const SW = { willReadFrequently: true }, HW = W >> 1, HH = H >> 1;
  // ---- a per-frame pool of software canvases (cleared on hand-out; OCC.begin(t) rewinds it every frame) ----
  const pool = []; let used = 0, GUARD = null;
  function begin() { used = 0; GUARD = null; }
  function canvas(w = W, h = H) {
    let c = pool[used]; if (!c) { c = document.createElement('canvas'); c.width = w; c.height = h; pool.push(c); }
    used++;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const g = c.getContext('2d', SW);
    if (g.reset) g.reset(); else { g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none'; }
    g.clearRect(0, 0, w, h); return c;
  }
  const ctx2 = c => c.getContext('2d', SW);
  // ---- sources: a matte or depth image normalised to an opaque grey canvas (alpha mattes read their alpha, grey ones
  // their value), cached with a small LRU (clip frames change every frame) ----
  const SRC = new Map(), MAXSRC = 40;
  function normalize(im) {
    const c = document.createElement('canvas'); c.width = im.naturalWidth; c.height = im.naturalHeight;
    const g = c.getContext('2d', SW); g.drawImage(im, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height), p = d.data;
    let alpha = false; for (let i = 3; i < p.length; i += 4 * 97) if (p[i] < 250) { alpha = true; break; }
    for (let i = 0; i < p.length; i += 4) { const v = alpha ? p[i + 3] : (p[i] * 54 + p[i + 1] * 183 + p[i + 2] * 19) >> 8; p[i] = p[i + 1] = p[i + 2] = v; p[i + 3] = 255; }
    g.putImageData(d, 0, 0); c.naturalWidth = c.width; c.naturalHeight = c.height; c.alphaMatte = alpha; return c;
  }
  function load(src) {
    if (SRC.has(src)) { const v = SRC.get(src); SRC.delete(src); SRC.set(src, v); return v; }
    const pr = new Promise(res => { const im = new Image(); im.onload = () => { try { res(normalize(im)); } catch (e) { res(null); } }; im.onerror = () => res(null); im.src = src; });
    SRC.set(src, pr); while (SRC.size > MAXSRC) SRC.delete(SRC.keys().next().value);
    return pr;
  }
  const metaOf = info => info.kind === 'plate' ? ((window.PLATES || {})[info.name] || {}) : ((window.CLIPS || {})[info.name] || {});
  const hasMatte = info => !!metaOf(info).matte;
  const hasDepth = info => (info.kind === 'plate' ? !!info.dep : !!metaOf(info).depth) && ENGINE.depthOK(metaOf(info));
  const mattePath = info => { const v = metaOf(info).matte; return typeof v === 'string' ? v : `assets/plates/${info.name}.matte.png`; };
  const pad5 = i => String(i).padStart(5, '0');
  // draw an aux image (matte / depth) exactly as the footage was drawn, into a half-res canvas
  function render(info, src, dep) {
    const c = canvas(HW, HH), g = ctx2(c), x = info.xf;
    g.setTransform(.5 * x.a, .5 * x.b, .5 * x.c, .5 * x.d, .5 * x.e, .5 * x.f);
    if (info.kind === 'plate' && info.deep) PLATE3D.draw(g, src, dep, Object.assign({}, info.cam, { aux: true, res: .5 })); else cover(g, src, info.cam);
    g.setTransform(1, 0, 0, 1, 0, 0); return c;
  }
  // called by media.js for every draw (when this file is loaded)
  function attach(res, info) {
    res.occ = info;
    res.matte = async () => {
      if (res._matte !== undefined) return res._matte;
      if (!hasMatte(info)) return res._matte = null;
      const path = info.kind === 'plate' ? mattePath(info) : `${info.dir}/matte/f${pad5(info.idx)}.png`, src = await load(path);
      if (!src) { if (ENGINE.noteMissing) ENGINE.noteMissing(path, 'declared matte missing'); return res._matte = null; }
      const c = render(info, src, info.dep), g = ctx2(c), d = g.getImageData(0, 0, HW, HH), p = d.data;
      for (let i = 0; i < p.length; i += 4) { p[i + 3] = (p[i] * p[i + 3] + 127) / 255; p[i] = p[i + 1] = p[i + 2] = 0; }
      g.putImageData(d, 0, 0); c.kind = 'matte'; return res._matte = c;
    };
    res.depth = async () => {
      if (res._depth !== undefined) return res._depth;
      if (!hasDepth(info)) return res._depth = null;
      const path = info.kind === 'plate' ? null : `${info.dir}/depth/f${pad5(info.idx)}.png`, src = info.kind === 'plate' ? info.dep : await load(path);
      if (!src) { if (path && ENGINE.noteMissing) ENGINE.noteMissing(path, 'declared depth missing'); return res._depth = null; }
      const c = render(info, src, info.kind === 'plate' ? info.dep : null); c.kind = 'depth'; return res._depth = c;
    };
    return res;
  }
  // ---- masks ----
  const sstep = (a, b, x) => { const k = clamp((x - a) / (b - a)); return k * k * (3 - 2 * k); };
  async function depthMask(m, near = .7, soft = .04) {
    if (!m || !m.depth) return null;
    const key = `_dk${near.toFixed(3)}_${soft.toFixed(3)}`; if (m[key] !== undefined) return m[key];
    const d = await m.depth(); if (!d) return m[key] = null;
    const c = canvas(HW, HH), g = ctx2(c), src = ctx2(d).getImageData(0, 0, HW, HH), p = src.data, out = g.createImageData(HW, HH), q = out.data;
    const lut = new Uint8ClampedArray(256); for (let v = 0; v < 256; v++) lut[v] = 255 * sstep(near - soft, near + soft, v / 255);
    for (let i = 0; i < p.length; i += 4) q[i + 3] = p[i + 3] ? lut[p[i]] : 0;
    g.putImageData(out, 0, 0); c.kind = 'depthkey'; return m[key] = c;
  }
  async function mask(m, o = {}) {
    if (!m) return null;
    const mode = o.mode || 'auto';
    let mk = null;
    if (mode !== 'depth' && m.matte) mk = await m.matte();
    if (!mk && mode !== 'matte') mk = await depthMask(m, o.near ?? ((m.meta && m.meta.subject_depth != null ? m.meta.subject_depth : .8) - .1), o.soft ?? .04);
    if (!mk) return null;
    if (o.feather || o.invert) {
      const c = canvas(HW, HH), g = ctx2(c);
      if (o.feather) g.filter = `blur(${Math.max(.5, o.feather / 2)}px)`;
      if (o.invert) { g.fillStyle = '#000'; g.fillRect(0, 0, HW, HH); g.globalCompositeOperation = 'destination-out'; }
      g.drawImage(mk, 0, 0);
      g.filter = 'none'; g.globalCompositeOperation = 'source-over'; return c;
    }
    return mk;
  }
  // ---- THE TUCK RULE: the glyph guard (see the header). L: the layer (W × H), mk: the subject mask (alpha, half res) →
  // the mask with the occluder lifted off every glyph it may not cover (mk itself when nothing changes; never edited)
  const TUCK = .4, INK = 24, BAND = .8;
  let LAB = null;
  function guard(L, mk, o = {}) {
    const tuck = clamp(+(o.tuck ?? TUCK) || 0, 0, .5), r = Array.isArray(o.region) && o.region.length >= 4 && o.region.every(isFinite) ? o.region : null;
    // rows of the block: its box ± a pad (a word entering from below, a breathing coverline, a lower-case masthead's
    // descender under its box: ≥ 30 % of the box height); the full width (a word tracked out on its entrance runs past its box)
    const pad = r ? Math.max(24, .3 * r[3]) : 0;
    const y0 = r ? clamp(Math.floor((r[1] - pad) / 2), 0, HH) : 0, y1 = r ? clamp(Math.ceil((r[1] + r[3] + pad) / 2), 0, HH) : HH, w = HW, h = y1 - y0;
    if (h <= 0) return mk;
    let M = mk; if (mk.width !== HW || mk.height !== HH) { M = canvas(HW, HH); ctx2(M).drawImage(mk, 0, 0, HW, HH); }
    const Ic = canvas(w, h), ig = ctx2(Ic); ig.drawImage(L, 0, y0 * 2, W, h * 2, 0, 0, w, h);
    const ink = ig.getImageData(0, 0, w, h).data, ma = ctx2(M).getImageData(0, y0, w, h).data, n = w * h;
    let hit = false; for (let i = 3; i < ink.length; i += 4) if (ink[i] > INK && ma[i] > 4) { hit = true; break; }
    if (!hit) return mk;
    if (!LAB || LAB.length < n) LAB = new Int32Array(n); else LAB.fill(0, 0, n);
    const lab = LAB, comps = [], st = [], on = q => !lab[q] && ink[q * 4 + 3] > INK;
    for (let i = 0; i < n; i++) {                                  // connected ink (4-neighbours): one glyph each
      if (!on(i)) continue;
      const id = comps.length + 1, c = { x0: w, y0: h, x1: -1, y1: -1, n: 0, ia: 0, hid: 0 }; comps.push(c); lab[i] = id; st.push(i);
      while (st.length) { const q = st.pop(), x = q % w, y = (q / w) | 0, a = ink[q * 4 + 3] / 255;
        c.n++; c.ia += a; c.hid += a * ma[q * 4 + 3] / 255;
        if (x < c.x0) c.x0 = x; if (x > c.x1) c.x1 = x; if (y < c.y0) c.y0 = y; if (y > c.y1) c.y1 = y;
        if (x > 0 && on(q - 1)) { lab[q - 1] = id; st.push(q - 1); } if (x < w - 1 && on(q + 1)) { lab[q + 1] = id; st.push(q + 1); }
        if (y > 0 && on(q - w)) { lab[q - w] = id; st.push(q - w); } if (y < h - 1 && on(q + w)) { lab[q + w] = id; st.push(q + w); } }
    }
    // a glyph is at a row's end when no letter-sized glyph of its row lies further out on that side (punctuation and the
    // dot of an i do not count as "further out"; they are glyphs all the same)
    const ns = comps.map(c => c.n).sort((a, b) => a - b), big = c => c.n >= .25 * (ns[ns.length >> 1] || 1);
    const row = (a, b) => Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0) + 1 > .5 * Math.min(a.y1 - a.y0 + 1, b.y1 - b.y0 + 1);
    const cx = c => (c.x0 + c.x1) / 2, rec = GUARD = GUARD || { glyphs: 0, kept: 0, eased: 0, tucked: 0, cover: 0 }, lift = [], ends = [];
    for (const c of comps) {
      if (!(c.hid > 1e-3)) continue;
      rec.glyphs++;
      const mates = comps.filter(d => d !== c && big(d) && row(c, d));
      c.endL = !mates.some(d => cx(d) < cx(c)); c.endR = !mates.some(d => cx(d) > cx(c));
      if (tuck <= 0 || !(c.endL || c.endR)) { rec.kept++; lift.push([c, 0]); continue; }
      // connected ink is a letter, or letters that touch (tight tracking, "rn", a masthead's one-frame accent block): only
      // its outer letter — a band BAND × the row's height wide on its end side(s) — may tuck; the occluder reaching past it
      // would take a letter
      c.bw = Math.max(2, Math.round(BAND * Math.max(c.y1 - c.y0 + 1, ...mates.map(d => d.y1 - d.y0 + 1)))); c.ib = c.hb = c.ho = 0; ends.push(c);
    }
    if (ends.length) {
      for (let i = 0; i < n; i++) {
        const id = lab[i]; if (!id) continue; const c = comps[id - 1]; if (c.bw === undefined) continue;
        const x = i % w, a = ink[i * 4 + 3] / 255, hm = a * ma[i * 4 + 3] / 255;
        if ((c.endL && x < c.x0 + c.bw) || (c.endR && x > c.x1 - c.bw)) { c.ib += a; c.hb += hm; } else c.ho += hm;
      }
      for (const c of ends) {
        const ib = Math.max(1e-6, c.ib), cov = c.hb / ib, inner = c.ho / ib;
        const k = Math.min(cov <= .6 * tuck ? 1 : cov >= tuck ? 0 : 1 - sstep(.6 * tuck, tuck, cov), 1 - sstep(.01, .05, inner));
        if (k >= 1) { rec.tucked++; rec.cover = Math.max(rec.cover, cov + inner); continue; }
        if (k > 0) rec.eased++; else rec.kept++;
        rec.cover = Math.max(rec.cover, (cov + inner) * k); lift.push([c, k]);
      }
    }
    if (!lift.length) return mk;
    // the lifted share of the subject over each lifted glyph's box (± 1 px): d = mask × (1 − k); the cut is mask − d, exactly
    // (G.lifted keeps d: OCC.behind draws a lifted glyph in the ink that reads ON the subject when it is given one)
    const dl = new Uint8ClampedArray(n);
    for (const [c, k] of lift) {
      const xa = Math.max(0, c.x0 - 1), xb = Math.min(w - 1, c.x1 + 1), ya = Math.max(0, c.y0 - 1), yb = Math.min(h - 1, c.y1 + 1);
      for (let y = ya; y <= yb; y++) for (let x = xa, i = y * w + xa; x <= xb; x++, i++) { const v = ma[i * 4 + 3] * (1 - k); if (v > dl[i]) dl[i] = v; }
    }
    const G = canvas(HW, HH), g = ctx2(G), Dl = canvas(HW, HH), dg = ctx2(Dl), gi = g.createImageData(w, h), di = dg.createImageData(w, h);
    g.drawImage(M, 0, 0);
    for (let i = 0; i < n; i++) { const a = ma[i * 4 + 3], d = dl[i]; gi.data[i * 4 + 3] = a - d; di.data[i * 4 + 3] = d; }
    g.putImageData(gi, 0, y0); dg.putImageData(di, 0, y0);
    G.kind = 'guarded'; G.lifted = Dl; Dl.kind = 'lifted'; return G;
  }
  const guarded = () => GUARD ? Object.assign({}, GUARD, { cover: +GUARD.cover.toFixed(3) }) : null;
  // the base's luminance under a box ON the subject (on: true) or OFF it — what type set behind the subject reads on:
  // {Y (mean relative luminance), min, max, share (of the box on that side)}, or null when that side holds < 3 % of the
  // box. b: the base (context or canvas), mk: the subject mask (OCC.mask), box: [x, y, w, h] screen px
  const lin = v => { v /= 255; return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }, LIN = new Float32Array(256).map((_, i) => lin(i));
  const GB = document.createElement('canvas'), GK = document.createElement('canvas');
  function ground(b, mk, box, on) {
    if (!b || !mk || !Array.isArray(box)) return null;
    const x = clamp(Math.floor(box[0]), 0, W - 1), y = clamp(Math.floor(box[1]), 0, H - 1), x1 = clamp(Math.ceil(box[0] + box[2]), 0, W), y1 = clamp(Math.ceil(box[1] + box[3]), 0, H);
    const w = x1 - x, h = y1 - y; if (!(w >= 2 && h >= 2)) return null;
    const sw = clamp(Math.round(w / 8), 2, 64), sh = clamp(Math.round(h / 8), 2, 64);
    GB.width = sw; GB.height = sh; GK.width = sw; GK.height = sh;                 // (resizing clears them)
    const gb = ctx2(GB), gk = ctx2(GK);
    gb.drawImage(b.canvas || b, x, y, w, h, 0, 0, sw, sh); gk.drawImage(mk, x * mk.width / W, y * mk.height / H, w * mk.width / W, h * mk.height / H, 0, 0, sw, sh);
    const p = gb.getImageData(0, 0, sw, sh).data, q = gk.getImageData(0, 0, sw, sh).data;
    let sw8 = 0, sY = 0, mn = 1, mx = 0;
    for (let i = 0; i < p.length; i += 4) {
      const a = q[i + 3] / 255, wt = on ? a : 1 - a; if (wt < .02) continue;
      const Yv = .2126 * LIN[p[i]] + .7152 * LIN[p[i + 1]] + .0722 * LIN[p[i + 2]]; sY += Yv * wt; sw8 += wt;
      if (wt > .5) { mn = Math.min(mn, Yv); mx = Math.max(mx, Yv); }
    }
    if (sw8 < .03 * sw * sh) return null;
    const Ym = sY / sw8; return { Y: Ym, min: Math.min(mn, Ym), max: Math.max(mx, Ym), share: sw8 / (sw * sh) };
  }
  // ---- layers ----
  async function layer(draw) { const L = canvas(W, H), g = ctx2(L); await draw(g); return L; }
  async function behind(o, m, draw, opts = {}) {
    const L = await layer(draw), mk = await mask(m, opts), gl = opts.glyphs ? (opts.glyphs === true ? {} : opts.glyphs) : null;
    const G = mk && gl ? guard(L, mk, gl) : mk, st = opts.strength ?? 1;
    // a glyph lifted over the subject sits ON it now: drawn from glyphs.over(g) (the layer in the ink that reads on the
    // subject — a split along the matte) when given, else in the layer's own ink
    const over = G && G !== mk && G.lifted && gl && typeof gl.over === 'function' ? gl.over : null;
    if (G) { const g = ctx2(L); g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'destination-out'; g.globalAlpha = st; g.drawImage(over ? mk : G, 0, 0, W, H); g.restore(); }
    if (over) {
      const L2 = await layer(over), g2 = ctx2(L2); g2.save(); g2.setTransform(1, 0, 0, 1, 0, 0); g2.globalCompositeOperation = 'destination-in'; g2.drawImage(G.lifted, 0, 0, W, H); g2.restore();
      const g = ctx2(L); g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = st; g.drawImage(L2, 0, 0); g.restore();
    }
    o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = opts.alpha ?? 1; o.drawImage(L, 0, 0); o.restore();
    return G;
  }
  const between = (o, m, draw, opts = {}) => behind(o, m, draw, Object.assign({}, opts, { mode: 'depth', near: opts.plane ?? opts.near ?? .6, soft: opts.soft ?? .03 }));
  async function over(o, m, draw, opts = {}) {
    const L = await layer(draw), mk = await mask(m, opts);
    if (!mk) return null;
    const g = ctx2(L); g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'destination-in'; g.drawImage(mk, 0, 0, W, H); g.restore();
    o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = opts.alpha ?? 1; o.drawImage(L, 0, 0); o.restore();
    return mk;
  }
  // ---- marching squares on a half-res canvas channel (R for depth, A for masks) at a grid step; segments in screen px ----
  function iso(c, levels, step, chan) {
    const g = ctx2(c), d = g.getImageData(0, 0, c.width, c.height).data, gw = Math.floor((c.width - 1) / step) + 1, gh = Math.floor((c.height - 1) / step) + 1;
    const v = new Float32Array(gw * gh);
    for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) v[j * gw + i] = d[((j * step) * c.width + i * step) * 4 + chan] / 255;
    const sx = W / c.width * step, sy = H / c.height * step, out = levels.map(() => []);
    levels.forEach((L, li) => {
      const segs = out[li];
      for (let j = 0; j < gh - 1; j++) for (let i = 0; i < gw - 1; i++) {
        const a = v[j * gw + i], b = v[j * gw + i + 1], cc = v[(j + 1) * gw + i + 1], dd = v[(j + 1) * gw + i];
        const k = (a > L ? 8 : 0) | (b > L ? 4 : 0) | (cc > L ? 2 : 0) | (dd > L ? 1 : 0); if (k === 0 || k === 15) continue;
        const e = (p, q, x0, y0, x1, y1) => { const u = (L - p) / ((q - p) || 1e-6); return [(x0 + (x1 - x0) * u) * sx, (y0 + (y1 - y0) * u) * sy]; };
        const T = e(a, b, i, j, i + 1, j), R = e(b, cc, i + 1, j, i + 1, j + 1), B = e(dd, cc, i, j + 1, i + 1, j + 1), Lf = e(a, dd, i, j, i, j + 1);
        const S = { 1: [[Lf, B]], 2: [[B, R]], 3: [[Lf, R]], 4: [[T, R]], 5: [[Lf, T], [B, R]], 6: [[T, B]], 7: [[Lf, T]], 8: [[Lf, T]], 9: [[T, B]], 10: [[T, R], [Lf, B]], 11: [[T, R]], 12: [[Lf, R]], 13: [[B, R]], 14: [[Lf, B]] }[k];
        S.forEach(s => segs.push(s));
      }
    });
    return out;
  }
  function stroke(o, segs, opts) {
    o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.strokeStyle = opts.color || '#fff'; o.lineWidth = opts.lw ?? 1; o.globalAlpha = opts.alpha ?? .7;
    if (opts.dash) o.setLineDash(opts.dash);
    const rv = opts.reveal;                                        // optional reveal: only segments inside a circle / below a y
    o.beginPath();
    segs.forEach(([p, q]) => { if (rv && !rv(p[0], p[1])) return; o.moveTo(p[0], p[1]); o.lineTo(q[0], q[1]); });
    o.stroke(); o.restore();
  }
  async function contours(o, m, opts = {}) {
    const d = m && m.depth ? await m.depth() : null; if (!d) return 0;
    const lv = opts.levels || [.15, .25, .35, .45, .55, .65, .75, .85, .95];
    const sets = iso(d, lv, opts.step ?? 3, 0);
    sets.forEach((segs, i) => stroke(o, segs, Object.assign({}, opts, { alpha: (opts.alpha ?? .6) * (opts.fade ? opts.fade(lv[i], i) : 1) })));
    return sets.reduce((a, s) => a + s.length, 0);
  }
  async function outline(o, m, opts = {}) {
    const mk = await mask(m, opts); if (!mk) return 0;
    const [segs] = iso(mk, [opts.level ?? .5], opts.step ?? 2, 3);
    stroke(o, segs, opts); return segs.length;
  }
  return { begin, canvas, load, attach, mask, depthMask, behind, between, over, contours, outline, iso, guard, guarded, ground, TUCK, HW, HH };
})();

window.OCC = OCC; ENGINE.occ = OCC;             // media.js / timeline.js call into window.OCC
