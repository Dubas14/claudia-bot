"""slop.taste.apply: the owner-confirmed look + a style tail into project.json (preview first, --yes writes)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "taste"))
import taste_synth as S  # noqa: E402

from slop.cli import main  # noqa: E402
from slop.config import SlopError, load_project  # noqa: E402
from slop.taste import apply as A  # noqa: E402
from slop.taste.profile import ensure_link  # noqa: E402
from slop.taste.store import read_jsonl  # noqa: E402


def run(capsys, *args):
    code = main(["--json", *args])
    out = capsys.readouterr().out.strip().splitlines()
    return code, json.loads(out[-1])


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    p = S.make_project(tmp_path, "song")
    pj = json.loads((p / "project.json").read_text(encoding="utf-8"))
    pj["look"] = {"mode": "native", "accent": "#D97757", "fonts": {"lyric": "Space Grotesk"}, "hero_plate": None}
    (p / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    ensure_link(p)
    return p


def tokens(p, lean="dark", lyric=None, texture=None):
    gr = {"dark": (20, 3), "light": (3, 20), "mixed": (8, 8)}[lean]
    t = {"palette": {"restraint": "mono+1", "status": "measured", "accent": None, "accent_source": "ask-owner",
                     "accent_candidates": [], "paper": "#eeede8", "ink": "#121212", "footage_grade": "native"},
         "ground": {"likes_dark": gr[0], "likes_light": gr[1], "likes_mid": 2, "status": "lead"},
         "texture": {"lean": "grain/texture", "apply": texture, "status": "ask-owner"},
         "type": {"lyric": lyric, "shortlist": [lyric] if lyric else [], "status": "lead"}}
    (p / "taste").mkdir(exist_ok=True)
    (p / "taste" / "taste-tokens.json").write_text(json.dumps(t), encoding="utf-8")
    return t


def test_hue_names():
    assert A.hue_name("#D97757") == ("clay-orange", True)
    assert A.hue_name("#E01010") == ("red", True) and A.hue_name("#2050FF") == ("blue", False)
    assert A.hue_name("#F4F4F2")[0] == "white" and A.hue_name("#DB5C34")[1] is True


def test_style_tails_follow_the_tokens_and_never_say_monochrome():
    dark = A.style_tails({"palette": {"ink": "#0f1216"}, "ground": {"likes_dark": 20, "likes_light": 2}}, "#D97757",
                         True)
    assert dark["mj"] == ("blue-black #0f1216 and deep greys, one small clay-orange #D97757 light as the only warm "
                          "note, fine film grain, cinematic 35mm film still")
    assert "photographed on a cinema camera" in dark["api"] and "fine film grain" in dark["api"]
    green = A.style_tails({"palette": {"ink": "#181e15"}, "ground": {"likes_dark": 20, "likes_light": 2}}, None, None)
    assert green["mj"].startswith("green-black #181e15") and "blue" not in green["mj"]       # the hex's real hue
    light = A.style_tails({"palette": {"paper": "#eeede8"}, "ground": {"likes_dark": 1, "likes_light": 12}}, None, False)
    assert light["mj"].startswith("paper white #eeede8") and "grain" not in light["mj"] + light["api"]
    for t in (dark, green, light):                       # the light is per chapter (docs/50): never in the project tail
        assert not any(w in (t["mj"] + t["api"]).lower() for w in ("night", "daylight", "dawn", "dusk", "high-key"))
    cel = A.style_tails(None, "#2050FF", None, medium="cel")
    assert "only accent" in cel["mj"] and "cel-animation" in cel["api"] and "a real photograph" not in cel["api"]
    for t in (dark, light, cel):
        assert "monochrome" not in (t["mj"] + t["api"]).lower() and len(t["mj"]) <= A.TAIL_MAX


def test_preview_changes_nothing_then_yes_writes_logs_and_records(proj, capsys):
    tokens(proj, lean="dark", lyric="Space Grotesk")
    before = (proj / "project.json").read_text(encoding="utf-8")
    code, j = run(capsys, "-p", str(proj), "taste", "apply")
    assert code == 0 and j["applied"] is False and "--yes" in j["text"] and "Ask the owner first" in j["text"]
    assert any(a.startswith("accent") for a in j["asks"]) and any(a.startswith("texture") for a in j["asks"])
    assert (proj / "project.json").read_text(encoding="utf-8") == before and not (proj / "DECISIONS.md").exists()
    code, j = run(capsys, "-p", str(proj), "taste", "apply", "--accent", "d97757", "--texture", "yes", "--yes",
                  "--note", "use the orange, grain is fine")
    assert code == 0 and j["applied"] is True and "logged in DECISIONS.md" in j["text"]
    look = load_project(proj)["look"]
    assert look["accent"] == "#D97757" and look["mode"] == "native" and look["fonts"]["lyric"] == "Space Grotesk"
    assert "one small clay-orange #D97757 light as the only warm note" in look["style_tail"]
    assert look["style_tail"].startswith("neutral black #121212") and "fine film grain" in look["style_tail"]
    assert "a real photograph" in look["style_tail_api"] and look["hero_plate"] is None      # other keys kept
    dec = (proj / "DECISIONS.md").read_text(encoding="utf-8")
    assert "TASTE apply: look.mode native; look.accent #D97757" in dec and "use the orange, grain is fine" in dec
    rules = {r["rule"]: r for r in read_jsonl(proj / "taste" / "verdicts.jsonl")}
    assert rules["palette.accent"]["value"] == "#D97757" and rules["texture"]["value"] == "grain"
    assert rules["texture"]["status"] == "confirmed"
    assert rules["type.lyric"]["value"] == "Space Grotesk" and "palette.footage_grade" not in rules   # unchanged mode
    assert json.loads((proj / "taste" / "applied.json").read_text(encoding="utf-8"))["look"]["accent"] == "#D97757"


def test_confirmed_verdicts_feed_apply_without_flags(proj):
    t = tokens(proj, lean="light", texture=True)
    t["palette"].update(accent="#E01010", accent_source="owner verdict", footage_grade="print",
                        footage_grade_status="confirmed")
    (proj / "taste" / "taste-tokens.json").write_text(json.dumps(t), encoding="utf-8")
    r = A.apply(proj)
    assert r["set"]["mode"] == "print" and r["set"]["accent"] == "#E01010" and r["sources"]["accent"] == "owner verdict"
    assert r["set"]["style_tail"].startswith("paper white") and "red #E01010" in r["set"]["style_tail"]
    assert not r["asks"]


def test_apply_validates_before_writing(proj):
    tokens(proj)
    before = (proj / "project.json").read_text(encoding="utf-8")
    with pytest.raises(SlopError, match="not an OFL face"):
        A.apply(proj, yes=True, lyric="Comic Sans")
    with pytest.raises(SlopError, match="hex colour"):
        A.apply(proj, yes=True, accent="orange")
    with pytest.raises(SlopError, match="-- parameters"):
        A.apply(proj, yes=True, tail="foggy dawn --ar 16:9")
    with pytest.raises(SlopError, match="native"):
        A.apply(proj, yes=True, mode="mono")
    assert (proj / "project.json").read_text(encoding="utf-8") == before


def test_apply_without_tokens_uses_neutral_light_and_says_so(proj):
    r = A.apply(proj, accent="none", texture="no", lyric="ibm plex mono", yes=True)
    look = load_project(proj)["look"]
    assert look["accent"] is None and look["fonts"]["lyric"] == "IBM Plex Mono"
    assert look["style_tail"] == "quiet neutral tones, cinematic 35mm film still"
    assert any("no taste-tokens.json" in a for a in r["text"].split("still to ask: ")[-1:])
    assert "engine still uses its default accent" in r["text"] and "logged in DECISIONS.md" in r["text"]
