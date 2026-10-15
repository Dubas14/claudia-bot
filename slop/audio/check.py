"""`slop lyrics check`: what the take really sings vs lyrics/lyrics.txt, per line, with proposed fixes.

Why: Lyria and Suno takes change words (a repeated line sung differently, a dropped "the", an extra "yeah", a whole
ad-lib line). The aligner forces the SHEET onto the audio, so a changed word is placed somewhere wrong and nothing
says so. This command transcribes the vocal stem with Whisper (OpenRouter /api/v1/audio/transcriptions, the same
paid, ledgered, budget-checked and cached call as `slop analyze --whisper-fallback`: ~$0.002 per song, free when that
transcription is already cached for this vocal stem, and a later `slop analyze` reuses it for free), aligns the heard
words to the sheet words (difflib over normalised words, digits spelled out, run-together letters split - the merge
module's matching), and reports per lyric line:
  ok            every sheet word heard
  spelling      heard words that SOUND like the sheet's (letters >= 60 % alike: Whisper's spelling of a name; a letter
                sung by name, "pee" for "P"): kept - the aligner needs the words as sung, which the sheet already has
  changed       different words heard: the take may sing something else -> a proposed line
  extra         words heard inside the line that the sheet lacks -> a proposed line
  missing       sheet words not heard while the rest of the line was (a dropped word, or Whisper missed it)
  not-heard     nothing of the line heard (sung/shouted/whispered lines are often missed): listen before changing it
and the "extra vocal" runs heard between lines (an ad-lib or a line missing from the sheet: add it to lyrics.txt or to
lyrics/adlibs.json).
CONFIDENCE (calibrated on a real take where Whisper heard a shouted "TIE ME TO THE MAST!" as "Sonic", "Talk" and "Psych
Do", "P doom" as "pee"/"peak doom", "a" as "the"): a proposal is "likely" unless one of these makes it "unsure":
  shout        the sheet line is in capitals (crowd shouts are misheard most)
  repeat       the same sheet line is heard as written elsewhere in the song (the take sings it; Whisper varies)
  small-words  only articles/pronouns/prepositions/single letters differ
  letter       a letter the sheet spells out ("P", "A G I") was heard as some other word
  echo         the extra words repeat the word(s) just sung (an echo/ad-lib: lyrics/adlibs.json, not the sheet)
  aligned      at least half of the replaced sheet words were placed by wav2vec2 with good confidence (words.json conf
               >= conf_min, when words.json was aligned on this sheet): the audio fits the sheet's words
  half-heard   the heard words are not in the song's sheet and sound partly like the replaced ones (letters 45-60 %
               alike): a garbled mishearing more often than a change
  (calibrated on a replay of the same take: the take sings the sheet as written, so all 9 proposals were Whisper
  errors; "aligned" and "half-heard" catch the one that was still LIKELY - "Peptide rave in" heard as "Hatsai Raven",
  whose words wav2vec2 placed at 0.04 / 0.81 / 0.59 and whose letters are 58 % alike - leaving 0 likely of 9)
Writes analysis/lyrics-check.json. --write writes lyrics/lyrics.proposed.txt (the "likely" proposals applied; lyrics.txt
untouched); --apply applies the "likely" proposals to lyrics/lyrics.txt; --apply-lines 14,25 applies exactly those
lines' proposals (any confidence; after the owner listened). Every apply first copies the sheet to a NEW timestamped
backup (lyrics/lyrics.txt.<YYYYmmdd-HHMMSS>.bak; an older backup is never overwritten, so the owner's original stays)
and names it. A proposed line keeps the sheet's own characters outside the changed words (curly apostrophes, accents).
Then re-run `slop analyze --steps align`. The proposals are for the owner to confirm, never automatic.
"""
from __future__ import annotations

import difflib
import re
import shutil
import time
from pathlib import Path

from slop.config import SlopError
from slop.util import is_lyric_noise

from . import whisper as wh
from .align import fold, read_sheet, sheet_words
from .common import Paths, audio_cfg, project_cmd, write_json
from .merge import norm, whisper_tokens

