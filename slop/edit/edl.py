"""slop edit edl — the edit: what every storyboard shot shows -> edit/edl.json (engine: window.EDL, EV format).

  {"s001": {"segs": [{"t0": 0.0, "clip": "c01-t1", "in": 0.0}]}, "s002": {"plate": "p002"}}

Port of edl.py (logic and tolerances kept). Clips play in SONG time: clip time = song time − song_t0 + lag_s of the take
(avsync). A shot's span is walked through its clip chain — the take, then its divergence covers — moment by moment the
element whose in-sync span contains it (spans tolerance −0.06/−0.05 s, the longest-running one); in a hole, the next
span's element if its footage reaches back, else the element already playing while its footage lasts, else any element
whose footage covers the moment (root first: a short lip patch must not hold its last frame); holes are reported. Where
lip sync was given up on a span, the shot cuts to its motion clip there (`fill_holes`, CLODYSSEY) instead of holding an
out-of-sync mouth. Motion clips use the same mapping (lag only when the take measured an audio copy: mode "copy" or
NCC > 0.2), held on the last frame when the shot outlasts the clip. A shot whose clip is not delivered shows its picked
plate (2.5D), so the film renders end to end at every stage; code-drawn shots need nothing; anything else is MISSING.

A shot's clips: the board's ids (`clips`, `clip`, legacy `seedance_clip`), then the root clips that `slop clip new` made
for it (clips/*.json "shot"), then root clips whose "needed" span covers the shot (one window cut into several shots);
sung before motion. The first delivered one plays; a later non-singing one fills lip-sync holes.
Inputs: board/shots.json (shot `clip` / `clips` / legacy `seedance_clip`, `plate`), clips/<clip>.json (contract §4.6:
kind, song_t0, body.duration, covers, takes[{file, status, sync{lag_s, ncc, mode, synced[[a,b]], diverge_at, cut_at}}];
EV field names spans_song/lag_ncc/cut_eighth_song/synced_song are read too), plates/picks.json, edit/overrides.json
{"s055": {"use": "plate" | "<clip>", "why": "…"}} (a judged-bad take gives way to the plate or another clip).
Engine clip names are "<clip>-t<k>" (k = the take's 1-based index); `slop edit export` extracts their frames.

Changes from the source: no import on first use (export extracts frames); the latest non-rejected take with an existing
file is used (EV used the latest take with a file even when QA rejected it); the contract's sync field names.
"""
from __future__ import annotations

from pathlib import Path

from ..board.common import (is_code, load_shots, read_json, resolve_file, shot_clips, shot_plate, shot_tier,
                            clip_kinds, write_json)

BAD_TAKE = ("failed", "declined", "rejected")


def sync_of(tk: dict) -> dict:
    sy = tk.get("sync") or {}
    spans = sy.get("synced") or sy.get("spans_song") or []
    spans = [[float(a), float(b)] for a, b in spans if b is not None and a is not None]
    ncc = sy.get("ncc", sy.get("lag_ncc"))
    cut = sy.get("cut_at", sy.get("cut_eighth_song"))
    div = sy.get("diverge_at", sy.get("diverge_at_song"))
    synced = sy.get("synced_song") or ([spans[0][0], spans[-1][1]] if spans else None)
    return {"lag_s": float(sy.get("lag_s") or 0.0), "ncc": float(ncc) if ncc is not None else None,
            "copy": sy.get("mode") == "copy" or (ncc is not None and float(ncc) > .2),
            "spans": spans, "cut": float(cut) if cut is not None else None,
            "diverges": bool(div is not None or sy.get("diverges")), "synced_song": synced}


def is_sing(c: dict | None) -> bool:
    return bool(c) and (c.get("kind") == "sung" or bool(c.get("kind") is None and c.get("sing")))


def song_t0(c: dict) -> float:
    return float(c.get("song_t0") or 0.0)


