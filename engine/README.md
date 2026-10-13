# Claudia engine — the lyric-video renderer

A JavaScript engine that draws every frame of a lyric music video as a **pure function of song time `t`**, in headless
Chromium (software GL / SwiftShader, CPU only). `slop render …` (Python, `slop/render/`) drives it with Playwright and
encodes the frames. Ported from the reference videos' engine; every project-specific value was removed — the engine
reads everything from the project (`window.BEATS/LYR/CLIPS/EDL/PLATES/SHOTS/HITS` + `window.PROJECT`).

```
engine/
  index.html          the page: loads the project's data, the engine, the project layer, devices, the shots renderer
  src/core.js         clock (beat map), maths, colours, image loading, cover(), size (W×H, landscape or portrait)
  src/post.js         the one full-frame pass (WebGL2): 'native' (clean composite) or 'print' (grade + colour halftone)
  src/glass.js        liquid glass shapes refracting the footage (opt-in by use; free when unused)
  src/plate3d.js      2.5D: a still + its depth map with a moving camera (parallax occlusion)
  src/chrome.js       overlay language: fonts F, margins M, split-flap, countdown, garment tag, mass, corner chrome,
                      ENGINE.chrome() default chrome stack, ENGINE.leadKit()
  src/kinetic.js      KIN: lyric type modes (subtitle · coverline · masthead · stack), every token on its sung t0
  src/annot.js        ANN: brackets, callout, ticker, meter, crop marks, beat ruler
  src/trans.js        FX: base effects (smear, whip, flap) + transition presets FX.T (iris, zoom, match, push, luma,
                      bands, through, wrap, flashCut) and the transitions registry
  src/media.js        MEDIA: plates (2.5D or flat), clips (JPEG sequences), drawShot from the EDL, camFrom(words)
  src/hits.js         HIT / CAM: the camera plays the track (kicks, snares, impacts, risers, fills, stem envelopes)
  src/occ.js          OCC: type behind the subject (rotoscope matte or depth key); a no-op without matte/depth data
  src/ink.js          AINK: adaptive ink (white / near-black / accent / split / difference / mono)
  src/seq.js          MEDIA.drawSeq: RGBA image sequences (e.g. Blender renders) over the footage
  src/timeline.js     scenes, transitions, renderAt(t), window.frame/drawn, ENGINE (the API below), boot()
  src/shots.js        the data-driven default renderer (owned by the engine-devices module; NOT part of engine-core)
  src/devices/**      the device library (owned by the engine-devices module)
  fonts/              OFL faces + fonts.js manifest + licenses/ (one OFL text per family)
```

## Loading (how a project is rendered)

`engine/index.html?project=<file URL of the project dir>&w=1920&h=1080` — `slop render` builds this URL and also
injects `window.SLOP = {project, engine, w, h, assets, deviceFiles, data}` and `window.PROJECT` (a subset of
project.json) before the page runs. The page:

1. sets `<base href="<project>/engine/">` — every **relative** media path (plates, clip frames, mattes, fx sequences,
   chapter files) resolves against the project's `engine/` folder, exactly like the original per-project page;
2. loads the project's data scripts from `<project>/engine/` (or `<project>/engine/assets/`), any of:
   `project.js beats.js lyrics.js hits.js spectrum.js clips.js plates.js tracks.js fx.js shots.js edl.js`
   (written by `slop edit export`). When one is missing, `slop render` injects the raw contract JSON instead
   (`analysis/beats.json` → BEATS, `analysis/hits.json` → HITS, `board/shots.json` → SHOTS, `edit/edl.json` → EDL,
   `analysis/words.json` → LYR with one token per sung word);
3. loads the engine (`fonts/fonts.js`, then `src/core.js … src/timeline.js`) and calls `ENGINE.prepareData()`;
4. loads the project layer if present: `<project>/engine/common.js`, then `scenes.js`, `ch/_index.js` (bespoke chapter
   code; `ch/_index.js` may `document.write` its chapter files with relative paths);
