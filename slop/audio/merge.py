"""One word timing from two aligners (port of the CLODYSSEY project script align_merge.py, generalised).

Rule, unchanged: wav2vec2 where its confidence >= 0.5; otherwise the matched Whisper word, its start moved to where the
vocal energy rises inside the word (only for words >= 0.45 s: the first 10 ms frame above 0.3 x the word's peak energy,
searched up to 0.12 s before its end), unless w2v's start falls strictly inside (t0, t1 - 0.1) of the Whisper word - then
w2v's start is the better start; words neither aligner placed are interpolated evenly between their placed neighbours in
the same line (a non-positive gap becomes 0.12 s per word).
Matching, unchanged: difflib.SequenceMatcher(autojunk=False) over normalised words; matching blocks map 1:1 and
equal-length 'replace' opcodes map 1:1 too (misheard words of the same count still pair).
Generalised: the hand-written SPLIT table (agi -> a g i, cyberpsychosis -> cyber psychosis, 3am -> three am, ...) is
replaced by rules - digits in Whisper text are spelled out, a heard token equal to 2-4 consecutive sheet words is split
into them, adjacent heard tokens that join into one sheet word are merged - plus project.json audio.whisper_map
{"heard": ["sheet", "words"]} for mishearings. The per-take hand corrections of the original are not automated; they
are what the ear-check list in analysis/report.md and `slop lyrics fix` are for. Manual fixes (src "manual") survive
re-analysis. Without Whisper, low-confidence w2v words keep their w2v times (EV's shipped timings are mostly exactly
those) and are listed for the ear check.
"""
from __future__ import annotations

import difflib
import re

import numpy as np

from .align import fold
from .pron import spell_numbers

CONF_MIN = 0.5


def norm(s: str) -> str:
    return re.sub(r"[^a-zЀ-ӿ]", "", fold(s).lower())


def whisper_tokens(wh: list[dict], sheet_norms: list[str], extra_map: dict | None = None) -> list[dict]:
    """Whisper words -> sheet-like tokens {n, t0, t1, conf?} (split/merge rules, see module docstring)."""
    vocab = {x for x in sheet_norms if x}
    concat: dict[str, list[str]] = {}
    for i in range(len(sheet_norms)):
        for k in (2, 3, 4):
            parts = sheet_norms[i:i + k]
            if len(parts) == k and all(parts):
                concat.setdefault("".join(parts), parts)
    emap = {norm(k): [norm(x) for x in (v if isinstance(v, list) else str(v).split())] for k, v in (extra_map or {}).items()}
    toks: list[dict] = []
    for w in wh:
        raw = str(w["w"]).strip()
        shown = re.sub(r"^[^\w']+|[^\w']+$", "", raw)                     # the heard spelling, for `lyrics check`
        pieces = spell_numbers(raw).split() if re.search(r"\d", raw) else [raw]
        parts: list[str] = []
        for p in pieces:
            t = norm(p)
            if not t:
                continue
            if t in emap:
                parts += emap[t]
            elif t in vocab:
                parts.append(t)
            elif t in concat:
                parts += concat[t]
            else:
                parts.append(t)
        parts = [p for p in parts if p]
        if not parts:
            continue
        d = (w["t1"] - w["t0"]) / len(parts)
        whole = len(parts) == 1 and parts[0] == norm(shown)
        for j, p in enumerate(parts):
            o = {"n": p, "t0": w["t0"] + j * d, "t1": w["t0"] + (j + 1) * d, "raw": shown if whole else p}
            if "conf" in w:
                o["conf"] = w["conf"]
            toks.append(o)
    merged: list[dict] = []
    i = 0
    while i < len(toks):
        if i + 1 < len(toks):
            a, b = toks[i]["n"], toks[i + 1]["n"]
            if a + b in vocab and not (a in vocab and b in vocab):
                merged.append({**toks[i], "n": a + b, "t1": toks[i + 1]["t1"],
                               "raw": toks[i]["raw"] + toks[i + 1]["raw"]})
                i += 2
                continue
        merged.append(toks[i])
        i += 1
    return merged


def match_words(lw: list[str], wh: list[dict]) -> dict[int, int]:
    sm = difflib.SequenceMatcher(None, lw, [x["n"] for x in wh], autojunk=False)
    match: dict[int, int] = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            match[a + k] = b + k
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace" and i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                match[i1 + k] = j1 + k
    return match


def energy_onset(R: np.ndarray, t0: float, t1: float, fps: float = 100.0) -> float:
    """Whisper's start pulled forward to where the vocal energy rises inside the word (verbatim rule)."""
    if t1 - t0 < 0.45 or R is None or not len(R):
        return t0
    a, b = int(t0 * fps), int(max(t0, t1 - 0.12) * fps)
    seg = R[a:b]
    win = R[a:int(t1 * fps) + 1]
    if not len(win):
        return t0
    thr = 0.3 * win.max()
    return t0 + (int(np.argmax(seg > thr)) / fps if len(seg) and np.any(seg > thr) else 0)


