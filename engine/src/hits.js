// hits.js — camera and cuts that play the track. Reads window.HITS (analysis/hits.json, via the engine assets); without
// it every move is 0 and every query returns null, so pages render unchanged. The owner's brief for it: editing and camera
// that feel really synced to the beat and the sound effects — cuts and flashes on the beat, in theme, never forced.
//
//   HIT — the sound events as functions of t: last / next / near / snap on kicks, snares, hats, the real hits (impacts),
//         vocal entries, beats and bars; the stem envelopes; the loudness integral (a move whose speed is the music).
//   CAM — camera moves made from them: punch (kicks), shake (the drum envelope), ride (a riser pushing into its hit),
//         impact (the real hits), whip (a cut or a fill); CAM.cam() folds them into the cam object MEDIA takes (image
//         space); CAM.shot / CAM.plate / CAM.clip draw footage through a screen-space camera (the same result for clips and
//         2.5D plates: rotation, shake and motion smear included) and keep m.map / m.box / m.matte / m.depth aligned.
// Everything is a pure function of t (frames render in parallel and out of order): nothing is carried between frames.
// Rules: a move answers a sound you can hear (no punches where the drums are out, no shake in UI shots); hold the camera
// still where the song breathes.
// Port notes: HIT.normalize() accepts both the engine form {kick, kick_s, snare, snare_s, hat, impact[{t,s}], ride[[t0,hit]],
// riser, fill[[t0,t1]], vox_on, env{…}, fps} and the toolkit contract form {kick, snare, hat, hits[{t,score}],
// risers[{t0,t1,land}], fills[{t0,t1}], vocal_entries, env24{…}} (ENGINE.prepareData calls it once at load).
'use strict';
const HIT = (() => {
  const HD = () => window.HITS || {};
  const cache = {};
  // contract form → engine form (idempotent; static data, so this is not frame state)
  function normalize(src) {
    const H = Object.assign({}, src || {}), num = x => (typeof x === 'number' ? x : x && typeof x === 'object' ? +(x.t ?? x.t0 ?? 0) : +x);
    const ts = a => (Array.isArray(a) ? a.map(num).filter(isFinite) : []);
    ['kick', 'snare', 'hat'].forEach(k => {
      if (Array.isArray(H[k]) && H[k].length && typeof H[k][0] === 'object') {
        H[k + '_s'] = H[k + '_s'] || H[k].map(x => x.s ?? x.score ?? 1); H[k] = ts(H[k]); } });
    if (!H.impact && Array.isArray(H.hits)) H.impact = H.hits.map(x => typeof x === 'number' ? { t: x, s: 1 } : { t: +x.t, s: +(x.s ?? x.score ?? 1) });
    if (!H.ride && Array.isArray(H.risers)) H.ride = H.risers.map(r => Array.isArray(r) ? r : [+r.t0, +(r.land ?? r.t1)]);
    if (!H.riser && Array.isArray(H.risers)) H.riser = H.risers.map(r => Array.isArray(r) ? r : [+r.t0, +r.t1]);
    if (Array.isArray(H.fills) && !H.fill) H.fill = H.fills.map(f => Array.isArray(f) ? f : [+f.t0, +f.t1]);
    if (Array.isArray(H.fill)) H.fill = H.fill.map(f => Array.isArray(f) ? f : [+f.t0, +f.t1]);
    if (!H.vox_on && Array.isArray(H.vocal_entries)) H.vox_on = ts(H.vocal_entries);
    if (!H.env && H.env24) { H.env = H.env24; H.fps = H.fps || 24; }
    if (H.env && !H.env.mix) { const ks = Object.keys(H.env).filter(k => Array.isArray(H.env[k]) && H.env[k].length);
      if (ks.length) { const n = Math.max(...ks.map(k => H.env[k].length)); H.env.mix = Array.from({ length: n }, (_, i) => Math.min(1, ks.reduce((a, k) => a + (H.env[k][i] || 0), 0) / Math.sqrt(ks.length))); } }
    H.fps = H.fps || 24; H._normalized = true;
    return H;
  }
  // events of one kind as sorted parallel arrays {t: [...], s: [...]} (strength 0..1)
  function ev(kind) {
    if (cache[kind]) return cache[kind];
    const H = HD(), pairs = [];
    const add = (ts, ss, def = 1) => (ts || []).forEach((x, i) => pairs.push([x, ss ? (ss[i] ?? def) : def]));
    switch (kind) {
      case 'kick': add(H.kick, H.kick_s); break;
      case 'snare': add(H.snare, H.snare_s); break;
      case 'hat': add(H.hat, null, .6); break;
      case 'impact': (H.impact || []).forEach(x => pairs.push([x.t, x.s])); break;
      case 'vox': add(H.vox_on); break;
      case 'beat': add(SONG.beats); break;
      case 'bar': add(SONG.downbeats); break;
      case 'drum': add(H.kick, H.kick_s); add(H.snare, H.snare_s); break;
      default: add(H.kick, H.kick_s); add(H.snare, H.snare_s); (H.impact || []).forEach(x => pairs.push([x.t, Math.max(1, x.s)]));   // 'any'
    }
    pairs.sort((a, b) => a[0] - b[0]);
    const o = { t: pairs.map(p => p[0]), s: pairs.map(p => p[1]) };
    if (kind !== 'beat' && kind !== 'bar' || (SONG.beats && SONG.beats.length)) cache[kind] = o;   // beats exist after boot
    return o;
  }
  const lastIdx = (a, t) => { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] <= t) lo = m + 1; else hi = m; } return lo - 1; };
  // the latest event at or before t: {t, s, i, dt}. o.minS skips weaker events, o.within caps how far back (s)
  function last(t, kind = 'kick', o = {}) {
    const E = ev(kind); let i = lastIdx(E.t, t + 1e-6);
    while (i >= 0 && E.s[i] < (o.minS ?? 0)) i--;
    if (i < 0 || t - E.t[i] > (o.within ?? 1e9)) return null;
    return { t: E.t[i], s: E.s[i], i, dt: t - E.t[i] };
  }
  function next(t, kind = 'kick', o = {}) {
    const E = ev(kind); let i = lastIdx(E.t, t + 1e-6) + 1;
    while (i < E.t.length && E.s[i] < (o.minS ?? 0)) i++;
    if (i >= E.t.length || E.t[i] - t > (o.within ?? 1e9)) return null;
    return { t: E.t[i], s: E.s[i], i, dt: E.t[i] - t };
  }
  // the nearest event within win seconds (either side): {t, s, dt (signed: t − event)}
  function near(t, kind = 'any', win = .12, o = {}) {
    const a = last(t, kind, o), b = next(t, kind, o);
    const da = a ? t - a.t : 1e9, db = b ? b.t - t : 1e9;
    if (Math.min(da, db) > win) return null;
    return da <= db ? { t: a.t, s: a.s, dt: da } : { t: b.t, s: b.s, dt: -db };
  }
  // snap a time (a cut, an animation key) to the nearest hit within win; t itself when none is that close
  const snap = (t, kind = 'any', win = .12, o = {}) => { const n = near(t, kind, win, o); return n ? n.t : t; };
  const between = (a, b, kind = 'kick', o = {}) => { const E = ev(kind), out = [];
    for (let i = Math.max(0, lastIdx(E.t, a - 1e-6)); i < E.t.length && E.t[i] < b; i++) if (E.t[i] >= a && E.s[i] >= (o.minS ?? 0)) out.push({ t: E.t[i], s: E.s[i] }); return out; };
  const count = (a, b, kind = 'kick', o = {}) => between(a, b, kind, o).length;
  // the stem envelopes (24 fps, 0..1): 'mix' | 'drums' | 'bass' | 'other' | 'vocals', linearly interpolated
  function env(t, stem = 'drums') {
    const e = (HD().env || {})[stem]; if (!e || !e.length) return 0;
    const x = t * (HD().fps || 24), i = Math.floor(x), k = x - i;
    return lerp(e[clamp(i, 0, e.length - 1)], e[clamp(i + 1, 0, e.length - 1)], k);
  }
  const envAvg = (t, stem = 'drums', win = .25) => { let s = 0; const n = 6; for (let i = 0; i < n; i++) s += env(t - win * i / (n - 1), stem); return s / n; };
  // the loudness integral ∫ env dt (level·seconds from 0): a camera whose speed is the music's energy
  const cums = {};
  function cum(t, stem = 'mix') {
    const e = (HD().env || {})[stem]; if (!e || !e.length) return t;
    const fr = HD().fps || 24;
    if (!cums[stem]) { const c = new Float64Array(e.length + 1); for (let i = 0; i < e.length; i++) c[i + 1] = c[i] + e[i] / fr; cums[stem] = c; }
    const c = cums[stem], x = clamp(t * fr, 0, e.length), i = Math.min(Math.floor(x), e.length - 1);
    return c[i] + (x - i) * e[i] / fr;
  }
  // progress 0..1 between t0 and t1 that advances with the stem's loudness (+ a floor so quiet stretches still move)
  function progress(t, t0, t1, stem = 'mix', floor = .15) {
    const f = x => cum(x, stem) + floor * x, a = f(t0), b = f(t1);
    return b > a ? clamp((f(clamp(t, t0, t1)) - a) / (b - a)) : seg(t, t0, t1);
  }
  // a generic hit envelope: strength × (attack, then exponential decay) since the last event of a kind
  function pulse(t, kind = 'kick', o = {}) {
    const e = last(t, kind, { minS: o.minS, within: o.within ?? 2 }); if (!e) return 0;
    const atk = o.atk ?? .025, tau = o.tau ?? .12, sh = e.dt < atk ? easeOut(e.dt / atk) : Math.exp(-(e.dt - atk) / tau);
    return (o.useS === false ? 1 : e.s) * sh;
  }
  // risers and the hit each lands on ([t0, hit]); fills (lead-in beats and turnarounds, [t0, t1]); the real hits
  const rides = () => HD().ride || (HD().riser || []).map(([a, b]) => [a, b]);
  function ride(t, o = {}) {
    const rel = o.release ?? .09;
    for (const [a, h] of rides()) if (t >= a && t < h + rel * 6) return { t0: a, hit: h, p: t < h ? (t - a) / Math.max(.05, h - a) : 1, after: Math.max(0, t - h) };
    return null;
  }
  const fills = () => HD().fill || [];
  const inFill = t => fills().find(([a, b]) => t >= a && t < b) || null;
  const impacts = (minS = .5) => (HD().impact || []).filter(x => x.s >= minS);
  return { normalize, ev, last, next, near, snap, between, count, env, envAvg, cum, progress, pulse, rides, ride, fills, inFill, impacts };
})();

