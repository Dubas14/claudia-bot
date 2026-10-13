'use strict';
// Claudia font A/B — the user's lyric lines on their style frame, two faces at a time.
// The server's schedule shows every pair twice (both orders); this page logs which face was in the FIRST slot
// (left / top) and the layout, and reveals the names only after the pick.
const $ = id => document.getElementById(id);
let queue = [], cur = null, shownAt = 0, undoStack = [], fetching = false, busy = false;
const loaded = {};

async function api(u, body) {
  const r = await fetch(u, body === undefined ? {cache: 'no-store'} :
    {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body), cache: 'no-store'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
function loadFace(f) {
  const k = f.css + ':' + f.weight;
  if (!loaded[k]) {
    const ff = new FontFace(f.css, `url("font/${encodeURIComponent(f.file)}")`, {weight: String(f.weight)});
    loaded[k] = ff.load().then(x => { document.fonts.add(x); return true; }).catch(() => false);
  }
  return loaded[k];
}
function setProgress(p) {
  if (!p) return;
  const rate = p.decisive ? ` · first slot ${Math.round(100 * p.first_slot_wins / p.decisive)}%` : '';
  $('meter').textContent = `${p.answered}/${p.cards} pairs${rate}`;
  $('bar').style.width = Math.min(100, 100 * p.answered / Math.max(1, p.cards)) + '%';
}
async function refill() {
  if (fetching) return; fetching = true;
  try {
    const j = await api('api/fonts/next', {exclude: queue.map(c => c.key).concat(cur ? [cur.key] : [])});
    for (const c of j.cards) if (!queue.some(q => q.key === c.key)) { queue.push(c); loadFace(c.first); loadFace(c.second); }
    setProgress(j.progress);
    if (j.error) { $('msg').textContent = j.error; }
  } catch (e) {}
  fetching = false;
}
async function advance() {
  if (!queue.length) await refill();
  cur = queue.shift() || null;
  if (queue.length < 2) refill();
  if (cur) await Promise.all([loadFace(cur.first), loadFace(cur.second)]);   // never show one face in a fallback font
  render();
}
// side by side ("row") even on a portrait phone (research: the old +0.86 first-slot bias was most likely the TOP
// slot of a stacked phone layout); portrait screens get a "turn sideways" hint for bigger frames instead
function layout() { return 'row'; }
function hint() {
  $('hint').textContent = innerWidth < innerHeight ? 'turn sideways for bigger frames' : 'which reads better?';
}
function render() {
  const P = $('fpair');
  if (!cur) {
    P.style.display = 'none'; $('msg').style.display = 'block';
    $('msg').textContent = $('msg').textContent || 'All pairs done — thank you. Tell the bot you finished; it ranks the fonts with `slop taste fonts rank`.';
    return;
  }
  P.style.display = 'flex'; $('msg').style.display = 'none';
  P.className = layout() === 'stack' ? 'stack' : ''; hint();
  [['f1', cur.first], ['f2', cur.second]].forEach(([id, f]) => {
    const fig = $(id); fig.className = '';
    const fr = fig.querySelector('.frame'); fr.style.backgroundImage = 'url("frame.jpg")';
    const ly = fig.querySelector('.ly');
    ly.textContent = cur.line; ly.style.fontFamily = `"${f.css}", sans-serif`; ly.style.fontWeight = f.weight; ly.style.color = cur.ink;
    fig.querySelector('.lab').textContent = f.family;
  });
  shownAt = performance.now();
}
async function pick(w) {
  if (!cur || busy) return; busy = true;
  const c = cur, dwell = Math.round(performance.now() - shownAt), lay = layout();
  if (w === 'first' || w === 'second') { $(w === 'first' ? 'f1' : 'f2').className = 'win'; $(w === 'first' ? 'f2' : 'f1').className = 'lose'; }
  if (w !== 'skip') $('fpair').classList.add('reveal');
  const r = api('api/fonts/pick', {card: c.card, winner: w, layout: lay, dwell_ms: dwell});
  setTimeout(async () => { $('fpair').classList.remove('reveal'); await advance(); busy = false; }, w === 'skip' ? 80 : 650);
  try { const j = await r; undoStack.push({eid: j.undo.eid, card: c}); setProgress(j.progress); } catch (e) {}
}
async function undo() {
  if (busy || !undoStack.length) return;
  const u = undoStack.pop();
  try { const j = await api('api/fonts/undo', {eid: u.eid}); setProgress(j.progress); } catch (e) {}
  if (cur) queue.unshift(cur);
  cur = u.card; $('msg').textContent = ''; render();
}
$('f1').onclick = () => pick('first'); $('f2').onclick = () => pick('second');
$('tie').onclick = () => pick('tie'); $('skip').onclick = () => pick('skip'); $('undo').onclick = undo;
addEventListener('keydown', e => {
  if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') pick('first');
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') pick('second');
  if (e.key === 'x') pick('tie'); if (e.key === 's') pick('skip'); if (e.key === 'z') undo();
});
addEventListener('resize', () => { hint(); if (cur) $('fpair').className = layout() === 'stack' ? 'stack' : ''; });
advance();
