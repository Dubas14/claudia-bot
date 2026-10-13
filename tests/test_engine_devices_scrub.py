"""Nothing engine-devices ships names the owner, his Midjourney profile code, hosts, the tailnet or the banned word, and
no reference-video value is hard-coded in the device library, the default renderer, DEVICES.md's examples or the test
fixtures (labels come from params; examples are fresh and generic; precedents are described, not quoted).

Every banned token and phrase is stored as a SHA-256 digest (the token list is the same as tests/test_engine_scrub.py),
so this test ships none of them. Phrases are matched on normalised text (lower case, every run of non-alphanumerics a
single space), as word n-grams. Scanned: engine/src/shots.js, engine/src/devices/, engine/DEVICES.md,
tests/fixtures/engine_devices/, this module's tests.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "engine" / "src" / "shots.js", ROOT / "engine" / "DEVICES.md",
         *sorted((ROOT / "engine" / "src" / "devices").glob("*.js")),
         *sorted((ROOT / "tests" / "fixtures" / "engine_devices").glob("*.py")),
         *sorted((ROOT / "tests").glob("test_engine_devices*.py"))]
BANNED_CI = {
    "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700",
    "a537830719fd3767b1898d8f730256de94f9c69b287704435e69104a6cca2f39",
    "65a9200f9247b5eb6ed0c449c89cd31913441d3b516acdefe6c7479fc4f56d04",
    "9702d9de853966388d3fbbb1692969bb672e2a628e7a2d18bb00ea6904b3e4e2",
    "ae679821f0649c15f6c5181130efecf6ca5e4eb04e469b87510b48aa4725a449",
    "fe0f6d7131c18323e3e8cba5ccc0e079ca6ebf795787717f3e6e0bcc5ad0262e",
}
BANNED_DOMAIN = "9c2c431ce731298cb3b0a8d47a11d98efe8c606df8d5ecc49f471e1e0e970f8f"
BANNED_CS = {"0df9e03357ae3a2b287a404094d2d61aa6ec114eb8bb1c92a6c2154a03dc438a"}
# the reference videos' own strings (their lyrics, labels, serials, UI copy) found in the original pipeline's project folders —
# never a device default, a registered example, a DEVICES.md example or a fixture string
STORY = {
    "a723e5f7083c5d32aa64754d6d1f52dcbf28e8b2b94ff3636f3baa32d7553ff3", "c996f8fea031ba6035220189d70902fe4c029af0f36db9a0882de4fdc957d822",
    "20e00956bd4963f7619c0a672d792febc0463598f3830352141dbfd45b952dc2", "f32c1246cc7d651d26e306d51e814250d0cceb0b1f032ea1c7fe0f42d901b227",
    "cbc29c0b66b3997f39c03c871e0e2ce26f8bb126b92ff1b797a201e8b34520ec", "73e8099a3d1da805f6475c232f4f162223eb49a318f0e2450be8c406bab05fcb",
    "97ded2db02e023ce03564ae62a4f569345276a8f0d1ccca7646360c2fd9d0969", "8639b2f0ea043326935729988517edb5c0c7d3c84b9f1cbc29fdec50101e1523",
    "bb22bd26da91669b1a9f846f7e08a3d6784965e713f49dd6f51f12e858c0932c", "a7197b2777d43194dea6e70a9b8622b3a50c506628c0ab842387284fca91fabe",
    "dba3cc8c52b9a5307ac5cb6795cc5cc986040ba4feada5d09496114d4bda5ef9", "dcafe4135596992fec8db9482219be80e44183b0371c05f7e379f3a448981c3c",
    "61933d3774170c68e3ae3ab49f20ca22db83a6a202410ffa6475b25ab44bb4da", "0e459f77167971c4c7ef8b9a1c7c2ee91498529993371f71d6a48dbf1c8ea5d2",
    "6199dd884aa2a1888491374d9d69fae5f5870e5858d0b36dbd7da5f29b5b4c79", "f0c44e083dc559dca977a872229352c927a4b177167fd93326ad21e338770d13",
    "bda138ecaa253a6fa2dffbea41fd8b0810d858935a79904184137eff51666ff6", "663621fd19aa45da23353cae13616b2ad6d92541f8424f0722d5d1310a5a58c5",
    "39058dcfba093aec14b49efedbd17514d4806bc91a7ab99fc55aa91423bf90ed", "384be7ef21abc4362cb47cd8112de44b901aa6750201ee2ee66c0441c9e7321f",
    "1d14866e9f2c61dc889247d8303af6feda8bbf936328c67eb780a90054623623", "4c9ce16430ede6454c2dadb24339819bc03e65f370b2838cf2439a7eb9b116a0",
    "97f7c3ef0891335b23709e8972f49ca06cac470cefa63d21304e70acf61bcffb", "8b8a1af863a056cdd0d8c758540dd76edcd64f08e9fa6679298025884a529e5f",
    "7662c05773552e5766301c0c24ee0ecfb077adcda205dcd6561ec394d106af99", "d225ac8deddee5cebb01c1967b550ac9ff985ffafba37aca87a932ab288d5676",
    "a26c1306dfb31ed39052a024f326cffa275ce57dde8edcc60fdb8e0d6cbfa5e7", "3181424903bfb4b5336b01a9f69cf93d99f40e8a93783e75ea0342e124d0ac55",
    "8a15017a8d66b7e0b1e942bd16a9ce936de13428fe726b114162535958aad388", "3e35df8a23e9e2094c8d7d2b8d0e58c64ab3a6c5e31881db1d567e4dc780cfb1",
    "62cc9f91494fa9f75efac4e2645473435290ef084cba53aa373c94447fb3e5e2", "b61e5b0af75922766762b2064ffa93cfad9c034705567ededc86d0e8b1d919a8",
    "419d768377214e9876c181fa158f4d8b56b35190a60118bc0dbbca8309366326",
}
# the reference videos' titles, project slugs and serials: fine in DEVICES.md's prose (it describes the precedents), never
# in code or fixtures
TITLES = {
    "b09fdd97d068ce07c20c881e211fd6c1e4d18e0fe434a06db55b89aeff22f425", "018770dd13f05394c1f9a473925ff230c3f413179427599594af1255ea6a8566",
    "0bf5e5a162c444214a7a58f43da69cfaad89a672ab91beebd1aa774bd0370dda", "9e50bcfc2ad0d4aade09564ed9fd5e832d252e477e20f821aacda3c314bca6b8",
    "fad46018e58d6ab123d5b4ba85f8f7a84d1b123680368c30351288023506b505", "0aed6243929a7b7e19dd3de414d5b190f682c191a07530479a753ad882d7f40d",
}
H = lambda s: hashlib.sha256(s.encode()).hexdigest()   # noqa: E731


def _ngrams(text: str, nmax: int = 5) -> set[str]:
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return {H(" ".join(words[i:i + n])) for n in range(1, nmax + 1) for i in range(len(words) - n + 1)}


def test_files_exist():
    names = {p.name for p in FILES if p.is_file()}
    assert {"shots.js", "DEVICES.md", "_base.js", "index.js", "type.js", "treat.js", "trans.js"} <= names


def test_no_scrubbed_tokens():
    bad = []
    for p in FILES:
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        for tok in set(re.findall(r"[A-Za-z0-9]+", txt)):
            if H(tok.lower()) in BANNED_CI or H(tok) in BANNED_CS:
                bad.append(f"{p.relative_to(ROOT)}: a banned token ({tok[:2]}…)")
        for a, b in re.findall(r"([A-Za-z0-9-]+)\.([A-Za-z0-9-]+)", txt):
            if H(f"{a}.{b}".lower()) == BANNED_DOMAIN:
                bad.append(f"{p.relative_to(ROOT)}: the tailnet domain")
    assert not bad, "\n".join(sorted(set(bad)))


def test_no_reference_video_strings():
    """No reference-video lyric, label, serial or UI string in the code, DEVICES.md's examples, or the fixtures."""
    bad = []
    for p in FILES:
        if not p.is_file():
            continue
        grams = _ngrams(p.read_text(encoding="utf-8", errors="replace"))
        hits = len(grams & STORY) + (0 if p.suffix == ".md" else len(grams & TITLES))
        if hits:
            bad.append(f"{p.relative_to(ROOT)}: {hits} reference-video string(s) (hashed list in this test)")
    assert not bad, "\n".join(bad)


def test_no_reference_video_constants_in_code():
    """No reference-video tempo/length constants or source-machine paths in the JS."""
    pat = re.compile(r"132\.7|306\.4|189\.72|/opt/|'MONTHS'")
    bad = [f"{p.name}: {m.group(0)}" for p in FILES if p.suffix == ".js" for m in pat.finditer(p.read_text(encoding="utf-8"))]
    assert not bad, bad


def test_no_nondeterminism_in_code():
    """Frames are pure functions of t: no Math.random, no Date, no performance.now in the device library or renderer."""
    pat = re.compile(r"Math\.random|\bDate\b|performance\.now")
    bad = [f"{p.name}: {m.group(0)}" for p in FILES if p.suffix == ".js"
           for m in pat.finditer(re.sub(r"//[^\n]*", "", p.read_text(encoding="utf-8")))]
    assert not bad, bad
