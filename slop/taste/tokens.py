"""Taste tokens, the look-bible suggestion and mood boards (``slop taste tokens`` / ``slop taste board``).

Tokens follow the TASTE-AUDIT procedure of research 11-gap-5 §3 (S1-S9) with its principles:
  * references tell you the SYSTEM (restraint, ground, density, type), never the footage grade: the EV audit's
    "mono + one red" thesis was right about the references and wrong for the video ("way too.. gray"), so
    `footage_grade` defaults to "native" and is asked, never imposed;
  * the accent hue comes from the owner — S2 only lists candidates; texture/grain is a yes/no QUESTION;
  * every rule carries a status (hypothesis / lead / measured / confirmed) and its denominator + test;
  * pair winners count as likes and losers as passes for the unary statistics (words.py convention); every image
    keeps its LAST answer (repeats and undo respected).
Statistics: S1 near-mono share (mean HSV saturation < 0.12 on 64x64) + coloured share, Fisher exact p; S2 hue lean
(share_L − share_P > 0.15 and Fisher p < 0.05, >= 20 coloured likes); S3 ground split (dark < 0.35 / light > 0.65)
and contrast; composition means (hypothesis); S4 modes (k-means on liked vectors, >= 8 likes each, named by their
nearest style-vocabulary phrases); S5 words (phrase AUC over likes vs passes ± Hanley–McNeil, the retired
feed/words.py with its 83-phrase vocabulary); S6 anti-sources (>= 6 taps, like-rate <= 0.1, (1 − base)^n < 0.05);
S7 longest-dwell likes; top items by the deployed model; S9 the position-corrected font ranking if it exists.
Boards are the retired studio/engine/inspo.py ranking: SigLIP text query(s) standardised per query, pool = top
max(6n, 300), rank by match + 0.4·taste_z + 1.0·[liked and match >= core], passes excluded, same-project collapsed
(cosine > 0.8 or shared keys); refs.json = the same ranking over TEXT-FREE images only ("a reference with lettering
teaches Midjourney to letter"). Text-free is judged zero-shot by the same embedder (text prompts vs no-text prompts)
instead of the retired EasyOCR CRAFT boxes (no OCR dependency on the box), with a calibrated cutoff (textfree.py).

Fixer changes (review round 1):
  * refs.json cutoff (SUPERSEDED by the paired probe in textfree.py, see Profiles + verdicts below): the stricter of
    a cutoff calibrated on rendered lettering probes and the pool's least-text
    third (the old absolute "< 0" passed 86-95 % of lettered images); the cutoff and how it was chosen are recorded;
  * board exclusions restored to inspo.py: liked = unary likes + pair winners, passed = unary passes - liked (a
    strong image that lost one pair is no longer dropped); the refs candidate pool is max(5 n, 300) of the board n;
  * S6 anti-sources also work for --dir / --urls pools and the starter deck: the source is the Are.na channel, else
    the item's `group` (dir:<folder>, url:<host>, starter:<template>), else the URL host;
  * `limited` restraint = >= 75 % of likes use <= 3 hue families (each >= 10 % of the image's colour pixels),
    matching the docs' "limited (<= 3)"; the old "coloured share of likes <= 0.5" had no source;
  * p-values keep 3 significant digits in JSON and print as "p < 0.0001" instead of "p = 0.0";
  * text embeddings with a paid OpenRouter model are budget-checked (`--yes` passes the confirm gate).
Profiles + verdicts (taste-profile track): the statistics come from the taste PROFILE (shared by every project linked
to the user profile); taste-tokens.json, look-bible.md and boards/ are written in the PROJECT's taste/ folder. The
owner's rule verdicts (verdicts.py; `slop taste verdict`) are honoured after the statistics: confirmed / rejected
statuses (the statistical one kept as `stat_status`), owner values (accent, footage grade, lyric font), answered
questions moved to `answered_questions`, stale verdicts listed to ask again; `look_suggestion` uses only
owner-confirmed values (`slop taste apply` writes them).
Text-free refs (the same track, validated on real images): `board` scores lettering with textfree.assess — a ridge
probe on the user's own images vs lettered copies of them (held-out AUC 0.995 on real Midjourney images vs 0.758
for the zero-shot score, whose synthetic calibration kept 0 of 509 real text-free images).
"""
from __future__ import annotations

import math
import shutil
from pathlib import Path

import numpy as np

from ..config import SlopError
from . import model as M
from . import embed as E
from . import textfree as TF
from .embed import load_store, text_vectors
from .imgstats import DARK, HUE_NAMES, LIGHT, NEAR_MONO, stats_for
from .textfree import NOTEXT_PROBES, TEXT_PROBES, text_free_scores  # noqa: F401  (re-exported)
from .pool import image_path, load_pool
from .store import (project_taste_dir, read_events, read_json, read_jsonl, slugify, split_events, taps_path, taste_dir,
                    write_json)

