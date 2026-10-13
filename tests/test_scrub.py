"""Release scrub: nothing the repository ships names the owner, his Midjourney profile code, private hosts or the
tailnet, private paths, the owner's mail address, provider job ids, or the owner's taboo word.

What is scanned: every file `git ls-files --cached --others --exclude-standard` lists (what a commit of the working
tree would ship; without git, the tree minus caches), both its PATH and its CONTENT. Text files are tokenized, and
neighbouring string literals are joined so a word assembled from pieces is found too; binary files (fonts, images) are
scanned for paths, addresses and the longer private words (their metadata is where such strings hide).

The private words live only as SHA-256 digests in tests/scrublist.py (the original pipeline's /opt folder is found by
its hashed name too), so this file ships none of them. A failure names the file, the line and the reason, never the
private word.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

import scrublist as S

ROOT = Path(__file__).resolve().parents[1]

# placeholders that may follow /home/ or a Windows Users folder in examples
PLACEHOLDER_USERS = {"box", "user", "you", "me", "x", "name", "username", "your-name", "yourname", "runner", "ubuntu"}
PATTERNS = [
    (re.compile(r"(?i)\bworkshop[\\/]+(?:slop|claudia)"), "the owner's local checkout path"),
    (re.compile(r"(?i)/mnt/[a-z]/users/"), "a Windows user folder seen from WSL"),
    (re.compile(r"(?i)(?<![\w.])/root/\.(?:claude|codex|config)\b"), "a private home folder"),
    (re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"), "a tailnet (CGNAT 100.64/10) address"),
    (re.compile(r"(?i)midjourney\.com/jobs/[0-9a-f]|cdn\.midjourney\.com/[0-9a-f]{8}-"), "a Midjourney job id"),
    (re.compile(r"\bgen-vid-\d{10}-"), "an OpenRouter video job id"),
    (re.compile(r"sk-or-v1-[0-9a-f]{16,}|\bsk-ant-[A-Za-z0-9_-]{20,}"), "an API key"),
]
WIN_USER = re.compile(r"(?i)\b[A-Z]:(?:\\\\|\\|/)+Users(?:\\\\|\\|/)+([^\\/\s\"'`<>]+)")
OPT_DIR = re.compile(r"/opt/([A-Za-z0-9][A-Za-z0-9_-]*)")
HOME_USER = re.compile(r"(?<![\w.])/home/([a-z_][a-z0-9_-]*)")
# a personal mail address (third-party licence texts carry their authors' addresses: allowed there)
PERSONAL_MAIL = re.compile(r"(?i)\b[A-Za-z0-9._%+-]+@(?:gmail|googlemail|hotmail|outlook|icloud|proton|yahoo)\.[a-z.]+\b")
EMAIL_OK_DIRS = ("engine/fonts/licenses/",)
# the delegation option must be described with public facts only
INTERNAL_WORDING = re.compile(r"(?i)\bMeta (?:accounts|employees) only\b|\bavailable to Meta employees\b|"
                              r"\binternal (?:build|dogfood)\b")
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
NL = "\n"


def shipped_files() -> list[str]:
    """Repo-relative paths a commit of the working tree would ship (tracked + untracked, minus .gitignore'd)."""
    files: list[str] = []
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, timeout=60, check=True).stdout.decode("utf-8", "replace")
        files = sorted({f for f in out.split("\0") if f})
    except (OSError, subprocess.SubprocessError):
        pass
    if not files:                       # no git (a tarball): the tree minus caches
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS and not d.endswith(".egg-info")]
            files += [Path(dirpath, fn).relative_to(ROOT).as_posix() for fn in filenames]
    return sorted(f for f in files if (ROOT / f).is_file() and not (set(Path(f).parts) & SKIP_PARTS))


