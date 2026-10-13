"""slop edit export — everything the render engine reads, in the EV/CLODYSSEY `window.*` formats, under
<project>/engine/assets/:

  beats.js   window.BEATS   = {beats, downbeats, duration, sections[{name, t0, t1}], sections_t, tempo_start, tempo_end,
                               bpm, rms24, lines, words[{w, line, t0, t1, s}], (downbeat_phase, phase_blocks), tempo}
  lyrics.js  window.LYR     = [{line, kind: "lyric"|"adlib", text, t0, t1, tokens[{txt, t0, t1, st, n}]}]
  hits.js    window.HITS    = {fps: 24, duration, kick, kick_s, snare, snare_s, hat, impact[{t, s}], impact_all[{t, s}]
                               (the audio module's hits_all peaks; impact when there are none), riser, ride, fill, vox_on,
                               env{mix, drums, bass, other, vocals}}   (when analysis/hits.json exists)
  shots.js   window.SHOTS   = board/shots.json (contract §3.2: {version, duration, chapters, shots, seedance, plates});
                               window.SHOTLIST = window.SHOTS (the older name the engine also reads)
  edl.js     window.EDL     = edit/edl.json (rebuilt first: `slop edit edl`)
  plates.js  window.PLATES  = {name: {w, boxes: {label: [u, v, w, h(, score)]}, subject_uv?, depth: false |
                               subject_depth + depth_model, graded?}}
                               + plates/<name>.jpg (<= 2400 px, q92)
                               and <name>.depth.png (Depth-Anything-V2-Small on CPU, when available)
                               boxes come from `slop plates box PLATE --label L --uv u,v,w,h` (plates/boxes.json), so
                               a device anchored {"box": "a face"} (or "a face") resolves on that plate; a box labelled
                               "subject" (or project.json lead.label) is also written as the plate's subject_uv
  clips.js   window.CLIPS   = {name: {n, fps, dir: "assets/clips/<name>", graded?}} + clips/<name>/f00001.jpg… (the
                               project fps, the project width, -q:v 2, graded with the clip's LUT in clean-grade)

LYR (port of display.py): lyrics/display.txt has one row per lyric line (blank rows and [Section] rows are skipped);
each space-separated token "TEXT|n" consumes n sung words and inherits their aligned times (default n = 1 if the token
has a letter or digit, else 0 = shown with the next token); ~strike~, *accent*, _mono_ styles. A row must consume exactly
its line's aligned words. When the audio module is installed its parser (`slop lyrics display`) builds the list, so the
check there and the export here can never disagree; the copy below is the fallback. Without display.txt the sung words
are the tokens. Optional ad-libs: lyrics/adlibs.json [{text, t0, t1, each?: [times]}] (0.4 s per token).

Idempotent: plates and clip frames are only rebuilt when their source, size or look changed (meta files next to them).
Changes from the source: one command instead of clip.py/prep.py/edl.py/display.py writing their own assets; frames go
straight to engine/assets (no media-volume symlinks); no Grounding DINO detections or mattes (boxes are named by hand
with `slop plates box`); BEATS.sections are the
contract's objects (EV wrote boundary floats, kept as sections_t) because the generic engine reads names from them.
"""
from __future__ import annotations

import json
import re
import shutil
import statistics
import subprocess
from pathlib import Path

from ..config import SlopError, load_project
from ..board.common import (load_beats, load_hits, load_shots, load_words, read_display, read_json, rel,
                            resolve_file, write_json, write_text)
from . import edl as edl_mod
from . import look as look_mod

PLATE_MAX_W = 2400
NAME_RE = re.compile(r"^(?P<clip>.+)-t(?P<k>\d+)$")


def js(name: str, obj) -> str:
    return f"window.{name} = " + json.dumps(obj, ensure_ascii=False) + ";\n"


