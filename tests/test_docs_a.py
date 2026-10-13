"""Tests for the docs-a module: docs/00-overview, 10-song, 20-analysis, 30-taste, 40-storyboard.

The docs are the knowledge a weaker model reads before each stage, so the tests check three things:
1. each doc exists, is substantial, and still states the load-bearing facts (numbers, rules, schema names);
2. nothing shipped leaks the owner's identity, private hosts, job ids, profile codes or the owner's taboo word;
3. the Markdown is well-formed for a reader (balanced fences, consistent table columns, JSON examples that parse,
   references only to docs the architecture plans);
4. what the docs tell the operator to run exists: every backticked `slop …` command and each of its `--flags` is in the
   CLI parser, and every device in the storyboard's JSON examples is an engine device whose params it actually reads
   (engine/src/devices/*.js), so a copied example never draws UNDEFINED or a default.
Pure-text tests: no network, no heavy imports, well under a few seconds.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

MY_DOCS = ["00-overview.md", "10-song.md", "20-analysis.md", "30-taste.md", "40-storyboard.md",
           "96-setup-and-hardware.md"]

# docs/ files the architecture contract (§6) plans; references to other doc names are typos
PLANNED_DOCS = {
    "00-overview", "10-song", "20-analysis", "30-taste", "40-storyboard", "50-plates-midjourney", "51-plates-api",
    "60-clips", "61-lipsync", "62-moderation", "70-motion-design", "80-review-qa", "90-master-publish",
    "95-delegation", "96-setup-and-hardware", "99-failures",
}
PLANNED_PREFIXES = {name.split("-", 1)[0] for name in PLANNED_DOCS}
UNIT_WORDS = {"second", "seconds", "minute", "minutes", "bar", "bars", "beat", "beats", "frame", "frames", "tap",
              "taps", "bit", "page", "pages", "shot", "shots", "line", "lines", "word", "words", "year", "day"}

MIN_BYTES = {"00-overview.md": 12_000, "10-song.md": 25_000, "20-analysis.md": 15_000, "30-taste.md": 15_000,
             "40-storyboard.md": 25_000, "96-setup-and-hardware.md": 15_000}

# facts each doc must keep stating (case-insensitive substrings). If you reword a doc, keep these facts in it.
REQUIRED = {
    "00-overview.md": [
        "quick", "studio", "director", "g1 concept", "g2 song by ear", "g3 face", "g4 board", "g5 prompts before spend",
        "g6 v1", "spend is never approved by silence", "quality flag stops all spending", "1.5 %", "--project",
        "slop doctor", "$0.231", "one phase per conversation", "never poll", "ledger", "/api/v1/credits",
        "the twelve non-negotiable rules", "depth-anything-v2-**small**", "out/review.mp4", "slop render encode --review",
        "refuses unless", "board.pace", "<project>/",
    ],
    "10-song.md": [
        "two-bar slot", "\"&\" of beat 2", "beat 4", "10–13 syllables", "7–9", "3.3 syllables", "2.9",
        "rhyme on the beat-4 word", "a g i", "dahrio", "p doom", "exclude", "audio influence", "75 %", "variety",
        "max mode", "weirdness", "style influence", "50 %", "keep current", "one voice per source song", "v6",
        "5:06", "2:19", "bpm lock", "timemap", "wav", "paid plan", "power, enable or train", "lyria", "$0.08",
        "lyria-3-pro-preview", "slop lyrics lint", "never touch a line the owner has locked", "takes.md",
        "a target, not a hard limit", "always refuses without `--yes`", "reference only: no toolkit command",
        "the first match wins",
    ],
    "20-analysis.md": [
        "htdemucs", "wav2vec2", "viterbi", "whisper", "conf ≥ 0.5", "ear-check", "never one bpm", "±30 ms",
        "20 s windows every 5 s", "downbeat", "downbeat_phase", "hits.json", "45 ms", "text|n", "|0",
        "display consumes", "slop render lyrics", "does **not** prove", "92.5 %", "letters", "slop analyze",
        "slop song ingest", "manual fixes", "`verylow`", "11 of the 12", "a low-energy start alone", "--init --force",
        "whisper_map", "chord-change vote", "lyrics/adlibs.json", "`w2v-low`", "`w2v+sung`",
    ],
    "30-taste.md": [
        "150", "≈ 7 min", "40 cold-start", "4–6 repeats", "15 % pure exploration", "1 card in 7", "style frames",
        "counterbalance", "first slot", "+0.86", "second slot", "taste-tokens.json", "verdicts.jsonl",
        "% of the canvas", "native", "real graphics", "verdict on a finished piece", "way too.. gray",
        "director bar", "≈ 7.0", "null or empty review is a failure", "never crawl", "30 requests a minute",
        "never edit `taste-tokens.json` by hand", "`slop taste verdict` writes the verdicts on taste rules",
    ],
    "40-storyboard.md": [
        "one explaining graphic per lyric line", "enters on the word that names it", "animates in beats",
        "one-second test", "plant", "premise is on screen by 3 s", "0.03 s", "0.028 s", "2.17 s", "1.83 s",
        "≥ 70 %", "83.2 %", "`still`", "`plate3d`", "`motion`", "`sung`", "4–8 s", "word gap",
        "one image per shot", "two clips never start from the same frame", "slop board audit",
        "silence counts as approval only if the owner set the window", "board/shots.json", "transition_in",
        "| **w** |", "| **b** |", "| **h** |", "| **f** |", "| **t** |", "at most 3", "treatment",
        "set the tier's pace first", "the floor is one shot per lyric line", "`params` must use that device's own keys",
    ],
    "96-setup-and-hardware.md": [
        "slop onboard next", "record_cmd", "only after you saw the step working yourself", "stuck",
        "secure secret card", "never see, type, paste or store a secret", "claude_login_code", "--code-from-env",
        "claude setup-token", "agents login codex --check", "forced_login_method", "at most **2 agent jobs**",
        "slop agents use codex --for director", "gemini cli is refused as director", "claude/versions/<v>/claude",
        "sign-ins stay in the home folder", "slop gpu pair --new", "slop gpu pair --refresh", "one-time pairing code",
        "expires after 24 h", "--gpu auto", "184 mb", "126 s on 8 threads", "41 s", "92 of 92",
        "depth-anything-v2-**small**", "--accept-licence", "slop gpu unpair", "only `/workspace` survives",
        "not yet verified",
    ],
}

# ---- scrub rules (ARCHITECTURE §7.12 and the build brief) ----
# Words that must never ship (the owner's initials, private host and user names, the owner's taboo word) are listed
# only as sha256 prefixes, so this test file does not ship them either. Every token of a doc is hashed: as written
# (initials are case-sensitive), lower-cased, its dotted suffixes (host.domain.tld) and its hyphen/dot parts.
FORBIDDEN_HASHES = {
    "0df9e03357ae3a2b": "the owner's initials",
    "a537830719fd3767": "a private host", "65a9200f9247b5eb": "a private host", "9702d9de85396638": "a private host",
    "8c5a24e9400550c2": "a private user name", "ec6f049478046f72": "a private network name",
    "795b104abe3e4134": "a private network name", "0d2a1a78af155f27": "a private host",
    "aab71a5e61a9015d": "a private host", "9c2c431ce731298c": "a private network domain",
    "ae679821f0649c15": "the owner's taboo word",
}
FORBIDDEN_RE = [
    (re.compile(r"/opt/|C:\\\\Users|/home/[a-z]", re.I), "a private path"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "an email address"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "a job/song id (UUID)"),
    (re.compile(r"midjourney\.com/jobs/|cdn\.midjourney\.com/[0-9a-f]", re.I), "a Midjourney job URL"),
    (re.compile(r"sk-or-[A-Za-z0-9]|sk-[A-Za-z0-9]{20,}"), "an API key"),
]
# a profile flag must be followed by a placeholder like <YOUR_PROFILE_CODE>, never a real code
PROFILE_FLAG = re.compile(r"--(?:profile|p)\s+([^\s`\"',;)]+)")


def _text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _outside_fences(text: str) -> list[str]:
    out, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return out


def _forbidden_tokens(text: str) -> list[str]:
    """Tokens of `text` whose hash is in FORBIDDEN_HASHES (reported with the reason, not the hash)."""
    import hashlib

    def h(w: str) -> str:
        return hashlib.sha256(w.encode("utf-8")).hexdigest()[:16]

    found = []
    for m in re.finditer(r"[A-Za-z0-9][A-Za-z0-9.\-_]*", text):
        tok = m.group(0).rstrip(".-_")
        low = tok.lower()
        cands = {tok, low}
        labels = low.split(".")
        cands.update(".".join(labels[i:]) for i in range(1, len(labels)))  # dotted suffixes
        cands.update(re.split(r"[.\-_]", low))                             # parts
        cands.update(c[:-1] for c in list(cands) if c.endswith("s"))       # plurals
        for c in cands:
            why = FORBIDDEN_HASHES.get(h(c))
            if why:
                found.append(f"{why}: {tok!r}")
                break
    return found


def _has_profile_code(text: str) -> bool:
    """The owner's real Midjourney profile code, compared by hash (tests/scrublist.py), so no copy is needed here."""
    import scrublist
    return any(scrublist.H(t.lower()) == scrublist.PROFILE_SHA256 for t in set(re.findall(r"[A-Za-z0-9]+", text)))


