---
name: storyboard
description: Use when making or fixing the storyboard - the board design (treatment, through-line device, chapters, hook), the draft, writing every shot and its explaining graphic, the audit, the board sheet and the owner's board approval (gate G4).
---

# Storyboard - draft, write every TODO, audit green, sheet, G4

Read docs/40-storyboard.md §0, §4 (one explaining graphic per lyric line) and §9.1 first. Before you start: the song is locked (G2), the ear check is done and the sections are confirmed.

1. Design (§2): one treatment paragraph, the through-line device, the chapter map, plants and payoffs, the hook for the first seconds (§5). Write them to board/TREATMENT.md.
2. Pace (§6.1): the project's tier sets it. `slop --json -p NAME board draft` (another pace only if the owner asks: `--pace studio`; a re-draft needs `--force`). Report its stats: shots, plates, mean shot length.
3. Write every TODO with commands, never by editing JSON (§9.1). Go section by section. The quality lives here: a concrete place, an action and its reaction, framing first.
   - One shot: `slop --json -p NAME board set SHOT --set '<the place, concrete>' --framing MS --action '<what happens, then the reaction>' --img-prompt '<framing first, then {lead}, the place, no text>'`. That is a Quick board (API stills); a Studio or Director board (Midjourney) takes `--mj-prompt` in its place. Use the field the draft left as TODO. Never write the other one: it is refused, and `--switch-generator` (moves that plate to the other generator) only when the owner asks.
   - Many shots: write board/shots.tsv with columns id, set, framing, action, prompt (`prompt` goes to the field the draft made), then `cd /workspace/slop/projects/NAME && slop --json -p NAME board fill board/shots.tsv --check`, then the same without --check.
   - Prompts: {far} in FS, WS and EWS shots, {lead} in every closer one; never paste the canon by hand. Sung shots: nothing in front of the mouth (no microphone, hand or hair). No grade or monochrome words: inputs stay in colour.
   - The explaining graphic for every lyric line (§4; docs/70-motion-design.md §5): choose the kind by what the line MEANS. A number: counter, chart, tally or gauge. A claim or a category: cv.tag, label, stamp or ui.chip. A process or a place: plot, leader, departures or sheet. Speech or tech: ui.chat, terminal or voice. A correction: strike or redact. Draw it from the thing in frame and enter on the word that names it: `slop --json -p NAME board device add SHOT --kind counter --line 3 --example --param word=thirteen`, then replace the example's on-screen text with --param (`slop --json -p NAME board device kinds --kind K` lists its params). At least 6 kinds in the film, never one kind on 3 lines in a row; callout only when nothing else fits.
   - Lead off screen: `slop --json -p NAME board set SHOT --no-lead`. Lead box on a plate without depth: `--subject-uv 0.40,0.15,0.25,0.70`.
4. `slop --json -p NAME board audit`. Fix exactly the gates it names (docs/40-storyboard.md §10 has the fix for each), and every mouth warning it lists first (a sung shot). Repeat until every gate passes. Keep its `clip_cmds` for skill clips.
5. `slop --json -p NAME board sheet`. Send the board/board-pNN.jpg pages with the §11.2 message: shots, lead share, clips and their estimate; "Flag anything by shot id."
6. Each note: record it verbatim with `slop --json -p NAME decide '<note>' --by owner`, apply every note (a later note wins), audit again.
7. The owner's yes (or the silence window they set themselves ran out): `slop --json -p NAME board approve --note '<their words>'`. While you wait, do only free work (the plate book). Any later board change: say so in one line, ask them to re-approve.

Merging shots on a dense Quick board, the lead-share rule, motion budgets: §6.1, §7, §8. Never repeat a 2.5D treatment on two shots in a row; never the same image on two shots.
