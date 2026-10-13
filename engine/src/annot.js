// annot.js — annotation tied to things in frame: tracking brackets, callouts with leader lines, a tempo-locked ticker,
// an audio meter from the song's loudness, crop marks, a beat ruler. Overlay layer, crisp.
// Port notes (engine-core v1):
//   - ruler: bar numbers come from the downbeat map (1-based, the bar a tick starts); it never prints negative or
//     malformed numbers ('0-3'), and without a beat map it counts bars of four from beat 0.
//   - callout: the leader draws over half a beat and rows type 3 characters per 16th (o.cps) — the old default (a whole
//     beat, 1 character per 16th) never finished on a one-bar shot; pass {lead: 1, cps: 1} for the old timing.
//   - meter: SONG.rms24 (beats asset) or, without it, the HITS mix envelope.
//   - brackets: o.safe = [x0, y0, x1, y1] keeps the label and confidence inside that rect (the portrait lead kit).
'use strict';
const ANN = (() => {
  // tracks for clips: window.TRACK[clip][label] = [[x,y,w,h] per frame | null] at 12 fps (image space)
  function trackBox(clip, label, localT, fps = 12) {
    const T = (window.TRACK || {})[clip]; if (!T || !T[label]) return null;
    const a = T[label]; const f = localT * fps, i = Math.floor(f), k = f - i;
    const b0 = a[clamp(i, 0, a.length - 1)], b1 = a[clamp(i + 1, 0, a.length - 1)];
    if (!b0 || !b1) return b0 || b1 || null;
    return b0.map((v, j) => lerp(v, b1[j], k));
  }
  // corner brackets around a screen-space box; corners grow in on t0 (over 1/8 note); jitter on eighths
  function brackets(ctx, box, t, o = {}) {
    if (!box) return; const t0 = o.t0 ?? -1e9; const e = easeOut(seg(t, t0, t0 + KIN.beatLen(t0) / 2)); if (e <= 0) return;
    let [x, y, w, h] = box; const j = o.jitter ?? 1.5, n = Math.floor(bpOf(t) * 2);
    x += (hash2(n, 1) - .5) * j; y += (hash2(n, 2) - .5) * j;
    const L = Math.min(w, h) * .18 * e + 6, col = o.color || INK.white, lw = o.lw || 1.4;
    ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.globalAlpha = o.alpha ?? 1; ctx.beginPath();
    [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]].forEach(([cx, cy, sx, sy]) => { ctx.moveTo(cx + sx * L, cy); ctx.lineTo(cx, cy); ctx.lineTo(cx, cy + sy * L); });
    ctx.stroke();
    if (o.label) { font(ctx, 12, F.mono, 500); ctx.fillStyle = col; ctx.textBaseline = 'bottom';
      const lab = String(o.label).toUpperCase(); let lx = x, ly = y - 6, rx = x + w;
      // o.safe = [x0, y0, x1, y1]: keep the label and the confidence inside it (portrait frames)
      if (o.safe) { const lw = ctx.measureText(lab).width + lab.length * 12 * .08; lx = clamp(lx, o.safe[0], Math.max(o.safe[0], o.safe[2] - lw));
        ly = Math.max(ly, o.safe[1] + 14); rx = Math.min(rx, o.safe[2]); }
      tracked(ctx, lab, lx, ly, .08);
      if (o.conf != null && isFinite(o.conf)) { ctx.textAlign = 'right'; ctx.fillText((+o.conf).toFixed(2), rx, ly); ctx.textAlign = 'left'; } }
    if (o.cross) { hair(ctx, x + w / 2 - 6, y + h / 2, x + w / 2 + 6, y + h / 2, col, 1); hair(ctx, x + w / 2, y + h / 2 - 6, x + w / 2, y + h / 2 + 6, col, 1); }
    ctx.restore();
  }
  // callout: dot at the anchor, leader with one elbow, label block typed on
  function callout(ctx, ax, ay, rows, t, t0, o = {}) {
    const bl = KIN.beatLen(t0) * (o.lead ?? .5), e = easeOut(seg(t, t0, t0 + bl)); if (e <= 0) return;
    const out = o.until ?? 1e9; if (t > out + .2) return; const fade = 1 - seg(t, out, out + .2);
    const dx = o.dx ?? 140, dy = o.dy ?? -90, col = o.color || INK.white;
    const ex = ax + dx, ey = ay + dy, lx = ex + (dx >= 0 ? 36 : -36);
    ctx.save(); ctx.globalAlpha = fade; ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.arc(ax, ay, 4, 0, TAU); ctx.stroke();
    const k1 = clamp(e * 2), k2 = clamp(e * 2 - 1);
    ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(lerp(ax, ex, k1), lerp(ay, ey, k1)); if (k2 > 0) ctx.lineTo(lerp(ex, lx, k2), ey); ctx.stroke();
    ctx.restore();
    if (k2 >= 1) KIN.typeRows(ctx, rows, dx >= 0 ? lx + 8 : lx - 8 - (o.labelW || 220), ey - 9, t, t0 + bl, { color: col, fade, cps: o.cps ?? 3 });
  }
  // ticker strip: items scroll right-to-left at a speed locked to the beat; functions of t are evaluated per frame
  function ticker(ctx, items, t, o = {}) {
    const y = o.y ?? (H - 40), hgt = 26, col = o.color || INK.white, bg = o.bg;
    const strs = items.map(it => typeof it === 'function' ? it(t) : it).filter(s => s != null && s !== '').map(s => String(s).toUpperCase() + '   ✱   ');
    if (!strs.length) return;
    if (bg) { ctx.fillStyle = bg; ctx.fillRect(0, y - hgt / 2 - 2, W, hgt + 4); }
    hair(ctx, 0, y - hgt / 2 - 2, W, y - hgt / 2 - 2, col, 1); hair(ctx, 0, y + hgt / 2 + 2, W, y + hgt / 2 + 2, col, 1);
    font(ctx, 13, F.mono, 500); ctx.fillStyle = col; ctx.textBaseline = 'middle';
    const widths = strs.map(s => ctx.measureText(s).width + s.length * 1.0), total = widths.reduce((a, b) => a + b, 0);
    const speed = (o.pxPerBeat ?? 60), off = ((bpOf(t) * speed) % total + total) % total;
    let x = -off; ctx.save(); ctx.beginPath(); ctx.rect(0, y - hgt / 2, W, hgt); ctx.clip();
    while (x < W) { strs.forEach((s, i) => { if (x > -widths[i] && x < W) tracked(ctx, s, x, y, .06); x += widths[i]; }); }
    ctx.restore();
  }
  // audio meter: the song's loudness (24/s) as a bar strip, the current bar in the accent
  function meter(ctx, x, y, w, h, t, o = {}) {
    const HH = window.HITS || {}, R = SONG.rms24 || (HH.env && HH.env.mix) || (HH.env24 && HH.env24.mix); if (!R || !R.length) return;
    const fr = SONG.rms24 ? 24 : (HH.fps || 24), n = o.bars || 48, i0 = Math.floor(t * fr);
    for (let k = 0; k < n; k++) { const v = R[clamp(i0 - (n - 1 - k), 0, R.length - 1)] || 0; const bh = Math.max(1, v * h);
      ctx.fillStyle = k === n - 1 ? (o.accent || INK.accent) : (o.color || INK.white); ctx.globalAlpha = k === n - 1 ? 1 : .55 + .45 * k / n;
      ctx.fillRect(x + k * (w / n), y + h - bh, Math.max(1, w / n - 2), bh); }
    ctx.globalAlpha = 1;
  }
  function cropMarks(ctx, col = INK.white, inset = 28, len = 16) {
    ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = 1; ctx.globalAlpha = .7; ctx.beginPath();
    [[inset, inset, 1, 1], [W - inset, inset, -1, 1], [inset, H - inset, 1, -1], [W - inset, H - inset, -1, -1]].forEach(([x, y, sx, sy]) => {
      ctx.moveTo(x - sx * len, y); ctx.lineTo(x + sx * len * .4, y); ctx.moveTo(x, y - sy * len); ctx.lineTo(x, y + sy * len * .4); });
    ctx.stroke(); ctx.restore();
  }
  // the bar number (1-based) a beat index starts, or null when that beat is not a downbeat
  function barOfBeat(b) {
    const B = SONG.beats, D = SONG.downbeats;
    if (B && B.length > 1 && D && D.length) {
      if (b < 0 || b >= B.length) return null;
      const tb = B[b]; let lo = 0, hi = D.length - 1;
      while (lo < hi) { const m = (lo + hi) >> 1; if (D[m] < tb - 1e-3) lo = m + 1; else hi = m; }
      return Math.abs(D[lo] - tb) < .02 ? lo + 1 : null;
    }
    return b >= 0 && b % 4 === 0 ? b / 4 + 1 : null;
  }
  // vertical ruler with beat ticks scrolling at tempo (left edge), bar numbers on downbeats
  function ruler(ctx, x, t, o = {}) {
    const col = o.color || INK.white, sp = o.spacing || 22, bp = bpOf(t);
    ctx.save(); ctx.strokeStyle = col; ctx.fillStyle = col; ctx.globalAlpha = .6; ctx.lineWidth = 1; font(ctx, 10, F.mono, 400); ctx.textBaseline = 'middle';
    for (let k = -2; k < H / sp + 2; k++) { const b = Math.floor(bp) + k - 12, y = H / 2 + (b - bp) * sp; if (y < 40 || y > H - 40) continue;
      const bar = barOfBeat(b); ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + (bar ? 14 : 7), y); ctx.stroke();
      if (bar) ctx.fillText(String(bar).padStart(3, '0'), x + 18, y); }
    ctx.globalAlpha = 1; ctx.fillStyle = o.accent || INK.accent; ctx.fillRect(x - 3, H / 2 - 1, 22, 2); ctx.restore();
  }
  return { trackBox, brackets, callout, ticker, meter, cropMarks, ruler, barOfBeat };
})();
