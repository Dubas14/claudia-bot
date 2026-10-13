"""`slop fetch` tests against a local HTTP server (Drive's confirm step emulated). No internet, no spend."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from slop import cli, fetch
from slop.config import SlopError

ROOT = Path(__file__).resolve().parents[1]
SONG = bytes(range(256)) * 1200  # 307200 bytes
SONG_SHA = hashlib.sha256(SONG).hexdigest()
DRIVE_FILE = b"RIFF....WAVEfmt drive bytes" * 5000


class Handler(BaseHTTPRequestHandler):
    log: list[str] = []

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        Handler.log.append(self.path)
        if u.path == "/files/song.wav":
            return self._send(200, SONG, "audio/wav", {"Content-Disposition": 'attachment; filename="song.wav"'})
        if u.path == "/files/other.wav":
            return self._send(200, SONG[::-1], "audio/wav", {"Content-Disposition": 'attachment; filename="song.wav"'})
        if u.path == "/page":
            return self._send(200, b"<html><head><title>Sign in</title></head><body>Sign in to continue</body></html>",
                              "text/html; charset=utf-8")
        if u.path == "/disguised.bin":
            return self._send(200, b"<!DOCTYPE html>\n<html><body>not the file</body></html>", "application/octet-stream")
        if u.path == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(5 * 1024 * 1024))
            self.end_headers()
            return
        if u.path == "/lyrics.txt":
            return self._send(200, b"line one\nline two\n", "text/plain")
        if u.path == "/drive/download":
            if q.get("id") == "PRIVATEFILE123":
                return self._send(200, b"<html><title>Google Drive - Sign in</title>Sign in</html>", "text/html")
            if q.get("id") == "QUOTAFILE12345":
                return self._send(200, b"<html><title>Google Drive</title>Too many users have viewed or downloaded "
                                       b"this file recently. Quota exceeded</html>", "text/html")
            if q.get("confirm") == "t" and q.get("uuid") == "u-123":
                return self._send(200, DRIVE_FILE, "application/octet-stream",
                                  {"Content-Disposition": "attachment; filename=\"x.wav\"; "
                                                          "filename*=UTF-8''my%20song.wav"})
            action = f"http://127.0.0.1:{self.server.server_address[1]}/drive/download"
            page = (f'<html><head><title>Google Drive - Virus scan warning</title></head><body>'
                    f'<form id="download-form" action="{action}" method="get">'
                    f'<input type="submit" id="uc-download-link" value="Download anyway"/>'
                    f'<input type="hidden" name="id" value="{q.get("id")}">'
                    f'<input type="hidden" name="export" value="download">'
                    f'<input type="hidden" name="confirm" value="t">'
                    f'<input type="hidden" name="uuid" value="u-123"></form></body></html>').encode()
            return self._send(200, page, "text/html; charset=utf-8")
        return self._send(404, b"nope", "text/plain")


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch, server):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    for v in ("SLOP_PROJECT", "SLOP_PROGRESS_FILE", "SLOP_MODULES"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "MODULES", ["slop.core_cli", "slop.job", "slop.fetch"])
    monkeypatch.setattr(fetch, "DRIVE_DOWNLOAD", f"{server}/drive/download")
    Handler.log.clear()
    return tmp_path


def run(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main(["--json", *argv])
    out = capsys.readouterr().out.strip().splitlines()
    return rc, json.loads(out[-1])


# ---------------------------------------------------------------- link kinds
@pytest.mark.parametrize("url", [
    "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp_qr-st/view?usp=sharing",
    "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp_qr-st",
    "https://drive.google.com/uc?id=1AbCdEfGhIjKlMnOp_qr-st&export=download",
    "https://docs.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp_qr-st",
    "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp_qr-st&export=download&confirm=t",
])
def test_drive_links_become_the_direct_download(url):
    kind, dl = fetch.classify(url)
    assert kind == "drive" and dl.endswith("/drive/download?id=1AbCdEfGhIjKlMnOp_qr-st&export=download")


@pytest.mark.parametrize("url, needle", [
    ("https://drive.google.com/drive/folders/1AbCdEfGhIjKl?usp=sharing", "FOLDER"),
    ("https://docs.google.com/document/d/1AbCdEfGhIjKl/edit", "Docs/Sheets/Slides"),
    ("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKl/edit", "Docs/Sheets/Slides"),
    ("ftp://example.com/song.wav", "not a web link"),
    ("song.wav", "not a web link"),
])
def test_links_that_cannot_be_a_file_are_refused(url, needle):
    with pytest.raises(SlopError, match=needle):
        fetch.classify(url)


def test_dropbox_gets_dl_1_and_keeps_the_key():
    kind, dl = fetch.classify("https://www.dropbox.com/scl/fi/abc123/song.wav?rlkey=k3y&st=x1&dl=0")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(dl).query)
    assert kind == "dropbox" and q["dl"] == ["1"] and q["rlkey"] == ["k3y"] and q["st"] == ["x1"]
    kind, dl = fetch.classify("https://dropbox.com/s/abc/song.wav")
    assert dl.endswith("dl=1")
    assert fetch.classify("https://example.com/a.wav") == ("http", "https://example.com/a.wav")


def test_drive_confirm_url_forms():
    page = ('<form id="download-form" action="https://drive.usercontent.google.com/download" method="get">'
            '<input type="hidden" name="id" value="ID1"><input type="hidden" name="confirm" value="t">'
            '<input type="hidden" name="uuid" value="U"></form>')
    u = fetch.drive_confirm_url(page, "https://drive.usercontent.google.com/download?id=ID1")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query))
    assert q == {"id": "ID1", "confirm": "t", "uuid": "U"}
    old = '<a id="uc-download-link" href="/uc?export=download&amp;confirm=AbC1&amp;id=ID2">Download anyway</a>'
    u = fetch.drive_confirm_url(old, "https://drive.google.com/uc?export=download&id=ID2")
    assert u == "https://drive.google.com/uc?export=download&confirm=AbC1&id=ID2"
    assert fetch.drive_confirm_url("<html>Sign in</html>", "https://x/download?id=1") is None
    assert fetch.looks_html(b"  <!DOCTYPE html><html>") and not fetch.looks_html(b"RIFF\x00\x00WAVE")


# ---------------------------------------------------------------- downloads
def test_plain_download_reports_size_and_sha256_and_is_idempotent(server, env, capsys):
    rc, out = run(capsys, "fetch", f"{server}/files/song.wav", "--to", "inbox")
    assert rc == 0 and out["status"] == "saved" and out["bytes"] == len(SONG) and out["sha256"] == SONG_SHA
    f = env / "inbox" / "song.wav"
    assert Path(out["file"]) == f.resolve() and f.read_bytes() == SONG and not list((env / "inbox").glob("*.part"))
    assert "sha256 " + SONG_SHA in out["text"] and "song ingest" in out["next"]
    rc, out = run(capsys, "fetch", f"{server}/files/song.wav", "--to", "inbox")
    assert rc == 0 and out["status"] == "unchanged" and "already there" in out["text"]
    rc, out = run(capsys, "fetch", f"{server}/files/other.wav", "--to", "inbox")  # same name, other content
    assert rc == 0 and out["status"] == "saved-as-new-name" and out["name"] == "song-2.wav"
    assert f.read_bytes() == SONG  # never overwritten without --force
    rc, out = run(capsys, "fetch", f"{server}/files/other.wav", "--to", "inbox", "--force")
    assert out["status"] == "replaced" and f.read_bytes() == SONG[::-1]
    rc, out = run(capsys, "fetch", f"{server}/files/song.wav", "--to", "inbox", "--name", "take 2.wav",
                  "--sha256", SONG_SHA.upper())
    assert rc == 0 and (env / "inbox" / "take 2.wav").read_bytes() == SONG
    rc, out = run(capsys, "fetch", f"{server}/files/song.wav", "--to", "inbox", "--name", "x.wav", "--sha256", "0" * 64)
    assert rc == 1 and "sha256 mismatch" in out["error"] and not (env / "inbox" / "x.wav").exists()
    rc, out = run(capsys, "fetch", f"{server}/lyrics.txt", "--to", "inbox")
    assert rc == 0 and out["name"] == "lyrics.txt"  # plain text is a file, not a web page


@pytest.mark.parametrize("path, needle", [("/page", "web page ('Sign in')"), ("/disguised.bin", "not the file"),
                                          ("/missing.wav", "HTTP 404")])
def test_web_pages_and_errors_are_refused(server, env, capsys, path, needle):
    rc, out = run(capsys, "fetch", f"{server}{path}", "--to", "inbox")
    assert rc == 1 and needle in out["error"], out
    assert not (env / "inbox").exists() or not list((env / "inbox").iterdir())


def test_size_limit(server, env, capsys):
    rc, out = run(capsys, "fetch", f"{server}/big", "--to", "inbox", "--max-mb", "1")
    assert rc == 1 and "over --max-mb 1" in out["error"]


def test_drive_big_file_confirm_step(server, env, capsys):
    rc, out = run(capsys, "fetch", "https://drive.google.com/file/d/BIGFILE1234567/view?usp=sharing", "--to", "dl")
    assert rc == 0 and out["source"] == "drive" and out["name"] == "my song.wav"
    assert (env / "dl" / "my song.wav").read_bytes() == DRIVE_FILE
    assert out["sha256"] == hashlib.sha256(DRIVE_FILE).hexdigest()
    reqs = [r for r in Handler.log if r.startswith("/drive/download")]
    assert len(reqs) == 2 and "confirm=t" in reqs[1] and "uuid=u-123" in reqs[1]


@pytest.mark.parametrize("fid, needle", [("PRIVATEFILE123", "not shared publicly"), ("QUOTAFILE12345", "quota")])
def test_drive_refusals_say_what_to_do(server, env, capsys, fid, needle):
    rc, out = run(capsys, "fetch", f"https://drive.google.com/file/d/{fid}/view", "--to", "dl")
    assert rc == 1 and needle in out["error"], out


def test_relative_dir_is_inside_the_project_and_progress_is_written(server, env, capsys, monkeypatch):
    rc, out = run(capsys, "new", "fp")
    p = Path(out["project"])
    pf = env / "prog.json"
    monkeypatch.setenv("SLOP_PROGRESS_FILE", str(pf))
    rc, out = run(capsys, "-p", "fp", "fetch", f"{server}/files/song.wav", "--to", "audio")
    assert rc == 0 and Path(out["file"]) == (p / "audio" / "song.wav").resolve()
    assert out["next"] == f"slop --project fp song ingest {out['file']}"
    prog = json.loads(pf.read_text())
    assert prog["done"] == prog["total"] == len(SONG)


def test_next_hint_survives_spaces_and_brackets(server, env, capsys):
    rc, out = run(capsys, "new", "f1")
    rc, out = run(capsys, "-p", "f1", "fetch", f"{server}/files/song.wav", "--to", "audio", "--name",
                  "My Song (final).wav")
    assert rc == 0 and out["name"] == "My Song (final).wav"
    import shlex
    words = shlex.split(out["next"])  # pasted into bash: one argument, no syntax error at "("
    assert words == ["slop", "--project", "f1", "song", "ingest", out["file"]]
    assert f"next: {out['next']}" in out["text"]


def test_fetch_is_registered_and_free():
    ap = cli.build_parser()
    sub = next(a for a in ap._actions if a.__class__.__name__ == "_SubParsersAction")
    assert "fetch" in sub.choices and "job" in sub.choices and "next" in sub.choices
    src = (ROOT / "slop" / "fetch.py").read_text(encoding="utf-8")
    assert "check_budget" not in src and "ledger" not in src  # downloads are free: never a paid call
    assert os.environ.get("SLOP_PROGRESS_FILE") is None
