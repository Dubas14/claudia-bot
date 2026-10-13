"""Song sections -> beats.json "sections": [{name, t0, t1, energy, vocals, bar0, bar1, source, ...}] (contract §4.2).

Bars are counted from 0 everywhere (bar k starts at downbeats[k]; bar -1 is the pickup before the first downbeat): the
sections' bar0/bar1, `@barK`, the report's tables and `slop song bars` all use that numbering.
Three sources, in this order of authority (each section says which in `source`):
  "set"        the owner's override: project.json audio.sections [{"name": "intro", "t0": 0}, {"name": "verse1",
               "bar": 8}, {"name": "chorus1", "line": 9}] (`slop song sections --set NAME@START,...` writes it; bar k
               starts at downbeats[k]; line N = the 1-based lyric line, snapped like a tag; seconds snap to the NEAREST
               bar line, or 0 = the song start - times picked by ear are a little off, and the board cuts and paces on
               these boundaries); each section ends where the next begins; a list that does not start at 0 gets an
               "intro" before it ("intro0" when the list already has an intro). Replaces everything below.
  "lyrics-tag" section tags in lyrics/lyrics.txt ([Intro], [Verse 1: spoken], [Pre-Chorus], [Chorus - sung], [Final
               Chorus], [Bridge], [Break], [Drop], [Outro] ...): each tagged block starts at its FIRST ALIGNED WORD,
               snapped to the downbeat at or before it; a first word in the last `audio.section_pickup_beats` (default
               0.1) beats before a bar line counts as on it (alignment jitter must not start a chorus a whole bar early).
               Measured on two songs against hand-made section tables (tests/bench_audio_ev.py --pickups): 0 / 0.1 /
               0.25 beats give the same starts; a larger tolerance (sung pickups start the next bar) is MIXED, not
               better - see slop/audio/__init__.py - so 0.1 is kept. A tag with no lyric lines after it
               ([Instrumental], [Break], [End]) names the no-vocal stretch between its neighbours, if there is one (a
               bar or more); a tag that names nothing is listed in the notes with the reason.
  "heuristic"  everything the tags do not cover, and the whole song when the sheet has no tags: the no-vocal stretch
               after a block's last word (>= 2 bars before the next section; >= 4 bars inside a block) becomes its own
               section, the span before the first tag too. Names are a GUESS and are marked `"unconfirmed": true` here
               and UNCONFIRMED in analysis/report.md; confirm_hints() says how to confirm each one (an empty tag line
               for a no-vocal stretch, a tag above an untagged line, or a full --set list).
Heuristic boundaries (whole song, no tags): port of the GPU analyze script - agglomerative segmentation
(librosa.segment.agglomerative) of beat-synchronous chroma_cqt + 13 MFCC (each normalised, 44.1 kHz),
k = clamp(duration / 12, 6, 14) segments, every boundary snapped to the nearest downbeat. Changes: features are
beat-synced on the variable beat map (the original used its single-period grid); boundaries closer than ~2 bars to the
previous one or to the end are dropped; FIXED off-by-one: librosa's sync() puts the frames before the first beat in
column 0, so boundary column b starts at beats[b - 1] (the original read beats[b], one beat late, before snapping to a
downbeat); the sections are cleared by the beats step whenever the bars move and `slop analyze` rebuilds them in the
same run (and again after `align` when the sheet has tags: the tag starts need the word timing).
Heuristic names (the CLODYSSEY timeline named sections by hand from the per-bar stem energy): a segment with vocals in
< 15 % of its frames is "intro" before the first sung segment, "outro" after the last one, else "break"; sung segments
whose mix energy is >= 0.8 of the loudest sung segment are "chorusN", the rest "verseN".
Benchmark (two songs, hand-made section tables, tests/bench_audio_ev.py): see slop/audio/__init__.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from slop.config import SlopError

from .common import (Paths, audio_cfg, fingerprint, load_mono, need_module, project_cmd, read_json, state_get,
                     state_set, write_json)

PICKUP_BEATS = 0.1          # a first word this close (beats) before a bar line starts the section on it (jitter)
GAP_END_BARS = 2.0          # no-vocal stretch after a block's last word that becomes its own section
GAP_INNER_BARS = 4.0        # ... inside a block (between two of its lines)
VOCAL_SHARE = 0.15          # a span with vocals in fewer frames than this is instrumental
NUMBERED = ("verse", "chorus", "break", "prechorus", "postchorus", "hook", "bridge", "drop", "inst", "section")
KEEP_WHOLE = ("intro", "outro", "break", "drop", "inst")     # tagged blocks whose no-vocal stretches stay inside them

# (kind, regex on the tag's head) - first match wins; kinds are names the board's section_kind() understands
TAG_KINDS = [
    ("prechorus", r"\bpre[\s-]?(chorus|hook)\b|\bbuild[\s-]?up\b|\bbuild\b|\blift\b|\bramp\b"),
    ("postchorus", r"\bpost[\s-]?chorus\b"),
    ("chorus", r"\bchorus\b|\brefrain\b"),
    ("hook", r"\bhook\b"),
    ("verse", r"\bverse\b|\brap\b"),
    ("intro", r"\bintro\b|\bopening\b"),
    ("outro", r"\boutro\b|\bcoda\b|\bending\b|\bend\b|\bfade[\s-]?out\b|\btag\b"),
    ("bridge", r"\bbridge\b|\bmiddle[\s-]?8\b"),
    ("break", r"\bbreak[\s-]?down\b|\bbreak\b"),
    ("drop", r"\bdrop\b"),
    ("inst", r"\binstrumental\b|\binterlude\b|\bsolo\b"),
]
_HEAD_SPLIT = re.compile(r"\s*(?::|\s[-–—]\s|[-–—]{2}|\(|,|\||;)\s*")


# ---------------------------------------------------------------- lyric tags
def tag_kind(text: str) -> str | None:
    """'[Verse 1: spoken]' -> 'verse'; a note or a delivery cue ('[Whispered]', '[the words AS SUNG ...]') -> None."""
    s = text.strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    head = _HEAD_SPLIT.split(s[1:-1].strip(), maxsplit=1)[0].strip().lower()
    if not head or len(head.split()) > 4:
        return None
    for kind, rx in TAG_KINDS:
        if re.search(rx, head):
            return kind
    return None


def parse_blocks(path: Path) -> list[dict]:
    """lyrics.txt -> blocks in order: {tag (text or None), kind (or None), lines [lyric line indices, 0-based as in
    words.json]}. Lyric lines are counted exactly as align.read_sheet counts them (every non-empty line not starting
    with '['); bracket lines that are not section tags (notes, delivery cues) are skipped and do not start a block."""
    if not Path(path).exists():
        return []
    blocks: list[dict] = [{"tag": None, "kind": None, "lines": []}]
    li = 0
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith("["):
            k = tag_kind(s)
            if k:
                blocks.append({"tag": s, "kind": k, "lines": []})
            continue
        blocks[-1]["lines"].append(li)
        li += 1
    if not blocks[0]["lines"]:
        blocks.pop(0)
    return blocks


def has_tags(path: Path) -> bool:
    return any(b["tag"] for b in parse_blocks(path))


# ---------------------------------------------------------------- snapping
def snap_start(t: float, down: np.ndarray, beats: np.ndarray, pickup_beats: float = PICKUP_BEATS) -> float:
    """The downbeat at or before t - or the next one when t is a pickup (within pickup_beats beats before it)."""
    if not len(down):
        return 0.0
    j = int(np.searchsorted(down, t + 1e-6, side="right"))      # down[j] is the first bar line after t
    if j < len(down) and pickup_beats > 0:
        k = int(np.searchsorted(beats, down[j], side="left"))
        per = float(beats[k] - beats[k - 1]) if 0 < k < len(beats) else float(np.median(np.diff(beats))) if len(beats) > 1 else 0.5
        if down[j] - t <= pickup_beats * per + 1e-6:
            return float(down[j])
    return float(down[j - 1]) if j > 0 else 0.0


def _first_down_at_or_after(t: float, down: np.ndarray) -> float | None:
    j = int(np.searchsorted(down, t - 1e-6, side="left"))
    return float(down[j]) if j < len(down) else None


# ---------------------------------------------------------------- heuristic boundaries (no tags)
def env24(x: np.ndarray, sr: int, dur: float) -> np.ndarray:
    n = int(np.ceil(dur * 24))
    hop = sr / 24
    e = np.zeros(n, np.float32)
    for i in range(n):
        a = int(i * hop)
        b = int(min(len(x), a + hop))
        if b > a:
            e[i] = np.sqrt(np.mean(x[a:b].astype(np.float64) ** 2))
    return e / (np.percentile(e, 99.5) + 1e-9) if len(e) else e


def boundaries(y: np.ndarray, sr: int, beats: np.ndarray, downbeats: np.ndarray, dur: float) -> list[float]:
    librosa = need_module("librosa", "section analysis")
    C = librosa.feature.chroma_cqt(y=y, sr=sr)
    Mf = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    bf = librosa.time_to_frames(beats, sr=sr)
    bf = bf[bf < C.shape[1]]
    Fs = librosa.util.sync(np.vstack([librosa.util.normalize(C), librosa.util.normalize(Mf)]), bf)
    k = max(6, min(14, int(dur / 12)))
    k = min(k, Fs.shape[1])
    if k < 2 or not len(downbeats):
        return [0.0]
    bounds = librosa.segment.agglomerative(Fs, k)
    grid = np.concatenate([[0.0], beats[: len(bf)]])          # sync() frame 0 spans [0, first beat)
    return sorted({float(downbeats[int(np.argmin(np.abs(downbeats - grid[min(b, len(grid) - 1)])))]) for b in bounds})


def heuristic_kind(vocals: float, energy: float, emax_sung: float, before_sung: bool, after_sung: bool) -> str:
    if vocals < VOCAL_SHARE:
        return "intro" if before_sung else ("outro" if after_sung else "break")
    return "chorus" if energy >= 0.8 * (emax_sung or 1.0) else "verse"


def name_sections(segs: list[dict]) -> list[dict]:
    sung = [i for i, s in enumerate(segs) if s["vocals"] >= VOCAL_SHARE]
    emax = max((segs[i]["energy"] for i in sung), default=1.0) or 1.0
    for i, s in enumerate(segs):
        s["kind"] = heuristic_kind(s["vocals"], s["energy"], emax, not sung or i < sung[0], bool(sung) and i > sung[-1])
    return number_names(segs)


def number_names(segs: list[dict]) -> list[dict]:
    """kind -> name in time order: numbered kinds always get a number (verse1, chorus2), others only from the second
    one on (intro, intro2). Consumes "kind"; keeps every other key."""
    total: dict[str, int] = {}
    for s in segs:
        total[s["kind"]] = total.get(s["kind"], 0) + 1
    count: dict[str, int] = {}
    out = []
    for s in segs:
        s = dict(s)
        k = s.pop("kind")
        count[k] = count.get(k, 0) + 1
        s["name"] = f"{k}{count[k]}" if k in NUMBERED or count[k] > 1 else k
        out.append(s)
    return out


# ---------------------------------------------------------------- tag sections
def _share(env: np.ndarray, t0: float, t1: float) -> float:
    i0, i1 = int(t0 * 24), max(int(t0 * 24) + 1, int(t1 * 24))
    return float(np.mean(env[i0:i1] > 0.06)) if i0 < len(env) else 0.0


def tag_sections(blocks: list[dict], words: list[dict], beats: np.ndarray, down: np.ndarray, dur: float,
                 ev: np.ndarray, pickup: float = PICKUP_BEATS, pdir: Path | None = None) -> tuple[list[dict], list[str]]:
    """Sections from tagged blocks + heuristic spans for what the tags do not cover. -> (segments with kind, source,
    tag, lines, t0, t1; notes)."""
    def cmd(rest: str) -> str:
        return project_cmd(pdir, rest) if pdir is not None else f"slop {rest}"
    notes: list[str] = []
    by_line: dict[int, list[dict]] = {}
    for w in words:
        if w.get("t0") is not None:
            by_line.setdefault(int(w["line"]), []).append(w)
    bar = float(np.median(np.diff(down))) if len(down) > 1 else 2.0
    # 1. anchors: each block with an aligned word starts at its first word (snapped)
    anchors: list[dict] = []
    pending_empty: list[dict] = []           # tags with no lyric lines, waiting for the next anchor
    for b in blocks:
        ws = [w for li in b["lines"] for w in by_line.get(li, [])]
        if not ws:
            if b["tag"] and not b["lines"]:
                pending_empty.append(b)
            elif b["tag"]:
                notes.append(f"tag {b['tag']} has lyric lines but none of their words is aligned: it was skipped")
            continue
        first = min(w["t0"] for w in ws)
        start = snap_start(first, down, beats, pickup)
        if anchors and start <= anchors[-1]["t0"] + 1e-6:
            nxt = _first_down_at_or_after(anchors[-1]["t0"] + 1e-3, down)
            if nxt is None or nxt > max(w["t1"] for w in ws):
                if b["tag"]:
                    notes.append(f"tag {b['tag']} starts in the same bar as the previous section: merged into it")
                anchors[-1]["words"] += ws
                anchors[-1]["lines"] += b["lines"]
                continue
            start = nxt
        anchors.append({"t0": start, "kind": b["kind"], "tag": b["tag"], "lines": list(b["lines"]), "words": list(ws),
                        "empty_before": pending_empty})
        pending_empty = []
    trailing_empty = pending_empty
    if not anchors:
        return [], notes
    # 2. spans: the head before the first anchor, then each anchor up to the next (split at long no-vocal stretches)
    segs: list[dict] = []

    def named(kind, tag, empt: list[dict]) -> dict:
        """kind/tag/source of a no-vocal span: the last empty tag before it names it, else the heuristic does."""
        if empt:
            empt[-1]["used"] = True
            return {"kind": empt[-1]["kind"], "tag": empt[-1]["tag"], "source": "lyrics-tag"}
        return {"kind": kind, "tag": tag, "source": "heuristic"}

    if anchors[0]["t0"] > 1e-6:
        if anchors[0]["t0"] < 1.9 * bar or anchors[0]["kind"] == "intro":
            anchors[0]["t0"] = 0.0                       # an intro tag starts the song; a sliver joins the first tag
        else:
            segs.append({"t0": 0.0, "t1": anchors[0]["t0"], "lines": [], **named(None, None, anchors[0]["empty_before"])})
    for i, a in enumerate(anchors):
        end = anchors[i + 1]["t0"] if i + 1 < len(anchors) else dur
        src = "lyrics-tag" if a["tag"] else "heuristic"
        ws = sorted(a["words"], key=lambda w: w["t0"])
        # an intro / outro / break / drop / instrumental block keeps its own no-vocal stretches (SP's intro: a spoken
        # line, a sung line, then three instrumental bars where the beat drops in - still the intro)
        keep_whole = a["kind"] in KEEP_WHOLE
        # inner stretches with no vocals (>= GAP_INNER_BARS) split the block; the part after keeps the later lines
        cuts: list[tuple[float, float]] = []
        for w0, w1 in (zip(ws, ws[1:]) if not keep_whole else ()):
            g0 = _first_down_at_or_after(w0["t1"] + 0.25, down)
            if g0 is None:
                continue
            g1 = snap_start(w1["t0"], down, beats, pickup)
            if g1 - g0 >= GAP_INNER_BARS * bar - 1e-6 and g1 < end - 1e-6 and _share(ev, g0, g1) < VOCAL_SHARE:
                cuts.append((g0, g1))
        bounds = [a["t0"]] + [x for c in cuts for x in c]
        pieces = []
        for k in range(len(cuts) + 1):
            t0 = bounds[2 * k]
            t1 = bounds[2 * k + 1] if k < len(cuts) else end
            lines = sorted({w["line"] for w in ws if (k == 0 or w["t0"] >= t0 - 1.0) and
                            (k == len(cuts) or w["t0"] < t1)})
            pieces.append({"t0": t0, "t1": t1, "kind": a["kind"], "tag": a["tag"], "lines": lines, "source": src})
            if k < len(cuts):
                pieces.append({"t0": cuts[k][0], "t1": cuts[k][1], "lines": [], **named(None, None, [])})
        # the no-vocal stretch after the block's last word (an [Instrumental]/[Outro] tag without lines names it)
        tail = _first_down_at_or_after(max(w["t1"] for w in ws) + 0.25, down)
        empt_next = anchors[i + 1]["empty_before"] if i + 1 < len(anchors) else trailing_empty
        need = (1.0 if empt_next else GAP_END_BARS) * bar - 1e-6        # a tag names it: one bar is enough
        if tail is not None and tail > pieces[-1]["t0"] + 1e-6 and end - tail >= need and \
                (not keep_whole or empt_next) and _share(ev, tail, end) < VOCAL_SHARE:
            pieces[-1]["t1"] = tail
            pieces.append({"t0": tail, "t1": end, "lines": [], **named(None, None, empt_next)})
        segs += pieces
    segs = [s for s in segs if s["t1"] - s["t0"] > 1e-6]
    unused = [b["tag"] for a in anchors for b in a["empty_before"] if not b.get("used")]
    if unused:
        notes.append("tag(s) without lyric lines and no no-vocal stretch of a bar or more between their neighbours to "
                     "name (ignored): " + ", ".join(unused))
    left = [b["tag"] for b in trailing_empty if not b.get("used")]
    if left:
        notes.append(", ".join(left) + " after the last lyric line names nothing (ignored): the stretch after the last "
                     "word has vocals (an ad-lib or a held note) or is shorter than a bar. If the song has an outro "
                     f"there, set the sections yourself: `{cmd('song sections --set NAME@START,...')}` REPLACES "
                     f"ALL sections, so list each one (`{cmd('song sections')}` shows each one's @START)")
    return segs, notes


def _name_heuristic(segs: list[dict]) -> None:
    """Fill in kind for heuristic spans (no tag): by vocals/energy and position, as name_sections does."""
    sung = [i for i, s in enumerate(segs) if s["vocals"] >= VOCAL_SHARE]
    emax = max((segs[i]["energy"] for i in sung), default=1.0) or 1.0
    tagged = [i for i, s in enumerate(segs) if s.get("source") != "heuristic"]
    for i, s in enumerate(segs):
        if s.get("kind"):
            continue
        before = not tagged or i < tagged[0]
        after = bool(tagged) and i > tagged[-1] and s["vocals"] < VOCAL_SHARE
        s["kind"] = heuristic_kind(s["vocals"], s["energy"], emax, before and (not sung or i <= sung[0]),
                                   after or (bool(sung) and i > sung[-1]))


# ---------------------------------------------------------------- build
def snap_nearest(t: float, down: np.ndarray) -> float:
    """The bar line nearest to t, or 0.0 (the song start) when that is nearer."""
    cand = np.concatenate([[0.0], np.asarray(down, float)])
    return float(cand[int(np.argmin(np.abs(cand - t)))])


def parse_override(over: list, down: np.ndarray, beats: np.ndarray, words: list[dict] | None,
                   pickup: float = PICKUP_BEATS, where: str = "project.json audio.sections", pdir: Path | None = None,
                   info: list | None = None) -> list[tuple[float, str]]:
    """Override entries -> [(t0, name)] in time order. Seconds snap to the nearest bar line (or 0); bar k = downbeats[k]
    (counted from 0); line N = its first aligned word snapped like a tag. `where` names the input in errors ("--set" or
    project.json); `info` collects one line per moved time ("verse1: 16.50 s -> bar 8 at 16.28 s")."""
    align_cmd = project_cmd(pdir, "analyze --steps align") if pdir is not None else "slop analyze --steps align"
    starts = []
    for s in over:
        if not isinstance(s, dict):
            raise SlopError(f"{where} entries must be objects like {{\"name\": \"verse1\", \"bar\": 8}}")
        name = str(s.get("name") or f"section{len(starts) + 1}")
        if "t0" in s:
            typed = float(s["t0"])
            t0 = snap_nearest(typed, down) if len(down) else typed
            if info is not None and abs(t0 - typed) > 1e-3:
                b = int(np.searchsorted(down, t0 + 1e-3, side="right")) - 1
                info.append(f"{name}: {typed:.2f} s -> " + (f"bar {b} at {t0:.2f} s" if b >= 0 and t0 > 0 else "0 s")
                            + " (the nearest bar line)")
        elif "bar" in s:
            b = int(s["bar"])
            if not 0 <= b < len(down):
                bars = project_cmd(pdir, "song bars") if pdir is not None else "slop song bars"
                raise SlopError(f"{where}: bar {b} is outside 0..{len(down) - 1} (bars count from 0: bar 0 is the first "
                                f"bar line; `{bars}` shows where it is)")
            t0 = float(down[b])
        elif "line" in s:
            n = int(s["line"])
            ws = [w for w in words or [] if w.get("t0") is not None and int(w["line"]) == n - 1]
            if not ws:
                raise SlopError(f"{where}: lyric line {n} has no aligned word (run `{align_cmd}` first, or give "
                                "seconds or barK)")
            t0 = snap_start(min(w["t0"] for w in ws), down, beats, pickup)
        else:
            raise SlopError(f"{where} entries need a name and either t0 (seconds), bar or line")
        starts.append((t0, name))
    starts.sort()
    return starts


def head_name(starts: list[tuple[float, str]]) -> str:
    """The name of the section added at 0 before an override list that starts later: intro, or intro0 when taken."""
    return "intro0" if any(n == "intro" for _, n in starts) else "intro"


def bar_ref(s: dict, down) -> str:
    """'@0', '@bar8' or '@40.25': the --set START that gives this section's start (bars counted from 0)."""
    t0 = float(s["t0"])
    if t0 <= 1e-3:
        return "@0"
    b = int(np.searchsorted(np.asarray(down, float), t0 + 1e-3, side="right")) - 1 if len(down) else -1
    if b >= 0 and abs(float(down[b]) - t0) <= 0.01:
        return f"@bar{b}"
    return f"@{t0:.2f}"


