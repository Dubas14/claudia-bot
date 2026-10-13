"""Identity anchor for API stills and Grok-named ingest (QUICK-E2E defect 3).

`slop gen image --ref PLATE[:K]` and a jobs.json job's "refs" send the picked candidate as input_references (refused
when the registry says the model takes none); `slop plates book --anchor PLATE[:K]` writes the approved lead image into
every lead plate's API job and records it in jobs.json; `slop plates ingest DIR` takes Grok GenerateImage outputs named
<plate>-<k>.png or <plate>/<k>.png. Every HTTP call is mocked: nothing here spends.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))
_H = ROOT / "tests" / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

import board_synth as synth  # noqa: E402
from slop import ledger  # noqa: E402
from slop.board import draft, plates  # noqa: E402
from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.gen import images  # noqa: E402

KEY = "sk-or-v1-test-not-a-real-key"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SLOP_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    H.write_cache(tmp_path / "home")                       # the model registry, offline
    return tmp_path


@pytest.fixture
def env(home):
    return H.make_project(home / "projects", audio=False)  # hero-cu #1 (picked) / #2, hall #1 (picked)


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


def images_ok(method, url, body):
    n = int(body.get("n") or 1)
    return H.FakeResp(200, {"data": [{"b64_json": H.b64(H.png_bytes((10 * i, 20, 30))), "media_type": "image/png"}
                                     for i in range(n)], "usage": {"cost": round(.004 * n, 6)}})


def sent_image(body: dict, i: int = 0) -> bytes:
    url = body["input_references"][i]["image_url"]["url"]
    assert url.startswith("data:image/") and body["input_references"][i]["type"] == "image_url"
    return base64.b64decode(url.split(",", 1)[1])


# ------------------------------------------------------------------------------------------------ gen image --ref
def test_ref_plate_k_sends_that_candidate(env, monkeypatch):
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "wide shot of {lead} on a roof", "--plate", "roof", "--ref", "hero-cu:2",
                  "--quality", "low")
    assert rc == 0, out
    body = s.calls[0]["body"]
    assert len(body["input_references"]) == 1
    assert sent_image(body) == (env / "plates/cands/hero-cu/2.png").read_bytes()
    assert out["refs"] == ["plates/cands/hero-cu/2.png"]
    side = json.loads((env / "plates/cands/roof/1.json").read_text())
    assert side["refs"] == ["plates/cands/hero-cu/2.png"] and side["ref_plates"] == ["hero-cu:2"]
    assert ledger.rows(env)[-1]["units"]["refs"] == 1


@pytest.mark.parametrize("ref,cand", [("hero-cu", "1"), ("hero-cu#2", "2"), ("hero-cu~2", "2")])
def test_ref_forms_pick_hash_and_variant(env, monkeypatch, ref, cand):
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", ref)
    assert rc == 0, out
    assert sent_image(s.calls[0]["body"]) == (env / f"plates/cands/hero-cu/{cand}.png").read_bytes()


def test_ref_files_and_duplicates(env, monkeypatch, tmp_path):
    f = H.write_png(tmp_path / "face.png", (1, 2, 3))
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", str(f), "--ref", "plates/cands/hero-cu/1.png",
                  "--ref", "hero-cu:1")                            # the same image twice: sent once
    assert rc == 0, out
    body = s.calls[0]["body"]
    assert len(body["input_references"]) == 2 and sent_image(body) == f.read_bytes()
    assert out["refs"][1] == "plates/cands/hero-cu/1.png"


def test_bad_refs_are_refused_before_any_call(env, monkeypatch):
    s = fake(monkeypatch, {})                                      # any request would fail the test
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", "hero-cu:9")
    assert rc == 1 and "no candidate #9" in out["error"] and "#1, #2" in out["error"]
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", "nothing-here")
    assert rc == 1 and "no candidates" in out["error"] and "PLATE[:K]" in out["error"]
    H.write_png(env / "plates/cands/roof2/1.png")
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", "roof2")
    assert rc == 1 and "no pick yet" in out["error"] and "plates pick roof2 K" in out["error"]
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", "C:/no/such/face.png")
    assert rc == 1 and "no such image file" in out["error"]
    assert not s.calls and not ledger.rows(env)


def test_models_without_reference_support_are_refused(env, monkeypatch):
    s = fake(monkeypatch, {})
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", "hero-cu:2", "--model", "recraft/recraft-v4.1-flash")
    assert rc == 1 and "takes no reference images" in out["error"] and "nothing was spent" in out["error"]
    assert "gen models --kind image" in out["error"] and "openai/gpt-image-2" in out["error"]
    refs = ["hero-cu:1", "hero-cu:2", "hall:1", "plates/cands/hall/1.png"]
    H.write_png(env / "plates/cands/hall/2.png", (5, 5, 5))
    refs[-1] = "hall:2"
    argv = [x for r in refs for x in ("--ref", r)]
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", *argv, "--model", "x-ai/grok-imagine-image-2.0")
    assert rc == 1 and "at most 3 reference image(s)" in out["error"]
    assert not s.calls and not ledger.rows(env)
    assert images.refs_max("openai/gpt-image-2") == 16 and images.refs_max("recraft/recraft-v4.1-flash") == 0
    assert images.refs_max("no/such-model") is None                # unknown: the provider decides


# ------------------------------------------------------------------------------------------------ jobs "refs"
def write_jobs(pdir: Path, jobs: list[dict]) -> Path:
    p = pdir / "plates" / "jobs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    return p


JOBS = [{"plate": "roof", "prompt": "Wide shot of the lead on a rooftop, illustrated. No text.", "n": 1,
         "refs": ["hero-cu:2"], "anchor": "hero-cu:2"},
        {"plate": "street", "prompt": "An empty wet street at night, illustrated. No text.", "n": 1}]


def test_job_refs_go_into_each_request_body(env, monkeypatch):
    write_jobs(env, JOBS)
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, dry = run(env, "gen", "image", "--jobs", "--quality", "low")
    assert rc == 0 and dry["dry_run"] and not s.calls
    roof = next(j for j in dry["jobs"] if j["plate"] == "roof")
    assert roof["refs"] == ["plates/cands/hero-cu/2.png"] and roof["anchor"] == "hero-cu:2" and "ref_src" not in roof
    assert "+ 1 ref(s) (anchored on hero-cu:2)" in dry["text"] and "lead anchor: 1 plate(s)" in dry["text"]
    assert dry["anchored"] == ["roof"]
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--yes", "--workers", "1")
    assert rc == 0, out
    by = {("rooftop" in c["body"]["prompt"]): c["body"] for c in s.calls}
    assert sent_image(by[True]) == (env / "plates/cands/hero-cu/2.png").read_bytes()
    assert "input_references" not in by[False]                     # a job without refs sends none
    assert all("ref_src" not in r for r in out["results"])
    # the batch's --ref is added to every job (a job's own refs first, the same image never twice)
    rc, out = run(env, "gen", "image", "--jobs", "--quality", "low", "--ref", "hall", "--ref", "hero-cu:2")
    rows = {j["plate"]: j for j in out["jobs"]}
    assert rows["roof"]["refs"] == ["plates/cands/hero-cu/2.png", "plates/cands/hall/1.png"]
    assert rows["street"]["refs"] == ["plates/cands/hall/1.png", "plates/cands/hero-cu/2.png"]
    assert "--ref hall --ref hero-cu:2 --yes" in out["text"]       # the command to run keeps the references


def test_resume_counts_only_images_made_with_the_same_refs(env, monkeypatch):
    plain = [{**JOBS[0], "refs": None}]
    plain[0].pop("anchor")
    write_jobs(env, plain)
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    assert run(env, "gen", "image", "--jobs", "--yes")[0] == 0 and len(s.calls) == 1
    write_jobs(env, [JOBS[0]])                                     # now anchored: the unanchored image does not count
    rc, out = run(env, "gen", "image", "--jobs")
    assert rc == 0 and out["planned_images"] == 1 and "1 made at other settings, not counted" in out["text"]
    assert run(env, "gen", "image", "--jobs", "--yes")[0] == 0 and len(s.calls) == 2
    rc, out = run(env, "gen", "image", "--jobs", "--yes")
    assert "nothing to do" in out["text"] and len(s.calls) == 2


def test_job_refs_on_a_model_without_support_or_missing_files(env, monkeypatch):
    s = fake(monkeypatch, {})
    write_jobs(env, [{**JOBS[0], "model": "recraft/recraft-v4.1-flash"}])
    rc, out = run(env, "gen", "image", "--jobs")
    assert rc == 1 and "job roof (anchored on hero-cu:2)" in out["error"] and "takes no reference images" in out["error"]
    write_jobs(env, [{**JOBS[0], "refs": ["plates/cands/hero-cu/7.jpg"]}])
    rc, out = run(env, "gen", "image", "--jobs")
    assert rc == 1 and "job roof" in out["error"] and "plates book --anchor PLATE:K" in out["error"]
    write_jobs(env, [{**JOBS[1], "refs": "hero-cu:2"}])
    rc, out = run(env, "gen", "image", "--jobs")
    assert rc == 1 and "must be a list" in out["error"]
    # --only skips the broken job: its refs are not even resolved
    write_jobs(env, [{**JOBS[0], "refs": ["gone:1"]}, JOBS[1]])
    rc, out = run(env, "gen", "image", "--jobs", "--only", "street")
    assert rc == 0 and out["planned_images"] == 1
    assert not s.calls


# ------------------------------------------------------------------------------------------------ plates book --anchor
def quick_board(home):
    p = synth.make_project(home / "projects", tier="quick")
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    (p / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    entries = plates.plate_entries(S, synth.load(p, "project.json"))
    lead = [e["plate"] for e in entries if e["lead"]]
    other = [e["plate"] for e in entries if not e["lead"]]
    return p, lead, other


def test_book_anchor_needs_the_owners_pick_and_writes_every_lead_job(home, monkeypatch):
    p, lead, other = quick_board(home)
    anchor = lead[0]
    for k in (1, 2, 3):
        synth.make_image(home / "dl" / f"{anchor}-{k}.png", 160, 90, seed=k)
    plates.ingest(p, str(home / "dl"))
    with pytest.raises(SlopError, match="no pick yet") as e:
        plates.book(p, anchor=anchor)
    assert f"plates pick {anchor} K" in str(e.value) and not (p / "plates/jobs.json").exists()
    with pytest.raises(SlopError, match="PLATE or PLATE:K"):
        plates.book(p, anchor="no good/ref")
    plates.pick(p, [anchor, "2"])
    r = plates.book(p, anchor=anchor)
    doc = synth.load(p, "plates/jobs.json")
    f = f"plates/cands/{anchor}/2.jpg"
    assert doc["anchor"]["ref"] == f"{anchor}:2" and doc["anchor"]["file"] == f and doc["anchor"]["k"] == 2
    assert doc["anchored"] == sorted(set(lead) - {anchor}) == r["anchored"] == doc["anchor"]["plates"]
    jobs = {j["plate"]: j for j in doc["jobs"]}
    for k in lead[1:]:
        assert jobs[k]["refs"] == [f] and jobs[k]["anchor"] == f"{anchor}:2"
        assert jobs[k]["cmd"].endswith(f" --ref {anchor}:2")
    for k in other + [anchor]:
        assert "refs" not in jobs[k] and "anchor" not in jobs[k] and "--ref" not in jobs[k]["cmd"]
    assert f"lead anchor {anchor}:2" in r["text"] and "--missing" in r["text"]
    md = (p / "plates/prompts.md").read_text(encoding="utf-8")
    assert "**Lead anchor:**" in md and f"anchored on {anchor}:2" in md
    dec = p / "DECISIONS.md"
    assert dec.is_file() and f"lead identity anchor {anchor}:2" in dec.read_text(encoding="utf-8")
    # sticky: a later book (a subset too) keeps the anchor on every lead job
    r = plates.book(p, only=[lead[1]], batch="b02")
    doc = synth.load(p, "plates/jobs.json")
    assert doc["anchor"]["ref"] == f"{anchor}:2" and doc["anchored"] == sorted(set(lead) - {anchor})
    assert any("kept from plates/jobs.json" in n for n in r["anchor_notes"])
    # another candidate than the pick: allowed, with a note; the old anchor's refs and --ref go
    r = plates.book(p, anchor=f"{anchor}:3")
    jobs = {j["plate"]: j for j in synth.load(p, "plates/jobs.json")["jobs"]}
    assert jobs[lead[1]]["refs"] == [f"plates/cands/{anchor}/3.jpg"]
    assert jobs[lead[1]]["cmd"].count("--ref") == 1 and jobs[lead[1]]["cmd"].endswith(f"--ref {anchor}:3")
    assert any("not its pick #2" in n for n in r["anchor_notes"])
    # --no-anchor drops it everywhere
    r = plates.book(p, no_anchor=True)
    doc = synth.load(p, "plates/jobs.json")
    assert "anchor" not in doc and doc["anchored"] == [] and not r["anchored"]
    assert all("refs" not in j and "--ref" not in j["cmd"] for j in doc["jobs"])
    with pytest.raises(SlopError, match="give one of them"):
        plates.book(p, anchor=anchor, no_anchor=True)


def test_book_anchor_refused_for_a_model_without_references(home):
    p, lead, _ = quick_board(home)
    synth.make_image(home / "dl" / f"{lead[0]}-1.png", 160, 90)
    plates.ingest(p, str(home / "dl"))
    plates.pick(p, [lead[0], "1"])
    proj = synth.load(p, "project.json")
    proj["models"]["image"] = "recraft/recraft-v4.1-flash"
    (p / "project.json").write_text(json.dumps(proj), encoding="utf-8")
    with pytest.raises(SlopError, match="takes no reference images") as e:
        plates.book(p, anchor=lead[0])
    assert "or book without --anchor" in str(e.value) and not (p / "plates/jobs.json").exists()
    proj["models"]["image"] = "openai/gpt-image-2"
    (p / "project.json").write_text(json.dumps(proj), encoding="utf-8")
    plates.book(p, anchor=lead[0])
    proj["models"]["image"] = "recraft/recraft-v4.1-flash"
    (p / "project.json").write_text(json.dumps(proj), encoding="utf-8")
    with pytest.raises(SlopError, match="--no-anchor"):            # the sticky anchor names its own way out
        plates.book(p)


def test_book_anchor_stays_local_without_a_cached_registry(home, monkeypatch):
    p, lead, _ = quick_board(home)
    synth.make_image(home / "dl" / f"{lead[0]}-1.png", 160, 90)
    plates.ingest(p, str(home / "dl"))
    plates.pick(p, [lead[0], "1"])
    monkeypatch.setenv("SLOP_HOME", str(home / "empty-home"))      # no model listing cached
    s = fake(monkeypatch, {})                                      # any request would fail the test
    r = plates.book(p, anchor=lead[0])
    assert r["anchored"] and not s.calls


def test_anchored_book_to_batch_request_bodies(home, monkeypatch):
    """the whole path: book --anchor through the CLI, then the batch sends the anchor with every lead plate only."""
    p, lead, other = quick_board(home)
    anchor = lead[0]
    synth.make_image(home / "dl" / f"{anchor}-1.png", 160, 90, seed=3)
    plates.ingest(p, str(home / "dl"))
    plates.pick(p, [anchor, "1"])
    rc, out = run(p, "plates", "book", "--anchor", anchor)
    assert rc == 0, out
    assert out["anchor"]["ref"] == f"{anchor}:1" and out["anchored"]
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    picked = (p / f"plates/cands/{anchor}/1.jpg").read_bytes()
    rc, out = run(p, "gen", "image", "--jobs", "--quality", "low", "--only", ",".join(lead[1:3] + other[:2]), "--yes",
                  "--workers", "1")
    assert rc == 0, out
    assert len(s.calls) == 4
    plate_of = {j["prompt"]: j["plate"] for j in synth.load(p, "plates/jobs.json")["jobs"]}
    assert sorted(plate_of[c["body"]["prompt"]] for c in s.calls) == sorted(lead[1:3] + other[:2])
    for c in s.calls:
        plate = plate_of[c["body"]["prompt"]]
        if plate in lead:
            assert len(c["body"]["input_references"]) == 1 and sent_image(c["body"]) == picked
        else:
            assert "input_references" not in c["body"]
    for k in lead[1:3]:
        side = json.loads(next((p / "plates/cands" / k).glob("*.json")).read_text())
        assert side["refs"] == [f"plates/cands/{anchor}/1.jpg"] and side["ref_plates"] == [f"{anchor}:1"]


# ------------------------------------------------------------------------------------------------ ingest (Grok names)
def test_ingest_grok_outputs_by_plate_name_and_folder(home):
    p, lead, other = quick_board(home)
    a, b, c = lead[0], lead[1], other[0]
    g = home / "grok"
    synth.make_image(g / f"{a}-1.png", 1024, 576, seed=1)            # <plate>-<k>.png
    synth.make_image(g / f"{a.upper()}-2.jpg", 1024, 576, seed=2)    # any case
    synth.make_image(g / b / "3.png", 1024, 576, seed=3)             # <plate>/<k>.png keeps k
    synth.make_image(g / "x_some_prompt_words_77.png", 1024, 576, seed=4)   # not a plate name: unmatched
    r = plates.ingest(p, str(g))
    assert {k: sorted(v) for k, v in r["added"].items()} == {a: [1, 2], b: [3]}
    assert r["unmatched_files"] == ["x_some_prompt_words_77.png"]
    assert not r["sd_size"] and "SD size" not in r["text"]         # an API/Grok size is the model's, not MJ's HD
    idx = synth.load(p, "plates/cands/index.json")
    assert idx[b]["3"]["orig"].endswith(f"{b}-3.png")             # "3.png" alone would say nothing
    # DIR = the plate's own folder
    synth.make_image(home / "grok2" / c / "1.png", 1024, 576, seed=5)
    synth.make_image(home / "grok2" / c / "2.png", 1024, 576, seed=6)
    r = plates.ingest(p, str(home / "grok2" / c))
    assert r["added"] == {c: [1, 2]}
    # a number an API generation already claimed (its sidecar) is never reused
    (p / "plates/cands" / c / "3.json").write_text("{}", encoding="utf-8")
    synth.make_image(home / "grok3" / f"{c}-3.png", 1024, 576, seed=7)
    r = plates.ingest(p, str(home / "grok3"))
    assert r["added"] == {c: [4]} and (p / "plates/cands" / c / "3.json").is_file()
    with pytest.raises(SlopError, match="the candidates themselves"):
        plates.ingest(p, str(p / "plates/cands" / c))


def test_ingest_grok_names_before_a_board_exists(home):
    p = synth.make_project(home / "projects", name="early", tier="quick")    # no board/shots.json, no batch
    g = home / "lead-tests"
    synth.make_image(g / "lead-cu-1.png", 1024, 576, seed=1)
    synth.make_image(g / "lead-cu-2.png", 1024, 576, seed=2)
    synth.make_image(g / "lead-ws" / "1.png", 1024, 576, seed=3)
    synth.make_image(g / "someuser_a_woman_in_a_hall_ab12cd_1.png", 1024, 576, seed=4)    # MJ-style: never a plate
    r = plates.ingest(p, str(g))
    assert {k: sorted(v) for k, v in r["added"].items()} == {"lead-cu": [1, 2], "lead-ws": [1]}
    assert r["unmatched_files"] == ["someuser_a_woman_in_a_hall_ab12cd_1.png"]
    # a zip's top-level "1.png" never makes a plate of the temporary folder
    z = home / "dl.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(g / "lead-cu-1.png", "1.png")
    r = plates.ingest(p, str(z))
    assert not r["added"] and r["unmatched_files"] == ["1.png"]
    plates.pick(p, ["lead-cu", "2"])
    assert images.resolve_ref(p, "lead-cu")["id"] == "plates/cands/lead-cu/2.jpg"


# ------------------------------------------------------------------------------------------------ review fixes
def test_url_refs_survive_the_cli_path_helper(env, monkeypatch):
    """`gen image --ref https://…` goes through the CLI's input-path helper, which collapses '//' (https:/host/…):
    the URL is repaired, sent as is, and the sidecar keeps it without its query (signed links carry tokens)."""
    assert images.resolve_ref(env, "https:/example.com/a.png")["src"] == "https://example.com/a.png"
    assert images.resolve_ref(env, r"https:\\cdn.example.com\x\a.png")["src"] == "https://cdn.example.com/x/a.png"
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "x", "--plate", "roof", "--ref", "https://cdn.example.com/a.png?Signature=abc")
    assert rc == 0, out
    assert s.calls[0]["body"]["input_references"][0]["image_url"]["url"] == "https://cdn.example.com/a.png?Signature=abc"
    side = json.loads((env / "plates/cands/roof/1.json").read_text())
    assert side["refs"] == ["https://cdn.example.com/a.png"]
    write_jobs(env, [JOBS[1]])
    rc, out = run(env, "gen", "image", "--jobs", "--ref", "https://cdn.example.com/b.png", "--ref",
                  str(env / "plates/cands/hero-cu/1.png"))
    assert rc == 0 and out["jobs"][0]["refs"] == ["https://cdn.example.com/b.png", "plates/cands/hero-cu/1.png"]
    assert "--ref https://cdn.example.com/b.png --ref plates/cands/hero-cu/1.png --yes" in out["text"]


def test_job_refs_are_the_projects_files_whatever_the_current_folder(env, monkeypatch, tmp_path):
    """jobs.json refs are project-relative: run from another project's folder (which has its own
    plates/cands/hero-cu/2.png), the batch still sends THIS project's image."""
    other = tmp_path / "elsewhere"
    H.write_png(other / "plates/cands/hero-cu/2.png", (9, 9, 9))
    monkeypatch.chdir(other)
    write_jobs(env, [{**JOBS[0], "refs": ["plates/cands/hero-cu/2.png"]}])
    s = fake(monkeypatch, {("POST", "/images"): images_ok})
    rc, out = run(env, "gen", "image", "--jobs", "--yes", "--workers", "1")
    assert rc == 0, out
    assert sent_image(s.calls[0]["body"]) == (env / "plates/cands/hero-cu/2.png").read_bytes()
    assert out["jobs"][0]["refs"] == ["plates/cands/hero-cu/2.png"]


