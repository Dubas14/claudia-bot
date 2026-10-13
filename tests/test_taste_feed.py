"""slop.taste.feed: the card policy (cold start, explore/model, pairs, repeats, re-posts) and a simulated user."""
import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.taste import model as M  # noqa: E402
from slop.taste.feed import WHY, Feed  # noqa: E402
from slop.taste.store import read_events, split_events, taps_path  # noqa: E402


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    return S.make_project(tmp_path)


def test_cold_start_is_stratified_and_pair_free(proj):
    ids, lab = S.fake_pool(proj, clusters=5, per=30)
    f = Feed(proj, seed=1)
    cards = []
    while len(cards) < 40:
        batch = f.next([c["key"] for c in cards])["cards"]
        assert all(c["type"] == "single" for c in batch)            # no pairs during the cold start
        cards += batch
    first40 = cards[:40]
    assert all(c["why"] == "cold" for c in first40)
    assert len({c["item"] for c in first40}) == 40
    labs = [lab[ids.index(c["item"])] for c in first40]
    assert min(np.bincount(labs, minlength=5)) >= 4                  # every cluster seen


def test_policy_after_cold_start_pairs_repeats_and_learning(proj):
    ids, lab = S.fake_pool(proj, clusters=4, per=60, spread=0.45)
    liked = {0, 2}
    prefer = lambda i: lab[ids.index(i)] in liked if i in ids else False
    f = Feed(proj, seed=3)
    log = S.simulate_taps(f, prefer, 170, rng=random.Random(5))
    whys = [c.get("why") for c in log if c["type"] == "single"]
    assert whys[:40] == ["cold"] * 40
    pairs = [c for c in log if c["type"] == "pair"]
    assert pairs and all(c["key"].startswith("h:") for c in pairs)
    n_singles = sum(1 for c in log if c["type"] == "single")
    assert 0.05 < len(pairs) / max(1, len(log) - 40) < 0.3          # ~1 card in 7 after the cold start
    reps = [c for c in log if c.get("why") == "repeat"]
    assert 4 <= len(reps) <= 6                                        # scheduled self-agreement repeats
    ev = read_events(taps_path(proj))
    tapped = [e for e in ev if e.get("action")]
    first_rep = next(k for k, e in enumerate(tapped) if e.get("why") == "repeat")
    assert first_rep >= M.REPEAT_GAP
    assert M.self_agreement(ev)["self_agreement"] == 1.0              # a perfectly consistent simulated user
    # the model's picks are liked more than random explores (research: 0.507 vs 0.178)
    rate = lambda w: np.mean([e["action"] == "like" for e in tapped if e.get("why") == w])
    assert rate("model") > 0.75 and rate("model") > rate("explore")
    # pair rows carry the position-bias fields
    pr = [e for e in ev if e.get("winner")]
    assert all(e["shown"] in ("ab", "ba") and e["layout"] in ("row", "stack") for e in pr)
    assert n_singles > 100
    unary, prs = split_events(ev)
    idx = {i: k for k, i in enumerate(f.ids)}
    met = M.meter(f.X, idx, unary, prs, reps=1)
    assert met["accuracy"] > 0.85


def test_reposts_and_seen_items_are_never_served(proj):
    ids, lab = S.fake_pool(proj, clusters=2, per=20)
    # an exact re-post of img-c0-000 under another id
    from slop.taste.embed import load_store, save_store
    from slop.taste.store import append_jsonl, pool_index
    i0, X, meta = load_store(proj)
    append_jsonl(pool_index(proj), {"id": "img-repost", "kind": "human", "src": "dir", "w": 1, "h": 1, "sha1": "x" * 40})
    save_store(proj, i0 + ["img-repost"], np.concatenate([X, X[:1]]), meta)
    f = Feed(proj, seed=0)
    for k in range(6):
        f.record_tap({"item": ids[k], "action": "like" if k % 2 else "pass"})
    f.record_tap({"item": "img-c0-000", "action": "like"})
    f.refit()
    served = set()
    for _ in range(8):
        for c in f.cards(list(served), n=6):
            served.add(c["key"])
    assert "img-repost" not in served and "img-c0-000" not in served and ids[1] not in served


def test_unembedded_images_still_served_and_writes_validate(proj):
    ids, lab = S.fake_pool(proj, clusters=2, per=5, unembedded=6)
    f = Feed(proj, seed=0)
    keys = []
    for _ in range(4):
        keys += [c["key"] for c in f.next(keys)["cards"]]
    assert any(k.startswith("img-new-") for k in keys)
    with pytest.raises(ValueError):
        f.record_tap({"item": "nope", "action": "like"})
    with pytest.raises(ValueError):
        f.record_pair({"a": ids[0], "b": ids[0], "winner": "a"})
    rec = f.record_tap({"item": ids[0], "action": "like", "dwell_ms": "x", "why": "hack" * 9})
    assert rec["dwell_ms"] == 0 and rec["why"] == ""
    f.undo(rec["eid"])
    assert not [e for e in read_events(taps_path(proj)) if e.get("item") == ids[0]]
    s = f.summary()
    assert s["taps"] == 0 and s["pool"] == 16 and s["embedded"] == 10 and s["target"] == 150


def test_liked_list_newest_first(proj):
    ids, lab = S.fake_pool(proj, clusters=1, per=5)
    f = Feed(proj, seed=0)
    for i in ids[:3]:
        f.record_tap({"item": i, "action": "like"})
    assert [x["id"] for x in f.liked()] == [ids[2], ids[1], ids[0]]