@pytest.mark.parametrize("name", MY_DOCS)
def test_doc_exists_and_is_substantial(name):
    path = DOCS / name
    assert path.exists(), f"missing {path}"
    size = len(path.read_bytes())
    assert size >= MIN_BYTES[name], f"{name} is only {size} bytes; it should be exhaustive"


@pytest.mark.parametrize("name", MY_DOCS)
def test_doc_heading_and_sections(name):
    text = _text(name)
    first = text.splitlines()[0]
    num = name.split("-", 1)[0]
    assert first.startswith(f"# {num} · "), f"{name}: first line must be '# {num} · <title>', got {first!r}"
    h2 = [l for l in text.splitlines() if l.startswith("## ")]
    assert len(h2) >= 8, f"{name}: expected numbered sections, found {len(h2)}"
    assert any("common mistakes" in l.lower() for l in h2), f"{name}: needs a 'Common mistakes' section"
    if name != "00-overview.md":
        assert any("checklist" in l.lower() for l in h2), f"{name}: needs a 'Checklists' section"


@pytest.mark.parametrize("name", MY_DOCS)
def test_required_facts_present(name):
    low = " ".join(_text(name).lower().split())  # line wrapping must not hide a fact
    missing = [s for s in REQUIRED[name] if s.lower() not in low]
    assert not missing, f"{name} lost load-bearing facts: {missing}"


