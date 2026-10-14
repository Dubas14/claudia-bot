"""`slop gpu ...`: wire up the user's home GPU (router contract: register(subparsers); func(args) -> dict with "text").

  slop gpu status [--verify]                    is a GPU paired and healthy? GPUs, profiles, queue, next step
  slop gpu serve [--no-tunnel] [--port N] [--stop]   the box's job server + Cloudflare quick tunnel (background)
  slop gpu pair [--gpu UUID|INDEX] [--refresh | --new]   the ONE line to paste on the PC (PowerShell / bash)
  slop gpu unpair [--keep-server]               revoke the pairing, cancel open jobs, stop the server + tunnel
  slop gpu mode [paired|direct]                 show or switch the mode (paired: the worker polls; direct: local exec)
  slop gpu install PROFILE... [--accept-licence]   install GPU profiles on the PC (audio, matte, interp, lipsync)
  slop gpu profiles                             what each profile does, its licences and VRAM
  slop gpu jobs [--all] | show JOB | wait JOB | cancel JOB | fetch JOB --to DIR   (JOB: the id or its first 6+ digits)
  slop gpu submit ENTRY --input NAME=FILE ... [--param K=V ...] [--force-gpu]   run one entry by hand
  slop gpu direct-plan [JOB] [--os windows|mac_linux] [--use-direct]   direct mode: exact local-exec steps for the PC
  slop gpu direct-ingest JOB [--from DIR]       direct mode: finish a job from the copied-back parts
It also adds `--gpu auto|off|require` to `slop analyze` and `slop edit export` (default auto): stems, alignment and
plate depth then run on the paired GPU when `slop gpu status` is healthy, else on the CPU with a note.
TRUST: the pairing line installs the worker code THIS box serves (built from its checkout). Pasting a line again
later (to update the worker) runs whatever the box serves at that moment - only paste lines from your own box.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from ..config import SlopError


def leaf(sub, name: str, help_: str) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help_, description=help_, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable JSON on stdout")
    p.add_argument("--project", "-p", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return p


def _wait_max(v: float | None) -> float:
    if v is not None:
        return max(0.0, float(v))
    try:
        return max(0.0, float(os.environ.get("SLOP_WAIT_MAX", 25)))
    except ValueError:
        return 25.0


def _mib(x) -> str:
    return f"{x / 1024:.1f} GB" if isinstance(x, (int, float)) else "?"


# ------------------------------------------------------------------------------------------------ status
def cmd_status(a) -> dict:
    from . import proto, route, service, store
    m = store.mode()
    if (store.gpath() / "jobs").is_dir():
        with store.locked():
            store.expire_leases()
    w = store.worker()
    sv = service.status()
    h = route.health()
    jobs = store.all_jobs()
    counts = {s: sum(1 for j in jobs if j["state"] == s) for s in ("queued", "assigned", "running", "succeeded",
                                                                     "failed", "cancelled", "interrupted")}
    waiting_direct = [j["id"] for j in jobs if j.get("mode") == "direct" and j["state"] == "queued"]
    lines = []
    if m == "none":
        lines.append("GPU: none set up. Two ways to add the user's own NVIDIA (or Apple Silicon) GPU:")
        lines.append("  paired (recommended): `slop gpu serve` then `slop gpu pair` -> the user pastes ONE line on the PC")
        lines.append("  direct (no tunnel): `slop gpu direct-plan` -> the bot runs the worker through local exec")
        if sv["server"]:
            lines.append("  note: the GPU job server is still running" + (f" (public tunnel {sv['url']})" if sv.get("url")
                                                                         else "") + " - `slop gpu serve --stop` stops it")
        nxt = "slop gpu pair" if sv["server"] else "slop gpu serve"
    else:
        state = "healthy" if h["ok"] else "not ready"
        lines.append(f"GPU: {m} mode, {state}" + ("" if h["ok"] else f" - {h['why']}"))
        if m == "paired":
            lines.append(f"  server: {'up' if sv['server'] else 'DOWN'}" +
                         (f", tunnel {sv['url']}" if sv.get("url") else (", NO tunnel" if sv["server"] else "")))
        if w.get("seen"):
            lines.append(f"  worker: {w.get('os')} {w.get('arch')}, {w.get('backend')}, last seen {w.get('age_s'):.0f} s ago"
                         + (", pinned to one GPU" if w.get("pinned") else ""))
            code = w.get("code")
            if code and code != _server_code():
                lines.append("  worker code is OUT OF DATE: `slop gpu pair --new`, and the user pastes the new line on "
                             "the PC (about 10 s; profiles are kept; it installs the worker code this box serves)")
            for g in w.get("gpus") or []:
                lines.append(f"  GPU {g.get('index')} {g.get('name')} {_mib(g.get('total_mib'))}, {_mib(g.get('free_mib'))} free"
                             + (", display" if g.get("display") else "") + (f" - BUSY: {g['busy']}" if g.get("busy") else "")
                             + (" (picked)" if g.get("picked") else "") + (" (not used: pinned)" if g.get("pinned_out") else ""))
            profs = w.get("profiles") or {}
            if profs:
                lines.append("  profiles: " + ", ".join(
                    f"{k} {'ready' if v.get('ready') else ('stale' if v.get('stale') else 'not installed')}"
                    for k, v in profs.items() if v.get("supported")))
        elif m == "paired":
            lines.append("  worker: never checked in - paste the line from `slop gpu pair` on the PC")
        net = w.get("net") or {}
        if net.get("upload_MBps") or net.get("download_MBps"):
            lines.append("  network (last measured): PC upload " + (f"{net['upload_MBps']} MB/s" if net.get("upload_MBps")
                                                                   else "?") +
                         ", PC download " + (f"{net['download_MBps']} MB/s" if net.get("download_MBps") else "?"))
        active = [j for j in jobs if j["state"] in proto.ACTIVE]
        for j in active:
            pr = j.get("progress")
            lines.append(f"  running: {j['id']} {j.get('entry') or 'install ' + str(j.get('profile'))} "
                         f"{j.get('phase') or ''}" + (f" {pr * 100:.0f} %" if isinstance(pr, (int, float)) else ""))
        lines.append("  queue: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v) if any(counts.values())
                     else "  queue: empty")
        for jid in waiting_direct[:3]:
            lines.append(f"  waiting for the PC (direct mode): `slop gpu direct-plan {jid}`")
        ready = [k for k, v in ((w.get("profiles") or {}).items()) if v.get("ready")]
        if h["ok"] and not ready:
            nxt = "`slop gpu install audio matte` (the GPU profiles, once; several GB)"
        elif h["ok"]:
            nxt = "nothing: `slop analyze` and `slop edit export` use the GPU automatically (--gpu auto)"
        else:
            nxt = h["next"]
    verify = None
    if getattr(a, "verify", False) and sv.get("url"):
        ok, err = service.public_health(sv["url"], 20)
        verify = {"public_url_ok": ok, "error": err or None}
        lines.append(f"  tunnel check: {'ok' if ok else 'FAILED - ' + err}")
    lines.append(f"next: {nxt}")
    return {"mode": m, "healthy": h["ok"], "why": h["why"] or None, "server": sv, "worker": _public_worker(w),
            "queue": counts, "waiting_direct": waiting_direct, "verify": verify, "next": nxt, "text": "\n".join(lines)}


def _public_worker(w: dict) -> dict:
    return {k: w.get(k) for k in ("os", "arch", "backend", "age_s", "fresh", "gpus", "profiles", "pinned", "gpu_ok", "why",
                                  "code", "state") if k in w}


def _server_code() -> str:
    from .worker import code_hash
    return code_hash(Path(__file__).resolve().parent)


# ------------------------------------------------------------------------------------------------ serve / pair
def cmd_serve(a) -> dict:
    from . import service, store
    if a.stop:
        r = service.stop()
        again = ("the tunnel URL changes: then give the PC the line from `slop gpu pair --refresh`"
                 if store.has_code() else "then `slop gpu pair`")
        return {**r, "next": "slop gpu serve",
                "text": "GPU job server stopped" + (f" (was {r['url']})" if r.get("url") else "") +
                f"\nnext: `slop gpu serve` to start it again ({again})"}
    r = service.start(tunnel=not a.no_tunnel, port=a.port)
    if store.mode() == "none" or (store.mode() == "direct" and store.has_code()):
        store.save_config(mode="paired")        # serving = paired mode (a direct-mode box with a pairing goes back)
    lines = [f"GPU job server {'already running' if r['reused'] else 'started'} on 127.0.0.1:{r['port']}" +
             (f", public URL {r['url']}" if r.get("url") else " (no tunnel: only this machine can reach it)")]
    if r.get("url_changed"):
        nxt = "slop gpu pair --refresh"
        lines.append("the tunnel URL CHANGED: the paired PC must be told the new URL")
    elif store.has_code() and store.worker().get("seen"):
        nxt = "slop gpu status"
    else:
        nxt = "slop gpu pair"
    lines.append(f"next: {nxt}")
    return {**r, "next": nxt, "text": "\n".join(lines)}


def cmd_pair(a) -> dict:
    from . import service, store
    sv = service.status()
    url = (a.url or sv.get("url") or "").rstrip("/")
    if not sv["server"]:
        raise SlopError("the GPU job server is not running: run `slop gpu serve` first (it starts the Cloudflare quick "
                        "tunnel the PC connects to), then `slop gpu pair`")
    if not url:
        raise SlopError("the job server has no tunnel URL: run `slop gpu serve` (without --no-tunnel); --url is for a "
                        "worker on this same machine (tests)")
    if not a.url:                            # the PC must be able to reach this address, or the line is useless
        ok, err = service.public_health(url, 20)
        if not ok:
            raise SlopError(f"the tunnel's public URL does not answer ({err or 'no answer'}), so no pairing line was "
                            "made: it could never work. `slop gpu status --verify` must pass first. If the tunnel "
                            "never connected (the computer's network blocks port 7844), use direct mode: "
                            "`slop gpu direct-plan`")
    if a.refresh:
        if not store.has_code():
            raise SlopError("nothing is paired yet: run `slop gpu pair` (without --refresh)")
        lines = service.refresh_lines(url)
        text = ("The box's tunnel URL is now " + url + ". On the paired PC, run ONE line (no code needed):\n"
                f"  Windows PowerShell:  {lines['windows']}\n  macOS / Linux:       {lines['mac_linux']}\n"
                "next: slop gpu status (the worker should check in within a minute)")
        return {"url": url, "lines": lines, "next": "slop gpu status", "text": text}
    w = store.worker()
    if store.has_code() and w.get("seen") and not a.new:
        age = w.get("age_s") or 0
        raise SlopError(f"already paired: a {w.get('os') or 'PC'} worker, last seen {age:.0f} s ago "
                        "(`slop gpu status`). A new pairing would cut that worker off. If the tunnel URL changed: "
                        "`slop gpu pair --refresh`. If the PC is asleep or its worker stopped: on the PC "
                        "`slopgpu start`. Only to REPLACE the pairing (another PC, or updating the worker code): "
                        "`slop gpu pair --new` - the user must then paste the new line on the PC")
    code = store.new_code()
    store.save_config(mode="paired", url=url)
    lines = service.pair_lines(url, code, a.gpu)
    hours = store.BOOT_TTL_S // 3600
    text = ("Pair the user's GPU computer: they paste ONE line into a terminal ON THAT COMPUTER. It installs a small "
            "worker under their home folder (uv + Python 3.12 + this toolkit's worker, about 1 minute; GPU profiles "
            "download later, several GB), pairs it with this box and starts it.\n"
            f"  Windows (PowerShell):  {lines['windows']}\n"
            f"  macOS / Linux (bash):  {lines['mac_linux']}\n"
            f"The line holds a one-time pairing code: share it only with the user. It works once (the worker trades it "
            f"for its own secret within seconds) and expires unused after {hours} h. It is shown once; "
            "`slop gpu pair --new` makes a new one and cuts off the old worker, `slop gpu unpair` revokes it. The line "
            "installs the worker code this box serves; the worker runs only Claudia's own GPU steps and never uses a "
            "busy GPU.\n"
            "next: slop gpu status (when the PC says 'paired'), then slop gpu install audio matte")
    return {"url": url, "lines": lines, "code_shown_once": True, "expires_h": hours, "next": "slop gpu status",
            "text": text}


UNPAIR_WAIT_S = 12.0     # a polling worker hears "revoked" within 0.5 s; one in a job at its next beat (8 s)


def cmd_unpair(a) -> dict:
    from . import service, store
    w = store.worker()
    wid, live = w.get("worker_id"), bool(w.get("fresh"))
    t0 = time.time() - 1
    had = store.revoke()
    cancelled = store.cancel_open() if (store.gpath() / "jobs").is_dir() else []
    store.save_config(mode="none")
    told = None
    if live and wid and service.status()["server"]:
        t_end = time.monotonic() + (UNPAIR_WAIT_S if not a.keep_server else 0)
        while not store.refused_since(wid, t0) and time.monotonic() < t_end:
            time.sleep(0.3)                     # let the worker hear "revoked" before its server disappears
        told = store.refused_since(wid, t0) if not a.keep_server else None
    stopped = None
    if not a.keep_server:
        stopped = service.stop()
    lines = [("pairing revoked: the worker on the PC is refused from now on and stops by itself. To remove it there: "
              "`slopgpu unpair` and delete the .claudia-gpu folder in the home folder.") if had else "nothing was paired"]
    if told is False:
        lines.append(f"the PC's worker did not check in within {UNPAIR_WAIT_S:.0f} s (asleep or busy): it keeps "
                     "retrying the old address until the user runs `slopgpu unpair` (or `slopgpu stop`) on the PC")
    if cancelled:
        lines.append(f"cancelled {len(cancelled)} open GPU job(s)")
    if stopped and stopped.get("stopped"):
        lines.append("stopped the GPU job server and its public tunnel")
    elif a.keep_server and service.status()["server"]:
        lines.append("the GPU job server is still running (--keep-server): `slop gpu serve --stop` stops it")
    nxt = "slop gpu pair" if a.keep_server else "slop gpu serve"
    lines.append(f"next: `{nxt}` to pair a computer again" + ("" if a.keep_server else " (then `slop gpu pair`)"))
    return {"revoked": had, "cancelled": cancelled, "server_stopped": bool(stopped and stopped.get("stopped")),
            "worker_told": told, "next": nxt, "text": "\n".join(lines)}


def cmd_mode(a) -> dict:
    from . import route, store
    if not a.mode:
        m = store.mode()
        return {"mode": m, "text": f"GPU mode: {m}\nnext: slop gpu status"}
    if a.mode == "paired" and not store.has_code():
        store.save_config(mode="paired")
        return {"mode": "paired", "next": "slop gpu pair",
                "text": "GPU mode: paired (no computer is paired yet)\nnext: `slop gpu serve`, then `slop gpu pair`"}
    store.save_config(mode=a.mode)
    h = route.health()
    return {"mode": a.mode, "healthy": h["ok"], "next": "slop gpu status",
            "text": f"GPU mode: {a.mode}" + ("" if h["ok"] else f" (not ready: {h['why']})") +
                    ("\nnext: `slop gpu direct-plan` for the PC setup steps (once)" if a.mode == "direct" else
                     "\nnext: slop gpu status")}


# ------------------------------------------------------------------------------------------------ profiles / install
def cmd_profiles(a) -> dict:
    from . import proto
    from .profiles import describe
    rows = describe()
    lines = []
    for r in rows:
        tag = " (OPT-IN: " + r["opt_in"] + " licence)" if r["opt_in"] else (" (documented only)" if r["document_only"] else "")
        if not r["tested_for_real"] and not r["document_only"]:
            tag += " (NOT TESTED on real hardware yet)"
        lines.append(f"{r['profile']}{tag}: {r['what']}; >= {r['vram_gib']} GB VRAM, ~{r['download_gib']} GB download; "
                     f"{'/'.join(r['backends'])}" + (f"; Python {r['python']}" if r.get("python") else ""))
        if r.get("needs"):
            lines.append(f"    needs on the PC: {r['needs']}")
        for e in r["entries"]:
            lines.append(f"    {e}: {proto.ENTRIES[e]['what']}")
        lines.append("    licences: " + "; ".join(f"{k} {v}" for k, v in r["licences"].items()))
    return {"profiles": rows, "text": "\n".join(lines)}


def cmd_install(a) -> dict:
    from . import store
    from .profiles import PROFILES
    bad = [p for p in a.profile if p not in PROFILES]
    if bad:
        raise SlopError(f"unknown profile(s) {bad}; choose from {', '.join(PROFILES)} (see `slop gpu profiles`)")
    for p in a.profile:
        if PROFILES[p].get("document_only"):
            raise SlopError(f"profile {p} is documented only and cannot be installed")
        if PROFILES[p].get("opt_in") and not a.accept_licence:
            raise SlopError(f"profile {p} uses weights under the {PROFILES[p]['opt_in']} licence (use restrictions). Ask the "
                            "user; only if they accept, run `slop gpu install lipsync --accept-licence`")
    if store.mode() == "direct":
        cli = "& \"$env:USERPROFILE\\.claudia-gpu\\slopgpu.cmd\""
        cmds = [f"{cli} install {p}" + (" --accept-licence" if a.accept_licence else "") + " --detach" for p in a.profile]
        return {"direct": True, "commands": cmds,
                "text": "direct mode: run on the PC with local exec (Windows; on macOS/Linux use ~/.claudia-gpu/slopgpu):\n"
                        + "\n".join(f"  {c}" for c in cmds) + "\nnext: `slopgpu status` on the PC until the profile is ready"}
    if store.mode() != "paired" or not store.has_code():
        raise SlopError("no paired GPU computer: run `slop gpu serve` and `slop gpu pair` first")
    jobs = []
    for p in a.profile:
        existing = [j for j in store.all_jobs() if j["kind"] == "install" and j.get("profile") == p
                    and j["state"] not in ("succeeded", "failed", "cancelled", "interrupted", "timed_out")]
        jobs.append(existing[0] if existing else store.submit(kind="install", profile=p, origin="slop gpu install",
                                                              accept_licence=a.accept_licence))
    text = "\n".join(f"install {j['profile']}: job {j['id']} {j['state']}" for j in jobs)
    return {"jobs": [{"id": j["id"], "profile": j["profile"], "state": j["state"]} for j in jobs],
            "next": "slop gpu status", "text": text + "\nThe PC downloads and installs them one after the other (5-15 min "
                                                      "each, several GB).\nnext: slop gpu status (repeat until ready)"}


# ------------------------------------------------------------------------------------------------ jobs
def _job_line(j: dict) -> str:
    what = j.get("entry") or f"install {j.get('profile')}"
    m = j.get("metrics") or {}
    extra = f" {m.get('seconds')} s" if m.get("seconds") is not None else ""
    if j.get("error"):
        extra += f" - {j['error'][:120]}"
    elif j.get("blocked") and j["state"] == "queued":
        extra += f" - waiting: {j['blocked'][:100]}"
    return f"{j['id']} {j['state']:<11} {what}{extra}"


def cmd_jobs(a) -> dict:
    from . import proto, store
    jobs = store.all_jobs()
    if not a.all:
        jobs = [j for j in jobs if j["state"] not in proto.TERMINAL] + \
               [j for j in jobs if j["state"] in proto.TERMINAL][-a.limit:]
    jobs = sorted(jobs, key=lambda j: j.get("seq", 0))[-max(a.limit, 1) * 3:]
    rows = [{k: j.get(k) for k in ("id", "state", "kind", "entry", "profile", "phase", "progress", "created",
                                   "finished", "error", "origin", "blocked")} for j in jobs]
    return {"jobs": rows, "text": "\n".join(_job_line(j) for j in jobs) or "no GPU jobs"}


def cmd_show(a) -> dict:
    from . import store
    a.job = store.resolve(a.job)
    j = store.get(a.job)
    keep = {k: v for k, v in j.items() if k not in ("log_tail",)}
    lines = [_job_line(j)]
    if j.get("outputs"):
        lines.append("outputs: " + ", ".join(f"{o['name']} ({o['size'] / 2**20:.1f} MiB)" for o in j["outputs"]))
    if j.get("metrics"):
        lines.append("metrics: " + json.dumps(j["metrics"], default=str))
    if j.get("log_tail"):
        lines.append("log tail:\n" + j["log_tail"][-1500:])
    return {"job": keep, "log_tail": (j.get("log_tail") or "")[-3000:], "text": "\n".join(lines)}


def cmd_wait(a) -> dict:
    from . import proto, store
    a.job = store.resolve(a.job)
    t_end = time.monotonic() + _wait_max(a.timeout)
    while True:
        j = store.get(a.job)
        if j["state"] in proto.TERMINAL or time.monotonic() >= t_end:
            break
        time.sleep(1)
    done = j["state"] in proto.TERMINAL
    nxt = (f"slop gpu fetch {a.job} --to DIR" if j["state"] == "succeeded" else f"slop gpu show {a.job}") if done \
        else f"slop gpu wait {a.job}"
    return {"id": a.job, "state": j["state"], "phase": j.get("phase"), "progress": j.get("progress"), "done": done,
            "next": nxt, "text": _job_line(j) + f"\nnext: {nxt}"}


def cmd_cancel(a) -> dict:
    from . import store
    a.job = store.resolve(a.job)
    j = store.cancel(a.job)
    return {"id": a.job, "state": j["state"], "text": f"{a.job}: {j['state']}" +
            (" (cancel sent to the worker; it kills the job's processes)" if j.get("cancel_requested") else "")}


def cmd_fetch(a) -> dict:
    from . import store
    a.job = store.resolve(a.job)
    j = store.get(a.job)
    if j["state"] != "succeeded":
        raise SlopError(f"GPU job {a.job} is {j['state']}, not succeeded: `slop gpu show {a.job}`")
    dest = Path(a.to).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for o in j.get("outputs") or []:
        shutil.copyfile(store.job_dir(a.job) / "out" / o["name"], dest / o["name"])
        files.append(str(dest / o["name"]))
    return {"files": files, "text": f"copied {len(files)} file(s) to {dest}"}


def cmd_submit(a) -> dict:
    from . import proto, route, store
    if a.entry not in proto.ENTRIES:
        raise SlopError(f"unknown entry {a.entry}; choose from {', '.join(sorted(proto.ENTRIES))}")
    inputs = {}
    for spec in a.input or []:
        if "=" not in spec:
            raise SlopError(f"--input wants NAME=FILE (e.g. song.wav=audio/song.wav), got {spec!r}")
        n, f = spec.split("=", 1)
        inputs[n.strip()] = Path(f).expanduser()
    params = {}
    for spec in a.param or []:
        if "=" not in spec:
            raise SlopError(f"--param wants KEY=VALUE, got {spec!r}")
        k, v = spec.split("=", 1)
        try:
            params[k] = json.loads(v)
        except ValueError:
            params[k] = v
    h = route.health(proto.ENTRIES[a.entry]["profile"])
    if not h["ok"] and h["mode"] != "direct" and not a.force_gpu:
        raise SlopError(f"the GPU is not ready: {h['why']}. Next: {h['next']}")
    j = store.submit(a.entry, inputs, params, force_gpu=a.force_gpu, origin="slop gpu submit")
    if store.mode() == "direct":
        store.mark_direct(j["id"])
    nxt = f"slop gpu direct-plan {j['id']}" if store.mode() == "direct" else f"slop gpu wait {j['id']}"
    return {"id": j["id"], "state": j["state"], "next": nxt, "text": f"queued GPU job {j['id']} ({a.entry})\nnext: {nxt}"}


# ------------------------------------------------------------------------------------------------ direct mode
def cmd_direct_plan(a) -> dict:
    from . import direct
    return direct.job_plan(a.job, a.os) if a.job else direct.setup_plan(a.os, a.profile, a.use_direct)


def cmd_direct_ingest(a) -> dict:
    from . import direct
    return direct.ingest(a.job, a.src)


# ------------------------------------------------------------------------------------------------ --gpu on other commands
GPU_HELP = ("auto (default): run stems/alignment/depth on the paired home GPU when `slop gpu status` is healthy, else on "
            "the CPU with a note; require: the GPU or an error; off: the CPU")


def _wrap(orig, kind: str):
    def run(args) -> dict:
        from . import route
        m = getattr(args, "gpu", None) or os.environ.get("SLOP_GPU") or "auto"
        with route.session(m):
            if kind == "export" and route.mode() != "off" and getattr(args, "depth", "auto") != "off":
                _prefetch_depth(args)
            out = orig(args)
            lines = route.summary()
        if lines and isinstance(out, dict):
            out["gpu"] = {"mode": m, "used": list(route.USED), "notes": list(route.NOTES)}
            if isinstance(out.get("text"), str):
                out["text"] = out["text"] + "\n" + "\n".join(lines)
            if isinstance(out.get("notes"), list):
                out["notes"] = out["notes"] + list(route.NOTES)
        return out
    run.__wrapped__ = orig
    return run


def _prefetch_depth(args) -> None:
    """edit export: every picked plate's depth in ONE GPU job before the export loop asks for them one by one."""
    from ..config import resolve_project
    from ..edit import depth
    try:
        n = depth.gpu_prefetch(resolve_project(getattr(args, "project", None)))
        if n:
            from . import route
            route.note(f"depth maps for {n} plate(s) computed on the GPU in one job")
    except SlopError:
        raise
    except Exception as e:  # noqa: BLE001 - the CPU path still runs
        from . import route
        route.note(f"GPU depth prefetch skipped ({type(e).__name__}: {str(e)[:120]})")


