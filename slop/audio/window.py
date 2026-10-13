"""Per-clip reference audio windows -> audio/windows/<clip>.mp3 + <clip>.json (the @Audio1 of a video clip).

clean: port of prompts.clean_window - the vocal stem's window with everything but the given words muted. Phrases are
merged across gaps <= 0.35 s; each opens 50 ms before its first word, closes with a release tail that follows the
stem's own energy (until the 10 ms RMS falls 24 dB below the phrase peak, at most 0.40 s, and before the next phrase);
15 ms raised-cosine ramps; normalised to -16 dBFS RMS over the kept part with a -1 dBFS peak cap; mono 44.1 kHz,
192 kbps mp3 (+ the wav beside it). Why: the video model copied the conditioning audio only about half the time, and
what made sung clips sync was a clean vocal window with everything outside the on-camera words muted (it also keeps
crowd shouts from being lip-synced by the lead).
mix: the song (mix) window as is, mono 44.1 kHz 192 kbps (motion clips: "moving in time with @Audio1").
Words for a clean window: the aligned words whose start is inside [t0 + .05, t1 - .08) (the her_words rule), or with
--words "exact quoted words" only the aligned words (in order) that spell that quote - other voices and the next line
stay muted; lyrics/adlibs.json entries are the fallback for sung words that are not on the sheet.
EXPLICIT TOKENS (tokens=[...], `--tokens 41,42,43-45`): exactly these words are kept, no text matching - word indices
(the "i" of analysis/words.json, as the report lists them), [t0, t1, word] spans (a clip's her_words: matched to the
aligned word or ad-lib starting at that t0, +-11 ms) or {"i"} / {"t0", "t1", "w"} dicts. Why: the quote matcher is
greedy-first, so a cover window of a her-words chain ("you" ... "you") could keep an EARLIER repeat of the word that is
also inside the window; the chain's own tokens cannot. Each token must start inside [t0 + .05, t1 - .08); with
--words too, the tokens must spell the quote. Backward compatible: without tokens nothing changes.
Changes: a window that ends past the song (less than half the requested length, or under 0.5 s, decodes) is an error
naming the song's duration - it used to "succeed" with an empty file that a paid clip could have used as @Audio1;
listen=True (`slop audio window ... --listen`, used by the ear check in analysis/report.md) writes a mix excerpt to
analysis/listen/ instead of audio/windows/ (the clip-window folder the gen module reads).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import SONG_SR, Paths, dbfs, load_mono, project_cmd, read_json, run_ffmpeg, write_audio, write_json

SR = SONG_SR
_CLIP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def window_words(words: list[dict], t0: float, t1: float, quoted: str | None = None,
                 adlibs: list[dict] | None = None) -> tuple[list[list], bool]:
    """-> ([[t0, t1, word]...] in song time, all_quoted_words_found)."""
    inside = [w for w in words if w.get("t0") is not None and t0 + .05 <= w["t0"] < t1 - .08]
    if not quoted:
        return [[w["t0"], w["t1"], w["w"]] for w in inside], True
    q = _norm(quoted)
    i, out = 0, []
    for w in inside:
        n = _norm(w["w"])
        if n and q.startswith(n, i):
            out.append([w["t0"], w["t1"], w["w"]])
            i += len(n)
    if i < len(q):
        for a in adlibs or []:
            if t0 <= a["t0"] < t1 and _norm(a["text"]) == q:
                return [[a["t0"], a["t1"], a["text"].strip("()")]], True
    return out, i == len(q)


def _tok_parts(tok) -> tuple[int | None, float | None, float | None, str | None]:
    """(word index, t0, t1, text) from one explicit token (int / [t0, t1, w] / {"i"} / {"t0", "t1", "w"})."""
    if isinstance(tok, bool):
        raise SlopError(f"token {tok!r}: give a word index or a [t0, t1, word] span")
    if isinstance(tok, int) or (isinstance(tok, str) and tok.strip().isdigit()):
        return int(tok), None, None, None
    if isinstance(tok, dict):
        if tok.get("i") is not None:
            return int(tok["i"]), None, None, None
        if tok.get("t0") is not None:
            return (None, float(tok["t0"]), float(tok["t1"]) if tok.get("t1") is not None else None,
                    tok.get("w") or tok.get("text"))
    if isinstance(tok, (list, tuple)) and len(tok) >= 2:
        return None, float(tok[0]), float(tok[1]), (str(tok[2]) if len(tok) > 2 and tok[2] is not None else None)
    raise SlopError(f'token {tok!r}: give a word index (words.json "i") or a [t0, t1, word] span')


def resolve_tokens(words: list[dict], tokens: list, t0: float, t1: float,
                   adlibs: list[dict] | None = None, pdir: Path | None = None) -> list[list]:
    """Explicit tokens -> [[t0, t1, word, index or None]] in song time (time order), each checked against the aligned
    words (or lyrics/adlibs.json) and the window. Raises SlopError naming the token and what to do (commands carry
    --project when pdir is given)."""
    def cmd(rest: str) -> str:
        return project_cmd(pdir, rest) if pdir is not None else f"slop {rest}"
    by_i = {int(w.get("i", k)): w for k, w in enumerate(words)}
    out, seen = [], set()
    for tok in tokens:
        i, a, b, txt = _tok_parts(tok)
        if i is not None:
            w = by_i.get(i)
            if w is None:
                raise SlopError(f"token {i}: no word {i} in analysis/words.json (0..{len(words) - 1})")
            if w.get("t0") is None:
                raise SlopError(f'token {i} "{w["w"]}" has no timing yet: fix it with '
                                f'`{cmd(f"lyrics fix --word {i} --t0 <start> --t1 <end>")}` first')
            hit = [w["t0"], w["t1"], w["w"], i]
        else:
            near = [w for w in words if w.get("t0") is not None and abs(w["t0"] - a) <= .011]
            if txt:
                near = [w for w in near if _norm(w["w"]) == _norm(txt)]
            if near:
                w = near[0]
                hit = [w["t0"], w["t1"], w["w"], int(w.get("i", words.index(w)))]
            else:
                ad = [x for x in adlibs or [] if abs(float(x["t0"]) - a) <= .011 and
                      (not txt or _norm(x.get("text", "")) == _norm(txt))]
                if not ad:
                    what = f"[{a:.3f}, {b if b is not None else '?'}, {txt!r}]"
                    raise SlopError(f"token {what} matches no aligned word (or lyrics/adlibs.json entry) starting at "
                                    f"{a:.3f} s: the word timing changed since the clip was drafted. Re-cut the window "
                                    "from the current words.json (re-draft the clip window), or pass word indices.")
                x = ad[0]
                hit = [float(x["t0"]), float(x.get("t1", float(x["t0"]) + .3)), str(x.get("text", "")).strip("()"), None]
        if not (t0 + .05 - 1e-6 <= hit[0] < t1 - .08):
            raise SlopError(f'token "{hit[2]}" starts at {hit[0]:.3f} s, outside the words this window can keep '
                            f"[{t0 + .05:.3f}, {t1 - .08:.3f}) (a clean window keeps words starting in [t0 + .05, t1 - .08)): "
                            "move the window or drop the token")
        key = (round(hit[0], 3), hit[3])
        if key not in seen:
            seen.add(key)
            out.append(hit)
    out.sort(key=lambda h: h[0])
    return out


def parse_token_list(spec: str) -> list[int]:
    """'41,42,45-47' -> [41, 42, 45, 46, 47] (word indices for --tokens)."""
    out: list[int] = []
    for part in [x.strip() for x in (spec or "").split(",") if x.strip()]:
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b < a or b - a > 200:
                raise SlopError(f"--tokens range {part!r}: write low-high, e.g. 41-45")
            out += list(range(a, b + 1))
        elif part.isdigit():
            out.append(int(part))
        else:
            raise SlopError(f"--tokens {part!r}: word indices from analysis/words.json, e.g. --tokens 41,42,45-47")
    if not out:
        raise SlopError("--tokens needs word indices, e.g. --tokens 41,42,45-47")
    return out


def clean_gain(x: np.ndarray, sr: int, words_rel: list[list], pre: float = .05, tail: float = .40, gap: float = .35,
               ramp: float = .015) -> tuple[np.ndarray, list[list[float]]]:
    """The gain curve that keeps only the given words (times relative to the window start). Verbatim algorithm."""
    n = len(x)
    phrases: list[list[float]] = []
    for a0, a1, *_ in sorted(words_rel):
        if phrases and a0 - phrases[-1][1] <= gap:
            phrases[-1][1] = max(phrases[-1][1], a1)
        else:
            phrases.append([a0, a1])
    h = max(1, int(.01 * sr))
    env = np.sqrt(np.convolve(x.astype(np.float64) ** 2, np.ones(h) / h, "same")) + 1e-9
    g = np.zeros(n, np.float32)
    r = int(ramp * sr)
    for i, (p0, p1) in enumerate(phrases):
        i0 = max(0, int((p0 - pre) * sr))
        i1 = min(n, int(p1 * sr))
        if i0 >= n:
            continue
        peak = env[i0:max(i1, i0 + 1)].max()
        lim = min(n, int((p1 + tail) * sr))
        if i + 1 < len(phrases):
            lim = min(lim, int((phrases[i + 1][0] - pre) * sr))
        j = i1
        while j < lim and env[j] > peak * 10 ** (-24 / 20):
            j += h
        i1 = min(j, lim)
        g[i0:i1] = 1.0
        if r and i1 - i0 > 2 * r:
            rr = (.5 - .5 * np.cos(np.linspace(0, np.pi, r))).astype(np.float32)
            g[i0:i0 + r] *= rr
            g[i1 - r:i1] *= rr[::-1]
    return g, phrases


def normalise(y: np.ndarray, g: np.ndarray, rms_db: float = -16.0, peak_db: float = -1.0) -> np.ndarray:
    act = y[g > .5]
    if len(act):
        y = y * (10 ** (rms_db / 20) / (np.sqrt(np.mean(act.astype(np.float64) ** 2)) + 1e-9))
        y = y * min(1.0, 10 ** (peak_db / 20) / (np.abs(y).max() + 1e-9))
    return y.astype(np.float32)


def _mp3(wav: Path, mp3: Path) -> None:
    tmp = mp3.with_name(mp3.stem + ".part.mp3")
    run_ffmpeg(["-y", "-i", str(wav), "-ac", "1", "-ar", str(SR), "-b:a", "192k", str(tmp)], what="encoding the mp3 window")
    tmp.replace(mp3)


def _check_length(paths: Paths, y: np.ndarray, t0: float, t1: float) -> None:
    dur = t1 - t0
    got = len(y) / SR
    if got < 0.5 or got < 0.5 * dur:
        from .common import song_duration
        sd = song_duration(paths)
        raise SlopError(f"window {t0:.2f}-{t1:.2f} s ends past the song (duration {sd:.2f} s; only {got:.2f} s of audio "
                        f"there): choose t1 <= {sd:.2f}" if sd else f"window {t0:.2f}-{t1:.2f} s holds only {got:.2f} s "
                        "of audio: check the times")


def make_window(pdir: Path, clip: str, t0: float, t1: float, mode: str = "clean", quoted: str | None = None,
                listen: bool = False, tokens: list | None = None) -> dict:
    paths = Paths(pdir)
    if not _CLIP.match(clip or ""):
        raise SlopError(f"clip id {clip!r}: use letters, digits, '.', '_' or '-' (e.g. SD01, W02, s014-sung)")
    if mode not in ("clean", "mix"):
        raise SlopError("--mode must be clean (vocal stem, only the clip's words) or mix (the song as is)")
    if t1 <= t0 or t0 < 0:
        raise SlopError(f"bad window {t0}-{t1}: need 0 <= t0 < t1 (song seconds)")
    dur = t1 - t0
    warn = []
    if dur > 15:
        warn.append(f"{dur:.1f} s is long for a video clip (sung clips 4-8 s, motion 4-12 s)")
    if dur < 1.0:
        warn.append(f"{dur:.2f} s is very short")
    if listen and mode != "mix":
        raise SlopError("--listen cuts a mix excerpt for the ear check: use it with --mode mix")
    if tokens is not None and mode != "clean":
        raise SlopError("--tokens picks the words a CLEAN window keeps: use it with --mode clean (a mix window keeps "
                        "everything)")
    if tokens is not None and not len(tokens):
        raise SlopError("tokens is empty: pass the words to keep (word indices or [t0, t1, word] spans), or leave it out")
    out_dir = paths.listen if listen else paths.windows
    rel = "analysis/listen" if listen else "audio/windows"
    out_dir.mkdir(parents=True, exist_ok=True)
    mp3 = out_dir / f"{clip}.mp3"
    wav = out_dir / f"{clip}.wav"
    info: dict = {"clip": clip, "mode": mode, "t0": round(t0, 3), "t1": round(t1, 3), "dur": round(dur, 3)}
    if mode == "mix":
        if not paths.song.exists():
            raise SlopError(f"no audio/song.wav - run `{project_cmd(pdir, 'song ingest FILE')}` first")
        y = load_mono(paths.song, SR, t0, dur)
        _check_length(paths, y, t0, t1)
        if len(y) < int(dur * SR) - SR // 10:
            warn.append(f"the song ends before {t1:.2f} s; the window is {len(y) / SR:.2f} s")
        write_audio(wav, y, SR)
        info.update(source="audio/song.wav", words=[], sung="")
    else:
        voc = paths.stem("vocals")
        if not voc.exists():
            raise SlopError(f"no audio/stems/vocals.wav - run `{project_cmd(pdir, 'analyze --steps stems')}` first")
        W = read_json(paths.words)
        if not W:
            raise SlopError(f"no analysis/words.json - run `{project_cmd(pdir, 'analyze')}` (with lyrics/lyrics.txt) "
                            "first: a clean window keeps only the aligned words")
        adl = read_json(paths.adlibs, []) or []
        idx = None
        if tokens is not None:
            res = resolve_tokens(W["words"], list(tokens), t0, t1, adl, pdir)
            ws, ok, idx = [[a, b, w] for a, b, w, _ in res], True, [k for *_, k in res]
            spelled = " ".join(w for _, _, w in ws)
            if quoted and _norm(spelled) != _norm(quoted):
                raise SlopError(f'the tokens spell "{spelled}" but the quote is "{quoted}": pass the tokens of exactly '
                                "the quoted words (or drop --words)")
        else:
            ws, ok = window_words(W["words"], t0, t1, quoted, adl)
        if quoted and not ok:
            got = " ".join(w[2] for w in ws)
            raise SlopError(f"the quoted words \"{quoted}\" were not all found among the aligned words starting inside "
                            f"{t0:.2f}-{t1:.2f} (found: \"{got}\"). Check the window times and the exact sung words "
                            "(analysis/words.json), or omit --words to keep every word in the window.")
        if not ws:
            raise SlopError(f"no aligned word starts inside {t0:.2f}-{t1:.2f}; use --mode mix for a motion clip")
        x = load_mono(voc, SR, t0, dur)
        _check_length(paths, x, t0, t1)
        wrel = [[a - t0, b - t0, w] for a, b, w in ws]
        g, phrases = clean_gain(x, SR, wrel)
        y = normalise(x * g, g)
        write_audio(wav, y, SR)
        act = y[g > .5]
        info.update(source="audio/stems/vocals.wav", words=[{"w": w, "t0": round(a, 3), "t1": round(b, 3)} for a, b, w in ws],
                    words_rel=[{"w": w, "t0": round(a - t0, 3), "t1": round(b - t0, 3)} for a, b, w in ws],
                    sung=" ".join(w for _, _, w in ws), phrases=[[round(a, 3), round(b, 3)] for a, b in phrases],
                    rms_dbfs=dbfs(np.sqrt(np.mean(act.astype(np.float64) ** 2))) if len(act) else None,
                    peak_dbfs=dbfs(np.abs(y).max() if len(y) else 0.0))
        if quoted:
            info["quoted"] = quoted
        if idx is not None:
            info["tokens"] = idx                   # word indices kept (None = an ad-lib), in time order
    _mp3(wav, mp3)
    info.update(file=f"{rel}/{clip}.mp3", wav=f"{rel}/{clip}.wav", warnings=warn)
    write_json(out_dir / f"{clip}.json", info, indent=1)
    txt = (f"{rel}/{clip}.mp3: {mode} window {t0:.2f}-{t1:.2f} s ({dur:.2f} s)"
           + (f", words \"{info['sung']}\"" if info.get("sung") else "") + "".join(f"\n  note: {w}" for w in warn))
    return {**info, "text_summary": txt}
