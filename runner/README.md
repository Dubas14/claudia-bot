# runner/ — delegate a job to the user's own Claude Code, Codex or Muse

`deleg.mjs` is how the Claudia Grok Bot (Director tier) hands heavy work — the storyboard panel, chapter motion design,
the prompt book, reviews, the safety scan, research and lyrics — to the agent subscription **on the user's own
computer**, without spending Grok Bot turns while it runs. One job = one folder. The runner starts the engine in a
detached supervisor (it survives the bot's shell, a Grok Bot restart or an app update), turns the engine's event stream
into a few small files, packs the results into one archive, and never asks anyone anything.

- Node 18.17+ (20+ recommended), **no dependencies**, Windows / macOS / Linux.
- Engines: **Claude Code** (`claude -p`, stream-json, the Workflow tool allowed) — best for panels and motion design;
  **Codex** (`codex exec --json`) — a strong single worker; **Muse Code** (`muse exec --json`; install it from
  dev.meta.ai); **Gemini CLI** (`gemini -p -o stream-json`; single-agent, write-only work, pass `--engine gemini`; §5).
- Where: on the **user's own computer** (below), or on the **bot's own computer** once the engines are installed there
  with `slop agents` (§1b) — then the Director tier needs no home computer at all.
- Free self-test: `node deleg.mjs selftest` runs a fake engine (`fake-engine.mjs`) through two scenarios: a Claude
  workflow job (the second result is the final one, a dead agent becomes a warning, the outbox is packed) and `stop`
  killing the engine's process tree. No model call. The test suite (`tests/test_deleg_*.py`) covers the rest.

**Placeholders** in this file (always write absolute paths in double quotes with forward slashes — they work in
PowerShell, cmd, Git Bash, zsh and bash):

| Placeholder | Meaning | Example |
|---|---|---|
| `<HOME>` | the user's home folder on their computer | `C:/Users/you`, `/Users/you` |
| `<TK>` | the toolkit checkout on the user's computer | `<HOME>/claudia` |
| `<PROJECTS>` | the projects folder on the user's computer | `<HOME>/slop/projects` |
| `<name>` | the project's folder name | `my-song` |
| `<PROJ>` | the project on the user's computer | `<PROJECTS>/<name>` |
| `<id>` | a job id (`new` prints it) | `20261001-a1b2-storyboard-panel` |
| `<BOX_TK>` | the toolkit checkout on the bot's computer | `/workspace/claudia` |
| `<BOX_PROJ>` | the project on the bot's computer | `/workspace/slop/projects/<name>` |
| `<XFER>` | a transfer folder on the bot's computer | `/workspace/xfer` |

**Where files can go.** Grok Bot's local exec can read, write and copy files **only inside the user's home folder**
(paths outside it are refused). Shell commands are not confined. So every copy target below is under `<HOME>`, and the
home folder itself always exists (whether `CopyFromBox` creates missing folders is unknown — never rely on it).

---

## 1. One-time setup on the user's computer (the bot walks the user through it)

The user installs and signs in to the engine themselves; the bot never types or reads credentials.

| Step | Who | Command |
|---|---|---|
| Install Node 20+ and Claude Code (or Codex); sign in once in a terminal (`claude` → their Claude plan; `codex login` → "Sign in with ChatGPT") | user | — |
| Get the toolkit: `git clone https://github.com/<org>/claudia "<TK>"` (or unzip a release into `<TK>`) | user or bot (1 card) | |
| **Install the toolkit runtime** (Python 3.13 venv + the toolkit + Chromium; the workers' checks run it) — macOS / Linux | bot, background (≈ 5 min) | `bash "<TK>/bin/setup.sh" --minimal` |
| … the same on Windows (four commands, PowerShell or cmd; the user installs uv and ffmpeg if `winget` is missing) | bot, background | see "Windows" below |
| Check the machine: engines, toolkit CLI, ffmpeg, and one render on a scratch project | bot, foreground | `node "<TK>/runner/deleg.mjs" doctor --render` |
| Prove the runner works here (free) | bot, foreground | `node "<TK>/runner/deleg.mjs" selftest` |
| One tiny real prompt (a sliver of the plan; shows whether the Workflow tool exists) | bot, foreground | `node "<TK>/runner/deleg.mjs" preflight claude` |
| One tiny real **workflow** (a subagent writes a file with Bash and one with Write — the path every workflow job takes) | bot, **background** (1–3 min) | `node "<TK>/runner/deleg.mjs" preflight claude --workflow` |

**Windows (the toolkit runtime).** `bin/setup.sh` does not run on Windows; these do the same (`~/.claudia` is where the
runner looks for the toolkit's Python):

    winget install --id astral-sh.uv -e
    winget install --id Gyan.FFmpeg -e
    uv venv --python 3.13 "<HOME>/.claudia/venv"
    uv pip install --python "<HOME>/.claudia/venv/Scripts/python.exe" -e "<TK>"
    "<HOME>/.claudia/venv/Scripts/python.exe" -m playwright install chromium

(Open a new terminal after the two `winget` lines so `uv` and `ffmpeg` are on PATH. Without winget:
`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` installs uv.) The renderer also
works with an installed Google Chrome if the Chromium download is blocked.

`doctor` lists the engines it found, their versions, the Codex login, `tar`, the env vars that will be stripped, and
`slop_ok` / `render_ok` / `ffmpeg_ok` with the fix for whatever is missing. `preflight claude` returns
`has_workflow_tool`; if it is `false` (Claude Pro plans default it off), set `"workflows_env": true` in workflow jobs
(sets `CLAUDE_CODE_WORKFLOWS=1`; tell the user workflows use a lot of their plan). `preflight claude --workflow` returns
`subagent_tools_ok`; if it is not `true`, do not start workflow jobs yet (send its `progress.log` and `runs/` to the
bot). If it is still running when the command returns, re-read it with
`node "<TK>/runner/deleg.mjs" preflight claude --job "<the job folder it printed>"`.

Jobs whose briefs run the toolkit (`requires` in job.json: storyboard and research need `slop`; chapters and reviews
need `slop` + `render`; the safety scan needs `ffmpeg`) re-check it on start and fail **in seconds** with the setup fix,
never hours into a run.

## 1b. On the bot's computer instead (no home computer; `slop agents`)

The agents can live on the bot's computer. A computer update there removes installed apps and packages and keeps
`/workspace`, so every agent COMMAND goes under `/workspace/.claudia` (`$SLOP_HOME`): npm installs in `$SLOP_HOME/npm`,
Muse Code in `$SLOP_HOME/muse`, and Claude Code's native binary (its official installer writes `~/.local`) is copied to
`$SLOP_HOME/claude/versions/<version>/claude`. Every command is linked in `$SLOP_HOME/bin`, which the runner searches
first. Re-running `slop agents install all` after an update repairs anything missing in seconds.

The SIGN-INS stay where each CLI keeps them, in the home folder (`~/.claude`, `~/.codex`, `~/.gemini`,
`~/.config/muse`). The platform says logins are kept, but that is not verified for these files: if `slop agents status`
says "not signed in" after an update, run `slop agents login ENGINE` again. The user signs in with their own plan; the
bot only ever moves the link and, for Claude Code and Gemini CLI, the code the sign-in page shows (through the **secure
secret card**, never chat; `--code-from-env` reads only `CLAUDE_LOGIN_CODE` / `GEMINI_LOGIN_CODE`).

| Step | Command (bot's computer) |
|---|---|
| Install (a background job; all four ≈ 35 s, ≈ 1.3 GB with the Claude copy) | `slop agents install claude` (or `codex`, `muse`, `gemini`, `all`), then `slop job wait ID` |
| Sign in | `slop agents login claude` → the user opens the link and approves → secure card `CLAUDE_LOGIN_CODE` → `slop agents login claude --code-from-env CLAUDE_LOGIN_CODE` |
| … Codex / Muse (device code) | `slop agents login codex` → the user enters the code at the link → `slop agents login codex --check` |
| … or a token | the user runs `claude setup-token` on their own computer → secure card `CLAUDE_CODE_OAUTH_TOKEN` → `slop agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN` (Gemini: `--key-from-env GEMINI_API_KEY`) |
| Prove it (one tiny reply) | `slop agents test claude` (a rejected sign-in prints the exact way out: `login ENGINE --force`, or a new token from the user) |
| Choose | `slop agents use codex --for director` — it prints which briefs follow it (see below); `slop agents use codex --for images` |
| Plan usage (no tokens spent) | `slop agents status --limits` |

**What `use … --for director|review` changes.** `new` without `--engine` takes the chosen engine only for a brief whose
`engines:` line lists it, and says so in `engine_from` / `engine_note`. Workflow briefs (storyboard-panel,
research-lyrics, chapter-motion, safety-scan) use Claude Code's Workflow tool; with Codex or Muse they run WITHOUT it,
step by step (the brief's own method for those engines; slower). A brief that does not list the engine (e.g. Muse for
research-lyrics) stays on Claude, with a note. An explicit `--workflow W` always means Claude; an explicit
`--engine codex|muse|gemini` on a workflow brief also runs it without the workflow. Gemini CLI is not offered
as director or review agent (no brief lists it); `--engine gemini` still runs one job on it.

Then the job loop is the same as §2 without any copying: `node /workspace/claudia/runner/deleg.mjs new auto --project
<name> --brief <b>` and `node /workspace/claudia/runner/deleg.mjs start <job>` (it returns at once), then `wait <job> 25`
in later turns. The box also renders, so at most 2 agent jobs run at once on the whole computer, across every project's
jobs folder (box-wide slots in `$SLOP_HOME/agents/slots`; `DELEG_BOX_SLOTS` changes the number; the tiny preflight
of `slop agents test ENGINE` is exempt); the others wait as `queued` and say why. The same `slop agents` commands
work on the user's own computer through local exec once the toolkit runtime is installed there (§1); there the sign-in
links can simply be opened on that computer.

## 2. The job loop — exact commands

Grok Bot reaches the user's computer only through local exec (`Shell`/`AwaitShell` with a `machineId`, shown as
"MachineShell") and `CopyFromBox` / `CopyToBox` (100 MiB per file). A foreground command gets ~30 s; a background one has
no limit and writes to a terminal file the bot can read. With "Ask every time", **every distinct command string and
every copy is one approval card that only that computer can answer** — so the loop below uses as few as possible.

**(a) The project's inputs to the user's computer (a "sync").** A job only reads what the project folder on the user's
computer holds, so sync what its kind needs (sizes for a 3-minute song):

| Job kind | What it reads | Sync | Size → archive parts (cards) |
|---|---|---|---|
| storyboard, research-lyrics, prompt-book | project.json, DECISIONS.md, PRODUCTION.md, lyrics/, analysis/, taste/, research/, board/ (+ plates/picks for the prompt book) | **small** | 1–20 MB → 1 part |
| chapters, review | the above + `engine/` (the engine assets `slop edit export` wrote: clip frames, plates, data) + `edit/` + `audio/song.wav` | **render** | 0.3–1.5 GB → 4–16 parts |
| safety-scan | project.json, DECISIONS.md, board/STORYBOARD.md and the takes its list names | **takes** | 0.2–1 GB → 3–11 parts |

On the box (one command; `split` only when the archive is over 95 MiB):

    # small
    mkdir -p <XFER> <BOX_PROJ>/jobs && cd /workspace/slop/projects && tar -czf <XFER>/<name>.tgz --exclude='<name>/render' --exclude='<name>/out' --exclude='<name>/jobs/*' --exclude='<name>/audio' --exclude='<name>/clips' --exclude='<name>/engine' --exclude='<name>/plates/cands' <name>
    # render (chapters, review): run `slop edit export` on the box first, so engine/ is current
    mkdir -p <XFER> <BOX_PROJ>/jobs && cd /workspace/slop/projects && tar -czf <XFER>/<name>.tgz --exclude='<name>/render' --exclude='<name>/out' --exclude='<name>/jobs/*' --exclude='<name>/audio/stems' --exclude='<name>/audio/windows' --exclude='<name>/clips' --exclude='<name>/plates/cands' <name>
    # takes (safety scan): the list file plus every file it names
    cd /workspace/slop/projects && { printf '%s\n' <name>/project.json <name>/DECISIONS.md <name>/board/STORYBOARD.md <name>/render/scan-list.json; jq -r '.[].file' <name>/render/scan-list.json | sed 's#^#<name>/#'; } | tar -czf <XFER>/<name>.tgz -T -
    # then, only if the archive is over 95 MiB:
    split -b 95m -d -a 3 <XFER>/<name>.tgz <XFER>/<name>.tgz.

A later sync can be a **delta** (only files changed since the last one; usually 1 part): `touch <XFER>/<name>.stamp`
after each sync, and next time `cd /workspace/slop/projects && find <name> -type f -newer <XFER>/<name>.stamp ! -path '*/render/*' ! -path '*/out/*' ! -path '*/jobs/*' | tar -czf <XFER>/<name>.tgz -T -`.

`CopyFromBox` the archive (or each `.000`, `.001` … part) to **`<HOME>/`** on the user's computer (one card per file),
then one foreground command:

    node "<TK>/runner/deleg.mjs" unpack "<HOME>/<name>.tgz" "<PROJECTS>"            (for parts pass the .000 file)

**Never sync a project while one of its jobs is running on the user's computer**: the archive would overwrite the
chapter files a job is editing. `unpack` refuses while a job of that project runs (it lists them); wait for the job to
end. (`--force` overrides; never use it while chapter jobs run.)

**(b) Per job: build the job on the box** (no cards). The brief is filled from a template, and the project's own values
(title, duration, lead canon, banned words from project.json `"banned"` …) are filled in automatically:

    node "<BOX_TK>/runner/deleg.mjs" new auto --project <name> --brief storyboard-panel --set OWNER_QUOTES="…"

It prints `job_dir`, `copy_from_box` (the job.json path on the box), `user_run_command` and `next`. `job.json` is
**self-contained** — the brief text is embedded and the paths are filled on the machine that runs it — so it is the only
file to send. `gates_needed` lists any flags the run command needs (see "Gates"; normally empty).

**(c) Send it:** `CopyFromBox` `<BOX_PROJ>/jobs/<id>/job.json` → `<PROJ>/jobs/<id>.job.json` (the folder `<PROJ>/jobs/`
exists after a sync). **1 card.** If that folder is missing, copy it to `<HOME>/<id>.job.json` instead: `run` puts the
job into `<PROJECTS>/<name>/jobs/<id>/` by itself (job.json names its project).

**(d) Run it: ONE background local command. 1 card.** Exactly the `user_run_command` that `new` printed:

    node "<TK>/runner/deleg.mjs" run "<PROJ>/jobs/<id>.job.json"

`run` creates `<PROJ>/jobs/<id>/` from the file, starts the job if it is not running, then follows it: one compact
progress line per event (the first one shows the effective gates), a heartbeat every 10 min, and **always** a last line
`STATUS {json}` (errors included: `"ok": false` with `error` and `fix`). Exit code 0 = done, 1 = failed / stopped /
lost / refused. Read the terminal file with `AwaitShell`/`Read` (it attaches to the same approval — no new card) at a
5–10 minute cadence in the bot's own turns, never in a tight loop. A Claude workflow job takes 1–3 hours. Re-running
the identical `run` command later re-attaches (it never starts a finished job twice). A **different** job.json with the
same id (e.g. after `new --force` on the box) is a new run: the old run's files move to `<PROJ>/jobs/<id>/history/N/`.

**(e) Results back:** when `STATUS` says `"state":"done"`, `CopyToBox` `<PROJ>/jobs/<id>/outbox.tgz` →
`<BOX_PROJ>/jobs/<id>/outbox.tgz` (parts `outbox.tgz.000 …` if the outbox is over 95 MiB: copy each, then
`cat outbox.tgz.* > outbox.tgz`). **1 card.** On the box:

    tar -xzf <BOX_PROJ>/jobs/<id>/outbox.tgz -C <BOX_PROJ>/jobs/<id>/

**(f) Apply — the bot validates, the worker never writes the box's project directly.** Read `outbox/report.md` and
`outbox/_status.json` (the final status incl. `warnings`). Re-run the job's acceptance check on the box against the
collected files (the worker's own pass is only a hint), then copy the files in `outbox/files/` into the project
(`outbox/files/` holds exactly the job's `collect` list — for a chapter job only **its own** chapter files):

| Kind | Acceptance check on the box, then apply |
|---|---|
| storyboard | `slop --project <name> board audit --shots <BOX_PROJ>/jobs/<id>/outbox/files/board/shots.json`, then copy `outbox/files/board/*` into `<BOX_PROJ>/board/` |
| research-lyrics | `slop --json lyrics lint <BOX_PROJ>/jobs/<id>/outbox/lyrics/lyrics.txt` (+ `--ban <word>` per banned word), the fact table, then the owner |
| chapters | copy `outbox/files/engine/ch/*.js` into `<BOX_PROJ>/engine/ch/`, then `node "<BOX_TK>/runner/deleg.mjs" wire "<BOX_PROJ>" --chapters "<BOX_PROJ>/jobs/<id>/job.json"` (merges `_index.js`; never copy an `_index.js` between computers), then per chapter `node "<BOX_TK>/runner/deleg.mjs" wire "<BOX_PROJ>" --check --chapters "<BOX_PROJ>/jobs/<id>/job.json"` (all WIRED) and `slop --project <name> render lyrics --from <t0> --to <t1>` (N/N) and `slop --project <name> render check --skip-flash` |
| review | `outbox/review.json`: the verdict rule (no blocking fix, owner ≥ 7, others ≥ 6, gate N/N); an empty review fails |
| safety-scan | every take of the list is in `outbox/scan/findings.json` `checked`; the owner decides every block and fix |

Log the run in the project's `RUNS.md`: `slop --project <name> runs add <id> --kind deleg --status done --what "<kind> job"`.

Card budget with "Ask every time": **3 per job** (copy in, run, copy out) **+ the sync parts** (1 for a small or delta
sync; 4–16 for a first render sync). With the user away from that computer the cards cannot be answered: either the
user approves them at the desk, or sets **Always allow** for that computer themselves (their decision — never suggest it
silently; it lets the bot run any command as them).

### Gates

`job.json` is written on the bot's computer, and the approval card shows only the command line. So every job.json field
that widens what a job may do is **refused** unless the run command carries the matching flag, which the card then shows:

| job.json field | Flag on `run` / `start` / `resume` | What it allows |
|---|---|---|
| `allow_api_billing: true` | `--allow-api-billing` | keeps API-key variables: the engine may bill an API key instead of the subscription |
| `allow_spend: true` | `--allow-spend` | enables Claude's Higgsfield connector (spends credits) |
| `pass_env: ["NAME"]` | `--pass-env NAME` (comma list or repeat) | hands that secret to the engine |
| `engine: "raw"`/`argv`, `engine_bin`, `env`, `slop_cmd`, `add_dirs`, `codex_config`, `muse_flags`, a `permission_mode` other than default/acceptEdits/plan, `sandbox: "danger-full-access"`, tools beyond the default list, a `cwd` outside the job/project, a `project_dir` that is not a slop project | `--allow-raw` | overrides the runner's safe defaults |

The templates never set any of these. If `new` prints `gates_needed`, ask the user first and say what each flag allows.
No delegated job ever spends money: briefs forbid it whatever the goal says, and spending happens on the bot's side
after the owner confirms.

## 3. Commands

Every command prints ONE JSON line (`{"ok": true, …}` or `{"ok": false, "error": "…", "fix": "…"}`), except `wait` and
`run`, which print progress lines and always end with `STATUS {json}`. Exit code 0 = ok / done / running.

| Command | What it does | From Grok Bot |
|---|---|---|
| `new <jobdir\|auto> --brief <name> [--project P] [--engine claude\|codex\|muse] [--workflow W\|none] [--set K=V …] [--vars f.json] [--args f.json] [--spec f.json] [--force]` | builds a job folder from `templates/briefs/<name>.md` (+ `templates/workflows/<W>.js`); refuses to overwrite a different job without `--force` (which moves the old run to `history/N/`); same inputs = no-op | box, foreground |
| `run <job\|id.job.json> [gates]` | start if needed, follow until the job ends | **user's computer, ONE background shell** |
| `start <job> [gates] [--fresh]` | launch the detached supervisor; returns in < 1 s (`--fresh`: a finished job from scratch, new session) | foreground |
| `status <job>` | the normalised status + `next` (the command to run next) | foreground |
| `wait <job> [secs=25]` | new progress lines, then `STATUS` after ≤ secs (keep ≤ 25 in the foreground) | foreground poll |
| `stop <job> [--force]` | marks `.stop`, kills the engine's process tree (`taskkill /T /F` on Windows, the process group on macOS/Linux) | foreground |
| `resume <job> [prompt-file] [gates]` | a new attempt **in the same session/thread** (stopped, failed or lost jobs); without a prompt file it writes the right continuation (a Claude workflow resumes by run id) | foreground |
| `list [jobs-root\|project]` | every job with state, attempt, last event, error | foreground |
| `wire <project> --chapters <job.json\|args.json\|chapters.json> [--check]` | chapter files: create missing stubs and merge `engine/ch/_index.js` (locked; jobs side by side are safe) / `--check`: WIRED or NOT WIRED per chapter (listed, parses, registers scenes); `--check --file 02_x.js --shots s1,s2` for one file | both machines |
| `pack <job>` / `unpack <archive> <dest> [--force]` | (re)build `outbox.tgz` (+ 95 MiB parts) / extract an archive or its parts (refused while a job of that project runs) | foreground |
| `templates` | the brief templates with their variables, and the workflow scripts with their args | box |
| `doctor [--render]` / `selftest [--keep]` / `preflight <engine> [--workflow] [--job D]` | machine + toolkit check / free end-to-end test with a fake engine / one tiny real prompt (or workflow) | foreground (`--workflow`: background) |

## 4. The job folder

```
<project>/jobs/<YYYYMMDD>-<4hex>-<slug>/
  job.json          engine config (below)                                  written by `new` (bot)
  BRIEF.md          the prompt, filled from a template                     rebuilt from job.json "brief" if missing
  wf/<name>.js      the Claude workflow script, copied from templates/workflows/ — inside the job folder so a resume can
                    read it (a session-store path was refused on resume in the reference production)
  wf/args.json      the workflow args as passed (runtime paths filled in; "wired": true when the runner wired chapters)
  prompt-N.md       the exact prompt of attempt N (a short preface + the brief or the resume prompt)
  outbox/           the collected output; workers write it continuously (a cut at any moment leaves valid files)
    report.md       the worker's report (≤ 1 page; the brief fixes its format)
    files/…         project files listed in job.json "collect", copied at the end (e.g. board/shots.json)
    _status.json    the final status;   _runs/  copies of each workflow's run output
  outbox.tgz        the outbox packed at the end (or outbox.tgz.000, .001 … over 95 MiB)
  status.json       runner-owned, normalised (below)
  progress.log      runner-owned, one line per event, ≤ 240 chars
  raw-N.jsonl       lossless engine stdout of attempt N;  stderr-N.log
  RUNS.md           attempt / session / workflow run ids / args — written by the runner, never by hand
  runs/             <taskId>.output.json (a workflow's summary, logs, result, per-agent states) and wf_<run>.json records
  history/N/        an earlier run of this folder (after `new --force`, or a different job.json with the same id)
  .stop             present after `stop`
```

Briefs decide where deliverables go: some write project files (`board/`, `engine/ch/<own file>`), which `collect` copies
into `outbox/files/`; everything else (reports, results, scratch notes) goes in `outbox/`.

### job.json

| Field | Default | Meaning |
|---|---|---|
| `engine` | — | `claude` \| `codex` \| `muse` \| `raw` (`raw` runs `argv` — for tests and odd jobs; needs `--allow-raw`) |
| `id`, `kind`, `title`, `brief_template`, `vars`, `created`, `project_name` | from `new` | bookkeeping; `kind` tells the bot which acceptance check to run; `project_name` places a job file copied to `<HOME>` |
| `brief` | from `new` | the filled brief; written to `BRIEF.md` when that file is missing |
| `prompt_file` | `BRIEF.md` | |
| `project_dir` | `../..` | relative to the job folder (or absolute); a missing absolute path falls back to `../..` |
| `cwd` | the project folder | the engine's working directory |
| `workflow`, `workflow_args` | from the template | a workflow name or path; args (strings may contain the runtime tokens below) |
| `model`, `effort` | engine default | passed as `--model`/`--effort` (claude), `-m`/`model_reasoning_effort` (codex), `--model`/`--reasoning-effort` (muse) |
| `allowed_tools` / `extra_allowed_tools` / `disallowed_tools` | Workflow, Agent, Task, Read, Write, Edit, MultiEdit, Glob, Grep, Bash, PowerShell, WebSearch, WebFetch, ToolSearch, TodoWrite, NotebookEdit, Skill | Claude permission rules; anything else is denied (`--permission-mode default --permission-prompts none`); tools beyond this list need `--allow-raw` |
| `permission_mode` | `default` | Claude permission mode (other than default/acceptEdits/plan: `--allow-raw`) |
| `allow_spend` | `false` | when false, Claude's `mcp__claude_ai_Higgsfield` connector tools are denied (true needs `--allow-spend`) |
| `add_dirs` | — | extra folders the engine may use (the job, project and toolkit folders are always added) |
| `max_turns`, `max_budget_usd` | — | Claude limits (`max_budget_usd` counts list-price usage even on a plan — leave it unset for workflows) |
| `sandbox`, `network`, `codex_config` | `workspace-write`, `false`, — | Codex sandbox, network access for the sandbox, extra `-c key=value` |
| `approval_mode`, `muse_flags`, `provider` | `never`, `["--no-foreign-personal-context"]`, — | Muse; Gemini's `approval_mode` is `auto_edit` (default) \| `default` \| `plan` \| `yolo` (`yolo` needs `--allow-raw`) |
| `output_schema` | — | a JSON-schema file for the final answer (codex, muse) |
| `timeout_s` | 21600 (6 h) | the job is stopped (state `failed`, error "timeout") after this |
| `allow_api_billing` | `false` | keep API-key env vars (bills the API instead of the subscription; needs `--allow-api-billing`) |
| `pass_env` | — | env names to pass through anyway (each needs `--pass-env NAME`) |
| `env` | — | extra env vars for the engine (needs `--allow-raw`) |
| `collect` | from the template | project-relative files or `dir/*.ext` globs copied into `outbox/files/` at the end (chapter jobs: exactly their own chapter files) |
| `requires` | from the template | `slop`, `render`, `ffmpeg`: the toolkit runtime checked on this computer before the engine starts |
| `wire_chapters` | chapter jobs | create stubs + merge `engine/ch/_index.js` for `workflow_args.chapters` before the engine starts |
| `queue_group` | chapter and review jobs: `"render"` | jobs of one group run one at a time per jobs folder (only one rendering job at a time) |
| `max_parallel` | 3 (2 on the bot's computer) | jobs running at once in the same jobs folder (others wait as `queued`); on the bot's computer also at most 2 agent jobs box-wide (§1b) |
| `stop_above_utilization` | — | e.g. `0.9`: stop when Claude's 5-hour or 7-day usage passes 90 % |
| `workflows_env` | `false` | set `CLAUDE_CODE_WORKFLOWS=1` (Claude Pro) |
| `engine_bin` | auto | the engine executable, or an argv prefix like `["node", "/path/cli.js"]` (needs `--allow-raw`; also `DELEG_CLAUDE_BIN` etc., a path or a JSON list) |
| `slop_cmd` | auto | how workers run the toolkit CLI (`slop`, else the toolkit venv, else `python -m slop` with `PYTHONPATH`; also `SLOP_CMD`) (needs `--allow-raw`) |

Runtime tokens, filled on the machine that runs the job (in `BRIEF.md` and in `workflow_args` strings):
`{{JOB_DIR}} {{JOB_ID}} {{OUTBOX}} {{PROJECT_DIR}} {{TOOLKIT_DIR}} {{SLOP}} {{ENGINE}} {{WORKFLOW_PATH}} {{WORKFLOW_ARGS}}`.
Template variables (`{{TITLE}}`, `{{KEY|default}}`) are filled by `new` with plain string replacement (prompts contain
literal JSON braces); every variable the brief uses also reaches the workflow as a lower-case arg.

### status.json (normalised)

| Field | Meaning |
|---|---|
| `state` | `queued` · `starting` · `running` · `done` · `failed` · `stopped` (`status` reports `lost` when a running job's supervisor is gone — a reboot or a kill) |
| `engine`, `attempt`, `started`, `ended`, `updated`, `first_started` | |
| `last_event` | `{at, what}` — the last thing the engine did (liveness) |
| `tokens` | summed `{input, output, cache_read, cache_write[, reasoning]}` where the engine reports them (Muse does not) |
| `result_text` | the final answer (the LAST result — for Claude, the one after the workflow finished) |
| `error` | why it failed or stopped, with the fix when known |
| `warnings` | read before trusting a `done`: dead workflow agents, permission denials, usage limit hit, no report written … |
| `gates`, `toolkit` | the effective gates of this attempt; the toolkit check result (`slop_ok`, `render_ok`, `ffmpeg_ok`) |
| `session_id` / `thread_id`, `planned_session_id` | what `resume` continues |
| `workflow_runs`, `tasks` | Claude workflow run ids; per task `{name, status, agents, done, err, failed_agents, tokens, result_ok}` |
| `limits` | Claude: `{status, five_hour{utilization,resetsAt}, seven_day{…}}`; Codex: from its rollout file after exit |
| `results`, `final`, `cost_usd` | every Claude `result` event; `cost_usd` is the list-price equivalent, not a bill |
| `argv`, `cwd`, `env_stripped`, `supervisor_pid`, `engine_pid`, `exit_code`, `outbox` | for debugging |

## 5. Engines: exactly what is launched

**Claude Code** (one job = one session):
`claude -p "Read the file <job>/prompt-N.md and do exactly what it says. … Deliverables go where the brief says;
everything else you write goes under <job>/outbox." --output-format stream-json --verbose --permission-mode default
--permission-prompts none --add-dir <job> --add-dir <project> --add-dir <toolkit> --allowedTools Workflow,Agent,…
--disallowedTools mcp__claude_ai_Higgsfield --session-id <uuid>` (resume: `--resume <session_id>`).
- A Workflow runs in the background; print mode **waits for it** and then emits a **second** `system/init`, assistant
  turn and `result`. The runner reads until the **process exits**; the first `result` is never "done".
- Workflow resume is **same-session only**: `resume <job>` re-enters the session and calls
  `Workflow({scriptPath: <job>/wf/<name>.js, resumeFromRunId: <run>, args: <same args>})`; finished agents replay from
  cache. Journals are not durable — the scripts also skip work already on disk, so a fresh run after a lost journal
  still continues.
- A run that says `completed` can hide agents that returned nothing (a usage limit). The runner copies each workflow's
  output to `runs/`, flags `[x] failed:` lines and `error` agents in `warnings`, and the toolkit's scripts return
  `ok: false` when a review, judge or audit is missing.
- Whether workflow **subagents** get Bash/Write under these headless flags is what `preflight claude --workflow` proves.
- On Windows the runner calls `claude.exe` directly; an npm-installed `claude.cmd` is unwrapped to `node cli.js`.

**Codex**: `codex exec --json --skip-git-repo-check -c forced_login_method="chatgpt" -o <job>/last-message.txt -C <cwd>
-s workspace-write --add-dir <job> … -` with the prompt on stdin, **stdin closed** (Codex reads a non-TTY stdin and would
wait). Resume: `codex exec resume … -c sandbox_mode="workspace-write" <thread_id> -` (resume has no `-s`/`-C`). Rate
limits are read from `~/.codex/sessions/…/rollout-*-<thread>.jsonl` after exit. On Windows the npm shim is unwrapped to
`node codex.js` (Node will not spawn `.cmd` files, and PowerShell may block `.ps1`).

**Muse Code**: install it from dev.meta.ai (paid plans) and sign in once in a terminal. The runner calls
`muse exec --json --prompt-file <job>/prompt-N.md` with the job's approval mode and workspace (resume:
`--session-id <session>`); extra flags come from the job's `muse_flags`, and `MUSE_NO_AUTO_UPDATE=1` keeps the CLI from
updating itself mid-job. On Windows the runner calls the installed versioned binary directly rather than the `muse.cmd`
launcher, because cmd quoting changes prompts that contain `" & | % ^ < >`.

**Gemini CLI**: `gemini -p "Read the file <job>/prompt-N.md and do exactly what it says. …" -o stream-json --skip-trust
--approval-mode auto_edit --include-directories <job>,<project>,<toolkit>` with stdin closed (Gemini appends a piped
stdin to the prompt). Stream (verified, 0.62): `init {session_id, model}`, `message {role, content, delta}`,
`tool_use`, `tool_result`, `result {status, error?, stats}`. No session resume: `resume` starts a new Gemini session on
the continuation prompt. [Unverified] Headless Gemini drops every tool that would ask for approval, so under
`auto_edit` it reads and writes files but probably cannot run shell commands (`slop`, `node`, `ffmpeg`): give it
write-only work (`new --engine gemini` warns when the brief's checks need the shell), or list the tool in
`"allowed_tools": ["run_shell_command"]` (passed as `--allowed-tools`; needs `--allow-raw`). Sign-in: a Google account
(`slop agents login gemini`) or `GEMINI_API_KEY`. The runner strips API keys from every job, so a key sign-in reaches a
job only through the pass-env gate: `new --engine gemini` adds `"pass_env": ["GEMINI_API_KEY"]` when Gemini's chosen
sign-in is the key, and the run command then needs `--pass-env GEMINI_API_KEY` (ask the user first: a key can bill the
Google Cloud project behind it).

**Subscriptions, not API bills.** Before launching, the runner removes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK/VERTEX`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `OPENAI_BASE_URL`,
`META_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY` from the engine's environment (unless `--allow-api-billing`),
forces Codex's ChatGPT login, and stops a
Claude job whose init reports an API-key source. It also strips a parent Claude Code session's `CLAUDECODE` /
`CLAUDE_CODE_*` variables, and never passes `OPENROUTER_API_KEY`, `HIGGSFIELD_API_KEY` or `ARENA_TOKEN` unless
`pass_env` names them and the command line carries `--pass-env`. Credentials stay with their engine: the Claude plan
token `CLAUDE_CODE_OAUTH_TOKEN` reaches only Claude jobs (never a Codex, Muse or Gemini agent that could read it with a
shell command), and the one-time sign-in codes `CLAUDE_LOGIN_CODE` / `GEMINI_LOGIN_CODE` reach no job. `status.json`
lists the names it removed (never values).

## 6. Briefs and workflow scripts

`node deleg.mjs templates` lists them with their variables. Briefs (`templates/briefs/`) all follow the same anatomy:
identity + "nobody answers mid-run" · the goal as a measurement and where the authoritative check lives · files (READ
FIRST: the project's `PRODUCTION.md` when it exists, then `DECISIONS.md`) · rules with explicit cheat definitions · an
ordered method with the first deliverable bounded in commands · budgets (never any spending) · a report format with a
length cap · "You do NOT" · the finish condition.

| Brief | Workflow | Collected | The bot's acceptance check after collecting |
|---|---|---|---|
| `research-lyrics` | `research-lyrics.js` (sweeps → verify → bank → 4 writers → 3 judges → merge → critic) | `outbox/research`, `outbox/lyrics` | `slop --json lyrics lint …`, banned words, every fact in the table confirmed/wording-fix; then the owner |
| `storyboard-panel` | `storyboard.js` (3 directors → 3 judges → merge → audit until it passes) | `board/shots.json`, `STORYBOARD.md`, `audit.json` | `slop board audit --shots …`; then the owner approves the sheet |
| `prompt-book` | none — one context on purpose | `outbox/prompts/` | the 8 checks in the brief; then the owner reads the book **before any spend** |
| `chapter-motion` | `chapters.js` (wire → animate → art director on real renders → fix → review 2 → fix; 2 chapters at a time, `--workers 2`) | its own `engine/ch/<file>`s | `wire --check` WIRED, `slop render lyrics` N/N and `render check` on the bot's side; then the owner |
| `review` | none | `outbox/review.json` | the verdict rule: no blocking fix, owner ≥ 7, others ≥ 6, gate N/N; an empty review fails |
| `safety-scan` | `safety-scan.js` (slices of a list file) | `outbox/scan/` | every take in the list is in `checked`; the owner decides every block and fix |
| `generic` | optional | as the brief says | as the brief says |

Rendering is the heavy part (each Chromium ≈ 1.7 GiB): chapter and review jobs share `queue_group: "render"`, so only
one of them renders at a time on the user's computer; inside a chapter job at most 2 chapters are in flight and every
render command uses `--workers 2`. Give a chapter job 3–4 chapters.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `{"ok":false,"error":"Claude Code (claude) was not found …"}` | not installed / not on PATH for the bot's shell | install it (on the bot's computer: `slop agents install claude`); or set `engine_bin` (+ `--allow-raw`) |
| `STATUS {"ok":false,"error":"this job.json asks for more than the safe defaults …"}` | a gated field (see "Gates") | ask the user; add the flag only if they agree, or rebuild the job without it |
| state `failed`, error "the toolkit CLI does not run here" / "the renderer does not run here" | toolkit runtime missing on the user's computer | §1 "Install the toolkit runtime", then `doctor --render`, then `resume` |
| state `failed`, error "no Workflow tool" | Claude Pro default | `"workflows_env": true` in job.json, then `resume` |
| state `failed`, error "would bill an API key" | Claude settings use an API key | remove it, or `"allow_api_billing": true` + `--allow-api-billing` if intended |
| `warnings`: "N agent(s) failed or returned nothing" | usage limit mid-workflow | wait for the reset (`limits`), then `resume` — finished agents replay |
| workflow result `incomplete` / `failed` lists chapters | reviews returned nothing after fixes | `resume` (or carry `open_fixes` into a refit job) |
| a chapter shows NOT WIRED | its file is not in `engine/ch/_index.js` or is still a stub | `wire <project> --chapters <job.json>`, then re-run the chapter |
| `warnings`: "permission denial(s) (X)" | the job needed tool X | add it to `extra_allowed_tools` (+ `--allow-raw`), `resume` |
| state `lost` | the computer rebooted or the supervisor was killed | `resume <job>` |
| state `queued` for long | `max_parallel` jobs, or another `"render"` job, already running in that jobs folder; on the bot's computer: 2 agent jobs already running box-wide (progress.log says which) | wait, or raise `max_parallel` (box-wide: `DELEG_BOX_SLOTS`) |
| state `failed`, error mentions 401 / "authenticate" / "invalid … token" | the engine's sign-in expired or was revoked | `slop agents test ENGINE` prints the fix: `slop agents login ENGINE --force`, or (a `CLAUDE_CODE_OAUTH_TOKEN` user) a new `claude setup-token` value from the user |
| `unpack` refused: "job(s) … are running" | a sync would overwrite files the job edits | wait until `list <PROJ>` shows `running: 0`, then unpack |
| `job.json is not valid JSON` | backslashes in Windows paths | use forward slashes |
| `outbox.tgz` missing, warning "could not pack" | no `tar` (very old Windows) | copy the files in `outbox/` one by one |
| a Grok Bot card says "not approved on the user's computer" | "Ask every time" and nobody at that computer | approve at the desk; nothing ran |

Known limits: the concurrency cap is per jobs folder and soft (two jobs starting in the same second can both pass;
`queue_group` uses a lock file and is strict); Claude's `cost_usd` is a list-price equivalent, not a bill (watch
`limits`); a Claude workflow can only be stopped as a whole; a `run` follower dies with the Grok Bot daemon but the job
does not — run the same `run` command again to re-attach. macOS paths are implemented but untested on a Mac.
