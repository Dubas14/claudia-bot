"""`slop gpu ...` for a weaker operator: every answer says what to do next; the pairing lines; the installers; scrub."""
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from slop.cli import build_parser, main  # noqa: E402
from slop.gpu import server, service, store  # noqa: E402

MODS = "slop.core_cli,slop.audio.cli,slop.edit.cli,slop.gpu.cli"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("SLOP_MODULES", MODS)
    monkeypatch.delenv("SLOP_GPU", raising=False)
    return tmp_path


def run(capsys, *argv):
    rc = main(["--json", *argv])
    out = json.loads(capsys.readouterr().out)
    return rc, out


@pytest.fixture()
def live(home):
    """A real job server in a thread, registered as running (no tunnel)."""
    srv = server.serve(0)
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    th.start()
    port = srv.server_address[1]
    service.state_file().write_text(json.dumps({"server_pid": os.getpid(), "port": port, "tunnel_pid": None,
                                                "url": None}))
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


def test_status_when_nothing_is_set_up_names_both_ways(home, capsys):
    rc, out = run(capsys, "gpu", "status")
    assert rc == 0 and out["mode"] == "none" and out["healthy"] is False
    assert "slop gpu serve" in out["text"] and "direct-plan" in out["text"] and out["next"] == "slop gpu serve"
    rc, out = run(capsys, "gpu")                                  # bare `slop gpu` = status
    assert rc == 0 and out["mode"] == "none"


def test_pair_needs_the_server_then_prints_both_lines_once(home, live, capsys):
    store.revoke()
    rc, out = run(capsys, "gpu", "pair")
    assert rc == 1 and "no tunnel URL" in out["error"] and "slop gpu serve" in out["error"]
    rc, out = run(capsys, "gpu", "pair", "--url", live, "--gpu", "1")
    assert rc == 0 and out["code_shown_once"] is True
    win, sh = out["lines"]["windows"], out["lines"]["mac_linux"]
    code = re.search(r"SLOPGPU_TOKEN='([^']+)'", win).group(1)
    assert f"$env:SLOPGPU_URL='{live}'" in win and "/gpu/install.ps1" in win and "| iex" in win
    assert "$env:SLOPGPU_GPU='1'" in win and "SLOPGPU_GPU='1'" in sh
    assert sh.startswith("curl -fsSL -H 'Authorization: Bearer ") and sh.endswith(" bash") and code in sh
    assert code not in (store.gdir() / "pairing.json").read_text()       # only the hash is kept
    assert store.check_code(code) and store.mode() == "paired"
    rc, ref = run(capsys, "gpu", "pair", "--refresh", "--url", "https://new-words.trycloudflare.com")
    assert rc == 0 and code not in json.dumps(ref)                       # re-pairing never repeats the code
    assert "slopgpu.cmd\" url 'https://new-words.trycloudflare.com'" in ref["lines"]["windows"]
    rc, out = run(capsys, "gpu", "unpair", "--keep-server")         # (the fake server.json names this process)
    assert rc == 0 and out["revoked"] and not store.check_code(code) and store.mode() == "none"


def test_the_server_serves_installers_and_code_only_with_the_code(home, live, capsys):
    import urllib.error
    import urllib.request
    import zipfile
    code = store.new_code()

    def get(path, auth=True):
        h = {"Authorization": f"Bearer {code}"} if auth else {}
        with urllib.request.urlopen(urllib.request.Request(live + path, headers=h), timeout=10) as r:
            return r.status, r.read()

    assert json.loads(get("/gpu/health", auth=False)[1])["ok"] is True
    with pytest.raises(urllib.error.HTTPError) as e:
        get("/gpu/install.ps1", auth=False)
    assert e.value.code == 401
    st, ps1 = get("/gpu/install.ps1")
    assert st == 200 and ps1 == (ROOT / "bin" / "gpu-worker.ps1").read_bytes()
    sh = get("/gpu/install.sh")[1]
    assert b"\r" not in sh and sh == (ROOT / "bin" / "gpu-worker.sh").read_bytes().replace(b"\r\n", b"\n")
    st, z = get("/gpu/worker.zip")
    names = zipfile.ZipFile(__import__("io").BytesIO(z)).namelist()
    from slop.gpu.worker import WORKER_FILES
    assert sorted(names) == sorted(["slop/__init__.py"] + [f"slop/gpu/{f}" for f in WORKER_FILES])
    assert not any(n.endswith(("store.py", "server.py", "service.py", "route.py", "cli.py", "direct.py")) for n in names)
    assert get("/gpu/worker.zip")[1] == z                                # deterministic


