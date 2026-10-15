"""On-screen lyric tokens: lyrics/display.txt + analysis/words.json -> the engine's LYR list (contract §4.3).

Port of tools/display.py. display.txt has one line per lyric line of lyrics/lyrics.txt (same skipping rules: blank lines
and [section] lines are ignored), written as it should READ (the joke, not the phonetics). Tokens are separated by
spaces; "TEXT|n" consumes n sung words and inherits their aligned times ("AGI|3" shows AGI for the three sung words
"A G I"); "TEXT|0" rides on the next token; without |n a token consumes 1 word if it has a letter or digit, else 0.
Styles: ~strike~, *accent*, _mono_. A line must consume exactly its sung words (that is the structural check that the
alignment sheet and the display text agree). lyrics/adlibs.json (optional): [{"text", "t0", "t1", "each": [times],
"kind": "adlib"|"zeros"}] for sung words that are not on the sheet.
Output: [{line, kind: "lyric"|"adlib"|"zeros", text, t0, t1, tokens: [{txt, t0, t1, st, n}]}] sorted by t0.
Changes: every bad line is reported at once (the original stopped at the first); a line whose words have no timing
yet is an error with the fix command instead of a crash; display.txt can be started from the sheet
(`slop lyrics display --init`: spaced capitals "A G I" become "AGI|3", section tags are copied): --init writes it when
it is missing OR holds no lyric lines yet (the project template's notes-only file; its notes are kept on top), and
--init --force rebuilds a filled one. Without --init, a notes-only display.txt is an error that names that command.
"""
from __future__ import annotations

import re
from pathlib import Path

from slop.config import SlopError
from slop.util import read_lyric_lines

from .align import read_sheet, split_words
from .common import Paths, read_json


def read_display(path: Path) -> list[str]:
    """display.txt's lyric lines (the shared rule: slop.util.read_lyric_lines; a missing file has none)."""
    return read_lyric_lines(path)


def tokens(spec: str) -> list[list]:
    out = []
    for tok in spec.split():
        if "|" in tok and re.fullmatch(r"\d+", tok.rsplit("|", 1)[1] or "x"):
            txt, n = tok.rsplit("|", 1)
            out.append([txt, int(n)])
        else:
            out.append([tok, None])
    return out


def consumed(spec: str) -> int:
    return sum((n if n is not None else (1 if re.search(r"[A-Za-z0-9\u0400-\u04FF]", txt) else 0)) for txt, n in tokens(spec))


def starter_line(sung: str) -> str:
    """Display text from a sung line: runs of single capitals become one token ("A G I era" -> "AGI|3 era"); a word
    the aligner counts as several sung words or none ("twenty-five" -> 2, "a.m." -> 2, "&" -> 0) gets its |n, so
    the starter always validates (integration fix: hyphenated and dotted words used to fail `lyrics display`)."""
    toks = sung.split()
    out, i = [], 0
    while i < len(toks):
        j = i
        while j < len(toks) and re.fullmatch(r"[A-Z][.,!?:;]?", toks[j]) and (j == i or not re.search(r"[.,!?:;]$", toks[j - 1])):
            j += 1
        if j - i >= 2:
            letters = "".join(t[0] for t in toks[i:j])
            tail = re.sub(r"^[A-Z]", "", toks[j - 1])
            out.append(f"{letters}{tail}|{j - i}")
            i = j
        else:
            n = len(split_words(toks[i]))
            out.append(toks[i] if n == 1 else f"{toks[i]}|{n}")
            i += 1
    return " ".join(out)