def test_background_embedding_fills_vectors(proj, tmp_path, monkeypatch):
    from slop.taste import embed as E
    from slop.taste.feed import wait_for
    from slop.taste.pool import PoolWriter, add_dir
    S.write_images(tmp_path / "refs", {"grey": 4, "red": 3, "colour": 3})
    add_dir(PoolWriter(proj), tmp_path / "refs")
    fe = S.FakeEmbedder()
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    f = Feed(proj, seed=0)
    assert len(f.ids) == 0 and f.next([])["cards"]                     # unembedded images are served meanwhile
    f.start_embedding()
    assert f.embedding["running"] is True
    n = len(f.pool)
    assert wait_for(lambda: not f.embedding.get("running") and len(f.ids) == n, timeout=60), (f.embedding, len(f.ids), n)
    assert f.embedding.get("done") == n and len(f.cold) == n


def test_running_feed_picks_up_pool_additions(proj, tmp_path, monkeypatch):
    from slop.taste import embed as E
    from slop.taste.feed import wait_for
    from slop.taste.pool import PoolWriter, add_dir
    S.fake_pool(proj, clusters=2, per=5)
    fe = S.FakeEmbedder("fake", tag="local-fake-p576")                 # the same model as the store (one model forever)
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    f = Feed(proj, seed=0, background=True)
    f.auto_embed = True
    assert len(f.serve_ids) == 10
    S.write_images(tmp_path / "more", {"grey": 3, "red": 2})
    add_dir(PoolWriter(proj), tmp_path / "more")
    assert wait_for(lambda: f.dirty.set() or len(f.serve_ids) == 15, timeout=20)   # wake the loop (else every 15 s)
    assert wait_for(lambda: len(f.ids) == 15 and not f.embedding.get("running"), timeout=30)


def _grow_store(proj, n_new: int, d: int = S.DIM, seed: int = 9, prefix: str = "img-late", keys=None):
    """append n_new embedded images to the pool + vector store (what a background-embedding flush does)"""
    from slop.taste.embed import load_store, save_store
    from slop.taste.store import append_jsonl, pool_index
    ids, X, meta = load_store(proj)
    rng = np.random.default_rng(seed)
    new = [f"{prefix}-{k:03d}" for k in range(n_new)]
    V = rng.normal(size=(n_new, X.shape[1]))
    V /= np.linalg.norm(V, axis=1, keepdims=True)
    for i in new:
        row = {"id": i, "kind": "human", "src": "dir", "w": 800, "h": 600, "sha1": i.ljust(40, "0")}
        if keys:
            row["keys"] = keys
        append_jsonl(pool_index(proj), row)
    save_store(proj, ids + new, np.concatenate([X, V]), meta)
    return new


def test_reload_between_fits_never_indexes_stale_model_arrays(proj):
    # review repro: a 199-row store grown to 259 rows, reload() without refit, then cards() / human_pair()
    ids, lab = S.fake_pool(proj, clusters=1, per=199, spread=0.8)
    f = Feed(proj, seed=0)
    S.simulate_taps(f, lambda i: int(i[-3:]) % 3 == 0, 70, rng=random.Random(1))
    assert f.model is not None and f.model["Z"].shape[0] == 199
    new = _grow_store(proj, 60)
    f.reload()                                                       # the model still has 199 rows
    assert len(f.ids) == 259 and f.model["Z"].shape[0] == 199
    for _ in range(3):
        cards = f.cards([], n=6)                                     # used to raise IndexError (index 199 ...)
        assert cards
        assert not any(c["item"] in new and c["why"] == "model" for c in cards)   # unscored until the next fit
        f.human_pair([])
        j = f.next([])
        assert "cards" in j
    f.refit()
    assert f.model["Z"].shape[0] == 259 and f.model["space"] is f.space


def test_server_answers_500_json_instead_of_dropping(proj, monkeypatch):
    import json as _json
    import threading as _th
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer
    from slop.taste import server as SV
    S.fake_pool(proj, clusters=2, per=10)
    app = SV.App(proj, "tok_" + "y" * 20, embed=False, background=False)
    monkeypatch.setattr(app.feed, "next", lambda ex: (_ for _ in ()).throw(IndexError("boom")))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), SV.make_handler(app))
    _th.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/{app.token}/api/next"
        r = urllib.request.Request(url, data=b'{"exclude": []}', headers={"content-type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(r, timeout=10)
        assert e.value.code == 500 and "error" in _json.loads(e.value.read())
    finally:
        httpd.shutdown()


def test_exhausted_pool_asks_for_one_repeat_at_a_time(proj):
    ids, lab = S.fake_pool(proj, clusters=2, per=35)
    f = Feed(proj, seed=2)
    for k, i in enumerate(ids):
        f.record_tap({"item": i, "action": "like" if lab[k] == 0 else "pass", "why": "cold"})
    f.refit()
    j = f.next([])
    assert len(j["cards"]) == 1 and j["cards"][0]["why"] == "repeat"   # used to be all due repeats at once
    c = j["cards"][0]
    f.record_tap({"item": c["item"], "action": "like", "why": "repeat"})
    j2 = f.next([])
    assert j2["cards"] == [] and j2["exhausted"] is True


def test_same_project_rule_holds_for_random_cards_and_fallback_is_labelled(proj):
    ids, lab = S.fake_pool(proj, clusters=3, per=30, spread=0.9)
    same = _grow_store(proj, 6, prefix="img-proj", keys=["behance:42"])
    f = Feed(proj, seed=4)
    S.simulate_taps(f, lambda i: i.startswith("img-c0"), 45, rng=random.Random(2))
    seen_keys = [same[0]]
    for _ in range(6):
        batch = f.cards(seen_keys, n=6)
        assert batch and all(c["why"] in WHY for c in batch)
        assert not any(c["item"] in same[1:] for c in batch)          # never next to a queued same-project card
        seen_keys += [c["key"] for c in batch]
    assert "fallback" in WHY
