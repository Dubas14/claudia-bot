// devices/ui.js — the interfaces a line can be about: the pill chip (a streaming app's AI label), the chat input that
// types and sends, a chat thread whose bubbles pop on the beat, and a scripted agent terminal typed on the beat.
// Ports: the second video's UI.chip / UI.chatbar, the engine's GFX.bubble and GFX.terminal. Intentional changes: no
// product strings in the defaults (the terminal's title/cwd/model, the chat placeholder and text are params); terminal
// lines may be timed by a time spec (`at`) as well as by beats after the start (`b`).
// Kit aliases (when nothing else defines them): UI.rr · UI.chip(o, x, y, text, t, t0, opts) · UI.chatbar(o, x, y, w, text,
// t, tType, tSend, opts) — the second video's signatures, drawn synchronously by these devices.
'use strict';
(() => {
  const D = window.DEV; if (!D || D.REG['ui.chip']) return;
  const C = D.C, TY = D.TY;
  const spark = (o, x, y, r, t, opts) => D.spark ? D.spark(o, x, y, r, t, opts) : (o.beginPath(), o.arc(x, y, r * .5, 0, TAU), o.fill());

  // ---- ui.chip: a pill that pops in over a 16th; `full` = the longer text that types in from `full_at` (a time spec)
  D.register('ui.chip', {
    role: 'cv', alias: ['chip', 'badge', 'pill'],
    defaults: { text: 'LABEL', full: null, full_at: null, size: 15, cps: 2, icon: true },
    doc: 'A UI pill label (a platform\'s AI badge, a status chip): the interface\'s own words about what we see.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const e = easeOut(seg(t, x.t0, x.t0 + D.bl(x.t0) / 4)), s = p.size;
      D.font(o, s, TY().mono, 500); o.letterSpacing = `${s * .1}px`;
      let txt = String(p.text); const tFull = p.full_at != null ? D.time(p.full_at, x.sh, x.t0 + D.bl(x.t0)) : null;
      if (p.full && tFull != null && t >= tFull) { const n = Math.floor((t - tFull) / (D.bl(tFull) / 4) * p.cps); txt = String(p.full).slice(0, Math.min(p.full.length, txt.length + n)); }
      const tw = o.measureText(txt).width, pad = s * .9, h = s * 2.2, wFull = tw + pad * 2 + (p.icon ? s * 1.6 : 0), w = wFull * lerp(.6, 1, e);
      const [px, py] = x.place(Math.max(wFull, o.measureText(String(p.full || p.text)).width + pad * 2 + s * 1.6), h);
      o.globalAlpha = e * (p.alpha ?? 1); o.fillStyle = p.bg || 'rgba(11,12,14,.78)'; D.rr(o, px, py, w, h, h / 2); o.fill();
      o.strokeStyle = p.line || C.line; o.lineWidth = 1; o.stroke();
      let tx = px + pad; if (p.icon) { o.fillStyle = x.acc(); spark(o, tx + s * .45, py + h / 2, s * .55, t, { color: o.fillStyle, bloom: 0, spin: .05 }); tx += s * 1.6; }
      o.save(); o.beginPath(); o.rect(px, py, w - pad * .5, h); o.clip(); o.fillStyle = p.color || C.light; o.textBaseline = 'middle'; o.fillText(txt, tx, py + h / 2 + 1); o.restore();
      o.letterSpacing = '0px';
    },
    example: { kind: 'ui.chip', anchor: { xy: [1080, 118] }, key: 'W', params: { x: 1080, y: 118, text: 'LIVE', full: 'LIVE · REQUESTS OPEN', full_at: { beats: 2 }, cps: 5 } },
  });

  // ---- ui.chatbar: a chat input that types `text` on 16ths from the start and sends at `send` (a time spec): the message
  // rises as a bubble, the send button pulses
  D.register('ui.chatbar', {
    role: 'hero', alias: ['chatbar', 'chat.input'],
    defaults: { text: 'ask me anything', placeholder: 'Message…', send: null, w: 760, h: 76, size: 30, cps: 2 },
    doc: 'A chat input typing the line\'s question and sending it: the moment someone asks a machine.',
    draw(o, b, t, p, x) {
      if (t < x.t0) return; const h = p.h, s = p.size, B = D.bl(x.t0), tSend = p.send != null ? D.time(p.send, x.sh, x.t1) : x.t0 + B * Math.max(2, p.text.length / (4 * p.cps) + 1);
      const [px, py] = x.place(p.w, h), w = p.w, n = clamp(Math.floor((t - x.t0) / (B / 4) * p.cps), 0, p.text.length), sent = t >= tSend, acc = x.acc();
      o.globalAlpha = p.alpha ?? 1; o.fillStyle = 'rgba(22,24,28,.92)'; D.rr(o, px, py, w, h, h / 2); o.fill(); o.strokeStyle = 'rgba(245,243,238,.18)'; o.lineWidth = 1.2; o.stroke();
      D.font(o, s, TY().grot, 400); o.textBaseline = 'middle';
      if (!sent) { const typed = p.text.slice(0, n); o.fillStyle = n ? '#E7E9EA' : '#71767B'; o.fillText(n ? typed : p.placeholder, px + h * .5, py + h / 2 + 1);
        if (n && frac(t * 3) < .6) { const cw = o.measureText(typed).width; o.fillStyle = acc; o.fillRect(px + h * .5 + cw + 3, py + h / 2 - s * .55, 3, s * 1.1); } }
      else { o.fillStyle = '#71767B'; o.fillText(p.placeholder, px + h * .5, py + h / 2 + 1); }
      const bx = px + w - h * .5, by = py + h / 2, pk = sent ? Math.exp(-(t - tSend) / .12) : 0;
      o.fillStyle = n || sent ? acc : 'rgba(245,243,238,.2)'; o.beginPath(); o.arc(bx, by, h * .34 * (1 + .25 * pk), 0, TAU); o.fill();
      o.strokeStyle = C.dark; o.lineWidth = 3.2; o.lineCap = 'round'; o.beginPath(); o.moveTo(bx, by + h * .15); o.lineTo(bx, by - h * .15); o.moveTo(bx - h * .12, by - h * .03); o.lineTo(bx, by - h * .15); o.lineTo(bx + h * .12, by - h * .03); o.stroke();
      if (sent) { const k = easeOut(seg(t, tSend, tSend + D.bl(tSend))), bw = o.measureText(p.text).width + 44, bh = s * 1.9, bxx = px + w - bw - h * .2, byy = py - 20 - bh - k * 60;
        o.globalAlpha = (p.alpha ?? 1) * clamp(k * 3); o.fillStyle = C.light; D.rr(o, bxx, byy, bw, bh, bh / 2); o.fill(); o.fillStyle = C.dark; o.fillText(p.text, bxx + 22, byy + bh / 2 + 1); }
    },
    example: { kind: 'ui.chatbar', anchor: { slot: 'bottom-right' }, key: 'W', params: { text: 'are you still up?', send: { beats: 3 } } },
  });

  // ---- ui.chat: a thread of bubbles, each popping in (back-out) on its beat; msgs [{who: 'user'|'ai', text, b | at}]
  D.register('ui.chat', {
    role: 'hero', alias: ['chat', 'bubbles', 'ui.bubble', 'bubble'],
    defaults: { msgs: [{ who: 'user', text: 'are you sure?', b: 0 }, { who: 'ai', text: 'absolutely.', b: 1 }], size: 24, w: 560, gap: 16 },
    doc: 'A chat exchange popping in on the beat: what was said to/by a machine, as the interface shows it.',
    draw(o, b, t, p, x) {
      const s = p.size, rows = p.msgs.map(m => ({ m, t0: m.at != null ? D.time(m.at, x.sh, x.t0) : D.tAtBeat(bpOf(x.t0) + (m.b || 0)) })).filter(r => t >= r.t0);
      if (!rows.length) return; const ph = s * 2, [px, py0] = x.place(p.w, (ph + p.gap) * p.msgs.length), TYf = TY(), acc = x.acc();
      let y = py0; D.font(o, s, TYf.grot, 400);
      rows.forEach(({ m, t0 }) => { const e = clamp(D.bs(t, t0) * 2), k = 1 + 2.7 * Math.pow(e - 1, 3) + 1.7 * Math.pow(e - 1, 2);
        const tw = o.measureText(m.text).width, pw = Math.min(p.w, tw + 36), ai = m.who === 'ai', bx = ai ? px + 30 : px + p.w - pw;
        o.save(); o.translate(bx, y); o.scale(k, k); o.globalAlpha = p.alpha ?? 1;
        o.fillStyle = ai ? 'rgba(22,24,28,.92)' : C.light; D.rr(o, 0, 0, pw, ph, ph / 2); o.fill();
        if (ai) { o.fillStyle = acc; spark(o, -18, ph / 2, 9, t, { color: acc, bloom: 0 }); }
        o.fillStyle = ai ? C.light : C.dark; o.textBaseline = 'middle'; o.save(); o.beginPath(); o.rect(0, 0, pw - 12, ph); o.clip(); o.fillText(m.text, 18, ph / 2 + 1); o.restore(); o.restore();
        y += ph + p.gap; });
    },
    example: { kind: 'ui.chat', anchor: { slot: 'top-right' }, key: 'B', params: { msgs: [{ who: 'user', text: 'is this real?', b: 0 }, { who: 'ai', text: 'it is now.', b: 1 }] } },
  });

  // ---- terminal: a scripted agent session typed on the beat. script: [{b (beats after the start) | at (time spec),
  // k: 'prompt'|'think'|'tool'|'out'|'add'|'del'|'ai'|'limit'|'sys', s, verb, speed (chars per 16th ÷ 2)}]
  const SPIN = ['·', '✢', '✳', '✶', '✻', '✽', '✻', '✶', '✳', '✢'];
  D.register('terminal', {
    role: 'hero', alias: ['term', 'console', 'gfx.terminal'],
    defaults: { w: 700, h: 300, size: 20, lh: 32, title: 'agent', cwd: '~/project', model: '', status: '? for shortcuts', theme: 'dark',
      script: [{ b: 0, k: 'prompt', s: 'make it explain itself' }, { b: 1, k: 'think', verb: 'Thinking' }, { b: 2, k: 'tool', s: 'Render(frame.js)' }, { b: 3, k: 'out', s: 'done · 1 file' }] },
    doc: 'A coding-agent / terminal session typed on the beat: the work the line describes, as the machine does it.',
    draw(o, b, t, p, x) {
      const bs = x.bs(t); if (bs < 0) return;
      const [px, py] = x.place(p.w, p.h), w = p.w, h = p.h, pad = 28, lh = p.lh, size = p.size, acc = x.acc(), light = p.theme === 'light';
      const FG = light ? '#121212' : '#f4f2ec', DIM = a => light ? `rgba(18,18,18,${a})` : `rgba(244,242,236,${a})`, PANEL = light ? '#f4f2ec' : '#15181c', LINE = DIM(.22), TYf = TY();
      o.globalAlpha = p.alpha ?? 1; o.fillStyle = PANEL; o.fillRect(px, py, w, h); o.strokeStyle = LINE; o.lineWidth = 1; o.strokeRect(px + .5, py + .5, w - 1, h - 1);
      o.fillStyle = acc; spark(o, px + pad + 9, py + 26, 11, t, { color: acc, bloom: .2 });
      D.font(o, 18, TYf.mono, 500); o.fillStyle = FG; o.textBaseline = 'middle'; const tw = D.tracked(o, p.title, px + pad + 30, py + 26, .02);
      o.globalAlpha = (p.alpha ?? 1) * .55; D.tracked(o, p.cwd, px + pad + 30 + tw + 24, py + 26, .02);
      if (p.model) { o.textAlign = 'right'; o.fillText(p.model, px + w - pad, py + 26); o.textAlign = 'left'; } o.globalAlpha = p.alpha ?? 1;
      D.hair(o, px, py + 52, px + w, py + 52, LINE, 1);
      o.save(); o.beginPath(); o.rect(px, py + 54, w, h - 54 - 44); o.clip();
      const script = p.script.map(l => Object.assign({}, l, { b: l.at != null ? bpOf(D.time(l.at, x.sh, x.t0)) - bpOf(x.t0) : (l.b || 0), s: l.s ?? '' }));
      const vis = script.filter(l => bs >= l.b); let yy = py + 54 + 26;
      const maxLines = Math.max(1, Math.floor((h - 54 - 44 - 20) / lh)), shown = vis.slice(Math.max(0, vis.length - maxLines));
      D.font(o, size, TYf.mono, 400); o.textBaseline = 'middle';
      shown.forEach((l, i) => {
        const typed = l.k === 'think' || l.k === 'sys' ? l.s.length : Math.floor((bs - l.b) * 4 * (l.speed || 2)), s = l.s.slice(0, Math.max(0, typed)), last = i === shown.length - 1;
        let lx = px + pad; const col = { prompt: FG, ai: FG, tool: acc, out: DIM(.7), add: FG, del: DIM(.45), limit: acc, think: acc, sys: DIM(.55) }[l.k] || FG;
        if (l.k === 'prompt') { o.fillStyle = acc; o.fillText('>', lx, yy); lx += 26; }
        if (l.k === 'ai') { o.fillStyle = acc; spark(o, lx + 9, yy, 9, t, { color: acc, bloom: 0, spin: 0 }); lx += 30; }
        if (l.k === 'tool') { o.fillStyle = acc; o.fillText('⏺', lx, yy); lx += 30; }
        if (l.k === 'out') { o.fillStyle = DIM(.45); o.fillText('⎿', lx + 6, yy); lx += 38; }
        if (l.k === 'add' || l.k === 'del') { o.fillStyle = l.k === 'add' ? DIM(.10) : DIM(.04); o.fillRect(px + 1, yy - lh / 2, w - 2, lh); o.fillStyle = col; o.fillText(l.k === 'add' ? '+' : '−', lx, yy); lx += 26; }
        if (l.k === 'think') {
          const g = SPIN[((Math.floor(bpOf(t) * 2) % SPIN.length) + SPIN.length) % SPIN.length], secs = Math.max(0, t - D.tAtBeat(bpOf(x.t0) + l.b)).toFixed(0), verb = (l.verb || l.s || 'Thinking') + '…';
          o.fillStyle = acc; o.fillText(g, lx, yy); lx += 32; o.fillText(verb, lx, yy);
          o.fillStyle = DIM(.5); o.fillText(` (${secs}s · esc to interrupt)`, lx + o.measureText(verb).width, yy);
        } else if (l.k === 'limit') {
          o.fillStyle = acc; o.fillRect(px + pad - 6, yy - lh / 2 + 2, Math.min(w - pad * 2 + 12, o.measureText(l.s).width + 24), lh - 4);
          o.fillStyle = C.dark; o.fillText(s, lx + 6, yy);
        } else { o.fillStyle = col; o.fillText(s + (last && typed < l.s.length && frac(t * 6) < .5 ? '▌' : ''), lx, yy); }
        yy += lh;
      });
      o.restore();
      o.globalAlpha = p.alpha ?? 1; D.hair(o, px, py + h - 44, px + w, py + h - 44, LINE, 1);
      D.font(o, 17, TYf.mono, 400); o.fillStyle = DIM(.55); o.textBaseline = 'middle';
      o.fillText('> ' + (frac(t * 2) < .5 ? '▌' : ''), px + pad, py + h - 22);
      o.textAlign = 'right'; o.fillText(p.status, px + w - pad, py + h - 22); o.textAlign = 'left';
    },
    example: { kind: 'terminal', anchor: { slot: 'top-right' }, key: 'W', params: { title: 'shell', cwd: '~/garden', status: '3 jobs · 02:14',
      script: [{ b: 0, k: 'prompt', s: 'water --all' }, { b: 1, k: 'think', verb: 'Watering' }, { b: 2, k: 'tool', s: 'Run(zones.sh)' }, { b: 3, k: 'out', s: '12/12 zones done' }, { b: 4, k: 'limit', s: 'Tank empty' }] } },
  });

  // the second video's UI kit, as thin synchronous adapters over these devices
  const kitX = (t, opts) => D.frame({ t, accent: opts.accent || C.accent });
  D.alias('UI', {
    rr: D.rr,
    chip: (o, x, y, text, t, t0, opts = {}) => { if (t < t0) return null;
      const X = kitX(t, opts); D.drawSync(o, null, D.adhoc('ui.chip', { x, y, text: String(text), full: opts.full || null, full_at: opts.tFull ?? null, size: opts.size || 15, cps: opts.cps ?? 2,
        icon: opts.icon !== false, bg: opts.bg, line: opts.line, color: opts.color, alpha: opts.alpha }, t0, null), t, X);
      const bx = (X.boxes || [])[0]; return bx ? bx.box : [x, y, 0, 0]; },
    chatbar: (o, x, y, w, text, t, tType, tSend, opts = {}) => {
      D.drawSync(o, null, D.adhoc('ui.chatbar', { x, y, w, text: String(text), send: tSend, h: opts.h || 76, size: opts.size || 30, cps: opts.cps ?? 2, placeholder: opts.placeholder || 'Message…', alpha: opts.alpha }, tType, null), t, kitX(t, opts));
      return [x, y, w, opts.h || 76]; },
  });
})();
