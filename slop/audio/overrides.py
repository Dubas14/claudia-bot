"""The owner's fixes to the analysis: `slop song sections` (names + starts) and `slop song bars` (where bar 0 is).

Bars are counted from 0 everywhere: bar 0 is the first bar line (downbeats[0]), bar k starts at downbeats[k].
  slop song sections                                   show the sections, where each name came from, each one's @START
  slop song sections --set NAME@START,...              START: 0, seconds (40.4 or 1:02.5; snapped to the nearest bar
                                                       line), barK (bar K, from 0) or lineN (lyric line N, snapped to
                                                       its bar like a lyric tag); each ends where the next begins.
                                                       REPLACES ALL sections (the tagged ones too): list every one
  slop song sections --clear                           back to the lyric tags / the guess
  slop song bars                                       the bar phase, the votes and the evidence for each phase
  slop song bars --phase N                             bar 0 starts on beat N of the beat map (0-3); "auto" = the vote
  slop song bars --method kick|harmony|auto            which vote decides (when no --phase is set)

Each change writes project.json (audio.sections / audio.downbeat_phase / audio.downbeat_method), rebuilds what depends
on it at once (sections; after a bar change also hits.json), rewrites analysis/report.md, logs a dated line in
DECISIONS.md (core's append_decision when present, else a plain append), and checks the storyboard (board_check()):
  - an UNTOUCHED draft (draft true, every shot's set/framing/action still a TODO marker, no prompt, camera or device
    written, no board approval) is marked stale (board/shots.json "stale": [{at, why, fix}]) and the fix is a re-draft;
  - any other board - the lead has written into it (`board draft` keeps "draft": true after `board set`, `fill`,
    `device add` and `approve`, so the flag alone says nothing) - is NEVER written (its sha1 covers a board approval):
    the text lists the shots that sit on a moved section boundary and how to draft a separate file to compare with.
`slop analyze` and `slop lyrics fix` call the same check when they change the section names or starts.
"""
from __future__ import annotations

import re
import shlex
import time
from pathlib import Path

import numpy as np

from slop.config import SlopError, load_project, save_project

from .common import Paths, audio_cfg, project_cmd, read_json, write_json

_ITEM = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _-]*?)\s*@\s*(.+?)\s*$")
TODO = "TODO"                       # the board draft's marker (slop/board/common.py TODO)
LEAD_FIELDS = ("set", "framing", "action")
PROMPT_FIELDS = ("mj_prompt", "img_prompt", "prompt")
SHOW_SHOTS = 12


# ---------------------------------------------------------------- shared plumbing
def log_decision(pdir: Path, text: str) -> dict:
    """One dated line in DECISIONS.md: core's append_decision (dedup, template header) when it is installed."""
    try:
        from slop.core_cli import append_decision
    except ImportError:
        append_decision = None
    if append_decision is not None:
        try:
            return append_decision(pdir, text)
        except SlopError as e:
            return {"recorded": False, "error": str(e)}
    p = Path(pdir) / "DECISIONS.md"
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    cur = p.read_text(encoding="utf-8") if p.exists() else "# decisions\n\n## Log\n\n"
    p.write_text(cur + ("" if cur.endswith("\n") else "\n") + f"- {stamp} - {text}\n", encoding="utf-8")
    return {"recorded": True, "entry": {"when": stamp, "text": text}, "file": str(p)}


def section_sig(secs: list[dict] | None) -> list[tuple[str, float]]:
    """(name, start) of each section, to tell whether a rebuild changed anything the board was cut on."""
    return [(str(s.get("name")), round(float(s.get("t0") or 0.0), 2)) for s in secs or [] if isinstance(s, dict)]


def _approved(pdir: Path) -> bool:
    try:
        return bool((load_project(pdir).get("gates") or {}).get("board_approved"))
    except Exception:
        return False