@pytest.mark.parametrize("name", MY_DOCS)
def test_scrubbed(name):
    text = _text(name)
    hits = _forbidden_tokens(text)
    for rx, why in FORBIDDEN_RE:
        for m in rx.finditer(text):
            hits.append(f"{why}: {m.group(0)!r}")
    for m in PROFILE_FLAG.finditer(text):
        code = m.group(1)
        if not (code.startswith("<") and code.endswith(">")):
            hits.append(f"a concrete profile code after {m.group(0)!r}")
    if _has_profile_code(text):
        hits.append("the owner's real Midjourney profile code")
    assert not hits, f"{name} must not ship: " + "; ".join(hits)


@pytest.mark.parametrize("name", MY_DOCS)
def test_code_fences_balanced(name):
    fences = [l for l in _text(name).splitlines() if l.lstrip().startswith("```")]
    assert len(fences) % 2 == 0, f"{name}: unbalanced ``` fences ({len(fences)})"


def _table_columns(row: str) -> int:
    """Cell count as GitHub renders it: escaped \\| does not split; pipes inside code spans DO split."""
    r = row.strip().replace("\\|", "")
    if r.startswith("|"):
        r = r[1:]
    if r.endswith("|"):
        r = r[:-1]
    return r.count("|") + 1


@pytest.mark.parametrize("name", MY_DOCS)
def test_tables_are_rectangular(name):
    lines = _outside_fences(_text(name))
    problems, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            if len(block) < 2 or not re.match(r"^\s*\|?\s*:?-{3,}", block[1]):
                problems.append(f"table without a separator row near {block[0][:60]!r}")
                continue
            want = _table_columns(block[0])
            for row in block[1:]:
                got = _table_columns(row)
                if got != want:
                    problems.append(f"{got} cells (header has {want}): {row[:70]!r}")
        else:
            i += 1
    assert not problems, f"{name}: " + " | ".join(problems[:8])


