"""slop.taste.profile: one taste profile per user — projects link to it by default, fork, merge, adopt, pinning."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.taste import embed as E  # noqa: E402
from slop.taste import fonts as F  # noqa: E402
from slop.taste import profile as PR  # noqa: E402
from slop.taste.feed import Feed  # noqa: E402
from slop.taste.pool import PoolWriter, add_dir, load_pool  # noqa: E402
from slop.taste.store import (append_jsonl, new_eid, pin_root, read_events, read_link, taps_path, taste_dir,  # noqa: E402
                              user_profile_dir)


def run(capsys, *args):
    code = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    S.write_images(tmp_path / "refs", {"grey": 16, "red": 6, "colour": 14, "stripes": 6})
    fe = S.FakeEmbedder()
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    monkeypatch.setattr(E, "text_embedder_for", lambda *a, **k: fe)
    return tmp_path, fe


def _tap_all(p):
    f = Feed(p, seed=0)
    for iid, it in load_pool(p).items():
        f.record_tap({"item": iid, "action": "like" if it["title"].split("-")[0] in ("grey", "red") else "pass"})
    f.wait_idle()


def test_second_project_starts_with_the_first_projects_taps_and_meter(env, capsys):
    tmp, _ = env
    a, b = S.make_project(tmp, "first-song"), S.make_project(tmp, "second-song")
    code, j = run(capsys, "-p", str(a), "taste", "pool", "add", "--dir", str(tmp / "refs"))
    assert code == 0 and j["added"] >= 40
    assert read_link(a)["profile"] == "user" and taste_dir(a) == user_profile_dir()
    assert not (a / "taste" / "pool").exists()                      # the data lives in the user profile
    run(capsys, "-p", str(a), "taste", "embed")
    _tap_all(a)
    code, j = run(capsys, "-p", str(a), "taste", "meter", "--reps", "1")
    assert code == 0 and j["accuracy"] > 0.7
    # the second project: nothing added, yet it sees the same taste
    code, j = run(capsys, "-p", str(b), "taste", "status")
    assert code == 0 and j["taps"] >= 40 and j["meter"]["accuracy"] == pytest.approx(j["profile"]["meter"]["accuracy"])
    assert j["profile"]["profile"] == "user" and j["profile"]["other_projects"] == ["first-song"]
    assert "taste profile: your user profile" in j["text"] and "first-song" in j["text"]
    code, j = run(capsys, "-p", str(b), "taste", "use")
    assert code == 0 and j["profile"] == "user" and j["changed"] is False and "--profile project" in j["text"]
    # tokens are per project (each project's own taste/ folder), from the shared taps
    code, j = run(capsys, "-p", str(b), "taste", "tokens")
    assert code == 0 and (b / "taste" / "taste-tokens.json").is_file() and not (a / "taste" / "taste-tokens.json").exists()
    t = json.loads((b / "taste" / "taste-tokens.json").read_text(encoding="utf-8"))
    assert t["profile"]["shared"] is True and t["evidence"]["taps"] >= 40


def test_fork_gives_a_project_its_own_copy(env, capsys):
    tmp, _ = env
    a, b = S.make_project(tmp, "one"), S.make_project(tmp, "two")
    run(capsys, "-p", str(a), "taste", "pool", "add", "--dir", str(tmp / "refs"))
    run(capsys, "-p", str(a), "taste", "embed")
    _tap_all(a)
    n_user = len(read_events(taps_path(a)))
    code, j = run(capsys, "-p", str(b), "taste", "use", "--profile", "project", "--fork")
    assert code == 0 and j["changed"] is True and j["profile"] == "project" and j["taps"] == n_user
    assert j["copied"]["images"] == j["images"] and j["copied"]["meter_copied"] is True
    assert taste_dir(b) == b / "taste" and (b / "taste" / "pool" / "pool.jsonl").is_file()
    assert (b / "taste" / "emb" / "vectors.npz").is_file() and len(list((b / "taste" / "pool" / "images").glob("*.jpg"))) == j["images"]
    # B diverges: its taps no longer reach the user profile
    f = Feed(b, seed=1)
    iid = next(iter(load_pool(b)))
    f.record_tap({"item": iid, "action": "like"})
    assert f.wait_idle()                     # its background meter finishes before b is relinked below
    assert len(read_events(taps_path(b))) == n_user + 1 and len(read_events(taps_path(a))) == n_user
    # forking again into a project that holds data is refused (no silent mix)
    run(capsys, "-p", str(b), "taste", "use", "--profile", "user", "--ignore-local")
    code, j = run(capsys, "-p", str(b), "taste", "use", "--profile", "project", "--fork")
    assert code == 1 and "already holds taste data" in j["error"]
    # flags that need --profile
    code, j = run(capsys, "-p", str(b), "taste", "use", "--fork")
    assert code == 1 and "--profile" in j["error"]


def test_an_older_project_keeps_its_own_data_until_merged(env, capsys):
    tmp, fe = env
    old, new = S.make_project(tmp, "old-song"), S.make_project(tmp, "new-song")
    # an older project (before profiles): data written straight into its own taste/ folder, no link
    add_dir(PoolWriter(old), tmp / "refs")
    E.embed_pool(old, embedder=fe, log=lambda m: None)
    _tap_all(old)
    n_old = len(read_events(taps_path(old)))
    n_pool_old = len(load_pool(old))
    assert read_link(old) is None and taste_dir(old) == old / "taste"
    # a newer project fills the user profile
    S.write_images(tmp / "more", {"blue": 8, "dark": 8}, start_seed=500)
    run(capsys, "-p", str(new), "taste", "pool", "add", "--dir", str(tmp / "more"))
    f = Feed(new, seed=0)
    for iid in list(load_pool(new))[:5]:
        f.record_tap({"item": iid, "action": "like"})
    # the CLI keeps the old project's own data (default link = project, with the hint)
    code, j = run(capsys, "-p", str(old), "taste", "status")
    assert code == 0 and read_link(old)["profile"] == "project" and j["taps"] == n_old
    code, j = run(capsys, "-p", str(old), "taste", "use", "--profile", "user")
    assert code == 1 and "--merge" in j["error"] and "--ignore-local" in j["error"]
    assert read_link(old)["profile"] == "project"                    # nothing changed
    code, j = run(capsys, "-p", str(old), "taste", "use", "--profile", "user", "--merge")
    assert code == 0 and j["profile"] == "user" and j["copied"]["taps"] == n_old
    assert len(read_events(taps_path(new))) == n_old + 5 and len(load_pool(new)) == 16 + n_pool_old
    assert "vectors" in j["copied"] and (old / "taste" / "taps.jsonl").is_file()       # the originals stay put
    code, j = run(capsys, "-p", str(old), "taste", "use", "--profile", "user", "--merge")   # idempotent
    assert code == 0 and j["copied"]["taps"] == 0 and j["copied"]["images"] == 0


def test_adopt_into_an_empty_user_profile(env, capsys):
    tmp, fe = env
    p = S.make_project(tmp, "solo")
    add_dir(PoolWriter(p), tmp / "refs")
    E.embed_pool(p, embedder=fe, log=lambda m: None)
    _tap_all(p)
    n = len(read_events(taps_path(p)))
    from slop.taste import model as M  # noqa: F401
    append_jsonl(p / "taste" / "meter.jsonl", {"t": "2026-10-01T00:00:00", "source": "cli", "accuracy": 0.8,
                                               "margin": 0.1, "n": n})
    r = PR.use(p, "user")
    assert r["changed"] is True and "moved this project's taste into your user profile" in r["text"]
    u = user_profile_dir()
    assert len(read_events(u / "taps.jsonl")) == n and (u / "emb" / "vectors.npz").is_file()
    assert (u / "meter.jsonl").is_file() and r["meter"]["accuracy"] == 0.8      # the meter came along
    assert taste_dir(p) == u


def test_pinned_root_ignores_a_link_change(env):
    tmp, _ = env
    p = S.make_project(tmp, "pinned")
    PR.ensure_link(p)
    assert taste_dir(p) == user_profile_dir()
    pin_root(p, user_profile_dir())
    try:
        PR.use(p, "project")
        assert read_link(p)["profile"] == "project" and taste_dir(p) == user_profile_dir()   # the running app's view
    finally:
        pin_root(p, None)
    assert taste_dir(p) == p / "taste"


def test_font_sessions_are_per_project_on_a_shared_profile(env, monkeypatch):
    tmp, _ = env
    d = tmp / "fonts"
    d.mkdir()
    for fn, fam in [("Geist-Regular.ttf", "Geist"), ("DINish-Bold.ttf", "DINish"), ("ShareTechMono-Regular.ttf", "Share Tech Mono")]:
        S.fake_font(d / fn, fam)
    monkeypatch.setattr(F, "font_dirs", lambda extra=None: [d])
    a, b = S.make_project(tmp, "aa"), S.make_project(tmp, "bb")
    PR.ensure_link(a)
    PR.ensure_link(b)
    ra = F.setup(a, texts=["hold still now"], seed=1)
    fs = F.FontSession(a)
    for c in fs.sess["cards"]:
        fs.record({"card": c["card"], "winner": "first", "layout": "row"})
    assert F.setup(a, texts=["hold still now"])["created"] is False          # same project: the same session
    rb = F.setup(b, texts=["a different line"], seed=2)
    assert rb["created"] is True and rb["session"]["project"] == "bb" and rb["session"]["id"] != ra["session"]["id"]
    assert F.rank(b)["picks"] == len(fs.sess["cards"])                      # the first project's picks still count


def test_profile_errors_are_actionable(env, capsys):
    tmp, _ = env
    p = S.make_project(tmp, "lonely")
    code, j = run(capsys, "-p", str(p), "taste", "use", "--profile", "project", "--fork")
    assert code == 1 and "nothing to fork" in j["error"]
    with pytest.raises(SlopError, match="--profile project"):
        PR.use(p, "user", fork=True)
    with pytest.raises(SlopError, match="--profile user"):
        PR.use(p, "project", merge=True)
