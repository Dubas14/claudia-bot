"""`slop analyze`: one command, many steps (stems -> beats -> align -> sections -> hits [-> spectrum] -> report).

Each step is idempotent: it keys on its inputs (analysis/state.json) and is skipped when nothing changed, so re-running
after editing the lyric sheet only re-aligns (emissions are cached too) and keeps manual timing fixes. --force redoes.

Operator contract (a weaker model drives this):
  - a fresh project (template lyrics.txt holding only [notes]) runs: alignment is skipped with a note saying what to
    write, never minutes of CPU ending in an error; an explicit `--steps align` without lyrics fails BEFORE any work;
  - when the beat map changes, the sections (stored in beats.json) and an existing hits.json are rebuilt in the same run
    (they were built on the old bars); sections run AFTER align, and a re-alignment of a sheet with section tags
    ([Verse 1], [Chorus] ...) rebuilds them too (each tagged section starts at its first aligned word);
  - Whisper: `--whisper-fallback` may pay (~$0.002/song, ledgered); every later plain run REUSES the cached
    transcription of the same vocal stem for free (the sung-line timing is never silently dropped); `--no-whisper`
    turns it off until the next `--whisper-fallback` (free while the cache fits the vocal stem); a plain run never
    spends money;
  - progress: one stderr line per step plus a heartbeat every 30 s, and analysis/progress.json rewritten after every
    step ({running, step, done[], failed?}) - run it as a background job and poll that file; last-run.json at the end.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from slop.config import SlopError

from . import whisper as wh
from .common import (Heartbeat, Paths, audio_cfg, fingerprint, project_cmd, read_json, state_get, state_set,
                     write_json)

DEFAULT_STEPS = ["stems", "align", "beats", "hits", "sections"]
ALL_STEPS = ["stems", "beats", "align", "sections", "hits", "spectrum"]          # execution order (sections read the tags' word timing)
SHEET_HELP = ("write the sung lyrics in lyrics/lyrics.txt (one line per lyric line, words AS SUNG: numbers and symbols "
              "spelled out, \"A G I\" for letters; [section] lines and notes are ignored)")


def parse_steps(spec: str | None) -> list[str]:
    if not spec:
        return list(DEFAULT_STEPS)
    steps = [s.strip().lower() for s in spec.split(",") if s.strip()]
    bad = [s for s in steps if s not in ALL_STEPS]
    if bad:
        raise SlopError(f"unknown step(s) {bad}; choose from {','.join(ALL_STEPS)}")
    return steps


def run_align(pdir: Path, paths: Paths, lines: list[str], force: bool, whisper_mode: str, whisper_model: str,
              yes: bool, allow_digits: bool, prefer_model: str | None = None) -> dict:
    """whisper_mode: "on" (--whisper-fallback: transcribe if needed, may pay), "auto" (reuse a cached transcription of
    this vocal stem for free - prefer_model's, else the latest - and never pay), "off" (--no-whisper)."""
    from . import align as al
    from . import merge as mg
    cfg = audio_cfg(pdir)
    problems = al.check_sheet(lines, allow_digits)
    conf_min = float(cfg.get("conf_min", mg.CONF_MIN))
    prev = state_get(paths, "align")
    notes: list[str] = []
    if whisper_mode == "auto" and prev.get("whisper") == "off":
        whisper_mode = "off"                      # --no-whisper sticks until --whisper-fallback turns it back on
    cached = None
    if whisper_mode == "on":
        cached = wh.find_cached(paths, whisper_model)
    elif whisper_mode == "auto":
        cached = (wh.find_cached(paths, prefer_model) if prefer_model else None) or wh.find_cached(paths, None)
    if cached:
        wtag = cached["tag"]
    elif whisper_mode == "on":
        wtag = "-" if prev.get("whisper") == "not-needed" and prev.get("whisper_model") == whisper_model else "pending"
    else:
        wtag = "-"
    base = f"v2|{fingerprint(paths.stem('vocals'), paths.lyrics)}|{conf_min}|{cfg.get('whisper_map')}"
    if not force and paths.words.exists() and prev.get("key") == f"{base}|{wtag}":
        W = read_json(paths.words)
        out = {"status": "up-to-date", "words": len(W["words"]), "sources": W.get("stats")}
        if W.get("whisper"):
            out["whisper"] = {k: W["whisper"].get(k) for k in ("model", "cost_usd", "words")}
        return out
    if whisper_mode == "auto" and not cached and prev.get("whisper") == "used":
        notes.append("the Whisper re-timing of sung lines was dropped: the vocal stem changed since that paid run. "
                     f"Re-run `{project_cmd(pdir, 'analyze --steps align --whisper-fallback')}` (~$0.002) to re-time "
                     "them.")
    res = al.align(paths, lines, force=force)
    w2v = res.pop("words")
    low = sum(1 for w in w2v if (w.get("score") or 0) < conf_min)
    whisper_words, wres, R, wstate = None, None, None, ("off" if whisper_mode == "off" else "none")
    if cached:
        wres = {**cached, "cached": True, "cost_paid_now": 0.0}
    elif whisper_mode == "on":
        if low:
            usd = cfg.get("whisper_usd_per_s")
            R = wh.vocal_env(paths.stem("vocals"))
            t = wh.transcribe(pdir, wh.plan_windows(R), model=whisper_model, yes=yes,
                              usd_per_s=float(usd) if usd is not None else None)
            wres = {"model": t["model"], "words": t["words"], "windows": t["windows"], "cost_usd": t["cost_total_usd"],
                    "tag": t["tag"], "cached": t["cached"], "cost_paid_now": t["cost_usd"]}
        else:
            wstate = "not-needed"
    if wres is not None:
        whisper_words = wres["words"]
        R = R if R is not None else wh.vocal_env(paths.stem("vocals"))
        wstate = "used"
        wtag = wres["tag"]
    elif wstate != "not-needed":
        wtag = "-"
    previous = read_json(paths.words)
    W = mg.merge(w2v, lines, whisper_words, R, cfg.get("whisper_map"), previous, conf_min)
    W["source"] = "align-v1"
    W["model"] = al.MODEL_ID
    if wres:
        W["whisper"] = {"model": wres["model"], "windows": wres["windows"], "cost_usd": wres["cost_usd"],
                        "paid_this_run": wres["cost_paid_now"], "cached": wres["cached"], "words": len(wres["words"])}
    write_json(paths.words, W)
    state_set(paths, "align", f"{base}|{wtag}", whisper=wstate, whisper_model=(wres or {}).get("model") or whisper_model)
    out = {"status": "done", "words": len(W["words"]), "lines": len(lines), "sources": W["stats"],
           "low_conf_w2v": low, "warnings": [p["msg"] + f" (line {p['line'] + 1})" for p in problems if p["level"] == "warn"],
           "notes": notes, **res}
    if wres:
        out["whisper"] = W["whisper"]
    return out


def _display_has_lines(paths: Paths) -> bool:
    if not paths.display.exists():
        return False
    from .display import read_display
    return bool(read_display(paths.display))


class _Progress:
    """analysis/progress.json, rewritten after every step (poll it while `slop analyze` runs in the background)."""

    def __init__(self, paths: Paths, steps: list[str]):
        self.paths, self.t0 = paths, time.monotonic()
        self.d = {"running": True, "pid": os.getpid(), "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": steps,
                  "step": None, "done": {}, "failed": None}
        self.write()

    def write(self) -> None:
        self.d["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.d["elapsed_s"] = round(time.monotonic() - self.t0, 1)
        try:
            write_json(self.paths.progress, self.d, 1)
        except OSError:
            pass

    def start(self, step: str) -> None:
        self.d["step"] = step
        self.write()

    def finish(self, step: str, r: dict) -> None:
        self.d["done"][step] = {"status": r.get("status"), "seconds": r.get("seconds")}
        self.d["step"] = None
        self.write()

    def fail(self, step: str | None, err: str) -> None:
        self.d.update(running=False, failed={"step": step, "error": err})
        self.write()

    def end(self) -> None:
        self.d.update(running=False, step=None)
        self.write()


def run(pdir: Path, steps: list[str], force: bool = False, whisper_fallback: bool = False,
        whisper_model: str | None = None, yes: bool = False, allow_digits: bool = False,
        stems_dir: str | None = None, no_whisper: bool = False, heartbeat: float = 30.0) -> dict:
    paths = Paths(pdir)
    if not paths.song.exists():
        raise SlopError(f"no audio/song.wav - run `{project_cmd(pdir, 'song ingest FILE')}` first")
    if whisper_fallback and no_whisper:
        raise SlopError("--whisper-fallback and --no-whisper contradict each other; pass one")
    cfg = audio_cfg(pdir)
    explicit_model = bool(whisper_model)
    whisper_model = whisper_model or cfg.get("whisper_model") or wh.DEFAULT_MODEL
    whisper_mode = "off" if no_whisper else ("on" if whisper_fallback else "auto")
    explicit = steps != DEFAULT_STEPS
    results: dict[str, dict] = {}
    notes: list[str] = []
    sheet: list[str] = []
    # fail fast, before minutes of CPU work
    if "align" in steps:
        from .align import check_sheet, read_sheet
        sheet = read_sheet(paths.lyrics) if paths.lyrics.exists() else []
        if not sheet:
            why = "no lyrics/lyrics.txt" if not paths.lyrics.exists() else "lyrics/lyrics.txt has no lyric lines yet"
            if explicit:
                raise SlopError(f"{why}: {SHEET_HELP}, check it with `{project_cmd(pdir, 'lyrics lint')}`, then re-run "
                                f"`{project_cmd(pdir, 'analyze --steps align')}`.")
            steps = [s for s in steps if s != "align"]
            results["align"] = {"status": "skipped", "why": why}
            notes.append(f"alignment skipped ({why}): {SHEET_HELP}, then run "
                         f"`{project_cmd(pdir, 'analyze --steps align')}`")
        else:
            check_sheet(sheet, allow_digits)
            if whisper_mode == "on" and not wh.have_key() and not wh.find_cached(paths, whisper_model):
                raise SlopError("--whisper-fallback needs OPENROUTER_API_KEY (about $0.002 per song). Ask the user for "
                                "it with the secure secret card, or run without --whisper-fallback.")
    old_sections = list((read_json(paths.beats) or {}).get("sections") or []) if paths.beats.exists() else []
    prog = _Progress(paths, [s for s in ALL_STEPS if s in steps])
    added: list[str] = []
    cur = None
    try:
        for step in ALL_STEPS:
            if step not in steps:
                continue
            cur = step
            prog.start(step)
            t = time.monotonic()
            with Heartbeat(step, every=heartbeat):
                if step == "stems":
                    from . import stems as st
                    r = st.import_stems(pdir, stems_dir, force=force) if stems_dir else st.separate(pdir, force=force)
                elif step == "beats":
                    from . import beatmap
                    r = beatmap.build(pdir, force=force)
                elif step == "sections":
                    from . import sections
                    r = sections.build(pdir, force=force)
                elif step == "align":
                    r = run_align(pdir, paths, sheet, force, whisper_mode, whisper_model, yes, allow_digits,
                                  prefer_model=whisper_model if explicit_model else None)
                    notes += r.get("notes") or []
                elif step == "hits":
                    from . import hits
                    r = hits.build(pdir, force=force)
                else:
                    from . import spectrum
                    r = spectrum.build(pdir, force=force)
            r["seconds"] = round(time.monotonic() - t, 1)
            results[step] = r
            prog.finish(step, r)
            if step == "align" and r.get("status") == "done" and "sections" not in steps and paths.beats.exists():
                from .sections import has_tags
                if has_tags(paths.lyrics):            # tagged sections start at their first aligned word
                    steps = steps + ["sections"]
                    added.append("sections")
            if step == "beats" and r.get("status") == "done":
                # bars moved: sections (inside beats.json) and an existing hits.json were built on the old bars
                for dep, exists in (("sections", True), ("hits", paths.hits.exists())):
                    if dep not in steps and exists:
                        steps = steps + [dep]
                        added.append(dep)
            if step == "stems" and r.get("status") in ("done", "imported"):
                for dep, path in (("beats", paths.beats), ("hits", paths.hits)):
                    if dep not in steps and path.exists():
                        steps = steps + [dep]
                        added.append(dep)
                if "align" not in steps and paths.words.exists():
                    notes.append("analysis/words.json was aligned on the old vocal stem: run "
                                 f"`{project_cmd(pdir, 'analyze --steps align')}`")
    except SlopError as e:
        prog.fail(cur, str(e))
        raise
    except BaseException as e:
        prog.fail(cur, f"{type(e).__name__}: {e}")
        raise
    if added:
        notes.append("re-ran " + ", ".join(sorted(set(added))) + " too: they were built on the old stems/beat map/word "
                     "timing")
    from . import report
    rep = report.write(pdir, results)
    items = rep["ear_check"]
    groups = rep["groups"]
    urgent = [g for g in groups if g["urgent"]]
    B = read_json(paths.beats) or {}
    W = read_json(paths.words)
    lines = []
    for k in [x for x in ALL_STEPS if x in results]:
        v = results[k]
        s = v.get("status")
        extra = ""
        if k == "beats" and B:
            extra = (f" - {len(B.get('beats', []))} beats, {B.get('tempo_start')} -> {B.get('tempo_end')} BPM, "
                     f"downbeat phase {B.get('downbeat_phase')} ({B.get('downbeat_method')})")
        elif k == "sections" and B.get("sections"):
            extra = (f" - from {B.get('sections_from', 'heuristic')}: "
                     + ", ".join(f"{x['name']}{'?' if x.get('unconfirmed') else ''} {x['t0']:.0f}s" for x in B["sections"]))
        elif k == "align" and W and s != "skipped":
            extra = (f" - {len(W['words'])} words, sources {W.get('stats')}"
                     + (f", mean conf {v['mean_conf']}" if "mean_conf" in v else "")
                     + (f", Whisper {W['whisper']['model']} (cached, free)" if W.get("whisper") and
                        not (W["whisper"].get("paid_this_run") or 0) else
                        (f", Whisper paid ${W['whisper']['paid_this_run']:.4f}" if W.get("whisper") else "")))
        elif k == "align" and s == "skipped":
            extra = f" - {v.get('why')}"
        elif k == "hits" and v.get("hits") is not None:
            extra = (f" - {v['kick']} kicks, {v['snare']} snares, {v['hits']} real hits, {v['risers']} risers, "
                     f"{v['fills']} fills")
        lines.append(f"{k}: {s}{extra} ({v.get('seconds', 0)} s)")
    nxt = []
    if urgent:
        nxt.append(f"listen to the {len(urgent)} line(s) in the EAR CHECK of analysis/report.md and fix timing with "
                   f"`{project_cmd(pdir, 'lyrics fix ...')}`")
    if W and not W.get("whisper") and any(i["kind"] == "verylow" for i in items) and whisper_mode != "off":
        nxt.append(f"sung lines aligned poorly: `{project_cmd(pdir, 'analyze --steps align --whisper-fallback')}` "
                   "re-times them (~$0.002, ledgered) - do this BEFORE the ear check; then "
                   f"`{project_cmd(pdir, 'lyrics check')}` (free: same transcription) lists words the take sings "
                   "differently from lyrics.txt (Lyria/Suno takes change words)")
    unconf = [x["name"] for x in (B or {}).get("sections") or [] if x.get("unconfirmed")]
    if unconf and "sections" in results:
        from .sections import confirm_hints
        hints = confirm_hints(B, pdir)
        more = len(hints) - 3 if len(hints) > 3 else 0
        nxt.append(f"section names marked ? ({', '.join(unconf[:6])}{' ...' if len(unconf) > 6 else ''}) are a guess - "
                   + " / ".join(hints[:2] + hints[-1:] if more else hints)
                   + (f" ({more} more in the Sections part of analysis/report.md)" if more else ""))
    board = None
    if (results.get("sections") or {}).get("status") == "done":
        from .overrides import board_check, board_text, section_sig
        if old_sections and section_sig(old_sections) != section_sig(B.get("sections")):
            what = ("the analysis re-built the sections: " + ", ".join(f"{n}@{t:.2f}s" for n, t in
                                                                      section_sig(B.get("sections"))))
            board = board_check(pdir, what, old_sections, B.get("sections"))
            if board:
                nxt.append("the section names/starts changed and board/shots.json was built on the old ones:"
                           + board_text(board).replace("\n", " "))
    if W and not _display_has_lines(paths):
        nxt.append(f"write the on-screen text: `{project_cmd(pdir, 'lyrics display --init')}`, then edit "
                   "lyrics/display.txt")
    text = "\n".join(lines + [f"report: analysis/report.md - ear check: {len(urgent)} line(s) need a listen"
                              + (f", {len(groups) - len(urgent)} more if time allows" if len(groups) > len(urgent) else "")]
                     + [f"note: {n}" for n in notes] + ([f"next: {'; '.join(nxt)}"] if nxt else []))
    write_json(paths.analysis / "last-run.json", {"steps": results, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, 1)
    prog.end()
    return {"steps": results, "ear_check": items, "ear_check_lines": groups, "report": rep["file"], "notes": notes,
            "next": nxt, "board": board, "text": text}
