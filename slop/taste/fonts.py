"""Font A/B (``slop taste fonts [setup|rank]``): the user's real lyric lines over their approved style frame, set in
candidate OFL faces from engine/fonts, judged two at a time on the tap server's /fonts page.

Why this shape (research 11-gap-5 §5.3-5.4, research 05 §5.4):
  * the author's own composed A/B picks were mostly POSITION BIAS: the first-shown option won 61/90 decisive picks (67.8 %,
    p = 0.001) although sides were shuffled; a Bradley–Terry fit with a first-slot term gives γ = +0.86 logit, and
    31 of 43 "unbeaten" fonts won only from the first slot. So this module
      1. logs what was shown (`shown` ab/ba = which side was in the FIRST slot, `layout` row/stack);
      2. counterbalances: every pair is shown twice, once in each order, >= 20 cards apart where the schedule allows
         (a split vote = a tie; agreement across the two orders measures self-agreement). A split vote (the first
         slot won both showings) is a TIE in every tally — wins/losses, the "preferred" rule, the flags, the naive
         BT and the >= 30-games threshold. Its two games stay in the joint fit below because they are what
         identifies γ; there they cancel on θ (the gradient pulls θ_a − θ_b towards 0, exactly like a tie);
      3. fits BT WITH a first-slot term: P(first beats second) = σ(θ_first − θ_second + γ), prior N(0, 1) on θ and
         N(0, 10²) on γ (MAP by Newton — the retired recompute used L-BFGS on the same objective);
      4. never calls a font "preferred" without >= 2 decisive games and >= 1 win from the SECOND slot, and flags
         fonts whose wins all came from the first slot; >= 30 decisive games before the ranking is more than a lead;
      5. gates a session whose first-slot rate among decisive picks is > 0.60 with binomial p < 0.05 (satisficing
         between weak options): its rows get weight 1 − 2·|p̂ − 0.5| and the report says to show better options;
         a ranking whose decisive games come only from gated sessions stays a "lead", never "measured".
  * Real lyric lines on the approved frame (not neutral copy on random grounds): "Relative picks between designs the
    owner doesn't like say little"; generated A/B is only for choosing among options already on an approved frame.
  * Ink follows the retired composer's rule: region luminance < 0.55 -> #f3f1ea, else #121212. Display size is the
    round 001-A anchor, 4.97 % of the frame width, hung from the left axis; labels are revealed only after a pick.
The naive BT of the retired optimizer (compose.font_ratings: N(0,1) prior, 200 gradient steps of 0.3, no position
term) is reported alongside (`theta_naive`) so the position correction is visible.
Default candidates: grotesk / condensed / mono faces plus one serif (Instrument Serif) and one display face
(Audiowide) from engine/fonts, so a serif or display taste can win without --families (review round 1: the old
list was the author's own position-biased grotesk/mono shortlist). The page lays the pair out side by side (`row`)
even on portrait phones, with a "turn the phone sideways" hint (research 11-gap-5 §5.4.5: the +0.86 first-slot
bias most likely came from the TOP slot on a phone); lyric tracking −0.03 em as in the 001-A anchor. display.txt
markers (`TEXT|n`, `*accent*`, `_mono_`, `~strike~`) are stripped from the A/B lines.
Licences: only OFL faces are offered; Nimbus Sans, Junicode, Pilcrow Rounded and Alchimia are never used.
"""
from __future__ import annotations

import itertools
import math
import random
import re
import struct
from pathlib import Path

import numpy as np

from .. import util
from ..config import SlopError, engine_dir, load_project
from . import model as M
from .store import append_jsonl, fonts_dir, new_eid, now_iso, read_events, read_json, write_json

DEFAULT_FAMILIES = ["Space Grotesk", "Geist", "DINish", "Barlow Condensed", "IBM Plex Mono", "Share Tech Mono",
                    "Instrument Serif", "Audiowide"]
