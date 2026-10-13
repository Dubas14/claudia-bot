"""The device schema: which `devices[]` entries the render engine can draw, read from the engine's own files.

Sources (read-only; nothing here edits the engine):
  engine/src/devices/*.js   every `D.register('kind', {...})` block: the kind, its aliases, role, accepted timing keys,
                            `defaults`, `example`, and every property name the block reads (p.x, r.x, {x: …}); the
                            camera moves are registered in a loop from camera.js's CAMS table
  engine/DEVICES.md         the catalogue (§8, §9): each kind's documented params (the param tables and "Params:" lines)
                            and its JSON example
  engine/src/devices/_base.js  the anchor and time grammar (engine_grammar()): the SLOT names, the PERSON/FACE labels,
                            the keys resolveTime reads (`spec.x`) and the keys anchorBox reads (`a.x`)

A device entry is `{"kind", "anchor", "params": {…}, "key": "W|B|H|F|T", "at", "until", "priority", "line"}`.
`check_device()` returns (errors, warnings):
  errors    an unknown kind; a param the device never reads (a copied `{"txt": …}` on a split-flap draws UNDEFINED; a
            `readout` given `rows` shows 0); `params` not an object; a timing key that is not one of W B H F T; a time
            spec (`at`, `until`) the engine cannot read; a top-level field the engine ignores (e.g. `word` outside
            `params`); `line` not a lyric line number; a param text that is still a hint placeholder ("…", "<row 1>",
            TODO); NaN/Infinity; a numeric `word` that is no lyric line (the engine reads a number there as a LINE);
            on a board (board=True), on-screen text still equal to the catalogue example's (`--example` copied it)
  warnings  a timing key the device does not list; an anchor shape the engine does not know (a misspelt slot such as
            "centre"); a uv anchor outside 0..1; a detection label with no box on the shot's plate (`slop plates box`)
            that is not a person label; a key-W word not sung in the shot; a numeric `word` that is a lyric line (it
            means that line's first word, not the sung number); `line` on a camera move (never a graphic)
`parse_params` keeps word / word_end / at / until as text (`--param word=13` is the sung word "13").
This is the checker `tests/test_docs_a.py` used for the storyboard doc's examples, moved here so `slop board audit`
(gate "devices"), `slop board device add` and `slop board fill` share it. The accepted param set is deliberately
permissive (every property name the device's block mentions + the base keys every device reads): it fails only on
names the device can never read.
"""
from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path

from ..config import SlopError, engine_dir
from .common import placeholder
from .vocab import js_value, literal_after, plain

KEYS = "WBHFT"
# params the device base reads for every device (engine/src/devices/_base.js: instance, ctx, place; shots.js)
BASE_PARAM_KEYS = {"color", "alpha", "x", "y", "slot", "at", "until", "keys", "word", "hit", "n", "t", "take", "clip",
                   "beat", "fadeOut", "anchor", "value", "priority", "is_line", "line", "size", "w", "h"}
# top-level fields of a devices[] entry the engine (or the board audit) reads
ENTRY_FIELDS = {"kind", "device", "anchor", "params", "key", "at", "until", "priority", "line", "notes", "note", "why",
                "id"}
# The anchor and time vocabulary is read from engine/src/devices/_base.js (engine_grammar()): the SLOT table, the PERSON
# and FACE label patterns, every key resolveTime/hitTime read (`spec.x`) and every key anchorBox reads (`a.x`). The
# sets below are only the fallback when that file cannot be read (they mirror it as of this checkout).
TIME_KEYS = {"word", "word_end", "line", "line_end", "beat", "bar", "beats", "eighths", "sixteenths", "from", "hit", "n",
             "near", "win", "minS", "take", "clip", "offset", "frame_nearest", "t"}
SLOTS = {"top-left", "top-right", "bottom-left", "bottom-right", "left", "right", "top", "bottom", "center", "auto"}
SLOT_SPELLINGS = {"centre": "center", "middle": "center", "topleft": "top-left", "topright": "top-right",
                  "bottomleft": "bottom-left", "bottomright": "bottom-right"}
PERSON_RE = re.compile(r"^(subject|lead|the lead|a person|a woman|a man|a girl|a boy|a singer|her|him|person|woman|man"
                       r"|singer)$", re.I)
