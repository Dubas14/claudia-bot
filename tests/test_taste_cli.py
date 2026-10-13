"""`slop taste …` end to end through the router (--json), with a fake embedder; plus the scrub check."""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.cli import main  # noqa: E402
from slop.taste import embed as E  # noqa: E402
from slop.taste import fonts as F  # noqa: E402
from slop.taste.feed import Feed  # noqa: E402

PKG = Path(__file__).resolve().parent.parent / "slop" / "taste"
PROFILE_SHA256 = "841486c93b12e81bd9fa1e7a86ce75862d65b62e8963979da438ecfcd5684700"


def run(capsys, *args):
    code = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    p = S.make_project(tmp_path)
    S.write_images(tmp_path / "refs", {"grey": 20, "red": 6, "colour": 14, "stripes": 8})
    fe = S.FakeEmbedder()
    monkeypatch.setattr(E, "make_embedder", lambda *a, **k: fe)
    monkeypatch.setattr(E, "text_embedder_for", lambda *a, **k: fe)
    return p, tmp_path


def test_help_lists_taste(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "taste" in capsys.readouterr().out


def test_full_cli_flow(env, capsys, monkeypatch):
    p, tmp = env
    code, j = run(capsys, "--project", str(p), "taste", "pool", "add", "--dir", str(tmp / "refs"))
    assert code == 0 and j["ok"] and j["added"] >= 45 and "slop taste embed" in j["text"]
    n = j["pool_size"]
    code, j = run(capsys, "--project", str(p), "taste", "fit")
    assert code == 1 and j["ok"] is False and "slop taste embed" in j["error"]
    code, j = run(capsys, "--project", str(p), "taste", "embed")
    assert code == 0 and j["embedded"] == n
    code, j = run(capsys, "--project", str(p), "taste", "pool", "list", "--limit", "2")
    assert j["images"] == n and j["embedded"] == n and len(j["last"]) == 2
    code, j = run(capsys, "--project", str(p), "taste", "meter")
    assert code == 1 and "keep tapping" in j["error"]
    # the user taps (simulated): likes the restrained images
    from slop.taste.pool import load_pool
    items = load_pool(p)
    f = Feed(p, seed=0)
    for iid, it in items.items():          # (the fake embedder's vectors are too alike for the re-post filter)
        f.record_tap({"item": iid, "action": "like" if it["title"].split("-")[0] in ("grey", "red") else "pass"})
    code, j = run(capsys, "--project", str(p), "taste", "fit")
    from slop.taste.store import taste_dir, user_profile_dir   # a new project links to the user profile (profiles)
    assert code == 0 and j["n_unary"] >= 40 and (taste_dir(p) / "model.npz").exists()
    assert taste_dir(p) == user_profile_dir() and not (p / "taste" / "model.npz").exists()
    code, j = run(capsys, "--project", str(p), "taste", "meter", "--reps", "1")
    assert code == 0 and j["accuracy"] > 0.7 and "held-out" in j["text"]
    code, j = run(capsys, "--project", str(p), "taste", "status")
    assert code == 0 and j["running"] is False and j["taps"] >= 44 and j["meter"]["source"] == "cli"
    code, j = run(capsys, "--project", str(p), "taste", "tokens")
    assert code == 0 and j["restraint"] in ("mono+1", "limited") and j["questions"][0]["id"] == "accent"
    code, j = run(capsys, "--project", str(p), "taste", "board", "red label; red accent", "--n", "6", "--refs", "4")
    assert code == 0 and j["items"] > 0 and Path(j["board"]).exists()


def test_fonts_cli(env, capsys, monkeypatch):
    p, tmp = env
    d = tmp / "fonts"
    d.mkdir()
    for fn, fam in [("Geist-Regular.ttf", "Geist"), ("DINish-Bold.ttf", "DINish"), ("ShareTechMono-Regular.ttf", "Share Tech Mono")]:
        S.fake_font(d / fn, fam)
    monkeypatch.setattr(F, "font_dirs", lambda extra=None: [d])
    code, j = run(capsys, "--project", str(p), "taste", "fonts", "--no-serve", "--text", "hold still now", "--seed", "4")
    assert code == 0 and j["cards"] == 6 and j["provisional_frame"] is True and "warning" in j["text"]
    fs = F.FontSession(p)
    for c in fs.sess["cards"]:
        fs.record({"card": c["card"], "winner": "first" if c["card"] % 2 else "second", "layout": "stack"})
    code, j = run(capsys, "--project", str(p), "taste", "fonts", "rank")
    assert code == 0 and j["decisive"] == 6 and "gamma" in j


def test_serve_refuses_an_empty_pool(env, capsys):
    p, tmp = env
    code, j = run(capsys, "--project", str(p), "taste", "serve")
    assert code == 1 and "pool add" in j["error"]


def test_no_project_is_an_actionable_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    monkeypatch.chdir(tmp_path)
    code, j = run(capsys, "taste", "status")
    assert code == 1 and "--project" in j["error"]


def test_scrub_nothing_identifying_ships():
    """No private word (hashed list + scanner: tests/scrublist.py), no /opt path, job id, VPN name or mail handle."""
    import codecs

    import scrublist
    # ROT13 so this file does not spell them
    extra = [re.compile(codecs.decode(p, "rot13"), re.I)
             for p in (r"/bcg/", r"\ognvyarg\o", r"nanobybtlpb", r"tra-ivq-\q{10}-")]
    root = PKG.parents[1]
    files = [f for f in [*PKG.rglob("*"), *root.glob("tests/test_taste*.py"), *root.glob("tests/fixtures/taste/**/*")]
             if f.is_file() and "__pycache__" not in f.parts]
    assert len(files) > 10
    bad = []
    for f in files:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        bad += [f"{f.name}: {h}" for h in scrublist.private_hits(txt, binary=f.suffix in (".jpg", ".png", ".npz"))]
        bad += [f"{f.name}: pattern {i}" for i, p in enumerate(extra) if p.search(txt)]
        if f.suffix in (".py", ".js", ".html", ".css", ".json", ".md"):
            bad += [f"{f.name}: profile code" for tok in set(re.findall(r"[A-Za-z0-9]{5,12}", txt))
                    if hashlib.sha256(tok.encode()).hexdigest() == PROFILE_SHA256]
    assert not bad, bad


def test_json_and_project_flags_work_after_the_subcommand(env, capsys):
    p, tmp = env
    # the review's failing form: the flags repeated / placed after the leaf command
    code = main(["--json", "-p", str(p), "taste", "fit", "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    j = json.loads(out[-1])
    assert code == 1 and j["ok"] is False and "slop taste embed" in j["error"]
    code = main(["taste", "status", "--json", "-p", str(p)])
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and j["running"] is False and j["taps"] == 0
    code = main(["taste", "pool", "list", "--project", str(p), "--json"])
    j = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert code == 0 and j["images"] == 0


def test_pool_add_starter_through_the_cli(env, capsys):
    p, tmp = env
    code, j = run(capsys, "--project", str(p), "taste", "pool", "add", "--starter", "--max", "20")
    assert code == 0 and j["added"] >= 18 and j["starter"]["deck_size"] == 320
    assert "starter deck" in j["text"] and "own references" in j["text"]
    code, j = run(capsys, "--project", str(p), "taste", "pool", "list", "--limit", "0")
    assert j["by_source"] == {"starter": j["images"]} and j["by_kind"] == {"composed": j["images"]}
    code, j = run(capsys, "--project", str(p), "taste", "embed")
    assert code == 0 and j["embedded"] == j["pool"]
    from slop.taste.feed import Feed
    f = Feed(p, seed=0)
    assert len(f.serve_ids) == j["pool"] and f.next([])["cards"]      # composed starter cards are served