# ------------------------------------------------------------------------------------------------ lyrics
def _tokens(spec: str) -> list[list]:
    out = []
    for tok in spec.split():
        if re.search(r"\|\d+$", tok):
            txt, n = tok.rsplit("|", 1)
            out.append([txt, int(n)])
        else:
            out.append([tok, None])
    return out


def build_lyr(pdir: Path, W: dict) -> tuple[list[dict], list[str]]:
    warns: list[str] = []
    disp = read_display(pdir)
    texts = {int(l["line"]): l.get("text", "") for l in W.get("lines", []) if l.get("line") is not None}
    by_line: dict[int, list] = {}
    for w in W["words"]:
        if w.get("line") is not None:
            by_line.setdefault(int(w["line"]), []).append(w)
    all_lines = sorted(set(texts) | set(by_line))
    if disp and len(disp) != len(all_lines):
        raise SlopError(f"lyrics/display.txt has {len(disp)} lyric rows but analysis/words.json has {len(all_lines)} "
                        "lines: write one row per lyric line, in order (blank rows and [Section] rows are "
                        "ignored)")
    if disp:
        try:
            from ..audio.display import build_lyr as audio_build_lyr
        except ImportError:
            audio_build_lyr = None
        if audio_build_lyr is not None:
            adl = read_json(pdir / "lyrics/adlibs.json", default=[]) or []
            return audio_build_lyr(W["words"], [disp[i] for i in sorted(disp)], adl), warns
    out = []
    for li in all_lines:
        ws = sorted(by_line.get(li, []), key=lambda w: w["t0"])
        if not ws:
            warns.append(f"line {li} has no aligned words — not on screen (re-run `slop analyze` or fix words.json)")
            continue
        spec = disp.get(li)
        if spec is None:
            res = [{"txt": w.get("w", ""), "t0": w["t0"], "t1": w["t1"], "st": "", "n": 1} for w in ws]
        else:
            k = 0
            res = []
            for txt, n in _tokens(spec):
                if n is None:
                    n = 1 if re.search(r"[A-Za-z0-9]", txt) else 0
                grp = ws[k:k + n]
                k += n
                st = "strike" if txt.startswith("~") else "accent" if txt.startswith("*") else "mono" if txt.startswith("_") else ""
                res.append({"txt": txt.strip("~*_"), "t0": grp[0]["t0"] if grp else None,
                            "t1": grp[-1]["t1"] if grp else None, "st": st, "n": n})
            if k != len(ws):
                raise SlopError(f"line {li}: lyrics/display.txt row \"{spec}\" consumes {k} of {len(ws)} sung words "
                                f"({' '.join(w.get('w', '') for w in ws)}). Give tokens that stand for several sung words "
                                "a count (e.g. AGI|3) and tokens that are not sung |0.")
            for i, r in enumerate(res):           # zero-word tokens take the next token's time
                if r["t0"] is None:
                    nxt = next((x for x in res[i + 1:] if x["t0"] is not None), None) or \
                        next((x for x in reversed(res[:i]) if x["t0"] is not None), None)
                    if nxt:
                        r["t0"], r["t1"] = nxt["t0"], nxt["t1"]
        ts = [r["t0"] for r in res if r["t0"] is not None]
        out.append({"line": li, "kind": "lyric", "text": " ".join(r["txt"] for r in res) if spec is not None
                    else (texts.get(li) or " ".join(r["txt"] for r in res)),
                    "t0": min(ts), "t1": max(r["t1"] for r in res if r["t1"] is not None), "tokens": res})
    for a in read_json(pdir / "lyrics/adlibs.json", default=[]) or []:
        parts = str(a.get("text", "")).split()
        if not parts:
            continue
        each = a.get("each") or [a["t0"] + i * (a["t1"] - a["t0"]) / len(parts) for i in range(len(parts))]
        toks = [{"txt": p, "t0": e, "t1": e + .4, "st": "adlib"} for p, e in zip(parts, each)]
        out.append({"line": None, "kind": "adlib", "text": a["text"], "t0": a["t0"], "t1": a["t1"], "tokens": toks})
    out.sort(key=lambda x: x["t0"])
    return out, warns


