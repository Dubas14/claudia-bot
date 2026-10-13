"""slop board audit — every storyboard gate of ARCHITECTURE §4.5, as code (EV ran these as a script before writing the
board and after every edit; research 01 §9.6, 03 §5.5 "CHECK with code and fix until all pass").

Gates (each PASS/FAIL with the shots to fix):
  tile          shots tile [0, duration] with no gaps/overlaps (1 ms tolerance; the end within 50 ms)
  cuts          every cut within 0.03 s of a beat/downbeat or a declared hit (hits.json hits/impact, project hits.add,
                or the shot's own "hit": seconds)
  words_typed   every aligned sung word starts inside a shot whose type[] lists its line
  graphics      one explaining graphic per lyric line (rule §7.3): each line with aligned words is served by a devices[]
                entry — one tagged {"line": N}, or an untagged one on the shot where the line's first word starts (else on
                another shot typing the line; one untagged device serves one line) — or by a code-drawn shot typing it.
                Camera moves (cam.*) draw nothing, so they never count as a graphic.
  devices       every devices[] entry is one the engine can draw (slop/board/devices.py reads the kinds, defaults and
                examples from engine/src/devices/*.js + engine/DEVICES.md): a known kind, only params the device
                reads, a timing key W|B|H|F|T, readable `at`/`until` time specs, `line` a real lyric line, no hint
                placeholder ("…", "<row 1>") or untouched catalogue-example text in what the device shows, no numeric
                `word` that is no lyric line. Anchors the engine cannot resolve and key-W words not sung in the shot
                are warnings.
  lead_share    lead_on_screen seconds / duration >= project.json board.lead_min (default 0.70)
  motion_budget sung+motion clip seconds <= budget.motion_s (default by tier) and clips <= board.max_clips (default 45,
                EV's cap: "<= 200 s across <= 45 clips"). Counted: every root clip gen made (clips/*.json without a
                "parent", except failed/declined ones that never delivered) plus every board seedance[] window not
                created yet; divergence covers are reported (covers_s), they come out of the draft's cover allowance.
  clip_windows  sung windows 4-8 s, motion 4-12 s; a sung window starts in a word gap and lists its exact words
                (board plans: EV's [t0-0.02, t1-0.08) rule; gen clips: their window mode's rule, clean = [t0+0.05, ...))
  plates_unique one plate per shot unless the shots are one continuous moment (adjacent + same clip); no two clips start
                from the same frame; no two plates in use picked to the same file; every plate a shot or clip uses is
                listed in plates[] (when the board has a plates[] list; an unused plates[] entry is a warning — the
                prompt book skips it)
  banned        no project.json "banned" word anywhere in the board (case-insensitive, whole words)
  treatments    every 2.5D (plate3d) shot names a treatment family and no two consecutive 2.5D shots share one, compared
                the way the renderer draws them (engine/src/devices/treat.js, read by slop/board/vocab.py): any name,
                alias, code or prose the engine accepts ("motion", "LS (rack)", "DI"); clip shots are transparent
                (the engine compares the plates on either side of a clip), and so are code-drawn shots; a still shot
                with a plate and an explicit treatment is compared too. A name the engine does not know
                draws a plain push (a warning); a depth family on a plate exported without a depth map draws a push
                (a warning, when engine/assets/plates.js says so).
  todo          no TODO marker left, no hint placeholder left in a shot's set / framing / action / prompts / camera /
                type text ("…", "<the place>": a next-step hint pasted as it was), and every shot has a framing
                (code-drawn shots excepted). The fixes it prints carry <…> markers that are refused until replaced.

Warnings (not gates): lead share > 85 %; the same transition twice in a row; a chapter with >= 5 2.5D/code shots but
fewer than 5 treatment families (ANIMATION_GUIDE "a chapter uses at least five different ones"); a gen clip made for a
shot that is not on the board, or outside the board's clip plan; a made clip the edit plays on no shot (made after the
board for a plate shot: the Studio run's motion clips never reached the edit) with its `board set RANGE --tier KIND
--clip ID`; a shot linking a clip that is neither planned nor made, or a clip of the other kind (a motion shot on a sung
clip); and, listed first, a sung shot (motion tier sung, or a motion shot on a sung clip) whose prompt, plate prompt,
action or lead canon puts a microphone, a hand or anything else at her mouth (its plate is the lip-sync start frame;
the Studio run measured 26 % in sync with a mic at her mouth), naming the shot whose prompt the book reads.

The report re-prints, for every board seedance[] window gen has not created yet, the exact `slop clip new` command
(`clip_cmds`), so ids, windows and the EDL line up.

Writes board/audit.json — the file the approval gate reads — only when it audits board/shots.json; `--shots OTHER.json`
writes OTHER.audit.json next to that file instead (an alternative board never counts as the audited board).
The human table is the command's text. Exit code 1 while any gate fails.
Changes from the source: generic (no EV words); clip records also read from clips/<clip>.json; tiers follow the
contract (still|plate3d|motion|sung) and legacy boards (seedance|plate25d|code) are mapped; the graphics gate and the
plate-listing check are code (EV checked graphics by eye).
"""
from __future__ import annotations

import bisect
import json
import re
import time
from pathlib import Path

from ..config import SlopError, load_project
from . import devices as devlib
from .common import (FRAMINGS, TODO, banned_words, clip_kinds, framing_of, graphic_hint, hit_times, is_code,
                     iter_strings, line_texts, load_beats, load_hits, load_shots, load_words, motion_budget_s,
                     mouth_blockers, pcmd, placeholder, read_json, set_hint, shot_clips, shot_plate, shot_tier,
                     sung_shot_ids, treatment_family, treatment_unknown, engine_treatment, write_json)
from .draft import clip_cmd, word_tokens, words_in