const CAM = (() => {
  // smooth deterministic noise (a hashed lattice at f Hz, cosine-interpolated), −1..1
  const noise = (t, f, seed) => { const x = t * f, i = Math.floor(x), k = x - i, u = (1 - Math.cos(k * Math.PI)) / 2;
    return lerp(hash2(i, seed) * 2 - 1, hash2(i + 1, seed) * 2 - 1, u); };
  // PUNCH — a zoom kick on the drums (fraction of zoom): o.amp (.02), o.kind ('kick'), o.minS, o.atk/o.tau (s),
  // o.gate (scale by the drum envelope at the hit; default on), o.every (only every Nth beat's kick, e.g. 2 or 4)
  function punch(t, o = {}) {
    const e = HIT.last(t, o.kind || 'kick', { minS: o.minS ?? 0, within: .8 }); if (!e) return 0;
    if (o.every > 1) { const bi = Math.round(bpOf(e.t)); if (((bi % o.every) + o.every) % o.every !== (o.phase ?? 0)) return 0; }
    const atk = o.atk ?? .03, tau = o.tau ?? .13, sh = e.dt < atk ? easeOut(e.dt / atk) : Math.exp(-(e.dt - atk) / tau);
    const gate = o.gate === false ? 1 : clamp(.35 + HIT.envAvg(e.t + .05, 'drums', .08) * 1.2);
    return (o.amp ?? .02) * lerp(.6, 1, e.s) * sh * gate;
  }
  // SHAKE — handheld energy scaled by the drum envelope (px and rad): o.amp (px, 6), o.rot (rad, .002), o.freq (Hz, 7),
  // o.gamma (envelope curve, 1.6), o.stem ('drums'), o.seed
  function shake(t, o = {}) {
    const k = Math.pow(clamp(HIT.envAvg(t, o.stem || 'drums', .12)), o.gamma ?? 1.6), f = o.freq ?? 7, sd = o.seed ?? 3;
    const a = (o.amp ?? 6) * k;
    return { x: a * noise(t, f, sd), y: a * .8 * noise(t, f * 1.13, sd + 7), r: (o.rot ?? .002) * k * noise(t, f * .7, sd + 13) };
  }
  // RIDE — a push that rides a riser into its hit, then snaps back on the hit (o.release s) or holds (o.hold): zoom add
  function ride(t, o = {}) {
    const r = HIT.ride(t, o); if (!r) return 0;
    const amp = o.amp ?? .06;
    if (t < r.hit) return amp * Math.pow(clamp(r.p), o.curve ?? 2.2);
    return o.hold ? amp : amp * Math.exp(-r.after / (o.release ?? .09));
  }
  // IMPACT — the real hits (HITS.impact filtered to s ≥ o.minS, default .6): a big zoom kick plus a shake burst.
  // Returns {z, x, y, r, s, dt, flash}; flash is true on the hit's first frame (use it only where the idea wants a flash)
  function impact(t, o = {}) {
    const e = HIT.last(t, 'impact', { minS: o.minS ?? .6, within: 2 });
    if (!e) return { z: 0, x: 0, y: 0, r: 0, s: 0, dt: 1e9, flash: false };
    const atk = o.atk ?? .035, tau = o.tau ?? .3, sh = e.dt < atk ? easeOut(e.dt / atk) : Math.exp(-(e.dt - atk) / tau);
    const b = e.s * Math.exp(-e.dt / (o.burst ?? .22)), a = (o.shake ?? 14) * b;
    return { z: (o.amp ?? .06) * e.s * sh, x: a * noise(t, 16, 21), y: a * noise(t, 17.3, 29), r: (o.rot ?? .006) * b * noise(t, 11, 37),
      s: e.s, dt: e.dt, flash: e.dt < 1 / FPS };
  }
  // WHIP — a whip pan through a cut at o.at (or the fill containing t when o.fill): the frame slides along o.dir
  // (radians; 0 = to the right) by o.dist px, accelerating out before the cut and settling after it; blur follows speed.
  // Returns {dx, dy, blur (px of smear), angle}
  function whip(t, o = {}) {
    let at = o.at, dur = o.dur ?? .24;
    if (at == null && o.fill) { const f = HIT.inFill(t); if (!f) return { dx: 0, dy: 0, blur: 0, angle: 0 }; at = f[1]; dur = Math.min(dur, f[1] - f[0]); }
    if (at == null) return { dx: 0, dy: 0, blur: 0, angle: 0 };
    const p = (t - (at - dur / 2)) / dur; if (p <= 0 || p >= 1) return { dx: 0, dy: 0, blur: 0, angle: 0 };
    const D = o.dist ?? 520, ang = o.dir ?? 0;
    const d = p < .5 ? D * easeIn(p * 2) * .5 : -D * .5 * (1 - easeOut((p - .5) * 2));      // out to +D/2, in from −D/2
    const blur = (o.blur ?? 180) * Math.pow(1 - Math.abs(p * 2 - 1), 1.4);
    return { dx: Math.cos(ang) * d, dy: Math.sin(ang) * d, blur, angle: ang };
  }
  // FX — every requested move for this frame, combined: o = {punch: {…}|amp|false, shake, ride, impact, whip, zoom (extra, +),
  // rot (rad), dx, dy (px): a base screen move, e.g. a corkscrew}
  // → {z (zoom factor), dx, dy (px), rot (rad), blur (px), angle, flash, parts}
  const opt = v => v === true ? {} : typeof v === 'number' ? { amp: v } : v;
  function fx(t, o = {}) {
    let z = 1 + (o.zoom || 0), dx = o.dx || 0, dy = o.dy || 0, rot = o.rot || 0, blur = 0, angle = 0, flash = false;   // o.rot/dx/dy: a base move
    const parts = {};
    if (o.punch) { parts.punch = punch(t, opt(o.punch)); z += parts.punch; }
    if (o.ride) { parts.ride = ride(t, opt(o.ride)); z += parts.ride; }
    if (o.impact) { const i = impact(t, opt(o.impact)); parts.impact = i; z += i.z; dx += i.x; dy += i.y; rot += i.r; flash = i.flash; }
    if (o.shake) { const s = shake(t, opt(o.shake)); parts.shake = s; dx += s.x; dy += s.y; rot += s.r; }
    if (o.whip) { const w = whip(t, opt(o.whip)); parts.whip = w; dx += w.dx; dy += w.dy; blur = w.blur; angle = w.angle; }
    return { z, dx, dy, rot, blur, angle, flash, parts };
  }
  // CAM.cam — fold the moves into the cam object MEDIA.drawShot / drawPlate / drawClip take (image space): zoom × z,
  // the shake as a framing offset, rot for 2.5D plates (drawShot drops rot on clips). base: a cam from MEDIA.camFrom or your own.
  function cam(t, base = {}, o = {}) {
    const f = fx(t, o), c = Object.assign({ zoom: 1.06, cx: .5, cy: .5 }, base);
    c.zoom = c.zoom * f.z; c.cx = (c.cx ?? .5) - f.dx / (W * c.zoom); c.cy = (c.cy ?? .5) - f.dy / (H * c.zoom);
    if (f.rot) c.rot = (c.rot || 0) + f.rot;
    c.fx = f; return c;
  }
  // the minimal zoom so a frame turned by r and moved by (dx, dy) still covers the screen
  const cover = (r, dx, dy) => (Math.cos(Math.abs(r)) + (W / H) * Math.sin(Math.abs(r))) + 2 * Math.max(Math.abs(dx) / W, Math.abs(dy) / H);
  // SMEAR — directional motion blur of a canvas (len px along angle), an average of n shifted copies
  const tmp = document.createElement('canvas'); tmp.width = W; tmp.height = H; const tg = tmp.getContext('2d', { willReadFrequently: true });
  function smear(ctx, len, angle = 0, n = 10) {
    if (!(len > .5)) return;
    tg.setTransform(1, 0, 0, 1, 0, 0); tg.globalCompositeOperation = 'copy'; tg.drawImage(ctx.canvas, 0, 0); tg.globalCompositeOperation = 'source-over';
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
    const ux = Math.cos(angle), uy = Math.sin(angle);
    for (let k = 0; k < n; k++) { const s = (k / (n - 1) - .5) * len; ctx.globalAlpha = 1 / (k + 1); ctx.drawImage(tmp, ux * s, uy * s); }
    ctx.restore();
  }
  // compose a mapper with a screen transform (DOMMatrix)
  function wrapMap(m, xf) {
    if (!m || !xf || xf.isIdentity) return m;
    const map0 = m.map, box0 = m.box, P = (x, y) => [xf.a * x + xf.c * y + xf.e, xf.b * x + xf.d * y + xf.f];
    m.map = (u, v) => { const [x, y] = map0(u, v); return P(x, y); };
    m.box = label => { const b = box0(label); if (!b) return b; const c = [P(b[0], b[1]), P(b[0] + b[2], b[1]), P(b[0], b[1] + b[3]), P(b[0] + b[2], b[1] + b[3])];
      const xs = c.map(q => q[0]), ys = c.map(q => q[1]), x0 = Math.min(...xs), y0 = Math.min(...ys); return [x0, y0, Math.max(...xs) - x0, Math.max(...ys) - y0]; };
    m.xf = xf; return m;
  }
  // draw footage through a screen-space camera: o as in fx() plus o.overscan (extra zoom so shake never shows an edge;
  // default from the shake/impact amplitudes). draw() is MEDIA.drawShot/drawPlate/drawClip on b. Returns m (map, box,
  // matte, depth all in screen space) with m.fx = the moves used.
  async function through(b, t, o, draw) {
    const f = fx(t, o);
    const sk = o.shake ? (opt(o.shake).amp ?? 6) : 0, im = o.impact ? (opt(o.impact).shake ?? 14) : 0, rr = (o.shake ? (opt(o.shake).rot ?? .002) : 0) + (o.impact ? (opt(o.impact).rot ?? .006) : 0);
    const need = Math.max(o.overscan != null ? 1 + o.overscan : cover(rr, sk + im, sk + im), cover(f.rot, f.dx, f.dy));
    const s = f.z * need;
    b.save(); b.translate(W / 2 + f.dx, H / 2 + f.dy); if (f.rot) b.rotate(f.rot); b.scale(s, s); b.translate(-W / 2, -H / 2);
    const xf = b.getTransform();
    let m = null;
    try { m = await draw(); } finally { b.restore(); }
    if (f.blur > .5) smear(b, f.blur, f.angle);
    if (m) { wrapMap(m, xf); m.fx = f; }
    return m;
  }
  const shot = (b, id, t, base = {}, o = {}) => through(b, t, o, () => MEDIA.drawShot(b, id, t, base));
  const plate = (b, name, base, t, o = {}) => through(b, t, o, () => MEDIA.drawPlate(b, name, base, t));
  const clip = (b, name, lt, base = {}, o = {}, t = lt) => through(b, t, o, () => MEDIA.drawClip(b, name, lt, base));
  return { noise, punch, shake, ride, impact, whip, fx, cam, cover, smear, wrapMap, through, shot, plate, clip };
})();

window.HIT = HIT; window.CAM = CAM; ENGINE.hit = HIT; ENGINE.cam = CAM;
