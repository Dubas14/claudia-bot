"""Write the storyboard with commands instead of JSON editing (the board's biggest manual step, INTEGRATION §4.2/5).

  slop board set SHOT [--set T] [--framing F] [--action T] [--img-prompt T | --mj-prompt T] [--camera T]
                      [--treatment F] [--transition-in T] [--lead | --no-lead] [--line N] [--type-mode M]
                      [--type-text T] [--type-placement P] [--subject-uv u,v,w,h] [--notes T]
      SHOT is one id (s004), a list (s004,s007) or a range in board order (s004-s009).
      One board, one generator: the prompt field of the generator the board does not use is refused with the right
      flag named (project.json board.generator, else the field every shot with a prompt uses, else the tier: quick =
      --img-prompt, studio/director = --mj-prompt; a board that mixes both follows the tier); --switch-generator
      writes it on purpose. A shot whose own plate is off the board's generator is named as such, with the command
      that brings it back (the board's flag + --switch-generator); editing its own prompt only warns.
  slop board set SHOT [--tier still|plate3d|motion|sung] [--clip CLIP|none]
      the shot's motion tier and its clip: link a clip made after the board (`board set s001-s002 --tier motion --clip
      c08`) so `edit edl` plays it. The clip must exist (clips/<clip>.json or the board's clip plan), be a root clip
      (not a cover), match the tier (motion <-> motion clip, sung <-> sung clip; no --tier = the clip's kind) and play
      inside the shot (its song window overlaps it; a partial cover warns). still/plate3d unlink the clip; motion/sung
      alone on a shot that plays a clip of the other kind is refused (add --clip CLIP or --clip none); EV's "seedance"
      tier reads as the clip's kind. The clip plan (seedance[]) follows: the shot leaves other entries, an entry left
      with no shot that was never made is dropped (the note prints its `clip new`).
      A plate-only treatment is cleared on a shot that becomes a clip shot; a plate3d shot without one warns.
  Any command here that changes the board after the owner approved it (G4) prints one warning line: the board gate is
  stale, show the owner the change and re-approve with `slop gate board --approve` (`plates vary` and `board draft
  --force` say it too).
  slop board fill FILE [--check]
      many shots at once from a TSV (a header row of field names, one row per shot; an empty cell leaves the field as
      it is; a cell wrapped in double quotes by a spreadsheet is unquoted) or JSONL (one {"id": "s004", "set": "…", …}
      per line). Every row is validated first; one bad row fails the whole fill and nothing is written (the error lists
      every bad row). --check validates only (its next step is the same fill without --check). A `devices` column / key
      REPLACES the shot's whole devices[] list ([] clears it); to add one device use `board device add`.
  slop board device add SHOT --kind K [--line N] [--anchor A] [--key W|B|H|F|T] [--param k=v ...] [--params JSON]
                         [--replace I]
                         [--at SPEC] [--until SPEC] [--example]
      --param values are JSON when they parse (numbers, [..], {..}) — except word, word_end, at and until, which stay
      text (`word=13` is the sung word "13": a number there would be lyric line 13 to the engine). A camera move takes
      no --line (it is never a line's graphic). --example starts from the catalogue entry (its key and anchor too);
      its on-screen text must be replaced in the same command (the check refuses the catalogue's own words).
  slop board device rm SHOT (--index I | --kind K | --line N) [--all]
  slop board device list [SHOT]
  slop board device kinds [--kind K]

Every value is checked against what the engine reads (slop/board/vocab.py, devices.py): framings (ECU…OTS, or words
like "close-up"), treatments (any name, alias, code or prose engine/src/devices/treat.js accepts), transitions
(engine/src/devices/trans.js presets, aliases and prose), type modes, device kinds/params/keys/time specs. A command
that fails changes nothing. Re-running a command with the same values is a no-op (safe to repeat).
Text still holding a next-step hint's placeholder ("…", "<the place>", TODO) is refused everywhere (set, fill, device
add, and the audit's todo/devices gates): the hints print <…> markers to replace, never values that would pass.
The type rule of docs/40 §3.6 is kept by construction: a line's mode and placement are written to every shot that
types the line ("a line is one mode and one position, held across cuts").
"""
from __future__ import annotations

import bisect
import json
import re
import shlex
from pathlib import Path

from ..config import SlopError, load_project
from . import devices as devlib
from . import vocab
from .common import (FRAMINGS, TIERS, TODO, board_gate_stale, clip_kinds, engine_treatment, graphic_hint, line_texts,
                     load_shots, load_words, mouth_blockers, pcmd, placeholder, read_json, save_shots, set_hint,
                     shot_clips, shot_plate, shot_tier)

# field -> shots.json key (the CLI flag is the field with "-" for "_"); tier -> motion_tier, clip -> clip (linked)
FIELDS = ("set", "framing", "action", "img_prompt", "mj_prompt", "prompt", "camera", "treatment", "transition_in",
          "lead", "line", "type_mode", "type_text", "type_placement", "subject_uv", "notes", "tier", "clip")
FILL_ALIASES = {"shot": "id", "lead_on_screen": "lead", "transition": "transition_in", "trans": "transition_in",
                "type": "type_mode", "mode": "type_mode", "placement": "type_placement", "text": "type_text",
                "subject": "subject_uv", "note": "notes", "image_prompt": "img_prompt", "midjourney_prompt": "mj_prompt",
                "motion_tier": "tier", "clip_id": "clip"}
TIER_ALIASES = {"2.5d": "plate3d", "plate25d": "plate3d", "plate-3d": "plate3d", "lipsync": "sung", "lip-sync": "sung",
                "singing": "sung", "video": "motion"}
UNLINK = {"", "none", "null", "-", "no", "off"}
BAD_TAKE = ("failed", "declined", "rejected")
TRUE = {"1", "true", "yes", "y", "on", "lead", "x"}
FALSE = {"0", "false", "no", "n", "off", "-", "none"}
CLIP_TREATMENTS = {"stills", "diagram", "xerox", "occlusion", "motion"}
PLACEMENTS = ("left", "right", "center", "centre", "top", "upper", "bottom", "lower")
# one board, one generator (critic P1: a Quick board given --mj-prompt silently became a Midjourney plate)
GEN_ALIASES = {"api": "img_prompt", "img": "img_prompt", "image": "img_prompt", "images": "img_prompt",
               "img_prompt": "img_prompt", "mj": "mj_prompt", "midjourney": "mj_prompt", "mj_prompt": "mj_prompt"}
PROMPT_FLAG = {"img_prompt": "--img-prompt", "mj_prompt": "--mj-prompt"}
GEN_NAME = {"img_prompt": "API images", "mj_prompt": "Midjourney"}
PLATE_NAME = {"img_prompt": "an API-image plate", "mj_prompt": "a Midjourney plate"}
BOARD_NAME = {"img_prompt": "an API-images board", "mj_prompt": "a Midjourney board"}
GEN_WORD = {"img_prompt": "api", "mj_prompt": "mj"}


