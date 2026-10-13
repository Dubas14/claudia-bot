"""Variable-tempo beat map -> analysis/beats.json (contract §4.2; the engine's window.BEATS). Never a single BPM.

Port of tools/beatmap.py + the beats part of the GPU analyze script, same algorithm and constants:
  1. global grid (analyze part 1): onset envelope of the mix (librosa, median aggregate); comb search over
     BPM_HINT x 0.92 ... x 1.08 in 0.01 BPM steps and phases in 5 ms steps for the period + offset whose comb best
     matches the envelope. Used to seed the tempo range and as the optional `beatgrid: "analysis"` grid.
  2. drum stem -> mono 11,025 Hz, log energy per 64-sample hop (172 fps), positive spectral flux minus its mean; the kick
     band = the drum stem through ffmpeg lowpass=f=150.
  3. tempo range = project.json audio.tempo_range or the global BPM +- 4 %; local (BPM, phase) fits in 20 s windows
     every 5 s (BPM step 0.05, phase step 4 ms, score = mean flux on the comb); windows scoring at or below the 20th
     percentile are ignored (breakdowns); the curve is interpolated on a 0.5 s grid and smoothed with a 21-point
     moving average (edge padding 10).
  4. beats are stepped along the curve from the second window's phase (stepped back to the song start) and each snaps
     to the strongest flux peak within +-30 ms when that peak exceeds 15 % of the song's max flux. ADDED: the head is
     re-tracked - from the first 4 consecutive snapped beats the map steps BACK to the song start, snapping each beat
     the same way (the original jumped back by whole periods of the tempo at 0 s, so an intro whose tempo differs from
     the first fit window started 40-80 ms off until the forward snapping caught up a few bars later: on the synthetic
     120 -> 124 BPM test song the first three bar lines were 37-77 ms late). The re-tracked head is used only when at
     least half of its beats snap to drum hits; a drumless intro keeps the original extrapolation (on the EV take that
     grid matches the intro's mix onsets; the re-tracked one did not), and where the forward pass snapped from the
     start nothing changes.
  5. downbeat phase: kick energy at each of the 4 beat phases summed per 32-beat block, majority vote;
     project.json audio.downbeat_phase overrides it (use it when the vote picks a backbeat: claps on 2 and 4; set it
     with `slop song bars --phase N`, which re-derives the bars in a second and logs the decision). Bars count from 0:
     bar 0 starts at downbeats[0] = beats[phase].
     FIXED: the kick energy of a beat is the MAX over [beat - 10 ms, beat + 50 ms] of the 150 Hz low-passed drum stem
     (172 fps), not the single frame at the beat: beats snap to the broadband flux peak (the attack), while the
     low-passed kick energy peaks later (median 17 ms on the synthetic kit, 35 ms on the EV take), so one frame
     sampled the rising edge and the vote could pick beat 4 of the bar (every bar line one beat early; drops, risers
     and fills snapped one beat early with it). The global grid's phase vote uses the same window.
     Second opinion (reported, not used unless asked): a per-block vote on where the chords change (chroma novelty of
     the other + bass stems) -> beats.json downbeat_votes.harmony, and a note when it disagrees.
     project.json audio.downbeat_method: "kick" (default, the original rule), "harmony" (the chord vote decides) or
     "auto" (the chord vote decides when significant: >= half the blocks and >= 1.5x the other phases). Measured on two
     songs (tests/bench_audio_ev.py): kick picks the shipped bar phase on both (EV 100 %, SP 97.1 % of shipped bars
     within 30 ms); harmony and auto agree on SP but put EV's bars two beats off (0 %) - so "kick" is the default.
     `slop song bars --phase N|auto` / `--method` re-decide from the votes stored in beats.json (apply_phase: no audio
     re-analysis) and the command shows each phase's first bar line and its kick and chord votes. Every note that
     suggests another phase names that command (with --project), never a hand edit of project.json: a hand edit skips
     the DECISIONS.md line, the storyboard check and the fast path (it costs a full beat-map rebuild).
     audio.beatgrid = "analysis" uses the global grid instead (steady takes); audio.beat_pad0 prepends a beat at 0.0.
Changes (bug fixes / generalisation): no fixed /tmp/*.f32 files (ffmpeg pipes; projects can run in parallel); the BPM
hint is project.json audio.bpm_hint or librosa's tempo estimate folded into 80-180 BPM (the original hard-coded 128
for electroclash); the comb searches are vectorised (same maths, same first-best tie rule); beatmap no longer reads
words.json (the align-merge <-> beatmap circular dependency is gone); a stepped beat past the song's end is dropped;
rms24 is exact 24 fps block RMS (the old hop int(sr/24) drifted ~0.08 s over 5 min); song onsets are not stored
(hits.json has the drum onsets).
Benchmark vs the shipped EV beat map: see slop/audio/__init__.py.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import Paths, audio_cfg, fingerprint, load_mono, need_module, read_json, state_get, state_set, write_json

SR_DRUM, HOP_DRUM = 11025, 64


# ---------------------------------------------------------------- 1. global grid (analyze part 1)
def onset_envelope(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    librosa = need_module("librosa", "beat analysis uses librosa's onset envelope")
    oenv = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
    return oenv, librosa.times_like(oenv, sr=sr)


def estimate_bpm(oenv: np.ndarray, sr: int) -> float:
    librosa = need_module("librosa", "beat analysis")
    try:
        bpm = float(np.atleast_1d(librosa.feature.tempo(onset_envelope=oenv, sr=sr))[0])
    except Exception:
        bpm = 120.0
    if not 20 <= bpm <= 400:
        return 120.0
    while bpm < 80:                       # octave errors: fold into 80-180 BPM (set audio.bpm_hint for slower songs)
        bpm *= 2
    while bpm >= 180:
        bpm /= 2
    return bpm


def comb_search(oenv: np.ndarray, ot: np.ndarray, dur: float, hint: float) -> tuple[float, float, float]:
    """-> (score, period, offset): the comb arange(off, dur, period) with the highest mean envelope."""
    best = (-1.0, 60 / hint, 0.0)
    for bpm in np.arange(hint * .92, hint * 1.08, .01):
        per = 60 / bpm
        offs = np.arange(0, per, .005)
        n = int(np.ceil(dur / per)) + 1
        g = offs[:, None] + np.arange(n)[None, :] * per
        mask = g < dur
        v = np.interp(np.where(mask, g, 0.0), ot, oenv)
        m = (v * mask).sum(1) / np.maximum(mask.sum(1), 1)
        j = int(np.argmax(m))
        if m[j] > best[0]:
            best = (float(m[j]), float(per), float(offs[j]))
    return best


def global_grid(y: np.ndarray, sr: int, hint: float | None = None) -> dict:
    librosa = need_module("librosa", "beat analysis")
    dur = len(y) / sr
    oenv, ot = onset_envelope(y, sr)
    hint = float(hint) if hint else estimate_bpm(oenv, sr)
    _, period, off = comb_search(oenv, ot, dur, hint)
    grid = np.arange(off, dur, period)
    import warnings
    with warnings.catch_warnings():                       # 128 mel bands under 200 Hz: librosa warns, as it did before
        warnings.simplefilter("ignore", UserWarning)
        oenv_low = librosa.onset.onset_strength(y=y, sr=sr, fmax=200)
    hop_fr = sr / 512.0                                    # librosa's default hop
    phase_energy = [float(np.sum(window_max(oenv_low, grid[k::4], hop_fr))) for k in range(4)]
    ph = int(np.argmax(phase_energy))
    return {"bpm": round(60 / period, 4), "offset": round(off, 4), "period": period, "hint": round(hint, 2),
            "beats": grid, "downbeats": grid[ph::4], "downbeat_phase": ph}


# ---------------------------------------------------------------- 2-5. variable map on the drum stem
def drum_features(drums: Path) -> tuple[np.ndarray, np.ndarray, float]:
    x = load_mono(drums, SR_DRUM)
    hop = HOP_DRUM
    fr = SR_DRUM / hop
    n = len(x) // hop
    if n < 4:
        raise SlopError("the drum stem is empty or too short to analyse")
    e = np.log1p((x[: n * hop].reshape(n, hop).astype(np.float64) ** 2).sum(1) * 1e3)
    flux = np.maximum(0, np.diff(e))
    flux -= flux.mean()
    k = load_mono(drums, SR_DRUM, af="lowpass=f=150")
    kn = len(k) // hop
    kick = (k[: kn * hop].reshape(kn, hop).astype(np.float64) ** 2).sum(1)
    return flux, kick, fr


def fit_window(flux: np.ndarray, fr: float, a: float, lo: float, hi: float, L: float = 20.0) -> tuple[float, float, float]:
    """Local (score, bpm, absolute phase) for the window [a, a + L) (vectorised port of beatmap.fit)."""
    seg = flux[int(a * fr):int((a + L) * fr)]
    best = (0.0, (lo + hi) / 2, a)
    if not len(seg):
        return best
    for bpm in np.arange(lo, hi, 0.05):
        per = 60 / bpm
        offs = np.arange(0, per, 0.004)
        n = int(np.ceil(L / per)) + 1
        tt = offs[:, None] + np.arange(n)[None, :] * per
        valid = tt < L
        idx = (tt * fr).astype(int)
        valid &= idx < len(seg)
        cnt = valid.sum(1)
        v = np.where(cnt > 0, (seg[np.where(valid, idx, 0)] * valid).sum(1) / np.maximum(cnt, 1), -np.inf)
        j = int(np.argmax(v))
        if v[j] > best[0]:
            best = (float(v[j]), float(bpm), float(a + offs[j]))
    return best


def variable_beats(flux: np.ndarray, fr: float, lo: float, hi: float) -> dict | None:
    T = len(flux) / fr
    pts = [(a + 10, *fit_window(flux, fr, a, lo, hi)) for a in np.arange(0, T - 20, 5)]
    if len(pts) < 2:
        return None
    tc = np.array([p[0] for p in pts])
    sc = np.array([p[1] for p in pts])
    bc = np.array([p[2] for p in pts])
    good = sc > np.percentile(sc, 20)
    if good.sum() < 1:
        good = np.ones(len(sc), bool)
    g05 = np.arange(0, T, 0.5)
    bm = np.interp(g05, tc[good], bc[good])
    bm = np.convolve(np.pad(bm, 10, mode="edge"), np.ones(21) / 21, mode="valid")

    def tempo_at(t: float) -> float:
        return float(np.interp(t, g05[:len(bm)], bm))

    fmax = flux.max()

    def snap(t: float) -> tuple[float, bool]:
        i0, i1 = int((t - .03) * fr), int((t + .03) * fr) + 1
        w = flux[max(0, i0):i1]
        if len(w) and w.max() > 0.15 * fmax:
            return (max(0, i0) + int(np.argmax(w))) / fr, True                 # snap to a real hit
        return t, False

    p1 = pts[1][3]
    start = p1 - np.floor((p1 - 0.0) / (60 / tempo_at(0))) * (60 / tempo_at(0))
    beats, snapped = [float(start)], [False]
    while beats[-1] < T - 0.2:
        t, ok = snap(beats[-1] + 60 / tempo_at(beats[-1]))
        beats.append(float(t))
        snapped.append(ok)
    # re-track the head: from the first 4 consecutive snapped beats, step back to the start snapping each beat
    # (only when the drums are there to snap to: a drumless intro keeps the forward extrapolation, which matched the
    # intro's mix onsets far better on the EV take - 1.20 vs 0.64 mean onset strength)
    lock = next((i for i in range(len(beats) - 3) if all(snapped[i:i + 4])), None)
    if lock and not all(snapped[:lock]):
        head, hits, t = [], 0, beats[lock]
        while t - 60 / tempo_at(t) >= 0:
            t, ok = snap(t - 60 / tempo_at(t))
            head.append(float(t))
            hits += ok
        if head and hits >= 0.5 * len(head):
            beats = head[::-1] + beats[lock:]
    return {"beats": np.array(beats), "tempo_at": tempo_at, "bm": bm, "T": T,
            "fits": [{"t": round(float(p[0]), 2), "bpm": round(float(p[2]), 2), "score": round(float(p[1]), 4),
                      "used": bool(g)} for p, g in zip(pts, good)]}


def window_max(env: np.ndarray, times, fr: float, pre: float = 0.01, post: float = 0.05) -> np.ndarray:
    """max of env (frame rate fr) over [t - pre, t + post] for each time t."""
    out = np.zeros(len(times))
    n = len(env)
    for j, t in enumerate(times):
        a = max(0, int(round((t - pre) * fr)))
        b = min(n, int(round((t + post) * fr)) + 1)
        out[j] = float(env[a:b].max()) if b > a else 0.0
    return out


def downbeat_vote(beats: np.ndarray, kick: np.ndarray, fr: float) -> tuple[int, list[int]]:
    kb = window_max(kick, beats, fr)
    phase = [int(np.argmax([kb[p + b:min(len(beats), b + 32):4].sum() for p in range(4)]))
             for b in range(0, len(beats), 32)]
    ph = max(set(phase), key=phase.count) if phase else 0
    return ph, phase


def harmony_vote(beats: np.ndarray, y: np.ndarray, sr: int) -> dict | None:
    """Where the chords change: chroma (CQT, 512 hop) of the harmonic stems synced to beats; novelty = cosine change
    from the previous beat; per 32-beat block the phase with the most change wins. Significant when the winning phase
    holds >= half the blocks and its total is >= 1.5 x the mean of the other phases (a static pad gives no answer)."""
    librosa = need_module("librosa", "downbeat analysis")
    if len(beats) < 16 or not len(y):
        return None
    C = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=512)
    bf = librosa.time_to_frames(beats, sr=sr, hop_length=512)
    bf = bf[bf < C.shape[1]]
    if len(bf) < 16:
        return None
    Cs = librosa.util.sync(C, bf, aggregate=np.median)[:, 1:]          # column j = [beat j, beat j + 1)
    Cn = Cs / (np.linalg.norm(Cs, axis=0, keepdims=True) + 1e-9)
    nov = np.zeros(Cn.shape[1])
    nov[1:] = 1 - (Cn[:, 1:] * Cn[:, :-1]).sum(0)
    tot = np.array([nov[p::4].sum() for p in range(4)])
    blocks = [int(np.argmax([nov[b + p:min(len(nov), b + 32):4].sum() for p in range(4)])) for b in range(0, len(nov), 32)]
    ph = int(np.argmax(tot))
    share = blocks.count(ph) / len(blocks)
    ratio = float(tot[ph] / (np.mean(np.delete(tot, ph)) + 1e-9))
    ok = share >= 0.5 and ratio >= 1.5 and float(np.mean(nov)) > 0.01
    return {"phase": ph, "blocks": blocks, "share": round(share, 3), "ratio": round(ratio, 2), "significant": bool(ok)}


def rms24(y: np.ndarray, sr: int, dur: float) -> list[float]:
    n = int(np.ceil(dur * 24))
    e = np.zeros(n, np.float32)
    hop = sr / 24
    for i in range(n):
        a, b = int(i * hop), int(min(len(y), (i + 1) * hop))
        if b > a:
            e[i] = np.sqrt(np.mean(y[a:b].astype(np.float64) ** 2))
    return np.round(e / (e.max() + 1e-12), 4).tolist()


def state_key(paths: Paths, cfg: dict) -> str:
    keys = {k: cfg.get(k) for k in ("tempo_range", "bpm_hint", "downbeat_phase", "beatgrid", "beat_pad0",
                                     "downbeat_method")}
    return f"v2|{fingerprint(paths.song, paths.stem('drums'))}|{sorted(keys.items(), key=str)}"


def base_key(paths: Paths, cfg: dict) -> str:
    """What the beats themselves depend on (not the bar phase): a change here needs a full rebuild."""
    keys = {k: cfg.get(k) for k in ("tempo_range", "bpm_hint", "beatgrid", "beat_pad0")}
    return f"v2|{fingerprint(paths.song, paths.stem('drums'))}|{sorted(keys.items(), key=str)}"


def downbeat_method(cfg: dict) -> str:
    dm = str(cfg.get("downbeat_method") or "kick").lower()
    if dm not in ("kick", "harmony", "auto"):
        raise SlopError(f"project.json audio.downbeat_method {dm!r}: use \"kick\" (default), \"harmony\" or \"auto\"")
    return dm


def decide_phase(cfg: dict, kick: dict, H: dict | None, pdir: Path | None = None) -> tuple[int, int, str, list[str]]:
    """(chosen phase, voted phase, method, notes) from the kick vote {phase, blocks, share}, the chord vote and
    project.json (audio.downbeat_method, audio.downbeat_phase)."""
    from .common import project_cmd

    def bars(rest: str) -> str:
        return project_cmd(pdir, f"song bars {rest}") if pdir is not None else f"slop song bars {rest}"
    notes: list[str] = []
    ph, blocks, kick_share = int(kick["phase"]), kick.get("blocks") or [], float(kick.get("share") or 0.0)
    dm = downbeat_method(cfg)
    if dm == "harmony" and H:
        analysis, how = H["phase"], "harmony"
    elif dm == "auto" and H and H["significant"]:
        analysis, how = H["phase"], "harmony"
    else:
        analysis, how = ph, "kick"
        if dm != "kick":
            notes.append("the chord-change vote gave no clear answer; the kick vote decided")
    if cfg.get("downbeat_phase") is not None:
        method, chosen = "project.json", int(cfg["downbeat_phase"]) % 4
        if chosen != analysis:
            notes.append(f"downbeat phase {chosen} from project.json (the {how} vote said {analysis})")
    else:
        method, chosen = how, analysis
        if how == "kick" and kick_share < 0.5:
            notes.append(f"the kick vote is split (phase {ph} won {kick_share:.0%} of 32-beat blocks: {blocks}); check that "
                         f"a drop or a chorus starts on a bar line, else `{bars('--phase N')}` (N = 0-3; "
                         f"`{bars('').rstrip()}` shows each phase)")
        other = H["phase"] if H and H["significant"] else None
        if other is not None and other != chosen:
            notes.append(f"second opinion: the chord changes fall on phase {other} ({H['share']:.0%} of blocks); if the "
                         f"bar lines feel off, try `{bars(f'--phase {other}')}` (`{bars('--phase auto')}` goes back)")
    return int(chosen), int(analysis), method, notes


PHASE_NOTE = ("downbeat phase ", "the kick vote is split", "second opinion:", "the chord-change vote gave no clear answer")


def apply_phase(pdir: Path) -> dict:
    """Re-decide the bar lines of an existing beats.json from its stored votes and the CURRENT project.json (after
    `slop song bars --phase N` wrote audio.downbeat_phase, or removed it): no audio work, a second. Falls back to a
    full build when the beat map is missing, out of date or uses the global grid."""
    paths = Paths(pdir)
    cfg = audio_cfg(pdir)
    B = read_json(paths.beats)
    votes = (B or {}).get("downbeat_votes") or {}
    st = state_get(paths, "beats")
    stale = not B or not votes.get("kick") or cfg.get("beatgrid") == "analysis" or st.get("base") != base_key(paths, cfg)
    if stale:
        return build(pdir, force=True)
    chosen, voted, method, notes = decide_phase(cfg, votes["kick"], votes.get("harmony"), pdir)
    beats = np.asarray(B["beats"], float)
    down = [round(float(b), 4) for b in beats[chosen::4]]
    moved = down != B.get("downbeats")
    B.update(downbeats=down, downbeat_phase=int(chosen), downbeat_vote=int(voted), downbeat_method=method)
    B["notes"] = [n for n in B.get("notes", []) if not n.startswith(PHASE_NOTE)] + notes
    if moved and B.get("sections"):
        B["sections"] = []
        B["notes"].append("the bars changed: sections cleared (`slop analyze` rebuilds them; `--steps sections` alone too)")
    write_json(paths.beats, B)
    state_set(paths, "beats", state_key(paths, cfg), base=base_key(paths, cfg))
    return {"status": "done" if moved else "up-to-date", "beats": len(beats), "downbeats": len(down),
            "downbeat_phase": int(chosen), "downbeat_method": method, "moved": moved, "notes": notes, "fast": True}


def build(pdir: Path, force: bool = False) -> dict:
    paths = Paths(pdir)
    cfg = audio_cfg(pdir)
    drums = paths.stem("drums")
    if not paths.song.exists():
        raise SlopError("no audio/song.wav - run `slop song ingest FILE` first")
    if not drums.exists():
        raise SlopError("no audio/stems/drums.wav - run `slop analyze --steps stems` first (the beat map reads the drum stem)")
    key = state_key(paths, cfg)
    if not force and paths.beats.exists() and state_get(paths, "beats").get("key") == key:
        return {"status": "up-to-date"}
    y = load_mono(paths.song, 44100)
    dur = len(y) / 44100
    hint = cfg.get("bpm_hint") or (float(np.mean(cfg["tempo_range"])) if cfg.get("tempo_range") else None)
    G = global_grid(y, 44100, hint)
    flux, kick, fr = drum_features(drums)
    lo, hi = cfg.get("tempo_range") or (G["bpm"] * .96, G["bpm"] * 1.04)
    lo, hi = float(lo), float(hi)
    V = None if cfg.get("beatgrid") == "analysis" else variable_beats(flux, fr, lo, hi)
    notes = []
    if V is None:
        beats = np.asarray(G["beats"], float)
        if cfg.get("beat_pad0"):
            beats = np.concatenate([[0.0], beats])
        if cfg.get("beatgrid") != "analysis":
            notes.append("song shorter than 25 s: used the global grid")
        fits, tempo = [], [{"t": 0.0, "bpm": G["bpm"]}]
        t_start = t_end = G["bpm"]
    else:
        beats = V["beats"]
        fits = V["fits"]
        tempo = [{"t": round(float(t), 2), "bpm": round(V["tempo_at"](t), 2)} for t in np.arange(0, V["T"], 5.0)]
        t_start, t_end = round(float(V["bm"][min(2, len(V["bm"]) - 1)]), 2), round(float(V["bm"][max(-3, -len(V["bm"]))]), 2)
    beats = beats[beats <= dur]                                    # no beat after the song ends
    ph, blocks = downbeat_vote(beats, kick, fr)
    kick_share = round(blocks.count(ph) / max(len(blocks), 1), 3)
    harm_src = [paths.stem(s) for s in ("other", "bass") if paths.stem(s).exists()]
    ys = [load_mono(x, 22050) for x in harm_src] or [load_mono(paths.song, 22050)]
    yh = sum(v[:min(len(u) for u in ys)] for v in ys)
    H = harmony_vote(beats, yh, 22050)
    votes = {"kick": {"phase": ph, "blocks": blocks, "share": kick_share}, "harmony": H}
    chosen, voted, method, pnotes = decide_phase(cfg, votes["kick"], H, pdir)
    notes += pnotes
    ph = chosen
    down = beats[ph::4]
    if cfg.get("beatgrid") == "analysis" and cfg.get("downbeat_phase") is None:
        down = np.asarray(G["downbeats"], float)
        ph = int(np.argmin(np.abs(beats - down[0]))) if len(down) else 0
    ib = np.diff(beats)
    out = {"duration": round(dur, 3), "beats": [round(float(b), 4) for b in beats],
           "downbeats": [round(float(b), 4) for b in down], "tempo": tempo, "sections": [], "source": "beatmap-v1",
           "bpm": round(float(60 / np.median(ib)), 3) if len(ib) else G["bpm"], "offset": round(float(beats[0]), 4) if len(beats) else 0.0,
           "tempo_start": t_start, "tempo_end": t_end, "downbeat_phase": int(ph), "downbeat_vote": int(voted),
           "downbeat_method": method, "downbeat_votes": votes,
           "phase_blocks": blocks, "tempo_range": [round(lo, 2), round(hi, 2)], "tempo_fits": fits,
           "global": {k: G[k] for k in ("bpm", "offset", "hint", "downbeat_phase")}, "rms24": rms24(y, 44100, dur),
           "notes": notes}
    if paths.beats.exists():                       # keep the sections only while the bars they were built on stand
        old = read_json(paths.beats, {}) or {}
        if old.get("sections") and old.get("downbeats") == out["downbeats"]:
            out["sections"] = old["sections"]
            if old.get("sections_from"):
                out["sections_from"] = old["sections_from"]
        elif old.get("sections"):
            notes.append("the bars changed: sections cleared (`slop analyze` rebuilds them; `--steps sections` alone too)")
    write_json(paths.beats, out)
    state_set(paths, "beats", key, base=base_key(paths, cfg))
    return {"status": "done", "beats": len(beats), "downbeats": len(down), "tempo_start": t_start, "tempo_end": t_end,
            "downbeat_phase": int(ph), "phase_blocks": blocks, "notes": notes}