FACE_RE = re.compile(r"^(a |the )?(face|head)$", re.I)
ANCHOR_KEYS = {"uv", "rect", "xy", "slot", "box", "track", "label", "pad", "keys", "clip", "w", "h"}
JS_METHODS = {"trim", "map", "length", "slice", "filter", "forEach", "concat", "toString", "indexOf"}
# params whose text the device draws on screen: copied unchanged from the catalogue example they are not this song's
CONTENT_PARAMS = {"rows", "label", "labels", "title", "text", "sub", "kicker", "caption", "items", "lines", "msgs",
                  "next", "words", "total", "serial", "status", "script", "full", "levels", "attractors", "pts"}
# params read as text (a word or a time), never as a JSON number: `word=13` is the sung word "13", not lyric line 13
TEXT_PARAMS = {"word", "word_end", "at", "until"}


@lru_cache(maxsize=1)
def engine_grammar() -> dict:
    """{"slots", "person", "face", "time_keys", "anchor_keys", "source"} from engine/src/devices/_base.js."""
    out = {"slots": set(SLOTS), "person": PERSON_RE, "face": FACE_RE, "time_keys": set(TIME_KEYS),
           "anchor_keys": set(ANCHOR_KEYS), "source": "fallback (engine/src/devices/_base.js unreadable)"}
    try:
        src = (engine_dir() / "src" / "devices" / "_base.js").read_text(encoding="utf-8")
    except OSError:
        return out
    slot = literal_after(src, r"const\s+SLOT\s*=\s*")
    if isinstance(slot, dict) and slot:
        out["slots"] = set(slot)
    for name in ("PERSON", "FACE"):
        m = re.search(r"const\s+" + name + r"\s*=\s*/(.+?)/([a-z]*)\s*;", src)
        if m:
            try:
                out[name.lower()] = re.compile(m.group(1), re.I if "i" in m.group(2) else 0)
            except re.error:
                pass
    a, b = src.find("function resolveTime"), src.find("function takeTime")
    if 0 <= a < b:
        keys = set(re.findall(r"(?<![\w.])spec\.(\w+)", src[a:b])) - JS_METHODS
        if {"word", "beats", "hit"} <= keys:
            out["time_keys"] = keys
    a, b = src.find("function anchorBox"), src.find("const SLOT")
    if 0 <= a < b:
        keys = set(re.findall(r"(?<![\w.])a\.(\w+)", src[a:b])) - JS_METHODS
        if {"uv", "rect", "slot"} <= keys:
            out["anchor_keys"] = keys
    out["source"] = "engine/src/devices/_base.js"
    return out


def is_person_label(label: str) -> bool:
    g = engine_grammar()
    return bool(g["person"].match(label) or g["face"].match(label))


# ------------------------------------------------------------------------------------------------ the registry
def _block_names(block: str) -> set[str]:
    """Every property name a register block reads or declares (the docs test's rule: x.name and {name: …})."""
    return set(re.findall(r"\b[a-z]\w*\.(\w+)", block)) | set(re.findall(r"[{,]\s*([A-Za-z_]\w*)\s*:", block))


def _doc_sections() -> dict[str, dict]:
    """engine/DEVICES.md catalogue: kind -> {"params": set, "aliases": [...], "examples": [dict], "keys": "WB…"}."""
    p = engine_dir() / "DEVICES.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, dict] = {}
    parts = re.split(r"(?m)^### `([^`]+)`\s*$", text)
    for k in range(1, len(parts), 2):
        kind, body = parts[k], parts[k + 1]
        body = re.split(r"(?m)^## ", body)[0]
        params: set[str] = set()
        for row in re.findall(r"(?m)^\|([^|]*)\|", body):
            if "param" in row.lower() or set(row.strip()) <= {"-", ":", " "}:
                continue
            params |= set(re.findall(r"`([A-Za-z_]\w*)`", row))
        for line in re.findall(r"(?m)^.*\bParams:.*$(?:\n(?!```|\n).*)*", body):
            params |= set(re.findall(r"`([A-Za-z_]\w*)`", line))
        al = re.search(r"(?m)^Aliases?\s+(.+?)\.\s", body)
        aliases = re.findall(r"`([^`]+)`", al.group(1)) if al else []
        examples = []
        for b in re.findall(r"```json\n(.*?)\n```", body, flags=re.S):
            try:
                ex = json.loads(b)
            except ValueError:
                continue
            if isinstance(ex, dict) and ex.get("kind"):
                examples.append(ex)
        km = re.search(r"(?m)^Keys:\s*([WBHFT ]+)", body)
        out[kind] = {"params": params, "aliases": aliases, "examples": examples,
                     "keys": km.group(1).replace(" ", "") if km else None}
    return out