class Ctx:
    """What the validators need, loaded once per command."""

    def __init__(self, pdir: Path):
        self.pdir = Path(pdir)
        self.proj = load_project(self.pdir)
        self.S = load_shots(self.pdir)
        self.W = load_words(self.pdir)
        self.lines = {int(l["line"]) for l in self.W.get("lines", []) if isinstance(l.get("line"), int)} | \
            {int(w["line"]) for w in self.W["words"] if isinstance(w.get("line"), int)}
        self._texts = None
        bx = read_json(self.pdir / "plates/boxes.json", default={}) or {}
        self.boxes = {k: (v.get("boxes") if isinstance(v, dict) and "boxes" in v else v) for k, v in bx.items()}
        self.order = [s["id"] for s in sorted(self.S["shots"], key=lambda s: (float(s["t0"]), float(s["t1"])))]
        self.by_id = {s["id"]: s for s in self.S["shots"]}

    @property
    def texts(self) -> dict[int, str]:
        if self._texts is None:
            self._texts = line_texts(self.pdir, self.W)
        return self._texts

    def sung(self, sh: dict) -> list[str]:
        """The words a device's `word` can name in this shot: aligned words + the display.txt tokens the engine
        matches ("13" where the aligner heard "Thirteen")."""
        if not hasattr(self, "_tokens"):
            self._tokens = devlib.display_tokens(self.pdir, self.W)
        return devlib.shot_word_list(sh, self.W["words"], self._tokens)

    def shot(self, sid: str) -> dict:
        sh = self.by_id.get(sid)
        if sh is None:
            near = devlib.suggest(sid, self.by_id)
            raise SlopError(f"no shot '{sid}' in board/shots.json" + (f" (did you mean {near}?)" if near else "")
                            + (f" — shots run {self.order[0]}…{self.order[-1]}" if self.order else "")
                            + "; nothing was changed")
        return sh

    def select(self, spec: str) -> list[str]:
        """'s004' | 's004,s007' | 's004-s009' (board order, inclusive) | 'all'."""
        spec = (spec or "").strip()
        if not spec:
            raise SlopError("name a shot: e.g. s004, s004,s007 or s004-s009")
        if spec.lower() == "all":
            return list(self.order)
        out: list[str] = []
        for part in [p.strip() for p in spec.split(",") if p.strip()]:
            m = re.fullmatch(r"([A-Za-z]\w*?)\s*(?:-|\.\.)\s*([A-Za-z]\w*)", part)
            if m and m.group(1) in self.by_id and m.group(2) in self.by_id:
                a, b = self.order.index(m.group(1)), self.order.index(m.group(2))
                if a > b:
                    a, b = b, a
                out += self.order[a:b + 1]
            else:
                self.shot(part)
                out.append(part)
        return list(dict.fromkeys(out))

    def words_in(self, sh: dict) -> list[dict]:
        return [w for w in self.W["words"] if float(sh["t0"]) <= w["t0"] < float(sh["t1"])]

    def prompt_key(self, sh: dict) -> str:
        """the field the generic `prompt` writes: the shot's own prompt field (edited in place; normalise warns when it
        is off the board's generator) unless project.json board.generator names the board's, else the board's."""
        g, why = self.board_generator()
        own = own_prompt(sh)
        return own if own and why != "project.json board.generator" else g

    def board_generator(self) -> tuple[str, str]:
        """(the prompt field this board's plates use, why): project.json board.generator, else the field every shot
        with a prompt uses, else the tier's default (quick = API images, studio/director = Midjourney). A board that
        mixes both (a leftover of the old silent switch) follows the tier too: it is never a licence for either."""
        if not hasattr(self, "_gen"):
            g = GEN_ALIASES.get(str((self.proj.get("board") or {}).get("generator") or "").strip().lower())
            if g:
                self._gen = (g, "project.json board.generator")
            else:
                kinds = {k for s in self.S["shots"] for k in ("img_prompt", "mj_prompt") if k in s}
                tier = str(self.proj.get("tier") or "quick")
                tier_g = "img_prompt" if tier == "quick" else "mj_prompt"
                if len(kinds) == 1:
                    k = next(iter(kinds))
                    self._gen = (k, f"the board's shots use {k}")
                elif kinds:
                    self._gen = (tier_g, f"the {tier} tier's default; the board mixes both")
                else:
                    self._gen = (tier_g, f"the {tier} tier's default")
        return self._gen

    def expected_prompt(self, sh: dict) -> tuple[str, str]:
        """(the prompt field this shot should get, why): always the board's generator. A shot whose own field differs
        is an off-board plate; normalise names it and the command that brings it back."""
        return self.board_generator()

    # ---- clips (for --tier / --clip)
    @property
    def kinds(self) -> dict[str, str]:
        """clip id -> sung | motion, from the board's clip plan (seedance[]) and clips/*.json."""
        if not hasattr(self, "_kinds"):
            self._kinds = clip_kinds(self.pdir, self.S)
        return self._kinds

    def clip_doc(self, cid: str) -> dict | None:
        """clips/<cid>.json (a clip gen made), or None."""
        if not hasattr(self, "_clip_docs"):
            self._clip_docs = {}
            d = self.pdir / "clips"
            for f in sorted(d.glob("*.json")) if d.is_dir() else []:
                c = read_json(f, default=None)
                if isinstance(c, dict):
                    self._clip_docs[str(c.get("id") or f.stem)] = c
        return self._clip_docs.get(cid)

    def plan_entry(self, cid: str) -> dict | None:
        """the board's clip plan entry (seedance[]) for cid, or None."""
        return next((c for c in self.S.get("seedance") or [] if (c.get("clip") or c.get("id")) == cid), None)

    def footage(self, cid: str) -> tuple[float, float] | None:
        """(song_t0, song_t0 + duration) of the clip's window: what the edit can play (song time)."""
        c = self.clip_doc(cid) or self.plan_entry(cid) or {}
        t0 = c.get("song_t0")
        dur = (c.get("body") or {}).get("duration") if isinstance(c.get("body"), dict) else None
        dur = dur or c.get("duration")
        try:
            return (float(t0), float(t0) + float(dur)) if t0 is not None and dur else None
        except (TypeError, ValueError):
            return None

    def delivered(self, cid: str) -> bool:
        """True when the edit would play this clip: the edit's own test (a usable take whose file is on disk)."""
        try:
            from ..edit.edl import Edit
            return Edit(self.pdir).delivered(cid)
        except ImportError:
            c = self.clip_doc(cid) or {}
            return any(isinstance(t, dict) and t.get("file") and t.get("status") not in BAD_TAKE
                       and not t.get("rejected") for t in c.get("takes") or [])

    def clips_for(self, sh: dict) -> list[str]:
        """root clips made for this shot (clips/*.json "shot") or whose needed span covers it — the edit's own
        fallbacks (slop/edit/edl.py candidates)."""
        self.clip_doc("")
        a, b = float(sh["t0"]), float(sh["t1"])
        out = []
        for cid, c in sorted(self._clip_docs.items()):
            if c.get("parent"):
                continue
            nd = c.get("needed")
            try:
                covers = isinstance(nd, list) and len(nd) == 2 and float(nd[0]) <= a + 1e-3 and float(nd[1]) >= b - 1e-3
            except (TypeError, ValueError):
                covers = False
            if c.get("shot") == sh.get("id") or covers:
                out.append(cid)
        return out


# ------------------------------------------------------------------------------------------------ validators
def own_prompt(sh: dict) -> str | None:
    """the shot's own plate prompt field (img_prompt or mj_prompt), or None (none, or both)."""
    own = [k for k in ("img_prompt", "mj_prompt") if k in sh]
    return own[0] if len(own) == 1 else None


def _text(v, field: str, allow_empty: bool = False) -> str:
    s = str(v if v is not None else "").strip()
    if not s and not allow_empty:
        raise ValueError(f"{field} is empty")
    ph = placeholder(s)
    if ph:
        raise ValueError(f"{field}: {ph} — write the real text")
    return s


def _bool(v, field: str) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in TRUE:
        return True
    if s in FALSE:
        return False
    raise ValueError(f"{field} '{v}' is not yes/no (true/false, 1/0)")


def _uv(v, field: str) -> list[float]:
    vals = v if isinstance(v, list) else [x for x in re.split(r"[,\s]+", str(v).strip()) if x]
    try:
        nums = [float(x) for x in vals]
    except (TypeError, ValueError):
        raise ValueError(f"{field} '{v}' must be four numbers u,v,w,h in 0..1 (e.g. 0.40,0.15,0.30,0.80)")
    if len(nums) != 4 or not all(0 <= x <= 1 for x in nums) or nums[2] <= 0 or nums[3] <= 0 \
            or nums[0] + nums[2] > 1.001 or nums[1] + nums[3] > 1.001:
        raise ValueError(f"{field} {nums}: four numbers u,v,w,h in 0..1 of the image (u+w and v+h at most 1)")
    return [round(x, 4) for x in nums]


def _line(v, ctx: Ctx, field: str = "line") -> int:
    try:
        li = int(str(v).strip())
    except ValueError:
        raise ValueError(f"{field} '{v}' is not a lyric line number (0-based, as in analysis/words.json)")
    if ctx.lines and li not in ctx.lines:
        raise ValueError(f"{field} {li} is not a lyric line (lines {min(ctx.lines)}–{max(ctx.lines)})")
    return li


def check_prompt(ctx: Ctx, sh: dict, prompt: str, framing: str | None, sung: bool = False) -> list[str]:
    """Plate-prompt lint from the prompt book (framing first, no '--' params, braces; on a sung shot nothing at the
    mouth) as warnings; braces are errors."""
    from .plates import expand
    plate = shot_plate(sh, ctx.S) or sh.get("id")
    e = {"plate": plate, "lead": bool(sh.get("lead_on_screen")), "framings": [framing] if framing else [],
         "sung": sung}
    try:
        _, warns = expand(prompt, e, ctx.proj)
    except SlopError as err:
        raise ValueError(str(err))
    return [w.split(": ", 1)[1] if w.startswith(f"{plate}: ") else w for w in warns
            if "inserted automatically" not in w]