def board_untouched(pdir: Path, S: dict) -> tuple[bool, str]:
    """(True, "") when board/shots.json is a draft nobody has written into yet; else (False, the first sign of an
    edit). Decided from the CONTENT: the board module keeps "draft": true through every edit."""
    if not S.get("draft"):
        return False, "not a draft"
    if _approved(pdir):
        return False, "the owner approved it (gates.board_approved)"
    for sh in S.get("shots") or []:
        if not isinstance(sh, dict):
            return False, "a shot is not an object"
        sid = sh.get("id", "?")
        for k in LEAD_FIELDS:
            if not str(sh.get(k) or "").strip().startswith(TODO):
                return False, f"{sid} has its {k} written"
        for k in PROMPT_FIELDS:
            v = str(sh.get(k) or "").strip()
            if v and not v.startswith(TODO):
                return False, f"{sid} has its {k.replace('_', '-')} written"
        if str(sh.get("camera") or "").strip():
            return False, f"{sid} has its camera written"
        if sh.get("devices"):
            return False, f"{sid} has devices"
    return True, ""


def _name_at(secs: list[dict], t: float) -> str | None:
    for s in secs:
        if float(s["t0"]) - 1e-3 <= t < float(s["t1"]) - 1e-3:
            return str(s["name"])
    return str(secs[-1]["name"]) if secs and t >= float(secs[-1]["t0"]) else None


def moved_shots(S: dict, old: list[dict], new: list[dict]) -> list[dict]:
    """The shots that sit on a changed section boundary: their section at the cut is named differently now, or a section
    start that appeared or disappeared falls at their cut or inside them."""
    olds = {round(float(s["t0"]), 2) for s in old or []}
    news = {round(float(s["t0"]), 2) for s in new or []}
    moved = sorted((olds ^ news) - {0.0})
    out = []
    for sh in S.get("shots") or []:
        try:
            t0, t1 = float(sh["t0"]), float(sh["t1"])
        except (KeyError, TypeError, ValueError):
            continue
        why = []
        a, b = _name_at(old or [], t0 + 1e-3), _name_at(new or [], t0 + 1e-3)
        if b is not None and a != b:
            why.append(f"section {a or '-'} -> {b}")
        hit = [x for x in moved if t0 - 0.05 <= x < t1 - 0.05]
        if hit:
            starts_new = [x for x in hit if x in news]
            why.append("a section now starts " + ("at its cut" if any(abs(x - t0) <= 0.05 for x in starts_new)
                                                  else f"inside it at {starts_new[0]:.2f} s") if starts_new else
                       f"its cut was on the old start at {hit[0]:.2f} s")
        if why:
            out.append({"id": sh.get("id"), "t0": round(t0, 3), "t1": round(t1, 3), "why": "; ".join(why)})
    return out


def _redraft_path(pdir: Path) -> Path:
    base = Path(pdir) / "board"
    for k in range(1, 100):
        p = base / ("shots.redraft.json" if k == 1 else f"shots.redraft-{k}.json")
        if not p.exists():
            return p
    return base / f"shots.redraft-{time.strftime('%Y%m%d-%H%M%S')}.json"


