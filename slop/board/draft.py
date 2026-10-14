"""slop board draft — a DRAFT storyboard (board/shots.json) from the song analysis, for the lead to finish.

What the draft decides (the mechanical part of a storyboard; calibrated on ESCAPE VELOCITY's board, research 01 §9, §16.2):
  * Cuts. Shots tile [0, duration]. Every cut is a beat of analysis/beats.json (downbeats preferred), section boundaries
    are cuts, and a cut that would split a word starting < 0.028 s before it moves onto the word (EV rule, under a frame).
  * Pace per section kind, mean seconds per shot, measured on ESCAPE VELOCITY's cut (research 01 §16.2): intro / opening
    hook 1.33 · verse 1 + pre 1.62 · first chorus 2.69 (long sung windows) · later verses + pre 2.63 · middle choruses
    1.67 · final chorus 2.38 · bridge 2.25 · drop 1.58 · outro 4.40. Not measured (tuned): break 2.25, post 2.0,
    inst 2.0, other 1.85. A hook later in the song paces like a chorus. Median lands near one bar.
    Override per key with project.json "board": {"pace": {"verse": 1.8, "chorus_last": 2.2, ...}} (keys: intro, verse,
    pre, verse_late, chorus, chorus_mid, chorus_last, bridge, break, drop, post, inst, outro, other).
    Tier defaults (docs/40 §6.1): with no board.pace, a Quick project drafts at the Quick pace (≈ 4–7 s a shot) and a
    Studio project at the Studio pace (≈ 2.5–5 s); Director keeps EV's. board.pace may also name a preset ("quick",
    "studio", "director"), and `slop board draft --pace NAME` overrides both for one draft. A board.pace object on a
    Quick/Studio project fills the keys it leaves out from that tier's preset (not EV's), and its "chorus" also paces
    the middle and last choruses unless it names chorus_mid / chorus_last — so docs/40 §6.1's blocks give exactly the
    tier default. The draft prints the pace it used (stats.pace). Measured on the synthetic 3-minute song with 39
    lyric lines (tests/test_board_cmds.py song3, WSL): quick 41 shots, studio 58, director 85 (the docs/40 §6.1 blocks
    as written: the same 41 / 58).
  * Lyric lines. Cut positions prefer the beat a line starts on. When a second line would start inside a shot that an
    earlier line started, a cut is added on the beat of the later line's first word if both sides keep >= 0.6 s, or the
    next cut moves back onto that beat (never a section boundary); otherwise (dense lines) lines run across cuts. Every
    shot types every line whose words start inside it (mode held per line: subtitle in choruses, coverline in verses).
  * Tiers and clips. Sung clips on chorus/hook lines, motion clips on the intro and drops, plate3d (2.5D) elsewhere.
    Clip windows: 4-8 s, a sung window starts in a word gap (port of seedance.py gap_start, lead 0.3 s) and lists its
    exact words; a motion window starts on its shot (no pre-roll). Consecutive shots share one clip; runs are split
    into even windows. Windows are accepted in priority order (the intro's first window = the hook, the first chorus,
    the first drop's first window, the last chorus, other choruses, the rest of intros/drops) while planned seconds +
    a 60 % cover allowance on sung seconds (seedance.py `cost`) fit project budget.motion_s; a window that does not
    fit is shortened to its first shots when that fits.
  * Lead on screen. Sung shots and the first frame always have her; otherwise a greedy pattern keeps the running share
    at project.json board.lead_target (default 0.78, inside the 70-85 % band) with no stretch without her > 2 bars.
  * 2.5D treatments rotate through the five ANIMATION_GUIDE families (layer-separation, depth-as-image,
    diagram-over-image, stills-in-rhythm, reproduction), so no two consecutive plate3d shots share one and a chapter with
    five or more 2.5D shots uses all five ("a chapter uses at least five different ones"). "reproduction"
    (xerox/halftone) is a print-look texture: it is rotated in only when look.mode is "print" (the engine and
    docs/70 §11 ban it in the native and clean-grade looks), so in those looks a chapter reaches five only with a
    pure-motion (code-drawn) shot; project.json board.treatments [..] sets the rotation explicitly.
    (Integration fix: the build rotated it into the native look too, which the engine then flagged on every render.)
  * A chorus window is "sung" only when a word starts inside the shots it covers (the pre-roll before them does not
    count); otherwise it is a motion window (integration fix).
  * Clip plan -> gen. Every seedance[] window carries `cmd`, the exact `slop -p P clip new <first shot> --kind K --id cNN
    --t0 --t1 --song-t0 --duration` that creates it, so gen's clip id, window and needed span equal the board's (and the
    EDL and audit find it). gen drafts the prompt itself -- the short sung form for a sung window (it copies @Audio1;
    docs/60-clips.md §4.0), the timed screenplay for a motion window (real word/kick times) -- and the lead fills its
    [[slots]] with `slop clip set cNN --prompt-file F` -- so the board holds no clip prompt TODO.
  * Cost. stats.est_usd prices the planned windows (+ the cover allowance) with the project's models.video at 720p
    from the cached OpenRouter listing or gen's offline price table (no network call); null when the price is unknown.
  * Everything creative is a TODO marker for the lead: set, framing, action, plate prompts and one explaining graphic
    per lyric line. `slop board audit` fails until every TODO is written and every line has its graphic.

Changes from the source (intentional): EV/SP boards were written by agent panels or a per-project script; this is a
generic, deterministic first pass. Budget key `budget.motion_s` is new (default by tier: quick 24, studio 120,
director 200 s). Never overwrites: board/shots.json or an existing --out FILE needs --force (a .bak copy is kept); a
--force over a board the owner approved warns that the board gate is stale.
"""
from __future__ import annotations

