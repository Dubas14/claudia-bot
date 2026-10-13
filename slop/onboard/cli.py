"""`slop onboard` - the onboarding checklist (status / next / mark / set / apply). See slop/onboard/__init__.py.

  slop onboard [status] [--tier T] [--offline] [--group G]   the whole checklist (`slop onboard` alone = status)
  slop onboard next [--tier T] [--offline] [--except ID]    the ONE next item, with what to ask, run and record
  slop onboard mark ITEM --done|--connected|--skip|--todo [--note TEXT]
  slop onboard set tier|suno-plan|mj-plan|mj-profile|coding-agents VALUE    (or --clear)
  slop onboard apply --project NAME [--force]   the recorded Midjourney plan and profile code -> project.json
"""
from __future__ import annotations

import argparse

from .. import util
from ..config import SlopError, load_project, resolve_project, save_project
from . import items as I
from . import state as st

HELP = ("onboarding checklist: what is set up and the next step (toolkit, keys, connectors, Suno, Midjourney, coding "
        "agents, home GPU)")
DESC = ("One checklist for setting up everything: the tier, the toolkit install, keys (secure secret card), "
        "connectors, Suno and Midjourney, coding agents (Claude Code, Codex on a ChatGPT plan, Muse Code, Gemini CLI) "
        "on the box and on your own computer, a home GPU, the taste profile and the first project. Checked items are "
        "measured on every call (free; the only network call is OpenRouter's free key check); recorded items come "
        "from `slop onboard mark` / `slop onboard set`. Start with: slop onboard next")


def cmd_status(a) -> dict:
    rep = I.report(tier=getattr(a, "tier", None), offline=getattr(a, "offline", False))
    group = getattr(a, "group", None)
    out = dict(rep)
    if group:
        out["items"] = [i for i in rep["items"] if i["group"] == group]
    if rep["next_item"]:
        out["next"] = "slop onboard next"
    elif rep["ready"]:                      # all set: the newest project's status (the tier skill takes over)
        fp = next(i for i in rep["items"] if i["id"] == "first-project")
        out["next"] = fp.get("next_cmd")
    else:                                   # stuck: `stuck` and the text say why; nothing runs blindly
        out["next"] = None
    out["text"] = I.render_status(rep, group=group)
    return out


def cmd_next(a) -> dict:
    exclude = [I.resolve_item(x) for x in (getattr(a, "except_ids", None) or [])]
    rep = I.report(tier=getattr(a, "tier", None), offline=getattr(a, "offline", False))
    tier = rep["tier"]
    it = I.pick_next(rep["items"], exclude=exclude, order=rep["priority"])
    ready = rep["tiers"][tier]["ready"]
    all_set = it is None and ready
    stuck = [] if (it or ready) else I.stuck(rep["items"], rep["tiers"], tier, exclude)
    if it:
        # only a command that DOES the step; a question (ask/answers) or a check only the bot can make (record_cmd)
        # leaves `next` empty, so running `next` blindly can never record something nobody checked
        nxt = it.get("next_cmd")
    elif all_set:
        nxt = next(i for i in rep["items"] if i["id"] == "first-project").get("next_cmd")
    else:                                   # stuck: `stuck` says why; nothing to run until the user decides
        nxt = None
    left = rep["counts"]["todo"] + sum(1 for i in rep["items"] if i["state"] == "error" and i["need"] != "optional")
    out = {"ok": True, "tier": tier, "tier_source": rep["tier_source"], "item": it, "all_set": all_set,
           "ready": ready, "left": left, "tiers": rep["tiers"], "unlocked": rep["unlocked"],
           "new_unlocks": rep["new_unlocks"], "running": rep["running"], "stuck": stuck,
           "routes": rep["routes"], "install": rep["install"],
           "hand_off": I.HAND_OFF[tier] if all_set else None, "next": nxt,
           "ask": it.get("ask") if it else None, "answers": it.get("answers") if it else None,
           "record_cmd": it.get("record_cmd") if it else None,
           "record_when": I.RECORD_WHEN if it and it.get("record_cmd") else None,
           "text": ("NEW: " + "; ".join(rep["new_unlocks"]) + "\n" if rep["new_unlocks"] else "")
           + I.render_next(it, rep, exclude)}
    return out


