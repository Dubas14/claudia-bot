// plate3d.js — 2.5D: a still + its depth map rendered with a moving camera (parallax occlusion mapping).
// PLATE3D.draw(ctx, img, depthImg, cam) paints into a 2D context (the base layer), cover-fitted to W×H.
// cam: { x, y } camera offset in screen fractions (e.g. .02 = 2 % of width of parallax at the nearest depth),
//      zoom (>=1), cx, cy (framing centre 0..1), focus (0..1 depth that stays still), rot (radians),
//      sway (hair/fabric wobble amount, px), t (time for sway)
// PLATE3D.safeCam(cam, imageAspect, faceUV, o) holds a push / zoom / crop where it would cut the face, and says whether the
// face fits through the screen-space camera (the default renderer's treatments call it for every plate shot and calm a
// shake that would still cut it: devices/treat.js "face-safe").
// Cost under SwiftShader: the 64-step shader is ~0.5–1.1 s a frame at 1920×1080 — for many 2.5D shots prefer depth
// slices / multiplane treatments (2D canvas, ~30 ms). Depth must be Depth-Anything-V2-Small derived (media.js checks).
// Port notes: unchanged maths; comments generalised.
'use strict';
const PLATE3D = (() => {
  const VS = `#version 300 es
  in vec2 p; out vec2 uv; void main(){ uv = p*.5+.5; uv.y = 1.-uv.y; gl_Position = vec4(p,0,1); }`;
  const FS = `#version 300 es
  precision highp float; in vec2 uv; out vec4 o;
  uniform sampler2D uImg, uDep; uniform vec2 uCam, uScale, uOff; uniform float uFocus, uRot, uSway, uT, uZoom, uRA;
  vec2 fit(vec2 s){ // screen uv -> image uv (cover fit, zoom about the framing centre, rotation)
    // uRA = 1: the rotation acts on uv (the original behaviour, exact); uRA = W/H (opt-in cam.rotA): a true rotation in pixels
    vec2 c = s - .5; c.x *= uRA; float cs = cos(uRot), sn = sin(uRot); c = vec2(cs*c.x - sn*c.y, sn*c.x + cs*c.y); c.x /= uRA;
    return uOff + c * uScale / uZoom; }
  float dep(vec2 st){ return texture(uDep, st).r; }
  void main(){
    vec2 base = fit(uv);
    // steep parallax: walk from the near plane toward the far plane along the camera offset
    const int N = 64; vec2 dir = uCam * uScale; vec2 st = base;
    float pl = 1., pd = dep(base + dir * (1. - uFocus));
    for (int i = 1; i < N; i++) {
      float layer = 1. - float(i) / float(N - 1);           // 1 = near, 0 = far
      vec2 s = base + dir * (layer - uFocus);
      float d = dep(s);
      if (d >= layer) {                                      // crossed the surface: refine linearly between the two layers
        float a = (pd - pl), b = (d - layer); float k = a / (a - b + 1e-5);
        float L = mix(pl, layer, clamp(k, 0., 1.)); st = base + dir * (L - uFocus); break; }
      pl = layer; pd = d; st = s;
    }
    // subtle secondary motion on near, high-frequency areas (hair, fabric): a slow sway weighted by depth
    float dn = dep(st);
    st += vec2(sin(uT*1.7 + st.y*9.), cos(uT*1.3 + st.x*7.)) * uSway * .0008 * smoothstep(.55, 1., dn);
    o = vec4(texture(uImg, clamp(st, 0., 1.)).rgb, 1.);
  }`;
  let cv, gl, prog, tI, tD, U = {}, lastI = null, lastD = null, tA = null, lastA = null;
  function init() {
    cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    gl = cv.getContext('webgl2', { preserveDrawingBuffer: true, antialias: false });
    const sh = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); if (!gl.getShaderParameter(x, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(x)); return x; };
    prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog); gl.useProgram(prog);
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const l = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
    const mk = () => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t; };
    tI = mk(); tD = mk();
    ['uImg', 'uDep', 'uCam', 'uScale', 'uOff', 'uFocus', 'uRot', 'uSway', 'uT', 'uZoom', 'uRA'].forEach(n => U[n] = gl.getUniformLocation(prog, n));
  }
  function draw(ctx, img, depth, cam = {}) {
    if (!gl) init();
    const c = Object.assign({ x: 0, y: 0, zoom: 1.06, cx: .5, cy: .5, focus: .35, rot: 0, sway: 0, t: 0 }, cam);
    // c.aux draws an auxiliary image (a rotoscope matte, a depth map) through the same camera from its own texture slot,
    // so the plate's texture stays cached (occ.js); c.res (0..1) renders at that fraction of the resolution.
    const aux = !!c.aux, vw = c.res ? Math.max(1, Math.round(W * c.res)) : W, vh = c.res ? Math.max(1, Math.round(H * c.res)) : H;
    gl.viewport(0, 0, vw, vh);
    if (aux) {
      if (!tA) { tA = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tA); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); }
      if (lastA !== img) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tA); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img); lastA = img; }
    } else if (lastI !== img) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tI); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img); lastI = img; }
    if (lastD !== depth) { gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, tD); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, depth); lastD = depth; }
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, aux ? tA : tI); gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, tD);
    gl.uniform1i(U.uImg, 0); gl.uniform1i(U.uDep, 1);
    // cover fit: the fraction of the image visible at zoom 1 on each axis
    const ia = (img.naturalWidth || img.width) / (img.naturalHeight || img.height), sa = W / H;
    const sx = ia > sa ? sa / ia : 1, sy = ia > sa ? 1 : ia / sa;
    const vx = sx / c.zoom, vy = sy / c.zoom;
    const ox = clamp(c.cx, vx / 2 + .01, 1 - vx / 2 - .01), oy = clamp(c.cy, vy / 2 + .01, 1 - vy / 2 - .01);
    gl.uniform2f(U.uScale, sx, sy); gl.uniform2f(U.uOff, ox, oy); gl.uniform1f(U.uZoom, c.zoom);
    gl.uniform2f(U.uCam, c.x, c.y); gl.uniform1f(U.uFocus, c.focus); gl.uniform1f(U.uRot, c.rot); gl.uniform1f(U.uSway, c.sway); gl.uniform1f(U.uT, c.t);
    gl.uniform1f(U.uRA, c.rotA ? W / H : 1);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    if (vw !== W || vh !== H) { handOffPart(ctx, vw, vh); return; }
    if (api.readback ?? !!window.GLASS) handOff(ctx); else ctx.drawImage(cv, 0, 0, W, H);
  }
  // (c.res) the bottom-left vw × vh of the drawing buffer, read back and drawn scaled to W × H (software path, like handOff)
  let pb = null, pbx = null, pbPx = null, pbRow = null;
  function handOffPart(ctx, vw, vh) {
    if (!pb || pb.width !== vw || pb.height !== vh) { pb = document.createElement('canvas'); pb.width = vw; pb.height = vh;
      pbx = pb.getContext('2d', { willReadFrequently: true }); pbPx = new Uint8Array(vw * vh * 4); pbRow = new Uint8Array(vw * 4); }
    gl.readPixels(0, 0, vw, vh, gl.RGBA, gl.UNSIGNED_BYTE, pbPx);
    for (let y = 0, n = vw * 4; y < vh >> 1; y++) { const a = y * n, b = (vh - 1 - y) * n;
      pbRow.set(pbPx.subarray(a, a + n)); pbPx.copyWithin(a, b, b + n); pbPx.set(pbRow, b); }
    pbx.putImageData(new ImageData(new Uint8ClampedArray(pbPx.buffer), vw, vh), 0, 0);
    ctx.drawImage(pb, 0, 0, vw, vh, 0, 0, W, H);
  }
  // Readback hand-off (on whenever glass.js is loaded — the engine page always loads it — or PLATE3D.readback = true):
  // drawing a WebGL canvas into a 2D canvas switches that 2D canvas to GPU rasterisation for the rest of the page's life,
  // so text drawn on the base in LATER frames anti-aliases differently and a frame depends on whether a 2.5D plate was
  // rendered before it. readPixels → putImageData on a software scratch canvas → drawImage keeps the base software.
  let rb = null, rbx = null, rbPx = null, rbRow = null;
  function handOff(ctx) {
    if (!rb) { rb = document.createElement('canvas'); rb.width = W; rb.height = H; rbx = rb.getContext('2d', { willReadFrequently: true });
      rbPx = new Uint8Array(W * H * 4); rbRow = new Uint8Array(W * 4); }
    gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, rbPx);                  // rows bottom-up: flip them
    for (let y = 0, n = W * 4; y < H >> 1; y++) { const a = y * n, b = (H - 1 - y) * n;
      rbRow.set(rbPx.subarray(a, a + n)); rbPx.copyWithin(a, b, b + n); rbPx.set(rbRow, b); }
    rbx.putImageData(new ImageData(new Uint8ClampedArray(rbPx.buffer), W, H), 0, 0);
    ctx.drawImage(rb, 0, 0, W, H);
  }
  // depth at image point (u,v) 0..1, from a depth image (for auto-focus on the subject)
  const _dc = document.createElement('canvas'); _dc.width = _dc.height = 1; const _dx = _dc.getContext('2d', { willReadFrequently: true });
  function depthAt(depth, u, v) { _dx.drawImage(depth, u * depth.naturalWidth - .5, v * depth.naturalHeight - .5, 1, 1, 0, 0, 1, 1); return _dx.getImageData(0, 0, 1, 1).data[0] / 255; }

  // FACE-SAFE FRAMING: safeCam(cam, ia, face, o) → {cam, ok, fits, held, moved}: the camera (zoom, cx, cy) closest to `cam`
  // that keeps `face` ([u, v, w, h], image space 0..1) inside the frame with headroom. The framing maths is draw()'s and
  // MEDIA.plateMap's (cover fit, the framing centre clamped .01 inside the image; MEDIA's flat cover() agrees), so the box
  // the engine reports is the box on screen. First the framing centre moves toward the face (never past the image edge);
  // when that is not enough the zoom is held at the largest value that fits (never under o.zmin, default 1: the plate
  // always covers the frame) — a push simply stops where it would cut the face. The headroom shrinks to what the plate has
  // above the face (a head at the image's top edge cannot get any), and a box that cannot fit even at the widest framing
  // keeps its top 60 % (the brow to the nose). ia: the image's aspect (w / h). fits: 'face' (the whole box is on screen,
  // through the screen-space camera), 'top' (its top 60 %), false (framed in this camera only: the screen-space camera's
  // overscan and shake still push it out — the caller calms the shake, devices/treat.js).
  // o: {sa (frame aspect, W/H), head .06 / foot .03 / side .03 (margins, fractions of the frame), outer {s, dx, dy, rot, jx,
  //    jy, jr} (a screen-space camera drawn after this one — CAM.through's zoom about the centre plus its offset; jx / jy px
  //    and jr rad: a shake that moves it up to that much either way, framed for its worst), zmin, e .01}
  function safeCam(cam, ia, face, o = {}) {
    const c0 = Object.assign({ zoom: 1.06, cx: .5, cy: .5 }, cam), sa = o.sa ?? W / H, sx = ia > sa ? sa / ia : 1, sy = ia > sa ? 1 : ia / sa, e = o.e ?? .01;
    const out = o.outer || {}, s = Math.max(1, +out.s || 1), dxf = (+out.dx || 0) / W, dyf = (+out.dy || 0) / H, jxf = Math.abs(+out.jx || 0) / W, jyf = Math.abs(+out.jy || 0) / H;
    const rs = Math.abs(Math.sin(Math.abs(+out.rot || 0) + Math.abs(+out.jr || 0))) * .5;
    // a screen window [A, B] (fractions) → the same window in this camera's frame, before the screen-space camera
    const win = (A, B, d, j, pad) => [.5 + (A + pad + j - .5 - d) / s, .5 + (B - pad - j - .5 - d) / s];
    const hd = o.head ?? .06, ft = o.foot ?? .03, sd = o.side ?? .03, px = rs * H / W, py = rs * W / H;
    const soft = { x: win(sd, 1 - sd, dxf, jxf, px), y: win(hd, 1 - ft, dyf, jyf, py) }, hard = { x: win(0, 1, dxf, jxf, px), y: win(0, 1, dyf, jyf, py) };
    // one axis at zoom z: the framing centres that keep [f0, f1] inside → the one nearest the asked centre, or null
    const axis = (z, f0, f1, sAx, so, ha, c) => {
      const v = sAx / z, h = v / 2, lo = h + e, hi = Math.max(lo, 1 - h - e);
      const a = Math.min(so[0], Math.max(ha[0], (f0 - e) / v)), b = Math.max(so[1], Math.min(ha[1], 1 + (f1 - 1 + e) / v));
      const L = Math.max(f1 - (b - .5) * v, lo), U = Math.min(f0 + (.5 - a) * v, hi);
      return L <= U + 1e-9 ? Math.min(Math.max(Math.min(Math.max(c, lo), hi), L), U) : null;
    };
    const at = (z, F, so, ha) => { const X = axis(z, F[0], F[0] + F[2], sx, so.x, ha.x, c0.cx), Y = axis(z, F[1], F[1] + F[3], sy, so.y, ha.y, c0.cy);
      return X != null && Y != null ? { zoom: z, cx: X, cy: Y } : null; };
    const fit = (F, so, ha) => {
      const z0 = +c0.zoom || 1.06, zmin = Math.min(z0, o.zmin ?? 1); let r = at(z0, F, so, ha); if (r) return r;
      if (!at(zmin, F, so, ha)) return null;
      let lo = zmin, hi = z0; for (let i = 0; i < 32; i++) { const m = (lo + hi) / 2; if (at(m, F, so, ha)) lo = m; else hi = m; }
      return at(lo, F, so, ha);
    };
    // (the part of the face the framing can show: the plate's .01 edge guard is never on screen)
    const g = face.slice(0, 4).map(Number), u0 = Math.max(g[0], e), v0 = Math.max(g[1], e), u1 = Math.min(g[0] + g[2], 1 - e), v1 = Math.min(g[1] + g[3], 1 - e);
    if (!(u1 > u0 && v1 > v0)) return { cam: Object.assign({}, cam), ok: false, fits: false, held: false, moved: false };
    const f = [u0, v0, u1 - u0, v1 - v0], top = [f[0], f[1], f[2], f[3] * .6], none = { x: [0, 1], y: [0, 1] };
    let fits = 'face', r = fit(f, soft, hard);
    if (!r) { fits = 'top'; r = fit(top, soft, hard); }
    if (!r) { fits = false; r = fit(f, none, none) || fit(top, none, none); }
    if (!r) return { cam: Object.assign({}, cam), ok: false, fits: false, held: false, moved: false };
    const held = r.zoom < (+c0.zoom || 1.06) - 1e-6;
    return { cam: Object.assign({}, cam, r), ok: true, fits, held, moved: held || Math.abs(r.cx - c0.cx) > 1e-6 || Math.abs(r.cy - c0.cy) > 1e-6 };
  }
  const api = { draw, depthAt, safeCam, readback: undefined };
  return api;
})();