CUT_TOL = 0.03
DEFAULT_MAX_CLIPS = 45          # EV: "Seedance <= 200 s across <= 45 clips" (research 01 §9.6)
CLEAN_LO = .05                  # gen's clean vocal window keeps the words starting in [t0 + .05, t1 - .08)
GATES = ("tile", "cuts", "words_typed", "graphics", "devices", "lead_share", "motion_budget", "clip_windows",
         "plates_unique", "banned", "treatments", "todo")


def _graphic(d) -> bool:
    try:
        return devlib.is_graphic(d)
    except SlopError:                              # no device library: count it, the devices gate reports why
        return bool(d)


def _depth_families() -> list[str]:
    try:
        from .vocab import treatments
        return treatments()["depth"]
    except Exception:  # noqa: BLE001
        return ["layers", "rack", "relight", "contours", "scan"]


def _engine_families() -> list[str]:
    try:
        from .vocab import treatments
        return treatments()["families"]
    except Exception:  # noqa: BLE001
        return []


def _depth_index(pdir: Path) -> dict | None:
    """plate -> has a usable depth map, from the last `slop edit export` (engine/assets/plates.js); None before any."""
    f = Path(pdir) / "engine/assets/plates.js"
    if not f.is_file():
        return None
    try:
        txt = f.read_text(encoding="utf-8")
        idx = json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))
    except (OSError, ValueError):
        return None
    return {k: bool(isinstance(v, dict) and v.get("depth") is not False and v.get("subject_depth") is not None)
            for k, v in idx.items()} if isinstance(idx, dict) else None


def _near(arr: list[float], t: float) -> tuple[float, float]:
    if not arr:
        return float("inf"), t
    i = bisect.bisect_left(arr, t)
    best = min((arr[j] for j in (i - 1, i) if 0 <= j < len(arr)), key=lambda c: abs(c - t))
    return abs(best - t), best


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (s or "").lower()))


def _kind(c: dict) -> str:
    return "sung" if (c.get("kind") == "sung" or (c.get("kind") is None and c.get("sing"))) else "motion"


def _clip_files(pdir: Path) -> dict[str, dict]:
    d = Path(pdir) / "clips"
    out: dict[str, dict] = {}
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(c, dict):
            out[str(c.get("id") or f.stem)] = c
    return out


def clip_records(pdir: Path, S: dict) -> tuple[dict[str, dict], dict]:
    """clip id -> {kind, song_t0, duration, words, shots, plate, start, src, lo} for the board's planned windows
    (seedance[], src "board") overlaid by the clips gen actually made (clips/*.json root clips, src "clips");
    plus extras {covers_s, covers}."""
    recs: dict[str, dict] = {}
    for c in S.get("seedance", []):
        cid = c.get("clip") or c.get("id")
        if not cid:
            continue
        recs[cid] = {"kind": _kind(c), "song_t0": c.get("song_t0"), "duration": c.get("duration"), "words": c.get("words"),
                     "shots": list(c.get("shots") or []), "plate": c.get("plate"), "start": c.get("start"),
                     "src": "board", "lo": -.02, "plan": c}
    extra = {"covers_s": 0.0, "covers": 0}
    for cid, cj in _clip_files(pdir).items():
        dur = (cj.get("body") or {}).get("duration") or cj.get("duration")
        if cj.get("parent"):                       # a divergence cover: paid from the cover allowance
            extra["covers"] += 1
            extra["covers_s"] += float(dur or 0)
            continue
        delivered = any(t.get("file") for t in cj.get("takes") or [] if isinstance(t, dict))
        if cj.get("status") in ("failed", "declined") and not delivered:
            continue                               # nothing spent, nothing on screen
        plan = (recs.get(cid) or {}).get("plan")
        recs[cid] = {"kind": _kind(cj), "song_t0": cj.get("song_t0"), "duration": dur, "words": cj.get("words"),
                     "shots": list((plan or {}).get("shots") or []), "plate": (plan or {}).get("plate") or cj.get("plate"),
                     "start": cj.get("start"), "src": "clips", "made_for": cj.get("shot"), "needed": cj.get("needed"),
                     "lo": CLEAN_LO if (cj.get("window") or {}).get("mode") == "clean" else -.02, "plan": plan}
    extra["covers_s"] = round(extra["covers_s"], 2)
    return recs, extra


