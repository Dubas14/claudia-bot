"""Image edit — fix a plate with an image-edit model (Gemini image via OpenRouter chat completions).

Port of the production imgedit.py. The rule behind it (owner, after a hand-painted fix): fixes to a plate "should have
been in the midjourney prompt from the start or with the edit model", never painted by hand. The instruction names what
changes; everything else must stay — the tool always appends the fixed keep-everything clause (verbatim, KEEP below).

Message (verbatim structure): "Edit this photograph. " + <instruction> + KEEP, then the plate as an RGB JPEG (q93)
data URL, then any reference images ("the second image" …). Body: {model, modalities:["image","text"], messages}.
Instruction grammar that worked: "Change only X: <precise target state, with negatives> … Keep Y."
(`--change X --keep Y` composes exactly that.) Re-check every edit for new canon errors (the edit model can, e.g.,
turn an eight-pointed star into a six-pointed one).

Additions: `--change/--keep` compose the instruction; the output is converted to the OUT suffix's format when the model
returns another one; the budget check runs before the call and the real usage.cost is ledgered; a timeout after the
request was sent is not re-sent (unknown outcome, ledgered at the estimate until checked on openrouter.ai/activity).
Default model: project.json models.edit, else google/gemini-3-pro-image (≈ $0.14 per call; the real usage.cost is
ledgered when returned). Never use an edit to get a reference past a provider's safety filter.

Estimate: models.estimate_edit — the most expensive listed endpoint / the chat listing price (an edit may be routed to
any provider of the model), so -preview and non-preview ids of the same model estimate alike (~$0.137).

Medium (`--medium photo|illustration|cel`, default project.json look.medium, else inferred from the project's lead canon
and style tails — an illustrated lead gives "illustration", with a note — else photo): the production wording above is
for PHOTOGRAPHS ("Edit this photograph … Photorealistic, the same photograph"). Sent with an illustrated / cel-shaded
plate (the Quick tier's recommended lead: illustrated faces pass the video providers' face filter) it pushes the edit
toward a photo — a new canon error, and a photoreal face the video provider may then decline. With "illustration" the
head is "Edit this illustration. " and the keep clause keeps the drawing style, line work and shading instead
(KEEP_ILLUSTRATION). When the plate's own sidecar prompt reads as an illustration and the medium is photo, a warning
says so.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

from .. import ledger
from ..config import SlopError
from . import models as reg
from .openrouter import OpenRouter, ProviderError, classify, decode_data_url, jpeg_data_url, make_error

DEFAULT_MODEL = "google/gemini-3-pro-image"
DEFAULT_EST = 0.14
HEAD = "Edit this photograph. "
KEEP = (" Keep everything else exactly as it is: the same framing and crop, the same light, colours, film grain and sharpness, "
        "the same people and objects except what this instruction changes. Photorealistic, the same photograph, same aspect ratio.")
HEAD_ILLUSTRATION = "Edit this illustration. "
KEEP_ILLUSTRATION = (" Keep everything else exactly as it is: the same framing and crop, the same drawing style, line work, "
                     "flat colours and shading, the same light, the same characters and objects except what this instruction "
                     "changes. Not a photograph: the same illustration, same aspect ratio.")
MEDIA = ("photo", "illustration")
ALIASES = {"cel": "illustration", "illustrated": "illustration", "anime": "illustration", "drawing": "illustration",
           "photograph": "photo", "photoreal": "photo"}       # `slop taste apply --medium photo|cel` uses "cel"
ILLUSTRATED_RE = re.compile(r"\b(illustrat\w*|cel[- ]shad\w*|anime|manga|cartoon|comic|drawn|drawing|line art|painted|"
                            r"painting|watercolou?r|gouache|vector|flat colou?r)\b", re.I)


def compose(instruction: str | None = None, change: str | None = None, keep: str | None = None) -> str:
    """the instruction text (without HEAD/KEEP): either as written, or "Change only X. Keep Y." from the parts."""
    if instruction and instruction.strip():
        return instruction.strip()
    if not change:
        raise SlopError('give the edit: an INSTRUCTION, or --change "what changes" [--keep "what must stay"]')
    s = "Change only " + change.strip().rstrip(".") + "."
    if keep:
        s += " Keep " + keep.strip().rstrip(".") + "."
    return s


def message_text(instruction: str, medium: str = "photo") -> str:
    if medium == "illustration":
        return HEAD_ILLUSTRATION + instruction.strip() + KEEP_ILLUSTRATION
    return HEAD + instruction.strip() + KEEP


def build_body(src: Path, instruction: str, refs: list[Path] | None = None, model: str = DEFAULT_MODEL,
               medium: str = "photo") -> dict:
    content = [{"type": "text", "text": message_text(instruction, medium)},
               {"type": "image_url", "image_url": {"url": jpeg_data_url(src)}}]
    for r in refs or []:
        content.append({"type": "image_url", "image_url": {"url": jpeg_data_url(r)}})
    return {"model": model, "modalities": ["image", "text"], "messages": [{"role": "user", "content": content}]}


def norm_medium(m: str | None) -> str | None:
    m = str(m or "").strip().lower()
    if not m:
        return None
    m = ALIASES.get(m, m)
    if m not in MEDIA:
        raise SlopError(f"--medium must be photo or illustration (cel = illustration), not {m!r}")
    return m


def project_medium(project: dict) -> tuple[str, str | None]:
    """(medium, note) when --medium is not given: project.json look.medium (photo | illustration | cel), else inferred
    from the project's lead canon and style tails (an illustrated lead -> illustration, with a note that says so)."""
    look = project.get("look") or {}
    try:
        m = norm_medium(look.get("medium"))
    except SlopError:
        m = None
    if m:
        return m, None
    lead = project.get("lead") or {}
    text = " ".join(str(x) for x in (lead.get("canon"), lead.get("far"), look.get("style_tail"),
                                     look.get("style_tail_api")) if x)
    if ILLUSTRATED_RE.search(text):
        return "illustration", ("medium: illustration, because the project's lead canon / style tail describes an "
                                "illustration (look.medium is not set); pass --medium photo if this plate is a photograph")
    return "photo", None