5. loads the device library (`src/devices/index.js` if it exists — it loads its files in its own order; without it,
   `src/shots.js` loads its library itself, or, when `src/shots.js` is absent too, every `src/devices/**/*.js` in sorted
   order with `_base.js` first), then `src/shots.js`. `ENGINE.defaultShots()` then registers a scene for every
   storyboard shot no scene covers yet (and fills any gap): when `src/shots.js` is absent (or `SLOP_ENGINE_SHOTS=0`,
   `SLOP.shots = false`) that is the whole film — media + camera + every sung word as a subtitle + chrome — so it
   always renders end to end and passes the lyric gate;
6. `window.booted = ENGINE.boot()` (fonts loaded, POST initialised). The renderer awaits it, then calls
   `window.frame(t, q)` → JPEG data URL, or `window.drawn(t)` → the lyric tokens drawn (`t0.toFixed(2)` keys).

Size: `W×H` comes from `SLOP.w/h` or `?w=&h=` or `PROJECT.size` (default 1920×1080). Portrait (`H > W`, e.g.
1080×1920 for the 9:16 cut) switches to portrait margins and layouts (`ENGINE.PORTRAIT`), fits big type to the width
and centres the base layer on the subject (PLATES boxes / clip tracks).

## The data the engine reads (all optional; formats as in docs/ARCHITECTURE.md §4)

| global | from | used for |
|---|---|---|
| `BEATS` `{duration, beats[], downbeats[], tempo[{t,bpm}], sections[{name,t0,t1,energy}], rms24?}` | analysis/beats.json | the clock (`bpOf`, `beatAt`, `barAt`, `KIN.beatLen`), sections → looks/chrome; **variable tempo** |
| `LYR` `[{line, kind:'lyric'|'adlib', text, t0, t1, tokens:[{txt, t0, t1, st:''|'accent'|'strike', n}]}]` | words.json + display.txt | KIN lyric modes; lyric gate |
| `SHOTS` (or `SHOTLIST`) `{duration, chapters, shots[…]}` | board/shots.json | the default renderer (one scene per shot) |
| `EDL` `{shot_id: {segs:[{t0, clip, in, hold?}]} | {plate}}` | edit/edl.json | `MEDIA.drawShot` |
| `PLATES` `{name: {file?, depth?, matte?, depth_model?, subject_depth, boxes:{label:[x,y,w,h,score]}}}` | plate picks | plates (default file `assets/plates/<name>.jpg`, depth `<name>.depth.png`, matte `<name>.matte.png`) |
| `CLIPS` `{name: {n, fps, dir, matte?, depth?, depth_model?}}` | clip frames | clips: `<dir>/f00001.jpg …` (+ `matte/`, `depth/`) |
| `TRACK` `{clip: {label: [[x,y,w,h,score]|null per frame @12 fps]}}` | clip tracks | `m.box(label)` on clips |
| `HITS` (engine form `{kick, kick_s, snare, hat, impact[{t,s}], ride[[t0,hit]], fill[[t0,t1]], vox_on, env{…}, fps}` or the contract form `{kick, snare, hat, hits[{t,score}], risers[{t0,t1,land}], fills[{t0,t1}], vocal_entries, env24{…}}`) | analysis/hits.json | HIT/CAM; both forms are accepted |
| `FXSEQ`, `SPECTRUM` | optional | `MEDIA.drawSeq`, spectrum devices |
| `PROJECT` | project.json subset | name/title, fps, size, `look {mode, accent, fonts{lyric,micro,display}}`, `chrome {style, corner, counter, ticker[], label, serial, board{unit,mid,line,sub}}`, `lead {label}`, `looks {name: overrides}`, `depth_model`, `preload` |

