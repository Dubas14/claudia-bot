<!--
slop-brief: chapter-motion
summary: Bespoke motion design for 1–4 chapters: the chapter files are wired into engine/ch/_index.js, an animator codes each chapter against engine/DEVICES.md, an art director reviews real renders (owner taste x2), fixes until no blocking fix is left
engines: claude (runs the chapters workflow; best), codex (one chapter per job, review yourself with renders)
defaults: {"kind": "chapters", "workflow": "chapters", "timeout_s": 21600, "wire_chapters": true, "queue_group": "render", "requires": ["slop", "render"], "workflow_args": {"parallel_chapters": 2, "render_workers": 2}}
vars:
  TITLE: the song title (auto from project.json)
  CHAPTERS: JSON list of chapters for this job: [{"id": "C2", "file": "02_name.js", "name": "...", "t0": 18.96, "t1": 47.25, "shots": ["s011", "s012"], "fixes": []}] (the runner wires each file into engine/ch/_index.js and collects exactly these files)
  OWNER: what the brief calls the owner (auto from project.json "owner" or "pseudonym" when present; default "the owner")
  OWNER_QUOTES: the owner's verbatim taste notes and brief (binding; optional — the reference bar is used otherwise)
  MODE: build (new chapters, default) or refit (re-key built chapters to re-made footage + carried fixes)
  ROUNDS: review rounds, 1 or 2 (default 2)
  BANNED_WORDS: words that never appear on screen (auto from project.json "banned"; default none)
-->
# Job: chapter motion design for "{{TITLE}}"

You lead the motion design of these chapters of the lyric music video "{{TITLE}}":
{{CHAPTERS}}

Mode: {{MODE|build}} (build = new chapters, or continue a half-built file; refit = re-key built chapters to re-made
footage and apply the carried `fixes`). Review rounds: {{ROUNDS|2}}.

You run unattended on {{OWNER|the owner}}'s own computer, started by the Claudia Grok Bot. **Nobody answers questions
mid-run: make sensible calls, write them down, and finish.**

## Goal (a measurement, not an opinion)

For every chapter above, all of these hold on its own time range `t0:t1`:

    {{SLOP}} --project "{{PROJECT_DIR}}" render lyrics --from <t0> --to <t1> --workers 2   -> prints N/N (every sung word drawn at its time)
    node "{{TOOLKIT_DIR}}/runner/deleg.mjs" wire "{{PROJECT_DIR}}" --check --chapters "{{JOB_DIR}}/job.json"   -> every chapter WIRED
    {{SLOP}} --project "{{PROJECT_DIR}}" render check --skip-flash --pairs <A:B,A:B,A:B>   -> HISTORY-INDEPENDENT (frames are pure functions of t)
    at most 3 full-frame flashes in any second (the whole cut is flash-checked later with `render check`)

and the art director's review of real renders leaves **no blocking fix** (owner-taste score >= 7, other lenses >= 6).
WIRED matters: the engine loads chapter code only through `engine/ch/_index.js`; a chapter file it does not load is
never on screen, yet the lyric gate still prints N/N because the default renderer subtitles every word.
These checks are hints here. **The verdict is the Grok Bot re-running the lyric gate, the wiring check and the history
check on its own copy, then the flash check on the cut, and then the owner watching it.** A chapter that passes here
and fails there has failed. (If a verb or flag differs, run `{{SLOP}} render --help` and use what it offers; report the
mismatch.) If `{{SLOP}}` does not run at all (command not found, an import error, no browser), stop: write
`{{OUTBOX}}/report.md` with the exact error under "Tooling problems" and end — never animate blind or fake a check.

## Files

Read (never edit): `{{PROJECT_DIR}}/PRODUCTION.md` if it exists (the binding plan; read it first) ·
`{{TOOLKIT_DIR}}/engine/DEVICES.md` — **the device library and engine API; code against it exactly** ·
`{{TOOLKIT_DIR}}/engine/README.md` · `{{TOOLKIT_DIR}}/docs/70-motion-design.md` (explaining layer, type modes, 2.5D
treatments, transitions, element budget, flashes; §16 = chapter code) · `{{TOOLKIT_DIR}}/docs/examples/` ·
`{{PROJECT_DIR}}/project.json`, `DECISIONS.md`, `board/STORYBOARD.md`, `board/shots.json`, `lyrics/`,
`analysis/words.json`, `beats.json`, `hits.json`, `edit/edl.json` · the other chapter files in `{{PROJECT_DIR}}/engine/ch/`.

The chapter files already exist and `{{PROJECT_DIR}}/engine/ch/_index.js` already loads them: the runner wired them
before you started (a new file is a stub until its animator writes it). Never edit `_index.js`; if a chapter shows NOT
WIRED, run `node "{{TOOLKIT_DIR}}/runner/deleg.mjs" wire "{{PROJECT_DIR}}" --chapters "{{JOB_DIR}}/job.json"` once.