def _tier_clip(ctx: Ctx, sh: dict, fields: dict, errs: list[str], warns: list[str], notes: list[str],
               out: dict) -> tuple[str, list[str]]:
    """--tier / --clip for one shot -> (its tier after the command, its clips after it). Writes out["_tier"] and
    out["_clip"] (a clip id, or "" = unlink every clip), and clears a plate-only treatment on a shot that becomes a clip
    shot (the draft's rule: clip shots carry none)."""
    sid = sh["id"]
    cur_tier = shot_tier(sh, ctx.kinds)
    cur_clips = shot_clips(sh)
    tier = None
    if "tier" in fields:
        t = str(fields["tier"] if fields["tier"] is not None else "").strip().lower()
        t = TIER_ALIASES.get(t, t)
        if t == "seedance":                           # EV/SP's tier: a clip shot, sung or motion by its clip
            given = str(fields.get("clip") or "").strip()
            ref = given if given and given.lower() not in UNLINK else (cur_clips[0] if cur_clips else "")
            t = ctx.kinds.get(ref, "") if ref else ""
            if not t:
                errs.append(f"tier 'seedance' (EV's clip tier) says a clip plays here but not which kind: use --tier "
                            "motion or --tier sung (docs/40 §8.1)")
                return cur_tier, cur_clips
        if t not in TIERS:
            errs.append(f"tier '{fields['tier']}' is not one of {' · '.join(TIERS)} (docs/40 §8.1)")
            return cur_tier, cur_clips
        tier = t
    clip = None                                       # None: no --clip; "": unlink; else the clip id
    if "clip" in fields:
        c = str(fields["clip"] if fields["clip"] is not None else "").strip()
        if c.lower() in UNLINK:
            clip = ""
        elif ctx.clip_doc(c) is None and ctx.plan_entry(c) is None:
            near = devlib.suggest(c, ctx.kinds) if ctx.kinds else None
            errs.append(f"clip '{c}' is neither made (clips/{c}.json) nor on the board's clip plan (seedance[])"
                        + (f" — did you mean {near}?" if near else "") + "; `slop clip list` lists the clips (make one "
                        f"with `slop clip new {sid} --kind motion …`)")
            return cur_tier, cur_clips
        elif (ctx.clip_doc(c) or {}).get("parent"):
            errs.append(f"clip {c} is a divergence cover of {ctx.clip_doc(c)['parent']}: link the root clip "
                        f"{ctx.clip_doc(c)['parent']} (its covers play inside it)")
            return cur_tier, cur_clips
        else:
            clip = c
    if clip is None and tier in ("sung", "motion") and cur_clips and ctx.kinds.get(cur_clips[0]) not in (None, tier):
        kind = ctx.kinds[cur_clips[0]]               # --tier alone would leave the shot on a clip of the other kind
        errs.append(f"--tier {tier}: {sid} plays {cur_clips[0]}, a {kind} clip — "
                    + ("a sung shot needs a sung clip (her mouth sings the words)" if tier == "sung" else
                       "a motion shot plays a motion clip (the edit would still lip-sync the sung one)")
                    + f": add --clip <a {tier} clip> to link one, or --clip none to unlink {cur_clips[0]} (the edit then "
                    "shows the plate until a clip is linked)")
        return cur_tier, cur_clips
    if clip:
        kind = ctx.kinds.get(clip, "motion")
        if tier is None:
            if cur_tier != kind:
                notes.append(f"{sid}: motion_tier {cur_tier} -> {kind} ({clip} is a {kind} clip)")
            tier = kind
        elif tier in ("still", "plate3d"):
            errs.append(f"--tier {tier} with --clip {clip}: a {tier} shot plays its plate, never a clip — use --tier "
                        f"{kind} to play {clip} (or --tier {tier} alone to unlink its clip)")
            return cur_tier, cur_clips
        elif tier != kind:
            errs.append(f"--tier {tier} with --clip {clip}, a {kind} clip: "
                        + ("a sung shot needs a sung clip (her mouth sings the words)" if tier == "sung" else
                           "a motion shot plays a motion clip (a sung clip lip-syncs)")
                        + f" — use --tier {kind}, or link a {tier} clip")
            return cur_tier, cur_clips
        span = ctx.footage(clip)
        a, b = float(sh["t0"]), float(sh["t1"])
        if span:
            f0, f1 = span
            if min(b, f1) - max(a, f0) <= .05:
                errs.append(f"{clip} plays song {f0:.2f}–{f1:.2f} s and {sid} is {a:.2f}–{b:.2f} s: a clip plays in song "
                            "time, so it shows nothing in this shot — link a clip whose window covers it")
                return cur_tier, cur_clips
            if f0 > a + .06 or f1 - .1 < b - .05:
                warns.append(f"{clip} covers {f0:.2f}–{f1:.2f} s but {sid} runs {a:.2f}–{b:.2f} s: outside the clip the "
                             "edit holds a frame (motion) or leaves a hole (sung)")
        if ctx.clip_doc(clip) is None:
            notes.append(f"{sid}: {clip} is planned but not made yet (`slop board audit` prints its `clip new`); the edit "
                         "shows the plate until it is delivered")
        elif not ctx.delivered(clip):
            notes.append(f"{sid}: {clip} has no delivered take the edit can play yet (status "
                         f"{ctx.clip_doc(clip).get('status')}; a take file on disk, not rejected): the edit shows the "
                         "plate until it has one")
        out["_clip"] = clip
    elif clip == "":
        out["_clip"] = ""
    new_tier = tier or cur_tier
    if tier is not None:
        out["_tier"] = tier
    if new_tier in ("still", "plate3d"):
        if cur_clips and clip is None:
            out["_clip"] = ""                             # a plate shot plays its plate: its clip links go
        if new_tier == "plate3d" and "treatment" not in fields and not sh.get("treatment"):
            warns.append(f"{sid} is a 2.5D (plate3d) shot without a treatment: the audit's treatments gate needs one — "
                         + pcmd(ctx.pdir, f"board set {sid} --treatment \"<family>\"") + " (`auto` lets the engine pick)")
        return new_tier, []
    clips = ([clip] + [x for x in cur_clips if x != clip]) if clip else ([] if clip == "" else cur_clips)
    if not clips:
        found = ctx.clips_for(sh)
        notes.append(f"{sid}: a {new_tier} shot with no clip linked — "
                     + (f"the edit plays {found[0]} (made for it or covering it) when delivered; link it with --clip "
                        f"{found[0]}" if found else "link one with --clip CLIP (`slop clip list`), else the edit shows "
                        "the plate"))
    if "treatment" not in fields and sh.get("treatment") and cur_tier not in ("sung", "motion"):
        fam = engine_treatment(sh)
        if fam not in CLIP_TREATMENTS:
            out["treatment"] = None
            notes.append(f"{sid}: treatment '{sh['treatment']}' cleared (a 2.5D look of the plate; a clip shot plays "
                         f"its footage — clip shots take {', '.join(sorted(CLIP_TREATMENTS))})")
    if new_tier == "sung" and tier is not None and not any(ctx.words_in(sh)):
        warns.append(f"{sid}: no sung word starts in it — a sung shot is a mouth singing the song's words")
    if new_tier == "sung" and "img_prompt" not in fields and "mj_prompt" not in fields and "prompt" not in fields:
        for k in ("mj_prompt", "img_prompt"):
            bl = mouth_blockers(sh.get(k) or "") if TODO not in str(sh.get(k) or "") else []
            if bl:
                warns.append(f"{sid} sings now, but its {k} puts {', '.join(repr(x) for x in bl)} at her mouth: "
                             "rewrite it with the mouth fully visible (it is the lip-sync start frame)")
    return new_tier, clips


