"""Lyria via OpenRouter (streamed audio chunks) — mocked; never called for real in tests."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import song  # noqa: E402

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects", audio=False)


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def sse_lines(mp3: bytes, chunk: int = 4000) -> list[bytes]:
    b = H.b64(mp3)
    out = [b": OPENROUTER PROCESSING"]
    out.append(b'data: ' + json.dumps({"choices": [{"delta": {"content": "[Verse 1] Sit up"}}]}).encode())
    for i in range(0, len(b), chunk):
        out.append(b"data: " + json.dumps({"choices": [{"delta": {"audio": {"data": b[i:i + chunk]}}}]}).encode())
    out.append(b"data: " + json.dumps({"choices": [], "usage": {"cost": .08}}).encode())
    out.append(b"data: [DONE]")
    return out


def test_body_shape():
    b = song.build_body("google/lyria-3-pro-preview", "Electroclash, 128 BPM. Lyrics: [Verse 1] ...")
    assert b["modalities"] == ["text", "audio"] and b["audio"] == {"format": "mp3"} and b["stream"] is True
    assert b["messages"][0]["role"] == "user"


def test_song_needs_yes(env):
    p = env / "prompt.txt"; p.write_text("Electroclash, 128 BPM.")
    rc, out = run(env, "gen", "song", "--prompt-file", str(p))
    assert rc == 1 and "$0.08" in out["error"] and "--yes" in out["error"]


def test_song_stream_to_master(env, tmp_path, monkeypatch):
    wav = H.write_wav(tmp_path / "t.wav", H.vocal_track(duration=2.0, words=[("a", 0, .2, 1.5)]))
    mp3 = tmp_path / "t.mp3"
    subprocess.run([H.FFMPEG, "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(mp3)], check=True)
    s = H.FakeSession({("POST", "/chat/completions"): H.FakeResp(200, content=b"", lines=sse_lines(mp3.read_bytes()))})
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    p = env / "prompt.txt"; p.write_text("Electroclash, 128 BPM, one female lead. Lyrics: [Verse 1] Sit up")
    rc, out = run(env, "gen", "song", "--prompt-file", str(p), "--yes", "--as-song")
    assert rc == 0, out
    assert s.calls[0]["body"]["model"] == "google/lyria-3-pro-preview"
    assert Path(out["mp3"]).read_bytes() == mp3.read_bytes()
    assert Path(out["text_file"]).read_text() == "[Verse 1] Sit up"
    import wave
    with wave.open(out["song"]) as w:
        assert w.getnchannels() == 2 and w.getframerate() == 44100
    assert ledger.rows(env)[-1]["kind"] == "song" and ledger.spent_usd(env) == pytest.approx(.08)


def test_song_without_audio_explains(env, monkeypatch):
    s = H.FakeSession({("POST", "/chat/completions"): H.FakeResp(200, content=b"", lines=[
        b"data: " + json.dumps({"choices": [{"delta": {"content": "I can't generate that."}}]}).encode(), b"data: [DONE]"])})
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    rc, out = run(env, "gen", "song", "--prompt", "a song like a famous artist", "--yes", "--clip")
    assert rc == 1 and "no audio" in out["error"] and s.calls[0]["body"]["model"] == "google/lyria-3-clip-preview"
    assert ledger.spent_usd(env) == 0
