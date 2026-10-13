<!--
slop-brief: safety-scan
summary: Before release, look at six frames of every generated take the edit uses and report block / fix / note findings (nudity, gore, minors, readable text, real people, off-canon lead, glitches) to outbox/scan/findings.json
engines: claude (runs the safety-scan workflow, 6 agents in parallel; best), codex or muse (scan in sequence)
defaults: {"kind": "safety-scan", "workflow": "safety-scan", "timeout_s": 5400, "requires": ["ffmpeg"], "workflow_args": {"list": "render/scan-list.json"}}
vars:
  TITLE: the song title (auto from project.json)
  LIST: path of the JSON take list [{clip, file, shots?}], relative to the project folder or absolute; "file" entries likewise (default render/scan-list.json)
  TOTAL: how many takes the list holds
  WORLD: one paragraph: who is who in the video, its places and its era (optional; else read from the project)
  LEAD_CANON: the lead's canon text (auto from project.json lead.canon)
  FIX_RULES: extra "fix" findings for this video, separated by ";" (optional)
  BLOCK_RULES: extra "block" findings for this video, separated by ";" (optional)
  SLICES: parallel agents (default 6)
-->
# Job: safety and canon scan of every take in "{{TITLE}}"

You run the release scan of the lyric music video "{{TITLE}}": every generated take the edit uses is checked for
anything that must not ship in a **public** video, and for canon breaks. You run unattended on the owner's own computer,
started by the Claudia Grok Bot. **Nobody answers questions mid-run: make sensible calls and finish.**

Takes: the list `{{LIST|render/scan-list.json}}` ({{TOTAL}} takes; relative paths — the list itself and its "file" entries — are relative to `{{PROJECT_DIR}}`).
The video's world: {{WORLD|read project.json, DECISIONS.md and board/STORYBOARD.md: who is who, the places, the era}}.
The lead's canon: {{LEAD_CANON}}

## Goal (a measurement, not an opinion)

Done means `{{OUTBOX}}/scan/findings.json` exists and holds `{"checked": [<every clip in the list>], "of": {{TOTAL}},
"counts": {"block": n, "fix": n, "note": n}, "findings": [{"clip", "time", "severity": "block"|"fix"|"note", "kind",
"what"}]}` with **every** take in the list checked. The Grok Bot compares `checked` with the list on its side: a take
that was not looked at is a failure of this job, never a clean take. Then the owner decides on every block and fix.

## Files

Read (never edit): the take list and the takes it names · `{{PROJECT_DIR}}/PRODUCTION.md` if it exists ·
`{{PROJECT_DIR}}/project.json`, `DECISIONS.md`,
`board/STORYBOARD.md` · `{{TOOLKIT_DIR}}/docs/80-review-qa.md` (the scan rubric) and `docs/62-moderation.md`.
Write only: `{{OUTBOX}}/scan/` (findings.json, the contact sheets that show a block or fix), `{{OUTBOX}}/report.md`;
frame scratch under `{{PROJECT_DIR}}/render/scratch/scan/`.

## Rules

- Per take: duration with ffprobe; six frames at 8 %, 25 %, 42 %, 58 %, 75 % and 92 % at 640 px wide; one 3x2 contact
  sheet per take (python PIL, each tile labelled with its time); Read every sheet and look carefully.
- **block** (must not ship): any nudity or visible genitals or nipples (even glowing, translucent or statue-like
  figures); sexual content; gore; a minor; text, logos or watermarks readable in frame; a real, recognisable person;
  {{BLOCK_RULES|anything the video's world rules out (e.g. a modern object in a period scene)}}.
- **fix**: the lead off-canon (compare with the canon above); obvious generation glitches (melting or doubled faces,
  extra limbs or fingers, a face morphing into another person, objects warping); background people who look like copies
  of a lead character; {{FIX_RULES|nothing else specific to this video}}.
- **note**: small things worth knowing (soft focus, a brief oddity).
- Do not report the grade or colour. Give ffmpeg `< /dev/null` inside loops (it eats a loop's input otherwise).

**Cheating (any one voids the scan):** marking a take checked without Reading its sheet; dropping takes from the list;
softening a block into a fix; deleting or editing a take.

## Method (in order)

**A. Claude Code with the Workflow tool (preferred).**
1. Call the Workflow tool exactly once, as your first action:
   `Workflow({scriptPath: "{{WORKFLOW_PATH}}", args: {{WORKFLOW_ARGS}}})` — `args` as a JSON object, not a string.
   It splits the list into {{SLICES|6}} slices, one agent per slice; a slice that returns nothing or skips takes fails
   the run.
2. End your turn; do not poll. You are notified when it completes (minutes, not hours).
3. When notified: write the result to `{{OUTBOX}}/scan/findings.json`; copy the sheets of every block and fix into
   `{{OUTBOX}}/scan/`; write the report; end. If the result lists unchecked takes, say so first in the report.

**B. Without the Workflow tool.** Scan the list in order yourself. **First deliverable within your first ~10
commands:** the first take's sheet Read and `findings.json` written with it; then append take by take (a cut at any
moment must leave a valid file).

## Budgets

One workflow run (or one pass in sequence). About 5 seconds of looking per take is not enough — look at every tile.
No spending of any kind; never re-generate or edit a take (the owner decides what is re-made).

## Report (handoff) — `{{OUTBOX}}/report.md`, at most 40 lines

Takes checked / total; every block (clip, time, what) on its own line; fixes grouped by kind with counts; takes you
could not open; what the owner must decide.

## You do NOT

Edit, crop, delete or re-generate any take or plate · write outside `{{OUTBOX}}/` and the scratch folder · judge the
grade or the edit · ask questions.

## Finish

Finish when every take in the list is checked (or reported as unreadable) and findings.json and report.md are written.
End with a 3-line summary: checked/total, blocks, fixes.