@pytest.mark.parametrize("name", MY_DOCS)
def test_json_examples_parse(name):
    text = _text(name)
    blocks = re.findall(r"```json\n(.*?)\n```", text, flags=re.S)
    for b in blocks:
        try:
            json.loads(b)
        except ValueError as e:  # pragma: no cover - the message is the point
            pytest.fail(f"{name}: a ```json example does not parse ({e}): {b[:120]!r}")


@pytest.mark.parametrize("name", MY_DOCS)
def test_doc_references_are_planned_docs(name):
    text = _text(name)
    bad = []
    for m in re.finditer(r"\b(\d\d)-([a-z]+(?:-[a-z]+)*)\b", text):
        if m.group(1) in PLANNED_PREFIXES and m.group(0) not in PLANNED_DOCS and m.group(2) not in UNIT_WORDS:
            bad.append(m.group(0))
    for m in re.finditer(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)", text):
        target = m.group(1)
        if target.startswith("http"):
            continue
        stem = Path(target).stem
        if not (DOCS / target).exists() and stem not in PLANNED_DOCS and not (ROOT / target).exists():
            bad.append(target)
    assert not bad, f"{name} refers to docs that are not planned: {sorted(set(bad))}"


def test_display_token_examples_balance():
    """Every sung → display example pair in 20-analysis must consume exactly its sung words (the export's own rule).
    Uses the audio module's own word counter and token parser when they are installed, so the doc can't drift from
    the implementation; falls back to the documented rule otherwise."""
    text = _text("20-analysis.md")
    pairs = re.findall(r"lyrics\.txt:\s+(.+)\ndisplay\.txt:\s+(.+)", text)
    assert len(pairs) >= 8, "the display-token examples are gone"

    def sung_words(line: str) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", line))

    def consumed(line: str) -> int:
        n = 0
        for tok in line.split():
            if "|" in tok:
                n += int(tok.rsplit("|", 1)[1])
            elif re.search(r"[A-Za-z0-9]", tok):
                n += 1
        return n

    try:  # the real implementation, if this checkout has it
        from slop.audio.align import split_words
        from slop.audio.display import consumed as real_consumed

        def sung_words(line: str) -> int:  # noqa: F811
            return len(split_words(line))

        consumed = real_consumed  # noqa: F811
    except Exception:  # pragma: no cover - module absent or not importable here
        pass

    for sung, shown in pairs:
        assert consumed(shown) == sung_words(sung), f"display {shown!r} consumes {consumed(shown)} of {sung_words(sung)} sung words in {sung!r}"


# ---- commands in the docs must exist in the CLI, with the flags they are documented with ----
CMD_RE = re.compile(r"`slop\s+([^`]+)`")
GLOBAL_FLAGS = {"--json", "--project", "-p", "--version", "-h", "--help"}


def _root_parser():
    try:
        from slop.cli import build_parser
        return build_parser()
    except Exception:  # pragma: no cover - the router itself is broken: other tests will say so
        return None


def _subparsers(parser):
    import argparse
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices
    return None


def _flags(parser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings}


def _check_command(root, cmd: str) -> str | None:
    """None when `slop <cmd>` names real (sub)commands and only real flags; else what is wrong."""
    toks = cmd.split()
    while toks and toks[0] in ("-p", "--project", "--json"):  # leading global flags (and their value)
        toks = toks[2:] if toks[0] in ("-p", "--project") else toks[1:]
    if not toks or toks[0].startswith(("-", "<", "…")):
        return None
    parser, path = root, ["slop"]
    while toks:
        subs = _subparsers(parser)
        head = toks[0]
        if not subs or head.startswith(("-", "<", "…", '"', "'")) or not re.fullmatch(r"[a-z][a-z0-9-]*", head):
            break
        if head not in subs:
            # a positional argument (e.g. `slop decide words`, `slop new my-song`) is fine below the first level
            if len(path) == 1 or path[-1] in ("decide", "new"):
                return None if len(path) > 1 else f"slop {head}"
            return f"{' '.join(path)} {head}"
        parser = subs[head]
        path.append(head)
        toks = toks[1:]
    known = _flags(parser) | GLOBAL_FLAGS
    for t in toks:
        if t.startswith("--") and len(t) > 2:
            flag = t.split("=", 1)[0].rstrip(",.;:)")
            if flag not in known:
                return f"{' '.join(path)} {flag}"
    return None


