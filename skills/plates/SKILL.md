---
name: plates
description: Use when making the stills (plates) - the lead canon and test plates, the Midjourney prompt book and paste sheets, ingesting the owner's downloads, picking, varying, fixing a plate with an image edit, or API stills for the Quick tier.
---

# Plates - lead, book, Grok runs Midjourney, ingest, picks, fixes

Midjourney (Studio, Director): read docs/50-plates-midjourney.md §1 first. Grok runs the prompt blocks in its own browser and downloads every image (`slop relay job --kind midjourney`, §9); the owner only judges the picks.

## Lead first (G3)
1. Write the canon with the owner (§5.1, §5.3): framing first, visible garments, ethnicity, age, skin; plus a short far version for wide shots. `slop --json -p NAME lead --canon '<canon>' --far '<far version>'`.
2. Midjourney's switches are the owner's, asked once per project (defaults: Raw on, personalization on, HD off): `slop --json -p NAME project set mj.raw true|false` (likewise mj.personalize, mj.hd). Never a `--v` or a profile code in a prompt: Midjourney's default is its newest model, and Grok presses the P button.
3. 4 test plates of the lead (CU, MCU, FS, WS). Before a board exists: write the 4 prompts yourself (§4.9 template, the canon verbatim, the far version for FS and WS) and ask Grok for them: `slop -p NAME relay job --kind midjourney --text '<prompt>' --plate lead-cu` (a --text and a --plate per plate). Ingest each download: `slop --json -p NAME plates ingest FILE --plate lead-cu` (then lead-mcu, lead-fs, lead-ws), then `slop --json -p NAME plates sheet --plates lead-cu,lead-mcu,lead-fs,lead-ws`. Once a board exists use `slop --json -p NAME plates book --batch NAME-00-lead --only K1,K2,K3,K4` instead (`slop --json -p NAME plates status` lists the keys). "Is this the lead? Flag any wrong face." Record: `slop --json -p NAME decide '<their words>' --by owner`.

## The book (§7, §8)
4. Settings: the version stays Midjourney's default (its newest); Raw and HD are in the params, personalization is the P button (the relay job applies the owner's choices).
5. `slop --json -p NAME plates book --batch NAME-01-core --plan standard` (their plan: basic, standard, pro or mega). Read every prompt against the lint list (§7.3). Grok runs one Midjourney job per line (never a permutation block), so a book needs no paste test.
6. Show the owner plates/prompts.md (G5 when it spends money: an API batch). Then one relay job for the Midjourney lines: a `--text` per line of plates/mj/BATCH.lines.txt and its `--plate` (the keys in plates/mj/BATCH.json).

## Ingest and pick (§10)
7. Grok's downloads arrive in inbox/midjourney/ named PLATE-N.png: `slop --json -p NAME plates ingest inbox/midjourney --batch BATCH`. Unmatched images: send plates/unmatched.jpg, the owner confirms, run it again with `--map KEY=PLATE`.
8. `slop --json -p NAME plates sheet`, send the sheets, the owner replies like "hall-ms #2, hall-wide #4": `slop --json -p NAME plates pick 'hall-ms#2, hall-wide#4'`. "You pick": `slop --json -p NAME plates pick --all-first`, and they review on the board. Then check each sung shot's pick: the whole mouth, nothing in front of it (no microphone, hand or hair); else pick another.
9. `slop --json -p NAME plates vary` (one image per shot; no two clips from one start frame). Gaps: `slop --json -p NAME plates status`.

## Fix the source, never the frame (§12)
Wrong face or framing: re-prompt and re-roll. One wrong detail on a good pick: an image edit (about $0.14, the owner's yes first):
`cd /workspace/slop/projects/NAME && slop --json -p NAME gen edit plates/cands/PLATE/2.jpg plates/cands/PLATE/5.png --change '<only this, target state>' --keep '<what must not move>' --yes`, then `slop --json -p NAME plates pick PLATE 5`. Check the canon again after every edit. A declined image is never edited (docs/62-moderation.md §1).

## API stills (Quick tier, or no Midjourney; docs/51-plates-api.md §2.5, §3)
`slop --json -p NAME plates book`, then `slop --json -p NAME gen image --jobs` (a dry run with the estimate; the lead's 4 test plates first with `--only K1,K2,K3,K4`, G3). The owner reads the book and the estimate; on yes `slop --json -p NAME gate prompts --approve --note '<their words>'` and `slop --json -p NAME gen image --jobs --yes`. Identity anchor, after G3: `slop --json -p NAME plates pick PLATE K` (the approved close-up), then `slop --json -p NAME plates book --anchor PLATE` (the full book plates/prompts.md, which G5 needs) gives every lead plate's job it as reference; `gen image --jobs --missing` skips plates already made (one image: `gen image` with `--ref PLATE:K`). The owner re-picks the close-up: that `plates book --anchor PLATE` again; text canon only again: `slop --json -p NAME plates book --no-anchor`. Images from Higgsfield: `slop --json -p NAME plates ingest --url 'URL' --plate PLATE`; from GenerateImage (no key): saved as uploads/gen/PLATE/K.png, then `slop --json -p NAME plates ingest uploads/gen` (both: skill mv-quick step 7).
Named regions for devices: `slop --json -p NAME plates box PLATE --label 'a face' --uv 0.41,0.18,0.16,0.30` (§6.4).
