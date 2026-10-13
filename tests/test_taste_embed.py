"""slop.taste.embed: store + per-image cache + one-model rule, OpenRouter provider (mocked), real SigLIP 2 (slow)."""
import base64
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.config import SlopError  # noqa: E402
from slop.taste import embed as E  # noqa: E402
from slop.taste import net  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    S.write_images(tmp_path / "refs", {"grey": 5, "red": 4, "colour": 3})
    add_dir(PoolWriter(p), tmp_path / "refs")
    return p


def test_embed_pool_store_cache_and_idempotence(proj, tmp_path):
    fe = S.FakeEmbedder()
    r = E.embed_pool(proj, embedder=fe, log=lambda m: None)
    assert r["computed"] == 12 and r["embedded"] == 12
    ids, X, meta = E.load_store(proj)
    assert len(ids) == 12 and X.shape == (12, S.DIM) and meta["tag"] == fe.tag and meta["dim"] == S.DIM
    assert np.allclose(np.linalg.norm(X, axis=1), 1, atol=2e-3)              # float16 store, L2-normalised
    r2 = E.embed_pool(proj, embedder=fe, log=lambda m: None)
    assert r2["todo"] == 0
    # a second project with the same images reuses the per-image cache (no model calls)
    p2 = S.make_project(tmp_path, "other")
    add_dir(PoolWriter(p2), tmp_path / "refs")
    fe2 = S.FakeEmbedder()
    r3 = E.embed_pool(p2, embedder=fe2, log=lambda m: None)
    assert r3["cached"] == 12 and fe2.image_calls == 0


def test_one_model_forever_unless_reembed(proj):
    E.embed_pool(proj, embedder=S.FakeEmbedder("model-a"), log=lambda m: None)
    with pytest.raises(SlopError, match="not comparable"):
        E.embed_pool(proj, embedder=S.FakeEmbedder("model-b"), log=lambda m: None)
    r = E.embed_pool(proj, embedder=S.FakeEmbedder("model-b"), reembed=True, log=lambda m: None)
    assert r["embedded"] == 12 and E.load_store(proj)[2]["model"] == "model-b"


def test_text_vectors_cached(proj):
    fe = S.FakeEmbedder()
    E.embed_pool(proj, embedder=fe, log=lambda m: None)
    meta = E.load_store(proj)[2]
    V = E.text_vectors(meta, ["red accent color", "a poster"], embedder=fe)
    assert V.shape == (2, S.DIM) and fe.text_calls == 1
    E.text_vectors(meta, ["a poster", "red accent color"], embedder=fe)
    assert fe.text_calls == 1                                                    # served from the cache


