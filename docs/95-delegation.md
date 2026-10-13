# 95 · Delegation: when Grok Bot hands work to Claude Code or Codex, and how

Grok Bot is the **director's interface and the gatekeeper**, not the worker. Its usage is a weekly pool that an EV-class
video would exhaust if every step were a bot turn. The reference videos were made by one long-context lead session that
planned, wrote the tools, spent the money and fanned the heavy, parallel work out to agent workflows. This document says
what to delegate, to which engine, how to run it from Grok Bot (the runner and its job folders), how to write the brief
and the binding plan (`PRODUCTION.md`), and the incident-backed management rules that kept 129 agents from losing the
plot.

Director tier only. Quick and Studio tiers run inside the bot with `slop` commands; read §1 anyway — it explains why a
single `slop` command does many steps.

---

## 1. The usage-pool math (why delegate at all)

### 1.1 Grok Bot

- Usage is a **weekly percentage**, with warnings at **75 %** and **90 %**. Per-turn cost is not shown to users.
- Measured upper bound on one account: **≈ 1.5 % of a Pro+ week per user turn** (46 % used over ≈ 30 user turns plus
  routine edits). A live Quick run inside a Grok Bot measured ≈ 0.25 % a reply (fat turns, autonomy to v1).
- **Each turn re-reads the whole conversation**, and each agent step inside a turn re-reads it again, so total tokens grow
  with the square of conversation length: `N·L₀ + Δ·N(N−1)/2` (L₀ = base context, Δ = growth per turn). Illustration:
  50 turns in one conversation ≈ 8.35 M tokens re-read; the same work as 5 conversations of 10 turns ≈ 2.35 M (3.5× less).
- An EV-class production had 50 (EV) and 68 (SP) director messages. Driven turn by turn through Grok Bot that is 50–90
  turns: **75–135 % of a Pro+ week**. So:
  - **one phase per Grok Bot conversation**; the state lives in project files, never in the chat;
  - **one `slop` command does many steps**, prints a small JSON result, and the bot reads files instead of transcripts;
  - **never poll a long job with bot turns or routines**: start it once in the background, read its status file later;
  - the bot's job is setup and secrets, gates and approvals, Higgsfield MCP calls (or delegating them), delivery.

### 1.2 Claude (Claude Code) — where the heavy creative work ran

Calibrated on a **Max 20x** plan running Opus 5.5 with 1M context (API-equivalent dollars per point of each window):

| Quantity | Value |
|---|---|
| 1 % of the weekly limit | **≈ $21.5** (range 20.4–23.7) ≈ 47–50 M tokens at the videos' mix (96–97 % cache re-reads) |
| Weekly allowance | ≈ **$2,150** |
| 1 % of a 5-hour window | ≈ $3.55 |
| One 5-hour window | ≈ **$355** |
| Weekly ÷ 5-hour | ≈ 6.1 windows |

What the two videos used: **EV $626 ≈ 29–30 % of a week** (busiest 5-hour window 90 %, three parallel animation workflows);
**SP $1,007 ≈ 47–51 %** (two 5-hour windows hit 100 %; one of those hits made reviewers return nothing — §9). Where the money
went: EV animation 48 %, the lead session 30 %, storyboard 15 %, research and lyrics 7 %; SP chapters 35 %, lead 27 %,
research and lyrics 13 %, design kit and media 6 %, touch-up 5 %, 3D 5 %, clip helpers 4 %. Images read were under 7 % of
cost; the bill is the volume of context re-read, not the model price.

| Plan | One EV-class video | Verdict |
|---|---|---|
| Max 20x | 29–47 % of a week; 1.8–2.8 windows of pure compute | fits; about two per week if nothing else runs |
| Max 5x | 5-hour window ≈ $89; weekly share 50–187 % (unverified ratio); 7–11 windows | marginal: ≥ 35–55 h wall clock from throttling alone; likely spans a weekly reset |
| Pro | 5-hour window ≈ $18; 35–57 windows | infeasible for EV-class; fine for Quick tier |

Model weighting differs: one cheaper model burned about twice the limit per API-dollar. Price per model; never reuse
these constants for another model.

### 1.3 Codex (and other agent CLIs)

- **Codex (ChatGPT Pro):** a weekly window only (no 5-hour window on Pro); ≈ 5–7 M Codex tokens per 1 % of the week, so
  ≈ 0.5–0.7 B tokens a week. It did not make either video; its one job there was an hourly **watchdog** of the lead
  session (16 checks over 11 h, 0.7 M tokens, **0 points** of the weekly limit). Best used for bounded, testable work:
  tool and engine engineering, lint/QA scripts, render babysitting, queue watching, second opinions.
