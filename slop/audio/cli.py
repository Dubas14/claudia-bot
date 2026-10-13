"""CLI for slop.audio (router contract: register(subparsers); every command sets func(args) -> dict with "text").

  slop song ingest FILE [--force]
  slop song sections [--set NAME@START,... | --clear]   (START: 0, seconds, barK (from 0), lineN; replaces ALL)
  slop song bars [--phase 0-3|auto] [--method kick|harmony|auto]   (bars count from 0)
  slop analyze [--steps stems,align,beats,hits,sections[,spectrum]] [--whisper-fallback|--no-whisper] [--force]
               [--stems-dir DIR]   (minutes on CPU: run it as a background job, poll analysis/progress.json)
  slop lyrics lint [FILE] [--line TEXT --mode spoken|sung|chant] [--grid] [--write-fixed]
  slop lyrics check [--yes] [--write | --apply | --apply-lines N,M]   (Whisper: what the take sings vs the sheet,
                    ~$0.002, ledgered; free when the transcription is cached)
  slop lyrics display [--init] [--force]
  slop lyrics fix (--word I | --line L) (--t0 S [--t1 S] | --shift S)
  slop audio window CLIP --t0 S --t1 S [--mode clean|mix] [--words "exact sung words"] [--tokens 41,42] [--listen]
Heavy imports happen inside the command functions.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from slop.config import SlopError, resolve_project


def _group(subparsers, name: str, help_: str):
    """Get-or-create a command group (another module may own the same top-level word)."""
    p = subparsers.choices.get(name) if hasattr(subparsers, "choices") else None
    if p is None:
        p = subparsers.add_parser(name, help=help_, description=help_)
        p.set_defaults(func=lambda args, _p=p: {"text": _p.format_help()})
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a
    return p.add_subparsers(dest=f"{name}_cmd", metavar="SUBCOMMAND")


def _pdir(args) -> Path:
    return resolve_project(getattr(args, "project", None))


# ---------------------------------------------------------------- song ingest
def cmd_ingest(args) -> dict:
    from .ingest import ingest
    return ingest(_pdir(args), args.file, force=args.force)


def cmd_sections(args) -> dict:
    from .overrides import sections_cmd
    return sections_cmd(_pdir(args), set_spec=args.set, clear=args.clear)


def cmd_bars(args) -> dict:
    from .overrides import bars_cmd
    return bars_cmd(_pdir(args), phase=args.phase, method=args.method)


# ---------------------------------------------------------------- analyze
def cmd_analyze(args) -> dict:
    from .analyze import parse_steps, run
    return run(_pdir(args), parse_steps(args.steps), force=args.force, whisper_fallback=args.whisper_fallback,
               whisper_model=args.whisper_model, yes=args.yes, allow_digits=args.allow_digits, stems_dir=args.stems_dir,
               no_whisper=args.no_whisper)


# ---------------------------------------------------------------- lyrics
def cmd_lint(args) -> dict:
    from . import scansion as S
    from .common import Paths, lyrics_cfg, read_json
    from .lyrics import lint_text, write_fixed
    pdir = None
    try:
        pdir = _pdir(args)
    except SlopError:
        if not args.file and not args.line:
            raise
    from slop.util import input_path, not_found
    path = input_path(pdir, args.file) if args.file else (Paths(pdir).lyrics if pdir else None)
    if args.file and not args.line and (path is None or not path.exists()):
        raise SlopError(not_found(pdir, args.file, "lyrics file"))
    bpm = args.bpm
    if bpm is None and pdir is not None:
        bpm = (read_json(Paths(pdir).beats, {}) or {}).get("bpm")
    bpm = float(bpm or S.BPM)
    cfg = dict(lyrics_cfg(pdir))
    if args.ban:
        b = cfg.get("banned") or {}
        b = {w: "banned for this project" for w in b} if isinstance(b, list) else dict(b)
        b.update({w.lower(): "banned (--ban)" for w in args.ban})
        cfg["banned"] = b
    if args.line:
        header = f"[{args.mode}{' ' + str(args.bars) + ' bars' if args.bars else ''}]"
        text = f"{header}\n{args.line}\n"
        pron = Paths(pdir).pron if pdir else None
    else:
        if path is None or not path.exists():
            raise SlopError(f"no lyrics file {path}: pass FILE, or write lyrics/lyrics.txt in the project")
        text = path.read_text(encoding="utf-8")
        pron = path
    out = lint_text(text, bpm, cfg, pron, args.section, args.grid)
    out["file"] = str(path) if path and not args.line else None
    out["bpm"] = bpm
    if args.write_fixed and path and not args.line:
        if out["fixed"]:
            dst = write_fixed(path, out["fixed"])
            out["fixed_file"] = str(dst)
            out["text"] += f"\nwrote {dst} (mechanical fixes applied; review it, then replace the original)"
        else:
            out["text"] += "\nnothing to fix mechanically"
    return out


def cmd_check(args) -> dict:
    from .check import check, parse_lines
    return check(_pdir(args), yes=args.yes, model=args.whisper_model, write=args.write, apply=args.apply,
                 apply_lines=parse_lines(args.apply_lines))


def cmd_display(args) -> dict:
    from .display import build
    return build(_pdir(args), init=args.init, force=args.force)


def cmd_fix(args) -> dict:
    from .lyrics import fix
    return fix(_pdir(args), word=args.word, line=args.line, t0=args.t0, t1=args.t1, shift=args.shift, note=args.note)


# ---------------------------------------------------------------- audio window
def cmd_window(args) -> dict:
    from .window import make_window, parse_token_list
    toks = parse_token_list(args.tokens) if args.tokens is not None else None
    out = make_window(_pdir(args), args.clip, args.t0, args.t1, args.mode, args.words, listen=args.listen, tokens=toks)
    out["text"] = out.pop("text_summary")
    return out


def register(subparsers) -> None:
    F = argparse.RawDescriptionHelpFormatter
    song = _group(subparsers, "song", "the song: ingest, section names, bar lines")
    p = song.add_parser("ingest", help="copy/convert a song to audio/song.wav (44.1 kHz stereo) + loudness stats",
                        formatter_class=F, description="Copy/convert the delivered song (wav/mp3/flac/m4a) to "
                        "audio/song.wav, 44.1 kHz stereo, and record loudness (LUFS, true peak).\n"
                        "example: slop -p my-song song ingest ~/Downloads/My_Song.wav")
    p.add_argument("file", help="the song file")
    p.add_argument("--force", action="store_true", help="replace a different song already ingested")
    p.set_defaults(func=cmd_ingest)

    p = song.add_parser("sections", help="show / set the song's sections (names + starts); guesses are marked",
                        formatter_class=F, description=
                        "Show the sections in analysis/beats.json and where each name came from: a lyric tag in "
                        "lyrics/lyrics.txt ([Verse 1], [Chorus] ...), the owner (--set), or a GUESS from energy and "
                        "vocals (unconfirmed). The board paces shots and plans clips by these names.\n"
                        "--set REPLACES ALL sections (the tagged ones too): list every section, in any order. It "
                        "writes project.json audio.sections (each section ends where the next begins; a list that "
                        "does not start at 0 gets an intro at 0), rebuilds the sections, rewrites analysis/report.md, "
                        "logs DECISIONS.md and checks the storyboard: an untouched draft is marked stale; a board the "
                        "lead has written into is never changed - the output lists the shots to re-check.\n"
                        "START: 0, seconds (40.4 or 1:02.5; snapped to the nearest bar line), barK (bars count from 0: "
                        "bar 0 is the first bar line, as `slop song bars` prints it) or lineN (lyric line N, its first "
                        "word snapped to the bar line at or before it). The plain command shows each section's "
                        "current START.\n"
                        "To confirm ONE guessed section of a tagged sheet, do not use --set: add a tag line in "
                        "lyrics/lyrics.txt (an empty [Instrumental] line names a stretch with no vocals) and run "
                        "`slop -p my-song analyze --steps sections`.\n"
                        "examples: slop -p my-song song sections\n"
                        "          slop -p my-song song sections --set \"intro@0,verse1@bar8,chorus1@line9,outro@bar94\"\n"
                        "            (the FORMAT only: list YOUR song's sections, every one, from the plain command)\n"
                        "          slop -p my-song song sections --clear")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--set", default=None, metavar="SPEC",
                   help='"NAME@START,..." listing EVERY section (it replaces all of them); START = 0, seconds, barK '
                        '(from 0) or lineN')
    g.add_argument("--clear", action="store_true", help="drop the override: back to the lyric tags / the guess")
    p.set_defaults(func=cmd_sections)

    p = song.add_parser("bars", help="show / set where the bar lines fall (the downbeat phase; bars count from 0)",
                        formatter_class=F,
                        description="Bar lines are every 4th beat of the beat map; the phase (0-3) says which beat "
                        "starts bar 0 (the first bar line). Bars count from 0 everywhere: bar k starts at downbeat k "
                        "(`song sections --set NAME@barK`, the report's bar columns). Without options: the current "
                        "phase and, per phase, its first bar line and the kick and chord votes.\n"
                        "--phase N writes project.json audio.downbeat_phase and re-derives the bars at once (no audio "
                        "re-analysis), then rebuilds the sections and hits.json, rewrites analysis/report.md, logs "
                        "DECISIONS.md and checks the storyboard (an untouched draft is marked stale; an edited board "
                        "is never changed: the output lists the shots to re-check). --phase auto goes back to the "
                        "vote. Use this command, not a hand edit of project.json (that skips the log and costs a full "
                        "beat-map rebuild).\n"
                        "examples: slop -p my-song song bars\n"
                        "          slop -p my-song song bars --phase 2\n"
                        "          slop -p my-song song bars --method harmony")
    p.add_argument("--phase", default=None, metavar="N", help="0-3: the beat that starts bar 0; auto = the vote")
    p.add_argument("--method", default=None, choices=["kick", "harmony", "auto"],
                   help="which vote sets the phase when no --phase is set (default kick)")
    p.set_defaults(func=cmd_bars)

    p = subparsers.add_parser("analyze", help="stems, word alignment, beat map, hits, sections + ear-check report",
                              formatter_class=F, description=
                              "Analyse audio/song.wav on CPU. Steps (default all but spectrum): stems (Demucs htdemucs), "
                              "align (wav2vec2 forced alignment of lyrics/lyrics.txt), beats (variable-tempo beat map), "
                              "sections, hits (kick/snare/hat, real hits, risers, fills), spectrum (optional).\n"
                              "Writes analysis/beats.json, words.json, hits.json and report.md (read its EAR CHECK).\n"
                              "Idempotent: unchanged inputs are skipped; --force redoes.\n\n"
                              "TIME: a 5-minute song takes about 3.5-6 min on an 8-vCPU box (first run also downloads "
                              "~1.35 GB of models). Run it as a BACKGROUND job and poll analysis/progress.json "
                              "({running, step, done, failed}); stderr prints one line per step and a heartbeat every 30 s; "
                              "the final JSON is also saved to analysis/last-run.json.\n"
                              "  nohup slop --json -p my-song analyze > analysis.log 2>&1 &\n"
                              "  cat <project folder>/analysis/progress.json   (until \"running\": false)\n\n"
                              "No lyrics yet? Alignment is skipped with a note; write lyrics/lyrics.txt and run "
                              "`slop -p my-song analyze --steps align`.\n"
                              "Whisper: --whisper-fallback re-times sung lines (OpenRouter, ~$0.002/song, ledgered); later "
                              "plain runs reuse that transcription for free; --no-whisper turns it off (until the next "
                              "--whisper-fallback). A plain run never pays.\n"
                              "examples: slop -p my-song analyze\n"
                              "          slop -p my-song analyze --steps align --whisper-fallback\n"
                              "          slop -p my-song analyze --stems-dir ~/Downloads/my-song-stems")
    p.add_argument("--steps", help="comma list from stems,beats,sections,align,hits,spectrum (default stems,align,beats,hits,sections)")
    p.add_argument("--whisper-fallback", action="store_true",
                   help="re-time low-confidence (sung) words with Whisper via OpenRouter (needs OPENROUTER_API_KEY; ~$0.002/song)")
    p.add_argument("--no-whisper", action="store_true",
                   help="wav2vec2 times only, also for later plain runs (--whisper-fallback turns Whisper back on, free if cached)")
    p.add_argument("--whisper-model", default=None, help="OpenRouter transcription model (default openai/whisper-large-v3)")
    p.add_argument("--stems-dir", default=None,
                   help="use these stems (files named vocals*, drums*, bass*, other*) instead of Demucs; later runs keep "
                        "them (--force switches back to Demucs)")
    p.add_argument("--allow-digits", action="store_true", help="align even if the sheet has digits/symbols (they are dropped)")
    p.add_argument("--force", action="store_true", help="redo every requested step")
    p.add_argument("--yes", action="store_true", help="confirm the (tiny) Whisper spend if the project asks for confirmation")
    p.set_defaults(func=cmd_analyze)

    ly = _group(subparsers, "lyrics", "lyric sheet tools: lint (scansion), display tokens, timing fixes")
    p = ly.add_parser("lint", help="scansion report + Suno lint + fixes for a lyrics file", formatter_class=F,
                      description="Score how each line will sit on the beat when Suno sings it, flag Suno formatting "
                      "problems and AI-lyric tells, suggest mechanical fixes.\nSection headers in [brackets] set the "
                      "delivery: spoken (default) / sung (chorus, hook, sung) / chant (chant, shout, drop).\n"
                      "examples: slop -p my-song lyrics lint\n          slop lyrics lint draft.md --grid\n"
                      "          slop lyrics lint --line \"Look one. A G I era.\" --mode spoken")
    p.add_argument("file", nargs="?", help="lyrics file (default: the project's lyrics/lyrics.txt)")
    p.add_argument("--line", help="score one line instead of a file")
    p.add_argument("--mode", default="spoken", choices=["spoken", "sung", "chant"], help="delivery for --line")
    p.add_argument("--bars", type=float, help="bar budget for --line")
    p.add_argument("--section", help="only sections whose header contains this")
    p.add_argument("--bpm", type=float, help="tempo (default: the project's beat map, else 128)")
    p.add_argument("--grid", action="store_true", help="draw each line on the 16th grid")
    p.add_argument("--ban", action="append", default=[], help="extra banned word (repeatable)")
    p.add_argument("--write-fixed", action="store_true", help="write FILE.fixed.txt with digits/symbols/acronyms spelled out")
    p.set_defaults(func=cmd_lint)

    p = ly.add_parser("check", help="what the take sings vs lyrics.txt, per line, with fixes (Whisper, ~$0.002)",
                      formatter_class=F, description=
                      "Transcribe the vocal stem with Whisper via OpenRouter (~$0.002 per song, ledgered and "
                      "budget-checked; FREE when `slop analyze --whisper-fallback` or an earlier check already "
                      "transcribed this vocal stem) and compare it with lyrics/lyrics.txt line by line. For Lyria/Suno "
                      "takes that change words: the aligner forces the sheet onto the audio, so changed words land in "
                      "the wrong place silently.\n"
                      "Per line: ok / spelling (sounds the same: kept) / changed / extra / missing / not-heard, a "
                      "proposed line for changed/extra marked LIKELY or UNSURE (shouts, lines heard as written "
                      "elsewhere, small words, spelled-out letters and echoes are unsure: Whisper mishears them), and "
                      "extra vocals heard between lines. Writes analysis/lyrics-check.json. Show the proposals to the "
                      "owner before changing the sheet.\n"
                      "Needs the vocal stem (`slop analyze --steps stems`) and OPENROUTER_API_KEY (unless cached).\n"
                      "examples: slop -p my-song lyrics check\n"
                      "          slop -p my-song lyrics check --write    (lyrics/lyrics.proposed.txt, sheet untouched)\n"
                      "          slop -p my-song lyrics check --apply    (owner agreed: the LIKELY ones into lyrics.txt, "
                      "the old sheet kept as a new lyrics.txt.<time>.bak)\n"
                      "          slop -p my-song lyrics check --apply-lines 14,25   (exactly the lines the owner confirmed)")
    p.add_argument("--yes", action="store_true", help="confirm the spend if the project asks for confirmation "
                   "(budget.confirm_over_usd)")
    p.add_argument("--whisper-model", default=None, help="OpenRouter transcription model (default openai/whisper-large-v3)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="write lyrics/lyrics.proposed.txt with the LIKELY proposals")
    g.add_argument("--apply", action="store_true",
                   help="apply the LIKELY proposals to lyrics/lyrics.txt (a new timestamped .bak each time)")
    g.add_argument("--apply-lines", default=None, metavar="N,M",
                   help="apply exactly these lines' proposals (any confidence) to lyrics/lyrics.txt (a new timestamped "
                        ".bak each time)")
    p.set_defaults(func=cmd_check)

    p = ly.add_parser("display", help="build/validate on-screen tokens (lyrics/display.txt, \"TEXT|n\")", formatter_class=F,
                      description="lyrics/display.txt: one line per lyric line, written as it should read on screen. "
                      "\"TEXT|n\" = TEXT spans n sung words (\"AGI|3\" for \"A G I\", \"+25%|3\" for \"plus twenty five\"); "
                      "\"TEXT|0\" rides on the next token; ~strike~ *accent* _mono_.\nValidates every line against "
                      "lyrics/lyrics.txt and, after `slop analyze`, writes analysis/lyrics-display.json.\n"
                      "example: slop -p my-song lyrics display --init")
    p.add_argument("--init", action="store_true",
                   help="create display.txt from lyrics.txt when it is missing or holds only [notes] (kept otherwise)")
    p.add_argument("--force", action="store_true", help="with --init: rebuild display.txt from lyrics.txt (edits are lost)")
    p.set_defaults(func=cmd_display)

    p = ly.add_parser("fix", help="fix word timing by hand (kept by later analyze runs)", formatter_class=F,
                      description="examples: slop -p my-song lyrics fix --word 41 --t0 47.46 --t1 47.60\n"
                      "          slop -p my-song lyrics fix --line 9 --shift 2.6")
    p.add_argument("--word", type=int, help="word index (as listed in analysis/report.md / words.json)")
    p.add_argument("--line", type=int, help="lyric line number (1-based)")
    p.add_argument("--t0", type=float, help="new start (s)")
    p.add_argument("--t1", type=float, help="new end (s), --word only")
    p.add_argument("--shift", type=float, help="move by this many seconds (+ later)")
    p.add_argument("--note", help="why (kept in words.json)")
    p.set_defaults(func=cmd_fix)

    au = _group(subparsers, "audio", "audio windows for video clips")
    p = au.add_parser("window", help="cut a clip's reference audio: clean vocal (only its words) or the mix",
                      formatter_class=F, description="Writes audio/windows/<CLIP>.mp3 (+ .wav, .json).\n"
                      "clean: the vocal stem with everything but the clip's words muted, -16 dBFS RMS, -1 dBFS peak "
                      "(sung clips).\nmix: the song as is (motion clips).\n"
                      "examples: slop -p my-song audio window W02 --t0 64.1 --t1 70.1 --words \"Why would I deceive you?\"\n"
                      "          slop -p my-song audio window W02c1 --t0 66.0 --t1 71.0 --tokens 88,89,90\n"
                      "          slop -p my-song audio window M07 --t0 80 --t1 86 --mode mix")
    p.add_argument("clip", help="clip id (letters, digits, . _ -)")
    p.add_argument("--t0", type=float, required=True, help="window start (song seconds)")
    p.add_argument("--t1", type=float, required=True, help="window end (song seconds)")
    p.add_argument("--mode", default="clean", choices=["clean", "mix"])
    p.add_argument("--words", default=None, help="clean mode: keep only these exact sung words (in order)")
    p.add_argument("--tokens", default=None, metavar="I,J,K-L",
                   help="clean mode: keep exactly these words (indices from analysis/words.json, e.g. 41,42,45-47) - "
                        "use it when a word repeats inside the window and --words could pick the wrong one")
    p.add_argument("--listen", action="store_true",
                   help="ear-check excerpt: write to analysis/listen/ instead of audio/windows/ (mix mode only)")
    p.set_defaults(func=cmd_window)
