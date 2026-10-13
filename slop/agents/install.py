"""`slop agents install ENGINE|all`: put the coding-agent CLIs where a computer update cannot wipe them.

On the bot's computer installed apps and packages are removed on an update; only /workspace is verified to persist
(ARCHITECTURE §7b), so every command must end up under $SLOP_HOME (/workspace/.claudia):
  - npm installs go to the prefix $SLOP_HOME/npm (`npm install -g --prefix $SLOP_HOME/npm <pkg>@latest`);
  - the vendors' own installers (Claude Code, Muse Code) run as published; Muse goes to $SLOP_HOME/muse
    (MUSE_INSTALL_DIR); Claude's installer always writes ~/.local/bin + ~/.local/share/claude, so on the bot's
    computer the native binary is then COPIED to $SLOP_HOME/claude/versions/<v>/claude (a self-contained file; verified
    to run from there) and the link points at that copy;
  - every command is linked into $SLOP_HOME/bin, which $SLOP_HOME/env.sh puts on PATH.
Re-running is safe (an installed engine is skipped unless --upgrade) and also repairs a missing link; on the bot's
computer a Claude Code found only in ~/.local is copied in, not downloaded again.
Sign-ins are not files this module moves: see engines.py (they stay in the home folder; `slop agents login` again if a
reset clears them).

Measured on Linux (Node 20, 2026-10-01): npm claude 3 s, codex 5.6 s, gemini 4.4 s; the Claude installer 14 s; the
Muse installer 7.6 s. Disk: Claude ~235 MB, Codex ~430 MB, Gemini ~100 MB, Muse ~330 MB (about 1.1 GB for all four).
"""
from __future__ import annotations

import os
import shutil
import time
import urllib.request
from pathlib import Path

from .. import util
from ..config import SlopError
from . import engines as E

INSTALL_TIMEOUT_S = 900


def _log(engine: str, text: str) -> Path:
    f = E.agents_dir() / f"install-{engine}.log"
    util.append_text(f, f"[{util.stamp()}] {text.rstrip()}\n")
    return f


