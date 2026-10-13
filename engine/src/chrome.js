// chrome.js — the overlay language: type tokens (F), margins (M), split-flap boards, countdown, garment tags / model
// cards, care label, the declared mass, corner chrome, and the default chrome stack + lead kit (ENGINE.chrome /
// ENGINE.leadKit). All drawn crisp on the overlay canvas.
// Port notes (engine-core v1):
//   - fonts come from fonts/fonts.js roles (Space Grotesk replaces Nimbus Sans as F.grotesk; Instrument Serif replaces
//     Junicode as F.serif; Pilcrow Rounded is gone — F.round aliases the grotesk); project.json look.fonts overrides
//     lyric / micro / display (ENGINE.prepareData).
//   - every string comes from window.PROJECT (chrome.{corner, counter, departures, serial, kicker, lead_label, ticker,
//     board{unit, mid, line, sub}}) — no reference-video defaults (look counters, serials, countdown units).
//   - flapBoard restores textAlign/textBaseline (it leaked textAlign = 'center' into later draws).
//   - mass() flickers on eighths of the beat map (it used a fixed-BPM eighth).
//   - portrait frames (H > W) get portrait margins (the vertical cut's UI-safe area); the lead kit fits its brackets into
//     them (ENGINE.fitBox: a subject wider than 90 % of the frame gets no body brackets) and keeps labels inside.
'use strict';
const F = (() => {
  const roles = ((window.ENGINE_FONTS || {}).roles) || { display: 'Barlow Condensed', grotesk: 'Space Grotesk', mono: 'IBM Plex Mono',
    tech: 'Share Tech Mono', serif: 'Instrument Serif', serif2: 'Instrument Serif', wide: 'Audiowide', lava: 'Pilowlava',
    sign: 'DINish Condensed', signW: 'DINish', code: 'JetBrains Mono', alt: 'Geist' };
  const f = {}; Object.keys(roles).forEach(k => f[k] = `"${roles[k]}"`); f.round = f.grotesk; return f;
})();
function font(ctx, size, fam, weight = 400, style = '') { ctx.font = `${style} ${weight} ${size}px ${F[fam] || fam}`.trim(); }
function tracked(ctx, txt, x, y, em = 0, align = 'left') {
  // letter-spaced text (canvas letterSpacing is supported in Chromium)
  const m = ctx.font.match(/(\d+(\.\d+)?)px/), size = m ? parseFloat(m[1]) : 16;
  ctx.letterSpacing = `${em * size}px`;
  const w = ctx.measureText(txt).width;
  const x0 = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
  ctx.textAlign = 'left'; ctx.fillText(txt, x0, y); ctx.letterSpacing = '0px'; return w;
}
function hair(ctx, x0, y0, x1, y1, col, w = 1.2) { ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); ctx.restore(); }

// margins: unequal on purpose; hang type from the left axis or from a feature, never centre by default. Portrait (the
// 9:16 cut) keeps type clear of the platforms' top bar, bottom caption/UI band and right-hand action column.
const M = PORTRAIT ? { l: 72, t: 180, r: 150, b: 420 } : { l: 72, t: 56, r: 96, b: 84 };

