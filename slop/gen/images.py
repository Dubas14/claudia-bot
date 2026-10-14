"""Image generation through OpenRouter's image API (POST /api/v1/images).

Request: {model, prompt, aspect_ratio, resolution, quality, n, seed, input_references:[{type:image_url, image_url:{url}}]}
(references as data URLs, up to 16 depending on the model). Response: {data:[{b64_json|url, media_type}],
usage:{cost}}. A generation either completes and is billed in full or fails and is not billed, so 429/5xx are retried.
A timeout or dropped connection after the request was sent is NOT re-sent (it may have been billed): it is ledgered as
"submitted" at the estimate (note unknown_outcome) and the error says to check https://openrouter.ai/activity.

Spend: the estimate is checked against the project budget BEFORE the call (slop.ledger.check_budget); the ledger row
carries the real `usage.cost` when the provider returns it (est_usd = real cost, units.est_usd = the estimate).
Files: plates/cands/<plate>/<k>.<ext> (next free k) + <k>.json sidecar (prompt, model, settings, cost), or an explicit
--out (with --n > 1: <stem>-1<ext>, <stem>-2<ext>, …). A number k is claimed by creating <k>.json exclusively before the
image is written, so two writers (batch workers, two shells) can never pick the same k and overwrite a paid image.

Batch runner (`slop gen image --jobs [plates/jobs.json] [--only P,..] [--missing] [--yes]`): reads the API jobs that
`slop plates book` writes ({"jobs":[{plate, prompt | prompt_file, aspect, n, model?, quality?, resolution?}]}) and runs
them as ONE spend: one estimate for the whole batch, one confirmation (--yes), one budget check for the total before the
first call. Without --yes it is a dry run (nothing is sent). Resumable: a job counts the images it already made (the
sidecars in plates/cands/<plate>/ with the same prompt, model, quality, resolution and aspect) and only makes the rest,
so re-running the same command after an interruption continues where it stopped and never pays twice. Images made at
other settings (e.g. --quality low drafts before a --quality high pass) are listed but not counted. Several jobs may
name the same plate (e.g. three prompt options for one plate): they run one after another on one worker, and jobs with
the same prompt and settings share the images already made, in file order. --missing skips plates that have any
candidate at all (e.g. Midjourney downloads). A refused job (moderation, bad request) is reported and the batch goes on;
an account problem (credits, key limit, auth, rate limit, server, unknown outcome) stops the batch. Every hint it prints
names the project (`slop -p NAME …`), so it runs from any directory.

Reference images (identity anchor): `--ref` takes an image file, an https/data URL, or a plate candidate PLATE[:K]
(PLATE#K and PLATE~K work too; no K = the plate's pick in plates/picks.json). A job in jobs.json may carry its own
"refs": [...] (same forms, files relative to the project; `slop plates book --anchor PLATE[:K]` writes the approved
lead image into every lead plate job); `--ref` on the batch is added to every job. They go out as input_references
(data URLs for files). Refused before any spend when the registry says the model takes no references (or fewer than
asked). The sidecar records them ("refs": project-relative paths / URLs without their query), and resume counts only
images made with the same refs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import shlex
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import ledger
from ..config import SlopError, load_project
from . import models as reg
from .openrouter import OpenRouter, ProviderError, data_url

DEFAULT_MODEL = "openai/gpt-image-2"
STOP_BATCH = ("credits", "key_limit", "auth", "rate_limited", "server", "network", "unknown_outcome")

EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/svg+xml": ".svg"}


def next_index(d: Path) -> int:
    ks = []
    for p in d.glob("*"):
        if p.stem.isdigit():
            ks.append(int(p.stem))
    return max(ks, default=0) + 1


def reserve(d: Path, ext: str, sidecar: dict | None = None) -> Path:
    """the next free <k><ext> in d, claimed atomically: <k>.json (the sidecar) is created exclusively FIRST, so two
    writers that read the same next_index never both take k (the second moves on to k + 1)."""
    d.mkdir(parents=True, exist_ok=True)
    k = next_index(d)
    for _ in range(10000):
        try:
            with open(d / f"{k}.json", "x", encoding="utf-8") as f:
                f.write(json.dumps(sidecar or {}, indent=1))
        except FileExistsError:
            k += 1
            continue
        return d / f"{k}{ext}"
    raise SlopError(f"could not find a free file number in {d}")


def _pcmd(pdir: Path, rest: str) -> str:
    """a command line with the project spelled out (runs from any directory, like board.common.pcmd)."""
    try:
        from ..core_cli import project_ref
        ref = project_ref(Path(pdir))
    except ImportError:
        import shlex
        ref = shlex.quote(str(pdir))
    return f"slop -p {ref} {rest}"


# ------------------------------------------------------------------------------------------------ reference images
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")
REF_RE = re.compile(r"^(?P<plate>[A-Za-z0-9][\w.~-]{0,79}?)(?:[:#](?P<k>\d{1,4}))?$")


def ref_id(pdir: Path, s: str) -> str:
    """the stable name of a reference for sidecars and resume: a project-relative path (else absolute, posix), a URL
    without its query (signed links carry tokens), or a short hash of a data: URL."""
    s = str(s)
    if s.startswith("data:"):
        return "data:sha1:" + hashlib.sha1(s.encode()).hexdigest()[:16]
    if s.startswith(("http://", "https://")):
        return s.split("#", 1)[0].split("?", 1)[0]
    p = Path(s)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(Path(pdir).resolve()).as_posix()
        except (ValueError, OSError):
            return p.as_posix()
    return p.as_posix()


def _cand_files(pdir: Path, plate: str) -> dict[int, Path]:
    """plates/cands/<plate>/<k>.<image ext> (any case) by k."""
    d = Path(pdir) / "plates" / "cands" / plate.split("~")[0]
    return {int(p.stem): p for p in sorted(d.iterdir()) if p.stem.isdigit() and p.suffix.lower() in IMG_EXTS} \
        if d.is_dir() else {}


def cand_file(pdir: Path, plate: str, k: int) -> Path | None:
    return _cand_files(pdir, plate).get(int(k))


def _cand_ks(pdir: Path, plate: str) -> list[int]:
    return sorted(_cand_files(pdir, plate))


URL_RE = re.compile(r"^(https?):[\\/]+(.*)$", re.I | re.S)


def _url(r: str) -> str | None:
    """r as an http(s) URL, or None. Repairs one that went through a path normaliser on the way in (`https:/host/a`,
    `https:\\host\\a`: the CLI's input-path helper collapses '//'); a file path never starts with 'https:'."""
    m = URL_RE.match(r)
    if not m:
        return None
    rest = m.group(2).replace("\\", "/") if "\\" in r.split("?", 1)[0] else m.group(2)
    return f"{m.group(1).lower()}://{rest}"


def resolve_ref(pdir: Path, ref: str, in_project: bool = False) -> dict:
    """one reference -> {"ref": as given, "src": URL or absolute file, "id": ref_id, "plate", "k"}.
    Forms: an https/data URL; an image file (from the current folder, else inside the project; in_project: a relative
    path only inside the project, for the project-relative paths a jobs file holds: the current folder may be another
    project's, with its own plates/cands/lead-cu/2.jpg); PLATE[:K] (also PLATE#K, PLATE~K): candidate K of
    plates/cands/PLATE/, or with no K the plate's pick (plates/picks.json)."""
    r = str(ref or "").strip()
    if not r:
        raise SlopError("an empty --ref: give an image file, a URL, or PLATE[:K] (a plate candidate)")
    if r.startswith("data:"):
        return {"ref": r, "src": r, "id": ref_id(pdir, r), "plate": None, "k": None}
    u = _url(r)
    if u:
        return {"ref": u, "src": u, "id": ref_id(pdir, u), "plate": None, "k": None}
    p = Path(r).expanduser()
    here = [p, Path(pdir) / p]
    for f in ([p] if p.is_absolute() else here[1:] if in_project else here):
        if f.is_file():
            src = str(f.resolve())
            rid = ref_id(pdir, src)
            mc = re.fullmatch(r"plates/cands/([^/]+)/(\d+)\.\w+", rid)      # a candidate named by its path
            return {"ref": r, "src": src, "id": rid, "plate": mc.group(1) if mc else None,
                    "k": int(mc.group(2)) if mc else None}
    m = REF_RE.match(r)
    if not m or Path(r).suffix.lower() in IMG_EXTS:
        raise SlopError(f"--ref {r}: no such image file (looked in "
                        + ("the project" if p.is_absolute() or in_project else "the current folder and in the project")
                        + "); give an image file, an https URL, or PLATE[:K] (candidate K of plates/cands/PLATE/)")
    plate, k = m.group("plate"), int(m.group("k")) if m.group("k") else None
    base = plate.split("~")[0]
    if k is None and "~" in plate and plate.split("~", 1)[1].isdigit():
        k = int(plate.split("~", 1)[1])                         # a variant key names its candidate
    have = _cand_ks(pdir, base)
    if not have:
        raise SlopError(f"--ref {r}: not an image file, and plates/cands/{base}/ has no candidates (`slop plates "
                        "status` lists the plates); give an image file, an https URL, or PLATE[:K]")
    if k is None:
        picks = {}
        try:
            picks = json.loads((Path(pdir) / "plates" / "picks.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        pk = picks.get(plate) if isinstance(picks, dict) else None
        if not isinstance(pk, dict) or pk.get("cand_k") is None:
            raise SlopError(f"--ref {r}: {plate} has no pick yet; name the candidate (`--ref {plate}:K`, K one of "
                            f"{', '.join('#' + str(x) for x in have)}) or record the owner's pick first (`slop plates "
                            f"pick {plate} K`)")
        k = int(pk["cand_k"])
    f = cand_file(pdir, base, k)
    if f is None:
        raise SlopError(f"--ref {r}: {base} has no candidate #{k} (has {', '.join('#' + str(x) for x in have)})")
    src = str(f.resolve())
    return {"ref": r, "src": src, "id": ref_id(pdir, src), "plate": base, "k": k}


def resolve_refs(pdir: Path, refs: list[str] | None, in_project: bool = False) -> list[dict]:
    """every reference resolved, duplicates (the same image named twice) dropped, order kept."""
    out, seen = [], set()
    for r in refs or []:
        d = resolve_ref(pdir, r, in_project=in_project)
        if d["id"] not in seen:
            seen.add(d["id"])
            out.append(d)
    return out


def _cached_image_model(model: str) -> dict | None:
    """the model's record from the cached image listing only (no network, any age); None when not cached."""
    from ..config import cache_dir
    try:
        doc = json.loads((cache_dir("openrouter") / "images_models.json").read_text(encoding="utf-8"))
        rows = doc.get("data") if isinstance(doc, dict) else None
    except (OSError, json.JSONDecodeError, SlopError):
        return None
    return next((m for m in rows or [] if isinstance(m, dict)
                 and model in (m.get("id"), m.get("canonical_slug"))), None)


def refs_max(model: str, cached_only: bool = False) -> int | None:
    """how many input_references the model takes per the OpenRouter image listing: 0 = none, None = not listed
    (unknown to the registry or no parameter data; the provider decides). cached_only: never fetch the listing (for
    free local commands such as `slop plates book`)."""
    rec = _cached_image_model(model) if cached_only else reg.find("image", model)
    if not rec:
        return None
    sps = [ep.get("supported_parameters") for ep in rec.get("endpoints") or []
           if isinstance(ep.get("supported_parameters"), dict) and ep.get("supported_parameters")]
    sps = sps or ([rec["supported_parameters"]] if isinstance(rec.get("supported_parameters"), dict)
                  and rec.get("supported_parameters") else [])
    if not sps:
        return None
    maxes, unknown = [], False
    for sp in sps:
        ir = sp.get("input_references")
        if ir is None or ir is False:
            maxes.append(0)                                       # the endpoint lists its parameters, not this one
            continue
        mx = ir.get("max") if isinstance(ir, dict) else None
        try:
            maxes.append(int(mx))
        except (TypeError, ValueError):
            unknown = True                                        # listed without a numeric max: it takes some
    if not maxes:
        return None if unknown else 0
    return min(maxes)                                             # an endpoint may take fewer: the smallest wins


def check_refs(model: str, n: int, where: str = "") -> None:
    """refuse (before any spend) a request with n reference images to a model that takes none, or fewer."""
    if not n:
        return
    mx = refs_max(model)
    if mx is None:
        return
    pre = f"{where}: " if where else ""
    if mx == 0:
        raise SlopError(f"{pre}{model} takes no reference images (its OpenRouter listing has no input_references), so "
                        f"the {n} reference image(s) cannot be sent; nothing was spent. Use a model that takes them "
                        "(`slop gen models --kind image` shows refs<=N, e.g. openai/gpt-image-2) with --model, or drop "
                        "the reference")
    if n > mx:
        raise SlopError(f"{pre}{model} takes at most {mx} reference image(s); this request has {n}; nothing was spent. "
                        "Send fewer references, or a model that takes more (`slop gen models --kind image`)")


def build_body(model: str, prompt: str, *, aspect_ratio: str | None = None, resolution: str | None = None,
               quality: str | None = None, n: int = 1, refs: list[str] | None = None, seed: int | None = None,
               output_format: str | None = None) -> dict:
    if not prompt or not prompt.strip():
        raise SlopError("empty prompt: pass the prompt text or --prompt-file FILE")
    b: dict = {"model": model, "prompt": prompt.strip()}
    if aspect_ratio:
        b["aspect_ratio"] = aspect_ratio
    if resolution:
        b["resolution"] = resolution
    if quality:
        b["quality"] = quality
    if n and n != 1:
        if not 1 <= n <= 10:
            raise SlopError("--n must be 1..10")
        b["n"] = n
    if seed is not None:
        b["seed"] = int(seed)
    if output_format:
        b["output_format"] = output_format
    if refs:
        if len(refs) > 16:
            raise SlopError("at most 16 reference images")
        b["input_references"] = [{"type": "image_url", "image_url": {"url": r if r.startswith(("http", "data:")) else data_url(r)}}
                                 for r in refs]
    return b


def generate(pdir: Path, *, model: str, prompt: str, out_dir: Path | None = None, out: Path | None = None,
             aspect_ratio: str | None = None, resolution: str | None = None, quality: str | None = None, n: int = 1,
             refs: list[str] | None = None, seed: int | None = None, yes: bool = False, client: OpenRouter | None = None,
             est_usd: float | None = None, meta: dict | None = None) -> dict:
    if out is None and out_dir is None:
        raise SlopError("say where the image goes: --plate NAME (plates/cands/NAME/<k>.png) or --out FILE")
    rs = resolve_refs(pdir, refs)                                 # files, URLs or PLATE[:K]; refused before any spend
    check_refs(model, len(rs))
    client = client or OpenRouter()
    est = est_usd if est_usd is not None else reg.estimate_image(model, resolution or "1K", quality, n, len(rs),
                                                                 prompt=prompt)
    ledger.check_budget(pdir, "openrouter", add_usd=est, yes=yes)
    body = build_body(model, prompt, aspect_ratio=aspect_ratio, resolution=resolution, quality=quality, n=n,
                      refs=[r["src"] for r in rs], seed=seed)
    try:
        resp = client.post("/images", body, where="images", retry_network=False)
    except ProviderError as e:
        if e.status == "unknown_outcome":                          # may have been billed: count it until checked
            ledger.record(pdir, provider="openrouter", model=model, kind="image", est_usd=est, units={"n": n, "est_usd": est},
                          status="submitted", note="unknown_outcome: check https://openrouter.ai/activity")
            raise ProviderError(str(e) + " If the activity page shows the image was made, it was billed but the file was "
                                "lost with the connection; re-run only after checking.", status=e.status, http=e.http,
                                detail=e.detail) from e
        ledger.record(pdir, provider="openrouter", model=model, kind="image", est_usd=0.0, units={"n": n, "est_usd": est},
                      status="declined" if e.status.startswith(("declined", "moderation")) else "failed", note=e.status)
        raise
    data = resp.get("data") or []
    if not data:
        raise ProviderError(f"OpenRouter returned no image (response keys: {sorted(resp)}); nothing was billed for a failed "
                            "generation — re-run, or try another model", status="error")
    usage = resp.get("usage") or {}
    real = usage.get("cost")
    side_doc = {"model": model, "prompt": body["prompt"], "aspect_ratio": aspect_ratio, "resolution": resolution,
                "quality": quality, "seed": seed, "refs": [r["id"] for r in rs], "cost_usd": real, "est_usd": est,
                **({"ref_plates": [f"{r['plate']}:{r['k']}" for r in rs if r["plate"]]} if any(r["plate"] for r in rs)
                   else {}), **(meta or {})}
    files = []
    for i, d in enumerate(data):
        raw, mime = None, d.get("media_type") or "image/png"
        if d.get("b64_json"):
            raw = base64.b64decode(d["b64_json"])
        elif d.get("url", "").startswith("data:"):
            head, b64 = d["url"].split(",", 1); raw = base64.b64decode(b64); mime = head[5:].split(";")[0] or mime
        elif d.get("url"):
            raw = client.request("GET", d["url"], auth=False, raw=True)
        if raw is None:
            continue
        ext = EXT.get(mime, mimetypes.guess_extension(mime) or ".png")
        if out is not None:
            o = Path(out)
            dst = o if len(data) == 1 else o.with_name(f"{o.stem}-{i + 1}{o.suffix or ext}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.with_suffix(".json").write_text(json.dumps(side_doc, indent=1), encoding="utf-8")
        else:
            dst = reserve(Path(out_dir), ext, side_doc)            # claims <k>.json (the sidecar) before the image
        dst.write_bytes(raw)
        files.append(dst)
    row = ledger.record(pdir, provider="openrouter", model=model, kind="image",
                        est_usd=float(real) if real is not None else est,
                        units={"n": len(files), "est_usd": est, "real_usd": real, "resolution": resolution,
                               "quality": quality, **({"refs": len(rs)} if rs else {})},
                        request_id=resp.get("id"), status="ok")
    return {"files": [str(f) for f in files], "cost_usd": real, "est_usd": est, "ledger": row,
            "refs": [r["id"] for r in rs]}


# ------------------------------------------------------------------------------------------------ batch (jobs.json)
def load_jobs(pdir: Path, path: Path) -> list[dict]:
    if not path.is_file():
        raise SlopError(f"no jobs file {path}: write it with `slop plates book` (it lists the API plate jobs), then re-run")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{path} is not valid JSON ({e}); re-write it with `slop plates book`") from e
    jobs = doc.get("jobs") if isinstance(doc, dict) else doc
    if not isinstance(jobs, list) or not jobs:
        raise SlopError(f"{path} has no jobs: the board has no API plates with written prompts (slop plates book lists them)")
    out = []
    for i, j in enumerate(jobs):
        if not isinstance(j, dict) or not j.get("plate"):
            raise SlopError(f"{path}: job {i + 1} has no 'plate' key; re-write the file with `slop plates book`")
        if j.get("refs") is not None and (not isinstance(j["refs"], list)
                                          or not all(isinstance(x, str) and x.strip() for x in j["refs"])):
            raise SlopError(f"{path}: job {j['plate']}: \"refs\" must be a list of image files, URLs or PLATE[:K] "
                            "strings; re-write the file with `slop plates book`")
        out.append(j)
    return out


def job_prompt(pdir: Path, job: dict) -> str:
    if (job.get("prompt") or "").strip():
        return job["prompt"].strip()
    pf = job.get("prompt_file")
    if pf:
        p = Path(pf) if Path(pf).is_absolute() else pdir / pf
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    raise SlopError(f"job {job.get('plate')} has no prompt (neither 'prompt' nor a readable 'prompt_file'): write the plate's "
                    "prompt on the board and re-run `slop plates book`")


ANY = object()                                                   # made_for: do not compare this setting


def _same(a, b) -> bool:
    return (a or None) == (b or None)


def _ref_set(pdir: Path, refs) -> list[str]:
    return sorted({ref_id(pdir, r) for r in refs or [] if isinstance(r, str) and r})


def made_for(pdir: Path, plate: str, prompt: str, model: str, *, quality=ANY, resolution=ANY, aspect=ANY,
             refs=ANY) -> list[Path]:
    """images in plates/cands/<plate>/ already made from this exact prompt with this model — and, when given, this
    quality, resolution, aspect ratio and set of reference images (their sidecars say so)."""
    want_refs = None if refs is ANY else _ref_set(pdir, refs)
    d = pdir / "plates" / "cands" / plate
    out = []
    if not d.is_dir():
        return out
    for side in sorted(d.glob("*.json"), key=lambda p: (len(p.stem), p.stem)):
        try:
            s = json.loads(side.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(s, dict) or s.get("model") != model or (s.get("prompt") or "").strip() != prompt.strip():
            continue
        if any(want is not ANY and not _same(s.get(k), want)
               for k, want in (("quality", quality), ("resolution", resolution), ("aspect_ratio", aspect))):
            continue
        if want_refs is not None and _ref_set(pdir, s.get("refs")) != want_refs:
            continue
        img = next((side.with_suffix(e) for e in IMG_EXTS if side.with_suffix(e).is_file()), None)
        if img:
            out.append(img)
    return out


def any_candidates(pdir: Path, plate: str) -> bool:
    d = pdir / "plates" / "cands" / plate
    return d.is_dir() and any(p.suffix.lower() in IMG_EXTS for p in d.iterdir())


def _job_refs(pdir: Path, j: dict, extra: list[str] | None, model: str) -> list[dict]:
    """a job's own "refs" + the batch's --ref, resolved, checked against the model; errors name the job and the fix.
    A job's file refs are project-relative (`plates book` writes them so): only the project's file counts, never a
    same-named one in the current folder, which may be another project's (plates/cands/lead-cu/2.jpg exists in most)."""
    try:
        own = resolve_refs(pdir, j.get("refs"), in_project=True)
    except SlopError as e:
        fix = (f"re-anchor with `{_pcmd(pdir, 'plates book --anchor PLATE:K')}` (or --no-anchor)" if j.get("anchor")
               else "fix the job's \"refs\" in the jobs file")
        raise SlopError(f"job {j['plate']}: {e}. Nothing was sent; {fix}") from None
    seen = {r["id"] for r in own}
    rs = own + [r for r in resolve_refs(pdir, extra) if r["id"] not in seen]
    check_refs(model, len(rs), where=f"job {j['plate']}" + (f" (anchored on {j['anchor']})" if j.get("anchor") else ""))
    return rs


def plan_jobs(pdir: Path, jobs: list[dict], *, only: list[str] | None = None, missing: bool = False,
              model: str | None = None, quality: str | None = None, resolution: str | None = None,
              n_refs: int = 0, refs: list[str] | None = None) -> list[dict]:
    """n_refs: kept for old callers (an estimate with that many references when the jobs carry none)."""
    proj = load_project(pdir)
    pmodel = reg.resolve(proj, "image", DEFAULT_MODEL, "image")      # the newest of its family unless pinned
    if only:
        known = {j["plate"] for j in jobs}
        bad = [o for o in only if o not in known]
        if bad:
            raise SlopError(f"--only: plate(s) not in the jobs file: {', '.join(bad)} (plates there: "
                            f"{', '.join(sorted(known)[:12])}{' …' if len(known) > 12 else ''})")
    rows = []
    taken: dict[tuple, int] = {}            # images already made, shared in file order by jobs with the same request
    for i, j in enumerate(jobs):
        plate = j["plate"]
        m = model or j.get("model") or pmodel or DEFAULT_MODEL
        q = quality or j.get("quality")
        res = resolution or j.get("resolution")
        asp = j.get("aspect") or "16:9"
        try:
            n = int(j.get("n") or 1)
        except (TypeError, ValueError):
            raise SlopError(f"job {plate}: n must be a whole number of images") from None
        row = {"job": i + 1, "plate": plate, "model": m, "quality": q, "resolution": res, "aspect": asp,
               "n": n, "done": 0, "need": 0, "other_settings": 0, "est_usd": 0.0, "skip": None}
        if only and plate not in only:
            row["skip"] = "not in --only"
        elif missing and any_candidates(pdir, plate):
            row["skip"] = "has candidates (--missing)"
        else:
            prompt = job_prompt(pdir, j)
            row["prompt"] = prompt
            rs = _job_refs(pdir, j, refs, m)
            ids = [r["id"] for r in rs]
            row["refs"], row["ref_src"] = ids, [r["src"] for r in rs]
            if j.get("anchor"):
                row["anchor"] = j["anchor"]
            key = (plate, m, prompt.strip(), q or None, res or None, asp, tuple(sorted(ids)))
            have = len(made_for(pdir, plate, prompt, m, quality=q, resolution=res, aspect=asp, refs=ids))
            row["done"] = min(n, max(0, have - taken.get(key, 0)))
            taken[key] = taken.get(key, 0) + row["done"]
            row["other_settings"] = len(made_for(pdir, plate, prompt, m)) - have
            row["need"] = max(0, n - row["done"])
            if row["need"] == 0:
                row["skip"] = f"done ({row['done']}/{n} made from this prompt at these settings)"
            else:
                if not 1 <= row["need"] <= 10:
                    raise SlopError(f"job {plate}: n={n}; one call makes 1..10 images - split it into jobs of at most 10")
                row["est_usd"] = reg.estimate_image(m, res or "1K", q, row["need"], len(rs) or n_refs, prompt=prompt)
        rows.append(row)
    return rows


def _settings(r: dict) -> str:
    return " ".join(x for x in (r.get("quality"), r.get("resolution"), r.get("aspect")) if x)


def _refs_note(r: dict) -> str:
    n = len(r.get("refs") or [])
    if not n:
        return ""
    return f" + {n} ref(s)" + (f" (anchored on {r['anchor']})" if r.get("anchor") else "")


def _ref_arg(pdir: Path, r: str) -> str:
    """a batch --ref as the command to run again spells it: a URL repaired, an image file project-relative (inside the
    project) or absolute (elsewhere), a plate candidate (PLATE:K) as given."""
    s = str(r)
    if s.startswith("data:"):
        return s
    u = _url(s)
    if u:
        return u
    p = Path(s).expanduser()
    return ref_id(pdir, str(p.resolve())) if p.is_absolute() or p.is_file() else s


def _public_row(r: dict) -> dict:
    """a plan/result row for --json: no prompt text, no absolute source paths (the ids say which images)."""
    return {k: v for k, v in r.items() if k not in ("prompt", "ref_src")}


def run_jobs(pdir: Path, jobs_file: Path, *, only: list[str] | None = None, missing: bool = False, yes: bool = False,
             model: str | None = None, quality: str | None = None, resolution: str | None = None,
             refs: list[str] | None = None, seed: int | None = None, workers: int = 4,
             client: OpenRouter | None = None) -> dict:
    jobs = load_jobs(pdir, jobs_file)
    rows = plan_jobs(pdir, jobs, only=only, missing=missing, model=model, quality=quality, resolution=resolution,
                     refs=refs)
    todo = [r for r in rows if not r["skip"]]
    total = round(sum(r["est_usd"] for r in todo), 6)
    n_img = sum(r["need"] for r in todo)
    try:
        rel_jobs = Path(jobs_file).resolve().relative_to(Path(pdir).resolve()).as_posix()
    except ValueError:
        rel_jobs = str(jobs_file)
    flags = (f" --only {','.join(only)}" if only else "") + (" --missing" if missing else "") + \
            (f" --model {model}" if model else "") + (f" --quality {quality}" if quality else "") + \
            (f" --res {resolution}" if resolution else "") + \
            "".join(f" --ref {shlex.quote(_ref_arg(pdir, r))}" for r in refs or [])
    again = _pcmd(pdir, f"gen image --jobs {rel_jobs}{flags}")
    after = f"next: {_pcmd(pdir, 'plates sheet')}, then the owner picks ({_pcmd(pdir, 'plates pick PLATE K')} …)"
    head = [f"{len(todo)} job(s), {n_img} image(s), estimate ${total:.4f}"
            + (f" ({len(rows) - len(todo)} skipped)" if len(rows) > len(todo) else "")]
    for r in rows:
        other = f"; {r['other_settings']} made at other settings, not counted" if r.get("other_settings") else ""
        head.append(f"  {r['plate']:<24} " + (f"skip: {r['skip']}{other}" if r["skip"] else
                                               f"{r['need']} image(s) {r['model']}"
                                               + (f" {_settings(r)}" if _settings(r) else "")
                                               + _refs_note(r)
                                               + f" ≈ ${r['est_usd']:.4f}"
                                               + (f" ({r['done']} already made)" if r["done"] else "") + other))
    anchored = sorted({r["plate"] for r in todo if r.get("anchor")})
    if anchored:
        head.append(f"  lead anchor: {len(anchored)} plate(s) send the approved lead image as a reference "
                    f"(input_references) with the text canon: {', '.join(anchored[:10])}"
                    + (" …" if len(anchored) > 10 else ""))
    base = {"jobs_file": rel_jobs, "jobs": [_public_row(r) for r in rows], "planned_images": n_img, "est_usd": total,
            **({"anchored": anchored} if anchored else {})}
    if not todo:
        return {**base, "dry_run": not yes, "made": [], "failed": [], "cost_usd": 0.0, "stopped": None,
                "text": "nothing to do: every job already has its images at these settings (or was skipped).\n"
                        + "\n".join(head[1:]) + "\n" + after}
    if not yes:
        warn = ""
        try:
            ledger.check_budget(pdir, "openrouter", add_usd=total, yes=True)
        except SlopError as e:
            warn = f"\n  ! this batch does not fit the budget: {e}"
        show = "plates/prompts.md" if (Path(pdir) / "plates" / "prompts.md").is_file() else f"the prompts in {rel_jobs}"
        nxt = (f"\nShow {show} and this estimate to the owner. After their explicit yes, run: {again} --yes" if not warn
               else "\nThis batch cannot run until it fits the budget: run fewer plates (--only P1,P2) or ask the owner "
                    "to raise the cap.")
        return {**base, "dry_run": True, "made": [], "failed": [], "cost_usd": 0.0, "stopped": None,
                "text": "DRY RUN - nothing was generated or spent.\n" + "\n".join(head) + warn + nxt}
    ledger.check_budget(pdir, "openrouter", add_usd=total, yes=True)        # the whole batch must fit BEFORE any call
    client = client or OpenRouter()
    stop: dict = {}

    def one(r: dict) -> dict:
        if stop:
            return {**r, "status": "not run", "error": f"batch stopped: {stop.get('why')}"}
        try:
            g = generate(pdir, model=r["model"], prompt=r["prompt"], out_dir=pdir / "plates" / "cands" / r["plate"],
                         aspect_ratio=r["aspect"], resolution=r["resolution"], quality=r["quality"], n=r["need"],
                         refs=r.get("ref_src") or None, seed=seed, yes=True, client=client, est_usd=r["est_usd"],
                         meta={"job": r["plate"], "jobs_file": rel_jobs})
            return {**r, "status": "ok", "files": g["files"], "cost_usd": g["cost_usd"]}
        except ProviderError as e:
            if e.status in STOP_BATCH:
                stop.setdefault("why", f"{r['plate']}: {e.status}")
            return {**r, "status": e.status, "error": str(e)[:400]}
        except SlopError as e:                                    # budget cap / frozen: stop everything
            stop.setdefault("why", str(e)[:200])
            return {**r, "status": "refused", "error": str(e)[:400]}

    groups: dict[str, list[dict]] = {}                            # one worker per plate: its jobs run one after another
    for r in todo:
        groups.setdefault(r["plate"], []).append(r)
    with ThreadPoolExecutor(max(1, min(int(workers or 1), 8, len(groups)))) as ex:
        ran = [x for g in ex.map(lambda rs: [one(r) for r in rs], list(groups.values())) for x in g]
    res = sorted(ran, key=lambda r: r["job"])
    made = [f for r in res for f in r.get("files") or []]
    failed = [{"plate": r["plate"], "status": r["status"], "error": r.get("error")} for r in res if r["status"] != "ok"]
    cost = round(sum(float(r.get("cost_usd") if r.get("cost_usd") is not None else r["est_usd"])
                     for r in res if r["status"] == "ok"), 6)
    lines = [f"made {len(made)} image(s) in {sum(1 for r in res if r['status'] == 'ok')}/{len(res)} job(s) "
             f"(${cost:.4f}; estimate ${total:.4f})"]
    for r in res:
        if r["status"] == "ok":
            lines.append(f"  {r['plate']:<24} ok: " + ", ".join(Path(f).name for f in r["files"])
                         + (f" (${r['cost_usd']:.4f})" if r.get("cost_usd") is not None else ""))
        else:
            lines.append(f"  {r['plate']:<24} {r['status']}: {(r.get('error') or '')[:200]}")
    err = None
    if stop:
        err = (f"STOPPED: {stop['why']}. Fix that first (the job's message says how), then re-run the same command "
               f"- it continues where it stopped: {again} --yes")
    elif failed:
        err = (f"{len(failed)} job(s) refused: reword those plates' prompts on the board ({_pcmd(pdir, 'plates book')}), "
               f"then re-run: {again} --yes (finished jobs are skipped)")
    if err:
        lines.append(err)
    if not stop:                                                  # a stopped batch has one next step: the fix above
        lines.append(after + f"; real spend: {_pcmd(pdir, 'spend')}")
    ok = err is None                                              # a partial batch exits non-zero so it is noticed
    return {**base, "ok": ok, **({} if ok else {"error": lines[0] + ". " + err}), "dry_run": False,
            "made": made, "failed": failed, "cost_usd": cost, "stopped": stop.get("why"),
            "results": [_public_row(r) for r in res], "text": "\n".join(lines)}


# ------------------------------------------------------------------------------------------------ provider hook
# `slop gen image --provider codex`: stills on the user's ChatGPT plan through the Codex CLI's built-in image tool
# (slop/gen/codex_image.py; $0 in the ledger with note "plan"; 1-4 min per image, so it runs as a `slop job`).
# The flag is added to the `gen image` parser by install_provider_flag(), which slop/agents/cli.py calls when it
# registers (it loads after slop/gen/cli.py); without it, `gen image` is the OpenRouter path exactly as above.
PROVIDERS = ("openrouter", "codex")


def install_provider_flag(sub) -> bool:
    """Add --provider openrouter|codex to `slop gen image` (idempotent; False when there is no gen image parser)."""
    import argparse
    gen = getattr(sub, "choices", {}).get("gen")
    acts = [a for a in getattr(gen, "_actions", []) if isinstance(a, argparse._SubParsersAction)]
    p = acts[0].choices.get("image") if acts else None
    if p is None or any("--provider" in a.option_strings for a in p._actions):
        return False
    p.add_argument("--provider", choices=PROVIDERS, default=None,
                   help="openrouter (pay per image) | codex (EXPERIMENTAL, not yet checked with a real plan: the user's "
                        "ChatGPT plan via the Codex CLI: $0, 1-4 min per image, runs as a background job; needs `slop "
                        "agents login codex`). Default: openrouter, or codex after `slop agents use codex --for images`")
    orig = p.get_default("func")

    def func(a):
        prov = getattr(a, "provider", None)
        note = None
        if prov is None:
            prov = preferred_provider(a)
            if prov == "codex":
                note = ("provider codex from `slop agents use codex --for images` (the ChatGPT plan; experimental); "
                        "--provider openrouter uses the API models")
                a.provider = "codex"
        if prov == "codex":
            from . import codex_image
            r = codex_image.cmd_image(a)
            if note and isinstance(r, dict):
                r["provider_note"] = note
                r["text"] = f"{r.get('text', '')}\n({note})"
            return r
        return orig(a)
    p.set_defaults(func=func)
    return True


def preferred_provider(a) -> str | None:
    """The user's images agent (`slop agents use codex --for images`, kept in $SLOP_HOME/onboard.json), when the
    command names no OpenRouter-only setting (--model, --res, --quality, --seed pick the API path)."""
    if any(getattr(a, k, None) not in (None, "") for k in ("model", "res", "quality", "seed")):
        return None
    try:
        from ..agents.prefs import get_use
        return "codex" if get_use().get("images") == "codex" else None
    except Exception:  # noqa: BLE001 - a broken onboard.json must not break the OpenRouter path
        return None
