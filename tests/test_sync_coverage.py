"""coverage(): sung seconds held by in-sync spans (port of the production run loop's check) + the review render."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop.sync.coverage import coverage  # noqa: E402

WORDS = [{"t0": a, "t1": b} for a, b in [(10.0, 10.3), (10.35, 10.55), (10.6, 11.0), (11.1, 11.35), (11.4, 11.7),
                                        (11.75, 11.9), (11.95, 12.05), (12.1, 12.6), (13.4, 13.7)]]
NEED = [10.0, 12.6]


def test_sung_seconds_exclude_silence_and_clip_to_need():
    cov, tot, gaps = coverage([], WORDS, NEED)
    # words ±30 ms, merged within .12 s -> one stretch 10.0 .. 12.6 (clipped to need); 13.4 is outside
    assert tot == pytest.approx(2.6) and cov == 0 and gaps == [[10.0, 12.6]]


def test_full_and_partial_cover():
    cov, tot, gaps = coverage([[10.0, 12.6]], WORDS, NEED)
    assert cov == pytest.approx(tot) and gaps == []
    cov, tot, gaps = coverage([[10.06, 11.3]], WORDS, NEED, min_gap=.6)   # span starts are extended 60 ms
    assert cov == pytest.approx(1.3) and gaps == [[11.3, 12.6]]


def test_short_slips_are_tolerated_and_close_gaps_merge():
    cov, tot, gaps = coverage([[10.0, 11.0], [11.4, 12.6]], WORDS, NEED, min_gap=.6)
    assert gaps == []                                                     # a .46 s slip is "most lips"
    cov, tot, gaps = coverage([[10.0, 11.0], [11.4, 12.6]], WORDS, NEED, min_gap=.25)
    assert gaps == [[11.0, 11.34]]                                        # the next span starts 60 ms early
    cov, tot, gaps = coverage([[10.0, 10.5], [10.86, 10.95]], WORDS, NEED, min_gap=.25)
    assert gaps == [[10.5, 12.6]]                                         # gaps closer than .3 s merge


@pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")
def test_review_render(tmp_path):
    r = subprocess.run([H.FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True)
    if "drawtext" not in r.stdout:
        pytest.skip("ffmpeg without drawtext")
    from slop.sync import avsync
    ref = H.babble(4.0, seed=1)
    other = H.babble(4.0, seed=2)
    import numpy as np
    H.write_wav(tmp_path / "ref.wav", ref)
    H.write_wav(tmp_path / "take.wav", np.r_[ref[: int(2 * H.SR)], other[int(2 * H.SR):]])
    take = H.make_mp4(tmp_path / "take.mp4", tmp_path / "take.wav")
    o = avsync.review(take, tmp_path / "ref.wav", 10.0, tmp_path / "review.mp4")
    assert o["diverges"] and (tmp_path / "review.mp4").stat().st_size > 1000
