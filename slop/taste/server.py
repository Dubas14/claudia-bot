"""The tap server: stdlib ThreadingHTTPServer serving the phone-first feed (/) and the font A/B page (/fonts) under a
random token path, writing taste/taps.jsonl and taste/fonts/taps.jsonl. Port of the retired feed/server.py routes
(api/next, api/tap, api/pair, api/undo, api/meter, api/liked, img/<id>) with:
  * every route under /<token>/ (a random URL-safe secret; anything else is a bare 404), so it is safe behind a
    public Cloudflare quick tunnel;
  * security headers (nosniff, DENY framing, a same-origin CSP), a 16 KB body cap, 240 POSTs/min per client;
  * files served only from the pool's images, the session's font files and the static app (no path joins on
    user input).
Run by `slop taste serve` as a detached child: `python -m slop.taste.server --project-dir P --port N --token T
--taste-root R` (R = the project's taste profile root at start, pinned: a later `slop taste use` never redirects the
running app's writes; server.json lives in that root, so one app serves every project sharing the user profile).
Robustness (review round 1): any unexpected handler error answers 500 JSON instead of dropping the connection;
`/<token>/fonts/` redirects to `/<token>/fonts` (its relative assets would otherwise 404); server.json is written as
soon as the server is healthy, before the tunnel step, and a failed tunnel is not fatal (`tunnel_error`, local URL,
the server stays stoppable) — a failed `--tunnel` used to leave an orphan server that `status`/`stop` could not see.
"""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
import urllib.request
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from ..config import SlopError, toolkit_root
from .store import fonts_dir, images_dir, read_json, taste_dir, write_json

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"feed.html", "fonts.html", "feed.js", "fonts.js", "app.css"}
BODY_MAX = 16 * 1024
POSTS_PER_MIN = 240
CSP = ("default-src 'self'; img-src 'self' data:; font-src 'self'; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")


