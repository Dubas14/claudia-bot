# 40 · Storyboard: shot grammar, the explaining graphic, the hook, cut rhythm, motion budget, audits, board review

Read this before you write the first shot, and again before you send the board to the owner. The storyboard
(`board/shots.json`) is the source of truth for everything after it: which plates get made, which clips get prompted,
where every cut lands, which graphic explains which line. A weak board cannot be rescued by good footage.

**Inputs (all must exist):** `analysis/beats.json`, `words.json`, `hits.json` and `report.md` with the ear-check done
(20-analysis); `lyrics/display.txt`; the concept and the owner's decisions (`DECISIONS.md`); the lead's canon
(`project.json lead`); the look and taste tokens (30-taste); the tier's motion budget (§8).
**Outputs:** `board/shots.json`, the board sheet (`board/board.pdf` or `.jpg`), `board/audit.json`, the owner's notes in
`DECISIONS.md`, `project.json gates.board_approved`.

---

## 0. The stage at a glance

1. Write the board-level design first (§2): treatment, through-line device, chapter map, the explaining devices,
   plants and payoffs, the hook. Put it at the top of `DECISIONS.md` (or a `board/TREATMENT.md`).
2. **Set the tier's pace first** (§6.1): the draft cuts at the project tier's pace (Quick ≈ 4–7 s a shot, Studio
   ≈ 2.5–5 s, Director = EV's ≈ 27 shots a minute). Check the tier in `project.json`; to draft at another pace put
   `"board": {"pace": "studio"}` (or a block of seconds per section) into `project.json`, or pass
   `slop -p <name> board draft --pace studio`, before anyone writes into the board.
3. `slop -p <name> board draft` writes a **draft** `board/shots.json` from the analysis: cuts on beats with a pace per
   section, every lyric line typed on its words, sung and motion clip windows inside the tier's budget, the lead share
   kept near 78 %, 2.5D treatments rotated. Everything creative is left as a `TODO` marker: set, framing, action, plate
   prompts, clip prompts, and one explaining graphic per lyric line.
4. Write every `TODO`, section by section (§3–§8), **with commands, not by editing JSON** (§9.1):
   `slop -p <name> board set s004 --set "a night market under sodium lamps" --framing MS --action "she counts coins into a paper cup, then looks up"`,
   many shots at once with `slop -p <name> board fill shots.tsv`, and for every lyric line the explaining graphic (§4)
   with `slop -p <name> board device add s004 --kind callout --line 3 --anchor uv:0.62,0.4 --param word=walk`. Every
   value is checked against the engine; a bad value changes nothing. Change the draft's cuts, tiers and clips wherever
   the story needs it.
5. `slop -p <name> board audit` (§10); fix until every gate passes.
6. `slop -p <name> board sheet` builds the review sheet; send it to the owner with a stated review window (§11).
   **Gate G4.**
7. Log the owner's notes verbatim, apply every one, re-audit, then `slop -p <name> board approve` (it sets
   `gates.board_approved` only when every gate passes).

---

## 1. What a good board does (the bar)

- **The first second is a hook**, readable on a muted phone (§5).
- **Every sung word is on screen at its time**, in one type mode and one position per line.
- **Every lyric line has an explaining graphic** that shows what it means (§4).
- **A through-line device** escalates across the whole song.
- **Every cut lands on a beat**, faster where the music is busy, held where the song breathes (§6).
- **The lead is on screen most of the time**, honestly counted (§7).
- **Motion is spent where it sells**: real turns, falls, fabric and sung mouths; stills and 2.5D where stillness is the
  design (§8).
