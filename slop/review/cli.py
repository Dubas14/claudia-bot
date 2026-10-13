"""`slop review …` — the safety and canon scan (router contract: register(subparsers); each step sets func(args) -> dict).

  scan-sheets   one 3×2 contact sheet per generated take the edit plays -> render/scan/, + render/scan-list.json
  record FILE   the findings JSON, checked against the safety-scan schema, merged into render/scan/scan.json
  status        takes checked, open blocks and fixes, the release verdict
Typical order (after `slop edit edl`, before the final render), one command per step:
  slop review scan-sheets
  cp render/scan/findings-template.json render/scan/findings.json
  (open every sheet in render/scan/; in findings.json add each take you looked at to "checked", each problem to "findings")
  slop review record render/scan/findings.json
  slop review status
The verdict is judged against the takes the edit plays now: a changed edit or a re-made take needs new sheets.
"""
from __future__ import annotations

import argparse
import functools
import re
import shlex
from pathlib import Path

from ..config import SlopError, resolve_project

_HINT = re.compile(r"`slop (?!--project |-p )")


def _project_ref(pdir: Path) -> str:
    try:
        from ..core_cli import project_ref
        return project_ref(pdir)
    except Exception:  # noqa: BLE001 - core not loaded: the full path always works
        return shlex.quote(str(pdir))


def _spell_project(pdir: Path, s):
    """Every `slop …` hint names the project, so a pasted hint works from any folder."""
    return _HINT.sub(f"`slop --project {_project_ref(pdir)} ", s) if isinstance(s, str) else s


def _with_project(step):
    """Wrap a step: its text / next / error hints get the project flag spelled out."""
    @functools.wraps(step)
    def run(a) -> dict:
        pdir = resolve_project(a.project)
        try:
            out = step(a, pdir)
        except SlopError as e:
            raise SlopError(_spell_project(pdir, str(e))) from e
        if isinstance(out, dict):
            for k in ("text", "next", "then"):
                if k in out:
                    out[k] = _spell_project(pdir, out[k])
        return out
    return run


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--project", "-p", default=argparse.SUPPRESS, help="project name or path")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable JSON on stdout")


@_with_project
def cmd_sheets(a, pdir: Path) -> dict:
    from .scan import scan_sheets
    return scan_sheets(pdir, plates=a.plates, force=a.force)


@_with_project
def cmd_record(a, pdir: Path) -> dict:
    from .scan import record
    f = Path(a.file)
    if not f.is_absolute() and not f.is_file() and (pdir / f).is_file():
        f = pdir / f
    return record(pdir, f)


@_with_project
def cmd_status(a, pdir: Path) -> dict:
    from .scan import status
    return status(pdir)


def _no_step(a) -> dict:
    raise SlopError("choose a step: slop review scan-sheets | record FILE | status "
                    "(order: scan-sheets → look at every sheet → record FILE → status)")


def register(subparsers) -> None:
    p = subparsers.add_parser("review", help="safety + canon scan of every generated take: sheets, findings record, status",
                              description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(func=_no_step)
    sp = p.add_subparsers(dest="review_step", metavar="STEP")

    s = sp.add_parser("scan-sheets", help="one 3x2 sheet per take the edit plays (8/25/42/58/75/92 %%) -> render/scan/")
    _common(s)
    s.add_argument("--plates", action="store_true", help="also sheet the picked plates the edit shows (6 a sheet)")
    s.add_argument("--force", action="store_true", help="make every sheet again (default: only new or changed takes)")
    s.set_defaults(func=cmd_sheets)

    s = sp.add_parser("record", help="record the findings JSON (safety-scan schema) -> render/scan/scan.json")
    _common(s)
    s.add_argument("file", help="the findings: render/scan/findings.json (a filled-in copy of "
                                "render/scan/findings-template.json — never the template itself), or the safety-scan "
                                "workflow's result")
    s.set_defaults(func=cmd_record)

    s = sp.add_parser("status", help="what render/scan/scan.json says: checked takes, open blocks, the verdict")
    _common(s)
    s.set_defaults(func=cmd_status)
