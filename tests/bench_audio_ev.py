"""Benchmark: the CPU audio chain on a reference song against its shipped engine assets (default "Escape Velocity").

  python tests/bench_audio_ev.py                         # EV_SONG / EV_ASSETS from the environment
  python tests/bench_audio_ev.py --song S.wav --assets DIR --work DIR --downbeat-method all \\
         [--tagged-sheet SUNO_SHEET.txt] [--sections-truth TRUTH.json] [--pickups 0,0.1,0.25,0.5,1]
         [--whisper-words TAKE_WHISPER.json] [--lyrics-check] [--meta META.json] [--out RESULT.json]
  pytest -m slow tests/bench_audio_ev.py                 # the >= 90 % gate on EV
Inputs (flags, else environment; the pytest bench is skipped when they are not set):
  --song / EV_SONG       the song file (the reference take)
  --assets / EV_ASSETS   the shipped engine assets dir holding lyrics.js + beats.js of that video
  --work / SLOP_BENCH_DIR  work dir (default ~/.claudia/bench/<song stem>; cached between runs - delete it for a cold
                         run)
The alignment sheet (lyrics/lyrics.txt) is derived from the shipped assets: lyrics.js holds the lines as displayed
("+25% = -17%", "P(doom)"), beats.js "lines" the same lines spelled as sung ("Plus twenty-five is minus seventeen"); the
sheet is the sung spelling, and every line's word count is checked against the n of lyrics.js's display tokens
("+25%|3 =|1 -17%|2" = 6 sung words), so a sheet that drifted from lyrics.js fails loudly.
--tagged-sheet: a lyric sheet with section tags ([Verse 1 - spoken], [Chorus] ...; e.g. the Suno sheet the take was made
from): its tags are put above the matching sung lines (fuzzy line match in order), so sections come from the tags.
--sections-truth: JSON {"name": [{"name", "t0"}...], ...} - one or more hand-made section tables; each truth boundary
(t0 > 0) is compared with our nearest section start (same bar line = within 0.10 s; within one bar; the mean |offset|
in bars and seconds). Result "sections": the lyric tags at the default snap tolerance + the heuristic alone;
"sections_pickups": the tags per --pickups value (audio.section_pickup_beats, default 0,0.1,0.25,0.5,1), on the
wav2vec2 word times ("w2v|pickup_P") and, after the Whisper variant, on the Whisper-merged times ("whisper|pickup_P").
Whisper fallback variant (measured last, after the wav2vec2-only numbers): --whisper-words FILE replays a transcription
of this take ([{w, t0, t1}] in song time, e.g. the take's own whisper-large-v3 output) through the fallback's cache, free;
--whisper pays for a real one through OpenRouter (needs OPENROUTER_API_KEY; refused above $0.01, ledgered in the work
dir).
--lyrics-check: `slop lyrics check` on the cached transcription of this take (after --whisper-words or --whisper), free;
skipped with a note when nothing is cached - this flag never pays.
--meta: a JSON object merged into the result's "bench_meta" (what the inputs are); the script fills in the date, the
environment and the command with every path replaced by a placeholder (no local paths or host names in the result).
Measures: % of lyrics.js tokens whose t0 is within 0.10 s of ours (target >= 90 %), the same per sung word against
beats.js words, and per downbeat method (kick, harmony, auto) our beats/downbeats against beats.js (% within 10/30 ms,
the bar phase relative to the shipped bars, tempo start/end); section starts per pickup setting. Money: only --whisper
pays (<= $0.01, ledgered); every other measurement, --whisper-words and --lyrics-check included, is free.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

METHODS = ("kick", "harmony", "auto")
PICKUPS = (0.0, 0.1, 0.25, 0.5, 1.0)
PATH_FLAGS = {"--song": "SONG", "--assets": "ASSETS_DIR", "--work": "WORK", "--tagged-sheet": "TAGGED_SHEET",
              "--sections-truth": "TRUTH.json", "--whisper-words": "TAKE_WHISPER.json", "--out": "RESULT.json",
              "--meta": "META.json"}


def _js(path: Path, open_ch: str, close_ch: str):
    t = path.read_text(encoding="utf-8")
    return json.loads(t[t.index(open_ch):t.rstrip().rstrip(";").rindex(close_ch) + 1])


def _defaults() -> tuple[Path | None, Path | None, Path]:
    song = os.environ.get("EV_SONG")
    assets = os.environ.get("EV_ASSETS")
    work = Path(os.environ.get("SLOP_BENCH_DIR") or Path.home() / ".claudia/bench/ev")
    return (Path(song) if song else None), (Path(assets) if assets else None), work


def available() -> bool:
    song, assets, _ = _defaults()
    return bool(song and assets and song.exists() and (assets / "lyrics.js").exists() and (assets / "beats.js").exists())


def derive_sheet(assets: Path) -> tuple[list[str], list[dict], dict]:
    from slop.audio.align import split_words
    LY = [x for x in _js(assets / "lyrics.js", "[", "]") if x["kind"] == "lyric"]
    B = _js(assets / "beats.js", "{", "}")
    lines = B["lines"]
    for x in LY:
        n = sum(t.get("n", 1) for t in x["tokens"])
        sung = split_words(lines[x["line"]])
        if n != len(sung):
            raise AssertionError(f"line {x['line']}: display tokens span {n} words, sung sheet has {len(sung)}: {lines[x['line']]}")
    return lines, LY, B


def _nrm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def tag_sheet(lines: list[str], tagged: Path) -> tuple[list[str], dict]:
    """The sung lines with the section tags of `tagged` above the lines that start each tagged block. Lines of the
    tagged sheet are matched to the sung lines in order (difflib ratio >= 0.6, looking up to 4 lines ahead); unmatched
    lines (notes, refs, lines the take dropped) are skipped. Tags with no lyric lines ([End]) keep their place."""
    from slop.audio.sections import tag_kind
    raw = tagged.read_text(encoding="utf-8").splitlines()
    tags_before: dict[int, list[str]] = {}
    pending: list[str] = []
    j, matched = 0, 0
    for ln in raw:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("["):
            if tag_kind(s):
                pending.append(s)
            continue
        best = None
        for k in range(j, min(len(lines), j + 5)):
            r = difflib.SequenceMatcher(None, _nrm(s), _nrm(lines[k])).ratio()
            if r >= 0.6 and (best is None or r > best[1]):
                best = (k, r)
                if r > 0.95:
                    break
        if best is None:
            continue
        k = best[0]
        if pending:
            tags_before.setdefault(k, []).extend(pending)
            pending = []
        matched += 1
        j = k + 1
    out = []
    for k, ln in enumerate(lines):
        out += tags_before.get(k, [])
        out.append(ln)
    out += pending
    return out, {"tagged_lines_matched": matched, "tags": sum(len(v) for v in tags_before.values()) + len(pending)}


def compare_words(words: list[dict], LY: list[dict], B: dict) -> dict:
    by_line: dict[int, list[dict]] = {}
    for w in words:
        by_line.setdefault(w["line"], []).append(w)
    d_tok = []
    for x in LY:
        ws, k = by_line.get(x["line"], []), 0
        for tk in x["tokens"]:
            n = tk.get("n", 1)
            if n >= 1 and k < len(ws) and ws[k]["t0"] is not None:
                d_tok.append(abs(ws[k]["t0"] - tk["t0"]))
            k += n
    d_w = [abs(a["t0"] - b["t0"]) for a, b in zip(words, B["words"]) if a["t0"] is not None and b.get("t0") is not None]

    def stats(d):
        d = sorted(d)
        return {"n": len(d), "within_0.02": round(sum(x <= .02 for x in d) / len(d), 4),
                "within_0.10": round(sum(x <= .10 for x in d) / len(d), 4),
                "within_0.25": round(sum(x <= .25 for x in d) / len(d), 4),
                "median": round(d[len(d) // 2], 3), "p90": round(d[int(.9 * (len(d) - 1))], 3), "max": round(d[-1], 3)}
    return {"tokens_vs_lyrics_js": stats(d_tok), "words_vs_beats_js": stats(d_w)}


def compare_beats(mine: dict, B: dict) -> dict:
    import numpy as np
    a, b = np.array(mine["beats"]), np.array(B["beats"])
    d = np.array([np.min(np.abs(a - x)) for x in b])
    da, db = np.array(mine["downbeats"]), np.array(B["downbeats"])
    dd = np.array([np.min(np.abs(da - x)) for x in db])
    dp = np.array([np.min(np.abs(db - x)) for x in da])
    # the shipped bars as a phase of our beats: which k puts our beats[k::4] on the shipped downbeats
    shift = []
    for k in range(4):
        mk = a[k::4]
        shift.append(float(np.mean([np.min(np.abs(mk - x)) <= .030 for x in db])) if len(mk) else 0.0)
    k_best = int(np.argmax(shift))
    votes = mine.get("downbeat_votes") or {}
    H = votes.get("harmony") or {}
    return {"beats_mine": len(a), "beats_shipped": len(b), "beat_within_10ms": round(float(np.mean(d <= .010)), 4),
            "shipped_downbeats_are_our_phase": k_best, "shipped_downbeats_on_that_phase": round(shift[k_best], 4),
            "our_phase_minus_shipped_beats": (int(mine.get("downbeat_phase", 0)) - k_best) % 4,
            "downbeat_method": mine.get("downbeat_method"),
            "beat_within_30ms": round(float(np.mean(d <= .030)), 4), "beat_median_ms": round(float(np.median(d)) * 1000, 2),
            "downbeat_within_30ms": round(float(np.mean(dd <= .030)), 4),
            "our_downbeats_on_shipped_30ms": round(float(np.mean(dp <= .030)), 4),
            "kick_vote": {"phase": (votes.get("kick") or {}).get("phase"), "share": (votes.get("kick") or {}).get("share")},
            "harmony_vote": {k: H.get(k) for k in ("phase", "share", "ratio", "significant")},
            "tempo_mine": [mine.get("tempo_start"), mine.get("tempo_end")], "tempo_shipped": [B["tempo_start"], B["tempo_end"]],
            "downbeat_phase_mine": mine.get("downbeat_phase"), "downbeat_phase_shipped": B.get("downbeat_phase")}


def _kind(name: str) -> str:
    from slop.board.common import section_kind
    return section_kind(name)


def compare_sections(secs: list[dict], truth: list[dict], downbeats: list[float]) -> dict:
    """Each truth boundary (t0 > 0) vs our nearest section start; names compared by kind half a bar after the truth
    section's start (the truth tables group sections differently further in)."""
    import numpy as np
    starts = np.array([s["t0"] for s in secs])
    bar = float(np.median(np.diff(downbeats))) if len(downbeats) > 1 else 2.0
    rows, same, one, kinds, offs = [], 0, 0, 0, []
    for k, t in enumerate(truth):
        t0 = float(t["t0"])
        probe = t0 + 0.5 * bar
        ours = next((s for s in secs if s["t0"] <= probe < s["t1"]), secs[-1])
        kind_ok = _kind(ours["name"]) == _kind(t["name"])
        kinds += kind_ok
        row = {"truth": t["name"], "t0": round(t0, 2), "ours_there": ours["name"], "kind_ok": kind_ok}
        if t0 > 0.05:
            j = int(np.argmin(np.abs(starts - t0)))
            dt = float(starts[j] - t0)
            row.update(nearest=round(float(starts[j]), 2), diff_s=round(dt, 2), diff_bars=round(dt / bar, 2))
            same += abs(dt) <= .10
            one += abs(dt) <= bar + .10
            offs.append(abs(dt))
        rows.append(row)
    nb = sum(1 for t in truth if float(t["t0"]) > 0.05)
    return {"boundaries": nb, "same_bar_line": same, "within_one_bar": one, "kind_match": kinds, "sections": len(truth),
            "mean_abs_offset_s": round(float(np.mean(offs)), 3) if offs else None,
            "mean_abs_offset_bars": round(float(np.mean(offs)) / bar, 3) if offs else None,
            "ours": [f"{s['name']}{'?' if s.get('unconfirmed') else ''}@{s['t0']:.2f}" for s in secs], "rows": rows}


