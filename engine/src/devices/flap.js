// devices/flap.js — the split-flap board: rows of cells that flip from old to new glyphs with the real mechanics (the
// top half of the old glyph folds down while the new top is revealed, then the bottom lands), staggered left to right;
// and the full departures board (a label column and a status column, each row flipping on its own time).
// Port of the engine's flapBoard / departures (chrome.js). Intentional changes: the board restores textAlign/textBaseline
// (the source leaked textAlign = 'center' into later draws); the title and row words are params (no project strings);
// rows flip on time specs (a word, a beat, a hit) instead of hand-typed seconds.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.flap) return;
  const C = D.C, TY = D.TY;
  const FLAP_CHARS = ' ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,:-/%$+×!?';
  function board(g, x, y, cells, text, prev, tFlip, t, o = {}) {
    const cw = o.cw || 40, ch = o.ch || 62, gap = o.gap ?? 4, fg = o.fg || C.light, bg = o.bg || '#1a1b1d', acc = o.accent;
    const size = ch * .78, spin = o.spin ?? 6;
    const T = String(text).toUpperCase().padEnd(cells).slice(0, cells), P = String(prev ?? '').toUpperCase().padEnd(cells).slice(0, cells);
    g.save(); D.font(g, size, TY().tech, 400); g.textBaseline = 'middle'; g.textAlign = 'center';
    for (let i = 0; i < cells; i++) {
      const cx = x + i * (cw + gap), start = tFlip + i * (o.stagger ?? .025) + hash(i * 3.1) * .04;
      const p = seg(t, start, start + (o.dur ?? .38)), changed = T[i] !== P[i];
      let a = P[i], b2 = T[i], k = 1;
      if (changed && p < 1) { const s = p * spin, n = Math.floor(s); k = s - n;
        const idx = j => FLAP_CHARS[(Math.max(0, FLAP_CHARS.indexOf(P[i])) + j * 7 + 1) % FLAP_CHARS.length];
        a = n === 0 ? P[i] : idx(n); b2 = n >= spin - 1 ? T[i] : idx(n + 1); }
      else { a = b2 = T[i]; k = 1; }
      g.fillStyle = bg; g.fillRect(cx, y, cw, ch);
      const cy = y + ch / 2, col = acc && o.accentCells && o.accentCells.includes(i) ? acc : fg;
      const half = (gl, top, sy) => { g.save(); g.beginPath(); top ? g.rect(cx, y, cw, ch / 2) : g.rect(cx, cy, cw, ch / 2); g.clip();
        g.translate(cx + cw / 2, cy); g.scale(1, sy); g.fillStyle = col; g.fillText(gl, 0, size * .04); g.restore(); };
      half(b2, true, 1); half(k < .5 ? a : b2, false, 1);
      if (k < 1) { if (k < .5) { g.fillStyle = bg; g.fillRect(cx, y + ch / 2 * (2 * k), cw, ch / 2 * (1 - 2 * k)); half(a, true, 1 - 2 * k); } else half(b2, false, 2 * k - 1); }
      g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(cx, cy - 1, cw, 2); g.fillStyle = 'rgba(255,255,255,.04)'; g.fillRect(cx, y, cw, ch / 2);
    }
    g.restore();
    return (cw + gap) * cells - gap;
  }
  D.flapBoard = board;

  // ---- flap: rows of cells; each row {text, prev, at (time spec; default the start + half a beat per row), accent}
  D.register('flap', {
    role: 'hero', alias: ['splitflap', 'split-flap', 'flapboard', 'countdown'], typeSize: p => +p.ch * .78, capType: (p, k) => { p.cw *= k; p.ch *= k; },
    defaults: { rows: [{ text: 'ON TIME', prev: 'DELAYED' }], cells: null, cw: 40, ch: 62, gap: 4, spin: 6, label: '', sub: '' },
    doc: 'A split-flap board: a status, count or headline that flips to its new value on the word/beat (a countdown, a verdict).',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const cells = p.cells || Math.max(...p.rows.map(r => Math.max(String(r.text).length, String(r.prev || '').length)));
      const w = (p.cw + p.gap) * cells - p.gap, rh = p.ch + 12, h = p.rows.length * rh + (p.label ? 24 : 0) + (p.sub ? 22 : 0);
      const [px, py] = x.place(w, h), B = D.bl(x.t0), ink = p.color || x.ink([px, py, w, h]); let y = py + (p.label ? 24 : 0);
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t);
      if (p.label) { D.font(o, 13, TY().mono, 500); o.fillStyle = ink; o.textBaseline = 'top'; D.tracked(o, String(p.label).toUpperCase(), px, py, .1); }
      p.rows.forEach((r, i) => { const at = r.at != null ? D.time(r.at, x.sh, x.t0) : x.t0 + i * B / 2;
        board(o, px, y, cells, r.text, r.prev ?? '', at, t, { cw: p.cw, ch: p.ch, gap: p.gap, spin: p.spin, bg: p.bg, fg: p.fg, accent: r.accent ? x.acc() : null, accentCells: r.accent ? [...Array(cells).keys()] : null });
        y += rh; });
      if (p.sub) { D.font(o, 12, TY().mono, 400); o.fillStyle = ink; o.textBaseline = 'top'; o.globalAlpha *= .8; D.tracked(o, String(p.sub).toUpperCase(), px, y, .08); }
    },
    example: { kind: 'flap', anchor: { slot: 'top-left' }, key: 'W', params: { label: 'PLATFORM 2', rows: [{ text: 'DELAYED', prev: 'ON TIME', accent: true }], sub: 'LAST TRAIN' } },
  });

  // ---- departures: the full board — rows of {label, value, prev, flip (time spec), accent, sub} under a header strip
  D.register('departures', {
    role: 'hero', alias: ['board', 'flap.board'], typeSize: p => +p.ch * .78, capType: (p, k) => { p.cw *= k; p.ch *= k; },
    defaults: { title: 'DEPARTURES', status: 'STATUS', rows: [{ label: 'NEXT', value: 'BOARDING', prev: 'ON TIME' }], cw: 44, ch: 70, labelCells: 18, valueCells: 9 },
    doc: 'A departures board: a list of items whose statuses flip in turn (a schedule, a leaderboard, a roll call).',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const cw = p.cw, ch = p.ch, lc = p.labelCells, vc = p.valueCells, rowH = ch + 46, lw = lc * (cw * .62 + 3) + 30;
      const w = lw + vc * (cw + 5), h = p.rows.length * rowH + 50, [px, py0] = x.place(w, h), py = py0 + 42, B = D.bl(x.t0), ink = p.color || x.ink([px, py0, w, h]);
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); D.font(o, 14, TY().mono, 500); o.fillStyle = ink; o.textBaseline = 'top';
      D.tracked(o, String(p.title).toUpperCase(), px, py - 42, .1); D.tracked(o, String(p.status).toUpperCase(), px + lw, py - 42, .1); D.hair(o, px, py - 16, px + w, py - 16, ink, 1.2);
      p.rows.forEach((r, i) => { const y = py + i * rowH, lab = String(r.label || '').toUpperCase(), at = r.flip != null ? D.time(r.flip, x.sh, x.t0) : x.t0 + i * B / 2;
        board(o, px, y, lc, lab, r.prevLabel ?? lab, r.labelFlip != null ? D.time(r.labelFlip, x.sh, -1) : -1, t, { cw: cw * .62, ch: ch * .62, gap: 3, bg: p.bg });
        board(o, px + lw, y - ch * .19, vc, String(r.value || ''), String(r.prev ?? ''), at, t, { cw, ch, gap: 5, bg: p.bg, accent: r.accent ? x.acc() : null, accentCells: r.accent ? [...Array(vc).keys()] : null, spin: r.spin ?? 8 });
        if (r.sub) { D.font(o, 12, TY().mono, 400); o.fillStyle = ink; o.globalAlpha = (p.alpha ?? 1) * x.fade(t) * .7; o.textBaseline = 'top'; D.tracked(o, String(r.sub).toUpperCase(), px, y + ch * .62 + 10, .08); o.globalAlpha = (p.alpha ?? 1) * x.fade(t); } });
    },
    example: { kind: 'departures', anchor: { slot: 'top-left' }, key: 'B', params: { title: 'LAST TRAINS',
      rows: [{ label: 'NORTH', value: 'BOARDING', prev: 'ON TIME' }, { label: 'SOUTH', value: 'CANCELLED', prev: 'ON TIME', accent: true, flip: { beats: 1 } }] } },
  });
})();
