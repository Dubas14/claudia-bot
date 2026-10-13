"""Clip files: clips/<id>.json (ARCHITECTURE §4.6) and clips/<id>/ (takes, start frames, provider request files).

One file per clip is the unit of spend and sync. Paths inside a clip file are project-relative POSIX paths when the file
lives inside the project (portable between the box and a laptop), absolute otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from ..config import SlopError

CLIP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
STATUSES = ("draft", "locked", "submitted", "delivered", "declined", "failed")
# take statuses: submitted | requested | pending | delivered | failed | declined | unknown (the submit got no clear
# answer: counted as spent, blocks a resubmit until it is attached with --job-id or abandoned with --resubmit-unknown) |
# abandoned


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def clips_dir(pdir: Path) -> Path:
    d = pdir / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clip_file(pdir: Path, cid: str) -> Path:
    if not CLIP_ID_RE.match(cid or ""):
        raise SlopError(f"bad clip id {cid!r}: use letters, digits, '-', '_' or '.' (e.g. W01, M-s012, W01-c1)")
    return clips_dir(pdir) / f"{cid}.json"


def clip_folder(pdir: Path, cid: str) -> Path:
    d = clips_dir(pdir) / cid
    d.mkdir(parents=True, exist_ok=True)
    return d


def exists(pdir: Path, cid: str) -> bool:
    return clip_file(pdir, cid).is_file()


def load(pdir: Path, cid: str) -> dict:
    p = clip_file(pdir, cid)
    if not p.is_file():
        raise SlopError(f"no clip {cid!r} in {p.parent} — create it with: slop clip new SHOT --kind sung|motion "
                        "(list clips with: slop clip list)")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{p} is not valid JSON ({e}); fix or delete it") from e


def save(pdir: Path, clip: dict) -> Path:
    p = clip_file(pdir, clip["id"])
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(clip, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


def all_clips(pdir: Path) -> list[dict]:
    out = []
    d = pdir / "clips"
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(c, dict) and c.get("id"):
            out.append(c)
    return sorted(out, key=lambda c: (c.get("song_t0") or 0.0, c["id"]))


def rel(pdir: Path, path: Path | str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    try:
        return p.resolve().relative_to(pdir.resolve()).as_posix()
    except ValueError:
        return str(p.resolve())


def absp(pdir: Path, s: str | None) -> Path | None:
    if not s:
        return None
    p = Path(s)
    return p if p.is_absolute() else pdir / p


def take_path(pdir: Path, cid: str, n: int) -> Path:
    return clip_folder(pdir, cid) / f"take-{n}.mp4"


def is_rejected(take: dict) -> bool:
    return bool(take.get("rejected")) or (take.get("qa") or {}).get("verdict") == "reject"


def latest_synced_take(clip: dict) -> dict | None:
    for tk in reversed(clip.get("takes") or []):
        if tk.get("sync") and not is_rejected(tk):
            return tk
    return None


def unknown_take(clip: dict) -> dict | None:
    """the take whose submit got no clear answer (status "unknown": it may or may not have been accepted)."""
    for tk in reversed(clip.get("takes") or []):
        if tk.get("status") == "unknown":
            return tk
    return None


def latest_delivered_take(clip: dict) -> dict | None:
    for tk in reversed(clip.get("takes") or []):
        if tk.get("status") == "delivered" and tk.get("file") and not is_rejected(tk):
            return tk
    return None


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_sha1(path: Path) -> str:
    """hash of the decoded pixels (the same frame re-encoded still matches)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGB")
            if max(im.size) > 512:
                im = im.resize((max(1, im.width // 8), max(1, im.height // 8)))
            return hashlib.sha1(im.tobytes()).hexdigest()
    except Exception:
        return file_sha1(path)


def used_starts(pdir: Path, exclude: str | None = None) -> dict[str, str]:
    """{start-image pixel hash: clip id} and {"take@frame": clip id} for every clip (two clips never share a start)."""
    used: dict[str, str] = {}
    for c in all_clips(pdir):
        if c["id"] == exclude:
            continue
        if c.get("start_sha1"):
            used[c["start_sha1"]] = c["id"]
        sf = c.get("start_frame") or {}
        if sf.get("take_file") is not None and sf.get("frame") is not None:
            used[f"{sf['take_file']}@{sf['frame']}"] = c["id"]
    return used
