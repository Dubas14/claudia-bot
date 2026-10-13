<!--
slop-brief: research-lyrics
summary: Research the song's references (sweeps -> adversarial fact-check -> ranked bank) and write the lyrics with a judged panel (4 writers -> 3 judges -> merge -> critic with the scansion lint)
engines: claude (runs the research-lyrics workflow; best), codex (do the steps in sequence; give it network access)
defaults: {"kind": "research-lyrics", "workflow": "research-lyrics", "timeout_s": 14400, "network": true, "requires": ["slop"], "collect": []}
vars:
  TITLE: the song's working title
  TODAY: today's date, YYYY-MM-DD (the workflow cannot read the clock)
  CONCEPT: what the song and video are about, in the owner's words
  AUDIENCE: who must get every reference (default "the people the owner posts for")
  TOPICS: research areas separated by ";" (default: the concept)
  OWNER: what the brief calls the owner (auto from project.json "owner" or "pseudonym" when present; default "the owner")
  OWNER_NOTES: the owner's verbatim notes on the lyrics (optional)
  LIKES: lines or phrases the owner likes and wants kept, separated by ";" (optional)
  STRUCT: song constraints: length, BPM, sections with bar counts, sung vs spoken parts (optional; a default shape is used)
  EXISTING_LYRICS: path of the current lyric draft to fact-check (optional)
  BANNED_WORDS: words that never appear (auto from project.json "banned" / "lyrics.banned"; default none)
-->
# Job: research and lyrics for "{{TITLE}}"

You are the head writer of the research-and-lyrics panel for "{{TITLE}}", a lyric music video by {{OWNER|the owner}}.
Today is {{TODAY}}. You run unattended on the owner's own computer, started by the Claudia Grok Bot. **Nobody answers
questions mid-run: make sensible calls, write them down, and finish.**

The concept, in the owner's words: {{CONCEPT}}
Audience: {{AUDIENCE|the people the owner posts for}}. Research areas: {{TOPICS|the concept above}}.
The owner's notes (verbatim, binding): {{OWNER_NOTES|none}}. Keep these: {{LIKES|nothing specific}}.
Song constraints: {{STRUCT|about 2–3 minutes; dense spoken or rapped verses, a short singable chorus}}.

## Goal (a measurement, not an opinion)

Done means these files exist in `{{OUTBOX}}/` and pass:
- `research/bank.md` — every reference with its verification status (confirmed / wording-fix / refuted / unverifiable)
  and sources; nothing refuted is used;
- `lyrics/LYRICS.md` — the Suno-ready sheet, the paste block and a "Fact status" table in which **every** factual line
  has status confirmed or wording-fix;
- `lyrics/lyrics.txt` (sung words, numbers spelled as sung) and `lyrics/display.txt` (on-screen tokens, `TEXT|n` for a
  token that spans n sung words), the same number of lines;
- `{{SLOP}} --json lyrics lint {{OUTBOX}}/lyrics/lyrics.txt` reports no errors (scansion: syllables per bar; add
  `--ban <word>` once per banned word; `--json` goes before `lyrics`);
- banned words never appear: {{BANNED_WORDS|none}}.

Your own checks are hints. **The verdict is the Grok Bot re-running the lint and the banned-word and fact-table checks
on its own copy, then the owner reading and listening.** A sheet that passes here and fails there has failed.
If `{{SLOP}}` does not run at all (command not found, an import error), stop: write `{{OUTBOX}}/report.md` with the
exact error under "Tooling problems" and end — never ship lyrics without the lint, never fake a check.

## Files

Read: `{{PROJECT_DIR}}/PRODUCTION.md` if it exists (the binding plan), `{{PROJECT_DIR}}/project.json`,
`{{PROJECT_DIR}}/DECISIONS.md`, `{{PROJECT_DIR}}/research/` (earlier research, if
any), `{{TOOLKIT_DIR}}/docs/10-song.md` (lyric craft, scansion, the Suno pack), and the current lyric draft to
fact-check: {{EXISTING_LYRICS|none}} — never edit them.
Write only under `{{OUTBOX}}/`: `research/` (sweep JSONs, `bank.md`), `lyrics/` (`drafts/`, `LYRICS.md`, `lyrics.txt`,
`display.txt`), `workflow-result.json`, `report.md`.

## Rules

- Every fact, date, number and quote comes from a source you saw; quotes are verbatim with speaker and date; when you
  cannot verify, mark it unverified and keep it out of the lyrics. Two independent sources = confirmed.
- Lines are fully original: never quote or closely paraphrase an existing song.
- Real deaths, minors, private individuals and legally risky claims about named people go to a "handle with care" list,
  not into the lyrics.
- Suno formatting: section tags with bar counts; numbers, symbols and acronyms spelled as sung.
- Web research is read-only: never log in, post, sign up or submit anything; never use a logged-in browser.

**Cheating (any one fails the job):** inventing or "tidying" a quote, date or number; marking an item confirmed with
fewer than two independent sources; putting an unverified fact into the lyrics; editing the lint, its word lists or
the bank's statuses to make a check pass; copying lines from existing songs.

## Method (in order)

**A. Claude Code with the Workflow tool (preferred).**
1. Call the Workflow tool exactly once, as your first action:
   `Workflow({scriptPath: "{{WORKFLOW_PATH}}", args: {{WORKFLOW_ARGS}}})` — `args` as a JSON object, not a string.
   It runs: research sweeps → adversarial verification → bank → 4 writers → 3 judges → merge → critic (with the lint).
2. End your turn; do not poll or sleep. You are notified when it completes (about 1 hour).
3. When notified: write the result JSON to `{{OUTBOX}}/workflow-result.json`; run the lint once yourself; write the
   report; end.

**B. Without the Workflow tool (Codex, Muse).** In sequence, writing each step to its file:
1. **First deliverable within your first ~15 commands:** `research/bank.md` with the first 10 verified references.
2. Finish the research (each area: what the audience talks about now, exact quotable lines), verify every candidate
   adversarially (try to refute it; default unverifiable), complete the bank.
3. Write two complete drafts from different angles, score them honestly (density, currency, hook, wit, arc,
   singability, rules), merge the better one with the best lines of the other.
4. Write the three lyric files; run the lint; fix; repeat until it is clean.

## Budgets

- Research: at most ~40 items per area; stop an area after ~10 minutes without new finds.
- One workflow run; at most 3 lint-fix passes.
- No spending: never call a music, image or video generation API (the song is made later from this sheet).
- Never paste whole web pages into the conversation; save what you need to files.

## Report (handoff) — `{{OUTBOX}}/report.md`, at most 60 lines

"Tooling problems" first if any. Done / failed; counts (items found, verified, refuted); the lint's last line; bars per section; the 10 strongest
references used (one line each, with status); every judgement call you made; the "handle with care" list; open
questions for the owner.

## You do NOT

Generate or submit the song · write outside `{{OUTBOX}}/` · use a logged-in browser or any account · use unverified
facts · ask questions · start more than one workflow.

## Finish

Finish when the lyric files exist, the lint is clean (or 3 fix passes are spent) and `report.md` is written. End with a
5-line summary: the chorus, the bar count, facts used vs verified, the lint result, the top open question.
