"""`slop gpu serve`: the job server + its Cloudflare quick tunnel as detached processes, their state, the pairing
lines and the health check the routing uses.

State: $SLOP_HOME/gpu/server.json {server_pid, port, tunnel_pid, url, started}; logs gpu/server.log, gpu/tunnel.log.
A quick tunnel gets a NEW random https://<words>.trycloudflare.com URL every time it starts, so a restarted tunnel
means the paired computer must be pointed at the new URL (`slop gpu pair --refresh` prints the short line for it).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import SlopError, toolkit_root
from . import store

# Windows: console helpers must never flash a window on the user's desktop.
NOWIN = {"creationflags": 0x08000000} if os.name == "nt" else {}


def state_file() -> Path:
    return store.gdir() / "server.json"


def read_state() -> dict:
    try:
        return json.loads((store.gpath() / "server.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def alive(pid) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True, **NOWIN)
            return str(int(pid)) in r.stdout
        try:
            done, _ = os.waitpid(int(pid), os.WNOHANG)          # our own exited child: reap it
            if done == int(pid):
                return False
        except ChildProcessError:
            pass
        os.kill(int(pid), 0)
        try:
            with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as f:
                return f.read().split(")")[-1].split()[0] != "Z"
        except OSError:
            return True
    except (OSError, ValueError):
        return False


def kill(pid) -> None:
    try:
        if int(pid) in (os.getpid(), os.getppid()):    # a stale or hand-written server.json: never ourselves
            return
    except (TypeError, ValueError):
        return
    if not alive(pid):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, **NOWIN)
            return
        import signal
        try:
            os.killpg(int(pid), signal.SIGTERM)
        except OSError:
            os.kill(int(pid), signal.SIGTERM)
        for _ in range(30):
            if not alive(pid):
                return
            time.sleep(0.1)
        try:
            os.killpg(int(pid), signal.SIGKILL)
        except OSError:
            os.kill(int(pid), signal.SIGKILL)
    except OSError:
        pass


def spawn(cmd: list[str], log: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(toolkit_root()) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    kw: dict = {"stdout": open(log, "ab"), "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def local_health(port, timeout: float = 3.0) -> bool:
    if not port:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/gpu/health", timeout=timeout) as r:
            return r.status == 200 and json.loads(r.read()).get("ok") is True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def public_health(url: str, wait_s: float = 30.0) -> tuple[bool, str]:
    t_end = time.monotonic() + wait_s
    err = ""
    while True:
        try:
            req = urllib.request.Request(url.rstrip("/") + "/gpu/health", headers={"User-Agent": "claudia-gpu/1"})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200 and json.loads(r.read()).get("ok") is True:
                    return True, ""
                err = f"HTTP {r.status}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = str(getattr(e, "reason", e))[:160]
        if time.monotonic() > t_end:
            return False, err
        time.sleep(2)


def status() -> dict:
    st = read_state()
    srv = alive(st.get("server_pid")) and local_health(st.get("port"))
    tun = bool(st.get("tunnel_pid")) and alive(st.get("tunnel_pid")) and bool(st.get("url"))
    return {"server": srv, "tunnel": tun, "url": st.get("url") if tun else None, "port": st.get("port"),
            "started": st.get("started"), "local_url": f"http://127.0.0.1:{st['port']}" if srv and st.get("port") else None}


def _cloudflared() -> str:
    from ..gen.hosting import cloudflared_bin
    return cloudflared_bin()


def _start_tunnel(port: int, wait_s: float) -> tuple[int, str]:
    from ..gen.hosting import await_edge, cloudflared_cmd, tunnel_url
    log = store.gdir() / "tunnel.log"
    log.write_text("", encoding="utf-8")
    tun = spawn(cloudflared_cmd(_cloudflared(), port), log)
    t_end = time.monotonic() + wait_s
    url = None
    while time.monotonic() < t_end:
        url = tunnel_url(log.read_text(encoding="utf-8", errors="replace"))
        if url or tun.poll() is not None:
            break
        time.sleep(0.3)
    if url:
        time.sleep(0.5)
        if tun.poll() is not None:
            url = None
    if not url:
        tail = log.read_text(encoding="utf-8", errors="replace")[-500:]
        kill(tun.pid)
        raise SlopError("the Cloudflare quick tunnel did not come up (no URL in cloudflared's banner, or it exited): the "
                        "box may have no outbound access to Cloudflare (port 7844). Use direct mode instead: "
                        "`slop gpu direct-plan`. cloudflared said: " + tail.strip()[-300:])
    ok, why = await_edge(tun, log, public_ok=lambda: public_health(url, 5)[0])
    if not ok:
        kill(tun.pid)
        raise SlopError(why + " No pairing line was made. Use direct mode instead (no tunnel: the bot runs the worker "
                        "on the PC through Grok Bot local exec): `slop gpu direct-plan`.")
    return tun.pid, url


def start(tunnel: bool = True, port: int | None = None, wait_s: float = 45.0) -> dict:
    """Start (or reuse) the server and, with tunnel, the quick tunnel. -> status + {"reused", "url_changed"}."""
    st = status()
    old_url = store.config().get("url")
    if st["server"] and (st["tunnel"] or not tunnel):
        return {**st, "reused": True, "url_changed": False}
    s = read_state()
    if not st["server"]:
        kill(s.get("tunnel_pid"))
        kill(s.get("server_pid"))
        port = port or free_port()
        log = store.gdir() / "server.log"
        srv = spawn([sys.executable, "-m", "slop.gpu.server", "--port", str(port)], log)
        t_end = time.monotonic() + 15
        while time.monotonic() < t_end and not local_health(port, 1.0):
            if srv.poll() is not None:
                break
            time.sleep(0.2)
        if not local_health(port, 2.0):
            tail = log.read_text(encoding="utf-8", errors="replace")[-400:] if log.exists() else ""
            kill(srv.pid)
            raise SlopError(f"the GPU job server did not start on port {port}: {tail.strip()[-300:]}")
        s = {"server_pid": srv.pid, "port": port, "tunnel_pid": None, "url": None,
             "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
        state_file().write_text(json.dumps(s, indent=1), encoding="utf-8")
    if tunnel:
        kill(s.get("tunnel_pid"))
        s["tunnel_pid"], s["url"] = _start_tunnel(int(s["port"]), wait_s)
        state_file().write_text(json.dumps(s, indent=1), encoding="utf-8")
        store.save_config(url=s["url"])
    out = status()
    return {**out, "reused": False,
            "url_changed": bool(tunnel and old_url and out.get("url") and old_url != out["url"] and store.has_code())}


def stop() -> dict:
    s = read_state()
    kill(s.get("tunnel_pid"))
    kill(s.get("server_pid"))
    if state_file().exists():
        state_file().unlink()
    return {"stopped": bool(s), "url": s.get("url")}


# ------------------------------------------------------------------------------------------------ pairing lines
def _sq(s: str) -> str:
    """single-quoted literal for PowerShell and POSIX sh (the code and URL never contain quotes, but be safe)."""
    if "'" in s:
        raise SlopError("unexpected quote in a pairing value")
    return f"'{s}'"


def pair_lines(url: str, code: str, gpu: str | None = None) -> dict:
    pin_ps = f"$env:SLOPGPU_GPU={_sq(gpu)}; " if gpu else ""
    pin_sh = f" SLOPGPU_GPU={_sq(gpu)}" if gpu else ""
    ps = (f"$env:SLOPGPU_URL={_sq(url)}; $env:SLOPGPU_TOKEN={_sq(code)}; {pin_ps}"
          "irm \"$env:SLOPGPU_URL/gpu/install.ps1\" -Headers @{Authorization=\"Bearer $env:SLOPGPU_TOKEN\"} | iex")
    sh = (f"curl -fsSL -H {_sq('Authorization: Bearer ' + code)} {_sq(url + '/gpu/install.sh')} | "
          f"SLOPGPU_URL={_sq(url)} SLOPGPU_TOKEN={_sq(code)}{pin_sh} bash")
    return {"windows": ps, "mac_linux": sh}


def refresh_lines(url: str) -> dict:
    return {"windows": f"& \"$env:USERPROFILE\\.claudia-gpu\\slopgpu.cmd\" url {_sq(url)}",
            "mac_linux": f"~/.claudia-gpu/slopgpu url {_sq(url)}"}
