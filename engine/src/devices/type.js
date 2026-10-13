// devices/type.js — the lyric modes the default renderer draws from shots.json type[]: subtitle · coverline · masthead ·
// stack · mass. Every token appears ON its aligned t0 (never snapped to a beat: the motion syncs to the beat, the word to
// the voice), entrances ≤ 1/8 note, the line leaves at KIN.exitOf(line), every drawn token calls KIN.mark (the lyric gate,
// `slop render lyrics`, must print N/N). Adaptive ink (ink.js) picks the ink from the base under the block;
// occlusion (occ.js) tucks the block behind the subject — an edge, never a glyph (OCC's glyph guard: a glyph at a row's
// end may tuck up to OCC.TUCK of its ink, every other glyph the subject reaches is drawn whole, ON the subject). A block
// set behind takes its ink from the ground off the subject, and its lifted glyphs the ink that reads on the subject.
//
// Port of the second video's LY kit (sub · cover · mast · stack · auto) with the engine's KIN coverline's subject
// avoidance folded into cover. The default positions are the kit's (1920 × 1080: subtitle baseline H − 124, coverline
// first baseline 600, masthead baseline 760 at 300 px, stack top 150) — not the engine's older shots.js place() (masthead
// 250 px at 640, the rest at 560, 'bottom' at H − 220). Intentional changes:
//   - every default and every placement is derived from the margins (DEV.MG(): portrait has its own UI-safe margins) and
//     the frame height (y × H / 1080), so the 9:16 cut keeps the lyric above the platform UI: the subtitle baseline is
//     H − MG().b − 40 (= H − 124 in 16:9), 'top'/'bottom' placements hang from MG().t / MG().b;
//   - 'right': mastheads and stacks hang from the right margin (align right); a coverline / subtitle hangs from a column
//     at 56 % of the width in 16:9 (the kit's), from the right margin (align right) in portrait;
//   - rows wrap inside the margins from wherever the block starts (the kit wrapped at a fixed 1100 / 900 px, so a
//     right-hand block ran off the frame); a stack word wider than the safe area is set smaller;
//   - the lyric is never set under 40 px; the accent is the shot's (not a hard-coded orange);
//   - `mass` is the declared wall of micro rows PLUS the sung line as a subtitle (the source's mass() drew no tokens, so a
//     mass-only shot failed the lyric gate) and its flicker runs on the beat map's eighths (the source used a fixed-BPM
//     eighth); the wall starts under the top margin;
//   - ink defaults to one solid ink per block (split ink cut glyphs mid-word over busy texture), except that mastheads and
//     stacks take one ink per word, and a word straddling light and dark inverts in black and white (the second video's
//     Mast ink); a subtitle over mixed ground gives a word the other ink only where the line's ink drops under 3:1 over
//     it (wordInks: a wide dead band, so a word does not change ink on a camera drift);
//   - the coverline's micro rows type at one character a 16th (KIN.typeRows, as both sources did).
'use strict';
(() => {
  const D = window.DEV; if (!D || D.type) return;
  const C = D.C, beat = t => D.bl(t), MG = D.MG;
  const mark = tk => { if (D.has.KIN()) KIN.mark(tk); };
  const exitOf = ln => D.has.KIN() ? KIN.exitOf(ln) : ln.t1 + 1;

  function rowsOf(g, toks, maxW, gap, breaks = []) {
    const rows = [[]]; let x = 0;
    toks.forEach((tk, i) => { const w = g.measureText(tk.txt).width;
      if (rows[rows.length - 1].length && (breaks.includes(i) || x + w > maxW)) { rows.push([]); x = 0; }
      rows[rows.length - 1].push({ tk, x, w, i }); x += w + gap; });
    return rows;
  }
  const rowW = r => r.length ? r[r.length - 1].x + r[r.length - 1].w : 0;
  // ink: 'auto' (default: one solid ink picked from the base) | 'split' | 'difference' | 'mono' | 'light' | 'dark' | '#hex'
  function parseInk(v) {
    const s = String(v || 'auto').replace(/^solid:/, '');
    if (s === 'light' || s === 'white') return { color: C.light }; if (s === 'dark' || s === 'black') return { color: C.dark };
    if (/^#|^rgb/.test(s)) return { color: s };
    return { mode: ['split', 'difference', 'mono'].includes(s) ? s : 'auto' };
  }
  const solid = (col, acc) => ({ ink: col, accent: acc, dim: col === C.dark ? C.dimDark : C.dimLight, dark: col === C.dark });
  // the subject a block is set behind (OCC.mask through the entry's occ mode), or null: not behind, no matte/depth, or no
  // base to read inks from — cached on the call's opts, so sub's word inks and paintBlock read the same mask
  async function subjectOf(b, opts) {
    if (opts._mk !== undefined) return opts._mk;
    const m = opts.behind;
    return opts._mk = b && m && D.has.OCC() && D.has.AINK() && typeof m.matte === 'function' ? (await OCC.mask(m, opts.occ || {})) || null : null;
  }
  const inkOn = Y => AINK.contrast(AINK.Yhex(C.light), Y) >= AINK.contrast(AINK.Yhex(C.dark), Y) ? C.light : C.dark;
  const straddles = s => !!s && s.max - s.min > .35;
  async function paintBlock(o, b, box, paint, opts) {
    const acc = opts.accent || C.accent, ink = parseInk(opts.ink);
    const wrap = (g, pal) => paint(g, Object.assign({}, pal, { accent: acc }));
    const behind = opts.behind && D.has.OCC() && typeof opts.behind.matte === 'function';
    // set behind the subject: the type that stays off the subject reads the ground OFF it (the subject's part of the box is
    // cut away, so it says nothing about the ink), and a glyph the glyph guard lifts over the subject is drawn in the ink
    // that reads ON it (OCC's glyphs.over: a split along the matte — a light laptop on a dark stage takes dark glyphs on
    // the laptop, light ones on the stage, even within one word)
    const mk = behind && !ink.color && ink.mode === 'auto' ? await subjectOf(b, opts) : null;
    const off = mk ? OCC.ground(b, mk, box, false) : null, on = mk ? OCC.ground(b, mk, box, true) : null;
    const go = g => {
      if (ink.color) { g.save(); wrap(g, solid(ink.color, acc)); g.restore(); return; }
      if (off && !(opts.crossInk && straddles(off))) { g.save(); wrap(g, solid(inkOn(off.Y), acc)); g.restore(); return; }
      if (b && D.has.AINK()) {
        // big type (mast, stack) that crosses light and dark inverts in black and white instead of losing glyphs to one ink
        let mode = ink.mode; if (mode === 'auto' && opts.crossInk) { try { if (AINK.pick(b, box, { split: true }).mode === 'split') mode = opts.crossInk; } catch (e) { /* off-canvas */ } }
        AINK.fill(g, b, box, wrap, { mode, split: mode === 'split', accent: false, th: opts.th }); return; }
      g.save(); wrap(g, solid(opts.defInk || C.light, acc)); g.restore();
    };
    const onSub = (g, pal) => wrap(g, Object.assign({}, pal, { on: true }));        // pal.on: the pass drawn ON the subject
    const over = on ? g => {
      if (opts.crossInk && straddles(on)) { AINK.fill(g, b, box, onSub, { mode: opts.crossInk }); return; }
      g.save(); onSub(g, solid(inkOn(on.Y), acc)); g.restore();
    } : null;
    // tucked behind the subject: an edge may tuck, never a glyph (OCC's glyph guard lifts the occluder off the rest)
    if (behind) await OCC.behind(o, opts.behind, go, Object.assign({}, opts.occ || {}, { glyphs: { region: box, over } }));
    else go(o);
  }
  const colFor = (tk, t, pal, opts) => (tk.st === 'accent' || (opts.karaoke !== false && t >= tk.t0 && t < tk.t1 + .06)) ? pal.accent : pal.ink;
  // per-word ink for a subtitle over mixed ground: null when the line's box is even (one ink reads everywhere), else
  // box → the ink for a word there: the line's solid ink unless it falls under READ (3:1, large text) over the word and
  // the other ink reads better
  const READ = 3;
  // samp(box) → {Y, min, max} | null: the ground a word reads on (default AINK.sample: all of it; a line set behind the
  // subject samples the ground off — or on — the subject, OCC.ground)
  function wordInks(b, box, samp) {
    const S = samp || (bx => AINK.sample(b, bx)), s0 = S(box); if (!s0 || s0.max - s0.min < .1) return null;
    const Yl = AINK.Yhex(C.light), Yd = AINK.Yhex(C.dark), ink = AINK.contrast(Yl, s0.Y) >= AINK.contrast(Yd, s0.Y) ? C.light : C.dark;
    return bx => { const s = S(bx); if (!s) return ink;
      const cl = AINK.contrast(Yl, s.Y), cd = AINK.contrast(Yd, s.Y), mine = ink === C.light ? cl : cd, other = ink === C.light ? cd : cl;
      return mine >= READ || other <= mine ? ink : (ink === C.light ? C.dark : C.light); };
  }

  // SUB — the plain line, low left on the margin axis: words rise in over 1/16 on their times, the sung word in the accent.
  // opts: x, y (baseline of the last row), size (46), w (1100), breaks [token index], until, align, family, weight
  async function sub(o, b, ln, t, opts = {}) {
    if (!ln) return null; const out = opts.until ?? exitOf(ln); if (t < ln.t0 - .02 || t > out + .2) return null;
    const TY = D.TY(), size = Math.max(40, opts.size || 46), fam = opts.family || TY.grot, wt = opts.weight || 700, tr = (opts.track ?? -.012) * size;
    const x0 = opts.x ?? MG().l, yb = opts.y ?? DEF.sub().y;
    D.font(o, size, fam, wt); o.letterSpacing = `${tr}px`; const rows = rowsOf(o, ln.tokens, room(x0, opts.align, opts.w || 1100), size * .26, opts.breaks); o.letterSpacing = '0px';
    const lh = size * 1.12, top = yb - (rows.length - 1) * lh, bw = Math.max(...rows.map(rowW));
    const ax = opts.align === 'right' ? x0 - bw : opts.align === 'center' ? x0 - bw / 2 : x0;
    const box = [ax - 6, top - size * .92, bw + 12, (rows.length - 1) * lh + size * 1.22], fade = 1 - seg(t, out, out + .2);
    if (opts.measure) return box;                                              // (measure: the block's box, nothing drawn)
    // a line over mixed ground (a white wall and a black coat) keeps the line's own ink on every word it reads on, and
    // gives a word the other ink only where the line's ink would not read over it (below 3:1 contrast). Frames are pure
    // functions of t, so a word's ink cannot be latched at its first frame; this wide dead band (the line's ink holds over
    // a word until it truly stops reading) is what keeps a word from changing ink as the camera drifts. An explicit `ink`
    // keeps one ink. A line set `behind` the subject reads the same way on each side of the matte: its words read the
    // ground OFF the subject, and the glyphs the glyph guard lifts over the subject are drawn in a second pass whose words
    // read the ground ON it (paintBlock; pal.on marks that pass)
    const ik = parseInk(opts.ink); let wordInk = null, wordInkOn = null;
    if (!ik.color && ik.mode === 'auto' && b && D.has.AINK()) {
      try {
        const mk = await subjectOf(b, opts);
        if (mk) { wordInk = wordInks(b, box, bx => OCC.ground(b, mk, bx, false)); wordInkOn = wordInks(b, box, bx => OCC.ground(b, mk, bx, true)); }
        else wordInk = wordInks(b, box);
      } catch (e) { wordInk = wordInkOn = null; }
    }
    const paint = (g, pal) => {
      D.font(g, size, fam, wt); g.letterSpacing = `${tr}px`; g.textBaseline = 'alphabetic';
      const wi = pal.on ? wordInkOn : wordInk;
      rows.forEach((r, ri) => r.forEach(({ tk, x, w }) => {
        if (t < tk.t0) return; mark(tk);
        const e = easeOut(clamp((t - tk.t0) / (opts.inDur ?? beat(tk.t0) / 4))), y = top + ri * lh;
        g.save(); g.beginPath(); g.rect(ax + x - 6, y - size * 1.02, w + 12, size * 1.34); g.clip();
        let col = colFor(tk, t, pal, opts); if (wi && col === pal.ink) { try { col = wi([ax + x - 2, y - size * .8, w + 4, size]); } catch (er) { /* off-canvas */ } }
        g.globalAlpha = fade; g.fillStyle = col; g.fillText(tk.txt, ax + x, y + (1 - e) * size * .6); g.restore();
      }));
      g.letterSpacing = '0px';
    };
    await paintBlock(o, b, box, paint, opts); return box;
  }

  // COVER — the editorial lockup: big grotesk hung from one axis, words collapse their tracking in on their times, the
  // block breathes on the kick, a micro kicker above and a hairline + typed micro rows below. Hangs from the other margin
  // when it would cross the subject (opts.avoid = the lead's screen box), as the engine's KIN.coverline did.
  // opts: x, y (baseline of the first row), size (84), w (900), breaks, kicker, micro [rows], breathe (.012), until, align
  async function cover(o, b, ln, t, opts = {}) {
    if (!ln) return null; const out = opts.until ?? exitOf(ln); if (t < ln.t0 - .02 || t > out + .25) return null;
    const TY = D.TY(), size = Math.max(40, opts.size || 84), fam = opts.family || TY.grot, wt = opts.weight || 700, tr = -.03 * size, lh = size * .98;
    let x0 = opts.x ?? MG().l, y0 = opts.y ?? DEF.cover().y;
    D.font(o, size, fam, wt); o.letterSpacing = `${tr}px`; const rows = rowsOf(o, ln.tokens, room(x0, opts.align, opts.w || 900), size * .25, opts.breaks); o.letterSpacing = '0px';
    const bw = Math.max(...rows.map(rowW));
    if (opts.avoid && opts.x == null) {
      const [axx, ayy, aw] = opts.avoid, bx1 = x0 + Math.max(bw, opts.ruleW || 0), over = bx1 > axx - 40 && x0 < axx + aw + 40;
      if (over) { const leftRoom = axx - 40 - MG().l, rightRoom = W - MG().r - (axx + aw + 40);
        x0 = rightRoom >= leftRoom ? Math.min(Math.max(axx + aw + 60, W - MG().r - bw), W - MG().r - bw) : MG().l;
        if (rightRoom < bw && leftRoom < bw) y0 = Math.max(MG().t + size + 40, Math.min(y0, ayy - 40)); }
    }
    const ax = opts.align === 'right' ? x0 - bw : opts.align === 'center' ? x0 - bw / 2 : x0, fade = 1 - seg(t, out, out + .25);
    if (opts.measure) {                // the whole lockup: the words at the top of their breath (a word enters tracked out a
      // little past its row), the kicker above, the rule and the micro rows below
      const pm = 1 + Math.abs(opts.breathe ?? .012); D.font(o, 13, TY.mono, 500);
      const kw = opts.kicker ? D.trackedW(o, String(opts.kicker).toUpperCase(), .14) : 0, mic = (opts.micro || []).slice(0, 3);
      const mw = mic.length ? Math.max(...mic.map(r => D.trackedW(o, String(r).toUpperCase(), .06))) : 0;
      const rw = Math.max(...rows.map(r => { const l = r[r.length - 1]; return l ? l.x + l.w + .15 * size * String(l.tk.txt).length : 0; })) * pm;
      const hy = y0 + (rows.length - 1) * lh + size * .34, top = Math.min(y0 - size * .95 * pm, opts.kicker ? y0 - size * .95 - 30 : 1e9);
      const bot = Math.max(y0 + ((rows.length - 1) * lh + size * .3) * pm, hy + 2, mic.length ? hy + 12 + 19 * mic.length : 0);
      const x1 = ax + Math.max(rw, opts.ruleW || Math.min(bw, 520), kw, mw) + 8;
      return [ax - 8, top, x1 - (ax - 8), bot - top];
    }
    const pk = 1 + (opts.breathe ?? .012) * D.pulse(t, 'kick', { tau: .14 });
    const box = [ax - 8, y0 - size * .95, bw + 16, (rows.length - 1) * lh + size * 1.25];
    const paint = (g, pal) => {
      g.save(); g.translate(ax, y0); g.scale(pk, pk); g.textBaseline = 'alphabetic';
      rows.forEach((r, ri) => r.forEach(({ tk, x }) => {
        if (t < tk.t0) return; mark(tk);
        const e = clamp((t - tk.t0) / (beat(tk.t0) / 2)); D.font(g, size, fam, wt);
        g.letterSpacing = `${lerp(.28, -.03, expoOut(e)) * size}px`; g.globalAlpha = fade * clamp(e * 3);
        g.fillStyle = t - tk.t0 < 1 / FPS && opts.flash !== false ? pal.accent : colFor(tk, t, pal, opts); g.fillText(tk.txt, x, ri * lh);
      }));
      g.restore(); g.letterSpacing = '0px';
      const bl = beat(ln.t0), yk = y0 - size * .95 - 12;
      if (opts.kicker) { D.font(g, 13, TY.mono, 500); g.fillStyle = pal.ink; g.globalAlpha = fade * .8 * clamp((t - ln.t0 + bl) / (bl / 2)); g.textBaseline = 'bottom'; D.tracked(g, String(opts.kicker).toUpperCase(), ax, yk, .14); }
      const hy = y0 + (rows.length - 1) * lh + size * .34, hw = opts.ruleW || Math.min(bw, 520), hk = easeOut(seg(t, ln.t0, ln.t0 + bl));
      g.globalAlpha = fade; D.hair(g, ax, hy, ax + hw * hk, hy, pal.ink, 1.2);
      if (opts.micro && opts.micro.length) D.typed(g, opts.micro, ax, hy + 12, t, ln.t0 + bl / 2, { color: pal.ink, alpha: fade, size: 13, per16: 1, max: 3 });   // KIN.typeRows: 1 char / 16th
      g.globalAlpha = 1;
    };
    const full = [box[0], box[1] - (opts.kicker ? 30 : 0), Math.max(box[2], 520), box[3] + (opts.micro ? 30 + 19 * opts.micro.length : 0) + (opts.kicker ? 30 : 0)];
    await paintBlock(o, b, full, paint, opts); return box;
  }

  // MAST — one word at a time in condensed black caps, hard cut on its time (each replaces the last), or accumulate: true
  // (the line builds across the frame). opts: x, y (baseline), size (300; shrinks to fit), align, flash ('block' default =
  // a 1-frame accent block behind the new word | false), until, track, karaoke (false)
  async function mast(o, b, ln, t, opts = {}) {
    if (!ln) return null; const toks = ln.tokens.filter(x => x.t0 <= t + 1e-6); if (!toks.length) return null;
    const out = opts.until ?? exitOf(ln); if (t > out + .02) return null;
    const TY = D.TY(), fam = opts.family || TY.sign, wt = opts.weight || 900, tr = (opts.track ?? -.005);
    const show = opts.accumulate ? toks : [toks[toks.length - 1]];
    const x0 = opts.x ?? MG().l, yb = opts.y ?? DEF.mast().y;
    let size = opts.size || 300;
    D.font(o, size, fam, wt); o.letterSpacing = `${tr * size}px`;
    const txt = tk => opts.upper === false ? tk.txt : tk.txt.toUpperCase();
    const gap = size * .2, widths = show.map(tk => o.measureText(txt(tk)).width), tot = widths.reduce((a, w) => a + w, 0) + gap * (show.length - 1);
    const maxW = Math.min(opts.fit || 1e9, room(x0, opts.align, 1e9));
    if (tot > maxW) size = Math.max(40, size * maxW / tot);
    D.font(o, size, fam, wt); o.letterSpacing = `${tr * size}px`;
    const ws = show.map(tk => o.measureText(txt(tk)).width), tw = ws.reduce((a, w) => a + w, 0) + size * .2 * (show.length - 1); o.letterSpacing = '0px';
    const ax = opts.align === 'right' ? x0 - tw : opts.align === 'center' ? x0 - tw / 2 : x0;
    const box = [ax - 10, yb - size * .78, tw + 20, size * .86];
    if (opts.measure) return box;
    const cur = toks[toks.length - 1], first = t - cur.t0 < 1 / FPS + 1e-4, flash = opts.flash ?? 'block';
    // one ink per word (a word straddling light and dark inverts in black and white; the others stay solid)
    let x = ax;
    for (let i = 0; i < show.length; i++) {
      const tk = show[i], wx = x, wbox = [wx - 10, yb - size * .78, ws[i] + 20, size * .86]; x += ws[i] + size * .2; mark(tk);
      const paint = (g, pal) => {
        D.font(g, size, fam, wt); g.letterSpacing = `${tr * size}px`; g.textBaseline = 'alphabetic';
        if (first && tk === cur && flash === 'block') { g.fillStyle = pal.accent; g.fillRect(wx - size * .04, yb - size * .76, ws[i] + size * .08, size * .84); g.fillStyle = pal.dark ? C.light : C.dark; }
        else g.fillStyle = tk.st === 'accent' ? pal.accent : (opts.karaoke && t < tk.t1 + .06 ? pal.accent : pal.ink);
        g.fillText(txt(tk), wx, yb); g.letterSpacing = '0px';
      };
      await paintBlock(o, b, wbox, paint, Object.assign({ crossInk: 'mono' }, opts));
    }
    return box;
  }

  // STACK — the line builds as a vertical stack, one word per row on its time; fit: every row set to the same width (a
  // justified column; sizes differ) or a fixed size. opts: x, y (top), size (150), fit (column px), lead (.86), until, upper
  async function stack(o, b, ln, t, opts = {}) {
    if (!ln) return null; const out = opts.until ?? exitOf(ln); if (t < ln.t0 - .02 || t > out + .2) return null;
    const TY = D.TY(), fam = opts.family || TY.sign, wt = opts.weight || 900, x0 = opts.x ?? MG().l, y0 = opts.y ?? DEF.stack().y, lead = opts.lead ?? .86;
    const txt = tk => opts.upper === false ? tk.txt : tk.txt.toUpperCase();
    const avail = room(x0, opts.align, 1e9), fit = opts.fit ? Math.min(opts.fit, avail) : null;
    let y = y0; const rows = ln.tokens.map(tk => { let size = opts.size || 150;
      D.font(o, 100, fam, wt); const w100 = Math.max(1, o.measureText(txt(tk)).width);
      if (fit) size = clamp(100 * fit / w100, 40, opts.maxSize || 420);
      else size = Math.max(40, Math.min(size, 100 * avail / w100));                 // a word wider than the safe area is set smaller
      y += size * lead; return { tk, size, y }; });
    // a stack taller than the frame scales down to fit between the margins
    const hgt = y - y0, space = H - MG().b - 40 - y0, k = hgt > space ? space / hgt : 1;
    if (k < 1) { y = y0; rows.forEach(r => { r.size = Math.max(40, r.size * k); y += r.size * lead; r.y = y; }); }
    const colW = fit || Math.min(900, avail), ax = opts.align === 'right' ? x0 - colW : opts.align === 'center' ? x0 - colW / 2 : x0;
    const box = [ax - 8, y0, colW + 16, y - y0 + 20], fade = 1 - seg(t, out, out + .2);
    if (opts.measure) {                                                        // the words' own extent (not the whole column)
      if (!rows.length) return box; let lx = 1e9, rx = -1e9;
      for (const { tk, size } of rows) { D.font(o, size, fam, wt); o.letterSpacing = `${-.005 * size}px`; const w = o.measureText(txt(tk)).width; o.letterSpacing = '0px';
        const xx = opts.align === 'right' ? x0 - w : opts.align === 'center' ? x0 - w / 2 : ax; lx = Math.min(lx, xx - 6); rx = Math.max(rx, xx + w + 6); }
      const top = y0 + rows[0].size * (lead - .8);
      return [lx, top, rx - lx, y + 20 - top];
    }
    // one ink per row (a row straddling light and dark inverts in black and white; the others stay solid)
    for (const { tk, size, y: ry } of rows) {
      if (t < tk.t0) continue; mark(tk);
      D.font(o, size, fam, wt); o.letterSpacing = `${-.005 * size}px`; const w = o.measureText(txt(tk)).width; o.letterSpacing = '0px';
      const xx = opts.align === 'right' ? x0 - w : opts.align === 'center' ? x0 - w / 2 : ax, rbox = [xx - 6, ry - size * .8, w + 12, size * .86];
      const paint = (g, pal) => {
        const e = clamp((t - tk.t0) / (beat(tk.t0) / 4));
        D.font(g, size, fam, wt); g.letterSpacing = `${-.005 * size}px`; g.textBaseline = 'alphabetic';
        g.save(); g.beginPath(); g.rect(xx - 6, ry - size * .8, W, size * .86); g.clip(); g.globalAlpha = fade;
        g.fillStyle = colFor(tk, t, pal, opts); g.fillText(txt(tk), xx, ry + (1 - expoOut(e)) * size * .8); g.restore(); g.letterSpacing = '0px';
      };
      await paintBlock(o, b, rbox, paint, Object.assign({ crossInk: 'mono' }, opts));
    }
    return box;
  }

  // the declared wall of micro text (the engine's mass(), on the beat map): rows flicker on eighths since t0, row `keep`
  // stays lit. lines: strings; o: {rows (40), size (13), density (.75), keep, scroll, color, alpha}
  function wall(g, lines, x, y, t, t0, o = {}) {
    if (!lines || !lines.length) return;
    const TY = D.TY(), size = o.size || 13, lh = size * 1.45, rows = Math.min(o.rows || 40, Math.floor((H - y - MG().b) / lh));
    D.font(g, size, o.family || TY.mono, 400); g.fillStyle = o.color || C.light; g.textBaseline = 'top';
    const e = Math.floor(D.bs(t, t0) * 2);                                  // eighths of the beat map (never a fixed BPM)
    for (let r = 0; r < rows; r++) {
      const on = hash2(r, e) < (o.density ?? .75) || r === o.keep; if (!on) continue;
      const ln = lines[(r + (o.scroll ? Math.max(0, e) : 0)) % lines.length];
      g.globalAlpha = (o.alpha ?? 1) * (r === o.keep ? 1 : lerp(.35, .9, hash2(r * 7, e)));
      D.tracked(g, String(ln).toUpperCase(), x, y + r * lh, .04);
    }
    g.globalAlpha = 1;
  }
  // MASS — the wall behind, the sung line on top as a subtitle (so every token lands on its time and reads)
  async function mass(o, b, ln, t, opts = {}) {
    if (!ln) return null; const out = opts.until ?? exitOf(ln); if (t < ln.t0 - .02 || t > out + .2) return null;
    if (opts.measure) return sub(o, b, ln, t, opts);                          // the block is the sung line (the wall is its ground)
    const lines = opts.lines || (window.LYR || []).map(l => l.text).filter(Boolean);
    const wy = opts.wallY ?? DEF.mass().y, ink = parseInk(opts.ink).color || (b && D.has.AINK() ? D.inkFor(b, [MG().l, wy, Math.min(900, W - MG().l - MG().r), H - wy - MG().b], null) : (opts.defInk || C.light));
    o.save(); wall(o, lines, opts.wallX ?? MG().l, wy, t, opts.t0 ?? ln.t0, { rows: opts.rows || 44, keep: opts.keep ?? 9, color: ink, alpha: (1 - seg(t, out, out + .2)) * .8 }); o.restore();
    return sub(o, b, ln, t, opts);
  }

  // AUTO — every lyric line active at t as a clean SUB (the default for a shot no type entry covers)
  async function auto(o, b, t, opts = {}) {
    let box = null; for (const ln of (window.LYR || [])) if (t >= ln.t0 - .02 && t <= exitOf(ln) + .2) box = await sub(o, b, ln, t, opts) || box; return box;
  }
  // the line active at t (the newest), or null
  const activeLine = t => { let cur = null; for (const ln of (window.LYR || [])) if (t >= ln.t0 - .02 && t <= exitOf(ln) + .2 && (!cur || ln.t0 > cur.t0)) cur = ln; return cur; };

  // a part of a line (tokens a..b, inclusive) — a masthead on one word of a coverline's line
  const part = (ln, a, b2) => { const n = ln.tokens.length, A = clamp(a < 0 ? n + a : a, 0, n - 1), B = clamp(b2 == null ? A : b2 < 0 ? n + b2 : b2, A, n - 1), toks = ln.tokens.slice(A, B + 1);
    return Object.assign({}, ln, { tokens: toks, t0: toks[0].t0, t1: toks[toks.length - 1].t1, part: [A, B] }); };

  // shots.json mode names → the functions (ARCHITECTURE §4.5 names first, the kit's short names accepted)
  const MODE = { subtitle: 'sub', sub: 'sub', caption: 'sub', coverline: 'cover', cover: 'cover', masthead: 'mast', mast: 'mast', mastheadline: 'mast',
    stack: 'stack', mass: 'mass', wall: 'mass' };
  const FN = { sub, cover, mast, stack, mass };
  // the defaults per mode, from the margins and the frame height (the kit's 1920 × 1080 values in 16:9)
  const yAt = px => Math.round(H * px / 1080), PORT = () => H > W;
  const DEF = { sub: () => ({ y: H - MG().b - 40 }), cover: () => ({ y: yAt(600) }), mast: () => ({ y: yAt(760) }), stack: () => ({ y: Math.max(yAt(150), MG().t + 20) }),
    mass: () => ({ y: MG().t + 54 }) };
  // the width a block starting at x0 (with this alignment) has before it would cross a margin
  function room(x0, align, want) {
    const Mg = MG(), r = align === 'right' ? x0 - Mg.l : align === 'center' ? 2 * Math.min(x0 - Mg.l, W - Mg.r - x0) : W - Mg.r - x0;
    return Math.max(120, Math.min(want, r));
  }
  // placement prose → coordinates: left (default) · right · center · top/upper · bottom/lower (see the header for 'right')
  function place(p, mode) {
    const s = String(p || '').toLowerCase(), o = {}, right = /right/.test(s), centre = /cent/.test(s) && !/left|right/.test(s), Mg = MG();
    if (mode === 'mast' || mode === 'stack' || PORT()) { if (right) { o.x = W - Mg.r; o.align = 'right'; } else if (centre) { o.x = W / 2; o.align = 'center'; } }
    else if (right) o.x = Math.round(W * .56); else if (centre) { o.x = W / 2; o.align = 'center'; }
    if (/top|upper/.test(s)) o.y = { mast: Mg.t + 274, stack: Mg.t + 64, sub: Mg.t + 204, cover: Mg.t + 194, mass: Mg.t + 204 }[mode];
    else if (/bottom|lower/.test(s)) o.y = { mast: H - Mg.b - 86, stack: H - Mg.b - 476, sub: H - Mg.b - 40, cover: H - Mg.b - 216, mass: H - Mg.b - 40 }[mode];
    return o;
  }
  // one shots.json type entry → its mode, drawn. en: {line, mode, placement, words: [a, b], x, y, size, w, align, ink, behind,
  // kicker, micro, breaks, accumulate, flash, karaoke, fit, until, lines (mass)}; X: the frame context (shots.js)
  const PASS = ['x', 'y', 'size', 'w', 'align', 'kicker', 'micro', 'breaks', 'accumulate', 'flash', 'karaoke', 'fit', 'maxSize', 'lead', 'upper', 'family', 'weight', 'track', 'ruleW', 'lines', 'rows', 'keep', 'breathe', 'th'];
  async function entry(o, b, en, t, X = {}) {
    const ln0 = D.line(en.line); if (!ln0 || !ln0.tokens || !ln0.tokens.length) return null;
    const ln = Array.isArray(en.words) ? part(ln0, en.words[0], en.words[1]) : ln0;
    const mode = MODE[String(en.mode || 'subtitle').toLowerCase()] || 'sub';
    const opts = Object.assign(place(en.placement, mode), { accent: X.accent, defInk: X.lightGround ? C.dark : C.light, ink: en.ink,
      avoid: X.lead || null, occ: { mode: en.behind === 'depth' ? 'depth' : en.behind === 'matte' ? 'matte' : 'auto' } });
    PASS.forEach(k => { if (en[k] != null) opts[k] = D.num(en[k]); });                  // "84" → 84 (hand-written JSON)
    if (X.measure) opts.measure = true;
    if (en.behind && X.m && !X.measure) opts.behind = X.m;
    if (en.until != null) opts.until = D.time(en.until, X.sh || ln0, undefined);
    else if (ln !== ln0) { const nxt = ln0.tokens[ln.part[1] + 1]; opts.until = nxt ? nxt.t0 - 1e-3 : exitOf(ln0); }
    return FN[mode](o, b, ln, t, opts);
  }
  // is a type entry on screen at t (its line's window, a part's own start, an explicit at/until)
  function entryWindow(en, sh) {
    const ln0 = D.line(en.line); if (!ln0 || !ln0.tokens || !ln0.tokens.length) return null;
    const ln = Array.isArray(en.words) ? part(ln0, en.words[0], en.words[1]) : ln0;
    // a part (words [a, b]) is on screen from its first word until the word after it starts (then the line's other entry
    // — a coverline, or the auto subtitle — carries the rest), or to the line's exit when it ends the line
    const nxt = ln.part ? ln0.tokens[ln.part[1] + 1] : null;
    const a = en.at != null ? D.time(en.at, sh, ln.t0) : ln.t0 - .02;
    const z = en.until != null ? D.time(en.until, sh, exitOf(ln0)) : nxt ? nxt.t0 - 1e-3 : exitOf(ln0) + .2;
    return [a, z, ln];
  }
  // where a lyric block will sit (an estimate from its mode, placement and the lead, so devices placed in 'auto' slots
  // stay off it): [x, y, w, h] screen px. pick: {en} (a type entry) or {auto: true} (the fallback subtitle)
  function region(pick, X = {}) {
    const Mg = MG(), Wd = W - Mg.l - Mg.r, yb = DEF.sub().y;
    if (!pick || pick.auto || !pick.en) return [Mg.l - 6, yb - 46 * 2.3, Math.min(1100, Wd), 46 * 2.6];
    const en = pick.en, mode = MODE[String(en.mode || 'subtitle').toLowerCase()] || 'sub', p = place(en.placement, mode);
    ['x', 'y', 'size', 'w', 'align', 'fit'].forEach(k => { if (en[k] != null) p[k] = en[k]; });
    const xa = (x0, w) => p.align === 'right' ? x0 - w : p.align === 'center' ? x0 - w / 2 : x0;
    if (mode === 'mass') { const y = p.y ?? DEF.mass().y; return [Mg.l, y - 10, Math.min(900, Wd), H - Mg.b - y + 10]; }
    if (mode === 'sub') { const sz = Math.max(40, p.size || 46), x0 = p.x ?? Mg.l, w = room(x0, p.align, p.w || 1100), y = p.y ?? yb; return [xa(x0, w), y - sz * 2.3, w, sz * 2.6]; }
    if (mode === 'mast') { const sz = p.size || 300, y = p.y ?? DEF.mast().y; return [Mg.l, y - sz * .8, Wd, sz * .9]; }
    if (mode === 'stack') { const y = p.y ?? DEF.stack().y, x0 = p.x ?? Mg.l, w = Math.min(p.fit || 900, room(x0, p.align, 1e9)); return [xa(x0, w), y, w, H - Mg.b - y]; }
    const sz = Math.max(40, p.size || 84); let x0 = p.x ?? Mg.l, y0 = p.y ?? DEF.cover().y; const w = room(x0, p.align, p.w || 900), bw = w * .75;   // cover
    if (X.lead && p.x == null) { const [ax, ay, aw] = X.lead; if (x0 + bw > ax - 40 && x0 < ax + aw + 40) { const lr = ax - 40 - Mg.l, rr = W - Mg.r - (ax + aw + 40);
      x0 = rr >= lr ? Math.min(Math.max(ax + aw + 60, W - Mg.r - bw), W - Mg.r - bw) : Mg.l; if (rr < bw && lr < bw) y0 = Math.max(Mg.t + sz + 40, Math.min(y0, ay - 40)); } }
    return [xa(x0, bw) - 8, y0 - sz - 40, bw + 16, sz * 2.2 + 100];
  }
  // the rect a lyric block covers over its whole time on screen (screen px), measured with the mode's own layout and
  // nothing drawn: the union of its boxes at each of its words' entrances (a masthead's words differ in width; the other
  // modes lay the whole line out at once). The default renderer keeps devices, CV labels and the chrome off it.
  // pick: {en, ln?} (a type entry) | {auto: true, ln} (the fallback subtitle); X: the frame context (a coverline steps
  // away from X.lead, as it does when drawn)
  let MC = null;
  async function measure(pick, X = {}) {
    if (!pick) return null;
    const w = pick.en ? entryWindow(pick.en, X.sh || { t0: -1e9, t1: 1e9 }) : null, ln = w ? w[2] : pick.ln;
    if (!ln || !ln.tokens || !ln.tokens.length) return null;
    MC = MC || D.mk(8, 8).getContext('2d'); MC.save();
    const add = (u, r) => !r ? u : !u ? r.slice(0, 4) : (() => { const x0 = Math.min(u[0], r[0]), y0 = Math.min(u[1], r[1]); return [x0, y0, Math.max(u[0] + u[2], r[0] + r[2]) - x0, Math.max(u[1] + u[3], r[1] + r[3]) - y0]; })();
    let u = null;
    try {
      const mx = Object.assign(Object.create(X), { measure: true });
      for (const tk of ln.tokens) { const tt = tk.t0 + 1e-3;
        const r = pick.en ? await entry(MC, null, pick.en, tt, mx) : await sub(MC, null, ln, tt, { measure: true }); u = add(u, r); }
    } finally { MC.restore(); MC.letterSpacing = '0px'; }
    return u;
  }
  // the lyric's type size for a pick (for the budget's "the lyric is the biggest type" check)
  function sizeOf(pick) {
    if (!pick || pick.auto || !pick.en) return 46;
    const en = pick.en, mode = MODE[String(en.mode || 'subtitle').toLowerCase()] || 'sub';
    return Math.max(40, +en.size || { sub: 46, cover: 84, mast: 300, stack: 150, mass: 46 }[mode]);
  }
  D.type = { sub, cover, mast, stack, mass, auto, wall, entry, entryWindow, activeLine, part, place, parseInk, region, measure, sizeOf, room, DEF, MODE, rowsOf, wordInks, READ };
  D.alias('LY', { sub, cover, mast, stack, auto, rowsOf });
})();
