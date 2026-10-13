# 80 · Review and QA: gates, contact sheets, reviewers, the safety scan, the owner's eye

Quality in the reference videos held only where it was **measured**. Every rule that survived became a check: every sung
word on screen at its time, cuts within 0.03 s of a beat, lip sync verified by audio, frames independent of render order,
≤ 3 flashes a second, correct colour tags on the master, a safety scan of every generated take. This document lists those
gates, how to run them, what "pass" means, and what to do on a fail. Then it covers the human-shaped reviews: contact
sheets, the reviewer agent's score, the safety and canon scan, and the owner's own review.

> Two lessons frame everything below. **"If a reviewer can see it and the judge cannot, the judge is wrong"**: every
> observation the user makes becomes a metric or a required field the same day. And **a missing or empty review is a
> failure, never a pass**: a usage limit once made reviewers return nothing, the scripts read "nothing" as "nothing to
> fix", and two runs reported success with no review at all.

Command names below follow the toolkit's CLI contract. Exact flags: `slop <command> --help`. **Put the global flags
first, always:** `slop --json --project NAME <command> …` (e.g. `slop --json --project my-song clip sync W07`). That
form works for every command. Some command groups (e.g. `render`, `board`, `plates`, `edit`, `gate`, `spend`) also
accept `--json`/`--project` after the subcommand; others (e.g. `analyze`, `lyrics`, `clip`, `gen`, `sync`, `taste`)
reject them there with "unrecognized arguments" and exit 2, printing no JSON. The commands below are written without
the global flags; add them in front.

---

## 1. The gates (run them in this order)

| # | Gate | Command | Pass | When | On fail |
|---|---|---|---|---|---|
| 1 | **Alignment ear-check** | `slop analyze` writes `analysis/report.md` with the ear-check list | every listed word (gap > 1 s inside a line, low confidence) listened to and fixed or accepted | before the storyboard | `slop lyrics fix --word N --t0 A --t1 B --note "…"` (one word, index from the report) or `slop lyrics fix --line L --shift S --note "…"` (a whole line, 1-based); it marks the words `src: manual` and keeps the note; then `slop edit export` (`20-analysis.md`) |
| 2 | **Board audit** | `slop board audit` → `board/audit.json` | all checks green (§2) | after every storyboard edit | fix `board/shots.json`; re-run |
| 3 | **Prompt book read** | (human), then `slop gate prompts --approve --note "<the owner's words>"` | the user said "go" on the exact prompts that will spend, and the gate records it (it unlocks spending) | before any paid generation | rewrite; never spend on unread prompts; never approve the gate for the owner |
| 4 | **Clip QA + AV-sync coverage** | `slop clip sync CLIP` per take; `slop clip coverage` | every take has a verdict line; sung coverage reported per window (§4) | after every take lands | retake / cover / give up sync and cut away (`61-lipsync.md`) |
| 5 | **Safety and canon scan** | `slop review scan-sheets` → look → `slop review record` → `slop review status` (§9.0, every tier), or the safety-scan workflow (`templates/workflows/`, Director tier, §9.1) | zero `block`; every `fix` resolved or kept off screen | after all final takes land, before the final render; again on every re-make | fix at the source (image edit, re-make), crop, or reject |
| 6 | **Lyric gate** | `slop render lyrics` (whole song; `--from A --to B` for a range) | prints **N/N** (every sung token drawn at its time) | per chapter while animating; for the whole film before rendering | draw the missing tokens (`KIN.mark` on custom draws); check display tokens |
| 7 | **History check** | `slop render check --pairs A:B,C:D --skip-flash` | **HISTORY-INDEPENDENT** on every pair | per chapter; at every chapter seam | §6 |
| 8 | **Render speed** | the contact sheet prints ms/frame | ≤ 1,500 ms/frame | per chapter | replace the expensive treatment (`70-motion-design.md` §11) |
| 9 | **Reviewer pass** | the review workflow (§8) | **no blocking fix left**, owner ≥ 7, craft/sync/story ≥ 6, the reviewer's lyric-gate line N/N; a null review is a fail | per chapter, after the animator | apply fixes; second round; then the owner decides |
| 10 | **Flash check** | `slop render check --skip-history` (reads `out/master.mp4`; `--video` for another file) | ≤ 3 flashes in every 1 s window | on the master, before delivery | move or shrink the flashes (§5) |
| 11 | **Master tags** | `ffprobe` (§7) | BT.709 matrix/primaries, sRGB transfer, tv range, frame count = duration × 24, audio present | after every encode | re-encode with `slop render encode` |
| 12 | **Spend truth** | `slop spend` (OpenRouter: the ledger plus the real usage, key limit and balance); Higgsfield: the connector's `balance` tool, called by the bot (`slop spend` cannot read it) | real spend read from each provider within the caps | before and after every paid batch | stop spending; reconcile the ledger |
| 13 | **Owner review** | (human, §10) | the owner's verdict logged verbatim | at the checkpoints | log, convert to metrics, fix |

