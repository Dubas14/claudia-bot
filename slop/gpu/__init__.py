"""Home GPU for Claudia: `slop gpu` on the box + a small worker on the user's own computer (KITOUT section 3).

Two ways to reach the user's GPU (read slop/gpu/README.md for the operator guide):
  - paired  `slop gpu serve` runs a job server on the box (localhost, behind a Cloudflare quick tunnel and a random
            pairing code); `slop gpu pair` prints ONE line to paste on the PC, which installs the worker (uv +
            Python under the user's home folder) from the box's own URL. The worker polls for jobs, downloads the
            inputs, runs ONLY this toolkit's own profile entrypoints, uploads the outputs and heartbeats.
  - direct  no networking: `slop gpu direct-plan JOB` prints the exact command lines the bot runs on the PC through
            Grok Bot local exec, and the file moves (CopyFromBox / CopyToBox, parts of at most 95 MiB).

Module map. BOX side (imports slop.config): store (the durable disk queue, pairing, worker state), server (the HTTP
job server), service (serve/stop/status, the tunnel), route (the --gpu auto|off|require routing used by analyze stems/
align and edit export depth), direct (direct mode), cli (`slop gpu ...`).
WORKER side (stdlib only, never imports slop.config; shipped to the PC as worker.zip): proto (ids, manifests, entry
table, size caps), profiles (pinned installs), gpus (detection and the busy check), worker (`slopgpu ...`), entry and
entries/ (the code that runs inside a profile's venv on the GPU).
"""
PROTO = 1
