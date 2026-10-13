"""The box's GPU job server: `python -m slop.gpu.server --port PORT` (started detached by `slop gpu serve`).

Binds 127.0.0.1 only; the outside world reaches it through the Cloudflare quick tunnel. Every route except
/gpu/health needs `Authorization: Bearer <code>` (compared with the stored sha256, constant time). The bootstrap code
from `slop gpu pair` opens only the installers, worker.zip and hello; hello trades it for the worker's own secret,
which every other route needs (store.py). A valid code is never throttled; a client (Cloudflare's CF-Connecting-IP,
else the socket address) that sends 30 bad codes in a minute gets 429 for a minute. Bodies are size-capped (JSON
256 KiB, upload pieces 33 MiB).

TRUST: the installers and worker.zip are built from THIS checkout (uncommitted edits included), and the user's PC
runs them when the pairing line is pasted. Pasting a line again later runs whatever this box serves at that moment.

  GET  /gpu/health                        {"ok": true} (no auth; the tunnel check)
  GET  /gpu/install.ps1 | /gpu/install.sh the worker installers (bin/gpu-worker.ps1 / .sh of this checkout)
  GET  /gpu/worker.zip                    the worker code (slop/gpu worker files of this checkout)
  POST /gpu/api/hello                     {"info"}: the pairing check + first heartbeat (+ {"secret"} for a
                                          bootstrap code)
  POST /gpu/api/next                      {"info", "gpu_ok", "why"} -> {"job": manifest | null} (long poll, 20 s)
  GET  /gpu/api/jobs/ID/in/NAME           an input (Range requests)
  POST /gpu/api/jobs/ID/event             phase/progress/log tail/VRAM (or release) -> {"cancel": bool}
  PUT  /gpu/api/jobs/ID/out/NAME?offset=N one piece of an output
  POST /gpu/api/jobs/ID/done              the final report: state, outputs [{name,size,sha256}], result, metrics
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..config import SlopError, toolkit_root
from . import proto, store

LONG_POLL_S = 20.0
MAX_PIECE = proto.CHUNK + (1 << 20)
FAIL_LIMIT = 30                     # bad codes a minute from one client before it gets 429
_FAILS: dict[str, list[float]] = {}
_FAILS_LOCK = threading.Lock()
BOOT_ROUTES = ("/gpu/install.ps1", "/gpu/install.sh", "/gpu/worker.zip", "/gpu/api/hello")
JOB_RE = re.compile(r"^/gpu/api/jobs/([0-9a-f]{32})/(in|out|event|done)(?:/([^/?]+))?$")


def worker_zip() -> Path:
    """Deterministic zip of the worker-side files (+ a stub slop/__init__.py), rebuilt when they change."""
    import zipfile
    from .worker import WORKER_FILES, code_hash
    pkg = Path(__file__).resolve().parent
    h = code_hash(pkg)
    dest = store.gdir() / f"worker-{h}.zip"
    if dest.is_file():
        return dest
    tmp = dest.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        def add(arc: str, data: bytes) -> None:
            zi = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)
        from .. import __version__
        add("slop/__init__.py", f'"""claudia GPU worker (a subset of the toolkit)."""\n__version__ = "{__version__}"\n'
            .encode())
        for rel in WORKER_FILES:
            add(f"slop/gpu/{rel}", (pkg / rel).read_bytes().replace(b"\r\n", b"\n"))
    os.replace(tmp, dest)
    for old in store.gdir().glob("worker-*.zip"):
        if old != dest:
            old.unlink(missing_ok=True)
    return dest


def installer(kind: str) -> Path:
    return toolkit_root() / "bin" / ("gpu-worker.ps1" if kind == "ps1" else "gpu-worker.sh")


def installer_bytes(kind: str) -> bytes:
    """The installer as served: the bash one always with LF endings (a checkout made on Windows may hold CRLF, and
    `curl | bash` breaks on CR)."""
    data = installer(kind).read_bytes()
    return data if kind == "ps1" else data.replace(b"\r\n", b"\n")


class Handler(BaseHTTPRequestHandler):
    server_version = "claudia-gpu"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):  # quiet unless asked
        if os.environ.get("SLOP_GPU_SERVER_LOG"):
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, default=str).encode())

    def _err(self, code: int, msg: str) -> None:
        self.close_connection = True             # an unread request body must not leak into the next request
        self._json(code, {"ok": False, "error": msg})

    def _body(self, cap: int) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > cap:
            raise SlopError(f"request body too large ({n} bytes > {cap})")
        return self.rfile.read(n) if n else b""

    def _jbody(self) -> dict:
        raw = self._body(proto.MAX_JSON)
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            raise SlopError("body is not JSON") from None
        if not isinstance(d, dict):
            raise SlopError("body must be a JSON object")
        return d

    def _bearer(self) -> str:
        h = self.headers.get("Authorization") or ""
        return h[7:].strip() if h.lower().startswith("bearer ") else ""

    def _auth(self, path: str) -> str | None:
        """-> "boot" | "worker", or None after answering 401/429. The code is checked FIRST: a valid code is never
        throttled, and only failures count, per client."""
        kind = store.check_code(self._bearer())
        if kind == "worker" or (kind == "boot" and path in BOOT_ROUTES):
            return kind
        if kind == "boot":
            self._err(401, "this pairing code only installs and pairs the worker: paste the WHOLE line from "
                           "`slop gpu pair` on the PC")
            return None
        now = time.time()
        client = (self.headers.get("CF-Connecting-IP") or self.client_address[0] or "?").strip()[:64]
        with _FAILS_LOCK:
            if len(_FAILS) > 4096:
                for k in [k for k, v in _FAILS.items() if not v or now - v[-1] >= 60]:
                    del _FAILS[k]
            fails = [t for t in _FAILS.get(client, []) if now - t < 60]
            fails.append(now)
            _FAILS[client] = fails[-FAIL_LIMIT - 1:]
            limited = len(fails) > FAIL_LIMIT
        if limited:
            self._err(429, "too many bad pairing codes from this address; wait a minute")
        else:
            self._refused()
            self._err(401, "bad, expired or revoked pairing code: on the box run `slop gpu pair --new` and paste the "
                           "new line on the PC")
        return None

    def _refused(self) -> None:
        """Record that a worker heard 'revoked' (`slop gpu unpair` waits for that before it stops the server)."""
        w = (self.headers.get("X-Slopgpu-Worker") or "").strip()
        if re.match(r"^[0-9a-f]{8,32}$", w):
            try:
                store.note_refused(w)
            except OSError:
                pass

    def _wid(self) -> str:
        w = (self.headers.get("X-Slopgpu-Worker") or "").strip()
        if not re.match(r"^[0-9a-f]{8,32}$", w):
            raise SlopError("missing worker id header")
        return w

    def _route(self):
        u = urllib.parse.urlsplit(self.path)
        return u.path, urllib.parse.parse_qs(u.query)

    # ---------------------------------------------------------------- verbs
    def do_GET(self):  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self):  # noqa: N802
        self._dispatch("GET")

    def do_POST(self):  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self):  # noqa: N802
        self._dispatch("PUT")

    def _dispatch(self, verb: str) -> None:
        path, q = self._route()
        try:
            if path == "/gpu/health" and verb == "GET":
                return self._json(200, {"ok": True, "service": "claudia-gpu", "proto": proto.PROTO})
            if not path.startswith("/gpu/"):
                return self._err(404, "not found")
            kind = self._auth(path)
            if not kind:
                return
            if verb == "GET" and path in ("/gpu/install.ps1", "/gpu/install.sh"):
                return self._send(200, installer_bytes(path[-3:].lstrip(".")), "text/plain; charset=utf-8")
            if verb == "GET" and path == "/gpu/worker.zip":
                return self._send(200, worker_zip().read_bytes(), "application/zip")
            if verb == "POST" and path == "/gpu/api/hello":
                b = self._jbody()
                wid = self._wid()
                out = {"ok": True, "server": {"proto": proto.PROTO, "code": _code()}}
                if kind == "boot":                    # trade the pasted code for the worker's own secret
                    out["secret"] = store.new_worker_secret(wid)
                store.save_worker(wid, b.get("info") or {}, state="hello")
                return self._json(200, out)
            if verb == "POST" and path == "/gpu/api/next":
                store.retire_boot()                   # the worker polls with its own secret: the pasted code dies
                return self._next(self._jbody())
            m = JOB_RE.match(path)
            if not m:
                return self._err(404, "not found")
            jid, what, name = m.group(1), m.group(2), urllib.parse.unquote(m.group(3) or "")
            if what == "in" and verb == "GET":
                return self._input(jid, name)
            if what == "event" and verb == "POST":
                wid = self._wid()
                r = store.event(jid, wid, self._jbody())
                store.touch_worker(wid, state="job")
                return self._json(200, r)
            if what == "out" and verb == "PUT":
                off = int((q.get("offset") or ["0"])[0])
                n = store.write_chunk(jid, self._wid(), name, off, self._body(MAX_PIECE))
                return self._json(200, {"ok": True, "size": n})
            if what == "done" and verb == "POST":
                wid = self._wid()
                j = store.finish(jid, wid, self._jbody())
                store.touch_worker(wid, state="idle")
                return self._json(200, {"ok": True, "state": j["state"]})
            return self._err(405, "method not allowed")
        except (SlopError, proto.ManifestError, ValueError) as e:
            return self._err(400, str(e))
        except (BrokenPipeError, ConnectionResetError):
            return None

    def _next(self, b: dict) -> None:
        wid = self._wid()
        info = b.get("info") or {}
        gpu_ok = bool(b.get("gpu_ok"))
        why = str(b.get("why") or "")[:600] or None
        t_end = time.monotonic() + LONG_POLL_S
        last_beat = 0.0
        while True:
            if store.check_code(self._bearer()) != "worker":     # first: a revoked worker leaves no heartbeat
                self._refused()
                return self._err(401, "pairing revoked")
            if time.monotonic() - last_beat > 5:
                store.save_worker(wid, info, state="idle" if gpu_ok else "gpu-busy", gpu_ok=gpu_ok, why=why)
                last_beat = time.monotonic()
            j = store.next_job(wid, gpu_ok, why)
            if j:
                return self._json(200, {"job": store.manifest(j)})
            if time.monotonic() > t_end:
                return self._json(200, {"job": None})
            time.sleep(0.5)

    def _input(self, jid: str, name: str) -> None:
        j = store.get(jid)
        if j["state"] not in proto.ACTIVE or j.get("worker_id") != self._wid():
            return self._err(409, "job is not running on this worker")
        proto.safe_name(name)
        p = store.job_dir(jid) / "in" / name
        if not any(f["name"] == name for f in j.get("inputs") or []) or not p.is_file():
            return self._err(404, "no such input")
        size = p.stat().st_size
        a, b = 0, size - 1
        rng = self.headers.get("Range")
        code = 200
        if rng:
            m = re.match(r"^bytes=(\d+)-(\d*)$", rng.strip())
            if not m:
                return self._err(416, "bad range")
            a = int(m.group(1))
            b = min(size - 1, int(m.group(2))) if m.group(2) else size - 1
            if a > b and size:
                return self._err(416, "range outside the file")
            code = 206
        if b - a + 1 > MAX_PIECE:
            b = a + MAX_PIECE - 1
            code = 206
        with open(p, "rb") as f:
            f.seek(a)
            data = f.read(max(0, b - a + 1))
        extra = {"Accept-Ranges": "bytes"}
        if code == 206:
            extra["Content-Range"] = f"bytes {a}-{b}/{size}"
        self._send(code, data, "application/octet-stream", extra)


def _code() -> str:
    from .worker import code_hash
    return code_hash(Path(__file__).resolve().parent)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(port: int, host: str = "127.0.0.1") -> Server:
    return Server((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="slop-gpu-server")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)
    srv = serve(a.port, a.host)
    print(json.dumps({"listening": f"{a.host}:{a.port}", "pid": os.getpid()}), flush=True)
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