A gate that cannot run (missing tool, missing asset) is a **fail**, never a skip. Write the reason in the run report.

---

## 2. The board audit (`slop board audit`)

Gates on `board/shots.json` (PASS/FAIL each, with the shots to fix; written to `board/audit.json`; exit code 1 while any
fails). Run it before the board is shown to anyone and after every edit:

| Gate | What it checks |
|---|---|
| `tile` | shots tile `[0, duration]` with **no gaps and no overlaps** |
| `cuts` | **every cut within 0.03 s of a beat** in the beat map, or of a declared hit (a word straddling a cut moves the cut by ≤ 0.028 s so the word stays whole) |
| `words_typed` | **every aligned sung word starts inside a shot whose `type[]` lists its line** |
| `graphics` | **one explaining graphic per lyric line** (`devices[]` tagged with the line, or one untagged device on the shot where the line starts, or a code-drawn shot typing it) |
| `lead_share` | lead-on-screen seconds ≥ `project.json` `board.lead_min` (default 0.70); `lead_on_screen` counts only when she is recognisable (face, figure or back view; hand/boot/tag macros are inserts) |
| `motion_budget` | planned sung + motion clip seconds within the budget |
| `clip_windows` | sung windows 4–8 s, motion clips 4–12 s; a sung window starts in a word gap and lists its exact words |
| `plates_unique` | one plate per shot (unless the shots are one continuous moment); no two clips start from the same frame |
| `banned` | no `project.json` `"banned"` word anywhere in the board |
| `treatments` | every 2.5D (`plate3d`) shot names a treatment family and **no two consecutive 2.5D shots share one** |
| `todo` | no TODO marker left; every shot has a framing |

Not automated — check them on the board PDF and in review: the explaining graphic actually explains its line (the
audit only counts it); each chapter uses ≥ 5 distinct 2.5D treatments (the audit warns); transitions are motivated and
never the same device twice in a row.

A storyboard written by agents MUST end with this audit run as code ("CHECK with code … and fix until all pass"), not with
an agent's opinion that it passes.

---

## 3. The lyric gate (`slop render lyrics`)

How it works: for every sung token, render the frame at `t0 + clamp((t1 − t0)/2, 0.03, 0.12)` and check that the token's
`t0` is in the set the frame marked as drawn (`KIN.mark(tk)`, called by every lyric mode). It prints `N/N`; anything less
fails. EV: 417/417 tokens. SP: 315/315 words.

Rules around it:
- No render before the gate is N/N for the whole film ("no render is allowed until every word is on screen").
- The default renderer keeps un-animated shots at N/N; a chapter that replaces the default must draw every token of its
  lines itself.
- A custom-drawn token (a lyric inside a post card, a stamp) must call `KIN.mark(tk)` or the gate cannot see it.
- The gate proves presence and timing, not legibility. Legibility (≥ 40 px, contrast, not hidden behind a matte) is checked
  on contact sheets (§8) — an occluded word still counts as drawn.
- If a token is mis-timed, fix the alignment with `slop lyrics fix` (it edits `analysis/words.json`, marks the word
  `src: manual` and keeps your `--note`), then run `slop edit export`; do not patch times in chapter code (EV did, as a
  stop-gap, with a "no-op once fixed" comment).

---

## 4. AV-sync coverage and clip QA

The lip-sync check is an **audio** check (`61-lipsync.md` has the method): Seedance copies the reference audio into its own
soundtrack and the mouth follows that soundtrack, so where the take's audio stops matching our window, the lips stop
matching the song.

**What `slop clip sync` records per take** (`clips/<clip>.json` → `takes[].sync`): `lag_s` (always map clip time through
it; outliers reached ±0.5–1.0 s), `ncc`, `mode` (`copy` if global NCC > 0.2, else `none`; the raw `slop sync check` report calls that case
`resynth`), in-sync spans in song time,
`diverge_at`, and `cut_at` = the last eighth note before the divergence.

