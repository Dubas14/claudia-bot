"""OpenRouter HTTP client (requests): auth, retries, error mapping, data URLs.

Headers: `Authorization: Bearer $OPENROUTER_API_KEY` (the key is read from the environment only and never printed),
`HTTP-Referer: claudia`, `X-Title: claudia`, `User-Agent: claudia/<version>`.

Retries: 429 and 5xx (and network errors on GETs) are retried with exponential backoff (2, 4, 8, 16 s, capped at 30 s; a
`Retry-After` header wins). 4xx are never retried. Paid POSTs are not re-sent once the request may have reached the
server: a read timeout or a dropped connection leaves the outcome unknown and re-posting could pay twice (the production
lesson for Higgsfield: "transport timeout → outcome unknown: do not resubmit") — they raise status `unknown_outcome`
(`retry_network=False`: images, image edits, songs; the video submit also passes `retry_5xx=False`, because a 5xx on
an async submit may still have queued the job). A connection that was never established (connect timeout, DNS, refused)
is always safe to retry. 429 is always retried because a rate-limited request was never accepted.

Error mapping (ProviderError.status; every message says what to do next):
  credits      402 — the account is out of credits
  key_limit    403 — this API key hit its own spend limit (the account may still have credit)
  declined_face  PrivacyInformation / InputImageSensitiveContentDetected — the provider's real-face filter declined a
                 reference. Free and FINAL for that image: never alter the image to pass the filter; trying the other
                 provider with the same unaltered image is allowed.
  declined_text  InputTextSensitiveContentDetected — reword the prompt (keep the beat, change the words)
  copyright    "the output audio may be related to copyright restrictions" — retry once as it is; refused again: the
               other provider (clips: slop.gen.clips.note_refusal gives the one next step)
  sensitive    "the output audio may contain sensitive information" — retry once reworded; refused again: the other
               provider
  ProviderError.head is the message without the advice (callers that print their own next step use it, so the
  operator never sees two different instructions).
  moderation   other moderation/flagged refusals
  auth 401 · not_found 404 · too_large 413 · rate_limited 429 · server 5xx · bad_request 400 · network
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from .. import __version__
from ..config import SlopError, require_env

BASE = "https://openrouter.ai/api/v1"
APP = "claudia"
INLINE_LIMIT = 3_000_000          # images above this go in re-encoded (the request is capped at ~32 MB)

ADVICE = {
    "credits": "OpenRouter says the account is out of credits (402). Top up at https://openrouter.ai/settings/credits, "
               "then re-run the same command.",
    "key_limit": "OpenRouter refused the key (403): this API key has its own spend limit and reached it, even if the "
                 "account still has credit. Raise the key's limit at https://openrouter.ai/settings/keys (owner decision), "
                 "then re-run.",
    "auth": "OpenRouter rejected the API key (401). Check OPENROUTER_API_KEY (ask the bot to request it again with the "
            "secure secret card).",
    "declined_face": "The provider's face filter declined this reference image (PrivacyInformation). A decline is free "
                     "and FINAL for this image: never alter, blur or re-grade it to get past the filter. Options: keep "
                     "the shot on its 2.5D plate, use another plate candidate, or send the same unaltered image to "
                     "Higgsfield: slop clip set CLIP --provider higgsfield && slop clip lock CLIP && "
                     "slop clip submit CLIP --yes",
    "declined_text": "The provider's text filter declined the prompt (InputTextSensitiveContentDetected). Reword it: keep "
                     "the beat, change the words (see docs/62-moderation), then slop clip set + lock + submit.",
    "copyright": "The provider refused the output audio as possibly copyrighted (not billed). Retry once as it is (it "
                 "often passes); if it is refused again, send the same unaltered image and window to the other provider.",
    "sensitive": "The provider flagged the output audio as possibly containing sensitive information (not billed). Retry "
                 "once with a reworded prompt (same timestamps and quoted words); if it is refused again, send the same "
                 "unaltered image and window to the other provider.",
    "moderation": "The request was refused by moderation. Reword the prompt (keep the beat, change the words); never "
                  "alter a reference image to pass a filter.",
    "not_found": "OpenRouter does not know this model or job (404). Check the model id with: slop gen models --kind video",
    "too_large": "The request is too large (413, ~32 MB cap). Host large references by URL instead of inlining them.",
    "rate_limited": "OpenRouter is rate limiting (429) and retries ran out. Wait a minute and re-run.",
    "server": "OpenRouter or the provider had a server error and retries ran out. Wait a few minutes and re-run.",
    "bad_request": "OpenRouter rejected the request (400). Read the message above; fix the parameter it names.",
    "network": "Could not reach openrouter.ai. Check the network, then re-run.",
    "unknown_outcome": "The request got a server/network error after it was sent: it may or may not have been accepted "
                       "(and billed). Do NOT re-run it blindly — look for it at https://openrouter.ai/activity first.",
}


class ProviderError(SlopError):
    """A provider refusal or failure with a machine-readable status (see module doc)."""

    def __init__(self, message: str, *, status: str = "error", http: int | None = None, detail: str = "",
                 head: str | None = None):
        super().__init__(message)
        self.status = status
        self.http = http
        self.detail = detail
        self.head = head or message                     # the message without the ADVICE text


def classify(http: int | None, text: str) -> str:
    """status for an error response body / a failed job's error text."""
    t = (text or "").lower()
    if "privacyinformation" in t or "inputimagesensitivecontentdetected" in t or "real person" in t or "real-person" in t:
        return "declined_face"
    if "inputtextsensitivecontentdetected" in t:
        return "declined_text"
    if "copyright" in t:
        return "copyright"
    if "sensitive information" in t or "outputaudiosensitive" in t:
        return "sensitive"
    if http == 402 or "insufficient credits" in t or "more credits" in t:
        return "credits"
    if ("moderation" in t or "flagged" in t or "sensitivecontent" in t or "content policy" in t or "safety system" in t
            or "safety filter" in t):
        return "moderation"
    if http == 401:
        return "auth"
    if http == 403:
        return "key_limit" if ("limit" in t or "key" in t or not t.strip()) else "moderation"
    if http == 404:
        return "not_found"
    if http == 413:
        return "too_large"
    if http == 429:
        return "rate_limited"
    if http is not None and http >= 500:
        return "server"
    if http == 400:
        return "bad_request"
    return "error"


