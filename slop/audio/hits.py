"""The song's sound events for camera moves and cuts -> analysis/hits.json (contract §4.4; the engine's window.HITS).

Port of tools/hits.py ("editing and camera should feel really synced to the beat or sound effects"), same constants:
  - analysis at 22,050 Hz, STFT N 2048, hop 256 (~11.6 ms), Hann;
  - drum voices from band-limited spectral flux of the DRUM STEM: kick 30-150 Hz; snare/clap .6 x flux(150 Hz-5 kHz) +
    .4 x flux(1.5-5 kHz); hat 6-16 kHz. Peaks: local maxima above max(moving median + k x 1.4826 x MAD over +-0.5 s,
    floor x the novelty's 97th percentile); kick k3 floor .35 gap .16 s; snare k3 floor .4 gap .16 s; hat k3 floor .3
    gap .08 s. A snare/hat onset within 45 ms of a kick is the kick's own broadband click and is dropped (the
    "kick click" rule, calibrated on a broadband kick) - see kick_click below;
  - hits_all: broadband mix flux peaks (k6, +-3 s, floor .55, >= 1 s apart), strength vs their 90th percentile;
  - hits (the REAL hits): 24 fps envelopes; score = max(d_mix, .9 d_drums, .7 d_bass), d = mean of the next 0.6 s minus
    the mean of the previous 1.5 s (ending 2 frames back); local maxima (+-12 frames) with score >= .22, snapped to the
    downbeat within 0.65 s (else the nearest beat), project.json audio.hits {"add": [[t, s]], "drop": [t]} applied
    (added s x .45; drops within .3 s), merged within 2 s keeping the stronger; score = min(1, raw / .45);
  - risers: (other + bass) envelope smoothed 12 frames, sliding 1.5 s least-squares slope; rising where slope x 36 > .15
    and r > .9; runs >= 1 s; "land" = the strongest real hit in [t0 + .5, t1 + 1.2], else the downbeat within .6 s of t1;
  - fills: the beat before every real hit with score >= .5, plus bars whose second half (16th steps 8-15, 4 bands)
    differs from the median of the previous 4 bars by > 9 while the drums keep playing (envelope > .3); merged;
  - vocal_entries: the vocal envelope crossing .06 after >= 9 frames (0.375 s) below;
  - env24: 24 fps RMS envelopes normalised to their 99.5th percentile: mix, drums, bass, other, vocals.
Changes: reads analysis/beats.json (not media/audio/beatmap.json); band energies are computed in STFT blocks (the
original built a 430 MB index matrix for a 5-minute song); the moving median/MAD is vectorised (same values).
kick_click (project.json audio.hits.kick_click: "auto" default | true | false): the original ALWAYS dropped snare/hat
onsets within 45 ms of a kick. That is right for a broadband kick (its click shows up as a "snare" on every kick) but
empties the snare list of a four-on-the-floor song with claps on 2 and 4 (every clap sits on a kick; measured: the
synthetic test song gave 0 snares through real Demucs stems). "auto" keeps the click rule but first looks for a
backbeat: per beat with a kick, the snare-band novelty divided by the kick-band novelty (each the max within 45 ms);
when the median of one beat parity (every other beat) is >= 1.25x the other's, the louder parity carries claps/snares
on the kick, and snare onsets on those beats are kept. true = the original rule, false = never drop.
hits.json "kick_click" = {mode, backbeat (parity or null), ratio, kept_on_kicks}.
Schema: contract keys kick, snare, hat, hits[{t, score}], risers[{t0, t1, land}], fills[{t0, t1}], vocal_entries, env24
plus kick_s, snare_s (0..1 strengths), hits_all, fps, duration. engine_assets.hits_obj() converts to the EV engine's
window.HITS keys (impact, impact_all, riser, ride, fill, vox_on, env).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import Paths, audio_cfg, fingerprint, load_mono, read_json, state_get, state_set, write_json

SR, HOP, N = 22050, 256, 2048


def stft_bands(x: np.ndarray, bands: dict[str, tuple[float, float]], block: int = 1024) -> dict[str, np.ndarray]:
    """log1p(|STFT| x 10) summed over each band's bins, frame by frame (blocked: bounded memory)."""
    n = 1 + (len(x) - N) // HOP if len(x) >= N else 0
    f = np.fft.rfftfreq(N, 1 / SR)
    masks = {k: (f >= lo) & (f < hi) for k, (lo, hi) in bands.items()}
    out = {k: np.zeros(n, np.float32) for k in bands}
    win = np.hanning(N).astype(np.float32)
    for i0 in range(0, n, block):
        idx = np.arange(i0, min(n, i0 + block))
        seg = x[(idx * HOP)[:, None] + np.arange(N)[None, :]] * win
        S = np.log1p(np.abs(np.fft.rfft(seg, axis=1)).astype(np.float32) * 10)
        for k, m in masks.items():
            out[k][idx] = S[:, m].sum(1)
    return out