def merge(w2v: list[dict], lines: list[str], whisper: list[dict] | None = None, R: np.ndarray | None = None,
          whisper_map: dict | None = None, previous: dict | None = None, conf_min: float = CONF_MIN) -> dict:
    """-> words.json (contract §4.3) {words, lines, gaps, stats}."""
    lw = [norm(w["w"]) for w in w2v]
    match: dict[int, int] = {}
    wh: list[dict] = []
    if whisper:
        wh = whisper_tokens(whisper, lw, whisper_map)
        match = match_words(lw, wh)
    out = []
    for i, w in enumerate(w2v):
        sc = float(w.get("score") or 0.0)
        o = {"i": i, "w": w["w"], "line": w["line"], "t0": w.get("t0"), "t1": w.get("t1"), "conf": round(sc, 3)}
        if sc >= conf_min and w.get("t0") is not None:
            o["src"] = "w2v"
        elif whisper is not None and i in match:
            x = wh[match[i]]
            t0, t1 = energy_onset(R, x["t0"], x["t1"]), x["t1"]
            if w.get("t0") is not None and t0 < w["t0"] < t1 - 0.1:
                t0 = w["t0"]
            o.update(t0=round(t0, 3), t1=round(t1, 3), src="whisper")
            if "conf" in x:
                o["wconf"] = x["conf"]
        elif whisper is None and w.get("t0") is not None:
            o["src"] = "w2v"                                    # no fallback ran: keep w2v's time, flag it for the ear
        else:
            o["src"] = "unplaced"
        out.append(o)
    # words neither aligner placed: interpolate inside their line (verbatim rule)
    by_line: dict[int, list[int]] = {}
    for k, o in enumerate(out):
        by_line.setdefault(o["line"], []).append(k)
    for li, ks in by_line.items():
        if not any(out[k]["src"] == "unplaced" for k in ks):
            continue
        good = [k for k in ks if out[k]["src"] != "unplaced" and out[k]["t0"] is not None]
        for k in ks:
            if k in good:
                continue
            prv = max([g for g in good if g < k], default=None)
            nxt = min([g for g in good if g > k], default=None)
            if prv is None or nxt is None:
                continue
            run = [j for j in ks if prv < j < nxt]
            a, b = out[prv]["t1"], out[nxt]["t0"]
            if b <= a:
                b = a + 0.12 * len(run)
            p_ = run.index(k)
            out[k].update(t0=round(a + (b - a) * p_ / len(run), 3), t1=round(a + (b - a) * (p_ + 1) / len(run), 3),
                          src="interp")
    # still unplaced: keep w2v's (low-confidence) time; a word with no time at all sits next to a placed neighbour
    for li, ks in by_line.items():
        for pos, k in enumerate(ks):
            o = out[k]
            if o["src"] != "unplaced":
                continue
            if o["t0"] is not None:
                o["src"], o["note"] = "w2v", "unplaced"
                continue
            prv = next((out[j] for j in reversed(ks[:pos]) if out[j]["t0"] is not None), None)
            nxt = next((out[j] for j in ks[pos + 1:] if out[j]["t0"] is not None), None)
            if prv is not None:
                o.update(t0=round(prv["t1"], 3), t1=round(prv["t1"] + 0.12, 3), src="interp", note="edge")
            elif nxt is not None:
                o.update(t0=round(max(0.0, nxt["t0"] - 0.12), 3), t1=round(nxt["t0"], 3), src="interp", note="edge")
            else:
                o.update(src="interp", note="no timing - fix by hand")
    # manual fixes survive a re-run (matched by line, position in line and word)
    if previous:
        keep = {}
        pos_in_line: dict[int, int] = {}
        for pw in previous.get("words", []):
            p = pos_in_line.get(pw["line"], 0)
            pos_in_line[pw["line"]] = p + 1
            if pw.get("src") == "manual":
                keep[(pw["line"], p, norm(pw["w"]))] = pw
        pos_in_line = {}
        for o in out:
            p = pos_in_line.get(o["line"], 0)
            pos_in_line[o["line"]] = p + 1
            m = keep.get((o["line"], p, norm(o["w"])))
            if m:
                o.update(t0=m["t0"], t1=m["t1"], src="manual", conf=1.0)
                if m.get("note"):
                    o["note"] = m["note"]
    return finish(out, lines, conf_min)


def line_label(ws: list[dict], conf_min: float = CONF_MIN) -> str:
    srcs = {w["src"] for w in ws}
    if any(w["t0"] is None for w in ws):
        return "missing"
    if "interp" in srcs or any(w.get("note") == "unplaced" for w in ws):
        return "check"
    low = any(w["src"] == "w2v" and w["conf"] < conf_min for w in ws)
    if srcs <= {"w2v", "manual"}:
        return "w2v-low" if low else ("manual" if srcs == {"manual"} else "w2v")
    if "w2v" not in srcs and "manual" not in srcs:
        return "sung"
    return "w2v+sung"


def finish(words: list[dict], lines: list[str], conf_min: float = CONF_MIN) -> dict:
    """Recompute lines[] and gaps[] for a words list (used after merges and manual fixes)."""
    for k, w in enumerate(words):
        w["i"] = k
    L = []
    for li, text in enumerate(lines):
        ws = [w for w in words if w["line"] == li]
        tt = [w for w in ws if w["t0"] is not None]
        L.append({"line": li, "text": text, "t0": min((w["t0"] for w in tt), default=None),
                  "t1": max((w["t1"] for w in tt), default=None), "n": len(ws),
                  "conf": line_label(ws, conf_min) if ws else "empty",
                  "conf_mean": round(float(np.mean([w["conf"] for w in ws])), 3) if ws else 0.0})
    gaps = []
    timed = [w for w in words if w["t0"] is not None]
    for a, b in zip(timed, timed[1:]):
        if b["t0"] - a["t1"] > 1.0:
            gaps.append({"t0": a["t1"], "t1": b["t0"], "after_word": a["i"], "in_line": a["line"] == b["line"],
                         "dur": round(b["t0"] - a["t1"], 3)})
    from collections import Counter
    stats = dict(Counter(w["src"] for w in words))
    return {"words": words, "lines": L, "gaps": gaps, "stats": stats, "conf_min": conf_min}
