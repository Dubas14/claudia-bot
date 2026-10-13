"""OpenRouter model registry + per-call price estimates (free listing endpoints, cached in $SLOP_HOME/cache/openrouter).

Sources (no key needed):
  GET /api/v1/videos/models                  -> video models with `pricing_skus` (the real video prices)
  GET /api/v1/images/models                  -> image models; prices per model at /api/v1/images/models/{id}/endpoints
  GET /api/v1/models?output_modalities=all   -> text / VLM / audio models (prompt / completion per-token prices)
The cache lives 24 h (`--refresh` re-fetches). Prices are ESTIMATES; real spend is the provider's `usage.cost` and
OpenRouter's /api/v1/key usage (`slop spend`).

Video pricing (pricing_skus):
  video_tokens[_<res>][_without_audio|_with_video_input]  $/token, tokens = W × H × 24 × billed seconds / 1024
      (Seedance: 2.5 = $10.7/M → 480p $0.1028/s, 720p $0.2311/s; with a video reference, input + output seconds at the
       cheaper _with_video_input rate)
      CALIBRATED on real takes (2026-10-01): Seedance renders and bills one frame more than asked —
      (round(s × 24) + 1) / 24 seconds (4 s → 4.04 s, 5 s → 5.04 s) — and the 2.0 family renders 480p as 864×496, not
      854×480. Billed: 2.0-mini 480p 4 s $0.142079 (formula $0.14208), 5 s $0.177 ($0.1772); 2.5 480p 5 s $0.518
      ($0.5183); 2.5 720p 5 s $1.16523 ($1.16523). Without this the estimates ran 1–6 % low.
  duration_seconds[_with_audio|_without_audio][_<res>], image_to_video_/text_to_video_/reference_duration_seconds_<res>
      $/s;  cents_per_second_output[_<res>], cents_per_video_output_second_<res>  ¢/s
  extras: reference_images ($/ref image), cents_per_image_input (¢/input image), minimum_cents_per_generation
Image pricing (endpoint `pricing` rows {billable, unit, cost_usd, variant?}): unit image | megapixel | token. Token-
priced outputs are estimated with a per-resolution (Google) or per-quality (OpenAI) output-token table — conservative.
"""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..config import SlopError, cache_dir

TTL = 24 * 3600
SEEDANCE_RATE = 10.7e-6                       # $/video token, bytedance/seedance-2.5 (verified 2026-10-01)
DIMS = {"360p": (640, 360), "480p": (854, 480), "540p": (960, 540), "720p": (1280, 720), "768p": (1366, 768),
        "1080p": (1920, 1080), "1k": (1920, 1080), "2k": (2560, 1440), "4k": (3840, 2160)}
OUT_DIMS = {"bytedance/seedance-2.0": {"480p": (864, 496)}}   # measured output sizes (model-id prefix -> res -> W, H)
EXTRA_FRAMES = 1                              # token-priced (Seedance) takes bill round(s × 24) + 1 frames
IMG_MP = {"512": .26, "768": .59, "1k": 1.05, "2k": 4.19, "4k": 16.78}
GOOGLE_OUT_TOKENS = {"512": 747, "768": 1000, "1k": 1120, "2k": 1680, "4k": 2520}
OPENAI_OUT_TOKENS = {"low": 130, "medium": 1800, "auto": 1800, "high": 7000, "xhigh": 9000, "max": 12000}
# low: calibrated 2026-10-01 on a real openai/gpt-image-2 low 16:9 image (1536x864) billed $0.004 = output tokens at
# $30/M + the prompt at $5/M. 130 output tokens + the prompt's own length lands within about 10 % (the old 150 + a flat
# 200-token prompt estimated $0.0055, 37 % high).
PROMPT_TOKENS = 200                           # input text tokens assumed when the prompt is not known
VLM_CALL = (1700, 300)                        # tokens in (one ~1K image + prompt) / out per judge call
TEXT_CALL = (3000, 1000)                      # a standard text call
FALLBACK = {                                  # used offline only (no cache, no network)
    "bytedance/seedance-2.5": {"video_tokens": "0.0000107", "video_tokens_without_audio": "0.0000107",
                               "video_tokens_with_video_input": "0.0000064"},
    "bytedance/seedance-2.0-mini": {"video_tokens": "0.0000035", "video_tokens_with_video_input": "0.0000021"},
}
LYRIA = {"google/lyria-3-pro-preview": 0.08, "google/lyria-3-clip-preview": 0.04}   # $ per song / per 30 s clip