BANNED = ("nimbus", "junicode", "pilcrow", "alchimia")       # not OFL / not shippable
WEIGHT_PREF = ["medium", "regular", "semibold", "book", "bold", "light", ""]
FONT_EXT = (".ttf", ".otf", ".woff2", ".woff")
MIN_GAP = 20
MAX_FONTS = 9
DISPLAY_PCT_W = 4.97          # round 001-A display size, % of frame width
GATE_RATE, GATE_P = 0.60, 0.05
PREFERRED_MIN_GAMES, ENOUGH_GAMES = 2, 30
PLACEHOLDER_LINE = "the quick brown fox jumps over the lazy dog"


# ---------------------------------------------------------------- font discovery

def sfnt_names(path: Path) -> dict:
    """family/subfamily from an OpenType/TrueType 'name' table (no fontTools needed); {} if unreadable"""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return {}
    if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return {}
    try:
        num = struct.unpack(">H", data[4:6])[0]
        off = None
        tags = set()
        for i in range(num):
            tag, _, toff, _ = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            tags.add(tag)
            if tag == b"name":
                off = toff
        if off is None:
            return {}
        _, count, soff = struct.unpack(">HHH", data[off:off + 6])
        names: dict[int, str] = {}
        for i in range(count):
            pid, eid, lid, nid, ln, noff = struct.unpack(">HHHHHH", data[off + 6 + 12 * i: off + 18 + 12 * i])
            if nid not in (1, 2, 16, 17):
                continue
            raw = data[off + soff + noff: off + soff + noff + ln]
            if pid == 3 or pid == 0:
                s = raw.decode("utf-16-be", "ignore")
            else:
                s = raw.decode("latin-1", "ignore")
            if nid not in names or (pid == 3 and lid == 0x409):
                names[nid] = s
        fam = names.get(16) or names.get(1)
        sub = names.get(17) or names.get(2) or ""
        return {"family": fam, "style": sub, "variable": b"fvar" in tags} if fam else {}
    except (struct.error, IndexError):
        return {}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _from_filename(p: Path) -> dict:
    stem = p.stem
    variable = "[" in stem or "variable" in stem.lower()
    stem = stem.split("[")[0]
    fam, _, style = stem.partition("-")
    fam = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", fam).strip()
    return {"family": fam, "style": style or ("Variable" if variable else "Regular"), "variable": variable}


def scan_fonts(dirs: list[Path]) -> list[dict]:
    out = []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() not in FONT_EXT or not p.is_file():
                continue
            meta = sfnt_names(p) if p.suffix.lower() in (".ttf", ".otf") else {}
            fn = _from_filename(p)
            fam = meta.get("family") or fn["family"]
            if any(b in _norm(fam) or b in _norm(p.name) for b in BANNED):
                continue
            out.append({"family": fam, "style": meta.get("style") or fn["style"], "path": str(p), "file": p.name,
                        "variable": bool(meta.get("variable") or fn["variable"]), "key": _norm(fam),
                        "file_key": _norm(p.stem.split("-")[0].split("[")[0])})
    return out


def pick_faces(fonts: list[dict], families: list[str]) -> list[dict]:
    """one face per wanted family, preferring Medium, then Regular… (one weight for every family)"""
    out = []
    for fam in families:
        k = _norm(fam)
        cands = [f for f in fonts if f["key"] == k or f["file_key"] == k]
        if not cands:
            continue

        def rank(f):
            st = _norm(f["style"])
            if f["variable"]:
                return -1
            if "italic" in st:
                return 99
            return WEIGHT_PREF.index(st) if st in WEIGHT_PREF else 50
        best = sorted(cands, key=lambda f: (rank(f), f["file"]))[0]
        weight = 500 if best["variable"] else {"medium": 500, "semibold": 600, "bold": 700, "light": 300}.get(_norm(best["style"]), 400)
        out.append({"family": fam, "file": best["file"], "path": best["path"], "weight": weight,
                    "css": "F" + _norm(fam)[:24]})
    return out


def font_dirs(extra: str | None = None) -> list[Path]:
    ds = [engine_dir() / "fonts"]
    if extra:
        ds.insert(0, Path(extra).expanduser())
    return ds


# ---------------------------------------------------------------- frame, lines, schedule

