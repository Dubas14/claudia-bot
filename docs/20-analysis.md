# 20 · Analysis: stems, word alignment, the ear-check, the beat map, hits, display tokens

Read this after the owner has picked the take (gate G2) and before you storyboard. Everything timed in the video (every
word on screen, every cut, every camera punch, every lip-sync window) comes from the files this stage writes. An error
here is copied into every later stage, so this stage ends with a check against the audio, not against the sheet.

**Inputs:** `audio/song.wav` (from `slop song ingest`), `lyrics/lyrics.txt` (the words exactly as sung).
**Outputs:** `audio/stems/{vocals,drums,bass,other}.wav`, `analysis/beats.json`, `analysis/words.json`,
`analysis/hits.json`, `analysis/report.md`, and `lyrics/display.txt` (what the viewer reads).

---

## 0. The stage at a glance

1. Check `lyrics/lyrics.txt` against the rules in §1 (spelled as sung, section tags on their own lines, no letterless
   lines).
2. Run `slop analyze` (one command: stems, alignment, beat map, sections, hits, report). CPU only; minutes, not hours.
   For a song with sung choruses the report will ask for a Whisper pass: copy `analysis/words.json` to
   `analysis/words-w2v.json` first, then run `slop analyze --steps align --whisper-fallback` (§2.2, §3.2; about
   $0.002).
3. Read `analysis/report.md`. Do the **ear-check** (§3) on every item in its EAR CHECK list. Fix times with
   `slop lyrics fix` where the audio says so.
4. Check the beat map's downbeat phase (§4.3). If it is wrong, set it with `slop song bars --phase K` (no re-run
   needed: it re-derives the bars, sections and hits at once).
5. Check the section names (§5) with `slop song sections`; confirm or fix them before `slop board draft`. For a
   generated song (Lyria, or a take nobody transcribed), also run `slop lyrics check` (§2.4): it shows where the take
   sings other words than the sheet.
6. Start `lyrics/display.txt` once with `slop lyrics display --init --force`, edit it (§7), then run
   `slop lyrics display`. Every line must consume exactly its sung words.
7. Record the take, tempo range, phase and the manual fixes in `DECISIONS.md` (the fixes are kept in `words.json`).

Only then start the storyboard.

---

## 1. The input sheet: `lyrics/lyrics.txt`

This file tells the aligner what words to look for. It is **not** the on-screen lyric.

1. **One line per lyric line**, in the order sung, including repeats, call-and-response answers and ad-libs you want on
   screen. The lyric lines (in file order) key everything downstream: words, display, storyboard `lines[]`. In the
   JSON files (`words.json`, `shots.json`) line numbers count from 0; in `analysis/report.md` and in
   `slop lyrics fix --line N` they count from 1 (the first lyric line is line 1). Don't mix them up.
2. **Section tags on their own lines are fine and useful** (`[Verse 1 - spoken, deadpan]`): the aligner and the display
   skip every line that starts with `[`, and `slop lyrics lint` reads them to know which lines are spoken, sung or
   chanted. Keep them.
3. **Spelled exactly as sung**: "A G I", "eighteen", "Plus twenty-five is minus seventeen", "Three a.m.", "P doom's".
   The Suno respelling is fine here too ("Dahrio"): the aligner matches sounds.
4. **Never a line without letters, never digits or symbols.** EV's sheet had a line "+25% = −17%": the aligner gave it
   no time, gave its audio to the next line, and put "Look / Shoes / off" 3.2–3.6 s early with confidence 0. Spell it.
   `slop analyze` refuses a sheet with digits or symbols (don't override it with `--allow-digits`: the digits are
   simply dropped); `slop lyrics lint --write-fixed` writes a copy with them spelled out for you to review.
5. **Trust the audio, not the Suno field.** If the take sings two "(It's so over?)" where the field had three, the sheet
   says two. If Suno dropped a word ("Nobody built me" without "If"), drop it here.
6. How the aligner counts words: a word is a run of letters, digits and apostrophes. Hyphens, dots and other punctuation
   split words: "twenty-five" is 2 words, "a.m." is 2, "doom's" is 1, "Cyber-psychosis" is 2. `display.txt` counts the
   same way (§7).

---

## 2. What `slop analyze` does (and why each step exists)

### 2.1 Stems (htdemucs, on CPU)

- Splits the master into **vocals, drums, bass, other** (the `htdemucs` model, 4 stems).
- Cost: about 64 s of compute for a 5-minute song on 8 CPU threads; expect 2–3 minutes on the bot's computer. Peak
  memory ≈ 2.7 GB. Weights ≈ 84 MB.
- What each stem is for:

