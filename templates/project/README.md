# {{TITLE}}

A Claudia project (tier **{{TIER}}**, created {{DATE}}). Folder name: `{{NAME}}`. It makes Claudia content sized
to the ask (a still, a clip, a song, a music video or a post); the stages below are the music video, the biggest ask.
claudia.gallery is the source of truth for her (the toolkit's docs/05-claudia-gallery.md).

Select it on **every** command line - `slop --project {{NAME}} <command>` or `SLOP_PROJECT={{NAME}} slop <command>`.
Put `--json` and `--project` BEFORE the command name (`slop --json --project {{NAME}} analyze`): every command
accepts them there. There is no default project: a command without one stops and lists the projects.

Where am I, what next?  ->  `slop --project {{NAME}} status`   (run the command it prints under "next:")
Let slop do the next step when it is free and needs nobody's input  ->  `slop --project {{NAME}} next`

Long steps (analyze, edit export, render frames / lyrics / encode / check / vertical, review scan-sheets, board
sheet, clip sync, taste embed) take minutes: run them in the background and wait in short calls, so no shell time
limit cuts them off (`status` already prints them in this form):

    slop --project {{NAME}} job start -- analyze
        -> it prints the job id at once, e.g. analyze-k3f9, and its wait command:
    slop --project {{NAME}} job wait analyze-k3f9   (returns within ~25 s; repeat until it is no longer running)

(`job wait last` means the newest job; prefer the id.) A step whose last job failed or changed nothing is not
started again by `next`: read that job first (`slop --project {{NAME}} job status ID`).

A file the owner shares as a link (Google Drive, Dropbox, HTTPS):  `slop --project {{NAME}} fetch "URL" --to audio`

## What lives where

| What | Where |
|---|---|
| the owner's ask VERBATIM, references, constraints | `BRIEF.md` |
| concept, style, the bar, cast/coverage, pipeline/budget, verification (12 headings) | `PLAN.md` |
| settings: title, tier, lead canon, look, models, budget caps, gates (+ what each approval covered) | `project.json` |
| the lead's canon (face/age/ethnicity/skin pinned, hair, outfit, never) | `bible/LEAD.md` -> `project.json` lead (`slop lead`) |
| the owner's decisions, dated (never rewrite - supersede) | `DECISIONS.md` (`slop decide "..."`) |
| production notes: what we learned, newest last | `NOTES.md` |
| run ids of long jobs, for resume | `RUNS.md` (`slop runs add ...`) |
| background jobs: state, progress, result, log (`slop job list`) | `jobs/<id>.json`, `jobs/<id>.log` |
| every paid call (estimate); real spend comes from the provider | `ledger.jsonl` (`slop spend`) |
| the song master (44.1 kHz stereo WAV) | `audio/song.wav` |
| stems and per-clip audio windows | `audio/stems/`, `audio/windows/` |
| lyrics as SUNG / as they should READ on screen (format: `lyrics/README.md`) | `lyrics/lyrics.txt`, `lyrics/display.txt` |
| every reference in the lyrics with its source (the jokes the graphics must land) | `lyrics/SOURCES.md` |
| beat map, word timings, drum hits, ear-check report | `analysis/beats.json`, `words.json`, `hits.json`, `report.md` |
| taste tokens, picks | `taste/` |
| storyboard (source of truth for the edit), contact sheet, audit | `board/shots.json`, `board/board.pdf`, `board/audit.json` |
| image prompt book, candidates, picks | `plates/prompts.md`, `plates/cands/`, `plates/picks.json` |
| one file per video clip (request, takes, measured lip sync) | `clips/<clip>.json`, `clips/<clip>/take-N.mp4` |
| edit decision list | `edit/edl.json` |
| engine data generated from the above | `engine/` |
| lyric gate and flash/history check reports | `render/lyrics-report.json`, `render/check.json` |
| the safety + canon scan of the generated takes the edit plays (sheets, findings, verdict) | `render/scan/` (`slop review scan-sheets`, `slop review record FILE`, `slop review status`) |
| rendered frames (delete after encoding) and finished videos | `render/frames/`, `out/review.mp4`, `out/master.mp4`, `out/vertical.mp4` |

## Stages (`slop status` walks them and says when one went stale)

1. **Brief** - paste the owner's ask verbatim into `BRIEF.md` (with the date), plus their references.
2. **Song** - put the master at `audio/song.wav` (`slop song ingest FILE`). Suno: the owner presses Create and
   downloads the WAV on a paid plan; the bot only writes the lyric and style fields.
3. **Lyrics** - fill `lyrics/lyrics.txt` (as sung; rules in `lyrics/README.md`), check with `slop lyrics lint`.
   Source every reference in `lyrics/SOURCES.md`.
4. **Analysis** - `slop analyze`: stems, beat map (variable tempo), word alignment, hits. Then read
   `analysis/report.md` and check every flagged gap BY EAR before storyboarding. After the analysis, start
   `lyrics/display.txt` (as read) with `slop lyrics display --init --force` and check it with `slop lyrics display`.
   Editing `lyrics.txt` or the song later makes the analysis stale: re-run it.
5. **Taste** (Studio/Director) - capture the owner's taste (`slop taste serve --tunnel`, then `slop taste tokens`).
6. **Lead and look** - the lead is Claudia unless the owner asks for a new character: `bible/LEAD.md` holds her
   canon. Test 4 plates, get the face approved, then `slop lead --canon "..." --far "..."`. Choose the look
   (`project.json` look: native, clean-grade or print).
   Only if the owner decided the video has no lead character: `slop lead --none` (and `board.lead_min` 0).
7. **Storyboard** - `slop board draft`, fill the TODOs, `slop board audit` until it passes, `slop board sheet` for
   the owner. Approve with `slop gate board --approve` only when the owner said yes. Changing `board/shots.json`
   afterwards makes the approval stale.
8. **Prompts and plates** - write `plates/prompts.md` (`slop plates book`); the owner reads it before any spend
   (`slop gate prompts --approve`); make or ingest plates; pick one image per shot. Plates the owner supplied
   need no book: then the owner's approval covers the locked clip prompts only.
9. **Clips** - write each clip prompt (sung: the short sung form; motion: a screenplay) and lock it; the owner reads
   the locked clip prompts with the estimate (`slop gate prompts --approve` again: only then may locked clips be
   submitted without `--yes`); submit, poll, measure lip sync (`slop clip sync`), cover divergences. A failed or declined clip needs a decision: the
   other provider with the UNALTERED image, or cut away (a plate on that shot).
10. **Edit** - `slop edit edl`, then `slop edit export` for the engine.
11. **QA and render** - lyric gate N/N (`slop render lyrics`), contact sheet (`slop render sheet`), frames, review
    copy (`slop render encode --review`). When the edit plays generated clips: the safety + canon scan of every
    take it plays (docs/80-review-qa section 9): `slop review scan-sheets` (6 frames per take), look at every
    sheet, copy `render/scan/findings-template.json` to `render/scan/findings.json` and fill it in, then
    `slop review record render/scan/findings.json`; `slop review status` gives the verdict. A block is cleared by
    re-making that take or cutting it from the edit, then scanning again. Then the owner approves v1
    (`slop gate v1 --approve`).
12. **Deliver** - master (`slop render encode`), flash and history check (`slop render check`: 3 flashes per second
    or fewer), the 9:16 cut (`slop render vertical`), then label it as AI-generated when posting, name the tools and
    credit her: "Claudia is an open character by anabology (claudia.gallery)" (docs/90-master-publish).

Spend rules: every paid call is estimated first; calls over `budget.confirm_over_usd` need the owner's yes; real spend
is read from the provider (`slop spend`). If the owner flags quality, stop all spending until it is resolved:
`slop spend --freeze "the owner's words"`, and `slop spend --unfreeze` once it is.

## project.json overrides

Optional keys other commands read. Add them only when a report or the owner asks for it; record why with
`slop decide`.

| Key | Read by | Effect | Example |
|---|---|---|---|
| `audio.tempo_range` | `slop analyze` | BPM search range of the variable beat map | `[128, 136]` |
| `audio.bpm_hint` | `slop analyze` | the real tempo when the report shows half or double | `132` |
| `audio.downbeat_phase` | `slop analyze` | force which beat of 4 is the downbeat (0-3) when the vote is wrong | `3` |
| `audio.beatgrid` | `slop analyze` | `"analysis"`: one steady grid instead of the fitted variable one | `"analysis"` |
| `audio.beat_pad0` | `slop analyze` | prepend a beat at 0.0 s | `true` |
| `audio.hits` | `slop analyze` | add or drop drum hits by hand | `{"add": [[170.7, 0.8]], "drop": []}` |
| `audio.sections` | `slop analyze` | name sections by time or bar | `[{"name": "chorus1", "t0": 41.2}]` |
| `audio.whisper_model` | `slop analyze` | the OpenRouter transcription model of the fallback | `"openai/whisper-large-v3"` |
| `audio.whisper_map` | `slop analyze` | map a misheard word to the sheet words | `{"gonna": ["going", "to"]}` |
| `audio.conf_min` | `slop analyze` | words below this alignment confidence go on the ear-check list (default 0.5) | `0.6` |
| `lyrics.banned` | `slop lyrics lint` | words the lyrics must not use (`{word: why}` or a list) | `{"delve": "AI tell"}` |
| `lyrics.callbacks`, `lyrics.names`, `lyrics.echo_check` | `slop lyrics lint` | allowed hooks from earlier songs, names to keep, echo check on/off | `["^escape"]` |
| `banned` (or `board.banned`) | `slop board audit` | words never on screen or in prompts | `["logo"]` |
| `board.pace` | `slop board draft` | seconds per shot by section kind | `{"verse": 1.8}` |
| `board.lead_target` | `slop board draft` | share of shots with the lead (default 0.78) | `0.8` |
| `board.lead_min` | `slop board audit` | minimum lead share (default 0.70) | `0.7` |
| `board.max_clips` | `slop board audit` | cap on the number of clips | `12` |
| `board.cover_allowance` | `slop board draft` | extra sung seconds kept for lip-sync covers (default 0.6) | `0.4` |
| `budget.motion_s` | board draft / audit | seconds of sung + motion clips (default by tier: 24 / 120 / 200) | `90` |
| `lead.noun`, `lead.pronoun` | clip prompts | how prompts name the lead (default "the woman", "She") | `"the singer"`, `"he"` |

Top-level `tempo_range`, `bpm_hint`, `downbeat_phase`, `beatgrid`, `beat_pad0` and `hits` (the older layout) are
read too. `gates_meta` is written by `slop gate`: do not edit it by hand.
