"""Pair sheets for chat — the no-tunnel fallback of the tap app (``slop taste sheet`` / ``slop taste record``).

The tap app over a Cloudflare quick tunnel stays the primary path (fast, like/pass + pairs, live meter). When no
tunnel works, the bot sends numbered pair sheets as images in the chat and the owner answers in one line:

    slop taste sheet                 # -> sheets/<id>/sheet-1.jpg ... (4 pairs each, JPEG <= 2 MB) + the message
    (the bot sends the images with the message; the owner replies "1a 2b 3a 4b 5b 6a 7a 8b 9a 10b 11a 12a")
    slop taste record --sheet <id> "1a 2b 3a 4b 5b 6a 7a 8b 9a 10b 11a 12a"

One sheet at a time (review round 2: a reply was recorded against the wrong sheet without a warning):
  * `slop taste sheet` shows the sheet that is still waiting for its reply again instead of making a new one (a
    retry is safe); `--new` makes another one anyway, `--discard ID` closes a sheet the owner will not answer;
  * sheet.json records the project it was made from; the printed record command always names the sheet;
  * `record` without --sheet uses the one open sheet, and refuses when several are open (it lists each with the
    exact command), so a reply never lands on the wrong pairs silently.

Answers: a = left, b = right, t = can't choose (tie), x = skip; "1a 2b", "1a,2b", "1 a; 2 b", "1:left" all parse;
punctuation, emoji and a greeting / sign-off around the answers ("here you go: ... thanks!") are ignored; anything
else in the reply is an error that quotes it (never a silent drop). Partial answers are recorded and the missing
numbers listed; answering a pair again needs --redo (the old answer is undone, not duplicated).

Which pairs (the feed's own policy, research 11-gap-5 §5.3, adapted to pairs only):
  * once the model is fitted on >= 40 answers, half the pairs are the feed's informative pairs (two unseen images
    the model scores alike, among its top third, that look different: cosine < 0.85, not the same project);
  * the rest walk the k-means-stratified cold-start order of the pool (only during the first 40 answers), each
    paired with the next image that looks different, then random unseen images (explore);
  * a small pool that runs out of unseen images pairs the least-shown images again at random (why = "reuse"),
    never a pair that was already asked. Review round 2 proposed model-chosen pairs here instead (two seen images
    the model scores alike); measured on a sheet-only owner who is 90 % consistent (13 sheets, 156 answers, 5 seeds
    on 140 real SigLIP 2 vectors of Midjourney plates, truth = darker is better; 4 seeds on synthetic vectors), the
    model's accuracy on independent random pairs did not improve (real 0.811 vs 0.808 for random reuse; synthetic
    0.852 vs 0.870) while the held-out meter fell 11-14 points (near-ties are coin flips for the owner too), so the
    random least-shown pairs stay; anchoring on the images the model is least sure of (posterior variance) was
    neutral as well (0.801). The meter with random reuse reached 0.78 (real) / 0.86 (synthetic) at 156 answers;
  * from 6 answered pairs on, one earlier decisive pair comes back with its sides swapped (why = "repeat") until 6
    repeats are done: self-agreement — the ceiling of the meter — is measured on sheets too;
  * sides are randomised; the left image is logged as the first slot (`shown: "ab"`, `layout: "sheet"`), so the
    position-bias analysis sees sheet answers as what they are;
  * images on a sheet that is still unanswered are not reused on the next sheet.
Rows land in the profile's taps.jsonl as ordinary pair rows (`via: "sheet"`), so fit / meter / tokens / boards use
them unchanged. After recording, a quick held-out meter (one 5-fold repetition) is printed once >= 20 answers with
image vectors exist (without vectors — `slop taste embed` not run — both commands say so).
"""
from __future__ import annotations

import io
import random
import re
import time
import unicodedata
from pathlib import Path

import numpy as np

from ..config import SlopError
from . import model as M
from .store import (append_jsonl, images_dir, new_eid, now_iso, read_events, read_json, read_jsonl, split_events,
                    taps_path, taste_dir, write_json)

