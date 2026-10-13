# 50 · Plates with Midjourney

A **plate** is the still image a shot starts from: it is shown as a 2.5D still, or it becomes the first frame or the
reference image of a video clip. On *Escape Velocity* (EV) and *Clodyssey (Superpersuasion)* (SP), every plate came from
Midjourney (MJ) v8.2 with the personal profile of anabology (who directed both videos), and that is the look people
noticed. This file is the playbook for that stage: setup, the prompt grammar, the lead's identity, batches, pasting,
ingest, picks and fixes.

Read first: `40-storyboard.md` (where plate keys, framings and type placements come from). Next: `51-plates-api.md`
(API images and image edits), `60-clips.md` (what the plates turn into).

**Tiers.** Studio and Director tiers use Midjourney. Quick tier uses API images instead (`51-plates-api.md`). Every
tier uses the image-edit model for fixes (§12).

**Files this stage reads and writes** (the project contract, ARCHITECTURE §3.2):

| File | What |
|---|---|
| `board/shots.json` | input: each shot's `plate` key, `framing`, `lead_on_screen`, `type[].placement`, `mj_prompt` |
| `project.json` → `lead.canon`, `lead.far`, `lead.possessive` | the pinned identity text (§5) |
| `project.json` → `mj.params`, `mj.profile` | `--ar 16:9 --v 8.2 --raw --hd` and the owner's own profile code |
| `plates/prompts.md` | the prompt book: every batch, every prompt, in the order it is pasted |
| `plates/cands/<plate>/<k>.jpg` | the 4 candidates of a job, `k` = 1..4 (grid position) |
| `plates/picks.json` | `{plate: {file, cand_k, shot_ids[]}}` — the chosen candidate per plate |

---

## 1. The rules (read these even if you read nothing else)

1. **One concrete storyboard shot per prompt.** A plate prompt describes one picture that one shot needs.
2. **The clause order is fixed** (§4): framing/vantage → lead canon (visible garments only) → placement → pose →
   set/props with the concept as an object → declared empty field for type → chapter style tail →
   `no text, no letters, no logos`.
3. **Framing first, always.** Midjourney obeys the first words most. A prompt that starts with the set gives you the set.
4. **The lead's identity is text, pasted verbatim** from `project.json` `lead.canon`, including ethnicity, age and skin.
   Without the ethnicity and skin words, EV's lead drifted ("Midjourney turns her Asian"; 12 plates had to be re-rolled).
   By default the lead is Claudia: her identity text from the canon on claudia.gallery (`claudia_canon`), photographic,
   an adult in her late twenties, never the word "young".
5. **Full-length and wide shots use the short `lead.far` text**, not the full canon. The face details pull MJ into a
   close-up "however the framing is worded".
6. **No face image references for the lead.** They import sheet layouts or give "a close-up-sized head on a distant
   figure". `--oref` does not exist in V8.x (it was replaced by the Edit Model). Image references only where the owner
   explicitly asks (§5.6).
7. **Parameters on every line:** `--ar 16:9 --v 8.2 --raw --hd --p <YOUR_PROFILE_CODE>`. **Never a bare `--p`.** The
   profile code is the owner's alone: it is never published (posts, making-ofs, shared prompt books).
8. **No style references (srefs) by default.** The profile carries the look.
9. **All type is drawn by the engine.** Every prompt ends `no text, no letters, no logos`; signs, tags and screens are
   "blank".
10. **Generation inputs stay in colour.** Never ask MJ for "dithered", "xerox", "halftone" plates to fake a print look;
    MJ doesn't give real 1-bit and the grade happens in post (`70-motion-design.md`).
11. **Test before you batch.** 4 test plates of the lead, approved by the owner (gate **G3**, `00-overview.md` §4),
    before any production batch.
12. **One image per shot.** The 3 unpicked candidates of every job are a free variety pool (§11).
13. **Fix the source, never the frame.** A wrong detail is fixed in the MJ prompt (re-roll) or with the image-edit model
    (§12), never painted by hand or in engine code.
14. **Midjourney is human-in-the-loop by default.** The bot writes paste-ready sheets; the owner pastes, picks,
    downloads and uploads. Browser assist is opt-in only, with a written ToS warning, and the owner signs in themselves (§9).
15. **The project's banned-words list applies to prompts too** (BRIEF / `project.json`). `slop board audit` checks it
    on the board's prompts; read every prompt against the lint checklist (§7.3) before the owner sees the book.

**Commands** (board module; the global flags go first, `slop --json --project NAME plates …`): `slop plates book` (the prompt book and the
paste blocks, §7) · `slop plates ingest` (downloads → candidates, §10.3) · `slop plates sheet` (picking sheets, §10.5) ·
`slop plates pick` (§10.6) · `slop plates vary` (one image per shot, §11) · `slop plates status` (per plate: prompt,
candidates, pick, shots) · `slop gen edit` (fixes, §12) · `slop gate prompts --approve` (G5, when a batch spends).

---

## 2. One-time setup (per owner)

### 2.1 Plan

| | Basic | Standard | Pro | Mega |
|---|---|---|---|---|
| Price (monthly / annual per month) | $10 / $8 | $30 / $24 | $60 / $48 | $120 / $96 |
| Fast GPU time | 3.3 h (200 min) | 15 h | 30 h | 60 h |
| Relax mode (unlimited images) | no | yes | yes | yes |
| **Max jobs in one permutation paste** | 4 | **10** | **40** | **40** |
| Stealth (images not public) | no | no | **yes** | **yes** |
| Queued jobs at once | 10 | 10 | 10 (more for permutations) | same |

- An HD image job costs **1.3 Fast GPU-minutes** (SD is 0.8). One EV-scale project (≈160 jobs) is ≈ 210 Fast-minutes
  (3.5 h). Basic cannot cover one project; Standard covers about four.
- Permutations need Fast (or Turbo) mode; Relax mode accepts single lines only.
- Recommend **Standard** for a one-shot video (8–15 plates, permutations of 10) and **Pro** for an EV/SP-scale project
  (Stealth for unreleased work; a 40-job batch is one paste).
- MJ images are **public by default** unless Stealth (Pro/Mega). Warn owners with unreleased work.
- A company with more than US$1M yearly revenue must be on Pro or Mega to own its images. Ask at setup.
- One person per MJ account (MJ terms). Every owner brings their own account and their own profile.

### 2.2 The personalization profile (the look)

anabology's plates were made with their own **V8 personal profile**. The owner makes theirs; never ship or reuse
anyone else's code.

1. On midjourney.com open **Personalize**. Click **Global V7 Profile** and pick images from the grid until the progress
   bar fills and the profile **unlocks**. (V8 has no global profile; the Global V7 profile must be unlocked first.)
2. In **Settings**, set the default version to **8.2**. New profiles are built for the default version.
3. Back in Personalize, click **New Profile** and keep picking images. More picks = a profile that knows the owner's
   taste better. Aim for several hundred.
4. Click the profile's **use** icon. It copies `--p <profile ID>`.
5. Submit one test prompt with that ID. MJ converts the ID into a **code** (`--p <code>`), visible on the job.
   An ID always means "the latest version of the profile"; a **code pins one version**, so the look stays stable for the
   whole project.
