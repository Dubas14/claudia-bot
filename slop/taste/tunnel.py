"""Cloudflare quick tunnel for the tap app (the box has no public preview URL; research 08 / ARCHITECTURE §2).

`cloudflared tunnel --no-autoupdate --url http://127.0.0.1:PORT` prints a random https://<words>.trycloudflare.com
URL; the app itself lives under a random token path, so the public URL alone reveals nothing. The binary is looked
up at $SLOP_HOME/bin/cloudflared (installed by bin/setup.sh), then on PATH. Quick tunnels need no account.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..config import SlopError, slop_home

URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")


def find_cloudflared() -> Path:
    names = ["cloudflared.exe", "cloudflared"] if os.name == "nt" else ["cloudflared"]
    for n in names:
        p = slop_home() / "bin" / n
        if p.is_file():
            return p
    w = shutil.which("cloudflared")
    if w:
        return Path(w)
    raise SlopError(f"cloudflared not found in {slop_home() / 'bin'} or on PATH: run bin/setup.sh (it downloads the "
                    "official cloudflared release into $SLOP_HOME/bin), or serve without --tunnel on the same network")


def spawn_detached(cmd: list[str], log: Path, env: dict | None = None, cwd: str | None = None) -> subprocess.Popen:
    f = open(log, "ab")
    kw: dict = {"stdout": f, "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env, "cwd": cwd}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def start(port: int, log: Path, binary: Path | None = None, timeout: float = 45.0) -> dict:
    """start a quick tunnel to 127.0.0.1:port; -> {pid, url}. Raises with the log tail if no URL appears."""
    b = binary or find_cloudflared()
    log.write_bytes(b"")
    from ..gen.hosting import await_edge, cloudflared_cmd, origin_answers
    p = spawn_detached(cloudflared_cmd(b, port), log)
    url = wait_url(log, timeout, proc=p)
    if not url:
        stop_pid(p.pid)
        tail = log.read_text(encoding="utf-8", errors="replace")[-600:] if log.exists() else ""
        raise SlopError(f"cloudflared started but printed no trycloudflare.com URL within {timeout:.0f} s. "
                        f"Log tail: {tail.strip()[-300:]}  Re-run `slop taste serve --tunnel`; if it keeps failing, "
                        "the network may block Cloudflare")
    ok, why = await_edge(p, log, public_ok=lambda: origin_answers(url))
    if not ok:
        stop_pid(p.pid)
        raise SlopError(why)
    return {"pid": p.pid, "url": url}


def wait_url(log: Path, timeout: float, proc=None) -> str | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            m = URL_RE.search(log.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            m = None
        if m:
            return m.group(0)
        if proc is not None and proc.poll() is not None:
            return None
        time.sleep(0.25)
    return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True,
                                 timeout=10).stdout
            return str(int(pid)) in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie child of ours is not alive
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def stop_pid(pid: int | None) -> bool:
    if not pid or not pid_alive(pid):
        return False
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=15)
        else:
            import signal
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                os.kill(int(pid), signal.SIGTERM)
            for _ in range(40):
                if not pid_alive(pid):
                    break
                time.sleep(0.05)
            if pid_alive(pid):
                try:
                    os.killpg(int(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    os.kill(int(pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def python_cmd() -> str:
    return sys.executable