# ------------------------------------------------------------------------------------------------ beats / hits
def rms24_from_song(pdir: Path, proj: dict) -> list[float]:
    import numpy as np
    song = resolve_file(pdir, proj.get("song") or "audio/song.wav")
    if not (song and song.is_file() and shutil.which("ffmpeg")):
        return []
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(song), "-ac", "1", "-ar", "24000", "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    if not len(x):
        return []
    n = len(x) // 1000
    fr = x[: n * 1000].reshape(n, 1000)
    return [round(float(v), 4) for v in np.sqrt((fr ** 2).mean(1))]


def build_beats(pdir: Path, proj: dict, B: dict, W: dict, hits: dict) -> tuple[dict, list[str]]:
    warns = []
    b = {"beats": [round(x, 4) for x in B["beats"]], "downbeats": [round(x, 4) for x in B["downbeats"]],
         "duration": round(B["duration"], 4)}
    for k in ("downbeat_phase", "phase_blocks", "source"):
        if k in B:
            b[k] = B[k]
    b["sections"] = B["sections"]                       # [{name, t0, t1, energy?}]: the engine reads them as objects
    b["sections_t"] = [round(s["t0"], 4) for s in B["sections"]]
    tempo = [t for t in (B.get("tempo") or []) if isinstance(t, dict) and t.get("bpm")]
    if tempo:
        b["tempo"] = tempo
        b["tempo_start"], b["tempo_end"] = round(float(tempo[0]["bpm"]), 2), round(float(tempo[-1]["bpm"]), 2)
        b["bpm"] = round(statistics.median(float(t["bpm"]) for t in tempo), 2)
    else:
        per = statistics.median(y - x for x, y in zip(B["beats"], B["beats"][1:]))
        b["bpm"] = round(60 / per, 2)
        b["tempo_start"] = b["tempo_end"] = b["bpm"]
    env = hits.get("env24") or hits.get("env") or {}
    rms = B.get("rms24") or env.get("mix") or rms24_from_song(pdir, proj)
    if not rms:
        warns.append("no rms24 (no analysis rms24, hits env mix or readable song): the engine's level-driven devices are flat")
    b["rms24"] = rms
    lines = sorted((l for l in W.get("lines", []) if l.get("line") is not None), key=lambda l: int(l["line"]))
    b["lines"] = [l.get("text", "") for l in lines]
    b["words"] = [{"w": w.get("w", ""), "line": w.get("line"), "t0": w["t0"], "t1": w["t1"],
                   "s": w.get("conf", w.get("s", w.get("score")))} for w in W["words"]]
    return b, warns


def _pairs(v) -> tuple[list, list | None]:
    if v and isinstance(v[0], dict):
        return [x["t"] for x in v], [x.get("s", x.get("score", 1.0)) for x in v]
    return list(v or []), None


def build_hits(hits: dict, dur: float) -> dict:
    H = {"fps": int(hits.get("fps", 24)), "duration": round(float(hits.get("duration", dur)), 3)}
    for k in ("kick", "snare", "hat"):
        t, s = _pairs(hits.get(k) or [])
        H[k] = t
        if hits.get(k + "_s") is not None:
            H[k + "_s"] = hits[k + "_s"]
        elif s is not None:
            H[k + "_s"] = s
        elif k != "hat":
            H[k + "_s"] = [1.0] * len(t)
    if "impact" in hits:
        H["impact"] = hits["impact"]
    else:
        H["impact"] = [{"t": h["t"], "s": h.get("s", h.get("score", 1.0))} for h in hits.get("hits") or []
                       if isinstance(h, dict) and "t" in h]
    if hits.get("impact_all") is not None:
        H["impact_all"] = hits["impact_all"]
    elif hits.get("hits_all"):                   # audio module: every broadband peak (impact = the top hits)
        H["impact_all"] = [{"t": h["t"], "s": h.get("s", h.get("score", 1.0))} for h in hits["hits_all"]
                           if isinstance(h, dict) and "t" in h]
    else:
        H["impact_all"] = H["impact"]
    risers = hits.get("risers") or []
    H["riser"] = hits.get("riser") or [[r["t0"], r["t1"]] for r in risers if isinstance(r, dict)]
    H["ride"] = hits.get("ride") or [[r["t0"], r["land"]] for r in risers if isinstance(r, dict) and r.get("land") is not None]
    H["fill"] = hits.get("fill") or [[f["t0"], f["t1"]] for f in hits.get("fills") or [] if isinstance(f, dict)]
    H["vox_on"] = hits.get("vox_on") or hits.get("vocal_entries") or []
    H["env"] = hits.get("env") or hits.get("env24") or {}
    for k, v in hits.items():                    # anything else the analysis wrote passes through
        if k not in H and k not in ("hits", "hits_all", "risers", "fills", "vocal_entries", "env24"):
            H[k] = v
    return H


