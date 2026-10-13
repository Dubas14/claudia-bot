// kinetic.js — beat-locked lyric typography. Every token appears on its aligned sung time (window.LYR), with an entrance of
// ≤ 1/8 note; type breathes with the kick; the sung token carries the accent (karaoke) until its t1. The WORD syncs to
// the voice (never beat-snapped), the MOTION to the beat. Every token drawn calls KIN.mark(tk) — the lyric gate
// (slop render lyrics) renders each token at t0 + clamp((t1−t0)/2, .03, .12) and fails if it was not marked.
// Modes: subtitle · coverline · masthead (mastheadLine) · stack — all on the overlay ctx (crisp, never screened).
// ENGINE.type is the lyric-mode registry the default renderer and devices use (modes: subtitle, coverline, masthead,
// stack, mass, auto; aliases sub, cover, mast, caption); an unknown mode falls back to subtitle so no word is lost.
// Port notes (engine-core v1): default positions scale with H and widths follow the frame (portrait included);
// masthead / stack fit the frame width (a long word never runs off the frame); subtitle/coverline wrap to the width;
// a coverline that cannot hang beside the subject box (o.avoid) moves above it, its top clamped to M.t + size (it could
// rise off the frame).
'use strict';
const KIN = (() => {
  const L = () => window.LYR || [];
  // lyric QA: every token drawn this frame is marked by its aligned start; custom lyric code calls KIN.mark(tk)
  const DRAWN = window.DRAWN = new Set(), mark = tk => { if (tk && tk.t0 != null) DRAWN.add((+tk.t0).toFixed(2)); };
  const byLine = li => L().find(x => x.line === li);
  const byKind = (kind, t) => L().filter(x => x.kind === kind && t >= x.t0 - .3 && t <= x.t1 + 1.5);
  // local beat length at t (songs drift and accelerate: always from the beat map)
  function beatLen(t) { const B = SONG.beats; if (!B || B.length < 2) return BEAT(); const i = clamp(Math.floor(bpOf(t)), 0, B.length - 2); return B[i + 1] - B[i]; }
  const kick = (t, k = 9) => Math.exp(-frac(bpOf(t)) * k);             // sharp attack on each beat
  const kickBar = (t, k = 5) => { const B = SONG.downbeats; if (!B || !B.length) return kick(t); let i = 0; while (i < B.length - 1 && B[i + 1] <= t) i++; return t >= B[i] ? Math.exp(-(t - B[i]) / beatLen(t) * k / 4) : 0; };
  const entr = (t, t0) => clamp((t - t0) / (beatLen(t0) / 2));           // entrance progress over an 1/8 note (half a beat)
  // when a line leaves the screen: the next downbeat after its end, or when the next line starts if sooner
  function exitOf(ln) {
    const nx = L().filter(x => x.t0 > ln.t0 + .01).sort((a, b) => a.t0 - b.t0)[0];
    const D = SONG.downbeats || []; const db = D.find(d => d >= ln.t1 + .05) ?? ln.t1 + 1;
    return Math.min(db, nx ? nx.t0 - .02 : 1e9, ln.t1 + 2.5);
  }
  // lines on screen at t (from just before their first word to their exit)
  const active = (t, kinds = ['lyric', 'adlib']) => L().filter(ln => kinds.includes(ln.kind || 'lyric') && ln.tokens && ln.tokens.length && t >= ln.t0 - .05 && t <= exitOf(ln) + .15);
  function setFont(ctx, size, fam, weight = 400, style = '') { ctx.font = `${style} ${weight} ${size}px ${fam}`.trim(); }
  // wrap tokens into lines no wider than maxW (token widths measured with a given letterSpacing)
  function layout(ctx, toks, maxW, gap) {
    const rows = [[]]; let x = 0;
    for (const tk of toks) { const w = ctx.measureText(tk.txt).width;
      if (x > 0 && x + w > maxW) { rows.push([]); x = 0; }
      rows[rows.length - 1].push({ tk, x, w }); x += w + gap; }
    return rows;
  }
  const colFor = (tk, t, o) => (tk.st === 'accent' || (o.karaoke !== false && t >= tk.t0 && t < tk.t1 + .05)) ? (o.accent || INK.accent) : (o.color || INK.white);
  const yAt = px => Math.round(H * px / 1080);                          // a 1080-line design position at this frame height
  const fullW = () => W - M.l - M.r;

  // ---- subtitle: the plain line on the chrome baseline, word-by-word, mask-wipe up, karaoke fill ----
  function subtitle(ctx, ln, t, o = {}) {
    if (!ln) return; const out = o.until ?? exitOf(ln); if (t < ln.t0 - .05 || t > out + .15) return;
    const size = o.size || 40, x0 = o.x ?? M.l, y0 = o.y ?? (H - M.b), gap = size * .28;
    setFont(ctx, size, o.family || F.grotesk, o.weight || 400); ctx.textBaseline = 'alphabetic';
    const rows = layout(ctx, ln.tokens, o.w || (PORTRAIT ? fullW() : W * .62), gap), lh = size * 1.12, fade = 1 - seg(t, out, out + .15);
    const top = y0 - (rows.length - 1) * lh;
    // micro label above: line index + timecode, the lyric-sheet reference
    if (o.label !== false) { ctx.globalAlpha = .75 * fade; setFont(ctx, 12, F.mono, 500); ctx.fillStyle = o.color || INK.white;
      tracked(ctx, `${(ln.kind || 'lyric') === 'lyric' ? 'L' + String(ln.line).padStart(2, '0') : String(ln.kind).toUpperCase()} · ${tc(ln.t0)}`, x0, top - size * 1.05, .08);
      setFont(ctx, size, o.family || F.grotesk, o.weight || 400); }
    rows.forEach((r, ri) => r.forEach(({ tk, x, w }) => {
      const e = entr(t, tk.t0); if (e <= 0) return; mark(tk);
      const y = top + ri * lh;
      ctx.save(); ctx.beginPath(); ctx.rect(x0 + x - 2, y - size * 1.05, w + 4, size * 1.35); ctx.clip();
      ctx.globalAlpha = fade; ctx.fillStyle = colFor(tk, t, o);
      ctx.fillText(tk.txt, x0 + x, y + (1 - easeOut(e)) * size * .9);
      ctx.restore();
      if (tk.st === 'strike') strikeOn(ctx, x0 + x, y - size * .32, w, t, tk.t1, o.accent || INK.accent);
    }));
    ctx.globalAlpha = 1;
  }
  // ---- coverline: the editorial lockup beside the subject; tracking collapse on entry, kick breathing, typed micro rows ----
  function coverline(ctx, ln, t, o = {}) {
    if (!ln) return; const out = o.until ?? exitOf(ln); if (t < ln.t0 - .05 || t > out + .2) return;
    const size = o.size || 76, gap = size * .26, fam = o.family || F.grotesk, wt = o.weight || 700;
    let x0 = o.x ?? M.l, y0 = o.y ?? yAt(640);
    const fade = 1 - seg(t, out, out + .2), pk = 1 + (o.breathe ?? .014) * kick(t);
    setFont(ctx, size, fam, wt); ctx.letterSpacing = `${-.03 * size}px`; ctx.textBaseline = 'alphabetic';
    const rows = layout(ctx, ln.tokens, o.w || (PORTRAIT ? fullW() : W * .42), gap), lh = size * 1.0;
    // avoid the subject: if the block would cross its box (screen px [x,y,w,h]), hang it from the other side's margin
    if (o.avoid) { const bw = Math.max(...rows.map(r => { const l = r[r.length - 1]; return l ? l.x + l.w : 0; })), bx0 = x0, bx1 = x0 + Math.max(bw, o.ruleW || 0);
      const [ax, ay, aw] = o.avoid, over = bx1 > ax - 40 && bx0 < ax + aw + 40;
      if (over) { const leftRoom = ax - 40 - M.l, rightRoom = W - M.r - (ax + aw + 40);
        x0 = rightRoom >= leftRoom ? Math.max(ax + aw + 60, W - M.r - bw) : M.l;
        if (rightRoom < bw && leftRoom < bw) y0 = Math.max(M.t + size, Math.min(y0, ay - 40)); } }
    ctx.save(); ctx.translate(x0, y0); ctx.scale(pk, pk);
    rows.forEach((r, ri) => r.forEach(({ tk, x, w }) => {
      const e = entr(t, tk.t0); if (e <= 0) return; mark(tk);
      const sp = lerp(.35, -.03, expoOut(e)) * size;
      ctx.letterSpacing = `${sp}px`; ctx.globalAlpha = fade * clamp(e * 2);
      const flash = t - tk.t0 < 1 / FPS;                                  // 1-frame accent flash on entry
      ctx.fillStyle = flash ? (o.accent || INK.accent) : colFor(tk, t, o);
      ctx.fillText(tk.txt, x, ri * lh);
      if (tk.st === 'strike') strikeOn(ctx, x, ri * lh - size * .32, w, t, tk.t1, o.accent || INK.accent);
    }));
    ctx.letterSpacing = '0px'; ctx.restore(); ctx.globalAlpha = 1;
    // hairline that draws on the line's first beat, then micro rows typed on 16ths
    const blockH = rows.length * lh, hy = y0 + blockH - lh + size * .42, hw = o.ruleW || Math.min(PORTRAIT ? fullW() : W * .42, size * 7.2);
    const hk = easeOut(seg(t, ln.t0, ln.t0 + beatLen(ln.t0)));
    ctx.globalAlpha = fade; hair(ctx, x0, hy, x0 + hw * hk, hy, o.color || INK.white, 1.2);
    const micro = (o.micro || []).filter(Boolean);
    if (micro.length) typeRows(ctx, micro, x0, hy + 12, t, ln.t0 + beatLen(ln.t0) * .5, { color: o.color, fade, cps: o.cps });
    ctx.globalAlpha = 1;
  }
  // ---- masthead: one giant word per token, hard cut on its time, 1-frame accent block, slow scale drift ----
  function masthead(ctx, tk, t, o = {}) {
    const t1 = o.until ?? tk.t1 + (o.hold ?? .15); if (t < tk.t0 || t > t1) return; mark(tk);
    const fam = o.family || F.display, wt = o.weight || 500, x = o.x ?? M.l, y = o.y ?? yAt(700);
    let size = o.size || 300;
    const age = t - tk.t0, first = age < 1 / FPS + 1e-4;
    const txt = o.upper === false ? tk.txt : String(tk.txt).toUpperCase();
    setFont(ctx, size, fam, wt); ctx.letterSpacing = `${(o.track ?? -.02) * size}px`; ctx.textBaseline = 'alphabetic';
    let w = ctx.measureText(txt).width;
    // fit the frame: a word never runs off the edge (portrait, long words); o.fit = max width px (false: off)
    const room = o.fit === false ? 1e9 : (o.fit || (o.align === 'center' ? fullW() : o.align === 'right' ? x - M.l : W - M.r - x));
    if (w > room && room > 20) { size *= room / w; setFont(ctx, size, fam, wt); ctx.letterSpacing = `${(o.track ?? -.02) * size}px`; w = ctx.measureText(txt).width; }
    const ax = o.align === 'right' ? x - w : o.align === 'center' ? x - w / 2 : x, s = 1 + (o.drift ?? .03) * age / (t1 - tk.t0 + .01);
    ctx.save(); ctx.translate(ax + w / 2, y - size * .35); ctx.scale(s * (o.stretch || 1), s); ctx.translate(-(ax + w / 2), -(y - size * .35));
    if (first && o.flash !== false) { ctx.fillStyle = o.accent || INK.accent; ctx.fillRect(ax - size * .06, y - size * .82, w + size * .12, size * .95); ctx.fillStyle = o.bg || INK.ink; }
    else ctx.fillStyle = tk.st === 'accent' ? (o.accent || INK.accent) : (o.color || INK.white);
    if (o.invert) ctx.globalCompositeOperation = 'difference';
    ctx.fillText(txt, ax, y); ctx.restore(); ctx.letterSpacing = '0px';
  }
  // masthead over a whole line: each token cuts in on its own time, replacing the previous one
  function mastheadLine(ctx, ln, t, o = {}) {
    if (!ln) return; const toks = ln.tokens.filter(x => x.t0 <= t); if (!toks.length) return;
    const tk = toks[toks.length - 1], i = ln.tokens.indexOf(tk), nx = ln.tokens[i + 1];
    masthead(ctx, tk, t, { ...o, until: nx ? nx.t0 : (o.until ?? exitOf(ln)) });
  }
  // ---- stack: the line assembles as a left-aligned vertical stack, each token a new row in rising size ----
  function stack(ctx, ln, t, o = {}) {
    if (!ln) return; const out = o.until ?? exitOf(ln); if (t < ln.t0 - .05 || t > out + .15) return;
    const x0 = o.x ?? M.l, y0 = o.y ?? (PORTRAIT ? M.t + 40 : yAt(170)), base = o.size || 120, fam = o.family || F.display, wt = o.weight || 500;
    let y = y0; const fade = 1 - seg(t, out, out + .15), pk = 1 + (o.breathe ?? .02) * kick(t), room = o.fit || (W - M.r - x0);
    ln.tokens.forEach((tk, i) => {
      let size = base * (o.grow ? (1 + i * .08) : 1);
      const txt = o.upper === false ? tk.txt : String(tk.txt).toUpperCase();
      setFont(ctx, size, fam, wt); ctx.letterSpacing = `${-.02 * size}px`;
      const w = ctx.measureText(txt).width * pk; if (w > room && room > 20) size *= room / w;    // fit the frame width
      y += size * .92;
      const e = entr(t, tk.t0); if (e <= 0) return; mark(tk);
      setFont(ctx, size, fam, wt); ctx.letterSpacing = `${-.02 * size}px`; ctx.textBaseline = 'alphabetic';
      ctx.save(); ctx.globalAlpha = fade; ctx.translate(x0, y); ctx.scale(pk, pk);
      ctx.beginPath(); ctx.rect(-4, -size * .95, W, size * 1.15); ctx.clip();
      ctx.fillStyle = colFor(tk, t, o); ctx.fillText(txt, 0, (1 - expoOut(e)) * size);
      ctx.restore(); ctx.letterSpacing = '0px';
    });
    ctx.globalAlpha = 1;
  }
  // ---- helpers ----
  function strikeOn(ctx, x, y, w, t, t1, col) {        // the strike line draws across on the word's end time
    const k = easeOut(seg(t, t1, t1 + beatLen(t1) * .5)); if (k <= 0) return;
    ctx.save(); ctx.fillStyle = col; ctx.fillRect(x - 4, y - 3, (w + 8) * k, 6); ctx.restore();
  }
  // mono micro rows, typed at o.cps characters per 1/16 note (default 1; 3 reads well on short shots)
  function typeRows(ctx, rows, x, y, t, t0, o = {}) {
    const cps = (o.cps || 1) * 4 / beatLen(t0); setFont(ctx, o.size || 13, F.mono, 500); ctx.textBaseline = 'top'; ctx.fillStyle = o.color || INK.white;
    let budget = Math.floor((t - t0) * cps); if (budget <= 0) return;
    rows.forEach((r, i) => { const s = String(r).toUpperCase(); const n = Math.min(s.length, budget); budget -= s.length; if (n <= 0) return;
      ctx.globalAlpha = (o.fade ?? 1) * (i % 2 ? .8 : 1); tracked(ctx, s.slice(0, n) + (n < s.length && frac(t * 8) < .5 ? '▌' : ''), x, y + i * 19, .06); });
    ctx.globalAlpha = 1;
  }
  const tc = s => { s = Math.max(0, s); const m = Math.floor(s / 60), ss = Math.floor(s % 60), f = Math.floor(frac(s) * FPS); return `${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}:${String(f).padStart(2, '0')}`; };
  return { byLine, byKind, active, exitOf, subtitle, coverline, masthead, mastheadLine, stack, typeRows, kick, kickBar, beatLen, entr, tc, mark, layout };
})();

