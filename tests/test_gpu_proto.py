"""slop.gpu: the job contract (manifests, caps, parts), GPU detection and the busy rule, the durable queue."""
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from slop.config import SlopError  # noqa: E402
from slop.gpu import gpus as G  # noqa: E402
from slop.gpu import proto, store  # noqa: E402
from slop.gpu.proto import ManifestError, validate_manifest  # noqa: E402

SHA = "0" * 64


def _m(**kw):
    m = {"v": 1, "id": "a" * 32, "kind": "run", "entry": "audio.stems", "params": {},
         "inputs": [{"name": "song.wav", "size": 10, "sha256": SHA}], "timeout_s": 600}
    m.update(kw)
    return m


# ------------------------------------------------------------------------------------------------ manifests
def test_manifest_ok_fills_defaults_and_profile():
    m = validate_manifest(_m())
    assert m["profile"] == "audio"
    assert m["params"] == {"shifts": 1, "overlap": 0.25, "seed": 0, "format": "flac24"}
    assert m["force_gpu"] is False


@pytest.mark.parametrize("bad, msg", [
    ({"entry": "audio.evil"}, "unknown entry"),
    ({"entry": "../../bin/sh"}, "unknown entry"),
    ({"id": "../x"}, "invalid job id"),
    ({"id": "A" * 32}, "invalid job id"),
    ({"v": 2}, "version"),
    ({"kind": "exec"}, "unknown job kind"),
    ({"params": {"cmd": "rm -rf /"}}, "unknown parameter"),
    ({"params": {"shifts": 99}}, "shifts"),
    ({"params": {"shifts": True}}, "shifts"),
    ({"params": {"format": "mp3"}}, "format"),
    ({"timeout_s": 10 ** 7}, "timeout"),
    ({"profile": "matte"}, "runs in profile audio"),
    ({"inputs": [{"name": "../song.wav", "size": 1, "sha256": SHA}]}, "unsafe file name"),
    ({"inputs": [{"name": "C:song.wav", "size": 1, "sha256": SHA}]}, "unsafe file name"),
    ({"inputs": [{"name": "song.wav", "size": proto.MAX_FILE + 1, "sha256": SHA}]}, "size"),
    ({"inputs": [{"name": "song.wav", "size": 1, "sha256": "x"}]}, "sha256"),
    ({"inputs": []}, "needs 1..1"),
    ({"inputs": [{"name": "song.wav", "size": 1, "sha256": SHA}, {"name": "x.exe", "size": 1, "sha256": SHA}]},
     "unexpected input"),
])
def test_manifest_refusals(bad, msg):
    with pytest.raises(ManifestError, match=msg):
        validate_manifest(_m(**bad))


def test_manifest_install_and_boxes():
    m = validate_manifest({"v": 1, "id": "b" * 32, "kind": "install", "profile": "matte", "timeout_s": 600},
                          known_profiles={"matte": {}})
    assert m["profile"] == "matte" and m["inputs"] == []
    with pytest.raises(ManifestError, match="unknown profile"):
        validate_manifest({"v": 1, "id": "b" * 32, "kind": "install", "profile": "evil"}, known_profiles={"matte": {}})
    imgs = [{"name": f"img-{i:03d}.png", "size": 1, "sha256": SHA} for i in range(2)]
    ok = validate_manifest(_m(entry="matte.sam2", inputs=imgs, params={"boxes": [[0, 0, .5, .5], [.1, .1, .9, .9]]}))
    assert len(ok["params"]["boxes"]) == 2
    with pytest.raises(ManifestError, match="one box per image"):
        validate_manifest(_m(entry="matte.sam2", inputs=imgs, params={"boxes": [[0, 0, .5, .5]]}))
    with pytest.raises(ManifestError, match="each box"):
        validate_manifest(_m(entry="matte.sam2", inputs=imgs[:1], params={"boxes": [[.5, 0, .4, 1]]}))


def test_every_entry_has_a_profile_and_defaults_validate():
    from slop.gpu.profiles import PROFILES
    for name, spec in proto.ENTRIES.items():
        assert spec["profile"] in PROFILES and name in PROFILES[spec["profile"]]["entries"]
        proto.validate_params(name, {})