PHRASES = [
    # genre / object
    "a poster", "a book spread", "a magazine layout", "a type specimen", "a logo", "a set of icons", "a label or sticker",
    "packaging", "an album cover", "a business card", "a website screenshot", "a mobile app interface", "a product mockup",
    "a t-shirt mockup", "a brand identity presentation", "an infographic", "a data visualization", "a chart", "a map",
    "a technical drawing", "a scientific figure", "a hand-drawn diagram", "a flowchart", "a spec sheet with small technical text",
    "an industrial warning label", "a photograph of printed matter", "an exhibition installation", "signage",
    # type
    "big bold sans-serif typography", "elegant serif typography", "italic script lettering", "monospace text",
    "distorted experimental typography", "tiny text", "japanese typography", "handwriting", "a single large letter",
    # composition
    "a minimal composition with lots of empty space", "a dense layout full of text", "a strict grid layout", "centered symmetric layout",
    "an asymmetric layout", "a collage", "repeating pattern", "lines and circles", "dots", "waveforms", "abstract geometric shapes",
    # tone / surface
    "black and white", "dark background", "white background", "cream paper", "colorful", "neon colors", "pastel colors",
    "red accent color", "blue", "green", "orange", "gradient", "grainy texture", "halftone print", "photocopy xerox texture",
    "glossy 3d render", "blurred photograph", "a photograph of a person", "fashion photography", "a vintage print from the 1970s",
    "retro futurism", "brutalist design", "swiss international style", "corporate design", "playful cartoon illustration",
    "rave flyer", "street art", "luxury brand", "tech startup branding", "scientific archive", "military or aerospace",
    "cyberpunk", "y2k aesthetic", "hand-made craft", "computer generated art",
]
TEXTURE_PHRASES = ["grainy texture", "halftone print", "photocopy xerox texture", "dots"]
MIN_LIKES_S1, MIN_COLOURED_S2, MODE_MIN = 60, 20, 8
FEW_HUES, HUE_FAMILY_MIN, LIMITED_SHARE = 3, 0.10, 0.75   # "limited (<= 3 colours)": hue families per image


# ---------------------------------------------------------------- labels

def labels(events: list[dict]) -> tuple[dict[str, float], dict[str, int]]:
    """{item: 1 like / 0 pass} — the last answer per image; pair winner = like, loser = pass. Also {item: dwell}"""
    lab: dict[str, float] = {}
    dwell: dict[str, int] = {}
    for e in events:
        if e.get("action") in ("like", "pass"):
            lab[e["item"]] = 1.0 if e["action"] == "like" else 0.0
            if e["action"] == "like":
                dwell[e["item"]] = max(dwell.get(e["item"], 0), int(e.get("dwell_ms") or 0))
        elif e.get("winner") in ("a", "b"):
            w, lo = (e["a"], e["b"]) if e["winner"] == "a" else (e["b"], e["a"])
            lab[w], lab[lo] = 1.0, 0.0
    return lab, dwell


def hanley_mcneil(a: float, n1: int, n0: int) -> float:
    if n1 < 1 or n0 < 1:
        return 1.0
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    se = math.sqrt(max(0.0, (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)))
    return 1.96 * se


def pnum(p: float) -> float:
    """a p-value for JSON: 3 significant digits (never rounded down to 0.0)"""
    return float(f"{p:.3g}")


def ptxt(p: float) -> str:
    return "p < 0.0001" if p < 1e-4 else f"p = {p:.4g}"


def n_hues(s: dict) -> int:
    """hue families covering >= 10 % of an image's colour pixels (0 for an image that shows no colour)"""
    if not s.get("coloured") or not s.get("hue_counts"):
        return 0
    c = np.asarray(s["hue_counts"], dtype=float)
    return int((c / max(c.sum(), 1.0) >= HUE_FAMILY_MIN).sum())


def source_group(it: dict) -> str | None:
    """where an image came from, for the anti-source statistic (S6)"""
    if it.get("channel"):
        return str(it["channel"])
    if it.get("group"):
        return str(it["group"])
    u = it.get("source_url") or (it.get("origin") if str(it.get("origin", "")).startswith("http") else None)
    if u:
        from urllib.parse import urlparse
        host = urlparse(str(u)).netloc.lower()
        return f"url:{host}" if host else None
    return None


def _share(xs) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 3) if xs else None


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


def _median_hex(hexes: list[str]) -> str | None:
    hs = [h for h in hexes if h]
    if not hs:
        return None
    arr = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in hs], dtype=float)
    r, g, b = np.median(arr, axis=0)
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


# ---------------------------------------------------------------- tokens

