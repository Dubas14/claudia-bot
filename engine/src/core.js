// core.js — frame size, the song clock (beat map), easing, deterministic randomness, colours, asset loading.
// Every frame is a pure function of song time t (seconds). No Math.random, no Date, no state carried between frames.
//
// Port notes (engine-core v1): the song clock no longer defaults to a reference video's tempo/length — it comes from
// window.BEATS (analysis/beats.json, a VARIABLE-tempo beat map); without a beat map bpOf() falls back to BEATS.tempo[0]
// or PROJECT.bpm or 120 BPM, and duration to the data. W×H come from window.SLOP / ?w=&h= / PROJECT.size (default
// 1920×1080); H > W is PORTRAIT (the 9:16 cut). Failed image loads are remembered (one failed request per file, not per frame)
// and REPORTED: every required file that fails is listed in ENGINE.missingMedia / ENGINE.info().missingMedia with one
// console.error, and marks the frame being drawn (ENGINE.frameMissing) — `slop render` refuses such frames (the original
// threw; a silent placeholder would ship). Depth is used only when labelled Depth-Anything-V2-Small (ENGINE.depthOK).
// Render-track additions: the decoded-image cache is capped by BYTES (dropCache; ENGINE.cache reports it) and a refused
// decode() of an image that loaded is not reported as missing (robustDecode, below); every frame leaves a record
// (ENGINE.lastFrame) from which ENGINE.frameLayers() counts its ordered information layers (the ≥ 3 rule); bespoke
// chapter code declares what it draws itself with ENGINE.noteLayer(kind).
'use strict';
const _SLOP = window.SLOP || {}, _QS = new URLSearchParams(location.search), _PJ0 = window.PROJECT || {};
const _pos = (...v) => { for (const x of v) { if (x == null || x === '') continue; const n = Number(x); if (isFinite(n) && n > 0) return n; } return 0; };
const W = Math.round(_pos(_SLOP.w, _QS.get('w'), (_PJ0.size || [])[0]) || 1920);
const H = Math.round(_pos(_SLOP.h, _QS.get('h'), (_PJ0.size || [])[1]) || 1080);
const FPS = _pos(_SLOP.fps, _QS.get('fps'), _PJ0.fps) || 24, BOIL = 12;   // BOIL: grain/shake re-seed rate (per s)
const TAU = Math.PI * 2;
const PORTRAIT = H > W, UNIT = Math.min(W, H) / 1080;                     // UNIT: px scale vs the 1080-line design
['out', 'base', 'over'].forEach(id => { const c = document.getElementById(id); if (c) { c.width = W; c.height = H; } });

// ---- the song clock: window.BEATS (merged by ENGINE.prepareData) ----
let SONG = { bpm: 120, offset: 0.0, duration: 0, beats: null, downbeats: null, sections: [], words: [], lines: [] };
const BEAT = () => 60 / (SONG.bpm || 120);      // only used when there is no beat map
// beat position (float). With a beat map it interpolates between real beats (songs drift and accelerate).
function bpOf(t) {
  const B = SONG.beats; if (!B || B.length < 2) return (t - SONG.offset) / BEAT();
  if (t <= B[0]) return (t - B[0]) / (B[1] - B[0]);
  let lo = 0, hi = B.length - 1;
  if (t >= B[hi]) return hi + (t - B[hi]) / (B[hi] - B[hi - 1]);
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (B[m] <= t) lo = m; else hi = m; }
  return lo + (t - B[lo]) / (B[hi] - B[lo]);
}
const beatAt = n => { const B = SONG.beats; if (!B || B.length < 2) return SONG.offset + n * BEAT(); n = Math.round(n); return B[Math.max(0, Math.min(B.length - 1, n))]; };
const barAt = n => (SONG.downbeats || [])[n] ?? beatAt(n * 4);
// words of lyric line li (from the forced alignment), and the line being sung at time t
const lineWords = li => (SONG.words || []).filter(w => w.line === li && w.t0 != null);
const lineAt = t => { const ws = SONG.words || []; let cur = null; for (const w of ws) if (w.t0 != null && w.t0 <= t) cur = w.line; return cur; };
const barOf = t => bpOf(t) / 4;
const beatN = t => Math.floor(bpOf(t));
const frac = x => x - Math.floor(x);
const pulse = (t, k = 6) => Math.exp(-frac(bpOf(t)) * k);   // 1 on each beat, decays
const pulse8 = (t, k = 6) => Math.exp(-frac(bpOf(t) * 2) * k);
const barT = n => barAt(n);
const beatT = n => beatAt(n);

