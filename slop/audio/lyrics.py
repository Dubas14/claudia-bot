"""`slop lyrics lint` (scansion report + fixes) and `slop lyrics fix` (manual word timing).

lint: the alignment-sheet problems that make `slop analyze` refuse the sheet (digits, symbols, lines without letters)
are counted as errors and printed first ("alignment sheet: must fix before slop analyze"), with the suggested
spelling - the same check analyze runs, so "0 errors" here means analyze accepts the sheet.
fix: every new time must satisfy 0 <= t0 < t1 <= the song's duration (beats.json / song.json), for --t0/--t1 and for
--shift alike; the error states the allowed range.
"""
from __future__ import annotations

from pathlib import Path

from slop.config import SlopError

from . import scansion as S
from .common import Paths, project_cmd, read_json, write_json

LEVEL = {"ERROR": "error", "warn": "warn", "info": "info"}


def _clean(r: dict) -> dict:
    return {k: v for k, v in r.items() if k not in ("syl", "spans", "pos")}


def lint_text(text: str, bpm: float = S.BPM, cfg: dict | None = None, pron_path: Path | None = None,
              section: str | None = None, show_grid: bool = False) -> dict:
    from .align import lint_sheet
    from .pron import cmu_status
    S.configure(cfg or {})
    S.load_pron(pron_path)
    secs = S.score_text(text, section, bpm)
    fl = [(n, m, f) for n, m, f in S.flow_text(text) if not section or section.lower() in n.lower()]
    flows = {name: f for name, _, f in fl}
    grooves = {g["section"]: g for g in S.groove_text(text)}
    human = S.report(secs, show_grid, bpm)
    if fl:
        human += "\n\n-- flow (spoken verses: each line in a two-bar slot; 10-13 syllables, rhyme on the beat-4 word) --"
        human += S.flow_report(fl, show_grid)
    out_secs, n_err, n_warn, scores, fixed_lines = [], 0, 0, [], {}
    for s in secs:
        f = flows.get(s["section"])
        fmap = {x["text"]: x for x in (f["lines"] if f else [])}
        lines = []
        for r in s["lines"]:
            lints = [{"level": LEVEL[lv], "msg": m} for lv, m in r.get("lint", [])]
            n_err += sum(1 for x in lints if x["level"] == "error")
            n_warn += sum(1 for x in lints if x["level"] == "warn")
            fx, fixed = S.fixes(r["text"])
            if fx:
                fixed_lines[r["text"]] = fixed
            row = _clean(r)
            row["lint"] = lints
            row["fixes"] = fx
            if "score" in r:
                scores.append(r["score"])
            fr = fmap.get(r["text"])
            if fr:
                row["flow"] = {k: fr[k] for k in ("fit", "dens", "rhythm", "cad", "shape", "figure", "grid", "bars",
                                                  "stretch", "rk", "stress")}
                row["flow"]["why"] = S.flow_why(fr, f["c"])
            lines.append(row)
        g = grooves.get(s["section"])
        out_secs.append({"section": s["section"], "mode": s["mode"], "budget": s["budget"], "est_bars": s["est_bars"],
                         "syllables": s["syl"], "scheme": s["scheme"],
                         "flow": {k: v for k, v in f.items() if k != "lines"} if f else None,
                         "groove": g["groove"] if g else None, "lines": lines})
    sheet = lint_sheet([ln for _, _, _, ls in S.parse(text) for ln in ls])
    sheet_err = [p for p in sheet if p["level"] == "error"]
    n_err += len(sheet_err)
    if sheet_err:
        human = ("-- alignment sheet: must fix before slop analyze (the aligner can only place spelled-out words) --\n" +
                 "\n".join(f"  ERROR \"{p['text']}\": {p['msg']}" + (f"\n    -> \"{p['fix']}\"" if p.get("fix") else "")
                           for p in sheet_err) +
                 "\n  (write the on-screen spelling in lyrics/display.txt as \"TEXT|n\" tokens, e.g. +25%|4)\n\n" + human)
    tot = [f["flow"] for f in flows.values()]
    summary = {"lines": sum(len(s["lines"]) for s in out_secs), "errors": n_err, "warnings": n_warn,
               "sheet_errors": len(sheet_err),
               "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
               "song_flow": round(sum(tot) / len(tot)) if tot else None, "dictionary": cmu_status()}
    if fixed_lines:
        human += "\n\n-- mechanical fixes for the sung sheet --\n" + "\n".join(f"  {a}\n    -> {b}" for a, b in fixed_lines.items())
    human += (f"\n\n{summary['lines']} lines · {n_err} errors · {n_warn} warnings · mean line score {summary['mean_score']}"
              f" · song flow {summary['song_flow']} · {summary['dictionary']}")
    return {"sections": out_secs, "sheet": sheet, "summary": summary, "fixed": fixed_lines, "text": human}


def write_fixed(path: Path, fixed: dict[str, str]) -> Path:
    src = Path(path).read_text(encoding="utf-8").splitlines()
    out = [fixed.get(ln.strip(), ln) for ln in src]
    dst = Path(path).with_name(Path(path).stem + ".fixed" + Path(path).suffix)
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    return dst


