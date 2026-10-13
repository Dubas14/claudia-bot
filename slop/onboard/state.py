"""$SLOP_HOME/onboard.json - onboarding marks and user settings. CONTRACT: other modules may call the functions below.

Schema (version 1; unknown top-level keys are kept on every write, so other modules may add their own):

    {"version": 1,
     "tier": "quick"|"studio"|"director"|null,          the tier the user chose (slop onboard set tier X)
     "marks": {ITEM: {"state": "done"|"skip"|"todo", "at": ISO, "note": str|null}},
     "settings": {"suno_plan": "free"|"pro"|"premier"|"none",
                  "mj_plan": "basic"|"standard"|"pro"|"mega"|"none",
                  "mj_profile": "<the user's own Midjourney profile code>",    # never shipped: lives in $SLOP_HOME
                  "coding_agents": ["claude"|"codex"|"muse"|"gemini", ...]},  # the user's plans, main first; [] = none
     "agents": {"use": {"director"|"images"|"review": "claude"|"codex"|"muse"|"gemini"}, ...},
                                                         # OWNED by slop.agents (`slop agents use`); read here only
     "unlocked": {KEY: ISO first seen},                  retention: what became possible and when
     "updated": ISO}

NO SECRETS: notes that look like an API key or token, hold an account (mail) address, or mention a password, token or
one-time code are refused (`clean_note`); secrets reach the box only through the Grok Bot secure secret card, as
environment variables, and are reported by NAME only.

Writes take a small lock file (onboard.json.lock, stale after 30 s) and replace the file atomically, so `slop agents
use` and `slop onboard mark` running at the same time cannot lose each other's change.
"""
from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from .. import util
from ..config import SlopError, slop_home

VERSION = 1
TIERS = ("quick", "studio", "director")
MARK_STATES = ("done", "skip", "todo")
SUNO_PLANS = ("free", "pro", "premier", "none")
MJ_PLANS = ("basic", "standard", "pro", "mega", "none")
AGENT_ENGINES = ("claude", "codex", "muse", "gemini")
# what a user may call their coding-agent plan -> the engine (`slop onboard set coding-agents chatgpt` = codex)
ENGINE_WORDS = {"claude": "claude", "claude-code": "claude", "anthropic": "claude", "codex": "codex",
                "chatgpt": "codex", "openai": "codex", "muse": "muse", "muse-code": "muse", "meta": "muse",
                "gemini": "gemini", "gemini-cli": "gemini", "google": "gemini"}