// ---------- split-flap board ----------
// Each cell flips from its old glyph to its new one, staggered left to right, with the real split-flap mechanics:
// top half of the old glyph folds down while the new glyph's top is revealed, then the bottom lands.
const FLAP_CHARS = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:-/%';
function flapBoard(ctx, x, y, cells, text, prev, tFlip, t, o = {}) {
  const cw = o.cw || 40, ch = o.ch || 62, gap = o.gap || 4, fg = o.fg || INK.white, bg = o.bg || '#1a1b1d', acc = o.accent;
  const size = ch * .78, spin = o.spin ?? 6;           // how many intermediate glyphs a cell cycles through
  const T = String(text ?? '').toUpperCase().padEnd(cells).slice(0, cells), P = String(prev ?? '').toUpperCase().padEnd(cells).slice(0, cells);
  const align0 = ctx.textAlign, base0 = ctx.textBaseline;
  font(ctx, size, F.tech, 400);
  ctx.textBaseline = 'middle'; ctx.textAlign = 'center';
  for (let i = 0; i < cells; i++) {
    const cx = x + i * (cw + gap), start = tFlip + i * (o.stagger ?? .025) + hash(i * 3.1) * .04;
    const p = seg(t, start, start + (o.dur ?? .38));           // 0..1 through this cell's flipping
    const changed = T[i] !== P[i];
    // which glyph pair is mid-flip: cycle through `spin` glyphs from old to new
    let a = P[i], b = T[i], k = 1;
    if (changed && p < 1) {
      const steps = spin, s = p * steps, n = Math.floor(s); k = s - n;
      const idx = j => FLAP_CHARS[(Math.max(0, FLAP_CHARS.indexOf(P[i])) + j * 7 + 1) % FLAP_CHARS.length];
      a = n === 0 ? P[i] : idx(n); b = n >= steps - 1 ? T[i] : idx(n + 1);
    } else { a = b = T[i]; k = 1; }
    // cell
    ctx.fillStyle = bg; ctx.fillRect(cx, y, cw, ch);
    const cy = y + ch / 2;
    const half = (g, top, scaleY) => {
      ctx.save(); ctx.beginPath(); top ? ctx.rect(cx, y, cw, ch / 2) : ctx.rect(cx, cy, cw, ch / 2); ctx.clip();
      ctx.translate(cx + cw / 2, cy); ctx.scale(1, scaleY); ctx.fillStyle = (acc && o.accentCells && o.accentCells.includes(i)) ? acc : fg;
      ctx.fillText(g, 0, size * .04); ctx.restore();
    };
    // static: top of new, bottom of old; flipping leaf: old top folding down (first half), new bottom unfolding (second half)
    half(b, true, 1); half(k < .5 ? a : b, false, 1);
    if (k < 1) {
      if (k < .5) { ctx.save(); ctx.fillStyle = bg; ctx.fillRect(cx, y + ch / 2 * (2 * k), cw, ch / 2 * (1 - 2 * k)); ctx.restore(); half(a, true, 1 - 2 * k); }
      else { half(b, false, 2 * k - 1); }
    }
    // the hinge line and a soft shade
    ctx.fillStyle = 'rgba(0,0,0,.55)'; ctx.fillRect(cx, cy - 1, cw, 2);
    ctx.fillStyle = 'rgba(255,255,255,.04)'; ctx.fillRect(cx, y, cw, ch / 2);
  }
  ctx.textAlign = align0; ctx.textBaseline = base0;      // (fix) never leak 'center' / 'middle' into later draws
  return (cw + gap) * cells - gap;
}

// the project's words for the chrome: window.PROJECT.chrome (or legacy top-level keys), e.g.
// { corner: 'TITLE · 2026', counter: 'SECTION', board: {unit, mid, line, sub}, departures: 'DEPARTURES · …', serial, kicker }
const PJ = () => { const p = window.PROJECT || {}; return Object.assign({}, p, p.chrome || {}); };
const _title = () => { const p = window.PROJECT || {}; return String(p.title || p.name || '').toUpperCase(); };

// ---------- the countdown lockup: N <unit> <mid> <line> ----------
function countdown(ctx, x, y, num, prevNum, tFlip, t, o = {}) {
  const s = o.scale || 1;
  const w = flapBoard(ctx, x, y, 2, num, prevNum, tFlip, t, { cw: 64 * s, ch: 100 * s, gap: 6 * s, accent: o.accent, accentCells: [0, 1], bg: o.bg });
  const B = PJ().board || {}, unit = o.unit ?? B.unit ?? '', mid = o.mid ?? B.mid ?? '';
  if (unit) flapBoard(ctx, x + w + 14 * s, y, 6, unit, o.prevUnit || unit, tFlip, t, { cw: 30 * s, ch: 48 * s, gap: 3 * s, bg: o.bg });
  if (mid) flapBoard(ctx, x + w + 14 * s, y + 52 * s, 9, mid, mid, tFlip, t, { cw: 30 * s, ch: 48 * s, gap: 3 * s, bg: o.bg });
  ctx.fillStyle = o.ink || INK.white; font(ctx, 13 * s, F.mono, 500); ctx.textBaseline = 'top';
  tracked(ctx, o.line ?? B.line ?? '', x, y + 112 * s, .08);
  hair(ctx, x, y + 134 * s, x + w + 14 * s + 9 * 33 * s, y + 134 * s, o.ink || INK.white, 1.2);
  font(ctx, 11 * s, F.mono, 400); tracked(ctx, o.sub ?? B.sub ?? '', x, y + 142 * s, .08);
}

