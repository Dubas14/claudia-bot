"""Tiny static server for the quick tunnel: serves ONLY GET/HEAD /<token>/<filename> from one directory.

No listing, no subdirectories, no path traversal, nothing outside the token prefix (404). Binds 127.0.0.1 (cloudflared
connects locally). Run: python -m slop.gen.serve --dir DIR --token TOKEN --port PORT
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,200}$")


def make_handler(root: Path, token: str):
    root = root.resolve()

    class H(BaseHTTPRequestHandler):
        server_version = "claudia-share"
        sys_version = ""

        def _resolve(self) -> Path | None:
            path = self.path.split("?", 1)[0]
            parts = path.strip("/").split("/")
            if len(parts) != 2 or parts[0] != token or not NAME_RE.match(parts[1]) or ".." in parts[1]:
                return None
            p = (root / parts[1]).resolve()
            if p.parent != root or not p.is_file():
                return None
            return p

        def _send(self, body: bool):
            p = self._resolve()
            if p is None:
                self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            size = p.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if body:
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(1 << 16)
                        if not chunk:
                            break
                        self.wfile.write(chunk)

        def do_GET(self):  # noqa: N802
            self._send(True)

        def do_HEAD(self):  # noqa: N802
            self._send(False)

        def do_POST(self):  # noqa: N802
            self.send_response(405); self.send_header("Content-Length", "0"); self.end_headers()

        do_PUT = do_DELETE = do_POST  # noqa: N815

        def log_message(self, fmt, *args):
            if os.environ.get("SLOP_SHARE_LOG"):
                super().log_message(fmt, *args)

    return H


def serve(root: Path, token: str, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(Path(root), token))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="slop-share")
    ap.add_argument("--dir", required=True); ap.add_argument("--token", required=True)
    ap.add_argument("--port", type=int, required=True); ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)
    srv = serve(Path(a.dir), a.token, a.port, a.host)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
