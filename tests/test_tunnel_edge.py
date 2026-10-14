"""A quick tunnel is up only once cloudflared registered a connection with Cloudflare's edge. Cloudflare hands out a
trycloudflare.com address before that, and when the network blocks the edge's port 7844 the address answers 1033 /
HTTP 530 forever: every tunnel user (sung-clip audio, the GPU server, the tap app) must fail with the real reason, the
GPU pairing must never hand out a line for a dead address, and the fallback is named instead of a restart."""
from __future__ import annotations

import io
import json
import os
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from slop import cli
from slop.config import SlopError
from slop.gen import hosting

POSIX = pytest.mark.skipif(os.name == "nt", reason="the fake cloudflared is a POSIX shell script")

BLOCKED = ("#!/bin/sh\n"
           "echo 'INF Requesting new quick Tunnel on trycloudflare.com...' >&2\n"
           "echo 'INF |  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |' >&2\n"
           "echo 'INF |  https://toward-dead-blocked-words.trycloudflare.com  |' >&2\n"
           "echo 'ERR Failed to dial a quic connection error=\"timeout: no recent network activity\" ip=198.41.192.7' >&2\n"
           "echo 'ERR Unable to establish connection with Cloudflare edge error=\"dial tcp 198.41.192.7:7844: i/o timeout\"' >&2\n"
           "exec sleep 60\n")
GOOD = ("#!/bin/sh\n"
        "echo 'INF |  https://brave-good-words-here.trycloudflare.com  |' >&2\n"
        "sleep 0.3\n"
        "echo 'INF Registered tunnel connection connIndex=0 event=0 location=ord08 protocol=http2' >&2\n"
        "exec sleep 60\n")


def fake(tmp_path: Path, body: str, monkeypatch) -> Path:
    f = tmp_path / "cloudflared"
    f.write_text(body)
    f.chmod(0o755)
    monkeypatch.setenv("SLOP_CLOUDFLARED", str(f))
    monkeypatch.setenv("SLOP_TUNNEL_EDGE_WAIT", "1.5")
    return f


def test_http2_is_the_default_protocol(monkeypatch):
    monkeypatch.delenv("SLOP_TUNNEL_PROTOCOL", raising=False)
    argv = hosting.cloudflared_cmd("cloudflared", 8123)
    assert argv[argv.index("--protocol") + 1] == "http2" and argv[-2:] == ["--url", "http://127.0.0.1:8123"]
    monkeypatch.setenv("SLOP_TUNNEL_PROTOCOL", "auto")
    assert "--protocol" not in hosting.cloudflared_cmd("cloudflared", 8123)
    monkeypatch.setenv("SLOP_TUNNEL_PROTOCOL", "quic")
    argv = hosting.cloudflared_cmd("cloudflared", 8123)
    assert argv[argv.index("--protocol") + 1] == "quic"


def test_the_blocked_message_names_port_7844_and_the_1033_address():
    msg = hosting.blocked_msg("ERR dial tcp 198.41.192.7:7844: i/o timeout", 30)
    assert "7844" in msg and "1033" in msg and "restarting does not help" in msg


@POSIX
def test_sung_clip_hosting_refuses_a_tunnel_that_never_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    fake(tmp_path, BLOCKED, monkeypatch)
    monkeypatch.setattr(hosting, "origin_answers", lambda url, timeout=8.0: False)
    t0 = time.monotonic()
    with pytest.raises(SlopError) as e:
        hosting.start(wait_s=10)
    msg = str(e.value)
    assert "never registered" in msg and "7844" in msg and "Higgsfield" in msg
    assert time.monotonic() - t0 < 20
    assert hosting.status()["running"] is False and not hosting.state_file().exists(), "nothing left running"


@POSIX
def test_sung_clip_hosting_comes_up_once_registered(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    fake(tmp_path, GOOD, monkeypatch)
    st = hosting.start(wait_s=10)
    try:
        assert st["running"] and st["url"] == "https://brave-good-words-here.trycloudflare.com"
    finally:
        hosting.stop()


@POSIX
def test_the_gpu_server_tunnel_refuses_and_names_direct_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    fake(tmp_path, BLOCKED, monkeypatch)
    from slop.gpu import service
    monkeypatch.setattr(service, "public_health", lambda url, wait_s=30.0: (False, "HTTP Error 530"))
    with pytest.raises(SlopError) as e:
        service._start_tunnel(8123, 10)
    msg = str(e.value)
    assert "never registered" in msg and "7844" in msg and "slop gpu direct-plan" in msg and "No pairing line" in msg


@POSIX
def test_the_tap_app_tunnel_refuses_a_tunnel_that_never_registered(tmp_path, monkeypatch):
    fake(tmp_path, BLOCKED, monkeypatch)
    from slop.taste import tunnel as T
    monkeypatch.setattr(hosting, "origin_answers", lambda url, timeout=8.0: False)
    with pytest.raises(SlopError) as e:
        T.start(8123, tmp_path / "tunnel.log", binary=tmp_path / "cloudflared", timeout=10)
    assert "never registered" in str(e.value) and "7844" in str(e.value)


def test_gpu_pair_makes_no_line_for_an_address_that_does_not_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    from slop.gpu import service, store
    monkeypatch.setattr(service, "status", lambda: {"server": True, "tunnel": True, "port": 8123, "started": "x",
                                                    "url": "https://toward-dead-blocked-words.trycloudflare.com",
                                                    "local_url": "http://127.0.0.1:8123"})
    monkeypatch.setattr(service, "public_health", lambda url, wait_s=30.0: (False, "HTTP Error 530"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["--json", "gpu", "pair"])
    out = json.loads(buf.getvalue())
    assert rc != 0 and not out["ok"]
    assert "no pairing line" in out["error"] and "slop gpu direct-plan" in out["error"] and "530" in out["error"]
    assert not store.has_code(), "no one-time code was made for a dead address"
