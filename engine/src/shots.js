// shots.js — the default renderer: one scene per storyboard shot (window.SHOTS = board/shots.json, exported by
// `slop edit export`; window.SHOTLIST, the older name, is read too), footage from window.EDL. Loaded AFTER the chapter
// files: a shot whose time range a chapter scene already covers is skipped, so bespoke chapter code overrides the default.
// The default is complete on its own, so the film always renders end to end. For each shot at time t it draws:
//   1  the base: plate still / clip frame through the shot's 2.5D treatment family (devices/treat.js; two consecutive 2.5D
//      shots never share a treatment) and the camera (the storyboard's camera words + the shot's cam.* devices, played by
//      window.HITS when present; with none, the source's kick: zoom + .018 · KIN.kickBar(t))
//   2  the shot's devices[] through the registry (devices/*.js) under the per-frame ELEMENT BUDGET:
//      one lyric block + one hero device + ≤ 2 CV marks (the lead's own mark counts) + ≤ 2 micro devices holding ≤ 3 rows of
//      micro type in all (a coverline's micro rows count first) + the chrome; the accent on ≤ 2 elements (the lyric claims
//      first, then a treatment's accent mark, then the devices); ≤ 3 full-frame flashes in any second across flash devices,
//      flash-cut transitions and stills-in-rhythm crop flashes, planned around the frame changes that happen anyway
//      (every other designed transition, every cut into a stills shot) — rejected flashes do not fire; while a full-frame
//      card / black / paper flash is up the CV marks, micro and hero devices wait (the footage they mark is hidden), and
//      while the hero replaces the footage (powers of ten's map: DEV.covers) the CV marks, micro devices and the
//      treatment's own marks on the footage (the stills strip, the diagram) wait
//   3  the lyric type from type[] modes (subtitle · coverline · masthead · stack · mass): every token exactly at its t0,
//      motion on the beat; a sung line no entry covers is drawn as a subtitle, so the lyric gate stays N/N
//   4  the chrome (the project's chrome() when it defines one, else DEV.hud)
//   5  transition_in presets (through · whip · flashCut · dither · fade · flap · smear · match · flash · iris · push, and any
//      name in ENGINE.transitions; never the same preset as the shot just before: a repeat is demoted to a cut)
// Fields read (ARCHITECTURE §4.5; see engine/DEVICES.md): id, t0, t1, section, lines, lead_on_screen, framing, camera,
// type[{line, mode, placement, words, …}], devices[{kind, anchor, params, key, at, until}], treatment, transition_in,
// chrome, accent, look, screen, lift, subject_uv (the subject's image-space box when there are no detections); also the
// gap-1 names lyric[] (= type[]), trans_in, camera_fx.
// NOTHING IS REPAIRED SILENTLY: every repair of the plan (a rotated treatment, a demoted or unknown transition, a dropped
// flash, an unknown kind, a malformed param, a word that is not sung in its shot, an anchor with nothing to point at) and
// every device that throws when the page boots (a dry run of every device and type entry) is reported once on the page
// console as '[devices] …' (`slop render info` returns the page console) and listed in ENGINE.info().deviceWarnings.
// ('[devices]', not engine-core's '[device]' prefix: that one marks device FAILURES, which the docs' render checks forbid.)
// THE COLLISION RULE (Quick E2E: a CV label sat under a lyric word): every lyric block is measured on every frame (its
// mode's own layout, DEV.type.measure) and nothing else covers it — panels move off it, CV labels flip to another corner
// of their box or drop, CV strokes and a treatment's own marks are clipped / moved, chrome items on it are taken out.
// QA hooks: window.DEV_FRAME (what the last frame drew and why: incl. the placed device boxes and the lyric box; the
// flash / hero / cv / micro lists hold only devices that drew something on that frame — core.js ENGINE.frameLayers()
// reads them for the "≥ 3 layers per frame" count that `slop render check --layers` uses, the one layer counter),
// window.SHOT_WARNINGS, window.DEV_ERRORS (render-time exceptions; also reported), window.SHOTS_PLAN() (the resolved plan:
// treatments, device windows, accepted/rejected flashes). ENGINE.info() adds: deviceWarnings, deviceErrors, chapterScenes
// (the scenes registered by bespoke chapter code, which the default renderer leaves alone) with chapterShots (the
// storyboard shots they cover), and treatments (per shot: the 2.5D family, its kind and guide code, picked automatically
// or asked, and the family it actually draws when that differs: a multiplane plate with no subject plane draws layers).
// Port of the engine's shots.js (51 lines: media + EV lyric modes + leadKit + chrome + 5 regex transitions). Intentional
// changes: data-driven devices, treatments, budget and flash rule; no project look names (sections map to look keys by
// order: the second chorus is 'chorus2' — the source used EV's own times); placement 'right' hangs from the right margin;
// the transition rule compares with the previous shot only (as `slop board audit` does), so whip · cut · whip is allowed.
'use strict';
(() => {
  // ---- the device library loads right after this file when the page did not include it (one <script> for the page)
  const FILES = ['_base.js', 'type.js', 'cv.js', 'ui.js', 'cards.js', 'flap.js', 'gauges.js', 'charts.js', 'voice.js', 'explain.js', 'flash.js', 'camera.js', 'hud.js', 'treat.js', 'trans.js'];
  window.DEVICE_FILES = FILES;
  if (!window.DEV || !window.DEV._base) {
    const me = (document.currentScript && document.currentScript.src) || '', dir = me ? me.replace(/[^/]*$/, '') + 'devices/' : 'devices/';
    if (document.readyState === 'loading') FILES.forEach(f => document.write(`<script src="${dir}${f}"><\/script>`));
    else window.DEV_LOADING = FILES.reduce((pr, f) => pr.then(() => new Promise(res => { const s = document.createElement('script'); s.src = dir + f; s.onload = s.onerror = res; document.head.appendChild(s); })), Promise.resolve());
  }
  if (typeof scene !== 'function') return;                                     // no timeline on this page (a device bench)
  const PRE = new Set(typeof SCENES !== 'undefined' ? SCENES : []);            // registered before this file: the project layer (chapters)

  const SL = window.SHOTS || window.SHOTLIST || {}, LIST = (Array.isArray(SL) ? SL : SL.shots) || [];
  const shots = LIST.filter(s => s && s.id != null && isFinite(+s.t0) && isFinite(+s.t1) && +s.t1 > +s.t0).map(s => Object.assign({}, s, { id: String(s.id), t0: +s.t0, t1: +s.t1 }))
    .sort((a, b) => a.t0 - b.t0);
  const covered = (a, b) => SCENES.some(s => !s.isDefault && s.t0 < b - .05 && s.t1 > a + .05);
  const PJ = () => window.PROJECT || {};
  const errs = window.DEV_ERRORS = window.DEV_ERRORS || [];
  const report = s => { const D = window.DEV; if (D && D.report) D.report(s); else { try { console.warn('[devices] ' + s); } catch (e) { /* no console */ } } };
  const note = (where, e) => { const s = `${where}: ${e && e.message || e}`; if (errs.length < 200 && !errs.includes(s)) { errs.push(s); report(`render error — ${s} (the frame still renders without it; fix the shot's entry)`); } };
  const dropped = LIST.length - shots.length;
  const loadWarn = dropped > 0 ? [`${dropped} storyboard shot(s) skipped: each needs an id and numeric t0 < t1`] : [];

  // ---------------------------------------------------------------------------------------------------- the plan --
  // everything decided once from static data (shots, lyrics, beats, hits, EDL): treatments, device windows, the flash
  // budget, the transition sequence. Memoised and re-made only when the data it reads changes (boot merges the beats).
  let PLAN = null, KEY = null;
  const sectionKey = () => { const n = {}; return sh => { const s = String(sh.section || '').toLowerCase();
    const base = /hook|intro|open/.test(s) ? 'hook' : /pre/.test(s) ? 'pre' : /final|last/.test(s) ? 'final' : /outro|end|coda/.test(s) ? 'outro' : /drop/.test(s) ? 'drop'
      : /bridge|break/.test(s) ? 'bridge' : /chorus|hook2/.test(s) ? 'chorus' : /verse/.test(s) ? 'verse' : null;
    if (!base) return null; if (base === 'chorus' || base === 'verse') { const id = s.replace(/\s+/g, ''); n[base] = n[base] || []; if (!n[base].includes(id)) n[base].push(id);
      const k = n[base].indexOf(id); return base === 'verse' ? (k ? 'verse2' : 'verse1') : (k ? 'chorus2' : 'chorus'); } return base; }; };
  function lookOf(sh, key) {
    const over = {}; if (sh.accent) over.accent = sh.accent; if (sh.screen) over.mode = sh.screen; if (typeof sh.lift === 'number') over.lift = sh.lift;
    const E = window.ENGINE, projLook = typeof look === 'function' && !(E && look === E.look);
    try {
      if (projLook) return look(sh.look || key || 'verse1', over) || {};                       // the project's own looks (common.js)
      if (E && typeof E.look === 'function') return (sh.look ? E.look(sh.look, over) : E.lookFor ? E.lookFor(sh) : E.look(key, over)) || {};
    } catch (e) { note(`look(${sh.look || key})`, e); }
    return Object.assign({ mode: 'native', accent: PJ().accent || '#D97757' }, over);
  }
  const NUMF = ['line', 'size', 'x', 'y', 'w', 'fit', 'maxSize', 'lead', 'rows', 'keep', 'ruleW'];
  // a type[] entry as the renderer reads it (numbers from strings, the line checked against the lyrics and the shot)
  function typeEntries(sh, S, warn) {
    const D = window.DEV, ty = Array.isArray(sh.type) ? sh.type : Array.isArray(sh.lyric) ? sh.lyric : [];
    if (sh.type != null && !Array.isArray(sh.type) && typeof sh.type !== 'string') warn.push(`${sh.id}: type should be a list of {line, mode, …} — ignored (the sung lines still show as subtitles)`);
    const out = [];
    ty.forEach(e0 => {
      if (!e0 || typeof e0 !== 'object' || e0.line == null) return;          // prose type entries are allowed (and ignored)
      const e = Object.assign({}, e0); NUMF.forEach(k => { if (e[k] != null) e[k] = D.num(e[k]); });
      const ln = D.line(e.line);
      if (!ln || !ln.tokens || !ln.tokens.length) { warn.push(`${sh.id}: type entry line ${D.short(e0.line)} has no sung words (lines count from 0; see engine/lyrics.js) — skipped`); return; }
      if (e.mode != null && !D.type.MODE[String(e.mode).toLowerCase()]) warn.push(`${sh.id}: type mode '${e.mode}' is not one of subtitle · coverline · masthead · stack · mass → subtitle`);
      if (ln.t1 < sh.t0 - .05 || ln.t0 > sh.t1 + .05) warn.push(`${sh.id}: type line ${e.line} is sung at ${ln.t0.toFixed(2)}–${ln.t1.toFixed(2)} s, outside this shot (${sh.t0.toFixed(2)}–${sh.t1.toFixed(2)} s) — it shows only where the shots overlap; put the entry on the shot that covers it`);
      if (S.treat.family === 'occlusion' && e.behind == null) e.behind = 'matte';
      out.push(e);
    });
    return out;
  }
  // the biggest type a non-line hero sets vs the lyric on screen with it ("the lyric is the biggest type unless a device is the
  // line"): a bigger one is CAPPED at the lyric's size — its type params scaled down (spec.capType(p, k), else params.size),
  // once, in the plan, so it never resizes mid-shot — and reported. A device that IS the line (params.is_line, or a line
  // it carries) keeps its size.
  function typeBudget(S, d, warn) {
    const D = window.DEV; if (d.role !== 'hero' || !d.spec.typeSize || d.p.line != null || d.p.is_line) return;
    const size = +d.spec.typeSize(d.p); if (!(size > 0)) return;
    let lyr = 0;
    for (const en of S.type) { const w = D.type.entryWindow(en, S.sh); if (w && w[0] < d.t1 && w[1] > d.t0) lyr = Math.max(lyr, D.type.sizeOf({ en })); }
    if (!lyr && (window.LYR || []).some(l => l.t0 < d.t1 && l.t1 + 1 > d.t0)) lyr = D.type.sizeOf(null);
    if (!(lyr && size > lyr + .5)) return;
    const k = lyr / size, cap = d.spec.capType || ((p, f) => { if (typeof p.size === 'number') p.size = p.size * f; });
    let after = size; try { cap(d.p, k); after = +d.spec.typeSize(d.p); } catch (e) { after = size; }
    d.capped = { from: Math.round(size), to: Math.round(after) };
    const said = `${S.id}: '${d.kind}' sets ${Math.round(size)} px type over a ${Math.round(lyr)} px lyric`;
    if (after > lyr + .5) warn.push(`${said} — the lyric should be the biggest type unless the device is the line; it could not be capped (shrink its type params, or set params.is_line: true when it is the line)`);
    else warn.push(`${said} → capped at ${Math.round(after)} px (the lyric is the biggest type unless the device is the line: set params.is_line: true when it is)`);
  }
  function plan() {
    const D = window.DEV;
    const key = `${SONG.beats ? SONG.beats.length : 0}:${(window.LYR || []).length}:${window.HITS ? 1 : 0}:${D && D.treat ? 1 : 0}`;
    if (PLAN && KEY === key) return PLAN;
    const warn = loadWarn.slice(), sk = sectionKey(), byId = {}, flashes = [], noLead = [];
    // clean or print, per shot: its own look (a `screen: "native"` shot in a print film is clean, and the reverse)
    const keys = shots.map(sh => sk(sh)), pm = String((PJ().look || {}).mode || PJ().look || '').toLowerCase(), pmClean = /^(native|clean|clean-grade)$/.test(pm);
    const cleanShot = shots.map((sh, i) => { const L = lookOf(sh, keys[i]); return pmClean || L.mode === 'native' || L.mode === 'clean'; });
    const cleanOf = i => !!cleanShot[i], clean = shots.length ? cleanOf(0) : pmClean;
    const tp = D.treat.plan(shots, { clean, cleanOf }); warn.push(...tp.warn);
    let prevTr = null;
    const list = shots.map((sh, i) => {
      const S = { id: sh.id, sh, i, t0: sh.t0, t1: sh.t1, treat: tp.list[i], lookKey: keys[i], clean: cleanOf(i), devices: [], cams: [], type: [], covered: covered(sh.t0, sh.t1) };
      const W_ = S.covered ? [] : warn;                                         // a chapter scene owns a covered shot: no warnings for it
      const hasLead = D.hasSubject ? D.hasSubject(sh) : true;
      if (sh.devices != null && !Array.isArray(sh.devices)) W_.push(`${sh.id}: devices should be a list of {kind, anchor, params, key} — ignored`);
      const raw = [].concat(Array.isArray(sh.devices) ? sh.devices : [], sh.camera_fx && typeof sh.camera_fx === 'object' ? Object.entries(sh.camera_fx).map(([k, v]) => ({ kind: 'cam.' + k, params: typeof v === 'object' ? v : { amp: v } })) : []);
      raw.forEach((r, j) => {
        if (!r || typeof r !== 'object') { W_.push(`${sh.id}: devices[${j}] is not an object {kind, …} — skipped`); return; }
        const inst = D.instance(r, sh, j); if (inst.err) { W_.push(`${sh.id}: ${inst.err}`); return; }
        (inst.warn || []).forEach(w => W_.push(`${sh.id}: ${w}`));
        const ap = inst.role !== 'camera' && D.anchorProblem ? D.anchorProblem(inst.anchor, sh, hasLead) : null; if (ap) W_.push(`${sh.id}: ${inst.kind}: ${ap}`);
        (inst.role === 'camera' ? S.cams : S.devices).push(inst); });
      if (sh.lead_on_screen && !S.devices.some(d => d.kind === 'cv.lead')) {
        if (hasLead) { const inst = D.instance({ kind: 'cv.lead', anchor: 'lead', key: 'B', params: { face: /^(E?CU|MCU)$/i.test(String(sh.framing || '')) } }, sh, -1); inst.pri = -1; inst.auto = true; S.devices.push(inst); }
        else if (!S.covered) noLead.push(sh.id);
      }
      S.type = typeEntries(sh, S, W_);
      S.devices.forEach(d => typeBudget(S, d, W_));
      // the flash budget's candidates: flash devices (cards first), the stills crops, the flash-cut transitions
      S.devices.forEach(d => { if (d.spec.flashes) d.spec.flashes(d).forEach(f => flashes.push(Object.assign({ shot: sh.id }, f))); });
      if (S.treat.family === 'stills' && S.treat.params.flash !== false) D.stillsFlashes(S, S.treat.params).forEach(t => flashes.push({ t, pri: 1, src: 'stills', shot: sh.id }));
      // the entry transition: never the same preset as the shot just before (a repeat becomes a cut)
      const want = sh.transition_in ?? sh.trans_in ?? sh.trans;
      let tr = S.covered ? null : D.trans.parse(want);
      if (tr && !tr.preset) { W_.push(`${sh.id}: transition ${JSON.stringify(tr.unknown)} is not a preset (${D.trans.names().join(' · ')}) → hard cut`); tr = null; }
      if (tr && S.clean && tr.preset === 'dither') tr = { preset: 'fade', opts: Object.assign({}, tr.opts, { dur: tr.opts.dur ?? .45 }) };   // dither is print texture: a crossfade in a clean look (as the engine's own dither)
      if (tr && S.clean && tr.preset === 'smear') W_.push(`${sh.id}: transition 'smear' is a print-look texture (a xerox scan band) in a clean look — kept because the board asks for it; prefer whip · through · match · fade`);
      if (tr && i > 0 && tr.preset === prevTr) { W_.push(`${sh.id}: transition '${tr.preset}' repeats the previous shot's transition → cut (never the same device twice in a row)`); tr = null; }
      prevTr = tr ? tr.preset : null;
      if (tr) { D.trans.flashTimes(tr, sh.t0).forEach(t => flashes.push({ t, pri: 2, src: 'trans:' + tr.preset, shot: sh.id }));
        D.trans.fixedTimes(tr, sh.t0).forEach(t => flashes.push({ t, fixed: true, src: 'trans:' + tr.preset, shot: sh.id })); }
      if (i > 0 && !S.covered && S.treat.family === 'stills') flashes.push({ t: sh.t0, fixed: true, src: 'cut-to-stills', shot: sh.id });
      S.tr = tr; byId[sh.id] = S; return S;
    });
    if (noLead.length) warn.push(`no lead mark on ${noLead.length} lead_on_screen shot(s) with no subject box (no detections, no subject_uv, no usable depth map): ${noLead.slice(0, 12).join(', ')}${noLead.length > 12 ? ', …' : ''} — add "subject_uv": [u, v, w, h] (image space 0..1) to those shots`);
    const flash = D.flashPlan(flashes);
    const rej = {}; flash.rejected.forEach(f => { const k = `${f.shot}|${f.src}`; (rej[k] = rej[k] || []).push(f.t); });
    Object.entries(rej).forEach(([k, ts]) => { const [id, src] = k.split('|');
      warn.push(`${id}: ${ts.length} full-frame flash${ts.length > 1 ? 'es' : ''} from ${src} dropped at ${ts.slice(0, 6).map(v => v.toFixed(2)).join(', ')}${ts.length > 6 ? ', …' : ''} s (≤ 3 full-frame flashes in any second, counting the transitions around them)`); });
    const fx = [...new Set(flashes.filter(f => f.fixed).map(f => Math.round(f.t * 1000)))].map(v => v / 1000).sort((a, b) => a - b);
    for (let k = 3; k < fx.length; k++) if (fx[k] - fx[k - 3] < 1) { warn.push(`the transitions at ${fx.slice(k - 3, k + 1).map(v => v.toFixed(2)).join(', ')} s alone are 4 big frame changes in one second — the master may fail the flash check: make one of them a hard cut`); break; }
    list.forEach(S => { if (S.tr) S.trans = D.trans.make(S.tr, { flashOk: t => flash.has(t), t0: S.t0 }); });
    PLAN = { list, byId, flash, warn, clean }; KEY = key; window.SHOT_WARNINGS = warn;
    warn.forEach(report);
    return PLAN;
  }
  window.SHOTS_PLAN = () => { try { return plan(); } catch (e) { note('plan', e); return null; } };

  // ------------------------------------------------------------------------------------------------- per frame ----
  // the lyric block for t: the newest of the shot's active type entries and the active sung line (so a line no entry
  // covers is still drawn, as a subtitle, the moment it starts)
  function pickType(S, t) {
    const D = window.DEV; let best = null;
    for (const en of S.type) { const w = D.type.entryWindow(en, S.sh); if (!w) continue; const [a, z, ln] = w;
      if (t >= a && t <= z) { const st = Math.max(a, ln.t0 - .02); if (!best || st >= best.start) best = { en, ln, start: st }; } }
    // the sung line wins when no active entry covers it and it is newer than the best entry (a fading line loses to the
    // next one at once, so the next line's first word is on screen on its t0)
    const ln = D.type.activeLine(t);
    if (ln && !(best && best.en.line === ln.line) && (!best || ln.t0 - .02 > best.start + 1e-6)) best = { auto: true, ln, start: ln.t0 - .02 };
    return best;
  }
  // THE COLLISION RULE: nothing else covers a lyric block. Every lyric block the shot can show (its type entries, and the
  // sung lines no full entry covers: they show as subtitles) is measured on each frame with the mode's own layout
  // (DEV.type.measure: the block's extent over its whole time on screen, through this frame's camera and lead) and padded by
  // PAD px. A device keeps off every block whose time on screen overlaps its own window (X.avoidFor → x.avoid: panels move,
  // CV labels flip or drop — so nothing jumps when the next line comes in); the CV strokes, the treatments' own marks and
  // the chrome keep off the blocks on screen now (X.avoidNow). Same rule in 9:16 (the measure uses the portrait layout).
  const PAD = 14;
  async function lyricBlocks(S, t, X) {
    const D = window.DEV, out = [], exit = ln => (D.has.KIN() ? KIN.exitOf(ln) : ln.t1 + 1) + .2, whole = new Set();
    for (const en of S.type) { const w = D.type.entryWindow(en, S.sh); if (!w) continue;
      if (!Array.isArray(en.words) && w[0] <= w[2].t0 + .05 && w[1] >= exit(w[2]) - .05) whole.add(w[2].line);
      out.push({ a: w[0], z: w[1], pick: { en, ln: w[2] }, line: w[2].line }); }
    for (const ln of window.LYR || []) { if (!ln || !ln.tokens || !ln.tokens.length || whole.has(ln.line)) continue;
      const a = ln.t0 - .02, z = exit(ln); if (a < S.t1 && z > S.t0) out.push({ a, z, pick: { auto: true, ln }, line: ln.line, auto: true }); }
    for (const k of out) { let r = null; try { r = await D.type.measure(k.pick, X); } catch (e) { note(`${S.id} lyric measure`, e); }
      k.rect = r && r.every(isFinite) ? [r[0] - PAD, r[1] - PAD, r[2] + 2 * PAD, r[3] + 2 * PAD] : null; }
    return out.filter(k => k.rect);
  }
  // the chrome over a lyric block: drawn on its own layer first; when any of it lands on a block on screen, the items that
  // do are taken out whole and the rest is kept → the count. An item: the chrome's ink in 4 px cells, joined across gaps of
  // up to 5 cells (20 px) sideways and 1 cell down — letters into words and rows, so a corner label, the bar counter, the
  // progress line or a ruler of any height goes as one piece. A block covers whole pixels ([x0, y0, x1, y1)), the same
  // for the cut and for the ink count (DEV_FRAME.chrome.ink: always 0)
  let CHL = null;
  const pxOf = r => [Math.max(0, Math.floor(r[0])), Math.max(0, Math.floor(r[1])), Math.min(W, Math.ceil(r[0] + r[2])), Math.min(H, Math.ceil(r[1] + r[3]))];
  function inkIn(g, r) { const [x0, y0, x1, y1] = pxOf(r);
    if (x1 <= x0 || y1 <= y0) return 0; const d = g.getImageData(x0, y0, x1 - x0, y1 - y0).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 6) n++; return n; }
  function cutItems(g, rects) {
    const S = 4, gw = Math.ceil(W / S), gh = Math.ceil(H / S), d = g.getImageData(0, 0, W, H).data, on = new Uint8Array(gw * gh), seen = new Uint8Array(gw * gh), st = [];
    for (let y = 0, i = 3; y < H; y++) { const row = ((y / S) | 0) * gw; for (let x = 0; x < W; x++, i += 4) if (d[i] > 6) on[row + ((x / S) | 0)] = 1; }
    let n = 0;
    for (const r of rects) { const [x0, y0, x1, y1] = pxOf(r);
      for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
        if (d[(y * W + x) * 4 + 3] <= 6) continue; const s0 = ((y / S) | 0) * gw + ((x / S) | 0); if (seen[s0]) continue;
        n++; seen[s0] = 1; st.push(s0);                                              // one item: everything its ink joins
        while (st.length) { const c = st.pop(), cx = c % gw, cy = (c / gw) | 0; g.clearRect(cx * S - 1, cy * S - 1, S + 2, S + 2);
          for (let yy = Math.max(0, cy - 1); yy <= Math.min(gh - 1, cy + 1); yy++) for (let xx = Math.max(0, cx - 5); xx <= Math.min(gw - 1, cx + 5); xx++) {
            const q = yy * gw + xx; if (on[q] && !seen[q]) { seen[q] = 1; st.push(q); } } } } }
    return n;
  }
  function chromeOff(o, cut, draw) {
    if (!cut.length) { draw(o); return { cut: 0, ink: 0 }; }
    const D = window.DEV; CHL = CHL || D.mk(W, H); const g = CHL.getContext('2d', { willReadFrequently: true });
    const fresh = () => { if (g.reset) g.reset(); else { g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; } };
    fresh(); cut.forEach(r => { const [x0, y0, x1, y1] = pxOf(r); g.clearRect(x0, y0, x1 - x0, y1 - y0); }); draw(g);
    if (!cut.some(r => inkIn(g, r))) { draw(o); return { cut: 0, ink: 0 }; }        // clear of every block: drawn as usual
    fresh(); g.clearRect(0, 0, W, H); draw(g); g.setTransform(1, 0, 0, 1, 0, 0);
    const n = cutItems(g, cut);
    o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = 1; o.globalCompositeOperation = 'source-over'; o.drawImage(CHL, 0, 0); o.restore();
    return { cut: n, ink: cut.reduce((s, r) => s + inkIn(g, r), 0) };
  }
  async function drawShot(sh, b, o, t, lt, dur) {
    const D = window.DEV;
    if (window.DEV_LOADING) await window.DEV_LOADING;
    if (!D || !D._base || !D.treat) { b.fillStyle = '#0f1216'; b.fillRect(0, 0, W, H); note('shots.js', 'the device library did not load (engine/src/devices/*.js)'); return {}; }
    const P = plan(), S = P.byId[sh.id]; D.begin(t);
    const L = lookOf(sh, S.lookKey), light = window.ENGINE && ENGINE.inkFor ? ENGINE.inkFor(L).light : (L.mode !== 'native' && ((L.lift || 0) > .4 || L.mode === 'bit' || L.mode === 'dot'));
    const acc = sh.accent || L.accent || PJ().accent || D.C.accent;
    const X = D.frame({ t, sh, L, b, o, accent: acc, lightGround: light, flashOk: tt => P.flash.has(tt) });
    // the budget, part 1: what is on screen at t; the lyric claims the first accent before anything is drawn
    const act = S.devices.filter(d => D.active(d, t)), newest = (a, c) => (c.pri - a.pri) || (c.t0 - a.t0);
    const flash = act.filter(d => d.role === 'flash').sort(newest).slice(0, 1);
    // a card that IS the line takes the lyric's place while it is up (only when the flash rule lets it fire); while a
    // full-frame card / black / paper flash is up the footage is hidden, so the marks and graphics on it wait
    const firing = d => D.flashFiring ? D.flashFiring(d, t, tt => P.flash.has(tt)) : P.flash.has(d.t0);
    const isLine = flash.some(d => d.p.kind === 'card' && d.p.line != null && firing(d));
    const opaque = flash.some(d => /^(card|black|paper)$/.test(String(d.p.kind)) && firing(d));
    const ty = isLine ? null : pickType(S, t); if (ty) X.accLeft--;              // the lyric claims the first accent
    // the hero is chosen before the base: one that replaces the footage (powers of ten's map) holds every mark drawn on
    // the footage — the treatment's own (the stills strip, the diagram), the CV marks and the micro devices
    const hero = opaque ? [] : act.filter(d => d.role === 'hero').sort(newest).slice(0, 1);
    const covering = hero.find(d => D.covers && D.covers(d, t)) || null; X.covered = !!covering;
    // camera: the storyboard's words, then every camera device (or the source's kick when the shot names none)
    const cam = typeof MEDIA !== 'undefined' ? MEDIA.camFrom(sh.camera || '', clamp(lt / dur), { t, amt: 1 }) : { zoom: 1.06, cx: .5, cy: .5 };
    const fx = D.camFx(S.cams, t, sh);
    if (!S.cams.length && !/static|locked|lock-off/i.test(String(sh.camera || ''))) cam.zoom = (cam.zoom || 1.06) + .018 * (D.has.KIN() ? KIN.kickBar(t) : D.kick(t));
    // 1 the base (a treatment's accent mark takes the next accent; its marks on the overlay wait in X.defer for the lyric
    // blocks, so they can keep off them, and those that give way to the devices — the stills strip — in X.under)
    X.defer = []; X.under = [];
    let m = null; try { m = await D.treat.draw(b, o, S, t, cam, fx, X); } catch (e) { note(`${sh.id} base`, e); }
    if (!m && S.treat.family !== 'motion') { b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.fillStyle = light ? D.C.paper : D.C.night; b.fillRect(0, 0, W, H); b.restore(); }
    X.m = m; X.lead = D.leadOf(m) || (D.subjectOf ? await D.subjectOf(sh, m).catch(() => null) : null);
    // the lyric blocks (THE COLLISION RULE above), then the treatment's deferred marks
    const blocks = await lyricBlocks(S, t, X), fade = d => d.role === 'flash' || d.role === 'camera' ? 0 : (d.p.fadeOut ?? .2);
    X.lyricBlocks = blocks; X.avoidNow = blocks.filter(k => t >= k.a && t <= k.z).map(k => k.rect); X.avoid = X.avoidNow.slice();
    X.avoidFor = d => blocks.filter(k => k.a < d.t1 + fade(d) && k.z > d.t0).map(k => k.rect);
    for (const f of X.defer.splice(0)) { try { await f(); } catch (e) { note(`${sh.id} treatment marks`, e); } }
    // the budget, part 2: one hero (above), ≤ 2 CV marks, ≤ 2 micro devices with ≤ 3 micro rows in all (a coverline's rows first)
    const hidden = opaque || !!covering, cv = hidden ? [] : act.filter(d => d.role === 'cv').sort(newest).slice(0, 2);
    const coverRows = ty && ty.en && D.type.MODE[String(ty.en.mode || '').toLowerCase()] === 'cover' && Array.isArray(ty.en.micro) ? Math.min(3, ty.en.micro.length) : 0;
    let rowsLeft = 3 - coverRows; const micro = [];
    for (const d of hidden ? [] : act.filter(d => d.role === 'micro').sort(newest)) { if (micro.length >= 2) break; const r = d.spec.microRows ? +d.spec.microRows(d.p) || 0 : 1; if (r > rowsLeft) continue; rowsLeft -= r; micro.push(d); }
    // the block drawn now (the one pickType chose), as measured: what DEV_FRAME reports and the chrome / CV strokes keep off
    const now = ty ? blocks.find(k => ty.auto ? k.auto && k.line === ty.ln.line : k.pick.en === ty.en) : null;
    if (now && !X.avoidNow.includes(now.rect)) X.avoidNow.push(now.rect);
    // what drew (DEV_FRAME lists only devices that put something on this frame: a flash that does not fire, or a device
    // whose params leave it nothing to draw, is not a layer — ENGINE.frameLayers() counts these lists)
    const shown = { flash: [], cv: [], micro: [], hero: [] };
    const run = async (list, tag) => { for (const d of list) { try { const x = await D.draw(o, b, d, t, X); if (x && x.drew !== false && (tag !== 'flash' || firing(d))) shown[tag].push(d.kind); } catch (e) { note(`${sh.id} ${tag} ${d.kind}`, e); } } };
    await run(flash, 'flash'); await run(cv, 'cv'); await run(micro, 'micro'); await run(hero, 'hero');
    // the treatment's marks that give way to the devices (the stills strip): left out where a device was placed, else drawn beneath them
    for (const f of X.under.splice(0)) { try { await f(); } catch (e) { note(`${sh.id} treatment marks`, e); } }
    // 3 the lyric block
    let lyric = null;
    if (ty) { try { let box = null;
      if (ty.auto) { box = await D.type.sub(o, b, ty.ln, t, { accent: acc, defInk: light ? D.C.dark : D.C.light }); lyric = { mode: 'subtitle', line: ty.ln.line, auto: true }; }
      else { box = await D.type.entry(o, b, ty.en, t, X); lyric = { mode: ty.en.mode || 'subtitle', line: ty.en.line }; }
      if (lyric && box) lyric.box = box.map(v => Math.round(v)); } catch (e) { note(`${sh.id} type`, e); } }
    if (PJ() && typeof PJ().shotExtras === 'function') { try { await PJ().shotExtras(o, b, m, sh, t, lt, dur); } catch (e) { note(`${sh.id} shotExtras`, e); } }
    // 4 the chrome: shot.chrome false/'off' → none · 'min'/'minimal' · 'full' · 'hud' (the device library's) · prose → default
    const ch = sh.chrome, cs = String(ch ?? '').trim().toLowerCase(), chromeOn = !(ch === false || /^(off|none|false|no)$/.test(cs));
    let chromeCut = null;
    if (chromeOn) {
      const style = /^min/.test(cs) ? 'minimal' : /^full/.test(cs) ? 'full' : /^hud/.test(cs) ? 'hud' : null;
      // (never over a lyric block on screen: chromeOff takes out the chrome items that would land on one)
      const lyrNow = lyric && lyric.box ? (now ? [now.rect] : [lyric.box]) : [];
      try { chromeCut = chromeOff(o, lyrNow, g => { if (style === 'hud' || typeof chrome !== 'function' || PJ().devChrome) D.hud(g, t, { b, accent: acc, light, min: false });
        else chrome(g, t, Object.assign({ color: D.inkFor(b, [D.MG().l, D.MG().t - 6, 420, 40], X), accent: acc, b, look: L }, style ? { style } : {})); }); }
      catch (e) { note(`${sh.id} chrome`, e); }
    }
    o.globalAlpha = 1; o.globalCompositeOperation = 'source-over';
    // the face the 2.5D camera kept in frame (treat.js face-safe), in screen px
    let face = null; if (X.face && m && m.map) { try { const [u, v, fw, fh] = X.face.uv, [x0, y0] = m.map(u, v), [x1, y1] = m.map(u + fw, v + fh); face = [x0, y0, x1 - x0, y1 - y0].map(q => Math.round(q)); } catch (e) { face = null; } }
    // what this frame drew (core.js ENGINE.frameLayers() reads treatment, flash, hero, cv, micro and lyric from here)
    window.DEV_FRAME = { t, shot: sh.id, treatment: S.treat.family, treatmentKind: S.treat.params && S.treat.params.kind || null, code: S.treat.code || null,
      drawnAs: S.treat.fallback || null, strip: S.treat.family === 'stills' && S.treat.params.strip !== false && !covering && X.strip !== false, covered: covering ? covering.kind : null,
      lyric, flash: shown.flash, hero: shown.hero, cv: shown.cv, micro: shown.micro,
      microRows: 3 - rowsLeft, accents: 2 - X.accLeft, suppressed: act.length - flash.length - hero.length - cv.length - micro.length,
      boxes: (X.boxes || []).map(e => ({ kind: e.kind, box: e.box.map(v => Math.round(v)), scale: +(+e.scale || 1).toFixed(3) })), lead: X.lead ? X.lead.map(v => Math.round(v)) : null,
      // the collision rule's record: the measured block drawn now (padded), the lyric blocks of the shot, every label a device
      // placed ({kind, spot: the candidate taken, -1 = dropped, box}), the chrome items taken out and the chrome ink left on
      // the block (0); the face box the 2.5D camera kept in frame (screen px; `faceHeld`: the zoom was held for it;
      // `faceCalm`: the shake was calmed to that fraction of its amplitude to keep it in, else null)
      lyricRect: now ? now.rect.map(v => Math.round(v)) : null, lyricBlocks: blocks.map(k => ({ line: k.line, auto: !!k.auto, a: +k.a.toFixed(3), z: +k.z.toFixed(3), rect: k.rect.map(v => Math.round(v)) })),
      labels: (X.labels || []).slice(), chrome: chromeCut, face, faceHeld: X.face ? !!X.face.held : null, faceCalm: X.face ? X.face.calm ?? null : null,
      // the tuck rule's record (occ.js glyph guard) when type was drawn behind the subject: {glyphs, kept, eased, tucked, cover}
      occ: window.OCC && OCC.guarded ? OCC.guarded() : null };
    return Object.assign({}, L, { focus: X.lead || [W / 2 - 120, H / 2 - 120, 240, 240] });
  }

  // ------------------------------------------------------------------------------- the boot lint (a dry run) -------
  // every device and type entry is drawn once at its own time on a scratch canvas when the page boots, so a device whose
  // params make it throw is reported before any frame is rendered (`slop render info` lists it) instead of silently
  // missing from every frame. Static data only; the frames rendered afterwards are unaffected.
  async function lint() {
    const D = window.DEV; if (!D || !D._base || !D.treat || (PJ().lint === false)) return;
    const P = plan(); if (!P || P.linted) return; P.linted = true;
    const Bc = D.mk(W, H), Oc = D.mk(W, H), b = Bc.getContext('2d', { willReadFrequently: true }), o = Oc.getContext('2d', { willReadFrequently: true });
    const found = []; let n = 0;
    const frameFor = (S, t) => { b.setTransform(1, 0, 0, 1, 0, 0); b.globalAlpha = 1; b.fillStyle = '#5a5e66'; b.fillRect(0, 0, W, H); o.setTransform(1, 0, 0, 1, 0, 0); o.clearRect(0, 0, W, H); D.begin(t);
      return D.frame({ t, sh: S.sh, b, o, accent: D.C.accent, flashOk: () => true, lead: [W * .4, H * .25, W * .2, H * .6] }); };
    for (const S of P.list) {
      if (S.covered) continue;
      for (const d of S.devices) { if (d.role === 'camera' || d.auto || n++ > 800) continue;
        const t = d.t0 + Math.min(.4, Math.max(0, (Math.min(d.t1, S.t1) - d.t0) / 2));
        try { await D.draw(o, b, d, t, frameFor(S, t)); } catch (e) { found.push(`${S.id}: device '${d.kind}' throws with these params (${e && e.message || e}) — it will not draw; fix its params (engine/DEVICES.md lists them)`); } }
      for (const en of S.type) { if (n++ > 1200) break; const w = D.type.entryWindow(en, S.sh); if (!w) continue;
        const t = clamp((Math.max(w[0], S.t0) + Math.min(w[1], S.t1)) / 2, w[0], w[1]);
        try { await D.type.entry(o, b, en, t, frameFor(S, t)); } catch (e) { found.push(`${S.id}: type entry (line ${en.line}, ${en.mode || 'subtitle'}) throws (${e && e.message || e}) — fix its fields`); } }
    }
    // a multiplane shot whose plate has no subject plane draws layers: said now (and the plan's treatments show it), with
    // the shot next to it named when that one draws layers too (a repeat the plan could not see from static data)
    const L2 = P.list.filter(S => !S.sh.gap);
    for (let i = 0; i < L2.length; i++) { const S = L2[i]; if (S.covered || S.treat.family !== 'multiplane' || !D.treat.splitOf) continue;
      const name = D.treat.plateOf(S.id); if (!name) continue;
      try { const sp = await D.treat.splitOf(name, S.treat.params.thr != null ? +S.treat.params.thr : null); if (sp.ok) continue;
        S.treat.fallback = 'layers'; found.push(D.treat.mpFallback(S, name, sp));
        const nb = [L2[i - 1], L2[i + 1]].filter(x => x && x.treat.base === 'plate' && (x.treat.fallback || x.treat.family) === 'layers');
        nb.forEach(x => found.push(`${S.id} and ${x.id} both draw 'layers' (multiplane fell back) — two 2.5D shots in a row share a treatment; give ${S.id} another treatment`)); }
      catch (e) { /* a missing plate: reported by the media check */ }
    }
    if (window.DRAWN && window.DRAWN.clear) window.DRAWN.clear();
    found.forEach(s => { if (!P.warn.includes(s)) { P.warn.push(s); report(s); } });
  }

  // ---------------------------------------------------------------------------- reporting into the engine ---------
  // (the layer count is NOT here: core.js ENGINE.frameLayers() is the one counter — `slop render check --layers` reads it —
  // and it reads window.DEV_FRAME, which drawShot fills with what actually drew)
  // the scenes chapter code registered (before this file ran, or any non-default scene once this renderer claimed the film)
  const chapterScenes = () => (typeof SCENES !== 'undefined' ? SCENES : []).filter(sc => !sc.isDefault && (PRE.has(sc) || (window.ENGINE && ENGINE.shotsRenderer === 'devices-v1')))
    .map(sc => ({ name: String(sc.name), t0: +(+sc.t0).toFixed(3), t1: +(+sc.t1).toFixed(3) }));
  if (window.ENGINE) {
    if (typeof ENGINE.info === 'function' && !ENGINE._devInfo) { const info0 = ENGINE.info; ENGINE._devInfo = true;
      ENGINE.info = (...a) => { const r = info0.apply(ENGINE, a) || {}; let P = null; try { P = shots.length ? plan() : null; } catch (e) { note('plan', e); }
        return Object.assign(r, { deviceWarnings: (P ? P.warn : loadWarn).slice(), deviceErrors: errs.slice(),
          chapterScenes: chapterScenes(), chapterShots: P ? P.list.filter(S => S.covered).map(S => S.id) : [],
          treatments: P ? P.list.filter(S => !S.sh.gap).map(S => ({ id: S.id, family: S.treat.family, kind: S.treat.params && S.treat.params.kind || null, code: S.treat.code || null,
            base: S.treat.base, auto: !!S.treat.auto, clean: !!S.clean, drawn: S.treat.fallback || S.treat.family })) : [] }); }; }
    if (typeof ENGINE.boot === 'function' && !ENGINE._devBoot) { const boot0 = ENGINE.boot; ENGINE._devBoot = true;
      ENGINE.boot = async function (...a) { const r = await boot0.apply(this, a); try { if (shots.length) await lint(); } catch (e) { note('lint', e); } return r; }; }
  }

  // ------------------------------------------------------------------------------------------- the scenes ----------
  const transOf = id => { try { const P = plan(), S = P && P.byId[id]; return S && S.trans || null; } catch (e) { note('transition', e); return null; } };
  if (!shots.length) { loadWarn.forEach(report); return; }                     // no storyboard yet: the engine's stub renders
  // holes in the storyboard (or before/after it) get a quiet motion-design scene so the film renders end to end
  const dur = +(SONG.duration || 0) || +SL.duration || shots[shots.length - 1].t1, gaps = []; let cur = 0;
  shots.forEach(sh => { if (sh.t0 - cur > .5 / FPS) gaps.push([cur, sh.t0]); cur = Math.max(cur, sh.t1); }); if (dur - cur > .5 / FPS) gaps.push([cur, dur]);
  gaps.forEach(([a, z], k) => shots.push({ id: `gap${String(k + 1).padStart(2, '0')}`, t0: a, t1: z, lines: [], gap: true, chrome: 'min' }));
  shots.sort((a, b) => a.t0 - b.t0);
  shots.forEach(sh => {
    if (covered(sh.t0, sh.t1)) return;
    const sc0 = scene(sh.id, sh.t0, sh.t1, async (b, o, t, lt, dur2) => drawShot(sh, b, o, t, lt, dur2));
    const sc = sc0 && sc0.name === sh.id ? sc0 : SCENES.filter(s => s.name === sh.id).pop(); if (!sc) return; sc.isDefault = true;
    const want = sh.transition_in ?? sh.trans_in ?? sh.trans;
    if (want != null && want !== '' && !/^(hard )?cut$/i.test(String(want))) sc.trans = {
      get type() { return transOf(sh.id) ? 'custom' : 'cut'; },
      get dur() { const r = transOf(sh.id); return r ? r.dur : 0; },
      draw(p, c) { const r = transOf(sh.id); if (r) return r.draw(p, c); c.base.drawImage(p < .5 ? c.a : c.b, 0, 0); c.over.drawImage(p < .5 ? c.ao : c.bo, 0, 0); return p < .5 ? c.la : c.lb; },
    };
  });
  if (window.ENGINE) ENGINE.shotsRenderer = 'devices-v1';                     // claim the default renderer (else the engine's stub runs)
  // the plan is made now (the data is merged before this file runs), so its warnings reach the page console at load
  if (window.DEV_LOADING) window.DEV_LOADING.then(() => window.SHOTS_PLAN()); else window.SHOTS_PLAN();
})();