def find_frame(pdir: Path, frame: str | None = None) -> tuple[Path | None, str]:
    if frame:
        p = Path(frame).expanduser()
        if not p.is_absolute():
            p = (pdir / p) if (pdir / p).exists() else p
        if not p.is_file():
            raise SlopError(f"--frame {frame} does not exist")
        return p, "--frame"
    try:
        proj = load_project(pdir)
    except (OSError, ValueError):
        proj = {}
    hero = ((proj.get("look") or {}).get("hero_plate"))
    if hero:
        for c in (pdir / hero, pdir / "plates" / hero):
            if c.is_file():
                return c, "project.json look.hero_plate"
        hits = sorted((pdir / "plates").rglob(f"{hero}*.jpg")) + sorted((pdir / "plates").rglob(f"{hero}*.png")) \
            if (pdir / "plates").is_dir() else []
        if hits:
            return hits[0], "project.json look.hero_plate"
    picks = read_json(pdir / "plates" / "picks.json", {}) or {}
    for _, v in picks.items():
        f = v.get("file") if isinstance(v, dict) else None
        if f:
            for c in (pdir / f, pdir / "plates" / f):
                if c.is_file():
                    return c, "plates/picks.json"
    return None, "none"


def prepare_frame(src: Path | None, out: Path) -> dict:
    """copy the style frame (long side <= 1920) or synthesise a neutral dark ground; -> {ink, lum, provisional}"""
    from PIL import Image, ImageFilter
    if src is not None:
        im = Image.open(src)
        im.draft("RGB", (1920, 1920))
        im = im.convert("RGB")
        if max(im.size) > 1920:
            s = 1920 / max(im.size)
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        provisional = False
    else:
        rng = np.random.default_rng(7)
        y = np.linspace(0, 1, 1080)[:, None]
        base = 26 + 30 * (1 - y) + rng.normal(0, 3, (1080, 1920))
        arr = np.clip(np.stack([base, base * 1.02, base * 1.08], -1), 0, 255).astype("uint8")
        im = Image.fromarray(arr).filter(ImageFilter.GaussianBlur(1))
        provisional = True
    im.save(out, quality=90)
    g = np.asarray(im.convert("L"), dtype=float) / 255
    h, w = g.shape
    band = g[int(h * 0.62):int(h * 0.92), int(w * 0.04):int(w * 0.80)]
    lum = float(band.mean()) if band.size else float(g.mean())
    return {"ink": "#f3f1ea" if lum < 0.55 else "#121212", "lum": round(lum, 3), "provisional": provisional,
            "w": im.width, "h": im.height}


def clean_line(s: str) -> str:
    """a display.txt / lyrics line as it reads on screen: span markers and style markers removed"""
    s = re.sub(r"\|\d+", "", s)                       # display.txt span markers "TEXT|n"
    s = re.sub(r"\*([^*]+?)\*", r"\1", s)              # *accent*
    s = re.sub(r"(?<![A-Za-z0-9])_([^_]+?)_(?![A-Za-z0-9])", r"\1", s)   # _mono_
    s = re.sub(r"~([^~]+?)~", r"\1", s)                # ~strike~
    return re.sub(r"\s+", " ", s).strip()


def read_lines(pdir: Path, texts: list[str] | None, n: int) -> tuple[list[str], str]:
    if texts:
        return [clean_line(t) for t in texts if clean_line(t)][:max(n, 1)], "--text"
    for rel in ("lyrics/display.txt", "lyrics/lyrics.txt"):
        f = pdir / rel
        if not f.is_file():
            continue
        lines = []
        for raw in util.read_lyric_lines(f):         # the shared lyric-line rule (blank and [tag] lines skipped)
            t = clean_line(raw)
            if t and 2 <= len(t.split()) <= 9 and len(t) <= 60:
                lines.append(t)
        lines = list(dict.fromkeys(lines))
        if lines:
            if len(lines) > n:
                step = len(lines) / n
                lines = [lines[int(i * step)] for i in range(n)]
            return lines, rel
    raise SlopError("no lyric lines: write lyrics/lyrics.txt (one sung line per row) or pass --text \"a line\" "
                    "(repeatable). The A/B must use the user's real words")


