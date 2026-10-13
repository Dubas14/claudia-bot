---
name: render-and-review
description: Use when building the edit and delivering - the EDL, engine export, look, layer check, the safety and canon scan, the lyric gate, the excerpt, frames, the review copy and v1 approval (gate G6), the master and flash check, the 9:16 cut, the chat copy and the posting copy with the AI label.
---

# Render, review, deliver

Read docs/80-review-qa.md §11 (the final QA order) and docs/90-master-publish.md §1 and §2 first. Long steps are jobs (`slop --json -p NAME job start -- render frames` prints an ID): wait by the profile's turn rule. A 5-minute song: frames 15-30 min, the 9:16 cut as long; record those with `slop --json -p NAME runs add ID --kind render --what '<step>'` so a new chat can resume. Start a step only when the one before is done.

1. Edit: `slop --json -p NAME edit edl` (it names shots without a picture; fix those first), then `slop --json -p NAME job start -- edit export`.
2. Look (docs/70-motion-design.md §8): `slop --json -p NAME edit look show`. Change only what the owner confirmed (skill taste).
3. `slop --json -p NAME render info`: fix missing media or device warnings at the source (board, plate, clip). Then `slop --json -p NAME job start -- render check --layers`: fix any shot under 3 layers at the source. A fix that changes the approved board: say so in one line, ask the owner to re-approve; on their yes `slop --json -p NAME board approve --note '<their words>'`.
4. Safety and canon scan of every generated take, before any frames (docs/80-review-qa.md §9.0; Quick tier with no clips: add `--plates`):
   - `slop --json -p NAME job start -- review scan-sheets`;
   - `cd /workspace/slop/projects/NAME && cp render/scan/findings-template.json render/scan/findings.json`; look at every sheet; list each take in `checked` and each problem in `findings`;
   - `cd /workspace/slop/projects/NAME && slop --json -p NAME review record render/scan/findings.json`, then `slop --json -p NAME review status` until it says CLEAN. Blocks go to the owner.
5. Lyric gate (§3): `slop --json -p NAME job start -- render lyrics`; it must say N/N.
6. The excerpt (docs/00-overview.md §4 rule 5): `slop --json -p NAME job start -- render frames --workers 3 --from T0 --to T1` (T0-T1 = the first finished section, 20-40 s, in seconds), then `slop --json -p NAME job start -- render encode --draft`. Send out/draft.mp4: "Look and pace right? Say "continue" and I render the rest." Frames are kept, so nothing is wasted. The owner said "go on to v1": skip this step.
7. The rest: `slop --json -p NAME job start -- render frames --workers 3` (the box has RAM for 3; 2 while agent jobs run); when done `slop --json -p NAME job start -- render encode --review`; then `slop --json -p NAME job start -- render sheet` and look at it yourself before the owner does (docs/80-review-qa.md §8.1).
8. G6: send out/review.mp4 (over 200 MiB: `slop --json -p NAME job start -- render encode --share`, send out/share.mp4). "Accept v1, or what's wrong? And the 9:16: full length, or a 15-60 s cut of the hook (default: the first chorus)?" Notes: fix the source, render again, ask again. Accept: `slop --json -p NAME gate v1 --approve --note '<their words>'`.
9. Master: `slop --json -p NAME job start -- render encode` (CRF 16, BT.709 tags, checked with ffprobe), then `slop --json -p NAME job start -- render check` (at most 3 flashes a second, history check).
10. 9:16 (docs/90-master-publish.md §4). Off-centre lead: name its box first (`slop --json -p NAME plates box PLATE --label subject --uv 0.40,0.15,0.25,0.70`, then edit export again). `slop --json -p NAME job start -- render vertical --from T0 --to T1` (the stretch the owner chose; full length: no --from/--to), then `slop --json -p NAME job start -- render lyrics --vertical --from T0 --to T1` (N/N) and `slop --json -p NAME job start -- render check --skip-history --video /workspace/slop/projects/NAME/out/vertical.mp4`.
11. Chat copy: `slop --json -p NAME job start -- render encode --share`, send out/share.mp4 (under 190 MiB).
12. Posting copy (§5, §6): title, one line of premise in the song's voice, "made with AI:" and the tools, the owner's pseudonym only, no job ids or file names. Remind them to switch on each platform's AI-content label. Never post without their yes for that post. A post promoting the template needs X's paid-partnership label and stays unedited for 30 days (§7).
13. `slop --json -p NAME render clean` frees the frames once the master checks out.
14. Close with one offer (default: none): a 15-30 s 9:16 teaser of the hook (`slop --json -p NAME job start -- render vertical --from T0 --to T1`, no new spend), a sequel concept (skill song; a sequel never reuses the device), or the paused weekly idea drop if it is still off.
