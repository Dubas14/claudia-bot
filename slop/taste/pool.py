"""The reference pool: the images the tap feed shows (``slop taste pool add|list``).

Sources (research 11-gap-5 §6.5 — a compliant pool is the user's OWN curation, never a crawl):
  --arena SLUG     the user's own or followed Are.na channels (see arena.py; <= 600 blocks, <= 30 req/min)
  --dir DIR        a folder of references (screenshots, saved posts, exports, kept generations, own work)
  --urls FILE      one image URL per line (the user's own links)
  --starter        the generated cold-start deck (starter.py) for a user with no references yet
Each item records a `group` (dir:<folder>, url:<host>, starter:<template>; Are.na items have `channel`) so the
tokens' anti-source statistic works for every source (review round 1).

Every image is normalised the way the retired crawler did (tools/arena/crawl.py constants, kept): decode, EXIF
transpose, RGB, skip if the long side < 300 px, resize the long side to <= 1024 px (LANCZOS), JPEG q85.
Dedupe: exact (sha1 of the normalised JPEG) and near (64-bit dHash, Hamming <= 4, plus a matching 4x4 colour
thumbnail) at add time; re-posts that
survive both (re-crops, re-colours) are filtered at serve time by embedding cosine > 0.93 (feed policy).
Re-running the same add is idempotent (everything already present is reported as a duplicate).
"""
from __future__ import annotations

import hashlib
import io
import re
import time
from pathlib import Path

from ..config import SlopError
from . import net
from .store import append_jsonl, images_dir, now_iso, pool_index, read_jsonl

MIN_LONG_SIDE = 300      # crawl.py: skip long side < 300 px
MAX_LONG_SIDE = 1024     # crawl.py: resize to long side <= 1024 (LANCZOS)
JPEG_QUALITY = 85        # crawl.py
DHASH_NEAR = 4           # Hamming bits on a 64-bit dHash: re-encodes / light re-crops of one image
NEAR_RGB = 14            # ... and a 4x4 colour thumbnail within 14/255 on average (same structure, other colours = new)
MAX_DOWNLOAD = 25 * 1024 * 1024
DOWNLOAD_INTERVAL = 0.5  # politeness between image downloads (crawl.py paced CDN downloads too)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
KINDS = ("human", "generated")


def load_pool(pdir: Path, root: Path | None = None) -> dict[str, dict]:
    """{id: item}, in insertion order; the last row per id wins; rows with "removed" drop the id. `root`: read
    this taste profile root instead of the project's current one (a Feed keeps the root it started with)"""
    out: dict[str, dict] = {}
    for r in read_jsonl(Path(root) / "pool" / "pool.jsonl" if root is not None else pool_index(pdir)):
        i = r.get("id")
        if not i:
            continue
        if r.get("removed"):
            out.pop(i, None)
            continue
        out[i] = r
    return out


def image_path(pdir: Path, item: dict) -> Path:
    return images_dir(pdir) / f"{item['id']}.jpg"


