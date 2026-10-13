"""Release checks across modules: one lyric-line parser, the licence and install facts, line endings, the public
architecture doc, and the docs naming every command the CLI has."""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/anabologyco-maker/claudia-bot"
INSTALL = f"git clone {REPO_URL} /workspace/claudia && bash /workspace/claudia/bin/setup.sh --minimal"

TRICKY = """[Intro]

  Signals. Systems. Strangers.
[Verse 1: spoken]
we ship it at plus twenty five percent tonight
# a hash line is a lyric line (only blank and [ lines are skipped)
[an unclosed bracket note
   go
[Instrumental]
the long room holds its breath again
"""
EXPECTED = ["Signals. Systems. Strangers.", "we ship it at plus twenty five percent tonight",
            "# a hash line is a lyric line (only blank and [ lines are skipped)", "go",
            "the long room holds its breath again"]


def test_one_lyric_line_parser_everywhere(tmp_path):
    """Every module counts lyric lines the same way (slop.util.read_lyric_lines), so line N is the same line in the
    aligner, the display tokens, the board and the font A/B."""
    from slop import util
    from slop.audio import align, display, sections
    from slop.board import common
    from slop.taste import fonts

    proj = tmp_path / "p"
    (proj / "lyrics").mkdir(parents=True)
    (proj / "lyrics" / "lyrics.txt").write_text(TRICKY, encoding="utf-8")
    (proj / "lyrics" / "display.txt").write_text(TRICKY, encoding="utf-8")
    assert util.lyric_lines(TRICKY) == EXPECTED
    assert util.read_lyric_lines(proj / "lyrics" / "lyrics.txt") == EXPECTED
    assert align.read_sheet(proj / "lyrics" / "lyrics.txt") == EXPECTED
    assert display.read_display(proj / "lyrics" / "display.txt") == EXPECTED
    assert common.read_display(proj) == dict(enumerate(EXPECTED))
    blocks = sections.parse_blocks(proj / "lyrics" / "lyrics.txt")
    assert sorted(i for b in blocks for i in b["lines"]) == list(range(len(EXPECTED)))
    lines, src = fonts.read_lines(proj, None, 20)
    assert src == "lyrics/display.txt"
    assert set(lines) <= set(EXPECTED) and "go" not in lines            # the A/B keeps 2-9 word lines only
    assert util.read_lyric_lines(proj / "missing.txt") == []


def test_licence_is_mit_by_the_public_name():
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert lic.startswith("MIT License") and "Copyright (c) 2026 anabology" in lic
    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["license"] == "MIT" and meta["license-files"] == ["LICENSE"]
    assert meta["authors"] == [{"name": "anabology"}]
    assert meta["urls"]["Repository"] == REPO_URL
    assert not any(c.startswith("License ::") for c in meta.get("classifiers", [])), "PEP 639: the expression only"


def test_readme_has_the_repo_url_and_the_one_line_install():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert INSTALL in readme and "<repo-url>" not in readme
    assert "docs/ARCHITECTURE.md" in readme


def test_gitattributes_keep_lf_and_binaries():
    ga = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\* text=auto eol=lf$", ga)
    for ext in ("png", "jpg", "ttf", "otf", "woff2", "mp3", "wav", "mp4"):
        assert re.search(rf"(?m)^\*\.{ext} binary$", ga), ext


def test_shell_entry_points_have_lf_endings():
    for rel in ("bin/slop", "bin/setup.sh"):
        assert b"\r\n" not in (ROOT / rel).read_bytes(), f"{rel} has CRLF line endings"


def test_public_architecture_doc():
    arch = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert not (ROOT / "ARCHITECTURE.md").exists(), "the private build contract must not ship"
    for sec in ("## 1.", "## 2.", "### 3.1", "### 3.2", "### 4.1", "### 4.5", "### 4.6", "## 5.", "## 6.", "## 7.",
                "## 7b.", "## 8."):
        assert sec in arch, f"docs/ARCHITECTURE.md lost section {sec} (code and docs cite it by number)"
    assert "iec61966-2-1" in arch and "BT.709 primaries and matrix" in arch          # rule 10, as the encoder tags it


def test_review_schema_has_the_wiring_check_in_the_literal():
    src = (ROOT / "templates" / "workflows" / "chapters.js").read_text(encoding="utf-8")
    lit = src[src.index("const REVIEW = "):src.index("\nconst SEVERITY")]
    assert "wired:" in lit and "required: ['lyric_gate', 'wired', 'sheets']" in lit
    assert "REVIEW.properties.checks" not in src, "the schema is one literal (docs/80 copies it verbatim)"


