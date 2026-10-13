"""Synthetic projects for the board/edit tests: a variable-tempo beat map, sections, aligned words, hits, tiny images
and (when ffmpeg exists) tiny videos. Nothing here comes from a real song."""
from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

SECTIONS = [("intro", 0.0, 8.0), ("verse1", 8.0, 24.0), ("chorus1", 24.0, 40.0), ("drop", 40.0, 48.0),
            ("verse2", 48.0, 56.0), ("chorus2", 56.0, 68.0), ("outro", 68.0, 76.0)]
VERSE_WORDS = ["robots", "walk", "the", "line", "tonight", "again", "under", "lights"]
CHORUS_WORDS = ["we", "are", "so", "back", "now"]
CANON = ("a young woman in her mid-twenties with pale skin and light freckles, a glossy black bob with one clay-orange "
         "streak through the bangs")
FAR = "a young woman with a glossy black bob and one clay-orange streak"


def beat_grid(duration: float = 76.0, bpm0: float = 120.0, bpm1: float = 124.0, offset: float = 0.25) -> list[float]:
    beats, t = [], offset
    while t < duration - 0.05:
        beats.append(round(t, 4))
        bpm = bpm0 + (bpm1 - bpm0) * t / duration
        t += 60.0 / bpm
    return beats


def make_words(beats: list[float], sections=SECTIONS) -> tuple[list[dict], list[dict]]:
    """Lines start on (or 20 ms after) a beat; words every half beat, 0.22 s long."""
    words, lines = [], []
    li = 0
    i = 0
    for name, a, b in sections:
        if name.startswith("verse"):
            vocab, n_words, lines_per = VERSE_WORDS, 6, 4
        elif name.startswith("chorus"):
            vocab, n_words, lines_per = CHORUS_WORDS, 5, 3
        else:
            continue
        bs = [x for x in beats if a + 0.3 <= x < b - 0.5]
        step = max(1, len(bs) // lines_per)
        for k in range(lines_per):
            j = k * step
            if j >= len(bs):
                break
            t = bs[j] + 0.02
            ws = []
            for m in range(n_words):
                t0 = round(t + m * 0.26, 3)
                if t0 + 0.22 >= b - 0.1:
                    break
                ws.append({"i": i, "w": vocab[(m + k) % len(vocab)], "line": li, "t0": t0, "t1": round(t0 + 0.22, 3),
                           "conf": 0.9, "src": "w2v"})
                i += 1
            if not ws:
                continue
            words += ws
            lines.append({"line": li, "text": " ".join(w["w"] for w in ws).capitalize() + ".", "t0": ws[0]["t0"],
                          "t1": ws[-1]["t1"]})
            li += 1
    return words, lines


def write_json(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1), encoding="utf-8")


def make_project(root: Path, name: str = "synth", tier: str = "studio", motion_s: float | None = 60.0,
                 look: dict | None = None, mj: dict | None = None, banned=None, hits: bool = True,
                 duration: float = 76.0) -> Path:
    p = Path(root) / name
    p.mkdir(parents=True, exist_ok=True)
    proj = {"name": name, "title": "Synth Song", "tier": tier, "song": "audio/song.wav", "fps": 24, "size": [1920, 1080],
            "lead": {"canon": CANON, "far": FAR, "possessive": "her"},
            "look": look or {"mode": "native", "accent": "#D97757", "hero_plate": None},
            "mj": mj if mj is not None else {"params": "--ar 16:9 --v 8.2 --raw --hd", "profile": ""},
            "models": {"image": "openai/gpt-image-2"},
            "budget": {"openrouter_usd": 40, "higgsfield_credits": 300, "confirm_over_usd": 2,
                       **({"motion_s": motion_s} if motion_s is not None else {})},
            "gates": {"board_approved": False, "prompts_approved": False, "v1_approved": False}}
    if banned:
        proj["banned"] = banned
    write_json(p / "project.json", proj)
    beats = beat_grid(duration)
    down = beats[1::4]
    secs = [{"name": n, "t0": a, "t1": b, "energy": 0.5} for n, a, b in SECTIONS if a < duration]
    secs[-1]["t1"] = duration
    tempo = [{"t": t, "bpm": round(120 + 4 * t / duration, 2)} for t in range(0, int(duration), 5)]
    write_json(p / "analysis/beats.json", {"duration": duration, "beats": beats, "downbeats": down, "tempo": tempo,
                                           "sections": secs, "source": "beatmap-v1"})
    words, lines = make_words(beats)
    write_json(p / "analysis/words.json", {"words": words, "lines": lines, "gaps": []})
    if hits:
        write_json(p / "analysis/hits.json", {
            "kick": beats[::2], "snare": beats[1::2], "hat": [round(b + .12, 3) for b in beats],
            "hits": [{"t": s["t0"], "score": 0.8} for s in secs[1:]],
            "risers": [{"t0": 22.0, "t1": 24.0, "land": 24.0}], "fills": [{"t0": 39.5, "t1": 40.0}],
            "vocal_entries": [lines[0]["t0"]] if lines else [],
            "env24": {"drums": [0.5] * int(duration * 24), "vocals": [0.2] * int(duration * 24),
                      "bass": [0.3] * int(duration * 24), "mix": [0.4] * int(duration * 24)}})
    (p / "lyrics").mkdir(exist_ok=True)
    (p / "lyrics/lyrics.txt").write_text("\n".join(l["text"] for l in lines) + "\n", encoding="utf-8")
    return p


def load(p: Path, rel: str):
    return json.loads((Path(p) / rel).read_text(encoding="utf-8"))


def fill_todos(S: dict, framing: str = "MS") -> dict:
    """What the lead would do: write every TODO field."""
    fr = ["CU", "MS", "WS", "MCU", "EWS", "FS"]
    for i, sh in enumerate(S["shots"]):
        sh["set"] = "an empty white hall"
        sh["framing"] = fr[i % len(fr)] if framing == "cycle" else framing
        sh["action"] = "she turns to the lens on the downbeat"
        for k in ("mj_prompt", "img_prompt"):
            if k in sh and sh[k]:
                lead = "{lead}" if sh.get("lead_on_screen") else "an empty white hall"
                sh[k] = (f"medium shot of {lead}, standing in the left third of a vast white hall {sh['id']}, "
                         "the right third empty, soft light, fine grain")
        sh["notes"] = ""
        if sh["lines"]:
            sh["devices"] = [{"kind": "counter", "anchor": "screen", "params": {}, "key": "W"}]
    for c in S["seedance"]:
        c["prompt"] = "Close-up. The woman from @Image1 sings @Audio1, every word in time. Locked camera."
    for p in S["plates"]:
        p.pop("set", None)
    return S


def make_image(path: Path, w: int = 640, h: int = 360, color=(40, 90, 110), accent: bool = False, seed: int = 0) -> Path:
    from PIL import Image, ImageDraw
    import random
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), color)
    d = ImageDraw.Draw(im)
    for _ in range(30):
        x, y = rnd.randrange(w), rnd.randrange(h)
        c = tuple(max(0, min(255, v + rnd.randrange(-40, 40))) for v in color)
        d.rectangle([x, y, x + w // 8, y + h // 8], fill=c)
    if accent:
        d.rectangle([w // 3, h // 3, w // 2, h // 2], fill=(217, 119, 87))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_video(path: Path, seconds: float = 2.0, size: str = "320x180", fps: int = 24) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}",
                    "-t", f"{seconds}", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "18", str(path)], check=True)
    return path


def make_wav(path: Path, seconds: float = 4.0, sr: int = 8000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / sr))) for i in range(int(seconds * sr)))
        w.writeframes(frames)
    return path
