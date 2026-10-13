// devices/treat.js — the base layer of a shot: footage from window.EDL (a plate still or a clip frame) through a 2.5D
// treatment family, with the camera moves folded in. Families (the ANIMATION_GUIDE's, with the source's codes):
//   push      LS  the plate's own 2.5D parallax (PLATE3D) on the storyboard's camera words — the plain default
//   layers    LS  layer separation: the plate cut once into cumulative depth slices, each with its own parallax (cheap;
//                 things can sit BETWEEN layers) — the first video's replacement for the 64-step shader
//   multiplane LS two planes: the subject (nearer than the Otsu split of the depth) and the background with the subject's
//                 hole filled by push-pull; each plane its own camera (they drift against each other). m.matte() is the
//                 subject plane, so type and devices set `behind` tuck behind the subject
//   rack      LS  rack focus: soft, then the focus plane travels to the subject on the beat (blur by resampling)
//   relight   DI  depth as image: a light band travels front → back once per beat through the depth map
//   contours  DI  iso-depth lines of the real depth map, revealed level by level on eighths
//   scan      DI  a CV depth scan: a sweep per beat leaves a point cloud of the depth behind it
//   stills    SR  stills in rhythm: crops of one image cut on the beat, a one-frame flash per crop, a contact strip
//   xerox     RP  reproduction: kind 'xerox' (a 1-bit photocopy that boils on eighths) and 'thermal' (a print head
//                 descends on 16ths) are print texture (never picked in a clean look); 'mosaic' (an ENHANCE that resolves on
//                 every beat) and 'tiles' (the frame assembles as split-flap tiles flipping on 16ths) are clean
//   diagram   DG  diagram over image: a measuring grid, a crosshair and a dimension line on the lead
//   motion    PM  pure motion design: no footage — a ground and a dot grid that breathes on the kick (the device carries)
//   occlusion OC  the push, with every lyric block tucked behind the subject (needs a matte or depth; occ.js)
// The default renderer never lets two consecutive 2.5D shots share a treatment (DEV.treat.plan rotates a repeat away and
// logs a warning) — compared on the EFFECTIVE family: a depth family asked for on a plate without a usable depth map draws
// a push, so it counts as push. Clip shots use the clip family (the take, through the camera; `stills` also works on clips).
// A plate shot whose board leaves `treatment` empty gets one picked from the guide's five families (LS DI RP SR DG), least
// recently used first and never the previous 2.5D shot's family (nor the next shot's asked one), so a run of five picked
// shots of ≥ 2 beats each covers all five — in the native and clean looks too (reproduction as mosaic / tiles there);
// shorter shots rotate the families whose variants fit them (no stills, tiles or rack under 2 beats), and an asked
// treatment or a pinned hero (no stills) can leave a five-shot window one family short. Clean or print is decided per
// shot (its own look: a `screen: "native"` shot in a print film is clean).
// Ports: EV ch00 slices()/pcam(), its depthMask/bandMask relights, softDraw/fastBlur, xerox() (C7), thermal print (s021),
// mosaic ENHANCE (s018), stills in rhythm (s027: the crop index runs bs + .03 and HOLDS the last crop — params.loop: true
// cycles instead); occ.js-style iso contours (marching squares on a memoised depth grid).
// Intentional changes: `stills` picked automatically (not asked for) fires no crop flashes (flashes only where the board
// asks for them); the treatments' accent marks (the scan sweep, the selected contact-strip frame, the thermal print head)
// take the frame's accent budget (DEV.takeAccent) after the lyric; DEV.subjectOf finds the subject without detections
// (the shot's / plate's subject_uv, else the largest near region of the depth map) for the lead mark, anchors, crops and
// the through / match / iris transitions. Memos are keyed by plate name (static media), never by frame, and only the last
// 3 plates keep theirs (DEV.memo's LRU). Multiplane: the first video's planes()/coverC() (Otsu split, push-pull inpaint at
// 160 px), with a wider guard band, push-pull everywhere (its flat-void mean tone left a ghost of the subject on walls) and
// the cover clamp widened so a plane's drift never shows an edge.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.treat) return;
  const C = D.C, TY = D.TY, MG = D.MG;
  const ALIAS = { ls: 'layers', 'layer-separation': 'layers', layer: 'layers', slices: 'layers', parallax: 'push', plate3d: 'push', default: 'push', clip: 'push',
    'multi-plane': 'multiplane', planes: 'multiplane', 'two-plane': 'multiplane', tiles: 'xerox', 'flip-tiles': 'xerox', 'split-flap': 'xerox',
    di: 'relight', 'depth-as-image': 'relight', depth: 'relight', relight: 'relight', contour: 'contours', topo: 'contours', topography: 'contours',
    pointcloud: 'scan', 'point-cloud': 'scan', lidar: 'scan', scan: 'scan', rp: 'xerox', reproduction: 'xerox', halftone: 'xerox', photocopy: 'xerox', thermal: 'xerox', mosaic: 'xerox', enhance: 'xerox', '1-bit': 'xerox',
    sr: 'stills', 'stills-in-rhythm': 'stills', crops: 'stills', stutter: 'stills', dg: 'diagram', 'diagram-over-image': 'diagram', measure: 'diagram',
    pm: 'motion', 'pure-motion': 'motion', 'motion-design': 'motion', 'pure-motion-design': 'motion', code: 'motion', none: 'motion', oc: 'occlusion', occ: 'occlusion', rotoscope: 'occlusion', 'rack-focus': 'rack', focus: 'rack' };
  const FAMS = ['push', 'layers', 'multiplane', 'rack', 'relight', 'contours', 'scan', 'stills', 'xerox', 'diagram', 'motion', 'occlusion'];
  const CODE = { push: 'LS', layers: 'LS', multiplane: 'LS', rack: 'LS', relight: 'DI', contours: 'DI', scan: 'DI', stills: 'SR', xerox: 'RP', diagram: 'DG', motion: 'PM', occlusion: 'OC', clip: 'clip' };
  const DEPTH = new Set(['layers', 'multiplane', 'rack', 'relight', 'contours', 'scan']);
  // reproduction kinds: print texture (never auto-picked in a clean look; kept with a warning when asked) and clean ones
  const RP_PRINT = new Set(['xerox', 'thermal']), RP_KINDS = ['xerox', 'thermal', 'mosaic', 'tiles'];
  // a treatment field (string or {family, …params}) → {family, params}
  const CODES = new Set(['ls', 'di', 'rp', 'sr', 'dg', 'pm', 'oc']);
  function parse(v) {
    if (v == null || v === '' || v === 'auto') return null;
    const o = typeof v === 'string' ? { family: v } : Object.assign({}, v); let f = String(o.family || o.name || o.kind || '').toLowerCase().trim();
    const kindOf = { thermal: 'thermal', mosaic: 'mosaic', enhance: 'mosaic', xerox: 'xerox', photocopy: 'xerox', halftone: 'xerox', '1-bit': 'xerox', tiles: 'tiles', 'flip-tiles': 'tiles', 'split-flap': 'tiles' }[f];
    if (kindOf && !o.kind) o.kind = kindOf;
    // a family name, an alias (the board's 'layer-separation', 'depth-as-image', …) or prose/codes: an explicit family
    // inside parentheses or after a code wins over the code ('LS (rack)' → rack, 'DI: contours' → contours); among codes
    // alone the first wins ('DI+LS' → relight)
    const known = w => FAMS.includes(w) ? w : ALIAS[w] || null;
    const words = s => s.split(/[^a-z0-9-]+/).filter(Boolean);
    const paren = (f.match(/\(([^)]*)\)/) || [])[1];
    const named = ws => ws.filter(w => !CODES.has(w)).map(known).find(Boolean);
    f = known(f) || (paren && (named(words(paren)) || words(paren).map(known).find(Boolean))) || named(words(f)) || words(f).map(known).find(Boolean)
      || (FAMS.find(x => f.startsWith(x)) ?? null);
    if (!f) return { family: 'push', params: o, unknown: v };
    delete o.family; delete o.name; return { family: f, params: o };
  }
  // the treatment of every shot, decided once from static data (shots, EDL, PLATES, the look): 2.5D shots never repeat
  // (compared on the family that will actually draw: a depth family without a usable depth map is a push). A plate shot
  // with no treatment gets the least recently used of the guide's five families (LS DI RP SR DG) that suits it, never the
  // previous 2.5D shot's (nor the next shot's asked one); inside a family the variants rotate the same way.
  const FIVE = ['LS', 'DI', 'SR', 'DG', 'RP'];
  function variants(code, depth, clean) {
    if (code === 'LS') return depth ? [['layers'], ['multiplane'], ['rack']] : [['push']];
    if (code === 'DI') return depth ? [['relight'], ['scan'], ['contours']] : [];
    if (code === 'RP') return clean ? [['xerox', 'mosaic'], ['xerox', 'tiles']] : [['xerox', 'xerox'], ['xerox', 'tiles'], ['xerox', 'thermal'], ['xerox', 'mosaic']];
    if (code === 'SR') return [['stills']];
    if (code === 'DG') return [['diagram']];
    return [];
  }
  // a variant that needs time to read: rack focus pulls on beat 1, stills cut a crop per beat, tiles assemble over 1.5 beats
  const suits = (v, beats) => !((v[0] === 'rack' && beats < 1.5) || (v[0] === 'stills' && beats < 2) || (v[1] === 'tiles' && beats < 2));
  // the board's own words for a treatment (the warnings quote what the operator wrote, not the engine's family name)
  // e.g. 'rack' · 'xerox' kind 'thermal' · 'tiles' (draws as xerox kind tiles) · 'planes' (draws as multiplane)
  const quoted = (v, fam, kind) => {
    const o = v && typeof v === 'object' ? v : null, bf = String((o ? o.family || o.name || o.kind : v) ?? '').trim(), bk = o && o.kind && o.kind !== bf ? String(o.kind) : '';
    const said = `'${bf || fam}'${bk ? ` kind '${bk}'` : ''}`;
    return !bf || bf.toLowerCase() === fam ? said : `${said} (draws as ${fam}${fam === 'xerox' && kind ? ` kind ${kind}` : ''})`; };
  function plan(shots, opts = {}) {
    const EDL = window.EDL || {}, PL = window.PLATES || {}, out = [], warn = [];
    const cleanOf = i => (typeof opts.cleanOf === 'function' ? !!opts.cleanOf(i) : !!opts.clean);   // per shot: its own look
    const beatsOf = sh => { try { return Math.max(0, bpOf(sh.t1) - bpOf(sh.t0)); } catch (e) { return 4; } };
    const info = shots.map(sh => {
      const e = EDL[sh.id] || {}, base = e.segs && e.segs.length ? 'clip' : e.plate ? 'plate' : 'none', meta = (e.plate && PL[e.plate]) || {};
      const depth = base === 'plate' && meta.depth !== false && (meta.subject_depth != null || meta.depth === true || typeof meta.depth === 'string' || meta.has_depth === true)
        && (typeof ENGINE === 'undefined' || !ENGINE.depthOK || ENGINE.depthOK(meta));   // the licence rule: Depth-Anything-V2-Small only
      const asked = parse(sh.treatment);
      const eff = base === 'plate' && asked && !asked.unknown ? (DEPTH.has(asked.family) && !depth ? 'push' : asked.family) : null;
      return { base, depth, asked, eff, beats: beatsOf(sh) };
    });
    const lastCode = {}, lastVar = {}; let prev = null;
    const pinned = sh => (Array.isArray(sh.devices) ? sh.devices : []).some(d => { const sp = d && D.get(d.kind || d.device); try { return !!(sp && sp.pinned && sp.pinned(d.params && typeof d.params === 'object' ? d.params : {})); } catch (e) { return false; } });
    // the next plate shot's asked family code (an auto pick never takes it: the board's own choice must not be rotated away)
    const nextAskedCode = i => { for (let j = i + 1; j < info.length; j++) { const I = info[j]; if (I.base === 'clip') continue; if (I.base !== 'plate') return null; return I.eff ? CODE[I.eff] : null; } return null; };
    const pick = (I, avoidCodes) => {
      const ranked = FIVE.filter(c => !avoidCodes.includes(c) && variants(c, I.depth, I.clean).length)
        .sort((a, b) => (lastCode[a] ?? -1e9) - (lastCode[b] ?? -1e9) || FIVE.indexOf(a) - FIVE.indexOf(b));
      for (const strict of [true, false]) for (const c of ranked) {
        const vs = variants(c, I.depth, I.clean).filter(v => !strict || suits(v, I.beats)); if (!vs.length) continue;
        const v = vs.slice().sort((a, b) => (lastVar[a.join(':')] ?? -1e9) - (lastVar[b.join(':')] ?? -1e9))[0]; return { fam: v[0], kind: v[1] || null };
      }
      return null;
    };
    // a reproduction kind nobody knows: the clean one in a clean look, the photocopy in a print look — reported
    const rpKind = (sh, params, clean) => {
      if (params.kind == null || params.kind === '') { params.kind = clean ? 'mosaic' : 'xerox'; return; }
      const k = String(params.kind).toLowerCase().trim(), kk = { enhance: 'mosaic', photocopy: 'xerox', halftone: 'xerox', '1-bit': 'xerox', 'flip-tiles': 'tiles', 'split-flap': 'tiles' }[k] || k;
      if (RP_KINDS.includes(kk)) { params.kind = kk; return; }
      const to = clean ? 'mosaic' : 'xerox';
      warn.push(`${sh.id}: reproduction kind '${params.kind}' is not one of ${RP_KINDS.join(' · ')} → '${to}' (${clean ? 'the clean reproduction in this look' : 'the photocopy'}); write {"family": "reproduction", "kind": "mosaic"} (or xerox · thermal · tiles)`);
      params.kind = to;
    };
    shots.forEach((sh, i) => {
      const I = info[i], asked = I.asked, clean = I.clean = cleanOf(i); let fam = asked ? asked.family : null, params = asked ? Object.assign({}, asked.params) : {};
      if (asked && asked.unknown) warn.push(`${sh.id}: unknown treatment ${JSON.stringify(asked.unknown)} → push (families: ${FAMS.join(', ')})`);
      if (I.base === 'none') { out.push({ family: 'motion', code: 'PM', params, base: I.base, depth: false, clean }); prev = 'motion'; return; }
      if (I.base === 'clip') { fam = fam && ['stills', 'diagram', 'xerox', 'occlusion', 'motion'].includes(fam) ? fam : 'push';
        if (asked && !asked.unknown && fam === 'push' && asked.family !== 'push') warn.push(`${sh.id}: treatment '${asked.family}' needs a plate (this shot plays a clip) → the clip through the camera`);
        if (fam === 'xerox') rpKind(sh, params, clean);
        out.push({ family: fam === 'push' ? 'clip' : fam, code: fam === 'push' ? 'clip' : CODE[fam], params, base: I.base, depth: false, clean }); return; }
      if (fam && DEPTH.has(fam) && !I.depth) { warn.push(`${sh.id}: treatment ${quoted(sh.treatment, fam)} needs the plate's depth map (Depth-Anything-V2-Small; \`slop edit export\` makes it) → push`); fam = 'push'; }
      let auto = !fam;
      const avoid = [prev && CODE[prev], nextAskedCode(i), pinned(sh) ? 'SR' : null].filter(Boolean);
      if (!fam) { const v = pick(I, avoid) || pick(I, prev ? [CODE[prev]] : []) || { fam: prev === 'push' ? 'stills' : 'push', kind: null }; fam = v.fam; if (v.kind) params.kind = v.kind; }
      if (fam === prev) {
        // a repeat (asked): the least recently used family that is not the previous one (asked kinds/params do not carry over)
        const v = pick(I, avoid.length ? avoid : [CODE[prev]]) || pick(I, [CODE[prev]]) || { fam: prev === 'stills' ? 'diagram' : 'stills', kind: null };
        if (asked) warn.push(`${sh.id}: treatment ${quoted(sh.treatment, fam, params.kind)} repeats the previous 2.5D shot → '${v.fam}'${v.kind ? ` kind '${v.kind}'` : ''} (2.5D treatments never repeat back to back; the previous shot draws '${prev}')`);
        fam = v.fam; params = {}; if (v.kind) params.kind = v.kind; auto = true;
      }
      if (fam === 'xerox') rpKind(sh, params, clean);
      if (fam === 'xerox' && clean && !auto && RP_PRINT.has(params.kind)) warn.push(`${sh.id}: treatment ${quoted(sh.treatment, fam, params.kind)} is a print-look texture (halftone/dither/print passes are banned in a clean look) — kept because the board asks for it; 'mosaic' or 'tiles' are the clean reproductions`);
      // flashes only where the board asks for them: stills picked automatically cut its crops without the crop flash
      if (fam === 'stills' && auto && params.flash == null) params = Object.assign({}, params, { flash: false });
      const code = CODE[fam] || 'LS'; lastCode[code] = i; lastVar[[fam, params.kind || null].filter(Boolean).join(':')] = i;
      out.push({ family: fam, code, params, base: I.base, depth: I.depth, auto, clean }); prev = fam;
    });
    return { list: out, warn };
  }

  // ---------------------------------------------------------------------------------------------- media helpers --
  const plateOf = id => ((window.EDL || {})[id] || {}).plate || null;
  const memoP = (k, f, owner) => D.memo(k, f, owner);
  // the footage through the screen-space camera (CAM.through when hits.js is loaded; else the zoom folded into the cam)
  async function through(b, t, cam, fx, draw) {
    if (D.has.CAM()) return CAM.through(b, t, fx || {}, draw);
    if (fx && fx.zoom) cam.zoom = (cam.zoom || 1.06) * (1 + fx.zoom);
    return draw();
  }
  const flatCam = (cam, name, t) => { const meta = ((window.PLATES || {})[name]) || {}; return Object.assign({ focus: meta.subject_depth ?? .5 }, cam, { t, flat: true }); };
  // a grid of the plate's depth (gw × gh floats 0..1, near = 1), memoised by plate name
  const depthGrid = (name, gw = 160, gh = 90) => memoP(`dgrid:${name}:${gw}`, async () => {
    const P = await MEDIA.plate(name); if (!P || !P.dep) return null;
    const c = D.mk(gw, gh), g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(P.dep, 0, 0, gw, gh);
    const d = g.getImageData(0, 0, gw, gh).data, a = new Float32Array(gw * gh); for (let i = 0; i < gw * gh; i++) a[i] = d[i * 4] / 255; return { a, gw, gh };
  }, name);
  // a depth-keyed alpha mask drawn through the base's current transform (the camera) at half resolution: fn(depth) → 0..1
  async function depthMask(b, name, c, fn) {
    const P = await MEDIA.plate(name); if (!P || !P.dep) return null;
    const s = D.scratch(W / 2, H / 2), g = s.getContext('2d', { willReadFrequently: true }), m = b.getTransform();
    g.setTransform(m.a * .5, m.b * .5, m.c * .5, m.d * .5, m.e * .5, m.f * .5); cover(g, P.dep, c); g.setTransform(1, 0, 0, 1, 0, 0);
    const I = g.getImageData(0, 0, W / 2, H / 2), d = I.data, lut = new Uint8ClampedArray(256); for (let v = 0; v < 256; v++) lut[v] = 255 * clamp(fn(v / 255));
    for (let i = 0; i < d.length; i += 4) { d[i + 3] = d[i + 3] ? lut[d[i]] : 0; d[i] = d[i + 1] = d[i + 2] = 255; }
    g.putImageData(I, 0, 0); return s;
  }
  // a colour layer through a mask, composited onto the base in screen space
  function tintThrough(b, mask, col, alpha, op = 'screen') {
    const s = D.scratch(W / 2, H / 2), g = s.getContext('2d'); g.fillStyle = col; g.fillRect(0, 0, W / 2, H / 2); g.globalCompositeOperation = 'destination-in'; g.drawImage(mask, 0, 0);
    b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.globalAlpha = alpha; b.globalCompositeOperation = op; b.imageSmoothingEnabled = true; b.drawImage(s, 0, 0, W, H); b.restore();
  }
  // blur the base in place by ~px screen px (down- then up-sample: the canvas blur filter is very slow in software GL)
  function soften(b, px) {
    const f = clamp(px / 1.6, 1, 9); if (f <= 1.05) return; const w = Math.max(8, Math.round(W / f)), h = Math.max(8, Math.round(H / f));
    const s = D.scratch(w, h), g = s.getContext('2d'); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high'; g.drawImage(b.canvas, 0, 0, w, h);
    b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.imageSmoothingEnabled = true; b.imageSmoothingQuality = 'high'; b.drawImage(s, 0, 0, W, H); b.restore();
  }
  const copyBase = b => { const s = D.scratch(W, H); s.getContext('2d').drawImage(b.canvas, 0, 0); return s; };

  // --------------------------------------------------------------------------------------------- the families ----
  async function push(b, o, S, t, cam, fx) { return D.has.MEDIA() ? through(b, t, cam, fx, () => MEDIA.drawShot(b, S.id, t, cam)) : null; }

  // LS · depth slices (EV ch00): cumulative layers above each threshold, each placed with its own parallax (pcam maths)
  const TH = [.16, .28, .4, .52, .64, .76, .88], LW = 2000;
  const slices = name => memoP(`slices:${name}`, async () => {
    const P = await MEDIA.plate(name), img = P.img, w = LW, h = Math.round(LW * img.naturalHeight / img.naturalWidth);
    if (!P.dep) return { img, meta: P.meta || {}, L: [] };
    const c = D.mk(w, h), g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0, w, h); const col = g.getImageData(0, 0, w, h).data;
    g.clearRect(0, 0, w, h); g.filter = 'blur(2px)'; g.drawImage(P.dep, 0, 0, w, h); g.filter = 'none'; const dd = g.getImageData(0, 0, w, h).data;
    const L = TH.map((th, k) => {
      let x0 = w, x1 = -1, y0 = h, y1 = -1; const al = new Uint8ClampedArray(w * h);
      for (let i = 0; i < w * h; i++) { const a = clamp((dd[i * 4] / 255 - th) / .035 + .5); if (a <= 0) continue; al[i] = 255 * a; const x = i % w, y = (i / w) | 0; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      if (x1 < 0) return null;
      const cw = x1 - x0 + 1, chh = y1 - y0 + 1, lc = D.mk(cw, chh), lg = lc.getContext('2d'), im = lg.createImageData(cw, chh), d = im.data;
      for (let y = 0; y < chh; y++) for (let x = 0; x < cw; x++) { const i = (y + y0) * w + x + x0, j = (y * cw + x) * 4; if (!al[i]) continue; d[j] = col[i * 4]; d[j + 1] = col[i * 4 + 1]; d[j + 2] = col[i * 4 + 2]; d[j + 3] = al[i]; }
      lg.putImageData(im, 0, 0); return { c: lc, u: x0 / w, v: y0 / h, uw: cw / w, vh: chh / h, d: th + (TH[k + 1] ? (TH[k + 1] - th) / 2 : .06) };
    }).filter(Boolean);
    return { img, meta: P.meta || {}, L };
  }, name);
  function pcam(img, meta, cam) {
    const ia = img.naturalWidth / img.naturalHeight, sa = W / H, sx = ia > sa ? sa / ia : 1, sy = ia > sa ? 1 : ia / sa, z = cam.zoom ?? 1.06;
    const vx = sx / z, vy = sy / z, ox = clamp(cam.cx ?? .5, vx / 2 + .01, 1 - vx / 2 - .01), oy = clamp(cam.cy ?? .5, vy / 2 + .01, 1 - vy / 2 - .01);
    const f = cam.focus ?? (meta.subject_depth ?? .5), dx = (cam.x || 0) * sx, dy = (cam.y || 0) * sy;
    const toS = (u, v, d = f) => [((u - dx * (d - f) - ox) * z / sx + .5) * W, ((v - dy * (d - f) - oy) * z / sy + .5) * H];
    return { toS, f };
  }
  async function layers(b, o, S, t, cam, fx, X, p) {
    const name = plateOf(S.id); if (!name) return push(b, o, S, t, cam, fx);
    const SL = await slices(name); if (!SL.L.length) return push(b, o, S, t, cam, fx);
    const k = clamp((t - S.t0) / Math.max(.1, S.t1 - S.t0));
    return through(b, t, cam, fx, async () => {
      const c = Object.assign({}, cam); if (!c.x && !c.y) c.x = lerp(-(p.amount ?? .03), p.amount ?? .03, easeInOut(k));   // a lateral move shows the parallax
      const C2 = pcam(SL.img, SL.meta, c); b.fillStyle = '#000'; b.fillRect(-W, -H, 3 * W, 3 * H);
      const put = (im, d, u = 0, v = 0, uw = 1, vh = 1) => { const [x0, y0] = C2.toS(u, v, d), [x1, y1] = C2.toS(u + uw, v + vh, d); if (x1 < 0 || y1 < 0 || x0 > W || y0 > H) return; b.drawImage(im, x0, y0, x1 - x0, y1 - y0); };
      put(SL.img, TH[0] / 2); SL.L.forEach(l => put(l.c, l.d, l.u, l.v, l.uw, l.vh));
      const boxes = SL.meta.boxes || {}, map = (u, v) => C2.toS(u, v);
      return { map, box: label => { const bb = boxes[label]; if (!bb) return null; const [x0, y0] = map(bb[0], bb[1]), [x1, y1] = map(bb[0] + bb[2], bb[1] + bb[3]); return [x0, y0, x1 - x0, y1 - y0]; }, meta: SL.meta };
    });
  }

  // LS · multiplane (the first video's takeoff chapter): the plate split at the Otsu threshold of its depth histogram into
  // the subject plane (nearer than the split) and the background, whose hole (the subject, dilated) is filled by push-pull
  // at 160 px from a guard band two cells out (so no edge colour of the subject is dragged into the fill). Two drawImage
  // calls a frame; the planes drift against each other along the camera's move.
  // the split alone (cheap: the depth at 480 px, its histogram) → {ok, th, frac, why}: the boot dry run checks every
  // multiplane shot with it, so a plate without a usable split is reported before any frame renders
  const MW = 480;
  const depthAt = async (name, mw) => { const P = await MEDIA.plate(name); if (!P || !P.dep) return null;
    const mh = Math.max(8, Math.round(mw * P.img.naturalHeight / P.img.naturalWidth)), mc = D.mk(mw, mh), mg = mc.getContext('2d', { willReadFrequently: true }); mg.drawImage(P.dep, 0, 0, mw, mh);
    return { P, mc, mg, mw, mh, I: mg.getImageData(0, 0, mw, mh) }; };
  function otsu(Dd, n, thr) {
    const hist = new Float64Array(256); for (let i = 0; i < n; i++) hist[Dd[i * 4]]++;
    let sum = 0, sB = 0, wB = 0, best = 0, th = 128; for (let i = 0; i < 256; i++) sum += i * hist[i];
    for (let i = 0; i < 256; i++) { wB += hist[i]; if (!wB) continue; const wF = n - wB; if (!wF) break; sB += i * hist[i];
      const mB = sB / wB, mF = (sum - sB) / wF, v = wB * wF * (mB - mF) ** 2; if (v > best) { best = v; th = i; } }
    if (thr != null && isFinite(thr)) th = Math.round(clamp(thr) * 255);
    return th;
  }
  const soft = (d, th) => { const lo = th / 255 - .02, hi = th / 255 + .06, a = clamp((d / 255 - lo) / (hi - lo)); return a * a * (3 - 2 * a); };
  const splitOf = (name, thr) => memoP(`mpsplit:${name}:${thr ?? 'otsu'}`, async () => {
    const R = await depthAt(name, MW); if (!R) return { ok: false, th: null, frac: 0, why: 'the plate has no usable depth map' };
    const n = R.mw * R.mh, Dd = R.I.data, th = otsu(Dd, n, thr); let n1 = 0; for (let i = 0; i < n; i++) if (soft(Dd[i * 4], th) > .5) n1++;
    const frac = n1 / n, ok = frac >= .015 && frac <= .8;
    return { ok, th: th / 255, frac, why: ok ? '' : frac < .015 ? 'nothing in its depth map stands nearer than the rest: no figure to lift' : 'almost all of its depth map is near: no background to slide' };
  }, name);
  // the line both the boot dry run and the renderer report when a multiplane shot draws layers instead
  const mpFallback = (S, name, sp) => `${S.id}: treatment 'multiplane' found no subject plane in plate '${name}' (${sp && sp.why || 'no split'}) → drew 'layers' instead; give the shot another treatment, or set {"family": "multiplane", "thr": 0.6} (the depth split, 0..1, near = 1)`;
  const planes = (name, thr) => memoP(`mp:${name}:${thr ?? 'otsu'}`, async () => {
    const sp = await splitOf(name, thr); if (!sp.ok) return null;          // no figure / everything near: no meaningful split
    const R = await depthAt(name, MW); if (!R) return null;
    const P = R.P, iw = P.img.naturalWidth, ih = P.img.naturalHeight, mw = R.mw, mh = R.mh, mc = R.mc, mg = R.mg, I = R.I, Dd = I.data, A = new Float32Array(mw * mh);
    const th = Math.round(sp.th * 255); let n1 = 0, su = 0, sv = 0;
    for (let i = 0; i < mw * mh; i++) { const s3 = soft(Dd[i * 4], th); A[i] = s3; Dd[i * 4] = Dd[i * 4 + 1] = Dd[i * 4 + 2] = 255; Dd[i * 4 + 3] = 255 * s3;
      if (s3 > .5) { n1++; su += (i % mw + .5) / mw; sv += (Math.floor(i / mw) + .5) / mh; } }
    mg.putImageData(I, 0, 0);
    const near = D.mk(iw, ih), ng = near.getContext('2d', { willReadFrequently: true }); ng.drawImage(P.img, 0, 0); ng.globalCompositeOperation = 'destination-in'; ng.drawImage(mc, 0, 0, iw, ih);
    const lw = 160, lh = Math.max(4, Math.round(lw * ih / iw)), lc = D.mk(lw, lh), lg = lc.getContext('2d', { willReadFrequently: true }); lg.drawImage(P.img, 0, 0, lw, lh);
    const Lp = lg.getImageData(0, 0, lw, lh), LD = Lp.data, N = lw * lh, known = new Uint8Array(N), rgbv = new Float32Array(N * 3);
    for (let y = 0; y < lh; y++) for (let x = 0; x < lw; x++) { let mx = 0;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) { const sx = clamp(Math.floor((x + dx + .5) / lw * mw), 0, mw - 1), sy = clamp(Math.floor((y + dy + .5) / lh * mh), 0, mh - 1); mx = Math.max(mx, A[sy * mw + sx]); }
      const i = y * lw + x; known[i] = mx < .05 ? 1 : 0; for (let c = 0; c < 3; c++) rgbv[i * 3 + c] = LD[i * 4 + c]; }
    const hole = Uint8Array.from(known, k => 1 - k); let fr = known.slice();
    // (the source filled a flat void with its global mean tone; the mean includes the floor and reads as a ghost of the
    // subject on a wall that is lighter where the subject stands — push-pull from a guard band two cells out keeps the tone local)
    for (let it = 0; it < 400; it++) { let any = false; const nf = fr.slice();
      for (let y = 0; y < lh; y++) for (let x = 0; x < lw; x++) { const i = y * lw + x; if (fr[i]) continue; let k = 0, r = 0, g = 0, b2 = 0;
        for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, -1], [1, -1], [-1, 1]]) { const X2 = x + dx, Y2 = y + dy; if (X2 < 0 || Y2 < 0 || X2 >= lw || Y2 >= lh) continue; const j = Y2 * lw + X2; if (!fr[j]) continue; k++; r += rgbv[j * 3]; g += rgbv[j * 3 + 1]; b2 += rgbv[j * 3 + 2]; }
        if (k) { rgbv[i * 3] = r / k; rgbv[i * 3 + 1] = g / k; rgbv[i * 3 + 2] = b2 / k; nf[i] = 1; any = true; } }
      fr = nf; if (!any) break; }
    for (let it = 0; it < 12; it++) for (let y = 1; y < lh - 1; y++) for (let x = 1; x < lw - 1; x++) { const i = y * lw + x; if (!hole[i]) continue;
      for (let c = 0; c < 3; c++) rgbv[i * 3 + c] = (rgbv[(i - 1) * 3 + c] + rgbv[(i + 1) * 3 + c] + rgbv[(i - lw) * 3 + c] + rgbv[(i + lw) * 3 + c]) / 4; }
    for (let i = 0; i < N; i++) { for (let c = 0; c < 3; c++) LD[i * 4 + c] = rgbv[i * 3 + c]; LD[i * 4 + 3] = hole[i] ? 255 : 0; }
    lg.putImageData(Lp, 0, 0); const lb = D.mk(lw, lh), lbg = lb.getContext('2d', { willReadFrequently: true }); lbg.filter = 'blur(1.5px)'; lbg.drawImage(lc, 0, 0); lbg.filter = 'none';
    const far = D.mk(iw, ih), fg = far.getContext('2d', { willReadFrequently: true }); fg.drawImage(P.img, 0, 0); fg.imageSmoothingEnabled = true; fg.drawImage(lb, 0, 0, iw, ih);
    return { near, far, iw, ih, meta: P.meta || {}, su: su / n1, sv: sv / n1, th: th / 255 };
  }, name);
  // cover-draw a canvas with a pixel offset (dx, dy) — the cover clamp includes the offset, so the frame never shows an edge;
  // returns the image-uv → screen mapper
  function coverC(g, c, cam = {}) {
    const z = cam.zoom ?? 1, s = Math.max(W / c.width, H / c.height) * z, IW = c.width * s, IH = c.height * s, dx = cam.dx || 0, dy = cam.dy || 0;
    const ox = clamp(-(cam.cx ?? .5) * IW, Math.min(W / 2 - IW - dx, -W / 2 - dx), Math.max(W / 2 - IW - dx, -W / 2 - dx));
    const oy = clamp(-(cam.cy ?? .5) * IH, Math.min(H / 2 - IH - dy, -H / 2 - dy), Math.max(H / 2 - IH - dy, -H / 2 - dy)), X = W / 2 + dx, Y = H / 2 + dy;
    g.save(); g.translate(X, Y); if (cam.rot) g.rotate(cam.rot); g.imageSmoothingEnabled = true; g.drawImage(c, ox, oy, IW, IH); g.restore();
    const cs = Math.cos(cam.rot || 0), sn = Math.sin(cam.rot || 0);
    return (u, v) => { const px = ox + u * IW, py = oy + v * IH; return [X + px * cs - py * sn, Y + px * sn + py * cs]; };
  }
  async function multiplane(b, o, S, t, cam, fx, X, p) {
    const name = plateOf(S.id); if (!name) return push(b, o, S, t, cam, fx);
    const thr = p.thr != null ? +p.thr : null, PL = await planes(name, thr);
    if (!PL) { D.report(mpFallback(S, name, await splitOf(name, thr))); if (S.treat) S.treat.fallback = 'layers'; return layers(b, o, S, t, cam, fx, X, p); }
    const k = easeInOut(clamp((t - S.t0) / Math.max(.1, S.t1 - S.t0))), amt = clamp(+(p.amount ?? .016) || 0, 0, .08);
    const vert = p.dir ? /^v/.test(String(p.dir)) : Math.abs(cam.y || 0) > Math.abs(cam.x || 0), off = (k - .5) * 2 * amt, z0 = cam.zoom || 1.06;
    const pf = PORTRAIT && !cam.faceSafe, sub = pf ? await D.subjectUV(S.sh) : null, cx = pf ? clamp(sub ? sub[0] + sub[2] / 2 : PL.su, .2, .8) : (cam.cx ?? .5), cy = cam.cy ?? .5;
    const far = { zoom: z0 * 1.05, cx, cy, dx: vert ? 0 : -off * W, dy: vert ? -off * H : 0, rot: cam.rot || 0 };
    const near = { zoom: z0, cx, cy, dx: vert ? 0 : off * .7 * W, dy: vert ? off * .7 * H : 0, rot: cam.rot || 0 };
    return through(b, t, cam, fx, async () => {
      b.fillStyle = '#000'; b.fillRect(-W, -H, 3 * W, 3 * H);
      coverC(b, PL.far, far); const mn = coverC(b, PL.near, near), xf = b.getTransform(), boxes = PL.meta.boxes || {};
      const res = { map: mn, box: l => { const bb = boxes[l]; if (!bb) return null; const [x0, y0] = mn(bb[0], bb[1]), [x1, y1] = mn(bb[0] + bb[2], bb[1] + bb[3]); return [x0, y0, x1 - x0, y1 - y0]; },
        score: l => (boxes[l] && boxes[l][4] != null ? boxes[l][4] : null), meta: PL.meta, kind: 'plate', name, planes: true };
      // the subject plane as the matte (half resolution, through the same camera): `behind` type and devices tuck behind it
      res.matte = async () => { if (res._matte !== undefined) return res._matte; const c = window.OCC ? OCC.canvas(W >> 1, H >> 1) : D.scratch(W >> 1, H >> 1), g = c.getContext('2d', { willReadFrequently: true });
        g.setTransform(.5 * xf.a, .5 * xf.b, .5 * xf.c, .5 * xf.d, .5 * xf.e, .5 * xf.f); coverC(g, PL.near, near); g.setTransform(1, 0, 0, 1, 0, 0); c.kind = 'matte'; return res._matte = c; };
      res.depth = async () => null;
      return res;
    });
  }

  // LS · rack focus: soft, then sharp where the depth is near the focus plane, the plane travelling far → subject on `at`
  async function rack(b, o, S, t, cam, fx, X, p) {
    const name = plateOf(S.id); if (!name) return push(b, o, S, t, cam, fx);
    const meta = ((window.PLATES || {})[name]) || {}, at = p.at != null ? D.time(p.at, S.sh, S.t0) : D.beatAfter(S.t0 + 1e-3, 1);
    const fTo = p.to ?? (meta.subject_depth ?? .8), fFrom = p.from ?? .2, k = easeInOut(seg(t, at - D.bl(at) / 2, at + D.bl(at) / 2)), f = lerp(fFrom, fTo, k);
    return through(b, t, cam, fx, async () => {
      const c = flatCam(cam, name, t), r = await MEDIA.drawPlate(b, name, c, t);
      const sharp = copyBase(b), mask = await depthMask(b, name, c, d => Math.exp(-Math.pow((d - f) / (p.width ?? .14), 2)));
      soften(b, p.blur ?? 9);
      if (mask) { const g = sharp.getContext('2d'); g.globalCompositeOperation = 'destination-in'; g.imageSmoothingEnabled = true; g.drawImage(mask, 0, 0, W, H);
        b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.drawImage(sharp, 0, 0); b.restore(); }
      else if (k >= 1) { b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.drawImage(sharp, 0, 0); b.restore(); }
      return r;
    });
  }

  // DI · relight: a light band through the depth, front → back once per beat (rows top → bottom when there is no depth)
  async function relight(b, o, S, t, cam, fx, X, p) {
    const name = plateOf(S.id); if (!name) return push(b, o, S, t, cam, fx);
    const ph = frac(bpOf(t) * (p.per_beat ?? 1)), f = Math.round((1 - ph) * 40) / 40, a = (p.alpha ?? .55) * (1 - .5 * ph);
    return through(b, t, cam, fx, async () => {
      const c = flatCam(cam, name, t), r = await MEDIA.drawPlate(b, name, c, t);
      const mask = await depthMask(b, name, c, d => Math.exp(-Math.pow((d - f) / (p.width ?? .06), 2)));
      if (mask) tintThrough(b, mask, p.tint || '#ffffff', a);
      else { const y = ph * H, gr = b.createLinearGradient(0, y - 90, 0, y + 90); gr.addColorStop(0, 'rgba(255,255,255,0)'); gr.addColorStop(.5, `rgba(255,255,255,${a})`); gr.addColorStop(1, 'rgba(255,255,255,0)');
        b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.globalCompositeOperation = 'screen'; b.fillStyle = gr; b.fillRect(0, y - 90, W, 180); b.restore(); }
      return r;
    });
  }

  // DI · contours: iso-depth lines (marching squares on the memoised depth grid), a level per eighth from the start
  function iso(G2, lv) {
    const { a, gw, gh } = G2, segs = [];
    for (let y = 0; y < gh - 1; y++) for (let x = 0; x < gw - 1; x++) {
      const A = a[y * gw + x], B = a[y * gw + x + 1], Cc = a[(y + 1) * gw + x + 1], Dd = a[(y + 1) * gw + x];
      const idx = (A > lv ? 8 : 0) | (B > lv ? 4 : 0) | (Cc > lv ? 2 : 0) | (Dd > lv ? 1 : 0); if (idx === 0 || idx === 15) continue;
      const ip = (p0, q) => (lv - p0) / ((q - p0) || 1e-6), T = [x + ip(A, B), y], R = [x + 1, y + ip(B, Cc)], Bt = [x + ip(Dd, Cc), y + 1], L = [x, y + ip(A, Dd)];
      const add = (P, Q) => segs.push([P[0] / (gw - 1), P[1] / (gh - 1), Q[0] / (gw - 1), Q[1] / (gh - 1)]);
      switch (idx) { case 1: case 14: add(L, Bt); break; case 2: case 13: add(Bt, R); break; case 3: case 12: add(L, R); break; case 4: case 11: add(T, R); break;
        case 5: add(L, T); add(Bt, R); break; case 6: case 9: add(T, Bt); break; case 7: case 8: add(L, T); break; case 10: add(T, R); add(L, Bt); break; }
    }
    return segs;
  }
  const isoSets = (name, levels) => memoP(`iso:${name}:${levels.join(',')}`, async () => { const G2 = await depthGrid(name); return G2 ? levels.map(lv => iso(G2, lv)) : null; }, name);
  async function contours(b, o, S, t, cam, fx, X, p) {
    const name = plateOf(S.id); if (!name) return push(b, o, S, t, cam, fx);
    const levels = p.levels || [.15, .25, .35, .45, .55, .65, .75, .85, .95], sets = await isoSets(name, levels);
    if (!sets) return scan(b, o, S, t, cam, fx, X, p);
    const shown = Math.floor(D.bs(t, S.t0) * 2) + 1, col = p.color || 'rgba(245,243,238,.8)';
    return through(b, t, cam, fx, async () => {
      const r = await MEDIA.drawPlate(b, name, flatCam(cam, name, t), t);
      b.save(); b.lineWidth = 1.2; b.strokeStyle = col;
      sets.forEach((segs, i) => { if (i >= shown) return; b.globalAlpha = (p.alpha ?? .6) * (i === shown - 1 ? 1 : .7); b.beginPath();
        segs.forEach(([u0, v0, u1, v1]) => { const [x0, y0] = r.map(u0, v0), [x1, y1] = r.map(u1, v1); b.moveTo(x0, y0); b.lineTo(x1, y1); }); b.stroke(); });
      b.restore(); return r;
    });
  }

  // DI · scan: a sweep per beat left → right; behind it a point cloud of the depth (near = larger, brighter), fading
  async function scan(b, o, S, t, cam, fx, X, p) {
    const name = plateOf(S.id); if (!name) return push(b, o, S, t, cam, fx);
    const G2 = await depthGrid(name, 96, 54), ph = frac(bpOf(t)), sx = ph, col = p.color || '#F5F3EE';
    return through(b, t, cam, fx, async () => {
      const r = await MEDIA.drawPlate(b, name, flatCam(cam, name, t), t);
      b.save(); b.fillStyle = col;
      if (G2) for (let y = 0; y < G2.gh; y += 1) for (let x = 0; x < G2.gw; x += 1) { const u = (x + .5) / G2.gw, v = (y + .5) / G2.gh; if (u > sx) continue;
        const d = G2.a[y * G2.gw + x], age = sx - u, al = clamp(1 - age * 2.2) * (.25 + .75 * d); if (al <= .02) continue;
        const [px, py] = r.map(u, v); b.globalAlpha = al * (p.alpha ?? .8); const s = 1 + 2.4 * d; b.fillRect(px - s / 2, py - s / 2, s, s); }
      const [lx] = r.map(sx, 0); b.globalAlpha = .9; b.fillStyle = D.takeAccent(X) || col; b.fillRect(lx - 1, 0, 2, H); b.restore();   // the sweep takes an accent (budgeted)
      return r;
    });
  }

  // ------------------------------------------------------------------------------- the subject without detections --
  // `slop edit export` writes no detection boxes, so the subject (the lead mark, 'lead' anchors, crops, the through /
  // match / iris transitions) comes from: the shot's subject_uv → the plate's subject_uv → the largest region of the
  // nearest 12 % of the plate's depth map (Depth-Anything-V2-Small, the same percentile depth.py uses for subject_depth).
  // All image space [u, v, w, h] (0..1); DEV.subjectOf maps it through the shot's camera to screen px.
  const uvOK = v => Array.isArray(v) && v.length >= 4 && v.slice(0, 4).every(x => isFinite(+x)) ? v.slice(0, 4).map(Number) : null;
  // the subject from the depth map: the pixels NEARER THAN THEIR OWN ROW (each row's median is the ground or the wall at that
  // height, so a floor that comes towards the camera never wins), largest connected region, a full-height column (a pillar,
  // a door frame) and an off-centre region count less; when nothing stands out of its row (a close-up: the subject is the
  // frame), the largest region of the nearest 12 % — the source's rule
  const depthSubject = name => memoP(`subj:${name}`, async () => {
    const G2 = await depthGrid(name); if (!G2) return null;
    const { a, gw, gh } = G2, n = gw * gh, med = new Float32Array(gh), row = new Float32Array(gw);
    for (let y = 0; y < gh; y++) { for (let x = 0; x < gw; x++) row[x] = a[y * gw + x]; med[y] = Float32Array.from(row).sort()[Math.floor(gw * .5)]; }
    const g50 = Float32Array.from(a).sort()[Math.floor(n * .5)], th = Float32Array.from(a).sort()[Math.floor(n * .88)];
    const comps = (inside, minN) => { const seen = new Uint8Array(n), out = [];
      for (let i0 = 0; i0 < n; i0++) { if (seen[i0] || !inside(i0)) continue;
        let cnt = 0, x0 = gw, x1 = -1, y0 = gh, y1 = -1, sx = 0; const st = [i0], rw = new Uint16Array(gh); seen[i0] = 1;
        while (st.length) { const i = st.pop(), x = i % gw, y = (i / gw) | 0; cnt++; sx += x; rw[y]++; if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
          for (const j of [x > 0 ? i - 1 : -1, x < gw - 1 ? i + 1 : -1, y > 0 ? i - gw : -1, y < gh - 1 ? i + gw : -1]) if (j >= 0 && !seen[j] && inside(j)) { seen[j] = 1; st.push(j); } }
        if (cnt < minN) continue;
        // a column (a pillar, a door frame) spans the frame's height at a near-constant width; a standing figure that is cut
        // by the frame top and bottom varies (head, shoulders, legs). A region on a side edge counts less too
        let m = 0, v = 0, k = 0; for (let y = y0; y <= y1; y++) { m += rw[y]; k++; } m /= Math.max(1, k); for (let y = y0; y <= y1; y++) v += (rw[y] - m) ** 2; const cv = Math.sqrt(v / Math.max(1, k)) / Math.max(1, m);
        const column = y0 <= 1 && y1 >= gh - 2 && cv < .22, ground = y1 >= gh - 2 && (x1 - x0 + 1) > gw * .7 && (y1 - y0 + 1) < gh * .45, side = x0 <= 0 || x1 >= gw - 1;
        out.push({ cnt, x0, x1, y0, y1, score: cnt * (column ? .3 : 1) * (ground ? .2 : 1) * (side && !ground ? .6 : 1) * (1 - .5 * Math.abs(sx / cnt / gw - .5)) }); }
      return out.sort((p, q) => q.score - p.score); };
    // one erosion first: a figure that touches a wall or a pillar (a hand on it) is usually joined by a thin bridge
    const raw = new Uint8Array(n); for (let i = 0; i < n; i++) raw[i] = a[i] - med[(i / gw) | 0] > .07 && a[i] >= g50 ? 1 : 0;
    const er = new Uint8Array(n); for (let y = 1; y < gh - 1; y++) for (let x = 1; x < gw - 1; x++) { const i = y * gw + x;
      er[i] = raw[i] && raw[i - 1] && raw[i + 1] && raw[i - gw] && raw[i + gw] ? 1 : 0; }
    let best = comps(i => er[i] === 1, n * .008)[0];
    if (best) { best.x0 = Math.max(0, best.x0 - 1); best.y0 = Math.max(0, best.y0 - 1); best.x1 = Math.min(gw - 1, best.x1 + 1); best.y1 = Math.min(gh - 1, best.y1 + 1); }
    if (!best) best = comps(i => raw[i] === 1, n * .01)[0];
    if (!best) best = comps(i => a[i] >= th, n * .01)[0];
    if (!best) return null;
    let u0 = best.x0 / gw - .02, v0 = best.y0 / gh - .02, u1 = (best.x1 + 1) / gw + .02, v1 = (best.y1 + 1) / gh + .02;
    if (u1 - u0 < .08) { const c = (u0 + u1) / 2; u0 = c - .04; u1 = c + .04; } if (v1 - v0 < .08) { const c = (v0 + v1) / 2; v0 = c - .04; v1 = c + .04; }
    u0 = clamp(u0); v0 = clamp(v0); u1 = clamp(u1); v1 = clamp(v1);
    return [u0, v0, u1 - u0, v1 - v0];
  }, name);
  const metaOfShot = sh => { const e = (window.EDL || {})[sh.id] || {}; return { e, meta: e.plate ? ((window.PLATES || {})[e.plate] || {}) : {} }; };
  const depthUsable = meta => meta.depth !== false && (meta.subject_depth != null || meta.depth === true || typeof meta.depth === 'string' || meta.has_depth === true)
    && (typeof ENGINE === 'undefined' || !ENGINE.depthOK || ENGINE.depthOK(meta));
  D.subjectUV = async sh => { if (!sh) return null; const { e, meta } = metaOfShot(sh);
    return uvOK(sh.subject_uv) || uvOK(sh.subject) || uvOK(meta.subject_uv) || uvOK(meta.subject) || (e.plate && depthUsable(meta) && D.has.MEDIA() ? await depthSubject(e.plate) : null); };
  D.subjectOf = async (sh, m) => { const uv = await D.subjectUV(sh); if (!uv) return null; const map = m && m.map ? m.map : (u, v) => [u * W, v * H];
    const [x0, y0] = map(uv[0], uv[1]), [x1, y1] = map(uv[0] + uv[2], uv[1] + uv[3]); return [x0, y0, x1 - x0, y1 - y0]; };
  // static: will the shot have a subject box (detections for a person/face label, a subject_uv, or a usable depth map)?
  D.hasSubject = sh => { const { e, meta } = metaOfShot(sh); if (uvOK(sh.subject_uv) || uvOK(sh.subject) || uvOK(meta.subject_uv) || uvOK(meta.subject)) return true;
    const lab = ((window.PROJECT || {}).lead || {}).label, person = k => k === lab || /subject|person|woman|man|girl|boy|singer|face/.test(k);
    if (e.plate) return Object.keys(meta.boxes || {}).some(person) || depthUsable(meta);
    const sg = e.segs && e.segs[0]; return !!(sg && Object.keys((window.TRACK || {})[sg.clip] || {}).some(person)); };

  // SR · stills in rhythm (EV s027): one crop per `step` beats — the index runs bs/step + .03 and holds on the last crop
  // (params.loop: true cycles the crops on a long shot); a one-frame paper flash on each re-crop (through the flash
  // budget; none when the treatment was picked automatically); a contact strip of the crops with the current one selected
  async function autoCrops(S) {
    const name = plateOf(S.id), meta = ((window.PLATES || {})[name] || {}), bx = meta.boxes || {}, ctr = bb => bb ? [bb[0] + bb[2] / 2, bb[1] + bb[3] / 2] : null;
    let face = ctr(bx['a face']), lead = ctr(bx['a woman'] || bx['a man'] || bx['a person']); const other = Object.entries(bx).filter(([k, v]) => v && !/face|woman|man|person/.test(k)).map(([, v]) => ctr(v))[0];
    const su = await D.subjectUV(S.sh), fr = String((S.sh || {}).framing || '').toUpperCase();
    // a close shot (the board says so, or the subject fills the frame and is not a tall figure): gentler crops around the face
    const close = /^(ECU|CU|MCU)$/.test(fr) || (!!su && su[3] > .55 && (su[3] * 9) / (su[2] * 16) < 1.4);
    if (su) { lead = lead || [su[0] + su[2] / 2, su[1] + su[3] / 2]; face = face || [su[0] + su[2] / 2, su[1] + (close ? su[3] * .36 : Math.min(su[3] * .13, .09))]; }
    // never magnify the plate past ~1.6 screen px per plate px (soft): on a plate narrower than the frame (1456 px at 1920
    // wide: the cover alone is 1.32 ×) the crops' zoom is capped near 1.21, so FACE / DETAIL are gentler there
    let s0 = 1; if (name && D.has.MEDIA()) { try { const P = await MEDIA.plate(name); if (P && P.img) s0 = Math.max(W / P.img.naturalWidth, H / P.img.naturalHeight); } catch (e) { /* missing: reported elsewhere */ } }
    const zmax = Math.max(1.12, 1.6 / Math.max(.3, s0)), Z = z => Math.min(z, zmax);
    const detail = other || (su ? [su[0] + su[2] * .5, su[1] + su[3] * (close ? .7 : .3)] : null);      // the collar / the chest, never the lap
    return [{ zoom: 1.06, cx: .5, cy: .5, s: 'WIDE' },
      face ? { zoom: Z(close ? 1.28 : 1.75), cx: face[0], cy: face[1], s: 'FACE' } : { zoom: Z(1.45), cx: .5, cy: .4, s: 'CLOSE' },
      lead ? { zoom: Z(close ? 1.1 : 1.18), cx: lead[0], cy: lead[1], s: 'MID' } : { zoom: Z(1.14), cx: .56, cy: .52, s: 'MID' },
      detail ? { zoom: Z(close ? 1.5 : 1.9), cx: detail[0], cy: detail[1], s: 'DETAIL' } : { zoom: Z(1.7), cx: .64, cy: .62, s: 'DETAIL' }];
  }
  const cropAt = (S, p, n, t) => { const step = +p.step || 1, t0 = D.beatAfter(S.t0 - 1e-3), bb = D.bs(t, t0) / step + .03, f = Math.floor(bb);
    return { k: p.loop ? ((Math.max(0, f) % n) + n) % n : clamp(f, 0, n - 1), f, sub: frac(Math.max(0, bb)), t0, step }; };
  // the re-crop times (the flash candidates): crop k starts .03 of a step before beat k·step
  D.stillsFlashes = (S, p) => { const n = Array.isArray(p.crops) && p.crops.length ? p.crops.length : 4, step = +p.step || 1, t0 = D.beatAfter(S.t0 - 1e-3), out = [];
    for (let k = 1; k < 64; k++) { if (!p.loop && k > n - 1) break; const s = D.tAtBeat(bpOf(t0) + (k - .03) * step); if (s >= S.t1 - 1e-3) break; if (s > S.t0) out.push(s); } return out; };
  async function stills(b, o, S, t, cam, fx, X, p) {
    const crops = Array.isArray(p.crops) && p.crops.length ? p.crops : await autoCrops(S), n = crops.length, { k, f, sub, t0, step } = cropAt(S, p, n, t);
    const Cr = crops[k], fs = cam.faceSafe; let c = Object.assign({}, cam, { x: .004 * (k % 2 ? -1 : 1) * sub, y: 0, zoom: (+Cr.zoom || 1.06) * (1 + .018 * easeOut(sub)) * (fs ? fs.fxZ : 1), cx: +Cr.cx, cy: +Cr.cy });
    // face-safe: a crop shows all of the face or none of it — one whose centre holds the face's centre is framed to show
    // all of it (calming the shake if it must, fitFace); one aimed elsewhere (DETAIL) that would show a sliver of it slides
    // off it, by what the screen-space camera can show at the shake's worst (else it shows all of it)
    let fxS = fx;
    if (fs && typeof PLATE3D !== 'undefined' && PLATE3D.safeCam) { const [fu, fv, fw, fh] = fs.face, sa = W / H, z = c.zoom, vx = (fs.ia > sa ? sa / fs.ia : 1) / z, vy = (fs.ia > sa ? 1 : fs.ia / sa) / z;
      const ox = clamp(c.cx, vx / 2 + .01, 1 - vx / 2 - .01), oy = clamp(c.cy, vy / 2 + .01, 1 - vy / 2 - .01);
      const safe = () => { const R = fitFace(t, c, fs.ia, fs.face, fxS); c = R.s.cam; fxS = R.r.fx;
        if (X && X.face) { X.face.held = X.face.held || R.s.held; X.face.fits = R.s.fits; if (R.k < 1) X.face.calm = +((X.face.calm ?? 1) * R.k).toFixed(3); } };
      // the image the screen can show around the framing centre (image units), the outer camera's offset and shake at worst
      const O = fs.outer || {}, so = Math.max(1, +O.s || 1), rs = Math.abs(Math.sin(Math.abs(+O.rot || 0) + Math.abs(+O.jr || 0))) * .5;
      const ext = (d, j, pad, v) => [-(.5 + d + j + pad) / so * v, (.5 - d + j + pad) / so * v];
      const ex = ext((+O.dx || 0) / W, Math.abs(+O.jx || 0) / W, rs * H / W, vx), ey = ext((+O.dy || 0) / H, Math.abs(+O.jy || 0) / H, rs * W / H, vy);
      const inWin = fu + fw / 2 > ox + ex[0] && fu + fw / 2 < ox + ex[1] && fv + fh / 2 > oy + ey[0] && fv + fh / 2 < oy + ey[1];
      const cuts = fu < ox + ex[1] && fu + fw > ox + ex[0] && fv < oy + ey[1] && fv + fh > oy + ey[0];
      if (inWin) safe();
      else if (cuts) { const ok = (v, h) => v >= h / 2 + .01 - 1e-9 && v <= 1 - h / 2 - .01 + 1e-9;
        const mv = [['cy', fv + fh / 2 < oy ? fv + fh - ey[0] + .005 : fv - ey[1] - .005, vy, oy], ['cx', fu + fw / 2 < ox ? fu + fw - ex[0] + .005 : fu - ex[1] - .005, vx, ox]]
          .filter(([, v, h]) => ok(v, h)).sort((A, B) => Math.abs(A[1] - A[3]) - Math.abs(B[1] - B[3]))[0];
        if (mv) c = Object.assign({}, c, { [mv[0]]: mv[1] }); else safe(); } }
    const m = await push(b, o, S, t, c, fxS);
    const cut = D.tAtBeat(bpOf(t0) + (f - .03) * step);
    if (f >= 1 && (p.loop || f <= n - 1) && t - cut < 1 / FPS - 1e-6 && t >= cut - 1e-6 && (!X.flashOk || X.flashOk(cut)) && p.flash !== false) { b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.globalAlpha = .35; b.fillStyle = '#fff'; b.fillRect(0, 0, W, H); b.restore(); }
    if (p.strip !== false && !(X && X.covered)) {                                      // (a hero that replaces the footage hides the strip)
      // the contact strip keeps off the shot's lyric blocks — one spot for the whole shot: bottom-right, top-right,
      // bottom-left, top-left, or none (DEV_FRAME.strip false) — and gives way to the devices: the renderer runs it once the
      // blocks are measured (X.defer: the spot and the accent, before the devices) and again once the devices are placed
      // (X.under: a device box or label on its spot leaves it out of that frame, else it is drawn beneath them)
      const rec = (spot, box) => { if (X) (X.labels || (X.labels = [])).push({ kind: 'stills:strip', spot, box: box ? box.map(v => Math.round(v)) : null, rects: box ? [box.map(v => Math.round(v))] : [] }); };
      const strip = async () => {
      const name = plateOf(S.id), P = name ? await MEDIA.plate(name).catch(() => null) : null, tw = 118, th = 66, sw = n * (tw + 10) - 10;
      const spots = [[W - MG().r - sw, H - MG().b - 120], [W - MG().r - sw, MG().t + 60], [MG().l, H - MG().b - 120], [MG().l, MG().t + 60]];
      const lab = X && X.lyricBlocks ? D.spot({ avoid: X.lyricBlocks.map(q => q.rect) }, spots.map(([sx0, sy0]) => [sx0, sy0 - 24, sw, th + 46]), 'stills:strip') : 0;
      if (lab < 0) { if (X) X.strip = false; rec(-1, null); return; }
      const [x0, y0] = spots[lab], box = [x0, y0 - 24, sw, th + 46];
      const thumbs = P && P.img ? memoP(`thumbs:${name}:${JSON.stringify(crops)}`, () => crops.map(cr => { const iw = P.img.naturalWidth, ih = P.img.naturalHeight, vw = .995 / cr.zoom, vh = 1 / cr.zoom,
        cx = clamp(cr.cx, vw / 2, 1 - vw / 2), cy = clamp(cr.cy, vh / 2, 1 - vh / 2), cv = D.mk(236, 132), g = cv.getContext('2d'); g.filter = 'grayscale(1) contrast(1.2)';
        g.drawImage(P.img, (cx - vw / 2) * iw, (cy - vh / 2) * ih, vw * iw, vh * ih, 0, 0, 236, 132); return cv; }), name) : null;
      const ink = D.inkFor(b, [x0, y0 - 20, n * (tw + 10), th + 40], X), acc = D.takeAccent(X) || ink;   // the selected frame takes an accent (budgeted)
      const paint = g => { g.save(); D.font(g, 11, TY().mono, 500); g.fillStyle = ink; g.textBaseline = 'bottom'; D.tracked(g, `CONTACT · ${n} FRAMES / ${step === 1 ? 'BEAT' : step + ' BEATS'}`, x0, y0 - 8, .1);
        crops.forEach((cr, i) => { const xx = x0 + i * (tw + 10); g.globalAlpha = i === k ? 1 : .5; if (thumbs) g.drawImage(thumbs[i], xx, y0, tw, th); else { g.fillStyle = 'rgba(0,0,0,.4)'; g.fillRect(xx, y0, tw, th); }
          g.globalAlpha = 1; g.strokeStyle = i === k ? acc : ink; g.lineWidth = i === k ? 3 : 1; g.strokeRect(xx + .5, y0 + .5, tw - 1, th - 1);
          D.font(g, 11, TY().mono, 500); g.fillStyle = i === k ? acc : ink; g.textBaseline = 'top'; D.tracked(g, `${String(i + 1).padStart(2, '0')} ${String(cr.s || '').toUpperCase()}`, xx, y0 + th + 6, .08); });
        g.restore(); };
      if (!(X && X.under)) { rec(lab, box); paint(o); return; }
      X.under.push(() => {
        const busy = [...(X.boxes || []).map(e => e.box), ...(X.labels || []).filter(l => l.spot >= 0 && !/^stills:/.test(l.kind)).flatMap(l => l.rects)];
        if (D.hitsAny(box, busy)) { X.strip = false; rec(-1, null); return; }
        rec(lab, box); const L = D.scratch(W, H); paint(L.getContext('2d'));
        o.save(); o.setTransform(1, 0, 0, 1, 0, 0); o.globalAlpha = 1; o.globalCompositeOperation = 'destination-over'; o.drawImage(L, 0, 0); o.restore(); });
      };
      if (X && X.defer) X.defer.push(strip); else await strip();
    }
    return m;
  }

  // RP · reproduction: the base as a 1-bit photocopy at 1/4 resolution (ordered dither, the threshold boiling on eighths);
  // kind 'thermal' prints it down the frame on 16ths with a heater line; kind 'mosaic' resolves blocks 28 → 1 on each beat
  const BAY4 = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
  async function xerox(b, o, S, t, cam, fx, X, p) {
    const m = await push(b, o, S, t, cam, fx), kind = p.kind || 'xerox';
    if (kind === 'tiles') {                                                     // split-flap tiles: a diagonal wave of flips on 16ths
      const portrait = H > W, nx = Math.round(clamp(+(p.cols ?? (portrait ? 9 : 16)) || 16, 2, 48)), ny = Math.round(clamp(+(p.rows ?? (portrait ? 16 : 9)) || 9, 2, 48));
      const src = copyBase(b), tw = W / nx, th2 = H / ny, bs = D.bs(t, S.t0), wave = +(p.wave ?? 1.5) || 1.5, fl = .25, bk = '#101215', K = Math.floor(bs);
      const re = K >= Math.ceil(wave + fl) ? Math.floor(hash(K * 1.71 + 3) * nx) : -1, reAge = bs - K;     // after it assembles, one column re-flips on each beat
      b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.fillStyle = bk; b.fillRect(0, 0, W, H); b.imageSmoothingEnabled = true;
      for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
        const d = (i / Math.max(1, nx - 1) + j / Math.max(1, ny - 1)) / 2 * .92 + hash2(i, j) * .08;
        let q = (bs - d * wave) / fl, again = false; if (i === re && reAge < fl && q >= 1) { q = reAge / fl; again = true; }
        const x0 = i * tw, y0 = j * th2;
        if (q <= 0) { b.fillStyle = '#1a1d21'; b.fillRect(x0 + 1, y0 + 1, tw - 2, th2 - 2); continue; }
        const sc = q >= 1 ? 1 : Math.max(.04, Math.abs(Math.cos(Math.PI * q))), hh = th2 * sc, yy = y0 + (th2 - hh) / 2;
        if (q < .5 && !again) { b.fillStyle = '#1a1d21'; b.fillRect(x0 + 1, yy, tw - 2, hh); }
        else b.drawImage(src, x0, y0, tw, th2, x0, yy, tw, hh);
      }
      b.globalAlpha = .55; b.fillStyle = bk;                                    // the seams and each cell's hinge
      for (let i = 1; i < nx; i++) b.fillRect(Math.round(i * tw) - 1, 0, 2, H);
      for (let j = 1; j < ny; j++) b.fillRect(0, Math.round(j * th2) - 1, W, 2);
      b.globalAlpha = .22; for (let j = 0; j < ny; j++) b.fillRect(0, Math.round(j * th2 + th2 / 2), W, 1);
      b.restore(); return m; }
    if (kind === 'mosaic') { const age = D.bs(t, D.tAtBeat(Math.floor(bpOf(t)))), n = Math.max(1, Math.round(lerp(28, 1, easeOut(clamp(age / .3)))));
      if (n > 1) { const w = Math.ceil(W / n), h = Math.ceil(H / n), s = D.scratch(w, h), g = s.getContext('2d'); g.imageSmoothingEnabled = true; g.drawImage(b.canvas, 0, 0, w, h);
        b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.imageSmoothingEnabled = false; b.drawImage(s, 0, 0, w, h, 0, 0, w * n, h * n); b.restore(); }
      return m; }
    const s = D.scratch(480, 270), g = s.getContext('2d', { willReadFrequently: true }); g.imageSmoothingEnabled = true; g.drawImage(b.canvas, 0, 0, 480, 270);
    const I = g.getImageData(0, 0, 480, 270), d = I.data, ink = [18, 18, 18], pap = [238, 237, 232], bias = (hash(Math.floor(bpOf(t) * 2) * 1.37) - .5) * .08;
    const head = kind === 'thermal' ? Math.floor(clamp(D.bs(t, S.t0) / Math.max(1, D.bs(S.t1, S.t0))) * 270 * 1.15) : 270;
    for (let i = 0, q = 0; i < d.length; i += 4, q++) { const x = q % 480, y = (q / 480) | 0;
      if (y > head) { d[i] = pap[0]; d[i + 1] = pap[1]; d[i + 2] = pap[2]; d[i + 3] = 255; continue; }
      const l = (.3 * d[i] + .59 * d[i + 1] + .11 * d[i + 2]) / 255, cc = ((l - .5) * 2.2 + .5 + bias) > (BAY4[(y & 3) * 4 + (x & 3)] + .5) / 16 ? pap : ink;
      d[i] = cc[0]; d[i + 1] = cc[1]; d[i + 2] = cc[2]; d[i + 3] = 255; }
    g.putImageData(I, 0, 0);
    b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.imageSmoothingEnabled = false; b.drawImage(s, 0, 0, W, H);
    if (kind === 'thermal' && head < 270) { b.fillStyle = D.takeAccent(X) || '#121212'; b.fillRect(0, head * H / 270, W, 3); }   // the print head takes an accent (budgeted)
    b.restore(); return m;
  }

  // DG · diagram over image: a grid of thirds, a crosshair and a dimension line on the lead (micro texture on the overlay)
  async function diagram(b, o, S, t, cam, fx, X, p) {
    const m = await push(b, o, S, t, cam, fx), e = easeOut(seg(t, S.t0, S.t0 + D.bl(S.t0)));
    if (X && X.covered) return m;                                                  // a hero replaces the footage: no marks on it
    const lead = D.leadOf(m) || await D.subjectOf(S.sh, m), ink = D.inkFor(b, [0, 0, W, H], X);
    const marks = () => {
    o.save(); (X && X.avoidNow || []).forEach(q => { o.beginPath(); o.rect(-W, -H, 3 * W, 3 * H); o.rect(q[0], q[1], q[2], q[3]); o.clip('evenodd'); });
    o.strokeStyle = ink; o.fillStyle = ink; o.globalAlpha = .28 * e;
    for (let i = 1; i < 3; i++) { D.hair(o, W * i / 3, 0, W * i / 3, H * e, ink, 1); D.hair(o, 0, H * i / 3, W * e, H * i / 3, ink, 1); }
    if (lead) { const [x0, y00, w, h0] = lead, y0 = Math.max(y00, MG().t), h = Math.max(8, Math.min(y00 + h0, H - MG().b) - y0), xr = Math.min(W - MG().r - 60, x0 + w + 24); o.globalAlpha = .85 * e;   // measured inside the frame
      D.hair(o, xr, y0, xr, y0 + h * e, ink, 1.2); D.hair(o, xr - 6, y0, xr + 6, y0, ink, 1.2); D.hair(o, xr - 6, y0 + h * e, xr + 6, y0 + h * e, ink, 1.2);
      D.font(o, 12, TY().mono, 500); o.textBaseline = 'middle'; const rd = `H ${Math.round(h / H * 100)}%`, rw = D.trackedW(o, rd, .08);
      const at = [[xr + 10, 'left'], [xr - 10, 'right']], i = X && X.lyricBlocks ? D.spot({ avoid: X.lyricBlocks.map(q => q.rect), labels: X.labels }, at.map(([lx, al]) => [al === 'left' ? lx : lx - rw, y0 + h / 2 - 9, rw, 18]), 'diagram:readout') : 0;
      if (i >= 0) D.tracked(o, rd, at[i][0], y0 + h / 2, .08, at[i][1]);
      const cx = x0 + w / 2, cy = y0 + h * .3; D.hair(o, cx - 16, cy, cx + 16, cy, ink, 1); D.hair(o, cx, cy - 16, cx, cy + 16, ink, 1); }
    o.restore(); };
    if (X && X.defer) X.defer.push(marks); else marks();
    return m;
  }

  // PM · pure motion design: no footage — a ground and a dot grid that breathes on the kick along a diagonal wave
  async function motion(b, o, S, t, cam, fx, X, p) {
    const light = p.ground === 'paper' || (p.ground == null && X.lightGround), bg = light ? C.paper : C.night, dot = light ? 'rgba(18,18,18,.22)' : 'rgba(245,243,238,.16)';
    b.save(); b.setTransform(1, 0, 0, 1, 0, 0); b.fillStyle = bg; b.fillRect(0, 0, W, H); b.fillStyle = dot;
    const sp = p.spacing || 48, k = D.kick(t), ph = frac(bpOf(t) / 4);
    for (let y = sp / 2; y < H; y += sp) for (let x = sp / 2; x < W; x += sp) { const wave = Math.exp(-Math.pow(frac((x + y) / (W + H) - ph) * 6, 2)), r = 1.4 + 1.6 * k * wave; b.fillRect(x - r / 2, y - r / 2, r, r); }
    b.restore(); return null;
  }
  async function occlusion(b, o, S, t, cam, fx, X, p) { return push(b, o, S, t, cam, fx); }
  async function clip(b, o, S, t, cam, fx) { return push(b, o, S, t, cam, fx); }

  // ------------------------------------------------------------------------------------------------ face-safe ----
  // A push / zoom / crop never cuts the face (Quick E2E: a push cropped the lead above the nose). The protected box (image
  // space): the plate's 'a face' detection (PLATES boxes), else the face read off the subject box (the shot's / plate's
  // subject_uv, else the depth subject) — on a CU / MCU / ECU the brow to the nose (its top half), on wider framings the
  // head (the top 30 % of a standing figure, as an 'a face' anchor reads it). Every plate treatment's camera goes through
  // it: the screen-space zoom of the camera devices (punch, ride, impact, snap; CAM.through) is folded into the image
  // camera so the whole move can be framed, then PLATE3D.safeCam moves the framing centre toward the face and, where that
  // is not enough, holds the zoom (never under 1: the plate always covers the frame) — so the face box stays inside the
  // frame with headroom at every t. A shake / impact burst that would still push it out (its overscan and offsets, framed
  // for their worst) is calmed just enough. The 9:16 cut frames on the subject (MEDIA does it from detections; here from
  // the subject box too). A whip (a transition) is left alone. Off for a shot with treatment param face_safe: false.
  const FACE_CLOSE = /^(ECU|CU|MCU)$/i;
  async function faceOf(S, name, ia) {
    const meta = ((window.PLATES || {})[name]) || {}, fb = (meta.boxes || {})['a face'];
    if (Array.isArray(fb) && fb.length >= 4 && fb.slice(0, 4).every(v => isFinite(+v)) && +fb[2] > 0 && +fb[3] > 0) return { uv: fb.slice(0, 4).map(Number), src: 'a face' };
    const su = await D.subjectUV(S.sh); if (!su || !(su[2] > 0) || !(su[3] > 0)) return null;
    const [u, v, w, h] = su;
    if (FACE_CLOSE.test(String((S.sh || {}).framing || ''))) return { uv: [u + w * .15, v, w * .7, h * .5], src: 'subject (close)' };
    return { uv: [u + w * .3, v, w * .4, Math.min(h * .3, w * .5 * ia)], src: 'subject' };
  }
  const optOf = v => v === true ? {} : typeof v === 'number' ? { amp: v } : (v && typeof v === 'object' ? v : {});
  // the camera devices' screen-space moves calmed by k (0..1): the shake, an impact's burst (its zoom kick stays: the
  // framing holds that), a base move (the snap's jag)
  const shakes = fx => !!(fx && (fx.shake || fx.impact || fx.dx || fx.dy || fx.rot));
  function calm(fx, k) {
    if (!(k < 1)) return fx; const o = Object.assign({}, fx);
    if (o.shake) { const s = optOf(o.shake); o.shake = Object.assign({}, s, { amp: (s.amp ?? 6) * k, rot: (s.rot ?? .002) * k }); }
    if (o.impact) { const s = optOf(o.impact); o.impact = Object.assign({}, s, { shake: (s.shake ?? 14) * k, rot: (s.rot ?? .006) * k }); }
    ['dx', 'dy', 'rot'].forEach(q => { if (o[q]) o[q] *= k; }); return o;
  }
  // the screen-space zoom folded into the image camera → {cam, fx, outer: what CAM.through still does (overscan, offset;
  // the shake's own offsets are noise, a new value every frame, so they are framed for their worst — the amplitude, jx / jy
  // / jr — and the framing and any calming do not flicker with the noise)}; k calms the moves (calm())
  function fold(t, cam, fx, k = 1) {
    const c = Object.assign({}, cam), f0 = calm(fx || {}, k);
    if (!D.has.CAM()) { if (f0.zoom) c.zoom = (c.zoom || 1.06) * (1 + f0.zoom); c.fxZ = f0.zoom ? 1 + f0.zoom : 1; return { cam: c, fx: Object.assign({}, f0, { zoom: 0 }), outer: { s: 1, dx: 0, dy: 0, rot: 0 } }; }
    const o = Object.assign({}, f0); delete o.whip;
    const f = CAM.fx(t, o), z = f.z > 0 ? f.z : 1, P = f.parts || {}, ns = q => (P.shake ? +P.shake[q] || 0 : 0) + (P.impact ? +P.impact[q] || 0 : 0);
    c.zoom = (c.zoom || 1.06) * z; c.fxZ = z;
    const sk = f0.shake ? (optOf(f0.shake).amp ?? 6) : 0, im = f0.impact ? (optOf(f0.impact).shake ?? 14) : 0, rr = (f0.shake ? (optOf(f0.shake).rot ?? .002) : 0) + (f0.impact ? (optOf(f0.impact).rot ?? .006) : 0);
    const need = Math.max(f0.overscan != null ? 1 + f0.overscan : CAM.cover(rr, sk + im, sk + im), CAM.cover(f.rot, f.dx, f.dy));
    return { cam: c, fx: Object.assign({}, f0, { zoom: (f0.zoom || 0) - (z - 1) }),
      outer: { s: need, dx: f.dx - ns('x'), dy: f.dy - ns('y'), rot: f.rot - ns('r'), jx: sk + im, jy: sk * .8 + im, jr: rr } };
  }
  async function faceSafe(S, name, t, cam, fx, X, p) {
    if (p.face_safe === false || (S.sh && S.sh.face_safe === false) || typeof PLATE3D === 'undefined' || !PLATE3D.safeCam || !D.has.MEDIA()) return null;
    const P = await MEDIA.plate(name).catch(() => null); if (!P || !P.img || !P.img.naturalWidth) return null;
    const ia = P.img.naturalWidth / P.img.naturalHeight, F = await faceOf(S, name, ia); if (!F) return null;
    const c0 = Object.assign({}, cam);
    if (PORTRAIT && c0.subject !== false) { const su = MEDIA.subject(P.meta), sb = await D.subjectUV(S.sh);
      const u = su ? su.u : sb ? sb[0] + sb[2] / 2 : F.uv[0] + F.uv[2] / 2; c0.cx = (c0.cx ?? .5) + (u - .5); c0.subject = false; }
    const R = fitFace(t, c0, ia, F.uv, fx), { r, s } = R;
    s.cam.faceSafe = { face: F.uv, ia, outer: r.outer, fxZ: r.cam.fxZ || 1 };
    if (X) X.face = { uv: F.uv, src: F.src, held: s.held, moved: s.moved, fits: s.fits, calm: R.k < 1 ? +R.k.toFixed(3) : null };
    return { cam: s.cam, fx: r.fx };
  }
  // the camera closest to c0 that keeps the face in (PLATE3D.safeCam through the folded camera) → {r: fold's, s: safeCam's,
  // k}. Where the shake (cam.shake, an impact's burst, the snap's jag) and its overscan would still push the face out (a
  // face near the plate's edge: no framing holds it) the shake is calmed by as little as keeps the face in — bisected on its
  // amplitude, so the calming does not flicker with the noise; a face the plate itself cuts keeps the shake as asked.
  // fx may be one fold() already returned (its zoom folded: folding it again changes nothing but the calming)
  function fitFace(t, c0, ia, face, fx) {
    const rank = s => s.fits === 'face' ? 2 : s.fits === 'top' ? 1 : 0;
    const run = k => { const r = fold(t, c0, fx, k); return { r, s: PLATE3D.safeCam(r.cam, ia, face, { outer: r.outer }), k }; };
    let R = run(1);
    if (rank(R.s) < 2 && shakes(fx)) { const R0 = run(0);
      if (rank(R0.s) > rank(R.s)) { let lo = 0, hi = 1; R = R0;
        for (let i = 0; i < 6; i++) { const m = (lo + hi) / 2, Rm = run(m); if (rank(Rm.s) >= rank(R0.s)) { lo = m; R = Rm; } else hi = m; } } }
    return R;
  }

  const FN = { push, layers, multiplane, rack, relight, contours, scan, stills, xerox, diagram, motion, occlusion, clip };
  // draw the base of a planned shot S ({id, t0, t1, sh, treat: {family, params}}); returns the mapper m (or null)
  async function draw(b, o, S, t, cam, fx, X) {
    const tr = S.treat || { family: 'push', params: {} }, f = FN[tr.family] || push, name = tr.family !== 'motion' ? plateOf(S.id) : null;
    let c = Object.assign({}, cam), fx1 = fx || {};
    if (X) X.face = null;
    if (name) { try { const r = await faceSafe(S, name, t, c, fx1, X, tr.params || {}); if (r) { c = r.cam; fx1 = r.fx; } } catch (e) { (window.DEV_ERRORS = window.DEV_ERRORS || []).push(`${S.id} face-safe: ${e && e.message || e}`); } }
    let m = null; try { m = await f(b, o, S, t, Object.assign({}, c), fx1, X, tr.params || {}); }
    catch (e) { (window.DEV_ERRORS = window.DEV_ERRORS || []).push(`${S.id} treatment ${tr.family}: ${e && e.message || e}`); m = await push(b, o, S, t, Object.assign({}, c), fx1).catch(() => null); }
    return m;
  }
  D.treat = { parse, plan, draw, FAMS, CODE, ALIAS, DEPTH, FN, FIVE, RP_KINDS, RP_PRINT, variants, slices, planes, splitOf, mpFallback, plateOf, coverC, depthGrid, depthSubject, cropAt };
})();
