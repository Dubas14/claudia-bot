"""LF line endings are required: bin/setup.sh refuses CRLF (even its own), `--check` reports CRLF scripts, the
install stops before writing anything, `slop doctor` fails on them. Plus the scrub of the hardening pass's files."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slop import doctor

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "bin" / "setup.sh"
BASH = shutil.which("bash")
posix = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="needs bash on Linux/macOS")


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SLOP_") and k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env.update({"SLOP_HOME": str(tmp_path / "home"), "SLOP_PROJECTS": str(tmp_path / "projects"),
                "HOME": str(tmp_path / "userhome")})
    return env


def _repo_copy(tmp_path: Path, crlf: tuple[str, ...] = ()) -> Path:
    """A minimal repo (bin/ + runner/*.mjs), with the named files converted to CRLF."""
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    (repo / "runner").mkdir()
    for f in ("bin/setup.sh", "bin/slop"):
        shutil.copy(ROOT / f, repo / f)
    for f in (ROOT / "runner").glob("*.mjs"):
        shutil.copy(f, repo / "runner" / f.name)
    for rel in crlf:
        p = repo / rel
        p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return repo


@posix
def test_repo_scripts_are_lf():
    for f in [SETUP, ROOT / "bin" / "slop", *(ROOT / "runner").glob("*.mjs")]:
        assert b"\r" not in f.read_bytes(), f


@posix
@pytest.mark.parametrize("shell", ["bash", "sh"])
def test_setup_refuses_its_own_crlf_copy(tmp_path, shell):
    repo = _repo_copy(tmp_path, crlf=("bin/setup.sh",))
    exe = shutil.which(shell)
    if exe is None:
        pytest.skip(f"no {shell}")
    for args in (["--check"], ["--minimal"]):
        r = subprocess.run([exe, str(repo / "bin/setup.sh"), *args], env=_env(tmp_path), capture_output=True,
                           text=True, timeout=60)
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "Windows (CRLF) line endings" in r.stderr and "sed -i 's/\\r$//' bin/setup.sh bin/slop" in r.stderr
    assert not (tmp_path / "home").exists()


@posix
def test_setup_check_reports_crlf_scripts_and_install_stops_first(tmp_path):
    repo = _repo_copy(tmp_path, crlf=("bin/slop",))
    env = _env(tmp_path)
    r = subprocess.run([BASH, str(repo / "bin/setup.sh"), "--check"], env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 1 and re.search(r"MISSING\s+line-endings\s+Windows \(CRLF\) line endings in: bin/slop",
                                           r.stdout), r.stdout
    assert "sed -i 's/\\r$//' bin/slop" in r.stdout
    r = subprocess.run([BASH, str(repo / "bin/setup.sh"), "--check", "--json"], env=env, capture_output=True,
                       text=True, timeout=120)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "line-endings" in out["missing"]
    r = subprocess.run([BASH, str(repo / "bin/setup.sh"), "--minimal"], env=env, capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 1 and "CRLF" in r.stderr and "bin/slop" in r.stderr
    assert not (tmp_path / "home").exists() and not (tmp_path / "projects").exists()  # nothing written


@posix
def test_setup_check_lists_line_endings_ok_on_lf(tmp_path):
    r = subprocess.run([BASH, str(SETUP), "--check"], env=_env(tmp_path), capture_output=True, text=True, timeout=120)
    assert re.search(r"ok\s+line-endings\s+LF in the bin/ and runner/ scripts", r.stdout), r.stdout
    assert subprocess.run([BASH, "-n", str(SETUP)]).returncode == 0
    assert not (tmp_path / "home").exists()


def test_doctor_line_endings(tmp_path):
    c = doctor.check_line_endings()
    assert c["status"] == "ok" and c["data"]["crlf"] == []
    repo = tmp_path / "r"
    (repo / "bin").mkdir(parents=True)
    (repo / "bin/setup.sh").write_bytes(b"#!/usr/bin/env bash\r\necho hi\r\n")
    (repo / "bin/slop").write_bytes(b"#!/bin/sh\necho ok\n")
    c = doctor.check_line_endings(repo)
    assert c["status"] == "fail" and c["data"]["crlf"] == ["bin/setup.sh"]
    assert "sed -i 's/\\r$//' bin/setup.sh" in c["fix"]


# ---------------------------------------------------------------- scrub (hashed list + scanner: tests/scrublist.py)
HARDENING_FILES = ["slop/job.py", "slop/fetch.py", "slop/cli.py", "slop/config.py", "slop/ledger.py", "slop/util.py",
                   "slop/core_cli.py", "slop/doctor.py", "bin/setup.sh", "bin/slop", "tests/test_core_job.py",
                   "tests/test_core_fetch.py", "tests/test_core_next.py", "tests/test_core_lf.py",
                   "tests/test_core_fixes.py"]


def test_hardening_files_are_scrubbed():
    import scrublist
    files = [ROOT / f for f in HARDENING_FILES] + [p for p in (ROOT / "templates/project").rglob("*") if p.is_file()]
    for f in files:
        text = f.read_text(encoding="utf-8")
        hits = scrublist.private_hits(text)
        assert not hits, (f.name, hits)


def test_template_readme_teaches_jobs_next_and_fetch():
    t = (ROOT / "templates/project/README.md").read_text(encoding="utf-8")
    for needle in ("job start -- analyze", "job wait analyze-k3f9", "slop --project {{NAME}} next",
                   "fetch \"URL\" --to audio", "slop review scan-sheets", "slop review record render/scan/findings.json",
                   "jobs/<id>.json"):
        assert needle in t, needle
