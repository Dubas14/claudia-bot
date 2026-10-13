"""`slop render clean [--keep-master] [--dry]` — free the disk the rendered frames take, once the deliverables verify.

A 5-minute film is ~7,400 frames per layout (16:9 and 9:16), several GB of JPEGs on the box's /workspace. They are
needed until the videos made from them are final; after that they are only a cache (`slop render frames` draws them
again). So clean refuses to delete anything until out/master.mp4 passes the master's ffprobe check (H.264 yuv420p,
BT.709 primaries/matrix, sRGB transfer, tv range, every frame of the song, its duration, an audio stream) and was
encoded from the frames now on disk (out/master.mp4.inputs.json, written by `slop render encode`, names their
.inputs.json hash; file times are not trusted — a render made after the encode would otherwise be lost).

Deleted (each only when its condition holds):
  render/frames/                 the master's frames — kept with --keep-master (to re-encode without re-rendering)
  render/frames-vertical/        only when out/vertical.mp4 also verifies (else kept, and the report says why) — a
                                 stretch (`render vertical --from/--to`) verifies over its own frames
  render/frames-WxH/, render/frames-vertical-crop/   previews at other sizes
  render/scratch/share*-x264*    x264 pass logs a stopped `encode --share` left behind
  out/draft*.mp4, out/*.frames.txt                   previews and leftovers
Never deleted: out/master.mp4, out/vertical.mp4, out/share*.mp4, out/review*.mp4, every project source file, the
reports (render/*.json), sheets (render/*.jpg), render/scan/ (the safety-scan record) and the rest of render/scratch/
(the Director-tier workflows work in render/scratch/chapters, review and scan while they run).
Refused while another `slop job` of this project is running (a render, an encode or a scan reading these files):
wait for it (`slop job wait ID`), then clean.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..config import SlopError
from . import project as P
from .encode import frame_indices, read_made_from, verify


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


def _newest(d: Path) -> float:
    try:
        return max((f.stat().st_mtime for f in d.glob("f*.jpg")), default=0.0)
    except OSError:
        return 0.0


def running_jobs(pdir: Path) -> list[dict]:
    """Other `slop job`s of this project that are still running (not this clean itself). [] when the job module is
    missing or unreadable — clean then relies on its other checks."""
    try:
        from ..job import TERMINAL, project_jobs
        jobs = project_jobs(pdir, unseen=False)
    except Exception:  # noqa: BLE001 - advisory: never block clean on a broken job store
        return []
    out = []
    for j in jobs:
        words = [str(w) for w in (j.get("argv") or [])]
        if j.get("state") in TERMINAL or ("render" in words and "clean" in words):
            continue
        out.append(j)
    return out


def _verify_deliverable(pdir: Path, video: Path, frames: Path, vertical: bool) -> tuple[bool, str]:
    """(ok, why): the video passes the master check for this project, and is newer than its frames."""
    if not video.is_file():
        return False, f"{video.relative_to(pdir).as_posix()} does not exist"
    fps = P.project_fps(pdir)
    rec = P.read_fingerprint(frames) if frames.is_dir() else None
    dur = float((rec or {}).get("duration") or 0) or P.render_duration(pdir, bool((rec or {}).get("timemap"))) or 0
    if not dur:
        return False, "unknown song duration (run `slop analyze`)"
    n = P.frame_count(dur, fps)
    # a stretch (`slop render vertical --from A --to B`: the cut that is posted) is checked over its own frames
    sp = (read_made_from(video) or {}).get("span")
    span = (int(sp[0]), int(sp[1])) if isinstance(sp, list) and len(sp) == 2 and 0 <= sp[0] < sp[1] <= n else None
    if span:
        n = span[1] - span[0]
    size = (1080, 1920) if vertical else P.project_size(pdir)
    try:
        v = verify(video, expect_frames=n, want_audio=True, size=size, expect_duration=n / fps)
    except SlopError as e:
        return False, f"{video.name} is not a readable video ({str(e)[-160:]})"
    if not v["ok"]:
        return False, f"{video.name} fails the master check: {'; '.join(v['problems'][:3])}"
    if frames.is_dir() and frame_indices(frames):
        made = read_made_from(video)
        redo = f"encode again (`slop render {'vertical' if vertical else 'encode'}`) before cleaning"
        if made is not None and rec is not None and made.get("hash") != rec.get("hash"):
            return False, f"{frames.name}/ holds a newer render than {video.name} (other inputs) — {redo}"
        if made is None and _newest(frames) > video.stat().st_mtime + 60:
            return False, f"{frames.name}/ has frames drawn after {video.name} was encoded — {redo}"
    what = f"the stretch {span[0] / fps:.2f}–{span[1] / fps:.2f} s, " if span else ""
    return True, (f"{video.name} verified ({what}{n} frames, {n / fps if span else dur:.2f} s, BT.709 / sRGB transfer / "
                  "tv, audio)")


def clean(pdir: Path, keep_master: bool = False, dry: bool = False) -> dict:
    render, out = pdir / "render", pdir / "out"
    busy = running_jobs(pdir)
    if busy and not dry:
        j = busy[0]
        raise SlopError(f"nothing deleted: {len(busy)} job(s) of this project still running ({j.get('id')}: "
                        f"{j.get('cmd') or ' '.join(map(str, j.get('argv') or []))}) — they may be reading these frames. "
                        f"Wait for it: `{j.get('wait') or 'slop job wait ' + str(j.get('id'))}`, then `slop render clean` "
                        "(`slop render clean --dry` lists what would go)")
    ok_m, why_m = _verify_deliverable(pdir, out / "master.mp4", render / "frames", False)
    if not ok_m:
        raise SlopError(f"nothing deleted: {why_m}. The master must verify before its frames go — run "
                        "`slop render encode` (it verifies the master), then `slop render clean`")
    targets: list[tuple[Path, str]] = []
    kept: list[str] = []
    if (render / "frames").is_dir():
        if keep_master:
            kept.append("render/frames/ (--keep-master)")
        else:
            targets.append((render / "frames", "the master's frames (out/master.mp4 verified)"))
    vdir = render / "frames-vertical"
    if vdir.is_dir():
        ok_v, why_v = _verify_deliverable(pdir, out / "vertical.mp4", vdir, True)
        if ok_v:
            targets.append((vdir, "the 9:16 frames (out/vertical.mp4 verified)"))
        else:
            kept.append(f"render/frames-vertical/ ({why_v}; run `slop render vertical` to finish it)")
    for d in sorted(render.glob("frames-*")) if render.is_dir() else []:
        if d.is_dir() and d.name != "frames-vertical":
            targets.append((d, "preview frames"))
    for f in sorted((render / "scratch").glob("share*-x264*")) if (render / "scratch").is_dir() else []:
        if f.is_file():
            targets.append((f, "x264 pass log left by a stopped `encode --share`"))
    for f in sorted(out.glob("draft*.mp4")) + sorted(out.glob("*.frames.txt")) if out.is_dir() else []:
        targets.append((f, "a preview"))
    freed = 0
    rows = []
    for p, why in targets:
        b = _size(p)
        freed += b
        rows.append({"path": p.relative_to(pdir).as_posix(), "bytes": b, "why": why})
        if not dry:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    gib = freed / 1024 ** 3
    verb = "would free" if dry else "freed"
    text = (f"{why_m}; {verb} {gib:.2f} GiB:"
            + ("".join(f"\n  {'-' if not dry else '?'} {r['path']}  {r['bytes'] / 1024 ** 2:,.0f} MiB  ({r['why']})" for r in rows)
               if rows else " nothing to delete"))
    if kept:
        text += "\nkept: " + "; ".join(kept)
    if busy:
        text += (f"\n! {len(busy)} job(s) of this project still running ({busy[0].get('id')}): the real clean waits "
                 "for them")
    text += ("\nkept always: out/*.mp4 deliverables, reports, sheets, render/scan/, the workflows' render/scratch/"
             + ("\nthis was a dry run: run `slop render clean` to delete" if dry else ""))
    return {"ok": True, "dry": dry, "freed_bytes": freed, "freed_gib": round(gib, 3), "deleted": [] if dry else rows,
            "would_delete": rows if dry else [], "kept": kept, "master": why_m, "text": text}
