# Reviews: reviewer JSON, clip QA lines, scan findings, owner one-liners

Real review output from the reference productions, scrubbed. The procedures and schemas are in `80-review-qa.md`.

---

## 1. Reviewer JSON (chapter reviews on real renders)

- `review-pass.json` — SP chapter 02, refit round 2: **8 / 8 / 8 / 8, pass** (the only chapter that reached the numeric
  bar), with 6 of its 12 fixes. **Why it's a good review:** passing did not stop it listing concrete, timed fixes — the
  orange budget (five accent elements where two are allowed), the lyric no longer the biggest type, a snap keyed 70 ms
  before its kick, one ugly occlusion frame on the most important word — each with the exact change.
- `review-fail.json` — SP chapter 01, refit round 1: **7 / 7 / 8.5 / 6.5, fail**, with 6 of its 12 fixes. **Why it's a good
  review:** the canon break comes first (the crew copy the lead man), every fix names shot, time, what is wrong on screen and
  the exact numbers to change (x 196→250, zoom 1.4–1.5, a panel "about 360 wide"), and it checks the user's own notes
  ("rotoscopes that cover text").
- `review-toolkit-form.json` — the failing review rewritten into the toolkit's schema (`owner`, a `severity` per fix,
  `checks`). **Why:** it shows how the script decides — one blocking fix (the canon break) fails the chapter although every
  score clears the floors (owner ≥ 7, others ≥ 6); the five polish fixes are carried into the next pass.

The originals named the first score after the owner; it is shown as `director` in the two original files and as `owner`
in the toolkit form. Context for calibration: the user called the cut built from reviews like these "perfect", though only
one chapter ever scored 8 — so the toolkit ships on "no blocking fix left" (`80-review-qa.md` §8.3).

## 2. Clip QA, one line per take (verbatim)

```
- **W07** · take 1 · **retake** · Higgsfield 28 cr. On-model floating ghost (bob, streak, star clip, headset mic) drifts in from frame left to his ear; he stays on model. Seedance did not copy the whisper (NCC 0.04): the words sat at clip 0.3-1.9 s while she was still in flight; his mouth drops open at the end. Retake with the words placed after her arrival.
- **W07** · take 2 · **keep** · Higgsfield 35 cr, 5 s from song 42.90 (vocal 44.60-46.40 in place, the rest silence). She glides in level from frame left by ~1.5 s and whispers at his cheek/ear in profile; lip sync verified song 44.94-46.40 (lag +725 ms, NCC 0.49, strong diagonal) = all of 'You don't have to die.' He stays silent, eyes widening (mouth parts only after 46.4, outside s026). Notes: her lips touch his cheek rather than the ear (reads close to a kiss); her face is porcelain-pale like the ghost-float reference and she is opaque (transparency in the comp); the orange streak is a wide band as in the reference. Imported as W07-t2.
- **M-s001** · take 1 · **keep** · The push into her eye: from the plate's close-up (freckles, streak, headset wire, wet skin) the camera pushes steadily into the eye until the pupil fills the frame and it ends black with one white highlight at 4.0 s (a clean match-cut point to s002). Smooth, no warping; the iris darkens from the plate's grey-green toward dark on the way in. Note: the eye-open plate itself shows two star clips (left and right).
- **W05b** · take 1 (openrouter) · **keep** · On-model (bob, one streak, star clip, mic, freckles), night rock, sings to lens; sleeveless bodice with ruffle shoulders and long gloves. In sync 36.13-37.17, diverges in 'timeline'; cover W05b-c1 takes over.
- **W05b-c1** · take 1 (openrouter) · **keep** · Cover from the frame at the cut: same framing and look, no jump. In sync 36.73-37.98; the chain holds 96% of the window's sung seconds.
- **W06b** · take 1 (higgsfield) · **keep** · Coverage only, no lip sync. Higgsfield (OpenRouter declined). Visually on-model and on-brief: ruffled long-sleeve gown, hand on chest, eyes closed, gold spray at dusk. The model re-sang the lines instead of copying @Audio1 (no diagonal in the cross-similarity): 0% verified. Lip sync given up for 43.10-44.17.
- **M-s003** · no take · **declined** · declined by the OpenRouter face filter (PrivacyInformation, free) on the siren-mcu (her face close-up) start frame; final for this reference on OpenRouter, never altered. Candidate for Higgsfield with the same reference if credits allow; otherwise the shot stays on its 2.5D plate.
```