**Depth licence rule.** Only Depth-Anything-V2-**Small** (Apache-2.0) derived depth is ever used. A depth map is used
only when the plate's / clip's `depth_model` (or `PROJECT.depth_model`) matches `/depth[-_ ]?anything.*v2.*small/i`
(and names no large/base/giant weights) — `slop edit export` stamps `depth-anything/Depth-Anything-V2-Small-hf`.
Unlabelled depth is unknown provenance and is drawn flat (`slop render info` lists it); depth naming any other model is
drawn flat and OCC treats it as having no depth (`ENGINE.depthOK(meta)`).

**Missing media is never silent.** Every required file that fails to load (a plate, a clip frame, a clip the EDL uses
but `CLIPS` lacks, a declared depth map or matte, a frame of a known fx sequence) is recorded once in
`ENGINE.missingMedia` (`[{src, why}]`, one `console.error` each) and marks the frame being drawn
(`ENGINE.frameMissing`). `ENGINE.checkMedia()` decodes every declared file up front. `slop render frames | stills |
sheet | vertical` stop with the list and the fix (`--allow-missing` draws placeholders for previews; `encode` refuses a
master drawn that way). Guessed paths (the default `assets/plates/<name>.depth.png`) and fx sequences with no manifest
are optional by contract. Without matte/depth data OCC is a no-op: `OCC.behind/between` draw the layer uncut,
`OCC.over/contours/outline` draw nothing.

## The frame contract

```js
scene(name, t0, t1, async (b, o, t, lt, dur) => look, prep?)   // == ENGINE.scene
```
`b` = base 2D context (footage and anything printed with it), `o` = overlay 2D context (type, chrome, graphics —
composited crisp), `t` = song time, `lt = t − t0`, `dur = t1 − t0`. Return a **look** (`ENGINE.look(...)`), optionally
with `focus: [x, y, w, h]` (the subject box, used by match/iris/zoom transitions).

**Purity.** Frames render in parallel and out of order: no state carried between frames, no `Math.random` (use
`hash(i)`, `hash2(a, b)`), no `Date`. Async only for loading media. Memos only for data derived from static media,
keyed by media name. `slop render check` runs the history check (frame B fresh vs after A in one page; > 40 levels
on any pixel fails).

**Time.** Never compute beats from a BPM: `bpOf(t)`, `beatAt(n)`, `barAt(n)`, `KIN.beatLen(t)`, `KIN.kick(t)`,
`KIN.kickBar(t)`, `pulse8(t)`, `ENGINE.time.beatsSince(t, t0)`. Words appear on their sung `t0` (never beat-snapped);
motion syncs to the beat. Every lyric drawer must call `KIN.mark(tk)` for each token it draws (lyric gate).

## window.ENGINE — the stable API (for src/shots.js, src/devices/**, chapter code)

