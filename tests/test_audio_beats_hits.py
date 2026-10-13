"""Beat map, sections and hits on a synthetic song with a tempo ramp (CLI end to end: slop --json analyze ...)."""
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

from slop.cli import main  # noqa: E402


def slop(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    song = synth.make_song(dur=40.0, phase=1, drop_at=20.0)          # the fixture's default 120 -> 124 BPM ramp
    root = synth.write_project(tmp_path_factory.mktemp("audio") / "synth", song)
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats,sections,hits")
    assert rc == 0, out
    return root, song, out


def test_beatmap_tracks_tempo_ramp(proj):
    root, song, out = proj
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["source"] == "beatmap-v1" and B["duration"] == pytest.approx(40.0, abs=0.05)
    mine = np.array(B["beats"])
    truth = song["beats"]
    inner = truth[(truth > 2.0) & (truth < 38.0)]
    err = np.array([np.min(np.abs(mine - t)) for t in inner])
    assert np.median(err) < 0.012, np.median(err)
    assert np.mean(err < 0.030) > 0.95
    span = mine[(mine > truth[0] - 0.1) & (mine < truth[-1] + 0.1)]
    assert abs(len(span) - len(truth)) <= 1
    assert mine[-1] <= B["duration"]
    # variable tempo: the curve rises with the ramp, never a single BPM
    assert B["tempo_start"] < B["tempo_end"]
    assert 119 < B["tempo_start"] < 122 and 121 < B["tempo_end"] < 125
    assert len(B["tempo"]) >= 5 and all("bpm" in x and "t" in x for x in B["tempo"])
    assert len(B["rms24"]) == int(np.ceil(40.0 * 24))


def test_downbeat_vote_finds_accented_kicks(proj):
    root, song, _ = proj
    B = json.loads((root / "analysis" / "beats.json").read_text())
    d = np.array(B["downbeats"])
    inner = song["downbeats"][(song["downbeats"] > 2) & (song["downbeats"] < 38)]
    err = np.array([np.min(np.abs(d - t)) for t in inner])
    assert np.mean(err < 0.03) >= 0.99, (B["downbeat_phase"], B["phase_blocks"], err)
    assert B["downbeat_method"] == "kick" and B["downbeat_votes"]["kick"]["share"] == 1.0
    assert "harmony" in B["downbeat_votes"]                                 # reported as a second opinion only


def test_downbeat_vote_samples_a_window_after_the_beat():
    from slop.audio import beatmap
    fr = 100.0
    beats = 0.5 + 0.5 * np.arange(64)                                      # two 32-beat blocks, downbeats on phase 2
    kick = np.zeros(4000)
    for j, b in enumerate(beats):
        amp = 1.0 if j % 4 == 2 else 0.6
        kick[int(round((b + 0.03) * fr))] = amp                             # the low-passed kick peaks 30 ms late
        kick[int(round(b * fr))] = 0.7 if j % 4 == 1 else 0.05              # a click-like blip on the beat frame
    ph, blocks = beatmap.downbeat_vote(beats, kick, fr)
    assert ph == 2 and set(blocks) == {2}


def test_sections_tile_the_song(proj):
    root, song, _ = proj
    S = json.loads((root / "analysis" / "beats.json").read_text())["sections"]
    assert S and S[0]["t0"] == 0.0 and S[-1]["t1"] == pytest.approx(40.0, abs=0.05)
    for a, b in zip(S, S[1:]):
        assert a["t1"] == pytest.approx(b["t0"])
    assert all(set(s) >= {"name", "t0", "t1", "energy"} for s in S)
    assert max(s["energy"] for s in S) == pytest.approx(1.0)


def test_hits_schema_and_events(proj):
    root, song, _ = proj
    H = json.loads((root / "analysis" / "hits.json").read_text())
    for k in ("kick", "snare", "hat", "hits", "risers", "fills", "vocal_entries", "env24"):
        assert k in H
    assert set(H["env24"]) >= {"drums", "vocals", "bass", "mix", "other"}
    assert len(H["env24"]["drums"]) == int(np.ceil(40 * 24))
    # kicks on (almost) every beat after the drop, where the kit is loud
    after = song["beats"][song["beats"] > song["drop_at"] + 0.5]
    k = np.array(H["kick"])
    assert np.mean([np.min(np.abs(k - b)) < 0.05 for b in after]) > 0.8
    # the drop is a real hit ON the drop (not a beat early), the riser lands on it, the vocal phrases are entries
    assert any(abs(h["t"] - song["drop_at"]) < 0.1 for h in H["hits"]), (song["drop_at"], H["hits"])
    assert all(0 <= h["score"] <= 1 for h in H["hits"])
    assert any(r["t1"] > song["drop_at"] - 2 and abs(r["land"] - song["drop_at"]) < 0.1 for r in H["risers"]), H["risers"]
    for p0 in (4.0, 12.0, 24.0, 32.0):
        assert any(abs(v - p0) < 0.2 for v in H["vocal_entries"]), (p0, H["vocal_entries"])
    # snares on 2 and 4 sit ON the four-on-the-floor kicks: auto kick_click finds the backbeat and keeps them
    s = np.array(H["snare"])
    truth_sn = np.array([b for i, b in enumerate(song["beats"]) if (i - song["phase"]) % 4 in (1, 3)])
    assert H["kick_click"]["backbeat"] is not None and H["kick_click"]["kept_on_kicks"] > 0
    assert len(s) >= 0.8 * len(truth_sn)
    assert np.mean([np.min(np.abs(truth_sn - x)) < 0.05 for x in s]) > 0.9


def _kit(click: bool, claps: bool, n_beats: int = 48, period: float = 0.5):
    """drum stem at 22,050 Hz: a kick on every beat (+ a broadband click), claps on every other beat."""
    from slop.audio import hits as HM
    rng = np.random.default_rng(5)
    sr = HM.SR
    beats = 0.5 + period * np.arange(n_beats)
    y = np.zeros(int((beats[-1] + 1.0) * sr), np.float32)
    tt = np.arange(int(.12 * sr)) / sr
    k = (0.8 * np.sin(2 * np.pi * np.cumsum(50 + 60 * np.exp(-tt * 35)) / sr) * np.exp(-tt * 20)).astype(np.float32)
    for j, b in enumerate(beats):
        i = int(b * sr)
        y[i:i + len(k)] += k
        if click:
            y[i:i + 60] += (0.2 * rng.standard_normal(60)).astype(np.float32)
        if claps and j % 2 == 1:
            n = int(.1 * sr)
            y[i:i + n] += (0.9 * np.diff(rng.standard_normal(n + 1)) * np.exp(-np.arange(n) / sr * 40)).astype(np.float32)
    return y, beats


@pytest.mark.parametrize("claps", [False, True])
def test_kick_click_rule_auto(claps):
    from slop.audio import hits as HM
    y, beats = _kit(click=True, claps=claps)
    z = np.zeros_like(y)
    H = HM.analyse(y, z, z, z, y, beats, beats[::4])
    if claps:                         # claps on the kicks every other beat: kept
        assert H["kick_click"]["backbeat"] is not None and len(H["snare"]) >= 0.8 * len(beats) / 2
    else:                             # a broadband kick alone: its click is not a snare (the original rule)
        assert H["kick_click"]["backbeat"] is None and len(H["snare"]) <= 2
    forced = HM.analyse(y, z, z, z, y, beats, beats[::4], {"kick_click": True})
    assert len(forced["snare"]) <= 2
    kept = HM.analyse(y, z, z, z, y, beats, beats[::4], {"kick_click": False})
    assert len(kept["snare"]) >= len(H["snare"])


def test_rerun_is_idempotent_and_overrides_apply(proj):
    root, song, _ = proj
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats,sections,hits")
    assert rc == 0
    assert all(v["status"] == "up-to-date" for v in out["steps"].values()), out["steps"]
    # project override: downbeat phase + a hand-added hit
    pj = json.loads((root / "project.json").read_text())
    pj["audio"] = {"downbeat_phase": 2, "hits": {"add": [[30.0, 0.9]], "drop": []}}
    (root / "project.json").write_text(json.dumps(pj))
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats")
    assert rc == 0 and out["steps"]["beats"]["status"] == "done"
    # the bars moved: sections (inside beats.json) and hits.json are rebuilt in the same run
    assert out["steps"]["sections"]["status"] == "done" and out["steps"]["hits"]["status"] == "done", out["steps"]
    B = json.loads((root / "analysis" / "beats.json").read_text())
    assert B["downbeat_phase"] == 2 and B["downbeat_method"] == "project.json"
    assert B["downbeats"][0] == B["beats"][2]
    assert B["sections"] and all(any(abs(s_["t0"] - d) < 1e-3 for d in [0.0] + B["downbeats"]) for s_ in B["sections"])
    assert not any("sections cleared" in n for n in B["notes"])
    H = json.loads((root / "analysis" / "hits.json").read_text())
    assert any(abs(h["t"] - 30.0) < 0.01 for h in H["hits"])
    # the chord-change vote is opt-in; a bad method name is a clear error
    pj["audio"] = {"downbeat_method": "harmony"}
    (root / "project.json").write_text(json.dumps(pj))
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats")
    assert rc == 0 and json.loads((root / "analysis" / "beats.json").read_text())["downbeat_method"] == "harmony"
    pj["audio"] = {"downbeat_method": "vibes"}
    (root / "project.json").write_text(json.dumps(pj))
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats")
    assert rc == 1 and "downbeat_method" in out["error"]
    pj["audio"] = {}
    (root / "project.json").write_text(json.dumps(pj))
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats,sections,hits")
    assert rc == 0, out


def test_report_written(proj):
    root, _, out = proj
    rep = (root / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "## Beat map" in rep and "## EAR CHECK" in rep and "Per-bar stem energy" in rep
    assert "report.md" in out["text"]


def test_engine_assets_conversion(proj):
    from slop.audio import engine_assets
    root, _, _ = proj
    H = engine_assets.hits_obj(root)
    assert {"impact", "riser", "ride", "fill", "vox_on", "env", "kick_s"} <= set(H)
    B = engine_assets.beats_obj(root)
    assert B["beats"] and "rms24" in B and B["words"] == []


def test_missing_stems_is_a_clear_error(tmp_path):
    song = synth.make_song(dur=12.0)
    root = synth.write_project(tmp_path / "p", song)
    for f in (root / "audio" / "stems").glob("drums.wav"):
        f.unlink()
    rc, out = slop("-p", str(root), "analyze", "--steps", "beats")
    assert rc == 1 and "stems" in out["error"]


def test_no_project_is_an_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    rc, out = slop("analyze")
    assert rc == 1 and "--project" in out["error"]


def test_spectrum_step(proj):
    import base64
    root, _, _ = proj
    rc, out = slop("-p", str(root), "analyze", "--steps", "spectrum")
    assert rc == 0, out
    S = json.loads((root / "analysis" / "spectrum.json").read_text())
    assert S["fps"] == 24 and S["bands"] == 64 and len(S["f"]) == 64 and S["n"] == int(np.ceil(40 * 24))
    assert len(base64.b64decode(S["vocals"])) == S["n"] * 64 and set(S["ref_db"]) == {"vocals", "mix"}
