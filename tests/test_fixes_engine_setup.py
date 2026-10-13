"""Fixes track: the engine honours look.accent = null (no accent drawn: the accent roles read as the plain type colour,
print looks drop their section accents and accent protection), and bin/setup.sh installs cloudflared on its own
(`--cloudflared`, no venv needed) and as setup step 5, reporting it REQUIRED for OpenRouter sung clips."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
SETUP = ROOT / "bin" / "setup.sh"
BASH = shutil.which("bash")


# ------------------------------------------------------------------------------------------------ engine: no accent
@pytest.fixture(scope="module")
def page(tmp_path_factory):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    from slop.config import SlopError
    from slop.render import project as P
    from slop.render.browser import EnginePage
    d = tmp_path_factory.mktemp("engine-accent") / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    pw = sync_playwright().start()
    try:
        pg = EnginePage(pw, P.page_spec(d))
    except SlopError as e:
        pw.stop()
        pytest.skip(f"no browser: {e}")
    yield pg
    pg.close()
    pw.stop()


def test_null_accent_draws_no_accent(page):
    r = page.page.evaluate("""() => {
      const P = window.PROJECT, L = P.look, keep = [L.mode, L.accent, 'accent' in L];
      const snap = () => [INK.accent, INK.clay, INK.red, INK.ember, ENGINE.look('verse2').accent,
                          ENGINE.look('bridge').accent, ENGINE.look('verse1').accentKeep];
      L.mode = 'print';
      const before = snap();
      L.accent = null;
      const none = snap(), native = (L.mode = 'native', ENGINE.look('chorus'));
      L.mode = 'print';
      const shot = ENGINE.look('verse2', {accent: '#00ff00'}).accent;       // a shot's own accent still wins
      const kept = ENGINE.look('verse1', {accentKeep: 1}).accentKeep;
      L.mode = keep[0]; if (keep[2]) L.accent = keep[1]; else delete L.accent;
      return {before, none, native, shot, kept, white: INK.white, after: INK.accent}; }""")
    w = r["white"]
    assert r["before"][:4] == ["#D97757", "#D97757", "#D97757", "#db5c34"] and r["before"][4] == "#db5c34"
    assert r["none"][:4] == [w, w, w, w], r                      # every accent role reads as the plain type colour
    assert r["none"][4] == w and r["none"][5] == w and r["none"][6] == 0   # no section accents, no accent protection
    assert r["native"] == {"mode": "native", "accent": w}
    assert r["shot"] == "#00ff00" and r["kept"] == 0
    assert r["after"] == "#D97757"                                          # back to the project accent


def test_a_set_accent_still_overrides(page):
    r = page.page.evaluate("""() => { const L = window.PROJECT.look, keep = L.accent; INK.accent = '#3FA7D6';
      const a = [INK.accent, ENGINE.look('chorus').accent]; INK.accent = '#D97757'; L.accent = keep; return a; }""")
    assert r[0] == "#3FA7D6"


# ------------------------------------------------------------------------------------------------ setup.sh cloudflared
@pytest.mark.skipif(not BASH or os.name == "nt", reason="bash (Linux) is required")
def test_setup_cloudflared_only_mode_uses_an_installed_binary_without_network(tmp_path):
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    fake = home / "bin" / "cloudflared"
    fake.write_text("#!/bin/sh\necho 'cloudflared version 2099.1.0 (built test)'\n")
    fake.chmod(0o755)
    env = {**os.environ, "SLOP_HOME": str(home), "SLOP_PROJECTS": str(tmp_path / "projects")}
    r = subprocess.run([BASH, str(SETUP), "--cloudflared"], capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "cloudflared present: cloudflared version 2099.1.0" in r.stdout and "cloudflared ready" in r.stdout
    assert not (home / "venv").exists() and not (home / "env.sh").exists()     # only this piece


@pytest.mark.skipif(not BASH or os.name == "nt", reason="bash (Linux) is required")
def test_setup_check_names_cloudflared_required(tmp_path):
    env = {**os.environ, "SLOP_HOME": str(tmp_path / "home"), "SLOP_PROJECTS": str(tmp_path / "projects")}
    r = subprocess.run([BASH, str(SETUP), "--check", "--json", "--no-browser"], capture_output=True, text=True,
                       env=env, timeout=120)
    out = json.loads(r.stdout)
    item = next(i for i in out["items"] if i["name"] == "cloudflared")
    assert item["status"] == "missing" and "REQUIRED for OpenRouter sung clips" in item["detail"]
    assert "setup.sh --cloudflared" in item["detail"]


def test_setup_installs_cloudflared_in_step_5_through_one_function():
    code = SETUP.read_text(encoding="utf-8")
    assert "--cloudflared) CF_ONLY=1 ;;" in code and code.count("install_cloudflared() {") == 1
    assert 'install_cloudflared || warn "no working cloudflared' in code              # step 5 of the install
    assert code.index("install_cloudflared() {") < code.index('if [ "$CF_ONLY" = 1 ]')
    assert 'jpy=python3; [ -x "$PY" ] && jpy="$PY"' in code                            # no venv needed
    assert "only needed for the phone tap app" not in code