@lru_cache(maxsize=1)
def registry() -> dict[str, dict]:
    """kind (and every alias) -> {kind, aliases, role, keys, defaults, example, names, documented, doc, file}.

    The same dict object is shared by a kind and its aliases. Raises SlopError when the engine's device files are
    missing (a partial checkout: re-run bin/setup.sh)."""
    ddir = engine_dir() / "src" / "devices"
    files = sorted(ddir.glob("*.js")) if ddir.is_dir() else []
    try:                                       # only the files the engine page loads (devices/index.js FILES)
        listed = literal_after((ddir / "index.js").read_text(encoding="utf-8"), r"const\s+FILES\s*=\s*")
    except OSError:
        listed = None
    if isinstance(listed, list) and listed:
        files = [ddir / f for f in listed if isinstance(f, str) and (ddir / f).is_file()]
    if not files:
        raise SlopError(f"the engine's device library is missing ({ddir}): re-install the toolkit (bin/setup.sh)")
    docs = _doc_sections()
    reg: dict[str, dict] = {}

    def add(kind: str, aliases: list[str], role: str, keys: str, defaults, example, names: set[str], doc: str,
            fname: str, word_param: bool = True) -> None:
        d = docs.get(kind) or {}
        ex_names: set[str] = set()
        for ex in d.get("examples") or []:
            ex_names |= set((ex.get("params") or {}).keys())
        spec = {"kind": kind, "aliases": list(dict.fromkeys(aliases + [a for a in d.get("aliases", []) if a != kind])),
                "role": role, "keys": keys or KEYS, "defaults": defaults if isinstance(defaults, dict) else {},
                "example": example if isinstance(example, dict) else None,
                "doc_example": (d.get("examples") or [None])[0], "doc": doc,
                "names": set(names) | set((defaults or {}).keys() if isinstance(defaults, dict) else ())
                | set(d.get("params") or ()) | ex_names,
                "documented": sorted(d.get("params") or ()), "doc_keys": d.get("keys"), "file": fname,
                "word_param": word_param}
        for k in [kind] + spec["aliases"]:
            reg.setdefault(k, spec)

    for js in files:
        src = js.read_text(encoding="utf-8")
        starts = list(re.finditer(r"D\.register\('([^']+)'", src))
        for k, m in enumerate(starts):
            block = src[m.start(): starts[k + 1].start() if k + 1 < len(starts) else len(src)]
            kind = m.group(1)
            al = literal_after(block, r"\balias\s*:\s*")
            aliases = [a for a in (al or []) if isinstance(a, str)] if isinstance(al, list) else []
            role = literal_after(block, r"\brole\s*:\s*")
            keys = literal_after(block, r"\bkeys\s*:\s*(?=')")
            defaults = literal_after(block, r"\bdefaults\s*:\s*")
            example = literal_after(block, r"\bexample\s*:\s*")
            doc = literal_after(block, r"\bdoc\s*:\s*")
            wp = literal_after(block, r"\bwordParam\s*:\s*")
            add(kind, aliases, role if isinstance(role, str) else "hero", keys if isinstance(keys, str) else KEYS,
                plain(defaults) if isinstance(defaults, dict) else {}, plain(example) if isinstance(example, dict) else None,
                _block_names(block), doc if isinstance(doc, str) else "", js.name, wp is not False)
        cams = literal_after(src, r"const\s+CAMS\s*=\s*") if "CAMS" in src else None
        if isinstance(cams, dict):                     # camera.js registers its moves in a loop over CAMS
            docs_js = literal_after(src, r"const\s+DOC\s*=\s*")
            body = src[src.find("D.camFx"):] if "D.camFx" in src else ""
            for kind, defaults in cams.items():
                dflt = plain(defaults) if isinstance(defaults, dict) else {}
                add(kind, [kind.replace("cam.", "camera.")], "camera", "BHFW", dflt,
                    {"kind": kind, "key": "B", "params": {"at": "shot.t1"} if kind == "cam.whip" else {}},
                    set(dflt) | _block_names(body), (docs_js or {}).get(kind, "") if isinstance(docs_js, dict) else "",
                    js.name)
    if not reg:
        raise SlopError(f"no device registrations found in {ddir}: re-install the toolkit (bin/setup.sh)")
    return reg


