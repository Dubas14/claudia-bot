"""analysis/report.md: the human summary of the analysis + the EAR-CHECK list (what to listen to before trusting the
timing). Folds in the CLODYSSEY make_timeline.py outputs (per-line confidence label, no-vocal gaps >= 2 s, per-bar stem
energy 0-9) - computed from the stems directly (the old script needed scratch/*.f32 files that nothing wrote).

Ear-check items (ear_check(), flat, each with a listen command and a fix command):
  letters  a sheet line with no letters (cannot be aligned)       (fix the sheet)
  missing  a word/line without timing                             (must fix)
  order    a word that starts before the previous word            (must fix)
  gap      > 1 s between two words of the same line               (EV's "Look" sat 2.5 s early on a delay throw)
  verylow  words with confidence < 0.1                            (on the EV take: 10 of the 12 words that were off)
  length   a word longer than 1.2 s
  lowconf  other words with confidence < 0.5, or timed by Whisper/interpolation (+-0.2 s) - check if time allows
Calibrated on the EV take against its shipped (hand-checked) timing: "word on near-silence" and "shorter than 40 ms"
flags were dropped - every one of them was a correct word.
The report groups the items PER LYRIC LINE (one listen per line) and ranks the lines: letters/missing/order first, then
the line's lowest word confidence (on EV this puts 7 of the 8 lines that really were off in the top 20 of 45, against
5 of 8 in time order). The top LISTEN_TOP (20) lines are the list; the rest go to an appendix, and lines that only have
"lowconf" words to "if time allows". Every command carries `--project <name>` (the bot may run it from any folder);
listen excerpts go to analysis/listen/ (`slop audio window ... --listen`), never into audio/windows/ (clip windows).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from slop.config import load_project

from .common import STEMS, Paths, load_mono, read_json

PRIORITY = {"letters": 0, "missing": 1, "order": 2, "gap": 3, "verylow": 4, "length": 5, "lowconf": 6}
VERYLOW = 0.1
LISTEN_TOP = 20


def stem_env100(paths: Paths) -> dict[str, np.ndarray]:
    """RMS per 10 ms of each stem (unnormalised), cached in analysis/cache/env100.npz per stem fingerprint - decoding
    four float stems costs seconds, and the report is rewritten after every `slop lyrics fix`."""
    from .common import fingerprint, write_json
    have = [s for s in STEMS if paths.stem(s).exists()]
    key = fingerprint(*(paths.stem(s) for s in have))
    cp, meta = paths.cache / "env100.npz", paths.cache / "env100.json"
    if cp.exists() and (read_json(meta, {}) or {}).get("key") == key:
        with np.load(cp) as z:
            return {s: z[s] for s in have if s in z}
    sr, hop = 22050, 220
    out = {}
    for s in have:
        v = load_mono(paths.stem(s), sr)
        n = len(v) // hop
        out[s] = np.sqrt((v[: n * hop].reshape(n, hop).astype(np.float64) ** 2).mean(1)).astype(np.float32)
    paths.cache.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cp, **out)
    write_json(meta, {"key": key, "fps": 100})
    return out


def _cmd(pdir: Path | None, rest: str) -> str:
    if pdir is None:
        return f"slop {rest}"
    from .common import project_cmd
    return project_cmd(pdir, rest)


def ear_check(words: dict | None, sheet: list[str] | None, R: np.ndarray | None = None, conf_min: float = 0.5,
              pdir: Path | None = None) -> list[dict]:
    items: list[dict] = []
    import re
    for li, ln in enumerate(sheet or []):
        if not re.search(r"[A-Za-z]", ln):
            items.append({"kind": "letters", "line": li, "t0": None, "t1": None,
                          "msg": f"line {li + 1} \"{ln}\" has no letters: write it as sung in lyrics/lyrics.txt"})
    if not words:
        return items
    W = words["words"]
    for L in words["lines"]:
        if L["t0"] is None and L.get("n"):
            items.append({"kind": "missing", "line": L["line"], "t0": None, "t1": None,
                          "msg": f"line {L['line'] + 1} \"{L['text']}\" has no timing"})
    prev = None
    for w in W:
        if w["t0"] is None:
            items.append({"kind": "missing", "line": w["line"], "word": w["i"], "t0": None, "t1": None,
                          "msg": f"word {w['i']} \"{w['w']}\" (line {w['line'] + 1}) has no timing"})
            continue
        if prev is not None and w["t0"] < prev["t0"] - 0.05:
            items.append({"kind": "order", "line": w["line"], "word": w["i"], "t0": w["t0"], "t1": w["t1"],
                          "msg": f"word {w['i']} \"{w['w']}\" starts at {w['t0']:.2f} s, before word {prev['i']} "
                                 f"\"{prev['w']}\" ({prev['t0']:.2f} s)"})
        dur = w["t1"] - w["t0"]
        if w["src"] != "manual" and dur > 1.2:
            items.append({"kind": "length", "line": w["line"], "word": w["i"], "t0": w["t0"], "t1": w["t1"],
                          "msg": f"word {w['i']} \"{w['w']}\" lasts {dur:.2f} s"})
        prev = w
    for g in words.get("gaps", []):
        if g.get("in_line"):
            a = W[g["after_word"]]
            items.append({"kind": "gap", "line": a["line"], "word": g["after_word"], "t0": g["t0"], "t1": g["t1"],
                          "msg": f"{g['t1'] - g['t0']:.2f} s gap inside line {a['line'] + 1} after \"{a['w']}\" "
                                 f"({g['t0']:.2f}-{g['t1']:.2f} s): a delay throw or an ad-lib taken as a word?"})
    for kind, pick in (("verylow", lambda w: w["src"] == "w2v" and w["conf"] < VERYLOW),
                       ("lowconf", lambda w: w["src"] in ("whisper", "interp") or
                        (w["src"] == "w2v" and VERYLOW <= w["conf"] < conf_min))):
        by_line: dict[int, list[dict]] = {}
        for w in W:
            if w["t0"] is not None and pick(w):
                by_line.setdefault(w["line"], []).append(w)
        for li, ws in sorted(by_line.items()):
            items.append({"kind": kind, "line": li, "words": [w["i"] for w in ws],
                          "t0": min(w["t0"] for w in ws), "t1": max(w["t1"] for w in ws),
                          "msg": f"line {li + 1}: " + ", ".join(f"#{w['i']} \"{w['w']}\" {w['t0']:.2f}s ({w['src']} {w['conf']:.2f})"
                                                                for w in ws[:8]) + (" ..." if len(ws) > 8 else "")})
    items.sort(key=lambda x: (PRIORITY[x["kind"]], x.get("t0") if x.get("t0") is not None else -1))
    for it in items:
        if it.get("t0") is not None:
            a, b = max(0.0, it["t0"] - 1.5), it["t1"] + 1.5
            it["listen"] = _cmd(pdir, f"audio window chk-l{it['line'] + 1} --t0 {a:.2f} --t1 {b:.2f} --mode mix --listen")
        if "word" in it:
            it["fix"] = _cmd(pdir, f"lyrics fix --word {it['word']} --t0 <start> --t1 <end>")
        elif it["kind"] in ("lowconf", "verylow", "missing"):
            it["fix"] = _cmd(pdir, f"lyrics fix --line {it['line'] + 1} --shift <seconds>") + "  (or --word N --t0 --t1)"
    return items


def _short(g: dict) -> list[str]:
    """the group's messages without their own "line N: " prefix (the list line names the line already)."""
    pre = f"line {g['line'] + 1}: "
    return [m[len(pre):] if m.startswith(pre) else m for m in g["msgs"]]


