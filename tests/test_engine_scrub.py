"""Nothing the engine module ships names the owner, his Midjourney profile code, hosts, the tailnet or the banned word.

The banned tokens are stored as SHA-256 digests so this test does not ship them either. Scanned: the engine-core files
(engine/index.html, README.md, src/<14 core files>.js, fonts/), slop/render/, tests/fixtures/engine/ — not the
engine-devices files (src/shots.js, src/devices/**), which that module checks itself.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINE = ["core", "media", "plate3d", "post", "trans", "timeline", "kinetic", "chrome", "annot", "ink", "occ", "hits", "seq", "glass"]
OWNED = [ROOT / "engine" / "index.html", ROOT / "engine" / "README.md", *[ROOT / "engine" / "src" / f"{n}.js" for n in MINE]]
SCAN = [ROOT / "engine" / "fonts", ROOT / "slop" / "render", ROOT / "tests" / "fixtures" / "engine"]
TEXT = {".js", ".html", ".md", ".py", ".json", ".txt", ".css", ".sh"}
# sha256 of lowercased tokens: the profile code, three host names, the banned word, the tailnet id
BANNED_CI = {
    "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700",
    "a537830719fd3767b1898d8f730256de94f9c69b287704435e69104a6cca2f39",
    "65a9200f9247b5eb6ed0c449c89cd31913441d3b516acdefe6c7479fc4f56d04",
    "9702d9de853966388d3fbbb1692969bb672e2a628e7a2d18bb00ea6904b3e4e2",
    "ae679821f0649c15f6c5181130efecf6ca5e4eb04e469b87510b48aa4725a449",
    "fe0f6d7131c18323e3e8cba5ccc0e079ca6ebf795787717f3e6e0bcc5ad0262e",
}
BANNED_DOMAIN = "9c2c431ce731298cb3b0a8d47a11d98efe8c606df8d5ecc49f471e1e0e970f8f"   # the tailnet's DNS suffix
BANNED_CS = {"0df9e03357ae3a2b287a404094d2d61aa6ec114eb8bb1c92a6c2154a03dc438a"}      # the owner's initials, exact case
H = lambda s: hashlib.sha256(s.encode()).hexdigest()   # noqa: E731
REL = lambda p: str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)   # noqa: E731


def files():
    yield from (p for p in OWNED if p.is_file())
    for base in SCAN:
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in TEXT and "__pycache__" not in p.parts:
                yield p


def test_no_scrubbed_tokens():
    bad = []
    for p in files():
        txt = p.read_text(encoding="utf-8", errors="replace")
        for tok in set(re.findall(r"[A-Za-z0-9]+", txt)):
            if H(tok.lower()) in BANNED_CI or H(tok) in BANNED_CS:
                bad.append(f"{REL(p)}: a banned token ({tok[:2]}…)")
        for dotted in re.findall(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", txt):
            parts = dotted.lower().split(".")
            if any(H(f"{a}.{b}") == BANNED_DOMAIN for a, b in zip(parts, parts[1:])):
                bad.append(f"{REL(p)}: the tailnet domain")
    assert not bad, "\n".join(sorted(set(bad)))


def test_no_reference_video_hardcodes_in_engine():
    pat = re.compile(r"132\.7|306\.4|escape-velocity|LOOK 01 / 12|EV-27-0001|'MONTHS'|CLODYSSEY|/opt/")
    bad = [f"{p.name}: {m.group(0)}" for p in OWNED if p.suffix == ".js"
           for m in pat.finditer(p.read_text(encoding="utf-8"))]
    assert not bad, bad
