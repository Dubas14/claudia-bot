# Home GPU (`slop gpu`): operator guide

The box (the Grok Bot computer) has no GPU. If the user has an NVIDIA GPU (Windows or Linux) or an Apple Silicon Mac,
Claudia can send its heavy steps there: song stems and lyric alignment (`slop analyze`), plate depth maps
(`slop edit export`), and by hand Whisper word times, mattes, masks and frame interpolation. Nothing else changes:
every result lands in the project exactly as the CPU path would write it. When no GPU is ready, everything still runs
on the box's CPU.

## Pick a mode

| | **paired** (recommended) | **direct** |
|---|---|---|
| How | the box runs a job server behind a Cloudflare quick tunnel; the PC runs a small worker that polls it | the bot runs the worker on the PC itself through Grok Bot local exec and moves files with CopyFromBox / CopyToBox |
| User does | pastes ONE line into a terminal on the PC, once | approves each local command (or sets the computer to "Always allow") |
| Works when | the PC is on and the worker runs; the user can be away | the user's desktop app is open (local exec) |
| Network | outbound HTTPS from both sides (tunnel) | none between box and PC |

## Paired mode, step by step (bot side)

1. `slop gpu serve` - starts the job server and its quick tunnel in the background. Prints the public URL only once
   cloudflared has registered a connection with Cloudflare's edge (or the URL answers): Cloudflare hands out a
   trycloudflare.com address before that, and when the network blocks the edge's outbound port 7844 (UDP and TCP)
   that address answers error 1033 / HTTP 530 forever. Then `serve` fails with that reason; restarting does not
   help: use direct mode (below). `slop gpu pair` also refuses until the public URL answers. cloudflared runs with
   `--protocol http2` (`SLOP_TUNNEL_PROTOCOL=quic` or `auto` to change); both need port 7844.
2. `slop gpu pair` - prints two lines. Give the user the one for their system:
   - Windows PowerShell: `$env:SLOPGPU_URL='https://…'; $env:SLOPGPU_TOKEN='…'; irm "$env:SLOPGPU_URL/gpu/install.ps1" -Headers @{…} | iex`
   - macOS / Linux: `curl -fsSL -H 'Authorization: Bearer …' 'https://…/gpu/install.sh' | SLOPGPU_URL='…' SLOPGPU_TOKEN='…' bash`

   The line holds a one-time pairing code. It is shown once and stored on the box only as a hash. Share it only
   with the user. The worker trades it for its own secret within seconds, so the copy left in the PC's shell history
   stops working; an unused line expires after 24 h. Add `--gpu INDEX|UUID` to pin one GPU (see "GPU choice" below).
   - While a worker is paired, `slop gpu pair` refuses (a new code would cut that worker off). `slop gpu pair --new`
     replaces the pairing on purpose: another PC, or updating the worker code (the user pastes the new line).
   - The line installs the worker code that THIS box serves. Pasting a line again later runs whatever the box serves
     at that moment, so the user should only paste lines from their own box.
3. The user pastes the line on the PC. The first time it takes about a minute (a re-paste later, which keeps
   uv and Python, about 10 s). It installs everything under `~/.claudia-gpu` (Windows:
   `%USERPROFILE%\.claudia-gpu`): a pinned, checksum-verified uv, a private Python 3.12 and the worker. It needs no
   admin rights and leaves PATH alone. Then it pairs and starts the worker in the background.
4. `slop gpu status` - must say `healthy` and list the PC's GPUs.
5. `slop gpu install audio matte` - installs the GPU profiles on the PC. They are queued jobs: repeat `slop gpu status`
   until they show `ready`. First install measured on a fast line: audio 121 s, matte 34 s (the two share torch's
   wheels). They download about 4.5 GB.
6. Done. `slop analyze` and `slop edit export` now use the GPU by themselves (`--gpu auto` is their default).

**The tunnel URL changes when `slop gpu serve` restarts** (box restart, wipe, or `--stop`). The worker then cannot
reach the box. Run `slop gpu pair --refresh` and give the user its short line (`slopgpu url https://…`, no code
needed).

## Direct mode, step by step

1. `slop gpu direct-plan` (add `--os mac_linux` on a Mac or Linux PC) - copies the installer and the worker code into
   the box's kit folder and prints the steps: two CopyFromBox moves, one installer command, one profile install.
   It switches the box to direct mode only when no mode is set yet. A paired box stays paired unless you add
   `--use-direct` (or run `slop gpu mode direct`); `slop gpu mode paired` switches back.