def schedule(n_fonts: int, n_lines: int, seed: int) -> list[dict]:
    """every unordered pair twice (both orders), the two showings >= MIN_GAP cards apart when the pair count allows
    (a pair's second showing comes one full pass later; adjacent swaps keep the gap), same line for both orders"""
    rng = random.Random(seed)
    pairs = list(itertools.combinations(range(n_fonts), 2))
    rng.shuffle(pairs)
    n = len(pairs)
    first = []
    for k, (i, j) in enumerate(pairs):
        shown = "ab" if rng.random() < 0.5 else "ba"
        first.append({"a": i, "b": j, "shown": shown, "line": k % max(n_lines, 1)})
    gap = min(MIN_GAP, n)
    order = list(range(n))
    for k in range(n - 1):                             # light shuffle that keeps every gap >= `gap`
        if rng.random() < 0.5:
            o2 = order[:]
            o2[k], o2[k + 1] = o2[k + 1], o2[k]
            if all(n + o2.index(p) - p >= gap for p in range(n)):
                order = o2
    second = [{**first[p], "shown": "ba" if first[p]["shown"] == "ab" else "ab"} for p in order]
    cards = first + second
    for c, card in enumerate(cards):
        card["card"] = c
    return cards


# ---------------------------------------------------------------- session

def session_path(pdir: Path) -> Path:
    return fonts_dir(pdir) / "session.json"


def taps_file(pdir: Path) -> Path:
    return fonts_dir(pdir) / "taps.jsonl"


def setup(pdir: Path, frame: str | None = None, families: list[str] | None = None, texts: list[str] | None = None,
          n_lines: int = 6, seed: int | None = None, extra_dir: str | None = None, reset: bool = False) -> dict:
    pdir = Path(pdir)
    sp = session_path(pdir)
    cur = read_json(sp)
    from .profile import project_name
    pname = project_name(pdir)
    # a shared (user) profile: another project's session uses that project's lines and frame -> a new session for
    # this project (the old picks are kept and still count in the ranking)
    if cur and not reset and cur.get("project", pname) == pname:
        return {"session": cur, "created": False}
    fonts = scan_fonts(font_dirs(extra_dir))
    wanted = families or DEFAULT_FAMILIES
    faces = pick_faces(fonts, wanted)[:MAX_FONTS]
    if len(faces) < 2:
        have = sorted({f["family"] for f in fonts})
        raise SlopError(f"need >= 2 candidate fonts; found {len(faces)} of {', '.join(wanted)} under "
                        f"{', '.join(str(d) for d in font_dirs(extra_dir))}. Available: {', '.join(have) or 'none'}. "
                        "Run bin/setup.sh (installs the engine fonts) or pass --fonts-dir / --families")
    lines, lines_src = read_lines(pdir, texts, n_lines)
    src, frame_src = find_frame(pdir, frame)
    fr = prepare_frame(src, fonts_dir(pdir) / "frame.jpg")
    seed = random.randrange(1 << 30) if seed is None else int(seed)
    weights = sorted({f["weight"] for f in faces})
    note = None if len(weights) == 1 else ("weights differ (" + ", ".join(f"{f['family']} {f['weight']}" for f in faces)
                                           + "): only the weights shipped in engine/fonts are used")
    sess = {"id": new_eid(), "created": now_iso(), "project": pname, "seed": seed, "fonts": faces, "lines": lines,
            "weights_note": note,
            "lines_source": lines_src, "frame_source": frame_src, "frame": "frame.jpg", **fr,
            "display_pct_w": DISPLAY_PCT_W, "cards": schedule(len(faces), len(lines), seed)}
    write_json(sp, sess)
    return {"session": sess, "created": True}


