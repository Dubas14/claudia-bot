"""Never a pinned version (0.2.9). OpenRouter defaults move to the newest model of their family and variant; a
Midjourney prompt never carries a --v or a profile code, its --raw and --hd follow the person's choices, and the
personalization profile goes on with the P button."""
from __future__ import annotations

import json
import time

import pytest

from slop.board.plates import mj_line, mj_params
from slop.config import SlopError
from slop.gen import models as M

import test_relay as RT  # noqa: E402  (its fake engine and helpers)
K = RT.K

VIDEO = [{"id": "bytedance/seedance-2.5"}, {"id": "bytedance/seedance-2.6"}, {"id": "bytedance/seedance-2.0-mini"},
         {"id": "bytedance/seedance-2.2-mini"}, {"id": "bytedance/seedance-3.0-pro"}, {"id": "kwaivgi/kling-v3"}]
IMAGE = [{"id": "openai/gpt-image-2"}, {"id": "openai/gpt-image-2.5"}, {"id": "openai/gpt-image-1-mini"},
         {"id": "google/gemini-3-pro-image-preview"}, {"id": "google/gemini-3.5-pro-image"},
         {"id": "google/gemini-3.5-flash-image"}]


@pytest.fixture
def live(monkeypatch):
    monkeypatch.delenv("SLOP_PIN_MODELS", raising=False)
    monkeypatch.setattr(M, "video_models", lambda refresh=False, client=None: VIDEO)
    monkeypatch.setattr(M, "image_models", lambda refresh=False, client=None: IMAGE)


def test_the_newest_of_the_same_family_and_variant(live):
    assert M.latest("bytedance/seedance-2.5", "video") == "bytedance/seedance-2.6"      # never the 3.0-pro
    assert M.latest("bytedance/seedance-2.0-mini", "video") == "bytedance/seedance-2.2-mini"
    assert M.latest("openai/gpt-image-2", "image") == "openai/gpt-image-2.5"           # never the 1-mini
    assert M.latest("google/gemini-3-pro-image", "image") == "google/gemini-3.5-pro-image"
    assert M.latest("kwaivgi/kling-v3", "video") == "kwaivgi/kling-v3"
    assert M.latest("some/unversioned-model", "video") == "some/unversioned-model"


def test_pinned_offline_or_no_list_keeps_the_id(live, monkeypatch):
    def down(refresh=False, client=None):
        raise SlopError("offline")
    monkeypatch.setattr(M, "video_models", down)
    assert M.latest("bytedance/seedance-2.5", "video") == "bytedance/seedance-2.5"
    monkeypatch.setattr(M, "video_models", lambda refresh=False, client=None: VIDEO)
    monkeypatch.setenv("SLOP_PIN_MODELS", "1")
    assert M.latest("bytedance/seedance-2.5", "video") == "bytedance/seedance-2.5"


def test_a_project_slot_moves_unless_the_person_pinned_it(live):
    assert M.resolve({}, "video", "bytedance/seedance-2.5", "video") == "bytedance/seedance-2.6"
    proj = {"models": {"video": "bytedance/seedance-2.0-mini"}}
    assert M.resolve(proj, "video", "bytedance/seedance-2.5", "video") == "bytedance/seedance-2.2-mini"
    proj["models"]["pin"] = True
    assert M.resolve(proj, "video", "bytedance/seedance-2.5", "video") == "bytedance/seedance-2.0-mini"


def test_offline_reads_only_the_cached_list(live, monkeypatch, tmp_path):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path))

    def never(refresh=False, client=None):
        raise AssertionError("offline must not fetch")
    monkeypatch.setattr(M, "video_models", never)
    assert M.latest("bytedance/seedance-2.5", "video", offline=True) == "bytedance/seedance-2.5"   # no cache yet
    M._cache_file("videos_models").write_text(json.dumps({"fetched_at": time.time() - 9e6, "data": VIDEO}),
                                              encoding="utf-8")                                    # stale is fine
    assert M.latest("bytedance/seedance-2.5", "video", offline=True) == "bytedance/seedance-2.6"


