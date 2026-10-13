"""`slop render check --layers` — the density rule as a check: every shot's mid-point frame needs at least 3 ORDERED
information layers (ANIMATION_GUIDE / docs/70 §4: media + lyric + chrome + annotation or graphic).

The engine counts them (engine/src/core.js ENGINE.frameLayers: media · graphic · annotation · micro · lyric · chrome,
each kind once, for the frame just drawn). This samples the mid-point of every scene the page renders (storyboard
shots, chapter scenes and the gap fillers between shots), in parallel browsers, and writes render/layers.json
(render/layers-vertical.json for the 9:16 layout, so the two reports never overwrite each other).
A shot may opt out as a CLEAN HERO MOMENT ("hero_moment": true in board/shots.json): allowed when it lasts at most
2 bars and still shows media + the lyric (docs/70 §4: "allowed for ≤ 2 bars and must be earned").
Bespoke chapter code (Director tier) draws with its own code, which the engine sees only through its helpers (plates
and clip frames, KIN.mark, ENGINE.chrome, ENGINE.drawDevice) or ENGINE.noteLayer(kind). A chapter scene below the rule
that declared nothing is reported UNVERIFIED (look at that frame), not failed.
No master needed: run it after `slop edit export`, before `slop render frames`.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import time
from pathlib import Path

from .. import progress
from ..config import SlopError
from . import project as P
from .browser import EnginePage
from .frames import _log, _suffix, _sync_playwright, default_workers

RULE = 3


def _shots(pdir: Path) -> dict:
    have = P.asset_files(pdir)
    v = P.read_js_asset(have["shots"]) if "shots" in have else None
    if v is None:
        v = P._read_json(pdir / "board" / "shots.json")
    lst = v.get("shots", []) if isinstance(v, dict) else (v or [])
    return {str(s.get("id")): s for s in lst if isinstance(s, dict) and s.get("id") is not None}


def _bar_len(pdir: Path, t: float) -> float:
    """Seconds in one bar near t (4 beats of analysis/beats.json; 2 s without a beat map)."""
    have = P.asset_files(pdir)
    b = P.read_js_asset(have["beats"]) if "beats" in have else None
    b = b if isinstance(b, dict) else (P._read_json(pdir / "analysis" / "beats.json") or {})
    beats = [float(x) for x in (b.get("beats") or []) if isinstance(x, (int, float))]
    if len(beats) < 5:
        return 2.0
    i = min(range(len(beats)), key=lambda k: abs(beats[k] - t))
    i = max(0, min(len(beats) - 5, i - 2))
    return max(.5, beats[i + 4] - beats[i])


def _lines(shot: dict | None) -> list[int]:
    out = []
    for x in (shot or {}).get("lines") or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def fix_hint(name: str, layers: list[str], shot: dict | None) -> str:
    """One board command that adds a MISSING layer to this shot, then the re-check."""
    have = set(layers)
    if shot is None and name.startswith(("gap", "fill")):
        return ("a hole in the storyboard (no shot covers it): extend the shot before or after it over the gap "
                "(t0/t1 in board/shots.json), then `slop edit export`")
    if "media" not in have:
        return "no picture drew (missing plate or clip?): `slop render info` lists missing media; `slop edit export` rebuilds it"
    lines = _lines(shot)
    if "annotation" not in have and lines:       # a callout (role cv) adds the annotation layer and explains the line
        tips = [f"add one device that explains its line: `slop board device add {name} --kind callout --line {lines[0]}`"]
    elif "micro" not in have:                    # marks (role micro) needs no lyric line: intro / outro / instrumental
        tips = [f"add one device that needs no lyric line, e.g. a beat ruler: `slop board device add {name} --kind marks "
                "--param style=ruler`"]
    else:
        tips = [f"add one hero device (a graphic): `slop board device kinds` lists them; `slop board device add {name} "
                "--kind K`"]
    if "chrome" not in have:
        tips.append('its chrome is off ("chrome": "off" in board/shots.json; no board command sets it): the device '
                    "adds the missing layer instead")
    return "; ".join(tips) + " — then `slop edit export` and run this again"


BESPOKE_NOTE = ("drawn by the project's chapter code, which the engine cannot fully see: look at this frame "
                "(`slop render stills --times {t}`), and in the chapter code call ENGINE.noteLayer('graphic' | "
                "'annotation' | 'micro' | 'media' | 'lyric' | 'chrome') for each layer it draws itself")


BESPOKE_FIX = ("drawn by the project's chapter code (it declares {have}): add a layer there — a graphic, an annotation "
               "or micro type — and declare it with ENGINE.noteLayer(kind), then `slop edit export` and run this again")


def judge(rows: list[dict], shots: dict, pdir: Path, rule: int = RULE) -> tuple[list, list, list]:
    """(failing, allowed, unverified) of the sampled mid-points; each failing row gets its "fix", each unverified
    one its "note"."""
    failing, allowed, unverified = [], [], []
    for r in rows:
        if r["count"] >= rule:
            continue
        if r.get("bespoke") and not r.get("noted") and not r.get("error"):
            r["note"] = BESPOKE_NOTE.format(t=r["t"])
            unverified.append(r)
            continue
        sh = shots.get(r["scene"])
        if sh and sh.get("hero_moment") and {"media", "lyric"} <= set(r["layers"]) \
                and (r["t1"] - r["t0"]) <= 2 * _bar_len(pdir, r["t"]) + 1e-3:
            r["allowed"] = "clean hero moment (hero_moment: true, ≤ 2 bars)"
            allowed.append(r)
            continue
        r["fix"] = (BESPOKE_FIX.format(have=" + ".join(r.get("noted") or []) or "nothing") if r.get("bespoke")
                    else fix_hint(r["scene"], r["layers"], sh))
        failing.append(r)
    return failing, allowed, unverified


def check_layers(pdir: Path, workers: int | None = None, w: int | None = None, h: int | None = None,
                 out: Path | None = None, rule: int = RULE) -> dict:
    spec = P.page_spec(pdir, w, h)
    fps = float(spec["fps"])
    sync_playwright = _sync_playwright()
    with sync_playwright() as p:
        with EnginePage(p, spec) as pg:
            scenes = pg.scenes()
            probe = pg.page.evaluate("() => !!(window.ENGINE && ENGINE.frameLayers)")
            errs = list(pg.errors)
    if errs:
        raise SlopError("the engine page threw errors (fix them first): " + " | ".join(errs[:3]))
    if not probe:
        raise SlopError("this engine has no layer probe (ENGINE.frameLayers): reinstall the toolkit (bin/setup.sh)")
    if not scenes:
        raise SlopError("the engine page has no scenes — run `slop board draft` and `slop edit export` first")
    shots = _shots(pdir)
    samples = []
    for sc in scenes:
        t = (float(sc["t0"]) + float(sc["t1"])) / 2
        samples.append({"scene": sc["name"], "t0": round(float(sc["t0"]), 3), "t1": round(float(sc["t1"]), 3),
                        "t": round(round(t * fps) / fps, 4), "bespoke": bool(sc.get("bespoke"))})
    nw = workers or default_workers(len(samples))
    nw = max(1, min(nw, len(samples)))
    chunks = [samples[k::nw] for k in range(nw)]
    prog = progress.Counter(len(samples), "render check layers", msg=f"layers: {len(samples)} mid-points, {nw} worker(s)")
    t0 = time.monotonic()

    def work(ch):
        res = []
        if not ch:
            return res
        with sync_playwright() as p:
            with EnginePage(p, spec) as pg:
                for s in ch:
                    try:
                        r = pg.layers(s["t"]) or {}
                    except Exception as e:  # noqa: BLE001 — a frame that fails counts as 0 layers, with the error
                        _log(f"[layers] t={s['t']:.2f}: {str(e)[:160]}")
                        pg.reopen()
                        r = {"count": 0, "layers": [], "error": str(e)[:200]}
                    res.append({**s, "count": int(r.get("count") or 0), "layers": list(r.get("layers") or []),
                                "noted": list(r.get("noted") or []), "treatment": r.get("treatment"),
                                **({"error": r["error"]} if r.get("error") else {})})
                    prog.add(1)
        return res

    try:
        with cf.ThreadPoolExecutor(nw) as ex:
            rows = sorted((r for part in ex.map(work, chunks) for r in part), key=lambda r: r["t"])
    finally:
        prog.finish()
    failing, allowed, unverified = judge(rows, shots, pdir, rule)
    rep = {"rule": rule, "checked": len(rows), "passed": len(rows) - len(failing) - len(unverified), "failing": failing,
           "allowed": allowed, "unverified": unverified, "frames": rows, "size": [spec["w"], spec["h"]],
           "seconds": round(time.monotonic() - t0, 1)}
    outf = Path(out) if out else pdir / "render" / f"layers{_suffix(pdir, spec['w'], spec['h'])}.json"
    outf.parent.mkdir(parents=True, exist_ok=True)
    outf.write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    counts = sorted(r["count"] for r in rows)
    med = counts[len(counts) // 2] if counts else 0
    rel = outf.relative_to(pdir).as_posix() if outf.is_relative_to(pdir) else str(outf)
    text = (f"layers ({spec['w']}x{spec['h']}): {rep['passed']}/{len(rows)} shot mid-points have ≥ {rule} ordered "
            f"layers (median {med}; {rep['seconds']} s) -> {rel}")
    if allowed:
        text += f"\n  {len(allowed)} clean hero moment(s) allowed: " + ", ".join(r["scene"] for r in allowed[:10])
    if unverified:
        text += (f"\nUNVERIFIED — {len(unverified)} chapter scene(s) below {rule} that declared no layers (bespoke code):\n"
                 + "\n".join(f"  {r['scene']:>8} {r['t']:7.2f}s  {r['count']} ({' + '.join(r['layers']) or 'nothing seen'})"
                             for r in unverified[:12])
                 + "\n  → " + BESPOKE_NOTE.format(t=unverified[0]["t"]))
    if failing:
        text += f"\nFAIL — {len(failing)} below {rule}:\n" + "\n".join(
            f"  {r['scene']:>8} {r['t']:7.2f}s  {r['count']} ({' + '.join(r['layers']) or 'nothing'})  → {r['fix']}"
            for r in failing[:30])
        if len(failing) > 30:
            text += f"\n  … and {len(failing) - 30} more (render/layers.json)"
    return {"ok": not failing, "layers": rep, "report": str(outf), "text": text}