def kinds() -> list[str]:
    """The canonical kinds (no aliases), sorted by role then name."""
    reg = registry()
    canon = {s["kind"]: s for s in reg.values()}
    order = {"cv": 0, "micro": 1, "hero": 2, "flash": 3, "camera": 4}
    return sorted(canon, key=lambda k: (order.get(canon[k]["role"], 5), k))


def spec_of(kind: str) -> dict | None:
    return registry().get(str(kind or ""))


def allowed_params(spec: dict) -> set[str]:
    return set(spec["names"]) | BASE_PARAM_KEYS


def example_of(kind: str) -> dict | None:
    """The device's example entry (DEVICES.md first: it is written for boards; else the JS `example`)."""
    s = spec_of(kind)
    if not s:
        return None
    ex = s.get("doc_example") or s.get("example")
    return json.loads(json.dumps(ex)) if ex else None


def suggest(name: str, pool) -> str | None:
    import difflib
    m = difflib.get_close_matches(str(name), list(pool), n=1, cutoff=0.6)
    return m[0] if m else None


# ------------------------------------------------------------------------------------------------ time specs, anchors
def time_spec_problem(v, where: str) -> str | None:
    """None when the engine's time grammar can read v (a number, a string, or an object with known keys)."""
    if v is None or isinstance(v, (int, float, str)) and not isinstance(v, bool):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return f"{where}: {v} is not a time (a number of seconds, a word, \"shot.t0\", or {{\"beats\": 2}})"
    if isinstance(v, dict):
        keys = engine_grammar()["time_keys"]
        bad = [k for k in v if k not in keys]
        if bad:
            return (f"{where}: {json.dumps(v)[:60]} has key(s) {', '.join(bad)} the time grammar does not read "
                    "(use word, word_end, line, line_end, beat, bar, beats, eighths, sixteenths, hit (+ n/near), take, "
                    "offset (+ from), t, or a number of song seconds)")
        if "from" in v:
            return time_spec_problem(v["from"], f"{where}.from")
        return None
    return f"{where}: {json.dumps(v)[:60]} is not a time (a number of seconds, a word, \"shot.t0\", or {{\"beats\": 2}})"


def _box_hint(label: str) -> str:
    return (f"add the box: `slop -p P plates box PLATE --label \"{label}\" --uv u,v,w,h`, or use {{\"uv\": [u, v]}} / "
            "a slot (top-left, right, auto…)")


def _uv_problem(uv) -> str | None:
    if not (isinstance(uv, list) and len(uv) in (2, 4)
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in uv)):
        return "anchor uv must be [u, v] or [u, v, w, h] in 0..1 of the image"
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in uv) \
            or (len(uv) == 4 and (uv[0] + uv[2] > 1.001 or uv[1] + uv[3] > 1.001 or uv[2] <= 0 or uv[3] <= 0)):
        return (f"anchor uv {json.dumps(uv)} is outside the image: u, v (and w, h) are fractions 0..1 of the picture "
                "(0,0 = top-left; u+w and v+h at most 1) — the device would draw off-frame")
    return None