def clip_dur(c: dict) -> float:
    return float((c.get("body") or {}).get("duration") or c.get("duration") or 0.0)


def engine_name(clip: str, k: int) -> str:
    return f"{clip}-t{k}"


class Edit:
    def __init__(self, pdir: Path):
        self.pdir = Path(pdir)
        self._cache: dict[str, dict | None] = {}
        self.missing_files: dict[str, str] = {}

    def load(self, cid: str) -> dict | None:
        if cid not in self._cache:
            c = read_json(self.pdir / "clips" / f"{cid}.json", default=None)
            self._cache[cid] = c if isinstance(c, dict) else None
        return self._cache[cid]

    def _takes(self, cid: str, c: dict) -> list[tuple[int, dict]]:
        out = []
        for i, t in enumerate(c.get("takes") or []):
            if not t.get("file") or t.get("status") in ("failed", "declined"):
                continue
            f = resolve_file(self.pdir, t["file"])
            if not (f and f.is_file()):
                self.missing_files[engine_name(cid, i + 1)] = str(t["file"])
                continue
            out.append((i + 1, t))
        return out

    def best_take(self, cid: str) -> tuple[int, dict] | None:
        c = self.load(cid)
        if not c:
            return None
        tk = self._takes(cid, c)
        good = [x for x in tk if not x[1].get("rejected") and (x[1].get("qa") or {}).get("verdict") != "reject"
                and x[1].get("status") != "rejected"]
        # a take still waiting for `slop clip sync` (e.g. a Higgsfield finalize) has no measured lag_s: never prefer it
        # over a measured one, or the sung words play off the mouth
        synced = [x for x in good if not x[1].get("needs_sync")]
        pool = synced or good or tk             # a rejected-but-only take stays as the fallback
        return pool[-1] if pool else None

    def chain(self, root: str) -> list[tuple[str, dict, int, dict]]:
        """[(element, clip json, take index, take)] for the root clip and its covers, latest usable take each."""
        r = self.load(root)
        if not r:
            return []
        out = []
        for n in [root] + list(r.get("covers") or []):
            s = self.load(n)
            bt = self.best_take(n) if s else None
            if bt:
                out.append((n, s, *bt))
        return out

    def roots(self) -> list[dict]:
        """Every root clip in clips/ (covers have a "parent")."""
        if not hasattr(self, "_roots"):
            out = []
            d = self.pdir / "clips"
            for f in sorted(d.glob("*.json")) if d.is_dir() else []:
                c = self.load(f.stem)
                if c and not c.get("parent"):
                    out.append({**c, "id": c.get("id") or f.stem})
            self._roots = out
        return self._roots

    def candidates(self, sh: dict) -> list[str]:
        """The shot's clips, primary first: the board's own ids, then clips made for this shot (clips/*.json "shot"),
        then clips whose needed span covers the shot (one window serving several shots); sung before motion."""
        out = [c for c in shot_clips(sh)]
        a, b = float(sh["t0"]), float(sh["t1"])
        mine = [c for c in self.roots() if c.get("shot") == sh.get("id")]
        span = [c for c in self.roots() if c.get("shot") != sh.get("id") and isinstance(c.get("needed"), list)
                and len(c["needed"]) == 2 and float(c["needed"][0]) <= a + 1e-3 and float(c["needed"][1]) >= b - 1e-3]
        for group in (mine, span):
            for c in sorted(group, key=lambda c: (not is_sing(c), c["id"])):
                if c["id"] not in out:
                    out.append(c["id"])
        return out

    def delivered(self, cid: str) -> bool:
        c = self.load(cid)
        if not c or (c.get("qa") or {}).get("verdict") == "reject":
            return False
        return self.best_take(cid) is not None

    # -------------------------------------------------------------------------------------------- segments (port)
    def segments(self, sh: dict, root: str) -> tuple[list[dict] | None, list[list[float]]]:
        els = self.chain(root)
        if els and is_sing(els[0][1]) and any(sync_of(tk)["spans"] for *_, tk in els):
            a, b = float(sh["t0"]), float(sh["t1"])
            segs: list[dict] = []
            holes: list[list[float]] = []
            T = a
            info = {n: (s, k, tk) for n, s, k, tk in els}
            named: dict[str, str] = {}
            spans = [(x0, x1, n) for n, s, k, tk in els for x0, x1 in sync_of(tk)["spans"]]
            while T < b - 1e-3:
                live = [(x1, x0, n) for x0, x1, n in spans if x0 - .06 <= T < x1 - .05]
                if live:
                    x1, x0, n = max(live)
                    end = min(b, x1)
                else:                                                  # a hole: the nearest element, flagged
                    nxt = sorted([(x0, n2) for x0, x1, n2 in spans if x0 > T])
                    end = min(b, nxt[0][0]) if nxt else b

                    def covers_T(n2: str, T: float = T) -> bool:
                        s2 = info[n2][0]
                        return song_t0(s2) - .01 <= T < song_t0(s2) + clip_dur(s2) - .1
                    prev = next((n2 for n2, *_ in els if segs and named.get(n2) == segs[-1]["clip"]), None)
                    order = [x for x in (nxt[0][1] if nxt else None, prev) if x] + [n2 for n2, *_ in els]
                    n = next((n2 for n2 in order if covers_T(n2)), nxt[0][1] if nxt else els[-1][0])
                    if covers_T(n):                                    # where this element's footage runs out
                        run_out = song_t0(info[n][0]) + clip_dur(info[n][0]) - .1
                        if T + .04 < run_out < end:
                            end = run_out
                    holes.append([round(T, 3), round(end, 3)])
                s, k, tk = info[n]
                name = engine_name(n, k)
                named[n] = name
                lag = sync_of(tk)["lag_s"]
                segs.append({"t0": round(T, 3), "clip": name, "in": round(max(0.0, T - song_t0(s) + lag), 3)})
                T = max(end, T + .04)
            return segs, holes
        return self._segments_linear(sh, root)

    def _segments_linear(self, sh: dict, root: str) -> tuple[list[dict] | None, list[list[float]]]:
        a, b = float(sh["t0"]), float(sh["t1"])
        els = self.chain(root)
        segs: list[dict] = []
        holes: list[list[float]] = []
        if not els:
            return None, [[a, b]]
        sing = is_sing(els[0][1])
        T = a
        for i, (n, s, k, tk) in enumerate(els):
            sy = sync_of(tk)
            t0s = song_t0(s)
            lag = sy["lag_s"] if (sing or sy["copy"]) else 0.0              # motion: only a measured copy
            span = sy["synced_song"] or [t0s, t0s + clip_dur(s)]
            last = i == len(els) - 1
            end = b if not sing else (span[1] if last or not sy["diverges"] else max(sy["cut"] or span[1], span[0]))
            if not last and sing and end <= T:
                continue
            name = engine_name(n, k)
            if sing and T < span[0] - .05:
                holes.append([round(T, 3), round(min(span[0], b), 3)])
            segs.append({"t0": round(T, 3), "clip": name, "in": round(max(0.0, T - t0s + lag), 3)})
            if not sing:
                return segs, holes
            if last and end < b - .05:
                holes.append([round(max(T, end), 3), round(b, 3)])
            T = max(T, end)
            if T >= b - 1e-3:
                break
        return segs, holes

    def fill_holes(self, segs: list[dict], holes: list[list[float]], alt: str) -> tuple[list[dict], list[list[float]]]:
        """Replace the singing chain's hole segments by the motion clip `alt` (linear in song time)."""
        els = self.chain(alt)
        if not els:
            return segs, holes
        n, s, k, tk = els[0]
        name = engine_name(n, k)
        t0s, dur = song_t0(s), clip_dur(s)
        out, left = [], []
        for g in segs:
            h = next((h for h in holes if abs(h[0] - g["t0"]) < 1e-3), None)
            if h and t0s - .01 <= h[0] < t0s + dur - .1:
                out.append({"t0": g["t0"], "clip": name, "in": round(max(0.0, h[0] - t0s), 3)})
            else:
                out.append(g)
                if h:
                    left.append(h)
        return out, left


