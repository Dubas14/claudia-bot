"""A fresh project from `slop new` (template lyrics.txt / display.txt hold only [notes]) through the default analyze:
alignment is skipped with a next step instead of loading wav2vec2 and failing; imported stems are kept by later runs;
an explicit `--steps align` without lyrics fails before any work; `lyrics display --init` fills the notes-only file."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "audio"))

import synth  # noqa: E402

from slop.audio import align as al  # noqa: E402
from slop.audio import stems as st  # noqa: E402
from slop.audio.common import write_audio  # noqa: E402
from slop.cli import main  # noqa: E402


def slop(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--json", *argv])
    return rc, json.loads(buf.getvalue().strip().splitlines()[-1])


def _boom(*a, **k):
    raise AssertionError("must not run on this path")


def test_fresh_template_project_default_analyze(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    monkeypatch.setenv("SLOP_PROJECTS", str(projects))
    monkeypatch.delenv("SLOP_PROJECT", raising=False)
    rc, out = slop("new", "fresh-song", "--root", str(projects))
    assert rc == 0, out
    root = Path(out["project"])
    assert al.read_sheet(root / "lyrics" / "lyrics.txt") == []            # the template holds only [notes]
    song = synth.make_song(dur=16.0, drop_at=8.0, vocal_phrases=[(2.0, 5.0), (10.0, 13.0)])
    import numpy as np
    take = write_audio(tmp_path / "take.wav", np.stack([song["mix"], song["mix"]]), 44100)
    sdir = tmp_path / "my-stems"
    for k, v in song["stems"].items():
        write_audio(sdir / f"{k}.wav", v, 44100)
    rc, out = slop("-p", "fresh-song", "song", "ingest", str(take))
    assert rc == 0, out
    monkeypatch.setattr(al, "compute_emissions", _boom)                   # wav2vec2 must never load here
    monkeypatch.setattr(al, "load_model", _boom)
    monkeypatch.setattr(st, "need_module", _boom)                         # nor Demucs
    rc, out = slop("-p", "fresh-song", "analyze", "--stems-dir", str(sdir))
    assert rc == 0, out
    assert out["steps"]["stems"]["status"] == "imported"
    assert out["steps"]["align"]["status"] == "skipped"
    assert {"beats", "sections", "hits"} <= set(out["steps"])
    assert any("lyrics/lyrics.txt" in n and "analyze --steps align" in n and "--project fresh-song" in n
               for n in out["notes"]), out["notes"]
    assert (root / "analysis" / "hits.json").exists() and (root / "analysis" / "report.md").exists()
    prog = json.loads((root / "analysis" / "progress.json").read_text())
    assert prog["running"] is False and prog["failed"] is None and set(prog["done"]) == {"stems", "beats", "sections", "hits"}
    assert json.loads((root / "audio" / "stems" / "stems.json").read_text())["model"] == "imported"
    # a plain re-run keeps the imported stems (never replaces them with Demucs) and redoes nothing
    rc, out = slop("-p", "fresh-song", "analyze")
    assert rc == 0, out
    assert out["steps"]["stems"]["status"] == "up-to-date" and out["steps"]["stems"]["model"] == "imported"
    assert all(v["status"] in ("up-to-date", "skipped") for v in out["steps"].values()), out["steps"]
    assert json.loads((root / "audio" / "stems" / "stems.json").read_text())["model"] == "imported"
    # the same import again is a no-op
    rc, out = slop("-p", "fresh-song", "analyze", "--steps", "stems", "--stems-dir", str(sdir))
    assert rc == 0 and out["steps"]["stems"]["status"] == "up-to-date"
    # explicit align without lyrics: fails before any work, says what to write and what to run
    rc, out = slop("-p", "fresh-song", "analyze", "--steps", "align")
    assert rc == 1 and "lyrics/lyrics.txt" in out["error"] and "analyze --steps align" in out["error"]
    # on-screen lyrics: first the sheet, then --init fills the notes-only display.txt (its notes stay on top)
    rc, out = slop("-p", "fresh-song", "lyrics", "display", "--init")
    assert rc == 1 and "lyrics.txt has no lyric lines" in out["error"]
    tpl_notes = (root / "lyrics" / "lyrics.txt").read_text(encoding="utf-8")
    (root / "lyrics" / "lyrics.txt").write_text(tpl_notes + "[Verse 1]\nfeel the A G I tonight\nsing it loud\n",
                                                 encoding="utf-8")
    rc, out = slop("-p", "fresh-song", "lyrics", "display")
    assert rc == 1 and "lyrics display --init" in out["error"] and "only notes" in out["error"]
    rc, out = slop("-p", "fresh-song", "lyrics", "display", "--init")
    assert rc == 0 and out["created"], out
    disp = (root / "lyrics" / "display.txt").read_text(encoding="utf-8")
    assert disp.startswith("[display.txt:") and "[Verse 1]" in disp and "feel the AGI|3 tonight" in disp
    rc, out = slop("-p", "fresh-song", "lyrics", "display", "--init")              # idempotent: kept, checked
    assert rc == 0 and not out["created"] and "kept the existing" in out["text"]
    # a different song after an import: analyze stops instead of mixing stems of two songs
    other = synth.make_song(dur=14.0, drop_at=7.0, seed=3)
    take2 = write_audio(tmp_path / "take2.wav", np.stack([other["mix"], other["mix"]]), 44100)
    rc, out = slop("-p", "fresh-song", "song", "ingest", str(take2), "--force")
    assert rc == 0, out
    rc, out = slop("-p", "fresh-song", "analyze", "--steps", "stems")
    assert rc == 1 and "--stems-dir" in out["error"] and "--force" in out["error"]
    prog = json.loads((root / "analysis" / "progress.json").read_text())
    assert prog["running"] is False and prog["failed"]["step"] == "stems"


def test_heartbeat_lines_go_to_stderr(tmp_path, capsys):
    import time

    from slop.audio.common import Heartbeat
    with Heartbeat("stems", every=0.05):
        time.sleep(0.18)
    err = capsys.readouterr().err
    assert "stems: running" in err and "still running" in err and "stems: done" in err


@pytest.mark.parametrize("which", ["lyrics", "display"])
def test_template_lyric_files_have_no_lyric_lines(which):
    from slop.audio.display import read_display
    tpl = ROOT / "templates" / "project" / "lyrics" / f"{which}.txt"
    if not tpl.exists():
        pytest.skip("project template not present")
    assert (al.read_sheet(tpl) if which == "lyrics" else read_display(tpl)) == []
