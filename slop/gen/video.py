"""OpenRouter video generation (POST /api/v1/videos -> poll GET /videos/{id} -> GET /videos/{id}/content?index=0).

Body: {model, prompt, duration, resolution, aspect_ratio, generate_audio, frame_images?, input_references?}.
  REFERENCE MODE (sung clips, and motion clips by default): the plate as input_references image_url (= @Image1, a data
    URL), the song window as input_references audio_url (= @Audio1, HTTPS only), optional video refs (@Video1…).
    Audio/video references are honoured only by Seedance 2+ (bytedance/seedance-2.x); other models ignore them (warned).
  FIRST-FRAME MODE (motion clips that need an exact start frame): frame_images first_frame (+ last_frame). VERIFIED
    2026-10-01: when frame_images is sent, OpenRouter IGNORES input_references — the audio window does nothing — so in
    this mode no references are sent at all (the take gets its own soundtrack; it plays at lag 0).
  Whenever a MOTION take goes out without an audio reference (first-frame mode, --no-audio-ref, or a model that takes
    none) the body's "moving in time with @Audio1" becomes "moving in time with the music" (there is no @Audio1 to
    point at) and a warning says the take is not conditioned on the song's beat. The clip file keeps its prompt.
Submit is NOT retried on 5xx/network errors (outcome unknown: re-posting could pay twice); 429 is retried.
Cost: Seedance tokens = W × H × 24 × billed s / 1024 at $10.7/M for 2.5 (480p $0.1028/s, 720p $0.2311/s; billed s =
(round(s × 24) + 1) / 24, and the 2.0 family renders 480p at 864×496 — calibrated on real takes, see slop.gen.models);
other models from their pricing_skus. Failed jobs are not billed.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from ..config import SlopError
from . import models as reg
from . import store
from .openrouter import OpenRouter, ProviderError, classify, data_url, make_error

DEFAULT_MODEL = "bytedance/seedance-2.5"
TERMINAL = ("completed", "failed", "cancelled", "canceled", "expired")
SEEDANCE2_RE = re.compile(r"^bytedance/seedance-(2|[3-9])")
AUDIO_PHRASE_RE = re.compile(r"(moving in time with) @Audio1", re.I)


def media_refs_ok(model: str) -> bool:
    """audio/video input_references are honoured only by Seedance generation 2 and newer."""
    return bool(SEEDANCE2_RE.match(model or ""))


def image_ref(url_or_path: str | Path, pdir: Path | None = None) -> dict:
    s = str(url_or_path)
    if s.startswith(("https://", "data:")):
        return {"type": "image_url", "image_url": {"url": s}}
    p = store.absp(pdir, s) if pdir else Path(s)
    return {"type": "image_url", "image_url": {"url": data_url(p)}}


def build_body(pdir: Path, clip: dict, *, model: str, audio_url: str | None, video_urls: list[str] | None = None,
               warnings: list[str] | None = None) -> dict:
    warnings = warnings if warnings is not None else []
    body = clip.get("body") or {}
    b = {"model": model}
    for k in ("prompt", "duration", "resolution", "aspect_ratio", "generate_audio", "seed"):
        if body.get(k) is not None:
            b[k] = body[k]
    start = clip.get("start")
    if not start:
        raise SlopError(f"{clip['id']} has no start image: slop clip set {clip['id']} --start IMAGE")
    cid = clip.get("id", "the clip")
    if clip.get("frame") == "first":
        b["frame_images"] = [{**image_ref(start, pdir), "frame_type": "first_frame"}]
        if clip.get("end"):
            b["frame_images"].append({**image_ref(clip["end"], pdir), "frame_type": "last_frame"})
        warnings.append("first-frame mode: no audio reference is sent — OpenRouter ignores input_references (the audio "
                        "window and extra refs) when a first frame is sent (verified 2026-10-01) — so this take is NOT "
                        f"conditioned on the song's beat. For beat conditioning use reference mode: slop clip set {cid} "
                        "--frame ref (or run it on Higgsfield, where start image + audio both count).")
        _no_audio_prompt(b, clip, warnings, said=True)
        return b
    refs = [image_ref(start, pdir)] + [image_ref(r, pdir) for r in clip.get("refs") or []]
    sent_audio = False
    if media_refs_ok(model):
        refs += [{"type": "video_url", "video_url": {"url": u}} for u in (video_urls or [])]
        if audio_url:
            refs.append({"type": "audio_url", "audio_url": {"url": audio_url}})
            sent_audio = True
    elif audio_url or video_urls:
        warnings.append(f"{model} ignores audio/video references (only Seedance 2+ honour them): the take will not be "
                        "conditioned on the song window")
    if not sent_audio:
        _no_audio_prompt(b, clip, warnings, said=bool(audio_url))
    b["input_references"] = refs
    return b


def _no_audio_prompt(b: dict, clip: dict, warnings: list[str], said: bool = False) -> None:
    """a motion take without @Audio1: say so, and stop the prompt pointing at an @Audio1 that is not sent."""
    if clip.get("kind") != "motion":
        return
    if not said:
        warnings.append(f"no audio reference goes out with {clip.get('id', 'this clip')}: the take is NOT conditioned on "
                        "the song's beat (motion on the beat comes only from @Audio1 on Seedance 2+, reference mode)")
    p = b.get("prompt") or ""
    if "@Audio1" in p:
        b["prompt"] = AUDIO_PHRASE_RE.sub(lambda m: m.group(1) + " the music", p)
        if "@Audio1" in b["prompt"]:
            warnings.append("the prompt still names @Audio1 although no audio is sent: reword those lines")
        else:
            warnings.append('"moving in time with @Audio1" was sent as "moving in time with the music"')


def summary(body: dict) -> dict:
    """the request as stored in the take (no inline data URLs)."""
    out = {k: v for k, v in body.items() if k not in ("frame_images", "input_references")}
    refs = []
    for r in body.get("frame_images") or []:
        refs.append(f"{r.get('frame_type')}:image")
    for r in body.get("input_references") or []:
        t = r.get("type", "")
        u = (r.get(t) or {}).get("url", "")
        refs.append(f"{t}:{'data' if u.startswith('data:') else u}")
    out["refs"] = refs
    return out


def estimate(model: str, body: dict, video_input_s: float = 0.0) -> float:
    n_img = sum(1 for r in body.get("input_references") or [] if r.get("type") == "image_url") + len(body.get("frame_images") or [])
    return reg.estimate_video(model, float(body.get("duration") or 5), str(body.get("resolution") or "720p"),
                              generate_audio=bool(body.get("generate_audio", True)), video_input_s=video_input_s,
                              n_images=n_img)


def submit(client: OpenRouter, body: dict) -> dict:
    r = client.post("/videos", body, retry_5xx=False, where="videos submit")
    if not isinstance(r, dict) or not r.get("id"):
        raise ProviderError(f"no job id in the response (not submitted, not billed): {str(r)[:300]}", status="error")
    return r


def job_status(client: OpenRouter, job_id: str, polling_url: str | None = None) -> dict:
    return client.get(polling_url or f"/videos/{job_id}", where="videos poll")


def job_error(st: dict) -> tuple[str, str]:
    """(status class, message) for a failed job."""
    e = st.get("error") or st.get("failure_reason") or st.get("message") or ""
    if isinstance(e, dict):
        e = e.get("message") or str(e)
    return classify(None, str(e)), str(e) or st.get("status", "failed")


def download(client: OpenRouter, job_id: str, out: Path) -> Path:
    raw = client.request("GET", f"/videos/{job_id}/content?index=0", raw=True, timeout=900, where="videos download")
    if not raw or len(raw) < 1000:
        raise ProviderError(f"the video download for {job_id} was empty — re-run slop clip poll", status="server")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)
    return out


def wait(client: OpenRouter, job_id: str, polling_url: str | None, max_s: float, sleep=time.sleep) -> dict:
    """poll with backoff 5 s ×1.4 up to 20 s until terminal or max_s elapsed (max_s 0 = one check)."""
    t_end = time.monotonic() + max_s; dly = 5.0
    while True:
        st = job_status(client, job_id, polling_url)
        if st.get("status") in TERMINAL or time.monotonic() + dly > t_end:
            return st
        sleep(dly); dly = min(20.0, dly * 1.4)


def failure_error(st: dict, job_id: str) -> ProviderError:
    cls, msg = job_error(st)
    return make_error(None, f"job {job_id} {st.get('status')}: {msg}", "video") if cls != "error" else \
        ProviderError(f"job {job_id} {st.get('status')}: {msg}", status="failed")
