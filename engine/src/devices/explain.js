// devices/explain.js — the explaining devices the reference videos wrote again and again as bespoke chapter code, made
// generic and data-driven: print-on-quad (a sign face, a screen or a printed page mapped into the plate by a 4-point
// homography, or a panel standing in perspective), the rope of type (a line wound round the subject as a helix, its far
// side behind them), streamlines (a real flow field: lines that bend to attractors that kindle on the words), the graph
// (a molecule or a network drawn bond by bond on the sixteenths: kind `molecule`, alias `network`) and powers of ten (the frame pulls out ×10 a beat into a
// plan of the world around it).
// Ports: the first video's homog()/drawQuad() (hall board, calendar page, sign faces) and the second video's quad() (phone
// screens); its ropeType() (a text helix, mirrored and dimmed behind the body); its attractor streamlines (one steady field,
// resampled by arc length so two fields morph point by point; particles carried along); its molecule() (bonds per 16th,
// the fresh ones in the accent, double bonds offset to the ring's inside); its powers-of-ten plan (a grid that thins as it
// shrinks, the altitude as the readout). Intentional changes: every string, point and graph is a param (the source's
// strings, measured points, molecule and city were story data); the molecule and network are built procedurally from a few
// numbers; the plan is procedural (no map data); a quad that falls mostly outside the frame (the 9:16 cut crops the plate)
// becomes a panel in perspective in a free slot (reported once per shot); everything is a pure function of t (memos only
// for static geometry). Operator safety: each device's check() repairs a malformed param with a warning that names the
// param, what is drawn instead and the exact shape to write (`slop render info` lists them); a device that draws nothing
// on a frame says so (draw returns false), so the layer count never counts it.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.quad) return;
  const C = D.C, TY = D.TY, MG = D.MG;
  const N_ = v => { const n = D.num(v); return typeof n === 'number' && isFinite(n) ? n : NaN; };
  const num = (v, d) => { const n = N_(v); return isFinite(n) ? n : d; };
  const uvPair = v => Array.isArray(v) && v.length >= 2 && isFinite(N_(v[0])) && isFinite(N_(v[1])) ? [N_(v[0]), N_(v[1])] : null;
  const J = v => D.short(v);
  // a list given as a JSON string ('[[.6, .2], …]' — a weaker model sometimes quotes the whole list) → the list, else null
  const jsonList = v => { if (typeof v !== 'string' || !/^\s*\[/.test(v)) return null; try { const j = JSON.parse(v); return Array.isArray(j) ? j : null; } catch (e) { return null; } };
  const mapOf = x => (x.m && typeof x.m.map === 'function' ? x.m.map : (u, v) => [u * W, v * H]);
  // the text of the first line sung in the shot (devices that default to "the line")
  const lineText = x => { const tk = D.shotTokens(x.sh || { t0: x.t0, t1: x.t1 })[0]; if (!tk) return '';
    const ln = (window.LYR || []).find(l => (l.tokens || []).includes(tk)); return ln ? String(ln.text || ln.tokens.map(k => k.txt).join(' ')) : ''; };
  // a placed block's box for the QA hooks (DEV_FRAME.boxes; the portrait check reads them)
  const note = (x, kind, box) => { (x.boxes || []).push({ kind, box, scale: 1 }); };

  // =========================================================================================== print on a quad ===
  // 4-point homography (the first video's solve8/homog), and a flat canvas drawn onto a screen quad [tl, tr, br, bl] in
  // n strips, each an affine piece (vertical strips when the quad recedes left/right, horizontal when it recedes up/down)
  function solve8(A, b) {
    A = A.map(r => r.slice()); b = b.slice(); const n = 8;
    for (let i = 0; i < n; i++) { let mx = i; for (let r = i + 1; r < n; r++) if (Math.abs(A[r][i]) > Math.abs(A[mx][i])) mx = r;
      [A[i], A[mx]] = [A[mx], A[i]]; [b[i], b[mx]] = [b[mx], b[i]]; if (Math.abs(A[i][i]) < 1e-12) return null;
      for (let r = i + 1; r < n; r++) { const f = A[r][i] / A[i][i]; for (let c = i; c < n; c++) A[r][c] -= f * A[i][c]; b[r] -= f * b[i]; } }
    const x = new Array(n).fill(0); for (let i = n - 1; i >= 0; i--) { let s = b[i]; for (let c = i + 1; c < n; c++) s -= A[i][c] * x[c]; x[i] = s / A[i][i]; } return x;
  }
  function homog(src, dst) {
    const A = [], b = []; for (let i = 0; i < 4; i++) { const [x, y] = src[i], [X, Y] = dst[i];
      A.push([x, y, 1, 0, 0, 0, -x * X, -y * X]); b.push(X); A.push([0, 0, 0, x, y, 1, -x * Y, -y * Y]); b.push(Y); }
    const h = solve8(A, b); if (!h) return null;
    return (x, y) => { const d = h[6] * x + h[7] * y + 1; return [(h[0] * x + h[1] * y + h[2]) / d, (h[3] * x + h[4] * y + h[5]) / d]; };
  }
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  function drawQuad(g, src, q, o = {}) {
    const sw = src.width, sh = src.height, Hm = homog([[0, 0], [sw, 0], [sw, sh], [0, sh]], q); if (!Hm) return null;
    const n = Math.max(4, Math.round(o.strips || 32)), vert = Math.abs(dist(q[0], q[3]) - dist(q[1], q[2])) >= Math.abs(dist(q[0], q[1]) - dist(q[3], q[2]));
    g.save(); if (o.alpha != null) g.globalAlpha *= o.alpha; if (o.op) g.globalCompositeOperation = o.op; g.imageSmoothingEnabled = true;
    const m0 = g.getTransform();
    for (let i = 0; i < n; i++) {
      if (vert) { const x0 = sw * i / n, x1 = sw * (i + 1) / n, p00 = Hm(x0, 0), p10 = Hm(x1, 0), p01 = Hm(x0, sh), p11 = Hm(x1, sh);
        const dy = [(p01[0] + p11[0]) / 2 - (p00[0] + p10[0]) / 2, (p01[1] + p11[1]) / 2 - (p00[1] + p10[1]) / 2], sx = Math.min(sw - x0, x1 - x0 + 1);
        g.setTransform(m0); g.transform((p10[0] - p00[0]) / (x1 - x0), (p10[1] - p00[1]) / (x1 - x0), dy[0] / sh, dy[1] / sh, p00[0], p00[1]);
        g.drawImage(src, x0, 0, sx, sh, 0, 0, sx, sh); }
      else { const y0 = sh * i / n, y1 = sh * (i + 1) / n, p00 = Hm(0, y0), p01 = Hm(0, y1), p10 = Hm(sw, y0), p11 = Hm(sw, y1);
        const dx = [(p10[0] + p11[0]) / 2 - (p00[0] + p01[0]) / 2, (p10[1] + p11[1]) / 2 - (p00[1] + p01[1]) / 2], sy = Math.min(sh - y0, y1 - y0 + 1);
        g.setTransform(m0); g.transform(dx[0] / sw, dx[1] / sw, (p01[0] - p00[0]) / (y1 - y0), (p01[1] - p00[1]) / (y1 - y0), p00[0], p00[1]);
        g.drawImage(src, 0, y0, sw, sy, 0, 0, sw, sy); }
    }
    g.restore(); return Hm;
  }
  D.homog = homog; D.drawQuad = drawQuad;
  // the share of a quad inside the frame (7×7 bilinear samples)
  function visible(q) {
    let n = 0; for (let i = 0; i < 7; i++) for (let j = 0; j < 7; j++) { const a = (i + .5) / 7, c = (j + .5) / 7;
      const x = lerp(lerp(q[0][0], q[1][0], a), lerp(q[3][0], q[2][0], a), c), y = lerp(lerp(q[0][1], q[1][1], a), lerp(q[3][1], q[2][1], a), c);
      if (x >= 0 && x <= W && y >= 0 && y <= H) n++; } return n / 49;
  }
  const rowsOf = v => (Array.isArray(v) ? v : v == null || v === '' ? [] : String(v).split(/\s*\|\s*/)).filter(r => r != null && r !== '');
  // the faces: drawn flat at the content's own size (w × h), then mapped onto the quad
  const FACE = {
    // a sign face: kicker, then up to four big lines, one more on each step (a beat): the newest carries the accent bar
    sign(g, w, h, p, t, x, acc) {
      const fg = p.fg || C.light, TYf = TY(), pad = Math.round(w * .07);
      g.fillStyle = p.bg || '#15191c'; g.fillRect(0, 0, w, h);
      g.strokeStyle = fg; g.globalAlpha = .5; g.lineWidth = Math.max(2, w / 240); const ins = Math.round(w * .025); g.strokeRect(ins, ins, w - 2 * ins, h - 2 * ins); g.globalAlpha = 1;
      let y = pad * .8;
      if (p.title) { D.font(g, Math.round(h * .07), TYf.mono, 500); g.fillStyle = fg; g.textBaseline = 'top'; D.tracked(g, String(p.title).toUpperCase(), pad, y, .14); y += h * .14; }
      const lines = rowsOf(p.lines).slice(0, 4), L = lines.length ? lines : [String(p.text || lineText(x) || 'NEXT EXIT').toUpperCase()];
      const lh = (h - y - pad * .6) / L.length, step = num(p.step, 1), b0 = bpOf(x.t0);
      let newest = -1;
      L.forEach((s, k) => { const at = D.tAtBeat(b0 + k * step); if (t < at - 1e-6) return; newest = k;
        let size = p.size ? +p.size : lh * .74; D.font(g, size, TYf.display, 600); const txt = String(s).toUpperCase(), maxW = w - pad * 2 - w * .04;
        const tw = g.measureText(txt).width; if (tw > maxW) { size *= maxW / tw; D.font(g, size, TYf.display, 600); }
        g.fillStyle = fg; g.textBaseline = 'middle'; g.fillText(txt, pad + w * .04, y + lh * (k + .5)); });
      if (newest >= 0) { g.fillStyle = acc; g.fillRect(pad, y + lh * newest + lh * .2, Math.max(4, w * .012), lh * .6); }
    },
    // a screen: a status bar, rows typed on the 16ths (the newest with the cursor), progress along the bottom
    screen(g, w, h, p, t, x, acc) {
      const s = h / 360, TYf = TY(), pad = Math.round(22 * s);
      g.fillStyle = p.bg || '#0c0e11'; g.fillRect(0, 0, w, h);
      g.fillStyle = acc; g.beginPath(); g.arc(pad + 5 * s, pad + 8 * s, 5 * s, 0, TAU); g.fill();
      D.font(g, Math.round(15 * s), TYf.mono, 500); g.fillStyle = C.light; g.textBaseline = 'middle';
      if (p.title) D.tracked(g, String(p.title).toUpperCase(), pad + 18 * s, pad + 8 * s, .12);
      if (p.status) { g.globalAlpha = .6; D.tracked(g, String(p.status).toUpperCase(), w - pad, pad + 8 * s, .1, 'right'); g.globalAlpha = 1; }
      g.fillStyle = 'rgba(245,243,238,.18)'; g.fillRect(pad, pad + 24 * s, w - 2 * pad, Math.max(1, s));
      const rows = rowsOf(p.rows).map(r => Array.isArray(r) ? r.join(' · ') : String(r)), R = rows.length ? rows : [String(lineText(x) || 'READY')];
      const room = h - pad * 2 - 64 * s, lh = Math.min(room / Math.max(3, R.length), 62 * s), size = Math.round(lh * .62);
      D.typed(g, R, pad, pad + 40 * s, t, x.t0, { size, lh: Math.round(lh), per16: num(p.per16, 2), max: Math.max(1, Math.floor(room / lh)), color: C.light, first: true, em: .04 });
      const pr = clamp((t - x.t0) / Math.max(.1, x.t1 - x.t0));
      g.fillStyle = 'rgba(245,243,238,.18)'; g.fillRect(pad, h - pad - 4 * s, w - 2 * pad, 4 * s); g.fillStyle = acc; g.fillRect(pad, h - pad - 4 * s, (w - 2 * pad) * pr, 4 * s);
    },
    // a printed page: a title, a rule, field · value rows one per eighth (the last value in the accent), a barcode
    paper(g, w, h, p, t, x, acc) {
      const ink = p.fg || C.ink, TYf = TY(), s = h / 360, pad = Math.round(26 * s);
      g.fillStyle = p.bg || C.paper; g.fillRect(0, 0, w, h);
      D.font(g, Math.round(46 * s), TYf.display, 600); g.fillStyle = ink; g.textBaseline = 'top';
      const title = String(p.title || lineText(x) || 'NOTICE').toUpperCase(); let ts = 46 * s; const tw = g.measureText(title).width; if (tw > w - 2 * pad) { ts *= (w - 2 * pad) / tw; D.font(g, ts, TYf.display, 600); }
      g.fillText(title, pad, pad); const y0 = pad + ts + 14 * s; D.hair(g, pad, y0, w - pad, y0, ink, Math.max(1, 1.5 * s));
      const rows = rowsOf(p.rows).map(r => Array.isArray(r) ? r : String(r).split(/\s*[:·]\s*/)), n = Math.min(rows.length, Math.floor((h - y0 - 60 * s) / (30 * s)));
      const shown = Math.floor(D.bs(t, x.t0) * 2 + 1e-6) + 1;
      D.font(g, Math.round(18 * s), TYf.mono, 500); g.textBaseline = 'top';
      for (let i = 0; i < Math.min(n, shown); i++) { const [f, v] = [String(rows[i][0] ?? '').toUpperCase(), String(rows[i].slice(1).join(' ') || '').toUpperCase()], yy = y0 + 12 * s + i * 30 * s;
        g.fillStyle = ink; D.tracked(g, f, pad, yy, .06); g.fillStyle = i === n - 1 ? acc : ink; D.tracked(g, v, w - pad, yy, .04, 'right'); }
      if (D.barcode) D.barcode(g, pad, h - pad - 30 * s, Math.min(220 * s, w * .4), 30 * s, title, ink);
    },
  };
  // a panel standing in perspective (no measured quad, or the quad is mostly outside the frame): it swings in from edge-on
  // over half a beat, turned towards the middle of the frame, and breathes on the beat. The projection makes the near edge
  // taller than h (by f / (f − w/2 · sin θ): ≈ 1.08 × at the swing-in for a 640-px panel), so the placed block is that
  // tall, and the drawn corners are shifted back inside the margins; the box recorded for the QA hooks is what is drawn.
  const TH_MAX = 1.25 + .012;
  function panelQuad(x, w, h, t, tilt) {
    const f = 2.2 * Math.max(W, H), hw = w / 2, hh = h / 2, grow = f / Math.max(1, f - hw * Math.sin(TH_MAX)), hp = Math.ceil(h * grow);
    const n0 = (x.boxes || []).length, [px, py] = x.place(w, hp), ent = (x.boxes || [])[n0], k = ent && ent.scale ? ent.scale : 1;
    const cx = px + w / 2, cy = py + hp / 2, side = cx < W / 2 ? 1 : -1;
    const sw = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2)), th = side * (lerp(1.25, clamp(tilt, 0, 1.2) * .7, sw) + .012 * Math.sin(bpOf(t) * Math.PI));
    let q = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]].map(([X, Y]) => { const Xr = X * Math.cos(th), Z = X * Math.sin(th), s = f / (f + Z); return [cx + Xr * s, cy + Y * s]; });
    // device px → screen px (x.place scales a block bigger than the safe area about its corner) and back inside the margins
    const scr = ([X, Y]) => [px + (X - px) * k, py + (Y - py) * k], Mg = MG(), S = q.map(scr);
    const x0 = Math.min(...S.map(v => v[0])), x1 = Math.max(...S.map(v => v[0])), y0 = Math.min(...S.map(v => v[1])), y1 = Math.max(...S.map(v => v[1]));
    const dx = x0 < Mg.l ? Mg.l - x0 : x1 > W - Mg.r ? W - Mg.r - x1 : 0, dy = y0 < Mg.t ? Mg.t - y0 : y1 > H - Mg.b ? H - Mg.b - y1 : 0;
    if (dx || dy) q = q.map(([X, Y]) => [X + dx / k, Y + dy / k]);
    note(x, 'quad.panel', [x0 + dx, y0 + dy, x1 - x0, y1 - y0]);
    return q;
  }
  const okQuad = q => Array.isArray(q) && q.length >= 4 && q.slice(0, 4).every(c => !!uvPair(c));
  const QUAD_EX = '[[.6, .2], [.9, .2], [.9, .4], [.6, .4]]';
  D.register('quad', {
    role: 'hero', alias: ['print.quad', 'print-on-quad', 'homography', 'sign.face', 'surface', 'screen.quad'],
    aliasParams: { 'sign.face': { content: 'sign' }, 'screen.quad': { content: 'screen' } },
    defaults: { quad: null, content: 'sign', title: '', lines: [], rows: [], status: '', text: '', w: 640, h: 360, size: null, step: 1, per16: 2, tilt: .45, print: null, op: null, behind: false, strips: 32 },
    typeSize: p => (p.content === 'sign' && p.size ? +p.size : 0),
    pinned: p => okQuad(p.quad) || okQuad(jsonList(p.quad)),
    check(p, warn) {
      if (p.quad != null) {
        const j = jsonList(p.quad);
        if (j && okQuad(j)) { warn(`quad.params.quad should be a list, not a string — read ${J(p.quad)} as its 4 corners`); p.quad = j; }
        if (!okQuad(p.quad)) { warn(`quad.params.quad needs 4 [u, v] corners (image space 0..1: top-left, top-right, bottom-right, bottom-left) like ${QUAD_EX} — got ${J(p.quad)}; drew a panel in a free slot instead`); p.quad = null; }
        else if (p.quad.length > 4) warn(`quad.params.quad has ${p.quad.length} points — used the first 4 (top-left, top-right, bottom-right, bottom-left)`);
      }
      const c = String(p.content ?? 'sign').toLowerCase().trim();
      if (!FACE[c]) { warn(`quad.params.content '${J(p.content)}' is not one of sign · screen · paper — drew a sign`); p.content = 'sign'; } else p.content = c;
    },
    doc: 'Print on a quad: a sign face, a screen or a printed page mapped into the plate by a 4-point homography (it follows the camera), or a panel standing in perspective: the thing in frame says the line.',
    async draw(o, b, t, p, x) {
      if (t < x.t0) return false;
      const w = Math.round(clamp(num(p.w, 640), 120, 1600)), h = Math.round(clamp(num(p.h, 360), 80, 1200)), kind = FACE[p.content] ? p.content : 'sign';
      const src = D.scratch(w, h), g = src.getContext('2d'), acc = x.acc();
      FACE[kind](g, w, h, p, t, x, acc);
      g.letterSpacing = '0px'; g.globalAlpha = 1;
      const rv = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2));                // the face prints top → bottom over half a beat
      if (rv < 1) { g.save(); g.globalCompositeOperation = 'destination-in'; g.fillStyle = '#000'; g.fillRect(0, 0, w, Math.max(1, h * rv)); g.restore();
        g.fillStyle = acc; g.fillRect(0, Math.max(0, h * rv - 3), w, 3); }
      const map = mapOf(x), Q = okQuad(p.quad) ? p.quad.slice(0, 4).map(uvPair) : null;
      let q = Q ? Q.map(([u, v]) => map(u, v)) : null;
      if (q && visible(q) < .92) {                                             // cut by the frame edge (the 9:16 crop): a panel instead
        if (x.sh && x.sh.id) D.report(`${x.sh.id}: quad's corners fall outside the ${H > W ? '9:16' : '16:9'} frame (the crop or the camera cuts it) → drew a panel in a free slot; move the corners inside the frame to keep it printed on the plate`);
        q = null; }
      const a = (p.alpha ?? 1) * x.fade(t);
      if (q) {                                                                  // pinned to the plate: printed INTO the footage (the base)
        const print = p.print ?? true, op = p.op || (kind === 'paper' ? 'multiply' : 'source-over'), tgt = print && b ? b : o;
        const put = (gg, opx = op) => { gg.save(); gg.setTransform(1, 0, 0, 1, 0, 0); gg.globalAlpha = a; drawQuad(gg, src, q, { strips: p.strips, op: opx }); gg.restore(); };
        if (p.behind && D.has.OCC() && x.m && (x.m.matte || x.m.depth)) { tgt.save(); tgt.globalCompositeOperation = op; await OCC.behind(tgt, x.m, gg => put(gg, 'source-over'), { mode: 'auto' }); tgt.restore(); }
        else put(tgt);
        return;
      }
      const pq = panelQuad(x, w, h, t, num(p.tilt, .45));
      o.globalAlpha = a; drawQuad(o, src, pq, { strips: p.strips });
      o.strokeStyle = p.color || x.ink(); o.globalAlpha = a * .7; o.lineWidth = 1.2; o.beginPath(); pq.forEach((pt, i) => i ? o.lineTo(pt[0], pt[1]) : o.moveTo(pt[0], pt[1])); o.closePath(); o.stroke();
    },
    example: { kind: 'quad', anchor: { slot: 'top-right' }, key: 'B', params: { content: 'screen', title: 'queue', status: '3 jobs', rows: ['JOB 01 · DONE', 'JOB 02 · RUNNING', 'JOB 03 · WAITING'] } },
  });

  // ============================================================================================== rope of type ===
  // glyphs along a descending helix round (cx, cy) (3D radius R, ellipse ry); side 'front' | 'back'. On the far side the
  // glyphs read mirrored and compress at the edges (the foreshortening of a real wrap); the separator takes the accent
  function ropeSide(g, side, s) {
    const { text, cx, cy, R, ry, pitch, turns, ph0, size, col, acc, alpha, sepFrom, grow } = s;
    D.font(g, size, TY().sign, 800); g.textBaseline = 'middle';
    const cw = {}, wOf = ch => cw[ch] ?? (cw[ch] = g.measureText(ch).width), total = turns * TAU * R * grow;
    let ph = ph0, i = 0, dd = 0; const m0 = g.getTransform();
    while (dd < total && i < 900) {
      const k = i % text.length, ch = text[k], w = wOf(ch) * 1.06 + 1, d = w / R; ph -= d / 2;
      const sn = Math.sin(ph), cs = Math.cos(ph), front = sn > 0;
      if ((side === 'front') === front && ch.trim()) {
        const x = cx + R * cs, y = cy + ry * sn + pitch * (dd + w / 2) / (R * TAU), ex = sn, ey = (-ry * cs) / R * .4;
        g.setTransform(m0); g.transform(ex, ey, 0, 1, x, y); g.globalAlpha = alpha * (front ? 1 : .5); g.fillStyle = k >= sepFrom ? acc : col; g.fillText(ch, -wOf(ch) / 2, 0);
      }
      ph -= d / 2; dd += w; i++;
    }
    g.setTransform(m0); g.globalAlpha = 1;
  }
  D.register('rope', {
    role: 'hero', alias: ['rope.type', 'type.helix', 'helix', 'wrap.type'],
    defaults: { text: '', sep: ' · ', turns: 1.35, height: .55, r: null, ry: .15, pitch: 70, size: 40, speed: 1.4, beats: 1, behind: true },
    doc: 'The rope of type: a line of words wound round the subject as a helix, the far side behind them — bound, tied, wrapped, held by words.',
    pinned: () => true,
    async draw(o, b, t, p, x) {
      if (t < x.t0) return false;
      const box = x.box() || x.lead || [W * .38, H * .18, W * .24, H * .64], Mg = MG(), size = clamp(num(p.size, 40), 14, 120);
      const turns = clamp(num(p.turns, 1.35), .3, 4), pitch = clamp(num(p.pitch, 70), 0, 300);
      let R = p.r != null && isFinite(N_(p.r)) ? N_(p.r) : clamp(box[2] / 2 * .94, 140, 380); R = Math.max(40, Math.min(R, (W - Mg.l - Mg.r) / 2 - size));
      const ry = R * clamp(num(p.ry, .15), 0, .6), cx = clamp(box[0] + box[2] / 2, Mg.l + R + size / 2, W - Mg.r - R - size / 2);
      const top = Mg.t + ry + size, bot = H - Mg.b - ry - pitch * turns - size, cy = clamp(box[1] + box[3] * clamp(num(p.height, .55), 0, 1), top, Math.max(top, bot));
      const sep = String(p.sep ?? ' · '), base = String(p.text || lineText(x) || 'HOLD ON').toUpperCase().trim(), text = base + sep;
      const grow = easeOut(clamp(D.bs(t, x.t0) / Math.max(.25, num(p.beats, 1)))), col = p.color || x.ink([cx - R, cy - ry - size, 2 * R, 2 * ry + pitch * turns + 2 * size]);
      const s = { text, cx, cy, R, ry, pitch, turns, ph0: Math.PI * .5 + (t - x.t0) * num(p.speed, 1.4), size, col, acc: x.acc(), alpha: (p.alpha ?? 1) * x.fade(t), sepFrom: base.length, grow };
      const back = g => ropeSide(g, 'back', s);
      if (p.behind !== false && D.has.OCC() && x.m && (x.m.matte || x.m.depth)) await OCC.behind(o, x.m, back, { mode: 'auto' }); else back(o);
      ropeSide(o, 'front', s);
      note(x, 'rope', [cx - R - size / 2, cy - ry - size, 2 * R + size, 2 * ry + pitch * turns + 2 * size]);
    },
    example: { kind: 'rope', anchor: 'lead', key: 'B', params: { text: 'HOLD ME TO IT', turns: 1.35 } },
  });

  // =============================================================================================== streamlines ===
  // one steady field (lines never cross): the pull of each kindled attractor (∝ 1/d, strength k) plus a drift; from each
  // seed a streamline is integrated in image space (a 1600 × 900 design frame) until it reaches an attractor, then
  // resampled by arc length to NP points so the field of k attractors morphs point by point into the field of k + 1
  const NP = 48, DW = 1600, DH = 900;
  // attractors are objects {uv: [u, v], k, label, at} by the time they get here (check() turns [u, v, k] rows into them)
  function attractorsOf(p) {
    const A = Array.isArray(p.attractors) ? p.attractors : [];
    return A.map(a => { const uv = a && typeof a === 'object' && !Array.isArray(a) ? uvPair(a.uv || [a.u, a.v]) : null;
      if (!uv) return null; return { u: uv[0], v: uv[1], k: clamp(num(a.k, 1.3), .1, 5), label: a.label ?? '', at: a.at ?? null }; })
      .filter(Boolean).slice(0, 6).map((a, i) => Object.assign(a, { i }));
  }
  const ATTR_EX = '[{"uv": [.3, .4], "k": 1.4}, {"uv": [.7, .35], "k": 1.6, "at": {"beats": 1}}]';
  function checkFlow(p, warn) {
    if (p.attractors != null) {
      const A = jsonList(p.attractors) || p.attractors;
      if (Array.isArray(A)) {
        const out = [];
        A.forEach((a, i) => {
          if (Array.isArray(a) && uvPair(a)) { out.push({ uv: uvPair(a), k: a[2], label: a[3] ?? '' }); return; }      // [u, v, k?, label?] is fine
          if (a && typeof a === 'object' && !Array.isArray(a)) {
            if (uvPair(a.uv) || uvPair([a.u, a.v])) { out.push(a); return; }
            const xy = uvPair([a.x, a.y]);
            if (xy && xy.every(v => v >= -.5 && v <= 1.5)) { out.push(Object.assign({}, a, { uv: xy })); warn(`streamlines.params.attractors[${i}]: read {"x": ${xy[0]}, "y": ${xy[1]}} as image space {"uv": [${xy[0]}, ${xy[1]}]} — write "uv"`); return; }
          }
          warn(`streamlines.params.attractors[${i}] ${J(a)} has no image-space point — dropped; write {"uv": [u, v], "k": 1.4} (u, v 0..1 across the plate)`);
        });
        if (out.length > 6) warn(`streamlines.params.attractors has ${out.length} — only the first 6 are drawn`);
        if (!out.length) warn(`streamlines has no attractor it can read — it draws nothing; write "attractors": ${ATTR_EX}`);
        p.attractors = out;
      }
    }
    if (p.points != null && !(Array.isArray(p.points) && !p.points.length)) {
      const P = jsonList(p.points) || p.points, ok = Array.isArray(P) ? P.filter(v => !!uvPair(v)) : [];
      if (!Array.isArray(P) || ok.length < P.length) warn(`streamlines.params.points: ${Array.isArray(P) ? `${P.length - ok.length} of ${P.length}` : J(P)} not [u, v] pairs — ${ok.length ? 'dropped' : `the lines start from "from" instead`}; write [[.1, .9], [.2, .1]]`);
      p.points = ok;
    }
    if (p.from != null && !(Array.isArray(p.from) && p.from.length >= 4 && p.from.slice(0, 4).every(v => isFinite(N_(v))))) {
      warn(`streamlines.params.from should be an image-space box [u, v, w, h] like [.36, .56, .28, .38] — got ${J(p.from)}; the lines start from the default box`); p.from = [.36, .56, .28, .38]; }
    if (p.drift != null && !(Array.isArray(p.drift) && p.drift.length >= 2 && isFinite(N_(p.drift[0])) && isFinite(N_(p.drift[1])))) {
      warn(`streamlines.params.drift should be [dx, dy] like [0, -.35] — got ${J(p.drift)}; used [0, -.35]`); p.drift = [0, -.35]; }
  }
  function seedsOf(p) {
    const pts = Array.isArray(p.points) ? p.points.map(uvPair).filter(Boolean).slice(0, 80) : []; if (pts.length) return pts;
    const n = Math.round(clamp(num(p.seeds, 18), 1, 80)), f = Array.isArray(p.from) && p.from.length >= 4 ? p.from.map(v => num(v, .5)) : [.36, .56, .28, .38];
    return Array.from({ length: n }, (_, i) => [f[0] + f[2] * frac(i * .6180339887 + .31), f[1] + f[3] * (i + .5) / n]);
  }
  function stream(u0, v0, act, drift, step) {
    let x = u0 * DW, y = v0 * DH, end = -1; const P = [[x, y]];
    for (let s = 0; s < 600 && end < 0; s++) {
      let fx = drift[0], fy = drift[1];
      for (const A of act) { const dx = A.u * DW - x, dy = A.v * DH - y, d = Math.hypot(dx, dy); if (d < 12) { end = A.i; break; } fx += A.k * dx / d * 500 / d; fy += A.k * dy / d * 500 / d; }
      if (end >= 0) break;
      const l = Math.hypot(fx, fy) || 1; x += fx / l * step; y += fy / l * step; P.push([x, y]);
      if (x < -.1 * DW || x > 1.1 * DW || y < -.1 * DH || y > 1.1 * DH) break;
    }
    if (end >= 0) { const A = act.find(a => a.i === end); P.push([A.u * DW, A.v * DH]); }
    const L = [0]; for (let i = 1; i < P.length; i++) L.push(L[i - 1] + Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]));
    const out = []; let j = 0; for (let k = 0; k < NP; k++) { const s = L[L.length - 1] * k / (NP - 1); while (j < L.length - 2 && L[j + 1] < s) j++;
      const f = clamp((s - L[j]) / ((L[j + 1] - L[j]) || 1)), A = P[j], B = P[Math.min(j + 1, P.length - 1)]; out.push([lerp(A[0], B[0], f) / DW, lerp(A[1], B[1], f) / DH]); }
    return out;
  }
  const field = p => { const A = attractorsOf(p), S = seedsOf(p), dr = Array.isArray(p.drift) ? [num(p.drift[0], 0), num(p.drift[1], -.35)] : [0, -.35], st = clamp(num(p.step, 8), 2, 40);
    return D.memo(`flow:${JSON.stringify([A.map(a => [a.u, a.v, a.k]), S, dr, st])}`, () => ({ A, S, F: A.map((_, k) => S.map(([u, v]) => stream(u, v, A.slice(0, k + 1), dr, st))) })); };
  D.register('streamlines', {
    role: 'hero', alias: ['flow', 'field', 'attractors', 'flowfield'],
    defaults: { attractors: [{ uv: [.24, .34], k: 1.3 }, { uv: [.82, .3], k: 1.8, at: { beats: 1 } }], seeds: 18, points: [], from: [.36, .56, .28, .38], drift: [0, -.35], step: 8, beats: 2, lw: 1.3, alpha: .6, particles: true, behind: false },
    doc: 'Streamlines: a real flow field — every line bends to the attractors as they kindle on the words; pull, influence, everyone drifting to one place.',
    pinned: () => true,
    check: checkFlow,
    async draw(o, b, t, p, x) {
      const Fd = field(p); if (!Fd.A.length || !Fd.S.length) return false;
      const ta = Fd.A.map((A, i) => D.time(A.at, x.sh, null) ?? D.tAtBeat(bpOf(x.t0) + i)), lit = ta.filter(v => t >= v - 1e-6).length;
      if (lit === 0) return false;
      const bl = D.bl(t), k = lit - 1, swing = k > 0 ? easeInOut(seg(t, ta[k], ta[k] + bl)) : 1, grow = easeInOut(seg(t, ta[0], ta[0] + Math.max(.25, num(p.beats, 2)) * bl));
      const map = mapOf(x), A0 = Fd.F[Math.max(0, k - 1)], A1 = Fd.F[k], n = Math.max(2, Math.round(NP * grow));
      const pts = Fd.S.map((_, s) => A1[s].map((q, i) => [lerp(A0[s][i][0], q[0], swing), lerp(A0[s][i][1], q[1], swing)]));
      const xs = Fd.A.map(A => map(A.u, A.v)), bx = [Math.min(...xs.map(q => q[0])) - 40, Math.min(...xs.map(q => q[1])) - 40, 0, 0];
      bx[2] = Math.max(...xs.map(q => q[0])) + 40 - bx[0]; bx[3] = Math.max(...xs.map(q => q[1])) + 40 - bx[1];
      const col = p.color || x.ink(bx), acc = x.acc(), a = (p.alpha ?? .6) * x.fade(t), pk = D.pulse(t, 'kick', { tau: .15 });
      const lines = g => { g.save(); g.lineWidth = num(p.lw, 1.3); g.strokeStyle = col; g.lineCap = 'round'; g.lineJoin = 'round'; g.globalAlpha = a;
        pts.forEach(L => { g.beginPath(); for (let i = 0; i < n; i++) { const [px, py] = map(L[i][0], L[i][1]); i ? g.lineTo(px, py) : g.moveTo(px, py); } g.stroke(); });
        if (p.particles !== false) { g.fillStyle = col; g.globalAlpha = Math.min(1, a * 1.6);
          const q = frac(Math.max(0, D.bs(t, ta[0])) / 4) * (n - 1);
          pts.forEach((L, s) => { const qq = (q + s * 3.7) % Math.max(1, n - 1), j = Math.floor(qq), f = qq - j, A = L[j], B = L[Math.min(j + 1, n - 1)], [px, py] = map(lerp(A[0], B[0], f), lerp(A[1], B[1], f));
            g.beginPath(); g.arc(px, py, 2.6 + 1.6 * pk, 0, TAU); g.fill(); }); }
        g.restore(); };
      // drawn on a layer with the lyric's region cleared (no line crosses the words), then onto the overlay (or behind the subject)
      const Lc = D.scratch(W, H), lg = Lc.getContext('2d'); lines(lg);
      (x.avoid || []).forEach(r => { if (r) lg.clearRect(r[0] - 18, r[1] - 18, r[2] + 36, r[3] + 36); });
      const put = g => { g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.drawImage(Lc, 0, 0); g.restore(); };
      if (p.behind && D.has.OCC() && x.m && (x.m.matte || x.m.depth)) await OCC.behind(o, x.m, put, { mode: 'auto' }); else put(o);
      // the attractors: a ring that closes on the kick (the newest kindled in the accent), its label typed fast
      const Mg = MG();
      Fd.A.forEach((A, i) => { if (t < ta[i] - 1e-6) return; const kin = easeOut(seg(t, ta[i], ta[i] + bl / 2)), [ax, ay] = xs[i], newest = i === k;
        if (ax < 0 || ay < 0 || ax > W || ay > H) return;                   // off the frame (a crop, the 9:16 cut): no ring, no label
        o.save(); o.globalAlpha = .95 * kin * x.fade(t); o.strokeStyle = newest ? acc : col; o.lineWidth = 2; o.beginPath(); o.arc(ax, ay, 18 + 6 * A.k + 12 * pk, 0, TAU); o.stroke();
        o.fillStyle = newest ? acc : col; o.beginPath(); o.arc(ax, ay, 4, 0, TAU); o.fill();
        const lab = A.label || (Array.isArray(p.labels) ? p.labels[i] : ''); if (lab) { const lx = clamp(ax + 28, Mg.l, W - Mg.r - 240), ly = clamp(ay - 44, Mg.t, H - Mg.b - 40);
          D.typedFast(o, [String(lab)], lx, ly, t, ta[i], { size: 13, color: col }); }
        o.restore(); });
    },
    example: { kind: 'streamlines', key: 'B', params: { attractors: [{ uv: [.22, .32], k: 1.3, label: 'SOURCE A' }, { uv: [.8, .28], k: 1.8, label: 'SOURCE B', at: { beats: 1 } }], seeds: 16 } },
  });

  // ================================================================================================== molecule ===
  // a molecule (a generic skeletal formula built from a few numbers) or a network (a hub and its nearest neighbours),
  // or your own nodes/edges, drawn bond by bond: `per` bonds on every 16th, the fresh ones in the accent; a double bond's
  // second line sits on the ring's inside; atom/node labels appear when a bond reaches them
  function molecule(p) {
    const L = 1, dx = Math.cos(Math.PI / 6), atoms = [], bonds = [], seq = [];
    const A = (x, y, lab = '') => { atoms.push({ x, y, lab }); return atoms.length - 1; };
    const add = (a, c, k = 1, rc = null) => { bonds.push({ a, c, k, rc }); seq.push(bonds.length - 1); };
    const n = Math.round(clamp(num(p.chain, 8), 3, 18)); let rings = Math.round(clamp(num(p.rings, 2), 0, 4));
    const bb = []; for (let i = 0; i < n; i++) bb.push(A(i * dx, i % 2 ? -L / 2 : 0, i === 0 ? 'H₂N' : i % 3 === 0 ? 'N' : ''));
    const ring = (x0, y0, ang, m) => { const R = L / (2 * Math.sin(Math.PI / m)), cx = x0 + Math.cos(ang) * R, cy = y0 + Math.sin(ang) * R, a0 = Math.atan2(y0 - cy, x0 - cx);
      return { pts: Array.from({ length: m }, (_, k) => [cx + R * Math.cos(a0 + k * TAU / m), cy + R * Math.sin(a0 + k * TAU / m)]), c: [cx, cy] }; };
    for (let i = 0; i < n - 1; i++) {
      add(bb[i], bb[i + 1]);
      const j = i + 1, up = j % 2 === 1, dir = up ? -1 : 1, a = atoms[bb[j]];
      if (j % 3 === 2 && j < n - 1) add(bb[j], A(a.x, a.y + dir * L, 'O'), 2);                     // the carbonyl
      if (j % 3 === 1 && j < n - 1) {                                                               // a side chain
        const c1 = A(a.x, a.y + dir * L); add(bb[j], c1);
        if (rings > 0) { rings--; const r = ring(atoms[c1].x, atoms[c1].y, dir * Math.PI / 2, 6), ids = [c1];
          for (let k = 1; k < 6; k++) ids.push(A(r.pts[k][0], r.pts[k][1], k === 3 && j % 2 ? 'N' : ''));
          for (let k = 0; k < 6; k++) add(ids[k], ids[(k + 1) % 6], k % 2 ? 1 : 2, r.c); }
        else { const c2 = A(a.x + dx * (j % 2 ? .5 : -.5) * 1.6, a.y + dir * L * 1.5); add(c1, c2); }
      }
    }
    const last = atoms[bb[n - 1]], up = (n - 1) % 2 === 1; add(bb[n - 1], A(last.x + dx, last.y + (up ? L / 2 : -L / 2), 'OH')); add(bb[n - 1], A(last.x, last.y + (up ? -L : L), 'O'), 2);
    return { atoms, bonds, seq, mol: true };
  }
  function network(p) {
    const n = Math.round(clamp(num(p.count, 14), 3, 60)), seed = num(p.seed, 1), atoms = [], bonds = [], seq = [], ga = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) { const r = i ? Math.sqrt(i / n) * (.9 + .2 * hash2(i, seed)) : 0, a = i * ga + hash2(seed, i) * .5; atoms.push({ x: Math.cos(a) * r * 1.6, y: Math.sin(a) * r, lab: '' }); }
    const lab = Array.isArray(p.labels) ? p.labels : []; lab.forEach((s, i) => { if (atoms[i]) atoms[i].lab = String(s); });
    const near = (i, k) => atoms.map((q, j) => [j, Math.hypot(q.x - atoms[i].x, q.y - atoms[i].y)]).filter(([j]) => j < i).sort((a, b) => a[1] - b[1]).slice(0, k).map(([j]) => j);
    for (let i = 1; i < n; i++) { const nb = near(i, i % 3 === 0 ? 2 : 1); nb.forEach(j => { bonds.push({ a: j, c: i, k: 1 }); seq.push(bonds.length - 1); }); }
    return { atoms, bonds, seq, hub: Math.round(clamp(num(p.hub, 0), 0, n - 1)) };
  }
  function custom(p) {
    const atoms = (Array.isArray(p.nodes) ? p.nodes : []).map(nd => Array.isArray(nd) ? { x: num(nd[0], 0), y: num(nd[1], 0), lab: String(nd[2] ?? '') }
      : nd && typeof nd === 'object' ? { x: num(nd.x, 0), y: num(nd.y, 0), lab: String(nd.label ?? nd.lab ?? ''), id: nd.id } : { x: 0, y: 0, lab: '' });
    const idx = v => { const n = N_(v); if (isFinite(n)) return n; const i = atoms.findIndex(a => a.id === v || a.lab === v); return i; };
    const bonds = (Array.isArray(p.edges) ? p.edges : []).map(e => Array.isArray(e) ? { a: idx(e[0]), c: idx(e[1]), k: num(e[2], 1) } : e && typeof e === 'object' ? { a: idx(e.a ?? e.from), c: idx(e.b ?? e.to), k: num(e.k, 1) } : { a: -1, c: -1, k: 1 })
      .filter(e => atoms[e.a] && atoms[e.c] && e.a !== e.c);
    return { atoms, bonds, seq: bonds.map((_, i) => i), hub: N_(p.hub) };
  }
  const graphOf = p => D.memo(`graph:${JSON.stringify([p.preset, p.chain, p.rings, p.count, p.seed, p.hub, p.labels, p.nodes, p.edges])}`,
    () => (Array.isArray(p.nodes) && p.nodes.length && Array.isArray(p.edges) && p.edges.length ? custom(p) : p.preset === 'network' ? network(p) : molecule(p)));
  const nodeOK = nd => Array.isArray(nd) ? isFinite(N_(nd[0])) && isFinite(N_(nd[1])) : !!nd && typeof nd === 'object' && isFinite(N_(nd.x)) && isFinite(N_(nd.y));
  function checkGraph(p, warn) {
    const pre = String(p.preset ?? 'molecule').toLowerCase().trim();
    if (pre !== 'molecule' && pre !== 'network') { warn(`molecule.params.preset ${J(p.preset)} is not molecule · network — drew a molecule`); p.preset = 'molecule'; } else p.preset = pre;
    const nodes = jsonList(p.nodes) || p.nodes, edges = jsonList(p.edges) || p.edges, stock = `the stock ${p.preset}`;
    const hasN = Array.isArray(nodes) && nodes.length > 0, hasE = Array.isArray(edges) && edges.length > 0;
    if (hasN && !hasE) warn(`molecule.params.nodes has no "edges" — drew ${stock} instead; add "edges": [[0, 1], [1, 2]] (pairs of node indexes from 0, or labels; a third number 2 = a double bond)`);
    if (hasE && !hasN) warn(`molecule.params.edges has no "nodes" — drew ${stock} instead; add "nodes": [{"x": 0, "y": 0, "label": "A"}, {"x": 1, "y": 0, "label": "B"}]`);
    if (!hasN || !hasE) return;
    p.nodes = nodes; p.edges = edges;
    const bad = nodes.map((nd, i) => nodeOK(nd) ? -1 : i).filter(i => i >= 0);
    if (bad.length) warn(`molecule.params.nodes[${bad.slice(0, 4).join(', ')}${bad.length > 4 ? ', …' : ''}] ${bad.length > 1 ? 'are' : 'is'} not {"x": 0, "y": 0, "label": "A"} or [x, y, label] — placed at 0, 0`);
    const G = custom(p);
    if (G.bonds.length < edges.length) warn(`molecule.params.edges: ${edges.length - G.bonds.length} of ${edges.length} edge(s) name a node that does not exist or join a node to itself — ${G.bonds.length ? 'dropped' : 'it draws nothing'}; an edge is [a, b] with node indexes from 0 (or labels) like [0, 1]`);
  }
  D.register('molecule', {
    role: 'hero', alias: ['network', 'bonds', 'graph.draw', 'nodes'], aliasParams: { network: { preset: 'network' }, nodes: { preset: 'network' } },
    defaults: { preset: 'molecule', chain: 8, rings: 2, count: 14, hub: 0, seed: 1, labels: [], nodes: [], edges: [], per: 3, w: 560, h: 320, lw: 3, size: 22, label: '' },
    doc: 'A graph drawn bond by bond on the sixteenths: a molecule (what it is made of), a network (who is connected to whom), or your own nodes and edges.',
    check: checkGraph,
    draw(o, b, t, p, x) {
      if (t < x.t0) return false;
      const G = graphOf(p); if (!G.atoms.length || !G.seq.length) return false;
      const w = clamp(num(p.w, 560), 160, 1400), h = clamp(num(p.h, 320), 120, 900), cap = p.label ? 34 : 0, [px, py] = x.place(w, h + cap);
      const xs = G.atoms.map(a => a.x), ys = G.atoms.map(a => a.y), x0 = Math.min(...xs), y0 = Math.min(...ys), bw = Math.max(1e-3, Math.max(...xs) - x0), bh = Math.max(1e-3, Math.max(...ys) - y0);
      const pad = G.mol ? 26 : 14, sc = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh, G.mol ? 70 : 1e9), ox = px + w / 2 - (x0 + bw / 2) * sc, oy = py + h / 2 - (y0 + bh / 2) * sc;
      const X = a => ox + a.x * sc, Y = a => oy + a.y * sc, col = p.color || x.ink([px, py, w, h + cap]), acc = x.acc(), alpha = (p.alpha ?? 1) * x.fade(t);
      const bls = D.bl(x.t0) / 4, per = Math.max(1, Math.round(num(p.per, 3))), idx = Math.floor((t - x.t0) / bls + 1e-6), shown = Math.min(G.seq.length, (idx + 1) * per), fresh = idx * per;
      const lw = clamp(num(p.lw, 3), .5, 8) * (G.mol ? Math.max(.7, sc / 60) : 1), seen = new Set();
      o.save(); o.lineCap = 'round'; o.lineJoin = 'round'; o.globalAlpha = alpha;
      for (let n = 0; n < shown; n++) {
        const bd = G.bonds[G.seq[n]], a = G.atoms[bd.a], c = G.atoms[bd.c]; seen.add(bd.a); seen.add(bd.c);
        let ax = X(a), ay = Y(a), cx = X(c), cy = Y(c); const Ln = Math.hypot(cx - ax, cy - ay) || 1, ux = (cx - ax) / Ln, uy = (cy - ay) / Ln, trim = G.mol ? sc * .26 : 8;
        if (a.lab || !G.mol) { ax += ux * trim; ay += uy * trim; } if (c.lab || !G.mol) { cx -= ux * trim; cy -= uy * trim; }
        const grow = n >= fresh ? easeOut(clamp((t - (x.t0 + idx * bls)) / (bls * .8) - (n - fresh) / per * .5)) : 1;
        o.strokeStyle = n >= fresh ? acc : col; o.lineWidth = lw; o.beginPath(); o.moveTo(ax, ay); o.lineTo(ax + (cx - ax) * grow, ay + (cy - ay) * grow); o.stroke();
        if (bd.k === 2 && grow > 0) { let nx = -uy, ny = ux; const off = Math.max(4, sc * .15);
          if (bd.rc) { const mx = (a.x + c.x) / 2 - bd.rc[0], my = (a.y + c.y) / 2 - bd.rc[1]; if (nx * mx + ny * my > 0) { nx = -nx; ny = -ny; } }
          const sh = bd.rc ? .16 : 0, sx0 = ax + (cx - ax) * sh, sy0 = ay + (cy - ay) * sh, sx1 = ax + (cx - ax) * (1 - sh), sy1 = ay + (cy - ay) * (1 - sh);
          o.beginPath(); o.moveTo(sx0 + nx * off, sy0 + ny * off); o.lineTo(sx0 + (sx1 - sx0) * grow + nx * off, sy0 + (sy1 - sy0) * grow + ny * off); o.stroke(); }
      }
      const pk = D.pulse(t, 'kick', { tau: .15 });
      if (G.mol) { D.font(o, clamp(sc * .38, 13, num(p.size, 22) * 1.4), TY().grot, 700); o.textAlign = 'center'; o.textBaseline = 'middle'; o.fillStyle = col;
        G.atoms.forEach((a, i) => { if (a.lab && seen.has(i)) o.fillText(a.lab, X(a), Y(a)); }); }
      else G.atoms.forEach((a, i) => { if (!seen.has(i) && !(i === G.hub && shown > 0)) return; const hub = i === G.hub, r = hub ? 9 + 3 * pk : 5;
        o.fillStyle = hub ? acc : col; o.beginPath(); o.arc(X(a), Y(a), r, 0, TAU); o.fill();
        if (a.lab) { D.font(o, clamp(num(p.size, 22) * .6, 11, 24), TY().mono, 500); o.textAlign = 'left'; o.textBaseline = 'middle'; D.tracked(o, String(a.lab).toUpperCase(), X(a) + r + 6, Y(a), .08); } });
      if (p.label) { D.font(o, 13, TY().mono, 500); o.fillStyle = col; o.textAlign = 'left'; o.textBaseline = 'top';
        D.tracked(o, String(p.label).toUpperCase(), Math.max(px, ox + x0 * sc), Math.min(py + h + 10, oy + (y0 + bh) * sc + 22), .1); }
      o.restore();
    },
    example: { kind: 'molecule', anchor: { slot: 'top-right' }, key: 'B', params: { preset: 'molecule', chain: 8, rings: 2, label: 'STRUCTURE · ILLUSTRATIVE' } },
  });

  // ============================================================================================= powers of ten ===
  // the frame pulls out by `factor` on every `beats` (each level lands ON its beat): the footage shrinks into a tile at the
  // zoom point and a plan of the world around it fills the frame — roads that thin as they shrink (never closer than 14 px),
  // blocks at the scale that reads, every level's frame drawn and labelled; a scale bar reads the level; the point stays marked
  // the plan: per level an irregular street grid (streets jittered, every fourth a main road), blocks between them (some
  // left empty: parks), and one avenue at an angle — the same pattern ×factor at each level, drawn only while its streets are
  // 16 px … 2.5 frames apart on screen, so the grid thins as it shrinks (the source's thin())
  function plan(o, P0, s, fac, col, seed, nL) {
    const cell = Math.min(W, H) / 3.2, big = 2.5 * Math.max(W, H);
    for (let lv = -1; lv <= nL; lv++) {
      const sp = cell * Math.pow(fac, lv) * s; if (sp < 16 || sp > big) continue;
      const al = clamp((sp - 16) / 50) * clamp((big - sp) / (big * .6)), sd = seed * 13 + lv * 7;
      const jx = i => (hash2(i, sd) - .5) * .5, jy = j => (hash2(sd, j) - .5) * .5;
      const i0 = Math.floor(-P0[0] / sp) - 1, i1 = Math.ceil((W - P0[0]) / sp) + 1, j0 = Math.floor(-P0[1] / sp) - 1, j1 = Math.ceil((H - P0[1]) / sp) + 1;
      const X = i => P0[0] + (i + .5 + jx(i)) * sp, Y = j => P0[1] + (j + .5 + jy(j)) * sp, major = k => ((k % 4) + 4) % 4 === 0;
      o.fillStyle = col;
      const bw = clamp((sp - 28) / 40) * clamp((260 - sp) / 120);           // blocks only at the scale where they read as blocks
      if (bw > 0) for (let i = i0; i < i1; i++) for (let j = j0; j < j1; j++) { const hv = hash2(i * 3.7 + sd, j * 5.3 - sd); if (hv < .22) continue;
        const ins = 2 + sp * .07, x0 = X(i) + ins, y0 = Y(j) + ins, w = X(i + 1) - X(i) - 2 * ins, h = Y(j + 1) - Y(j) - 2 * ins; if (w <= 1 || h <= 1) continue;
        o.globalAlpha = al * bw * (.04 + .07 * hv); o.fillRect(x0, y0, w, h); }
      o.strokeStyle = col;
      for (let i = i0; i <= i1; i++) { const m = major(i); o.globalAlpha = al * (m ? .36 : .16); o.lineWidth = m ? 2 : 1; o.beginPath(); o.moveTo(X(i), 0); o.lineTo(X(i), H); o.stroke(); }
      for (let j = j0; j <= j1; j++) { const m = major(j); o.globalAlpha = al * (m ? .36 : .16); o.lineWidth = m ? 2 : 1; o.beginPath(); o.moveTo(0, Y(j)); o.lineTo(W, Y(j)); o.stroke(); }
      const ang = hash2(sd, 99) * Math.PI, ax = P0[0] + (hash2(99, sd) - .5) * sp * 2, ay = P0[1] + (hash2(sd, 98) - .5) * sp * 2, L2 = 2 * Math.max(W, H);
      o.globalAlpha = al * .34; o.lineWidth = 2.5; o.beginPath(); o.moveTo(ax - Math.cos(ang) * L2, ay - Math.sin(ang) * L2); o.lineTo(ax + Math.cos(ang) * L2, ay + Math.sin(ang) * L2); o.stroke();
    }
    o.globalAlpha = 1;
  }
  const LEVELS = ['10 M', '100 M', '1 KM', '10 KM', '100 KM'];
  const levelsOf = p => { const L = rowsOf(p.levels).map(v => String(v).trim()).filter(Boolean).slice(0, 8); return L.length ? L : LEVELS; };
  // the zoom at t (a pure function of the instance's window): zE levels out (eased per level), s the footage's scale
  function zoomOf(p, inst, t) {
    const L = levelsOf(p), nL = Math.max(1, L.length), fac = clamp(num(p.factor, 10), 2, 20), sh = inst.sh || {};
    // beats per level: given, else the levels spread over the device's window with its last beat held
    const per = p.beats != null && isFinite(N_(p.beats)) ? Math.max(.25, N_(p.beats)) : Math.max(.5, (D.bs(Math.min(inst.t1, sh.t1 ?? inst.t1), inst.t0) - 1) / Math.max(1, nL - 1));
    const z = clamp(D.bs(t, inst.t0) / per, 0, nL - 1), k = Math.floor(z), zE = k + easeInOut(z - k);
    return { L, nL, fac, zE, s: Math.pow(fac, -zE) };
  }
  function checkPowers(p, warn) {
    const L = p.levels;
    if (L !== LEVELS && (L == null || (typeof L === 'string' && !L.trim()) || (Array.isArray(L) && !L.some(v => v != null && String(v).trim() !== '')))) {
      warn(`powers.params.levels is empty — drew the default levels ${J(LEVELS)}; write one label per level like ["10 M", "100 M", "1 KM"]`); p.levels = LEVELS; }
    else if (L != null && typeof L !== 'string' && !Array.isArray(L)) { warn(`powers.params.levels should be a list of labels like ["10 M", "100 M", "1 KM"] — got ${J(L)}; drew the default levels`); p.levels = LEVELS; }
    if (p.point != null) {
      const s = typeof p.point === 'string' ? p.point.toLowerCase().trim() : null, j = jsonList(p.point);
      if (s && /^(center|centre|middle|mid)$/.test(s)) p.point = [.5, .5];             // the words a weaker model writes are fine
      else if (s && /^(lead|subject|auto)$/.test(s)) p.point = null;
      else if (j && uvPair(j)) p.point = uvPair(j);
      else if (!uvPair(p.point)) { warn(`powers.params.point should be [u, v] in image space like [.5, .4] (or "center", or "lead") — got ${J(p.point)}; zoomed out from the lead instead`); p.point = null; }
    }
    if (p.ground != null && !/^(night|paper)$/i.test(String(p.ground).trim())) { warn(`powers.params.ground ${J(p.ground)} is not night · paper — drew a night ground`); p.ground = 'night'; }
    else if (p.ground != null) p.ground = String(p.ground).toLowerCase().trim();
  }
  D.register('powers', {
    role: 'hero', alias: ['powers.of.ten', 'zoom10', 'scale.zoom', 'map.zoom', 'zoom.out'],
    defaults: { levels: ['10 M', '100 M', '1 KM', '10 KM', '100 KM'], beats: null, factor: 10, point: null, ground: 'night', label: '', seed: 3 },
    doc: 'Powers of ten: the frame pulls out ×10 on every beat into a plan of the world around it, each level framed and labelled — scale, distance, how small this is.',
    check: checkPowers,
    // the map replaces the footage from the first pull-out until the device's end (then it fades back to the footage):
    // the default renderer holds the CV marks, micro devices and treatment marks drawn on the footage while it does
    covers: (inst, t) => t >= inst.t0 && t < inst.t1 && zoomOf(inst.p, inst, t).s < .999,
    draw(o, b, t, p, x) {
      if (t < x.t0) return false;
      const { L, nL, fac, zE, s } = zoomOf(p, x, t), Mg = MG();
      const at = uvPair(p.point), map = mapOf(x), lead = x.lead, P0 = at ? map(at[0], at[1]) : lead ? [lead[0] + lead[2] / 2, lead[1] + lead[3] * .4] : [W / 2, H / 2];
      P0[0] = clamp(P0[0], Mg.l, W - Mg.r); P0[1] = clamp(P0[1], Mg.t, H - Mg.b);
      const light = p.ground === 'paper', bg = light ? C.paper : C.night, col = p.color || (light ? C.ink : C.light), acc = x.acc(), a = (p.alpha ?? 1) * x.fade(t);
      o.save(); o.globalAlpha = a;
      if (s < .999) {
        // the map REPLACES the footage: it is painted on the base only, like footage — so the print look's screen and grain
        // reach it, and the lyric's adaptive ink reads the map, not the hidden footage. (The marks drawn on the footage wait
        // while it is up: DEV.covers; chapter code calling this device by hand draws its marks after it, or skips them.)
        const tw = Math.max(W * s, 44), th = tw * H / W, tx = P0[0] - (P0[0] / W) * tw, ty = P0[1] - (P0[1] / H) * th;
        const g = b || o, snap = b ? D.scratch(W, H) : null; if (snap) snap.getContext('2d').drawImage(b.canvas, 0, 0);
        g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = a; g.globalCompositeOperation = 'source-over';
        g.fillStyle = bg; g.fillRect(0, 0, W, H);
        plan(g, P0, s, fac, col, num(p.seed, 3), nL); g.globalAlpha = a;
        const vg = g.createRadialGradient(P0[0], P0[1], Math.min(W, H) * .2, P0[0], P0[1], Math.max(W, H) * .85);   // the plan falls away from the point
        vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, light ? 'rgba(238,237,232,.75)' : 'rgba(15,18,22,.75)'); g.fillStyle = vg; g.fillRect(0, 0, W, H);
        // the footage itself: the first frame, shrinking into the plan (never smaller than a readable thumbnail)
        if (snap) { g.imageSmoothingEnabled = true; g.drawImage(snap, tx, ty, tw, th); }
        g.restore();
        o.globalAlpha = a; o.strokeStyle = acc; o.lineWidth = 2; o.strokeRect(tx, ty, tw, th);
        // every level's frame (level j = the first frame × factor^j), labelled while it is whole on screen
        D.font(o, 13, TY().mono, 500); o.textBaseline = 'top';
        for (let j = 1; j < nL; j++) { const f = Math.pow(fac, j) * s, fw = W * f; if (fw < 60 || fw > 2.2 * W) continue;
          const fx = P0[0] - P0[0] * f, fy = P0[1] - P0[1] * f, fade = clamp((.95 * W - fw) / (.3 * W)) * clamp((fw - 60) / 60);
          o.globalAlpha = a * fade * .9; o.strokeStyle = col; o.lineWidth = 1.2; o.setLineDash([10, 6]); o.strokeRect(fx, fy, fw, H * f); o.setLineDash([]);
          if (fx >= Mg.l && fy >= Mg.t + 24 && fx + fw <= W - Mg.r && fy + H * f <= H - Mg.b) { o.fillStyle = col; D.tracked(o, L[j].toUpperCase(), fx + 8, fy + 8, .1); } }
        if (tw > 140) { o.globalAlpha = a; o.fillStyle = acc; D.tracked(o, L[0].toUpperCase(), tx + 8, ty + 8, .1); }
        o.globalAlpha = a;
      }
      // the point: a ring and a cross once the footage is a thumbnail
      const tk = clamp((220 - W * s) / 120); if (tk > 0) { o.globalAlpha = a * tk; o.strokeStyle = acc; o.lineWidth = 2; o.beginPath(); o.arc(P0[0], P0[1], 30 + 8 * D.kick(t), 0, TAU); o.stroke();
        D.hair(o, P0[0] - 44, P0[1], P0[0] - 32, P0[1], acc, 1.5); D.hair(o, P0[0] + 32, P0[1], P0[0] + 44, P0[1], acc, 1.5); o.globalAlpha = a; }
      // the scale readout: a bar and the level (and the factor so far), in a free slot off the lyric and the subject
      const [bx, by] = x.place(320, 48), lvl = L[Math.min(nL - 1, Math.round(zE))].toUpperCase(), bink = s < .999 ? col : x.ink([bx, by, 320, 48]);
      o.fillStyle = bink; o.fillRect(bx, by + 38, 160, 3); o.fillRect(bx, by + 30, 2, 11); o.fillRect(bx + 158, by + 30, 2, 11);
      D.font(o, 18, TY().mono, 500); o.textBaseline = 'top'; D.tracked(o, lvl, bx, by + 2, .1);
      D.font(o, 12, TY().mono, 500); o.globalAlpha = a * .75; D.tracked(o, `${p.label ? String(p.label).toUpperCase() + ' · ' : ''}×${Math.round(Math.pow(fac, Math.round(zE))).toLocaleString('en-US')}`, bx + 176, by + 30, .1);
      o.restore();
    },
    example: { kind: 'powers', key: 'B', params: { levels: ['10 M', '100 M', '1 KM', '10 KM'], label: 'FROM HERE' } },
  });
})();
