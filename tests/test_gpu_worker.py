"""slop.gpu end to end in CI: the real job server (in a thread), the real worker loop (in a thread) with a FAKE GPU
(nvidia-smi is never called) and a FAKE profile venv whose "python" runs this file's fake entry (no torch, no
models), and the real routing hooks in slop/audio/stems.py, slop/audio/align.py and slop/edit/depth.py.

Run as a script (`python tests/test_gpu_worker.py -u -m slop.gpu.entry --serve`, the warm-host protocol, or
`... ENTRY JOBDIR`) this file IS the fake entry:
  audio.stems   vocals 0.5 x song, drums 2.5 x song (above full scale: exercises the FLAC gain), bass, other
  audio.align   deterministic log-posteriors at 50 frames a second of the 16 kHz input
  matte.depth   a left-to-right ramp at half the image size
  audio.whisper sleeps FAKE_SLEEP s after writing its pid to JOBDIR/pid (cancel/timeout); FAKE_FAIL=1 fails
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fake_entry_main() -> int:
    """`--serve`: the warm-host protocol (one {"entry", "jobdir"} line per job on stdin -> JOBDIR/host-done.json);
    `ENTRY JOBDIR`: one job."""
    from slop.gpu.proto import atomic_json
    if sys.argv[-1] == "--serve":
        print(json.dumps({"host": "ready", "pid": os.getpid()}), flush=True)
        for line in sys.stdin:
            req = json.loads(line)
            jobdir = Path(req["jobdir"])
            try:
                fake_job(req["entry"], jobdir)
                atomic_json(jobdir / "host-done.json", {"ok": True})
            except Exception as e:  # noqa: BLE001
                atomic_json(jobdir / "host-done.json", {"ok": False, "error": f"{type(e).__name__}: {e}"})
        return 0
    fake_job(sys.argv[-2], Path(sys.argv[-1]))
    return 0


def fake_job(entry: str, jobdir: Path) -> None:
    from slop.gpu.proto import atomic_json, read_json, validate_manifest
    m = validate_manifest(read_json(jobdir / "manifest.json"))
    assert m["entry"] == entry
    ind, out = jobdir / "in", jobdir / "out"
    out.mkdir(exist_ok=True)
    print(f"[fake] {entry} on CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')}", flush=True)
    if os.environ.get("FAKE_FAIL") == "1":
        raise RuntimeError("failing on purpose")
    import numpy as np
    res: dict = {}
    if entry == "audio.stems":
        import soundfile as sf
        song = next(p for p in (ind / "song.flac", ind / "song.wav") if p.is_file())
        y, sr = sf.read(str(song), dtype="float32", always_2d=True)
        files, gains = {}, {}
        for name, k in (("vocals", 0.5), ("drums", 2.5), ("bass", 0.25), ("other", 0.1)):
            s = y * k
            peak = float(np.max(np.abs(s)))
            g = 1.0 if peak <= 0.999 else 0.999 / peak
            sf.write(str(out / f"{name}.flac"), s * g, sr, subtype="PCM_24", format="FLAC")
            files[name], gains[name] = f"{name}.flac", g
        res = {"model": "htdemucs", "sources": ["drums", "bass", "other", "vocals"], "samplerate": sr,
               "format": "flac24", "files": files, "gains": gains, "separate_s": 0.01}
    elif entry == "audio.align":
        import soundfile as sf
        v, sr = sf.read(str(ind / "vocals16k.wav"), dtype="float32")
        assert sr == 16000
        T = int(round(len(v) / 16000 * 50))
        E = np.log(np.random.default_rng(0).dirichlet(np.ones(32), size=T)).astype(np.float32)
        np.savez_compressed(str(out / "w2v.npz"), E=E)
        vocab = {"<pad>": 0, "|": 4, **{c: 5 + i for i, c in enumerate("ETAONIHSRDLUMWCFGYPBVK'XJQZ")}}
        (out / "vocab.json").write_text(json.dumps(vocab), encoding="utf-8")
        res = {"frames": T}
    elif entry == "matte.depth":
        from PIL import Image
        for p in sorted(ind.glob("img-*.png")):
            w, h = Image.open(p).size
            np.save(str(out / f"{p.stem}.npy"),
                    np.tile(np.linspace(0, 7, max(1, w // 2), dtype=np.float32), (max(1, h // 2), 1)))
    elif entry == "audio.whisper":
        (jobdir / "pid").write_text(str(os.getpid()))
        time.sleep(float(os.environ.get("FAKE_SLEEP", "60")))
        (out / "words.json").write_text("{}", encoding="utf-8")
    res["metrics"] = {"seconds": 0.05, "device": "cuda", "gpu": "Fake GPU", "vram_peak_reserved_mib": 512.0}
    atomic_json(out / "result.json", res)


if __name__ == "__main__":
    sys.exit(fake_entry_main())

# ------------------------------------------------------------------------------------------------ the tests
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from slop.config import SlopError  # noqa: E402
from slop.gpu import gpus as G  # noqa: E402
from slop.gpu import profiles as P  # noqa: E402
from slop.gpu import proto, route, server, service, store, worker  # noqa: E402

FAKE_GPU = {"kind": "cuda", "index": 0, "uuid": "GPU-fake-0000", "name": "Fake GPU", "total_mib": 24000.0,
            "used_mib": 10.0, "free_mib": 23990.0, "util": 0.0, "display": False, "driver": "999"}
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake profile python is a POSIX shell script")


def _fake_profile(pc: Path, name: str) -> None:
    env = pc / "envs" / name
    (env / "bin").mkdir(parents=True, exist_ok=True)
    py = env / "bin" / "python"
    py.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{Path(__file__).resolve()}' \"$@\"\n")
    py.chmod(0o755)
    (env / "slopgpu-profile.json").write_text(json.dumps({"profile": name, "fingerprint": P.fingerprint(name, "cuda")}))


class Box:
    def __init__(self, tmp: Path, monkeypatch):
        self.tmp, self.mp = tmp, monkeypatch
        self.pc = tmp / "pc"
        monkeypatch.setenv("SLOP_HOME", str(tmp / "home"))
        monkeypatch.setenv("SLOP_PROJECTS", str(tmp / "projects"))
        monkeypatch.setenv("SLOPGPU_HOME", str(self.pc))
        monkeypatch.setenv("SLOPGPU_ECHO", "0")
        monkeypatch.delenv("SLOP_GPU", raising=False)
        monkeypatch.setattr(server, "LONG_POLL_S", 0.5)
        monkeypatch.setattr(G, "detect", lambda samples=3: [dict(self.gpu)])
        monkeypatch.setattr(G, "used_mib", lambda uuid: 100.0)
        self.gpu = dict(FAKE_GPU)
        self.srv = server.serve(0)
        self.port = self.srv.server_address[1]
        self.th = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.th.start()
        service.state_file().write_text(json.dumps({"server_pid": os.getpid(), "port": self.port,
                                                    "tunnel_pid": None, "url": None}))
        store.save_config(mode="paired")
        self.code = store.new_code()
        (self.pc / "app").mkdir(parents=True)
        (self.pc / "app" / "slop").symlink_to(ROOT / "slop")
        for prof in ("audio", "matte"):
            _fake_profile(self.pc, prof)
        # the real pairing: hello trades the pasted one-time code for the worker's own secret
        worker.pair_with(f"http://127.0.0.1:{self.port}", self.code, "ab12cd34ef56ab78")
        assert worker.pairing()["token"] != self.code and store.check_code(worker.pairing()["token"]) == "worker"
        self.wth = None

    def start_worker(self):
        (self.pc / "stop").unlink(missing_ok=True)
        self.wth = threading.Thread(target=worker.run_loop, daemon=True)
        self.wth.start()
        t_end = time.monotonic() + 10                    # hello made it fresh; wait for its first poll (gpu_ok)
        while not (store.worker().get("fresh") and "gpu_ok" in store.worker()) and time.monotonic() < t_end:
            time.sleep(0.05)
        assert store.worker().get("fresh") and "gpu_ok" in store.worker(), "the worker never checked in"

    def stop_worker(self):
        (self.pc / "stop").write_text("stop")
        if self.wth:
            self.wth.join(timeout=30)
            assert not self.wth.is_alive(), "the worker did not stop"
        worker.close_host(force=True)

    def stop(self):
        try:
            self.stop_worker()
        finally:
            self.srv.shutdown()
            self.srv.server_close()


@pytest.fixture()
def box(tmp_path, monkeypatch):
    b = Box(tmp_path, monkeypatch)
    yield b
    b.stop()


def _project(tmp: Path, seconds: float = 2.0) -> Path:
    import soundfile as sf
    p = tmp / "projects" / "gp"
    (p / "audio").mkdir(parents=True)
    (p / "project.json").write_text(json.dumps({"name": "gp", "title": "gp"}))
    t = np.arange(int(44100 * seconds)) / 44100
    y = (0.6 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(str(p / "audio" / "song.wav"), np.stack([y, y * 0.8], 1), 44100, subtype="PCM_16")
    return p


# ------------------------------------------------------------------------------------------------ routing hooks
def test_stems_hook_runs_on_the_paired_gpu_and_restores_gains(box):
    import soundfile as sf
    from slop.audio import stems
    from slop.audio.common import Paths
    box.start_worker()
    p = _project(box.tmp)
    with route.session("require"):
        r = stems.separate(p)
        used = list(route.USED)
    assert r["status"] == "done" and r["device"] == "gpu: Fake GPU" and proto.ID_RE.match(r["gpu_job"])
    assert used and used[0]["step"] == "stems"
    song, _ = sf.read(str(p / "audio/song.wav"), dtype="float32", always_2d=True)
    drums, sr = sf.read(str(Paths(p).stem("drums")), dtype="float32", always_2d=True)
    assert sr == 44100 and sf.info(str(Paths(p).stem("drums"))).subtype == "FLOAT"
    assert np.abs(drums).max() > 1.2                          # 2.5 x song survived (gain undone on the box)
    assert np.allclose(drums, 2.5 * song, atol=1e-4)
    meta = json.loads((p / "audio/stems/stems.json").read_text())
    assert meta["device"] == "gpu: Fake GPU" and meta["gpu_job"] == r["gpu_job"]
    with route.session("require"):                         # same song again: up to date, no second job
        assert stems.separate(p)["status"] == "up-to-date"
    j = store.get(r["gpu_job"])
    assert j["state"] == "succeeded" and not (store.job_dir(j["id"]) / "in").exists()


def test_align_hook_returns_gpu_emissions(box):
    import soundfile as sf
    from slop.audio import align
    box.start_worker()
    p = _project(box.tmp, 3.0)
    voc = p / "audio" / "vocals.wav"
    sf.write(str(voc), np.zeros((44100 * 3, 2), np.float32) + 0.01, 44100, subtype="FLOAT")
    with route.session("require"):
        E, vocab = align.compute_emissions(voc)
    assert E.shape == (150, 32) and E.dtype == np.float32 and vocab["<pad>"] == 0 and "E" in vocab


def test_depth_prefetch_is_one_job_and_matches_the_cpu_post_processing(box):
    from PIL import Image
    from slop.edit import depth
    box.start_worker()
    p = _project(box.tmp)
    picks = {}
    for i in range(3):
        f = p / "plates" / "cands" / f"p00{i}" / "1.png"
        f.parent.mkdir(parents=True)
        Image.new("RGB", (1600 + 40 * i, 900), (40 * i, 90, 160)).save(f)
        picks[f"p00{i}"] = {"file": f"plates/cands/p00{i}/1.png", "cand_k": 1}
    (p / "plates" / "picks.json").write_text(json.dumps(picks))
    with route.session("auto"):                            # 3 plates: below AUTO_MIN_DEPTH, the CPU is as fast
        assert depth.gpu_prefetch(p) == 0 and not store.all_jobs()
        assert any("ran on the CPU" in n and "--gpu require" in n for n in route.NOTES)
    with route.session("require"):
        n = depth.gpu_prefetch(p)
        assert n == 3 and len([j for j in store.all_jobs() if j.get("entry") == "matte.depth"]) == 1
        assert depth.gpu_prefetch(p) == 0                   # cached by content: nothing sent twice
        im = Image.open(p / "plates/cands/p001/1.png").convert("RGB")
        d = depth.estimate(im)
        assert depth.available()
    assert d.shape == (900, 1640)
    assert d[:, :50].mean() < 0.1 and d[:, -50:].mean() > 0.9   # the fake ramp, normalised: near = right = bright
    monkeypatch_auto = route.AUTO_MIN_DEPTH
    try:                                                    # auto with enough plates: one GPU job as well
        route.AUTO_MIN_DEPTH = 2
        for i, f in enumerate(sorted((p / "plates" / "cands").rglob("1.png"))):
            Image.new("RGB", (1500, 800), (9, 9 * i, 90)).save(f)        # three different images (content-keyed)
        with route.session("auto"):
            assert depth.gpu_prefetch(p) == 3
    finally:
        route.AUTO_MIN_DEPTH = monkeypatch_auto


def test_cli_analyze_gpu_require_end_to_end(box, monkeypatch):
    from slop.cli import main
    box.start_worker()
    p = _project(box.tmp)
    monkeypatch.setenv("SLOP_MODULES", "slop.audio.cli,slop.edit.cli,slop.gpu.cli")
    rc = main(["--json", "-p", str(p), "analyze", "--steps", "stems", "--gpu", "require"])
    assert rc == 0
    assert (p / "audio/stems/vocals.wav").is_file()
    assert json.loads((p / "audio/stems/stems.json").read_text())["device"] == "gpu: Fake GPU"


# ------------------------------------------------------------------------------------------------ auto fallbacks
def test_auto_without_a_gpu_is_silent_and_require_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    with route.session("auto"):
        assert route.plan("audio.stems", "stems") is False and route.NOTES == []
    with route.session("require"):
        with pytest.raises(SlopError, match="no home GPU is set up.*slop gpu serve"):
            route.plan("audio.stems", "stems")
    with route.session("off"):
        assert route.plan("audio.stems") is False
    monkeypatch.setenv("SLOP_GPU", "sometimes")
    with pytest.raises(SlopError, match="must be one of"):
        route.mode()


def test_auto_falls_back_with_a_note_when_the_worker_is_gone(box):
    box.start_worker()
    box.stop_worker()
    w = json.loads((store.gdir() / "worker.json").read_text())
    w["seen"] = time.time() - 3600
    (store.gdir() / "worker.json").write_text(json.dumps(w))
    with route.session("auto"):
        assert route.plan("audio.stems", "stems") is False
        assert "has not checked in" in route.NOTES[0]


def test_auto_queues_a_missing_profile_and_uses_the_cpu(box, monkeypatch):
    import shutil
    calls = []
    monkeypatch.setattr(worker.P, "install", lambda name, *a, **k: calls.append(name) or {"status": "installed"})
    (box.pc / "bin").mkdir(exist_ok=True)
    (box.pc / "bin" / "uv").write_text("#!/bin/sh\nexit 1\n")      # never run: install is stubbed
    shutil.rmtree(box.pc / "envs" / "matte")
    box.start_worker()
    time.sleep(0.8)                                       # one more poll with the new profile list
    with route.session("auto"):
        assert route.plan("matte.depth", "depth") is False
        assert any("not installed" in n for n in route.NOTES) and any("queued the install" in n for n in route.NOTES)
    inst = [j for j in store.all_jobs() if j["kind"] == "install"]
    assert len(inst) == 1 and inst[0]["profile"] == "matte"
    with route.session("auto"):
        route.plan("matte.depth", "depth")                # a second run does not queue a second install
    assert len([j for j in store.all_jobs() if j["kind"] == "install"]) == 1
    t_end = time.monotonic() + 10
    while store.get(inst[0]["id"])["state"] != "succeeded" and time.monotonic() < t_end:
        time.sleep(0.1)
    assert calls == ["matte"]                             # the worker ran the (stubbed) install job


def test_busy_gpu_is_never_used_in_auto(box):
    box.gpu.update(used_mib=6000.0, util=55.0)            # somebody else's render on the only GPU
    box.start_worker()
    with route.session("auto"):
        assert route.plan("audio.stems", "stems") is False
        assert "busy" in route.NOTES[0]
    with route.session("require"):
        with pytest.raises(SlopError, match="busy"):
            route.plan("audio.stems", "stems")


def test_gpu_job_failure_falls_back_in_auto_and_raises_in_require(box, monkeypatch):
    from slop.audio import stems
    monkeypatch.setenv("FAKE_FAIL", "1")
    box.start_worker()
    p = _project(box.tmp)
    with route.session("auto"):
        assert stems._separate_on_gpu(stems.Paths(p), "fp", "key") is None
        assert any("failed" in n and "ran on the CPU instead" in n for n in route.NOTES)
    with route.session("require"):
        with pytest.raises(SlopError, match="failed.*slop gpu show"):
            route.execute("audio.stems", {"song.wav": p / "audio/song.wav"}, {}, label="stems")


def _plates(p: Path, n: int, seed: int = 0) -> None:
    from PIL import Image
    picks = {}
    for i in range(n):
        f = p / "plates" / "cands" / f"p{seed}{i:02d}" / "1.png"
        f.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1200 + 10 * i, 700), (30 * i % 255, 90 + seed, 160)).save(f)
        picks[f"p{seed}{i:02d}"] = {"file": f"plates/cands/p{seed}{i:02d}/1.png", "cand_k": 1}
    (p / "plates").mkdir(exist_ok=True)
    (p / "plates" / "picks.json").write_text(json.dumps(picks))


def _beat(**fields) -> dict:
    """Refresh the stopped worker's last heartbeat (WSL's wall clock can jump by a minute mid-test) + set fields."""
    w = json.loads((store.gdir() / "worker.json").read_text())
    w.update(seen=time.time(), **fields)
    (store.gdir() / "worker.json").write_text(json.dumps(w))
    return w


def test_depth_on_a_box_without_torch_goes_to_the_gpu_even_for_few_plates(box, monkeypatch):
    """Review: minimal bin/setup.sh (no torch/transformers) + a healthy GPU: auto must not keep 1-7 plates 'on the
    CPU', which cannot run there."""
    from PIL import Image
    from slop.edit import depth
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    assert route.cpu_depth_ok() is False
    box.start_worker()
    p = _project(box.tmp)
    _plates(p, 3)
    with route.session("auto"):
        assert depth.available()
        assert depth.gpu_prefetch(p) == 3                           # 3 < AUTO_MIN_DEPTH, but the CPU cannot do it
        assert not any("ran on the CPU" in n for n in route.NOTES)
        d = depth.estimate(Image.new("RGB", (640, 360), (1, 2, 3)))   # not prefetched: one GPU job of its own
    assert d.shape == (360, 640) and d[:, -20:].mean() > 0.9
    assert len([j for j in store.all_jobs() if j.get("entry") == "matte.depth"]) == 2