def confirm_hints(B: dict, pdir: Path | None, lines: list[str] | None = None) -> list[str]:
    """How to confirm the guessed (heuristic) sections of beats.json, one item per way (the report, `slop analyze` and
    `slop song sections` print these). Never a runnable --set with values: --set replaces every section, the tagged
    ones too. With a tagged sheet, a guessed no-vocal stretch is confirmed by an EMPTY tag line ([Instrumental],
    [Break], [Outro]) between the two lyric blocks around it; an untagged lyric line by a tag above it."""
    secs = B.get("sections") or []
    guess = [s for s in secs if s.get("unconfirmed") or not s.get("source")]
    if not guess:
        return []
    if lines is None and pdir is not None:
        from .align import read_sheet
        try:
            lines = read_sheet(Paths(pdir).lyrics) if Paths(pdir).lyrics.exists() else None
        except SlopError:
            lines = None

    def cmd(rest: str) -> str:
        return project_cmd(pdir, rest) if pdir is not None else f"slop {rest}"

    def quote(li: int) -> str:
        txt = (lines or [])[li] if lines and 0 <= li < len(lines) else ""
        return f' ("{txt[:40]}{"..." if len(txt) > 40 else ""}")' if txt else ""
    redo = cmd("analyze --steps sections")
    out = []
    if str(B.get("sections_from") or "").startswith("lyrics tags"):
        for s in guess:
            i = secs.index(s)
            prev = next((x for x in reversed(secs[:i]) if x.get("lines")), None)
            nxt = next((x for x in secs[i + 1:] if x.get("lines")), None)
            span = f"{s['name']} ({s['t0']:.2f}-{s['t1']:.2f} s"
            if s.get("lines"):
                a = s["lines"][0]
                out.append(f"{span}, lyric lines {a + 1}-{s['lines'][1] + 1}, no tag): put a section tag ([Verse], "
                           f"[Chorus] ...) on its own line above lyric line {a + 1}{quote(a)} in lyrics/lyrics.txt, "
                           f"then `{redo}`")
                continue
            kind = "no vocals" if (s.get("vocals") or 0) < VOCAL_SHARE else "vocals but no lyric line"
            if prev and nxt:
                a = prev["lines"][1]
                where = (f"on its own line right after lyric line {a + 1}{quote(a)}, above the tag line that starts "
                         "the next block")
                tags = "[Instrumental] or [Break]"
            elif nxt:
                b = nxt["lines"][0]
                where = f"at the top, above lyric line {b + 1}{quote(b)} and the tag line above it"
                tags = "[Intro]"
            elif prev:
                a = prev["lines"][1]
                where = f"on its own line after the last lyric line ({a + 1}{quote(a)})"
                tags = "[Outro]"
            else:
                where, tags = "", ""
            if where:
                out.append(f"{span}, {kind}): add an empty tag line such as {tags} in lyrics/lyrics.txt {where} - a tag "
                           f"with no lyric lines under it names that stretch - then `{redo}`")
    else:
        out.append("put section tags ([Intro], [Verse 1], [Pre-Chorus], [Chorus], [Bridge], [Outro] ...) on their own "
                   f"lines above the lyric lines in lyrics/lyrics.txt (an empty tag line names a stretch with no "
                   f"vocals), then `{redo}`")
    out.append(f"or set every section yourself: `{cmd('song sections --set NAME@START,...')}` (START = 0, barK, lineN "
               "or seconds; bars count from 0). --set REPLACES ALL sections, the tagged ones too, so list each one: "
               f"`{cmd('song sections')}` shows each section's @START")
    return out