def normalise(ctx: Ctx, sh: dict, fields: dict, switch: bool = False) -> tuple[dict, list[str]]:
    """Validate one shot's field values -> (clean values, warnings). Raises ValueError with every problem.
    A plate prompt for the generator this board does not use is refused (naming the right flag) unless `switch`."""
    errs: list[str] = []
    warns: list[str] = []
    out: dict = {}
    sid = sh["id"]

    def guard(fn):
        try:
            return fn()
        except ValueError as e:
            errs.append(str(e))
            return None

    for k in ("set", "action", "camera", "notes"):
        if k in fields:
            v = guard(lambda k=k: _text(fields[k], k, allow_empty=k in ("camera", "notes")))
            if v is not None:
                out[k] = v
    if out.get("camera"):
        if not any(w in out["camera"].lower() for w in vocab.CAMERA_WORDS):
            warns.append(f"camera '{out['camera']}': the engine reads push · pull · pan/truck left/right · tilt/crane · "
                         "orbit · static/locked · handheld — no camera word found, it drifts gently")
    if "framing" in fields:
        f = vocab.framing(fields["framing"])
        if not f:
            errs.append(f"framing '{fields['framing']}' is not one of {'|'.join(FRAMINGS)} (or words like close-up, "
                        "medium shot, wide shot, extreme wide shot)")
        else:
            out["framing"] = f
    if "tier" in fields or "clip" in fields:
        lnotes: list[str] = []
        tier_after, clips_after = _tier_clip(ctx, sh, fields, errs, warns, lnotes, out)
        if lnotes:
            out["_notes"] = lnotes
    else:
        tier_after, clips_after = shot_tier(sh, ctx.kinds), shot_clips(sh)
    if "prompt" in fields:
        fields = {**fields, ctx.prompt_key(sh): fields["prompt"]}
    pk = [k for k in ("img_prompt", "mj_prompt") if k in fields]
    want, why = ctx.expected_prompt(sh) if pk else (None, "")
    own = own_prompt(sh)
    explicit = why == "project.json board.generator"
    back = pcmd(ctx.pdir, f"board set {sid} {PROMPT_FLAG[want]} \"…\" --switch-generator") if want else ""
    if len(pk) == 2:
        errs.append("give --img-prompt (API images) or --mj-prompt (Midjourney), not both")
    elif pk and pk[0] != want and not switch and (explicit or own != pk[0]):
        k = pk[0]
        errs.append(f"{PROMPT_FLAG[k]}: this board's plates are {GEN_NAME[want]} ({why}), so write {PROMPT_FLAG[want]} "
                    f"\"…\" instead (same prompt grammar). Only to make {sid}'s plate {PLATE_NAME[k]} on purpose, "
                    f"add --switch-generator (its {want} is removed); to switch the whole board: "
                    + pcmd(ctx.pdir, f"project set board.generator {GEN_WORD[k]}"))
    elif pk and pk[0] == want and own and own != want and not switch and not explicit:
        errs.append(f"{sid} is {PLATE_NAME[own]} (it has an {own}) on {BOARD_NAME[want]} ({why}). To bring it back to "
                    f"{GEN_NAME[want]}, run the same command with --switch-generator (its {own} is removed): {back}")
    elif pk:
        if pk[0] != want and own == pk[0] and not switch:
            warns.append(f"{sid} stays {PLATE_NAME[own]} on {BOARD_NAME[want]} ({why}); to bring it back to "
                         f"{GEN_NAME[want]}: {back}")
        k = pk[0]
        v = guard(lambda: _text(fields[k], k.replace("_", "-")))
        if v is not None:
            sung = tier_after == "sung" or bool(tier_after == "motion" and clips_after
                                                and ctx.kinds.get(clips_after[0]) == "sung")
            if not sung:                               # its plate starts another sung shot or a planned sung window
                from .plates import sung_plates
                sung = (shot_plate(sh, ctx.S) or "").split("~")[0] in sung_plates(ctx.pdir, ctx.S)
            try:
                warns += [f"{k}: {w}" for w in check_prompt(ctx, sh, v, out.get("framing") or sh.get("framing"),
                                                            sung=sung)]
                out[k] = v
            except ValueError as e:
                errs.append(f"{k}: {e}")
    if "treatment" in fields:
        t = fields["treatment"]
        t = t.strip() if isinstance(t, str) else t
        if t in (None, "", "auto") or (isinstance(t, str) and t.lower() == "auto"):
            if tier_after == "plate3d":
                errs.append(f"treatment '{t or ''}': a 2.5D (plate3d) shot names its treatment (the audit's treatments "
                            f"gate) — one of {', '.join(vocab.treatments()['families'])}")
            else:
                out["treatment"] = None
        else:
            fam, unknown = vocab.treatment_parse(t)
            if unknown:
                errs.append(f"treatment '{t}' is not one the engine knows (families: "
                            f"{', '.join(vocab.treatments()['families'])}; the board's names layer-separation, "
                            "depth-as-image, diagram-over-image, stills-in-rhythm, reproduction, pure-motion; codes "
                            "LS DI RP SR DG PM OC)")
            else:
                out["treatment"] = t
                if str(t).strip().lower() == "none":
                    warns.append("treatment 'none' draws a code-drawn frame with no footage (the engine's 'motion' "
                                 "family); to let the engine pick, use --treatment auto")
                if tier_after in ("sung", "motion") and clips_after and fam not in CLIP_TREATMENTS:
                    warns.append(f"{sid} plays a clip: '{t}' needs a plate, so the clip plays through the camera "
                                 f"(clip shots take {', '.join(sorted(CLIP_TREATMENTS))})")
                look = str((ctx.proj.get("look") or {}).get("mode") or "native")
                if fam == "xerox" and look != "print":
                    warns.append(f"'{t}' is a print-look texture (xerox); this project's look is {look} — the engine "
                                 "keeps it but reports it")
    if "transition_in" in fields:
        t = fields["transition_in"]
        t = t.strip() if isinstance(t, str) else t
        preset, unknown = vocab.transition_parse(t)
        if unknown:
            errs.append(f"transition '{t}' is not one the engine knows: {', '.join(vocab.transition_names())} "
                        "(prose works too: \"whip left\", \"push through the pupil\", \"flash cut\")")
        else:
            out["transition_in"] = t if t not in (None, "") else "cut"
    if "lead" in fields:
        v = guard(lambda: _bool(fields["lead"], "lead"))
        if v is not None:
            out["lead_on_screen"] = v
    if "subject_uv" in fields:
        v = guard(lambda: _uv(fields["subject_uv"], "subject-uv"))
        if v is not None:
            out["subject_uv"] = v
    if any(k in fields for k in ("type_mode", "type_text", "type_placement", "line")):
        ty: dict = {}
        if fields.get("line") not in (None, ""):
            li = guard(lambda: _line(fields["line"], ctx))
            if li is not None:
                ty["line"] = li
        if fields.get("type_mode") not in (None, ""):
            m = vocab.type_mode(fields["type_mode"])
            if not m:
                errs.append(f"type mode '{fields['type_mode']}' is not one of {', '.join(vocab.TYPE_MODES)}")
            else:
                ty["mode"] = m
        if fields.get("type_text") not in (None, ""):
            v = guard(lambda: _text(fields["type_text"], "type-text"))
            if v is not None:
                ty["text"] = v
        if fields.get("type_placement") not in (None, ""):
            p = str(fields["type_placement"]).strip()
            if placeholder(p):
                errs.append(f"type placement '{p}' is a placeholder — one of left · right · center · top · bottom")
            elif not any(w in p.lower() for w in PLACEMENTS):
                warns.append(f"type placement '{p}': the engine reads left · right · center · top/upper · "
                             "bottom/lower (anything else is placed left)")
            ty["placement"] = p
        if ty:
            out["_type"] = ty
    if errs:
        raise ValueError("; ".join(errs))
    return out, warns


# ------------------------------------------------------------------------------------------------ apply
def _type_line(ctx: Ctx, sh: dict, ty: dict) -> int:
    entries = [t for t in sh.get("type") or [] if isinstance(t, dict) and isinstance(t.get("line"), int)]
    if "line" in ty:
        return ty["line"]
    if len(entries) == 1:
        return entries[0]["line"]
    if not entries:
        sung = sorted({w["line"] for w in ctx.words_in(sh) if isinstance(w.get("line"), int)})
        raise ValueError(f"{sh['id']} types no lyric line yet — add --line N"
                         + (f" (lines sung in it: {', '.join(map(str, sung))})" if sung else ""))
    raise ValueError(f"{sh['id']} types lines {', '.join(str(t['line']) for t in entries)} — add --line N to say "
                     "which one")


