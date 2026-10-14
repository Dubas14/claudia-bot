---
name: song
description: Use when making or checking the song - concept pitches, lyrics written for Suno, the Suno pack, auditioning takes, getting the WAV in, a Lyria song, the analysis and ear check, or the Suno terms talk.
---

# Song - concept, lyrics, Suno pack, take, analysis

Read docs/10-song.md §0 first. Suno has no API: Grok creates each take in its own browser (`slop relay job --kind suno`, docs/10-song.md §5); the owner only listens and picks.

1. Questions (§1): one message with the 9 questions and their defaults. Record the answers verbatim: `slop --json -p NAME decide '<answers>' --by owner`. Words they never want: `cd /workspace/slop/projects/NAME && jq '.banned=["WORD1","WORD2"]' project.json > p.tmp && mv p.tmp project.json`.
2. Concept (§2): web search for a fact bank (§2.1), then 3 pitches of at most 120 words: premise, through-line device, lead, arc, one risk (§2.3). G1: "Which one? (Default: A.) Anything to change?" Record the answer with `slop --json -p NAME decide '<their words>' --by owner`.
3. Lyrics (§3): pick a structure template (§3.2), write lyrics/lyrics.txt spelled as sung (§3.4), section tags on their own lines. `slop --json -p NAME lyrics lint` (add `--ban WORD` per banned word), fix every flagged line, lint again until it is clean (§3.7).
4. Suno pack (§4): write suno/style.txt, suno/exclude.txt, suno/lyrics-field.txt, suno/title.txt and suno/settings.md. Send them in one message with the §4.6 text, each field in its own code block so a phone copies it.
5. Rounds (§5): the owner gives a verdict per take; change one thing; next round. Log suno/takes.md. G2: the owner names the take; record it the same way.
6. Terms (§8), once per owner: commercial use needs a download on a paid plan; the clause about not powering other AI tools is ambiguous for a video pipeline, so suggest a legal read before monetising; Free plan downloads are non-commercial (offer Lyria or an upgrade). Record their answer the same way.
7. The file (§6.2): a WAV up to 25 MiB as an attachment; bigger by a Drive or Dropbox share link: `slop --json -p NAME fetch 'LINK' --to audio`. Never take audio from Suno's CDN or by recording the player. Then `slop --json -p NAME song ingest FILE` (FILE = the full path; after fetch, the `file` it printed).
8. Analysis (docs/20-analysis.md §0; needs the full install): `slop --json -p NAME job start -- analyze`, then wait by the profile's turn rule. Read analysis/report.md.
   - Ear check every flagged item (§3.2); fix a word: `slop --json -p NAME lyrics fix --word WORD_INDEX --t0 SECONDS --note '<why>'`.
   - Bars (§4.3): `slop --json -p NAME song bars`; wrong phase: `slop --json -p NAME song bars --phase PHASE`.
   - Sections (§5): `slop --json -p NAME song sections`; wrong: `slop --json -p NAME song sections --set 'SECTION@START,...'` built from its table (each name with its `--set START` value, changed where the owner says), EVERY section: it replaces all.
   - Sung choruses (§2.2): copy analysis/words.json to analysis/words-w2v.json, then `slop --json -p NAME job start -- analyze --steps align --whisper-fallback --yes` (about $0.002; say so).
9. Display text (docs/20-analysis.md §7): `slop --json -p NAME lyrics display --init` (never --force: it wipes edits), edit lyrics/display.txt as it should read on screen (AGI|3, +25%|3, the accents), then `slop --json -p NAME lyrics display` until every line consumes its words.
10. One message to the owner: the take, tempo range, the fixes and the sections. Record their yes the same way. Then skill storyboard.

## Lyria (no Suno, up to about 3 minutes, needs OpenRouter; docs/10-song.md §9)
Write suno/lyria-prompt.txt from the pack (the table in §9). Show the prompt and the price. On yes: `slop --json -p NAME gen song --prompt-file suno/lyria-prompt.txt --clip --yes` (30 s test, about $0.04), then `slop --json -p NAME gen song --prompt-file suno/lyria-prompt.txt --as-song --yes` (about $0.08; writes audio/song.wav). The owner auditions it (G2). After the analysis: `slop --json -p NAME lyrics check --yes` shows what the take really sings.