import bisect
import shutil
import statistics
import time
from pathlib import Path

from ..config import SlopError, load_project
from .common import (SHOTS_REL, TIER_PACE, TODO, TREATMENTS, beat_period, ceil_int, clamp, graphic_hint, line_texts,
                     load_beats, load_words, motion_budget_s, pcmd, read_display, sections_with_kind, set_hint,
                     write_json)

# mean shot length per section, EV measured (research 01 §16.2); break/post/inst/other are tuned, not measured
PACE = {"intro": 1.33, "hook": 1.33, "verse": 1.62, "pre": 1.62, "verse_late": 2.63, "chorus": 2.69, "chorus_mid": 1.67,
        "chorus_last": 2.38, "bridge": 2.25, "drop": 1.58, "outro": 4.40, "break": 2.25, "post": 2.0, "inst": 2.0,
        "other": 1.85}
MIN_SHOT = 0.6            # s; EV's shortest shot was 0.44 s
DOWNBEAT_BONUS = 0.35     # x beat period: prefer downbeats when choosing a cut
LINE_BONUS = 0.30         # x beat period: prefer the beat a lyric line starts on
WORD_NUDGE = 0.028        # s; a cut may move onto a word that starts just before it (EV: "under one frame")
SUNG_MAX, MOTION_MAX, CLIP_MIN = 8, 8, 4
COVER_ALLOWANCE = 0.6     # seedance.py cost: +60 % of singing seconds for divergence covers
PACE_PRESETS = ("quick", "studio", "director")
PACE_LABEL = {"quick": "Quick", "studio": "Studio", "director": "Director (EV's measured cut)"}
TYPE_MODE = {"chorus": "subtitle", "hook": "subtitle", "drop": "subtitle", "outro": "subtitle", "intro": "subtitle",
             "verse": "coverline", "pre": "coverline", "bridge": "coverline", "break": "coverline", "post": "coverline",
             "inst": "subtitle", "other": "subtitle"}


# ------------------------------------------------------------------------------------------------ word helpers (ports)
def word_tokens(W: dict) -> list[dict]:
    """Aligned words with their lyric-sheet spelling when the line's token count matches (seedance.py tokens())."""
    lines = {int(l["line"]): l.get("text", "") for l in W.get("lines", []) if l.get("line") is not None}
    by_line: dict = {}
    for w in W["words"]:
        by_line.setdefault(w.get("line"), []).append(w)
    out = []
    for li, ws in by_line.items():
        tk = (lines.get(li) or "").split()
        for k, w in enumerate(ws):
            out.append({**w, "text": tk[k] if len(tk) == len(ws) else w.get("w", ""), "last": k == len(ws) - 1})
    return sorted(out, key=lambda w: w["t0"])


def words_in(tok: list[dict], t0: float, t1: float, lo: float = -.02) -> str:
    """The words sung in [t0, t1): starting in [t0 + lo, t1 - .08); lines joined as sentences (seedance.py words_in()).
    lo = -.02 for a raw window (EV); gen's clean vocal windows keep the words starting at t0 + .05 or later."""
    s = ""
    for w in (w for w in tok if t0 + lo <= w["t0"] < t1 - .08):
        txt = w["text"] or w.get("w", "")
        s += txt + (("" if txt and txt[-1] in ".,!?—-" else ".") if w["last"] else "") + " "
    return s.strip()


def gap_start(tok: list[dict], t: float, lead: float = .25, span: float = 1.6) -> float:
    """A window start in a word gap: the latest gap midpoint in [t - span, t - lead] (seedance.py gap_start())."""
    if not tok:
        return round(max(0.0, t - lead), 3)
    gaps = [(tok[i]["t1"], tok[i + 1]["t0"]) for i in range(len(tok) - 1) if tok[i + 1]["t0"] - tok[i]["t1"] >= .06]
    gaps = [(0.0, tok[0]["t0"])] + gaps
    mids = [min((a + b) / 2, b - .12) if b - a > .5 else (a + b) / 2 for a, b in gaps]
    ok = [m for m in mids if t - span <= m <= t - lead] or [m for m in mids if m <= t - lead] or [max(0.0, t - lead)]
    return round(max(0.0, max(ok)), 3)


# ------------------------------------------------------------------------------------------------ pace
def _preset(name: str) -> dict:
    n = str(name).strip().lower()
    if n in ("director", "ev", "default"):
        return dict(PACE)
    if n in TIER_PACE:
        return {**PACE, **TIER_PACE[n]}
    raise SlopError(f"pace '{name}': one of {', '.join(PACE_PRESETS)} (docs/40 §6.1), or a {{section: seconds}} object "
                    "in project.json board.pace")


