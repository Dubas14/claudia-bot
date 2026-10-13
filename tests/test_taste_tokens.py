"""slop.taste.imgstats + slop.taste.tokens: the audit statistics, tokens/look-bible (ask, never impose), boards."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.config import SlopError  # noqa: E402
from slop.taste import imgstats as I  # noqa: E402
from slop.taste import tokens as T  # noqa: E402
from slop.taste.embed import embed_pool  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402
from slop.taste.store import append_jsonl, new_eid, taps_path  # noqa: E402


def test_imgstats_on_synthetic_images(tmp_path):
    S.image("grey", 1).save(tmp_path / "g.png")
    S.image("red", 2).save(tmp_path / "r.png")
    S.image("colour", 3).save(tmp_path / "c.png")
    S.image("dark", 4).save(tmp_path / "d.png")
    g, r, c, d = (I.compute(tmp_path / f"{k}.png") for k in "grcd")
    assert g["sat"] < I.NEAR_MONO and not g["coloured"] and g["hue"] is None
    assert r["coloured"] and r["hue"] == "red" and r["red_share"] > 0.8 and r["accent_hex"].startswith("#")
    assert c["coloured"] and c["sat"] > 0.5
    assert d["ground_lum"] < I.DARK and d["dark_hex"] and d["light_hex"] is None
    assert 0 <= g["quiet"] <= 1 and 0 < g["mass_x"] < 1 and len(g["thirds_v"]) == 3


@pytest.fixture
def tapped(tmp_path, monkeypatch):
    """a pool where the user likes restrained (grey/dark/a few red-accent) images and passes colourful/texty ones"""
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    S.write_images(tmp_path / "refs", {"grey": 24, "dark": 8, "red": 6, "colour": 18, "stripes": 10, "blue": 6})
    add_dir(PoolWriter(p), tmp_path / "refs")
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    items = load_pool(p)
    for iid, it in items.items():
        kind = it["title"].split("-")[0]
        like = kind in ("grey", "dark", "red")
        if kind == "grey" and it["title"].endswith(("020", "021", "022", "023")):
            continue                                      # leave a few unseen for the board
        append_jsonl(taps_path(p), {"eid": new_eid(), "t": "2026-10-01T00:00:00", "item": iid,
                                    "action": "like" if like else "pass", "kind": "human", "dwell_ms": 1000 + len(iid),
                                    "why": "cold", "score": None})
    return p, fe, items


def test_tokens_measure_restraint_but_never_pick_the_accent(tapped):
    p, fe, items = tapped
    t = T.build_tokens(p, embedder=fe)
    pal = t["palette"]
    assert pal["restraint"] == "mono+1" and pal["accent"] is None and pal["accent_source"] == "ask-owner"
    assert pal["footage_grade"] == "native"
    assert pal["near_mono_share"]["likes"] > pal["near_mono_share"]["passes"]
    assert pal["coloured_share"]["p"] < 0.05
    assert pal["accent_candidates"] == []                # < 20 coloured likes: candidates need evidence
    ro = pal["red_orange"]
    assert ro["red_dominant_overall"]["likes"] > ro["red_dominant_overall"]["passes"] and ro["red_share_of_colour"]["likes"] > 0.5
    red = next(h for h in pal["hues"] if h["hue"] == "red")
    assert red["likes"] == 6 and red["observed_hex"]
    q = [x["id"] for x in t["open_questions"]]
    assert q[:5] == ["accent", "footage_grade", "faces", "texture", "style_frame"] and len(q) <= 8
    assert t["texture"]["apply"] is None and t["texture"]["status"] == "ask-owner"
    assert any(r["phrase"] == "colorful" for r in t["words"]["passed"])
    assert t["modes"] and all(m["likes"] >= 8 for m in t["modes"])
    assert t["references"]["top_liked"] and t["type"]["status"] == "not measured"
    assert t["look_suggestion"]["look.accent"] is None and t["look_suggestion"]["look.mode"] == "native"
    saved = json.loads((p / "taste" / "taste-tokens.json").read_text(encoding="utf-8"))
    n_likes = sum(1 for it in items.values() if it["title"].split("-")[0] in ("grey", "dark", "red")) - 4
    assert saved["version"] == 1 and saved["evidence"]["likes"] == n_likes
    md = (p / "taste" / "look-bible.md").read_text(encoding="utf-8")
    assert "your call" in md and "native" in md and "## Questions" in md


def test_tokens_need_taps(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path)
    with pytest.raises(SlopError, match="not enough taps"):
        T.build_tokens(p, words=False)


def test_labels_last_answer_and_pairs():
    ev = [{"item": "a", "action": "like"}, {"item": "a", "action": "pass", "why": "repeat"},
          {"a": "b", "b": "c", "winner": "b"}, {"a": "d", "b": "e", "winner": "tie"}]
    lab, _ = T.labels(ev)
    assert lab == {"a": 0.0, "c": 1.0, "b": 0.0}


def test_board_excludes_passes_and_refs_are_text_free(tapped):
    p, fe, items = tapped
    r = T.board(p, "a red accent; red label", n=8, n_refs=6, embedder=fe)
    b = json.loads(Path(r["board_json"]).read_text(encoding="utf-8"))
    refs = json.loads(Path(r["refs_json"]).read_text(encoding="utf-8"))
    title = lambda i: items[i]["title"].split("-")[0]
    assert b["items"] and title(b["items"][0]["id"]) == "red"           # the query wins…
    passed = {i for i, it in items.items() if title(i) in ("colour", "stripes", "blue")}
    assert not any(x["id"] in passed for x in b["items"])               # …passes never appear
    cut = refs["text_free"]["cutoff"]
    assert all(x["text_score"] < cut for x in refs["items"])          # (the crude fake model may leave none)
    assert refs["text_free"]["score"] == "paired-probe" and refs["text_free"]["backgrounds"] >= 24
    assert not any(title(x["id"]) == "stripes" for x in refs["items"])
    assert Path(r["board"]).exists() and len(list(Path(r["refs_dir"]).glob("*.jpg"))) == len(refs["items"])
    # with an explicit cutoff at the pool median: refs exist, stay under it, and never include passes
    from slop.taste import textfree as TF
    from slop.taste.embed import load_store
    ids, X, meta = load_store(p)
    sc, _ = TF.assess(p, ids, X / np.linalg.norm(X, axis=1, keepdims=True), items, meta, embedder=fe)
    med = float(np.median(sc))
    r2 = T.board(p, "a red accent; red label", n=8, n_refs=6, embedder=fe, text_max=med)
    refs2 = json.loads(Path(r2["refs_json"]).read_text(encoding="utf-8"))
    assert refs2["items"] and all(x["text_score"] < med for x in refs2["items"])
    assert not any(x["id"] in passed or title(x["id"]) == "stripes" for x in refs2["items"])
    assert refs2["text_free"]["method"].startswith("--text-max (absolute")


def test_text_free_scores_flag_texty_images(tapped):
    p, fe, items = tapped
    from slop.taste.embed import load_store
    ids, X, meta = load_store(p)
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    s = T.text_free_scores(X, meta, embedder=fe)
    stripes = [k for k, i in enumerate(ids) if items[i]["title"].startswith("stripes")]
    grey = [k for k, i in enumerate(ids) if items[i]["title"].startswith("grey")]
    assert s[stripes].min() > s[grey].max()


# ---------------------------------------------------------------- text-free refs on rendered lettering

def lettered(kind: str, seed: int):
    """review set: blurred grounds + shapes, with rendered headlines (Space Grotesk 64 px), micro-text blocks
    (IBM Plex Mono 18 px) or no lettering — a different generator seed range from the calibration probes"""
    from PIL import ImageDraw
    from slop.taste import synth as Y
    rng = np.random.default_rng(500 + seed)
    size = (1024, 640)
    cols = [Y.hsv(rng.random(), rng.uniform(0, .6), rng.uniform(.15, .9)) for _ in range(4)]
    im = Y.ground_blur(rng, size, cols)
    d = ImageDraw.Draw(im)
    Y.shapes(d, rng, size, cols)
    ink = Y.ink_for(tuple(int(x) for x in np.asarray(im).reshape(-1, 3).mean(0)))
    if kind == "headline":
        Y.text_block(d, rng, (60, 200), [Y.headline(rng, 2), Y.headline(rng, 2)], "grotesk", 64, ink)
    elif kind == "micro":
        Y.text_block(d, rng, (60, 120), [Y.micro_line(rng) for _ in range(8)], "mono", 18, ink)
    return im


def _lettered_project(tmp_path, monkeypatch, n=18, embedder=None):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path, "letters")
    d = tmp_path / "letters-refs"
    d.mkdir()
    for kind in ("headline", "micro", "none"):
        for k in range(n):
            lettered(kind, k).save(d / f"{kind}-{k:03d}.png")
    add_dir(PoolWriter(p), d)
    if embedder is not None:
        embed_pool(p, embedder=embedder, log=lambda m: None)
    else:
        embed_pool(p, provider="local", log=lambda m: None)
    return p


def _check_text_free(p, embedder, min_kept: float, need_refs: bool = True):
    from slop.taste import textfree as TF
    from slop.taste.embed import load_store
    items = load_pool(p)
    r = T.board(p, "a quiet field; soft shapes", n=12, n_refs=12, embedder=embedder)
    refs = json.loads(Path(r["refs_json"]).read_text(encoding="utf-8"))
    tf = refs["text_free"]
    assert {"cutoff", "method", "score", "clean_share"} <= set(tf)
    ids, X, meta = load_store(p)
    X = X / np.linalg.norm(X, axis=1, keepdims=True)
    sc, again = TF.assess(p, ids, X, items, meta, embedder=embedder)        # cached copies: the same probe
    assert again["cutoff"] == tf["cutoff"] and again.get("embedded_now", 0) == 0
    kind = [items[i]["title"].split("-")[0] for i in ids]
    let = [s_ for s_, k in zip(sc, kind) if k != "none"]
    clean = [s_ for s_, k in zip(sc, kind) if k == "none"]
    excluded = np.mean([s_ >= tf["cutoff"] for s_ in let])
    kept = np.mean([s_ < tf["cutoff"] for s_ in clean])
    assert excluded >= 0.9, (excluded, tf)                  # the review: 86-95 % of lettered images passed "< 0"
    assert kept >= min_kept, (kept, tf)
    if need_refs or refs["items"]:
        assert refs["items"] and np.mean([items[x["id"]]["title"].startswith("none") for x in refs["items"]]) >= 0.9
    return tf


def test_text_free_cutoff_excludes_rendered_lettering(tmp_path, monkeypatch):
    fe = S.FakeEmbedder()
    p = _lettered_project(tmp_path, monkeypatch, embedder=fe)
    # the fake model sees lettering only crudely: it must still exclude >= 90 % of it (keeping clean images is
    # checked with the real model below, opt-in)
    tf = _check_text_free(p, fe, min_kept=0.0, need_refs=False)
    # too few images for the paired probe (it needs 24 clean backgrounds) -> the zero-shot policy (stricter of
    # the calibration on rendered probes and the pool's least-text third)
    assert tf["score"] == "zero-shot" and "too few" in tf["method"]
    assert tf["cutoff"] == min(tf["calibrated_cutoff"], tf["pool_cutoff"])
    # an absolute --text-max replaces the calibration; a broken probe path falls back to the stricter pool share
    r = T.board(p, "a quiet field", n=6, n_refs=4, embedder=fe, text_max=-5.0)
    assert r["refs"] == 0 and r["text_free"]["method"].startswith("--text-max")


def test_text_free_falls_back_to_a_stricter_pool_share(tmp_path, monkeypatch):
    from slop.taste import textfree as TF
    fe = S.FakeEmbedder()
    p = _lettered_project(tmp_path, monkeypatch, n=6, embedder=fe)
    from slop.taste.embed import load_store
    ids, X, meta = load_store(p)

    class TextOnly:
        def embed_texts(self, texts):
            return fe.embed_texts(texts)
    sc = np.linspace(-1, 1, 30)
    c = TF.cutoff(sc, {**meta, "tag": "other-tag"}, embedder=TextOnly())
    assert c["method"].startswith("pool least-text 20%") and c["clean_share"] == pytest.approx(0.2, abs=0.04)


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("SLOP_TEST_SIGLIP"), reason="set SLOP_TEST_SIGLIP=1 to run SigLIP 2 base (~1.5 GB)")
def test_text_free_cutoff_real_siglip(tmp_path, monkeypatch):
    from slop.taste.embed import LocalSiglip
    emb = LocalSiglip()
    p = _lettered_project(tmp_path, monkeypatch, n=18, embedder=emb)
    tf = _check_text_free(p, emb, min_kept=0.5)
    # the blurred synthetic grounds are near-duplicates of each other (a handful survive the pool's dedupe): too few
    # backgrounds for the per-pool probe, so this pins the zero-shot fallback; the probe on real images is
    # test_taste_textfree.py::test_paired_probe_on_real_text_free_images (opt-in)
    assert tf["score"] == "zero-shot" and tf["probe"]["lettered"]["n"] == 24


# ---------------------------------------------------------------- restraint classes, anti-sources, p formatting

def hues_image(hues: list[float], seed: int):
    from PIL import Image
    from slop.taste import synth as Y
    rng = np.random.default_rng(seed)
    w, h = 640, 480
    arr = np.zeros((h, w, 3))
    cuts = np.sort(rng.uniform(0.1, 0.9, len(hues) - 1)) if len(hues) > 1 else np.array([])
    edges = [0, *[int(c * w) for c in cuts], w]                  # random splits: distinct images (no near-dup)
    vertical = rng.random() < 0.5
    for k, hu in enumerate(rng.permutation(hues)):
        c = Y.hsv(hu + rng.uniform(-0.01, 0.01), 0.85, 0.9)
        if vertical:
            arr[:, edges[k]:edges[k + 1]] = c
        else:
            arr[edges[k] * h // w:edges[k + 1] * h // w, :] = c
    x0, y0 = int(rng.integers(0, w - 200)), int(rng.integers(0, h - 150))
    arr[y0:y0 + int(rng.integers(40, 150)), x0:x0 + int(rng.integers(60, 200))] = 20   # a dark block: distinct layouts
    return Image.fromarray(np.clip(arr + rng.normal(0, 4, arr.shape), 0, 255).astype("uint8"))


def test_limited_restraint_and_dir_anti_source(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path, "hues")
    for k in range(14):
        (tmp_path / "refs" / "two").mkdir(parents=True, exist_ok=True)
        (tmp_path / "refs" / "many").mkdir(parents=True, exist_ok=True)
        hues_image([0.08, 0.5], k).save(tmp_path / "refs" / "two" / f"two-{k:03d}.png")          # orange + cyan
        hues_image([0.0, 0.17, 0.33, 0.6, 0.83], 100 + k).save(tmp_path / "refs" / "many" / f"many-{k:03d}.png")
    add_dir(PoolWriter(p), tmp_path / "refs")
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    for iid, it in load_pool(p).items():
        append_jsonl(taps_path(p), {"eid": new_eid(), "t": "2026-10-01T00:00:00", "item": iid,
                                    "action": "like" if it["title"].startswith("two") else "pass", "kind": "human",
                                    "dwell_ms": 900, "why": "cold", "score": None})
    t = T.build_tokens(p, embedder=fe, words=False)
    pal = t["palette"]
    assert pal["restraint"] == "limited" and pal["few_colour_share"]["likes"] >= 0.75
    assert pal["few_colour_share"]["passes"] < 0.5
    assert [a["source"] for a in t["anti_sources"]] == ["dir:refs/many"]
    assert any(q["id"] == "avoid:dir:refs/many" for q in t["open_questions"])
    md = (p / "taste" / "look-bible.md").read_text(encoding="utf-8")
    assert "p = 0.0 " not in md and "p = 0.0)" not in md


def test_colourful_restraint_and_p_formatting(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    p = S.make_project(tmp_path, "loud")
    d = tmp_path / "loud-refs"
    d.mkdir()
    for k in range(12):
        hues_image([0.0, 0.17, 0.33, 0.6, 0.83], k).save(d / f"many-{k:03d}.png")
        hues_image([0.6], 50 + k).save(d / f"one-{k:03d}.png")
    add_dir(PoolWriter(p), d)
    fe = S.FakeEmbedder()
    embed_pool(p, embedder=fe, log=lambda m: None)
    for iid, it in load_pool(p).items():
        append_jsonl(taps_path(p), {"eid": new_eid(), "t": "2026-10-01T00:00:00", "item": iid,
                                    "action": "like" if it["title"].startswith("many") else "pass", "kind": "human",
                                    "dwell_ms": 900, "why": "cold", "score": None})
    assert T.build_tokens(p, embedder=fe, words=False)["palette"]["restraint"] == "colourful"
    assert T.ptxt(3e-9) == "p < 0.0001" and T.ptxt(0.0123) == "p = 0.0123"
    assert T.pnum(1.23456e-9) == pytest.approx(1.23e-9) and T.pnum(0.04567) == 0.0457


def test_text_cutoff_is_the_stricter_of_calibration_and_pool_third(monkeypatch):
    from slop.taste import textfree as TF
    sc = np.linspace(-0.1, 0.05, 31)                               # pool scores; third at -0.05
    monkeypatch.setattr(TF, "calibrate", lambda *a, **k: {"cutoff": -0.03, "lettered": {}, "clean": {},
                                                          "headline_median": 0, "micro_median": 0})
    c = TF.cutoff(sc, {"tag": "t"})
    assert c["cutoff"] == pytest.approx(-0.05) and c["pool_cutoff"] == pytest.approx(-0.05)
    assert c["calibrated_cutoff"] == -0.03 and c["clean_share"] == pytest.approx(10 / 31, abs=0.01)
    monkeypatch.setattr(TF, "calibrate", lambda *a, **k: {"cutoff": -0.08, "lettered": {}, "clean": {},
                                                          "headline_median": 0, "micro_median": 0})
    assert TF.cutoff(sc, {"tag": "t"})["cutoff"] == pytest.approx(-0.08)   # a typography-heavy pool: calibration rules