Write: only each chapter's own file `{{PROJECT_DIR}}/engine/ch/<file>` (the runner copies exactly these files into the
outbox) · render scratch under `{{PROJECT_DIR}}/render/scratch/` (never /tmp) · `{{OUTBOX}}/` for the workflow result,
the review JSONs, 2–4 key contact sheets and the report.

The owner's words (binding; they win any conflict): {{OWNER_QUOTES|none recorded here — read DECISIONS.md; the workflow carries the reference bar}}

## Rules

Mechanical: frames are pure functions of t (no state between frames, no `Math.random` — use the engine's hash — no
`Date`); every sung token on its word time and counted by the lyric gate (mark tokens you draw yourself as DEVICES.md
says); the main lyric is at least 40 px on a 1080p frame and never over a face; at most 3 full-frame flashes a second;
ms/frame at most 1500; scenes cover each chapter's `[t0, t1)` exactly, one per shot; every chapter WIRED.

Reviewed: one explaining graphic per lyric line (it shows what the words mean, enters on the words naming it, moves in
beats, reads in one glance); at least 3 ordered layers per frame; 2.5D treatments never repeat back to back (five
different ones in a chapter with five or more plate shots); mostly hard cuts on the beat, a motivated transition every
few shots, never the same device twice in a row; cuts and camera moves answer the hits; where a sung line has no synced
take, never hold a singing mouth in close-up on the words; the footage keeps its colour unless DECISIONS.md says
otherwise; banned words never appear: {{BANNED_WORDS|none}}.

**Cheating (any one fails the chapter):** marking a lyric token as drawn when it is not visible; editing the engine,
DEVICES.md, the lyric gate, the analysis, `_index.js` beyond the wire command, or another chapter's file; drawing type
outside the frame or at zero opacity to satisfy a check; hiding a failing shot behind a full-frame card; lowering a
threshold.

## Method (in order)

**A. Claude Code with the Workflow tool (preferred).**
1. Call the Workflow tool exactly once, as your first action:
   `Workflow({scriptPath: "{{WORKFLOW_PATH}}", args: {{WORKFLOW_ARGS}}})` — `args` as a JSON object, not a string.
   It runs, per chapter (at most 2 at a time): animator → art director on real renders → fix → second review → last
   fix while blocking fixes remain. In refit mode it first rebuilds the edit once. A review that returns nothing counts
   as a failure, never as a pass.
2. End your turn; do not poll or sleep. You are notified when it completes (roughly 1.5–3 hours).
3. When notified: write the result JSON to `{{OUTBOX}}/workflow-result.json`; run the wiring check (the second command
   in the Goal) and the lyric gate once per chapter yourself; copy the 2–4 most telling contact sheets into
   `{{OUTBOX}}/sheets/`; write the report; end. Do not redo chapters by hand.

**B. Without the Workflow tool (Codex).** One chapter at a time:
1. Read the files. In refit mode, rebuild the edit once first: `{{SLOP}} --project "{{PROJECT_DIR}}" edit edl`, then
   `{{SLOP}} --project "{{PROJECT_DIR}}" edit export`. **First deliverable within your first ~12 commands:** a rough but
   complete chapter file (every shot covered), the wiring check printing WIRED, and one contact sheet you have looked at.
2. Iterate: lyric gate → contact sheets (`render sheet --times …`) at every shot's first/last frame, every line's
   first/last word, each graphic's entrance and each transition's middle → look → fix the worst first.
3. Review yourself as the art director would (owner taste x2, craft, sync, story; fixes marked blocking or polish);
   write it to `{{OUTBOX}}/review-<id>.json`; fix every blocking item; re-verify.

## Budgets

- One workflow run; at most two review rounds per chapter; at most 12 fixes per review.
- Rendering is heavy: every render command keeps `--workers 2` or less; at most 2 chapters render at once; the runner
  runs one rendering job at a time on this computer. Check free memory and disk before rendering.
- No spending: never call an image, video or music generation tool or API. A shot that needs new footage is reported.

## Report (handoff) — `{{OUTBOX}}/report.md`, at most 60 lines

"Tooling problems" first if any. Per chapter: status (pass / fixed-not-rereviewed / fail / unreviewed), the wiring
line, the lyric gate line, scores, blocking fixes left; shared bugs found (file, line, fix) — reported, not patched;
footage or plates that need re-generating; anything the owner should look at first (with times).

## You do NOT

Edit any file except each chapter's own file · touch the engine, DEVICES.md, `_index.js`, the analysis, the board or
other chapters · rebuild the edit (only the workflow's setup step does, once, in refit mode) · generate or buy footage ·
ask questions · run more than one workflow · put scratch in /tmp.

## Finish

Finish when every chapter has a final verdict and `report.md` is written. End with a 5-line summary: chapters passed,
the weakest chapter and why, shared bugs, footage to re-make, the first thing the owner should watch.