class FontSession:
    """the server side of the /fonts page"""

    def __init__(self, pdir: Path):
        self.pdir = Path(pdir)
        self.sess = read_json(session_path(self.pdir))

    def reload(self) -> None:
        self.sess = read_json(session_path(self.pdir))

    def picks(self) -> list[dict]:
        if not self.sess:
            return []
        return [e for e in read_events(taps_file(self.pdir)) if e.get("session") == self.sess["id"]]

    def card_json(self, c: dict) -> dict:
        F = self.sess["fonts"]
        first, second = (c["a"], c["b"]) if c["shown"] == "ab" else (c["b"], c["a"])
        face = lambda i: {"family": F[i]["family"], "css": F[i]["css"], "file": F[i]["file"], "weight": F[i]["weight"]}
        return {"type": "fontpair", "key": f"f:{c['card']}", "card": c["card"], "line": self.sess["lines"][c["line"]],
                "ink": self.sess["ink"], "first": face(first), "second": face(second), "shown": c["shown"]}

    def next(self, exclude: list[str], n: int = 4) -> dict:
        if not self.sess:
            return {"cards": [], "progress": self.progress(), "error": "no font session: run `slop taste fonts`"}
        done = {e.get("card") for e in self.picks()}
        ex = {k for k in exclude}
        out = [self.card_json(c) for c in self.sess["cards"] if c["card"] not in done and f"f:{c['card']}" not in ex][:n]
        return {"cards": out, "progress": self.progress()}

    def record(self, body: dict) -> dict:
        if not self.sess:
            raise ValueError("no session")
        try:
            k = int(body.get("card"))
            c = self.sess["cards"][k]
        except (TypeError, ValueError, IndexError):
            raise ValueError("bad card") from None
        w = body.get("winner")            # in slot terms: first / second / tie / skip
        if w not in ("first", "second", "tie", "skip"):
            raise ValueError("bad winner")
        F = self.sess["fonts"]
        first, second = (c["a"], c["b"]) if c["shown"] == "ab" else (c["b"], c["a"])
        win_ab = {"first": "a" if c["shown"] == "ab" else "b", "second": "b" if c["shown"] == "ab" else "a"}.get(w, w)
        rec = {"eid": new_eid(), "t": now_iso(), "session": self.sess["id"], "card": k,
               "a": F[c["a"]]["family"], "b": F[c["b"]]["family"], "first": F[first]["family"],
               "second": F[second]["family"], "shown": c["shown"],
               "layout": body.get("layout") if body.get("layout") in ("row", "stack") else "row",
               "winner": win_ab, "line": c["line"], "dwell_ms": _int(body.get("dwell_ms"))}
        append_jsonl(taps_file(self.pdir), rec)
        return rec

    def undo(self, eid: str) -> None:
        if eid:
            append_jsonl(taps_file(self.pdir), {"undo": str(eid)[:20], "t": now_iso()})

    def font_path(self, name: str) -> Path | None:
        if not self.sess:
            return None
        for f in self.sess["fonts"]:
            if f["file"] == name:
                return Path(f["path"])
        return None

    def progress(self) -> dict:
        if not self.sess:
            return {"cards": 0, "answered": 0}
        p = self.picks()
        dec = [e for e in p if e.get("winner") in ("a", "b")]
        return {"cards": len(self.sess["cards"]), "answered": len({e["card"] for e in p}), "decisive": len(dec),
                "first_slot_wins": sum(1 for e in dec if e[e["winner"]] == e["first"])}


def _int(v) -> int:
    try:
        return max(0, min(int(v), 10 ** 7))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------- Bradley–Terry

def bt_fit(games: list[tuple[int, int, float]], n: int, weights=None, home: bool = True) -> tuple[np.ndarray, float]:
    """games: (first, second, 1.0 if first won). MAP BT: P(first beats second) = σ(θf − θs + γ);
    θ ~ N(0, 1), γ ~ N(0, 10²) (precision 1e-2 = fit_logistic's free-column prior). -> (θ, γ)"""
    if not games:
        return np.zeros(n), 0.0
    A = np.zeros((len(games), n + (1 if home else 0)))
    y = np.zeros(len(games))
    for r, (f, s, lab) in enumerate(games):
        A[r, f] += 1.0
        A[r, s] -= 1.0
        if home:
            A[r, n] = 1.0
        y[r] = lab
    wt = np.ones(len(games)) if weights is None else np.asarray(weights, dtype=float)
    w, _ = M.fit_logistic(A, y, wt, 1.0, n_free=1 if home else 0)
    return (w[:n], float(w[n])) if home else (w, 0.0)


