"""Paths, env and project resolution. CONTRACT — other modules import these names; keep signatures stable.

Never fall back to a default project silently: a missing project is an error that names the three ways to set it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class SlopError(RuntimeError):
    """User-facing error: the CLI prints {"ok": false, "error": str(e)} and exits 1."""


def on_box() -> bool:
    """True inside a Grok Bot cloud computer (HOME=/home/box with /workspace present)."""
    return Path("/workspace").is_dir() and os.environ.get("HOME", "") == "/home/box"


def slop_home() -> Path:
    env = os.environ.get("SLOP_HOME")
    if env:
        return Path(env).expanduser()
    return Path("/workspace/.claudia") if on_box() else Path.home() / ".claudia"


def projects_root() -> Path:
    env = os.environ.get("SLOP_PROJECTS")
    if env:
        return Path(env).expanduser()
    return Path("/workspace/slop/projects") if on_box() else Path.home() / "slop" / "projects"


def toolkit_root() -> Path:
    """The repo checkout (parent of the `slop` package)."""
    return Path(__file__).resolve().parent.parent


def engine_dir() -> Path:
    return toolkit_root() / "engine"


def _project_from_cwd() -> Path | None:
    p = Path.cwd().resolve()
    for d in [p, *p.parents]:
        if (d / "project.json").is_file():
            return d
    return None


def resolve_project(name: str | None = None, must_exist: bool = True) -> Path:
    """Project dir from --project NAME/path, else $SLOP_PROJECT, else the cwd. No silent default."""
    cand = name or os.environ.get("SLOP_PROJECT")
    if cand:
        p = Path(cand).expanduser()
        if not p.is_absolute() and not (p / "project.json").exists():
            p = projects_root() / cand
    else:
        p = _project_from_cwd()
        if p is None:
            raise SlopError("no project: pass --project NAME, set SLOP_PROJECT, or cd into a project folder")
    p = p.resolve()
    if must_exist and not (p / "project.json").is_file():
        raise SlopError(f"no project.json in {p} (create it with: slop new NAME)")
    return p


def load_project(pdir: Path) -> dict:
    return json.loads((pdir / "project.json").read_text(encoding="utf-8"))


def save_project(pdir: Path, data: dict) -> None:
    tmp = pdir / "project.json.tmp"
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(pdir / "project.json")


def require_env(name: str, why: str = "") -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        hint = (" — " + why) if why else ""
        raise SlopError(f"{name} is not set{hint}. In Grok Bot, ask the bot to request it with its secure secret card.")
    return v


def cache_dir(kind: str) -> Path:
    d = slop_home() / "cache" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d