def test_a_midjourney_line_never_pins_a_version_or_carries_a_profile_code():
    line, did = mj_line("close-up of her --ar 16:9 --v 8.2 --raw --hd --p abc123x", {})
    assert line == "close-up of her --ar 16:9 --raw --hd"
    assert any("--v 8.2" in d for d in did) and any("P button" in d for d in did)
    assert "abc123x" not in json.dumps(did)
    assert mj_line("a city --ar 16:9 --profile abc123x def456y --raw", {})[0] == "a city --ar 16:9 --raw"
    assert mj_line("a city --ar 16:9 --personalize abc --stylize 50", {})[0] == "a city --ar 16:9 --stylize 50"
    assert mj_line("a city --ar 16:9 --version 7 --niji 6", {})[0] == "a city --ar 16:9"
    assert mj_line("a city --ar 16:9 --video 1 --public", {}) == ("a city --ar 16:9 --video 1 --public", [])


def test_raw_and_hd_follow_the_persons_switches():
    assert mj_line("a --ar 16:9", {"raw": True, "hd": False})[0] == "a --ar 16:9 --raw"
    assert mj_line("a --ar 16:9 --raw --hd", {"raw": False, "hd": False})[0] == "a --ar 16:9"
    assert mj_line("a --ar 16:9 --raw", {"raw": True, "hd": True})[0] == "a --ar 16:9 --raw --hd"
    assert mj_line("a --ar 16:9 --raw --hd", {}) == ("a --ar 16:9 --raw --hd", [])   # an older project: as written
    line, did = mj_line("a --ar 16:9 --v 7", {"version": "8.2"})                      # only when they asked
    assert line == "a --ar 16:9 --v 8.2" and did
    assert mj_line("a --ar 16:9 --v 8.2", {"version": "8.2"}) == ("a --ar 16:9 --v 8.2", [])


def test_the_plate_book_params_follow_the_project():
    proj = {"mj": {"params": "--ar 16:9", "raw": True, "hd": False, "personalize": True, "profile": "abc123x"}}
    assert mj_params({}, proj) == "--ar 16:9 --raw"
    assert mj_params({"aspect": "4:5"}, proj) == "--ar 4:5 --raw"
    assert mj_params({}, {"mj": {"params": "--ar 16:9 --v 8.2 --raw --hd", "profile": ""}}) == "--ar 16:9 --raw --hd"


def test_new_projects_pin_nothing_and_ask_the_switches(tmp_path, monkeypatch):
    env = RT.setup(tmp_path, monkeypatch)
    assert K.run("new", "demo")[0] == 0
    pj = json.loads((env["wd"] / "demo" / "project.json").read_text(encoding="utf-8"))
    assert "--v" not in pj["mj"]["params"] and pj["models"]["pin"] is False
    assert (pj["mj"]["raw"], pj["mj"]["hd"], pj["mj"]["personalize"]) == (True, False, True)
    for key, val in (("mj.raw", "false"), ("mj.personalize", "off")):
        rc, out = K.run("-p", "demo", "project", "set", key, val)
        assert rc == 0, out
    rc, out = K.run("-p", "demo", "project", "set", "mj.hd", "maybe")
    assert rc == 1 and "true or false" in out["error"]
    assert K.run("relay", "setup")[0] == 0
    rc, out = K.run("-p", "demo", "relay", "job", "--kind", "midjourney", "--text", "a door --ar 16:9 --raw --v 8.2")
    assert rc == 0 and "Personalization: off" in out["text"] and "dropped --raw" in out["text"], out
    rc, out = K.run("-p", "demo", "relay", "job", "--kind", "midjourney", "--personalize", "on", "--text", "a door")
    assert rc == 0 and "P button" in out["text"], out
    rc, r = K.run("relay", "read")
    mj = [j for j in r["jobs"] if j["job_kind"] == "midjourney"]
    assert [j["text"] for j in mj] == [["a door --ar 16:9"], ["a door"]]
    assert [j["personalize"] for j in mj] == [False, True]
    assert "the P button off" in r["grok_next"] and "the P button on" in r["grok_next"]


def test_opus_and_grok_are_told_to_use_the_newest():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    brief = (root / "templates/production-brief.md").read_text(encoding="utf-8")
    assert "Never pin a version" in brief and "from memory" in brief
    assert "v8.2" not in brief and "Raw (on), their personalization profile (on" in brief
    for skill in ("midjourney", "suno", "grok-imagine"):
        text = (root / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "newest" in text, skill
    suno = (root / "skills/suno/SKILL.md").read_text(encoding="utf-8")
    assert "Custom mode" not in suno and "leave the lyrics box empty" in suno