def test_refs_max_reads_the_listing_shapes(monkeypatch):
    rec = {"endpoints": [{"supported_parameters": {"input_references": {"type": "range", "min": 0, "max": 0}}}]}
    monkeypatch.setattr(images.reg, "find", lambda kind, m, **k: rec)
    assert images.refs_max("m") == 0
    rec["endpoints"] = [{"supported_parameters": {"input_references": {"type": "boolean"}}}]
    assert images.refs_max("m") is None                            # listed without a max: it takes some
    rec["endpoints"] = [{"supported_parameters": {"seed": {}}}]
    assert images.refs_max("m") == 0                               # parameters listed, references not among them
    rec["endpoints"] = [{"supported_parameters": {"input_references": {"max": 14}}},
                        {"supported_parameters": {"input_references": {"max": 3}}}]
    assert images.refs_max("m") == 3


def test_candidate_refs_with_upper_case_extensions(env):
    (env / "plates/cands/roof2").mkdir(parents=True)
    H.write_png(env / "plates/cands/roof2/3.PNG")
    assert images.resolve_ref(env, "roof2:3")["src"].endswith("3.PNG")
    with pytest.raises(SlopError, match="no such image file"):
        images.resolve_ref(env, "face.png")


def test_sticky_anchor_notes_a_changed_pick_and_drops_are_logged(home):
    p, lead, _ = quick_board(home)
    a = lead[0]
    for k in (1, 2, 3):
        synth.make_image(home / "dl" / f"{a}-{k}.png", 160, 90, seed=k)
    plates.ingest(p, str(home / "dl"))
    plates.pick(p, [a, "2"])
    plates.book(p, anchor=a)
    plates.pick(p, [a, "3"])                                       # the owner changed their mind after the book
    r = plates.book(p)
    assert synth.load(p, "plates/jobs.json")["anchor"]["ref"] == f"{a}:2"
    assert any(f"pick of {a} is now #3, the anchor is still #2" in n and f"plates book --anchor {a}" in n
               for n in r["anchor_notes"])
    r = plates.book(p, anchor=f"{a}~1")                            # a variant key names its candidate, like --ref
    assert r["anchor"]["ref"] == f"{a}:1"
    plates.book(p, no_anchor=True)
    dec = (p / "DECISIONS.md").read_text(encoding="utf-8")
    assert f"lead identity anchor {a}:1" in dec and f"lead identity anchor {a}:1 dropped (--no-anchor)" in dec