def resolve_pace(proj: dict, override: str | None = None) -> tuple[dict, dict]:
    """(seconds per shot by section kind, {"name", "source", "values"}) — --pace beats project.json board.pace beats
    the tier's default (docs/40 §6.1: Quick and Studio presets; Director = EV's measured cut)."""
    cfg = proj.get("board") or {}
    tier = str(proj.get("tier") or "").lower()
    given = cfg.get("pace")
    if override:
        name = override.strip().lower()
        pace, src = _preset(name), f"--pace {name}"
    elif isinstance(given, str) and given.strip():
        name = given.strip().lower()
        pace, src = _preset(name), f"project.json board.pace \"{given}\""
    elif isinstance(given, dict):
        bad = {k: v for k, v in given.items() if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0}
        if bad:
            raise SlopError(f"project.json board.pace has values that are not positive seconds: {bad} — e.g. "
                            "{\"verse\": 2.5, \"chorus\": 3.5}")
        unknown = sorted(set(given) - set(PACE))
        if unknown:
            raise SlopError(f"project.json board.pace has unknown section keys {unknown}: use {', '.join(PACE)}")
        # The keys a block leaves out come from the TIER's preset (quick/studio), not EV's cut: docs/40 §6.1's blocks
        # omit chorus_mid/chorus_last, and EV's 1.67 s middle choruses inside a Quick board gave 55 shots instead of
        # the preset's 41 (review finding). A block's chorus also paces the middle and last choruses unless it names
        # them (the presets do the same). Director keeps EV's value for every key left out (EV's cut is its preset).
        base = {**PACE, **TIER_PACE[tier]} if tier in TIER_PACE else dict(PACE)
        vals = {k: float(v) for k, v in given.items()}
        if tier in TIER_PACE and "chorus" in vals:
            vals.setdefault("chorus_mid", vals["chorus"])
            vals.setdefault("chorus_last", vals["chorus"])
        pace = {**base, **vals}
        if tier in TIER_PACE and pace == base:
            name = tier
            src = (f"tier {tier} default (docs/40 §6.1; project.json board.pace "
                   + ("is empty)" if not given else "equals the preset)"))
        elif given:
            name = "custom"
            src = ("project.json board.pace (" + (f"the {tier} preset" if tier in TIER_PACE else "EV's pace")
                   + " for the keys it leaves out)")
        else:
            name, src = "director", "project.json board.pace {} (EV's measured cut)"
    elif given is not None:
        raise SlopError(f"project.json board.pace must be a preset name ({', '.join(PACE_PRESETS)}) or an object "
                        "{\"verse\": 2.5, …}, not " + type(given).__name__)
    elif tier in TIER_PACE:
        name, pace, src = tier, {**PACE, **TIER_PACE[tier]}, f"tier {tier} default (docs/40 §6.1)"
    else:
        name, pace = "director", dict(PACE)
        src = f"tier {tier or '(none)'} default: EV's measured cut" if tier else "EV's measured cut (no tier set)"
    return pace, {"name": name, "label": PACE_LABEL.get(name, name), "source": src,
                  "values": {k: pace[k] for k in ("intro", "verse", "verse_late", "pre", "chorus", "chorus_mid",
                                                  "chorus_last", "bridge", "drop", "outro") if k in pace}}


# ------------------------------------------------------------------------------------------------ cuts
def _pace(kind: str, ordinal: int, opening: bool, pace: dict, chorus_pos: str | None = None) -> float:
    """chorus_pos: "first" | "mid" | "last" among the song's (non-opening) choruses/hooks."""
    if opening and kind in ("intro", "hook", "other", "verse"):
        return pace.get("intro", PACE["intro"]) if kind != "verse" else pace.get("verse", PACE["verse"])
    if kind in ("chorus", "hook"):                        # a song hook later in the song is sung like a chorus
        key = {"mid": "chorus_mid", "last": "chorus_last"}.get(chorus_pos or "first", "chorus")
        return pace.get(key, PACE[key])
    if kind in ("verse", "pre") and ordinal > 1:
        return pace.get("verse_late", PACE["verse_late"])
    return pace.get(kind, PACE.get(kind, PACE["other"]))


def _nearest(arr: list[float], t: float) -> float:
    i = bisect.bisect_left(arr, t)
    cands = [arr[j] for j in (i - 1, i) if 0 <= j < len(arr)]
    return min(cands, key=lambda c: abs(c - t))