def _tail(s: str, n: int = 8) -> str:
    lines = [ln for ln in (s or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _download(url: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl")
    if curl:
        rc, _, err = util.run([curl, "-fsSL", "--proto", "=https", "--tlsv1.2", "-o", str(dst), url], timeout=120)
        if rc == 0 and dst.is_file() and dst.stat().st_size > 0:
            return dst
        raise SlopError(f"could not download {url}: {err.strip()[:300] or f'curl exit {rc}'}. Check the network, then "
                        "run the same command again.")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "claudia"})
        with urllib.request.urlopen(req, timeout=120) as r:
            dst.write_bytes(r.read())
    except OSError as e:
        raise SlopError(f"could not download {url}: {e}. Check the network, then run the same command again.") from e
    return dst


def method_for(engine: str, method: str | None) -> str:
    spec = E.SPEC[engine]
    m = (method or spec["default_method"]).lower()
    if m not in spec["methods"]:
        raise SlopError(f"{spec['title']} installs with: {', '.join(spec['methods'])} (not {m})")
    return m


def plan(engine: str, method: str | None = None) -> dict:
    """What `install` will run (no side effects)."""
    spec = E.SPEC[engine]
    m = method_for(engine, method)
    manual = False
    if m == "npm":
        cmd = f"npm install -g --prefix {E.npm_prefix()} {spec['npm']}@latest"
        target = E.npm_bin_dir() / spec["bin"]
    elif E.WIN and engine == "claude":
        cmd = f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm {spec['installer_ps1']} | iex\""
        target = E.native_bin(engine)
    elif engine == "muse" and E.WIN:
        manual = True
        cmd = "manual install: Muse Code's own Windows installer from dev.meta.ai, then: slop agents status muse"
        target = None
    elif engine == "muse":
        cmd = f"MUSE_INSTALL_DIR={E.muse_dir()} MUSE_NO_MODIFY_PATH=1 bash <(curl -fsSL {spec['installer']})"
        target = E.native_bin(engine)
    else:
        cmd = f"bash <(curl -fsSL {spec['installer']})"
        target = E.native_bin(engine)
        if engine == "claude" and E.on_box():
            cmd += f"; then copy the binary to {E.claude_versions_dir()}/<version>/claude"
    out = {"engine": engine, "method": m, "command": cmd, "target": str(target) if target else None,
           # Windows: no symlinks without admin rights; `find` searches the npm prefix and the native place instead
           "link": None if E.WIN else str(E.bin_dir() / spec["bin"])}
    if manual:
        out["manual"] = True
    return out


def _check_prereqs(engine: str, m: str) -> None:
    spec = E.SPEC[engine]
    if m == "npm":
        if not shutil.which("npm"):
            raise SlopError(f"npm is not installed, so {spec['title']} cannot be installed with npm. Install Node.js 20+ "
                            "(it brings npm), then run the same command again.")
        n = E.node_info()
        if n["major"] and n["major"] < spec.get("node_min", 18):
            raise SlopError(f"{spec['title']} needs Node {spec['node_min']}+ but this computer has {n['version']}. "
                            f"Install Node {spec['node_min']} or newer, then run the same command again.")
    elif not E.WIN and not shutil.which("bash"):
        raise SlopError("bash is needed to run the vendor's installer")
    if engine == "muse" and E.WIN:
        raise SlopError("on Windows install Muse Code with the instructions at dev.meta.ai (its own installer), then "
                        "run `slop agents status muse`")


def _native_claude(path: str) -> bool:
    """A native Claude Code binary (the installer's ~/.local/share/claude/versions/<v>), not an npm node script."""
    real = os.path.realpath(path)
    return not real.endswith((".js", ".mjs", ".cjs")) and os.path.isfile(real)


def _keep_box_copy(engine: str, target: Path, ver: str) -> Path:
    """Bot's computer + native Claude Code outside /workspace: the copy under $SLOP_HOME that a computer update keeps."""
    if engine == "claude" and not E.WIN and E.on_box() and not E.survives_update(str(target)) \
            and _native_claude(str(target)):
        kept = E.keep_claude_copy(target, ver)
        _log(engine, f"kept a copy of the native binary at {kept} (a computer update removes ~/.local)")
        return kept
    return target


def install_one(engine: str, method: str | None = None, upgrade: bool = False) -> dict:
    spec = E.SPEC[engine]
    m = method_for(engine, method)
    p = plan(engine, m)
    if p.get("manual"):
        raise SlopError(f"{spec['title']} cannot be installed by slop here: {p['command']}")
    have = E.find(engine)
    ver = E.version(engine) if have and not upgrade else None
    if have and ver:
        durable = E.survives_update(have["real"])
        # bot's computer: a native Claude Code only in ~/.local is copied in (no new download); any other copy outside
        # /workspace (e.g. a system npm install) is installed again under $SLOP_HOME
        keep = (not durable and engine == "claude" and m == "native" and not E.WIN and E.on_box()
                and _native_claude(have["real"]))
        if durable or keep:
            target = _keep_box_copy(engine, Path(have["real"]), ver) if keep else Path(have["path"])
            linked = None
            if have["via"] != "slop_home/bin" or keep:   # repair the link (e.g. a fresh $SLOP_HOME/bin)
                try:
                    linked = E.link(engine, target)
                except SlopError:
                    linked = None
            note = f"; copied into {target} so a computer update keeps it" if keep else ""
            return {"engine": engine, "ok": True, "skipped": True, "version": ver, "bin": str(target),
                    "via": have["via"], "linked": str(linked) if linked else None,
                    "kept_copy": str(target) if keep else None,
                    "text": f"{spec['title']} {ver} already installed - skipped (--upgrade installs the latest){note}"}
    _check_prereqs(engine, m)
    t0 = time.monotonic()
    env = dict(os.environ)
    if m == "npm":
        E.npm_prefix().mkdir(parents=True, exist_ok=True)
        argv = [shutil.which("npm") or "npm", "install", "-g", "--prefix", str(E.npm_prefix()), "--no-fund",
                "--no-audit", "--loglevel=error", f"{spec['npm']}@latest"]
        target = E.npm_bin_dir() / spec["bin"]
    elif E.WIN:                                            # claude on Windows: the vendor's PowerShell installer
        argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                f"irm {spec['installer_ps1']} | iex"]
        target = E.native_bin(engine)
    else:
        script = _download(spec["installer"], E.agents_dir() / "cache" / f"{engine}-install.sh")
        argv = ["bash", str(script)]
        if engine == "muse":
            E.muse_dir().mkdir(parents=True, exist_ok=True)
            env.update(MUSE_INSTALL_DIR=str(E.muse_dir()), MUSE_NO_MODIFY_PATH="1", MUSE_NO_AUTO_UPDATE="1")
        target = E.native_bin(engine)
    _log(engine, f"run: {p['command']}")
    rc, out, err = util.run(argv, timeout=INSTALL_TIMEOUT_S, env=env)
    secs = round(time.monotonic() - t0, 1)
    _log(engine, f"exit {rc} after {secs} s\n{_tail(out, 20)}\n{_tail(err, 20)}")
    if rc != 0:
        why = _tail(err) or _tail(out) or f"exit code {rc}"
        raise SlopError(f"installing {spec['title']} failed after {secs} s ({p['command']}): {why[-600:]}. "
                        f"Full log: {E.agents_dir() / f'install-{engine}.log'}. Fix the cause (network, disk space), "
                        f"then run `slop agents install {engine}` again.")
    if not E._usable(target):
        found = E.find(engine)
        if not found:
            raise SlopError(f"the {spec['title']} installer finished but {target} is missing. Log: "
                            f"{E.agents_dir() / f'install-{engine}.log'}")
        target = Path(found["path"])
    linked = E.link(engine, target)
    ver = E.version(engine)
    if not ver:
        raise SlopError(f"{spec['title']} was installed at {target} but `{spec['bin']} --version` does not run. "
                        f"Log: {E.agents_dir() / f'install-{engine}.log'}")
    kept = _keep_box_copy(engine, target, ver)
    if kept != target:
        linked = E.link(engine, kept)
        target = kept
    return {"engine": engine, "ok": True, "skipped": False, "method": m, "version": ver, "bin": str(target),
            "linked": str(linked) if linked else None, "secs": secs,
            "kept_copy": str(kept) if kept.is_relative_to(E.claude_versions_dir()) else None,
            "text": f"{spec['title']} {ver} installed in {secs} s ({m})"
                    + (f"; linked as {linked}" if linked else "")
                    + (f" -> {kept} (kept under $SLOP_HOME so a computer update keeps it)"
                       if kept.is_relative_to(E.claude_versions_dir()) else "")}


def install(engines: list[str], method: str | None = None, upgrade: bool = False) -> dict:
    rows = []
    for eng in engines:
        try:
            rows.append(install_one(eng, method if len(engines) == 1 else None, upgrade))
        except SlopError as e:
            rows.append({"engine": eng, "ok": False, "error": str(e), "text": f"{E.SPEC[eng]['title']}: FAILED - {e}"})
    ok = all(r["ok"] for r in rows)
    lines = [r["text"] for r in rows]
    nxt = next((f"slop agents login {r['engine']}" for r in rows if r["ok"]), None)
    lines.append("next: sign in with " + (", ".join(f"slop agents login {r['engine']}" for r in rows if r["ok"])
                                            or "(nothing installed)"))
    out = {"ok": ok, "installed": rows, "bin_dir": str(E.bin_dir()), "next": nxt, "text": "\n".join(lines)}
    if not ok:
        out["error"] = "; ".join(r["error"] for r in rows if not r["ok"])[:1500]
    return out