def board_check(pdir: Path, why: str, old: list[dict] | None, new: list[dict] | None) -> dict | None:
    """After the sections or bars changed: mark an untouched draft stale (the fix is a re-draft), or leave an edited
    board alone and list the shots to re-check. -> None without a board, else {file, untouched, marked, fix, shots,
    approved, why_kept}."""
    p = Path(pdir) / "board" / "shots.json"
    if not p.is_file():
        return None
    audit = project_cmd(pdir, "board audit")
    try:
        S = read_json(p)
    except SlopError:
        S = None
    if not isinstance(S, dict):
        return {"file": "board/shots.json", "untouched": False, "marked": False, "shots": [], "approved": False,
                "fix": f"board/shots.json does not read as a storyboard: fix it, then `{audit}`"}
    untouched, reason = board_untouched(pdir, S)
    if untouched:
        fix = project_cmd(pdir, "board draft --force")
        st = [x for x in (S.get("stale") or []) if isinstance(x, dict)][-4:]
        st.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": why, "fix": fix})
        S["stale"] = st
        write_json(p, S, indent=1)
        return {"file": "board/shots.json", "untouched": True, "marked": True, "fix": fix, "shots": [],
                "approved": False}
    shots = moved_shots(S, old or [], new or [])
    redraft = _redraft_path(pdir)
    compare = project_cmd(pdir, f"board draft --out {shlex.quote(str(redraft))}")
    return {"file": "board/shots.json", "untouched": False, "marked": False, "why_kept": reason, "shots": shots,
            "approved": _approved(pdir), "compare": compare, "redraft": str(redraft),
            "fix": f"re-check the cuts and section pace of the listed shots in board/shots.json "
                   f"(`{project_cmd(pdir, 'board set SHOT ...')}`), then `{audit}`"}


def board_text(b: dict | None) -> str:
    if not b:
        return ""
    if b.get("marked"):
        return (f"\nboard/shots.json is an untouched draft built on the old analysis: marked stale. Re-draft it: "
                f"`{b['fix']}`")
    if b.get("untouched") is False and "compare" in b:
        sh = b.get("shots") or []
        lines = [f"\nboard/shots.json has the lead's work in it ({b.get('why_kept')}): NOT changed, do NOT re-draft it "
                 "with --force."]
        if sh:
            lines.append(f"{len(sh)} shot(s) sit on a changed section boundary: "
                         + "; ".join(f"{x['id']} {x['t0']:.2f}-{x['t1']:.2f} s ({x['why']})" for x in sh[:SHOW_SHOTS])
                         + (f"; ... {len(sh) - SHOW_SHOTS} more (the JSON lists all)" if len(sh) > SHOW_SHOTS else ""))
        else:
            lines.append("no shot sits on a changed section boundary; the section pace may still differ.")
        lines.append(f"To compare with a fresh draft on the new analysis (written to a separate file; board/shots.json "
                     f"stays as it is): `{b['compare']}`. Then {b['fix']}.")
        if b.get("approved"):
            lines.append("The owner approved this board on the old sections: after the re-check, ask the owner again.")
        return "\n".join(lines)
    return f"\n{b.get('fix')}" if b.get("fix") else ""


def _need_beats(paths: Paths, pdir: Path) -> dict:
    B = read_json(paths.beats)
    if not B or not B.get("beats"):
        raise SlopError(f"no analysis/beats.json yet: run `{project_cmd(pdir, 'analyze')}` first (sections and bars live "
                        "on the beat map)")
    return B


def _set_audio(pdir: Path, **kv) -> dict:
    proj = load_project(pdir)
    au = dict(proj.get("audio") or {})
    for k, v in kv.items():
        if v is None:
            au.pop(k, None)
        else:
            au[k] = v
    proj["audio"] = au
    save_project(pdir, proj)
    return au