```js
ENGINE.version                       // '1'
ENGINE.W, ENGINE.H, ENGINE.FPS, ENGINE.PORTRAIT, ENGINE.M (margins {l,t,r,b}), ENGINE.U (= min(W,H)/1080)
ENGINE.urls                          // {engine, project, projectEngine} (file URLs, '/'-terminated)
ENGINE.url(rel)                      // absolute URL of a project media path (relative to <project>/engine/)
ENGINE.project                       // window.PROJECT (always an object)
ENGINE.data                          // live getters: song (SONG), lyrics (LYR), shots (SHOTLIST), edl, plates, clips, hits, track

// scenes & layers
ENGINE.scene(name, t0, t1, draw, prep) -> scene        // register (sorted by t0); scene.trans = ENGINE.transitions.make(...)
ENGINE.scenes                        // the SCENES array
ENGINE.covered(t0, t1, tol = .05)    // true if a registered scene overlaps [t0, t1] by more than tol
ENGINE.findScene(name)
ENGINE.layers                        // {out, base, over} canvases (W×H). Draw only through the b/o contexts a scene receives.
ENGINE.mark(tk)                      // lyric QA mark (== KIN.mark)

// layers (the >= 3 ordered layers rule; counting only, never a pixel)
ENGINE.frameLayers()                 // the frame just drawn: {count, layers: [...], noted, shot, treatment} (null before
                                     //    the first frame); `slop render check --layers` samples it at every shot's mid-point
ENGINE.noteLayer(kind)               // bespoke chapter code declares a layer it draws itself: kind is one of
ENGINE.layerKinds                    //    media | graphic | annotation | micro | lyric | chrome (unknown kinds: one warning)
ENGINE.lastFrame                     // what the last frame used (images, lyric tokens, device frame, chrome/device calls)

// time
ENGINE.time = {bpOf, beatAt, barAt, timeAtBeat, beatLen, beatsSince, kick, kickBar, pulse, pulse8, exitOf,
               sectionAt(t) -> {name, t0, t1}|null, sectionIndex(t), resolve(key, shot)}
ENGINE.sectionAt(t) -> {i, n, s}     // index, count and section object from the beat map (chrome counters)
//   resolve(key): number (s) | 'shot.t0' | 'shot.t1' | {word:[line, tok]} | {word_end:[line, tok]} | {beat:n} | {bar:n}
//                 | {beats_after:[key, k]} | {eighth_after:[key, k]} | {hit:'kick'|'snare'|'impact'|…, near:s, win:.12}
//                 | {frame_nearest:key} | {add:[key, seconds]}   → seconds (null when unresolvable)

// media (MEDIA): every draw returns m = {map(u,v)->[x,y], box(label)->[x,y,w,h]|null, meta, matte(), depth()}
//   EXCEPT a missing plate: drawPlate / drawShot return null (draw your fallback, e.g. ENGINE.fallbackBase) — the file
//   is in ENGINE.missingMedia and the frame is refused by `slop render` unless --allow-missing. A clip with no frames
//   returns an m that maps the whole frame and draws nothing (also reported).
ENGINE.media.drawShot(ctx, shotId, t, cam) ; drawPlate(ctx, name, cam, t) ; drawClip(ctx, name, localT, cam)
ENGINE.media.camFrom(words, p, {amt, cx, cy, t}) ; drawSeq(ctx, name, lt, o) ; subject(plate|meta|shotId|clip, lt) -> {u, v, box, label}|null
//   m.score(label) -> the detection score of a box (plates: boxes[label][4]; clips: the track's score)
ENGINE.cam                           // CAM (punch, shake, ride, impact, whip, fx, cam, shot, plate, clip, smear)
ENGINE.hit                           // HIT (last, next, near, snap, between, count, env, envAvg, pulse, ride, inFill, impacts)
ENGINE.occ                           // OCC (behind, between, over, contours, outline, mask) — no-ops without data
ENGINE.ink                           // AINK (pick, fill, sample, split, invert)
ENGINE.depthOK(meta)                 // the Depth-Anything-V2-Small rule (labelled V2-Small only; unlabelled → false)
ENGINE.missingMedia                  // [{src, why}] required media that failed to load (getter)
ENGINE.frameMissing                  // the missing media the frame being drawn asked for (reset by every renderAt)
ENGINE.noteMissing(src, why)         // report a required file your code failed to load (devices loading their own media)
ENGINE.checkMedia() -> Promise       // decode every declared plate / clip end frame / depth / matte → missingMedia
loadImage(name, src, {optional})     // cached decode; a failure is reported unless optional (a guessed path)

// type
ENGINE.type.modes                    // {subtitle, coverline, masthead, stack, mass, auto} → fn(o, ln, t, opts, env)
//                                      aliases: sub, caption → subtitle · cover → coverline · mast → masthead · wall → mass
ENGINE.type.register(mode, fn)       // add or replace a lyric mode (it MUST call ENGINE.mark(tk) for every token drawn)
ENGINE.type.draw(mode, o, ln, t, opts = {}, env = {})   // unknown mode → subtitle (never lose a word)
ENGINE.fonts                         // F: role → CSS family ('"Space Grotesk"' …); ENGINE.font(ctx, size, role|family, weight, style)

// look, chrome, lead
ENGINE.look(nameOrSection, overrides) -> look   // 'native' projects → {mode:'native', accent}; 'print' → graded halftone looks
ENGINE.lookFor(shot) -> look         // by shot.section (or the beat-map section at shot.t0); chorus/verse ordinals, no time hard-codes
ENGINE.chrome(o, t, {color, accent, style:'full'|'minimal'|'none', look})   // the always-on chrome stack
ENGINE.leadKit(o, m, t, t0, {face, rows, label, color})                   // brackets on the lead (+ face, + one callout)
ENGINE.leadLabel(m) -> label|null    // the lead's detection label: PROJECT.lead.label, else subject / a person / a woman / a man …
ENGINE.safeRect() -> [x0, y0, x1, y1]   // inside the margins (portrait: clear of the platforms' UI)
ENGINE.fitBox(box, {maxW: .9, always}) -> box|null   // portrait: null for a box wider than maxW·W (no brackets), else the
//                                      box intersected with safeRect — use it for brackets/labels on subjects in 9:16
ENGINE.fallbackBase(b, t, look)      // a quiet gradient for a shot with no media yet (never a black hole)
ENGINE.printLooks, ENGINE.lookKey(sectionName, ordinal)                 // the print-look table and the section → key map
ENGINE.deepen(hex)                   // the 'ember' variant of an accent (verse2 in print looks); INK.ember follows look.accent
ENGINE.inkFor(look) -> {color, accent, light}                             // overlay ink for a look (dark ink on light looks)

// transitions (a scene's ENTRY, centred on its t0; p 0..1 with the cut at .5)
ENGINE.transitions.registry          // name → factory(params, t0) -> {type, dur, draw?}
//   built in: cut, dither, flap, smear, whip, flash (handled by timeline.js), and custom presets
//   iris, zoom, match, push, luma, bands, through, wrap (whip that wraps, no black edge), flashcut
ENGINE.transitions.register(name, factory)
ENGINE.transitions.make(spec, t0) -> trans|null  // spec: 'match' | 'dissolve…' (prose is regex-mapped) | {preset|type, dur, ...params}
ENGINE.transitions.set(sceneOrName, spec)        // make + assign scene.trans

// devices (the library lives in src/devices/**, owned by engine-devices)
ENGINE.devices                       // registry: kind → fn
ENGINE.registerDevice(kind, fn)      // fn(o, env) -> void | box | Promise ; draws on the overlay o (env.b = base)
//   env = {b, t, lt, dur, shot, m, params, spec, anchor (resolved [x,y,w,h] | [x,y] | null), t0, t1 (resolved),
//          key, look, color, accent}
ENGINE.drawDevice(spec, env) -> Promise   // resolves spec.anchor / spec.at|t0|t1 timing keys, calls the registered fn;
//                                           an unknown kind warns once and draws nothing (never throws)
ENGINE.anchor(spec, m) -> box|point|null  // {box:'a face'} | {track:'label'} | {uv:[u,v]} | {rect:[x,y,w,h]} | {xy:[x,y]}
//                                           | 'lead' | 'face' | 'subject'

// shots renderer
ENGINE.shotsRenderer                 // set by src/shots.js to claim the default renderer (e.g. 'devices-v1');
//                                      the page sets 'src/shots.js' if it registered scenes without claiming
ENGINE.defaultShots()                // the minimal stub: a scene for every shot no scene covers yet + gap fillers
//                                      (the whole film when src/shots.js is absent); 'engine-stub' when it drew any
ENGINE.prepareData()                 // normalise window data (called by the page before the project layer)
ENGINE.boot() -> Promise             // fonts + POST; window.booted
ENGINE.info()                        // {W, H, FPS, duration, beats, sections, lyrics, tokens, shots, scenes, shotsRenderer,
//                                      fontsFailed, missingMedia, depthUnlabelled, …}
window.sceneAt(t)                    // the scene name at t (contact-sheet labels)
```

