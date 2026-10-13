"""The private words no shipped file may contain, as SHA-256 digests only, and the one scanner every scrub test uses.

Not a test module (pytest collects test_*.py only): `tests/test_scrub.py` runs it over the whole tree, and the module
tests call `private_hits(text)` on their own files. Nothing here spells a private word, not even in parts: a word
assembled from string pieces ("ab" + "cd") is found too, because the scanner also joins neighbouring string literals.
"""
from __future__ import annotations

import hashlib
import re

H = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()  # noqa: E731

# sha256 of the LOWER-CASED token -> why it is banned
BANNED_CI = {
    "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700": "the owner's Midjourney profile code",
    "a537830719fd3767b1898d8f730256de94f9c69b287704435e69104a6cca2f39": "a private host name",
    "65a9200f9247b5eb6ed0c449c89cd31913441d3b516acdefe6c7479fc4f56d04": "a private host name",
    "9702d9de853966388d3fbbb1692969bb672e2a628e7a2d18bb00ea6904b3e4e2": "a private host name",
    "fe0f6d7131c18323e3e8cba5ccc0e079ca6ebf795787717f3e6e0bcc5ad0262e": "the tailnet's name",
    "0d2a1a78af155f27dbc77a32b25d43f974bf1c96cd71b3c930702f2459288216": "a private host folder",
    "cb0eaefae8eacd1d5d385adffc8407215e9f60aab4d53e1174158e71d884a88e": "a private volume name",
    "a189ab606c73e71be38a14dd49c67b45257222a0631397f9555f7a767369435c": "the owner's private repository name",
    "8c5a24e9400550c2ab78a75f840425ab942e0faf92af4809c547fa68a5549ffb": "the owner's OS user name",
    "2b5840744d713425ebcaae5d6dfe4bc680ad0798faf15d52cbb6de854d8c8d7f": "a private project name",
    "ae679821f0649c15f6c5181130efecf6ca5e4eb04e469b87510b48aa4725a449": "the owner's taboo word",
}
# 16-hex prefixes of sha256(lower-cased token), for words known here only by prefix
BANNED_PREFIX = {"aab71a5e61a9015d": "a private host name"}
# sha256 of the token AS WRITTEN (these letters are ordinary in lower case)
BANNED_CS = {
    "0df9e03357ae3a2b287a404094d2d61aa6ec114eb8bb1c92a6c2154a03dc438a": "the owner's initials",
    "37c66a2cfceda4d420a247bb617e5dadfb2d2107fd484fffaacff7bcd72091dc": "a private company name",
}
BANNED_DOMAIN = "9c2c431ce731298cb3b0a8d47a11d98efe8c606df8d5ecc49f471e1e0e970f8f"  # the tailnet's DNS suffix
MAIL_LOCAL = "c0e7c9f31054f1ac234982646d6e0e5cca1f649f5edcb8384795cd878dcf7019"     # the owner's mail address
PROFILE_SHA256 = "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700"  # the owner's Midjourney --profile

TOKEN = re.compile(r"[A-Za-z0-9]+")
HYPHENATED = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]")
DOTTED = re.compile(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")
LITERAL = re.compile(r"\"((?:[^\"\\\n]|\\.)*)\"|'((?:[^'\\\n]|\\.)*)'")


def token_hits(text: str, min_len: int = 1, case_sensitive: bool = True) -> list[str]:
    """Why `text` is private (one reason per banned word found), never the word itself."""
    why = []
    for t in set(TOKEN.findall(text)) | set(HYPHENATED.findall(text)):
        if len(t) < min_len:
            continue
        low = t.lower()
        for c in {low} | ({low[:-1]} if low.endswith("s") and len(low) > 3 else set()):
            h = H(c)
            if h in BANNED_CI:
                why.append(BANNED_CI[h])
            elif h[:16] in BANNED_PREFIX:
                why.append(BANNED_PREFIX[h[:16]])
        if case_sensitive and H(t) in BANNED_CS:
            why.append(BANNED_CS[H(t)])
    for dotted in DOTTED.findall(text):
        parts = dotted.lower().split(".")
        if any(H(f"{a}.{b}") == BANNED_DOMAIN for a, b in zip(parts, parts[1:], strict=False)):
            why.append("the tailnet's DNS suffix")
    for m in EMAIL.finditer(text):
        if H(m.group(1).lower()) == MAIL_LOCAL:
            why.append("the owner's mail address")
    return why


def _unescape(s: str) -> str:
    s = re.sub(r"\\[bBAzZ]", " ", s)          # regex anchors are not letters
    return re.sub(r"\\(.)", r"\1", s)


def joined_literal_hits(line: str) -> list[str]:
    """Banned words spelled across neighbouring string literals on one line ("ab" + "cd", j(["a", "b"]))."""
    lits = [_unescape(a if a is not None else b) for a, b in LITERAL.findall(line)]
    single = {w for lit in lits for w in token_hits(lit)}     # a whole word in one literal is reported elsewhere
    why = []
    for i in range(len(lits)):
        for j in range(i + 2, min(len(lits), i + 8) + 1):
            why += [w for w in token_hits("".join(lits[i:j])) if w not in single]
    return why


def private_hits(text: str, binary: bool = False) -> list[str]:
    """['line N: reason', …] for a file's text: banned tokens (short ones skipped in binary data, where random bytes
    spell them) and words assembled from string pieces."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        reasons = token_hits(line, min_len=5 if binary else 1, case_sensitive=not binary)
        if not binary:
            reasons += joined_literal_hits(line)
        out += [f"line {n}: {r}" for r in sorted(set(reasons))]
    return out
