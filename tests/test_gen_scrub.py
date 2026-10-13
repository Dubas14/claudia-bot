"""Nothing shipped by the gen/sync modules may carry private identifiers (scrub rule, ARCHITECTURE §7.12).

The private words (hosts, the tailnet, the owner's initials and profile code, the taboo word) are checked by hash with
the shared scanner in tests/scrublist.py; the reference videos' project slugs must not be hard-coded here either.
"""
from __future__ import annotations

import codecs
import re
from pathlib import Path

import scrublist

ROOT = Path(__file__).resolve().parent.parent
FILES = [*ROOT.glob("slop/gen/**/*.py"), *ROOT.glob("slop/sync/**/*.py"), *ROOT.glob("tests/test_gen*.py"),
         *ROOT.glob("tests/test_sync*.py"), *ROOT.glob("tests/fixtures/gen/**/*"), *ROOT.glob("tests/fixtures/sync/**/*")]

# ROT13 so this file does not spell them: a private /opt path, provider job ids, the reference videos' project slugs
PATTERNS = [codecs.decode(p, "rot13") for p in (r"/bcg/", r"tra-ivq-\q{10}-", r"rfpncr-irybpvgl", r"pybqlffrl",
                                                 r"fhcrecrefhnfvba", r"\.gf\.arg\o")]


def test_no_private_identifiers():
    pats = [re.compile(p, re.I) for p in PATTERNS]
    bad = []
    for f in FILES:
        if not f.is_file() or f.suffix in (".pyc",) or "__pycache__" in f.parts:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        bad += [f"{f.relative_to(ROOT)}: {h}" for h in scrublist.private_hits(text)]
        bad += [f"{f.relative_to(ROOT)}: pattern {i}" for i, p in enumerate(pats) if p.search(text)]
    assert not bad, bad