def plan_cuts(B: dict, W: dict, pace: dict) -> tuple[list[float], list[dict]]:
    """Cut times (internal boundaries, on beats) and the segments (sections after snapping) they fall in."""
    beats, dur = B["beats"], B["duration"]
    down = {round(d, 4) for d in B["downbeats"]}
    secs = sections_with_kind(B["sections"])
    # section boundaries on the nearest beat; a section shorter than a shot merges into its neighbour
    segs = [dict(secs[0], t0=0.0)]
    for s in secs[1:]:
        b = _nearest(beats, s["t0"])
        if b - segs[-1]["t0"] >= MIN_SHOT and dur - b >= MIN_SHOT:
            segs[-1]["t1"] = b
            segs.append(dict(s, t0=b))
    segs[-1]["t1"] = dur
    choruses = [i for i, s in enumerate(segs) if s["kind"] in ("chorus", "hook") and i]
    chorus_pos = {i: ("first" if n == 0 else "last" if n == len(choruses) - 1 else "mid") for n, i in enumerate(choruses)}
    line_beats = set()
    first_word = {}
    for w in W["words"]:
        first_word.setdefault(w.get("line"), w["t0"])
    for t in first_word.values():
        i = bisect.bisect_right(beats, t + .03) - 1
        if i >= 0:
            line_beats.add(round(beats[i], 4))
    cuts: list[float] = []
    for si, s in enumerate(segs):
        a, b = s["t0"], s["t1"]
        if si:
            cuts.append(a)
        target = _pace(s["kind"], s["ordinal"], si == 0, pace, chorus_pos.get(si))
        n = max(1, int(round((b - a) / target)))
        inner = [c for c in beats if a + MIN_SHOT <= c <= b - MIN_SHOT]
        last = a
        for k in range(1, n):
            ideal = a + k * (b - a) / n
            ok = [c for c in inner if c >= last + MIN_SHOT and c <= b - MIN_SHOT]
            if not ok:
                break
            def cost(c: float) -> float:
                bp = beat_period(beats, c)
                return abs(c - ideal) - DOWNBEAT_BONUS * bp * (round(c, 4) in down) - LINE_BONUS * bp * (round(c, 4) in line_beats)
            c = min(ok, key=cost)
            cuts.append(c)
            last = c
    cuts = sorted(set(cuts))
    fixed = {round(s["t0"], 6) for s in segs}            # section boundaries never move
    # a line that would start inside a shot an earlier line started gets its own shot when a beat allows: a cut on the
    # beat of its first word, or the next cut moved back onto that beat (dense lines run across cuts)
    for li, t in sorted(first_word.items(), key=lambda kv: kv[1]):
        bounds = [0.0] + cuts + [dur]
        j = max(0, bisect.bisect_right(bounds, t) - 1)
        s0, s1 = bounds[j], bounds[min(j + 1, len(bounds) - 1)]
        earlier = [u for l2, u in first_word.items() if l2 != li and s0 <= u < t]
        if not earlier:
            continue
        i = bisect.bisect_right(beats, t + .03) - 1
        if i < 0:
            continue
        c = beats[i]
        if not (c - s0 >= MIN_SHOT and max(earlier) < c):
            continue
        if s1 - c >= MIN_SHOT:
            cuts = sorted(set(cuts + [c]))
        elif s1 < dur and round(s1, 6) not in fixed:     # the following shot grows by < MIN_SHOT
            cuts = sorted(set([x for x in cuts if x != s1] + [c]))
    # a word starting just before a cut belongs to the next shot (move the cut onto the word, < 0.028 s)
    words = W["words"]
    out = []
    for c in cuts:
        for w in words:
            if w["t0"] < c < w["t1"] and c - w["t0"] <= WORD_NUDGE:
                c = round(w["t0"], 4)
                break
        out.append(round(c, 4))
    return sorted(set(out)), segs


# ------------------------------------------------------------------------------------------------ draft
def _todo_prompt(lead: bool) -> str:
    if lead:
        return (f"{TODO}: framing first, then {{lead}} (the canon), pose/action, the set, where she stands, the empty field "
                "left for type, the style tail; ends 'no text, no letters, no logos'")
    return (f"{TODO}: framing first (e.g. 'extreme wide shot of'), the place + one human-scale trace + light, the empty "
            "field left for type, the style tail; ends 'no text, no letters, no logos'")


def clip_cmd(pdir: Path, c: dict) -> str:
    """The exact `slop clip new` that creates a board clip window with the board's id, needed span and window."""
    shots = c.get("shots") or []
    need = c.get("needed") or [None, None]
    kind = c.get("kind") or ("sung" if c.get("sing") else "motion")
    parts = [f"clip new {shots[0] if shots else 'SHOT'}", f"--kind {kind}", f"--id {c.get('clip') or c.get('id')}"]
    if need[0] is not None and need[1] is not None:
        parts.append(f"--t0 {round(float(need[0]), 4)} --t1 {round(float(need[1]), 4)}")
    if c.get("song_t0") is not None:
        parts.append(f"--song-t0 {round(float(c['song_t0']), 4)}")
    if c.get("duration"):
        parts.append(f"--duration {int(c['duration'])}")
    if c.get("start"):
        parts.append(f"--start {c['start']}")
    return pcmd(pdir, " ".join(parts))


def clip_next(pdir: Path, cid: str) -> str:
    return (f"after the plates are picked: run cmd; gen drafts the prompt with [[slots]] (sung: the short sung form; "
            f"motion: the timed screenplay; docs/60-clips.md §4) -- the lead fills them (write the prompt to a file, "
            f"then {pcmd(pdir, f'clip set {cid} --prompt-file FILE')}), the owner reads it, then "
            f"{pcmd(pdir, f'clip lock {cid}')}")