# --------------------------------------------------------------------------------------------- cache + fetch
def _cache_file(name: str) -> Path:
    return cache_dir("openrouter") / f"{name}.json"


def _cached(name: str, refresh: bool, fetch, ttl: float = TTL) -> Any:
    p = _cache_file(name)
    if not refresh and p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - float(doc.get("fetched_at", 0)) < ttl:
                return doc["data"]
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            pass
    try:
        data = fetch()
    except SlopError:
        if p.is_file():                                           # stale beats nothing when offline
            try:
                return json.loads(p.read_text(encoding="utf-8"))["data"]
            except (OSError, json.JSONDecodeError, KeyError):
                pass
        raise
    p.write_text(json.dumps({"fetched_at": time.time(), "data": data}), encoding="utf-8")
    return data


def _client(client=None):
    if client is not None:
        return client
    from .openrouter import OpenRouter
    return OpenRouter(retries=1, timeout=30)                      # listings: fail fast when offline (stale cache wins)


def video_models(refresh: bool = False, client=None) -> list[dict]:
    return _cached("videos_models", refresh, lambda: _client(client).get("/videos/models", auth=False)["data"])


def chat_models(refresh: bool = False, client=None) -> list[dict]:
    return _cached("models_all", refresh,
                   lambda: _client(client).get("/models?output_modalities=all", auth=False)["data"])


def image_models(refresh: bool = False, client=None) -> list[dict]:
    """image models, each with "endpoints" (the per-provider pricing rows) merged in."""
    def fetch():
        c = _client(client)
        models = c.get("/images/models", auth=False)["data"]

        def ep(m):
            try:
                return m["id"], c.get(f"/images/models/{m['id']}/endpoints", auth=False).get("endpoints") or []
            except SlopError:
                return m["id"], []
        with ThreadPoolExecutor(8) as ex:
            eps = dict(ex.map(ep, models))
        return [{**m, "endpoints": eps.get(m["id"], [])} for m in models]
    return _cached("images_models", refresh, fetch)


def find(kind: str, model_id: str, refresh: bool = False, client=None) -> dict | None:
    try:
        rows = {"video": video_models, "image": image_models}.get(kind, chat_models)(refresh=refresh, client=client)
    except SlopError:
        return None
    for m in rows:
        if m.get("id") == model_id or m.get("canonical_slug") == model_id:
            return m
    return None


def lyria_model(kind: str = "pro", refresh: bool = False, client=None) -> str:
    """the Lyria model id as listed in /api/v1/models (pro = full song, clip = 30 s)."""
    want = "clip" if kind == "clip" else "pro"
    try:
        for m in chat_models(refresh=refresh, client=client):
            mid = m.get("id", "")
            if "lyria" in mid and want in mid and "audio" in (m.get("architecture", {}).get("output_modalities") or []):
                return mid
    except SlopError:
        pass
    return f"google/lyria-3-{want}-preview"


# --------------------------------------------------------------------------------------------- video pricing
def _res(resolution: str) -> str:
    return str(resolution or "720p").lower()


def out_dims(model: str, resolution: str) -> tuple[int, int]:
    res = _res(resolution)
    for prefix, table in OUT_DIMS.items():
        if (model or "").startswith(prefix) and res in table:
            return table[res]
    return DIMS.get(res, DIMS["720p"])


def billed_seconds(duration: float) -> float:
    """the seconds a token-priced take is billed for: one frame more than asked (calibrated, see module doc)."""
    return (round(float(duration) * 24) + EXTRA_FRAMES) / 24