def normalize(data: bytes):
    """bytes -> (PIL RGB image with long side <= 1024, jpeg bytes). Raises ValueError on undecodable / too small."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001 — PIL raises many types
        raise ValueError(f"not a readable image ({type(e).__name__})") from e
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa: BLE001
        pass
    if im.mode != "RGB":
        im = im.convert("RGBA").convert("RGB") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
    w, h = im.size
    if max(w, h) < MIN_LONG_SIDE:
        raise ValueError(f"too small ({w}x{h}; the long side must be >= {MIN_LONG_SIDE} px)")
    if max(w, h) > MAX_LONG_SIDE:
        s = MAX_LONG_SIDE / float(max(w, h))
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_QUALITY)
    return im, buf.getvalue()


def dhash(im) -> int:
    """64-bit difference hash of a 9x8 greyscale thumbnail"""
    import numpy as np
    g = np.asarray(im.convert("L").resize((9, 8)), dtype=int)
    v = 0
    for bit in (g[:, :-1] > g[:, 1:]).ravel():
        v = (v << 1) | int(bit)
    return v


def thumb(im) -> str:
    """4x4 RGB thumbnail as hex: dHash ignores colour, so near-duplicates must also match in colour"""
    return im.convert("RGB").resize((4, 4)).tobytes().hex()


def _thumb_close(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    x, y = bytes.fromhex(a), bytes.fromhex(b)
    return sum(abs(p - q) for p, q in zip(x, y)) / max(1, len(x)) < NEAR_RGB


def project_keys(source_url: str | None) -> list[str]:
    """same-project keys (the feed's re-post rule): one Behance gallery / Instagram post is one project whatever the
    cosine; one source page needs cosine >= 0.6 (applied in feed.py)"""
    if not source_url:
        return []
    keys = []
    m = re.search(r"behance\.net/gallery/(\d+)", source_url)
    if m:
        keys.append("behance:" + m.group(1))
    m = re.search(r"instagram\.com/(?:p|reel)/([A-Za-z0-9_-]+)", source_url)
    if m:
        keys.append("ig:" + m.group(1))
    page = source_url.split("#")[0].split("?")[0].rstrip("/")
    if page.startswith("http"):
        keys.append("page:" + page[:200])
    return keys


class PoolWriter:
    """adds normalised images to the pool with exact + near dedupe; reusable across sources in one command"""

    def __init__(self, pdir: Path, kind: str = "human"):
        if kind not in KINDS:
            raise SlopError(f"--kind must be one of {', '.join(KINDS)}")
        self.pdir = Path(pdir)
        self.kind = kind
        self.items = load_pool(pdir)
        self.sha = {it.get("sha1") for it in self.items.values()}
        self.hashes = [(int(it["dhash"], 16), it.get("thumb")) for it in self.items.values() if it.get("dhash")]
        self.stats = {"added": 0, "duplicate": 0, "near_duplicate": 0, "skipped": 0, "errors": []}

    def __len__(self) -> int:
        return len(self.items)

    def known_id(self, iid: str) -> bool:
        return iid in self.items

    def add(self, data: bytes, meta: dict, iid: str | None = None) -> str | None:
        try:
            im, jpg = normalize(data)
        except ValueError as e:
            self.stats["skipped"] += 1
            if len(self.stats["errors"]) < 20:
                self.stats["errors"].append(f"{meta.get('origin', '?')}: {e}")
            return None
        sha = hashlib.sha1(jpg).hexdigest()
        if sha in self.sha or (iid and iid in self.items):
            self.stats["duplicate"] += 1
            return None
        dh, th = dhash(im), thumb(im)
        if any(bin(dh ^ h).count("1") <= DHASH_NEAR and _thumb_close(th, t) for h, t in self.hashes):
            self.stats["near_duplicate"] += 1
            return None
        iid = iid or f"img-{sha[:12]}"
        (images_dir(self.pdir) / f"{iid}.jpg").write_bytes(jpg)
        item = {"id": iid, "kind": meta.get("kind", self.kind), "src": meta.get("src", "dir"), "w": im.width,
                "h": im.height, "sha1": sha, "dhash": f"{dh:016x}", "thumb": th, "added": now_iso()}
        for k in ("title", "source_url", "channel", "block_id", "origin", "image_url", "group"):
            if meta.get(k):
                item[k] = str(meta[k])[:500]
        keys = project_keys(meta.get("source_url"))
        if keys:
            item["keys"] = keys
        append_jsonl(pool_index(self.pdir), item)
        self.items[iid] = item
        self.sha.add(sha)
        self.hashes.append((dh, th))
        self.stats["added"] += 1
        return iid


def add_dir(writer: PoolWriter, d: str | Path, limit: int | None = None) -> dict:
    d = Path(d).expanduser()
    if not d.is_dir():
        raise SlopError(f"--dir {d} is not a folder")
    files = sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    if not files:
        raise SlopError(f"no images (.jpg/.png/.webp/.gif) found under {d}")
    n0 = writer.stats["added"]
    for p in files:
        if limit is not None and writer.stats["added"] - n0 >= limit:
            break
        try:
            data = p.read_bytes()
        except OSError as e:
            writer.stats["errors"].append(f"{p}: {e}")
            continue
        rel = p.parent.relative_to(d).as_posix()
        group = f"dir:{d.name}" + ("" if rel in ("", ".") else f"/{rel}")
        writer.add(data, {"src": "dir", "origin": str(p.name), "title": p.stem, "group": group})
    return {"files": len(files)}


def add_urls(writer: PoolWriter, url_file: str | Path, limit: int | None = None, sleep=time.sleep) -> dict:
    f = Path(url_file).expanduser()
    if not f.is_file():
        raise SlopError(f"--urls {f} is not a file (one image URL per line)")
    urls = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            if not re.match(r"^https?://", line):
                writer.stats["errors"].append(f"not an http(s) URL: {line[:80]}")
                continue
            urls.append(line)
    n0 = writer.stats["added"]
    for k, u in enumerate(urls):
        if limit is not None and writer.stats["added"] - n0 >= limit:
            break
        if k:
            sleep(DOWNLOAD_INTERVAL)
        data = download(u, writer.stats)
        if data is not None:
            from urllib.parse import urlparse
            writer.add(data, {"src": "url", "origin": u, "source_url": u, "image_url": u,
                              "group": "url:" + urlparse(u).netloc.lower()})
    return {"urls": len(urls)}


def download(url: str, stats: dict, headers: dict | None = None) -> bytes | None:
    try:
        status, h, body = net.http_get(url, headers=headers, timeout=45)
    except OSError as e:
        stats["skipped"] += 1
        stats["errors"].append(f"{url[:80]}: network error {e}")
        return None
    if status != 200:
        stats["skipped"] += 1
        stats["errors"].append(f"{url[:80]}: HTTP {status}")
        return None
    if len(body) > MAX_DOWNLOAD:
        stats["skipped"] += 1
        stats["errors"].append(f"{url[:80]}: larger than {MAX_DOWNLOAD // 2**20} MB")
        return None
    return body


def summary(pdir: Path, vec_ids: set[str] | None = None, tapped: set[str] | None = None) -> dict:
    items = load_pool(pdir)
    by_src: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for it in items.values():
        by_src[it.get("src", "?")] = by_src.get(it.get("src", "?"), 0) + 1
        by_kind[it.get("kind", "human")] = by_kind.get(it.get("kind", "human"), 0) + 1
    out = {"images": len(items), "by_source": by_src, "by_kind": by_kind}
    if vec_ids is not None:
        out["embedded"] = sum(1 for i in items if i in vec_ids)
    if tapped is not None:
        out["tapped"] = sum(1 for i in items if i in tapped)
    return out