class _Offline:
    """An OpenRouter stand-in that refuses network calls: prices come from the cached listing or gen's offline table."""

    def get(self, *a, **k):
        raise SlopError("offline")


def plan_cost(proj: dict, windows: list[dict], cover: float = COVER_ALLOWANCE, resolution: str = "720p") -> dict:
    """$ estimate for planned clip windows (+ the cover allowance on sung seconds); never calls the network."""
    from ..gen import models as M, video as V
    model = M.resolve(proj, "video", V.DEFAULT_MODEL, "video", offline=True)
    out: dict = {"model": model, "resolution": resolution, "est_usd": None, "est_usd_with_covers": None}
    if not windows:
        out["est_usd"] = out["est_usd_with_covers"] = 0.0
        return out
    try:
        from ..gen import models as M
    except ImportError:
        out["note"] = "gen module not installed: no price"
        return out
    try:
        rec = M.find("video", model, client=_Offline())
    except Exception:   # noqa: BLE001 - a price is a nicety, never a failure
        rec = None
    skus = (rec or {}).get("pricing_skus") or getattr(M, "FALLBACK", {}).get(model)
    if not skus:
        out["note"] = f"no offline price for {model}: `slop gen estimate --model {model} --duration 5`"
        return out
    usd = cov = 0.0
    for w in windows:
        try:
            c = M.video_cost(skus, float(w["duration"]), resolution, model=model, n_images=1)
        except Exception:   # noqa: BLE001
            c = None
        if c is None:
            out["note"] = f"{model} has no {resolution} price"
            return out
        usd += c
        if w.get("kind") == "sung":
            cov += cover * c
    out["est_usd"] = round(usd, 2)
    out["est_usd_with_covers"] = round(usd + cov, 2)
    return out


