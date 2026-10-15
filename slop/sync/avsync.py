"""avsync — where does a Seedance clip stop singing OUR audio?

Seedance 2.5 in reference mode ("@Image1 sings @Audio1") copies the reference audio into its own soundtrack almost
sample for sample, and the mouth follows its own soundtrack — so the lips match the song exactly as long as the clip's
audio IS the reference, and drift from the moment the model starts singing something else. The lip-sync check is
therefore an audio check: the clip's own audio against the reference it was conditioned on.

check(CLIP, REF, song_t0, ...) returns the global lag, the synced span, the divergence point (clip and song time), the
last beat / eighth before it (the cut), and short dips that recover. Two measures per 10 ms frame, at the global lag:
  wave  normalised cross-correlation of the waveforms (100 ms) — a verbatim copy scores 0.6–1.0
  mel   cosine of mean-removed log-mel frames (±50 ms) — also holds on fricatives, whose noise never correlates
        sample-wise; its threshold is calibrated against a null (ref shifted by non-beat offsets)
review(CLIP, REF, song_t0, out) renders the clip with our audio laid on (lag-corrected) and a burned-in marker from the
divergence on, to eyeball.

PORTED EXACTLY from the production pipeline's tools/avsync.py (calibrated on two shipped videos). Unchanged: 16 kHz mono,
10 ms frames (HOP 160), 64 ms FFT, 80 mels 50–7600 Hz, 70 dB floor, global lag search ±1.0 s, 100 ms wave NCC,
active = RMS > 10 % of p95 (clip or ref), mel smoothed over 11 frames, null offsets ±37/61/89/131 frames (avoid
eighth-note multiples), thr = null90 + 0.4·(matched_median − null90), match = active & (wave >= .4 | mel >= thr),
divergence = first 300 ms stretch (>= 60 % active, < 30 % matched) that never recovers with a 400 ms matched run,
tail rule (>= 80 ms of voice after the last match), synced_until = last match − 42 ms, spans bridged across silence and
<= .25 s of unmatched voice, spans < .5 s dropped, mode "copy" when global NCC > .2 (else "resynth"),
song = song_t0 + clip_t − lag, cut on the last beat / eighth (beats + midpoints) <= synced_until_song.

Intentional changes (generic toolkit):
  * beats and words are passed in (slop.sync.songdata.SongData) instead of read from a hard-wired project.
  * the diagnostic PNG is drawn with Pillow instead of matplotlib (same panels, colours and labels; no matplotlib
    dependency on the box); the title is "<project title> — LIP-SYNC = AUDIO CHECK" instead of a hard-coded video name.
  * the font is IBM Plex Mono (OFL) from engine/fonts when present, else Pillow's default font.
  * a take without an audio stream raises a clear SlopError (motion takes made with generate_audio false).
  * the PNG header names where the sync starts ("IN SYNC <synced_from> -> <synced_until> s", not "0 ->") and says
    "(not a copy)" when the global NCC is <= .2, so a late, short match never reads as a good take.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import numpy as np

from ..config import SlopError

SR, HOP, NFFT = 16000, 160, 1024          # 10 ms frames, 64 ms windows
FR = SR // HOP                            # frames per second
ACC, INK, PAPER = "#D97757", "#111111", "#F4F2EE"


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SlopError("ffmpeg is not installed or not on PATH (run bin/setup.sh, or install ffmpeg)")
    return exe


def load(p, sr=SR):
    p = pathlib.Path(p)
    if not p.is_file():
        raise SlopError(f"audio/video file not found: {p}")
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(p), "-map", "a:0", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace")[-300:]
        if "matches no streams" in err or "Stream map" in err:
            raise SlopError(f"{p.name} has no audio stream (a take made with generate_audio false): nothing to measure — "
                            "motion takes play at lag 0")
        raise SlopError(f"ffmpeg could not decode the audio of {p.name}: {err.strip()}")
    x = np.frombuffer(r.stdout, np.float32).copy()
    if not len(x):
        raise SlopError(f"{p.name} decoded to an empty audio track")
    return x


def mel_fb(n_mels=80, fmin=50, fmax=7600):
    hz2m = lambda f: 2595 * np.log10(1 + f / 700)  # noqa: E731
    m2hz = lambda m: 700 * (10 ** (m / 2595) - 1)  # noqa: E731
    pts = m2hz(np.linspace(hz2m(fmin), hz2m(fmax), n_mels + 2)); bins = np.fft.rfftfreq(NFFT, 1 / SR)
    fb = np.zeros((n_mels, len(bins)))
    for i in range(n_mels):
        l, c, r = pts[i:i + 3]
        fb[i] = np.clip(np.minimum((bins - l) / (c - l), (r - bins) / (r - c)), 0, None)
    return fb


def logmel(x, n):
    x = np.pad(x, (NFFT // 2, NFFT // 2 + n * HOP))
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(n)[:, None]
    S = np.abs(np.fft.rfft(x[idx] * np.hanning(NFFT), axis=1)) ** 2
    return 10 * np.log10(S @ mel_fb().T + 1e-10)                  # frames x mels, frame i centred at i*10 ms


def win_sum(x, w):                                                # centred moving sum, same length
    c = np.concatenate([[0], np.cumsum(x)]); h = w // 2; i = np.arange(len(x))
    return c[np.clip(i + h, 0, len(x))] - c[np.clip(i - h, 0, len(x))]


def global_lag(clip, ref, max_s=1.0):
    """samples by which the clip is later than the ref (clip[t] ~ ref[t - lag]) and the peak NCC."""
    n = 1 << int(np.ceil(np.log2(len(ref) + len(clip))))
    xc = np.fft.irfft(np.fft.rfft(clip, n) * np.conj(np.fft.rfft(ref, n)), n)
    lags = np.r_[np.arange(0, n // 2), np.arange(-n // 2, 0)]
    xc = np.where(np.abs(lags) <= max_s * SR, xc, -np.inf); k = int(np.argmax(xc))
    return int(lags[k]), float(xc[k] / np.sqrt((ref ** 2).sum() * (clip ** 2).sum() + 1e-12))


def on_clip(ref, lag, n):                                         # the ref placed on the clip's timeline
    r = np.zeros(n, np.float32)
    if lag >= 0:
        m = max(0, min(len(ref), n - lag)); r[lag:lag + m] = ref[:m]
    else:
        m = max(0, min(len(ref) + lag, n)); r[:m] = ref[-lag:-lag + m]
    return r


def unit_rows(M, floor_db=70):
    M = np.maximum(M, M.max() - floor_db); M = M - M.mean(1, keepdims=True)
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


def _beat_arrays(song):
    bt = np.array(song.beats() if song is not None else [], dtype=float)
    e8 = np.sort(np.r_[bt, (bt[:-1] + bt[1:]) / 2]) if len(bt) else bt
    return bt, e8


def check(clip_p, ref_p, song_t0=None, png=None, song=None, title: str = ""):
    """the sync measurement. `song` is a slop.sync.songdata.SongData (beats for the cut, words for labels) or None."""
    clip, ref = load(clip_p), load(ref_p)
    lag, gncc = global_lag(clip, ref)
    r = on_clip(ref, lag, len(clip)); n = len(clip) // HOP + 1
    t = np.arange(n) / FR
    # wave: windowed NCC at the global lag
    w = SR // 10; pad = lambda x: np.pad(x, (0, n * HOP - len(x)))[:n * HOP]  # noqa: E731
    cc, rr, pp = pad(clip), pad(r), pad(clip * r)
    num, ec, er = win_sum(pp, w)[::HOP][:n], win_sum(cc * cc, w)[::HOP][:n], win_sum(rr * rr, w)[::HOP][:n]
    wave = num / np.sqrt(ec * er + 1e-12)
    rms_c, rms_r = np.sqrt(ec / w), np.sqrt(er / w)
    active = (rms_c > .1 * np.percentile(rms_c, 95)) | (rms_r > .1 * np.percentile(rms_r, 95))
    # mel: cross-similarity of mean-removed log-mel frames; diagonal = at the global lag
    Mc, Mr = logmel(clip, n), logmel(r, n)
    A, B = unit_rows(Mc), unit_rows(Mr); C = A @ B.T                 # C[i, j] = sim(clip frame i, ref-on-clip frame j)
    sm = lambda x, k=11: np.convolve(np.nan_to_num(x), np.ones(k) / k, "same")  # noqa: E731
    mel = sm(np.diagonal(C).copy())
    null = []
    for k in (37, 61, 89, 131, -37, -61, -89, -131):              # offsets that avoid 8th-note multiples (~22.8 frames)
        d = np.full(n, np.nan); idx = np.arange(n); j = idx + k; ok = (j >= 0) & (j < n); d[ok] = C[idx[ok], j[ok]]
        null.append(sm(d)[active & ok])
    null = np.concatenate(null); null90 = float(np.percentile(null, 90)) if len(null) else .3
    sure = active & (wave > .6)
    if sure.sum() > 10:
        matched_med = float(np.median(mel[sure]))
    else:
        matched_med = float(np.percentile(mel[active], 75)) if active.any() else null90
    thr = null90 + .4 * (matched_med - null90)
    match = active & ((wave >= .4) | (mel >= thr))
    # local lag (mel), ±150 ms, ±100 ms context: where it wanders, the timing drifted
    D = 15; loc = np.zeros(n)
    for i in range(n):
        a0, a1 = max(0, i - 10), min(n, i + 11); best, bd = -9, 0
        for d in range(-D, D + 1):
            b0, b1 = a0 + d, a1 + d
            if b0 < 0 or b1 > n:
                continue
            s = np.mean(np.einsum("ij,ij->i", A[a0:a1], B[b0:b1]))
            if s > best:
                best, bd = s, d
        loc[i] = bd / FR * 1000
    # divergence: first 300 ms stretch of mostly-unmatched voice that never recovers (a 400 ms matched run)
    L, R = int(.3 * FR), int(.4 * FR); dips = []; div = None; i = 0
    first = int(np.argmax(match)) if match.any() else 0
    while i < n - L:
        seg = active[i:i + L]
        if seg.sum() >= .6 * L and match[i:i + L][seg].mean() < .3 and match[i]:
            i += 1; continue
        if seg.sum() >= .6 * L and match[i:i + L][seg].mean() < .3:
            run, rec = 0, None
            for j in range(i + L, n):
                run = run + 1 if match[j] else (run if not active[j] else 0)
                if run >= R:
                    rec = j - R + 1; break
            if rec is None:
                div = i; break
            dips.append((round(i / FR, 2), round(rec / FR, 2))); i = rec; continue
        i += 1
    if div is None:                                               # a tail too short for the window: voice after the last match
        good = np.where(match)[0]
        if len(good) and active[good[-1] + 1:].sum() >= int(.08 * FR):
            div = good[-1] + 1
    if div is not None:
        good = np.where(match[:div])[0]; until = (good[-1] + 1) / FR if len(good) else 0.0
    else:
        until = n / FR
    until_safe = max(0.0, until - .042) if div is not None else len(clip) / SR
    # in-sync spans: matched voice, bridged across silence and gaps <= 0.25 s; spans < 0.5 s are noise
    spans, i0, gap, last = [], None, 0, 0
    for i in range(n):
        if match[i]:
            i0 = i if i0 is None else i0; gap = 0; last = i
        elif active[i] and i0 is not None:
            gap += 1
            if gap > int(.25 * FR):
                spans.append((i0, last + 1)); i0, gap = None, 0
    if i0 is not None:
        spans.append((i0, last + 1))
    spans = [(a / FR, b / FR) for a, b in spans if (b - a) / FR >= .5]
    to_song = (lambda x: song_t0 + x - lag / SR) if song_t0 is not None else (lambda x: None)  # noqa: E731
    out = {"clip": str(clip_p), "ref": str(ref_p), "song_t0": song_t0, "lag_s": round(lag / SR, 4), "lag_ncc": round(gncc, 3),
           "mode": "copy" if gncc > .2 else "resynth", "thr_mel": round(thr, 3), "null90": round(null90, 3), "matched_med": round(matched_med, 3),
           "synced_from": round(first / FR, 2), "diverges": div is not None, "diverge_at": round(div / FR, 2) if div is not None else None,
           "synced_until": round(until_safe, 3), "dips": dips, "duration": round(len(clip) / SR, 3),
           "spans": [[round(a, 3), round(b, 3)] for a, b in spans]}
    if song_t0 is not None:
        out["spans_song"] = [[round(to_song(a), 3), round(to_song(b) - .042, 3)] for a, b in spans]
        bt, e8 = _beat_arrays(song); us = to_song(until_safe)
        out.update({"synced_until_song": round(us, 3), "diverge_at_song": round(to_song(div / FR), 3) if div is not None else None,
                    "cut_beat_song": float(bt[bt <= us].max()) if (bt <= us).any() else None,
                    "cut_eighth_song": float(e8[e8 <= us].max()) if (e8 <= us).any() else None})
        out["cut_eighth_clip"] = round(out["cut_eighth_song"] - song_t0 + lag / SR, 3) if out["cut_eighth_song"] else None
        if div is not None and song is not None:
            out["words_at_divergence"] = [w.get("w") for w in song.words_between(to_song(div / FR) - .15, to_song(div / FR) + .3)]
    out = _py(out)
    if png:
        figure(out, t, Mr, Mc, C, wave, mel, thr, null90, loc, active, match, lag, song_t0, png, song=song, title=title)
        out["png"] = str(png)
    return out


def _py(o):
    """numpy scalars -> plain Python numbers (values unchanged) so the result is JSON-clean."""
    if isinstance(o, dict):
        return {k: _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return type(o)(_py(v) for v in o) if isinstance(o, list) else tuple(_py(v) for v in o)
    if isinstance(o, np.generic):
        return o.item()
    return o


# ---------------------------------------------------------------------------------------------------------- figure
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    try:
        from ..config import engine_dir
        cands = (["IBMPlexMono-Medium.ttf"] if bold else []) + ["IBMPlexMono-Regular.ttf"]
        for name in cands:
            p = engine_dir() / "fonts" / name
            if p.is_file():
                return ImageFont.truetype(str(p), size)
    except Exception:
        pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                             # very old Pillow
        return ImageFont.load_default()


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#"); return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _gray_r(M, vmin, vmax):
    """matplotlib's gray_r: high values dark. M is rows x cols (row 0 drawn at the top)."""
    v = np.clip((M - vmin) / max(1e-9, vmax - vmin), 0, 1)
    return (255 * (1 - v)).astype(np.uint8)