// ---- the lyric-mode registry: fn(o, ln, t, opts, env). Every mode must call KIN.mark(tk) for each token it draws. ----
ENGINE.mark = KIN.mark;
ENGINE.type = (() => {
  const modes = {
    subtitle: (o, ln, t, opts) => KIN.subtitle(o, ln, t, opts),
    coverline: (o, ln, t, opts) => KIN.coverline(o, ln, t, opts),
    masthead: (o, ln, t, opts) => KIN.mastheadLine(o, ln, t, Object.assign({ size: 250 }, opts)),
    stack: (o, ln, t, opts) => KIN.stack(o, ln, t, opts),
    // a declared wall of every lyric line flickering on eighths, with this line on top word by word (no word is lost)
    mass: (o, ln, t, opts, env = {}) => {
      const lines = (window.LYR || []).map(l => l.text).filter(Boolean), t0 = env.t0 ?? (ln ? ln.t0 : t);
      mass(o, lines, M.l, opts.y0 ?? Math.max(M.t + 54, Math.round(H * .1)), t, t0, { rows: opts.rows || Math.floor((H - M.t - M.b - 120) / 19), keep: opts.keep ?? 9, color: opts.color, density: opts.density });
      if (ln) KIN.subtitle(o, ln, t, opts);
    },
    // every line on screen at t, as subtitles (the "never lose a word" layer)
    auto: (o, ln, t, opts) => { KIN.active(t, ['lyric']).forEach(l => KIN.subtitle(o, l, t, opts)); },
  };
  const alias = { sub: 'subtitle', subtitles: 'subtitle', caption: 'subtitle', cover: 'coverline', mast: 'masthead', mastheadline: 'masthead',
    masthead_line: 'masthead', stacked: 'stack', wall: 'mass' };
  const warned = new Set();
  const norm = m => { const k = String(m || 'subtitle').toLowerCase(); return modes[k] ? k : (alias[k] || k); };
  return {
    modes,
    register(mode, fn) { if (typeof fn !== 'function') throw new Error('ENGINE.type.register: fn must be a function'); modes[String(mode).toLowerCase()] = fn; },
    draw(mode, o, ln, t, opts = {}, env = {}) {
      const k = norm(mode);
      if (!modes[k]) { if (!warned.has(k)) { warned.add(k); console.warn(`[engine] unknown lyric mode '${mode}' — drawn as subtitle`); } return modes.subtitle(o, ln, t, opts, env); }
      return modes[k](o, ln, t, opts, env);
    },
  };
})();