def bt_naive(games_wl: list[tuple[int, int]], n: int) -> np.ndarray:
    """the retired compose.font_ratings: BT without a position term, N(0,1) prior, 200 gradient steps of 0.3"""
    th = np.zeros(n)
    if not games_wl:
        return th
    for _ in range(200):
        g = -th.copy()
        for w_, l_ in games_wl:
            p = 1 / (1 + np.exp(th[w_] - th[l_]))
            g[w_] += p
            g[l_] -= p
        th += 0.3 * g
    return th


def _splits(dec: list[dict]) -> tuple[set[int], int, int]:
    """pair each decisive showing with the opposite-order showing of the same pair (same session and line, in log
    order) -> (indices into `dec` of split votes, pairs answered in both orders, of which agreeing)"""
    groups: dict[tuple, dict[str, list[int]]] = {}
    for k, e in enumerate(dec):
        key = (e.get("session"), tuple(sorted((e["a"], e["b"]))), e.get("line"))
        groups.setdefault(key, {}).setdefault(e["first"], []).append(k)
    split: set[int] = set()
    both = agree = 0
    for g in groups.values():
        if len(g) < 2:
            continue
        x, y = list(g.values())[:2]
        for kx, ky in zip(x, y):
            both += 1
            ex, ey = dec[kx], dec[ky]
            if ex[ex["winner"]] == ey[ey["winner"]]:
                agree += 1
            else:
                split |= {kx, ky}
    return split, both, agree