def group_items(items: list[dict], words: dict | None, pdir: Path | None = None) -> list[dict]:
    """One entry per lyric line: {line, kinds, urgent, t0, t1, min_conf, msgs, listen, fix}, ranked (module docstring)."""
    W = (words or {}).get("words", [])
    texts = {L["line"]: L["text"] for L in (words or {}).get("lines", [])}
    by: dict[int, list[dict]] = {}
    for it in items:
        by.setdefault(it["line"], []).append(it)
    out = []
    for li, its in by.items():
        kinds = sorted({i["kind"] for i in its}, key=PRIORITY.get)
        urgent = any(k != "lowconf" for k in kinds)
        ts = [(i["t0"], i["t1"]) for i in its if i.get("t0") is not None]
        lw = [w for w in W if w["line"] == li and w.get("src") != "manual"]
        minc = min((float(w.get("conf") or 0.0) for w in lw), default=1.0)
        meanc = float(np.mean([float(w.get("conf") or 0.0) for w in lw])) if lw else 1.0
        g = {"line": li, "text": texts.get(li), "kinds": kinds, "urgent": urgent, "min_conf": round(minc, 3),
             "t0": min((a for a, _ in ts), default=None), "t1": max((b for _, b in ts), default=None),
             "msgs": [i["msg"] for i in sorted(its, key=lambda x: PRIORITY[x["kind"]])]}
        if g["t0"] is not None:
            a, b = max(0.0, g["t0"] - 1.5), g["t1"] + 1.5
            g["listen"] = _cmd(pdir, f"audio window chk-l{li + 1} --t0 {a:.2f} --t1 {b:.2f} --mode mix --listen")
        single = [i for i in its if "word" in i]
        if len(its) == 1 and single:
            g["fix"] = single[0]["fix"]
        elif "letters" in kinds:
            g["fix"] = f"edit line {li + 1} of lyrics/lyrics.txt (write it as sung), then " + \
                _cmd(pdir, "analyze --steps align")
        else:
            g["fix"] = _cmd(pdir, f"lyrics fix --line {li + 1} --shift <seconds>") + \
                "  (or one word: " + _cmd(pdir, "lyrics fix --word N --t0 <start> --t1 <end>") + ")"
        tier = min(PRIORITY[k] for k in kinds)
        g["_key"] = (0 if urgent else 1, tier if tier < 3 else 3, minc, meanc, li)
        out.append(g)
    out.sort(key=lambda g: g.pop("_key"))
    for k, g in enumerate(out, 1):
        g["rank"] = k
    return out


