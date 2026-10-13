"""slop.gpu review fixes: every hint parses; short job ids; pairing is one-time and never replaced by accident; direct
mode never switches a paired box by itself; unpair cleans up; wrong codes never lock out the worker; lipsync checks
for a compiler; the Windows launcher carries no literal home path."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slop.cli import build_parser, main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.gpu import gpus as G  # noqa: E402
from slop.gpu import profiles as P  # noqa: E402
from slop.gpu import route, server, service, store, worker  # noqa: E402

MODS = "slop.core_cli,slop.audio.cli,slop.edit.cli,slop.gpu.cli"
CMD_RE = re.compile(r"`(slop gpu [^`\n]+)`")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("SLOP_MODULES", MODS)
    monkeypatch.setenv("SLOPGPU_HOME", str(tmp_path / "pc"))
    monkeypatch.setenv("SLOPGPU_ECHO", "0")
    monkeypatch.delenv("SLOP_GPU", raising=False)
    return tmp_path


def run(capsys, *argv):
    rc = main(["--json", *argv])
    return rc, json.loads(capsys.readouterr().out)


@pytest.fixture()
def live(home):
    srv = server.serve(0)
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    th.start()
    port = srv.server_address[1]
    service.state_file().write_text(json.dumps({"server_pid": os.getpid(), "port": port, "tunnel_pid": None,
                                                "url": None}))
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
    srv.server_close()


def _fresh_worker(**extra):
    info = {"os": "windows", "backend": "cuda", "profiles": {
        "audio": {"ready": True, "supported": True}, "matte": {"ready": True, "supported": True}}}
    store.save_worker("ab12cd34ef56ab78", info, state="idle", gpu_ok=True, why=None, **extra)


def _parses(cmd: str) -> None:
    words = cmd.replace("...", "X").split()
    assert words[:2] == ["slop", "gpu"], cmd
    try:
        build_parser().parse_args(words[1:])
    except SystemExit as e:                     # argparse error: the hint would fail for the operator
        raise AssertionError(f"hint does not parse: {cmd!r}") from e


def _hints(text: str) -> list[str]:
    return CMD_RE.findall(text or "") + ([text] if (text or "").startswith("slop gpu ") and "`" not in text else [])


# ------------------------------------------------------------------------------------------------ hints parse
def test_every_health_hint_parses_with_the_real_parser(home, live):
    seen = []

    def check(profile=None):
        h = route.health(profile)
        hs = _hints(h["next"]) + _hints(h["why"])
        seen.extend(hs)
        for c in hs:
            _parses(c)
        return h

    assert "serve --tunnel" not in check()["next"]                              # mode none
    store.save_config(mode="direct")
    check()                                                                      # direct, no worker
    store.new_code()
    _fresh_worker()
    assert check()["next"] == "`slop gpu mode paired`"                           # direct + a live paired worker
    store.save_config(mode="paired")
    store.revoke()
    check()                                                                      # server up, nothing paired
    store.new_code()
    check()                                                                      # line not used yet
    _fresh_worker()
    w = json.loads((store.gdir() / "worker.json").read_text())
    w["seen"] = time.time() - 600
    (store.gdir() / "worker.json").write_text(json.dumps(w))
    check()                                                                      # PC gone quiet
    _fresh_worker()
    assert "install interp" in check("interp")["next"]                          # profile missing
    service.state_file().write_text(json.dumps({"server_pid": None, "port": None}))
    assert "slop gpu serve`" in check()["next"]                                  # server down
    assert {"slop gpu serve", "slop gpu pair", "slop gpu direct-plan", "slop gpu mode paired",
            "slop gpu pair --refresh", "slop gpu install interp"} <= set(seen)


def test_every_backticked_slop_gpu_command_in_the_code_parses():
    """Static sweep: hints in f-strings use placeholders ({jid}, JOB, PROFILE) - those parse as positionals."""
    files = sorted((ROOT / "slop" / "gpu").rglob("*.py")) + [ROOT / "slop" / "audio" / "stems.py",
                                                             ROOT / "slop" / "audio" / "align.py",
                                                             ROOT / "slop" / "edit" / "depth.py"]
    cmds = set()
    for f in files:
        for c in CMD_RE.findall(f.read_text(encoding="utf-8")):
            if "|" in c or "[" in c or c.startswith("slop gpu ..."):   # a syntax summary, not a command
                continue
            cmds.add(c)
    assert len(cmds) > 15
    for c in sorted(cmds):
        _parses(c)


def test_serve_accepts_tunnel_as_the_default(home):
    a = build_parser().parse_args(["gpu", "serve", "--tunnel"])
    assert a.tunnel and not a.no_tunnel
    with pytest.raises(SystemExit):
        build_parser().parse_args(["gpu", "serve", "--tunnel", "--no-tunnel"])


# ------------------------------------------------------------------------------------------------ job ids
def test_short_job_ids_work_everywhere_and_bad_ones_say_what_to_do(home, capsys, tmp_path, monkeypatch):
    song = tmp_path / "s.wav"
    song.write_bytes(b"RIFF" + bytes(64))
    store.save_config(mode="paired")
    j = store.submit("audio.stems", {"song.wav": song})
    short = j["id"][:8]
    rc, out = run(capsys, "gpu", "show", short)
    assert rc == 0 and out["job"]["id"] == j["id"]
    rc, out = run(capsys, "gpu", "wait", short, "--timeout", "0")
    assert rc == 0 and out["id"] == j["id"] and out["next"] == f"slop gpu wait {j['id']}"
    rc, out = run(capsys, "gpu", "direct-plan", short)
    assert rc == 0 and out["job"] == j["id"]
    rc, out = run(capsys, "gpu", "cancel", short.upper())
    assert rc == 0 and out["state"] == "cancelled"
    for bad in ("xyz", "0b16e", "f" * 40):
        rc, out = run(capsys, "gpu", "show", bad)
        assert rc == 1 and "traceback" not in out and "slop gpu jobs" in out["error"]
    ids = iter(["abcdef01" + "0" * 24, "abcdef02" + "0" * 24])
    monkeypatch.setattr(store.proto, "new_id", lambda: next(ids))
    store.submit("audio.stems", {"song.wav": song})
    store.submit("audio.stems", {"song.wav": song})
    rc, out = run(capsys, "gpu", "fetch", "abcdef", "--to", str(tmp_path / "o"))
    assert rc == 1 and "give more digits" in out["error"]
    assert store.resolve("abcdef02") == "abcdef02" + "0" * 24


# ------------------------------------------------------------------------------------------------ pairing
def test_pair_refuses_to_replace_a_live_worker_unless_new(home, live, capsys):
    rc, out = run(capsys, "gpu", "pair", "--url", live)
    first = re.search(r"SLOPGPU_TOKEN='([^']+)'", out["lines"]["windows"]).group(1)
    rc, again = run(capsys, "gpu", "pair", "--url", live)                # line not used yet: a new one is fine
    assert rc == 0 and not store.check_code(first)
    code = re.search(r"SLOPGPU_TOKEN='([^']+)'", again["lines"]["windows"]).group(1)
    _fresh_worker()
    rc, out = run(capsys, "gpu", "pair", "--url", live)
    assert rc == 1 and "already paired" in out["error"] and "--new" in out["error"] and "--refresh" in out["error"]
    assert store.check_code(code) == "boot"                              # nothing was replaced
    rc, out = run(capsys, "gpu", "pair", "--url", live, "--new")
    assert rc == 0 and not store.check_code(code) and out["expires_h"] == 24
    assert "works once" in out["text"] and "this box serves" in out["text"]
    with pytest.raises(SystemExit):
        build_parser().parse_args(["gpu", "pair", "--new", "--refresh"])


def test_the_pasted_code_works_once_and_expires(home, live, monkeypatch):
    def call(path, code, body=None, headers=None):
        h = {"Authorization": f"Bearer {code}", "X-Slopgpu-Worker": "ab12cd34ef56ab78", **(headers or {})}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(live + path, data=data, headers=h, method="POST" if data is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"{}") if path.startswith("/gpu/api") else r.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    monkeypatch.setattr(server, "LONG_POLL_S", 0.2)
    code = store.new_code()
    assert call("/gpu/install.ps1", code)[0] == 200
    st, body = call("/gpu/api/next", code, {"info": {}, "gpu_ok": True})
    assert st == 401 and "only installs and pairs" in body["error"]
    st, body = call("/gpu/api/hello", code, {"info": {"os": "linux"}})
    secret = body["secret"]
    assert st == 200 and secret and secret != code and store.check_code(secret) == "worker"
    assert code not in (store.gdir() / "pairing.json").read_text() and secret not in \
        (store.gdir() / "pairing.json").read_text()
    st, body = call("/gpu/api/next", secret, {"info": {}, "gpu_ok": True})
    assert st == 200 and body["job"] is None
    assert call("/gpu/install.ps1", code)[0] == 401                     # the pasted copy is dead now
    st, body = call("/gpu/api/hello", secret, {"info": {}})
    assert st == 200 and "secret" not in body                           # `slopgpu url`: no new secret
    assert store.has_code()
    late = store.new_code()
    monkeypatch.setattr(store, "BOOT_TTL_S", -1)
    assert store.check_code(late) is None and not store.has_code()      # an unused line expires


def test_bad_codes_never_lock_out_a_valid_code(home, live, monkeypatch):
    monkeypatch.setattr(server, "FAIL_LIMIT", 3)
    code = store.new_code()

    def get(token, ip=None):
        h = {"Authorization": f"Bearer {token}"}
        if ip:
            h["CF-Connecting-IP"] = ip
        try:
            with urllib.request.urlopen(urllib.request.Request(live + "/gpu/install.sh", headers=h), timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    codes = [get("wrong", "203.0.113.9") for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[-1] == 429
    assert get(code, "203.0.113.9") == 200                              # the valid code still works from there
    assert get("wrong", "198.51.100.7") == 401                          # another address is not blocked
    api = worker.Api(live, "wrong", "ab12cd34ef56ab78")
    server._FAILS.clear()
    monkeypatch.setattr(server, "FAIL_LIMIT", 0)
    with pytest.raises(worker.RateLimited, match="rate limited"):
        api.call("GET", "/gpu/install.sh", raw=True)
    assert issubclass(worker.RateLimited, worker.Unreachable)           # retry() and the loop back off on it


def test_worker_url_and_pair_refuse_plain_http_to_another_host(home):
    for bad in ("http://192.0.2.5:8080", "ftp://x", "https://", "http://localhost.example.com"):
        with pytest.raises(SystemExit, match="must be https"):
            worker.check_box_url(bad)
    assert worker.check_box_url("https://a-b.trycloudflare.com/") == "https://a-b.trycloudflare.com"
    assert worker.check_box_url("http://127.0.0.1:9") == "http://127.0.0.1:9"
    worker.home().mkdir(parents=True, exist_ok=True)
    worker.save_pairing({"url": "https://old.trycloudflare.com", "token": "t", "worker_id": "ab12cd34ef56ab78"})
    with pytest.raises(SystemExit, match="must be https"):
        worker.main(["url", "http://192.0.2.5:8080"])
    assert worker.pairing()["url"] == "https://old.trycloudflare.com"


# ------------------------------------------------------------------------------------------------ modes + unpair
def test_direct_plan_never_switches_a_paired_box_by_itself(home, live, capsys):
    store.save_config(mode="paired")
    store.new_code()
    _fresh_worker()
    rc, out = run(capsys, "gpu", "direct-plan")
    assert rc == 0 and store.mode() == "paired" and out["switched"] is False and "--use-direct" in out["text"]
    rc, out = run(capsys, "gpu", "direct-plan", "--use-direct")
    assert rc == 0 and store.mode() == "direct" and "slop gpu mode paired" in out["text"]
    _fresh_worker()                     # heartbeat just now: the WSL test clock is corrected in jumps (freshness 60 s)
    rc, st = run(capsys, "gpu", "status")
    assert st["next"] == "`slop gpu mode paired`" and "paired worker is online" in st["why"]
    rc, out = run(capsys, "gpu", "mode", "paired")
    assert rc == 0 and store.mode() == "paired"
    rc, out = run(capsys, "gpu", "mode")
    assert out["mode"] == "paired"


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_unpair_cancels_open_jobs_and_stops_the_server_and_tunnel(home, capsys, tmp_path):
    song = tmp_path / "s.wav"
    song.write_bytes(b"RIFF" + bytes(64))
    store.save_config(mode="paired")
    store.new_code()
    j = store.submit("audio.stems", {"song.wav": song})
    srv = subprocess.Popen(["sleep", "60"], start_new_session=True)
    tun = subprocess.Popen(["sleep", "60"], start_new_session=True)
    service.state_file().write_text(json.dumps({"server_pid": srv.pid, "port": 9, "tunnel_pid": tun.pid,
                                                "url": "https://x.trycloudflare.com"}))
    try:
        rc, out = run(capsys, "gpu", "unpair")
        assert rc == 0 and out["cancelled"] == [j["id"]] and out["server_stopped"]
        assert store.get(j["id"])["state"] == "cancelled" and store.mode() == "none" and not store.has_code()
        assert srv.wait(timeout=10) is not None and tun.wait(timeout=10) is not None
        assert not service.state_file().exists() and "slop gpu serve" in out["text"]
        rc, out = run(capsys, "gpu", "serve", "--stop")
        assert "then `slop gpu pair`" in out["text"] and "--refresh" not in out["text"]
    finally:
        for p in (srv, tun):
            if p.poll() is None:
                p.kill()


def test_status_says_a_server_still_runs_with_nothing_paired(home, live, capsys):
    rc, out = run(capsys, "gpu", "status")
    assert out["mode"] == "none" and "still running" in out["text"] and out["next"] == "slop gpu pair"


# ------------------------------------------------------------------------------------------------ profiles, gpus
def test_lipsync_checks_for_a_compiler_before_installing(tmp_path, monkeypatch, capsys, home):
    monkeypatch.setattr(P, "compiler_missing", lambda: "Visual Studio Build Tools")
    monkeypatch.setattr(P, "_run", lambda *a, **k: pytest.fail("must not start uv without a compiler"))
    with pytest.raises(P.InstallError, match="no C\\+\\+ compiler.*Visual Studio Build Tools"):
        P.install("lipsync", tmp_path / "pc", tmp_path / "uv", "cuda", accept_licence=True)
    rc, out = run(capsys, "gpu", "profiles")
    lip = [ln for ln in out["text"].splitlines() if ln.startswith("lipsync")][0]
    assert "NOT TESTED" in lip and "Python 3.10" in lip and "C++ compiler" in out["text"]
    assert "NOT TESTED" not in [ln for ln in out["text"].splitlines() if ln.startswith("audio")][0]


def test_an_amd_gpu_is_named_not_silently_ignored(monkeypatch):
    monkeypatch.setattr(G, "amd_present", lambda: True)
    assert "AMD" in G.blocked_text([]) and "NVIDIA" in G.blocked_text([])


def test_windows_launcher_has_no_literal_home_path():
    ps1 = (ROOT / "bin" / "gpu-worker.ps1").read_text(encoding="utf-8")
    assert "%~dp0" in ps1 and "-Encoding Oem" in ps1 and "-Encoding Default" not in ps1
    assert "set `\"SLOPGPU_HOME=$H`\"" not in ps1


def test_route_require_errors_are_slop_errors_with_the_next_step(home):
    with route.session("require"):
        with pytest.raises(SlopError, match="Next: `slop gpu serve` then `slop gpu pair`"):
            route.plan("audio.stems", "stems")
