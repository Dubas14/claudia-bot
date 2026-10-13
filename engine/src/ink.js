// ink.js — adaptive ink: type and graphics that adapt to the colour under them, and invert where they cross light/dark.
// Loaded by the engine page; nothing runs until a scene or device calls it.
//
//   AINK.sample(b, box)          the base under a block (b = the base 2D context, box = [x, y, w, h] px): mean relative
//                                luminance Y, its spread, min/max, chroma, hue — from a tiny downsample (cheap)
//   AINK.pick(b, box, {accent})  → {ink, mode: 'solid'|'split', s}: white on dark, near-black on light, the project accent
//                                on dark neutrals when accent is allowed; 'split' when the block crosses light and dark
//   AINK.fill(o, b, box, draw, {mode: 'auto'|'solid'|'split'|'difference'|'mono', ink, accent, th, soft})
//        draws a block whose ink adapts: draw(g, pal) paints it with pal = {ink, accent, dim, dark} (called once per ink).
//        'split'      the block in light ink where the base is dark and dark ink where it is light, cut along the base's
//                     luminance edge (the letters invert as they cross a white garment / a black sea)
//        'difference' a true difference inversion: the letters show the negative of the footage
//        'mono'       a black-and-white inversion: the letters show the inverted luminance
//   AINK.C                       the inks: light '#F5F3EE', dark '#0B0C0E', accent = project look.accent
// All reads use the base canvas as drawn (footage + anything drawn on the base), not the overlay: draw phone UIs and
// screens on the base if type over them must adapt. Lesson: split ink fails over translucent or busy texture (glyphs cut
// mid-word) — prefer one solid ink per block or per word, a split along a rotoscope matte, or a forced ink.
// Port notes: the accent ink follows INK.accent (project look.accent) instead of a fixed orange.
'use strict';
const AINK = (() => {
  const SW = { willReadFrequently: true };
  const C = { light: '#F5F3EE', dark: '#0B0C0E', accent: '#D97757', dimLight: 'rgba(245,243,238,.62)', dimDark: 'rgba(11,12,14,.62)' };
  const sc = document.createElement('canvas'); sc.width = 32; sc.height = 32; const sg = sc.getContext('2d', SW);
  const mc = document.createElement('canvas'); mc.width = 64; mc.height = 64;                       // the split mask's downsample
  const lin = v => { v /= 255; return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
  const LIN = new Float32Array(256).map((_, i) => lin(i));
  const Yhex = h => { const [r, g, b] = rgb(h); return .2126 * lin(r * 255) + .7152 * lin(g * 255) + .0722 * lin(b * 255); };
  const contrast = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  const clip = box => { let [x, y, w, h] = box; x = Math.floor(clamp(x, 0, W - 1)); y = Math.floor(clamp(y, 0, H - 1));
    w = Math.ceil(clamp(box[0] + w, 0, W) - x); h = Math.ceil(clamp(box[1] + h, 0, H) - y); return w >= 1 && h >= 1 ? [x, y, w, h] : null; };
  const baseCanvas = b => b && b.canvas ? b.canvas : b;
  function sample(b, box) {
    const r = clip(box); if (!r) return null; const [x, y, w, h] = r;
    const sw = clamp(Math.round(w / 12), 2, 32), sh = clamp(Math.round(h / 12), 2, 32);
    sg.clearRect(0, 0, sw, sh); sg.drawImage(baseCanvas(b), x, y, w, h, 0, 0, sw, sh);
    const d = sg.getImageData(0, 0, sw, sh).data, n = sw * sh;
    let sY = 0, sY2 = 0, mn = 1, mx = 0, sr = 0, sgc = 0, sb = 0, sch = 0;
    for (let i = 0; i < d.length; i += 4) {
      const Y = .2126 * LIN[d[i]] + .7152 * LIN[d[i + 1]] + .0722 * LIN[d[i + 2]];
      sY += Y; sY2 += Y * Y; mn = Math.min(mn, Y); mx = Math.max(mx, Y); sr += d[i]; sgc += d[i + 1]; sb += d[i + 2];
      sch += (Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2])) / 255;
    }
    const Y = sY / n, sd = Math.sqrt(Math.max(0, sY2 / n - Y * Y)), R = sr / n / 255, G = sgc / n / 255, B = sb / n / 255;
    const mxc = Math.max(R, G, B), mnc = Math.min(R, G, B); let hue = 0;
    if (mxc > mnc) { const dd = mxc - mnc; hue = mxc === R ? ((G - B) / dd) % 6 : mxc === G ? (B - R) / dd + 2 : (R - G) / dd + 4; hue = (hue * 60 + 360) % 360; }
    return { Y, sd, min: mn, max: mx, chroma: sch / n, hue, rgb: [R, G, B] };
  }
  function pick(b, box, o = {}) {
    C.accent = INK.accent || C.accent;
    const s = sample(b, box); if (!s) return { ink: C.light, mode: 'solid', s: null };
    const cl = contrast(Yhex(C.light), s.Y), cd = contrast(Yhex(C.dark), s.Y), ca = contrast(Yhex(C.accent), s.Y);
    if (o.split !== false && s.max - s.min > (o.splitRange ?? .35) && s.sd > (o.splitSd ?? .09)) return { ink: cl >= cd ? C.light : C.dark, mode: 'split', s };
    const warm = s.hue < 50 || s.hue > 330;                         // don't set a warm accent on warm ground (skin, orange props)
    if (o.accent && s.Y < .09 && ca >= 4.5 && !(warm && s.chroma > .12)) return { ink: C.accent, mode: 'solid', s, accent: true, contrast: ca };
    return cl >= cd ? { ink: C.light, mode: 'solid', s, contrast: cl } : { ink: C.dark, mode: 'solid', s, contrast: cd };
  }
  // ---- scratch canvases (per call; OCC's per-frame pool when loaded, else our own pair) ----
  const own = [0, 1, 2].map(() => { const c = document.createElement('canvas'); c.width = W; c.height = H; return c; });
  let ownI = 0;
  const scratch = () => { if (window.OCC) return OCC.canvas(W, H); const c = own[ownI++ % own.length], g = c.getContext('2d', SW);
    if (g.reset) g.reset(); g.clearRect(0, 0, W, H); return c; };
  const pal = ink => ink === C.dark ? { ink: C.dark, accent: C.accent, dim: C.dimDark, dark: true } : { ink, accent: C.accent, dim: C.dimLight, dark: false };
  function fill(o, b, box, draw, opts = {}) {
    let mode = opts.mode || 'auto', p = null;
    if (mode === 'auto' || mode === 'solid') { p = opts.ink ? { ink: opts.ink, mode: 'solid' } : pick(b, box, opts); if (mode === 'auto') mode = p.mode; }
    if (mode === 'solid') { o.save(); draw(o, pal(p.ink)); o.restore(); return p; }
    if (mode === 'difference' || mode === 'mono') { invert(o, b, box, draw, mode === 'mono'); return { mode }; }
    split(o, b, box, draw, opts); return p || { mode: 'split' };
  }
  // light ink over dark base, dark ink over light base, cut along the base's luminance edge (smoothstep th ± soft)
  function split(o, b, box, draw, opts = {}) {
    const r = clip([box[0] - 6, box[1] - 6, box[2] + 12, box[3] + 12]); if (!r) return;
    const [x, y, w, h] = r, th = opts.th ?? .42, soft = opts.soft ?? .06;
    const Lc = scratch(), Kc = scratch(), lg = Lc.getContext('2d', SW), kg = Kc.getContext('2d', SW);
    lg.save(); draw(lg, pal(opts.light || C.light)); lg.restore(); kg.save(); draw(kg, pal(C.dark)); kg.restore();
    // the base's lightness under the box (perceptual, gamma space) → alpha of a mask in the box. Read from a 1/q downsample
    // (o.detail, default 3): the edge follows the light, not the skin's specular speckle; drawn back up with smoothing
    const q = opts.detail ?? 3, sw = Math.max(1, Math.round(w / q)), sh = Math.max(1, Math.round(h / q));
    if (mc.width < sw || mc.height < sh) { mc.width = Math.max(mc.width, sw); mc.height = Math.max(mc.height, sh); }
    const mx = mc.getContext('2d', SW); mx.clearRect(0, 0, mc.width, mc.height); mx.imageSmoothingQuality = 'high'; mx.drawImage(baseCanvas(b), x, y, w, h, 0, 0, sw, sh);
    const src = mx.getImageData(0, 0, sw, sh), p = src.data, lut = new Uint8ClampedArray(256);
    for (let v = 0; v < 256; v++) { const k = clamp((v / 255 - (th - soft)) / (2 * soft)); lut[v] = 255 * k * k * (3 - 2 * k); }
    for (let i = 0; i < p.length; i += 4) { const l = (p[i] * 54 + p[i + 1] * 183 + p[i + 2] * 19) >> 8; p[i + 3] = lut[l]; p[i] = p[i + 1] = p[i + 2] = 0; }
    mx.putImageData(src, 0, 0);
    const Mc = scratch(), mg = Mc.getContext('2d', SW); mg.imageSmoothingQuality = 'high'; mg.drawImage(mc, 0, 0, sw, sh, x, y, w, h);
    kg.globalCompositeOperation = 'destination-in'; kg.drawImage(Mc, 0, 0);          // dark ink only where the base is light
    lg.globalCompositeOperation = 'destination-out'; lg.drawImage(Mc, 0, 0);         // light ink only where it is dark
    o.save(); o.setTransform(1, 0, 0, 1, 0, 0);
    o.drawImage(Lc, x, y, w, h, x, y, w, h); o.drawImage(Kc, x, y, w, h, x, y, w, h); o.restore();
  }
  // the letters as a window onto the inverted footage: colour negative ('difference') or inverted luminance ('mono')
  function invert(o, b, box, draw, mono) {
    const r = clip([box[0] - 6, box[1] - 6, box[2] + 12, box[3] + 12]); if (!r) return;
    const [x, y, w, h] = r, Lc = scratch(), lg = Lc.getContext('2d', SW);
    lg.save(); draw(lg, pal('#ffffff')); lg.restore();
    const Dc = scratch(), dg = Dc.getContext('2d', SW);
    if (mono) dg.filter = 'grayscale(1) contrast(1.15)';
    dg.drawImage(baseCanvas(b), x, y, w, h, x, y, w, h); dg.filter = 'none';
    dg.globalCompositeOperation = 'difference'; dg.fillStyle = '#fff'; dg.fillRect(x, y, w, h);
    dg.globalCompositeOperation = 'destination-in'; dg.drawImage(Lc, 0, 0);
    o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.drawImage(Dc, x, y, w, h, x, y, w, h); o.restore();
  }
  return { C, sample, pick, fill, split, invert, contrast, Yhex };
})();

window.AINK = AINK; ENGINE.ink = AINK;
