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
    tour = WELCOME[WELCOME.index("**My skills**"):WELCOME.index("**What to subscribe to**")]
    assert [m for m in re.findall(r"^\d+\. ([a-z-]+):", tour, flags=re.M)] == BR.ORDER


def test_the_welcome_names_subscriptions_with_cheaper_alternatives():
    table = WELCOME[WELCOME.index("**What to subscribe to**"):]
    assert "| For | Recommended | Cheaper |" in table
    for must in ("Claude Max", "Claude Pro", "ChatGPT Plus", "Grok Imagine", "Midjourney", "Suno", "Seedance",
                 "OpenRouter", "NVIDIA GPU", "check current prices"):
        assert must in table, must
    assert "Nothing is spent without your yes" in WELCOME and "claudia.gallery" in WELCOME


def test_the_welcome_hands_over_to_the_setup():
    assert "skill claudia-setup, from Reply 1" in WELCOME and "Set me up now" in WELCOME
    setup = read(SKILLS / "claudia-setup" / "SKILL.md")
    assert "never repeat it" in setup and "Which do you have?" in setup
    assert "skill claudia-welcome" in read(SKILLS / "profile.md")