// ---------- garment tag / model card ----------
// A woven care-label card: header, field:value rows, care symbols, serial, barcode. rows: [[field, value], …]
function garmentTag(ctx, x, y, o) {
  const rowsIn = o.rows || [], w = o.w || 300, pad = 16, rowH = 20, ink = o.ink || INK.ink, paper = o.paper || INK.white, acc = o.accent || INK.accent;
  const n = rowsIn.length, h = o.h || (pad * 2 + 58 + n * rowH + 64);
  const rot = o.rot || 0, k = o.pop == null ? 1 : easeOut(o.pop);
  const serial = o.serial ?? PJ().serial ?? '', kicker = o.kicker ?? PJ().kicker ?? '';
  ctx.save(); ctx.translate(x, y); ctx.rotate(rot); ctx.globalAlpha = k; ctx.translate(0, (1 - k) * 30);
  // woven label body with a stitched fold at the top
  ctx.fillStyle = paper; ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(0,0,0,.08)'; ctx.fillRect(0, 0, w, 10);
  ctx.setLineDash([3, 3]); hair(ctx, 6, 14, w - 6, 14, 'rgba(0,0,0,.35)', 1); ctx.setLineDash([]);
  ctx.fillStyle = ink; ctx.textBaseline = 'top';
  if (kicker) { font(ctx, 11, F.mono, 500); tracked(ctx, kicker, pad, 24, .08); }
  if (o.badge) { font(ctx, 11, F.mono, 500); const bw = ctx.measureText(o.badge).width + 14; ctx.fillStyle = acc; ctx.fillRect(w - pad - bw, 20, bw, 18); ctx.fillStyle = paper; tracked(ctx, o.badge, w - pad - bw + 7, 24, .04); ctx.fillStyle = ink; }
  font(ctx, 30, F.display, 600); tracked(ctx, o.title || '', pad, 42, -.01);
  let yy = 42 + 40; hair(ctx, pad, yy, w - pad, yy, ink, 1.2); yy += 8;
  font(ctx, 12, F.mono, 400);
  rowsIn.forEach(([f, v], i) => { const reveal = o.reveal == null ? 1 : clamp(o.reveal * (n + 1) - i);
    if (reveal <= 0) return; ctx.globalAlpha = k * reveal; tracked(ctx, String(f).toUpperCase(), pad, yy + i * rowH, .06);
    ctx.textAlign = 'right'; ctx.fillText(String(v).toUpperCase(), w - pad, yy + i * rowH); ctx.textAlign = 'left'; });
  ctx.globalAlpha = k;
  yy += n * rowH + 6; hair(ctx, pad, yy, w - pad, yy, ink, 1.2);
  careSymbols(ctx, pad, yy + 10, 18, ink, o.nerf);
  barcode(ctx, w - pad - 110, yy + 10, 110, 26, serial || o.title || _title() || 'SLOP', ink);
  if (serial) { font(ctx, 10, F.mono, 400); tracked(ctx, serial, w - pad - 110, yy + 40, .06); }
  ctx.restore();
  return h;
}
function careSymbols(ctx, x, y, s, ink, nerf) {
  ctx.save(); ctx.strokeStyle = ink; ctx.lineWidth = 1.3; ctx.fillStyle = ink;
  // wash tub, triangle (bleach), iron, circle (dry clean), square (tumble) — o.nerf crosses the last one ("do not")
  const tub = () => { ctx.beginPath(); ctx.moveTo(0, 3); ctx.lineTo(3, s); ctx.lineTo(s - 3, s); ctx.lineTo(s, 3); ctx.stroke(); font(ctx, 8, F.mono, 500); ctx.textAlign = 'center'; ctx.fillText('30', s / 2, s * .45); ctx.textAlign = 'left'; };
  const tri = () => { ctx.beginPath(); ctx.moveTo(s / 2, 2); ctx.lineTo(s, s); ctx.lineTo(0, s); ctx.closePath(); ctx.stroke(); };
  const iron = () => { ctx.beginPath(); ctx.moveTo(2, s); ctx.lineTo(s, s); ctx.lineTo(s - 2, 5); ctx.lineTo(6, 5); ctx.quadraticCurveTo(2, 8, 2, s); ctx.stroke(); };
  const circ = () => { ctx.beginPath(); ctx.arc(s / 2, s / 2 + 1, s / 2 - 1, 0, TAU); ctx.stroke(); };
  const sq = () => { ctx.strokeRect(1, 2, s - 2, s - 2); ctx.beginPath(); ctx.arc(s / 2, s / 2 + 1, s / 2 - 4, 0, TAU); ctx.stroke(); };
  const cross = () => { ctx.beginPath(); ctx.moveTo(0, 1); ctx.lineTo(s, s + 1); ctx.moveTo(s, 1); ctx.lineTo(0, s + 1); ctx.stroke(); };
  [tub, tri, iron, circ, sq].forEach((f, i) => { ctx.save(); ctx.translate(x + i * (s + 8), y); f(); if (i === 2 || (nerf && i === 4)) cross(); ctx.restore(); });
  ctx.restore();
}
function barcode(ctx, x, y, w, h, seed, ink) {
  ctx.fillStyle = ink; let xx = x, i = 0; const sd = [...String(seed)].reduce((a, c) => a + c.charCodeAt(0), 0);
  while (xx < x + w) { const bw = 1 + Math.floor(hash(sd + i) * 3); if (i % 2 === 0) ctx.fillRect(xx, y, bw, h); xx += bw; i++; }
}

