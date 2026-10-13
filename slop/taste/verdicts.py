"""Owner verdicts on taste rules (``slop taste verdict RULE confirmed|rejected [--value V] [--note "..."]``).

Every rule `slop taste tokens` derives is a hypothesis until the owner judges it on something rendered (docs/30 §1).
A verdict is one JSON line in the project's ``taste/verdicts.jsonl`` (the same file the plate / frame verdicts go to):

    {"vid", "t", "level": "rule", "rule": "palette.restraint", "value": "mono+1", "status": "confirmed",
     "owner": {"verdict": "accept", "note": "yes, this"}, "project": "my-song", "source": "slop taste verdict"}

plus a dated ``TASTE <rule> <value>: CONFIRMED (...)`` line in DECISIONS.md. When the project shares the user profile,
the row is copied to ``$SLOP_HOME/taste/verdicts.jsonl`` so the next project's tokens start from it.

The owner's questions and the command that answers each (`slop taste tokens` prints them; the question ids work as
rule names too: accent, footage_grade, faces, texture, style_frame, type):

    accent         palette.accent         confirmed --value "#RRGGBB"  |  confirmed --value none   (--value REQUIRED)
    footage_grade  palette.footage_grade  confirmed --value native | clean-grade | print
    faces          faces                  confirmed = show the lead's face   rejected = hide faces
    texture        texture                confirmed = add grain               rejected = no grain (clean graphics)
    style_frame    style_frame            confirmed --value FRAME (file or number)   rejected = none is close
    type           type.lyric             confirmed (the A/B leader, or --value FAMILY)   rejected = the next font
    avoid:SOURCE   avoid:SOURCE           confirmed = banned                  rejected = keep it

Yes/no rules have ONE fixed value (texture = "grain", faces = "show"): confirmed means yes, rejected means no, whatever
the statistics lean to (review round 2: a value taken from the measured lean turned "rejected — no grain" into GRAIN).
`--value yes|no` (grain|clean, show|hide) is accepted and stored in that canonical form; a double negative such as
`texture rejected --value clean` is refused with the direct command.

How `slop taste tokens` honours verdicts (`honour`):
  * a verdict binds to the rule AND the value it judged: "restraint mono+1 confirmed" stops applying when new taps
    move the statistic to "limited" (it is then listed under `verdicts.stale` with the question to ask again);
  * this project's own verdicts win over verdicts carried from other projects; the latest one wins inside each;
  * owner-valued rules take the verdict's value: a confirmed accent becomes `palette.accent`, a rejected lyric font is
    skipped for the next one on the A/B shortlist, texture = grain only when confirmed (rejected = no grain);
  * the accent, the footage grade, faces and the style frame are choices for ONE video: another project's verdict on
    them is never applied, it only becomes the question's proposal ("last time (song-a): #D97757 — the same again?");
  * `word:<phrase>` and `avoid:<source>` rows get a status; a confirmed avoid is a banned source;
  * answered questions leave `open_questions` (listed in `answered_questions` with the answer); a confirmed
    `style_frame` verdict, or any `level: "frame"` row, answers the style-frame question.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import SlopError
from .store import (append_jsonl, new_eid, now_iso, project_taste_dir, read_json, read_jsonl, taste_dir)

FILE = "verdicts.jsonl"
STATUSES = ("confirmed", "rejected")
GRADES = ("native", "clean-grade", "print")
GRADE_MEANING = {
    "native": "the generated footage keeps the generator's own colour (the default; restraint lives in the graphics)",
    "clean-grade": "a light global grade toward the hero plate, baked into the plates and clips (needs a hero plate)",
    "print": "EV's print look: the footage keeps its colour and the engine prints a halftone / grain screen over it",
}
OWNER_RULES = {
    "palette.accent": "the accent colour of THIS video, the owner's choice (never measured): --value \"#RRGGBB\" or "
                      "--value none (required)",
    "palette.footage_grade": "how the generated footage is coloured: --value native | clean-grade | print (native = "
                             "the generator's own colour, the default; clean-grade = a light grade toward the hero "
                             "plate; print = own colour + the engine's halftone / grain screen)",
    "type.lyric": "the lyric font family, judged on a rendered style frame (rejected = the next font on the shortlist)",
    "texture": "add fine grain / halftone texture to the graphics? confirmed = YES, add grain; rejected = NO grain",
    "faces": "show the lead's face (sung, lip-synced shots)? confirmed = YES, show faces; rejected = NO, hide faces",
    "style_frame": "the rendered style frame closest to the look: confirmed --value FRAME (its file or number) "
                   "--note \"what is wrong with it\"; rejected = none is close (render new frames)",
}
PROJECT_ONLY = ("palette.accent", "palette.footage_grade", "faces", "style_frame")   # choices for THIS video
YES_NO = {"texture": ("grain", "clean", "add grain", "no grain"), "faces": ("show", "hide", "show faces", "hide faces")}
YES_WORDS = {"texture": ("yes", "y", "grain", "true", "on", "add", "add grain"),
             "faces": ("yes", "y", "show", "true", "on", "show faces")}
NO_WORDS = {"texture": ("no", "n", "clean", "none", "false", "off", "no grain"),
            "faces": ("no", "n", "hide", "false", "off", "hide faces", "none")}
# question ids (taste-tokens.json open_questions) and a few natural words -> rule ids
ALIASES = {"accent": "palette.accent", "colour": "palette.accent", "color": "palette.accent",
           "accent_colour": "palette.accent", "footage_grade": "palette.footage_grade", "grade": "palette.footage_grade",
           "footage": "palette.footage_grade", "mode": "palette.footage_grade", "look.mode": "palette.footage_grade",
           "type": "type.lyric", "font": "type.lyric", "fonts": "type.lyric", "lyric": "type.lyric",
           "lyric_font": "type.lyric", "grain": "texture", "face": "faces", "frame": "style_frame",
           "style-frame": "style_frame", "styleframe": "style_frame", "restraint": "palette.restraint"}
QUESTION_RULE = {"accent": "palette.accent", "footage_grade": "palette.footage_grade", "faces": "faces",
                 "texture": "texture", "style_frame": "style_frame", "type": "type.lyric"}
GRADE_WORDS = {"clean": "clean-grade", "graded": "clean-grade", "grade": "clean-grade", "clean grade": "clean-grade",
               "own": "native", "natural": "native", "original": "native", "halftone": "print"}


def project_file(pdir: Path) -> Path:
    return project_taste_dir(pdir) / FILE


def profile_file(pdir: Path) -> Path:
    return taste_dir(pdir) / FILE


def ground_lean(gr: dict) -> str:
    d, li = int(gr.get("likes_dark") or 0), int(gr.get("likes_light") or 0)
    if d > 1.5 * li and d >= 3:
        return "dark"
    if li > 1.5 * d and li >= 3:
        return "light"
    return "mixed"


def rule_id(name: str) -> str:
    """a rule id from what the bot typed: the rule itself, or a question id / natural word (accent, faces, ...)"""
    n = (name or "").strip()
    return ALIASES.get(n.lower(), n)


def answers_for(rule: str, value=True) -> dict[str, str]:
    """{the owner's answer: the exact command that records it} for one rule (printed with each question);
    `value` = the rule's current value (type.lyric without an A/B leader needs --value FAMILY)"""
    v = f"slop taste verdict {rule}"
    note = '--note "their words"'
    if rule == "palette.accent":
        return {"a colour": f'{v} confirmed --value "#RRGGBB" {note}   (their colour as a hex)',
                "no accent": f"{v} confirmed --value none {note}"}
    if rule == "palette.footage_grade":
        return {g: f"{v} confirmed --value {g} {note}" for g in GRADES}
    if rule == "texture":
        return {"yes, grain": f"{v} confirmed {note}", "no grain": f"{v} rejected {note}"}
    if rule == "faces":
        return {"show faces": f"{v} confirmed {note}", "hide faces": f"{v} rejected {note}"}
    if rule == "style_frame":
        return {"frame N is closest": f'{v} confirmed --value N --note "what is wrong with it"',
                "none is close": f"{v} rejected {note}"}
    if rule == "type.lyric":
        if value is None:
            return {"a font family": f'{v} confirmed --value "FAMILY" {note}   (an OFL face from engine/fonts)',
                    "not sure yet": "slop taste fonts   (the font A/B on real lyric lines first)"}
        return {"yes, it reads well": f"{v} confirmed {note}", "no": f"{v} rejected {note}   (the next font)"}
    if rule.startswith("avoid:"):
        return {"yes, ban it": f"{v} confirmed {note}", "no, keep it": f"{v} rejected {note}"}
    return {"yes": f"{v} confirmed {note}", "no": f"{v} rejected {note}"}


def rules(t: dict) -> list[dict]:
    """the verdict-able rules of a (statistical) token set: [{id, value, status, about, owner?}]"""
    pal, gr, tex, ty = t.get("palette") or {}, t.get("ground") or {}, t.get("texture") or {}, t.get("type") or {}
    cands = ", ".join(f"{h['hue']} {h['observed_hex']}" if h.get("observed_hex") else h["hue"]
                      for h in pal.get("hues") or [] if h.get("hue") in (pal.get("accent_candidates") or []))
    out = [
        {"id": "palette.restraint", "value": pal.get("restraint"), "status": pal.get("stat_status") or pal.get("status"),
         "about": "how much colour the GRAPHICS use (mono+1 / limited / colourful) — never the footage"},
        {"id": "palette.accent", "value": pal.get("accent"), "status": "ask-owner", "owner": True,
         "about": OWNER_RULES["palette.accent"] + (f"; candidates from the taps: {cands}" if cands else "")},
        {"id": "palette.footage_grade", "value": pal.get("footage_grade", "native"), "status": "ask-owner",
         "owner": True, "about": OWNER_RULES["palette.footage_grade"]},
        {"id": "ground", "value": ground_lean(gr), "status": gr.get("stat_status") or gr.get("status", "lead"),
         "about": "the grounds of the liked images: dark / light / mixed"},
        {"id": "texture", "value": "grain", "status": "ask-owner", "owner": True,
         "lean": tex.get("lean", "unclear"),
         "about": OWNER_RULES["texture"] + f" (your taps lean: {tex.get('lean', 'unclear')})"},
        {"id": "faces", "value": "show", "status": "ask-owner", "owner": True, "about": OWNER_RULES["faces"]},
        {"id": "style_frame", "value": None, "status": "ask-owner", "owner": True, "about": OWNER_RULES["style_frame"]},
        {"id": "composition", "value": "as measured", "status": (t.get("composition") or {}).get("stat_status")
         or (t.get("composition") or {}).get("status", "hypothesis"),
         "about": "the placement tendencies in taste-tokens.json composition"},
        {"id": "type.lyric", "value": ty.get("lyric_measured", ty.get("lyric")), "status": ty.get("stat_status")
         or ty.get("status", "not measured"), "owner": True, "about": OWNER_RULES["type.lyric"]},
    ]
    words = t.get("words") or {}
    for side in ("liked", "passed"):
        for r in words.get(side) or []:
            out.append({"id": f"word:{r['phrase']}", "value": side, "status": "descriptive",
                        "about": f"images that look like '{r['phrase']}' are {side} more (AUC {r['auc']})"})
    for a in t.get("anti_sources") or []:
        out.append({"id": f"avoid:{a['source']}", "value": "banned", "status": "measured",
                    "about": f"{a['taps']} taps, like-rate {a['like_rate']}: keep this source out of the look"})
    return out


def load_rows(pdir: Path) -> list[dict]:
    """rule verdicts from this project's file and (when shared) the user profile's copy, oldest first"""
    pf, uf = project_file(pdir), profile_file(pdir)
    rows = list(read_jsonl(pf))
    if uf.resolve() != pf.resolve():
        seen = {r.get("vid") for r in rows if r.get("vid")}
        rows += [r for r in read_jsonl(uf) if r.get("vid") and r["vid"] not in seen]
    return sorted((r for r in rows if isinstance(r, dict)), key=lambda r: str(r.get("t") or ""))


def frame_verdicts(rows: list[dict], pname: str) -> list[dict]:
    return [r for r in rows if r.get("level") == "frame" and r.get("project", pname) == pname]


def latest(rows: list[dict], pname: str) -> dict[str, dict]:
    """{rule: verdict}: this project's latest verdict per rule, else the latest carried from another project"""
    own: dict[str, dict] = {}
    carried: dict[str, dict] = {}
    for r in rows:
        if r.get("level") != "rule" or r.get("status") not in STATUSES or not r.get("rule"):
            continue
        if r.get("project", pname) != pname and r["rule"] in PROJECT_ONLY:
            continue                      # the accent / footage grade / faces of another video (`previous_choices`)
        (own if r.get("project", pname) == pname else carried)[r["rule"]] = r
    return {**carried, **own}


def previous_choices(rows: list[dict], pname: str) -> dict[str, dict]:
    """{rule: verdict} the owner gave in OTHER projects for the per-video rules (shown as a proposal only)"""
    out: dict[str, dict] = {}
    for r in rows:
        if (r.get("level") == "rule" and r.get("rule") in PROJECT_ONLY and r.get("rule") != "style_frame"
                and r.get("project", pname) != pname
                and (r.get("status") == "confirmed" or r.get("rule") == "faces")):
            out[r["rule"]] = r
    return out


def meaning(rule: str, value, status: str) -> str | None:
    """what a yes/no verdict means in plain words (texture: 'add grain' / 'no grain'; faces: show / hide)"""
    if rule in YES_NO:
        yes_val, _, yes_txt, no_txt = YES_NO[rule]
        return yes_txt if (status == "confirmed" and value == yes_val) else no_txt
    return None


def _short(v: dict, pname: str) -> dict:
    out = {"rule": v["rule"], "value": v.get("value"), "status": v["status"], "t": v.get("t"),
           "note": (v.get("owner") or {}).get("note"), "project": v.get("project"),
           "carried": v.get("project", pname) != pname}
    m = meaning(v["rule"], v.get("value"), v["status"])
    if m:
        out["meaning"] = m
    return out


def honour(t: dict, rows: list[dict], pname: str) -> dict:
    """apply the owner's verdicts to a freshly built (statistical) token set, in place; returns t"""
    pal, gr, tex, ty = t["palette"], t["ground"], t["texture"], t["type"]
    comp = t.get("composition") or {}
    pal["stat_status"] = pal.get("status")
    gr["stat_status"] = gr.get("status")
    comp["stat_status"] = comp.get("status")
    ty["stat_status"] = ty.get("status")
    ty["lyric_measured"] = ty.get("lyric")
    base = {r["id"]: r for r in rules(t)}
    v_by = latest(rows, pname)
    applied, stale = [], []
    answered: dict[str, str] = {}
    for rid, v in v_by.items():
        st, val = v["status"], v.get("value")
        r = base.get(rid)
        if r is None:
            stale.append({**_short(v, pname), "why": f"'{rid}' is not among the current tokens (new taps changed "
                                                      "them); ask the owner again if it still matters"})
            continue
        if not r.get("owner") and val != r["value"]:
            stale.append({**_short(v, pname), "now": r["value"],
                          "why": f"the owner {st} {rid} = {val} on {str(v.get('t'))[:10]}; the taps now say "
                                 f"{r['value']} — ask again"})
            continue
        if rid == "palette.restraint":
            pal["status"] = st
        elif rid == "ground":
            gr["status"] = st
        elif rid == "composition":
            comp["status"] = st
        elif rid == "texture":
            grain = st == "confirmed" and val == "grain"      # rejected = no grain, whatever value the row carries
            tex.update(apply=grain, status=st, owner_value="grain" if grain else "clean")
            answered["texture"] = "yes, grain" if grain else "no grain"
        elif rid == "faces":
            show = st == "confirmed" and val != "hide"
            t["faces"] = {"show": show, "status": st, "note": (v.get("owner") or {}).get("note")}
            answered["faces"] = "show faces" if show else "hide faces"
        elif rid == "style_frame":
            note = (v.get("owner") or {}).get("note")
            if st == "confirmed" and val:
                t["style_frame"] = {"pick": val, "note": note, "status": "confirmed"}
                answered["style_frame"] = f"{val}" + (f" ({note})" if note else "")
            else:
                t["style_frame"] = {"pick": None, "note": note, "status": "rejected"}
        elif rid == "palette.accent":
            if st == "confirmed":
                pal.update(accent=val, accent_source="owner verdict")
                answered["accent"] = val or "none"
            else:
                pal.setdefault("accent_rejected", []).append(val)
        elif rid == "palette.footage_grade":
            if st == "confirmed" and val in GRADES:
                pal.update(footage_grade=val, footage_grade_status="confirmed")
                answered["footage_grade"] = val
            else:
                pal["footage_grade_status"] = "rejected"
                pal.setdefault("footage_grade_rejected", []).append(val)
        elif rid == "type.lyric":
            if st == "confirmed" and val:
                ty.update(lyric=val, status="confirmed")
                answered["type"] = val
            else:
                ty.setdefault("rejected", []).append(val)
        elif rid.startswith("word:"):
            for side in ("liked", "passed"):
                for w in (t.get("words") or {}).get(side) or []:
                    if w["phrase"] == rid[5:]:
                        w["status"] = st
        elif rid.startswith("avoid:"):
            for a in t.get("anti_sources") or []:
                if a["source"] == rid[6:]:
                    a["status"] = st
                    a["banned"] = st == "confirmed"
            answered[rid] = "banned" if st == "confirmed" else "keep"
        applied.append(_short(v, pname))
    rej = set(ty.get("rejected") or [])
    if ty.get("lyric") in rej:
        ty["lyric"] = next((f for f in ty.get("shortlist") or [] if f not in rej), None)
    if frame_verdicts(rows, pname) and "style_frame" not in answered:
        answered["style_frame"] = "see taste/verdicts.jsonl (level frame)"
    prev = previous_choices(rows, pname)
    qs = t.get("open_questions") or []
    for q in qs:
        rid = QUESTION_RULE.get(q["id"], q["id"])
        q.setdefault("rule", rid)
        q.setdefault("answers", answers_for(rid))
        r = prev.get(rid)                 # retention: "last time you chose ..." as the proposal, never applied
        if r and q["id"] not in answered:
            shown = meaning(rid, r.get("value"), r["status"]) or r.get("value") or "none"
            q["proposal"] = f"last time ({r.get('project')}): {shown} — the same again? (was: {q['proposal']})"
            q["previous"] = {"value": r.get("value"), "status": r.get("status"), "project": r.get("project"),
                             "t": r.get("t")}
        if q["id"] == "style_frame" and (t.get("style_frame") or {}).get("status") == "rejected":
            sf = t["style_frame"]
            q["proposal"] = ("none of the last frames was close" + (f" ('{sf['note']}')" if sf.get("note") else "")
                             + ": render 3 new frames that fix that, then ask again")
    t["answered_questions"] = [{**q, "answer": answered[q["id"]]} for q in qs if q["id"] in answered]
    t["open_questions"] = [q for q in qs if q["id"] not in answered]
    t["verdicts"] = {"applied": applied, "stale": stale,
                     "previous": {k: _short(v, pname) for k, v in prev.items()},
                     "note": "owner verdicts (slop taste verdict); DECISIONS.md has the same lines with dates"}
    t["rules"] = [{**r, "status": _status_of(t, r)} for r in rules(t)]
    return t


def _status_of(t: dict, r: dict) -> str:
    rid = r["id"]
    for v in (t.get("verdicts") or {}).get("applied") or []:
        if v["rule"] == rid:
            return v["status"]
    return r.get("status") or "hypothesis"


# ---------------------------------------------------------------- slop taste verdict

def tokens_or_none(pdir: Path) -> dict | None:
    return read_json(project_taste_dir(pdir) / "taste-tokens.json")


def list_rules(pdir: Path) -> dict:
    t = tokens_or_none(pdir)
    rs = (t.get("rules") or rules(t)) if t else [{"id": k, "value": None, "status": "ask-owner", "owner": True,
                                                   "about": v} for k, v in OWNER_RULES.items()]
    lines = []
    for r in rs:
        val = r.get("value")
        if r["id"] in YES_NO:
            val = "yes/no"
        lines.append(f"  {r['id']:<24} {str('-' if val is None else val)[:24]:<24} {r.get('status') or ''}")
        lines.append(f"      {r.get('about', '')}")
        if r.get("owner") or r["id"].startswith("avoid:"):
            for ans, cmd in answers_for(r["id"], r.get("value")).items():
                lines.append(f"      {ans}: {cmd}")
    head = ("rules in taste-tokens.json (id, value, status), each with what it means:" if t else
            "no taste-tokens.json yet (slop taste tokens): only the owner's own rules can take a verdict:")
    return {"rules": rs, "tokens": bool(t),
            "text": head + "\n" + "\n".join(lines)
                    + "\nrecord one: slop taste verdict RULE confirmed|rejected --note \"the owner's words\" "
                      "(question ids work too: accent, footage_grade, faces, texture, style_frame, type)"}


def _accent_help(t: dict | None, rows: list[dict], pname: str) -> str:
    pal = (t or {}).get("palette") or {}
    cands = [f"{h['hue']} {h['observed_hex']}" if h.get("observed_hex") else h["hue"]
             for h in pal.get("hues") or [] if h.get("hue") in (pal.get("accent_candidates") or [])]
    prev = previous_choices(rows, pname).get("palette.accent")
    bits = []
    if cands:
        bits.append(f"candidates from the taps: {', '.join(cands)}")
    if prev:
        bits.append(f"last time ({prev.get('project')}): {prev.get('value') or 'none'}")
    return (" (" + "; ".join(bits) + ")") if bits else ""


def _yes_no(rule: str, status: str, value: str | None) -> tuple[str, str]:
    """-> (canonical value, status) for the yes/no rules texture / faces"""
    yes_val = YES_NO[rule][0]
    if value is None:
        return yes_val, status
    v = value.strip().lower()
    if v in YES_WORDS[rule]:
        want = True
    elif v in NO_WORDS[rule]:
        want = False
    else:
        raise SlopError(f"--value {value!r}: {rule} is a yes/no question — {YES_NO[rule][2]} or {YES_NO[rule][3]}: "
                        f"slop taste verdict {rule} confirmed (= {YES_NO[rule][2]}) or slop taste verdict {rule} "
                        f"rejected (= {YES_NO[rule][3]})")
    if status == "rejected" and not want:
        raise SlopError(f"`{rule} rejected --value {value}` is a double negative. Record the owner's answer directly: "
                        f"slop taste verdict {rule} confirmed (= {YES_NO[rule][2]}) or slop taste verdict {rule} "
                        f"rejected (= {YES_NO[rule][3]}); nothing was recorded")
    if status == "rejected":          # "rejected --value grain" = no grain
        want = False
    return yes_val, ("confirmed" if want else "rejected")


def record(pdir: Path, rule: str, status: str, note: str | None = None, value: str | None = None,
           by: str = "owner") -> dict:
    from .profile import project_name
    pdir = Path(pdir)
    status = (status or "").strip().lower()
    status = {"confirm": "confirmed", "yes": "confirmed", "accept": "confirmed", "reject": "rejected",
              "no": "rejected"}.get(status, status)
    rule = rule_id(rule)
    if status not in STATUSES:
        raise SlopError(f"the verdict must be confirmed or rejected (got {status!r}): "
                        f"slop taste verdict {rule} confirmed --note \"...\"")
    t = tokens_or_none(pdir)
    known = {r["id"]: r for r in ((t.get("rules") or rules(t)) if t else [])}
    if rule not in known and rule not in OWNER_RULES:
        some = ", ".join(list(known)[:14]) or ", ".join(OWNER_RULES)
        hint = "" if t else " (no taste-tokens.json yet: run `slop taste tokens` for the measured rules)"
        raise SlopError(f"unknown rule {rule!r}{hint}. Rules: {some} (question ids work too: accent, footage_grade, "
                        "faces, texture, style_frame, type). All of them with their commands: slop taste verdict --list")
    r = known.get(rule) or {"id": rule, "value": None, "owner": True}
    pname = project_name(pdir)
    if rule == "palette.accent":
        if value is None or not value.strip():
            raise SlopError("palette.accent needs the owner's colour: slop taste verdict palette.accent confirmed "
                            "--value \"#RRGGBB\" (their colour as a hex) or --value none (no accent)"
                            + _accent_help(t, load_rows(pdir), pname) + "; nothing was recorded")
        v = value.strip()
        if v.lower() in ("none", "no", "-", "no accent"):
            value = None
        elif not re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
            raise SlopError(f"--value {value!r}: an accent is a hex colour like #D97757 (or none)"
                            + _accent_help(t, load_rows(pdir), pname) + "; nothing was recorded")
        else:
            value = "#" + v.lstrip("#").upper()
        val = value
    elif rule == "palette.footage_grade":
        if value is not None:
            v = value.strip().lower()
            v = GRADE_WORDS.get(v, v)
            if v not in GRADES:
                raise SlopError(f"--value {value!r}: the footage grade is one of: "
                                + "; ".join(f"{g} = {GRADE_MEANING[g]}" for g in GRADES) + ". Nothing was recorded")
            value = v
        val = value if value is not None else (r.get("value") or "native")
    elif rule in YES_NO:
        val, status = _yes_no(rule, status, value)
    elif rule == "style_frame":
        val = value.strip() if value and value.strip() else None
        if status == "confirmed" and not val:
            raise SlopError("style_frame needs the frame the owner picked: slop taste verdict style_frame confirmed "
                            "--value N (the frame's number or file) --note \"what is wrong with it\"; if none is close: "
                            "slop taste verdict style_frame rejected --note \"their words\"")
    else:
        val = value if value is not None else r.get("value")
        if r.get("owner") and val is None and status == "confirmed":
            raise SlopError(f"{rule} has no value yet: give the owner's answer, e.g. slop taste verdict {rule} "
                            f"confirmed --value \"...\" --note \"their words\"")
    row = {"vid": new_eid(), "t": now_iso(), "level": "rule", "rule": rule, "value": val, "status": status,
           "owner": {"verdict": "accept" if status == "confirmed" else "reject", "note": (note or "").strip() or None},
           "project": pname, "source": "slop taste verdict"}
    pf, uf = project_file(pdir), profile_file(pdir)
    append_jsonl(pf, row)
    if uf.resolve() != pf.resolve():
        append_jsonl(uf, row)
    m = meaning(rule, val, status)
    shown = f"{val if val is not None else 'none'}: {status.upper()}" + (f" = {m}" if m else "")
    dec = None
    try:
        from ..core_cli import append_decision
        txt = f"TASTE {rule} {shown}" + (f" ('{row['owner']['note']}')" if row["owner"]["note"] else "")
        dec = append_decision(pdir, txt, by=by)
    except SlopError as e:            # no DECISIONS.md possible (bare project.json): the verdict still counts
        dec = {"recorded": False, "error": str(e)}
    nxt = "slop taste tokens   (re-reads the verdicts)"
    if rule == "palette.footage_grade" and status == "rejected":
        nxt = ("ask the owner which grade instead (" + "; ".join(f"{g} = {GRADE_MEANING[g]}" for g in GRADES)
               + ") and record it: slop taste verdict palette.footage_grade confirmed --value GRADE")
    elif rule == "style_frame" and status == "rejected":
        nxt = "render 3 new style frames that fix what the owner said, then ask again"
    return {"verdict": row, "file": str(pf), "shared": uf.resolve() != pf.resolve(), "decision": dec,
            **({"meaning": m} if m else {}),
            "text": f"recorded: {rule} = {shown}"
                    + (f" (\"{row['owner']['note']}\")" if row["owner"]["note"] else "")
                    + f" in {pf.relative_to(pdir) if pf.is_relative_to(pdir) else pf}"
                    + (" and DECISIONS.md" if (dec or {}).get("recorded") or (dec or {}).get("duplicate") else "")
                    + (" (also in your user profile, so your next project starts with it)"
                       if uf.resolve() != pf.resolve() and rule not in PROJECT_ONLY else "")
                    + f".\nnext: {nxt}"}
