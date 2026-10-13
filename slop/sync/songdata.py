"""Song timing helpers shared by clips, sync and covers: aligned words, word-gap window starts, beats and eighths.

Reads the project's analysis files (ARCHITECTURE §4.2 / §4.3 / §4.4):
  analysis/words.json  {"words":[{"w","line","t0","t1",...}], "lines":[{"line","text","t0","t1"}|"text"], "gaps":[...]}
  analysis/beats.json  {"beats":[s...], "downbeats":[s...], ...}
  analysis/hits.json   {"kick":[s], "snare":[s], ...}

Ported from the production pipeline's seedance.py (tokens, words_in, gap_start) and avsync.py (beats -> eighths) with the
calibrated constants unchanged:
  words_in(t0, t1): the words that START in [t0 - .02, t1 - .08); line ends get "." when the lyric has no punctuation.
  gap_start(t, lead=.25, span=1.6): gaps between consecutive words >= 60 ms (plus [0, first word]); the gap midpoint (for
      gaps > .5 s: min(mid, next word - .12)); the latest midpoint in [t - 1.6, t - lead], else the latest <= t - lead,
      else max(0, t - lead).
  eighths: the beats plus the midpoints between consecutive beats, sorted.
Generic changes: data comes from the project passed in (no module-level project globals); lines may be dicts or strings.
Additions (not in the source): `lo` selects the clean-window word rule ([t0 + .05, t1 − .08), the audio module's clean
window keeps exactly those words); phrases() groups a window's words for the screenplay scaffold (split at gaps > .35 s,
at the lyric's own punctuation, or past 1.6 s); her_words() is the production prompts.py matcher (the aligned words, in
order, that spell a quote — "her words only" windows; lyrics/adlibs.json is the fallback); clean_start() moves a clean
window's start back so the first word after a gap midpoint is not muted (gap_start puts the start at the midpoint; for a
gap under ~.1 s the clean rule's +.05 s would drop the next word — the start moves to that word's t0 − .06, still in
the gap because gap_start only uses gaps ≥ .06 s).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PUNCT_END = ".,!?—-…;:"
CLEAN_LO = .05                                   # a clean window keeps the words starting in [t0 + .05, t1 − .08)


def norm_compact(s: str) -> str:
    """letters and digits only, lower case (the her_words matcher's normalisation: "Dahrio," == "dahrio")."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


class SongData:
    """Aligned words + beats + hits of one project (any of them may be missing; methods degrade, never guess)."""

    def __init__(self, pdir: Path | None = None, *, words: dict | None = None, beats: dict | None = None,
                 hits: dict | None = None):
        self.pdir = pdir
        a = (pdir / "analysis") if pdir else None
        self.words_doc = words if words is not None else (_read(a / "words.json") if a else None) or {}
        self.beats_doc = beats if beats is not None else (_read(a / "beats.json") if a else None) or {}
        self.hits_doc = hits if hits is not None else (_read(a / "hits.json") if a else None) or {}
        self.words: list[dict] = sorted([w for w in self.words_doc.get("words", []) if "t0" in w and "t1" in w],
                                        key=lambda w: w["t0"])
        self._tok: list[dict] | None = None

    # ---- presence ----
    @property
    def has_words(self) -> bool:
        return bool(self.words)

    @property
    def has_beats(self) -> bool:
        return bool(self.beats_doc.get("beats"))

    # ---- words ----
    def line_texts(self) -> list[str]:
        out = []
        for i, ln in enumerate(self.words_doc.get("lines", [])):
            out.append(ln.get("text", "") if isinstance(ln, dict) else str(ln))
        return out

    def tokens(self) -> list[dict]:
        """every aligned word with its lyric-sheet spelling (punctuation kept) when the line's token count matches."""
        if self._tok is not None:
            return self._tok
        lines = self.line_texts()
        out = []
        if lines:
            by_line: dict[int, list[dict]] = {}
            for w in self.words:
                by_line.setdefault(int(w.get("line", -1)), []).append(w)
            for li, text in enumerate(lines):
                ws = by_line.get(li, [])
                tk = text.split()
                for k, w in enumerate(ws):
                    out.append({**w, "text": tk[k] if len(tk) == len(ws) else w.get("w", ""), "last": k == len(ws) - 1})
            seen = {id(w) for w in self.words if int(w.get("line", -1)) in range(len(lines))}
            for w in self.words:                                   # words without a line index still count
                if id(w) not in seen:
                    out.append({**w, "text": w.get("w", ""), "last": False})
        else:
            out = [{**w, "text": w.get("w", ""), "last": False} for w in self.words]
        self._tok = sorted(out, key=lambda w: w["t0"])
        return self._tok

    def words_starting_in(self, t0: float, t1: float, lo: float = -.02) -> list[dict]:
        """aligned words that START inside the window [t0 + lo, t1 - .08) (the window words rule: lo = -.02 for a raw
        window; lo = +.05 for a clean vocal window, whose audio keeps exactly the words starting in [t0 + .05, t1 - .08))."""
        return [w for w in self.tokens() if t0 + lo <= w["t0"] < t1 - .08]

    def words_in(self, t0: float, t1: float, lo: float = -.02) -> str:
        """the words sung in [t0, t1): starting inside it; lines joined as sentences."""
        return self.join(self.words_starting_in(t0, t1, lo))

    @staticmethod
    def join(tokens: list[dict]) -> str:
        """tokens as quoted text: lyric-sheet spelling, a line's last word ends with "." when the lyric has none."""
        s = ""
        for w in tokens:
            txt = w.get("text") or w.get("w", "")
            if not txt:
                continue
            s += txt + (("" if txt[-1] in PUNCT_END else ".") if w.get("last") else "") + " "
        return s.strip()

    def text_for(self, spans: list) -> str:
        """lyric-sheet text for [[t0, t1, w], ...] aligned words (e.g. a clip's her_words), in that order."""
        by_t0 = {round(w["t0"], 3): w for w in self.tokens()}
        out = []
        for sp in spans:
            tk = by_t0.get(round(float(sp[0]), 3))
            out.append(tk if tk else {"text": str(sp[2]) if len(sp) > 2 else "", "last": False})
        return self.join(out)

    def adlibs(self) -> list[dict]:
        if not self.pdir:
            return []
        doc = _read(self.pdir / "lyrics" / "adlibs.json")
        return [a for a in (doc if isinstance(doc, list) else []) if isinstance(a, dict) and "t0" in a and "text" in a]

    def her_words(self, quoted: str, t0: float, t1: float, lo: float = CLEAN_LO) -> tuple[list[dict], bool]:
        """(tokens, all found): the aligned words, in order, that spell the quoted words, from those starting inside the
        window [t0 + lo, t1 − .08); unmatched words (another voice, the next line) are left out. Falls back to
        lyrics/adlibs.json (sung but not aligned). Port of the production prompts.her_words with one change: the
        production matcher was greedy-first, so a quote whose first word is repeated earlier in the window ("here we go
        now, here it comes": quote "here it comes") took the EARLIER repeat and the clean window kept the wrong word.
        Every start word is tried and the tightest complete match wins (ties: the earliest) - for an unrepeated quote
        this is exactly the old result. These tokens go to the audio module as explicit tokens."""
        q = norm_compact(quoted)
        inside = [w for w in self.tokens() if t0 + lo <= w["t0"] < t1 - .08]
        norm = [norm_compact(w.get("w") or w.get("text") or "") for w in inside]

        def from_start(s: int) -> tuple[list[dict], int]:
            i, out = 0, []
            for w, n in zip(inside[s:], norm[s:]):
                if n and q.startswith(n, i):
                    out.append(w)
                    i += len(n)
            return out, i

        best: tuple[list[dict], int] | None = None
        for s, n in enumerate(norm):
            if not (q and n and q.startswith(n)):
                continue
            out_s, i_s = from_start(s)
            if i_s == len(q) and (best is None or (out_s[-1]["t1"] - out_s[0]["t0"]) < (best[0][-1]["t1"] - best[0][0]["t0"]) - 1e-9):
                best = (out_s, i_s)
        out, i = best if best is not None else from_start(0)
        if i < len(q):
            for a in self.adlibs():
                if t0 <= a["t0"] < t1 and norm_compact(a["text"]) == q:
                    return [{"t0": a["t0"], "t1": a.get("t1", a["t0"]), "w": a["text"].strip("()"),
                             "text": a["text"].strip("()"), "last": False}], True
        return out, bool(q) and i == len(q)

    def clean_start(self, t0: float, lo: float = CLEAN_LO) -> float:
        """a clean window's start moved back so no word that starts just after it is muted by the clean rule."""
        near = [w["t0"] for w in self.tokens() if t0 - .02 <= w["t0"] < t0 + lo + .01]
        return round(max(0.0, min(t0, min(near) - .06)), 3) if near else round(t0, 3)

    def words_between(self, a: float, b: float) -> list[dict]:
        """words overlapping [a, b] (labels for figures, words at a divergence)."""
        return [w for w in self.words if w.get("t1", 0) > a and w.get("t0", 0) < b]

    def gap_start(self, t: float, lead: float = .25, span: float = 1.6) -> float:
        """a window start in a word gap: the latest gap midpoint in [t - span, t - lead] (else the latest before t - lead)."""
        tok = self.tokens()
        if not tok:
            return round(max(0.0, t - lead), 3)
        gaps = [(tok[i]["t1"], tok[i + 1]["t0"]) for i in range(len(tok) - 1) if tok[i + 1]["t0"] - tok[i]["t1"] >= .06]
        gaps = [(0.0, tok[0]["t0"])] + gaps
        mids = [min((a + b) / 2, b - .12) if b - a > .5 else (a + b) / 2 for a, b in gaps]
        ok = [m for m in mids if t - span <= m <= t - lead] or [m for m in mids if m <= t - lead] or [max(0.0, t - lead)]
        return round(max(ok), 3)

    def in_word(self, t: float) -> dict | None:
        """the word sounding at time t (None in a gap)."""
        for w in self.words:
            if w["t0"] < t < w["t1"]:
                return w
        return None

    def phrases(self, t0: float, t1: float, gap: float = .35, lo: float = -.02, max_len: float = 1.6,
                keep: list | None = None) -> list[dict]:
        """the window's words grouped into phrases: [{t0, t1, text}] in song time. A phrase ends at a gap > `gap` s, after
        a word ending in punctuation (the lyric sheet's own phrasing), or before it would exceed `max_len` s.
        keep: only these words ([[t0, t1, w], ...], e.g. a clip's her_words)."""
        out: list[dict] = []
        brk = True
        ks = {round(float(k[0]), 3) for k in keep} if keep else None
        for w in self.words_starting_in(t0, t1, lo):
            if ks is not None and round(w["t0"], 3) not in ks:
                continue
            txt = w["text"] or w.get("w", "")
            if out and not brk and w["t0"] - out[-1]["t1"] <= gap and w["t1"] - out[-1]["t0"] <= max_len:
                out[-1]["t1"] = w["t1"]
                out[-1]["text"] += " " + txt
            else:
                out.append({"t0": w["t0"], "t1": w["t1"], "text": txt})
            brk = bool(txt) and txt[-1] in PUNCT_END
        return out

    # ---- beats / hits ----
    def beats(self) -> list[float]:
        return [float(x if isinstance(x, (int, float)) else x["t"]) for x in self.beats_doc.get("beats", [])]

    def downbeats(self) -> list[float]:
        return [float(x if isinstance(x, (int, float)) else x["t"]) for x in self.beats_doc.get("downbeats", [])]

    def eighths(self) -> list[float]:
        bt = self.beats()
        mids = [(a + b) / 2 for a, b in zip(bt[:-1], bt[1:])]
        return sorted(bt + mids)

    def last_beat_before(self, t: float) -> float | None:
        c = [b for b in self.beats() if b <= t]
        return max(c) if c else None

    def last_eighth_before(self, t: float) -> float | None:
        c = [b for b in self.eighths() if b <= t]
        return max(c) if c else None

    def kicks(self, t0: float, t1: float) -> list[float]:
        return [float(k) for k in self.hits_doc.get("kick", []) if t0 <= float(k) < t1]

    def downbeats_in(self, t0: float, t1: float) -> list[float]:
        return [b for b in self.downbeats() if t0 <= b < t1]
