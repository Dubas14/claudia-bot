# Claudia devices — the data-driven motion-design layer

This is the layer that **explains each lyric line**: the counter that ticks the stakes, the label that classifies the
subject, the terminal the joke is about, the chart the number implies — plus the lyric type, the 2.5D treatment of the
footage, the camera that plays the track, and the transitions. Everything here is driven from `board/shots.json`; nothing
needs code.

- `engine/src/shots.js` — the **default renderer**: one scene per storyboard shot (skipped where bespoke chapter code
  already covers the time), and a quiet motion-design scene for any hole in the storyboard.
- `engine/src/devices/*.js` — the **device library** (40 drawable devices + 6 camera moves), the type modes, the 2.5D
  treatment families and the transition presets. `devices/index.js` loads them in order; the engine page includes it.
  The five newest (`quad`, `rope`, `streamlines`, `molecule`, `powers`, in `devices/explain.js`) are the explaining
  devices both reference videos wrote again and again as bespoke chapter code; they are §8's last five entries.

The reference videos: **EV** = *Escape Velocity* (5:06, print look: colour halftone + grain) and **SP** = *Clodyssey /
Superpersuasion* (3:09, clean look). Every device below is a generic port of something one of them did; the
"precedent" lines describe what (they never quote the videos' words) — use them to pick a device for a line. Every example
below is a fresh, generic one: fill the params with **your** line's own facts.

> Rule zero (from both videos): **every lyric line gets an explaining graphic** that shows what the line *means*,
> enters on the word that names it, animates in beats, and reads in one glance. Start from the line's meaning, pick the
> device whose "explains" column matches, then fill its params with the line's own facts.

> **Check what the renderer did.** It never repairs a storyboard silently. Run `slop --json render info` after every
> board change: `info.deviceWarnings` lists every repair (a rotated treatment, a demoted or unknown transition, a dropped
> flash, an unknown kind, a malformed param — each line names the param, what was drawn instead and the exact shape to
> write —, a word that is not sung in its shot, an anchor with nothing to point at, a lead mark that could not be placed, a
> `multiplane` plate with no subject plane) and every device or type entry that **throws** when the page boots (each one
> is drawn once as a dry run). The same lines are on the page console as `[devices] …` (`info.console`), with the few
> that only a rendered frame can find (a measured `quad` the 9:16 crop cuts). An empty list is the goal.

---

## 1. What a frame contains (and the budget the renderer enforces)

For each shot at song time `t`, `shots.js` draws, in this order:

1. **The base**: the shot's footage from `window.EDL` (a plate still or a clip frame) through its 2.5D **treatment**
   (§6) and the **camera** (the storyboard's `camera` words + the shot's `cam.*` devices, §9). No media → a ground.
2. **One flash** (if a flash device fires now and the flash rule allows it) — full-frame, under everything else. While a
   full-frame `card` / `black` / `paper` flash is up the footage is hidden, so the CV marks, micro and hero devices wait
   (the lyric and the chrome stay; a card that **is** the line replaces the lyric). The same while a hero **replaces the
   footage** (`powers` once it pulls out: its map is painted on the base, like footage): the CV marks, micro devices and
   the treatment's own marks on the footage (the `stills` strip, the `diagram` grid) wait until it ends.
3. **≤ 2 CV marks** (role `cv`: brackets, tags, lock, callout, leader, chip, outline — the lead's own mark counts).
4. **≤ 2 micro devices** (role `micro`: typed rows, ticker, ruler) holding **≤ 3 rows of micro type in all** (a coverline's
   own micro rows count first).
5. **One hero device** (role `hero`: the card, the plot, the readout, the terminal…).
6. **One lyric block** (§5) — every sung token on its exact `t0`. Drawn last of the graphics, and nothing else ever sits
   on it (**the collision rule**, below).
7. **The chrome** (the project's `chrome()`; `chrome: "hud"` uses the device library's own).

**When more are active than the budget allows, the newest wins** (latest start; `priority` breaks ties; the
automatic lead mark always yields first). Suppressed devices are counted in `window.DEV_FRAME.suppressed`.

| rule | how it is enforced |
|---|---|
| one lyric block per frame | the newest active `type[]` entry, or the sung line itself as a subtitle when no entry covers it (so the lyric gate stays N/N) |
| one hero device, ≤ 2 CV marks, ≤ 2 micro devices with ≤ 3 micro rows | newest-wins selection per frame (a micro device that would push the rows past 3 is skipped) |
| the accent on ≤ 2 elements | the lyric claims the first accent; a treatment's accent mark (the `scan` sweep, the selected `stills` contact frame, the `thermal` print head) the next; then each device asks for it (`x.acc()`); once two elements hold it, later ones get the ink colour. The chrome's beat pip and progress line are not counted |
| the lyric is the biggest type unless a device is the line | the plan **caps** a hero that sets bigger type (`strike`, `stamp`, `counter`, `tally`, `flap`, `departures`) over the lyric on screen with it: its type params are scaled down to the lyric's size once, in the plan (the spec's `capType(p, k)`, else `params.size`), so it never resizes mid-shot, and the cap is reported (`deviceWarnings`); one it cannot cap is reported to fix by hand. Set the device's `is_line: true` when it **is** the line (it keeps its size) |
| ≤ 3 full-frame flashes in any second | planned up front: the frame changes that happen anyway (every designed transition except `flash`/`flashCut`/`fade`, and every cut into a `stills` shot) are fixed; flash devices (cards first), `flashCut`/`flash` transitions and stills crop flashes fit around them; a flash that would make any 1-s window hold a 4th is dropped and reported. `slop render check` tests the master again (WCAG 2.3.1) |
| 2.5D treatments never repeat back to back | a repeat (asked or auto-picked) is rotated to another family and reported — compared on the family that actually draws (a depth family on a plate without a depth map draws a push) |
| every 2.5D shot gets a treatment; five families per run | **write the treatment yourself today**: `slop board audit` fails a 2.5D shot whose `treatment` is empty or `"auto"` (§6). The engine can pick one — a plate shot with no `treatment` gets the least recently used of the guide's five families (§6: LS · DI · RP · SR · DG), so five picked shots of ≥ 2 beats in a row cover all five, in native and clean looks too (reproduction as `mosaic`/`tiles` there) — but a board only reaches the renderer that way once the audit accepts it |
| ≥ 3 ordered information layers per frame | counted, not forced, by **one** counter: `ENGINE.frameLayers()` (engine core) after a frame says which of media · graphic · annotation · micro · lyric · chrome it drew; `slop render check --layers` runs it on every shot's mid-point. A frame with only media + lyric + chrome is the "clean hero moment" the guide allows for ≤ 2 bars (`hero_moment: true` on the shot). Only devices that drew something count (a flash that did not fire, a device whose params leave it nothing to draw, are left out) |
| never the same transition twice in a row | a designed transition equal to the **previous shot's** is demoted to a hard cut and reported (`whip` · cut · `whip` is fine, as `slop board audit` says) |
| words on the voice, motion on the beat | tokens appear at `tk.t0` (never snapped); every animation is timed through the beat map (`bpOf`/`beatAt`), never a BPM |
| everything inside the margins | every placed block stays inside the frame's margins (the 9:16 cut has its own UI-safe margins: top 180, right 150, bottom 420 px); a block bigger than the safe area is scaled down to fit |
| **nothing covers the lyric** (the collision rule) | every lyric block the shot can show is **measured on every frame** with its mode's own layout (`DEV.type.measure`: the block's extent over its whole time on screen, through this frame's camera and lead) and padded 14 px; then: **panels** (everything placed with `x.place`: cards, charts, counters, terminals, typed rows, chips) move to the nearest free spot — the other side of their anchor, above / below / beside the block, a slot — shrunk to .8 / .64 when nothing is free at full size (a position the board asked for, `x`/`y` or a named slot, that has to move is reported once on the console, and so is a panel with no room off the lyric at all); **CV labels** (`cv.lead` / `cv.bracket` "LEAD · 01 0.97", a `det` chip, `cv.tag` / `callout` rows, a `leader` chip, `cv.lock` rows, a `gauge` tag) flip to another corner of their box or the other side of their leader (a way whose leader runs clear of the lyric first) — else the label is left off (the brackets still frame; a bare leader takes a clear way); the **CV strokes** stop at the block on screen; the **chrome** items that would land on it (its ink joined into items: a corner label, the bar counter, the progress line, a ruler of any height) are taken out whole; the `stills` contact strip and the `diagram` readout move or drop (the strip also gives way to a device on its spot: left out of that frame, else drawn beneath the devices); a `ticker` takes the other edge. A device keeps off every block whose time on screen overlaps its own, so nothing jumps when the next line comes in. Same rule in 9:16 (labels also stay within 32 px of the UI-safe margins). `DEV_FRAME.lyricRect` / `labels` / `chrome` show what happened (§12) |

Placement: a device without `x`/`y` or an anchor goes to the **`auto` slot** — the first free slot on the side away
from the lead (top, middle, bottom), then the lead's side — avoiding the lead's box and the lyric blocks. Wherever a
device is placed, it then keeps off the lyric (the collision rule above).

---

## 2. The shots.json fields this reads (ARCHITECTURE §4.5)

| field | used for | notes |
|---|---|---|
| `id`, `t0`, `t1` | the scene and its span | shots should tile the song (holes get a `gapNN` motion-design scene); a shot without an id or with t0 ≥ t1 is skipped and reported |
| `section` | the look (`ENGINE.lookFor`: chorus/verse ordinals → `chorus2`, `verse2`), the chrome's section label | |
| `lines` | informational (the type and the lyric gate read `window.LYR`) | |
| `lead_on_screen` | adds the automatic lead mark (`cv.lead`, lowest CV priority) | needs a subject box (§4); a shot without one gets no mark and is reported |
| `subject_uv` | `[u, v, w, h]` — the subject's box in **image space** (0..1 of the plate / clip frame) | the lead box when there are no detections (§4). Write it for shots whose plate has no depth map |
| `framing` | `CU`/`MCU`/`ECU` → the lead mark adds a face cross; `a face` anchors use the whole subject box | |
| `camera` | `MEDIA.camFrom` words: push · pull · pan/truck left/right · tilt/crane · orbit · static/locked · handheld | `static`/`locked` also switches off the default kick |
| `type[]` | the lyric blocks (§5) | prose strings are ignored (every sung word is still drawn as a subtitle) |
| `devices[]` | the explaining graphics and camera moves (§8–§9) | unknown kinds are skipped and reported |
| `treatment` | the 2.5D family (§6): a name or `{family, …params}` | write one on every 2.5D shot (`slop board audit` fails a missing one); the renderer would auto-pick (never repeating) |
| `transition_in` | the entry transition (§7): a preset name, prose, or `{preset, …params}` | `cut`/missing → hard cut; an unknown name → hard cut **and a warning** |
| `chrome` | `false`/`"off"` none · `"min"` minimal · `"full"` · `"hud"` the device library's chrome; other prose → the default | |
| `accent` | the shot's accent colour (default: `project.json look.accent`, else `#D97757`) | |
| `look`, `screen`, `lift` | look overrides (print-look projects) | |
| also accepted | `lyric[]` (= `type[]`), `trans_in`, `camera_fx: {punch: {…}, shake: …}` (= `cam.*` devices), `subject` (= `subject_uv`) | the gap-1 proposal names |
| not read | `set`, `action`, `motion_tier`, `plate`, `clip`, `mj_prompt`, `img_prompt`, `notes` | the footage comes from `edit/edl.json` (`window.EDL`) |

A device entry: `{"kind": "...", "anchor": …, "params": {…}, "key": "W|B|H|F|T", "at": <time>, "until": <time>, "priority": 0}`
(`device` is accepted for `kind`; `at: {t0, t1}` is accepted for `at`/`until`).

**Hand-written JSON is forgiven, and told about it.** Numbers written as strings (`"beats": "2"`, `"line": "1"`,
`"size": "60"`) are read as numbers. A param of the wrong shape is converted to the shape the device expects, with a
warning: a list given as a string is split on `|` (`"rows": "RENT: 1 | FOOD: 2"` → `[["RENT","1"],["FOOD","2"]]`), a row
given as a string or object becomes a row, a row that cannot be read is dropped; anything else falls back to the default.

---

## 3. Timing: the keys W · B · H · F · T and the time grammar

A device's **start** is `at` when given, else decided by its **key**:

| key | the device starts… | params read |
|---|---|---|
| `W` (word) | on a sung word's `t0`: `params.word` (the word's text, or `[line, index]`), else the shot's first sung word | `word` |
| `B` (beat) | on the first beat at/after the shot start, plus `params.beat` beats (fractions allowed) — **default when there is no `word`** | `beat` |
| `H` (hit) | on the n-th track event of a kind inside the shot (`window.HITS`; without it, the beat map stands in) | `hit` (`kick`·`snare`·`hat`·`impact`·`vox`·`any`), `n` |
| `F` (fixed) | at `params.t` song seconds (or a time spec) | `t` |
| `T` (take) | at `params.take` seconds **into the shot's clip** (the EDL segment maps take time → song time); bare numbers in `keys` and in anchor tracks are take seconds too | `take`, `clip` |

