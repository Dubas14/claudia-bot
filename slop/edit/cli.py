"""CLI for the edit: `slop edit edl|export|look ...` (router contract: register(subparsers))."""
from __future__ import annotations

from ..board.cli import _help, leaf
from ..config import resolve_project


def cmd_edl(a) -> dict:
    from . import edl
    return edl.build(resolve_project(a.project), a.shots)


def cmd_export(a) -> dict:
    from . import export
    return export.run(resolve_project(a.project), depth=a.depth, frames=not a.no_frames, force=a.force)


def cmd_look_show(a) -> dict:
    from . import look
    return look.cmd_show(resolve_project(a.project))


def cmd_look_set(a) -> dict:
    from . import look
    return look.cmd_set(resolve_project(a.project), mode=a.mode, hero=a.hero, strength=a.strength,
                        contrast=a.contrast, accent=a.accent, font_lyric=a.font_lyric, font_micro=a.font_micro,
                        font_display=a.font_display)


def cmd_look_sheet(a) -> dict:
    from . import look
    return look.cmd_sheet(resolve_project(a.project), a.plates or None, a.out)


def cmd_look_grade(a) -> dict:
    from . import look
    return look.cmd_grade(resolve_project(a.project), a.files, a.out, a.width)


def cmd_look_lut(a) -> dict:
    from . import look
    return look.cmd_lut(resolve_project(a.project), a.video, a.out, a.size, a.samples)


def register(sub) -> None:
    e = sub.add_parser("edit", help="the edit: EDL, engine asset export, look/LUT grade",
                       description="The edit: `edl` (what every shot shows), `export` (engine/assets/*.js + frames + "
                                   "plates), `look` (the colour grade).")
    es = e.add_subparsers(dest="edit_cmd", metavar="ACTION")
    e.set_defaults(func=_help(e))
    p = leaf(es, "edl", "build edit/edl.json from the board, picks and synced clips (+ a per-shot report)")
    p.add_argument("--shots", help="use this shots.json instead of board/shots.json")
    p.set_defaults(func=cmd_edl)
    p = leaf(es, "export", "write engine/assets/{beats,lyrics,hits,shots,edl,plates,clips}.js, clip frames and plates")
    p.add_argument("--depth", choices=["auto", "on", "off"], default="auto",
                   help="plate depth maps with Depth-Anything-V2-Small on CPU (auto: when torch is installed)")
    p.add_argument("--no-frames", action="store_true", help="skip clip frame extraction (keeps the existing clips.js)")
    p.add_argument("--force", action="store_true", help="rebuild plates and frames even when unchanged")
    p.set_defaults(func=cmd_export)

    lk = leaf(es, "look", "the colour look (native | clean-grade | print): show, set, sheet, grade, lut")
    lk.set_defaults(func=cmd_look_show)
    ls = lk.add_subparsers(dest="look_cmd", metavar="LOOK_ACTION")
    p = leaf(ls, "show", "show the look settings and whether they can be applied")
    p.set_defaults(func=cmd_look_show)
    p = leaf(ls, "set", "change project.json look")
    p.add_argument("--mode", choices=["native", "clean-grade", "print"])
    p.add_argument("--hero", help="hero plate key (its picked image is the colour reference); '' clears it")
    p.add_argument("--strength", type=float, help="how far colours move toward the hero (default 0.65)")
    p.add_argument("--contrast", type=float, help="how much of the hero's contrast is borrowed (default 0.25)")
    p.add_argument("--accent", help="accent colour kept and boosted, hex (default #D97757)")
    p.add_argument("--font-lyric", dest="font_lyric", help="the lyric face (look.fonts.lyric): a family in engine/fonts "
                                                           "(e.g. \"Space Grotesk\", \"Instrument Serif\"); '' = default")
    p.add_argument("--font-micro", dest="font_micro", help="the micro-type face (look.fonts.micro), e.g. \"IBM Plex Mono\"")
    p.add_argument("--font-display", dest="font_display", help="the display face (look.fonts.display), e.g. "
                                                               "\"Barlow Condensed\"")
    p.set_defaults(func=cmd_look_set)
    p = leaf(ls, "sheet", "before | after pairs on picked plates -> board/look-sheet.jpg")
    p.add_argument("plates", nargs="*", help="plate keys (default: the hero + up to 7 picked plates)")
    p.add_argument("--out", help="output JPG")
    p.set_defaults(func=cmd_look_sheet)
    p = leaf(ls, "grade", "graded copies of images")
    p.add_argument("files", nargs="+")
    p.add_argument("--out", required=True, help="output folder")
    p.add_argument("--width", type=int, help="downscale wider images to this width first")
    p.set_defaults(func=cmd_look_grade)
    p = leaf(ls, "lut", "bake the grade for one video into a .cube LUT (16 sampled frames)")
    p.add_argument("video")
    p.add_argument("--out", required=True, help="output .cube file")
    p.add_argument("--size", type=int, default=52)
    p.add_argument("--samples", type=int, default=16)
    p.set_defaults(func=cmd_look_lut)
