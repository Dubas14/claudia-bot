"""Tests for templates/briefs/*.md (brief anatomy, placeholders, filling through `deleg.mjs new`) and
templates/workflows/*.js (run through tests/fixtures/deleg/wf_harness.mjs with canned agent answers: control flow,
null agents treated as failures, the chapters pass rule, wiring, concurrency cap, determinism for resume), every `slop`
command the templates and the runner README tell a worker to run (parsed by the real argparse router), plus a scrub
check of everything the deleg module ships. Needs `node` (skipped otherwise)."""
from __future__ import annotations

import json
import math
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # the slop package (for parsing the commands the templates name)
RUNNER = ROOT / "runner" / "deleg.mjs"
BRIEFS = ROOT / "templates" / "briefs"
WORKFLOWS = ROOT / "templates" / "workflows"
HARNESS = ROOT / "tests" / "fixtures" / "deleg" / "wf_harness.mjs"
PREFLIGHT_WF = ROOT / "runner" / "preflight-wf.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
RUNTIME = {"JOB_DIR", "JOB_ID", "OUTBOX", "PROJECT_DIR", "TOOLKIT_DIR", "SLOP", "ENGINE", "WORKFLOW_PATH", "WORKFLOW_ARGS"}
JOB_KEYS = {"id", "kind", "engine", "title", "created", "brief_template", "brief", "prompt_file", "project_dir", "cwd", "workflow",
            "workflow_args", "vars", "model", "effort", "permission_mode", "allowed_tools", "extra_allowed_tools", "disallowed_tools",
            "add_dirs", "max_turns", "max_budget_usd", "sandbox", "network", "codex_config", "approval_mode", "muse_flags", "provider",
            "output_schema", "timeout_s", "allow_api_billing", "allow_spend", "pass_env", "env", "collect", "max_parallel", "engine_bin",
            "workflows_env", "stop_above_utilization", "argv", "slop_cmd", "notes", "wire_chapters", "queue_group", "requires",
            "project_name"}
# job.json fields that need a gate flag on the run command (runner/README.md "Gates"): templates must never set them
GATED = {"allow_api_billing", "allow_spend", "pass_env", "engine_bin", "env", "slop_cmd", "add_dirs", "codex_config", "muse_flags",
         "argv", "extra_allowed_tools", "allowed_tools", "permission_mode", "cwd"}
PH = re.compile(r"\{\{([A-Z][A-Z0-9_]*)(?:\|([^}]*))?\}\}")


def parse_brief(p: Path):
    raw = p.read_text(encoding="utf-8")
    m = re.match(r"<!--(.*?)-->\s*", raw, re.S)
    assert m, f"{p.name}: no header comment"
    head, body = m.group(1), raw[m.end():]
    meta = {"vars": {}}
    in_vars = False
    for line in head.splitlines():
        if mm := re.match(r"\s*(slop-brief|summary|engines):\s*(.*)$", line):
            meta[mm.group(1)] = mm.group(2).strip(); in_vars = False
        elif mm := re.match(r"\s*defaults:\s*(\{.*\})\s*$", line):
            meta["defaults"] = json.loads(mm.group(1)); in_vars = False
        elif re.match(r"\s*vars:\s*$", line):
            in_vars = True
        elif in_vars and (mm := re.match(r"\s+([A-Z][A-Z0-9_]*):\s*(.*)$", line)):
            meta["vars"][mm.group(1)] = mm.group(2)
    return meta, body


BRIEF_FILES = sorted(BRIEFS.glob("*.md"))
WF_FILES = sorted(WORKFLOWS.glob("*.js"))


def test_the_assigned_templates_exist():
    names = {p.stem for p in BRIEF_FILES}
    assert {"research-lyrics", "storyboard-panel", "prompt-book", "chapter-motion", "review", "safety-scan"} <= names
    assert {"storyboard", "chapters", "research-lyrics"} <= {p.stem for p in WF_FILES}


# ---------------------------------------------------------------------------------------------------------- briefs
@pytest.mark.parametrize("path", BRIEF_FILES, ids=lambda p: p.stem)
def test_brief_has_the_full_anatomy(path):
    meta, body = parse_brief(path)
    assert meta.get("slop-brief") == path.stem and meta.get("summary") and meta["vars"]
    low = body.lower()
    assert "nobody answers" in low, "identity: say nobody answers questions mid-run"
    for h in ("## Goal", "## Files", "## Rules", "## Method", "## Budgets", "## Report", "## You do NOT", "## Finish"):
        assert h in body, f"missing section {h}"
    assert "cheating" in low, "rules must define cheating"
    assert re.search(r"within your first ~(\d+|\{\{FIRST_COMMANDS)", body), "the first deliverable must be bounded in commands"
    assert re.search(r"## Report[^\n]*at most \d+ lines", body), "the report needs a length cap"
    assert re.search(r"(verdict|re-run|re-runs|reads the whole book|on its side)", low), "say where the authoritative check lives"
    if path.stem != "generic":
        assert "spend" in low, "budgets must rule out spending"