def _kick_click_line(H: dict) -> str:
    kc = H.get("kick_click") or {}
    if str(kc.get("mode")) in ("False", "false", "off", "0"):
        return "- snare/clap onsets on kicks were all kept (`audio.hits.kick_click: false`)"
    if kc.get("backbeat") is not None and str(kc.get("mode")) not in ("True", "true", "on", "1"):
        return (f"- claps/snares on the kick every other beat detected (ratio {kc.get('ratio')}): kept "
                f"{kc.get('kept_on_kicks', 0)} of them; other snare-band onsets within 45 ms of a kick were dropped as "
                "its click. Force with `audio.hits.kick_click: true|false` in project.json.")
    return ("- snare/clap onsets within 45 ms of a kick were dropped as the kick's own click (the original rule). If the "
            "song has claps ON the kicks and the snare list looks too short, set `audio.hits.kick_click: false`.")


def bar_energy(env: dict[str, np.ndarray], downbeats: list[float], dur: float) -> list[dict]:
    """RMS of each stem per bar (bar k = downbeat k .. k+1; bar -1 = the pickup before the first downbeat), scaled 0-9
    of that stem's loudest bar (make_timeline's table)."""
    edges = [0.0] + list(downbeats) + [dur]
    rows = []
    for k in range(len(edges) - 1):
        a, b = int(edges[k] * 100), max(int(edges[k] * 100) + 1, int(edges[k + 1] * 100))
        e = {s: float(np.sqrt(np.mean(x[a:b].astype(np.float64) ** 2))) if len(x[a:b]) else 0.0 for s, x in env.items()}
        rows.append({"bar": k - 1, "t0": round(edges[k], 3), "t1": round(edges[k + 1], 3), "e": e})
    mx = {s: max((r["e"][s] for r in rows), default=0.0) or 1.0 for s in env}
    for r in rows:
        r["lvl"] = {s: min(9, int(9.99 * r["e"][s] / mx[s])) for s in env}
    return rows


