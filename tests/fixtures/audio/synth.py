"""Synthetic songs for the audio tests: a drum stem with a tempo ramp (accented downbeat kicks, snares on 2 and 4, offbeat
hats), a bass stem, an "other" pad with a riser into a drop, and a vocal stem of harmonic tones in phrases.
No samples, no recordings - everything is generated here (deterministic seeds)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SR = 44100


def beat_times(dur: float, bpm0: float, bpm1: float, t_start: float = 0.5) -> np.ndarray:
    t = [t_start]
    while True:
        bpm = bpm0 + (bpm1 - bpm0) * min(1.0, t[-1] / dur)
        nxt = t[-1] + 60.0 / bpm
        if nxt > dur - 0.4:
            break
        t.append(nxt)
    return np.array(t)


def _add(y: np.ndarray, t: float, sig: np.ndarray) -> None:
    i = int(round(t * SR))
    if i >= len(y):
        return
    n = min(len(sig), len(y) - i)
    y[i:i + n] += sig[:n]


def kick(amp: float) -> np.ndarray:
    n = int(.12 * SR)
    tt = np.arange(n) / SR
    f = 50 + 90 * np.exp(-tt * 35)
    return (amp * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 22)).astype(np.float32)


def noise_burst(amp: float, dur: float, rng: np.random.Generator, highpass: int = 1) -> np.ndarray:
    n = int(dur * SR)
    x = rng.standard_normal(n + highpass)
    for _ in range(highpass):
        x = np.diff(x)
    tt = np.arange(n) / SR
    return (amp * x[:n] / (np.abs(x).max() + 1e-9) * np.exp(-tt * (6 / dur))).astype(np.float32)


def tone(dur: float, f0: float, amp: float, vib: float = 0.0) -> np.ndarray:
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = f0 * (1 + vib * np.sin(2 * np.pi * 5 * tt))
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = sum(np.sin(k * ph) / k for k in (1, 2, 3, 4))
    env = np.minimum(1, tt / .02) * np.minimum(1, (dur - tt) / .03)
    return (amp * y * env).astype(np.float32)


def make_song(dur: float = 40.0, bpm0: float = 120.0, bpm1: float = 124.0, phase: int = 1, drop_at: float = 20.0,
              vocal_phrases: list[tuple[float, float]] | None = None, seed: int = 7) -> dict:
    """-> {stems: {drums, bass, other, vocals}, mix, beats, downbeats, phase, drop_at, syllables: [(t0, t1)]}
    Beat i is a downbeat when (i - phase) % 4 == 0. Before drop_at the drums play at 40 % level and the bass is out."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    drums, bass, other, vocals = (np.zeros(n, np.float32) for _ in range(4))
    beats = beat_times(dur, bpm0, bpm1)
    downs = np.array([b for i, b in enumerate(beats) if (i - phase) % 4 == 0])
    drop_at = float(downs[int(np.argmin(np.abs(downs - drop_at)))])        # the drop lands on a downbeat
    for i, b in enumerate(beats):
        lvl = 0.4 if b < drop_at else 1.0
        down = (i - phase) % 4 == 0
        _add(drums, b, kick(lvl * (1.0 if down else 0.6)))
        if (i - phase) % 4 in (1, 3):
            _add(drums, b + 0.002, noise_burst(lvl * 0.35, 0.12, rng, 1))
        if i + 1 < len(beats):
            _add(drums, (b + beats[i + 1]) / 2, noise_burst(lvl * 0.12, 0.03, rng, 3))
        if b >= drop_at:
            _add(bass, b, tone(0.25, 55.0, 0.5))
    # pad: steady chord, a 3 s riser into the drop, louder after it
    tt = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * f * tt) for f in (220.0, 277.2, 329.6)) / 3
    gain = np.where(tt < drop_at - 3, 0.06, np.where(tt < drop_at, 0.06 + 0.3 * (tt - (drop_at - 3)) / 3, 0.25))
    other += (pad * gain).astype(np.float32)
    syll = []
    for p0, p1 in vocal_phrases or [(4.0, 7.0), (12.0, 15.5), (24.0, 27.0), (32.0, 35.0)]:
        t = p0
        k = 0
        while t + 0.25 <= p1:
            d = 0.22 + 0.08 * (k % 3)
            vocals_seg = tone(d, 196.0 * (1 + 0.12 * (k % 4)), 0.3, vib=0.01)
            _add(vocals, t, vocals_seg)
            syll.append((round(t, 3), round(t + d, 3)))
            t += d + 0.08
            k += 1
    mix = drums + bass + other + vocals
    peak = np.abs(mix).max()
    if peak > 0.95:
        s = 0.95 / peak
        drums, bass, other, vocals, mix = (x * s for x in (drums, bass, other, vocals, mix))
    return {"stems": {"drums": drums, "bass": bass, "other": other, "vocals": vocals}, "mix": mix, "beats": beats,
            "downbeats": downs, "phase": phase, "drop_at": drop_at, "syllables": syll}


def write_project(root: Path, song: dict | None = None, name: str = "synth", audio: dict | None = None) -> Path:
    """A minimal project folder (project.json, audio/song.wav, audio/stems/*.wav) for CLI tests."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from slop.audio.common import write_audio
    root.mkdir(parents=True, exist_ok=True)
    pj = {"name": name, "title": name.title()}
    if audio:
        pj["audio"] = audio
    (root / "project.json").write_text(json.dumps(pj), encoding="utf-8")
    if song is not None:
        write_audio(root / "audio" / "song.wav", np.stack([song["mix"], song["mix"]]), SR)
        for k, v in song["stems"].items():
            write_audio(root / "audio" / "stems" / f"{k}.wav", v, SR, codec="pcm_f32le")
    return root
