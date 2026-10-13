"""Every gen hint line carries the project: `slop clip submit W01 --yes` -> `slop -p NAME clip submit W01 --yes`.

A weaker operator pastes the `next` line (or the "then: …" in a warning or an error) as it is; without -p it fails with
"no project" whenever the shell is not inside the project folder, and a turn is lost. The clip functions build their
hint text without a project, so their public entry points (and every `slop gen` / `slop clip` command) pass their
result and their SlopError messages through `stamp` / `@project_hints`, which add `-p REF` (core_cli.project_ref: the
bare name under $SLOP_PROJECTS, else the quoted path). Idempotent; a line that already names a project is kept.
"""
from __future__ import annotations

import functools
from pathlib import Path

from ..config import SlopError
from ..util import with_project_flag

TEXT_KEYS = ("text", "next", "error", "hint")
LIST_KEYS = ("warnings", "how_to_run", "notes", "lock_problems", "steps")
NESTED_KEYS = ("results", "request_file_steps")


def project_ref(pdir: Path | str | None) -> str | None:
    if pdir is None:
        return None
    try:
        from ..core_cli import project_ref as core_ref
        return core_ref(Path(pdir))
    except ImportError:                                          # core missing: the quoted path
        import shlex
        return shlex.quote(str(pdir))


def stamp_text(text, pdir: Path | str | None):
    return with_project_flag(text, project_ref(pdir))


def _stamp(obj, ref: str, depth: int = 0):
    if depth > 3 or not isinstance(obj, dict):
        return obj
    for k in TEXT_KEYS:
        if isinstance(obj.get(k), str):
            obj[k] = with_project_flag(obj[k], ref)
    for k in LIST_KEYS:
        if isinstance(obj.get(k), list):
            obj[k] = [with_project_flag(x, ref) for x in obj[k]]
    for k in NESTED_KEYS:
        if isinstance(obj.get(k), list):
            for x in obj[k]:
                _stamp(x, ref, depth + 1)
    return obj


def stamp(out, pdir: Path | str | None):
    """add -p REF to the hint lines of a command result (in place; returns it)."""
    ref = project_ref(pdir)
    return _stamp(out, ref) if ref else out


def stamp_error(e: SlopError, pdir: Path | str | None) -> SlopError:
    """add -p REF to the hint lines of an error message (same exception object, so its type and fields stay)."""
    ref = project_ref(pdir)
    if ref and e.args and isinstance(e.args[0], str):
        e.args = (with_project_flag(e.args[0], ref),) + tuple(e.args[1:])
    return e


def project_hints(fn):
    """decorator for functions whose first argument is the project folder."""
    @functools.wraps(fn)
    def wrapper(pdir, *a, **kw):
        try:
            out = fn(pdir, *a, **kw)
        except SlopError as e:
            stamp_error(e, pdir)
            raise
        return stamp(out, pdir) if isinstance(out, dict) else out
    return wrapper
