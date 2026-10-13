// devices/_base.js — the device registry, the timing grammar (W/B/H/F/T), anchors, adaptive ink, the accent budget and
// the flash budget. Every device in engine/src/devices/*.js registers here; engine/src/shots.js (the default renderer)
// drives them from board/shots.json `devices[]`, and bespoke chapter code may call them directly:
//
//   await DEV.draw(o, b, DEV.instance({kind: 'cv.tag', anchor: {box: 'a face'}, params: {rows: ['LABEL']}, key: 'W'}, shot), t, X)
//
// Contract (ARCHITECTURE §4.5): a device instance is {kind, anchor, params, key: 'W'|'B'|'H'|'F'|'T', at?, until?}.
//   W  word times (a token's t0/t1 from window.LYR)          B  the beat map (bpOf / beatAt — never a fixed BPM)
//   H  track events (window.HITS via HIT.*)                  F  song seconds                T  take-time keyframes (EDL)
// Every device is a pure function of t (frames render in parallel and out of order): no Math.random, no Date, no state
// carried between frames. Memos hold only data derived from static media/data, keyed by name, never by frame.
//
// Ported from the shared engine's helpers and the second video's design kit (_kit.js); see engine/DEVICES.md for the
// catalogue. Intentional changes from the source: device labels/defaults are generic (no project strings); every
// beat-timed device reads the beat map (the source's mass() flickered on a fixed-BPM eighth); text state (textAlign,
// letterSpacing) is restored after every device (the source's flapBoard leaked textAlign = 'center').
// Operator safety (a weaker model writes shots.json by hand): numbers given as strings ("2") are read as numbers; params of
// the wrong shape are coerced to the shape the device expects (or its default) with a warning; a word that is not sung,
// or is sung outside the shot, is a warning (a device keyed to it starts at the shot start instead of never showing);
// every warning reaches `slop render info` (DEV.report → console '[devices] …' and ENGINE.info().deviceWarnings).
// Subject boxes: `slop edit export` writes no detection boxes, so 'lead' (and person / face labels) fall back to the
// shot's `subject_uv`, the plate's `subject_uv`, then the subject found in the depth map (treat.js DEV.subjectOf).
// Placement: a block never leaves the margins (portrait has its own); one too big for them is scaled down to fit. Nothing
// a device draws covers a lyric block: panels move off it (x.place), labels flip or drop (DEV.spot), CV strokes are clipped.
// Memory: plate-derived memos (depth slices, grids, thumbs) are kept for the last 3 plates only (an LRU).
'use strict';
(() => {
  const G = window, DEV = G.DEV = G.DEV || {};
  if (DEV._base) return;
  DEV._base = true; DEV.version = 1;
  const REG = DEV.REG = {}, ALIAS = DEV.ALIAS = {};

  // ---------------------------------------------------------------------------------------- engine access (lazy) --
  // Engine-core globals (core.js, kinetic.js, chrome.js, hits.js, ink.js, occ.js, media.js, gfx.js) are read at call
  // time; the opt-in modules are guarded so a page without them still renders.
  const has = DEV.has = {
    KIN: () => typeof KIN !== 'undefined',
    HIT: () => typeof HIT !== 'undefined' && !!G.HITS,
    CAM: () => typeof CAM !== 'undefined',
    AINK: () => typeof AINK !== 'undefined',
    OCC: () => typeof OCC !== 'undefined',
    GFX: () => typeof GFX !== 'undefined',
    MEDIA: () => typeof MEDIA !== 'undefined',
    SPECTRUM: () => !!G.SPECTRUM,
  };
  // colour tokens: white / near-black / one accent (the accent is per shot, default the engine's clay orange)
  const C = DEV.C = { light: '#F5F3EE', dark: '#0B0C0E', accent: '#D97757', paper: '#eeede8', ink: '#121212', night: '#0f1216',
    panel: 'rgba(11,12,14,.78)', panelSolid: '#15181c', line: 'rgba(245,243,238,.28)', dimLight: 'rgba(245,243,238,.62)', dimDark: 'rgba(11,12,14,.62)' };
  // type tokens, read from the engine's F at call time (OFL faces only; the page loads them)
  DEV.TY = () => {
    const f = (typeof F !== 'undefined' && F) || {};
    return { sign: f.sign || f.display || 'sans-serif', grot: f.grotesk || f.sans || 'sans-serif', mono: f.mono || 'monospace',
      tech: f.tech || f.mono || 'monospace', display: f.display || f.sign || 'sans-serif', serif: f.serif2 || f.serif || 'serif' };
  };
  DEV.font = (g, size, fam, wt = 400, style = '') => { g.font = `${style} ${wt} ${size}px ${fam}`.trim(); };
  DEV.tracked = (g, txt, x, y, em = 0, align = 'left') => {
    if (typeof tracked === 'function') { const w = tracked(g, txt, x, y, em, align); g.letterSpacing = '0px'; return w; }
    const size = parseFloat((g.font.match(/(\d+(\.\d+)?)px/) || [0, 13])[1]); g.letterSpacing = `${em * size}px`;
    const w = g.measureText(txt).width, x0 = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    g.textAlign = 'left'; g.fillText(txt, x0, y); g.letterSpacing = '0px'; return w;
  };
  DEV.hair = (g, x0, y0, x1, y1, col, w = 1.2) => { g.save(); g.strokeStyle = col; g.lineWidth = w; g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke(); g.restore(); };
  DEV.rr = (g, x, y, w, h, r) => { r = Math.max(0, Math.min(r, w / 2, h / 2)); g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); };
  const MG = DEV.MG = () => (typeof M !== 'undefined' && M) || (typeof ENGINE !== 'undefined' && ENGINE.M) || { l: 72, t: 56, r: 96, b: 84 };   // the margins (unequal on purpose; portrait-safe from the engine)

  // ----------------------------------------------------------------------------------------- the clock (beat map) --
  const bl = DEV.bl = t => has.KIN() ? KIN.beatLen(t) : (() => { const B = SONG.beats; if (!B || B.length < 2) return 60 / (SONG.bpm || 120);
    const i = clamp(Math.floor(bpOf(t)), 0, B.length - 2); return B[i + 1] - B[i]; })();
  DEV.bs = (t, t0) => bpOf(t) - bpOf(t0);                                     // beats since t0 (tempo-aware)
  // the song time of a (fractional) beat position: the inverse of bpOf, extrapolated past both ends of the map
  function tAtBeat(x) {
    const B = SONG.beats; if (!B || B.length < 2) return (SONG.offset || 0) + x * 60 / (SONG.bpm || 120);
    const n = B.length; if (x <= 0) return B[0] + x * (B[1] - B[0]);
    if (x >= n - 1) return B[n - 1] + (x - (n - 1)) * (B[n - 1] - B[n - 2]);
    const i = Math.floor(x); return lerp(B[i], B[i + 1], x - i);
  }
  DEV.tAtBeat = tAtBeat;
  DEV.beatAfter = (t, k = 0) => tAtBeat(Math.ceil(bpOf(t) - 1e-6) + k);      // the first beat at/after t, plus k beats
  DEV.kick = t => has.KIN() ? KIN.kick(t) : Math.exp(-frac(bpOf(t)) * 9);
  // a hit envelope: the track's events when window.HITS exists, else the beat
  DEV.pulse = (t, kind = 'kick', o = {}) => has.HIT() ? HIT.pulse(t, kind, o) : Math.exp(-frac(bpOf(t)) * bl(t) / (o.tau ?? .12));

  // ---------------------------------------------------------------------------------------------- the warnings --
  // DEV.report(msg): one console line per distinct problem ('[devices] …' — `slop render info` returns the page console) and
  // the list ENGINE.info().deviceWarnings returns. SINK: DEV.instance collects its timing problems here while it resolves.
  const REPORTED = new Set(); DEV.warnings = [];
  DEV.report = msg => { const s = String(msg); if (REPORTED.has(s)) return; REPORTED.add(s); if (DEV.warnings.length < 500) DEV.warnings.push(s); try { console.warn('[devices] ' + s); } catch (e) { /* no console */ } };
  let SINK = null;
  const miss = s => { if (SINK && !SINK.includes(s)) SINK.push(s); };
  // numbers that arrive as strings from hand-written JSON ("2", "1.5") → numbers; anything else unchanged
  const num = v => typeof v === 'string' && v.trim() !== '' && isFinite(+v) ? +v : v;
  const N = v => { const n = num(v); return typeof n === 'number' && isFinite(n) ? n : NaN; };
  DEV.num = num;
  const short = v => { const s = typeof v === 'string' ? v : JSON.stringify(v); return s && s.length > 48 ? s.slice(0, 45) + '…' : s; };
  DEV.short = short;

  // ------------------------------------------------------------------------------------------------- lyric access --
  const LYR = () => G.LYR || [];
  DEV.line = n => { const k = num(n); return LYR().find(l => l.line === k || l.line === n) || null; };
  const norm = s => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}%$+\-]/gu, '');
  DEV.norm = norm;
  // a token by [line, index] (negative index counts from the end) or by its text near the shot → {tk, inShot}
  // (inShot: the token is sung inside the shot's span; a text match prefers the earliest one inside the shot)
  function tokenInfo(spec, sh) {
    const inside = tk => !sh || (tk.t0 >= sh.t0 - .05 && tk.t0 < sh.t1 + .05);
    if (Array.isArray(spec)) { const ln = DEV.line(spec[0]); if (!ln || !ln.tokens.length) return { tk: null, why: `line ${short(spec[0])} has no sung words` };
      const i = N(spec[1] ?? 0) || 0, tk = ln.tokens[i < 0 ? ln.tokens.length + i : Math.min(i, ln.tokens.length - 1)] || null; return { tk, inShot: !!tk && inside(tk) }; }
    if (typeof spec === 'number') { const ln = DEV.line(spec), tk = ln && ln.tokens[0] || null; return tk ? { tk, inShot: inside(tk) } : { tk: null, why: `line ${short(spec)} has no sung words` }; }
    const want = norm(spec); if (!want) return { tk: null, why: 'an empty word' };
    const lo = sh ? sh.t0 - .05 : -1e9, hi = sh ? sh.t1 + .05 : 1e9;
    let best = null, any = null;                                            // the earliest match inside the shot, else the first anywhere
    for (const ln of LYR()) for (const tk of ln.tokens || []) {
      if (norm(tk.txt) !== want && !norm(tk.txt).startsWith(want)) continue;
      if (!any) any = tk;
      if (tk.t0 >= lo && tk.t0 < hi && (!best || tk.t0 < best.t0)) best = tk;
    }
    return best ? { tk: best, inShot: true } : any ? { tk: any, inShot: false } : { tk: null, why: `'${short(spec)}' is not a sung word (lyrics/display.txt → slop edit export)` };
  }
  function token(spec, sh) { const r = tokenInfo(spec, sh); if (!r.tk) miss(`word ${short(spec)}: ${r.why}`); return r.tk; }
  DEV.token = token; DEV.tokenInfo = tokenInfo;
  // the tokens sung inside a shot (its lines first, else any token whose t0 falls in the span)
  DEV.shotTokens = sh => { const out = []; for (const ln of LYR()) for (const tk of ln.tokens || []) if (tk.t0 >= sh.t0 - 1e-6 && tk.t0 < sh.t1) out.push(tk); return out; };

  // ----------------------------------------------------------------------------------------------- the time grammar --
  // number → song seconds (F) · "shot.t0" | "shot.t1" | "shot.mid" · "text" → that word's t0 in the shot (W) ·
  // {word: [line, i] | "text"} (W) · {word_end: …} → t1 · {line: n} · {line_end: n} · {beat: n} (absolute beat index) ·
  // {bar: n} · {beats: k, from?: spec} (k beats after the shot start / from, fractional allowed: B) · {eighths|sixteenths: k} ·
  // {hit: kind, n?: k | near?: s, win?: .12, minS?} (H) · {take: s, clip?} (T: seconds into the shot's take) ·
  // {offset: s, from: spec} · {frame_nearest: spec}
  // (numeric fields may be strings: {"beats": "2"} is 2 beats, never "…" + "2")
  function resolveTime(spec, sh, fb) {
    sh = sh || { t0: 0, t1: 1e9 };
    if (spec == null) return fb;
    if (typeof spec === 'number') return isFinite(spec) ? spec : fb;
    if (typeof spec === 'string') {
      const s = spec.trim();
      if (s === 'shot.t0' || s === 'start') return sh.t0;
      if (s === 'shot.t1' || s === 'end') return sh.t1;
      if (s === 'shot.mid' || s === 'mid') return (sh.t0 + sh.t1) / 2;
      const n = Number(s); if (s !== '' && isFinite(n)) return n;
      const tk = token(s, sh); return tk ? tk.t0 : fb;
    }
    if (Array.isArray(spec)) { const tk = token(spec, sh); return tk ? tk.t0 : fb; }
    if (typeof spec !== 'object') return fb;
    const ok = (v, what) => { if (isFinite(v)) return true; miss(`time ${short(spec)}: ${what} is not a number`); return false; };
    if (spec.word != null) { const tk = token(spec.word, sh); return tk ? tk.t0 : fb; }
    if (spec.word_end != null) { const tk = token(spec.word_end, sh); return tk ? tk.t1 : fb; }
    if (spec.line != null) { const ln = DEV.line(spec.line); if (!ln) miss(`time ${short(spec)}: there is no lyric line ${short(spec.line)} (lines count from 0)`); return ln ? ln.t0 : fb; }
    if (spec.line_end != null) { const ln = DEV.line(spec.line_end); if (!ln) miss(`time ${short(spec)}: there is no lyric line ${short(spec.line_end)}`); return ln ? ln.t1 : fb; }
    if (spec.beat != null) { const v = N(spec.beat); return ok(v, 'beat') ? tAtBeat(v) : fb; }
    if (spec.bar != null) { const v = N(spec.bar); if (!ok(v, 'bar')) return fb; const D = SONG.downbeats; return D && D.length ? D[clamp(Math.round(v), 0, D.length - 1)] : tAtBeat(v * 4); }
    const from = () => resolveTime(spec.from ?? 'shot.t0', sh, sh.t0);
    if (spec.beats != null) { const v = N(spec.beats); return ok(v, 'beats') ? tAtBeat(bpOf(from()) + v) : fb; }
    if (spec.eighths != null) { const v = N(spec.eighths); return ok(v, 'eighths') ? tAtBeat(bpOf(from()) + v / 2) : fb; }
    if (spec.sixteenths != null) { const v = N(spec.sixteenths); return ok(v, 'sixteenths') ? tAtBeat(bpOf(from()) + v / 4) : fb; }
    if (spec.hit != null) return hitTime(spec, sh, fb);
    if (spec.take != null) { const v = N(spec.take); return ok(v, 'take') ? takeTime(v, sh, spec.clip, fb) : fb; }
    if (spec.offset != null) { const v = N(spec.offset); return ok(v, 'offset') ? from() + v : fb; }
    if (spec.frame_nearest != null) { const x = resolveTime(spec.frame_nearest, sh, fb); const F_ = typeof FPS !== 'undefined' ? FPS : 24; return Math.round(x * F_) / F_ - .5 / F_ + 1e-4; }
    if (spec.t != null) return resolveTime(num(spec.t), sh, fb);
    miss(`time ${short(spec)} has none of word · word_end · line · line_end · beat · bar · beats · eighths · sixteenths · hit · take · offset · t`);
    return fb;
  }
  DEV.time = resolveTime;
  function hitTime(spec, sh, fb) {
    const kind = spec.hit === true ? 'any' : spec.hit, n = N(spec.n ?? 0) || 0, win = N(spec.win ?? .12), minS = spec.minS != null ? N(spec.minS) : undefined;
    if (has.HIT()) {
      if (spec.near != null) return HIT.snap(resolveTime(num(spec.near), sh, sh.t0), kind, isFinite(win) ? win : .12, { minS });
      const ev = HIT.between(sh.t0 - 1e-3, sh.t1, kind, { minS });
      if (ev.length) return ev[clamp(n < 0 ? ev.length + n : n, 0, ev.length - 1)].t;
      miss(`time ${short(spec)}: no '${kind}' event inside the shot → the first beat`);
      return fb ?? DEV.beatAfter(sh.t0);
    }
    // no hits asset: the beat map stands in (kick = every beat, snare = beats 2 and 4, impact = the downbeats)
    if (spec.near != null) { const x = resolveTime(num(spec.near), sh, sh.t0); return tAtBeat(Math.round(bpOf(x))); }
    return DEV.beatAfter(sh.t0, Math.max(0, n) * (kind === 'snare' ? 2 : 1) + (kind === 'snare' ? 1 : 0));
  }
  // seconds into the shot's take → song time (the EDL segment that plays that clip: song = seg.t0 + (take − seg.in))
  function takeTime(s, sh, clip, fb) {
    const e = (G.EDL || {})[sh.id] || {}, segs = e.segs || [];
    const sg = segs.find(x => !clip || x.clip === clip) || segs[0];
    s = num(s);
    if (!sg) return typeof s === 'number' ? sh.t0 + s : fb;
    return sg.t0 + (s - (sg.in || 0));
  }
  DEV.takeTime = takeTime;
  // the take time at song time t (for take-keyed tracks)
  DEV.takeAt = (t, sh, clip) => { const segs = ((G.EDL || {})[sh.id] || {}).segs || []; let sg = null;
    for (const x of segs) if ((!clip || x.clip === clip) && x.t0 <= t + 1e-6) sg = x; sg = sg || segs[0];
    return sg ? (sg.in || 0) + (t - sg.t0) : t - sh.t0; };

  // keyed values (a readout that rolls between numbers, landing ON each key's time): keys [[time, value, ramp?], …]
  // value holds, then eases over `ramp` s (default .25) into the next key so it reaches it exactly at that key's time
  const lerpV = (a, b, k) => Array.isArray(a) ? a.map((v, i) => lerp(v, b[i], k)) : lerp(a, b, k);
  DEV.keyed = (t, keys) => {
    if (!keys || !keys.length) return null; let v = keys[0][1];
    for (let i = 0; i < keys.length; i++) if (t >= keys[i][0]) { const nx = keys[i + 1]; v = keys[i][1];
      if (nx && t > nx[0] - (nx[2] ?? .25)) v = lerpV(keys[i][1], nx[1], easeInOut(seg(t, nx[0] - (nx[2] ?? .25), nx[0]))); }
    return v;
  };
  // a linear track (take-time anchors): keys [[time, …values]]
  DEV.track = (t, keys) => { if (!keys || !keys.length) return null; if (t <= keys[0][0]) return keys[0].slice(1);
    for (let i = 1; i < keys.length; i++) if (t < keys[i][0]) { const a = keys[i - 1], b = keys[i], k = (t - a[0]) / Math.max(1e-6, b[0] - a[0]); return a.slice(1).map((v, j) => lerp(v, b[j + 1], k)); }
    return keys[keys.length - 1].slice(1); };

  // ---------------------------------------------------------------------------------------------------- registry --
  // spec: {role: 'hero'|'cv'|'micro'|'flash'|'camera', keys: 'WBHFT' (accepted timing keys), defaults: {}, draw(o, b, t, p, x),
  //        dur?(p, t0) (default span when no `until`), flashes?(inst) → [{t, pri}], example: {anchor, params, key}, doc: '…',
  //        check?(p, warn) (reads the merged params BEFORE the shape coercion: repairs a malformed param in place and calls
  //        warn(msg) once per repair — the param, what is drawn instead, the exact shape to write),
  //        covers?(inst, t) (true while the device replaces the footage: the marks drawn on the footage wait)}
  // draw() returns false when it drew nothing on this frame (the layer count and DEV_FRAME then leave it out)
  DEV.register = (kind, spec) => {
    REG[kind] = Object.assign({ kind, role: 'hero', keys: 'WBHFT', defaults: {} }, spec); (spec.alias || []).forEach(a => ALIAS[a] = kind);
    // the engine's own registry (ENGINE.drawDevice(spec, env) → fn(o, env)) draws the same device through DEV
    if (typeof ENGINE !== 'undefined' && typeof ENGINE.registerDevice === 'function' && REG[kind].role !== 'camera')
      [kind, ...(spec.alias || [])].forEach(k => { if (!ENGINE.devices || !ENGINE.devices[k]) { try { ENGINE.registerDevice(k, (o, env) => DEV.engineDraw(kind, o, env)); } catch (e) { /* the engine refused it */ } } });
    return REG[kind];
  };
  // ENGINE.drawDevice → DEV: env = {b, t, shot, m, look, accent, spec, …}
  DEV.engineDraw = async (kind, o, env = {}) => {
    const sh = env.shot || { id: '', t0: env.t0 ?? env.t ?? 0, t1: env.t1 ?? 1e9 }, inst = DEV.instance(Object.assign({}, env.spec || {}, { kind: (env.spec && (env.spec.kind || env.spec.device)) || kind }), sh);
    const L = env.look || {}, light = typeof ENGINE !== 'undefined' && ENGINE.inkFor ? ENGINE.inkFor(L).light : false;
    const X = DEV.frame({ t: env.t, sh, m: env.m || null, L, b: env.b || null, o, accent: env.accent || L.accent || C.accent, lightGround: light });
    X.lead = DEV.leadOf(env.m) || (DEV.subjectOf && sh.id ? await DEV.subjectOf(sh, env.m || null) : null);
    return DEV.draw(o, env.b || null, inst, env.t, X);
  };
  // the lead's screen box in a media result: the engine's lead label (PROJECT.lead.label, person labels), else the face
  // (detections only — the default renderer then falls back to DEV.subjectOf: the shot's / plate's subject_uv, the depth)
  DEV.leadOf = m => { if (!m || typeof m.box !== 'function') return null;
    try { const l = typeof ENGINE !== 'undefined' && ENGINE.leadLabel ? ENGINE.leadLabel(m) : null; if (l) { const bx = m.box(l); if (bx) return bx; } } catch (e) { /* no detections */ }
    for (const l of ((window.PROJECT || {}).leadBoxes || ['subject', 'a person', 'a woman', 'a man', 'a singer', 'a face'])) { try { const bx = m.box(l); if (bx) return bx; } catch (e) { /* ignore */ } }
    return null; };
  DEV.get = kind => REG[kind] || REG[ALIAS[kind]] || null;
  DEV.kinds = () => Object.keys(REG).sort();

  // params of the wrong shape (a hand-written shots.json) → the shape the device's defaults have, with a warning each, so
  // one bad field never throws inside the draw: a list given as a string ("A | B" → ["A", "B"]; rows "F: V | F: V" →
  // [["F", "V"], …]), a row given as a string or an object, a number given as a string. Anything it cannot read → the default.
  const splitRows = s => String(s).split(/\s*[|\n]\s*/).filter(Boolean);
  function coerce(kind, defs, p, warn) {
    for (const k of Object.keys(defs || {})) {
      const d = defs[k], v = p[k]; if (v == null || d == null || v === d) continue;
      if (Array.isArray(d)) {
        const rowsOfPairs = d.length && Array.isArray(d[0]), rowsOfObjs = d.length && d[0] && typeof d[0] === 'object' && !Array.isArray(d[0]);
        if (!Array.isArray(v)) {
          if (typeof v === 'string' && !rowsOfObjs) {
            p[k] = rowsOfPairs ? splitRows(v).map(r => r.split(/\s*:\s*/)) : splitRows(v);
            warn(`${kind}.params.${k} should be a list — read the string ${short(v)} as ${short(p[k])}`);
          } else { p[k] = d; warn(`${kind}.params.${k} should be a list like ${short(d)} — got ${short(v)}; using the default`); }
        } else if (rowsOfPairs && v.some(r => !Array.isArray(r))) {
          p[k] = v.map(r => Array.isArray(r) ? r : typeof r === 'string' ? r.split(/\s*:\s*/) : r && typeof r === 'object' ? Object.values(r) : [String(r)]);
          warn(`${kind}.params.${k} rows should be [field, value] lists like ${short(d[0])} — converted`);
        } else if (rowsOfObjs && v.some(r => !r || typeof r !== 'object' || Array.isArray(r))) {
          p[k] = v.filter(r => r && typeof r === 'object' && !Array.isArray(r));
          warn(`${kind}.params.${k} rows should be objects like ${short(d[0])} — ${v.length - p[k].length} row(s) dropped`);
        }
      } else if (typeof d === 'number' && typeof v !== 'number') {
        const n = num(v); if (typeof n === 'number') p[k] = n;
        else if (typeof v !== 'string') { p[k] = d; warn(`${kind}.params.${k} should be a number — got ${short(v)}; using ${d}`); }
      }
    }
    ['beat', 'n', 'x', 'y', 'take', 'size', 'w', 'h'].forEach(k => { if (typeof p[k] === 'string' && typeof num(p[k]) === 'number') p[k] = num(p[k]); });
    return p;
  }
  DEV.coerce = coerce;
  const wordSpec = v => typeof v === 'string' && !/^(shot\.(t0|t1|mid)|start|end|mid)$/.test(v.trim()) && !isFinite(+v) ? v : Array.isArray(v) ? v : v && typeof v === 'object' && v.word != null ? v.word : null;

  // a device instance from a shots.json entry, resolved against its shot: {kind, spec, role, p, key, t0, t1, anchor, keys,
  // warn} — warn: what was wrong with the entry and what was done instead (the plan logs it; DEV.report sends it on)
  DEV.instance = (raw, sh, i = 0) => {
    raw = raw || {}; const kind = raw.kind || raw.device;
    const spec = DEV.get(kind); if (!spec) return { kind, err: `unknown device kind '${kind}' (see engine/DEVICES.md for the list)` };
    const warn = [], w = s => { if (!warn.includes(s)) warn.push(s); };
    const given = raw.params && typeof raw.params === 'object' && !Array.isArray(raw.params) ? raw.params : (raw.params != null ? (w(`${kind}.params should be an object {…} — ignored`), {}) : {});
    const merged = Object.assign({}, spec.defaults, (spec.aliasParams || {})[raw.kind || raw.device] || {}, given);   // an alias may imply a style
    if (spec.check) { try { spec.check(merged, w); } catch (e) { w(`${spec.kind}: its params could not be checked (${e && e.message || e}) — see engine/DEVICES.md for their shapes`); } }
    const p = coerce(kind, spec.defaults, merged, w);
    const tw = spec.wordParam === false ? null : p.word;                    // the timing word (a device may use params.word for its text)
    let key = String(raw.key || (tw != null ? 'W' : spec.key0 || 'B')).toUpperCase()[0];
    if (!'WBHFT'.includes(key)) { w(`${kind}: key '${raw.key}' is not one of W B H F T → B`); key = 'B'; }
    const at = raw.at && typeof raw.at === 'object' && !Array.isArray(raw.at) && ('t0' in raw.at || 't1' in raw.at) ? raw.at.t0 : (raw.at ?? p.at);
    const until = raw.at && typeof raw.at === 'object' && 't1' in raw.at ? raw.at.t1 : (raw.until ?? p.until);
    const T = v => key === 'T' && typeof num(v) === 'number' ? { take: num(v) } : v;     // under key T, bare numbers are take seconds
    SINK = [];
    let t0, t1, keys, byWord = null;
    try {
      if (at != null) { t0 = resolveTime(T(at), sh, sh.t0); byWord = wordSpec(at); }
      else if (key === 'W') {
        if (tw != null) { t0 = resolveTime({ word: tw }, sh, sh.t0); byWord = tw; }
        else { const tk = DEV.shotTokens(sh)[0]; t0 = tk ? tk.t0 : sh.t0; if (!tk && sh.id) miss(`key W but no word is sung in the shot (and no params.word) → starts at the shot start`); }
      }
      else if (key === 'H') t0 = resolveTime({ hit: p.hit || 'any', n: p.n || 0 }, sh, DEV.beatAfter(sh.t0));
      else if (key === 'F') t0 = p.t != null ? resolveTime(num(p.t), sh, sh.t0) : sh.t0;
      else if (key === 'T') t0 = takeTime(N(p.take ?? 0) || 0, sh, p.clip, sh.t0);
      else t0 = DEV.beatAfter(sh.t0 - 1e-3, N(p.beat || 0) || 0);
      if (!isFinite(t0)) t0 = sh.t0;
      // a start keyed to a word that is sung outside the shot would never be seen: it starts at the shot start instead
      if (byWord != null && sh.id && sh.t1 < 1e8) { const r = tokenInfo(byWord, sh);
        if (r.tk && !r.inShot) { miss(`word ${short(byWord)} is sung at ${r.tk.t0.toFixed(2)} s, outside the shot (${sh.t0.toFixed(2)}–${sh.t1.toFixed(2)} s) → starts at the shot start`); t0 = sh.t0; } }
      t1 = until != null ? resolveTime(T(until), sh, null) : null;
      if (t1 == null || !isFinite(t1)) { const d = spec.dur ? spec.dur(p, t0) : null; t1 = d != null && isFinite(d) ? t0 + d : Math.max(sh.t1, t0 + 1e-3); }
      else if (t1 <= t0) { miss(`until ${short(until)} (${t1.toFixed(2)} s) is not after the start (${t0.toFixed(2)} s) → the shot end`); t1 = Math.max(sh.t1, t0 + 1e-3); }
      // keyed values: times resolve through the grammar (bare numbers are take seconds under key T)
      keys = Array.isArray(p.keys) ? p.keys.filter(k => Array.isArray(k) && k.length >= 2).map(k => [resolveTime(T(k[0]), sh, sh.t0), num(k[1]), num(k[2])]).sort((a, b) => a[0] - b[0]) : null;
      if (p.keys != null && !Array.isArray(p.keys)) miss(`params.keys should be [[time, value, ramp?], …] — ignored`);
    } finally { SINK.forEach(s => w(`${kind}: ${s}`)); SINK = null; }
    return { kind: spec.kind, spec, role: spec.role, p, key, t0, t1, keys, anchor: raw.anchor ?? p.anchor, raw, sh, i, pri: N(raw.priority ?? 0) || 0, warn };
  };

  // ------------------------------------------------------------------------------------------------- the anchors --
  // 'lead' / 'subject' · a detection label ('a face', from PLATES boxes or TRACK) · {box|track: label, pad} · {rect: [x, y, w, h]} ·
  // {xy: [x, y]} (screen px) · {uv: [u, v] | [u, v, w, h]} (image space through the camera; the frame when there is no
  // footage) · {keys: [[time, u, v(, w, h)]], clip?} (a hand-measured track; times are take seconds under key T) ·
  // {slot: 'left'|'right'|'top-left'|…|'auto'} · [x, y] / [x, y, w, h] (screen px)
  // Without a detection (the real pipeline writes none), person labels resolve to the lead/subject box and 'a face' to the
  // top of it (the whole box on CU/MCU/ECU framings); any other missing label resolves to nothing (the plan warns).
  const PERSON = /^(subject|lead|the lead|a person|a woman|a man|a girl|a boy|a singer|her|him|person|woman|man|singer)$/i;
  const FACE = /^(a |the )?(face|head)$/i;
  function labelBox(label, x) {
    const m = x.m; let bx = null; if (m && m.box) { try { bx = m.box(label); } catch (e) { bx = null; } } if (bx) return bx;
    if (!x.lead) return null;
    if (PERSON.test(label)) return x.lead;
    if (FACE.test(label)) { const [lx, ly, lw, lh] = x.lead; return /^(E?CU|MCU)$/i.test(String((x.sh || {}).framing || '')) ? x.lead : [lx + lw * .3, ly, lw * .4, Math.min(lh * .3, lw * .5)]; }
    return null;
  }
  DEV.labelBox = labelBox;
  function anchorBox(a, x) {
    if (a == null) return null;
    const m = x.m, pad = (v, k) => v && k ? [v[0] - k, v[1] - k, v[2] + 2 * k, v[3] + 2 * k] : v;
    if (typeof a === 'string') { if (a === 'lead' || a === 'subject') return x.lead || null; if (SLOT[a]) return slotBox(a, x, 360, 220); return labelBox(a, x); }
    if (Array.isArray(a)) { const v = a.map(num); return v.length >= 4 ? v.slice(0, 4) : v.length >= 2 ? [v[0] - 6, v[1] - 6, 12, 12] : null; }
    if (typeof a !== 'object') return null;
    const label = a.box || a.track || a.label;
    if (label) return pad(label === 'lead' || label === 'subject' ? x.lead : labelBox(label, x), a.pad);
    if (Array.isArray(a.rect)) return pad(a.rect.slice(0, 4).map(num), a.pad);
    if (Array.isArray(a.xy)) return [num(a.xy[0]) - 6, num(a.xy[1]) - 6, 12, 12];
    if (a.slot) return slotBox(a.slot, x, a.w || 360, a.h || 220);
    const map = m && m.map ? m.map : (u, v) => [u * W, v * H];             // no footage: uv is the frame
    const uvBox = uv => { uv = uv.map(num); if (uv.length >= 4) { const [x0, y0] = map(uv[0], uv[1]), [x1, y1] = map(uv[0] + uv[2], uv[1] + uv[3]); return [x0, y0, x1 - x0, y1 - y0]; }
      const [px, py] = map(uv[0], uv[1]); return [px - 6, py - 6, 12, 12]; };
    if (Array.isArray(a.uv)) return pad(uvBox(a.uv), a.pad);
    if (a.keys) { const tt = x.inst && x.inst.key === 'T' ? DEV.takeAt(x.t, x.sh, a.clip) : x.t, v = DEV.track(tt, a.keys); return v ? pad(uvBox(v), a.pad) : null; }
    return null;
  }
  // can this anchor resolve on this shot (static data only)? → null, or a warning that says what to do instead
  DEV.anchorProblem = (a, sh, hasLead) => {
    if (a == null) return null;
    const e = (G.EDL || {})[sh.id] || {}, meta = e.plate ? ((G.PLATES || {})[e.plate] || {}) : {}, seg = e.segs && e.segs[0], tr = seg ? ((G.TRACK || {})[seg.clip] || {}) : {};
    const label = typeof a === 'string' ? (SLOT[a] ? null : a) : a && typeof a === 'object' && !Array.isArray(a) ? (a.box || a.track || a.label || null) : null;
    if (!label) return null;
    const fix = 'add "subject_uv": [u, v, w, h] to the shot, or anchor it with {"uv": [u, v]}, {"rect": [x, y, w, h]} or a slot';
    if (label === 'lead' || label === 'subject') return hasLead ? null : `anchor '${label}' has nothing to resolve to (no detection boxes, no subject_uv, no depth map) — ${fix}`;
    if ((meta.boxes || {})[label] || tr[label]) return null;
    if ((PERSON.test(label) || FACE.test(label)) && hasLead) return null;
    return `anchor '${label}': no detection box for it on this shot (\`slop edit export\` writes none) → the device draws nothing — ${fix}`;
  };
  const SLOT = { left: 1, right: 1, 'top-left': 1, 'top-right': 1, 'bottom-left': 1, 'bottom-right': 1, center: 1, top: 1, bottom: 1, auto: 1 };
  // a free region for a w × h block that respects the margins and stays off the lead and the lyric block: 'auto' tries the
  // slots on the side away from the lead first (top, middle, bottom), then the lead's side, and takes the first that
  // overlaps nothing in x.avoid (the lyric blocks, set by the default renderer) — else the least-covered one
  const inter = (a, b) => { const w = Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]), h = Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]); return w > 0 && h > 0 ? w * h : 0; };
  DEV.inter = inter;
  const slotAt = (n, w, h) => { const Mg = MG(), X0 = Mg.l, X1 = W - Mg.r - w, Y0 = Mg.t + 84, Y1 = H - Mg.b - h - 96, YC = (H - h) / 2;
    return [/left/.test(n) ? X0 : /right/.test(n) ? X1 : (W - w) / 2, /top/.test(n) ? Y0 : /bottom/.test(n) ? Y1 : YC, w, h]; };
  function slotBox(name, x, w, h) {
    const lead = x.lead, away = lead ? (lead[0] + lead[2] / 2 < W / 2 ? 'right' : 'left') : 'right', near = away === 'right' ? 'left' : 'right';
    if (name !== 'auto') return slotAt(name, w, h);
    const avoid = [lead, ...(x.avoid || [])].filter(Boolean); let best = null, bestA = Infinity;
    for (const n of [`top-${away}`, away, `bottom-${away}`, `top-${near}`, 'top', `bottom-${near}`, near]) {
      const r = slotAt(n, w, h), a = avoid.reduce((acc, q) => acc + inter(r, q), 0); if (a === 0) return r; if (a < bestA) { bestA = a; best = r; } }
    return best;
  }
  DEV.slot = slotBox; DEV.anchor = anchorBox;

  // ------------------------------------------------------------------------------ the lyric block keeps its room --
  // x.avoid: the lyric blocks a device keeps off (screen rects, padded by the renderer): every block whose time on screen
  // overlaps the device's own, measured with DEV.type.measure (the block's extent over its whole time on screen), so a
  // device does not jump when the next line comes in. x.place moves a panel off them; DEV.spot picks a free spot for a
  // label (a CV label flips to another corner of its box, or is dropped); DEV.draw clips the strokes of the CV marks out
  // of the blocks on screen now (X.avoidNow). The chrome is handled by the renderer (shots.js).
  const hitsAny = (r, list) => (list || []).some(q => q && inter(r, q) > 0);
  // inside the frame (2 px in); in 9:16 within 32 px of the UI-safe margins (a label below a subject must not land in the
  // platform's caption band)
  const inFrame = (r, m = 2) => { const P = H > W ? MG() : null, l = P ? Math.max(m, P.l - 32) : m, tp = P ? Math.max(m, P.t - 32) : m, rt = P ? Math.max(m, P.r - 32) : m, bt = P ? Math.max(m, P.b - 32) : m;
    return r[0] >= l && r[1] >= tp && r[0] + r[2] <= W - rt && r[1] + r[3] <= H - bt; };
  DEV.hitsAny = hitsAny; DEV.inFrame = inFrame;
  // the width of letter-spaced text (DEV.tracked's), without drawing it
  DEV.trackedW = (g, txt, em = 0) => { const size = parseFloat((g.font.match(/(\d+(\.\d+)?)px/) || [0, 13])[1]); g.letterSpacing = `${em * size}px`;
    const w = g.measureText(String(txt)).width; g.letterSpacing = '0px'; return w; };
  // does a polyline [x0, y0, x1, y1, …] cross any rect of the list (a leader running into a lyric block)?
  const segHit = (r, x0, y0, x1, y1) => { let a = 0, b = 1; const dx = x1 - x0, dy = y1 - y0;
    for (const [p, q] of [[-dx, x0 - r[0]], [dx, r[0] + r[2] - x0], [-dy, y0 - r[1]], [dy, r[1] + r[3] - y0]]) {
      if (p === 0) { if (q < 0) return false; continue; } const u = q / p; if (p < 0) { if (u > b) return false; if (u > a) a = u; } else { if (u < a) return false; if (u < b) b = u; } }
    return a < b; };
  DEV.lineHits = (list, pts) => { for (let i = 0; i + 3 < pts.length; i += 2) if ((list || []).some(r => r && segHit(r, pts[i], pts[i + 1], pts[i + 2], pts[i + 3]))) return true; return false; };
  // does a leader from its anchor (pts[0], pts[1]) run clear of x.avoid? (a block around the anchor itself aside: the CV
  // strokes are clipped there anyway)
  DEV.clearPath = (x, pts) => !DEV.lineHits(((x && x.avoid) || []).filter(r => r && !(pts[0] >= r[0] && pts[0] <= r[0] + r[2] && pts[1] >= r[1] && pts[1] <= r[1] + r[3])), pts);
  // the first candidate whose rects all sit inside the frame and off x.avoid → its index, or -1 (nothing free: drop the
  // label). A candidate is a rect [x, y, w, h] or a list of rects (a label and its score); pref (optional, one flag per
  // candidate) puts the flagged ones first — a label whose leader stays off the lyric too. The choice is recorded in
  // X.labels (DEV_FRAME.labels: {kind, spot (-1: dropped), box, rects}); x without an avoid list (the kit adapters) takes the first candidate.
  DEV.spot = (x, cands, kind, pref) => {
    const rec = (i, rs) => { const L = x && (x.labels || (x.labels = [])); if (!L) return; const u = rs.length ? rs.reduce((a, r) => a ? [Math.min(a[0], r[0]), Math.min(a[1], r[1]), Math.max(a[2], r[0] + r[2]), Math.max(a[3], r[1] + r[3])] : [r[0], r[1], r[0] + r[2], r[1] + r[3]], null) : null;
      L.push({ kind: kind || (x.inst && x.inst.kind) || '', spot: i, box: u ? [u[0], u[1], u[2] - u[0], u[3] - u[1]].map(v => Math.round(v)) : null, rects: rs.map(r => r.map(v => Math.round(v))) }); };
    if (!x || !x.avoid) { const c = cands.find(Boolean); if (!c) return -1; rec(cands.indexOf(c), Array.isArray(c[0]) ? c : [c]); return cands.indexOf(c); }
    for (const first of pref ? [true, false] : [false])
      for (let i = 0; i < cands.length; i++) { const c = cands[i]; if (!c || (first && !pref[i])) continue; const rs = Array.isArray(c[0]) ? c : [c];
        if (rs.every(r => inFrame(r) && !hitsAny(r, x.avoid))) { rec(i, rs); return i; } }
    rec(-1, []); return -1;
  };
  // a block that would cover a lyric block → the nearest free spot inside the margins (least movement; a spot on the lead
  // or on a block another device placed on this frame costs more): the other side of its anchor, above / below / beside
  // each block it hits, the slots; at .8 and then .64 of its size when nothing at full size is free → {r, k} (k: the
  // extra scale); when nothing is free at all, the smallest spot that covers the least of the blocks ({r, k, covers: true})
  // — a frame filled by its lyric has no room left
  function freeSpot(r0, x, av, bx) {
    const Mg = MG(), lead = x.lead, placed = (x.boxes || []).map(e => e.box).filter(Boolean);
    const inside = r => [clamp(r[0], Mg.l, Math.max(Mg.l, W - Mg.r - r[2])), clamp(r[1], Mg.t, Math.max(Mg.t, H - Mg.b - r[3])), r[2], r[3]];
    let least = null, la = Infinity;
    for (const k of [1, .8, .64]) {
      const w = r0[2] * k, h = r0[3] * k, c = [[r0[0], r0[1], w, h]];
      if (bx) c.push([bx[0] - 30 - w, r0[1], w, h], [bx[0] + bx[2] + 30, r0[1], w, h]);
      av.forEach(q => c.push([r0[0], q[1] - h, w, h], [r0[0], q[1] + q[3], w, h], [q[0] - w, r0[1], w, h], [q[0] + q[2], r0[1], w, h], [q[0] - w, q[1] - h, w, h], [q[0] + q[2], q[1] - h, w, h]));
      ['top-left', 'top-right', 'left', 'right', 'bottom-left', 'bottom-right', 'top', 'bottom', 'center'].forEach(n => c.push(slotAt(n, w, h)));
      let best = null, bd = Infinity;
      for (const c0 of c) { const q = inside(c0), a = av.reduce((s, r) => s + inter(q, r), 0);
        if (a > 0) { if (k === .64 && a < la - 1e-6) { la = a; least = q; } continue; }
        const d = Math.hypot(q[0] - r0[0], q[1] - r0[1]) + (lead && inter(q, lead) > 0 && !(inter(r0, lead) > 0) ? 600 : 0) + (hitsAny(q, placed) ? 900 : 0);
        if (d < bd - 1e-6) { bd = d; best = q; } }
      if (best) return { r: best, k };
    }
    return least ? { r: least, k: .64, covers: true } : null;
  }
  DEV.freeSpot = freeSpot;

  // ------------------------------------------------------------------------------------------------ adaptive ink --
  // the ink that reads on the BASE under a box: AINK (white on dark, near-black on light; never split by default — split
  // ink cut glyphs mid-word over busy texture in the source video); without ink.js, by the look (paper → ink)
  DEV.inkFor = (b, box, X, o = {}) => {
    if (o.ink) return o.ink;
    if (b && box && has.AINK()) { try { return AINK.pick(b, box, { split: false, accent: false }).ink; } catch (e) { /* off-canvas box */ } }
    return X && X.lightGround ? C.dark : C.light;
  };

  // --------------------------------------------------------------------------------------- the per-frame context --
  // X: one frame of one shot — {t, sh, m, L, b, o, lead, accent, lightGround, accLeft, warn}. Instances get x = a view of X
  // with their own window and helpers. The accent budget: orange on ≤ 2 elements per frame (the lyric claims first).
  DEV.frame = (o = {}) => Object.assign({ t: 0, sh: { id: '', t0: 0, t1: 1e9 }, m: null, L: {}, b: null, lead: null, accent: C.accent, lightGround: false,
    accLeft: 2, drawn: [], warn: [], boxes: [], labels: [] }, o);
  // a whole-frame accent claim (a treatment's sweep line, a strip's selection): the accent, or null when 2 elements hold it
  DEV.takeAccent = X => { if (!X) return C.accent; if (X.accLeft > 0) { X.accLeft--; return X.accent || C.accent; } return null; };
  function ctx(X, inst) {
    const x = Object.create(X);
    x.inst = inst; x.t0 = inst.t0; x.t1 = inst.t1; x.p = inst.p; x.key = inst.key;
    // the lyric blocks this device keeps off (over its whole window; see "the lyric block keeps its room")
    x.avoid = (X.avoidFor ? X.avoidFor(inst) : X.avoid) || [];
    let claimed = false;
    x.acc = () => { if (claimed) return X.accent; if (X.accLeft > 0) { X.accLeft--; claimed = true; return X.accent; } return x.ink(); };
    x.ink = box => DEV.inkFor(X.b, box || x.box() || [W / 2 - 100, H / 2 - 50, 200, 100], X, { ink: inst.p.color });
    x.box = () => anchorBox(inst.anchor, x);
    x.pt = () => { const bx = x.box(); return bx ? [bx[0] + bx[2] / 2, bx[1] + bx[3] / 2] : null; };
    x.bs = t => bpOf(t) - bpOf(inst.t0);
    x.bl = bl;
    x.val = t => inst.keys ? DEV.keyed(t, inst.keys) : inst.p.value;
    x.fade = t => 1 - seg(t, inst.t1, inst.t1 + (inst.p.fadeOut ?? .2));
    // where a w × h block goes: params x/y (screen px) → a slot anchor → beside the anchor's box → a free slot. The block
    // always stays inside the margins (MG(): portrait has its own UI-safe margins); one bigger than the safe area is scaled
    // down to fit (the device keeps drawing in its own px: x.place sets the scale on the device's canvas). It never covers
    // a lyric block (x.avoid): it moves to the nearest free spot (DEV.freeSpot; shrunk to .8 / .64 when nothing at full size
    // is free) — a position the board asked for (x/y, a named slot) that has to move is reported once. params.free: true
    // keeps explicit x/y as given (the SP-kit adapters).
    x.place = (w, h) => {
      const p = inst.p, Mg = MG(), aw = W - Mg.l - Mg.r, ah = H - Mg.t - Mg.b;
      w = Math.max(1, +w || 1); h = Math.max(1, +h || 1);
      let k = p.free ? 1 : Math.min(1, aw / w, ah / h), sw = w * k, shh = h * k;
      let px, py, bx = null;
      const sl = inst.anchor && (typeof inst.anchor === 'string' ? SLOT[inst.anchor] && inst.anchor : inst.anchor.slot);
      const asked = p.x != null && p.y != null ? 'params x/y' : sl && sl !== 'auto' ? `slot '${sl}'` : null;
      if (p.x != null && p.y != null) { px = +num(p.x); py = +num(p.y); }
      else if (sl) { const s = slotBox(sl, x, sw, shh); px = s[0]; py = s[1]; }
      else { bx = inst.anchor ? x.box() : null;
        if (bx) { const right = bx[0] + bx[2] + 30 + sw < W - Mg.r; px = right ? bx[0] + bx[2] + 30 : bx[0] - 30 - sw; py = clamp(bx[1], Mg.t + 84, H - Mg.b - shh - 96); }
        else { const s = slotBox(p.slot || 'auto', x, sw, shh); px = p.x != null ? +num(p.x) : s[0]; py = p.y != null ? +num(p.y) : s[1]; } }
      if (!isFinite(px)) px = Mg.l; if (!isFinite(py)) py = Mg.t;
      if (!p.free) { px = clamp(px, Mg.l, Math.max(Mg.l, W - Mg.r - sw)); py = clamp(py, Mg.t, Math.max(Mg.t, H - Mg.b - shh)); }
      const av = p.free ? [] : x.avoid || [];
      if (av.length && hitsAny([px, py, sw, shh], av)) {
        const f = freeSpot([px, py, sw, shh], x, av, bx);
        if (f) { px = f.r[0]; py = f.r[1]; sw = f.r[2]; shh = f.r[3]; k *= f.k; }
        if (x.sh && x.sh.id) {
          if (asked) DEV.report(`${x.sh.id}: '${inst.kind}' at its ${asked} would cover the lyric block → ${f && !f.covers ? 'moved off it' : 'nothing is free: shrunk where it covers the least of it'} (the lyric always reads; put the device where no lyric is)`);
          else if (!f || f.covers) DEV.report(`${x.sh.id}: '${inst.kind}' finds no room off the lyric block (the lyric fills the frame) → shrunk where it covers the least of it; give the lyric less room (a smaller size or fit) or the device its own moment`);
        }
      }
      if (k < 1 && x.g) { x.g.translate(px, py); x.g.scale(k, k); x.g.translate(-px, -py); }
      (X.boxes || (X.boxes = [])).push({ kind: inst.kind, box: [px, py, sw, shh], scale: k });
      return [px, py]; };
    return x;
  }
  DEV.ctx = ctx;
  // draw one instance (save/restore around it, text state reset after it)
  DEV.draw = async (o, b, inst, t, X) => {
    if (!inst || !inst.spec) throw new Error(inst && inst.err || 'not a device instance');
    const X0 = X || DEV.frame({ t, b }), x = ctx(X0, inst); x.t = t;
    // after its end a graphic fades out (params.fadeOut): it draws into a scratch layer composited at the fade's alpha
    const fading = inst.role !== 'flash' && inst.role !== 'camera' && t >= inst.t1, layer = fading ? DEV.scratch(W, H) : null, g = layer ? layer.getContext('2d') : o;
    x.g = g;
    g.save(); b && b.save(); let r;
    // the CV marks' strokes (brackets, leaders, the range-finder's hairlines) stop at the lyric blocks on screen now (their
    // labels are placed off the blocks: DEV.spot); one clip per block, so overlapping blocks stay cut out
    if (inst.role === 'cv') (X0.avoidNow || []).forEach(q => { if (!q) return; g.beginPath(); g.rect(-W, -H, 3 * W, 3 * H); g.rect(q[0], q[1], q[2], q[3]); g.clip('evenodd'); });
    try { r = await inst.spec.draw(g, b, t, inst.p, x); }
    finally { g.restore(); b && b.restore(); g.letterSpacing = '0px'; g.textAlign = 'start'; g.textBaseline = 'alphabetic'; }
    if (layer) { o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = clamp(x.fade(t)); o.drawImage(layer, 0, 0); o.restore(); }
    x.drew = r !== false;                                                     // false: it drew nothing on this frame
    return x;
  };
  // does an active instance replace the footage at t (powers of ten's map): the marks drawn on the footage then wait
  DEV.covers = (inst, t) => { try { return !!(inst && inst.spec && inst.spec.covers && DEV.active(inst, t) && inst.spec.covers(inst, t)); } catch (e) { return false; } };
  // the same, synchronously (for synchronous chapter code through the SP-kit adapters: the state is restored before it
  // returns). Only for devices whose draw is synchronous.
  DEV.drawSync = (o, b, inst, t, X) => {
    if (!inst || !inst.spec) throw new Error(inst && inst.err || 'not a device instance');
    const x = ctx(X || DEV.frame({ t, b }), inst); x.t = t; x.g = o;
    o.save(); b && b.save(); let r;
    try { r = inst.spec.draw(o, b, t, inst.p, x); }
    finally { o.restore(); b && b.restore(); o.letterSpacing = '0px'; o.textAlign = 'start'; o.textBaseline = 'alphabetic'; }
    x.drew = r !== false;
    return x;
  };
  // is the instance on screen at t (its window; a flash or a camera move is checked by its own role)
  // (graphics fade out over params.fadeOut s, default .2, after their end; flashes and camera moves stop dead)
  DEV.active = (inst, t) => t >= inst.t0 - 1e-6 && t < inst.t1 + (inst.role === 'flash' || inst.role === 'camera' ? 0 : (inst.p.fadeOut ?? .2));

  // ----------------------------------------------------------------------------------------------- typed rows ----
  // mono micro rows typed on the sixteenths (the source: 3 characters a 16th after the entrance; o.per16), ≤ o.max rows
  DEV.typed = (g, rows, x, y, t, t0, o = {}) => {
    const TY = DEV.TY(), size = o.size || 13, lh = o.lh || Math.round(size * 1.46), per16 = o.per16 ?? 3, B = bl(t0);
    let budget = Math.floor((t - t0) / (B / 4) * per16) + (o.first ? 1 : 0); if (budget <= 0) return 0;
    DEV.font(g, size, TY.mono, o.weight || 500); g.textBaseline = 'top';
    const R = rows.slice(0, o.max ?? 3); let shown = 0;
    R.forEach((r, i) => { const s = o.upper === false ? String(r) : String(r).toUpperCase(), n = Math.min(s.length, budget); budget -= s.length; if (n <= 0) return; shown++;
      g.globalAlpha = (o.alpha ?? 1) * (o.dim && i % 2 ? .72 : 1); g.fillStyle = (o.colors && o.colors[i]) || o.color || C.light;
      DEV.tracked(g, s.slice(0, n) + (n < s.length && frac(t * 8) < .5 ? '▌' : ''), x, y + i * lh, o.em ?? .06, o.align || 'left'); });
    g.globalAlpha = 1; return shown;
  };
  // the fast variant (a CV tag must finish typing within the beat of its hit): ≥ 40 characters a second
  DEV.typedFast = (g, rows, x, y, t, t0, o = {}) => {
    const B = bl(t0), ups = rows.map(r => String(r).toUpperCase()), cps = Math.max(o.cps ?? 40, Math.max(1, ...ups.map(s => s.length)) / Math.max(.05, .75 * B));
    let n = Math.floor((t - t0) * cps) + 1; if (t < t0) return;
    const TY = DEV.TY(); DEV.font(g, o.size || 13, TY.mono, 500); g.textBaseline = 'top'; g.fillStyle = o.color || C.light;
    ups.slice(0, o.max ?? 4).forEach((s, i) => { const k = Math.min(s.length, n); if (k <= 0) return; DEV.tracked(g, s.slice(0, k) + (k < s.length ? '▌' : ''), x, y + i * (o.lh || 19), .08, o.align || 'left'); });
  };

  // ------------------------------------------------------------------------------------------- number formatting --
  // format: 'int' (1,234) · 'fixed1' / 'fixed2' · 'pct' · 'usd' ($1,234) · 'si' (1.2K, 3.4M) · 'times' (×1,024) or a string
  // template with {v} (e.g. '{v} kN'); prefix / suffix params are added around it
  DEV.fmt = (v, f = 'int', o = {}) => {
    const int = x => Math.round(x).toLocaleString('en-US');
    let s;
    if (typeof f === 'string' && f.includes('{v}')) s = f.replace('{v}', o.dp != null ? v.toFixed(o.dp) : int(v));
    else if (f === 'fixed1') s = v.toFixed(1); else if (f === 'fixed2') s = v.toFixed(2);
    else if (f === 'pct') s = `${o.dp != null ? v.toFixed(o.dp) : Math.round(v)}%`;
    else if (f === 'usd') s = '$' + int(v);
    else if (f === 'si') s = Math.abs(v) >= 1e9 ? (v / 1e9).toFixed(1) + 'B' : Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + 'M' : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(1) + 'K' : int(v);
    else if (f === 'times') s = '×' + int(v);
    else s = o.dp != null ? v.toFixed(o.dp) : int(v);
    return (o.prefix || '') + s + (o.suffix || '');
  };

  // ---------------------------------------------------------------------------------------- per-frame scratch pool --
  // software-backed canvases (willReadFrequently: history-independent), handed out cleared; DEV.begin(t) rewinds the pool
  const pool = []; let used = 0;
  DEV.begin = () => { used = 0; };
  DEV.scratch = (w = W, h = H) => {
    let c = pool[used]; if (!c) { c = document.createElement('canvas'); pool.push(c); } used++;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const g = c.getContext('2d', { willReadFrequently: true }); if (g.reset) g.reset(); else { g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none'; }
    g.clearRect(0, 0, w, h); return c;
  };
  // every canvas the library creates is SOFTWARE-backed from its first getContext call: drawing a GPU-backed canvas into
  // the base/overlay switches them to GPU rasterisation for the rest of the page's life (a frame would then depend on
  // which frames this worker rendered before it — the history check fails)
  DEV.mk = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; c.getContext('2d', { willReadFrequently: true });
    try { Object.defineProperty(c, 'naturalWidth', { value: w }); Object.defineProperty(c, 'naturalHeight', { value: h }); } catch (e) { /* read-only */ } return c; };
  // static-data memos (keyed by name, never by frame). With an owner (a plate name) the entry belongs to that plate, and
  // only the MEMO_PLATES most recently used plates keep theirs: a worker renders interleaved frames of the whole film, so
  // unbounded per-plate slices/grids/thumbs grew Chromium by ~5× on a long film (a transition touches 2 plates per frame)
  const memo = new Map(), owners = [], MEMO_PLATES = 3;
  const pxOf = (v, seen = new Set()) => { if (!v || typeof v !== 'object' || seen.has(v)) return 0; seen.add(v);
    if (typeof HTMLCanvasElement !== 'undefined' && v instanceof HTMLCanvasElement) return v.width * v.height;
    if (ArrayBuffer.isView(v)) return v.length;
    if (typeof HTMLImageElement !== 'undefined' && v instanceof HTMLImageElement) return 0;   // the engine's own image cache holds those
    let n = 0; for (const k of Object.keys(v)) n += pxOf(v[k], seen); return n; };
  DEV.memo = (k, f, owner) => {
    if (owner != null) { const i = owners.indexOf(owner); if (i >= 0) owners.splice(i, 1); owners.push(owner);
      while (owners.length > MEMO_PLATES) { const old = owners.shift(); for (const [kk, e] of memo) if (e.owner === old) memo.delete(kk); } }
    const e = memo.get(k); if (e) return e.v;
    const ent = { v: f(), owner, px: 0 }; memo.set(k, ent);
    Promise.resolve(ent.v).then(r => { ent.px = pxOf(r); }, () => { memo.delete(k); });
    return ent.v;
  };
  // what the memos hold: {entries, owners (plates, oldest first), px (canvas pixels + typed-array cells)}
  DEV.memoStats = () => ({ entries: memo.size, owners: owners.slice(), px: [...memo.values()].reduce((a, e) => a + (e.px || 0), 0), limit: MEMO_PLATES });

  // ------------------------------------------------------------------------------------------------- the flash rule --
  // ≤ 3 full-frame flashes in any second: FLASH.ok(times). DEV.flashPlan accepts flashes by priority, then time.
  DEV.flashOk = times => { const s = [...times].sort((a, b) => a - b); for (let i = 3; i < s.length; i++) if (s[i] - s[i - 3] < 1) return false; return true; };
  DEV.flashAt = (t, times, dur) => { const d = dur ?? 1 / (typeof FPS !== 'undefined' ? FPS : 24); return times.some(x => t >= x - 1e-6 && t < x + d - 1e-6); };
  // Entries with fixed: true are the frame changes that happen anyway (a designed transition, a cut into a stills shot): the
  // WCAG check on the master can count them as flashes, so they always take their place in the budget and the droppable
  // flashes (devices, flash cuts, crop flashes) fit around them.
  DEV.flashPlan = list => {
    const acc = [], rejected = [], key = f => Math.round(f.t * 1000);
    const seenF = new Set(); list.filter(f => f.fixed).forEach(f => { const k = key(f); if (!seenF.has(k)) { seenF.add(k); acc.push(f); } });
    list.filter(f => !f.fixed).sort((a, b) => (b.pri || 0) - (a.pri || 0) || a.t - b.t).forEach(f => {
      const near = acc.filter(x => Math.abs(x.t - f.t) < 1).map(x => x.t).concat([f.t]);
      if (acc.some(x => key(x) === key(f)) || DEV.flashOk(near)) acc.push(f); else rejected.push(f); });
    const ok = new Set(acc.filter(f => !f.fixed).map(key));
    return { accepted: acc.sort((a, b) => a.t - b.t), rejected, has: t => ok.has(Math.round(t * 1000)) };
  };

  // ------------------------------------------------------------------------------------------ SP-style aliases --
  // chapter code written against the second video's kit names keeps working (only when nothing else defines them)
  DEV.alias = (name, val) => { if (typeof G[name] === 'undefined') { try { G[name] = val; } catch (e) { /* defined lexically elsewhere */ } } };
  // an ad-hoc instance for the kit adapters (a time window instead of a shot)
  DEV.adhoc = (kind, params, t0, t1, anchor, key = 'F') => DEV.instance({ kind, key, at: t0, until: t1 ?? null, anchor, params: Object.assign({ free: true }, params) }, { id: '', t0: isFinite(t0) ? t0 : -1e9, t1: 1e9 });
})();