def flux(e: np.ndarray) -> np.ndarray:
    d = np.diff(e, prepend=e[0] if len(e) else 0)
    d[d < 0] = 0
    return d


def _rolling_median_mad(x: np.ndarray, w: int, block: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    from numpy.lib.stride_tricks import sliding_window_view
    pad = np.pad(x, w, mode="edge")
    V = sliding_window_view(pad, 2 * w + 1)
    med = np.empty(len(x), np.float64)
    mad = np.empty(len(x), np.float64)
    for i0 in range(0, len(x), block):
        blk = V[i0:i0 + block]
        m = np.median(blk, axis=1)
        med[i0:i0 + block] = m
        mad[i0:i0 + block] = np.median(np.abs(blk - m[:, None]), axis=1)
    return med, mad + 1e-6


def peaks(novelty: np.ndarray, min_gap_s: float, k: float = 1.5, win_s: float = 0.5, floor: float = 0.3) -> np.ndarray:
    """Onsets: local maxima above max(moving median + k*1.4826*MAD, floor x the novelty's 97th percentile)."""
    if len(novelty) < 3:
        return np.zeros(0, int)
    w = max(3, int(win_s * SR / HOP))
    med, mad = _rolling_median_mad(novelty, w)
    thr = np.maximum(med + k * mad * 1.4826, floor * np.percentile(novelty, 97))
    out, last = [], -10 ** 9
    gap = int(min_gap_s * SR / HOP)
    for i in range(1, len(novelty) - 1):
        if novelty[i] > thr[i] and novelty[i] >= novelty[i - 1] and novelty[i] >= novelty[i + 1] and i - last >= gap:
            out.append(i)
            last = i
    return np.array(out, int)


def env24(x: np.ndarray, dur: float) -> np.ndarray:
    n = int(np.ceil(dur * 24))
    hop = SR / 24
    e = np.zeros(n, np.float32)
    for i in range(n):
        a = int(i * hop)
        b = int(min(len(x), a + hop))
        if b > a:
            e[i] = np.sqrt(np.mean(x[a:b].astype(np.float64) ** 2))
    return e / (np.percentile(e, 99.5) + 1e-9) if n else e


def real_hits(env: dict, beats: np.ndarray, downbeats: np.ndarray, extra: dict | None = None) -> list[dict]:
    n = len(env["mix"])
    pre_n, post_n = 36, 14
    cs = {k: np.concatenate([[0.0], np.cumsum(v, dtype=np.float64)]) for k, v in env.items()}

    def mean(k, i0, i1):
        i0, i1 = max(0, i0), min(n, i1)
        return (cs[k][i1] - cs[k][i0]) / (i1 - i0) if i1 > i0 else 0.0

    sc = np.zeros(n)
    for i in range(n):
        d = {k: mean(k, i, i + post_n) - mean(k, i - pre_n, i - 2) for k in ("mix", "drums", "bass")}
        sc[i] = max(d["mix"], .9 * d["drums"], .7 * d["bass"])
    out = []
    for i in range(n):
        if sc[i] < .22 or sc[i] < sc[max(0, i - 12):i + 13].max():
            continue
        t = i / 24
        if len(downbeats):
            j = int(np.argmin(np.abs(downbeats - t)))
            tt = downbeats[j] if abs(downbeats[j] - t) <= .65 else (beats[int(np.argmin(np.abs(beats - t)))] if len(beats) else t)
        else:
            tt = t
        out.append([float(tt), float(sc[i])])
    ex = extra or {}
    for t, s in ex.get("add", []):
        out.append([float(t), float(s) * .45])
    drop = ex.get("drop", [])
    out = [o for o in sorted(out) if not any(abs(o[0] - d) < .3 for d in drop)]
    merged: list[list[float]] = []
    for o in out:
        if merged and o[0] - merged[-1][0] < 2.0:
            if o[1] > merged[-1][1]:
                merged[-1] = o
        else:
            merged.append(o)
    return [{"t": round(t, 3), "score": round(min(1.0, s / .45), 3)} for t, s in merged]


def rides(risers: list[list[float]], hits: list[dict], downbeats: np.ndarray) -> list[dict]:
    out = []
    for r0, r1 in risers:
        cand = [x for x in hits if r0 + .5 <= x["t"] <= r1 + 1.2]
        if cand:
            land = max(cand, key=lambda x: x["score"])["t"]
        elif len(downbeats):
            j = int(np.argmin(np.abs(downbeats - r1)))
            land = float(downbeats[j]) if abs(downbeats[j] - r1) < .6 else r1
        else:
            land = r1
        out.append({"t0": r0, "t1": r1, "land": round(float(land), 3)})
    return out


def fills(Bf: list[np.ndarray], tt: np.ndarray, beats: np.ndarray, downbeats: np.ndarray, env_drums: np.ndarray,
          hits: list[dict]) -> list[dict]:
    """Bf: the four normalised band fluxes (30-150, 150-1500, 1500-5000, 6000-16000 Hz) of the drum stem."""
    def pat(b):
        t0 = downbeats[b]
        t1 = downbeats[b + 1] if b + 1 < len(downbeats) else t0 + (t0 - downbeats[b - 1])
        v = np.zeros((16, 4))
        for s in range(16):
            t = t0 + (t1 - t0) * s / 16
            lo, hi = np.searchsorted(tt, t - .03, "right"), np.searchsorted(tt, t + .03, "left")
            for k in range(4):
                v[s, k] = min(1.2, Bf[k][lo:hi].max()) if hi > lo else 0
        return v

    def drum(b):
        a = int(downbeats[b] * 24)
        z = int((downbeats[b + 1] if b + 1 < len(downbeats) else downbeats[b] + 1.8) * 24)
        e = env_drums[a:z]
        return float(np.mean(e)) if len(e) else 0.0

    out = []
    for x in hits:
        if x["score"] < .5:
            continue
        j = int(np.searchsorted(beats, x["t"] - 1e-3)) - 1
        if j >= 0:
            out.append([round(float(beats[j]), 3), x["t"]])
    if len(downbeats) > 5:
        P = [pat(b) for b in range(len(downbeats))]
        for b in range(4, len(downbeats) - 1):
            ref = np.median(np.stack(P[b - 4:b]), axis=0)
            late = np.abs(P[b][8:] - ref[8:]).sum()
            if late > 9 and min(drum(k) for k in range(b - 4, b + 2)) > .3:
                h = (downbeats[b + 1] - downbeats[b]) / 2
                out.append([round(float(downbeats[b] + h), 3), round(float(downbeats[b + 1]), 3)])
    out.sort()
    merged: list[list[float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1] + .05:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [{"t0": a, "t1": b} for a, b in merged]


def backbeat(kt: np.ndarray, snare_n: np.ndarray, kick_n: np.ndarray, beats: np.ndarray, tt: np.ndarray) -> dict:
    """Claps/snares ON the kick every other beat? -> {"parity": 0|1|None, "ratio"} (see kick_click in the docstring)."""
    r = {0: [], 1: []}
    for j, b in enumerate(beats):
        if not len(kt) or np.min(np.abs(kt - b)) > .045:
            continue
        lo, hi = np.searchsorted(tt, b - .045), np.searchsorted(tt, b + .045, "right")
        if hi <= lo:
            continue
        r[j % 2].append(float(snare_n[lo:hi].max()) / (float(kick_n[lo:hi].max()) + 1e-9))
    if min(len(r[0]), len(r[1])) < 4:
        return {"parity": None, "ratio": None}
    m0, m1 = float(np.median(r[0])), float(np.median(r[1]))
    hi_p = 0 if m0 >= m1 else 1
    ratio = max(m0, m1) / (min(m0, m1) + 1e-9)
    return {"parity": hi_p if ratio >= 1.25 else None, "ratio": round(ratio, 3)}


def analyse(drums, other, vocals, bass, mix, beats, downbeats, extra=None) -> dict:
    dur = len(mix) / SR

    def t(i):
        return np.round(np.asarray(i) * HOP / SR + N / (2 * SR), 3)

    DB = stft_bands(drums, {"kick": (30, 150), "sn1": (150, 5000), "sn2": (1500, 5000), "hat": (6000, 16000),
                            "mid": (150, 1500)})
    nfr = len(DB["kick"])
    tt = np.arange(nfr) * HOP / SR + N / (2 * SR)
    kick_n = flux(DB["kick"])
    snare_n = flux(DB["sn1"]) * 0.6 + flux(DB["sn2"]) * 0.4
    hat_n = flux(DB["hat"])
    ki = peaks(kick_n, .16, k=3, floor=.35)
    si = peaks(snare_n, .16, k=3, floor=.4)
    hi = peaks(hat_n, .08, k=3, floor=.3)
    kt = t(ki)

    def near_kick(idx):
        return np.array([len(kt) > 0 and np.min(np.abs(kt - t(i))) <= .045 for i in idx], bool)

    mode = (extra or {}).get("kick_click", "auto")
    bb = backbeat(kt, snare_n, kick_n, np.asarray(beats, float), tt)
    kept = 0
    if mode in (False, "false", "off", 0):
        pass
    elif mode in (True, "true", "on", 1) or bb["parity"] is None:
        si, hi = si[~near_kick(si)], hi[~near_kick(hi)]
    else:                                         # auto with a backbeat: keep the snares on the backbeat kicks
        bt = np.asarray(beats, float)
        on_bb = np.array([len(bt) > 0 and int(np.argmin(np.abs(bt - t(i)))) % 2 == bb["parity"] and
                          np.min(np.abs(bt - t(i))) <= .06 for i in si], bool)
        nk = near_kick(si)
        kept = int(np.sum(nk & on_bb))
        si, hi = si[~nk | on_bb], hi[~near_kick(hi)]
    broad = flux(stft_bands(mix, {"all": (0, SR)})["all"])
    ii = peaks(broad, 1.0, k=6, win_s=3.0, floor=.55)
    ref90 = np.percentile(broad[ii], 90) if len(ii) else 1.0
    hits_all = [{"t": float(t(i)), "score": round(float(min(1, broad[i] / (ref90 + 1e-9))), 3)} for i in ii]
    eo, eb = env24(other, dur), env24(bass, dur)
    m = np.convolve((eo + eb) / 2, np.ones(12) / 12, mode="same")
    L = 36
    xs = np.arange(L) - (L - 1) / 2
    rising = np.zeros(len(m), bool)
    for i in range(0, len(m) - L):
        seg = m[i:i + L]
        sl = float((xs * (seg - seg.mean())).sum() / (xs ** 2).sum())
        r = np.corrcoef(xs, seg)[0, 1] if seg.std() > 1e-6 else 0
        if sl * L > 0.15 and r > 0.9:
            rising[i:i + L] = True
    rs, run0 = [], None
    for i, v in enumerate(np.append(rising, False)):
        if v and run0 is None:
            run0 = i
        if not v and run0 is not None:
            if i - run0 >= 24:
                rs.append([round(run0 / 24, 3), round(i / 24, 3)])
            run0 = None
    ev = env24(vocals, dur)
    on, quiet = [], 0
    for i, v in enumerate(ev):
        if v < 0.06:
            quiet += 1
        else:
            if quiet >= 9:
                on.append(round(i / 24, 3))
            quiet = 0
    env = {"mix": env24(mix, dur), "drums": env24(drums, dur), "bass": eb, "other": eo, "vocals": ev}
    beats, downbeats = np.asarray(beats, float), np.asarray(downbeats, float)
    H = real_hits(env, beats, downbeats, extra)

    def bandn(e):
        fx = flux(e)
        return fx / (np.percentile(fx, 97) + 1e-9) if len(fx) else fx

    Bf = [bandn(DB[k]) for k in ("kick", "mid", "sn2", "hat")]

    def norm(v, idx):
        return (v[idx] / (np.percentile(v[idx], 95) + 1e-9)).clip(0, 1).round(3).tolist() if len(idx) else []

    return {"fps": 24, "duration": round(dur, 3), "kick": t(ki).tolist(), "kick_s": norm(kick_n, ki),
            "snare": t(si).tolist(), "snare_s": norm(snare_n, si), "hat": t(hi).tolist(), "hits": H,
            "hits_all": hits_all, "risers": rides(rs, H, downbeats), "fills": fills(Bf, tt, beats, downbeats, env["drums"], H),
            "vocal_entries": on, "env24": {k: np.round(v, 3).tolist() for k, v in env.items()},
            "kick_click": {"mode": str(mode), "backbeat": bb["parity"], "ratio": bb["ratio"], "kept_on_kicks": kept}}


def build(pdir: Path, force: bool = False) -> dict:
    paths = Paths(pdir)
    B = read_json(paths.beats)
    if not B:
        raise SlopError("no analysis/beats.json - run `slop analyze --steps beats` first")
    for s in ("drums", "other", "vocals", "bass"):
        if not paths.stem(s).exists():
            raise SlopError(f"no audio/stems/{s}.wav - run `slop analyze --steps stems` first")
    cfg = audio_cfg(pdir)
    key = (f"v2|{fingerprint(paths.song, *(paths.stem(s) for s in ('drums', 'other', 'vocals', 'bass')))}|"
           f"{state_get(paths, 'beats').get('key')}|{cfg.get('hits')}")
    if not force and paths.hits.exists() and state_get(paths, "hits").get("key") == key:
        return {"status": "up-to-date"}
    drums, other, vocals, bass = (load_mono(paths.stem(s), SR) for s in ("drums", "other", "vocals", "bass"))
    mix = load_mono(paths.song, SR)
    H = analyse(drums, other, vocals, bass, mix, B["beats"], B["downbeats"], cfg.get("hits"))
    write_json(paths.hits, H)
    state_set(paths, "hits", key)
    return {"status": "done", "kick": len(H["kick"]), "snare": len(H["snare"]), "hat": len(H["hat"]),
            "hits": len(H["hits"]), "hits_all": len(H["hits_all"]), "risers": len(H["risers"]), "fills": len(H["fills"]),
            "vocal_entries": len(H["vocal_entries"]), "kick_click": H["kick_click"]}
