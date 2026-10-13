// devices/cv.js — computer-vision marks tied to what is in frame (≤ 2 per frame; the lead's own mark counts): corner
// brackets / detections with a class chip, the range-finder lock, the fast CV tag, the elbow callout, the leader, the
// lead mark the default renderer puts on every lead_on_screen shot, and the matte outline.
// Ports: the second video's CV.bracket / CV.lock / CV.tag and its chapter-local tagQ (rows finish within the beat), the
// first video's chapter-private det / leader / callout (the fast one: the engine's ANN.callout typed one character a 16th
// after a whole beat, too slow for a one-bar shot). Labels come from params only. Brackets frame, they never cover a face.
// Kit aliases (when nothing else defines them): CV.bracket(o, box, t, opts) · CV.lock(o, box, t, t0, tLock, opts) ·
// CV.tag(o, ax, ay, rows, t, t0, opts) — the second video's signatures, drawn synchronously by these devices.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG['cv.bracket']) return;
  const C = D.C, TY = D.TY;
  // a leader's four ways (the board's dx / dy, then flipped left, up, both): fl, pref (which run clear of the lyric blocks:
  // DEV.spot tries those first; path(flip) → the leader's polyline) and bare (the way for a leader whose label has no free
  // spot: the first clear one, else the board's)
  const flips = (x, dx, dy, path) => { const fl = [[dx, dy], [-dx, dy], [dx, -dy], [-dx, -dy]], pref = fl.map(f => D.clearPath(x, path(f)));
    return { fl, pref, bare: Math.max(0, pref.indexOf(true)) }; };
  const corners = (o, x, y, w, h, L) => { o.beginPath(); [[x, y, 1, 1], [x + w, y, -1, 1], [x, y + h, 1, -1], [x + w, y + h, -1, -1]].forEach(([cx, cy, sx, sy]) => { o.moveTo(cx + sx * L, cy); o.lineTo(cx, cy); o.lineTo(cx, cy + sy * L); }); o.stroke(); };

  // ---- cv.bracket: corner brackets on a box, growing in over an eighth; label + confidence (style 'corners'), or the
  // detection style ('det': corners then the edges draw on over a quarter beat, the class and score in a solid chip).
  // With the device context x the label keeps off the lyric blocks and inside the frame (DEV.spot): above the box's top-left
  // corner, else above its top-right, else below the box (left, then right), else no label — the brackets still frame.
  function bracket(o, box, t, t0, p, col, chipCol, x) {
    const [bx, by, w, h] = box, B = D.bl(t0);
    if (p.style === 'det') {
      const e = clamp(D.bs(t, t0) * 4); if (e <= 0) return;
      const Lc = Math.min(w, h) * .2 + 5; o.strokeStyle = col; o.lineWidth = p.lw || 1.5; corners(o, bx, by, w, h, Lc);
      o.globalAlpha = (p.alpha ?? 1) * .5; o.lineWidth = 1; o.beginPath(); const k = easeOut(e);
      o.moveTo(bx + Lc, by); o.lineTo(bx + Lc + (w - 2 * Lc) * k, by); o.moveTo(bx + w - Lc, by + h); o.lineTo(bx + w - Lc - (w - 2 * Lc) * k, by + h);
      o.moveTo(bx, by + Lc); o.lineTo(bx, by + Lc + (h - 2 * Lc) * k); o.moveTo(bx + w, by + h - Lc); o.lineTo(bx + w, by + h - Lc - (h - 2 * Lc) * k); o.stroke();
      o.globalAlpha = p.alpha ?? 1;
      if (p.label && e >= .5) { const s = p.conf != null ? `${String(p.label).toUpperCase()} ${(+p.conf).toFixed(2)}` : String(p.label).toUpperCase(), size = p.size || 12;
        D.font(o, size, TY().mono, 500); const tw = o.measureText(s).width + s.length * size * .06 + 10, ch = size + 7;
        const up = [bx - .75, by - ch, tw, ch], dn = [bx - .75, by + h, tw, ch], upR = [bx + w - tw, by - ch, tw, ch], dnR = [bx + w - tw, by + h, tw, ch];
        const cands = x ? (p.below ? [dn, up, dnR, upR] : [up, dn, upR, dnR]) : [by - ch >= 4 && !p.below ? up : dn];
        const i = x ? D.spot(x, cands, (x.inst && x.inst.kind || 'cv.bracket') + ':label') : 0; if (i < 0) return;
        const [cx0, cy] = cands[i];
        o.fillStyle = chipCol || col; o.fillRect(cx0, cy, tw, ch); o.fillStyle = (chipCol || col) === C.dark ? C.light : C.dark; o.textBaseline = 'middle'; D.tracked(o, s, cx0 + 5.75, cy + ch / 2 + .5, .06); }
      return;
    }
    const e = easeOut(seg(t, t0, t0 + B / 2)); if (e <= 0) return;
    const n = Math.floor(bpOf(t) * 2), j = p.jitter ?? 0, xx = bx + (hash2(n, 1) - .5) * j, yy = by + (hash2(n, 2) - .5) * j;
    const L = Math.min(w, h) * (p.len ?? .16) * e + 6;
    o.globalAlpha = (p.alpha ?? 1) * clamp(e * 1.5); o.strokeStyle = col; o.lineWidth = p.lw ?? 1.5; corners(o, xx, yy, w, h, L);
    if (p.cross) { D.hair(o, xx + w / 2 - 7, yy + h / 2, xx + w / 2 + 7, yy + h / 2, col, 1.2); D.hair(o, xx + w / 2, yy + h / 2 - 7, xx + w / 2, yy + h / 2 + 7, col, 1.2); }
    if (p.label) { D.font(o, 13, TY().mono, 500); o.fillStyle = col; o.textBaseline = 'bottom';
      const s = String(p.label).toUpperCase(), cs = p.conf != null ? (+p.conf).toFixed(2) : null, lw = D.trackedW(o, s, .08), cw = cs ? D.trackedW(o, cs, .04) : 0;
      // [left x, baseline, span (the score's right end)]: the label above the top-left corner, the score at the box's right
      // (as the source); then the pair right-aligned on the box, then both below it
      const span = cs ? Math.max(w, lw + 60) : lw, tight = cs ? lw + 60 : lw, above = yy - 7, below = yy + h + 7 + 15;
      const spots = [[xx, above, span], [xx + w - tight, above, tight], [xx, below, span], [xx + w - tight, below, tight]];
      const rects = ([lx, base, sp]) => cs ? [[lx, base - 15, lw, 16], [lx + sp - cw, base - 15, cw, 16]] : [[lx, base - 15, lw, 16]];
      const i = x ? D.spot(x, spots.map(rects), (x.inst && x.inst.kind || 'cv.bracket') + ':label') : 0;
      if (i >= 0) { const [lx, base, sp] = spots[i]; D.tracked(o, s, lx, base, .08);
        if (cs) { o.globalAlpha *= .75; D.tracked(o, cs, lx + sp, base, .04, 'right'); } } }
  }
  D.bracket = bracket;
  // portrait cut: brackets and their labels kept inside the safe area (ENGINE.fitBox, engine-core's lead kit rule;
  // integration fix: cv.lead/cv.bracket drew the 'LEAD · 01' label past the top edge in 1080x1920)
  const fit = box => (window.ENGINE && ENGINE.fitBox ? ENGINE.fitBox(box) : box);
  D.register('cv.bracket', {
    role: 'cv', alias: ['bracket', 'det', 'cv.det', 'brackets'], aliasParams: { det: { style: 'det', chip: true }, 'cv.det': { style: 'det', chip: true } },
    defaults: { label: '', conf: null, style: 'corners', len: .16, lw: 1.5, cross: false, jitter: 0, chip: false },
    doc: 'A detection: corner brackets on a thing in frame, with its class label and confidence. Classifies what we see.',
    draw(o, b, t, p, x) {
      const box = fit(x.box()); if (!box) return;     // portrait: inside the safe rect (labels stay in frame)
      const col = p.color || x.ink(box), chipCol = p.chip ? x.acc() : null;
      bracket(o, box, t, x.t0, p, col, chipCol, x);
    },
    example: { kind: 'cv.bracket', anchor: 'lead', key: 'B', params: { label: 'SUBJECT · 01', conf: .97 } },
  });

  // ---- cv.lock: a range-finder that closes in from wide (pad `from` px) onto the target, wobbling while it searches, and
  // snaps on `lock` (a time spec; default one beat after it starts); rows beside it (the first reads ACQUIRING… until locked)
  D.register('cv.lock', {
    role: 'cv', alias: ['lock', 'rangefinder'],
    defaults: { from: 220, rows: [], lock: null, searching: 'ACQUIRING…' },
    doc: 'A range-finder locks onto a target on the word/hit: the moment something is identified or targeted.',
    draw(o, b, t, p, x) {
      const box = x.box(); if (!box || t < x.t0) return;
      const tLock = p.lock != null ? D.time(p.lock, x.sh, x.t0 + D.bl(x.t0)) : x.t0 + D.bl(x.t0), locked = t >= tLock;
      const col = p.color || x.ink(box), lockCol = locked ? x.acc() : col;
      const k = locked ? 1 : easeInOut(seg(t, x.t0, tLock)), pad = lerp(p.from, 10, k) + (locked ? 0 : 6 * Math.sin(t * 40));
      const [bx, by, bw, bh] = [box[0] - pad, box[1] - pad * .6, box[2] + 2 * pad, box[3] + 1.2 * pad];
      o.strokeStyle = locked ? lockCol : col; o.lineWidth = locked ? 2 : 1.2; o.globalAlpha = p.alpha ?? 1;
      corners(o, bx, by, bw, bh, Math.min(bw, bh) * .22);
      if (!locked) { o.globalAlpha *= .5; D.hair(o, bx + bw / 2, 0, bx + bw / 2, by, col, 1); D.hair(o, bx + bw / 2, by + bh, bx + bw / 2, H, col, 1); D.hair(o, 0, by + bh / 2, bx, by + bh / 2, col, 1); D.hair(o, bx + bw, by + bh / 2, W, by + bh / 2, col, 1); }
      o.globalAlpha = p.alpha ?? 1;
      const rows = p.rows || []; if (!rows.length) return;
      D.font(o, 13, TY().mono, 500); o.textBaseline = 'top';
      // the rows beside the frame: right of it, else left of it — off the lyric blocks and inside the frame (else none)
      const rw = Math.max(...[p.searching, ...rows].map(r => D.trackedW(o, String(r).toUpperCase(), .08))) + 4, rh = rows.length * 20 + 2;
      const sides = [[bx + bw + 18, true], [bx - 18, false]], pick = p.free ? (bx + bw + 18 + 240 < W ? 0 : 1) : D.spot(x, sides.map(([sx, r]) => [r ? sx : sx - rw, by - 2, rw, rh]), 'cv.lock:rows');
      if (pick < 0) return; const [rx, right] = sides[pick];
      rows.forEach((r, i) => { if (!locked && i > 0) return; o.globalAlpha = (p.alpha ?? 1) * (i === 0 && !locked ? .6 : 1);
        o.fillStyle = i === 0 && locked ? lockCol : col; D.tracked(o, String(i === 0 && !locked ? p.searching : r).toUpperCase(), rx, by + i * 20, .08, right ? 'left' : 'right'); });
    },
    example: { kind: 'cv.lock', anchor: { uv: [.56, .3, .14, .22] }, key: 'W', params: { rows: ['MATCH · 0.99', 'ID · CONFIRMED'], lock: { beats: 1 } } },
  });

  // ---- cv.tag: a leader from an anchor to a block of mono rows; the leader grows over a 16th and the rows finish typing
  // within the beat (≥ 40 characters a second: the kit's 3-a-16th tag never finished on a one-beat shot)
  D.register('cv.tag', {
    role: 'cv', alias: ['tag', 'tagq', 'cv.tagq'],
    defaults: { rows: [], dx: 90, dy: -50, size: 13, w: 260, fast: true, per16: 3 },
    doc: 'A CV tag: a dot on the thing, a leader, rows of facts typed fast. Names or measures the thing as the word lands.',
    draw(o, b, t, p, x) {
      const a = x.pt(); if (!a || t < x.t0) return; const [ax, ay] = a, col = p.color || x.ink([ax - 20, ay - 80, 320, 120]);
      const B = D.bl(x.t0), ld = p.fast ? B / 4 : B / 2, e = easeOut(seg(t, x.t0, x.t0 + ld));
      // the rows keep off the lyric blocks and inside the frame: the leader flips left, up, or both (DEV.spot; a flip whose
      // leader runs clear of the lyric first), else no rows and the bare leader takes a clear way (flips(), below)
      let dx = p.dx, dy = p.dy, show = true; const rows = (p.rows || []).slice(0, 4);
      if (rows.length && !p.free) { D.font(o, p.size, TY().mono, 500); const rw = Math.max(...rows.map(r => D.trackedW(o, String(r).toUpperCase(), .08))) + 12, rh = rows.length * 19 + 2;
        const F = flips(x, p.dx, p.dy, ([u, v]) => [ax, ay, ax + u, ay + v, ax + u + Math.sign(u || 1) * 26, ay + v]), rect = ([u, v]) => { const rx = ax + u + (u >= 0 ? 32 : -32); return [u >= 0 ? rx : rx - rw, ay + v - 9, rw, rh]; };
        const i = D.spot(x, F.fl.map(rect), 'cv.tag:rows', F.pref); if (i >= 0) [dx, dy] = F.fl[i]; else { show = false; [dx, dy] = F.fl[F.bare]; } }
      o.strokeStyle = col; o.fillStyle = col; o.lineWidth = 1.2; o.globalAlpha = p.alpha ?? 1;
      o.beginPath(); o.arc(ax, ay, 3.5, 0, TAU); o.fill();
      const ex = ax + dx * e, ey = ay + dy * e; o.beginPath(); o.moveTo(ax, ay); o.lineTo(ex, ey); o.lineTo(ex + Math.sign(dx || 1) * 26 * e, ey); o.stroke();
      if (e < 1 || !show) return;
      const rx = dx >= 0 ? ex + 32 : ex - 32, al = dx >= 0 ? 'left' : 'right';
      if (p.fast) D.typedFast(o, p.rows, rx, ey - 9, t, x.t0 + ld, { color: col, size: p.size, align: al });
      else D.typed(o, p.rows, rx, ey - 9, t, x.t0 + ld, { color: col, size: p.size, per16: p.per16, lh: 19, align: al, max: 4, first: true });
    },
    example: { kind: 'cv.tag', anchor: { uv: [.62, .4] }, key: 'W', params: { rows: ['OBJECT · 0.94', 'RANGE · 12 M'], dx: 120, dy: -70 } },
  });

  // ---- callout: a ring on the thing, a leader with one elbow drawn over half a beat, rows typed 3 a 16th after it
  D.register('callout', {
    role: 'cv', alias: ['cv.callout', 'annotation'],
    defaults: { rows: [], dx: 140, dy: -90, size: 13, per16: 3 },
    doc: 'An editorial callout: points at a detail and explains it in two or three typed rows.',
    draw(o, b, t, p, x) {
      const a = x.pt(); if (!a) return; const [ax, ay] = a, B = D.bl(x.t0), e = easeOut(seg(t, x.t0, x.t0 + B * .5)); if (e <= 0) return;
      // the rows keep off the lyric blocks and inside the frame: the elbow flips left, up, or both (as cv.tag), else no rows
      let dx = p.dx, dy = p.dy, show = true; const rows = (p.rows || []).slice(0, 3);
      if (rows.length && !p.free) { D.font(o, p.size, TY().mono, 500); const rw = Math.max(...rows.map(r => D.trackedW(o, String(r).toUpperCase(), .06))) + 12, rh = rows.length * 19 + 2;
        const F = flips(x, p.dx, p.dy, ([u, v]) => [ax, ay, ax + u, ay + v, ax + u + (u >= 0 ? 30 : -30), ay + v]), rect = ([u, v]) => { const tx = ax + u + (u >= 0 ? 38 : -38); return [u >= 0 ? tx : tx - rw, ay + v - 8, rw, rh]; };
        const i = D.spot(x, F.fl.map(rect), 'callout:rows', F.pref); if (i >= 0) [dx, dy] = F.fl[i]; else { show = false; [dx, dy] = F.fl[F.bare]; } }
      const ex = ax + dx, ey = ay + dy, lx = ex + (dx >= 0 ? 30 : -30), col = p.color || x.ink([Math.min(ax, lx) - 10, ey - 30, 340, 90]);
      o.strokeStyle = col; o.lineWidth = 1.2; o.globalAlpha = (p.alpha ?? 1) * x.fade(t); o.beginPath(); o.arc(ax, ay, 4, 0, TAU); o.stroke();
      const k1 = clamp(e * 2), k2 = clamp(e * 2 - 1); o.beginPath(); o.moveTo(ax, ay); o.lineTo(lerp(ax, ex, k1), lerp(ay, ey, k1)); if (k2 > 0) o.lineTo(lerp(ex, lx, k2), ey); o.stroke();
      if (k2 >= 1 && show) D.typed(o, p.rows, dx >= 0 ? lx + 8 : lx - 8, ey - 8, t, x.t0 + B * .5, { size: p.size, lh: 19, align: dx >= 0 ? 'left' : 'right', color: col, colors: p.colors, per16: p.per16, max: 3, alpha: o.globalAlpha });
    },
    example: { kind: 'callout', anchor: { uv: [.31, .62] }, key: 'B', params: { rows: ['KEY · BRASS', 'Ø 24 MM'], dx: 160, dy: -80 } },
  });

  // ---- leader: a ring on the thing and a line that draws on over a quarter beat to a point (to: [x, y] screen px or an
  // anchor spec), with an optional chip at the far end
  D.register('leader', {
    role: 'cv', alias: ['cv.leader'],
    defaults: { to: null, dx: 160, dy: -60, label: '', fill: false },
    doc: 'A leader line from a thing to a label or to another thing: connects two elements (cause and effect, a label to its object).',
    draw(o, b, t, p, x) {
      const a = x.pt(); if (!a) return; const e = easeOut(clamp(x.bs(t) * 4)); if (e <= 0) return;
      let to = p.to; if (to && !Array.isArray(to)) { const bx = D.anchor(to, x); to = bx ? [bx[0] + bx[2] / 2, bx[1] + bx[3] / 2] : null; }
      // the chip keeps off the lyric blocks and inside the frame: a leader with no target flips left, up, or both (one that
      // runs clear of the lyric first; with no chip spot free, the bare line takes a clear way); a chip with nowhere free is
      // left off (the line still connects)
      let chip = !!p.label; const s = String(p.label || '').toUpperCase(), size = p.size || 13; D.font(o, size, TY().mono, 500);
      const cw = o.measureText(s).width + s.length * size * .06 + 14, hh = size + 10, chipAt = q => [q[0] < a[0] ? q[0] - cw : q[0], q[1] - hh / 2, cw, hh];
      if (!to) { const F = flips(x, p.dx, p.dy, ([u, v]) => [a[0], a[1], a[0] + u, a[1] + v]), fl = F.fl.map(([u, v]) => [a[0] + u, a[1] + v]);
        const i = chip && !p.free ? D.spot(x, fl.map(chipAt), 'leader:chip', F.pref) : p.free ? 0 : F.bare; to = fl[i >= 0 ? i : F.bare]; if (i < 0) chip = false; }
      else if (chip && !p.free && D.spot(x, [chipAt(to)], 'leader:chip') < 0) chip = false;
      const col = p.color || x.ink([Math.min(a[0], to[0]) - 10, Math.min(a[1], to[1]) - 10, Math.abs(to[0] - a[0]) + 20, Math.abs(to[1] - a[1]) + 20]);
      o.strokeStyle = col; o.fillStyle = col; o.lineWidth = p.lw || 1.2; o.globalAlpha = p.alpha ?? 1;
      o.beginPath(); o.arc(a[0], a[1], 3.5, 0, TAU); p.fill ? o.fill() : o.stroke();
      o.beginPath(); o.moveTo(a[0], a[1]); o.lineTo(lerp(a[0], to[0], e), lerp(a[1], to[1], e)); o.stroke();
      if (chip && e >= 1) { D.font(o, size, TY().mono, 500); const w = cw, x0 = to[0] < a[0] ? to[0] - w : to[0];
        o.fillStyle = p.chipColor || col; o.fillRect(x0, to[1] - hh / 2, w, hh); o.fillStyle = (p.chipColor || col) === C.dark ? C.light : C.dark; o.textBaseline = 'middle'; D.tracked(o, s, x0 + 7, to[1] + 1, .06); }
    },
    example: { kind: 'leader', anchor: { uv: [.4, .55] }, key: 'B', params: { label: 'PART 01', dx: -180, dy: 60 } },
  });

  // ---- cv.lead: the lead's own mark (the default renderer adds it on lead_on_screen shots; lowest priority in the CV
  // budget): brackets on the body box with the project's label; a face cross on close framings
  D.register('cv.lead', {
    role: 'cv', alias: ['lead'],
    defaults: { label: null, conf: .97, face: false },
    doc: 'The lead\'s identity mark: brackets on her body with a stable label, so the viewer tracks who the video is about.',
    draw(o, b, t, p, x) {
      const box = fit(x.lead || x.box()); if (!box) return;   // portrait: ENGINE.fitBox (a too-wide subject: no mark)
      const PJ = window.PROJECT || {}, col = p.color || x.ink(box);
      bracket(o, box, t, x.t0, { label: p.label || (PJ.chrome || {}).lead_label || PJ.lead_label || 'LEAD · 01', conf: p.conf, len: .16 }, col, null, x);
      const face = p.face && x.m && x.m.box ? fit(x.m.box('a face')) : null;
      if (face && face !== box) bracket(o, face, t, x.t0 + .08, { cross: true, len: .12 }, col);
    },
    example: { kind: 'cv.lead', anchor: 'lead', key: 'B', params: { face: true } },
  });

  // ---- cv.outline: the subject's matte edge as a segmentation outline (occ.js; needs a matte), dashed; without a matte it
  // falls back to brackets on the anchor box
  D.register('cv.outline', {
    role: 'cv', alias: ['outline', 'segmentation'],
    defaults: { dash: [6, 6], lw: 1.4, label: '' },
    doc: 'A segmentation outline traced on the subject\'s matte: the machine sees her shape (person / object segmentation).',
    async draw(o, b, t, p, x) {
      if (t < x.t0) return; const e = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2));
      const box = x.box() || x.lead, col = p.color || x.ink(box);
      if (D.has.OCC() && x.m && typeof x.m.matte === 'function') {
        const n = await OCC.outline(o, x.m, { color: col, lw: p.lw, alpha: (p.alpha ?? 1) * e, dash: p.dash });
        if (n) { if (p.label && box) { D.font(o, 13, TY().mono, 500); o.fillStyle = col; o.textBaseline = 'bottom'; o.globalAlpha = e;
          const s = String(p.label).toUpperCase(), lw = D.trackedW(o, s, .08), spots = [[box[0], box[1] - 7], [box[0] + box[2] - lw, box[1] - 7], [box[0], box[1] + box[3] + 22], [box[0] + box[2] - lw, box[1] + box[3] + 22]];
          const i = D.spot(x, spots.map(([lx, base]) => [lx, base - 15, lw, 16]), 'cv.outline:label'); if (i >= 0) D.tracked(o, s, spots[i][0], spots[i][1], .08); } return; }
      }
      if (box) bracket(o, box, t, x.t0, { label: p.label, len: .16 }, col, null, x);
    },
    example: { kind: 'cv.outline', anchor: 'lead', key: 'B', params: { label: 'SEGMENT · PERSON' } },
  });

  // the second video's CV kit, as thin synchronous adapters over these devices (chapter code ported from it keeps working)
  const kitX = (t, opts) => D.frame({ t, accent: opts.lockColor || opts.accent || C.accent });
  D.alias('CV', {
    bracket: (o, box, t, opts = {}) => { if (!box) return; o.save(); try { bracket(o, box, t, opts.t0 ?? -1e9, opts, opts.color || C.light); } finally { o.restore(); } },
    lock: (o, box, t, t0, tLock, opts = {}) => { if (!box || t < t0) return;
      D.drawSync(o, null, D.adhoc('cv.lock', { from: opts.from ?? 220, rows: opts.rows || [], lock: tLock, color: opts.color || C.light, alpha: opts.alpha }, t0, null, { rect: box }), t, kitX(t, opts)); },
    tag: (o, ax, ay, rows, t, t0, opts = {}) => { if (t < t0) return;
      D.drawSync(o, null, D.adhoc('cv.tag', { rows: rows || [], dx: opts.dx ?? 90, dy: opts.dy ?? -50, size: opts.size || 13, w: opts.w || 260, fast: false, per16: opts.cps ?? 3, color: opts.color || C.light, alpha: opts.alpha }, t0, null, { xy: [ax, ay] }), t, kitX(t, opts)); },
  });
})();
