// devices/flash.js — full-frame flashes (the hard black-and-white frames of the "Mast language", on the beat, in theme
// only) and the spark (an irregular multi-ray burst: the accent mark, a bloom on kicks).
// The flash rule is enforced by the default renderer: ≤ 3 full-frame flashes in any second, across every flash device,
// flash-cut transition and stills-in-rhythm crop flash (DEV.flashPlan; WCAG 2.3.1 is checked again on the master by
// `slop render` flashcheck). A rejected flash simply does not fire.
// Ports: the second video's FLASH.mono / at / ok and CARD.flash (a pictogram card on a shout; its ISO pictograms were
// story-specific, so the card here takes a generic sign — prohibit / mandatory / warn / info — and a glyph), the first
// video's one-frame paper flash, the engine's GFX.spark / sparkPath. Intentional change: in portrait (9:16) the card sets
// the sign above the caption inside the UI-safe margins (the 16:9 layout's sign was taller than a portrait frame is wide).
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.flash) return;
  const C = D.C, TY = D.TY, FPS_ = () => (typeof FPS !== 'undefined' ? FPS : 24);

  // ---- the spark ✱ (path, and the beat-alive mark)
  function sparkPath(g, x, y, r, o = {}) {
    const n = o.rays || 12, rot = o.rot || 0, wr = r * (o.width ?? .075); g.beginPath();
    for (let i = 0; i < n; i++) { const a = rot + i / n * TAU, L = r * (o.even ? 1 : .72 + .28 * hash(i * 7.7 + (o.seed || 1))), cx = Math.cos(a), sy = Math.sin(a), qx = -sy * wr, qy = cx * wr;
      g.moveTo(x + qx * .6, y + qy * .6); g.lineTo(x + cx * L + qx, y + sy * L + qy); g.arc(x + cx * L, y + sy * L, wr, a + Math.PI / 2, a - Math.PI / 2, true); g.lineTo(x - qx * .6, y - qy * .6); g.closePath(); }
  }
  const backOutK = v => { const s = 1.7; return 1 + (s + 1) * Math.pow(v - 1, 3) + s * Math.pow(v - 1, 2); };
  D.sparkPath = sparkPath;
  D.spark = (g, x, y, r, t, o = {}) => {
    const k = o.t0 != null ? backOutK(clamp(D.bs(t, o.t0) / (o.inBeats || 1))) : 1; if (k <= 0) return;
    const bloom = 1 + (o.bloom ?? .12) * D.kick(t), rot = (o.spin ?? .08) * bpOf(t);
    g.save(); g.fillStyle = o.color || g.fillStyle; g.globalAlpha *= o.alpha ?? 1; sparkPath(g, x, y, Math.max(.01, r * k * bloom), Object.assign({}, o, { rot })); g.fill(); g.restore();
  };
  D.register('spark', {
    role: 'hero', alias: ['burst', 'star'],
    defaults: { r: 90, rays: 12, width: .075, bloom: .12, spin: .08, inBeats: 1, even: false, seed: 1 },
    doc: 'The spark: an irregular multi-ray burst that pops in (back-out) and blooms on every kick — an accent mark, a sign-off.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const [px, py] = x.place(p.r * 2, p.r * 2);
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); D.spark(o, px + p.r, py + p.r, p.r, t, { t0: x.t0, inBeats: p.inBeats, rays: p.rays, width: p.width, bloom: p.bloom, spin: p.spin, even: p.even, seed: p.seed, color: p.color || x.acc() });
    },
    example: { kind: 'spark', anchor: { slot: 'top-right' }, key: 'B', params: { r: 80 } },
  });

  // ---- the frame as black and white (inverted when invert), painted opaque onto the overlay (the source FLASH.mono)
  D.mono = (o, b, opts = {}) => { o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = 1;
    o.filter = `grayscale(1) contrast(${opts.contrast ?? 1.35})${opts.invert ? ' invert(1)' : ''}`; o.drawImage(b.canvas || b, 0, 0); o.filter = 'none'; o.restore(); };

  // ---- a generic safety-sign pictogram drawn in unit space at (x, y), diameter d; draw 0..1 = it draws itself
  function sign(g, x, y, d, o = {}) {
    const kind = o.sign || 'prohibit', dr = o.draw ?? 1, fg = o.fg || C.light, bg = o.bg || C.dark, ring = o.ring || fg;
    g.save(); g.translate(x, y); g.scale(d, d);
    if (kind === 'warn') {
      g.strokeStyle = ring; g.lineWidth = .06; g.lineJoin = 'round'; g.beginPath(); const k = clamp(dr * 1.6);
      g.moveTo(0, -.44); g.lineTo(.48 * k, -.44 + .82 * k); g.moveTo(0, -.44); g.lineTo(-.48 * k, -.44 + .82 * k); if (k >= 1) { g.moveTo(-.48, .38); g.lineTo(.48, .38); } g.stroke();
    } else {
      g.fillStyle = kind === 'mandatory' ? fg : bg; g.beginPath(); g.arc(0, 0, .5 * clamp(dr * 3), 0, TAU); g.fill();
      g.strokeStyle = ring; g.lineWidth = .07; g.beginPath(); g.arc(0, 0, .455, -Math.PI / 2, -Math.PI / 2 + TAU * clamp(dr * 1.6)); g.stroke();
    }
    g.restore();
    // the glyph, set in screen space (a sub-pixel font in a scaled context renders unreliably)
    if (dr > .2) { g.save(); g.globalAlpha *= clamp((dr - .2) * 3); g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillStyle = kind === 'mandatory' ? bg : fg; const gl = String(o.glyph ?? (kind === 'warn' ? '!' : kind === 'info' ? 'i' : '')).toUpperCase();
      if (gl) { let s = d * .34; D.font(g, s, TY().sign, 900); while (g.measureText(gl).width > d * .62 && s > 8) { s *= .9; D.font(g, s, TY().sign, 900); } g.fillText(gl, x, y + d * (kind === 'warn' ? .06 : .02)); }
      g.restore(); }
    if (kind === 'prohibit' && dr > .6) { const bk = clamp((dr - .6) / .4); g.save(); g.translate(x, y); g.scale(d, d); g.beginPath(); g.arc(0, 0, .41, 0, TAU); g.clip(); g.rotate(Math.PI / 4); g.fillStyle = o.bar || ring; g.fillRect(-.45, -.04, .9 * bk, .08); g.restore(); }
  }
  D.sign = sign;

  // ---- flash: kind 'mono' | 'invert' (the frame in black and white, inverted), 'paper' (a white flash), 'black', or 'card' (a
  // full-frame sign + caption on a shout). Starts: the instance start, plus every `every` beats until its end, plus `times`.
  // A card with `line` set IS the lyric: it shows the line's words so far as its caption and marks them for the lyric gate.
  const starts = inst => { const p = inst.p, out = [inst.t0];
    if (p.every) { for (let k = 1; k < 256; k++) { const s = D.tAtBeat(bpOf(inst.t0) + k * p.every); if (s >= inst.t1 - 1e-6) break; out.push(s); } }
    (p.times || []).forEach(s => out.push(D.time(s, inst.sh, null))); return out.filter(v => v != null && isFinite(v)); };
  const durOf = (p, s) => p.kind === 'card' ? (p.dur ?? D.bl(s) / 2) : (p.frames ?? 1) / FPS_();
  // is this flash instance drawing at t (one of its starts is live and the flash budget lets it fire)?
  D.flashFiring = (inst, t, ok) => starts(inst).some(s => t >= s - 1e-6 && t < s + durOf(inst.p, s) - 1e-6 && (!ok || ok(s)));
  D.register('flash', {
    role: 'flash', alias: ['flash.mono', 'flash.invert', 'flash.paper', 'flash.card', 'card.flash', 'card'],
    aliasParams: { 'flash.mono': { kind: 'mono' }, 'flash.invert': { kind: 'invert' }, 'flash.paper': { kind: 'paper' }, 'flash.card': { kind: 'card' }, 'card.flash': { kind: 'card' }, card: { kind: 'card' } },
    defaults: { kind: 'mono', frames: 1, every: null, times: [], sign: 'prohibit', glyph: '', caption: '', number: null, of: null, label: 'CARD', contrast: 1.35, line: null },
    dur: (p, t0) => p.every || (p.times && p.times.length) ? null : durOf(p, t0) + 1e-3,     // repeating flashes run to the shot's end
    flashes: inst => starts(inst).map(t => ({ t, pri: inst.p.kind === 'card' ? 3 : 2, src: inst.kind })),
    doc: 'A full-frame flash on the beat (black-and-white, inverted, paper, or a sign card on a shout). Max 3 per second.',
    draw(o, b, t, p, x) {
      const S = starts(x.inst).filter(s => t >= s - 1e-6 && t < s + durOf(p, s) - 1e-6 && (x.flashOk ? x.flashOk(s) : true)); if (!S.length) return;
      const s0 = S[S.length - 1];
      if (p.kind === 'mono' || p.kind === 'invert') { if (b) D.mono(o, b, { invert: p.kind === 'invert' || p.invert, contrast: p.contrast }); return; }
      if (p.kind === 'paper' || p.kind === 'black') { o.fillStyle = p.kind === 'paper' ? 'rgba(244,242,236,.85)' : 'rgba(0,0,0,.9)'; o.fillRect(0, 0, W, H); return; }
      // card
      const inv = !!p.invert, bg = inv ? C.light : C.dark, fg = inv ? C.dark : C.light, TYf = TY(), acc = x.acc();
      o.fillStyle = bg; o.fillRect(0, 0, W, H);
      const dr = clamp((t - s0) / Math.max(.05, durOf(p, s0) * .6)), port = H > W, Mg = D.MG();
      // 16:9: the sign left, the caption right (the kit's layout); portrait (9:16): the sign above, the caption under it,
      // inside the UI-safe margins
      const aw = W - Mg.l - Mg.r, pd = aw * .7;
      const L = port ? { sx: W / 2, sy: Mg.t + 110 + pd / 2, d: pd, nx: Mg.l, ny: Mg.t + 64, cx: Mg.l, cy: Mg.t + 150 + pd, cw: aw }
        : { sx: W * .31, sy: H * .5, d: H * .62, nx: W * .56, ny: H * .28, cx: W * .56, cy: H * .42, cw: W * .38 };
      sign(o, L.sx, L.sy, L.d, { sign: p.sign, glyph: p.glyph, draw: dr, fg, bg, ring: p.sign === 'prohibit' ? acc : fg, bar: acc });
      let cap = String(p.caption || '');
      if (p.line != null) { const ln = D.line(p.line); if (ln) { const toks = ln.tokens.filter(tk => tk.t0 <= t + 1e-6); toks.forEach(tk => D.has.KIN() && KIN.mark(tk)); if (toks.length) cap = toks.map(tk => tk.txt).join(' '); } }
      if (p.number != null) { o.save(); o.strokeStyle = fg; o.lineWidth = 4; o.beginPath(); o.arc(L.nx + 34, L.ny, 34, 0, TAU); o.stroke(); D.font(o, 42, TYf.sign, 900); o.fillStyle = fg; o.textAlign = 'center'; o.textBaseline = 'middle'; o.fillText(String(p.number), L.nx + 34, L.ny + 2); o.restore();
        D.font(o, 14, TYf.mono, 500); o.fillStyle = fg; o.globalAlpha = .7; o.textBaseline = 'middle'; D.tracked(o, `${String(p.label).toUpperCase()} · ${p.number}${p.of ? ' / ' + p.of : ''}`, L.nx + 84, L.ny, .14); o.globalAlpha = 1; }
      const parts = cap.toUpperCase().split(/,\s*/).filter(Boolean); if (!parts.length) return;
      let size = 150; const maxW = L.cw; parts.forEach(c => { D.font(o, 150, TYf.sign, 900); size = Math.min(size, 150 * maxW / Math.max(1, o.measureText(c).width)); });
      size = Math.max(40, size); D.font(o, size, TYf.sign, 900); o.fillStyle = fg; o.textBaseline = 'alphabetic';
      parts.forEach((c, i) => o.fillText(c + (i < parts.length - 1 ? ',' : ''), L.cx, L.cy + size * .7 + i * size * .92));
    },
    example: { kind: 'flash', key: 'W', params: { kind: 'card', sign: 'warn', glyph: '!', caption: 'MIND THE GAP', number: 1, of: 3, label: 'NOTICE' } },
  });

  D.alias('FLASH', { mono: D.mono, at: D.flashAt, ok: D.flashOk });
})();
