"""`slop` CLI router. CONTRACT — each module exposes `slop/<module>/cli.py: register(subparsers) -> None`.

Each registered subcommand sets `func(args) -> dict`. The router prints the dict as JSON with --json
(always including "ok"), or a readable rendering otherwise. SlopError -> exit 1 with {"ok": false, "error": ...}.

The root flags --json and --project/-p work before or after the command name (`util.hoist_global_flags` moves them
to the front), and argparse usage errors print {"ok": false, "error", "usage"} on stdout when --json is given
(`util.json_usage_errors`; exit code 2).

$SLOP_MODULES (comma list of module names, e.g. "slop.core_cli,slop.job") limits which modules the router loads -
for tests and for working around a broken module on a box; unset = all of MODULES.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback

from . import __version__
from .config import SlopError

# Order = help order. Missing modules are skipped (so a partial install still runs).
MODULES = ["slop.core_cli", "slop.job", "slop.fetch", "slop.audio.cli", "slop.gen.cli", "slop.sync.cli",
           "slop.board.cli", "slop.edit.cli", "slop.render.cli", "slop.review.cli", "slop.taste.cli", "slop.gpu.cli"]
MODULES.append("slop.agents.cli")  # after slop.gen.cli: it also adds `gen image --provider codex`
MODULES.append("slop.onboard.cli")  # onboarding checklist: slop onboard status|next|mark|set|apply
MODULES.append("slop.relay")  # Grok passes words, the production (Claude Code / Codex) works: slop relay ...
MODULES.append("slop.update")  # a newer release? one quiet reminder per release; slop update apply installs it


def _render_human(out: dict) -> str:
    if "text" in out and isinstance(out["text"], str):
        return out["text"]
    return json.dumps(out, indent=1, ensure_ascii=False, default=str)


def modules() -> list[str]:
    """MODULES, or the subset named in $SLOP_MODULES."""
    env = os.environ.get("SLOP_MODULES", "").strip()
    return [m.strip() for m in env.split(",") if m.strip()] if env else list(MODULES)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="slop", description="Claudia music-video toolkit")
    ap.add_argument("--version", action="version", version=f"slop {__version__}")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON on stdout")
    ap.add_argument("--project", "-p", default=None, help="project name or path (else $SLOP_PROJECT or cwd)")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")
    for mod in modules():
        try:
            m = importlib.import_module(mod)
        except ModuleNotFoundError as e:
            if e.name and (e.name == mod or mod.startswith(e.name + ".") or e.name.startswith("slop.")):
                continue
            raise
        m.register(sub)
    return ap


def main(argv: list[str] | None = None) -> int:
    from .util import hoist_global_flags, json_usage_errors
    words = hoist_global_flags(sys.argv[1:] if argv is None else list(argv))
    ap = build_parser()
    json_usage_errors(ap, words)
    args = ap.parse_args(words)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    try:
        out = args.func(args) or {}
        out.setdefault("ok", True)
        print(json.dumps(out, ensure_ascii=False, default=str) if args.json else _render_human(out))
        return 0 if out.get("ok", True) else 1
    except SlopError as e:
        print(json.dumps({"ok": False, "error": str(e)}) if args.json else f"error: {e}", file=sys.stdout if args.json else sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # unexpected: keep the traceback for the bot to read
        tb = traceback.format_exc(limit=6)
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": tb}) if args.json else tb,
              file=sys.stdout if args.json else sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