**Coverage** = needed *sung* seconds (word spans ±30 ms; silences need no lips) covered by in-sync spans of the chain
(take + covers). A remaining gap ≥ 0.6 s gets a cover; shorter slips are tolerated ("just sync most lips"). EV verified
~86 % of sung seconds. SP verified 16 windows by audio (2 partly) and checked 7 by eye (whispers at the ear, a mask, a wide).
When covers fail, **give up sync for that span and cut away**; never hold an out-of-sync mouth, and no lip-sync-model
fallbacks by default.

**Clip QA: one line per take** (append to `clips/QA.md`):

```
- **W07** · take 2 · **keep** · Higgsfield 35 cr, 5 s from song 42.90 (vocal 44.60-46.40 in place, the rest silence). She glides
  in level from frame left by ~1.5 s and whispers at his cheek/ear in profile; lip sync verified song 44.94-46.40 (lag +725 ms,
  NCC 0.49, strong diagonal) = all of 'You don't have to die.' … Notes: her lips touch his cheek rather than the ear (reads
  close to a kiss); … she is opaque (transparency in the comp).
```

How to QA a take: extract 5 frames across it plus a face crop and look at them next to the start image. Check on-model
(the canon list), no warped or painterly faces, no extra limbs, no text or watermarks, the right performance (only the
singer voices; nobody else's mouth forms words), the avsync diagnostic image for sung takes; for motion takes, that the
motion does what the shot needs, is smooth and keeps the composition. Verdict: `keep | retake | reject`; at most one
retake per clip unless it carries a key lyric moment.

**QA against the story, not against the prompt.** SP's first-round takes all passed QA because QA checked each take
against its prompt, and the prompts asked for very little ("she stands still and whispers"). The user saw "missing context
and the vibe" at once. Ask: does the take play the story beat the storyboard describes?

---

## 5. The flash check (`slop render check`)

After WCAG 2.3.1's general flash threshold. Reads the video at 96×54, 24 fps, in linear relative luminance.

- A **flash** = a *pair* of opposing changes in relative luminance of ≥ 10 % of the range, where the darker state is < 0.8,
  over ≥ ¼ of the frame (defaults `--max 3 --area .25 --delta .10`).
- **Fail:** any 1 s window with more than 3 flashes. The tool prints the count, the worst window and every failing second.
- Count pairs, not transitions: an early version counted each transition, so one strobe counted twice and quarter-note
  flashes at 2.2/s read as 4.4/s.
- Fixes: move flashes onto every other hit; shrink flicker to a panel under ¼ of the frame; lower its contrast.

SP's master passed with a worst second of 3.

---

## 6. The history check (`slop render check --pairs`)

Frames render in parallel and out of order, so each frame must be a pure function of `t`. The check renders frame B fresh
and frame B right after frame A in the same page, and fails if any pixel differs by more than 40 levels. Run 3 pairs per
chapter (one pair across each seam); always include a pair where A is a heavy 2.5D or glass frame.

Typical causes and fixes:
- state kept between frames (a variable outside the scene, a counter) → compute from `t`;
- a memo keyed by frame, or one that depends on which frame came first → key by media name; build deterministically;
- a GPU-backed 2D canvas (the overlay of the previous frame "sticks") → make every canvas software-backed;
- drawing a WebGL canvas into a 2D canvas switches it to GPU rasterisation for the page's life → read 2.5D pixels back
  through the CPU (`PLATE3D.readback`);
- leaked context state (letterSpacing, textAlign, filter, shadow) → reset at the start of every scene and in every scratch
  canvas.

Tolerated: first-use caches that change renders by ≤ 0.3/255 (EV) — below the 40-level threshold.

---

## 7. Master and deliverable tags (`ffprobe`)

Expected on the master (`out/master.mp4`, from `slop render encode`):

```
ffprobe -v error -select_streams v:0 -show_entries \
  stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_frames,color_space,color_primaries,color_transfer,color_range \
  -of json out/master.mp4
```

| Field | Expected |
|---|---|
| codec, profile | h264 (High) |
| width × height | 1920 × 1080 (vertical: 1080 × 1920) |
| r_frame_rate | 24/1 |
| nb_frames | = duration × 24 (± 1) |
| pix_fmt | yuv420p |
| color_space / color_primaries | bt709 / bt709 |
| color_transfer | iec61966-2-1 (sRGB) |
| color_range | tv |
| audio | aac, 2 channels, duration = the song's |

Why: an untagged or BT.601 stream looks lighter and washed out in QuickTime ("stuff is v blown out"). EV's published master
predated the fix and is tagged BT.601 with no primaries or transfer. Settings and loudness: `90-master-publish.md`.

---

## 8. Contact sheets and the reviewer

### 8.1 Contact-sheet review procedure

Contact sheets are how agents (and you) **look**. Rendered frames, not code, are reviewed.

| Sheet | Times | Size | Who |
|---|---|---|---|
| **Per chapter (animator)** | every shot's first, middle and last frame; every lyric line's first and last word; every hit; each graphic's entrance; each transition's middle | `--cols 4 --w 480` | the animator, every iteration |
| **Per chapter (reviewer)** | **at least 24** of the above (EV used ≥ 28), plus full-size stills of the 5 most important moments (`slop render stills --times …`) | `--cols 4 --w 480` | the reviewer |
| **Sync** | the chapter at 12 fps: `slop render frames --from A --to B --every 2 --out <scratch>` (every 2nd frame of 24 fps), or those times sampled on a sheet | small | list the 10 biggest moves and the nearest hit for each |
| **Whole film** | mid-shot frames of every shot (`slop render sheet` with no `--times` samples every shot's mid-point), 6 × 24 per sheet; every chapter seam; 100 % crops of faces | `--cols 6 --w 320` | the orchestrator, before the final render |
| **Owner review** | one sheet per decision (§10) | big enough to judge faces | the user |

Command: `slop render sheet --times t1,t2,… --cols 4 --w 480 --out <file>`. The sheet prints ms/frame per still. Open every sheet with your image-reading tool and **look**; a sheet nobody opened
is not a review. Name sheets by chapter and round (`ch03-r1-2.jpg`) in the project's scratch folder.

**What to look for** (the reviewer's checklist, from both videos):
1. **The explaining graphic** — does it show what the words mean, in one glance, in the style languages?
2. **Lyric timing and legibility** — on the word, never early; ≥ 40 px; the lyric the biggest type unless a device is the
   line; nothing clipped by chrome or the frame edge; occlusion tucks an edge and never loses a glyph.
3. **Beat sync** — cuts on beats/hits; moves answer sounds; stillness where the song breathes; snaps not early (a snap 70
   ms before its kick "reads slightly early").
4. **Density** — ≥ 3 ordered layers / within the element budget; accent on ≤ 2 elements; ≤ 3 micro rows.
5. **2.5D** — layered, alive, different from its neighbours; never a still with a slow zoom.
6. **Transitions** — motivated, landing on the beat, never repeated back to back, never amateurish.
7. **Colour** — the footage saturated and in the chosen look; never greyed; no washes over footage in clean/native looks.
8. **Faces and canon** — type never over her face; the lead on-model; the cast distinct; no out-of-sync singing mouth held.
9. **Information consistency** — two numbers on screen that should agree, agree ("the counter reads x380 while the
   dashboard reads '135 RUNNING'. It reads as sloppy information design").
10. **Performance** — ms/frame ≤ 1,500.

### 8.2 The reviewer score (the toolkit's schema, copied from `templates/workflows/chapters.js`)

```js
const REVIEW = { type: 'object', properties: {
  owner: { type: 'number', description: `${OWNER}'s taste and the bar, 0-10 (counts double): clean, beautiful motion design that explains the words, never cheap or busy, the footage's action reads` },
  craft: { type: 'number', description: 'type setting, ink over footage, depth/occlusion, devices, transitions, 0-10' },
  sync: { type: 'number', description: 'cuts and camera answer the beats and hits; every word on its time; no out-of-sync mouth on screen, 0-10' },
  story: { type: 'number', description: 'every lyric on screen and legible on a phone; each line explained by its graphic; canon and owner notes kept, 0-10' },
  pass: { type: 'boolean', description: 'your own opinion; the script decides the verdict from the fixes and scores' },
  fixes: { type: 'array', items: { type: 'object', properties: {
    shot: { type: 'string' }, time: { type: 'number' }, severity: { type: 'string', enum: ['blocking', 'polish'] }, problem: { type: 'string' }, fix: { type: 'string' } },
    required: ['shot', 'severity', 'problem', 'fix'] } },
  checks: { type: 'object', properties: {
    lyric_gate: { type: 'string', description: 'the exact line the lyric gate printed, e.g. "132/132 tokens on screen at their time"' },
    wired: { type: 'string', description: 'the exact line the wiring check printed: "WIRED …" or "NOT WIRED …"' },
    sheets: { type: 'number', description: 'how many frames you looked at on contact sheets and stills' },
    ms_per_frame: { type: 'number' }, flash_max_per_s: { type: 'number' } }, required: ['lyric_gate', 'wired', 'sheets'] } },
  required: ['owner', 'craft', 'sync', 'story', 'pass', 'fixes', 'checks'] }
```

The four lenses are the reference videos' **director / craft / sync / story**; the toolkit calls the first one `owner`
(the owner's taste, counted double) because it must mean *this* user's taste.

**Severity.** Every fix is `blocking` or `polish`. **Blocking** = it would stop the chapter shipping: the chapter not
wired (the wiring check, `node runner/deleg.mjs wire <project> --check`, prints NOT WIRED: the default renderer draws its
shots instead); a lyric-gate miss or a word off its time; type over a face; the main lyric unreadable on a phone (< 40 px or no contrast); an out-of-sync mouth
held on screen; black, frozen, torn or broken frames; an off-model lead; banned content or words; more than 3 flashes in a
second; the same treatment or transition device back to back; a line with no explaining graphic; a render error.
**Polish** = everything that would make it better but would not stop it shipping. An unmarked fix counts as blocking.

**The verdict is computed by the script, not taken from the reviewer:**
- **Valid review** = all four scores are numbers 0–10, `fixes` is a list, `checks.lyric_gate` is the gate's printed line,
  `checks.wired` is the wiring check's printed line and `checks.sheets > 0` (the reviewer really looked at renders). Anything else is a **failed review** (retried once), never a
  pass (§8.4). `slop render lyrics` prints its line as `N/M tokens on screen at their time (S s)`, e.g.
  `132/132 tokens on screen at their time (41.2s)`; the gate counts as N/N when the two numbers are equal and non-zero.
- **pass = no blocking fix left AND owner ≥ 7 AND craft, sync, story ≥ 6 AND the lyric gate line reads N/N AND the
  wiring line starts with WIRED.**
- score = (2·owner + craft + sync + story) / 5, for ranking only.

Other rules:
- **At most 12 fixes, most important first**, each concrete: shot, time, problem, the exact change ("move the column right
  (x 196→250) so the right ends of WOULD and DECEIVE run 40–80 px under her hair strands"). Vague fixes ("make it pop")
  are rejected.
- **The reviewer never edits files.** It renders and looks itself ("your opinion of code you have not seen rendered is
  worthless"); it does not trust the animator's notes.
- Put the user's verbatim brief and storyboard notes in the reviewer's prompt, so `owner` means *this* user's taste.
- Real examples: `examples/review-pass.json` and `examples/review-fail.json` (the originals, in the reference videos'
  schema) and `examples/review-toolkit-form.json` (the failing one rewritten in this schema), explained in
  `examples/review.md`.

### 8.3 Why the bar is "no blocking fix left" (calibrated to the owner)

The original rule was `director ≥ 8 and craft, sync, story ≥ 7` (the first score named after the owner, double weight).
The reviewers were stricter than the user: across both chapter rounds of SP the first-round director scores ran 6–7.5,
only one chapter in nine ever reached 8/8/8/8, the rest shipped at 7–7.5 after up to two fix rounds — and the user's
verdict on that cut was "its perfect. change nothing." So:

- The numbers are a **ratchet for fixes**, not the ship condition. The ship condition is **"no blocking fix left"** plus
  the lower floors above. `args.pass_rule` can override the floors per project, but write the reason in `DECISIONS.md`.
  An owner who wants the reference videos' original bar back passes `pass_rule: {min_owner: 8, min_other: 7}` (the
  "no blocking fix" rule still applies on top).
- Run at most **two** review → fix rounds per chapter, then carry the open polish fixes into the next pass (a refit or
  touch-up) instead of looping.
- **Calibrate on the owner's verdicts.** After each owner review, store `{chapter, reviewer scores, owner verdict}` in
  `taste/` and, when they disagree, adjust the reviewer prompt's description of `owner` with the owner's words. (The same
  pattern calibrated SP's lyric-flow metric: it was fitted until it ranked sections in the user's order.)

### 8.4 A null review is a failure (MUST, in code)

```js
const validReview = r => !!(r && ['owner', 'craft', 'sync', 'story'].every(k => typeof r[k] === 'number' && r[k] >= 0 && r[k] <= 10)
  && Array.isArray(r.fixes) && r.checks && typeof r.checks.lyric_gate === 'string' && r.checks.lyric_gate.trim() && Number(r.checks.sheets) > 0)
// not valid → { pass: false, reason: 'no valid review (nothing returned, malformed, or no renders looked at): counted as a FAILED review, never a pass' }
```

The original scripts had `(!rev || !rev.fixes || !rev.fixes.length) ? 'no fixes' : …` — so a review that never ran
became "no fixes" and the run reported completed. After any run, also scan the run record's `logs[]` and per-agent states
for errors (a completed run can hide agents that died on a usage limit; the delegation runner flags them in `runs/`) and
carry every open item forward explicitly.

### 8.5 The fixer

"Apply every fix (the user's brief wins any conflict). Rebuild the edit first (clips may have landed). Re-verify: lyric gate
N/N, sheets and full-size stills of what changed (look at them), the sync check on changed moves, the history check on 3
pairs. Return what changed and the checks." Fixes on shared files are reported to the orchestrator, not made.

---

## 9. Safety and canon scan (before any public render)

Every take the edit uses was generated. Before the final render, scan all of them; re-scan every re-make. On SP the first
scan of 96 takes took 6 agents 8 minutes and found **12 blocks and 44 fixes** (modern objects in ancient scenes, nudity
showing through a thin corset, crew who looked like copies of the male lead, the lead off-canon, generation glitches); the
lead's own pass added a nude glowing figure, a shape that read as a religious symbol, a gown cutout and an uncapped needle.
The scan paid for itself.

### 9.0 The scan with the toolkit's commands (every tier)

One command per step, after `slop edit edl` and before the final render:

1. `slop --project my-song review scan-sheets` (a long step: run it as a job, `job start -- review scan-sheets`) makes
   one 3 × 2 sheet per generated take the edit plays (frames at 8 / 25 / 42 / 58 / 75 / 92 % of the take, 640 px wide,
   labelled with the time) in `render/scan/`, the take list `render/scan-list.json`, and the findings template
   `render/scan/findings-template.json`. `--plates` also sheets the picked plates the edit shows; a re-run only makes
   the sheets of new or changed takes (`--force`: all of them).
2. Copy the template; never edit or record the template itself:
   `cp render/scan/findings-template.json render/scan/findings.json` (the command prints the copy line with absolute
   paths).
3. Open every sheet. In `findings.json` add each take you looked at to `"checked"` (the template lists them under
   `"to_check"` and starts with `"checked": []`), and each problem to `"findings"`: `{clip, time, severity: block | fix
   | note, kind, what}` (§9.2 rubric).
4. `slop --project my-song review record render/scan/findings.json` checks it against the scan schema and merges it into
   `render/scan/scan.json`. It refuses the template, an unchanged copy and an empty `"checked"` list. A re-scan of a
   re-made take replaces that take's findings.
5. `slop --project my-song review status` prints the takes checked, the open blocks and fixes, and the verdict. It is
   judged against the takes the edit plays NOW: a take not yet checked, a take re-made after it was checked, or a changed
   edit gives NOT CLEAN with the next step (usually `review scan-sheets` again). Findings on takes the edit no longer
   plays are kept but marked stale and never count as open.

`slop status` shows this as the `scan` stage before gate v1 and the master, with the one command to run next.

### 9.1 Method (the safety-scan workflow, Director tier)

`slop review scan-sheets` writes the take list for you. By hand it is:

1. Write the list of final takes to a **file**, `render/scan-list.json` (the safety-scan brief's default):
   `[{clip, file, shots, song_t0, dur}]`, with `file` relative to the project folder. Never pass long lists inline in
   workflow arguments (a placeholder once launched instead of the list). Build it from the edit (only takes the EDL
   plays), in the project folder, after `slop edit edl`:

   ```
   python3 - <<'PY'
   import json, os
   edl = json.load(open("edit/edl.json"))
   used = {}                                    # engine clip name "<clip>-t<k>" -> the shots that play it
   for shot, e in sorted(edl.items()):
       for g in e.get("segs", []):
           used.setdefault(g["clip"], []).append(shot)
   out = []
   for name, shots in sorted(used.items()):
       clip, k = name.rsplit("-t", 1)
       rec = json.load(open(f"clips/{clip}.json"))
       take = rec["takes"][int(k) - 1]
       out.append({"clip": name, "file": take["file"], "shots": sorted(set(shots)),
                   "song_t0": rec.get("song_t0"), "dur": (rec.get("body") or {}).get("duration")})
   os.makedirs("render", exist_ok=True)
   json.dump(out, open("render/scan-list.json", "w"), indent=1)
   print(len(out), "takes -> render/scan-list.json")
   PY
   ```

   Pass the printed count as the scan's `total`.
2. Split it into N slices (6 agents for ~100 takes); each agent reads its slice from the file.
3. For each clip: get the duration with `ffprobe`, extract **6 frames at 8 %, 25 %, 42 %, 58 %, 75 % and 92 %** of the
   duration at 640 px wide, tile them **3 × 2** into one sheet labelled with the times, and look at every sheet.
4. Report findings with the schema below. Do not edit files. **Do not report the grade or colour.**

### 9.2 Severity rubric (fill the bracketed parts per project)

- **block** (must not ship): any nudity or visible genitals/nipples (even glowing, translucent or statue-like figures);
  sexual content; gore; a minor; text, logos or watermarks readable in frame; a real, recognisable person; [an object
  that breaks the world: e.g. a modern object in an ancient scene — steel ships, cars, planes, modern clothing on the
  crew].
- **fix**: [the cast canon: e.g. "the crew look like copies of the lead man"; "the man wears earplugs"]; **the lead
  off-canon** [paste the canon text: hair, the ONE accent detail, the clip, the mic, the outfit's must-haves; e.g. "a
  cleavage cutout or bare chest is off-canon"]; obvious generation glitches (melting or doubled faces, extra limbs or
  fingers, a face morphing into another person, objects warping); [figures that read badly: e.g. hooded/veiled/robed
  figures in white].
- **note**: small things worth knowing (soft focus, a brief oddity).

**Whitelist intended anachronisms and props by name** in the scan prompt: "These are deliberate and are NOT findings:
[a small white satellite dish bolted to the mast; the phone in his hand on the ship]." SP's scan flagged its own intended
satellite-dish joke as a block because the generic "modern object" rule caught it.

Give the agents a one-line context: "a lyric video about [premise]; the woman is [role]; the man is [role]; settings:
[list]."

### 9.3 The workflow's arguments and schema (copied from `templates/workflows/safety-scan.js`)

Arguments (a JSON object; the delegation runner fills `project_dir`, `out_dir`, `toolkit_dir`, `job_dir` and `slop`):

| Arg | Required | What |
|---|---|---|
| `list` | yes | the take list file (absolute, or relative to `project_dir`), e.g. `render/scan-list.json` |
| `total` | yes | how many takes the list holds (the script cannot read files; each agent checks it) |
| `out_dir` | yes | the job's outbox |
| `project_dir` | no | the project folder (relative `file` entries resolve against it) |
| `slices` | no | number of agents (default 6, max 16) |
| `scratch_dir` | no | default `<project_dir>/render/scratch/scan` |
| `world` | no | one paragraph: who is who, the places and the era (default: read `project.json` / `DECISIONS.md`) |
| `canon` | no | the lead's canon text (default: `project.json` `lead.canon`) |
| `fix_rules` | no | a list of extra `fix` findings for this video (cast look-alikes, props that must not appear) |
| `block_rules` | no | a list of extra `block` findings (e.g. a modern object in a period scene); put the anachronism whitelist in `world` |

Each agent returns:

```js
const SCHEMA = { type: 'object', properties: {
  findings: { type: 'array', items: { type: 'object', properties: { clip: { type: 'string' }, time: { type: 'number' }, severity: { type: 'string', enum: ['block', 'fix', 'note'] }, kind: { type: 'string' }, what: { type: 'string' } }, required: ['clip', 'severity', 'kind', 'what'] } },
  checked: { type: 'array', items: { type: 'string' } }, given: { type: 'number', description: 'how many takes your slice contained' } },
  required: ['findings', 'checked', 'given'] }
```

The script checks `checked` against each slice: a slice that returns nothing, or checks fewer takes than it was given,
makes the run fail (`ok: false` with an `unchecked` list) — resume the run; never count an unscanned take as clean.

### 9.4 Triage

| Finding | Fix (in order of preference) |
|---|---|
| block in the plate itself | fix the plate with the image-edit model (`51-plates-api.md`), re-make the clip from it, re-scan |
| block that appears only in the take | re-make the clip with a tightened prompt (name the canon explicitly, add the negative), re-scan; or crop/retime it off screen in the edit; or reject the take |
| fix: off-canon / glitch | crop or retime around it (time-map the take to skip the frames) if it is brief; else re-make |
| fix in a re-make that came back | crop in the touch-up pass |
| note | log it; act only if it is on a key moment |

Never paint over a canon break by hand in code ("it should have been in the midjourney prompt from the start or with the
edit model"). Never alter an image to get it past a provider's filter (`62-moderation.md`).

---

## 10. The owner review ritual

The owner's time is the scarcest resource and their eye is the final metric. Reviews are **fast, by eye, one line per
item**, at fixed checkpoints, and everything between is autonomous.

### 10.1 Checkpoints (and only these)

| Checkpoint | What you show | What you ask |
|---|---|---|
| Concept | 2–3 one-paragraph concepts | pick one |
| Lead face | **4 test plates** of the lead | approve the face before any batch; the owner flags wrong faces by name |
| Song | the Suno takes in the player | pick by ear |
| Storyboard | the board PDF (one card per shot: frame, time, lyric, framing, action, motion source, explaining graphic), suspect faces badged | approve with notes; silence after the stated wait = approval |
| Prompt book | every paid video prompt, as one document | "go" before any spend |
| v1 | the review copy | the verdict |

**Approval by timeout:** "just wait like 5 mins once you send it and if I don't respond take it as approval". State the
wait in the message (5 minutes; the owner once asked for 15). **Ping between checkpoints only for** a paid-service failure,
a handoff the bot cannot do (captcha, 2FA, a download), or a decision that is the owner's.

### 10.2 How to present

- One message, one decision. A numbered contact sheet or PDF with ids the owner can type back ("s058 has a backwards head";
  "wrong: arena, flap-wide, … others are good").
- Labelled variants when there is a choice (H1–H4, s1–s4); "h4 best do that" is a complete answer.
- Show the short proof before committing to a method ("Wait show me the short clip w audio before wasting time on the
  latent sync").
- Low-resolution previews with the real context around them for fast iteration, then scale up.
- Always show graded frames (the project look), never raw ones.

### 10.3 Logging (MUST)

- Paste every owner message verbatim (typos kept) into `DECISIONS.md` (`slop decide "…"` appends a dated entry; owner
  gates such as board/prompts/v1 approval are set with `slop gate`) with the date and what it changed. A later decision
  is an "UPDATE … supersedes" block, not an edit of the old one; write it into the shared files **before** briefing
  workers, so running agents that re-read the files pick it up.
- **Every human observation becomes a metric or a required field the same day.** "she gets turned asian" → the pinned
  ethnicity descriptor + a face-approval gate. "same image for like 6 diff storyboard shots" → the one-plate-per-shot
  audit. "way too gray" → a colourfulness check on takes. "two seedance videos shouldnt start from the exact same frame"
  → the distinct-start audit.
- One line per take in the QA log, one line per shot in the storyboard review log (pick / reject / comment).
- When the owner flags quality mid-run: **stop every workflow that can spend first** (search each running script for its
  generate calls), then log, then fix (`95-delegation.md` §8).

---

## 11. Final QA order before render and delivery

1. All takes landed; QA lines written; coverage report done.
2. Safety and canon scan clean (`slop review status` says CLEAN; re-scans of re-makes clean); fixes applied at the
   source.
3. Edit rebuilt (`slop edit edl`, `slop edit export`).
4. Touch-up pass on chapters whose footage changed (no generation; re-key, crop canon breaks; lyric gate N/N per chapter).
5. Lyric gate N/N for 0:END.
6. History check on the seams; whole-film contact sheets looked at.
7. Render frames; encode master + review copy (`90-master-publish.md`).
8. ffprobe tags; flash check on the master.
9. Owner review of v1; log the verdict.
10. Spend reconciled from the provider; the run report updated (one file, rewritten in place).