def error_text(body: Any) -> str:
    """the human message inside an OpenRouter error body (and the provider's raw message when present)."""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode(errors="replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return body[:600]
    if isinstance(body, dict):
        e = body.get("error", body)
        if isinstance(e, dict):
            msg = str(e.get("message") or "")
            meta = e.get("metadata") or {}
            raw = meta.get("raw") if isinstance(meta, dict) else None
            if raw:
                msg += " | " + (raw if isinstance(raw, str) else json.dumps(raw))[:400]
            if isinstance(meta, dict) and meta.get("reasons"):
                msg += " | " + ", ".join(map(str, meta["reasons"]))
            return msg[:800] or json.dumps(e)[:600]
        return str(e)[:600]
    return str(body)[:600]


def make_error(http: int | None, text: str, where: str = "") -> ProviderError:
    st = classify(http, text)
    head = f"OpenRouter {where + ' ' if where else ''}{'HTTP ' + str(http) if http else 'error'}: {text.strip()[:500]}"
    adv = ADVICE.get(st, "")
    return ProviderError(head + ((" — " + adv) if adv else ""), status=st, http=http, detail=text, head=head)


class OpenRouter:
    """Small client. `session` is any object with requests.Session's .request(); tests inject a fake."""

    def __init__(self, key: str | None = None, *, session: Any = None, base: str = BASE, retries: int = 4,
                 backoff: float = 2.0, max_backoff: float = 30.0, timeout: float = 300.0,
                 sleep: Callable[[float], None] = time.sleep):
        self._key = key
        self.session = session
        self.base = base.rstrip("/")
        self.retries = retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.timeout = timeout
        self.sleep = sleep

    # ---- plumbing ----
    def _sess(self):
        if self.session is None:
            import requests
            self.session = requests.Session()
        return self.session

    def key(self) -> str:
        if not self._key:
            self._key = require_env("OPENROUTER_API_KEY", "needed for OpenRouter image/video/song generation")
        return self._key

    def headers(self, auth: bool = True, json_body: bool = True) -> dict:
        h = {"HTTP-Referer": APP, "X-Title": APP, "User-Agent": f"{APP}/{__version__}"}
        if json_body:
            h["Content-Type"] = "application/json"
        if auth:
            h["Authorization"] = f"Bearer {self.key()}"
        return h

    def url(self, path: str) -> str:
        return path if path.startswith("http") else self.base + "/" + path.lstrip("/")

    def _delay(self, attempt: int, resp: Any = None) -> float:
        if resp is not None:
            ra = (getattr(resp, "headers", None) or {}).get("Retry-After")
            try:
                if ra is not None:
                    return min(self.max_backoff, max(0.0, float(ra)))
            except ValueError:
                pass
        return min(self.max_backoff, self.backoff * (2 ** attempt))

    def request(self, method: str, path: str, *, json_body: Any = None, auth: bool = True, raw: bool = False,
                stream: bool = False, retry_5xx: bool = True, retry_network: bool | None = None,
                timeout: float | None = None, where: str = "") -> Any:
        """JSON (default), raw bytes (raw=True) or the streaming response (stream=True).
        retry_network (default: GET or retry_5xx): re-send after a timeout / dropped connection. Paid POSTs pass False."""
        import requests
        method = method.upper()
        data = json.dumps(json_body).encode() if json_body is not None else None
        h = self.headers(auth=auth, json_body=json_body is not None)
        resend = retry_network if retry_network is not None else (method == "GET" or retry_5xx)
        last: Any = None
        for attempt in range(self.retries + 1):
            try:
                r = self._sess().request(method, self.url(path), headers=h, data=data, timeout=timeout or self.timeout,
                                         stream=stream)
            except (requests.ConnectionError, requests.Timeout) as e:
                safe = method == "GET" or resend or never_sent(e)
                if attempt < self.retries and safe:
                    self.sleep(self._delay(attempt)); continue
                st = "network" if safe else "unknown_outcome"
                raise ProviderError(f"OpenRouter {where or path}: {type(e).__name__} — {ADVICE[st]}", status=st) from e
            code = int(getattr(r, "status_code", 0) or 0)
            if code == 429 or (code >= 500 and (retry_5xx or method == "GET")):
                last = r
                if attempt < self.retries:
                    self.sleep(self._delay(attempt, r)); continue
            if code >= 500 and not retry_5xx and method != "GET":
                txt = error_text(getattr(r, "content", b"") or getattr(r, "text", ""))
                raise ProviderError(f"OpenRouter {where or path} HTTP {code}: {txt[:300]} — {ADVICE['unknown_outcome']}",
                                    status="unknown_outcome", http=code, detail=txt)
            if code >= 400:
                txt = error_text(getattr(r, "content", b"") or getattr(r, "text", ""))
                raise make_error(code, txt, where or path)
            if stream:
                return r
            if raw:
                return r.content
            try:
                return r.json()
            except ValueError as e:
                raise ProviderError(f"OpenRouter {where or path}: response was not JSON ({str(e)[:100]})", status="server",
                                    http=code) from e
        txt = error_text(getattr(last, "content", b"") or "") if last is not None else ""
        raise make_error(getattr(last, "status_code", None), txt, where or path)

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any, **kw) -> Any:
        return self.request("POST", path, json_body=body, **kw)

    def sse(self, path: str, body: Any, **kw) -> Iterator[dict]:
        """POST with stream=True; yields each `data:` JSON event (OpenRouter chat streaming). A stream that breaks
        after it started is an unknown outcome (the call was accepted and may be billed)."""
        import requests
        r = self.request("POST", path, json_body=body, stream=True, **kw)
        try:
            lines = list(r.iter_lines())
        except (requests.RequestException, OSError) as e:
            raise ProviderError(f"OpenRouter {kw.get('where') or path}: the stream broke ({type(e).__name__}) — "
                                f"{ADVICE['unknown_outcome']}", status="unknown_outcome") from e
        for line in lines:
            if not line:
                continue
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            if line.startswith(":") or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("error"):
                raise make_error(None, error_text(ev), path)
            yield ev