def anchor_problem(a, boxes: dict | None = None) -> str | None:
    """A warning for an anchor the engine resolves to nothing (None when it can resolve). Mirrors _base.js anchorBox
    and DEV.anchorProblem: 'lead'/'subject', the SLOT names (exact spelling), the PERSON/FACE labels, a box on the
    shot's plate, [x, y(, w, h)], {uv|rect|xy|slot|box|track|label|keys}."""
    if a is None:
        return None
    g = engine_grammar()
    if isinstance(a, str):
        s = a.strip()
        if s in ("lead", "subject") or s in g["slots"] or is_person_label(s):
            return None
        if boxes is not None and s in boxes:
            return None
        fix = slot_name(s)
        if fix:
            return f"anchor '{s}' is not a slot the engine knows — write '{fix}' (slots: {', '.join(sorted(g['slots']))})"
        return f"anchor '{s}' is a detection label with no box on this shot's plate — the device draws nothing; " + \
            _box_hint(s)
    if isinstance(a, list):
        if len(a) in (2, 4) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in a):
            return None
        return f"anchor {json.dumps(a)[:40]}: a list anchor is [x, y] or [x, y, w, h] in screen pixels"
    if isinstance(a, dict):
        bad = [k for k in a if k not in g["anchor_keys"]]
        if bad:
            return (f"anchor {json.dumps(a)[:60]}: unknown key(s) {', '.join(bad)} (the engine reads "
                    f"{', '.join(sorted(g['anchor_keys']))})")
        if "uv" in a:
            p = _uv_problem(a["uv"])
            if p:
                return p
        for k in ("box", "track", "label"):
            v = a.get(k)
            if isinstance(v, str) and v not in ("lead", "subject") and not is_person_label(v) \
                    and (boxes is None or v not in boxes):
                return f"anchor {{\"{k}\": \"{v}\"}}: no such box on this shot's plate — " + _box_hint(v)
        return None
    return f"anchor {json.dumps(a)[:40]} is not an anchor (\"lead\", a slot name, {{\"uv\": [u, v]}}, {{\"rect\": [x, y, w, h]}})"


def _strings(v, path: str):
    """(path, text) for every string inside a param value (lists and objects walked)."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _strings(x, f"{path}[{i}]")
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _strings(x, f"{path}.{k}")


def _nonfinite(v) -> bool:
    if isinstance(v, float):
        return not math.isfinite(v)
    if isinstance(v, list):
        return any(_nonfinite(x) for x in v)
    if isinstance(v, dict):
        return any(_nonfinite(x) for x in v.values())
    return False


# ------------------------------------------------------------------------------------------------ one device
def example_text(kind: str, params: dict) -> list[str]:
    """The on-screen text params still equal to the catalogue example's (copied by `--example`, never rewritten)."""
    ex = (example_of(kind) or {}).get("params") or {}
    return [k for k in sorted(CONTENT_PARAMS & set(params) & set(ex))
            if params[k] == ex[k] and any(re.search(r"[^\W\d_]", s) for _, s in _strings(ex[k], k))]


