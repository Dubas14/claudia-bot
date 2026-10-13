"""Sung-seconds coverage and cover proposals (port of the production seedance.py coverage / make_cover logic).

coverage(spans, words, need, min_gap): which SUNG stretches of [need0, need1) the chain's in-sync spans cover — silence
needs no lips. Sung stretches = aligned words ±30 ms, clipped to the needed span, merged when within .12 s; in-sync spans
come from each chain element's latest synced take (start extended 60 ms); gaps >= min_gap (the run loop uses .6 s:
"most lips" — shorter slips are tolerated), merged when within .3 s. Returns (covered s, total sung s, gaps).

Cover proposal (make_cover): for the first uncovered gap [cut, end]: the window starts in the word gap before the cut
(gap_start(cut), lead .25 s, span 1.6 s), duration int(min(8, max(4, ceil(end − t0 + .3)))), the words are the
window's words, and the start image is the frame of the take that was in sync up to the cut, at clip time
cut − song_t0 + lag_s (the take's measured lag, never a constant). Later gaps that fall inside that window are left to
it. After `max_covers` covers (default 2) the rest is recorded as `fallback` spans: cut away in the edit (no lip-sync
model fallback by default).

Intentional changes: the start frame is NOT pre-graded (generation inputs stay in colour, and a reference is never
altered to get past a provider filter); two clips never start from the same frame — if the frame at the cut is already
some clip's start, the proposal steps back one frame at a time (up to 12 frames, 0.5 s) to the nearest unused one. The
proposal's words follow the same rule as the cover clip written from it (slop.gen.clips.cover_words: the root window's
word rule — clean windows keep words starting at t0 + .05 — and a her-words chain keeps only her words), and for clean
windows the start is moved back to the next word's t0 − .06 when the gap midpoint would mute that word
(SongData.clean_start).
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from ..config import SlopError
from .songdata import SongData

FPS = 24
COVER_MIN, COVER_MAX = 4, 8


def coverage(spans_song, words, need, min_gap=.25):
    spans = [(a - .06, b) for a, b in spans_song]
    sung: list[list[float]] = []
    for w in sorted(words, key=lambda w: w["t0"]):
        a, b = max(w["t0"] - .03, need[0]), min(w["t1"] + .03, need[1])
        if b > a:
            if sung and a <= sung[-1][1] + .12:
                sung[-1][1] = max(sung[-1][1], b)
            else:
                sung.append([a, b])
    cov = tot = 0.0; gaps: list[list[float]] = []
    for a, b in sung:
        tot += b - a; T = a
        while T < b - 1e-3:
            live = [x1 for x0, x1 in spans if x0 <= T < x1]
            if live:
                e = min(b, max(live)); cov += e - T; T = e; continue
            nxt = [x0 for x0, x1 in spans if T < x0 < b]; e = min(nxt) if nxt else b
            if e - T >= min_gap:
                if gaps and T - gaps[-1][1] < .3:
                    gaps[-1][1] = round(e, 3)
                else:
                    gaps.append([round(T, 3), round(e, 3)])
            T = e
    return cov, tot, gaps


# ------------------------------------------------------------------------------------------------ chains
def chain(pdir: Path, root: dict) -> list[dict]:
    from ..gen import store
    out = [root]
    for cid in root.get("covers") or []:
        if store.exists(pdir, cid):
            out.append(store.load(pdir, cid))
    return out


def element_spans(clip: dict) -> list[list[float]]:
    from ..gen import store
    tk = store.latest_synced_take(clip)
    if not tk:
        return []
    sy = tk["sync"]
    return [list(x) for x in (sy.get("spans_song") or sy.get("synced") or []) if x[1] > x[0]]


def chain_report(pdir: Path, root: dict, song: SongData, min_gap: float = .6) -> dict:
    ch = chain(pdir, root)
    need = root.get("needed") or [root.get("song_t0", 0.0), root.get("song_t0", 0.0) + root.get("body", {}).get("duration", 0)]
    spans = [s for c in ch for s in element_spans(c)]
    cov, tot, gaps = coverage(spans, song.words, need, min_gap=min_gap)
    synced_any = any(element_spans(c) for c in ch)
    delivered = any(c.get("status") == "delivered" for c in ch)
    return {"root": root["id"], "chain": [c["id"] for c in ch], "needed": need, "sung_s": round(tot, 3),
            "covered_s": round(cov, 3), "share": round(cov / tot, 3) if tot > 0 else None, "gaps": gaps,
            "measured": synced_any, "delivered": delivered, "fallback": root.get("fallback") or []}


def project_report(pdir: Path, song: SongData, clips: list[dict], min_gap: float = .6) -> dict:
    roots = [c for c in clips if c.get("kind") == "sung" and not c.get("parent")]
    rows = [chain_report(pdir, r, song, min_gap) for r in roots]
    sung = sum(r["sung_s"] for r in rows); cov = sum(r["covered_s"] for r in rows)
    return {"clips": rows, "sung_s": round(sung, 3), "covered_s": round(cov, 3),
            "share": round(cov / sung, 3) if sung > 0 else None,
            "gaps": sum(len(r["gaps"]) for r in rows), "min_gap_s": min_gap}


# ------------------------------------------------------------------------------------------------ proposals
def _probe_duration(path: Path) -> float | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def extract_frame(video: Path, t: float, out: Path) -> Path:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SlopError("ffmpeg is not installed or not on PATH (run bin/setup.sh)")
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([exe, "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", str(out)],
                       capture_output=True)
    if r.returncode or not out.is_file():
        raise SlopError(f"could not extract a frame at {t:.3f} s from {video.name}: {r.stderr.decode(errors='replace')[-200:]}")
    return out


def _parent_for_gap(ch: list[dict], g0: float) -> dict:
    """the chain element that was in sync up to the gap (its span ends nearest before g0), else the latest delivered."""
    from ..gen import store
    best, bend = None, -1e9
    for c in ch:
        for a, b in element_spans(c):
            if b <= g0 + .1 and b > bend:
                best, bend = c, b
    if best is not None:
        return best
    for c in reversed(ch):
        if store.latest_delivered_take(c):
            return c
    return ch[-1]


def propose(pdir: Path, root: dict, song: SongData, *, min_gap: float = .6, max_covers: int = 2) -> dict:
    """cover proposals for the root's uncovered sung gaps (nothing written)."""
    from ..gen import store
    from ..gen.clips import cover_words
    mode = (root.get("window") or {}).get("mode")
    rep = chain_report(pdir, root, song, min_gap)
    have = len(root.get("covers") or [])
    out = {**rep, "proposals": [], "exhausted": False}
    if not rep["gaps"]:
        return out
    if not rep["measured"]:
        out["note"] = "no take of this chain has a sync measurement yet: run slop clip sync CLIP first"
        return out
    ch = chain(pdir, root)
    used = store.used_starts(pdir)
    k = have + 1
    pending = list(rep["gaps"])
    waiting = [c for c in ch[1:] if not element_spans(c) and c.get("status") not in ("declined", "failed")]
    out["pending_covers"] = []
    while pending:
        g0, g1 = pending.pop(0)
        busy = [c["id"] for c in waiting if (c.get("needed") or [0, 0])[0] < g1 and (c.get("needed") or [0, 0])[1] > g0]
        if busy:                                                  # a cover for this gap is not measured yet: no double spend
            out["pending_covers"].append({"gap": [g0, g1], "covers": busy})
            continue
        if k > max_covers:
            out["exhausted"] = True
            out["fallback"] = [[g0, g1]] + pending
            break
        t0 = song.gap_start(g0)
        if mode == "clean":
            t0 = song.clean_start(t0)
        dur = int(min(COVER_MAX, max(COVER_MIN, math.ceil(g1 - t0 + .3))))
        we = t0 + dur
        handled = [[g0, g1]]
        while pending and pending[0][1] <= we - .08:              # later gaps inside this window are left to it
            handled.append(pending.pop(0))
        parent = _parent_for_gap(ch, g0)
        ptk = store.latest_synced_take(parent) or store.latest_delivered_take(parent)
        cid = f"{root['id']}-c{k}"
        while store.exists(pdir, cid):
            k += 1; cid = f"{root['id']}-c{k}"
        words = cover_words(song, parent.get("her_words") or root.get("her_words"), t0, dur, mode)[0]
        prop = {"id": cid, "root": root["id"], "parent": parent["id"], "song_t0": t0, "duration": dur,
                "needed": [round(g0, 3), round(max(g1, handled[-1][1]), 3)], "gaps": handled,
                "words": words,
                "why": f"cover for {parent['id']}: it diverges from our audio at song {g0:.2f}s; this window starts in the word gap at {t0:.2f}s"}
        if ptk and ptk.get("file"):
            lag = float((ptk.get("sync") or {}).get("lag_s") or 0.0)
            ct = g0 - float(parent.get("song_t0") or 0.0) + lag
            tf = store.absp(pdir, ptk["file"])
            dur_take = _probe_duration(tf) if tf and tf.is_file() else None
            hi = (dur_take or float(parent.get("body", {}).get("duration") or ct + .05)) - .05
            ct = max(0.0, min(hi, ct))
            frame = int(round(ct * FPS))
            steps = 0
            while f"{ptk['file']}@{frame}" in used and steps < 12 and frame > 0:
                frame -= 1; steps += 1
            if f"{ptk['file']}@{frame}" in used:
                prop["start_problem"] = (f"every frame within 0.5 s before the cut of {parent['id']} already starts another clip; "
                                         "pass --start IMAGE to `slop clip cover --make` or continue from another take")
            used[f"{ptk['file']}@{frame}"] = cid
            prop["start_frame"] = {"clip": parent["id"], "take_file": ptk["file"], "t": round(frame / FPS, 3), "frame": frame,
                                   "lag_s": lag, "stepped_back": steps}
        else:
            prop["start_problem"] = f"{parent['id']} has no delivered take to take a start frame from"
        out["proposals"].append(prop)
        k += 1
    return out