def never_sent(e: BaseException) -> bool:
    """True when the connection was never established (connect timeout, DNS failure, refused): safe to re-send."""
    import requests
    if isinstance(e, requests.ConnectTimeout):
        return True
    t = repr(e)
    return any(k in t for k in ("NewConnectionError", "NameResolutionError", "Failed to establish a new connection",
                                "Name or service not known", "getaddrinfo failed", "Connection refused"))


# ---------------------------------------------------------------------------------------------------- data URLs
def data_url(path: Path | str, limit: int = INLINE_LIMIT, kind: str = "image") -> str:
    """a data: URL for a local file. Images above `limit` bytes are re-encoded as JPEG (q92, <= 2400 px wide) so the
    request stays under OpenRouter's ~32 MB cap — a size change only, never a content change."""
    p = Path(path)
    if not p.is_file():
        raise SlopError(f"file not found: {p}")
    ct = mimetypes.guess_type(p.name)[0] or ("image/png" if kind == "image" else "application/octet-stream")
    raw = p.read_bytes()
    if kind == "image" and len(raw) > limit:
        from PIL import Image
        with Image.open(p) as im:
            im = im.convert("RGB")
            if im.width > 2400:
                im = im.resize((2400, max(1, round(im.height * 2400 / im.width))), Image.LANCZOS)
            b = io.BytesIO(); im.save(b, "JPEG", quality=92)
        raw, ct = b.getvalue(), "image/jpeg"
    return f"data:{ct};base64," + base64.b64encode(raw).decode()


def jpeg_data_url(path: Path | str, quality: int = 93) -> str:
    """the image re-encoded as RGB JPEG (the image-edit path sends the plate this way)."""
    from PIL import Image
    with Image.open(path) as im:
        b = io.BytesIO(); im.convert("RGB").save(b, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def decode_data_url(u: str) -> tuple[bytes, str]:
    """(bytes, mime) from a data: URL."""
    if not u.startswith("data:") or "," not in u:
        raise SlopError("expected a data: URL from the provider")
    head, b64 = u.split(",", 1)
    mime = head[5:].split(";")[0] or "application/octet-stream"
    return base64.b64decode(b64), mime
