"""tools/scansion.py, the director's lyric scorer: it runs on a lyric sheet and prints both numbers per section and
for the song. Needs cmudict (bin/setup.sh installs it); skipped without it."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "scansion.py"
SAMPLE = ROOT / "tests" / "fixtures" / "lyrics" / "sample.md"

pytestmark = pytest.mark.skipif(importlib.util.find_spec("cmudict") is None, reason="needs cmudict")


def run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, timeout=120)


def test_lyric_prints_both_numbers_per_section_and_for_the_song():
    r = run("lyric", str(SAMPLE), "--brief")
    assert r.returncode == 0, r.stderr
    secs = re.findall(r"== (.+?)\s+\[(spoken|sung|chant)\]\s+SCANSION (\d+) .*?ASSONANCE (\d+)", r.stdout, re.S)
    assert [(s[0], s[1]) for s in secs] == [("Verse 1", "spoken"), ("Chorus", "sung")], r.stdout
    song = re.search(r"song\s+SCANSION (\d+)\s+ASSONANCE (\d+)", r.stdout)
    assert song and all(0 <= int(x) <= 100 for x in song.groups())


def test_lyric_detail_names_each_line_end_and_its_partner():
    r = run("lyric", str(SAMPLE))
    assert r.returncode == 0, r.stderr
    assert "\u2194" in r.stdout and "end " in r.stdout


def test_ban_json_next_to_the_lyrics_is_linted(tmp_path):
    (tmp_path / "LYRICS.md").write_text("[Verse - spoken]\nWe walk the catwalk to the end of the line.\n", encoding="utf-8")
    (tmp_path / "ban.json").write_text('{"catwalk": "say show"}', encoding="utf-8")
    r = run("score", str(tmp_path / "LYRICS.md"))
    assert r.returncode == 0, r.stderr
    assert "catwalk" in r.stdout and "say show" in r.stdout


def test_the_shipped_scorer_names_no_private_words():
    text = TOOL.read_text(encoding="utf-8")
    assert not re.search(r"\bRJ\b", text)
    sys.path.insert(0, str(ROOT / "tests"))
    import scrublist
    assert scrublist.private_hits(text) == []