# ---------------------------------------------------------------- sections
def parse_spec(spec: str) -> list[dict]:
    """'intro@0,verse1@bar8,chorus1@line9,bridge@1:42.5' -> project.json audio.sections entries."""
    items = [x for x in re.split(r"[,;\n]", spec or "") if x.strip()]
    if not items:
        raise SlopError("--set needs NAME@START items separated by commas (START: 0, seconds, barK or lineN); it "
                        "replaces ALL sections, so list every one")
    out, seen = [], set()
    for it in items:
        m = _ITEM.match(it)
        if not m:
            raise SlopError(f'--set: cannot read "{it.strip()}": write NAME@START (START: 0, seconds like 40.4 or 1:02.5, '
                            "barK like bar8, or lineN like line9)")
        name = re.sub(r"[^a-z0-9-]", "", re.sub(r"[\s_]+", "-", m.group(1).strip().lower()))
        if not name:
            raise SlopError(f'--set: "{it.strip()}": the name needs letters (intro, verse1, chorus2, bridge, outro)')
        if name in seen:
            raise SlopError(f'--set: section name "{name}" is used twice: number repeats (chorus1, chorus2)')
        seen.add(name)
        w = m.group(2).strip().lower()
        if re.fullmatch(r"(bar|b)\s*-?\d+", w):
            out.append({"name": name, "bar": int(re.sub(r"\D", "", w) or 0) * (-1 if "-" in w else 1)})
        elif re.fullmatch(r"(line|l)\s*\d+", w):
            n = int(re.sub(r"\D", "", w))
            if n < 1:
                raise SlopError(f'--set: "{it.strip()}": lyric lines count from 1')
            out.append({"name": name, "line": n})
        elif re.fullmatch(r"\d+:\d{1,2}(\.\d+)?", w):
            mm, ss = w.split(":")
            out.append({"name": name, "t0": round(int(mm) * 60 + float(ss), 3)})
        elif re.fullmatch(r"\d+(\.\d+)?s?", w):
            out.append({"name": name, "t0": round(float(w.rstrip("s")), 3)})
        else:
            raise SlopError(f'--set: "{it.strip()}": the start must be 0, seconds (40.4 or 1:02.5), barK (bar8, bars '
                            "count from 0) or lineN (line9)")
    return out


def _sections_text(B: dict) -> list[str]:
    from .sections import bar_ref
    down = B.get("downbeats") or []
    rows = []
    for s in B.get("sections") or []:
        src = {"set": "set", "lyrics-tag": "tag " + (s.get("tag") or ""), "heuristic": "GUESS (unconfirmed)"}.get(
            s.get("source") or "heuristic", s.get("source"))
        b0 = "pickup" if (s.get("bar0") or 0) < 0 else s.get("bar0")
        start = f"{s['name']}{bar_ref(s, down)}"
        bars = f"bars {b0}..{s.get('bar1')}"
        rows.append(f"  {s['name']:<12} {s['t0']:7.2f} - {s['t1']:7.2f} s  {bars:<15} {start:<18} {src}")
    return rows


