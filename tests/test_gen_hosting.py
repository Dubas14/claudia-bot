"""HTTPS hosting: the token-path share server, the quick-tunnel manager (fake cloudflared), clip hosting + re-hosting."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop.cli import main  # noqa: E402
from slop.gen import clips, hosting, serve, store  # noqa: E402


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def test_share_server_serves_only_the_token_path(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"RIFF....data")
    (tmp_path / "sub").mkdir(); (tmp_path / "sub" / "x.wav").write_bytes(b"no")
    srv = serve.serve(tmp_path, "tok123", 0)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True); th.start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert get(f"{base}/tok123/a.wav") == (200, b"RIFF....data")
        assert get(f"{base}/wrong/a.wav")[0] == 404
        assert get(f"{base}/tok123/")[0] == 404
        assert get(f"{base}/tok123/sub/x.wav")[0] == 404
        assert get(f"{base}/tok123/..%2Fa.wav")[0] == 404
        assert get(f"{base}/tok123/missing.wav")[0] == 404
        assert get(f"{base}/a.wav")[0] == 404
    finally:
        srv.shutdown(); srv.server_close()


def test_check_https():
    assert hosting.check_https("https://x.example/a.wav") == "https://x.example/a.wav"
    with pytest.raises(Exception, match="HTTPS"):
        hosting.check_https("http://x.example/a.wav")


@pytest.mark.skipif(os.name == "nt", reason="the fake cloudflared is a POSIX shell script")
def test_tunnel_start_publish_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    fake = tmp_path / "cloudflared"
    fake.write_text("#!/bin/sh\necho 'INF Requesting new quick Tunnel on trycloudflare.com...' >&2\nsleep 0.3\n"
                    "echo 'INF |  https://brave-tiny-words-here.trycloudflare.com   |' >&2\nexec sleep 60\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SLOP_CLOUDFLARED", str(fake))
    st = hosting.start(wait_s=10)
    try:
        assert st["running"] and st["url"] == "https://brave-tiny-words-here.trycloudflare.com"
        f = tmp_path / "w.wav"; f.write_bytes(b"RIFFdata")
        url = hosting.publish(f, "proj__W01.wav")
        state = hosting.read_state()
        assert url == f"{st['url']}/{state['token']}/proj__W01.wav"
        assert hosting.url_is_live_tunnel(url)
        assert not hosting.url_is_live_tunnel("https://old-host.trycloudflare.com/x/y.wav")
        # the local share server answers on the token path
        code, body = get(f"http://127.0.0.1:{state['port']}/{state['token']}/proj__W01.wav")
        for _ in range(30):
            if code == 200:
                break
            import time; time.sleep(.1)
            code, body = get(f"http://127.0.0.1:{state['port']}/{state['token']}/proj__W01.wav")
        assert code == 200 and body == b"RIFFdata"
        assert hosting.start()["reused"] is True
    finally:
        out = hosting.stop()
    assert out["stopped"] and not hosting.status()["running"]


def test_missing_cloudflared_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_CLOUDFLARED", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(Exception, match="bin/setup.sh"):
        hosting.cloudflared_bin()


@pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
def test_stale_tunnel_url_is_rehosted_at_submit(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    H.write_cache(tmp_path / "home")
    pdir = H.make_project(tmp_path / "projects")
    clips.new(pdir, "s002", "sung")
    c = store.load(pdir, "W01")
    c["window"]["url"] = "https://old-host.trycloudflare.com/tok/x.wav"; store.save(pdir, c)
    monkeypatch.setattr(hosting, "status", lambda: {"running": True, "url": "https://new-host.trycloudflare.com"})
    monkeypatch.setattr(hosting, "publish", lambda path, name=None: f"https://new-host.trycloudflare.com/tok/{name}")
    url, notes = clips.resolve_audio_url(pdir, c)
    assert url.startswith("https://new-host.trycloudflare.com/") and notes
    monkeypatch.setattr(hosting, "status", lambda: {"running": False, "url": None})
    c["window"]["url"] = "https://old-host.trycloudflare.com/tok/x.wav"
    with pytest.raises(Exception, match="slop gen tunnel start"):
        clips.resolve_audio_url(pdir, c)


def test_tunnel_status_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert main(["--json", "gen", "tunnel", "status"]) == 0
    assert json.loads(buf.getvalue())["running"] is False


def test_tunnel_url_comes_from_the_banner_only():
    fail = ('2026-10-01T10:00:00Z ERR Error unmarshaling QuickTunnel response: error="Post '
            '\\"https://api.trycloudflare.com/tunnel\\": dial tcp 104.16.230.132:443: i/o timeout"\n')
    assert hosting.tunnel_url(fail) is None
    ok = ("INF Requesting new quick Tunnel on trycloudflare.com...\n"
          "INF +--------------------------------------------------------------------------------------------+\n"
          "INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |\n"
          "INF |  https://brave-tiny-words-here.trycloudflare.com                                           |\n")
    assert hosting.tunnel_url(fail + ok) == "https://brave-tiny-words-here.trycloudflare.com"


@pytest.mark.skipif(os.name == "nt", reason="the fake cloudflared is a POSIX shell script")
def test_tunnel_start_fails_when_cloudflare_is_unreachable(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    fake = tmp_path / "cloudflared"
    fake.write_text("#!/bin/sh\necho 'INF Requesting new quick Tunnel on trycloudflare.com...' >&2\n"
                    "echo 'ERR Error unmarshaling QuickTunnel response: error=\"Post \\\"https://api.trycloudflare.com/tunnel"
                    "\\\": dial tcp: i/o timeout\"' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SLOP_CLOUDFLARED", str(fake))
    with pytest.raises(Exception, match="did not come up") as e:
        hosting.start(wait_s=5)
    assert "api.trycloudflare.com" in str(e.value)                       # the log tail is shown, not taken as the URL
    assert not hosting.status()["running"] and not hosting.read_state()


@pytest.mark.skipif(os.name == "nt", reason="the fake cloudflared is a POSIX shell script")
def test_tunnel_that_dies_after_the_banner_is_not_up(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    fake = tmp_path / "cloudflared"
    fake.write_text("#!/bin/sh\necho 'INF |  https://brave-tiny-words-here.trycloudflare.com   |' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SLOP_CLOUDFLARED", str(fake))
    with pytest.raises(Exception, match="did not come up"):
        hosting.start(wait_s=5)


@pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
def test_window_changed_after_hosting(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    H.write_cache(tmp_path / "home")
    pdir = H.make_project(tmp_path / "projects")
    clips.new(pdir, "s002", "sung")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert main(["--json", "--project", str(pdir), "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav"]) == 0
    c = store.load(pdir, "W01")
    assert c["hosted"]["audio"]["sha1"] and clips.resolve_audio_url(pdir, c)[0] == "https://cdn.example.com/W01.wav"
    (pdir / c["window"]["wav"]).write_bytes((pdir / c["window"]["wav"]).read_bytes() + b"\0\0")  # re-cut behind slop's back
    with pytest.raises(Exception, match="changed after it was hosted"):
        clips.resolve_audio_url(pdir, store.load(pdir, "W01"))
    # on a live tunnel the changed window is simply re-published
    c = store.load(pdir, "W01")
    c["window"]["url"] = "https://new-host.trycloudflare.com/tok/x.wav"; store.save(pdir, c)
    monkeypatch.setattr(hosting, "url_is_live_tunnel", lambda u: True)
    monkeypatch.setattr(hosting, "status", lambda: {"running": True, "url": "https://new-host.trycloudflare.com"})
    monkeypatch.setattr(hosting, "publish", lambda path, name=None: f"https://new-host.trycloudflare.com/tok2/{name}")
    url, notes = clips.resolve_audio_url(pdir, c)
    assert "/tok2/" in url and "changed" in notes[0]
