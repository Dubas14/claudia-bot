"""bin/setup.sh and bin/slop tests (bash required; the box and the parity env are Linux).

The real installer run is opt-in (downloads ~1 GB): SLOP_TEST_SETUP=1 pytest -m slow tests/test_core_setup.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "bin" / "setup.sh"
SHIM = ROOT / "bin" / "slop"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None or sys.platform == "win32", reason="needs bash on Linux/macOS")


def _env(tmp_path: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("SLOP_") and k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env.update({"SLOP_HOME": str(tmp_path / "home"), "SLOP_PROJECTS": str(tmp_path / "projects"),
                "HOME": str(tmp_path / "userhome")})
    env.update(extra)
    return env


def sh(args, env, timeout=120, cwd=None):
    return subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def test_scripts_parse():
    assert sh([BASH, "-n", str(SETUP)], os.environ).returncode == 0
    assert sh(["sh", "-n", str(SHIM)], os.environ).returncode == 0


def test_setup_help(tmp_path):
    r = sh([BASH, str(SETUP), "--help"], _env(tmp_path))
    assert r.returncode == 0 and "--minimal" in r.stdout and "--full" in r.stdout and "--check" in r.stdout
    assert not (tmp_path / "home").exists()


def test_setup_rejects_unknown_option(tmp_path):
    r = sh([BASH, str(SETUP), "--bogus"], _env(tmp_path))
    assert r.returncode == 2 and "unknown option" in r.stderr


def test_setup_check_on_empty_home_reports_and_writes_nothing(tmp_path):
    env = _env(tmp_path)
    r = sh([BASH, str(SETUP), "--check"], env)
    assert r.returncode == 1, r.stdout + r.stderr
    for item in ("uv", "python", "deps:minimal", "claudia", "browser", "cloudflared", "env"):
        assert re.search(rf"MISSING\s+{re.escape(item)}\b", r.stdout), (item, r.stdout)
    assert "bin/setup.sh --minimal" in r.stdout
    assert not (tmp_path / "home").exists() and not (tmp_path / "projects").exists()

    r = sh([BASH, str(SETUP), "--check", "--json", "--full"], env)
    assert r.returncode == 1
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["ok"] is False and out["profile"] == "full"
    assert {"uv", "python", "deps:minimal", "deps:full", "cmudict", "browser", "cloudflared"} <= set(out["missing"])
    assert not (tmp_path / "home").exists()


def test_setup_check_respects_skip_flags_and_recorded_profile(tmp_path):
    env = _env(tmp_path)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "profile").write_text("full\n")
    r = sh([BASH, str(SETUP), "--check", "--json", "--no-browser", "--no-cloudflared"], env)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["profile"] == "full"
    assert "browser" not in out["missing"] and "cloudflared" not in out["missing"]


def test_setup_pins_torch_on_every_pip_line():
    text = SETUP.read_text()
    assert "apt" not in re.sub(r"#.*", "", text).split()  # never apt
    assert "sudo" not in re.sub(r"#.*", "", text)
    # every pip install goes through uvpip(), which appends the torch pins
    calls = [ln for ln in text.splitlines() if "pip install" in ln and not ln.lstrip().startswith("#")]
    assert len(calls) == 1 and '"${TORCH_PINS[@]}"' in calls[0], calls
    assert "TORCH_V=2.11.0" in text and "TORCHVISION_V=0.26.0" in text and "demucs==4.1.0" in text
    assert "transformers==5.17.*" in text and "librosa==1.0.0" in text and "playwright==$PLAYWRIGHT_V" in text
    assert "PLAYWRIGHT_V=1.60.0" in text and "download.pytorch.org/whl/cpu" in text


def test_shim_falls_back_to_system_python_before_setup(tmp_path):
    env = _env(tmp_path)
    r = sh(["sh", str(SHIM), "--version"], env)
    assert r.returncode == 0 and r.stdout.strip().startswith("slop "), r.stderr
    assert "run: bash" in r.stderr and "setup.sh" in r.stderr


def test_shim_uses_venv_and_env_sh(tmp_path):
    home = tmp_path / "home"
    (home / "venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, home / "venv" / "bin" / "python")
    (home / "env.sh").write_text('export SLOP_PROFILE="full"\nexport SLOP_TEST_MARK="from-env-sh"\n')
    env = _env(tmp_path)
    r = sh(["sh", str(SHIM), "--json", "doctor", "--quick", "--offline"], env, timeout=180)
    assert r.stderr.strip() == "" or "not found" not in r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["profile"] == "full"  # SLOP_PROFILE came from env.sh
    # works from any cwd, through a symlink, and with the project flag after the command
    link = tmp_path / "slop-link"
    os.symlink(SHIM, link)
    r = sh([str(link), "new", "via-shim", "--json"], env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["created"] is True


def test_setup_refuses_non_bash_shells(tmp_path):
    sh_path = shutil.which("sh")
    if sh_path is None or os.path.realpath(sh_path).endswith("bash"):
        pytest.skip("sh is bash here")
    r = sh(["sh", str(SETUP), "--check"], _env(tmp_path))
    assert r.returncode == 2 and "run it with bash" in r.stderr
    assert not (tmp_path / "home").exists()


def test_setup_full_profile_adds_lyric_lint_data_and_verifies_downloads():
    text = SETUP.read_text()
    code = re.sub(r"(?m)^\s*#.*$", "", text)
    assert '"wordfreq>=3.1,<4"' in code and "wordfreq)" in code  # FULL_PKGS and FULL_MODS
    assert "raw.githubusercontent.com/cmusphinx/cmudict" in code and "pip install cmudict" not in code
    assert code.count('checksum_state "$tmp/') == 2  # uv tarball and cloudflared binary
    assert "$url.sha256" in code and "api.github.com/repos/cloudflare/cloudflared/releases" in code
    assert 'XDG_CACHE_HOME="$SLOP_HOME/cache"' in code
    assert "BASH_VERSINFO" in code


def _setup_function(*names: str) -> str:
    """The bash source of setup.sh helper functions (to test them without running the installer)."""
    text = SETUP.read_text()
    out = []
    for n in names:
        m = re.search(rf"(?ms)^{n}\(\) {{.*?^}}\n", text) or re.search(rf"(?m)^{n}\(\) {{.*}}$", text)
        assert m, n
        out.append(m.group(0))
    return "\n".join(out)


def test_setup_checksum_state(tmp_path):
    import hashlib
    f = tmp_path / "blob.bin"
    f.write_bytes(b"claudia checksum test\n")
    good = hashlib.sha256(f.read_bytes()).hexdigest()
    funcs = _setup_function("have", "sha256_of", "checksum_state")

    def state(expected: str) -> str:
        r = sh([BASH, "-c", funcs + '\nchecksum_state "$1" "$2"', "x", str(f), expected], os.environ)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()
    assert state(f"{good.upper()}  uv-x86_64-unknown-linux-gnu.tar.gz") == "ok"  # the .sha256 file format
    assert state(good) == "ok"  # the GitHub API digest (sha256: prefix already stripped)
    assert state("0" * 64) == "mismatch"
    assert state("") == "unknown" and state("not a hash") == "unknown"


def test_shim_runs_without_the_exec_bit(tmp_path):
    """A GitHub clone made on Windows may lose the exec bit: `sh bin/slop` (what the docs say) still works."""
    d = tmp_path / "repo" / "bin"
    d.mkdir(parents=True)
    shutil.copy(SHIM, d / "slop")
    os.chmod(d / "slop", 0o644)
    (tmp_path / "repo" / "slop").symlink_to(ROOT / "slop", target_is_directory=True)
    r = sh(["sh", str(d / "slop"), "--version"], _env(tmp_path))
    assert r.returncode == 0 and r.stdout.startswith("slop "), r.stderr


# ---------------------------------------------------------------- scrub (no private identifiers in core files)
CORE_FILES = ["bin/setup.sh", "bin/slop", "slop/core_cli.py", "slop/util.py", "slop/doctor.py", "pyproject.toml",
              "README.md", "tests/test_core.py", "tests/test_core_setup.py"]


def _core_files():
    files = [ROOT / f for f in CORE_FILES]
    files += [p for p in (ROOT / "templates" / "project").rglob("*") if p.is_file()]
    return files


def test_core_files_are_scrubbed():
    """No private word in the core files (hashed list + scanner, profile code included: tests/scrublist.py)."""
    import scrublist
    for f in _core_files():
        hits = scrublist.private_hits(f.read_text(encoding="utf-8"))
        assert not hits, (f.name, hits)


def test_template_project_json_has_empty_profile():
    proj = json.loads((ROOT / "templates" / "project" / "project.json").read_text())
    assert proj["mj"]["profile"] == "" and "--profile" not in proj["mj"]["params"]


# ---------------------------------------------------------------- real install (opt-in, slow, downloads)
@pytest.mark.slow
@pytest.mark.skipif(os.environ.get("SLOP_TEST_SETUP") != "1", reason="set SLOP_TEST_SETUP=1 to run the real installer")
def test_setup_minimal_real_install_is_idempotent(tmp_path):
    env = _env(tmp_path)
    r = sh([BASH, str(SETUP), "--minimal"], env, timeout=1800)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    install_log = r.stdout + r.stderr
    home = tmp_path / "home"
    for p in ("bin/uv", "bin/slop", "venv/bin/python", "env.sh", "profile"):
        assert (home / p).exists(), p
    envsh = (home / "env.sh").read_text()
    assert 'SLOP_PROFILE="minimal"' in envsh and "HF_HOME=" in envsh and "OPENROUTER" not in envsh
    assert re.search(r'SLOP_BROWSER="(bundled|chrome|none)"', envsh), envsh
    assert re.search(r'SLOP_BROWSER_CHANNEL="(chrome)?"', envsh), envsh  # never "chromium"/"none" (it is a Playwright channel)
    assert not (tmp_path / "userhome" / ".local" / "bin" / "python3.13").exists()  # nothing written outside SLOP_HOME
    r = sh([BASH, str(SETUP), "--check", "--json"], env)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    # a host without Chromium's OS libraries and without google-chrome cannot launch any browser
    assert set(out["missing"]) <= {"browser"}, out
    if 'SLOP_BROWSER="none"' not in envsh:
        assert out["ok"] is True, out
    assert "uv SHA-256 matches" in install_log and "cloudflared SHA-256 matches" in install_log, install_log[-3000:]
    assert not (tmp_path / "userhome" / ".cache" / "fontconfig").exists()  # setup's browser launch caches in SLOP_HOME
    r2 = sh([BASH, str(SETUP)], env, timeout=900)  # re-run: nothing to download, same profile
    assert r2.returncode == 0 and "uv present" in r2.stdout and "venv ok" in r2.stdout
    assert "already installed (editable)" in r2.stdout
    r3 = sh([str(home / "bin" / "slop"), "--json", "doctor", "--offline"], env, timeout=300)
    doc = json.loads(r3.stdout.strip().splitlines()[-1])
    chk = {c["name"]: c["status"] for c in doc["checks"]}
    assert chk["python"] == "ok" and chk["deps:minimal"] == "ok" and chk["cloudflared"] == "ok"
    browser_ok = 'SLOP_BROWSER="none"' not in envsh
    assert chk["chromium"] in (("ok", "warn") if browser_ok else ("fail",)), (chk, envsh)
