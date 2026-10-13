"""slop.taste.server: routes under the token, security headers, limits; the detached manager; the tunnel (faked)."""
import io
import json
import os
import stat
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.taste import fonts as F  # noqa: E402
from slop.taste import server as SV  # noqa: E402
from slop.taste.embed import embed_pool  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402

TOKEN = "tok_" + "x" * 20


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    S.write_images(tmp_path / "refs", {"grey": 6, "red": 4, "colour": 4})
    add_dir(PoolWriter(p), tmp_path / "refs")
    embed_pool(p, embedder=S.FakeEmbedder(), log=lambda m: None)
    (p / "lyrics" / "lyrics.txt").write_text("hold still now\nopen circuit tonight\n", encoding="utf-8")
    return p


@pytest.fixture
def live(proj, tmp_path, monkeypatch):
    d = tmp_path / "fonts"
    d.mkdir()
    for fn, fam in [("Geist-Regular.ttf", "Geist"), ("DINish-Bold.ttf", "DINish"), ("IBMPlexMono-Regular.ttf", "IBM Plex Mono")]:
        S.fake_font(d / fn, fam)
    monkeypatch.setattr(F, "font_dirs", lambda extra=None: [d])
    F.setup(proj, seed=1)
    app = SV.App(proj, TOKEN, embed=False, background=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SV.make_handler(app))
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", app
    httpd.shutdown()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def req(url, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    r = urllib.request.Request(url, data=data, headers={"content-type": "application/json"} if data is not None else {})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(r, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_token_gate_pages_and_headers(live):
    base, app = live
    assert req(base + "/")[0] == 404
    assert req(base + "/wrong-token/")[0] == 404
    st, h, _ = req(base + f"/{TOKEN}")
    assert st == 302 and h["Location"] == f"/{TOKEN}/"
    st, h, body = req(base + f"/{TOKEN}/")
    assert st == 200 and b"static/feed.js" in body
    assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in h["Content-Security-Policy"]
    assert req(base + f"/{TOKEN}/static/feed.js")[1]["Content-Type"].startswith("text/javascript")
    assert req(base + f"/{TOKEN}/static/../server.py")[0] == 404
    assert json.loads(req(base + f"/{TOKEN}/api/health")[2]) == {"ok": True, "app": "slop-taste"}


def test_tap_pair_undo_flow(live, proj):
    base, app = live
    st, _, b = req(base + f"/{TOKEN}/api/next", {"exclude": []})
    j = json.loads(b)
    assert st == 200 and j["cards"] and j["meter"]["target"] == 150
    c = j["cards"][0]
    st, _, img = req(base + f"/{TOKEN}/{c['img']}")
    assert st == 200 and Image.open(io.BytesIO(img)).format == "JPEG"
    st, _, b = req(base + f"/{TOKEN}/api/tap", {"item": c["item"], "action": "like", "dwell_ms": 900, "why": c["why"]})
    t = json.loads(b)
    assert st == 200 and t["meter"]["likes"] == 1
    ids = list(load_pool(proj))
    st, _, b = req(base + f"/{TOKEN}/api/pair", {"a": ids[1], "b": ids[2], "winner": "b", "shown": "ba", "layout": "row"})
    assert st == 200 and json.loads(b)["meter"]["pairs"] == 1
    st, _, b = req(base + f"/{TOKEN}/api/undo", {"eid": t["undo"]["eid"]})
    assert json.loads(b)["meter"]["likes"] == 0
    assert req(base + f"/{TOKEN}/api/tap", {"item": "nope", "action": "like"})[0] == 400
    assert req(base + f"/{TOKEN}/api/next", raw=b"{not json")[0] == 400
    assert req(base + f"/{TOKEN}/api/next", raw=b"x" * (SV.BODY_MAX + 1))[0] == 413
    assert req(base + f"/{TOKEN}/img/../../project.json")[0] == 404
    rows = [json.loads(x) for x in (proj / "taste" / "taps.jsonl").read_text().splitlines()]
    assert rows[1]["shown"] == "ba" and rows[1]["layout"] == "row" and "undo" in rows[2]
    assert json.loads(req(base + f"/{TOKEN}/api/liked")[2]) == []


def test_fonts_page_and_assets(live, proj):
    base, app = live
    st, _, body = req(base + f"/{TOKEN}/fonts")
    assert st == 200 and b"static/fonts.js" in body
    j = json.loads(req(base + f"/{TOKEN}/api/fonts/next", {"exclude": []})[2])
    c = j["cards"][0]
    assert j["progress"]["cards"] == 6 and c["line"] in ("hold still now", "open circuit tonight")
    st, h, fb = req(base + f"/{TOKEN}/font/{c['first']['file']}")
    assert st == 200 and h["Content-Type"] == "font/ttf" and fb[:4] == b"\x00\x01\x00\x00"
    assert req(base + f"/{TOKEN}/font/secret.ttf")[0] == 404
    assert req(base + f"/{TOKEN}/frame.jpg")[0] == 200
    st, _, b = req(base + f"/{TOKEN}/api/fonts/pick", {"card": c["card"], "winner": "second", "layout": "stack"})
    p = json.loads(b)
    assert st == 200 and p["progress"]["answered"] == 1 and p["progress"]["first_slot_wins"] == 0
    assert req(base + f"/{TOKEN}/api/fonts/pick", {"card": c["card"], "winner": "left"})[0] == 400
    req(base + f"/{TOKEN}/api/fonts/undo", {"eid": p["undo"]["eid"]})
    assert json.loads(req(base + f"/{TOKEN}/api/fonts/progress")[2])["answered"] == 0


def test_post_rate_limit(live, monkeypatch):
    base, app = live
    monkeypatch.setattr(SV, "POSTS_PER_MIN", 3)
    codes = [req(base + f"/{TOKEN}/api/undo", {"eid": ""})[0] for _ in range(4)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_manager_serve_is_idempotent_then_stops(proj):
    r = SV.serve(proj, embed=False)
    try:
        assert r["running"] and not r["reused"] and r["urls"]["local"].endswith("/")
        st, _, _ = req(r["urls"]["local"] + "api/health")
        assert st == 200
        r2 = SV.serve(proj, embed=False)
        assert r2["reused"] and r2["urls"]["local"] == r["urls"]["local"]
        assert SV.status(proj)["running"] is True
    finally:
        out = SV.stop(proj)
    assert "server" in out["stopped"] and SV.status(proj)["running"] is False


@pytest.mark.skipif(os.name == "nt", reason="the fake cloudflared is a POSIX shell script")
def test_tunnel_with_fake_cloudflared(proj, tmp_path):
    b = tmp_path / "home" / "bin"
    b.mkdir(parents=True, exist_ok=True)
    fake = b / "cloudflared"
    fake.write_text("#!/bin/sh\necho 'INF | Your quick Tunnel has been created! Visit it at:'\n"
                    "echo 'INF |  https://brave-otter-fun-test.trycloudflare.com  |'\nexec sleep 30\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    r = SV.serve(proj, tunnel=True, embed=False)
    try:
        assert r["urls"]["public"].startswith("https://brave-otter-fun-test.trycloudflare.com/")
        assert r["urls"]["public"].endswith("/") and r["urls"]["fonts_public"].endswith("/fonts")
        assert "trycloudflare" in r["text"]
        assert SV.status(proj)["tunnel"] is True
    finally:
        out = SV.stop(proj)
    assert set(out["stopped"]) == {"server", "tunnel"}


def test_fonts_trailing_slash_redirects(live):
    base, app = live
    st, h, _ = req(base + f"/{TOKEN}/fonts/")
    assert st == 302 and h["Location"] == f"/{TOKEN}/fonts"            # relative assets would 404 under /fonts/
    assert req(base + f"/{TOKEN}/fonts")[0] == 200


def test_failed_tunnel_leaves_a_stoppable_server(proj, monkeypatch):
    from slop.config import SlopError
    from slop.taste import tunnel as T

    def no_tunnel(*a, **k):
        raise SlopError("cloudflared not found in $SLOP_HOME/bin or on PATH: run bin/setup.sh")
    monkeypatch.setattr(T, "start", no_tunnel)
    r = SV.serve(proj, tunnel=True, embed=False)
    try:
        assert r["running"] and "tunnel_error" in r and "public" not in r["urls"]
        assert "NO PUBLIC LINK" in r["text"] and "cloudflared" in r["text"]
        st = SV.status(proj)
        assert st["running"] is True and st["tunnel"] is False          # status sees the server it started
        r2 = SV.serve(proj, tunnel=True, embed=False)                    # a retry reuses it (no second orphan)
        assert r2["reused"] and r2["pid"] == r["pid"] and "tunnel_error" in r2
    finally:
        out = SV.stop(proj)
    assert out["stopped"] == ["server"] and SV.status(proj)["running"] is False
    assert not T.pid_alive(r["pid"])
