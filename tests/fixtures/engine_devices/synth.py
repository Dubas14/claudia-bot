"""A synthetic project for the engine-devices tests (shots.js + engine/src/devices/**). Everything is generated:

  * an ACCELERATING beat map (120 → 126 BPM over 30 s; never a fixed BPM), downbeats, sections
  * nine lyric lines whose words sit OFF the beat grid (engine/lyrics.js, the export format)
  * hits in the toolkit contract form (analysis/hits.json: kicks, snares, hits, risers, fills, env24)
  * four gradient plates with a dark "subject" disc (three with a radial depth map, one flat) + detection boxes — or, with
    boxes=False, NO boxes and no clip track (what `slop edit export` really writes): the subject then comes from the depth
    map, from a shot's subject_uv (s08, the flat plate), or is missing (the clip shots s03/s12: warnings)
  * one 24-frame clip (a disc moving across) with a 12 fps track
  * a 13-shot storyboard (board/shots.json) that exercises every type mode, many devices, every treatment family, the
    transition presets, the element budget (three heroes / five CV marks at once), the flash rule (a flash every 16th),
    a repeated treatment and a repeated transition (both must be rotated / demoted), and a hole at the end (gap scene)

    build(root: Path, hits_json=True, look="native", boxes=True, tweak=None) -> dict   # writes the project; returns {"dir", "shots",
                                                                                     # "beats", "lines"}; tweak(shots) edits the board
    (hits_json=False leaves out analysis/hits.json: H keys and camera moves fall back to the beat map; look="print" tests the
    print look's light grounds and ink)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DUR = 30.0


def beat_map() -> tuple[list[float], list[float]]:
    beats, t = [], 0.5
    while t < DUR:
        beats.append(round(t, 4))
        bpm = 120.0 + 6.0 * t / DUR
        t += 60.0 / bpm
    return beats, beats[::4]


def _shot_bounds(beats: list[float]) -> list[tuple[float, float]]:
    idx = list(range(0, 53, 4))                      # 13 shots of 4 beats each (s01 starts at 0, not at the first beat)
    out = []
    for k in range(len(idx) - 1):
        a = 0.0 if k == 0 else beats[idx[k]]
        out.append((a, beats[idx[k + 1]]))
    return out


LINES = ["This voice is a test", "Thirteen boxes humming all night", "Twenty parked in the rain", "Tie the rope down tight",
         "Half the budget in tokens", "The tide rose up", "Do not stop", "Every word on time", "Closer"]


def lyrics(bounds: list[tuple[float, float]]) -> list[dict]:
    out = []
    for i, text in enumerate(LINES):
        a, _ = bounds[i if i < 4 else i + 1]          # lines 0-3 in shots 1-4, lines 4-8 in shots 6-10 (shot 5 is instrumental)
        t, toks = a + 0.37 + 0.013 * i, []
        for w in text.split():
            toks.append({"txt": w, "t0": round(t, 3), "t1": round(t + 0.24, 3), "st": "", "n": 1})
            t += 0.31 + 0.017 * (len(toks) % 3)
        out.append({"line": i, "kind": "lyric", "text": text, "t0": toks[0]["t0"], "t1": toks[-1]["t1"], "tokens": toks})
    return out


def hits(beats: list[float]) -> dict:
    n = int(DUR * 24)
    env = lambda f, ph: [round(0.5 + 0.45 * math.sin(i / 24 * f + ph) * math.exp(-((i / 24) % 0.5) * 3), 4) for i in range(n)]
    return {"kick": beats[:], "snare": beats[1::2], "hat": [round((a + b) / 2, 4) for a, b in zip(beats, beats[1:])],
            "hits": [{"t": beats[20], "score": 0.9}, {"t": beats[40], "score": 1.0}],
            "risers": [{"t0": beats[14], "t1": beats[20], "land": beats[20]}], "fills": [{"t0": beats[30], "t1": beats[32]}],
            "vocal_entries": [], "env24": {"drums": env(9.0, 0.0), "vocals": env(5.0, 1.0), "bass": env(3.0, 2.0), "other": env(2.0, 0.5)}}


PLATES = {  # name: (top colour, bottom colour, subject u, v, radius, depth)
    "p-a": ((214, 112, 72), (40, 24, 60), .64, .48, .30, True),
    "p-b": ((40, 92, 168), (230, 214, 190), .30, .52, .28, True),
    "p-c": ((22, 70, 52), (210, 220, 120), .52, .45, .24, True),
    "p-flat": ((120, 120, 128), (230, 226, 210), .45, .5, .26, False),
}
SIZE = (960, 540)


def _plate(top, bot, u, v, r):
    from PIL import Image, ImageDraw, ImageFilter
    w, h = SIZE
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        k = y / (h - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3)))
    img = grad.resize(SIZE)
    disc = Image.new("L", SIZE, 0)
    ImageDraw.Draw(disc).ellipse([u * w - r * h, v * h - r * h, u * w + r * h, v * h + r * h], fill=255)
    disc = disc.filter(ImageFilter.GaussianBlur(4))
    return Image.composite(Image.new("RGB", SIZE, (18, 16, 20)), img, disc)


def _depth(u, v, r):
    from PIL import Image
    w, h = SIZE[0] // 4, SIZE[1] // 4
    img = Image.new("L", (w, h))
    for y in range(h):
        for x in range(w):
            d = math.hypot(x / w - u, (y / h - v) * h / w) / (r * h / w * 1.4)
            img.putpixel((x, y), int(255 * max(.12, min(1.0, 1.05 - .75 * d)) * (.55 + .45 * y / h)))
    return img


def _boxes(u, v, r):
    rw, rh = r * SIZE[1] / SIZE[0], r
    return {"a woman": [round(u - rw, 4), round(v - rh, 4), round(2 * rw, 4), round(2 * rh, 4), 0.93],
            "a face": [round(u - rw * .4, 4), round(v - rh * .9, 4), round(rw * .8, 4), round(rh * .6, 4), 0.9],
            "a phone": [0.08, 0.7, 0.1, 0.16, 0.6]}


def build(root: Path, hits_json: bool = True, look: str = "native", boxes: bool = True, tweak=None) -> dict:
    from PIL import Image, ImageDraw
    root = Path(root)
    eng = root / "engine"
    (eng / "assets" / "plates").mkdir(parents=True, exist_ok=True)
    for d in ("analysis", "board", "edit", "plates"):
        (root / d).mkdir(parents=True, exist_ok=True)
    beats, downbeats = beat_map()
    bounds = _shot_bounds(beats)
    secs = [("intro", 0, 4), ("verse", 4, 10), ("chorus", 10, 16), ("verse", 16, 20), ("chorus", 20, 26), ("outro", 26, DUR)]
    (root / "project.json").write_text(json.dumps({"name": "devtest", "title": "Device Test", "tier": "quick", "song": "audio/song.wav", "fps": 24,
        "size": [1920, 1080], "look": {"mode": look, "accent": "#D97757"}, "lead": {"canon": "", "far": "", "possessive": ""},
        "gates": {"board_approved": True, "prompts_approved": False, "v1_approved": False}}, indent=1), encoding="utf-8")
    (root / "analysis" / "beats.json").write_text(json.dumps({"duration": DUR, "beats": beats, "downbeats": downbeats,
        "tempo": [{"t": 0, "bpm": 120}, {"t": DUR, "bpm": 126}], "sections": [{"name": n, "t0": a, "t1": b, "energy": .5} for n, a, b in secs],
        "source": "synthetic"}), encoding="utf-8")
    if hits_json:
        (root / "analysis" / "hits.json").write_text(json.dumps(hits(beats)), encoding="utf-8")
    lyr = lyrics(bounds)
    (eng / "lyrics.js").write_text("window.LYR = " + json.dumps(lyr) + ";\n", encoding="utf-8")
    meta = {}
    for name, (top, bot, u, v, r, dep) in PLATES.items():
        _plate(top, bot, u, v, r).save(eng / "assets" / "plates" / f"{name}.jpg", quality=90)
        m = {"boxes": _boxes(u, v, r) if boxes else {}, "w": SIZE[0]}
        if dep:
            _depth(u, v, r).save(eng / "assets" / "plates" / f"{name}.depth.png")
            m.update(subject_depth=.86, depth_model="depth-anything-v2-small")
        else:
            m["depth"] = False
        meta[name] = m
    (eng / "plates.js").write_text("window.PLATES = " + json.dumps(meta) + ";\n", encoding="utf-8")
    # the clip: a disc travelling left → right over 24 frames, with its track
    cdir = eng / "assets" / "clips" / "c1"
    cdir.mkdir(parents=True, exist_ok=True)
    track = []
    for i in range(24):
        im = Image.new("RGB", (480, 270), (30 + i * 4, 40, 70))
        u = .2 + .6 * i / 23
        ImageDraw.Draw(im).ellipse([u * 480 - 50, 85, u * 480 + 50, 185], fill=(230, 200, 170))
        im.save(cdir / f"f{i + 1:05d}.jpg", quality=85)
    for k in range(12):
        u = .2 + .6 * (k * 2) / 23
        track.append([round(u - 50 / 480, 4), round(85 / 270, 4), round(100 / 480, 4), round(100 / 270, 4), 0.9])
    (eng / "clips.js").write_text("window.CLIPS = " + json.dumps({"c1": {"n": 24, "fps": 24, "dir": "assets/clips/c1"}}) + ";\n"
                                  + ("window.TRACK = " + json.dumps({"c1": {"a woman": track, "a face": track}}) + ";\n" if boxes else ""), encoding="utf-8")
    shots = storyboard(bounds)
    if tweak:                         # a test's variant of the storyboard (mutates the list of shot dicts)
        tweak(shots)
    if not boxes:                     # the flat plate's shot names its subject by hand (image space u, v, w, h)
        next(sh for sh in shots if sh["id"] == "s08")["subject_uv"] = [0.33, 0.28, 0.24, 0.46]
    (root / "board" / "shots.json").write_text(json.dumps({"version": 1, "duration": DUR, "chapters": [{"id": "I", "name": "the test", "t0": 0, "t1": 14},
        {"id": "II", "name": "the budget", "t0": 14, "t1": DUR}], "shots": shots}, indent=1), encoding="utf-8")
    edl = {}
    plate_of = {"s01": "p-a", "s02": "p-b", "s04": "p-c", "s05": "p-a", "s06": "p-b", "s08": "p-flat", "s09": "p-c", "s10": "p-a", "s11": "p-b", "s13": "p-c"}
    for sh in shots:
        if sh["id"] in ("s03", "s12"):
            edl[sh["id"]] = {"segs": [{"t0": sh["t0"], "clip": "c1", "in": 0.0}]}
        elif sh["id"] in plate_of:
            edl[sh["id"]] = {"plate": plate_of[sh["id"]]}
    (root / "edit" / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    return {"dir": root, "shots": shots, "beats": beats, "lines": lyr}


def storyboard(bounds: list[tuple[float, float]]) -> list[dict]:
    S = []

    def shot(i, **kw):
        a, b = bounds[i]
        d = {"id": f"s{i + 1:02d}", "t0": round(a, 4), "t1": round(b, 4), "section": "verse", "lines": [], "lead_on_screen": True, "framing": "MS",
             "camera": "slow push in", "type": [], "devices": []}
        d.update(kw)
        S.append(d)

    shot(0, section="intro", lines=[0], treatment="layers", type=[{"line": 0, "mode": "coverline", "placement": "left", "kicker": "THE VOICE", "micro": ["SRC · TEST"]}],
         devices=[{"kind": "ui.chip", "key": "W", "params": {"word": "voice", "text": "LIVE", "full": "LIVE · REQUESTS OPEN", "full_at": {"beats": 2}}},
                  {"kind": "cv.bracket", "anchor": {"box": "a face"}, "key": "B", "params": {"label": "FACE", "conf": .98, "style": "det", "chip": True}}])
    shot(1, lines=[1], treatment="relight", transition_in="whip left", type=[{"line": 1, "mode": "subtitle"}],
         devices=[{"kind": "terminal", "key": "W", "params": {"word": "boxes"}},
                  {"kind": "sparkline", "key": "B", "params": {"beat": 0}},
                  {"kind": "counter", "key": "B", "params": {"beat": 2, "from": 0, "to": 13, "beats": 1, "label": "BOXES"}}])
    shot(2, lines=[2], framing="CU", transition_in="flash cut", type=[{"line": 2, "mode": "coverline"}, {"line": 2, "mode": "masthead", "words": [0, 0], "placement": "right"}],
         devices=[{"kind": "cv.tag", "anchor": {"box": "a woman"}, "key": "W", "params": {"word": "parked", "rows": ["CAR 01 · PARKED"]}},
                  {"kind": "callout", "anchor": {"box": "a face"}, "key": "B", "params": {"beat": 1, "rows": ["FOG · 0.91"]}},
                  {"kind": "leader", "anchor": {"uv": [.5, .5]}, "key": "B", "params": {"beat": 2, "label": "FOG"}},
                  {"kind": "cv.lock", "anchor": "lead", "key": "B", "params": {"beat": 0, "rows": ["LOCK"]}},
                  {"kind": "gauge", "anchor": {"box": "a woman"}, "key": "B", "params": {"style": "tag", "unit": "°C", "max": 20, "red": 9,
                   "keys": [[{"beats": 0}, 2.1], [{"beats": 2}, 9.8, .3]], "label": "TEMP"}}])
    shot(3, section="chorus", lines=[3], treatment="stills", transition_in="match", type=[{"line": 3, "mode": "stack", "fit": 520}],
         devices=[{"kind": "flash", "key": "W", "params": {"word": "rope", "kind": "card", "sign": "prohibit", "glyph": "X", "line": 3, "number": 1, "of": 4}},
                  {"kind": "label", "key": "B", "params": {"title": "ITEM 03", "rows": [["A", "1"], ["B", "2"]], "serial": "T-03"}}])
    shot(4, section="chorus", treatment="rack", transition_in="dither",
         devices=[{"kind": "sheet", "key": "B", "params": {"style": "receipt", "title": "RECEIPT", "rows": [["BASE", "$100"], ["TOKENS", "$50", "hot"]], "total": ["TOTAL", "$150"]}},
                  {"kind": "chart", "key": "B", "params": {"beat": 1, "type": "exp", "beats": 2, "title": "growth", "value": {"from": 0, "to": 100, "format": "pct"}}},
                  {"kind": "cam.punch", "params": {"amp": .02}}, {"kind": "cam.shake", "params": {"amp": 4}}, {"kind": "cam.ride", "params": {}}])
    shot(5, section="chorus", lines=[4], treatment="rack", transition_in="flap", type=[{"line": 4, "mode": "coverline", "placement": "right"}],
         devices=[{"kind": "flap", "key": "W", "params": {"word": "tokens", "rows": [{"text": "PAID", "prev": "DUE", "accent": True}]}},
                  {"kind": "departures", "key": "B", "params": {"rows": [{"label": "A", "value": "GO", "prev": "WAIT"}]}}])
    shot(6, lines=[5], transition_in="push through", type=[{"line": 5, "mode": "stack"}], lead_on_screen=False,
         devices=[{"kind": "arrow", "key": "W", "params": {"word": "up", "dir": "up", "label": "UP"}}, {"kind": "plot", "key": "B"}])
    shot(7, lines=[6], treatment={"family": "xerox", "kind": "thermal"}, transition_in="smear", type=[{"line": 6, "mode": "masthead", "accumulate": True}],
         devices=[{"kind": "flash", "key": "B", "params": {"kind": "invert", "every": .25}}, {"kind": "ecg", "key": "B", "params": {"bigeminy_at": {"beats": 2}}}])
    shot(8, lines=[7], treatment="contours", transition_in="iris", type=[{"line": 7, "mode": "coverline", "behind": "matte"}],
         devices=[{"kind": "voice", "key": "B", "params": {"style": "bars"}}, {"kind": "cv.outline", "anchor": "lead", "key": "B"}])
    shot(9, section="outro", lines=[8], treatment="scan", transition_in={"preset": "push", "dir": 2},
         devices=[{"kind": "title.knockout", "key": "W", "params": {"token": [8, 0], "word": "CLOSER"}},
                  {"kind": "strike", "key": "B", "params": {"beat": 1}}, {"kind": "redact", "key": "B", "params": {"beat": 2}}])
    shot(10, section="outro", treatment="diagram", transition_in="whip", type=[{"line": 8, "mode": "mass"}],
         devices=[{"kind": "mass", "key": "B"}, {"kind": "ticker", "key": "B", "params": {"items": ["A", "B"]}}, {"kind": "marks", "key": "B", "params": {"style": "ruler"}},
                  {"kind": "typed", "key": "B", "params": {"rows": ["SRC · TEST"]}}, {"kind": "tally", "key": "B", "params": {"n": 8}}])
    shot(11, section="outro", treatment="stills", transition_in="whip right",
         devices=[{"kind": "ui.chatbar", "key": "B", "params": {"send": {"beats": 2}}}, {"kind": "ui.chat", "key": "B", "params": {"beat": 1}},
                  {"kind": "spark", "key": "B", "params": {"beat": 3}}, {"kind": "cam.snap", "params": {}}, {"kind": "cam.whip", "params": {"at": "shot.t1"}}])
    shot(12, section="outro", treatment="occlusion", transition_in="flash", chrome="hud",
         devices=[{"kind": "voice", "key": "B", "params": {"style": "orb"}}, {"kind": "gauge", "key": "B", "params": {"style": "half", "value": 64, "max": 100, "label": "RISK"}},
                  {"kind": "cam.impact", "params": {}}, {"kind": "nonexistent.device", "key": "B"}])
    return S
