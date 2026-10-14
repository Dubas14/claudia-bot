---
name: setup-gpu
description: Use when the person wants to wire up a home computer with an NVIDIA GPU or an Apple Silicon Mac (paired worker or direct), to install or check GPU profiles, or when the GPU worker is offline, the tunnel address changed, the pairing must be replaced or revoked, or a GPU step fell back to the CPU.
---

# Home GPU - paired or direct

The box has no GPU. A home GPU runs stems, lyric alignment and plate depth (by hand also Whisper, mattes, frame interpolation); without one everything still runs on the box's CPU. It saves minutes, not money (about 1-2 min per song analysis, less on a slow home upload); "later" is a fine answer. Read /workspace/claudia/slop/gpu/README.md first (modes, profiles, troubleshooting).

## Pick a mode (one question)
- Paired (recommended): the box runs a job server behind a quick tunnel; the person pastes ONE line on the GPU computer once; it works whenever that computer is on, also while they are away.
- Direct: no network link; you run each GPU step on their computer through Grok Bot local exec (an approval card per command, the desktop app open).
- None: `slop --json onboard mark gpu --skip`.
Works with NVIDIA (driver 570 or newer) on Windows or Linux, or an Apple Silicon Mac (audio and matte only). AMD: not supported yet.

## Paired
1. `slop --json gpu serve` (server and tunnel in the background). It fails when the tunnel never connects (the computer's network blocks port 7844): never retry it and never hand out a line; go to Direct below.
2. `slop --json gpu pair`. Send only the line for their system (Windows PowerShell, or a Mac or Linux terminal) in its own code block: "Paste this once in a terminal on your GPU computer (about a minute, no admin rights; it installs into .claudia-gpu in your home folder)." The line holds a one-time code: it works once, expires after 24 h, and is never posted anywhere else.
3. When they say it ran: `slop --json gpu status` (healthy, the GPUs listed); not yet: ask them to say "continue" once it ran.
4. `slop --json gpu install audio matte` (queued on their computer, about 4.5 GB), then the time (a few minutes) and the profile's turn rule line; on "continue" `slop --json gpu status`: both ready. `slop --json gpu profiles` lists the rest: interp; lipsync only after the person accepts its OpenRAIL++ licence (`slop --json gpu install lipsync --accept-licence`; untested on real hardware; the default stays: cut away).
5. `slop --json onboard next` now shows the GPU done. analyze and edit export use it by themselves (`--gpu auto`; `--gpu off`: the CPU; `--gpu require`: fail instead of falling back).

## Direct
1. `slop --json gpu direct-plan` (a Mac or Linux computer: `slop --json gpu direct-plan --os mac_linux`). Do its steps in order: two CopyFromBox moves, one installer command, one profile install.
2. A GPU step as a background job: `slop --json -p NAME job start -- analyze --steps stems,align --gpu require`. It names a GPU job: `slop --json gpu direct-plan JOB`, then its steps (copy the parts over, `slopgpu run-bundle JOB --detach`, `slopgpu bundle-status JOB` once per turn, each turn ending on the turn rule's "continue" line, copy the output parts back), then `slop --json gpu direct-ingest JOB`.
3. Switch: `slop --json gpu mode paired` (or `direct`).

## Everyday and troubleshooting
`slopgpu` below = the worker command on their computer, by its full path: HOME/.claudia-gpu/slopgpu (Windows: HOME/.claudia-gpu/slopgpu.cmd; HOME = their home folder); it is not on PATH.
- Health: `slop --json gpu status` (`--verify` also tries the public address).
- Jobs: `slop --json gpu jobs`, `slop --json gpu show JOB`, `slop --json gpu cancel JOB` (JOB: the id or its first 8 digits).
- The box restarted, or "has not checked in": `slop --json gpu serve`, then `slop --json gpu pair --refresh`; send its short line. Computer asleep or off: they wake it, or run `slopgpu start` there.
- Another computer, or "worker code is OUT OF DATE": `slop --json gpu pair --new` (cuts the old worker off) and send the new line. Plain `pair` refuses while a worker is paired.
- "the box refused this pairing code" (used, replaced or older than 24 h): `slop --json gpu pair --new`.
- BUSY (another program uses the GPU): auto mode uses the CPU meanwhile, or the person closes that program.
- "the cuda device does not work": the NVIDIA driver is too old; update it, then install again. The tunnel never starts: direct mode.
- The rest: the Troubleshooting table in /workspace/claudia/slop/gpu/README.md.

## Safety (tell the person once)
- The worker runs only the toolkit's own GPU steps. The box cannot send it commands, packages or model names; its files stay in its own folder, size-capped. No key or account secret ever goes to that computer.
- The line installs the worker code this bot's computer serves: paste only lines from your own bot.
- Stop any time: `slop --json gpu unpair` (revokes the pairing, cancels jobs, stops the server and tunnel). On their computer: `slopgpu stop`; uninstall: `slopgpu unpair`, then delete the .claudia-gpu folder.
- The worker runs hidden. A window popping up on their computer is a bug: `slopgpu stop` there, and report it.