# ------------------------------------------------------------------------------------------------ media
def _src_sig(f: Path) -> dict:
    st = f.stat()
    return {"src": str(f), "size": st.st_size, "mtime": int(st.st_mtime)}


def export_plates(pdir: Path, picks: dict, plan: dict, depth_mode: str, force: bool) -> tuple[dict, list[str], dict]:
    from PIL import Image
    warns: list[str] = []
    outdir = pdir / "engine/assets/plates"
    outdir.mkdir(parents=True, exist_ok=True)
    use_depth = False
    if depth_mode in ("on", "auto"):
        from . import depth as depth_mod
        use_depth = depth_mod.available()
        if not use_depth:
            msg = "no depth maps: torch/transformers are not installed (bin/setup.sh) — plates render flat (no 2.5D)"
            if depth_mode == "on":
                raise SlopError(msg)
            warns.append(msg)
    sig = look_mod.signature(plan)
    index: dict = {}
    counts = {"made": 0, "kept": 0, "depth": 0}
    from ..board.plates import read_boxes
    boxes = read_boxes(pdir)                     # `slop plates box`: named regions, image space 0..1
    lead_label = str(((load_project(pdir).get("lead") or {}).get("label")) or "")
    for name, v in sorted(picks.items()):
        f = resolve_file(pdir, (v or {}).get("file"))
        if not (f and f.is_file()):
            warns.append(f"plate {name}: picked file {v.get('file') if v else None} is missing")
            continue
        jpg, dpng, metap = outdir / f"{name}.jpg", outdir / f"{name}.depth.png", outdir / f"{name}.meta.json"
        want = {**_src_sig(f), "look": sig, "depth": use_depth}
        meta = read_json(metap, default={}) or {}
        if not force and jpg.is_file() and meta.get("sig") == want and (not use_depth or dpng.is_file()):
            counts["kept"] += 1
        else:
            im = Image.open(f).convert("RGB")
            if im.width > PLATE_MAX_W:
                im = im.resize((PLATE_MAX_W, round(im.height * PLATE_MAX_W / im.width)), Image.LANCZOS)
            meta = {"sig": want, "w": im.width, "h": im.height}
            if use_depth:
                from . import depth as depth_mod
                try:
                    meta["subject_depth"] = depth_mod.depth_png(depth_mod.estimate(im), dpng)
                    counts["depth"] += 1
                except Exception as e:  # noqa: BLE001 - e.g. no network for the first model download
                    if depth_mode == "on":
                        raise SlopError(f"depth for {name} failed: {e}") from e
                    warns.append(f"depth for {name} failed ({type(e).__name__}: {str(e)[:120]}) — flat plate")
                    use_depth = False
            elif dpng.exists():
                dpng.unlink()
            if plan.get("grade"):
                im = look_mod.look_image(im, plan["conf"], plan["ref"])
                meta["graded"] = True
            im.save(jpg, quality=92)
            write_json(metap, meta)
            counts["made"] += 1
        bx = boxes.get(name) or {}
        entry = {"w": meta.get("w"), "boxes": dict(bx.get("boxes") or {})}
        if entry["boxes"]:
            if bx.get("file") and bx["file"] != (v or {}).get("file"):
                warns.append(f"plate {name}: its boxes ({', '.join(entry['boxes'])}) were drawn on {bx['file']}, but the "
                             f"pick is now {(v or {}).get('file')} — check them (`slop plates box {name}`)")
            subj = next((entry["boxes"][k] for k in (lead_label, "subject", "lead") if k and k in entry["boxes"]), None)
            if subj and len(subj) >= 4:
                entry["subject_uv"] = list(subj[:4])      # the engine's subject box without a depth map
        if meta.get("subject_depth") is not None and dpng.is_file():
            from .depth import MODEL
            entry["subject_depth"] = meta["subject_depth"]
            entry["depth_model"] = MODEL
        else:
            entry["depth"] = False
        if meta.get("graded"):
            entry["graded"] = True
        index[name] = entry
    return index, warns, counts


