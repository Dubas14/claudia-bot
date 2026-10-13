# 30 · Taste: capturing the owner's taste, the tokens, and calibrating reviewers to the owner

Read this before the first setup session, before you choose the look of a project, before you write any image prompt
from taste, and before you set up any reviewer. It tells you how to learn what this owner likes, what the result
means, how far to trust it, and where it may and may not be applied.

**Outputs:** `taste/taste-tokens.json` (machine-readable taste) and `taste/look-bible.md` (the suggested look plus the
questions to ask the owner), both from `slop taste tokens`; `taste/verdicts.jsonl` (every owner verdict, verbatim:
`slop taste verdict` writes the verdicts on taste rules, and you append the verdicts on finished pieces by hand, §5);
the taste module's tap log; the owner's answers and every rule's confirmed/rejected status in `DECISIONS.md` (never in
`taste-tokens.json`, see §1); the confirmed look in `project.json` (`slop taste apply`, §1).

**Commands (a typical first session):**

```
slop -p <name> taste pool add --arena <channel-slug> --mine   # or --dir <folder>, --urls <file>; ≤ 600 Are.na blocks
slop -p <name> taste embed                                    # image vectors on CPU (~0.35 s/image), cached
slop -p <name> taste serve --tunnel                           # prints the https link for the owner's phone
slop -p <name> taste status                                   # taps, meter, stop rule
slop -p <name> taste sheet                                    # no tunnel? numbered pair sheets for the chat (§2.4b)
slop -p <name> taste record --sheet <id> "1a 2b 3a 4b"        # the owner's one-line reply to that sheet
slop -p <name> taste fit && slop -p <name> taste meter && slop -p <name> taste tokens
slop -p <name> taste verdict texture rejected --note "<the owner's words>"   # one per answered question (§1)
slop -p <name> taste apply                                    # preview the confirmed look; --yes after the owner's OK
slop -p <name> taste fonts --tunnel                           # font A/B on real lyric lines over the style frame
slop -p <name> taste fonts rank
slop -p <name> taste board "dark technical labels; tiny monospace type"   # a mood board + text-free references
slop -p <name> taste stop
```

---

## 0. The ten lessons first (from the owner whose taste built EV and SP)

These were each learned by getting it wrong once. Obey them before any statistic.

1. **A verdict on a finished piece beats any number of A/B picks.** The owner, about a week of A/B font and layout
   duels: "these weren't good, i chose them in a/b testing above the one they opposed. the real stuff was my are.na
   picks." A model fit on those duels predicted held-out picks at **49.5 % (chance)**. One verdict on one finished
   design (the "001-A" layout below) carried more than all of them.
2. **Taste in references is not the grade of the footage.** 82 % of the owner's liked references were near-monochrome
   (vs 70 % of passes), so EV's first cut got a monochrome grade with a red accent. The owner: "the majority of the video
   is way too.. gray … loses the Midjourney magic … Id change the early halftone from red to Claude orange." A 3.5-hour
   rework. Reference statistics say **how restrained the graphics are**, never what the footage looks like and never
   which hue the accent is.
3. **Native generator colour unless the owner asks for a grade.** Another project: "Some color grading looked insane …
   would prefer to use midjoureny native colors. And the blue clashes w the blue from the shots." The exception proves
   the rule: on SP the owner *asked* for a grade toward one plate ("s018 color is PERFECT") and for no texture ("keep it
   clean so it feels like imax, high res rather than dithered").
4. **Graphics must be real and belong to the picture.** "as if when you were taking the picture, you lined it up
   perfectly to have the graphics fit, but you put the graphics in in post". "the only thing i really like are real
   graphics that are derived from math, physics, cad, or real data". "i dont like claude svgs". Image generators make
   backgrounds and textures ("mj is backgrounds only"); anything with content (a chart, a scan, a diagram) is computed.
5. **Illegibility only when it is a choice.** "illegibility is actually kind of good, but it has to be tasteful where
   you feel like the illegibility is a design choice." Text is either readable (contrast ≥ 4.5 for small type, ≥ 3 for
   large) or a declared mass of texture. Nothing in between.
6. **Restraint is the look.** In the one design the owner called good, type covers about 6 % of the canvas; one accent;
   grain matched to the thinnest stroke.
