---
name: mv-studio
description: Use when the owner wants a Studio-tier video (their own Suno song and Midjourney stills, Seedance sung clips with measured lip sync, 30-45 turns, $50-110), when a project's tier is studio, or to find out which stage, skill and gate come next.
---

# Studio tier - the stage machine

Read docs/00-overview.md §2, §4 and §5 once per project. Stages run in order, each stage has a skill, and the owner speaks only at the gates. Needs an OpenRouter key or the Higgsfield connector (sung clips); neither: offer skill mv-quick.

Every new conversation: `slop --json -p NAME status`, then `slop --json -p NAME decide --list --last 20`, then continue at `next`. After each gate, suggest a new chat for the next stage.

## Plan files (once per project)
- PRODUCTION.md: copy the skeleton in docs/examples/production-skeleton.md into the project folder; fill the go message verbatim, the rules, the budget per pool and the stage table (docs/95-delegation.md §6). Write a change of plan there first.
- DECISIONS.md: every owner message that decides something, verbatim and dated: `slop --json -p NAME decide '<their words>' --by owner`. A changed decision: add `--supersedes '<the old one>'`; never edit old entries.

## Stages
| # | Stage | Skill | Gate, recorded with |
|---|---|---|---|
| 1 | brief + taste capture | taste | - |
| 2 | concept, 3 pitches | song | G1 concept: decide |
| 3 | lyrics, Suno pack, rounds by ear | song | G2 song: decide |
| 4 | ingest, analysis, ear check | song | - |
| 5 | lead canon + 4 test plates | plates | G3 face: decide |
| 6 | storyboard | storyboard | G4: board approve |
| 7 | Midjourney book, paste, ingest, picks | plates | G5: gate prompts |
| 8 | clip prompt book in one context | clips | G5 again for the clips |
| 9 | clips, sync, covers | clips | - |
| 10 | edit, render, scan, v1, master, 9:16 | render-and-review | G6: gate v1 |

## Rules (docs/00-overview.md §4 and §5.3)
1. Lock the song (G2) and finish the ear check before the storyboard. Stage 5 can run beside stages 2-4.
2. Spend: show the book and the estimate (generated seconds x price x 2); wait for an explicit "go". Silence never approves spend. One action over the confirm limit needs its own yes.
3. Combine gates that are ready into one message (the face sheet with the Suno pack or a song round). The board may pass on silence only if the owner set that window themselves; record it.
4. Before the full v1 show a 20-40 s excerpt (skill render-and-review step 6) to catch "too gray" early; the cheaper look first: `slop --json -p NAME job start -- render sheet --chapter 1 --review`.
5. A quality complaint: `slop --json -p NAME spend --freeze '<their words>'` before anything else.
6. Sung clips: screenplay for acting and motion, short for copy: every sung window takes the short sung form (docs/60-clips.md §4.0). Sung plates show the whole mouth, nothing in front of it (no microphone, hand or hair). Takes from a long prompt that did not copy: retake short on the same provider before any re-route. Photoreal close-ups on Higgsfield, stylized or wide on OpenRouter (§6.5). Never alter a declined image.
7. Long runs: wait by the profile's turn rule, and record them: `slop --json -p NAME runs add ID --what '<what>' --resume '<command>'` so a later conversation can resume.
8. Ping the owner between gates only for a failing paid service, a handoff (login, captcha, download) or a decision that is theirs.

Too many turns for the owner's plan, or EV-class bespoke graphics wanted: offer skill mv-director.
