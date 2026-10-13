'use strict';
// Claudia taste feed — one image at a time: like / pass (tap, swipe, or ←/→); ~1 card in 7 is a pair.
// Pairs: the client shuffles which side is shown FIRST and logs it ("shown": ab|ba) with the layout (row|stack),
// so position bias can be measured and corrected (research 11-gap-5 §5.4).
const $ = id => document.getElementById(id);
let queue = [], cur = null, shownAt = 0, undoStack = [], fetching = false, busy = false, M = null, exhausted = false;

async function api(u, body) {
  const r = await fetch(u, body === undefined ? {cache: 'no-store'} :
    {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body), cache: 'no-store'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
function preload(c) { (c.type === 'pair' ? [c.a.img, c.b.img] : [c.img]).forEach(u => { const i = new Image(); i.src = u; }); }

function setMeter(m) {
  if (!m) return; M = m;
  const acc = m.accuracy == null ? (m.taps < 20 ? 'learning' : 'measuring…')
    : `predicts you ${Math.round(m.accuracy * 100)}% ±${Math.round(m.margin * 100)}`;
  $('meter').textContent = `${m.taps}/${m.target} taps · ${m.phase === 'cold start' ? 'warming up' : acc}`;
  $('bar').style.width = Math.min(100, 100 * m.taps / Math.max(1, m.target)) + '%';
  const d = $('done');
  if (m.stop && m.stop.stop) {
    d.textContent = `You can stop here: ${m.stop.why}.` + (m.accuracy != null ? ` It predicts you ${Math.round(m.accuracy * 100)}% (± ${Math.round(m.margin * 100)}).` : '') + ' Keep tapping if you like — it keeps learning.';
    d.style.display = 'block';
  } else d.style.display = 'none';
}

async function refill() {
  if (fetching) return; fetching = true;
  try {
    const ex = queue.map(c => c.key).concat(cur ? [cur.key] : []);
    const j = await api('api/next', {exclude: ex});
    for (const c of j.cards) if (!queue.some(q => q.key === c.key)) { queue.push(c); preload(c); }
    exhausted = !!j.exhausted;
    setMeter(j.meter);
  } catch (e) { /* retried on the next advance */ }
  fetching = false;
}
async function advance() {
  if (!queue.length) await refill();
  cur = queue.shift() || null;
  if (queue.length < 4) refill();
  render();
}

function layoutFor(c) {
  // side by side ("row") is preferred, even on phones; stack only two wide images on a portrait screen
  if (innerWidth >= innerHeight) return 'row';
  const wide = x => (x.ar || 1) > 1.15;
  return (wide(c.a) && wide(c.b)) ? 'stack' : 'row';
}

function render() {
  const s = $('single'), p = $('pair');
  $('msg').style.display = 'none';
  if (!cur) {
    s.style.display = 'none'; p.style.display = 'none';
    $('msg').style.display = 'block';
    $('msg').textContent = exhausted
      ? `You have seen everything in your pool${M ? ` (${M.pool} images)` : ''}. Tell the bot: it can add more images (slop taste pool add), or you can stop here.`
      : 'Nothing new to show yet — new images are still being read. This page retries by itself.';
    setTimeout(() => { if (!cur) advance(); }, exhausted ? 60000 : 15000);
    return;
  }
  if (cur.type === 'single') {
    p.style.display = 'none'; s.style.display = 'flex';
    $('tapbar').style.display = 'flex'; $('pairbar').style.display = 'none';
    const im = $('img'); im.style.transform = ''; im.style.opacity = 1; im.src = cur.img;
  } else {
    if (!cur.shown) cur.shown = Math.random() < 0.5 ? 'ab' : 'ba';   // which side is FIRST (left / top)
    cur.layout = layoutFor(cur);
    const first = cur.shown === 'ab' ? cur.a : cur.b, second = cur.shown === 'ab' ? cur.b : cur.a;
    s.style.display = 'none'; p.style.display = 'flex'; p.className = cur.layout === 'stack' ? 'stack' : '';
    $('tapbar').style.display = 'none'; $('pairbar').style.display = 'flex';
    $('p1').className = ''; $('p2').className = '';
    $('p1').querySelector('img').src = first.img; $('p2').querySelector('img').src = second.img;
  }
  shownAt = performance.now();
}

async function tap(action) {
  if (!cur || cur.type !== 'single' || busy) return; busy = true;
  const c = cur, dwell = Math.round(performance.now() - shownAt);
  const im = $('img'); im.style.transform = `translateX(${action === 'like' ? 60 : -60}px)`; im.style.opacity = 0;
  const r = api('api/tap', {item: c.item, action, dwell_ms: dwell, why: c.why, score: c.score});
  setTimeout(async () => { await advance(); busy = false; }, 120);
  try { const j = await r; undoStack.push({eid: j.undo.eid, card: c}); if (undoStack.length > 20) undoStack.shift(); setMeter(j.meter); } catch (e) {}
}

async function pick(slot) {
  if (!cur || cur.type !== 'pair' || busy) return; busy = true;
  const c = cur, dwell = Math.round(performance.now() - shownAt);
  let winner = slot;
  if (slot === 'first') winner = c.shown === 'ab' ? 'a' : 'b';
  if (slot === 'second') winner = c.shown === 'ab' ? 'b' : 'a';
  if (slot === 'first' || slot === 'second') {
    $(slot === 'first' ? 'p1' : 'p2').className = 'win'; $(slot === 'first' ? 'p2' : 'p1').className = 'lose';
  }
  const r = api('api/pair', {a: c.a.id, b: c.b.id, winner, shown: c.shown, layout: c.layout, dwell_ms: dwell});
  setTimeout(async () => { await advance(); busy = false; }, 160);
  try { const j = await r; undoStack.push({eid: j.undo.eid, card: c}); setMeter(j.meter); } catch (e) {}
}

async function undo() {
  if (busy || !undoStack.length) return;
  const u = undoStack.pop();
  try { const j = await api('api/undo', {eid: u.eid}); setMeter(j.meter); } catch (e) {}
  if (cur) queue.unshift(cur);
  cur = u.card; render();
}

$('like').onclick = () => tap('like'); $('pass').onclick = () => tap('pass');
$('undo').onclick = undo; $('undo2').onclick = undo;
$('p1').onclick = () => pick('first'); $('p2').onclick = () => pick('second');
$('tie').onclick = () => pick('tie'); $('pskip').onclick = () => pick('skip');
$('img').onerror = () => { if (cur && cur.type === 'single') advance(); };

let x0 = null, y0 = null; const S = $('single');
S.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, {passive: true});
S.addEventListener('touchmove', e => { if (x0 == null) return; const dx = e.touches[0].clientX - x0; $('img').style.transform = `translateX(${dx}px) rotate(${dx / 40}deg)`; }, {passive: true});
S.addEventListener('touchend', e => {
  if (x0 == null) return;
  const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0; x0 = null;
  if (Math.abs(dx) > 70 && Math.abs(dx) > Math.abs(dy)) tap(dx > 0 ? 'like' : 'pass'); else $('img').style.transform = '';
});
addEventListener('keydown', e => {
  if ($('panel').style.display === 'block') { if (e.key === 'Escape') $('panel').style.display = 'none'; return; }
  if (cur && cur.type === 'single') { if (e.key === 'ArrowRight') tap('like'); if (e.key === 'ArrowLeft') tap('pass'); }
  else if (cur) {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') pick('first');
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') pick('second');
    if (e.key === 'x') pick('tie'); if (e.key === 's') pick('skip');
  }
  if (e.key === 'z') undo();
});
addEventListener('resize', () => { if (cur && cur.type === 'pair') { cur.layout = layoutFor(cur); $('pair').className = cur.layout === 'stack' ? 'stack' : ''; } });

function el(tag, attrs, kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (k === 'text') n.textContent = v; else n.setAttribute(k, v); }
  for (const k of kids || []) n.appendChild(k);
  return n;
}
function panel(nodes) {
  const P = $('panel'); P.replaceChildren();
  const c = el('button', {class: 'close', text: 'close'}); c.onclick = () => { P.style.display = 'none'; };
  P.appendChild(c); nodes.forEach(n => P.appendChild(n)); P.style.display = 'block';
}
$('tasteBtn').onclick = async () => {
  let m = M; try { m = await api('api/meter'); } catch (e) {}
  m = m || {};
  const acc = m.accuracy == null ? 'It needs about 20 taps before it can test itself.'
    : `Tested on taps it did not learn from, it picks the one you prefer ${Math.round(m.accuracy * 100)}% of the time (± ${Math.round(m.margin * 100)}; 50% = a coin flip). Typical at this many taps: ${Math.round((m.predicted || 0) * 100)}%.`;
  const rep = m.repeats ? `Repeats: ${m.repeats} images were shown to you a second time; you gave the same answer ${Math.round(m.self_agreement * 100)}% of the time — the ceiling for any model of your taps.`
    : 'From tap 60, a few cards you already answered come back once, to measure how consistent taste itself is.';
  const emb = m.embedding && m.embedding.running ? ` Still reading images (${m.embedding.progress || 'starting'}).` : '';
  panel([el('h2', {text: 'taste'}),
    el('p', {text: `${m.likes || 0} likes · ${m.passes || 0} passes · ${m.pairs || 0} pairs. ${acc}`}),
    el('p', {text: `No rules: every image is a vector from a vision model, and your taps teach a small model which directions you like (${m.dims || '—'} dimensions now; more as you tap). The first 40 cards sample every corner of your pool; then most cards are its best guess, about 15% are random so it keeps finding new ground, and about 1 in 7 is a pair.`}),
    el('p', {text: rep}),
    el('p', {text: `${m.pool || 0} images in your pool, ${m.embedded || 0} read by the model.${emb}`})]);
};
$('savedBtn').onclick = async () => {
  let L = []; try { L = await api('api/liked'); } catch (e) {}
  const g = el('div', {class: 'grid'});
  for (const x of L) {
    const a = el('a', {href: x.link || x.img, target: '_blank', rel: 'noopener noreferrer'});
    const im = el('img', {loading: 'lazy', src: x.img, alt: '', title: x.title || ''});
    a.appendChild(im); g.appendChild(a);
  }
  panel([el('h2', {text: `saved · ${L.length}`}), g]);
};
advance();