Globals kept from the original engine (chapter code may use them): `W H FPS TAU SONG bpOf beatAt barAt beatN pulse
pulse8 clamp lerp seg ease easeOut easeIn easeInOut expoOut hash hash2 kf shake INK rgb IMG SEQ loadImage cover
F M font tracked hair flapBoard countdown garmentTag careSymbols barcode mass departures cornerChrome KIN ANN FX MEDIA
PLATE3D POST GLASS HIT CAM OCC AINK scene SCENES`. A project's `common.js` may define `look`, `chrome`, `leadKit`
(as the reference projects did); when it does not, the page binds them to `ENGINE.look/chrome/leadKit`.

**Removed: `GFX` (the original `src/gfx.js`).** engine-core does not load it, so chapter code written against the
original engine that calls `GFX.*` throws a ReferenceError. Use instead: `GFX.roundRect` → `ctx.roundRect(x, y, w, h, r)`
(Canvas 2D); `GFX.sparkPath` → `FX.sparkPath(ctx, x, y, r, o)`; `GFX.counter / terminal / chart / bubble / …` → the
device library: `ENGINE.drawDevice({kind, params, anchor, at}, env)` (kinds in `engine/DEVICES.md`).

## Fixes against the original engine (behaviour changes)

- No reference-video values in shared code: the song clock defaults to the data (no 132.7 BPM / 306.4 s fallback);
  chrome strings (section counter, corner, garment-tag serial/kicker, countdown unit, departures title, ticker) come
  from `PROJECT.chrome`; sections map to looks by name and ordinal (2nd chorus → chorus2), never by hard-coded times;
  the lead kit finds the lead by `PROJECT.lead.label` (else common person labels), not the reference lead's labels.