def test_auto_uses_the_cpu_when_another_gpu_job_is_ahead(box):
    box.start_worker()
    box.stop_worker()
    _beat()                                                         # the PC still counts as online
    inst = store.submit(kind="install", profile="interp", origin="slop gpu install")
    with route.session("auto"):
        assert route.plan("audio.stems", "stems") is False
        assert "busy with another Claudia job (install interp, queued" in route.NOTES[0]
    with route.session("require"):
        assert route.plan("audio.stems", "stems") is True           # require queues behind it
    store.cancel(inst["id"])
    with route.session("auto"):
        assert route.plan("audio.stems", "stems") is True


def test_a_failed_auto_install_is_not_queued_again_for_hours(box, monkeypatch):
    import shutil
    shutil.rmtree(box.pc / "envs" / "matte")
    box.start_worker()
    box.stop_worker()
    _beat()
    j = store.submit(kind="install", profile="matte", origin="auto (first use)")
    store.finish(j["id"], None, {"state": "failed", "error": "No space left on device"})
    with route.session("auto"):
        assert route.plan("matte.depth", "depth") is False
        assert any("failed" in n and "No space left" in n and "slop gpu install matte" in n for n in route.NOTES)
    assert len([x for x in store.all_jobs() if x["kind"] == "install"]) == 1
    monkeypatch.setattr(route, "AUTO_INSTALL_RETRY_S", 0)
    with route.session("auto"):
        route.plan("matte.depth", "depth")
    assert len([x for x in store.all_jobs() if x["kind"] == "install"]) == 2