def sections_cmd(pdir: Path, set_spec: str | None = None, clear: bool = False) -> dict:
    from . import report, sections
    from .align import read_sheet
    paths = Paths(pdir)
    B = _need_beats(paths, pdir)
    if set_spec and clear:
        raise SlopError("pass --set SPEC or --clear, not both")
    old = list(B.get("sections") or [])
    changed, dec, board, what, snaps = False, None, None, None, []
    if set_spec:
        items = parse_spec(set_spec)
        dur = float(B.get("duration") or 0)
        for it in items:                   # typed seconds past the end must not snap silently onto the last bar line
            if "t0" in it and dur and not 0 <= it["t0"] < dur:
                raise SlopError(f'--set: section "{it["name"]}" starts at {it["t0"]:.2f} s, outside the song '
                                f'(0-{dur:.2f} s)')
        W = read_json(paths.words) or {}
        down, beats = np.asarray(B["downbeats"], float), np.asarray(B["beats"], float)
        cfg = audio_cfg(pdir)
        starts = sections.parse_override(items, down, beats, W.get("words"),
                                         float(cfg.get("section_pickup_beats", sections.PICKUP_BEATS)),
                                         where="--set", pdir=pdir, info=snaps)
        for t0, n in starts:
            if dur and not 0 <= t0 < dur:
                raise SlopError(f'--set: section "{n}" starts at {t0:.2f} s, outside the song (0-{dur:.2f} s)')
        ts = [round(t, 3) for t, _ in starts]
        if len(set(ts)) != len(ts):
            dup = sorted({f"{t:.2f}" for t in ts if ts.count(t) > 1})
            raise SlopError(f"--set: two sections start at the same time ({', '.join(dup)} s"
                            + (", after snapping to the nearest bar line" if snaps else "") + "): give each its own start")
        if starts[0][0] > 0.5 and any(n == "intro" for _, n in starts):
            first = starts[0]
            raise SlopError(f'--set: your first section "{first[1]}" starts at {first[0]:.2f} s, so the song before it '
                            'needs a section too, and that one would be the intro - but your list already uses the name '
                            '"intro". Start the intro at 0 (intro@0) or rename it.')
        _set_audio(pdir, sections=items)
        changed = True
        what = "sections set: " + ", ".join(f"{n}@{t:.2f}s" for t, n in starts)
    elif clear:
        if audio_cfg(pdir).get("sections") is not None:
            _set_audio(pdir, sections=None)
            changed = True
            what = "sections override cleared (back to the lyric tags / the guess)"
    r = sections.build(pdir, force=changed)
    B = read_json(paths.beats)
    if changed:
        report.write(pdir)
        dec = log_decision(pdir, f"{what} [slop song sections]")
        if section_sig(old) != section_sig(B.get("sections")):
            board = board_check(pdir, what, old, B.get("sections"))
    unconf = [s["name"] for s in B.get("sections") or [] if s.get("unconfirmed")]
    lines = ([what or "no change"] if (set_spec or clear) else ["sections:"])
    lines += [f"  snapped: {x}" for x in snaps]
    lines.append(f"  {'name':<12} {'start':>7} - {'end':>7}    {'bars (from 0)':<15} {'--set START':<18} source")
    lines += _sections_text(B)
    lines.append(f"from: {B.get('sections_from', 'heuristic')}")
    if changed:
        lines.append("logged in DECISIONS.md; analysis/report.md updated")
    if unconf:
        try:
            sheet = read_sheet(paths.lyrics) if paths.lyrics.exists() else None
        except SlopError:
            sheet = None
        lines.append(f"{len(unconf)} name(s) are a GUESS ({', '.join(unconf)}). Confirm them:")
        lines += [f"  - {h}" for h in sections.confirm_hints(B, pdir, sheet)]
    elif not set_spec and not clear:
        lines.append(f"change them: `{project_cmd(pdir, 'song sections --set NAME@START,...')}` (REPLACES ALL "
                     "sections: list every one, the START column above gives each one's current start)")
    text = "\n".join(lines) + board_text(board)
    return {"sections": B.get("sections") or [], "from": B.get("sections_from"), "changed": changed,
            "unconfirmed": unconf, "snapped": snaps, "decision": dec, "board": board, "status": r.get("status"),
            "text": text}


# ---------------------------------------------------------------- bars
def phase_evidence(B: dict) -> list[dict]:
    """Per phase 0-3: the first bar line and the 32-beat blocks the kick and chord votes gave it. (A lyric-tag count was
    tried and dropped: on a real song the tagged lines start on pickups and on beat 2 as often as on bar lines, and it
    favoured a wrong phase.)"""
    beats = np.asarray(B["beats"], float)
    votes = B.get("downbeat_votes") or {}
    kb = (votes.get("kick") or {}).get("blocks") or B.get("phase_blocks") or []
    hb = (votes.get("harmony") or {}).get("blocks") or []
    return [{"phase": p, "first_bar": round(float(beats[p]), 3) if p < len(beats) else None,
             "kick_blocks": kb.count(p), "chord_blocks": hb.count(p)} for p in range(4)]


