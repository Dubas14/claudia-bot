"""slop.taste.model: the ported feed model, the meter, the exact tests, onboarding helpers."""
import random

import numpy as np
import pytest

from slop.taste import model as M


def test_constants_are_the_calibrated_ones():
    assert M.LAMS == [0.3, 1, 3, 10, 30, 100]
    assert (M.EXPLORE, M.PAIR_EVERY, M.DUP_COS, M.REPEAT) == (0.15, 7, 0.93, 0.04)
    assert M.KINDS == ["human", "generated", "composed"]
    assert M.COLD_START == 40 and M.KNN_K == 10
    assert [M.adaptive_k(n) for n in (0, 60, 96, 300, 768, 2000)] == [16, 16, 16, 50, 128, 128]


def test_exact_tests_reproduce_the_audit_numbers():
    # T1: 120/146 likes near-mono vs 129/184 passes -> Fisher p = 0.014 (research 11-gap-5 §2.2)
    assert M.fisher_exact(120, 26, 129, 55) == pytest.approx(0.014, abs=0.002)
    # T2: red given colour 16/30 likes vs 16/62 passes -> p = 0.012
    assert M.fisher_exact(16, 14, 16, 46) == pytest.approx(0.012, abs=0.002)
    # position bias: 61 of 90 decisive picks from the first slot -> two-sided binomial p = 0.00097
    assert M.binom_two_sided(61, 90) == pytest.approx(0.00097, abs=0.0001)
    assert M.binom_two_sided(21, 42) == pytest.approx(1.0)
    assert M.margin(372) == pytest.approx(0.0508, abs=0.0005)


def test_predicted_curve_and_auc():
    assert M.predicted(100) == pytest.approx(0.732, abs=0.002)
    assert M.predicted(300) == pytest.approx(0.81, abs=0.003)
    assert M.auc([3, 2, 1, 0], [1, 1, 0, 0]) == 1.0
    assert M.auc([1, 1], [1, 0]) == 0.5
    assert M.auc([1, 2], [1, 1]) is None


def test_fit_logistic_recovers_direction():
    rng = np.random.default_rng(0)
    A = rng.normal(size=(400, 5))
    w_true = np.array([2.0, -1.0, 0, 0, 0.5])
    y = (rng.random(400) < M.sigmoid(A @ w_true)).astype(float)
    w, H = M.fit_logistic(A, y, np.ones(400), 1.0)
    assert np.corrcoef(w, w_true)[0, 1] > 0.95
    assert H.shape == (5, 5)


def synth_space(n=240, d=24, seed=0):
    rng = np.random.default_rng(seed)
    centers = rng.normal(size=(4, d))
    lab = rng.integers(0, 4, n)
    X = centers[lab] + 0.6 * rng.normal(size=(n, d))
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    ids = [f"img-{k:04d}" for k in range(n)]
    return ids, X.astype("float32"), lab


def test_model_learns_a_two_mode_taste_and_meter_beats_chance():
    ids, X, lab = synth_space()
    index = {i: k for k, i in enumerate(ids)}
    liked_modes = {0, 2}                      # taste with two separate modes (the kNN term's raison d'être)
    rng = random.Random(1)
    order = list(range(len(ids)))
    rng.shuffle(order)
    unary = [(ids[k], 1.0 if lab[k] in liked_modes else 0.0, "human") for k in order[:150]]
    pairs = []
    for _ in range(20):
        a, b = rng.sample(order[150:], 2)
        if (lab[a] in liked_modes) != (lab[b] in liked_modes):
            pairs.append((ids[a], ids[b], 1.0 if lab[a] in liked_modes else 0.0))
    m = M.fit(X, index, unary, pairs)
    assert m is not None and m["k"] == min(M.adaptive_k(len(unary) + len(pairs)), X.shape[1])
    assert m["lam"] in M.LAMS and m["knn"] is not None
    s = M.taste_scores(X, index, unary, pairs)
    held = order[150:]
    a = M.auc(s[held], [1.0 if lab[k] in liked_modes else 0.0 for k in held])
    assert a > 0.9
    met = M.meter(X, index, unary, pairs, reps=1)
    assert met["accuracy"] > 0.8 and met["n"] == len(unary) + len(pairs)
    assert met["margin"] == pytest.approx(M.margin(met["n"]), abs=1e-4)
    # Thompson draws vary but stay correlated with the mean
    d1 = M.linear_scores(m, draw=True, rng=np.random.default_rng(1))
    d0 = M.linear_scores(m)
    assert np.corrcoef(d0, d1)[0, 1] > 0.5 and not np.allclose(d0, d1)