def extract_frames(src: Path, dst: Path, fps: int, width: int, lut: Path | None = None) -> int:
    dst.mkdir(parents=True, exist_ok=True)
    for f in dst.glob("f*.jpg"):
        f.unlink()
    vf = f"fps={fps},scale={width}:-2:flags=lanczos"
    if lut:
        vf += f",lut3d=file={look_mod.ff_path(lut)}:interp=tetrahedral"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", vf, "-q:v", "2", str(dst / "f%05d.jpg")],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SlopError(f"ffmpeg could not extract frames from {src}: {r.stderr.strip()[-300:]}")
    return len(list(dst.glob("f*.jpg")))


def export_clips(pdir: Path, names: list[str], plan: dict, fps: int, width: int, force: bool) -> tuple[dict, list[str], dict]:
    warns: list[str] = []
    root = pdir / "engine/assets/clips"
    root.mkdir(parents=True, exist_ok=True)
    sig = look_mod.signature(plan)
    counts = {"made": 0, "kept": 0}
    ed = edl_mod.Edit(pdir)
    for name in sorted(set(names)):
        m = NAME_RE.match(name)
        c = ed.load(m.group("clip")) if m else None
        takes = (c or {}).get("takes") or []
        k = int(m.group("k")) if m else 0
        if not m or not c or not (1 <= k <= len(takes)):
            warns.append(f"clip {name}: no clips/<clip>.json take for it")
            continue
        src = resolve_file(pdir, takes[k - 1].get("file"))
        if not (src and src.is_file()):
            warns.append(f"clip {name}: take file {takes[k - 1].get('file')} is missing")
            continue
        d = root / name
        want = {**_src_sig(src), "look": sig, "fps": fps, "width": width}
        meta = read_json(d / "meta.json", default={}) or {}
        if not force and meta.get("sig") == want and meta.get("n") and len(list(d.glob("f*.jpg"))) == meta["n"]:
            counts["kept"] += 1
            continue
        if not shutil.which("ffmpeg"):
            raise SlopError("ffmpeg not found on PATH — run bin/setup.sh (needed to extract clip frames)")
        lut = None
        if plan.get("grade"):
            st = look_mod.clip_stats(src)
            lut = look_mod.cube(st, d / "grade.cube", plan["conf"], plan["ref"], title=name)
        n = extract_frames(src, d, fps, width, lut)
        write_json(d / "meta.json", {"sig": want, "n": n, "fps": fps, "src": rel(pdir, src),
                                     **({"graded": {"lut": "grade.cube", "stats": "16 sampled frames"}} if lut else {})})
        counts["made"] += 1
    index = {}
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        meta = read_json(d / "meta.json", default={}) or {}
        n = len(list(d.glob("f*.jpg")))
        if not n:
            continue
        e = {"n": n, "fps": int(meta.get("fps", fps)), "dir": f"assets/clips/{d.name}"}
        if meta.get("graded"):
            e["graded"] = True
        index[d.name] = e
    return index, warns, counts


