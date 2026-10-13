// post.js — the one full-frame pass (WebGL2) that turns the base (footage) + overlay (type, graphics) into the frame.
// Two looks:
//   'native'  (clean projects: project look.mode 'native' | 'clean' | 'clean-grade') — the footage exactly as generated
//             (any grade is baked into plates/clips at import): no grade, screen, grain, vignette, lift or flash; texelFetch
//             reads each base pixel unresampled and the overlay composites over it; a dissolve is a plain crossfade.
//   'print'   (project look.mode 'print'; per-section screen modes grain | line | bit | dot) — exposure, an S-curve that
//             never clips, saturation, a four-plate colour halftone (CMY + K by grey-component replacement, classic screen
//             angles, a little misregistration) mixed with the continuous image so faces keep their detail, grain, then
//             the overlay composited crisp. The footage keeps its colour — never desaturate the base.
// Glass (glass.js) drawn this frame is rendered into an offscreen copy of the base first.
// Port notes (engine-core v1): accentKeep / accentTol / accentSat are honoured by the print look again — the reference
// project's look table set them, but only the retired v1 mono pass read them (this re-adds its accent mask to the colour
// pass):
// base pixels near the look's accent hue keep their continuous colour through the screen and grain ("only the accent
// prints clean"); accentKeep defaults to 0, which is exactly the previous output. ENGINE.look() / PRINT_LOOKS live here
// (section → look by name and ordinal, no time hard-codes). Shaders are otherwise unchanged.
// No accent: project look.accent null — ENGINE.look() then drops the section accents (verse2 ember, the
// bridge grey) and forces accentKeep 0, and its accent is the plain type colour (core.js INK); a shot's own accent wins.
'use strict';
const POST = (() => {
  const VS = `#version 300 es
  in vec2 p; out vec2 uv; void main(){ uv = p*.5+.5; uv.y = 1.-uv.y; gl_Position = vec4(p,0,1); }`;
  const FS = `#version 300 es
  precision highp float;
  in vec2 uv; out vec4 o;
  uniform sampler2D uBase, uOver, uBase2;
  uniform float uMix; uniform int uMixMode;   // transition: 0 none, 1 ordered-dither dissolve into uBase2
  uniform vec2 uRes;
  uniform int uMode;            // 0 fine dots (verses), 1 line screen (choruses), 2 bold dots (drop), 3 dots (final/outro)
  uniform vec3 uPaper;
  uniform float uExposure, uContrast, uGamma, uSat, uLift;
  uniform float uScreen, uFreq, uAngle, uMisreg, uGrain, uCell, uSeed, uVignette, uOverGrain;
  uniform float uAccentHue, uAccentTol, uAccentKeep, uAccentSat;
  vec3 rgb2hsv(vec3 c){ vec4 K=vec4(0.,-1./3.,2./3.,-1.); vec4 p=mix(vec4(c.bg,K.wz),vec4(c.gb,K.xy),step(c.b,c.g));
    vec4 q=mix(vec4(p.xyw,c.r),vec4(c.r,p.yzx),step(p.x,c.r)); float d=q.x-min(q.w,q.y); float e=1e-10;
    return vec3(abs(q.z+(q.w-q.y)/(6.*d+e)),d/(q.x+e),q.x); }
  float h12(vec2 p){ p = fract(p*vec2(443.897,441.423)); p += dot(p, p.yx+19.19); return fract((p.x+p.y)*p.x); }
  float lum(vec3 c){ return dot(c, vec3(.2126,.7152,.0722)); }
  float bayer8(vec2 p){ int x = int(mod(p.x, 8.)), y = int(mod(p.y, 8.));
    const int B[64] = int[64](0,32,8,40,2,34,10,42,48,16,56,24,50,18,58,26,12,44,4,36,14,46,6,38,60,28,52,20,62,30,54,22,
      3,35,11,43,1,33,9,41,51,19,59,27,49,17,57,25,15,47,7,39,13,45,5,37,63,31,55,23,61,29,53,21);
    return (float(B[y*8+x]) + .5) / 64.; }
  vec3 baseAt(vec2 st){
    vec3 a = texture(uBase, st).rgb;
    if (uMixMode == 1) { float th = bayer8(floor(st * uRes / 3.)); if (uMix > th) a = texture(uBase2, st).rgb; }
    return a; }
  // colour grade: exposure, a smooth S-curve on luminance (contrast without clipping), gamma, saturation; chroma ratios kept
  vec3 grade(vec3 c){
    c = max(c * uExposure, 0.);
    float l = lum(c), lc = clamp(l, 0., 1.);
    float s = lc * lc * (3. - 2. * lc);                        // smoothstep: slope 1.5 at mid-grey, 0 at the ends
    float l2 = pow(clamp(mix(lc, s, clamp((uContrast - 1.) * 2., 0., 1.)), 0., 1.), uGamma);
    vec3 g = c * (l2 / max(l, 1e-4));
    float mx = max(g.r, max(g.g, g.b));
    if (mx > 1.) g = mix(g / mx, vec3(1.), clamp((mx - 1.) / mx, 0., 1.));   // highlight roll-off: toward white, hue kept
    g = mix(vec3(lum(g)), g, uSat);
    g = mix(g, vec3(1.), uLift);                               // deliberate fades to paper only (lift >= .8 upstream)
    return clamp(g, 0., 1.);
  }
  // one halftone plate: 1 where ink. Euclidean dot (dots → checkerboard → inverted dots) or line screen; antialiased
  float plate(vec2 px, float ang, float cov){
    float c = cos(ang), s = sin(ang);
    vec2 r = vec2(c*px.x - s*px.y, s*px.x + c*px.y) / uFreq;
    float p = uMode == 1 ? .5 - .5 * cos(6.2831853 * r.y)
                         : .25 * (2. - cos(6.2831853 * r.x) - cos(6.2831853 * r.y));
    float w = fwidth(p) * .75 + 1e-4;
    return smoothstep(p - w, p + w, cov);
  }
  void main(){
    vec2 px = uv * uRes;
    vec2 mo = vec2(uMisreg, -uMisreg * .5) / uRes;
    vec3 c0 = grade(baseAt(uv));
    vec3 cC = grade(baseAt(uv + mo)), cM = grade(baseAt(uv - mo));          // two plates slightly off register
    float K = 1. - max(c0.r, max(c0.g, c0.b));                                 // grey-component replacement: neutrals print as K
    float ik = 1. / max(1. - K, 1e-3);
    float C = clamp((1. - cC.r - K) * ik, 0., 1.), Mg = clamp((1. - cM.g - K) * ik, 0., 1.), Y = clamp((1. - c0.b - K) * ik, 0., 1.);
    float a = uAngle;
    vec3 printed = vec3(1. - plate(px, a + .2618, C), 1. - plate(px, a + 1.309, Mg), 1. - plate(px, a, Y))
                 * (1. - plate(px, a + .7854, K)) * uPaper;
    // accent protection (look.accentKeep > 0): base pixels near the accent hue print as continuous colour, no grain
    vec3 hb = rgb2hsv(baseAt(uv)); float dh = abs(hb.x - uAccentHue); dh = min(dh, 1. - dh);
    float am = uAccentKeep * smoothstep(uAccentTol, uAccentTol * .4, dh) * smoothstep(uAccentSat * .6, uAccentSat, hb.y) * smoothstep(.12, .3, hb.z);
    vec3 col = mix(c0, printed, uScreen * (1. - am));
    float g = h12(floor(px / uCell) + uSeed * 17.13) - .5;                    // grain at a uCell px cell, boils with uSeed
    col = clamp(col + g * uGrain * (1. - am), 0., 1.);
    float v = smoothstep(1.25, .35, length((uv - .5) * vec2(1., uRes.y/uRes.x) * 1.6));
    col *= mix(1. - uVignette, 1., v);
    vec4 ov = texture(uOver, uv);                                              // overlay (premultiplied), light grain
    vec3 oc = ov.rgb + g * uOverGrain * ov.a;
    col = col * (1. - ov.a) + oc;
    o = vec4(col, 1.);
  }`;
  let gl, prog, texB, texO, texB2, U = {};
  function init(canvas) {
    gl = canvas.getContext('webgl2', { preserveDrawingBuffer: true, antialias: false });
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog); if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const mk = () => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t; };
    texB = mk(); texO = mk(); texB2 = mk();
    ['uBase', 'uOver', 'uBase2', 'uMix', 'uMixMode', 'uRes', 'uMode', 'uPaper', 'uExposure', 'uContrast', 'uGamma', 'uSat', 'uLift',
      'uScreen', 'uFreq', 'uAngle', 'uMisreg', 'uGrain', 'uCell', 'uSeed', 'uVignette', 'uOverGrain',
      'uAccentHue', 'uAccentTol', 'uAccentKeep', 'uAccentSat'].forEach(n => U[n] = gl.getUniformLocation(prog, n));
  }
  const MODES = { grain: 0, line: 1, bit: 2, dot: 3 };
  // per screen: default pitch (px) and how much of the printed image shows over the continuous one
  const SCREEN = [{ freq: 4.2, screen: .42 }, { freq: 6, screen: .55 }, { freq: 8.5, screen: .68 }, { freq: 7, screen: .6 }];
  const smooth = (a, b, x) => { const k = clamp((x - a) / (b - a)); return k * k * (3 - 2 * k); };
  const hue = hex => { const [r, g, b] = rgb(hex); const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; if (!d) return 0;
    let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; h /= 6; return h < 0 ? h + 1 : h; };
  // look: the section looks (PRINT_LOOKS / PROJECT.looks) + per-shot overrides. exposure/contrast/gamma/lift are damped
  // intent (calibrated under a mono screen whose default gamma was 1.45). Keys: sat, screen, accentKeep/Tol/Sat.
  function run(base, over, look, t, base2 = null, mix = 0) {
    // glass drawn this frame (glass.js) is rendered into an offscreen copy of the base first; look.mode 'native'
    // composites without any colour operation.
    const gtex = window.GLASS && GLASS.used() ? glassPass(base, GLASS.field(), t) : null;
    if (look && look.mode === 'native') return native(gtex, base, over, base2, mix);
    if (gtex) { gl.useProgram(prog); gl.bindFramebuffer(gl.FRAMEBUFFER, null); }
    const L = Object.assign({ mode: 'grain', paper: INK.paper, exposure: 1, contrast: 1.35, gamma: 1.45, lift: 0, grain: .12, cell: 2,
      angle: .785, misreg: 2, vignette: .3, overGrain: .05, accent: INK.accent, accentKeep: 0, accentTol: .045, accentSat: .55 }, look);
    const mode = MODES[L.mode] ?? 0, S = SCREEN[mode];
    const paper = rgb(L.paper).map(v => 1 - (1 - v) * .35);
    gl.viewport(0, 0, W, H);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    if (gtex) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, gtex); }
    else { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texB); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, base); }
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texO); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, over);
    if (base2) { gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false); gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, texB2); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, base2); }
    gl.uniform1i(U.uBase2, 2); gl.uniform1f(U.uMix, mix); gl.uniform1i(U.uMixMode, base2 ? 1 : 0);
    gl.uniform1i(U.uBase, 0); gl.uniform1i(U.uOver, 1); gl.uniform2f(U.uRes, W, H);
    gl.uniform1i(U.uMode, mode); gl.uniform3fv(U.uPaper, paper);
    gl.uniform1f(U.uExposure, clamp(1 + (L.exposure - 1) * .3, .85, 1.35));
    gl.uniform1f(U.uContrast, clamp(1.2 + (L.contrast - 1.35) * .4, 1, 1.45));
    gl.uniform1f(U.uGamma, clamp(1 + (L.gamma - 1.45) * .15, .9, 1.1));
    gl.uniform1f(U.uSat, L.sat ?? 1.15);
    gl.uniform1f(U.uLift, smooth(.8, 1, L.lift));
    gl.uniform1f(U.uScreen, L.screen ?? S.screen);
    gl.uniform1f(U.uFreq, clamp(mode === 0 || L.freq == null ? S.freq : L.freq, 3.2, 16));
    gl.uniform1f(U.uAngle, L.angle); gl.uniform1f(U.uMisreg, L.misreg);
    gl.uniform1f(U.uGrain, clamp(L.grain, 0, .2) * .5); gl.uniform1f(U.uCell, L.cell); gl.uniform1f(U.uSeed, boilSeed(t) % 997);
    gl.uniform1f(U.uVignette, Math.min(L.vignette, .2)); gl.uniform1f(U.uOverGrain, L.overGrain);
    gl.uniform1f(U.uAccentHue, hue(L.accent || INK.accent)); gl.uniform1f(U.uAccentTol, clamp(+L.accentTol || .045, .005, .5));
    gl.uniform1f(U.uAccentKeep, clamp(+L.accentKeep || 0)); gl.uniform1f(U.uAccentSat, clamp(L.accentSat ?? .55, .02, 1));
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  // ---- NATIVE: look {mode: 'native'}: the footage exactly as generated (the owner rejected graded, blown-out output) —
  // no grade, contrast, saturation or exposure, no screen, grain or vignette, no lift or flash. texelFetch reads each base
  // pixel unresampled and the overlay (premultiplied) composites over it; a dissolve (base2) is a plain crossfade.
  const FS_NATIVE = `#version 300 es
  precision highp float; out vec4 o;
  uniform sampler2D uBase, uOver, uBase2; uniform float uMix, uH; uniform int uMixOn;
  void main(){
    ivec2 p = ivec2(int(gl_FragCoord.x), int(uH - gl_FragCoord.y));          // top-down image row
    vec3 c = texelFetch(uBase, p, 0).rgb;
    if (uMixOn == 1) c = mix(c, texelFetch(uBase2, p, 0).rgb, uMix);
    vec4 ov = texelFetch(uOver, p, 0);
    o = vec4(c * (1. - ov.a) + ov.rgb, 1.);
  }`;
  const FS_COPY = `#version 300 es
  precision highp float; out vec4 o; uniform sampler2D uBase;
  void main(){ o = vec4(texelFetch(uBase, ivec2(gl_FragCoord.xy), 0).rgb, 1.); }`;
  // ---- GLASS (engine/src/glass.js; the maths is described there) ----
  const FS_GLASS = `#version 300 es
  precision highp float; out vec4 o;
  uniform sampler2D uBase;                  // the footage, mipmapped: frost and reflections read its blurred levels
  uniform sampler2D uF1, uF2, uF3;          // the field: [f, dh/dx, dh/dy, presence] [frost px, refract, disp, tint] [ripple, spec, bevel px, h]
  uniform vec2 uRes, uShOff;
  uniform vec4 uBox;                        // px, top-left origin: where glass or its shadow can be; elsewhere the base passes through
  uniform float uSig, uSigH, uIor, uGap, uThick, uShadow, uEnv, uRim, uDispK, uT, uLI, uRimBlur;
  uniform vec3 uL;
  uniform int uND; uniform vec4 uDome[16]; uniform float uDK[16];
  float erfinv(float x) {                   // Giles 2010, single precision
    float w = -log((1. - x) * (1. + x)), p;
    if (w < 5.) { w -= 2.5; p = 2.81022636e-08; p = 3.43273939e-07 + p*w; p = -3.5233877e-06 + p*w; p = -4.39150654e-06 + p*w;
      p = 0.00021858087 + p*w; p = -0.00125372503 + p*w; p = -0.00417768164 + p*w; p = 0.246640727 + p*w; p = 1.50140941 + p*w; }
    else { w = sqrt(w) - 3.; p = -0.000200214257; p = 0.000100950558 + p*w; p = 0.00134934322 + p*w; p = -0.00367342844 + p*w;
      p = 0.00573950773 + p*w; p = -0.0076224613 + p*w; p = 0.00943887047 + p*w; p = 1.00167406 + p*w; p = 2.83297682 + p*w; }
    return p * x;
  }
  vec3 toLin(vec3 c){ return pow(max(c, 0.), vec3(2.2)); }
  vec3 toSrgb(vec3 c){ return pow(clamp(c, 0., 1.), vec3(1. / 2.2)); }
  // cubic B-spline read of mip level lod (4 bilinear taps): a smooth blur of ≈ 0.67·2^lod px, no mip blocks
  vec3 bs(vec2 st, float lod) {
    vec2 sz = vec2(textureSize(uBase, int(lod)));
    vec2 p = st * sz - .5, i = floor(p), f = p - i, f2 = f * f, f3 = f2 * f;
    vec2 w0 = (1. - 3.*f + 3.*f2 - f3) / 6., w1 = (4. - 6.*f2 + 3.*f3) / 6., w2 = (1. + 3.*f + 3.*f2 - 3.*f3) / 6., w3 = f3 / 6.;
    vec2 g0 = w0 + w1, g1 = w2 + w3, c0 = (i - .5 + w1 / g0) / sz, c1 = (i + 1.5 + w3 / g1) / sz;
    return g0.y * (g0.x * textureLod(uBase, c0, lod).rgb + g1.x * textureLod(uBase, vec2(c1.x, c0.y), lod).rgb)
         + g1.y * (g0.x * textureLod(uBase, vec2(c0.x, c1.y), lod).rgb + g1.x * textureLod(uBase, c1, lod).rgb);
  }
  // what the glass sees behind it at st, frosted by r px: sharp below 0.7 px, else a B-spline read between two mip levels
  vec3 behind(vec2 st, float r) {
    if (r < .7) return textureLod(uBase, st, 0.).rgb;
    float L = max(log2(r / .67), 0.), l0 = floor(L), k = L - l0;
    vec3 a = bs(st, l0); return k < .02 ? a : mix(a, bs(st, l0 + 1.), k);
  }
  // Snell: where the view ray through this surface point, refracted into glass of index ior, meets the image plane
  vec2 bend(vec3 n, float ior, float depth) { vec3 r = refract(vec3(0., 0., -1.), n, 1. / ior); return r.xy / max(-r.z, .15) * depth; }
  // the bevel alone: the inward shift of the sample at inside distance d (a circular profile of radius bev, height T)
  float bevelShift(float d, float bev, float T, float gap) {
    float u = clamp(d / bev, 0., 1.), q = 1. - u, sl = min(T / bev * q / sqrt(max(1. - q * q, 4e-3)), 12.);
    vec2 o = bend(normalize(vec3(-sl, 0., 1.)), uIor, T * sqrt(max(1. - q * q, 0.)) + gap);
    return -o.x;                             // the normal tilts outward (-x here), the ray bends inward (+)
  }
  void main(){
    vec2 px = gl_FragCoord.xy;              // this pass writes a texture that is read top-down: fragment row = image row
    vec3 bg = texelFetch(uBase, ivec2(px), 0).rgb, res = bg;
    // (structured ifs, no early returns: SwiftShader skips a block only when a whole group of pixels agrees on it)
    if (px.x >= uBox.x && px.y >= uBox.y && px.x <= uBox.z && px.y <= uBox.w) {
    vec2 st = px / uRes;
    vec4 A = textureLod(uF1, st, 0.);
    float f = A.x, g = length(A.yz);                            // f: the silhouette field (σ = soft); A.yz: the height field's slope
    vec4 As = textureLod(uF1, (px - uShOff) / uRes, 0.);               // contact shadow: the field read back toward the light
    float sh = uShadow * As.w * smoothstep(.04, .8, As.x);
    // the silhouette, antialiased over ~1.6 px: at the edge a σ-blurred step has slope 1/(σ·√2π) per px
    float aa = .8 / (uSig * 2.5066), m = smoothstep(.5 - aa, .5 + aa, f);
    vec3 outside = bg * (1. - sh);
    res = outside;
    if (m > 0.) {
    vec4 B = textureLod(uF2, st, 0.), C = textureLod(uF3, st, 0.);
    float pres = A.w, frost = B.x * pres, refr = B.y, disp = B.z, tint = B.w * pres, ripple = C.x, spec = C.y, bev = max(C.z, 2.);
    // height: the distance inside the rim from the height field h, the coverage blurred by σh (a straight edge blurred by
    // σh reads h = Φ(d/σh); σh ≥ bevel/3.2 so the distance never saturates inside a bevel) …
    float d = uSigH * 1.41421356 * erfinv(clamp(2. * C.w - 1., -.9999, .9999));
    vec2 inw = g > 1e-7 ? A.yz / g : vec2(0.);                   // inward, up the field
    // … a rounded bevel of radius bev (vertical at the rim, flat on top) …
    float u = clamp(d / bev, 0., 1.), q = 1. - u, T = bev * uThick * pres;
    float Hh = T * sqrt(max(1. - q * q, 0.));
    vec2 gr = inw * min(T / bev * q / sqrt(max(1. - q * q, 4e-3)), 12.);
    // … plus domes. Blobs: a Gaussian cap that sums with its neighbours (drops that meet share one surface), sitting on the
    // image like a drop of water. Lenses: a shallow paraboloid floating uDK px above the image — a thin magnifier: the shift
    // grows linearly from the centre (clean magnification) and its dispersion is lateral colour, growing toward the rim.
    vec2 grD = vec2(0.), grL = vec2(0.); float Hd = 0., gapL = 0., wL = 0.;
    for (int i = 0; i < 16; i++) { if (i >= uND) break;
      vec4 D = uDome[i]; vec2 v = (px - D.xy) / D.z; float r2 = dot(v, v);
      if (uDK[i] > 0.) { if (r2 < 1.) { grL += D.w * (-2. * v / D.z); gapL = max(gapL, uDK[i]); wL = 1.; } }
      else { float e = exp(-2. * r2); Hd += D.w * e; grD += D.w * e * (-4. * v / D.z); } }
    Hh += Hd; gr += grD;
    // a liquid surface: a slow flow of shallow waves on the top, kept off the rim so the edge stays crisp
    if (ripple > .001) { vec2 p = px / 150.; float tt = uT * .3;
      vec2 w1 = vec2(cos(p.x * 1.7 + p.y * .6 + tt * 1.3), cos(p.y * 1.9 - p.x * .5 - tt));
      vec2 w2 = vec2(cos(p.x * 3.1 - p.y * 2.3 + tt * 2.1), cos(p.y * 2.7 + p.x * 1.1 + tt * 1.7));
      gr += ripple * pres * .08 * (w1 + .45 * w2) * smoothstep(.1, .9, u); }
    vec3 n = normalize(vec3(-gr, 1.)), nl = normalize(vec3(-gr - .4 * grL, 1.));
    float depth = Hh + uGap * pres;
    // refraction with dispersion: R, G and B bend by slightly different indices, so colour splits only where glass bends light
    float dn = uDispK * disp;
    vec2 oG = bend(n, uIor, depth), oR = bend(n, uIor - dn, depth), oB = bend(n, uIor + dn, depth);
    if (wL > 0.) { vec3 nL = normalize(vec3(-grL * pres, 1.));
      oG += bend(nL, uIor, gapL); oR += bend(nL, uIor - dn, gapL); oB += bend(nL, uIor + dn, gapL); }
    oG *= refr; oR *= refr; oB *= refr;
    // the refracted footprint: where the rim squeezes a strip of the image into a few pixels (the radial Jacobian
    // |1 + dδ/dd| of the bevel's shift δ), each pixel sees that strip's average — read it blurred by the footprint, so the
    // rim shows smooth compressed light instead of radial streaks. Frost adds on top.
    float gp = uGap * pres, jac = abs(1. + (bevelShift(d + .75, bev, T, gp) - bevelShift(d - .75, bev, T, gp)) / 1.5 * refr);
    // (+ a little polish: real rims are never optically perfect; it also calms fine texture the rim stretches into streaks)
    float fr = frost + uRimBlur * (max(jac - 1., 0.) * .5 + 2.6 * smoothstep(.25, .95, 1. - n.z) * pres);
    vec3 col = behind((px + oG) / uRes, fr);
    if (length(oR - oB) > .3) { col.r = behind((px + oR) / uRes, fr).r; col.b = behind((px + oB) / uRes, fr).b; }
    vec3 c = toLin(mix(col, vec3(tint > 0. ? 1. : 0.), abs(tint)));        // a faint neutral tint, measured on screen (≤ 10 %)
    // light. Fresnel: the rim reflects a soft studio (a broad key from the light, a dim sky) over the blurred surroundings;
    // a thin bright edge line (Apple's specular rim) strongest facing the light and again on the far side; a soft sheen
    vec2 l2 = normalize(uL.xy + 1e-6);
    float cosT = clamp(nl.z, 0., 1.), F0 = pow((uIor - 1.) / (uIor + 1.), 2.), Fr = F0 + (1. - F0) * pow(1. - cosT, 5.);
    vec3 Rv = reflect(vec3(0., 0., -1.), nl);
    // (the surroundings: one read of a deep mip level — only where the reflection is strong enough to see)
    vec3 sur = Fr * pres > .03 ? toLin(textureLod(uBase, st - Rv.xy * .1, 5.5).rgb) : toLin(col);
    // the whole reflection follows env (the key and sky terms used to ignore it and hazed glass over black footage ~20
    // levels grey; at env 1 this is exactly the previous shading)
    vec3 env = (sur * .6 + vec3(.95) * pow(max(dot(Rv, uL), 0.), 5.) * uLI + vec3(.05) * (.5 + .5 * Rv.z)) * uEnv;
    float face = dot(-inw, l2);
    float edge = exp(-max(d, 0.) / 1.7) * uRim * uLI * (.22 + .78 * pow(max(face, 0.), 1.6) + .5 * pow(max(-face, 0.), 2.));
    float sheen = pow(max(dot(nl, normalize(uL + vec3(0., 0., 1.))), 0.), mix(80., 34., clamp(frost / 16., 0., 1.))) * .35 * uLI * spec;
    float far = pow(max(dot(inw, l2), 0.), 2.) * smoothstep(.05, .6, 1. - cosT) * .16 * uLI * uRim;
    float inner = .06 * smoothstep(.1, .7, 1. - cosT);
    c = mix(c, env, Fr * pres);
    c *= 1. - inner * pres;
    c += vec3(edge * .85 + sheen + far) * pres;
    res = mix(outside, toSrgb(c), m);
    } }
    o = vec4(res, 1.);
  }`;
  let progN, progG, progC, UN = {}, UG = {}, UC = {}, texGB, texF, texFB, fbo, tileBuf;
  function build(fs, names, into) {
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
    gl.bindAttribLocation(p, gl.getAttribLocation(prog, 'p'), 'p');    // share the full-screen quad's attribute slot
    gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    names.forEach(n => into[n] = gl.getUniformLocation(p, n)); return p;
  }
  const tex2d = (min = gl.LINEAR) => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, min); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t; };
  function native(gtex, base, over, base2, mix) {
    if (!progN) progN = build(FS_NATIVE, ['uBase', 'uOver', 'uBase2', 'uMix', 'uH', 'uMixOn'], UN);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, W, H); gl.useProgram(progN);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.activeTexture(gl.TEXTURE0);
    if (gtex) gl.bindTexture(gl.TEXTURE_2D, gtex); else { gl.bindTexture(gl.TEXTURE_2D, texB); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, base); }
    if (base2) { gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, texB2); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, base2); }
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);          // the overlay stays premultiplied, exactly as the 2D canvas holds it
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texO); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, over);
    gl.uniform1i(UN.uBase, 0); gl.uniform1i(UN.uOver, 1); gl.uniform1i(UN.uBase2, 2); gl.uniform1f(UN.uMix, mix);
    gl.uniform1i(UN.uMixOn, base2 ? 1 : 0); gl.uniform1f(UN.uH, H);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.useProgram(prog);                                               // leave the graded program current, as init() did
  }
  // the glass pass: base (+ its mip chain) and the field → an offscreen RGBA8 texture, top-down like an uploaded canvas
  function glassPass(base, G, t) {
    if (!progG) {
      gl.getExtension('OES_texture_float_linear');
      progG = build(FS_GLASS, ['uBase', 'uF1', 'uF2', 'uF3', 'uRes', 'uShOff', 'uBox', 'uSig', 'uSigH', 'uIor', 'uGap', 'uThick', 'uShadow', 'uEnv',
        'uRim', 'uDispK', 'uT', 'uLI', 'uL', 'uND', 'uDome', 'uDK', 'uRimBlur'], UG);
      texGB = tex2d(gl.LINEAR_MIPMAP_LINEAR); texF = [tex2d(), tex2d(), tex2d()];
      texFB = tex2d(); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, W, H, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      fbo = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texFB, 0);
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      progC = build(FS_COPY, ['uBase'], UC); tileBuf = gl.createBuffer();
    }
    if (!G) return null;
    gl.useProgram(progG);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texB);          // never sample the render target
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, texGB);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, base); gl.generateMipmap(gl.TEXTURE_2D);
    [G.F1, G.F2, G.F3].forEach((a, k) => { gl.activeTexture(gl.TEXTURE4 + k); gl.bindTexture(gl.TEXTURE_2D, texF[k]);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, G.fw, G.fh, 0, gl.RGBA, gl.FLOAT, a); });
    const g = G.G, l2 = Math.hypot(G.L[0], G.L[1]) || 1;
    gl.uniform1i(UG.uBase, 3); gl.uniform1i(UG.uF1, 4); gl.uniform1i(UG.uF2, 5); gl.uniform1i(UG.uF3, 6);
    gl.uniform2f(UG.uRes, W, H); gl.uniform4f(UG.uBox, ...G.box);
    gl.uniform2f(UG.uShOff, -G.L[0] / l2 * g.shOff, -G.L[1] / l2 * g.shOff);
    gl.uniform1f(UG.uSig, G.sig); gl.uniform1f(UG.uSigH, G.sigH); gl.uniform1f(UG.uIor, g.ior); gl.uniform1f(UG.uGap, g.gap); gl.uniform1f(UG.uThick, g.thick);
    gl.uniform1f(UG.uShadow, g.shadow); gl.uniform1f(UG.uEnv, g.env); gl.uniform1f(UG.uRim, g.rim); gl.uniform1f(UG.uDispK, g.dispK);
    gl.uniform1f(UG.uT, t); gl.uniform1f(UG.uLI, G.LI); gl.uniform1f(UG.uRimBlur, g.rimBlur); gl.uniform3f(UG.uL, ...G.L);
    gl.uniform1i(UG.uND, G.nd); gl.uniform4fv(UG.uDome, G.domes); gl.uniform1fv(UG.uDK, G.kinds);
    // the base everywhere (a plain copy draw: cheaper than a blit on SwiftShader), then the glass shader on the tiles
    // that hold glass or its shadow only
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo); gl.viewport(0, 0, W, H);
    gl.useProgram(progC); gl.uniform1i(UC.uBase, 3); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); gl.useProgram(progG);
    if (G.tiles.length) {
      const loc = gl.getAttribLocation(prog, 'p'), quad = gl.getVertexAttrib(loc, gl.VERTEX_ATTRIB_ARRAY_BUFFER_BINDING);
      gl.bindBuffer(gl.ARRAY_BUFFER, tileBuf); gl.bufferData(gl.ARRAY_BUFFER, G.tiles, gl.STREAM_DRAW); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLES, 0, G.tiles.length / 2);
      gl.bindBuffer(gl.ARRAY_BUFFER, quad); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);   // the full-screen quad again
    }
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return texFB;
  }
  return { init, run, native: (base, over, base2 = null, mix = 0) => native(null, base, over, base2, mix) };
})();

