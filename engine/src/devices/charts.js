// devices/charts.js — data drawn on in beats: the chart (axes over the first beat, the curve drawn to its head, labels
// popping as the head passes them, the head pulsing on the kick), the sparkline, the points plot (each point lands on its
// time; the curve runs to the newest), the ECG whose heartbeat IS the beat map, and the arrow.
// Ports: the engine's GFX.chart, the second video's INST.plot and its chapter ECG (P/Q/R/S/T as Gaussians around every
// beat; an optional switch to ventricular bigeminy), the big direction arrow. Intentional changes: curves may be data
// (points or values) and the value readout is a format string, so a shots.json entry can carry them; the ECG's switch time
// and labels are params.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.chart) return;
  const C = D.C, TY = D.TY;
  const FN = { exp: u => Math.pow(u, 3.2), lev: u => .08 + .95 * Math.pow(u, 2.4), tick: u => .1 + .7 * u + .08 * Math.sin(u * 37) * (1 - u) + .05 * Math.sin(u * 91),
    osc: u => .5 + .42 * Math.sin(u * TAU * 3.25 - .3) * (1 - .35 * u) + (u > .85 ? (u - .85) * 3 : 0), linear: u => u, log: u => Math.log(1 + 9 * u) / Math.log(10),
    flat: () => .5, drop: u => .92 - .8 * Math.pow(u, 1.8), s: u => 1 / (1 + Math.exp(-12 * (u - .5))) };
  // a curve from data: points [[u, v], …] (u, v in 0..1) linearly interpolated, or values [...] evenly spaced over ymin..ymax
  function curveOf(p) {
    if (Array.isArray(p.points) && p.points.length > 1) { const P = [...p.points].sort((a, b) => a[0] - b[0]);
      return u => { if (u <= P[0][0]) return P[0][1]; for (let i = 1; i < P.length; i++) if (u <= P[i][0]) return lerp(P[i - 1][1], P[i][1], (u - P[i - 1][0]) / Math.max(1e-6, P[i][0] - P[i - 1][0])); return P[P.length - 1][1]; }; }
    if (Array.isArray(p.values) && p.values.length > 1) { const V = p.values, lo = p.ymin ?? Math.min(...V), hi = p.ymax ?? Math.max(...V), n = V.length - 1;
      return u => { const f = clamp(u) * n, i = Math.min(n - 1, Math.floor(f)); return (lerp(V[i], V[i + 1], f - i) - lo) / Math.max(1e-9, hi - lo); }; }
    return FN[p.type] || FN.exp;
  }
  D.curveOf = curveOf;
  const readout = (p, f, u) => { const v = p.value; if (!v) return null; const val = lerp(v.from ?? 0, v.to ?? 100, clamp(f(u), 0, 1.05)); return D.fmt(val, v.format || 'int', { dp: v.dp, prefix: v.prefix, suffix: v.suffix }); };

  D.register('chart', {
    role: 'hero', alias: ['gfx.chart', 'graph', 'curve'],
    defaults: { type: 'exp', w: 520, h: 300, beats: 8, title: '', xlab: '', ylab: '', ref: null, refLabel: '', labels: [], value: null, lw: 2.2 },
    doc: 'A chart that draws itself in beats: the curve the line implies (exponential, a level, a drop), labelled as it passes.',
    draw(o, b, t, p, x) {
      const bs = x.bs(t); if (bs < 0) return; const w = p.w, h = p.h, [px, py0] = x.place(w + 80, h + 90), X0 = px + 40, Y0 = py0 + 46;
      const col = p.color || x.ink([px, py0, w + 80, h + 90]), acc = x.acc(), f = curveOf(p), pr = clamp(bs / (p.beats || 8)), TYf = TY();
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); o.strokeStyle = col; o.fillStyle = col;
      const ax = easeOut(clamp(bs));
      D.hair(o, X0, Y0 + h, X0 + w * ax, Y0 + h, col, 1.2); D.hair(o, X0, Y0 + h, X0, Y0 + h - h * ax, col, 1.2);
      o.globalAlpha *= .25; for (let g = 1; g <= 4; g++) D.hair(o, X0, Y0 + h - h * g / 4, X0 + w * ax, Y0 + h - h * g / 4, col, 1); o.globalAlpha /= .25;
      D.font(o, 17, TYf.mono, 500); o.textBaseline = 'top';
      if (p.title) D.tracked(o, String(p.title).toUpperCase(), X0, Y0 - 34, .08);
      if (p.xlab) { o.textAlign = 'right'; o.fillText(String(p.xlab).toUpperCase(), X0 + w, Y0 + h + 8); o.textAlign = 'left'; }
      if (p.ylab) { o.save(); o.translate(X0 - 10, Y0 + h); o.rotate(-Math.PI / 2); D.tracked(o, String(p.ylab).toUpperCase(), 0, -14, .08); o.restore(); }
      if (p.ref != null) { const ry = Y0 + h - h * p.ref; o.setLineDash([6, 6]); D.hair(o, X0, ry, X0 + w * ax, ry, acc, 1.2); o.setLineDash([]);
        if (p.refLabel) { o.fillStyle = acc; o.textBaseline = 'bottom'; D.tracked(o, String(p.refLabel).toUpperCase(), X0 + 8, ry - 6, .08); o.fillStyle = col; } }
      o.lineWidth = p.lw; o.strokeStyle = p.lineColor || acc; o.beginPath();
      const N = 160; let hx = X0, hy = Y0 + h;
      for (let i = 0; i <= N * pr; i++) { const u = i / N, v = clamp(f(u), 0, 1.05), qx = X0 + u * w, qy = Y0 + h - v * h; i ? o.lineTo(qx, qy) : o.moveTo(qx, qy); hx = qx; hy = qy; }
      o.stroke();
      (p.labels || []).forEach(L => { if (pr < L.u) return; const lx = X0 + L.u * w, ly = Y0 + h - clamp(f(L.u), 0, 1.05) * h;
        o.fillStyle = col; o.beginPath(); o.arc(lx, ly, 5, 0, TAU); o.fill(); D.font(o, 17, TYf.mono, 500); o.textBaseline = 'bottom'; D.tracked(o, String(L.s).toUpperCase(), lx + 8, ly - 6, .06); });
      o.fillStyle = acc; o.beginPath(); o.arc(hx, hy, 5 + 3 * D.kick(t), 0, TAU); o.fill();
      const rv = readout(p, f, pr); if (rv) { D.font(o, 30, TYf.mono, 500); o.textBaseline = 'bottom'; D.tracked(o, rv, hx + 12, hy - 8, .02); }
    },
    example: { kind: 'chart', anchor: { slot: 'top-right' }, key: 'W', params: { type: 'exp', beats: 3, title: 'water level', xlab: 'march', labels: [{ u: .92, s: 'now' }], value: { from: 0, to: 100, format: 'pct' } } },
  });

  // ---- sparkline: a small line of values drawn on over `beats`, the newest point pulsing, its value read out beside it
  D.register('sparkline', {
    role: 'hero', alias: ['spark.line', 'trend'],
    defaults: { values: [3, 4, 3.5, 5, 6.5, 6, 8, 12], w: 260, h: 56, beats: 2, label: '', format: 'int', dp: null, suffix: '' },
    doc: 'A sparkline: a trend in a glance next to the thing it describes (a price, a count, a temperature).',
    draw(o, b, t, p, x) {
      const bs = x.bs(t); if (bs < 0) return; const V = p.values, n = V.length - 1, lo = Math.min(...V), hi = Math.max(...V), pr = clamp(bs / p.beats);
      const [px, py] = x.place(p.w + 110, p.h + 26), col = p.color || x.ink([px, py, p.w + 110, p.h + 26]), acc = x.acc(), TYf = TY(), y0 = py + 22;
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t);
      if (p.label) { D.font(o, 12, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), px, py, .1); }
      o.strokeStyle = col; o.lineWidth = 1.6; o.lineJoin = 'round'; o.beginPath();
      const Y = v => y0 + p.h - p.h * (v - lo) / Math.max(1e-9, hi - lo); let hx = px, hy = Y(V[0]), hv = V[0];
      for (let i = 0; i <= 64 * pr; i++) { const f = i / 64 * n, k = Math.min(n - 1, Math.floor(f)), v = lerp(V[k], V[k + 1], f - k); hx = px + p.w * i / 64; hy = Y(v); hv = v; i ? o.lineTo(hx, hy) : o.moveTo(hx, hy); }
      o.stroke(); o.fillStyle = acc; o.beginPath(); o.arc(hx, hy, 3.5 + 2 * D.kick(t), 0, TAU); o.fill();
      D.font(o, 22, TYf.mono, 500); o.textBaseline = 'middle'; D.tracked(o, D.fmt(hv, p.format, { dp: p.dp, suffix: p.suffix }), px + p.w + 14, hy, .02);
    },
    example: { kind: 'sparkline', anchor: { slot: 'bottom-right' }, key: 'B', params: { values: [12, 14, 13, 18, 22, 21, 30, 41], label: 'VISITS · 30 D', format: 'int' } },
  });

  // ---- plot: points that land on their times — pts [{x, y?, at}] on axes 0..xmax / 0..ymax; fn 'pow2' (y = 2^x, a doubling
  // curve), 'linear' or 'points' (straight segments through the given y); the head eases to the newest point in half a beat
  D.register('plot', {
    role: 'hero', alias: ['inst.plot', 'doubling', 'scatter'],
    defaults: { pts: [{ x: 0, at: { beats: 0 } }, { x: 4, at: { beats: 1 } }, { x: 7, at: { beats: 2 } }, { x: 10, at: { beats: 3 } }], fn: 'pow2', xmax: 10, ymax: 1024, w: 520, h: 300, xlab: 'n', ylab: null },
    doc: 'A plot whose points land on the words/beats: growth made literal (doublings, copies, a count over time).',
    draw(o, b, t, p, x) {
      const pts = p.pts.map(q => ({ ...q, t: D.time(q.at ?? { beats: 0 }, x.sh, x.t0) })).sort((a, b2) => a.t - b2.t), seen = pts.filter(q => t >= q.t); if (!seen.length) return;
      const w = p.w, h = p.h, [px, py] = x.place(w + 60, h + 60), col = p.color || x.ink([px, py, w + 60, h + 60]), acc = x.acc(), TYf = TY(), X0 = px + 20, Y0 = py + 24;
      const yOf = q => p.fn === 'pow2' ? Math.pow(2, q.x) : p.fn === 'linear' ? q.x * p.ymax / p.xmax : (q.y ?? 0);
      const PX = n => X0 + w * n / p.xmax, PY = v => Y0 + h - h * clamp(v / p.ymax);
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); D.hair(o, X0, Y0 + h, X0 + w, Y0 + h, col, 1.2); D.hair(o, X0, Y0, X0, Y0 + h, col, 1.2);
      D.font(o, 12, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'top'; D.tracked(o, String(p.xlab || '').toUpperCase(), X0 + w, Y0 + h + 8, .08, 'right');
      o.textBaseline = 'bottom'; D.tracked(o, String(p.ylab || (p.fn === 'pow2' ? `2ⁿ · ${p.ymax.toLocaleString('en-US')}` : p.ymax.toLocaleString('en-US'))).toUpperCase(), X0 + 8, Y0 - 4, .08);
      const last = seen[seen.length - 1], prev = seen[seen.length - 2], k = prev ? easeOut(seg(t, last.t, last.t + D.bl(last.t) / 2)) : 1, nHead = prev ? lerp(prev.x, last.x, k) : last.x;
      o.strokeStyle = acc; o.lineWidth = 2.4; o.beginPath();
      if (p.fn === 'points') { seen.forEach((q, i) => { const qx = i === seen.length - 1 && prev ? lerp(prev.x, q.x, k) : q.x, qy = i === seen.length - 1 && prev ? lerp(yOf(prev), yOf(q), k) : yOf(q); i ? o.lineTo(PX(qx), PY(qy)) : o.moveTo(PX(qx), PY(qy)); }); }
      else for (let i = 0; i <= 200; i++) { const n = nHead * i / 200, v = p.fn === 'pow2' ? Math.pow(2, n) : n * p.ymax / p.xmax; i ? o.lineTo(PX(n), PY(v)) : o.moveTo(PX(n), PY(v)); }
      o.stroke();
      seen.forEach(q => { if (q.x > nHead + 1e-6) return; o.fillStyle = col; o.beginPath(); o.arc(PX(q.x), PY(yOf(q)), 4, 0, TAU); o.fill(); });
      const hv = p.fn === 'pow2' ? Math.pow(2, nHead) : p.fn === 'linear' ? nHead * p.ymax / p.xmax : lerp(prev ? yOf(prev) : yOf(last), yOf(last), k);
      o.fillStyle = acc; o.beginPath(); o.arc(PX(nHead), PY(hv), 6 + 3 * D.pulse(t, 'kick'), 0, TAU); o.fill();
    },
    example: { kind: 'plot', anchor: { slot: 'top-right' }, key: 'W', params: { fn: 'pow2', xmax: 10, ymax: 1024, xlab: 'weeks', pts: [{ x: 0, at: { beats: 0 } }, { x: 5, at: { beats: 1 } }, { x: 8, at: { beats: 2 } }, { x: 10, at: { beats: 3 } }] } },
  });

  // ---- ecg: a sweeping trace whose heartbeat is the song's beat map (P, Q, R, S, T as Gaussians around every beat); from
  // `bigeminy_at` (a time spec) a premature ventricular beat lands between every other pair of beats
  const gs = (v, s) => Math.exp(-v * v / (2 * s * s));
  const sinus = d => .1 * gs(d + .15, .022) - .12 * gs(d + .024, .007) + gs(d, .008) - .3 * gs(d - .022, .009) + .24 * gs(d - .19, .04);
  function ecgAt(tau, big0) {
    let v = 0; const i0 = Math.floor(bpOf(tau)) - 1;
    for (let i = i0; i <= i0 + 2; i++) { const bt = D.tAtBeat(i); if (bt > tau + .5) continue; const d = tau - bt;
      if (big0 == null || bt < big0) v += sinus(d);
      else { const j = Math.round(bpOf(bt) - bpOf(big0)); if (((j % 2) + 2) % 2 === 0) { v += sinus(d);
        const pv = tau - (bt + (D.tAtBeat(i + 1) - bt) / 2); v += -.25 * gs(pv + .03, .018) + 1.3 * gs(pv, .028) - .45 * gs(pv - .055, .026) - .42 * gs(pv - .2, .05); } } }
    return v;
  }
  D.ecgAt = ecgAt;
  D.register('ecg', {
    role: 'hero', alias: ['heartbeat', 'ekg'],
    defaults: { w: 640, h: 90, sweep: 3.2, label: 'ECG', status: null, bigeminy_at: null, big_label: 'IRREGULAR · EXTRA BEATS' },
    doc: 'A heartbeat monitor whose pulse is the song\'s tempo: panic, love, a body under stress; the rhythm can break on a word.',
    draw(o, b, t, p, x) {
      const e = easeOut(seg(t, x.t0, x.t0 + .25)); if (e <= 0) return;
      const big0 = p.bigeminy_at != null ? D.time(p.bigeminy_at, x.sh, null) : null, w = p.w, h = p.h, [px, py] = x.place(w, h * 2 + 60), y = py + 50 + h;
      const col = p.color || x.ink([px, py, w, h * 2 + 60]), SW = p.sweep, head = px + (((t - x.t0) / SW) % 1) * w, big = big0 != null && t >= big0, TYf = TY();
      o.globalAlpha = e * x.fade(t); o.strokeStyle = col; o.lineWidth = 2; o.lineJoin = 'round'; o.beginPath();
      const dT = 3 / w * SW; let run = [], pt = null;
      const flush = () => { if (run.length >= 3) { o.moveTo(run[0][0], run[0][1]); for (let i = 1; i < run.length; i++) o.lineTo(run[i][0], run[i][1]); } run = []; };
      for (let xx = px; xx <= px + w; xx += 3) {
        const gap = (xx > head && xx < head + 46) || (xx < head + 46 - w), tau = t - (((head - xx) % w + w) % w) / w * SW;
        if (gap || tau < x.t0 || (pt != null && Math.abs(tau - pt - dT) > dT * .5)) { flush(); pt = gap || tau < x.t0 ? null : tau; if (pt != null) run.push([xx, y - h * ecgAt(tau, big0)]); continue; }
        run.push([xx, y - h * ecgAt(tau, big0)]); pt = tau; }
      flush(); o.stroke(); o.fillStyle = big ? x.acc() : col; o.beginPath(); o.arc(head, y - h * ecgAt(t, big0), 4.5, 0, TAU); o.fill();
      o.fillStyle = col; o.textBaseline = 'bottom'; D.font(o, 13, TYf.mono, 500); D.tracked(o, String(p.label).toUpperCase(), px, y - h - 16, .12);
      const r2 = big ? p.big_label : (p.status || `SINUS · ${Math.round(60 / D.bl(t))} BPM`); if (big) o.fillStyle = x.acc();
      D.tracked(o, String(r2).toUpperCase(), px + w, y - h - 16, .1, 'right');
    },
    example: { kind: 'ecg', anchor: { slot: 'bottom-right' }, key: 'B', params: { bigeminy_at: { beats: 4 } } },
  });

  // ---- arrow: a big arrow that draws on along its direction over half a beat (up / down / left / right or radians), with a
  // label at its tail; the head lands on the beat
  D.register('arrow', {
    role: 'hero', alias: ['big.arrow', 'pointer'],
    defaults: { dir: 'up', len: 420, width: 70, label: '' },
    doc: 'A big arrow: direction as meaning (it rose, it fell, over there).',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const ang = typeof p.dir === 'number' ? p.dir : { up: -Math.PI / 2, down: Math.PI / 2, left: Math.PI, right: 0 }[p.dir] ?? -Math.PI / 2;
      const L = p.len, wd = p.width, e = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2)), bw = Math.abs(Math.cos(ang)) * L + wd * 2, bh = Math.abs(Math.sin(ang)) * L + wd * 2;
      const [px, py] = x.place(bw, bh), cx = px + bw / 2, cy = py + bh / 2, col = p.color || x.acc();
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); o.save(); o.translate(cx, cy); o.rotate(ang); o.translate(-L / 2, 0);
      const l = L * e, hd = Math.min(l, wd * 1.4); o.fillStyle = col; o.beginPath();
      o.moveTo(0, -wd * .3); o.lineTo(l - hd, -wd * .3); o.lineTo(l - hd, -wd * .75); o.lineTo(l, 0); o.lineTo(l - hd, wd * .75); o.lineTo(l - hd, wd * .3); o.lineTo(0, wd * .3); o.closePath(); o.fill();
      o.restore();
      if (p.label) { const tx = cx - Math.cos(ang) * L / 2, ty = cy - Math.sin(ang) * L / 2; D.font(o, 15, TY().mono, 500); o.fillStyle = x.ink([px, py, bw, bh]); o.textBaseline = 'top';
        D.tracked(o, String(p.label).toUpperCase(), tx + 8, ty + wd * .5 + 8, .1); }
    },
    example: { kind: 'arrow', anchor: { slot: 'right' }, key: 'W', params: { dir: 'up', label: 'HIGH TIDE' } },
  });
})();