def check_device(dev, lines: set[int] | None = None, boxes: dict | None = None,
                 shot_words: list[str] | None = None, board: bool = False) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one devices[] entry. `lines`: the lyric line numbers that exist (None: not checked);
    `boxes`: the detection boxes of the shot's plate (plates/boxes.json); `shot_words`: the words sung in the shot;
    `board`: the entry is on a song's board (device add, fill, the audit), so on-screen text still equal to the
    catalogue example's is an error (the docs' own examples are checked with board=False)."""
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(dev, dict):
        return [f"{json.dumps(dev)[:50]} is not a device object {{\"kind\": …, \"params\": {{…}}}}"], []
    kind = dev.get("kind") or dev.get("device")
    if not kind:
        return ["a device without a kind (e.g. {\"kind\": \"callout\", …}; `slop board device kinds` lists them)"], []
    spec = spec_of(kind)
    if spec is None:
        near = suggest(kind, registry())
        return [f"unknown device kind '{kind}'" + (f" (did you mean '{near}'?)" if near else "")
                + " — `slop board device kinds` lists the engine's devices"], []
    for f in dev:
        if f not in ENTRY_FIELDS:
            hint = " — put it inside params" if f in allowed_params(spec) else ""
            errs.append(f"{kind}: top-level field '{f}' is not read by the engine{hint}")
    params = dev.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        errs.append(f"{kind}: params must be an object {{…}}, not {type(params).__name__}")
        params = {}
    ok = allowed_params(spec)
    for k, v in params.items():
        if k not in ok:
            near = suggest(k, spec["defaults"]) or suggest(k, set(spec["documented"]) | ok)
            errs.append(f"{kind}: param '{k}' is not read by this device" + (f" (did you mean '{near}'?)" if near else "")
                        + f" — its params: {', '.join(sorted(spec['defaults'])) or '(none)'}")
        for row in v if isinstance(v, list) else []:
            for rk in row if isinstance(row, dict) else []:
                if rk not in ok:
                    errs.append(f"{kind}: {k}[].{rk} is not read by this device")
        for path, sv in _strings(v, k):
            ph = placeholder(sv, words=False)
            if ph:
                errs.append(f"{kind}: params.{path}: {ph} — write the text the device shows (what the line means)")
                break
        if _nonfinite(v):
            errs.append(f"{kind}: params.{k} is NaN or Infinity — give a real number")
    if board:
        copied = example_text(spec["kind"], params)
        if copied:
            errs.append(f"{kind}: the on-screen text in params.{', params.'.join(copied)} is still the catalogue "
                        "example's "
                        f"({json.dumps(params[copied[0]], ensure_ascii=False)[:60]}) — write this song's own words: "
                        + " ".join(f"--param '{k}=" + ('["<row 1>", "<row 2>"]' if isinstance(params[k], list)
                                                       else "<the text>") + "'" for k in copied))
    key = dev.get("key")
    if key is not None:
        kk = str(key).strip().upper()
        if kk not in tuple(KEYS):
            errs.append(f"{kind}: key '{key}' is not one of W B H F T (W word, B beat, H hit, F fixed seconds, T take)")
        else:
            listed = (spec.get("doc_keys") or spec.get("keys") or KEYS).upper()
            if kk not in listed:
                warns.append(f"{kind}: key {kk} — this device is timed by {' '.join(listed)} (engine/DEVICES.md)")
    for f in ("at", "until"):
        if f in dev:
            p = time_spec_problem(dev[f], f"{kind}.{f}")
            if p:
                errs.append(p)
    for f in ("at", "until"):
        if f in params:
            p = time_spec_problem(params[f], f"{kind}.params.{f}")
            if p:
                errs.append(p)
    if "line" in dev:
        li = dev["line"]
        if not isinstance(li, int) or isinstance(li, bool):
            errs.append(f"{kind}: line must be a lyric line number (0-based), not {li!r}")
        elif lines is not None and li not in lines:
            errs.append(f"{kind}: line {li} is not a lyric line of analysis/words.json (lines {min(lines, default=0)}–"
                        f"{max(lines, default=0)})")
    if "priority" in dev and not isinstance(dev["priority"], (int, float)):
        errs.append(f"{kind}: priority must be a number")
    aw = anchor_problem(dev.get("anchor"), boxes)
    if aw:
        warns.append(f"{kind}: {aw}")
    if spec.get("role") == "camera" and "line" in dev:
        warns.append(f"{kind}: a camera move draws nothing, so it is never a line's explaining graphic — drop its "
                     "\"line\" (the graphics gate does not count it)")
    w = params.get("word")
    if shot_words is not None and spec.get("word_param", True) and isinstance(w, str) and w.strip():
        norm = re.sub(r"[^\w%$+\-]", "", w.lower())
        if norm and not any(x.startswith(norm) for x in shot_words):
            warns.append(f"{kind}: word '{w}' is not sung in this shot — the device would start at the shot start "
                         "(pick a word sung inside the shot, or move the device)")
    for wk in ("word", "word_end"):                  # _base.js tokenInfo: a number is a LYRIC LINE, not a sung word
        wv = params.get(wk)
        if wk == "word" and not spec.get("word_param", True):
            break                                    # the device draws params.word as text: never a time
        if isinstance(wv, (int, float)) and not isinstance(wv, bool):
            as_text = f"--param {wk}={wv:g}" if isinstance(wv, (int, float)) and math.isfinite(wv) else ""
            if lines is not None and (not float(wv).is_integer() or int(wv) not in lines):
                errs.append(f"{kind}: params.{wk} is the number {wv:g}, which the engine reads as lyric line {wv:g} "
                            f"(there is no such line) — for the sung word \"{wv:g}\" write it as text: \"{wk}\": "
                            f"\"{wv:g}\" ({as_text} does that)")
            else:
                warns.append(f"{kind}: params.{wk} {wv:g} is a number: the engine enters on line {wv:g}'s first word. "
                             f"To mean the sung word \"{wv:g}\", write it as text: \"{wk}\": \"{wv:g}\"")
    return errs, warns


def _word_norm(s: str) -> str:
    return re.sub(r"[^\w%$+\-]", "", str(s or "").lower())


def display_tokens(pdir: Path, W: dict) -> list[dict]:
    """The on-screen tokens the engine matches a `word` param against (lyrics/display.txt through the export's
    build_lyr: "13" where the aligner heard "Thirteen"), flat [{txt, t0, …}]; [] when there is no display.txt or it
    does not fit the aligned words (`slop edit export` reports that)."""
    if not (Path(pdir) / "lyrics/display.txt").is_file():
        return []
    try:
        from ..edit.export import build_lyr
        lyr, _ = build_lyr(Path(pdir), W)
    except Exception:  # noqa: BLE001 - a display.txt that does not fit: the export says why
        return []
    return [tk for ln in lyr if isinstance(ln, dict) for tk in ln.get("tokens") or [] if isinstance(tk, dict)]


def shot_word_list(sh: dict, words: list[dict], display_tokens: list[dict] | None = None) -> list[str]:
    """Normalised words (aligned words + display tokens) sung inside a shot's span."""
    t0, t1 = float(sh["t0"]) - .05, float(sh["t1"]) + .05
    out = [_word_norm(w.get("w", "")) for w in words if t0 <= float(w["t0"]) < t1]
    for tk in display_tokens or []:
        if tk.get("t0") is not None and t0 <= float(tk["t0"]) < t1:
            out.append(_word_norm(tk.get("txt", "")))
    return [w for w in out if w]


