"""Model registry + price estimators (fixture listings captured from the free endpoints, 2026-10-01)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_H = Path(__file__).parent / "fixtures" / "gen" / "helpers.py"
_spec = importlib.util.spec_from_file_location("gen_test_helpers", _H)
H = importlib.util.module_from_spec(_spec); sys.modules.setdefault("gen_test_helpers", H); _spec.loader.exec_module(H)

from slop.cli import main  # noqa: E402
from slop.config import SlopError  # noqa: E402
from slop.gen import models as reg  # noqa: E402
from slop.gen.openrouter import OpenRouter  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "gen"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "home"))
    H.write_cache(tmp_path / "home")
    return tmp_path / "home"


def test_seedance_formula():
    # $/s of OUTPUT stays 480p $0.1028, 720p $0.2311; a take bills round(s × 24) + 1 frames (calibrated on real takes)
    assert reg.billed_seconds(4) == pytest.approx(97 / 24) and reg.billed_seconds(5) == pytest.approx(121 / 24)
    assert reg.seedance_cost(1, "480p") == pytest.approx(.1028 * 25 / 24, abs=1e-4)
    assert reg.seedance_cost(1, "720p") == pytest.approx(.2311 * 25 / 24, abs=1e-4)
    assert reg.seedance_cost(5, "720p") == pytest.approx(1.16523, abs=1e-4)      # billed 1.16523 on a real 5 s take


def test_estimates_match_the_paid_probes(home):
    est = reg.estimate_video
    assert reg.out_dims("bytedance/seedance-2.0-mini", "480p") == (864, 496)       # measured output size
    assert reg.out_dims("bytedance/seedance-2.5", "480p") == (854, 480)
    assert est("bytedance/seedance-2.0-mini", 4, "480p") == pytest.approx(.142079, abs=2e-4)
    assert est("bytedance/seedance-2.0-mini", 5, "480p") == pytest.approx(.177, abs=1e-3)
    assert est("bytedance/seedance-2.5", 5, "480p") == pytest.approx(.518, abs=1e-3)
    assert est("bytedance/seedance-2.5", 5, "720p") == pytest.approx(1.16523, abs=1e-4)


def test_video_skus(home):
    est = lambda m, d=5, r="720p", **k: reg.estimate_video(m, d, r, **k)  # noqa: E731
    assert est("bytedance/seedance-2.5", 1, "480p") == pytest.approx(.1028 * 25 / 24, abs=1e-4)
    assert est("bytedance/seedance-2.5", 5) == pytest.approx(1.16523, abs=1e-4)
    assert est("bytedance/seedance-2.5", 5, video_input_s=5) == pytest.approx(21600 * (121 / 24 + 5) * 6.4e-6, abs=1e-3)
    assert est("bytedance/seedance-2.0-mini", 1) == pytest.approx(.0756 * 25 / 24, abs=1e-3)
    assert est("google/veo-3.1-fast", 1) == pytest.approx(.10)                   # _720p key wins over the 1080p default
    assert est("google/veo-3.1-fast", 1, "1080p") == pytest.approx(.12)
    assert est("google/veo-3.1-lite", 1, generate_audio=False) == pytest.approx(.03)
    assert est("kwaivgi/kling-v3.0-std", 1) == pytest.approx(.126)               # with audio
    assert est("kwaivgi/kling-v3.0-std", 1, generate_audio=False) == pytest.approx(.084)
    assert est("x-ai/grok-imagine-video", 1, "480p", n_images=1) == pytest.approx(.05 + .002)
    assert est("alibaba/wan-3.0", 1, "480p") == pytest.approx(.05)
    assert est("minimax/hailuo-3", 5, "2K", n_images=1) == pytest.approx(.65 + .04)
    with pytest.raises(SlopError, match="no price known"):
        est("nobody/nothing")


def test_image_prices(home):
    assert reg.estimate_image("recraft/recraft-v4.1-flash") == pytest.approx(.007)
    assert reg.estimate_image("black-forest-labs/flux.2-klein-4b", "1K") == pytest.approx(.0147, abs=1e-3)
    assert reg.estimate_image("x-ai/grok-imagine-image-2.0", "1K", "low") == pytest.approx(.04)
    assert reg.estimate_image("x-ai/grok-imagine-image-2.0", "2K", "medium") == pytest.approx(.08)
    low = reg.estimate_image("openai/gpt-image-2", "1K", "low")
    assert .003 < low < .01                                               # observed $0.004 per low image
    assert reg.estimate_image("google/gemini-3.1-flash-image", "1K") == pytest.approx(.0672, abs=1e-3)
    assert reg.estimate_image("google/gemini-3-pro-image", "1K") == pytest.approx(.134, abs=2e-3)


def test_rows_are_cheapest_first(home):
    for kind in ("video", "image", "vlm", "text"):
        rows = reg.rows(kind)
        assert rows and [r["est_usd"] for r in rows] == sorted(r["est_usd"] for r in rows)
    vlm = reg.rows("vlm")
    assert vlm[0]["id"].endswith(":free") and all(not r["id"].startswith("openrouter/") for r in vlm)
    assert "google/lyria-3-pro-preview" not in [r["id"] for r in reg.rows("text")]


def test_lyria_id_comes_from_the_listing(home):
    assert reg.lyria_model("pro") == "google/lyria-3-pro-preview"
    assert reg.lyria_model("clip") == "google/lyria-3-clip-preview"


def test_registry_fetch_and_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SLOP_HOME", str(tmp_path / "h2"))
    vids = json.loads((FIX / "videos_models.json").read_text())
    imgs = json.loads((FIX / "images_models.json").read_text())
    routes = {("GET", "/videos/models"): H.FakeResp(200, {"data": vids}),
              ("GET", "/endpoints"): lambda m, url, b: H.FakeResp(200, {"endpoints": next(x["endpoints"] for x in imgs if x["id"] in url)}),
              ("GET", "/images/models"): H.FakeResp(200, {"data": [{k: v for k, v in x.items() if k != "endpoints"} for x in imgs]})}
    c = OpenRouter(session=H.FakeSession(routes))
    assert len(reg.video_models(client=c)) == len(vids)
    n = len(c.session.calls)
    reg.video_models(client=c)                                            # served from the cache
    assert len(c.session.calls) == n
    im = reg.image_models(client=c)
    assert im[0]["endpoints"] and all("Authorization" not in x["headers"] for x in c.session.calls)
    assert (tmp_path / "h2" / "cache" / "openrouter" / "images_models.json").is_file()


def test_cli_models_and_estimate(home, capsys):
    assert main(["--json", "gen", "models", "--kind", "video", "--res", "480p", "--limit", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["models"]) == 3 and out["ok"]
    assert main(["--json", "gen", "estimate", "--model", "bytedance/seedance-2.5", "--duration", "4", "--res", "720p"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["est_usd"] == pytest.approx(21600 * 97 / 24 * 10.7e-6, abs=1e-3)      # 4 s bills 4.04 s
