"""Shared helpers for slop.audio: project paths, ffmpeg I/O (pipes, never fixed /tmp files), JSON, step state, config.

Everything here is stdlib + numpy. Heavy libraries (torch, transformers, demucs, librosa) are imported lazily by the
step modules that need them, so `slop --help` stays fast.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from slop.config import SlopError, load_project

SONG_SR = 44100


# ---------------------------------------------------------------- paths
@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def song(self) -> Path: return self.root / "audio" / "song.wav"
    @property
    def song_meta(self) -> Path: return self.root / "audio" / "song.json"
    @property
    def stems(self) -> Path: return self.root / "audio" / "stems"
    def stem(self, name: str) -> Path: return self.stems / f"{name}.wav"
    @property
    def windows(self) -> Path: return self.root / "audio" / "windows"
    @property
    def listen(self) -> Path: return self.analysis / "listen"            # ear-check excerpts (not clip windows)
    @property
    def lyrics(self) -> Path: return self.root / "lyrics" / "lyrics.txt"
    @property
    def display(self) -> Path: return self.root / "lyrics" / "display.txt"
    @property
    def adlibs(self) -> Path: return self.root / "lyrics" / "adlibs.json"
    @property
    def pron(self) -> Path: return self.root / "lyrics" / "pron.json"
    @property
    def analysis(self) -> Path: return self.root / "analysis"
    @property
    def beats(self) -> Path: return self.analysis / "beats.json"
    @property
    def words(self) -> Path: return self.analysis / "words.json"
    @property
    def hits(self) -> Path: return self.analysis / "hits.json"
    @property
    def report(self) -> Path: return self.analysis / "report.md"
    @property
    def cache(self) -> Path: return self.analysis / "cache"
    @property
    def state(self) -> Path: return self.analysis / "state.json"
    @property
    def progress(self) -> Path: return self.analysis / "progress.json"


STEMS = ("vocals", "drums", "bass", "other")


# ---------------------------------------------------------------- ffmpeg
def ffmpeg_bin(name: str = "ffmpeg") -> str:
    p = shutil.which(name)
    if not p:
        raise SlopError(f"{name} not found on PATH. Install ffmpeg (bin/setup.sh does it) and re-run.")
    return p


def run_ffmpeg(args: list[str], input_bytes: bytes | None = None, what: str = "ffmpeg") -> bytes:
    """Run ffmpeg with ONE pipe (stdout for decodes, stdin for encodes) and stderr in an anonymous temp file: with a
    single pipe subprocess reads/writes it in one go (two pipes cost a select() per 4 KB chunk - 4 s per stem)."""
    import tempfile
    cmd = [ffmpeg_bin(), "-v", "error", *args]
    with tempfile.TemporaryFile() as errf:
        if input_bytes is None:
            r = subprocess.run([cmd[0], "-nostdin", *cmd[1:]], stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=errf)
        else:
            r = subprocess.run(cmd, input=input_bytes, stdout=subprocess.DEVNULL, stderr=errf)
        if r.returncode != 0:
            errf.seek(0)
            err = errf.read().decode("utf-8", "replace").strip().splitlines()[-3:]
            raise SlopError(f"{what} failed: {' | '.join(err) or 'ffmpeg exit ' + str(r.returncode)}")
    return r.stdout or b""


def load_mono(path: Path | str, sr: int, t0: float | None = None, dur: float | None = None,
              af: str | None = None) -> np.ndarray:
    """Decode any audio file to mono float32 at `sr` through an ffmpeg pipe (no temp files)."""
    path = Path(path)
    if not path.exists():
        raise SlopError(f"missing audio file {path}")
    args: list[str] = []
    if t0 is not None:
        args += ["-ss", f"{max(0.0, t0):.4f}"]
    if dur is not None:
        args += ["-t", f"{max(0.0, dur):.4f}"]
    args += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr)]
    if af:
        args += ["-af", af]
    args += ["-f", "f32le", "-"]
    raw = run_ffmpeg(args, what=f"decoding {path.name}")
    return np.frombuffer(raw, np.float32).copy()


def load_multi(path: Path | str, sr: int, channels: int = 2) -> np.ndarray:
    """Decode to float32 (channels, n)."""
    path = Path(path)
    if not path.exists():
        raise SlopError(f"missing audio file {path}")
    raw = run_ffmpeg(["-i", str(path), "-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"],
                     what=f"decoding {path.name}")
    x = np.frombuffer(raw, np.float32)
    n = len(x) // channels
    return x[: n * channels].reshape(n, channels).T.copy()


def write_audio(path: Path | str, y: np.ndarray, sr: int, codec: str = "pcm_s16le", extra: list[str] | None = None) -> Path:
    """Write float32 audio ((n,) mono or (ch, n)) with ffmpeg; atomic (tmp then rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    y = np.asarray(y, np.float32)
    ch = 1 if y.ndim == 1 else y.shape[0]
    data = y if y.ndim == 1 else y.T.reshape(-1)
    tmp = path.with_name(path.stem + ".part" + path.suffix)
    args = ["-y", "-f", "f32le", "-ar", str(sr), "-ac", str(ch), "-i", "-", "-c:a", codec, *(extra or []), str(tmp)]
    run_ffmpeg(args, input_bytes=np.ascontiguousarray(data).tobytes(), what=f"writing {path.name}")
    tmp.replace(path)
    return path


def probe(path: Path | str) -> dict:
    p = shutil.which("ffprobe")
    if not p:
        raise SlopError("ffprobe not found on PATH. Install ffmpeg (bin/setup.sh does it) and re-run.")
    r = subprocess.run([p, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                       capture_output=True)
    if r.returncode != 0:
        raise SlopError(f"cannot read {path}: is it an audio file? ({r.stderr.decode('utf-8', 'replace').strip()[:200]})")
    d = json.loads(r.stdout or b"{}")
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    if a is None:
        raise SlopError(f"{path} has no audio stream")
    fmt = d.get("format", {})
    dur = float(a.get("duration") or fmt.get("duration") or 0.0)
    return {"codec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate") or 0),
            "channels": int(a.get("channels") or 0), "duration": round(dur, 3),
            "bits": int(a.get("bits_per_raw_sample") or a.get("bits_per_sample") or 0),
            "sample_fmt": a.get("sample_fmt"), "format": fmt.get("format_name")}