# ------------------------------------------------------------------------------------------------ a board
def check_board(S: dict, lines: set[int] | None = None, boxes_by_plate: dict | None = None,
                words: list[dict] | None = None, shot_plate=None, tokens: list[dict] | None = None) -> dict:
    """{"errors": [msg], "warnings": [msg], "devices": n} over every shot's devices[] (messages name the shot)."""
    errors: list[str] = []
    warnings: list[str] = []
    n = 0
    for sh in S.get("shots") or []:
        devs = sh.get("devices")
        if devs is None or devs == []:
            continue
        sid = sh.get("id", "?")
        if not isinstance(devs, list):
            errors.append(f"{sid}.devices must be a list [...]")
            continue
        plate = shot_plate(sh) if shot_plate else sh.get("plate")
        boxes = (boxes_by_plate or {}).get(plate) if plate else None
        sw = shot_word_list(sh, words, tokens) if words is not None else None
        for i, d in enumerate(devs):
            n += 1
            e, w = check_device(d, lines, boxes if boxes_by_plate is not None else None, sw, board=True)
            errors += [f"{sid}.devices[{i}] {m}" for m in e]
            warnings += [f"{sid}.devices[{i}] {m}" for m in w]
    return {"errors": errors, "warnings": warnings, "devices": n}


def is_graphic(dev) -> bool:
    """A device that draws something (camera moves draw nothing: they never count as an explaining graphic)."""
    if not isinstance(dev, dict):
        return bool(dev)
    s = spec_of(dev.get("kind") or dev.get("device") or "")
    try:
        return not (s and s.get("role") == "camera")
    except Exception:  # noqa: BLE001
        return True


# ------------------------------------------------------------------------------------------------ CLI value parsing
def _no_constant(name: str):
    raise ValueError(f"{name} is not a number the engine can use")


def parse_value(v: str, text: bool = False, what: str = "value"):
    """A --param / --at value: JSON when it parses (numbers, true, null, [..], {..}, "quoted"), else the raw text.
    text=True (word, word_end, at, until params): only [..], {..} and "quoted" are JSON; anything else stays text, so
    `word=13` is the sung word "13" (a number there is a lyric line to the engine). NaN / Infinity are refused."""
    s = v.strip()
    if s == "":
        return ""
    if text and s[0] not in "[{\"":
        return s
    try:
        out = json.loads(s, parse_constant=_no_constant)
    except ValueError as e:
        if "is not a number the engine" in str(e):
            raise SlopError(f"{what} {v!r}: NaN / Infinity is not a value the engine can draw — give a real number; "
                            "nothing was changed") from e
        return v
    if _nonfinite(out):
        raise SlopError(f"{what} {v!r}: NaN / Infinity is not a value the engine can draw; nothing was changed")
    return out