def test_a_slow_home_uplink_keeps_stems_on_the_cpu(box):
    box.start_worker()
    box.stop_worker()
    _beat(net={"upload_MBps": 1.25, "download_MBps": 9.0})            # 10 Mbit/s up
    out_mb, cpu_s = 184.0, 92.0                                        # a 5-minute song
    with route.session("auto"):
        assert route.plan("audio.stems", "stems", out_mb=out_mb, cpu_s=cpu_s) is False
        assert "uplink (measured 1.2 MB/s)" in route.NOTES[0] or "uplink (measured 1.3 MB/s)" in route.NOTES[0]
    with route.session("require"):
        assert route.plan("audio.stems", "stems", out_mb=out_mb, cpu_s=cpu_s) is True
    _beat(net={"upload_MBps": 28.0})
    with route.session("auto"):
        assert route.plan("audio.stems", "stems", out_mb=out_mb, cpu_s=cpu_s) is True
    o, c = route.stems_estimate(_project(box.tmp, 2.0) / "audio" / "song.wav")
    assert 1.0 < o < 1.3 and c > 0.5


def test_sigterm_while_waiting_cancels_the_gpu_job(box, monkeypatch):
    import signal
    if threading.current_thread() is not threading.main_thread():
        pytest.skip("signal handlers need the main thread")
    p = _project(box.tmp)                                           # no worker: the job just waits in the queue
    seen = {}

    def wait_then_term(jid, *a):
        seen["jid"] = jid
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(100):
            time.sleep(0.05)
        pytest.fail("SIGTERM did not stop the wait")

    monkeypatch.setattr(route, "_wait", wait_then_term)
    before = signal.getsignal(signal.SIGTERM)
    with route.session("require"):
        with pytest.raises(SystemExit) as e:
            route.execute("audio.stems", {"song.wav": p / "audio/song.wav"}, {}, label="stems")
    assert e.value.code == 128 + signal.SIGTERM
    assert store.get(seen["jid"])["state"] == "cancelled"
    assert signal.getsignal(signal.SIGTERM) == before                # the handler is put back


