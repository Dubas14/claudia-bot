"""Which frames a chapter's contact sheet shows (`slop render sheet --chapter X [--review]`).

  --chapter X            the mid-point of every shot in chapter X (an id like C3, a name like chorus1, or its number)
  --chapter X --review   the review sheet: every shot's FIRST, MID and LAST frame (cuts and transitions), every lyric
                         line's FIRST and LAST word at the time the lyric gate checks it (is the word on screen when it
                         is sung?), and the chapter's strongest HITS (does the picture answer the sound?) — labelled,
                         in time order; the reviewer looks at it in one pass (docs/80 §3).
Chapters come from board/shots.json "chapters" ({id, name, t0, t1}); a shot belongs to the chapter its t0 falls in.
"""
from __future__ import annotations

import math
from pathlib import Path

from ..config import SlopError
from . import project as P

MAX_HITS = 8


def _data(pdir: Path, name: str, rel: str):
    have = P.asset_files(pdir)
    v = P.read_js_asset(have[name]) if name in have else None
    return v if v is not None else P._read_json(pdir / rel)


def chapters(pdir: Path) -> tuple[list[dict], list[dict]]:
    """(chapters, shots) from the exported board (engine/assets/shots.js) or board/shots.json."""
    S = _data(pdir, "shots", "board/shots.json") or {}
    if not isinstance(S, dict):
        S = {"shots": S}
    shots = [s for s in S.get("shots") or [] if isinstance(s, dict) and "t0" in s and "t1" in s]
    return [c for c in S.get("chapters") or [] if isinstance(c, dict)], shots


def find_chapter(pdir: Path, key: str) -> dict:
    chs, _ = chapters(pdir)
    if not chs:
        raise SlopError("board/shots.json has no chapters — run `slop board draft` (it writes them), or pass --times")
    k = str(key).strip().lower()
    for i, c in enumerate(chs):
        if k in (str(c.get("id", "")).lower(), str(c.get("name", "")).lower(), str(i + 1)):
            return {**c, "index": i + 1}
    names = ", ".join(f"{c.get('id') or i + 1} ({c.get('name', '')})" for i, c in enumerate(chs))
    raise SlopError(f"no chapter '{key}': the chapters are {names}")


def _frame_t(t: float, fps: float) -> float:
    return round(t * fps) / fps


def chapter_times(pdir: Path, key: str, review: bool, fps: float, lyr: list | None = None) -> tuple[dict, list[tuple[float, str]]]:
    """(the chapter, [(t, label)]) in time order; times on frame boundaries; same-frame labels merged."""
    ch = find_chapter(pdir, key)
    _, shots = chapters(pdir)
    c0, c1 = float(ch.get("t0", 0)), float(ch.get("t1", 0))
    mine = [s for s in shots if c0 - 1e-6 <= float(s["t0"]) < c1 - 1e-6]
    if not mine:
        raise SlopError(f"chapter {ch.get('id') or ch['index']} ({ch.get('name', '')}) has no shots between {c0:.2f} and {c1:.2f} s")
    picks: list[tuple[float, str]] = []
    for s in mine:
        a, b, sid = float(s["t0"]), float(s["t1"]), str(s.get("id"))
        mid = (a + b) / 2
        if not review:
            picks.append((_frame_t(mid, fps), sid))
            continue
        first = math.ceil(a * fps - 1e-6) / fps
        last = (math.ceil(b * fps - 1e-6) - 1) / fps
        picks += [(first, f"{sid} first"), (_frame_t(mid, fps), f"{sid} mid"), (max(first, last), f"{sid} last")]
    if review:
        for ln in lyr or []:
            toks = [tk for tk in ln.get("tokens") or [] if isinstance(tk, dict) and tk.get("t0") is not None]
            if not toks or (ln.get("kind") or "lyric") != "lyric":
                continue
            for tag, tk in (("first", toks[0]), ("last", toks[-1])):
                t0, t1 = float(tk["t0"]), float(tk.get("t1") if tk.get("t1") is not None else float(tk["t0"]) + .2)
                t = t0 + min(.12, max(.03, (t1 - t0) / 2))          # when the lyric gate checks it
                if c0 <= t0 < c1:
                    picks.append((_frame_t(t, fps), f"L{int(ln.get('line', 0)):02d} {tag} '{str(tk.get('txt', ''))[:14]}'"))
        H = _data(pdir, "hits", "analysis/hits.json") or {}
        hits = [h for h in (H.get("hits") or []) if isinstance(h, dict) and c0 <= float(h.get("t", -1)) < c1]
        for h in sorted(hits, key=lambda h: -float(h.get("score") or 0))[:MAX_HITS]:
            picks.append((_frame_t(float(h["t"]), fps), f"hit {float(h.get('score') or 0):.2f}"))
    merged: dict[int, list[str]] = {}                 # by frame number: one tile per frame, its labels joined
    for t, lab in sorted(picks):
        k = int(round(t * fps))
        merged.setdefault(k, [])
        if lab not in merged[k]:
            merged[k].append(lab)
    return ch, [(k / fps, " · ".join(labs)) for k, labs in sorted(merged.items())]
