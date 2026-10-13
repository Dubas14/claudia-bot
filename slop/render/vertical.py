"""The 9:16 cut (1080×1920).

method "rerender" (default): the engine lays the film out for portrait (portrait margins clear of the platforms' UI,
type fitted to the width, the base layer centred on the subject from PLATES boxes / clip tracks) and every frame is
rendered again at 1080×1920 into render/frames-vertical, then encoded to out/vertical.mp4 at FULL quality (the master
profile) — the whole song, or the stretch --from/--to picks (a hook cut is the cut that is posted: its frames, its
audio from its first frame, recorded as a stretch in out/vertical.mp4.inputs.json). Only --every N > 1 or
--allow-missing make a preview (draft profile -> out/vertical-draft.mp4). The result says which profile it used.
method "crop": a fast fallback — crops each master frame (render/frames) to 9:16 around the shot's subject (the
PLATES box of the shot's plate, or the clip's first tracked box; centre otherwise), one crop centre per shot (no
jitter), scaled to 1080×1920. Left-hung type is cut off: it is a preview, so it is encoded with the draft profile to
out/vertical-crop.mp4 (never out/vertical.mp4, the deliverable's name). It refuses stale master frames.
"""
from __future__ import annotations

from pathlib import Path

from .. import progress
from ..config import SlopError
from . import project as P
from .encode import check_fresh, encode, frame_indices
from .frames import frame_files, render_frames

VW, VH = 1080, 1920
_LABELS = ["subject", "a person", "a woman", "a man", "a girl", "a boy", "a singer", "a face"]


def _data(pdir: Path, name: str, rel: str):
    have = P.asset_files(pdir)
    if name in have:
        v = P.read_js_asset(have[name])
        if v is not None:
            return v
    return P._read_json(pdir / rel)


def subject_u(pdir: Path) -> list[tuple[float, float, float]]:
    """[(t0, t1, u)] — the subject's horizontal centre (image space 0..1) per shot."""
    shots = _data(pdir, "shots", "board/shots.json") or {}
    lst = shots.get("shots", []) if isinstance(shots, dict) else shots
    edl = _data(pdir, "edl", "edit/edl.json") or {}
    plates = _data(pdir, "plates", "plates/picks.json") or {}
    tracks = _data(pdir, "tracks", "") or {}
    proj = P.load_project(pdir)
    lead = (proj.get("lead") or {})
    want = [x for x in (lead.get("label"), lead.get("match")) if x] + _LABELS
    out = []
    for s in lst:
        try:
            t0, t1 = float(s["t0"]), float(s["t1"])
        except (KeyError, TypeError, ValueError):
            continue
        e = edl.get(s.get("id"), {}) if isinstance(edl, dict) else {}
        boxes = {}
        if e.get("plate"):
            boxes = (plates.get(e["plate"]) or {}).get("boxes") or {}
        elif e.get("segs"):
            tr = tracks.get(e["segs"][0].get("clip"), {}) if isinstance(tracks, dict) else {}
            boxes = {k: next((b for b in v if b), None) for k, v in tr.items()} if isinstance(tr, dict) else {}
        u = .5
        for lab in want:
            b = boxes.get(lab)
            if b and len(b) >= 4:
                u = float(b[0]) + float(b[2]) / 2
                break
        out.append((t0, t1, u))
    return out


def crop_frames(pdir: Path, src: Path, dst: Path, span: tuple[int, int] | None = None) -> dict:
    """Crop the master frames to 9:16 (span: only frames [first, end) — the stretch asked for)."""
    from PIL import Image
    idx = frame_indices(src)
    if span is not None:
        idx = [i for i in idx if span[0] <= i < span[1]]
    if not idx:
        raise SlopError(f"no master frames{' in the stretch asked for' if span else ''} in {src} — run `slop render "
                        "frames` first (crop works from them)")
    rec, changed = check_fresh(pdir, src)
    if changed:
        raise SlopError(f"the master frames in {src} are stale (the project changed: {', '.join(changed[:6])}) — run "
                        "`slop render frames` first (it redraws them), then crop")
    # crops of other master frames are stale: start over when the master's record changed
    if rec is not None and (P.read_fingerprint(dst) or {}).get("hash") != rec["hash"]:
        for f in frame_files(dst):
            f.unlink(missing_ok=True)
    fps = P.project_fps(pdir)
    spans = subject_u(pdir)
    dst.mkdir(parents=True, exist_ok=True)
    if rec is not None:
        P.write_fingerprint(dst, rec)                 # crops are fresh exactly when their master frames are
    n = 0
    prog = progress.Counter(len(idx), "render vertical crop", msg=f"render vertical crop: {len(idx)} master frames")
    try:
        for i in idx:
            f = dst / f"f{i:05d}.jpg"
            if not f.exists():
                t = i / fps
                u = next((u for a, b, u in spans if a <= t < b), .5)
                with Image.open(src / f"f{i:05d}.jpg") as im:
                    W, H = im.size
                    cw = min(W, int(round(H * VW / VH / 2)) * 2)
                    xc = W / 2 + (u - .5) * W * 1.06                   # the engine's default plate zoom is ~1.06
                    x0 = int(max(0, min(W - cw, round(xc - cw / 2))))
                    im.crop((x0, 0, x0 + cw, H)).resize((VW, VH), Image.LANCZOS).save(f.with_suffix(".jpg.tmp"), "JPEG",
                                                                                      quality=95)
                f.with_suffix(".jpg.tmp").replace(f)
                n += 1
            prog.add(1)
    finally:
        prog.finish()
    return {"cropped": n, "total": len(idx)}


