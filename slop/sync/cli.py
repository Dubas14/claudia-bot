"""`slop sync check|review` — the avsync measurement on any take + window pair (clip files use `slop clip sync`).

`check` prints one plain line for a weaker reader: lag; "copy" or "not a copy" (global NCC > .2 or not); WHERE the take
is in sync ("in sync A–B s", never "in sync to B s", which hid a late start); recovered dips; the divergence; and, with
the project's words and --song-t0, the share of sung seconds in sync — counted over the words the window audio holds
(its voiced span, or --need SONG_T0 SONG_T1), like `slop clip sync`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import SlopError, load_project, resolve_project


def _song(project_arg):
    """the project's song data for labels and the cut on the last eighth. No project named (no --project, no
    SLOP_PROJECT): run without it. A project that was named but cannot be found is an error, never silently ignored."""
    import os
    from .songdata import SongData
    named = bool(project_arg or os.environ.get("SLOP_PROJECT"))
    try:
        pdir = resolve_project(project_arg)
    except SlopError as e:
        if named:
            raise SlopError(f"{e} — the project gives the beats (cut on the last eighth) and word labels; fix --project "
                            "/ SLOP_PROJECT, or unset it to measure the take alone") from e
        return None, ""
    return SongData(pdir), load_project(pdir).get("title") or ""


def voiced_span(ref) -> tuple[float, float] | None:
    """(first, last) voiced second of the window audio (RMS over 10 ms > 10 % of its p95): a clean window that keeps
    only some words is silent elsewhere, so the share below counts only the words it holds."""
    import numpy as np
    from . import avsync
    x = avsync.load(ref)
    hop = avsync.SR // 100
    n = len(x) // hop
    if n == 0:
        return None
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    on = np.where(rms > .1 * np.percentile(rms, 95))[0]
    return (on[0] / 100, (on[-1] + 1) / 100) if len(on) else None


def sung_share(o: dict, song, need: list[float] | None = None) -> tuple[float, float, float | None]:
    """(sung seconds in sync, sung seconds needed, share) — needs the song's words and --song-t0. `need` is the song
    span that counts (default: the window's voiced span)."""
    if song is None or not getattr(song, "has_words", False) or o.get("song_t0") is None:
        return 0.0, 0.0, None
    from .coverage import coverage
    t0 = float(o["song_t0"])
    need = need or [t0, t0 + float(o.get("duration") or 0)]
    cov, tot, _ = coverage(o.get("spans_song") or [], song.words, need, min_gap=.6)
    return round(cov, 3), round(tot, 3), (round(cov / tot, 3) if tot else None)


def summary(name: str, o: dict) -> str:
    """one plain line: lag, copy or not, WHERE the take is in sync (start and end), dips, divergence, sung share
    (o["share"], when the caller measured it)."""
    sf, us = float(o.get("synced_from") or 0.0), float(o["synced_until"])
    copy = "copy" if o["lag_ncc"] > .2 else "not a copy"
    if o["diverges"]:
        sync = (f"in sync {sf:.2f}–{us:.2f} s ({us - sf:.2f} s), diverges at {o['diverge_at']:.2f} s" if us - sf >= .05
                else f"never in sync (diverges at {o['diverge_at']:.2f} s)")
    else:
        sync = f"in sync {sf:.2f} s to the end ({o.get('duration', 0):.2f} s)"
    dips = o.get("dips") or []
    share = o.get("share")
    return (f"{name}: lag {o['lag_s'] * 1000:+.0f} ms, copy NCC {o['lag_ncc']:.2f} ({copy}), {sync}"
            + (f"; out of sync (recovered) {', '.join(f'{a:.2f}–{b:.2f} s' for a, b in dips)}" if dips else "")
            + (f"; {o['sung_s_in_sync']:.2f}/{o['sung_s']:.2f} sung s in sync ({share:.0%})" if share is not None else "")
            + (f"; cut on the eighth at song {o['cut_eighth_song']:.2f} s"
               if o.get("cut_eighth_song") is not None and o["diverges"] and us - sf >= .05 else ""))


def cmd_check(a) -> dict:
    from . import avsync
    song, title = _song(a.project)
    o = avsync.check(Path(a.video), Path(a.ref), a.song_t0, png=a.png, song=song, title=a.title or title)
    need = None
    if a.need:
        need = [float(a.need[0]), float(a.need[1])]
    elif a.song_t0 is not None:
        v = voiced_span(Path(a.ref))
        if v:
            need = [round(a.song_t0 + v[0], 3), round(a.song_t0 + v[1], 3)]
    cov, tot, share = sung_share(o, song, need)
    o = {**o, "sung_s_in_sync": cov, "sung_s": tot, "share": share, "need_song": need}
    if a.out_json:
        Path(a.out_json).write_text(json.dumps(o, indent=1), encoding="utf-8")
    txt = summary(Path(a.video).name, o) + (f"; figure {a.png}" if a.png else "")
    if share is None and a.song_t0 is not None:
        txt += "\n  (no sung share: run it with the project (-p NAME) so the song's words are known)"
    return {**o, "text": txt}


def cmd_review(a) -> dict:
    from . import avsync
    song, _ = _song(a.project)
    o = avsync.review(Path(a.video), Path(a.ref), a.song_t0, Path(a.out), audio=a.audio, song=song)
    return {**o, "text": f"review video -> {a.out} (our audio laid on, lag-corrected; marker from the divergence)"}


def register(sub) -> None:
    s = sub.add_parser("sync", help="lip sync as an audio check (avsync) on a take + the window it was given")
    ss = s.add_subparsers(dest="sync_cmd", metavar="ACTION")
    p = ss.add_parser("check", help="lag, synced span, divergence, cut on the last eighth; optional PNG")
    p.add_argument("video"); p.add_argument("ref"); p.add_argument("--song-t0", type=float)
    p.add_argument("--png"); p.add_argument("--out-json"); p.add_argument("--title", default="")
    p.add_argument("--need", nargs=2, type=float, metavar=("SONG_T0", "SONG_T1"),
                   help="the sung span that counts for the share (default: where the window audio is voiced)")
    p.set_defaults(func=cmd_check)
    p = ss.add_parser("review", help="render the take with our audio laid on and a divergence marker")
    p.add_argument("video"); p.add_argument("ref"); p.add_argument("--song-t0", type=float, required=True)
    p.add_argument("--out", required=True); p.add_argument("--audio", help="lay this track instead (e.g. the mix) from the same song time")
    p.set_defaults(func=cmd_review)
    s.set_defaults(func=lambda a: (_ for _ in ()).throw(SlopError("missing action: slop sync check|review")))
