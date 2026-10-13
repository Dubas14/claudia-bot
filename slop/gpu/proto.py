"""The job contract shared by the box and the worker (stdlib only; runs on Windows, macOS and Linux, Python 3.10+).

A job manifest (box -> worker), version 1:
  {"v": 1, "id": "<32 hex>", "kind": "run" | "install", "entry": "audio.stems", "profile": "audio",
   "params": {...}, "inputs": [{"name": "song.wav", "size": N, "sha256": "..."}], "timeout_s": 1800,
   "force_gpu": false}
The worker refuses anything that does not validate: unknown entries (the box cannot name a program, a model or a
package - those are fixed in ENTRIES and profiles.PROFILES), parameters outside their schema, unsafe file names, files
over the size caps. Ids are 32 lower-case hex digits (uuid4), durable across restarts and retries.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

PROTO = 1
ID_RE = re.compile(r"^[0-9a-f]{32}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
MiB = 1 << 20
GiB = 1 << 30
CHUNK = 32 * MiB                    # one HTTP upload/download piece (Cloudflare caps a request body at 100 MB)
PART = 95 * MiB                     # one direct-mode file part (Grok Bot CopyToBox/CopyFromBox cap 100 MiB a file)
MAX_FILE = 2 * GiB                  # one input or output file
MAX_TOTAL = 6 * GiB                 # all inputs (or all outputs) of one job
MAX_JSON = 256 * 1024               # one JSON request body
MAX_FILES = 512
TERMINAL = ("succeeded", "failed", "cancelled", "interrupted", "timed_out")
ACTIVE = ("assigned", "running")
KINDS = ("run", "install")


class ManifestError(ValueError):
    """A manifest or parameter that does not validate: the worker refuses the job with this message."""


# ------------------------------------------------------------------------------------------------ the entry table
# inputs: [(name regex, min count, max count)]; params: name -> (type, ...). Types:
#   ("int", lo, hi, default) ("float", lo, hi, default) ("bool", default) ("enum", [choices], default)
#   ("str", regex, default) ("boxes", max_n): a list of [x0, y0, x1, y1] in 0..1 (one per input image, or empty)
IMG = r"img-\d{3}\.png"
ENTRIES: dict[str, dict] = {
    "audio.stems": {
        "profile": "audio", "timeout": 1800, "inputs": [(r"song\.(wav|flac)", 1, 1)],
        "params": {"shifts": ("int", 0, 4, 1), "overlap": ("float", 0.0, 0.9, 0.25), "seed": ("int", 0, 2**31 - 1, 0),
                   "format": ("enum", ["flac24", "f32"], "flac24")},
        "what": "Demucs htdemucs 4-stem separation (vocals, drums, bass, other)"},
    "audio.align": {
        "profile": "audio", "timeout": 1200, "inputs": [(r"vocals16k\.wav", 1, 1)],
        "params": {"chunk_s": ("int", 5, 60, 20), "context_s": ("float", 0.0, 2.0, 0.1)},
        "what": "wav2vec2 CTC emissions for forced alignment (the Viterbi runs on the box)"},
    "audio.whisper": {
        "profile": "audio", "timeout": 1800, "inputs": [(r"audio\.wav", 1, 1)],
        "params": {"language": ("str", r"^(|[a-z]{2})$", ""), "beam_size": ("int", 1, 10, 5),
                   "vad": ("bool", False)},
        "what": "faster-whisper large-v3 word timestamps"},
    "matte.depth": {
        "profile": "matte", "timeout": 900, "inputs": [(IMG, 1, 256)], "params": {},
        "what": "Depth-Anything-V2-Small depth (raw predicted depth per image, .npy float32)"},
    "matte.birefnet": {
        "profile": "matte", "timeout": 1800, "inputs": [(IMG, 1, 256)],
        "params": {"size": ("int", 512, 2048, 2048), "half": ("bool", True)},
        "what": "BiRefNet_HR foreground matte (8-bit alpha PNG per image)"},
    "matte.sam2": {
        "profile": "matte", "timeout": 1800, "inputs": [(IMG, 1, 64)],
        "params": {"boxes": ("boxes", 64)},
        "what": "SAM 2.1 (hiera-small) masks from one box prompt per image"},
    "interp.film": {
        "profile": "interp", "timeout": 3600, "inputs": [(r"frames\.zip", 1, 1)],
        "params": {"factor": ("enum", [2, 4, 8], 2), "half": ("bool", False)},
        "what": "FILM frame interpolation (x2/x4/x8 frames)"},
    "lipsync.latentsync": {
        "profile": "lipsync", "timeout": 5400, "inputs": [(r"video\.mp4", 1, 1), (r"audio\.wav", 1, 1)],
        "params": {"steps": ("int", 10, 50, 20), "guidance": ("float", 1.0, 3.0, 1.5), "seed": ("int", 0, 2**31 - 1, 1247)},
        "what": "LatentSync 1.6 lip sync (opt-in, openrail++ weights)"},
}


def new_id() -> str:
    return uuid.uuid4().hex


def valid_id(value: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ManifestError("invalid job id (want 32 lower-case hex digits)")
    return value


def safe_name(name: str) -> str:
    """A plain file name: no folders, no '..', no drive letters, no leading dot."""
    if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
        raise ManifestError(f"unsafe file name {str(name)[:60]!r}")
    return name


def param_defaults(entry: str) -> dict:
    out = {}
    for k, spec in ENTRIES[entry]["params"].items():
        if spec[0] in ("int", "float"):
            out[k] = spec[3]
        elif spec[0] in ("bool", "str"):
            out[k] = spec[-1]
        elif spec[0] == "enum":
            out[k] = spec[2]
        elif spec[0] == "boxes":
            out[k] = []
    return out


def validate_params(entry: str, params: dict | None) -> dict:
    """-> the full parameter dict (defaults filled in). Unknown keys and out-of-range values are refused."""
    if entry not in ENTRIES:
        raise ManifestError(f"unknown entry {str(entry)[:40]!r}; known: {', '.join(sorted(ENTRIES))}")
    params = dict(params or {})
    schema = ENTRIES[entry]["params"]
    bad = sorted(set(params) - set(schema))
    if bad:
        raise ManifestError(f"{entry}: unknown parameter(s) {bad}; allowed: {sorted(schema) or 'none'}")
    out = param_defaults(entry)
    for k, v in params.items():
        spec = schema[k]
        t = spec[0]
        if t == "int":
            if isinstance(v, bool) or not isinstance(v, int) or not spec[1] <= v <= spec[2]:
                raise ManifestError(f"{entry}: {k} must be an integer {spec[1]}..{spec[2]}")
        elif t == "float":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not spec[1] <= float(v) <= spec[2]:
                raise ManifestError(f"{entry}: {k} must be a number {spec[1]}..{spec[2]}")
            v = float(v)
        elif t == "bool":
            if not isinstance(v, bool):
                raise ManifestError(f"{entry}: {k} must be true or false")
        elif t == "enum":
            if v not in spec[1]:
                raise ManifestError(f"{entry}: {k} must be one of {spec[1]}")
        elif t == "str":
            if not isinstance(v, str) or not re.match(spec[1], v):
                raise ManifestError(f"{entry}: {k} has an invalid value")
        elif t == "boxes":
            if not isinstance(v, list) or len(v) > spec[1]:
                raise ManifestError(f"{entry}: {k} must be a list of at most {spec[1]} boxes")
            for b in v:
                if (not isinstance(b, list) or len(b) != 4 or
                        not all(isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1 for x in b)
                        or b[2] <= b[0] or b[3] <= b[1]):
                    raise ManifestError(f"{entry}: each box is [x0, y0, x1, y1] with 0 <= x0 < x1 <= 1, 0 <= y0 < y1 <= 1")
        out[k] = v
    return out


def validate_inputs(entry: str, inputs: list) -> list:
    if not isinstance(inputs, list) or len(inputs) > MAX_FILES:
        raise ManifestError("inputs must be a list of at most %d files" % MAX_FILES)
    seen, total = set(), 0
    for f in inputs:
        if not isinstance(f, dict) or set(f) - {"name", "size", "sha256"}:
            raise ManifestError("each input is {name, size, sha256}")
        safe_name(f.get("name"))
        if f["name"] in seen:
            raise ManifestError(f"duplicate input {f['name']}")
        seen.add(f["name"])
        size = f.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE:
            raise ManifestError(f"input {f['name']}: size must be 0..{MAX_FILE} bytes")
        if not isinstance(f.get("sha256"), str) or not re.match(r"^[0-9a-f]{64}$", f["sha256"]):
            raise ManifestError(f"input {f['name']}: sha256 missing")
        total += size
    if total > MAX_TOTAL:
        raise ManifestError(f"inputs total {total} bytes > cap {MAX_TOTAL}")
    names = [f["name"] for f in inputs]
    for rx, lo, hi in ENTRIES[entry]["inputs"]:
        n = sum(1 for x in names if re.fullmatch(rx, x))
        if not lo <= n <= hi:
            raise ManifestError(f"{entry}: needs {lo}..{hi} input(s) named like {rx!r}, got {n}")
    pats = [r for r, _, _ in ENTRIES[entry]["inputs"]]
    extra = [x for x in names if not any(re.fullmatch(r, x) for r in pats)]
    if extra:
        raise ManifestError(f"{entry}: unexpected input(s) {extra[:5]}")
    return inputs


def validate_manifest(m: dict, known_profiles=None) -> dict:
    """Check a manifest from the box; -> a normalised copy. Raises ManifestError."""
    if not isinstance(m, dict):
        raise ManifestError("manifest is not an object")
    if m.get("v") != PROTO:
        raise ManifestError(f"manifest version {m.get('v')!r}; this worker speaks version {PROTO} (re-run the pairing "
                            "line from `slop gpu pair` to update the worker)")
    valid_id(m.get("id"))
    kind = m.get("kind", "run")
    if kind not in KINDS:
        raise ManifestError(f"unknown job kind {str(kind)[:20]!r}")
    timeout = m.get("timeout_s", 1800)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 6 * 3600:
        raise ManifestError("timeout_s must be 10..21600")
    out = {"v": PROTO, "id": m["id"], "kind": kind, "timeout_s": timeout, "force_gpu": bool(m.get("force_gpu"))}
    if kind == "install":
        prof = m.get("profile")
        if not isinstance(prof, str) or (known_profiles is not None and prof not in known_profiles):
            raise ManifestError(f"unknown profile {str(prof)[:30]!r}")
        out.update(profile=prof, accept_licence=bool(m.get("accept_licence")), entry=None, params={}, inputs=[])
        return out
    entry = m.get("entry")
    if entry not in ENTRIES:
        raise ManifestError(f"unknown entry {str(entry)[:40]!r}: the worker runs only the toolkit's own entrypoints "
                            f"({', '.join(sorted(ENTRIES))})")
    if m.get("profile", ENTRIES[entry]["profile"]) != ENTRIES[entry]["profile"]:
        raise ManifestError(f"{entry} runs in profile {ENTRIES[entry]['profile']}, not {m.get('profile')!r}")
    out.update(entry=entry, profile=ENTRIES[entry]["profile"], params=validate_params(entry, m.get("params")),
               inputs=validate_inputs(entry, m.get("inputs", [])))
    if entry == "matte.sam2" and out["params"]["boxes"] and len(out["params"]["boxes"]) != len(out["inputs"]):
        raise ManifestError("matte.sam2: give one box per image (or none for the centre box)")
    return out


# ------------------------------------------------------------------------------------------------ small helpers
def atomic_json(path: Path | str, value) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(value, indent=1, ensure_ascii=False, default=str) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    for attempt in range(40):          # Windows: a reader may hold the file for a moment
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)


def read_json(path: Path | str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_entry(path: Path | str, name: str | None = None) -> dict:
    p = Path(path)
    return {"name": safe_name(name or p.name), "size": p.stat().st_size, "sha256": sha256_file(p)}


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def list_outputs(out_dir: Path) -> list[dict]:
    """The files an entry produced: regular files directly in out_dir with safe names (no links, no folders), within
    the caps. Anything else is an error (an entry never writes elsewhere)."""
    files, total = [], 0
    for p in sorted(Path(out_dir).iterdir()):
        if p.is_symlink() or not p.is_file():
            raise ManifestError(f"output {p.name!r} is not a regular file")
        safe_name(p.name)
        size = p.stat().st_size
        if size > MAX_FILE:
            raise ManifestError(f"output {p.name} is {size} bytes > cap {MAX_FILE}")
        total += size
        files.append(file_entry(p))
    if total > MAX_TOTAL or len(files) > MAX_FILES:
        raise ManifestError("outputs exceed the size/count caps")
    return files


def safe_extract(archive: Path, dest: Path, max_total: int = MAX_TOTAL, max_files: int = 20000) -> list[str]:
    """Extract a zip refusing traversal, absolute and drive paths, links and oversized content. -> member names."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > max_files:
            raise ManifestError(f"archive has {len(infos)} members > {max_files}")
        total = 0
        for it in infos:
            p = PurePosixPath(it.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or any(":" in x for x in p.parts):
                raise ManifestError(f"unsafe archive path {it.filename[:80]!r}")
            if (it.external_attr >> 16) & 0o170000 == 0o120000:
                raise ManifestError("archive links are not allowed")
            total += it.file_size
            if total > max_total:
                raise ManifestError("archive content exceeds the size cap")
            if not it.is_dir():
                names.append(str(p))
        for it in infos:
            target = dest / it.filename.replace("\\", "/")
            if not inside(target, dest):
                raise ManifestError("archive escapes its folder")
        z.extractall(dest)
    return names


def split_file(path: Path, part_bytes: int = PART) -> list[Path]:
    """path -> path.001, path.002 ... (each <= part_bytes); a file that fits becomes one .001 part."""
    path = Path(path)
    parts, i = [], 1
    with open(path, "rb") as f:
        while True:
            chunk = f.read(part_bytes)
            if not chunk and parts:
                break
            p = path.with_name(f"{path.name}.{i:03d}")
            p.write_bytes(chunk)
            parts.append(p)
            i += 1
            if len(chunk) < part_bytes:
                break
    return parts


def join_parts(first_or_parts, dest: Path) -> Path:
    """Join name.001, name.002 ... (or an explicit list, in order) into dest."""
    if isinstance(first_or_parts, (list, tuple)):
        parts = [Path(p) for p in first_or_parts]
    else:
        base = Path(first_or_parts)
        stem = base.name[:-4] if re.search(r"\.\d{3}$", base.name) else base.name
        parts = sorted(base.parent.glob(stem + ".[0-9][0-9][0-9]"))
    if not parts:
        raise ManifestError("no parts to join")
    nums = [int(p.name[-3:]) for p in parts if re.search(r"\.\d{3}$", p.name)]
    if nums and nums != list(range(1, len(nums) + 1)):
        raise ManifestError(f"parts are not complete: have {nums}")
    dest = Path(dest)
    with open(dest, "wb") as out:
        for p in parts:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    out.write(chunk)
    return dest