# the encode profile of each cut, said in the command's text and JSON (the Studio E2E's 9:16 hook came out at draft quality)
PROFILE_TEXT = {"master": "profile master: full quality (x264 CRF 16, preset slow, BT.709)",
                "draft": "profile draft: a PREVIEW (x264 CRF 23, preset veryfast)"}


def vertical(pdir: Path, method: str = "rerender", workers: int | None = None, t_from: float | None = None,
             t_to: float | None = None, every: int = 1, skip_encode: bool = False, audio: bool = True,
             allow_missing: bool = False) -> dict:
    """The 9:16 cut. Full quality by default — the whole song, or the stretch --from/--to picks (the cut that is
    posted) -> out/vertical.mp4 with the master profile. A preview only when the frames are sampled (--every > 1) or
    drawn with placeholders (--allow-missing), or for --method crop -> out/vertical-draft.mp4 / out/vertical-crop.mp4
    with the draft profile. The text and JSON say which profile was used and why."""
    if method not in ("rerender", "crop"):
        raise SlopError("--method must be rerender or crop")
    every = max(1, int(every or 1))
    dst = pdir / "render" / ("frames-vertical" if method == "rerender" else "frames-vertical-crop")
    if method == "rerender":
        r = render_frames(pdir, t_from=t_from, t_to=t_to, every=every, workers=workers, w=VW, h=VH, out=dst,
                          allow_missing=allow_missing)
        if not r["ok"]:
            return {**r, "text": "vertical: " + r["text"]}
    fps = P.project_fps(pdir)
    if method == "rerender":
        step = {"frames": r}
        a, b = r["range"]
        # the frames of the stretch: exactly the ones render_frames drew ([first, end), not re-derived from the rounded
        # seconds) — none when --from/--to still cover the whole song (then it is the film, an ordinary master)
        lo, hi = r.get("span") or (int(round(a * fps)), P.frame_count(b, fps))
        whole = lo == 0 and hi >= P.frame_count(float(r.get("duration") or b), fps)
        span = None if (whole or (t_from is None and t_to is None)) else (int(lo), int(hi))
    else:
        a, b = max(0.0, float(t_from or 0)), (float(t_to) if t_to is not None else 1e9)
        span = (int(round(a * fps)), P.frame_count(b, fps)) if (t_from is not None or t_to is not None) else None
        step = {"crop": crop_frames(pdir, pdir / "render" / "frames", dst, span)}
    if method == "crop":
        # a preview by construction (left-hung type is cut off): never written under the deliverable's name
        name, profile, why = "vertical-crop.mp4", "draft", "--method crop cuts left-hung type"
    else:
        why = "; ".join(x for x in (f"--every {every} samples the frames" if every > 1 else "",
                                    "--allow-missing draws placeholders" if allow_missing else "") if x)
        name, profile = ("vertical-draft.mp4", "draft") if why else ("vertical.mp4", "master")
    stretch = f", the stretch {a:.2f}–{b:.2f} s" if span and method == "rerender" else ""
    said = PROFILE_TEXT[profile] + (f" — {why}" if why else "") + stretch
    if skip_encode:
        return {"ok": True, "frames_dir": str(dst), **step, "profile": profile, "profile_why": why or None,
                "text": f"vertical frames in {dst} (encode skipped; `slop render vertical` without --skip-encode encodes "
                        f"them: {said})"}
    e = encode(pdir, frames=dst, out=pdir / "out" / name, profile=profile, audio=audio, allow_gaps=profile == "draft",
               vertical=True, span=span)
    if method == "rerender" and span and not e.get("span"):        # encode found the range to be the whole song
        span, said = None, PROFILE_TEXT[profile] + (f" — {why}" if why else "")
    note = " — PREVIEW ONLY (crop cuts left-hung type; the deliverable is `slop render vertical`)" if method == "crop" else ""
    if profile == "draft" and method == "rerender":
        note = (" — PREVIEW ONLY: the deliverable is `slop render vertical`" + (" --from/--to" if span else "")
                + " without --every/--allow-missing (full quality -> out/vertical.mp4)")
    return {"ok": e["ok"], "method": method, "frames_dir": str(dst), **step, "encode": e, "out": e["out"],
            "profile": profile, "profile_why": why or None,
            "span_s": [round(a, 3), round(b, 3)] if span and method == "rerender" else None,
            "preview": profile == "draft", "text": f"vertical ({method}; {said}): {e['text']}{note}"}