SIMILAR = 0.6          # letter similarity at or above which a heard word is a spelling of the sheet word
HALF_HEARD = 0.45      # ... at or above which (and below SIMILAR) a heard run of non-sheet words is a garbled mishearing
GAP_EXTRA = 1.5        # heard words this far (s) from both neighbouring sheet words are an extra vocal, not a line's
SMALL = {"a", "an", "the", "in", "on", "at", "to", "of", "and", "or", "for", "with", "is", "it", "its", "i", "im",
         "you", "your", "we", "our", "he", "she", "they", "me", "my", "so", "but", "oh", "yeah", "uh", "ah", "this",
         "that", "be", "are", "was", "do"}
LETTER_NAMES = {"ay": "a", "eh": "a", "bee": "b", "be": "b", "see": "c", "sea": "c", "si": "c", "dee": "d", "ee": "e",
                "ef": "f", "eff": "f", "gee": "g", "ji": "g", "aitch": "h", "eye": "i", "ai": "i", "jay": "j", "kay": "k",
                "el": "l", "ell": "l", "em": "m", "en": "n", "oh": "o", "pee": "p", "pea": "p", "queue": "q", "cue": "q",
                "ar": "r", "are": "r", "es": "s", "ess": "s", "tee": "t", "tea": "t", "you": "u", "vee": "v", "ex": "x",
                "why": "y", "wye": "y", "zee": "z", "zed": "z"}
ORDER = {"changed": 0, "extra": 1, "missing": 2, "not-heard": 3, "spelling": 4, "ok": 5}


def _similar(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(None, "".join(a), "".join(b), autojunk=False).ratio()


def sounds_alike(sheet: list[str], heard: list[str]) -> bool:
    """Letters >= 60 % alike, or single sheet letters sung by name ("P" / "pee", "A G I" / "ay gee eye")."""
    if _similar(sheet, heard) >= SIMILAR:
        return True
    if all(len(w) == 1 for w in sheet):
        named = [LETTER_NAMES.get(w, w) for w in heard]
        return "".join(named) == "".join(sheet)
    return False


def _fold_map(line: str) -> tuple[str, list[int]]:
    """(fold(line), for each folded character the index of the original character it came from). fold() maps quotes
    1:1 and drops combining marks after NFKD, which may also expand a character (a ligature -> two letters), so the map is
    built character by character (NFKD of a string = the NFKD of its characters, up to the order of combining marks,
    which fold drops)."""
    out, idx = [], []
    for i, c in enumerate(line):
        for d in fold(c):
            out.append(d)
            idx.append(i)
    return "".join(out), idx


def _word_spans(line: str) -> list[tuple[int, int]]:
    """(start, end) in fold(line) of each sung word, as align.split_words counts them."""
    f = fold(line)
    return [(m.start(), m.end()) for m in re.finditer(r"[A-Za-z0-9\u0400-\u04FF']+", f) if re.search(r"[A-Za-z\u0400-\u04FF]", m.group())]


def rebuild_line(line: str, ops: dict[int, list[str] | None], inserts: dict[int, list[str]]) -> str:
    """The sheet line with word k replaced by ops[k] (a list of words; [] or None deletes it) and inserts[k] added
    after word k (inserts[-1] = before the first word). Everything else - punctuation, spacing, and the untouched
    words exactly as written (curly apostrophes, accents) - is kept from the original line."""
    f, idx = _fold_map(line)
    if f != fold(line):                                # cannot map back (should not happen): fall back to the fold
        f, idx = fold(line), None
    fsp = _word_spans(line)
    if not fsp:
        return line
    if idx is None:
        src, sp = f, fsp
    else:                                              # word spans in ORIGINAL coordinates
        src = line
        sp = [(idx[a], idx[b - 1] + 1) for a, b in fsp]
    if _shout(line):                                   # keep a shouted line in capitals
        ops = {k: [w.upper() for w in (v or [])] for k, v in ops.items()}
        inserts = {k: [w.upper() for w in v] for k, v in inserts.items()}
    out = src[:sp[0][0]]
    if inserts.get(-1):
        out += " ".join(inserts[-1]) + " "
    for k, (a, b) in enumerate(sp):
        piece = src[a:b] if k not in ops else " ".join(ops[k] or [])
        out += piece
        if inserts.get(k):
            out += (" " if piece else "") + " ".join(inserts[k])
        out += src[b:sp[k + 1][0]] if k + 1 < len(sp) else src[b:]
    out = re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"\s{2,}", " ", out)).strip()
    out = re.sub(r"([,;:])[,;:]+", r"\1", out)                         # "replied:, it" -> "replied: it"
    out = re.sub(r"[,;:]+([.!?])", r"\1", out)
    out = re.sub(r"^[,.;:]\s*", "", out)
    return out[:1].upper() + out[1:] if line[:1].isupper() else out


