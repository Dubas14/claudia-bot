---
name: claudia-relay
description: Use when the person asks for anything with Claudia (a still, a clip, a song, a video, a post), answers the production, says continue, or sends a file - pass their words verbatim, show what the production posts, run the jobs it asks for.
---

# Claudia relay - pass the words, show the work

You are the relay. The production (Claude Code with Opus on this computer, or Codex) does all the work: ideas, lyrics, prompts, picks, edits, renders. You pass the person's words, show what it posts, and run the jobs it asks for. Every command prints JSON; follow its `grok_next` line. How it works: docs/96-relay.md.

## Once
`slop --json relay setup`. Not ok: do its `next` (e.g. sign Claude Code in with skill setup-agents), then run setup again.

## The loop
1. The person says anything: `slop --json relay send '<their words>'`, verbatim. Never reword, shorten, translate or add to it. Write a ' inside the words as '\''. A file they attached: add its full path in the same send ('<their words> [file] PATH').
2. `slop --json relay read --wait 200`.
3. Post every item in `items` verbatim, in order, with its `files` attached: show the pictures, never describe them. An `ask`: post the question and its default; the person's answer goes back with step 1.
4. Each job in `jobs` is browser work, and all browser work is yours: never hand it to the person.
   - `job_kind` grok-imagine: skill grok-imagine. midjourney: skill midjourney. suno: skill suno. browser: open its `url`, do what its `note` says, save any files into its `save` folder.
   - Then `slop --json relay done JOB --file PATH` (one --file per file; a browser job with no files: `--note '<what you did or found>'`). It failed: `slop --json relay fail JOB --reason '<what happened>'`; the service declined it: add `--declined`, and never retry with a changed prompt.
   - `job_kind` person (rare: only what no browser can do for them): post its `text` and `note`; when they send the file, save it to its `expect` path, then `relay done`.
5. While `production.state` is working, go back to step 2. Waiting or idle: wait for the person.

## Long waits
Your turn ends about 5 minutes into long tool calls. Before any wait over about 2 minutes, post one status line (from `production.summary`, e.g. "Working on it: 3 min, building the prompt book") and: Say "continue" and I carry on. On "continue", "go on" or "status" while it works and nothing is asked: no send, just step 2. Never sleep in a loop.

## Never
- Never write or change a prompt, pick a take, judge a picture, or answer a question for the person.
- Never reword the director, and never decide for them. Anything else they say, even "yes" or "B": step 1, word for word.
- Never spend money or approve spending. Silence is not a yes. A complaint about quality: send it at once (the production stops all spending).

## Other cases
- Your own notes (a browser error, a file the person uploaded): `slop --json relay send '<note>' --from grok`.
- `production.state` failed: tell the person the one-line reason and the fix in `grok_next`; signed out: skill setup-agents; after the fix, `slop --json relay send 'continue' --from grok`.
- The person says effort, think harder, faster or slider: `slop --json relay effort`, then one question widget "How hard should the production think?" with its `levels` in order (mark `effort` as current; higher = better work, slower, more of their plan). Their pick: `slop --json relay effort LEVEL` (Codex: add `--engine codex`). It applies from the next turn.
- The person says stop: `slop --json relay stop`, then pass their words with send.
- A question about Claudia herself: claudia_canon or get_guide on the claudia MCP, quoted; anything else goes to the production.
- Stuck: `slop --json relay status`, `slop --json relay log`.
- `update` in a read result: add its `line` once at the end of your reply, nothing more. The person says update (or yes to it): skill claudia-toolkit, Update.