def apply(ctx: Ctx, sid: str, clean: dict, notes: list[str]) -> list[str]:
    """Apply validated values to one shot (and, for type mode/placement/text, to every shot typing that line).
    Returns the names of the fields that changed."""
    sh = ctx.by_id[sid]
    changed: list[str] = []

    def put(obj: dict, k: str, v) -> bool:
        if obj.get(k) != v or k not in obj:
            obj[k] = v
            return True
        return False

    notes += clean.get("_notes") or []
    if "_tier" in clean or "_clip" in clean:
        changed += _link(ctx, sid, clean.get("_tier"), clean.get("_clip"), notes)
    for k, v in clean.items():
        if k.startswith("_"):
            continue
        if k in ("img_prompt", "mj_prompt"):
            other = "mj_prompt" if k == "img_prompt" else "img_prompt"
            if other in sh:
                if sh[other] and TODO not in str(sh[other]):
                    notes.append(f"{sid}: removed its {other} (one plate, one generator: {k} now)")
                del sh[other]
                changed.append(other)
            plate = shot_plate(sh, ctx.S)
            owner = next((x for x in ctx.order if shot_plate(ctx.by_id[x], ctx.S) == plate), sid) if plate else sid
            if owner != sid:
                notes.append(f"{sid} shares plate {plate} with {owner} (one continuous moment): the prompt book reads "
                             f"the first shot's prompt — write it on {owner}")
        if put(sh, k, v):
            changed.append(k)
    ty = clean.get("_type")
    if ty:
        li = _type_line(ctx, sh, ty)
        entries = [t for t in sh.get("type") or [] if isinstance(t, dict) and t.get("line") == li]
        if not entries:
            if not isinstance(sh.get("type"), list):
                sh["type"] = []
            same = next((t for x in ctx.order for t in ctx.by_id[x].get("type") or []
                         if isinstance(t, dict) and t.get("line") == li), {})      # the line's mode on other shots
            new = {"line": li, "mode": ty.get("mode", same.get("mode", "subtitle")),
                   "text": ty.get("text") or same.get("text") or ctx.texts.get(li, ""),
                   "placement": ty.get("placement", same.get("placement", ""))}
            sh["type"].append(new)
            sh["type"].sort(key=lambda t: t.get("line", 0) if isinstance(t, dict) else 0)
            if li not in (sh.get("lines") or []):
                sh["lines"] = sorted(set(sh.get("lines") or []) | {li})
            changed.append(f"type[line {li}] added")
            if not any(w.get("line") == li for w in ctx.words_in(sh)):
                notes.append(f"{sid}: line {li} is not sung inside this shot — the engine shows a block only where "
                             "its line is sung")
        others = []
        for x in ctx.order:
            for t in ctx.by_id[x].get("type") or []:
                if not (isinstance(t, dict) and t.get("line") == li):
                    continue
                hit = False
                for f in ("mode", "placement", "text"):
                    if f in ty and t.get(f) != ty[f]:
                        t[f] = ty[f]
                        hit = True
                if hit:
                    if x == sid:
                        changed.append(f"type[line {li}]")
                    else:
                        others.append(x)
        if others:
            notes.append(f"line {li}'s type also changed on {', '.join(others)} (a line keeps one mode and position "
                         "across cuts)")
    return changed


def _link(ctx: Ctx, sid: str, tier: str | None, clip: str | None, notes: list[str]) -> list[str]:
    """Write a shot's tier and clip link (clip "" = unlink every clip), and keep the board's clip plan (seedance[])
    in step: the shot leaves the other plan entries; an entry left with no shot that was never made is dropped (it
    would still count in the motion budget and print a `clip new`); a planned clip linked here lists the shot.
    Returns the changed field names."""
    sh = ctx.by_id[sid]
    changed: list[str] = []
    if tier is not None and sh.get("motion_tier") != tier:
        sh["motion_tier"] = tier
        changed.append("motion_tier")
    if clip == "":
        old = shot_clips(sh)
        if old:
            sh["clip"] = None
            sh.pop("clips", None)
            sh.pop("seedance_clip", None)
            changed.append("clip")
            notes.append(f"{sid}: unlinked {', '.join(old)} (" + ("it plays its plate" if (tier or shot_tier(sh)) in
                                                                  ("still", "plate3d") else "no clip linked") + ")")
    elif clip:
        if sh.get("clip") != clip:
            sh["clip"] = clip
            changed.append("clip")
        if isinstance(sh.get("clips"), list) and sh["clips"][:1] != [clip]:
            sh["clips"] = [clip] + [x for x in sh["clips"] if x != clip]      # the primary clip comes first
            changed.append("clips")
    if clip is not None and _plan_sync(ctx, sid, clip or None, notes):
        changed.append("clip plan")
    return changed


def _plan_sync(ctx: Ctx, sid: str, keep: str | None, notes: list[str]) -> bool:
    """sid leaves every clip plan entry but `keep`'s (and joins keep's, when keep is planned). True when the plan
    changed."""
    from .draft import clip_cmd
    plan = ctx.S.get("seedance") or []
    hit = False
    drop = []
    for c in plan:
        eid = c.get("clip") or c.get("id")
        shots = c.get("shots") if isinstance(c.get("shots"), list) else []
        made = ctx.clip_doc(eid) is not None
        if eid == keep:
            if sid not in shots:
                c["shots"] = sorted(shots + [sid], key=lambda x: ctx.order.index(x) if x in ctx.order else 1 << 30)
                hit = True
            else:
                continue
        elif sid in shots:
            c["shots"] = [x for x in shots if x != sid]
            hit = True
            if not c["shots"]:
                if not made:
                    drop.append(c)
                    notes.append(f"{eid} dropped from the board's clip plan (never made, and no shot plays it now)"
                                 + (f"; to make it after all: `{c['cmd']}`, then link it with --clip {eid}"
                                    if isinstance(c.get("cmd"), str) and c["cmd"] else ""))
                else:
                    notes.append(f"{eid} (made) is on no shot now: it stays in clips/, unused (`board set SHOT --clip "
                                 f"{eid}` links it again)")
                continue
        else:
            continue
        if not made and c["shots"]:                    # a clip not made yet: its `clip new` follows its shots
            ts = [ctx.by_id[x] for x in c["shots"] if x in ctx.by_id]
            if ts:
                c["needed"] = [min(float(s["t0"]) for s in ts), max(float(s["t1"]) for s in ts)]
                c["cmd"] = clip_cmd(ctx.pdir, c)
    if drop:
        ctx.S["seedance"] = [c for c in plan if all(c is not d for d in drop)]
    return hit


def _neighbour_warnings(ctx: Ctx, sids: list[str]) -> list[str]:
    """Back-to-back treatment / transition repeats around the edited shots (the audit fails the first)."""
    from .common import engine_treatment, is_code
    out = []
    # the shots the audit's treatments gate compares (a 2.5D plate shot, or a still with a plate); clip shots and
    # motion/sung shots without a clip are transparent there
    plate_shots = [x for x in ctx.order if shot_tier(ctx.by_id[x], ctx.kinds) == "plate3d"
                   or (shot_tier(ctx.by_id[x], ctx.kinds) == "still" and shot_plate(ctx.by_id[x], ctx.S))]
    for sid in sids:
        sh = ctx.by_id[sid]
        if "treatment" in sh and sh.get("treatment") and sid in plate_shots and not is_code(sh):
            i = plate_shots.index(sid)
            for j in (i - 1, i + 1):
                if 0 <= j < len(plate_shots):
                    o = ctx.by_id[plate_shots[j]]
                    if not is_code(o) and o.get("treatment") and engine_treatment(o) == engine_treatment(sh):
                        out.append(f"{sid} and {o['id']} both draw '{engine_treatment(sh)}' back to back — the audit "
                                   f"fails it; pick another treatment for one of them")
        elif sid not in plate_shots:                   # a clip shot is transparent: the plates around it now meet
            k = ctx.order.index(sid)
            before = next((x for x in reversed(ctx.order[:k]) if x in plate_shots and not is_code(ctx.by_id[x])), None)
            after = next((x for x in ctx.order[k + 1:] if x in plate_shots and not is_code(ctx.by_id[x])), None)
            if before and after:
                b, a = ctx.by_id[before], ctx.by_id[after]
                if b.get("treatment") and a.get("treatment") and engine_treatment(b) == engine_treatment(a):
                    out.append(f"{before} and {after} now meet across clip shots and both draw '{engine_treatment(a)}' "
                               "— the audit fails it; pick another treatment for one of them")
        tr = sh.get("transition_in")
        k = ctx.order.index(sid)
        if tr and str(tr).lower() != "cut" and k:
            prev = ctx.by_id[ctx.order[k - 1]].get("transition_in")
            if prev and vocab.transition_parse(prev)[0] == vocab.transition_parse(tr)[0]:
                out.append(f"{sid}: transition '{tr}' repeats the previous shot's — the engine demotes it to a cut")
    return list(dict.fromkeys(out))


