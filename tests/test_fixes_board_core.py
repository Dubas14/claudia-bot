"""Fixes track, board + core side (offline): board set / fill refuse the prompt field of the generator the board does
not use (naming the right flag) unless --switch-generator; `plates ingest --url --credits` ledgers Higgsfield stills
once; `slop project set KEY VALUE` writes validated dotted keys and logs them; relative input paths fall back to the
project folder (board fill, plates ingest, song ingest, lyrics lint FILE, taste pool add --dir, render check --video);
doctor says cloudflared is REQUIRED for OpenRouter sung clips."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))
import board_synth as synth  # noqa: E402

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import cli, ledger  # noqa: E402
from slop.board import draft, plates, shotedit  # noqa: E402
from slop.config import SlopError  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "slophome"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)                                          # never inside the project


def _run(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--json", *argv])
    return code, json.loads(buf.getvalue().strip().splitlines()[-1])


def _board(tmp_path, tier: str, name: str = "synth"):
    p = synth.make_project(tmp_path, name=name, tier=tier)
    draft.run(p)
    return p, synth.load(p, "board/shots.json")


PROMPT = "medium shot of {lead}, standing in the left third of a glass lobby at night, the right third empty"


# ------------------------------------------------------------------------------------------------ one board, one generator
def test_quick_board_refuses_mj_prompt_and_names_the_right_flag(tmp_path):
    p, S = _board(tmp_path, "quick")
    sid = next(s["id"] for s in S["shots"] if "img_prompt" in s)
    before = (p / "board/shots.json").read_bytes()
    code, out = _run("-p", "synth", "board", "set", sid, "--mj-prompt", PROMPT)
    assert code == 1 and "--img-prompt" in out["error"] and "--switch-generator" in out["error"], out
    assert "API images" in out["error"] and "slop -p synth project set board.generator mj" in out["error"]
    assert (p / "board/shots.json").read_bytes() == before                  # nothing was changed
    code, out = _run("-p", "synth", "board", "set", sid, "--img-prompt", PROMPT)
    assert code == 0 and synth.load(p, "board/shots.json")["shots"][[s["id"] for s in S["shots"]].index(sid)]["img_prompt"] == PROMPT
    # on purpose: --switch-generator makes this one plate a Midjourney plate (its img_prompt goes)
    code, out = _run("-p", "synth", "board", "set", sid, "--mj-prompt", PROMPT, "--switch-generator")
    sh = next(s for s in synth.load(p, "board/shots.json")["shots"] if s["id"] == sid)
    assert code == 0 and sh["mj_prompt"] == PROMPT and "img_prompt" not in sh, out
    # that shot is now off the board's generator: editing its own mj_prompt only warns; the way back is named plainly
    code, out = _run("-p", "synth", "board", "set", sid, "--mj-prompt", PROMPT + ", dusk")
    assert code == 0 and any("stays a Midjourney plate on an API-images board" in w for w in out["warnings"]), out
    code, out = _run("-p", "synth", "board", "set", sid, "--img-prompt", PROMPT)
    assert code == 1 and f"{sid} is a Midjourney plate" in out["error"] and "--switch-generator" in out["error"], out
    assert f"slop -p synth board set {sid} --img-prompt" in out["error"] and "write --mj-prompt" not in out["error"]
    code, out = _run("-p", "synth", "board", "set", sid, "--img-prompt", PROMPT, "--switch-generator")
    sh = next(s for s in synth.load(p, "board/shots.json")["shots"] if s["id"] == sid)
    assert code == 0 and sh["img_prompt"] == PROMPT and "mj_prompt" not in sh, out


def test_a_mixed_quick_board_follows_the_tier(tmp_path):
    p, S = _board(tmp_path, "quick")
    ids = [s["id"] for s in S["shots"]]
    with_img = [s["id"] for s in S["shots"] if "img_prompt" in s]
    mixed, bare = with_img[1], next((s["id"] for s in S["shots"] if "img_prompt" not in s and "mj_prompt" not in s), None)
    S["shots"][ids.index(mixed)]["mj_prompt"] = S["shots"][ids.index(mixed)].pop("img_prompt")  # the old silent switch
    synth.write_json(p / "board/shots.json", S)
    code, out = _run("-p", "synth", "board", "set", mixed, "--img-prompt", PROMPT)   # the right fix back to API images
    assert code == 1 and f"{mixed} is a Midjourney plate (it has an mj_prompt) on an API-images board" in out["error"]
    assert "quick tier's default; the board mixes both" in out["error"] and "--switch-generator" in out["error"]
    assert "write --mj-prompt" not in out["error"] and "a API" not in out["error"], out
    assert _run("-p", "synth", "board", "set", mixed, "--img-prompt", PROMPT, "--switch-generator")[0] == 0
    S = synth.load(p, "board/shots.json")
    S["shots"][ids.index(mixed)]["mj_prompt"] = S["shots"][ids.index(mixed)].pop("img_prompt")
    synth.write_json(p / "board/shots.json", S)
    for sid in [x for x in (bare, with_img[0]) if x]:                        # never --mj-prompt on a Quick board
        code, out = _run("-p", "synth", "board", "set", sid, "--mj-prompt", PROMPT)
        assert code == 1 and "write --img-prompt" in out["error"] and "API images" in out["error"], (sid, out)


def test_studio_board_refuses_img_prompt_and_the_project_setting_switches_the_board(tmp_path):
    p, S = _board(tmp_path, "studio")
    sid = next(s["id"] for s in S["shots"] if "mj_prompt" in s)
    code, out = _run("-p", "synth", "board", "set", sid, "--img-prompt", PROMPT)
    assert code == 1 and "--mj-prompt" in out["error"] and "Midjourney" in out["error"]
    assert _run("-p", "synth", "project", "set", "board.generator", "api")[0] == 0
    code, out = _run("-p", "synth", "board", "set", sid, "--img-prompt", PROMPT)
    sh = next(s for s in synth.load(p, "board/shots.json")["shots"] if s["id"] == sid)
    assert code == 0 and sh["img_prompt"] == PROMPT and "mj_prompt" not in sh, out
    code, out = _run("-p", "synth", "board", "set", sid, "--mj-prompt", PROMPT)
    assert code == 1 and "project.json board.generator" in out["error"]


def test_fill_refuses_the_other_generator_unless_switched_and_reads_project_relative_files(tmp_path):
    p, S = _board(tmp_path, "quick")
    sid = next(s["id"] for s in S["shots"] if "img_prompt" in s)
    (p / "board/fill.tsv").write_text(f"id\tmj_prompt\n{sid}\t{PROMPT}\n", encoding="utf-8")
    code, out = _run("-p", "synth", "board", "fill", "board/fill.tsv", "--check")      # relative to the project
    assert code == 1 and "--img-prompt" in out["error"] and "nothing was changed" in out["error"], out
    code, out = _run("-p", "synth", "board", "fill", "board/fill.tsv", "--check", "--switch-generator")
    assert code == 0 and out["next"].endswith("board fill board/fill.tsv --switch-generator"), out
    code, out = _run("-p", "synth", "board", "fill", "board/nope.tsv")
    assert code == 1 and "not found in the current folder" in out["error"] and "project folder" in out["error"]


def test_generic_prompt_field_follows_the_board(tmp_path):
    p, S = _board(tmp_path, "studio")
    sid = next(s["id"] for s in S["shots"] if "mj_prompt" in s)
    r = shotedit.cmd_set(p, sid, {"prompt": PROMPT})
    sh = next(s for s in synth.load(p, "board/shots.json")["shots"] if s["id"] == sid)
    assert sh["mj_prompt"] == PROMPT and r["changed"][sid] == ["mj_prompt"]
    with pytest.raises(SlopError, match="--mj-prompt"):
        shotedit.cmd_set(p, sid, {"img_prompt": PROMPT})


# ------------------------------------------------------------------------------------------------ plates ingest --credits
def test_ingest_url_ledgers_higgsfield_stills_once(tmp_path, monkeypatch):
    p, S = _board(tmp_path, "quick")
    S = synth.fill_todos(S)
    synth.write_json(p / "board/shots.json", S)
    key = S["shots"][0]["plate"]
    imgs = [synth.make_image(tmp_path / f"src{k}.png", 320, 180, seed=k) for k in (1, 2)]

    def fake(url, dest, timeout=60.0):
        dest.write_bytes(imgs[0 if url.endswith("a.png") else 1].read_bytes())
        return dest, "image/png"
    monkeypatch.setattr(plates, "_download", fake)
    u = "https://d1.cloudfront.example/r/a.png?Signature=SECRET"
    job = "0f8fad5b-d9cb-469f-a165-70867728950e"
    code, out = _run("-p", "synth", "plates", "ingest", "--url", u, "--plate", key, "--credits", "4", "--job-id", job,
                     "--model", "nano_banana_2")
    assert code == 0 and out["ledgered"] and "recorded 4 Higgsfield credits" in out["text"], out
    rows = [r for r in ledger.rows(p) if r["kind"] == "image"]
    assert len(rows) == 1 and rows[0]["provider"] == "higgsfield" and rows[0]["credits"] == 4
    assert rows[0]["request_id"] == job and rows[0]["model"] == "nano_banana_2" and "SECRET" not in json.dumps(rows)
    assert ledger.spent_credits(p) == 4
    code, out = _run("-p", "synth", "plates", "ingest", "--url", u, "--plate", key, "--credits", "4", "--job-id", job)
    assert code == 0 and out["ledgered"] is False and "already recorded" in out["text"]
    assert len([r for r in ledger.rows(p) if r["kind"] == "image"]) == 1
    assert rows[0]["units"]["usd_equiv"] == round(4 * 0.0526, 2)
    u2 = "https://d1.cloudfront.example/r/b.png"
    assert _run("-p", "synth", "plates", "ingest", "--url", u2, "--plate", key, "--credits", "2")[1]["ledgered"]
    assert _run("-p", "synth", "plates", "ingest", "--url", u2, "--plate", key, "--credits", "2")[1]["ledgered"] is False
    # the same URLs again, now with their job id: still the same generation, never ledgered twice
    code, out = _run("-p", "synth", "plates", "ingest", "--url", u2, "--plate", key, "--credits", "2", "--job-id",
                     "7c9e6679-7425-40de-944b-e07fc1f90ae7")
    assert code == 0 and out["ledgered"] is False and "already recorded" in out["text"], out
    assert ledger.spent_credits(p) == 6
    code, out = _run("-p", "synth", "plates", "ingest", str(imgs[0]), "--plate", key, "--credits", "2")
    assert code == 1 and "go with --url" in out["error"]


def test_plates_ingest_reads_a_project_relative_file(tmp_path):
    p, S = _board(tmp_path, "quick")
    key = S["shots"][0]["plate"]
    synth.make_image(p / "downloads" / "one.png", 320, 180, seed=3)
    code, out = _run("-p", "synth", "plates", "ingest", "downloads/one.png", "--plate", key)
    assert code == 0 and out["added"] == {key: [1]}, out
    code, out = _run("-p", "synth", "plates", "ingest", "downloads/none.png", "--plate", key)
    assert code == 1 and "not found in the current folder" in out["error"]


# ------------------------------------------------------------------------------------------------ project set
def test_project_set_validates_writes_and_logs(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    code, out = _run("-p", "synth", "project", "set", "look.accent", "none")
    assert code == 0 and out["value"] is None and out["changed"] and "no accent" in out["text"], out
    assert synth.load(p, "project.json")["look"]["accent"] is None
    code, out = _run("-p", "synth", "project", "set", "look.accent", "#3fa7d6")
    assert code == 0 and synth.load(p, "project.json")["look"]["accent"] == "#3FA7D6"
    code, out = _run("-p", "synth", "project", "set", "look.accent", "#3FA7D6")
    assert code == 0 and out["changed"] is False and "no change" in out["text"]
    for key, val in (("budget.openrouter_usd", "8"), ("budget.higgsfield_credits", "40"), ("tier", "studio"),
                     ("models.image", "openai/gpt-image-2"), ("lead.pronoun", "he"), ("look.mode", "print"),
                     ("board.lead_min", "60"), ("size", "1080x1920"), ("look.medium", "cel")):
        code, out = _run("-p", "synth", "project", "set", key, val)
        assert code == 0, (key, out)
    pj = synth.load(p, "project.json")
    assert pj["budget"]["openrouter_usd"] == 8 and pj["budget"]["higgsfield_credits"] == 40 and pj["tier"] == "studio"
    assert pj["lead"]["pronoun"] == "He" and pj["look"]["mode"] == "print" and pj["board"]["lead_min"] == 0.6
    assert pj["size"] == [1080, 1920] and pj["look"]["medium"] == "cel"
    dec = (p / "DECISIONS.md").read_text(encoding="utf-8")
    assert 'project.json look.accent = null (was "#D97757")' in dec and "project.json tier = \"studio\"" in dec
    for key, val, msg in (("look.accent", "orange", "hex colour"), ("budget.openrouter_usd", "-3", "between"),
                          ("budget.openrouter_usd", "lots", "a number"), ("tier", "pro", "tier must be"),
                          ("models.video", "seedance", "model id"), ("lead.canon", "TODO write it", "placeholder"),
                          ("gates.v1_approved", "true", "slop gate"), ("budget.frozen", "x", "spend --freeze"),
                          ("name", "other", "folder name"), ("look.fonts.lyric", "Comic Sans", "OFL"),
                          ("colour", "red", "unknown project.json key"), ("lead", "x", "name one lead key"),
                          ("board.generator", "dalle", "api")):
        before = (p / "project.json").read_bytes()
        code, out = _run("-p", "synth", "project", "set", key, val)
        assert code == 1 and msg in out["error"], (key, out)
        assert (p / "project.json").read_bytes() == before
    code, out = _run("-p", "synth", "project", "show", "budget")
    assert code == 0 and out["value"]["openrouter_usd"] == 8
    # validation gaps: #abc is stored as #AABBCC, fps is a whole number, unknown board/audio keys are refused
    assert _run("-p", "synth", "project", "set", "look.accent", "#abc")[0] == 0
    assert synth.load(p, "project.json")["look"]["accent"] == "#AABBCC"
    for key, val, msg in (("fps", "29.97", "whole number"), ("fps", "thirty", "whole number"),
                          ("board.anything", "lol", "not a board key"), ("audio.anything", "1", "not an audio key")):
        before = (p / "project.json").read_bytes()
        code, out = _run("-p", "synth", "project", "set", key, val)
        assert code == 1 and msg in out["error"], (key, out)
        assert (p / "project.json").read_bytes() == before
    assert _run("-p", "synth", "project", "set", "fps", "30")[0] == 0 and synth.load(p, "project.json")["fps"] == 30
    assert _run("-p", "synth", "project", "set", "board.max_clips", "20")[0] == 0
    code, out = _run("-p", "synth", "project", "show", "look.nothing")
    assert code == 1 and "no look.nothing" in out["error"]


# ------------------------------------------------------------------------------------------------ relative input paths
def test_lyrics_lint_reads_a_project_relative_file(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    (p / "lyrics").mkdir(exist_ok=True)
    (p / "lyrics" / "draft.md").write_text("[Chorus: sung]\nFeel it coming fast\nEscape velocity\n", encoding="utf-8")
    code, out = _run("-p", "synth", "lyrics", "lint", "lyrics/draft.md")
    assert code == 0 and Path(out["file"]) == p / "lyrics" / "draft.md", out
    code, out = _run("-p", "synth", "lyrics", "lint", "lyrics/missing.md")
    assert code == 1 and "not found in the current folder" in out["error"]


def test_taste_pool_add_dir_is_project_relative(tmp_path):
    p = synth.make_project(tmp_path, tier="quick")
    for k in range(3):
        synth.make_image(p / "refs" / f"r{k}.png", 640, 360, seed=11 * k + 1, color=(60 * k, 90, 160 - 40 * k),
                         accent=bool(k % 2))
    code, out = _run("-p", "synth", "taste", "pool", "add", "--dir", "refs")
    assert code == 0 and out["added"] >= 1, out
    code, out = _run("-p", "synth", "taste", "pool", "add", "--dir", "no-such-dir")
    assert code == 1 and "not found in the current folder" in out["error"]


@needs_ffmpeg
def test_song_ingest_and_render_check_video_are_project_relative(tmp_path):
    import numpy as np
    p = synth.make_project(tmp_path, tier="quick")
    t = np.arange(int(3 * H.SR)) / H.SR
    H.write_wav(p / "downloads" / "song.wav", (.2 * np.sin(2 * np.pi * 220 * t)).astype("float32"), channels=2)
    code, out = _run("-p", "synth", "song", "ingest", "downloads/song.wav")
    assert code == 0 and out["status"] == "ingested" and (p / "audio" / "song.wav").is_file(), out
    code, out = _run("-p", "synth", "song", "ingest", "downloads/other.wav")
    assert code == 1 and "not found in the current folder" in out["error"]
    H.make_mp4(p / "out" / "cut.mp4", None, duration=1)
    code, out = _run("-p", "synth", "render", "check", "--video", "out/cut.mp4", "--skip-history")
    assert "flash" in out and "missing" not in json.dumps(out.get("flash")), out
    code, out = _run("-p", "synth", "render", "check", "--video", "out/none.mp4", "--skip-history")
    assert out["flash"]["error"].startswith("no video at") and "none.mp4" in out["flash"]["error"]


def test_input_path_helper(tmp_path, monkeypatch):
    from slop.util import input_path, not_found
    proj = tmp_path / "p"
    (proj / "a").mkdir(parents=True)
    (proj / "a" / "f.txt").write_text("x")
    assert input_path(proj, "a/f.txt") == proj / "a" / "f.txt"           # cwd is elsewhere: the project's file
    (Path.cwd() / "a").mkdir()
    (Path.cwd() / "a" / "f.txt").write_text("y")
    assert input_path(proj, "a/f.txt") == Path("a/f.txt")               # the current folder wins
    assert input_path(None, "zz.txt") == Path("zz.txt") and input_path(proj, None) is None
    assert "or the project folder (" in not_found(proj, "zz.txt") and "or the project folder (" not in not_found(None, "zz")


# ------------------------------------------------------------------------------------------------ doctor
def test_doctor_says_cloudflared_is_required(monkeypatch):
    from slop import doctor, util
    monkeypatch.setattr(util, "find_tool", lambda name: None)
    c = doctor.check_cloudflared()
    assert c["status"] == "warn" and "REQUIRED for OpenRouter sung clips" in c["detail"] and "tap app" in c["detail"]
    assert "setup.sh --cloudflared" in c["fix"] and "only needed" not in c["detail"]


def test_project_set_never_loosens_a_money_guard_without_the_owner(tmp_path):
    p = synth.make_project(tmp_path, tier="studio")               # openrouter_usd 40, higgsfield_credits 300, confirm 2
    for key, val in (("budget.openrouter_usd", "9999"), ("budget.openrouter_usd", "0"),
                     ("budget.confirm_over_usd", "10000"), ("budget.higgsfield_credits", "301"),
                     ("budget.motion_s", "61")):
        before = (p / "project.json").read_bytes()
        code, out = _run("-p", "synth", "project", "set", key, val)
        assert code == 1 and "loosens the owner's money guard" in out["error"] and "Ask the owner first" in out["error"]
        assert f"project set {key} {val} --owner-ok --by owner" in out["error"], (key, out)
        assert (p / "project.json").read_bytes() == before
        code, out = _run("-p", "synth", "project", "set", key, val, "--owner-ok")            # --by owner is required too
        assert code == 1 and (p / "project.json").read_bytes() == before
    assert "removes the spend cap" in _run("-p", "synth", "project", "set", "budget.openrouter_usd", "0")[1]["error"]
    # lowering is free; the owner's yes raises it (logged)
    assert _run("-p", "synth", "project", "set", "budget.openrouter_usd", "20")[0] == 0
    assert _run("-p", "synth", "project", "set", "budget.confirm_over_usd", "1")[0] == 0
    code, out = _run("-p", "synth", "project", "set", "budget.openrouter_usd", "60", "--owner-ok", "--by", "owner",
                     "--note", "owner: ok up to 60")
    assert code == 0 and synth.load(p, "project.json")["budget"]["openrouter_usd"] == 60, out
    dec = (p / "DECISIONS.md").read_text(encoding="utf-8")
    assert "budget.openrouter_usd = 60" in dec and "owner: ok up to 60" in dec


def test_project_set_keeps_an_accent_while_the_look_grades(tmp_path):
    p = synth.make_project(tmp_path, tier="studio")
    assert _run("-p", "synth", "project", "set", "look.mode", "clean-grade")[0] == 0
    before = (p / "project.json").read_bytes()
    code, out = _run("-p", "synth", "project", "set", "look.accent", "none")
    assert code == 1 and "needs one" in out["error"] and "project set look.mode native" in out["error"], out
    assert (p / "project.json").read_bytes() == before
    assert _run("-p", "synth", "project", "set", "look.mode", "native")[0] == 0
    assert _run("-p", "synth", "project", "set", "look.accent", "none")[0] == 0
    code, out = _run("-p", "synth", "project", "set", "look.mode", "print")
    assert code == 1 and 'project set look.accent "#D97757"' in out["error"], out
    assert synth.load(p, "project.json")["look"]["mode"] == "native"


def test_status_names_an_unmeasured_finalize(tmp_path):
    from slop import core_cli
    p = synth.make_project(tmp_path, tier="studio")
    (p / "clips").mkdir(exist_ok=True)
    (p / "clips" / "t.mp4").write_bytes(b"x")
    c = {"id": "W01", "kind": "sung", "status": "delivered", "takes": [
        {"n": 1, "status": "delivered", "file": "clips/t.mp4", "sync": {"mode": "copy", "lag_s": .475}},
        {"n": 2, "status": "delivered", "file": "clips/t.mp4", "finalize_of": 1, "needs_sync": True}]}
    st = core_cli._clips_stage(p, "studio", [("W01", c)], None)
    assert not st["done"] and "W01 take 2 (the finalize of take 1" in st["detail"] and "no lag correction" in st["detail"]
    assert st["cmd"].endswith("clip sync W01")