def _skip_warning(iid: str) -> str | None:
    """After a skip: say so when the item is REQUIRED for the current tier (that tier then cannot become ready)."""
    try:
        rep = I.report(offline=True, record=False)
    except Exception:  # a warning must never break the mark itself
        return None
    it = next((i for i in rep["items"] if i["id"] == iid), None)
    tier = rep["tier"]
    missing = rep["tiers"][tier]["missing"]
    if iid in I.ROUTES:                     # Studio / Director need OpenRouter OR Higgsfield (item video)
        other = next(i for i in rep["items"] if i["id"] == I.other_route(iid))
        if "video" not in missing or not other.get("skipped"):
            return None                     # the other route works, or can still come
        return (f"the {tier} tier needs OpenRouter or Higgsfield for its clips, and both are skipped now: it cannot "
                f"become ready. Undo one, with the user's OK: slop onboard mark {other['id']} --todo (or: slop onboard "
                f"mark {iid} --todo); or choose another tier with the user (Quick needs neither): slop onboard set "
                f"tier quick")
    if not it or not (it["need"] == "required" or iid in missing):
        return None
    return (f"{iid} is required for the {tier} tier: while it is skipped, that tier cannot become ready. Undo: slop "
            f"onboard mark {iid} --todo; or choose another tier with the user: slop onboard set tier "
            "quick|studio|director")


def cmd_mark(a) -> dict:
    iid = I.resolve_item(a.item)
    spec = I.SPEC[iid]
    want = "done" if (a.done or a.connected) else "skip" if a.skip else "todo"
    if want == "done" and iid in I.DERIVED:
        raise SlopError(f"{iid} follows {' or '.join(I.DERIVED[iid])}: it is done as soon as "
                        f"{'one of them is' if len(I.DERIVED[iid]) > 1 else 'that is'} (slop onboard next shows the "
                        f"step), so it cannot be marked done by hand; leave it out: slop onboard mark {iid} --skip")
    if want == "done" and spec["kind"] == "check":
        raise SlopError(f"{iid} is checked automatically on every `slop onboard status`, so it cannot be marked done "
                        f"by hand. Do its step (slop onboard next shows it), or leave it out: slop onboard mark {iid} "
                        "--skip")
    if want == "done" and spec["kind"] == "plan":
        how = {"tier": "slop onboard set tier quick|studio|director",
               "suno": "slop onboard set suno-plan free|pro|premier|none",
               "midjourney": "slop onboard set mj-plan basic|standard|pro|mega|none",
               "mj-profile": "slop onboard set mj-profile CODE (CODE = the user's own code)",
               "coding-agents": "slop onboard set coding-agents claude|codex|muse|gemini|none (several: "
                                "comma-separated, the main one first)"}[iid]
        raise SlopError(f"{iid} is recorded with a value: {how}")
    st.set_mark(iid, want, a.note)
    verb = {"done": "connected" if a.connected else "done", "skip": "skipped (it no longer comes up as next)",
            "todo": "back on the list"}[want]
    warn = _skip_warning(iid) if want == "skip" else None
    out = {"ok": True, "item": iid, "mark": want, "state_file": str(st.path()), "next": "slop onboard next",
           "text": f"{iid}: {verb}." + (f"\n! {warn}" if warn else "") + "\nNext: slop onboard next"}
    if warn:
        out["warn"] = warn
    return out


def _shown(name: str, v):
    if name == "mj-profile":
        return st.mask(v)
    if name == "coding-agents" and isinstance(v, list):
        return ",".join(v) or "none"
    return v


