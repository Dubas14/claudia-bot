"""slop edit look: the Lab grade toward a hero plate with the accent kept, the 52³ LUT, the three modes."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests/fixtures/board"))

import board_synth as synth  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.edit import look  # noqa: E402

np = pytest.importorskip("numpy")
from PIL import Image  # noqa: E402

C = look.conf({"look": {"mode": "clean-grade"}})


def _img(color, w=96, h=54, seed=0, accent=False):
    rng = np.random.default_rng(seed)
    a = np.clip(np.array(color, np.float32) + rng.normal(0, 12, (h, w, 3)), 0, 255).astype(np.uint8)
    if accent:
        a[h // 3:h // 2, w // 3:w // 2] = (217, 119, 87)
    return a


def test_lab_roundtrip():
    rgb = np.random.default_rng(1).integers(0, 256, (40, 40, 3), dtype=np.uint8)
    back = look.to_rgb8(look.to_lab(rgb))
    assert np.abs(back.astype(int) - rgb.astype(int)).max() <= 1


def test_hero_grades_to_itself_outside_the_accent():
    hero = _img((40, 90, 110))
    ref = look.stats(look.to_lab(hero))
    g, w = look.grade(hero, C, ref)
    assert w.max() < 0.05
    assert np.abs(g.astype(int) - hero.astype(int)).mean() < 1.0


def test_grade_moves_toward_the_hero_and_keeps_the_accent():
    hero = _img((40, 90, 110))                  # blue-green-grey
    ref = look.stats(look.to_lab(hero))
    src = _img((150, 120, 60), seed=3, accent=True)     # warm image with a clay-orange patch
    g, w = look.grade(src, C, ref)
    lab_src, lab_g = look.to_lab(src), look.to_lab(g)
    mr = ref[0]
    d_before = np.abs(lab_src[..., 1:].reshape(-1, 2).mean(0) - mr[1:]).sum()
    d_after = np.abs(lab_g[..., 1:].reshape(-1, 2).mean(0) - mr[1:]).sum()
    assert d_after < 0.6 * d_before                    # toward the hero (strength 0.65)
    patch = (slice(54 // 3 + 2, 54 // 2 - 2), slice(96 // 3 + 2, 96 // 2 - 2))
    assert w[patch].mean() > 0.9
    a, b = lab_g[patch][..., 1].mean(), lab_g[patch][..., 2].mean()
    hue = np.degrees(np.arctan2(b, a)) % 360
    chroma_src = np.hypot(lab_src[patch][..., 1], lab_src[patch][..., 2]).mean()
    assert 22 <= hue <= 72 and np.hypot(a, b) >= chroma_src * 1.05   # the orange pops (x1.12 boost)


def test_cube_file_layout(tmp_path):
    ref = look.stats(look.to_lab(_img((40, 90, 110))))
    ident = {**C, "strength": 0.0, "contrast": 0.0, "accent_chroma": [1000, 2000]}    # a grade that changes nothing
    f = look.cube(ref, tmp_path / "g.cube", ident, ref, n=9)
    lines = f.read_text().splitlines()
    assert lines[1] == "LUT_3D_SIZE 9" and lines[2:4] == ["DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    assert len(lines) == 4 + 9 ** 3
    v = np.array([list(map(float, x.split())) for x in lines[4:]])
    lattice = np.linspace(0, 1, 9)
    assert v[1] == pytest.approx([lattice[1], 0, 0], abs=0.01)          # red varies fastest
    assert v[9] == pytest.approx([0, lattice[1], 0], abs=0.01)          # then green
    assert v[81] == pytest.approx([0, 0, lattice[1]], abs=0.01)         # then blue
    assert v[-1] == pytest.approx([1, 1, 1], abs=0.01)


@pytest.mark.skipif(not synth.have_ffmpeg(), reason="ffmpeg not installed")
def test_lut_matches_the_grade_on_a_clip(tmp_path):
    vid = synth.make_video(tmp_path / "v.mp4", seconds=1.0, size="160x90")
    ref = look.stats(look.to_lab(_img((40, 90, 110))))
    st = look.clip_stats(vid, n=4, width=160)
    lut = look.cube(st, tmp_path / "g.cube", C, ref)
    def frame(vf):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(vid), "-frames:v", "1", "-vf", vf,
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(raw, np.uint8).reshape(90, 160, 3)
    plain = frame("format=rgb24")
    via_lut = frame(f"format=rgb24,lut3d=file={look.ff_path(lut)}:interp=tetrahedral")
    direct, _ = look.grade(plain, C, ref, st)
    diff = np.abs(via_lut.astype(int) - direct.astype(int))
    assert diff.mean() < 1.5 and np.percentile(diff, 99) <= 6


def _proj(tmp_path, mode, hero=True):
    p = synth.make_project(tmp_path, look={"mode": mode, "accent": "#D97757", "hero_plate": "hero" if hero else None})
    synth.make_image(p / "plates/cands/hero/1.jpg", 320, 180, color=(40, 90, 110))
    synth.make_image(p / "plates/cands/p002/1.jpg", 320, 180, color=(150, 120, 60), accent=True)
    synth.write_json(p / "plates/picks.json", {"hero": {"file": "plates/cands/hero/1.jpg", "cand_k": 1, "shot_ids": []},
                                               "p002": {"file": "plates/cands/p002/1.jpg", "cand_k": 1, "shot_ids": []}})
    return p


def test_modes_bake_plan(tmp_path):
    proj = json.loads((_proj(tmp_path / "a", "native") / "project.json").read_text())
    assert look.bake_plan(tmp_path / "a/synth", proj)["grade"] is False
    p = _proj(tmp_path / "b", "clean-grade")
    plan = look.bake_plan(p, json.loads((p / "project.json").read_text()))
    assert plan["grade"] and plan["conf"]["halftone"]["opacity"] == 0
    p = _proj(tmp_path / "c", "clean-grade", hero=False)
    with pytest.raises(SlopError, match="hero"):
        look.bake_plan(p, json.loads((p / "project.json").read_text()))
    p = _proj(tmp_path / "d", "print", hero=False)
    plan = look.bake_plan(p, json.loads((p / "project.json").read_text()))
    assert plan["grade"] is False and plan["conf"]["halftone"]["opacity"] == pytest.approx(0.28)


def test_look_commands(tmp_path):
    p = _proj(tmp_path, "native", hero=False)
    out = look.cmd_set(p, mode="clean-grade", hero="hero", strength=0.5)
    pj = json.loads((p / "project.json").read_text())
    assert pj["look"]["mode"] == "clean-grade" and pj["look"]["hero_plate"] == "hero" and pj["look"]["strength"] == .5
    assert out["ok"]
    sh = look.cmd_sheet(p)
    im = Image.open(sh["sheet"])
    assert im.width == 2 * 900 + 30 and sh["plates"][0] == "hero"
    g = look.cmd_grade(p, [str(p / "plates/cands/p002/1.jpg")], str(tmp_path / "graded"))
    assert Path(g["files"][0]).is_file()
    with pytest.raises(SlopError):
        look.cmd_set(p, mode="sepia")
    look.cmd_set(p, mode="print")
    sh = look.cmd_sheet(p, ["p002"])                     # print look previews the screen on stills
    assert Path(sh["sheet"]).is_file()