def bars_cmd(pdir: Path, phase: str | int | None = None, method: str | None = None) -> dict:
    from . import beatmap, report, sections
    paths = Paths(pdir)
    B = _need_beats(paths, pdir)
    before = {"phase": B.get("downbeat_phase"), "method": B.get("downbeat_method"), "first": (B.get("downbeats") or [None])[0]}
    old = list(B.get("sections") or [])
    changes = {}
    if phase is not None:
        ps = str(phase).strip().lower()
        if ps in ("auto", "vote", "none", "clear"):
            changes["downbeat_phase"] = None
        elif re.fullmatch(r"[0-3]", ps):
            changes["downbeat_phase"] = int(ps)
        else:
            raise SlopError("--phase takes 0, 1, 2 or 3 (the beat of the beat map that starts bar 0, the first bar "
                            "line), or auto (the vote)")
    if method is not None:
        m = method.strip().lower()
        if m not in ("kick", "harmony", "auto"):
            raise SlopError("--method takes kick (the default vote), harmony (chord changes) or auto")
        changes["downbeat_method"] = None if m == "kick" else m
    cfg = audio_cfg(pdir)
    real = {k: v for k, v in changes.items() if cfg.get(k) != v}
    res, steps, dec, board = None, {}, None, None
    if real:
        _set_audio(pdir, **real)
        res = beatmap.apply_phase(pdir)
        steps["beats"] = res.get("status")
        B = read_json(paths.beats)
        moved = res.get("moved", res.get("status") == "done")
        if moved:
            steps["sections"] = sections.build(pdir, force=True).get("status")
            if paths.hits.exists():
                from . import hits
                try:
                    steps["hits"] = hits.build(pdir, force=True).get("status")
                except SlopError as e:
                    steps["hits"] = f"failed: {e}"
            B = read_json(paths.beats)
        report.write(pdir)
        desc = "; ".join([f"bar phase {B.get('downbeat_phase')} ({'set' if real.get('downbeat_phase') is not None else 'vote'})"]
                         + ([f"downbeat vote {changes['downbeat_method'] or 'kick'}"] if "downbeat_method" in real else []))
        what = f"bars: {desc}, bar 0 at {B['downbeats'][0]:.2f} s (was phase {before['phase']}, {before['first']:.2f} s)" \
            if B.get("downbeats") and before["first"] is not None else f"bars: {desc}"
        dec = log_decision(pdir, f"{what} [slop song bars]")
        if moved:
            board = board_check(pdir, what, old, B.get("sections"))
    ev = phase_evidence(B)
    cur = int(B.get("downbeat_phase") or 0)
    lines = [(f"bar phase {before['phase']} -> {cur}" if real and before["phase"] != cur else
              f"bar phase {cur}") + f" ({B.get('downbeat_method')}); bar 0 (the first bar line) starts at "
             f"{(B.get('downbeats') or [0])[0]:.2f} s; {len(B.get('downbeats') or [])} bars, numbered 0.."
             f"{max(len(B.get('downbeats') or []) - 1, 0)} (`song sections --set NAME@barK` and the report use the "
             "same numbers)"]
    lines.append("phase  bar 0 at  kick votes  chord votes   (votes = 32-beat blocks won)")
    for e in ev:
        mark = "   <- now" if e["phase"] == cur else ""
        fb = f"{e['first_bar']:.2f}" if e["first_bar"] is not None else "-"
        lines.append(f"  {e['phase']}    {fb:>7} s  {e['kick_blocks']:>5}       {e['chord_blocks']:>5}{mark}")
    for n in B.get("notes") or []:
        if n.startswith(beatmap.PHASE_NOTE):
            lines.append(f"note: {n}")
    if real:
        lines.append("re-built: " + ", ".join(f"{k} {v}" for k, v in steps.items()) + "; analysis/report.md updated; "
                     "logged in DECISIONS.md")
    else:
        lines.append("check by ear: a drop, a chorus or the first kick after a break should land on beat 1 of a bar "
                     "(listen with the bar column of analysis/report.md); if every bar line is off by the same beats, "
                     f"`{project_cmd(pdir, 'song bars --phase N')}` (N = 0-3 from the table; `--phase auto` goes back "
                     "to the vote)")
    text = "\n".join(lines) + board_text(board)
    return {"downbeat_phase": cur, "downbeat_method": B.get("downbeat_method"), "first_bar": (B.get("downbeats") or [None])[0],
            "changed": sorted(real), "rebuilt": steps, "evidence": ev, "decision": dec, "board": board, "text": text}