def todo_fields(sh: dict) -> list[str]:
    """The fields of one shot the lead still has to write: a TODO marker or a hint placeholder left in them, or no
    framing (code-drawn shots excepted)."""
    from .common import framing_of, is_code
    miss = [k for k in ("set", "framing", "action", "img_prompt", "mj_prompt", "camera")
            if isinstance(sh.get(k), str) and placeholder(sh[k])]
    if not is_code(sh) and not framing_of(sh) and "framing" not in miss:
        miss.append("framing")
    return miss


def todo_summary(ctx: Ctx) -> tuple[int, list[str], str]:
    """(shots with TODO fields, a few "s004: set, framing" items, the next command). The command's values are <…>
    markers the validators refuse: the operator replaces them, a pasted hint changes nothing."""
    left = []
    for x in ctx.order:
        miss = todo_fields(ctx.by_id[x])
        if miss:
            left.append(f"{x}: {', '.join(miss)}")
    if left:
        first, fields = left[0].split(": ", 1)
        nxt = set_hint(ctx.pdir, first, fields.split(", "))
    else:
        need = lines_without_graphic(ctx)
        if need:
            li, sid, w = need[0]
            nxt = graphic_hint(ctx.pdir, sid, li, w)
            left.append(f"{len(need)} lyric line(s) still need their explaining graphic (lines "
                        f"{', '.join(str(n[0]) for n in need[:8])}; pick the device that shows what the line means: "
                        "`slop board device kinds`)")
            return 0, left, nxt
        nxt = pcmd(ctx.pdir, "board audit")
    return len(left), left[:6], nxt


def _left_line(n_left: int, left: list[str], after: str = "") -> str:
    if n_left:
        return f"{n_left} shot(s) still have TODO fields{after} ({'; '.join(left[:3])})."
    return f"no TODO fields left{after}." + (f" {left[0]}." if left else "")


def lines_without_graphic(ctx: Ctx) -> list[tuple[int, str, str]]:
    """[(line, shot where its first word starts, that word)] for lyric lines no device explains yet (a quick version
    of the audit's graphics gate, for the next-step hint)."""
    from .common import is_code
    starts = [float(ctx.by_id[x]["t0"]) for x in ctx.order]
    tagged, untagged = set(), {}
    for x in ctx.order:
        for d in ctx.by_id[x].get("devices") or []:
            if isinstance(d, dict) and not devlib.is_graphic(d):
                continue
            if isinstance(d, dict) and isinstance(d.get("line"), int):
                tagged.add(d["line"])
            elif d:
                untagged[x] = untagged.get(x, 0) + 1
    first: dict[int, dict] = {}
    for w in ctx.W["words"]:
        if isinstance(w.get("line"), int) and (w["line"] not in first or w["t0"] < first[w["line"]]["t0"]):
            first[w["line"]] = w
    out = []
    for li, w in sorted(first.items(), key=lambda kv: kv[1]["t0"]):
        if li in tagged:
            continue
        sid = ctx.order[max(0, bisect.bisect_right(starts, w["t0"]) - 1)]
        if untagged.get(sid, 0) > 0:
            untagged[sid] -= 1
            continue
        if is_code(ctx.by_id[sid]):
            continue
        out.append((li, sid, re.sub(r"[^\w'-]", "", w.get("w", ""))))
    return out


# ------------------------------------------------------------------------------------------------ commands
def cmd_set(pdir: Path, shots: str, fields: dict, switch_generator: bool = False) -> dict:
    fields = {k: v for k, v in fields.items() if v is not None}
    if not fields:
        raise SlopError("nothing to set: give at least one field, e.g. `slop board set s004 --set \"a night market\" "
                        "--framing WS --action \"…\"` (`slop board set --help` lists them)")
    ctx = Ctx(pdir)
    sids = ctx.select(shots)
    if len(sids) > 1 and any(k in fields for k in ("img_prompt", "mj_prompt", "prompt")):
        raise SlopError("a plate prompt belongs to one shot (one image per shot): set prompts one shot at a time; "
                        "nothing was changed")
    errs, warns, notes, changed = [], [], [], {}
    cleans = {}
    for sid in sids:
        try:
            cleans[sid], w = normalise(ctx, ctx.by_id[sid], fields, switch=switch_generator)
            warns += [f"{sid}: {x}" for x in w]
        except ValueError as e:
            errs.append(f"{sid}: {e}")
    if errs:
        raise SlopError("nothing was changed:\n  - " + "\n  - ".join(errs))
    for sid in sids:
        try:
            c = apply(ctx, sid, cleans[sid], notes)
        except ValueError as e:
            raise SlopError(f"nothing was changed: {e}") from e
        if c:
            changed[sid] = c
    warns += _neighbour_warnings(ctx, sids)
    stale = None
    if changed:
        save_shots(pdir, ctx.S)
        stale = board_gate_stale(pdir)
    n_left, left, nxt = todo_summary(ctx)
    if changed:
        text = "\n".join(f"{sid}: changed {', '.join(c)}" for sid, c in changed.items())
    else:
        text = f"{', '.join(sids)}: no change (already set)"
    if stale:
        warns.insert(0, stale)
    if notes:
        text += "\n" + "\n".join(f"note: {n}" for n in notes)
    if warns:
        text += "\n" + "\n".join(f"warning: {w}" for w in warns)
    text += "\n" + _left_line(n_left, left) + f"\nnext: `{nxt}`"
    linked = {sid: ctx.by_id[sid].get("clip") for sid in changed if {"clip", "clips"} & set(changed[sid])}
    if any(linked.values()):
        text += ("\nthe edit plays the linked clip once it has a delivered take: `" + pcmd(pdir, "edit edl") + "` (then `"
                 + pcmd(pdir, "board audit") + "`)")
    return {"shots": sids, "changed": changed, "warnings": warns, "notes": notes, "todo_shots": n_left, "next": nxt,
            "gate_stale": bool(stale), "linked": linked, "text": text}


