"""Generate README.md's module command tables from the real argparse tree (`slop … --help`).

    python tests/gen_cmdref.py           rewrite the block between the MODULE COMMANDS markers in README.md
    python tests/gen_cmdref.py --check   exit 1 (and say which lines differ) when README.md is out of date

Not a test module (pytest collects test_*.py); tests/test_release.py runs the --check form. The hand-written Core table
above the block is left alone.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slop.cli import build_parser  # noqa: E402

GROUPS = [("Next step, background jobs and downloads", ["next", "job", "fetch"]),
          ("Song, lyrics and analysis", ["song", "analyze", "lyrics", "audio"]),
          ("Generation, clips and lip sync", ["gen", "clip", "sync"]),
          ("Storyboard, plates and edit", ["board", "plates", "edit"]),
          ("Render and delivery", ["render"]),
          ("Review (safety and canon scan)", ["review"]),
          ("Taste", ["taste"]),
          ("Setup checklist (onboarding)", ["onboard"]),
          ("Coding agents (Claude Code, Codex, Muse Code, Gemini CLI)", ["agents"]),
          ("Relay (Grok passes the words; the production does the work)", ["relay"]),
          ("Updates (one quiet reminder per release; update in one step)", ["update"]),
          ("Home GPU", ["gpu"])]
SKIP_OPTS = {"-h", "--help", "--json", "--project", "-p"}
BEGIN = ("<!-- BEGIN MODULE COMMANDS (generated from the real `slop ... --help` tree by tests/gen_cmdref.py; run it "
         "after changing a parser) -->")
BLOCK = re.compile(r"<!-- BEGIN MODULE COMMANDS.*?<!-- END MODULE COMMANDS -->", re.S)


def subactions(p):
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a
    return None


def helps(sa) -> dict:
    return {ca.dest: (ca.help or "") for ca in sa._choices_actions}


def _opt(a) -> str:
    o = max(a.option_strings, key=len)
    if a.nargs == 0:
        return o
    if a.choices:
        return f"{o} {'|'.join(map(str, a.choices))}"
    mv = a.metavar or a.dest.upper()
    return f"{o} {' '.join(mv) if isinstance(mv, tuple) else mv}"


def usage(p, prefix: str) -> str:
    parts = []
    # a required "one of" group (e.g. `onboard mark ITEM --done|--skip|...`) is shown once, as a choice, not as options
    req_groups = {id(a): g for g in p._mutually_exclusive_groups if g.required for a in g._group_actions}
    shown = set()
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction) or a.help == argparse.SUPPRESS:
            continue
        g = req_groups.get(id(a))
        if g is not None:
            if id(g) not in shown:
                shown.add(id(g))
                parts.append("|".join(_opt(x) for x in g._group_actions if x.help != argparse.SUPPRESS))
            continue
        if not a.option_strings:
            name = a.metavar or a.dest.upper()
            if a.nargs == argparse.REMAINDER:
                parts.append("-- COMMAND …")
            elif a.nargs in ("?", "*"):
                parts.append(f"[{name}]")
            elif a.choices and not a.metavar:
                parts.append(f"[{'|'.join(map(str, a.choices))}]" if a.nargs == "?" else "|".join(map(str, a.choices)))
            else:
                parts.append(name)
            continue
        if any(o in SKIP_OPTS for o in a.option_strings):
            continue
        t = _opt(a)
        parts.append(t if a.required else f"[{t}]")
    return " ".join([prefix] + parts)


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def first_line(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("%%", "%")).strip()


def build() -> str:
    ap = build_parser()
    root = subactions(ap)
    top = helps(root)
    out = [BEGIN, ""]
    for title, cmds in GROUPS:
        out += [f"### {title}", "", "| Command | What it does |", "|---|---|"]
        for c in cmds:
            p = root.choices.get(c)
            if p is None:
                continue
            sa = subactions(p)
            if sa is None:
                out.append(f"| `{esc(usage(p, 'slop ' + c))}` | {esc(first_line(top.get(c, '')))} |")
                continue
            h2 = helps(sa)
            for name, sp in sa.choices.items():
                if name not in h2:     # aliases
                    continue
                sa3 = subactions(sp)
                if sa3 is None:
                    out.append(f"| `{esc(usage(sp, f'slop {c} {name}'))}` | {esc(first_line(h2.get(name, '')))} |")
                    continue
                h3 = helps(sa3)
                for n3, sp3 in sa3.choices.items():
                    if n3 in h3:
                        out.append(f"| `{esc(usage(sp3, f'slop {c} {name} {n3}'))}` | {esc(first_line(h3.get(n3, '')))} |")
        out.append("")
    out.append("<!-- END MODULE COMMANDS -->")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    readme_p = ROOT / "README.md"
    readme = readme_p.read_text(encoding="utf-8")
    block = build()
    m = BLOCK.search(readme)
    if not m:
        print("README.md has no MODULE COMMANDS markers")
        return 1
    if "--check" in argv:
        if m.group(0) == block:
            print("README command tables are current")
            return 0
        diff = difflib.unified_diff(m.group(0).splitlines(), block.splitlines(), "README.md", "generated", lineterm="", n=0)
        print("README command tables are out of date; run: python tests/gen_cmdref.py")
        print("\n".join(list(diff)[:40]))
        return 1
    new = readme[:m.start()] + block + readme[m.end():]
    readme_p.write_text(new, encoding="utf-8", newline="\n")
    print("commands documented:", sum(1 for ln in block.splitlines() if ln.startswith("| `")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