def video_cost(skus: dict, duration: float, resolution: str = "720p", *, generate_audio: bool = True,
               video_input_s: float = 0.0, n_images: int = 0, image_input: bool = True, model: str = "") -> float | None:
    """$ for one generation from a model's pricing_skus (None when no SKU applies)."""
    s = {str(k).lower(): float(v) for k, v in (skus or {}).items() if _num(v)}
    res = _res(resolution)
    cost: float | None = None
    if any(k.startswith("video_tokens") for k in s):
        w, h = out_dims(model, res)
        tps = w * h * 24 / 1024
        rate = s.get(f"video_tokens_{res}", s.get("video_tokens"))
        if not generate_audio:
            rate = s.get(f"video_tokens_{res}_without_audio", s.get("video_tokens_without_audio", rate))
        secs = billed_seconds(duration)
        if video_input_s:
            rate = s.get(f"video_tokens_{res}_with_video_input", s.get("video_tokens_with_video_input", rate))
            secs = billed_seconds(duration) + video_input_s
        if rate is not None:
            cost = tps * secs * rate
    else:
        keys = []
        if generate_audio:
            keys += [f"duration_seconds_with_audio_{res}", "duration_seconds_with_audio"]
        else:
            keys += [f"duration_seconds_without_audio_{res}", "duration_seconds_without_audio"]
        if n_images:
            keys += [f"reference_duration_seconds_{res}"]
        keys += [f"{'image' if image_input else 'text'}_to_video_duration_seconds_{res}", f"duration_seconds_{res}",
                 "duration_seconds"]
        rate = next((s[k] for k in keys if k in s), None)
        if rate is None:
            cents = next((s[k] for k in (f"cents_per_second_output_{res}", f"cents_per_video_output_second_{res}",
                                         "cents_per_second_output") if k in s), None)
            rate = cents / 100 if cents is not None else None
        if rate is not None:
            cost = rate * duration
    if cost is None:
        return None
    if n_images:
        cost += s.get("reference_images", 0.0) * n_images + s.get("cents_per_image_input", 0.0) / 100 * n_images
    if "minimum_cents_per_generation" in s:
        cost = max(cost, s["minimum_cents_per_generation"] / 100)
    return round(cost, 4)


def _num(v) -> bool:
    try:
        float(v); return True
    except (TypeError, ValueError):
        return False


def seedance_cost(duration: float, resolution: str = "720p", rate: float = SEEDANCE_RATE,
                  model: str = "bytedance/seedance-2.5") -> float:
    w, h = out_dims(model, resolution)
    return round(billed_seconds(duration) * w * h * 24 / 1024 * rate, 4)


def estimate_video(model: str, duration: float, resolution: str = "720p", *, generate_audio: bool = True,
                   video_input_s: float = 0.0, n_images: int = 1, refresh: bool = False, client=None) -> float:
    rec = find("video", model, refresh=refresh, client=client)
    skus = (rec or {}).get("pricing_skus") or FALLBACK.get(model)
    if not skus:
        raise SlopError(f"no price known for video model {model!r} (not in the OpenRouter video listing). "
                        "List the models with: slop gen models --kind video")
    c = video_cost(skus, duration, resolution, generate_audio=generate_audio, video_input_s=video_input_s,
                   n_images=n_images, model=model)
    if c is None:
        raise SlopError(f"{model} has no price for {resolution}; supported: "
                        f"{(rec or {}).get('supported_resolutions')}. Pick one of those with --res.")
    return c


def video_rows(resolution: str = "720p", duration: float = 5, refresh: bool = False, client=None) -> list[dict]:
    out = []
    for m in video_models(refresh=refresh, client=client):
        res_ok = [r.lower() for r in (m.get("supported_resolutions") or [])]
        res = _res(resolution) if (not res_ok or _res(resolution) in res_ok) else res_ok[0]
        c = video_cost(m.get("pricing_skus") or {}, duration, res, model=m.get("id", ""))
        if c is None:
            continue
        refs = "image+video+audio refs" if re.match(r"bytedance/seedance-(2|[3-9])", m["id"]) else ""
        out.append({"id": m["id"], "est_usd": c, "per_s": round(c / duration, 4), "resolution": res, "duration": duration,
                    "audio": m.get("generate_audio"), "frames": m.get("supported_frame_images"),
                    "durations": _span(m.get("supported_durations")), "note": refs})
    return sorted(out, key=lambda r: r["est_usd"])


def _span(ds):
    if not ds:
        return None
    ds = sorted(ds)
    return f"{ds[0]}-{ds[-1]}s" if len(ds) > 3 else ",".join(map(str, ds))