def figure(o, t, Mr, Mc, C, wave, mel, thr, null90, loc, active, match, lag, song_t0, png, song=None, title: str = ""):
    """the diagnostic sheet (Pillow): our vocal, the clip's soundtrack, the match curves, local offset, cross-similarity."""
    from PIL import Image, ImageDraw
    W, H = 1650, 902                                              # 15 x 8.2 in at 110 dpi
    img = Image.new("RGB", (W, H), _rgb(PAPER))
    dr = ImageDraw.Draw(img)
    f_title, f_head, f_lab, f_small = _font(19, True), _font(14), _font(15), _font(12)
    ink, acc, grey = _rgb(INK), _rgb(ACC), (138, 138, 138)
    T = float(t[-1]) if len(t) else 1.0
    T = T or 1.0
    dv = o["diverge_at"]; us = o["synced_until"]
    # layout (gridspec 4 x 2, width ratios 2.35:1, heights 1:1:.9:.55, left .05, right .98, top .9, bottom .07)
    x0, x1, y0, y1 = int(.05 * W), int(.98 * W), int(.125 * H), int(.93 * H)
    gapx = int(.025 * W)
    lw = int((x1 - x0 - gapx) * 2.35 / 3.35)
    hr = [1, 1, .9, .55]; vgap = 46
    unit = (y1 - y0 - vgap * 3) / sum(hr)
    rows, yy = [], y0
    for h in hr:
        rows.append((yy, int(yy + h * unit))); yy = int(yy + h * unit) + vgap
    L0, L1 = x0, x0 + lw
    R0, R1 = L1 + gapx, x1

    def xmap(tt, a=L0, b=L1):
        return a + (b - a) * (tt / T)

    def frame(box, name):
        a, top, b, bot = box
        dr.text((a, top - 19), name, fill=ink, font=f_lab)
        dr.rectangle([a, top, b, bot], outline=ink, width=1)

    def mark(box):
        if dv is None:
            return
        a, top, b, bot = box
        xa = int(xmap(us, a, b))
        ov = Image.new("RGBA", (max(1, b - xa), bot - top), acc + (int(.13 * 255),))
        img.paste(Image.alpha_composite(img.crop((xa, top, xa + ov.size[0], bot)).convert("RGBA"), ov).convert("RGB"), (xa, top))
        dr.line([xa, top, xa, bot], fill=acc, width=2)

    def xticks(box, label=False):
        a, top, b, bot = box
        step = 1.0 if T <= 12 else (2.0 if T <= 30 else 5.0)
        k = 0.0
        while k <= T + 1e-6:
            x = xmap(k, a, b); dr.line([x, bot, x, bot + 4], fill=ink)
            dr.text((x - 6, bot + 5), f"{k:g}", fill=ink, font=f_small)
            k += step
        if label:
            dr.text(((a + b) / 2 - 40, bot + 20), "clip time (s)", fill=ink, font=f_small)

    vmax = float(max(Mr.max(), Mc.max()))
    for k, (M, name) in enumerate([(Mr, "OUR VOCAL (the reference the model was given, lag-aligned)"),
                                   (Mc, "THE CLIP'S OWN SOUNDTRACK (what the mouth follows)")]):
        top, bot = rows[k]; box = (L0, top, L1, bot)
        arr = _gray_r(M.T[::-1], vmax - 70, vmax)                 # mels x frames, low mels at the bottom
        im = Image.fromarray(arr, "L").resize((L1 - L0, bot - top), Image.NEAREST).convert("RGB")
        img.paste(im, (L0, top)); frame(box, name); mark(box)
        if k == 0 and song_t0 is not None and song is not None:
            right = -1                                             # stagger labels that would collide
            for wd in song.words_between(song_t0, song_t0 + T + 1):
                xw = wd["t0"] - song_t0 + lag / SR; lo = xw < right
                if 0 <= xw <= T:
                    txt = wd.get("w", ""); px = xmap(xw)
                    py = top + (bot - top) * (1 - (.72 if lo else .93))
                    bb = dr.textbbox((px, py), txt, font=f_small)
                    dr.rectangle([bb[0] - 2, bb[1] - 1, bb[2] + 2, bb[3] + 1], fill=_rgb(PAPER))
                    dr.text((px, py), txt, fill=ink, font=f_small)
                    if not lo:
                        right = xw + (len(txt) + 1) * .04 * T / 5
        xticks(box)
    # match curves
    top, bot = rows[2]; box = (L0, top, L1, bot)
    ylo, yhi = -.22, 1.05
    ymap = lambda v: bot - (bot - top) * ((v - ylo) / (yhi - ylo))  # noqa: E731
    ov = Image.new("RGBA", (L1 - L0, bot - top), (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    for i in range(len(t)):
        if not active[i]:
            xa = xmap(t[i]) - L0; od.line([xa, 0, xa, bot - top], fill=ink + (int(.05 * 255),), width=2)
    img.paste(Image.alpha_composite(img.crop((L0, top, L1, bot)).convert("RGBA"), ov).convert("RGB"), (L0, top))
    dr.line([(xmap(tt), ymap(v)) for tt, v in zip(t, np.clip(wave, -.2, 1))], fill=grey, width=1)
    dr.line([(xmap(tt), ymap(v)) for tt, v in zip(t, np.clip(mel, ylo, yhi))], fill=ink, width=2)
    xa = L0
    while xa < L1:                                                 # dashed threshold
        dr.line([xa, ymap(thr), min(L1, xa + 8), ymap(thr)], fill=ink, width=1); xa += 14
    lab = f"threshold {thr:.2f} (null p90 {null90:.2f})"
    bb = dr.textbbox((0, 0), lab, font=f_small)
    dr.text((L1 - (bb[2] - bb[0]) - 4, ymap(thr) - 16), lab, fill=ink, font=f_small)
    for i in np.where(active & ~match)[0]:
        x, y = xmap(t[i]), ymap(-.15); dr.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=acc)
    frame(box, "DOES THE CLIP STILL SING OUR AUDIO?"); mark(box)
    lx = L0 + dr.textbbox((0, 0), "DOES THE CLIP STILL SING OUR AUDIO?", font=f_lab)[2] + 24   # legend on the title line,
    ly = top - 17                                                                            # clear of the no-match dots
    for colr, name in ((grey, "waveform match (verbatim copy)"), (ink, "spectral match"), (acc, "no match")):
        dr.line([lx, ly + 7, lx + 18, ly + 7], fill=colr, width=2); dr.text((lx + 22, ly), name, fill=ink, font=f_small)
        lx += 30 + dr.textbbox((0, 0), name, font=f_small)[2]
    xticks(box)
    # local timing offset
    top, bot = rows[3]; box = (L0, top, L1, bot)
    ymap2 = lambda v: bot - (bot - top) * ((v + 160) / 320)  # noqa: E731
    dr.line([L0, ymap2(0), L1, ymap2(0)], fill=ink, width=1)
    seg = []
    for i in range(len(t)):
        if active[i]:
            seg.append((xmap(t[i]), ymap2(float(np.clip(loc[i], -160, 160)))))
        elif seg:
            if len(seg) > 1:
                dr.line(seg, fill=ink, width=1)
            seg = []
    if len(seg) > 1:
        dr.line(seg, fill=ink, width=1)
    frame(box, "LOCAL TIMING OFFSET (ms)"); mark(box); xticks(box, label=True)
    # cross-similarity (right column, all rows)
    top, bot = rows[0][0], rows[3][1]
    side = min(R1 - R0, bot - top)
    arr = _gray_r(C[::-1], 0, 1)                                   # origin lower: clip frame 0 at the bottom
    im = Image.fromarray(arr, "L").resize((side, side), Image.NEAREST).convert("RGB")
    img.paste(im, (R0, top))
    dr.rectangle([R0, top, R0 + side, top + side], outline=ink, width=1)
    dr.text((R0, top - 38), "CROSS-SIMILARITY", fill=ink, font=f_lab)
    dr.text((R0, top - 19), "clip (y) x our vocal (x): the diagonal is 'in sync'", fill=ink, font=f_small)
    if dv is not None:
        yu = top + side - side * (us / T); xu = R0 + side * (us / T)
        dr.line([R0, yu, R0 + side, yu], fill=acc, width=2)
        yy = top
        while yy < top + side:
            dr.line([xu, yy, xu, min(top + side, yy + 3)], fill=acc, width=1); yy += 7
    dr.text((R0 + side / 2 - 50, top + side + 6), "our vocal (s)", fill=ink, font=f_small)
    # header
    s = o.get("synced_until_song")
    words = " ".join(x for x in (o.get("words_at_divergence") or []) if x)
    sf = float(o.get("synced_from") or 0.0)
    head = (f"{pathlib.Path(o['clip']).name}  ·  lag {o['lag_s'] * 1000:+.0f} ms  ·  copy NCC {o['lag_ncc']:.2f}"
            + ("" if o["lag_ncc"] > .2 else " (not a copy)") + "  ·  "
            + ((f"IN SYNC {sf:.2f} -> {us:.2f} s" if us - sf >= .05 else "NEVER IN SYNC")
               + (f" (song {s:.2f} s)" if s and us - sf >= .05 else "") + f", DIVERGES at {dv:.2f} s"
               + (f" in '{words}'" if words else "")
               + (f"  ·  cut on the eighth at song {o['cut_eighth_song']:.2f} s" if o.get("cut_eighth_song") else "")
               if dv is not None else f"IN SYNC {sf:.2f} s -> the end"))
    name = (title.upper() + " — " if title else "") + "LIP-SYNC = AUDIO CHECK"
    dr.text((x0, int(.008 * H)), name, fill=ink, font=f_title)
    dr.text((x0, int(.038 * H)), head, fill=ink, font=f_head)
    pathlib.Path(png).parent.mkdir(parents=True, exist_ok=True)
    img.save(png)


# ---------------------------------------------------------------------------------------------------------- review
def review(clip_p, ref_p, song_t0, out, audio=None, song=None):
    """the clip with our audio laid on (lag-corrected) and a burned-in marker from the divergence on."""
    o = check(clip_p, ref_p, song_t0, song=song); lag = o["lag_s"]; us = o["synced_until"]
    src = audio or ref_p; start = (song_t0 - lag) if audio else None
    ain = ["-ss", f"{start:.3f}", "-i", str(src)] if audio else ["-i", str(src)]
    af = "[1:a]aresample=48000,apad[a]" if audio else (f"[1:a]adelay={int(lag * 1000)}:all=1,aresample=48000,apad[a]" if lag > 0
                                                       else f"[1:a]atrim=start={-lag:.4f},asetpts=PTS-STARTPTS,aresample=48000,apad[a]")
    fs = 34
    font = None
    try:
        from ..config import engine_dir
        p = engine_dir() / "fonts" / "IBMPlexMono-Regular.ttf"
        font = str(p) if p.is_file() else None
    except Exception:
        pass
    if font:  # filtergraph syntax: forward slashes, and the drive colon escaped (E:\x -> E\:/x on Windows)
        font = font.replace("\\", "/").replace(":", "\\:")
    ff = (f"fontfile='{font}':" if font else "")

    def dt(text, en, fc, bc, y):
        return (f"drawtext={ff}text='{text}':fontsize={fs}:fontcolor={fc}:box=1:boxcolor={bc}:boxborderw=12:x=40:y={y}:enable='{en}'")
    vf = ",".join([
        f"drawtext={ff}text='%{{pts\\:hms}}':fontsize={fs}:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=10:x=w-tw-40:y=40",
        dt("OUR AUDIO · IN SYNC", f"lt(t,{us:.3f})", "black", "white@0.9", 40),
        dt(f"DIVERGED at {us:.2f}s · CUT HERE", f"gte(t,{us:.3f})", "white", "0xD97757@0.95", 40) if o["diverges"] else "null",
    ])
    r = subprocess.run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(clip_p), *ain, "-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]",
                        "-map", "[a]", "-t", f"{o['duration']:.3f}", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-b:a", "192k", str(out)], capture_output=True)
    if r.returncode:
        raise SlopError("ffmpeg review render failed: " + r.stderr.decode(errors="replace")[-400:])
    o["review"] = str(out)
    return o


def dumps(o: dict) -> str:
    return json.dumps(o, indent=1)