7. **Agent-written style guides drift.** 26 of 28 written by agents were never approved and "pulled work away from what
   he liked". Keep exemplars, measured tokens and verbatim verdicts. No style rule without an owner verdict.
8. **No stock-photo subjects.** "dont like the crowd or old woman. they became too stock photo-y … stuff that you look at
   and feels like a stock photo … change the direction entirely". Crowds, elderly or patient portraits, hands with
   props, generic clinic shots → a new idea, not a re-roll.
9. **Only the faces the owner named.** "is that serif font even one i chose?" A new font needs the owner's yes.
10. **Review by eye, fast.** Send takes quickly, one line each; don't measure visual qualities the owner can just look
    at ("dont worry about meausuring tumble lol"). Sample one direction before building a whole line ("not good. ignore
    all the shirts.").

---

## 1. The evidence ranking

When sources disagree, the higher one wins.

1. **The owner's verdicts on finished pieces**, verbatim, dated (style frames, plates, cuts).
2. **The owner's explicit statements** ("use Claude orange", "no strings").
3. **Likes and passes on high-quality human-made references** (the tap feed).
4. **The owner's kept artefacts** (wallpapers they installed, images they reuse, their own past work).
5. **A/B picks between generated designs.** Weakest: chance-level on rule-built designs and position-biased (§2.6).

Every derived rule is a **hypothesis** until one owner verdict on a rendered frame confirms it. Rule status values:
`hypothesis` → `measured` (has a statistic with n and p) → `confirmed` (an owner verdict agrees) → or `rejected`.

**Where each status lives.** `slop taste tokens` rebuilds `taste/taste-tokens.json` from the taps every time it runs:
it sets the statistical statuses (`hypothesis`, `lead`, `measured`, `not measured`, `ask-owner`) and honours the owner's
recorded verdicts. **Never edit `taste-tokens.json` by hand**: the next run silently overwrites the edit. Record each
owner answer with one command instead (the tokens output and `look-bible.md` print the exact command for each open
question; `slop -p <name> taste verdict --list` lists the rules):

1. `slop -p <name> taste verdict RULE confirmed|rejected [--value V] --note "<the owner's words>"` writes one line to
   `taste/verdicts.jsonl` and a dated `TASTE <rule> <value>: CONFIRMED (…)` line in `DECISIONS.md`. The question ids
   work as rule names:

   | Question | Command (examples) |
   |---|---|
   | accent | `taste verdict accent confirmed --value "#D97757"` or `--value none` (the value is required) |
   | footage grade | `taste verdict footage_grade confirmed --value native` (or `clean-grade`, `print`) |
   | faces | `taste verdict faces confirmed` = show the lead's face; `rejected` = hide faces |
   | texture | `taste verdict texture confirmed` = add grain; `rejected` = no grain (never `rejected --value clean`) |
   | style frame | `taste verdict style_frame confirmed --value 2` (its number or file); `rejected` = none is close |
   | type | `taste verdict type confirmed` (the A/B leader, or `--value "Space Grotesk"`); `rejected` = the next font |

   A verdict binds to the value it judged: when new taps move the statistic, the old verdict is listed as stale and
   the question comes back. The accent, the grade, faces and the style frame are choices for ONE video: another
   project's answer only becomes the proposal ("last time: #D97757 — the same again?").
2. `slop -p <name> taste apply` previews the look those answers give (`look.mode`, `look.accent`, `look.fonts`, the
   plates' style tail). Show the preview to the owner; after their yes, run the same command with `--yes` (it writes
   `project.json`, logs `DECISIONS.md` and records the owner-valued choices as confirmed verdicts). `banned` takes
   anything the owner rules out.
3. A verdict on a finished piece (a style frame, a plate, a cut) is appended to `taste/verdicts.jsonl` by hand (§5).

Whoever reads the taste (you, a reviewer, a delegated brief) takes `confirmed`/`rejected` from `DECISIONS.md` and the
statistics from `taste-tokens.json`; when they disagree, `DECISIONS.md` wins.

---

## 2. The capture protocol (setup session)

### 2.1 The interview (one message, at most 8 questions, the most consequential first)

Always ask these four (each cost EV a round-trip when it wasn't asked):

1. "Which accent colour, if any? (A brand colour?)" — the feed can't tell you a hue.
2. "Should generated footage keep the generator's own colour, or get one global grade?" — default: keep it.
3. "Show faces or hide them?" — EV's audit said hide; the owner wanted the lead to sing.
4. "Which of these three style frames is closest, and what's wrong with the others?" (§2.5, once frames exist.)

Then, as needed: texture (clean / grain / print halftone), density (sparse and intentional / dense), type preferences,
taboo words and subjects, any reference videos or images. Generate a question for every **conflict** you find (a
statistic against a stated brief; two kept sources that disagree; a rule resting on one verdict). Each question states
the evidence on both sides with numbers, proposes a default, and asks for yes/no or A/B. Log the answers verbatim.

### 2.2 The tap feed: sizing

The owner taps like / pass on reference images (and now and then picks the better of two). The model learns which
*kinds* of images they like.

| Session | Taps | Time | Expected accuracy | Good enough for |
|---|---|---|---|---|
| minimum | 60 | ≈ 3 min | ≈ 67–71 % | the main "modes", colour restraint (if ≥ 20 likes) |
| **recommended** | **150 + 3 style frames** | **≈ 7 min + 2 min** | **≈ 75–79 % ± 8** | everything in §3 |
| full | 300 | ≈ 13–15 min | ≈ 80–81 % ± 6 (the plateau) | heavy users; better as 150 now + 150 after the first project |

Measured on the owner of EV/SP: 22.9 taps a minute, a median of **1.2 s per single card** and 2.8 s per pair. Accuracy
("picks the one they prefer", held out) grew as ≈ `0.5 + 0.316 × (1 − e^(−taps/75))`: 52 % at 20 taps, 65 % at 40, 73 % at
100, 79 % at 150–200, 81 % at 300. The ceiling (how often the owner agrees with themselves) was never measured; measure
it (repeats, below).

### 2.3 The tap feed: card policy (what the taste module serves)

1. **40 cold-start cards** stratified over clusters of the pool, so every "mode" (diagrams, labels, printed matter,
   photography, 3D, …) is seen once before the model has an opinion.
2. Then the model's picks by Thompson sampling, with **15 % pure exploration**, and **1 card in 7 a pair** ("which is
   better?": two items the model scores alike that look different).
3. **4–6 repeats**: cards answered at least 60 taps earlier, shown again once. Agreement on repeats is the owner's
   ceiling.
4. Duplicates filtered (near-identical images, the same project posted twice).
5. Show the meter as "predicts you 76 % ± 8". **Stop** when the meter (the mean of its last 3 readings, the app's own
   readings preferred) moved by less than 2 points over the last 50 taps on **2 checks in a row**, never before 150
   taps; always stop at 200. `slop taste status` reports the stop rule.

What the model is (for explaining it to the owner in one line): every image becomes a vector (a SigLIP 2 image
embedding); likes, passes and pairs fit one preference direction plus a nearest-neighbours term for the separate
"modes" of taste. Measured: the model's own picks were liked 51 % of the time against 18 % for random exploration.
It is good at **what kind** of image the owner likes and bad at **how good** an example is (its confident errors were
genre-matched but ordinary work). One owner uses **one embedding model forever**: vectors from different models
can't be mixed.

### 2.4 The tap feed: the pool and the interface

**The pool** needs 300–400 candidates for a 150-tap session. Build it from, in order of preference:

1. **The owner's own curation:** their Are.na channels and the channels they follow
   (`slop taste pool add --arena <slug> --mine`; with the owner's own access token as the `ARENA_TOKEN` secret, entered
   on the secure secret card, `@me` and `@following` work too). At most 30 requests a minute and 600 blocks (what is
   kept per image: "Pool storage" below); re-sync only when asked. `--mine` is the owner confirming the
   channel is theirs or one they follow — never add other people's channels wholesale.
2. **Other owner-supplied images** (`--dir <folder>` or `--urls <file>`): references they saved, posts they exported,
   their own past work, generator images they kept (`--kind generated` for their own AI images).
3. **The starter deck** for a cold start (`slop taste pool add --starter`): about 300 swatches the toolkit renders
   locally (CC0 by construction, OFL fonts only, deterministic), deliberately diverse, including anti-modes the owner
   will pass on (neon flyer, y2k chrome, glossy 3D, pastel, dense collage) so they can be learned. It measures
   system-level taste (restraint, ground, density, type, anti-modes), not imagery or subject matter: replace it with
   the owner's real references as soon as they have some.

Pool storage: each item keeps a ≤ 1024 px JPEG copy (needed to embed on the CPU), its title, source URL and image URL,
served only through the token-gated tap app. `slop taste board` picks text-free reference images with a calibrated
cutoff (the stricter of a rendered-lettering probe and the pool's least-text third); `--text-max X` overrides it.

**Never crawl.** Are.na's terms prohibit automated crawling and mass downloading (guests get 30 requests a minute); a
90,000-image crawl like the one EV's taste model used must not be repeated by the template. References are evidence
of a system, **never material to copy**.

**The interface** (what the owner responded well to):

- phone-first, one tap per card, ~1 s decisions, a visible undo;
- "both bad" and "skip" on pairs (their rate is itself a signal);
- pairs side by side (`row`) even on a phone, labels revealed only after the pick;
- a visible meter ("how well do I know you") and a "saved" view of their likes;
- log for every pair which item was shown first and the layout (`shown`, `layout`), for the position correction.

Avoid: pairs that differ in one hard-to-see detail ("hard to see the difference … I would rather do it blinded").

### 2.4b No tunnel? Pair sheets in the chat

The tap app over a Cloudflare quick tunnel is the primary path. When no tunnel works, send numbered pair sheets:

1. `slop -p <name> taste sheet` writes the sheet images (4 pairs each, JPEG ≤ 2 MB) and prints the message to send
   with them and the exact record command, which names the sheet: `slop -p <name> taste record --sheet ID "…"`.
2. Send the images and the message. The owner answers in one line: `1a 2b 3t 4x` (a = left, b = right, t = can't
   choose, x = skip). A greeting or "thanks" around the answers is ignored; anything else is quoted back as an error.
3. Run the printed record command with the reply as written. It prints the quick meter once 20 answers with image
   vectors exist (run `slop -p <name> taste embed` first).

Running `slop taste sheet` again shows the sheet still waiting for its reply instead of making a new one; `--new`
makes another anyway, and `--discard ID` closes a sheet the owner will not answer. With two sheets open, `record`
without `--sheet` refuses and lists both commands. Sheet answers are ordinary pair taps: fit, meter and tokens use them.

**One taste profile per user.** The taps, model, meter and font picks live in the user's profile (`$SLOP_HOME/taste`),
and every new project links to it, so the second song starts with the first song's taste. `slop -p <name> taste use`
shows where a project's taste lives; `slop -p <name> taste use --profile=project` gives a project its own (`--fork`
starts it from a copy); `slop -p <name> taste use --profile=user --merge` adds an older project's own taps to the
profile. Tokens, verdicts on this video's choices and
`look-bible.md` stay in each project.

### 2.5 Style frames (the most valuable two minutes of the session)

1. From the draft tokens, render **3 style frames** that differ on the **riskiest axes** for this project: footage
   colour native vs graded; accent A vs B; type as a small coverline vs a giant masthead; texture clean vs grain. Use a
   real plate and a real lyric line when you have them.
2. Send them numbered in one message: "Rank these 1–3 and say in one line what's wrong with the others."
3. Record the pick: `slop -p <name> taste verdict style_frame confirmed --value 2 --note "<the owner's words>"`, and
   append the full answer to `taste/verdicts.jsonl` (level `frame`; §5 has the line format).
4. Translate each sentence of the verdict into token changes (measure the winning frame: sizes, positions, contrast) and
   record each affected rule with `slop taste verdict RULE confirmed|rejected` (§1). Do not edit `taste-tokens.json`.
5. Only then write the confirmed values into `project.json` with `slop -p <name> taste apply` (preview), then
   `slop -p <name> taste apply --yes` after the owner's yes.
6. Re-check at the first rough cut with one 20–40 s excerpt **before** fix rounds, so "too gray" arrives at hour 2, not
   hour 15.

### 2.6 Font A/B (short, separate, after a style frame is approved)

Fonts are chosen **on real lyric lines set over the approved style frame**, never on abstract specimens.
`slop taste fonts --tunnel` sets up the session (the frame defaults to `look.hero_plate` or the first picked plate;
`--frame`, `--families "A,B,C"` and `--text "<lyric line>"` override) and prints the link; `slop taste fonts rank`
gives the position-corrected ranking.

1. Candidates: only fonts the engine ships (OFL licence) plus any the owner names. Never Nimbus Sans, Junicode,
   Pilcrow Rounded or Alchimia (licences).
2. Each card: the same frame, the same words, **one** type choice different (usually the display face).
3. **30–50 decisive picks** (≈ 6–9 min at ≈ 4 s per pair).
4. **Counterbalance:** every comparison that decides a token (the final two or three fonts) is shown **twice, in both
   orders, at least 20 cards apart**. A split vote (A then B) is a tie.
5. **Correct for position.** On the reference owner the first-shown option won **61 of 90 decisive picks (67.8 %)**
   although sides were randomised; a first-slot term in the ranking model came out at **+0.86 logit (70 % for two equal
   options)**, and **31 of the 43 "unbeaten" fonts had won only from the first slot**. So: fit the ranking with a
   first-slot term, and **never call a font "preferred" without at least one win from the second slot**. Need ≥ 2
   decisive games per font and ≥ 30 decisive games in total.
6. **Session check:** if more than 60 % of a session's decisive picks went to the first slot (binomial p < 0.05), the
   owner is choosing between weak options. Down-weight that session and show better options instead of more pairs.
7. How many picks you need: a strong preference (≈ 75/25) shows in ≈ 15 decisive picks, a mild one (≈ 65/35) in ≈ 45;
   after ≈ 40 picks a coin flip is itself the answer (they don't care; use the default).
8. The owner's verdict on a style frame wins over the A/B ranking.

---

## 3. The tokens: `taste/taste-tokens.json`

`slop taste tokens` writes this file (and `taste/look-bible.md`, a readable suggestion with the owner questions). It is
a set of **suggestions with evidence**, not decisions: nothing in it is applied until the owner confirms it. Abridged
shape (the file itself is authoritative):

```json
{"version": 1,
 "evidence": {"taps": 152, "likes": 61, "passes": 80, "pairs": 11, "meter": 0.77, "margin": 0.08},
 "palette": {"restraint": "mono+1", "scope": "graphics only (not the footage)", "status": "measured",
             "near_mono_share": {"likes": 0.82, "passes": 0.70, "p": 0.014},
             "accent": null, "accent_candidates": ["red"], "accent_source": "ask-owner",
             "paper": "#eeede8", "ink": "#121212", "footage_grade": "native"},
 "ground": {"likes_dark": 22, "likes_light": 25, "likes_mid": 14, "status": "lead"},
 "texture": {"lean": "unclear", "apply": null, "scope": "graphics-only", "status": "ask-owner"},
 "composition": {"status": "hypothesis"},
 "type": {"lyric": null, "shortlist": [], "status": "not measured",
          "anchor": {"display_size_pct_w": 4.97, "micro_size_pct_w": 1.2, "ratio": 4.13}},
 "modes": [{"name": "spec labels", "likes": 9, "exemplars": ["<id>"]}],
 "words": {"liked": [{"phrase": "photocopy xerox texture", "auc": 0.654, "pm": 0.055}],
           "passed": [{"phrase": "colorful", "auc": 0.378, "pm": 0.054}]},
 "anti_sources": [{"source": "early-cyber", "taps": 8, "like_rate": 0.0, "p": 0.0093}],
 "references": {"top_liked": [], "longest_dwell": []},
 "open_questions": [{"id": "accent", "ask": "Which accent colour, if any?", "evidence": "…", "proposal": "…", "answer": null}]}
```

### 3.1 What each part means, and how it is computed

| Token | Meaning | Computed from | Minimum evidence | Trust |
|---|---|---|---|---|
| `palette.restraint` | how much colour the **graphics** use: `mono+1`, `limited` (≤ 3), `colourful` | share of near-monochrome likes vs passes (mean saturation < 0.12) | ≥ 60 likes; p < 0.05 or ≥ 75 % mono likes | graphics only, never footage |
| `palette.accent` | THE accent hex (null until the owner answers) | the owner's answer or brand | the owner says it | high |
| `palette.accent_candidates` | hues the likes lean to | hue histogram of coloured likes vs passes | ≥ 20 coloured likes | candidates only: ask |
| `palette.footage_grade` | `native` (default) / `clean-grade` / `print` | the owner's answer to question 2 + the style-frame verdict | the owner | high |
| `ground` | dark / light / mid split of liked grounds | luminance of liked images (dark < 0.35, light > 0.65) | — | a lead; an arc only if the owner wants one |
| `texture` | does the owner lean to grain / halftone in graphics? | phrase scores ("grainy texture", "halftone print" …) | beyond the margin | a question, never applied unasked |
| `composition` | placement tendencies | image statistics of likes vs passes | — | `hypothesis` until a frame confirms |
| `type` | the lyric face, a shortlist, the position-bias γ, the measured anchor (sizes as **% of canvas width**) | the font A/B (position-corrected) + the approved frame | ≥ 30 decisive picks; one frame verdict | `confirmed` only after a verdict |
| `modes[]` | the separate kinds of image the owner likes, with exemplars | clusters of liked images (5–8), each ≥ 8 likes, named by their nearest phrases | ≥ 8 likes per mode | a hint for references |
| `words.liked/passed` | phrases whose image match predicts likes / passes (`auc` ± `pm`) | phrase-to-image scores against taps | beyond the error margin | vocabulary only |
| `anti_sources[]` | sources the owner always passes (e.g. 0 likes of 8: p = 0.009) | ≥ 6 taps and like-rate ≤ 10 % | the statistic | becomes a banned item once the owner says yes |
| `references` | the top liked images and the longest looks | the model and dwell times | — | inspiration only, never material to copy |
| `open_questions[]` | what to ask the owner, with evidence and a proposal | the conflicts above | — | ask in one message; record answers in `DECISIONS.md` |

Where the owner's answers go: the accent, footage grade and fonts into `project.json "look"` (`accent`, `mode`,
`fonts`), the banned items into `project.json "banned"`, and every answer verbatim into `DECISIONS.md`. The owner's
Midjourney profile code goes into `project.json "mj" "profile"` and nowhere else.

**Store sizes as % of the canvas, never pixels.** The approved design was measured on a 1080 px-wide portrait; copied as
pixels onto a 1920 px frame, its 54 px coverline became 2.8 % of the width instead of 5 %.

### 3.2 The measured anchor (the one design the reference owner called good)

When the owner calls a design good, measure it and store it as the anchor. The reference owner's anchor ("001-A": a
strict editorial lockup over an archive film frame):

- Verdict: "It feels like a, I would say, like a magazine cover, except you've like gotten rid of all of the other
  parts of the magazine cover, so your eyes just go to the text … The mono, very thin font goes very well with the
  background … just a clean, well-chosen background and text."
- Display: bold neo-grotesk, **5.0 % of width**, title case, tracking −0.03 em, two lines.
- Micro: mono 400, **1.2 % of width**, caps, +0.06 em, in pairs of rows. Display:micro ≈ 4.1.
- A 1.2 px hairline (at 1080) the width of the display block between them.
- Lockup **6.1 % of the canvas**, centre at (0.24, 0.80), one left axis, nothing off-grid.
- Contrast 4.3–6.4 on a mid-grey patch.
- (The original face, Nimbus Sans, is not shipped for licence reasons; use the engine's OFL grotesk.)

---

## 4. Where taste may be applied (and where it may not)

| Downstream | Uses | Never |
|---|---|---|
| **Look** (`project.json look`) | `footage_grade` → `look.mode` (`native` / `clean-grade` / `print`); `accent` → `look.accent`; type → `look.fonts` | grade footage from reference statistics |
| **Midjourney prompts** (50-plates-midjourney) | the owner's own `--profile` code; prompt vocabulary from `words.liked`; avoid `banned`; the skeleton below | another person's profile code; bare `--p` |
| **API image prompts** (51-plates-api) | the same skeleton and vocabulary | style words that fight the owner's answers |
| **Motion design** (70-motion-design) | display/micro faces and sizes in % of canvas; accent on ≤ 2 elements per frame; unequal margins; type hung from a left axis or a feature; graphics coupled to things in frame | neon, glows, gradients as decoration, drop shadows (if confirmed banned) |
| **References for plates** | `modes[]` exemplars as inspiration for the human writing prompts | references as material to copy; references with lettering (they teach the generator to letter) |
| **Reviewers** (§6) | the owner's verbatim brief + `confirmed` rules | `hypothesis` rules as pass/fail gates |

**The prompt skeleton taste feeds (owner-liked recipe):** one long descriptive sentence = **a place + a human-scale
trace + light**; the palette written out (hex is fine); "one small <accent>-coloured light as the only warm note"; a
declared empty field for type ("the upper third empty fog"); "no text, no letters, no logos". Midjourney: the owner's
own `--profile <THEIR_PROFILE_CODE>` (never bare `--p`, which silently applies their default profiles — on the reference
account that was a profile they had rejected: "these aren't the right profile, I need v8.2 personalized"); no style
references unless the owner wants them.

---

## 5. Verdicts: `taste/verdicts.jsonl`

Every owner judgement is kept here, verbatim, forever. Verdicts on taste RULES (level `rule`) are written by
`slop taste verdict` and `slop taste apply --yes`. Verdicts on a finished thing (a style frame, a plate, a board shot,
a cut) are appended by hand: one JSON object per line (create the file on the first verdict), never rewriting or
reordering earlier lines. The format:

```json
{"t": "2026-09-30", "level": "plate", "artifact": "plates/cands/s016/2.jpg",
 "owner": {"verdict": "reject", "rank": null, "note": "its kinda bodyslop, need her as a virtual ghost or something"},
 "review": {"rubric_version": "plates-v1", "model": "<reviewer>", "order": "single",
            "scores": {"director": 6, "craft": 7}, "pass": true, "n_fixes": 2, "blocking": []}}
```

`level` ∈ `plate | frame | section | chapter | cut`; `owner.verdict` ∈ `pick | reject | accept | rank | comment`.
A note that covers many items ("looks really good up to s049") is copied onto each item it covers. The owner's 70 notes
on SP's board are the model: short, specific, and each one changed a prompt or a plate. Leave `review` out (or null)
when no reviewer scored the item; fill it when you are calibrating a reviewer (§6). Check the file still parses after
each append (one JSON object per line; `python -c "import json,sys;[json.loads(l) for l in open(sys.argv[1])]"
taste/verdicts.jsonl`).

---

## 6. Calibrating reviewers to the owner

Reviewer agents (on plates, chapters, cuts) are only useful if they say "no" where the owner would. On SP they didn't
match: 27 chapter reviews averaged a director score of **6.96 ± 0.47**; the gate was "director ≥ 8 and the rest ≥ 7"; only
**1 of 27** passed; and the owner accepted every chapter ("its perfect. change nothing."). The gate was a full point
stricter than the owner and carried no information; its fix lists were always 9–12 items (the cap), whatever the score.
EV's reviewer rubric enforced "mono plus one accent" — the very hypothesis the owner then rejected.

### 6.1 The method

1. **Log** every owner verdict with the reviewer's blind scores attached (§5).
2. **Blind re-score**: run the reviewer on every logged artefact without the owner's verdict in its context. For
   pairwise comparisons, score both orders and average (judges are order-sensitive).
3. **Check the ranking first**:
   - ranked sets: Kendall τ between the reviewer's total and the owner's order;
   - plates: the AUC of picks over rejects, **≥ 0.70** required;
   - the owner's best item must land in the reviewer's top third.
   If this fails, **fix the rubric text** (missing criteria, wrong rules) before touching any numbers.
4. **Fit weights** only where both classes exist (plates, frames): logistic regression of "owner accepts" on the
   z-scored sub-scores, ridge-shrunk toward the prior weights (director 2, others 1); keep the prior unless the fitted
   weights beat it by ≥ 0.03 AUC held-out. If two sub-scores correlate above 0.7 (director and craft did, 0.81), merge
   them.
5. **Set the threshold**:
   - with both classes: the threshold that maximises balanced accuracy;
   - with accepts only (chapters): at most the **10th percentile of accepted totals**. On SP that puts the director bar
     at **≈ 7.0**, not 8.
6. **Change what "pass" means**: pass = **no blocking fix left**. Blocking = a canon break, a lyric miss, an
   out-of-sync mouth, unreadable on a phone, a banned item. Polish fixes are applied in at most 2 rounds whatever the
   score. (This keeps what worked — concrete fixes such as "the clock reads as a flat sticker, not the clock's LED" —
   and drops a numeric bar the owner never shared.)
7. **Anchor the scale** to the owner's extremes: their best-ever item reads 9, the worst known reject reads 4:
   `s' = 4 + 5 × (s − s_worst) / (s_best − s_worst)`.
8. **Keep it as a regression test**: any change to the rubric or the reviewer model must keep τ ≥ 0.6 on ranked sets,
   AUC ≥ 0.70 on plates, and 100 % pass on accepted finals.
9. **Refit after every 10 new two-class verdicts**, and show the owner a one-line status: "the reviewer agrees with you
   on 78 % of 56 plates".

The lyric-flow score in 10-song was calibrated exactly this way: the sections the owner judged, with the verdict in
the header, kept as a file the score must rank in the owner's order.

### 6.2 Rubric hygiene

1. The reviewer's taste criteria = **the owner's verbatim brief + confirmed rules only**. Never a hypothesis.
2. Ask for blocking and polish fixes separately. Don't ask for "at most N fixes" and then read N as information.
3. **A null or empty review is a failure, not "no fixes".** (On SP a usage limit made reviews come back empty and the
   scripts read that as a pass.)
4. Reviewers render and **look** at real frames (contact sheets), never only at code or prompts.
5. A reviewer that checks a take only against its own prompt can't catch a weak prompt. Review against the **story**.

### 6.3 The 5-minute calibration a new owner can give in setup

1. Three style frames: rank them, one line why (anchors the frame level).
2. Twelve plates from their first board: pick or reject each, one line (the first two-class set).
3. The first 20–40 s rough cut: accept, or say what's wrong (anchors the cut level; catches global errors early).

Then blind-score those, run §6.1 steps 3–7, and report the agreement before production.

---

## 7. What changes per tier

| | Quick | Studio | Director |
|---|---|---|---|
| Interview | the 4 always-ask questions | full (≤ 8) | full |
| Tap feed | optional, 60 taps | 150 taps + 3 style frames | 150 now + 150 after the first project |
| Font A/B | no (engine defaults) | optional (30 decisive picks) | yes (counterbalanced) |
| Reviewer calibration | none (the owner's eye) | 12-plate set | full method + regression file |

Taste improves with use: every gate verdict is appended to `verdicts.jsonl`, and the weekly idea drop can draw on the
modes and the last project. Tell the owner the meter after each session.

---

## 8. Checklists

**Setup session**
- [ ] the 4 always-ask questions answered verbatim
- [ ] pool of ≥ 300 candidates from the owner's own sources (no crawling)
- [ ] ≥ 150 taps including 40 cold-start and 4–6 repeats; meter and repeat agreement recorded
- [ ] 3 style frames ranked; verdict appended to `verdicts.jsonl`; rules recorded with `slop taste verdict` (never by
  editing `taste-tokens.json`)
- [ ] `taste-tokens.json` written; accent from the owner; footage grade from the owner; `slop taste apply --yes` run
  after the owner said yes to the preview

**Before using taste in a project**
- [ ] footage grade and accent come from the owner's answers, not statistics
- [ ] type sizes in % of canvas; faces only from the shipped OFL set or named by the owner
- [ ] reviewer rubric = verbatim brief + confirmed rules; null review = failure

---

## 9. Common mistakes

| Mistake | What happened | Do instead |
|---|---|---|
| Grading footage from reference statistics | EV v1 "way too.. gray", 3.5 h rework | footage keeps native colour unless the owner asks |
| Choosing the accent hue from likes | red became the accent; the owner changed it to Claude orange | ask for the accent |
| Treating A/B winners as approvals | the owner disowned them | verdicts on finished pieces |
| Counting skips and ties as wins | "lighter weights win 21–13" was really 13–10, no signal | decisive picks only, report n and p |
| Ignoring position bias | 31 of 43 "unbeaten" fonts won only from the first slot | counterbalance; first-slot term; need a second-slot win |
| Reading pass rates off filtered boards | "0 passes" on every board by construction | compute only from unfiltered taps |
| Pixel tokens on a new canvas | a coverline at half its intended size | % of canvas |
| Agent-written style guides | 26 of 28 never approved | exemplars + measured tokens + verdicts |
| Crawling a reference site | breaks its terms | the owner's own channels with their token |
| A reviewer gate stricter than the owner | 1 of 27 passes, all accepted by the owner | calibrate the threshold to the owner (≈ 7) |
| A null review read as a pass | broken chapters marked "done" | null = failure |
| Another person's generator profile code | identity leak and the wrong taste | each owner's own code, in their own project only, never shared |
| Editing `taste-tokens.json` by hand to mark a rule confirmed | the next `slop taste tokens` run erased it | `slop taste verdict RULE confirmed`; then `slop taste apply` |
| Recording a sheet reply without its id while two sheets were open | the answers landed on the wrong pairs | `slop taste record --sheet ID "…"` (the id `slop taste sheet` printed) |