def _shout(line: str) -> bool:
    letters = re.sub(r"[^A-Za-z\u0400-\u04FF]", "", line)
    return len(letters) >= 4 and letters.upper() == letters


def diff_sheet(lines: list[str], heard: list[dict], whisper_map: dict | None = None,
               aligned: list[float | None] | None = None, conf_min: float = 0.5) -> dict:
    """lines: the sung sheet; heard: Whisper words [{w, t0, t1, conf?}] in song time; aligned (optional): per sheet
    word, the wav2vec2 confidence words.json gave it (None = not a wav2vec2 time), only when words.json was aligned on
    this very sheet. -> {lines: [...], extra: [...]}."""
    sw = sheet_words(lines)
    sn = [norm(w["w"]) for w in sw]
    vocab = set(sn)
    if aligned is not None and len(aligned) != len(sw):
        aligned = None
    toks = whisper_tokens(sorted(heard, key=lambda x: x["t0"]), sn, whisper_map)
    hn = [t["n"] for t in toks]
    sm = difflib.SequenceMatcher(None, sn, hn, autojunk=False)
    match: dict[int, int] = {}
    per_line: dict[int, dict] = {li: {"equal": 0, "spelling": [], "changed": [], "missing": [], "extra": [],
                                      "echo": False, "small": True, "letter": False, "aligned": [], "half": False,
                                      "ops": {}, "inserts": {}}
                for li in range(len(lines))}
    pos_in_line = []
    count: dict[int, int] = {}
    for w in sw:
        pos_in_line.append(count.get(w["line"], 0))
        count[w["line"]] = pos_in_line[-1] + 1
    extra_runs: list[dict] = []
    opcodes = sm.get_opcodes()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                match[i1 + k] = j1 + k
                per_line[sw[i1 + k]["line"]]["equal"] += 1
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        if tag == "delete":
            for i in range(i1, i2):
                per_line[sw[i]["line"]]["missing"].append(i)
            continue
        if tag == "insert":
            run = toks[j1:j2]
            prev_i, next_i = i1 - 1, i1
            tp = toks[match[prev_i]]["t1"] if prev_i in match else None
            tn = toks[match[next_i]]["t0"] if next_i in match else None
            far_p = tp is None or run[0]["t0"] - tp > GAP_EXTRA
            far_n = tn is None or tn - run[-1]["t1"] > GAP_EXTRA
            same_line = prev_i >= 0 and next_i < len(sw) and sw[prev_i]["line"] == sw[next_i]["line"]
            if far_p and far_n and not same_line:
                extra_runs.append({"t0": round(run[0]["t0"], 2), "t1": round(run[-1]["t1"], 2),
                                   "heard": " ".join(t["raw"] for t in run),
                                   "after_line": sw[prev_i]["line"] + 1 if prev_i >= 0 else 0})
                continue
            # inside a line: after the previous word; between lines: the closer neighbour in time (previous on a tie)
            if prev_i < 0:
                to_prev = False
            elif next_i >= len(sw) or same_line or tn is None:
                to_prev = True
            elif tp is None:
                to_prev = False
            else:
                to_prev = run[0]["t0"] - tp <= tn - run[-1]["t1"]
            if to_prev:
                li, k = sw[prev_i]["line"], pos_in_line[prev_i]
            else:
                li, k = sw[next_i]["line"], pos_in_line[next_i] - 1
            L = per_line[li]
            L["inserts"].setdefault(k, []).extend(t["raw"] for t in run)
            L["extra"].append(" ".join(t["raw"] for t in run))
            ins = [t["n"] for t in run]
            before = sn[max(0, prev_i - len(ins) + 1):prev_i + 1] if prev_i >= 0 else []
            after = sn[next_i:next_i + len(ins)] if next_i < len(sn) else []
            if ins in (before, after):                 # "what he heard heard" (either copy may be the matched one)
                L["echo"] = True
            if not all(n in SMALL for n in ins):
                L["small"] = False
            continue
        # replace: an echo of the word(s) sung just before (heard first) belongs to the previous line, not this run
        for k in (3, 2, 1):
            if i1 - k >= 0 and j2 - j1 > k and hn[j1:j1 + k] == sn[i1 - k:i1] and sw[i1 - 1]["line"] != sw[i1]["line"]:
                L = per_line[sw[i1 - 1]["line"]]
                L["inserts"].setdefault(pos_in_line[i1 - 1], []).extend(t["raw"] for t in toks[j1:j1 + k])
                L["extra"].append(" ".join(t["raw"] for t in toks[j1:j1 + k]))
                L["echo"], L["small"] = True, L["small"] and all(n in SMALL for n in hn[j1:j1 + k])
                j1 += k
                break
        # pair sheet run i1:i2 with heard run j1:j2, split over the lines of the sheet run
        srun = list(range(i1, i2))
        hrun = list(range(j1, j2))
        lines_in = []
        for i in srun:
            if sw[i]["line"] not in lines_in:
                lines_in.append(sw[i]["line"])
        n_s = len(srun)
        start = 0
        for li in lines_in:
            sidx = [i for i in srun if sw[i]["line"] == li]
            lo = round(len(hrun) * start / n_s)
            hi = round(len(hrun) * (start + len(sidx)) / n_s)
            hidx = hrun[lo:hi]
            start += len(sidx)
            a = [sn[i] for i in sidx]
            b = [toks[j]["n"] for j in hidx]
            L = per_line[li]
            if b and sounds_alike(a, b):
                L["spelling"].append({"sheet": " ".join(sw[i]["w"] for i in sidx),
                                      "heard": " ".join(toks[j]["raw"] for j in hidx)})
                for i, j in zip(sidx, hidx):
                    match[i] = j
                continue
            if not b:
                L["missing"] += sidx
                continue
            L["changed"].append({"sheet": " ".join(sw[i]["w"] for i in sidx),
                                 "heard": " ".join(toks[j]["raw"] for j in hidx)})
            if not all((x in SMALL or len(x) == 1) for x in a + b):
                L["small"] = False
            if all(len(x) == 1 for x in a):
                L["letter"] = True
            if aligned is not None:
                good = [(sw[i]["w"], aligned[i]) for i in sidx if aligned[i] is not None and aligned[i] >= conf_min]
                if 2 * len(good) >= len(sidx):
                    L["aligned"] += good
            if HALF_HEARD <= _similar(a, b) < SIMILAR and not any(x in vocab for x in b):
                L["half"] = True
            L["ops"][pos_in_line[sidx[0]]] = [toks[j]["raw"] for j in hidx]
            for i in sidx[1:]:
                L["ops"][pos_in_line[i]] = []
    out_lines = []
    for li, text in enumerate(lines):
        L = per_line[li]
        n = count.get(li, 0)
        miss = sorted(set(L["missing"]))
        heard_any = L["equal"] or L["spelling"] or L["changed"] or L["extra"]
        if n and not heard_any:
            status = "not-heard"
        elif L["changed"]:
            status = "changed"
        elif L["extra"]:
            status = "extra"
        elif miss:
            status = "missing"
        elif L["spelling"]:
            status = "spelling"
        else:
            status = "ok"
        row = {"line": li + 1, "sheet": text, "status": status, "words": n, "heard_equal": L["equal"]}
        for k in ("spelling", "changed", "extra"):
            if L[k]:
                row[k] = L[k]
        if miss:
            row["missing"] = [sw[i]["w"] for i in miss]
        if status in ("changed", "extra"):
            row["proposed"] = rebuild_line(text, L["ops"], L["inserts"])
            if norm(row["proposed"]) == norm(text):
                row.pop("proposed")
            row["_echo"], row["_small"], row["_letter"] = L["echo"], L["small"], L["letter"]
            row["_aligned"], row["_half"] = L["aligned"], L["half"]
        if status == "missing" and L["equal"] >= 0.5 * n:
            row["if_dropped"] = rebuild_line(text, {pos_in_line[i]: [] for i in miss}, {})
        out_lines.append(row)
    # confidence of each proposal (see the module docstring)
    as_written: dict[str, list[int]] = {}
    for r in out_lines:
        if r["status"] in ("ok", "spelling"):
            as_written.setdefault(norm(r["sheet"]), []).append(r["line"])
    for r in out_lines:
        echo, small, letter = r.pop("_echo", False), r.pop("_small", False), r.pop("_letter", False)
        good, half = r.pop("_aligned", []), r.pop("_half", False)
        if "proposed" not in r:
            continue
        why = []
        if _shout(r["sheet"]):
            why.append("shout: crowd shouts are often misheard")
        same = [x for x in as_written.get(norm(r["sheet"]), []) if x != r["line"]]
        if same:
            why.append(f"repeat: the same line is heard as written at line {same[0]}")
        if small:
            why.append("small-words: only short words differ (a common Whisper slip)")
        elif letter:
            why.append("letter: a letter sung by name (\"P\", \"A G I\") is spelled many ways by Whisper")
        if echo:
            why.append("echo: it repeats the word just sung - an ad-lib for lyrics/adlibs.json, not the sheet")
        if good:
            why.append("aligned: wav2vec2 placed the sheet's words here with good confidence ("
                       + ", ".join(f"{w} {c:.2f}" for w, c in good[:4]) + "): the take probably sings the sheet")
        if half:
            why.append("half-heard: the heard words are not in the song and sound partly like the sheet's - a garbled "
                       "mishearing more often than a change")
        r["confidence"] = "unsure" if why else "likely"
        if why:
            r["why"] = why
    return {"lines": out_lines, "extra": extra_runs}


