"""song ingest, Demucs plumbing (model mocked), clean/mix windows (slop audio window)."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "audio"))

import synth  # noqa: E402

from slop.audio.common import load_mono, probe, write_audio  # noqa: E402
from slop.cli import main  # noqa: E402


def slop(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


# ---------------------------------------------------------------- ingest
def test_ingest_converts_and_is_idempotent(tmp_path):
    root = synth.write_project(tmp_path / "ing")
    t = np.arange(48000 * 3) / 48000
    src = write_audio(tmp_path / "take.wav", (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), 48000)
    rc, out = slop("-p", str(root), "song", "ingest", str(src))
    assert rc == 0 and out["status"] == "ingested", out
    p = probe(root / "audio" / "song.wav")
    assert p["sample_rate"] == 44100 and p["channels"] == 2 and p["duration"] == pytest.approx(3.0, abs=0.01)
    assert out["loudness"]["lufs_i"] < 0 and "true_peak_dbfs" in out["loudness"]
    assert any("resampled" in w for w in out["warnings"]) and any("mono" in w for w in out["warnings"])
    rc, out = slop("-p", str(root), "song", "ingest", str(src))
    assert rc == 0 and out["status"] == "unchanged"
    other = write_audio(tmp_path / "other.wav", (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 48000)
    rc, out = slop("-p", str(root), "song", "ingest", str(other))
    assert rc == 1 and "--force" in out["error"]
    rc, out = slop("-p", str(root), "song", "ingest", str(other), "--force")
    assert rc == 0 and out["status"] == "ingested"
    rc, out = slop("-p", str(root), "song", "ingest", str(tmp_path / "missing.wav"))
    assert rc == 1 and "does not exist" in out["error"]


def test_analyze_without_song_says_what_to_do(tmp_path):
    root = synth.write_project(tmp_path / "empty")
    rc, out = slop("-p", str(root), "analyze")
    assert rc == 1 and "song ingest" in out["error"]


# ---------------------------------------------------------------- stems (Demucs mocked)
def test_stems_plumbing_with_fake_demucs(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    pytest.importorskip("demucs")
    import demucs.apply
    import demucs.pretrained
    song = synth.make_song(dur=6.0, drop_at=3.0)
    root = synth.write_project(tmp_path / "st", song)
    for f in (root / "audio" / "stems").glob("*.wav"):
        f.unlink()

    class Fake:
        samplerate = 44100
        sources = ["drums", "bass", "other", "vocals"]

        def eval(self):
            return self

    seen = {}

    def apply_model(model, mix, shifts, split, overlap, progress=False):
        seen.update(shifts=shifts, split=split, overlap=overlap, shape=tuple(mix.shape))
        return torch.stack([mix[0] * k for k in (0.1, 0.2, 0.3, 0.4)])[None]

    monkeypatch.setattr(demucs.pretrained, "get_model", lambda name: Fake())
    monkeypatch.setattr(demucs.apply, "apply_model", apply_model)
    rc, out = slop("-p", str(root), "analyze", "--steps", "stems")
    assert rc == 0, out
    assert seen["shifts"] == 1 and seen["split"] and seen["overlap"] == .25 and seen["shape"][:2] == (1, 2)
    v = load_mono(root / "audio" / "stems" / "vocals.wav", 44100)
    m = load_mono(root / "audio" / "song.wav", 44100)
    assert np.allclose(v, 0.4 * m, atol=2e-3)             # de-normalised back to the song's scale
    assert probe(root / "audio" / "stems" / "drums.wav")["codec"] == "pcm_f32le"
    rc, out = slop("-p", str(root), "analyze", "--steps", "stems")
    assert out["steps"]["stems"]["status"] == "up-to-date"


def test_import_stems_dir(tmp_path):
    song = synth.make_song(dur=4.0, drop_at=2.0)
    root = synth.write_project(tmp_path / "imp", song)
    src = tmp_path / "suno-stems"
    for k, v in song["stems"].items():
        write_audio(src / f"{k.capitalize()} stem.wav", v, 48000)
    rc, out = slop("-p", str(root), "analyze", "--steps", "stems", "--stems-dir", str(src))
    assert rc == 0 and out["steps"]["stems"]["status"] == "imported"
    assert probe(root / "audio" / "stems" / "bass.wav")["sample_rate"] == 44100


# ---------------------------------------------------------------- windows
@pytest.fixture()
def wproj(tmp_path):
    sr = 44100
    n = sr * 6
    voc = np.zeros(n, np.float32)

    def put(t, sig):
        voc[int(t * sr):int(t * sr) + len(sig)] = sig

    put(1.0, synth.tone(0.4, 220, 0.2))                                       # "why"
    put(1.5, synth.tone(0.4, 247, 0.2))                                       # "would"
    put(3.0, (0.3 * np.random.default_rng(1).standard_normal(int(0.6 * sr))).astype(np.float32))   # a crowd shout
    put(4.0, synth.tone(0.5, 262, 0.2))                                       # "you"
    song = {"stems": {"vocals": voc, "drums": voc * 0, "bass": voc * 0, "other": voc * 0}, "mix": voc}
    root = synth.write_project(tmp_path / "win", song)
    words = [{"i": 0, "w": "Why", "line": 0, "t0": 1.0, "t1": 1.4, "conf": .9, "src": "w2v"},
             {"i": 1, "w": "would", "line": 0, "t0": 1.5, "t1": 1.9, "conf": .9, "src": "w2v"},
             {"i": 2, "w": "HEY", "line": 1, "t0": 3.0, "t1": 3.6, "conf": .9, "src": "w2v"},
             {"i": 3, "w": "you", "line": 0, "t0": 4.0, "t1": 4.5, "conf": .9, "src": "w2v"}]
    (root / "analysis").mkdir()
    (root / "analysis" / "words.json").write_text(json.dumps({"words": words, "lines": [], "gaps": []}))
    return root


def test_clean_window_keeps_only_the_quoted_words(wproj):
    rc, out = slop("-p", str(wproj), "audio", "window", "W01", "--t0", "0.5", "--t1", "5.5", "--words", "Why would you")
    assert rc == 0, out
    assert out["sung"] == "Why would you" and out["mode"] == "clean"
    assert [w["t0"] for w in out["words_rel"]] == [0.5, 1.0, 3.5]
    y = load_mono(wproj / "audio" / "windows" / "W01.wav", 44100)
    sr = 44100
    shout = y[int(2.55 * sr):int(3.05 * sr)]                               # song 3.05-3.55 s: muted
    assert np.abs(shout).max() < 1e-4
    kept = y[int(0.5 * sr):int(0.85 * sr)]
    assert np.abs(kept).max() > 0.05
    assert out["rms_dbfs"] == pytest.approx(-16.0, abs=0.6) and out["peak_dbfs"] <= -0.99
    assert (wproj / "audio" / "windows" / "W01.mp3").exists() and (wproj / "audio" / "windows" / "W01.json").exists()
    assert probe(wproj / "audio" / "windows" / "W01.mp3")["codec"] == "mp3"


def test_clean_window_all_words_and_errors(wproj):
    rc, out = slop("-p", str(wproj), "audio", "window", "W02", "--t0", "0.5", "--t1", "5.5")
    assert rc == 0 and out["sung"] == "Why would HEY you"
    rc, out = slop("-p", str(wproj), "audio", "window", "W03", "--t0", "0.5", "--t1", "5.5", "--words", "Why would I")
    assert rc == 1 and "not all found" in out["error"]
    rc, out = slop("-p", str(wproj), "audio", "window", "../evil", "--t0", "0.5", "--t1", "5.5")
    assert rc == 1 and "clip id" in out["error"]
    rc, out = slop("-p", str(wproj), "audio", "window", "W04", "--t0", "5", "--t1", "2")
    assert rc == 1


def test_mix_window(wproj):
    rc, out = slop("-p", str(wproj), "audio", "window", "M01", "--t0", "2", "--t1", "4", "--mode", "mix")
    assert rc == 0 and out["mode"] == "mix" and out["file"] == "audio/windows/M01.mp3"
    p = probe(wproj / "audio" / "windows" / "M01.mp3")
    assert p["channels"] == 1 and p["duration"] == pytest.approx(2.0, abs=0.08)


def test_window_past_the_song_end_is_an_error(wproj):
    rc, out = slop("-p", str(wproj), "audio", "window", "M02", "--t0", "50", "--t1", "52", "--mode", "mix")
    assert rc == 1 and "ends past the song" in out["error"] and "6.00" in out["error"], out
    assert not (wproj / "audio" / "windows" / "M02.mp3").exists()
    rc, out = slop("-p", str(wproj), "audio", "window", "M03", "--t0", "5.0", "--t1", "8.0", "--mode", "mix")
    assert rc == 1 and "t1 <= 6.00" in out["error"]                     # 1.0 of 3.0 s: less than half
    from slop.audio.window import make_window
    info = make_window(wproj, "M04", 4.0, 6.5, mode="mix")              # 2.0 of 2.5 s: kept, with a note
    assert info["warnings"] and "ends before" in info["warnings"][0]


def test_listen_excerpts_go_to_analysis_listen(wproj):
    rc, out = slop("-p", str(wproj), "audio", "window", "chk-l1", "--t0", "0.5", "--t1", "3.0", "--mode", "mix", "--listen")
    assert rc == 0, out
    assert out["file"] == "analysis/listen/chk-l1.mp3" and (wproj / "analysis" / "listen" / "chk-l1.mp3").exists()
    assert not (wproj / "audio" / "windows" / "chk-l1.mp3").exists()
    rc, out = slop("-p", str(wproj), "audio", "window", "chk-l2", "--t0", "0.5", "--t1", "3.0", "--listen")
    assert rc == 1 and "--mode mix" in out["error"]


def test_ingest_refuses_to_replace_an_unknown_song_wav(tmp_path):
    root = synth.write_project(tmp_path / "hand", synth.make_song(dur=3.0, drop_at=1.0))   # song.wav, no song.json
    t = np.arange(44100 * 3) / 44100
    src = write_audio(tmp_path / "new.wav", (0.4 * np.sin(2 * np.pi * 330 * t)).astype(np.float32), 44100)
    rc, out = slop("-p", str(root), "song", "ingest", str(src))
    assert rc == 1 and "--force" in out["error"] and "song.json" in out["error"]
    rc, out = slop("-p", str(root), "song", "ingest", str(src), "--force")
    assert rc == 0 and out["status"] == "ingested"