// ---- maths ----
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, x) => a + (b - a) * x;
const seg = (t, a, b) => clamp((t - a) / (b - a));
const ease = x => { x = clamp(x); return x * x * (3 - 2 * x); };
const easeOut = x => 1 - Math.pow(1 - clamp(x), 3);
const easeIn = x => Math.pow(clamp(x), 3);
const easeInOut = x => { x = clamp(x); return x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const expoOut = x => { x = clamp(x); return x === 1 ? 1 : 1 - Math.pow(2, -10 * x); };
const hash = i => { const x = Math.sin(i * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };
const hash2 = (a, b) => hash(a * 73.13 + b * 19.91);
function kf(t, keys, e = ease) {
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) if (t < keys[i][0]) {
    const [a, va] = keys[i - 1], [b, vb] = keys[i], k = e((t - a) / (b - a));
    return Array.isArray(va) ? va.map((v, j) => lerp(v, vb[j], k)) : lerp(va, vb, k);
  }
  return keys[keys.length - 1][1];
}
const boilSeed = t => Math.floor(t * BOIL);
// deterministic per-frame shake, changes at the boil rate
const shake = (t, amt) => { const f = boilSeed(t); return [(hash(f * 1.7) - .5) * 2 * amt, (hash(f * 2.3 + 9) - .5) * 2 * amt]; };

// ---- colours (hex -> [r,g,b] 0..1). accent/clay/red follow project.json look.accent (set in ENGINE.prepareData) ----
// look.accent: null (`taste apply --accent none`, `slop project set look.accent none`) = NO ACCENT: every accent role
// (accent, clay, red, ember) reads as the plain type colour INK.white, so the karaoke word, accent tokens, flash
// blocks and chrome highlights carry no colour emphasis, and the print looks drop their section accents and accent
// protection (post.js). Read live (getters), so it holds whenever window.PROJECT is set or changed.
const INK = {
  paper: '#eeede8', paper2: '#e6e4dc', ink: '#121212', night: '#0f1216', steel: '#6fa8d4', ice: '#9cc6e6',
  red: '#D97757', clay: '#D97757', accent: '#D97757', ember: '#db5c34', white: '#f4f2ec', grey: '#8a8a86',
};
const _ACCENT = { red: INK.red, clay: INK.clay, accent: INK.accent, ember: INK.ember };
const noAccent = () => { const L = (window.PROJECT || {}).look; return !!L && Object.prototype.hasOwnProperty.call(L, 'accent') && L.accent === null; };
for (const k of Object.keys(_ACCENT)) {
  Object.defineProperty(INK, k, { enumerable: true, configurable: true,
    get() { return noAccent() ? INK.white : _ACCENT[k]; }, set(v) { _ACCENT[k] = v; } });
}
const rgb = hex => { const s = String(hex || '#000').trim(); let h = s[0] === '#' ? s.slice(1) : s; if (h.length === 3) h = h.split('').map(c => c + c).join('');
  const n = parseInt(h.slice(0, 6), 16) || 0; return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; };

// ---- assets ----
// HTMLImageElement.decode() REFUSES large images when several decode at once (Chromium's decode budget): it rejects
// with "EncodingError: The source image cannot be decoded" although the file loaded (complete, naturalWidth > 0) —
// measured: 24 of 80 refused when 2912×1632 plates + depth maps were decoded 6 at a time. That reported good plates as
// MISSING (the media preflight stopped the render). Here a refused decode of a loaded image resolves (drawImage decodes
// on use); a file that did not load (naturalWidth 0) still rejects. Applies to every decode() on the engine page.
function robustDecode(d0) {
  const settle = im => new Promise((res, rej) => {
    if (im.complete) { if (im.naturalWidth > 0) res(); else rej(new Error('image failed to load: ' + im.src)); return; }
    im.addEventListener('load', () => res(), { once: true }); im.addEventListener('error', () => rej(new Error('image failed to load: ' + im.src)), { once: true });
  });
  return function () { return d0.call(this).catch(e => settle(this).catch(() => { throw e; })); };
}
(() => {
  const P = typeof HTMLImageElement !== 'undefined' && HTMLImageElement.prototype, d0 = P && P.decode;
  if (!d0 || d0._slop) return;
  const dec = robustDecode(d0); dec._slop = true; P.decode = dec;
})();
const IMG = {};         // name -> HTMLImageElement
const SEQ = {};         // clip name -> { n, fps, dir }
const _FAILED = new Set();          // sources that failed to load once (no retry storm on every frame)
const _MISSING = new Map();         // REQUIRED media that failed: absolute URL (or 'clip:<name>') -> why
const _FRAME_MISSING = new Set();   // required media requested but missing while drawing the current frame
// The decoded-image cache is capped by BYTES (width · height · 4 of every cached image), not by count: a 2912×1632
// plate is 19 MB decoded and its depth map as much again, so the old "keep 400 images" let one page hold several GB
// (four render workers did not fit a 15 GiB box). Least recently used goes first; an image the frame being drawn has
// used is never dropped. Budget: window.SLOP.cacheMiB, ?cache=MiB, PROJECT.cache_mib; default 320 MiB per page.
const CACHE_BYTES = Math.round((_pos(_SLOP.cacheMiB, _QS.get('cache'), _PJ0.cache_mib) || 320) * 1048576);
const _SIZE = new Map();            // cached name -> decoded bytes, least recently used first
const _USED = new Set();            // names the frame being drawn has used (pinned until dropCache() ends the frame)
const _PENDING = new Map();         // name -> the one in-flight load of it (callers share it: one decode per file)
const CACHE = { bytes: 0, peakBytes: 0, budget: CACHE_BYTES, evicted: 0, evictedBytes: 0, gcs: 0 };
const _abs = src => { try { return new URL(src, document.baseURI).href; } catch (e) { return String(src); } };
// a required file is missing: remembered for ENGINE.info().missingMedia, one console.error per file, and the current
// frame is marked (`slop render` refuses such frames unless --allow-missing)
function noteMissing(src, why = 'failed to load') {
  const k = /^clip:/.test(src) ? src : _abs(src);
  if (!_MISSING.has(k)) { _MISSING.set(k, why); console.error(`[media] missing: ${k} (${why})`); }
  _FRAME_MISSING.add(k);
}
const _touch = name => { const b = _SIZE.get(name); if (b !== undefined) { _SIZE.delete(name); _SIZE.set(name, b); } _USED.add(name); };
// opt.optional: a guessed path (e.g. the default depth map) — a failure is expected and is not reported
async function loadImage(name, src, opt = {}) {
  if (IMG[name]) { _touch(name); return IMG[name]; }
  if (_PENDING.has(name)) { _USED.add(name); return _PENDING.get(name); }
  if (_FAILED.has(src)) { if (!opt.optional) noteMissing(src); throw new Error('missing image ' + src); }
  const pr = (async () => {
    const im = new Image(); im.src = src;
    try { await im.decode(); } catch (e) { _FAILED.add(src); if (!opt.optional) noteMissing(src); throw e; }
    const b = (im.naturalWidth || 0) * (im.naturalHeight || 0) * 4;
    IMG[name] = im; _SIZE.set(name, b); CACHE.bytes += b; _USED.add(name);
    if (CACHE.bytes > CACHE.peakBytes) CACHE.peakBytes = CACHE.bytes;
    return im;
  })();
  _PENDING.set(name, pr); _USED.add(name);
  try { return await pr; } finally { _PENDING.delete(name); }
}
// a clip is a pre-extracted JPEG sequence: <dir>/f00001.jpg … (CLIPS[name] = {n, fps, dir}); dir is relative to <project>/engine/
async function clipFrame(name, localT) {
  const c = SEQ[name]; if (!c || !c.n) { noteMissing('clip:' + name, 'no frames: not in window.CLIPS (engine/clips.js)'); return null; }
  const i = clamp(Math.floor(localT * (c.fps || 24) + 1e-6), 0, c.n - 1) + 1;   // +1e-6: a time exactly on a frame boundary picks that frame
  try { return await loadImage(`${name}#${i}`, `${c.dir}/f${String(i).padStart(5, '0')}.jpg`); } catch (e) { return null; }
}
// ---- what the frame just drawn was made of (ENGINE.lastFrame, ENGINE.frameLayers) ----
// renderAt (timeline.js) ends every frame with dropCache(), so the frame's record is taken there: the images it used,
// the lyric tokens it marked (window.DRAWN), the default renderer's DEV_FRAME when this frame replaced it, and the
// chrome / device calls counted by the page's probes (index.html wraps chrome(), ENGINE.chrome, DEV.hud and
// ENGINE.drawDevice into ENGINE._frameHits).
let _prevDev = null;
const LAYER_KINDS = ['media', 'graphic', 'annotation', 'micro', 'lyric', 'chrome'], _NOTED = new Set(), _BADKIND = new Set();
// Bespoke chapter code declares the layers it draws with its own code (the engine sees plates / clip frames, KIN.mark,
// ENGINE.chrome and ENGINE.drawDevice by itself): ENGINE.noteLayer('graphic') while drawing a frame. Counting only:
// it never changes a pixel. Unknown kinds are ignored with one console warning.
function noteLayer(kind) {
  const k = String(kind || '').toLowerCase();
  if (!LAYER_KINDS.includes(k)) { if (!_BADKIND.has(k)) { _BADKIND.add(k); console.warn(`[layers] ENGINE.noteLayer: unknown kind '${kind}' (one of ${LAYER_KINDS.join(', ')})`); } return false; }
  _NOTED.add(k); return true;
}
function _endFrame() {
  const dev = window.DEV_FRAME || null, hits = ENGINE._frameHits || {};
  ENGINE.lastFrame = { used: [..._USED], missing: [..._FRAME_MISSING], lyric: window.DRAWN ? window.DRAWN.size : 0,
    dev: dev && dev !== _prevDev ? dev : null, hits: Object.assign({}, hits), noted: [..._NOTED] };
  _prevDev = dev;
  for (const k of Object.keys(hits)) hits[k] = 0;
  _NOTED.clear();
}
// The ANIMATION_GUIDE density rule: at least 3 ORDERED information layers in every frame — media + lyric + chrome +
// annotation / graphic. Counted for the last frame drawn, by kind (each kind once), in drawing order:
//   media       a plate or clip frame drew (not a placeholder for missing media; the 'motion' treatment has none)
//   graphic     a hero / flash device, a device drawn by chapter code, the code-drawn 'motion' base, or a treatment
//               that draws information over the footage ('contours', 'scan', 'diagram')
//   annotation  CV marks (brackets, tags, the lead mark)       micro   micro-type devices
//   lyric       sung words on screen (KIN.mark)                 chrome  the chrome / HUD through-line
// plus any kind the frame's own code declared with ENGINE.noteLayer(kind) (bespoke chapter code).
// → {count, layers: [...], noted, shot, treatment}; null before the first frame. `slop render check --layers` samples it.
const LAYER_RULE = 3;
function frameLayers() {
  const f = ENGINE.lastFrame; if (!f) return null;
  const d = f.dev, e = d && d.shot ? ((window.EDL || {})[d.shot] || {}) : {}, L = [];
  const usedMedia = f.used.some(n => /^plate:/.test(n) || (/#\d+$/.test(n) && !/^fx:/.test(n)));
  const motion = !!(d && d.treatment === 'motion');
  if (!f.missing.length && !motion && (usedMedia || (d && (e.plate || (Array.isArray(e.segs) && e.segs.length))))) L.push('media');
  if (motion || (d && /^(contours|scan|diagram)$/.test(String(d.treatment))) || (d && ((d.hero || []).length || (d.flash || []).length))
    || (!d && f.hits.devices > 0)) L.push('graphic');
  if (d && (d.cv || []).length) L.push('annotation');
  if (d && (d.micro || []).length) L.push('micro');
  if (f.lyric > 0 || (d && d.lyric)) L.push('lyric');
  if (f.hits.chrome > 0) L.push('chrome');
  const noted = (f.noted || []).filter(k => k !== 'media' || !f.missing.length);   // never media over a missing file
  const all = LAYER_KINDS.filter(k => L.includes(k) || noted.includes(k));
  return { count: all.length, layers: all, noted, rule: LAYER_RULE, ok: all.length >= LAYER_RULE, shot: d ? d.shot : null,
    treatment: d ? d.treatment : null, missingMedia: f.missing.length };
}
// The page's probes (index.html calls this once every engine, project and device file has loaded, before boot): count
// chrome / HUD and ENGINE.drawDevice calls per frame (ENGINE._frameHits, read by frameLayers) and make ENGINE.info()
// report the last frame's layers and the image cache. Wrappers only count; they never change what is drawn.
function installProbes() {
  const E = ENGINE, H = E._frameHits;
  const wrap = (obj, k, tag) => { const f = obj && obj[k]; if (typeof f !== 'function' || f._slopProbe) return;
    const g = function (...a) { H[tag] = (H[tag] || 0) + 1; return f.apply(this, a); }; g._slopProbe = true; obj[k] = g; };
  if (typeof window.chrome === 'function') wrap(window, 'chrome', 'chrome');
  wrap(E, 'chrome', 'chrome'); wrap(E, 'drawDevice', 'devices');
  const dev = () => { if (window.DEV) wrap(window.DEV, 'hud', 'chrome'); };
  if (window.DEV_LOADING && typeof window.DEV_LOADING.then === 'function') window.DEV_LOADING.then(dev); else dev();
  const info0 = E.info;
  if (typeof info0 === 'function' && !info0._slopProbe) {
    const g = (...a) => Object.assign(info0.apply(E, a) || {}, { frameLayers: frameLayers(), layerRule: LAYER_RULE, imageCache: Object.assign({}, CACHE) });
    g._slopProbe = true; E.info = g;
  }
  return true;
}
// the end of every frame (timeline.js renderAt): drop least-recently-used images until the cache is within budget
// (bytes) and within `keep` images, never one this frame used; then unpin. When anything was dropped and the page was
// started with --js-flags=--expose-gc (`slop render` does that), a GC runs so the decoded pixels go now, not whenever
// V8 next feels memory pressure (it does not count Blink's image memory, so it would wait far too long).
function dropCache(keep = 400, budget = CACHE.budget) {
  _endFrame();
  let freed = 0;
  if (CACHE.bytes > budget || _SIZE.size > keep) {
    for (const [n, b] of _SIZE) {
      if (CACHE.bytes <= budget && _SIZE.size <= keep) break;
      if (_USED.has(n) || _PENDING.has(n)) continue;
      _SIZE.delete(n); delete IMG[n]; CACHE.bytes -= b; CACHE.evicted++; CACHE.evictedBytes += b; freed += b;
    }
  }
  _USED.clear();
  if (freed && typeof window.gc === 'function') { try { window.gc(); CACHE.gcs++; } catch (e) { /* not exposed */ } }
  return freed;
}

// draw an image to cover a rect with a camera: cx, cy are the image point (0..1) at rect centre, zoom >= 1
function cover(ctx, im, o = {}) {
  const { x = 0, y = 0, w = W, h = H, cx = .5, cy = .5, zoom = 1, rot = 0, alpha = 1 } = o;
  const iwN = im.naturalWidth || im.width, ihN = im.naturalHeight || im.height;
  const s = Math.max(w / iwN, h / ihN) * zoom;
  const iw = iwN * s, ih = ihN * s;
  ctx.save(); ctx.globalAlpha = alpha; ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
  ctx.translate(x + w / 2, y + h / 2); if (rot) ctx.rotate(rot);
  // left/top edge of the image relative to the rect centre, clamped so the image always covers the rect
  const ox = o.free ? -cx * iw : clamp(-cx * iw, w / 2 - iw, -w / 2), oy = o.free ? -cy * ih : clamp(-cy * ih, h / 2 - ih, -h / 2);
  ctx.drawImage(im, ox, oy, iw, ih);
  ctx.restore();
}

// ---- the API object (extended by every later engine file; documented in engine/README.md) ----
const ENGINE = window.ENGINE = window.ENGINE || {};
Object.assign(ENGINE, {
  version: '1', W, H, FPS, PORTRAIT, U: UNIT,
  urls: { engine: _SLOP.engine || '', project: _SLOP.project || '', projectEngine: _SLOP.projectEngine || '' },
  // a project media path → absolute URL (relative paths resolve against <project>/engine/, the document base)
  url: rel => { try { return new URL(rel, document.baseURI).href; } catch (e) { return rel; } },
  get project() { return window.PROJECT || (window.PROJECT = {}); },
  // the depth licence rule: only Depth-Anything-V2-Small (Apache-2.0) derived depth is ever used. The plate's
  // depth_model (stamped by `slop edit export`) or PROJECT.depth_model must name it; unlabelled depth is unknown → flat.
  DEPTH_RE: /depth[-_ ]?anything.*v2.*small/i,
  depthOK(meta) {
    const m = String((meta && meta.depth_model) || (window.PROJECT || {}).depth_model || '');
    return !!m && ENGINE.DEPTH_RE.test(m) && !/large|base|giant/i.test(m);
  },
  noteMissing,
  // the decoded-image cache: {bytes, peakBytes, budget, evicted, evictedBytes, gcs} (budget in bytes; see dropCache)
  cache: CACHE,
  // the last frame's information layers (≥ 3 required): {count, layers, rule, ok, shot, treatment, missingMedia}
  frameLayers, layerRule: LAYER_RULE, lastFrame: null, _frameHits: { chrome: 0, devices: 0 }, installProbes,
  noteLayer, layerKinds: LAYER_KINDS,     // chapter code: ENGINE.noteLayer('graphic') for a layer it draws itself
  robustDecode,      // the decode() wrapper (above), exposed for tests
});
// media that failed to load (required files only): [{src, why}]; and the ones the frame being drawn asked for
Object.defineProperties(ENGINE, {
  missingMedia: { get: () => [..._MISSING].map(([src, why]) => ({ src, why })), configurable: true },
  frameMissing: { get: () => [..._FRAME_MISSING], configurable: true },
});