def build_draft(pdir: Path, pace_name: str | None = None) -> tuple[dict, dict]:
    proj = load_project(pdir)
    B = load_beats(pdir)
    W = load_words(pdir)
    cfg = proj.get("board") or {}
    pace, pace_info = resolve_pace(proj, pace_name)
    lead_target = float(cfg.get("lead_target", 0.78))
    budget = motion_budget_s(proj)
    cover = float(cfg.get("cover_allowance", COVER_ALLOWANCE))
    look_mode = (proj.get("look") or {}).get("mode", "native")
    api_plates = str(proj.get("tier") or "") == "quick"
    prompt_key = "img_prompt" if api_plates else "mj_prompt"
    dur = B["duration"]
    beats = B["beats"]

    cuts, segs = plan_cuts(B, W, pace)
    bounds = [0.0] + cuts + [dur]
    tok = word_tokens(W)
    texts = line_texts(pdir, W)

    def seg_of(t: float) -> int:
        return max(0, min(len(segs) - 1, bisect.bisect_right([s["t0"] for s in segs], t + 1e-6) - 1))

    shots = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        s = segs[seg_of(a)]
        shots.append({"id": f"s{i + 1:03d}", "t0": round(a, 4), "t1": round(b, 4), "section": s["name"],
                      "_seg": seg_of(a), "_kind": s["kind"]})
    # words per shot and lyric lines
    line_kind: dict = {}
    for w in W["words"]:
        line_kind.setdefault(w.get("line"), segs[seg_of(w["t0"])]["kind"])
    for sh in shots:
        ws = [w for w in W["words"] if sh["t0"] <= w["t0"] < sh["t1"]]
        sh["_words"] = ws
        sh["lines"] = sorted({w["line"] for w in ws if w.get("line") is not None})

    # ---- clip windows
    first_chorus = next((i for i, s in enumerate(segs) if s["kind"] in ("chorus", "hook") and i), None)
    last_chorus = next((i for i in range(len(segs) - 1, -1, -1) if segs[i]["kind"] in ("chorus", "hook") and i), None)
    first_drop = next((i for i, s in enumerate(segs) if s["kind"] == "drop"), None)

    def want(sh: dict) -> str | None:
        k, opening = sh["_kind"], sh["_seg"] == 0
        if k in ("chorus", "hook") and not opening:
            return "sung"                         # held notes between word onsets are sung too
        if k in ("intro", "drop") or (opening and k in ("hook", "other")):
            return "motion"
        return None

    windows = []
    i = 0
    while i < len(shots):
        kind = want(shots[i])
        if not kind:
            i += 1
            continue
        j = i
        while j + 1 < len(shots) and want(shots[j + 1]) == kind and shots[j + 1]["_seg"] == shots[i]["_seg"]:
            j += 1
        mx = SUNG_MAX if kind == "sung" else MOTION_MAX
        span = shots[j]["t1"] - shots[i]["t0"]
        limit = min(mx, max(CLIP_MIN, span / max(1, ceil_int(span / mx)) + 0.75))   # even windows: less waste
        k = i                                     # pack the run [i..j] into windows of <= 8 s
        nth = 0                                   # window number inside this run (only the first one is urgent)
        while k <= j:
            first = shots[k]
            t0w = gap_start(tok, first["t0"], lead=.3) if kind == "sung" else first["t0"]
            m = k
            while m + 1 <= j and shots[m + 1]["t1"] - t0w <= limit:
                m += 1
            if shots[m]["t1"] - t0w > mx:          # one shot longer than a clip: leave it to 2.5D
                k = m + 1
                continue
            d = int(clamp(ceil_int(shots[m]["t1"] - t0w), CLIP_MIN, mx))
            if kind == "motion" and t0w + d > dur:
                t0w = max(0.0, round(dur - d, 3))
            words = words_in(tok, t0w, t0w + d) if kind == "sung" else ""
            # an instrumental stretch of a chorus: she is there, not singing. Judged on the shots the edit uses, not
            # the pre-roll (integration fix: a window whose only word fell in the pre-roll before its shot was planned
            # as a sung clip whose lip sync the edit never shows)
            if kind == "sung" and not (words and words_in(tok, first["t0"], shots[m]["t1"])):
                kind_w, words = "motion", ""
            else:
                kind_w = kind
            seg = first["_seg"]
            pr = (0 if (kind == "motion" and seg == 0 and nth == 0) else 1 if (kind == "sung" and seg == first_chorus)
                  else 2 if (kind == "motion" and seg == first_drop and nth == 0)
                  else 3 if (kind == "sung" and seg == last_chorus) else 4 if kind == "sung" else 5)
            nth += 1
            if kind_w == "motion" and kind == "sung":
                t0w = first["t0"]                  # motion windows start on their shot (no pre-roll)
                d = int(clamp(ceil_int(shots[m]["t1"] - t0w), CLIP_MIN, MOTION_MAX))
            windows.append({"kind": kind_w, "shots": list(range(k, m + 1)), "song_t0": round(t0w, 3), "duration": d,
                            "words": words, "prio": pr})
            k = m + 1
        i = j + 1
    def shrunk(wdw: dict) -> list[dict]:
        """The window, then shorter versions of it (its first shots only), longest first."""
        out = [wdw]
        mx = SUNG_MAX if wdw["kind"] == "sung" else MOTION_MAX
        for m in range(len(wdw["shots"]) - 1, 0, -1):
            idx = wdw["shots"][:m]
            d = int(clamp(ceil_int(shots[idx[-1]]["t1"] - wdw["song_t0"]), CLIP_MIN, mx))
            if d < out[-1]["duration"]:
                w = wdw["song_t0"]
                ws = words_in(tok, w, w + d) if wdw["kind"] == "sung" else ""
                if wdw["kind"] == "sung" and not (ws and words_in(tok, shots[idx[0]]["t0"], shots[idx[-1]]["t1"])):
                    continue
                out.append({**wdw, "shots": idx, "duration": d, "words": ws})
        return out

    spent = 0.0
    accepted = []
    for wdw in sorted(windows, key=lambda w: (w["prio"], shots[w["shots"][0]]["t0"])):
        for w2 in shrunk(wdw):
            cost = w2["duration"] * (1 + cover if w2["kind"] == "sung" else 1)
            if spent + cost <= budget + 1e-9:
                spent += cost
                accepted.append(w2)
                break
    accepted.sort(key=lambda w: shots[w["shots"][0]]["t0"])
    seedance = []
    in_window: dict[int, dict] = {}
    for n, wdw in enumerate(accepted):
        cid = f"c{n + 1:02d}"
        wdw["clip"] = cid
        for si in wdw["shots"]:
            in_window[si] = wdw

    # ---- tiers, lead pattern, plates, treatments, type
    families = [str(f) for f in (cfg.get("treatments") or [])] or \
        [f for f in TREATMENTS if f != "reproduction" or look_mode == "print"]
    lead_s = tot = run_without = 0.0
    plate_of: dict[int, str] = {}
    n3d = 0
    for si, sh in enumerate(shots):
        d = sh["t1"] - sh["t0"]
        wdw = in_window.get(si)
        sh["motion_tier"] = wdw["kind"] if wdw else "plate3d"
        sh["clip"] = wdw["clip"] if wdw else None
        bar = 4 * beat_period(beats, sh["t0"])
        if wdw and wdw["kind"] == "motion" and si != wdw["shots"][0]:
            lead = shots[wdw["shots"][0]]["lead_on_screen"]          # one continuous take: keep her presence
        else:
            # a motion window decides once, for its whole span (one take), so the 2-bar rule sees all of it
            d_eff = (shots[wdw["shots"][-1]]["t1"] - sh["t0"]) if (wdw and wdw["kind"] == "motion") else d
            must = sh["motion_tier"] == "sung" or si == 0 or run_without + d_eff > 2 * bar
            lead = must or (lead_s / (tot + d_eff)) < lead_target
        sh["lead_on_screen"] = bool(lead)
        tot += d
        lead_s += d if lead else 0.0
        run_without = 0.0 if lead else run_without + d
        plate_of[si] = plate_of[wdw["shots"][0]] if (wdw and si != wdw["shots"][0]) else f"p{si + 1:03d}"
        sh["plate"] = plate_of[si]
        if sh["motion_tier"] == "plate3d":
            sh["treatment"] = families[n3d % len(families)]
            n3d += 1
        else:
            sh["treatment"] = None
    for wdw in accepted:
        ss = [shots[i] for i in wdw["shots"]]
        c = {"clip": wdw["clip"], "kind": wdw["kind"], "sing": wdw["kind"] == "sung",
             "shots": [s["id"] for s in ss], "song_t0": wdw["song_t0"], "duration": wdw["duration"],
             "needed": [ss[0]["t0"], ss[-1]["t1"]], "words": wdw["words"], "plate": ss[0]["plate"]}
        c["cmd"] = clip_cmd(pdir, c)
        c["next"] = clip_next(pdir, wdw["clip"])
        seedance.append(c)

    out_shots = []
    started: set = set()
    for sh in shots:
        types = [{"line": li, "mode": TYPE_MODE.get(line_kind.get(li, "other"), "subtitle"), "text": texts.get(li, ""),
                  "placement": ""} for li in sh["lines"]]
        new_lines = [li for li in sh["lines"] if li not in started]
        started.update(new_lines)
        notes = "; ".join(f"{TODO}: one explaining graphic for line {li} (devices[], enters on the word that names it)"
                          for li in new_lines)
        rec = {"id": sh["id"], "t0": sh["t0"], "t1": sh["t1"], "section": sh["section"], "lines": sh["lines"],
               "set": TODO, "lead_on_screen": sh["lead_on_screen"], "framing": TODO,
               "action": f"{TODO}: what happens, concrete, one sentence", "camera": "",
               "motion_tier": sh["motion_tier"], "plate": sh["plate"], "clip": sh["clip"],
               prompt_key: _todo_prompt(sh["lead_on_screen"]) if sh["plate"] == f"p{int(sh['id'][1:]):03d}" else "",
               "type": types, "devices": [], "treatment": sh["treatment"], "transition_in": "cut", "chrome": "",
               "accent": (proj.get("look") or {}).get("accent", ""), "notes": notes}
        out_shots.append(rec)
    plates = []
    for key in dict.fromkeys(plate_of.values()):
        used = [shots[i]["id"] for i, k in plate_of.items() if k == key]
        lead = any(shots[i]["lead_on_screen"] for i, k in plate_of.items() if k == key)
        aspect = "16:9"
        size = proj.get("size") or [1920, 1080]
        if size and size[0] < size[1]:
            aspect = "9:16"
        # the prompt lives on the shot that owns the plate (one place for the lead to write it); `slop plates book`
        # also accepts EV-style boards whose prompts sit here in plates[]
        plates.append({"plate": key, "lead": lead, "aspect": aspect, "used_by": used})
    chapters = [{"id": f"C{i + 1}", "name": s["name"], "t0": round(s["t0"], 4), "t1": round(s["t1"], 4),
                 "sections": s["name"]} for i, s in enumerate(segs)]
    S = {"version": 1, "draft": True, "generator": "slop board draft", "duration": round(dur, 4), "chapters": chapters,
         "shots": out_shots, "seedance": seedance, "plates": plates}

    durs = [s["t1"] - s["t0"] for s in out_shots]
    by_kind: dict = {}
    for sh, d in zip(shots, durs):
        by_kind.setdefault(sh["_kind"], []).append(d)
    sung_s = sum(w["duration"] for w in accepted if w["kind"] == "sung")
    motion_s = sum(w["duration"] for w in accepted if w["kind"] == "motion")
    bar_med = 4 * statistics.median(b - a for a, b in zip(beats, beats[1:]))
    cost = plan_cost(proj, accepted, cover)
    stats = {"shots": len(out_shots), "duration": round(dur, 2), "median_s": round(statistics.median(durs), 3),
             "mean_s": round(statistics.mean(durs), 3), "bar_s": round(bar_med, 3),
             "pace_by_section": {k: round(statistics.mean(v), 2) for k, v in by_kind.items()},
             "lead_share": round(lead_s / max(tot, 1e-9), 3), "clips": len(seedance), "sung_clip_s": sung_s,
             "motion_clip_s": motion_s, "planned_clip_s": sung_s + motion_s,
             "cover_allowance_s": round(cover * sung_s, 1), "budget_motion_s": budget,
             "est_usd": cost["est_usd"], "est_usd_with_covers": cost["est_usd_with_covers"], "price": cost,
             "plates": len(plates), "lines": len({w.get('line') for w in W['words']}),
             "words": len(W["words"]), "display_txt": bool(read_display(pdir)), "pace": pace_info}
    return S, stats


