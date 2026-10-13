"""`slop agents …` — coding agents (Claude Code, Codex, Muse Code, Gemini CLI) on this computer.

On the bot's computer:  install -> login -> test -> use. Every step prints the exact next command.
On the user's own computer (the "home computer"): the same commands, run through Grok Bot's local exec once the
toolkit runtime is installed there (runner/README.md §1); the sign-in links then open on that computer's browser
directly, so the user can also just run `claude`, `codex login`, `muse login` or `gemini` in a terminal there.

  slop agents status [ENGINE] [--limits]
  slop agents install ENGINE|all [--method native|npm] [--upgrade]     (runs as a background `slop job`)
  slop agents login ENGINE [--force]                                   prints the link (+ code) for the user
  slop agents login claude|gemini --code-from-env CLAUDE_LOGIN_CODE|GEMINI_LOGIN_CODE   the code the page showed
  slop agents login ENGINE --check | --cancel
  slop agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN    (from `claude setup-token` on the user's computer)
  slop agents login gemini --key-from-env GEMINI_API_KEY
  slop agents test ENGINE [--job DIR]                                  one tiny "reply OK" run (runner/deleg.mjs preflight)
  slop agents use [ENGINE --for director|review|images]                prints exactly which briefs follow the choice

Install places (bot's computer): every command under $SLOP_HOME (/workspace/.claudia), incl. a copy of Claude Code's
native binary; sign-ins stay in the home folder (`slop agents login` again if a computer reset clears them).
"""
from __future__ import annotations

import json
import os
import re
import time

from ..config import SlopError, toolkit_root
from . import engines as E

ENGINE_HELP = "claude | codex | muse | gemini"


def _engines(arg: str | None) -> list[str]:
    if not arg or arg == "all":
        return list(E.ENGINES)
    return [E.norm_engine(arg)]


# ------------------------------------------------------------------------------------------------------- commands
def cmd_status(a) -> dict:
    from . import status
    return status.status(_engines(getattr(a, "engine", None)), limits=bool(getattr(a, "limits", False)))


def _in_job() -> bool:
    return bool(os.environ.get("SLOP_JOB_ID"))


def cmd_install(a) -> dict:
    from . import install
    target = E.norm_engine(a.engine, allow_all=True)
    engines = list(E.ENGINES) if target == "all" else [target]
    if a.method and target == "all":
        raise SlopError("--method applies to one engine: slop agents install claude --method npm")
    if a.method:
        install.method_for(target, a.method)                 # validate before a job starts
    if a.dry_run:
        plans = [install.plan(e, a.method) for e in engines]
        return {"ok": True, "dry_run": True, "plans": plans,
                "text": "would run:\n" + "\n".join(f"  {p['engine']}: {p['command']}"
                                                   + (f"  -> {p['link']}" if p.get("link") else "") for p in plans)}
    if not (_in_job() or a.foreground):
        from .. import job
        words = ["agents", "install", target] + (["--method", a.method] if a.method else []) + \
                (["--upgrade"] if a.upgrade else [])
        r = job.start(words)
        s = r["job"]
        return {"ok": True, "job": s, "id": s["id"], "existing": r["existing"], "next": s["wait"],
                "text": (f"{'already running' if r['existing'] else 'started'} job {s['id']}: install "
                         f"{', '.join(engines)} into {E.slop_home()} (npm installs take seconds, the vendor installers "
                         f"up to a few minutes). Next: {s['wait']}")}
    return install.install(engines, a.method, a.upgrade)


def cmd_login(a) -> dict:
    from . import login
    eng = E.norm_engine(a.engine)
    modes = [m for m in ("code_from_env", "token_from_env", "key_from_env", "check", "cancel") if getattr(a, m)]
    if len(modes) > 1:
        raise SlopError("use one of --code-from-env / --token-from-env / --key-from-env / --check / --cancel at a time")
    if a.code_from_env:
        return login.send_code(eng, a.code_from_env)
    if a.token_from_env:
        return login.token_from_env(eng, a.token_from_env)
    if a.key_from_env:
        return login.key_from_env(eng, a.key_from_env)
    if a.check:
        return login.check(eng)
    if a.cancel:
        return login.cancel(eng)
    return login.start(eng, force=a.force)


def cmd_login_session(a) -> dict:
    from . import login
    return login.run_session(E.norm_engine(a.engine), ttl=float(a.ttl))


