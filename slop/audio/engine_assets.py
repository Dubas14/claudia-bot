"""Convert the analysis files into the shapes the EV/CLODYSSEY engine reads (for `slop edit export`).

  beats_obj(pdir) -> window.BEATS  {beats, downbeats, downbeat_phase, phase_blocks, duration, sections, tempo_start,
                                    tempo_end, bpm, offset, rms24, lines[], words[{w, line, t0, t1, s}]}
  hits_obj(pdir)  -> window.HITS   {fps, duration, kick, kick_s, snare, snare_s, hat, impact[{t, s}], impact_all,
                                    riser[[t0, t1]], ride[[t0, land]], fill[[t0, t1]], vox_on, env{mix, drums, ...}}
  lyr_obj(pdir)   -> window.LYR    [{line, kind, text, t0, t1, tokens[{txt, t0, t1, st, n}]}] (display.build_lyr)
Each returns None when the source file does not exist yet.
"""
from __future__ import annotations

from pathlib import Path

from .common import Paths, read_json


def beats_obj(pdir: Path) -> dict | None:
    p = Paths(pdir)
    B = read_json(p.beats)
    if not B:
        return None
    W = read_json(p.words) or {"words": [], "lines": []}
    out = {k: B.get(k) for k in ("beats", "downbeats", "downbeat_phase", "phase_blocks", "duration", "sections",
                                 "tempo_start", "tempo_end", "bpm", "offset", "rms24", "tempo")}
    out["lines"] = [L["text"] for L in W.get("lines", [])]
    out["words"] = [{"w": w["w"], "line": w["line"], "t0": w["t0"], "t1": w["t1"], "s": w.get("conf")} for w in W.get("words", [])]
    return out


def hits_obj(pdir: Path) -> dict | None:
    H = read_json(Paths(pdir).hits)
    if not H:
        return None
    return {"fps": H.get("fps", 24), "duration": H.get("duration"), "kick": H["kick"], "kick_s": H.get("kick_s", []),
            "snare": H["snare"], "snare_s": H.get("snare_s", []), "hat": H["hat"],
            "impact": [{"t": x["t"], "s": x["score"]} for x in H["hits"]],
            "impact_all": [{"t": x["t"], "s": x["score"]} for x in H.get("hits_all", [])],
            "riser": [[r["t0"], r["t1"]] for r in H["risers"]], "ride": [[r["t0"], r["land"]] for r in H["risers"]],
            "fill": [[f["t0"], f["t1"]] for f in H["fills"]], "vox_on": H["vocal_entries"], "env": H["env24"]}


def lyr_obj(pdir: Path) -> list | None:
    from .display import build_lyr, read_display
    p = Paths(pdir)
    W = read_json(p.words)
    if not W or not p.display.exists():
        return None
    return build_lyr(W["words"], read_display(p.display), read_json(p.adlibs, []) or [])
