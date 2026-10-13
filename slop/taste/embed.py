"""Image (and text) embeddings for the taste model (``slop taste embed``).

Providers
  local       SigLIP 2 base, `google/siglip2-base-patch16-naflex` (licence: Apache-2.0), CPU via transformers.
              NaFlex keeps each image's aspect ratio (no crop: a poster's composition survives). Ported from the
              retired feed/embed.py: PIL draft to 1024, `max_num_patches=576`, vision pooler output, L2-normalised,
              stored float16. The retired feed used so400m on a GPU; research 11-gap-5 §6.2 measured base-size on CPU
              at 78.7 % held-out vs 82.0 % for so400m (inside the ±5 margin) at ~0.35 s/image on 8 threads, so base
              is the portable default. Text vectors come from the same checkpoint's text tower (same space), used
              for the style-vocabulary probes, mood-board queries and the text-free check.
  openrouter  `POST https://openrouter.ai/api/v1/embeddings` with `image_url` content parts (needs
              OPENROUTER_API_KEY). Default model `nvidia/llama-nemotron-embed-vl-1b-v2:free` ($0, 20 req/min);
              `voyageai/voyage-multimodal-3.5` or `google/gemini-embedding-2` are paid alternatives. Every call is
              ledgered (slop.ledger) and budget-checked first — image AND text calls (review round 1: text
              batches for `tokens` / `board` used to spend unchecked with a paid --model); `--yes` passes the
              confirm gate.

Rules (research 11-gap-5 §6.3): one user uses ONE model forever — vectors from different models are not comparable,
so a project's store refuses a different model unless --reembed. Vectors are cached per image (by the sha1 of the
normalised JPEG) under $SLOP_HOME/cache/embed/<tag>/, so re-adding an image or reusing a pool in another project
costs nothing. Hosted APIs get display-size images (long side <= 1024), never originals.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from ..config import SlopError, cache_dir, slop_home
from . import net
from .pool import image_path, load_pool
from .store import emb_dir, read_json, write_json

LOCAL_MODEL = "google/siglip2-base-patch16-naflex"   # Apache-2.0
LOCAL_LICENCE = "Apache-2.0"
PATCHES = 576
BATCH = 8
OR_URL = "https://openrouter.ai/api/v1/embeddings"
OR_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2:free"
OR_FREE_INTERVAL = 3.2       # :free models allow 20 requests/minute
OR_EST_USD_PER_IMAGE = 0.001  # conservative estimate for paid multimodal embedders (voyage: $0.60 per 1e9 px)
OR_EST_USD_PER_TEXT = 0.0002  # conservative estimate per short phrase (a few tokens) for paid embedders
SAVE_EVERY = 64


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def tag_for(provider: str, model: str, patches: int = PATCHES) -> str:
    safe = "".join(c if c.isalnum() or c in "-." else "-" for c in model.split("/")[-1])
    return f"{provider}-{safe}" + (f"-p{patches}" if provider == "local" else "")


def local_available() -> bool:
    try:
        import importlib.util
        return bool(importlib.util.find_spec("torch") and importlib.util.find_spec("transformers"))
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------- providers

class LocalSiglip:
    provider = "local"

    def __init__(self, model: str | None = None, patches: int = PATCHES, threads: int | None = None):
        self.model = model or LOCAL_MODEL
        self.patches = int(patches)
        self.threads = threads
        self.tag = tag_for("local", self.model, self.patches)
        self._m = None
        self._p = None
        self.calib = None

    def _load(self):
        if self._m is not None:
            return
        os.environ.setdefault("HF_HOME", str(slop_home() / "cache" / "hf"))   # = bin/setup.sh
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            import torch
            import transformers
            from transformers import AutoModel, AutoProcessor
        except ImportError as e:
            raise SlopError("local embeddings need torch + transformers (run bin/setup.sh), or use "
                            "--provider openrouter") from e
        transformers.logging.set_verbosity_error()
        if self.threads:
            torch.set_num_threads(int(self.threads))
        _log(f"loading {self.model} on CPU (first run downloads ~1.5 GB into $HF_HOME)…")
        try:
            self._m = AutoModel.from_pretrained(self.model, dtype=torch.float32).eval()
            self._p = AutoProcessor.from_pretrained(self.model)
        except Exception as e:  # noqa: BLE001 — network / cache errors come in many types
            raise SlopError(f"could not load {self.model} ({type(e).__name__}: {str(e)[:200]}). Check that "
                            "huggingface.co is reachable, or use --provider openrouter") from e
        try:
            self.calib = {"scale": float(self._m.logit_scale.detach().exp()), "bias": float(self._m.logit_bias.detach())}
        except AttributeError:
            self.calib = None

    def _open(self, p):
        from PIL import Image
        im = Image.open(p)
        im.draft("RGB", (1024, 1024))
        return im.convert("RGB")

    def embed_images(self, paths: list[Path]) -> list[np.ndarray | None]:
        import torch
        self._load()
        try:
            ims = [self._open(p) for p in paths]
            x = self._p.image_processor(images=ims, return_tensors="pt", max_num_patches=self.patches)
            with torch.no_grad():
                f = self._m.vision_model(**x).pooler_output
            f = torch.nn.functional.normalize(f.float(), dim=-1).numpy()
            return [v for v in f]
        except Exception:  # noqa: BLE001 — one bad file must not kill the batch: retry one by one
            if len(paths) == 1:
                return [None]
            return [self.embed_images([p])[0] for p in paths]

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        import torch
        self._load()
        vs = []
        with torch.no_grad():
            for s in range(0, len(texts), 16):
                t = self._p.tokenizer([x.lower() for x in texts[s:s + 16]], padding="max_length", max_length=64,
                                      truncation=True, return_tensors="pt")
                f = self._m.text_model(**t).pooler_output
                vs.append(torch.nn.functional.normalize(f.float(), dim=-1).numpy())
        return np.concatenate(vs) if vs else np.zeros((0, 768), "float32")


class OpenRouterEmbedder:
    provider = "openrouter"

    def __init__(self, model: str | None = None, pdir: Path | None = None, sleep=time.sleep, yes: bool = False):
        from ..config import require_env
        self.model = model or OR_MODEL
        self.yes = yes        # the owner confirmed a paid run over confirm_over_usd (--yes)
        self.tag = tag_for("openrouter", self.model)
        self.pdir = pdir
        self.sleep = sleep
        self.key = require_env("OPENROUTER_API_KEY", "needed for --provider openrouter embeddings")
        self._last = 0.0
        self.calib = None
        self.spent = 0.0

    def est_usd(self, n_images: int = 0, n_texts: int = 0) -> float:
        if self.model.endswith(":free"):
            return 0.0
        return round(n_images * OR_EST_USD_PER_IMAGE + n_texts * OR_EST_USD_PER_TEXT, 4)

    def _post(self, inputs: list, kind: str, units: dict) -> list[np.ndarray]:
        from .. import ledger
        est = self.est_usd(units.get("images", 0), units.get("texts", 0))
        if est > 0 and self.pdir is not None:   # every paid call: budget cap + confirm gate BEFORE the spend
            ledger.check_budget(self.pdir, "openrouter", add_usd=est, yes=self.yes)
        elif est > 0:                           # no project to budget against: the spend lock still holds
            ledger.assert_spend_allowed("openrouter")
        if self.model.endswith(":free"):
            wait = self._last + OR_FREE_INTERVAL - time.monotonic()
            if wait > 0:
                self.sleep(wait)
        payload = {"model": self.model, "input": inputs, "encoding_format": "float"}
        for attempt in range(4):
            self._last = time.monotonic()
            try:
                st, h, body = net.http_post_json(OR_URL, payload, headers={"Authorization": f"Bearer {self.key}"})
            except OSError as e:
                if attempt == 3:
                    raise SlopError(f"cannot reach openrouter.ai ({e}); re-run later") from e
                self.sleep(2 ** (attempt + 1))
                continue
            try:
                d = json.loads(body.decode("utf-8")) if body else {}
            except ValueError:
                d = {}
            if st == 429 or st >= 500:
                self.sleep(min(60, 5 * 2 ** attempt))
                continue
            if st != 200 or "data" not in d:
                msg = ((d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error")) or ""
                ledger.record(self.pdir, provider="openrouter", model=self.model, kind=f"embed-{kind}",
                              est_usd=0.0, units=units, status="failed", note=f"HTTP {st} {str(msg)[:120]}")
                if st == 402:
                    raise SlopError("OpenRouter says the key is out of credits (402); top up or use --provider local")
                if st in (401, 403):
                    raise SlopError("OpenRouter rejected OPENROUTER_API_KEY (401/403); ask the user for a valid key")
                raise SlopError(f"OpenRouter embeddings failed (HTTP {st}: {str(msg)[:200]}); try another --model")
            usage = d.get("usage") or {}
            cost = float(usage.get("cost") or 0.0)
            self.spent += cost
            ledger.record(self.pdir, provider="openrouter", model=self.model, kind=f"embed-{kind}",
                          est_usd=cost if cost else est, units=units,
                          request_id=d.get("id"), status="ok")
            rows = sorted(d["data"], key=lambda r: r.get("index", 0))
            vs = []
            for r in rows:
                v = np.asarray(r.get("embedding") or [], dtype="float32")
                n = float(np.linalg.norm(v))
                vs.append(v / n if n > 0 else v)
            return vs
        raise SlopError("OpenRouter kept rate-limiting the embeddings request; wait a minute and re-run")

    def embed_images(self, paths: list[Path]) -> list[np.ndarray | None]:
        inputs = []
        for p in paths:
            b64 = base64.b64encode(Path(p).read_bytes()).decode("ascii")
            inputs.append({"content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]})
        vs = self._post(inputs, "image", {"images": len(paths)})
        return list(vs) + [None] * (len(paths) - len(vs))

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        vs = []
        for s in range(0, len(texts), 32):
            vs += self._post(list(texts[s:s + 32]), "text", {"texts": len(texts[s:s + 32])})
        return np.stack(vs) if vs else np.zeros((0, 1), "float32")


def make_embedder(provider: str = "auto", model: str | None = None, patches: int = PATCHES,
                  pdir: Path | None = None, threads: int | None = None, yes: bool = False):
    if provider == "auto":
        provider = "local" if local_available() else ("openrouter" if os.environ.get("OPENROUTER_API_KEY") else "")
        if not provider:
            raise SlopError("no embedding provider: install torch + transformers (bin/setup.sh) for local SigLIP 2, "
                            "or set OPENROUTER_API_KEY and pass --provider openrouter")
    if provider == "local":
        return LocalSiglip(model, patches, threads)
    if provider == "openrouter":
        return OpenRouterEmbedder(model, pdir, yes=yes)
    raise SlopError(f"unknown --provider {provider} (use local or openrouter)")


# ---------------------------------------------------------------- the project's vector store

def store_paths(pdir: Path, root: Path | None = None) -> tuple[Path, Path]:
    d = Path(root) / "emb" if root is not None else emb_dir(pdir)
    return d / "vectors.npz", d / "meta.json"


def load_store(pdir: Path, root: Path | None = None) -> tuple[list[str], np.ndarray, dict]:
    vp, mp = store_paths(pdir, root)
    meta = read_json(mp, {}) or {}
    if not vp.exists():
        return [], np.zeros((0, int(meta.get("dim") or 0)), "float32"), meta
    try:
        z = np.load(vp, allow_pickle=False)
        ids = [str(x) for x in z["ids"].tolist()]
        X = z["vecs"].astype("float32")
    except Exception:  # noqa: BLE001 — a torn file: treat as empty, the next embed rewrites it
        return [], np.zeros((0, int(meta.get("dim") or 0)), "float32"), meta
    return ids, X, meta


def save_store(pdir: Path, ids: list[str], X: np.ndarray, meta: dict) -> None:
    vp, mp = store_paths(pdir)
    tmp = vp.with_name(f"vectors.tmp{os.getpid()}.npz")
    np.savez(tmp, ids=np.array(ids), vecs=np.asarray(X, dtype="float16"))
    os.replace(tmp, vp)
    write_json(mp, meta)


def _cache_file(tag: str, sha: str) -> Path:
    d = cache_dir("embed") / tag / sha[:2]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{sha}.npy"


def check_model(meta: dict, emb, reembed: bool) -> None:
    if meta.get("tag") and meta["tag"] != emb.tag and not reembed:
        raise SlopError(f"this project's taste vectors were made with {meta.get('provider')}:{meta.get('model')} "
                        f"and vectors from different models are not comparable. Re-run with --provider "
                        f"{meta.get('provider')} --model {meta.get('model')}, or pass --reembed to re-embed every "
                        f"image with {emb.provider}:{emb.model}")


def embed_pool(pdir: Path, provider: str = "auto", model: str | None = None, patches: int = PATCHES,
               reembed: bool = False, yes: bool = False, embedder=None, log=_log, threads: int | None = None) -> dict:
    """embed every pool image that has no vector yet (idempotent). Returns counts."""
    pdir = Path(pdir)
    items = load_pool(pdir)
    ids, X, meta = load_store(pdir)
    if embedder is None and provider == "auto" and meta.get("provider") and not reembed:
        provider, model = meta["provider"], model or meta.get("model")
        patches = int(meta.get("patches") or patches)
    emb = embedder or make_embedder(provider, model, patches, pdir, threads, yes=yes)
    if yes and getattr(emb, "provider", "") == "openrouter":
        emb.yes = True
    check_model(meta, emb, reembed)
    if reembed and meta.get("tag") != emb.tag:
        ids, X = [], np.zeros((0, 0), "float32")
    have = set(ids)
    todo = [it for i, it in items.items() if i not in have and image_path(pdir, it).exists()]
    out = {"pool": len(items), "embedded_before": len(have & set(items)), "todo": len(todo), "cached": 0,
           "computed": 0, "failed": 0, "provider": emb.provider, "model": emb.model, "tag": emb.tag}
    if not todo:
        out["embedded"] = out["embedded_before"]
        return out
    if emb.provider == "openrouter":
        from ..ledger import check_budget
        est = emb.est_usd(len(todo))
        if est > 0:
            check_budget(pdir, "openrouter", add_usd=est, yes=yes)
        out["est_usd"] = est
    new_ids, new_vecs = [], []
    # per-image cache first
    rest = []
    for it in todo:
        cf = _cache_file(emb.tag, it.get("sha1") or it["id"])
        if cf.exists():
            try:
                new_ids.append(it["id"])
                new_vecs.append(np.load(cf).astype("float32"))
                out["cached"] += 1
                continue
            except Exception:  # noqa: BLE001
                new_ids.pop()
        rest.append(it)
    base_meta = {"provider": emb.provider, "model": emb.model, "tag": emb.tag,
                 "patches": patches if emb.provider == "local" else None,
                 "licence": LOCAL_LICENCE if emb.provider == "local" else "provider terms"}

    def flush():
        if not new_ids:
            return
        V = np.stack(new_vecs)
        allX = V if not len(ids) else np.concatenate([X.astype("float32"), V])
        m = dict(meta) if meta.get("tag") == emb.tag else {}
        m.update(base_meta)
        m["dim"] = int(allX.shape[1])
        if getattr(emb, "calib", None):
            m["calib"] = emb.calib
        m["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        save_store(pdir, ids + new_ids, allX, m)

    t0 = time.monotonic()
    for s in range(0, len(rest), BATCH):
        part = rest[s:s + BATCH]
        vs = emb.embed_images([image_path(pdir, it) for it in part])
        for it, v in zip(part, vs):
            if v is None:
                out["failed"] += 1
                continue
            v = np.asarray(v, dtype="float32")
            np.save(_cache_file(emb.tag, it.get("sha1") or it["id"]), v.astype("float16"))
            new_ids.append(it["id"])
            new_vecs.append(v)
            out["computed"] += 1
        done = s + len(part)
        if done % SAVE_EVERY < BATCH or done == len(rest):
            flush()   # partial progress becomes visible to a running tap server
            log(f"embedded {done}/{len(rest)} ({done / max(time.monotonic() - t0, 1e-6):.2f} img/s)")
    flush()
    out["embedded"] = out["embedded_before"] + len(new_ids)
    out["seconds"] = round(time.monotonic() - t0, 1)
    if getattr(emb, "spent", 0):
        out["real_usd"] = round(emb.spent, 5)
    return out


def text_embedder_for(meta: dict, pdir: Path | None = None, yes: bool = False):
    """an embedder that matches the store's model (text probes must live in the image vectors' space); a paid
    OpenRouter model is budget-checked before every call (`yes` = the owner confirmed a run over the threshold)"""
    if not meta.get("provider"):
        raise SlopError("no taste vectors yet: run `slop taste embed` first")
    if meta["provider"] == "local":
        return LocalSiglip(meta.get("model"), int(meta.get("patches") or PATCHES))
    return OpenRouterEmbedder(meta.get("model"), pdir, yes=yes)


def text_vectors(meta: dict, phrases: list[str], embedder=None, pdir: Path | None = None, yes: bool = False) -> np.ndarray:
    """text vectors in the store's space, cached per phrase under $SLOP_HOME/cache/embed/<tag>/text.npz"""
    tag = meta.get("tag")
    if not tag:
        raise SlopError("no taste vectors yet: run `slop taste embed` first")
    cf = cache_dir("embed") / tag / "text.npz"
    cache: dict[str, np.ndarray] = {}
    if cf.exists():
        try:
            z = np.load(cf, allow_pickle=False)
            cache = dict(zip([str(p) for p in z["phrases"].tolist()], z["vecs"].astype("float32")))
        except Exception:  # noqa: BLE001
            cache = {}
    new = [p for p in dict.fromkeys(phrases) if p not in cache]
    if new:
        emb = embedder or text_embedder_for(meta, pdir, yes=yes)
        V = emb.embed_texts(new)
        for p, v in zip(new, V):
            cache[p] = np.asarray(v, dtype="float32")
        cf.parent.mkdir(parents=True, exist_ok=True)
        tmp = cf.with_name(f"text.tmp{os.getpid()}.npz")
        np.savez(tmp, phrases=np.array(list(cache)), vecs=np.stack(list(cache.values())).astype("float32"))
        os.replace(tmp, cf)
    return np.stack([cache[p] for p in phrases]) if phrases else np.zeros((0, int(meta.get("dim") or 1)), "float32")