def off_in_top(words: list[dict], B: dict, groups: list[dict], top: int) -> list[int]:
    """[lines whose words are > 0.1 s off the shipped timing found in the first `top` ranked ear-check lines, all such]"""
    off = {a["line"] for a, b in zip(words, B["words"])
           if a["t0"] is not None and b.get("t0") is not None and abs(a["t0"] - b["t0"]) > .10}
    ranked = [g["line"] for g in groups if g["urgent"]][:top]
    return [len(off & set(ranked)), len(off)]


def _set_audio(work: Path, **kv) -> None:
    pj = json.loads((work / "project.json").read_text(encoding="utf-8"))
    au = pj.setdefault("audio", {})
    for k, v in kv.items():
        if v is None:
            au.pop(k, None)
        else:
            au[k] = v
    (work / "project.json").write_text(json.dumps(pj), encoding="utf-8")


def whisper_variant(work: Path, LY: list[dict], B: dict, words_file: Path | None, paid: bool) -> dict:
    """Re-align with the Whisper fallback: a replayed transcription (free) or a paid one (<= $0.01)."""
    from slop.audio import analyze
    from slop.audio import whisper as wh
    from slop.audio.common import Paths, fingerprint, read_json, write_json
    paths = Paths(work)
    model = wh.DEFAULT_MODEL
    if words_file is not None:
        ws = [{"w": w["w"], "t0": float(w["t0"]), "t1": float(w["t1"]), **({"conf": w["conf"]} if "conf" in w else {})}
              for w in json.loads(Path(words_file).read_text(encoding="utf-8"))]
        dur = float((read_json(paths.beats) or {}).get("duration") or max(w["t1"] for w in ws) + 1)
        plan = [[0.0, round(dur, 2)]]
        write_json(wh.cache_path(paths, model), {"model": model, "vocals": fingerprint(paths.stem("vocals")), "plan": plan,
                                                 "windows": {wh._wkey(*plan[0]): {"words": ws, "cost_usd": 0.0}},
                                                 "at": "replay#1"})
        how = f"replayed {Path(words_file).name} ({len(ws)} words), free"
    else:
        est = wh.estimate_usd(wh.plan_windows(wh.vocal_env(paths.stem("vocals"))), model)
        if est > 0.01:
            raise SystemExit(f"the Whisper variant would cost ~${est:.4f} > $0.01: refused")
        how = f"paid through OpenRouter (estimate ${est:.4f})"
    t = time.monotonic()
    r = analyze.run(work, ["align"], whisper_fallback=True, yes=True, heartbeat=0)
    W = read_json(paths.words)
    a = r["steps"]["align"]
    return {"how": how, "seconds": round(time.monotonic() - t, 1), "alignment": compare_words(W["words"], LY, B),
            "sources": W.get("stats"), "whisper": W.get("whisper"), "status": a.get("status")}