| Stem | Used for |
|---|---|
| vocals | word alignment, Whisper fallback, clean lip-sync windows (`slop audio window`), the lip-sync check, vocal entries |
| drums | the beat map (onsets), kicks / snares / hats, fills, impacts |
| bass | impacts (drops), risers, section energy |
| other | risers (synth swells), section energy, harmony changes |

- Licence note: the separation code is MIT; the published weights carry no explicit licence tag. This is flagged in the
  toolkit's licence notes; tell the owner if they ask about monetisation.

### 2.2 Word alignment (wav2vec2 + Viterbi; Whisper fallback)

1. **Forced alignment of the known lyric** to the vocal stem: a wav2vec2 CTC model (`facebook/wav2vec2-large-960h-lv60-self`,
   Apache-2.0) gives per-character probabilities every 20 ms; a Viterbi pass walks the lyric's characters through them.
   Each word gets `t0`, `t1` and a confidence (`conf`: the mean probability over its frames, 0–1).
   - About 35–40 s on CPU for a whole song.
   - Measured on EV: re-running it on CPU reproduced the shipped word times **exactly for 78.6 % of words and within
     0.10 s for 92.5 %** (median error 0.000 s). The target for a new song is **≥ 90 % within 0.10 s**.
   - Speech aligns well; **singing aligns worse**. EV mean confidence 0.64 (64 % of words ≥ 0.5); SP 0.75.
2. **Whisper word timestamps for the words wav2vec2 is unsure of** (sung lines, shouts). This is opt-in:
   `slop analyze --steps align --whisper-fallback` (needs `OPENROUTER_API_KEY`; about $0.002 a song, ledgered). The
   vocal stem goes in short windows to OpenRouter's transcription endpoint (default `openai/whisper-large-v3`) with word
   timestamps. Whisper hears sung words much better (text match 92.5 % vs 72 % for a small local model), but it
   **starts words early**: measured mean error −0.33 s, median |error| 0.28 s.
3. **The merge rule, per word, in this order:**
   1. wav2vec2 `conf ≥ 0.5` → keep it (`src: "w2v"`).
   2. else, if the word matches a Whisper word → Whisper's `t1`, and a corrected `t0`: for words longer than 0.45 s,
      move `t0` forward to the first 10 ms frame where the vocal energy passes 0.3 × the word's peak energy (but if
      wav2vec2's own `t0` falls inside the word, use that) (`src: "whisper"`).
   3. else, if it sits between two placed words of the same line → an even share of the gap (`src: "interp"`).
   4. else it stays unplaced and goes on the ear-check list.
