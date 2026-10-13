"""Shared helpers for `slop.board` and `slop.edit`: project files, JSON I/O, analysis loading, tiers, fonts.

Nothing here spends money or needs a GPU. Heavy imports (Pillow) happen inside functions.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterator

from ..config import SlopError, engine_dir, load_project

SHOTS_REL = "board/shots.json"
TODO = "TODO"
TIERS = ("still", "plate3d", "motion", "sung")
FRAMINGS = ("ECU", "CU", "MCU", "MS", "MWS", "WS", "FS", "EWS", "OTS")
WIDE_FRAMINGS = ("FS", "WS", "MWS", "EWS")
# 2.5D treatment families (ANIMATION_GUIDE; research 11-gap-1 §5.3). "reproduction" is a print-look family.
TREATMENTS = ("layer-separation", "depth-as-image", "diagram-over-image", "stills-in-rhythm", "reproduction")
TREATMENT_ALIASES = {"ls": "layer-separation", "di": "depth-as-image", "dg": "diagram-over-image",
                     "sr": "stills-in-rhythm", "rp": "reproduction", "pm": "pure-motion",
                     "motion": "pure-motion"}       # the engine's name for a code-drawn shot (docs/70 §11)
CODE_FAMILIES = ("pure-motion", "motion-design", "code")
# The engine's treatment vocabulary is read from engine/src/devices/treat.js itself (slop/board/vocab.py parses its
# ALIAS/FAMS/CODES tables and ports its parse() rules), so consecutive shots are compared the way the renderer draws
# them whichever vocabulary the board was written in ("layers" after "layer-separation" is a repeat; "push" after
# "rack" is not; "LS (rack)" is rack; "motion"/"none"/"code" draw a code frame). The table below is only the fallback
# when the engine file cannot be read.
ENGINE_TREATMENT = {
    "ls": "layers", "layer-separation": "layers", "layer": "layers", "slices": "layers", "parallax": "push",
    "plate3d": "push", "default": "push", "clip": "push", "di": "relight", "depth-as-image": "relight",
    "depth": "relight", "contour": "contours", "topo": "contours", "topography": "contours", "pointcloud": "scan",
    "point-cloud": "scan", "lidar": "scan", "rp": "xerox", "reproduction": "xerox", "halftone": "xerox",
    "photocopy": "xerox", "thermal": "xerox", "mosaic": "xerox", "enhance": "xerox", "1-bit": "xerox", "sr": "stills",
    "stills-in-rhythm": "stills", "crops": "stills", "stutter": "stills", "dg": "diagram",
    "diagram-over-image": "diagram", "measure": "diagram", "pm": "motion", "pure-motion": "motion",
    "motion-design": "motion", "pure-motion-design": "motion", "code": "motion", "none": "motion", "oc": "occlusion",
    "occ": "occlusion", "rotoscope": "occlusion", "rack-focus": "rack", "focus": "rack"}
ENGINE_FAMILIES = ("push", "layers", "rack", "relight", "contours", "scan", "stills", "xerox", "diagram", "motion",
                   "occlusion")
# default motion/sung clip seconds per tier when project.json has no budget.motion_s (EV planned <= 200 s)
MOTION_BUDGET_BY_TIER = {"quick": 24.0, "studio": 120.0, "director": 200.0}
# The draft's pace per tier when project.json has no board.pace (docs/40 §6.1): seconds per shot by section kind.
# Director = EV's measured cut (draft.PACE); Quick ≈ 4–7 s a shot; Studio ≈ 2.5–5 s a shot. The preset's chorus value
# also paces the middle and last choruses (chorus_mid / chorus_last): EV's 1.67 s middle choruses inside a Quick board
# would double its chorus shots (measured: quick 54 shots instead of 40 on the synthetic 3-minute song).
TIER_PACE = {
    "quick": {"intro": 4, "hook": 4, "verse": 5, "verse_late": 5, "pre": 5, "chorus": 6, "chorus_mid": 6,
              "chorus_last": 6, "post": 5, "bridge": 5, "break": 5, "drop": 4, "inst": 5, "outro": 7, "other": 5},
    "studio": {"intro": 2.5, "hook": 2.5, "verse": 2.5, "verse_late": 3, "pre": 2.5, "chorus": 3.5, "chorus_mid": 3.5,
               "chorus_last": 3.5, "post": 3, "bridge": 3, "break": 3, "drop": 2.5, "inst": 3, "outro": 5, "other": 3},
}


# ------------------------------------------------------------------------------------------------ files
def read_json(path: Path, default: Any = ..., hint: str = "") -> Any:
    path = Path(path)
    if not path.is_file():
        if default is not ...:
            return default
        raise SlopError(f"missing {path}" + (f" — {hint}" if hint else ""))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SlopError(f"{path} is not valid JSON ({e}); fix the file by hand or re-create it") from e


def write_text(path: Path, text: str) -> Path:
    """Atomic write (renders in flight may be reading engine assets)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_json(path: Path, data: Any, indent: int | None = 1) -> Path:
    return write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")