def dbfs(x: float) -> float:
    return round(20 * float(np.log10(max(float(x), 1e-12))), 2)


# ---------------------------------------------------------------- json / files
def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise SlopError(f"{path} is not valid JSON ({e}); fix or delete it and re-run")


def write_json(path: Path, data: Any, indent: int | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def fingerprint(*paths: Path) -> str:
    """Cheap change key for derived files: size + mtime of each (missing -> '-')."""
    parts = []
    for p in paths:
        try:
            st = Path(p).stat()
            parts.append(f"{Path(p).name}:{st.st_size}:{st.st_mtime_ns}")
        except FileNotFoundError:
            parts.append(f"{Path(p).name}:-")
    return "|".join(parts)


def sha256_file(path: Path, limit: int | None = None) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        read = 0
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            read += len(b)
            if limit and read >= limit:
                break
    return h.hexdigest()


# ---------------------------------------------------------------- step state (idempotent re-runs)
def state_get(paths: Paths, step: str) -> dict:
    return (read_json(paths.state, {}) or {}).get(step, {})


def state_set(paths: Paths, step: str, key: str, **extra: Any) -> None:
    st = read_json(paths.state, {}) or {}
    st[step] = {"key": key, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), **extra}
    write_json(paths.state, st, indent=1)


# ---------------------------------------------------------------- project config
LEGACY_KEYS = ("tempo_range", "downbeat_phase", "beatgrid", "beat_pad0", "hits", "bpm_hint")


