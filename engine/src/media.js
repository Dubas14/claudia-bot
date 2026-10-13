// media.js — plates (still + depth + detections) and clips (JPEG sequences + per-frame tracks) with a camera.
// Every draw returns m = {map(u, v) -> [x, y] (IMAGE space 0..1 → SCREEN px), box(label) -> [x, y, w, h] screen px | null,
// score(label) -> detection score | null, meta} (+ m.matte() / m.depth() from occ.js), so annotations stay pinned to
// what is in frame while the camera moves.
//   window.PLATES = { name: { file?, depth?, matte?, depth_model?, subject_depth, boxes: { 'a face': [x,y,w,h,score], … } } }
//       file  defaults to assets/plates/<name>.jpg, depth to assets/plates/<name>.depth.png (depth: false = none);
//       relative paths resolve against <project>/engine/ (the page's base URL)
//   window.CLIPS  = { clip: { n, fps, dir, matte?, depth? } }        frames <dir>/f00001.jpg …
//   window.TRACK  = { clip: { label: [[x,y,w,h,score] | null per frame at 12 fps], … } }
//   window.EDL    = { shotId: { segs: [{t0, clip, in, hold?}] } | { plate } }
// Port notes (engine-core v1): plate/depth paths may come from PLATES metadata; depth is used only when it is labelled
// Depth-Anything-V2-Small (ENGINE.depthOK: PLATES[name].depth_model or PROJECT.depth_model) — otherwise the plate is
// drawn flat; a missing plate / clip / declared depth is reported (ENGINE.missingMedia) instead of failing silently; in portrait frames (the 9:16 cut)
// the camera centre follows the subject (MEDIA.subject: the lead's box from detections/tracks) unless cam.subject === false.
'use strict';
const MEDIA = (() => {
  const P = () => window.PLATES || {}, T = () => window.TRACK || {};
  const metaOf = name => P()[name] || {};
  const plateSrc = (name, meta) => (typeof meta.file === 'string' && meta.file) || (typeof meta.src === 'string' && meta.src) || `assets/plates/${name}.jpg`;
  const depthSrc = (name, meta) => meta.depth === false || meta.depth === null ? null : (typeof meta.depth === 'string' ? meta.depth : `assets/plates/${name}.depth.png`);
  const refused = new Set();
  // a missing plate image rejects (and is reported: ENGINE.missingMedia); a declared depth path that is missing is
  // reported too, the guessed default (assets/plates/<name>.depth.png) is optional; depth that is not labelled
  // Depth-Anything-V2-Small is not loaded (flat plate, one warning)
  async function plate(name) {
    const meta = metaOf(name);
    const img = await loadImage('plate:' + name, plateSrc(name, meta));
    let dep = null; const ds = depthSrc(name, meta), ok = ENGINE.depthOK(meta);
    if (ds && !ok && typeof meta.depth === 'string' && !refused.has(name)) {
      refused.add(name); console.warn(`[media] depth of plate '${name}' is not labelled Depth-Anything-V2-Small (depth_model: ${meta.depth_model || 'none'}) — drawn flat`);
    }
    if (ds && ok) { try { dep = await loadImage('depth:' + name, ds, { optional: typeof meta.depth !== 'string' }); } catch (e) { dep = null; } }
    return { img, dep, meta };
  }
  // same maths as cover(): returns the mapper for an image drawn with cover options
  function coverMap(im, o = {}) {
    const { x = 0, y = 0, w = W, h = H, cx = .5, cy = .5, zoom = 1 } = o;
    const nw = im.naturalWidth || im.width, nh = im.naturalHeight || im.height;
    const s = Math.max(w / nw, h / nh) * zoom, IW = nw * s, IH = nh * s;
    const ox = o.free ? -cx * IW : clamp(-cx * IW, w / 2 - IW, -w / 2), oy = o.free ? -cy * IH : clamp(-cy * IH, h / 2 - IH, -h / 2);
    return (u, v) => [x + w / 2 + ox + u * IW, y + h / 2 + oy + v * IH];
  }
  // PLATE3D framing (see plate3d.js): screen uv = (img uv − off) · zoom / scale + .5 (the focus plane does not shift)
  function plateMap(im, c) {
    const ia = (im.naturalWidth || im.width) / (im.naturalHeight || im.height), sa = W / H, sx = ia > sa ? sa / ia : 1, sy = ia > sa ? 1 : ia / sa, z = c.zoom ?? 1.06;
    const vx = sx / z, vy = sy / z, ox = clamp(c.cx ?? .5, vx / 2 + .01, 1 - vx / 2 - .01), oy = clamp(c.cy ?? .5, vy / 2 + .01, 1 - vy / 2 - .01);
    return (u, v) => [((u - ox) * z / sx + .5) * W, ((v - oy) * z / sy + .5) * H];
  }
  const toBox = (map, b) => { if (!b) return null; const [x0, y0] = map(b[0], b[1]), [x1, y1] = map(b[0] + b[2], b[1] + b[3]); return [x0, y0, x1 - x0, y1 - y0]; };
  // the subject's image-space box: the lead label (PROJECT.lead.label), else common person labels, else a face
  const SUBJ = ['subject', 'a person', 'a woman', 'a man', 'a girl', 'a boy', 'a singer', 'a face'];
  function subjectBox(boxes) {
    if (!boxes) return null; const P0 = window.PROJECT || {}, want = [P0.lead && (P0.lead.label || P0.lead.match), ...SUBJ].filter(Boolean);
    for (const l of want) { const b = boxes[l]; if (b && b.length >= 4) return { label: l, box: b }; }
    return null;
  }
  function trackAt(name, label, lt) {
    const tr = T()[name]; if (!tr || !tr[label]) return null; const a = tr[label], fi = lt * 12, i = Math.floor(fi), k = fi - i;
    const b0 = a[clamp(i, 0, a.length - 1)], b1 = a[clamp(i + 1, 0, a.length - 1)]; return b0 && b1 ? b0.map((v, j) => lerp(v, b1[j], k)) : (b0 || b1);
  }
  // MEDIA.subject(plateName | {boxes} | shotId, lt?) → {u, v, box, label} (image space) | null
  function subject(x, lt = 0) {
    if (!x) return null;
    if (typeof x === 'object') { const s = subjectBox(x.boxes); return s ? { u: s.box[0] + s.box[2] / 2, v: s.box[1] + s.box[3] / 2, box: s.box, label: s.label } : null; }
    if (P()[x]) return subject(P()[x]);
    const e = (window.EDL || {})[x]; if (e && e.plate) return subject(P()[e.plate]);
    if (e && e.segs && e.segs.length) { const sg = e.segs[0], tr = T()[sg.clip] || {};
      const lab = subjectBox(Object.fromEntries(Object.keys(tr).map(k => [k, [0, 0, 1, 1]]))); if (!lab) return null;
      const b = trackAt(sg.clip, lab.label, sg.in + lt); return b ? { u: b[0] + b[2] / 2, v: b[1] + b[3] / 2, box: b, label: lab.label } : null; }
    if (T()[x]) { const lab = subjectBox(Object.fromEntries(Object.keys(T()[x]).map(k => [k, [0, 0, 1, 1]]))); const b = lab && trackAt(x, lab.label, lt);
      return b ? { u: b[0] + b[2] / 2, v: b[1] + b[3] / 2, box: b, label: lab.label } : null; }
    return null;
  }
  // portrait: shift the framing centre to the subject (the cover clamp keeps the frame filled)
  const portraitCam = (cam, su) => (PORTRAIT && su && cam.subject !== false) ? Object.assign({}, cam, { cx: (cam.cx ?? .5) + (su.u - .5) }) : cam;
  // draw a plate in 2.5D (depth) or flat (no depth); cam: {x, y, zoom, cx, cy, focus, sway, rot, flat}
  async function drawPlate(ctx, name, cam = {}, t = 0) {
    // a missing plate: null (the caller draws its fallback) — the file is reported in ENGINE.missingMedia and the frame is
    // marked, so `slop render frames` refuses it instead of shipping the placeholder
    let m; try { m = await plate(name); } catch (e) { return null; }
    cam = portraitCam(cam, subject(m.meta));
    const deep = !!(m.dep && !cam.flat), c = Object.assign({ focus: m.meta.subject_depth ?? .5 }, cam, { t });
    if (deep) PLATE3D.draw(ctx, m.img, m.dep, c); else cover(ctx, m.img, c);
    const map = deep ? plateMap(m.img, c) : coverMap(m.img, c);
    const boxes = m.meta.boxes || {};
    const res = { map, box: label => toBox(map, boxes[label]), score: label => (boxes[label] && boxes[label][4] != null ? boxes[label][4] : null), meta: m.meta, kind: 'plate', name };
    // m.matte() / m.depth() drawn through this same camera and base transform (occ.js)
    if (window.OCC) OCC.attach(res, { kind: 'plate', name, img: m.img, dep: m.dep, cam: c, deep, xf: ctx.getTransform() });
    return res;
  }
  // draw a clip frame; localT = seconds into the clip; cam: {zoom, cx, cy, speed (time-stretch), hold (freeze at s)}
  async function drawClip(ctx, name, localT, cam = {}) {
    const lt = cam.hold != null ? cam.hold : localT * (cam.speed || 1);
    const f = await clipFrame(name, lt); if (!f) return { map: (u, v) => [u * W, v * H], box: () => null, score: () => null, meta: {}, kind: 'clip', name };
    cam = portraitCam(cam, subject(name, lt));
    cover(ctx, f, cam); const map = coverMap(f, cam);
    const res = { map, box: label => toBox(map, trackAt(name, label, lt)), score: label => { const b = trackAt(name, label, lt); return b && b[4] != null ? b[4] : null; },
      meta: (window.CLIPS || {})[name] || {}, kind: 'clip', name };
    // the clip's matte/depth frame with the same number as the picture frame, same camera (occ.js)
    if (window.OCC) { const c = SEQ[name]; OCC.attach(res, { kind: 'clip', name, dir: c.dir, idx: clamp(Math.floor(lt * (c.fps || 24) + 1e-6), 0, c.n - 1) + 1, cam, xf: ctx.getTransform() }); }
    return res;
  }
  // camera presets from storyboard words (push, pull, pan left/right, tilt up/down, truck, static, handheld, orbit)
  function camFrom(desc, p, o = {}) {
    const d = (desc || '').toLowerCase(), a = o.amt ?? 1, e = easeInOut(p);
    const c = { x: 0, y: 0, zoom: 1.06, cx: o.cx ?? .5, cy: o.cy ?? .5 };
    if (/push|dolly in|creep in|zoom in/.test(d)) c.zoom = lerp(1.04, 1.04 + .12 * a, e);
    if (/pull|dolly out|zoom out|reveal/.test(d)) c.zoom = lerp(1.16 * a + (1 - a) * 1.04, 1.04, e);
    if (/pan left|truck left|slide left/.test(d)) { c.x = lerp(.018, -.018, e) * a; c.cx = (o.cx ?? .5) + lerp(.03, -.03, e) * a; }
    if (/pan right|truck right|slide right|lateral/.test(d)) { c.x = lerp(-.018, .018, e) * a; c.cx = (o.cx ?? .5) + lerp(-.03, .03, e) * a; }
    if (/tilt up|crane up|rise/.test(d)) { c.y = lerp(.012, -.012, e) * a; c.cy = (o.cy ?? .5) + lerp(.04, -.04, e) * a; }
    if (/tilt down|crane down|descend/.test(d)) { c.y = lerp(-.012, .012, e) * a; c.cy = (o.cy ?? .5) + lerp(-.04, .04, e) * a; }
    if (/orbit|arc/.test(d)) { c.x = Math.sin(e * Math.PI - Math.PI / 2) * .02 * a; c.rot = lerp(-.01, .01, e) * a; }
    if (/static|locked|lock-off/.test(d) && !/push|pull|pan|tilt/.test(d)) { c.x = lerp(-.003, .003, e); c.zoom = lerp(1.05, 1.07, e); }
    if (/handheld|shake/.test(d)) { const [sx, sy] = shake(o.t || 0, .004 * a); c.x += sx; c.y += sy; }
    return c;
  }
  // draw a storyboard shot's base layer from window.EDL: its clip segments in SONG time (a take, then its divergence
  // covers) or its plate (2.5D). Scene code calls this instead of naming clips, so it survives retakes.
  async function drawShot(ctx, id, t, cam = {}) {
    const e = (window.EDL || {})[id] || {};
    const sg = e.segs && e.segs.length ? (e.segs.filter(x => x.t0 <= t + 1e-6).pop() || e.segs[0]) : null;
    // a segment may freeze a frame ({hold: s}) — e.g. hold a take's first frame until its sung window opens
    if (sg) return drawClip(ctx, sg.clip, sg.hold != null ? sg.hold : (sg.in || 0) + (t - sg.t0), { zoom: cam.zoom, cx: cam.cx, cy: cam.cy, hold: sg.hold != null ? sg.hold : cam.hold, subject: cam.subject });
    if (e.plate) return drawPlate(ctx, e.plate, cam, t);
    return null;
  }
  return { plate, drawPlate, drawClip, drawShot, camFrom, coverMap, plateMap, toBox, subject, trackAt };
})();
ENGINE.media = MEDIA;