2. Run a step with `--gpu require`, for example `slop analyze --steps stems,align --gpu require`. Run it as a
   background `slop job`. It queues a GPU job and waits for it, printing `run slop gpu direct-plan JOB`.
3. `slop gpu direct-plan JOB` - packs the job (parts of at most 95 MiB; CopyToBox and CopyFromBox carry at most
   100 MiB a file) and prints every step: CopyFromBox the parts, `slopgpu run-bundle JOB --detach`, then
   `slopgpu bundle-status JOB` (one short call per turn) until it says finished. Then CopyToBox the output parts it
   lists, then `slop gpu direct-ingest JOB`. The waiting step continues on its own.

## Routing: `--gpu auto | off | require`

`slop analyze` and `slop edit export` take `--gpu`. Without the flag the mode comes from `$SLOP_GPU`, else `auto`.

- **auto**: the GPU when `slop gpu status` is healthy for that profile, else the CPU with a `note:` line saying why.
  - A GPU job that fails, or meets a busy GPU, falls back to the CPU too. So does a step that finds another GPU job
    ahead of it in the queue (for example a profile install that takes minutes).
  - Stems stay on the CPU when sending them back over the PC's measured upload speed (shown in `slop gpu status`)
    would take longer than the box's CPU. 5 minutes of song is about 184 MB of stems.
  - A missing profile gets an install job queued, so the next run uses the GPU. After a failed install, auto mode
    does not queue another one for 6 hours; the note shows the error.
  - Depth maps for fewer than 8 plates stay on the CPU, which is as fast as a cold GPU (measured below). A box
    without torch/transformers (minimal `bin/setup.sh`) sends even one plate to the GPU, since it cannot run depth.
- **require**: the GPU or an error that names the next step. In direct mode the step waits for the bot.
- **off**: the CPU.

A step that is stopped while it waits (Ctrl-C, or `slop job stop`) cancels its GPU job.

Library calls and the test suite never touch a GPU unless `SLOP_GPU` or `--gpu` asks for it.

## What the GPU computes, and parity with the CPU

| step | on the GPU | stays on the box |
|---|---|---|
| stems | Demucs htdemucs, same seed, same normalisation and same apply_model settings | FLAC to float WAV, gain undone, stems.json |
| align | wav2vec2 CTC emissions, same 20 s chunks and 0.1 s context, fp32 (TF32 off) | 16 kHz resampling, Viterbi, merge, report |
| depth | Depth-Anything-V2-Small raw depth for every picked plate, in ONE job | min-max normalisation, resize, filters, subject_depth |

Measured on a 60 s excerpt and 5 plates against the CPU path:
- word start times are identical (92 of 92 words; 447 of 447 on the full song);
- stems differ only at floating-point level (41-62 dB SNR, inaudible);
- depth PNGs differ by at most 1/255, with identical subject_depth.

## Measured (RTX 3090 Ti pinned, Windows 11 worker; box = WSL Ubuntu, 32 threads; tunnel round trip)

Box and worker were on the SAME PC here, so both legs of the tunnel used one fast home line (about 28 MB/s up). On
a real setup the stems travel up the user's home uplink: 34 MB per minute of song, 184 MB for a 5-minute song. At
10-20 Mbit/s that alone is 74-147 s for the full song, which removes much of the gain; auto mode measures the uplink
and keeps stems on the CPU when the GPU route would be slower.

| task | CPU (32 thr / 8 thr) | GPU end to end, cold worker | GPU end to end, warm | GPU compute only |
|---|---|---|---|---|
| analyze stems, 60 s | 17.4 / 18.0 s | 12.1 s (2 runs) | 6.1-6.6 s | 1.1 s separation |
| analyze align, 60 s | 11.2 / 9.9 s | 7.6-11.6 s | 3.5-3.6 s | 0.22 s emissions |
| both (wall) | 27.5-33.5 / 32.5 s | 23.1-27.0 s (localhost: 15.1 s) | 13.0 s (localhost: 11.3-11.6 s) | |
| depth, 5 plates (`edit export`, depth part) | 6.3 / 7.8 s | 10.5 s | 3.0 s | 0.03-0.05 s a plate |
| Whisper large-v3 words, 60 s | (OpenRouter, paid) | 63 s first use (3 GB download) | 7.3 s | 2.9 s |
| FILM x2, 12 frames 720p -> 23 | - | 10.0 s (7.8 s job) | | |
| **full song 5:06**, stems + align | 126 s (8 thr: stems 77.9 + align 37.9) | 41 s (29.7 + 11.4) | | 5.8 s separation |