6. Record the code in `project.json` → `mj.profile`. Every pasted line carries `--p <that code>`.
7. In the Imagine bar settings: turn the **Personalization toggle OFF** (it would add the default profiles to every
   prompt; whether it stacks with an explicit code is untested, so off is the safe setting). Version 8.2, Raw on, HD on.

**Why "never a bare `--p`":** `--p` with no code applies the *default* profiles, which for anabology was the Global
V7 profile. A whole batch came back in the wrong look and was rejected ("these aren't the right profile, I need v8.2
personalized"). `--p` and `--profile` are the same parameter; both need the code.

If the owner has no profile yet, the bot can still write the batches; plates made without a profile look generic. Say so
once, and offer to wait.

---

## 3. Parameters

Default (`project.json` → `mj.params` + `mj.profile`):

```
--ar 16:9 --v 8.2 --raw --hd --p <YOUR_PROFILE_CODE>
```

| Parameter | Use | Notes |
|---|---|---|
| `--ar 16:9` | every plate | `--hd` 16:9 output is **2944×1648**. A 16:9 job that comes back **1456×816 ran in SD** (HD off). |
| `--v 8.2` | every plate | V8.2 is the default since 2026-07-24; V8.0 is retired. |
| `--raw` | every plate | turns off MJ's default styling so the profile and the prompt carry the look; no surcharge |
| `--hd` | every plate | native 2K; 1.3 GPU-min per job (not 4×) |
| `--p <code>` | every plate | the pinned profile code; never bare |
| `--ar 4:5` | rare fashion close-ups / detail inserts | 1968×2464 with HD |
| `--niji` | only for an anime-style insert | niji jobs carry **no personal profile**; output 1456×816 |
| `--iw <0–3>` | only with an allowed image reference (§5.6) | default 1 |
| `--s` | not used | stylize stays at its default 100 (it also sets personalization strength) |
| `--oref` | **never** | not supported in V8.x ("Version 8.2 doesn't support --oref"); MJ's V8 consistency tool is the Edit Model (`--edit`) |
| `--sref` | not by default | anabology's kept work used none |

Keep each prompt under about **800 characters** (before parameters). Longer prompts can be silently rewritten by MJ's
prompt shortener (a "Long Prompt" badge), and then the job no longer matches its text at ingest (§10.4).

---

## 4. The prompt grammar (fixed clause order)

Write every plate prompt as one long sentence of comma-separated clauses, **in this order**. Each slot below has its
rule, a phrase bank and the most common mistake.

### Slot 1 — Framing and vantage

The camera first. Use the storyboard `framing` and say it in words MJ knows:

| `framing` | Opening words |
|---|---|
| ECU | `extreme close-up of` · `extreme macro close-up of` |
| CU | `close-up of` · `close-up portrait of` · `long-lens close-up of` |
| MCU | `medium close-up of` |
| MS | `medium shot of` · `low-angle medium shot of` · `lateral medium shot along …` |
| MWS | `medium wide shot of` |
| FS | `full-length shot of` · `full-body fashion editorial photograph taken from far away with a long lens:` |
| WS | `wide shot of` |
| EWS | `extreme wide shot from a high overpass of` · `extreme wide shot of <place>, and alone in the middle …` |
| special | `straight-down aerial of` · `over-the-shoulder shot from behind` · `side view` · `macro product photograph of` |

Mistake: putting the set first ("a vast data hall …, a woman …"). The lead becomes a speck or the framing is
ignored.

### Slot 2 — The lead canon text (visible garments only)

Paste `lead.canon` (or `lead.far` for FS/WS/EWS, §5.3) **verbatim**. Then add only the garments that are **visible in
this framing**: a close-up gets hair, face, clip, mic and collar; it does not get boots. EV's own prompt books show the
mistake: close-ups that list "black knee-high boots".

- A body-part insert (her hand on a strap, her boots on a step) uses `lead.possessive` + the body part:
  `a Caucasian American woman's hand pulling a black utility harness strap tight …`. Never append the full canon
  to a body part (see the substitution bug in §5.5).
- An insert with no lead (a set, a prop) has no canon at all.
- Other recurring characters get their own canon block, written the same way (§5.7).

### Slot 3 — Placement in frame

Where she stands, so the type field (slot 6) stays clear: `in the left half of the frame`, `in the right third`,
`her face in the centre of the frame`, `standing small in the middle lane in the lower centre`. For far shots add a size
cue: `her whole figure about one third of the frame height`, `about one tenth of the frame height`,
`head to toe in frame with empty fog above her head and floor below her boots`.

### Slot 4 — Pose and action

Editorial, upright, deadpan, concrete. One verb you could photograph.

- Good: `walking toward the camera`, `holding one black knee boot up at chest height`,
  `singing with her eyes closed and her mouth wide open`, `turning her face to the lens`,
  `floating horizontally in mid-air like a diver gliding, chest toward the floor`.
- Singing plates (future lip-sync references) show the face to the lens, eyes closed or open, mouth open.
- **Sung plates: the mouth fully visible, nothing in front of it.** A sung shot's plate (motion tier `sung`, or a
  motion shot on a sung clip) is the start frame its clip lip-syncs from. No microphone (not a held one, not a stand;
  a canon headset stays at her cheek), no hand or fingers at the lips, no hair across them. In the Studio run a mic at
  her mouth on one sung plate held that clip to 26 % in sync, and image models add a microphone to "singing" on their
  own. So `slop plates book` adds `her mouth fully visible, nothing in front of her mouth` to every sung plate's prompt
  by itself (`his`/`their` from `lead.pronoun`; before the style tail). Midjourney prompts get only that: MJ draws
  what a prompt names, "no microphone" included (its own docs: it does not understand "no"). API jobs also get
  `(no microphone, hand or hair)` (`51-plates-api.md` §4), or, when the canon carries a headset,
  `(the headset microphone at her cheek, clear of her lips; no hand or hair)`, so the canon prop is never dropped.
  `slop board audit` warns when a sung shot's prompt, action or the lead canon puts a microphone or a hand there. Do
  not write "singing into a microphone"; write what her mouth does.
- Avoid seated or reclining frontal poses in short skirts (downstream image and video providers refused them), avoid
  "sheer", "bare shoulders", "bare feet" on the lead (SP's sheer gown came back as nude-reading "plastic wrap" with
  reclining poses; the canon was changed to a structured high-neck gown, "composed and deadpan").
- Never "smiling for the camera"; the house expression is deadpan and curious.

### Slot 5 — Set and props, with the concept as an object

The lyric's idea becomes a physical thing in the frame ("the meme as an object"): a pile of sneakers outside a startup
door, thirteen small silver desktop computers on a wire shelf, a broadcast microphone on a boom arm in a black void.

- **Name the exact form factor.** "a white robotaxi" came back as an old sedan; "a small white compact electric SUV
  robotaxi with a tall spinning lidar dome" worked.
- **Make the important thing the subject of the clause.** "a flank covered in eyes" gave a bare flank; "the hide studded
  with dozens of large glossy human eyes of different sizes … each eye reflecting a tiny pale figure" gave eyes.