def build(pdir: Path, shots_file: str | None = None, write: bool = True) -> dict:
    pdir = Path(pdir)
    S = load_shots(pdir, shots_file)
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    over = read_json(pdir / "edit/overrides.json", default=None) or read_json(pdir / "edl-overrides.json", default={}) or {}
    kinds = clip_kinds(pdir, S)
    ed = Edit(pdir)
    edl: dict[str, dict] = {}
    rows = []
    for sh in sorted(S["shots"], key=lambda s: float(s["t0"])):
        e: dict = {}
        holes: list = []
        src = "code"
        cands = ed.candidates(sh)
        forced = (over.get(sh["id"]) or {}).get("use")
        if forced and forced != "plate" and forced in cands:
            cands = [forced] + [c for c in cands if c != forced]
        live = [c for c in cands if ed.delivered(c)]
        tier = shot_tier(sh, kinds)
        clip = cands[0] if cands else None
        if tier in ("sung", "motion") and live and forced != "plate":
            clip = live[0]
            segs, holes = ed.segments(sh, clip)
            alt = next((c for c in live[1:] if not is_sing(ed.load(c))), None)
            if segs and holes and alt:            # lip sync given up on a span: cut to the shot's motion clip there
                segs, holes = ed.fill_holes(segs, holes, alt)
            if segs:
                e["segs"] = segs
                used_alt = alt and any(g["clip"].startswith(alt + "-t") for g in segs)
                src = f"clip {clip} x{len(segs)}" + (f" (+{alt})" if used_alt else "")
        if not e:
            pl = shot_plate(sh, S)
            f = resolve_file(pdir, (picks.get(pl) or {}).get("file")) if pl else None
            if pl and f and f.is_file():
                e["plate"] = pl
                src = f"plate {pl}" + (f" (stand-in for {clip})" if clip and tier in ("sung", "motion") else "")
            elif not is_code(sh):
                src = "MISSING" + (f" (plate {pl} not picked)" if pl else " (no plate)")
        if e:
            edl[sh["id"]] = e
        rows.append({"id": sh["id"], "t0": float(sh["t0"]), "t1": float(sh["t1"]), "src": src, "holes": holes})
    out = pdir / "edit/edl.json"
    if write:
        write_json(out, edl, indent=None)
    n = len(rows)
    miss = [r["id"] for r in rows if r["src"].startswith("MISSING")]
    hol = [r["id"] for r in rows if r["holes"]]
    lines = [f"{r['id']:6s} {r['t0']:7.2f}–{r['t1']:7.2f}  {r['src']}" + (f"  HOLES {r['holes']}" if r["holes"] else "")
             for r in rows]
    summary = (f"{n} shots · {len(edl)} with media · {len(miss)} missing a source · {len(hol)} with unsynced spans"
               + (" · edit/edl.json written" if write else ""))
    if ed.missing_files:
        summary += f"\n{len(ed.missing_files)} take file(s) listed in clips/*.json are missing on disk: " \
                   + ", ".join(sorted(ed.missing_files)[:6])
    text = "\n".join(lines[-40:] if len(lines) > 40 else lines) + "\n" + summary
    if miss:
        text += "\nnext: pick plates for the MISSING shots (`slop plates pick`) or mark code-drawn shots with \"code\": true."
    return {"edl": edl if not write else None, "path": str(out) if write else None, "shots": n, "with_media": len(edl),
            "missing": miss, "holes": hol, "missing_take_files": ed.missing_files, "rows": rows,
            "summary": summary.splitlines()[0], "text": text}