def init_display(paths: Paths, force: bool = False) -> Path:
    """display.txt from lyrics.txt. Refuses to overwrite lyric lines without force; a notes-only file is filled in
    (its [notes] stay on top)."""
    header: list[str] = []
    if paths.display.exists():
        if read_display(paths.display) and not force:
            raise SlopError("lyrics/display.txt already has lyric lines (use --init --force to rebuild it from lyrics.txt)")
        if not read_display(paths.display):
            header = [ln.rstrip() for ln in paths.display.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines = read_sheet(paths.lyrics)
    if not lines:
        raise SlopError("lyrics/lyrics.txt has no lyric lines yet: write the sung lyrics there first (one line per lyric "
                        "line, words as sung), then run `slop lyrics display --init`")
    out = list(header)
    for raw in paths.lyrics.read_text(encoding="utf-8").splitlines():
        r = raw.strip()
        if not r:
            continue
        if r.startswith("["):
            if re.fullmatch(r"\[[^\]]{1,40}\]", r):                 # section tags help to keep the lines in step
                out.append(r)
            continue
        out.append(starter_line(r))
    paths.display.parent.mkdir(parents=True, exist_ok=True)
    paths.display.write_text("\n".join(out) + "\n", encoding="utf-8")
    return paths.display


def validate(sheet: list[str], display: list[str]) -> list[dict]:
    """Structural check without timing: every display line consumes exactly its sung words."""
    probs = []
    if len(display) != len(sheet):
        probs.append({"line": None, "msg": f"display.txt has {len(display)} lyric lines, lyrics.txt has {len(sheet)}: "
                                           "they must match line for line ([section] and blank lines are ignored)"})
    for li, (spec, sung) in enumerate(zip(display, sheet)):
        k, m = consumed(spec), len(split_words(sung))
        if k != m:
            probs.append({"line": li, "msg": f"display consumes {k} of {m} sung words", "display": spec, "sung": sung})
    return probs


def build_lyr(words: list[dict], display: list[str], adlibs: list[dict] | None = None) -> list[dict]:
    """words: words.json "words"; display: one spec per lyric line. Raises SlopError listing every bad line."""
    by_line: dict[int, list[dict]] = {}
    for w in words:
        by_line.setdefault(w["line"], []).append(w)
    lines, errs = [], []
    for li, spec in enumerate(display):
        ws = by_line.get(li, [])
        k, res = 0, []
        for txt, n in tokens(spec):
            if n is None:
                n = 1 if re.search(r"[A-Za-z0-9\u0400-\u04FF]", txt) else 0
            grp = ws[k:k + n]
            k += n
            st = "strike" if txt.startswith("~") else "accent" if txt.startswith("*") else "mono" if txt.startswith("_") else ""
            txt = txt.strip("~*_")
            t0 = grp[0]["t0"] if grp else None
            t1 = grp[-1]["t1"] if grp else None
            res.append({"txt": txt, "t0": t0, "t1": t1, "st": st, "n": n})
        if k != len(ws):
            errs.append(f"line {li + 1}: display consumes {k} of {len(ws)} sung words: {spec}")
            continue
        if any(r["n"] and r["t0"] is None for r in res):
            errs.append(f"line {li + 1}: some words have no timing yet (fix with `slop lyrics fix`): {spec}")
            continue
        timed = [r for r in res if r["t0"] is not None]
        if not timed:
            errs.append(f"line {li + 1}: no token carries a sung word: {spec}")
            continue
        for i, r in enumerate(res):                                   # zero-word tokens take the next token's time
            if r["t0"] is None:
                nxt = next((x for x in res[i + 1:] if x["t0"] is not None), None) or \
                    next(x for x in reversed(res[:i]) if x["t0"] is not None)
                r["t0"], r["t1"] = nxt["t0"], nxt["t1"]
        lines.append({"line": li, "kind": "lyric", "text": " ".join(r["txt"] for r in res),
                      "t0": min(r["t0"] for r in res), "t1": max(r["t1"] for r in res), "tokens": res})
    if errs:
        raise SlopError("display tokens do not match the sung words: " + " | ".join(errs[:10]) +
                        (f" (+{len(errs) - 10} more)" if len(errs) > 10 else "") +
                        ". Edit lyrics/display.txt (\"TEXT|n\" = n sung words) and re-run `slop lyrics display`.")
    for a in adlibs or []:
        kind = a.get("kind", "adlib")
        parts = a["text"].split()
        if kind == "zeros":
            each = a.get("each") or []
            toks = [{"txt": "0", "t0": z, "t1": z + .44, "st": "accent", "n": 0} for z in each]
            lines.append({"line": None, "kind": "zeros", "text": " ".join("0" * len(each)), "t0": each[0] if each else a["t0"],
                          "t1": (each[-1] + .45) if each else a["t1"], "tokens": toks})
            continue
        each = a.get("each") or [a["t0"] + i * (a["t1"] - a["t0"]) / len(parts) for i in range(len(parts))]
        toks = [{"txt": p, "t0": e, "t1": e + .4, "st": "adlib", "n": 0} for p, e in zip(parts, each)]
        lines.append({"line": None, "kind": "adlib", "text": a["text"], "t0": a["t0"], "t1": a["t1"], "tokens": toks})
    lines.sort(key=lambda x: x["t0"])
    return lines


def build(pdir: Path, init: bool = False, force: bool = False) -> dict:
    """`slop lyrics display`: validate display.txt against lyrics.txt and, when words.json exists, build the LYR list
    (analysis/lyrics-display.json)."""
    from .common import write_json
    from .common import project_cmd
    paths = Paths(pdir)
    sheet = read_sheet(paths.lyrics)
    if not sheet:
        raise SlopError("lyrics/lyrics.txt has no lyric lines yet: write the sung lyrics there first (one line per lyric "
                        f"line, words as sung), check them with `{project_cmd(pdir, 'lyrics lint')}`, then run "
                        f"`{project_cmd(pdir, 'lyrics display --init')}`")
    created = False
    empty = not paths.display.exists() or not read_display(paths.display)
    if empty:
        if not init:
            raise SlopError(("no lyrics/display.txt" if not paths.display.exists() else
                             "lyrics/display.txt has no lyric lines yet (only notes)") +
                            f". Run `{project_cmd(pdir, 'lyrics display --init')}` to start it from lyrics.txt, then "
                            "edit it so each line reads the way it should on screen (\"TEXT|n\" = n sung words).")
        init_display(paths)
        created = True
    elif init and force:
        init_display(paths, force=True)
        created = True
    kept = bool(init and not created)               # idempotent: --init again keeps the edited file and checks it
    display = read_display(paths.display)
    probs = validate(sheet, display)
    if probs:
        msg = "; ".join((f"line {p['line'] + 1}: " if p["line"] is not None else "") + p["msg"] +
                        (f" (display \"{p['display']}\" vs sung \"{p['sung']}\")" if "display" in p else "") for p in probs[:10])
        raise SlopError(f"lyrics/display.txt does not match lyrics/lyrics.txt: {msg}. Fix the tokens and re-run.")
    W = read_json(paths.words)
    out = {"created": created, "lines": len(display), "tokens": sum(len(tokens(s)) for s in display)}
    pre = ("kept the existing lyrics/display.txt (`--init --force` rebuilds it from lyrics.txt). " if kept else "")
    if not W:
        out["text"] = (pre + f"display.txt OK ({len(display)} lines){' (created from lyrics.txt)' if created else ''}. "
                       f"Timing comes after `{project_cmd(pdir, 'analyze')}` (words.json); re-run this then.")
        return out
    adl = read_json(paths.adlibs, []) or []
    lyr = build_lyr(W["words"], display, adl)
    write_json(paths.analysis / "lyrics-display.json", lyr)
    out.update(lyr_lines=len(lyr), file=str(paths.analysis / "lyrics-display.json"),
               text=pre + f"display OK: {len(lyr)} lines, {sum(len(x['tokens']) for x in lyr)} tokens -> "
                    "analysis/lyrics-display.json")
    return out