- **One image per shot.** Two clips never start from the same frame.
- **Every change of place has a cause in the story** (EV: "car door → catwalk, billboard → board, falling flaps →
  backstage, gold light → board light, loading door → freeway, gantries → ramp, tag → care label").
- **"Not a drag at any point"**, and dense but intentional (SP's brief: "fairly dense, but it also needs to be
  intentional").

---

## 2. Board-level design (write this before any shot)

### 2.1 The treatment (one paragraph)

Who, where, what happens, how it ends, and the one image that makes the concept. EV's (abridged):

> ESCAPE VELOCITY is one night, one woman and one route, staged as a techwear fashion show in eleven looks. She wakes in
> the back of a driverless Waymo on the fogged 101 while a full-width split-flap row clatters onto 18 MONTHS TO ESCAPE
> THE PERMANENT UNDERCLASS. The car turns into a datacenter and its open door gives straight onto the catwalk … At dawn a
> loading door opens onto an elevated freeway above the fog for chorus 2. The freeway's gantry signs are the bridge's
> three boards: they count 3·2·1·0 … The road ends in a ramp; the drop is her takeoff into white … the outro turns her
> garment tag into the care label … before she walks off the paper until she is one clay dot.

SP's opened with the reason the concept works: "The song is a siren song, so the video is one."

### 2.2 The through-line device

A piece of chrome that is always on and **changes with the story**, so the viewer can feel progress without a word of
explanation. Write its schedule against word times.

- EV: the split-flap board read 18 until verse 2, then stepped down one number per "Look N" (16 · 14 · 12 · 10 · 8 · 7),
  flipped to 06 exactly on the word "six", counted 03 · 02 · 01 · 00 on the bridge words, then read THERE IS NO
  UNDERCLASS and finally END OF SHOW. A LOOK counter only ever climbed (00 → 06 → 11 → ALL).
- SP: a rope load readout climbing 2.1 kN → 3.8 → 5.2 → 9.8 ⚠ → TIGHTER ("persuasion measured as a physical force"); a
  four-pictogram safety card (① tie him to the mast ② plug your ears ③ do not untie him ④ do not jump) flashing on every
  shout and paying off as DO NOT UNTIE HER; an instance counter ×1 → ×1,024 → ×8,192.
- Payoffs land **on their words** (EV: 18 locks on "eighteen", 06 flips on "six", 11.2 KM/S lands on "eleven").

### 2.3 The chapter map

One row per chapter (chapters follow the song's sections): time range, place, light, accent, what changes. EV:

| Chapter | Time (s) | Sections | Light | Accent |
|---|---|---|---|---|
| C0 ARRIVAL | 0.00–18.96 | intro | night, blue-black, one warm lamp | clay |
| C1 THE SHOW | 18.96–74.12 | first walk, verse 1 | night | clay |
| C2 THE BOARD | 74.12–110.42 | pre-chorus 1, chorus 1 | night → first light | clay |
| C3 BACKSTAGE AT DAWN | 110.42–153.80 | verse 2 | pre-dawn slate grey, one ember lamp | ember |
| C4 THE OVERPASS | 153.80–184.82 | pre-chorus 2, chorus 2 | dawn grey-white, fog below | clay |
| C5 THREE BOARDS | 184.82–222.99 | bridge | near-white fog | none (mono ink) |
| C6 TAKEOFF | 222.99–252.59 | drop | high-key white | 1-bit ink |
| C7 WHITE-PILLED | 252.59–271.41 | final chorus | white paper | clay |
| C8 CARE LABEL | 271.41–306.40 | outro | paper | clay |

The light carries the arc ("the arc of the song is the arc of the exposure"). SP did the same with sea light: night,
the phone's blue, dusk, twilight, night lit by cliffs, strobe and chrome, grey first light, sunrise, morning, then
3 a.m.

### 2.4 The devices that explain it

List the recurring explanatory devices before the shots (SP's list: three visual languages cut against each other;
the safety card; the load readout; who is tied; her voice drawn as a spectrum; the instance counter; the myth's
original text as micro-type with translations; the contagion network; screens inside screens; real numbers with
sources; the loop). Each later shot reuses them, so the viewer learns the system once.

**Three visual languages** (optional, powerful): SP cut between *Siren* (graded plates, slow, liquid, long lenses),
*Mast* (black and white, hard, flashing on the beat, crisp vector graphics) and *Timeline* (clean phone UI, editorial
portraits, counters). "That switching is the density, rather than more elements."

### 2.5 Plants and payoffs

Everything that pays off later is planted early, so the payoff lands in one glance:

- EV: the buckle clicks shut at 8.04 s — "lock in" as a gesture, 71 s before it is sung — and recurs on every "Lock in",
  harder each time.
- SP: for six frames at 3 s, something pale and enormous under the water: the face of the creature that breaches in the
  Break at 2:23. All four safety rules are on screen at 15 s, before the first chorus at 40 s: "Every rule is on screen
  before the first chorus, so the payoffs land."
- SP's loop: the last frame (her eye, on his phone) is the first frame (her eye, on the rock): autoplay becomes the
  encore.

### 2.6 Open questions for the owner

End the board with a short list: likeness questions, anything risky, and **"my additions in this draft"** (ideas you
added beyond the owner's brief). The owner's creative-freedom clause on SP: "You should be able to override the things
that I'm saying that don't make sense … I want it to be like not a drag at any point." Use it, and say where you did.

---

## 3. Shot grammar

### 3.1 A shot

A shot is a span `[t0, t1]` between two beats of the beat map. Write each shot in this order (readable form; the JSON
form is §9):

```
sNNN · t0–t1 (length) · section · lines · set · lead ✓/— · FRAMING · motion tier · plate
- action: what happens, concretely, with an end state
- camera: one move, tied to a sound
- type: line, mode, text, placement
- graphic: the explaining device for the line, and the word it enters on
- chrome: what the through-line devices show
- treatment / transition_in / notes
```

### 3.2 Framing

| Code | Name | Use for |
|---|---|---|
| ECU | extreme close-up | an eye, a mouth, a mark (the streak, the clip): hooks and payoffs |
| CU | close-up | singing, the stare into the lens |
| MCU | medium close-up | talking to the lens, an action with the hands |
| MS | medium shot | two people, action and reaction |
| MWS | medium wide | a figure in its place (SP: the man at the mast with the ghost arriving) |
| FS | full shot | walks, turns, fabric |
| WS | wide | the set |
| EWS | extreme wide | scale (a fogged freeway, a datacenter on a plain, a ship on the horizon) |
| OTS | over the shoulder | a two-person moment; the lead's canon must still be in the prompt (a bare shoulder put a stranger in SP's shot) |

EV's mix: CU 30, WS 27, MS 21, FS 17, EWS 16, MCU 15, ECU 15 of 141. Alternate framings inside a sung passage (CU → MCU
→ profile → CU) so a cut to cover a lip-sync divergence looks designed.

### 3.3 Action

1. **Concrete and physical**, with an end state: "She walks toward the camera down the wet catwalk; the red lamp shivers
   in the puddles." Never a mood ("she exudes confidence").
2. **Action and reaction** whenever two people share a shot. SP's owner on the first round of prompts: "the guy tied to
   the mast should be thrashing about if in the sirens influence, hes just sitting there peacefully". A pose is not a
   beat.
3. **Upright, editorial poses** for the lead (seated or reclining frontal poses get refused downstream; EV: "the golden
   pool is a step down and a kneel (upright, not lying back)").
4. **Risky moves have simple versions**: the car door is already open in the plate; a swarm of her is built in code from
   one figure; a takeoff is an edge walk + a run + a 2.5D rise, not a generated jump.

### 3.4 Camera

- **One move per shot**, named plainly: locked, slow push in, pull back, tracking back at her walking speed, slow pan,
  crane up, handheld, snap zooms on the beat.
- **Every move answers a sound you can hear** (`hits.json`): a push rides a riser into the hit it lands on; punches on
  kicks only where the drums play; an impact gets a bigger hit; **stillness where the song breathes**. "Hold the camera
  still where the song breathes — stillness is part of the sync."
- Lip-sync shots: locked or a very slow push; no head turns.

### 3.5 Images

1. **One image per shot.** Never the same plate on two shots unless they are one continuous moment. (EV's owner on the
   board: "should have the same image for like 6 diff storyboard shots" — as a complaint.)
2. **Two clips never start from the same frame.** The k-th clip on a plate uses the plate's k-th other Midjourney
   candidate (a job gives four images: the three not picked are a free variety pool), or continues from the previous
   clip's last frame.
3. Where a plate would repeat its neighbours, make the shot **pure motion design** instead (a diagram, a UI, a
   typographic poster, a data-vis, a split-flap wall). EV's owner: "for some repeitive 2.5D panels we could replace it
   with pure motion design."
4. No stock-photo subjects (crowds, elderly or patient portraits, hands with props): change the idea, don't re-roll.

### 3.6 Type on screen (the lyric)

| Mode | What | Size | Use for |
|---|---|---|---|
| subtitle | a caption on a baseline, word-by-word wipe, the current word in the accent (karaoke) | ≥ 46 px at 1080p | sung lines, calls, board lines |
| coverline | an editorial lockup in the plate's declared empty field, display face + mono micro rows, hung from something visible | cap height 1.5–3.5 % of frame height | spoken verses |
| masthead | one giant token per beat, hard cut, only over a quiet patch | 7–19 % of frame height | payoff words, chorus answers, countdown numerals |
| stack | a justified column, each word on its time | — | chants (IT / WAS / THAT / GOOD!) |
| mass | a declared wall of micro text with one big word at a time | — | a drop; illegible on purpose |

Rules:

1. **Every token appears at its aligned `t0`, never snapped to a beat.** "The motion syncs to the beat, the word to the
   voice."
2. **A line is one mode and one position, held across cuts**; it exits on the next downbeat after its last word.
3. **One lyric block per frame.** The biggest type in the frame is the lyric, unless a device *is* the line (the safety
   card on a shout, the title on the title word).
4. **The lyric is never smaller than 40 px** at 1080p (46 for subtitles); it must read on a phone.
5. **Never over the lead's face.** Where type crosses her, it tucks behind (a matte) or is drawn as a difference of the
   ground. "Tuck an edge and never lose a glyph."
6. **Declare the empty field in the plate prompt** ("the upper third empty fog", "the left third empty dark") so the
   type has a place to live.
7. Call-and-response: the call small (a grey subtitle), the answer as the masthead (EV: "(It's so over?)" small, WE'RE
   SO BACK big).

### 3.7 Devices (the explaining graphics and the chrome) as data

Each device has a `kind`, an `anchor` (where it sits), `params` (its content) and a timing `key`:

| Key | Timed by | Example |
|---|---|---|
| **W** | a word's `t0`/`t1` | the graphic enters on the word that names it |
| **B** | the beat grid (beats, eighths, sixteenths) | counters tick on sixteenths, rows type on eighths |
| **H** | a sound event from `hits.json` (kick, snare, impact, riser) | a flash on the impact; a punch on the kick |
| **F** | a fixed song time in seconds | a hand-measured hit pasted as a number (use sparingly) |
| **T** | the footage itself (a tracked box or keyframes on the clip's own time) | a CV bracket that follows her; a meter read off her bow |

Anchors: a detection box (`{"box": "a face"}`, or `"lead"`), a tracked label (`{"track": "a woman"}`), an image point
(`{"uv": [0.62, 0.60]}`), a screen rectangle (`{"rect": [x, y, w, h]}`) or a free screen region (`{"slot": "top-left"}`;
also `top-right`, `bottom-left`, `bottom-right`, `left`, `right`, `top`, `bottom`, `center`, `auto`; `centre` is
rewritten to `center`). On the command line: `--anchor lead`, `--anchor top-left`, `--anchor uv:0.62,0.4`,
`--anchor rect:120,80,600,300` or `--anchor "box:a face"`. The toolkit detects no boxes by itself: name one on a
plate's picked image with `slop -p <name> plates box p004 --label "a face" --uv 0.41,0.18,0.16,0.30` (u, v = the
top-left corner, 0..1 of the image; `--label subject` is the lead box), then `slop edit export` passes it to the engine. A CV mark
(bracket, outline) is drawn **on** its anchor's box; a block device (a board, a sheet, a card, a tag's rows) is drawn
**beside** it, so it never covers the thing it names. To pin a block to an exact screen position, give `params.x` and
`params.y` (px) or use a `slot`.

Kinds: use the ones the engine's device library lists (70-motion-design): CV brackets and tags, counters, charts,
labels and garment tags, split-flap boards, readouts and gauges, terminals, UI chips, pictogram flashes, spectrum
lines, strike-throughs, title knockouts. A kind the library doesn't have is drawn by chapter code (Director tier) —
say so in `notes`.

**`params` must use that device's own keys.** Each device is registered in `engine/src/devices/*.js` with its
`defaults` and an `example`: `slop -p <name> board device kinds` lists the library, `--kind flap` prints one device's
params, defaults and example, and `board device add … --example` starts from the example (replace its on-screen text in
the same command: the catalogue's own words are refused). `slop board device add` checks the kind, every param key,
the anchor, the timing key and the time specs, and the audit's devices gate checks devices written any other way,
because a wrong key fails silently on the frame: a split-flap row written `{"txt": …}` instead of
`{"text": …}` flips to the word UNDEFINED, and a `readout` (an alias of `gauge`, which takes `value`/`unit`/`max`/
`label`, not text rows) given `rows` ignores them and shows a value of 0. For text rows next to a thing use `cv.tag`
(`rows: ["…"]`) or `sheet` (`title`, `rows: [["FIELD", "VALUE"]]`). `--param` values are JSON when they parse
(numbers, `[…]`, `{…}`), except `word`, `word_end`, `at` and `until`, which stay text: `--param word=13` is the sung
word "13", never lyric line 13. Render one frame of the shot (`slop render stills --times <s>`, after
`slop edit export --no-frames`) to check a device you haven't used before.

**Time specs** (wherever a device takes a time: a row's `at`, a key's time, a device's own `at`/`until`):

| Spec | Means | Key |
|---|---|---|
| `12.48` (a number) | that song second (on a device with key `T`: seconds into the clip's take) | F |
| `"shot.t0"`, `"shot.mid"`, `"shot.t1"` | the shot's start, middle, end | F |
| `{"word": [line, i]}` or `"<text>"` | the start of display token `i` of lyric line `line` (both 0-based), or of the first display token with that text in the shot | W |
| `{"word_end": [line, i]}`, `{"line": n}`, `{"line_end": n}` | a token's end; a line's start or end | W |
| `{"beats": k}`, `{"eighths": k}`, `{"sixteenths": k}` | k beats / eighths / sixteenths after the shot start (add `"from": <spec>` to count from elsewhere) | B |
| `{"beat": n}`, `{"bar": n}` | beat n / bar n of the song's beat map | B |
| `{"hit": "kick"}` (`snare`, `hat`, `impact`, `vox`, `drum`, `any`; `"n": k` for the k-th in the shot, `"near": <spec>` to snap) | a sound event from `hits.json` | H |
| `{"take": s}` | s seconds into the shot's clip take | T |
| `{"offset": s, "from": <spec>}` | s seconds after another spec | any |

**Density budget per frame** (pick one per song, record it in `DECISIONS.md`):

- EV (dense): at least 3 ordered information layers in every frame (footage + lyric + chrome + annotation or graphic).
- SP (dense but intentional): footage + one lyric block + one hero device + at most 2 CV marks + the chrome; micro-type
  at most 3 rows; the accent on at most 2 elements. A clean hero moment (footage + lyric only) is allowed for at most
  2 bars and "must be earned".
- A calm song (an earlier project): "at most 1 element on screen; nothing locked to the beat; straight cuts only".

### 3.8 2.5D treatments (for `motion_tier: "plate3d"`)

Never a still with a slow zoom. Pick a family per shot, **never the same family on two consecutive 2.5D shots**, and
use at least 5 families per chapter. `"treatment": "auto"` (`board set s004 --treatment auto`) lets the engine pick
from its five-family rotation, never the family of the shot before; an empty treatment is a TODO and fails the audit:

| `treatment` | What it does |
|---|---|
| `layer-separation` | depth parallax; type *between* depth layers; rack focus |
| `depth-as-image` | contour lines, a thermal ramp, a point cloud, a depth-scan sweep on the beat, a relight bar |
| `reproduction` | scan reveal band by band, dots growing with the kick, 1-bit flicker, misregistration (print looks only; not on a clean project) |
| `stills-in-rhythm` | stutter, freeze and slide, crops cut on eighths, a contact-sheet grid selecting on the downbeat |
| `diagram-over-image` | leader-line callouts, measured dimensions, a CV mesh, a plan view morphing into the plate |
| `occlusion` | type and graphics tucked behind the subject through a matte or a depth key (your own family name; the audit accepts any name) |
| `pure-motion` | no footage: a code-drawn frame (use with `motion_tier: "still"` and `plate: null`; the audit treats it as a code shot that needs no plate or framing) |

### 3.9 Transitions

1. **Mostly hard cuts on the beat.** EV: 130 of 141 shots entered on a cut.
2. **A motivated device every few shots**, landing on a beat, **never the same device twice in a row**. The owner's bar:
   "interesting and intelligent transitions, like edgar wright level haha. not solely cuts but things that work with the
   motion design or graphics - but also not overdone and amateurish."
3. Good devices are ideas: **the graphic that explains one line becomes the frame of the next shot**; a match cut on
   shape or position (SP: "her pupil = the gap in the clouds"); a push through an object (an eye, an ear, a phone screen);
   a whip that continues a head turn; split-flap tiles wiping into the next set; a paper flash as a door floods the room.
4. Full-frame flashes: **at most 3 in any second**, and only where they belong to the design language (SP: only in the
   black-and-white "Mast" language, "dont need to force flashing").

---

## 4. The explaining-graphic rule

**One explaining graphic per lyric line.** The owner's words: "motion graphics and motion design, not just animated
lyrics but things that fit the words being said … almost explaining the words with visuals." For anyone who doesn't
know the meme or the myth, the graphic is how the line lands.

1. **It shows what the line means**: the chart the number implies, the UI the joke is about, the diagram of the
   mechanism, the label that classifies the subject, the counter that ticks the stakes.
2. **It is drawn from the thing in frame** where possible: the tally marks are scratched into the mast itself; the
   clock's own LED segments re-light as the P(doom) number; the meter is read off her actual bow. Graphics that sit on
   top of a picture they don't belong to read as fake ("as if when you were taking the picture, you lined it up
   perfectly to have the graphics fit").
3. **It enters on the word that names it** (key W): on "billboard", the classifier tag flips to AI BILLBOARD; on "hoax",
   one inversion.
4. **It animates in beats** (key B): counters roll on sixteenths, rows type per sixteenth, detections land on
   thirty-seconds, crops cut on eighths.
5. **It escalates across the film** (the through-line), and **its sources are on screen** in micro-type (dates, "HIS
   WORDS", "(PARAPHRASE)", "ILLUSTRATIVE CURVE").
6. **Real, not decorative**: numbers, diagrams, labels and UIs that could exist; computed curves; no clip-art. Real
   people only inside a frame labelled AI IMAGE, with their own words.
7. **Readable in one glance on a phone.** If it needs a pause to read, it is a second read (pause bait), not the first.

**Examples (line → the graphic)**

| Line (as read) | Explaining graphic |
|---|---|
| Ladies. Gentlemen. Agents. | a guest list: share of seats LADIES 0 % · GENTLEMEN 0 % · AGENTS 100 %, then a front row of open laptops with no people, each detected as AGENT |
| This is not an AI billboard. | a classifier tag on the billboard flips BILLBOARD · 0.99 → AI BILLBOARD · 0.97 on "billboard." |
| +25% = −17% | bar chart drawn on the beat: the weekly limit falls 150 → 125, "+25%" struck through, "= −17%" lands in the accent |
| Sorry. Encore. | an APOLOGY METER · VIA BOW gauge read off her actual bow (0° upright / 30° sorry / 60° deep) |
| No grades, no tests. | a transcript as a garment tag: GRADES — / TESTS — / DEGREE —, while she tears the answer sheet |
| Feel the AGI | a seismograph: M 9.0 · "FEEL THE AGI" · OFF SCALE |
| Escape velocity: 11.2 KM/S | Newton's cannonball diagram: falls 7.0, orbits 7.9, escapes 11.2 km/s |
| gambling with our lives | a three-reel slot machine of crops: EYES · BADGE · SEAT EMPTY |
| (It's so over?) WE'RE SO BACK! | a VIBE METER slider SO OVER ↔ SO BACK; a poll card filling the sky |
| Dario said to slow it down. | a post with an editorial portrait labelled AI IMAGE; on "slow it down" the portrait runs at an eighth of real speed and a tempo dial eases down |
| You don't sleep. Three a.m., P doom's at ten | the bedside clock's own digits re-form from 3:00 into 10 % |
| Forty plays. | forty tally marks scratched into the mast |
| TIE ME TO THE MAST! | pictogram ① flashes full-frame; the lyric wraps round the mast as a rope of type, behind the mast on the far side |
| You don't have to die. | a hairline of her voice's spectrum flowing into his ear, tagged SOURCE: SIREN ROCK, 2.4 NMI · ALSO: INSIDE HIS HEAD |

Write the graphic for **every** line in the board before any shot is final. If a line has no graphic, the board is
not done.

---

## 5. Hook design (the first seconds)

Viewers on X see the video **muted**, in a feed, and decide in about a second. Design for that.

1. **The one-second test:** the frame at 1.0 s shows the lead's face (or the hero image), her identity mark, and one
   readable line that states the premise — on a muted phone. EV frame 1: her face in the dark back seat, eyes closed, a
   red lamp crossing the clay streak, and a full-width split-flap row clattering onto 18 MONTHS TO ESCAPE THE PERMANENT
   UNDERCLASS, locking on the 1.20 s beat; her eyes open into the lens on the 1.12 s hit.
2. **No black frames, no slow title card first.**
3. **The premise is on screen by 3 s** (EV: SHOW 01 · SS27 · 11 LOOKS · FRONT ROW: AGENTS by 2.1 s, the title tag by
   3.9 s; SP: an "AI PERSONA · THIS VOICE DOES NOT REPRESENT A REAL PERSON" chip beside her eye in the first shot).
4. **Each bar brings one new piece of information, and nothing sung appears early.** EV's intro cut once per bar
   (2.11 / 3.94 / 5.76 / 7.58 s) through face → scale → profile → destination → a gesture → the arrival.
5. **The first joke lands by about 10–11 s** (EV: on "Agents." the next beat shows a front row of open laptops and no
   people, at 10.8 s).
6. **Plant the hook early** (§2.5): the gesture or object of the payoff appears before it is sung.
7. **Voice and words early.** If the song has a cold open, put its words on screen from 0:00 (SP's spoken first line).
8. **Freeze-frame test:** if the key line is not readable on a phone, enlarge it before changing anything else.
9. Hooks travel; verse jokes don't. The chorus moments people will screenshot (the call-and-response answer, the title
   word) get the cleanest, biggest frames.

---

## 6. Cut rhythm

**Numbers from the two references**

- EV: 141 shots in 306 s. **Mean 2.17 s, median 1.83 s ≈ one bar** at ≈ 131.5 BPM. Shortest 0.44 s, longest 5.4 s.
- SP: 94 shots in 190 s, **mean ≈ 2.0 s**, plus beat-level cuts inside flash and montage shots.
- The board template's guide: average shot 1.5–4 s; for a dense song, about **one shot per 2–2.5 s of song**.
- A calm song (an earlier project, rebuilt after "the entire thing is very off pace and off vibe"): 0.47 cuts per bar,
  mean shot 4.0 s, no shot under 1 s, straight cuts on bar lines.

**EV by section (cuts detected in the master)**

| Section | Time (s) | Cuts | Mean shot | Why |
|---|---|---|---|---|
| intro (no vocal) | 0–9.3 | 6 | 1.33 s | the hook: one new thing per bar |
| verse 1 + pre-chorus | 9.3–80.4 | 43 | 1.62 s | joke-dense spoken verse |
| chorus 1 | 80.4–110 | 10 | 2.69 s | long sung windows: lip sync needs room to settle |
| verse 2 + pre-chorus | 110–159.9 | 18 | 2.63 s | darker, slower |
| chorus 2 | 159.9–181.6 | 12 | 1.67 s | |
| bridge | 181.6–219.9 | 16 | 2.25 s | the countdown |
| drop | 219.9–251.5 | 19 | 1.58 s | plus eighth-note strobes inside shots |
| final chorus | 251.5–280 | 11 | 2.38 s | sung windows |
| outro | 280–306.4 | 5 | 4.40 s | the ring-out |

**Rules**

1. **Every cut within 0.03 s of a beat** (or of a declared hit). Where a word would straddle a cut, move the cut by at
   most 0.028 s so the word stays whole; if the word must straddle (a held note), type it in both shots.
2. Section changes on downbeats or impacts.
3. **Match the cut rate to the song's energy, section by section.** The busiest picture goes on the busiest music. An
   earlier project put its busiest picture on its quietest music (3.2× the chorus's motion) and had to be re-animated
   from scratch.
4. Hold longer on sung close-ups (lip sync needs 2–4 s to settle and be checked); cut faster in spoken, joke-dense verses and drops.
5. No stretch without the lead longer than 2 bars (§7).

### 6.1 Setting the draft's pace per tier (before `slop board draft`)

`slop board draft` cuts each section at a target length in seconds per shot. The default is **the project tier's
pace**: `quick` (≈ 4–7 s a shot), `studio` (≈ 2.5–5 s) or `director` (**EV's measured pace**: intro 1.35 · verse 1 1.6 ·
later verses 2.4 · pre-chorus 1.6 · chorus 2.7 · bridge/break 2.25 · drop 1.55 · outro 4.4 · other 1.85). Every shot
needs its own plate (one image per shot) and its own set, framing, action and prompt, so the shot count sets the work
and the plate bill. Set the tier's pace first, before anyone writes into the board:

- the tier itself (`project.json "tier"`) picks the preset; nothing else to do when the tier is right;
- another preset for this project: `"board": {"pace": "studio"}` in `project.json` (keep every other key, and any other
  `board` settings such as `lead_min`), or for one draft `slop -p <name> board draft --pace studio`;
- your own seconds per section: a block like the ones below. A key you leave out keeps the tier preset's value, and
  `chorus` also sets the middle and last choruses unless the block names them.

**Quick** (≈ 4–7 s a shot; the `quick` preset, written out):

```json
{"board": {"pace": {"intro": 4, "hook": 4, "verse": 5, "verse_late": 5, "pre": 5, "chorus": 6, "post": 5,
                    "bridge": 5, "break": 5, "drop": 4, "inst": 5, "outro": 7, "other": 5}}}
```

**Studio** (≈ 2.5–5 s a shot; the `studio` preset, written out):

```json
{"board": {"pace": {"intro": 2.5, "hook": 2.5, "verse": 2.5, "verse_late": 3, "pre": 2.5, "chorus": 3.5, "post": 3,
                    "bridge": 3, "break": 3, "drop": 2.5, "inst": 3, "outro": 5, "other": 3}}}
```

**Director:** the default (EV's pace), or EV's numbers adjusted per section after the board review.

The keys are section kinds, read from the section names in `beats.json` (confirm them first: 20-analysis §5):
`intro`, `hook`, `verse` (the first verse; `verse_late` is every later one), `pre` (pre-chorus), `chorus`, `post`,
`bridge`, `break`, `drop`, `inst` (instrumental, solo, interlude), `outro`, `other`. The draft's result (with `--json`:
`stats.shots`, `stats.plates`, `stats.mean_s`, `stats.pace_by_section`, and the pace's name and source) shows what you
got: check it against the tier before writing anything.

What the draft does with them, measured on a synthetic 3-minute song with 39 lyric lines (one line every ≈ 4.6 s,
like EV):

| Pace | Shots | Per minute | Plates | Mean shot |
|---|---|---|---|---|
| director (EV's) | 85 | 28 | 78 | 2.1 s |
| studio | 58 | 19 | 56 | 3.1 s |
| quick | 41 | 14 | 41 | 4.4 s |

On a quick board the lead can sit in almost every long shot (the 2-bar rule of §7); when the draft reports a lead
share above 85 % it prints a `board set … --no-lead` command for the shot that brings it down.

**The floor is one shot per lyric line.** Whatever the pace, the draft starts every lyric line in its own shot when a
beat allows it, so a song with 50 lines gets at least about 50 shots. To go lower (a Quick project with a dense
lyric), merge neighbouring `plate3d` or `still` shots by hand after the draft (never shots inside a clip window): keep
the first shot's id, set its `t1` to the second shot's `t1`, list both lines in `lines` and `type`, delete the second
shot and its entry in `plates`; then re-run `slop board audit`. The plate count follows the shot count (minus the
shots that continue one clip), and the plate cost with it: about $0.004–0.05 an image on the API (51-plates-api),
times `board.api_candidates` (default 2) per plate.

If `slop board draft` was already run, change the pace and re-run it with `--force` (the old board is kept as a
`.bak.json` copy) before anyone writes TODOs into it.

---

## 7. Lead share

1. **Target: the lead on screen ≥ 70 % of the runtime** (the audit's default; set another floor in `project.json` as
   `"board": {"lead_min": 0.6}`). EV reached 83.2 %; the draft aims at 78 %; the audit warns above 85 % (leave room for
   inserts and graphics). A second main character can lower it (SP planned 60 %): record the target in `DECISIONS.md`.
2. **Count honestly:** `lead_on_screen` is true only when she is recognisable (face, figure, or back view). Hand, boot,
   tag and prop macros are inserts and count as false.
3. **No stretch without her longer than 2 bars.**
4. To raise the share, **convert prop inserts, not her shots**: put the prop in her hand, or her reflection in it.
5. **She sings on camera** for most sung words (EV: 62 % of sung words, plus 17 % of spoken words said straight to the
   lens), in chained lip-sync windows.

---

## 8. Motion tiers and the budget

### 8.1 The four tiers (`motion_tier`)

| Tier | What it is | Use when | Cost |
|---|---|---|---|
| `still` | a plate (or no plate) moved in code: crops on eighths, stills swapped on the beat; or pure motion design | stillness is the design, or a graphic says it better | free |
| `plate3d` | a plate with its depth map, animated in 2.5D with a treatment (§3.8) | most non-hero shots; "that's where we'll have to shine" | free (CPU) |
| `motion` | a video clip from the plate (first frame or reference) conditioned on the song window; nobody's mouth forms words | a real turn, a fall, fabric, water, a crowd moving, a camera move a still can't give | paid per second |
| `sung` | a video clip with a clean vocal of only her words as the audio reference; her mouth matches the song | she sings or speaks on camera | paid per second + covers |

Expensive motion only where a real move sells the shot; cheap motion everywhere else.

### 8.2 Budgets

| | Quick | Studio | Director |
|---|---|---|---|
| Clips planned | 4–8 (the default budget is 24 s of clips; raise `budget.motion_s` for more) | 12–25 (incl. lip-sync windows) | EV 47 clips (224 s planned); SP 101 clips (≈ 400 s: ≈ 116 s sung + ≈ 282 s motion) |
| On screen as video | 24–60 s | 25–50 % of runtime | ≈ 50 % of runtime |
| Seconds generated | ≈ 2 × planned | ≈ 2 × planned | EV 421 s; SP 809 s |
| Typical cost | $3–20 (480p / cheap models) | $50–100 | ≈ $95–110 + Higgsfield credits |

**The board's budget** is `project.json "budget": {"motion_s": …}`: the planned seconds of sung + motion clips. Without
it the defaults are **quick 24 s, studio 120 s, director 200 s**. `"board": {"max_clips": N}` caps the clip count. The
draft adds a 60 % allowance on sung seconds for divergence covers when it fits windows into the budget.

**Estimate before G5:** `planned seconds × 2 × $0.231` at 720p on OpenRouter (or × 7 credits on Higgsfield). EV's
planning cap was ≤ 200 s across ≤ 45 clips; leftover budget went to replacing the most repetitive 2.5D shots with
motion (the owner: "if we come out at the end significantly below budget … lets just do some more gens to replace
some of the more repetitive 2.5d plates").

### 8.3 Rules for clips in the board (details in 60-clips)

1. Clips are 4–12 s; **a sung window is 4–8 s**; never more than 8 s of singing in one clip.
2. **A sung window starts in a gap between words** (never mid-word) and **its prompt quotes exactly the words sung
   inside it**.
3. Plan every sung passage she is on camera for as a **chain of windows with alternating framings**, so a cover cut
   lands as a designed cut.
4. Several shots may cut from one clip (`clip` repeats across shots), but each shot only uses the clip inside the
   clip's own song window.
5. Choreography before words: if she must arrive before she speaks, the audio window places the words after her
   arrival (SP: the ghost glides in for 1.9 s, then whispers).
6. Every motion clip has a cheap fallback written in `notes` (a 2.5D push with 2–4 pose stills swapped on beats); every
   sung window has one (a cover, else cut away to other coverage; never hold an out-of-sync mouth).
7. **A sung shot's plate shows her mouth fully visible, with nothing in front of it**: no microphone, no hand at the
   lips, no hair across them. That plate is the lip-sync start frame; in the Studio run a mic at her mouth held one
   clip to 26 % in sync. `slop plates book` adds `her mouth fully visible, nothing in front of her mouth` to every
   sung plate's prompt itself, and on API jobs `(no microphone, hand or hair)` (Midjourney draws what a prompt names,
   so its prompts name no object there; a canon headset stays "at her cheek", `50-plates-midjourney.md` §4, slot 4).
   `slop board audit` warns, first in its list, when a sung shot's prompt, action or the lead canon puts a microphone
   or a hand there, naming the shot whose prompt the book reads. Never write "singing into a microphone".

### 8.4 A clip made after the board: link it to its shots

A clip made later (a motion take for a span, a retake, a replacement window) does not play on a shot whose tier is
still `plate3d`: the edit shows a clip only on a `motion` or `sung` shot. `slop board audit` names such a clip ("plays
on no shot") with the command for the shots its span covers. Link it:

```
slop -p <name> board set s001-s002 --tier motion --clip c08
slop -p <name> edit edl                         # s001 and s002 now play c08 in song time
```

`board set --clip` checks that the clip exists (`clips/<clip>.json`, or the board's clip plan), is a root clip (not a
cover), matches the tier (a `motion` shot plays a motion clip, a `sung` shot a sung one; without `--tier` the shot
takes the clip's kind), and that its song window overlaps the shot (a partial cover warns: the edit holds a frame or
leaves a hole there). A shot that becomes a clip shot loses its plate-only treatment (its plate stays as the stand-in
until the clip has a delivered take); `--tier plate3d` or `--tier still` unlinks the clip, and `--clip none` unlinks it
on a clip shot. `--tier motion` (or `sung`) alone on a shot that plays a clip of the other kind is refused: add
`--clip <a clip of that kind>` or `--clip none`. EV's `seedance` tier is read as the clip's kind. The clip plan in
`seedance[]` follows: the shot leaves its old plan entry, and an entry left with no shot that was never made is dropped,
so it no longer counts in the motion budget and the audit stops listing its `clip new` (the note prints that command,
should you want the clip after all). `board fill` takes the same `tier` and `clip` columns. Then re-audit: the board changed, so an approved
board needs the owner again (§11.3).

---

## 9. `board/shots.json` (the contract)

Top level: `{"version": 1, "duration": <s>, "chapters": [...], "shots": [...], "seedance": [...], "plates": [...]}`.
Chapters: `{id, name, t0, t1, sections, grade, accent, set}`. Plates: `{plate, set, mj_prompt, id_pass, aspect,
used_by: [shot ids]}`. The clip details live in `clips/<clip>.json` (60-clips); `seedance` keeps EV's summary list for
compatibility.

**Shot fields**

| Field | Type | Rule |
|---|---|---|
| `id` | `"s001"` … | stable once the owner has reviewed them (merged shots keep the first id) |
| `t0`, `t1` | seconds | on beats (within 0.03 s) or declared hits; shots tile `[0, duration]` |
| `section` | string | a section name from `beats.json` |
| `lines` | [int] | the lyric line numbers whose words fall in the shot |
| `set` | string | the place |
| `lead_on_screen` | bool | honest (§7) |
| `framing` | `ECU / CU / MCU / MS / MWS / WS / FS / EWS / OTS` | §3.2; not needed on a `pure-motion` shot |
| `action` | string | concrete, with an end state |
| `camera` | string | one move, tied to a sound |
| `motion_tier` | `still / plate3d / motion / sung` | §8 |
| `plate` | plate key or null | null only for pure motion design |
| `clip` | clip id or null | for `motion` / `sung` |
| `mj_prompt` or `img_prompt` | string | the plate's prompt (50/51 docs); framing first; ends "no text, no letters, no logos" |
| `type` | [{`line`, `mode`, `text`, `placement`}] | `mode` ∈ subtitle / coverline / masthead / stack / mass; `placement` names the empty field |
| `devices` | [{`kind`, `anchor`, `params`, `key`}] | `key` ∈ W / B / H / F / T (§3.7); the explaining graphic is one of these |
| `treatment` | string or null | a 2.5D family (§3.8); never the same on consecutive 2.5D shots |
| `transition_in` | string | `cut`, or the motivated device |
| `chrome` | string | what the always-on devices show in this shot |
| `accent` | hex | the chapter accent |
| `notes` | string | fallbacks, the owner's notes on this shot, warnings |
| `hit` | seconds (optional) | a declared hit this shot starts on, when the cut is meant to sit on a sound rather than a beat |

**Example (EV's first shot, in this schema; its "young" is EV's retired wording, and new prompts use today's identity
text from the canon):**

```json
{"id": "s001", "t0": 0.0, "t1": 2.111, "section": "intro", "lines": [],
 "set": "Waymo back seat, US-101 at night", "lead_on_screen": true, "framing": "CU",
 "action": "Frame 1 is her face in the dark back seat, eyes closed. A red lamp slides across her face left to right and lights the clay streak and the spark clip. On the song's first hit (1.12) her eyes open straight into the lens and stay there.",
 "camera": "locked, very slow push in (3%)", "motion_tier": "motion", "plate": "waymo-cu", "clip": "SD01",
 "mj_prompt": "close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, sitting upright alone in the back seat of a driverless robotaxi at night, her face in the centre of the frame, eyes closed, a single red lamp sliding across one cheek through the side window, dark leather seat, the lower third of the frame dark and empty, blue-black night, fog, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic 35mm film still, no text, no letters, no logos",
 "type": [],
 "devices": [
   {"kind": "flap", "anchor": {"slot": "bottom"},
    "params": {"rows": [{"text": "18 MONTHS TO ESCAPE THE PERMANENT UNDERCLASS", "prev": "", "at": 0.0}], "cw": 36, "gap": 3}, "key": "F"},
   {"kind": "sheet", "anchor": {"box": "a face"},
    "params": {"title": "EXPRESSION · MODEL 01 · LIVE", "rows": [["CALM", ".98"], ["WORRY", ".02"], ["THRESHOLD · WORRY > 0.50", "NOT MET", "hot"]], "w": 420}, "key": "B"},
   {"kind": "cv.bracket", "anchor": {"box": "a face"}, "params": {"label": "FACE · MODEL 01", "conf": 0.99}, "key": "B"}],
 "treatment": null, "transition_in": "cut",
 "chrome": "BOARD full-width across the lower third, cap 4.5% of height, clatters from frame 1 and settles by 1.5 s",
 "accent": "#D97757",
 "notes": "HOOK frame 1. One-second test: at 1.0 s her face, the streak and a readable board line on a muted phone."}
```

(The explaining idea of s001: a face that is not worried under the year's most-quoted threat — the expression meter
says so in numbers.)

How the devices read: the `flap` board (44 cells of 36 px; the default 40 px cells would not fit 44 characters in
1920 px) starts flipping at song second 0.0 (`at`, a fixed time, so key `F`) from blank (`prev: ""`), cell by cell
from the left, and settles in about 1.5 s; to make a row flip on a word instead, give it `"at": {"word": [line, i]}`
(key `W`; §3.7 lists the time specs). The `sheet` types its three rows one per sixteenth from the first beat of the
shot, beside the face, with the last row in the accent (`"hot"`). The `cv.bracket` frames the face with its label and
confidence. Each device's own params are its `defaults` in `engine/src/devices/*.js`.

---

### 9.1 Writing the board with commands (never by editing JSON)

The draft leaves every creative field as a TODO. Write them with these commands; each one checks every value against
what the engine reads, changes nothing when a value is wrong, and is safe to repeat:

| To write | Command |
|---|---|
| one shot's fields | `slop -p <name> board set s004 --set "a night market under sodium lamps" --framing MS --action "she counts coins into a paper cup, then looks up" --img-prompt "medium shot of {lead} counting coins at a night-market stall, sodium lamps, the upper third empty, no text, no letters, no logos" --camera "slow push in on the kick" --treatment layers --transition-in cut` |
| several shots at once | the same with `s004,s007` or a range in board order, `s004-s009` |
| the lead on screen or not | `slop -p <name> board set s004 --no-lead` (or `--lead`) |
| a typed line's mode and place | `slop -p <name> board set s004 --line 3 --type-mode coverline --type-placement left` (written to every shot that types line 3: one mode and one position, held across cuts) |
| the lead box when the plate has no depth map | `slop -p <name> board set s004 --subject-uv 0.40,0.15,0.25,0.70` |
| a shot's tier, or a clip made after the board | `slop -p <name> board set s001-s002 --tier motion --clip c08` (checked against the clip, §8.4; `--tier plate3d` unlinks it) |
| many shots from a table | `slop -p <name> board fill shots.tsv --check`, then `slop -p <name> board fill shots.tsv` |
| a device (the explaining graphic) | `slop -p <name> board device add s004 --kind callout --line 3 --anchor uv:0.62,0.4 --param word=walk` |
| change or remove a device | `slop -p <name> board device list s004`, then `board device add s004 --replace 1 …` or `board device rm s004 --index 1` |

`board fill` takes a TSV (a header row of field names: `id`, `set`, `framing`, `action`, `img_prompt`, …; an empty
cell leaves the field as it is) or JSONL (one `{"id": "s004", "set": "…"}` per line). One bad row fails the whole fill
and the error lists every bad row; nothing is written. A `devices` column REPLACES the shot's whole device list.

Next-step hints print markers to replace, such as `--set "<the place, concrete>"` or `--framing "<ECU|CU|…|OTS>"`.
Text that still holds a marker (`<…>`), only dots, `TODO`, or a bare hint word such as WORD is refused by these
commands and by the audit, so a hint pasted unchanged never passes. After adding devices, refresh the engine data with
`slop -p <name> edit export --no-frames` before `slop render stills`.

## 10. Audits: `slop board audit`

Run it after every edit to the board. It writes `board/audit.json`, prints a table, and exits non-zero while any gate
fails. The board is not sent to the owner until it passes.

| Gate | Fails when | Fix |
|---|---|---|
| `tile` | a gap or overlap in `[0, duration]` | extend the neighbour to the shared beat |
| `cuts` | a cut is more than 0.03 s from a beat or downbeat and is not a declared hit (`hits.json`, `project.json` added hits, or the shot's own `hit`) | move it to the nearest beat; if a word straddles, shift ≤ 0.028 s |
| `words_typed` | an aligned sung word starts in a shot whose `type` doesn't list its line | add the line to that shot's `type` (held across the cut: same mode and position) |
| `graphics` | a lyric line with no explaining graphic: no `devices[]` entry tagged `"line": N`, no untagged device on the shot where the line's first word starts (one untagged device serves one line), and no code-drawn shot typing the line | add the device the audit names (it prints the shot and an example entry) |
| `lead_share` | `lead_on_screen` seconds / duration below `board.lead_min` (default 0.70) | convert prop inserts into shots with her; don't relabel |
| `motion_budget` | planned sung + motion clip seconds over `budget.motion_s` (or more clips than `board.max_clips`) | demote the weakest motion shots to `plate3d` |
| `clip_windows` | a sung window outside 4–8 s or a motion clip outside 4–12 s; a sung window not starting in a word gap or not listing its exact words | move `song_t0` into the gap before the first word; copy the window's words exactly |
| `plates_unique` | a plate on two shots that are not one continuous moment; two clips from the same start frame; two plate keys picked to the same file | use the plate's other candidates (`slop plates vary`), a new plate, or pure motion design |
| `banned` | a word from `project.json "banned"` anywhere in the board | rewrite |
| `treatments` | a 2.5D shot without a `treatment`, or two consecutive 2.5D shots that draw the same engine family (`layers` after `layer-separation` counts) | pick another family |
| `todo` | any `TODO` marker left, or a shot without a valid framing (the draft's per-line "TODO: one explaining graphic for line N" note clears itself once `graphics` counts that line) | write it |

Warnings (not gates, but fix them): first, a sung shot whose prompt, action or lead canon puts a microphone, a hand or
anything else at her mouth (§8.3 rule 7); lead share above 85 %; the same transition device twice in a row; a chapter
with 5 or more 2.5D shots using fewer than 5 treatments; a `plates[]` entry no shot uses; a shot linking a clip that is
neither planned nor made, or a clip of the other kind; a clip made for a shot the plan gives another clip, or a made
clip the edit plays on no shot (link it, §8.4). A plate a shot uses but `plates[]` does not list fails `plates_unique`.

The audit also prints `clip_cmds`: the exact `slop -p <project> clip new …` line for every planned clip not created yet
(each `seedance[]` entry carries it as `cmd`, plus `next`). `slop board audit --shots OTHER.json` audits another file
and writes `OTHER.audit.json` next to it (never `board/audit.json`), and `slop board approve` re-audits and records the
approval through `slop gate board --approve` (logged in `DECISIONS.md`).

Also check by hand: full-frame flashes at most 3 in any second (the render's `slop render check` measures it).

---

## 11. The board sheet and the review ritual (gate G4)

### 11.1 The sheet

One card per shot, in order: the picked frame (or the plate prompt's first words if there is no image yet), the id,
the time, the lyric, the framing, the action in one line, the motion tier, the explaining graphic in one line, and a
`FACE?` badge on plates whose face may be off-model. EV's was 13 pages at 12 cards a page, with a cover page showing
the chapter map. `slop -p <name> board sheet` writes `board/board.pdf` and `board/board-pNN.jpg` pages; pass
`--flags flags.json` (`{"<plate>": "note"}`) to badge suspect faces `FACE? note`. Review graded frames if the project
has a grade: the owner judges what the film will look like.

### 11.2 The message (one message)

```
The storyboard for <TITLE> is ready: <N> shots, lead on screen <X> %, <M> motion clips (<S> s, est. $<E>).
[board sheet attached]
Please flag anything by shot id: faces, repeats, boring moments, story logic, colour.
<If the owner set an approval window:> I'll go ahead in <W> minutes unless you say stop.
Open questions: <likenesses? / my additions in this draft: …>
```

### 11.3 The rules

1. **Silence counts as approval only if the owner set the window** (EV: "just wait like 5 mins once you send it and
   if I don't respond take it as approval to do the entire thing"; once they asked for 15). Record the window in
   `DECISIONS.md`. Silence never approves spending: the plate and clip spend waits for G5.
2. While you wait, do only work that costs nothing (the plate prompt book, contact sheets), never generation.
3. **Log every note verbatim**, against its shot id, in `DECISIONS.md`. SP's owner left 70 notes; each one changed a
   prompt or a plate.
4. **Apply every note.** If two notes conflict, the later one wins; if a note conflicts with the concept, ask once.
5. Re-run the audit; re-send only if the owner asked to see it again ("make all those changes and we're good to go"
   means proceed).
6. Run `slop -p <name> board approve` (it records `gates.board_approved` only when every gate passes) and continue.
7. **A change after the approval makes the board gate stale.** The approval records what it covered (the content of
   `board/shots.json`); `board set`, `board fill`, `board device add/rm`, `plates vary` and `board draft --force`
   print one warning line when they change an approved board. Tell the owner in one line what changed and why (e.g.
   "I added a layer to s009 and s017 after the layer check; the board needs your OK again"), and after their yes run
   `slop -p <name> board approve --note '<their words>'` (it re-audits first and logs their words; `slop -p <name> gate
   board --approve` records the same gate). Never carry on as if the old approval covered the new board.

### 11.4 What owner notes look like (and what each changed)

| Note (verbatim) | What it changed |
|---|---|
| "two seedance videos shouldnt start from teh exact same frame - either use the last frame of the previous video to pick it up, or choose another starting frame" | the distinct-start-frame rule |
| "the 2.5d plates - thats where we'll have to shine … diversity so its not repetitive" | a treatment per shot, never repeated back to back |
| "s058 has a backwards head btw" | a plate re-roll |
| "theres 3 guys here just looking straight and ear plugs arnet set in. the man whos being tied to mast shouldnt have earplugs because he want sto hear." | the crew recast; a story-logic rule in the canon |
| "the boat looks too small compared to s022 / s023." | scale continuity: the plate re-made as a long galley |
| "its kinda bodyslop, need her as a virtual ghost or something, its just two heads next to eachother." | a new idea for the shot, not a re-roll |
| "feel like we could do more with this shot." | a stronger explaining graphic (the clock became the P(doom) meter) |
| "s034-s036 could use more creativity, kind of a boring moment." | three shots rethought (replay addiction, tally marks) |
| "he needs to have cyberpsychosis still - eyes must be silver again here." | continuity of an effect across shots |
| "the one saying untie me should actually be the main character woman" | the ending restructured (the flip) |

---

## 12. Worked examples (verbatim from the two boards)

**EV hook, 0.00–12.15 s** (the shots after s001):

```
s002 · 2.11–3.94 · intro · EWS · 2.5D · plate waymo-101
- action: The fogged 101 at night: rows of blank billboards, red tail lights, and one white Waymo (compact electric SUV,
  spinning roof lidar) alone in the fast lane, her silhouette in the rear window.
- camera: 2.5D slow push down the lanes, fog layer drifting
- chrome: BOARD row stays full-width; LOOK 00/11 and SHOW 01 · SS27 · 11 LOOKS · FRONT ROW: AGENTS tick in on eighths
- joke: a billboard skyline with nothing on it; the show premise is on screen by 3 s

s005 · 7.58–8.50 · intro · CU · 2.5D · plate buckle-cu
- action: Her hand pulls the harness strap tight; the buckle clicks shut on the 8.04 beat (2-still swap: open, closed).
- joke: strapping in: "lock in" as a gesture, 71 s before it is sung
- notes: The buckle click recurs on every "Lock in", harder each time.

s006 · 8.50–10.78 · intro · L0 · FS · Seedance SD02 · plate waymo-arrive
- action: Inside the data hall the robotaxi stands at the head of the catwalk with its rear door open; she steps out onto
  the wet concrete and stands upright facing the lens.
- type: L0 coverline "Ladies. Gentlemen. Agents." upper-right dark panel, word by word · L0 masthead "AGENTS." hard cut +
  1-frame flash on 10.26, held into the next shot
- notes: Door already open in the plate; no door motion needed.

s007 · 10.78–12.15 · intro · WS · 2.5D · plate hall-laptops · enters on: flash
- action: Cut on the next beat to the front row the word was addressed to: every folding seat holds an open glowing
  laptop and no person.
- joke: the audience is agents (the first joke, at 10.8 s)
```

**EV verse shot with a chart as the explaining graphic:**

```
s025 · 44.05–47.25 (3.19 s) · verse 1 · L7 · Look 03 · data hall catwalk · lead ✓ · CU · 2.5D plate · plate dadcap-cu
- action: Under the brim she stares into the lens while the weekly-limit bars draw on the beat: 150 falls to 125,
  +25% is struck through, and = −17% lands in red.
- camera: slow pull back
- type: L7 masthead "+25% / = / −17%" @ right half, one token per beat
- joke: a "permanent +25%" that was a 17% cut
```

**EV chorus shot (original JSON):**

```json
{"id": "s045", "t0": 80.9273, "t1": 84.1201, "section": "chorus 1", "lines": [17], "framing": "FS",
 "action": "The hero walk: she comes down the catwalk toward camera singing, the board's flaps strobing on the kick and bands of clay light crossing the floor.",
 "camera": "tracking back (SD07)", "motion_tier": "seedance", "seedance_clip": "SD07",
 "type": [{"line": 17, "mode": "subtitle", "text": "18 months to escape the underclass", "placement": "bottom baseline, karaoke fill in clay"},
          {"line": 17, "mode": "masthead", "text": "UNDERCLASS", "placement": "upper third over the board, on 83.08"}],
 "chrome": "BOARD 18 · LOOK 06/11 · CV brackets track her walk: MODEL 01 · LOOK 06 · timecode at song tempo",
 "accent": "#D97757", "transition_in": "cut"}
```

(EV's tiers were `seedance / plate25d / code`; in this toolkit they are `sung` or `motion` / `plate3d` / `still`.)

**SP chorus shots (the prose board format):**

```
s025 · 0:43.1 (1.7 s) · on "TIE" (line 9) · TIE ME TO THE MAST! ①
- See: Her voice alone sings the first shout. Pictogram ① flashes full-frame; the beat is full now. Her on the rock at
  dusk, singing it with all her voice; then, on the eighths, the crew carry out the order: the man backs against the
  mast and two rowers whip the rope round him: rope, hands, knot, his face. The lyric itself wraps round the mast in 3D
  like a second rope, behind the mast on the far side, in front of him on the near side.
- Camera: her held; then handheld, cut on eighths · MCU → MS
- Graphics: Pictogram ① "TIE HIM TO THE MAST". The type helix is rotoscoped around the mast and his body.
- Type: mass: TIE ME TO THE MAST! as a rope of type
- Source: SING + MOVE · lip-sync W06b · plates: siren-shout, tying

s026 · 0:44.8 (1.6 s) · on "You" (line 10) · "You don't have to die." whisper
- See: A little wider now: the man tied at the mast, looking out to sea. She drifts in beside him, floating level like a
  diver, chest to the deck, see-through, and puts her lips to his ear to whisper the line.
- Camera: locked; she enters from frame left · MWS
- Graphics: A hairline of her spectrum flowing into his ear; a tiny source tag: "SOURCE: SIREN ROCK, 2.4 NMI · ALSO:
  INSIDE HIS HEAD".
- Source: SING + MOVE · lip-sync W07 · plates: mast-dusk-wide, ghost-float
- Note: the video model gets mast-dusk-wide as the first frame and ghost-float (an isolated pose plate on a plain
  backdrop) as her reference; the transparency is done in the comp.
```

Notice in both: the shot starts on a word or a beat, the action has a beginning and an end, the camera has one move,
the graphic is the meaning of the line, and the source (plates, clip window) is named.

---

## 13. What changes per tier

| | Quick | Studio | Director |
|---|---|---|---|
| Who writes it | `slop board draft`, then the bot writes the TODOs briefly | `slop board draft`, then the bot writes every TODO, section by section | delegated: a storyboard panel, or the lead writing from the owner's walkthrough plus a critic (the draft is a useful skeleton for both) |
| Pace (§6.1) | set the Quick pace before drafting | set the Studio pace before drafting | EV's pace (the default) |
| Shots | ≈ 15 per minute: about one per lyric line (a 3-min song ≈ 40–50) | ≈ 20 per minute (a 3-min song ≈ 55–65) | ≈ 25–30 per minute (EV 141 for 5:06; SP 94 for 3:11) |
| Explaining graphics | one device per line from the library | one per line, chosen per shot | one per line, bespoke where the meaning is unique |
| Review | the owner skims the sheet | sheet + notes | sheet + shot-by-shot notes + open questions |

**The Director-tier panel** (EV, ≈ 1.5 h): three directors board the whole song independently from different angles,
three judges score every board, a head director merges and runs the audit in code. The angles:

- *Purist:* "restraint and gravity, long deadpan passes, few but perfect cuts; the jokes land in the type, tags and
  graphics, not in slapstick."
- *Density:* "timeline-scroll energy — every line its own one-glance visual joke, inserts on the beat, graphics between
  her shots; maximum rewatch value."
- *Narrative:* "a journey — every chapter a place, motivated transitions (a door opens onto the next set, a board flips
  into the next scene), an ending that is earned."

The judges' lenses: a music-video director and a viewer of the target audience (is the first 3 s a hook, would people
rewatch and screenshot, does every reference land in one glance, is the lead the star?); the owner's taste and the
lyric-video rules; a producer (is it buildable within the budget, are windows in word gaps, is 0 to the end covered?).
Merge rule: start from the best-scoring board, graft every judge-listed best idea that fits, apply every fix. On EV the
narrative board won (238.1 vs 235.4 vs 209.9).

**The critic** (SP, one agent, before the owner's review) reads the board as "someone who knows neither the myth nor the
memes" and returns, in this order: where a viewer would lose the thread; drag and pacing against the per-bar energy;
the 8–12 weakest shots with a sharper replacement each; 3–6 missed opportunities; taste and real-people risks. At most
≈ 900 words, ranked by impact. It never edits files.

The delegation templates are in `templates/workflows/` (95-delegation).

---

## 14. Checklists

**Before writing shots**
- [ ] the tier's pace checked before `slop board draft` (§6.1: the tier's preset, `board.pace`, or `--pace`); shot and
  plate counts read from the draft's summary and fit the tier
- [ ] sections confirmed (`slop song sections` shows no GUESS left; 20-analysis §5)
- [ ] ear-check done; sections named; display tokens exported without errors
- [ ] treatment, through-line schedule, chapter map, devices list, plants and payoffs written
- [ ] motion budget for the tier written in `DECISIONS.md`; density budget chosen

**Before the audit**
- [ ] every TODO written with `board set` / `board fill` / `board device add` (§9.1), never by hand in the JSON
- [ ] every lyric line typed in one mode and one position; every line has an explaining graphic
- [ ] hook passes the one-second test; premise by 3 s; first joke by ≈ 11 s
- [ ] every motion/sung shot has a fallback in `notes`; sung windows 4–8 s from word gaps
- [ ] one image per shot; distinct clip start frames; treatments vary
- [ ] transitions: mostly cuts on beats; a motivated device every few shots; never the same twice in a row

**Before G4**
- [ ] `slop board audit` passes
- [ ] board sheet built with graded frames and FACE? badges
- [ ] open questions and "my additions" listed; approval window stated only if the owner set one

---

## 15. Common mistakes

| Mistake | What happened | Do instead |
|---|---|---|
| Animated lyrics with no explaining graphics | "not just animated lyrics" was the owner's whole bar | one graphic per line, entering on its word |
| Graphics floating over a picture they don't belong to | "it kind of feels like the graphics on top are not part of the same picture" | draw from the thing in frame; couple to visible features |
| A still with a slow zoom | dead 2.5D | a treatment family per shot, never repeated back to back |
| The same image on several shots | the owner caught it on the board | one image per shot; pure motion design where plates repeat |
| Two clips from the same start frame | "jarring" | other candidates, or the previous clip's last frame |
| Words snapped to the beat | lyrics early or late against the voice | words on the voice, motion on the beat |
| Cuts on a fixed BPM | drift by the end | the beat list; audit within 0.03 s |
| Busy picture on quiet music | a full re-animation on an earlier project | match the cut rate to the section energy |
| Long sung passage as one clip | one divergence ruins it | a chain of 4–8 s windows with alternating framings |
| Poses instead of actions | lifeless takes | action + reaction with an end state |
| Counting a hand insert as the lead | an inflated lead share | honest counting; convert inserts |
| A risky generated move with no fallback | a hole in the film | a simple version and a fallback in `notes` |
| Flashing for its own sake | "dont need to force flashing" | ≤ 3 full-frame flashes a second, only in the design language that owns them |
| A board the viewer can't follow | lost viewers | plant the rules early; run the critic as a newcomer |
| Spending while waiting for the board review | money on a board that changes | free work only until G4 and G5 |
| Drafting a Quick or Studio board at EV's (Director) pace | ≈ 27 shots a minute: 80+ shots, plates and hundreds of TODOs for a 3-minute song | check the tier and its `board.pace` first (§6.1) |
| A device param copied from another board's notes | the device silently draws a default ("UNDEFINED", a 0) | `board device add` (it checks every key); `board device kinds --kind K` for the params; render a still |
| Pasting a next-step hint as it is | `--set "<the place, concrete>"` written into the board | replace every `<…>` marker; the commands and the audit refuse them |
| Editing `board/shots.json` by hand | a typo'd key or framing passed silently until the render | `board set`, `board fill`, `board device add` |
| A motion clip made after the board, left off it | paid footage never reached the edit (Studio run: the shots stayed `plate3d`) | `board set s001-s002 --tier motion --clip c08`, then `edit edl` (§8.4) |
| A microphone or hand at the mouth on a sung plate | Studio run: that clip 26 % in sync | the mouth line `plates book` adds; take the mic out of the prompt; never pick such a candidate (§8.3) |
| Editing the board after the owner approved it, silently | the approval no longer covered the board | say what changed in one line, then re-approve after their yes (§11.3) |
