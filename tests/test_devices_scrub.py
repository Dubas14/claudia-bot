"""devices track: the same scrub as tests/test_engine_devices_scrub.py (names, hosts, the tailnet, the banned word, the
reference videos' strings — all stored there as SHA-256 digests) over this track's own test modules,
tests/test_devices_*.py, which that module's file list does not reach."""
from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "tests").glob("test_devices_*.py"))


def _scrub():
    spec = importlib.util.spec_from_file_location("engine_devices_scrub", ROOT / "tests" / "test_engine_devices_scrub.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_files_exist():
    assert {p.name for p in FILES} >= {"test_devices_explain.py", "test_devices_treatments.py", "test_devices_params.py", "test_devices_scrub.py"}


def test_no_scrubbed_tokens_or_reference_strings():
    S = _scrub()
    H = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    bad = []
    for p in FILES:
        txt = p.read_text(encoding="utf-8", errors="replace")
        for tok in set(re.findall(r"[A-Za-z0-9]+", txt)):
            if H(tok.lower()) in S.BANNED_CI or H(tok) in S.BANNED_CS:
                bad.append(f"{p.name}: a banned token ({tok[:2]}…)")
        for a, b in re.findall(r"([A-Za-z0-9-]+)\.([A-Za-z0-9-]+)", txt):
            if H(f"{a}.{b}".lower()) == S.BANNED_DOMAIN:
                bad.append(f"{p.name}: the tailnet domain")
        grams = S._ngrams(txt)
        if grams & S.STORY or grams & S.TITLES:
            bad.append(f"{p.name}: {len(grams & S.STORY) + len(grams & S.TITLES)} reference-video string(s) (hashed list in test_engine_devices_scrub.py)")
    assert not bad, "\n".join(sorted(set(bad)))