def cmd_set(a) -> dict:
    name = a.name
    key, _ = st.SETTINGS[name]
    if a.clear:
        st.set_setting(name, None)
        return {"ok": True, "setting": name, "value": None, "next": "slop onboard next",
                "text": f"{name} cleared. Next: slop onboard next"}
    if a.value is None:
        d = st.load()
        v = d.get("tier") if key == "tier" else (d.get("settings") or {}).get(key)
        shown = _shown(name, v)
        return {"ok": True, "setting": name, "value": shown,
                "text": f"{name}: {shown if shown else 'not set'} (set it: slop onboard set {name} VALUE)"}
    st.set_setting(name, a.value)
    d = st.load()
    v = d.get("tier") if key == "tier" else d["settings"].get(key)
    shown = _shown(name, v)
    extra = ""
    if name == "suno-plan" and v == "free":
        extra = " Note: Suno Free songs are for non-commercial use only."
    if name in ("mj-profile", "mj-plan") and v and v != "none":
        extra = (" Kept in your user settings only (never shipped); a project uses it after: "
                 "slop --project NAME onboard apply.")
    if name == "coding-agents" and v:
        extra = (" The checklist now sets up " + ", ".join(I.ENGINE_NAMES[e] for e in v) + " on the box "
                 "(slop onboard next shows the install and sign-in).")
    return {"ok": True, "setting": name, "value": shown, "next": "slop onboard next",
            "text": f"{name} set to {shown}.{extra} Next: slop onboard next"}


def cmd_apply(a) -> dict:
    pdir = resolve_project(getattr(a, "project", None))
    sets = st.load().get("settings") or {}
    code = sets.get("mj_profile")
    plan = sets.get("mj_plan") if sets.get("mj_plan") in I.PAID_MJ else None
    if not code and not plan:
        raise SlopError("nothing to apply: no Midjourney plan or profile code is recorded (slop onboard set mj-plan "
                        "basic|standard|pro|mega; slop onboard set mj-profile CODE), or the project goes without")
    proj = load_project(pdir)
    mj = proj.get("mj") if isinstance(proj.get("mj"), dict) else {}
    cur = str(mj.get("profile") or "").strip()
    if code and cur and cur != code and st.PROFILE_RE.fullmatch(cur) and not a.force:
        raise SlopError(f"{pdir.name} already has a different profile code ({st.mask(cur)}); replace it with yours: "
                        f"slop --project {pdir.name} onboard apply --force")
    changes = []
    if code and cur != code:
        mj["profile"] = code
        changes.append(f"mj.profile from your user settings ({st.mask(code)}): the plate book adds --profile")
    if plan and str(mj.get("plan") or "standard").lower() != plan:
        mj["plan"] = plan
        changes.append(f"mj.plan = {plan}: prompt batches sized for the {plan.title()} plan")
    if not changes:
        return {"ok": True, "project": pdir.name, "changed": False, "next": f"slop --project {pdir.name} status",
                "text": f"{pdir.name} already uses your recorded Midjourney settings"
                        + (f" (profile {st.mask(code)})" if code else "") + (f" (plan {plan})" if plan else "")}
    proj["mj"] = mj
    save_project(pdir, proj)
    return {"ok": True, "project": pdir.name, "changed": True, "set": changes, "next": f"slop --project {pdir.name} status",
            "text": f"{pdir.name}: project.json " + "; ".join(changes)}


def _tier_flags(p, top: bool = False) -> None:
    """--tier / --offline. On the subcommands default=SUPPRESS keeps a value given before the action
    (`slop onboard --tier studio status`)."""
    dflt = None if top else argparse.SUPPRESS
    p.add_argument("--tier", choices=I.TIERS, default=dflt,
                   help="judge the checklist for this tier (default: the chosen one: slop onboard set tier ...)")
    p.add_argument("--offline", action="store_true", default=False if top else argparse.SUPPRESS,
                   help="no network (the OpenRouter key is not validated)")


def _group_flag(p, top: bool = False) -> None:
    p.add_argument("--group", choices=[g for g, _ in I.GROUPS], default=None if top else argparse.SUPPRESS,
                   help="show only one group")


