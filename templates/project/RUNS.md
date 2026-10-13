# {{TITLE}} - runs

Every long-running job (Claude Code workflow, delegated agent job, render, batch generation) gets a row here the
moment it starts, so an interrupted run can be resumed instead of restarted. Interrupts kill workflows; the run id
and its args file are the only way back in.

    slop runs add wf_1234abcd --kind workflow --what "storyboard: 3 directors -> judges -> merge" --resume "args: board/storyboard-args.json"
    slop runs add render-v1 --kind render --status done --what "frames 0:END -> out/review.mp4"
    slop runs list

Background jobs started with `slop job start -- <command>` keep their own records in `jobs/` (`slop job list`,
`slop job wait ID`); they need no row here.

Resume a killed Claude Code workflow with the same args and its run id (see docs/95-delegation).
Put `--project {{NAME}}` (or `SLOP_PROJECT={{NAME}}`) on every command line - never rely on an `export` inside a
backgrounded chain.

| when | id | kind | what | status | resume |
|---|---|---|---|---|---|