def cmd_test(a) -> dict:
    from .. import util
    from . import status
    eng = E.norm_engine(a.engine)
    title = E.SPEC[eng]["title"]
    s = None
    if not a.job:
        s = status.engine_status(eng)
        if not s["installed"]:
            return {"ok": False, "skipped": True, "engine": eng, "error": f"{title} is not installed, so the test was "
                    f"skipped", "next": f"slop agents install {eng}", "text": f"skipped: {title} is not installed. "
                    f"Next: slop agents install {eng}"}
        if not s["logged_in"]:
            return {"ok": False, "skipped": True, "engine": eng, "error": f"{title} is not signed in, so the test was "
                    f"skipped", "next": f"slop agents login {eng}", "text": f"skipped: {title} is not signed in. "
                    f"Next: slop agents login {eng}"}
    node = E.node_path()
    if not node:
        raise SlopError("node is not installed: the test runs through runner/deleg.mjs (Node 18+)")
    deleg = toolkit_root() / "runner" / "deleg.mjs"
    argv = [node, str(deleg), "preflight", eng]
    if a.job:
        argv += ["--job", a.job]
    else:
        argv += ["--dir", str(E.agents_dir() / "tests")]
        if eng == "gemini" and s and s.get("auth") == "api_key":
            argv.append("--allow-api-billing")           # the user chose the key as Gemini's sign-in
    t0 = time.monotonic()
    rc, out, err = util.run(argv, timeout=120, env=E.base_env(eng, plan_only=False))
    secs = round(time.monotonic() - t0, 1)
    res = None
    for line in reversed(out.strip().splitlines()):
        try:
            res = json.loads(line)
            break
        except ValueError:
            continue
    if not isinstance(res, dict):
        raise SlopError(f"runner/deleg.mjs preflight gave no JSON (exit {rc}): {(err or out).strip()[-400:]}")
    state = res.get("state")
    base = {"engine": eng, "secs": secs, "job": res.get("job"), "state": state, "model": res.get("model"),
            "reply": (res.get("result_text") or "")[:200], "preflight_ok": bool(res.get("preflight_ok"))}
    if state in ("queued", "starting", "running"):
        nxt = f"slop agents test {eng} --job {res.get('job')}"
        return {"ok": True, **base, "running": True, "next": nxt,
                "text": f"{title} is still answering after {secs} s. Next: {nxt}"}
    if res.get("preflight_ok"):
        extra = ""
        if eng == "claude" and res.get("has_workflow_tool") is False:
            extra = " (no Workflow tool on this plan: workflow jobs need \"workflows_env\": true)"
        if eng == "gemini" and s and s.get("auth") == "api_key":
            extra = f" (with GEMINI_API_KEY). {GEMINI_KEY_JOBS}"
        return {"ok": True, **base, "has_workflow_tool": res.get("has_workflow_tool"), "next": f"slop agents use {eng} "
                "--for director", "text": f"{title} works: it replied in {secs} s"
                + (f" as {res.get('model')}" if res.get("model") else "") + extra
                + f". Next: slop agents use {eng} --for director"}
    err_txt = res.get("error") or f"no PREFLIGHT-OK reply (state {state})"
    out = {"ok": False, **base, "error": f"{title} test failed: {err_txt}"[:800], "fix": res.get("fix"),
           "next": f"slop agents status {eng}",
           "text": f"{title} test FAILED after {secs} s: {err_txt}"[:800] + f"\n  details: {res.get('job')}"}
    if SIGNIN_REJECTED_RE.search(err_txt):           # status cannot see this (it checks offline): never loop back to it
        nxt, ask = _signin_fix(eng, s)
        out.update(signin_rejected=True, next=nxt, **({"ask_user": ask} if ask else {}))
        out["text"] += "\n  the sign-in was rejected. " + (f"{ask}. Then: {nxt}" if ask else f"Next: {nxt}")
    return out


# The runner strips API keys from every job unless the run command grants them; a Gemini API-key sign-in therefore
# reaches delegated jobs only through the pass-env gate (runner/deleg.mjs `new --engine gemini` writes it into job.json).
GEMINI_KEY_JOBS = ("Delegated Gemini jobs get the key only through the pass-env gate: `deleg.mjs new --engine gemini` "
                   "adds \"pass_env\": [\"GEMINI_API_KEY\"] to job.json, and the run/start command then needs "
                   "--pass-env GEMINI_API_KEY (ask the user first: a key can bill the Google Cloud project behind it)")


# An engine answer that means "this sign-in is not accepted" (expired, revoked, wrong): a new sign-in is the fix.
SIGNIN_REJECTED_RE = re.compile(
    r"(?i)\b401\b|authenticat|unauthori[sz]ed|invalid[^.\n]{0,40}(?:token|api key|credential|bearer)|"
    r"token[^.\n]{0,20}(?:expired|revoked)|not logged in|please (?:log|sign) ?in|invalid_grant|api key not valid")


