"""avsync port: synthetic takes that copy, shift, diverge from or ignore the reference window."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop.config import SlopError  # noqa: E402
from slop.sync import avsync  # noqa: E402
from slop.sync.songdata import SongData  # noqa: E402

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
SONG_T0 = 10.0
DUR = 6.0


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("avsync")
    ref = H.babble(DUR, seed=1)
    other = H.babble(DUR, seed=2)
    rng = np.random.default_rng(9)
    cases = {
        "copy": ref + .003 * rng.standard_normal(len(ref)).astype(np.float32),
        "shift": np.r_[np.zeros(int(.35 * H.SR), np.float32), ref][: len(ref)],
        "diverge": np.r_[ref[: int(2.5 * H.SR)], other[int(2.5 * H.SR):]],
        "resynth": other,
    }
    H.write_wav(d / "ref.wav", ref)
    out = {"ref": d / "ref.wav", "dir": d}
    for k, x in cases.items():
        H.write_wav(d / f"{k}.wav", x)
        out[k] = H.make_mp4(d / f"{k}.mp4", d / f"{k}.wav")
    out["silent"] = H.make_mp4(d / "silent.mp4", None, duration=2)
    return out


@pytest.fixture(scope="module")
def song():
    return SongData(None, words=H.words_doc(), beats={"beats": [round(i * .5, 3) for i in range(80)]})


def test_constants_are_the_calibrated_ones():
    assert (avsync.SR, avsync.HOP, avsync.NFFT, avsync.FR) == (16000, 160, 1024, 100)
    fb = avsync.mel_fb()
    assert fb.shape == (80, 513) and fb.min() >= 0


def test_helpers_match_naive_versions():
    x = np.random.default_rng(0).standard_normal(500)
    naive = np.array([x[max(0, i - 5):min(len(x), i + 5)].sum() for i in range(len(x))])
    assert np.allclose(avsync.win_sum(x, 10), naive)
    ref = np.random.default_rng(1).standard_normal(16000).astype(np.float32)
    clip = np.r_[np.zeros(800, np.float32), ref][:16000]
    lag, ncc = avsync.global_lag(clip, ref)
    assert lag == 800 and ncc > .9
    r = avsync.on_clip(ref, -100, 1000)
    assert np.allclose(r, ref[100:1100])


def test_copy_is_in_sync_for_the_whole_clip(media, song):
    o = avsync.check(media["copy"], media["ref"], SONG_T0, song=song)
    assert o["mode"] == "copy" and o["lag_ncc"] > .6
    assert abs(o["lag_s"]) < .01
    assert not o["diverges"] and o["diverge_at"] is None
    assert o["spans"] and o["spans"][0][0] < .2 and o["spans"][-1][1] > DUR - .5
    json.dumps(o)                                                    # JSON-clean (no numpy scalars)


def test_shift_measures_the_lag_and_maps_song_time(media, song):
    o = avsync.check(media["shift"], media["ref"], SONG_T0, song=song)
    assert abs(o["lag_s"] - .35) < .005 and o["mode"] == "copy"
    assert not o["diverges"]
    a, b = o["spans"][0]
    sa, sb = o["spans_song"][0]
    assert abs(sa - (SONG_T0 + a - o["lag_s"])) < 1e-3                # song = song_t0 + clip_t − lag
    assert abs(sb - (SONG_T0 + b - o["lag_s"] - .042)) < 1e-3


def test_divergence_and_cut_on_the_last_eighth(media, song, tmp_path):
    png = tmp_path / "fig.png"
    o = avsync.check(media["diverge"], media["ref"], SONG_T0, png=png, song=song, title="Demo")
    assert o["diverges"] and 2.0 < o["diverge_at"] < 2.9
    assert o["synced_until"] < 2.6
    us = o["synced_until_song"]
    assert abs(us - (SONG_T0 + o["synced_until"] - o["lag_s"])) < 1e-3
    e8 = o["cut_eighth_song"]
    assert e8 <= us and us - e8 < .25 + 1e-9 and abs(e8 * 4 - round(e8 * 4)) < 1e-9   # eighths of 120 BPM: .25 s grid
    assert o["cut_beat_song"] <= us and abs(o["cut_beat_song"] * 2 - round(o["cut_beat_song"] * 2)) < 1e-9
    assert abs(o["cut_eighth_clip"] - (e8 - SONG_T0 + o["lag_s"])) < 1e-3
    from PIL import Image
    with Image.open(png) as im:
        assert im.size == (1650, 902)


def test_resynth_is_not_a_copy(media, song):
    o = avsync.check(media["resynth"], media["ref"], SONG_T0, song=song)
    assert o["mode"] == "resynth" and o["lag_ncc"] < .2
    assert o["diverges"]


def test_no_song_t0_has_no_song_fields(media):
    o = avsync.check(media["copy"], media["ref"])
    assert "spans_song" not in o and o["song_t0"] is None


def test_take_without_audio_is_a_clear_error(media):
    with pytest.raises(SlopError, match="no audio stream"):
        avsync.check(media["silent"], media["ref"], SONG_T0)


def test_cli_sync_check(media, tmp_path, monkeypatch):
    from slop.cli import main
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "o.json"
    rc = main(["--json", "sync", "check", str(media["diverge"]), str(media["ref"]), "--song-t0", "10", "--out-json", str(out)])
    assert rc == 0
    o = json.loads(out.read_text())
    assert o["diverges"] is True


def test_sync_check_refuses_a_named_project_that_does_not_exist(media, tmp_path, monkeypatch, capsys):
    from slop.cli import main
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "none"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    rc = main(["--json", "--project", "no-such-song", "sync", "check", str(media["copy"]), str(media["ref"]), "--song-t0", "10"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and "no-such-song" in out["error"] and "--project" in out["error"]
    rc = main(["--json", "sync", "check", str(media["copy"]), str(media["ref"]), "--song-t0", "10"])   # none named: fine
    assert rc == 0 and json.loads(capsys.readouterr().out)["mode"]