SOURCE_LABEL = {"set": "set by the owner", "lyrics-tag": "lyrics tag", "heuristic": "UNCONFIRMED guess"}


def section_table(B: dict, pdir: Path | None, sheet: list[str] | None = None) -> list[str]:
    """The Sections part of report.md: where each name came from; guesses are marked UNCONFIRMED with how to confirm
    each one (sections.confirm_hints: an empty tag line for a no-vocal stretch, a tag above an untagged line, or a full
    `slop song sections --set` list - never a runnable example with made-up values)."""
    from .sections import bar_ref, confirm_hints
    secs = B["sections"]
    down = B.get("downbeats") or []
    P = ["", "## Sections", "", f"From: {B.get('sections_from', 'heuristic')}. Bars count from 0 (bar 0 = the first "
         f"bar line), as in `{_cmd(pdir, 'song bars')}` and `--set NAME@barK`.", "",
         "| section | start | end | bars | --set START | energy | vocals | lyric lines | source |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s in secs:
        b0 = "pickup" if s.get("bar0", 0) < 0 else s.get("bar0")
        ln = f"{s['lines'][0] + 1}-{s['lines'][1] + 1}" if s.get("lines") else ""
        src = SOURCE_LABEL.get(s.get("source") or "heuristic", s.get("source"))
        if s.get("tag"):
            src += f" {s['tag']}"
        name = f"{s['name']} (unconfirmed)" if s.get("unconfirmed") or not s.get("source") else s["name"]
        P.append(f"| {name} | {s['t0']:.2f} | {s['t1']:.2f} | {b0}..{s.get('bar1')} | {s['name']}{bar_ref(s, down)} | "
                 f"{s['energy']:.2f} | {s.get('vocals', 0):.0%} | {ln} | {src} |")
    unconf = [s["name"] for s in secs if s.get("unconfirmed") or not s.get("source")]
    P.append("")
    if unconf:
        P.append(f"UNCONFIRMED: {', '.join(unconf)} - named from energy and vocals only (a guess; the board paces and plans "
                 "clips by these names). Confirm them:")
        P += [f"{k}. {h}" for k, h in enumerate(confirm_hints(B, pdir, sheet), 1)]
    else:
        P.append(f"Change them with `{_cmd(pdir, 'song sections --set NAME@START,...')}` - it REPLACES ALL sections, so "
                 f"list every one (the --set START column gives each one's current start); "
                 f"`{_cmd(pdir, 'song sections --clear')}` goes back to the lyric tags / the guess.")
    P.append("")
    return P


def vocal_gaps(R: np.ndarray, fps: int = 100, min_s: float = 2.0, thr: float = 0.06) -> list[list[float]]:
    if not len(R):
        return []
    hop = fps // 20                                    # 50 ms hops (make_timeline)
    n = len(R) // hop
    r = R[: n * hop].reshape(n, hop).mean(1)
    r = r / (r.max() + 1e-12)
    quiet = r < thr
    gaps, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if (j - i) / 20 >= min_s:
                gaps.append([round(i / 20, 2), round(j / 20, 2)])
            i = j
        else:
            i += 1
    return gaps


def write(pdir: Path, steps: dict | None = None) -> dict:
    from .align import read_sheet
    paths = Paths(pdir)
    B = read_json(paths.beats)
    W = read_json(paths.words)
    H = read_json(paths.hits)
    song = read_json(paths.song_meta, {}) or {}
    try:
        name = load_project(pdir).get("title") or pdir.name
    except Exception:
        name = pdir.name
    sheet = read_sheet(paths.lyrics) if paths.lyrics.exists() else None
    env = stem_env100(paths)
    R = env.get("vocals", np.zeros(0))
    R = R / (R.max() + 1e-12) if len(R) else R
    items = ear_check(W, sheet, None, (W or {}).get("conf_min", 0.5), pdir)
    groups = group_items(items, W, pdir)
    P = [f"# Analysis report: {name}", "", f"_written {time.strftime('%Y-%m-%d %H:%M')} by `slop analyze`_", ""]
    if song:
        lo = song.get("loudness", {})
        P.append(f"**Song** {song.get('source_name', 'audio/song.wav')} - {song.get('duration', 0):.1f} s, "
                 f"{lo.get('lufs_i', '?')} LUFS, true peak {lo.get('true_peak_dbfs', '?')} dBFS.")
        P.append("")
    down = (B or {}).get("downbeats", [])
    if B:
        P += ["## Beat map", "",
              f"- tempo {B.get('tempo_start')} -> {B.get('tempo_end')} BPM (median {B.get('bpm')}); search range "
              f"{B.get('tempo_range')} - if this is half or double the real tempo, set `audio.bpm_hint` in project.json and re-run",
              f"- {len(B['beats'])} beats, {len(down)} downbeats (bars); downbeat phase {B.get('downbeat_phase')} from "
              f"{B.get('downbeat_method', 'kick')} (kick vote per 32-beat block {B.get('phase_blocks')}; second "
              f"opinion, chord changes: phase {((B.get('downbeat_votes') or {}).get('harmony') or {}).get('phase')}, "
              f"blocks {((B.get('downbeat_votes') or {}).get('harmony') or {}).get('blocks')}). If bar lines feel off "
              f"(a drop or a chorus should start on beat 1): `{_cmd(pdir, 'song bars')}` shows each phase, "
              f"`{_cmd(pdir, 'song bars --phase N')}` sets it (N = 0-3; it re-derives the bars in a second, rebuilds "
              "the sections and hits and logs the decision).",
              "- cut on the beat map, never on a fixed BPM.", ""]
        for n in B.get("notes", []):
            P.append(f"- note: {n}")
        if B.get("sections"):
            P += section_table(B, pdir, sheet)
    P += ["## EAR CHECK", ""]
    urgent = [g for g in groups if g["urgent"]]
    later = [g for g in groups if not g["urgent"]]
    if not W:
        P.append("No word timing yet: write the sung lyrics in lyrics/lyrics.txt, then run "
                 f"`{_cmd(pdir, 'analyze --steps align')}`.")
        for g in groups:
            P.append(f"- line {g['line'] + 1}: " + "; ".join(g["msgs"]))
    elif not groups:
        P.append("Nothing flagged. Still listen to one chorus with the lyric overlay before the edit.")
    else:
        nlow = len({i["line"] for i in items if i["kind"] in ("verylow", "lowconf")})
        if nlow and not W.get("whisper"):
            P.append(f"FIRST: {nlow} line(s) have low-confidence words (usually sung or shouted lines). Re-time them with "
                     f"Whisper before listening: `{_cmd(pdir, 'analyze --steps align --whisper-fallback')}` (OpenRouter, "
                     "about $0.002 per song; later runs reuse it for free).")
            P.append("")
        P.append(f"{len(urgent)} line(s) need a listen, most likely wrong first. For each: run `listen` (a mix excerpt "
                 "in analysis/listen/), compare the words with the times in words.json, fix with `fix` (fixes are kept "
                 "when the analysis re-runs).")
        P.append("")
        if urgent:
            P += [f"### Listen first (top {min(LISTEN_TOP, len(urgent))})", ""]
            for g in urgent[:LISTEN_TOP]:
                P.append(f"{g['rank']}. **line {g['line'] + 1}** \"{g.get('text') or ''}\" - {', '.join(g['kinds'])}")
                for m in g["msgs"]:
                    P.append(f"   - {m}")
                if g.get("listen"):
                    P.append(f"   - listen: `{g['listen']}`")
                P.append(f"   - fix: `{g['fix']}`")
        if len(urgent) > LISTEN_TOP:
            P += ["", f"### Appendix: {len(urgent) - LISTEN_TOP} more line(s) to check", ""]
            for g in urgent[LISTEN_TOP:]:
                P.append(f"- {g['rank']}. line {g['line'] + 1} ({', '.join(g['kinds'])}, lowest conf {g['min_conf']:.2f}): "
                         + "; ".join(_short(g)) + (f" - listen: `{g['listen']}`" if g.get("listen") else ""))
        if later:
            P += ["", f"### If time allows: {len(later)} line(s) with low-confidence or Whisper-timed words", ""]
            for g in later:
                P.append(f"- line {g['line'] + 1}: " + "; ".join(_short(g)))
    if W:
        st = W.get("stats", {})
        cf = [w["conf"] for w in W["words"]]
        P += ["", "## Alignment", "",
              f"- {len(W['words'])} words in {len(W['lines'])} lines; sources {st}; mean confidence "
              f"{np.mean(cf):.2f}, {np.mean([c >= 0.5 for c in cf]):.0%} >= 0.5",
              "- conf labels: `w2v` forced alignment >= 0.5 (+-0.05 s); `w2v-low` some words < 0.5; `sung` Whisper "
              "(+-0.2 s); `w2v+sung` mixed; `check` interpolated words; `manual` fixed by hand", "",
              "| # | start | end | bar | conf | section | line |", "|---|---|---|---|---|---|---|"]
        secs = (B or {}).get("sections", [])
        for L in W["lines"]:
            if L["t0"] is None:
                P.append(f"| {L['line'] + 1} | - | - | - | {L['conf']} | | {L['text']} |")
                continue
            bar = int(np.searchsorted(down, L["t0"], side="right")) - 1 if down else ""
            sec = next((s["name"] for s in secs if s["t0"] <= L["t0"] + 0.8 < s["t1"]), "")
            P.append(f"| {L['line'] + 1} | {L['t0']:.2f} | {L['t1']:.2f} | {bar} | {L['conf']} | {sec} | {L['text']} |")
    gaps = vocal_gaps(R)
    if len(R):
        P += ["", "## No vocal for 2 s or more", "",
              (", ".join(f"{a:.1f}-{b:.1f} ({b - a:.1f} s)" for a, b in gaps) or "none") + "", ""]
    if H:
        P += ["## Hits", "", f"- kick {len(H['kick'])}, snare/clap {len(H['snare'])}, hat {len(H['hat'])}; real hits "
              f"{len(H['hits'])} (of {len(H.get('hits_all', []))} peaks); risers {len(H['risers'])}; fills {len(H['fills'])}; "
              f"vocal entries {len(H['vocal_entries'])}",
              "- real hits: " + " ".join(f"{x['t']:.2f}:{x['score']:.2f}" for x in H["hits"]),
              "- add/drop hits with `audio.hits` {\"add\": [[t, strength]], \"drop\": [t]} in project.json",
              _kick_click_line(H), ""]
    if B and down and any(paths.stem(s).exists() for s in STEMS):
        rows = bar_energy(env, down, float(B["duration"]))
        P += ["## Per-bar stem energy", "", "0-9 of each stem's loudest bar: D drums, B bass, O other, V vocals. Bar k starts at downbeat k (from 0; "
              "bar -1 is the pickup before the first bar line).", "",
              "```", " bar   start  D B O V"]
        for r in rows:
            lv = r["lvl"]
            P.append(f"{r['bar']:4d} {r['t0']:7.2f}  {lv.get('drums', '-')} {lv.get('bass', '-')} {lv.get('other', '-')} {lv.get('vocals', '-')}")
        P.append("```")
    if steps:
        P += ["", "## Steps", ""] + [f"- {k}: {v.get('status')}" + (f" ({v.get('seconds')} s)" if v.get("seconds") else "")
                                      for k, v in steps.items()]
    paths.report.parent.mkdir(parents=True, exist_ok=True)
    paths.report.write_text("\n".join(P) + "\n", encoding="utf-8")
    return {"file": str(paths.report), "ear_check": items, "groups": groups, "vocal_gaps": gaps}