@pytest.mark.parametrize("name", MY_DOCS)
def test_documented_commands_exist(name):
    root = _root_parser()
    if root is None:
        pytest.skip("CLI router not importable here")
    bad = [why for m in CMD_RE.finditer(_text(name)) if (why := _check_command(root, m.group(1)))]
    assert not bad, f"{name} documents commands or flags the CLI does not have: {sorted(set(bad))}"


def test_command_checker_catches_bad_flags():
    root = _root_parser()
    if root is None:
        pytest.skip("CLI router not importable here")
    assert _check_command(root, "-p demo lyrics display --init --force") is None
    assert _check_command(root, "analyze --steps align --whisper-fallback") is None
    assert _check_command(root, "lyrics display --initialise") == "slop lyrics display --initialise"
    assert _check_command(root, "render lyrics-gate") == "slop render lyrics-gate"
    assert _check_command(root, "nosuchgroup") == "slop nosuchgroup"


# ---- device params in the storyboard's JSON examples must be ones the engine's devices read ----
DEVICE_DIR = ROOT / "engine" / "src" / "devices"
# keys the device base reads for every device (engine/src/devices/_base.js: instance, ctx, place)
BASE_PARAM_KEYS = {"color", "alpha", "x", "y", "slot", "at", "until", "keys", "word", "hit", "n", "t", "take", "clip",
                   "beat", "fadeOut", "anchor", "value", "priority"}


def _device_registry() -> dict[str, set[str]]:
    """kind (and every alias) -> the property names its register block reads or declares (defaults, example, p.x, r.x)."""
    reg: dict[str, set[str]] = {}
    for js in sorted(DEVICE_DIR.glob("*.js")):
        src = js.read_text(encoding="utf-8")
        starts = [m for m in re.finditer(r"D\.register\('([^']+)'", src)]
        for k, m in enumerate(starts):
            block = src[m.start(): starts[k + 1].start() if k + 1 < len(starts) else len(src)]
            names = set(re.findall(r"\b[a-z]\w*\.(\w+)", block)) | set(re.findall(r"[{,]\s*([A-Za-z_]\w*)\s*:", block))
            alias = re.search(r"alias:\s*\[([^\]]*)\]", block)
            kinds = [m.group(1)] + (re.findall(r"'([^']+)'", alias.group(1)) if alias else [])
            for kind in kinds:
                reg[kind] = names
    return reg


def test_storyboard_device_examples_use_real_params():
    if not DEVICE_DIR.is_dir():
        pytest.skip("engine devices not in this checkout")
    reg = _device_registry()
    assert "flap" in reg and "sheet" in reg and "cv.bracket" in reg, "device registry parse failed"
    text = _text("40-storyboard.md")
    checked, bad = 0, []
    for b in re.findall(r"```json\n(.*?)\n```", text, flags=re.S):
        doc = json.loads(b)
        for dev in (doc.get("devices") or []) if isinstance(doc, dict) else []:
            checked += 1
            kind = dev.get("kind")
            if kind not in reg:
                bad.append(f"unknown device kind {kind!r}")
                continue
            ok = reg[kind] | BASE_PARAM_KEYS
            for key, val in (dev.get("params") or {}).items():
                if key not in ok:
                    bad.append(f"{kind}: param {key!r} is not read by the device")
                for row in val if isinstance(val, list) else []:
                    for rk in row if isinstance(row, dict) else []:
                        if rk not in ok:
                            bad.append(f"{kind}: {key}[].{rk} is not read by the device")
            if dev.get("key") not in ("W", "B", "H", "F", "T"):
                bad.append(f"{kind}: key {dev.get('key')!r} is not one of W/B/H/F/T")
    assert checked >= 3, "the full shot example with devices is gone from 40-storyboard"
    assert not bad, "40-storyboard device examples the engine would draw wrong: " + "; ".join(bad)


def test_device_check_catches_the_old_mistakes():
    if not DEVICE_DIR.is_dir():
        pytest.skip("engine devices not in this checkout")
    reg = _device_registry()
    assert "txt" not in reg["flap"] and "lock_at" not in reg["flap"]
    assert "rows" not in reg["readout"]