def pickup_sweep(work: Path, truth: dict, pickups: tuple[float, ...], downbeats: list[float], label: str) -> dict:
    """Sections from the lyric tags per snap tolerance, on the word times words.json holds now."""
    from slop.audio import sections
    from slop.audio.common import Paths, read_json
    paths = Paths(work)
    W = read_json(paths.words) or {}
    out = {}
    for pk in pickups:
        _set_audio(work, section_pickup_beats=pk)
        sections.build(work, force=True)
        S = read_json(paths.beats)
        out[f"{label}|pickup_{pk:g}"] = {"words": W.get("stats"), "from": S.get("sections_from"),
                                         **{name: compare_sections(S["sections"], tt, downbeats)
                                            for name, tt in truth.items()}}
    _set_audio(work, section_pickup_beats=None)
    sections.build(work, force=True)
    return out


def lyrics_check_block(work: Path) -> dict:
    """`slop lyrics check` on the CACHED transcription only (never pays): what it proposes on this take."""
    from slop.audio import check
    from slop.audio import whisper as wh
    from slop.audio.common import Paths
    if not wh.find_cached(Paths(work), None):
        return {"skipped": "no cached transcription of this vocal stem (this flag never pays)"}
    r = check.check(work)
    if r.get("paid"):                                   # cannot happen with a cache; never hide it if it does
        raise SystemExit(f"lyrics check paid ${r.get('cost_usd')}: unexpected")
    rows = r["lines"]
    reasons = sorted({w.split(":")[0] for x in rows for w in x.get("why", [])})
    return {"lines": len(rows), "summary": r["summary"],
            "proposals": {k: len(v) for k, v in r["proposals"].items()},
            "likely_lines": r["proposals"]["likely"], "unsure_lines": r["proposals"]["unsure"],
            "unsure_reasons": reasons, "extra_vocals": len(r.get("extra_vocals") or []), "cost_usd": r["cost_usd"]}


