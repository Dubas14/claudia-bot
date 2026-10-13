"""slop.audio - song ingest, CPU audio analysis and lyric tools (module "audio" of ARCHITECTURE.md §5).

Commands: `slop song ingest|sections|bars`, `slop analyze`, `slop lyrics lint|check|display|fix`, `slop audio window`.
Writes (contract §3.2/§4): audio/song.wav (+ song.json), audio/stems/*.wav, analysis/beats.json, words.json, hits.json,
report.md (+ transcript.json, lyrics-display.json, spectrum.json, state.json, progress.json, last-run.json, cache/,
listen/), audio/windows/<clip>.mp3/.json.

Ported from the private pipeline (method and constants kept; see each module's docstring for its changes):
  stems.py      Demucs htdemucs separation (CPU), or imported stems (kept)  <- tools/gpu-audio/analyze.py (stems)
  align.py      wav2vec2 CTC + own Viterbi alignment (CPU)    <- tools/gpu-audio/analyze.py (alignment)
  whisper.py    Whisper word timestamps via OpenRouter        <- tools/gpu-audio/whisper_words.py (was CUDA)
  merge.py      w2v >= 0.5 else Whisper (energy onset) else interpolation <- projects/<sp>/align_merge.py
  beatmap.py    variable tempo beat map + downbeat vote       <- tools/beatmap.py + analyze.py (beats)
  sections.py   agglomerative sections + names                <- analyze.py (sections), make_timeline.py
  hits.py       kick/snare/hat, real hits, risers, fills, vocal entries, env24 <- tools/hits.py
  spectrum.py   24 fps band spectrum of vocals and mix        <- tools/spectrum.py
  display.py    "TEXT|n" display tokens -> engine LYR         <- tools/display.py
  scansion.py   Suno scansion/flow/groove model + lint        <- tools/scansion.py
  window.py     clean vocal / mix windows for clips           <- tools/prompts.py clean_window, seedance.py window_audio
  report.py     report.md + ear-check list, per-bar energy    <- make_timeline.py, PLAYBOOK ear-check rule
New here (no port): overrides.py (`slop song sections --set/--clear`, `slop song bars --phase/--method`: project.json +
  DECISIONS.md + the storyboard check: an UNTOUCHED draft - decided from its content, every lead field still a TODO,
  no device, no approval - is marked stale; a board the lead has written into is never written, the output lists the
  shots on moved section boundaries and a `board draft --out` file to compare with; `slop analyze` and `slop lyrics
  fix` run the same check when they move or rename sections), check.py (`slop lyrics check`: what the take sings vs
  the sheet, via the same cached Whisper transcription; timestamped backups), sections from lyric tags (sections.py),
  explicit clean-window tokens (window.py, `--tokens`). Bars count from 0 in every command, table and `@barK`.
Bugs fixed: fixed /tmp/*.f32 paths in beatmap (pipes now); the align-merge <-> beatmap circular dependency (neither reads
the other); scratch/*.f32 stems that nothing wrote (report reads the stems); hard-coded 128 BPM hint; CUDA-only Whisper;
digits silently dropped from the alignment sheet (now a lint error); silent default project (contract resolver);
the downbeat vote read the kick energy at ONE 5.8 ms frame on the beat (the low-passed kick peaks 17-35 ms later), which
could put every bar line a beat early (beatmap.py); the head of the beat map is re-tracked from the first locked
drums; the sections' boundary column off-by-one (sections.py).
Operator safety (a weaker model drives these): a template project runs `slop analyze` without lyrics (alignment
skipped with the next step, never minutes of CPU then an error); imported stems are never silently replaced by Demucs;
a paid Whisper re-timing is reused for free by later plain runs (cached per window, a failed run resumes); a plain
`slop analyze` never spends; progress.json + stderr heartbeats while it runs; every generated command carries
`--project`; manual timing and windows are range-checked against the song's duration.

Model / weight licences: wav2vec2-large-960h-lv60-self Apache-2.0 (1.26 GB, HF hub); Demucs code MIT, htdemucs weights
no separate licence tag (FLAGGED - stems can be imported instead with --stems-dir); Whisper large-v3 Apache-2.0 (run
by the provider through OpenRouter, paid per second, ledgered); CMU Pronouncing Dictionary BSD-2-Clause (optional,
downloaded once). No GPU, no private hosts.

Benchmark (tests/bench_audio_ev.py, the reference song "Escape Velocity", 306.4 s; WSL CPU parity env, 32 threads):
  words: 97.4 % of the 416 display tokens of the shipped lyrics.js start within 0.10 s of ours (88.9 % within 0.02 s,
    98.6 % within 0.25 s; median 0.000 s, p90 0.02 s, max 3.42 s); per sung word 97.3 % of 447 (wav2vec2 only, no
    Whisper; the alignment sheet is the shipped sung sheet, numbers spelled as sung). Target was >= 90 %. Before the
    Demucs shift was seeded, runs varied 95.9-97.4 %.
  beats: 679 of 679 shipped beats matched within 10 ms (median 0 ms); tempo 131.54 -> 133.89 BPM (shipped 131.55 ->
    133.90). Downbeats: 100 % of the shipped bars within 30 ms (phase 3, the default kick vote with the 10-50 ms
    window; the vote is split on this four-on-the-floor take - 46 % of blocks - and the report says so). The
    chord-change vote (second opinion, opt-in) says phase 1, two beats off the shipped bars.
  time (CPU, 32 threads shared with other jobs; first run also downloads htdemucs 84 MB + wav2vec2 1.26 GB): stems
    87 s, beats 22-31 s, sections 7-9 s, align 31 s (emissions 29 s + Viterbi 1.3 s), hits 14-21 s - about 3.5 min
    wall, 2.65 GB peak RSS. The 8-vCPU box: estimated 3.5-6 min (research 11-gap-3 section 3.5; not measured here).
  ear check: 45 lines need a listen (15 in-line gaps, 38 lines with words < 0.1 confidence, 3 long words), 10 more
    "if time allows"; ranked by hard problems then lowest confidence, the top 20 hold 7 of the 8 lines whose words
    are more than 0.1 s from the shipped (hand-checked) timing (time order: 5 of 8).
  synthetic 120 -> 124 BPM song (tests): downbeats 100 % within 30 ms and the drop's real hit / riser landing within
    7 ms, through the synthetic stems and through real htdemucs stems (the single-frame vote picked the wrong bar
    phase on both); its claps on 2 and 4 over the four-on-the-floor kick are kept (hits.py kick_click "auto").
Second song (same bench, `--song/--assets`; "Superpersuasion", 189.7 s, spoken verses + sung choruses + crowd shouts;
results in the project's e2e/bench/{ev,sp}-audio-bench.json):
  words, wav2vec2 only: 87.9 % of 315 display tokens within 0.10 s (81.3 % within 0.02 s, 94.0 % within 0.25 s; per
    sung word 87.0 % of 323) - BELOW the 90 % target: its sung chorus lines need the Whisper fallback. With the
    fallback fed the take's own whisper-large-v3 words (the model `--whisper-fallback` calls; replayed, free): 96.5 %
    within 0.10 s (92.1 % within 0.02 s; per word 96.0 %; 69 of 323 words re-timed by Whisper). Not independent: the
    shipped times were merged from the same Whisper words - it shows the merge reproduces the shipped pipeline.
  beats: 96.6 % of 414 shipped beats within 30 ms (95.7 % within 10 ms); tempo 129.19 -> 132.14 (shipped 132.09).
  DOWNBEAT METHOD (both songs): kick - EV 100 %, SP 97.1 % of the shipped bars within 30 ms (both phase 3 = shipped);
    harmony - SP 97.1 % but EV 0 % (two beats off); auto - same as harmony on both (the chord vote counts as
    significant on EV: 82 % of blocks, ratio 5.2). The default stays "kick"; harmony/auto are opt-in second opinions.
  sections from lyric tags vs hand-made section tables (on the kick bars, wav2vec2 words): SP 5 of 10 boundaries on
    the same bar line, 8 of 10 within one bar, 9 of 11 section kinds right; EV 7 of 7 within one bar (its table cuts a
    beat before the bar line), 7 of 8 kinds. The heuristic alone: SP 2/10 same bar, 6/10 within a bar, 2/11 kinds; EV
    0/7, 2/7, 3/8. Snap tolerance (audio.section_pickup_beats; `--pickups`, results in sections_pickups with the mean
    |offset|): 0 / 0.1 / 0.25 beats give identical starts. Larger is MIXED, not better: on EV, 1 beat lands closer to
    the storyboard chapters (mean |offset| 0.43 vs 0.57 bars - they cut a beat before the bar line) but one fewer is
    within a bar (6/7); on SP, 1 beat ties on the storyboard table (4/8/9, 1.43 vs 1.48 bars) and loses one section
    kind on the timeline table (8/11); 0.5 is equal or worse on both. 0.1 is kept (alignment jitter only).
    On the Whisper-merged SP word times the tags do worse (4 / 7 / 9: the final chorus starts 2 bars early).
    Misses: an outro that starts mid-block (no [Outro] tag; the ring-out keeps an ad-lib vocal) and an instrumental
    after a block's last word that the table starts one bar earlier.
  lyrics check on the replayed SP transcription (the take sings the sheet as written, so every proposal is a Whisper
    error): 51 lines - 36 ok, 4 spelling, 7 changed, 2 extra, 2 missing; 9 proposals, 0 LIKELY, 9 UNSURE (the
    "aligned" and "half-heard" triggers caught the one garbled line that used to stay LIKELY).
"""