// ---------- type modes (simple, string-based; the lyric modes with word timing are KIN.* in kinetic.js) ----------
// (i) coverline lockup: one left axis, 1-2 display lines + micro mono pairs. words: [{w, t0}] reveal on their times.
function coverline(ctx, x, y, lines, t, o = {}) {
  const size = o.size || 54, col = o.color || INK.white, micro = o.micro || [], lh = size * 1.02;
  ctx.fillStyle = col; ctx.textBaseline = 'alphabetic';
  font(ctx, size, o.family || F.grotesk, o.weight || 700);
  lines.forEach((ln, i) => {
    if (typeof ln === 'string') { tracked(ctx, ln, x, y + i * lh, o.track ?? -.03); return; }
    let xx = x; ln.forEach(wd => { const k = seg(t, wd.t0 - .02, wd.t0 + .06); if (k <= 0) { xx += ctx.measureText(wd.w + ' ').width; return; }
      ctx.globalAlpha = k; const ww = tracked(ctx, wd.w, xx, y + i * lh + (1 - k) * 6, o.track ?? -.03); xx += ww + ctx.measureText(' ').width; ctx.globalAlpha = 1; });
  });
  const my = y + (lines.length - 1) * lh + size * .55;
  if (micro.length) { const w = o.ruleW || size * 5; hair(ctx, x, my, x + w, my, col, 1.2);
    font(ctx, 13, F.mono, 400); ctx.textBaseline = 'top'; micro.forEach((m, i) => tracked(ctx, String(m).toUpperCase(), x, my + 10 + i * 19, .06)); }
}
// (ii) masthead word: huge, only over a quiet patch. pop on its beat; optional value-inversion via 'difference'.
function masthead(ctx, word, x, y, size, t, t0, o = {}) {
  const k = o.cut ? (t >= t0 ? 1 : 0) : expoOut(seg(t, t0, t0 + .12));
  if (k <= 0) return;
  ctx.save(); if (o.invert) ctx.globalCompositeOperation = 'difference';
  ctx.fillStyle = o.color || INK.white; ctx.globalAlpha = o.alpha ?? 1; ctx.textBaseline = 'alphabetic';
  font(ctx, size, o.family || F.display, o.weight || 500);
  const sx = o.stretch || 1; ctx.translate(x, y); ctx.scale(sx * (o.cut ? 1 : lerp(1.04, 1, k)), 1);
  tracked(ctx, word, 0, 0, o.track ?? -.02, o.align || 'left'); ctx.restore();
}
// (iii) declared mass: a wall of micro lines (≥ 12 lines), each flickering in on eighths of the beat map.
function mass(ctx, lines, x, y, t, t0, o = {}) {
  if (!lines || !lines.length) return;
  const size = o.size || 13, lh = size * 1.45, col = o.color || INK.white, rows = o.rows || 40;
  font(ctx, size, o.family || F.mono, 400); ctx.fillStyle = col; ctx.textBaseline = 'top';
  const e = Math.floor((bpOf(t) - bpOf(t0)) * 2);           // (fix) eighths since t0 on the beat map, not a fixed BPM
  for (let r = 0; r < rows; r++) {
    const on = hash2(r, e) < (o.density ?? .75) || r === o.keep;
    if (!on) continue;
    const ln = lines[(r + (o.scroll ? e : 0)) % lines.length];
    ctx.globalAlpha = r === o.keep ? 1 : lerp(.35, .9, hash2(r * 7, e));
    tracked(ctx, String(ln).toUpperCase(), x, y + r * lh, .04);
  }
  ctx.globalAlpha = 1;
}
// subtitle: the plain lyric line, small, lower-left, on one axis with the chrome
function subtitle(ctx, txt, x, y, t, t0, t1, o = {}) {
  const k = seg(t, t0, t0 + .1) * (1 - seg(t, t1 - .1, t1)); if (k <= 0) return;
  ctx.globalAlpha = k; ctx.fillStyle = o.color || INK.white; font(ctx, o.size || 24, o.family || F.grotesk, 400); ctx.textBaseline = 'alphabetic';
  tracked(ctx, txt, x, y, -.01); ctx.globalAlpha = 1;
}
// corner chrome: section counter + project corner text + timecode, on one margin system
function cornerChrome(ctx, t, n, total, o = {}) {
  const col = o.color || INK.white; ctx.fillStyle = col; font(ctx, 12, F.mono, 500); ctx.textBaseline = 'top';
  const counter = PJ().counter ?? 'SECTION';
  tracked(ctx, o.label ?? `${counter} ${String(n).padStart(2, '0')} / ${String(total).padStart(2, '0')}`, M.l, M.t, .08);
  tracked(ctx, o.corner ?? PJ().corner ?? _title(), W - M.r, M.t, .08, 'right');
  const s = Math.max(0, t), mm = Math.floor(s / 60), ss = Math.floor(s % 60), ff = Math.floor(frac(s) * FPS);
  ctx.textBaseline = 'alphabetic';
  tracked(ctx, `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}:${String(ff).padStart(2, '0')}`, W - M.r, H - M.b + 12, .08, 'right');
}