class App:
    def __init__(self, pdir: Path, token: str, embed: bool = True, background: bool = True):
        from .feed import Feed
        from .fonts import FontSession
        self.pdir = Path(pdir)
        self.token = token
        self.feed = Feed(self.pdir, background=background)
        self.fonts = FontSession(self.pdir)
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()
        self.feed.auto_embed = embed
        if embed:
            self.feed.start_embedding()

    def allow_post(self, ip: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= POSTS_PER_MIN:
                return False
            q.append(now)
            return True


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        server_version = "slop-taste"
        sys_version = ""

        def _headers(self, code: int, ctype: str, length: int, cache: str = "no-store") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()

        def _json(self, obj, code: int = 200) -> None:
            b = json.dumps(obj, default=str).encode("utf-8")
            self._headers(code, "application/json", len(b))
            self.wfile.write(b)

        def _bytes(self, b: bytes, ctype: str, cache: str = "no-store") -> None:
            self._headers(200, ctype, len(b), cache)
            self.wfile.write(b)

        def _file(self, p: Path, cache: str = "max-age=604800") -> None:
            try:
                b = p.read_bytes()
            except OSError:
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            if p.suffix.lower() in (".ttf", ".otf"):
                ctype = "font/ttf" if p.suffix.lower() == ".ttf" else "font/otf"
            elif p.suffix.lower() == ".woff2":
                ctype = "font/woff2"
            elif p.suffix.lower() == ".js":
                ctype = "text/javascript; charset=utf-8"
            elif p.suffix.lower() == ".css":
                ctype = "text/css; charset=utf-8"
            elif p.suffix.lower() == ".html":
                ctype = "text/html; charset=utf-8"
            self._bytes(b, ctype, cache)

        def _redirect(self, location: str) -> None:
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()

        def _route(self) -> str | None:
            """the path after /<token>/, or None (-> 404) if the token does not match"""
            path = urlparse(self.path).path
            parts = path.split("/", 2)
            if len(parts) < 2 or not hmac.compare_digest(parts[1].encode(), app.token.encode()):
                return None
            if len(parts) == 2:
                return ""  # /<token> -> redirect target
            return unquote(parts[2])

        def do_GET(self):  # noqa: N802
            self._safe(self._get)

        def do_POST(self):  # noqa: N802
            self._safe(self._post)

        def _safe(self, fn) -> None:
            """any unexpected error -> a 500 JSON answer (never a dropped connection); details go to server.log"""
            try:
                fn()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # noqa: BLE001
                import traceback
                print(f"error on {self.command} {urlparse(self.path).path[-40:]}: {type(e).__name__}: {e}", flush=True)
                traceback.print_exc()
                try:
                    self._json({"error": "server error, retrying is safe", "type": type(e).__name__}, 500)
                except OSError:
                    pass

        def _get(self) -> None:
            r = self._route()
            if r is None:
                return self._json({"error": "not found"}, 404)
            if r == "" and not urlparse(self.path).path.endswith("/"):
                return self._redirect(f"/{app.token}/")
            if r in ("", "index.html"):
                return self._file(STATIC / "feed.html", "no-store")
            if r == "fonts/":   # relative assets would resolve under /fonts/ -> redirect to the canonical URL
                return self._redirect(f"/{app.token}/fonts")
            if r == "fonts":
                return self._file(STATIC / "fonts.html", "no-store")
            if r.startswith("static/") and r[7:] in STATIC_FILES:
                return self._file(STATIC / r[7:], "no-store")
            if r == "api/health":
                return self._json({"ok": True, "app": "slop-taste"})
            if r == "api/meter":
                return self._json(app.feed.summary())
            if r == "api/liked":
                return self._json(app.feed.liked())
            if r.startswith("img/"):
                iid = r[4:]
                it = app.feed.pool.get(iid)
                if not it:
                    return self._json({"error": "unknown image"}, 404)
                return self._file(images_dir(app.pdir) / f"{it['id']}.jpg")
            if r == "frame.jpg":
                return self._file(fonts_dir(app.pdir) / "frame.jpg", "no-store")
            if r.startswith("font/"):
                p = app.fonts.font_path(r[5:])
                if not p:
                    return self._json({"error": "unknown font"}, 404)
                return self._file(p, "max-age=2592000")
            if r == "api/fonts/progress":
                app.fonts.reload()
                return self._json(app.fonts.progress())
            return self._json({"error": "not found"}, 404)

        def _post(self) -> None:
            r = self._route()
            if r is None:
                return self._json({"error": "not found"}, 404)
            peer = self.client_address[0]
            ip = (self.headers.get("CF-Connecting-IP") or peer) if peer == "127.0.0.1" else peer   # behind the tunnel
            if not app.allow_post(ip[:64]):
                return self._json({"error": "too many requests"}, 429)
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > BODY_MAX:
                return self._json({"error": "too large"}, 413)
            try:
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            ex = [str(x)[:200] for x in (body.get("exclude") or [])][:100] if isinstance(body.get("exclude"), list) else []
            try:
                if r == "api/next":
                    return self._json(app.feed.next(ex))
                if r == "api/tap":
                    rec = app.feed.record_tap(body)
                    return self._json({"ok": True, "undo": {"eid": rec["eid"]}, "meter": app.feed.summary()})
                if r == "api/pair":
                    rec = app.feed.record_pair(body)
                    return self._json({"ok": True, "undo": {"eid": rec["eid"]}, "meter": app.feed.summary()})
                if r == "api/undo":
                    app.feed.undo(str(body.get("eid") or ""))
                    return self._json({"ok": True, "meter": app.feed.summary()})
                if r == "api/fonts/next":
                    app.fonts.reload()
                    return self._json(app.fonts.next(ex))
                if r == "api/fonts/pick":
                    rec = app.fonts.record(body)
                    return self._json({"ok": True, "undo": {"eid": rec["eid"]}, "progress": app.fonts.progress()})
                if r == "api/fonts/undo":
                    app.fonts.undo(str(body.get("eid") or ""))
                    return self._json({"ok": True, "progress": app.fonts.progress()})
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            return self._json({"error": "not found"}, 404)

        def log_message(self, *a):  # quiet
            pass

    return H


def run(pdir: Path, host: str, port: int, token: str, embed: bool = True) -> None:
    app = App(pdir, token, embed=embed)
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    httpd.daemon_threads = True
    print(f"taste server: http://{host}:{port}/{token[:4]}…/  pool {len(app.feed.serve_ids)} images, "
          f"{len(app.feed.ids)} embedded", flush=True)
    httpd.serve_forever()


# ---------------------------------------------------------------- manager (used by the CLI)

def state_path(pdir: Path) -> Path:
    return taste_dir(pdir) / "server.json"


def free_port(host: str = "127.0.0.1") -> int:
    s = socket.socket()
    s.bind((host if host != "0.0.0.0" else "127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def health(port: int, token: str, timeout: float = 2.0, host: str = "127.0.0.1") -> bool:
    h = "127.0.0.1" if host in ("0.0.0.0", "", "localhost") else host
    try:
        with urllib.request.urlopen(f"http://{h}:{port}/{token}/api/health", timeout=timeout) as r:
            return r.status == 200 and json.loads(r.read()).get("ok") is True
    except (OSError, ValueError):
        return False


def _healthy(st: dict, host: str) -> bool:
    """the recorded server answers; a live process that is slow to answer (a loaded machine, background embedding)
    gets a second, longer chance instead of being killed and restarted on a new port"""
    from . import tunnel as T
    h = st.get("host", host)
    if health(st["port"], st["token"], host=h):
        return True
    return bool(st.get("pid") and T.pid_alive(st["pid"]) and health(st["port"], st["token"], timeout=8.0, host=h))


def urls(st: dict) -> dict:
    base = f"http://127.0.0.1:{st['port']}/{st['token']}/"
    out = {"local": base, "fonts_local": base + "fonts"}
    if st.get("tunnel", {}).get("url"):
        pub = st["tunnel"]["url"].rstrip("/") + f"/{st['token']}/"
        out.update(public=pub, fonts_public=pub + "fonts")
    return out


def serve(pdir: Path, port: int | None = None, host: str = "127.0.0.1", tunnel: bool = False,
          new_token: bool = False, embed: bool = True, wait: float = 25.0) -> dict:
    from . import tunnel as T
    pdir = Path(pdir)
    st = read_json(state_path(pdir), {}) or {}
    if st.get("port") and st.get("token") and not new_token and _healthy(st, host):
        reused = True
    else:
        reused = False
        if st.get("pid"):
            T.stop_pid(st.get("pid"))
        if (st.get("tunnel") or {}).get("pid"):
            T.stop_pid(st["tunnel"]["pid"])
        token = st.get("token") if (st.get("token") and not new_token) else secrets.token_urlsafe(18)
        port = port or free_port(host)
        log = taste_dir(pdir) / "server.log"
        from .threads import blas_env
        env = {**os.environ, **blas_env()}    # small BLAS pools: refits / meter do not fight the image embedding
        env["PYTHONPATH"] = str(toolkit_root()) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        cmd = [sys.executable, "-m", "slop.taste.server", "--project-dir", str(pdir), "--port", str(port),
               "--host", host, f"--token={token}", "--taste-root", str(taste_dir(pdir))]   # a token may start with - + ([] if embed else ["--no-embed"])
        p = T.spawn_detached(cmd, log, env=env, cwd=str(toolkit_root()))
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait and not health(port, token, host=host):
            if p.poll() is not None:
                break
            time.sleep(0.2)
        if not health(port, token, host=host):
            rc = p.poll()
            T.stop_pid(p.pid)
            tail = log.read_text(encoding="utf-8", errors="replace")[-800:] if log.exists() else ""
            why = f"it exited with code {rc}" if rc is not None else f"no answer after {wait:.0f} s"
            raise SlopError(f"the taste server did not come up on port {port} ({why}). Log tail: {tail.strip()[-400:]}  "
                            "Re-run without --port (a free port is picked), or run `slop taste serve --foreground` "
                            "to see the error")
        st = {"pid": p.pid, "port": port, "host": host, "token": token, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "tunnel": {}}
        write_json(state_path(pdir), st)      # recorded as soon as it is healthy: `stop` / `status` always find it
    tunnel_error = None
    if tunnel and not (st.get("tunnel", {}).get("pid") and T.pid_alive(st["tunnel"]["pid"])):
        try:
            st["tunnel"] = T.start(st["port"], taste_dir(pdir) / "tunnel.log")
        except (SlopError, OSError) as e:     # not fatal: the local app keeps running and stays stoppable
            st["tunnel"] = {}
            tunnel_error = str(e)
    if (st.get("tunnel") or {}).get("pid") and not T.pid_alive(st["tunnel"]["pid"]):
        st["tunnel"] = {}                     # a dead tunnel's URL must not be handed out again
    write_json(state_path(pdir), st)
    u = urls(st)
    link = u.get("public") or u["local"]
    if tunnel_error:
        text = (f"NO PUBLIC LINK: the tunnel failed ({tunnel_error})\n"
                f"The taste app {'is' if reused else 'was started'} running locally only: {u['local']} - this link "
                "works on this machine, not on the user's phone, so do not send it. Fix the tunnel (bin/setup.sh "
                "installs cloudflared) and re-run `slop taste serve --tunnel`; `slop taste stop` stops the local app.\n"
                "No tunnel at all? Send numbered pair sheets in the chat instead: slop taste sheet")
    else:
        text = (f"taste app {'already running' if reused else 'started'}: {link}\n"
                f"font A/B page: {u.get('fonts_public') or u['fonts_local']}\n"
                + ("" if u.get("public") else "(local only: add --tunnel for a phone-reachable https link)\n")
                + ("(bound to 0.0.0.0: on the LAN use this machine's address instead of 127.0.0.1)\n"
                   if st.get("host") == "0.0.0.0" else "")
                + "Send the link to the user; ~150 taps (about 7 minutes) is the recommended first session.")
    out = {"running": True, "reused": reused, "pid": st["pid"], "port": st["port"], "urls": u, "text": text}
    if tunnel_error:
        out["tunnel_error"] = tunnel_error
    return out


def stop(pdir: Path) -> dict:
    from . import tunnel as T
    st = read_json(state_path(pdir), {}) or {}
    killed = []
    if st.get("pid") and T.stop_pid(st["pid"]):
        killed.append("server")
    if (st.get("tunnel") or {}).get("pid") and T.stop_pid(st["tunnel"]["pid"]):
        killed.append("tunnel")
    if st:
        st.update(pid=None, tunnel={}, stopped=time.strftime("%Y-%m-%dT%H:%M:%S"))
        write_json(state_path(pdir), st)
    return {"stopped": killed, "text": ("stopped " + " and ".join(killed)) if killed else "nothing was running"}


def status(pdir: Path) -> dict:
    from . import tunnel as T
    st = read_json(state_path(pdir), {}) or {}
    up = bool(st.get("port") and st.get("token") and health(st["port"], st["token"], host=st.get("host", "127.0.0.1")))
    tun = bool((st.get("tunnel") or {}).get("pid") and T.pid_alive(st["tunnel"]["pid"]))
    out = {"running": up, "tunnel": tun}
    if up:
        out["urls"] = urls(st if tun else {**st, "tunnel": {}})
        try:   # the live app's view: background embedding progress / errors
            h = "127.0.0.1" if st.get("host", "127.0.0.1") in ("0.0.0.0", "") else st["host"]
            with urllib.request.urlopen(f"http://{h}:{st['port']}/{st['token']}/api/meter", timeout=3) as r:
                out["embedding"] = json.loads(r.read()).get("embedding")
        except (OSError, ValueError):
            pass
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m slop.taste.server")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--token", required=True)
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--taste-root", default=None, help="the taste profile root, fixed for this process's lifetime")
    a = ap.parse_args(argv)
    if a.taste_root:
        from .store import pin_root
        pin_root(Path(a.project_dir), Path(a.taste_root))   # `slop taste use` must never redirect a running app
    run(Path(a.project_dir), a.host, a.port, a.token, embed=not a.no_embed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
