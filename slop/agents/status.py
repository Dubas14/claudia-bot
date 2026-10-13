"""`slop agents status [ENGINE] [--limits]`: installed? version? signed in, with which plan? plan usage?

Nothing here spends a token or prints a secret:
  claude  `claude auth status --json` (loggedIn, authMethod, subscriptionType, email). Limits: GET
          https://api.anthropic.com/api/oauth/usage with the plan's own OAuth token (from ~/.claude/.credentials.json
          or CLAUDE_CODE_OAUTH_TOKEN) and the header anthropic-beta: oauth-2025-04-20 - the read Claude Code's /usage
          makes (verified: a bad token answers 401 "Invalid bearer token"). The token never leaves this process.
  codex   `codex login status` (exit 1 when logged out); plan and limits from a throwaway
          `codex app-server --listen stdio://` (JSON-RPC: initialize, account/read, account/rateLimits/read; API-key
          variables removed and -c forced_login_method="chatgpt"). Logged out it answers account null and
          "codex account authentication required to read rate limits" (verified, 0.2 s).
  muse    the credential file's presence ($XDG_CONFIG_HOME/muse/auth.json; never read beyond which keys exist).
          Muse reports usage only inside a session, so there is no limits read.
  gemini  ~/.gemini/oauth_creds.json (+ google_accounts.json for the account) or GEMINI_API_KEY in the environment.
          No account-level usage read either.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

from .. import util
from . import engines as E


def mask_account(a) -> str | None:
    """Never show a full account address (docs/96 §2.3): 'alex@example.com' -> 'a***@e***.com'."""
    if not a or not isinstance(a, str):
        return None
    if "@" not in a:
        return a[:1] + "***"
    user, _, dom = a.partition("@")
    host, dot, tld = dom.rpartition(".")
    return f"{user[:1]}***@{(host or dom)[:1]}***" + (f".{tld}" if dot else "")

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
RPC_TIMEOUT_S = 12.0


# ------------------------------------------------------------------------------------------------- per engine
def _claude(s: dict) -> None:
    rc, out, err = E.run_cli("claude", ["auth", "status", "--json"], timeout=30)
    data = None
    try:
        data = json.loads(out[out.index("{"):]) if "{" in out else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        s.update(logged_in=None, detail=(err or out).strip()[-200:] or f"auth status exit {rc}")
        return
    s["logged_in"] = bool(data.get("loggedIn"))
    m = data.get("authMethod")
    s["auth"] = m if m not in (None, "none") else None
    s["plan"] = data.get("subscriptionType") or data.get("plan")
    s["account"] = mask_account(data.get("email") or data.get("emailAddress"))
    if m == "oauth_token":
        s["auth_text"] = "plan token from CLAUDE_CODE_OAUTH_TOKEN"
    elif m in ("claude.ai", "claudeai", "oauth"):
        s["auth_text"] = "Claude plan"
    elif m:
        s["auth_text"] = str(m)
    if os.environ.get("ANTHROPIC_API_KEY"):
        s.setdefault("notes", []).append("ANTHROPIC_API_KEY is set: plan runs (slop agents test, delegated jobs) "
                                         "remove it so nothing bills the API")


def _codex(s: dict) -> None:
    rc, out, err = E.run_cli("codex", ["login", "status"], timeout=30)
    text = (out + "\n" + err).strip()
    if rc == 0 and "logged in" in text.lower():
        s["logged_in"] = True
        s["auth"] = "chatgpt" if "chatgpt" in text.lower() else ("api_key" if "key" in text.lower() else "other")
        s["auth_text"] = {"chatgpt": "ChatGPT plan", "api_key": "an API key (bills per token; plan runs ignore it)"}\
            .get(s["auth"], "signed in")
        acct = codex_account()
        if acct.get("ok"):
            a = acct.get("account") or {}
            s["plan"] = a.get("planType") or a.get("plan_type") or a.get("plan")
            s["account"] = mask_account(a.get("email"))
    else:
        s["logged_in"] = False if rc in (0, 1) else None
        if rc not in (0, 1):
            s["detail"] = text[-200:]
    for k in ("OPENAI_API_KEY", "CODEX_API_KEY"):
        if os.environ.get(k):
            s.setdefault("notes", []).append(f"{k} is set: plan runs remove it and force the ChatGPT sign-in")


def _muse(s: dict) -> None:
    f = E.muse_auth_file()
    data = E.read_json_quiet(f)
    prov = ((data or {}).get("providers") or {}).get("meta") if data else None
    if isinstance(prov, dict) and any(prov.get(k) for k in ("access_token", "refresh_token")):
        s.update(logged_in=True, auth="meta_account", auth_text="Meta account")
    elif isinstance(prov, dict) and prov.get("api_key"):
        s.update(logged_in=True, auth="api_key", auth_text="a stored Meta API key")
    else:
        s["logged_in"] = False
    if os.environ.get("META_API_KEY"):
        s.setdefault("notes", []).append("META_API_KEY is set: it takes priority over the account login; plan runs "
                                         "remove it")


def _gemini(s: dict) -> None:
    d = E.gemini_dir()
    creds = d / "oauth_creds.json"
    settings = E.read_json_quiet(d / "settings.json") or {}
    sel = ((settings.get("security") or {}).get("auth") or {}).get("selectedType") or settings.get("selectedAuthType")
    s["selected_auth"] = sel
    if creds.is_file():
        s.update(logged_in=True, auth="google_account", auth_text="Google account")
        acc = E.read_json_quiet(d / "google_accounts.json") or {}
        s["account"] = mask_account(acc.get("active"))
    elif os.environ.get("GEMINI_API_KEY"):
        s.update(logged_in=True, auth="api_key", auth_text="GEMINI_API_KEY")
        if sel != "gemini-api-key":
            s.setdefault("notes", []).append("run `slop agents login gemini --key-from-env GEMINI_API_KEY` once so the "
                                             "CLI uses the key")
    else:
        s["logged_in"] = False


PROBES = {"claude": _claude, "codex": _codex, "muse": _muse, "gemini": _gemini}


def engine_status(engine: str, limits: bool = False) -> dict:
    spec = E.SPEC[engine]
    s: dict = {"engine": engine, "title": spec["title"], "installed": False, "bin": None, "via": None,
               "version": None, "logged_in": None, "auth": None, "plan": None, "account": None}
    b = E.find(engine)
    if b:
        s.update(installed=True, bin=b["path"], via=b["via"])
        s["version"] = E.version(engine)
        if s["version"] is None:
            s["installed"] = False
            s["detail"] = f"{b['path']} is there but `--version` does not run (reinstall: slop agents install {engine})"
    if s["installed"]:
        try:
            PROBES[engine](s)
        except Exception as e:  # noqa: BLE001 - a broken probe must not hide the other engines
            s["detail"] = f"status probe failed: {e}"
    try:
        from .login import read_state, WAITING
        ls = read_state(engine)
        if ls and ls.get("alive") and ls.get("state") in WAITING:
            s["login_pending"] = {k: ls.get(k) for k in ("state", "url", "user_code", "expires_at")}
    except Exception:  # noqa: BLE001
        pass
    if not s["installed"]:
        s["next"] = f"slop agents install {engine}"
    elif s.get("login_pending"):
        s["next"] = f"slop agents login {engine} --check"
    elif not s["logged_in"]:
        s["next"] = f"slop agents login {engine}"
    else:
        s["next"] = f"slop agents test {engine}"
    if limits and s["installed"] and s["logged_in"]:
        s["limits"] = read_limits(engine)
    return s


# ------------------------------------------------------------------------------------------------- limits
def read_limits(engine: str) -> dict:
    if engine == "claude":
        return claude_limits()
    if engine == "codex":
        return codex_limits()
    if engine == "muse":
        return {"available": False, "why": "Muse Code reports plan usage only inside a running session"}
    return {"available": False, "why": "Gemini CLI shows usage only inside a session (/stats)"}


def _claude_token() -> tuple[str | None, str]:
    env = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env:
        return env, "CLAUDE_CODE_OAUTH_TOKEN"
    f = E.claude_config_dir() / ".credentials.json"
    d = E.read_json_quiet(f) or {}
    o = d.get("claudeAiOauth") or {}
    tok = o.get("accessToken")
    if tok:
        exp = o.get("expiresAt")
        try:
            if exp and float(exp) / (1000 if float(exp) > 1e11 else 1) < time.time():
                return None, "expired"
        except (TypeError, ValueError):
            pass
        return tok, "credentials file"
    return None, "none"


def _pct(v) -> float | None:
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def parse_claude_usage(d: dict) -> list[dict]:
    """Windows from the usage endpoint: a `limits` list, else the keys five_hour / seven_day / seven_day_opus /
    seven_day_sonnet ({utilization (percent), resets_at}). [U] the shape was read from a client, not from a logged-in
    call on this machine."""
    out = []
    for lim in d.get("limits") or []:
        if not isinstance(lim, dict):
            continue
        scope = ((lim.get("scope") or {}).get("model") or {}).get("display_name")
        name = {"session": "5-hour"}.get(lim.get("kind"), lim.get("kind") or "limit")
        if lim.get("group") == "weekly":
            name = "weekly" + (f" ({scope})" if scope else "")
        out.append({"window": name, "used_percent": _pct(lim.get("percent")), "resets_at": lim.get("resets_at"),
                    "severity": lim.get("severity")})
    if out:
        return out
    for key, name in (("five_hour", "5-hour"), ("seven_day", "weekly"), ("seven_day_opus", "weekly (Opus)"),
                      ("seven_day_sonnet", "weekly (Sonnet)")):
        w = d.get(key)
        if isinstance(w, dict):
            out.append({"window": name, "used_percent": _pct(w.get("utilization")), "resets_at": w.get("resets_at")})
    ex = d.get("extra_usage")
    if isinstance(ex, dict) and ex.get("is_enabled"):
        out.append({"window": "extra usage", "used_percent": _pct(ex.get("utilization")),
                    "limit_reached": ex.get("spend_limit_reached")})
    return out


def claude_limits() -> dict:
    tok, src = _claude_token()
    if not tok:
        why = {"expired": "the saved sign-in token has expired; it renews the next time Claude Code runs "
                          "(slop agents test claude)",
               "none": "no readable plan token here (on macOS it is in the Keychain)"}.get(src, src)
        return {"available": False, "why": why}
    status, data, err = util.http_json(USAGE_URL, headers={"Authorization": f"Bearer {tok}",
                                                           "anthropic-beta": "oauth-2025-04-20"}, timeout=20)
    if status == 200 and isinstance(data, dict):
        return {"available": True, "source": "oauth usage endpoint", "windows": parse_claude_usage(data)}
    if status == 401:
        if src == "CLAUDE_CODE_OAUTH_TOKEN":
            return {"available": False, "signin_rejected": True, "why": TOKEN_REJECTED, "next": TOKEN_NEXT}
        return {"available": False, "signin_rejected": True, "next": "slop agents login claude --force",
                "why": "Claude says the sign-in is no longer valid: slop agents login claude --force"}
    return {"available": False, "why": f"usage read failed: {err or status}"}


# A rejected long-lived token: only the user can make a new one (a new sign-in does not help while the variable is set,
# because Claude Code uses CLAUDE_CODE_OAUTH_TOKEN before any stored sign-in).
TOKEN_REJECTED = ("Claude rejected the plan token in CLAUDE_CODE_OAUTH_TOKEN (expired or revoked). Ask the user to run "
                  "`claude setup-token` on their own computer and give the new value with the secure secret card named "
                  "CLAUDE_CODE_OAUTH_TOKEN (it replaces the old one); or to delete that secret and sign in with "
                  "`slop agents login claude` in a new shell")
TOKEN_NEXT = "slop agents login claude --token-from-env CLAUDE_CODE_OAUTH_TOKEN"


def _rpc(argv: list[str], env: dict, calls: list[tuple[str, dict]], timeout: float = RPC_TIMEOUT_S) -> dict:
    """Minimal JSON-RPC-over-stdio client for `codex app-server`: {method: result | {"error": ...}}."""
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    q: queue.Queue = queue.Queue()

    def reader():
        for line in iter(p.stdout.readline, b""):
            q.put(line)
        q.put(None)
    threading.Thread(target=reader, daemon=True).start()

    def send(o):
        p.stdin.write((json.dumps(o) + "\n").encode())
        p.stdin.flush()

    def wait_id(i, deadline):
        while time.monotonic() < deadline:
            try:
                line = q.get(timeout=max(0.05, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == i and ("result" in m or "error" in m):
                return m
        return None
    res: dict = {}
    deadline = time.monotonic() + timeout
    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "slop", "title": "slop", "version": "1"},
                                                          "capabilities": {"experimentalApi": True}}})
        m = wait_id(1, deadline)
        if not m or "error" in m:
            return {"_error": (m or {}).get("error") or "codex app-server did not answer initialize"}
        send({"method": "initialized", "params": {}})
        for n, (method, params) in enumerate(calls, start=2):
            send({"id": n, "method": method, "params": params})
            m = wait_id(n, deadline)
            res[method] = (m or {}).get("result") if m and "result" in m else {"error": (m or {}).get("error") or "timeout"}
    except (OSError, ValueError) as e:
        res["_error"] = str(e)
    finally:
        try:
            p.stdin.close()
        except OSError:
            pass
        p.terminate()
        try:
            p.wait(3)
        except subprocess.TimeoutExpired:
            p.kill()
    return res


def _codex_rpc(calls: list[tuple[str, dict]]) -> dict:
    b = E.find("codex")
    if not b:
        return {"_error": "codex is not installed"}
    argv = b["argv"] + ["app-server", "--listen", "stdio://", "-c", 'forced_login_method="chatgpt"']
    return _rpc(argv, E.base_env("codex"), calls)


def codex_account() -> dict:
    r = _codex_rpc([("account/read", {"refreshToken": False})])
    a = r.get("account/read")
    if not isinstance(a, dict) or "error" in a:
        return {"ok": False, "why": str(r.get("_error") or (a or {}).get("error"))[:200]}
    acct = a.get("account") or {}
    if isinstance(acct, dict) and acct.get("email"):
        acct = {**acct, "email": mask_account(acct["email"])}
    return {"ok": True, "account": acct, "requires_auth": a.get("requiresOpenaiAuth")}


def _windows_from(obj, out: list, plan: list) -> None:
    """Find every {usedPercent, windowDurationMins, resetsAt} window in a rate-limit answer (nested by limit id)."""
    if isinstance(obj, dict):
        if "usedPercent" in obj or "used_percent" in obj:
            mins = obj.get("windowDurationMins") or obj.get("window_minutes")
            name = {300: "5-hour", 10080: "weekly"}.get(mins, f"{mins} min" if mins else "window")
            out.append({"window": name, "used_percent": _pct(obj.get("usedPercent", obj.get("used_percent"))),
                        "resets_at": obj.get("resetsAt", obj.get("resets_at"))})
            return
        for k in ("planType", "plan_type"):
            if obj.get(k):
                plan.append(obj[k])
        for v in obj.values():
            _windows_from(v, out, plan)
    elif isinstance(obj, list):
        for v in obj:
            _windows_from(v, out, plan)


def codex_limits() -> dict:
    r = _codex_rpc([("account/rateLimits/read", {})])
    v = r.get("account/rateLimits/read")
    if not isinstance(v, dict) or "error" in v:
        err = (v or {}).get("error") if isinstance(v, dict) else r.get("_error")
        msg = err.get("message") if isinstance(err, dict) else err
        return {"available": False, "why": str(msg or "no answer")[:200]}
    wins: list = []
    plan: list = []
    _windows_from(v, wins, plan)
    return {"available": True, "source": "codex app-server account/rateLimits/read", "windows": wins,
            "plan": plan[0] if plan else None}


# ------------------------------------------------------------------------------------------------- all engines
def _line(s: dict) -> str:
    head = f"  {s['engine']:<7}"
    if not s["installed"]:
        return f"{head}not installed{' - ' + s['detail'] if s.get('detail') else ''}   next: {s['next']}"
    ver = (s.get("version") or "?")[:34]
    if s.get("login_pending"):
        who = f"sign-in waiting ({s['login_pending'].get('state')})"
    elif s["logged_in"]:
        who = "signed in: " + (s.get("auth_text") or s.get("auth") or "yes") + (f", plan {s['plan']}" if s.get("plan") else "")
    elif s["logged_in"] is None:
        who = "sign-in unknown" + (f" ({s.get('detail')})" if s.get("detail") else "")
    else:
        who = "not signed in"
    line = f"{head}{ver:<36}{who}   next: {s['next']}"
    lim = s.get("limits")
    if lim:
        if lim.get("available"):
            ws = ", ".join(f"{w['window']} {w['used_percent']}%" for w in lim.get("windows") or [] if w.get("used_percent") is not None)
            line += f"\n           usage: {ws or 'no windows reported'}"
        else:
            line += f"\n           usage: not available ({lim.get('why')})"
    for n in s.get("notes") or []:
        line += f"\n           note: {n}"
    return line


def status(engines: list[str], limits: bool = False) -> dict:
    rows = [engine_status(e, limits=limits) for e in engines]
    ready = [r["engine"] for r in rows if r["installed"] and r["logged_in"]]
    lines = [f"coding agents on this computer (linked in {E.bin_dir()}):"] + [_line(r) for r in rows]
    if ready:
        lines.append(f"ready: {', '.join(ready)}" + ("" if limits else "   (plan usage: slop agents status --limits)"))
    note = None
    if E.on_box():
        note = SIGNIN_NOTE
        lines.append("note: " + note)
    lines.append("home computer: run the same `slop agents ...` commands there through local exec (runner/README.md).")
    first = next((r for r in rows if not (r["installed"] and r["logged_in"])), None)
    out = {"ok": True, "agents": rows, "ready": ready, "bin_dir": str(E.bin_dir()),
           "next": (first or rows[0])["next"] if rows else None, "text": "\n".join(lines)}
    if note:
        out["signin_note"] = note
    return out


# Bot's computer: the commands live under /workspace (kept on a computer update); the sign-ins do not move.
SIGNIN_NOTE = ("the agents' sign-ins are kept by each CLI in the home folder (~/.claude, ~/.codex, ~/.gemini, "
               "~/.config/muse), not under /workspace. If a computer reset clears them, this list shows \"not signed "
               "in\": run `slop agents login ENGINE` again (the installs themselves are kept)")