@pytest.mark.parametrize("path", BRIEF_FILES, ids=lambda p: p.stem)
def test_brief_placeholders_are_documented_and_flat(path):
    meta, body = parse_brief(path)
    for m in PH.finditer(body):
        key, dflt = m.group(1), m.group(2)
        assert key in RUNTIME or key in meta["vars"], f"{{{{{key}}}}} is not documented in the header vars"
        assert key not in RUNTIME or dflt is None
    assert not re.search(r"\{\{[A-Z_]+\|[^}]*\{\{", body), "nested placeholders are not supported"
    d = meta.get("defaults", {})
    assert set(d) <= JOB_KEYS, set(d) - JOB_KEYS
    assert not set(d) & GATED, f"a template must not set gated fields: {set(d) & GATED}"
    if d.get("workflow"):
        assert (WORKFLOWS / f"{d['workflow']}.js").exists()
        assert "{{WORKFLOW_PATH}}" in body and "{{WORKFLOW_ARGS}}" in body and "JSON object" in body
    assert "{{OUTBOX}}" in body


def _deleg(*args):
    r = subprocess.run([NODE, str(RUNNER), *map(str, args)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("path", BRIEF_FILES, ids=lambda p: p.stem)
def test_every_brief_fills_through_new(path, tmp_path):
    proj = tmp_path / "song"
    (proj / "analysis").mkdir(parents=True)
    (proj / "project.json").write_text(json.dumps({"name": "song", "title": "Test Song", "lead": {"canon": "a person in a grey coat", "far": "grey coat"},
                                                    "mj": {"params": "--ar 16:9 --raw", "profile": ""}}), encoding="utf-8")
    (proj / "analysis" / "beats.json").write_text(json.dumps({"duration": 90.5}), encoding="utf-8")
    meta, body = parse_brief(path)
    values = {"CHAPTERS": json.dumps([{"id": "C1", "file": "01_a.js", "name": "A", "t0": 0, "t1": 12.5, "shots": ["s001", "s002"]}]),
              "TODAY": "2026-10-01", "T0": "0", "T1": "12.5", "TOTAL": "4", "ROUNDS": "2", "SLICES": "2", "FIRST_COMMANDS": "10"}
    sets = []
    for k in meta["vars"]:
        if re.search(r"\{\{" + k + r"\}\}", body):   # required (no default) and not auto-filled from project.json
            sets += ["--set", f"{k}={values.get(k, 'value for ' + k.lower())}"]
    r = _deleg("new", "auto", "--project", proj, "--brief", path.stem, *sets)
    assert r["ok"], r
    j = Path(r["job_dir"])
    brief = (j / "BRIEF.md").read_text(encoding="utf-8")
    left = {m.group(1) for m in PH.finditer(brief)}
    assert left <= RUNTIME, f"content placeholders left unfilled: {left - RUNTIME}"
    job = json.loads((j / "job.json").read_text(encoding="utf-8"))
    assert job["brief"] == brief
    assert r["gates_needed"] == [], "a template job must run with the plain run command"
    assert r["user_run_command"] == f'node "<TK>/runner/deleg.mjs" run "<PROJ>/jobs/{j.name}.job.json"'
    if job.get("workflow"):
        assert (j / "wf" / f"{job['workflow']}.js").exists()
        if path.stem == "chapter-motion":
            assert job["workflow_args"]["chapters"][0]["id"] == "C1", "a JSON var must reach the workflow as a list"
            assert job["collect"] == ["engine/ch/01_a.js"], "a chapter job collects exactly its own chapter files"
            assert job["wire_chapters"] is True and job["queue_group"] == "render" and job["requires"] == ["slop", "render"]
            assert job["workflow_args"]["render_workers"] == 2 and job["workflow_args"]["parallel_chapters"] == 2


# every var a workflow brief fills also reaches the workflow as a lower-case arg; the script must read it (a var the
# script ignores is a silent bug: LEAD_CANON once reached safety-scan.js as lead_canon while the script read canon)
BRIEF_ONLY = {("chapter-motion", "chapters"): None, ("safety-scan", "title"): "the scan never shows the title"}


@pytest.mark.parametrize("path", [p for p in BRIEF_FILES if parse_brief(p)[0].get("defaults", {}).get("workflow")], ids=lambda p: p.stem)
def test_every_brief_var_is_read_by_its_workflow(path):
    meta, body = parse_brief(path)
    src = (WORKFLOWS / f"{meta['defaults']['workflow']}.js").read_text(encoding="utf-8")
    for k in meta["vars"]:
        if not re.search(r"\{\{" + k + r"[|}]", body) or k in RUNTIME:
            continue
        arg = k.lower()
        if (path.stem, arg) in BRIEF_ONLY:
            continue
        assert re.search(r"\bA\." + arg + r"\b", src) or f"A['{arg}']" in src, f"{path.stem}: {{{{{k}}}}} reaches the workflow as '{arg}' but the script never reads A.{arg}"


# ----------------------------------------------------------------------------------------------- workflow scripts
def run_wf(tmp_path, script: str, args: dict, responses: list, default=None) -> dict:
    sc = tmp_path / f"sc-{len(list(tmp_path.glob('sc-*')))}.json"
    sc.write_text(json.dumps({"args": args, "responses": responses, "default": default}), encoding="utf-8")
    r = subprocess.run([NODE, str(HARNESS), str(WORKFLOWS / f"{script}.js"), str(sc)], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["error"] is None, d["error"]
    assert d["issues"] == [], d["issues"]
    return d


def labels(d):
    return [c["label"] for c in d["calls"]]


BASE = {"project_dir": "/home/user/slop/projects/song", "out_dir": "/home/user/slop/projects/song/jobs/j/outbox",
        "toolkit_dir": "/home/user/claudia", "slop": "slop", "title": "Test Song", "duration": 90.5}
CH = [{"id": "C1", "file": "01_a.js", "name": "Arrival", "t0": 0, "t1": 12.5, "shots": ["s001", "s002"]}]
MIN_ARGS = {
    "storyboard": dict(BASE),
    "chapters": dict(BASE, chapters=CH),
    "research-lyrics": dict(BASE, today="2026-10-01", concept="a song about trains"),
    "safety-scan": dict(BASE, list="render/scan-list.json", total=4, slices=2),
}


@pytest.mark.parametrize("path", WF_FILES, ids=lambda p: p.stem)
def test_workflow_script_rules(path, tmp_path):
    src = path.read_text(encoding="utf-8")
    assert src.startswith("export const meta = {"), "a workflow must begin with its meta block"
    for banned in ("Date.now(", "Math.random(", "new Date("):   # calls; prompts may still tell animators not to use them
        assert banned not in src, f"{banned} breaks resume (the runtime forbids it)"
    assert "// args" in src, "document the args under the meta block"
    a = run_wf(tmp_path, path.stem, MIN_ARGS[path.stem], [])
    b = run_wf(tmp_path, path.stem, MIN_ARGS[path.stem], [])
    assert a["meta"]["name"].startswith("slop-") and a["meta"]["phases"]
    assert [(c["label"], c["prompt"]) for c in a["calls"]] == [(c["label"], c["prompt"]) for c in b["calls"]], "prompts must be deterministic (resume cache keys)"
    assert a["result"]["ok"] is False, "with every agent returning nothing the run must fail, never pass"
    for c in a["calls"]:
        assert "/home/user/claudia" in c["prompt"] or path.stem in ("safety-scan",), "agents get pointed at the toolkit docs"
    missing = run_wf(tmp_path, path.stem, {}, [])
    assert missing["result"]["ok"] is False and "missing" in missing["result"]["error"] and missing["calls"] == []
    as_string = run_wf(tmp_path, path.stem, json.dumps(MIN_ARGS[path.stem]), [])   # args sent as a JSON string by mistake
    assert len(as_string["calls"]) == len(a["calls"])


DIRECTOR = {"file": "x.md", "complete": True, "shots": 40, "mean_shot_s": 2.2, "lead_fraction": 0.75, "motion_s": 120, "clips": 20, "hook": "h"}


def score(board, total):
    return {"board": board, "total": total, "hook": 7, "lead_coverage": 7, "lyric_video": 7, "jokes": 7, "taste_fit": 7,
            "feasibility": 7, "arc": 7, "best": ["b"], "fixes": ["f"]}


MERGED = {"storyboard": "a", "shots_json": "b", "shots": 40, "mean_shot_s": 2.2, "lead_fraction": 0.76, "motion_s": 130, "clips": 21, "plates": 35, "summary": "s"}


def audit(ok):
    return {"pass": ok, "audit_output": "PASS" if ok else "FAIL tiling", "numbers": {}, "fixed": [], "remaining": [] if ok else ["gap at 3.0"]}


def test_storyboard_panel_flow(tmp_path):
    args = dict(BASE, banned_words=["foo"], owner_quotes=["make it dense"], lead_min=0.8)
    d = run_wf(tmp_path, "storyboard", args, [
        {"match": "^director:", "value": DIRECTOR},
        {"match": "^judge:1$", "value": {"scores": [score("purist", 70), score("density", 82), score("narrative", 76)]}},
        {"match": "^judge:2$", "value": {"scores": [score("purist", 90)]}},   # partial: void
        {"match": "^judge:3$", "value": None},                               # usage limit
        {"match": "^head-director$", "value": MERGED},
        {"match": "^audit:1$", "value": audit(False)},
        {"match": "^audit:2$", "value": audit(True)},
    ])
    r = d["result"]
    assert r["ok"] is True and r["judges_valid"] == 1 and r["judge_failures"] == 2
    assert r["ranked"] == ["density", "narrative", "purist"]
    assert labels(d) == ["director:purist", "director:density", "director:narrative", "judge:1", "judge:2", "judge:3", "head-director", "audit:1", "audit:2"]
    judge = next(c for c in d["calls"] if c["label"] == "judge:1")
    assert judge["schema"]["properties"]["scores"]["items"]["properties"]["board"]["enum"] == ["purist", "density", "narrative"]
    head = next(c for c in d["calls"] if c["label"] == "head-director")["prompt"]
    assert "density > narrative > purist" in head and '"seedance"' in head and "foo" in head and "make it dense" in head and ">= 0.8" in head
    assert "gap at 3.0" in next(c for c in d["calls"] if c["label"] == "audit:2")["prompt"]
    assert any("judge:3 FAILED" in l for l in d["logs"])


def test_storyboard_fails_loudly(tmp_path):
    few = run_wf(tmp_path, "storyboard", BASE, [{"match": "^director:purist", "value": DIRECTOR}])
    assert few["result"]["ok"] is False and "at least two" in few["result"]["error"] and not any(l.startswith("judge") for l in labels(few))
    nojudge = run_wf(tmp_path, "storyboard", BASE, [{"match": "^director:", "value": DIRECTOR}, {"match": "^head-director$", "value": MERGED},
                                                    {"match": "^audit:", "value": audit(False)}])
    head = next(c for c in nojudge["calls"] if c["label"] == "head-director")["prompt"]
    assert "NO VALID JUDGE SCORES" in head
    assert nojudge["result"]["ok"] is False and "still fails" in nojudge["result"]["error"]
    assert [l for l in labels(nojudge) if l.startswith("audit")] == ["audit:1", "audit:2"]
    off = run_wf(tmp_path, "storyboard", dict(BASE, judges=False), [{"match": "^director:", "value": DIRECTOR}, {"match": "^head-director$", "value": MERGED},
                                                                    {"match": "^audit:", "value": audit(True)}])
    assert off["result"]["ok"] is True and not any(l.startswith("judge") for l in labels(off))


WIRED = "WIRED C1 01_a.js: listed in engine/ch/_index.js, parses, registers scenes, names 2/2 shots"


def review(owner=8, craft=7, sync=7, story=7, fixes=(), gate="20/20 tokens on screen at their time", sheets=24, wired=WIRED):
    return {"owner": owner, "craft": craft, "sync": sync, "story": story, "pass": True, "fixes": list(fixes),
            "checks": {"lyric_gate": gate, "wired": wired, "sheets": sheets, "ms_per_frame": 900}}


BLOCK = {"shot": "s001", "time": 1.0, "severity": "blocking", "problem": "type over her face", "fix": "move it"}
POLISH = {"shot": "s002", "time": 7.0, "severity": "polish", "problem": "a bit busy", "fix": "drop the plot"}
SETUP_OK = {"wired": True, "wire_output": "wired 1 chapter file(s)", "edit_rebuilt": True, "info": "song: 1920x1080", "page_errors": [], "problems": []}


def chapters(tmp_path, responses, wired=True, **extra):
    """the chapters workflow as the runner launches it (wired=True: the runner already wired the chapter files)"""
    return run_wf(tmp_path, "chapters", dict(BASE, chapters=CH, wired=wired, **extra), [{"match": "^animate:", "value": "notes: built"}, *responses],
                  default="applied the fixes")


def test_chapters_null_review_is_a_failure_not_a_pass(tmp_path):
    d = chapters(tmp_path, [])   # every review returns nothing (a usage limit)
    r = d["result"]
    assert r["ok"] is False and r["all_pass"] is False and r["failed"] == ["C1"]
    assert r["chapters"][0]["status"] == "unreviewed" and r["chapters"][0]["verdict"]["valid"] is False
    assert labels(d) == ["animate:C1", "review1:C1", "review1b:C1", "review2:C1", "review2b:C1"], "retry once per round, never fix blind"
    render_less = chapters(tmp_path, [{"match": "^review", "value": review(sheets=0)}])
    assert render_less["result"]["chapters"][0]["status"] == "unreviewed", "a review that looked at no renders is not a review"


def test_chapters_blocking_fix_then_pass(tmp_path):
    d = chapters(tmp_path, [{"match": "^review1:", "value": review(owner=6, fixes=[BLOCK, POLISH])},
                            {"match": "^review2:", "value": review(owner=7, craft=6, sync=6.5, story=7, fixes=[POLISH])}])
    c = d["result"]["chapters"][0]
    assert labels(d) == ["animate:C1", "review1:C1", "fix1:C1", "review2:C1"], "pass in round 2 needs no last fix"
    assert c["status"] == "pass" and c["round"] == 2 and c["verdict"]["reason"] == "no blocking fix left"
    assert c["verdict"]["score"] == round((2 * 7 + 6 + 6.5 + 7) / 5, 1)
    fix1 = next(x for x in d["calls"] if x["label"] == "fix1:C1")["prompt"]
    assert "type over her face" in fix1 and "BLOCKING fix first" in fix1
    assert d["result"]["ok"] is True and d["result"]["all_pass"] is True


def test_chapters_pass_rule(tmp_path):
    first = chapters(tmp_path, [{"match": "^review1:", "value": review(owner=8, fixes=[POLISH])}])
    assert labels(first) == ["animate:C1", "review1:C1"] and first["result"]["chapters"][0]["status"] == "pass"
    gate = chapters(tmp_path, [{"match": "^review", "value": review(gate="130/132 tokens on screen at their time")}])
    assert gate["result"]["chapters"][0]["status"] != "pass" and "lyric gate" in gate["result"]["chapters"][0]["verdict"]["reason"]
    low = chapters(tmp_path, [{"match": "^review", "value": review(owner=6.5)}])
    assert "owner 6.5 < 7" in low["result"]["chapters"][0]["verdict"]["reason"]
    # the shape of the docs' worked example: every score clears the floor, one canon break blocks the chapter
    one_block = chapters(tmp_path, [{"match": "^review", "value": review(owner=7, craft=7, sync=8.5, story=6.5, fixes=[BLOCK] + [POLISH] * 5, gate="lyrics 10/10")}])
    v = one_block["result"]["chapters"][0]["verdict"]
    assert v["valid"] and not v["pass"] and v["blocking"] == 1 and v["polish"] == 5 and v["reason"] == "1 blocking fix(es)"
    unmarked = chapters(tmp_path, [{"match": "^review", "value": review(fixes=[{"shot": "s1", "problem": "p", "fix": "f", "severity": "?"}])}])
    assert unmarked["result"]["chapters"][0]["verdict"]["blocking"] == 1, "an unmarked fix counts as blocking"
    lenient = chapters(tmp_path, [{"match": "^review", "value": review(owner=6.5)}], pass_rule={"min_owner": 6})
    assert lenient["result"]["chapters"][0]["status"] == "pass"


def test_chapters_one_round_refit_and_bad_args(tmp_path):
    one = chapters(tmp_path, [{"match": "^review1:", "value": review(owner=7, fixes=[BLOCK])}], rounds=1)
    c = one["result"]["chapters"][0]
    assert labels(one) == ["animate:C1", "review1:C1", "fix1:C1"] and c["status"] == "fixed-not-rereviewed"
    assert c["open_fixes"] == [BLOCK] and "carry them" in c["open_fixes_note"]
    assert one["result"]["ok"] is True and c["incomplete"] is False, "one planned round: fixed-not-rereviewed is the expected end"
    carried = [dict(BLOCK, problem="rowers copy the lead")]
    refit = run_wf(tmp_path, "chapters", dict(BASE, mode="refit", wired=True, chapters=[dict(CH[0], fixes=carried)]),
                   [{"match": "^setup", "value": SETUP_OK}, {"match": "^animate:", "value": "n"}, {"match": "^review", "value": review()}])
    assert labels(refit)[:2] == ["setup", "animate:C1"], "a refit rebuilds the edit once, before every animator"
    setup = refit["calls"][0]["prompt"]
    assert "render/scratch/chapters/_setup/chapters.json" in setup and "edit edl`, then `" in setup and "edit export" in setup
    anim = refit["calls"][1]["prompt"]
    assert "REFIT" in anim and "rowers copy the lead" in anim and "never rebuild it yourself" in anim
    no_edit = run_wf(tmp_path, "chapters", dict(BASE, mode="refit", wired=True, chapters=CH), [{"match": "^setup", "value": dict(SETUP_OK, edit_rebuilt=False)}])
    assert no_edit["result"]["ok"] is False and "edit was not rebuilt" in no_edit["result"]["error"] and labels(no_edit) == ["setup"]
    bad = run_wf(tmp_path, "chapters", dict(BASE, chapters=[{"id": "C1", "file": "a.js", "t0": 5, "t1": 2, "shots": ["s1"]}]), [])
    assert bad["result"]["ok"] is False and bad["calls"] == []
    nested = run_wf(tmp_path, "chapters", dict(BASE, chapters=[dict(CH[0], file="../engine/x.js")]), [])
    assert nested["result"]["ok"] is False and nested["calls"] == [], "chapter files are plain names inside engine/ch"
    dead = run_wf(tmp_path, "chapters", dict(BASE, chapters=CH, wired=True), [{"match": "^animate:", "value": None}], default="x")
    assert dead["result"]["chapters"][0]["status"] == "animate-failed" and labels(dead) == ["animate:C1"]
    anim_prompt = chapters(tmp_path, [{"match": "^review", "value": review()}])["calls"][0]["prompt"]
    for needle in ("engine/DEVICES.md", "render lyrics --from 0 --to 12.5 --workers 2", "Edit ONLY this file", "within your first ~12 commands", "anabology",
                   "_index.js already loads it", "wire \"/home/user/slop/projects/song\" --check --file 01_a.js --shots s001,s002",
                   "render frames --from 0 --to 12.5 --every 2 --workers 2", "PRODUCTION.md"):
        assert needle in anim_prompt, needle
    assert "edit edl" not in anim_prompt.replace("(edit edl / edit export)", ""), "build-mode animators never rebuild the edit"


def test_chapters_setup_wires_when_the_runner_did_not(tmp_path):
    d = chapters(tmp_path, [{"match": "^setup$", "value": SETUP_OK}, {"match": "^review", "value": review()}], wired=False)
    assert labels(d) == ["setup", "animate:C1", "review1:C1"] and d["result"]["ok"] is True
    setup = d["calls"][0]["prompt"]
    assert 'node "/home/user/claudia/runner/deleg.mjs" wire "/home/user/slop/projects/song" --chapters' in setup and '"file":"01_a.js"' in setup
    failed = chapters(tmp_path, [{"match": "^setup", "value": dict(SETUP_OK, wired=False, wire_output="EACCES")}], wired=False)
    assert failed["result"]["ok"] is False and "not wired" in failed["result"]["error"] and labels(failed) == ["setup"]
    null = chapters(tmp_path, [{"match": "^setup", "value": None}], wired=False)
    assert labels(null) == ["setup", "setup:2"] and null["result"]["ok"] is False and null["result"]["failed"] == ["C1"]
    skipped = chapters(tmp_path, [{"match": "^review", "value": review()}], wired=True)
    assert "setup" not in labels(skipped), "the runner wired the files: no setup agent in build mode"


def test_chapters_not_wired_blocks_the_pass(tmp_path):
    d = chapters(tmp_path, [{"match": "^review", "value": review(wired="NOT WIRED C1 01_a.js: it is still the stub (no scenes yet)")}])
    c = d["result"]["chapters"][0]
    assert c["status"] != "pass" and "not wired" in c["verdict"]["reason"], "a default-renderer pass is never a chapter pass"
    no_check = chapters(tmp_path, [{"match": "^review", "value": review(wired="")}])
    assert no_check["result"]["chapters"][0]["status"] == "unreviewed", "a review that skipped the wiring check is not a review"
    schema = next(x for x in d["calls"] if x["label"] == "review1:C1")["schema"]
    assert "wired" in schema["properties"]["checks"]["required"]


def test_chapters_missing_round2_after_fixes_is_incomplete(tmp_path):
    d = chapters(tmp_path, [{"match": "^review1:", "value": review(owner=6, fixes=[BLOCK])}, {"match": "^review2", "value": None}])
    r, c = d["result"], d["result"]["chapters"][0]
    assert labels(d) == ["animate:C1", "review1:C1", "fix1:C1", "review2:C1", "review2b:C1"]
    assert c["status"] == "fixed-not-rereviewed" and c["incomplete"] is True and "round-2 review" in c["incomplete_why"]
    assert r["ok"] is False and r["incomplete"] == ["C1"] and "resume" in r["error"]
    dead_fix = chapters(tmp_path, [{"match": "^review1:", "value": review(owner=6, fixes=[BLOCK])}, {"match": "^fix1", "value": None}], rounds=1)
    assert dead_fix["result"]["ok"] is False and "last fix returned nothing" in dead_fix["result"]["chapters"][0]["incomplete_why"]


def test_chapters_render_at_most_two_chapters_at_once(tmp_path):
    many = [dict(CH[0], id=f"C{i}", file=f"0{i}_c.js", t0=10 * i, t1=10 * i + 9) for i in range(1, 6)]
    d = run_wf(tmp_path, "chapters", dict(BASE, chapters=many, wired=True), [{"match": "^animate:", "value": "built"}, {"match": "^review", "value": review(owner=6, fixes=[BLOCK])}],
               default="fixed")
    assert d["max_active"] == 2, f"peak agents in flight {d['max_active']} (the reference ran 2; six rendering at once filled the disk)"
    assert sorted(c["chapter"] for c in d["result"]["chapters"]) == [f"C{i}" for i in range(1, 6)]
    one = run_wf(tmp_path, "chapters", dict(BASE, chapters=many, wired=True, parallel_chapters=1, render_workers=1), [{"match": "^animate:", "value": "built"}, {"match": "^review", "value": review()}])
    assert one["max_active"] == 1 and "--workers 1" in one["calls"][0]["prompt"]


ITEMS = {"items": [{"name": f"item{i}", "what": "w", "date": "2026-09", "recognisability": 3 + (i % 3), "lyric_hook": "h", "visual": "v",
                    "sources": ["s"], "confidence": "single-source", "risk": "r"} for i in range(12)], "notes": "n"}


def test_research_lyrics_flow(tmp_path):
    args = dict(BASE, today="2026-10-01", concept="a song about trains", topics=["rail memes", "timetables"], existing_lyrics="/x/old.md",
                banned_words=["foo"], likes=["all aboard"])
    d = run_wf(tmp_path, "research-lyrics", args, [
        {"match": "^research:", "value": ITEMS},
        {"match": "^verify:", "value": {"results": [{"name": "item0", "status": "confirmed", "correct_fact": "c", "sources": ["a", "b"]}]}},
        {"match": "^bank$", "value": "DIGEST"},
        {"match": "^write:", "value": "[Verse 1]\nline"},
        {"match": "^judge:", "value": {"scores": [{"draft": k, "total": 70 + i, "density": 7, "currency": 7, "hook": 7, "wit": 7, "arc": 7,
                                                   "singability": 7, "rules": 10, "best_lines": [], "worst_lines": []}
                                                  for i, k in enumerate(["density", "tension", "hook", "format"])]}},
        {"match": "^merge$", "value": "SUNO BLOCK"},
        {"match": "^critic$", "value": {"pass": True, "lint": "0 errors", "bars": 72, "changed": [], "risks": []}},
    ])
    r = d["result"]
    assert r["ok"] is True and r["judges_valid"] == 3 and r["counts"]["sweeps"] == 4
    research = [l for l in labels(d) if l.startswith("research:")]
    assert research == ["research:rail-memes", "research:timetables", "research:quotes", "research:factcheck-old"]
    assert len([l for l in labels(d) if l.startswith("verify:")]) == math.ceil(48 / 10)
    critic = next(c for c in d["calls"] if c["label"] == "critic")["prompt"]
    assert '`slop --json lyrics lint /home/user/slop/projects/song/jobs/j/outbox/lyrics/lyrics.txt --ban "foo"`' in critic, "--json is a root flag"
    merge = next(c for c in d["calls"] if c["label"] == "merge")["prompt"]
    assert "display.txt" in merge and "TEXT|n" in merge and "2026-10-01" in merge


def test_research_lyrics_fails_loudly(tmp_path):
    args = dict(BASE, today="2026-10-01", concept="c", topics=["a", "b", "c"])
    d = run_wf(tmp_path, "research-lyrics", args, [{"match": "^research:a$", "value": ITEMS}])
    assert d["result"]["ok"] is False and "sweeps" in d["result"]["error"] and not any(l.startswith("verify") for l in labels(d))
    nodate = run_wf(tmp_path, "research-lyrics", dict(BASE, concept="c"), [])
    assert nodate["result"]["ok"] is False and "today" in nodate["result"]["error"]


SCAN = {"findings": [{"clip": "M1", "time": 1.2, "severity": "block", "kind": "text", "what": "readable sign"}], "checked": ["M1", "M2"], "given": 2}


def test_safety_scan_counts_every_take(tmp_path):
    args = dict(BASE, list="render/scan-list.json", total=4, slices=2, fix_rules=["the crew copies the lead"])
    ok = run_wf(tmp_path, "safety-scan", args, [{"match": "^scan:", "value": SCAN}])
    assert ok["result"]["ok"] is True and ok["result"]["counts"]["block"] == 2 and ok["result"]["checked"] == 4
    p0 = ok["calls"][0]["prompt"]
    assert "/home/user/slop/projects/song/render/scan-list.json" in p0 and "[0:2]" in p0 and "the crew copies the lead" in p0
    half = run_wf(tmp_path, "safety-scan", args, [{"match": "^scan:0$", "value": SCAN}])
    assert half["result"]["ok"] is False and half["result"]["unchecked"][0]["slice"] == 1
    short = run_wf(tmp_path, "safety-scan", args, [{"match": "^scan:", "value": dict(SCAN, checked=["M1"])}])
    assert short["result"]["ok"] is False
    # 7 takes over 6 asked slices: slices of 2 take 4 agents, none of them idle with an empty slice
    seven = run_wf(tmp_path, "safety-scan", dict(BASE, list="render/scan-list.json", total=7, slices=6, lead_canon="a grey coat, a red scarf"),
                   [{"match": "^scan:[0-2]$", "value": dict(SCAN, checked=["a", "b"])}, {"match": "^scan:3$", "value": dict(SCAN, checked=["g"])}])
    assert labels(seven) == ["scan:0", "scan:1", "scan:2", "scan:3"] and seven["result"]["ok"] is True and seven["result"]["checked"] == 7
    assert "[6:8]" in seven["calls"][3]["prompt"] and "entries 6 to 6" in seven["calls"][3]["prompt"]
    assert "a grey coat, a red scarf" in seven["calls"][0]["prompt"], "the brief's LEAD_CANON reaches the scan as lead_canon"


def test_preflight_workflow_script(tmp_path):
    sc = tmp_path / "pf.json"
    for args, value, ok in (({"dir": "C:/Users/x/job/outbox"}, "DONE", True), ({"dir": "/tmp/o"}, None, False), ({}, None, False)):
        sc.write_text(json.dumps({"args": args, "responses": [{"match": "^probe$", "value": value}]}), encoding="utf-8")
        r = subprocess.run([NODE, str(HARNESS), str(PREFLIGHT_WF), str(sc)], capture_output=True, text=True, timeout=60, encoding="utf-8")
        d = json.loads(r.stdout)
        assert d["error"] is None and d["issues"] == [] and d["result"]["ok"] is ok
        if args:
            p = d["calls"][0]["prompt"]
            assert f"{args['dir']}/probe-bash.txt" in p and f"{args['dir']}/probe-write.txt" in p and "Bash tool" in p and "Write tool" in p


# ------------------------------------------------------------------------------- every command a worker is told to run
SENTINEL = "SLOPCLI"
SUBCMDS = ("render", "board", "lyrics", "edit", "audio", "song", "analyze", "clip", "gen", "taste", "plates")   # not status/list: runner verbs too


def _fill_brief(body: str, meta: dict) -> str:
    vals = {"SLOP": SENTINEL, "PROJECT_DIR": "/p/song", "TOOLKIT_DIR": "/tk", "OUTBOX": "/p/song/jobs/j/outbox", "JOB_DIR": "/p/song/jobs/j",
            "JOB_ID": "j", "ENGINE": "claude", "WORKFLOW_PATH": "/p/song/jobs/j/wf/x.js", "WORKFLOW_ARGS": "{}", "T0": "1.5", "T1": "9.25"}
    return PH.sub(lambda m: vals.get(m.group(1), m.group(2) if m.group(2) is not None else "value"), body)


def _placeholder(m: re.Match) -> str:
    inner = m.group(1).lower()
    if ":" in inner:
        return "1:2,3:4"
    if inner in ("t0", "a"):
        return "1"
    if inner in ("t1", "b"):
        return "2"
    if "," in inner or "second" in inner or "…" in inner:
        return "1,2"
    return "x"


def _commands(text: str) -> list[str]:
    """`…` spans and 4-space-indented lines that start with the CLI (or a bare slop subcommand), as single lines"""
    out = []
    for span in re.findall(r"`([^`]+)`", text, re.S):
        s = re.sub(r"\s+", " ", span).strip()
        if s.startswith(SENTINEL + " ") or s.startswith("slop ") or s.split(" ")[0] in SUBCMDS and len(s.split(" ")) > 1:
            out.append(s)
    for line in text.splitlines():
        if line.startswith("    ") and line.strip().startswith((SENTINEL + " ", "slop ")):
            out.append(re.split(r"\s{2,}|\s->", line.strip())[0])
    return out


def _argv(cmd: str) -> list[str]:
    cmd = re.sub(r"<([^<>]+)>", _placeholder, cmd).replace("…", "1")
    toks = shlex.split(cmd)
    if toks and toks[0] in (SENTINEL, "slop"):
        toks = toks[1:]
    return toks


def test_every_slop_command_in_the_templates_parses():
    pytest.importorskip("slop.cli")
    from slop.cli import build_parser
    ap = build_parser()
    texts = {}
    for p in BRIEF_FILES:
        meta, body = parse_brief(p)
        texts[p.name] = _fill_brief(body, meta)
    texts["runner/README.md"] = (ROOT / "runner" / "README.md").read_text(encoding="utf-8")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for script, args in MIN_ARGS.items():
            for extra in ({}, {"mode": "refit", "banned_words": ["foo"]}):
                sc = Path(td) / "sc.json"
                sc.write_text(json.dumps({"args": dict(args, slop=SENTINEL, **extra), "responses": [], "default": None}), encoding="utf-8")
                r = subprocess.run([NODE, str(HARNESS), str(WORKFLOWS / f"{script}.js"), str(sc)], capture_output=True, text=True, timeout=60, encoding="utf-8")
                calls = json.loads(r.stdout)["calls"]
                if script == "chapters":   # the later stages only run past setup/animate: render them with canned answers
                    sc.write_text(json.dumps({"args": dict(args, slop=SENTINEL, wired=True, **extra),
                                              "responses": [{"match": "^setup", "value": SETUP_OK}, {"match": "^animate", "value": "n"}, {"match": "^review1:", "value": review(owner=5, fixes=[BLOCK])}],
                                              "default": None}), encoding="utf-8")
                    r = subprocess.run([NODE, str(HARNESS), str(WORKFLOWS / f"{script}.js"), str(sc)], capture_output=True, text=True, timeout=60, encoding="utf-8")
                    calls += json.loads(r.stdout)["calls"]
                texts[f"{script}.js {extra}"] = "\n".join(c["prompt"] for c in calls)
    checked, bad = 0, []
    for name, text in texts.items():
        for cmd in _commands(text):
            argv = _argv(cmd)
            if argv and argv[-1] == "--help":
                argv = argv[:-1]
            if not argv:
                continue
            try:
                ap.parse_args(argv)
                checked += 1
            except SystemExit:
                bad.append(f"{name}: {cmd!r} -> slop {' '.join(argv)}")
    assert not bad, "commands the CLI rejects:\n" + "\n".join(bad)
    assert checked >= 30, f"only {checked} commands found: the extraction is broken"


def test_every_runner_verb_in_the_docs_exists():
    verbs = {"new", "run", "start", "status", "wait", "stop", "resume", "list", "wire", "pack", "unpack", "templates", "doctor",
             "selftest", "preflight", "version", "help"}
    for p in [*BRIEF_FILES, *WF_FILES, ROOT / "runner" / "README.md"]:
        for v in re.findall(r"deleg\.mjs\"? (\w[\w-]*)", p.read_text(encoding="utf-8")):
            assert v in verbs, f"{p.name}: deleg.mjs {v} is not a runner command"


# ------------------------------------------------------------------------------------------------------------ scrub
def _shipped_files():
    out = [*ROOT.joinpath("runner").rglob("*"), *BRIEFS.rglob("*"), *WORKFLOWS.rglob("*"), *ROOT.joinpath("tests", "fixtures", "deleg").rglob("*"),
           *ROOT.joinpath("tests").glob("test_deleg*.py")]
    return [p for p in out if p.is_file() and "__pycache__" not in p.parts]


def test_nothing_shipped_leaks_identity_hosts_or_codes():
    """No private word (hashed list + scanner: tests/scrublist.py) and no hard-coded --profile code."""
    import scrublist
    for p in _shipped_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        hits = scrublist.private_hits(text)
        assert not hits, f"{p.relative_to(ROOT)}: {hits}"
        assert not re.search(r"--profile\s+[a-z0-9]{6,}", text), f"{p.relative_to(ROOT)} hard-codes a --profile code"


ID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|\bwf_[0-9a-z-]{6,}\b|\b[0-9a-f]{12,}\b", re.I)


def test_no_ids_copied_from_the_research():
    """Session, thread, run and job ids in fixtures are synthetic: none may come from the research notes (they are the
    owner's real sessions). Checked against ../research when that folder is present (it is not shipped)."""
    research = ROOT.parent / "research"
    if not research.is_dir():
        pytest.skip("research notes not present (only the build checkout has them)")
    real = set()
    for f in research.rglob("*.md"):
        real |= {m.group(0).lower() for m in ID_RE.finditer(f.read_text(encoding="utf-8", errors="replace"))}
    for p in _shipped_files():
        found = {m.group(0).lower() for m in ID_RE.finditer(p.read_text(encoding="utf-8", errors="replace"))}
        leaked = sorted(found & real)
        assert not leaked, f"{p.relative_to(ROOT)} contains ids copied from the research: {leaked}"