def _rows_from_file(path: Path) -> list[tuple[int, dict]]:
    """[(row number, {field: value})] from a TSV (header row) or JSONL / JSON list file."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise SlopError(f"cannot read {path}: {e}") from e
    body = [ln for ln in raw.splitlines()]
    first = next((ln.strip() for ln in body if ln.strip() and not ln.lstrip().startswith("#")), "")
    rows: list[tuple[int, dict]] = []
    if first.startswith("[") and path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise SlopError(f"{path} is not valid JSON ({e})") from e
        for i, r in enumerate(data, 1):
            if not isinstance(r, dict):
                raise SlopError(f"{path} item {i} is not an object {{\"id\": \"s004\", …}}")
            rows.append((i, r))
        return rows
    if first.startswith("{"):
        for n, ln in enumerate(body, 1):
            s = ln.strip()
            if not s or s.startswith("#"):
                continue
            try:
                r = json.loads(s)
            except ValueError as e:
                raise SlopError(f"{path} line {n} is not valid JSON ({e}) — one object per line, e.g. "
                                "{\"id\": \"s004\", \"set\": \"a night market\", \"framing\": \"WS\"}; nothing was changed")
            if not isinstance(r, dict):
                raise SlopError(f"{path} line {n} is not an object {{…}}; nothing was changed")
            rows.append((n, r))
        return rows
    lines = [(n, ln) for n, ln in enumerate(body, 1) if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        raise SlopError(f"{path} is empty")
    if "\t" not in lines[0][1]:
        raise SlopError(f"{path}: the first row must be a TAB-separated header (id<TAB>set<TAB>framing…) or the file "
                        "must be JSONL (one {\"id\": …} object per line); nothing was changed")
    header = [_unquote(h).strip() for h in lines[0][1].split("\t")]
    for n, ln in lines[1:]:
        cells = [_unquote(c) for c in ln.split("\t")]
        if len(cells) > len(header):
            rows.append((n, {"__error__": f"{len(cells)} cells but the header has {len(header)} — a TAB inside a "
                                          "value? (use JSONL for text with tabs)"}))
            continue
        rows.append((n, {h: c for h, c in zip(header, cells) if c.strip() != ""}))
    return rows


def _unquote(cell: str) -> str:
    """A cell a spreadsheet or csv.writer wrapped in double quotes ("a hall, quoted" -> a hall, quoted; "" inside ->
    "). A quote that is part of the text (5" screen) is kept."""
    s = cell.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"' and '"' not in s[1:-1].replace('""', ""):
        return s[1:-1].replace('""', '"')
    return cell


def _field_name(k: str) -> str:
    k2 = re.sub(r"[\s-]+", "_", str(k).strip().lower())
    return FILL_ALIASES.get(k2, k2)


def cmd_fill(pdir: Path, file: str, check: bool = False, switch_generator: bool = False) -> dict:
    from ..util import input_path, not_found
    path = input_path(pdir, file)                     # from the current folder, else inside the project
    if not path or not path.is_file():
        raise SlopError(not_found(pdir, file, "fill file") + " — write a TSV (header: id, set, framing, action, "
                        "img_prompt, …) or a JSONL file first")
    rows = _rows_from_file(path)
    if not rows:
        raise SlopError(f"{file} has no rows")
    ctx = Ctx(pdir)
    errs: list[str] = []
    warns: list[str] = []
    seen: dict[str, int] = {}
    plan: list[tuple[str, dict, list | None]] = []
    for n, r in rows:
        if "__error__" in r:
            errs.append(f"row {n}: {r['__error__']}")
            continue
        r = {_field_name(k): v for k, v in r.items()}
        sid = str(r.pop("id", "") or "").strip()
        where = f"row {n}" + (f" ({sid})" if sid else "")
        if not sid:
            errs.append(f"{where}: no id (the shot, e.g. s004)")
            continue
        if sid not in ctx.by_id:
            near = devlib.suggest(sid, ctx.by_id)
            errs.append(f"{where}: no shot {sid} in board/shots.json" + (f" (did you mean {near}?)" if near else ""))
            continue
        if sid in seen:
            errs.append(f"{where}: {sid} is already on row {seen[sid]} (one row per shot)")
            continue
        seen[sid] = n
        devs = r.pop("devices", None)
        unknown = [k for k in r if k not in FIELDS]
        if unknown:
            errs.append(f"{where}: unknown field(s) {', '.join(unknown)} — fields: id, {', '.join(FIELDS)}, devices "
                        "(JSONL)")
            continue
        try:
            clean, w = normalise(ctx, ctx.by_id[sid], r, switch=switch_generator)
            warns += [f"{sid}: {x}" for x in w]
        except ValueError as e:
            errs.append(f"{where}: {e}")
            continue
        if devs is not None:
            if isinstance(devs, str):
                try:
                    devs = json.loads(devs)
                except ValueError:
                    errs.append(f"{where}: devices must be a JSON list [{{\"kind\": …}}]")
                    continue
            if not isinstance(devs, list):
                errs.append(f"{where}: devices must be a list [{{\"kind\": …}}]")
                continue
            sh = ctx.by_id[sid]
            plate = shot_plate(sh, ctx.S)
            sw = ctx.sung(sh)
            for i, d in enumerate(devs):
                e, w = devlib.check_device(d, ctx.lines or None, ctx.boxes.get(plate) if plate else None, sw,
                                           board=True)
                errs += [f"{where}: devices[{i}] {m}" for m in e]
                warns += [f"{sid}: devices[{i}] {m}" for m in w]
        plan.append((sid, clean, devs))
    if errs:
        raise SlopError(f"{file}: {len(errs)} problem(s); nothing was changed (one bad row fails the whole fill):\n  - "
                        + "\n  - ".join(errs[:40]) + (f"\n  … {len(errs) - 40} more" if len(errs) > 40 else ""))
    notes: list[str] = []
    changed: dict[str, list] = {}
    for sid, clean, devs in plan:
        try:
            c = apply(ctx, sid, clean, notes)
        except ValueError as e:
            raise SlopError(f"{file}: nothing was changed: {e}") from e
        if devs is not None and ctx.by_id[sid].get("devices") != devs:
            ctx.by_id[sid]["devices"] = devs
            c.append("devices")
        if c:
            changed[sid] = c
    warns += _neighbour_warnings(ctx, [sid for sid, _, _ in plan])
    stale = None
    if changed and not check:
        save_shots(pdir, ctx.S)
        stale = board_gate_stale(pdir)
        if stale:
            warns.insert(0, stale)
    n_left, left, nxt = todo_summary(ctx)
    if check:                                      # the check passed: the next step is the same fill, for real
        nxt = pcmd(pdir, "board fill " + shlex.quote(str(file)) + (" --switch-generator" if switch_generator else ""))
    verb = "would change" if check else "changed"
    text = (f"{file}: {len(plan)} row(s) valid; {verb} {len(changed)} shot(s)"
            + (" (--check: nothing written)" if check else "") + ".")
    if notes:
        text += "\n" + "\n".join(f"note: {x}" for x in notes[:12])
    if warns:
        text += "\n" + "\n".join(f"warning: {x}" for x in warns[:20]) + (f"\n… {len(warns) - 20} more warnings"
                                                                          if len(warns) > 20 else "")
    text += "\n" + _left_line(n_left, left, " after this fill" if check else "") + f"\nnext: `{nxt}`"
    return {"rows": len(plan), "changed": changed, "check": check, "warnings": warns, "notes": notes,
            "todo_shots": n_left, "next": nxt, "gate_stale": bool(stale), "text": text}


# ------------------------------------------------------------------------------------------------ devices
def _dev_line(i: int, d) -> str:
    if not isinstance(d, dict):
        return f"  [{i}] {json.dumps(d)[:80]}"
    p = json.dumps(d.get("params") or {}, ensure_ascii=False)
    extra = "".join(f" {k}={json.dumps(d[k], ensure_ascii=False)}" for k in ("anchor", "at", "until") if k in d)
    return (f"  [{i}] {d.get('kind') or d.get('device')} key={d.get('key', '-')}"
            + (f" line={d['line']}" if "line" in d else "") + extra + f" params={p[:120]}")


def device_add(pdir: Path, shot: str, kind: str, line=None, anchor: str | None = None, key: str | None = None,
               params: list[str] | None = None, params_json: str | None = None, at: str | None = None,
               until: str | None = None, example: bool = False, priority: float | None = None,
               replace: int | None = None) -> dict:
    ctx = Ctx(pdir)
    sh = ctx.shot(shot)
    spec = devlib.spec_of(kind)
    if spec is None:
        near = devlib.suggest(kind, devlib.registry())
        raise SlopError(f"unknown device kind '{kind}'" + (f" (did you mean '{near}'?)" if near else "")
                        + " — `slop board device kinds` lists the engine's devices; nothing was changed")
    ex = (devlib.example_of(kind) or {}) if example else {}
    p: dict = dict(ex.get("params") or {})
    user: dict = {}
    if params_json:
        try:
            pj = json.loads(params_json)
        except ValueError as e:
            raise SlopError(f"--params is not valid JSON ({e}); nothing was changed") from e
        if not isinstance(pj, dict):
            raise SlopError("--params must be a JSON object {\"word\": \"walk\", …}; nothing was changed")
        user.update(pj)
    user.update(devlib.parse_params(params or []))
    p.update(user)
    notes: list[str] = []
    dev: dict = {"kind": kind}
    a = devlib.parse_anchor(anchor)
    if a is None and example:
        a = ex.get("anchor")
    if a is not None:
        dev["anchor"] = a
    li = None
    if line is not None:
        try:
            li = _line(line, ctx)
        except ValueError as e:
            raise SlopError(f"{e}; nothing was changed") from e
        if spec["role"] == "camera":
            raise SlopError(f"{kind} is a camera move: it draws nothing, so it is never line {li}'s explaining graphic "
                            "(the graphics gate does not count it). Drop --line: "
                            + pcmd(pdir, f"board device add {shot} --kind {kind}"
                                   + "".join(f" --param {shlex.quote(x)}" for x in params or []))
                            + "; give the line a drawing device instead (`slop board device kinds`); nothing was changed")
    word_param = spec.get("word_param", True)
    ex_key = str(ex.get("key") or "").strip().upper() or None
    k = (key or "").strip().upper() or None
    if k is None and "word" in user and word_param:
        k = "W"                                    # the operator named the word: it enters on it
    if k is None and ex_key:
        k = ex_key                                 # --example: the example's timing, unless --key says otherwise
    if "word" not in user and word_param and li is not None and spec["role"] != "camera" and k in (None, "W"):
        inside = sorted((w for w in ctx.words_in(sh) if w.get("line") == li), key=lambda w: w["t0"])
        line_words = sorted((w for w in ctx.W["words"] if w.get("line") == li), key=lambda w: w["t0"])
        if inside:
            starts_here = line_words and line_words[0]["t0"] >= float(sh["t0"]) - 1e-6
            p["word"] = [li, 0] if starts_here else inside[0].get("w", "")
            notes.append(f"no --param word: it enters on line {li}'s first word sung in {shot} "
                         f"(\"{inside[0].get('w', '')}\"); for the word that names it give "
                         "--param word=\"<the word>\"")
    if k is None and "word" in p and word_param:
        k = "W"
    if example and ex_key and ex_key != "W" and k == ex_key and li is not None:
        notes.append(f"timed like the example (key {ex_key}); to enter on the word that names line {li} add "
                     "--key W --param word=\"<the word>\"")
    if example:                                    # (example TEXT left unchanged is refused by check_device below)
        notes.append("--example copied the catalogue entry's params: check each value fits this shot (`slop board "
                     f"device kinds --kind {spec['kind']}` shows them)")
    if k:
        dev["key"] = k
    if li is not None:
        dev["line"] = li
    dev["params"] = p
    for f, v in (("at", at), ("until", until)):
        if v is not None:
            dev[f] = devlib.parse_value(v, what=f"--{f}")
    if priority is not None:
        dev["priority"] = priority
    plate = shot_plate(sh, ctx.S)
    errs, warns = devlib.check_device(dev, ctx.lines or None, ctx.boxes.get(plate) if plate else None,
                                      ctx.sung(sh), board=True)
    if errs:
        raise SlopError("nothing was changed:\n  - " + "\n  - ".join(errs) + "\n" + devlib.describe(kind))
    if li is not None and not any(w.get("line") == li for w in ctx.words_in(sh)):
        warns.append(f"line {li} has no word starting in {shot}; its graphic usually enters on the shot where the line "
                     "starts")
    devs = sh.get("devices")
    if not isinstance(devs, list):
        devs = sh["devices"] = []
    if replace is not None and not 0 <= replace < len(devs):
        raise SlopError(f"--replace {replace}: {shot} has {len(devs)} device(s) (`slop board device list {shot}`); "
                        "nothing was changed")
    if replace is not None and devs[replace] == dev or replace is None and any(d == dev for d in devs):
        text = f"{shot}: this {kind} is already there (no change)"
        changed = False
    elif replace is not None:
        old = devs[replace]
        devs[replace] = dev
        save_shots(pdir, ctx.S)
        text = (f"{shot}: replaced devices[{replace}] ({old.get('kind') if isinstance(old, dict) else old}) with {kind}"
                + (f" (the graphic for line {li})" if li is not None else ""))
        changed = True
    else:
        devs.append(dev)
        save_shots(pdir, ctx.S)
        text = f"{shot}: added {kind} as devices[{len(devs) - 1}]" + (f" (the graphic for line {li})" if li is not None
                                                                      else "")
        changed = True
    stale = board_gate_stale(pdir) if changed else None
    if stale:
        warns.insert(0, stale)
    if notes:
        text += "\n" + "\n".join(f"note: {n}" for n in notes)
    if warns:
        text += "\n" + "\n".join(f"warning: {w}" for w in warns)
    need = lines_without_graphic(ctx)
    if need:
        li2, sid2, w2 = need[0]
        nxt = graphic_hint(pdir, sid2, li2, w2)
        text += (f"\n{len(need)} lyric line(s) still need their explaining graphic (lines "
                 f"{', '.join(str(n[0]) for n in need[:8])}; pick the device that shows what the line means: "
                 f"`slop board device kinds`).\nnext: `{nxt}`")
    else:
        nxt = pcmd(pdir, "board audit")
        text += f"\nevery lyric line has its graphic.\nnext: `{nxt}`"
    # render reads engine/assets/shots.js, which only `edit export` rewrites: export first, or the still shows the
    # board as it was at the last export
    text += ("\nsee the device on the frame: `" + pcmd(pdir, "edit export --no-frames") + "` then `"
             + pcmd(pdir, "render stills --times " + format((float(sh["t0"]) + float(sh["t1"])) / 2, ".2f")) + "`")
    idx = replace if replace is not None else (len(devs) - 1 if changed else devs.index(dev))
    return {"shot": shot, "device": dev, "index": idx, "changed": changed, "warnings": warns, "notes": notes,
            "next": nxt, "gate_stale": bool(stale), "text": text}


def device_rm(pdir: Path, shot: str, index: int | None = None, kind: str | None = None, line=None,
              all_: bool = False) -> dict:
    if index is None and kind is None and line is None:
        raise SlopError("say which device to remove: --index I (from `slop board device list SHOT`), --kind K or "
                        "--line N; nothing was changed")
    ctx = Ctx(pdir)
    sh = ctx.shot(shot)
    devs = sh.get("devices") if isinstance(sh.get("devices"), list) else []
    if index is not None:
        if not 0 <= index < len(devs):
            raise SlopError(f"{shot} has {len(devs)} device(s) (indexes 0–{max(0, len(devs) - 1)}); nothing was changed")
        hit = [index]
    else:
        hit = [i for i, d in enumerate(devs) if isinstance(d, dict)
               and (kind is None or (d.get("kind") or d.get("device")) == kind
                    or (devlib.spec_of(kind) or {}).get("kind") == (devlib.spec_of(d.get("kind") or "") or {}).get("kind"))
               and (line is None or str(d.get("line")) == str(line))]
    if not hit:
        return {"shot": shot, "removed": [], "changed": False,
                "text": f"{shot}: no matching device (no change)\n" + "\n".join(_dev_line(i, d) for i, d in enumerate(devs))}
    if len(hit) > 1 and not all_:
        raise SlopError(f"{len(hit)} devices on {shot} match — add --all to remove them all, or --index I:\n"
                        + "\n".join(_dev_line(i, devs[i]) for i in hit) + "\nnothing was changed")
    removed = [devs[i] for i in hit]
    sh["devices"] = [d for i, d in enumerate(devs) if i not in set(hit)]
    save_shots(pdir, ctx.S)
    stale = board_gate_stale(pdir)
    return {"shot": shot, "removed": removed, "changed": True, "gate_stale": bool(stale),
            "warnings": [stale] if stale else [],
            "text": f"{shot}: removed {len(removed)} device(s): " + ", ".join(str(d.get('kind')) for d in removed)
                    + (f"\nwarning: {stale}" if stale else "") + f"\nnext: `{pcmd(pdir, 'board audit')}`"}


def device_list(pdir: Path, shot: str | None = None) -> dict:
    ctx = Ctx(pdir)
    sids = ctx.select(shot) if shot else ctx.order
    rows, out = [], {}
    for sid in sids:
        sh = ctx.by_id[sid]
        devs = sh.get("devices") if isinstance(sh.get("devices"), list) else []
        if not devs and not shot:
            continue
        plate = shot_plate(sh, ctx.S)
        sw = ctx.sung(sh)
        out[sid] = devs
        lines_typed = ",".join(str(t.get("line")) for t in sh.get("type") or [] if isinstance(t, dict))
        rows.append(f"{sid} {float(sh['t0']):7.2f}–{float(sh['t1']):6.2f}  lines [{lines_typed}]  {len(devs)} device(s)")
        for i, d in enumerate(devs):
            rows.append(_dev_line(i, d))
            e, w = devlib.check_device(d, ctx.lines or None, ctx.boxes.get(plate) if plate else None, sw, board=True)
            rows += [f"      ERROR {m}" for m in e] + [f"      warning {m}" for m in w]
    if not rows:
        need = lines_without_graphic(ctx)
        rows = ["no devices on the board yet — next: `" + (graphic_hint(pdir, need[0][1], need[0][0], need[0][2])
                                                             if need else pcmd(pdir, "board audit")) + "`"]
    return {"devices": out, "text": "\n".join(rows)}


def device_kinds(kind: str | None = None) -> dict:
    if kind:
        s = devlib.spec_of(kind)
        if not s:
            raise SlopError(f"unknown device kind '{kind}' — `slop board device kinds` lists them")
        return {"kind": s["kind"], "role": s["role"], "aliases": s["aliases"], "defaults": s["defaults"],
                "example": devlib.example_of(kind), "text": devlib.describe(kind)}
    reg = devlib.registry()
    rows = ["KIND            ROLE    WHAT IT EXPLAINS"]
    out = []
    for k in devlib.kinds():
        s = reg[k]
        doc = re.split(r"(?<=[a-z)])[.:] ", (s["doc"] or "") + " ")[0].strip()[:90]
        rows.append(f"{k:<15} {s['role']:<7} {doc}")
        out.append({"kind": k, "role": s["role"], "aliases": s["aliases"], "params": sorted(s["defaults"])})
    rows.append("one kind in full (params, defaults, an example): `slop board device kinds --kind K`; the catalogue: "
                "engine/DEVICES.md §8")
    return {"kinds": out, "text": "\n".join(rows)}
