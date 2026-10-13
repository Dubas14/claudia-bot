"""Test helpers for the gen/sync modules: synthetic songs and takes, a tiny project, and a scripted fake HTTP session.

Everything is generated (tones, clicks, flat-colour images); no network, no paid calls.
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
FFMPEG = shutil.which("ffmpeg")

# ------------------------------------------------------------------------------------------- the synthetic song
LINES = ["Hello. Everyone.",
         "Sit up, darling, eyes out on the road.",
         "Here we go now, here it comes so fast.",
         "Lift off"]
WORDS = [  # (w, line, t0, t1)
    ("hello", 0, 7.50, 7.90), ("everyone", 0, 8.00, 8.60),
    ("sit", 1, 10.00, 10.30), ("up", 1, 10.35, 10.55), ("darling", 1, 10.60, 11.00), ("eyes", 1, 11.10, 11.35),
    ("out", 1, 11.40, 11.70), ("on", 1, 11.75, 11.90), ("the", 1, 11.95, 12.05), ("road", 1, 12.10, 12.60),
    ("here", 2, 13.40, 13.70), ("we", 2, 13.75, 13.85), ("go", 2, 13.90, 14.10), ("now", 2, 14.15, 14.70),
    ("here", 2, 14.80, 15.10), ("it", 2, 15.15, 15.25), ("comes", 2, 15.30, 15.55), ("so", 2, 15.58, 15.70),
    ("fast", 2, 15.75, 16.40),
    ("lift", 3, 18.00, 18.50), ("off", 3, 18.55, 19.40),
]
DURATION = 30.0
BPM = 120.0


def words_doc() -> dict:
    ws = [{"i": i, "w": w, "line": ln, "t0": a, "t1": b, "conf": .9, "src": "w2v"} for i, (w, ln, a, b) in enumerate(WORDS)]
    lines = []
    for li, text in enumerate(LINES):
        lw = [x for x in ws if x["line"] == li]
        lines.append({"line": li, "text": text, "t0": lw[0]["t0"], "t1": lw[-1]["t1"]})
    return {"words": ws, "lines": lines, "gaps": []}


def beats_doc() -> dict:
    bt = [round(i * 60 / BPM, 3) for i in range(int(DURATION * BPM / 60))]
    return {"duration": DURATION, "beats": bt, "downbeats": bt[::4], "tempo": [{"t": 0.0, "bpm": BPM}],
            "sections": [{"name": "verse1", "t0": 0.0, "t1": DURATION, "energy": .5}], "source": "beatmap-v1"}


def hits_doc() -> dict:
    bt = beats_doc()["beats"]
    return {"kick": bt[::2], "snare": bt[1::2], "hat": [], "hits": [], "risers": [], "fills": [], "vocal_entries": [],
            "env24": {}}


def syllable(n: int, f0: float, rng) -> np.ndarray:
    t = np.arange(n) / SR
    vib = 1 + .01 * np.sin(2 * np.pi * 5.5 * t)
    ph = 2 * np.pi * np.cumsum(f0 * vib) / SR
    s = sum((0.6 / h) * np.sin(h * ph + rng.uniform(0, 6)) for h in range(1, 7))
    env = np.minimum(1, t / .02) * np.minimum(1, np.maximum(0, (n / SR - t)) / .04)
    return (s * env).astype(np.float32)


def vocal_track(seed: int = 1, duration: float = DURATION, words=None) -> np.ndarray:
    """a 'vocal' with one tonal syllable per aligned word (random pitch per word), silence elsewhere."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(duration * SR), np.float32)
    for _, _, a, b in (words if words is not None else WORDS):
        i0, n = int(a * SR), int((b - a) * SR)
        seg = syllable(n, rng.uniform(170, 380), rng)
        if rng.random() < .3:
            m = min(n, int(.06 * SR)); seg[:m] += (rng.standard_normal(m) * .15).astype(np.float32)
        x[i0:i0 + n] += seg[: len(x) - i0]
    return (.3 * x / max(1e-9, np.abs(x).max())).astype(np.float32)


