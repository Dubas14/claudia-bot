"""The voice as data: 24 fps log-spectrum frames of the vocal stem and of the mix -> analysis/spectrum.json
(engine: window.SPECTRUM; a "her voice as a line / a beam / the sea it moves" device). Optional analyze step `spectrum`.

Port of tools/spectrum.py, unchanged: frame i is centred on t = i / 24 s (a 4096-sample Hann window at 24 kHz, hop 1000);
band k sums the power between log-spaced edges 60 Hz ... 12 kHz (default 64 bands; a band narrower than a bin takes its
nearest bin); each byte = (dB - (ref - 72)) / 72 x 255 with ref = the stem's 99.7th-percentile band level, so one byte is
72/255 dB and an attenuation of A dB is a drop of A x 255/72 byte levels.
{fps: 24, n, bands, f: [band centre Hz], lo: 60, hi: 12000, range_db: 72, ref_db: {vocals, mix},
 vocals: base64(uint8 n x bands), mix: base64(uint8 n x bands)}
"""
from __future__ import annotations

import base64
from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import Paths, fingerprint, load_mono, state_get, state_set, write_json

SR, HOP, N, LO, HI, RANGE = 24000, 1000, 4096, 60.0, 12000.0, 72.0


def frames(x: np.ndarray, nb: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    pad = np.concatenate([np.zeros(N // 2, np.float32), x, np.zeros(N, np.float32)])
    need = (n - 1) * HOP + N if n else 0
    if len(pad) < need:
        pad = np.concatenate([pad, np.zeros(need - len(pad), np.float32)])
    edges = np.geomspace(LO, HI, nb + 1)
    f = np.fft.rfftfreq(N, 1 / SR)
    bins = [np.where((f >= edges[k]) & (f < edges[k + 1]))[0] for k in range(nb)]
    for k, b in enumerate(bins):
        if not len(b):
            bins[k] = np.array([int(np.argmin(np.abs(f - np.sqrt(edges[k] * edges[k + 1]))))])
    win = np.hanning(N).astype(np.float32)
    out = np.zeros((n, nb), np.float32)
    for i0 in range(0, n, 256):
        idx = np.arange(i0, min(n, i0 + 256))
        seg = pad[(idx * HOP)[:, None] + np.arange(N)[None, :]] * win
        pw = np.abs(np.fft.rfft(seg, axis=1)) ** 2
        out[idx] = np.stack([pw[:, b].sum(1) for b in bins], 1)
    return out, np.sqrt(edges[:-1] * edges[1:])


def encode(pw: np.ndarray) -> tuple[str, float]:
    db = 10 * np.log10(pw + 1e-12)
    ref = float(np.percentile(db, 99.7))
    q = np.clip((db - (ref - RANGE)) / RANGE * 255, 0, 255).round().astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode(), ref


def build(pdir: Path, bands: int = 64, force: bool = False) -> dict:
    paths = Paths(pdir)
    voc = paths.stem("vocals")
    if not voc.exists():
        raise SlopError("no audio/stems/vocals.wav - run `slop analyze --steps stems` first")
    out_p = paths.analysis / "spectrum.json"
    key = f"v1|{bands}|{fingerprint(paths.song, voc)}"
    if not force and out_p.exists() and state_get(paths, "spectrum").get("key") == key:
        return {"status": "up-to-date"}
    v, mix = load_mono(voc, SR), load_mono(paths.song, SR)
    dur = len(mix) / SR
    n = int(np.ceil(dur * 24))
    S: dict = {"fps": 24, "n": n, "bands": bands, "lo": LO, "hi": HI, "range_db": RANGE, "ref_db": {}}
    fc = None
    for name, x in (("vocals", v), ("mix", mix)):
        pw, fc = frames(x, bands, n)
        S[name], S["ref_db"][name] = encode(pw)
    S["f"] = [round(float(c), 1) for c in fc]
    write_json(out_p, S)
    state_set(paths, "spectrum", key)
    return {"status": "done", "frames": n, "bands": bands, "kb": out_p.stat().st_size // 1024}