Its **end** is `until`, else the device's own length (a flash: one frame / half a beat), else the shot's end.

**A start keyed to a word must be a word sung in that shot.** A word that is sung only outside the shot would start the
device where it is never seen: the device starts at the shot start instead and the plan reports it. A word that is never
sung (a typo, a word the display text spells differently) is reported too. Fix the word or the shot.

**Time specs** (anywhere a time is asked for: `at`, `until`, `keys`, `lock`, `send`, row `at`s, chart points…):

| spec | means |
|---|---|
| `12.34` · `{"t": 12.34}` | song seconds |
| `"shot.t0"` · `"shot.t1"` · `"shot.mid"` | the shot's start / end / middle |
| `"lamp"` or `{"word": "lamp"}` | that word's `t0` (the earliest match inside the shot, else the first in the song) |
| `{"word": [3, 2]}` · `{"word_end": [3, -1]}` | line 3's third token `t0` · line 3's last token `t1` |
| `{"line": 3}` · `{"line_end": 3}` | the line's start / end |
| `{"beat": 120}` · `{"bar": 30}` | an absolute beat index / downbeat index |
| `{"beats": 2}` · `{"beats": 1.5, "from": "lamp"}` | 2 beats after the shot start (tempo-aware) · 1½ beats after a word |
| `{"eighths": 3}` · `{"sixteenths": 5}` | eighths / sixteenths after the shot start (or `from`) |
| `{"hit": "kick", "n": 1}` · `{"hit": "impact", "near": 91.0, "win": 0.12}` | the 2nd kick in the shot · the impact nearest 91.0 s within 0.12 s |
| `{"take": 1.25, "clip": "SD03-t2"}` | 1.25 s into that take (as placed by the EDL) |
| `{"offset": 0.1, "from": "lamp"}` | 0.1 s after the word |
| `{"frame_nearest": <spec>}` | snapped to the nearest frame |

A spec that cannot be read (`{"beats": "two"}`, a line that does not exist, an object with none of these keys) falls back
and is reported.

**Keyed values** (`params.keys`, read by `counter`, `gauge` and any device that shows a number):
`[[time, value, ramp?], …]` — the value holds, then eases over `ramp` seconds (default 0.25) so it lands **on** each key's
time. Example: `"keys": [[{"word": "warm"}, 36.6], [{"beats": 4}, 37.9], [{"hit": "impact", "n": 0}, 39.1, 0.3]]`.

Inside devices every animation runs in beats of the beat map (entrances over ½ beat, rows typed per 16th, crops per
beat…). Songs drift and accelerate; **never compute beats from a BPM**.

---

## 4. Anchors (where a device points or sits)

**The toolkit detects no boxes by itself**: `PLATES[name].boxes` holds only the boxes you name on a plate's picked image
with `slop plates box PLATE --label "a phone" --uv u,v,w,h` (exported by `slop edit export`), and there is no clip `TRACK`,
so any other detection label resolves to nothing in a real project. Point at things with **image-space `uv` anchors**
(they follow the camera), screen `rect`s or slots, or name the box — and give the shot a **subject box**. The lead /
subject box is, in order:

1. a box for the lead (`PROJECT.lead.label`, else `subject` / `a person` / `a woman` / `a man` / `a singer`, else
   `a face`) — `slop plates box PLATE --label subject --uv …` writes one;
2. the shot's `subject_uv: [u, v, w, h]` (image space);
3. the plate's `subject_uv` in `window.PLATES` (when a later tool writes it);
4. the subject found in the plate's depth map (Depth-Anything-V2-Small, written by `slop edit export`): the largest region
   of pixels **nearer than the rest of their own row** (a floor or a road coming towards the camera is never the subject; a
   full-height column such as a pillar and an off-centre region count less); a close-up where nothing stands out of its
   row falls back to the largest region of the nearest 12 %. Good for a figure in front of a background; write
   `subject_uv` when it is wrong (a figure touching a wall or a pillar merges with it).

