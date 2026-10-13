# 70 · Motion design: the layer that makes it a Claudia video

This is the engine layer drawn on top of the footage: every lyric word on its time, one explaining graphic per line, the
camera and the cuts playing the track, 2.5D treatments, type behind the subject, ink that adapts to the picture. In both
reference videos (*Escape Velocity*, "EV", 5:06, 141 shots; *Clodyssey (Superpersuasion)*, "SP", 3:11, 94 shots) this layer
is what turned Midjourney stills and Seedance clips into a film people rewatched. Read it before you write a storyboard's
graphics column, before you configure `shots.json` devices, and before any chapter code (Director tier).

Related docs: `40-storyboard.md` (shot grammar, the explaining-graphic column), `61-lipsync.md` (what the edit does with
sync), `80-review-qa.md` (the gates and the reviewer), `99-failures.md` (what went wrong and why), `examples/` (verbatim
exemplars).

Conventions: **MUST** = a gate or an audit fails without it. **SHOULD** = the owner of the reference videos flagged its
absence. Numbers are the calibrated values from the two videos; keep them unless a project decision in `DECISIONS.md`
overrides one, and write the override down.

---

## 0. The bar, in the owner's words (carry these into every brief, verbatim)

These quotes were pasted into every animator and reviewer prompt of both videos. Paste them into yours.

- "all this should be high effort: e.g. animate the lyric renderings to be on beat, have everything be quite dense"
- "adding all the programmatic graphics on top that are animated by you and on theme will be necessary to give it the
  Claude feel"
- "One big part of the magic of the videos I sent you were that you generated motion graphics and motion design, not just
  animated lyrics but things that fit the words being said to bring the words and theme to life, almost explaining the
  words with visuals"
- on 2.5D plates: "that's where we'll have to shine and be creative. depth to separate layers ofc, motion graphics
  galore, diversity so its not repetitive"
- on transitions: "interesting and intelligent transitions, like edgar wright level ... not solely cuts but things that
  work with the motion design or graphics - but also not overdone and amateurish."
- SP: "beautiful motion design, real depth mapping, i like rotoscopes and depth mapping to cover text + beautiful text that
  adapts to color of bg"
- SP: "editing and camera should feel really synced to the beat or sound effects … cuts and flashing on beat, should be in
  theme and part of the video for camera movements, dont need to force flashing. we should get to this high tier camera
  audio sync."
- SP: "its a lyric video - all the lyrics must be on screen"
- SP: "not just like having scenes be more busy with more motion design, but I want everything to be higher quality and
  better" · "it needs to be fairly dense, but it also needs to be intentional"

Replace or extend them with **your user's** verbatim words when you have them. The user's words win any conflict.

---

## 1. Ask before you design (three questions, every project)

Each of these cost the reference productions a full rework when it was assumed instead of asked. Ask the user, record the
answer in `project.json` and `DECISIONS.md`, and only then brief anyone.

| Question | Options | Where it goes | What happens if you guess |
|---|---|---|---|
| **1. The look** | `native` (footage exactly as generated) · `clean-grade` (footage graded toward one hero plate, no texture) · `print` (colour halftone/line/dot screens, grain, dither transitions) | `project.json` `look.mode`, `look.hero_plate` | EV v1 shipped a mono print look: "way too.. gray … loses the Midjourney magic" → a 3.5 h colour rework. The unreleased third video shipped a graded look: "some color grading looked insane … would prefer to use midjoureny native colors" → a full colour pass. SP's user rejected the halftone dot grid on sight: "keep it clean so it feels like imax". |
| **2. Density** | EV-dense (≥ 3 layers, "quite dense") · SP-budgeted (footage + 1 lyric block + 1 hero device + ≤ 2 CV marks + chrome) · sparse (≤ 1 element, stillness; "the user experience is none") | `DECISIONS.md`; the element budget in your brief | The third video's v1 was busiest where the music was quietest (picture motion 6.4 in a drumless section vs 2.0 in the chorus): "the entire thing is very off pace and off vibe with the song" → every chapter re-animated. |
| **3. The accent** | one hex (EV and SP: Claude clay `#D97757`) or mono (black/white) | `project.json` `look.accent` | The accent must not share the footage's hue: blue graphics over blue footage "clashes". Pick it *against* the footage. |

Also confirm before chapter work: the type faces (from the user's ranked fonts, `30-taste.md`), the lead-on-screen target
(EV ≥ 70 %, SP ≥ 60 % with a second character), and any taboo words (they go in `project.json` `"banned": [...]`, and `slop board audit` checks the whole board for them).

---

## 2. The frame contract (MUST, all tiers)

The engine renders offline in headless Chromium, one frame per 1/24 s, in parallel, **out of order**. So:

1. **Every frame is a pure function of song time `t`.** No state carried between frames, no `Math.random` (use
   `hash(i)` / `hash2(a,b)`), no `Date`. Async is only for loading media.
2. **Two canvases.** The **base** `b` holds footage and anything that must be graded/printed with it (and anything glass
   should bend). The **overlay** `o` holds type, chrome, annotations; it is composited crisp on top and never screened or
   dithered.
3. **Memos are allowed only for data derived from static media, keyed by media name, never by frame** (depth slices,
   masks, measured plate features). A re-rolled plate then falls back to its detections instead of drawing on the wrong
   spot. A memo must not depend on what was drawn first (a 2400 px image scaled down straight from decode draws
   differently the first time than from the decode cache: reduce it once, deterministically).
4. **Every canvas is software-backed** (`willReadFrequently`) and every scene starts from a reset context (transform,
   alpha, composite, dash, letterSpacing, textAlign, textBaseline, smoothing, filter, shadow). The engine does this; a
   chapter that makes its own scratch canvases must too. Chromium's GPU-backed 2D canvas under software GL kept the
   previous frame's overlay once frames got dense; it took ~2 h of bisecting to find.
5. **Per-frame pools** (occlusion layers, ink scratch) are rewound each frame.
6. **Frame quantisation.** A cut shows on the first frame at or after its time; an in-shot cut lands on the frame
   *nearest* the beat; on a hit frame the drop, the arrow and the smear start one frame before it; video may be up to
   one frame (≈ 23 ms) **ahead** of the sound, never behind. Helper: `nf(x) = x − 0.5/24`.
7. **Speed:** ≤ 1,500 ms per frame (the contact sheet prints it). Known costs under software GL: the 64-step 2.5D
   parallax shader ~0.5–1.1 s/frame; full-resolution canvas `filter: blur` ~0.5 s/frame; a 1-px `getImageData` GPU flush
   up to 1 s. Use depth slices (~30 ms), multiplanes, and blur-by-resampling instead (§11).
8. **Verify** with the history check (`80-review-qa.md` §6): frame B rendered fresh must equal frame B rendered after A
   (no pixel off by more than 40 levels).

---

## 3. The clock: words on the voice, motion on the beat (MUST)

- **Never use a fixed BPM.** Suno takes drift: EV accelerated 131.55 → 133.9 BPM, SP 129.19 → 132.09 BPM. All musical
  time goes through the beat map (`analysis/beats.json` → `window.BEATS`): `bpOf(t)` (float beat position), `beatAt(n)`,
  `barAt(n)`, `KIN.beatLen(t)` (the *local* beat length), `KIN.kick(t)` (1 on each beat, sharp decay), `KIN.kickBar(t)`
  (on downbeats), `pulse8(t)` (eighths), `ENGINE.time.beatsSince(t, t0)` (= `bpOf(t) − bpOf(t0)`; inside a device's
  draw function it is `x.bs(t)`).
- **A lyric token appears at its aligned `t0` exactly — never snapped to a beat.** "The *motion* syncs to the beat, the
  *word* to the voice." Entrances take ≤ 1/8 beat.
- **Graphics are animated in beats:** counters roll on 16ths, rows type per 16th (or faster on short shots), detections
  land on 32nds, crops cut on eighths, hairlines draw over one beat, micro chrome flickers on eighths.
- **Camera moves and cuts answer real sounds** from `analysis/hits.json` → `window.HITS` (§9), not just the grid.

The timing-key vocabulary every device uses: **W** a word's `t0`/`t1`; **B** the beat grid; **H** a track event (kick,
snare, impact, riser, fill, stem envelope); **F** a fixed song time; **T** a keyframe measured on a take's own frames.
Write the key next to every timed thing in your storyboard and code comments.