def _backup(paths: Paths) -> Path:
    """Copy lyrics.txt to a NEW lyrics/lyrics.txt.<YYYYmmdd-HHMMSS>.bak (never overwrites an older backup)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = paths.lyrics.with_name(f"lyrics.txt.{stamp}.bak")
    k = 2
    while dst.exists():
        dst = paths.lyrics.with_name(f"lyrics.txt.{stamp}-{k}.bak")
        k += 1
    shutil.copy2(paths.lyrics, dst)
    return dst


def _aligned_conf(paths: Paths, lines: list[str]) -> tuple[list[float | None] | None, float]:
    """Per sheet word, the wav2vec2 confidence of analysis/words.json - only when it was aligned on this very sheet
    (same lyric lines); else None."""
    from .common import read_json
    try:
        W = read_json(paths.words)
    except SlopError:
        return None, 0.5
    if not W or [L.get("text") for L in W.get("lines") or []] != lines:
        return None, 0.5
    out = [float(w.get("conf") or 0.0) if w.get("src") == "w2v" and w.get("t0") is not None else None
           for w in W.get("words") or []]
    return out, float(W.get("conf_min", 0.5) or 0.5)


def _apply(paths: Paths, proposals: dict[int, str], to: Path) -> None:
    src = paths.lyrics.read_text(encoding="utf-8").splitlines()
    li, out = 0, []
    for raw in src:
        if not is_lyric_noise(raw):                  # the shared lyric-line rule (slop.util)
            li += 1
            out.append(proposals.get(li, raw))
        else:
            out.append(raw)
    to.write_text("\n".join(out) + "\n", encoding="utf-8")


def parse_lines(spec: str | None) -> list[int] | None:
    if spec is None:
        return None
    out = []
    for part in [x.strip() for x in spec.split(",") if x.strip()]:
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", part)
        if not m:
            raise SlopError(f"--apply-lines {part!r}: lyric line numbers as the check lists them, e.g. 14,25 or 14-16")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        out += list(range(a, b + 1))
    if not out:
        raise SlopError("--apply-lines needs line numbers, e.g. --apply-lines 14,25")
    return out


def check(pdir: Path, yes: bool = False, model: str | None = None, write: bool = False, apply: bool = False,
          apply_lines: list[int] | None = None) -> dict:
    paths = Paths(pdir)
    lines = read_sheet(paths.lyrics)
    if not lines:
        raise SlopError("lyrics/lyrics.txt has no lyric lines yet: write the sung lyrics there (one line per lyric line, "
                        f"words as sung), then `{project_cmd(pdir, 'lyrics check')}`")
    if sum(bool(x) for x in (write, apply, apply_lines)) > 1:
        raise SlopError("pass one of --write (a proposal file), --apply (the likely proposals) or --apply-lines, "
                        "not both")
    if not paths.stem("vocals").exists():
        raise SlopError("no audio/stems/vocals.wav: the check listens to the vocal stem. Run "
                        f"`{project_cmd(pdir, 'analyze --steps stems')}` first (1-2 min on CPU), then "
                        f"`{project_cmd(pdir, 'lyrics check')}`")
    cfg = audio_cfg(pdir)
    explicit = bool(model)
    model = model or cfg.get("whisper_model") or wh.DEFAULT_MODEL
    cached = wh.find_cached(paths, model) or (None if explicit else wh.find_cached(paths, None))
    if cached:
        heard, cost, paid, used_model = cached["words"], 0.0, False, cached["model"]
    else:
        if not wh.have_key():
            raise SlopError("the lyrics check needs OPENROUTER_API_KEY (Whisper via OpenRouter, about $0.002 per song). "
                            "Ask the user for it with the secure secret card, then re-run "
                            f"`{project_cmd(pdir, 'lyrics check')}`")
        usd = cfg.get("whisper_usd_per_s")
        R = wh.vocal_env(paths.stem("vocals"))
        wins = wh.plan_windows(R)
        if not wins:
            raise SlopError("the vocal stem is silent (no vocal-active window): is audio/stems/vocals.wav right?")
        t = wh.transcribe(pdir, wins, model=model, yes=yes, usd_per_s=float(usd) if usd is not None else None)
        heard, cost, paid, used_model = t["words"], t["cost_usd"], not t["cached"], t["model"]
    aligned, conf_min = _aligned_conf(paths, lines)
    D = diff_sheet(lines, heard, cfg.get("whisper_map"), aligned, conf_min)
    rows, extra = D["lines"], D["extra"]
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(r["status"], []).append(r["line"])
    likely = {r["line"]: r["proposed"] for r in rows if r.get("proposed") and r.get("confidence") == "likely"}
    unsure = {r["line"]: r["proposed"] for r in rows if r.get("proposed") and r.get("confidence") == "unsure"}
    res = {"model": used_model, "cost_usd": round(cost, 8), "paid": paid, "lines": rows, "extra_vocals": extra,
           "summary": {k: len(v) for k, v in by.items()}, "proposals": {"likely": sorted(likely), "unsure": sorted(unsure)},
           "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": "analysis/lyrics-check.json"}
    written, applied = None, []
    if apply_lines is not None:
        allp = {**likely, **unsure}
        bad = [n for n in apply_lines if n not in allp]
        if bad:
            raise SlopError(f"no proposal for line(s) {', '.join(map(str, bad))}: the lines with a proposal are "
                            f"{', '.join(map(str, sorted(allp))) or 'none'}")
        chosen = {n: allp[n] for n in apply_lines}
    else:
        chosen = likely
    if (write or apply or apply_lines) and chosen:
        if write:
            _apply(paths, chosen, paths.lyrics.with_name("lyrics.proposed.txt"))
            written = "lyrics/lyrics.proposed.txt"
        else:
            bak = _backup(paths)
            _apply(paths, chosen, paths.lyrics)
            written = f"lyrics/lyrics.txt (the sheet before this change: lyrics/{bak.name})"
            applied = sorted(chosen)
            res["backup"] = f"lyrics/{bak.name}"
        res["written"] = written
    res["applied"] = applied
    write_json(paths.analysis / "lyrics-check.json", res, indent=1)
    # human text: only the lines that need a look
    T = [f"lyrics check ({used_model}" + (f", paid ${cost:.4f}" if paid else ", cached transcription: free") + "): "
         + ", ".join(f"{len(v)} {k}" for k, v in sorted(by.items(), key=lambda kv: ORDER.get(kv[0], 9)))
         + f" - proposals: {len(likely)} likely, {len(unsure)} unsure"]
    for r in rows:
        if r["status"] == "ok":
            continue
        if r["status"] == "spelling":
            T.append(f"  line {r['line']} spelling only (kept): " + "; ".join(f"\"{x['heard']}\" for \"{x['sheet']}\""
                                                                        for x in r["spelling"][:3]))
            continue
        conf = f" [{r['confidence'].upper()}]" if r.get("confidence") else ""
        T.append(f"  line {r['line']} {r['status'].upper()}{conf}: \"{r['sheet']}\"")
        for x in r.get("changed", []):
            T.append(f"      heard \"{x['heard']}\" where the sheet has \"{x['sheet']}\"")
        for x in r.get("extra", []):
            T.append(f"      extra words heard: \"{x}\"")
        if r.get("missing"):
            T.append(f"      not heard: {' '.join(r['missing'])}")
        if r.get("proposed"):
            T.append(f"      proposed: \"{r['proposed']}\"")
        for w in r.get("why", []):
            T.append(f"      unsure - {w}")
        if r.get("if_dropped"):
            T.append(f"      if the singer dropped them: \"{r['if_dropped']}\"")
    for e in extra:
        T.append(f"  EXTRA VOCAL {e['t0']:.2f}-{e['t1']:.2f} s (after line {e['after_line']}): \"{e['heard']}\" - an ad-lib "
                 "or a line missing from the sheet")
    nxt = []
    left_likely = [n for n in likely if n not in applied]
    left_unsure = [n for n in unsure if n not in applied]
    if applied:
        nxt.append(f"applied line(s) {', '.join(map(str, applied))}; re-align the new sheet: "
                   f"`{project_cmd(pdir, 'analyze --steps align')}`")
    if left_likely and not applied:
        nxt.append(f"show the {len(left_likely)} LIKELY proposal(s) to the owner; if they agree: "
                   f"`{project_cmd(pdir, 'lyrics check --apply')}` (free now: the transcription is cached)")
    if left_unsure:
        nxt.append(f"the {len(left_unsure)} UNSURE one(s) (line {', '.join(map(str, left_unsure))}) need the owner's ear "
                   "(Whisper mishears shouts, repeats and spelled-out letters); apply only those they confirm: "
                   f"`{project_cmd(pdir, 'lyrics check --apply-lines N,M')}`")
    if (left_likely or left_unsure) and not applied:
        nxt.append(f"after any change: `{project_cmd(pdir, 'analyze --steps align')}`")
    if by.get("not-heard") or by.get("missing"):
        nxt.append("lines not (fully) heard: ask the owner to listen (sung or shouted lines are often missed by Whisper); "
                   "keep the sheet if they are sung as written")
    if extra:
        nxt.append("extra vocals: add a line to lyrics/lyrics.txt where the owner hears a sung line, or an entry in "
                   "lyrics/adlibs.json ({\"text\", \"t0\", \"t1\"}) for an ad-lib")
    if not likely and not unsure and not by.get("not-heard") and not by.get("missing") and not extra:
        nxt.append("the sheet matches the take")
    if written:
        T.append(f"wrote {written}")
    T.append("next: " + "; ".join(nxt))
    res["next"] = nxt
    res["text"] = "\n".join(T)
    return res
