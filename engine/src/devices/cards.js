// devices/cards.js — printed and panel graphics: the spec label (a woven garment tag: field:value rows, care symbols, a
// barcode), the instrument sheet (a dark panel of typed readings, or a paper receipt), the rubber stamp, the strike-through
// escalation, the redaction bar, and the titles (the knockout word that shows the footage through its letters; the lockup).
// Ports: the engine's garmentTag/careSymbols/barcode and the first video's lookCard (pop + a row per eighth), its panel()/
// receipt() and stamp moments, the second video's strike() and TITLE.knockout / lockup. Intentional changes: every string is
// a param (the source defaulted to its own serials and title); the stamp and redaction are generalised from chapter code.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG.label) return;
  const C = D.C, TY = D.TY;

  function careSymbols(g, x, y, s, ink, nerf) {
    g.save(); g.strokeStyle = ink; g.lineWidth = 1.3; g.fillStyle = ink;
    const tub = () => { g.beginPath(); g.moveTo(0, 3); g.lineTo(3, s); g.lineTo(s - 3, s); g.lineTo(s, 3); g.stroke(); D.font(g, 8, TY().mono, 500); g.textAlign = 'center'; g.fillText('30', s / 2, s * .45); g.textAlign = 'left'; };
    const tri = () => { g.beginPath(); g.moveTo(s / 2, 2); g.lineTo(s, s); g.lineTo(0, s); g.closePath(); g.stroke(); };
    const iron = () => { g.beginPath(); g.moveTo(2, s); g.lineTo(s, s); g.lineTo(s - 2, 5); g.lineTo(6, 5); g.quadraticCurveTo(2, 8, 2, s); g.stroke(); };
    const circ = () => { g.beginPath(); g.arc(s / 2, s / 2 + 1, s / 2 - 1, 0, TAU); g.stroke(); };
    const sq = () => { g.strokeRect(1, 2, s - 2, s - 2); g.beginPath(); g.arc(s / 2, s / 2 + 1, s / 2 - 4, 0, TAU); g.stroke(); };
    const cross = () => { g.beginPath(); g.moveTo(0, 1); g.lineTo(s, s + 1); g.moveTo(s, 1); g.lineTo(0, s + 1); g.stroke(); };
    [tub, tri, iron, circ, sq].forEach((f, i) => { g.save(); g.translate(x + i * (s + 8), y); f(); if (i === 2 || (nerf && i === 4)) cross(); g.restore(); });
    g.restore();
  }
  function barcode(g, x, y, w, h, seed, ink) {
    g.fillStyle = ink; let xx = x, i = 0; const sd = [...String(seed)].reduce((a, c) => a + c.charCodeAt(0), 0);
    while (xx < x + w) { const bw = 1 + Math.floor(hash(sd + i) * 3); if (i % 2 === 0) g.fillRect(xx, y, Math.min(bw, x + w - xx), h); xx += bw; i++; }
  }
  D.barcode = barcode; D.careSymbols = careSymbols;

  // ---- label: the woven spec label (pop on the start, a row per eighth); rows [[field, value]]
  D.register('label', {
    role: 'hero', alias: ['garment.tag', 'garmentTag', 'tag.card', 'spec.label', 'lookcard', 'card.label'],
    defaults: { title: 'TITLE', kicker: '', badge: '', rows: [['FIELD', 'VALUE']], serial: '', w: 300, rot: 0, swing: 0, care: true, nerf: false, scale: 1 },
    doc: 'A spec label (garment care tag): classifies a person/object as a product with field:value rows. Spec-label language.',
    draw(o, b, t, p, x) {
      const e = x.bs(t); if (e < 0) return;
      const n = p.rows.length, w = p.w, pad = 16, rowH = 20, h = p.h || (pad * 2 + 58 + n * rowH + (p.care || p.serial ? 64 : 10)), sc = p.scale;
      const [px, py] = x.place(w * sc, h * sc), ink = p.ink || C.ink, paper = p.paper || '#f4f2ec';
      const k = easeOut(clamp(e * 2)), reveal = clamp(e / ((n + 1) * .5)), rot = (p.rot || 0) + (p.swing ? p.swing * Math.sin(bpOf(t) * Math.PI / 2) : 0);
      o.translate(px, py); o.scale(sc, sc); o.rotate(rot); o.globalAlpha = k * x.fade(t); o.translate(0, (1 - k) * 30);
      o.fillStyle = paper; o.fillRect(0, 0, w, h); o.fillStyle = 'rgba(0,0,0,.08)'; o.fillRect(0, 0, w, 10);
      o.setLineDash([3, 3]); D.hair(o, 6, 14, w - 6, 14, 'rgba(0,0,0,.35)', 1); o.setLineDash([]);
      o.fillStyle = ink; o.textBaseline = 'top'; D.font(o, 11, TY().mono, 500); if (p.kicker) D.tracked(o, String(p.kicker).toUpperCase(), pad, 24, .08);
      if (p.badge) { const s = String(p.badge).toUpperCase(); D.font(o, 11, TY().mono, 500); const bw = o.measureText(s).width + 14; o.fillStyle = x.acc(); o.fillRect(w - pad - bw, 20, bw, 18); o.fillStyle = paper; D.tracked(o, s, w - pad - bw + 7, 24, .04); o.fillStyle = ink; }
      D.font(o, 30, TY().display, 600); let ts = 30; while (o.measureText(p.title).width > w - 2 * pad && ts > 14) { ts -= 2; D.font(o, ts, TY().display, 600); }
      D.tracked(o, p.title, pad, 42, -.01);
      let yy = 82; D.hair(o, pad, yy, w - pad, yy, ink, 1.2); yy += 8; D.font(o, 12, TY().mono, 400);
      p.rows.forEach(([f, v], i) => { const r = clamp(reveal * (n + 1) - i); if (r <= 0) return; o.globalAlpha = k * r * x.fade(t);
        D.tracked(o, String(f).toUpperCase(), pad, yy + i * rowH, .06); o.textAlign = 'right'; o.fillText(String(v).toUpperCase(), w - pad, yy + i * rowH); o.textAlign = 'left'; });
      o.globalAlpha = k * x.fade(t); yy += n * rowH + 6; D.hair(o, pad, yy, w - pad, yy, ink, 1.2);
      if (p.care) careSymbols(o, pad, yy + 10, 18, ink, p.nerf);
      if (p.serial) { barcode(o, w - pad - 110, yy + 10, 110, 26, p.serial, ink); D.font(o, 10, TY().mono, 400); o.fillStyle = ink; D.tracked(o, String(p.serial), w - pad - 110, yy + 40, .06); }
    },
    example: { kind: 'label', anchor: { slot: 'top-right' }, key: 'W', params: { title: 'NIGHT JACKET', kicker: 'ITEM 04 / 09', badge: 'NEW', serial: 'NJ-04-0001', rows: [['SHELL', 'WAXED COTTON'], ['LINING', 'WOOL'], ['SIZE', 'M']] } },
  });

  // ---- sheet: an instrument panel of readings typed one row per 16th (style 'panel'), or a paper receipt with a total rule
  // (style 'receipt'); rows [[field, value, state?]] (state 'hot' = the accent row; 'strike' = struck), hl = a row index
  D.register('sheet', {
    role: 'hero', alias: ['panel', 'receipt', 'spec.sheet', 'readings'], aliasParams: { receipt: { style: 'receipt' } },
    defaults: { title: 'READINGS', rows: [['FIELD', 'VALUE']], style: 'panel', w: 470, size: 15, per16: 1, total: null },
    doc: 'A spec sheet / instrument panel / receipt: the line\'s numbers as a document (a log, a perception readout, a bill).',
    draw(o, b, t, p, x) {
      const bs = x.bs(t); if (bs < 0) return;
      const rec = p.style === 'receipt', s = p.size, rowH = Math.round(s * 1.75), n = p.rows.length, h = 70 + n * rowH + (p.total ? rowH * 1.6 : 0) + 24, w = p.w;
      const [px, py] = x.place(w, h), shown = Math.floor(bs * 4 * p.per16) + 1, fg = rec ? C.ink : C.light, acc = x.acc(), TYf = TY();
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t) * easeOut(clamp(bs * 4));
      if (rec) { o.fillStyle = '#f4f2ec'; o.beginPath(); o.moveTo(px, py); o.lineTo(px + w, py); o.lineTo(px + w, py + h);
        for (let i = 0, nz = Math.floor(w / 14); i <= nz; i++) o.lineTo(px + w - i * w / nz, py + h - (i % 2 ? 8 : 0)); o.closePath(); o.fill(); }
      else { o.fillStyle = 'rgba(12,14,17,.82)'; o.fillRect(px, py, w, h); o.strokeStyle = 'rgba(245,243,238,.22)'; o.lineWidth = 1; o.strokeRect(px + .5, py + .5, w - 1, h - 1); }
      D.font(o, 13, TYf.mono, 500); o.fillStyle = fg; o.textBaseline = 'top'; D.tracked(o, String(p.title).toUpperCase(), px + 18, py + 18, .1);
      if (rec) { o.setLineDash([4, 4]); D.hair(o, px + 18, py + 46, px + w - 18, py + 46, fg, 1); o.setLineDash([]); } else D.hair(o, px, py + 46, px + w, py + 46, 'rgba(245,243,238,.22)', 1);
      D.font(o, s, TYf.mono, 400);
      p.rows.forEach(([f, v, st], i) => { if (i >= shown) return; const y = py + 60 + i * rowH, hot = st === 'hot' || p.hl === i;
        o.fillStyle = hot ? acc : fg; D.tracked(o, String(f).toUpperCase(), px + 18, y, .04);
        o.textAlign = 'right'; o.fillText(String(v ?? '').toUpperCase(), px + w - 18, y); o.textAlign = 'left';
        if (st === 'strike') { o.fillStyle = acc; o.fillRect(px + 14, y + s * .45, w - 28, 2); } });
      if (p.total && shown > n) { const y = py + 60 + n * rowH + 8; D.hair(o, px + 18, y, px + w - 18, y, fg, 1.2); D.font(o, s * 1.25, TYf.mono, 500);
        o.fillStyle = fg; D.tracked(o, String(p.total[0]).toUpperCase(), px + 18, y + 10, .04); o.textAlign = 'right'; o.fillStyle = acc; o.fillText(String(p.total[1]).toUpperCase(), px + w - 18, y + 10); o.textAlign = 'left'; }
    },
    example: { kind: 'sheet', anchor: { slot: 'top-right' }, key: 'B', params: { title: 'MONTHLY', style: 'receipt', rows: [['RENT', '$1,200'], ['COFFEE', '$310', 'hot'], ['BUS', '$64']], total: ['COFFEE / RENT', '25.8%'] } },
  });

  // ---- stamp: a rubber stamp slammed on (scale 1.5 → 1 over ~.05 s, accent on its first frame), rotated, double rule
  D.register('stamp', {
    role: 'hero', alias: ['rubber.stamp', 'slap'], typeSize: p => +p.size,
    defaults: { text: 'APPROVED', sub: '', size: 74, rot: -.14 },
    doc: 'A rubber stamp slammed on the beat: a verdict (SECURED, RETIRED, ALARMED) issued on the word.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const age = t - x.t0, sc = 1 + .5 * Math.exp(-age / .05), first = age < 1 / FPS + 1e-4, TYf = TY();
      D.font(o, p.size, TYf.display, 600); const tw = o.measureText(String(p.text).toUpperCase()).width, w = tw + p.size * .6, h = p.size * (p.sub ? 1.55 : 1.2);
      const [px, py] = x.place(w, h), col = first ? x.acc() : (p.color || x.ink([px, py, w, h]));
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); o.translate(px + w / 2, py + h / 2); o.rotate(p.rot); o.scale(sc, sc); o.translate(-w / 2, -h / 2);
      o.strokeStyle = col; o.lineWidth = 4; o.strokeRect(0, 0, w, h); o.lineWidth = 1.5; o.strokeRect(7, 7, w - 14, h - 14);
      o.fillStyle = col; o.textBaseline = 'alphabetic'; D.font(o, p.size, TYf.display, 600); o.fillText(String(p.text).toUpperCase(), p.size * .3, p.size * 1.0);
      if (p.sub) { D.font(o, 13, TYf.mono, 500); o.textBaseline = 'top'; D.tracked(o, String(p.sub).toUpperCase(), p.size * .3, p.size * 1.12, .1); }
    },
    example: { kind: 'stamp', anchor: { slot: 'center' }, key: 'W', params: { text: 'FILED', sub: 'FORM 7 · CHECKED' } },
  });

  // ---- strike: the promise escalates — words in a row, the struck ones get an accent bar over half a beat; `next` (a row
  // of words) appears under it at `next_at` (a time spec), typed letter by letter. words: [[text, struck?]]
  D.register('strike', {
    role: 'hero', alias: ['strikethrough', 'erratum', 'correction'], typeSize: p => +p.size,
    defaults: { words: [['ALWAYS', true], ['SOMETIMES', false]], next: null, next_at: null, size: 96 },
    doc: 'A correction / escalation: the old claim is struck out and the new one is written under it.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const s = p.size, TYf = TY(); D.font(o, s, TYf.sign, 700); o.letterSpacing = `${s * .02}px`;
      const wOf = ws => ws.reduce((a, [w]) => a + o.measureText(String(w).toUpperCase()).width + s * .28, 0);
      const tw = Math.max(wOf(p.words), p.next ? wOf(p.next) : 0), [px, py] = x.place(tw, s * 2.3), ink = p.color || x.ink([px, py, tw, s * 2.3]), acc = x.acc();
      const k = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2)); let xx = px; const y = py + s; o.textBaseline = 'alphabetic';
      p.words.forEach(([w0, st]) => { const w = String(w0).toUpperCase(), ww = o.measureText(w).width;
        o.globalAlpha = (st ? lerp(.9, .55, k) : .9) * x.fade(t); o.fillStyle = ink; o.fillText(w, xx, y);
        if (st && k > 0) { o.globalAlpha = x.fade(t); o.fillStyle = acc; o.fillRect(xx - 4, y - s * .4, (ww + 8) * k, Math.max(4, s * .11)); }
        xx += ww + s * .28; });
      if (p.next) { const tn = p.next_at != null ? D.time(p.next_at, x.sh, x.t0 + D.bl(x.t0)) : x.t0 + D.bl(x.t0); if (t >= tn) {
        const all = p.next.map(([w]) => String(w).toUpperCase()).join(' '), n = Math.ceil(all.length * easeOut(seg(t, tn, tn + D.bl(tn) / 2)));
        o.globalAlpha = x.fade(t); o.fillStyle = ink; o.fillText(all.slice(0, n), px, y + s * 1.12); } }
      o.letterSpacing = '0px';
    },
    example: { kind: 'strike', anchor: { slot: 'top-left' }, key: 'W', params: { words: [["I'LL", false], ['CALL', true]], next: [["I'LL", false], ['WRITE', false]], next_at: { beats: 1 }, size: 64 } },
  });

  // ---- redact: lines of text with a black bar sweeping across the marked words (a quarter beat each, in order from the
  // start); `lift` (a time spec) slides the bars off again. rows: [[text, redacted?], …] one per line
  D.register('redact', {
    role: 'hero', alias: ['redaction', 'blackout'],
    defaults: { rows: [['THE SOURCE IS', false], ['CLASSIFIED', true]], size: 28, lift: null, w: 620 },
    doc: 'A redaction: words blacked out on the beat (what is hidden, censored or not said).',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const s = p.size, lh = s * 1.4, TYf = TY(), [px, py] = x.place(p.w, lh * p.rows.length);
      const ink = p.color || x.ink([px, py, p.w, lh * p.rows.length]), B = D.bl(x.t0), tl = p.lift != null ? D.time(p.lift, x.sh, null) : null;
      D.font(o, s, TYf.mono, 500); o.textBaseline = 'top'; o.globalAlpha = x.fade(t); let k = 0;
      p.rows.forEach(([txt, red], i) => { const y = py + i * lh, s2 = String(txt).toUpperCase(), w = o.measureText(s2).width + s2.length * s * .04;
        o.fillStyle = ink; D.tracked(o, s2, px, y, .04);
        if (red) { const e = easeOut(seg(t, x.t0 + k * B / 4, x.t0 + (k + 1) * B / 4)) * (tl != null ? 1 - easeOut(seg(t, tl, tl + B / 4)) : 1); k++;
          o.fillStyle = ink === C.dark ? C.dark : '#050505'; o.fillRect(px - 4, y - 3, (w + 8) * e, s * 1.15);
          if (e > 0 && e < 1) { o.fillStyle = x.acc(); o.fillRect(px - 4 + (w + 8) * e - 3, y - 3, 3, s * 1.15); } } });
    },
    example: { kind: 'redact', anchor: { slot: 'top-left' }, key: 'W', params: { rows: [['THE PLAN IS', false], ['NOT FOR YOU', true]], lift: { beats: 4 } } },
  });

  // ---- title.knockout: the frame black except the letters of the word, so the footage shows only through them; the sub
  // (a lyric token: `token` [line, i] is drawn on its time and marked for the lyric gate) lands under it in the accent
  D.register('title.knockout', {
    role: 'hero', alias: ['knockout', 'title'], wordParam: false,          // params.word is the knocked-out word, not a time
    defaults: { word: null, sub: null, token: null, fill: '#050505', w: null, subSize: 64 },
    doc: 'The title as a knockout: the word cut out of black so the footage shows through it. When the device IS the line.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const PJ = window.PROJECT || {}, word = String(p.word || PJ.title || 'TITLE').toUpperCase(), tw = p.w || W - 120, TYf = TY();
      D.font(o, 100, TYf.sign, 900); o.letterSpacing = '0px'; const size = 100 * tw / Math.max(1, o.measureText(word).width);
      const px = p.x ?? (W - tw) / 2, py = p.y ?? (H / 2 + size * .36), a = (p.alpha ?? 1) * x.fade(t);
      o.save(); o.globalAlpha = a; o.fillStyle = p.fill; o.fillRect(0, 0, W, H);
      o.globalCompositeOperation = 'destination-out'; D.font(o, size, TYf.sign, 900); o.textBaseline = 'alphabetic'; o.fillText(word, px, py); o.restore();
      const tk = p.token != null ? D.token(p.token, x.sh) : null, tSub = tk ? tk.t0 : x.t0;
      if ((tk || p.sub) && t >= tSub) { if (tk && D.has.KIN()) KIN.mark(tk);
        const ss = p.subSize, st = String(p.sub || (tk ? tk.txt.replace(/\.+$/, '') : '')).toUpperCase(), e = easeOut(clamp((t - tSub) / (D.bl(tSub) / 2)));
        D.font(o, ss, TYf.grot, 700); o.letterSpacing = `${ss * .06}px`; o.fillStyle = x.acc(); o.textAlign = 'center'; o.textBaseline = 'top';
        o.globalAlpha = e * a; o.fillText(`(${st})`, W / 2, py + size * .12 + (1 - e) * 20); o.letterSpacing = '0px'; o.textAlign = 'left'; }
    },
    example: { kind: 'title.knockout', key: 'W', params: { word: 'Claudia', sub: 'a lyric video' } },
  });

  // ---- title.card: the lockup — a big condensed title over a sub line in the accent, wiped on left to right over half a beat
  D.register('title.card', {
    role: 'hero', alias: ['lockup', 'title.lockup', 'card.title'],
    defaults: { title: null, sub: '', w: 900, kicker: '' },
    doc: 'A title lockup (title + sub): opens or closes a section, names the chapter.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const PJ = window.PROJECT || {}, title = String(p.title || PJ.title || 'TITLE').toUpperCase(), TYf = TY();
      D.font(o, 100, TYf.sign, 900); const size = 100 * p.w / Math.max(1, o.measureText(title).width), h = size * 1.2 + (p.sub ? size * .3 : 0);
      const [px, py] = x.place(p.w, h), col = p.color || x.ink([px, py, p.w, h]), e = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 2));
      o.globalAlpha = (p.alpha ?? 1) * x.fade(t); o.save(); o.beginPath(); o.rect(px - 10, py - 10, (p.w + 20) * e, h + 40); o.clip();
      if (p.kicker) { D.font(o, 13, TYf.mono, 500); o.fillStyle = col; o.textBaseline = 'bottom'; D.tracked(o, String(p.kicker).toUpperCase(), px, py - 6, .14); }
      o.fillStyle = col; o.textBaseline = 'top'; D.font(o, size, TYf.sign, 900); o.fillText(title, px, py);
      if (p.sub) { D.font(o, size * .2, TYf.grot, 700); o.letterSpacing = `${size * .02}px`; o.fillStyle = x.acc(); o.fillText(String(p.sub).toUpperCase(), px + 2, py + size * .86); o.letterSpacing = '0px'; }
      o.restore();
    },
    example: { kind: 'title.card', anchor: { slot: 'top-left' }, key: 'B', params: { title: 'CHAPTER II', sub: 'the instances', kicker: 'II · 00:10' } },
  });
})();
