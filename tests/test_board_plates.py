"""slop plates: book (permutation paste blocks), ingest (names, MJ downloads, zips), pick, vary, sheets, status."""
import json
import math
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop.board import audit, draft, plates  # noqa: E402
from slop.config import SlopError  # noqa: E402

UUIDS = ["0a1b2c3d-1111-4222-8333-944455556666", "7f8e9d0c-aaaa-4bbb-8ccc-ddddeeeeffff",
         "12345678-9abc-4def-8123-456789abcdef"]


def _board(tmp_path, **kw):
    p = synth.make_project(tmp_path, **kw)
    draft.run(p)
    S = synth.fill_todos(synth.load(p, "board/shots.json"))
    (p / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    return p, S


def _owners(S):
    """plate key -> the shot that owns it (has the prompt)."""
    return {s["plate"]: s for s in S["shots"] if s.get("mj_prompt") or s.get("img_prompt")}


def _split_perm(text):
    inner = text[text.index("{") + 1:text.rindex("}")]
    return re.split(r"(?<!\\),\s*", inner)


def test_book_permutation_blocks_and_canon(tmp_path):
    p, S = _board(tmp_path)
    r = plates.book(p, batch="b01")
    owners = _owners(S)
    n = len(owners)
    assert r["mj_jobs"] == n and not r["todo"]
    assert len(r["blocks"]) == math.ceil(n / 10)
    total = 0
    for b in r["blocks"]:
        text = (p / b["file"]).read_text(encoding="utf-8").strip()
        parts = _split_perm(text)
        assert len(parts) == b["expect"] <= 10
        total += len(parts)
        assert text.endswith("} --ar 16:9 --raw --hd")           # an older project's --v 8.2 is dropped
        for part in parts:
            assert part.endswith("no text\\, no letters\\, no logos")
            assert "{" not in part and "}" not in part
            assert re.search(r"(?<!\\),", part) is None          # every inner comma escaped
    assert total == n
    bj = synth.load(p, "plates/mj/b01.json")
    lead_jobs = [j for j in bj["jobs"] if j["lead"]]
    assert lead_jobs and all(synth.CANON[:30] in j["prompt"] for j in lead_jobs)
    md = (p / "plates/prompts.md").read_text(encoding="utf-8")
    assert "Run **" in md and "Personalization on (the P button)" in md and "Midjourney's default" in md
    assert "--v " not in md
    for f in [p / "plates/prompts.md", *sorted((p / "plates/mj").iterdir())]:
        assert "--profile" not in f.read_text(encoding="utf-8")
    # pro plan: one paste for up to 40
    r = plates.book(p, batch="b01", plan="pro")
    assert len(r["blocks"]) == 1 and len(list((p / "plates/mj").glob("b01.perm-*.txt"))) == 1


def test_book_never_a_version_or_a_profile_code_and_the_persons_switches(tmp_path):
    p, S = _board(tmp_path, mj={"params": "--ar 16:9 --v 8.2 --raw --hd --profile zzz999", "profile": ""})
    plates.book(p)
    lines = (p / "plates/mj/b01.lines.txt").read_text(encoding="utf-8")
    assert "zzz999" not in lines and "--v " not in lines and "--profile" not in lines
    pj = synth.load(p, "project.json")
    pj["mj"]["profile"] = "<USER'S OWN CODE or empty>"
    (p / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    r = plates.book(p)
    assert any("placeholder" in w for w in r["warnings"])
    pj["mj"].update(profile="myOwn42", raw=False, hd=False, personalize=False)
    (p / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    plates.book(p)
    lines = (p / "plates/mj/b01.lines.txt").read_text(encoding="utf-8").strip().splitlines()
    assert lines and all(l.endswith("--ar 16:9") for l in lines), lines[:2]   # the code never; P is a button
    assert "**Personalization off**" in (p / "plates/prompts.md").read_text(encoding="utf-8")
    pj["mj"].update(raw=True, hd=True, version="8.2")                          # a version only when they asked
    (p / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    plates.book(p)
    lines = (p / "plates/mj/b01.lines.txt").read_text(encoding="utf-8").strip().splitlines()
    assert all(l.endswith("--ar 16:9 --raw --hd --v 8.2") for l in lines), lines[:2]


def test_book_todo_braces_and_api_jobs(tmp_path):
    p, S = _board(tmp_path)
    owner = list(_owners(S).values())
    owner[0]["mj_prompt"] = "TODO: later"
    owner[1]["mj_prompt"] = "wide shot of a {red, blue} door"
    (p / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    with pytest.raises(SlopError, match="brace"):
        plates.book(p)
    owner[1]["mj_prompt"] = "wide shot of a red door at night"
    (p / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    r = plates.book(p)
    assert r["todo"] == [owner[0]["plate"]]
    q, _ = _board(tmp_path / "q", tier="quick")
    r = plates.book(q)
    jobs = synth.load(q, "plates/jobs.json")["jobs"]
    assert r["api_jobs"] == len(jobs) > 0 and r["mj_jobs"] == 0
    assert all(j["prompt"].endswith("no text, no letters, no logos") for j in jobs)
    j = jobs[0]
    assert j["cmd"].startswith("slop -p ") and j["cmd"].endswith(f" gen image --plate {j['plate']} --prompt-file plates/api/{j['plate']}.txt --aspect-ratio 16:9 --n 2")
    assert (q / j["prompt_file"]).read_text(encoding="utf-8").strip() == j["prompt"]


def _mj_name(prompt: str, uuid: str, n: int, chars: int = 120) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", prompt.lower())[:chars].strip().replace(" ", "_")
    return f"someuser_{words}_{uuid}_{n}.png"


def test_ingest_names_mj_downloads_zip_and_map(tmp_path):
    p, S = _board(tmp_path)
    plates.book(p, batch="b01")
    bj = synth.load(p, "plates/mj/b01.json")
    jobs = {j["plate"]: j for j in bj["jobs"]}
    plain = [k for k, j in jobs.items() if not j["lead"]]
    lead = [k for k, j in jobs.items() if j["lead"]]
    keys = [lead[0], plain[0], plain[1], lead[1]]
    dl = tmp_path / "downloads"
    for k in range(1, 5):                                   # API / older tool names
        synth.make_image(dl / f"{keys[0]}-{k}.png", 160, 90, seed=k)
    for n in range(4):                                       # Midjourney website names, long enough to be unique
        synth.make_image(dl / _mj_name(jobs[keys[1]]["prompt"], UUIDS[0], n), 160, 90, seed=10 + n)
    for n in range(4):                                       # CDN layout: no prompt text -> needs --map
        synth.make_image(dl / UUIDS[1] / f"0_{n}.png", 160, 90, seed=20 + n)
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()                                         # a lead plate: the name is ambiguous, the metadata is not
    meta.add_text("Description", jobs[keys[3]]["prompt"] + " --ar 16:9 --v 8.2 Job ID: " + UUIDS[2])
    for n in range(4):
        f = synth.make_image(dl / _mj_name(jobs[keys[3]]["prompt"], UUIDS[2], n, chars=40), 160, 90, seed=30 + n)
        Image.open(f).save(f, pnginfo=meta)
    r = plates.ingest(p, str(dl), batch="b01")
    assert sorted(r["added"][keys[0]]) == [1, 2, 3, 4]
    assert sorted(r["added"][keys[1]]) == [1, 2, 3, 4]
    assert sorted(r["added"][keys[3]]) == [1, 2, 3, 4]
    assert UUIDS[1] in r["unmatched_jobs"] and (p / "plates/unmatched.jpg").is_file()
    r = plates.ingest(p, str(dl), batch="b01", maps=[f"{UUIDS[1][:8]}={keys[2]}"])
    assert sorted(r["added"][keys[2]]) == [1, 2, 3, 4] and r["duplicates"] == 12
    idx = synth.load(p, "plates/cands/index.json")
    assert len(idx[keys[0]]) == 4 and all(len(v["sha256"]) == 64 for v in idx[keys[0]].values())
    # a zip of a re-roll for keys[0]: new images get the next numbers, the same images are skipped
    z = tmp_path / "reroll.zip"
    synth.make_image(tmp_path / "rr" / f"{keys[0]}-1.png", 160, 90, seed=99)
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(tmp_path / "rr" / f"{keys[0]}-1.png", f"folder/{keys[0]}-1.png")
        zf.write(dl / f"{keys[0]}-2.png", f"folder/{keys[0]}-2.png")
    r = plates.ingest(p, str(z))
    assert r["added"] == {keys[0]: [5]} and r["duplicates"] == 1
    assert (p / "plates/cands" / keys[0] / "5.jpg").is_file()


def test_ingest_ambiguous_prefix_is_never_guessed(tmp_path):
    p, S = _board(tmp_path)
    plates.book(p, batch="b01")
    jobs = synth.load(p, "plates/mj/b01.json")["jobs"]
    lead = [j for j in jobs if j["lead"]][:2]                 # same framing + canon at the start
    dl = tmp_path / "dl"
    synth.make_image(dl / _mj_name(lead[0]["prompt"], UUIDS[2], 0, chars=40), 160, 90)
    r = plates.ingest(p, str(dl), batch="b01")
    assert not r["added"] and UUIDS[2] in r["unmatched_jobs"]


def _with_cands(tmp_path, n=4):
    p, S = _board(tmp_path)
    for key in _owners(S):
        for k in range(1, n + 1):
            synth.make_image(tmp_path / "c" / f"{key}-{k}.png", 160, 90, seed=k + hash(key) % 50)
    plates.ingest(p, str(tmp_path / "c"))
    return p, S


def test_pick_and_sheets(tmp_path):
    p, S = _with_cands(tmp_path)
    keys = list(_owners(S))
    r = plates.pick(p, [keys[0], "2", f"{keys[1]}#3,", f"{keys[2]}:1"])
    picks = synth.load(p, "plates/picks.json")
    assert picks[keys[0]] == {"file": f"plates/cands/{keys[0]}/2.jpg", "cand_k": 2,
                              "shot_ids": [s["id"] for s in S["shots"] if s["plate"] == keys[0]]}
    assert picks[keys[1]]["cand_k"] == 3 and picks[keys[2]]["cand_k"] == 1
    assert keys[3] in r["unpicked"]
    with pytest.raises(SlopError, match="no candidate #9"):
        plates.pick(p, [keys[0], "9"])
    plates.pick(p, [], all_first=True)
    picks = synth.load(p, "plates/picks.json")
    assert set(keys) <= set(picks) and picks[keys[0]]["cand_k"] == 2
    sh = plates.sheet(p)
    assert sh["sheets"] and all((p / f).is_file() for f in sh["sheets"])
    st = plates.status(p)
    assert all(r["pick"] for r in st["plates"]) and "PLATE" in st["text"]


def test_vary_gives_repeated_plates_other_candidates(tmp_path):
    p, S = _with_cands(tmp_path)
    plates.pick(p, [], all_first=True)
    S = synth.load(p, "board/shots.json")
    p3 = [s for s in S["shots"] if s["motion_tier"] == "plate3d"]
    a, b, c = p3[0], p3[3], p3[6]
    b["plate"] = a["plate"]
    c["plate"] = a["plate"]
    (p / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    assert not audit.audit(p)["gates"]["plates_unique"]["ok"]
    dry = plates.vary(p, dry=True)
    assert len([x for x in dry["changes"] if "->" in x]) == 2
    assert synth.load(p, "board/shots.json")["shots"] == S["shots"]          # dry changes nothing
    r = plates.vary(p)
    S2 = synth.load(p, "board/shots.json")
    by = {s["id"]: s for s in S2["shots"]}
    assert by[a["id"]]["plate"] == a["plate"]
    assert by[b["id"]]["plate"] == f"{a['plate']}~2" and by[c["id"]]["plate"] == f"{a['plate']}~3"
    picks = synth.load(p, "plates/picks.json")
    assert picks[f"{a['plate']}~2"]["variant_of"] == a["plate"]
    assert picks[f"{a['plate']}~2"]["shot_ids"] == [b["id"]]
    assert audit.audit(p)["gates"]["plates_unique"]["ok"]
    assert not plates.vary(p)["changes"]                                      # idempotent
    assert not r["problems"]


def test_vary_reports_running_out_of_candidates(tmp_path):
    p, S = _with_cands(tmp_path, n=1)
    plates.pick(p, [], all_first=True)
    S = synth.load(p, "board/shots.json")
    p3 = [s for s in S["shots"] if s["motion_tier"] == "plate3d"]
    p3[4]["plate"] = p3[0]["plate"]
    (p / "board/shots.json").write_text(json.dumps(S), encoding="utf-8")
    r = plates.vary(p)
    assert r["problems"] and "out of distinct images" in r["problems"][0]