# setting name on the command line -> (key in "settings" or top level, allowed values or None = checked below)
SETTINGS = {
    "tier": ("tier", TIERS),
    "suno-plan": ("suno_plan", SUNO_PLANS),
    "mj-plan": ("mj_plan", MJ_PLANS),
    "mj-profile": ("mj_profile", None),
    "coding-agents": ("coding_agents", None),
}
PROFILE_RE = re.compile(r"[A-Za-z0-9]{3,40}")       # the same rule the plate book uses (board/plates.valid_profile)
NOTE_MAX = 200
# key / token shapes: provider key prefixes, JWTs, PEM blocks, a 32+ run mixing upper case, lower case and digits,
# a 40+ run with no word separator, a 32+ hex run. Hyphen-joined plain words ("studio-tier-with-higgsfield-plan") pass.
SECRET_RE = re.compile(
    r"(?:\bsk-[A-Za-z0-9_-]{8,}"
    r"|\b(?:ghp_|gho_|ghs_|github_pat_|xox[abprs]-|AKIA|AIza|hf_|glpat-)[A-Za-z0-9_-]{8,}"
    r"|\beyJ[A-Za-z0-9_-]{10,}"
    r"|-----BEGIN"
    r"|(?=[A-Za-z0-9+/=_-]*[0-9])(?=[A-Za-z0-9+/=_-]*[a-z])(?=[A-Za-z0-9+/=_-]*[A-Z])[A-Za-z0-9+/=_-]{32,}"
    r"|[A-Za-z0-9+/=]{40,}"
    r"|\b(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{32,}\b)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# words that say a sign-in secret is in the note ("password hunter2", "pw: x", "otp 123456", "token abc")
SIGNIN_WORDS_RE = re.compile(r"(?i)\b(password|passwd|passcode|passphrase|pwd|pw|pin|otp|totp|2fa|mfa|secret|token|"
                             r"api[ _-]?key|login code|auth code|one[ -]time code|recovery code|verification code)\b")
SAFE_PHRASES_RE = re.compile(r"(?i)\bsetup-token\b|\b(?:secure )?secret card\b")
LOCK_STALE_S = 30.0


def path() -> Path:
    return slop_home() / "onboard.json"


def empty() -> dict:
    return {"version": VERSION, "tier": None, "marks": {}, "settings": {}, "unlocked": {}}


def load() -> dict:
    """The state (an empty one when the file does not exist yet). A broken file is a SlopError with the way out."""
    p = path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty()
    except OSError as e:
        raise SlopError(f"cannot read {p}: {e}") from None
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError as e:
        raise SlopError(f"{p} is not valid JSON ({e}). Move it aside and start the checklist again (checked items "
                        f"re-check themselves; marks and settings are re-recorded): mv {p} {p}.bad") from None
    if not isinstance(data, dict):
        raise SlopError(f"{p} must hold one JSON object; move it aside: mv {p} {p}.bad")
    out = empty()
    out.update(data)
    for k in ("marks", "settings", "unlocked"):
        if not isinstance(out.get(k), dict):
            out[k] = {}
    if out.get("tier") not in TIERS:
        out["tier"] = None
    return out


@contextmanager
def _locked(timeout: float = 10.0):
    lock = path().with_name(path().name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.time() - t0 > timeout:
                raise SlopError(f"{lock} is held by another slop command; try again in a moment (delete it if no "
                                "slop command is running)") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def update(fn: Callable[[dict], None]) -> dict:
    """Read-modify-write under the lock; `fn(data)` changes `data` in place. Returns the saved state."""
    with _locked():
        data = load()
        fn(data)
        data["version"] = VERSION
        data["updated"] = util.iso_now()
        util.atomic_write_json(path(), data)
    return data


# ---------------------------------------------------------------- validation
def check_no_secret(text: str, what: str) -> None:
    if text and SECRET_RE.search(text):
        raise SlopError(f"{what} looks like it holds a secret (a key or token), so it was NOT saved. Onboarding never "
                        "stores secrets: they go only through the bot's secure secret card into an environment "
                        "variable. Write the note again without it.")


def clean_note(note: str | None) -> str | None:
    """One short line of context, or a SlopError when it holds a secret, an account address or sign-in words.
    Longer than NOTE_MAX: cut at the last whole word first (so half a word is never stored), then checked."""
    if note is None:
        return None
    n = " ".join(str(note).split())
    if len(n) > NOTE_MAX:
        n = n[:NOTE_MAX]
        n = n.rsplit(" ", 1)[0] if " " in n else n
    if not n:
        return None
    check_no_secret(n, "the note")
    if EMAIL_RE.search(n):
        raise SlopError("the note holds an account (mail) address, so it was NOT saved. Onboarding never stores "
                        "account details: write the plan only, e.g. --note 'Max plan'.")
    w = SIGNIN_WORDS_RE.search(SAFE_PHRASES_RE.sub(" ", n))
    if w:
        raise SlopError(f"the note mentions {w.group(0)!r}, so it was NOT saved: onboarding never stores passwords, "
                        "tokens or sign-in codes (secrets go only through the bot's secure secret card). Write the "
                        "note again without it, e.g. --note 'Max plan, Windows laptop'.")
    return n


def parse_coding_agents(value: str) -> list[str]:
    """'claude,chatgpt' -> ['claude', 'codex'] (main first, no repeats); 'none' -> []."""
    words = [w for w in re.split(r"[\s,;+/]+", str(value or "").strip().lower()) if w and w != "and"]
    if words in (["none"], ["no"]):
        return []
    out: list[str] = []
    for w in words:
        e = ENGINE_WORDS.get(w)
        if e is None:
            raise SlopError(f"coding-agents takes engine names: claude, codex (ChatGPT plan), muse, gemini - several "
                            f"comma-separated, the main one first - or none (got {w!r}); nothing was saved. Example: "
                            "slop onboard set coding-agents claude,codex")
        if e not in out:
            out.append(e)
    if not out:
        raise SlopError("coding-agents needs a value: claude, codex, muse, gemini (comma-separated) or none")
    return out


def valid_mj_profile(code: str) -> str:
    c = str(code or "").strip()
    if c.startswith("--"):                       # `--profile abc123` pasted whole
        parts = c.split()
        c = parts[1] if len(parts) > 1 else ""
    if not PROFILE_RE.fullmatch(c):
        raise SlopError("a Midjourney profile code is 3-40 letters and digits (the text after --profile in your "
                        "Midjourney settings); nothing was saved. Example shape: slop onboard set mj-profile abc123x")
    return c


def mask(code: str | None) -> str | None:
    """Show a personal code without echoing it whole: 'ab… (7 characters)'."""
    if not code:
        return None
    return f"{code[:2]}… ({len(code)} characters)"


# ---------------------------------------------------------------- writers (public API)
def set_mark(item: str, state: str, note: str | None = None) -> dict:
    if state not in MARK_STATES:
        raise SlopError(f"mark state must be one of {', '.join(MARK_STATES)}")
    note = clean_note(note)

    def fn(d: dict) -> None:
        if state == "todo":
            d["marks"].pop(item, None)
        else:
            d["marks"][item] = {"state": state, "at": util.iso_now(), "note": note}
    return update(fn)


def set_setting(name: str, value: str | None) -> dict:
    """name = a SETTINGS key (tier, suno-plan, mj-plan, mj-profile); value None clears it."""
    if name not in SETTINGS:
        raise SlopError(f"unknown setting {name!r}: one of {', '.join(SETTINGS)}")
    key, allowed = SETTINGS[name]
    if value is not None:
        value = str(value).strip()
        if allowed is not None:
            value = value.lower()
            if value not in allowed:
                raise SlopError(f"{name} must be one of: {', '.join(allowed)} (got {value!r})")
        elif name == "mj-profile":
            value = valid_mj_profile(value)
        elif name == "coding-agents":
            value = parse_coding_agents(value)

    def fn(d: dict) -> None:
        if key == "tier":
            d["tier"] = value
        elif value is None:
            d["settings"].pop(key, None)
        else:
            d["settings"][key] = value
    return update(fn)


def coding_agents(data: dict | None = None) -> list[str] | None:
    """The user's coding-agent plans as engines, main first ([] = none; None = not recorded yet)."""
    d = data if data is not None else load()
    s = d.get("settings") if isinstance(d.get("settings"), dict) else {}
    v = s.get("coding_agents")
    if not isinstance(v, list):
        return None
    return [e for e in v if e in AGENT_ENGINES]


def agent_use(role: str, data: dict | None = None) -> str | None:
    """The engine `slop agents use ENGINE --for ROLE` chose (slop.agents writes onboard.json "agents"."use")."""
    d = data if data is not None else load()
    ag = d.get("agents")
    use = ag.get("use") if isinstance(ag, dict) else None
    v = use.get(role) if isinstance(use, dict) else None
    return v if v in AGENT_ENGINES else None


def record_unlocks(keys: list[str]) -> dict:
    """Remember the first time each unlock was seen; returns {key: iso} for the keys that are NEW."""
    new: dict[str, str] = {}

    def fn(d: dict) -> None:
        for k in keys:
            if k not in d["unlocked"]:
                d["unlocked"][k] = new[k] = util.iso_now()
    current = load().get("unlocked") or {}
    if all(k in current for k in keys):
        return {}
    update(fn)
    return new