def register(subparsers) -> None:
    op = subparsers.add_parser("onboard", help=HELP, description=DESC)
    _tier_flags(op, top=True)
    _group_flag(op, top=True)
    util.add_common_flags(op)
    op.set_defaults(func=cmd_status)
    sub = op.add_subparsers(dest="onboard_cmd", metavar="ACTION")

    s = sub.add_parser("status", help="every item with its state, why and next step",
                       description="The whole checklist for a tier. States: done, todo, optional, blocked, error. "
                                   "Example: slop onboard status --tier studio --json")
    _tier_flags(s)
    _group_flag(s)
    util.add_common_flags(s)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("next", help="the single best next item for the tier",
                       description="The ONE next item: why, what to ask the user (with the exact command for each "
                                   "answer), the skill to read, the command to run (`next`) and, for a step only the "
                                   "bot can check, the command that records it (`record_cmd`: run it ONLY after you "
                                   "saw it working). all_set is true only when the tier is ready. Example: slop "
                                   "onboard next --json")
    _tier_flags(s)
    s.add_argument("--except", dest="except_ids", action="append", default=[], metavar="ITEM",
                   help="pass over this item for now (repeatable), e.g. while it is installing")
    util.add_common_flags(s)
    s.set_defaults(func=cmd_next)

    s = sub.add_parser("mark", help="record an item: --done/--connected, --skip or --todo",
                       description="Record what the bot saw or the user said. Checked items (toolkit, keys, agents "
                                   "on the box, GPU ...) can only be skipped; connectors, browser sign-ins and agents "
                                   "on the user's own computer are marked done ONLY after the bot saw them working. "
                                   "Notes never hold a key, token, password or account address (refused). Example: "
                                   "slop onboard mark higgsfield --connected")
    s.add_argument("item", help="item id (slop onboard status lists them), e.g. higgsfield, home-claude, gpu")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--done", action="store_true", help="it is set up (you saw it working)")
    g.add_argument("--connected", action="store_true", help="the same as --done (for connectors)")
    g.add_argument("--skip", action="store_true", help="the user does not want it (it stops coming up as next)")
    g.add_argument("--todo", action="store_true", help="undo a mark")
    s.add_argument("--note", help="short context, e.g. the plan (cut at 200 characters); never a key, token, "
                                  "password or account address")
    util.add_common_flags(s)
    s.set_defaults(func=cmd_mark)

    s = sub.add_parser("set", help="user settings: tier, suno-plan, mj-plan, mj-profile, coding-agents",
                       description="User settings in $SLOP_HOME/onboard.json (no secrets). tier = quick|studio|"
                                   "director; suno-plan = free|pro|premier|none; mj-plan = basic|standard|pro|mega|"
                                   "none; mj-profile = the user's own Midjourney profile code (never shipped); "
                                   "coding-agents = the user's coding-agent plans: claude, codex (ChatGPT plan), "
                                   "muse, gemini, comma-separated with the main one first, or none. No VALUE: show "
                                   "it. Example: slop onboard set coding-agents claude,codex")
    s.add_argument("name", choices=list(st.SETTINGS), help="which setting")
    s.add_argument("value", nargs="?", help="the value (none = show the current value)")
    s.add_argument("--clear", action="store_true", help="remove the setting")
    util.add_common_flags(s)
    s.set_defaults(func=cmd_set)

    s = sub.add_parser("apply", help="put the recorded Midjourney plan and profile code into a project",
                       description="Copies the Midjourney plan (prompts per paste) and profile code from your user "
                                   "settings into the project's project.json (mj.plan, mj.profile), so the plate book "
                                   "sizes its batches and adds --profile. Example: slop --project my-song onboard "
                                   "apply")
    s.add_argument("--force", action="store_true", help="replace a different profile code already in the project")
    util.add_common_flags(s)
    s.set_defaults(func=cmd_apply)
