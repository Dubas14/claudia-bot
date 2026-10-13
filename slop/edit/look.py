"""slop edit look — the project's colour look: a Lab grade toward a hero plate with the accent kept, baked into plates
and, through one 3D LUT per clip, into clip frames (port of look.py, CLODYSSEY 2026-09-30).

The owner's brief that shaped it: an Odyssey-like grade, "blue-greens-grays (dont over do it)", "we want the orange to
pop", gold "shifted … a bit muted", and then "keep it clean so it feels like imax, high res rather than dithered".

Algorithm (constants kept; set in project.json "look", sRGB <-> CIE Lab D65 in numpy):
  1. grade   Lab a/b mean and spread move toward the hero plate by `strength` (0.65):
             out = (1-k)·x + k·((x − μ_t)·σ_r/σ_t + μ_r); lightness keeps its own shape and borrows contrast
             1 + `contrast`·(σ_rL/σ_tL − 1) (0.25)
  2. accent  saturated oranges (hue band `accent_hue` 22–72°, soft edges `accent_soft` 14°, chroma ramp `accent_chroma`
             30–52) keep their own colour, pulled `accent_pull` 30 % toward the accent (project look.accent, default
             #D97757) and boosted ×`accent_boost` 1.12; lightness half its own. Gold sits at the band edge (muted, not
             lost); skin is below the chroma ramp (follows the grade). The hero plate grades to itself (identity outside
             the accent band).
  3. screen  optional semi-halftone (cell 0.0034·W, 45°, ink #0e1719, accent clear .75, highlights clean above L
             .46–.76) at `halftone.opacity` — preview only (`slop edit look sheet` in the print look); never baked into
             media (dots would swim under 2.5D parallax; the engine's print pass draws the screen).
  LUT       clip statistics = Lab mean/std over 16 frames sampled evenly (640 px wide) -> the grade with those fixed
            statistics baked into one 52³ .cube (52 puts the lattice on whole 8-bit steps of 5; red fastest; float
            interpolation between 8-bit grades); ffmpeg lut3d (tetrahedral) applies it, the same transform on every frame
            (no flicker; EV measured 0.49 levels mean difference vs the per-frame grade).

Modes (project.json look.mode):
  native       nothing is baked: plates and clip frames keep the generator's colour (CLODYSSEY lesson).
  clean-grade  the grade above, baked into plates (export) and clip frames (LUT per clip); no screen. Needs
               look.hero_plate (a plate key with a pick, or an image path).
  print        EV's print look: the media keep their colour ("never desaturate the base"); the grade is baked only when a
               hero plate is set; the engine's post pass prints the halftone/line/grain screen.

  slop edit look [show]                                show the look and check it can be applied
  slop edit look set [--mode M] [--hero PLATE] [--strength X] [--contrast X] [--accent HEX]
                     [--font-lyric F] [--font-micro F] [--font-display F]   (look.fonts: a family from engine/fonts/
                     fonts.js or project.json font_files, by family or file name; '' restores the engine default; a
                     font_files face must exist — "project": true is relative to the project, else engine/fonts — and
                     show its SIL OFL licence: in the font's name table or an OFL.txt beside it)
  slop edit look sheet [PLATE ...] [--out FILE]        before | after pairs -> board/look-sheet.jpg
  slop edit look grade IMG... --out DIR [--width W]    graded copies (JPEG q90)
  slop edit look lut VIDEO --out FILE.cube [--size 52] [--samples 16]

Changes from the source: the reference is the project's hero plate (look.hero_plate) instead of a fixed plate name;
the halftone defaults to off outside the print look; ffprobe/ffmpeg paths are escaped for lut3d. `look set` validates
before it saves (strength and contrast in 0..1, the hero a picked plate or an existing image, the accent a hex colour)
and a saved setting that cannot be applied yet (clean-grade without a hero) is ok:true with a "warning", never exit 1;
`look show` is ok:true with the same warning.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..config import SlopError, load_project, save_project
from ..board.common import read_json, rel, resolve_file

DEF = {"strength": 0.65, "contrast": 0.25, "accent": "#D97757", "accent_hue": [22, 72], "accent_soft": 14,
       "accent_chroma": [30, 52], "accent_boost": 1.12, "accent_pull": 0.3,
       "halftone": {"cell": 0.0034, "angle": 45, "opacity": 0.28, "ink": "#0e1719", "accent_clear": 0.75,
                    "clean_above": [0.46, 0.76]}}
MODES = ("native", "clean-grade", "print")
LUT_SIZE, LUT_SAMPLES = 52, 16


def conf(proj: dict) -> dict:
    look = proj.get("look") or {}
    c = {**DEF, **{k: v for k, v in look.items() if k in DEF and k != "halftone"}}
    ht = {**DEF["halftone"], **(look.get("halftone") or {})}
    if look.get("mode", "native") != "print" and "opacity" not in (look.get("halftone") or {}):
        ht["opacity"] = 0.0
    if look.get("mode") == "clean-grade":
        ht["opacity"] = 0.0
    c["halftone"] = ht
    c["mode"] = look.get("mode", "native")
    return c


# ---------------------------------------------------------------- sRGB <-> CIE Lab (D65)
def _np():
    import numpy as np
    return np


_M = [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
_WP = [0.95047, 1.0, 1.08883]


def to_lab(rgb8):
    np = _np()
    M, WP = np.array(_M), np.array(_WP)
    c = rgb8.astype(np.float32) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = c @ M.T / WP
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def to_rgb8(lab):
    np = _np()
    MI, WP = np.linalg.inv(np.array(_M)), np.array(_WP)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * WP
    c = np.clip(xyz @ MI.T, 0, 1)
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)
    return (np.clip(c, 0, 1) * 255 + 0.5).astype(np.uint8)


def hexlab(h: str):
    np = _np()
    h = h.strip()
    if not (len(h) == 7 and h.startswith("#")):
        raise SlopError(f"accent colour '{h}' must be a hex colour like #D97757")
    return to_lab(np.array([[[int(h[i:i + 2], 16) for i in (1, 3, 5)]]], np.uint8))[0, 0]


def stats(lab):
    x = lab.reshape(-1, 3)
    return x.mean(0), x.std(0) + 1e-6


def ref_stats_file(path: Path):
    """Lab (mean, std) of the hero plate (thumbnailed to 900 px, as the source did)."""
    np = _np()
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((900, 900))
    return stats(to_lab(np.asarray(im)))


def smooth(x, a, b):
    np = _np()
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def accent_weight(lab, c):
    np = _np()
    h = np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360
    C = np.hypot(lab[..., 1], lab[..., 2])
    lo, hi = c["accent_hue"]
    s = c["accent_soft"]
    band = smooth(h, lo - s, lo) * (1 - smooth(h, hi, hi + s))
    return band * smooth(C, *c["accent_chroma"]), h, C


def grade(rgb8, c: dict, ref, st=None):
    """ref: the hero plate's (mean, std); st: the statistics to grade from (default the image's own — plates; clips
    pass clip-level statistics so every frame gets the same transform and it bakes into a LUT)."""
    np = _np()
    lab = to_lab(rgb8)
    (mr, sr), (mt, stt) = ref, (st or stats(lab))
    out = lab.copy()
    k = c["strength"]
    for i in (1, 2):
        out[..., i] = (1 - k) * lab[..., i] + k * ((lab[..., i] - mt[i]) * (sr[i] / stt[i]) + mr[i])
    cs = 1 + c["contrast"] * (sr[0] / stt[0] - 1)
    out[..., 0] = np.clip(mt[0] + (lab[..., 0] - mt[0]) * cs, 0, 100)
    w, h, C = accent_weight(lab, c)
    if not c.get("accent"):                     # look.accent null/'' (`taste apply --accent none`): no accent kept
        return to_rgb8(out), np.zeros_like(w)
    acc = hexlab(c["accent"])
    ha = np.degrees(np.arctan2(acc[2], acc[1])) % 360
    dh = ((ha - h + 180) % 360) - 180
    h2 = np.radians(h + c["accent_pull"] * dh)
    C2 = C * c["accent_boost"]
    keep = np.stack([C2 * np.cos(h2), C2 * np.sin(h2)], -1)
    out[..., 1:] = out[..., 1:] * (1 - w[..., None]) + keep * w[..., None]
    out[..., 0] = out[..., 0] * (1 - 0.5 * w) + lab[..., 0] * 0.5 * w
    return to_rgb8(out), w


def screen(rgb8, w, c: dict):
    """Semi halftone: round ink dots on a rotated grid, sized by darkness, multiplied in at `opacity`."""
    np = _np()
    ht = c["halftone"]
    H, W = rgb8.shape[:2]
    cell = max(2.0, ht["cell"] * W)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    a = np.radians(ht["angle"])
    u = (x * np.cos(a) + y * np.sin(a)) / cell
    v = (-x * np.sin(a) + y * np.cos(a)) / cell
    d = np.hypot(u - np.round(u), v - np.round(v))
    L = to_lab(rgb8)[..., 0] / 100.0
    r = np.sqrt(np.clip(1 - L, 0, 1)) * 0.58
    aa = 0.9 / cell
    ink = 1 - smooth(d, r - aa, r + aa)
    o = ht["opacity"] * (1 - ht["accent_clear"] * w) * (1 - smooth(L, *ht["clean_above"]))
    inkc = np.array([int(ht["ink"][i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    f = rgb8.astype(np.float32)
    out = f * (1 - (o * ink)[..., None]) + inkc * (o * ink)[..., None]
    lift = 1 + 0.5 * o * (1 - L)
    return np.clip(out * lift[..., None], 0, 255).astype(np.uint8)


def look_image(im, c: dict, ref, with_screen: bool = False):
    """PIL image -> graded PIL image (+ the screen when asked and opacity > 0)."""
    np = _np()
    from PIL import Image
    rgb = np.asarray(im.convert("RGB"))
    g, w = grade(rgb, c, ref)
    if with_screen and c["halftone"].get("opacity", 0) > 0:
        g = screen(g, w, c)
    return Image.fromarray(g)


# ---------------------------------------------------------------- clips -> LUT
def _need_ffmpeg() -> None:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise SlopError("ffmpeg/ffprobe not found on PATH — run bin/setup.sh (or install ffmpeg)")


def probe_duration(src: Path) -> float:
    _need_ffmpeg()
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        raise SlopError(f"cannot read the duration of {src} (not a video, or a broken file)")


def clip_stats(src: Path, n: int = LUT_SAMPLES, width: int = 640):
    """Lab (mean, std) over n frames sampled evenly through a video (the clip-level statistics for its LUT)."""
    np = _np()
    dur = probe_duration(src)
    labs = []
    for k in range(n):
        t = dur * (k + .5) / n
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1", "-vf",
                              f"scale={width}:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if not raw:
            continue
        h = len(raw) // (width * 3)
        labs.append(to_lab(np.frombuffer(raw[:h * width * 3], np.uint8).reshape(h, width, 3)).reshape(-1, 3))
    if not labs:
        raise SlopError(f"could not decode frames from {src}")
    x = np.concatenate(labs)
    return x.mean(0), x.std(0) + 1e-6


def _grade_float(rgbf, c, ref, st):
    """grade() on float RGB 0..255 (the lattice is not all on 8-bit values), returning float RGB 0..1."""
    np = _np()
    q = np.clip(rgbf, 0, 255)
    lo = np.floor(q).astype(np.uint8)
    hi = np.minimum(lo.astype(np.int32) + 1, 255).astype(np.uint8)
    fr = q - lo
    a, _ = grade(lo, c, ref, st)
    b, _ = grade(hi, c, ref, st)
    return (a.astype(np.float32) * (1 - fr) + b.astype(np.float32) * fr) / 255


def cube(st, path: Path, c: dict, ref, n: int = LUT_SIZE, title: str = "look") -> Path:
    """The grade for fixed statistics as an n³ 3D LUT (.cube, red fastest) — ffmpeg lut3d applies it."""
    np = _np()
    g = np.linspace(0, 255, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r, gg, b], -1).reshape(1, -1, 3)
    out = _grade_float(rgb.astype(np.float32), c, ref, st).reshape(-1, 3)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="ascii") as f:
        f.write(f'TITLE "{title}"\nLUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        np.savetxt(f, out, fmt="%.6f")
    return path


def ff_path(p: Path) -> str:
    """A path quoted for an ffmpeg filter argument (lut3d=file=...)."""
    s = Path(p).resolve().as_posix().replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"'{s}'"


# ---------------------------------------------------------------- project glue
def hero_file(pdir: Path, proj: dict, picks: dict | None = None) -> Path | None:
    hero = (proj.get("look") or {}).get("hero_plate")
    if not hero:
        return None
    picks = picks if picks is not None else (read_json(Path(pdir) / "plates/picks.json", default={}) or {})
    if hero in picks:
        f = resolve_file(pdir, picks[hero].get("file"))
        return f if f and f.is_file() else None
    f = resolve_file(pdir, hero)
    return f if f and f.is_file() else None


def bake_plan(pdir: Path, proj: dict) -> dict:
    """What export bakes: {"grade": bool, "conf", "ref" (stats), "hero", "why"}."""
    c = conf(proj)
    mode = c["mode"]
    if mode not in MODES:
        raise SlopError(f"project.json look.mode '{mode}' is not one of {', '.join(MODES)} (`slop edit look set --mode ...`)")
    hero = hero_file(pdir, proj)
    if mode == "native":
        return {"grade": False, "conf": c, "ref": None, "hero": None, "why": "native: media keep their own colour"}
    if mode == "clean-grade" and not hero:
        raise SlopError("look.mode is clean-grade but no hero plate is set (or it has no picked image): "
                        "`slop edit look set --hero PLATE` — the plate whose colour the whole film should match")
    if mode == "print" and not hero:
        return {"grade": False, "conf": c, "ref": None, "hero": None,
                "why": "print: media keep their colour; the engine prints the screen (set a hero plate to also grade)"}
    return {"grade": True, "conf": c, "ref": ref_stats_file(hero), "hero": str(hero),
            "why": f"{mode}: graded toward {rel(pdir, hero)} at strength {c['strength']}"}


def signature(plan: dict) -> str:
    if not plan.get("grade"):
        return "none"
    c = plan["conf"]
    keys = {k: c[k] for k in ("strength", "contrast", "accent", "accent_hue", "accent_soft", "accent_chroma",
                              "accent_boost", "accent_pull")}
    return json.dumps({"hero": plan["hero"], **keys}, sort_keys=True)


# ---------------------------------------------------------------- commands
def cmd_show(pdir: Path) -> dict:
    """The look settings and whether export can apply them. A setting that cannot be applied yet (e.g. clean-grade
    without a hero plate) is reported as a "warning" with ok:true: showing it is not a failure."""
    proj = load_project(pdir)
    c = conf(proj)
    try:
        plan = bake_plan(pdir, proj)
        ready, why = True, plan["why"]
    except SlopError as e:
        ready, why = False, str(e)
    look = proj.get("look") or {}
    fonts = look.get("fonts") if isinstance(look.get("fonts"), dict) else {}
    ftxt = " · ".join(f"{r} {fonts.get(r) or '(engine default)'}" for r in FONT_ROLES)
    text = (f"look.mode {c['mode']} · hero_plate {look.get('hero_plate') or '—'} · strength {c['strength']} · contrast "
            f"{c['contrast']} · accent {c['accent']}\nfonts: {ftxt}\n" + (why if ready else f"warning: not applicable yet — {why}"))
    return {"ok": True, "ready": ready, "mode": c["mode"], "hero_plate": look.get("hero_plate"), "conf": c,
            "fonts": fonts, "status": why, "text": text, **({} if ready else {"warning": why})}


def _check_unit(name: str, v: float | None) -> float | None:
    if v is None:
        return None
    v = float(v)
    if not 0.0 <= v <= 1.0:
        raise SlopError(f"--{name} {v:g}: must be between 0 and 1 (default {DEF[name]}); nothing was changed")
    return v


FONT_ROLES = ("lyric", "micro", "display")


def font_choices(proj: dict) -> dict[str, str]:
    """lower-cased family / file name -> family, over engine/fonts/fonts.js (OFL faces) + project.json font_files."""
    from ..board.vocab import font_families
    return font_families(proj.get("font_files") if isinstance(proj.get("font_files"), list) else None)


OFL_MARKS = ("Open Font License", "scripts.sil.org/OFL", "openfontlicense.org")


def _has_ofl(font: Path) -> bool:
    """Cheap OFL evidence for a project font: the licence named in the font's own name table (ASCII or UTF-16BE, where
    every Google/OFL face states it), or an OFL / licence text next to the file (or in a licenses/ folder beside it)."""
    try:
        data = font.read_bytes()
    except OSError:
        return False
    for m in OFL_MARKS:
        if m.encode("ascii") in data or m.encode("utf-16-be") in data:
            return True
    for d in (font.parent, font.parent / "licenses", font.parent / "licences"):
        for f in sorted(d.glob("*")) if d.is_dir() else []:
            if f.is_file() and f.suffix.lower() in ("", ".txt", ".md") and re.search(r"ofl|licen[cs]e", f.name, re.I) \
                    and f.stat().st_size < 200_000:
                try:
                    if "Open Font License" in f.read_text(encoding="utf-8", errors="replace"):
                        return True
                except OSError:
                    continue
    return False


def _project_face_problem(pdir: Path, face: dict) -> str | None:
    """Why a project.json font_files face cannot be used (missing file, no OFL licence), else None."""
    f = str(face.get("file") or "")
    if not f:
        return "has no \"file\""
    if re.match(r"^(https?|data):", f):
        return None                               # fetched by the page itself: not checkable offline
    if f.startswith("file:"):
        from urllib.parse import unquote, urlsplit
        path = Path(unquote(urlsplit(f).path.lstrip("/") if re.match(r"^file:///[A-Za-z]:", f) else urlsplit(f).path))
    elif face.get("project"):
        path = Path(pdir) / f                      # the engine loads it relative to the project (E.url)
    else:
        from ..config import engine_dir
        path = engine_dir() / "fonts" / f          # without "project": true the engine looks in engine/fonts
    if not path.is_file():
        return (f"lists {f}, which does not exist ({path}) — put the font file there"
                + ("" if face.get("project") or f.startswith("file:") else
                   " (or mark the entry \"project\": true for a file inside the project)") + ", or fix the path")
    if not _has_ofl(path):
        return (f"{f} shows no SIL Open Font License (not in the font's name table, no OFL.txt beside it) — only OFL "
                "fonts may be used: put the font's OFL.txt next to it, or choose an engine font")
    return None


def check_font(proj: dict, role: str, name: str | None, pdir: Path | None = None) -> str | None:
    """A family the engine can load for look.fonts.<role> ('' clears the override -> None); SlopError otherwise.
    With pdir, a family that only project.json font_files provides must have its file (and an OFL licence)."""
    if name is None:
        return None
    n = name.strip().strip("\"'")
    if not n:
        return ""
    fams = font_choices(proj)
    fam = fams.get(n.lower())
    if not fam:
        names = sorted(set(fams.values()))
        raise SlopError(f"--font-{role} '{name}' is not a font the engine has (engine/fonts, SIL OFL only): "
                        f"{', '.join(names)} — or add your own OFL face to project.json font_files; nothing was changed")
    if pdir is not None:
        from ..board.vocab import engine_fonts
        engine_fams = {str(f.get("family")) for f in engine_fonts().get("faces") or [] if isinstance(f, dict)}
        faces = [f for f in (proj.get("font_files") if isinstance(proj.get("font_files"), list) else [])
                 if isinstance(f, dict) and str(f.get("family") or "") == fam]
        if faces and fam not in engine_fams:
            probs = [p for p in (_project_face_problem(pdir, f) for f in faces) if p]
            if len(probs) == len(faces):           # no usable file for this family
                raise SlopError(f"--font-{role} '{name}': project.json font_files {probs[0]}; nothing was changed")
    return fam


def cmd_set(pdir: Path, mode: str | None = None, hero: str | None = None, strength: float | None = None,
            contrast: float | None = None, accent: str | None = None, font_lyric: str | None = None,
            font_micro: str | None = None, font_display: str | None = None) -> dict:
    """Validate every value first, then save project.json once. Nothing is saved when a value is invalid."""
    proj = load_project(pdir)
    look = dict(proj.get("look") or {})
    if mode and mode not in MODES:
        raise SlopError(f"--mode {mode}: one of {', '.join(MODES)}; nothing was changed")
    fonts = {r: check_font(proj, r, v, pdir) for r, v in zip(FONT_ROLES, (font_lyric, font_micro, font_display))}
    strength = _check_unit("strength", strength)
    contrast = _check_unit("contrast", contrast)
    if accent:
        hexlab(accent)
    if hero:
        picks = read_json(Path(pdir) / "plates/picks.json", default={}) or {}
        f = resolve_file(pdir, (picks.get(hero) or {}).get("file")) if hero in picks else resolve_file(pdir, hero)
        if not (f and f.is_file()):
            picked = sorted(k for k in picks if "~" not in k)
            raise SlopError(f"--hero {hero}: not a picked plate (or an existing image file) — "
                            + (f"picked plates: {', '.join(picked[:12])}" if picked else
                               "no plate is picked yet (`slop plates pick PLATE K` first)") + "; nothing was changed")
    if mode:
        look["mode"] = mode
    if hero is not None:
        look["hero_plate"] = hero or None
    if strength is not None:
        look["strength"] = strength
    if contrast is not None:
        look["contrast"] = contrast
    if accent:
        look["accent"] = accent
    if any(v is not None for v in fonts.values()):
        fl = dict(look.get("fonts") or {})
        for r, v in fonts.items():
            if v is None:
                continue
            if v:
                fl[r] = v
            else:
                fl.pop(r, None)                 # '' clears the override: the engine's default role font
        look["fonts"] = fl
    proj["look"] = look
    save_project(pdir, proj)
    out = cmd_show(pdir)
    out["saved"] = True
    out["text"] = "project.json look updated (saved).\n" + out["text"] + \
        ("\nnext: `slop edit look sheet` to see it on the plates." if out["ready"] else
         "\nnext: set a hero plate (`slop edit look set --hero PLATE`) before `slop edit export`.")
    return out


def cmd_grade(pdir: Path | None, files: list[str], out: str, width: int | None = None) -> dict:
    from PIL import Image
    if pdir is None:
        raise SlopError("grade needs a project (the hero plate and look settings come from project.json)")
    proj = load_project(pdir)
    plan = bake_plan(pdir, proj)
    if not plan["grade"]:
        raise SlopError(f"nothing to grade: {plan['why']}")
    od = Path(out)
    od.mkdir(parents=True, exist_ok=True)
    done = []
    for f in files:
        im = Image.open(f).convert("RGB")
        if width and im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        o = od / (Path(f).stem + ".jpg")
        look_image(im, plan["conf"], plan["ref"]).save(o, quality=90)
        done.append(str(o))
    return {"files": done, "text": f"graded {len(done)} image(s) into {od}"}


def cmd_lut(pdir: Path, video: str, out: str, size: int = LUT_SIZE, samples: int = LUT_SAMPLES) -> dict:
    proj = load_project(pdir)
    plan = bake_plan(pdir, proj)
    if not plan["grade"]:
        raise SlopError(f"no grade to bake: {plan['why']}")
    st = clip_stats(Path(video), samples)
    cube(st, Path(out), plan["conf"], plan["ref"], size, title=Path(video).stem)
    return {"lut": out, "mean": [round(float(x), 2) for x in st[0]], "std": [round(float(x), 2) for x in st[1]],
            "text": f"wrote {out} ({size}³ LUT from {samples} frames of {Path(video).name}); apply with ffmpeg "
                    f"-vf lut3d=file={out}:interp=tetrahedral"}


def cmd_sheet(pdir: Path, plates: list[str] | None = None, out: str | None = None) -> dict:
    from PIL import Image, ImageDraw
    from ..board.common import font
    proj = load_project(pdir)
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    c = conf(proj)
    plan = bake_plan(pdir, proj)
    if not plan["grade"] and c["halftone"].get("opacity", 0) <= 0:
        raise SlopError(f"nothing to preview: {plan['why']}. Set a hero plate (`slop edit look set --hero PLATE`).")
    keys = plates or ([proj["look"]["hero_plate"]] if (proj.get("look") or {}).get("hero_plate") in picks else []) + \
        [k for k in sorted(picks) if "~" not in k and k != (proj.get("look") or {}).get("hero_plate")][:7]
    rows = []
    w = 900
    for p in keys:
        f = resolve_file(pdir, (picks.get(p) or {}).get("file")) or resolve_file(pdir, p)
        if not (f and f.is_file()):
            raise SlopError(f"plate {p} has no picked image (`slop plates pick {p} K`)")
        im = Image.open(f).convert("RGB")
        big = im.resize((2048, round(im.height * 2048 / im.width)), Image.LANCZOS)
        if plan["grade"]:
            graded = look_image(big, plan["conf"], plan["ref"], with_screen=c["mode"] == "print")
        else:
            np = _np()
            graded = Image.fromarray(screen(np.asarray(big), np.zeros(big.size[::-1], np.float32), c))
        full = graded.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        rows.append((p, im.resize(full.size, Image.LANCZOS), full))
    if not rows:
        raise SlopError("no picked plates to preview yet (`slop plates pick ...`)")
    h = max(r[1].height for r in rows)
    S = Image.new("RGB", (2 * w + 30, len(rows) * (h + 34)), "white")
    d = ImageDraw.Draw(S)
    F = font(20, True)
    for k, (p, b, g) in enumerate(rows):
        y = k * (h + 34)
        d.text((4, y + 6), f"{p} · as generated", fill="black", font=F)
        d.text((w + 34, y + 6), f"{p} · the look ({c['mode']})", fill="black", font=F)
        S.paste(b, (0, y + 30))
        S.paste(g, (w + 30, y + 30))
    o = Path(out) if out else pdir / "board/look-sheet.jpg"
    o.parent.mkdir(parents=True, exist_ok=True)
    S.save(o, quality=88)
    return {"sheet": str(o), "plates": [r[0] for r in rows],
            "text": f"wrote {o}: as generated | the look, for {len(rows)} plate(s). Show it to the owner before export."}
