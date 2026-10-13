"""slop edit edl: song-time clip mapping, covers, holes cut to the motion clip, plates as stand-ins, overrides."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop.edit import edl  # noqa: E402


def _take(p: Path, clip: str, n: int = 1) -> str:
    f = p / "clips" / clip / f"take-{n}.mp4"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\x00" * 16)
    return f"clips/{clip}/take-{n}.mp4"


def _clip(p: Path, cid: str, **kw) -> None:
    synth.write_json(p / "clips" / f"{cid}.json", {"id": cid, "status": "delivered", **kw})


def _project(tmp_path: Path) -> Path:
    p = synth.make_project(tmp_path)
    shots = [
        {"id": "s001", "t0": 0.0, "t1": 2.0, "motion_tier": "plate3d", "plate": "p1"},
        {"id": "s002", "t0": 2.0, "t1": 6.0, "motion_tier": "sung", "plate": "p2", "clip": "c01"},
        {"id": "s003", "t0": 6.0, "t1": 9.0, "motion_tier": "motion", "plate": "p3", "clip": "c02"},
        {"id": "s004", "t0": 9.0, "t1": 11.0, "motion_tier": "sung", "plate": "p4", "clip": "c03"},
        {"id": "s005", "t0": 11.0, "t1": 12.0, "motion_tier": "plate3d", "plate": "p5"},
        {"id": "s006", "t0": 12.0, "t1": 13.0, "motion_tier": "still", "code": True},
        {"id": "s007", "t0": 13.0, "t1": 17.0, "motion_tier": "sung", "plate": "p7", "clips": ["c04", "c05"]},
        {"id": "s008", "t0": 17.0, "t1": 20.0, "motion_tier": "motion", "plate": "p8", "clip": "c06"},
    ]
    synth.write_json(p / "board/shots.json", {"version": 1, "duration": 20.0, "chapters": [], "shots": shots,
                                              "seedance": [], "plates": []})
    picks = {}
    for k in ("p1", "p3", "p4", "p7", "p8"):
        f = synth.make_image(p / "plates/cands" / k / "1.jpg", 64, 36)
        picks[k] = {"file": f"plates/cands/{k}/1.jpg", "cand_k": 1, "shot_ids": []}
        assert f.is_file()
    synth.write_json(p / "plates/picks.json", picks)
    _clip(p, "c01", kind="sung", song_t0=1.5, body={"duration": 5}, covers=["c01-c1"],
          takes=[{"file": _take(p, "c01"), "status": "delivered",
                  "sync": {"lag_s": 0.12, "ncc": 0.5, "mode": "copy", "synced": [[1.6, 4.0]], "diverge_at": 4.1,
                           "cut_at": 4.0}}])
    _clip(p, "c01-c1", kind="sung", song_t0=3.8, body={"duration": 4},
          takes=[{"file": _take(p, "c01-c1"), "status": "delivered",
                  "sync": {"lag_s": -0.05, "ncc": 0.4, "mode": "copy", "synced": [[4.0, 6.5]]}}])
    _clip(p, "c02", kind="motion", song_t0=6.0, body={"duration": 4},
          takes=[{"file": _take(p, "c02"), "status": "delivered", "sync": {"lag_s": 0.3, "ncc": 0.05, "mode": "none"}}])
    _clip(p, "c03", kind="sung", song_t0=8.7, body={"duration": 4}, status="declined", takes=[])
    _clip(p, "c04", kind="sung", song_t0=12.8, body={"duration": 5},
          takes=[{"file": _take(p, "c04"), "status": "delivered",
                  "sync": {"lag_s": 0.0, "ncc": 0.3, "mode": "copy", "synced": [[12.9, 14.5]], "diverge_at": 14.6,
                           "cut_at": 14.5}}])
    _clip(p, "c05", kind="motion", song_t0=13.0, body={"duration": 5},
          takes=[{"file": _take(p, "c05"), "status": "delivered", "sync": {}}])
    _clip(p, "c06", kind="motion", song_t0=17.0, body={"duration": 4},
          takes=[{"file": _take(p, "c06", 1), "status": "delivered", "sync": {"lag_s": 0.2, "ncc": 0.6, "mode": "copy"}},
                 {"file": _take(p, "c06", 2), "status": "delivered", "rejected": True, "sync": {}}])
    return p


def test_edl_song_time_mapping_covers_holes_and_plates(tmp_path):
    p = _project(tmp_path)
    r = edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s001"] == {"plate": "p1"}
    # sung chain: the take until its synced span ends, then the cover (in = T - song_t0 + lag)
    assert E["s002"] == {"segs": [{"t0": 2.0, "clip": "c01-t1", "in": 0.62},
                                  {"t0": 4.0, "clip": "c01-c1-t1", "in": 0.15}]}
    # motion clip without a measured copy plays at lag 0
    assert E["s003"] == {"segs": [{"t0": 6.0, "clip": "c02-t1", "in": 0.0}]}
    # declined clip: the shot stays on its plate
    assert E["s004"] == {"plate": "p4"}
    # unpicked plate -> MISSING; code-drawn -> nothing needed
    assert "s005" not in E and "s006" not in E
    assert r["missing"] == ["s005"]
    # lip sync given up after 14.5: cut to the shot's motion clip there
    assert E["s007"] == {"segs": [{"t0": 13.0, "clip": "c04-t1", "in": 0.2},
                                  {"t0": 14.5, "clip": "c05-t1", "in": 1.5}]}
    # a rejected later take gives way to the good one; motion with a measured copy uses its lag
    assert E["s008"] == {"segs": [{"t0": 17.0, "clip": "c06-t1", "in": 0.2}]}
    rows = {x["id"]: x for x in r["rows"]}
    assert rows["s004"]["src"].startswith("plate p4 (stand-in")
    assert rows["s002"]["holes"] == [] and rows["s007"]["holes"] == []


def test_edl_holes_without_alt_and_overrides(tmp_path):
    p = _project(tmp_path)
    S = synth.load(p, "board/shots.json")
    S["shots"][6]["clips"] = ["c04"]                         # no motion clip to cut away to
    synth.write_json(p / "board/shots.json", S)
    synth.write_json(p / "edit/overrides.json", {"s003": {"use": "plate", "why": "judged bad"}})
    r = edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s003"] == {"plate": "p3"}
    assert E["s007"]["segs"][-1] == {"t0": 14.5, "clip": "c04-t1", "in": 1.7}
    assert {x["id"]: x for x in r["rows"]}["s007"]["holes"] == [[14.5, 17.0]]


def test_edl_missing_take_files_and_qa_reject(tmp_path):
    p = _project(tmp_path)
    (p / "clips/c02/take-1.mp4").unlink()
    c = synth.load(p, "clips/c06.json")
    c["qa"] = {"verdict": "reject"}
    synth.write_json(p / "clips/c06.json", c)
    r = edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s003"] == {"plate": "p3"} and E["s008"] == {"plate": "p8"}
    assert "c02-t1" in r["missing_take_files"]


def test_edl_discovers_clips_made_by_slop_clip_new(tmp_path):
    p = _project(tmp_path)
    S = synth.load(p, "board/shots.json")
    S["shots"][3].pop("clip")                                # s004: the board's planned id never became a file
    S["shots"][4]["motion_tier"] = "motion"                  # s005: covered by a window made for s004
    synth.write_json(p / "board/shots.json", S)
    _clip(p, "W01", shot="s004", kind="sung", song_t0=8.7, needed=[9.0, 12.0], body={"duration": 4},
          takes=[{"n": 1, "file": _take(p, "W01"), "status": "delivered",
                  "sync": {"lag_s": 0.1, "ncc": 0.4, "mode": "copy", "synced": [[8.8, 12.5]], "cut_at": None}}])
    _clip(p, "W01-c1", shot="s004", kind="sung", parent="W01", song_t0=10.0, body={"duration": 4},
          takes=[{"n": 1, "file": _take(p, "W01-c1"), "status": "delivered", "sync": {"synced": [[10, 13]]}}])
    edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s004"] == {"segs": [{"t0": 9.0, "clip": "W01-t1", "in": 0.4}]}
    assert E["s005"] == {"segs": [{"t0": 11.0, "clip": "W01-t1", "in": 2.4}]}


def test_edl_reads_legacy_ev_fields(tmp_path):
    p = _project(tmp_path)
    S = synth.load(p, "board/shots.json")
    sh = S["shots"][1]
    sh.pop("clip")
    sh["seedance_clip"] = "c01"
    sh["motion_tier"] = "seedance"
    S["seedance"] = [{"clip": "c01", "sing": True, "duration": 5, "song_t0": 1.5, "shots": ["s002"]}]
    synth.write_json(p / "board/shots.json", S)
    for cid in ("c01", "c01-c1"):
        c = synth.load(p, f"clips/{cid}.json")
        c.pop("kind")
        c["sing"] = True
        sy = c["takes"][0]["sync"]
        c["takes"][0]["sync"] = {"lag_s": sy["lag_s"], "lag_ncc": sy["ncc"], "spans_song": sy["synced"],
                                 "diverges": bool(sy.get("diverge_at")), "cut_eighth_song": sy.get("cut_at")}
        synth.write_json(p / "clips" / f"{cid}.json", c)
    edl.build(p)
    E = synth.load(p, "edit/edl.json")
    assert E["s002"]["segs"][0] == {"t0": 2.0, "clip": "c01-t1", "in": 0.62}
    assert json.dumps(E)          # EV format: plain JSON