def _next_steps(pdir: Path, S: dict) -> str:
    shots = S.get("shots") or [{}]
    first = shots[0].get("id", "s001")
    key = "img_prompt" if any("img_prompt" in s for s in S.get("shots") or []) else "mj_prompt"
    typed = next(((s["id"], s["lines"][0]) for s in shots if s.get("lines")), None)
    dev = graphic_hint(pdir, typed[0], typed[1], None) if typed else \
        pcmd(pdir, "board device add SHOT --kind callout --line N")
    return ("next: the lead writes every TODO (each <…> below is a marker to replace with the real text; the commands "
            "refuse it as it stands) — one shot: `" + set_hint(pdir, first, ["set", "framing", "action", key])
            + "`; many shots at once from a TSV or JSONL file: `" + pcmd(pdir, "board fill FILE") + "`; one explaining "
            "graphic per lyric line: `" + dev + "` (`" + pcmd(pdir, "board device kinds") + "` lists the devices); then `"
            + pcmd(pdir, "board audit") + "`. Each seedance[] clip has its `cmd` for after the plates are picked.")


def lead_note(pdir: Path, S: dict, proj: dict) -> str | None:
    """When the draft's lead share is above the 70–85 % band (long shots at the Quick/Studio pace are each longer than
    2 bars, so the draft keeps her in nearly every one): which insert to turn off, with the command and the result."""
    shots = S.get("shots") or []
    tot = sum(s["t1"] - s["t0"] for s in shots) or 1.0
    lead = sum(s["t1"] - s["t0"] for s in shots if s.get("lead_on_screen"))
    share = lead / tot
    if share <= 0.85:
        return None
    cfg = proj.get("board") or {}
    lo, target = float(cfg.get("lead_min", 0.70)), float(cfg.get("lead_target", 0.78))
    cands = [s for i, s in enumerate(shots) if i and s.get("lead_on_screen") and s.get("motion_tier") == "plate3d"
             and lo + .01 <= (lead - (s["t1"] - s["t0"])) / tot]
    msg = (f"note: lead on screen {share * 100:.0f}% is above the 70–85 % band (the audit warns, it does not fail): at "
           "this pace most shots are longer than 2 bars, and the draft keeps her in every stretch that long.")
    if not cands:
        return msg
    best = min(cands, key=lambda s: abs((lead - (s["t1"] - s["t0"])) / tot - target))
    after = (lead - (best["t1"] - best["t0"])) / tot
    return (msg + f" To make room for an insert (a prop, the place): `{pcmd(pdir, 'board set ' + best['id'] + ' --no-lead')}`"
            f" (→ {after * 100:.0f}%; keep it ≥ {lo * 100:.0f}%).")