// ---- looks. A scene returns a look; the print pass reads it. Clean projects (look.mode native/clean/clean-grade, the
// default) always print 'native' with the project accent. 'print' projects use the section looks below — calibrated on
// the reference video's print pass (mode = screen: grain | line | bit | dot; freq = screen pitch px; lift fades to paper).
// PROJECT.looks {name: overrides} adds or replaces entries; a shot's accent/screen/lift override the section look.
// Per-section accents (as calibrated): verse2 prints in the deeper 'ember' variant of the accent (INK.ember — the
// reference ember exactly for the default accent, else derived from look.accent in ENGINE.prepareData) and the bridge
// greys the accent out (#9a9a96). look.section_accents: false keeps the project accent in every section.
const PRINT_LOOKS = {
  hook:    { mode: 'grain', contrast: 1.35, gamma: 1.45, lift: 0,   grain: .13 },
  verse1:  { mode: 'grain', contrast: 1.3,  gamma: 1.35, lift: .02, grain: .12 },
  pre:     { mode: 'grain', contrast: 1.4,  gamma: 1.3,  lift: .04, grain: .1 },
  chorus:  { mode: 'line',  contrast: 1.2,  gamma: 1.2,  lift: .08, freq: 6, angle: 1.1, grain: .1 },
  verse2:  { mode: 'grain', accent: 'ember', contrast: 1.25, gamma: 1.2,  lift: .14, grain: .12 },
  chorus2: { mode: 'line',  contrast: 1.15, gamma: 1.1,  lift: .22, freq: 6, angle: .9, grain: .1 },
  bridge:  { mode: 'grain', accent: '#9a9a96', accentKeep: 0, contrast: 1.1, gamma: 1.0, lift: .42, grain: .08 },
  drop:    { mode: 'bit',   contrast: 1.3,  gamma: 1.0,  lift: .5 },
  final:   { mode: 'dot',   contrast: 1.1,  gamma: .95,  lift: .62, freq: 8 },
  outro:   { mode: 'dot',   contrast: 1.05, gamma: .9,   lift: .75, freq: 9 },
};
// a section name (intro, verse 2, chorus, pre-chorus, bridge, drop, final chorus, outro …) + its ordinal → a look key
function _lookKey(name, ordinal = 1) {
  const n = String(name || '').toLowerCase();
  if (PRINT_LOOKS[n] || ((window.PROJECT || {}).looks || {})[n]) return n;
  if (/hook|intro|open/.test(n)) return 'hook';
  if (/pre/.test(n)) return 'pre';
  if (/final|last/.test(n)) return 'final';
  if (/outro|end|coda/.test(n)) return 'outro';
  if (/drop|break/.test(n)) return 'drop';
  if (/bridge|middle/.test(n)) return 'bridge';
  if (/chorus|hook/.test(n)) return ordinal > 1 || /2|two|second/.test(n) ? 'chorus2' : 'chorus';
  if (/verse/.test(n)) return ordinal > 1 || /[2-9]|two|second|third/.test(n) ? 'verse2' : 'verse1';
  return 'verse1';
}
const _CLEAN = new Set(['native', 'clean', 'clean-grade', 'grade', '']);
// ENGINE.look(name | {section, ordinal} | null, overrides) → the look object a scene returns
ENGINE.look = function (name, over = {}) {
  const P = window.PROJECT || {}, PL = P.look || {}, accent = (over && over.accent) || PL.accent || INK.accent;
  const none = PL.accent === null;                 // look.accent null = no accent (core.js INK): no section accents,
  const projMode = String(PL.mode || 'native').toLowerCase();               // no accent protection in the print pass
  if (_CLEAN.has(projMode) || (over && over.mode === 'native')) {
    const o = { mode: 'native', accent }; if (over && over.focus) o.focus = over.focus; return o;   // colour keys are dropped
  }
  let key = name, ord = 1;
  if (name && typeof name === 'object') { key = name.section || name.name; ord = name.ordinal || 1; }
  key = _lookKey(key, ord);
  const tab = Object.assign({}, PRINT_LOOKS[key] || PRINT_LOOKS.verse1);
  if (PL.section_accents === false || none) delete tab.accent;
  const base = Object.assign(tab, (P.looks || {})[key] || {});
  if (base.accent === 'ember') base.accent = INK.ember;
  const out = Object.assign({ accent }, base, over || {}, { section: key });
  if (none && !(over && over.accent)) { out.accent = INK.accent; out.accentKeep = 0; }
  return out;
};
ENGINE.printLooks = PRINT_LOOKS;
ENGINE.lookKey = _lookKey;