def babble(duration: float, seed: int) -> np.ndarray:
    """dense random 'singing' unrelated to the song (what a model sings when it stops copying)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(duration * SR), np.float32); t = .02
    while t < duration - .3:
        L = rng.uniform(.15, .4); n = int(L * SR); i0 = int(t * SR)
        x[i0:i0 + n] += syllable(n, rng.uniform(170, 380), rng)[: len(x) - i0]
        t += L + rng.uniform(.05, .2)
    return (.3 * x / max(1e-9, np.abs(x).max())).astype(np.float32)


def click_track(duration: float = DURATION) -> np.ndarray:
    x = np.zeros(int(duration * SR), np.float32)
    for b in beats_doc()["beats"]:
        i = int(b * SR); n = int(.03 * SR)
        x[i:i + n] += (np.exp(-np.arange(n) / (.005 * SR)) * np.sin(2 * np.pi * 60 * np.arange(n) / SR)).astype(np.float32)[: len(x) - i]
    return .4 * x


def write_wav(path: Path, x: np.ndarray, sr: int = SR, channels: int = 1) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    y = np.clip(x, -1, 1)
    if channels == 2:
        y = np.stack([y, y], -1).reshape(-1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return path


def make_mp4(path: Path, audio: Path | None, duration: float | None = None, size: str = "320x180", color: str = "gray") -> Path:
    """a small H.264 mp4 with a moving test pattern (distinct frames) and the given audio (AAC)."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    src = ["-f", "lavfi", "-i", f"testsrc2=s={size}:r=24" + (f":d={duration}" if duration else "")]
    cmd = [FFMPEG, "-v", "error", "-y", *src]
    if audio:
        cmd += ["-i", str(audio), "-shortest", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def png_bytes(color=(200, 80, 40), size=(64, 36)) -> bytes:
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", size, color).save(b, "PNG"); return b.getvalue()


def write_png(path: Path, color=(200, 80, 40), size=(64, 36)) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(png_bytes(color, size)); return path


# ------------------------------------------------------------------------------------------- the project
def make_project(root: Path, name: str = "demo", budget: dict | None = None, audio: bool = True, **extra) -> Path:
    p = Path(root) / name
    (p / "analysis").mkdir(parents=True, exist_ok=True)
    proj = {"name": name, "title": "Demo Song", "tier": "quick", "song": "audio/song.wav", "fps": 24, "size": [1920, 1080],
            "lead": {"canon": "black bob, one orange streak, star clip, headset mic", "far": "", "possessive": "her"},
            "look": {"mode": "native"}, "mj": {"params": "", "profile": ""},
            "models": {"image": "openai/gpt-image-2", "video": "bytedance/seedance-2.5"},
            "budget": budget or {"openrouter_usd": 40, "higgsfield_credits": 300, "confirm_over_usd": 2},
            "gates": {"board_approved": False, "prompts_approved": False, "v1_approved": False}, **extra}
    (p / "project.json").write_text(json.dumps(proj, indent=1), encoding="utf-8")
    (p / "analysis" / "words.json").write_text(json.dumps(words_doc()), encoding="utf-8")
    (p / "analysis" / "beats.json").write_text(json.dumps(beats_doc()), encoding="utf-8")
    (p / "analysis" / "hits.json").write_text(json.dumps(hits_doc()), encoding="utf-8")
    if audio:
        voc = vocal_track()
        write_wav(p / "audio" / "stems" / "vocals.wav", voc)
        write_wav(p / "audio" / "song.wav", voc + click_track(), channels=2)
    shots = {"version": 1, "duration": DURATION, "chapters": [], "seedance": [], "plates": [], "shots": [
        {"id": "s001", "t0": 0.0, "t1": 9.5, "section": "intro", "plate": "hall", "framing": "WS", "action": "",
         "camera": "", "motion_tier": "motion", "lead_on_screen": True},
        {"id": "s002", "t0": 10.0, "t1": 12.6, "section": "verse1", "plate": "hero-cu", "framing": "CU",
         "action": "facing the camera, singing with her eyes closed", "camera": "Locked camera, very slight push in",
         "motion_tier": "sung", "lead_on_screen": True},
        {"id": "s003", "t0": 13.4, "t1": 16.4, "section": "verse1", "plate": "hero-cu", "framing": "MCU", "action": "",
         "camera": "", "motion_tier": "sung", "lead_on_screen": True},
        {"id": "s004", "t0": 16.5, "t1": 21.0, "section": "verse1", "plate": "hall", "framing": "FS",
         "action": "walks toward the camera down the hall", "camera": "The camera moves back slowly",
         "motion_tier": "motion", "lead_on_screen": True}]}
    (p / "board").mkdir(exist_ok=True)
    (p / "board" / "shots.json").write_text(json.dumps(shots, indent=1), encoding="utf-8")
    write_png(p / "plates" / "cands" / "hero-cu" / "1.png", (200, 80, 40))
    write_png(p / "plates" / "cands" / "hero-cu" / "2.png", (40, 80, 200))
    write_png(p / "plates" / "cands" / "hall" / "1.png", (90, 90, 90))
    (p / "plates" / "picks.json").write_text(json.dumps({"hero-cu": {"file": "plates/cands/hero-cu/1.png", "cand_k": 1},
                                                          "hall": {"file": "plates/cands/hall/1.png", "cand_k": 1}}),
                                             encoding="utf-8")
    return p


# ------------------------------------------------------------------------------------------- fake HTTP
class FakeResp:
    def __init__(self, status: int = 200, json_body=None, content: bytes | None = None, headers: dict | None = None,
                 lines: list | None = None):
        self.status_code = status
        self.headers = headers or {}
        self._json = json_body
        self.content = content if content is not None else (json.dumps(json_body).encode() if json_body is not None else b"")
        self._lines = lines or []

    @property
    def text(self) -> str:
        return self.content.decode(errors="replace")

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json

    def iter_lines(self):
        yield from self._lines


class FakeSession:
    """routes: {(METHOD, url-substring): FakeResp | [FakeResp, ...] | callable(method, url, body) -> FakeResp}.
    A list is consumed in order (the last item repeats). Unmatched requests raise AssertionError."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[dict] = []

    def request(self, method, url, headers=None, data=None, timeout=None, stream=False):
        body = json.loads(data) if data else None
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "body": body})
        for (m, sub), resp in self.routes.items():
            if m == method and sub in url:
                if callable(resp) and not isinstance(resp, FakeResp):
                    return resp(method, url, body)
                if isinstance(resp, list):
                    return resp.pop(0) if len(resp) > 1 else resp[0]
                return resp
        raise AssertionError(f"unexpected request {method} {url}")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def write_cache(slop_home: Path) -> None:
    """put the fixture model listings into $SLOP_HOME/cache/openrouter as fresh caches."""
    import time
    src = Path(__file__).parent
    d = Path(slop_home) / "cache" / "openrouter"; d.mkdir(parents=True, exist_ok=True)
    for name in ("videos_models", "images_models", "models_all"):
        data = json.loads((src / f"{name}.json").read_text(encoding="utf-8"))
        (d / f"{name}.json").write_text(json.dumps({"fetched_at": time.time(), "data": data}), encoding="utf-8")
