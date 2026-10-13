"""Song generation with Google Lyria through OpenRouter (the Quick-tier fallback when the user has no Suno song).

Model ids come from /api/v1/models (listed 2026-10-01: google/lyria-3-pro-preview — full song, about 2–3 min, $0.08 per
song; google/lyria-3-clip-preview — 30 s, $0.04). The list price shows 0; the per-song price is in the description, so
the ledger counts max(usage.cost, $0.08 / $0.04) — a returned cost of 0 may only mirror the unpriced listing — and keeps
the real figure in units.real_usd (no real Lyria stream has been recorded yet; compare with /api/v1/key: slop spend).
Request (chat completions; audio output requires streaming):
  {"model", "messages":[{"role":"user","content": PROMPT}], "modalities":["text","audio"], "audio":{"format":"mp3"},
   "stream": true}
The audio arrives as base64 chunks in choices[0].delta.audio.data (concatenated, then decoded); text (lyrics / structure)
in delta.content or delta.audio.transcript. Output: audio/lyria-<n>.mp3 + lyrics/lyria-<n>.txt, and with --as-song the
44.1 kHz stereo master audio/song.wav (ARCHITECTURE §3.2).
Prompt: lead with the primary genre, instruments, BPM, key, mood; one lead voice; delivery in prose; no negative field
(write "No rap, no …" in prose); then "Lyrics:" with [Intro]/[Verse 1]/[Chorus] tags. No artist names or real people
(blocked); results vary per call (budget 3–5 tries per keeper). Licence: Google does not claim ownership of the output
but gives no explicit commercial grant — tell the user. All Lyria audio carries a SynthID watermark.
A timeout / broken stream after the request was sent is not re-sent (it may be billed): ledgered at the estimate with
note unknown_outcome; check https://openrouter.ai/activity before re-running.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

from .. import ledger
from ..config import SlopError
from . import models as reg
from .openrouter import OpenRouter, ProviderError


def build_body(model: str, prompt: str, fmt: str = "mp3", seed: int | None = None) -> dict:
    if not prompt or not prompt.strip():
        raise SlopError("empty song prompt: write it to a file and pass --prompt-file FILE")
    b = {"model": model, "messages": [{"role": "user", "content": prompt.strip()}],
         "modalities": ["text", "audio"], "audio": {"format": fmt}, "stream": True}
    if seed is not None:
        b["seed"] = int(seed)
    return b


def b64_chunks(chunks: list[str]) -> bytes:
    """decode streamed base64 audio chunks. Each SSE chunk may be its OWN base64 string with its own '=' padding
    (OpenAI-style audio deltas): decoding the plain concatenation stops silently at the first padding and keeps only the
    first chunk. So the joined text is decoded one padded segment at a time (a segment ends with the 4-character group
    that holds '='); a chunk may also carry a data: URL head, which is dropped."""
    parts = []
    for c in chunks:
        c = "".join(str(c).split())
        if c.startswith("data:") and "," in c:
            c = c.split(",", 1)[1]
        parts.append(c)
    s = "".join(parts)
    out = bytearray()
    i = 0
    while i < len(s):
        j = s.find("=", i)
        if j < 0:
            seg, i = s[i:], len(s)
        else:
            k = i + ((j - i) // 4 + 1) * 4                       # the end of the 4-character group holding the '='
            seg, i = s[i:k], k
            while i < len(s) and s[i] == "=":                    # stray extra padding
                i += 1
        seg = seg.rstrip("=")
        if seg:
            out += base64.b64decode(seg + "=" * (-len(seg) % 4))
    return bytes(out)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):                                 # content parts: [{"type": "text", "text": …}]
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def collect(events) -> tuple[bytes, str, dict]:
    """(audio bytes, text, usage) from the SSE event stream (choices[].delta.audio.data base64 chunks +
    delta.audio.transcript / delta.content text; a final message.audio in the same shape is read too)."""
    chunks, text, usage = [], [], {}
    for ev in events:
        if ev.get("usage"):
            usage = ev["usage"]
        for ch in ev.get("choices") or []:
            d = ch.get("delta") or ch.get("message") or {}
            a = d.get("audio") or {}
            if a.get("data"):
                chunks.append(a["data"])
            if a.get("transcript"):
                text.append(a["transcript"])
            t = _text_of(d.get("content"))
            if t:
                text.append(t)
    raw = b64_chunks(chunks) if chunks else b""
    return raw, "".join(text), usage


def ledger_usd(model: str, real, est: float) -> float:
    """what the ledger counts for one song. Lyria is listed at price 0 (the per-song price is only in the model's
    description), so a usage.cost of 0 (or below the listed per-song price) may be the unpriced listing, not the bill:
    the ledger keeps the larger of the two, so check_budget never under-counts; the real figure stays in units.real_usd
    (`slop spend` compares the ledger with OpenRouter's /key usage)."""
    if real is None:
        return est
    if model in reg.LYRIA or "lyria" in model:
        return max(float(real), est)
    return float(real)


def next_n(d: Path, stem: str) -> int:
    ks = [int(p.stem.split("-")[-1]) for p in d.glob(f"{stem}-*.*") if p.stem.split("-")[-1].isdigit()]
    return max(ks, default=0) + 1


def generate(pdir: Path, prompt: str, *, kind: str = "pro", model: str | None = None, yes: bool = False,
             as_song: bool = False, seed: int | None = None, client: OpenRouter | None = None) -> dict:
    model = model or reg.lyria_model(kind)
    est = reg.LYRIA.get(model, .08 if "clip" not in model else .04)
    if not yes:
        raise SlopError(f"generating a song with {model} costs about ${est:.2f}: show the prompt to the user and re-run "
                        "with --yes after they agree")
    ledger.check_budget(pdir, "openrouter", add_usd=est, yes=yes)
    client = client or OpenRouter()
    body = build_body(model, prompt, seed=seed)
    try:
        raw, text, usage = collect(client.sse("/chat/completions", body, where="song", timeout=900, retry_network=False))
    except ProviderError as e:
        if e.status == "unknown_outcome":                          # may have been billed: count it until checked
            ledger.record(pdir, provider="openrouter", model=model, kind="song", est_usd=est, units={"est_usd": est},
                          status="submitted", note="unknown_outcome: check https://openrouter.ai/activity")
            raise
        ledger.record(pdir, provider="openrouter", model=model, kind="song", est_usd=0.0, units={"est_usd": est},
                      status="declined" if e.status.startswith(("declined", "moderation")) else "failed", note=e.status)
        if e.status in ("moderation", "declined_text", "bad_request"):
            raise SlopError(str(e) + " — Lyria blocks artist names, real people and copyrighted lyrics: drop names, "
                            "reword, re-run.") from e
        raise
    if not raw:
        ledger.record(pdir, provider="openrouter", model=model, kind="song", est_usd=0.0, units={"est_usd": est},
                      status="failed", note="no audio")
        raise SlopError("Lyria returned no audio" + (f" (it said: {text[:300]})" if text else "") +
                        " — reword the prompt (no artist names or real people) and re-run")
    ad = pdir / "audio"; ad.mkdir(parents=True, exist_ok=True)
    n = next_n(ad, "lyria")
    mp3 = ad / f"lyria-{n}.mp3"; mp3.write_bytes(raw)
    ld = pdir / "lyrics"; ld.mkdir(parents=True, exist_ok=True)
    txt = ld / f"lyria-{n}.txt"; txt.write_text(text, encoding="utf-8")
    real = usage.get("cost")
    row = ledger.record(pdir, provider="openrouter", model=model, kind="song", est_usd=ledger_usd(model, real, est),
                        units={"est_usd": est, "real_usd": real}, status="ok")
    out = {"mp3": str(mp3), "text_file": str(txt), "model": model, "cost_usd": real, "est_usd": est, "ledger": row}
    if as_song:
        out["song"] = str(to_master(mp3, ad / "song.wav"))
    return out


def to_master(src: Path, dst: Path) -> Path:
    """44.1 kHz stereo 16-bit WAV master (ARCHITECTURE §3.2)."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SlopError("ffmpeg is not installed (run bin/setup.sh)")
    if dst.exists():
        dst.replace(dst.with_name(dst.stem + ".prev.wav"))
    r = subprocess.run([exe, "-v", "error", "-y", "-i", str(src), "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(dst)],
                       capture_output=True)
    if r.returncode:
        raise SlopError("ffmpeg could not convert the song: " + r.stderr.decode(errors="replace")[-300:])
    return dst