// ---------- the departures board (full frame): rows of split-flap cells, each row flips on its own time ----------
// rows: [{label, value, prev, tFlip, accent:true|false, sub}] · o: {x, y, cw, ch, title, dim}
function departures(ctx, rows, t, o = {}) {
  const cw = o.cw || 44, ch = o.ch || 70, gap = 5, x = o.x ?? M.l, y0 = o.y ?? 150, labelCells = o.labelCells || 24, valueCells = o.valueCells || 9;
  const rowH = ch + (o.rowGap ?? 46);
  ctx.save(); ctx.globalAlpha = o.alpha ?? 1;
  ctx.fillStyle = o.ink || INK.white; font(ctx, 14, F.mono, 500); ctx.textBaseline = 'top';
  tracked(ctx, o.title || PJ().departures || 'DEPARTURES', x, y0 - 42, .1);
  tracked(ctx, o.statusLabel || 'STATUS', x + labelCells * (cw * .62 + 3) + 30, y0 - 42, .1);
  hair(ctx, x, y0 - 16, W - M.r, y0 - 16, o.ink || INK.white, 1.2);
  rows.forEach((r, i) => {
    const y = y0 + i * rowH, lab = (r.label || '').toUpperCase();
    flapBoard(ctx, x, y, labelCells, lab, r.prevLabel ?? lab, r.tLabel ?? -1, t, { cw: cw * .62, ch: ch * .62, gap: 3, bg: o.bg });
    const vx = x + labelCells * (cw * .62 + 3) + 30;
    flapBoard(ctx, vx, y - ch * .19, valueCells, (r.value || '').toUpperCase(), (r.prev ?? '').toUpperCase(), r.tFlip ?? -1, t,
      { cw, ch, gap, bg: o.bg, accent: r.accent ? (o.accent || INK.accent) : null, accentCells: r.accent ? [...Array(valueCells).keys()] : null, spin: r.spin ?? 8 });
    if (r.sub) { font(ctx, 12, F.mono, 400); ctx.fillStyle = o.ink || INK.white; ctx.globalAlpha = (o.alpha ?? 1) * .7; tracked(ctx, r.sub.toUpperCase(), x, y + ch * .62 + 10, .08); ctx.globalAlpha = o.alpha ?? 1; }
  });
  ctx.restore();
}

