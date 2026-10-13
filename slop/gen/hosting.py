"""HTTPS hosting for reference files (OpenRouter accepts audio/video references by HTTPS URL only).

Verified 2026-10-01 (paid probes): OpenRouter /api/v1/videos REJECTS data: URIs for audio ("Only HTTPS URLs are
allowed"); a Cloudflare quick tunnel serving a random token path works for both images and audio; a Higgsfield MCP
media URL (CloudFront) works too.

Three ways, in order of preference:
  1. tunnel      `slop gen tunnel start` runs a local token-path file server + `cloudflared tunnel --no-autoupdate
                 --url http://127.0.0.1:PORT`; `slop clip submit` then puts the window (OpenRouter) or the start image,
                 references and window (Higgsfield: the bot imports them with media_import_url) on it by itself, and
                 `slop gen host CLIP [--role start] --tunnel` does it by hand; each records
                 https://<random>.trycloudflare.com/<token>/<file>. The URL lives only while the tunnel runs (keep it up
                 until the job leaves "pending" / the import is done); restarting the tunnel changes the host — submit
                 re-hosts automatically.
  2. --url URL   the bot uploads the file with its Higgsfield connector (media_upload -> PUT with the signed header
                 `If-None-Match: *` (403 without it) -> media_confirm -> show_medias) and passes the public CloudFront
                 URL (and the media_id, reused by the Higgsfield path). The fallback when the tunnel cannot start.
  3. data:       experimental and KNOWN REJECTED for audio by OpenRouter (kept only behind --experimental).
State: $SLOP_HOME/run/tunnel.json (pids, port, token, url, share dir); logs in $SLOP_HOME/run/.
The binary: $SLOP_CLOUDFLARED, else $SLOP_HOME/bin/cloudflared, else `cloudflared` on PATH (bin/setup.sh installs it).
The public URL is read ONLY from cloudflared's banner (the "|  https://<words>.trycloudflare.com  |" line under "Your
quick Tunnel has been created"): its failure line `Post "https://api.trycloudflare.com/tunnel": dial tcp …` also
contains a trycloudflare URL and must never be taken for the tunnel. The tunnel counts as up only while cloudflared is
still running after the banner; `verify` (CLI default) also fetches a probe file through the public URL (a new hostname
can take a few seconds to resolve: a failed probe is reported, not fatal). A probe that answered is remembered in the
state ("verified_url"); `ensure_verified()` probes only until then. A paid OpenRouter submit that would send a tunnel URL
calls it first and refuses while the public URL does not answer (a new hostname took ~45 s to resolve in a real test).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..config import SlopError, slop_home

URL_RE = re.compile(r"https://(?!api\.)[a-z0-9-]+\.trycloudflare\.com\b")
BANNER = "quick tunnel has been created"
PROBE = "slop-probe.txt"


def tunnel_url(log: str) -> str | None:
    """the quick tunnel's public URL from cloudflared's log: the banner box line ("|  https://… |") or a URL printed
    after "Your quick Tunnel has been created" — never the api.trycloudflare.com endpoint from an error line."""
    after = False
    for line in log.splitlines():
        if BANNER in line.lower():
            after = True
        m = URL_RE.search(line)
        if m and ("|" in line or after):
            return m.group(0)
    return None


def run_dir() -> Path:
    d = slop_home() / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def share_dir() -> Path:
    d = slop_home() / "share"
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_file() -> Path:
    return run_dir() / "tunnel.json"


def cloudflared_bin() -> str:
    env = os.environ.get("SLOP_CLOUDFLARED")
    if env and Path(env).is_file():
        return env
    for name in ("cloudflared", "cloudflared.exe"):
        p = slop_home() / "bin" / name
        if p.is_file():
            return str(p)
    w = shutil.which("cloudflared")
    if w:
        return w
    from ..config import toolkit_root
    raise SlopError(f"cloudflared is not installed (it is REQUIRED for OpenRouter sung clips and the tap app): run bash "
                    f"{toolkit_root() / 'bin' / 'setup.sh'} --cloudflared (it downloads cloudflared into $SLOP_HOME/bin), "
                    "or host the file another way: upload it with the Higgsfield connector (media_upload; PUT with the "
                    "header 'If-None-Match: *') and run slop gen host CLIP --url URL")


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
            return str(pid) in r.stdout
        try:                                                      # reap it if it is our own exited child (zombie)
            done, _ = os.waitpid(pid, os.WNOHANG)
            if done == pid:
                return False
        except ChildProcessError:
            pass
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _kill(pid: int | None) -> None:
    if not pid or not _alive(pid):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                if not _alive(pid):
                    break
                time.sleep(.1)
            if _alive(pid):
                os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def _spawn(cmd: list[str], log: Path) -> subprocess.Popen:
    from ..config import toolkit_root
    env = dict(os.environ)
    env["PYTHONPATH"] = str(toolkit_root()) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    kw: dict = {"stdout": open(log, "ab"), "stderr": subprocess.STDOUT, "stdin": subprocess.DEVNULL, "env": env}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kw["start_new_session"] = True
    return subprocess.Popen(cmd, **kw)


def read_state() -> dict:
    p = state_file()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def status() -> dict:
    st = read_state()
    up = bool(st) and _alive(st.get("server_pid")) and _alive(st.get("tunnel_pid")) and bool(st.get("url"))
    return {"running": up, **{k: st.get(k) for k in ("url", "port", "share_dir", "started", "server_pid", "tunnel_pid")},
            **({"verified": True} if up and st.get("verified_url") == st.get("url") else {})}


def start(wait_s: float = 45.0, verify: bool = False, verify_s: float = 20.0) -> dict:
    """start (or reuse) the share server + quick tunnel; returns the state with the public base URL."""
    st = status()
    if st["running"]:
        return {**st, "reused": True, **(probe(verify_s) if verify else {})}
    stop()
    exe = cloudflared_bin()
    token = secrets.token_hex(12)
    port = _free_port()
    sd = share_dir()
    rd = run_dir()
    slog, tlog = rd / "share-server.log", rd / "tunnel.log"
    tlog.write_text("", encoding="utf-8")
    srv = _spawn([sys.executable, "-m", "slop.gen.serve", "--dir", str(sd), "--token", token, "--port", str(port)], slog)
    tun = _spawn([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"], tlog)
    state = {"server_pid": srv.pid, "tunnel_pid": tun.pid, "port": port, "token": token, "share_dir": str(sd),
             "url": None, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    state_file().write_text(json.dumps(state, indent=1), encoding="utf-8")
    t_end = time.monotonic() + wait_s
    url = None
    while time.monotonic() < t_end:
        url = tunnel_url(tlog.read_text(encoding="utf-8", errors="replace"))
        if url or tun.poll() is not None:
            break
        time.sleep(.3)
    if url:                                                       # cloudflared must still be running after the banner
        time.sleep(.5)
        if tun.poll() is not None or srv.poll() is not None:
            url = None
    if not url:
        tail = tlog.read_text(encoding="utf-8", errors="replace")[-600:]
        stop()
        raise SlopError("the Cloudflare quick tunnel did not come up (no tunnel URL in cloudflared's banner, or it exited). "
                        "The box may have no outbound access to Cloudflare (it needs outbound port 7844 or 443). Use the "
                        "Higgsfield upload instead (media_upload; PUT with the header 'If-None-Match: *'; media_confirm), "
                        "then: slop gen host CLIP --url URL. cloudflared said: " + tail.strip())
    state["url"] = url
    state_file().write_text(json.dumps(state, indent=1), encoding="utf-8")
    return {**status(), "reused": False, **(probe(verify_s) if verify else {})}


def probe(wait_s: float = 20.0) -> dict:
    """fetch a probe file through the public tunnel URL: {"verified": bool, "note"?}. Not fatal: a new quick-tunnel
    hostname can take a few seconds to resolve."""
    import urllib.error
    import urllib.request
    st = read_state()
    if not st.get("url"):
        return {"verified": False, "note": "no tunnel URL"}
    body = secrets.token_hex(8).encode()
    (Path(st["share_dir"]) / PROBE).write_bytes(body)
    url = f"{st['url']}/{st['token']}/{PROBE}"
    t_end = time.monotonic() + wait_s
    err = ""
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "claudia"}), timeout=8) as r:
                if r.status == 200 and r.read() == body:
                    _remember_verified(st["url"])
                    return {"verified": True}
                err = f"HTTP {r.status}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = str(getattr(e, "reason", e))[:120]
        if time.monotonic() + 2 > t_end:
            return {"verified": False, "error": err,
                    "note": f"the tunnel URL did not answer yet ({err}); new quick-tunnel hostnames can take ~30-60 s — "
                            "check with slop gen tunnel status --verify before submitting"}
        time.sleep(2)


def _remember_verified(url: str) -> None:
    st = read_state()
    if st.get("url") == url:
        st["verified_url"] = url
        try:
            state_file().write_text(json.dumps(st, indent=1), encoding="utf-8")
        except OSError:
            pass


def ensure_verified(wait_s: float = 20.0) -> dict:
    """{"verified": bool, "note"?}: the running tunnel's public URL answers. Free once a probe answered for this URL
    (remembered in the state); otherwise one probe of up to `wait_s` seconds."""
    st = status()
    if not st["running"]:
        return {"verified": False, "error": "not running", "note": "the tunnel is not running (slop gen tunnel start)"}
    if st.get("verified"):
        return {"verified": True}
    return probe(wait_s)


def unverified_msg(error: str | None = None) -> str:
    """the refusal line when a paid submit would send a tunnel URL that does not answer yet."""
    return ("the tunnel's public URL does not answer yet" + (f" ({error})" if error else "") + ": a new quick-tunnel "
            "hostname can take ~30-60 s to resolve. Nothing was sent or spent. Wait about 30 s, run slop gen tunnel "
            "status --verify until it says 'reachable through the public URL', then run this command again")


def stop() -> dict:
    st = read_state()
    _kill(st.get("tunnel_pid")); _kill(st.get("server_pid"))
    if state_file().is_file():
        state_file().unlink()
    return {"stopped": bool(st), "url": st.get("url")}


def publish(path: Path, name: str | None = None) -> str:
    """copy a file into the share dir and return its public tunnel URL (tunnel must be running)."""
    st = read_state()
    if not status()["running"]:
        raise SlopError("the tunnel is not running: start it with slop gen tunnel start")
    path = Path(path)
    if not path.is_file():
        raise SlopError(f"file not found: {path}")
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name or path.name)
    dst = Path(st["share_dir"]) / name
    shutil.copyfile(path, dst)
    return f"{st['url']}/{st['token']}/{name}"


def url_is_live_tunnel(url: str | None) -> bool:
    if not url or "trycloudflare.com" not in url:
        return True                                               # not a tunnel URL: nothing to check
    st = status()
    return bool(st["running"] and st.get("url") and url.startswith(st["url"] + "/"))


def check_https(url: str) -> str:
    u = (url or "").strip()
    if not u.startswith("https://"):
        raise SlopError(f"not an HTTPS URL: {u[:80]!r}. OpenRouter accepts audio/video references by HTTPS URL only "
                        "(upload with the Higgsfield connector and pass its https URL, or use --tunnel)")
    return u
