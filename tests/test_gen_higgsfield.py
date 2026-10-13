"""Higgsfield path: the request file the bot executes with its MCP connector, and result ingest."""
from __future__ import annotations

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
from slop.gen import higgsfield as hf, store, templates as tpl  # noqa: E402

pytestmark = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)           # the Higgsfield path needs no key
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects")


def run(pdir, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(pdir), *argv])
    return rc, json.loads(buf.getvalue())


def ready(env, tmp_path, shot, kind, *extra):
    rc, out = run(env, "clip", "new", shot, "--kind", kind, "--provider", "higgsfield", *extra)
    cid = out["clip_id"]
    c = store.load(env, cid)
    f = tmp_path / f"{cid}.txt"; f.write_text(tpl.SLOT_RE.sub("she moves", c["body"]["prompt"]), encoding="utf-8")
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0, out
    return cid


def test_sung_request_shape(env, tmp_path):
    cid = ready(env, tmp_path, "s002", "sung")
    rc, out = run(env, "clip", "submit", cid, "--yes", "--res", "480p")
    assert rc == 0, out
    req = json.loads(Path(out["request_file"]).read_text())
    prm = req["request"]["params"]
    assert prm["model"] == "seedance_2_5" and prm["mode"] == "omni_reference" and prm["resolution"] == "480p"
    assert prm["draft"] is True and prm["duration"] == 4 and prm["aspect_ratio"] == "16:9"
    assert "generate_audio" not in prm                                 # sung: omitted (= true)
    assert [m["role"] for m in prm["medias"]] == ["image_references", "audio_references"]
    assert prm["medias"][0]["value"] == f"<<MEDIA_ID:{cid}__image_references__0>>"
    assert [u["type"] for u in req["uploads"]] == ["image", "audio"] and req["uploads"][1]["filename"].endswith(".mp3")
    assert req["get_cost"]["params"]["get_cost"] is True and req["expected_credits"] == 12
    assert any("generate_video_batch" in s for s in req["how_to_run"]) and any("get_cost" in s for s in req["how_to_run"])
    assert req["warnings"] and "late" in req["warnings"][0]            # the Higgsfield pre-roll tail warning
    c = store.load(env, cid)
    assert c["status"] == "submitted" and c["takes"][0]["status"] == "requested"
    row = ledger.rows(env)[-1]
    assert row["provider"] == "higgsfield" and row["credits"] == 12 and ledger.spent_credits(env) == 12


def test_motion_first_frame_request_and_renumbering(env, tmp_path):
    cid = ready(env, tmp_path, "s004", "motion", "--frame", "first")
    c = store.load(env, cid)
    c["refs"] = ["plates/cands/hall/1.png"]
    c["body"]["prompt"] = "Moving in time with @Audio1. The woman from @Image1 walks. No cuts."
    store.save(env, c)
    req = hf.build_request(env, store.load(env, cid), resolution="720p")
    prm = req["request"]["params"]
    assert [m["role"] for m in prm["medias"]] == ["start_image", "image_references", "audio_references"]
    assert prm["generate_audio"] is False and "draft" not in prm
    assert "@Image2" in prm["prompt"] and "@Image1" not in prm["prompt"] and req["prompt_note"]
    assert req["expected_credits"] == 7 * 5


def test_known_media_ids_skip_uploads(env, tmp_path):
    cid = ready(env, tmp_path, "s002", "sung")
    assert run(env, "gen", "host", cid, "--role", "start", "--media-id", "11111111-2222-4333-8444-555555555555")[0] == 0
    assert run(env, "gen", "host", cid, "--url", "https://d1.cloudfront.example/u/a.mp3", "--media-id",
               "66666666-2222-4333-8444-555555555555")[0] == 0
    req = hf.build_request(env, store.load(env, cid))
    assert [m["value"] for m in req["request"]["params"]["medias"]] == ["11111111-2222-4333-8444-555555555555",
                                                                        "66666666-2222-4333-8444-555555555555"]
    assert not req["uploads"]
    assert store.load(env, cid)["window"]["url"] == "https://d1.cloudfront.example/u/a.mp3"


def test_ingest_pending_url_and_failure(env, tmp_path, monkeypatch):
    cid = ready(env, tmp_path, "s002", "sung")
    run(env, "clip", "submit", cid, "--yes")
    rc, out = run(env, "clip", "ingest", cid, "--pending", "--job-id", "job-1")
    assert rc == 0 and store.load(env, cid)["takes"][0]["status"] == "pending"
    rc, out = run(env, "clip", "poll")
    assert "jobs_wait" in out["text"]
    take = H.make_mp4(tmp_path / "res.mp4", None, duration=2)
    s = H.FakeSession({("GET", "cloudfront"): H.FakeResp(200, content=take.read_bytes())})
    import requests
    monkeypatch.setattr(requests, "Session", lambda: s)
    rc, out = run(env, "clip", "ingest", cid, "--url", "https://d2.cloudfront.example/res.mp4", "--job-id", "job-1",
                  "--credits", "30")
    assert rc == 0, out
    assert "Authorization" not in s.calls[0]["headers"]                # public URL: no key is ever sent
    c = store.load(env, cid)
    assert c["status"] == "delivered" and c["takes"][0]["file"] == f"clips/{cid}/take-1.mp4" and c["takes"][0]["credits"] == 30
    assert ledger.spent_credits(env) == 30                               # 28 estimated + 2 adjustment
    rc, out = run(env, "clip", "ingest", cid, "--url", "https://d2.cloudfront.example/res.mp4", "--job-id", "job-1")
    assert rc == 0 and "already ingested" in out["text"] and len(store.load(env, cid)["takes"]) == 1
    # a second request that the silent input filter fails is refunded and goes back to locked
    run(env, "clip", "lock", cid)
    run(env, "clip", "submit", cid, "--yes")
    rc, out = run(env, "clip", "ingest", cid, "--failed", "failed with no reason (filter)")
    assert rc == 0 and "reword" in out["text"]
    assert store.load(env, cid)["status"] == "locked" and ledger.spent_credits(env) == 30


def test_duration_limits(env, tmp_path):
    cid = ready(env, tmp_path, "s004", "motion")
    c = store.load(env, cid); c["body"]["duration"] = 10; store.save(env, c)
    with pytest.raises(Exception, match="4–8 s"):
        hf.build_request(env, c)