PAIRS = 12
PER_SHEET = 4
MAX_BYTES = 2_000_000
W = 1200
MARGIN, GAP = 28, 18
CELL_W = (W - 2 * MARGIN - GAP) // 2
CELL_H = round(CELL_W * 0.75)
HEAD, ROW_GAP, FOOT = 128, 26, 96
BG, CELL_BG, INK, BADGE = (17, 17, 17), (34, 34, 34), (240, 238, 232), (245, 242, 235)
REPEAT_FROM = 6
ANSWER_WORDS = {"a": "a", "l": "a", "left": "a", "b": "b", "r": "b", "right": "b",
                "t": "tie", "tie": "tie", "same": "tie", "both": "tie", "=": "tie",
                "x": "skip", "s": "skip", "skip": "skip", "none": "skip", "?": "skip"}
ANSWER_RE = re.compile(r"(\d+)\s*[:.)\-]?\s*(left|right|tie|same|both|skip|none|a|b|l|r|t|x|s|=|\?)(?![a-z])")
SIGNOFF_RE = re.compile(r"^(?:thanks?|thank you|thank you so much|thanks a lot|many thanks|thx|ty|cheers|ok|okay|"
                        r"done|here|here you go|there you go|here they are|my answers|answers|sure|great|cool|nice|"
                        r"perfect|lol|hope (?:this|that) helps|xx|xxx)$")
MESSAGE = ("Which one do you like more in each pair? Reply in one line with the number and a or b for every pair, "
           "like: {example}   (a = left, b = right, t = can't choose, x = skip)")


def sheets_dir(pdir: Path) -> Path:
    d = taste_dir(pdir) / "sheets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_sheets(pdir: Path) -> list[dict]:
    out = []
    for p in sorted(sheets_dir(pdir).glob("*/sheet.json")):
        s = read_json(p)
        if isinstance(s, dict) and s.get("pairs"):
            s["_path"] = str(p)
            out.append(s)
    return sorted(out, key=lambda s: (str(s.get("created")), s["id"]))


def _unanswered(s: dict) -> list[int]:
    ans = s.get("answers") or {}
    return [p["n"] for p in s["pairs"] if str(p["n"]) not in ans]


def open_sheets(sheets: list[dict]) -> list[dict]:
    """sheets still waiting for (part of) their reply, oldest first (a discarded sheet is closed)"""
    return [s for s in sheets if _unanswered(s) and not s.get("discarded")]


def _ranges(ns: list[int]) -> str:
    out, k = [], 0
    while k < len(ns):
        j = k
        while j + 1 < len(ns) and ns[j + 1] == ns[j] + 1:
            j += 1
        out.append(str(ns[k]) if j == k else f"{ns[k]}-{ns[j]}")
        k = j + 1
    return ", ".join(out)


def _record_cmd(sid: str) -> str:
    return f'slop taste record --sheet {sid} "<the reply>"'


def _describe(s: dict) -> str:
    miss = _unanswered(s)
    return (f"{s['id']}  made {str(s.get('created') or '?').replace('T', ' ')}"
            + (f" from project {s['project']}" if s.get("project") else "")
            + (f", pairs {_ranges(miss)} unanswered" if miss else ", answered"))


def _has_vectors(pdir: Path, pool: dict) -> bool:
    from .embed import load_store
    ids = load_store(pdir)[0]
    return any(i in pool for i in ids)


NO_VECTORS = ("warning: the pool has no image vectors yet — pairs are chosen at random and the model and meter cannot "
              "learn from the answers until you run: slop taste embed   (the answers are kept and count after that)")


# ---------------------------------------------------------------- choosing pairs

def _feed(pdir: Path, seed):
    from .feed import Feed

    class Quiet(Feed):            # no background meter thread from a one-shot CLI command
        def measure(self, *a, **k):
            self.measuring = False
            return None
    return Quiet(pdir, seed=seed)


