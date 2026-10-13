"""Image generation (POST /images) and the image-edit port (chat completions + the keep-everything clause)."""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import imgedit  # noqa: E402

KEY = "sk-or-v1-test-not-a-real-key"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects", audio=False)


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def fake(monkeypatch, routes):
    s = H.FakeSession(routes)
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    return s


def test_image_generation_writes_files_and_ledger(env, monkeypatch, tmp_path):
    ref = H.write_png(tmp_path / "ref.png", (10, 20, 30))
    s = fake(monkeypatch, {("POST", "/images"): H.FakeResp(200, {"created": 1, "data": [
        {"b64_json": H.b64(H.png_bytes((1, 2, 3))), "media_type": "image/png"},
        {"b64_json": H.b64(H.png_bytes((4, 5, 6))), "media_type": "image/png"}], "usage": {"cost": .008}})})
    rc, out = run(env, "gen", "image", "a hall of glowing laptops at night", "--plate", "hall", "--n", "2",
                  "--quality", "low", "--ref", str(ref), "--seed", "7")
    assert rc == 0, out
    body = s.calls[0]["body"]
    assert body["model"] == "openai/gpt-image-2" and body["n"] == 2 and body["seed"] == 7 and body["aspect_ratio"] == "16:9"
    assert body["input_references"][0]["image_url"]["url"].startswith("data:image/png;base64,")
    files = [Path(f) for f in out["files"]]
    assert [f.name for f in files] == ["2.png", "3.png"]                # 1.png (the fixture pick) already exists
    assert json.loads(files[0].with_suffix(".json").read_text())["prompt"].startswith("a hall")
    row = ledger.rows(env)[-1]
    assert row["kind"] == "image" and row["est_usd"] == .008 and row["units"]["real_usd"] == .008


def test_board_command_with_project_relative_prompt_file(env, monkeypatch, tmp_path):
    (env / "plates" / "api").mkdir(parents=True)
    (env / "plates" / "api" / "hall.txt").write_text("a long concrete hall, fog\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir(); monkeypatch.chdir(elsewhere)
    s = fake(monkeypatch, {("POST", "/images"): H.FakeResp(200, {"data": [{"b64_json": H.b64(H.png_bytes()),
                                                                          "media_type": "image/png"}], "usage": {"cost": .004}})})
    rc, out = run(env, "gen", "image", "--plate", "hall", "--prompt-file", "plates/api/hall.txt", "--aspect-ratio", "16:9",
                  "--n", "1")
    assert rc == 0, out
    assert s.calls[0]["body"]["prompt"] == "a long concrete hall, fog"
    assert Path(out["files"][0]).parent == env / "plates" / "cands" / "hall"


def test_image_needs_a_destination_and_respects_budget(env, monkeypatch):
    rc, out = run(env, "gen", "image", "x")
    assert rc == 1 and "--plate" in out["error"]
    proj = json.loads((env / "project.json").read_text()); proj["budget"]["openrouter_usd"] = .001
    (env / "project.json").write_text(json.dumps(proj))
    s = fake(monkeypatch, {})
    rc, out = run(env, "gen", "image", "x", "--plate", "p", "--model", "recraft/recraft-v4.1-flash")
    assert rc == 1 and "budget cap" in out["error"] and not s.calls


def test_declined_image_is_ledgered_not_spent(env, monkeypatch):
    fake(monkeypatch, {("POST", "/images"): H.FakeResp(400, {"error": {"message": "Your request was rejected by the safety system (moderation)"}})})
    rc, out = run(env, "gen", "image", "x", "--plate", "p")
    assert rc == 1 and "moderation" in out["error"]
    assert ledger.rows(env)[-1]["status"] == "declined" and ledger.spent_usd(env) == 0


def test_edit_instruction_is_verbatim():
    instr = imgedit.compose(change="the man's eyes: make both of his eyes mirror-polished liquid chrome",
                            keep="the woman, her glove on his cheek")
    assert instr == "Change only the man's eyes: make both of his eyes mirror-polished liquid chrome. Keep the woman, her glove on his cheek."
    t = imgedit.message_text(instr)
    assert t.startswith("Edit this photograph. Change only the man's eyes")
    assert t.endswith(" Keep everything else exactly as it is: the same framing and crop, the same light, colours, film grain "
                      "and sharpness, the same people and objects except what this instruction changes. Photorealistic, the "
                      "same photograph, same aspect ratio.")


def test_edit_roundtrip(env, monkeypatch, tmp_path):
    src = H.write_png(tmp_path / "plate.png", (120, 30, 30), (96, 54))
    ref = H.write_png(tmp_path / "obj.png", (0, 200, 0))
    out_png = H.png_bytes((30, 30, 120), (96, 54))
    s = fake(monkeypatch, {("POST", "/chat/completions"): H.FakeResp(200, {"id": "gen-1", "choices": [{"message": {
        "content": "", "images": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + H.b64(out_png)}}]}}],
        "usage": {"cost": .1352}})})
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "fixed.png"), "--change", "the sky: make it night",
                  "--keep", "the woman", "--ref", str(ref), "--yes")
    assert rc == 0, out
    body = s.calls[0]["body"]
    assert body["model"] == "google/gemini-3-pro-image" and body["modalities"] == ["image", "text"]
    content = body["messages"][0]["content"]
    assert content[0]["text"].startswith("Edit this photograph. Change only the sky: make it night. Keep the woman.")
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,") and len(content) == 3
    assert (tmp_path / "fixed.png").read_bytes() == out_png and out["size"] == [96, 54]
    assert ledger.rows(env)[-1]["kind"] == "image-edit" and ledger.rows(env)[-1]["est_usd"] == .1352
    # a jpg destination converts
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "fixed.jpg"), "make it night", "--yes")
    assert rc == 0 and (tmp_path / "fixed.jpg").read_bytes()[:3] == b"\xff\xd8\xff"


def test_edit_without_image_explains(env, monkeypatch, tmp_path):
    src = H.write_png(tmp_path / "plate.png")
    fake(monkeypatch, {("POST", "/chat/completions"): H.FakeResp(200, {"choices": [{"message": {"content": "I can't do that."}}]})})
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "o.png"), "make it night", "--yes")
    assert rc == 1 and "no image returned" in out["error"]


def test_n_images_with_out_keep_the_name(env, monkeypatch, tmp_path):
    fake(monkeypatch, {("POST", "/images"): H.FakeResp(200, {"data": [
        {"b64_json": H.b64(H.png_bytes((1, 2, 3))), "media_type": "image/png"},
        {"b64_json": H.b64(H.png_bytes((4, 5, 6))), "media_type": "image/png"}], "usage": {"cost": .008}})})
    rc, out = run(env, "gen", "image", "x", "--out", "plates/one.png", "--n", "2")
    assert rc == 0, out
    assert [Path(f).name for f in out["files"]] == ["one-1.png", "one-2.png"]
    assert all(Path(f).parent == env / "plates" for f in out["files"])


def test_image_timeout_is_not_resent_and_counted(env, monkeypatch):
    import requests

    def timeout(method, url, body):
        raise requests.ReadTimeout("read timed out")
    s = fake(monkeypatch, {("POST", "/images"): timeout})
    rc, out = run(env, "gen", "image", "x", "--plate", "p", "--quality", "low")
    assert rc == 1 and "openrouter.ai/activity" in out["error"]
    assert len(s.calls) == 1                                            # never re-posted (it may have been billed)
    row = ledger.rows(env)[-1]
    assert row["status"] == "submitted" and row["est_usd"] > 0 and "unknown_outcome" in row["note"]
