"""OpenRouter client: headers, retries (429/5xx yes, 4xx never, non-idempotent submits not on 5xx), error mapping."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop.config import SlopError  # noqa: E402
from slop.gen.openrouter import OpenRouter, ProviderError, classify, data_url, decode_data_url  # noqa: E402

KEY = "sk-or-v1-test-not-a-real-key"


def client(routes, **kw):
    sleeps = []
    c = OpenRouter(key=KEY, session=H.FakeSession(routes), sleep=sleeps.append, **kw)
    return c, sleeps


def test_headers_and_json():
    c, _ = client({("GET", "/key"): H.FakeResp(200, {"data": {"usage": 1.5}})})
    assert c.get("/key")["data"]["usage"] == 1.5
    h = c.session.calls[0]["headers"]
    assert h["Authorization"] == f"Bearer {KEY}"
    assert h["HTTP-Referer"] == "claudia" and h["X-Title"] == "claudia" and h["User-Agent"].startswith("claudia/")
    assert c.session.calls[0]["url"] == "https://openrouter.ai/api/v1/key"


def test_free_listing_sends_no_key():
    c, _ = client({("GET", "/videos/models"): H.FakeResp(200, {"data": []})})
    c.get("/videos/models", auth=False)
    assert "Authorization" not in c.session.calls[0]["headers"]


def test_retries_429_and_5xx_with_backoff_and_retry_after():
    c, sleeps = client({("GET", "/x"): [H.FakeResp(429, {"error": {"message": "slow down"}}, headers={"Retry-After": "3"}),
                                        H.FakeResp(502, {"error": {"message": "bad gateway"}}),
                                        H.FakeResp(200, {"ok": 1})]})
    assert c.get("/x") == {"ok": 1}
    assert sleeps == [3.0, 4.0]                                         # Retry-After wins, then 2 * 2**1


def test_4xx_is_never_retried():
    c, sleeps = client({("POST", "/images"): [H.FakeResp(400, {"error": {"message": "bad aspect_ratio"}}), H.FakeResp(200, {})]})
    with pytest.raises(ProviderError) as e:
        c.post("/images", {"model": "m"})
    assert e.value.status == "bad_request" and len(c.session.calls) == 1 and not sleeps


def test_retries_give_up():
    c, sleeps = client({("GET", "/x"): H.FakeResp(503, {"error": {"message": "overloaded"}})}, retries=2)
    with pytest.raises(ProviderError) as e:
        c.get("/x")
    assert e.value.status == "server" and len(c.session.calls) == 3 and len(sleeps) == 2


def test_video_submit_is_not_reposted_on_5xx():
    c, sleeps = client({("POST", "/videos"): [H.FakeResp(502, {"error": {"message": "upstream"}}), H.FakeResp(202, {"id": "x"})]})
    with pytest.raises(ProviderError) as e:
        c.post("/videos", {"model": "m"}, retry_5xx=False)
    assert e.value.status == "unknown_outcome" and "Do NOT re-run" in str(e.value) and len(c.session.calls) == 1


def _raise(exc):
    def f(method, url, body):
        raise exc
    return f


def test_paid_post_is_not_resent_after_a_timeout():
    import requests
    c, sleeps = client({("POST", "/images"): _raise(requests.ReadTimeout("read timed out"))})
    with pytest.raises(ProviderError) as e:
        c.post("/images", {"model": "m"}, retry_network=False)
    assert e.value.status == "unknown_outcome" and len(c.session.calls) == 1 and not sleeps
    assert "openrouter.ai/activity" in str(e.value)
    # a connection that was never established is safe to re-send
    n = {"k": 0}

    def flaky(method, url, body):
        n["k"] += 1
        if n["k"] == 1:
            raise requests.ConnectTimeout("connect timed out")
        return H.FakeResp(200, {"data": []})
    c, sleeps = client({("POST", "/images"): flaky})
    assert c.post("/images", {"model": "m"}, retry_network=False) == {"data": []} and len(sleeps) == 1
    # GETs are always retried after a dropped connection
    m = {"k": 0}

    def reset_once(method, url, body):
        m["k"] += 1
        if m["k"] == 1:
            raise requests.ConnectionError("Connection aborted: RemoteDisconnected")
        return H.FakeResp(200, {"ok": 1})
    c, sleeps = client({("GET", "/x"): reset_once})
    assert c.get("/x") == {"ok": 1} and len(sleeps) == 1


def test_broken_stream_is_an_unknown_outcome():
    import requests

    class Broken(H.FakeResp):
        def iter_lines(self):
            yield b'data: {"choices":[{"delta":{"audio":{"data":"AAAA"}}}]}'
            raise requests.exceptions.ChunkedEncodingError("connection broken")
    c, _ = client({("POST", "/chat/completions"): Broken(200, content=b"")})
    with pytest.raises(ProviderError) as e:
        list(c.sse("/chat/completions", {"stream": True}, retry_network=False))
    assert e.value.status == "unknown_outcome"


def test_face_decline_advice_names_the_working_sequence():
    from slop.gen.openrouter import ADVICE
    assert "slop clip set CLIP --provider higgsfield && slop clip lock CLIP && slop clip submit CLIP --yes" in ADVICE["declined_face"]


@pytest.mark.parametrize("code,msg,status", [
    (402, "Insufficient credits", "credits"),
    (403, "Key limit exceeded", "key_limit"),
    (401, "No auth credentials found", "auth"),
    (400, "InputImageSensitiveContentDetected.PrivacyInformation: real person", "declined_face"),
    (400, "InputTextSensitiveContentDetected", "declined_text"),
    (400, "Invalid reference URL: input_references[0].audio_url.url: Only HTTPS URLs are allowed", "bad_request"),
    (403, "Your input was flagged by moderation", "moderation"),
    (404, "Model not found", "not_found"),
])
def test_error_mapping(code, msg, status):
    c, _ = client({("POST", "/videos"): H.FakeResp(code, {"error": {"code": code, "message": msg}})})
    with pytest.raises(ProviderError) as e:
        c.post("/videos", {"model": "m"})
    assert e.value.status == status and e.value.http == code
    assert KEY not in str(e.value)                                     # the key is never printed
    assert isinstance(e.value, SlopError)


def test_job_error_classes():
    assert classify(None, "The request failed because the output audio may be related to copyright restrictions") == "copyright"
    assert classify(None, "the output audio may contain sensitive information") == "sensitive"
    assert classify(None, "") == "error"


def test_metadata_raw_is_included():
    c, _ = client({("POST", "/videos"): H.FakeResp(400, {"error": {"message": "Provider returned error",
                                                                   "metadata": {"raw": "PrivacyInformation"}}})})
    with pytest.raises(ProviderError) as e:
        c.post("/videos", {})
    assert e.value.status == "declined_face"


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    c = OpenRouter(session=H.FakeSession({}))
    with pytest.raises(SlopError, match="OPENROUTER_API_KEY is not set"):
        c.get("/key")


def test_sse_stream():
    lines = [b": OPENROUTER PROCESSING", b'data: {"choices":[{"delta":{"content":"hi"}}]}', b"",
             b'data: {"choices":[{"delta":{"content":" there"}}]}', b"data: [DONE]"]
    c, _ = client({("POST", "/chat/completions"): H.FakeResp(200, content=b"", lines=lines)})
    evs = list(c.sse("/chat/completions", {"stream": True}))
    assert [e["choices"][0]["delta"]["content"] for e in evs] == ["hi", " there"]


def test_data_urls(tmp_path):
    p = H.write_png(tmp_path / "a.png")
    u = data_url(p)
    raw, mime = decode_data_url(u)
    assert mime == "image/png" and raw == p.read_bytes()
    big = tmp_path / "big.png"
    from PIL import Image
    import numpy as np
    Image.fromarray((np.random.default_rng(0).random((1400, 3000, 3)) * 255).astype("uint8")).save(big)
    assert big.stat().st_size > 3_000_000
    raw2, mime2 = decode_data_url(data_url(big))
    assert mime2 == "image/jpeg" and len(raw2) < big.stat().st_size
    with Image.open(__import__("io").BytesIO(raw2)) as im:
        assert im.width == 2400
