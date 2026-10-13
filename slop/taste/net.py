"""Tiny stdlib HTTP helpers (one place for tests to mock; no `requests` dependency).

`http_get` / `http_post_json` return (status, headers{lower-case}, body bytes) and never raise on HTTP errors,
only on network failure (urllib.error.URLError / OSError) — callers turn those into SlopError with a next step.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

USER_AGENT = "claudia-taste/0.1 (+personal taste profile; reads only the user's own sources)"


def http_get(url: str, headers: dict | None = None, timeout: float = 30.0) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body


def http_post_json(url: str, payload: dict, headers: dict | None = None,
                   timeout: float = 120.0) -> tuple[int, dict, bytes]:
    data = json.dumps(payload).encode("utf-8")
    h = {"User-Agent": USER_AGENT, "Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, body