def test_transfer_speeds_are_measured_and_reported(box, monkeypatch):
    from slop.audio import stems
    monkeypatch.setattr(worker, "NET_MIN_BYTES", 0)
    worker.NET.clear()
    box.start_worker()
    p = _project(box.tmp)
    with route.session("require"):
        r = stems.separate(p)
    m = store.get(r["gpu_job"])["metrics"]
    assert m["upload_MB"] > 0 and m["upload_MBps"] > 0 and m["download_MB"] > 0
    t_end = time.monotonic() + 5
    while not (store.worker().get("net") or {}).get("upload_MBps") and time.monotonic() < t_end:
        time.sleep(0.1)
    assert store.worker()["net"]["upload_MBps"] > 0                  # the next heartbeat carries it to the box
    worker.NET.clear()


# ------------------------------------------------------------------------------------------------ worker safety
def test_cancel_kills_the_jobs_process_group(box, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "60")
    box.start_worker()
    wav = box.tmp / "a.wav"
    wav.write_bytes(b"RIFF")
    j = store.submit("audio.whisper", {"audio.wav": wav})
    pidf = box.pc / "work" / j["id"] / "pid"
    t_end = time.monotonic() + 15
    while not pidf.exists() and time.monotonic() < t_end:
        time.sleep(0.1)
    pid = int(pidf.read_text())
    store.cancel(j["id"])
    t_end = time.monotonic() + 30
    while store.get(j["id"])["state"] not in proto.TERMINAL and time.monotonic() < t_end:
        time.sleep(0.2)
    assert store.get(j["id"])["state"] == "cancelled"
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_timeout_and_a_forged_manifest_are_refused(box, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "60")
    box.start_worker()
    wav = box.tmp / "a.wav"
    wav.write_bytes(b"RIFF")
    j = store.submit("audio.whisper", {"audio.wav": wav}, timeout_s=10)
    seen = []
    t_end = time.monotonic() + 40
    while time.monotonic() < t_end:
        st = store.get(j["id"])["state"]
        seen.append(st)
        if st in proto.TERMINAL:
            break
        time.sleep(0.3)
    assert store.get(j["id"])["state"] == "timed_out", (seen[:3], seen[-3:], store.get(j["id"]).get("events"))
    # a job file edited on the box to run something else: the worker validates and refuses it
    k = store.submit(kind="install", profile="audio")
    d = store.job_dir(k["id"]) / "job.json"
    forged = json.loads(d.read_text())
    forged.update(kind="run", entry="shell.exec", params={"cmd": "calc"})
    d.write_text(json.dumps(forged))
    t_end = time.monotonic() + 15
    while store.get(k["id"])["state"] not in proto.TERMINAL and time.monotonic() < t_end:
        time.sleep(0.2)
    assert store.get(k["id"])["state"] == "failed" and "worker refused" in store.get(k["id"])["error"]


