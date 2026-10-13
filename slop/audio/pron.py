"""Pronunciation helpers shared by the aligner and the scansion model: numbers as words, letter names, the CMU
Pronouncing Dictionary (loaded lazily) and a spelling fallback.

CMUdict source order: (1) the `cmudict` Python package if installed; (2) a cached copy of the raw dictionary in
$SLOP_HOME/cache/cmudict/cmudict.dict; (3) a one-time download of that raw file from github.com/cmusphinx/cmudict
(BSD-2-Clause data, ~3.6 MB; skipped when SLOP_OFFLINE=1); (4) none - then pronunciations fall back to g2p_en (if
installed) and to a rule-based syllable guess, and the lint report says "pronunciation guessed" for those words.
"""
from __future__ import annotations

import functools
import os
import re
from pathlib import Path

CMU_URL = "https://raw.githubusercontent.com/cmusphinx/cmudict/master/cmudict.dict"

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def num_words(s: str) -> str:
    """'2077' -> 'twenty seventy seven', '157' -> 'one fifty seven', '11.2' -> 'eleven point two', '18' -> 'eighteen'.
    (Port of the scansion helper: years and 3-digit numbers read the way people say them.)"""
    s = s.replace(",", "")
    if "." in s:
        a, b = s.split(".", 1)
        return (num_words(a) if a else "") + " point " + " ".join(ONES[int(c)] for c in b if c.isdigit())
    n = int(s)

    def two(k: int) -> str:
        return ONES[k] if k < 20 else TENS[k // 10] + ("" if k % 10 == 0 else " " + ONES[k % 10])

    if n < 100:
        return two(n)
    if 1100 <= n <= 2099 and len(s) == 4:                                  # read like a year
        hi, lo = divmod(n, 100)
        return two(hi) + (" hundred" if lo == 0 else (" oh " + ONES[lo] if lo < 10 else " " + two(lo)))
    if n < 1000:
        h, r = divmod(n, 100)
        return ONES[h] + (" hundred" if r == 0 else " " + two(r))
    if n >= 10 ** 15:
        return " ".join(ONES[int(c)] for c in s)
    for div, name in ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= div:
            th, r = divmod(n, div)
            return num_words(str(th)) + " " + name + ("" if r == 0 else " " + num_words(str(r)))
    return two(n)


SYMBOL_WORDS = {"%": "percent", "&": "and", "+": "plus", "=": "equals", "@": "at", "#": "number", "$": "dollars",
                "€": "euros", "£": "pounds", "/": "slash", "−": "minus", "×": "times"}


def spell_numbers(text: str) -> str:
    """Replace digit groups (and %, &, +, =) in a line with words as most singers would say them. A suggestion only:
    '$60B' -> 'sixty billion dollars' needs a human; this gives 'dollars sixty B'."""
    out = text
    out = re.sub(r"(\d+(?:[.,]\d+)*)\s*%", lambda m: num_words(m.group(1)) + " percent", out)
    out = re.sub(r"\d+(?:\.\d+)?", lambda m: " " + num_words(m.group(0)) + " ", out)
    for k, v in SYMBOL_WORDS.items():
        if k in ("$", "/"):
            continue
        out = out.replace(k, f" {v} ")
    return re.sub(r"\s+", " ", out).strip()


# ---------------------------------------------------------------- CMUdict
def _cmu_cache() -> Path:
    from slop.config import cache_dir
    return cache_dir("cmudict") / "cmudict.dict"


def parse_cmu(text: str) -> dict[str, list[list[str]]]:
    d: dict[str, list[list[str]]] = {}
    for line in text.splitlines():
        if not line or line.startswith(";;;"):
            continue
        line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 2:
            continue
        w = re.sub(r"\(\d+\)$", "", parts[0].lower())
        d.setdefault(w, []).append(parts[1:])
    return d


def fetch_cmu(dest: Path | None = None, timeout: float = 30.0) -> Path:
    """Download the raw CMU dictionary (BSD-2-Clause) once into the cache."""
    import requests
    dest = dest or _cmu_cache()
    r = requests.get(CMU_URL, timeout=timeout)
    r.raise_for_status()
    if "abandon" not in r.text[:200000]:
        raise RuntimeError("unexpected content from " + CMU_URL)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_text(r.text, encoding="utf-8")
    tmp.replace(dest)
    return dest


@functools.lru_cache(None)
def cmu() -> dict[str, list[list[str]]]:
    """The CMU dictionary {word: [phones...]}, or {} when unavailable (see module docstring)."""
    try:
        import cmudict  # type: ignore
        return cmudict.dict()
    except Exception:
        pass
    try:
        p = _cmu_cache()
        if not p.exists() and os.environ.get("SLOP_OFFLINE", "") not in ("1", "true", "yes"):
            fetch_cmu(p)
        if p.exists():
            return parse_cmu(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        pass
    return {}


def cmu_if_available() -> dict[str, list[list[str]]]:
    """CMUdict only if it is already installed or cached (never downloads)."""
    if cmu.cache_info().currsize:
        return cmu()
    try:
        import cmudict  # type: ignore  # noqa: F401
        return cmu()
    except Exception:
        pass
    return cmu() if _cmu_cache().exists() else {}


def cmu_status() -> str:
    d = cmu()
    return f"cmudict ({len(d)} words)" if d else "no cmudict (pronunciations guessed by spelling rules)"


@functools.lru_cache(None)
def g2p():
    """g2p_en if installed (optional, Apache-2.0). Never auto-installed."""
    try:
        from g2p_en import G2p  # type: ignore
        return G2p()
    except Exception:
        return None


def guess_phones(w: str) -> list[str]:
    """Rule-based fallback: one syllable per vowel group (silent final e, -le, -ed, -es handled), stress on the
    first syllable - unless the word starts with a typical unstressed prefix (a-, be-, re-, de-, con-...)."""
    w = re.sub(r"[^a-z]", "", w.lower()) or "a"
    groups = [m.span() for m in re.finditer(r"[aeiouy]+", w)]
    n = len(groups)
    if n > 1 and w.endswith("e") and not w.endswith(("le", "ee", "ye")) and groups[-1] == (len(w) - 1, len(w)):
        n -= 1                                                        # silent e: make, slope
    if n > 1 and re.search(r"[^aeiouy]ed$", w) and not re.search(r"[td]ed$", w):
        n -= 1                                                        # walked, played
    if n > 1 and re.search(r"[^aeiouy]es$", w) and not re.search(r"(s|x|z|ch|sh|ge|ce)es$", w):
        n -= 1                                                        # makes, slopes
    n = max(1, n)
    first = 1 if (n > 1 and re.match(r"(a|be|re|de|con|com|pre|ex|in|un|en|em)[^aeiouy]", w) and n >= 2) else 0
    return [("AH1" if i == first else "AH0") for i in range(n)]
