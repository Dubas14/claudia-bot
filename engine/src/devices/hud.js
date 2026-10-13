// devices/hud.js — the chrome and the micro layer. DEV.hud is the default chrome when the project defines no chrome():
// top left the title and the section, top right the bar number and four beat pips (the current beat in the accent),
// a bottom hairline with the song's progress and a tick at each section start; the ink adapts per corner.
// Micro devices (texture; ≤ 3 rows of micro type per FRAME, counted by the renderer — microRows): typed (source rows /
// timestamps typed on 16ths), ticker (a strip that
// scrolls one item per bar), marks (crop marks / a beat ruler / a measuring grid), and the declared wall (mass).
// Ports: the second video's chrome() (made generic: the title and sections come from window.PROJECT / shots.json), the
// engine's ANN.ticker / cropMarks / ruler (the ruler no longer prints negative or odd bar numbers) and mass() (on the
// beat map's eighths instead of a fixed-BPM eighth). Portrait (9:16): the progress line, the ticker and the wall keep to
// the UI-safe margins.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.hud) return;
  const C = D.C, TY = D.TY, MG = D.MG;
  const sections = () => { const SL = window.SHOTS || window.SHOTLIST || {}; return (Array.isArray(SL) ? [] : SL.chapters || []).map(c => ({ id: c.id ?? '', name: c.name ?? '', t0: c.t0 ?? c.start ?? 0, t1: c.t1 ?? c.end ?? 1e9 })); };
  const sectionAt = t => { const S = sections(); let cur = S[0] || null; for (const s of S) if (t >= s.t0 - 1e-6) cur = s; return cur; };
  // opts: off · min (pips only) · b (the base ctx for the ink) · ink (force) · alpha · accent · title · section (text)
  D.hud = (o, t, opts = {}) => {
    if (opts.off) return; const b = opts.b || null, a = opts.alpha ?? 1, acc = opts.accent || C.accent, TYf = TY(), Mg = MG();
    const ink = box => opts.ink || (b && D.has.AINK() ? AINK.pick(b, box, { split: false }).ink : (opts.light ? C.dark : C.light));
    const PJ = window.PROJECT || {}, SL = window.SHOTS || window.SHOTLIST || {};
    o.save(); o.globalAlpha = a; o.textBaseline = 'top';
    const bar = Math.max(0, Math.floor(bpOf(t) / 4 + 1e-6)), beat = ((Math.floor(bpOf(t) + 1e-6) % 4) + 4) % 4;
    if (!opts.min) {
      const title = String(opts.title ?? PJ.title ?? SL.title ?? '').toUpperCase(), sec = sectionAt(t), stxt = opts.section ?? (sec ? [sec.id, sec.name].filter(Boolean).join(' · ') : '');
      const cl = ink([Mg.l, Mg.t - 6, 420, 40]); o.fillStyle = cl; D.font(o, 13, TYf.mono, 500); const w1 = title ? D.tracked(o, title, Mg.l, Mg.t, .16) : 0;
      if (stxt) { o.globalAlpha = a * .7; D.font(o, 13, TYf.mono, 400); D.tracked(o, String(stxt).toUpperCase(), Mg.l + w1 + (w1 ? 22 : 0), Mg.t, .1); o.globalAlpha = a; }
      const y = H > W ? H - Mg.b - 12 : H - 34, x0 = Mg.l, x1 = W - Mg.r, dur = (window.HITS && window.HITS.duration) || SONG.duration || SL.duration || 1, cb = ink([x0, y - 8, x1 - x0, 16]);
      o.globalAlpha = a * .38; D.hair(o, x0, y, x1, y, cb, 1);
      sections().forEach(s => { const x = lerp(x0, x1, clamp(s.t0 / dur)); D.hair(o, x, y - 3, x, y + 3, cb, 1); });
      o.globalAlpha = a; o.fillStyle = acc; o.fillRect(x0, y - 1, (x1 - x0) * clamp(t / dur), 2);
    }
    const cr = ink([W - Mg.r - 200, Mg.t - 6, 200, 40]), px = W - Mg.r - 4 * 12 + 3; D.font(o, 13, TYf.mono, 500);
    for (let k = 0; k < 4; k++) { const on = k === beat; o.fillStyle = on ? acc : cr; o.globalAlpha = a * (on ? 1 : .45); o.fillRect(px + k * 12, Mg.t + 3, 7, 7); }
    o.globalAlpha = a; o.fillStyle = cr; D.tracked(o, `BAR ${String(bar).padStart(3, '0')}`, px - 14, Mg.t, .12, 'right');
    o.restore(); o.letterSpacing = '0px'; o.textAlign = 'start';
  };
  D.sectionAt = sectionAt;

  // ---- typed: micro rows (a source, a timestamp, a caption) typed on 16ths, ≤ 3 rows
  D.register('typed', {
    role: 'micro', alias: ['micro', 'source', 'rows', 'caption.micro'], microRows: p => Math.min((p.rows || []).length, +p.max || 3),
    defaults: { rows: ['SOURCE · 2026'], size: 13, per16: 3, max: 3, align: 'left' },
    doc: 'Micro rows typed on the 16ths: the source of a claim, a date, a caption — sources cited on screen.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const w = p.w || 520, h = Math.min(p.rows.length, p.max) * 19, [px, py] = x.place(w, h), col = p.color || x.ink([px, py, w, h]);
      D.typed(o, p.rows, p.align === 'right' ? px + w : px, py, t, x.t0, { size: p.size, per16: p.per16, max: p.max, color: col, alpha: x.fade(t), align: p.align, dim: true, first: true });
    },
    example: { kind: 'typed', anchor: { slot: 'bottom-left' }, key: 'W', params: { rows: ['SRC · CITY RECORDS · 1987', 'PARAPHRASE'] } },
  });

  // ---- ticker: a strip of items scrolling right to left, one bar of the beat map per `pxPerBeat` × 4 px
  D.register('ticker', {
    role: 'micro', alias: ['crawl', 'ann.ticker'], microRows: () => 1,
    defaults: { items: ['ITEM ONE', 'ITEM TWO'], y: null, pxPerBeat: 60, sep: '   ✱   ', bg: null },
    doc: 'A news-style ticker crawling on the beat: background facts, the world reacting.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const hgt = 26, TYf = TY();
      // its band keeps off the lyric blocks: the asked / default band, else the other edge of the frame, else no ticker
      const y0 = p.y ?? (H > W ? H - MG().b - 20 : H - 30), bands = [y0, H > W ? MG().t - 40 : 30, H > W ? H - MG().b - 20 : H - 30];
      const i = bands.findIndex(yy => !D.hitsAny([0, yy - hgt / 2 - 3, W, hgt + 6], x.avoid)); if (i < 0) return false;
      const y = bands[i], col = p.color || x.ink([0, y - 15, W, 30]);
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); if (p.bg) { o.fillStyle = p.bg; o.fillRect(0, y - hgt / 2 - 2, W, hgt + 4); }
      D.hair(o, 0, y - hgt / 2 - 2, W, y - hgt / 2 - 2, col, 1); D.hair(o, 0, y + hgt / 2 + 2, W, y + hgt / 2 + 2, col, 1);
      D.font(o, 13, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'middle';
      const strs = p.items.map(s => String(s).toUpperCase() + p.sep), widths = strs.map(s => o.measureText(s).width + s.length * .78), total = Math.max(1, widths.reduce((a, c) => a + c, 0));
      const off = ((bpOf(t) * p.pxPerBeat) % total + total) % total; let xx = -off;
      o.save(); o.beginPath(); o.rect(0, y - hgt / 2, W, hgt); o.clip();
      for (let guard = 0; xx < W && guard < 400; guard++) strs.forEach((s, i) => { if (xx > -widths[i] && xx < W) D.tracked(o, s, xx, y, .06); xx += widths[i]; });
      o.restore();
    },
    example: { kind: 'ticker', key: 'B', params: { items: ['WEATHER · CLEAR', 'TRAINS · ON TIME', 'LIVE'] } },
  });

  // ---- marks: crop marks at the frame corners, a beat ruler on the left edge (ticks scroll at tempo, bar numbers on
  // downbeats, never negative), or a measuring grid of thirds with a crosshair on the anchor
  D.register('marks', {
    role: 'micro', alias: ['cropmarks', 'ruler', 'grid', 'ann.ruler'], microRows: p => p.style === 'ruler' ? 1 : 0, aliasParams: { cropmarks: { style: 'crop' }, ruler: { style: 'ruler' }, 'ann.ruler': { style: 'ruler' }, grid: { style: 'grid' } },
    defaults: { style: 'crop', inset: 28, len: 16, spacing: 22 },
    doc: 'Printer\'s crop marks, a beat ruler or a measuring grid: the frame as a document being measured.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const col = p.color || x.ink([0, 0, 200, H]); o.strokeStyle = col; o.fillStyle = col; o.lineWidth = 1; o.globalAlpha = .7 * x.fade(t);
      if (p.style === 'crop') { const I = p.inset, L = p.len; o.beginPath();
        [[I, I, 1, 1], [W - I, I, -1, 1], [I, H - I, 1, -1], [W - I, H - I, -1, -1]].forEach(([qx, qy, sx, sy]) => { o.moveTo(qx - sx * L, qy); o.lineTo(qx + sx * L * .4, qy); o.moveTo(qx, qy - sy * L); o.lineTo(qx, qy + sy * L * .4); }); o.stroke(); return; }
      if (p.style === 'ruler') { const sp = p.spacing, bp = bpOf(t), x0 = p.x ?? 30; D.font(o, 10, TY().mono, 400); o.textBaseline = 'middle';
        for (let k = -2; k < H / sp + 2; k++) { const bb = Math.floor(bp) + k - 12, y = H / 2 + (bb - bp) * sp; if (y < 40 || y > H - 40) continue;
          const isBar = ((bb % 4) + 4) % 4 === 0; o.beginPath(); o.moveTo(x0, y); o.lineTo(x0 + (isBar ? 14 : 7), y); o.stroke(); if (isBar && bb >= 0) o.fillText(String(Math.floor(bb / 4)).padStart(3, '0'), x0 + 18, y); }
        o.globalAlpha = 1; o.fillStyle = x.acc(); o.fillRect(x0 - 3, H / 2 - 1, 22, 2); return; }
      // grid: thirds + a crosshair on the anchor (or the lead)
      o.globalAlpha = .35 * x.fade(t); for (let i = 1; i < 3; i++) { D.hair(o, W * i / 3, 0, W * i / 3, H, col, 1); D.hair(o, 0, H * i / 3, W, H * i / 3, col, 1); }
      const c = x.pt() || (x.lead ? [x.lead[0] + x.lead[2] / 2, x.lead[1] + x.lead[3] / 2] : null);
      if (c) { o.globalAlpha = .8 * x.fade(t); D.hair(o, c[0] - 18, c[1], c[0] + 18, c[1], col, 1); D.hair(o, c[0], c[1] - 18, c[0], c[1] + 18, col, 1);
        D.font(o, 11, TY().mono, 500); o.textBaseline = 'top'; D.tracked(o, `${Math.round(c[0])}, ${Math.round(c[1])}`, c[0] + 8, c[1] + 8, .06); }
    },
    example: { kind: 'marks', key: 'B', params: { style: 'ruler' } },
  });

  // ---- mass: the declared wall of micro text (≥ 12 rows), flickering on eighths; lines from params or every lyric
  D.register('mass', {
    role: 'hero', alias: ['wall', 'declared.mass'],
    defaults: { lines: null, rows: 40, keep: 9, density: .75, size: 13, scroll: false },
    doc: 'A declared wall of micro text: volume made visible (every message, every copy, every rule at once).',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const lines = p.lines || (window.LYR || []).map(l => l.text).filter(Boolean); if (!lines.length) return;
      const y0 = MG().t + 54, [px, py] = p.x != null ? [+p.x, p.y != null ? +p.y : y0] : [MG().l, y0], col = p.color || x.ink([px, py, 900, H - py - 100]);
      o.globalAlpha = x.fade(t); D.type.wall(o, lines, px, py, t, x.t0, { rows: p.rows, keep: p.keep, density: p.density, size: p.size, scroll: p.scroll, color: col, alpha: (p.alpha ?? 1) * x.fade(t) });
    },
    example: { kind: 'mass', key: 'B', params: { lines: ['SEE YOU SOON', 'MISS YOU', 'CALL ME BACK'], rows: 30 } },
  });
})();