def rel(pdir: Path, path: Path | str) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(Path(pdir).resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def resolve_file(pdir: Path, f: str | None) -> Path | None:
    if not f:
        return None
    p = Path(f)
    return p if p.is_absolute() else Path(pdir) / p


def project(pdir: Path) -> dict:
    return load_project(pdir)


# ------------------------------------------------------------------------------------------------ board
def shots_path(pdir: Path, path: str | None = None) -> Path:
    return Path(path) if path else Path(pdir) / SHOTS_REL


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def shots_problems(S: dict) -> list[str]:
    """Structural problems a hand edit can leave in a storyboard (each names the shot and field to fix).
    Reversed/empty shots (t1 <= t0) are not listed here: `slop board audit` reports them in its tile gate."""
    probs: list[str] = []
    for i, sh in enumerate(S.get("shots") or []):
        if not isinstance(sh, dict):
            probs.append(f"shots[{i}] is {type(sh).__name__}, not an object like {{\"id\": \"s014\", \"t0\": 12.3, \"t1\": 14.1}}")
            continue
        sid = sh.get("id")
        ok_id = isinstance(sid, str) and bool(sid.strip())
        name = sid if ok_id else f"shots[{i}]"
        if not ok_id:
            probs.append(f"{name}: id is {'missing' if sid is None else repr(sid)} — every shot needs a text id like \"s014\"")
        for k in ("t0", "t1"):
            if sh.get(k) is None:
                probs.append(f"{name}: {k} is missing — every shot needs numeric t0 and t1 (song seconds, on beats)")
            elif not _is_num(sh[k]):
                probs.append(f"{name}: {k} is {sh[k]!r}, not a number — write seconds as a bare number, e.g. 12.345")
    for top in ("chapters", "seedance", "plates"):
        v = S.get(top)
        if v is None:
            continue
        if not isinstance(v, list):
            probs.append(f"'{top}' must be a list [...], not {type(v).__name__}")
            continue
        for i, x in enumerate(v):
            if not isinstance(x, dict):
                probs.append(f"{top}[{i}] is {type(x).__name__}, not an object {{...}}")
    return probs


def load_shots(pdir: Path, path: str | None = None) -> dict:
    """The storyboard, validated: a shot without a text id or numeric t0/t1 is a SlopError that names it (a hand-edit
    mistake must never surface as a traceback)."""
    p = shots_path(pdir, path)
    S = read_json(p, hint="write a storyboard first: `slop board draft` (then the lead fills the TODO fields)")
    if not isinstance(S, dict) or not isinstance(S.get("shots"), list):
        raise SlopError(f"{p} has no 'shots' list (expected the storyboard format {{version,duration,chapters,shots,seedance,plates}})")
    probs = shots_problems(S)
    if probs:
        more = f"\n  … {len(probs) - 20} more" if len(probs) > 20 else ""
        raise SlopError(f"{p} has {len(probs)} problem(s) — fix them in the file, then re-run the command:\n  - "
                        + "\n  - ".join(probs[:20]) + more)
    S.setdefault("chapters", [])
    S.setdefault("seedance", [])
    S.setdefault("plates", [])
    return S


def project_ref(pdir: Path) -> str:
    """What to pass to --project: the bare name under $SLOP_PROJECTS, else the full path (shell-quoted)."""
    try:
        from ..core_cli import project_ref as core_ref
        return core_ref(Path(pdir))
    except ImportError:
        import shlex
        from ..config import projects_root
        try:
            if Path(pdir).parent.resolve() == projects_root().resolve():
                return Path(pdir).name
        except OSError:
            pass
        return shlex.quote(str(pdir))


def pcmd(pdir: Path, rest: str) -> str:
    """A command line with the project spelled out, runnable verbatim from any directory."""
    return f"slop -p {project_ref(pdir)} {rest}"


# ------------------------------------------------------------------------------------------------ placeholders
# Next-step hints print the part the lead must write as an explicit <marker> ("--set \"<the place>\""), and every
# validator (board set / fill, device add, the audit's todo and devices gates) refuses a value that is still one: a
# hint pasted word for word fails instead of filling the board with "…" (review finding: a board of "…" passed every
# gate). A value that is only an ellipsis, contains a <…> marker, or is exactly one of the hint words below counts.
PLACEHOLDER_WORDS = {"WORD", "FAMILY", "TEXT", "PLACE", "ACTION", "PROMPT", "KIND", "VALUE"}
_PH_MARK = re.compile(r"<[^<>\n]{1,80}>")
_PH_DOTS = re.compile(r"[\s.…]+")


def placeholder(v, words: bool = True) -> str | None:
    """Why `v` (a string) is still a placeholder, else None. words=False skips the bare hint words (on-screen device
    text such as a row "TEXT" or "VALUE" can be real)."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    if TODO in s:
        return f"still contains the {TODO} marker"
    if _PH_DOTS.fullmatch(s):
        return f"'{s}' is a placeholder (only dots)"
    m = _PH_MARK.search(s)
    if m:
        return f"'{m.group(0)}' is a placeholder from a hint (replace the whole <…> part)"
    if words and s in PLACEHOLDER_WORDS:
        return f"'{s}' is a placeholder word from a hint"
    return None


# the flag a next-step hint prints for a field the lead still has to write (every value is refused as it stands)
FIELD_HINT = {"set": '--set "<the place, concrete>"', "framing": '--framing "<' + "|".join(FRAMINGS) + '>"',
              "action": '--action "<what happens, one sentence>"',
              "img_prompt": '--img-prompt "<the plate prompt: framing words first, then the place>"',
              "mj_prompt": '--mj-prompt "<the plate prompt: framing words first, then the place>"',
              "camera": '--camera "<push|pull|pan left|static|handheld>"',
              "notes": '--notes "<the note without its TODO, or empty>"', "treatment": '--treatment "<family>"'}


def set_hint(pdir: Path, sid: str, fields) -> str:
    """`slop -p P board set SHOT --set "<…>" …` for the fields still to write (the markers are refused as they are)."""
    flags = [FIELD_HINT.get(f, f'--{f.replace("_", "-")} "<{f.replace("_", " ")}>"') for f in fields]
    return pcmd(pdir, f"board set {sid} " + " ".join(dict.fromkeys(flags)))


def graphic_hint(pdir: Path, sid: str, line: int, word: str | None) -> str:
    """The command that adds line N's explaining graphic; the rows are a <marker> the device check refuses."""
    import shlex
    w = shlex.quote(word) if word else '"<the word that names it>"'
    return pcmd(pdir, f"board device add {sid} --kind callout --line {line} --anchor uv:0.62,0.42 --param word={w} "
                      "--param 'rows=[\"<what line " + str(line) + " means>\"]'")


def save_shots(pdir: Path, S: dict, path: str | None = None) -> Path:
    return write_json(shots_path(pdir, path), S)


def board_gate_stale(pdir: Path) -> str | None:
    """After a command changed board/shots.json: one warning line when the owner had approved the board (G4) and that
    approval no longer covers the board as it is now (core's gate_state; an approval that did not record what it
    covered never covers a change), else None."""
    try:
        proj = load_project(pdir)
    except SlopError:
        return None
    metas = proj.get("gates_meta") if isinstance(proj.get("gates_meta"), dict) else {}
    meta = metas.get("board_approved") if isinstance(metas.get("board_approved"), dict) else None
    if not (proj.get("gates") or {}).get("board_approved") and meta is None:
        return None
    at = (meta or {}).get("at")
    try:
        from ..core_cli import gate_state
        stale = meta is None or not gate_state(Path(pdir), proj, "board_approved")["current"]
    except ImportError:                                # core not loaded: compare the recorded signature ourselves
        from ..util import file_sig
        rec = ((meta or {}).get("covers") or {}).get(SHOTS_REL)
        stale = meta is None or rec != file_sig(Path(pdir) / SHOTS_REL)
    if not stale:
        return None
    return (f"the board changed after the owner approved it{f' ({at})' if at else ''}: the board gate is now stale — "
            f"show the owner the change (`{pcmd(pdir, 'board sheet')}`) and, after their yes, re-approve with their "
            f"words: `{pcmd(pdir, 'board approve')} --note '<their words>'`")


def shot_clips(sh: dict) -> list[str]:
    """Clip ids a shot may show, primary first (contract `clip`; EV/SP `seedance_clip` and `clips`)."""
    out: list[str] = []
    for c in (sh.get("clips") or []) + [sh.get("clip"), sh.get("seedance_clip")]:
        if c and c not in out:
            out.append(c)
    return out


def clip_kinds(pdir: Path | None, S: dict) -> dict[str, str]:
    """clip id -> "sung" | "motion" from the board's clip list and clips/<clip>.json files."""
    kinds: dict[str, str] = {}
    for c in S.get("seedance", []):
        cid = c.get("clip") or c.get("id")
        if cid:
            kinds[cid] = "sung" if (c.get("kind") == "sung" or (c.get("kind") is None and c.get("sing"))) else "motion"
    if pdir is not None and (Path(pdir) / "clips").is_dir():
        for f in (Path(pdir) / "clips").glob("*.json"):
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(c, dict):
                kinds.setdefault(c.get("id") or f.stem, "sung" if (c.get("kind") == "sung" or c.get("sing")) else "motion")
    return kinds


def sung_shot_ids(S: dict, kinds: dict[str, str]) -> set[str]:
    """The shots that sing on screen: motion tier "sung", or a motion shot whose primary clip is sung (the edit plays
    it lip-synced; docs/40 §8.1). A plate shot (still/plate3d) shows its plate whatever clip ids it still lists."""
    out: set[str] = set()
    for sh in S.get("shots") or []:
        cl = shot_clips(sh)
        t = shot_tier(sh, kinds)
        if t == "sung" or (t == "motion" and cl and kinds.get(cl[0]) == "sung"):
            out.add(sh.get("id"))
    return out


# ------------------------------------------------------------------------------------------------ sung plates: the mouth
# The Studio run (2026-10-02): a microphone at her mouth on a sung plate held that clip to 26 % in sync, and image
# models add a microphone to "singing" prompts on their own. A sung shot's plate is the lip-sync start frame, so its
# prompt always says the mouth is clear (plates book adds it) and the audit warns when the prompt puts something there.
_MOUTH_NEG = re.compile(r"\b(?:no|not|never|without|nothing|none|free of|away from|clear of)\b", re.I)
_MOUTH_BLOCK = (
    re.compile(r"\b(?:(?:hand-?held|headset|wireless|vintage|studio|stage|broadcast|retro|chrome|silver|black)\s+)?"
               r"(?:mic|mics|microphones?|megaphone|bullhorn)\b", re.I),
    re.compile(r"\bhand-to-mouth\b|\b(?:hands?|fingers?|fingertips?|thumbs?|fists?|palms?|knuckles?)\b"
               r"(?:\s+[\w'-]+){0,3}?\s+(?:to|at|near|over|on|"
               r"against|across|around|covering|in front of|by)\s+(?:her|his|their|the)\s+(?:mouth|lips)\b", re.I),
    re.compile(r"\b(?:covering|covers|covered|hiding|hides|hidden|blocking|blocks|obscuring|obscures|over|across|"
               r"in front of)\s+(?:her|his|their|the)\s+(?:mouth|lips)\b", re.I),
)


_HEADSET = re.compile(r"\bheadset\b", re.I)


def mouth_clause(proj: dict, prompt: str = "", mj: bool = False) -> str:
    """The line every sung plate prompt carries (the lead's pronoun from project.json lead.pronoun, default she).

    API models follow a literal negative, so they get the objects named: "(no microphone, hand or hair)". Midjourney
    draws what a prompt names, negated or not (its docs: words like "no" are not understood), so mj=True gives the
    positive part only. A prompt whose canon carries a headset microphone (docs/50 §5: "a thin headset microphone at her
    cheek") is not told "no microphone" — that would drop a canon prop — but where it stays."""
    pron = str((proj.get("lead") or {}).get("pronoun") or "she").strip().lower()
    poss = {"he": "his", "they": "their", "it": "its"}.get(pron, "her")
    base = f"{poss} mouth fully visible, nothing in front of {poss} mouth"
    if mj:
        return base
    if _HEADSET.search(prompt or ""):
        return f"{base} (the headset microphone at {poss} cheek, clear of {poss} lips; no hand or hair)"
    return f"{base} (no microphone, hand or hair)"


def mouth_blockers(text: str) -> list[str]:
    """What a prompt puts in front of the mouth: a microphone (a headset kept 'at her cheek' aside), a hand or
    fingers at the mouth or lips, something over or covering it. Negated mentions ("no microphone", "nothing in front
    of her mouth", the mouth line itself) do not count."""
    found: list[str] = []
    for clause in re.split(r"[,;.()\[\]\n]|\s-\s", str(text or "")):
        for rx in _MOUTH_BLOCK:
            for m in rx.finditer(clause):
                if _MOUTH_NEG.search(clause[max(0, m.start() - 25):m.start()]):
                    continue
                hit = m.group(0).strip().lower()
                if "headset" in hit and "cheek" in clause.lower():
                    continue                       # a canon headset kept at her cheek stays clear of the lips
                if hit not in found:
                    found.append(hit)
    return found


def is_code(sh: dict) -> bool:
    """A code-drawn shot (pure motion design): needs no plate or clip. True when the engine draws its treatment as its
    `motion` family (pure-motion, motion-design, code, PM, motion, none — engine/src/devices/treat.js)."""
    if sh.get("code") or sh.get("motion_tier") == "code":
        return True
    if treatment_family(sh) in CODE_FAMILIES:
        return True
    return engine_treatment(sh) == "motion"


def shot_tier(sh: dict, kinds: dict[str, str] | None = None) -> str:
    """Contract tier still|plate3d|motion|sung; legacy EV/SP tiers (seedance/plate25d/code) are mapped."""
    t = (sh.get("motion_tier") or "").lower()
    if t in TIERS:
        return t
    if t == "plate25d":
        return "plate3d"
    if t == "code":
        return "still"
    if t == "seedance":
        clips = shot_clips(sh)
        if kinds and clips and kinds.get(clips[0]) == "sung":
            return "sung"
        return "sung" if sh.get("sung") else "motion"
    return "plate3d" if sh.get("plate") else "still"


def treatment_family(sh: dict) -> str | None:
    t = sh.get("treatment")
    if isinstance(t, dict):
        t = t.get("family")
    if not t or not isinstance(t, str):
        return None
    t = t.strip().lower()
    return TREATMENT_ALIASES.get(t, t)


def engine_treatment(sh: dict) -> str | None:
    """The engine family a shot's treatment draws as (treat.js parse(): names, aliases, codes, prose), for repeat
    checks across vocabularies; None when the shot asks for none (the engine picks one). A name the engine does not
    know draws a plain push, so it compares as "push"."""
    t = sh.get("treatment")
    if isinstance(t, dict):
        t = t.get("family") or t.get("name") or t.get("kind")
    if not t or not isinstance(t, str):
        return None
    try:
        from .vocab import treatment_parse
        fam, _unknown = treatment_parse(t)
        return fam
    except Exception:  # noqa: BLE001 - the engine file is unreadable: the fallback table
        t = t.strip().lower()
        return t if t in ENGINE_FAMILIES else ENGINE_TREATMENT.get(t, "push")


def treatment_unknown(sh: dict) -> bool:
    """True when the engine does not know the shot's treatment name (it would draw a push and warn)."""
    t = sh.get("treatment")
    if isinstance(t, dict):
        t = t.get("family") or t.get("name") or t.get("kind")
    if not t or not isinstance(t, str):
        return False
    try:
        from .vocab import treatment_parse
        return treatment_parse(t)[1]
    except Exception:  # noqa: BLE001
        return False


def shot_plate(sh: dict, S: dict | None = None) -> str | None:
    if sh.get("plate"):
        return sh["plate"]
    if S:
        for p in S.get("plates", []):
            if sh.get("id") in (p.get("used_by") or []):
                return p.get("plate")
    return None


def framing_of(sh: dict) -> str:
    f = (sh.get("framing") or "").strip().upper()
    return f if f in FRAMINGS else ""


# ------------------------------------------------------------------------------------------------ analysis
def load_beats(pdir: Path) -> dict:
    B = read_json(Path(pdir) / "analysis/beats.json",
                  hint="run `slop analyze` first (it writes analysis/beats.json, words.json, hits.json)")
    beats = sorted(float(b) for b in B.get("beats", []))
    if len(beats) < 2:
        raise SlopError("analysis/beats.json has fewer than 2 beats — re-run `slop analyze` (is the song silent or very short?)")
    B["beats"] = beats
    B["downbeats"] = sorted(float(b) for b in B.get("downbeats", []))
    dur = B.get("duration")
    B["duration"] = float(dur) if dur else beats[-1] + (beats[-1] - beats[-2])
    secs = []
    for s in B.get("sections") or []:
        if isinstance(s, dict) and s.get("t1", 0) > s.get("t0", 0):
            secs.append({"name": str(s.get("name") or "section"), "t0": float(s["t0"]), "t1": float(s["t1"]),
                         **({"energy": s["energy"]} if "energy" in s else {})})
    if not secs:
        secs = [{"name": "song", "t0": 0.0, "t1": B["duration"]}]
    secs.sort(key=lambda s: s["t0"])
    secs[0]["t0"] = 0.0
    secs[-1]["t1"] = B["duration"]
    for a, b in zip(secs, secs[1:]):        # tile [0, duration]: each section ends where the next begins
        a["t1"] = b["t0"]
    B["sections"] = [s for s in secs if s["t1"] - s["t0"] > 1e-6]
    return B


def load_words(pdir: Path) -> dict:
    W = read_json(Path(pdir) / "analysis/words.json", default=None)
    if W is None:
        return {"words": [], "lines": [], "missing": True}
    words = [w for w in W.get("words", []) if w.get("t0") is not None and w.get("t1") is not None]
    for w in words:
        w["t0"], w["t1"] = float(w["t0"]), float(w["t1"])
    words.sort(key=lambda w: w["t0"])
    lines = sorted(W.get("lines", []), key=lambda l: (l.get("line", 0)))
    return {"words": words, "lines": lines, "gaps": W.get("gaps", [])}


def load_hits(pdir: Path) -> dict:
    return read_json(Path(pdir) / "analysis/hits.json", default={}) or {}


def hit_times(hits: dict, proj: dict | None = None) -> list[float]:
    """Declared hits a cut may land on: hits.json hits/impact (+ project.json hits.add)."""
    out: list[float] = []
    for key in ("hits", "impact"):
        for h in hits.get(key) or []:
            t = h.get("t") if isinstance(h, dict) else (h[0] if isinstance(h, (list, tuple)) else h)
            if t is not None:
                out.append(float(t))
    for h in ((proj or {}).get("hits") or {}).get("add") or []:
        out.append(float(h[0] if isinstance(h, (list, tuple)) else h))
    return sorted(out)


def line_texts(pdir: Path, W: dict) -> dict[int, str]:
    """line index -> on-screen text (lyrics/display.txt tokens if present, else the aligned line text)."""
    out = {int(l["line"]): l.get("text", "") for l in W.get("lines", []) if l.get("line") is not None}
    disp = read_display(pdir)
    for i, spec in disp.items():
        out[i] = " ".join(strip_token(t) for t in spec.split())
    return out


def read_display(pdir: Path) -> dict[int, str]:
    """lyrics/display.txt -> {line index: token spec}. Blank lines and [Section] lines are skipped (the same rule as
    `slop lyrics display`); the remaining rows are the lyric lines in order (row k = line k)."""
    from slop.util import read_lyric_lines           # the shared lyric-line rule
    return dict(enumerate(read_lyric_lines(Path(pdir) / "lyrics/display.txt")))


def strip_token(tok: str) -> str:
    txt = tok.rsplit("|", 1)[0] if re.search(r"\|\d+$", tok) else tok
    return txt.strip("~*_")


def section_kind(name: str) -> str:
    n = (name or "").lower()
    if "pre" in n and ("chorus" in n or "hook" in n):
        return "pre"
    for kind, keys in (("chorus", ("chorus", "refrain")), ("hook", ("hook",)), ("intro", ("intro",)),
                       ("outro", ("outro", "ring", "end", "coda")), ("verse", ("verse", "rap")), ("bridge", ("bridge",)),
                       ("drop", ("drop",)), ("break", ("break",)), ("inst", ("inst", "solo", "interlude")),
                       ("pre", ("pre",)), ("post", ("post",))):
        if any(k in n for k in keys):
            return kind
    return "other"


def sections_with_kind(sections: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    out = []
    for s in sections:
        k = section_kind(s["name"])
        seen[k] = seen.get(k, 0) + 1
        m = re.search(r"(\d+)", s["name"])
        out.append({**s, "kind": k, "ordinal": int(m.group(1)) if m else seen[k]})
    return out


def beat_period(beats: list[float], t: float) -> float:
    import bisect
    i = min(max(bisect.bisect_right(beats, t), 1), len(beats) - 1)
    return max(1e-3, beats[i] - beats[i - 1])


# ------------------------------------------------------------------------------------------------ project bits
def motion_budget_s(proj: dict) -> float:
    b = proj.get("budget") or {}
    if b.get("motion_s") is not None:
        return float(b["motion_s"])
    return MOTION_BUDGET_BY_TIER.get(str(proj.get("tier") or "studio"), 120.0)


def banned_words(proj: dict) -> list[str]:
    words = list(proj.get("banned") or []) + list((proj.get("board") or {}).get("banned") or [])
    return [w for w in dict.fromkeys(str(x).strip() for x in words) if w]


def look_conf(proj: dict) -> dict:
    return dict(proj.get("look") or {})


def mmss(t: float) -> str:
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


def iter_strings(obj: Any, path: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{path}[{i}]")


def clamp(x: float, a: float, b: float) -> float:
    return max(a, min(b, x))


def ceil_int(x: float) -> int:
    return int(math.ceil(x - 1e-9))


# ------------------------------------------------------------------------------------------------ fonts (OFL only)
_FONT_CACHE: dict = {}


def font(size: int, bold: bool = False):
    """IBM Plex Mono (OFL) from the engine's fonts folder; Pillow's built-in font if the engine fonts are missing."""
    from PIL import ImageFont
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    fdir = engine_dir() / "fonts"
    names = (["IBMPlexMono-Medium.ttf", "IBMPlexMono-SemiBold.ttf"] if bold else []) + ["IBMPlexMono-Regular.ttf",
                                                                                      "JetBrainsMono-Regular.ttf"]
    f = None
    for n in names:
        if (fdir / n).is_file():
            try:
                f = ImageFont.truetype(str(fdir / n), size)
                break
            except OSError:
                pass
    if f is None:
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:           # Pillow < 10.1
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f
