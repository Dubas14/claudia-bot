"""Whisper word timestamps through OpenRouter (the sung-line fallback for low-confidence wav2vec2 words).

Replaces the GPU whisper_words script (openai/whisper-large-v3 on CUDA, 18.5 GiB on CPU) with the same model behind
OpenRouter's speech-to-text endpoint:
  POST https://openrouter.ai/api/v1/audio/transcriptions
  {"model", "input_audio": {"data": <base64 wav>, "format": "wav"}, "language": "en",
   "response_format": "verbose_json", "timestamp_granularities": ["word"]}
  -> {"text", "words": [{"word", "start", "end", "confidence"?}], "segments": [...], "usage": {"cost", "seconds"}}
Windows: <= 26 s of the vocal stem, as the original (it kept every window under Whisper's native 30 s context - no
long-form chunking, which degrades word timestamps - and well under the providers' 60 s request timeout; pricing is per
second, so shorter windows cost the same). Each window ends at the quietest 0.2 s in its last third, and only the
vocal-active part of the song is sent.
Spend: openai/whisper-large-v3 is $0.0000075 per audio second (~$0.002 for a 5-minute song). The estimate is checked
against the project budget before any request; models outside the vetted list are priced from OpenRouter's free model
listing when it gives a per-second price, else refused (or priced by project.json audio.whisper_usd_per_s, the owner's
declaration). Every request is written to the project ledger (provider openrouter, kind stt; the exact cost is in
units.usd because the ledger rounds est_usd to 4 decimals). Results are cached PER WINDOW as they arrive
(analysis/cache/whisper-<model>.json, keyed on the vocal stem), so a re-run - even after a failure half-way - never
pays twice for a window; `slop analyze` reuses a cached transcription for free on later runs (find_cached).
Licence: Whisper large-v3 weights Apache-2.0 (run by the provider).
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import numpy as np

from slop.config import SlopError, require_env

from .common import Paths, fingerprint, load_mono, read_json, run_ffmpeg, write_json

URL = "https://openrouter.ai/api/v1/audio/transcriptions"
MODELS_URL = "https://openrouter.ai/api/v1/models?output_modalities=transcription"
DEFAULT_MODEL = "openai/whisper-large-v3"
# vetted: per-second prices from OpenRouter's listing (2026-10-01) and OpenAI-style word timestamps
PRICE_PER_S = {"openai/whisper-large-v3": 0.0000075, "openai/whisper-large-v3-turbo": 0.00000333,
               "openai/whisper-1": 0.0001}
MAX_WIN = 26.0


def vocal_env(vocals: Path, sr: int = 22050, hop_s: float = 0.01) -> np.ndarray:
    """RMS of the vocal stem in 10 ms hops, normalised to max 1 (the align-merge energy envelope)."""
    v = load_mono(vocals, sr)
    hop = int(sr * hop_s)
    n = len(v) // hop
    if n == 0:
        return np.zeros(0, np.float32)
    R = np.sqrt((v[: n * hop].reshape(n, hop) ** 2).mean(1))
    return (R / (R.max() + 1e-12)).astype(np.float32)


def plan_windows(R: np.ndarray, fps: float = 100.0, max_len: float = MAX_WIN, thr: float = 0.06,
                 pad: float = 0.4, min_len: float = 1.0) -> list[tuple[float, float]]:
    """Windows over the vocal-active part of the song, each <= max_len s, cut at the quietest 0.2 s inside the last
    third of each window so a word is rarely split."""
    if not len(R):
        return []
    act = np.where(R > thr)[0]
    if not len(act):
        return []
    dur = len(R) / fps
    a, end = max(0.0, act[0] / fps - pad), min(dur, act[-1] / fps + pad)
    sm = np.convolve(R, np.ones(20) / 20, mode="same")
    out = []
    while end - a > 1e-6:
        if end - a <= max_len:
            b = end
        else:
            lo, hi = int((a + max_len * 2 / 3) * fps), int((a + max_len) * fps)
            seg = sm[lo:hi]
            b = (lo + int(np.argmin(seg))) / fps if len(seg) else a + max_len
        if b - a >= min_len and R[int(a * fps):int(b * fps)].max(initial=0) > thr:
            out.append((round(a, 2), round(b, 2)))
        a = b
    return out


def price_per_s(model: str, override: float | None = None, lister=None) -> float:
    """USD per audio second for `model`: the owner's override (project.json audio.whisper_usd_per_s), the vetted table,
    or OpenRouter's free model listing when its price is clearly per second (prompt > 0, <= $0.001, no completion
    price). Anything else is refused: a wrong estimate would bypass the budget and confirmation gates."""
    if override is not None:
        return float(override)
    if model in PRICE_PER_S:
        return PRICE_PER_S[model]
    vetted = ", ".join(PRICE_PER_S)
    try:
        listing = (lister or list_models)()
    except Exception as e:
        raise SlopError(f"cannot price {model}: OpenRouter's model list did not load ({type(e).__name__}). Use a vetted "
                        f"model ({vetted}) or set audio.whisper_usd_per_s in project.json.")
    m = next((x for x in listing if x["id"] == model), None)
    if m is None:
        raise SlopError(f"{model} is not an OpenRouter transcription model. Use one of: {vetted}.")
    pr, co = m.get("prompt") or 0.0, m.get("completion") or 0.0
    if co > 0 or not 0 < pr <= 0.001:
        raise SlopError(f"cannot estimate the cost of {model}: OpenRouter lists it at prompt {pr} / completion {co}, not a "
                        f"per-second audio price. Use one of: {vetted} (or set audio.whisper_usd_per_s in project.json "
                        "if the owner knows its per-second price).")
    return float(pr)


def _price(model: str) -> float:
    return PRICE_PER_S.get(model, 0.0001)


def estimate_usd(windows: list[tuple[float, float]], model: str, usd_per_s: float | None = None) -> float:
    return round(sum(b - a for a, b in windows) * (usd_per_s if usd_per_s is not None else _price(model)), 7)


def _wav_b64(vocals: Path, a: float, b: float) -> str:
    raw = run_ffmpeg(["-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(vocals), "-ac", "1", "-ar", "16000",
                      "-c:a", "pcm_s16le", "-f", "wav", "-"], what="cutting a whisper window")
    return base64.b64encode(raw).decode()


def _post(payload: dict, key: str, timeout: float = 120.0) -> dict:
    import requests
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "X-Title": "claudia"}
    last = None
    for attempt in range(3):
        try:
            r = requests.post(URL, json=payload, headers=hdr, timeout=timeout)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 200:
            try:
                d = r.json()
            except ValueError:
                raise SlopError(f"OpenRouter returned non-JSON for {payload['model']}: {r.text[:200]}")
            d.setdefault("_request_id", r.headers.get("x-request-id") or d.get("id"))
            return d
        msg = r.text[:300]
        if r.status_code == 401:
            raise SlopError("OpenRouter rejected OPENROUTER_API_KEY (401). Ask the user to re-enter it in the secure card.")
        if r.status_code == 402:
            raise SlopError("OpenRouter says the account is out of credits (402). Ask the user to top up, or re-run "
                            "`slop analyze` without --whisper-fallback (wav2vec2 times only).")
        if r.status_code == 400:
            raise SlopError(f"OpenRouter refused the transcription request (400): {msg}. Try --whisper-model "
                            "openai/whisper-large-v3-turbo, or run without --whisper-fallback.")
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}: {msg}"
            time.sleep(3 * (attempt + 1))
            continue
        raise SlopError(f"OpenRouter transcription failed (HTTP {r.status_code}): {msg}")
    raise SlopError(f"OpenRouter transcription kept failing ({last}); try again later or skip --whisper-fallback")


def parse_words(d: dict, offset: float, win: int) -> list[dict]:
    ws = d.get("words")
    if not ws:
        ws = [w for s in d.get("segments") or [] for w in (s.get("words") or [])]
    out = []
    for w in ws or []:
        txt = str(w.get("word", w.get("text", ""))).strip()
        if not txt or w.get("start") is None:
            continue
        t0 = float(w["start"])
        t1 = float(w["end"]) if w.get("end") is not None else t0 + .3
        o = {"w": txt, "t0": round(offset + t0, 3), "t1": round(offset + max(t1, t0), 3), "win": win}
        if w.get("confidence") is not None:
            o["conf"] = round(float(w["confidence"]), 3)
        out.append(o)
    return out


def _wkey(a: float, b: float) -> str:
    return f"{a:.2f}-{b:.2f}"


def cache_path(paths: Paths, model: str) -> Path:
    return paths.cache / f"whisper-{model.replace('/', '_')}.json"


def _assemble(cache: dict, windows: list) -> list[dict]:
    words = []
    for k, (a, b) in enumerate(windows):
        for w in cache["windows"][_wkey(a, b)]["words"]:
            words.append({**w, "win": k})
    return words


def _complete(cache: dict, voc_fp: str) -> bool:
    plan = cache.get("plan")
    return bool(cache.get("vocals") == voc_fp and plan is not None and
                all(_wkey(a, b) in cache.get("windows", {}) for a, b in plan))


def find_cached(paths: Paths, model: str | None = None) -> dict | None:
    """A complete cached transcription of the CURRENT vocal stem (free to reuse): the given model's, else (model None)
    the most recent of any model. -> {"model", "words", "windows", "cost_usd", "tag"} or None."""
    voc = paths.stem("vocals")
    if not voc.exists():
        return None
    fp = fingerprint(voc)
    files = [cache_path(paths, model)] if model else sorted(paths.cache.glob("whisper-*.json"))
    best = None
    for f in files:
        try:
            c = read_json(f, None)
        except SlopError:
            continue
        if not isinstance(c, dict) or not isinstance(c.get("windows"), dict) or not _complete(c, fp):
            continue
        if best is None or str(c.get("at", "")) > str(best.get("at", "")):
            best = c
    if best is None:
        return None
    plan = [tuple(w) for w in best["plan"]]
    return {"model": best["model"], "words": _assemble(best, plan), "windows": plan,
            "cost_usd": round(sum(v.get("cost_usd", 0.0) for v in best["windows"].values()), 7),
            "tag": f"{best['model']}@{best.get('at')}"}


def transcribe(pdir: Path, windows: list[tuple[float, float]] | None = None, model: str = DEFAULT_MODEL,
               yes: bool = False, force: bool = False, post=None, usd_per_s: float | None = None) -> dict:
    """Whisper words for the vocal stem -> {"words": [{w, t0, t1, win, conf?}], "windows", "cost_usd" (paid in THIS
    call), "cost_total_usd", "cached" (nothing paid), "cached_windows", "tag"}. Windows already in the cache are not
    sent again; each new window is cached the moment it arrives."""
    from slop import ledger
    paths = Paths(pdir)
    voc = paths.stem("vocals")
    if not voc.exists():
        raise SlopError("no audio/stems/vocals.wav - run `slop analyze --steps stems` first")
    if windows is None:
        windows = plan_windows(vocal_env(voc))
    windows = [(round(float(a), 2), round(float(b), 2)) for a, b in windows]
    fp = fingerprint(voc)
    cp = cache_path(paths, model)
    cache = read_json(cp, {}) or {}
    if force or cache.get("vocals") != fp or cache.get("model") != model or not isinstance(cache.get("windows"), dict):
        cache = {"model": model, "vocals": fp, "windows": {}}
    cache["plan"] = [list(w) for w in windows]
    todo = [(a, b) for a, b in windows if _wkey(a, b) not in cache["windows"]]
    n_cached = len(windows) - len(todo)
    cost = 0.0
    if todo:
        key_env = require_env("OPENROUTER_API_KEY", "needed for the Whisper fallback (about $0.002 per song)")
        rate = price_per_s(model, usd_per_s)
        est = estimate_usd(todo, model, rate)
        ledger.check_budget(pdir, "openrouter", add_usd=est, yes=yes)
        post = post or _post
        for a, b in todo:
            k = windows.index((a, b))
            payload = {"model": model, "input_audio": {"data": _wav_b64(voc, a, b), "format": "wav"}, "language": "en",
                       "response_format": "verbose_json", "timestamp_granularities": ["word"]}
            try:
                d = post(payload, key_env)
            except SlopError:
                ledger.record(pdir, provider="openrouter", model=model, kind="stt", est_usd=0.0,
                              units={"seconds": round(b - a, 2)}, status="failed", note=f"window {a}-{b}")
                raise
            usage = d.get("usage") or {}
            real = usage.get("cost")
            c = float(real) if real is not None else (b - a) * rate
            cost += c
            ledger.record(pdir, provider="openrouter", model=model, kind="stt", est_usd=round(c, 6),
                          units={"seconds": round(b - a, 2), "usd": round(c, 8)}, request_id=d.get("_request_id"),
                          status="ok", note=f"whisper window {a}-{b}")
            ws = parse_words(d, a, k)
            if not ws and (d.get("text") or "").strip():
                raise SlopError(f"{model} returned text but no word timestamps; pick a model that supports "
                                "timestamp_granularities=word (default openai/whisper-large-v3)")
            cache["windows"][_wkey(a, b)] = {"words": [{kk: v for kk, v in w.items() if kk != "win"} for w in ws],
                                              "cost_usd": round(c, 8), "request_id": d.get("_request_id"),
                                              "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            cache["at"] = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}#{len(cache['windows'])}"
            write_json(cp, cache)                               # a paid window is never lost to a later failure
    if "at" not in cache:
        cache["at"] = f"{time.strftime('%Y-%m-%dT%H:%M:%S')}#{len(cache['windows'])}"
    write_json(cp, cache)
    total = round(sum(v.get("cost_usd", 0.0) for v in cache["windows"].values()), 7)
    return {"model": model, "words": _assemble(cache, windows), "windows": windows, "cost_usd": round(cost, 7),
            "cost_total_usd": total, "cached": not todo, "cached_windows": n_cached,
            "tag": f"{model}@{cache.get('at')}"}


def list_models(timeout: float = 20.0) -> list[dict]:
    """Free call: OpenRouter's transcription models with their listed prices (USD per prompt / completion unit; for
    most speech-to-text models the prompt unit is one audio second, but not for all - see price_per_s)."""
    import requests
    r = requests.get(MODELS_URL, timeout=timeout)
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        pr = m.get("pricing") or {}
        try:
            out.append({"id": m["id"], "prompt": float(pr.get("prompt") or 0),
                        "completion": float(pr.get("completion") or 0)})
        except (TypeError, ValueError, KeyError):
            continue
    return out


def have_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