def looks_illustrated(src: Path) -> bool:
    """the plate's sidecar (written by slop gen image) describes an illustration."""
    side = Path(src).with_suffix(".json")
    if not side.is_file():
        return False
    try:
        doc = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    prompt = doc.get("prompt") if isinstance(doc, dict) else None
    return bool(ILLUSTRATED_RE.search(prompt or ""))


def edit(pdir: Path, src: Path, out: Path, instruction: str, *, refs: list[Path] | None = None, model: str | None = None,
         yes: bool = False, client: OpenRouter | None = None, medium: str = "photo") -> dict:
    src, out = Path(src), Path(out)
    if not src.is_file():
        raise SlopError(f"source image not found: {src}")
    for r in refs or []:
        if not Path(r).is_file():
            raise SlopError(f"reference image not found: {r}")
    medium = norm_medium(medium) or "photo"
    warnings = []
    if medium == "photo" and looks_illustrated(src):
        warnings.append(f"{src.name} was generated from an illustration prompt but the edit says 'photograph … "
                        "Photorealistic': if this plate is illustrated, re-run with --medium illustration (or set "
                        "look.medium to \"illustration\" in project.json)")
    if not model:
        from . import models as M
        model = M.latest(DEFAULT_MODEL, "image")
    try:
        est = reg.estimate_edit(model, 1 + len(refs or []))
    except SlopError:
        est = DEFAULT_EST
    ledger.check_budget(pdir, "openrouter", add_usd=est, yes=yes)
    client = client or OpenRouter()
    body = build_body(src, instruction, refs, model, medium)
    try:
        d = client.post("/chat/completions", body, where="image edit", retry_network=False)
    except ProviderError as e:
        if e.status == "unknown_outcome":                          # may have been billed: count it until checked
            ledger.record(pdir, provider="openrouter", model=model, kind="image-edit", est_usd=est, units={"est_usd": est},
                          status="submitted", note="unknown_outcome: check https://openrouter.ai/activity")
            raise
        ledger.record(pdir, provider="openrouter", model=model, kind="image-edit", est_usd=0.0, units={"est_usd": est},
                      status="declined" if e.status.startswith(("declined", "moderation")) else "failed", note=e.status)
        raise
    msg = ((d.get("choices") or [{}])[0].get("message") or {})
    imgs = msg.get("images") or []
    if not imgs:
        txt = str(msg.get("content"))[:300]
        st = classify(None, txt)
        ledger.record(pdir, provider="openrouter", model=model, kind="image-edit", est_usd=float((d.get("usage") or {}).get("cost") or 0),
                      units={"est_usd": est}, request_id=d.get("id"), status="ok", note="no image returned")
        if st in ("moderation", "declined_face", "declined_text"):
            raise make_error(None, txt, "image edit")
        raise SlopError("no image returned: " + txt + " — reword the instruction (Change only X … Keep Y) and re-run")
    raw, mime = decode_data_url(imgs[0]["image_url"]["url"])
    out.parent.mkdir(parents=True, exist_ok=True)
    want = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}.get(out.suffix.lower(), "PNG")
    got = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}.get(mime)
    if got == want:
        out.write_bytes(raw)
    else:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as im:
            (im.convert("RGB") if want == "JPEG" else im).save(out, want, **({"quality": 95} if want == "JPEG" else {}))
    from PIL import Image
    with Image.open(out) as im:
        size = list(im.size)
    real = (d.get("usage") or {}).get("cost")
    row = ledger.record(pdir, provider="openrouter", model=model, kind="image-edit",
                        est_usd=float(real) if real is not None else est,
                        units={"est_usd": est, "real_usd": real, "refs": len(refs or [])}, request_id=d.get("id"), status="ok")
    return {"out": str(out), "size": size, "cost_usd": real, "est_usd": est, "instruction": message_text(instruction, medium),
            "medium": medium, "warnings": warnings, "ledger": row}