def test_muse_is_described_with_public_facts():
    for rel in ("runner/README.md", "runner/deleg.mjs", "docs/95-delegation.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "dev.meta.ai" in text, f"{rel}: say where Muse Code is installed from"
        assert not re.search(r"(?i)meta (accounts|employees)", text), rel


def _cli_paths() -> set[str]:
    """Every `slop <group> <command>` path the router builds."""
    import argparse

    from slop.cli import build_parser

    def subs(p):
        for a in p._actions:
            if isinstance(a, argparse._SubParsersAction):
                return a
        return None

    out = set()
    root = subs(build_parser())
    for name, p in root.choices.items():
        sa = subs(p)
        if sa is None:
            out.add(name)
            continue
        helps = {ca.dest for ca in sa._choices_actions}
        for n2, p2 in sa.choices.items():
            if n2 not in helps:
                continue
            sa3 = subs(p2)
            if sa3 is None:
                out.add(f"{name} {n2}")
            else:
                h3 = {ca.dest for ca in sa3._choices_actions}
                out |= {f"{name} {n2} {n3}" for n3 in sa3.choices if n3 in h3}
    return out


def test_readme_command_index_names_every_command():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = sorted(c for c in _cli_paths() if f"`slop {c}" not in readme)
    assert not missing, f"README's command index misses: {missing} (regenerate it: python tests/gen_cmdref.py)"


def test_docs_name_the_new_commands():
    """Each command the hardening tracks added is taught in the playbook of its stage."""
    want = {
        "00-overview.md": ["slop --project my-song next", "job start --", "job wait", "fetch", "SLOP_FREE_ONLY",
                           "review scan-sheets", "render encode --share"],
        "20-analysis.md": ["song sections", "song bars", "lyrics check"],
        "30-taste.md": ["taste sheet", "taste record", "taste verdict", "taste apply", "taste use"],
        "40-storyboard.md": ["board set", "board fill", "board device add", "board device kinds"],
        "51-plates-api.md": ["gen image --jobs", "gen estimate --kind edit", "plates ingest --url", "plates box"],
        "80-review-qa.md": ["review scan-sheets", "review record", "review status"],
        "90-master-publish.md": ["render encode --share", "render clean"],
    }
    bad = []
    for doc, needles in want.items():
        text = re.sub(r"\s+", " ", (ROOT / "docs" / doc).read_text(encoding="utf-8"))
        bad += [f"{doc}: {n}" for n in needles if n not in text]
    assert not bad, bad


def test_command_reference_is_current():
    """README's module tables are generated from the real parsers (tests/gen_cmdref.py); --check fails on drift."""
    import subprocess
    gen = ROOT / "tests" / "gen_cmdref.py"
    r = subprocess.run([sys.executable, str(gen), "--check"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def test_auto_treatment_passes_the_audit_and_never_repeats(tmp_path):
    """`board set --treatment auto` (the engine's five-family rotation) is a written choice, not a TODO: the audit
    accepts it on consecutive 2.5D shots; an empty treatment still fails."""
    sys.path.insert(0, str(ROOT / "tests/fixtures/board"))
    import board_synth as synth

    from slop.board import audit, draft
    p = synth.make_project(tmp_path)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    idx = [i for i, s in enumerate(S["shots"]) if s["motion_tier"] == "plate3d"]
    assert len(idx) >= 2
    for i in idx:
        S["shots"][i]["treatment"] = "auto"
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert rep["gates"]["treatments"]["ok"], rep["gates"]["treatments"]
    S["shots"][idx[0]]["treatment"] = ""
    synth.write_json(p / "board/shots.json", S)
    rep = audit.audit(p)
    assert not rep["gates"]["treatments"]["ok"] and "needs a treatment" in " ".join(rep["gates"]["treatments"]["fails"])


def test_paid_embedding_without_a_project_honours_the_spend_lock(monkeypatch):
    """A paid OpenRouter embedding call made outside a project still stops under SLOP_FREE_ONLY (ledger lock)."""
    from slop.config import SlopError
    from slop.taste import embed as E
    monkeypatch.setenv("SLOP_FREE_ONLY", "1")
    emb = E.OpenRouterEmbedder.__new__(E.OpenRouterEmbedder)      # no network: the lock fires before any request
    emb.model, emb.pdir, emb.yes, emb._last, emb.spent = "some/paid-embedding-model", None, True, 0.0, 0.0
    with pytest.raises(SlopError, match="SLOP_FREE_ONLY"):
        emb._post(["x"], "text", {"texts": 1})


def test_review_hints_name_the_project(tmp_path, capsys):
    """`slop review …` prints its next-step hints with --project, like `slop status` does."""
    import json as _json
    sys.path.insert(0, str(ROOT / "tests/fixtures/board"))
    import board_synth as synth

    from slop import cli
    p = synth.make_project(tmp_path)
    rc = cli.main(["--json", "--project", str(p), "review", "status"])
    out = _json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    msg = out.get("error") or out.get("text") or ""
    assert "`slop --project " in msg and "`slop review" not in msg and "`slop edit" not in msg, (rc, msg)