def choose_pairs(pdir: Path, n: int, seed: int | None = None) -> list[dict]:
    f = _feed(pdir, seed)
    sp, ev = f.space, f.events()
    rng = random.Random(seed)
    pending = {x for s in open_sheets(list_sheets(pdir)) for p in s["pairs"] for x in (p["a"], p["b"])}
    used: set[str] = set(pending)
    out: list[dict] = []
    decisive = [e for e in ev if e.get("winner") in ("a", "b") and e.get("a") in sp.pool and e.get("b") in sp.pool]
    # 1. one self-agreement repeat per sheet set (sides swapped)
    repeats = sum(1 for e in decisive if e.get("why") == "repeat")
    if n >= 6 and len(decisive) >= REPEAT_FROM and repeats < M.REPEAT_TARGET:
        done = {frozenset((e["a"], e["b"])) for e in decisive if e.get("why") == "repeat"}
        old = [e for e in decisive if e.get("why") != "repeat" and frozenset((e["a"], e["b"])) not in done
               and e["a"] not in used and e["b"] not in used]
        if old:
            e = rng.choice(old)
            out.append({"a": e["b"], "b": e["a"], "why": "repeat"})
            used |= {e["a"], e["b"]}
    # 2. the model's informative pairs (half the sheet) once it is fitted
    if f.model is not None:
        for _ in range(max(0, n // 2 - len(out))):
            p = f.human_pair(sorted(used))
            if not p:
                break
            a, b = p["a"]["id"], p["b"]["id"]
            out.append({"a": a, "b": b, "why": "model"})
            used |= {a, b}
    # 3. cold-start order, then random unseen images: pairs that look different
    seen = f._seen(ev, sorted(used))
    dup = (f.model or {}).get("dup") or set()
    answered = sum(1 for e in ev if e.get("action") or e.get("winner") in ("a", "b"))
    cold = [i for i in sp.cold if i not in seen and i not in dup] if answered < M.COLD_START else []
    rest = [i for i in sp.serve_ids if i not in seen and i not in dup and i not in set(cold)]
    rng.shuffle(rest)
    cand = cold + rest
    why_of = {i: ("cold" if i in set(cold) else "explore") for i in cand}

    def different(x: str, y: str) -> bool:
        ix, iy = sp.index.get(x), sp.index.get(y)
        if ix is None or iy is None:
            return True
        c = float(sp.X[ix] @ sp.X[iy])
        return c < M.PAIR_LOOKALIKE and not sp.same_project(ix, iy, c)

    while len(out) < n and len(cand) >= 2:
        a = cand.pop(0)
        j = next((k for k, y in enumerate(cand[:200]) if different(a, y)), None)
        if j is None:
            continue
        b = cand.pop(j)
        out.append({"a": a, "b": b, "why": why_of[a]})
    # 4. a small pool runs out of unseen images: pair images seen least often, never a pair asked before (random
    #    pairs teach the model as much as model-chosen near-ties and keep the meter honest: see the docstring)
    if len(out) < n:
        asked = {frozenset((e["a"], e["b"])) for e in ev if e.get("a") and e.get("b")}
        uses: dict[str, int] = {}
        for e in ev:
            for x in (e.get("item"), e.get("a"), e.get("b")):
                if x:
                    uses[x] = uses.get(x, 0) + 1
        taken = {x for p in out for x in (p["a"], p["b"])} | used
        old = [i for i in sp.serve_ids if i not in taken and i not in dup]
        rng.shuffle(old)
        old.sort(key=lambda i: uses.get(i, 0))
        while len(out) < n and len(old) >= 2:
            a = old.pop(0)
            j = next((k for k, y in enumerate(old[:200]) if different(a, y) and frozenset((a, y)) not in asked), None)
            if j is None:
                continue
            out.append({"a": a, "b": old.pop(j), "why": "reuse"})
    for p in out:                   # randomise sides: the left image is the first slot
        if p["why"] != "repeat" and rng.random() < 0.5:
            p["a"], p["b"] = p["b"], p["a"]
    rng.shuffle(out)
    return out


# ---------------------------------------------------------------- rendering

def _fonts():
    from . import synth as Y
    return Y.font("grotesk", 40), Y.font("grotesk", 26), Y.font("grotesk", 48)


def _tile(path: Path):
    from PIL import Image
    im = Image.open(path)
    im.draft("RGB", (CELL_W * 2, CELL_H * 2))
    im = im.convert("RGB")
    im.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
    return im


def render(pdir: Path, rows: list[dict], out: Path, first: int, last: int, total: int, sid: str = "") -> dict:
    from PIL import Image, ImageDraw
    h = HEAD + len(rows) * (CELL_H + ROW_GAP) - ROW_GAP + FOOT
    im = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(im)
    f_title, f_small, f_badge = _fonts()
    d.text((MARGIN, 26), f"Pairs {first}–{last} of {total}: which one do you like more?", font=f_title, fill=INK)
    d.text((MARGIN, 80), "Reply with a number and a letter for every pair, e.g. "
                         + " ".join(f"{k}{'ab'[(k - first) % 2]}" for k in range(first, min(last, first + 2) + 1)),
           font=f_small, fill=(170, 168, 160))
    for k, row in enumerate(rows):
        y = HEAD + k * (CELL_H + ROW_GAP)
        for side, x in (("a", MARGIN), ("b", MARGIN + CELL_W + GAP)):
            d.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], fill=CELL_BG)
            try:
                t = _tile(images_dir(pdir) / f"{row[side]}.jpg")
                im.paste(t, (x + (CELL_W - t.width) // 2, y + (CELL_H - t.height) // 2))
            except (OSError, ValueError):
                d.text((x + 20, y + CELL_H // 2), "(image missing)", font=f_small, fill=INK)
            label = f"{row['n']}{side}"
            tw = d.textlength(label, font=f_badge)
            d.rounded_rectangle([x + 10, y + 10, x + 10 + tw + 28, y + 10 + 64], radius=10, fill=BADGE)
            d.text((x + 24, y + 14), label, font=f_badge, fill=(18, 18, 18))
    d.text((MARGIN, h - FOOT + 30), "a = left · b = right · t = can't choose · x = skip"
           + (f"      sheet {sid}" if sid else ""), font=f_small, fill=(170, 168, 160))
    q, scale = 88, 1.0
    for _ in range(12):
        src = im if scale == 1.0 else im.resize((round(W * scale), round(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        src.save(buf, "JPEG", quality=q, optimize=True, progressive=True)
        if buf.tell() <= MAX_BYTES:
            break
        if q > 60:
            q -= 8
        else:
            scale *= 0.85
    tmp = out.with_name(out.stem + ".tmp.jpg")
    tmp.write_bytes(buf.getvalue())
    tmp.replace(out)
    return {"file": str(out), "bytes": buf.tell(), "quality": q, "size": list(src.size)}


def _render_all(pdir: Path, d: Path, rows: list[dict], per_sheet: int, sid: str) -> list[dict]:
    files = []
    for s in range(0, len(rows), per_sheet):
        part = rows[s:s + per_sheet]
        files.append(render(pdir, part, d / f"sheet-{s // per_sheet + 1}.jpg", part[0]["n"], part[-1]["n"],
                            len(rows), sid))
    return files


def _reprint(pdir: Path, sh: dict, others: list[dict]) -> dict:
    """the open sheet again (a retry, or the bot lost track of it): the same images, message and record command"""
    d = Path(sh["_path"]).parent
    paths = [d / f for f in sh.get("files") or []]
    if not paths or not all(p.is_file() for p in paths):
        paths = [Path(f["file"]) for f in _render_all(pdir, d, sh["pairs"], int(sh.get("per_sheet") or PER_SHEET),
                                                      sh["id"])]
    miss = _unanswered(sh)
    done = [p["n"] for p in sh["pairs"] if p["n"] not in miss]
    lines = [f"sheet {sh['id']} (made {str(sh.get('created')).replace('T', ' ')}"
             + (f" from project {sh['project']}" if sh.get("project") else "")
             + f") is still waiting for the owner's reply: pairs {_ranges(miss)} unanswered"
             + (f" ({_ranges(done)} already recorded)" if done else "") + ". No new sheet was made.",
             f"If the owner has not seen it yet, send these {len(paths)} images in ONE message with this text:",
             f"  {sh.get('message') or ''}"]
    lines += [f"  {p}" for p in paths]
    lines.append(f"Record the reply exactly as written: {_record_cmd(sh['id'])}")
    if others:
        lines.append("other sheets waiting for a reply: " + "; ".join(_describe(o) for o in others))
    lines.append(f"A fresh sheet instead: slop taste sheet --new   (the owner will not answer this one: "
                 f"slop taste sheet --discard {sh['id']})")
    return {"sheet": sh["id"], "reprinted": True, "pairs": len(sh["pairs"]), "files": [str(p) for p in paths],
            "missing": miss, "message": sh.get("message"), "project": sh.get("project"),
            "open": [o["id"] for o in others] + [sh["id"]], "record": _record_cmd(sh["id"]), "text": "\n".join(lines)}


def make_sheets(pdir: Path, pairs: int = PAIRS, per_sheet: int = PER_SHEET, seed: int | None = None,
                new: bool = False) -> dict:
    pdir = Path(pdir)
    if pairs < 1 or pairs > 40:
        raise SlopError("--pairs must be between 1 and 40 (12 is one comfortable reply)")
    if per_sheet < 1 or per_sheet > 6:
        raise SlopError("--per-sheet must be between 1 and 6 (4 keeps the images readable on a phone)")
    from .pool import load_pool
    pool = load_pool(pdir)
    if not pool:
        raise SlopError("the reference pool is empty: add the user's references first, e.g. `slop taste pool add "
                        "--dir FOLDER` (or `--starter` for a user with none), then `slop taste embed`")
    op = open_sheets(list_sheets(pdir))
    if op and not new:
        return _reprint(pdir, op[-1], op[:-1])
    chosen = choose_pairs(pdir, pairs, seed)
    if not chosen:
        raise SlopError("every image in the pool has been answered: add more references (slop taste pool add ...), "
                        "then run slop taste sheet again")
    from .profile import project_name
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + new_eid()[:4]
    d = sheets_dir(pdir) / sid
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"n": k + 1, **p} for k, p in enumerate(chosen)]
    files = _render_all(pdir, d, rows, per_sheet, sid)
    example = " ".join(f"{r['n']}{'ab'[k % 2]}" for k, r in enumerate(rows[:4])) + (" ..." if len(rows) > 4 else "")
    msg = MESSAGE.format(example=example)
    sheet = {"id": sid, "created": now_iso(), "project": project_name(pdir), "project_dir": str(pdir), "pairs": rows,
             "files": [Path(f["file"]).name for f in files], "per_sheet": per_sheet, "answers": {}, "message": msg}
    write_json(d / "sheet.json", sheet)
    why = {}
    for r in rows:
        why[r["why"]] = why.get(r["why"], 0) + 1
    paths = [f["file"] for f in files]
    vec = _has_vectors(pdir, pool)
    return {"sheet": sid, "pairs": len(rows), "files": paths, "bytes": [f["bytes"] for f in files], "why": why,
            "message": msg, "short": len(rows) < pairs, "project": sheet["project"], "record": _record_cmd(sid),
            "vectors": vec, "open": [o["id"] for o in op] + [sid],
            "text": (f"sheet {sid}: {len(rows)} pairs on {len(paths)} image(s) (largest "
                     f"{max(f['bytes'] for f in files) / 1e6:.2f} MB):\n" + "\n".join(f"  {p}" for p in paths)
                     + f"\nSend all {len(paths)} images in ONE message with this text:\n  {msg}\n"
                     f"Then record the reply exactly as written: {_record_cmd(sid)}"
                     + (f"\n(only {len(rows)} of {pairs} pairs: the pool is running out of images — add more "
                        "references)" if len(rows) < pairs else "")
                     + (f"\nnote: {len(op)} older sheet(s) are still open too ({', '.join(o['id'] for o in op)}); "
                        "always record with --sheet" if op else "")
                     + ("" if vec else "\n" + NO_VECTORS))}


def discard(pdir: Path, sid: str) -> dict:
    sh = _find(list_sheets(pdir), sid)
    miss = _unanswered(sh)
    sh["discarded"] = now_iso()
    path = Path(sh.pop("_path"))
    write_json(path, sh)
    return {"sheet": sh["id"], "discarded": True, "unanswered": miss,
            "text": f"sheet {sh['id']} closed ({len(miss)} unanswered pairs dropped; a late reply can still be "
                    f"recorded with --sheet {sh['id']}). next: slop taste sheet"}


def _find(sheets: list[dict], sid: str) -> dict:
    sid = (sid or "").strip()
    hit = [s for s in sheets if s["id"] == sid] or [s for s in sheets if sid and s["id"].startswith(sid)]
    if len(hit) != 1:
        recent = "; ".join(_describe(s) for s in sheets[-5:]) or "none yet (slop taste sheet)"
        raise SlopError(f"no sheet {sid!r}" + (" (the prefix matches several)" if len(hit) > 1 else "")
                        + f"; sheets: {recent}. Nothing was recorded")
    return hit[0]


# ---------------------------------------------------------------- recording answers

def _ignorable(piece: str, edge: bool) -> bool:
    """punctuation / emoji anywhere, or a greeting / sign-off before or after the answers (never digits)"""
    t = "".join(ch for ch in piece if unicodedata.category(ch)[0] in "LNZ")
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return True
    return edge and not re.search(r"\d", t) and bool(SIGNOFF_RE.match(t))


def parse_answers(text: str) -> list[tuple[int, str]]:
    s = re.sub(r"[,;/|\n\t]+", " ", (text or "").strip().lower())
    out: list[tuple[int, str]] = []
    pos, junk = 0, []
    matches = list(ANSWER_RE.finditer(s))
    for k, m in enumerate(matches):
        gap = s[pos:m.start()].strip()
        if gap and not _ignorable(gap, edge=k == 0):
            junk.append(gap)
        out.append((int(m.group(1)), ANSWER_WORDS[m.group(2)]))
        pos = m.end()
    tail = s[pos:].strip()
    if tail and not _ignorable(tail, edge=True):
        junk.append(tail)
    if junk or not out:
        what = f"could not read {', '.join(repr(j) for j in junk)}" if junk else "no answers found"
        raise SlopError(f"{what} in the reply. Write one number and letter per pair, e.g. \"1a 2b 3a\" (a = left, "
                        "b = right, t = can't choose, x = skip), then run slop taste record again; nothing was recorded")
    return out


def _quick_meter(pdir: Path) -> tuple[dict | None, int, bool]:
    """-> (the meter or None, answered rows with vectors, whether the pool has vectors at all)"""
    from .embed import load_store
    from .pool import load_pool
    items = load_pool(pdir)
    ids, X, _ = load_store(pdir)
    keep = [k for k, i in enumerate(ids) if i in items]
    if not keep:
        return None, 0, False
    ids = [ids[k] for k in keep]
    X = X[keep].astype("float32")
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    index = {i: k for k, i in enumerate(ids)}
    unary, pairs = split_events(read_events(taps_path(pdir)))
    rows = len(M.rows_of(unary, pairs, index))
    m = M.meter(X, index, unary, pairs, reps=1)
    if m:
        append_jsonl(taste_dir(pdir) / "meter.jsonl", {"t": now_iso(), "source": "cli", **m})
    return m, rows, True


def record(pdir: Path, answers: str, sheet: str | None = None, redo: bool = False, meter: bool = True) -> dict:
    pdir = Path(pdir)
    sheets = list_sheets(pdir)
    if not sheets:
        raise SlopError("no pair sheet yet: run `slop taste sheet`, send the images, then record the reply")
    if sheet:
        sh = _find(sheets, sheet)
    else:
        op = open_sheets(sheets)
        if len(op) > 1:
            raise SlopError(
                f"{len(op)} pair sheets are waiting for a reply, so it is not clear which one this reply answers "
                "(nothing was recorded). Record it against the sheet whose images you sent (its id is in the image "
                "file paths and at the bottom of each image):\n"
                + "\n".join(f"  {_describe(s)}: {_record_cmd(s['id'])}" for s in op)
                + "\nA sheet the owner will not answer: slop taste sheet --discard ID")
        sh = op[0] if op else sheets[-1]
    parsed = parse_answers(answers)
    by_n = {p["n"]: p for p in sh["pairs"]}
    bad = sorted({n for n, _ in parsed if n not in by_n})
    if bad:
        raise SlopError(f"sheet {sh['id']} has pairs 1-{max(by_n)}; the reply names {', '.join(map(str, bad))}. "
                        "Check you are recording the reply to the right sheet (pass --sheet ID); nothing was "
                        "recorded")
    want: dict[int, str] = {}
    for n, w in parsed:
        if n in want and want[n] != w:
            raise SlopError(f"pair {n} is answered twice ({want[n]} and {w}); fix the reply; nothing was recorded")
        want[n] = w
    from .pool import load_pool
    pool = load_pool(pdir)
    answered = dict(sh.get("answers") or {})
    rec_n, again, gone = [], [], []
    tp = taps_path(pdir)
    for n in sorted(want):
        p, w = by_n[n], want[n]
        if str(n) in answered and not redo:
            again.append(n)
            continue
        if p["a"] not in pool or p["b"] not in pool:
            gone.append(n)
            continue
        if str(n) in answered and redo:
            append_jsonl(tp, {"undo": answered[str(n)]["eid"], "t": now_iso()})
        rec = {"eid": new_eid(), "t": now_iso(), "a": p["a"], "b": p["b"], "winner": w, "via": "sheet",
               "dwell_ms": 0, "shown": "ab", "layout": "sheet", "sheet": sh["id"], "n": n, "why": p.get("why", "")}
        append_jsonl(tp, rec)
        answered[str(n)] = {"winner": w, "eid": rec["eid"], "t": rec["t"]}
        rec_n.append(n)
    sh["answers"] = answered
    path = Path(sh.pop("_path"))
    write_json(path, sh)
    missing = _unanswered(sh)
    ev = read_events(tp)
    unary, pairs = split_events(ev)
    taps = len(unary) + sum(1 for e in ev if e.get("winner"))
    m, rows, vec = None, None, _has_vectors(pdir, pool)
    t_meter = None
    if meter and rec_n and vec:
        t0 = time.monotonic()
        try:
            m, rows, vec = _quick_meter(pdir)
        except Exception:  # noqa: BLE001 — a meter failure must never lose recorded answers
            m = None
        t_meter = round(time.monotonic() - t0, 2)
    counts = {w: sum(1 for n in rec_n if want[n] == w) for w in ("a", "b", "tie", "skip")}
    hist = read_jsonl(taste_dir(pdir) / "meter.jsonl")
    stop = M.stop_rule(hist, taps)
    agree = M.self_agreement(ev)
    lines = [f"recorded {len(rec_n)} answers from sheet {sh['id']} ({counts['a']} left, {counts['b']} right, "
             f"{counts['tie']} ties, {counts['skip']} skips); {taps} taps in the taste profile ({len(pairs)} decisive "
             "pairs)"]
    if again:
        lines.append(f"already answered (kept; --redo replaces them): {', '.join(map(str, again))}")
    if gone:
        lines.append(f"skipped (image no longer in the pool): {', '.join(map(str, gone))}")
    if missing:
        lines.append(f"still unanswered on this sheet: {', '.join(map(str, missing))} — ask for them, then: "
                     f"slop taste record --sheet {sh['id']} \"{' '.join(f'{n}a' for n in missing[:3])} ...\"")
    if not vec:
        lines.append(NO_VECTORS)
    elif m:
        lines.append(f"the model now picks the one you prefer {m['accuracy'] * 100:.0f} % ± {m['margin'] * 100:.0f} "
                     f"of the time (held-out, n = {m['n']}; 50 % = chance)")
    elif meter and rows is not None and rows < 20:
        lines.append(f"the meter starts at 20 answers with image vectors ({rows} so far)")
    elif meter and rec_n:
        lines.append("the quick meter could not run this time; run: slop taste meter")
    if agree["self_agreement"] is not None:
        lines.append(f"self-agreement {agree['self_agreement'] * 100:.0f} % on {agree['repeats']} repeats")
    lines.append(("enough for now: " if stop["stop"] else "next: slop taste sheet (more pairs) — ") + stop["why"])
    return {"sheet": sh["id"], "recorded": rec_n, "already": again, "missing": missing, "skipped": gone,
            "answers": counts, "taps": taps, "pairs": len(pairs), "meter": m, "meter_seconds": t_meter,
            "vectors": vec, **agree, "stop": stop, "text": "\n".join(lines)}