def test_split_join_and_safe_extract(tmp_path):
    f = tmp_path / "blob.zip"
    data = bytes(range(256)) * 1000
    f.write_bytes(data)
    parts = proto.split_file(f, 100_000)
    assert [p.name for p in parts] == ["blob.zip.001", "blob.zip.002", "blob.zip.003"]
    assert all(p.stat().st_size <= 100_000 for p in parts)
    assert proto.join_parts(parts[0], tmp_path / "back.bin").read_bytes() == data
    parts[1].unlink()
    with pytest.raises(ManifestError, match="not complete"):
        proto.join_parts(parts[0], tmp_path / "x")
    exact = tmp_path / "exact"
    exact.write_bytes(b"x" * 1000)
    assert len(proto.split_file(exact, 500)) == 2
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.txt", "x")
    with pytest.raises(ManifestError, match="unsafe archive path"):
        proto.safe_extract(bad, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_list_outputs_refuses_links_and_folders(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.npy").write_bytes(b"1")
    assert [f["name"] for f in proto.list_outputs(out)] == ["a.npy"]
    (out / "sub").mkdir()
    with pytest.raises(ManifestError, match="not a regular file"):
        proto.list_outputs(out)
    (out / "sub").rmdir()
    try:
        (out / "link").symlink_to(tmp_path / "secret")
    except OSError:
        pytest.skip("no symlinks here")
    with pytest.raises(ManifestError, match="not a regular file"):
        proto.list_outputs(out)


# ------------------------------------------------------------------------------------------------ GPUs
SMI = """0, GPU-aaaa, NVIDIA GeForce RTX 5070, 12227, 2967, 8977, 32, Enabled, 610.62
1, GPU-bbbb, NVIDIA GeForce RTX 3090 Ti, 24564, 13, 24297, 0, Disabled, 610.62
"""


def test_parse_and_pick_prefers_the_free_non_display_gpu():
    gl = G.parse_nvidia(SMI)
    assert [g["name"] for g in gl] == ["NVIDIA GeForce RTX 5070", "NVIDIA GeForce RTX 3090 Ti"]
    assert gl[0]["display"] and not gl[1]["display"]
    chosen, rows = G.pick(gl)
    assert chosen["uuid"] == "GPU-bbbb"
    assert "2.9 GiB in use" in rows[0]["busy"] and "32 % busy" in rows[0]["busy"] and rows[1]["busy"] is None
    assert G.backend(gl) == "cuda"


def test_pick_refuses_busy_unless_forced_and_respects_the_pin():
    gl = G.parse_nvidia(SMI)
    gl[1]["used_mib"], gl[1]["util"] = 5000, 0          # somebody else's 5 GB on the big card
    chosen, rows = G.pick(gl)
    assert chosen is None and "every usable GPU is busy" in G.blocked_text(rows)
    forced, _ = G.pick(gl, force=True)
    assert forced["uuid"] == "GPU-bbbb"                 # forced: most free memory, non-display first
    gl = G.parse_nvidia(SMI)
    pinned, rows = G.pick(gl, pin="GPU-aaaa")
    assert pinned is None and rows[1]["pinned_out"]     # pinned to the busy display GPU: wait, never the other one
    pinned, _ = G.pick(gl, pin="GPU-bbbb")
    assert pinned["uuid"] == "GPU-bbbb"
    small = G.parse_nvidia("0, GPU-c, X, 8000, 900, 7100, 9, Enabled, 610\n")
    assert G.pick(small)[0] is not None                 # under both thresholds: usable
    assert G.blocked_text([]).startswith("no NVIDIA GPU")


# ------------------------------------------------------------------------------------------------ queue
@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    return tmp_path


def _song(tmp_path) -> Path:
    p = tmp_path / "song.wav"
    p.write_bytes(b"RIFF" + bytes(100))
    return p


def test_fifo_one_at_a_time_and_busy_gpu_waits(home):
    a = store.submit("audio.stems", {"song.wav": _song(home)})
    b = store.submit("audio.stems", {"song.wav": _song(home)})
    inst = store.submit(kind="install", profile="matte")
    assert len({a["id"], b["id"]}) == 2 and proto.ID_RE.match(a["id"])
    assert store.next_job("w1", gpu_ok=False, why="busy card")["id"] == inst["id"]   # installs need no free GPU
    assert store.get(a["id"])["blocked"] == "busy card"
    assert store.next_job("w2", gpu_ok=True) is None            # one job at a time
    store.finish(inst["id"], "w1", {"state": "succeeded", "outputs": []})
    j = store.next_job("w1", gpu_ok=True)
    assert j["id"] == a["id"] and store.get(a["id"])["blocked"] is None
    assert store.manifest(j)["inputs"][0]["name"] == "song.wav"


def test_lease_expiry_requeues_then_interrupts(home, monkeypatch):
    a = store.submit("audio.stems", {"song.wav": _song(home)})
    store.next_job("w1", True)
    store.expire_leases(time.time() + store.LEASE_S + 5)
    j = store.get(a["id"])
    assert j["state"] == "queued" and j["attempts"] == 1
    store.next_job("w1", True)
    store.expire_leases(time.time() + store.LEASE_S + 5)
    j = store.get(a["id"])
    assert j["state"] == "interrupted" and "stopped reporting" in j["error"]
    assert not (store.job_dir(a["id"]) / "in").exists()


def test_a_restarted_worker_gets_its_job_back(home):
    a = store.submit("audio.stems", {"song.wav": _song(home)})
    store.next_job("w1", True)
    j = store.next_job("w1", True)                      # w1 asks again: it lost the job (restart)
    assert j["id"] == a["id"] and j["attempts"] == 1


def test_events_release_cancel_and_ownership(home):
    a = store.submit("audio.stems", {"song.wav": _song(home)})
    store.next_job("w1", True)
    with pytest.raises(SlopError, match="not running on this worker"):
        store.event(a["id"], "w2", {"phase": "running"})
    assert store.event(a["id"], "w1", {"phase": "running", "progress": .5}) == {"cancel": False}
    store.cancel(a["id"])
    assert store.event(a["id"], "w1", {"phase": "running"})["cancel"] is True
    b = store.submit("audio.stems", {"song.wav": _song(home)})
    store.finish(a["id"], "w1", {"state": "cancelled"})
    store.next_job("w1", True)
    store.event(b["id"], "w1", {"release": True, "why": "GPU busy now"})
    assert store.get(b["id"])["state"] == "queued" and store.get(b["id"])["blocked"] == "GPU busy now"
    assert store.cancel(b["id"])["state"] == "cancelled"


def test_uploads_are_checked_before_success(home):
    a = store.submit("audio.stems", {"song.wav": _song(home)})
    store.next_job("w1", True)
    assert store.write_chunk(a["id"], "w1", "vocals.flac", 0, b"abc") == 3
    assert store.write_chunk(a["id"], "w1", "vocals.flac", 3, b"def") == 6
    assert store.write_chunk(a["id"], "w1", "vocals.flac", 3, b"def") == 6     # a retried piece
    with pytest.raises(SlopError, match="expected offset"):
        store.write_chunk(a["id"], "w1", "vocals.flac", 99, b"x")
    with pytest.raises(proto.ManifestError):
        store.write_chunk(a["id"], "w1", "../x", 0, b"x")
    import hashlib
    good = {"name": "vocals.flac", "size": 6, "sha256": hashlib.sha256(b"abcdef").hexdigest()}
    bad = dict(good, sha256=SHA)
    j = store.finish(a["id"], "w1", {"state": "succeeded", "outputs": [bad]})
    assert j["state"] == "failed" and "checksum" in j["error"]
    b = store.submit("audio.stems", {"song.wav": _song(home)})
    store.next_job("w1", True)
    store.write_chunk(b["id"], "w1", "vocals.flac", 0, b"abcdef")
    j = store.finish(b["id"], "w1", {"state": "succeeded", "outputs": [good], "metrics": {"seconds": 1}})
    assert j["state"] == "succeeded" and (store.job_dir(b["id"]) / "out" / "vocals.flac").read_bytes() == b"abcdef"


def test_pairing_code_is_stored_only_as_a_hash(home):
    code = store.new_code()
    raw = (store.gdir() / "pairing.json").read_text()
    assert code not in raw and len(code) >= 30
    assert store.check_code(code) and not store.check_code(code + "x") and not store.check_code("")
    code2 = store.new_code()
    assert store.check_code(code2) and not store.check_code(code)          # a new pairing revokes the old code
    assert store.revoke() and not store.check_code(code2)


def test_submit_refuses_unknown_entries_and_missing_files(home):
    with pytest.raises(SlopError, match="unknown GPU entry"):
        store.submit("shell.exec", {})
    with pytest.raises(SlopError, match="no file"):
        store.submit("audio.stems", {"song.wav": home / "missing.wav"})
    with pytest.raises(SlopError, match="bad GPU job"):
        store.submit("audio.stems", {"evil.sh": _song(home)})
    assert store.all_jobs() == []


def test_prune_keeps_recent_jobs(home):
    ids = []
    for _ in range(5):
        j = store.submit(kind="install", profile="audio")
        store.next_job("w", True)
        store.finish(j["id"], "w", {"state": "succeeded"})
        ids.append(j["id"])
    assert store.prune(keep=2) == 3
    assert [j["id"] for j in store.all_jobs()] == ids[-2:]
    j = json.loads((store.job_dir(ids[-1]) / "job.json").read_text())
    assert j["state"] == "succeeded"
