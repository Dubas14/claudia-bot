// devices/gauges.js — numbers that move on the music: the odometer / sign counter, the keyed readout (a load cell on a
// rope, a usage meter, a risk dial: styles tag · half · bar · thermo), and the tally (marks counted up on 16ths).
// Ports: the engine's GFX.counter (odometer) and GFX.limitBar, the second video's INST.counter (×N set big) and LOAD.tag
// (a keyed readout tracked to an object; value rolls between keys and lands ON each key's time), its chapter gauge() half
// dial, the first video's thermometer and tally strip. Intentional changes: unit / max / mark / thresholds / labels are
// params (the source hard-coded its unit, its mark tick and its label); rolls are timed in beats of the beat map.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.counter) return;
  const C = D.C, TY = D.TY;
  // the value at t: keyed (params.keys [[time, value, ramp]]) or rolling from `from` to `to` over `beats` beats (ease-out)
  const valueAt = (t, p, x) => { const k = x.val(t); if (k != null) return k;
    if (p.to != null) { const tEnd = p.to_at != null ? D.time(p.to_at, x.sh, null) : null, b = tEnd != null ? Math.max(.01, bpOf(tEnd) - bpOf(x.t0)) : p.beats;
      return lerp(p.from ?? 0, p.to, (p.ease === 'in' ? easeIn : easeOut)(clamp(x.bs(t) / b))); }
    return p.value ?? 0; };
  D.valueAt = valueAt;

  // odometer digits: every digit column rolls; the ones column scrolls by the value's fraction (GFX.counter)
  function odometer(g, x, y, value, txt, o) {
    const size = o.size; D.font(g, size, o.family, 400); g.textBaseline = 'alphabetic'; g.fillStyle = o.color;
    const cw = g.measureText('0').width; let xx = x;
    g.save(); g.beginPath(); g.rect(x - 4, y - size * .9, (txt.length + 1) * cw * 1.05, size * 1.05); g.clip();
    for (let i = 0; i < txt.length; i++) { const ch = txt[i];
      if (/\d/.test(ch)) { const place = txt.slice(i + 1).replace(/\D/g, '').length, d = +ch, off = (place === 0 && o.roll ? frac(value) : 0) * size;
        g.fillText(String(d), xx, y - off); if (off) g.fillText(String((d + 1) % 10), xx, y - off + size); }
      else g.fillText(ch, xx, y);
      xx += /\d/.test(ch) ? cw : g.measureText(ch).width; }
    g.restore(); return xx - x;
  }
  D.register('counter', {
    role: 'hero', alias: ['odometer', 'count', 'inst.counter'], typeSize: p => +p.size,
    defaults: { from: 0, to: 100, beats: 3.2, format: 'int', prefix: '', suffix: '', dp: null, size: 120, label: '', style: 'odometer', align: 'left' },
    doc: 'A counter that rolls to the line\'s number on the beat (an amount, a count, a copy number): the stakes ticking.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const v = valueAt(t, p, x), txt = D.fmt(p.dp == null && Math.abs((p.to ?? v) - Math.round(p.to ?? v)) < 1e-9 ? Math.floor(v) : v, p.format, { prefix: p.prefix, suffix: p.suffix, dp: p.dp });
      const TYf = TY(), sign = p.style === 'sign', fam = sign ? TYf.sign : TYf.tech, s = p.size;
      D.font(o, s, fam, sign ? 900 : 400); const tw = o.measureText(txt.replace(/\d/g, '0')).width + s * .3, [px0, py0] = x.place(tw, s * 1.3), col = p.color || x.ink([px0, py0, tw, s * 1.3]);
      const px = p.align === 'right' ? px0 + tw : px0, py = py0 + s; o.globalAlpha = (p.alpha ?? 1) * x.fade(t);
      if (sign) { D.font(o, s, fam, 900); o.fillStyle = col; o.textBaseline = 'alphabetic'; o.textAlign = p.align === 'right' ? 'right' : 'left'; o.fillText(txt, px, py); o.textAlign = 'left'; }
      else odometer(o, p.align === 'right' ? px - tw : px, py, v, txt, { size: s, family: fam, color: col, roll: p.to != null && x.bs(t) < (p.beats || 0) });
      if (p.label) { D.font(o, 15, TYf.mono, 500); o.fillStyle = col; o.globalAlpha *= .85; o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), p.align === 'right' ? px : px, py + 14, .14, p.align === 'right' ? 'right' : 'left'); }
    },
    example: { kind: 'counter', anchor: { slot: 'top-right' }, key: 'W', params: { from: 0, to: 2400, format: '{v} MI', beats: 2, style: 'sign', size: 120, label: 'SINCE SPRING' } },
  });

  // the warning triangle (blinks on the beat when red)
  function warn(g, x, y, s, col) { g.save(); g.fillStyle = col; g.beginPath(); g.moveTo(x, y - s * .55); g.lineTo(x + s * .6, y + s * .48); g.lineTo(x - s * .6, y + s * .48); g.closePath(); g.fill();
    g.fillStyle = C.dark; g.fillRect(x - s * .06, y - s * .2, s * .12, s * .38); g.fillRect(x - s * .06, y + s * .26, s * .12, s * .1); g.restore(); }
  D.register('gauge', {
    role: 'hero', alias: ['readout', 'load', 'meter.gauge', 'dial', 'half.dial', 'thermo', 'thermometer', 'limitbar', 'usage', 'progress'],
    aliasParams: { dial: { style: 'half' }, 'half.dial': { style: 'half' }, thermo: { style: 'thermo' }, thermometer: { style: 'thermo' }, limitbar: { style: 'bar' }, usage: { style: 'bar' }, progress: { style: 'bar' } },
    defaults: { style: 'tag', value: 0, unit: '', max: 100, mark: null, warn: null, red: null, label: 'READOUT', dp: null, dx: 70, dy: -110, r: 130, w: 420, done: '' },
    doc: 'A keyed readout of a physical/abstract quantity (load, usage, risk, temperature) that escalates across shots.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const v = valueAt(t, p, x), e = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2)), TYf = TY();
      const st = p.state || (p.red != null && v >= p.red ? 'red' : p.warn != null && v >= p.warn ? 'warn' : 'ok');
      const dp = p.dp ?? (Math.abs(v) >= 10 ? 0 : 1), txt = v.toFixed(dp);
      o.globalAlpha = (p.alpha ?? 1) * e * x.fade(t);
      if (p.style === 'tag') {                                                    // the load-cell tag on a leader
        // the tag keeps off the lyric blocks and inside the frame: flipped left, down, or both (one whose leader runs clear
        // of the lyric first); else moved to a free spot (x.place, which may shrink the device's canvas about the tag's
        // corner: the anchor is then drawn in that space, so the leader still starts on the thing)
        const a = x.pt() || [W / 2, H / 2], w = 214, h = 92, fl = [[p.dx, p.dy], [-p.dx - w, p.dy], [p.dx, -p.dy - h], [-p.dx - w, -p.dy - h]].map(([u, v]) => [a[0] + u, a[1] + v, w, h]);
        const pref = fl.map((r, i) => D.clearPath(x, [a[0], a[1], i ? clamp(a[0], r[0], r[0] + w) : r[0], i ? clamp(a[1], r[1], r[1] + h) : r[1] + h]));
        let k = p.free ? 0 : D.spot(x, fl, 'gauge:tag', pref), bx, by, s = 1;
        if (k >= 0) [bx, by] = fl[k]; else { [bx, by] = x.place(w, h); const pb = (x.boxes || [])[(x.boxes || []).length - 1]; s = pb && pb.scale > 0 ? pb.scale : 1; }
        const A = s === 1 ? a : [bx + (a[0] - bx) / s, by + (a[1] - by) / s];
        const col = p.color || x.ink([bx, by, w * s, h * s]), hot = st !== 'ok' ? x.acc() : col;
        o.strokeStyle = col; o.lineWidth = 1.2; o.beginPath(); o.arc(A[0], A[1], 5, 0, TAU); o.stroke(); o.beginPath(); o.moveTo(A[0] + 4, A[1] - 4); o.lineTo(k > 0 || k < 0 ? clamp(A[0], bx, bx + w) : bx, k > 0 || k < 0 ? clamp(A[1], by, by + h) : by + h); o.stroke();
        o.fillStyle = 'rgba(11,12,14,.72)'; o.fillRect(bx, by, w, h); o.strokeStyle = st === 'red' ? hot : 'rgba(245,243,238,.35)'; o.strokeRect(bx + .5, by + .5, w - 1, h - 1);
        D.font(o, 12, TYf.mono, 500); o.fillStyle = C.light; o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), bx + 12, by + 10, .1);
        D.font(o, 44, TYf.sign, 900); o.fillStyle = st !== 'ok' ? hot : C.light; o.textBaseline = 'alphabetic'; o.fillText(txt, bx + 12, by + 70); const tw = o.measureText(txt).width;
        if (p.unit) { D.font(o, 20, TYf.sign, 700); o.fillText(p.unit, bx + 18 + tw, by + 70); }
        if (st === 'red' && frac(bpOf(t)) < .5) warn(o, bx + w - 26, by + 50, 26, hot);
        const bw = w - 24; o.fillStyle = 'rgba(245,243,238,.2)'; o.fillRect(bx + 12, by + h - 12, bw, 3);
        o.fillStyle = st !== 'ok' ? hot : C.light; o.fillRect(bx + 12, by + h - 12, bw * clamp(v / p.max), 3);
        if (p.mark != null) { o.fillStyle = hot; o.fillRect(bx + 12 + bw * clamp(p.mark / p.max), by + h - 16, 2, 11); }
        return;
      }
      if (p.style === 'half' || p.style === 'dial') {                             // the half dial (0 … max), needle in the accent
        const R = p.r, [px, py] = x.place(R * 2 + 40, R + 70), cx = px + R + 20, cy = py + R + 20, col = p.color || x.ink([px, py, R * 2 + 40, R + 70]), acc = x.acc();
        const u = clamp(v / p.max), a = Math.PI * (1 + u), head = Math.min(.07, u * Math.PI);
        o.strokeStyle = col; o.lineWidth = Math.max(1.2, R * .02); o.beginPath(); o.arc(cx, cy, R, Math.PI, TAU); o.stroke();
        for (let q = 0; q <= 100; q += 10) { const aa = Math.PI * (1 + q / 100), l = q % 50 ? .9 : .82; D.hair(o, cx + Math.cos(aa) * R * l, cy + Math.sin(aa) * R * l, cx + Math.cos(aa) * R, cy + Math.sin(aa) * R, col, q % 50 ? 1 : 2); }
        o.globalAlpha *= .55; o.lineWidth = Math.max(3, R * .06); o.beginPath(); o.arc(cx, cy, R * .74, Math.PI, a - head); o.stroke(); o.globalAlpha /= .55;
        o.strokeStyle = acc; o.beginPath(); o.arc(cx, cy, R * .74, a - head, a); o.stroke();
        D.hair(o, cx, cy, cx + Math.cos(a) * R * .97, cy + Math.sin(a) * R * .97, acc, Math.max(2, R * .03));
        o.fillStyle = col; o.beginPath(); o.arc(cx, cy, Math.max(4, R * .04), 0, TAU); o.fill();
        D.font(o, Math.max(12, R * .085), TYf.mono, 500); o.textAlign = 'center'; o.textBaseline = 'top';
        o.fillText('0', cx - R, cy + 10); o.fillText(D.fmt(p.max / 2, 'int'), cx, cy - R - 26 - R * .04); o.fillText(D.fmt(p.max, 'int'), cx + R, cy + 10);
        D.font(o, Math.max(28, R * .3), TYf.sign, 900); o.textBaseline = 'alphabetic'; o.fillText(txt + (p.unit || ''), cx, cy - R * .18);
        D.font(o, 13, TYf.mono, 500); o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), cx, cy + 34, .1, 'center'); o.textAlign = 'left';
        return;
      }
      if (p.style === 'thermo') {                                                 // a thermometer that pins at the top
        const hh = p.h || 420, [px, py] = x.place(120, hh + 60), col = p.color || x.ink([px, py, 120, hh + 60]), acc = x.acc(), u = clamp(v / p.max), tx = px + 30, top = py + 20, bot = py + hh;
        o.strokeStyle = col; o.lineWidth = 1.5; D.rr(o, tx - 12, top, 24, hh - top + py + 6, 12); o.stroke(); o.beginPath(); o.arc(tx, bot + 22, 24, 0, TAU); o.stroke();
        o.fillStyle = u >= 1 ? acc : col; o.beginPath(); o.arc(tx, bot + 22, 17, 0, TAU); o.fill(); o.fillRect(tx - 6, top + 6 + (bot - top - 6) * (1 - u), 12, (bot - top - 6) * u + 12);
        D.font(o, 12, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'middle';
        for (let q = 0; q <= 4; q++) { const y = bot - (bot - top - 6) * q / 4; D.hair(o, tx + 16, y, tx + 26, y, col, 1); o.fillText(D.fmt(p.max * q / 4, 'int'), tx + 32, y); }
        o.fillStyle = u >= 1 ? acc : col; D.font(o, 15, TYf.mono, 500); o.textBaseline = 'bottom'; D.tracked(o, (u >= 1 && p.done ? p.done : txt + (p.unit || '')).toUpperCase(), px, top - 8, .08);
        D.font(o, 12, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), px, bot + 56, .08);
        return;
      }
      // bar: the usage meter that fills and flips to the banner at max
      const w = p.w, [px, py] = x.place(w, 60), col = p.color || x.ink([px, py, w, 60]), u = clamp(v / p.max), full = u >= 1, acc = full ? x.acc() : col;
      D.font(o, 13, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'bottom'; D.tracked(o, String(p.label).toUpperCase(), px, py + 12, .08);
      o.fillStyle = 'rgba(245,243,238,.15)'; o.fillRect(px, py + 20, w, 16); o.fillStyle = full ? acc : col; o.fillRect(px, py + 20, w * u, 16);
      if (p.mark != null) { o.fillStyle = col; o.fillRect(px + w * clamp(p.mark / p.max), py + 16, 2, 24); }
      o.textBaseline = 'top'; o.fillStyle = full ? acc : col; D.tracked(o, (full && p.done ? String(p.done) : `${D.fmt(v, 'int', { dp: p.dp })}${p.unit || '%'}`).toUpperCase(), px, py + 44, .08);
    },
    example: { kind: 'gauge', anchor: { uv: [.55, .5] }, key: 'W', params: { style: 'tag', unit: '°C', max: 42, mark: 37, warn: 37.5, red: 38.5, dp: 1, label: 'FEVER · NIGHT 3', keys: [[{ beats: 0 }, 36.6], [{ beats: 2 }, 37.9], [{ beats: 4 }, 39.1, .3]] } },
  });

  // ---- tally: marks counted up on 16ths (or 32nds) from the start to n; style 'tally' (groups of five, the fifth struck),
  // 'bar' (a strip of n cells), or a glyph; a micro readout SEEN nn / n
  D.register('tally', {
    role: 'hero', alias: ['count.marks', 'marks.count', 'tallystrip'], typeSize: p => +p.size,
    defaults: { n: 20, per: 16, style: 'tally', label: 'COUNT', size: 34, glyph: '●', of: true },
    doc: 'A tally counted on the beat (cars waiting, people online, days away): the count is the explanation.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const k = Math.min(p.n, Math.floor(x.bs(t) * (p.per / 4)) + 1), s = p.size, TYf = TY();
      const step = p.style === 'tally' ? s * .32 : s * .78, cols = p.style === 'tally' ? p.n + Math.floor(p.n / 5) : p.n, w = Math.min(W - 400, cols * step + 40), [px, py] = x.place(w, s + 40);
      const col = p.color || x.ink([px, py, w, s + 40]), acc = x.acc(); o.globalAlpha = (p.alpha ?? 1) * x.fade(t); o.fillStyle = col; o.strokeStyle = col; o.lineWidth = Math.max(2, s * .08);
      let xx = px;
      for (let i = 0; i < k; i++) { const fresh = i === k - 1 && k < p.n;
        if (p.style === 'tally') { if (i % 5 === 4) { o.strokeStyle = fresh ? acc : col; o.beginPath(); o.moveTo(xx - step * 4.4, py + s * .8); o.lineTo(xx + step * .2, py + s * .15); o.stroke(); o.strokeStyle = col; xx += step * 1.4; continue; }
          o.strokeStyle = fresh ? acc : col; o.beginPath(); o.moveTo(xx, py); o.lineTo(xx, py + s); o.stroke(); o.strokeStyle = col; xx += step; }
        else if (p.style === 'bar') { o.fillStyle = fresh ? acc : col; o.fillRect(xx, py, step * .8, s); xx += step; }
        else { o.fillStyle = fresh ? acc : col; D.font(o, s * .8, TYf.mono, 500); o.textBaseline = 'top'; o.fillText(p.glyph, xx, py); xx += step; } }
      D.font(o, 13, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'top';
      D.tracked(o, `${String(p.label).toUpperCase()} ${String(k).padStart(2, '0')}${p.of ? ' / ' + p.n : ''}`, px, py + s + 12, .08);
    },
    example: { kind: 'tally', anchor: { slot: 'bottom-right' }, key: 'W', params: { n: 30, per: 16, label: 'DAYS AWAY' } },
  });
})();