// ---------- the default chrome stack and the lead kit (the project layer may replace them: common.js chrome/leadKit) ----------
// sections from the beat map: index (1-based) and name at t
function _sectionAt(t) {
  const S = (SONG.sections || []).filter(s => s && s.t0 != null);
  let i = -1; S.forEach((s, k) => { if (t >= s.t0 - 1e-6) i = k; });
  return { i, n: S.length, s: i >= 0 ? S[i] : null };
}
// a beat-pip + bar counter (top right), and the hairline progress bar with section ticks (bottom)
function _barPips(o, t, x, y, col, acc) {
  const bp = bpOf(t), D = SONG.downbeats || [];
  let bar = 0; if (D.length) { let lo = 0, hi = D.length; while (lo < hi) { const m = (lo + hi) >> 1; if (D[m] <= t + 1e-6) lo = m + 1; else hi = m; } bar = lo; } else bar = Math.floor(bp / 4) + 1;
  const beatIn = D.length && bar > 0 ? Math.max(0, Math.floor(bp - bpOf(D[bar - 1]) + 1e-6)) % 4 : ((Math.floor(bp) % 4) + 4) % 4;
  font(o, 12, F.mono, 500); o.fillStyle = col; o.textBaseline = 'top';
  const w = tracked(o, `BAR ${String(Math.max(0, bar)).padStart(3, '0')}`, x, y, .08, 'right');
  for (let k = 0; k < 4; k++) { o.fillStyle = k === beatIn ? acc : col; o.globalAlpha = k === beatIn ? 1 : .45; o.fillRect(x - w - 16 - (3 - k) * 10, y + 3, 6, 6); }
  o.globalAlpha = 1;
}
function _progress(o, t, col, acc) {
  const dur = SONG.duration || 0; if (!(dur > 0)) return;
  const y = H - Math.max(18, M.b * .35), x0 = M.l, x1 = W - M.r, k = clamp(t / dur);
  o.save(); o.globalAlpha = .35; hair(o, x0, y, x1, y, col, 1); o.globalAlpha = 1; hair(o, x0, y, lerp(x0, x1, k), y, acc, 2);
  (SONG.sections || []).forEach(s => { if (s.t0 > 0 && s.t0 < dur) { const xx = lerp(x0, x1, s.t0 / dur); hair(o, xx, y - 4, xx, y + 4, col, 1); } });
  o.restore();
}
ENGINE.chrome = function (o, t, opts = {}) {
  const P = window.PROJECT || {}, C = P.chrome || {}, col = opts.color || INK.white, acc = opts.accent || INK.accent;
  const mode = String((P.look || {}).mode || 'native');
  const style = opts.style || C.style || (/print/.test(mode) ? 'full' : 'minimal');
  if (style === 'none') return;
  const sec = _sectionAt(t);
  if (style === 'minimal') {
    font(o, 12, F.mono, 500); o.fillStyle = col; o.textBaseline = 'top';
    const left = [C.corner ?? _title(), sec.s ? String(sec.s.name || '').toUpperCase() : ''].filter(Boolean).join(' · ');
    tracked(o, left, M.l, M.t, .08);
    _barPips(o, t, W - M.r, M.t, col, acc);
    if (opts.progress !== false && C.progress !== false) _progress(o, t, col, acc);
    return;
  }
  cornerChrome(o, t, Math.max(1, sec.i + 1), Math.max(1, sec.n), { color: col, label: opts.label ?? C.label });
  if (C.cropMarks !== false) ANN.cropMarks(o, col);
  if (opts.ruler !== false && C.ruler !== false) ANN.ruler(o, 30, t, { accent: acc, color: col });
  const tick = (C.ticker && C.ticker.length ? C.ticker : [_title()]).filter(Boolean);
  if (opts.ticker !== false && C.ticker !== false) ANN.ticker(o, [tt => `TC ${KIN.tc(tt)}`, ...tick], t, { y: H - 30, color: col });
  if (opts.meter !== false && C.meter !== false) ANN.meter(o, W - M.r - 180, M.t + 28, 180, 26, t, { accent: acc, color: col });
};
// the lead's annotation kit: brackets on the lead (+ the face) and one callout. Boxes come from the plate detections
// (PLATES[name].boxes) or clip tracks (TRACK); the label to look for is PROJECT.lead.label, else common person labels.
const _LEAD_LABELS = ['subject', 'a person', 'a woman', 'a man', 'a girl', 'a boy', 'a singer'];
ENGINE.leadLabel = m => {
  const P = window.PROJECT || {}, want = [P.lead && (P.lead.label || P.lead.match), ..._LEAD_LABELS].filter(Boolean);
  if (!m || !m.box) return null; for (const l of want) if (m.box(l)) return l; return null;
};
// the frame's safe rect [x0, y0, x1, y1] (inside the margins) and a box fitted into it for annotation. In portrait (the
// 9:16 cut) a subject box is usually wider than the frame: a box wider than `maxW` of the frame gets no brackets (null),
// any other box is intersected with the safe rect so brackets and labels stay in frame. Landscape boxes pass unchanged
// unless opts.always.
ENGINE.safeRect = () => [M.l, M.t, W - M.r, H - M.b];
ENGINE.fitBox = function (b, opts = {}) {
  if (!b || !(PORTRAIT || opts.always)) return b || null;
  if (b[2] > (opts.maxW ?? .9) * W) return null;
  const [sx0, sy0, sx1, sy1] = ENGINE.safeRect(), x0 = Math.max(b[0], sx0), y0 = Math.max(b[1], sy0);
  const x1 = Math.min(b[0] + b[2], sx1), y1 = Math.min(b[1] + b[3], sy1);
  return x1 - x0 > 8 && y1 - y0 > 8 ? [x0, y0, x1 - x0, y1 - y0, ...b.slice(4)] : null;
};
ENGINE.leadKit = function (o, m, t, t0, opts = {}) {
  if (!m || !m.box) return;
  const lab = opts.box || ENGINE.leadLabel(m), body = ENGINE.fitBox(lab ? m.box(lab) : null), face = ENGINE.fitBox(m.box('a face'), { maxW: .6 });
  const sec = _sectionAt(t), C = (window.PROJECT || {}).chrome || {};
  const conf = opts.conf ?? (m.score && lab ? m.score(lab) : null);
  const safe = PORTRAIT ? ENGINE.safeRect() : null;
  if (body && opts.body !== false) ANN.brackets(o, body, t, { t0, label: opts.label || `${C.lead_label || 'LEAD 01'} · ${String(Math.max(1, sec.i + 1)).padStart(2, '0')}`, conf: conf ?? undefined, color: opts.color, safe });
  if (face && opts.face) ANN.brackets(o, face, t, { t0: t0 + .1, cross: true, color: opts.color, safe });
  if (opts.rows && (face || body)) { const b = face || body; ANN.callout(o, b[0] + b[2], b[1] + b[3] * .4, opts.rows, t, t0 + .3, { dx: opts.dx ?? 170, dy: opts.dy ?? -70, color: opts.color }); }
};
ENGINE.sectionAt = _sectionAt;
ENGINE.fonts = F; ENGINE.font = font; ENGINE.M = M;
