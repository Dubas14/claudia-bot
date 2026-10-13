"""`slop gen image --provider codex`: stills on the ChatGPT plan through the Codex CLI's built-in image tool, mocked with a
fake `codex` that plays `codex exec --json` (never a real call). Ledger at $0 with note "plan"; a background job."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_K = Path(__file__).parent / "fixtures" / "agents" / "kit.py"
_spec = importlib.util.spec_from_file_location("agents_kit", _K)
K = importlib.util.module_from_spec(_spec); sys.modules.setdefault("agents_kit", K); _spec.loader.exec_module(K)
_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_hs = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_hs); sys.modules.setdefault("gen_test_helpers", H); _hs.loader.exec_module(H)

from slop import ledger  # noqa: E402

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX fake CLI")


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = K.setup(tmp_path, monkeypatch, engines=("codex",), logged=("codex",))
    e["proj"] = H.make_project(tmp_path / "projects", audio=False)
    monkeypatch.setenv("SLOP_CODEX_IMAGE_FOREGROUND", "1")
    return e


def run(env, *argv):
    return K.run("--project", str(env["proj"]), *argv)


def exec_calls(env):
    return [c for c in K.calls(env["state"], "codex") if c["argv"][:1] == ["exec"]]


def test_one_image_on_the_plan(env, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-never-used")
    rc, out = run(env, "gen", "image", "a neon hall, fog, a lone singer", "--plate", "neon", "--provider", "codex")
    assert rc == 0, out
    f = Path(out["files"][0])
    assert f.parent == env["proj"] / "plates" / "cands" / "neon" and f.suffix == ".png" and f.name == "1.png"
    side = json.loads(f.with_suffix(".json").read_text())
    assert side["model"] == "codex/imagegen" and side["provider"] == "codex" and side["cost_usd"] == 0.0
    assert side["prompt"] == "a neon hall, fog, a lone singer" and side["size"] == [48, 27]
    assert side["revised_prompt"] == "a revised prompt" and side["thread_id"]
    row = ledger.rows(env["proj"])[-1]
    assert row["provider"] == "codex" and row["est_usd"] == 0.0 and row["note"] == "plan" and row["status"] == "ok"
    assert ledger.spent_usd(env["proj"]) == 0.0
    call = exec_calls(env)[-1]
    a = call["argv"]
    assert a[:3] == ["exec", "--json", "--skip-git-repo-check"] and 'forced_login_method="chatgpt"' in a
    assert a[a.index("--enable") + 1] == "image_generation" and a[a.index("-s") + 1] == "read-only" and a[-1] == "-"
    assert "OPENAI_API_KEY" not in call["env_present"]
    assert "$imagegen" in call["stdin_head"] and "16:9" in call["stdin_head"] and "a neon hall" in call["stdin_head"]
    assert "$0" in out["text"] and "plates sheet" in out["text"]


def test_found_by_scanning_generated_images_when_the_events_lack_a_path(env, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_IMG", "nosaved")
    rc, out = run(env, "gen", "image", "x", "--out", "stills/a.png", "--provider", "codex", "--aspect-ratio", "9:16")
    assert rc == 0, out
    assert Path(out["files"][0]) == env["proj"] / "stills" / "a.png"
    assert "9:16" in exec_calls(env)[-1]["stdin_head"]


def test_refs_are_attached_and_n_makes_several(env, tmp_path):
    ref = H.write_png(tmp_path / "ref.png")
    rc, out = run(env, "gen", "image", "same lead, new angle", "--plate", "hero-cu", "--provider", "codex", "--n", "2",
                  "--ref", str(ref))
    assert rc == 0, out
    assert [Path(f).name for f in out["files"]] == ["3.png", "4.png"]     # 1.png and 2.png are the fixture's
    a = exec_calls(env)[-1]["argv"]
    assert a[a.index("-i") + 1] == str(ref) and "attached image" in exec_calls(env)[-1]["stdin_head"]


@pytest.mark.parametrize("mode,kind,msg", [("noimage", "noimage", "without an image"),
                                           ("limit", "limit", "--limits")])
def test_failures_are_ledgered_at_zero_and_explained(env, monkeypatch, mode, kind, msg):
    monkeypatch.setenv("FAKE_CODEX_IMG", mode)
    rc, out = run(env, "gen", "image", "x", "--plate", "p1", "--provider", "codex")
    assert rc == 1 and msg in out["error"]
    row = ledger.rows(env["proj"])[-1]
    assert row["status"] == "failed" and row["est_usd"] == 0.0 and row["note"].startswith(f"plan: {kind}")


def test_timeout_stops_codex(env, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_IMG", "slow")
    monkeypatch.setenv("SLOP_CODEX_IMAGE_TIMEOUT", "2")
    rc, out = run(env, "gen", "image", "x", "--plate", "p1", "--provider", "codex")
    assert rc == 1 and "no image after 2 s" in out["error"]
    assert not K.pids_alive("fakecli.py codex exec")


def test_needs_the_chatgpt_sign_in(env):
    (env["state"] / "codex_logged_in").unlink()
    rc, out = run(env, "gen", "image", "x", "--plate", "p1", "--provider", "codex")
    assert rc == 1 and "slop agents login codex" in out["error"]
    assert not exec_calls(env)


def test_openrouter_only_flags_are_refused(env):
    rc, out = run(env, "gen", "image", "x", "--plate", "p1", "--provider", "codex", "--model", "openai/gpt-image-2")
    assert rc == 1 and "--model" in out["error"] and "do not apply" in out["error"]


def test_outside_a_job_it_starts_one(env, monkeypatch, tmp_path):
    monkeypatch.delenv("SLOP_CODEX_IMAGE_FOREGROUND")
    from slop import job
    got = {}

    def fake_start(words, project=None, **kw):
        got.update(words=words, project=project)
        return {"job": {"id": "gen-image-wxyz", "wait": "slop job wait gen-image-wxyz --max 25"}, "existing": False}
    monkeypatch.setattr(job, "start", fake_start)
    (env["proj"] / "plates" / "api").mkdir(parents=True)
    (env["proj"] / "plates" / "api" / "hall.txt").write_text("a hall")
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir(); monkeypatch.chdir(elsewhere)
    rc, out = run(env, "gen", "image", "--prompt-file", "plates/api/hall.txt", "--plate", "hall", "--provider", "codex")
    assert rc == 0 and out["next"] == "slop job wait gen-image-wxyz --max 25" and "$0" in out["text"]
    w = got["words"]
    assert w[:2] == ["gen", "image"] and w[-2:] == ["--provider", "codex"]
    assert w[w.index("--prompt-file") + 1] == str(env["proj"] / "plates" / "api" / "hall.txt")   # absolute for the job
    assert got["project"] == str(env["proj"])
    ns = job.check_argv(w)                                    # the job's argv parses with the real router
    assert ns.provider == "codex"
    assert not exec_calls(env)


def test_jobs_batch_dry_run_then_run_then_resume(env):
    jobs = {"jobs": [{"plate": "hall", "prompt": "a long concrete hall", "n": 2},
                     {"plate": "roof", "prompt": "a rooftop at dawn", "aspect": "21:9"}]}
    (env["proj"] / "plates" / "jobs.json").write_text(json.dumps(jobs))
    rc, out = run(env, "gen", "image", "--jobs", "--provider", "codex")
    assert rc == 0 and out["dry_run"] and out["planned_images"] == 3 and "DRY RUN" in out["text"]
    assert "--provider codex --jobs plates/jobs.json --yes" in out["text"] and not exec_calls(env)
    rc, out = run(env, "gen", "image", "--jobs", "--provider", "codex", "--yes")
    assert rc == 0 and len(out["made"]) == 3, out
    assert "21:9" in exec_calls(env)[-1]["stdin_head"]
    n = len(exec_calls(env))
    rc, out = run(env, "gen", "image", "--jobs", "--provider", "codex", "--yes")
    assert rc == 0 and out["planned_images"] == 0 and len(exec_calls(env)) == n       # resumable: nothing made twice
    assert sum(1 for r in ledger.rows(env["proj"]) if r["provider"] == "codex") == 3


def test_batch_stops_at_the_plan_limit(env, monkeypatch):
    (env["proj"] / "plates" / "jobs.json").write_text(json.dumps({"jobs": [{"plate": "a", "prompt": "x", "n": 3}]}))
    monkeypatch.setenv("FAKE_CODEX_IMG", "limit")
    rc, out = run(env, "gen", "image", "--jobs", "--provider", "codex", "--yes")
    assert rc == 1 and out["stopped"] and len(exec_calls(env)) == 1 and "re-run" in out["text"]


def test_the_provider_hook_is_idempotent_and_keeps_openrouter_as_default():
    import argparse
    from slop.gen import codex_image, images
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers()
    g = sub.add_parser("gen").add_subparsers()
    p = g.add_parser("image")
    p.add_argument("prompt", nargs="?")
    p.set_defaults(func=lambda a: "openrouter-path")
    assert images.install_provider_flag(sub) is True and images.install_provider_flag(sub) is False
    assert ap.parse_args(["gen", "image", "x"]).func(ap.parse_args(["gen", "image", "x"])) == "openrouter-path"
    orig = codex_image.cmd_image
    try:
        codex_image.cmd_image = lambda a: "codex-path"
        ns = ap.parse_args(["gen", "image", "x", "--provider", "codex"])
        assert ns.func(ns) == "codex-path"
    finally:
        codex_image.cmd_image = orig


def test_parse_events_reads_paths_inline_images_and_errors():
    from slop.gen import codex_image as C
    ev = C.parse_events([json.dumps({"type": "thread.started", "thread_id": "t1"}),
                         json.dumps({"type": "item.completed", "item": {"type": "image_generation", "saved_path": "/x/a.png"}}),
                         json.dumps({"type": "item.completed", "item": {"type": "imageGeneration", "result": "A" * 300}}),
                         json.dumps({"type": "turn.failed", "error": {"message": "boom"}}), "not json"])
    assert ev["thread_id"] == "t1" and ev["images"][0] == ("path", "/x/a.png") and ev["images"][1][0] == "b64"
    assert ev["error"] == "boom"
    assert "Composition: a tall portrait 9:16 frame." in C.build_prompt("p", "9:16", 0)
