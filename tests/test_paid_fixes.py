"""Paid-track review fixes (phase 2), tested offline with fake HTTP: the batch runner never overwrites a paid image
(duplicate plates, parallel workers), resume counts only images made at the same settings, runnable hints; the clip
dry run runs the submit's own preflight; one next step per output-audio refusal (OpenRouter and Higgsfield); the Lyria
ledger never under-counts; the edit medium (cel alias, inferred from the lead) and the conservative edit estimate;
`slop sync check` says where the sync starts and whether the take is a copy.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import sys
import threading
import time
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop import ledger  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.gen import images, imgedit, models as reg, song, store, templates as tpl  # noqa: E402
from slop.gen.openrouter import ADVICE  # noqa: E402

KEY = "sk-or-v1-test-not-a-real-key"
needs_ffmpeg = pytest.mark.skipif(not H.FFMPEG, reason="ffmpeg is required")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")
    return H.make_project(tmp_path / "projects", audio=bool(H.FFMPEG))


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


def slow_images(method, url, body):
    time.sleep(.05)                                                  # every worker holds a response at the same time
    n = int(body.get("n") or 1)
    return H.FakeResp(200, {"data": [{"b64_json": H.b64(H.png_bytes((10 * i, 20, 30))), "media_type": "image/png"}
                                     for i in range(n)], "usage": {"cost": round(.004 * n, 6)}})


def write_jobs(pdir: Path, jobs: list[dict]) -> Path:
    p = pdir / "plates" / "jobs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------------ batch runner
def test_duplicate_plates_with_parallel_workers_never_overwrite(env, monkeypatch):
    jobs = [{"plate": "hero", "prompt": f"Option {k}: the lead on a rooftop, illustrated. No text.", "n": 1}
            for k in range(3)] + [{"plate": "hero", "prompt": "Option 0: the lead on a rooftop, illustrated. No text.",
                                   "n": 1}, {"plate": "roof", "prompt": "An empty rooftop at dusk. No text.", "n": 2}]
    write_jobs(env, jobs)
    s = fake(monkeypatch, {("POST", "/images"): slow_images})
    rc, out = run(env, "gen", "image", "--jobs", "--yes", "--workers", "4")
    assert rc == 0, out
    hero = sorted(p.name for p in (env / "plates" / "cands" / "hero").iterdir())
    assert hero == ["1.json", "1.png", "2.json", "2.png", "3.json", "3.png", "4.json", "4.png"]
    paid = [r for r in ledger.rows(env) if r["kind"] == "image"]
    assert len(paid) == 5 and len(out["made"]) == 6 and len(s.calls) == 5      # every paid image is on disk
    sides = [json.loads((env / "plates" / "cands" / "hero" / f"{k}.json").read_text()) for k in range(1, 5)]
    assert sorted(x["prompt"][:8] for x in sides) == ["Option 0", "Option 0", "Option 1", "Option 2"]
    # re-run: the two identical jobs share the two images made from that prompt: nothing is paid again
    rc, out = run(env, "gen", "image", "--jobs", "--yes")
    assert rc == 0 and "nothing to do" in out["text"] and len(s.calls) == 5
    # one of the two lost: exactly one job makes one image again
    k = next(k for k, x in enumerate(sides, 1) if x["prompt"].startswith("Option 0"))
    (env / "plates" / "cands" / "hero" / f"{k}.png").unlink()
    rc, out = run(env, "gen", "image", "--jobs", "--yes")
    assert rc == 0 and len(s.calls) == 6 and out["planned_images"] == 1
    assert [j["need"] for j in out["jobs"]] == [0, 0, 0, 1, 0]


def test_reserve_claims_numbers_atomically(env, monkeypatch):
    monkeypatch.setattr(images, "next_index", lambda d: 1)               # every writer sees the same stale k
    d = env / "plates" / "cands" / "race"
    got, start = [], threading.Barrier(6)

    def claim():
        start.wait()
        got.append(images.reserve(d, ".png", {"model": "m"}).name)
    ts = [threading.Thread(target=claim) for _ in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(got) == [f"{k}.png" for k in range(1, 7)]


def test_resume_counts_only_the_same_settings(env, monkeypatch):
    write_jobs(env, [{"plate": "roof", "prompt": "An empty rooftop at dusk. No text.", "n": 1}])
    s = fake(monkeypatch, {("POST", "/images"): slow_images})
    assert run(env, "gen", "image", "--jobs", "--quality", "low", "--yes")[0] == 0
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--yes")
    assert "nothing to do" in out["text"] and len(s.calls) == 1
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "high")             # the finals pass is not "done"
    assert rc == 0 and out["planned_images"] == 1 and "1 made at other settings, not counted" in out["text"]
    assert run(env, "gen", "image", "--jobs", "--quality", "high", "--yes")[0] == 0
    assert len(s.calls) == 2 and s.calls[-1]["body"]["quality"] == "high"


def test_hints_name_the_project_and_a_stopped_batch_has_one_next_step(env, monkeypatch):
    write_jobs(env, [{"plate": "roof", "prompt": "An empty rooftop at dusk. No text.", "n": 1},
                     {"plate": "hall2", "prompt": "A long hall. No text.", "n": 1}])
    fake(monkeypatch, {})
    rc, out = run(env, "gen", "image", "--jobs")
    assert "Show the prompts in plates/jobs.json" in out["text"] and "prompts.md" not in out["text"]
    assert f"run: slop -p {env.name} gen image --jobs plates/jobs.json --yes" in out["text"]
    (env / "plates" / "prompts.md").write_text("# prompts\n", encoding="utf-8")
    assert "Show plates/prompts.md" in run(env, "gen", "image", "--jobs")[1]["text"]
    fake(monkeypatch, {("POST", "/images"): H.FakeResp(402, {"error": {"code": 402, "message": "Insufficient credits"}})})
    rc, out = run(env, "gen", "image", "--jobs", "--yes", "--workers", "1")
    assert rc == 1 and "STOPPED" in out["text"] and "next:" not in out["text"]
    assert f"slop -p {env.name} gen image --jobs plates/jobs.json --yes" in out["error"]


# ------------------------------------------------------------------------------------------------ clip dry run
def sung_locked(env, tmp_path, cid="W01", shot="s002", *extra) -> dict:
    rc, out = run(env, "clip", "new", shot, "--kind", "sung", "--id", cid, *extra)
    assert rc == 0, out
    c = store.load(env, cid)
    f = tmp_path / f"{cid}.txt"; f.write_text(tpl.SLOT_RE.sub("she sings it softly", c["body"]["prompt"]), encoding="utf-8")
    assert run(env, "clip", "set", cid, "--prompt-file", str(f))[0] == 0
    rc, out = run(env, "clip", "lock", cid)
    assert rc == 0, out
    return store.load(env, cid)


@needs_ffmpeg
def test_dry_run_runs_the_submit_preflight(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    s = fake(monkeypatch, {})
    rc, out = run(env, "clip", "submit", "W01", "--dry-run", "--no-audio-ref")
    assert rc == 0 and any("never submitted without its audio window" in p for p in out["lock_problems"])
    assert "--yes" not in out["text"].split("next:")[-1] and "fix the problems above" in out["text"]
    rc, real = run(env, "clip", "submit", "W01", "--yes", "--no-audio-ref")
    assert rc == 1 and "never submitted without its audio window" in real["error"]
    rc, out = run(env, "clip", "submit", "W01", "--dry-run", "--res", "1080p")
    assert any("480p/720p only" in p for p in out["lock_problems"]) and "--yes" not in out["text"].split("next:")[-1]
    rc, real = run(env, "clip", "submit", "W01", "--yes", "--res", "1080p")
    assert rc == 1 and "480p/720p only" in real["error"]
    rc, out = run(env, "clip", "submit", "W01", "--dry-run")                     # the clean case still offers --yes
    assert out["lock_problems"] == [] and "slop -p demo clip submit W01 --yes" in out["text"]
    assert not s.calls and not ledger.rows(env)


@needs_ffmpeg
def test_dry_run_flags_a_sung_request_without_audio(env, tmp_path, monkeypatch):
    from slop.gen import video as vid
    sung_locked(env, tmp_path)
    real_build = vid.build_body

    def no_audio(pdir, c, *, model, audio_url=None, **kw):                     # a regression that drops @Audio1
        return real_build(pdir, c, model=model, audio_url=None, **kw)
    monkeypatch.setattr(vid, "build_body", no_audio)
    rc, out = run(env, "clip", "submit", "W01", "--dry-run")
    assert any("@Audio1" in p for p in out["lock_problems"]) and "--yes" not in out["text"].split("next:")[-1]


@needs_ffmpeg
def test_higgsfield_dry_run_has_the_tail_warning_and_the_credit_cap(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path, "W02", "s003", "--provider", "higgsfield")
    c = store.load(env, "W02")
    from slop.gen import clips
    from slop.sync.songdata import SongData
    tail = clips.higgsfield_tail_warning(SongData(env), float(c["song_t0"]), float(c["body"]["duration"]))
    rc, out = run(env, "clip", "submit", "W02", "--dry-run", "--res", "480p")
    assert rc == 0 and (tail is None or any("0.8 s" in w for w in out["warnings"]))
    assert "next: slop -p demo clip submit W02 --res 480p --yes" in out["text"]           # the hint keeps the flags it ran with
    sung_locked(env, tmp_path, "W03", "s002")
    rc, out = run(env, "clip", "submit", "W03", "--dry-run", "--provider", "higgsfield", "--res", "480p")
    assert out["provider"] == "higgsfield" and "slop -p demo clip submit W03 --provider higgsfield --res 480p --yes" in out["text"]
    assert store.load(env, "W03")["provider"] == "openrouter"                    # the dry run saved nothing
    proj = json.loads((env / "project.json").read_text()); proj["budget"]["higgsfield_credits"] = 5
    (env / "project.json").write_text(json.dumps(proj))
    rc, out = run(env, "clip", "submit", "W02", "--dry-run", "--res", "480p")
    assert any("credit cap" in w for w in out["warnings"]) and "--yes" not in out["text"].split("next:")[-1]
    rc, real = run(env, "clip", "submit", "W02", "--yes", "--res", "480p")
    assert rc == 1 and "credit cap" in real["error"]


def test_tail_warning_reaches_the_higgsfield_dry_run(env, monkeypatch):
    from slop.gen import clips
    c = {"id": "Z1", "kind": "sung", "provider": "higgsfield", "song_t0": 10.0, "status": "locked", "start": "x.png",
         "body": {"duration": 4, "prompt": "p", "resolution": "480p"}, "window": {"file": "audio/windows/Z1.mp3"},
         "hosted": {"start": {"media_id": "11111111-1111-4111-8111-111111111111"},
                    "audio": {"media_id": "22222222-2222-4222-8222-222222222222"}}}
    monkeypatch.setattr(clips, "lock_problems", lambda pdir, c: [])
    monkeypatch.setattr(clips, "higgsfield_tail_warning", lambda song, t0, dur: "the last word ends late (CLIP)")
    out = clips.dry_run(env, c, json.loads((env / "project.json").read_text()))
    assert "the last word ends late (Z1)" in out["warnings"] and "slop clip submit Z1 --yes" in out["text"]


# ------------------------------------------------------------------------------------------------ refusals: one step
def _instructions(text: str) -> int:
    return len(re.findall(r"slop (?:-p \S+ )?clip submit", text))


@needs_ffmpeg
def test_refusal_lines_carry_exactly_one_instruction(env, tmp_path, monkeypatch):
    sung_locked(env, tmp_path)
    run(env, "gen", "host", "W01", "--url", "https://cdn.example.com/W01.wav")
    fake(monkeypatch, {("POST", "/videos"): H.FakeResp(202, {"id": "gen-vid-a", "status": "pending"}),
                       ("GET", "/videos/"): H.FakeResp(200, {"status": "failed", "error":
                                                             "The output audio may contain sensitive information"})})
    assert run(env, "clip", "submit", "W01", "--yes")[0] == 0
    rc, out = run(env, "clip", "poll", "W01")
    assert _instructions(out["text"]) == 1 and ADVICE["sensitive"] not in out["text"]
    assert "Change the window" not in out["text"] and "not billed" in out["text"]
    fake(monkeypatch, {("POST", "/videos"): H.FakeResp(400, {"error": {"code": 400, "message":
                       "The request failed because the output audio may be related to copyright restrictions"}})})
    rc, out = run(env, "clip", "submit", "W01", "--yes")
    assert rc == 1 and ADVICE["copyright"] not in out["error"] and ADVICE["copyright"] not in out["text"]
    assert _instructions(out["error"]) == 1 and _instructions(out["text"]) == 1


def test_advice_agrees_with_the_protocol():
    for st in ("sensitive", "copyright"):
        a = ADVICE[st]
        assert "other provider" in a and "move the window" not in a and "Change the window" not in a


@needs_ffmpeg
def test_higgsfield_failed_refusals_follow_the_protocol(env, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    sung_locked(env, tmp_path, "W01", "s002", "--provider", "higgsfield")
    assert run(env, "clip", "submit", "W01", "--yes", "--res", "480p")[0] == 0
    rc, out = run(env, "clip", "ingest", "W01", "--failed", "output audio may contain sensitive information")
    assert rc == 0 and "NEXT (higgsfield refused once" in out["text"] and _instructions(out["text"]) == 1
    c = store.load(env, "W01")
    assert c["status"] == "locked" and c["refusals"][0]["provider"] == "higgsfield" and ledger.spent_credits(env) == 0
    assert run(env, "clip", "submit", "W01", "--yes", "--res", "480p")[0] == 0
    rc, out = run(env, "clip", "ingest", "W01", "--failed", "The output audio may contain sensitive information")
    assert "refused 2 times" in out["text"] and "--provider openrouter" in out["text"] and out["next"]
    assert "--failed" in " ".join(json.loads((env / "clips" / "W01" / "higgsfield-request.json").read_text())["how_to_run"])


# ------------------------------------------------------------------------------------------------ Lyria ledger
def test_lyria_zero_cost_never_under_counts():
    assert song.ledger_usd("google/lyria-3-clip-preview", 0, .04) == .04
    assert song.ledger_usd("google/lyria-3-pro-preview", 0.0, .08) == .08
    assert song.ledger_usd("google/lyria-3-pro-preview", 0.09, .08) == .09
    assert song.ledger_usd("google/lyria-3-pro-preview", None, .08) == .08


def test_lyria_cli_ledgers_the_estimate_when_the_stream_says_zero(env, monkeypatch):
    import base64
    raw = b"ID3" + bytes(range(256)) * 4
    lines = [b"data: " + json.dumps({"choices": [{"delta": {"audio": {"data": base64.b64encode(raw).decode()}}}]}).encode(),
             b"data: " + json.dumps({"choices": [], "usage": {"cost": 0}}).encode(), b"data: [DONE]"]
    fake(monkeypatch, {("POST", "/chat/completions"): H.FakeResp(200, content=b"", lines=lines)})
    rc, out = run(env, "gen", "song", "--prompt", "Trance, 132 BPM. Lyrics: [Chorus] Go", "--clip", "--yes")
    assert rc == 0, out
    row = ledger.rows(env)[-1]
    assert row["est_usd"] == pytest.approx(.04) and row["units"]["real_usd"] == 0


# ------------------------------------------------------------------------------------------------ edit medium + estimate
def _edit_resp():
    return H.FakeResp(200, {"id": "gen-1", "choices": [{"message": {"content": "", "images": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + H.b64(H.png_bytes((30, 30, 120), (96, 54)))}}]}}],
        "usage": {"cost": .1352}})


def test_edit_medium_cel_alias_and_inferred_from_the_lead(env, monkeypatch, tmp_path):
    src = H.write_png(tmp_path / "lead.png", (120, 30, 30), (96, 54))            # no sidecar: a staged lead image
    s = fake(monkeypatch, {("POST", "/chat/completions"): _edit_resp()})
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "a.png"), "make it night", "--yes", "--medium", "cel")
    assert rc == 0 and out["medium"] == "illustration"
    assert s.calls[-1]["body"]["messages"][0]["content"][0]["text"].startswith("Edit this illustration.")
    proj = json.loads((env / "project.json").read_text())
    proj["lead"]["canon"] = "a young woman drawn in clean anime cel-shading: a black bob"
    (env / "project.json").write_text(json.dumps(proj))
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "b.png"), "make it night", "--yes")
    assert rc == 0 and out["medium"] == "illustration" and "--medium photo" in out["warnings"][0]
    proj["look"]["medium"] = "cel"; (env / "project.json").write_text(json.dumps(proj))
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "c.png"), "make it night", "--yes")
    assert out["medium"] == "illustration" and not out["warnings"]
    rc, out = run(env, "gen", "edit", str(src), str(tmp_path / "d.png"), "make it night", "--yes", "--medium", "photo")
    assert out["medium"] == "photo"
    assert imgedit.project_medium({"lead": {"canon": "a woman, 30, freckles"}, "look": {}}) == ("photo", None)


def test_edit_estimate_takes_the_priciest_endpoint(monkeypatch):
    two = {"id": "google/gemini-3-pro-image-preview", "endpoints": [
        {"pricing": [{"billable": "input_image", "unit": "token", "cost_usd": 1e-06},
                     {"billable": "output_image", "unit": "token", "cost_usd": 6e-05}]},
        {"pricing": [{"billable": "input_image", "unit": "token", "cost_usd": 2e-06},
                     {"billable": "output_image", "unit": "token", "cost_usd": .00012}]}]}
    chat = {"id": two["id"], "pricing": {"prompt": "0.000002", "image_output": "0.00012"}}
    monkeypatch.setattr(reg, "find", lambda kind, mid, **kw: two if kind == "image" else chat)
    cheap = reg.estimate_image(two["id"], "1K", None, 1, 1)
    est = reg.estimate_edit(two["id"], 1)
    assert cheap < .07 and est > .13                                            # the old $0.068 vs ~$0.137


def test_edit_estimates_alike_for_both_ids(env):
    a = reg.estimate_edit("google/gemini-3-pro-image", 1)
    assert .13 < a < .145
    rc, out = run(env, "gen", "estimate", "--kind", "edit", "--model", "google/gemini-3-pro-image")
    assert rc == 0 and out["est_usd"] == pytest.approx(a)


# ------------------------------------------------------------------------------------------------ sync check text
def test_sync_check_line_names_the_span_and_the_copy_verdict():
    from slop.sync.cli import summary
    late = {"synced_from": 1.77, "synced_until": 2.25, "lag_ncc": .022, "lag_s": 0.0, "diverges": True,
            "diverge_at": 2.3, "dips": [], "duration": 5.0, "song_t0": None, "cut_eighth_song": None}
    t = summary("take.mp4", late)
    assert "in sync 1.77–2.25 s (0.48 s)" in t and "(not a copy)" in t and "in sync to" not in t
    never = {**late, "synced_from": 0.0, "synced_until": 0.0}
    assert "never in sync" in summary("take.mp4", never)
    good = {**late, "synced_from": .12, "synced_until": 1.38, "lag_ncc": .31, "dips": [[.4, .9]]}
    t = summary("take.mp4", good)
    assert "(copy)" in t and "in sync 0.12–1.38 s" in t and "out of sync (recovered) 0.40–0.90 s" in t
    whole = {**good, "diverges": False, "diverge_at": None}
    assert "in sync 0.12 s to the end (5.00 s)" in summary("take.mp4", whole)
    shared = {**good, "sung_s_in_sync": .87, "sung_s": 2.6, "share": .335}
    assert "0.87/2.60 sung s in sync (34%)" in summary("take.mp4", shared)


@needs_ffmpeg
def test_sync_check_cli_reports_the_sung_share(env, tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.chdir(tmp_path)
    ref = H.babble(4.0, seed=1)
    other = H.babble(4.0, seed=2)
    H.write_wav(tmp_path / "ref.wav", ref)
    H.write_wav(tmp_path / "late.wav", np.r_[other[: int(1.5 * H.SR)], ref[int(1.5 * H.SR):]].astype(np.float32))
    take = H.make_mp4(tmp_path / "late.mp4", tmp_path / "late.wav")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(env), "sync", "check", str(take), str(tmp_path / "ref.wav"),
                   "--song-t0", "10", "--png", str(tmp_path / "s.png")])
    out = json.loads(buf.getvalue())
    assert rc == 0, out
    assert f"in sync {out['synced_from']:.2f}" in out["text"] or "never in sync" in out["text"]
    assert out["share"] is not None and "sung s in sync" in out["text"] and (tmp_path / "s.png").is_file()
    assert out["need_song"][0] >= 10.0                                         # the window's voiced span, in song time
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--json", "--project", str(env), "sync", "check", str(take), str(tmp_path / "ref.wav"),
                   "--song-t0", "10", "--need", "10", "11"])
    assert rc == 0 and json.loads(buf.getvalue())["need_song"] == [10.0, 11.0]
