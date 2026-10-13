// seq.js — RGBA image sequences over the footage (3D renders: type helixes, placards, chrome type, membranes …).
// Adds MEDIA.drawSeq and MEDIA.seqInfo (no cost until called).
// Contract: <project>/engine/assets/fx/<name>/f00001.png … (RGBA) + optional depth/ + manifest.json
// {fps, frames, w, h, anchor, notes}; an index window.FXSEQ (assets fx.js) {name: {fps, frames, dir, anchor}} is read
// first — without it the manifest is read directly (file:// XHR, which the renderer allows).
//
//   await MEDIA.drawSeq(ctx, name, lt, o) → {box: [x, y, w, h], frame, info} | null (sequence or frame missing)
//     lt: seconds into the sequence (frame = floor(lt × fps)); o.loop (wrap) or o.hold (default: clamp to the ends;
//     hold: false → nothing outside); o.speed
//     placement: o.at = [x, y] puts the manifest's anchor ([u, v] of the image, default centre) there at o.scale
//     (default 1 = the rendered size); else a rect {x, y, w, h} (default the frame) with o.fit 'contain' (default when a
//     rect is given) | 'cover' | 'fill'; o.opacity, o.rot (radians about the anchor), o.composite (canvas op)
//   Put it behind the subject with OCC: OCC.behind(o, m, g => MEDIA.drawSeq(g, 'name', lt, {...}))
// Always keep a code fallback for a missing sequence (drawSeq returns null).
// Port notes: an anchor that is not an [u, v] pair (e.g. a descriptive object) falls back to the centre. A sequence with no
// index entry and no manifest is optional (null, the caller's fallback draws); a FRAME of a known sequence that fails to
// load is reported in ENGINE.missingMedia (loadImage).
'use strict';
(() => {
  if (typeof MEDIA === 'undefined') return;
  const meta = {};
  function xhrJSON(url) {
    return new Promise(res => { try { const x = new XMLHttpRequest(); x.open('GET', url);
      x.onload = () => { try { res(JSON.parse(x.responseText)); } catch (e) { res(null); } }; x.onerror = () => res(null); x.send(); } catch (e) { res(null); } });
  }
  async function seqInfo(name) {
    const I = window.FXSEQ || {}; if (I[name]) return I[name];
    if (meta[name] === undefined) meta[name] = xhrJSON(`assets/fx/${name}/manifest.json`).then(m => m && m.frames ? Object.assign({ fps: 24, dir: `assets/fx/${name}` }, m) : null);
    return meta[name];
  }
  async function drawSeq(ctx, name, lt, o = {}) {
    const S = await seqInfo(name); if (!S || !S.frames) return null;     // optional by contract: the caller has a code fallback
    let i = Math.floor(lt * (o.speed || 1) * (S.fps || 24) + 1e-6);
    if (o.loop) i = ((i % S.frames) + S.frames) % S.frames;
    else if (o.hold === false && (i < 0 || i >= S.frames)) return null;
    else i = clamp(i, 0, S.frames - 1);
    let f = null; try { f = await loadImage(`fx:${name}#${i + 1}`, `${S.dir}/f${String(i + 1).padStart(5, '0')}.png`); } catch (e) { return null; }
    const iw = f.naturalWidth, ih = f.naturalHeight, an = Array.isArray(S.anchor) && S.anchor.length === 2 ? S.anchor : [.5, .5];
    let x, y, w, h;
    if (o.at) { const s = o.scale ?? 1; w = iw * s; h = ih * s; x = o.at[0] - an[0] * w; y = o.at[1] - an[1] * h; }
    else {
      const R = [o.x ?? 0, o.y ?? 0, o.w ?? W, o.h ?? H], fit = o.fit || (o.w != null ? 'contain' : 'cover');
      if (fit === 'fill') [x, y, w, h] = R;
      else { const s = (fit === 'cover' ? Math.max : Math.min)(R[2] / iw, R[3] / ih); w = iw * s; h = ih * s; x = R[0] + (R[2] - w) / 2; y = R[1] + (R[3] - h) / 2; }
    }
    ctx.save(); ctx.globalAlpha = o.opacity ?? 1; if (o.composite) ctx.globalCompositeOperation = o.composite;
    if (o.rot) { const ax = x + an[0] * w, ay = y + an[1] * h; ctx.translate(ax, ay); ctx.rotate(o.rot); ctx.translate(-ax, -ay); }
    ctx.drawImage(f, x, y, w, h); ctx.restore();
    return { box: [x, y, w, h], frame: i + 1, info: S };
  }
  MEDIA.drawSeq = drawSeq; MEDIA.seqInfo = seqInfo;
})();
