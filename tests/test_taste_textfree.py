"""slop.taste.textfree: the in-pool paired probe (the user's own images vs lettered copies of them) for --sref refs.

The real-image validation (Midjourney plates prompted "no text" + lettered versions + real engine frames) is in the
track report; these tests pin the mechanics with the deterministic fake embedder, plus an opt-in real-model run on a
folder of the user's own text-free images (SLOP_TEST_TEXTFREE_DIR)."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.taste import textfree as TF  # noqa: E402
from slop.taste.embed import embed_pool, load_store  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402


def test_leave_one_pair_out_is_not_fooled_by_twins():
    rng = np.random.default_rng(0)
    k, dim = 30, 64
    unit = lambda A: A / np.linalg.norm(A, axis=-1, keepdims=True)
    base = unit(rng.normal(size=(k, dim)))                                 # embedding-like unit vectors
    d = unit(rng.normal(size=dim))
    X = np.vstack([base, unit(base + 0.5 * d + 0.02 * rng.normal(size=(k, dim)))])
    y = np.r_[np.zeros(k), np.ones(k)]
    w, b, loo = TF._ridge_dual(X, y)
    assert TF._auc(loo[k:], loo[:k]) > 0.95                 # each pair predicted by a model that never saw either
    assert ((X @ w + b)[k:] > (X @ w + b)[:k]).mean() == 1.0
    new_clean = unit(rng.normal(size=(50, dim)))
    new_let = unit(new_clean + 0.5 * d)
    assert TF._auc(new_let @ w, new_clean @ w) > 0.95       # generalises to images it never saw


def test_render_lettered_is_deterministic_and_adds_lettering():
    im = S.image("grey", 3, size=(800, 600))
    for kind in TF.LETTER_KINDS:
        a, b = TF.render_lettered(im, kind, 11), TF.render_lettered(im, kind, 11)
        assert a.tobytes() == b.tobytes() and a.tobytes() != im.tobytes() and a.size == im.size


@pytest.fixture
def pool(tmp_path, monkeypatch):
    """84 clean synthetic images + 16 with big headlines (what the fake embedder can see)"""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    d = tmp_path / "refs"
    S.write_images(d, {"grey": 24, "dark": 12, "light": 12, "red": 12, "colour": 12, "blue": 12})
    for k in range(16):
        TF.render_lettered(S.image(["grey", "colour", "blue", "dark"][k % 4], 900 + k), "headline", 40 + k) \
            .save(d / f"lettered-{k:03d}.png")
    add_dir(PoolWriter(p), d)
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    items = load_pool(p)
    ids, X, meta = load_store(p)
    return p, fe, items, ids, X / np.linalg.norm(X, axis=1, keepdims=True), meta


def test_paired_probe_on_a_pool(pool):
    p, fe, items, ids, X, meta = pool
    assert len(ids) >= 72
    s, info = TF.assess(p, ids, X, items, meta, embedder=fe)
    assert info["score"] == "paired-probe" and info["backgrounds"] >= 24 and info["loo_auc"] > 0.9
    assert info["cutoff"] == pytest.approx(min(info["midpoint"], info["clean_q90"]), abs=1e-4)
    assert info["embedded_now"] == info["backgrounds"]
    let = np.array([items[i]["title"].startswith("lettered") for i in ids])
    ref = s < info["cutoff"]
    # (the fake model is crude; the real SigLIP numbers are in textfree.py's docstring)
    assert (~ref[let]).mean() >= 0.9 and ref[~let].mean() >= 0.3 and info["clean_share"] == pytest.approx(ref.mean(), abs=1e-3)
    # the copies are cached per image: a rerun embeds nothing and gives the same probe
    calls = fe.image_calls
    s2, again = TF.assess(p, ids, X, items, meta, embedder=fe)
    assert again["embedded_now"] == 0 and fe.image_calls == calls and again["cutoff"] == info["cutoff"]
    assert np.allclose(s, s2)
    # an absolute --text-max is on the probe's scale
    _, abs_ = TF.assess(p, ids, X, items, meta, embedder=fe, text_max=0.5)
    assert abs_["cutoff"] == 0.5 and abs_["method"].startswith("--text-max (absolute, on the paired-probe")


def test_small_pools_and_failing_copies_fall_back_to_the_zero_shot_fifth(pool):
    p, fe, items, ids, X, meta = pool
    few = ids[:36]                                                         # under 40 images: no paired probe
    s, info = TF.assess(p, few, X[:36], items, meta, embedder=fe)
    assert info["score"] == "zero-shot" and "too few" in info["method"] and info["method"].startswith("stricter of")
    assert info["score_range"][0] <= info["cutoff"] or info["clean_share"] == 0.0

    class NoImages:
        def embed_texts(self, texts):
            return fe.embed_texts(texts)

        def embed_images(self, paths):
            return [None] * len(paths)
    TF_cache = Path(os.environ["SLOP_HOME"]) / "cache" / "embed" / meta["tag"] / f"letter-v{TF.POOL_PROBE_VERSION}"
    for f in TF_cache.glob("*.npy"):
        f.unlink()
    s, info = TF.assess(p, ids, X, items, meta, embedder=NoImages())
    assert info["score"] == "zero-shot" and "could be embedded" in info["method"]


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("SLOP_TEST_TEXTFREE_DIR"),
                    reason="set SLOP_TEST_TEXTFREE_DIR to a folder of >= 100 text-free images (real SigLIP 2 base)")
def test_paired_probe_on_real_text_free_images(tmp_path, monkeypatch):
    """the user's own text-free images (e.g. their Midjourney plates) + lettered copies of a held-out fifth"""
    import random
    import shutil
    from slop.taste.embed import LocalSiglip
    from PIL import Image
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HF_HOME", os.environ.get("HF_HOME", str(Path.home() / ".claudia" / "cache" / "hf")))
    src = sorted(Path(os.environ["SLOP_TEST_TEXTFREE_DIR"]).rglob("*.jpg"))
    random.Random(0).shuffle(src)
    src = src[:200]
    d = tmp_path / "refs"
    d.mkdir()
    for k, f in enumerate(src):
        if k % 5 == 0:
            TF.render_lettered(Image.open(f), TF.LETTER_KINDS[k % 3], 7000 + k).save(d / f"lettered-{k:03d}.jpg")
        else:
            shutil.copy(f, d / f"clean-{k:03d}.jpg")
    p = S.make_project(tmp_path)
    add_dir(PoolWriter(p), d)
    emb = LocalSiglip()
    embed_pool(p, embedder=emb, log=lambda m: None)
    items = load_pool(p)
    ids, X, meta = load_store(p)
    s, info = TF.assess(p, ids, X / np.linalg.norm(X, axis=1, keepdims=True), items, meta, embedder=emb)
    let = np.array([items[i]["title"].startswith("lettered") for i in ids])
    ref = s < info["cutoff"]
    assert info["score"] == "paired-probe" and (~ref[let]).mean() >= 0.9 and ref[~let].mean() >= 0.5, info