---

## 4. Layers and the element budget

**MUST (all looks): at least 3 ordered information layers per frame** — media + lyric + chrome + annotation/graphic.
"Ordered" means they sit on a grid with a clear reading order, not piled up. A **clean hero moment** (footage + lyric
only) is allowed for ≤ 2 bars and must be earned (the hook's first seconds, a held stare, an eyes-open bookend).

Then pick the budget the user chose in §1:

| Budget | Per frame | Use when |
|---|---|---|
| **EV-dense** | footage + lyric (often 2 modes) + chrome through-line + CV brackets + 1 callout + the explaining graphic + micro rows; ≥ 3 layers is the floor, 5–6 the norm | joke-dense spoken verses, a fashion-show premise with a count-down through-line |
| **SP-budgeted** (default) | footage + **one lyric block** + **one hero device** (a card, a plot, a post, a readout) + **≤ 2 CV marks** (brackets, tags, lock) + the chrome. Micro-type (sources, coordinates, translations) counts as texture, not a device, and stays **≤ 3 rows**. The accent colour on **≤ 2 elements**. | a narrative video; anything the user called "clean", "intentional" or "IMAX" |
| **Sparse** | footage + the lyric + minimal chrome (still 3 layers); about 70 % of the film carries no graphic element at all; at most 1 element on screen ("nothing, then words, then one glass object"); nothing locked to the beat; shots hold 2–4 bars; straight cuts on bar lines. Not every line gets an explaining graphic — write that override in `DECISIONS.md` | a chill song; the user said "slow", "intentional", "less busy" |

**Density follows the song.** Measure it: picture motion = mean absolute frame difference of the review copy at 160×90
grey (0–255), per section; song energy = per-section stem RMS and kick/hat onsets per bar. Busy picture over quiet music
reads as "off pace". The third video's fix halved the cuts (0.92 → 0.47 cuts/bar, mean shot 2.06 → 4.03 s) and slowed
in-shot motion until picture motion followed the music.

**Nothing covers the lyric (the engine's collision rule).** The toolkit's engine measures every lyric block on every
frame and keeps the other layers off it: panels move to a free spot (or shrink), CV labels ("LEAD · 01") flip to
another corner or are left off, chrome items on the block are taken out whole. A live Quick run had a CV bracket label
under a sung word; that can no longer happen. The rule is in `engine/DEVICES.md` §1, and the frame report says what
it did (`window.DEV_FRAME.lyricRect`, `.labels`, `.chrome`).

---

## 5. The explaining layer: one explaining graphic per lyric line (MUST)

Every lyric line gets, besides its kinetic type, **a motion graphic that shows what the line means**: the chart the number
implies, the UI the joke is about, the diagram of the mechanism, the label that classifies her, the counter that ticks
the stakes, the map of the place. This is the single biggest quality driver. The storyboard's `meme_visual` /
graphics column is the *starting* idea; push it further.

### 5.0 What the toolkit gives you (read this before you anchor anything)

> The reference videos ran a GPU pipeline that detected boxes (Grounding DINO), rotoscoped mattes (BiRefNet held by
> SAM 2.1) and tracked labels through every clip. **The toolkit ships none of that.** What a toolkit project has:
>
> | You have | From | So |
> |---|---|---|
> | a **depth map** per plate (Depth-Anything-V2-Small, CPU) | `slop edit export` (`<plate>.depth.png`, `subject_depth`) | 2.5D treatments, depth contours, and occlusion by **depth key** (`mode: 'auto'`, §12) on plate shots |
> | **no detected boxes**: `PLATES[name].boxes` holds only the boxes you name with `slop plates box` | `slop edit export` writes the named ones (else `{}`) | without one, `m.box('a face')` returns **null**; the anchors `{box: …}`, `{track: …}`, `'lead'`, `'face'` resolve to nothing: box-bound devices (`cv.bracket`, `cv.lock`, `cv.lead`) draw nothing, the others float in a free slot |
> | **no mattes** and no clip depth | — | `m.matte()` is null; `OCC.behind` draws the block uncut on clip shots |
>
> Anchor devices with what exists: `{uv: [u, v]}` or `{uv: [u, v, w, h]}` (a point or box in **image space**, 0–1,
> measured by eye on the plate, so it follows the camera), `{rect: [x, y, w, h]}` / `{xy: [x, y]}` (screen pixels),
> `{slot: 'right'}` (a free region away from the lyric), or `{keys: [[t, u, v, w, h], …]}` (a hand-measured track: song
> seconds, or take seconds when the device's key is `T`). If you need real boxes (for `m.box`, a `'lead'` anchor, match
> cuts that land subject on subject, or the 9:16 cut's subject centring), name them on the plate's picked image with
> `slop plates box p004 --label "a face" --uv 0.22,0.18,0.16,0.30` (`--label subject` is the lead box; then
> `slop edit export`). Chapter code can also write them in the project layer, `<project>/engine/common.js` (never in
> `engine/assets/plates.js`, which `slop edit export` rewrites):
>
> ```js
> // <project>/engine/common.js: hand-measured boxes, image space 0–1 [u, v, w, h, score]; measured on the plate by eye
> (() => {
>   const BOXES = { 'dadcap-cu': { 'a face': [.22, .18, .16, .30, 1], subject: [.12, .10, .38, .90, 1] } };
>   for (const [plate, b] of Object.entries(BOXES)) if (window.PLATES && PLATES[plate]) PLATES[plate].boxes = Object.assign({}, PLATES[plate].boxes, b);
> })();
> ```
>
> Clip shots have no boxes at all (no tracks): anchor on them with `uv`, `rect` or `keys`.

### 5.1 Rules for every explaining device

1. **It is the meaning of the line, drawn from the thing in frame.** A classifier disagrees with a billboard's copy; tally
   marks are scratched on the mast itself; the clock's own LED segments are re-lit as the P(doom) figure; a charging cable
   is coloured by distance from the rope it replaces. Couple the graphic to visible features (a hand-measured `uv` point or
   box, a keyed track, the depth map; §5.0), "as if when you were taking the picture, you lined it up perfectly to have the
   graphics fit".
2. **It enters on the word that names it** (timing key W): "hoax" → one inverted frame; "boom." → one inverted frame and
   a burst.
3. **It animates in beats** (`ENGINE.time.beatsSince(t, t0)`; `x.bs(t)` inside a device), never in seconds.
4. **It reads in one glance** on a phone. If it needs a second look, cut it down.
5. **It escalates across the film.** Recurring devices are a structure of their own (§5.4).
6. **Sources are cited on screen** in micro type: dates, "HIS WORDS", "(PARAPHRASE)", "ILLUSTRATIVE CURVE". Real people
   appear only inside posts labelled AI IMAGE, with their own dated words; never speaking, never given words they did not
   say.
7. **The biggest type in the frame is the lyric** — unless the device *is* the line (a full-frame safety-sign pictogram
   on a shouted order; the title on the title word).

### 5.2 The style languages (draw in these)

Device kinds below are the names `devices[].kind` takes in `board/shots.json` (the engine's registered kinds, in
`engine/src/devices/*.js`; each has a `doc` line and an `example`).

| Language | What it looks like | Typical devices (toolkit kinds) |
|---|---|---|
| **Information design** (the main one) | diagrams, charts, maps, annotated systems; explaining *is* the design | `chart` (the curve the line implies), `plot`, `sparkline`, `ecg`, `counter`, `gauge`, `tally`, `arrow`; FIG. n diagrams, plan views, step charts, waffles as chapter code |
| **Micrographics** | tiny technical type, outline marks and hairlines floating over the image; ~11 micro elements per lockup | `typed` (sources, dates), `marks` (crop marks, rulers, grids), `ticker`; coordinates, serials, scale bars |
| **Spec-label** | the label as composition: codes, serials, certification marks, field:value rows, barcodes | `label` (garment tag / care label as a "model card"), `sheet`, `stamp`, `strike`, `redact`; the engine helpers `garmentTag`, `careSymbols`, `barcode` |
| **Computer vision** | boxes, confidence scores, meshes, masks tied to what is in frame | `cv.bracket`, `cv.lock`, `cv.tag`, `callout`, `leader`, `cv.lead`, `cv.outline`, `ANN.brackets`; depth scans (§11). Anchor them as §5.0 says |
| **UI** | the interface the joke is about | `terminal` (a coding-agent session typed on the beat), `ui.chatbar`, `ui.chat`, `ui.chip` (the AI-label pill), `flap`, `departures`; X-post cards and feeds as chapter code |
| **Reproduction** (print look only) | xerox, halftone, 1-bit, thermal print, misregistration | the `xerox` treatment (§11), scan bars, dots that grow with the kick, thermal receipt bands |

### 5.3 How to invent the device for a line (checklist, in this order)

1. What does the line **claim**? Is there a number? → a counter, a chart, a gauge, a before/after strike.
2. What **interface** is the joke about? → draw that UI (terminal, post, chat, status page, usage bar).
3. What **object** in frame can carry it? → label it, measure it, classify it (CV box + a wrong/funny class name).
4. What **mechanism** is described? → a diagram (FIG. n), a flow, a plan view.
5. What **place**? → a map, coordinates, a route.
6. What **stakes**? → a readout that ticks (a load cell in kN, a countdown board, a meter).
7. Is it a callback? → re-use the earlier device one step further (§5.4).

Then write it in the storyboard as: device · anchor · entry word · beats · text rows. Example row (EV s025, line 7):
"`BARS (code): WEEKLY LIMIT 150 → 125 · +25% (struck) = −17%` · anchored right half · enters on 'Plus' · one token per
beat · footnote 'temporary 50% boost ended'".

### 5.4 Through-lines: devices that escalate (SHOULD; pick one in the brief)

A through-line device is what makes 100+ shots feel like one object. Make "pick a through-line" a required brief
question.

- **EV:** a split-flap board counting `18 MONTHS TO ESCAPE THE PERMANENT UNDERCLASS` down per "Look" (18 → 16 → 14 → … →
  06 on "six" → 03·02·01·00 on the sung words → `THERE IS NO UNDERCLASS` → `END OF SHOW`); a LOOK counter that only
  climbs; a ticker of live counters; CV brackets labelling her (`MODEL 01 · LOOK 04 · CONF 0.97`, the labels themselves are
  jokes).
- **SP:** a load cell on the rope (2.1 kN → 3.8 → 5.2 → 9.8 ⚠ → TIGHTER 20 kN: "persuasion measured as a physical force");
  a four-pictogram safety card that flashes on every shouted order and is finally redrawn; an instance counter
  (×1 → ×1,024 → ×8,192 with a 2ⁿ plot); the P(doom) figure; the last frame equals the first (the loop).
- **Payoffs land on their words:** the board flips to 06 on "six"; 11.2 KM/S lands on "eleven"; 3·2·1·0 on their words.

### 5.5 Examples that worked (line → device)

| Line (video) | Device | Why it worked |
|---|---|---|
| "Sorry. Encore." (EV) | `APOLOGY METER · VIA BOW` gauge (0° UPRIGHT / 30° SORRY / 60° DEEP) reading 19° | the bow is in the footage; the gauge measures it |
| "No grades, no tests" (EV) | a garment-tag card `ACADEMY [NO DEGREE] TRANSCRIPT` while she tears a sheet | the spec-label language carries the joke |
| "Feel the AGI" (EV) | a seismograph `M 9.0 · OFF SCALE ▸ PEN AT STOP` over her singing close-up | the number makes the feeling literal |
| "Impossible puzzles" (EV) | a CV wireframe impossible triangle on the object in her hands + `PASS RATE 0.00 % · SOLVABLE FALSE` | CV on a real object; the stats are the punchline |
| "gambling with our lives" (EV) | a 3-reel slot machine built from crops of the plate; the reels stop on 'with' / 'our' / 'lives.' | stills-in-rhythm *is* the device; stops on words |
| "(It's so over?)" (EV) | a poll card `IT'S SO: SO OVER 67% / SO BACK 33%` that every answer swings, closing at 3 % / 97 % on the last BACK! | escalates across the chorus |
| "This voice? Not a real person." (SP) | the streaming apps' AI chip on her eye: `AI PERSONA` → `AI PERSONA · THIS VOICE DOES NOT REPRESENT A REAL PERSON` | a real-world UI label, typed on the spoken words |
| "Why would I deceive you?" (SP) | the Greek source under the lyric (Odyssey 12.184–185) with its translation, typed on 16ths | explains the myth for viewers who don't know it |
| the drop (SP, no words) | ×1 → ×8 counter and 2ⁿ plot while plates of 1, 2, 4, 8 copies swap on beats | "one AI, copied" in one glance |
| "Chrome in your blood. Cyber-psychosis." (SP) | a skeletal molecule drawn bond by bond + a CYBERPSYCHOSIS card with a progress readout | the chemistry joke is drawn, not stated |

More, shot by shot, in `examples/shots-json.md` and the per-device catalogue of `engine/DEVICES.md` (until that file
exists: `engine/README.md` for the engine API, and the `doc` and `example` fields of each `D.register(…)` in
`engine/src/devices/*.js` for the devices).

---

## 6. Type system

### 6.1 Roles and faces

| Role | What it carries | Face (token) | Size @1080p | Setting |
|---|---|---|---|---|
| **Her voice / the lyric** | subtitles, coverlines, stacks, UI text | a neutral grotesk, bold (`F.grotesk`; in device code `DEV.TY().grot`) | sub **46** (SP) / 40 (EV); cover **76–96**; stack: fit to width | title case as sung; −0.012 em (sub), −0.03 em (cover) |
| **Micro** | labels, readouts, CV, chrome, kickers, sources | a mono (`F.mono`; both videos used IBM Plex Mono, OFL) | **12–15** | CAPS, +0.06 to +0.16 em |
| **Display / masthead** | one giant word, stacks, counters | a condensed display face (`F.display`, or `F.sign` for signage; EV used Barlow Condensed, SP DINish Condensed, both OFL) | masthead **300** (EV 7–19 % of frame height); counters 180–260; up to 460 | CAPS, −0.005 to −0.02 em |
| **Flaps / counters** (EV) | split-flap boards, odometers | a technical mono (`F.tech`; EV: Share Tech Mono, OFL) | per device | |
| **Wildcard** (one per film) | one word at a time in the drop | one display face from the user's ranked list | masthead | sparingly |

Rules:
- **Faces come from the user's ranked fonts** (`30-taste.md`, the font A/B). Write *why* each face was chosen (SP: the
  signage face sets the shouted orders "literally as a sign", and condensed letters are ~1.6× taller at the same width so
  her face shows through more of a title knockout).
- **Ship only OFL fonts.** The originals used Nimbus Sans (AGPL; not shipped), Junicode 0.6 (GPL; not shipped), Pilcrow
  Rounded (Fontshare EULA; not shipped) and Alchimia (no licence; not shipped). The toolkit's `engine/fonts/` holds OFL
  faces with their licence texts (`fonts.js` maps the roles: grotesk = Space Grotesk, alt = Geist, mono = IBM Plex Mono,
  display = Barlow Condensed, sign = DINish Condensed, tech = Share Tech Mono). Override per project with
  `project.json` `look.fonts {lyric, micro, display}`; draw with the tokens, never a file name.
- **≤ 3 faces in one frame.** Weights **≥ 400 on footage**. Lighter weights beat heavier (the user's A/B picks went 21–13
  for lighter).
- A sequel never reuses the previous video's display faces (SP banned EV's).

### 6.2 The lyric modes (every sung word MUST appear in at least one)

In `board/shots.json` a shot's `type[]` names the mode (`{line, mode, text, placement}`) and the default renderer
draws it. In chapter code call the device library's lyric functions inside a scene's draw function (`LY.sub`,
`LY.cover`, `LY.mast`, `LY.stack`, all `(o, b, line, t, opts)`, `line` from `KIN.byLine(n)`), or
`ENGINE.type.draw(mode, o, line, t, opts)`. Both mark every token they draw for the lyric gate. (The reference videos
called the same modes `KIN.subtitle`, `KIN.coverline`, `KIN.mastheadLine`, `KIN.stack`; those still exist in the
engine core.)

| Mode | Chapter-code call (toolkit) | For | Behaviour |
|---|---|---|---|
| **subtitle** | `LY.sub(o, b, line, t, {x, y, size: 46, w, breaks})` | sung lines, calls, the default | low left on the margin axis (x = 72, y = H − 84 EV / H − 124 SP), wrap 0.62·W; words rise in over 1/16 (EV: mask wipe up); the sung word in the accent (karaoke) from `t0` to `t1 + 0.05`; a micro label above (`L07 · 00:44:05`) |
| **coverline** | `LY.cover(o, b, line, t, {size: 84–96, kicker, micro: [rows], avoid})` | spoken, deadpan lines beside her | the editorial lockup in the plate's declared empty field, hung from something visible; tracking collapses +0.35 em → −0.03 em per word (expo-out); 1-frame accent flash on entry; breathes 1 + 0.014·kick; a hairline draws over the first beat; micro rows typed one character per 16th; `avoid: [x, y, w, h]` (her screen box: a hand-measured box, §5.0) hangs it from the other margin with 40 px clearance |
| **masthead** | `LY.mast(o, b, line, t, {size, align, accumulate, flash: 'block'})` | payoff words, chorus answers, numerals, shouted orders | one giant token per word, hard cut on its time; first frame = an accent block behind it (1 frame); slow scale drift 0.03; only over a quiet patch of the picture |
| **stack** | `LY.stack(o, b, line, t, {maxSize: 420})` | short emphatic lines (IT / WAS / THAT / GOOD!) | a justified column; each word rises in on its time; +8 %/row (EV) |
| **mass** | `type[].mode: "mass"`, or the engine helper `mass(o, lines, x, y, t, t0, {rows: 40, keep, density: .75})` plus the sung line as a subtitle | the drop; declared illegibility | a declared wall of ≥ 12 rows of micro text flickering on eighths with one kept row, plus one big word at a time ("way too much text that you can't even read … works" — illegibility only when deliberate). The wall draws no lyric tokens: the sung line must still be drawn (the `mass` mode adds it as a subtitle) |
| **title** | the device kind `title.knockout` (`{kind: "title.knockout", key: "W", params: {word, token: [line, i]}}`) | the title word | the title cut out of black so the footage shows only through the letters; the sung token (`token`) appears under it on its time and is marked for the gate (without `token`, draw the word in another mode too) |
| **post caption** | draw it in the card and call `KIN.mark(tk)` per token | a lyric shown as a social post's caption | must still mark every token |

**Choosing a mode:** emphasis words, numbers and meme keywords get masthead/stack; long spoken lines get coverlines; sung
lines get subtitles; the call of a call-and-response is a small grey subtitle and the answer is the masthead.

### 6.3 Timing and layout rules (MUST unless marked)

- A token appears at `tk.t0` exactly. The entrance takes ≤ 1/8 beat.
- A line exits at `KIN.exitOf(line)` = the next downbeat after `t1 + 0.05`, or the next line's `t0 − 0.02` if sooner, at
  most `t1 + 2.5`. Then it fades over ~0.15–0.2 s.
- **One lyric block per frame** (plus source micro-type). **A line is one mode and one position, held across cuts.**
- Type breathes with the kick: a 1–2 % scale punch decaying within the beat.
- **Lyric ≥ 40 px** carrying the line (SP minimum for subtitles: 46). At least one lyric element per frame must be
  readable on a phone.
- **Margins `M = {l: 72, t: 56, r: 96, b: 84}`** — unequal on purpose. **Hang type from the left axis (x = 72) or from a
  feature in frame; never centre by default.** Lockup centre in the 15–35 % / 65–85 % horizontal bands; a lockup ≤ 8 % of
  the canvas.
- **Nothing important under y > 1030** (the ticker band) or under the corner chrome.
- **Never over her face** (no marks across eyes or mouth; brackets frame, they do not cover). Where type crosses her it is
  drawn behind her (occlusion, §12) or as a difference of the ground.
- **Display tokens are the joke, not the phonetics.** `lyrics/display.txt` maps sung words to what is read:
  `+25%|3 =|1 −17%|2` shows "+25% = −17%" over the sung words "Plus twenty-five is minus seventeen";
  `AGI|3` shows AGI over "A G I". A line must consume exactly its aligned words (the export fails loudly otherwise).
  Accent `*x*`, strike `~x~`, mono `_x_`, `|0` = rides on the next token.
- **Every token you draw yourself MUST call `KIN.mark(tk)`** or the lyric gate cannot see it.
- Short shots: default typing speeds (1 char per 16th) never finish on a one-beat shot. Every tag must finish **≥ 6 frames
  before its cut**: raise characters-per-second (SP used ≥ 16–40 cps on short shots) or shorten the text.

---

## 7. Colour and accent rules

- **The footage keeps its colour.** Never desaturate the base: no saturation fills, no grayscale filters on plates or
  clips, no white lift, no tint washes painted on the overlay over footage. (EV v1 desaturated by hand for a
  one-accent rule and was "way too gray".)
- **Graphics carry one accent.** EV: one accent per chapter. SP: white `#F5F3EE`, near-black `#0B0C0E` and orange
  `#D97757` only, **orange on ≤ 2 elements at a time**: the sung word, the live head of a chart, a pointer, the newest ring.
- **The accent must not share the footage's hue.** If the footage is blue, a blue accent "clashes"; go mono.
- **Semantic colour tokens only**, never literals in chapter code, so a late palette change is one line. In the toolkit:
  `DEV.C.light`, `DEV.C.dark` and `DEV.C.accent` (device and chapter code), `INK.accent` (the engine core), the project's
  `look.accent`, and `ENGINE.inkFor(look)` for the overlay ink of a look. (EV's chapters used their own ink keys, SP's a
  colour table; same idea.)
- **Physical-object colours stay physical:** standard sign colours (ISO blue `#1C5CA8`, red `#C8161D`, yellow `#F4B400`,
  enamel `#F1EDE3`) only on placards and signs that exist in the world; app UI greys only inside a phone UI.
- **Banned:** neon, glows, gradients as decoration, drop shadows, bevels, rainbow/holographic/synthwave palettes,
  orange on orange (skin, the hair streak, a lamp).

---

## 8. Looks: native, clean grade, print (ask the user — §1)

| | **native** | **clean-grade** (SP) | **print** (EV) |
|---|---|---|---|
| What the post pass does | composites the overlay over unresampled base pixels; nothing else (proven bit-identical to source frames) | the same composite; the grade is baked into plates and clip frames at import | colour grade + four-plate CMYK halftone/line/dot screen + grain + misregistration, mixed with the continuous image |
| Grade | none | plate Lab a/b mean and spread moved toward the **hero plate** by strength 0.65; lightness keeps its shape (contrast borrowed at 0.25); saturated oranges (hue 22–72°, chroma ramp 30–52) keep their colour, pulled 30 % toward the accent, ×1.12 | S-curve contrast that never clips, gamma 0.9–1.1, saturation 1.15, highlight roll-off |
| Clips | as generated | one 52³ 3D LUT per clip from 16 sampled frames, applied with ffmpeg `lut3d` at import: the same transform on every frame, so no flicker (0.49 levels mean abs diff vs per-frame grade) | per chapter look keys |
| Texture | none | none (MJ's own grain is kept) | grain cell 2 px boiling at 12 fps; screen 0.42 (grain) / 0.55 (line) / 0.68 (bold dots) / 0.60 (dot); pitches 4.2 / 6 / 8.5 / 7 px; 2 px misregistration on two plates; vignette ≤ 0.2 |
| Transitions | `dither` becomes a crossfade; `flash` does nothing | same | 8×8 Bayer ordered-dither dissolve inside the shader |
| When | the user wants "Midjourney native colours" | the user names a hero plate ("s018 color is PERFECT") and wants "clean", "IMAX" | the user asks for xerox / dither / halftone / print / "camera effects" |

**The grey-takes lesson (MUST).** EV pre-graded its Seedance reference images to a mono print look so they would pass a
provider face filter. Seedance keeps the reference's colour, so 32 of 59 clips came back near-grey; fixing it took a
colourisation pass. **A look applied at generation time is baked in. Keep generation inputs in colour (ungraded or a mild
contrast/grain pre-grade: k 1.1, grain 0.03) and apply the look in post.** The thumbnails the user reviews are rebuilt
with the project grade whenever a plate or the look changes, so they always review graded frames.

**EV's print look, per section** (keep these numbers if the user picks print):

| look | mode | contrast | gamma | lift | other |
|---|---|---|---|---|---|
| hook | grain | 1.35 | 1.45 | 0 | grain .13 |
| verse 1 | grain | 1.3 | 1.35 | .02 | grain .12 |
| pre-chorus | grain | 1.4 | 1.3 | .04 | grain .1 |
| chorus | line | 1.2 | 1.2 | .08 | freq 6, angle 1.1 |
| verse 2 | grain | 1.25 | 1.2 | .14 | accent ember `#db5c34` |
| chorus 2 | line | 1.15 | 1.1 | .22 | freq 6, angle .9 |
| bridge | grain | 1.1 | 1.0 | .42 | mono ink |
| drop | bit (bold dots) | 1.3 | 1.0 | .5 | ink on paper |
| final chorus | dot | 1.1 | .95 | .62 | freq 8 |
| outro | dot | 1.05 | .9 | .75 | freq 9 |

The pass damps chapter values (exposure → clamp(1 + (e−1)·0.3, 0.85, 1.35); contrast → clamp(1.2 + (c−1.35)·0.4, 1, 1.45);
gamma → clamp(1 + (g−1.45)·0.15, 0.9, 1.1); lift → smoothstep(0.8, 1, lift)), so a chapter cannot blow out the footage.
EV's "white-pill" arc raised `lift` continuously from 0 (night) to 1 (paper) and never let it fall back; lyric type and
chrome were never screened. One screen per chapter (grain in verses, line in choruses, bold dots in the drop, dot in the
outro). In the print look the pass also honours `accentKeep`, `accentTol` and `accentSat`: pixels near the accent hue
keep their continuous colour through the screen and the grain (the original engine ignored these keys; the toolkit's
`post.js` reads them). The default `accentKeep: 0` changes nothing; native and clean looks drop all colour keys.

**What native/clean cannot stop:** washes a chapter paints on the overlay. In native and clean looks, chapters must not
paint light, tint or white bands over the footage (put scans and light bands on the base through the depth map, §11,
or use glass, §14).

---

## 9. The camera plays the track (hits-driven camera)

`slop analyze` writes `analysis/hits.json` (the engine's `window.HITS`): kick, snare and hat onsets (band-limited spectral
flux; onsets within 45 ms of a broadband kick are dropped from snare and hat), **real hits** (energy steps snapped to
downbeats, with a strength), **risers** and the hit each one rides into, **fills** (the lead-in beat before a real hit),
vocal entries, and 24 fps envelopes per stem. Add a hit the detector missed in `project.json` (`"audio": {"hits": {"add": [[170.7, 0.8]], "drop": []}}`; `drop` lists times) — SP's loudest bar grew out of an already loud chorus and had to be added by hand.

### 9.1 The moves (defaults from SP; image or screen space, edges never show)

```js
const m = await CAM.shot(b, 's045', t, { zoom: 1.08, cx: .5, cy: .45, focus: .8 },          // framing
  { impact: { amp: .07 }, punch: { amp: .02 }, shake: { amp: 5 }, ride: { amp: .06 } });  // moves
```

| Move | Answers | Defaults | Notes |
|---|---|---|---|
| `punch` | each kick (or `kind: 'vox'` for a vocal entry) | amp .02 (use .01–.03), attack .03 s, decay τ .13 s, gated by the drum envelope (.35 + env·1.2), `every: 2|4` | no punch where the drums are out |
| `shake` | the drum envelope | 6 px, rotation .002 rad, 7 Hz smooth noise, scaled by drum env^1.6 | never in UI shots |
| `ride` | a riser | amp .06, curve 2.2; pushes into its hit, snaps back over .09 s (or holds) | the a cappella line into the drop |
| `impact` | a real hit | minimum strength .6, zoom kick .06, attack .035, τ .3, shake burst 14 px decaying over .22 s, rotation .006; `.flash` is true on the hit frame | the drop, the section starts |
| `whip` | a fill, a head turn | `{at, dir, dist: 520, blur: 180, dur: .24}` | wraps, no black edge |
| snap zoom | a beat, in-shot | two-frame overshoot `zoom += .09·e^(−age/.045)`, alternate dx ±18 px | screens into screens |

Helpers: `HIT.snap(t, 'kick')` (put a cut or key on the nearest hit), `HIT.last/next/near/between`, `HIT.pulse(t, 'kick')`,
`HIT.env(t, stem)`, `HIT.progress(t, t0, t1, 'other')` (a move whose speed is the music's loudness: SP's opening dive rides
the synth swell).

Without hits (EV, or a quick render), use storyboard camera words through `MEDIA.camFrom`: push/dolly in → zoom 1.04 →
1.16; pull/reveal → 1.16 → 1.04; pan → x ±.018, cx ±.03; tilt/crane → y ±.012, cy ±.04; orbit → x sin·.02, rot ±.01;
static → zoom 1.05 → 1.07; handheld → shake .004. Add `zoom += .02·KIN.kickBar(t)` for downbeat punches.

### 9.2 Rules (MUST)

- **A camera move answers a sound you can hear.** No punches where the drums are out; no shake in UI/phone shots.
- **Hold the camera still where the song breathes — stillness is part of the sync.** A cappella lines, held notes, the
  title word ("stillness on 'Superpersuasion'").
- Cuts land on beats or hits, from the beat map.
- **A move never cuts the face.** The engine's 2.5D camera keeps the plate's face box in frame through pushes, zooms,
  shakes and impacts (it calms a shake only as much as the face needs; `window.DEV_FRAME.face`, `.faceCalm`), and
  `stills` crops do the same; `"face_safe": false` on the treatment turns it off for a shot that wants the crop
  (`engine/DEVICES.md` §6).
- Before chapter work, write a **per-section sync table** from `analysis/report.md` (stem energy per bar, drop-outs, hits)
  into the brief. SP's, abridged:

| Section | What the track does | Camera and cutting |
|---|---|---|
| Intro (0–10.72) | no drums, a synth swell (riser 2.25→5.83), a cappella line (riser 9.83→10.72) | slow pushes and rides only; no punches, no shake; cuts on bar lines |
| The drop (10.72–17.93) | four on the floor | impact on 10.72 (the first flash); punch every kick; drum shake; snap zooms on beats |
| Verse 1 | thin drums, then a real hit at 25.57 | UI shots: the feed scrolls and snaps on the beat, no shake; punch .01 until the hit, .018 after; cut on the names |
| Chorus 1 | a cappella bar, full from the hit at 44.10 with shouts | hold on the sung question; ride into 44.10; impact + a pictogram flash on each shouted order; stillness on the title word |
| Verse 2 | bouncy; the beat stops at 66.25, back at 68.09 | punch every kick, offbeat sway; **freeze-frame on the stop**; impact on the line that answers it |
| Instrumental | 4 bars | locked top-down; oars cut on downbeats; sonar pings on beats |
| Verse 3 | bass out, back at 128.75 | strobe cuts on beats (≤ 3 full flashes/s, the rest small glints); punches small until the bass returns |
| Final chorus | loudest bar at 170.70 | the flip flicker on quarters (< 3/s); impacts on the two hits; stillness on the title word |
| Outro | hits at 174.34, 181.58, 185.23 | quarter-note flashes (2.2/s); the pull-up on 181.58; hold the stop |

---

## 10. Cutting, transitions and Edgar-Wright-level sync

### 10.1 Cutting (MUST)

- **Hard cuts on the beat are the default.** Every cut within **0.03 s** of a beat in the beat map (or a declared hit);
  where a word would straddle a cut, move the cut by ≤ 0.028 s (under one frame) so the word stays whole.
- Shot length follows the song: mean ~2 s ≈ one bar. EV: fastest in the hook (1.33 s) and the joke-dense verse (1.62 s);
  **longer on sung chorus windows (2.69 s: lip sync needs time to settle)**; fast again in the drop (1.58 s plus eighth-note strobes
  inside shots); long ring-out (4.40 s).
- The hook: the first 3 s are a hook, not a wait. "Each bar brings one new piece of information, and nothing sung appears
  early." **One-second test:** the frame at 1.0 s shows the lead's face, her signature detail and a readable line on a
  muted phone.

### 10.2 Transitions are ideas (SHOULD)

"A transition is a *joke or an idea*." **Mostly hard cuts on the beat; a clever, motivated transition every few shots;
never the same device twice in a row; each lands on a beat.** EV used 49 designed entry transitions in 141 shots (a 1-in-3
rate, almost all bespoke); SP 20 in 94 (1-in-5). Everything else was a hard cut.

The patterns (each picks up something the outgoing shot explained):

| Pattern | Examples that shipped |
|---|---|
| **The graphic of one shot becomes the frame of the next** | an ECG curve leaves its card and becomes the wipe edge; a detection box lerps into the next billboard's box; BACK!'s letters fly as flap cells into the next sign |
| **Push through an object** into the next scene | her pupil becomes the hole in the clouds; push ×9 into a garment tag, emerge from a billboard; through the ear, the phone, the check mark, the mast |
| **Match cut on shape, position or motion** | her face lands where the car's lidar was; flip-pair plates with identical framing and swapped roles, cut on quarter notes |
| **The object's own mechanism** | split-flap tile wipe (16×9 flaps in a wave); the tag's barcode stripes wipe to the next look; a steel roller shutter; a paper tear; a thermal print head prints the next shot |
| **Continue a move** | a whip that continues her head turn (wraps, no black edge) |
| **Sound-led** | a one-frame inverted flash cut on a hit (the `flashcut` preset); a one-frame paper burn (the `flash` device, `flash.paper`) |
| **Screens inside screens** | draw the next shot's UI on the screen you push into |

Engine presets (the names `transition_in` takes in `board/shots.json`, and `preset` in chapter code):
`cut`, `dither`, `flap`, `smear`, `whip`, `flash`, and `iris {shape: 'spark'|'circle', at}`, `zoom {depth}`, `match`,
`push {dir}`, `luma {invert}`, `bands {n}`, `through {a, b, depth}`, `wrap {dir, dist, blur}` (a whip that wraps, no black
edge), `flashcut {invert, frames}`. In chapter code set a scene's entry with
`ENGINE.transitions.set('s042', {preset: 'through', dur: .4, a: [960, 520], b: [960, 540]})`; the draw functions
themselves are `FX.T.iris(…)`, `FX.T.zoom(…)`, `FX.T.match(…)`, `FX.T.push(…)`, `FX.T.luma(…)`, `FX.T.bands(…)`,
`FX.T.through(…)`, `FX.T.wrap(…)`, `FX.T.flashCut(…)`. Write a custom one when the idea needs it:
`ENGINE.transitions.set('s042', {type: 'custom', dur: .5, draw: (p, c) => …})` with `p` 0..1 and the cut at 0.5;
`c.a/ao/b/bo` are both shots' base and overlay canvases and `c.base`/`c.over` the output; return the look to print with
(`c.la` or `c.lb`). `match`, `zoom` and `iris` centre on each scene's `look.focus` (its subject box, `[x, y, w, h]` in
screen pixels); without boxes (§5.0) give a scene a focus by hand or use `through` with explicit `a`/`b` points.
`FX.T.match` landing B's subject off target was a bug of the original engine; it is fixed in the toolkit's engine (the
centre is lerped, the scale clamped, no frame edge shows), but still check the middle frame of every match.

### 10.3 Edgar-Wright-level sync: the checklist

"High tier camera audio sync" is many small alignments, each measurable:

1. Every cut on a beat or a hit (audit, §10.1).
2. Every camera move answers a named sound (§9); list the 10 biggest moves of a chapter and the nearest hit for each.
3. Things in the footage move on the music: write the kick times into the video prompts so waves burst, oars bite,
   strobes fire on them (`60-clips.md`, screenplay grammar).
4. In-shot cuts on eighths (stills in rhythm), counters on 16ths, detections on 32nds.
5. Freeze or hold where the beat stops; stillness on held notes.
6. Flashes on hits only, inside the flash budget (§13).
7. Match cuts and pushes land on the beat, not near it.
8. Lyrics on the voice, never early.

---

## 11. 2.5D treatments (where the stills have to shine)

Most shots in EV were stills with a depth map. "A plate must never read as a still with a slow zoom." **Build every 2.5D
shot from a treatment; never the same treatment on two consecutive 2.5D shots; a chapter uses at least five different
ones.** `slop board audit` checks the consecutive rule from `shots.json` `treatment`.

| Family (code) | What | Recipes that shipped |
|---|---|---|
| **Layer separation** (LS) | depth-keyed parallax; type and graphics *between* depth layers ("the word behind her, in front of the hall"); foreground grain boil; rack focus | **depth slices**: cut the plate once into cumulative slices at depth thresholds .16 .28 .40 .52 .64 .76 .88 (soft edge ±.035, 2000 px), placed far → near with their own parallax, ~30 ms/frame vs ~500 ms for the shader, and you can draw *between* slices. **Multiplane**: an Otsu depth split into near/far planes with push-pull inpaint of the far plane (12 relaxation passes, 1.5 px blur; fill with the void's mean tone if its luminance sd < .09), each plane with its own camera; graphics drawn behind the near plane. **Rack focus** by resampling blur. |
| **Depth as image** (DI) | the depth map itself as the visual | iso-depth contour lines revealed by a scan front once per beat; thermal ramp; point-cloud dots; a CV depth-scan sweep; a **relight band**: a Gaussian depth band (quantised to 1/40) that travels front → back once per beat, screened onto the base, the figure excluded |
| **Reproduction** (RP; `mosaic` and `tiles` in every look, the print textures `xerox` and `thermal` in a print look only) | per-shot reproduction effects, not a global filter | photocopy scan revealing band by band; halftone dots growing with the kick (dot frequency 7 + 5·kick); 1-bit threshold flicker (threshold .42 ± .11 at half resolution, or a Bayer 4×4 ordered dither at ¼ resolution); misregistration ghost per beat; thermal print bands (Bayer 8×8 per 16th with a print head); mosaic "enhance" 28 → 1 px over .3 beat |
| **Stills in rhythm** (SR) | one plate cut in time | 3–4 crops `{zoom, cx, cy}` of the same plate cut on eighths with a contact strip and a one-frame flash per crop; plates of a series swapped on beats (×1, ×2, ×4, ×8); a contact-sheet grid that selects one frame on the downbeat; freeze + slide; SP adds the two-frame overshoot per crop |
| **Diagram over image** (DG) | information design on the plate | callouts with leader lines to things in frame; measured dimensions; a CV mesh on her face; a plan view that morphs into the plate; the plate cropped into chart cards; a flat graphic projected onto a plate quad by homography (sign faces, phone screens) |
| **Occlusion** (OC; SP) | type behind the subject | §12 |
| **Pure motion design** (PM) | replace the plate with a code-drawn frame | an information-design diagram, a terminal/UI screen, a typographic poster, a split-flap wall, data-viz, a spec-label sheet — where a plate would repeat its neighbours or the idea reads clearer as a graphic. It still carries the lyric, chrome and look. |

**In `board/shots.json`, write `treatment` with the engine's family names, one vocabulary for the whole board**
(`slop board audit` compares consecutive shots by the family the engine will draw, so `layers` next to
`layer-separation` counts as a repeat, but one vocabulary keeps the board readable):
`push` · `layers` · `multiplane` · `rack` (LS) · `relight` · `contours` · `scan` (DI) · `xerox` (RP; the kinds `mosaic`
and `tiles` work in every look, written `{"family": "reproduction", "kind": "tiles"}`; the print kinds `xerox` and
`thermal` never in clean or native) · `stills` (SR) · `diagram` (DG) · `occlusion` (OC) · `auto` (the engine rotates the
five families, never repeating the shot before). A string or `{"family": "layers", …params}`; `engine/DEVICES.md` §6
lists every family, kind and param. Write them with `slop board set s004 --treatment layers`.
**A code-drawn shot (PM) is written `"treatment": "pure-motion"` with no plate** (or `"code": true`). The engine's
short name `motion` is read the same way by the engine and by `slop board audit` (both count it as code-drawn, so it
needs no plate). The default renderer also rotates a repeat away and logs a warning, but fix the board instead of relying on it.

Rules: **one plate per shot** — never borrow another shot's plate (UI thumbnails excepted); keep the lead on screen for
the target share (convert prop inserts and repeats of the same set to PM, not her shots); with budget left over, replace
the most repetitive 2.5D shots with motion clips ("more seedance less 2.5d where we can fit it").

Software-GL performance: prefer slices and multiplanes over the 64-step parallax shader; blur by drawing to a ¼ or ½ size
canvas and back (`fastBlur`, `softDraw`) instead of `filter: blur` at full resolution.

---

## 12. Occlusion: type behind the subject (rotoscope and depth)

Every media draw returns `m` with `m.box(label)` (boxes), `m.matte()` (the subject's alpha) and `m.depth()` (the depth
map), all drawn through the same camera as the footage. **In a toolkit project only `m.depth()` has data, and only on
plate shots** (§5.0): `m.box()` is null unless you wrote boxes, `m.matte()` is null, and clips have neither. So in the
toolkit, occlusion means **the depth key**:

- `LY.*(…, {behind: m, occ: {mode: 'auto'}})` or `OCC.behind(o, m, draw)` — the block sits behind her; with no matte,
  `mode: 'auto'` keys on depth at the subject's depth − 0.1 (`subject_depth` from `slop edit export`). Without depth (clip
  shots, flat plates) the block is drawn uncut: place it so it reads without the tuck.
- `OCC.between(o, m, draw, {plane: .6})` — at a depth plane (a crosshair behind a crowd).
- `OCC.over(o, m, draw)` — only on the subject (a label printed on her, a scan across his body).
- `OCC.contours(o, m, {levels, reveal})` — the depth map as iso-lines. `OCC.outline(o, m)` (the matte edge as a CV
  segmentation line) needs a matte, so it draws nothing in a toolkit project.
- The `occlusion` treatment (§11) does the same for every lyric block of a shot.

**The tuck rule (MUST):** place the block so it **tucks** — an edge, a word end — "tuck an edge and never lose a glyph".
Never place it so most of the block disappears. A reviewer fix that shows the bar: "WHY/WOULD/I/DECEIVE/YOU? stops about
10 px short of her hair … nothing tucks behind her … move the column right so the right ends of WOULD and DECEIVE run 40–80
px under her hair strands through the matte."

**The engine enforces it** (`OCC`'s glyph guard, `engine/src/occ.js`; the Studio run's s005 lost a lyric behind a
laptop): an end glyph of a line may hide up to its outer letter's worth (eased out by 40 % as it goes); where letters
touch (tight tracking, an accent block) only the outer letter of the run may tuck; every other glyph the occluder would
cover is lifted and **drawn whole, on the subject, in the ink that reads there** (a line behind the subject takes its ink
from the ground off the subject, and the lifted glyphs a second pass in the ink that reads on it, even within one word).
`window.DEV_FRAME.occ` records each frame (`{glyphs, kept, eased, tucked, cover}`). Placement is still yours: a block that only
the guard keeps readable is a block in the wrong place.

Sources and licences: depth from **Depth-Anything-V2-Small only** (Apache-2.0; the Large weights are CC-BY-NC and must
never be used in this toolkit), computed on CPU by `slop edit export`. *Reference pipeline only, not shipped:* the
reference videos' mattes came from BiRefNet (MIT) held by SAM 2.1 (Apache-2.0) on clips; a project that adds its own
mattes (`PLATES[name].matte`, `CLIPS[name].matte`, see `engine/src/occ.js`) must record their licence. Landscapes with no
subject: occlude with depth there, never with a matte. After a plate is edited, re-run `slop edit export` so its depth is
re-made (SP's v1 shipped edited plates with pre-edit mattes).

---

## 13. Adaptive ink and the flash policy

### 13.1 Adaptive ink (`AINK`, SP)

The lyric modes pick ink from the footage **under the block**: white on dark, near-black on light; **split** (the letters
change ink along the footage's luminance edge — "text inversions") when the block's range > .35 and sd > .09; the accent
only on dark neutrals (luminance < .09, contrast ≥ 4.5, not warm). Modes: `solid | split | difference` (the letters show
the footage's negative) `| mono` (inverted black and white). It reads the **base only** — draw phone screens and UIs on
the base so ink can see them.

Split ink fails over translucent or busy texture ("the split ink cut glyphs mid-word ('it's' read 'i's')"; "blotchy on her
gown"). In order of preference: one solid ink per block or per word; a split along the rotoscope matte; a forced ink.
EV's ancestor: type drawn as a difference of the ground, through a mask that emulates the print pass's tone.

### 13.2 Flashes (MUST)

- **≤ 3 full-frame flashes in any second.** A flash = a pair of opposing changes in relative luminance of ≥ 10 % of the
  range, where the darker state is < 0.8, over ≥ ¼ of the frame (WCAG 2.3.1 general flash). `slop render check` runs
  it on the master (`80-review-qa.md` §5).
- Faster flicker only in panels smaller than a quarter of the frame, or at low contrast.
- **Flashes belong to a theme** (SP's black-and-white "Mast language": the drop, a pictogram on a shout, the flip's scene
  swaps, the strobe in one verse, the outro's quarter notes). Not on quiet lines, not as decoration: "dont need to force
  flashing". Plan them on hits; in code, check a list of flash times with `DEV.flashOk(times)` (alias `FLASH.ok`).

---

## 14. Glass (opt-in, native/clean looks only)

Physically lit liquid glass that refracts the base (`GLASS.pane/capsule/blob/lens/text`). Use only if the user asks for
"liquid glass", "transparent", "the user experience is none". Rules: glass bends the **base** (type on the overlay stays
crisp on top; type drawn on the base gets refracted); fade with `presence`, never with alpha; 1–3 glass elements per
frame, always over real content it bends; tint ≤ 10 %; no painted fringes (dispersion does it); calm motion in seconds,
never on the beat; ≤ 16 domes per frame; minimum stroke ≈ 2·soft. Cost +44 to +341 ms/frame (typically +110–160).

---

## 15. Lip-sync awareness (MUST)

The edit plays a sung take only inside its measured in-sync spans and cuts to other coverage elsewhere (`61-lipsync.md`).
In motion design: **where a sung line has no synced take, never hold her singing mouth large on the words** — use stills
in rhythm, depth moves, crops to eyes/hair/hands, inserts, motion design or other coverage. Crop off a mouth exactly where
the word ends, never hold it on silence. Re-frame any shot whose code was tuned to an old take when a re-take lands (EV:
a 1.8× crop cut her head off once the new take had her head to boots).

---

## 16. Writing chapter code (Director tier)

Quick and Studio tiers render from data: the default renderer draws every shot from `board/shots.json` (`type[]` modes and
placements, `devices[]`, `treatment`, `transition_in`, `chrome`, camera words) and needs no code. Director tier adds
**chapter code** where a line's explanation is unique. The contract is `engine/DEVICES.md` (the device catalogue and the
exact call signatures of this toolkit's engine); where a name here differs from DEVICES.md, DEVICES.md wins. Until
DEVICES.md exists, the contract is `engine/README.md` ("window.ENGINE — the stable API" and the list of globals) plus the
registered device kinds in `engine/src/devices/*.js`. Every engine global and member written in this file exists in that engine
(`tests/test_docs_c.py` checks it).

**How chapter code is loaded.** Chapter files live in `<project>/engine/ch/`. The page loads only
`<project>/engine/common.js`, `<project>/engine/scenes.js` and `<project>/engine/ch/_index.js`, so `_index.js` must list
the chapter files, in time order:

```js
// <project>/engine/ch/_index.js: one entry per chapter file (paths are relative to <project>/engine/)
['01_arrival.js', '02_board.js'].forEach(f => document.write(`<script src="ch/${f}"><\/script>`));
```

The orchestrator writes `ch/_index.js` with every chapter file name **before** it launches the animators (each animator
edits only its own chapter file, never the index); a chapter file missing from the index never renders, and its shots
silently fall back to the default renderer.

The project layer loads **before** the device library. So at the top level of a chapter file use only the engine core
(`scene`, `ENGINE.*`, `KIN`, `CAM`, `MEDIA`, `HIT`, `OCC`, `AINK`, `FX`, `M`, `F`); the device library's helpers (`LY`,
`DEV`, `CV`, `TR`, `FLASH`) exist only inside draw functions, which run after boot. A shot that no scene covers falls
back to the default renderer.

### 16.1 Read order (put this list at the top of every animator brief)

1. `PRODUCTION.md` (rules, budget, file contracts) — `95-delegation.md` §6.
2. The storyboard entries of the chapter's shots (`board/shots.json`, the board PDF notes, the user's verbatim notes).
3. This file and the project's `DESIGN.md` (type, colour, the sync table, flash policy, element budget, banned list).
4. `engine/DEVICES.md` (until it exists: `engine/README.md` and `engine/src/devices/*.js`) and the exemplar chapter
   (write chapter 1 first as the exemplar; everyone else follows its patterns and quality).
5. The bench: every device rendered at t ≥ the song's end, so animators can see them all on one sheet.
6. `edit/edl.json` (what footage each shot has right now) and the clip QA notes (where lip sync was given up).

### 16.2 The scene template

```js
// <project>/engine/ch/02_board.js: one chapter file, yours alone. One scene per shot.
(() => {
  const ID = 's042';
  const SH = ENGINE.data.shots.shots.find(s => s.id === ID);     // times come from board/shots.json, never typed by hand
  if (!SH) return;                                                // the shot was renamed: the default renderer covers it
  scene(ID, SH.t0, SH.t1, async (b, o, t, lt, dur) => {
    // 1. the footage (the edit's take in song time, or the plate) through the hits camera
    const m = await CAM.shot(b, ID, t, { zoom: 1.06, cx: .5, cy: .45 }, { punch: { amp: .015 } });
    // 2. the lyric: every token on its t0 and marked for the lyric gate; tucked behind her by depth where the plate has depth
    await LY.cover(o, b, KIN.byLine(23), t, { x: M.l, y: 640, size: 88, behind: m, occ: { mode: 'auto' }, micro: ['LOOK 07 / 11'] });
    // 3. the explaining graphic and <= 2 CV marks: registered device kinds, anchored on what the toolkit has (§5.0)
    await ENGINE.drawDevice({ kind: 'cv.tag', anchor: { uv: [.58, .30] }, key: 'W', params: { rows: ['MODEL 01 · CONF 0.97'] } },
      { o, b, t, lt, dur, shot: SH, m });
    // (a graphic unique to this line: a function of t, defined in this file)
    // 4. the always-on chrome, then the look, with the subject box for match/zoom/iris transitions when one exists
    ENGINE.chrome(o, t, {});
    const L = ENGINE.lookFor(SH), face = m && m.box('a face');   // null without hand-written boxes (§5.0)
    if (face) L.focus = face;
    return L;
  });
  ENGINE.transitions.set(ID, { preset: 'through', dur: .4, a: [960, 520], b: [960, 540] });   // its entry: push through a point
})();
```

`KIN.byLine(n)` takes the line number of `analysis/words.json`. A device the library does not have: write it as a
function in your file and call it inside the draw function. If a draw function throws, `slop render lyrics` stops with
"the engine page threw errors": open `slop render info` and fix the first error.

### 16.3 Build each shot in this order

1. **Base:** `MEDIA.drawShot` / `CAM.shot` — the edit's footage (takes and covers in song time, or the plate until the
   clip exists). Never name clips yourself; the edit survives re-takes. 2.5D shots get a treatment (§11).
2. **Lyrics:** every sung token in your range on its time, in the modes the storyboard sets, ≥ 40 px, with adaptive ink
   and a tuck where it lifts the frame.
3. **The explaining graphic** for each line (§5), entering on its word, animated in beats.
4. **Annotations** tied to what is in frame: hand-measured `uv` points or boxes, keyed tracks, or boxes you wrote in
   `common.js` (§5.0), and the chrome.
5. **Transitions:** hard cuts by default; a motivated device every few shots (§10).
6. **Measurements are data, not code:** tracked points, keyed uv tables, quads, seed points go in `shots.json` /
   tracks, with a comment saying how they were measured ("the foam's centroid, every 4 frames"). Hand-measured plate
   features are keyed by plate name.

**Declare what your chapter draws.** `slop render check --layers` counts the ordered layers of every shot's mid-point
frame from what the engine sees (plates and clip frames, `KIN.mark`, `ENGINE.chrome`, `ENGINE.drawDevice`). A graphic
your own code draws is invisible to it: call `ENGINE.noteLayer('graphic')` (or `annotation`, `micro`, `chrome`; the
kinds are in `ENGINE.layerKinds`) while drawing the frame. A chapter scene below the rule that declared nothing is
listed UNVERIFIED with a `slop render stills` command to look at it.

### 16.4 File ownership (MUST)

- Edit **only your own chapter file**. Other chapters are written in parallel.
- A missing shared helper: write it privately inside your file. **A bug in a shared file: report it (file, line, fix);
  never patch it.** The orchestrator fixes shared files once, centrally. (EV's animators found a countdown schedule bug,
  off-palette terminal colours, a wrong track fps, negative ruler numbers, a mis-aligned word and off-model clips this
  way.)
- If your file already has scenes (an interrupted run), read it and continue from it.

### 16.5 Verify before you hand in (MUST; paste into every animator brief)

1. `slop render lyrics --from A --to B` → **N/N** for your range.
2. Contact sheets (`slop render sheet --times t1,t2,… --cols 4 --w 480`) at every shot's first, middle and last frame, every
   line's first and last word, every hit, each graphic's entrance and each transition's middle; full-size stills of your
   4 best moments. **Open every sheet and look.** Iterate until each shot is beautiful, legible on a phone, dense to the
   budget, on the beat and on-model.
3. Sync: render the range at 12 fps (or sample those times) and list the 10 biggest camera moves and the nearest hit for
   each.
4. History check on 3 out-of-order pairs inside your range → HISTORY-INDEPENDENT.
5. ms/frame ≤ 1,500.
6. Return: scenes (ids, times); per line its mode and explaining graphic; each 2.5D shot's treatment; the transitions; the
   lyric gate line; the sync list; known issues and shared bugs.

---

## 17. Banned (consolidated)

- The user's taboo words anywhere (code, labels, file names, on screen).
- Desaturating or tinting the footage; colour looks applied to generation inputs.
- Neon, glows, gradients as decoration, drop shadows, bevels; colours outside the palette (+ physical sign colours on
  physical signs, UI greys in UI).
- Marks across her eyes or mouth; type over her face.
- Real people outside labelled posts, speaking, or given words they did not say.
- `Math.random`, `Date`, state carried between frames; memos keyed by frame.
- Borrowing another shot's plate; two clips starting from the same frame.
- Lyric type under 40 px; a lyric token early or snapped to a beat; a sung word missing from the screen.
- Flashes outside the theme or more than 3 full-frame flashes in a second.
- Camera moves that answer no sound; shake in UI shots; punches where the drums are out.
- The same transition device twice in a row; the same 2.5D treatment on consecutive 2.5D shots; "a still with a slow
  zoom".
- The owner's or user's real name or initials on screen; credits use the user's chosen pseudonym only.
- Fonts that are not OFL; Depth-Anything-V2-Large.

## 18. Hand-off checklist (copy into the chapter's report)

- [ ] lyric gate N/N for the range (and the film still N/N)
- [ ] one explaining graphic per line, entering on its word
- [ ] ≥ 3 ordered layers / within the chosen element budget; accent on ≤ 2 elements (SP budget)
- [ ] 2.5D: ≥ 5 treatments per chapter, none twice in a row, no slow-zoom stills
- [ ] cuts on beats/hits; transitions motivated, never repeated back to back
- [ ] camera moves listed against hits; stillness where the song breathes
- [ ] ≤ 3 full-frame flashes in any second
- [ ] no singing mouth held where the take is not synced
- [ ] history-independent; ≤ 1,500 ms/frame
- [ ] shared bugs reported, not patched