def _pace_line(st: dict) -> str:
    p = st.get("pace") or {}
    v = p.get("values") or {}
    pv = " · ".join(f"{k} {v[k]:g}" for k in ("intro", "verse", "chorus", "bridge", "outro") if k in v)
    other = [n for n in PACE_PRESETS if n != p.get("name")]
    return (f"pace: {p.get('label', '?')} — {p.get('source', '')}; seconds a shot: {pv}; mean {st['mean_s']} s. "
            f"Too many or too few shots for the tier? re-draft with --force --pace {'|'.join(other)} (docs/40 §6.1).")


def run(pdir: Path, force: bool = False, out: str | None = None, pace: str | None = None) -> dict:
    S, stats = build_draft(pdir, pace)
    target = (Path(out) if Path(out).is_absolute() else Path(pdir) / out) if out else pdir / SHOTS_REL   # relative: in the project
    backup = None
    if target.exists():
        if not force:
            raise SlopError(f"{target} already exists (the lead may have written it). Re-run with --force to replace it "
                            "(the old file is kept as a .bak copy), or with --out NEWFILE to write the draft elsewhere.")
        backup = target.with_name(f"{target.stem}.{time.strftime('%Y%m%d-%H%M%S')}.bak.json")
        shutil.copy2(target, backup)
    write_json(target, S)
    st = stats
    text = (f"wrote {target.name}: {st['shots']} shots over {st['duration']} s · median {st['median_s']} s "
            f"(1 bar = {st['bar_s']} s) · lead on screen {st['lead_share'] * 100:.0f}% · {st['clips']} clips, "
            f"{st['planned_clip_s']} s planned (+{st['cover_allowance_s']} s cover allowance) of a {st['budget_motion_s']:g} s "
            "budget" + (f" ≈ ${st['est_usd']:.2f} (≈ ${st['est_usd_with_covers']:.2f} with covers; "
                        f"{st['price']['model']} {st['price']['resolution']})" if st["est_usd"] is not None else
                        (f" (price unknown: {st['price'].get('note', '')})" if st["clips"] else ""))
            + f" · {st['plates']} plates.\n" + _pace_line(st) + "\n" + _next_steps(pdir, S))
    ln = lead_note(pdir, S, load_project(pdir))
    if ln:
        text += "\n" + ln
        stats["lead_note"] = ln
    if not st["words"]:
        text += "\nwarning: analysis/words.json has no aligned words — the board has no lyric types (run `slop analyze`)."
    stale = None
    if backup is not None and target.resolve() == (Path(pdir) / SHOTS_REL).resolve():
        from .common import board_gate_stale
        stale = board_gate_stale(pdir)             # a re-draft replaced the board the owner approved
        if stale:
            text += f"\nwarning: {stale}"
    return {"path": str(target), "backup": str(backup) if backup else None, "stats": stats,
            "gate_stale": bool(stale), "text": text}