**Why these work:** each line gives a verdict, the provider and cost, the measured sync (span, lag, NCC), what the edit
should do with it (cover, give up sync and cut away, comp transparency), and canon notes — and a decline records that the
image was never altered.

## 3. Safety-scan findings (format; contents reconstructed from the production log, not the original file — `XXX`/`YYY` mark clips the log does not name)

```json
{"findings": [
  {"clip": "M-sXXX", "time": 2.1, "severity": "block", "kind": "anachronism", "what": "a steel warship in the haze on the horizon behind the galley"},
  {"clip": "M-s082", "time": 1.4, "severity": "block", "kind": "anachronism", "what": "bright orange industrial ear defenders (earmuffs) on two rowers instead of small foam earplugs"},
  {"clip": "W06b", "time": 2.8, "severity": "fix", "kind": "canon", "what": "the Siren's gown has a cleavage cutout; canon is structured, high-necked, long sleeves"},
  {"clip": "M-s010", "time": 0.6, "severity": "fix", "kind": "canon", "what": "the rowers look like copies of the bald bearded man in black"},
  {"clip": "W11", "time": 2.3, "severity": "fix", "kind": "canon", "what": "the man wears her headset microphone from 2.3 s on"},
  {"clip": "M-sYYY", "time": 3.0, "severity": "note", "kind": "soft focus", "what": "the far figure is soft for a few frames"}
 ],
 "checked": ["M-sXXX", "M-sYYY", "M-s010", "M-s082", "W06b", "W11"]}
```

Outcomes on SP: 15 plates corrected with the image-edit model, 23 clips re-made and re-scanned, two windows rejected, two
trimmed, three canon breaks cropped in the touch-up (the earmuffs, the mic on him after 2.3 s, a take after 6 s). The
intended satellite-dish prop was wrongly flagged as a block — whitelist intended anachronisms by name.

## 4. The owner's review, one line per item (verbatim)

Storyboard and plate reviews arrive as one message of short notes keyed by shot id; log each as a row, act on each, and
turn each into a rule where it generalises:

```
s058 has a backwards head btw , s115 / s117 / s118 / s120 / s121 repetitive, some more near the end tend to repeat a lot, maybe it ran out of new gens? please look at that and fix
```
```
wrong: arena, flap-wide, freeway-dream, hacker-house, hall-cu, mission-fire, ramp-white, shoes-off, takeoff, waymo-cu, waymo-seat, white-catwalk. others are good. the consistn issue is that she gets turned asian. i think if you just specify that shes caucasian / american in the prompt itll work each time
```
```
s010 - doesnt seem riht , theres 3 guys here just looking straight and ear plugs arnet set in. the man whos being tied to mast shouldnt have earplugs because he want sto hear. s011 the boat looks too small compared to s022 / s023. … s016 - its kinda bodyslop, need her as a virtual ghost or something, its just two heads next to eachother. … s027 shot is pretty but not sure how the vid gen will come out since the earplug is just floating
```
```
its perfect. change nothing.
```

**What each became:** a backwards head → re-roll + an anatomy check in the scan; repeats → the one-plate-per-shot audit;
"she gets turned asian" → the pinned canon descriptor + the 4-plate face gate; "shouldnt have earplugs because he want sto
hear" → a canon rule in every prompt ("No earplugs on him, ever") and a scan `fix` item; "the earplug is just floating" →
a prompt constraint line ("The plug is always held, never floating"); "its perfect. change nothing." → the v1 verdict that
calibrates the reviewers.
