# 96 · The relay: Grok passes the words, the production works

Grok is a thin relay. Claude Code with Opus (or Codex, for people without a Claude plan) is the production: it does
all the creative and technical work with this toolkit. Grok passes the person's words verbatim, shows what the
production posts, and runs the jobs the production asks for. `slop relay` is the wire between them.

There is one relay per computer. Grok never names a project: the production works in the projects folder
(`$SLOP_PROJECTS`, on the box /workspace/slop/projects) and picks or creates the project itself.

## 1. Setup (once)

    slop --json relay setup [--engine claude|codex] [--model M]

- Checks that the engine is installed and signed in (`slop agents status`). If not, it prints the exact step
  (`slop agents install claude`, `slop agents login claude`) and stops.
- Registers the claudia.gallery MCP for the engine. Claude Code:
  `claude mcp add --transport http --scope user claudia https://claudia.gallery/mcp` (skipped when it is already
  there). Codex: `[mcp_servers.claudia]` with `url = "https://claudia.gallery/mcp"` in ~/.codex/config.toml.
- Claude Code only: downloads the official Claudia skill (https://claudia.gallery/skill/claudia-skill.zip) into
  ~/.claude/skills/. Offline, it skips this and says so; the MCP has the same knowledge.
- Writes the production brief (templates/production-brief.md) into the projects folder as CLAUDE.md and AGENTS.md.
  A file there that the relay did not write is kept; `--force` replaces it.
- The model is opus by default for Claude Code, Codex's own default for Codex.

## 2. The loop

    Grok                                   relay ($SLOP_HOME/relay)                 production (in the projects folder)
    relay send '<words>'          ->       inbox.jsonl; starts a turn if idle  ->  claude -p ... --resume SESSION
    relay read --wait 200         <-       outbox.jsonl, jobs, state           <-  relay say / ask / job
    relay done J-0003 --file F    ->       "[grok] J-0003 done: files ..."     ->  the next turn uses the files

1. `slop --json relay send '<words>'`: the words go to the inbox verbatim. A director's words are also appended,
   dated, to `decisions.md` (never edited). If no turn is running, the relay starts one as a background `slop job`
   and returns in a second or two. If a turn is running, the message waits: the next turn picks it up when the
   current one ends.
2. A turn: `claude -p <prompt> --output-format stream-json --verbose --permission-mode bypassPermissions
   --model opus --resume <session>`, run in the projects folder. Codex: `codex exec --json ... -` (the prompt on
   stdin), then `codex exec resume <thread> ...`. The prompt holds every pending message, verbatim, oldest first.
   The session id is kept, so every turn continues the same conversation.
3. The production talks back only through the relay:
   - `slop relay say TEXT --show FILE ...` and `slop relay ask QUESTION --default X --show FILE ...` (files are
     checked and stored as absolute paths);
   - `slop relay job --kind grok-imagine --what still|clip --prompt TEXT ...`: browser work for Grok on grok.com
     (the person's X plan, $0; stills and motion clips, never sung lip-sync windows);
   - `slop relay job --kind person --text BLOCK --expect FILE`: a step only the person can do (Suno, Midjourney,
     a sign-in);
   - `slop relay inbox`: messages that arrived during the turn.
4. `slop --json relay read --wait 200`: new say/ask items verbatim with their files (marked read), every open job
   with all its fields, the production's state, and one `grok_next` line, for example "Post these 2 messages
   verbatim with their files, then run job J-0003 with skill grok-imagine (...), then `slop --json relay read
   --wait 200`." The wait is capped at 240 s and returns early on anything new; it returns at once when nothing
   is working or a job is open.
5. Grok saves a job's downloads into the job's `save` folder, then `slop --json relay done J-0003 --file PATH`
   (or `relay fail J-0003 --reason TEXT [--declined]`). That is a message to the production, and it starts a turn
   when the production is idle.

The production's states: working (since when, the last tool line), waiting (its last post was a question),
idle, queued (messages wait but nothing runs), failed (with the error and the log tail), stopped.

## 3. The files ($SLOP_HOME/relay/)

| File | What |
|---|---|
| config.json | engine, model, what setup did |
| inbox.jsonl | every message to the production: `{id, ts, from, text}` |
| decisions.md | every director message, dated, append-only |
| outbox.jsonl | every say, ask and job: `{id, kind, text, default, files, turn}`; job J-0003 is outbox item 3 |
| jobs.json | the result of each finished job (done, failed or declined); a job not in it is open |
| state.json | the cursors (delivered to the production, shown by Grok), the turn count, the session per engine |
| runner.json | the supervisor: starting, running, idle, failed or stopped, with its pid and job id |
| turn.json | the running turn: number, start, pid, the last progress line |
| relay.log | one line per event; `turns/turn-NNNN.jsonl` and `.err` keep each turn's raw stream and stderr |
| bin/slop | the toolkit's `slop` for the production, first on its PATH |

Every file is LF. Logs are appended; everything else is replaced by an atomic rename. Every change holds a short
lock (the folder `lock/` with its owner's pid; a lock whose owner is gone is broken), so `send`, `read` and the
production's `say` can run at the same time. Order comes from a sequence number in every inbox and outbox line, and
ages from the monotonic clock, never the wall clock: it can step (a WSL clock was seen jumping 68 s back and forth).

## 4. Failure modes

- **The engine is not signed in, or the sign-in expired.** `setup` stops with the step. A turn that fails with a
  401 makes `read` say so: `slop agents status` shows the fix.
- **A turn fails** (usage limit, a crash, an error result). Its messages go back to the inbox, the state is
  "failed", and `read` gives the reason and the log tail. After the fix, `slop --json relay send 'continue' --from
  grok` runs them again; the prompt says the last turn failed and may have done part of the work.
- **The saved session is gone** (a wiped ~/.claude). The turn is retried once in a new session.
- **The production posts nothing.** Its last words are posted for it, marked as its own words, so the person
  still hears something.
- **The supervisor dies** (killed, out of memory, a restart). `read` reports "failed"; the next `send` starts a new
  supervisor and the waiting messages run.
- **A turn hangs.** `slop --json relay stop` stops it (the whole process group); waiting messages stay. A turn is
  also stopped after 4 hours (`SLOP_RELAY_TURN_MAX_S`).
- **Running as root.** Claude Code refuses `--permission-mode bypassPermissions` for root; run the bot as a normal
  user.
- **Grok's turn ends** about 5 minutes into long tool calls, so `read --wait` is capped at 240 s and the skill
  posts a status line and "Say continue" before any long wait.

## 5. Commands

| Who | Command |
|---|---|
| Grok | `slop --json relay setup`, `send '<words>' [--from grok]`, `read --wait 200`, `done JOB --file PATH`, `fail JOB --reason '<words>' [--declined]`, `status`, `stop`, `log` |
| Production | `slop relay say`, `ask`, `job`, `inbox` |

The skill for Grok's side is skills/claudia-relay/SKILL.md.