Cold runs vary: in the slower cold run (27.0 s wall) the align step took 11.6 s, longer than on 8 CPU threads
(9.9 s). A later re-check with box and worker talking over localhost (no tunnel) gave 15.1 s cold and 11.3-11.6 s
warm, against 27.5 s on 32 CPU threads, with the same 92/92 word starts.

The worker keeps a warm process per profile: torch, CUDA and the models stay loaded between jobs. The models are
parked in CPU memory and the CUDA cache is emptied after every job. An idle warm process holds only its CUDA context
(about 250-430 MiB) and is stopped after 60 s without work. A cold start costs about 5-7 s on Windows: torch, plus
transformers pulling in torchvision.

VRAM peaks (torch reserved):
- stems 0.8 GiB;
- align 1.6 GiB;
- depth 0.4 GiB;
- BiRefNet_HR at 1024 px, fp16: 2.3 GiB;
- SAM 2.1-small: 0.8 GiB;
- Whisper large-v3, fp16: about 4.3 GiB;
- FILM at 720p: 5.8 GiB.

## Profiles (`slop gpu profiles`)

| profile | entries | VRAM | download | licences | tested on real hardware |
|---|---|---|---|---|---|
| audio | audio.stems, audio.align, audio.whisper | >= 4 GB | ~4.5 GB | htdemucs code MIT, weights FLAGGED (no licence tag); wav2vec2 Apache-2.0; faster-whisper large-v3 MIT | yes (all three) |
| matte | matte.depth, matte.birefnet, matte.sam2 | >= 6 GB | ~4 GB | Depth-Anything-V2-**Small only** Apache-2.0; BiRefNet_HR MIT (model code from its HF repo at one pinned revision); SAM 2.1 Apache-2.0 | yes (all three) |
| interp | interp.film | >= 6 GB | ~3 GB | FILM Apache-2.0 (TorchScript port, Apache-2.0, sha256-pinned); RIFE not used: its weights only ship through a file-sharing link | yes |
| lipsync | lipsync.latentsync | >= 18 GB | ~12 GB | LatentSync code Apache-2.0, 1.6 weights OpenRAIL++-M: **opt-in only**, `slop gpu install lipsync --accept-licence` after the user agrees; the default rule stays "cut away, no lip-sync fallbacks" | **no**. Needs a C++ compiler on the PC (insightface 0.7.3 builds from source: Visual Studio Build Tools on Windows, g++ on Linux; the install checks first). torch 2.11 with LatentSync's transformers/diffusers pins is an untested combination |
| video-local | - | >= 24 GB | - | per model | documented only (open-weight video models such as Wan 2.x via diffusers) |

Every profile is its own uv venv:
- Python 3.12 (lipsync: 3.10); torch 2.11.0 from the cu128 index on NVIDIA, or from PyPI on Apple (MPS: audio and
  matte only);
- installed with `--compile-bytecode`;
- smoke-tested on the GPU, then swapped in atomically.

Changing a pin in `profiles.py` makes the worker report the profile `stale`. `slop gpu install` then rebuilds it from
the cache (about 40 s).

## GPU choice and the busy rule

- **Busy:** a GPU is busy when more than 1 GiB of its memory is in use, or it is more than 10 % utilised, before our
  job starts (median of three samples). Someone else is using it (a game, a render, another queue, a display), so we
  do not disturb it. Our own idle warm process does not count.
- **Choice:** the worker picks the usable GPU with the most free memory, non-display GPUs first.
- **Pinning:** `slop gpu pair --gpu UUID|INDEX` (or `slopgpu pin …` on the PC) uses only that GPU.
- **All busy:** when every GPU is busy, the job waits in the queue. In `--gpu auto` the box uses its CPU instead.
  `slop gpu submit … --force-gpu` overrides the rule; only use it when the user says so.
- **Display GPUs:** a single display GPU with a busy desktop (browser, video) may count as busy. Tell the user to
  close GPU-heavy apps.

## Safety

- **Runs only the toolkit's own code.** The worker runs only `slop.gpu.entries` functions listed in `proto.ENTRIES`.
  The box cannot send a command, a package or a model name. Parameters are schema-checked, and every manifest is
  validated twice (by the worker and inside the job).
