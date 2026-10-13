"""Write the owner-confirmed look into project.json (``slop taste apply`` → preview; ``--yes`` → write).

The bot runs `slop taste apply [--accent HEX] [--mode M] [--lyric-font F] [--texture yes|no] ...`, shows the owner the
preview (one message), and only after the owner says yes runs the same command with `--yes`. What is written:

    look.mode         the footage grade: --mode, else a confirmed `palette.footage_grade` verdict, else the current
                      value, else native (reference statistics never choose it)
    look.accent       --accent HEX|none, else a confirmed `palette.accent` verdict; otherwise left as it is and the
                      preview says to ask (the tokens never pick the accent)
    look.fonts        --lyric-font / --micro-font / --display-font, else a confirmed `type.lyric` verdict or the
                      position-corrected font A/B leader (shown in the preview, so the owner's yes confirms it); every
                      family must be an OFL face shipped in engine/fonts
    look.style_tail   the PROJECT part of the plates' style tail (docs/50 slot 7 minus the light): palette + one
    look.style_tail_api  warm note + texture + finish, and its API version (docs/51 §4: the photography said out
                      loud); --tail replaces the generated MJ tail. `slop board plates` appends look.style_tail to
                      every plate prompt it books.

The tail NEVER says "monochrome": colour restraint describes the GRAPHICS the owner likes, not the footage (the
EV lesson: "mono + one red" was right for the references and "way too.. gray" for the video), and generation inputs
stay in colour (ARCHITECTURE §7 rule 5). Review round 2:
  * no light / time of day: the tail is appended to EVERY plate, and the light is a chapter's choice (docs/50: "one
    fixed string per chapter (light state + ...)"; EV moved from night to first light to high-key white). The
    chapter's light goes in the plate prompts themselves;
  * the palette names the measured neutrals by their real hue ("green-black #181e15", never a fixed "blue-black");
  * the one warm note only from an accent the owner chose (--accent or a confirmed verdict) — never from the
    template's default accent while the question is still open.

`--yes` also logs one dated line in DECISIONS.md (with the owner's words from --note), records the owner-valued
choices as confirmed verdicts in taste/verdicts.jsonl (so `slop taste tokens` shows them answered) and writes
taste/applied.json (what was applied, from which tokens).
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

from ..config import SlopError, load_project, save_project
from .store import now_iso, project_taste_dir, read_json, write_json

MODES = ("native", "clean-grade", "print")
NO_ACCENT = ("note: accent none = no warm note in the plates' style tail; the engine still uses its default accent "
             "colour where a graphics device needs one (give a hex to control it)")
MEDIA = ("photo", "cel")
TAIL_MAX = 240
FINISH = {"photo": "cinematic 35mm film still", "cel": "a hand-painted cel-animation film still"}
API_FINISH = {
    "photo": "photographed on a cinema camera with an anamorphic lens, natural colour, soft halation on the lights, "
             "{grain}slightly crushed blacks, a real photograph, not an illustration, not a 3D render",
    "cel": "a hand-painted cel-animation film still, clean ink outlines, flat colour with soft painted shading, "
           "painted background, consistent character design, not a photograph, not a 3D render",
}


def norm_hex(v: str) -> str | None:
    v = (v or "").strip()
    if v.lower() in ("none", "no", "-", ""):
        return None
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", v):
        raise SlopError(f"--accent {v!r}: give a hex colour like #D97757 (or none for no accent)")
    return "#" + v.lstrip("#").upper()


def hue_name(hexv: str) -> tuple[str, bool]:
    """a plain colour word for a hex + whether it reads as warm"""
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.15 or v < 0.12:
        return ("white" if v > 0.8 else "grey"), False
    deg = h * 360
    table = [(10, "red", True), (40, "orange", True), (62, "amber", True), (160, "green", False),
             (200, "teal", False), (255, "blue", False), (290, "violet", False), (335, "magenta", False),
             (361, "red", True)]
    for top, name, warm in table:
        if deg < top:
            if name == "orange":     # the docs' words: clay-orange (#D97757), ember / vermilion (#DB5C34)
                name = "clay-orange" if s < 0.65 else ("vermilion" if deg < 22 else "orange")
            return name, warm
    return "red", True


def _neutral(hexv: str | None, dark: bool) -> str | None:
    """the measured ink / paper hex only when it really is a near-black / near-white neutral (else no hex in the tail)"""
    if not hexv or not re.fullmatch(r"#[0-9a-fA-F]{6}", hexv):
        return None
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    _, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s > 0.45:
        return None
    return hexv if ((v < 0.3) if dark else (v > 0.75)) else None


def neutral_name(hexv: str, dark: bool) -> str:
    """the hue word of a near-neutral ink (dark) or paper (light) colour: green-black, blue-black, warm cream white..."""
    r, g, b = (int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < (0.12 if dark else 0.05):
        return "neutral black" if dark else "paper white"
    deg = h * 360
    fam = ("warm" if deg < 70 or deg >= 340 else "green" if deg < 170 else "blue" if deg < 260 else "violet")
    if dark:
        return {"warm": "warm brown-black", "green": "green-black", "blue": "blue-black", "violet": "violet-black"}[fam]
    return {"warm": "warm cream white", "green": "pale green-white", "blue": "cool blue-white",
            "violet": "pale violet-white"}[fam]


def style_tails(tokens: dict | None, accent: str | None, texture: bool | None, medium: str = "photo") -> dict:
    """-> {mj, api, parts}: the project's style tail from the tokens + the owner's answers (no light: per chapter).
    `accent` must be one the owner chose (or None): it becomes the one warm note."""
    if medium not in MEDIA:
        raise SlopError(f"--medium must be one of {', '.join(MEDIA)}")
    from .verdicts import ground_lean
    t = tokens or {}
    pal, gr = t.get("palette") or {}, t.get("ground") or {}
    lean = ground_lean(gr) if gr else "mixed"
    if (gr.get("status") == "rejected"):
        lean = "mixed"
    ink, paper = _neutral(pal.get("ink"), dark=True), _neutral(pal.get("paper"), dark=False)
    ink_w = f"{neutral_name(ink, True)} {ink}" if ink else None
    paper_w = f"{neutral_name(paper, False)} {paper}" if paper else None
    if lean == "dark":
        palette = f"{ink_w or 'near-black'} and deep greys"
    elif lean == "light":
        palette = f"{paper_w or 'paper white'} and soft greys"
    elif ink_w or paper_w:
        palette = " and ".join(x for x in (ink_w, paper_w) if x)
    else:
        palette = "quiet neutral tones"
    note = None
    if accent:
        name, warm = hue_name(accent)
        note = (f"one small {name} {accent} light as the only warm note" if warm else
                f"one small {name} {accent} light as the only accent")
    grain = "fine film grain" if texture else None
    parts = [p for p in (palette, note, grain, FINISH[medium]) if p]
    mj = ", ".join(parts)
    api = ", ".join([p for p in (palette, note) if p] +
                    [API_FINISH[medium].format(grain="fine film grain, " if texture else "")])
    return {"mj": mj, "api": api, "parts": {"palette": palette, "warm_note": note, "texture": grain,
                                            "finish": FINISH[medium], "ground_lean": lean,
                                            "light": "per chapter: write it in the plate prompts (docs/50 slot 7)"}}


def _font_families() -> set[str]:
    from .fonts import BANNED, font_dirs, scan_fonts
    return {f["family"] for f in scan_fonts(font_dirs()) if not any(b in f["family"].lower() for b in BANNED)}


def _check_font(name: str, fams: set[str]) -> str:
    want = re.sub(r"\s+", " ", name).strip()
    hit = next((f for f in fams if f.lower() == want.lower()), None)
    if not hit:
        raise SlopError(f"font {name!r} is not an OFL face shipped in engine/fonts. Available: "
                        f"{', '.join(sorted(fams)) or 'none (run bin/setup.sh)'}; nothing was changed")
    return hit


def plan(pdir: Path, accent: str | None = None, mode: str | None = None, lyric: str | None = None,
         micro: str | None = None, display: str | None = None, texture: str | None = None, medium: str = "photo",
         tail: str | None = None) -> dict:
    pdir = Path(pdir)
    proj = load_project(pdir)
    look = dict(proj.get("look") or {})
    t = read_json(project_taste_dir(pdir) / "taste-tokens.json")
    pal = (t or {}).get("palette") or {}
    src: dict[str, str] = {}
    new: dict = {}
    asks: list[str] = []
    # the verdicts as recorded come first (taste-tokens.json is derived from them and may predate the latest one: a
    # verdict or an earlier `apply --yes` must not be asked again just because `slop taste tokens` was not rerun)
    from . import verdicts as VD
    from .profile import project_name
    vd = VD.latest(VD.load_rows(pdir), project_name(pdir))
    v_acc, v_grade, v_tex = vd.get("palette.accent"), vd.get("palette.footage_grade"), vd.get("texture")
    # footage grade
    if mode:
        if mode not in MODES:
            raise SlopError(f"--mode {mode}: one of {', '.join(MODES)}; nothing was changed")
        new["mode"], src["mode"] = mode, "--mode"
    elif v_grade and v_grade["status"] == "confirmed" and v_grade.get("value") in MODES:
        new["mode"], src["mode"] = v_grade["value"], "owner verdict"
    elif not v_grade and pal.get("footage_grade_status") == "confirmed":
        new["mode"], src["mode"] = pal["footage_grade"], "owner verdict"
    else:
        new["mode"], src["mode"] = look.get("mode") or "native", "unchanged (native unless the owner says otherwise)"
    # accent
    if accent is not None:
        new["accent"], src["accent"] = norm_hex(accent), "--accent"
    elif v_acc and v_acc["status"] == "confirmed":
        new["accent"], src["accent"] = v_acc.get("value"), "owner verdict"
    elif not v_acc and pal.get("accent_source") == "owner verdict":
        new["accent"], src["accent"] = pal.get("accent"), "owner verdict"
    else:
        new["accent"], src["accent"] = look.get("accent"), "unchanged — ASK the owner (the taps never pick the accent)"
        asks.append("accent: which accent colour, if any? then --accent HEX (or --accent none)")
    # fonts
    fams = None
    fonts = dict(look.get("fonts") or {})
    ty = (t or {}).get("type") or {}
    for key, val in (("lyric", lyric), ("micro", micro), ("display", display)):
        if val:
            fams = fams if fams is not None else _font_families()
            fonts[key] = _check_font(val, fams)
            src[f"fonts.{key}"] = f"--{key}-font"
    if not lyric and ty.get("lyric"):
        fams = fams if fams is not None else _font_families()
        try:
            fonts["lyric"] = _check_font(ty["lyric"], fams)
            src["fonts.lyric"] = ("owner verdict" if ty.get("status") == "confirmed" else
                                  f"font A/B leader ({ty.get('status') or 'lead'}) — the owner's yes confirms it")
        except SlopError:
            asks.append(f"lyric font: the A/B leader {ty['lyric']} is not shipped in engine/fonts; pass --lyric-font")
    new["fonts"] = fonts
    # texture -> tail
    tex = None
    if texture is not None:
        tv = texture.strip().lower()
        if tv not in ("yes", "no", "grain", "none", "clean"):
            raise SlopError(f"--texture {texture!r}: yes (grain) or no; nothing was changed")
        tex, src["texture"] = tv in ("yes", "grain"), "--texture"
    elif v_tex:                    # the yes/no rule: grain only when confirmed (verdicts.py)
        tex, src["texture"] = v_tex["status"] == "confirmed" and v_tex.get("value") == "grain", "owner verdict"
    elif ((t or {}).get("texture") or {}).get("apply") is not None:
        tex, src["texture"] = bool(t["texture"]["apply"]), "owner verdict"
    else:
        src["texture"] = "not asked: the tail has no grain words (ask: grain yes/no? then --texture yes|no)"
        asks.append("texture: fine grain in the plates, yes or no? then --texture yes|no")
    owner_accent = src["accent"] in ("--accent", "owner verdict")    # never the template default while still asked
    tails = style_tails(t, new["accent"] if owner_accent else None, tex, medium)
    if tail:
        tail = re.sub(r"\s+", " ", tail).strip()
        if re.search(r"--\w", tail):
            raise SlopError("--tail must not contain Midjourney -- parameters (they go in project.json mj.params)")
        new["style_tail"], src["style_tail"] = tail, "--tail"
    else:
        new["style_tail"], src["style_tail"] = tails["mj"], "generated from the tokens + the answers above"
    new["style_tail_api"] = tails["api"] if not tail else tail + ", " + API_FINISH[medium].format(
        grain="fine film grain, " if tex else "")
    if len(new["style_tail"]) > TAIL_MAX:
        asks.append(f"the style tail is {len(new['style_tail'])} characters; keep it under {TAIL_MAX} (MJ prompts "
                    "have a ~800-character budget)")
    if not t:
        asks.insert(0, "no taste-tokens.json yet: the tail uses a neutral palette (run `slop taste tokens` after "
                       "tapping for a tail from the owner's taste)")
    changes = {}
    for k in ("mode", "accent", "style_tail", "style_tail_api"):
        if look.get(k) != new[k]:
            changes[k] = {"from": look.get(k), "to": new[k]}
    if (look.get("fonts") or {}) != fonts:
        changes["fonts"] = {"from": look.get("fonts"), "to": fonts}
    return {"look_now": look, "look_new": {**look, **new}, "set": new, "sources": src, "changes": changes,
            "asks": asks, "tails": tails, "tokens": bool(t), "medium": medium, "texture": tex}


def preview_text(p: dict) -> str:
    s, src = p["set"], p["sources"]
    fonts = s["fonts"]
    lines = ["Look to apply (show this to the owner; nothing is written yet):",
             f"  look.mode        {s['mode']}   [{src['mode']}]",
             f"  look.accent      {s['accent'] or 'none'}   [{src['accent']}]",
             f"  look.fonts       lyric {fonts.get('lyric') or '-'}, micro {fonts.get('micro') or '-'}, display "
             f"{fonts.get('display') or '-'}" + (f"   [lyric: {src['fonts.lyric']}]" if src.get("fonts.lyric") else ""),
             f"  look.style_tail  \"{s['style_tail']}\"",
             f"  (API version)    \"{s['style_tail_api']}\"",
             "  (the tail has no light / time of day: that is each chapter's choice — write it in the plate prompts; "
             "`slop board plates` appends this tail to every plate)"]
    if s["accent"] is None and src["accent"] == "--accent":
        lines.append(NO_ACCENT)
    if p["asks"]:
        lines.append("Ask the owner first:")
        lines += [f"  - {a}" for a in p["asks"]]
    lines.append("When the owner says yes, run the same command with --yes (add --note \"their words\").")
    return "\n".join(lines)


def apply(pdir: Path, yes: bool = False, note: str | None = None, **kw) -> dict:
    pdir = Path(pdir)
    p = plan(pdir, **kw)
    if not yes:
        return {**{k: p[k] for k in ("set", "sources", "changes", "asks", "tokens")}, "applied": False,
                "text": preview_text(p)}
    proj = load_project(pdir)
    look = dict(proj.get("look") or {})
    look.update(p["set"])
    proj["look"] = look
    save_project(pdir, proj)
    s = p["set"]
    summary = (f"look.mode {s['mode']}; look.accent {s['accent'] or 'none'}; look.fonts.lyric "
               f"{s['fonts'].get('lyric') or '-'}; look.style_tail \"{s['style_tail']}\"")
    dec = None
    from .profile import project_name
    try:
        from ..core_cli import append_decision
        dec = append_decision(pdir, "TASTE apply: " + summary + (f" (owner: '{note.strip()}')" if note and note.strip()
                                                                 else ""), by="owner")
    except SlopError as e:
        dec = {"recorded": False, "error": str(e)}
    # owner-valued choices become confirmed verdicts, so the tokens show them answered
    from . import verdicts as VD
    from .store import append_jsonl, new_eid
    src = p["sources"]
    rows = []
    for rule, val, key in (("palette.footage_grade", s["mode"], "mode"), ("palette.accent", s["accent"], "accent"),
                           ("type.lyric", s["fonts"].get("lyric"), "fonts.lyric")):
        if src.get(key, "").startswith(("--", "font A/B leader")):     # a flag, or the A/B leader the owner saw
            rows.append({"vid": new_eid(), "t": now_iso(), "level": "rule", "rule": rule, "value": val,
                         "status": "confirmed", "owner": {"verdict": "accept", "note": (note or "").strip() or None},
                         "project": project_name(pdir), "source": "slop taste apply"})
    if src.get("texture") == "--texture":      # the yes/no rule's canonical form: grain confirmed / rejected
        st = "confirmed" if p["texture"] else "rejected"
        rows.append({"vid": new_eid(), "t": now_iso(), "level": "rule", "rule": "texture", "value": "grain",
                     "status": st, "owner": {"verdict": "accept" if p["texture"] else "reject",
                                             "note": (note or "").strip() or None},
                     "project": project_name(pdir), "source": "slop taste apply"})
    pf, uf = VD.project_file(pdir), VD.profile_file(pdir)
    for r in rows:
        append_jsonl(pf, r)
        if uf.resolve() != pf.resolve():
            append_jsonl(uf, r)
    write_json(project_taste_dir(pdir) / "applied.json", {"t": now_iso(), "look": s, "sources": src,
                                                          "note": note, "tokens": p["tokens"]})
    return {"set": s, "sources": src, "changes": p["changes"], "applied": True, "decision": dec,
            "verdicts": len(rows),
            "text": "applied to project.json: " + summary
                    + ("\nlogged in DECISIONS.md" if (dec or {}).get("recorded") or (dec or {}).get("duplicate") else
                       f"\nNOT logged in DECISIONS.md ({(dec or {}).get('error')}): record it with slop decide")
                    + (f"; {len(rows)} owner choice(s) recorded as confirmed verdicts" if rows else "")
                    + (("\n" + NO_ACCENT) if s["accent"] is None and src.get("accent") == "--accent" else "")
                    + ("\nstill to ask: " + "; ".join(p["asks"]) if p["asks"] else "")
                    + "\nnext: `slop board plates` appends look.style_tail to every plate prompt it books (write "
                      "each chapter's light in the prompts themselves); a one-off `slop gen image` prompt ends with "
                      "look.style_tail_api. Then: slop status"}