def test_ingest_refuses_the_candidates_and_the_folders_that_hold_them(home):
    p, lead, other = quick_board(home)
    synth.make_image(home / "dl" / f"{lead[0]}-1.png", 160, 90)
    plates.ingest(p, str(home / "dl"))
    for src in (p / "plates", p):
        with pytest.raises(SlopError, match="holds plates/cands"):
            plates.ingest(p, str(src))
    cand = p / "plates/cands" / lead[0] / "1.jpg"
    with pytest.raises(SlopError, match="already a candidate") as e:
        plates.ingest(p, str(cand))
    assert "--plate PLATE" in str(e.value)
    assert plates._cands(p, lead[0]).keys() == {1}
    r = plates.ingest(p, str(cand), maps=[f"1.jpg={other[0]}"])    # what `--plate` does: a copy for another plate
    assert r["added"] == {other[0]: [1]}


def test_ingest_before_a_board_takes_no_generic_names(home):
    p = synth.make_project(home / "projects", name="early2", tier="quick")
    dl = home / "Downloads"
    synth.make_image(dl / "1.png", 1024, 576, seed=1)
    r = plates.ingest(p, str(dl / "1.png"))                       # one file: its own folder is not a plate
    assert not r["added"] and r["unmatched_files"] == ["1.png"]
    for name in ("image-1.png", "Screenshot-2026-10-01-12.png", "grok-image-2.png", "2026/1.png", "20261001/2.png"):
        synth.make_image(dl / "mix" / name, 1024, 576, seed=len(name))
    synth.make_image(dl / "mix" / "lead-cu" / "1.png", 1024, 576, seed=40)
    synth.make_image(dl / "mix" / "Lead-WS-2.png", 1024, 576, seed=41)
    r = plates.ingest(p, str(dl / "mix"))
    assert {k: sorted(v) for k, v in r["added"].items()} == {"lead-cu": [1], "Lead-WS": [2]}
    assert sorted(r["unmatched_files"]) == sorted(["1.png", "2.png", "Screenshot-2026-10-01-12.png", "grok-image-2.png",
                                                   "image-1.png"])