# --------------------------------------------------------------------------------------------- image pricing
def image_cost(endpoints: list[dict], resolution: str = "1K", quality: str | None = None, n: int = 1,
               n_refs: int = 0, model_id: str = "", prompt_tokens: int | None = None) -> float | None:
    """$ for one call (n images) — the cheapest endpoint. prompt_tokens: the prompt's size (default PROMPT_TOKENS)."""
    best = None
    res = str(resolution or "1K").lower()
    q = (quality or "auto").lower()
    for ep in endpoints or []:
        rows = ep.get("pricing") or []
        out_rows = [r for r in rows if r.get("billable") == "output_image"]
        if not out_rows:
            continue
        if len(out_rows) > 1:
            pick = [r for r in out_rows if str(r.get("variant", "")).lower() in (f"{q}_{res}", res, q)]
            row = pick[0] if pick else max(out_rows, key=lambda r: float(r.get("cost_usd", 0)))
        else:
            row = out_rows[0]
        unit, c = row.get("unit"), float(row.get("cost_usd", 0))
        if unit == "image":
            per = c
        elif unit == "megapixel":
            per = c * IMG_MP.get(res, 1.05)
        elif unit == "token":
            if model_id.startswith("openai/") or "quality" in (ep.get("supported_parameters") or {}):
                per = c * OPENAI_OUT_TOKENS.get(q, 1800)
            else:
                per = c * GOOGLE_OUT_TOKENS.get(res, 1120)
        else:
            per = c
        total = per * max(1, n)
        for r in rows:
            if r.get("billable") == "input_image" and n_refs:
                rc = float(r.get("cost_usd", 0))
                total += rc * n_refs * (1000 if r.get("unit") == "token" else 1)
            if r.get("billable") == "input_text":
                total += float(r.get("cost_usd", 0)) * (PROMPT_TOKENS if prompt_tokens is None else prompt_tokens)
        best = total if best is None else min(best, total)
    return round(best, 4) if best is not None else None


def prompt_tokens(prompt: str | None) -> int | None:
    """a prompt's size in tokens (about 4 characters a token); None when unknown."""
    return max(1, math.ceil(len(prompt) / 4)) if prompt else None


def estimate_image(model: str, resolution: str = "1K", quality: str | None = None, n: int = 1, n_refs: int = 0,
                   refresh: bool = False, client=None, prompt: str | None = None) -> float:
    rec = find("image", model, refresh=refresh, client=client)
    c = image_cost((rec or {}).get("endpoints") or [], resolution, quality, n, n_refs, model,
                   prompt_tokens=prompt_tokens(prompt)) if rec else None
    if c is None:
        cm = find("chat", model, refresh=refresh, client=client)        # chat-listed image models (edit path)
        pr = (cm or {}).get("pricing") or {}
        if _num(pr.get("image_output")) and float(pr["image_output"]) > 0:
            per_tok = float(pr["image_output"])
            toks = OPENAI_OUT_TOKENS.get((quality or "auto").lower(), 1800) if model.startswith("openai/") else \
                GOOGLE_OUT_TOKENS.get(str(resolution).lower(), 1120)
            c = round(per_tok * toks * max(1, n) + float(pr.get("prompt") or 0) * (300 + 1100 * n_refs), 4)
    if c is None:
        raise SlopError(f"no price known for image model {model!r}. List the models with: slop gen models --kind image")
    return c


def estimate_edit(model: str, n_refs: int = 1, refresh: bool = False, client=None) -> float:
    """$ for one image edit (chat completions, 1K output, `n_refs` input images: the plate + references) — CONSERVATIVE.
    A chat call may be routed to any provider of the model, so the most expensive listed image endpoint and the chat
    listing's price are both priced and the larger one wins. (google/gemini-3-pro-image-preview lists a second endpoint
    at half the output price; the cheapest-first image estimate said $0.068 where the chat listing, like
    google/gemini-3-pro-image, prices ~$0.137.)"""
    vals = []
    rec = find("image", model, refresh=refresh, client=client)
    for ep in (rec or {}).get("endpoints") or []:
        c = image_cost([ep], "1K", None, 1, n_refs, model)
        if c is not None:
            vals.append(c)
    pr = (find("chat", model, refresh=refresh, client=client) or {}).get("pricing") or {}
    if _num(pr.get("image_output")) and float(pr["image_output"]) > 0:
        vals.append(round(float(pr["image_output"]) * GOOGLE_OUT_TOKENS["1k"]
                          + float(pr.get("prompt") or 0) * (300 + 1100 * n_refs), 4))
    if not vals:
        raise SlopError(f"no price known for edit model {model!r}. List the models with: slop gen models --kind image")
    return max(vals)


