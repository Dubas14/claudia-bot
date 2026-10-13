"""Paths and append-only logs of the taste data, and where that data lives (the taste PROFILE).

Profiles (taste-profile track): the taste data — pool, vectors, taps, model, meter, font A/B — belongs to the USER,
not to one song. By default a project links to the user profile in ``$SLOP_HOME/taste/``, so the second project starts
with the first project's taps and meter. A project can keep its own data instead (``slop taste use --profile
project``, optionally ``--fork`` = start from a copy of the user profile). The link is ``<project>/taste/profile.json``
``{"profile": "user"|"project", ...}``:
  * `taste_dir(pdir)` = the profile ROOT holding the data below (``$SLOP_HOME/taste`` or ``<project>/taste``);
  * `project_taste_dir(pdir)` = ``<project>/taste`` — always the project's own folder: the link, taste-tokens.json,
    look-bible.md, boards/, verdicts.jsonl (the project's verdicts), applied.json;
  * no link file (library calls, old projects) = ``<project>/taste`` (the layout before profiles); the CLI writes the
    default link on first use (`ensure_link`): user, unless the project already holds its own taste data;
  * a server process pins its root at start (`pin_root`), so changing the link never redirects a running tap app.

Layout of a profile root (``taste_dir(pdir)``)::

    pool/pool.jsonl          one row per reference image (last row per id wins; {"id", "removed": true} drops it)
    pool/images/<id>.jpg     the image, RGB JPEG q85, long side <= 1024 px
    emb/vectors.npz          {ids, vecs float16 L2-normalised}  +  emb/meta.json {provider, model, tag, dim, ...}
    taps.jsonl               feed events (schema below), append-only; undo = {"undo": eid}
    model.npz / model.json   the fitted feed model (slop taste fit)
    meter.jsonl              held-out meter history (slop taste meter)
    stats.json               per-image colour/composition statistics cache (slop taste tokens)
    taste-tokens.json        machine-readable taste tokens; look-bible.md = the human suggestion + questions
    boards/<slug>/           mood boards (board.json, board.jpg, refs.json)
    fonts/                   font A/B: session.json, taps.jsonl, ranking.json, frame.jpg
    server.json / server.log the running tap server (slop taste serve / stop / status)
    sheets/<id>/             numbered pair sheets for chat (slop taste sheet / record): sheet.json + sheet-N.jpg
    verdicts.jsonl           (user profile only) a copy of every project's rule verdicts, so they carry over
    PROFILE.json             (user profile only) {"kind": "user", "projects": {name: {path, linked}}}

taps.jsonl rows (the retired feed's schema, plus the position-bias fields from research 11-gap-5 §5.4):
    unary  {"eid","t","item","action":"like"|"pass","kind","dwell_ms","why":"cold|model|explore|seed|repeat","score"}
    pair   {"eid","t","a","b","winner":"a"|"b"|"tie"|"skip","via":"human"|"sheet","dwell_ms","shown":"ab"|"ba",
            "layout":"row"|"stack"|"sheet"}   (sheet rows add "sheet", "n" and "why")
    undo   {"undo": eid, "t"}   -> readers drop both rows
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

_LOCK = threading.RLock()
LINK_FILE = "profile.json"          # <project>/taste/profile.json
PROFILE_KINDS = ("user", "project")
_PINNED: dict[str, Path] = {}
_LINK_CACHE: dict[str, tuple] = {}
DATA_FILES = ("pool/pool.jsonl", "taps.jsonl", "fonts/taps.jsonl")   # any of these non-empty = the root holds data


def project_taste_dir(pdir: Path) -> Path:
    """the project's own taste/ folder (link, tokens, look bible, boards, verdicts), whatever profile it uses"""
    d = Path(pdir) / "taste"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_profile_dir() -> Path:
    from ..config import slop_home
    return slop_home() / "taste"


def link_path(pdir: Path) -> Path:
    return Path(pdir) / "taste" / LINK_FILE


def read_link(pdir: Path) -> dict | None:
    """the project's profile link, or None (cached on the file's mtime + size: taste_dir is called per event read)"""
    p = link_path(pdir)
    try:
        st = p.stat()
    except OSError:
        return None
    key = str(p)
    sig = (st.st_mtime_ns, st.st_size)
    hit = _LINK_CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    v = read_json(p, None)
    v = v if isinstance(v, dict) and v.get("profile") in PROFILE_KINDS else None
    _LINK_CACHE[key] = (sig, v)
    return v


def pin_root(pdir: Path, root: Path | None) -> None:
    """fix this project's taste root for the rest of the process (the tap server), or unpin with None"""
    if root is None:
        _PINNED.pop(str(Path(pdir)), None)
    else:
        _PINNED[str(Path(pdir))] = Path(root)


def profile_root(pdir: Path, link: dict | None = None) -> Path:
    """where this project's taste DATA lives (not created)"""
    pin = _PINNED.get(str(Path(pdir)))
    if pin is not None:
        return pin
    link = read_link(pdir) if link is None else link
    if link and link.get("profile") == "user":
        return user_profile_dir()
    return Path(pdir) / "taste"


def has_data(root: Path) -> bool:
    """True if a profile root holds any pool image, tap or font pick"""
    for rel in DATA_FILES:
        try:
            if (Path(root) / rel).stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def taste_dir(pdir: Path) -> Path:
    """the profile root holding this project's taste data (see the module docstring)"""
    d = profile_root(pdir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def pool_dir(pdir: Path) -> Path:
    d = taste_dir(pdir) / "pool"
    (d / "images").mkdir(parents=True, exist_ok=True)
    return d


def images_dir(pdir: Path) -> Path:
    return pool_dir(pdir) / "images"


def pool_index(pdir: Path) -> Path:
    return pool_dir(pdir) / "pool.jsonl"


def emb_dir(pdir: Path) -> Path:
    d = taste_dir(pdir) / "emb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def taps_path(pdir: Path) -> Path:
    return taste_dir(pdir) / "taps.jsonl"


def fonts_dir(pdir: Path) -> Path:
    d = taste_dir(pdir) / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_eid() -> str:
    return uuid.uuid4().hex[:12]


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn last line (crash mid-write) must not break every reader
    return out


def append_jsonl(path: Path, rec: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _LOCK, path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass


def write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return default


def live_events(rows: list[dict]) -> list[dict]:
    """drop undo rows and the rows they undo"""
    undone = {r["undo"] for r in rows if "undo" in r}
    return [r for r in rows if "undo" not in r and r.get("eid") not in undone]


def read_events(path: Path) -> list[dict]:
    return live_events(read_jsonl(path))


def split_events(events: list[dict]) -> tuple[list[tuple], list[tuple]]:
    """-> unary [(item, 1.0 like / 0.0 pass, kind)], decisive pairs [(a, b, 1.0 if a won else 0.0)]"""
    unary = [(e["item"], 1.0 if e["action"] == "like" else 0.0, e.get("kind", "human"))
             for e in events if e.get("action") in ("like", "pass") and e.get("item")]
    pairs = [(e["a"], e["b"], 1.0 if e["winner"] == "a" else 0.0)
             for e in events if e.get("winner") in ("a", "b") and e.get("a") and e.get("b")]
    return unary, pairs


def slugify(s: str, maxlen: int = 40) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:maxlen] or "board"
