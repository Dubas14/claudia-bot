"""The render engine's vocabulary, read from the engine's own files so the board tools never drift from what draws.

  treatments   engine/src/devices/treat.js   ALIAS table, FAMS, CODES and its parse() rules (ported below)
  transitions  engine/src/devices/trans.js   PRESETS + ALIAS (+ the prose rules); engine/src/trans.js registry + alias
  fonts        engine/fonts/fonts.js         window.ENGINE_FONTS (strict JSON after "=")

Nothing here edits the engine. When a file cannot be read (a partial checkout), the fallback tables below (copies of
the engine's tables when this module was written) are used and `source()` says so.

`js_value(text, i)` is a small tolerant reader for JavaScript object/array literals: strings, numbers (".5"), true/false/
null, nested {} and [] become Python values; anything else (an expression, an arrow function, a method) becomes
UNKNOWN and is skipped without breaking the parse. The device schema (devices.py) uses it for `defaults` and `example`.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..config import engine_dir


class _Unknown:
    """A literal value the reader could not evaluate (an expression); compares unequal to everything."""

    def __repr__(self) -> str:
        return "UNKNOWN"


UNKNOWN = _Unknown()
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


# ------------------------------------------------------------------------------------------------ the literal reader
def _skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n:
        if s[i].isspace():
            i += 1
        elif s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j < 0 else j + 1
        elif s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            break
    return i


def _string(s: str, i: int) -> tuple[str, int]:
    q = s[i]
    i += 1
    out = []
    esc = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nx = s[i + 1]
            if nx == "u" and re.match(r"[0-9a-fA-F]{4}", s[i + 2:i + 6]):
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(esc.get(nx, nx))
            i += 2
            continue
        if c == q:
            return "".join(out), i + 1
        out.append(c)
        i += 1
    raise ValueError("unterminated string")


_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}


def skip_expr(s: str, i: int, stops: str = ",}]);") -> int:
    """Skip a JS expression (strings, template literals, regex literals and nested brackets aware) up to a stop
    character at depth 0; returns the index of that stop character (or len(s))."""
    depth = 0
    prev = ""
    n = len(s)
    while i < n:
        c = s[i]
        if c in "'\"`":
            try:
                _, i = _string(s, i)
            except ValueError:
                return n
            prev = "a"
            continue
        if s.startswith("//", i) or s.startswith("/*", i):
            i = _skip_ws(s, i)
            continue
        if c == "/" and prev in _REGEX_PREV:          # a regex literal
            j = i + 1
            cls = False
            while j < n:
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == "[":
                    cls = True
                elif s[j] == "]":
                    cls = False
                elif s[j] == "/" and not cls:
                    break
                elif s[j] == "\n":
                    break
                j += 1
            i = j + 1
            while i < n and s[i].isalpha():
                i += 1
            prev = "a"
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c in stops and depth == 0:
            return i
        if not c.isspace():
            m = _IDENT.match(s, i)
            if m:
                word = m.group(0)
                prev = "" if word in ("return", "typeof", "case", "in", "of", "new", "delete", "void") else "a"
                i = m.end()
                continue
            prev = c if c in _REGEX_PREV else "a"
        i += 1
    return n


def js_value(s: str, i: int = 0):
    """(value, end index) of the JS literal starting at s[i]; UNKNOWN for expressions."""
    i = _skip_ws(s, i)
    if i >= len(s):
        raise ValueError("no value")
    c = s[i]
    start = i
    if c == "{":
        out: dict = {}
        i += 1
        while True:
            i = _skip_ws(s, i)
            if i >= len(s):
                raise ValueError("unterminated object")
            if s[i] == "}":
                i += 1
                break
            if s.startswith("...", i):                        # a spread: skip it
                i = skip_expr(s, i + 3)
            else:
                if s[i] in "'\"":
                    key, i = _string(s, i)
                elif s[i] == "[":                              # a computed key: skip key and value
                    i = skip_expr(s, i)
                    key = None
                else:
                    m = _IDENT.match(s, i) or _NUM.match(s, i)
                    if not m:
                        raise ValueError(f"bad key at {i}")
                    key = m.group(0)
                    i = m.end()
                    if key in ("async", "get", "set", "static") and _IDENT.match(s, _skip_ws(s, i)):
                        m2 = _IDENT.match(s, _skip_ws(s, i))
                        key, i = m2.group(0), m2.end()
                i = _skip_ws(s, i)
                if i < len(s) and s[i] == ":":
                    try:
                        val, i = js_value(s, i + 1)
                    except ValueError:
                        val, i = UNKNOWN, skip_expr(s, i + 1)
                elif i < len(s) and s[i] == "(":                # a method: name(args) { body }
                    i = skip_expr(s, i + 1, stops=")") + 1
                    i = _skip_ws(s, i)
                    if i < len(s) and s[i] == "{":
                        i = skip_expr(s, i + 1, stops="}") + 1
                    val = UNKNOWN
                else:                                           # shorthand {defaults, ...}
                    val = UNKNOWN
                if key is not None:
                    out[key] = val
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "}":
                i += 1
                break
            else:
                i = skip_expr(s, i)
                if i < len(s) and s[i] == ",":
                    i += 1
        return _after(s, start, i, out)
    if c == "[":
        arr = []
        i += 1
        while True:
            i = _skip_ws(s, i)
            if i >= len(s):
                raise ValueError("unterminated array")
            if s[i] == "]":
                i += 1
                break
            try:
                val, i = js_value(s, i)
            except ValueError:
                val, i = UNKNOWN, skip_expr(s, i)
            arr.append(val)
            i = _skip_ws(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
            elif i < len(s) and s[i] == "]":
                i += 1
                break
            else:
                i = skip_expr(s, i)
        return _after(s, start, i, arr)
    if c in "'\"":
        v, i = _string(s, i)
        return _after(s, start, i, v)
    if c == "`":
        v, i = _string(s, i)
        return _after(s, start, i, v if "${" not in v else UNKNOWN)
    m = _NUM.match(s, i)
    if m and (c.isdigit() or c in ".-"):
        txt = m.group(0)
        v = float(txt) if any(ch in txt for ch in ".eE") else int(txt)
        return _after(s, start, m.end(), v)
    m = _IDENT.match(s, i)
    if m:
        word = m.group(0)
        lit = {"true": True, "false": False, "null": None, "undefined": None}
        if word in lit:
            return _after(s, start, m.end(), lit[word])
    return UNKNOWN, skip_expr(s, i)


def _after(s: str, start: int, i: int, val):
    """A literal followed by an operator (`.5 * 2`, `'a' + b`) is an expression: UNKNOWN."""
    j = _skip_ws(s, i)
    if j < len(s) and s[j] not in ",}]);:":
        return UNKNOWN, skip_expr(s, j)
    return val, i


def literal_after(src: str, pattern: str):
    """The literal that follows the first match of `pattern` (a regex ending just before the value), else None."""
    m = re.search(pattern, src)
    if not m:
        return None
    try:
        return js_value(src, m.end())[0]
    except ValueError:
        return None


def plain(v):
    """A parsed literal with UNKNOWN parts replaced by None (JSON-safe)."""
    if v is UNKNOWN:
        return None
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [plain(x) for x in v]
    return v


def _read(rel: str) -> str | None:
    p = engine_dir() / rel
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


# ------------------------------------------------------------------------------------------------ treatments
# Fallback copies of engine/src/devices/treat.js (used only when that file cannot be read).
_FB_FAMS = ("push", "layers", "rack", "relight", "contours", "scan", "stills", "xerox", "diagram", "motion", "occlusion")
_FB_ALIAS = {
    "ls": "layers", "layer-separation": "layers", "layer": "layers", "slices": "layers", "parallax": "push",
    "plate3d": "push", "default": "push", "clip": "push", "di": "relight", "depth-as-image": "relight",
    "depth": "relight", "relight": "relight", "contour": "contours", "topo": "contours", "topography": "contours",
    "pointcloud": "scan", "point-cloud": "scan", "lidar": "scan", "scan": "scan", "rp": "xerox", "reproduction": "xerox",
    "halftone": "xerox", "photocopy": "xerox", "thermal": "xerox", "mosaic": "xerox", "enhance": "xerox", "1-bit": "xerox",
    "sr": "stills", "stills-in-rhythm": "stills", "crops": "stills", "stutter": "stills", "dg": "diagram",
    "diagram-over-image": "diagram", "measure": "diagram", "pm": "motion", "pure-motion": "motion",
    "motion-design": "motion", "pure-motion-design": "motion", "code": "motion", "none": "motion", "oc": "occlusion",
    "occ": "occlusion", "rotoscope": "occlusion", "rack-focus": "rack", "focus": "rack"}
_FB_CODES = ("ls", "di", "rp", "sr", "dg", "pm", "oc")
_FB_DEPTH = ("layers", "rack", "relight", "contours", "scan")


@lru_cache(maxsize=1)
def treatments() -> dict:
    """{"families": [...], "alias": {name: family}, "codes": [...], "depth": [...], "source": "treat.js"|"fallback"}."""
    src = _read("src/devices/treat.js")
    if src:
        alias = literal_after(src, r"const\s+ALIAS\s*=\s*")
        fams = literal_after(src, r"const\s+FAMS\s*=\s*")
        codes = literal_after(src, r"const\s+CODES\s*=\s*new\s+Set\(\s*")
        depth = literal_after(src, r"const\s+DEPTH\s*=\s*new\s+Set\(\s*")
        if isinstance(alias, dict) and isinstance(fams, list) and fams and all(isinstance(x, str) for x in fams):
            return {"families": list(fams), "alias": {str(k).lower(): v for k, v in alias.items() if isinstance(v, str)},
                    "codes": [c for c in (codes or _FB_CODES) if isinstance(c, str)],
                    "depth": [d for d in (depth or _FB_DEPTH) if isinstance(d, str)], "source": "engine/src/devices/treat.js"}
    return {"families": list(_FB_FAMS), "alias": dict(_FB_ALIAS), "codes": list(_FB_CODES), "depth": list(_FB_DEPTH),
            "source": "fallback table (engine/src/devices/treat.js not readable)"}


def treatment_parse(v) -> tuple[str | None, bool]:
    """(engine family, unknown) for a shot's `treatment` value — a port of treat.js parse(): a family name, an alias, a
    code, or prose (a family named in parentheses or after a code wins over the code: 'LS (rack)' -> rack,
    'DI: contours' -> contours; among codes alone the first wins: 'DI+LS' -> relight). None/''/'auto' -> (None, False)
    (the engine picks one). A name nobody knows draws a plain push: ("push", True)."""
    if v is None:
        return None, False
    if isinstance(v, dict):
        v = v.get("family") or v.get("name") or v.get("kind") or ""
    f = str(v).lower().strip()
    if f in ("", "auto"):
        return None, False
    T = treatments()
    fams, alias, codes = T["families"], T["alias"], set(T["codes"])

    def known(w: str) -> str | None:
        return w if w in fams else alias.get(w)

    def words(s: str) -> list[str]:
        return [w for w in re.split(r"[^a-z0-9-]+", s) if w]

    def named(ws: list[str]) -> str | None:
        return next((k for k in (known(w) for w in ws if w not in codes) if k), None)

    def first(ws: list[str]) -> str | None:
        return next((k for k in (known(w) for w in ws) if k), None)

    m = re.search(r"\(([^)]*)\)", f)
    paren = m.group(1) if m else None
    r = known(f) or (paren and (named(words(paren)) or first(words(paren)))) or named(words(f)) or first(words(f)) \
        or next((x for x in fams if f.startswith(x)), None)
    if not r:
        return "push", True
    return r, False


def treatment_names() -> list[str]:
    """Every name the engine accepts (families first, then aliases), for help texts."""
    T = treatments()
    return list(T["families"]) + sorted(k for k in T["alias"] if k not in T["families"])


# ------------------------------------------------------------------------------------------------ transitions
_FB_TRANS = ("through", "whip", "flashCut", "dither", "flap", "smear", "match", "flash", "iris", "push", "fade", "cut")


@lru_cache(maxsize=1)
def transitions() -> dict:
    """{"presets": [...], "alias": {name: preset}, "engine": [...], "engine_alias": {...}, "source"}."""
    out = {"presets": list(_FB_TRANS), "alias": {}, "engine": [], "engine_alias": {}, "source": "fallback"}
    src = _read("src/devices/trans.js")
    if src:
        pre = literal_after(src, r"const\s+PRESETS\s*=\s*")
        al = literal_after(src, r"const\s+ALIAS\s*=\s*")
        if isinstance(pre, dict) and pre:
            out["presets"] = list(pre)
            out["source"] = "engine/src/devices/trans.js"
        if isinstance(al, dict):
            out["alias"] = {str(k).lower(): v for k, v in al.items() if isinstance(v, str)}
    src2 = _read("src/trans.js")
    if src2:
        reg = literal_after(src2, r"const\s+registry\s*=\s*")
        al2 = literal_after(src2, r"const\s+alias\s*=\s*")
        if isinstance(reg, dict):
            out["engine"] = [str(k).lower() for k in reg]
        if isinstance(al2, dict):
            out["engine_alias"] = {str(k).lower(): v for k, v in al2.items() if isinstance(v, str)}
    return out


def _trans_prose(s: str) -> str | None:
    """Port of devices/trans.js prose(): most specific first; prose that starts with "cut" is a cut."""
    rules = ((r"^(hard |straight |clean )?cut\b|^none\b", "cut"), (r"flash ?-?cut|invert", "flashCut"), (r"match", "match"),
             (r"\bthrough\b|\b(push|pushes|zoom|zooms|dive|dives) into\b", "through"), (r"whip", "whip"),
             (r"dither|dissolve", "dither"), (r"cross-? ?fade|\bfade\b", "fade"), (r"flap", "flap"),
             (r"smear|\bscan\b|xerox", "smear"), (r"iris", "iris"), (r"\bpush\b|\bslide\b", "push"), (r"flash", "flash"))
    for rx, name in rules:
        if re.search(rx, s):
            return name
    return None


def transition_parse(v) -> tuple[str | None, bool]:
    """(preset, unknown) for a shot's `transition_in` (a preset name, an alias, an engine registry name, prose, or
    {preset, ...}); ("cut", False) for a hard cut; (None, True) for a name the engine does not know (it cuts and warns)."""
    if v is None or v is False or v == "":
        return "cut", False
    if isinstance(v, dict):
        v = v.get("preset") or v.get("type") or v.get("kind") or ""
        if not v:
            return None, True
    s = str(v).lower().strip()
    T = transitions()
    presets = {p.lower(): p for p in T["presets"]}
    if s in presets:
        return presets[s], False
    if s in T["alias"]:
        return T["alias"][s], False
    if s == "flashcut":
        return "flashCut", False
    if s in T["engine"] and s not in ("cut", "flashcut"):
        return s, False
    p = _trans_prose(s)
    if p:
        return p, False
    return None, True


def transition_names() -> list[str]:
    T = transitions()
    extra = [e for e in T["engine"] if e not in {p.lower() for p in T["presets"]} and e not in ("flashcut",)]
    return list(T["presets"]) + extra


# ------------------------------------------------------------------------------------------------ type modes
TYPE_MODES = ("subtitle", "coverline", "masthead", "stack", "mass")
TYPE_MODE_ALIASES = {"sub": "subtitle", "caption": "subtitle", "cover": "coverline", "mast": "masthead",
                     "wall": "mass"}


def type_mode(v: str) -> str | None:
    s = str(v or "").strip().lower()
    return s if s in TYPE_MODES else TYPE_MODE_ALIASES.get(s)


# ------------------------------------------------------------------------------------------------ framings
FRAMING_WORDS = {
    "extreme close-up": "ECU", "extreme close up": "ECU", "extreme closeup": "ECU", "ecu": "ECU",
    "medium close-up": "MCU", "medium close up": "MCU", "medium closeup": "MCU", "mcu": "MCU",
    "close-up": "CU", "close up": "CU", "closeup": "CU", "cu": "CU",
    "medium wide shot": "MWS", "medium wide": "MWS", "mws": "MWS", "cowboy": "MWS",
    "medium shot": "MS", "medium": "MS", "ms": "MS",
    "extreme wide shot": "EWS", "extreme wide": "EWS", "ews": "EWS", "establishing": "EWS",
    "wide shot": "WS", "wide": "WS", "ws": "WS", "long shot": "WS",
    "full shot": "FS", "full-length": "FS", "full length": "FS", "full body": "FS", "full-body": "FS", "fs": "FS",
    "over-the-shoulder": "OTS", "over the shoulder": "OTS", "ots": "OTS",
}


def framing(v: str) -> str | None:
    s = re.sub(r"\s+", " ", str(v or "").strip().lower())
    return FRAMING_WORDS.get(s) or FRAMING_WORDS.get(s.removesuffix(" shot"))


# ------------------------------------------------------------------------------------------------ camera words
CAMERA_WORDS = ("push", "pull", "pan", "truck", "tilt", "crane", "orbit", "static", "locked", "handheld", "dolly",
                "zoom", "drift", "track", "rise", "descend", "lock")


# ------------------------------------------------------------------------------------------------ fonts
@lru_cache(maxsize=1)
def engine_fonts() -> dict:
    """window.ENGINE_FONTS from engine/fonts/fonts.js: {"roles": {...}, "faces": [{family, file, ...}]}."""
    src = _read("fonts/fonts.js")
    if not src:
        return {"roles": {}, "faces": []}
    m = re.search(r"window\.ENGINE_FONTS\s*=\s*", src)
    if not m:
        return {"roles": {}, "faces": []}
    body = src[m.end():].strip().rstrip(";").strip()
    try:
        data = json.loads(body)
    except ValueError:
        try:
            data = plain(js_value(src, m.end())[0])
        except ValueError:
            data = None
    return data if isinstance(data, dict) else {"roles": {}, "faces": []}


def font_families(extra_faces: list | None = None) -> dict[str, str]:
    """lower-cased family / file name / file stem -> the family name, over the engine's faces + project font_files."""
    out: dict[str, str] = {}
    for f in list(engine_fonts().get("faces") or []) + list(extra_faces or []):
        if not isinstance(f, dict) or not f.get("family"):
            continue
        fam = str(f["family"])
        out.setdefault(fam.lower(), fam)
        if f.get("file"):
            out.setdefault(str(f["file"]).lower(), fam)
            out.setdefault(Path(str(f["file"])).stem.lower(), fam)
    return out


def source() -> dict:
    return {"treatments": treatments()["source"], "transitions": transitions()["source"],
            "fonts": "engine/fonts/fonts.js" if engine_fonts().get("faces") else "missing"}