def fix(pdir: Path, word: int | None = None, line: int | None = None, t0: float | None = None, t1: float | None = None,
        shift: float | None = None, note: str | None = None) -> dict:
    """Manual timing: one word (--word I with --t0/--t1 or --shift) or a whole line (--line L, 1-based, with --shift or
    --t0 to move its first word there). Marks the words src "manual" (kept by later `slop analyze` runs)."""
    from .merge import finish
    paths = Paths(pdir)
    W = read_json(paths.words)
    if not W:
        raise SlopError(f"no analysis/words.json - run `{project_cmd(pdir, 'analyze')}` first")
    words = W["words"]
    if (word is None) == (line is None):
        raise SlopError("pass exactly one of --word I (0-based word index from words.json/report) or --line L (1-based)")
    if word is not None:
        if not 0 <= word < len(words):
            raise SlopError(f"--word {word} is outside 0..{len(words) - 1}")
        targets = [words[word]]
    else:
        targets = [w for w in words if w["line"] == line - 1]
        if not targets:
            raise SlopError(f"--line {line}: no such lyric line (1..{len(W['lines'])})")
    if shift is None and t0 is None and t1 is None:
        raise SlopError("give --t0/--t1 (seconds) or --shift (seconds, + later / - earlier)")
    from .common import song_duration
    dur = song_duration(paths)

    def check(a: float | None, b: float | None, what: str) -> None:
        lim = f"{dur:.2f}" if dur else "the song's end"
        if a is None or b is None or not (0 <= a < b) or (dur is not None and b > dur + 1e-6):
            raise SlopError(f"bad times for {what}: {a} - {b}. Need 0 <= t0 < t1 <= {lim} s (song seconds)"
                            + (" - a --shift must keep every word of the line inside the song" if shift is not None else ""))
    if line is not None and t1 is not None:
        raise SlopError("for a whole line use --shift or --t0 (where its first word should start)")
    changed = []
    if word is not None and shift is None:
        w = targets[0]
        a = t0 if t0 is not None else w["t0"]
        if a is None or (t1 is None and w["t0"] is None):
            raise SlopError(f"word {w['i']} \"{w['w']}\" has no timing yet: give both --t0 and --t1")
        b = t1 if t1 is not None else (a + ((w["t1"] - w["t0"]) if w["t0"] is not None else 0.3) if a is not None else None)
        check(a, b, f"word {w['i']} \"{w['w']}\"")
        w.update(t0=round(a, 3), t1=round(b, 3))
        changed.append(w)
    else:
        if shift is None:
            first = next((w for w in targets if w["t0"] is not None), None)
            if first is None:
                raise SlopError("the line has no timed word to move; fix words one by one with --word")
            shift = t0 - first["t0"]
        timed = [w for w in targets if w["t0"] is not None]
        if not timed:
            raise SlopError("no timed word to shift: give --word N --t0 S --t1 S for each word")
        for w in timed:
            check(w["t0"] + shift, w["t1"] + shift, f"word {w['i']} \"{w['w']}\" shifted by {shift:+.2f} s")
        for w in timed:
            w.update(t0=round(w["t0"] + shift, 3), t1=round(w["t1"] + shift, 3))
            changed.append(w)
    for w in changed:
        w["src"], w["conf"] = "manual", 1.0
        if note:
            w["note"] = note
    lines = [L["text"] for L in W["lines"]]
    new = finish(words, lines, W.get("conf_min", 0.5))
    W.update(new)
    write_json(paths.words, W)
    sec_note, board = "", None
    if paths.beats.exists() and paths.song.exists():
        from .sections import build as build_sections, has_tags
        if has_tags(paths.lyrics):                 # tagged sections start at their first word: follow the fix
            old = list((read_json(paths.beats) or {}).get("sections") or [])
            try:
                if build_sections(pdir).get("status") == "done":
                    from .overrides import board_check, board_text, section_sig
                    new = (read_json(paths.beats) or {}).get("sections") or []
                    if section_sig(old) != section_sig(new):
                        sec_note = " Sections re-placed from the lyric tags (" + ", ".join(
                            f"{n}@{t:.2f}s" for n, t in section_sig(new)) + ")."
                        if old:
                            board = board_check(pdir, "lyrics fix moved the tagged sections" + sec_note, old, new)
                            sec_note += board_text(board)
            except SlopError as e:
                sec_note = f" (sections not rebuilt: {e})"
    from . import report
    rep = report.write(pdir)
    urgent = [g for g in rep["groups"] if g["urgent"]]
    return {"changed": [{"i": w["i"], "w": w["w"], "line": w["line"] + 1, "t0": w["t0"], "t1": w["t1"]} for w in changed],
            "ear_check_left": len(urgent), "board": board,
            "text": "fixed " + ", ".join(f"#{w['i']} \"{w['w']}\" {w['t0']:.2f}-{w['t1']:.2f}" for w in changed)
                    + f"; report updated ({len(urgent)} ear-check line(s) left).{sec_note}"
                    + (f"\nlyrics/display.txt exists: re-run `{project_cmd(pdir, 'lyrics display')}`"
                       if paths.display.exists() else "")}