def scan_text(rel: str, text: str, binary: bool = False) -> list[str]:
    """Problems in one file's text, as 'path:line N: reason' (never the private word itself)."""
    bad = [f"{rel}:{h}" for h in S.private_hits(text, binary)]
    for n, line in enumerate(text.splitlines(), 1):
        reasons = [why for rx, why in PATTERNS if rx.search(line)]
        reasons += ["a Windows user folder" for m in WIN_USER.finditer(line)
                    if (re.sub(r"[^a-z0-9_-]", "", m.group(1).lower()) or "x") not in PLACEHOLDER_USERS]
        reasons += ["the original pipeline's private path" for m in OPT_DIR.finditer(line)
                    if S.H(m.group(1).lower()) in S.BANNED_CI]
        reasons += ["a private /home folder" for m in HOME_USER.finditer(line) if m.group(1) not in PLACEHOLDER_USERS]
        if PERSONAL_MAIL.search(line) and not rel.startswith(EMAIL_OK_DIRS):
            reasons.append("a personal mail address")
        if not binary and "muse" in line.lower() and INTERNAL_WORDING.search(line):
            reasons.append("internal wording about Muse Code (describe it with public facts only)")
        bad += [f"{rel}:line {n}: {r}" for r in sorted(set(reasons))]
    return bad


def _read(p: Path) -> tuple[str, bool]:
    raw = p.read_bytes()
    if b"\0" in raw[:8192]:
        return raw.decode("latin-1"), True
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        return raw.decode("latin-1"), True


FILES = shipped_files()


def test_the_scan_sees_the_whole_tree():
    names = set(FILES)
    assert len(FILES) > 200, f"only {len(FILES)} files listed: is this the repository root?"
    for must in ("README.md", "LICENSE", "bin/setup.sh", "slop/cli.py", "docs/ARCHITECTURE.md", "tests/test_scrub.py",
                 "tests/scrublist.py"):
        assert must in names, f"{must} is not in the shipped file list"


def test_paths_are_clean():
    bad = [f"{rel}: the PATH carries {why}" for rel in FILES for why in S.token_hits(rel.replace("/", " "))]
    assert not bad, NL.join(bad)


@pytest.mark.parametrize("chunk", range(8))
def test_contents_are_clean(chunk):
    bad = []
    for rel in FILES[chunk::8]:
        text, binary = _read(ROOT / rel)
        bad += scan_text(rel, text, binary)
    assert not bad, NL.join(bad)


def test_the_private_contract_is_not_shipped():
    """The build contract with the owner's notes stays outside the repository; docs/ARCHITECTURE.md is the public one."""
    assert "ARCHITECTURE.md" not in FILES and (ROOT / "docs" / "ARCHITECTURE.md").is_file()


def test_the_scanner_catches_what_it_should(monkeypatch):
    """Self-check with harmless stand-ins: planted words are added to the hash list for this test only."""
    monkeypatch.setitem(S.BANNED_CI, S.H("plantedrepo"), "the owner's private repository name")
    monkeypatch.setitem(S.BANNED_CS, S.H("PLX"), "the owner's initials")
    sample = NL.join([
        "see /opt/plantedrepo/video",
        "C:" + "\\" + "Users" + "\\" + "someone" + "\\" + "x.txt",
        "/home/" + "someone" + "/proj",
        "ssh 100." + "100.1.2",
        "id gen-vid" + "-1234567890-abc",
        "a cut by PLX",
        "a wicked candlewick",                          # near misses of a private word stay clean
    ])
    found = scan_text("sample.md", sample)
    reasons = {line.split(": ", 1)[1] for line in found}
    assert reasons == {"the original pipeline's private path", "a Windows user folder", "a private /home folder",
                       "a tailnet (CGNAT 100.64/10) address", "an OpenRouter video job id", "the owner's initials",
                       "the owner's private repository name"}, found
    assert not [f for f in found if f.startswith("sample.md:line 7:")], "a near miss was flagged"
    pieces = 'x = "planted" + "repo"'                   # a private word split into two literals
    assert any("private repository" in h for h in S.private_hits(pieces))
    ok = NL.join(["C:/Users/you/jobs", "C:/Users/.../x", "/home/box/sand-data", "/opt/homebrew/bin",
                  "127.0.0.1 and 10.0.0.1", "astigma" + "@" + "example.com",
                  "git clone https://github.com/anabologyco-maker/claudia-bot"])
    assert scan_text("engine/fonts/licenses/x.txt", ok) == []