| anchor | resolves to |
|---|---|
| `"lead"` · `"subject"` | the lead / subject box above |
| `{"uv": [0.62, 0.40]}` · `{"uv": [u, v, w, h]}` | an image-space point / box through the camera (the frame itself when the shot has no footage) — **the recommended anchor** |
| `{"rect": [x, y, w, h]}` · `{"xy": [x, y]}` · `[x, y]` · `[x, y, w, h]` | screen pixels (1920×1080 design; the portrait cut has its own margins) |
| `"top-left"` · `"top-right"` · `"left"` · `"right"` · `"bottom-left"` · `"bottom-right"` · `"center"` · `"auto"` · `{"slot": …, "w": 360, "h": 220}` | a free region inside the margins (`auto` = away from the lead and the lyric; `w`/`h` size the region; the board tools rewrite `centre` and `Top Left` to the engine's `center` / `top-left`) |
| `{"keys": [[t, u, v], …], "clip": "…"}` | a hand-measured track (take seconds under key `T`), interpolated |
| `"a face"` (any detection label) · `{"box": "a phone", "pad": 12}` · `{"label": "a phone"}` · `{"track": "a person"}` | the plate's box (named with `slop plates box`) or the clip's track, through the camera. Without one: person labels (`a woman`, `a man`, `a person`, `a singer`) fall back to the subject box, `a face` to the top of it (the whole box on CU/MCU/ECU framings); any other label resolves to **nothing** |

The plan checks every anchor against the shot's data and reports the ones with nothing to resolve to ("no detection box
… add `subject_uv` or use a uv/rect/slot anchor"); such a device draws nothing (it never throws).

Devices that **point at** something (CV marks, callout, leader, gauge tag) need an anchor; devices that **sit** somewhere
(cards, charts, counters) use `params.x`/`params.y`, else a slot anchor, else beside the anchor's box, else `auto` — and
are moved off a lyric block if that spot covers one (§1, the collision rule; reported when it was a spot you asked for).

---

## 5. Lyric type (`type[]`)

`{"line": 3, "mode": "coverline", "placement": "right", …}` — one entry per block. Modes: **subtitle · coverline ·
masthead · stack · mass** (`sub`, `cover`, `mast`, `caption`, `wall` accepted). Every token is drawn on its aligned
`t0` and marked for the lyric gate (`slop render lyrics` must print N/N). The lyric is never set under 40 px.
An entry whose line does not exist is skipped and reported; an entry whose line is sung outside the shot is reported
(it would show only where the shots overlap).

Default positions (16:9 values; every one is derived from the margins and the frame height, so the 9:16 cut keeps the
lyric above the platform UI): subtitle baseline `H − 124` (= bottom margin + 40), coverline first baseline 600, masthead
baseline 760 at 300 px, stack top 150, the mass wall from the top margin + 54.

| field | modes | meaning |
|---|---|---|
| `placement` | all | prose: `left` (default) · `right` · `center` · `top`/`upper` · `bottom`/`lower` (a right-hand masthead/stack hangs from the right margin; a right-hand coverline/subtitle hangs from a column at 56 % width in 16:9 and from the right margin in portrait) |
| `words` | all | `[a, b]`: only tokens a..b of the line (a masthead on one word of a coverline's line); it holds until the next word starts |
| `x`, `y`, `size`, `w`, `align` | all | explicit layout (px); rows always wrap inside the margins |
| `ink` | all | `auto` (default: one solid ink picked from the footage under the block — per word for mastheads and stacks, where a word straddling light and dark inverts in black and white; a subtitle over mixed ground keeps the line's ink on every word it reads on and gives a word the other ink only where the line's ink drops under 3:1 contrast over it, so words do not change ink as the camera drifts unless their ground really turns against them) · `light` · `dark` · `#hex` · `split` (inverts where it crosses light/dark — avoid over busy texture) · `difference` · `mono` |
| `behind` | all | `"matte"` / `"depth"` / `true`: the block tucks behind the subject (needs a matte or depth; place it so an edge tucks, never so most of it disappears) |
| `at`, `until` | all | override the block's window (time specs) |
| `kicker`, `micro` | coverline | a micro kicker above · ≤ 3 typed micro rows under the rule (sources, dates; one character a 16th) — they count toward the frame's 3 micro rows |
| `breaks` | subtitle, coverline | token indexes that start a new row |
| `accumulate`, `flash` | masthead | the line builds across the frame · `"block"` (default: a 1-frame accent block behind each new word) or `false` |
| `fit`, `maxSize`, `lead` | stack | column width (every row set to it), size cap, row spacing; a word wider than the safe area is set smaller |
| `lines`, `rows`, `keep` | mass | the wall's lines (default: every lyric), rows, the row that stays lit |

| mode | look | use it for (precedent) |
|---|---|---|
| `subtitle` | 46 px grotesk, low left, words rise in over a 16th, the sung word in the accent | long spoken lines, quiet moments; SP's default for every line |
| `coverline` | 84 px editorial lockup beside the subject: tracking collapses in on each word, breathes on the kick, hairline + typed micro rows; hangs from the other margin when it would cross the subject | most EV verse lines (each look line set beside the model with its source rows) |
| `masthead` | one word at a time in condensed black caps, hard cut on its time, 1-frame accent block | emphasis words, numbers, shouts (EV's one-word mastheads; SP's shouted orders) |
| `stack` | the line builds as a vertical column, one word per row | short punchy lines (SP's three-word stacked exclamation, EV's stacked numbers) |
| `mass` | a declared wall of micro text flickering on eighths, the sung line as a subtitle on top | volume: "every message at once" (EV's chant wall in the drop) |

When no entry covers a sung line, it is drawn as a subtitle — so a storyboard with only prose type still passes the gate.

---

## 6. 2.5D treatments (`treatment`)

A string (`"layers"`) or `{"family": "relight", …params}`. Codes in brackets are the guide's families: LS layer
separation · DI depth as image · RP reproduction · SR stills in rhythm · DG diagram over image · PM pure motion design ·
OC occlusion. Depth families need a depth map (Depth-Anything-V2-**Small** only — any other model's depth is ignored):
asked for on a plate without one they draw a plain push, and the plan says so. Clip shots take `stills`, `diagram`,
`xerox`, `occlusion` or the plain clip.

Names accepted: the family names below; the board's (`slop board draft`) `layer-separation` → `layers`,
`depth-as-image` → `relight`, `diagram-over-image` → `diagram`, `stills-in-rhythm` → `stills`, `reproduction` → `xerox`,
`pure-motion` / `motion-design` / `code` → `motion`; the codes `LS DI RP SR DG PM OC`; `multi-plane` / `planes` →
`multiplane`; `thermal`, `mosaic`, `tiles` (and `photocopy`, `halftone`, `enhance`, `split-flap`) → `xerox` with that kind;
and prose. In prose a family **named** inside parentheses or after a code wins over the code (`"LS (rack)"` → `rack`,
`"DI: contours"` → `contours`); among codes alone the first wins (`"DI+LS"` → `relight`). An unknown name draws a plain
push and is reported.

**Write a treatment on every 2.5D shot: a family, or `"auto"`.** `slop board audit` fails a 2.5D (plate) shot whose
`treatment` is empty ("a 2.5D shot needs a treatment"), and the board cannot be approved without a passing audit.
`"auto"` (`slop board set s004 --treatment auto`) is a written choice: the audit accepts it on any number of shots in a
row, and the engine picks the family as described below. To choose yourself, write the rotation — one family per
shot, never the same as the shot before, all five families in every run of five 2.5D shots, e.g.:

```
"layers" → "relight" → {"family": "reproduction", "kind": "mosaic"} → "stills" → "diagram" → "multiplane" → "scan" → {"family": "reproduction", "kind": "tiles"} → …
```

(in a print look `"xerox"` and `{"family": "reproduction", "kind": "thermal"}` are reproductions too; in a native or clean
look use `mosaic` or `tiles`). `slop board draft` writes four families in native looks today; swap one of every five for a
reproduction.

**What the engine does with `"auto"`** (and with a missing treatment on a board that reaches the renderer without passing
the audit — `--force`, or chapter tooling): it picks one, covering the guide's five families. The renderer rotates the five
families LS · DI · RP · SR · DG, least recently used first (asked treatments count as used), never the previous 2.5D
shot's family and never the family the *next* shot asks for (so your own choice is never rotated away). Five picked
shots of **≥ 2 beats** in a row cover all five, in every look; shorter shots rotate the families whose variants fit them
(`stills`, `tiles` and `rack` need time), and an asked treatment or a pinned hero (no `stills`) can leave a five-shot
window one family short:

| code | picked as (with a depth map) | without a depth map |
|---|---|---|
| LS | `layers` · `multiplane` · `rack` (in turn) | `push` |
| DI | `relight` · `scan` · `contours` | — (needs depth) |
| RP | native / clean look: `xerox` kind `mosaic` · `tiles` — print look: `xerox` · `tiles` · `thermal` · `mosaic` | same |
| SR | `stills` (its crops cut without the crop flash: flashes only where the board asks) | same |
| DG | `diagram` | same |

A variant that needs time is skipped on a short shot (`rack` under 1.5 beats, `stills` and `tiles` under 2 beats), and a
shot whose hero is pinned into the picture (`streamlines`, `rope`, a `quad` with a measured `quad`) never gets `stills`
(its crops would make the graphic jump on every beat). `ENGINE.info().treatments` lists what every shot got
(`family`, `kind`, `code`, `auto`, `clean`, and `drawn` — the family that actually draws, e.g. `layers` for a
`multiplane` plate with no subject plane).

Clean or print is decided **per shot**, from the shot's own look: in a print film a shot with `"screen": "native"` is
clean (no print reproductions picked for it, print kinds asked on it are reported), and the reverse. `xerox` kind `xerox` /
`thermal` asked for in a clean look is kept and reported (print texture is banned there); `mosaic` and `tiles` are the
clean reproductions, and `reproduction` with no kind draws `mosaic` in a native or clean look (`xerox` in a print look). A
kind nobody knows (`{"family": "xerox", "kind": "banana"}`) draws `mosaic` in a clean look and `xerox` in a print look,
and is reported. Warnings quote what you wrote: `treatment 'tiles' (draws as xerox kind tiles) repeats …`.

**Face-safe camera (every plate treatment).** A push, a zoom, a camera device or a `stills` crop never cuts the face
(Quick E2E: a push cropped the lead above the nose). The protected box is the plate's `a face` box (`slop plates box`),
else the face read off the subject box (the shot's / plate's `subject_uv`, else the depth subject): its top half on
CU / MCU / ECU framings (the brow to the nose), the head on wider ones. The screen-space zoom of the camera devices
(punch, ride, impact, snap) is folded into the 2.5D camera, then `PLATE3D.safeCam` moves the framing centre toward the
face and, where that is not enough, holds the zoom (never under 1) — so the whole face box stays in frame with headroom
(6 % above, 3 % at the sides and below) at every frame; where the plate has less room above the head, the face gets what
the plate has. A `stills` crop shows all of the face or none of it (a DETAIL crop that would show a sliver slides off
it). A shake or an impact burst (`cam.shake`, `cam.impact`, the snap's jag) that would still push the face out — a face near
the plate's edge, where no framing makes room for the shake's overscan — is calmed just enough (framed for the shake's
amplitude, so neither the framing nor the calming flickers with it); a face the plate itself cuts keeps the shake. In 9:16 the camera centres on the subject. A whip transition is left alone. Switch it off for a deliberate crop with
`{"family": "push", "face_safe": false}` (or `"face_safe": false` on the shot). `DEV_FRAME.face` is the kept box (screen
px), `faceHeld` whether the zoom was held, `faceCalm` the fraction of the shake kept (null: all of it).

| family | params (defaults) | what it does | precedent |
|---|---|---|---|
| `push` (LS) | — | the plate's own 2.5D parallax on the camera words | the default 2.5D move in both videos |
| `layers` (LS) | `amount` .03 | the plate cut once into 7 cumulative depth slices, each with its own parallax; a lateral move shows the depth | EV intro: show lights igniting *between* depth layers |
| `multiplane` (LS) | `amount` .016 (drift, fraction of the frame), `dir` (`h`/`v`; default from the camera words), `thr` (depth split; default Otsu) | two planes: the subject (nearer than the depth histogram's Otsu split) and the background with the subject's hole filled by push-pull from its surroundings; they drift against each other over the shot, edges never show. `m.matte()` is the subject plane, so lyric blocks and devices set `behind` tuck behind the subject. A plate whose depth has no such split (no figure stands nearer than the rest, or nearly everything is near) draws `layers` instead — reported when the page boots, with the neighbour named if it draws `layers` too | EV's takeoff chapter: the campus falling away under a lifting figure; a slow orbit with planes sliding |
| `rack` (LS) | `at` (time; default 1 beat in), `from` .2, `to` subject depth, `width` .14, `blur` 9 | soft, then the focus plane travels to the subject on the beat | EV: autofocus hunting then locking on an eye; racking to a card on a table |
| `relight` (DI) | `per_beat` 1, `width` .06, `alpha` .55, `tint` `#ffffff` | a light band travels front → back through the depth once per beat | EV: a relight wave per beat when the room drops |
| `contours` (DI) | `levels` [.15….95], `alpha` .6, `color` | iso-depth lines of the real depth map, one more level per eighth | SP: the depth map drawn as terrain while descending |
| `scan` (DI) | `alpha` .8, `color` | a CV sweep per beat leaves a point cloud of the depth behind it (the sweep line takes an accent) | EV: a depth scan of a road; a lidar point cloud in fog |
| `stills` (SR) | `crops` [{zoom, cx, cy, s}] (auto: wide / face / mid / detail from the subject box — gentler on a close-up; never magnified past ~1.6 screen px per plate px, so on a plate narrower than the frame — 1456 px at 1920 wide is already 1.32 × — the crops' zoom is capped near 1.21 and FACE / DETAIL come out gentler; write your own `crops` for tighter ones), `step` 1 beat, `loop` false, `flash` true (false when auto-picked), `strip` true | the image re-cropped on every step (the index runs .03 of a step early and **holds the last crop**; `loop: true` cycles), a one-frame flash per crop (through the flash rule), a contact strip whose selected frame takes an accent | EV: four crops on the beat ending on a price tag; SP: snap zooms through a montage |
| `xerox` (RP) | `kind`: `xerox` (1-bit photocopy boiling on eighths) · `thermal` (prints down the frame on 16ths; the print head takes an accent) — print texture, **never picked in a clean look** · `mosaic` (ENHANCE: blocks resolve on each beat) · `tiles` (the frame assembles as split-flap tiles flipping on 16ths in a diagonal wave over `wave` 1.5 beats, then one column re-flips on each beat; `cols`/`rows` default 16 × 9, 9 × 16 in portrait) — clean | the frame reproduced through a medium | EV: the frame printed as a thermal receipt; a forensic "enhance"; the photocopy chapter; the whole frame as one split-flap board |
| `diagram` (DG) | — | thirds grid, a crosshair and a dimension line on the subject (the device carries the meaning) | EV: a tech pack of an outfit; a plate cropped into a bar chart |
| `motion` (PM) | `ground` `paper`/`night`, `spacing` 48 | no footage: a ground and a dot grid breathing on the kick | EV's full-frame terminals and departure boards; SP's chat-app screens |
| `occlusion` (OC) | — | the push, with every lyric block of the shot tucked behind the subject | SP: type tucked behind hair, a mast, a mask |

---

## 7. Transitions (`transition_in`)

A preset name, prose (`"whip left"`, `"push through the pupil"`, `"flash cut"`), or `{"preset": "whip", "dir": "left", …}`.
Centred on the shot's cut (which is on a beat). **Most cuts stay hard cuts**; use one of these every few shots, as an
idea (the graphic of one shot becomes the frame of the next), never the same one as the shot before.

Prose is read most specific first; prose that **starts with "cut"** is a cut (`"cut into the chorus"` is not a
push-through). Any other name the engine's own registry knows (`ENGINE.transitions`: `luma`, `bands`, `zoom`, `wrap`, and
any a project registers) is played through it. A name nobody knows is a hard cut **and a warning** listing the names.

| preset | params (defaults) | what it does | precedent |
|---|---|---|---|
| `through` | `dur` .3, `depth` 5, `a` [x,y] (default A's subject), `b` [x,y] (default B's subject) | push through a point of A and come out of a point of B — a match cut on shape | SP: through a pupil into clouds, through a check mark, through an ear |
| `whip` | `dur` .3, `dir` (radians or `left`/`right`/`up`/`down`) 0, `dist` 760, `blur` 340 | a whip pan that wraps (no black edge), two smear passes (no banding); vertical whips mirror the wrap (no seam) | SP: whips continuing a head turn; a vertical whip |
| `flashCut` | `dur` .2, `invert` true, `frames` 1 | a hard cut whose first frame is B in inverted black and white (counts toward the flash rule) | SP: a flash on the kick |
| `dither` | `dur` .45 | an ordered-dither dissolve (Bayer 8×8, 1/4 res); overlay and look switch at the cut. **Print texture: in a clean look it is drawn as `fade`** | EV chorus 2 and bridge dissolves |
| `fade` | `dur` .4 | a plain crossfade; overlay and look switch at the cut (also `crossfade`) | the clean look's dissolve |
| `flap` | `dur` .5, `cols` 16, `rows` 9 | the frame flips like a split-flap board, a wave from the upper left (both layers) | EV: the board wipe; the whole frame as one flap cell |
| `smear` | `dur` .3, `bands` 7, `amp` 220 | a photocopier scan band drags rows through the cut (print texture: reported in a clean look) | EV's scan/xerox cuts |
| `match` | `dur` .5 | B's subject starts where A's was and eases to rest (never off target, never an exposed edge) | EV: subject-to-subject match cuts |
| `flash` | `dur` .2, `frames` 1 | a one-frame paper flash on the cut (counts toward the flash rule) | EV: a one-frame ink flash on a click |
| `iris` | `dur` .5, `shape` `circle`/`spark`, `at` [x,y] | B revealed through a growing circle (or spark) from A's subject | EV: a ring-light iris; the spark iris close |
| `push` | `dur` .4, `dir` 1 (±1 horizontal, ±2 vertical) | B pushes A out with motion streaks | EV chapter 2's vertical push |

The through / match / iris transitions use each shot's subject box (§4); without one they work from the frame centre.

---

## 8. The device catalogue

Each entry: the `kind` (aliases), its **role** in the budget, what it **explains**, its params with defaults, the timing
keys it reads, an example `devices[]` entry, and the precedent. All text params are uppercased by the device unless
noted. Every graphic fades out over `fadeOut` seconds (default 0.2) after its `until`; flashes and camera moves stop dead.
Placed devices keep inside the margins; a device too big for the safe area (e.g. `departures` in portrait) is scaled down.

### `cv.bracket`
Aliases `bracket`, `brackets`, `det`, `cv.det` (`det` = the detection style with a chip). **Role cv.**
**Explains:** a detection — corner brackets on a thing in frame with its class and confidence: the machine classifies
what we see (reclassify on the word: two instances with different labels, the second keyed `W`).

| param | default | meaning |
|---|---|---|
| `label` | `""` | class text |
| `conf` | `null` | confidence (two decimals) |
| `style` | `corners` | `corners` (grows in over an eighth) · `det` (corners then edges over ¼ beat, label in a solid chip) |
| `len` | .16 | corner length (fraction of the short side) |
| `lw` | 1.5 | line width |
| `cross` | false | a crosshair at the centre |
| `jitter` | 0 | px of jitter on eighths |
| `chip` | false | `det` style: the chip in the accent |

Keys: W B H F T. Anchor: a box (`lead`, a uv box, a rect, a detection). The label (and score) sits above the box's
top-left corner; when that is on a lyric block or out of frame it goes above the top-right, then below the box, else it
is left off — the brackets still frame (§1, the collision rule). The `det` chip moves the same way.
```json
{"kind": "cv.bracket", "anchor": "lead", "key": "W", "params": {"word": "stranger", "label": "UNKNOWN · 01", "conf": 0.62}}
```
Precedent: EV detected a front row of laptops as agents on 32nds and reclassified a jacket on the word; SP put brackets on
the cast in nearly every shot.

### `cv.lock`
Aliases `lock`, `rangefinder`. **Role cv.** **Explains:** a range-finder closing in and locking — the moment something is
identified, targeted or chosen.

| param | default | meaning |
|---|---|---|
| `from` | 220 | starting pad around the box (px) |
| `lock` | `null` | when it locks (time spec; default 1 beat after the start) |
| `rows` | `[]` | rows beside the box (row 0 reads `searching` until locked, then turns the accent) |
| `searching` | `ACQUIRING…` | the searching label |

Keys: W B H F T. The rows go right of the frame, else left, off any lyric block (else none).
```json
{"kind": "cv.lock", "anchor": {"uv": [0.55, 0.22, 0.16, 0.3]}, "key": "W", "params": {"word": "found", "lock": {"beats": 1}, "rows": ["MATCH · 0.98", "ID · CONFIRMED"]}}
```
Precedent: SP's range-finder that locks on in the first chorus and is called back near the end.

### `cv.tag`
Aliases `tag`, `tagq`, `cv.tagq`. **Role cv.** **Explains:** a fast CV tag — a dot on the thing, a leader, a few rows of
facts that finish typing within the beat.

| param | default | meaning |
|---|---|---|
| `rows` | `[]` | the facts (≤ 4 rows) |
| `dx`, `dy` | 90, −50 | the leader's offset (px) |
| `size` | 13 | row size |
| `w` | 260 | row block width |
| `fast` | true | ≥ 40 characters/s (finishes within ¾ beat); `false` = 3 characters a 16th (`per16`) |
| `per16` | 3 | characters per 16th when not fast |

Keys: W B H F T. Anchor: a point (or a box's centre). Rows that would sit on a lyric block or leave the frame flip the
leader left, up, or both (a way whose leader runs clear of the lyric first); with nowhere free the dot and leader draw
without rows, the leader taking a way clear of the lyric.
```json
{"kind": "cv.tag", "anchor": {"uv": [0.66, 0.5]}, "key": "H", "params": {"hit": "snare", "rows": ["LAMP · 2700 K", "ON SINCE 06:12"], "dx": 150, "dy": -120}}
```
Precedent: SP's second chorus: tags that must finish within the beat of their hit.

### `callout`
Aliases `cv.callout`, `annotation`. **Role cv.** **Explains:** an editorial callout — points at a detail and explains it
in two or three typed rows (a measurement, a material, a source).

| param | default | meaning |
|---|---|---|
| `rows` | `[]` | ≤ 3 rows, typed 3 characters a 16th after the leader |
| `dx`, `dy` | 140, −90 | the elbow's offset |
| `size` | 13 | row size |
| `per16` | 3 | typing speed |
| `colors` | — | per-row colours |

Keys: W B H F T. Rows that would sit on a lyric block or leave the frame flip the elbow (as `cv.tag`).
```json
{"kind": "callout", "anchor": {"uv": [0.31, 0.62]}, "key": "B", "params": {"beat": 1, "rows": ["KEY · BRASS", "Ø 24 MM"]}}
```
Precedent: EV measured a hair clip before it became the next transition, and called out the parts of an outfit.

### `leader`
Alias `cv.leader`. **Role cv.** **Explains:** a line from a thing to a label or to another thing — connects cause and
effect, a part to its name.

| param | default | meaning |
|---|---|---|
| `to` | `null` | the far end: `[x, y]` or an anchor spec (default: the anchor + `dx`,`dy`) |
| `dx`, `dy` | 160, −60 | offset when `to` is missing |
| `label` | `""` | a chip at the far end |
| `fill` | false | a filled dot at the anchor |

Keys: W B H F T. A chip that would sit on a lyric block flips the leader (no `to`; a way that runs clear of the lyric first) or is left off (with `to`).
```json
{"kind": "leader", "anchor": {"uv": [0.4, 0.55]}, "key": "B", "params": {"to": {"slot": "top-right"}, "label": "02 · THE DOOR"}}
```
Precedent: EV tied garment parts and seating rows to their detections.

### `cv.lead`
Alias `lead`. **Role cv** (lowest priority; added automatically on `lead_on_screen` shots that have a subject box).
**Explains:** the lead's identity mark — brackets with a stable label so the viewer tracks who the video is about.

| param | default | meaning |
|---|---|---|
| `label` | `null` | default `PROJECT.chrome.lead_label`, else `LEAD · 01` |
| `conf` | .97 | confidence |
| `face` | false | a face cross too (automatic on CU/MCU/ECU framings) |

Keys: B. Anchor: `lead` (the subject box, §4). Its label flips like the `cv.bracket` label, so "LEAD · 01 0.97" is never
under a lyric word.
```json
{"kind": "cv.lead", "anchor": "lead", "params": {"label": "MODEL 01", "face": true}}
```
Precedent: both videos' lead kit on every shot of the lead.

### `cv.outline`
Aliases `outline`, `segmentation`. **Role cv.** **Explains:** a segmentation outline traced on the subject (matte, else
the depth key) — the machine sees the subject's shape.

| param | default | meaning |
|---|---|---|
| `dash` | [6, 6] | dash pattern |
| `lw` | 1.4 | line width |
| `label` | `""` | a label above the box |

Keys: W B H F. Needs a matte or depth (occ.js); otherwise falls back to brackets on the subject box.
```json
{"kind": "cv.outline", "anchor": "lead", "key": "W", "params": {"word": "shape", "label": "SEGMENT · PERSON 0.99"}}
```
Precedent: SP's occlusion kit (the matte's edge drawn as a segmentation line).

### `ui.chip`
Aliases `chip`, `badge`, `pill`. **Role cv.** **Explains:** an interface's own label about what we see (a platform's
badge, a status pill); `full` types the longer disclosure in on a later word.

| param | default | meaning |
|---|---|---|
| `text` | `LABEL` | the pill text |
| `full`, `full_at` | `null` | the longer text and when it starts typing (time spec) |
| `size` | 15 | text size |
| `cps` | 2 | characters a 16th for `full` |
| `icon` | true | the spark icon in the accent |

Keys: W B H F T. Place with `x`,`y` or an anchor.
```json
{"kind": "ui.chip", "key": "W", "params": {"word": "radio", "x": 1080, "y": 118, "text": "LIVE", "full": "LIVE · REQUESTS OPEN", "full_at": "open", "cps": 5}}
```
Precedent: SP opened on a streaming app's own disclosure label over the spoken first line.

### `ui.chatbar`
Aliases `chatbar`, `chat.input`. **Role hero.** **Explains:** a chat input typing the line's question and sending it.

| param | default | meaning |
|---|---|---|
| `text` | `ask me anything` | what is typed (2 characters a 16th) |
| `placeholder` | `Message…` | the empty field |
| `send` | `null` | when it sends (time spec; default after typing) |
| `w`, `h`, `size`, `cps` | 760, 76, 30, 2 | geometry and speed |

Keys: W B H F T.
```json
{"kind": "ui.chatbar", "anchor": {"slot": "bottom-right"}, "key": "W", "params": {"word": "ask", "text": "are you still up?", "send": {"beats": 3}}}
```
Precedent: SP typed the line's question into a chat bar and sent it on the beat.

### `ui.chat`
Aliases `chat`, `bubbles`, `ui.bubble`, `bubble`. **Role hero.** **Explains:** an exchange with a machine, bubbles popping
on the beat.

| param | default | meaning |
|---|---|---|
| `msgs` | two sample bubbles | `[{who: "user"|"ai", text, b (beats after start) | at (time spec)}]` |
| `size`, `w`, `gap` | 24, 560, 16 | geometry |

Keys: W B H F T.
```json
{"kind": "ui.chat", "key": "B", "params": {"msgs": [{"who": "user", "text": "you up?", "b": 0}, {"who": "ai", "text": "always.", "b": 1}]}}
```
Precedent: EV's chat bubbles and its wall of agreeable replies; SP's chat-app screens.

### `terminal`
Aliases `term`, `console`, `gfx.terminal`. **Role hero.** **Explains:** an agent/terminal session typed on the beat —
the work the line describes, as the machine does it.

| param | default | meaning |
|---|---|---|
| `script` | a 4-line sample | `[{b (beats) | at (time spec), k, s, verb, speed}]`; `k`: `prompt` · `think` (spinner + verb) · `tool` · `out` · `add` · `del` · `ai` · `limit` (an accent banner) · `sys`; `s` must be text |
| `title`, `cwd`, `model`, `status` | `agent`, `~/project`, `""`, `? for shortcuts` | header and footer text (no product names by default) |
| `w`, `h`, `size`, `lh` | 700, 300, 20, 32 | geometry |
| `theme` | `dark` | or `light` |

Keys: W B H F T.
```json
{"kind": "terminal", "key": "W", "params": {"word": "build", "title": "shell", "cwd": "~/garden", "status": "3 jobs · 02:14",
  "script": [{"b": 0, "k": "prompt", "s": "water --all"}, {"b": 1, "k": "think", "verb": "Watering"}, {"b": 2, "k": "tool", "s": "Run(zones.sh)"}, {"b": 3, "k": "out", "s": "12/12 zones done"}]}}
```
Precedent: EV showed an agent loop keeping a rack of machines up all night, and a quota banner landing on the word.

### `label`
Aliases `garment.tag`, `garmentTag`, `tag.card`, `spec.label`, `lookcard`, `card.label`. **Role hero.** **Explains:** a
spec label (a woven care tag) — classifies a person or thing as a product with field:value rows.

| param | default | meaning |
|---|---|---|
| `title` | `TITLE` | the big name |
| `kicker`, `badge`, `serial` | `""` | micro header, an accent badge, a serial + barcode |
| `rows` | `[["FIELD","VALUE"]]` | field:value rows (one more per eighth) |
| `w`, `rot`, `swing`, `scale` | 300, 0, 0, 1 | geometry; `swing` = a pendulum on the beat (radians) |
| `care`, `nerf` | true, false | care symbols; `nerf` crosses the last one |
| `ink`, `paper` | `#121212`, `#f4f2ec` | colours |

Keys: W B H F T.
```json
{"kind": "label", "key": "W", "params": {"word": "jacket", "title": "NIGHT JACKET", "kicker": "ITEM 04 / 09", "serial": "NJ-04-0001", "rows": [["SHELL", "WAXED COTTON"], ["LINING", "WOOL"], ["SIZE", "M"]]}}
```
Precedent: EV set its title as a garment tag, gave every look line its own look card, and closed on a shipping label.

### `sheet`
Aliases `panel`, `receipt`, `spec.sheet`, `readings` (`receipt` implies the paper style). **Role hero.** **Explains:** the
line's numbers as a document — a perception log, a readout panel, a bill.

| param | default | meaning |
|---|---|---|
| `title` | `READINGS` | header |
| `rows` | `[["FIELD","VALUE"]]` | `[field, value, state?]` — `hot` = accent row, `strike` = struck (one row per 16th) |
| `style` | `panel` | `panel` (dark instrument panel) · `receipt` (paper with a torn edge) |
| `total` | `null` | `[label, value]` under a rule |
| `hl` | — | a highlighted row index |
| `w`, `size`, `per16` | 470, 15, 1 | geometry, rows per 16th |

Keys: W B H F T.
```json
{"kind": "sheet", "key": "W", "params": {"word": "rent", "style": "receipt", "title": "MONTHLY", "rows": [["RENT", "$1,200"], ["COFFEE", "$310", "hot"], ["BUS", "$64"]], "total": ["COFFEE / RENT", "25.8%"]}}
```
Precedent: EV read out a self-driving car's perception log as a panel, and printed a payslip as a thermal receipt.

### `stamp`
Aliases `rubber.stamp`, `slap`. **Role hero.** **Explains:** a verdict slammed on on the word (FILED, VOID, DENIED).

| param | default | meaning |
|---|---|---|
| `text` | `APPROVED` | the verdict |
| `sub` | `""` | micro line under it |
| `size`, `rot` | 74, −.14 | size, rotation (radians) |

Keys: W B H F T.
```json
{"kind": "stamp", "key": "W", "params": {"word": "done", "text": "FILED", "sub": "FORM 7 · CHECKED"}}
```
Precedent: EV turned a buckle's click into a stamp, stamped a campaign as retired, and stamped a status change on the word.

### `strike`
Aliases `strikethrough`, `erratum`, `correction`. **Role hero.** **Explains:** a correction or escalation — the old
claim struck out, the new one written under it.

| param | default | meaning |
|---|---|---|
| `words` | `[["ALWAYS",true],["SOMETIMES",false]]` | the row: `[text, struck?]` |
| `next`, `next_at` | `null` | the replacing row and when it types in (time spec; default 1 beat) |
| `size` | 96 | size (keep it under the lyric's unless the strike is the line) |

Keys: W B H F T.
```json
{"kind": "strike", "key": "W", "params": {"word": "write", "words": [["I'LL", false], ["CALL", true]], "next": [["I'LL", false], ["WRITE", false]], "next_at": "write", "size": 64}}
```
Precedent: SP struck a promise and wrote a stronger one under it; EV's struck tokens and the erratum on the care label.

### `redact`
Aliases `redaction`, `blackout`. **Role hero.** **Explains:** what is hidden — words blacked out on the beat (and lifted).

| param | default | meaning |
|---|---|---|
| `rows` | `[["THE SOURCE IS",false],["CLASSIFIED",true]]` | `[text, redacted?]` per line (bars sweep a quarter beat each) |
| `lift` | `null` | when the bars slide off (time spec) |
| `size`, `w` | 28, 620 | geometry |

Keys: W B H F T.
```json
{"kind": "redact", "key": "W", "params": {"word": "address", "rows": [["THE ADDRESS IS", false], ["NOT LISTED", true]], "lift": {"beats": 4}}}
```
Precedent: SP's redaction bar as a through-line across a chorus.

### `title.knockout`
Aliases `knockout`, `title`. **Role hero.** **Explains:** the title as a knockout — the word cut out of black so the
footage shows only through its letters; the subtitle lands under it on the sung word. Use when the device **is** the line.

| param | default | meaning |
|---|---|---|
| `word` | `PROJECT.title` | the knocked-out word (its text — not a timing word: time it with `token`, `at` or `key`) |
| `sub` | `null` | the subtitle text (default: the token's text) |
| `token` | `null` | `[line, index]`: the sung token — drawn on its time and marked for the lyric gate |
| `fill`, `w`, `subSize` | `#050505`, W−120, 64 | colours, letter width, subtitle size |

Keys: W B F.
```json
{"kind": "title.knockout", "key": "W", "params": {"word": "Claudia", "token": [12, 3]}}
```
Precedent: SP knocked its title out of black with the subtitle landing on the sung word.

### `title.card`
Aliases `lockup`, `title.lockup`, `card.title`. **Role hero.** **Explains:** a title lockup that opens or closes a section.

| param | default | meaning |
|---|---|---|
| `title` | `PROJECT.title` | the title |
| `sub`, `kicker` | `""` | the accent sub line, a micro kicker |
| `w` | 900 | width |

Keys: W B H F.
```json
{"kind": "title.card", "anchor": {"slot": "top-left"}, "key": "B", "params": {"title": "CHAPTER II", "sub": "the instances", "kicker": "II · 00:10"}}
```
Precedent: SP's end-card lockup.

### `flap`
Aliases `splitflap`, `split-flap`, `flapboard`, `countdown`. **Role hero.** **Explains:** a status, count or headline
that flips to its new value on the word — a countdown, a verdict, a departure.

| param | default | meaning |
|---|---|---|
| `rows` | `[{"text":"ON TIME","prev":"DELAYED"}]` | `{text, prev, at (time spec; default ½ beat per row), accent}` |
| `cells` | longest row | cells per row |
| `cw`, `ch`, `gap`, `spin` | 40, 62, 4, 6 | cell size, glyphs cycled per flip |
| `label`, `sub` | `""` | micro header and footer |

Keys: W B H F T.
```json
{"kind": "flap", "key": "W", "params": {"word": "late", "label": "PLATFORM 2", "rows": [{"text": "DELAYED", "prev": "ON TIME", "accent": true}], "sub": "LAST TRAIN"}}
```
Precedent: EV ran a countdown board through the whole film, resolved a hedge on a board, and flipped a status on the word.

### `departures`
Aliases `board`, `flap.board`. **Role hero.** **Explains:** a list whose statuses flip in turn — a schedule, a roll
call, a leaderboard.

| param | default | meaning |
|---|---|---|
| `title`, `status` | `DEPARTURES`, `STATUS` | headers |
| `rows` | one sample row | `{label, value, prev, flip (time spec), accent, sub}` |
| `cw`, `ch`, `labelCells`, `valueCells` | 44, 70, 18, 9 | geometry (≈ 1016 px wide: scaled down in the portrait cut) |

Keys: W B H F T.
```json
{"kind": "departures", "key": "B", "params": {"title": "LAST TRAINS", "rows": [{"label": "NORTH", "value": "BOARDING", "prev": "ON TIME"}, {"label": "SOUTH", "value": "CANCELLED", "prev": "ON TIME", "accent": true, "flip": {"beats": 1}}]}}
```
Precedent: EV's board chapters.

### `counter`
Aliases `odometer`, `count`, `inst.counter`. **Role hero.** **Explains:** the stakes ticking — an amount, a count, a copy
number rolling to the line's number on the beat.

| param | default | meaning |
|---|---|---|
| `from`, `to`, `beats` | 0, 100, 3.2 | the roll (beats of the beat map); or `to_at` (time spec) for its end |
| `keys` | — | keyed values instead of a roll |
| `format` | `int` | `int` · `fixed1` · `fixed2` · `pct` · `usd` · `si` · `times` (×N) · a template with `{v}` |
| `prefix`, `suffix`, `dp` | `""`, `""`, null | text around it, decimals |
| `size`, `style`, `align` | 120, `odometer`, `left` | `odometer` (rolling digits, tech mono) · `sign` (condensed black) |
| `label` | `""` | micro label under it |

Keys: W B H F T. A big counter is the line's number: set `is_line: true` when it carries the line, else keep `size` under
the lyric's.
```json
{"kind": "counter", "key": "W", "params": {"word": "miles", "from": 0, "to": 2400, "format": "{v} MI", "beats": 3.2, "label": "SINCE SPRING", "is_line": true}}
```
Precedent: EV rolled an odometer to a deal's value; SP counted copies of one model up by powers of two.

### `gauge`
Aliases `readout`, `load`, `meter.gauge`, `usage`, `progress` (bar), `dial`, `half.dial` (half), `thermo`,
`thermometer` (thermo), `limitbar` (bar). **Role hero.** **Explains:** a keyed physical/abstract quantity (load, risk,
usage, temperature) — the through-line that escalates across shots.

| param | default | meaning |
|---|---|---|
| `style` | `tag` | `tag` (a load-cell tag on a leader from the anchor) · `half` (a half dial) · `thermo` · `bar` (a usage bar) |
| `value` / `keys` | 0 / — | a fixed value, or keyed values landing on their times |
| `unit`, `max`, `mark` | `""`, 100, null | unit text, the scale's max, a tick at a value |
| `warn`, `red` | null | thresholds: warn/red turn the value to the accent; red blinks ⚠ on the beat |
| `label`, `dp`, `done` | `READOUT`, auto, `""` | label, decimals, the bar/thermo text at max |
| `dx`, `dy`, `r`, `w` | 70, −110, 130, 420 | tag offset, dial radius, bar width |

Keys: W B H F T.
```json
{"kind": "gauge", "anchor": {"uv": [0.62, 0.60]}, "key": "W", "params": {"style": "tag", "unit": "°C", "max": 42, "mark": 37, "warn": 37.5, "red": 38.5, "dp": 1,
  "label": "FEVER · NIGHT 3", "keys": [["warm", 36.6], [{"beats": 4}, 37.9], [{"hit": "impact"}, 39.1, 0.3]]}}
```
Precedent: SP carried one physical load reading that climbed across the whole film, and a risk dial; EV pinned a
thermometer and stepped a usage meter to 100 %.

### `tally`
Aliases `count.marks`, `marks.count`, `tallystrip`. **Role hero.** **Explains:** a count made visible mark by mark on the
16ths (cars waiting, people online, days).

| param | default | meaning |
|---|---|---|
| `n` | 20 | the total |
| `per` | 16 | 16 = one mark a 16th, 32 = a 32nd |
| `style` | `tally` | `tally` (groups of five) · `bar` (cells) · a glyph (`glyph`) |
| `label`, `of`, `size` | `COUNT`, true, 34 | readout, show "/ n", size |

Keys: W B H F T.
```json
{"kind": "tally", "key": "W", "params": {"word": "days", "n": 30, "label": "DAYS AWAY"}}
```
Precedent: EV tallied cars stuck in fog; SP scratched tally marks into wood.

### `chart`
Aliases `gfx.chart`, `graph`, `curve`. **Role hero.** **Explains:** the curve the line implies, drawn on in beats and
labelled as it passes.

| param | default | meaning |
|---|---|---|
| `type` | `exp` | `exp` · `lev` · `tick` · `osc` · `linear` · `log` · `flat` · `drop` · `s` |
| `points` / `values` | — | data: `[[u, v], …]` in 0..1, or values (with `ymin`, `ymax`) |
| `beats` | 8 | draw-on length (beats) |
| `title`, `xlab`, `ylab` | `""` | labels |
| `ref`, `refLabel` | null | a dashed reference line (0..1) in the accent |
| `labels` | `[]` | `[{u, s}]` popping when the head passes |
| `value` | null | `{from, to, format, dp, prefix, suffix}`: the head's readout |
| `w`, `h`, `lw` | 520, 300, 2.2 | geometry |

Keys: W B H F T.
```json
{"kind": "chart", "key": "W", "params": {"word": "rising", "type": "exp", "beats": 3, "title": "water level", "xlab": "march", "labels": [{"u": 0.92, "s": "now"}]}}
```
Precedent: EV drew an exponential chart asking where on the curve we stand, an escape-velocity curve for longevity, and a
breakout chart.

### `sparkline`
Aliases `spark.line`, `trend`. **Role hero.** **Explains:** a trend in a glance beside the thing (a price, a count).

| param | default | meaning |
|---|---|---|
| `values` | 8 sample values | the series |
| `beats` | 2 | draw-on length |
| `label`, `format`, `dp`, `suffix` | `""`, `int`, null, `""` | readout |
| `w`, `h` | 260, 56 | geometry |

Keys: W B H F T.
```json
{"kind": "sparkline", "anchor": {"uv": [0.12, 0.7, 0.1, 0.16]}, "key": "B", "params": {"values": [12, 14, 13, 18, 22, 21, 30, 41], "label": "VISITS · 30 D"}}
```
Precedent: generalised from EV's small charts and readouts.

### `plot`
Aliases `inst.plot`, `doubling`, `scatter`. **Role hero.** **Explains:** growth made literal — points land on the words,
the curve runs to the newest.

| param | default | meaning |
|---|---|---|
| `pts` | four doubling points | `[{x, y?, at (time spec)}]` |
| `fn` | `pow2` | `pow2` (y = 2^x) · `linear` · `points` (through each `y`) |
| `xmax`, `ymax` | 10, 1024 | axes |
| `xlab`, `ylab` | `n`, auto | labels |
| `w`, `h` | 520, 300 | geometry |

Keys: W B H F T.
```json
{"kind": "plot", "key": "W", "params": {"word": "doubles", "fn": "pow2", "xlab": "weeks", "pts": [{"x": 0, "at": "one"}, {"x": 7, "at": "doubles"}, {"x": 10, "at": {"beats": 3}}]}}
```
Precedent: SP plotted a doubling curve beside its copy counter.

### `ecg`
Aliases `heartbeat`, `ekg`. **Role hero.** **Explains:** a body under stress, panic or love — the heartbeat **is** the
song's beat map; the rhythm can break on a word.

| param | default | meaning |
|---|---|---|
| `bigeminy_at` | null | when an extra beat starts landing between every other pair (time spec) |
| `w`, `h`, `sweep` | 640, 90, 3.2 | geometry, sweep seconds |
| `label`, `status`, `big_label` | `ECG`, `SINUS · nnn BPM`, `IRREGULAR · EXTRA BEATS` | text |

Keys: W B H F.
```json
{"kind": "ecg", "key": "B", "params": {"bigeminy_at": "panic"}}
```
Precedent: SP's third verse, where a steady trace breaks into an extra beat on a word; EV's heart-rate-equals-tempo chart.

### `arrow`
Aliases `big.arrow`, `pointer`. **Role hero.** **Explains:** direction as meaning (it rose, it fell, over there).

| param | default | meaning |
|---|---|---|
| `dir` | `up` | `up` · `down` · `left` · `right` · radians |
| `len`, `width` | 420, 70 | size |
| `label` | `""` | micro label at the tail |

Keys: W B H F.
```json
{"kind": "arrow", "key": "W", "params": {"word": "down", "dir": "down", "label": "TEMPERATURE · −12 °C"}}
```
Precedent: SP's big accent arrow on a line about something rising.

### `voice`
Aliases `spectrum`, `spec`, `spec.line`/`voice.line` (line), `spec.bars` (bars), `spec.beam`/`voice.beam`/`ribbon`
(beam), `spec.rings`/`voice.rings` (rings), `orb`/`voice.orb` (orb). **Role hero.** **Explains:** the singer's actual
voice as a shape — the sound travelling to a listener, rings on the water, a breathing orb.

| param | default | meaning |
|---|---|---|
| `style` | `bars` | `line` · `bars` · `beam` (from the anchor to `to_pt`) · `rings` (born on each kick) · `orb` |
| `stem` | `vocals` | `vocals` · `mix` |
| `w`, `h`, `n`, `from`, `to`, `gain`, `lw`, `mirror` | 520, 120, 32, 4, 60, 1.15, 2, false | spectrum geometry and band range |
| `to_pt`, `width`, `lines`, `speed` | null, 40, 3, 900 | beam: target, half-width, strands, px/s |
| `aspect`, `life`, `decay`, `disp` | .2, 1.6, .6, .06 | rings |
| `r` | 110 | orb radius |
| `label` | `""` | micro label |

Keys: B H F. Reads `window.SPECTRUM` (24 fps × 64 bands); without it, bands are synthesised from the stem envelope.
```json
{"kind": "voice", "anchor": {"uv": [0.35, 0.45]}, "key": "W", "params": {"word": "call", "style": "beam", "to_pt": {"uv": [0.8, 0.3]}}}
```
Precedent: SP sent the singer's voice across water as a ribbon, rang rings on each kick, and breathed an orb.

### `spark`
Aliases `burst`, `star`. **Role hero.** **Explains:** an accent mark that pops in and blooms on every kick — a sign-off,
a "this one".

| param | default | meaning |
|---|---|---|
| `r`, `rays`, `width` | 90, 12, .075 | shape |
| `bloom`, `spin`, `inBeats` | .12, .08, 1 | kick bloom, spin per beat, back-out entrance (beats) |
| `even`, `seed` | false, 1 | equal rays, ray-length seed |

Keys: W B H F.
```json
{"kind": "spark", "anchor": {"slot": "top-right"}, "key": "W", "params": {"word": "spark", "r": 80}}
```
Precedent: EV's eight-point spark (a measured hair clip; the closing iris).

### `flash`
Aliases `flash.mono`, `flash.invert`, `flash.paper`, `flash.card`/`card.flash`/`card` (card). **Role flash.**
**Explains:** a full-frame hit — the frame in hard black and white on a shout, or a sign card. **Max 3 per second**
(the planner drops the rest, around the transitions); never on quiet lines, never as decoration.

| param | default | meaning |
|---|---|---|
| `kind` | `mono` | `mono` · `invert` · `paper` · `black` · `card` |
| `frames` | 1 | frames per flash (mono/invert/paper/black) |
| `every`, `times` | null, [] | repeat every N beats until the end · extra start times |
| `dur` | ½ beat | a card's length |
| `sign`, `glyph` | `prohibit`, `""` | card pictogram: `prohibit` · `mandatory` · `warn` · `info`, with a short glyph |
| `caption`, `number`, `of`, `label` | `""`, null, null, `CARD` | card text (commas break lines), its number disc |
| `line` | null | the card **is** this lyric line: its words so far become the caption (marked for the gate; the lyric block steps aside) |
| `contrast`, `invert` | 1.35, — | mono contrast; card white-on-black or inverted |

Keys: W B H F. In portrait the card sets the sign above the caption inside the safe margins.
```json
{"kind": "flash", "key": "W", "params": {"word": "gap", "kind": "card", "sign": "warn", "glyph": "!", "caption": "MIND THE GAP", "number": 1, "of": 3, "label": "NOTICE"}}
```
Precedent: SP flashed a numbered instruction card on each shouted order, black-and-white frames on the hits, and
quarter-note flashes in the outro (≈ 2.2/s); EV's one-frame paper flash on a click.

### `mass`
Aliases `wall`, `declared.mass`. **Role hero.** **Explains:** volume — a declared wall of micro text (every message,
every copy, every rule at once), flickering on eighths.

| param | default | meaning |
|---|---|---|
| `lines` | every lyric | the wall's lines |
| `rows`, `keep`, `density`, `size`, `scroll` | 40, 9, .75, 13, false | rows, the row kept lit, on-ratio, size, scroll per eighth |

Keys: B F W.
```json
{"kind": "mass", "key": "B", "params": {"lines": ["SEE YOU SOON", "MISS YOU", "CALL ME BACK"], "rows": 30}}
```
Precedent: EV's chant wall in the drop chapter.

### `typed`
Aliases `micro`, `source`, `rows`, `caption.micro`. **Role micro** (counts its rows toward the frame's 3). **Explains:**
sources cited on screen — a date, a source, "(paraphrase)", typed on the 16ths.

| param | default | meaning |
|---|---|---|
| `rows` | `["SOURCE · 2026"]` | ≤ `max` rows |
| `size`, `per16`, `max`, `align`, `w` | 13, 3, 3, `left`, 520 | type, speed, row cap, alignment, width |

Keys: W B H F T.
```json
{"kind": "typed", "anchor": {"slot": "bottom-left"}, "key": "W", "params": {"word": "said", "rows": ["SRC · CITY RECORDS · 1987", "PARAPHRASE"]}}
```
Precedent: the source rows under EV's coverlines; SP's sources and dates in micro type.

### `ticker`
Aliases `crawl`, `ann.ticker`. **Role micro** (one row). **Explains:** the world reacting in the background — a strip
scrolling on the beat.

| param | default | meaning |
|---|---|---|
| `items` | two samples | the items |
| `y`, `pxPerBeat`, `sep`, `bg` | H−30 (portrait: above the bottom margin), 60, `   ✱   `, null | position, speed (px per beat), separator, band colour |

Keys: B F.
```json
{"kind": "ticker", "key": "B", "params": {"items": ["WEATHER · CLEAR", "TRAINS · ON TIME", "LIVE"]}}
```
Precedent: EV's chrome ticker.

### `marks`
Aliases `cropmarks` (crop), `ruler`/`ann.ruler` (ruler), `grid` (grid). **Role micro** (the ruler counts one row).
**Explains:** the frame as a document being measured — printer's crop marks, a beat ruler, a grid with a crosshair.

| param | default | meaning |
|---|---|---|
| `style` | `crop` | `crop` · `ruler` (bar numbers from the beat map, never negative) · `grid` |
| `inset`, `len`, `spacing` | 28, 16, 22 | geometry |

Keys: B F.
```json
{"kind": "marks", "key": "B", "params": {"style": "ruler"}}
```
Precedent: EV's crop marks and beat ruler in the chrome.

### `quad`
Aliases `print.quad`, `print-on-quad`, `homography`, `surface`, `sign.face` (content `sign`), `screen.quad` (content
`screen`). **Role hero.** **Explains:** the thing in frame says the line — a sign face, a screen or a printed page **inside
the picture**, mapped onto four measured points of the plate by a homography (it follows the camera and the 2.5D move), or,
with no points, a panel standing in perspective that swings in from edge-on over half a beat.

| param | default | meaning |
|---|---|---|
| `quad` | `null` | four image-space corners `[[u, v], [u, v], [u, v], [u, v]]`: top-left, top-right, bottom-right, bottom-left (measure them on the plate, 0..1). Without them, a panel in a free slot. Anything else (a string, 3 points, `{x, y}` corners) is reported and draws the panel; when the frame (the 9:16 crop, the camera) cuts the quad it draws the panel too, said once on the page console |
| `content` | `sign` | `sign` (a dark sign face: `title` kicker, up to 4 big `lines`, one more each `step` beats, the newest with an accent bar) · `screen` (status bar with `title`/`status`, `rows` typed on the 16ths, a progress line) · `paper` (a printed page: `title`, `rows` of `[field, value]` one per eighth, the last value in the accent, a barcode). Any other value is reported and draws a `sign` |
| `title`, `lines`, `rows`, `status`, `text` | `""`, `[]`, `[]`, `""`, `""` | the face's words (lists may be written `"A \| B"`); an empty face uses the shot's sung line |
| `w`, `h` | 640, 360 | the face's own size (px) — its aspect; on a quad it is stretched onto the corners |
| `size`, `step`, `per16` | null, 1, 2 | sign line size (null: fit), beats between sign lines, screen characters per 16th |
| `tilt` | .45 | the panel's turn (0 flat … 1.2) |
| `print` | null | on a quad, print INTO the footage (the base) — default true; `false` draws it on the overlay |
| `op` | null | how it prints: `multiply` (default for `paper`: the plate's light and texture show through) or `source-over` |
| `behind` | false | the subject in front of the quad covers it (needs depth or a matte) |
| `strips` | 32 | homography strips (more for a steep quad) |

Keys: W B H F T. The face prints top → bottom over half a beat, its edge in the accent. Set `size` only when the sign is
the line (the plan compares it with the lyric's size). On a quad it is printed **into the footage** (the base), so a print
look's screen and grain run through it like the plate; the panel is a graphic on the overlay (crisp, like every device),
and the block placed for it is tall enough for its perspective (the near edge grows ≈ 8 % at the swing-in), so it never
crosses the margins.
```json
{"kind": "quad", "key": "W", "params": {"word": "exit", "content": "sign", "quad": [[0.63, 0.16], [0.88, 0.16], [0.88, 0.32], [0.63, 0.32]], "title": "EXIT 4 · 1/2 MILE", "lines": ["HARBOUR", "LAST FERRY 23:40"]}}
```
Precedent: EV printed a hall board, a calendar page and three roadside sign faces into its plates by homography; SP put
its posts and chats on the phone screens in the footage.

### `rope`
Aliases `rope.type`, `type.helix`, `helix`, `wrap.type`. **Role hero.** **Explains:** bound, tied, held — a line of
words wound round the subject as a helix, the far side behind the body (mirrored and dimmed, cut by the depth map or the
matte), the near side over it; the separator takes the accent; the wrap turns slowly and grows on over `beats`.

| param | default | meaning |
|---|---|---|
| `text`, `sep` | `""`, `" · "` | the words (default: the shot's sung line), the separator between repeats |
| `turns`, `pitch` | 1.35, 70 | helix turns, px it descends per turn |
| `height` | .55 | where on the subject box the wrap sits (0 top … 1 bottom; .55 ≈ the waist of a standing figure) |
| `r`, `ry` | null, .15 | radius (default: half the subject's width, 140–380 px), the ellipse's depth as a fraction of `r` |
| `size`, `speed`, `beats` | 40, 1.4, 1 | glyph size, turn speed (radians/s), beats to wind on |
| `behind` | true | cut the far side by the subject (depth or matte; without either it draws dimmed) |

Keys: W B H F T. Anchor: a box — `lead` (default: the subject box, §4) or a `uv` box. Inside the margins in both cuts.
```json
{"kind": "rope", "anchor": "lead", "key": "W", "params": {"word": "tied", "text": "STAY WHERE YOU ARE", "height": 0.5}}
```
Precedent: SP wound its chant round a bound figure as a rope of type, its back half behind the body.

### `streamlines`
Aliases `flow`, `field`, `attractors`, `flowfield`. **Role hero.** **Explains:** pull, influence, everyone drifting to one
place — a real flow field (one steady field: the lines never cross) from seed points to attractors that kindle on the
words; when the next attractor kindles the lines in its basin swing over to it; a particle rides each line; rings close
on the kick. No line ever crosses the lyric block.

| param | default | meaning |
|---|---|---|
| `attractors` | two | `[{"uv": [u, v], "k": pull, "label": …, "at": time spec}]` — objects, or rows `[u, v, k]` (up to 6; the first kindles at the start, each next one a beat later unless `at`). `{"x": .3, "y": .4}` is read as `uv` and reported; an entry with no point is dropped and reported; with none left the device draws nothing (and is reported — it then counts as no layer) |
| `seeds`, `from` | 18, [.36, .56, .28, .38] | how many lines and the image-space box `[u, v, w, h]` they start in |
| `points` | [] | the start points yourself instead: `[[u, v], …]` (up to 80; entries that are not pairs are dropped and reported) |
| `drift` | [0, -.35] | a steady current under the pull (`[0, 0]`: pure pull) |
| `step`, `beats` | 8, 2 | integration step (design px), beats for the lines to draw out |
| `lw`, `alpha`, `particles` | 1.3, .6, true | line width, line opacity, one particle per line |
| `behind` | false | the lines pass behind the subject (depth or matte) |

Keys: W B H F T. Pinned to the picture (image space through the camera): an attractor outside the frame shows no ring.
```json
{"kind": "streamlines", "key": "W", "params": {"word": "drawn", "attractors": [{"uv": [0.62, 0.37], "k": 1.6, "label": "THE CITY"}, {"uv": [0.55, 0.8], "k": 1.4, "label": "ONE STOPS", "at": {"word": "stops"}}], "seeds": 20, "from": [0.02, 0.55, 0.4, 0.4]}}
```
Precedent: SP drew every swimmer's line bending to the lit alcoves, the field changing when the second one kindled.

### `molecule`
Aliases `network` (preset `network`), `nodes` (preset `network`), `bonds`, `graph.draw`. **Role hero.** **Explains:** what
a thing is made of, who is connected to whom — a skeletal formula or a network drawn bond by bond on the sixteenths, the
fresh bonds in the accent, labels appearing as the bonds reach them.

| param | default | meaning |
|---|---|---|
| `preset` | `molecule` | `molecule` (built from `chain` backbone atoms, carbonyls, an N every third atom, `rings` aromatic rings on side chains) · `network` (`count` nodes around a hub, each tied to its nearest, the `hub` in the accent); anything else is reported and draws a molecule |
| `chain`, `rings` | 8, 2 | the molecule's backbone length and ring count |
| `count`, `hub`, `labels`, `seed` | 14, 0, [], 1 | the network's nodes, which one is the hub, node labels by index, the layout seed |
| `nodes`, `edges` | [], [] | your own graph instead — **both** are needed: nodes `[{"x": 0, "y": 0, "label": "A"}, …]` or `[x, y, label]` (any units) and edges `[[a, b, order?]]` (node indexes from 0, or labels; order 2 = a double bond). Nodes without edges (or edges without nodes) draw the stock preset and are reported; an edge naming a node that does not exist is dropped and reported |
| `per` | 3 | bonds drawn per 16th |
| `w`, `h`, `lw`, `size` | 560, 320, 3, 22 | the block, line width, label size |
| `label` | `""` | a micro caption under it (cite it: "ILLUSTRATIVE") |

Keys: W B H F T.
```json
{"kind": "network", "anchor": {"slot": "top-right"}, "key": "W", "params": {"word": "everyone", "count": 16, "labels": ["YOU", "", "", "THEM"], "label": "WHO KNOWS WHOM"}}
```
Precedent: SP drew a real molecule bond by bond on a line about a stranger with a chemical.

### `powers`
Aliases `powers.of.ten`, `zoom10`, `scale.zoom`, `map.zoom`, `zoom.out`. **Role hero.** **Explains:** scale and distance —
how small this is, how far it goes: the frame pulls out ×`factor` per level, each level landing on its beat; the footage
shrinks into a thumbnail at the zoom point while a plan of the world around it (streets that thin as they shrink,
blocks, an avenue) fills the frame; each level's frame is drawn and labelled; a scale readout names the level.

| param | default | meaning |
|---|---|---|
| `levels` | `["10 M", "100 M", "1 KM", "10 KM", "100 KM"]` | one label per level (the first is the footage's own frame); an empty list draws these defaults and is reported |
| `beats` | null | beats per level (null: the levels spread over the device's window, the last beat held) |
| `factor` | 10 | the zoom per level |
| `point` | null | the zoom point `[u, v]` in image space, or `"center"`, or `"lead"` (default: the subject's head, else the centre); anything else is reported and zooms from the lead |
| `ground`, `seed` | `night`, 3 | `night` or `paper` ground, the plan's layout seed |
| `label` | `""` | added to the readout ("THE SITE · ×100") |

Keys: W B H F T. The map **replaces the footage on the base** — like footage, so a print look's screen and grain run
through it, and the lyric's adaptive ink reads it. While it is up (from the first pull-out to `until`) the default
renderer holds the CV marks, micro devices and the treatment's marks on the footage (the `stills` strip, the `diagram`
grid); the level frames, labels, the point and the readout are drawn over it. It fades back to the footage after `until`.
Chapter code that draws it by hand (`DEV.draw`) draws its own marks after it, or skips them while `DEV.covers(inst, t)`.
```json
{"kind": "powers", "key": "W", "params": {"word": "small", "point": [0.48, 0.62], "levels": ["100 M", "1 KM", "10 KM", "100 KM"], "label": "THE SITE"}}
```
Precedent: SP rose from a rooftop to the whole city with the altitude as its readout; EV closed on a static city map.

---

## 9. The camera devices (role camera — they draw nothing)

Every camera device active at `t` is folded into one move; the footage is drawn through it (`CAM.through`: the zoom
always covers any shake, so no frame edge shows, and anchors stay pinned). With `window.HITS` the moves read the real
events; without it they fall back to the beat map. A shot with no camera device gets the source's gentle kick (the zoom
plus .018 × the bar's kick envelope, `KIN.kickBar`) unless its `camera` says `static`/`locked`. **A move answers a sound
you can hear**: no punches where the drums are out, no shake in UI shots; hold still where the song breathes.

### `cam.punch`
Alias `camera.punch`. A zoom kick on the kicks (gated by the drum envelope). Params: `amp` .02 (fraction of zoom; .01–.03),
`kind` `kick` (or `snare`, `vox` for vocal entries), `every` null (only every Nth beat's kick), `phase` 0, `tau` .13, `atk` .03,
`gate` true, `minS` 0. Keys: B H.
```json
{"kind": "cam.punch", "params": {"amp": 0.018, "every": 2}}
```
Precedent: SP punched every kick in the verses; EV's kick-bar zoom.

### `cam.shake`
Alias `camera.shake`. Handheld energy scaled by the drum envelope. Params: `amp` 6 (px), `rot` .002 (rad), `freq` 7 (Hz),
`gamma` 1.6, `stem` `drums`, `seed` 3. Keys: B H.
```json
{"kind": "cam.shake", "params": {"amp": 5}}
```
Precedent: SP's drum shake from the first drop.

### `cam.ride`
Alias `camera.ride`. A push that rides a riser into its hit and snaps back on it (or holds). Params: `amp` .06, `curve` 2.2,
`release` .09, `hold` false. Keys: H (risers in `window.HITS`).
```json
{"kind": "cam.ride", "params": {"amp": 0.07}}
```
Precedent: SP rides into the chorus hits (a riser landing on the drop).

### `cam.impact`
Alias `camera.impact`. The real hits (drops, section starts): a big zoom kick + a shake burst. Params: `amp` .06, `shake` 14
(px), `rot` .006, `burst` .22, `tau` .3, `atk` .035, `minS` .6 (impact strength floor). Keys: H.
```json
{"kind": "cam.impact", "params": {"amp": 0.07}}
```
Precedent: SP's first flash on the drop; impacts on the final chorus's hits.

### `cam.whip`
Alias `camera.whip`. A whip pan through a cut (`at`) or through a drum fill (`fill: true`). Params: `at` (time spec; default the
device's end), `dir` 0 (rad), `dist` 520, `blur` 180, `dur` .24, `fill` false. Keys: B H F.
```json
{"kind": "cam.whip", "params": {"at": "shot.t1", "dir": 3.1416}}
```
Precedent: SP's whips continuing a head turn; a ribbon whip in the second verse.

### `cam.snap`
Alias `camera.snap`. Snap zooms on the beat with a two-frame overshoot (`amp · e^(−age/tau)`) and a lateral jag that
alternates sides on every snap (`±jag · e^(−age/tau)` px). Params: `amp` .09, `every` 1 (beats), `kind` `beat` (or a hit
kind), `tau` .045, `jag` 18 (px). Keys: B H.
```json
{"kind": "cam.snap", "params": {"amp": 0.09}}
```
Precedent: SP's jagged snap zooms on the beats of a montage.

---

## 10. A worked shot

A generic line, *"Every lamp on the street went out"* (line 18), on a plate whose depth map finds the subject (no
`subject_uv` needed):

```json
{"id": "s031", "t0": 63.40, "t1": 65.38, "section": "chorus 2", "lines": [18], "lead_on_screen": true, "framing": "MS",
 "camera": "slow pull out", "treatment": "relight", "transition_in": "through",
 "type": [{"line": 18, "mode": "coverline", "placement": "right", "micro": ["SRC · CITY GRID LOG", "21:04"]}],
 "devices": [
   {"kind": "flap", "anchor": {"slot": "top-left"}, "key": "W", "params": {"word": "out", "label": "BLOCK 7", "rows": [{"text": "DARK", "prev": "LIT", "accent": true}], "ch": 48}},
   {"kind": "cv.tag", "anchor": {"uv": [0.70, 0.32]}, "key": "H", "params": {"hit": "snare", "rows": ["LAMP 14 · OFF", "0 LUX"]}},
   {"kind": "flash", "key": "W", "params": {"word": "out", "kind": "black", "frames": 1}},
   {"kind": "cam.ride", "params": {"amp": 0.05}}]}
```
At any frame this draws: the plate relit band by band through its depth on the pull-out, riding the riser into the hit;
the black frame on "out" (one flash, planned around the `through` transition); the split-flap status flipping LIT → DARK
on the same word (the hero, its 37 px cells under the 84 px coverline); the CV tag finishing within the snare's beat and
the lead mark (2 CV marks); the coverline hung right of the subject with its two source rows typed under it (2 of the 3
micro rows); the chrome. The shot enters through the previous shot's subject. `slop --json render info` must list no
warning for it.

---

## 11. Writing a bespoke device or chapter

Chapter code (Director tier) may call the library directly and register new devices:

```js
DEV.register('my.device', {
  role: 'hero', defaults: {rows: []}, doc: 'what it explains',
  typeSize: p => 40,                  // the biggest type it sets (the plan's "lyric is the biggest type" check); optional
  capType(p, k) { p.size *= k; },     // optional: scale its type params by k (< 1) when the plan caps it at the lyric's
                                      // size (default: params.size *= k when params.size is a number)
  check(p, warn) {                    // optional: repair a malformed param in place, one warning per repair (in deviceWarnings)
    if (!Array.isArray(p.rows)) { warn(`my.device.params.rows should be a list like ["A", "B"] — got ${DEV.short(p.rows)}; drew none`); p.rows = []; }
  },
  draw(o, b, t, p, x) {               // o overlay, b base (2D contexts); p = params; x = this instance's context
    if (t < x.t0 || !p.rows.length) return false;   // false: drew nothing on this frame (it is not counted as a layer)
                                      // x.t0 / x.t1: its window; x.bs(t): beats since start; x.bl(t): beat length
    const [px, py] = x.place(400, 200);           // a free slot / anchor-relative placement, inside the margins (scaled to fit)
    const box = x.box(), ink = x.ink([px, py, 400, 200]), acc = x.acc();   // anchor box, adaptive ink, the accent (budgeted)
    DEV.typed(o, p.rows, px, py, t, x.t0, {color: ink});                    // rows typed on 16ths
  },
  example: {kind: 'my.device', key: 'B', params: {rows: ['HELLO']}},
});
// draw any device by hand inside a chapter scene:
const inst = DEV.instance({kind: 'cv.tag', anchor: {uv: [0.6, 0.4]}, key: 'W', params: {word: 'lamp', rows: ['LAMP']}}, {id: 's012', t0, t1});
await DEV.draw(o, b, inst, t, DEV.frame({t, m, b, o, accent: '#D97757'}));
```
Rules: a pure function of `t` (no `Math.random`, no `Date`, nothing carried between frames — use `hash(i)`); memos only
for data derived from static media, keyed by name (`DEV.memo(key, fn, plateName)`: per-plate memos are kept for the last 3
plates only); every canvas you create through `DEV.mk(w, h)` (software-backed: a GPU-backed canvas drawn into the frame
makes later frames render differently); every lyric token you draw calls `KIN.mark(tk)`. Every registered device is also
available through `ENGINE.drawDevice(spec, env)`. `inst.warn` lists what was wrong with the entry. A device that paints
over the whole footage on the base declares `covers(inst, t)` (true while it does): the default renderer then holds the
marks drawn on the footage (`DEV.covers(inst, t)` asks it).

Useful helpers: `DEV.time(spec, shot)`, `DEV.keyed(t, keys)`, `DEV.tAtBeat(bp)`, `DEV.beatAfter(t, k)`, `DEV.bs(t, t0)`,
`DEV.bl(t)`, `DEV.kick(t)`, `DEV.pulse(t, kind)`, `DEV.anchor(spec, x)`, `DEV.subjectOf(shot, m)`, `DEV.inkFor(b, box)`,
`DEV.typed`/`typedFast`, `DEV.fmt(v, format)`, `DEV.homog(src4, dst4)` / `DEV.drawQuad(g, canvas, quad, {strips, op, alpha})` (a flat canvas onto any screen quad), `DEV.treat.planes(plate)` (the multiplane split), `DEV.flapBoard`, `DEV.barcode`, `DEV.spark`, `DEV.mono`, `DEV.sign`,
`DEV.type.{sub,cover,mast,stack,mass}`, `DEV.treat.draw`, `DEV.trans.make`, `DEV.flashPlan`/`flashOk`, `DEV.report(msg)`
(a warning on the page console and in `render info`), `DEV.adhoc(kind, params, t0, t1, anchor)` + `DEV.drawSync(o, b,
inst, t, X)` (a device outside a shot, drawn synchronously).

The second video's kit names are aliased when nothing else defines them — **exactly these** (same signatures as its
chapter code, drawn synchronously by the devices above): `LY.sub/cover/mast/stack/auto/rowsOf`;
`CV.bracket(o, box, t, opts)`, `CV.lock(o, box, t, t0, tLock, opts)`, `CV.tag(o, ax, ay, rows, t, t0, opts)`;
`UI.rr`, `UI.chip(o, x, y, text, t, t0, opts)`, `UI.chatbar(o, x, y, w, text, t, tType, tSend, opts)`;
`FLASH.mono/at/ok`; `TR.whip/through/flashCut`. Its story-specific kits (the instruction cards, the load tag, the copy
counter and plot, the title lockup, the spectrum helpers) are not aliased: use the `flash` card, `gauge`, `counter`,
`plot`, `title.*` and `voice` devices.

---

## 12. QA hooks

| hook | what it holds |
|---|---|
| `slop --json render info` → `info.deviceWarnings` | every repair the plan made and every device / type entry that threw in the boot dry run (the list to empty) |
| `info.deviceErrors` · `window.DEV_ERRORS` | any device/treatment/type error caught at render time (the frame still renders; also reported on the console) — should be empty |
| page console `[devices] …` | the same warnings, once each (`slop render info` returns the console as `info.console`) |
| `window.DEV_FRAME` | the last frame: shot, treatment (+ `treatmentKind`, the guide `code`, `drawnAs` when a multiplane fell back to layers, `strip` when the stills contact strip drew), lyric block (+ its `box`), the flash / hero / cv / micro devices **that drew something** on this frame, `covered` (the hero replacing the footage, e.g. `powers`), `microRows`, accents used, devices suppressed by the budget, the placed device `boxes` (and their fit `scale`; a perspective panel also records the box it actually covers as `quad.panel`), the `lead` box; the collision rule's record: `lyricRect` (the measured, padded block drawn now), `lyricBlocks` (every block of the shot: `{line, auto, a, z, rect}`), `labels` (every label a device placed: `{kind, spot, box, rects}` — `spot` 0 is the default corner, > 0 a flip, −1 left off), `chrome` (`{cut: items taken out, ink: chrome pixels left on the block — always 0}`); `face` (the face box the 2.5D camera kept in frame, screen px), `faceHeld` and `faceCalm`; `occ` (the tuck rule's record when type was drawn behind the subject: `{glyphs, kept, eased, tucked, cover}`, from `OCC.guarded()`) |
| `ENGINE.frameLayers()` | **the one layer counter** (engine core; `slop render check --layers` samples it at every shot's mid-point): after a frame, `{count, layers, rule: 3, ok, shot, treatment, missingMedia}` — `layers` in drawing order out of `media` (a plate or clip drew) · `graphic` (a hero or a firing flash that drew, or the `contours` / `scan` / `diagram` treatments; the `stills` contact strip is not counted as one today) · `annotation` (CV marks) · `micro` · `lyric` · `chrome`. It reads `DEV_FRAME`, so a device that drew nothing is not a layer. Chapter frames: their `ENGINE.drawDevice` calls count as graphic |
| `ENGINE.info().chapterScenes` · `chapterShots` | the scenes bespoke chapter code registered (`[{name, t0, t1}]`; the default renderer leaves their time alone) and the storyboard shots they cover — the runtime proof that a delegated chapter is wired in |
| `ENGINE.info().treatments` | per storyboard shot: `{id, family, kind, code, base, auto, clean, drawn}` — the 2.5D treatment it got, whether it was picked for it (§6), whether its look is clean, and the family that actually draws |
| `window.SHOT_WARNINGS` | the plan's warnings (as `deviceWarnings`) |
| `window.SHOTS_PLAN()` | the resolved plan: per shot its treatment, device windows, transition; the accepted/rejected flash list (fixed events marked) |

Reading the layer count for a frame (what `slop render check --layers` does at each shot's mid-point):
```js
await window.renderAt(t); const L = ENGINE.frameLayers();   // L.count >= 3, else a clean hero moment (≤ 2 bars) or a missing graphic
```
With `chrome: "off"` a shot needs a device (or a `contours` / `scan` / `diagram` treatment) to reach 3: media + lyric
alone is 2.

The boot dry run draws every device and type entry once (a few ms each) before the page reports ready; a project that
needs the fastest boot can switch it off with `window.PROJECT.lint = false` (then a throwing device shows up only in
`DEV_ERRORS` while frames render).

`tests/test_engine_devices.py` renders every device over a range of `t` on the real engine page, checks same `t` → same
pixels (also against a fresh page), the timing grammar on an accelerating beat map (and string numbers, unsung words),
the budget, the flash rule, the treatment/transition rotation, the lyric gate, portrait frames inside the margins, a
project without detection boxes, bounded plate memos, and that `slop render info --json` reports every repair.
`tests/test_devices_explain.py` does the same for every variant of the five explaining devices (and checks the homography,
streamlines staying off the lyric, the powers map on the base, the 9:16 margins); `tests/test_devices_treatments.py`
checks the five-family pick (native, print, no depth, asked treatments, pinned heroes, per-shot looks), multiplane (and
its fallback) and tiles, that `DEV_FRAME` and `ENGINE.frameLayers()` agree (a device that drew nothing is no layer), and
the chapter scenes; `tests/test_polish_engine.py` checks the collision rule in 16:9 and 9:16 (the lead label flips off a subtitle, tag and
callout rows flip, panels asked onto the lyric move and are reported, chrome on the lyric is taken out; the measure holds
every mode's ink) and the face-safe camera (a push with punch and snap keeps the face box in frame at every frame — the
engine's mapper and the face's own pixels — and crops it with `face_safe: false`; layers, relight, stills, multiplane;
`PLATE3D.safeCam` alone); `tests/test_polish_engine_review.py` pins what exercising them found (the stills strip gives way to a device on its spot, no chrome ink on the lyric at any frame and a chrome item of any height taken out whole, the face kept in frame under `cam.impact` + `cam.shake` by calming them, `safeCam`'s `fits`, a panel with no room reported, bare leaders taking a clear way, a shrunk gauge tag's anchor ring on its anchor). `tests/test_devices_params.py` checks that every malformed param of the explaining devices is
reported with the shape to write, and powers / quad in a print look.
