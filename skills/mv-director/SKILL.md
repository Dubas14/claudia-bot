---
name: mv-director
description: Use when the owner wants EV-class quality with their own coding agent (Claude Code, Codex or Muse Code, on the bot's computer or theirs), when a project's tier is director, or when heavy work (research and lyrics, storyboard panel, prompt book, chapter motion design, reviews, safety scan) should be delegated instead of done in chat.
---

# Director tier - delegate the heavy work, keep the gates

Read runner/README.md §1b and §2 and docs/95-delegation.md §2 (what to delegate) and §4 before the first job. You are the gatekeeper; the owner's agent does the work on their plan. A delegated job never spends money: spending stays with you, after the owner's yes.

## Where the jobs run (once per project)
`slop --json agents status`. An engine signed in on the bot's computer (the box): run there ("On the box"): no copies, no approval cards, the owner can be away. None: skill setup-agents signs one in on the box; or, if the owner prefers their own computer, "On their computer". The engine for jobs: `slop --json agents use ENGINE --for director` (it prints which briefs follow it; ENGINE = claude, codex or muse).
Once per box: `slop --json agents test ENGINE`. Claude workflow briefs (research-lyrics, storyboard-panel, chapter-motion, safety-scan) also need, as a background command (1-3 min), `node /workspace/claudia/runner/deleg.mjs preflight claude --workflow` with `subagent_tools_ok` true.

## Which brief for which stage (docs/95-delegation.md §2)
research-lyrics (concept facts, lyric drafts) · storyboard-panel · prompt-book (one context writes the clip prompts; you still run G5 and the spend) · chapter-motion · review · safety-scan. Gates, spend and the final edit decisions never leave you.

## On the box
1. `node /workspace/claudia/runner/deleg.mjs new auto --project NAME --brief storyboard-panel --set OWNER_QUOTES='<their words, verbatim>'`. Read `job_dir`, `engine` (not signed in here per `slop --json agents status`: do not start; do that stage in chat), `engine_note` and `gates_needed` (a gate flag needs the owner's yes and what it allows, first).
2. `node /workspace/claudia/runner/deleg.mjs start JOB_DIR` (JOB_DIR = its `job_dir`; the gate flags after it). It returns at once. Record: `slop --json -p NAME runs add ID --kind deleg --what '<kind> job'` (ID = the job folder's name).
3. A workflow job takes 1-3 hours: tell the owner and end with the profile's turn rule line (say "continue"). Then `node /workspace/claudia/runner/deleg.mjs wait JOB_DIR 25`, once per turn, never in a loop. At most 2 agent jobs run on the box at once; while they run, render frames with `--workers 2`.
4. Done: the results are in JOB_DIR/outbox/. Check and apply them (below).

## On their computer (local exec; every command and copy is an approval card: tell them first; "Always allow" is their decision, never push it)
Placeholders (runner/README.md, the table at the top): HOME = their home folder, TK = HOME/claudia, PROJECTS = HOME/slop/projects, PROJ = PROJECTS/NAME. Absolute paths, forward slashes, in double quotes.
- Once: the engine signed in there (skill setup-agents); macOS needs bash 4.4+ (`brew install bash`). `git clone https://github.com/anabologyco-maker/claudia-bot "TK"`, then in the background `bash "TK/bin/setup.sh" --minimal` (Windows: runner/README.md §1). Checks: `node "TK/runner/deleg.mjs" doctor --render`, `node "TK/runner/deleg.mjs" selftest`, `node "TK/runner/deleg.mjs" preflight ENGINE`.
- Sync (runner/README.md §2, part a): the "small" tar line for research, storyboard and prompt-book jobs, "render" for chapters and reviews; CopyFromBox each part to HOME; `node "TK/runner/deleg.mjs" unpack "HOME/NAME.tgz" "PROJECTS"`. Never while a job of that project runs.
- Build it on the box with `new` as above (add `--engine ENGINE` for their engine), CopyFromBox its job.json to PROJ/jobs/ID.job.json, then run its `user_run_command` as ONE background local command and record it with runs add. 1-3 hours: the same "continue" line; then read its terminal output.
- Done: CopyToBox PROJ/jobs/ID/outbox.tgz to /workspace/slop/projects/NAME/jobs/ID/, then `tar -xzf /workspace/slop/projects/NAME/jobs/ID/outbox.tgz -C /workspace/slop/projects/NAME/jobs/ID/`.

## Check, then apply (runner/README.md §2, part f; the worker's own PASS is only a hint)
- Storyboard: `slop --json -p NAME board audit --shots /workspace/slop/projects/NAME/jobs/ID/outbox/files/board/shots.json`, then copy outbox/files/board/* into the project's board/.
- Lyrics: `slop --json -p NAME lyrics lint /workspace/slop/projects/NAME/jobs/ID/outbox/lyrics/lyrics.txt`, then the owner.
- Prompt book (the clips exist: skill clips step 1): each entry of outbox/prompts/clips.json to clips/prompts/CLIP.txt, `cd /workspace/slop/projects/NAME && slop --json -p NAME clip set CLIP --prompt-file clips/prompts/CLIP.txt`, then `slop --json -p NAME clip lock CLIP`; then G5 with outbox/prompts/book.md.
Report in at most 6 lines: done or failed, what changed, flags for the owner.

## Gates and stops
The same six gates and spend rules as skill mv-studio. An owner quality flag: stop the job (`node /workspace/claudia/runner/deleg.mjs stop JOB_DIR`, or `node "TK/runner/deleg.mjs" stop "PROJ/jobs/ID"` on their computer) and `slop --json -p NAME spend --freeze '<their words>'` before you reply.