def parse_params(pairs: list[str]) -> dict:
    out: dict = {}
    for p in pairs or []:
        k, eq, v = p.partition("=")
        k = k.strip()
        if not eq or not re.fullmatch(r"[A-Za-z_][\w]*", k):
            raise SlopError(f"--param {p!r}: write NAME=VALUE (e.g. --param word=walk --param 'rows=[\"LINE 01\", "
                            "\"TEXT\"]'); nothing was changed")
        out[k] = parse_value(v, text=k in TEXT_PARAMS, what=f"--param {k}=")
    return out


def parse_anchor(v: str | None):
    """--anchor: "lead", a slot ("top-left"), "uv:0.62,0.4[,w,h]", "rect:x,y,w,h", "box:a face", "track:a person",
    or JSON ({"uv": [0.6, 0.4]})."""
    if v is None:
        return None
    s = v.strip()
    if not s:
        return None
    if s[0] in "{[":
        try:
            return json.loads(s)
        except ValueError as e:
            raise SlopError(f"--anchor {v!r} is not valid JSON ({e}); nothing was changed") from e
    m = re.fullmatch(r"(uv|rect|xy)\s*[:=]\s*(.+)", s, re.I)
    if m:
        try:
            nums = [float(x) for x in re.split(r"[,\s]+", m.group(2).strip()) if x]
        except ValueError as e:
            raise SlopError(f"--anchor {v!r}: {m.group(1)} takes numbers, e.g. uv:0.62,0.40; nothing was changed") from e
        return {m.group(1).lower(): nums}
    m = re.fullmatch(r"(box|track|slot|label)\s*[:=]\s*(.+)", s, re.I)
    if m:
        return {m.group(1).lower(): m.group(2).strip()}
    return slot_name(s) or s


def slot_name(s: str) -> str | None:
    """The engine's spelling of a slot name written another way ("centre" -> "center", "Top Left" -> "top-left");
    None when `s` is not a slot (the engine's SLOT table is exact: anything else is read as a detection label)."""
    slots = engine_grammar()["slots"]
    k = re.sub(r"[\s_]+", "-", str(s).strip().lower())
    if k in slots:
        return k
    k = SLOT_SPELLINGS.get(k.replace("-", "")) or SLOT_SPELLINGS.get(k)
    return k if k in slots else None


def describe(kind: str) -> str:
    """A short help block for one kind: role, aliases, params with defaults, keys, the example entry."""
    s = spec_of(kind)
    if not s:
        raise SlopError(f"unknown device kind '{kind}' — `slop board device kinds` lists them")
    ex = example_of(kind)
    dflt = ", ".join(f"{k}={json.dumps(v)}" for k, v in s["defaults"].items()) or "(none)"
    out = [f"{s['kind']} · role {s['role']}" + (f" · aliases {', '.join(s['aliases'])}" if s["aliases"] else ""),
           f"  {s['doc']}" if s["doc"] else "", f"  params (defaults): {dflt}",
           f"  keys: {s.get('doc_keys') or s.get('keys')}"]
    if ex:
        out.append("  example: " + json.dumps(ex, ensure_ascii=False))
    return "\n".join(x for x in out if x)


__all__ = ["registry", "kinds", "spec_of", "allowed_params", "example_of", "check_device", "check_board", "is_graphic",
           "parse_params", "parse_anchor", "parse_value", "describe", "time_spec_problem", "anchor_problem",
           "engine_grammar", "slot_name", "example_text", "is_person_label", "BASE_PARAM_KEYS", "KEYS"]


def _selftest() -> None:  # pragma: no cover - a manual check: python -m slop.board.devices
    reg = registry()
    print(len(kinds()), "kinds;", len(reg), "names incl. aliases")
    for k in kinds():
        print(describe(k).splitlines()[0])


if __name__ == "__main__":  # pragma: no cover
    _selftest()