- **Muse Code** (Meta's coding agent, paid plans): install it from dev.meta.ai and sign in once in a terminal. The
  runner drives it headless as engine `muse` (`muse exec --json`, the prompt in a file). Use it like Codex, for bounded
  single-agent work (briefs without a Workflow run in sequence), and cross-review its output like any optional engine.
- **Any other agent CLI** the user already has, with a headless mode that reads a prompt file and prints JSON events
  and can resume a session, can take cheap bulk work (research harvests, fact-check fan-out). Treat it as optional
  overflow, **always cross-review its output** with another model, and never make it a required engine of the template:
  Claude Code and Codex cover every role (Muse Code is supported by the runner but optional, like Codex).
- Codex and Claude token counts are not comparable one to one (different context windows and re-read patterns).

### 1.4 Budget-governor rules (MUST)

1. **Preflight every fan-out** against the limits: read the current 5-hour and weekly utilisation (Claude: the last
   turn's rate-limit event; Codex: its session file; Grok Bot: the usage percent), convert the phase's expected cost to
   points, and **refuse to launch if the projected 5-hour use exceeds 85 % or the remaining week is below the projection +
   10 %**. Never start a fan-out above 60 % of the 5-hour window.
2. **Start an EV-class production right after the account's weekly reset.**
3. With extra usage (overage) enabled, every number above becomes real money at API prices; ask the user first.
4. Stagger chapter workflows: **≤ 1 parallel chapter workflow on Max 5x; ≤ 3 on Max 20x.**
5. Keep the lead's context lean: new sessions per phase, compaction, files instead of pasted transcripts.

---

## 2. What to delegate (decision table)

**Rule of thumb:** delegate what needs many tool calls or a long context; keep in Grok Bot what needs the user; keep in
**one** long-context lead session what needs the whole story in one head or spends money.

| Work | Quick | Studio | Director | Why |
|---|---|---|---|---|
| Setup, secrets (secure secret card), director chat, approvals and gates, delivery | Grok Bot | Grok Bot | Grok Bot | the shareable surface; keep turns few and fat |
| Media generation calls on the Higgsfield MCP | Grok Bot | Grok Bot / lead | lead (batch calls) or a verbatim submitter | generations cost credits, not LLM turns |
| OpenRouter submit, poll, ledger (`slop gen …`) | `slop` on the box | `slop` | lead | needs the measured lip-sync loop and the provider spend check |
| **Video prompt writing** ("the prompt is the product") | `slop` templates | lead (one context) | **lead, one context, no sub-agents** | agent-written prompts were "poses, not drama" and burned ~830 credits |
| Research and lyric fan-out | none / one agent | one agent | a workflow (EV 31 agents $44; SP 9 researchers $130); Codex (or another agent CLI, §1.3) can take fact-check fan-out | parallel, easy to verify |
| Storyboard | inline | one agent ($20–40) | 3 directors + 3 judges + head + code audit (EV $95), or the lead + one critic (SP) | taste-critical; keep on Claude |
| Motion design | data-driven default | default + one reviewer per section | animator → reviewer → fixer per chapter (EV $301, SP $348) | the biggest bill and the source of the 5-hour peaks |
| Engine/tool engineering, lint, flash/history checks, render babysitting | — | Codex | **Codex** | bounded, low-context, testable |
| Watchdog / status polling of long jobs | status files | Codex watchdog | Codex watchdog | never poll with Grok Bot turns |
| Safety and canon scan | — | one agent | a 6-agent workflow | §7 |

What never leaves the lead: the prompt book, spend decisions, the final edit decisions, fixes to shared files.

---

## 3. The engines (launch, resume, read limits)

Both run headless from a job folder (§4). Prompts live in files; the command line only says "read BRIEF.md and do it".

| | Claude Code (2.1.x) | Codex CLI (0.15x) |
|---|---|---|
| Launch | `claude -p "Read <job>/BRIEF.md and do exactly what it says. Write deliverables only under <job>/outbox." --output-format stream-json --verbose --permission-mode <mode> --permission-prompts none --add-dir <job> --allowedTools "Workflow,Read,Edit,Write,Bash(…)" --session-id <uuid> [--max-turns N] [--max-budget-usd X]` | `codex exec --json --skip-git-repo-check -c forced_login_method="chatgpt" -o <job>/last-message.txt -C <cwd> -s workspace-write --add-dir <job> -` (prompt on stdin, then close stdin) |
| Auth | the user's subscription login (no API key) | ChatGPT login; unset `OPENAI_API_KEY` and `CODEX_API_KEY` |
| Output | stream-json lines; **several `result` events per process when a Workflow or background task finishes after the main turn — wait for process exit** | JSONL `thread.started → turn.started → item.* → turn.completed` (`turn.failed`, `error`) |
| Resume | **same session only**: `claude -p --resume <session_id> …`; a Workflow resumes inside that session with `{scriptPath, resumeFromRunId, args}` (same args) | `codex exec resume <thread_id> -` (no `-s`/`-C` on resume: pass `-c sandbox_mode=…`) |
| Limits | rate-limit events in the stream (5-hour and 7-day utilisation, reset times) | only in the session's rollout file (`token_count.rate_limits`) |
| Gotchas | the Workflow tool may be off on Pro (check the init tool list); strip `CLAUDECODE`/`CLAUDE_CODE_*` env vars when launching from inside another agent; claude.ai connectors (e.g. Higgsfield) connect asynchronously, so a very short job may start without them | reads stdin if it is not a terminal: always close stdin; on Windows spawn `node …/codex.js`, not the `.cmd`/`.ps1` shim; always pass `-s` (a machine default may be full access) |

**Muse Code** (engine `muse`): the runner calls `muse exec --json --prompt-file <job>/prompt-N.md` with the job's
approval mode and workspace, and resumes with `--session-id`. Install it from dev.meta.ai and sign in once in a
terminal; `node runner/deleg.mjs doctor` shows whether it is found.

**On the bot's computer.** The runner also runs on the box (Linux), so the Director tier no longer needs the user's
PC: `slop agents install ENGINE` puts Claude Code, Codex, Muse Code or Gemini CLI under `/workspace/.claudia`,
`slop agents login ENGINE` signs it in headless (codes only through the secure secret card), `slop agents test ENGINE`
proves it with one tiny run, and `slop agents use codex --for director` makes `deleg.mjs new` (without `--engine`)
pick that engine for every brief whose `engines:` line lists it; Workflow briefs then run step by step. Gemini CLI
runs one-off jobs only (`--engine gemini`). At most 2 agent jobs run at once on the whole box (`DELEG_BOX_SLOTS`);
more wait as queued. The full guide is `docs/96-setup-and-hardware.md` §4.

General gotchas for any agent CLI: on Windows, `.cmd` launchers can cut a prompt at `" & | % ^ < >`, so pass the prompt
as a file; a CLI that updates itself can delete the binary a running job uses, so turn its auto-update off for long
jobs and pin the version; give it a dedicated working folder, never `/`.

**Workflow scripts** (Claude Code's Workflow tool: `agent()`, `parallel()`, `pipeline()`, `phase()`, `log()`, JSON-schema
results) are the music videos' orchestration primitive. Rules:
- The script file must live **inside the job folder or an `--add-dir` directory**; resuming from a path in the session's
  own store was refused.
- **Journals are not durable.** Copy the run record (`wf_<id>.json`: the full script, args, result, per-agent states) into
  the project's `runs/` folder when a run ends. Derive run status from the record, not from a hand-kept log.
- A run that says `completed` can hide dead agents (a usage limit makes an `agent()` return `null`): scan `logs[]` and every
  agent's state; treat null results as failures (`80-review-qa.md` §8.4).
- `Date.now()`, `Math.random()` and `new Date()` throw inside scripts (they would break replay).
- Concurrency per workflow is `min(16, CPUs − 2)` agents; on a 4-CPU server that is 2, so parallelism comes from running
  2–3 workflows side by side. **Only one rendering workflow at a time** (six agents rendering at once filled swap and the
  root disk); keep scratch on the big disk, never `/tmp`; check free memory and disk before fanning out.

---

## 4. The runner (`runner/deleg.mjs`) and the job folder

The engine never talks to Grok Bot directly. Grok Bot writes a job folder; the runner launches the engine detached
(double-spawned, so it survives the bot's shell, a daemon restart or an app update) and normalises its stream into small
files; Grok Bot reads them later.

```
<project>/jobs/<YYYYMMDD>-<4hex>-<slug>/
  job.json            engine config (engine, model, effort, permission/sandbox, allowed tools, add_dirs, max_turns,
                      max_budget_usd, timeout_s, allow_spend, pass_env, max_parallel, stop_above_utilization)
  BRIEF.md            the prompt (§5), filled from a template in templates/briefs/
  wf/<name>.js        a workflow script, if any (copied from templates/workflows/; must be inside the job folder)
  outbox/             the ONLY collected output, written continuously (a cut at any moment leaves valid output)
    report.md         ≤ 1 page: done / failed / skipped, wall time, tokens, what changed and why, flags for the user
  status.json         normalised state (queued|starting|running|done|failed|stopped|lost), engine, tokens, result text,
                      error + the next command to run                            ← runner-owned
  progress.log        one compact line per event                                 ← runner-owned
  raw-<N>.jsonl       lossless engine output of attempt N; stderr-<N>.log
  RUNS.md, runs/      the job's session/run ids; copies of each workflow's run output (dead agents flagged)
  outbox.tgz          the outbox packed at the end (one file to copy back to the bot's computer)
<project>/RUNS.md     every long run id with how to resume it (`slop runs add <id> --kind deleg --what … --resume …`)
```

| Command (`node runner/deleg.mjs …`) | What it does | How the bot uses it |
|---|---|---|
| `new auto --project <project> --brief <name> [--engine claude\|codex\|muse] [--workflow W] [--set K=V …]` (or `new <jobdir> --brief <name> …`; `auto` needs `--project`) | builds `<project>/jobs/<id>/` from a brief template; a missing variable fails with the `--set` line to add | foreground, once |
| `run <job>` | start if needed, then follow until the job ends; prints progress, ends with `STATUS {json}` | **one background shell per job** |
| `start <job>` | launches the detached supervisor; returns in < 1 s | foreground |
| `status <job>` | one JSON line with the state and the next command to run | foreground |
| `wait <job> 25` | new progress lines, then `STATUS {json}` after ≤ 25 s | foreground poll |
| `stop <job>` | stops the job and kills the engine's process tree | foreground |
| `resume <job> [prompt-file]` | a new attempt in the same session/thread (a stopped, failed or lost job) | foreground |
| `list`, `pack`, `unpack`, `doctor`, `selftest`, `preflight <engine>` | housekeeping; `selftest` is free; `preflight` sends one tiny prompt | as needed |

Every command prints one JSON line (`{"ok": true, …}` or `{"ok": false, "error": …, "fix": …}`); exit code 0 = ok/done/
running. Other engine names the runner accepts are listed by `node runner/deleg.mjs --help`.

The shipped brief templates (`node runner/deleg.mjs templates` prints each with its variables):

| Brief | Workflow it runs | Variables you usually `--set` (the rest come from `project.json`) |
|---|---|---|
| `research-lyrics` | `research-lyrics` | `TODAY`, `CONCEPT`, `TOPICS`, `OWNER_NOTES`, `LIKES`, `STRUCT`, `EXISTING_LYRICS` |
| `storyboard-panel` | `storyboard` | `OWNER_QUOTES`, `LEAD_MIN`, `MOTION_S`, `MOTION_CLIPS` |
| `prompt-book` | none (one context on purpose) | `STORY`, `CLIPS` |
| `chapter-motion` | `chapters` | `CHAPTERS` (a JSON list), `OWNER_QUOTES`, `MODE`, `ROUNDS` |
| `review` | none (one agent) | `TARGET`, `T0`, `T1`, `ROUND`, `OWNER_QUOTES` |
| `safety-scan` | `safety-scan` | `LIST` (default `render/scan-list.json`), `TOTAL`, `WORLD`, `FIX_RULES`, `BLOCK_RULES`, `SLICES` |
| `generic` | none | `TASK`, `ROLE`, `GOAL`, `CHECK`, `FILES`, `RULES`, `CHEATS`, `FIRST`, `METHOD`, `BUDGET`, `DONT` |

A worked example, the safety scan of 96 takes (one foreground `new`, then one background `run`):

```
node runner/deleg.mjs new auto --project my-song --brief safety-scan --set TOTAL=96 \
  --set WORLD="a lyric video about a siren and a sailor; ancient Greek galley, sea rocks, a modern rave; a small satellite dish on the mast is deliberate"
# → {"ok": true, "job_dir": "<project>/jobs/<id>", …, "next": "node …/deleg.mjs run …"}; then run `next` as one background shell:
node runner/deleg.mjs run "<project>/jobs/<id>"
``` Safety defaults: API-key environment variables are stripped so the engines bill the user's **subscription**, not
an API key (override only with `--allow-api-billing`); the toolkit's own secrets are never passed to a worker unless
`pass_env` names them; Claude's paid-generation connector tools are denied unless `allow_spend` is true; at most
`max_parallel` (default 3) jobs run per jobs folder; `stop_above_utilization` stops a job when the account's usage window
passes the given share. Any job.json field that widens what a job may do needs its flag on the `run` command line too
(`--allow-api-billing`, `--allow-spend`, `--pass-env NAME`, `--allow-raw`), so the approval card shows it; jobs declare
`requires` (slop, render, ffmpeg) and fail in seconds with the setup fix when the user's computer lacks them; chapter
and review jobs share `queue_group: "render"`, so only **one rendering job runs at a time** per jobs folder, and each
chapters workflow keeps at most 2 chapters in flight (`--workers 2` on every render). Chapter jobs carry
`wire_chapters`: the runner (or the workflow's Setup step) runs `node runner/deleg.mjs wire <project> --chapters
<job.json>`, which creates placeholder chapter files and merges `engine/ch/_index.js`; `wire --check` must print WIRED
for every chapter before a review counts. Full reference: `runner/README.md`.

**Running it from Grok Bot's local exec** (the user's own computer):
- A foreground command gets ~30 s; background commands have no timeout and write to a terminal file the bot can read.
  Keep every foreground call under 25 s and its output to a few KB.
- With the machine on "Ask every time", **every distinct command string needs its own approval card** that only that
  computer can answer. So use **one background `node "<abs path>/deleg.mjs" run "<abs job path>"` per job** (one card),
  read its terminal file and `status.json`, and write `job.json` + `BRIEF.md` in as few commands as possible. "Always
  allow" is the user's decision, never the bot's suggestion to make silently.
- Use absolute paths, quoted; forward slashes in JSON on Windows (shells eat backslashes).
- The bot never types or reads the user's credentials; the engines use the user's own logins on their own machine.
- Poll at a 5–10 minute cadence in the bot's own turns, or let a Codex watchdog do it.

---

## 5. Writing a brief

"The prompt is the whole brief — nobody answers questions mid-job." Every brief has these parts, in this order:

1. **Identity and situation.** "You are <role> on <project>, running unattended. Nobody answers questions mid-run; make
   sensible calls and finish." Then the PREFACE: "Workspace: <job>. Put every deliverable in <job>/outbox (files, reports,
   data); it is collected when you finish. End with a concise summary of what you produced and anything you could not
   do."
2. **READ FIRST, fully:** `PRODUCTION.md`, then the stage's binding spec (`DESIGN.md`, the storyboard entries, the
   relevant `docs/` file), then the exemplar.
3. **The owner's words, verbatim** (the bar quotes, the notes that concern this stage; `70-motion-design.md` §0).
4. **The goal as a measurement** and where the authoritative check lives: "done = `slop render lyrics --from 40.4 --to 58.6` prints
   N/N, the sheets show …, and `outbox/report.md` exists". The worker's own PASS is a hint; the orchestrator re-runs the
   check with something the worker could not edit.
5. **Files:** what each input is; **which files it may edit (usually exactly one)**; which it must not touch.
6. **Rules:** the mechanical ones the validator enforces, then the ones the owner reviews.
7. **Method, in order, with a bounded first deliverable:** "read X → a complete rough draft within ~10 commands → measure →
   fix the worst first". Reviewers: "write the short version first, refine if time remains."
8. **Budgets:** spend caps (or "no generation of any kind"), commands to first deliverable, minutes per item.
9. **You do NOT** — what the role never does (other roles' files, shared code, spending, re-deriving authoritative
   numbers, editing the reference copies) and **where to ask** for what it lacks (`requests.md`, a "Tooling problems"
   section at the top of the handoff).
10. **Handoff and report format** with a length cap; the finish condition ("mark complete only after …").

Brief templates live in `templates/briefs/` (`node runner/deleg.mjs templates` lists them and their variables). Workflow
scripts live in `templates/workflows/`, parameterised for any project: `research-lyrics.js`, `storyboard.js`,
`chapters.js` (animate → review → fix → review → fix) and `safety-scan.js`. A refit or touch-up pass reuses the chapter
pipeline with a "no generation; re-key to the new footage" brief and the open fixes passed in.

---

## 6. The binding plan: `PRODUCTION.md`

Before launching anything parallel, the lead writes one binding plan, and **every agent prompt begins "READ FIRST:
PRODUCTION.md"**. Its sections (skeleton: `examples/production-skeleton.md`):

1. **The go message, verbatim**, plus every follow-up note, verbatim.
2. **Deliverable:** length, resolution, fps, file paths, title.
3. **The rules every agent follows** (a numbered checklist; SP's eight): the lyric gate; the camera and edit play the
   track with ≤ 3 flashes/s; the look; the motion-design bar; the lip-sync method (no model fallbacks); identity (face from
   text; image references only where the user allowed; two clips never from the same frame; declines final, never alter an
   image; another provider OK); taboos and real-person rules; machines and disk.
4. **Budget per pool:** available / cap for this production / where the ledger is / the real-billing endpoint / unit
   prices. SP: OpenRouter **$185 of $200.91** (singing $80 · motion $70 · retakes and fixes $35); Higgsfield **950 of
   1,181.65 credits** (previz-driven clips ~500 · declined windows ~300 · reserve 150).
5. **Stages, owners, gates** (a table): # · stage · owner (main / which workflow) · output · gate. SP: 0 bootstrap (a
   sheet renders) → 1 clip plan (cost ≤ caps) → 2 clips (coverage report) → 3 kit (review pass) → 4 media (spot checks) →
   5 3D (QA sheets) → 6 chapters (lyric N/N, history check, review pass) → 7 whole-film review (panel pass) → 8 render and
   deliver (ffprobe).
6. **Chapter map:** file · sections · from–to (s) · shots.
7. **File contracts** ("so parallel owners don't collide"): exactly one writer per file — only the clips workflow edits
   the clip plan; only the kit workflow edits the shared engine, additively (existing renders must stay byte-identical);
   each animator edits only its chapter and reports shared bugs; mattes, depth and 3D sequences have fixed paths and
   formats; every run id and its args go in the project's `RUNS.md` (`slop runs add`).
8. **Status log, newest first:** timestamped paragraphs of what happened, with numbers and decisions.

New decisions go into `PRODUCTION.md` / `DECISIONS.md` **first**, then into briefs. Workers that re-read the shared files
mid-task pick them up ("decisions written into shared files reach running workers").

---

## 7. Workflow shapes per stage

| Stage | Shape | Notes |
|---|---|---|
| Research | parallel topic agents (shared brief, tags for source strength, freshness buckets, a "handle with care" list, ≤ 350-word summaries) → the lead synthesises one shortlist; EV added an **adversarial verifier** per 10 claims ("try to REFUTE it … default to 'unverifiable'") | research and lyrics in **separate turns** ("so no single response is doing everything at once"; a do-everything reply was blocked by a content filter) |
| Lyrics | the lead writes with the user live, scored by the scansion tool calibrated to the user's verdicts (SP); or 4 angle writers → 3 judges → merge → critic (EV) | never optimise a metric past the user's ear |
| Storyboard | 3 directors (purist / density / narrative) → 3 judges with a numeric schema → head director merges and **checks with code** (the board audit); or the lead from the user's walkthrough + one critic who knows neither the source myth nor the memes | judge schema: `{board, total, hook, lead_coverage, lyric_video, jokes, taste_fit, feasibility, arc, best[], fixes[]}`; check the judges' board names match the angle keys (an empty-judges bug once passed silently) |
| Video prompts | **the lead, alone, one context**, after reading the storyboard, every first-frame plate and the exact word/hit times of each window | the user reads the book before any spend |
| Mechanical spend | a **verbatim submitter**: a small agent that submits a request file exactly as written, retries only failed items once, never resubmits an item with a job id, writes the job ids to a file | keeps the lead's context and money safe; "write a manifest immediately after each batch submit" |
| Design kit | engine additions + project kit + `DESIGN.md` + an **exemplar chapter**, reviewed as soon as it exists | split slow media work (mattes, depth) into its own workflow: a parallel barrier once held the kit review for 3+ h |
| Chapters | per chapter: animate → review on real renders → fix → second review (skipped if passed) → last fix; 3–4 chapters per workflow (EV ran 2–3 workflows in parallel; the toolkit runner queues rendering jobs one at a time per jobs folder, so split the chapters across workflows only when the renders are light) | null review = failure; carry open fixes into the next pass as an explicit `fixes` argument; write `engine/ch/_index.js` (every chapter file, in time order) before launching, or the chapters never render (`70-motion-design.md` §16) |
| Refit / touch-up | per chapter, after footage changes: refit or touch up → check → one fix; **no generation of any kind** | briefs per chapter written by the lead from the scan findings |
| Safety scan | N agents, each takes a slice of a **list file** | `80-review-qa.md` §9 |

---

## 8. The management rules (incident-backed; MANAGEMENT.md, condensed)

The owner keeps a living document of rules for agent swarms, each "paid for: it names the run, the date and what it cost".
The ones that apply here:

**The goal is a measurement**
- **Write the acceptance test before the brief.** "Replicate this exactly" became "the judge prints PASS"; without it
  "exact" would have been argued, not measured.
- **The reference copy the worker can edit is not the one that counts.** Re-run the check yourself on a copy the worker
  could not touch; a worker's own PASS is a hint.
- **Define cheating explicitly, then check precisely.** False positives cost trust ("a flag that is wrong twice gets ignored
  the third time"): hash the reference files at spawn; scan code with a tokenizer, not a grep of comments.
- **Granularity of the spec is the definition of pass:** one element per thing you would complain about.
- **Workers optimise the metric, not the goal.** Whenever a metric has a floor, ask what a worker could remove and still
  clear it, then check the parts; when rules tighten, re-judge every earlier pass.
- **Every human observation becomes a metric the same day.** "If a reviewer can see it and the judge cannot, the judge is
  wrong." And **every human question becomes a required field.**

**Bound the work**
- **Bound the first deliverable in commands, not minutes.** "Draft first, measure second": a worker that spent 75 minutes
  probing delivered nothing; the brief now says "first judge run within ~10 commands, handoff mandatory".
- **Bound reviewers by output, not by time.** Tell a role what is authoritative and forbid re-deriving it; "a retro that
  exists beats a thorough one that does not."
- **Say what a role does NOT do,** and give it a channel to ask (`requests.md`), so a blocked worker asks instead of
  building another role's tools.

**Transfer and interruption**
- **Learning must transfer between units of work:** a shared playbook edited by exactly one role (the reviewer), a library
  of things that already passed (seeded before the first epoch), tools that ship only with a before/after proof, and a
  handoff per unit so the next worker continues instead of restarting.
- **Design for interruption from day one:** progress on disk continuously; resume from the last artifact. "Any long run
  whose progress lives only inside a session is a run you cannot touch."
- **The orchestrator must be restartable mid-flight:** keep its state in files; on restart **adopt** in-flight jobs instead
  of respawning them.
- **Sessions die with the endpoint;** stop the scheduler, cut, relaunch, resume — in that order. Probe a shared endpoint
  before respawning work into it.
- **"Drained" must distinguish no-work from can't-start:** check the job's error before concluding there is nothing to do
  (an agent-CLI auto-update once made every new session fail instantly, read as "no work").
- **Cancelling a goal-mode job does not stop its shells:** clear the goal, cancel, then kill its processes by tag. Beware
  `pkill -f <pattern>` matching its own shell.
- **Guard the host's disk, not the guest's:** a VM's disk grows on the host drive.
- **Preflight prompts carry no context** ("Reply with exactly: PREFLIGHT-OK"); a diagnosis in a preflight's title made the
  agent probe its sandbox instead.

**Throughput, reporting, spending**
- **Throughput is per stream, and agents are serial:** wide parallelism pays for embarrassingly parallel per-unit work;
  iterative loops want fewer, faster streams. Reserve capacity for the humans sharing the endpoint.
- **Reports are a dashboard, not a feed:** one report file rewritten in place plus one notification when a job settles.
  "If a human would delete it the next morning, do not emit it."
- **Show real renders early.** The two most valuable corrections of one run came from the owner looking at four images.
- **Spend the expensive agent at the boundaries** (design the test, write the briefs, look at samples, rule on flagged
  cases, fix the pipeline); push everything repeated to cheap workers with a validator behind each. **Measure the
  delegation before trusting it** (score worker output against your own on a few units first).
- **Check paid APIs against the provider's billing, not a local ledger.** "Submitted" with no job id, 5xx errors and
  content-filter refusals were silent failures in the ledger; an API key's own spend limit returned 403s while the account
  still had credit; ledgers counted free declines against the cap.

**From the videos**
- **Reviewers of rendered frames were worth it:** first-draft chapter scores were 5–6.5/10; concrete fix lists (faces
  printing blank, type over faces, repeated devices) closed most gaps.
- **Workers report shared-file bugs instead of fixing them;** the operator fixes them once, centrally.
- **The user watches workers' intermediate renders:** fix the look centrally before fanning out; put colours in semantic
  tokens so a late palette change is one line plus a parallel per-file pass.
- **A blocked action is a stop, not a puzzle.** When the harness blocked a workaround for a provider's safety filter, the
  right move was to stop, remove the automation that did the same thing, route around it with legitimate means, and tell
  the user.
- **Generator agents wrote poses, not drama, and spent before anyone read them.** The owner's bar: every prompt has
  timestamped beats, full blocking, the story beat, and action *and* reaction for everyone in frame; the lead writes them
  in one context and the owner reads them before any spend.
- **When the owner flags quality mid-run, stop every workflow that can spend, then fix** (§10).
- **Don't spend context reviewing bad takes when the prompts were the fault:** re-make them ("please don't. make all new
  ones, your egoing to burn your whole context window doing that then fail at prompts again.").
- **Many waiters on one machine: poll one shared listing**, not one wait loop each (two dozen waiters pinned a GPU box's CPU
  and made every job 3–5× slower). Record each job's id beside its inputs; adopt queued jobs on restart. Queue background
  post-processing only for takes the edit uses, in priority order; cancel superseded jobs (a per-import post became a ~20 h
  queue).

**The launch checklist (verbatim)**
- What exactly prints PASS, and where does the copy the worker cannot edit live?
- What counts as cheating, and how precisely is it detected (false-positive rate)?
- Is the spec at the granularity of the things you will complain about?
- What is the first deliverable, and within how many commands?
- What does each role NOT do? Where does it ask for what it lacks?
- What transfers between units of work (playbook, library, handoff), and what seeds it?
- What happens when the endpoint restarts mid-run? Where is progress on disk?
- How fast is one stream under the real workload, and how many streams do others need?
- Where do humans look (one report file), and what do they never receive (per-job notes)?
- Which observations from the first samples became metrics?

---

## 9. Interrupt and resume (lessons)

- **A user interrupt kills every running workflow, not just the foreground call.** EV's storyboard merge restarted three
  times (~1.5 h lost). So: keep each phase short; split the audit into its own agent; prefer three small parallel workflows
  to one long one (EV's chapters: ~12 h serial vs ~4 h as three parallel workflows).
- **Save every run id with its exact args** in `RUNS.md` (`slop runs add`) the moment it starts; resume with the same script path, the
  same args and the run id, in the **same session**. Replay re-uses every unchanged `agent()` call from the journal and runs
  only the changed or unfinished ones (EV's resumed storyboard replayed the 3 directors and 3 judges from cache and re-ran
  only the merge).
- **Usage limits end runs quietly.** Agents that start while the account is at its limit return nothing; the run still says
  completed. Read every agent's state; carry the open items into the next run explicitly ("chapter 04 was never reviewed:
  the review failed on a usage limit").
- **A long list goes in a file, not in the launch args** (a placeholder once launched in place of 96 file paths).
- **Spending agents write a manifest after each batch submit,** so an interrupt never loses which jobs exist (and nothing is
  resubmitted).
- **Coordinate parallel agents through files:** e.g. the second agent waits for a sentinel file (`windows-submitted`) in
  short polling calls, and goes anyway after a stated timeout.
- After an interrupt, resume or adopt; never blindly re-run a stage that spends.

---

## 10. The stop-spend protocol (on any owner quality flag)

1. **Stop every workflow and job that can spend** — not just the one the owner named. Search each running script and brief
   for its generate/submit calls (SP's 3D workflow still had its own Higgsfield stage and would have spent after a credit
   reset).
2. Confirm at each provider that nothing is still queued (`slop spend` for OpenRouter; the Higgsfield connector's
   `balance` and job tools for Higgsfield).
3. Log the owner's words verbatim in `DECISIONS.md`, as a rule, before anything else.
4. Fix the cause (usually the prompts), re-brief, re-make — don't review the bad outputs.
5. Do not let a deadline (a credit reset, "spend it within the hour") drive spending on unread prompts.

---

## 11. Reporting to the user

- One `STATUS.md` (or the run report) rewritten in place: stage, what is running (ids), spend so far from the provider,
  gates passed, what needs the user.
- One message when a job settles or a checkpoint is reached; nothing per sub-job.
- Ids and titles when you start long jobs, so the user can find them.
- Real renders (contact sheets, short clips) early and at every checkpoint.
