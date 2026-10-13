# `shots.json` excerpts (verbatim originals + the toolkit's contract form)

The storyboard is data: one record per shot, on beats, with the lyric lines it carries, its framing, footage source, type
modes, explaining graphic and transition. The audit (`80-review-qa.md` §2) and the default renderer read it. Three forms
below: EV's original record (structured), SP's original record (prose fields — the default renderer could draw only its
lyrics), and the toolkit's contract form in `shots.example.json` (structured `type[]` and `devices[]`, so the default
renderer can draw the explaining layer without chapter code).

---

## 1. EV, original (verbatim)

```json
{"id": "s025", "t0": 44.0541, "t1": 47.2468, "section": "verse 1", "lines": [7], "look": "Look 03",
 "set": "data hall catwalk", "lead_on_screen": true, "framing": "CU",
 "action": "Under the brim she stares into the lens while the weekly-limit bars draw on the beat: 150 falls to 125, +25% is struck through, and = −17% lands in red.",
 "camera": "slow pull back", "motion_tier": "plate25d", "seedance_clip": null,
 "mj_prompt": "close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, wearing a washed black baseball dad cap with a blank embroidered front panel, the brim low over her eyes, standing in the left half of the frame, deadpan, the right half empty darkness, blue-black night, fog, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic 35mm film still, no text, no letters, no logos",
 "id_pass": true,
 "type": [{"line": 7, "mode": "masthead", "text": "+25% / = / −17%", "placement": "right half, one token per beat"}],
 "chrome": "BARS (code): WEEKLY LIMIT 150 → 125 · +25% (struck) = −17% · footnote: temporary 50% boost ended",
 "accent": "#d11f1f", "screen": "grain", "lift": 0.05,
 "meme_visual": "Claude Code's 'permanent +25%' that was a 17% cut", "notes": null, "transition_in": "cut"}
```

**Why it worked:** the plate prompt declares the empty field ("the right half empty darkness") exactly where the type and
the chart go; the type mode is chosen for a number joke (masthead, one token per beat); `meme_visual` states the meaning
the graphic must show. (The red accent became clay after v1.)

The same board's hook shot, in the format a weaker model should emit when it writes the board as text:

```
**s025** · 44.05–47.25 (3.19 s) · verse 1 · L7 · Look 03 · data hall catwalk · lead ✓ · CU · 2.5D plate · plate `dadcap-cu`
- action: Under the brim she stares into the lens while the weekly-limit bars draw on the beat: 150 falls to 125, +25% is struck through, and = −17% lands in red.
- camera: slow pull back
- type: L7 masthead "+25% / = / −17%" @ right half, one token per beat
- chrome: BARS (code): WEEKLY LIMIT 150 → 125 · +25% (struck) = −17% · footnote: temporary 50% boost ended
- joke: Claude Code's 'permanent +25%' that was a 17% cut
```

## 2. SP, original (verbatim; the owner's name replaced by the pseudonym)

```json
{"id": "s025", "t0": 43.1, "t1": 44.8, "section": "IV", "title": "TIE ME TO THE MAST! ①", "lines": [9],
 "lead_on_screen": true, "framing": "MCU → MS",
 "action": "Her voice alone sings the first shout. Pictogram ① flashes full-frame; the beat is full now. Her on the rock at dusk, singing it with all her voice; then, on the eighths, the crew carry out the order: the Chad backs against the mast and two rowers whip the rope round him: rope, hands, knot, his face. The lyric itself wraps round the mast in 3D like a second rope, behind the mast on the far side, in front of him on the near side.",
 "camera": "her held; then handheld, cut on eighths", "motion_tier": "seedance", "tier": "SING + MOVE + MG3D",
 "seedance_clip": "W06b", "plate": "siren-shout", "plates": ["siren-shout", "tying"],
 "type": "mass: TIE ME TO THE MAST! as a rope of type",
 "gfx": "Pictogram ① \"TIE HIM TO THE MAST\". The type helix is rotoscoped around the mast and his body.",
 "trans": "", "notes": "anabology (2026-09-30): her voice alone sings the first and third shouts of each chorus, the crowd the second. So she sings \"tie me\" while they tie him: whose mast is it? The final chorus answers. He doesn't voice it.",
 "anchor": {"line": 9, "word": 0, "text": "TIE"}, "sung": "TIE ME TO THE MAST!", "rough": false, "clips": ["W06b", "M-s025"]}
```

**Why it worked (and what to change):** the `anchor` (first word of the line) lets the whole board re-time automatically
when a new take shifts the song; `tier` names every source (lip-sync window + motion clip + 3D type); the user's note is
kept verbatim on the shot. But `type`, `gfx` and `trans` are prose, so the default renderer could not draw them — the
toolkit's contract makes them structured (`shots.example.json`, shot `s025-sp`).

SP's board as text, per shot (the format of its `STORYBOARD.md`):

```
**s005** · 0:08.9 (1.9 s) · on "Why" (line 1) · **"Why would I deceive you?" a cappella**
> Why would I deceive you?
- **See:** Close-up: she sings the answer straight into the lens, eyes open.
- **Framing:** CU
- **Graphics:** Under the lyric, the Greek source and its translation (Homer, Odyssey 12.184–185).
- **Type:** masthead, word by word, in the empty sea: WHY WOULD I DECEIVE YOU?
- **Source:** SING · lip-sync W02 · plates: siren-sing-cu
```

## 3. The contract form

`shots.example.json` holds five shots (EV s001, s025, s045; SP s025, s047) rewritten into `board/shots.json`'s contract:
`motion_tier` is `still | plate3d | motion | sung`; `type[]` has `{line, mode, text, placement}`; `devices[]` has `{kind,
anchor, params, key}` and `key` is the timing key (W word, B beat, H hit, F fixed time, T take keyframe); `treatment`
names the 2.5D family for `plate3d` shots (a code-drawn shot uses `"pure-motion"`, `70-motion-design.md` §11); each
shot's `notes` starts with WHY. Device kind names follow `engine/DEVICES.md` (until it exists, the registered kinds in
`engine/src/devices/*.js`); where a name there differs from this example, DEVICES.md wins.

**Anchors: use what a toolkit project has** (`70-motion-design.md` §5.0). The toolkit detects no boxes and makes no
mattes, so the example anchors devices with `{"uv": [u, v, w, h]}` (a box in image space, 0–1, measured by eye on the
plate or take; it follows the camera), `{"keys": [[t, u, v, w, h], …]}` (a hand-measured track for a subject that
moves; song seconds under keys W/B/H/F, take seconds under key T), `{"rect": [x, y, w, h]}` (screen pixels) and
`{"slot": "right"}` (a free region). The reference boards anchored on detections (`{"box": "a face"}`, `"lead"`); in a
toolkit project those resolve to nothing unless you write the boxes yourself in `<project>/engine/common.js`.