- **Sandboxed files.**
  - Files are plain names inside the job folder (no paths, links or `..`) and are checksummed.
  - Size caps: 2 GiB a file, 6 GiB a job.
  - Transfers go in 32 MiB pieces, under Cloudflare's 100 MB request cap.
- **Killing a job.** Each job runs in its own process tree: a kill-on-close Job Object on Windows, a process group
  elsewhere. Cancel, timeout or `slopgpu stop` kills the whole tree.
- **No pop-up windows.** On Windows the worker runs in a hidden console, so no helper process opens a window.
- **Secrets.** The pairing code and the worker's own secret are the only secrets; the box keeps their sha256 only.
  The pasted code works once (the worker trades it for its secret) and expires unused after 24 h. `slop gpu unpair`
  revokes the pairing (the worker stops by itself), cancels open GPU jobs and stops the server and its public
  tunnel. No API key or account secret is ever sent to the PC.
- **Wrong codes.** A valid code is never throttled. An address that sends 30 bad codes in a minute gets HTTP 429 for
  a minute; the worker backs off and retries.
- **Trust.** The installers and worker.zip are built from the box's own checkout. The worker never updates itself;
  re-pasting a pairing line installs whatever the box serves then.
- **Uninstall** on the PC: `slopgpu unpair`, then delete the `.claudia-gpu` folder in the home folder.

## Commands

Box:
- `slop gpu status [--verify]`
- `serve [--no-tunnel] [--stop]` (the tunnel is the default; `--tunnel` is accepted)
- `pair [--gpu X] [--refresh | --new]`
- `unpair [--keep-server]`
- `mode [paired|direct]`
- `install PROFILE… [--accept-licence]`
- `profiles`
- `jobs`, `show JOB`, `wait JOB`, `cancel JOB`, `fetch JOB --to DIR` (JOB: the full id or its first 6+ digits, as
  the progress lines show them)
- `submit ENTRY --input NAME=FILE … [--param K=V …]`
- `direct-plan [JOB] [--use-direct]`, `direct-ingest JOB`

PC (`~/.claudia-gpu/slopgpu`, Windows `slopgpu.cmd`):
- `status`, `gpus`, `start`, `stop`, `logs`
- `pin UUID|INDEX|auto`
- `url URL`
- `install PROFILE [--detach]`
- `run-bundle JOB [--detach]`, `bundle-status JOB`
- `unpair`

## Troubleshooting

| symptom (`slop gpu status`) | cause | fix |
|---|---|---|
| `the GPU job server is not running` | box restarted | `slop gpu serve`, then `slop gpu pair --refresh` and the short line on the PC |
| `has not checked in for N s` | PC asleep or off, worker stopped, tunnel URL changed | PC: `slopgpu start`; or `slop gpu pair --refresh` |
| `worker code is OUT OF DATE` | the toolkit was updated | `slop gpu pair --new`; the user pastes the new line (about 10 s; profiles are kept) |
| `pair` says `already paired` | a worker is paired | nothing to do; tunnel URL changed: `slop gpu pair --refresh`; replace the PC: `slop gpu pair --new` |
| `direct mode is on, but the paired worker is online` | `direct-plan --use-direct` or `mode direct` ran | `slop gpu mode paired` |
| PC log: `rate limited by the box (HTTP 429 ...)` | someone sent many wrong codes to the box's URL | nothing: the worker retries; if it persists: `slop gpu serve --stop`, `slop gpu serve` (new URL), `slop gpu pair --refresh` |
| PC: `the box refused this pairing code` | the line expired (24 h), was used already, or was replaced | `slop gpu pair --new`, paste the new line |
| lipsync install: `no C++ compiler` | insightface builds from source | install the named build tools, then `slop gpu install lipsync --accept-licence` again |
| `profile … stale` | pins changed | `slop gpu install PROFILE` |
| `BUSY: … in use by other programs` | another program uses the GPU | wait, or close it; auto mode uses the CPU meanwhile |
| install fails `the cuda device does not work` | NVIDIA driver too old for CUDA 12.8 | update the driver (570 or newer) and install again |
| the line fails `no NVIDIA GPU found` | no NVIDIA GPU / no driver | nothing to do: the box's CPU does the work |
| quick tunnel does not start | box blocks Cloudflare (outbound port 7844) | use direct mode |