def _signin_fix(eng: str, s: dict | None) -> tuple[str, str | None]:
    """(next command, what to ask the user first) after the engine rejected its sign-in."""
    auth = (s or {}).get("auth")
    if eng == "claude" and (auth == "oauth_token" or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
        from .status import TOKEN_NEXT, TOKEN_REJECTED
        return TOKEN_NEXT, TOKEN_REJECTED
    if eng == "gemini" and auth == "api_key":
        return ("slop agents login gemini --key-from-env GEMINI_API_KEY",
                "Google rejected GEMINI_API_KEY: ask the user for a new key (aistudio.google.com) with the secure secret "
                "card named GEMINI_API_KEY (it replaces the old one), or to delete it and sign in with "
                "`slop agents login gemini`")
    return f"slop agents login {eng} --force", None


def cmd_use(a) -> dict:
    from . import prefs
    eng = E.norm_engine(a.engine) if a.engine else None
    return prefs.cmd_use(eng, a.role)


# ------------------------------------------------------------------------------------------------------- register
def register(sub) -> None:
    g = sub.add_parser("agents", help="coding agents on this computer: Claude Code, Codex, Muse Code, Gemini CLI "
                                      "(install, sign in, test, choose)")
    g.set_defaults(func=cmd_status, engine=None, limits=False)
    gs = g.add_subparsers(dest="agents_cmd", metavar="ACTION")

    p = gs.add_parser("status", help="installed? version? signed in (plan)? --limits: plan usage, no tokens spent")
    p.add_argument("engine", nargs="?", help=ENGINE_HELP + " (default: all)")
    p.add_argument("--limits", action="store_true", help="also read plan usage windows where the CLI allows it")
    p.set_defaults(func=cmd_status)

    p = gs.add_parser("install", help="install into $SLOP_HOME (survives a computer update); runs as a background job")
    p.add_argument("engine", help=ENGINE_HELP + " | all")
    p.add_argument("--method", choices=["native", "npm"], help="claude: native (default, the official installer) or npm")
    p.add_argument("--upgrade", action="store_true", help="install the latest even if one is installed")
    p.add_argument("--dry-run", action="store_true", help="print what would run")
    p.add_argument("--foreground", action="store_true", help="run here instead of as a background job")
    p.set_defaults(func=cmd_install)

    p = gs.add_parser("login", help="sign in headless: prints the link (and code) for the user; see --code-from-env")
    p.add_argument("engine", help=ENGINE_HELP)
    p.add_argument("--code-from-env", metavar="NAME", help="feed the code the sign-in page showed, from the secure "
                   "secret card's env var: only CLAUDE_LOGIN_CODE (claude) or GEMINI_LOGIN_CODE (gemini)")
    p.add_argument("--token-from-env", metavar="NAME", help="claude: use CLAUDE_CODE_OAUTH_TOKEN (from `claude "
                   "setup-token` on the user's computer)")
    p.add_argument("--key-from-env", metavar="NAME", help="gemini: use GEMINI_API_KEY (only that name)")
    p.add_argument("--check", action="store_true", help="wait up to 25 s for the waiting sign-in to finish")
    p.add_argument("--cancel", action="store_true", help="stop a waiting sign-in")
    p.add_argument("--force", action="store_true", help="start a new sign-in even when already signed in")
    p.set_defaults(func=cmd_login)

    p = gs.add_parser("_login-session")          # internal: the sign-in keeper job (no help = not in the command list)
    p.add_argument("engine")
    p.add_argument("--ttl", type=float, default=15 * 60)
    p.set_defaults(func=cmd_login_session)

    p = gs.add_parser("test", help='one tiny "reply OK" run through runner/deleg.mjs (skipped when not signed in)')
    p.add_argument("engine", help=ENGINE_HELP)
    p.add_argument("--job", help="re-read a test that was still running (the job folder it printed)")
    p.set_defaults(func=cmd_test)

    p = gs.add_parser("use", help="which agent does what: --for director|review|images (no args: show)")
    p.add_argument("engine", nargs="?", help=ENGINE_HELP)
    p.add_argument("--for", dest="role", choices=["director", "review", "images"])
    p.set_defaults(func=cmd_use)

    try:                                       # `slop gen image --provider codex` (the ChatGPT plan's image tool)
        from ..gen import images
        images.install_provider_flag(sub)
    except (ImportError, AttributeError):
        pass
