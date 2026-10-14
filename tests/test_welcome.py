"""The welcome runs first (the template's gettingStarted): what the bot is, how it works, every skill, and what to
subscribe to with cheaper alternatives, before any install or sign-in; then it hands over to the setup."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
_spec = importlib.util.spec_from_file_location("build_recipe", SKILLS / "build_recipe.py")
BR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BR)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


WELCOME = read(SKILLS / "claudia-welcome" / "SKILL.md")


def test_the_welcome_runs_first_and_before_any_sign_in():
    assert BR.GETTING_STARTED == "claudia-welcome" and BR.ORDER[0] == "claudia-welcome"
    assert "No install, no sign-in" in WELCOME
    assert not re.search(r"`slop |git clone|setup\.sh", WELCOME), "nothing is installed before the person says go"


def test_the_welcome_lists_every_skill_once():
    tour = WELCOME[WELCOME.index("**My skills**"):WELCOME.index("**What each subscription gets you**")]
    assert [m for m in re.findall(r"^\d+\. ([a-z-]+):", tour, flags=re.M)] == BR.ORDER


def test_the_welcome_says_what_each_subscription_gets_you_with_cheaper_alternatives():
    subs = WELCOME[WELCOME.index("**What each subscription gets you**"):WELCOME.index("## Then ask")]
    assert "**Claude Max 20x, about $200 (recommended):**" in subs and "Max 5x (about $100)" in subs
    for must in ("Pro (about $20)", "ChatGPT Plus", "Grok Imagine", "Midjourney Standard", "Suno Pro", "Seedance",
                 "OpenRouter", "check current prices"):
        assert must in subs, must
    bullets = [ln for ln in subs.splitlines() if ln.startswith("- **")]
    assert len(bullets) == 5 and all(":**" in b for b in bullets), "each subscription says what it gets you"
    assert sum("Cheaper:" in b for b in bullets) >= 4


def test_the_shipped_bot_never_offers_the_parked_home_gpu(monkeypatch):
    for f in [*(SKILLS / s / "SKILL.md" for s in BR.ORDER), SKILLS / "profile.md", ROOT / "templates" / "production-brief.md"]:
        text = read(f)
        assert "setup-gpu" not in text and "NVIDIA" not in text and "gpu pair" not in text, f.name
    monkeypatch.delenv("SLOP_GPU", raising=False)
    from slop.onboard import items as I
    r = I._gpu(type("C", (), {"gpu": {"available": True, "mode": "none", "ok": True}})())
    assert r["raw"] == "skipped" and "later update" in r["why"] and "ask" not in r
    assert "Nothing is spent without your yes" in WELCOME and "claudia.gallery" in WELCOME


def test_the_welcome_asks_set_me_up_then_the_setup_asks_have_or_will_get():
    ask = WELCOME[WELCOME.index("## Then ask"):]
    assert '"Set me up?"' in ask and "Set up everything" in ask and "Just the basics" in ask and "Just looking" in ask
    assert "skill claudia-setup, Reply 1" in ask
    setup = read(SKILLS / "claudia-setup" / "SKILL.md")
    assert '"Which do you have, or are willing to get?"' in setup and "Never repeat the welcome" in setup
    assert "run skill claudia-welcome now and stop here" in setup, "an install that skipped the welcome gets it first"
    assert "sign-up page" in setup
    assert "skill claudia-welcome" in read(SKILLS / "profile.md")