def audit(pdir: Path, shots_file: str | None = None) -> dict:
    proj = load_project(pdir)
    S = load_shots(pdir, shots_file)
    B = load_beats(pdir)
    W = load_words(pdir)
    hits = load_hits(pdir)
    cfg = proj.get("board") or {}
    kinds = clip_kinds(pdir, S)
    shots = sorted(S["shots"], key=lambda s: (float(s["t0"]), float(s["t1"])))
    dur = float(B["duration"])
    G: dict[str, dict] = {g: {"ok": True, "fails": [], "info": {}} for g in GATES}
    warnings: list[str] = []

    def fail(g: str, msg: str) -> None:
        G[g]["ok"] = False
        G[g]["fails"].append(msg)

    # ---- tile
    ids = [s.get("id") for s in shots]
    for d in sorted({i for i in ids if ids.count(i) > 1}):
        fail("tile", f"duplicate shot id {d}")
    if [s.get("id") for s in S["shots"]] != ids:
        fail("tile", "shots are not in time order in shots.json (sort them by t0)")
    if shots:
        if abs(float(shots[0]["t0"])) > 1e-3:
            fail("tile", f"{shots[0]['id']} starts at {shots[0]['t0']} — the first shot must start at 0")
        if abs(float(shots[-1]["t1"]) - dur) > .05:
            fail("tile", f"{shots[-1]['id']} ends at {shots[-1]['t1']} — the last shot must end at the song's end ({dur:.3f})")
    else:
        fail("tile", "no shots")
    for s in shots:
        if float(s["t1"]) <= float(s["t0"]):
            fail("tile", f"{s['id']} is empty or reversed ({s['t0']}–{s['t1']}): t1 must be after t0")
    for a, b in zip(shots, shots[1:]):
        gap = float(b["t0"]) - float(a["t1"])
        if gap > 1e-3:
            fail("tile", f"gap {a['t1']}–{b['t0']} between {a['id']} and {b['id']}")
        elif gap < -1e-3:
            fail("tile", f"overlap {b['t0']}–{a['t1']} between {a['id']} and {b['id']}")
    G["tile"]["info"] = {"shots": len(shots), "duration": dur}

    # ---- cuts
    grid = sorted(set(B["beats"]) | set(B["downbeats"]))
    hts = hit_times(hits, proj)
    worst = 0.0
    for s in shots[1:]:
        c = float(s["t0"])
        e, nb = _near(grid, c)
        eh, _ = _near(hts, c)
        own = abs(c - float(s["hit"])) if isinstance(s.get("hit"), (int, float)) else float("inf")
        err = min(e, eh, own)
        worst = max(worst, err)
        if err > CUT_TOL + 1e-6:
            fail("cuts", f"{s['id']} cut at {c:.3f} is {e:.3f} s off the beat grid (nearest beat {nb:.3f})")
    G["cuts"]["info"] = {"cuts": max(0, len(shots) - 1), "max_err_s": round(worst, 4), "tolerance_s": CUT_TOL}

    # ---- words typed
    starts = [float(s["t0"]) for s in shots]

    def shot_at(t: float) -> int:
        return max(0, min(len(shots) - 1, bisect.bisect_right(starts, t) - 1))

    missing: dict = {}
    prose = set()
    for w in W["words"]:
        if w.get("line") is None or not shots:
            continue
        sh = shots[shot_at(w["t0"])]
        ty = sh.get("type")
        if isinstance(ty, str):
            prose.add(sh["id"])
            continue
        typed = {t.get("line") for t in (ty or []) if isinstance(t, dict)}
        if w["line"] not in typed:
            missing.setdefault((w["line"], sh["id"]), []).append(w.get("w", ""))
    for (li, sid), ws in sorted(missing.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        fail("words_typed", f"line {li}: {len(ws)} word(s) start in {sid} but its type[] has no entry for line {li} "
                            f"({' '.join(ws)[:60]})")
    for sid in sorted(prose):
        fail("words_typed", f"{sid}: type is prose — write it as a list [{{line, mode, text, placement}}]")
    G["words_typed"]["info"] = {"words": len(W["words"]), "untyped": sum(len(v) for v in missing.values())}
    if W.get("missing"):
        G["words_typed"]["info"]["note"] = "analysis/words.json missing: nothing to check"

    # ---- graphics: one explaining graphic per lyric line
    by_line: dict[int, list] = {}
    for w in W["words"]:
        if w.get("line") is not None:
            try:
                by_line.setdefault(int(w["line"]), []).append(w)
            except (TypeError, ValueError):
                continue
    typed_by: dict[int, set] = {}
    tagged: set = set()
    pool: dict[int, int] = {}
    for i, s in enumerate(shots):
        for t in s.get("type") if isinstance(s.get("type"), list) else []:
            if isinstance(t, dict) and isinstance(t.get("line"), int):
                typed_by.setdefault(t["line"], set()).add(i)
        n = 0
        for d in s.get("devices") if isinstance(s.get("devices"), list) else []:
            if not _graphic(d):
                continue                           # a camera move draws nothing: never the line's graphic
            if isinstance(d, dict) and isinstance(d.get("line"), int):
                tagged.add(d["line"])
            elif d:
                n += 1
        pool[i] = n
    texts = line_texts(pdir, W) if by_line else {}
    unexplained = []
    if shots:
        for li in sorted(by_line, key=lambda k: min(w["t0"] for w in by_line[k])):
            if li in tagged:
                continue
            ws = by_line[li]
            first_i = shot_at(min(w["t0"] for w in ws))
            others = sorted((typed_by.get(li, set()) | {shot_at(w["t0"]) for w in ws}) - {first_i})
            cand = [first_i] + others
            got = next((i for i in cand if pool.get(i, 0) > 0), None)
            if got is not None:
                pool[got] -= 1
                continue
            if any(is_code(shots[i]) for i in cand):
                continue
            unexplained.append(li)
            w0 = re.sub(r"[^\w'-]", "", min(ws, key=lambda w: w["t0"]).get("w", ""))
            fail("graphics", f"line {li} (\"{(texts.get(li) or '')[:40]}\"): no explaining graphic — add a devices[] "
                             f"entry to {shots[first_i]['id']} (its first word starts there; replace the <…> text): "
                             + graphic_hint(pdir, shots[first_i]["id"], li, w0)
                             + " (`slop board device kinds` lists the devices)")
    G["graphics"]["info"] = {"lines": len(by_line), "explained": len(by_line) - len(unexplained)}

    # ---- devices: every entry is one the engine can draw
    try:
        lines_known = {int(li) for li in by_line} | {int(l["line"]) for l in W.get("lines", [])
                                                     if isinstance(l.get("line"), int)}
        boxes = read_json(pdir / "plates/boxes.json", default={}) or {}
        boxes = {k: (v.get("boxes") if isinstance(v, dict) and "boxes" in v else v) for k, v in boxes.items()}
        dv = devlib.check_board({"shots": shots}, lines_known if W["words"] or W.get("lines") else None, boxes,
                                W["words"], lambda sh: shot_plate(sh, S), devlib.display_tokens(pdir, W))
        for m in dv["errors"]:
            fail("devices", m)
        warnings.extend(f"devices: {m}" for m in dv["warnings"][:40])
        G["devices"]["info"] = {"devices": dv["devices"], "kinds": len(devlib.kinds())}
    except SlopError as e:                          # no engine device library in this checkout
        fail("devices", str(e))

    # ---- lead share
    total = sum(float(s["t1"]) - float(s["t0"]) for s in shots) or 1.0
    lead = sum(float(s["t1"]) - float(s["t0"]) for s in shots if s.get("lead_on_screen"))
    lead_min = float(cfg.get("lead_min", 0.70))
    share = lead / total
    if share + 1e-9 < lead_min:
        fail("lead_share", f"lead on screen {share * 100:.1f}% < {lead_min * 100:.0f}%: put her in more shots "
                           "(honest presence: face, figure or back view)")
    G["lead_share"]["info"] = {"share": round(share, 4), "min": lead_min}

    # ---- motion budget (planned windows + the clips gen actually made)
    recs, extra = clip_records(pdir, S)
    budget = motion_budget_s(proj)
    if recs:
        sung = sum(float(r.get("duration") or 0) for r in recs.values() if r["kind"] == "sung")
        mot = sum(float(r.get("duration") or 0) for r in recs.values() if r["kind"] == "motion")
    else:
        sung = sum(float(s["t1"]) - float(s["t0"]) for s in shots if shot_tier(s, kinds) == "sung")
        mot = sum(float(s["t1"]) - float(s["t0"]) for s in shots if shot_tier(s, kinds) == "motion")
    if sung + mot > budget + 1e-6:
        fail("motion_budget", f"{sung + mot:.1f} s of sung+motion clips (planned + made) > budget {budget:g} s "
                              "(project.json budget.motion_s): turn some clips back into 2.5D plates")
    max_clips = int(cfg.get("max_clips", DEFAULT_MAX_CLIPS))
    if len(recs) > max_clips:
        fail("motion_budget", f"{len(recs)} clips > {max_clips} (project.json board.max_clips; EV's cap was 45): merge "
                              "short windows or turn clips back into 2.5D plates")
    G["motion_budget"]["info"] = {"sung_s": round(sung, 2), "motion_s": round(mot, 2), "budget_s": budget,
                                  "clips": len(recs), "made": sum(1 for r in recs.values() if r["src"] == "clips"),
                                  "max_clips": max_clips, "covers_s": extra["covers_s"]}

    # ---- clip windows
    tok = word_tokens(W)
    by_id = {s["id"]: s for s in shots}
    for cid, r in sorted(recs.items()):
        d = r.get("duration")
        lo, hi = (4, 8) if r["kind"] == "sung" else (4, 12)
        if d is None or not (lo - 1e-6 <= float(d) <= hi + 1e-6):
            fail("clip_windows", f"{cid}: {r['kind']} clip is {d} s — must be {lo}-{hi} s")
        t0 = r.get("song_t0")
        if r["kind"] == "sung" and t0 is not None and d:
            inside = [w for w in W["words"] if w["t0"] + .01 < float(t0) < w["t1"] - .01]
            if inside:
                fail("clip_windows", f"{cid}: song_t0 {t0} is inside the word '{inside[0].get('w', '')}' — start the "
                                     "window in a word gap")
            exp = words_in(tok, float(t0), float(t0) + float(d), r.get("lo", -.02))
            if r.get("words") is not None and _norm(r["words"]) != _norm(exp):
                fail("clip_windows", f"{cid}: words must be exactly the words sung in the window: \"{exp}\"")
        for sid in r.get("shots") or []:
            if sid not in by_id:
                fail("clip_windows", f"{cid}: lists shot {sid}, which is not in the board")
        if r["src"] == "clips" and r.get("made_for") and r["made_for"] not in by_id:
            warnings.append(f"clip {cid} was made for shot {r['made_for']}, which is not on the board (the edit uses it "
                            "only where its needed span covers a shot)")
    planned_shots = {sid: cid for cid, r in recs.items() if r.get("plan") for sid in r["plan"].get("shots") or []}
    reach = _reachable_clips(pdir, shots, kinds)
    for cid, r in sorted(recs.items()):
        if r["src"] != "clips" or r.get("plan"):
            continue
        rng = _span_range(shots, r.get("needed"), r.get("made_for"))
        link = pcmd(pdir, f"board set {rng} --tier {r['kind']} --clip {cid}")
        if r.get("made_for") in planned_shots:
            warnings.append(f"clip {cid} (made for {r['made_for']}) is not on the board's clip plan, which plans "
                            f"{planned_shots[r['made_for']]} there: to play {cid}, link it to its shots ({link}), or "
                            "create board clips with their cmd (same id)")
        elif reach is not None and cid not in reach and r.get("made_for") in by_id:
            warnings.append(f"clip {cid} ({r['kind']}, made for {r['made_for']}) plays on no shot: the edit plays a clip "
                            f"only on a motion or sung shot, and {rng} {'is' if '-' not in rng else 'are'} "
                            f"{shot_tier(by_id[r['made_for']], kinds)} — link it ({link}), then `"
                            + pcmd(pdir, "edit edl") + "`")
    G["clip_windows"]["info"] = {"clips": len(recs)}

    # ---- plates unique (+ every plate listed, every listed plate used)
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    groups: dict[str, list] = {}
    for s in shots:
        p = shot_plate(s, S)
        tier = shot_tier(s, kinds)
        if not p:
            if not is_code(s) and tier in ("plate3d", "still"):
                fail("plates_unique", f"{s['id']}: a {tier} shot without a plate (set its plate key)")
            continue
        groups.setdefault(p, []).append(s)

    def continuous(a: dict, b: dict) -> bool:
        ca, cb = shot_clips(a), shot_clips(b)
        return abs(float(a["t1"]) - float(b["t0"])) < 1e-3 and bool(ca) and bool(cb) and ca[0] == cb[0]

    for p, L in groups.items():
        need = [L[0]] + [cur for prev, cur in zip(L, L[1:]) if not continuous(prev, cur)]
        if len(need) > 1:
            fail("plates_unique", f"plate {p} is on {', '.join(s['id'] for s in need)} (not one continuous moment) — "
                                  "run `slop plates vary` (other candidates) or give each shot its own plate")
    starts_of: dict[str, str] = {}
    for cid, r in sorted(recs.items()):
        key = r.get("start") or ((picks.get(r.get("plate")) or {}).get("file")) or r.get("plate")
        if not key:
            continue
        if key in starts_of:
            fail("plates_unique", f"clips {starts_of[key]} and {cid} start from the same frame ({key}) — run "
                                  "`slop plates vary`")
        else:
            starts_of[key] = cid
    listed = {p.get("plate") for p in S.get("plates", []) if p.get("plate")}
    used = set(groups) | {r.get("plate") for r in recs.values() if r.get("plate")}
    used.discard(None)
    if listed:
        for key in sorted(used - listed):
            who = ", ".join(s["id"] for s in groups.get(key, [])) or ", ".join(
                cid for cid, r in sorted(recs.items()) if r.get("plate") == key)
            fail("plates_unique", f"plate {key} (used by {who}) is not listed in plates[] — add "
                                  f"{{\"plate\": \"{key}\", \"used_by\": [...]}} to plates[] (the prompt book reads it)")
        for key in sorted(listed - used):
            warnings.append(f"plates[] lists {key} but no shot or clip uses it: delete that entry (the prompt book "
                            "skips unused plates)")
    elif used and S.get("plates") is not None:
        warnings.append("the board has no plates[] list: `slop plates book` reads the prompts from the shots")
    live = used | listed
    files: dict[str, str] = {}
    for p, v in sorted(picks.items()):
        if live and p not in live:
            continue                               # a stale pick (e.g. an old variant) is not on screen
        f = (v or {}).get("file")
        if f and f in files:
            fail("plates_unique", f"plates {files[f]} and {p} are picked to the same image {f} — pick another candidate "
                                  f"for one of them (`slop plates status` lists candidates; `slop plates pick {p} K`), "
                                  "then re-run `slop plates vary`")
        elif f:
            files[f] = p
    G["plates_unique"]["info"] = {"plates": len(groups), "picked": len(picks), "listed": len(listed)}

    # ---- banned words
    bw = banned_words(proj)
    if bw:
        pat = re.compile(r"\b(" + "|".join(re.escape(w) for w in bw) + r")\b", re.I)
        for top in ("shots", "seedance", "plates", "chapters"):
            for path, s in iter_strings(S.get(top, []), top):
                m = pat.search(s)
                if m:
                    fail("banned", f"{_where(S, path)}: banned word '{m.group(1)}'")
    G["banned"]["info"] = {"banned": len(bw), "note": "" if bw else "no project.json \"banned\" list"}

    # ---- treatments
    # Like the engine's plan (treat.js): clip shots are transparent (the plates on either side are compared), a plate
    # shot without a treatment is auto-picked (never a repeat), a plate shot with one is compared as the family it draws
    # (a depth family without a depth map draws a push). Code-drawn shots are skipped too (docs/70 §11: the rule is
    # about consecutive 2.5D shots), which is stricter than the renderer.
    prev = None
    n3d = 0
    depth_of = _depth_index(pdir)
    depth_fams = set(_depth_families())
    for s in shots:
        tier = shot_tier(s, kinds)
        if is_code(s):
            continue                                # not a 2.5D shot: the 2.5D shots on either side are compared
                                                    # (docs/70 §11 — stricter than the renderer, which resets there)
        if tier in ("sung", "motion") and shot_clips(s):
            continue                                # a clip shot: the engine compares across it
        if not (tier == "plate3d" or (tier == "still" and shot_plate(s, S))):
            continue
        n3d += tier == "plate3d"
        fam = treatment_family(s)
        efam = engine_treatment(s)          # compared as the engine draws it, whichever vocabulary the board uses
        if not fam:
            if tier == "plate3d":
                fail("treatments", f"{s['id']}: a 2.5D shot needs a treatment — "
                                   + pcmd(pdir, "board set " + s["id"] + ' --treatment "<family>"')
                                   + " (layers | relight | contours | scan | rack | stills | diagram | push | occlusion"
                                     " | xerox in a print look | auto = the engine rotates its families; the board's "
                                     "names layer-separation, depth-as-image, diagram-over-image, stills-in-rhythm "
                                     "work too)")
            prev = None                             # auto-picked by the engine: never a repeat
            continue
        if fam == "auto" and efam is None:
            prev = None                             # "auto": the engine's five-family rotation picks it (treat.js
            continue                                # plan), never the family of the shot before
        if treatment_unknown(s):
            warnings.append(f"{s['id']}: treatment '{fam}' is not one the engine knows — it draws a plain push "
                            "(families: " + ", ".join(_engine_families()) + ")")
        plate = shot_plate(s, S)
        if efam in depth_fams and depth_of is not None and plate in depth_of and not depth_of[plate]:
            warnings.append(f"{s['id']}: treatment '{fam}' needs the plate's depth map, which {plate} has none of in "
                            "the last export — it draws a push (`slop edit export --depth on`)")
            efam = "push"
        if prev and efam == prev[1]:
            fail("treatments", f"{prev[0]} and {s['id']} are consecutive 2.5D shots with the same treatment '{fam}'"
                               + (f" (both draw as '{efam}')" if efam != fam else "")
                               + " — pick another: " + pcmd(pdir, "board set " + s["id"] + ' --treatment "<family>"')
                               + " (families: " + ", ".join(_engine_families()) + ")")
        prev = (s["id"], efam, fam)
    G["treatments"]["info"] = {"plate3d_shots": n3d}
    for ch in S.get("chapters", []):
        try:
            c0, c1 = float(ch.get("t0", ch.get("start"))), float(ch.get("t1", ch.get("end")))
        except (TypeError, ValueError):
            continue
        fams = [("motion" if is_code(s) else engine_treatment(s)) for s in shots
                if c0 - 1e-3 <= float(s["t0"]) < c1 - 1e-3 and (is_code(s) or shot_tier(s, kinds) == "plate3d")]
        distinct = {f for f in fams if f}
        n_auto = sum(1 for s in shots if c0 - 1e-3 <= float(s["t0"]) < c1 - 1e-3 and not is_code(s)
                     and shot_tier(s, kinds) == "plate3d" and treatment_family(s) == "auto")
        if len(fams) >= 5 and len(distinct) + n_auto < 5:     # "auto" shots rotate through the engine's families
            warnings.append(f"chapter {ch.get('id') or ch.get('name')}: {len(distinct)} different 2.5D treatments over "
                            f"{len(fams)} 2.5D/code shots — a chapter uses at least five (add a family, or a pure-motion "
                            "code-drawn shot)")

    # ---- TODO markers
    # The draft's per-line note "TODO: one explaining graphic for line N (...)" is the graphics gate's own reminder:
    # once that gate counts line N as explained, the note is resolved (no second bookkeeping step for the operator).
    graphic_note = re.compile(re.escape(TODO) + r": one explaining graphic for line (\d+) \([^)]*\)(; )?")
    explained_lines = set(by_line) - set(unexplained) if shots else set()
    todo = 0
    for top in ("shots", "seedance", "plates", "chapters"):
        for path, s in iter_strings(S.get(top, []), top):
            if TODO in s and path.endswith(".notes"):
                s = graphic_note.sub(lambda m: "" if int(m.group(1)) in explained_lines else m.group(0), s)
            if TODO in s:
                todo += 1
                if todo <= 400:
                    where = _where(S, path)
                    gm = graphic_note.search(s) if path.endswith(".notes") else None
                    fail("todo", f"{where}: {s[:60]}"
                                 + (f" → add line {gm.group(1)}'s explaining graphic (the graphics gate prints the "
                                    "command); this note then clears itself" if gm else _todo_fix(pdir, where, top)))
    # a next-step hint pasted word for word ("…", "<the place>") is a TODO too: the lead has not written the field
    placeholders = 0
    for top in ("shots", "plates"):
        for path, s in iter_strings(S.get(top, []), top):
            if TODO in s or not re.search(r"\.(set|framing|action|img_prompt|mj_prompt|prompt|camera|text)$", path):
                continue                            # TODO markers are counted above; device text: the devices gate
            if ".devices[" in path or (".type[" not in path and path.endswith(".text")):
                continue
            ph = placeholder(s)
            if ph:
                placeholders += 1
                where = _where(S, path)
                fail("todo", f"{where}: {ph}{_todo_fix(pdir, where, top)}")
    for s in shots:
        if not is_code(s) and not framing_of(s) and not placeholder(str(s.get("framing", ""))):
            fail("todo", f"{s['id']}.framing: '{s.get('framing', '')}' — one of {'|'.join(FRAMINGS)} → "
                         + set_hint(pdir, s["id"], ["framing"]))
    G["todo"]["info"] = {"markers": todo, "placeholders": placeholders}

    # ---- warnings (not gates)
    mouth = _mouth_warnings(pdir, proj, S, shots, kinds)
    for s in shots:                                 # a shot's linked clip: one that exists, of the shot's kind
        cl = shot_clips(s)
        if not cl or is_code(s):
            continue
        tier = str(s.get("motion_tier") or "").lower()
        if cl[0] not in kinds:
            warnings.append(f"{s['id']} links clip {cl[0]}, which is neither on the board's clip plan (seedance[]) nor "
                            f"made (clips/): link a clip that exists ({pcmd(pdir, 'board set ' + s['id'] + ' --clip <clip id>')}"
                            f"; `slop clip list`) or make it with `slop clip new`")
        elif tier in ("sung", "motion") and kinds[cl[0]] != tier:
            warnings.append(f"{s['id']} is a {tier} shot but its clip {cl[0]} is a {kinds[cl[0]]} clip: "
                            + pcmd(pdir, f"board set {s['id']} --tier {kinds[cl[0]]}") + " (or link a "
                            f"{tier} clip with --clip)")
    if share > 0.85:
        warnings.append(f"lead on screen {share * 100:.0f}% (> 85%): leave room for inserts and graphics")
    last_tr = None
    for s in shots:
        tr = (s.get("transition_in") or s.get("trans") or "cut")
        tr = tr.get("preset") if isinstance(tr, dict) else tr
        tr = str(tr).split()[0].lower() if tr else "cut"
        if tr != "cut" and tr == last_tr:
            warnings.append(f"{s['id']}: transition '{tr}' twice in a row (never the same device twice in a row)")
        last_tr = tr

    # ---- the clips still to create, with the exact command (ids/windows match the board)
    clip_cmds = []
    for cid, r in sorted(recs.items(), key=lambda kv: float(kv[1].get("song_t0") or 0)):
        if r["src"] != "board":
            continue
        c = dict(r["plan"])
        first = by_id.get((c.get("shots") or [None])[0])
        if c.get("plate") and first is not None and shot_plate(first, S) != c["plate"] and not c.get("start"):
            f = (picks.get(c["plate"]) or {}).get("file")
            if f:
                c["start"] = f                     # `slop plates vary` gave this clip its own start frame
        clip_cmds.append({"clip": cid, "cmd": clip_cmd(pdir, c)})

    warnings[:0] = mouth                            # first: a sung plate with a blocked mouth wastes a paid clip
    ok = all(g["ok"] for g in G.values())
    stats = {"shots": len(shots), "duration": dur, "lead_share": round(share, 4), "clips": len(recs),
             "planned_clip_s": round(sung + mot, 2), "todo_markers": todo, "clips_to_create": len(clip_cmds),
             "sung_shots": len(sung_shot_ids(S, kinds)), "mouth_warnings": len(mouth)}
    return {"ok": ok, "gates": G, "warnings": warnings, "stats": stats, "clip_cmds": clip_cmds,
            "shots_file": str(Path(shots_file) if shots_file else pdir / "board/shots.json"),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _reachable_clips(pdir: Path, shots: list[dict], kinds: dict[str, str]) -> set[str] | None:
    """Every clip the edit may play somewhere: the candidates (slop/edit/edl.py, the edit's own rule) of every motion
    or sung shot. None when the edit module is not installed."""
    try:
        from ..edit.edl import Edit
    except ImportError:
        return None
    ed = Edit(pdir)
    out: set[str] = set()
    for s in shots:
        if not is_code(s) and shot_tier(s, kinds) in ("sung", "motion"):
            out.update(ed.candidates(s))
    return out


def _span_range(shots: list[dict], needed, made_for: str | None) -> str:
    """The shots a clip's needed span covers as a `board set` selection ("s005-s006"), else the shot it was made for."""
    try:
        n0, n1 = float(needed[0]), float(needed[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return made_for or "SHOT"
    idx = [i for i, s in enumerate(shots) if float(s["t0"]) >= n0 - .05 and float(s["t1"]) <= n1 + .05]
    if not idx or idx != list(range(idx[0], idx[-1] + 1)):
        return made_for or "SHOT"
    a, b = shots[idx[0]]["id"], shots[idx[-1]]["id"]
    return a if a == b else f"{a}-{b}"


def _mouth_warnings(pdir: Path, proj: dict, S: dict, shots: list[dict], kinds: dict[str, str]) -> list[str]:
    """A sung shot's plate is its clip's lip-sync start frame: warn when its prompt (the shot's own prompt, the plate
    prompt the book reads, its action) or the lead canon it pulls in puts a microphone, a hand or anything else at the
    mouth (the Studio run: a mic at her mouth held c06 to 26 % in sync)."""
    ids = sung_shot_ids(S, kinds)
    if not ids:
        return []
    from .plates import plate_entries
    try:
        book = {e["plate"]: e["prompt"] for e in plate_entries(S, proj) if e.get("prompt")}
    except Exception:  # noqa: BLE001 - a malformed plates[] list: the shots' own prompts are still checked
        book = {}
    lead = proj.get("lead") or {}
    owner: dict[str, tuple[str, str]] = {}          # plate -> (shot whose own prompt the book reads, its prompt key)
    for s in shots:
        base = (shot_plate(s, S) or "").split("~")[0]
        for k in ("mj_prompt", "img_prompt"):
            if base and base not in owner and isinstance(s.get(k), str) and s[k] == book.get(base):
                owner[base] = (s["id"], k)
    out: list[str] = []
    canon_shots: dict[str, list[str]] = {}
    for s in shots:
        if s.get("id") not in ids:
            continue
        texts = [(k, s[k]) for k in ("mj_prompt", "img_prompt", "action")
                 if isinstance(s.get(k), str) and s[k].strip() and TODO not in s[k]]
        pl = shot_plate(s, S)
        base = (pl or "").split("~")[0]
        pp = book.get(base)
        if isinstance(pp, str) and pp.strip() and TODO not in pp and all(pp != t for _, t in texts):
            texts.append((f"plate {pl} prompt", pp))
        hits = [(where, f"{where} mentions {', '.join(repr(b) for b in bl)}") for where, t in texts
                for bl in [mouth_blockers(t)] if bl]
        if hits:
            fixes = []
            for where, _ in hits:                   # the field to rewrite: the shot's own, or the plate prompt's owner
                if where == "action":
                    fix = pcmd(pdir, f"board set {s['id']} --action \"<what her mouth does, nothing at it>\"")
                elif where.startswith("plate ") and base in owner:
                    o, k = owner[base]
                    fix = pcmd(pdir, f"board set {o} --{k.replace('_', '-')} \"<the prompt, mouth clear>\"") + (
                        f" — the book reads {base}'s prompt from {o}" if o != s["id"] else "")
                elif where.startswith("plate "):
                    fix = f"the plates[] entry {base} in board/shots.json (its prompt)"
                else:
                    fix = pcmd(pdir, f"board set {s['id']} --{where.replace('_', '-')} \"<the prompt, mouth clear>\"")
                if fix not in fixes:
                    fixes.append(fix)
            out.append(f"{s['id']} is a sung shot (lip sync) but its " + "; ".join(h for _, h in hits) + " — a "
                       "microphone, hand or hair in front of her mouth breaks the lip sync: rewrite it with the mouth "
                       "fully visible (" + "; ".join(fixes) + "); `plates book` adds the mouth line to sung plates "
                       "itself")
        prompts = " ".join(t for k, t in texts if k != "action")
        if s.get("lead_on_screen") or any(ph in prompts for ph in ("{lead}", "{her}", "{far}")):
            for key in ("canon", "far"):
                for b in mouth_blockers(str(lead.get(key) or "")):
                    canon_shots.setdefault(f"lead.{key}|{b}", []).append(s["id"])
    for k, sids in canon_shots.items():
        key, b = k.split("|", 1)
        out.append(f"the lead canon (project.json {key}) puts {b!r} at her mouth on {len(sids)} sung shot(s) "
                   f"({', '.join(sids[:6])}{' …' if len(sids) > 6 else ''}): on sung plates keep it at her cheek, clear of "
                   "the lips, or write those prompts without it")
    return out


def _todo_fix(pdir: Path, where: str, top: str) -> str:
    """' → slop -p P board set s004 --set "<the place, concrete>"' for a shot field (the <…> marker is refused as it
    stands: the operator writes the value), else ''."""
    m = re.fullmatch(r"(s[\w-]+)\.(set|framing|action|img_prompt|mj_prompt|camera|notes)", where) \
        if top == "shots" else None
    return (" → " + set_hint(pdir, m.group(1), [m.group(2)])) if m else ""


def _where(S: dict, path: str) -> str:
    """'shots[3].action' -> 's004.action'."""
    m = re.match(r"(shots|seedance|plates|chapters)\[(\d+)\](.*)", path)
    if not m:
        return path
    top, i, rest = m.group(1), int(m.group(2)), m.group(3)
    try:
        item = S[top][i]
    except (KeyError, IndexError):
        return path
    name = item.get("id") or item.get("clip") or item.get("plate") or f"{top}[{i}]"
    return f"{name}{rest}"


def table(rep: dict, per_gate: int = 5, report_name: str = "board/audit.json") -> str:
    rows = ["GATE           RESULT  DETAIL"]
    for g in GATES:
        r = rep["gates"][g]
        info = r["info"]
        if r["ok"]:
            detail = ", ".join(f"{k}={v}" for k, v in info.items() if v not in ("", None))
            rows.append(f"{g:<14} PASS    {detail}")
        else:
            rows.append(f"{g:<14} FAIL    {len(r['fails'])} issue(s)")
            for f in r["fails"][:per_gate]:
                rows.append(f"{'':<22}- {f}")
            if len(r["fails"]) > per_gate:
                rows.append(f"{'':<22}… {len(r['fails']) - per_gate} more in {report_name}")
    for w in rep.get("warnings", [])[:8]:
        rows.append(f"warning: {w}")
    cmds = rep.get("clip_cmds") or []
    if cmds:
        rows.append(f"clips planned on the board, not created yet ({len(cmds)}; run each after its plate is picked):")
        rows += [f"  {c['cmd']}" for c in cmds[:6]]
        if len(cmds) > 6:
            rows.append(f"  … {len(cmds) - 6} more in {report_name} (clip_cmds)")
    n_fail = sum(1 for g in GATES if not rep["gates"][g]["ok"])
    rows.append("ALL GATES PASS — send the contact sheet (`slop board sheet`) to the owner for approval."
                if not n_fail else f"{n_fail} gate(s) fail — fix the fields listed with `slop board set SHOT --FIELD …` "
                                   "(many shots: `slop board fill FILE`; graphics: `slop board device add|rm`), then "
                                   "re-run `slop board audit`.")
    return "\n".join(rows)


def report_path(pdir: Path, shots_file: str | None = None) -> tuple[Path, bool]:
    """(where the report goes, whether it is THE board's report). Only board/shots.json writes board/audit.json."""
    main = (Path(pdir) / "board/shots.json").resolve()
    sf = Path(shots_file).resolve() if shots_file else main
    if sf == main:
        return Path(pdir) / "board/audit.json", True
    return sf.with_name(sf.stem + ".audit.json"), False


def _sig(path: Path) -> str | None:
    """The audited board's content signature (core's util.file_sig when available)."""
    try:
        from ..util import file_sig
        return file_sig(path)
    except Exception:  # noqa: BLE001
        return None


def _after_board(out: Path, shots: Path, sig: str | None) -> None:
    """Keep the report's mtime after the board's, failing safe. Status and the approval gate treat 'shots.json newer
    than audit.json' as 'changed after the last audit'; a wall clock that jumps backwards (seen on the WSL dev machine)
    leaves shots.json with an mtime in the future, which would make a fresh audit look stale.
    The fix never moves the report into the future (review finding: a report stamped in the future let a LATER edit,
    saved at the real time, look audited). Instead, when the board's mtime is ahead of the report's, the board — still
    exactly the content this audit read (same signature) — is stamped just before now and the report at now; any later
    save of the board is then newer than the report, as it should be."""
    import os
    try:
        ms, mo = shots.stat().st_mtime, out.stat().st_mtime
        if mo > ms + 0.01:
            return
        if sig is None or _sig(shots) != sig:
            return                                 # the board changed while we audited: leave it looking stale
        now = time.time()
        os.utime(shots, (now - 0.05, now - 0.05))
        os.utime(out, (now, now))
    except OSError:
        pass


def run(pdir: Path, shots_file: str | None = None) -> dict:
    sig = _sig(Path(shots_file) if shots_file else pdir / "board/shots.json")    # what this audit reads
    rep = audit(pdir, shots_file)
    out, is_main = report_path(pdir, shots_file)
    rep["shots_sig"] = sig
    write_json(out, rep)
    if is_main:
        _after_board(out, pdir / "board/shots.json", sig)
    failed = [g for g in GATES if not rep["gates"][g]["ok"]]
    name = "board/audit.json" if is_main else out.name
    text = table(rep, report_name=name)
    if not is_main:
        text += (f"\nnote: this audited {rep['shots_file']}, not board/shots.json — the report is {out} and "
                 "board/audit.json (what the approval gate reads) is unchanged. To use this board, copy it to "
                 "board/shots.json and run `slop board audit` again.")
    res = {"ok": rep["ok"], "path": str(out), "main_board": is_main, "failed": failed,
           "gates": {g: ("PASS" if rep["gates"][g]["ok"] else "FAIL") for g in GATES},
           "stats": rep["stats"], "warnings": rep["warnings"], "clip_cmds": rep["clip_cmds"], "text": text}
    if failed:
        res["error"] = f"{len(failed)} gate(s) fail: {', '.join(failed)} (details in {out})"
    return res