# ------------------------------------------------------------------------------------------------ run
def run(pdir: Path, depth: str = "auto", frames: bool = True, force: bool = False) -> dict:
    pdir = Path(pdir)
    proj = load_project(pdir)
    B = load_beats(pdir)
    W = load_words(pdir)
    hits = load_hits(pdir)
    S = load_shots(pdir)
    assets = pdir / "engine/assets"
    assets.mkdir(parents=True, exist_ok=True)
    warns: list[str] = []
    rep = edl_mod.build(pdir)
    E = read_json(pdir / "edit/edl.json", default={}) or {}
    plan = look_mod.bake_plan(pdir, proj)
    picks = read_json(pdir / "plates/picks.json", default={}) or {}
    fps = int(proj.get("fps") or 24)
    width = int((proj.get("size") or [1920, 1080])[0])
    plates_idx, w1, pc = export_plates(pdir, picks, plan, depth, force)
    warns += w1
    clip_names = [g["clip"] for e in E.values() for g in e.get("segs", [])]
    if frames:
        clips_idx, w2, cc = export_clips(pdir, clip_names, plan, fps, width, force)
        warns += w2
    else:
        clips_idx, cc = {}, {"made": 0, "kept": 0}
        old = assets / "clips.js"
        if old.exists():
            txt = old.read_text(encoding="utf-8")
            clips_idx = json.loads(txt[txt.index("=") + 1:].strip().rstrip(";"))
    lyr, w3 = build_lyr(pdir, W)
    warns += w3
    beats, w4 = build_beats(pdir, proj, B, W, hits)
    warns += w4
    written = []
    shots_obj = {**S, "duration": S.get("duration", round(B["duration"], 4))}
    for fname, var, obj in (("beats.js", "BEATS", beats), ("lyrics.js", "LYR", lyr), ("shots.js", "SHOTS", shots_obj),
                            ("edl.js", "EDL", E), ("plates.js", "PLATES", plates_idx), ("clips.js", "CLIPS", clips_idx)):
        text = js(var, obj) + ("window.SHOTLIST = window.SHOTS;\n" if var == "SHOTS" else "")
        write_text(assets / fname, text)
        written.append(fname)
    if hits:
        write_text(assets / "hits.js", js("HITS", build_hits(hits, B["duration"])))
        written.append("hits.js")
    else:
        warns.append("no analysis/hits.json: hits.js not written (the engine's HIT/CAM helpers stay idle)")
    missing_media = [g for g in set(clip_names) if g not in clips_idx] if frames else []
    text = (f"engine/assets: {', '.join(written)} · {len(lyr)} lyric lines, {sum(len(l['tokens']) for l in lyr)} tokens · "
            f"{len(plates_idx)} plates ({pc['made']} made, {pc['kept']} unchanged, {pc['depth']} depth maps) · "
            f"{len(clips_idx)} clip frame sets ({cc['made']} extracted, {cc['kept']} unchanged) · look: {plan['why']}\n"
            f"edit: {rep.get('summary') or rep['text'].splitlines()[-1]}")
    if rep["missing"]:
        text += f"\n{len(rep['missing'])} shot(s) have no media yet: {', '.join(rep['missing'][:10])}"
    if missing_media:
        text += f"\n{len(missing_media)} clip(s) in the EDL have no frames: {', '.join(sorted(missing_media)[:8])}"
    if warns:
        text += "\nwarnings:\n" + "\n".join("  - " + w for w in warns[:12])
    text += "\nnext: render a preview with the engine (`slop render ...`)."
    return {"assets": str(assets), "written": written, "lyric_lines": len(lyr), "plates": pc, "clips": cc,
            "missing_shots": rep["missing"], "missing_clip_frames": missing_media, "look": plan["why"],
            "warnings": warns, "text": text}
