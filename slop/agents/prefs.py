"""`slop agents use ENGINE --for director|images|review`: which agent does which job, kept in $SLOP_HOME/onboard.json.

Only the "agents" key of onboard.json belongs to this module ({"agents": {"use": {"director": "claude", ...}}}); every
other key (the onboarding checklist) is left as it is. Writes go through slop.onboard.state.update() (its lock file
onboard.json.lock), so `slop agents use` and `slop onboard ...` at the same time never lose each other's change.
Readers:
  director  runner/deleg.mjs `new` (without --engine): the engine of a delegated job WHEN the brief's "engines:" line
            lists it. A brief that runs a Claude workflow (storyboard-panel, research-lyrics, chapter-motion,
            safety-scan) then runs WITHOUT the workflow, in sequence (the brief's method B). A brief that does not list
            the engine stays on Claude and `new` says so. `brief_plan()` below lists exactly which brief does what.
  review    the same for review and safety-scan briefs (else they follow the director engine)
  images    `codex` = `slop gen image` without --provider makes stills on the ChatGPT plan (--provider codex; $0, plan
            limits; experimental until a real plan has made one); --provider openrouter still picks the API models
Gemini CLI is not offered as director or review agent: no brief lists it, and headless Gemini runs without shell
commands (the briefs' checks run `slop`, `node`, `ffmpeg`). `deleg.mjs new --engine gemini` still runs one job on it.
"""
from __future__ import annotations

import json
import re

from .. import util
from ..config import SlopError, slop_home, toolkit_root
from . import engines as E

ROLES = {
    "director": "delegated jobs whose brief lists the engine (runner/deleg.mjs new without --engine)",
    "review": "review and safety-scan jobs whose brief lists the engine (else the director agent)",
    "images": "slop gen image without --provider: stills on the ChatGPT plan via Codex (--provider codex)",
}
IMAGE_ENGINES = ("codex",)
JOB_ENGINES = ("claude", "codex", "muse")          # engines the briefs list (director / review)
REVIEW_RE = re.compile(r"review|safety")           # the same rule as runner/deleg.mjs preferredEngine()


def onboard_file():
    return slop_home() / "onboard.json"


def read_all() -> dict:
    f = onboard_file()
    if not f.is_file():
        return {}
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SlopError(f"{f} is not valid JSON ({e}); fix it or move it aside, then run the command again") from e
    return d if isinstance(d, dict) else {}


def get_use() -> dict:
    return dict(((read_all().get("agents") or {}).get("use")) or {})