def build_tokens(pdir: Path, words: bool = True, embedder=None, yes: bool = False) -> dict:
    pdir = Path(pdir)
    items = load_pool(pdir)
    ev = read_events(taps_path(pdir))
    lab, dwell = labels(ev)
    lab = {i: y for i, y in lab.items() if i in items}
    L = [i for i, y in lab.items() if y == 1]
    P = [i for i, y in lab.items() if y == 0]
    if len(L) < 5 or len(P) < 5:
        raise SlopError(f"not enough taps for tokens ({len(L)} likes, {len(P)} passes; need >= 5 of each, "
                        f"{M.MIN_TAPS}+ taps recommended): run `slop taste serve` and tap first")
    st = stats_for(pdir, items, L + P)
    L = [i for i in L if i in st]
    P = [i for i in P if i in st]
    unary, pairs = split_events(ev)
    out: dict = {"version": 1, "evidence": {}, "palette": {}, "ground": {}, "texture": {}, "composition": {},
                 "type": {}, "modes": [], "words": {}, "anti_sources": [], "references": {}, "open_questions": []}
    hist = read_jsonl(taste_dir(pdir) / "meter.jsonl")
    last_meter = hist[-1] if hist else None
    out["evidence"] = {"taps": len(unary) + len(pairs) + sum(1 for e in ev if e.get("winner") in ("tie", "skip")),
                       "likes": len(L), "passes": len(P), "pairs": len(pairs),
                       "meter": last_meter and last_meter.get("accuracy"), "margin": last_meter and last_meter.get("margin"),
                       **M.self_agreement(ev)}

    # S1 colour restraint
    monoL = sum(st[i]["sat"] < NEAR_MONO for i in L)
    monoP = sum(st[i]["sat"] < NEAR_MONO for i in P)
    colL = sum(bool(st[i]["coloured"]) for i in L)
    colP = sum(bool(st[i]["coloured"]) for i in P)
    p_mono = M.fisher_exact(monoL, len(L) - monoL, monoP, len(P) - monoP)
    p_col = M.fisher_exact(colL, len(L) - colL, colP, len(P) - colP)
    mono_share_L, col_share_L, col_share_P = monoL / len(L), colL / len(L), colP / max(1, len(P))
    few_L = sum(n_hues(st[i]) <= FEW_HUES for i in L) / len(L)
    few_P = sum(n_hues(st[i]) <= FEW_HUES for i in P) / max(1, len(P))
    if (col_share_L < col_share_P and p_col < 0.05) or mono_share_L >= 0.75:
        restraint = "mono+1"
    elif few_L >= LIMITED_SHARE:
        restraint = "limited"
    else:
        restraint = "colourful"
    s1_status = "measured" if len(L) >= MIN_LIKES_S1 and (p_col < 0.05 or p_mono < 0.05) else "lead"
    # S2 hue lean among coloured images
    cL = [i for i in L if st[i]["coloured"]]
    cP = [i for i in P if st[i]["coloured"]]
    hue_rows, cands = [], []
    for h in HUE_NAMES:
        a = sum(st[i]["hue"] == h for i in cL)
        b = sum(st[i]["hue"] == h for i in cP)
        sL, sP = a / max(1, len(cL)), b / max(1, len(cP))
        p = M.fisher_exact(a, len(cL) - a, b, len(cP) - b)
        lean = len(cL) >= MIN_COLOURED_S2 and sL - sP > 0.15 and p < 0.05
        hue_rows.append({"hue": h, "likes": a, "passes": b, "share_likes": round(sL, 3), "share_passes": round(sP, 3),
                         "p": pnum(p), "leans": lean,
                         "observed_hex": _median_hex([st[i].get("accent_hex") for i in cL if st[i]["hue"] == h])})
        if lean:
            cands.append(h)
    paper = _median_hex([st[i].get("light_hex") for i in L])
    ink = _median_hex([st[i].get("dark_hex") for i in L])
    out["palette"] = {
        "restraint": restraint, "status": s1_status, "scope": "graphics only (not the footage)",
        "near_mono_share": {"likes": round(mono_share_L, 3), "passes": round(monoP / max(1, len(P)), 3), "p": pnum(p_mono),
                            "threshold": f"mean HSV saturation < {NEAR_MONO} on 64x64"},
        "coloured_share": {"likes": round(col_share_L, 3), "passes": round(col_share_P, 3), "p": pnum(p_col)},
        "few_colour_share": {"likes": round(few_L, 3), "passes": round(few_P, 3),
                             "threshold": f"<= {FEW_HUES} hue families, each >= {HUE_FAMILY_MIN:.0%} of the colour pixels",
                             "limited_if_likes_at_least": LIMITED_SHARE},
        "restraint_rule": "mono+1 if likes are less often coloured (Fisher p < 0.05) or >= 75 % near-mono; else "
                          "limited if >= 75 % of likes use <= 3 hue families; else colourful",
        "mean_saturation": {"likes": _mean(st[i]["sat"] for i in L), "passes": _mean(st[i]["sat"] for i in P)},
        "hues": hue_rows,
        "red_orange": {   # the audit's red/orange masks: share of colour pixels per mask, and red-dominant overall
            "red_share_of_colour": {"likes": _mean(st[i].get("red_share") for i in cL),
                                    "passes": _mean(st[i].get("red_share") for i in cP)},
            "orange_share_of_colour": {"likes": _mean(st[i].get("orange_share") for i in cL),
                                       "passes": _mean(st[i].get("orange_share") for i in cP)},
            "red_dominant_overall": {"likes": _share(st[i]["hue"] == "red" for i in L),
                                     "passes": _share(st[i]["hue"] == "red" for i in P)},
            "note": "a hue lean among coloured images is not a brand accent: on the original study only 11 % of "
                    "likes were red-dominant vs 8.7 % of passes"},
        "accent": None, "accent_candidates": cands, "accent_source": "ask-owner",
        "paper": paper, "ink": ink, "footage_grade": "native",
        "note": "the feed says HOW MUCH colour, not WHICH: the accent comes from the owner (brand / statement)"}
    # S3 ground + contrast
    gl = [st[i]["ground_lum"] for i in L]
    out["ground"] = {"likes_dark": sum(g < DARK for g in gl), "likes_light": sum(g > LIGHT for g in gl),
                     "likes_mid": sum(DARK <= g <= LIGHT for g in gl),
                     "mean_lum": {"likes": _mean(st[i]["lum"] for i in L), "passes": _mean(st[i]["lum"] for i in P)},
                     "contrast": {"likes": _mean(st[i]["lum_std"] for i in L), "passes": _mean(st[i]["lum_std"] for i in P)},
                     "dark_frac": {"likes": _mean(st[i]["dark_frac"] for i in L), "passes": _mean(st[i]["dark_frac"] for i in P)},
                     "status": "lead", "note": "a light/dark arc only if the owner wants one"}
    comp = {}
    for k in ("edge", "quiet", "mass_x", "mass_y", "symmetry"):
        comp[k] = {"likes": _mean(st[i][k] for i in L), "passes": _mean(st[i][k] for i in P)}
    comp["edge_by_third_v"] = {"likes": [round(float(np.mean([st[i]["thirds_v"][t] for i in L])), 3) for t in range(3)]}
    comp["status"] = "hypothesis"
    comp["note"] = "descriptive; confirm on 2-3 rendered style frames before it becomes a rule"
    out["composition"] = comp

    # vectors: modes, words, top items
    ids, X, meta = load_store(pdir)
    index = {i: n for n, i in enumerate(ids)}
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12) if len(X) else X
    tscore = M.taste_scores(Xn, index, unary, pairs) if len(Xn) else None
    if tscore is not None and len(Xn):
        liked_rows = sorted((i for i in L if i in index), key=lambda i: -tscore[index[i]])
        out["references"]["top_liked"] = [{"id": i, "file": f"pool/images/{i}.jpg", "taste": round(float(tscore[index[i]]), 2),
                                           "title": items[i].get("title", ""), "path": str(image_path(pdir, items[i]))}
                                          for i in liked_rows[:12]]
        out["references"]["root"] = str(taste_dir(pdir))   # `file` is relative to the taste profile's root
    out["references"]["longest_dwell"] = [{"id": i, "dwell_s": round(dwell[i] / 1000, 2)}
                                          for i in sorted((i for i in L if i in dwell), key=lambda i: -dwell[i])[:10]]
    V = None
    if words and len(Xn) and meta.get("tag"):
        V = text_vectors(meta, PHRASES, embedder=embedder, pdir=pdir, yes=yes)
        V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-12)
        U = [(i, lab[i]) for i in L + P if i in index]
        y = np.array([v for _, v in U])
        S = Xn[[index[i] for i, _ in U]] @ V.T
        rows = []
        n1, n0 = int(y.sum()), int(len(y) - y.sum())
        for k, p in enumerate(PHRASES):
            a = M.auc(S[:, k], y)
            if a is None:
                continue
            rows.append({"phrase": p, "auc": round(a, 3), "pm": round(hanley_mcneil(a, n1, n0), 3)})
        rows.sort(key=lambda r: -r["auc"])
        sig = [r for r in rows if abs(r["auc"] - 0.5) > r["pm"]]
        out["words"] = {"liked": [r for r in sig if r["auc"] > 0.5][:10],
                        "passed": [r for r in sorted(sig, key=lambda r: r["auc"]) if r["auc"] < 0.5][:10],
                        "all": rows, "status": "descriptive",
                        "note": "AUC of each phrase's similarity over likes vs passes (0.5 = no relation)"}
        tex = [r for r in rows if r["phrase"] in TEXTURE_PHRASES]
        out["texture"] = {"evidence": tex, "lean": "grain/texture" if any(r["auc"] - 0.5 > r["pm"] for r in tex) else
                          ("clean" if any(0.5 - r["auc"] > r["pm"] for r in tex) else "unclear"),
                          "apply": None, "scope": "graphics-only", "status": "ask-owner"}
    else:
        out["texture"] = {"evidence": [], "lean": "unclear", "apply": None, "scope": "graphics-only", "status": "ask-owner"}
    # S4 modes
    li = [i for i in L if i in index]
    if len(li) >= MODE_MIN and len(Xn):
        k = int(max(1, min(8, len(li) // MODE_MIN)))
        XL = Xn[[index[i] for i in li]]
        labs = M.kmeans(XL, k, seed=0)
        for j in range(labs.max() + 1):
            mem = [li[t] for t in np.flatnonzero(labs == j)]
            if len(mem) < MODE_MIN:
                continue
            c = XL[labs == j].mean(0)
            c = c / (np.linalg.norm(c) + 1e-12)
            ex = sorted(mem, key=lambda i: -float(Xn[index[i]] @ c))[:3]
            name = None
            if V is not None:
                name = ", ".join(PHRASES[t] for t in np.argsort(-(V @ c))[:3])
            out["modes"].append({"name": name or f"mode {j + 1}", "likes": len(mem), "exemplars": ex})
        out["modes"].sort(key=lambda m: -m["likes"])
    # S6 anti-sources (Are.na channels, source folders / URL hosts, starter-deck templates)
    base = len(L) / max(1, len(L) + len(P))
    by_src: dict[str, list[float]] = {}
    for i in L + P:
        s = source_group(items[i])
        if s:
            by_src.setdefault(s, []).append(lab[i])
    for s, ys in sorted(by_src.items()):
        n, rate = len(ys), sum(ys) / len(ys)
        p0 = (1 - base) ** n
        if n >= 6 and rate <= 0.1 and p0 < 0.05:
            out["anti_sources"].append({"source": s, "taps": n, "like_rate": round(rate, 3), "p": pnum(p0)})
    # S9 type
    fr = read_json(taste_dir(pdir) / "fonts" / "ranking.json")
    if fr and fr.get("fonts"):
        out["type"] = {"lyric": (fr.get("recommendation") or {}).get("lyric"),
                       "shortlist": (fr.get("recommendation") or {}).get("shortlist", []),
                       "position_bias_gamma": fr.get("gamma"), "decisive": fr.get("decisive"),
                       "status": (fr.get("recommendation") or {}).get("status", "lead"),
                       "anchor": {"display_size_pct_w": 4.97, "micro_size_pct_w": 1.20, "ratio": 4.13,
                                  "status": "book (round 001-A); store sizes as % of the canvas, never px"}}
    else:
        out["type"] = {"lyric": None, "status": "not measured", "next": "run `slop taste fonts` (A/B on real lyric lines)"}
    out["open_questions"] = questions(out)
    from . import verdicts as VD
    from .profile import project_name
    VD.honour(out, VD.load_rows(pdir), project_name(pdir))     # the owner's verdicts win over the statistics
    out["look_suggestion"] = look_suggestion(out)
    out["profile"] = {"root": str(taste_dir(pdir)), "shared": taste_dir(pdir).resolve() != (pdir / "taste").resolve()}
    write_json(project_taste_dir(pdir) / "taste-tokens.json", out)
    (project_taste_dir(pdir) / "look-bible.md").write_text(look_bible_md(out), encoding="utf-8")
    return out


def questions(t: dict) -> list[dict]:
    """research 11-gap-5 §3.4: always ask accent / footage grade / faces / closest style frame; plus conflicts.
    Each: evidence on both sides, a proposed default, yes/no or A/B, the rule it answers and the exact command for
    each answer (`answers`). At most 8, biggest build impact first."""
    from .verdicts import GRADE_MEANING, QUESTION_RULE, answers_for
    pal, tex = t["palette"], t["texture"]
    qs = []
    cands = pal.get("accent_candidates") or []
    hexes = {h["hue"]: h.get("observed_hex") for h in pal["hues"]}
    hue_ev = ", ".join(f"{h['hue']} {h['likes']}/{h['passes']}" for h in pal["hues"] if h["likes"] or h["passes"])
    qs.append({"id": "accent", "ask": "Which accent colour, if any? (a brand colour, or one you love; or none)",
               "evidence": f"colour restraint: {pal['restraint']} ({pal['coloured_share']['likes'] * 100:.0f} % of your likes "
                           f"show colour vs {pal['coloured_share']['passes'] * 100:.0f} % of passes, {ptxt(pal['coloured_share']['p'])}); "
                           f"hue counts likes/passes among coloured images: {hue_ev or 'none'}",
               "proposal": (f"candidates from your taps: "
                            f"{', '.join(c + (' ' + hexes[c] if hexes.get(c) else '') for c in cands)} — but you choose"
                            if cands else "no hue leans clearly; pick one accent (or none)"), "answer": None})
    qs.append({"id": "footage_grade",
               "ask": "How should the generated footage be coloured: native (the generator's own colour), clean-grade "
                      "(a light grade toward the hero plate) or print (own colour + a halftone / grain screen)?",
               "evidence": f"your references are {pal['near_mono_share']['likes'] * 100:.0f} % near-monochrome — that "
                           "describes the graphics you like, not how your footage should look",
               "grades": dict(GRADE_MEANING),
               "proposal": "native colour for footage; restraint lives in the graphics", "answer": None})
    qs.append({"id": "faces", "ask": "Show the lead's face (sung, lip-synced shots), or hide faces?",
               "evidence": "not measurable from references", "proposal": "show — a singing lead carries a lyric video",
               "answer": None})
    qs.append({"id": "texture", "ask": "Add grain / halftone texture to the graphics? (yes / no)",
               "evidence": "; ".join(f"{r['phrase']} AUC {r['auc']} ±{r['pm']}" for r in tex.get("evidence", [])) or "not measured",
               "proposal": {"grain/texture": "yes, light, graphics only", "clean": "no texture",
                            "unclear": "no texture unless you want it"}[tex.get("lean", "unclear")], "answer": None})
    qs.append({"id": "style_frame", "ask": "Which of these 3 style frames is closest? (and what is wrong with it)",
               "evidence": "every derived rule stays a hypothesis until one verdict on a rendered frame",
               "proposal": "render 3 frames differing on the riskiest axes (native vs graded, accent A vs B, "
                           "coverline vs masthead) on the real song section", "answer": None})
    if t["type"].get("status") in ("lead", "not measured"):
        qs.append({"id": "type", "ask": "Do the lyric lines read well in the leading font on your frame?",
                   "evidence": f"font A/B: {t['type'].get('decisive') or 0} decisive picks"
                               + (f", leader {t['type']['lyric']}" if t['type'].get('lyric') else ""),
                   "proposal": "confirm on the style frame, or run more font A/B", "answer": None})
    for a in t.get("anti_sources", [])[:2]:
        qs.append({"id": f"avoid:{a['source']}", "ask": f"Keep '{a['source']}' out of the look entirely?",
                   "evidence": f"{a['taps']} taps, like-rate {a['like_rate']} ({ptxt(a['p'])})", "proposal": "yes, banned",
                   "answer": None})
    for q in qs:
        q["rule"] = QUESTION_RULE.get(q["id"], q["id"])
        q["answers"] = answers_for(q["rule"], t["type"].get("lyric") if q["id"] == "type" else True)
    return qs[:8]


def look_suggestion(t: dict) -> dict:
    """what `slop taste apply` would propose: owner-confirmed values (verdicts) where they exist, else safe defaults"""
    pal, tex = t["palette"], t.get("texture") or {}
    return {"look.mode": pal.get("footage_grade") if pal.get("footage_grade_status") == "confirmed" else "native",
            "look.accent": pal.get("accent") if pal.get("accent_source") == "owner verdict" else None,
            "look.fonts.lyric": t["type"].get("lyric"),
            "graphics_palette": {"restraint": pal["restraint"] if pal.get("status") != "rejected" else None,
                                 "paper": pal.get("paper"), "ink": pal.get("ink")},
            "texture": tex.get("apply"), "faces": (t.get("faces") or {}).get("show"),
            "style_frame": (t.get("style_frame") or {}).get("pick"),
            "status": "suggestion — apply only what the owner confirms (slop taste apply shows it; --yes writes it)",
            "never": "do not re-grade footage from reference statistics; do not pick the accent for the owner"}


def look_bible_md(t: dict) -> str:
    ev, pal, gr = t["evidence"], t["palette"], t["ground"]
    lines = ["# Look bible — suggestion (owner to confirm)", "",
             f"Evidence: {ev['taps']} taps ({ev['likes']} likes, {ev['passes']} passes, {ev['pairs']} pairs)"
             + (f"; the model predicts you {ev['meter'] * 100:.0f} % ± {ev['margin'] * 100:.0f}" if ev.get("meter") else "")
             + (f"; self-agreement {ev['self_agreement'] * 100:.0f} % on {ev['repeats']} repeats" if ev.get("self_agreement") is not None else "")
             + ".", "",
             "## What your references say (graphics, not footage)",
             f"- **Colour restraint: {pal['restraint']}** ({pal['status']}). {pal['near_mono_share']['likes'] * 100:.0f} % of likes are "
             f"near-monochrome vs {pal['near_mono_share']['passes'] * 100:.0f} % of passes (Fisher {ptxt(pal['near_mono_share']['p'])}); "
             f"coloured {pal['coloured_share']['likes'] * 100:.0f} % vs {pal['coloured_share']['passes'] * 100:.0f} % ({ptxt(pal['coloured_share']['p'])}).",
             f"- Graphics neutrals (hypothesis): paper {pal.get('paper') or '—'}, ink {pal.get('ink') or '—'}.",
             f"- Grounds of your likes: {gr['likes_dark']} dark, {gr['likes_light']} light, {gr['likes_mid']} mid.",
             ]
    if t["words"].get("liked"):
        lines.append("- Liked more when it looks like: " + ", ".join(f"{r['phrase']} ({r['auc']})" for r in t["words"]["liked"][:6]) + ".")
    if t["words"].get("passed"):
        lines.append("- Passed more when it looks like: " + ", ".join(f"{r['phrase']} ({r['auc']})" for r in t["words"]["passed"][:6]) + ".")
    for m in t["modes"][:6]:
        lines.append(f"- Mode: {m['name']} ({m['likes']} likes; e.g. {', '.join(m['exemplars'])}).")
    if t["type"].get("lyric"):
        lines.append(f"- Type: {t['type']['lyric']} leads the position-corrected font A/B ({t['type']['status']}); "
                     "confirm it on a style frame.")
    ls = t.get("look_suggestion") or {}
    vd = t.get("verdicts") or {}
    acc = ls.get("look.accent")
    lines += ["", "## Proposed look (nothing is applied until you say yes)",
              f"- `look.mode`: **{ls.get('look.mode') or 'native'}**"
              + (" (your verdict)." if pal.get("footage_grade_status") == "confirmed" else
                 " — the footage keeps the generator's colour; restraint lives in the graphics."),
              f"- `look.accent`: **{acc}** (your verdict)." if acc else "- `look.accent`: **your call** (see the questions).",
              ("- Texture: **" + ("grain" if ls.get("texture") else "none") + "** (your verdict).")
              if ls.get("texture") is not None else "- Texture: **your call** (see the questions).",
              ("- Faces: **" + ("show" if ls.get("faces") else "hide") + "** (your verdict).")
              if ls.get("faces") is not None else "- Faces: **your call** (see the questions)."]
    if ls.get("style_frame"):
        sf = t.get("style_frame") or {}
        lines.append(f"- Closest style frame: **{ls['style_frame']}** (your verdict)"
                     + (f" — to fix: \"{sf['note']}\"" if sf.get("note") else "") + ".")
    if vd.get("applied"):
        lines += ["", "## Your verdicts (they win over the statistics)"]
        for v in vd["applied"]:
            lines.append(f"- {v['rule']} = {v['value']}: **{v['status']}**" + (f" = {v['meaning']}" if v.get("meaning") else "")
                         + (f" — \"{v['note']}\"" if v.get("note") else "")
                         + (f" (from project {v['project']})" if v.get("carried") else ""))
    if vd.get("stale"):
        lines += ["", "## Verdicts to ask again (the taps moved)"]
        lines += [f"- {v['why']}" for v in vd["stale"]]
    lines += ["", "## Questions"]
    for k, q in enumerate(t["open_questions"], 1):
        lines.append(f"{k}. **{q['ask']}** Evidence: {q['evidence']}. Proposal: {q['proposal']}.")
        for ans, cmd in (q.get("answers") or {}).items():
            lines.append(f"   - {ans}: `{cmd}`")
    if not t["open_questions"]:
        lines.append("None open: every question has an answer.")
    lines += ["", "Record each answer with the command under its question (`slop taste verdict --list` shows every "
              "rule); write the look: `slop taste apply` (preview), then `slop taste apply --yes` after they agree."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- boards

def board(pdir: Path, query: str, n: int = 24, n_refs: int = 12, text_max: float | None = None, embedder=None,
          yes: bool = False) -> dict:
    pdir = Path(pdir)
    items = load_pool(pdir)
    ids, X, meta = load_store(pdir)
    keep = [k for k, i in enumerate(ids) if i in items]
    ids = [ids[k] for k in keep]
    if len(ids) < 2:
        raise SlopError("the pool has no embedded images yet: run `slop taste pool add ...` then `slop taste embed`")
    X = X[keep]
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    index = {i: k for k, i in enumerate(ids)}
    queries = [q.strip() for q in query.replace("|", ";").split(";") if q.strip()]
    if not queries:
        raise SlopError("give a board query, e.g. slop taste board \"dark technical labels; tiny monospace type\"")
    ev = read_events(taps_path(pdir))
    unary, pairs = split_events(ev)
    # inspo.py: liked = unary likes + pair winners; passed = unary passes that were never liked (pair losers stay)
    liked = {i for i, y, _ in unary if y == 1} | {a if y == 1 else b for a, b, y in pairs}
    passed = {i for i, y, _ in unary if y == 0} - liked
    taste = M.taste_scores(X, index, unary, pairs)
    embedder = embedder or E.text_embedder_for(meta, pdir, yes=yes)   # one (lazy) model for queries and probes
    Q = text_vectors(meta, queries, embedder=embedder, pdir=pdir, yes=yes)
    Q = Q / (np.linalg.norm(Q, axis=1, keepdims=True) + 1e-12)
    S = X @ Q.T
    S = (S - S.mean(0)) / (S.std(0) + 1e-9)      # standardise per description
    match = S.max(1)
    pool = np.argsort(-match)[: max(n * 6, 300)]
    cut = float(match[pool[-1]])
    core = float(match[pool[min(len(pool) - 1, n * 2)]])
    keys = [set(items[i].get("keys") or []) for i in ids]
    tfs, tcut = TF.assess(pdir, ids, X, items, meta, embedder=embedder, text_max=text_max, yes=yes)

    def same_project(a: int, b: int) -> bool:
        c = float(X[a] @ X[b])
        if c > 0.8:
            return True
        for k in keys[a] & keys[b]:
            if k.startswith(("behance:", "ig:")) or (k.startswith("page:") and c >= 0.6) or (k.startswith("batch:") and c >= 0.7):
                return True
        return False

    def pick(cands, m):
        rank = sorted(cands, key=lambda k: -(match[k] + 0.4 * taste[k] + (1.0 if ids[k] in liked and match[k] >= core else 0)))
        chosen = []
        for k in rank:
            if ids[k] in passed or any(same_project(k, c) for c in chosen):
                continue
            chosen.append(int(k))
            if len(chosen) >= m:
                break
        return [{"id": ids[k], "file": f"pool/images/{ids[k]}.jpg", "title": items[ids[k]].get("title", ""),
                 "source": items[ids[k]].get("source_url") or items[ids[k]].get("origin", ""),
                 "match": round(float(match[k]), 2), "taste": round(float(taste[k]), 2), "liked": ids[k] in liked,
                 "text_score": round(float(tfs[k]), 4)} for k in chosen]

    slug = slugify(queries[0])
    d = project_taste_dir(pdir) / "boards" / slug
    d.mkdir(parents=True, exist_ok=True)
    items_out = pick(pool, n)
    clean = np.flatnonzero(tfs < tcut["cutoff"])
    refs = pick(clean[np.argsort(-match[clean])[: max(n * 5, 300)]], n_refs) if len(clean) else []
    write_json(d / "board.json", {"query": query, "queries": queries, "match_floor": round(cut, 2), "items": items_out,
                                  "taste_model": bool(np.any(taste)), "note": "references only: take the system "
                                  "(type, scale, grid, ground, density), never the image, layout or words"})
    rd = d / "refs"
    if rd.exists():
        shutil.rmtree(rd)
    rd.mkdir()
    for k, r in enumerate(refs, 1):
        shutil.copyfile(image_path(pdir, items[r["id"]]), rd / f"{k:02d}-{r['id']}.jpg")
    write_json(d / "refs.json", {"query": query, "items": refs, "text_free": tcut, "text_max": tcut["cutoff"],
                                 "use": "Midjourney --sref / style references: text-free images only (lettering in a "
                                        "reference teaches the generator to letter); still look at them before use"})
    contact_sheet([image_path(pdir, items[r["id"]]) for r in items_out], d / "board.jpg",
                  [f"{k + 1}" + (" liked" if r["liked"] else "") for k, r in enumerate(items_out)])
    sug = tcut.get("suggested_text_max")
    loosen = (f"or loosen it with --text-max {sug:+.4f} and look at every ref first" if sug is not None and
              text_max is None and sug > tcut["cutoff"] else "the cutoff is already at the check's boundary")
    short = "" if len(refs) >= n_refs else (f" Only {len(refs)} of {n_refs} refs passed the text-free check: add more "
                                            f"text-free references to the pool, {loosen}."
                                            + (f" ({tcut['hint']})" if tcut.get("hint") else ""))
    if tcut.get("warning"):
        short += f" {tcut['warning']}"
    rng_txt = (f"; scores here run {tcut['score_range'][0]:+.4f}..{tcut['score_range'][1]:+.4f} on the "
               f"{tcut.get('score', 'text')} scale" if tcut.get("score_range") else "")
    return {"board": str(d / "board.jpg"), "board_json": str(d / "board.json"), "refs_json": str(d / "refs.json"),
            "refs_dir": str(rd), "items": len(items_out), "refs": len(refs), "liked_in_board": sum(r["liked"] for r in items_out),
            "text_free": tcut,
            "text": f"board '{queries[0]}': {len(items_out)} images ({sum(r['liked'] for r in items_out)} of your likes), "
                    f"{len(refs)} text-free refs for --sref in {rd} (text cutoff {tcut['cutoff']:+.4f}: "
                    f"{tcut['method']}; {tcut['clean_share'] * 100:.0f} % of the pool qualifies{rng_txt}). "
                    f"Contact sheet: {d / 'board.jpg'}.{short}"}


def contact_sheet(paths: list[Path], out: Path, labels_: list[str] | None = None, tile: int = 256, cols: int = 6) -> None:
    from PIL import Image, ImageDraw
    rows = max(1, (len(paths) + cols - 1) // cols)
    lab_h = 18
    sheet = Image.new("RGB", (cols * (tile + 6) + 6, rows * (tile + lab_h + 6) + 6), (22, 22, 22))
    dr = ImageDraw.Draw(sheet)
    for k, p in enumerate(paths):
        try:
            im = Image.open(p)
            im.draft("RGB", (tile * 2, tile * 2))
            im = im.convert("RGB")
            im.thumbnail((tile, tile))
        except Exception:  # noqa: BLE001
            continue
        x = 6 + (k % cols) * (tile + 6)
        y = 6 + (k // cols) * (tile + lab_h + 6)
        sheet.paste(im, (x + (tile - im.width) // 2, y + (tile - im.height) // 2))
        if labels_:
            dr.text((x + 2, y + tile + 3), labels_[k][:30], fill=(180, 180, 180))
    sheet.save(out, quality=86)
