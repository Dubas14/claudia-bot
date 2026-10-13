"""slop board sheet — the storyboard for owner approval: every shot as a card (plate thumbnail if picked, id + time,
framing, tier/clip, section/treatment/plate, the lyric, the action, a prompt excerpt, the explaining graphic), 12 cards
a page, a cover with the stats and the chapter map; JPG pages + one PDF (Pillow only).

Port of board.py (layout constants kept: 2480x2240 pages, 4x3 cards, margin 70, gutter 36, ink #111111 on paper
#F4F2EE, grey #8a8a86, accent #D97757 or the project accent; IBM Plex Mono, OFL). Changes: plates resolve through
plates/picks.json; thumbnails are shown with the project's grade when look.mode is clean-grade (owners review graded
frames); optional --flags {plate: note} badges "FACE? note" as before; the cover states the clip plan's $ estimate
(the board approval approves that spend plan; priced offline, see draft.plan_cost). Outputs board/board.pdf,
board/board-pNN.jpg and board/board.jpg (the cover).
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from ..config import load_project
from .common import (TODO, clip_kinds, font, line_texts, load_shots, load_words, mmss, read_json, resolve_file,
                     shot_clips, shot_plate, shot_tier, treatment_family)

INK, PAPER, GREY, ACC = "#111111", "#F4F2EE", "#8a8a86", "#D97757"
PW, PH, COLS, ROWS, M = 2480, 2240, 4, 3, 70            # 12 cards a page
CW = (PW - 2 * M - (COLS - 1) * 36) // COLS
TH = CW * 9 // 16
CH = TH + 330


def _wrap(d, xy, text, fnt, width_px, fill, max_lines, lh) -> int:
    cw = max(1.0, fnt.getlength("M"))
    n = max(8, int(width_px / cw))
    rows_all = textwrap.wrap(text or "", n)
    rows = rows_all[:max_lines]
    if len(rows_all) > max_lines and rows:
        rows[-1] = rows[-1][: n - 1] + "…"
    for i, r in enumerate(rows):
        d.text((xy[0], xy[1] + i * lh), r, font=fnt, fill=fill)
    return len(rows) * lh


class _Grader:
    """Applies the project grade to thumbnails when look.mode is clean-grade (best effort, never fails the sheet)."""

    def __init__(self, pdir: Path, proj: dict, picks: dict):
        self.fn = None
        look = proj.get("look") or {}
        if look.get("mode") != "clean-grade":
            return
        try:
            from ..edit import look as L
            ref = L.hero_file(pdir, proj, picks)
            if ref:
                c = L.conf(proj)
                rs = L.ref_stats_file(ref)
                self.fn = lambda im: L.look_image(im, c, rs)
        except Exception:   # noqa: BLE001 - a sheet without the grade is still useful
            self.fn = None

    def __call__(self, im):
        if self.fn is None:
            return im
        try:
            return self.fn(im)
        except Exception:   # noqa: BLE001
            return im


def _thumb(path: Path, grader):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    r = max(CW / im.width, TH / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    x0, y0 = (im.width - CW) // 2, (im.height - TH) // 2
    return grader(im.crop((x0, y0, x0 + CW, y0 + TH)))


def card(sh: dict, ctx: dict):
    from PIL import Image, ImageDraw
    acc = ctx["accent"]
    c = Image.new("RGB", (CW, CH), PAPER)
    d = ImageDraw.Draw(c)
    pid = shot_plate(sh, ctx["S"])
    pick = (ctx["picks"].get(pid) or {}) if pid else {}
    path = resolve_file(ctx["pdir"], pick.get("file"))
    tier = shot_tier(sh, ctx["kinds"])
    if path and path.is_file():
        try:
            c.paste(_thumb(path, ctx["grader"]), (0, 0))
        except OSError:
            path = None
    if not (path and path.is_file()):
        d.rectangle([0, 0, CW - 1, TH - 1], fill="#dcdad4")
        if sh.get("code") or treatment_family(sh) in ("pure-motion", "motion-design", "code"):
            label = "CODE · " + str(sh.get("action") or "")
        else:
            label = "PLATE PENDING · " + (pid or "no plate")
        _wrap(d, (18, 58), label, font(22), CW - 36, INK, 7, 30)
    d.rectangle([0, 0, 250, 40], fill=INK)
    d.text((10, 6), f"{sh['id']}  {mmss(sh['t0'])}", font=font(24, True), fill=PAPER)
    fr = str(sh.get("framing") or "").upper()
    fr = "?" if (not fr or TODO in fr) else fr[:5]
    d.rectangle([CW - 96, 0, CW, 40], fill=PAPER)
    d.text((CW - 88, 6), fr, font=font(24, True), fill=INK)
    if sh.get("lead_on_screen"):
        d.rectangle([CW - 150, 0, CW - 100, 40], fill=acc)
        d.text((CW - 142, 6), "L", font=font(24, True), fill=INK)
    if pid and pid in ctx["flags"]:
        d.rectangle([0, TH - 44, CW, TH], fill=acc)
        d.text((10, TH - 38), ("FACE? " + str(ctx["flags"][pid]))[:60], font=font(22, True), fill=INK)
    y = TH + 10
    dur = float(sh["t1"]) - float(sh["t0"])
    clips = shot_clips(sh)
    src = {"sung": "SUNG", "motion": "MOTION", "plate3d": "2.5D", "still": "STILL"}.get(tier, tier.upper())
    if clips and tier in ("sung", "motion"):
        src += f" {clips[0]}"
    d.text((0, y), f"{dur:4.1f}s · {src}"[:52], font=font(21, True), fill=INK)
    y += 30
    meta = " · ".join(x for x in (str(sh.get("section") or ""), treatment_family(sh) or "", f"plate {pid or '-'}") if x)
    d.text((0, y), meta[:56], font=font(19), fill=GREY)
    y += 28
    lyr = " / ".join(ctx["lines"].get(li, "") for li in (sh.get("lines") or []) if li in ctx["lines"])
    if lyr:
        y += _wrap(d, (0, y), "“" + lyr + "”", font(21, True), CW, INK, 2, 28) + 4
    y += _wrap(d, (0, y), str(sh.get("action") or ""), font(19), CW, INK, 3, 25) + 4
    dev = sh.get("devices") or []
    meme = sh.get("meme_visual") or (", ".join(str(x.get("kind") or x.get("device") or "") for x in dev
                                              if isinstance(x, dict)) if dev else "")
    if meme:
        y += _wrap(d, (0, y), "* " + str(meme), font(19), CW, acc, 2, 25)
    pr = sh.get("mj_prompt") or sh.get("img_prompt") or ""
    if pr and y < CH - 30:
        _wrap(d, (0, y), "prompt: " + str(pr), font(17), CW, GREY, max(1, (CH - y) // 23), 23)
    return c


def cover(ctx: dict, stats: str):
    from PIL import Image, ImageDraw
    pg = Image.new("RGB", (PW, PH), PAPER)
    d = ImageDraw.Draw(pg)
    d.text((M, M), f"{ctx['title'].upper()} — STORYBOARD", font=font(72, True), fill=INK)
    d.text((M, M + 100), stats, font=font(30), fill=INK)
    y = M + 190
    d.text((M, y), "CHAPTERS", font=font(30, True), fill=INK)
    y += 50
    for ch in ctx["S"].get("chapters", []):
        t0 = ch.get("t0", ch.get("start", 0))
        t1 = ch.get("t1", ch.get("end", 0))
        name = ch.get("name") or ch.get("chapter") or ch.get("id", "")
        extra = " · ".join(str(ch.get(k)) for k in ("sections", "grade", "accent", "set") if ch.get(k))
        d.text((M, y), f"{mmss(t0):>7} – {mmss(t1):>7}  {name}"[:70], font=font(28, True), fill=INK)
        _wrap(d, (M + 1150, y + 2), extra, font(24), PW - 2 * M - 1150, GREY, 2, 30)
        y += 70
        if y > PH - 200:
            break
    d.text((M, PH - M - 40), "card: frame = the picked plate the shot starts from · L = lead on screen · FACE? = check "
                             "her face · * = the explaining graphic · “…” = lyric on screen", font=font(24), fill=GREY)
    return pg


def build(pdir: Path, shots_file: str | None = None, flags_file: str | None = None) -> dict:
    from PIL import Image, ImageDraw
    proj = load_project(pdir)
    S = load_shots(pdir, shots_file)
    W = load_words(pdir)
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    flags = read_json(Path(flags_file), default={}) if flags_file else {}
    kinds = clip_kinds(pdir, S)
    shots = sorted(S["shots"], key=lambda s: float(s["t0"]))
    ctx = {"pdir": pdir, "S": S, "picks": picks, "flags": flags or {}, "kinds": kinds, "lines": line_texts(pdir, W),
           "accent": (proj.get("look") or {}).get("accent") or ACC, "title": proj.get("title") or proj.get("name") or pdir.name,
           "grader": _Grader(pdir, proj, picks)}
    tot = sum(float(s["t1"]) - float(s["t0"]) for s in shots) or 1.0
    lead = sum(float(s["t1"]) - float(s["t0"]) for s in shots if s.get("lead_on_screen"))
    clips = S.get("seedance", [])
    planned = sum(float(c.get("duration") or 0) for c in clips)
    n_picked = sum(1 for s in shots if (picks.get(shot_plate(s, S) or "") or {}).get("file"))
    from .draft import plan_cost
    cost = plan_cost(proj, [{"duration": c.get("duration") or 0, "kind": "sung" if (c.get("kind") == "sung" or (
        c.get("kind") is None and c.get("sing"))) else "motion"} for c in clips],
        float((proj.get("board") or {}).get("cover_allowance", 0.6)))
    est = (f" ≈ ${cost['est_usd']:.0f}–{cost['est_usd_with_covers']:.0f} ({cost['model']} {cost['resolution']}, "
           "with covers)") if clips and cost.get("est_usd") is not None else ""
    stats = (f"{len(shots)} shots · {tot:.1f} s · lead on screen {100 * lead / tot:.0f}% · {len(clips)} clips, "
             f"{planned:.0f} s planned{est} · {len(S.get('plates', []))} plates, {n_picked} shots with a picked frame")
    pages = [cover(ctx, stats)]
    per = COLS * ROWS
    for i in range(0, len(shots), per):
        pg = Image.new("RGB", (PW, PH), PAPER)
        d = ImageDraw.Draw(pg)
        grp = shots[i:i + per]
        d.text((M, 20), f"{ctx['title'].upper()} · {mmss(grp[0]['t0'])} – {mmss(grp[-1]['t1'])} · page {i // per + 1}",
               font=font(26, True), fill=GREY)
        for k, sh in enumerate(grp):
            x = M + (k % COLS) * (CW + 36)
            y = M + (k // COLS) * (CH + 40)
            pg.paste(card(sh, ctx), (x, y))
        pages.append(pg)
    out = pdir / "board"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("board-p*.jpg"):
        old.unlink()
    jpgs = []
    for j, pg in enumerate(pages):
        f = out / f"board-p{j:02d}.jpg"
        pg.save(f, quality=85)
        jpgs.append(str(f))
    pages[0].save(out / "board.jpg", quality=85)
    pdf = out / "board.pdf"
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=150)
    text = (f"wrote {pdf} ({len(pages)} pages) and {len(jpgs)} page JPGs in board/. {stats}.\n"
            "next: send board.pdf (or the JPG pages) to the owner, state how long you will wait, and record the approval "
            "with `slop board approve` once they agree.")
    return {"pdf": str(pdf), "jpgs": jpgs, "cover": str(out / "board.jpg"), "pages": len(pages), "stats": stats,
            "est_usd": cost.get("est_usd"), "est_usd_with_covers": cost.get("est_usd_with_covers"), "text": text}