def rank(pdir: Path) -> dict:
    pdir = Path(pdir)
    rows = read_events(taps_file(pdir))
    dec = [e for e in rows if e.get("winner") in ("a", "b") and e.get("first") and e.get("second")]
    fams = sorted({e["a"] for e in rows if e.get("a")} | {e["b"] for e in rows if e.get("b")})
    out = {"version": 1, "picks": len(rows), "decisive": len(dec), "ties": sum(1 for e in rows if e.get("winner") == "tie"),
           "skips": sum(1 for e in rows if e.get("winner") == "skip"), "fonts": [], "notes": []}
    if not dec:
        out["text"] = "no decisive font picks yet: open the /fonts page from `slop taste fonts` and pick"
        return out
    ix = {f: k for k, f in enumerate(fams)}
    split, both, agree = _splits(dec)
    # session gate: satisficing between weak options shows up as a first-slot habit
    weights = []
    sessions: dict[str, dict] = {}
    for e in dec:
        s = sessions.setdefault(e.get("session", "?"), {"n": 0, "first": 0})
        s["n"] += 1
        s["first"] += int(e[e["winner"]] == e["first"])
    for sid, s in sessions.items():
        rate = s["first"] / s["n"]
        p = M.binom_two_sided(s["first"], s["n"])
        gated = rate > GATE_RATE and p < GATE_P
        s.update(rate=round(rate, 3), p=float(f"{p:.3g}"), gated=gated,
                 weight=round(1 - 2 * abs(rate - 0.5), 3) if gated else 1.0)
    for e in dec:
        weights.append(sessions[e.get("session", "?")]["weight"])
    # joint fit on every decisive game: split votes identify γ and cancel on θ (tie-like)
    games = [(ix[e["first"]], ix[e["second"]], 1.0 if e[e["winner"]] == e["first"] else 0.0) for e in dec]
    theta, gamma = bt_fit(games, len(fams), weights=weights, home=True)
    kept = [e for k, e in enumerate(dec) if k not in split]           # split votes are ties from here on
    naive = bt_naive([(ix[e[e["winner"]]], ix[e["b"] if e["winner"] == "a" else e["a"]]) for e in kept], len(fams))
    first_w = sum(g[2] for g in games)
    p_all = M.binom_two_sided(int(first_w), len(games))
    out.update(first_slot_wins=int(first_w), first_slot_rate=round(first_w / len(games), 3),
               binom_p=float(f"{p_all:.3g}"), gamma=round(gamma, 3),
               gamma_prob=round(1 / (1 + math.exp(-gamma)), 3), sessions=sessions,
               decisive_games=len(kept), split_ties=len(split) // 2)
    stats = {f: {"wins": 0, "losses": 0, "wins_first": 0, "wins_second": 0, "split_ties": 0} for f in fams}
    for k, e in enumerate(dec):
        if k in split:
            stats[e["a"]]["split_ties"] += 1
            stats[e["b"]]["split_ties"] += 1
            continue
        w = e[e["winner"]]
        lo = e["b"] if e["winner"] == "a" else e["a"]
        stats[w]["wins"] += 1
        stats[lo]["losses"] += 1
        stats[w]["wins_first" if w == e["first"] else "wins_second"] += 1
    for f in fams:
        st = stats[f]
        st["split_ties"] //= 2
        games_f = st["wins"] + st["losses"]
        flag = None
        if st["wins"] and not st["wins_second"]:
            flag = "first-slot-only wins"
        preferred = games_f >= PREFERRED_MIN_GAMES and st["wins_second"] >= 1 and theta[ix[f]] > 0
        out["fonts"].append({"family": f, "theta": round(float(theta[ix[f]]), 3),
                             "theta_naive": round(float(naive[ix[f]]), 3), **st, "games": games_f,
                             "preferred": bool(preferred), "flag": flag})
    out["fonts"].sort(key=lambda r: -r["theta"])
    out["counterbalanced"] = {"pairs_both_orders": both, "agree": agree, "split_ties": both - agree,
                              "self_agreement": round(agree / both, 3) if both else None}
    pref = [r["family"] for r in out["fonts"] if r["preferred"]]
    ungated = sum(1 for k, e in enumerate(dec) if k not in split and not sessions[e.get("session", "?")]["gated"])
    all_gated = all(s["gated"] for s in sessions.values())
    status = "measured" if ungated >= ENOUGH_GAMES else "lead"
    out["recommendation"] = {"lyric": pref[0] if pref else None, "shortlist": pref[:4], "status": status,
                             "evidence": f"{ungated} decisive non-split picks from sessions without a first-slot habit"}
    if all_gated:
        out["recommendation"]["action"] = "show better options"
        out["notes"].append("every session picked the first slot > 60 % of the time (p < 0.05): these are 'least bad' "
                            "choices — show the owner better font options (or the fonts on a better frame) rather "
                            "than more pairs; the ranking stays a lead")
    elif any(s["gated"] for s in sessions.values()):
        out["notes"].append("a session picked the first slot > 60 % of the time (p < 0.05): its picks are down-weighted "
                            "as 'least bad' — show the owner better options rather than more pairs of the same quality")
    if ungated < ENOUGH_GAMES:
        out["notes"].append(f"only {ungated} decisive non-split picks from ungated sessions (< {ENOUGH_GAMES}): the "
                            "ranking is a lead, not a result")
    if split:
        out["notes"].append(f"{len(split) // 2} pair(s) were split votes (the first slot won both showings): counted "
                            "as ties")
    if out["fonts"] and not pref:
        out["notes"].append("no font has a win from the second slot yet: nothing can be called preferred")
    out["notes"].append("confirm the winner on a rendered style frame before it becomes look.fonts.lyric")
    write_json(fonts_dir(pdir) / "ranking.json", out)
    top = ", ".join(f"{r['family']} {r['theta']:+.2f} ({r['wins']}-{r['losses']}{'*' if r['flag'] else ''})"
                    for r in out["fonts"][:5])
    ptx = "p < 0.0001" if p_all < 1e-4 else f"p = {p_all:.3g}"
    rec = out["recommendation"]
    out["text"] = (f"{len(dec)} decisive picks ({len(split) // 2} split pairs counted as ties); first slot won "
                   f"{out['first_slot_rate'] * 100:.0f} % (γ = {gamma:+.2f} logit, {ptx}). Position-corrected: {top}. "
                   f"Recommendation: {rec['lyric'] or 'none yet'} ({rec['status']})"
                   + (" — show the owner better options: every session looks like 'least bad' picking" if all_gated else "")
                   + ". * = wins only from the first slot.")
    return out
