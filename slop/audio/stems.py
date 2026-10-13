"""Stem separation on CPU: Demucs `htdemucs` -> audio/stems/{vocals,drums,bass,other}.wav (44.1 kHz stereo, float32).

Port of the stems part of the GPU analyze script, unchanged in method: the song is normalised by its mono reference
(mean/std), separated with apply_model(shifts=1, split=True, overlap=.25) and de-normalised.
Changes: CPU only; the random shift of apply_model(shifts=1) is seeded, so re-running gives the same stems (unseeded,
the EV benchmark's word accuracy moved between 95.9 and 97.4 % from run to run); stems are written as 32-bit float WAV
(no clipping, levels comparable across stems - the old 16-bit write could wrap/clip loud stems); a stems.json sidecar
records the model and the song it came from.
Imported stems (`slop analyze --stems-dir DIR`, e.g. exported from the music service): converted to the same format and
KEPT - a later plain `slop analyze` does not replace them with Demucs (only `--force` does); re-running the same import
is a no-op (keyed on the song and the source files); if song.wav changes after an import, analyze stops and asks for a
re-import (or --force for Demucs) instead of silently mixing stems of two songs.

Licences: demucs code MIT (github.com/adefossez/demucs). The htdemucs weights (84 MB, fetched by demucs 4.1 from the
Hugging Face hub, repo adefossez/HTDemucs, fallback dl.fbaipublicfiles.com) carry no separate licence tag - FLAGGED:
tell the user before commercial use, or let them supply stems exported from their music service (`--stems-dir`).
CPU cost for a 306 s song (first run also downloads the 84 MB weights):
  - 64 s on 8 pinned threads of a 16-core desktop CPU, 2.7 GiB peak RAM (measured, research 11-gap-3 section 3);
  - 87 s in this module's benchmark (tests/bench_audio_ev.py) on 32 threads while other jobs shared the machine;
  - the 8-vCPU box: estimated 2-3 min (research 11-gap-3 section 3.5 puts the whole analyze at 3.5-6 min).
  Run `slop analyze` as a background job and poll analysis/progress.json (see `slop analyze --help`).
GPU route: `slop analyze --gpu auto|require` (auto is the CLI default) separates on the user's paired home GPU when
`slop gpu status` is healthy (_separate_on_gpu; same method and seed), else on the CPU with a note.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import (SONG_SR, STEMS, Paths, fingerprint, hf_home_default, load_multi, need_module, state_get, state_set,
                     write_audio, write_json)

MODEL = "htdemucs"


def stems_present(paths: Paths) -> bool:
    return all(paths.stem(s).exists() for s in STEMS)


def separate(pdir: Path, force: bool = False, progress: bool = False) -> dict:
    paths = Paths(pdir)
    if not paths.song.exists():
        raise SlopError("no audio/song.wav - run `slop song ingest FILE` first")
    song_fp = fingerprint(paths.song)
    key = f"{MODEL}|{song_fp}"
    st = state_get(paths, "stems")
    if not force and stems_present(paths) and st.get("model") == "imported":
        if st.get("song") == song_fp:
            return {"status": "up-to-date", "model": "imported", "stems": [str(paths.stem(s)) for s in STEMS],
                    "note": "using the imported stems (--force would replace them with Demucs)"}
        raise SlopError("audio/stems/ holds stems imported for a different audio/song.wav (the song changed since). "
                        "Re-import the new song's stems with `slop analyze --stems-dir DIR`, or separate with Demucs "
                        "with `slop analyze --force`.")
    if not force and stems_present(paths) and st.get("key") == key:
        return {"status": "up-to-date", "model": MODEL, "stems": [str(paths.stem(s)) for s in STEMS]}
    gpu = _separate_on_gpu(paths, song_fp, key)      # routing hook (--gpu auto|require): the user's paired home GPU
    if gpu is not None:
        return gpu
    hf_home_default()
    torch = need_module("torch", "stem separation runs Demucs on torch (CPU)")
    need_module("demucs", "stem separation uses the demucs package")
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    t = time.monotonic()
    try:
        model = get_model(MODEL)
    except Exception as e:  # network / hub problems
        raise SlopError(f"could not load the Demucs '{MODEL}' weights ({type(e).__name__}: {e}). They download once "
                        "(84 MB) from huggingface.co; check the network, or pass --stems-dir with stems you already have.")
    model.eval()
    sr = int(model.samplerate)
    wav = torch.from_numpy(load_multi(paths.song, sr, 2))
    ref = wav.mean(0)
    mu, sd = ref.mean(), ref.std() + 1e-9
    wn = (wav - mu) / sd
    t_load = time.monotonic() - t
    import random
    random.seed(0)                      # apply_model(shifts=1) draws a random time shift: seed it -> same stems every run
    torch.manual_seed(0)
    with torch.no_grad():
        src = apply_model(model, wn[None], shifts=1, split=True, overlap=.25, progress=progress)[0]
    src = src * sd + mu
    t_sep = time.monotonic() - t - t_load
    paths.stems.mkdir(parents=True, exist_ok=True)
    for name, s in zip(model.sources, src):
        if name in STEMS:
            write_audio(paths.stem(name), s.numpy().astype(np.float32), sr, codec="pcm_f32le")
    missing = [s for s in STEMS if not paths.stem(s).exists()]
    if missing:
        raise SlopError(f"Demucs did not produce stems {missing} (model sources: {model.sources})")
    write_json(paths.stems / "stems.json", {"model": MODEL, "sources": list(model.sources), "samplerate": sr,
                                            "song": fingerprint(paths.song), "seconds": round(time.monotonic() - t, 1)}, 1)
    state_set(paths, "stems", key, model=MODEL, song=song_fp)
    return {"status": "done", "model": MODEL, "load_s": round(t_load, 1), "separate_s": round(t_sep, 1),
            "stems": [str(paths.stem(s)) for s in STEMS]}


def _separate_on_gpu(paths: Paths, song_fp: str, key: str) -> dict | None:
    """The same separation on the user's paired home GPU (slop/gpu: same method, seed and stem format; the stems
    travel as 24-bit FLAC with a per-stem gain and are written here as float WAV like the CPU path). None = the CPU
    path runs: --gpu off (the library default), no healthy GPU in auto mode, or a failed GPU job in auto mode (the
    router adds a note saying why)."""
    from slop.gpu import route
    out_mb, cpu_s = route.stems_estimate(paths.song)    # auto: a slow home uplink can make the GPU route slower
    if not route.plan("audio.stems", "stems", out_mb=out_mb, cpu_s=cpu_s):
        return None
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    from .common import run_ffmpeg
    t = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="slop-stems-") as td:
        song = Path(td) / "song.flac"                 # lossless (song.wav is 16/24-bit PCM), about half the upload
        try:
            run_ffmpeg(["-y", "-i", str(paths.song), "-c:a", "flac", str(song)], what="packing the song for the GPU")
            inputs = {"song.flac": song}
        except SlopError:
            inputs = {"song.wav": paths.song}
        r = route.execute("audio.stems", inputs, {"seed": 0}, label="stems")
    if r is None:
        return None
    try:
        files, gains = r.result.get("files") or {}, r.result.get("gains") or {}
        missing = [s for s in STEMS if s not in files]
        if missing:
            raise SlopError(f"the GPU job returned no {missing} stem")
        paths.stems.mkdir(parents=True, exist_ok=True)

        def unpack(name: str) -> None:
            y = load_multi(r.file(files[name]), SONG_SR, 2) / float(gains.get(name) or 1.0)
            write_audio(paths.stem(name), y.astype(np.float32), SONG_SR, codec="pcm_f32le")
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(unpack, STEMS))
    except SlopError as e:
        if route.mode() == "require":
            raise
        route.note(f"stems: the GPU result was unusable ({e}) - ran on the CPU instead")
        return None
    secs = round(time.monotonic() - t, 1)
    dev = f"gpu: {r.gpu or 'paired GPU'}"
    write_json(paths.stems / "stems.json", {"model": MODEL, "sources": r.result.get("sources"), "samplerate": SONG_SR,
                                            "song": song_fp, "seconds": secs, "device": dev, "gpu_job": r.id}, 1)
    state_set(paths, "stems", key, model=MODEL, song=song_fp)
    return {"status": "done", "model": MODEL, "device": dev, "gpu_job": r.id, "separate_s": r.result.get("separate_s"),
            "gpu_job_s": r.metrics.get("seconds"), "end_to_end_s": secs, "stems": [str(paths.stem(s)) for s in STEMS]}


def import_stems(pdir: Path, src_dir: str | Path, force: bool = False) -> dict:
    """Use stems the user already has (e.g. exported from their music service): files named vocals/drums/bass/other
    (any audio format) are converted to audio/stems/<name>.wav at 44.1 kHz stereo float. Idempotent: the same song and
    the same source files again is a no-op (unless force)."""
    paths = Paths(pdir)
    if not paths.song.exists():
        raise SlopError("no audio/song.wav - run `slop song ingest FILE` first (the stems must belong to that song)")
    src_dir = Path(src_dir).expanduser()
    if not src_dir.is_dir():
        raise SlopError(f"--stems-dir {src_dir} is not a folder. Put the four stem files (vocals, drums, bass, other) "
                        "in one folder and pass its path.")
    found = {}
    for s in STEMS:
        cands = sorted(p for p in src_dir.glob("*") if p.is_file() and p.stem.lower().startswith(s))
        if not cands:
            raise SlopError(f"no '{s}' file in {src_dir} (need vocals, drums, bass and other; names starting with those words)")
        found[s] = cands[0]
    song_fp = fingerprint(paths.song)
    key = f"imported|{song_fp}|{fingerprint(*found.values())}"
    if not force and stems_present(paths) and state_get(paths, "stems").get("key") == key:
        return {"status": "up-to-date", "model": "imported", "stems": {k: str(paths.stem(k)) for k in found}}
    durs = {}
    paths.stems.mkdir(parents=True, exist_ok=True)
    for s, p in found.items():
        y = load_multi(p, SONG_SR, 2)
        durs[s] = y.shape[1] / SONG_SR
        write_audio(paths.stem(s), y, SONG_SR, codec="pcm_f32le")
    write_json(paths.stems / "stems.json", {"model": "imported", "from": str(src_dir),
                                            "files": {k: v.name for k, v in found.items()}, "song": song_fp}, 1)
    state_set(paths, "stems", key, model="imported", song=song_fp)
    out = {"status": "imported", "model": "imported", "stems": {k: str(paths.stem(k)) for k in found}}
    try:
        from .common import probe
        song_d = float(probe(paths.song)["duration"])
        off = {k: round(d - song_d, 2) for k, d in durs.items() if abs(d - song_d) > 0.5}
        if off:
            out["warnings"] = [f"stem lengths differ from song.wav by {off} s: are these the stems of this song "
                               "(same take, same start)?"]
    except SlopError:
        pass
    return out


def clear(pdir: Path) -> None:
    shutil.rmtree(Paths(pdir).stems, ignore_errors=True)