def _attach(sub) -> None:
    ch = getattr(sub, "choices", {}) or {}
    targets = []
    if "analyze" in ch:
        targets.append((ch["analyze"], "analyze"))
    if "edit" in ch:
        for act in ch["edit"]._actions:
            if isinstance(act, argparse._SubParsersAction) and "export" in act.choices:
                targets.append((act.choices["export"], "export"))
    for p, kind in targets:
        if any("--gpu" in act.option_strings for act in p._actions):
            continue
        p.add_argument("--gpu", choices=["auto", "off", "require"], default=None, help=GPU_HELP)
        orig = p.get_default("func")
        if orig is not None:
            p.set_defaults(func=_wrap(orig, kind))


def register(sub) -> None:
    g = sub.add_parser("gpu", help="the user's home GPU: pair it, status, profiles, jobs (KITOUT section 3)",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    gs = g.add_subparsers(dest="gpu_cmd", metavar="ACTION")
    g.set_defaults(func=cmd_status, verify=False)
    p = leaf(gs, "status", "is a home GPU paired and healthy? its GPUs, profiles, queue and the next step")
    p.add_argument("--verify", action="store_true", help="also fetch /gpu/health through the public tunnel URL")
    p.set_defaults(func=cmd_status)
    p = leaf(gs, "serve", "start the box's GPU job server + Cloudflare quick tunnel in the background")
    tg = p.add_mutually_exclusive_group()
    tg.add_argument("--tunnel", action="store_true", help="with the quick tunnel (the default; accepted for clarity)")
    tg.add_argument("--no-tunnel", action="store_true", help="localhost only (a worker on this same machine, tests)")
    p.add_argument("--port", type=int, help="local port (default: a free one)")
    p.add_argument("--stop", action="store_true", help="stop the server and the tunnel")
    p.set_defaults(func=cmd_serve)
    p = leaf(gs, "pair", "print the ONE line the user pastes on the GPU computer (Windows PowerShell or bash). Refused "
                         "while a worker is paired: a new pairing cuts the old worker off (use --new for that)")
    pg = p.add_mutually_exclusive_group()
    pg.add_argument("--refresh", action="store_true", help="the tunnel URL changed: print the short re-pair line (keeps "
                                                           "the pairing)")
    pg.add_argument("--new", action="store_true", help="replace the current pairing: the paired worker is cut off and "
                                                       "the user must paste the new line (another PC, or a worker update)")
    p.add_argument("--gpu", help="pin the worker to one GPU (its UUID or index from nvidia-smi); default: the free GPU "
                                 "with the most memory")
    p.add_argument("--url", help="pair against this URL instead of the tunnel: only a worker on this same machine "
                                 "(http://127.0.0.1:PORT, tests); the worker accepts https or localhost only")
    p.set_defaults(func=cmd_pair)
    p = leaf(gs, "unpair", "revoke the pairing (the worker on the PC stops), cancel open GPU jobs, stop the server and "
                           "its public tunnel")
    p.add_argument("--keep-server", action="store_true", help="leave the job server and tunnel running")
    p.set_defaults(func=cmd_unpair)
    p = leaf(gs, "mode", "show or switch the GPU mode: paired (the worker polls the box) or direct (local exec)")
    p.add_argument("mode", nargs="?", choices=["paired", "direct"])
    p.set_defaults(func=cmd_mode)
    p = leaf(gs, "profiles", "the GPU profiles: what they run, VRAM, download size, licences")
    p.set_defaults(func=cmd_profiles)
    p = leaf(gs, "install", "install GPU profiles on the paired PC (queued; watch with slop gpu status)")
    p.add_argument("profile", nargs="+", help="audio | matte | interp | lipsync")
    p.add_argument("--accept-licence", action="store_true", help="the user accepted the profile's licence (lipsync)")
    p.set_defaults(func=cmd_install)
    p = leaf(gs, "jobs", "the GPU job queue")
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_jobs)
    jh = "the job id (32 hex digits) or its first 6 or more"
    p = leaf(gs, "show", "one job: state, metrics, outputs, log tail")
    p.add_argument("job", help=jh)
    p.set_defaults(func=cmd_show)
    p = leaf(gs, "wait", "wait for a job (at most --timeout s, default 25 / SLOP_WAIT_MAX)")
    p.add_argument("job", help=jh)
    p.add_argument("--timeout", type=float)
    p.set_defaults(func=cmd_wait)
    p = leaf(gs, "cancel", "cancel a job (a running job's processes are killed on the PC)")
    p.add_argument("job", help=jh)
    p.set_defaults(func=cmd_cancel)
    p = leaf(gs, "fetch", "copy a finished job's outputs")
    p.add_argument("job", help=jh)
    p.add_argument("--to", required=True)
    p.set_defaults(func=cmd_fetch)
    p = leaf(gs, "submit", "run one GPU entry by hand (see slop gpu profiles for the entries)")
    p.add_argument("entry")
    p.add_argument("--input", action="append", help="NAME=FILE (the names the entry expects, e.g. img-000.png)")
    p.add_argument("--param", action="append", help="KEY=VALUE (JSON values allowed)")
    p.add_argument("--force-gpu", action="store_true", help="run even on a busy GPU (the user said so)")
    p.set_defaults(func=cmd_submit)
    p = leaf(gs, "direct-plan", "direct mode: the exact local-exec steps for the PC (setup, or one JOB). The setup "
                                "plan switches to direct mode only when no mode is set yet, or with --use-direct")
    p.add_argument("job", nargs="?", help=jh)
    p.add_argument("--os", choices=["windows", "mac_linux"], default="windows")
    p.add_argument("--profile", default="audio", help="the profile the setup plan installs (default audio)")
    p.add_argument("--use-direct", action="store_true",
                   help="switch a paired box to direct mode (`slop gpu mode paired` switches back)")
    p.set_defaults(func=cmd_direct_plan)
    p = leaf(gs, "direct-ingest", "direct mode: finish JOB from the output parts copied back with CopyToBox")
    p.add_argument("job", help=jh)
    p.add_argument("--from", dest="src", help="folder holding JOB-out.zip.001 ... (default: the job's back/ folder)")
    p.set_defaults(func=cmd_direct_ingest)
    _attach(sub)