def _write(fn) -> dict:
    """Read-modify-write onboard.json under the onboarding module's lock (same file, same lock)."""
    try:
        from ..onboard import state as ob
    except ImportError:                              # toolkit without the onboarding module: same lock file by hand
        ob = None
    if ob is not None and hasattr(ob, "update"):
        return ob.update(fn)
    import os
    import time
    lock = onboard_file().with_name("onboard.json.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.time() - t0 > 10:
                raise SlopError(f"{lock} is held by another slop command; try again in a moment") from None
            time.sleep(0.05)
    try:
        data = read_all()
        fn(data)
        util.atomic_write_json(onboard_file(), data)
        return data
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def set_use(engine: str, role: str) -> dict:
    if role not in ROLES:
        raise SlopError(f"--for takes one of: {', '.join(ROLES)}")
    if role == "images" and engine not in IMAGE_ENGINES:
        raise SlopError("only codex makes images on a plan (the ChatGPT plan's image generation): "
                        "slop agents use codex --for images")
    if role in ("director", "review") and engine not in JOB_ENGINES:
        raise SlopError(f"{E.SPEC[engine]['title']} cannot be the {role} agent: no brief lists it, and headless "
                        "Gemini CLI runs without shell commands, which every brief's checks need (slop, node, ffmpeg). "
                        "Choose claude, codex or muse: slop agents use claude --for "
                        f"{role}. One job can still run on it: node runner/deleg.mjs new ... --engine {engine}")

    def fn(data: dict) -> None:
        ag = data.get("agents") if isinstance(data.get("agents"), dict) else {}
        use = ag.get("use") if isinstance(ag.get("use"), dict) else {}
        use[role] = engine
        ag["use"] = use
        ag["updated"] = util.iso_now()
        data["agents"] = ag
    data = _write(fn)
    return dict((data.get("agents") or {}).get("use") or {})


# ------------------------------------------------------------------------------------------------- which brief does what
def _briefs() -> list[dict]:
    """[{name, engines, workflow}] from templates/briefs/*.md headers (the runner reads the same lines)."""
    out = []
    d = toolkit_root() / "templates" / "briefs"
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            head = f.read_text(encoding="utf-8").split("-->", 1)[0]
        except OSError:
            continue
        name = re.search(r"^\s*slop-brief:\s*(\S+)", head, re.M)
        eng = re.search(r"^\s*engines:\s*(.*)$", head, re.M)
        dfl = re.search(r"^\s*defaults:\s*(\{.*\})\s*$", head, re.M)
        wf = None
        if dfl:
            try:
                wf = json.loads(dfl.group(1)).get("workflow")
            except ValueError:
                wf = None
        out.append({"name": name.group(1) if name else f.stem, "engines": eng.group(1).strip() if eng else "",
                    "workflow": wf})
    return out


def brief_plan(engine: str, role: str, use: dict | None = None) -> dict:
    """What `deleg.mjs new` (without --engine) does for each brief this role covers, with `engine` as the role's agent:
    {"as_is": [...], "in_sequence": [...] (workflow briefs run without the Claude workflow), "claude": [...]}."""
    use = use or {}
    out: dict[str, list[str]] = {"as_is": [], "in_sequence": [], "claude": []}
    for b in _briefs():
        is_review = bool(REVIEW_RE.search(b["name"]))
        if role == "director" and is_review and use.get("review"):
            continue                                        # the review agent decides those
        if role == "review" and not is_review:
            continue
        listed = not b["engines"] or re.search(rf"\b{engine}\b", b["engines"])
        if engine == "claude" or (listed and not b["workflow"]):
            out["as_is"].append(b["name"])
        elif listed:
            out["in_sequence"].append(b["name"])
        else:
            out["claude"].append(b["name"])
    return out


def _plan_text(engine: str, role: str, use: dict) -> str:
    p = brief_plan(engine, role, use)
    t = E.SPEC[engine]["title"]
    parts = []
    if p["as_is"]:
        parts.append(f"{t} runs: {', '.join(p['as_is'])}")
    if p["in_sequence"]:
        parts.append(f"{t} runs WITHOUT the Claude workflow, step by step: {', '.join(p['in_sequence'])} "
                     "(slower; for the workflow add --engine claude)")
    if p["claude"]:
        parts.append(f"still Claude Code (the brief does not list {engine}): {', '.join(p['claude'])}")
    return "; ".join(parts) or "no brief is affected"


def cmd_use(engine: str | None, role: str | None) -> dict:
    if not engine:
        use = get_use()
        lines = ["agent preferences (" + str(onboard_file()) + "):"]
        for r, what in ROLES.items():
            lines.append(f"  {r:<9}{use.get(r) or '-':<8}{what}")
        lines.append("set one: slop agents use ENGINE --for director|review|images")
        return {"ok": True, "use": use, "text": "\n".join(lines)}
    if not role:
        raise SlopError("say what the agent is for: slop agents use ENGINE --for director|review|images")
    if role in ("director", "review") and engine not in JOB_ENGINES:
        set_use(engine, role)                         # raises with the reason and the way out
    from .status import engine_status
    s = engine_status(engine)
    if not s["installed"]:
        raise SlopError(f"{E.SPEC[engine]['title']} is not installed: slop agents install {engine} (then sign in)")
    use = set_use(engine, role)
    warn = "" if s["logged_in"] else f"\n  ! {E.SPEC[engine]['title']} is not signed in yet: slop agents login {engine}"
    briefs = None
    if role in ("director", "review"):
        briefs = brief_plan(engine, role, use)
        how = "with runner/deleg.mjs new (no --engine): " + _plan_text(engine, role, use)
        if role == "director" and not use.get("review"):
            how += ". Review briefs follow this choice too until: slop agents use ENGINE --for review"
    else:
        how = ("`slop gen image` without --provider now means --provider codex: stills on the ChatGPT plan via Codex "
               "(a background job; $0, the plan's image limits, 1-4 min per image; EXPERIMENTAL: not yet checked with a "
               "real plan). --provider openrouter (or --model) still uses the API models. Example: slop -p NAME gen "
               "image --plate P \"prompt\"")
    return {"ok": True, "use": use, "engine": engine, "role": role, "logged_in": s["logged_in"],
            **({"briefs": briefs} if briefs is not None else {}),
            "next": f"slop agents login {engine}" if not s["logged_in"] else f"slop agents test {engine}",
            "text": f"{E.SPEC[engine]['title']} is now the {role} agent: {how}{warn}"}
