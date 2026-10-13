"""slop/render without a browser: project data + fallbacks, page spec, flash counting, ffprobe verification, CLI wiring."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "engine"
sys.path.insert(0, str(FIX))


@pytest.fixture()
def demo(tmp_path) -> Path:
    d = tmp_path / "demo-project"
    shutil.copytree(FIX / "demo-project", d)
    return d


def test_assets_and_fallbacks(demo):
    from slop.render import project as P
    have = P.asset_files(demo)
    assert set(have) == {"lyrics", "plates"}
    data, warn = P.fallback_data(demo, set(have))
    assert set(data) == {"BEATS", "HITS", "SHOTS", "EDL"}
    assert data["BEATS"]["duration"] == 8.0 and len(data["BEATS"]["beats"]) == 17
    assert not warn
    # without the exported lyrics the words become one token each (and it says so)
    (demo / "engine" / "lyrics.js").unlink()
    data, warn = P.fallback_data(demo, set(P.asset_files(demo)))
    lyr = data["LYR"]
    assert [len(l["tokens"]) for l in lyr] == [3, 3] and lyr[1]["tokens"][0]["t0"] == 4.0
    assert any("words.json" in w for w in warn)


def test_plates_from_picks_are_file_urls(demo):
    from slop.render import project as P
    (demo / "engine" / "plates.js").unlink()
    data, _ = P.fallback_data(demo, set(P.asset_files(demo)))
    pl = data["PLATES"]
    assert pl["grad-a"]["file"].startswith("file:") and pl["grad-a"]["file"].endswith("plates/grad-a.jpg")
    assert pl["grad-b"]["depth"].endswith("grad-b.depth.png")


def test_read_js_asset_roundtrip(demo):
    from slop.render import project as P
    lyr = P.read_js_asset(demo / "engine" / "lyrics.js")
    assert lyr[0]["tokens"][1]["st"] == "accent"
    assert P.read_js_asset(demo / "nope.js") is None


def test_page_spec(demo, monkeypatch):
    from slop.render import project as P
    spec = P.page_spec(demo)
    assert spec["w"] == 1920 and spec["h"] == 1080 and spec["fps"] == 24
    assert spec["url"].startswith("file:") and "index.html?w=1920&h=1080&project=" in spec["url"]
    init = spec["init"]
    slop = json.loads(init.split("window.SLOP = ", 1)[1].split(";\n", 1)[0])
    assert slop["assets"] == ["lyrics.js", "plates.js"] and slop["shots"] is True
    assert slop["project"].endswith("demo-project/") and slop["projectEngine"].endswith("demo-project/engine/")
    assert '"accent": "#D97757"' in init and '"mode": "native"' in init
    v = P.page_spec(demo, 1080, 1920, shots=False)
    assert (v["w"], v["h"]) == (1080, 1920) and '"shots": false' in v["init"]
    monkeypatch.setenv("SLOP_ENGINE_SHOTS", "0")
    assert '"shots": false' in P.page_spec(demo)["init"]


def test_duration_and_frame_count(demo):
    from slop.render import project as P
    assert P.project_duration(demo) == 8.0
    assert P.frame_count(8.0, 24) == 192 and P.frame_count(8.01, 24) == 193


def test_default_workers_bounds():
    from slop.render.frames import default_workers
    assert 1 <= default_workers() <= 4
    assert default_workers(1) == 1


def test_env_sh_is_read_without_overriding(tmp_path, monkeypatch):
    from slop.render import browser as B
    (tmp_path / "env.sh").write_text('export PLAYWRIGHT_BROWSERS_PATH="/x/ms-playwright"\nexport SLOP_BROWSER_CHANNEL=chrome\n'
                                     'export OPENROUTER_API_KEY=secret\nSLOP_CHROME_PATH=/already\n', encoding="utf-8")
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("PLAYWRIGHT_BROWSERS_PATH", "SLOP_BROWSER_CHANNEL", "OPENROUTER_API_KEY")}
    env.update(SLOP_HOME=str(tmp_path), SLOP_CHROME_PATH="/mine")
    monkeypatch.setattr(os, "environ", env)              # a private copy: nothing leaks into later tests
    B.load_env_sh()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/x/ms-playwright"
    assert os.environ["SLOP_BROWSER_CHANNEL"] == "chrome"
    assert os.environ["SLOP_CHROME_PATH"] == "/mine"           # never overrides the environment
    assert "OPENROUTER_API_KEY" not in os.environ             # only PLAYWRIGHT_* / SLOP_* are taken


# ---------------------------------------------------------------- flash check (WCAG 2.3.1 pairs) --
def _strobe(per_second: float, seconds: float = 3.0, fps: int = 24, area: float = 1.0):
    import numpy as np
    n = int(seconds * fps)
    L = np.full((n, 54, 96), .05, np.float32)
    period = fps / per_second
    w = int(96 * area)
    for i in range(n):
        if int(i // (period / 2)) % 2 == 1:
            L[i, :, :w] = .7
    return L


def test_flash_count_pass_and_fail():
    from slop.render.flash import count_flashes
    ok = count_flashes(_strobe(2))
    assert ok["pass"] and ok["worst_per_second"] <= 3
    bad = count_flashes(_strobe(6))
    assert not bad["pass"] and bad["worst_per_second"] > 3 and bad["fails"]
    small = count_flashes(_strobe(6, area=.2))          # a flicker in under a quarter of the frame is allowed
    assert small["pass"] and small["flashes"] == 0


def test_flash_pairs_count_once():
    import numpy as np
    from slop.render.flash import count_flashes
    L = np.full((48, 54, 96), .05, np.float32)
    L[10:12] = .9                                       # one strobe: dark -> white -> dark = ONE flash
    r = count_flashes(L)
    assert r["flashes"] == 1 and r["worst_per_second"] == 1


# ------------------------------------------------------------------ ffprobe tag verification --------
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg not installed")


@needs_ffmpeg
def test_verify_flags_untagged_and_accepts_tagged(tmp_path):
    from slop.render.encode import TAGS, VF, verify
    src = ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=1"]
    plain, tagged = tmp_path / "plain.mp4", tmp_path / "tagged.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(plain)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-vf", VF, *TAGS, "-c:v", "libx264", "-crf", "16",
                    "-pix_fmt", "yuv420p", str(tagged)], check=True)
    v0 = verify(plain, want_audio=False)
    assert not v0["ok"] and any("color" in p for p in v0["problems"])
    v1 = verify(tagged, expect_frames=24, want_audio=False, size=(320, 180))
    assert v1["ok"], v1["problems"]
    assert v1["tags"]["color_transfer"] == "iec61966-2-1" and v1["tags"]["color_primaries"] == "bt709"
    assert not verify(tagged, want_audio=True)["ok"]   # the master must carry audio


@needs_ffmpeg
def test_encode_errors_are_actionable(demo):
    from slop.config import SlopError
    from slop.render.encode import encode
    with pytest.raises(SlopError, match="slop render frames"):
        encode(demo)
    fr = demo / "render" / "frames"
    fr.mkdir(parents=True)
    from PIL import Image
    for i in (0, 1, 5):
        Image.new("RGB", (64, 36), (i * 20, 40, 90)).save(fr / f"f{i:05d}.jpg")
    with pytest.raises(SlopError, match="missing"):
        encode(demo)                                   # holes: refuse a master
    with pytest.raises(SlopError, match="audio"):
        encode(demo, allow_gaps=True)                  # no song yet
    r = encode(demo, profile="draft", audio=False)     # a draft holds frames over the holes
    assert r["ok"] and r["gaps"] > 0 and Path(r["out"]).name == "draft.mp4"


# -------------------------------------------------------------------------------- CLI wiring -------
def test_cli_registers_render_steps():
    from slop.cli import build_parser
    ap = build_parser()
    a = ap.parse_args(["render", "frames", "--from", "1", "--to", "2", "--every", "4", "--project", "x", "--json"])
    assert a.render_step == "frames" and a.t_from == 1.0 and a.every == 4 and a.project == "x" and a.json
    a = ap.parse_args(["--project", "y", "render", "lyrics"])
    assert a.project == "y" and callable(a.func)          # the root --project is kept when the step does not repeat it
    for step in ("info", "stills", "sheet", "encode", "check", "vertical"):
        extra = ["--times", "1"] if step == "stills" else []
        assert callable(ap.parse_args(["render", step, *extra]).func)


def test_cli_no_step_and_no_project(tmp_path, monkeypatch, capsys):
    from slop.cli import main
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    assert main(["--json", "render"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert not out["ok"] and "frames" in out["error"]
    assert main(["--json", "render", "lyrics"]) == 1
    assert "no project" in json.loads(capsys.readouterr().out)["error"]


def test_vertical_subject_centres(demo):
    from slop.render.vertical import subject_u
    spans = subject_u(demo)
    assert [round(u, 2) for _, _, u in spans] == [0.64, 0.3, 0.52]


def test_timemap(demo):
    from slop.config import SlopError
    from slop.render.frames import load_timemap
    with pytest.raises(SlopError, match="timemap"):
        load_timemap(demo)
    (demo / "edit" / "timemap.json").write_text(json.dumps({"segments": [[0, 4, 0, 4], [4, 6, 3, 5], [6, 9, 5, 8]]}))
    tl = load_timemap(demo)
    assert [tl(1.0), tl(4.5), tl(7.0)] == [1.0, 3.5, 6.0]


def test_cli_import_is_light():
    code = ("import sys, slop.render.cli; heavy = [m for m in ('playwright', 'numpy', 'PIL', 'torch') if m in sys.modules]; "
            "print(','.join(heavy))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    assert out.returncode == 0 and out.stdout.strip() == "", out.stdout + out.stderr


# ------------------------------------------------------- fixer pass: what a master must be -----------------------------
def _frames(d: Path, idx, size=(64, 36)):
    from PIL import Image
    d.mkdir(parents=True, exist_ok=True)
    for i in idx:
        Image.new("RGB", size, ((i * 7) % 255, 40, 90)).save(d / f"f{i:05d}.jpg")


def _song(path: Path, silent_until: float = 0.0, seconds: float = 8.0, sr: int = 44100):
    """A stereo wav: silence until `silent_until`, then a loud 440 Hz tone."""
    import math
    import struct
    import wave
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        buf = bytearray()
        for j in range(int(seconds * sr)):
            v = 0 if j < silent_until * sr else int(20000 * math.sin(2 * math.pi * 440 * j / sr))
            buf += struct.pack("<hh", v, v)
        w.writeframes(bytes(buf))
    return path


def _fresh_record(demo: Path, frames: Path, **extra):
    from slop.render import project as P
    fp = P.inputs_fingerprint(demo, P.page_spec(demo))
    fp["duration"] = 8.0
    fp.update(extra)
    P.write_fingerprint(frames, fp)
    return fp


@needs_ffmpeg
def test_master_must_start_at_frame_zero(demo):
    """frames --from 2 then encode: refused (the audio starts at 0, so every word would play 2 s early)."""
    from slop.config import SlopError
    from slop.render.encode import encode
    fr = demo / "render" / "frames"
    _frames(fr, range(48, 192))
    _fresh_record(demo, fr)
    _song(demo / "audio" / "song.wav")
    with pytest.raises(SlopError, match=r"48 of 192 frames missing .*first: f00000"):
        encode(demo)
    with pytest.raises(SlopError, match="f00000"):
        encode(demo, profile="review")
    # the true count when only a slice exists
    for f in fr.glob("f*.jpg"):
        if not 48 <= int(f.stem[1:]) <= 71:
            f.unlink()
    with pytest.raises(SlopError, match=r"168 of 192 frames missing .*first: f00000"):
        encode(demo)


@needs_ffmpeg
def test_preview_offsets_the_audio(demo):
    """A draft of frames 48..95 (2 s → 4 s) hears the song from 2 s: the tone that starts at 2.0 s is there at once."""
    import numpy as np
    from slop.render.encode import encode
    fr = demo / "render" / "frames"
    _frames(fr, range(48, 96))
    _fresh_record(demo, fr)
    _song(demo / "audio" / "song.wav", silent_until=2.0)
    r = encode(demo, profile="draft")
    assert r["ok"], r["text"]
    assert r["start_frame"] == 48 and r["verify"]["frames"] == 48 and abs(r["verify"]["video_duration"] - 2.0) < 1e-6
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", r["out"], "-t", "0.25", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(float)
    assert np.sqrt((a[400:] ** 2).mean()) > 3000, "the preview's audio is not offset to its first frame"


@needs_ffmpeg
def test_master_verifies_duration_and_count(demo):
    from slop.render.encode import PROFILES, encode, verify
    fr = demo / "render" / "frames"
    _frames(fr, range(0, 192))
    _fresh_record(demo, fr)
    _song(demo / "audio" / "song.wav")
    r = encode(demo)
    v = r["verify"]
    assert r["ok"] and v["frames"] == 192 and abs(v["video_duration"] - 8.0) < 1 / 24, r["text"]
    bad = verify(Path(r["out"]), expect_frames=200, expect_duration=8.4, size=(64, 36))
    assert not bad["ok"] and any("frames, expected 200" in p for p in bad["problems"])
    assert any("expected 8.400 s" in p for p in bad["problems"])
    # a song shorter than the film: -shortest cuts the picture and verify says so
    _song(demo / "audio" / "song.wav", seconds=6.0)
    r2 = encode(demo)
    assert not r2["ok"] and "song.wav shorter" in r2["text"], r2["text"]
    assert PROFILES["review"][PROFILES["review"].index("-tune") + 1] == "grain"


@needs_ffmpeg
def test_encode_refuses_stale_frames(demo):
    from slop.config import SlopError
    from slop.render.encode import encode
    fr = demo / "render" / "frames"
    _frames(fr, range(0, 192))
    _fresh_record(demo, fr)
    assert encode(demo, audio=False)["ok"]
    shots = json.loads((demo / "board" / "shots.json").read_text(encoding="utf-8"))
    shots["shots"][0]["camera"] = "push in"                     # the storyboard changed after the frames were drawn
    (demo / "board" / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
    with pytest.raises(SlopError, match=r"stale .*fallback:SHOTS.*slop render frames"):
        encode(demo, audio=False)
    r = encode(demo, profile="draft", audio=False)              # a draft encodes them anyway, and says so
    assert r["ok"] and any("stale" in w for w in r["warnings"])
    # frames drawn over missing media (--allow-missing) never make a master
    _fresh_record(demo, fr, placeholders=True)
    with pytest.raises(SlopError, match="allow-missing"):
        encode(demo, audio=False)


def test_fingerprint_names_what_changed(demo):
    import os
    from slop.render import project as P
    a = P.inputs_fingerprint(demo, P.page_spec(demo))
    assert a == P.inputs_fingerprint(demo, P.page_spec(demo))      # stable
    lj = demo / "engine" / "lyrics.js"
    src = lj.read_text(encoding="utf-8")
    assert '"Hello"' in src, "the fixture's first token changed: pick another word to edit"
    lj.write_text(src.replace('"Hello"', '"HELLO"'), encoding="utf-8")       # a real content change (not CRLF -> LF)
    b = P.inputs_fingerprint(demo, P.page_spec(demo))
    assert P.fingerprint_changes(a, b) == ["data:engine/lyrics.js"]
    st = (demo / "plates" / "grad-a.jpg").stat()
    os.utime(demo / "plates" / "grad-a.jpg", ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))   # a re-picked plate
    c = P.inputs_fingerprint(demo, P.page_spec(demo))
    assert P.fingerprint_changes(b, c) == ["media"]
    d = P.inputs_fingerprint(demo, P.page_spec(demo, 1080, 1920))
    assert "size" in P.fingerprint_changes(c, d)
    assert P.inputs_fingerprint(demo, P.page_spec(demo, shots=False))["renderer"] == "stub"
    assert P.fingerprint_changes(None, a)[0].startswith("no record")


def test_stale_frames_are_discarded(demo):
    from slop.render import project as P
    from slop.render.frames import refresh_stale
    fr = demo / "render" / "frames"
    _frames(fr, range(0, 5))
    fp = P.inputs_fingerprint(demo, P.page_spec(demo))
    assert "no record" in refresh_stale(demo, fr, fp) and not list(fr.glob("f*.jpg"))   # unknown provenance: redrawn
    _frames(fr, range(0, 5))
    assert refresh_stale(demo, fr, fp) == "" and len(list(fr.glob("f*.jpg"))) == 5     # same inputs: resumed
    bj = demo / "analysis" / "beats.json"
    bj.write_text(bj.read_text(encoding="utf-8").replace("verse1", "verse"), encoding="utf-8")
    fp2 = P.inputs_fingerprint(demo, P.page_spec(demo))
    note = refresh_stale(demo, fr, fp2)
    assert "fallback:BEATS" in note and "5 frames" in note and not list(fr.glob("f*.jpg"))
    assert P.read_fingerprint(fr)["hash"] == fp2["hash"]


def test_timemap_duration(demo):
    from slop.render import project as P
    assert P.render_duration(demo) == 8.0 and P.render_duration(demo, True) == 8.0     # no time map, no audio: beat map
    (demo / "edit" / "timemap.json").write_text(json.dumps({"segments": [[0, 4, 0, 4], [4, 10, 4, 8]]}), encoding="utf-8")
    assert P.timemap_end(demo) == 10.0 and P.render_duration(demo, True) == 10.0
    (demo / "edit" / "timemap.json").unlink()
    _song(demo / "audio" / "song.wav", seconds=9.5)
    assert P.render_duration(demo, True) == pytest.approx(9.5)                        # else the final song's audio


def test_untimed_words_are_kept_for_the_gate(demo):
    from slop.render import project as P
    words = json.loads((demo / "analysis" / "words.json").read_text(encoding="utf-8"))
    words["words"][4]["t0"] = None
    (demo / "analysis" / "words.json").write_text(json.dumps(words), encoding="utf-8")
    (demo / "engine" / "lyrics.js").unlink()
    spec = P.page_spec(demo)
    assert spec["untimed"] == [{"line": 1, "i": 4, "w": words["words"][4]["w"]}]
    assert any("no t0" in w for w in spec["warnings"])
    assert sum(len(ln["tokens"]) for ln in P.lyr_from_words(words)) == 5


def test_apply_env_reaches_the_driver(tmp_path, monkeypatch):
    """PLAYWRIGHT_BROWSERS_PATH from $SLOP_HOME/env.sh must be set BEFORE sync_playwright() starts the driver."""
    import os
    import types
    from slop.render import frames as FR
    (tmp_path / "env.sh").write_text('export PLAYWRIGHT_BROWSERS_PATH="/opt/x/ms-playwright"\n', encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PLAYWRIGHT_BROWSERS_PATH"}
    env["SLOP_HOME"] = str(tmp_path)
    monkeypatch.setattr(os, "environ", env)
    seen = {}
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: seen.setdefault("at_start", os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    FR._sync_playwright()()
    assert seen["at_start"] == "/opt/x/ms-playwright"
    # no env.sh entry: $SLOP_HOME/ms-playwright when setup.sh installed Chromium there
    (tmp_path / "env.sh").unlink()
    (tmp_path / "ms-playwright").mkdir()
    del env["PLAYWRIGHT_BROWSERS_PATH"]
    seen.clear()
    FR._sync_playwright()()
    assert seen["at_start"] == str(tmp_path / "ms-playwright")


def test_no_invented_duration(demo, capsys):
    from slop.config import SlopError
    from slop.render.frames import _sheet_times
    for rel in ("analysis/beats.json", "board/shots.json"):
        (demo / rel).unlink()
    with pytest.raises(SlopError, match="no song duration"):
        _sheet_times(demo, {}, None)
    from slop.cli import main
    assert main(["--json", "--project", str(demo), "render", "check", "--skip-flash"]) == 1
    assert "no song duration" in json.loads(capsys.readouterr().out.strip().splitlines()[-1])["error"]


def test_cli_new_flags():
    from slop.cli import build_parser
    from slop.config import SlopError
    from slop.render.cli import _size_or_vertical
    ap = build_parser()
    a = ap.parse_args(["render", "lyrics", "--vertical"])
    assert a.vertical and a.render_step == "lyrics"
    a = ap.parse_args(["render", "sheet", "--size", "1080x1920", "--allow-missing"])
    assert a.size == "1080x1920" and a.allow_missing
    for step in ("frames", "vertical"):
        assert ap.parse_args(["render", step, "--allow-missing"]).allow_missing
    assert ap.parse_args(["render", "stills", "--times", "1", "--allow-missing"]).allow_missing
    assert _size_or_vertical(ap.parse_args(["render", "lyrics", "--vertical"])) == (1080, 1920)
    with pytest.raises(SlopError):
        _size_or_vertical(ap.parse_args(["render", "sheet", "--vertical", "--size", "10x10"]))


def test_media_labels_are_paths(tmp_path):
    from slop.render.frames import media_label, missing_text
    assert media_label("clip:SD01-t1") == "clip:SD01-t1"
    p = (tmp_path / "plates" / "a b.jpg").resolve()
    assert media_label(p.as_uri()) == str(p)
    t = missing_text([{"src": p.as_uri(), "why": "plate 'a'"}], ["x.ttf"])
    assert "a b.jpg" in t and "slop edit export" in t and "x.ttf" in t


def test_fingerprint_sees_engine_code(tmp_path, monkeypatch):
    from slop.render import project as P
    eng = tmp_path / "engine"
    (eng / "src" / "devices").mkdir(parents=True)
    (eng / "index.html").write_text("<html>", encoding="utf-8")
    (eng / "src" / "core.js").write_text("const a = 1;", encoding="utf-8")
    (eng / "src" / "devices" / "cv.js").write_text("const b = 1;", encoding="utf-8")
    monkeypatch.setattr(P, "engine_dir", lambda: eng)
    h0 = P.engine_code_hash()
    (eng / "src" / "devices" / "cv.js").write_text("const b = 2;", encoding="utf-8")     # a device changed
    h1 = P.engine_code_hash()
    (eng / "fonts").mkdir()
    (eng / "fonts" / "x.ttf").write_bytes(b"0")                                         # binaries are not code
    assert h0 != h1 and P.engine_code_hash() == h1