def test_unpair_stops_the_worker(box):
    box.start_worker()
    store.revoke()
    box.wth.join(timeout=10)
    assert not box.wth.is_alive()
    assert json.loads((box.pc / "state.json").read_text())["state"] == "unpaired"


def test_cli_unpair_lets_the_worker_hear_it_before_stopping_the_server(box, monkeypatch, capsys):
    """`slop gpu unpair` stops the server and tunnel - but only after the live worker was refused, so it stops too
    instead of retrying a dead address forever. (server.json names this test process: kill() never kills itself.)"""
    from slop.cli import main
    monkeypatch.setenv("SLOP_MODULES", "slop.gpu.cli")
    box.start_worker()
    t0 = time.monotonic()
    assert main(["--json", "gpu", "unpair"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["worker_told"] is True and out["server_stopped"] and time.monotonic() - t0 < 10
    box.wth.join(timeout=10)
    assert not box.wth.is_alive()
    assert json.loads((box.pc / "state.json").read_text())["state"] == "unpaired"
    assert not service.state_file().exists() and store.mode() == "none"


# ------------------------------------------------------------------------------------------------ direct mode
def test_direct_mode_round_trip_in_parts(box, monkeypatch):
    """direct-plan packs the job in <= PART parts, the worker runs the bundle (as the bot would through local exec),
    the output parts come back and direct-ingest finishes the job - no networking at all."""
    import shutil
    from slop.gpu import direct
    monkeypatch.setattr(proto, "PART", 64 * 1024)
    store.save_config(mode="direct")
    p = _project(box.tmp, 2.0)
    j = store.submit("audio.stems", {"song.wav": p / "audio/song.wav"})
    plan = direct.job_plan(j["id"], "windows")
    assert len(plan["parts"]) > 1 and all(Path(x).stat().st_size <= 64 * 1024 for x in plan["parts"])
    assert "CopyFromBox" in plan["text"] and f"run-bundle {j['id']} --detach" in plan["text"]
    assert "slopgpu.cmd" in plan["text"] and "direct-ingest" in plan["text"]
    assert store.get(j["id"])["mode"] == "direct"
    assert store.next_job("someworker", True) is None             # a direct job is never handed to a paired worker
    inbox = box.pc / "inbox"
    inbox.mkdir(parents=True)
    for x in plan["parts"]:                                       # CopyFromBox
        shutil.copy(x, inbox / Path(x).name)
    done = worker.run_bundle(j["id"])                             # MachineShell: slopgpu run-bundle JOB
    assert done["state"] == "succeeded" and done["parts"]
    assert worker.bundle_status(j["id"])["finished"] is True
    back = direct.ddir(j["id"]) / "back"
    for part in done["parts"]:                                    # CopyToBox
        shutil.copy(box.pc / "outbox" / j["id"] / part["name"], back / part["name"])
    r = direct.ingest(j["id"])
    assert r["state"] == "succeeded" and "vocals.flac" in r["outputs"]
    assert (store.job_dir(j["id"]) / "out" / "vocals.flac").is_file()


def test_direct_ingest_refuses_missing_or_broken_parts(box):
    from slop.gpu import direct
    store.save_config(mode="direct")
    p = _project(box.tmp, 1.0)
    j = store.submit("audio.stems", {"song.wav": p / "audio/song.wav"})
    direct.job_plan(j["id"])
    with pytest.raises(SlopError, match="CopyToBox"):
        direct.ingest(j["id"])
    (direct.ddir(j["id"]) / "back" / f"{j['id']}-out.zip.001").write_bytes(b"not a zip")
    with pytest.raises(SlopError, match="copy every part again"):
        direct.ingest(j["id"])