- `FX.T.match`: B's subject now lands exactly on A's: the centre is lerped; the scale is the subject-box ratio clamped to
  [1, 1.6] and, when the move needs room (e.g. A's subject is smaller or off-centre), raised just enough that the offset
  never uncovers a frame edge; the translation is clamped to the frame. Only when even 1.6× cannot reach A's spot does
  B land as close as the frame allows (the original could drift off target, show the frame edge, and shrank B below 1×).
- `renderAt`: a time in a gap between scenes (or past the end) draws the scene that just ended (the original drew the
  first scene); a look without a `mode` gets the project's default look; a `flash` transition in a native look flashes
  the overlay (native has no lift).
- `ANN.callout`: the leader draws over half a beat and rows type 3 characters per 16th (`{lead: 1, cps: 1}` = the old
  timing, which never finished on a one-bar shot).
- `ANN.ruler`: bar numbers come from the downbeat map (1-based); never negative or malformed ('0-3').
- `flapBoard` no longer leaks `textAlign = 'center'` / `textBaseline` to later draws.
- `mass()` flickers on eighths of the beat map (was a fixed-BPM eighth).
- `post.js` honours `accentKeep / accentTol / accentSat` in the print look (pixels near the accent hue keep their
  continuous colour through the screen and grain; `accentKeep: 0`, the default, is the previous output). This is not a
  fix of the colour pass: the reference look table set these keys but only the retired v1 mono pass read them; its
  accent mask is re-added here.
- Print looks keep the reference's per-section accents: verse2 prints in the deeper 'ember' accent (`INK.ember`,
  derived from `look.accent` with `ENGINE.deepen`; exactly the reference ember for the default accent) and the bridge
  greys the accent (#9a9a96). `look.section_accents: false` keeps one accent everywhere.
- Missing media is reported (`ENGINE.missingMedia`, `ENGINE.checkMedia()`), never silently replaced — the original threw
  and failed the frame; the port first swallowed the error (see "Missing media is never silent" above).
- Depth must be labelled Depth-Anything-V2-Small; unlabelled depth is drawn flat (the original trusted any depth file).
- Portrait: the lead kit fits its brackets into the margins (`ENGINE.fitBox`: none on a subject wider than 90 % of the
  frame) and `ANN.brackets(o.safe)` keeps label and confidence inside.
- Small numeric choices: `clipFrame` picks frame `floor(lt·fps + 1e-6)` (a time exactly on a frame boundary is that
  frame, not the one before, despite float error); the stub coverline's subject avoidance clamps its top to `M.t + size`
  (it could rise off the frame); the renderer's frame range is `[round(from·fps), ceil(to·fps))` (the original used
  `round(to·fps)`, dropping the last partial frame of a song that is not a whole number of frames long).