def test_fit_needs_rows_and_lambda_rule():
    ids, X, lab = synth_space(60)
    index = {i: k for k, i in enumerate(ids)}
    assert M.fit(X, index, [(ids[0], 1.0, "human")], []) is None
    unary = [(ids[k], float(lab[k] == 0), "human") for k in range(20)]
    assert M.fit(X, index, unary, [])["lam"] == 10.0   # λ = 10 below 40 rows
    assert M.meter(X, index, unary[:10], []) is None    # the meter needs >= 20 rows


def test_cold_start_is_stratified_over_clusters():
    ids, X, lab = synth_space(400)
    order = M.cold_start_order(X, 40, seed=3)
    assert len(order) == 40 and len(set(order)) == 40
    counts = np.bincount(lab[order], minlength=4)
    assert counts.min() >= 5                     # every mode seen early


def test_self_agreement_and_stop_rule():
    ev = [{"item": "a", "action": "like"}, {"item": "b", "action": "pass"},
          {"item": "a", "action": "like", "why": "repeat"}, {"item": "b", "action": "like", "why": "repeat"}]
    assert M.self_agreement(ev) == {"repeats": 2, "self_agreement": 0.5}
    assert M.stop_rule([], 210)["stop"]
    assert "more taps" in M.stop_rule([], 30)["why"]
    flat = [{"n": n, "accuracy": 0.75, "source": "app"} for n in range(20, 201, 10)]
    assert M.stop_rule(flat, 149)["stop"] is False                   # never before the recommended 150
    assert M.stop_rule(flat, 150)["stop"] is True                    # a flat smoothed meter on two checks
    rising = [{"n": n, "accuracy": 0.6 + 0.001 * n, "source": "app"} for n in range(20, 201, 10)]
    assert M.stop_rule(rising, 170)["stop"] is False                 # +5 points over 50 rows: keep going


def _app_meter_path(seed: int, upto: int = 190):
    """the app's meter readings every 10 rows (reps=2): flat ~0.70 until ~150 then rising to ~0.79, with the
    5-9 point swings between consecutive readings that the review measured on the author's 372-tap replay"""
    rng = np.random.default_rng(seed)
    out = []
    for n in range(20, upto + 1, 10):
        base = 0.70 if n < 150 else 0.70 + 0.09 * min(1.0, (n - 150) / 100)
        out.append({"n": n, "accuracy": float(base + rng.choice([-1, 1]) * rng.uniform(0.025, 0.045)), "source": "app"})
    return out


def _old_rule(history, taps):
    """the literal rule as first shipped: one reading vs the one >= 50 rows earlier, from 60 taps"""
    if taps >= M.STOP_AT:
        return True
    h = [r for r in history if r.get("accuracy") is not None]
    if not h:
        return False
    last = h[-1]
    older = [r for r in h if r["n"] <= last["n"] - M.STOP_WINDOW]
    return bool(older and last["n"] >= M.MIN_TAPS and abs(last["accuracy"] - older[-1]["accuracy"]) < M.STOP_DELTA)


def test_stop_rule_ignores_noise_in_the_flat_stretch():
    old_early = 0
    for seed in range(12):
        path = _app_meter_path(seed)
        cli = [{"n": r["n"] + 3, "accuracy": r["accuracy"] + 0.08, "source": "cli"} for r in path[::4]]
        hist = sorted(path + cli, key=lambda r: r["n"])
        fired_old = False
        for r in path:
            h = [x for x in hist if x["n"] <= r["n"] + 3]
            if r["n"] < M.TARGET_TAPS:
                assert M.stop_rule(h, r["n"])["stop"] is False, (seed, r["n"])   # never in the flat stretch
                fired_old |= _old_rule(h, r["n"])
        old_early += fired_old
    assert old_early >= 8          # the replayed noise really did trip the literal rule before 150 taps


def test_stop_rule_needs_two_consecutive_quiet_checks():
    flat = [{"n": n, "accuracy": 0.75, "source": "app"} for n in range(20, 191, 10)]
    assert M.stop_rule(flat, 190)["stop"] is True
    spiky = [dict(r, accuracy=0.85) if r["n"] == 110 else r for r in flat]
    assert M.stop_rule(spiky, 190)["stop"] is False                  # the latest check is quiet, the one before is not
    cli_only = [dict(r, source="cli") for r in flat]
    assert M.stop_rule(cli_only, 190)["stop"] is True                # CLI readings are the fallback series


def test_kmeans_separates_blobs():
    rng = np.random.default_rng(0)
    X = np.concatenate([rng.normal(0, .1, (30, 3)) + [5, 0, 0], rng.normal(0, .1, (30, 3)) - [5, 0, 0]])
    lab = M.kmeans(X, 2, seed=0)
    assert len(set(lab[:30])) == 1 and len(set(lab[30:])) == 1 and lab[0] != lab[-1]