def test_install_refuses_licensed_and_documented_profiles(home, capsys):
    store.save_config(mode="paired")
    store.new_code()
    rc, out = run(capsys, "gpu", "install", "lipsync")
    assert rc == 1 and "--accept-licence" in out["error"] and "openrail" in out["error"]
    rc, out = run(capsys, "gpu", "install", "video-local")
    assert rc == 1 and "documented only" in out["error"]
    rc, out = run(capsys, "gpu", "install", "audio", "matte")
    assert rc == 0 and [j["profile"] for j in out["jobs"]] == ["audio", "matte"]
    rc, again = run(capsys, "gpu", "install", "audio")
    assert again["jobs"][0]["id"] == out["jobs"][0]["id"]                # not queued twice
    rc, prof = run(capsys, "gpu", "profiles")
    assert "Depth-Anything-V2-Small" in prof["text"] and "Small only" in prof["text"]
    assert "OPT-IN" in prof["text"] and "documented only" in prof["text"]


def test_gpu_flag_is_attached_to_analyze_and_edit_export(home):
    ap = build_parser()
    a = ap.parse_args(["analyze", "--gpu", "require"])
    assert a.gpu == "require" and a.func.__wrapped__.__name__ == "cmd_analyze"
    e = ap.parse_args(["edit", "export", "--gpu", "off"])
    assert e.gpu == "off" and e.func.__wrapped__.__name__ == "cmd_export"
    assert ap.parse_args(["analyze"]).gpu is None                       # None = auto (or $SLOP_GPU)
    with pytest.raises(SystemExit):
        ap.parse_args(["analyze", "--gpu", "maybe"])


def test_jobs_show_wait_cancel_fetch(home, capsys, tmp_path):
    song = tmp_path / "s.wav"
    song.write_bytes(b"RIFF" + bytes(64))
    store.save_config(mode="paired")
    j = store.submit("audio.stems", {"song.wav": song})
    rc, out = run(capsys, "gpu", "jobs")
    assert rc == 0 and out["jobs"][0]["id"] == j["id"]
    rc, out = run(capsys, "gpu", "wait", j["id"], "--timeout", "0")
    assert out["done"] is False and out["next"] == f"slop gpu wait {j['id']}"
    rc, out = run(capsys, "gpu", "cancel", j["id"])
    assert out["state"] == "cancelled"
    rc, out = run(capsys, "gpu", "fetch", j["id"], "--to", str(tmp_path / "o"))
    assert rc == 1 and "not succeeded" in out["error"]
    rc, out = run(capsys, "gpu", "submit", "shell.exec")
    assert rc == 1 and "unknown entry" in out["error"]


def test_direct_plan_setup_copies_the_kit(home, capsys):
    rc, out = run(capsys, "gpu", "direct-plan")
    assert rc == 0 and out["mode"] == "direct" and store.mode() == "direct"
    kit = Path(out["kit"])
    assert (kit / "gpu-worker.ps1").is_file() and (kit / "slopgpu-worker.zip").is_file()
    assert "CopyFromBox" in out["text"] and "SLOPGPU_MODE='direct'" in out["text"] and "install audio" in out["text"]
    rc, out = run(capsys, "gpu", "install", "matte")
    assert rc == 0 and out["direct"] and "slopgpu.cmd\" install matte --detach" in out["commands"][0]


# ------------------------------------------------------------------------------------------------ installers + scrub
def test_installers_are_pinned_consistent_and_safe():
    ps1 = (ROOT / "bin" / "gpu-worker.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "bin" / "gpu-worker.sh").read_text(encoding="utf-8")
    v1 = re.search(r"\$UvVersion = '([\d.]+)'", ps1).group(1)
    v2 = re.search(r"UV_VERSION=([\d.]+)", sh).group(1)
    assert v1 == v2
    assert re.search(r"\$UvSha = '[0-9a-f]{64}'", ps1) and len(re.findall(r"SHA=[0-9a-f]{64}", sh)) == 3
    assert not re.search(r"(?im)^\s*exit\b", ps1)          # `irm | iex` runs in the user's session: never `exit`
    assert "astral.sh" not in ps1 + sh                     # uv comes from its pinned GitHub release, checksum-verified
    assert "Remove-Item Env:SLOPGPU_TOKEN" in ps1 and "unset SLOPGPU_TOKEN" in sh
    if os.name != "nt":
        assert subprocess.run(["bash", "-n", str(ROOT / "bin" / "gpu-worker.sh")]).returncode == 0


def test_gpu_files_are_scrubbed():
    import scrublist as S
    files = sorted((ROOT / "slop" / "gpu").rglob("*.py")) + [ROOT / "bin" / "gpu-worker.ps1",
                                                               ROOT / "bin" / "gpu-worker.sh"]
    files += sorted((ROOT / "slop" / "gpu").glob("*.md"))
    bad = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        bad += [f"{f.name}: {h}" for h in S.private_hits(text)]
        if re.search(r"GPU-[0-9a-f]{8}-[0-9a-f]{4}", text):
            bad.append(f"{f.name}: a real GPU UUID")
        if re.search(r"(?i)[A-Z]:\\+Users\\+(?!you\b|user\b)[A-Za-z]", text) or re.search(r"\b100\.\d+\.\d+\.\d+\b", text):
            bad.append(f"{f.name}: a local path or tailnet address")
    assert bad == []