def bench_meta(argv: list[str] | None, extra: dict | None, out: dict) -> dict:
    """date, environment and the command (every path replaced by a placeholder), plus the --meta descriptions."""
    args, it = [], iter(argv if argv is not None else sys.argv[1:])
    for a in it:
        flag = a.split("=", 1)[0]
        if flag in PATH_FLAGS:
            args.append(f"{flag} {PATH_FLAGS[flag]}")
            if "=" not in a:
                next(it, None)
        else:
            args.append(a)
    meta = {"date": time.strftime("%Y-%m-%d"),
            "env": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}, {os.cpu_count()} CPU "
                   "threads",
            "command": "python tests/bench_audio_ev.py " + " ".join(args),
            "song_duration_s": out.get("duration")}
    meta.update(extra or {})
    return meta


def run(force: bool = False, song: Path | None = None, assets: Path | None = None, work: Path | None = None,
        methods: tuple[str, ...] = ("kick",), tagged: Path | None = None, truth: dict | None = None,
        pickups: tuple[float, ...] = PICKUPS, whisper_words: Path | None = None,
        whisper_paid: bool = False, lyrics_check: bool = False) -> dict:
    from slop.audio import analyze, ingest, sections
    from slop.audio.common import Paths, read_json
    d_song, d_assets, d_work = _defaults()
    song, assets = song or d_song, assets or d_assets
    work = work or (d_work if not song or song == d_song else Path.home() / ".claudia/bench" / re.sub(r"\W+", "-", song.stem).strip("-").lower())
    lines, LY, B = derive_sheet(assets)
    sheet, tag_info = (tag_sheet(lines, tagged) if tagged else (lines, None))
    work.mkdir(parents=True, exist_ok=True)
    (work / "project.json").write_text(json.dumps({"name": "bench", "title": "audio bench",
                                                   "audio": {"downbeat_method": methods[0]}}), encoding="utf-8")
    paths = Paths(work)
    paths.lyrics.parent.mkdir(parents=True, exist_ok=True)
    paths.lyrics.write_text("\n".join(sheet) + "\n", encoding="utf-8")
    t = time.monotonic()
    ing = ingest.ingest(work, song)
    t_ing = time.monotonic() - t
    t = time.monotonic()
    res = analyze.run(work, ["stems", "align", "beats", "hits", "sections"], force=force, no_whisper=True, heartbeat=0)
    t_an = time.monotonic() - t
    W = read_json(paths.words)
    out = {"song": song.name, "duration": ing.get("duration"), "ingest_s": round(t_ing, 1), "analyze_s": round(t_an, 1),
           "steps": {k: {kk: v.get(kk) for kk in ("status", "seconds", "separate_s", "emissions_s", "viterbi_s",
                                                 "mean_conf", "conf_ge_05", "emissions_cached")} for k, v in res["steps"].items()},
           "alignment": compare_words(W["words"], LY, B), "sources": W.get("stats"),
           "ear_check": dict(__import__("collections").Counter(i["kind"] for i in res["ear_check"])),
           "ear_check_lines": {"urgent": sum(1 for g in res["ear_check_lines"] if g["urgent"]),
                               "all": len(res["ear_check_lines"]),
                               "off_lines_in_top20": off_in_top(W["words"], B, res["ear_check_lines"], 20)},
           "hits": {k: len(v) for k, v in (read_json(paths.hits) or {}).items() if isinstance(v, list)},
           "downbeats": {}}
    if tag_info:
        out["tagged_sheet"] = tag_info
    for m in methods:
        _set_audio(work, downbeat_method=m)
        t = time.monotonic()
        r = analyze.run(work, ["beats"], no_whisper=True, heartbeat=0)
        mine = read_json(paths.beats)
        out["downbeats"][m] = {**compare_beats(mine, B), "rebuilt": sorted(r["steps"]), "seconds": round(time.monotonic() - t, 1)}
    out["beats"] = out["downbeats"][methods[0]]
    # sections: lyric tags (per pickup setting) and the heuristic, on the first method's bars
    _set_audio(work, downbeat_method=methods[0])
    analyze.run(work, ["beats"], no_whisper=True, heartbeat=0)
    mine = read_json(paths.beats)
    if truth:
        # "tags" at the shipped default tolerance, "heuristic" with no tags; the tolerance sweep in sections_pickups
        sec = {}
        variants = [("tags", None, True)] if tagged else []
        variants.append(("heuristic", None, False))
        for label, p, tags in variants:
            _set_audio(work, section_pickup_beats=p)
            if not tags:
                paths.lyrics.write_text("\n".join(lines) + "\n", encoding="utf-8")
            t = time.monotonic()
            sections.build(work, force=True)
            S = read_json(paths.beats)
            sec[label] = {"from": S.get("sections_from"), "seconds": round(time.monotonic() - t, 1),
                          "pickup_beats": sections.PICKUP_BEATS if tags else None,
                          **{name: compare_sections(S["sections"], tt, mine["downbeats"]) for name, tt in truth.items()}}
            if not tags:
                paths.lyrics.write_text("\n".join(sheet) + "\n", encoding="utf-8")
        _set_audio(work, section_pickup_beats=None)
        sections.build(work, force=True)
        out["sections"] = sec
        if tagged:
            out["sections_pickups"] = pickup_sweep(work, truth, pickups, mine["downbeats"], "w2v")
    if whisper_words is not None or whisper_paid:
        out["whisper"] = whisper_variant(work, LY, B, whisper_words, whisper_paid)
        if truth and tagged:
            out["sections_pickups"].update(pickup_sweep(work, truth, pickups, mine["downbeats"], "whisper"))
    if lyrics_check:
        out["lyrics_check"] = lyrics_check_block(work)
    (work / "bench.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


try:
    import pytest

    @pytest.mark.slow
    @pytest.mark.skipif(not available(), reason="EV song or shipped assets not available")
    def test_bench_ev():
        out = run()
        print(json.dumps(out, indent=1))
        assert out["alignment"]["tokens_vs_lyrics_js"]["within_0.10"] >= 0.90
        assert out["beats"]["beat_within_30ms"] >= 0.90
except ImportError:  # running as a plain script without pytest
    pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="audio benchmark against a video's shipped engine assets")
    ap.add_argument("--song", type=Path, help="the song file (default $EV_SONG)")
    ap.add_argument("--assets", type=Path, help="the shipped engine assets dir with lyrics.js + beats.js (default $EV_ASSETS)")
    ap.add_argument("--work", type=Path, help="work dir (cached between runs)")
    ap.add_argument("--downbeat-method", default="kick", choices=[*METHODS, "all"],
                    help="downbeat vote(s) to measure; all = kick, harmony, auto")
    ap.add_argument("--tagged-sheet", type=Path, help="a lyric sheet with section tags to put above the sung lines")
    ap.add_argument("--sections-truth", type=Path, help='JSON {"table name": [{"name", "t0"}...]} hand-made sections')
    ap.add_argument("--whisper-words", type=Path, help="replay this transcription as the Whisper fallback (free)")
    ap.add_argument("--whisper", action="store_true", help="measure the paid Whisper fallback too (<= $0.01)")
    ap.add_argument("--pickups", default=",".join(f"{x:g}" for x in PICKUPS),
                    help="snap tolerances (beats) to sweep for the tag sections, e.g. 0,0.1,0.25,0.5,1")
    ap.add_argument("--lyrics-check", action="store_true",
                    help="run `slop lyrics check` on the cached transcription (free; skipped when nothing is cached)")
    ap.add_argument("--meta", type=Path, help="JSON object merged into the result's bench_meta (what the inputs are)")
    ap.add_argument("--out", type=Path, help="also write the result JSON here")
    ap.add_argument("--force", action="store_true", help="redo every analysis step (cold run)")
    a = ap.parse_args(argv)
    song = a.song or _defaults()[0]
    assets = a.assets or _defaults()[1]
    if not (song and assets and song.exists() and (assets / "lyrics.js").exists() and (assets / "beats.js").exists()):
        print("give --song FILE and --assets DIR (with lyrics.js + beats.js), or set EV_SONG / EV_ASSETS")
        return 2
    methods = METHODS if a.downbeat_method == "all" else (a.downbeat_method,)
    truth = json.loads(a.sections_truth.read_text(encoding="utf-8")) if a.sections_truth else None
    pickups = tuple(float(x) for x in a.pickups.split(",") if x.strip())
    out = run(force=a.force, song=song, assets=assets, work=a.work, methods=methods, tagged=a.tagged_sheet, truth=truth,
              pickups=pickups, whisper_words=a.whisper_words, whisper_paid=a.whisper, lyrics_check=a.lyrics_check)
    extra = json.loads(a.meta.read_text(encoding="utf-8")) if a.meta else None
    out = {"bench_meta": bench_meta(argv, extra, out), **out}
    txt = json.dumps(out, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(txt + "\n", encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