def image_rows(resolution: str = "1K", quality: str | None = None, refresh: bool = False, client=None) -> list[dict]:
    out = []
    for m in image_models(refresh=refresh, client=client):
        eps = m.get("endpoints") or []
        c = image_cost(eps, resolution, quality, 1, 0, m["id"])
        if c is None:
            continue
        sp = (eps[0].get("supported_parameters") if eps else None) or m.get("supported_parameters") or {}
        refs = (sp.get("input_references") or {}).get("max")
        note = ["needs a reference image (image-to-image only)" if (sp.get("input_references") or {}).get("min") else
                ("edit/refs" if refs else "")]
        if c == 0:
            note.append("listed at $0 (unpriced or promotional: verify)")
        out.append({"id": m["id"], "est_usd": c, "resolution": resolution, "refs_max": refs,
                    "note": "; ".join(x for x in note if x)})
    return sorted(out, key=lambda r: r["est_usd"])


# --------------------------------------------------------------------------------------------- text / vlm
def chat_cost(pricing: dict, tokens_in: int, tokens_out: int, images: int = 0) -> float | None:
    try:
        pin, pout = float(pricing.get("prompt", 0)), float(pricing.get("completion", 0))
    except (TypeError, ValueError):
        return None
    if pin < 0 or pout < 0:
        return None
    c = pin * tokens_in + pout * tokens_out
    if images and _num(pricing.get("image")) and float(pricing["image"]) > 0 and float(pricing["image"]) > 1e-4:
        c += float(pricing["image"]) * images                     # per-image input price (not per-token)
    return round(c, 6)


def chat_rows(kind: str = "text", refresh: bool = False, client=None) -> list[dict]:
    out = []
    for m in chat_models(refresh=refresh, client=client):
        arch = m.get("architecture") or {}
        ins, outs = arch.get("input_modalities") or [], arch.get("output_modalities") or []
        if outs != ["text"]:
            continue
        if kind == "vlm" and "image" not in ins:
            continue
        mid = m.get("id", "")
        if mid.startswith("openrouter/") or ":batch" in mid:
            continue
        tin, tout = VLM_CALL if kind == "vlm" else TEXT_CALL
        c = chat_cost(m.get("pricing") or {}, tin, tout, images=1 if kind == "vlm" else 0)
        if c is None:
            continue
        note = []
        if mid.endswith(":free"):
            note.append("free: 20 req/min, 50-1000/day")
        if "contributor" in mid:
            note.append("trains on your data")
        if m.get("expiration_date"):
            note.append(f"expires {m['expiration_date']}")
        if kind == "vlm" and "video" in ins:
            note.append("video in")
        out.append({"id": mid, "est_usd": c, "per_m_in": round(float(m['pricing'].get('prompt', 0)) * 1e6, 4),
                    "per_m_out": round(float(m['pricing'].get('completion', 0)) * 1e6, 4), "note": "; ".join(note)})
    return sorted(out, key=lambda r: (r["est_usd"], r["id"]))


def rows(kind: str, *, resolution: str | None = None, duration: float = 5, quality: str | None = None,
         refresh: bool = False, client=None) -> list[dict]:
    if kind == "video":
        return video_rows(resolution or "720p", duration, refresh=refresh, client=client)
    if kind == "image":
        return image_rows(resolution or "1K", quality, refresh=refresh, client=client)
    if kind in ("vlm", "text"):
        return chat_rows(kind, refresh=refresh, client=client)
    raise SlopError(f"unknown --kind {kind!r}: use image, video, vlm or text")


def per_second_table(model: str, durations=(4, 5, 8)) -> dict:
    return {r: {d: estimate_video(model, d, r) for d in durations} for r in ("480p", "720p")}


def ceil_int(x: float) -> int:
    return int(math.ceil(x - 1e-9))
