"""Whisper fallback via OpenRouter - all HTTP mocked (no paid calls): window planning, request shape, ledger, cache,
error messages, and the merge into words.json."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "audio"))

import synth  # noqa: E402

from slop.audio import whisper as wh  # noqa: E402
from slop.config import SlopError  # noqa: E402


def test_plan_windows_cover_vocals_and_stay_short():
    fps = 100
    R = np.zeros(200 * fps, np.float32)
    for a in range(10, 190, 7):                    # 3 s phrases every 7 s
        R[a * fps:(a + 3) * fps] = 0.5
    wins = wh.plan_windows(R)
    assert wins and all(b - a <= wh.MAX_WIN + 1e-6 for a, b in wins)
    assert wins[0][0] <= 10.0 and wins[-1][1] >= 186.0
    for (a0, b0), (a1, b1) in zip(wins, wins[1:]):
        assert b0 == pytest.approx(a1)            # contiguous: no audio skipped inside the vocal span
    # cuts land in silence where possible
    for a, b in wins[:-1]:
        assert R[int(b * fps)] < 0.06
    assert wh.plan_windows(np.zeros(1000, np.float32)) == []


def test_windows_stay_under_whisper_context():
    assert wh.MAX_WIN == 26.0                      # the original's < 30 s windows (no long-form chunking)


def test_estimate_and_price():
    assert wh.estimate_usd([(0, 100)], "openai/whisper-large-v3") == pytest.approx(0.00075)
    assert wh.estimate_usd([(0, 10), (10, 20)], "openai/whisper-large-v3-turbo") == pytest.approx(20 * 0.00000333, rel=1e-3)


def test_price_unknown_models_from_the_free_listing():
    listing = [{"id": "qwen/qwen3-asr-1.7b", "prompt": 0.0000075, "completion": 0.0},
               {"id": "microsoft/mai-transcribe-1.5", "prompt": 0.36, "completion": 0.0},
               {"id": "openai/gpt-4o-transcribe", "prompt": 0.0000025, "completion": 0.00001}]
    assert wh.price_per_s("openai/whisper-large-v3", lister=lambda: 1 / 0) == 0.0000075     # vetted: no listing call
    assert wh.price_per_s("qwen/qwen3-asr-1.7b", lister=lambda: listing) == 0.0000075
    with pytest.raises(SlopError, match="not a per-second"):
        wh.price_per_s("microsoft/mai-transcribe-1.5", lister=lambda: listing)          # other units: refused
    with pytest.raises(SlopError, match="not a per-second"):
        wh.price_per_s("openai/gpt-4o-transcribe", lister=lambda: listing)              # token priced: refused
    with pytest.raises(SlopError, match="not an OpenRouter transcription model"):
        wh.price_per_s("acme/nope", lister=lambda: listing)
    with pytest.raises(SlopError, match="did not load"):
        wh.price_per_s("acme/nope", lister=lambda: 1 / 0)
    assert wh.price_per_s("acme/nope", override=0.00002) == 0.00002                     # the owner's declaration


def test_parse_words_offsets_and_segments_fallback():
    d = {"text": "hi there", "words": [{"word": " hi", "start": 0.5, "end": 0.7, "confidence": 0.9},
                                        {"word": "there", "start": 0.8, "end": None}]}
    out = wh.parse_words(d, 10.0, 2)
    assert out[0] == {"w": "hi", "t0": 10.5, "t1": 10.7, "win": 2, "conf": 0.9}
    assert out[1]["t1"] == pytest.approx(11.1)
    d2 = {"segments": [{"words": [{"word": "yo", "start": 1.0, "end": 1.2}]}]}
    assert wh.parse_words(d2, 0.0, 0)[0]["w"] == "yo"


@pytest.fixture()
def wproj(tmp_path, monkeypatch):
    song = synth.make_song(dur=12.0, drop_at=6.0, vocal_phrases=[(1.0, 4.0), (7.0, 10.0)])
    root = synth.write_project(tmp_path / "wh", song)
    pj = json.loads((root / "project.json").read_text())
    pj["budget"] = {"openrouter_usd": 5, "confirm_over_usd": 2}
    (root / "project.json").write_text(json.dumps(pj))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    return root


def test_transcribe_posts_ledgers_and_caches(wproj):
    calls = []

    def post(payload, key):
        calls.append(payload)
        assert key == "sk-or-test-not-a-real-key"
        assert payload["response_format"] == "verbose_json" and payload["timestamp_granularities"] == ["word"]
        assert payload["input_audio"]["format"] == "wav"
        raw = base64.b64decode(payload["input_audio"]["data"])
        assert raw[:4] == b"RIFF"
        return {"text": "la la", "words": [{"word": "la", "start": 0.2, "end": 0.5}], "usage": {"cost": 0.00001},
                "_request_id": f"req-{len(calls)}"}

    wins = [(0.0, 5.0), (5.0, 11.0)]
    out = wh.transcribe(wproj, wins, post=post)
    assert len(calls) == 2 and not out["cached"]
    assert [w["t0"] for w in out["words"]] == [0.2, 5.2]
    rows = [json.loads(x) for x in (wproj / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and all(r["provider"] == "openrouter" and r["kind"] == "stt" for r in rows)
    assert rows[0]["request_id"] == "req-1" and rows[0]["status"] == "ok" and rows[0]["units"]["seconds"] == 5.0
    assert out["cost_usd"] == pytest.approx(0.00002)       # (the ledger rounds est_usd to 4 decimals ...)
    assert rows[0]["units"]["usd"] == pytest.approx(0.00001)        # (... so the exact cost rides in units.usd)
    again = wh.transcribe(wproj, wins, post=post)                   # a re-run never pays twice
    assert again["cached"] and len(calls) == 2 and again["cost_usd"] == 0 and again["cost_total_usd"] == pytest.approx(2e-5)
    found = wh.find_cached(wh.Paths(wproj))
    assert found and found["model"] == wh.DEFAULT_MODEL and [w["t0"] for w in found["words"]] == [0.2, 5.2]


def test_transcribe_resumes_after_a_failed_window(wproj):
    calls = []

    def flaky(payload, key):
        calls.append(1)
        if len(calls) == 2:
            raise SlopError("OpenRouter transcription kept failing (HTTP 503)")
        return {"text": "la", "words": [{"word": "la", "start": 0.1, "end": 0.3}], "usage": {"cost": 0.00001}}

    wins = [(0.0, 4.0), (4.0, 8.0), (8.0, 11.0)]
    with pytest.raises(SlopError, match="503"):
        wh.transcribe(wproj, wins, post=flaky)
    assert len(calls) == 2
    assert wh.find_cached(wh.Paths(wproj)) is None                 # incomplete: not reused as a full transcription
    out = wh.transcribe(wproj, wins, post=flaky)                    # window 1 is cached: only windows 2 and 3 are sent
    assert len(calls) == 4 and out["cached_windows"] == 1 and out["cost_usd"] == pytest.approx(0.00002)
    assert [w["win"] for w in out["words"]] == [0, 1, 2]
    rows = [json.loads(x) for x in (wproj / "ledger.jsonl").read_text().splitlines()]
    assert [r["status"] for r in rows] == ["ok", "failed", "ok", "ok"]


def test_transcribe_without_key_or_over_budget(wproj, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(SlopError, match="OPENROUTER_API_KEY"):
        wh.transcribe(wproj, [(0.0, 5.0)], post=lambda p, k: {})
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    pj = json.loads((wproj / "project.json").read_text())
    pj["budget"] = {"openrouter_usd": 0.0000001}
    (wproj / "project.json").write_text(json.dumps(pj))
    with pytest.raises(SlopError, match="budget"):
        wh.transcribe(wproj, [(0.0, 5.0)], model="openai/whisper-1", post=lambda p, k: {})


def test_text_without_word_times_is_an_error(wproj):
    with pytest.raises(SlopError, match="word timestamps"):
        wh.transcribe(wproj, [(0.0, 3.0)], post=lambda p, k: {"text": "hello there"})


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.headers = code, body, {"x-request-id": "abc"}
        self.text = json.dumps(body) if isinstance(body, dict) else str(body)

    def json(self):
        if isinstance(self._body, dict):
            return self._body
        raise ValueError("not json")


@pytest.mark.parametrize("code,match", [(401, "rejected"), (402, "credits"), (400, "refused")])
def test_post_error_messages(monkeypatch, code, match):
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(code, {"error": {"message": "x"}}))
    with pytest.raises(SlopError, match=match):
        wh._post({"model": "m"}, "k")


def test_post_retries_then_succeeds(monkeypatch):
    import requests
    seq = [_Resp(503, "busy"), _Resp(200, {"text": "ok", "words": []})]
    monkeypatch.setattr(requests, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(wh.time, "sleep", lambda s: None)
    d = wh._post({"model": "m"}, "k")
    assert d["text"] == "ok" and d["_request_id"] == "abc"


def test_fallback_end_to_end_merges_whisper_words(wproj, monkeypatch):
    """analyze --steps align --whisper-fallback with fake emissions (all low confidence) + a mocked transcription."""
    import io
    from contextlib import redirect_stdout

    from slop.audio import align as al
    from slop.cli import main
    from test_audio_align import VOCAB, fake_emissions
    (wproj / "lyrics").mkdir()
    (wproj / "lyrics" / "lyrics.txt").write_text("sing it loud\n", encoding="utf-8")
    E = fake_emissions([("sing", 1.0, 1.4), ("it", 1.5, 1.6), ("loud", 1.7, 2.4)], 12.0, hi=0.3)
    monkeypatch.setattr(al, "compute_emissions", lambda v: (E, dict(VOCAB)))
    monkeypatch.setattr(wh, "_post", lambda payload, key: {
        "text": "sing it loud", "usage": {"cost": 0.00002},
        "words": [{"word": "Sing", "start": 0.95, "end": 1.3}, {"word": "it", "start": 1.45, "end": 1.6},
                  {"word": "loud!", "start": 1.65, "end": 2.5}]})
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", "-p", str(wproj), "analyze", "--steps", "align", "--whisper-fallback"])
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert rc == 0, out
    W = json.loads((wproj / "analysis" / "words.json").read_text())
    assert {w["src"] for w in W["words"]} == {"whisper"}
    assert W["whisper"]["model"] == wh.DEFAULT_MODEL and W["whisper"]["words"] >= 3
    assert (wproj / "ledger.jsonl").exists()


def test_whisper_timing_is_kept_by_later_plain_runs(wproj, monkeypatch):
    """--whisper-fallback once; plain re-runs reuse the cached transcription for free; --no-whisper drops it."""
    import io
    from contextlib import redirect_stdout

    from slop.audio import align as al
    from slop.cli import main
    from test_audio_align import VOCAB, fake_emissions

    def run(*extra):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["--json", "-p", str(wproj), "analyze", "--steps", "align", *extra])
        return rc, json.loads(buf.getvalue().strip().splitlines()[-1])

    (wproj / "lyrics").mkdir()
    (wproj / "lyrics" / "lyrics.txt").write_text("sing it loud\n", encoding="utf-8")
    E = fake_emissions([("sing", 1.0, 1.4), ("it", 1.5, 1.6), ("loud", 1.7, 2.4)], 12.0, hi=0.3)
    monkeypatch.setattr(al, "compute_emissions", lambda v: (E, dict(VOCAB)))
    calls = []

    def post(payload, key):
        calls.append(1)
        return {"text": "sing it loud", "usage": {"cost": 0.00002},
                "words": [{"word": "Sing", "start": 0.55, "end": 0.9}, {"word": "it", "start": 1.05, "end": 1.2},
                          {"word": "loud!", "start": 1.25, "end": 2.0}]}

    monkeypatch.setattr(wh, "_post", post)
    rc, out = run("--whisper-fallback")
    assert rc == 0, out
    paid = len(calls)
    W1 = json.loads((wproj / "analysis" / "words.json").read_text())
    assert {w["src"] for w in W1["words"]} == {"whisper"} and W1["whisper"]["paid_this_run"] > 0
    monkeypatch.delenv("OPENROUTER_API_KEY")                       # a plain run never needs (or spends) the key
    rc, out = run()
    assert rc == 0, out
    assert out["steps"]["align"]["status"] == "up-to-date"         # nothing changed: same words, Whisper kept
    rc, out = run("--force")
    assert rc == 0, out
    W2 = json.loads((wproj / "analysis" / "words.json").read_text())
    assert [(w["src"], w["t0"]) for w in W2["words"]] == [(w["src"], w["t0"]) for w in W1["words"]]
    assert W2["whisper"]["paid_this_run"] == 0 and len(calls) == paid
    rc, out = run("--no-whisper")
    assert rc == 0, out
    W3 = json.loads((wproj / "analysis" / "words.json").read_text())
    assert {w["src"] for w in W3["words"]} == {"w2v"} and "whisper" not in W3
    rc, out = run()                                                 # --no-whisper sticks for plain runs
    assert rc == 0 and out["steps"]["align"]["status"] == "up-to-date"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    rc, out = run("--whisper-fallback")                             # back on: the cache fits, so it is free
    assert rc == 0, out
    W4 = json.loads((wproj / "analysis" / "words.json").read_text())
    assert {w["src"] for w in W4["words"]} == {"whisper"} and len(calls) == paid and W4["whisper"]["paid_this_run"] == 0
    monkeypatch.delenv("OPENROUTER_API_KEY")
    # new vocal stem: the old transcription no longer fits; a plain run says so and does not pay
    from slop.audio.common import load_mono, write_audio
    v = load_mono(wproj / "audio" / "stems" / "vocals.wav", 44100)
    write_audio(wproj / "audio" / "stems" / "vocals.wav", v * 0.9, 44100, codec="pcm_f32le")
    rc, out = run()
    assert rc == 0, out
    assert any("Whisper re-timing" in n and "--whisper-fallback" in n for n in out["notes"]), out["notes"]
    assert len(calls) == paid
    W5 = json.loads((wproj / "analysis" / "words.json").read_text())
    assert {w["src"] for w in W5["words"]} == {"w2v"}