def test_openrouter_provider_mocked_and_ledgered(proj, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-real")
    seen = []

    def fake_post(url, payload, headers=None, timeout=120):
        seen.append((url, payload, headers))
        assert url == E.OR_URL and headers["Authorization"].startswith("Bearer ")
        out = []
        for k, inp in enumerate(payload["input"]):
            u = inp["content"][0]["image_url"]["url"]
            assert u.startswith("data:image/jpeg;base64,") and len(base64.b64decode(u.split(",", 1)[1])) > 100
            out.append({"index": k, "embedding": list(np.random.default_rng(k).normal(size=16))})
        return 200, {}, json.dumps({"id": "gen-1", "data": out, "usage": {"cost": 0}}).encode()
    monkeypatch.setattr(net, "http_post_json", fake_post)
    emb = E.OpenRouterEmbedder(pdir=proj, sleep=lambda s: None)
    r = E.embed_pool(proj, embedder=emb, log=lambda m: None)
    assert r["computed"] == 12 and r["provider"] == "openrouter" and r["model"] == E.OR_MODEL
    assert all(p["model"].endswith(":free") for _, p, _ in seen) and len(seen) == 2   # batches of 8
    rows = [json.loads(line) for line in (proj / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and all(x["provider"] == "openrouter" and x["status"] == "ok" for x in rows)


def test_openrouter_errors(proj, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SlopError, match="OPENROUTER_API_KEY"):
        E.OpenRouterEmbedder(pdir=proj)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-real")
    monkeypatch.setattr(net, "http_post_json", lambda *a, **k: (402, {}, b'{"error": {"message": "no credits"}}'))
    with pytest.raises(SlopError, match="credits"):
        E.embed_pool(proj, embedder=E.OpenRouterEmbedder(pdir=proj, sleep=lambda s: None), log=lambda m: None)
    rows = [json.loads(line) for line in (proj / "ledger.jsonl").read_text().splitlines()]
    assert rows[-1]["status"] == "failed"


def test_paid_model_is_budget_checked(proj, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-real")
    pj = json.loads((proj / "project.json").read_text())
    pj["budget"] = {"openrouter_usd": 40, "confirm_over_usd": 0.001}
    (proj / "project.json").write_text(json.dumps(pj))
    monkeypatch.setattr(net, "http_post_json", lambda *a, **k: pytest.fail("must not call before confirmation"))
    emb = E.OpenRouterEmbedder("voyageai/voyage-multimodal-3.5", pdir=proj, sleep=lambda s: None)
    with pytest.raises(SlopError, match="--yes"):
        E.embed_pool(proj, embedder=emb, log=lambda m: None)


def test_paid_text_embeddings_are_budget_checked(proj, monkeypatch):
    """tokens / board text batches with a paid model: cap + confirm gate before the call (review round 1)"""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test-not-real")
    pj = json.loads((proj / "project.json").read_text())
    pj["budget"] = {"openrouter_usd": 40, "confirm_over_usd": 0.001}
    (proj / "project.json").write_text(json.dumps(pj))
    calls = []

    def fake_post(url, payload, headers=None, timeout=120):
        calls.append(payload)
        data = [{"index": k, "embedding": [1.0, float(k)]} for k in range(len(payload["input"]))]
        return 200, {}, json.dumps({"id": "gen-t", "data": data, "usage": {"cost": 0.0001}}).encode()
    monkeypatch.setattr(net, "http_post_json", fake_post)
    meta = {"provider": "openrouter", "model": "voyageai/voyage-multimodal-3.5", "tag": "openrouter-voyage", "dim": 2}
    with pytest.raises(SlopError, match="--yes"):
        E.text_vectors(meta, [f"phrase {k}" for k in range(10)], pdir=proj)       # est $0.002 > confirm $0.001
    assert calls == []                                                           # nothing spent before the gate
    V = E.text_vectors(meta, ["a poster", "tiny text"], pdir=proj, yes=True)
    assert V.shape == (2, 2) and len(calls) == 1
    pj["budget"] = {"openrouter_usd": 0.0001, "confirm_over_usd": 2}
    (proj / "project.json").write_text(json.dumps(pj))
    with pytest.raises(SlopError, match="cap"):
        E.text_vectors(meta, ["something new"], pdir=proj, yes=True)
    free = {**meta, "model": E.OR_MODEL, "tag": "openrouter-free"}
    E.text_vectors(free, ["a poster"], pdir=proj)                                # :free models need no gate
    assert len(calls) == 2


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("SLOP_TEST_SIGLIP"), reason="set SLOP_TEST_SIGLIP=1 to download (~1.5 GB, into $HF_HOME) and run SigLIP 2 base")
def test_real_siglip2_base_on_cpu(proj):
    r = E.embed_pool(proj, provider="local", log=lambda m: None)
    assert r["embedded"] == 12 and r["model"] == E.LOCAL_MODEL
    ids, X, meta = E.load_store(proj)
    assert X.shape == (12, 768) and meta["calib"]["scale"] > 10
    items = load_pool(proj)
    V = E.text_vectors(meta, ["a red rectangle on a dark background", "a grey photograph"])
    red = [k for k, i in enumerate(ids) if items[i]["title"].startswith("red")]
    grey = [k for k, i in enumerate(ids) if items[i]["title"].startswith("grey")]
    S_ = X @ V.T
    assert S_[red, 0].mean() > S_[grey, 0].mean()