- `KIN.masthead` / `stack` fit the frame width (portrait and long words); positions scale with H.
- Fonts: Nimbus Sans → Space Grotesk (lyric face), Junicode → Instrument Serif, Pilcrow Rounded and Alchimia dropped.
- Frames are written as the browser's JPEG (q .95) directly (the original re-encoded them through PIL).

## Fonts

All OFL 1.1 (texts in `fonts/licenses/`): Barlow Condensed, Space Grotesk (lyric face; replaces Nimbus Sans Bold),
Geist (alternative grotesk), IBM Plex Mono, Share Tech Mono (RFN "Share"), Instrument Serif, Audiowide (RFN
"Audiowide"), Pilowlava, DINish / DINish Condensed, JetBrains Mono. IBM Plex declares the RFN "Plex". Do not modify and
redistribute a font under its reserved name.

## Rendering (`slop render …`)

```
slop render info                       # boot the page: scenes, lyrics, fonts, data files and fallbacks, page errors,
                                       #    MISSING MEDIA and unlabelled depth (ok:false when media/fonts are missing)
slop render sheet [--times a,b,… | --vertical]   # contact sheet (shot mid-points) -> render/sheet.jpg (ms/frame, ≤ 1500)
slop render lyrics [--vertical]        # lyric gate: N/N or it fails and lists the missing words (untimed words count)
slop render frames [--from s --to s --every N --workers K]   # -> render/frames/fNNNNN.jpg (resumable, q .95);
                                       #    frames drawn from inputs that changed since are discarded and redrawn
slop render encode [--review|--draft]  # -> out/master.mp4: x264 CRF 16, yuv420p, BT.709 primaries/matrix, sRGB transfer,
                                       #    tv range (stream + frame tags), AAC 256k from audio/song.wav, +faststart;
                                       #    needs EVERY frame from f00000 to the song's end, fresh; verified with ffprobe
                                       #    (tags, size, frame count, duration ± 1 frame, audio)
slop render check                      # flash check (≤ 3 flashes/s, WCAG 2.3.1) on out/master.mp4 + history check
slop render check --layers [--vertical]  # every shot's mid-point frame has >= 3 ordered layers -> render/layers.json
                                       #    (render/layers-vertical.json); a chapter scene that declared nothing with
                                       #    ENGINE.noteLayer is listed UNVERIFIED with a `render stills` command
slop render encode --share [--vertical]  # the chat copy under 190 MiB -> out/share.mp4 (a current master that fits is copied)
slop render clean [--keep-master|--dry]  # delete the frames once the master (and 9:16 cut) verify
slop render vertical                   # the 9:16 cut: re-render at 1080x1920 -> out/vertical.mp4
slop render vertical --method crop     # a PREVIEW cropped from the master frames -> out/vertical-crop.mp4 (draft)
```
`--allow-missing` (frames, stills, sheet, vertical) draws placeholders for missing media/fonts — previews only.
The lyric gate command is `slop render lyrics`. Long render commands write their progress to `$SLOP_PROGRESS_FILE`
(`command`, `step` k/n, `state`): only `done`, `stopped` or `failed` mean the command is over; `stage_done` /
`stage_stopped` mark one step of several. Run them as background jobs (`slop job start -- render frames …`).
Chromium flags: `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader --ignore-gpu-blocklist
--no-sandbox --allow-file-access-from-files`. Each worker is its own browser (~1.7 GiB RAM), recycled every 200 frames,
one retry per frame on a fresh page. `SLOP_ENGINE_SHOTS=0` renders with the engine's stub instead of `src/shots.js`.