def audio_cfg(pdir: Path) -> dict:
    """The optional "audio" block of project.json (legacy top-level keys from the EV/CLODYSSEY layout are honoured too).

    Keys: tempo_range [lo, hi] · bpm_hint · downbeat_phase 0-3 · beatgrid "fitted"|"analysis" · beat_pad0 bool ·
    hits {add: [[t, s]], drop: [t]} · sections [{name, t0}|{name, bar}] · whisper_map {heard: [sheet words]} ·
    whisper_model · conf_min (0.5)."""
    try:
        proj = load_project(pdir)
    except FileNotFoundError:
        return {}
    cfg = {k: proj[k] for k in LEGACY_KEYS if k in proj}
    cfg.update(proj.get("audio") or {})
    return cfg


def lyrics_cfg(pdir: Path | None) -> dict:
    """The optional "lyrics" block of project.json: banned {word: why}|[words], callbacks [regex], names [..],
    echo_check bool (default true)."""
    if pdir is None:
        return {}
    try:
        return load_project(pdir).get("lyrics") or {}
    except (FileNotFoundError, SlopError):
        return {}


def need_module(name: str, why: str) -> Any:
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError as e:
        raise SlopError(f"python package '{name}' is missing ({why}). Run bin/setup.sh (it installs the pinned CPU "
                        f"stack) and retry. [{e}]")


def hf_home_default() -> None:
    """Put Hugging Face downloads under $SLOP_HOME/cache/hf unless HF_HOME is already set (contract §3.1; the same
    cache bin/setup.sh, edit/depth.py and the taste module use). Torch hub downloads go under $SLOP_HOME/cache/torch."""
    from slop.config import slop_home
    if not os.environ.get("HF_HOME"):
        os.environ["HF_HOME"] = str(slop_home() / "cache" / "hf")
    if not os.environ.get("TORCH_HOME"):
        os.environ["TORCH_HOME"] = str(slop_home() / "cache" / "torch")


# ---------------------------------------------------------------- commands and progress for the operator
def project_cmd(pdir: Path, rest: str) -> str:
    """A command line with the project flag spelled out, e.g. `slop --project my-song audio window ...` (never rely on
    the cwd or an exported SLOP_PROJECT: the bot may run it from anywhere)."""
    try:
        from slop.core_cli import project_ref
        ref = project_ref(Path(pdir))
    except Exception:  # core module absent: the full path always works
        import shlex
        ref = shlex.quote(str(pdir))
    return f"slop --project {ref} {rest}"


def song_duration(paths: Paths) -> float | None:
    """The song's length in seconds: beats.json, else song.json, else ffprobe (None without a song)."""
    for src in (paths.beats, paths.song_meta):
        try:
            d = (read_json(src, {}) or {}).get("duration")
        except SlopError:
            d = None
        if d:
            return float(d)
    if paths.song.exists():
        return float(probe(paths.song)["duration"])
    return None


class Heartbeat:
    """Progress lines on stderr while a long step runs: "[slop] stems: running ..." at the start, then one line every
    `every` seconds. stdout stays a single JSON object; a bot polling a background job (or a tool call with an idle
    timeout) sees that the command is alive."""

    def __init__(self, label: str, every: float = 30.0, prefix: str = "[slop analyze]"):
        self.label, self.every, self.prefix = label, every, prefix
        self._stop = threading.Event()
        self._t0 = 0.0
        self._th: threading.Thread | None = None

    def _say(self, msg: str) -> None:
        try:
            print(f"{self.prefix} {msg}", file=sys.stderr, flush=True)
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop.wait(self.every):
            self._say(f"{self.label}: still running ({time.monotonic() - self._t0:.0f} s)")

    def __enter__(self) -> "Heartbeat":
        self._t0 = time.monotonic()
        self._say(f"{self.label}: running ...")
        if self.every > 0:
            self._th = threading.Thread(target=self._loop, daemon=True)
            self._th.start()
        return self

    def __exit__(self, et, ev, tb) -> None:
        self._stop.set()
        if self._th is not None:
            self._th.join(timeout=1.0)
        self._say(f"{self.label}: {'failed' if et else 'done'} ({time.monotonic() - self._t0:.1f} s)")
