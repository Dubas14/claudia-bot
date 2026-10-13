// devices/voice.js — the singer's actual voice as a shape: the live spectrum as a line or bars, a ribbon travelling from a
// source to a target (the older sound further out), rings born on each kick and displaced by the spectrum, and an orb
// whose outline breathes with the vocal bands.
// Ports: the second video's SPEC (frame · level · line · bars · beam · rings) and its chapter orb(). Data: window.SPECTRUM
// (24 fps × 64 log bands, bytes = dB over range_db, base64 per stem; written by the audio module). Intentional change:
// without a spectrum asset the bands are synthesised from the stem envelope (window.HITS.env) — or the beat — so the
// device still moves with the music instead of disappearing.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.voice) return;
  const C = D.C, TY = D.TY;
  const S = () => window.SPECTRUM || null, dec = {};
  function data(stem) { if (dec[stem]) return dec[stem]; const s = S(); if (!s || !s[stem]) return null;
    const bin = atob(s[stem]), a = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) a[i] = bin.charCodeAt(i); return dec[stem] = a; }
  // the spectrum at t: Float32Array(nb) 0..1, interpolated between frames (synthesised from the envelope when absent)
  function frame(t, stem = 'vocals') {
    const s = S(), a = data(stem), nb = s ? s.bands || 64 : 64, out = new Float32Array(nb);
    if (a) { const x = clamp(t * s.fps, 0, s.n - 1), i = Math.floor(x), k = x - i, j = Math.min(i + 1, s.n - 1);
      for (let b2 = 0; b2 < nb; b2++) out[b2] = lerp(a[i * nb + b2], a[j * nb + b2], k) / 255; return out; }
    const env = D.has.HIT() ? HIT.env(t, stem === 'mix' ? 'mix' : stem) || HIT.env(t, 'mix') : .55 * Math.exp(-frac(bpOf(t)) * 3), f = Math.floor(t * 24);
    for (let b2 = 0; b2 < nb; b2++) { const shape = Math.exp(-Math.pow((b2 - 18) / 16, 2)) * .9 + .1; out[b2] = clamp(env * shape * (.55 + .45 * hash2(b2, f)) * 1.4); }
    return out;
  }
  const level = (t, stem = 'vocals', lo = 0, hi = 64) => { const f = frame(t, stem); let s = 0; hi = Math.min(hi, f.length); for (let b2 = lo; b2 < hi; b2++) s += f[b2]; return s / Math.max(1, hi - lo); };
  D.spec = { frame, level };

  D.register('voice', {
    role: 'hero', alias: ['spectrum', 'spec', 'spec.line', 'spec.bars', 'spec.beam', 'spec.rings', 'orb', 'voice.orb', 'voice.line', 'voice.beam', 'voice.rings', 'ribbon'],
    aliasParams: { 'spec.line': { style: 'line' }, 'voice.line': { style: 'line' }, 'spec.bars': { style: 'bars' }, 'spec.beam': { style: 'beam' }, 'voice.beam': { style: 'beam' }, ribbon: { style: 'beam' },
      'spec.rings': { style: 'rings' }, 'voice.rings': { style: 'rings' }, orb: { style: 'orb' }, 'voice.orb': { style: 'orb' } },
    defaults: { style: 'bars', stem: 'vocals', w: 520, h: 120, n: 32, from: 4, to: 60, gain: 1.15, lw: 2, mirror: false, to_pt: null, width: 40, lines: 3, speed: 900,
      aspect: .2, life: 1.6, decay: .6, disp: .06, r: 110, label: '' },
    doc: 'The voice itself as a shape (spectrum line/bars, a ribbon of sound travelling to a listener, rings on the water, an orb).',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const e = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0))), TYf = TY(), acc = x.acc();
      o.globalAlpha = (p.alpha ?? 1) * e * x.fade(t); o.lineJoin = 'round';
      const st = p.style;
      if (st === 'beam') {                                       // the ribbon: half-width at distance d = the level at t − d / speed
        const a = x.pt() || [W * .3, H * .6], to = p.to_pt ? (Array.isArray(p.to_pt) ? p.to_pt : (() => { const bx = D.anchor(p.to_pt, x); return bx ? [bx[0] + bx[2] / 2, bx[1] + bx[3] / 2] : [W * .75, H * .4]; })()) : [a[0] + 600, a[1] - 200];
        const [x0, y0] = a, [x1, y1] = to, L = Math.max(1, Math.hypot(x1 - x0, y1 - y0)), ux = (x1 - x0) / L, uy = (y1 - y0) / L, nx = -uy, ny = ux, N = 120;
        o.strokeStyle = p.color || acc; o.lineWidth = 1.6;
        for (let li = 0; li < p.lines; li++) { const off = p.lines === 1 ? 0 : (li / (p.lines - 1) - .5) * 2; o.beginPath();
          for (let i = 0; i <= N; i++) { const d = L * i / N * e, tt = t - d / p.speed, av = level(tt, p.stem, 6, 50) * (1 - .35 * i / N);
            const wig = Math.sin(d * .045 - t * 9 + li * 1.7) * av * p.width * .35, r = off * av * p.width + wig, qx = x0 + ux * d + nx * r, qy = y0 + uy * d + ny * r; i ? o.lineTo(qx, qy) : o.moveTo(qx, qy); }
          o.stroke(); }
        return;
      }
      if (st === 'rings') {                                      // rings born on each kick, displaced by the mix spectrum at birth
        const c = x.pt() || [W / 2, H * .62], col = p.color || x.ink([c[0] - 200, c[1] - 60, 400, 120]);
        const ks = D.has.HIT() ? HIT.between(t - p.life, t + 1e-6, 'kick') : (() => { const out = []; for (let k = Math.floor(bpOf(t - p.life)); k <= Math.floor(bpOf(t)); k++) { const bt = D.tAtBeat(k); if (bt <= t && bt >= t - p.life) out.push({ t: bt, s: 1 }); } return out; })();
        o.lineWidth = 1.4; const a0 = o.globalAlpha;
        ks.forEach((k, ki) => { const age = t - k.t, r = age * p.speed + 30, f = frame(k.t, 'mix');
          o.globalAlpha = a0 * .8 * Math.exp(-age / p.decay) * lerp(.5, 1, k.s); o.strokeStyle = ki === ks.length - 1 ? acc : col; o.beginPath();
          for (let i = 0; i <= 128; i++) { const an = i / 128 * TAU, bi = Math.min(f.length - 1, 4 + Math.floor(Math.abs(Math.sin(an * .5)) * 55)), d = 1 + p.disp * f[bi];
            const qx = c[0] + Math.cos(an) * r * d, qy = c[1] + Math.sin(an) * r * p.aspect * d; i ? o.lineTo(qx, qy) : o.moveTo(qx, qy); } o.stroke(); });
        return;
      }
      if (st === 'orb') {                                        // the outline breathes with ten vocal band groups (Catmull-Rom)
        const [px, py] = x.place(p.r * 2.6, p.r * 2.6), cx = px + p.r * 1.3, cy = py + p.r * 1.3, f = frame(t, p.stem), lv = level(t, p.stem, 6, 50), K = 10, N = 120;
        const on = Math.max(0, lv - .15), base = p.r * (1 + .08 * on), d = [];
        for (let i = 0; i < K; i++) { let a = 0; for (let q = 0; q < 4; q++) a += f[4 + i * 4 + q] || 0; d.push(base * clamp(.02 * Math.sin(t * 2.2 + i * 1.9) + .45 * (a / 4) * on, -.2, .2)); }
        const cr = (p0, p1, p2, p3, u) => .5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u * u * u);
        const rad = s => { const xx = s * K, i = Math.floor(xx), u = xx - i, at = k => d[((k % K) + K) % K]; return base + cr(at(i - 1), at(i), at(i + 1), at(i + 2), u); };
        const path = sc => { o.beginPath(); for (let n = 0; n <= N; n++) { const s = n / N, an = s * TAU - Math.PI / 2, r0 = rad(s) * sc; const qx = cx + Math.cos(an) * r0, qy = cy + Math.sin(an) * r0; n ? o.lineTo(qx, qy) : o.moveTo(qx, qy); } o.closePath(); };
        path(1); o.strokeStyle = acc; o.lineWidth = 3.5; o.stroke(); path(.86); o.strokeStyle = p.color || x.ink([px, py, p.r * 2.6, p.r * 2.6]); o.lineWidth = 1.2; o.stroke();
        return;
      }
      // line / bars: the live spectrum across w, up from a baseline
      const [px, py] = x.place(p.w, p.h + 30), y = py + p.h + (p.label ? 22 : 0), col = p.color || x.ink([px, py, p.w, p.h + 30]), f = frame(t, p.stem), w = p.w * e;
      if (p.label) { D.font(o, 13, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), px, py, .1); }
      if (st === 'line') { o.strokeStyle = col; o.lineWidth = p.lw; const n = p.to - p.from;
        const side = s => { o.beginPath(); for (let i = 0; i < n; i++) { const qx = px + w * i / (n - 1), qy = y - s * p.h * clamp(f[p.from + i] * p.gain); i ? o.lineTo(qx, qy) : o.moveTo(qx, qy); } o.stroke(); };
        side(1); if (p.mirror) side(-1); return; }
      for (let i = 0; i < p.n; i++) { const bi = Math.floor(p.from + (p.to - p.from) * i / p.n), bh = Math.max(1, p.h * clamp(f[bi] * p.gain));
        o.fillStyle = i === Math.floor(p.n * .3) ? acc : col; o.fillRect(px + i * w / p.n, y - bh, Math.max(1, w / p.n - 3), bh); }
    },
    example: { kind: 'voice', anchor: { slot: 'bottom-right' }, key: 'B', params: { style: 'bars', label: 'VOCAL · STEM' } },
  });
})();
