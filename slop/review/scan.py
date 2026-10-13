"""The safety and canon scan: contact sheets of every generated take, and the findings record (docs/80 §9).

Port of the safety-scan workflow's per-agent steps (templates/workflows/safety-scan.js) into commands the bot runs
itself: the take list (docs/80 §9.1's script, unchanged in meaning: only takes the EDL plays), six frames per take at
8 / 25 / 42 / 58 / 75 / 92 % of its length, 640 px wide, tiled 3 × 2 and labelled with the time; the findings schema is
read from the workflow file, so the two can never disagree (the copy below is the fallback, kept equal by a test).
Intentional changes: the sheets are made by code, not by each agent (identical sheets for every reviewer, made once);
a record is MERGED (a re-scan of a re-made take replaces that take's findings; findings on takes the edit no longer
plays are kept but marked stale and never count as open).

What counts as checked (never assumed):
- the verdict is judged against the takes edit/edl.json plays NOW (the same rule as `slop status`): a take the edit
  plays that is not in the record, a take re-made after it was checked (its file changed: size + mtime signature,
  recorded when it was sheeted), or a take list (render/scan-list.json) that no longer matches the edit → NOT CLEAN;
- the findings template (render/scan/findings-template.json) lists the takes under "to_check" and starts with
  "checked": [] — a take counts only once someone has looked at its sheet and added it; the template itself, or an
  unchanged copy of it, is refused;
- the workflow's result names no takes (only "checked": N, "of": M): it clears the whole list only when M is the
  number of takes the edit plays, the list file matches the edit and no finding names a take outside it; otherwise
  only the takes its findings name count as checked.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from ..config import SlopError, toolkit_root
from ..util import atomic_write_json, iso_now

FRACS = (.08, .25, .42, .58, .75, .92)
TILE_W = 640
LABEL_H = 24
TEMPLATE = "render/scan/findings-template.json"
FINDINGS = "render/scan/findings.json"          # where the bot writes its filled-in copy (core's `slop status` says so)
EPS = 2.0                                        # seconds of file-time slack (legacy records without signatures)
SEVERITIES = ("block", "fix", "note")
# the per-agent result schema of templates/workflows/safety-scan.js (fallback copy; tests/test_review_scan.py keeps it equal)
SCHEMA = {"type": "object", "properties": {
    "findings": {"type": "array", "items": {"type": "object", "properties": {
        "clip": {"type": "string"}, "time": {"type": "number"},
        "severity": {"type": "string", "enum": ["block", "fix", "note"]}, "kind": {"type": "string"},
        "what": {"type": "string"}}, "required": ["clip", "severity", "kind", "what"]}},
    "checked": {"type": "array", "items": {"type": "string"}},
    "given": {"type": "number", "description": "how many takes your slice contained"}},
    "required": ["findings", "checked", "given"]}


# ------------------------------------------------------------------------------------------------ the schema -------
def workflow_file() -> Path:
    return toolkit_root() / "templates" / "workflows" / "safety-scan.js"


def js_object_to_json(src: str) -> object:
    """A JS object literal of plain data (unquoted keys, 'single' or "double" quoted strings, numbers, true/false/null,
    arrays, trailing commas) → Python."""
    out: list[str] = []
    last = ""                                     # the last significant character written
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1] if src[j + 1] in "'\"" else src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append(json.dumps(json.loads('"' + "".join(buf).replace('"', '\\"') + '"')))
            last = '"'
            i = j + 1
            continue
        m = re.match(r"[A-Za-z_$][\w$]*", src[i:])
        if m:
            word = m.group(0)
            if last in ("{", ",", "") and src[i + len(word):].lstrip().startswith(":"):
                out.append(json.dumps(word))
            else:
                out.append(word)
            last = word[-1]
            i += len(word)
            continue
        out.append(c)
        if not c.isspace():
            last = c
        i += 1
    return json.loads(re.sub(r",\s*([}\]])", lambda m: m.group(1), "".join(out)))


def schema_from_workflow(path: Path | None = None) -> dict | None:
    """The SCHEMA constant of templates/workflows/safety-scan.js, or None when it cannot be read."""
    f = Path(path) if path else workflow_file()
    try:
        s = f.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"const\s+SCHEMA\s*=\s*", s)
    if not m:
        return None
    i, depth, start = m.end(), 0, m.end()
    quote = None
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    v = js_object_to_json(s[start:i + 1])
                except (ValueError, json.JSONDecodeError):
                    return None
                return v if isinstance(v, dict) else None
        i += 1
    return None


def schema() -> dict:
    return schema_from_workflow() or SCHEMA


def validate(value, sch: dict, path: str = "$") -> list[str]:
    """The JSON-schema subset the workflow uses (type object/array/string/number, properties, required, items, enum)."""
    errs: list[str] = []
    t = sch.get("type")
    if t == "object":
        if not isinstance(value, dict):
            return [f"{path} must be an object {{…}}, got {type(value).__name__}"]
        for k in sch.get("required", []):
            if k not in value:
                errs.append(f"{path} is missing \"{k}\"")
        for k, sub in (sch.get("properties") or {}).items():
            if k in value:
                errs += validate(value[k], sub, f"{path}.{k}")
    elif t == "array":
        if not isinstance(value, list):
            return [f"{path} must be a list […], got {type(value).__name__}"]
        for i, v in enumerate(value):
            errs += validate(v, sch.get("items") or {}, f"{path}[{i}]")
    elif t == "string":
        if not isinstance(value, str) or not value.strip():
            errs.append(f"{path} must be a non-empty string, got {json.dumps(value)[:40]}")
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errs.append(f"{path} must be a number, got {json.dumps(value)[:40]}")
    if "enum" in sch and value not in sch["enum"]:
        errs.append(f"{path} must be one of {' · '.join(map(str, sch['enum']))}, got {json.dumps(value)[:40]}")
    return errs


# --------------------------------------------------------------------------------------------- the take list -------
def _read(path: Path, hint: str):
    if not path.is_file():
        raise SlopError(f"missing {path} — {hint}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{path} is not valid JSON ({e}) — {hint}") from e


def _abs(pdir: Path, f: str | None) -> Path | None:
    if not f:
        return None
    p = Path(f)
    return p if p.is_absolute() else pdir / p


def used_takes(pdir: Path) -> tuple[list[dict], list[str]]:
    """([{clip, file, shots, song_t0, dur}], problems) — every take the EDL plays (engine names "<clip>-t<k>")."""
    edl = _read(pdir / "edit" / "edl.json", "run `slop edit edl` first (the scan covers the takes the edit plays)")
    used: dict[str, list[str]] = {}
    for shot, e in sorted((edl or {}).items()):
        for g in (e or {}).get("segs") or []:
            if isinstance(g, dict) and g.get("clip"):
                used.setdefault(str(g["clip"]), []).append(str(shot))
    out, probs = [], []
    for name, shots in sorted(used.items()):
        clip, sep, k = name.rpartition("-t")
        if not sep or not k.isdigit():
            probs.append(f"{name}: not a take name (<clip>-t<k>)")
            continue
        f = pdir / "clips" / f"{clip}.json"
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            take = (rec.get("takes") or [])[int(k) - 1]
        except (OSError, json.JSONDecodeError, IndexError, ValueError):
            probs.append(f"{name}: no take {k} in clips/{clip}.json (run `slop edit edl` again)")
            continue
        out.append({"clip": name, "file": take.get("file"), "shots": sorted(set(shots)), "song_t0": rec.get("song_t0"),
                    "dur": (rec.get("body") or {}).get("duration")})
    return out, probs


def used_plates(pdir: Path) -> list[dict]:
    """[{plate, file, shots}] — the picked plates the EDL shows (a plate is generated imagery too)."""
    edl = _read(pdir / "edit" / "edl.json", "run `slop edit edl` first")
    picks = {}
    pf = pdir / "plates" / "picks.json"
    if pf.is_file():
        try:
            picks = json.loads(pf.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            picks = {}
    by: dict[str, list[str]] = {}
    for shot, e in sorted((edl or {}).items()):
        if isinstance(e, dict) and e.get("plate"):
            by.setdefault(str(e["plate"]), []).append(str(shot))
    out = []
    for name, shots in sorted(by.items()):
        v = picks.get(name) if isinstance(picks.get(name), dict) else {}
        f = v.get("file") or f"engine/assets/plates/{name}.jpg"
        out.append({"plate": name, "file": f, "shots": sorted(set(shots))})
    return out


def take_sig(path: Path | None) -> str | None:
    """size:mtime_ns of a take file — compared for EQUALITY only (a re-made take changes it), never ordered, so a
    clock that jumps cannot hide or invent a re-make."""
    try:
        st = Path(path).stat()
    except (OSError, TypeError):
        return None
    return f"{st.st_size}:{st.st_mtime_ns}"


def _list_names(pdir: Path) -> list[str] | None:
    lf = pdir / "render" / "scan-list.json"
    if not lf.is_file():
        return None
    try:
        v = json.loads(lf.read_text(encoding="utf-8"))
        return sorted({str(t["clip"]) for t in v if isinstance(t, dict) and t.get("clip")})
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _sheet_sigs(pdir: Path) -> dict[str, str]:
    """{clip: the take file's signature when its sheet was made} from render/scan/sheets.json."""
    try:
        v = json.loads((pdir / "render" / "scan" / "sheets.json").read_text(encoding="utf-8"))
        return {str(r["clip"]): str(r["sig"]) for r in v.get("takes") or [] if isinstance(r, dict) and r.get("sig")}
    except (OSError, json.JSONDecodeError, AttributeError, KeyError, TypeError):
        return {}


# ------------------------------------------------------------------------------------------------- the sheets ------
def _need(tool: str) -> str:
    exe = shutil.which(tool)
    if not exe:
        raise SlopError(f"{tool} not found on PATH — install ffmpeg (the box has it; elsewhere: apt install ffmpeg)")
    return exe


def duration(path: Path) -> float:
    r = subprocess.run([_need("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=120)
    try:
        return float(json.loads(r.stdout or "{}")["format"]["duration"])
    except (KeyError, ValueError, TypeError) as e:
        raise SlopError(f"ffprobe cannot read {path}: {(r.stderr or '').strip()[:200]}") from e


def grab(path: Path, t: float, width: int = TILE_W):
    """One frame at t seconds, `width` px wide (PIL image)."""
    from PIL import Image
    r = subprocess.run([_need("ffmpeg"), "-nostdin", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path),
                        "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", "-"],
                       capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode != 0 or not r.stdout:
        raise SlopError(f"ffmpeg could not read a frame at {t:.2f} s of {path}: {r.stderr.decode(errors='replace')[-200:]}")
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def tile_sheet(tiles: list, labels: list[str], out: Path, cols: int = 3, rows: int = 2, width: int = TILE_W) -> Path:
    """Tiles (PIL images, any aspect) letterboxed into width × 9/16 cells, labelled underneath."""
    from PIL import Image, ImageDraw
    ch = round(width * 9 / 16)
    if tiles:
        ch = max(round(width * im.height / im.width) for im in tiles)
    img = Image.new("RGB", (cols * width, rows * (ch + LABEL_H)), (17, 17, 17))
    d = ImageDraw.Draw(img)
    for k, (im, lab) in enumerate(zip(tiles, labels)):
        x, y = (k % cols) * width, (k // cols) * (ch + LABEL_H)
        fit = im.copy()
        fit.thumbnail((width, ch))
        img.paste(fit, (x + (width - fit.width) // 2, y + (ch - fit.height) // 2))
        d.text((x + 8, y + ch + 5), lab[:100], fill=(235, 235, 230))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.jpg")
    img.save(tmp, quality=88)
    tmp.replace(out)
    return out


def take_times(dur: float) -> list[float]:
    return [round(dur * f, 3) for f in FRACS]


def scan_sheets(pdir: Path, plates: bool = False, force: bool = False) -> dict:
    takes, probs = used_takes(pdir)
    render = pdir / "render"
    sdir = render / "scan"
    sdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(render / "scan-list.json", takes)
    old_sigs = _sheet_sigs(pdir)
    made, kept, rows, missing = 0, 0, [], []
    for tk in takes:
        f = _abs(pdir, tk["file"])
        if f is None or not f.is_file():
            missing.append(f"{tk['clip']}: take file {tk['file'] or '(none)'} is missing")
            continue
        sheet = sdir / f"{tk['clip']}.jpg"
        sig = take_sig(f)
        dur = duration(f)
        ts = take_times(dur)
        if force or not sheet.is_file() or old_sigs.get(tk["clip"]) != sig:      # new or re-made take: a new sheet
            tiles = [grab(f, t) for t in ts]
            tile_sheet(tiles, [f"{tk['clip']}  {t:.2f} s ({round(fr * 100)} %)" for t, fr in zip(ts, FRACS)], sheet)
            made += 1
        else:
            kept += 1
        rows.append({"clip": tk["clip"], "file": tk["file"], "sheet": sheet.relative_to(pdir).as_posix(), "dur": round(dur, 3),
                     "times": ts, "shots": tk["shots"], "sig": sig})
    prow = []
    if plates:
        from PIL import Image
        pl = used_plates(pdir)
        for old in sdir.glob("plates-*.jpg"):
            old.unlink(missing_ok=True)
        for k in range(0, len(pl), 6):
            group = pl[k:k + 6]
            tiles, labels = [], []
            for p in group:
                f = _abs(pdir, p["file"])
                if f is None or not f.is_file():
                    missing.append(f"plate {p['plate']}: {p['file']} is missing")
                    continue
                with Image.open(f) as im:
                    tiles.append(im.convert("RGB").resize((TILE_W, max(1, round(TILE_W * im.height / im.width)))))
                labels.append(f"plate {p['plate']}  ({', '.join(p['shots'][:4])}{' …' if len(p['shots']) > 4 else ''})")
            if tiles:
                sh = tile_sheet(tiles, labels, sdir / f"plates-{k // 6 + 1:02d}.jpg")
                prow.append({"sheet": sh.relative_to(pdir).as_posix(), "plates": [p["plate"] for p in group]})
    index = {"made_at": iso_now(), "list": "render/scan-list.json", "total": len(takes), "takes": rows, "plates": prow,
             "fractions": list(FRACS)}
    atomic_write_json(sdir / "sheets.json", index)
    template = pdir / TEMPLATE
    to_check = [r["clip"] for r in rows] + [f"plate:{p}" for s in prow for p in s["plates"]]
    atomic_write_json(template, {
        "how": (f"copy this file to {FINDINGS}; open each sheet in render/scan/ (one per name in to_check; plates on "
                "plates-NN.jpg) and look at all six frames; add the name to \"checked\" only after you looked at it; "
                "add a finding for every problem ({\"clip\", \"time\", \"severity\": block|fix|note, \"kind\", "
                f"\"what\"}}); then `slop review record {FINDINGS}`"),
        "to_check": to_check, "findings": [], "checked": [], "given": len(to_check)})
    lines = [f"{len(takes)} generated take(s) in the edit → {made} sheet(s) made, {kept} unchanged in render/scan/ "
             f"(3×2 frames at 8/25/42/58/75/92 %); the take list for the safety-scan workflow: render/scan-list.json "
             f"(total {len(takes)})"]
    if plates:
        lines.append(f"{sum(len(s['plates']) for s in prow)} plate(s) on {len(prow)} sheet(s): render/scan/plates-NN.jpg")
    elif not takes:
        lines.append("the edit plays no generated takes (plates only): run `slop review scan-sheets --plates` to scan the plates")
    if probs or missing:
        lines.append("NOT SHEETED: " + "; ".join((probs + missing)[:8]))
    cp = f"cp {shlex.quote((pdir / TEMPLATE).as_posix())} {shlex.quote((pdir / FINDINGS).as_posix())}"
    lines.append(f"next, one step at a time: (1) `{cp}`; (2) open EVERY sheet in render/scan/ and look "
                 "at all six frames (rubric: docs/80-review-qa.md §9.2 — block / fix / note); (3) in "
                 f"{FINDINGS}, add each take you looked at to \"checked\" (the names are in \"to_check\") and each "
                 "problem to \"findings\" ({\"clip\", \"time\", \"severity\", \"kind\", \"what\"}); (4) `slop review "
                 f"record {FINDINGS}` (it refuses the untouched template: nothing counts as checked until you add it)")
    return {"ok": not probs and not missing, "takes": rows, "plates": prow, "list": str(render / "scan-list.json"),
            "total": len(takes), "made": made, "kept": kept, "problems": probs + missing, "template": str(template),
            "text": "\n".join(lines)}


# ----------------------------------------------------------------------------------------------- the record -------
def _normalize(doc) -> tuple[list[dict], list[str] | None, list[str], bool | None, dict]:
    """(findings, checked clip names or None, schema errors, complete?, extra) from any accepted shape:
    the workflow's result {ok, checked: N, of, findings, unchecked} (checked None: it names no takes; extra["of"]),
    one agent slice {findings, checked: [...], given}, or a list of slices."""
    sch = schema()
    if isinstance(doc, list):
        F, C, E, complete = [], [], [], True
        for i, part in enumerate(doc):
            errs = [e.replace("$", f"$[{i}]", 1) for e in validate(part, sch)]
            E += errs
            if not errs:
                F += part["findings"]
                C += part["checked"]
                complete &= len(part["checked"]) >= int(part["given"])
        return F, C, E, complete, {}
    if isinstance(doc, dict) and isinstance(doc.get("checked"), (int, float)) and not isinstance(doc.get("checked"), bool):
        item = (sch.get("properties") or {}).get("findings") or SCHEMA["properties"]["findings"]
        E = validate(doc.get("findings"), item, "$.findings") if "findings" in doc else ['$ is missing "findings"']
        of = doc.get("of")
        complete = bool(doc.get("ok")) and not doc.get("unchecked") and isinstance(of, (int, float)) and doc["checked"] >= of
        names = doc.get("takes") if isinstance(doc.get("takes"), list) else doc.get("clips")
        names = [str(x) for x in names] if isinstance(names, list) and all(isinstance(x, str) and x for x in names) else None
        return (doc.get("findings") or [] if not E else []), names, E, complete, {"workflow": True, "of": of}
    E = validate(doc, sch)
    if E:
        return [], [], E, False, {}
    return doc["findings"], doc["checked"], [], len(doc["checked"]) >= int(doc["given"]), {}


def _fid(f: dict) -> str:
    return hashlib.sha1(json.dumps({k: f.get(k) for k in ("clip", "time", "severity", "kind", "what")},
                                   sort_keys=True).encode()).hexdigest()[:10]


def _take_files(pdir: Path) -> dict[str, Path | None]:
    return {t["clip"]: _abs(pdir, t.get("file")) for t in used_takes(pdir)[0]}


def state(pdir: Path, scan: dict | None = None) -> dict:
    """The scan's state against the takes edit/edl.json plays NOW (not against render/scan-list.json, which only
    says what was sheeted): {takes, checked, unchecked, remade, list_stale, counts, open, stale, release_ok,
    recorded, step}. step = the one thing to do next: "sheets" (`slop review scan-sheets`), "record", "triage", None."""
    files = _take_files(pdir)
    takes = sorted(files)
    lst = _list_names(pdir)
    list_stale = lst is not None and set(lst) != set(takes)
    sf = pdir / "render" / "scan" / "scan.json"
    if scan is None:
        try:
            scan = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
        except json.JSONDecodeError as e:
            raise SlopError(f"{sf} is not valid JSON ({e}) — move it aside (rename it to scan.broken.json), then record "
                            f"the findings again: `slop review record {FINDINGS}`") from e
        smt = sf.stat().st_mtime if sf.is_file() else None
    else:
        smt = None                                   # a record being written now: its takes were checked now
    checked = set(scan.get("checked") or [])
    sigs = scan.get("sigs") if isinstance(scan.get("sigs"), dict) else {}
    remade = []
    for t in takes:
        if t not in checked:
            continue
        f = files.get(t)
        if t in sigs:
            if take_sig(f) != sigs[t]:
                remade.append(t)
        elif smt is not None and f is not None and f.is_file() and f.stat().st_mtime > smt + EPS:
            remade.append(t)                         # a record from before signatures: file time, like `slop status`
    live = set(takes)
    is_open = lambda f: f.get("clip") in live or str(f.get("clip", "")).startswith("plate:")    # noqa: E731
    open_f = [f for f in scan.get("findings") or [] if is_open(f)]
    stale = [f for f in scan.get("findings") or [] if not is_open(f)]
    counts = {s: sum(1 for f in open_f if f.get("severity") == s) for s in SEVERITIES}
    unchecked = [t for t in takes if t not in checked or t in remade]
    clean = counts["block"] == 0 and not unchecked and not list_stale and bool(scan)
    step = None
    if list_stale or remade or (unchecked and lst is None):
        step = "sheets"
    elif unchecked or not scan:
        step = "record"
    elif counts["block"]:
        step = "triage"
    return {"takes": len(takes), "checked": len(live & checked) - len(remade), "unchecked": unchecked, "remade": remade,
            "list_stale": list_stale, "list_new": sorted(live - set(lst or [])) if list_stale else [],
            "list_gone": sorted(set(lst or []) - live) if list_stale else [], "counts": counts, "open": open_f,
            "stale": len(stale), "release_ok": clean, "recorded": bool(scan), "step": step}


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b))
    except OSError:
        return False


def _refuse_template(pdir: Path, f: Path, doc) -> None:
    """The template is a starting point, never a record: nothing in it was looked at."""
    tpl = pdir / TEMPLATE
    steps = (f"(1) `cp {TEMPLATE} {FINDINGS}` (or rename yours: `mv {f} {FINDINGS}`); (2) open each sheet in "
             f"render/scan/ and look at all six frames; (3) add its name to \"checked\" in {FINDINGS} and each problem to "
             f"\"findings\"; (4) `slop review record {FINDINGS}`")
    if _same_file(f, tpl):
        raise SlopError(f"nothing recorded: {f.name} is the template `slop review scan-sheets` rewrites, not your "
                        f"findings — {steps}")
    try:
        t = json.loads(tpl.read_text(encoding="utf-8")) if tpl.is_file() else None
    except (OSError, json.JSONDecodeError):
        t = None
    if t is not None and doc == t:
        raise SlopError(f"nothing recorded: {f.name} is an unchanged copy of the template (\"checked\" is empty: no "
                        f"sheet was looked at) — {steps}")
    if isinstance(doc, dict) and isinstance(doc.get("checked"), list) and not doc["checked"] and not doc.get("findings"):
        raise SlopError(f"nothing recorded: \"checked\" is empty in {f.name} — {steps}")


def record(pdir: Path, file: Path) -> dict:
    f = Path(file)
    if not f.is_file():
        raise SlopError(f"no file {f} — make it: `cp {TEMPLATE} {FINDINGS}` (after `slop review scan-sheets`), fill it "
                        f"in, then `slop review record {FINDINGS}`")
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{f} is not valid JSON ({e}) — fix it and run `slop review record {f}` again") from e
    _refuse_template(pdir, f, doc)
    findings, checked, errs, complete, extra = _normalize(doc)
    if errs:
        raise SlopError(f"{f} does not match the scan schema (templates/workflows/safety-scan.js), nothing recorded:\n  - "
                        + "\n  - ".join(errs[:15]) + ("\n  …" if len(errs) > 15 else "")
                        + "\nexpected {\"findings\": [{\"clip\": \"c03-t1\", \"time\": 2.4, \"severity\": \"block|fix|note\", "
                          "\"kind\": \"…\", \"what\": \"…\"}], \"checked\": [\"c03-t1\", …], \"given\": N} — fix the file, "
                          f"then `slop review record {f}` again")
    files = _take_files(pdir)
    takes = sorted(files)
    known = set(takes)
    unknown = sorted({x["clip"] for x in findings if x["clip"] not in known and not str(x["clip"]).startswith("plate:")})
    notes: list[str] = []
    if extra.get("workflow") and checked is None:
        # the workflow's result names no takes: it covers the whole edit only if it ran on the edit's own list
        lst = _list_names(pdir)
        of = extra.get("of")
        whole = (complete and isinstance(of, (int, float)) and int(of) == len(takes) and not unknown
                 and (lst is None or set(lst) == known))
        if whole:
            checked = list(takes)
        else:
            checked = sorted({x["clip"] for x in findings} & known)
            why = []
            if isinstance(of, (int, float)) and int(of) != len(takes):
                why.append(f"it covers {int(of)} take(s), the edit plays {len(takes)}")
            if lst is not None and set(lst) != known:
                why.append("render/scan-list.json no longer matches the edit")
            if unknown:
                why.append(f"its findings name take(s) the edit does not play ({', '.join(unknown[:4])})")
            if not complete:
                why.append("it says it did not check everything (ok false or unchecked slices)")
            notes.append("this workflow result does not cover the takes the edit plays now (" + "; ".join(why)
                         + f"): only the {len(checked)} take(s) its findings name count as checked — run `slop review "
                           "scan-sheets`, then the safety-scan workflow again on render/scan-list.json with total "
                           f"{len(takes)}")
            complete = False
    sf = pdir / "render" / "scan" / "scan.json"
    old = json.loads(sf.read_text(encoding="utf-8")) if sf.is_file() else {}
    now = set(checked)
    try:                                     # takes re-made since the last record stay re-made unless re-checked now
        redo = set(state(pdir)["remade"]) - now if sf.is_file() else set()
    except SlopError:
        redo = set()
    sheet_sigs = _sheet_sigs(pdir)
    sigs = dict(old.get("sigs") or {}) if isinstance(old.get("sigs"), dict) else {}
    for c in now & known:                    # the file the sheet was made from (else the file as it is now)
        sig = sheet_sigs.get(c) or take_sig(files.get(c))
        if sig:
            sigs[c] = sig
    for c in redo:                           # a record from before signatures: keep the re-make visible (never matches)
        sigs.setdefault(c, "re-made after it was checked")
    keep = [x for x in old.get("findings") or [] if x.get("clip") not in now]
    new = []
    for x in findings:
        y = dict(x)
        y["id"] = _fid(y)
        y["recorded"] = iso_now()
        new.append(y)
    merged = {"version": 2, "updated": iso_now(), "list": "render/scan-list.json",
              "checked": sorted(set(old.get("checked") or []) | now), "sigs": sigs, "findings": keep + new,
              "records": (old.get("records") or []) + [{"file": str(f), "at": iso_now(), "findings": len(new),
                                                        "checked": len(now), "complete": bool(complete)}]}
    st = state(pdir, merged)
    merged.update({"counts": st["counts"], "unchecked": st["unchecked"], "release_ok": st["release_ok"]})
    atomic_write_json(sf, merged)
    c = st["counts"]
    text = (f"recorded {len(new)} finding(s) on {len(now)} checked item(s) from {f.name} → render/scan/scan.json\n"
            f"scan: {st['checked']}/{st['takes']} takes checked · block {c['block']} · fix {c['fix']} · note {c['note']}")
    for n in notes:
        text += "\n  ! " + n
    if unknown and not notes:
        text += f"\n  ! findings name clips that are not in the take list (typo?): {', '.join(unknown[:8])}"
    if not complete and not notes:
        text += "\n  ! this record says it did not check everything it was given (a slice came back short): re-scan those takes"
    text += "\n" + verdict_text(st)
    return {"ok": True, "recorded": len(new), "checked_now": sorted(now), "unknown_clips": unknown, "complete": bool(complete),
            **{k: st[k] for k in ("takes", "checked", "unchecked", "remade", "list_stale", "counts", "release_ok", "stale",
                                  "step")},
            "scan": str(sf), "text": text}


def verdict_text(st: dict) -> str:
    c = st["counts"]
    if st.get("list_stale"):
        diff = "; ".join(x for x in (f"new: {', '.join(st['list_new'][:6])}" if st.get("list_new") else "",
                                     f"no longer played: {', '.join(st['list_gone'][:6])}" if st.get("list_gone") else "") if x)
        return (f"NOT CLEAN: the edit changed after the scan sheets were made ({diff}) — run `slop review scan-sheets` "
                "(only new or re-made takes get new sheets), look at the new ones and record them")
    if st.get("remade"):
        return (f"NOT CLEAN: {len(st['remade'])} take(s) were re-made after they were checked ({', '.join(st['remade'][:8])}) "
                "— run `slop review scan-sheets` (it re-sheets them), look at those sheets and record them again")
    if st["unchecked"]:
        return (f"NOT CLEAN: {len(st['unchecked'])} take(s) not checked yet ({', '.join(st['unchecked'][:8])}) — look at their "
                "sheets (`slop review scan-sheets` makes them) and record the findings; never count an unscanned take as clean")
    if c["block"]:
        blocks = [f for f in st["open"] if f.get("severity") == "block"]
        return (f"NOT CLEAN: {c['block']} block(s) — " + "; ".join(f"{b['clip']} @{b.get('time', '?')}: {b['what'][:60]}" for b in blocks[:5])
                + " — triage (docs/80 §9.4): fix at the source and re-make, or cut it off screen; then `slop review "
                  "scan-sheets` and record the re-scan")
    tail = f"; {c['fix']} fix(es) to resolve or keep off screen (docs/80 §9.4)" if c["fix"] else ""
    return f"CLEAN: no blocks, every take checked{tail} — the scan gate for the final render is met"


def status(pdir: Path) -> dict:
    sf = pdir / "render" / "scan" / "scan.json"
    if not sf.is_file():
        takes, _ = used_takes(pdir)
        return {"ok": True, "recorded": False, "takes": len(takes), "release_ok": False,
                "step": "sheets" if _list_names(pdir) is None else "record",
                "text": f"no scan recorded yet ({len(takes)} take(s) in the edit): `slop review scan-sheets`, then `cp "
                        f"{TEMPLATE} {FINDINGS}`, look at every sheet and add each take to \"checked\", then "
                        f"`slop review record {FINDINGS}`"}
    st = state(pdir)
    c = st["counts"]
    return {"ok": True, **{k: st[k] for k in ("takes", "checked", "unchecked", "remade", "list_stale", "counts",
                                              "release_ok", "stale", "recorded", "step")},
            "open": st["open"][:50], "scan": str(sf),
            "text": f"scan: {st['checked']}/{st['takes']} takes checked · block {c['block']} · fix {c['fix']} · note {c['note']}"
                    + (f" · {st['stale']} stale (takes no longer in the edit)" if st["stale"] else "") + "\n" + verdict_text(st)}