def state_key(paths: Paths, cfg: dict) -> str:
    tags = has_tags(paths.lyrics) and not cfg.get("sections")
    extra = f"|tags:{fingerprint(paths.lyrics, paths.words)}" if tags else ""
    if cfg.get("sections") and any(isinstance(s, dict) and "line" in s for s in cfg["sections"]):
        extra += f"|words:{fingerprint(paths.words)}"
    pickup = float(cfg.get("section_pickup_beats", PICKUP_BEATS))        # the effective value: a new default rebuilds
    return (f"v3|{state_get(paths, 'beats').get('key')}|{fingerprint(paths.song, paths.stem('vocals'))}|"
            f"{cfg.get('sections')}|{pickup}{extra}")


def build(pdir: Path, force: bool = False) -> dict:
    paths = Paths(pdir)
    B = read_json(paths.beats)
    if not B:
        raise SlopError(f"no analysis/beats.json - run `{project_cmd(pdir, 'analyze --steps beats')}` first")
    cfg = audio_cfg(pdir)
    voc = paths.stem("vocals")
    key = state_key(paths, cfg)
    if not force and B.get("sections") and state_get(paths, "sections").get("key") == key:
        return {"status": "up-to-date", "sections": len(B["sections"]), "from": B.get("sections_from")}
    pickup = float(cfg.get("section_pickup_beats", PICKUP_BEATS))
    sr = 44100
    y = load_mono(paths.song, sr)
    dur = float(B.get("duration") or len(y) / sr)
    beats, down = np.asarray(B["beats"], float), np.asarray(B["downbeats"], float)
    em = env24(y, sr, dur)
    ev = env24(load_mono(voc, sr), sr, dur) if voc.exists() else np.zeros_like(em)
    W = read_json(paths.words) or {}
    words = W.get("words") or []
    over = cfg.get("sections")
    notes: list[str] = []
    blocks = parse_blocks(paths.lyrics) if not over else []
    tagged = any(b["tag"] for b in blocks)
    if over:
        starts = parse_override(over, down, beats, words, pickup, pdir=pdir)
        if starts[0][0] > 0.5:
            starts.insert(0, (0.0, head_name(starts)))
        segs = [{"name": n, "t0": t0, "t1": starts[i + 1][0] if i + 1 < len(starts) else dur, "source": "set"}
                for i, (t0, n) in enumerate(starts)]
        frm = "project.json"
    elif tagged and words:
        segs, notes = tag_sections(blocks, words, beats, down, dur, ev, pickup, pdir=pdir)
        frm = "lyrics tags"
        if not segs:
            notes.append("lyrics.txt has section tags but no tagged line is aligned: heuristic sections instead")
    else:
        segs = []
        if tagged:
            notes.append("lyrics.txt has section tags but no word timing yet: heuristic sections until "
                         f"`{project_cmd(pdir, 'analyze --steps align')}` (the analysis rebuilds them after the "
                         "alignment)")
    if not segs:
        frm = "heuristic"
        bar = float(np.median(np.diff(down))) if len(down) > 1 else 2.0
        sec = [0.0]
        for t in boundaries(y, sr, beats, down, dur):         # sections at least ~2 bars long
            if t - sec[-1] >= 1.9 * bar and dur - t >= 1.9 * bar:
                sec.append(t)
        segs = [{"t0": a, "t1": b, "source": "heuristic"} for a, b in zip(sec, sec[1:] + [dur])]
    for s in segs:
        i0, i1 = int(s["t0"] * 24), max(int(s["t0"] * 24) + 1, int(s["t1"] * 24))
        s["energy"] = float(np.mean(em[i0:i1])) if i0 < len(em) else 0.0
        s["vocals"] = float(np.mean(ev[i0:i1] > 0.06)) if i0 < len(ev) else 0.0
    if frm == "heuristic":
        segs = name_sections(segs)
    elif frm == "lyrics tags":
        _name_heuristic(segs)
        segs = number_names(segs)
        if any(s["source"] == "heuristic" for s in segs):
            frm = "lyrics tags + heuristic"
    emax = max((s["energy"] for s in segs), default=1.0) or 1.0
    out = []
    for s in segs:
        b0 = int(np.searchsorted(down, s["t0"] + 1e-3, side="right")) - 1
        b1 = int(np.searchsorted(down, s["t1"] - 1e-3, side="right")) - 1
        row = {"name": s["name"], "t0": round(float(s["t0"]), 3), "t1": round(float(s["t1"]), 3),
               "energy": round(s["energy"] / emax, 3), "vocals": round(s["vocals"], 3), "bar0": b0, "bar1": b1,
               "source": s["source"]}
        if s["source"] == "heuristic":
            row["unconfirmed"] = True
        if s.get("tag"):
            row["tag"] = s["tag"]
        if s.get("lines"):
            row["lines"] = [min(s["lines"]), max(s["lines"])]
        out.append(row)
    B["sections"] = out
    B["sections_from"] = frm
    B["notes"] = [n for n in B.get("notes", []) if not n.startswith("the bars changed: sections cleared")
                  and not n.startswith("sections: ")] + [f"sections: {n}" for n in notes]
    write_json(paths.beats, B)
    state_set(paths, "sections", key)
    unconf = [s["name"] for s in out if s.get("unconfirmed")]
    return {"status": "done", "from": frm, "unconfirmed": unconf, "notes": notes,
            "sections": [f"{s['name']} {s['t0']:.1f}-{s['t1']:.1f}" + (" (unconfirmed)" if s.get("unconfirmed") else "")
                         for s in out]}
