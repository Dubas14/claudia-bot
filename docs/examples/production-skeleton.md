# `PRODUCTION.md` skeleton (+ `RUNS.md` and an UPDATE block)

The binding plan the lead writes before launching anything parallel (`95-delegation.md` §6). Every agent prompt begins
"READ FIRST: PRODUCTION.md". Copy the skeleton into the project root and fill every `<…>`. The indented excerpts are SP's
real values, scrubbed, to show the level of detail.

**Why it worked:** one file held the user's words verbatim, the rules every agent checks itself against, hard money caps
per pool, who owns which stage and which file, and a run log — so 129 agents across 17 workflow runs never wrote the same
file and every killed run could be resumed or explained.

---

```markdown
# <TITLE> — production (<date>)

**The go message, verbatim:** "<paste the user's go message exactly, typos included>"
Then: "<every follow-up note, verbatim, in order>"

## Deliverable
<length>, <width>×<height>, <fps> fps: `out/review.mp4` (review copy) and `out/master.mp4`. Title: **<TITLE>** <(SUBTITLE)>.

## The rules every agent follows (checklist)
1. **Lyric video.** Every sung word on screen at its aligned time, in at least one lyric mode, legible on a phone (≥ 40 px).
   Gate: `slop render lyrics --from A --to B` prints N/N for every chapter, and `slop render lyrics` for the film.
2. **Camera and edit play the track.** Cuts on beats or hits; moves answer the actual sounds (`analysis/hits.json`).
   A motivated transition every few shots, hard cuts on hits the rest. Flashes only where the idea calls for them; ≤ 3
   full-frame flashes a second (flash check before delivery).
3. **The look.** <native | clean-grade toward <hero plate> | print>. Accent <hex> on ≤ <n> elements. <banned textures>.
4. **Motion design.** One explaining graphic per lyric line; <density budget>; <occlusion, adaptive ink, 3D, …>.
5. **Lip sync.** Audio-conditioned clips; the audio check; cut at the last eighth before divergence; covers from the frame
   at the cut; if covers fail, give up sync for that span and cut away. No lip-sync-model fallbacks.
6. **Identity.** Faces from the canon text; image references only where the user allowed (<list>). Two clips never start
   from the same frame. Face-filter declines are final for that image (never alter it to pass); another provider with the
   same image is allowed.
7. **Taboos and people.** <the user's taboo words>. Credit only <pseudonym>. Real people only in labelled AI IMAGE posts,
   never speaking, their own words only.
8. **Machines and disk.** <where agents run / where renders run>. Check free memory and disk before anything heavy;
   scratch on <big disk>, never /tmp. `--project <name>` on every command.

## Budget (<date>)
| pool | available | cap for this production | ledger | real billing |
|---|---|---|---|---|
| OpenRouter (video, image edits) | $<…> | **$<…>** (<split by purpose>) | `ledger.jsonl` | `slop spend` (provider credits + key endpoints) |
| Higgsfield (MCP) | <…> credits | **<…>** (<split>) | `ledger.jsonl` | the `balance` tool |
Prices: <per second per resolution>. The API key's own limit is <…> (set it above the cap).

    SP: OpenRouter $185 of $200.91 (singing $80 · motion $70 · retakes/fixes $35);
        Higgsfield 950 of 1,181.65 credits (previz-driven clips ~500 · declined windows ~300 · reserve 150).
        Prices: OpenRouter ≈ $0.23/s at 720p; Higgsfield 7 credits/s at 720p, 12/s at 1080p, 3/s for 480p drafts.

## Stages, owners, gates
| # | stage | owner | output | gate |
|---|---|---|---|---|
| 0 | bootstrap: lyric tokens, hits, graded plates + depth (`slop edit export`) | main | engine assets | a contact sheet renders |
| 1 | clip plan (the prompt book, read by the user) | main | `clips/*.json` | the user's "go"; cost ≤ caps |
| 2 | clips: windows + motion; QA of every take; declines → second provider | main / verbatim submitters | takes imported, `clips/QA.md` | coverage report |
| 3 | design kit: engine additions, project kit, `DESIGN.md`, exemplar chapter | wf **kit** | kit + chapter 1 | review pass |
| 4 | media: hand-measured boxes and tracks the devices anchor on (`engine/common.js`, 70 §5.0); SP ran detection, mattes and clip depth here on a GPU, which the toolkit does not ship | wf **media** or main | `engine/common.js`, keyed tracks in `shots.json` | spot checks |
| 5 | chapters 2–N: animate → review → fix → review → fix | wf **chapters** (≤ 3 in parallel) | chapter files | lyric N/N, history check, no blocking fix |
| 6 | safety and canon scan of every take; fixes at the source | wf **scan** + main | findings, re-makes | zero blocks |
| 7 | touch-up where footage changed (no generation) | wf **touch-up** | chapter files | lyric N/N per chapter |
| 8 | render, encode, flash check, deliver | main | `out/master.mp4`, `out/review.mp4` | ffprobe tags, flash check |

## Chapter map
| file | sections | from–to (s) | shots |
|---|---|---|---|
| `engine/ch/01_<name>.js` | <…> | <t0>–<t1> | s001–s0NN |

## File contracts (so parallel owners don't collide)
- Only <stage/workflow> edits <file>; everyone else reads it.
- Only the kit workflow edits the shared engine, additively (existing renders must stay byte-identical).
- Chapter animators edit only their own chapter file; shared bugs are reported, never patched.
- Mattes: `plates/<name>.matte.png` (8-bit alpha, plate size); clip mattes/depth: `clips/<clip>/matte/f00001.png`,
  `…/depth/f00001.png` (<width> px wide, same numbering as the frames).
- Every workflow run id and its exact args go in `RUNS.md` the moment it starts (`slop runs add <id> …`).

## Status (newest first)
- <date time> — <what happened, with numbers and decisions; e.g. "v1 APPROVED: 'its perfect. change nothing.'">
```

---

## `RUNS.md` (one row per run; status derived from the run records, not typed by hand)

```markdown
# Workflow runs (<project>)

| run | workflow | script | args | status |
|---|---|---|---|---|
| wf_<id> | chapters (02–04) | templates/workflows/chapters.js | {"project": "<p>", "chapters": [<…>]} | done: 02 passed r2 8/8/8/8; 03 at 7; 04 never reviewed (usage limit) → carried into v2 |
| wf_<id> | safety-scan | templates/workflows/safety-scan.js | {"list": "render/scan-list.json", "slices": 6, "total": 96} | done: 12 block / 44 fix / 40 note → findings in clips/scan-findings.json |
```

To resume a killed run: the same script path, the same args, `resumeFromRunId: "wf_<id>"`, in the same Claude session.

---

## An UPDATE block (a decision made after a stage started)

Append to `DECISIONS.md` and to the prompts of every later stage; never re-run finished agents for it. EV's storyboard
merge received this one mid-run (verbatim excerpt; the "FACE UPDATE:" label is added here; its "young" is EV's
retired wording: a new UPDATE quotes today's identity text from the canon):

```
FACE UPDATE: every mj_prompt with her MUST describe her as 'a young Caucasian American woman with pale skin and light freckles, a glossy black blunt jaw-length bob with heavy bangs and one clay-orange streak through the bangs, a small flat clay-orange eight-pointed star hair clip, a thin headset microphone, a white cropped puff-sleeve shirt, a black pleated skirt with a harness belt and a hanging white garment tag, black knee boots' (drop garments not visible in the framing) … State the framing explicitly at the start of every such prompt … and where she stands in the frame. Keep her poses editorial and upright.
```

**Why it worked:** the decision reached every later agent without restarting the panel, and it names exactly what changes
in every prompt (the descriptor, framing first, placement, upright poses).
