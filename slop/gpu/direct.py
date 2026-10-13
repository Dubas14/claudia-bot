"""Direct mode: no networking between the box and the PC. The bot itself moves the files and runs the worker on the
user's computer through Grok Bot local exec (each command needs the user's approval unless they chose "Always
allow" for that computer). CopyFromBox / CopyToBox move at most 100 MiB a file, so bundles travel in parts of at most
95 MiB (NAME.001, NAME.002 ...).

  slop gpu direct-plan            one-time setup: copy the kit to the PC, run the installer there, install a profile
  slop gpu direct-plan JOB        pack JOB (manifest + inputs) into parts and print every step for the PC
  slop gpu direct-ingest JOB      after the output parts were copied back: join, verify, finish the job

Paths on the PC are relative to the user's home folder (the local-exec root), so the same lines work for every user.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from ..config import SlopError
from . import proto, store

PC_DIR = ".claudia-gpu"


def ddir(jid: str | None = None) -> Path:
    d = store.gdir() / "direct" / (jid or "kit")
    d.mkdir(parents=True, exist_ok=True)
    return d


def kit() -> dict:
    """Copy the installers + worker.zip into gpu/direct/kit (what the bot copies to the PC once)."""
    from .server import worker_zip
    d = ddir()
    from .server import installer_bytes
    for kind in ("ps1", "sh"):
        (d / f"gpu-worker.{kind}").write_bytes(installer_bytes(kind))
    shutil.copyfile(worker_zip(), d / "slopgpu-worker.zip")
    return {"dir": str(d), "files": ["gpu-worker.ps1", "gpu-worker.sh", "slopgpu-worker.zip"]}


def setup_plan(os_name: str = "windows", profile: str = "audio", use_direct: bool = False) -> dict:
    """The one-time PC setup steps. Switches the box to direct mode only when no mode is set yet, or with use_direct
    (`slop gpu direct-plan --use-direct`): printing the plan never cuts off a working paired worker."""
    k = kit()
    before = store.mode()
    if before == "none" or use_direct:
        store.save_config(mode="direct")
    now = store.mode()
    d = k["dir"]
    win = os_name == "windows"
    inst = (f"$env:SLOPGPU_MODE='direct'; powershell -NoProfile -ExecutionPolicy Bypass -File "
            f"\"$env:USERPROFILE\\{PC_DIR}\\kit\\gpu-worker.ps1\"") if win else \
        f"SLOPGPU_MODE=direct bash ~/{PC_DIR}/kit/gpu-worker.sh"
    cli = f"& \"$env:USERPROFILE\\{PC_DIR}\\slopgpu.cmd\"" if win else f"~/{PC_DIR}/slopgpu"
    steps = [
        {"tool": "CopyFromBox", "from": f"{d}/gpu-worker.{'ps1' if win else 'sh'}",
         "to": f"{PC_DIR}/kit/gpu-worker.{'ps1' if win else 'sh'}"},
        {"tool": "CopyFromBox", "from": f"{d}/slopgpu-worker.zip", "to": f"{PC_DIR}/kit/slopgpu-worker.zip"},
        {"tool": "MachineShell", "run": inst, "note": "installs uv + Python 3.12 + the worker under the home folder "
                                                      "(about 1 minute)"},
        {"tool": "MachineShell", "run": f"{cli} install {profile} --detach",
         "note": f"installs the {profile} profile in the background (5-15 min, several GB of downloads)"},
        {"tool": "MachineShell", "run": f"{cli} status",
         "note": f"repeat until profiles.{profile}.ready is true (one short call per turn, under 30 s)"},
    ]
    text = "\n".join([f"Direct mode setup ({'Windows PowerShell' if win else 'macOS/Linux shell'}; the PC paths are "
                      "relative to the user's home folder):"] +
                     [f"{i}. {s['tool']}: " + (f"{s['from']} -> {s['to']}" if s["tool"] != "MachineShell" else s["run"])
                      + (f"   ({s['note']})" if s.get("note") else "") for i, s in enumerate(steps, 1)] +
                     ["then: run the step with --gpu require (it queues a GPU job and waits), and "
                      "`slop gpu direct-plan JOB` prints that job's steps"])
    if now != "direct":
        text += (f"\nNOTE: the box stays in {now} mode (nothing was switched). Only if the user wants direct mode "
                 "instead: `slop gpu direct-plan --use-direct` (or `slop gpu mode direct`); `slop gpu mode paired` "
                 "switches back")
    elif before == "paired":
        text += "\nNOTE: switched from paired to direct mode; `slop gpu mode paired` switches back"
    return {"mode": now, "switched": now != before, "steps": steps, "kit": d, "text": text,
            "next": f"CopyFromBox {d}/gpu-worker.{'ps1' if win else 'sh'} to {PC_DIR}/kit/ on the PC"}


def job_plan(jid: str, os_name: str = "windows") -> dict:
    jid = store.resolve(jid)
    j = store.get(jid)
    if j["state"] in proto.TERMINAL:
        raise SlopError(f"GPU job {jid} already ended ({j['state']}); nothing to run")
    if j["state"] in proto.ACTIVE:
        raise SlopError(f"GPU job {jid} is running on the paired worker; direct mode is not needed")
    store.mark_direct(jid)
    d = ddir(jid)
    for old in d.glob(f"{jid}.zip.*"):
        old.unlink()
    z = d / f"{jid}.zip"
    with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("manifest.json", json.dumps(store.manifest(j)))
        for f in j.get("inputs") or []:
            zf.write(store.job_dir(jid) / "in" / f["name"], f"in/{f['name']}")
    parts = proto.split_file(z, proto.PART)
    z.unlink()
    (d / "back").mkdir(exist_ok=True)
    win = os_name == "windows"
    cli = f"& \"$env:USERPROFILE\\{PC_DIR}\\slopgpu.cmd\"" if win else f"~/{PC_DIR}/slopgpu"
    steps = [{"tool": "CopyFromBox", "from": str(p), "to": f"{PC_DIR}/inbox/{p.name}"} for p in parts]
    steps += [
        {"tool": "MachineShell", "run": f"{cli} run-bundle {jid} --detach", "note": "starts the job in the background"},
        {"tool": "MachineShell", "run": f"{cli} bundle-status {jid}",
         "note": "repeat (one call per turn) until finished is true; it lists the output parts"},
        {"tool": "CopyToBox", "from": f"{PC_DIR}/outbox/{jid}/{jid}-out.zip.001 (and .002 ... as listed)",
         "to": f"{d / 'back'}/"},
        {"tool": "shell (box)", "run": f"slop gpu direct-ingest {jid}"},
    ]
    size = sum(p.stat().st_size for p in parts)
    text = "\n".join([f"GPU job {jid} ({j.get('entry') or j.get('profile')}), {size / 2**20:.1f} MiB in {len(parts)} "
                      "part(s); on the PC (paths relative to the home folder):"] +
                     [f"{i}. {s['tool']}: " + (s["run"] if "run" in s else f"{s['from']} -> {s['to']}") +
                      (f"   ({s['note']})" if s.get("note") else "") for i, s in enumerate(steps, 1)])
    return {"job": jid, "parts": [str(p) for p in parts], "steps": steps, "text": text,
            "next": steps[0]["tool"] + " " + steps[0]["from"]}


def ingest(jid: str, src: str | None = None) -> dict:
    jid = store.resolve(jid)
    j = store.get(jid)
    if j["state"] in proto.TERMINAL:
        return {"job": jid, "state": j["state"], "text": f"GPU job {jid} already ended: {j['state']}"}
    back = Path(src) if src else ddir(jid) / "back"
    parts = sorted(back.glob(f"{jid}-out.zip.[0-9][0-9][0-9]"))
    if not parts:
        raise SlopError(f"no {jid}-out.zip.001 in {back}: CopyToBox the output parts listed by `slopgpu bundle-status "
                        f"{jid}` into that folder first")
    work = ddir(jid) / "ingest"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    z = proto.join_parts(parts, work / "out.zip")
    try:
        proto.safe_extract(z, work / "x")
    except (zipfile.BadZipFile, proto.ManifestError) as e:
        raise SlopError(f"the output parts do not form a valid bundle ({e}): copy every part again") from None
    status = proto.read_json(work / "x" / "status.json", {}) or {}
    outs = []
    out_dir = store.job_dir(jid) / "out"
    out_dir.mkdir(exist_ok=True)
    for p in sorted((work / "x").iterdir()):
        if p.name == "status.json" or not p.is_file():
            continue
        proto.safe_name(p.name)
        shutil.copyfile(p, out_dir / p.name)
        outs.append(proto.file_entry(out_dir / p.name))
    body = {"state": status.get("state") or "failed", "error": status.get("error"), "result": status.get("result"),
            "metrics": status.get("metrics"), "outputs": outs, "log_tail": status.get("log_tail")}
    with store.locked():
        jj = store.get(jid)
        jj.update(state="running", worker_id="direct")
        store._save(jj)
    done = store.finish(jid, "direct", body)
    shutil.rmtree(ddir(jid), ignore_errors=True)
    return {"job": jid, "state": done["state"], "outputs": [o["name"] for o in done.get("outputs") or []],
            "error": done.get("error"),
            "text": f"GPU job {jid}: {done['state']}" + (f" - {done['error']}" if done.get("error") else
                                                       f", {len(done.get('outputs') or [])} output file(s)")}