- **Props are blank:** `a blank billboard`, `a blank white garment tag`, `the paper inside blank`,
  `a blank yellow enamel sign`, `the screen plain glowing white`. The engine draws the words later.
- **Say what is not there** when MJ adds things: `none of them bald`, `no ships or boats of any kind`,
  `bare-headed women (no hoods, no veils)`.
- **Crowds of the lead's look need her canon too:** "hundreds of women in white gowns" gave hooded shrouds; say
  "bare-headed women with glossy black bobs".

### Slot 6 — The declared empty field for type

Name the quiet area where the lyric will sit. It must match the shot's `type[].placement` in `board/shots.json`.

`the upper third empty fog` · `the right third empty dark` · `the top half empty night sky` ·
`the left third empty white` · `the lower third of the frame dark and empty` · `vast calm negative space in the upper third`

Mistake: no empty field → the type later sits on her face or on detail (`70-motion-design.md`: "never type over her
face").

### Slot 7 — The chapter style tail

One fixed string per chapter (light state + palette + one warm note + grain + finish), defined **once** in the
storyboard's chapter table and pasted verbatim into every plate of that chapter. Same chapter = same tail = plates that
cut together.

How to write a tail:

1. The light: time of day / light source, said physically (`dusk, low gold light on a glassy sea, violet sky`).
2. The palette in words (hex is fine): `blue-black #0f1216 and steel blue`.
3. **One warm note:** `one small red lamp as the only warm note`, `one small ember-orange #db5c34 light as the only warm
   note`. This is anabology's measured taste ("quiet places and one warm light").
4. Texture: `fine grain`, `fine silver-gelatin grain`.
5. The finish: `cinematic 35mm film still`, `anamorphic`, `cinematic stillness`, `flash photography`,
   `macro product photograph, hard rim light, razor-thin focus`.

EV tails (verbatim):

| Chapter | Tail |
|---|---|
| Night | `blue-black #0f1216 and steel blue, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic stillness` |
| Board / first light | `blue-black night turning to first light, clay-orange #D97757 light as the only colour, fine grain, cinematic stillness` |
| Backstage pre-dawn | `pre-dawn slate grey, one small ember-orange #db5c34 light as the only warm note, fine silver-gelatin grain` |
| Overpass at dawn | `pale dawn grey-white, soft even light, a single clay-orange #D97757 accent, fine grain, calm` |
| Bridge | `pale grey-white fog, pure monochrome, no colour at all, soft diffuse light, fine grain` |
| Drop (high key) | `high-key white void, pure white paper light, hard clean black shadows, monochrome` |
| Final / outro | `high-key white paper, soft shadowless light, monochrome except her clay-orange streak and hair clip, fine grain` |

SP tails (verbatim; the voyage runs from night to morning):

| Chapter | Tail |
|---|---|
| night | `night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain` |
| dusk | `dusk, low gold light on a glassy sea, violet sky, cinematic 35mm film still, anamorphic, fine grain` |
| twilight | `deep blue twilight, the last gold on the horizon, glassy sea, cinematic 35mm film still, anamorphic, fine grain` |
| break | `grey first light before sunrise, heavy spray, cinematic 35mm film still, anamorphic, fine grain` |
| final chorus | `sunrise, warm gold light and long shadows, spray lit gold, cinematic 35mm film still, anamorphic, fine grain` |
| outro | `clear morning light on a calm sea, cinematic 35mm film still, anamorphic, fine grain` |
| bedroom | `a dark bedroom at 3am lit only by a phone screen, blue-white glow on the face, cinematic 35mm film still, grain` |
| rave | `a San Francisco warehouse rave, fog, white strobe, chrome reflections, deep black, flash photography` |
| inserts | `macro product photograph, hard rim light, razor-thin focus` |
| posts | `high-fashion editorial photograph, magazine campaign, studio strobe, razor sharp, luxurious` |

A recurring object gets a fixed phrase too (SP's ship, always: `a long black ancient Greek galley with a single mast, a
square sail and two banks of oars`).

Note: "monochrome" words in a tail do not stop MJ from returning rich colour at night (EV's night plates came back
blue/teal with amber floor light and red lamps). That is fine: footage keeps its MJ colour.

### Slot 8 — The closer

Every prompt ends with exactly:

```
no text, no letters, no logos
```

### 4.9 The assembled template

```
<framing/vantage> <lead.canon or lead.far, + visible garments only>, <placement in frame>, <pose/action>,
<set and props: the concept as a physical object, exact form factors, blank surfaces>, <the declared empty field>,
<chapter style tail, verbatim>, no text, no letters, no logos
```

Then the pasted line adds the parameters: `<prompt> --ar 16:9 --v 8.2 --raw --hd --p <YOUR_PROFILE_CODE>`.

Worked example (EV's hook close-up, verbatim; its "young" is retired: new prompts use today's identity text, §5.1):

```
close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, sitting upright alone in the back seat of a driverless robotaxi at night, her face in the centre of the frame, eyes closed, a single red lamp sliding across one cheek through the side window, dark leather seat, the lower third of the frame dark and empty, blue-black night, fog, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic 35mm film still, no text, no letters, no logos
```

Slots: `close-up of` (1) · canon, no garments below the collar (2) · `her face in the centre of the frame` (3) ·
`sitting upright … eyes closed` (4) · robotaxi back seat, red lamp through the window (5) ·
`the lower third of the frame dark and empty` (6) · night tail (7) · closer (8).

---

## 5. The lead's identity

### 5.1 The canon block

Write the lead once, as a block of text, and store it in `project.json`:

```json
"lead": {
  "canon": "a 28-year-old Caucasian American woman with a grown-up angular face, defined cheekbones and a strong jawline, pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek",
  "far": "a Caucasian American woman in her late twenties with pale skin and a glossy black blunt bob with heavy straight bangs and one clay-orange streak, a thin headset microphone",
  "possessive": "a Caucasian American woman's"
}
```

(That is Claudia, the default lead, in the canon's current words: re-read them with `claudia_canon`. EV said "young"
and SP "in her mid-twenties", and plates still came back reading teenage. The EV and SP prompts quoted verbatim in
this doc and in `examples/` keep those old words as records; every new prompt uses the text above. Write a new
character the owner asked for the same way.)

What the canon must contain, in this order:

1. **Ethnicity / nationality descriptor** (`Caucasian American`, `Nigerian`, `Korean`, …): explicit, always.
2. **Age as a number, with an adult face** (`a 28-year-old … with a grown-up angular face`, `in her late twenties`,
   `in his early thirties`). Never the word "young". Make adult leads unmistakably adult: EV's "early 20s" lead was
   read as a teenager by viewers, so SP aged her up and banned schoolgirl cues (no pleated mini, no puff sleeves), and
   the canon now says 28 with adult bone structure.
3. **Skin** (`pale skin and light freckles`).
4. **Hair** with shape, length and colour (`a glossy black blunt jaw-length bob with heavy straight bangs`).
5. **The one signature mark** that reads at thumbnail size (`one clay-orange streak through the bangs`). One only:
   say "one".
6. **Small props that are part of her** (`a small flat clay-orange eight-pointed star hair clip`, `a thin headset
   microphone at her cheek`).
7. Wardrobe is **not** in the canon: it is a separate "look" string per world, added in slot 2 when visible
   (SP's Siren look: `wearing a structured high-neck pearl-white couture gown with long sleeves, its sculpted ruffles
   rising around her like breaking sea foam, hair damp from the spray, composed and deadpan`).

Also keep a **Never** list in the bible (not in prompts): no second streak, no orange elsewhere on her, no influencer
smile, nothing reading under-age, explicit or sexualised, no neon, no logos, no text on clothes.

### 5.2 Framing first, canon second

The canon is long. If it comes first, MJ composes a portrait. The framing words go before it, every time; the
storyboard head director on EV got this as a binding update: "State the framing explicitly at the start of every such
prompt … and where she stands in the frame. Keep her poses editorial and upright."

### 5.3 The FAR variant for full-length and wide shots

With the full canon, MJ "crops in to her face however the framing is worded": freckles, the clip and the headset pull
the frame in. SP's `chrome-full` came back as face crops four times running. What worked (batch `sp-07`):

- the camera first and far: `full-body fashion editorial photograph taken from far away with a long lens:` or
  `extreme wide shot of a vast dark warehouse rave, and alone in the middle of the empty concrete floor …`;
- the short identity `lead.far` (skin, hair, the mark; no freckles, clip or mic);
- an explicit size cue: `head to toe in frame with empty fog above her head and floor below her boots`.

Use `lead.far` for FS, WS and EWS. Use `lead.canon` for ECU, CU, MCU, MS, MWS and over-the-shoulder shots (SP:
"a woman's bare shoulder" with no canon put a stranger in the shot — OTS shots of her still need her canon). The one
exception is a pose-only reference on a plain backdrop, made to feed the video model (§14, `ghost-float`).

### 5.4 Casting call, test plates, owner approval

Claudia needs no casting call: her look is fixed, so start at step 3 with her canon. For a new character:

1. **Casting call (first batch):** 2–3 hair/look directions for the lead, each as (a) a turnaround sheet on grey
   seamless, (b) one shot in the video's main set, (c) a 6-up expression sheet (neutral, faint smile, singing with open
   mouth, eyes closed, looking over shoulder, laughing). EV picked "black bob + one clay streak" because "the silhouette
   reads at thumbnail size, and the clay colour stays a small accent".
2. Write the winning look into `lead.canon` / `lead.far`.
3. **4 test plates** of the lead at different framings (CU, MCU, FS, WS) in the real sets.
4. **The owner approves the face** (gate **G3**) before any production batch. Record the approval in `DECISIONS.md`:
   `slop decide "<the owner's words>" --by owner`.
5. During production the owner flags wrong faces on contact sheets or the board; re-roll exactly the flagged jobs with
   the descriptor present (EV batch `ev-15-fix`: 12 re-rolls).

### 5.5 The substitution bug (do not reproduce)

EV's tool substituted the canon into storyboard prompts by text replacement and shipped broken grammar:

```
close-up of a young Caucasian American woman with pale skin and light freckles,'s hand pulling a black utility harness strap tight …
… black knee-high boots's black knee-high boots stepping past the pile …
```

Rules: use `lead.possessive` for body parts; never append the canon to a phrase that already names a body part or a
garment; read every assembled prompt once before it goes in the book. The checklist in §7.3 has a row for `,'s` and
`'s` after a garment.

### 5.6 Image references: when they fail, when they are allowed

What EV tried, and what happened:

| Attempt | Result |
|---|---|
| `--oref <face sheet> --ow 200` | rejected by V8.2 ("doesn't support --oref"); no images |
| GPT Image "replace only the woman" identity pass on MJ plates | drifted from the MJ look ("diverging way too much"); refused seated poses |
| Whole face sheet as image prompt (Images slot) | imports the multi-head layout (floating giant heads) |
| Single-face crops, `--iw 0.3–1.0` | keeps the face but **over-conditions: a close-up-sized head on a distant figure** |
| Distance reference sheet (her at CU/MS/FS/WS on grey) | close/medium/full carried face crops; wide/extreme-wide had to be text-only |
| **Plain text: ethnicity + skin + canon** | **works**; adopted from then on |

anabology: "face references overindex on the face and we mostly need to get her back from textual references."

Image references are allowed **only where the owner explicitly asks**, for a subject text cannot hold:

- a sculpture/mask of her face (SP's porcelain Mask: refs at `--iw 0.75` for a close-up, `--iw 0.4` for wides "so the
  composition survives");
- an anime-style homage character (`--niji --iw 1.0`; never Claudia herself, who is photographic);
- a real public figure inside a labelled AI IMAGE post, from a licensed photo with attribution recorded (opt-in only,
  see `62-moderation.md`).

Mechanics: drag the reference into the **Images** slot of the Imagine bar (not "Attach to prompt", which is the Edit
slot); references ≤ 1024 px JPEG cropped to 16:9; `--iw` by framing (ECU/CU 1.0, MCU 0.75, MS 0.5, FS/WS 0.3, EWS 0.25
as a start). Jobs with image references cannot be packed into permutations; paste them one at a time.

**`--oref` is gone.** In V8.x, Omni Reference was replaced by the **Edit Model** (`--edit`, up to four reference images;
1 GPU-min SD / 2.3 HD). Omni Reference only works on V7. The toolkit's default is still text identity; treat `--edit`
as an experiment the owner opts into.

### 5.7 More than one character

Every recurring character gets a canon block with the same structure. SP's second lead:

```
a broad-shouldered Caucasian man in his early thirties with a shaved head, a thick short dark beard, a square jaw, heavy brows and pale blue eyes, the build of a man who lifts
```

Pinning "a shaved head, a thick short dark beard, pale blue eyes" made him consistent. Groups need **distinctness
negatives**, or MJ copies the main character into the crowd (SP's crew came back as "three copies of him"). What
worked, verbatim:

```
four oarsmen of different ages and builds pulling their oars together, a grey-haired old sailor, a lanky young man with long curly hair tied back, a heavyset man with a red beard and a wiry dark-haired man, none of them bald
```

List each person, then say what none of them is.

---

## 6. Batch strategy

### 6.1 The shape that worked

1. **Casting call** (≈ 10–25 jobs): the lead's looks (§5.4), the world's main sets, a few texture or prop plates.
   Profile only, no references.
2. **Core sets** (≈ 20–30 jobs): the places shared by most of the storyboard, with the lead in them.
3. **Tiny single-variable tests** (2–5 jobs each): when something fails, change **one** thing per test batch (the
   framing words, the identity text, one prop phrase) so the result tells you which change mattered. EV ran four small
   identity tests; SP ran 2–3-job fix batches (`sp-06-fix`, `sp-07-chrome`, `sp-08-eyes`).
4. **Fixes** (re-rolls of the flagged jobs, or image edits, §12).
5. **Plates per the approved storyboard** (≈ 20–50 jobs per batch): every plate key in `board/shots.json` that no pick
   covers yet. **No stand-ins at render time**: an alias to another shot's plate is temporary.
6. **Gap fills and variants** after the owner's board review (one more batch answering every note).

Production batches are big; test batches are tiny. Run **one batch at a time**.

### 6.2 Naming

- Batch name: `<project>-NN-<purpose>` (`myvid-01-cast`, `myvid-02-core`, `myvid-03-fix`). It is also the MJ folder
  name (§8.1).
- Job name = the storyboard **plate key** (`hall-ms`, `siren-mcu`). Variants of a job get a suffix (`white-cu-b`).
  Never reuse a job name inside a project for a different picture.

### 6.3 Throughput and size

- About one minute per job end to end; ≈ 45–50 min per 50 jobs (EV, through a browser).
- EV: 188 prompts in 15 batches → 159 completed jobs → 636 images → 130 plates used.
  SP: 161 prompts in 10 batches → 644 images → 116 plates used.
- A one-shot video (Studio tier, short song): 8–15 plates in one style family, one or two batches.

---

## 7. The prompt book and the lint

### 7.1 `plates/prompts.md` (`slop plates book`)

Write each plate's prompt on the storyboard shot that owns the plate: `mj_prompt` in `board/shots.json` (`img_prompt`
for an API plate). Write `{lead}`, `{far}` or `{possessive}` where the lead's identity goes; the book fills in the text
from `project.json` → `lead`. Keep the parameters out of the prompt text. Then build the batch:

```
slop plates book --batch myvid-02-core --plan standard     # every plate with a written prompt
slop plates book --batch myvid-03-fix --only hall-ms,siren-mcu
slop plates book --batch myvid-04-gaps --missing           # only plates that have no candidates yet
```

It writes:

| File | What |
|---|---|
| `plates/prompts.md` | **the book the owner reads**: the steps before pasting, every paste block with its expected count ("Midjourney must ask: Run **10** prompts?"), each plate's full prompt and params, and a **Lint** section with every warning |
| `plates/mj/<batch>.perm-NN.txt` | one permutation paste each (≤ 4 / 10 / 40 prompts by plan, commas escaped, params after the braces; §8.3) |
| `plates/mj/<batch>.lines.txt` | one prompt per line, with its params (Sheet A, §8.2) |
| `plates/mj/<batch>.json` | the batch file that ingest uses to match downloads to prompts (§7.2) |
| `plates/jobs.json` | the API image jobs, if any (`51-plates-api.md` §2.5) |

Re-running rewrites the book for that batch (it is idempotent); use a new `--batch` name for every new batch. Record the
owner's notes that caused a batch verbatim with `slop decide "<the owner's words>" --by owner`.

### 7.2 The batch file

`plates/mj/<batch>.json`, one per batch, so ingest can match jobs to prompts by text:

```json
{"batch": "myvid-02-core", "created": "2026-10-02", "note": "my-song plates", "plan": "standard",
 "jobs": [{"job": "hall-ms", "plate": "hall-ms", "kind": "plate", "prompt": "…",
           "params": "--ar 16:9 --v 8.2 --raw --hd --profile <YOUR_PROFILE_CODE>", "srefs": [], "irefs": [],
           "expect_images": 4, "shots": ["s011", "s013"], "lead": true}]}
```

The profile code in `params` comes only from `project.json` → `mj.profile` (the owner's own code). `--profile` and
`--p` are the same parameter.

### 7.3 Lint checklist (read every prompt before the owner sees the book)

No single command runs all of these. `slop plates book` checks some of them and lists its warnings in the book's
**Lint** section: a prompt that does not start with a framing phrase, a prompt over 800 characters, `--` parameters
inside the prompt text, a `{` or `}` left in a prompt (an error), a missing `lead` text for a placeholder, a lead plate
without the canon (it inserts the canon and warns), a sung plate whose prompt puts a microphone, a hand or anything
else at her mouth (it adds the mouth line to every sung plate, §4 slot 4), and a profile value that is not a code.
`slop board audit` checks the project's banned words across the board, prompts included, and warns (first in its
list) about a sung shot with something at her mouth. **Read every assembled prompt in `plates/prompts.md`
against the whole table yourself** (the bot does this by reading; it is not a command):

| Check | Fails when |
|---|---|
| framing first | the first clause is not a framing/vantage phrase (§4 slot 1) |
| identity present | `lead_on_screen` is true but neither `lead.canon` nor `lead.far` (nor `lead.possessive`) appears verbatim |
| FAR rule | framing is FS/WS/EWS and the full canon is used (use `lead.far`) |
| garment visibility | a CU/ECU/MCU prompt names boots, shoes or a skirt hem |
| grammar | `,'s` or `<garment>'s <garment>` appears (§5.5) |
| empty field | no `empty` / `negative space` clause when the shot has type |
| closer | the prompt does not end with `no text, no letters, no logos` |
| sung mouth | a sung plate lacks `her mouth fully visible, nothing in front of her mouth`, or names a microphone (a canon headset at her cheek aside), a hand at the lips or anything over the mouth |
| length | > 800 characters |
| params | a bare `--p`, a missing profile code, `--oref`, or an unexpected `--sref` |
| words | any word from the project's banned list; a real person's name when the project has not opted in |
| braces | a `{` or `}` inside a prompt (breaks permutations) |

---

## 8. Pasting (human in the loop — the default)

Midjourney has no API and its terms forbid automated access. So by default **the owner** submits every job; the bot
prepares everything around it.

### 8.1 What the owner does first (once per batch)

1. midjourney.com → Settings: version **8.2**, Raw on, HD on, **Personalization toggle off**, **Fast** mode (needed for
   permutations).
2. Create a folder named exactly like the batch (`myvid-02-core`) and **open it**: the Imagine bar shows "Generating in
   myvid-02-core", so every image lands in that folder.

### 8.2 Sheet A: one line per job (any plan, phone-friendly)

The lines are in `plates/mj/<batch>.lines.txt`. The bot sends one code block per job, so a phone tap copies exactly one
line:

```
<prompt for hall-ms> --ar 16:9 --v 8.2 --raw --hd --p <YOUR_PROFILE_CODE>
```

Never put a job number in front of the line (it would be pasted into the prompt). Paste one line, press Enter, next.
Basic and Standard queue at most 10 jobs at once: wait when the queue is full.

### 8.3 Sheet B: permutation pastes (Standard and up, Fast mode)

One paste can submit many jobs: `{option 1, option 2, …}` expands into one job per option. Limits per paste:
**≤ 4 (Basic), ≤ 10 (Standard), ≤ 40 (Pro, Mega).**

The plate prompts are full of commas, and an unescaped comma inside the braces would split a prompt into many jobs.
So **every comma inside a prompt is written `\,`**, and plain `, ` separates the prompts:

```
{close-up of a woman in her late twenties\, a glossy black bob\, sitting in a car at night\, no text\, no letters\, no logos, wide shot of an empty freeway at dawn\, fog\, no text\, no letters\, no logos} --ar 16:9 --v 8.2 --raw --hd --p <YOUR_PROFILE_CODE>
```

That paste is **2 jobs**. `slop plates book` builds every chunk this way and writes it to
`plates/mj/<batch>.perm-NN.txt`, with the expected count above each block in the book. What the command does:

1. Take ≤ 4 (Basic), ≤ 10 (Standard) or ≤ 40 (Pro/Mega) prompts, in batch order (`--plan` sets the size). Leave out jobs
   with image references (the book lists them separately, to paste one at a time).
2. In each prompt: replace every `,` with `\,`; make sure there is no `{`, `}` or `\` already. If you edit a block by
   hand, also replace the smart quotes and long dashes a phone keyboard might add.
3. Join the escaped prompts with `, ` inside one pair of braces; append the parameters once after the closing brace.
4. Write the expected count on the sheet: **"Midjourney must ask: run 10 prompts? Click Yes only if the number is 10."**

The confirmation count is the built-in check. If MJ asks for a different number (e.g. 87 instead of 10), a comma was
not escaped: the owner clicks **No** and tells the bot, which rebuilds that chunk. Permutations are refused in Relax mode
and above the plan limit: switch to Fast or use smaller chunks or Sheet A.

**The first permutation paste of a project is a 3-prompt test chunk.** Whether the expanded, comma-heavy plate prompts
trip V8's prompt shortener is untested. The shortener rewrites a prompt and marks the job with a **"Long Prompt"**
badge, and a rewritten job no longer matches its text at ingest (§10.4). So build a test batch of 3 typical prompts
first (`slop plates book --batch myvid-02-test --only <three plate keys>`) and paste it. The owner checks that MJ asked
for exactly 3 and that **no job carries the Long Prompt badge**. Only then paste chunks of 10 or 40 (build the rest
with `--missing` once the test images are ingested). If the badge appears, shorten that prompt family below ~800
characters, or use Sheet A for it.

### 8.4 While MJ runs

- Fast: minutes per job. Relax: 0–30 min queue per job (lines only).
- The owner waits until every job of the batch has finished before downloading.

---

## 9. Opt-in browser assist (only if the owner asks for it)

Some owners want the bot to do the pasting. That breaks Midjourney's terms (automated tools may not access or generate on
the service; the community guidelines say automating interactions is "strictly prohibited" and accounts may be blocked).
It is **off by default** and offered only when the owner asks.

Before enabling it, send this warning and wait for an explicit yes (record it in `DECISIONS.md` with the date):

> **Browser assist for Midjourney — please read.** Midjourney's terms forbid automated tools. If I type prompts into
> midjourney.com for you, your account may be suspended or banned, and Midjourney allows one account per person. You
> sign in yourself; I will never type, read or store your password, and I stop at any captcha, Cloudflare check or
> two-factor prompt. Logins in my browser stay saved on this computer and are shared by every bot and routine that runs
> on it — sign out when we are done if that matters to you. Reply "I accept the risk" to turn this on for this project,
> or "no" to keep pasting yourself.

Rules once enabled:

1. **The owner signs in** in the bot's browser (typing it themselves, or approving their password manager's fill). The
   bot never enters credentials, never solves a captcha, a Cloudflare check or 2FA: it stops and hands the browser back.
2. **The owner approves each batch in chat** before the bot submits it; the bot shows the sheet and the expected job
   count first.
3. One batch at a time, one tab, the batch folder open (§8.1). For permutations, read the confirmation count and click
   Yes only if it equals the expected number.
4. **Identify every job by its own prompt text, never by position** (a stray re-run once shifted 16 jobs by one while
   the count still matched). Check each job carries the right profile; a wrong-profile job is not ingested.
5. Downloads go through the site's own Download button only (§10.1). Never fetch images with exported cookies.
6. Stop at anything unexpected (a dialog, a changed layout, an error toast) and ask. Never retry a login or a payment.
7. An owner can also teach their own UI by demonstration (Grok Bot's "Teach a task" recording). The same warning applies.

---

## 10. Ingest and picks

### 10.1 The owner downloads

1. Organize → open the batch folder → **Profiles** filter → tick the V8 profile → select all.
2. **The selection count must be 4 × jobs** (49 jobs → 196 images). Lower means some jobs ran on the wrong profile:
   download anyway and tell the bot the number.
3. Download (or the folder's ⋯ → Download). MJ delivers zip files (reported 50 images per zip).

### 10.2 The owner hands the files over (pick one channel)

| Channel | Limits | Use for |
|---|---|---|
| Chat attachments | 6 files per message, 25 MiB each | picks only (≤ ~30 images); phone OK |
| Google Drive folder `Claudia/<project>/mj/<batch>/` with the zips | the bot lists it via the Drive connector; files are pulled to the box by link-share + `curl` (the owner sets "Anyone with the link: Viewer", then back to Restricted) | full grids |
| `CopyToBox` from the owner's computer | 100 MiB per file, one approval per copy | full grids on a desktop session: zip in ≤ 95 MiB parts |

Size guide: an MJ JPG is ≈ 0.9 MiB (a PNG ≈ 6.5 MiB); an EV-scale project is ≈ 550 MiB as JPG.

### 10.3 The bot ingests (idempotent)

```
slop plates ingest uploads/myvid-02-core.zip --batch myvid-02-core     # a zip, a folder of images, or one image
```

What the command does (and what to do by hand if it can't):

1. Reads the zip or folder without overwriting anything; the originals stay untouched.
2. De-duplicates by SHA-256 (double downloads happen); re-running skips files it already has.
3. Identifies each job (§10.4) and writes its four images as `plates/cands/<plate>/<k>.jpg`, `k` = 1..4 in grid order,
   with source names, SHA-256 and sizes in `plates/cands/index.json`.
4. Lists the batch's plates that still have no images, and writes `plates/unmatched.jpg` for anything it could not
   match.

Then check by reading its output and `plates/cands/index.json`: every image decodes; 16:9 HD = **2944×1648** (1456×816 on
a non-niji job means it ran SD → flag it); count = 4 × expected jobs.

### 10.4 Matching images to jobs

1. If filenames carry a job id, group by it; each group must have exactly 4 images.
2. Map each group to its prompt by **text** against the batch file's prompts — the prompt stored in the file's
   metadata when present, else the normalised prompt words in the file name (lowercase, collapse whitespace and
   underscores, unify quotes and dashes) — **never by position**.
3. Groups that don't match (MJ's prompt shortener rewrote them, or the names only show the shared framing and canon) go
   on `plates/unmatched.jpg`, a "who is this?" sheet. Look at it beside the unmatched plate prompts, propose a mapping,
   and ask the owner to confirm in one reply. Then record it and re-run (already ingested files are skipped):
   `slop plates ingest uploads/myvid-02-core.zip --batch myvid-02-core --map 1a2b3c4d=hall-ms`
   (the key is the start of the job id, or a file name).
4. Only if filenames carry no id and the owner pasted in sheet order may download order be used — and confirm visually.

### 10.5 Contact sheets

`slop plates sheet` (or `--plates hall-ms,hall-wide`) writes numbered picking sheets to `plates/sheets/pick-NN.jpg`: one
row per plate with its candidates labelled **#1–#4**, ≤ 10 plates per sheet, small JPEGs (well under the 25 MiB attachment
limit). Send each sheet to the owner as a file.

### 10.6 Picking

- The owner replies `hall-ms #2, hall-wide #4, …`, **or** says "agents pick, I review on the board" (SP's flow: agents
  picked from contact sheets, then the owner reviewed every pick on the storyboard PDF with the project grade applied).
- Record the picks: `slop plates pick hall-ms 2 hall-wide 4` (the owner's reply pasted as `"hall-ms#2, hall-wide#4"`
  works too). It writes `plates/picks.json`:

```json
{"hall-ms": {"file": "plates/cands/hall-ms/2.jpg", "cand_k": 2, "shot_ids": ["s011", "s013"]}}
```

- What to look for when picking: on-canon (one streak, one clip, the right age read), anatomy (EV's flagged "backwards
  head"), the declared empty field really empty, no text or logos, the right framing, nothing stock-photo-like (crowds,
  elderly or patient portraits, generic clinic close-ups were rejected as "too stock photo-y"). On a **sung** plate,
  never pick a candidate with a microphone, a hand or hair in front of her mouth, however good the rest is: re-roll
  that plate (`slop plates book --only <plate> --batch <new>`); the lip sync is measured on that mouth.
- Show the owner graded thumbnails when the project has a grade, so they review what will be on screen.

---

## 11. The unpicked candidates are a free variety pool

Every job returns four images; the pick uses one. **The other three are already paid for.**

- **One image per shot.** If two shots that are not one continuous moment use the same plate, the second shot takes the
  job's next candidate (anabology: "should have the same image for like 6 diff storyboard shots" was a complaint,
  not a request). `slop board audit` fails on a repeated plate candidate.
- **Two clips never start from the same frame.** The k-th clip made from a plate uses the plate's k-th other candidate;
  when the candidates run out, it continues from the previous clip's last frame (`60-clips.md`).
- Watch for black-and-white or off-canon candidates before using one; skip them.
- Only make a new MJ job when the pool is empty or off-canon.
- `slop plates vary` applies both rules: a plate used on several shots that are not one continuous moment gives the
  later shots its other candidates as variant plates (`<plate>~<k>`). Run `slop plates vary --dry` first to see what
  would change. It treats every numbered file in `plates/cands/<plate>/` as a candidate, edits included (§12.3), so
  check its choices. It rewrites `board/shots.json`, so on a board the owner approved it prints the one-line "board
  gate is now stale" warning: show the owner the new sheet and re-approve after their yes (`40-storyboard.md` §11.3).

---

## 12. Fix the source: image edits

When a picked plate is right except for one thing, **do not re-roll and do not paint it**. Use the image-edit model
(default `project.json` → `models.edit`; SP used Gemini 3 Pro Image through OpenRouter, ≈ $0.14 per edit, 16 edits for
$2.22). anabology's rule, after a hand-painted effect: it "should have been in the midjourney prompt from the start
or with the edit model".

### 12.1 When to edit, re-roll or re-prompt

| Problem | Do this |
|---|---|
| One wrong detail on a good pick (an extra hair clip, a modern object in a period scene, a crew copying the lead, a hood that should be bare hair, a missing effect such as chrome eyes) | **image edit** |
| The face reads as the wrong ethnicity or age | re-roll with the descriptor (§5.4); edits change faces badly |
| Wrong framing, wrong pose, wrong set | re-prompt (new job) |
| The pool has a candidate without the problem | use the candidate (§11) |
| A provider declined the image | **not an edit case.** Never alter an image to pass a filter (`62-moderation.md`) |

### 12.2 The instruction grammar

```
Edit this photograph. Change only <the thing>: <its precise target state, with negatives>. Keep <the things that must not move>. Keep everything else exactly as it is: the same framing and crop, the same light, colours, film grain and sharpness, the same people and objects except what this instruction changes. Photorealistic, the same photograph, same aspect ratio.
```

The last two sentences are the **fixed KEEP clause**; the toolkit appends it verbatim to every edit. Examples that
worked (SP, verbatim instruction parts):

- `Change only the man's eyes: make both of his eyes (the whole eyeball, iris and white) mirror-polished liquid chrome silver, like a chrome ball bearing, catching the white strobe light as hard specular highlights and reflecting a tiny dark figure of the woman.`
- `Change only the standing figures on the rocks: make every one of them a young woman seen from behind or in profile with a glossy black jaw-length bob with heavy bangs, in a white structured high-necked couture gown with long sleeves, bare-headed (no hoods, no veils, no cones), all facing the same direction toward the horizon. Keep their number and their positions on the rocks.`
- `Remove the orange star hair clip on the left side of the image, so that exactly one small clay-orange eight-pointed star clip remains (the one on the right side of the image). Keep the eye, the lashes, the orange streak and everything else.`
- `Make her hair clip a small flat clay-orange EIGHT-pointed star (exactly eight points), not a pink six-pointed star.`

### 12.3 After every edit

1. **Re-check the canon**: the edit model can introduce new errors (the pink six-pointed star above came from an edit).
2. Keep the original pick; save the edit as the plate's next candidate number and pick it:
   `slop gen edit plates/cands/hall-ms/2.jpg plates/cands/hall-ms/5.png --change "…" --keep "…" --yes`, then
   `slop plates pick hall-ms 5` (`51-plates-api.md` §6). The edit is spend: the owner's yes first.
3. Re-run the plate prep (depth, mattes, detection) on the edited image — SP's first cut used stale pre-edit mattes.
4. Re-make any clip that started from the old version of the plate.
5. Edit outputs are ≈ 1376×768 at 1K: request 2K where the endpoint offers it, otherwise upscale with Lanczos to 2400
   wide (learned upscalers measured worse: shimmer, waxy skin).

Details of the edit API and the other edit models: `51-plates-api.md` §6.

---

## 13. Failure catalogue (Midjourney)

| Symptom | Cause | Fix |
|---|---|---|
| The lead's ethnicity drifts | no ethnicity/skin words, or canon not verbatim | paste `lead.canon` verbatim; re-roll flagged jobs |
| A full-length prompt returns face crops | full canon on a far shot | camera-first wording + `lead.far` + head-to-toe size cue (§5.3) |
| An oversized close-up head on a distant figure / floating giant heads | face image references | text identity only (§5.6) |
| Whole batch in the wrong look | bare `--p` (default Global V7) or the toggle on | explicit `--p <code>`, toggle off; re-run |
| "Version 8.2 doesn't support --oref" | `--oref` | remove it; V8 uses the Edit Model |
| 1456×816 instead of 2944×1648 | HD off | re-run with `--hd`, or accept for a minor insert |
| Permutation asks for the wrong number of prompts | an unescaped comma or brace | click No; rebuild the chunk with `\,` |
| Permutations refused | Relax mode or over the plan limit | Fast mode; chunks of ≤ 4/10/40 |
| Jobs missing after download | moderation block, skipped paste, queue overflow | ask for a screenshot of any notice; reword plainly; send a "resume" sheet of only the missing jobs |
| Fewer than 4 × jobs under the profile filter | some jobs ran without the code | resume sheet for those jobs |
| Images don't match any prompt | MJ rewrote a long prompt ("Long Prompt") | match by content (§10.4); shorten that prompt family |
| Crew or crowd are copies of the lead | no distinctness negatives | list each person + "none of them …" (§5.7); or edit |
| Hooded or robed figures | "women in white gowns" | "bare-headed women with glossy black bobs"; or edit |
| The key object is missing ("covered in eyes" → bare flank) | the object is not the subject of its clause | make it the subject (§4 slot 5) |
| Wrong object form (robotaxi → old sedan) | vague noun | name the exact form factor |
| A stranger's shoulder in an OTS shot | no canon on "a woman's shoulder" | OTS shots of her carry her canon |
| Nude-reading or reclining results | "sheer", "bare shoulders", fashion words on bodies | structured garments, upright poses, "composed and deadpan" |
| Real 1-bit / xerox look requested | MJ returns a grainy photo | do print looks in post (`70-motion-design.md`) |
| A plate is reused across many shots | stand-in aliases | real plates + the variety pool (§11) |
| A microphone or a hand in front of her mouth on a sung plate; that clip then barely syncs (Studio run: 26 %) | "singing" makes image models add a mic; a mic or a hand-to-mouth pose written in the prompt | take it out of the prompt (the book adds the mouth line to sung plates); never pick such a candidate; re-roll (§4 slot 4) |

---

## 14. Exemplars (verbatim, from the two reference videos)

The lead's descriptor in these is the reference videos' lead; write yours from your own `lead.canon`.

**Insert, no lead, with a declared empty field (EV):**

```
a vast low datacenter on a black plain at night, steam plumes rising from its roof, a row of loading bays lit white, one red aviation lamp, a small white robotaxi turning into the nearest bay, a passenger silhouette in its rear window, the top half empty night sky, blue-black #0f1216 and steel blue, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic stillness, no text, no letters, no logos
```

**The concept as an object (EV, a podcast joke as a set):**

```
medium close-up of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt, seated in the right half of the frame behind a large broadcast microphone on a boom arm in a pure black void, speaking calmly like a podcast guest, one hard top light, the left half of the frame empty black, blue-black night, fog, one small red lamp as the only warm note, fine silver-gelatin grain, cinematic 35mm film still, no text, no letters, no logos
```

**High-key chapter (EV; EV still used the full canon on full-length shots — on SP's evidence, use `lead.far` there):**

```
full-length shot of a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt, a black pleated skirt with a harness belt and a hanging white garment tag, black knee boots, stepping upright out of an oversized empty white shoebox on a white paper floor, the lid leaning beside it, white tissue paper spilling out, in the centre of the frame, high-key white paper light, almost no shadow, vast empty white, monochrome, fine grain, no text, no letters, no logos
```

**A distance reference (EV `dist-ws`; the size cue in slot 3):**

```
wide shot: a young woman with a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt with a small spark pin on the collar, a black pleated coated-nylon skirt with a harness belt and a hanging white garment tag, black knee-high boots, standing small in the middle of the frame, her whole figure about one third of the frame height, lots of empty studio floor and wall around her, in an empty seamless light-grey photo studio, plain backdrop and floor, soft even light, nothing else in the frame, deadpan expression, cinematic 35mm film still, fine silver grain, no text, no letters, no logos
```

**Character plate with the look string (SP, `siren-mcu`):**

```
medium close-up of a Caucasian American woman in her mid-twenties with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy straight bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone at her cheek, wearing a structured high-neck pearl-white couture gown with long sleeves, its sculpted ruffles rising around her like breaking sea foam, hair damp from the spray, composed and deadpan, sitting on a black wet rock, turning her face to the lens, sea spray behind her, empty dark sea on the left, night, moonlight on a black-teal sea, silver spray, cinematic 35mm film still, anamorphic, fine grain, no text, no letters, no logos
```

A plate series by changing one clause (SP `inst-1 … inst-8`): the same prompt with only `behind her one / two / four /
eight identical copies of the same woman rising out of the sea foam onto the rocks` changed.

**The FAR fix (SP, `chrome-full-b`, picked after face crops four times):**

```
full-body fashion editorial photograph taken from far away with a long lens: a young Caucasian American woman with pale skin and a glossy black blunt bob with heavy straight bangs and one clay-orange streak, in a mirrored liquid-chrome couture bodysuit, chrome opera gloves and chrome thigh-high boots, standing tall and still on a wet mirror-black floor that reflects her whole figure, head to toe in frame with empty fog above her head and floor below her boots, a warehouse rave lit by white strobes, deep black, flash photography, no text, no letters, no logos
```

**A pose plate made only as a video reference (SP, `ghost-float`; the canon is shown as its slot):** an isolated pose
on a plain backdrop, fed to the video model next to the scene's start image, when MJ can't compose the character into
the scene at that pose. **This is the one exception to rule 5:** a full-body shot that keeps the full `lead.canon`. On a
plain backdrop there is no set for a face crop to lose, and the video model copies the face from this image, so the
face details must be in it. With SP's canon filled in, it runs to about 840 characters, over the ~800 budget (§3). It
passed, but watch this kind of prompt for the Long Prompt badge.

```
full-body side view of <lead.canon>, wearing the same structured high-neck pearl-white couture gown, all of her translucent as if made of glass and seawater, faintly lit at the edges, hair drifting as if underwater, floating horizontally in mid-air like a diver gliding, chest toward the floor, her head and neck reaching forward as if about to whisper into someone's ear, the long gown trailing behind her like smoke, arms soft at her sides, elegant and poised, the composure of a high-fashion model, against a plain dark grey backdrop, no text, no letters, no logos
```

**A mirrored A/B pair for a flicker edit (SP `flip-a` / `flip-b`):** write both prompts with identical framing language
(`side view at sunrise on the deck …, the mast in the centre of the frame, rowers with orange earplugs rowing below, sun
flare`) and swap only the roles (who is tied, who stands a step away).

**Anti-examples** (what not to ship): the two substitution bugs in §5.5; a close-up that lists knee boots; a set-first
prompt where the lead is the last clause.

---

## 15. Checklists

**Before sending a batch to the owner**
- [ ] `slop plates book` ran; its Lint section is empty or every warning is answered; every prompt was read against the
      checklist (§7.3); `slop board audit` has no banned-word failure.
- [ ] The project's first permutation paste is a 3-prompt test chunk with no Long Prompt badge (§8.3).
- [ ] The lead's 4 test plates were approved at gate G3 (first production batch only).
- [ ] GPU minutes computed (jobs × 1.3) against the owner's plan; permutation chunk size matches the plan. If the
      batch needs paid extra GPU time, it is a spend: ask at gate G5 with the estimate.
- [ ] Sheets built (lines and/or permutations) with the expected confirmation counts written on them.
- [ ] Image-reference jobs are listed separately with their reference files and `--iw`.
- [ ] `plates/prompts.md` and the batch file are saved.

**After ingest**
- [ ] `slop plates ingest … --batch …` ran; 4 × jobs images, all 2944×1648 (or flagged), no duplicates, every job
      matched by text (`plates/unmatched.jpg` resolved with `--map`).
- [ ] Contact sheets sent (`slop plates sheet`); picks recorded with `slop plates pick` (`plates/picks.json`, `cand_k`);
      `slop plates vary` run.
- [ ] Unpicked candidates kept in `plates/cands/` (the variety pool).
- [ ] Edits done for one-detail fixes, canon re-checked, prep re-run.
- [ ] `slop board audit` passes the one-image-per-shot check.
