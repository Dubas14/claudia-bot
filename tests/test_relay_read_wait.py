"""`relay read --wait` holds its full time unless there is something for Grok (0.2.9): a blip in the production's
state or a misread never ends it early; a production that really stopped does, within about 2 s."""
from __future__ import annotations

import time

from slop import relay

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K


def _ready(tmp_path, monkeypatch):
    RT.setup(tmp_path, monkeypatch)
    assert K.run("relay", "setup")[0] == 0


def test_a_blip_in_the_state_does_not_end_the_wait(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    calls = {"n": 0}

    def prod(rd):
        calls["n"] += 1
        return {"state": "idle" if calls["n"] == 3 else "working", "summary": "working"}
    monkeypatch.setattr(relay, "production", prod)
    t0 = time.monotonic()
    rc, r = K.run("relay", "read", "--wait", "3")
    assert rc == 0 and r["items"] == [] and time.monotonic() - t0 >= 2.8, (r, time.monotonic() - t0)


def test_a_production_that_stopped_ends_the_wait_soon(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(relay, "production", lambda rd: {"state": "waiting", "summary": "waiting"})
    t0 = time.monotonic()
    rc, r = K.run("relay", "read", "--wait", "30")
    assert rc == 0 and 1.5 <= time.monotonic() - t0 < 6, time.monotonic() - t0


def test_a_misread_keeps_waiting(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    monkeypatch.setattr(relay, "production", lambda rd: {"state": "working", "summary": "working"})
    real, seen = relay._snapshot, {"n": 0}

    def snap(rd):
        new, prod, q, sig = real(rd)
        seen["n"] += 1
        return ([{"id": 99, "kind": "say"}] if seen["n"] == 1 else new), prod, q, sig   # a torn read, once
    monkeypatch.setattr(relay, "_snapshot", snap)
    t0 = time.monotonic()
    rc, r = K.run("relay", "read", "--wait", "3")
    assert rc == 0 and r["items"] == [] and time.monotonic() - t0 >= 2.8


def test_new_items_still_end_the_wait_at_once(tmp_path, monkeypatch):
    _ready(tmp_path, monkeypatch)
    K.run("relay", "send", "hello")
    items, r = RT.collect(lambda it, r: any("heard #1" in i["text"] for i in it))
    assert r["waited_s"] < 30
