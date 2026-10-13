"""`slop song ingest FILE`: copy/convert the delivered song to audio/song.wav (44.1 kHz stereo) + loudness stats.

Idempotent: the same source file again is a no-op; a different song refuses to overwrite without --force (the old
analysis would silently go stale - the analysis state keys on song.wav, so `slop analyze` redoes everything after).
An audio/song.wav that was put in place by hand (no audio/song.json beside it) is an UNKNOWN song: replacing it also
needs --force.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from slop.config import SlopError

from .common import SONG_SR, Paths, probe, read_json, run_ffmpeg, sha256_file, write_json


def loudness(path: Path) -> dict:
    """EBU R128 integrated loudness, range and true peak (ffmpeg ebur128) + sample peak/mean (volumedetect)."""
    import shutil
    import subprocess
    cmd = [shutil.which("ffmpeg") or "ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-vn",
           "-af", "ebur128=peak=true,volumedetect", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True)
    err = r.stderr.decode("utf-8", "replace")
    out: dict = {}
    summ = err[err.rfind("Summary:"):] if "Summary:" in err else err
    for key, pat in (("lufs_i", r"I:\s*(-?[\d.]+|-inf)\s*LUFS"), ("lra_lu", r"LRA:\s*(-?[\d.]+)\s*LU"),
                     ("true_peak_dbfs", r"Peak:\s*(-?[\d.]+|-inf)\s*dBFS")):
        m = re.search(pat, summ)
        if m:
            out[key] = float(m.group(1)) if m.group(1) != "-inf" else None
    for key, pat in (("mean_dbfs", r"mean_volume:\s*(-?[\d.]+)\s*dB"), ("peak_dbfs", r"max_volume:\s*(-?[\d.]+)\s*dB")):
        m = re.search(pat, err)
        if m:
            out[key] = float(m.group(1))
    return out


def ingest(pdir: Path, src: str | Path, force: bool = False) -> dict:
    from slop.util import input_path, not_found
    paths = Paths(pdir)
    given = src
    src = input_path(pdir, src)                       # from the current folder, else inside the project folder
    if not src or not src.exists():
        raise SlopError(f"{given} does not exist - " + not_found(pdir, given, "song file") + ". Pass the path of the "
                        "song file (wav/mp3/flac/m4a) you downloaded.")
    if src.resolve() == paths.song.resolve():
        raise SlopError("that is already audio/song.wav; pass the original download instead")
    info = probe(src)
    if info["duration"] <= 1.0:
        raise SlopError(f"{src.name} is only {info['duration']} s long - is this the right file?")
    sha = sha256_file(src)
    meta = read_json(paths.song_meta, {}) or {}
    if paths.song.exists() and meta.get("source_sha256") == sha and not force:
        return {"status": "unchanged", "song": str(paths.song), **{k: meta.get(k) for k in ("duration", "loudness")},
                "text": f"audio/song.wav already holds {src.name} ({meta.get('duration')} s); nothing to do."}
    if paths.song.exists() and meta.get("source_sha256") not in (None, sha) and not force:
        raise SlopError(f"audio/song.wav already holds a different song (from {meta.get('source_name')}). "
                        "Re-run with --force to replace it, then run `slop analyze --force` (the old analysis is stale).")
    if paths.song.exists() and not meta.get("source_sha256") and not force:
        raise SlopError("audio/song.wav already exists but was not ingested by `slop song ingest` (no audio/song.json), "
                        "so it may be a different song. Re-run with --force to replace it with this file (then "
                        "`slop analyze --force`), or keep it and skip ingest.")
    paths.song.parent.mkdir(parents=True, exist_ok=True)
    codec = "pcm_s24le" if info["bits"] > 16 else "pcm_s16le"          # keep 24-bit/float masters at 24 bit
    tmp = paths.song.with_name("song.part.wav")
    run_ffmpeg(["-y", "-i", str(src), "-vn", "-map_metadata", "-1", "-ac", "2", "-ar", str(SONG_SR),
                "-c:a", codec, str(tmp)], what=f"converting {src.name}")
    tmp.replace(paths.song)
    out = probe(paths.song)
    loud = loudness(paths.song)
    warn = []
    if info["sample_rate"] != SONG_SR:
        warn.append(f"resampled {info['sample_rate']} Hz -> 44100 Hz (timing is unchanged)")
    if info["channels"] == 1:
        warn.append("the source is mono; song.wav has the same signal on both channels")
    if info["codec"] in ("mp3", "aac", "opus", "vorbis"):
        warn.append(f"the source is lossy ({info['codec']}); a WAV download from the music service is better for stems")
    if (loud.get("true_peak_dbfs") or -99) > 0.0:
        warn.append(f"true peak {loud['true_peak_dbfs']} dBFS > 0: the master clips (fine for analysis; note for mastering)")
    if out["duration"] > 600:
        warn.append("longer than 10 min: analysis will be slow on CPU")
    meta = {"source_name": src.name, "source_path": str(src), "source_sha256": sha, "source": info,
            "duration": out["duration"], "sample_rate": out["sample_rate"], "channels": out["channels"], "codec": codec,
            "loudness": loud, "ingested": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_json(paths.song_meta, meta, indent=1)
    lu = loud.get("lufs_i")
    text = (f"audio/song.wav <- {src.name}: {out['duration']:.1f} s, 44.1 kHz stereo, "
            f"{lu if lu is not None else '?'} LUFS, true peak {loud.get('true_peak_dbfs', '?')} dBFS."
            + "".join(f"\n  note: {w}" for w in warn)
            + "\nNext: write lyrics/lyrics.txt (sung words, numbers spelled as sung), then `slop analyze`.")
    return {"status": "ingested", "song": str(paths.song), "duration": out["duration"], "loudness": loud,
            "source": info, "warnings": warn, "text": text}