4. **Matching Whisper's words to the sheet:** sequence matching. Two kinds of difference are handled automatically:
   digits are spelled out ("10" → "ten"), and a heard word that equals 2–4 consecutive sheet words is split into them
   ("AGI" → "A G I", "cyberpsychosis" → "cyber psychosis"; two heard pieces that join into one sheet word are joined).
   Equal-length mismatches are then paired one to one. **Names and brands are not automatic**: a respelled name ("Dario"
   heard for the sheet's "Dahrio") or a misheard brand ("clod" for "Claude") must go in `project.json` as
   `"audio": {"whisper_map": {"<heard>": ["<sheet>", "<words>"]}}`, e.g. `{"dario": ["dahrio"], "clod": ["claude"]}`;
   then re-run `slop analyze --steps align --whisper-fallback` (the Whisper result is cached, so it costs nothing).
5. **Things neither aligner hears**: a crowd shout buried in the mix, a whispered word under a loud bar. SP placed chorus
   2's shouts by copying chorus 1's beat positions forward by the bar offset. Do the same by hand: work out the time from
   the earlier chorus plus the bar offset (`downbeats[]` in `beats.json`), set it with
   `slop lyrics fix --word I --t0 S --t1 S --note "copied from chorus 1 + N bars"`, and list it under **Manual fixes**
   in `DECISIONS.md`. (A shout that is not on the sheet at all goes in `lyrics/adlibs.json` instead, §7.3.)

`analysis/words.json` (contract):

```json
{"words": [{"i": 0, "w": "ladies", "line": 0, "t0": 9.32, "t1": 9.64, "conf": 0.91, "src": "w2v"}],
 "lines": [{"line": 0, "text": "Ladies. Gentlemen. Agents.", "t0": 9.32, "t1": 10.72}],
 "gaps":  [{"t0": 18.8, "t1": 26.3, "after_word": 12}]}
```

`src` is one of `w2v | whisper | interp | manual`.

### 2.3 The rest

`slop analyze` also writes the beat map (§4), the sections (§5), the hits (§6) and `analysis/report.md` (§8).

---

### 2.4 `slop lyrics check`: what the take really sings

Lyria and Suno takes change words (a repeated line sung differently, a dropped "the", an extra "yeah", a whole ad-lib
line). The aligner forces the SHEET onto the audio, so a changed word lands somewhere wrong and nothing says so.
`slop --project my-song lyrics check` transcribes the vocal stem with Whisper (about $0.002 a song, ledgered; free when
`slop analyze --whisper-fallback` or an earlier check already transcribed this stem) and compares it with the sheet,
line by line:

| Status | Means | Do |
|---|---|---|
| `ok` | every sheet word heard | nothing |
| `spelling` | heard words that sound like the sheet's (a name, a letter sung by name) | nothing: the sheet already has the words as sung |
| `changed` / `extra` | other or more words heard: a proposed line, marked LIKELY or UNSURE | play the line to the owner |
| `missing` | sheet words not heard while the rest of the line was | listen first |
| `not-heard` | nothing of the line heard (shouts and whispers are often missed) | listen before changing anything |

A proposal is UNSURE when Whisper is the likely culprit: a shouted line in capitals, a line heard as written elsewhere
in the song, only small words differ, a spelled-out letter, an echo of the words just sung, words wav2vec2 already
placed with good confidence (`aligned`), or a garbled near-miss (`half-heard`). Extra vocals between lines are listed
too (an ad-lib: `lyrics/adlibs.json`; a missing line: add it to the sheet). Show the proposals to the owner, then:

1. `slop --project my-song lyrics check --write` writes `lyrics/lyrics.proposed.txt` (the LIKELY ones; the sheet is
   untouched) for the owner to read, or
2. `slop --project my-song lyrics check --apply` applies the LIKELY ones, or
   `slop --project my-song lyrics check --apply-lines 14,25` applies exactly the lines the owner confirmed (any
   confidence). Each apply first keeps the old sheet as a NEW `lyrics/lyrics.txt.<time>.bak` and names it.
3. `slop --project my-song analyze --steps align` re-aligns on the corrected sheet.

Never apply a proposal the owner has not heard: Whisper mishears shouted and sung words often (on SP's take every one
of the 9 proposals was a Whisper error).

## 3. The ear-check (alignment verified against the audio)

The lyric gate later (`slop render lyrics`, §9) only proves that each word is *drawn* at its own `t0`. It does
**not** prove that `t0` is when the word is sung. A word 3 s early passes the gate. On EV, "Look" was aligned 2.6 s
early onto a delay throw: it passed the global lyric gate, and it was caught only because one chapter's own lyric
check (that chapter drew by its own times) failed. The ear-check is the only thing that checks alignment against the
audio.

### 3.1 What gets flagged (the report's EAR CHECK list, in this order)

`slop analyze` writes these items into the EAR CHECK section of `analysis/report.md`, most urgent first (the same
order as the table):

| Kind | Threshold | What it usually means |
|---|---|---|
| `letters` | a sheet line with no letters | the sheet is wrong (§1 rule 4): fix `lyrics.txt`, re-run the align step |
| `missing` | a word or a line with no time | neither aligner placed it: must fix |
| `order` | a word starts more than 0.05 s before the previous word | an alignment slip: must fix |
| `gap` | > 1 s between two words of the same line | a word placed on an echo, a delay throw, or the wrong repeat (EV's "Look") |
| `verylow` | a wav2vec2 word with `conf < 0.1` | **the flag that matters most**: on EV's take, 11 of the 12 words that were really off carried it. Check every one |
| `length` | a word longer than 1.2 s (manual words are exempt) | it swallowed a pause, a held note, or a neighbour's slot |
| `lowconf` | any other word with `conf < 0.5`, or timed by Whisper or interpolation (± 0.2 s) | usually a sung or shouted word that is right; check if time allows |

`verylow` and `lowconf` items are grouped per line (one item lists that line's flagged words). Two flags you may expect
are deliberately **not** raised: "a word on near-silence in the vocal stem" and "a word shorter than 40 ms". They were
calibrated on EV's take against its hand-checked timing and **every word they flagged was correct**, so they were
dropped. A quiet or very short word is not evidence of an error.

Also check by hand: the first word of a line after a long instrumental (aligners often start it early on a breath or a
riser), and every word placed by copying another chorus's positions.

Each item in the report comes with a **listen** command (`slop --project <name> audio window chk-l<N> --t0 … --t1 …
--mode mix --listen`, which writes `analysis/listen/chk-l<N>.mp3`, never into `audio/windows/`, the clip-window folder)
and a **fix** command (`slop --project <name> lyrics fix …`). Items are grouped per lyric line and ranked: hard problems
(letters, missing, order) first, then the lowest confidence; the top 20 lines are the ones to listen to first.

### 3.2 How to check a flagged item (a model can't listen, so weigh the signals in this order)

For each flagged item:

1. **The flag itself.** `letters`, `missing` and `order` are always wrong: fix them. A `gap` inside a line is wrong more
   often than not (an echo or a delay throw took the word). `verylow` words are the ones most likely to be off. A
   `lowconf` word alone is usually right.
2. **A second aligner.** If the report says "Re-time them with Whisper first" (low-confidence words, and no Whisper
   pass yet in `analysis/words.json`): copy `analysis/words.json` to `analysis/words-w2v.json`, then run
   `slop analyze --steps align --whisper-fallback` once for the whole song (OpenRouter, about $0.002, ledgered and
   cached, so a re-run never pays twice). Every word under `conf 0.5` that Whisper heard now carries Whisper's time
   (with the energy-onset correction, §2.2) and `src: "whisper"`. For each word that was flagged before, compare its
   old and new `t0`: **within ≈ 0.3 s, the two aligners agree: keep it**; further apart, the next signal decides.
   Don't transcribe slices yourself with other API calls: that is unledgered spend, and this command already does the
   comparison for the whole song.
3. **Neighbours and repeats.** Is this the second of two identical lines (a chorus repeat, an echo)? Pick the occurrence
   whose time sits inside its line's span. SP fixes of this kind: the first "Superpersuasion" vs its echo 6 s later; a
   quiet first "Tighter" vs the loud one; an a cappella line vs its repeat. Does the word sit after its line's previous
   word and before its next one, with gaps that match the delivery (spoken words ≈ 0.3 s apart, no 1 s hole)?
4. **Vocal energy (a weak signal).** The report's per-bar stem energy and its "no vocal for 2 s or more" list, or a
   10 ms RMS of `audio/stems/vocals.wav`, show where the voice is. Use energy only to choose between two candidate times
   that the signals above already proposed (the original is usually louder than its echo). **A low-energy start alone
   never justifies a move**: when EV's flags were calibrated, every word that sat on near-silence in the vocal stem
   was correct.

Decide one of:

- **Keep** (the signals agree).
- **Move** the word: `slop lyrics fix --word I --t0 S --t1 S --note "<evidence>"` (I = the 0-based word index the
  report shows), or a whole line: `slop lyrics fix --line N --shift S` (N counts from 1; S in seconds, + later). The
  word becomes `src: "manual"`, the note is kept in `words.json`, and later `slop analyze` runs keep it. Also add a row
  to the **Manual fixes** list in `DECISIONS.md` (word, old time, new time, the evidence).
- **Ask the owner.** Only for what these signals can't settle. Batch at most 5 per song into one message: a 10–20 s
  preview of each spot with the words on screen at their times (render just that range with
  `slop render frames --from <s> --to <s>`, then `slop render encode --draft`), and the question "do the words appear
  when she sings them? Say ok, early or late for each". Approving is one word for them.

### 3.3 Rules

1. Fix the **sheet** if the take sings something different; fix the **times** if the take sings the sheet. Never edit
   the audio to match the sheet.
2. Manual fixes must survive re-runs (`slop lyrics fix` marks them so). After any re-run, spot-check that they are
   still applied.
3. Do the ear-check **before** the storyboard. Shot times and lip-sync windows are cut from word times.
4. Per take: a new take (or an edited export) means a new ear-check. SP's merge needed about 15 lines of judgement per
   take; they cannot be automated away.

---

## 4. The beat map (never one BPM)

### 4.1 Why

Suno songs drift in tempo like live music. EV accelerated from 131.5 to 133.9 BPM over 5 minutes; SP drifted from
129.2 to 132.1 BPM over 103 bars (a bar lasting 1.80–1.86 s). A single-period fit gave EV 133.84 BPM: by the end of the
song a grid at one BPM is more than a beat off. **Nothing in the pipeline ever uses a fixed BPM.** Cuts, camera moves,
counters and flashes read the beat list.

### 4.2 How it is built

1. Onset strength ("flux") of the drum stem.
2. **Local tempo fits on 20 s windows every 5 s** (BPM in 0.05 steps, phase in 4 ms steps, inside a tempo range); the
   weakest 20 % of windows (breakdowns) are discarded.
3. The tempo curve is smoothed, then beats are stepped along it and each beat is **snapped to a real drum onset within
   ±30 ms**.
4. **Downbeat phase**: which of every 4 beats is beat 1. Two votes, each taken per 32-beat block:
   - the **kick vote**: the beat phase with the most kick energy;
   - the **chord-change vote**: the beat phase where the harmony (chroma of the "other" and bass stems) changes most.

   The chord-change vote wins when it is significant (its phase holds at least half the blocks and changes ≥ 1.5× more
   than the other phases); otherwise the kick vote decides. On EV the kick vote was split (its phase held only 36 % of
   the blocks) while the chord vote held 77 %, and 27 of 36 energy jumps (drops, entries) fell on the chord phase.
   `slop song bars --phase K` (stored as `project.json "audio": {"downbeat_phase": K}`) overrides both (§4.3).
   `beats.json` records the result: `downbeat_phase`, `downbeat_method` (`harmony`, `kick` or `project.json`) and
   `downbeat_votes` (each vote's phase and per-block list); `analysis/report.md` prints both votes, and a `note` when the
   chosen phase differs from the kick vote.

`analysis/beats.json` (contract):

```json
{"duration": 306.4, "beats": [0.452, 0.908], "downbeats": [0.452, 2.276],
 "tempo": [{"t": 0.0, "bpm": 131.55}, {"t": 5.0, "bpm": 131.6}],
 "sections": [{"name": "intro", "t0": 0.0, "t1": 18.96, "energy": 0.31}], "source": "beatmap-v1"}
```

### 4.3 Checking the downbeat phase (do this every time)

Either vote can pick the wrong beat as "1". SP's final take had claps on beats 2 and 4 and harmony changes on beat 3 of
the kick vote's count: the kick vote said phase 1, the truth was phase 3, and it had to be overridden by hand (the
chord-change vote now automates the cue that override was set from). Read the "Beat map" lines of the report first: the chosen phase, the
method, and both votes' per-block phases. If the two votes disagree, or the winning phase holds few blocks, check by
the events below.

1. List the big events: section starts, the first word of each verse, the impacts in `hits.json`, the chorus entries.
2. For each, find its position in the bar (beat 1–4) on the current beat map.
3. **If most of them fall on the same beat that is not beat 1, the phase is wrong.** Set it with
   `slop --project my-song song bars --phase K` (K = 0–3, which of every four beats starts bar 0; `slop song bars` alone
   prints the current phase, each phase's first bar line and both votes). It writes `project.json "audio":
   {"downbeat_phase": K}`, re-derives the bars at once (no audio re-analysis), rebuilds the sections and `hits.json`,
   rewrites the report and logs `DECISIONS.md`. `--phase auto` goes back to the vote. Do not hand-edit the key: that
   skips the log and costs a full beat-map rebuild. **Bars count from 0 everywhere**: bar 0 starts at the first bar
   line, bar k at `downbeats[k]`.
4. Also check: kicks heavy on 1 and 3, claps or snares on 2 and 4; harmony (the "other" stem's energy steps) changes on 1.
5. If the tempo search locks onto half or double time, pin it in `project.json` with
   `"audio": {"tempo_range": [129, 136]}` (EV's range) or a `"bpm_hint"`.

### 4.4 What reads it

The storyboard puts every cut on `beats[]` (§ audits in 40-storyboard: within 0.03 s), the engine animates on
beat-relative time (beat number, bar, eighths), and the lip-sync cut lands on the last eighth note before a divergence.

---

## 5. Sections and the timed sheet

1. **Per-bar stem energy**: each stem's RMS per bar, scaled 0–9 against its loudest bar. Read it like a score: where
   the drums drop out, where the bass returns, where everything is loudest.
2. **Section boundaries** come from segmenting the song's harmony and timbre, snapped to downbeats, and are named
   automatically: no vocals before the first sung part → `intro`, after the last → `outro`, otherwise `break`; loud sung
   parts → `chorus1`, `chorus2` …; the rest → `verse1`, `verse2` …. Compare them with the per-bar energy table and the
   lyric's section tags. `slop --project my-song song sections` prints every section, where its name came from (a lyric
   tag, the owner, or a GUESS from energy and vocals, marked unconfirmed) and its `NAME@START` form. The board paces
   shots and plans clips by these names, so confirm them **before** `slop board draft`:
   - **A tagged sheet with one guessed stretch** (usually a stretch with no vocals): do not use `--set`. Add an empty
     tag line such as `[Instrumental]` in `lyrics/lyrics.txt` right after the lyric line it follows (the report names
     the line), then `slop --project my-song analyze --steps sections`.
   - **An untagged lyric line**: put a tag line (`[Verse 2]`, `[Chorus]`) above it, then re-run the sections step.
   - **A full override**: `slop --project my-song song sections --set "intro@0,verse1@bar8,chorus1@line9,outro@bar94"`
     (that is the FORMAT only: list YOUR song's sections from the plain command). **`--set` replaces ALL sections, the
     tagged ones too**, so list every one. START is `0`, seconds (`40.4` or `1:02.5`, snapped to the nearest bar line
     and the snap printed), `barK` (from 0) or `lineN` (lyric line N's first word, snapped to the bar line at or before
     it). Each section ends where the next begins; a list that does not start at 0 gets an `intro` at 0 (or `intro0`
     when your list already has an intro). `slop --project my-song song sections --clear` drops the override.

   Every change rebuilds the sections, rewrites the report, logs `DECISIONS.md` and checks the storyboard: an
   untouched draft (every shot still TODO, nothing written, not approved) is marked stale and the fix is
   `slop --project my-song board draft --force`; a board the lead has written into is **never** changed: the output
   lists the shots on a moved section boundary and gives a `board draft --out …/board/shots.redraft.json` command to
   draft a separate file to compare with, then `board set` / `board audit` (an approved board needs the owner again).
3. **Pickup rule:** a line that starts less than 0.8 s before a section's first downbeat belongs to that section.
4. **Vocal gaps of 2 s or more** are listed: they are where instrumental shots, title cards and pure motion design go.
5. Write one line per section describing what the track does (SP's: "the beat stops after 'it sucks' before 'send me
   more'"; "the bass drops out for most of Verse 3 and comes back on 'Chrome in your blood'"). The storyboard's camera
   decisions come from these lines.

SP's final take, as an example of the table you should end up with:

| Section | Bars | What the track does |
|---|---|---|
| Intro | –4 | spoken line over near-silence, a synth swell, an a cappella line |
| Intro: the beat drops | 5–7 | four on the floor |
| Verse 1 | 8–20 | thin drums, then a real hit |
| Chorus 1 | 21–30 | a cappella bar, full from the hit, shouts |
| Verse 2 | 31–46 | bouncy; the beat stops in bar 35 and returns on a hit |
| Chorus 2 | 47–55 | as chorus 1 |
| Instrumental | 56–59 | four bars |
| Verse 3 | 60–76 | bass out, a swell, a quiet stall, bass back on a hit |
| Break | 77–84 | bass hit, synths over a half-weight kick, stacked shouts |
| Final chorus | 85–93 | a cappella bar, full from the hit, the loudest bar |
| Outro | 94– | loud hit, "Tighter.", a stop, a last hit |

---

## 6. Hits: the sound events the camera plays

The beat map says *when the beats are*; `analysis/hits.json` says *what you hear*. The owner's bar for SP: "editing and
camera should feel really synced to the beat or sound effects … cuts and flashing on beat, should be in theme … dont need
to force flashing". A camera move must answer a sound you can hear; no punches where the drums are out.

| Field | How it is found | SP count |
|---|---|---|
| `kick` | onsets in the drum stem, 30–150 Hz | 367 |
| `snare` | onsets 150 Hz–5 kHz, **minus anything within 45 ms of a kick** (a broadband kick fires in every band) | 191 (mostly the off-beat clap) |
| `hat` | onsets 6–16 kHz, minus kick-coincident ones | 256 |
| `hits` (impacts) | a jump of the next 0.6 s over the previous 1.5 s in the mix, drum or bass envelope (score = max(mix, 0.9 × drums, 0.7 × bass) ≥ 0.22), snapped to a downbeat within 0.65 s, merged within 2 s | 18 |
| `risers` | the "other" and bass stems rising for ≥ 1 s, with the hit each one lands on (`land`) | 20 |
| `fills` | the beat before a real hit, and bars whose last half breaks the pattern | 18 |
| `vocal_entries` | where the vocal stem comes back after silence | 25 |
| `env24` | 24 fps envelopes (0–1) of drums, vocals, bass | — |

`analysis/hits.json` (contract): `{"kick": [], "snare": [], "hat": [], "hits": [{"t", "score"}], "risers": [{"t0",
"t1", "land"}], "fills": [{"t0", "t1"}], "vocal_entries": [], "env24": {"drums": [], "vocals": [], "bass": []}}`.

**Fixing hits:** the detector misses a hit that grows out of an already loud passage (SP's loudest bar). Add or drop
hits in `project.json` as `"audio": {"hits": {"add": [[170.7, 0.8]], "drop": []}}` (time in seconds, strength 0–1)
and re-run `slop analyze --steps hits`. Check every listed impact against the per-bar energy table; an impact in a
quiet bar is false.

**How the storyboard uses them:** hard cuts on beats by default, on impacts at section changes; camera pushes ride a
riser into its `land` hit; punches on kicks only where the drums play; stillness where the song breathes.

---

## 7. Display tokens: `lyrics/display.txt`

What the viewer reads is often not what is sung. The display is the joke; the sung sheet is the phonetics. EV: the
sung "plus twenty-five is minus seventeen" reads on screen as `+25% = −17%`.

### 7.1 Format

One line per lyric line, same order and count as `lyrics/lyrics.txt`. A line is a list of tokens separated by spaces.
A token is `TEXT|n`: show TEXT for the next **n sung words**, from the first one's `t0` to the last one's `t1`.

1. `n` defaults to 1 for a token that has a letter or digit, so plain words need no `|n`.
2. `|0` = a token that consumes no sung word; it rides on the next token's time (units, labels).
3. **Each line must consume exactly its sung words.** If not, the export fails with "line N: display consumes k of M
   sung words". That failure is the structural check that the sheet and the display agree.
4. Style marks: `*accent*` (the accent colour), `~strike~` (struck through), `_mono_` (the mono face). Use them only
   where the joke needs them (EV: `~Stop~ ~hiring~ ~humans?~ Retired. Sorry. Encore.`).
5. **Start the file from the sheet:** `slop -p <name> lyrics display --init --force`. It writes one line per lyric line
   (plain words) for you to edit, and folds runs of spaced capitals into one token ("A G I era" → "AGI|3 era").
   `--force` is needed in every project made by `slop new`: the template already contains a `display.txt` that holds
   only `[…]` comment lines, so `--init` alone refuses (the error says "display.txt has 0 lyric lines"). `--force`
   overwrites the file, so run it once, before you edit. The command writes the file and then validates it, so it can
   end with an error even though the file was written: the starter keeps a hyphenated or dotted word as one token, but
   the sheet counts "twenty-five" and "a.m." as two sung words each ("display consumes 5 of 6 sung words"). That is
   your first edit: give such tokens their count (`twenty-five|2`), or write the display form straight away (`+25%|3`
   for "Plus twenty-five", §7.2). Afterwards run plain
   `slop lyrics display`, which validates every line and, after `slop analyze`, writes the timed tokens
   (`analysis/lyrics-display.json`) that the engine export reads.

### 7.2 Examples (sung line → display line)

Each pair is one line of `lyrics.txt` and the matching line of `display.txt`, verbatim from EV and SP:

```
lyrics.txt:  Look one. A G I era. Not unreasonable.
display.txt: Look|1 01.|1 AGI|3 era. Not unreasonable.
             (the acronym reads as one word: AGI shows for the three sung letters)

lyrics.txt:  Plus twenty-five is minus seventeen.
display.txt: +25%|3 =|1 −17%|2
             ("twenty-five" is two sung words, so "+25%" consumes three)

lyrics.txt:  Look four. Shoes off in North Beach. Sixty billion at the door.
display.txt: Look|1 04.|1 Shoes off in North Beach. $60B|2 at the door.
             (the number is the joke)

lyrics.txt:  Escape velocity: eleven point two.
display.txt: Escape velocity: 11.2|3 KM/S.|0
             (a unit with no sung word rides along with |0)

lyrics.txt:  Slash loop: make me happier.
display.txt: /loop|2 make me happier.

lyrics.txt:  Permanent underclass: three. Two. One. Zero.
display.txt: Permanent underclass: 3.|1 2.|1 1.|1 0.|1

lyrics.txt:  You don't sleep. Three a.m., P doom's at ten,
display.txt: You don't sleep. 3|1 a.m.,|2 P(doom)'s|2 at 10%|1
             ("a.m." and "P doom's" are two sung words each)

lyrics.txt:  Dahrio said to slow it down. Elon said he's right.
display.txt: Dario said to slow it down. Elon said he's right.
             (the Suno respelling never reaches the screen)

lyrics.txt:  Chrome in your blood. Cyber-psychosis.
display.txt: Chrome in your blood. Cyberpsychosis.|2
             (one display word for two sung words)
```

### 7.3 Rules

1. Display tokens read as the meaning: AGI, not A G I; numerals and symbols where they are the joke.
2. Real names spelled correctly on screen whatever Suno needed.
3. Ad-libs and repeats you want on screen are normally lines in `lyrics.txt` (then aligned) and in `display.txt`. Every
   sung word on screen is the rule; a heard ad-lib left off is a choice, recorded in `analysis/report.md`.
4. **Sung words that are not on the sheet** (a backing shout under the lead, an ad-lib the aligner can't place) go in
   `lyrics/adlibs.json`, timed by your ear-check rather than the aligner. Each entry is one on-screen ad-lib:
   `[{"text": "SO BACK", "t0": 98.2, "t1": 99.1, "each": [98.2, 98.65]}]`. Its words appear at the `each` times (one time
   per word; without `each` they are spread evenly over `t0`–`t1`), each held 0.4 s, in the ad-lib style.
   `"kind": "zeros"` draws an accent "0" at every time in `each` (a chanted count of zeros). `slop lyrics display`
   merges them into `analysis/lyrics-display.json`. Note each entry's times and evidence in `DECISIONS.md`.
5. After editing `display.txt` or `adlibs.json`, run `slop lyrics display` and fix any count error before going on;
   `slop edit export` then carries the tokens into the engine.

---

## 8. `analysis/report.md` (what it must contain)

1. The take: file, duration, sample rate, loudness.
2. Tempo: start and end BPM, the drift, the tempo range used, the downbeat phase (and whether it was overridden).
3. Sections table (name, bars, start, end, what the track does).
4. Lines table: line number, start, end, bar, a confidence label per line, text. The labels: `w2v` (forced
   alignment, every word ≥ 0.5, ± 0.05 s), `w2v-low` (forced alignment with some words < 0.5), `sung` (timed by
   Whisper, ± 0.2 s), `w2v+sung` (mixed), `check` (some words interpolated or unplaced), `manual` (every word fixed by
   hand) and `missing` (a word with no time).
5. Vocal gaps of 2 s or more.
6. Hits summary (counts; the list of impacts with times).
7. **The EAR CHECK list** (§3.1), with a listen and a fix command per item.
8. Alignment health: % of words from `w2v`, mean confidence, number unplaced.

`slop analyze` writes these sections itself (read its EAR CHECK first). You add the outcomes: what you kept, what you
moved (also in `DECISIONS.md`), and anything you sent to the owner.

---

## 9. The lyric gate: what it means and what it doesn't

`slop render lyrics` (run before every render) samples each display token a little after its `t0` and checks the
engine actually drew it. It prints `N/N tokens on screen at their time` (EV 417/417; SP 315/315).

- **It proves:** every token is drawn at the time in the lyric data (nothing missing, nothing late in the engine).
- **It does not prove:** that the time in the lyric data is when the word is sung. That is the ear-check (§3).
- A render with fewer than N/N is never delivered. Fix the chapter or the export, not the gate.

---

## 10. A new take or an edited export

1. Archive the old analysis (`analysis/<old-take>/`), never delete it: the approved board is keyed to it.
2. Re-run `slop analyze` on the new master, then the whole of this doc again: ear-check, phase, sections, display.
3. If the shape changed (an instrumental added or removed, the first line moved), the storyboard needs restructuring by
   hand, not just re-timing.
4. If only a word was re-sung after the cut, use a time map instead (10-song §7).

---

## 11. Checklists

**Before `slop analyze`**
- [ ] `lyrics.txt`: sung words, tags on their own lines, spelled as sung, no digits or symbols, no line without
  letters, repeats and ad-libs included

**After `slop analyze`**
- [ ] ≥ 90 % of words from `w2v` or verified; mean confidence noted
- [ ] every EAR CHECK item resolved (keep / move with `slop lyrics fix` / owner), manual fixes noted in `DECISIONS.md`;
  every `verylow` word looked at
- [ ] names and brands Whisper mishears are in `audio.whisper_map`
- [ ] downbeat phase checked against section starts and impacts (both votes read in the report); fixed with
  `slop song bars --phase K`, never by hand
- [ ] sections named after the lyric's tags (`slop song sections` shows no GUESS left), each with a "what the track
  does" line
- [ ] a generated song: `slop lyrics check` run, every proposal heard by the owner before it is applied
- [ ] impacts checked against the energy table; missing hits added
- [ ] `display.txt` started with `--init --force`, then edited: same line count as `lyrics.txt`; every line consumes
  exactly its sung words; real spellings; off-sheet ad-libs in `lyrics/adlibs.json`

---

## 12. Common mistakes

| Mistake | What happened | Do instead |
|---|---|---|
| Cutting on a fixed BPM | cuts drift more than a beat by the end of a 5-minute song | always the beat list |
| Trusting the lyric gate for alignment | a word 2.6 s early passed | the ear-check |
| A line of symbols in the sheet | 3.6 s alignment error on the next line | spell it as sung |
| Section directions written inside a lyric line | the directions aligned as sung words | tags on their own lines, starting with `[` |
| Taking Whisper's start times raw | words appear ≈ 0.3 s early | energy-onset correction |
| Picking the echo of a word | the word appears on the delay throw | choose the occurrence inside its line |
| Not checking the downbeat phase | every "downbeat" cut lands on beat 3 | check against section starts; `slop song bars --phase K` |
| `song sections --set` with only the section to fix | every other section (the tagged ones too) was dropped | list every section, or confirm one guessed stretch with a tag line |
| Applying every `lyrics check` proposal | a Whisper mishearing replaced the real words | play each line to the owner; `--apply-lines` for the confirmed ones |
| Ignoring a missed impact | the biggest moment has no camera hit | add it in `project.json` |
| Editing the board before the ear-check | windows cut on wrong word times | ear-check first |
| Display text with Suno respellings | "Dahrio" on screen | display keeps the real spelling |
| Deleting the old analysis after a new export | the approved board can't be time-mapped | archive it |
| Mixing 0-based and 1-based line numbers | the fix lands on the wrong line | JSON counts from 0; the report and `--line` from 1 |
| `slop lyrics display --init` on a project from `slop new` | "display.txt has 0 lyric lines": the template file already exists | `--init --force` once, before editing |
| Moving a word because the vocal stem is quiet there | a correct word moved off its sound | energy is a weak signal; on EV every "near-silence" word was right |
| Skipping the `verylow` items | the words most likely to be off stay off | check every `verylow` word (11 of EV's 12 real errors) |
| Fixing a name mismatch by editing the sheet | the sheet no longer says what was sung | `audio.whisper_map` in `project.json` |
