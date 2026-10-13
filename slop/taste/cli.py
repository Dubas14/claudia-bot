"""`slop taste …` — taste capture -> tokens. Every command is idempotent, non-interactive and returns a JSON-able
dict with a short human "text" (the router prints it, or the whole dict with --json).

Typical first session (research 11-gap-5 §5.3: ~150 taps ≈ 7 minutes, then a short font A/B):
    slop taste pool add --arena my-channel --mine        # or --dir ~/refs, --urls links.txt (<= 600 Are.na blocks)
    slop taste pool add --starter                        # no references yet: the generated ~300-image starter deck
    slop taste embed                                     # SigLIP 2 base on CPU (~0.35 s/image); or --provider openrouter
    slop taste serve --tunnel                            # prints the https link for the user's phone
    slop taste status                                    # taps, meter, stop rule
    slop taste fit && slop taste meter && slop taste tokens
    slop taste fonts --tunnel                            # font A/B link (real lyric lines on the style frame)
    slop taste fonts rank
    slop taste board "dark technical labels; tiny monospace type"
    slop taste stop
No tunnel (the phone cannot reach the tap app): numbered pair sheets in the chat instead
    slop taste sheet                                     # 12 pairs on 3 images; send them with the printed message
    slop taste record --sheet ID "1a 2b 3a 4b ..."       # the owner's reply, verbatim (the sheet prints the command)
After the owner judges the look (style frames, answers to the questions):
    slop taste tokens                                    # prints each question with the command for each answer
    slop taste verdict texture rejected --note "no grain"            # yes/no rules: confirmed = yes, rejected = no
    slop taste verdict accent confirmed --value "#D97757" --note "the orange"   # slop taste verdict --list: all
    slop taste apply                                     # preview for the owner; then the same with --yes
Profiles: the taste data lives in the user's profile ($SLOP_HOME/taste) and every project links to it by default, so
the second project starts with the first one's taps and meter (`slop taste use` shows / changes it).
Every leaf command accepts --json / --project (-p) after the subcommand too (review round 1).
"""
from __future__ import annotations

import random
import time
from pathlib import Path

from .. import util
from ..config import SlopError, resolve_project
from .threads import small_blas

HELP = ("taste capture -> tokens: reference pool, tap app (or chat pair sheets), model + meter, tokens, verdicts, "
        "apply to the look, mood boards, font A/B; one taste profile per user")


def register(subparsers) -> None:
    tp = subparsers.add_parser("taste", help=HELP, description=HELP)
    util.add_common_flags(tp)
    tp.set_defaults(func=lambda a: {"text": tp.format_help()})
    sub = tp.add_subparsers(dest="taste_cmd", metavar="ACTION")

    s = sub.add_parser("serve", help="start the tap app (background; idempotent); --tunnel for a phone link")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 to reach it on the LAN)")
    s.add_argument("--tunnel", action="store_true", help="also open a Cloudflare quick tunnel (https link)")
    s.add_argument("--new-token", action="store_true", help="restart with a fresh secret URL")
    s.add_argument("--no-embed", action="store_true", help="do not embed missing images in the background")
    s.add_argument("--foreground", action="store_true", help="run in this process (debugging; blocks)")
    s.set_defaults(func=cmd_serve)
    util.add_common_flags(s)

    s = sub.add_parser("stop", help="stop the tap app and its tunnel")
    s.set_defaults(func=cmd_stop)
    util.add_common_flags(s)
    s = sub.add_parser("status", help="server URLs, taps, meter, stop rule, font A/B progress")
    s.set_defaults(func=cmd_status)
    util.add_common_flags(s)

    pp = sub.add_parser("pool", help="the reference pool (add / list)")
    pp.set_defaults(func=lambda a: {"text": pp.format_help()})
    util.add_common_flags(pp)
    ps = pp.add_subparsers(dest="pool_cmd", metavar="ACTION")
    s = ps.add_parser("add", help="add images: --arena SLUG (own/followed channels) | --dir DIR | --urls FILE | --starter")
    s.add_argument("--arena", action="append", default=[], metavar="SLUG",
                   help="Are.na channel slug or URL (repeatable); @me / @following need ARENA_TOKEN")
    s.add_argument("--mine", action="store_true",
                   help="the user confirms the channel is their own or one they follow (needed without ARENA_TOKEN)")
    s.add_argument("--dir", action="append", default=[], help="folder of reference images (repeatable)")
    s.add_argument("--urls", action="append", default=[], help="text file with one image URL per line")
    s.add_argument("--starter", action="store_true",
                   help="the generated starter deck (320 style swatches, ~300 after near-duplicate removal, incl. "
                        "anti-modes; CC0, OFL fonts) for a user with no references yet — real references beat it, "
                        "add them when the user has some")
    s.add_argument("--kind", default="human", choices=["human", "generated"],
                   help="human = references made by people; generated = the user's own kept AI images")
    s.add_argument("--max", type=int, default=None, help="add at most N new images (Are.na is capped at 600 anyway)")
    s.set_defaults(func=cmd_pool_add)
    util.add_common_flags(s)
    s = ps.add_parser("list", help="pool summary (+ the last N images)")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_pool_list)
    util.add_common_flags(s)

    s = sub.add_parser("embed", help="embed pool images that have no vector yet (cached per image)")
    s.add_argument("--provider", default="auto", choices=["auto", "local", "openrouter"])
    s.add_argument("--model", default=None, help="override the model (local: an HF id; openrouter: a model slug)")
    s.add_argument("--patches", type=int, default=576, help="SigLIP NaFlex max patches (576 calibrated; 256 ≈ 2x faster)")
    s.add_argument("--threads", type=int, default=None)
    s.add_argument("--reembed", action="store_true", help="switch models: re-embed every image")
    s.add_argument("--yes", action="store_true", help="confirm a paid embedding run over the confirm threshold")
    s.set_defaults(func=cmd_embed)
    util.add_common_flags(s)

    s = sub.add_parser("fit", help="fit the taste model on all taps -> taste/model.npz + model.json")
    s.set_defaults(func=cmd_fit)
    util.add_common_flags(s)
    s = sub.add_parser("meter", help="held-out accuracy (repeated 5-fold, nested λ), margin, self-agreement, stop rule")
    s.add_argument("--reps", type=int, default=4)
    s.add_argument("--curve", action="store_true", help="also a learning curve over tap subsets")
    s.set_defaults(func=cmd_meter)
    util.add_common_flags(s)
    s = sub.add_parser("tokens", help="write taste/taste-tokens.json + look-bible.md (suggestions + owner questions)")
    s.add_argument("--no-words", action="store_true", help="skip the text-probe vocabulary (no text model load)")
    s.add_argument("--yes", action="store_true", help="confirm paid text embeddings over the confirm threshold")
    s.set_defaults(func=cmd_tokens)
    util.add_common_flags(s)
    s = sub.add_parser("board", help="mood board for a text query x your taste (+ text-free refs for --sref)")
    s.add_argument("query", help='one or more descriptions separated by ";"')
    s.add_argument("--n", type=int, default=24)
    s.add_argument("--refs", type=int, default=12)
    s.add_argument("--text-max", type=float, default=None,
                   help="absolute text-score cutoff for refs (< this). The scale depends on the check in use (the "
                        "per-pool probe: about 0 clean, 1 lettered; a pool under 40 images: the zero-shot score, "
                        "about -0.05..+0.05) — the board prints the score range and a suggested value; values that "
                        "would let lettered images through are refused. Default: calibrated per pool")
    s.add_argument("--yes", action="store_true", help="confirm paid embeddings over the confirm threshold")
    s.set_defaults(func=cmd_board)
    util.add_common_flags(s)

    s = sub.add_parser("fonts", help="font A/B on real lyric lines over the style frame: setup (default) | rank")
    s.add_argument("action", nargs="?", default="setup", choices=["setup", "rank"])
    s.add_argument("--frame", default=None, help="the approved style frame (else look.hero_plate / plates/picks.json)")
    s.add_argument("--families", default=None, help='comma list, e.g. "Space Grotesk,Geist,DINish"')
    s.add_argument("--text", action="append", default=[], help="a lyric line (repeatable; else lyrics/*.txt)")
    s.add_argument("--lines", type=int, default=6, help="how many lyric lines to rotate through")
    s.add_argument("--fonts-dir", default=None, help="extra folder of OFL fonts")
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--reset", action="store_true", help="start a new session (old picks are kept)")
    s.add_argument("--tunnel", action="store_true", help="make sure the server runs with a tunnel")
    s.add_argument("--no-serve", action="store_true", help="only write the session; do not start the server")
    s.set_defaults(func=cmd_fonts)
    util.add_common_flags(s)

    s = sub.add_parser("use", help="where this project's taste lives: your user profile (default) or its own")
    s.add_argument("--profile", choices=["user", "project"], default=None,
                   help="user = share your taste across projects (default); project = this project keeps its own")
    s.add_argument("--fork", action="store_true", help="with --profile project: start from a copy of your user profile")
    s.add_argument("--merge", action="store_true",
                   help="with --profile user: add this project's own taps and images to your user profile")
    s.add_argument("--ignore-local", action="store_true",
                   help="with --profile user: link without this project's own taste data (it stays unused)")
    s.set_defaults(func=cmd_use)
    util.add_common_flags(s)

    s = sub.add_parser("sheet", help="no tunnel? numbered pair sheets (JPG <= 2 MB) to send in the chat")
    s.add_argument("--pairs", type=int, default=12, help="pairs in total (default 12 = one comfortable reply)")
    s.add_argument("--per-sheet", type=int, default=4, help="pairs per image (default 4, readable on a phone)")
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--new", action="store_true",
                   help="make a new sheet even though one is still waiting for its reply (default: show that one again)")
    s.add_argument("--discard", default=None, metavar="SHEET_ID",
                   help="the owner will not answer this sheet: close it (its images can be shown again)")
    s.set_defaults(func=cmd_sheet)
    util.add_common_flags(s)
    s = sub.add_parser("record", help='record the reply to a pair sheet, e.g. slop taste record "1a 2b 3a"')
    s.add_argument("answers", help='the reply as written: "1a 2b 3a ..." (a = left, b = right, t = tie, x = skip)')
    s.add_argument("--sheet", default=None, help="the sheet id printed by `slop taste sheet` (needed when more than "
                                                 "one sheet is waiting for a reply)")
    s.add_argument("--redo", action="store_true", help="replace answers already recorded for these pairs")
    s.add_argument("--no-meter", action="store_true", help="skip the quick held-out meter after recording")
    s.set_defaults(func=cmd_record)
    util.add_common_flags(s)

    s = sub.add_parser("verdict", help="the owner's verdict on a taste rule: RULE confirmed|rejected [--value] [--note]")
    s.add_argument("rule", nargs="?", default=None,
                   help="a rule id from `slop taste verdict --list` (e.g. palette.restraint, palette.accent, texture, "
                        "faces, style_frame, type.lyric, avoid:SOURCE) or a question id from `slop taste tokens` "
                        "(accent, footage_grade, faces, texture, style_frame, type)")
    s.add_argument("status", nargs="?", default=None, choices=["confirmed", "rejected"])
    s.add_argument("--note", default=None, help="the owner's words, verbatim")
    s.add_argument("--value", default=None,
                   help="the owner's value: palette.accent needs it (\"#RRGGBB\" or none); footage grade native | "
                        "clean-grade | print; style_frame the frame's number or file; type.lyric a font family. "
                        "Yes/no rules need none: texture confirmed = add grain, rejected = no grain; faces confirmed = "
                        "show, rejected = hide")
    s.add_argument("--list", action="store_true", help="list the rules that can take a verdict")
    s.set_defaults(func=cmd_verdict)
    util.add_common_flags(s)

    s = sub.add_parser("apply", help="write the owner-confirmed look into project.json (preview; --yes writes)")
    s.add_argument("--accent", default=None, help='the owner accent colour, e.g. "#D97757" (or none)')
    s.add_argument("--mode", default=None, choices=["native", "clean-grade", "print"], help="the footage grade")
    s.add_argument("--lyric-font", default=None, help="lyric font family (OFL, from engine/fonts)")
    s.add_argument("--micro-font", default=None)
    s.add_argument("--display-font", default=None)
    s.add_argument("--texture", default=None, choices=["yes", "no"], help="fine grain in the plates' style tail")
    s.add_argument("--medium", default="photo", choices=["photo", "cel"],
                   help="photo (default) or cel = a stylized/illustrated lead (changes the API tail's medium)")
    s.add_argument("--tail", default=None, help="your own style tail instead of the generated one")
    s.add_argument("--note", default=None, help="the owner's words, logged verbatim in DECISIONS.md")
    s.add_argument("--yes", action="store_true", help="the owner said yes to the preview: write project.json")
    s.set_defaults(func=cmd_apply)
    util.add_common_flags(s)


# ---------------------------------------------------------------- helpers

def _pdir(a) -> Path:
    """the project, with its taste profile link (a new project links to the user profile on first use)"""
    from .profile import ensure_link
    p = resolve_project(getattr(a, "project", None))
    ensure_link(p)
    return p


def _events(pdir):
    from .store import read_events, split_events, taps_path
    ev = read_events(taps_path(pdir))
    return ev, *split_events(ev)


def _space(pdir):
    import numpy as np
    from .embed import load_store
    from .pool import load_pool
    items = load_pool(pdir)
    ids, X, meta = load_store(pdir)
    keep = [k for k, i in enumerate(ids) if i in items]
    ids = [ids[k] for k in keep]
    X = X[keep] if keep else np.zeros((0, max(1, X.shape[1] if X.ndim == 2 else 1)), "float32")
    if len(X):
        X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    return items, ids, X, {i: k for k, i in enumerate(ids)}, meta


# ---------------------------------------------------------------- server

def cmd_serve(a) -> dict:
    from . import server
    pdir = _pdir(a)
    if a.foreground:
        import secrets
        from .store import pin_root, read_json, taste_dir
        pin_root(pdir, taste_dir(pdir))       # like the detached server: a later `slop taste use` never redirects it
        st = read_json(server.state_path(pdir), {}) or {}
        token = st.get("token") if st.get("token") and not a.new_token else secrets.token_urlsafe(18)
        port = a.port or server.free_port(a.host)
        print(f"serving http://127.0.0.1:{port}/{token}/  (Ctrl-C to stop)", flush=True)
        server.run(pdir, a.host, port, token, embed=not a.no_embed)
        return {"text": "stopped"}
    from .embed import load_store
    from .pool import load_pool
    items = load_pool(pdir)
    if not items:
        raise SlopError("the reference pool is empty: add the user's references first, e.g. `slop taste pool add "
                        "--dir FOLDER` or `--arena THEIR-CHANNEL --mine` (see `slop taste pool add --help`)")
    have = set(load_store(pdir)[0])
    missing = sum(1 for i in items if i not in have)
    out = server.serve(pdir, port=a.port, host=a.host, tunnel=a.tunnel, new_token=a.new_token, embed=not a.no_embed)
    if missing and not a.no_embed:
        out["text"] += (f"\nReading {missing} new images in the background (~0.35 s each on CPU); until then the "
                        "first cards come in random order.")
    if len(items) < 150:
        out["text"] += f"\nNote: only {len(items)} images in the pool; 300-400 give a 150-tap session room to explore."
    out.update(pool=len(items), missing_vectors=missing)
    return out


def cmd_stop(a) -> dict:
    from . import server
    return server.stop(_pdir(a))


def cmd_status(a) -> dict:
    from . import fonts, server
    from . import model as M
    from .pool import summary
    from .store import read_jsonl, taste_dir
    pdir = _pdir(a)
    st = server.status(pdir)
    ev, unary, pairs = _events(pdir)
    from .embed import load_store
    ids, _, meta = load_store(pdir)
    likes = sum(1 for u in unary if u[1] == 1)
    taps = len(unary) + sum(1 for e in ev if e.get("winner"))
    hist = read_jsonl(taste_dir(pdir) / "meter.jsonl")
    last = hist[-1] if hist else None
    fs = fonts.FontSession(pdir)
    out = {**st, "pool": summary(pdir, vec_ids=set(ids), tapped={u[0] for u in unary}),
           "taps": taps, "likes": likes, "passes": len(unary) - likes, "pairs": len(pairs),
           "meter": last, **M.self_agreement(ev), "stop": M.stop_rule(hist, taps),
           "embed_model": meta.get("model"), "fonts": fs.progress() if fs.sess else None}
    link = (st.get("urls") or {}).get("public") or (st.get("urls") or {}).get("local")
    m = f"; predicts you {last['accuracy'] * 100:.0f} % ± {last['margin'] * 100:.0f}" if last else ""
    from .profile import describe, info
    out["profile"] = info(pdir)
    out["text"] = (describe(out["profile"]) + "\n"
                   f"server {'running: ' + link if st['running'] else 'not running (slop taste serve --tunnel; no tunnel: slop taste sheet)'}\n"
                   f"pool {out['pool']['images']} images ({out['pool'].get('embedded', 0)} embedded); {taps} taps "
                   f"({likes} likes, {out['passes']} passes, {len(pairs)} pairs){m}\n"
                   f"{'stop: ' if out['stop']['stop'] else 'keep going: '}{out['stop']['why']}"
                   + (f"\nfont A/B: {out['fonts']['answered']}/{out['fonts']['cards']} pairs" if out["fonts"] else "")
                   + (f"\nbackground embedding FAILED: {emb['error']}" if (emb := st.get("embedding") or {}).get("error")
                      else (f"\nreading images: {emb.get('progress') or 'starting'}" if emb.get("running") else "")))
    return out


# ---------------------------------------------------------------- pool / embed

def cmd_pool_add(a) -> dict:
    from .arena import add_arena
    from .pool import PoolWriter, add_dir, add_urls
    pdir = _pdir(a)
    if not (a.arena or a.dir or a.urls or a.starter):
        raise SlopError("give a source: --arena SLUG (the user's own/followed channel), --dir DIR, --urls FILE, or "
                        "--starter (the generated deck, for a user with no references yet)")
    w = PoolWriter(pdir, a.kind)
    rep: dict = {"sources": []}
    if a.starter:
        from .starter import add_starter
        rep["starter"] = add_starter(w, a.max)
    from ..util import input_path, not_found
    for d in a.dir:                                   # relative folders: from the current folder, else the project's
        dp = input_path(pdir, d)
        if dp is None or not dp.is_dir():
            raise SlopError(not_found(pdir, d, "folder") + " (--dir takes a folder of reference images)")
        rep["sources"].append({"dir": d, **add_dir(w, str(dp), a.max)})
    for u in a.urls:
        up = input_path(pdir, u)
        rep["sources"].append({"urls": u, **add_urls(w, str(up) if up is not None and up.is_file() else u, a.max)})
    if a.arena:
        rep["arena"] = add_arena(w, a.arena, confirm_own=a.mine, limit=a.max or 600)
    rep.update(w.stats)
    rep["pool_size"] = len(w)
    rep["text"] = (f"pool: +{w.stats['added']} images ({w.stats['duplicate']} duplicates, {w.stats['near_duplicate']} "
                   f"near-duplicates, {w.stats['skipped']} skipped); {len(w)} in the pool. "
                   + ("Next: slop taste embed" if w.stats["added"] else "")
                   + (f"\nfirst problems: {'; '.join(w.stats['errors'][:3])}" if w.stats["errors"] else ""))
    if a.starter:
        rep["text"] += ("\nstarter deck: generated style swatches (colour restraint, ground, density, type, anti-modes "
                        "like neon / y2k chrome / glossy 3D). It measures the system, not imagery: ask the user for "
                        "their own references (Are.na channel or a folder) as soon as they have some.")
    if len(w) < 150:
        rep["text"] += f"\nnote: {len(w)} images is small — 300-400 candidates give a 150-tap session room to explore"
    return rep


def cmd_pool_list(a) -> dict:
    from .embed import load_store
    from .pool import load_pool, summary
    pdir = _pdir(a)
    ids, _, _ = load_store(pdir)
    _, unary, pairs = _events(pdir)
    s = summary(pdir, vec_ids=set(ids), tapped={u[0] for u in unary} | {x for p in pairs for x in p[:2]})
    items = list(load_pool(pdir).values())[-max(0, a.limit):] if a.limit else []
    s["last"] = [{k: it.get(k) for k in ("id", "src", "kind", "title", "channel", "w", "h")} for it in items]
    s["text"] = (f"{s['images']} images ({', '.join(f'{k} {v}' for k, v in s['by_source'].items()) or 'none'}); "
                 f"{s.get('embedded', 0)} embedded; {s.get('tapped', 0)} tapped")
    return s


def cmd_embed(a) -> dict:
    from .embed import embed_pool
    pdir = _pdir(a)
    r = embed_pool(pdir, provider=a.provider, model=a.model, patches=a.patches, reembed=a.reembed, yes=a.yes,
                   threads=a.threads)
    r["text"] = (f"embedded {r.get('embedded', 0)}/{r['pool']} images with {r['provider']}:{r['model']} "
                 f"({r['computed']} computed, {r['cached']} from cache, {r['failed']} failed"
                 + (f", ${r['real_usd']}" if r.get("real_usd") else "") + ")")
    return r


# ---------------------------------------------------------------- model

def cmd_fit(a) -> dict:
    with small_blas():
        return _fit(a)


def _fit(a) -> dict:
    import numpy as np
    from . import model as M
    from .store import taste_dir, write_json
    pdir = _pdir(a)
    items, ids, X, index, meta = _space(pdir)
    ev, unary, pairs = _events(pdir)
    if not len(X):
        raise SlopError("no taste vectors: run `slop taste embed` first")
    m = M.fit(X, index, unary, pairs)
    if m is None:
        raise SlopError(f"not enough taps to fit ({len(unary)} likes/passes, {len(pairs)} pairs; need >= 5): "
                        "send the user the tap link (slop taste serve --tunnel)")
    mu, V, sd = m["B"]
    np.savez(taste_dir(pdir) / "model.npz", w=m["w"], H=m["H"], mu=mu, V=V, sd=sd, lam=m["lam"], ids=np.array(ids))
    s = M.taste_scores(X, index, unary, pairs)
    order = np.argsort(-s)
    lift = {}
    for why in ("cold", "model", "explore", "seed", "repeat", "fallback"):
        rows = [e for e in ev if e.get("why") == why and e.get("action")]
        if rows:
            lift[why] = {"n": len(rows), "like_rate": round(sum(e["action"] == "like" for e in rows) / len(rows), 3)}
    summ = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_unary": m["n_unary"], "n_pairs": m["n_pairs"],
            "k": m["k"], "lam": m["lam"], "embed_model": meta.get("model"), "kinds": M.KINDS,
            "top": [ids[i] for i in order[:8]], "bottom": [ids[i] for i in order[-8:]], "like_rate_by_why": lift,
            "scores": {ids[i]: round(float(s[i]), 3) for i in range(len(ids))}}
    write_json(taste_dir(pdir) / "model.json", summ)
    out = {k: v for k, v in summ.items() if k != "scores"}
    out["text"] = (f"fit: {m['n_unary']} likes/passes + {m['n_pairs']} pairs, k = {m['k']} dims, λ = {m['lam']}; "
                   f"top: {', '.join(summ['top'][:4])}"
                   + (f"; like-rate model {lift['model']['like_rate']} vs explore {lift['explore']['like_rate']}"
                      if "model" in lift and "explore" in lift else ""))
    return out


def cmd_meter(a) -> dict:
    with small_blas():
        return _meter(a)


def _meter(a) -> dict:
    from . import model as M
    from .store import append_jsonl, now_iso, read_jsonl, taste_dir
    pdir = _pdir(a)
    items, ids, X, index, meta = _space(pdir)
    ev, unary, pairs = _events(pdir)
    if not len(X):
        raise SlopError("no taste vectors: run `slop taste embed` first")
    m = M.meter(X, index, unary, pairs, reps=max(1, a.reps))
    taps = len(unary) + sum(1 for e in ev if e.get("winner"))
    if m is None:
        rows = len(M.rows_of(unary, pairs, index))
        raise SlopError(f"the meter needs >= 20 answered cards with vectors (have {rows}): keep tapping")
    append_jsonl(taste_dir(pdir) / "meter.jsonl", {"t": now_iso(), "source": "cli", **m})
    hist = read_jsonl(taste_dir(pdir) / "meter.jsonl")
    out = {**m, "taps": taps, "predicted": round(M.predicted(m["n"]), 3), **M.self_agreement(ev),
           "stop": M.stop_rule(hist, taps), "chance": 0.5}
    if a.curve:
        rows = M.rows_of(unary, pairs, index)
        rng = random.Random(1)
        curve = []
        for n in [20, 40, 60, 100, 150, 200, 300, len(rows)]:
            if n > len(rows) or (curve and curve[-1]["n"] == n):
                continue
            accs = [M.evaluate(rng.sample(rows, n), M.deployed(X, index), index, reps=1, seed=r)[0] for r in range(3)]
            curve.append({"n": n, "accuracy": round(sum(accs) / len(accs), 4), "predicted": round(M.predicted(n), 3)})
        out["curve"] = curve
    sa = f"; self-agreement {out['self_agreement'] * 100:.0f} % on {out['repeats']} repeats (the ceiling)" if out["self_agreement"] is not None else ""
    out["text"] = (f"held-out: picks the one you prefer {m['accuracy'] * 100:.1f} % ± {m['margin'] * 100:.1f} "
                   f"(n = {m['n']}; 50 % = chance; typical at this n: {out['predicted'] * 100:.0f} %){sa}. "
                   f"{'Stop: ' if out['stop']['stop'] else 'Keep going: '}{out['stop']['why']}")
    return out


def cmd_tokens(a) -> dict:
    from .tokens import build_tokens
    pdir = _pdir(a)
    t = build_tokens(pdir, words=not a.no_words, yes=a.yes)
    pal = t["palette"]
    qlines = []
    for k, x in enumerate(t["open_questions"], 1):
        qlines.append(f"  {k}. {x['ask']} (proposal: {x['proposal']})")
        qlines += [f"       {ans} -> {cmd}" for ans, cmd in (x.get("answers") or {}).items()]
    q = "\n".join(qlines)
    vd = t.get("verdicts") or {}
    extra = ""
    if vd.get("applied"):
        extra += ("\nowner verdicts honoured: "
                  + ", ".join(v["rule"] + " " + (v.get("meaning") or (f"{v['value'] if v['value'] is not None else 'none'} "
                                                                       f"{v['status']}"))
                              for v in vd["applied"][:8]))
    if vd.get("stale"):
        extra += f"\nask again (the taps moved): {'; '.join(v['why'] for v in vd['stale'][:3])}"
    return {"tokens": str(pdir / "taste" / "taste-tokens.json"), "look_bible": str(pdir / "taste" / "look-bible.md"),
            "restraint": pal["restraint"], "accent_candidates": pal["accent_candidates"],
            "modes": [m["name"] for m in t["modes"]], "questions": t["open_questions"],
            "answered": t.get("answered_questions") or [], "verdicts": vd,
            "text": (f"tokens written: {_state_line(t)}.\n"
                     + (f"Ask the owner these questions in ONE message; then record each answer with the command "
                        f"shown under it (their words go in --note):\n{q}" if q else "every question is answered")
                     + extra + "\nthen: slop taste apply   (a preview for the owner; --yes writes project.json)")}


def _state_line(t: dict) -> str:
    """the tokens' current state in one line, from the verdicts (never a fixed sentence: a weaker model would ask
    the owner again about something already answered)"""
    pal, tex = t["palette"], t.get("texture") or {}
    if pal.get("accent_source") == "owner verdict":
        acc = f"accent {pal.get('accent') or 'none'} (owner verdict)"
    else:
        hexes = {h["hue"]: h.get("observed_hex") for h in pal.get("hues") or []}
        c = ", ".join(x + (f" {hexes[x]}" if hexes.get(x) else "") for x in pal.get("accent_candidates") or [])
        acc = f"accent = ask the owner (candidates: {c or 'none'})"
    if pal.get("footage_grade_status") == "confirmed":
        grade = f"footage grade {pal.get('footage_grade')} (owner verdict)"
    elif pal.get("footage_grade_status") == "rejected":
        grade = f"footage grade: the owner rejected {', '.join(map(str, pal.get('footage_grade_rejected') or []))} — ask which"
    else:
        grade = "footage grade = native unless the owner says otherwise"
    bits = [f"colour restraint {pal['restraint']} ({pal['status']})", acc, grade]
    if tex.get("apply") is not None:
        bits.append(f"texture: {'grain' if tex['apply'] else 'no grain'} (owner verdict)")
    if (t.get("faces") or {}).get("show") is not None:
        bits.append(f"faces: {'show' if t['faces']['show'] else 'hide'} (owner verdict)")
    if (t.get("type") or {}).get("status") == "confirmed":
        bits.append(f"lyric font {t['type'].get('lyric')} (owner verdict)")
    return ", ".join(bits)


def cmd_board(a) -> dict:
    from .tokens import board
    return board(_pdir(a), a.query, n=a.n, n_refs=a.refs, text_max=a.text_max, yes=a.yes)


def cmd_fonts(a) -> dict:
    from . import fonts, server
    pdir = _pdir(a)
    if a.action == "rank":
        return fonts.rank(pdir)
    fams = [f.strip() for f in a.families.split(",") if f.strip()] if a.families else None
    r = fonts.setup(pdir, frame=a.frame, families=fams, texts=a.text or None, n_lines=a.lines, seed=a.seed,
                    extra_dir=a.fonts_dir, reset=a.reset)
    sess = r["session"]
    out = {"session": sess["id"], "created": r["created"], "fonts": [f["family"] for f in sess["fonts"]],
           "lines": sess["lines"], "cards": len(sess["cards"]), "frame_source": sess["frame_source"],
           "provisional_frame": sess.get("provisional", False)}
    tunnel_note = ""
    if not a.no_serve:
        srv = server.serve(pdir, tunnel=a.tunnel)
        u = srv["urls"]
        out["url"] = u.get("fonts_public") or u["fonts_local"]
        if srv.get("tunnel_error"):
            out["tunnel_error"] = srv["tunnel_error"]
            tunnel_note = (f"\nNO PUBLIC LINK: the tunnel failed ({srv['tunnel_error']}); the link above works on this "
                           "machine only — fix the tunnel (bin/setup.sh) and re-run with --tunnel")
    prog = fonts.FontSession(pdir).progress()
    out["progress"] = prog
    if sess.get("weights_note"):
        out["weights_note"] = sess["weights_note"]
    warn = ("\nwarning: no approved style frame found — using a neutral ground; pass --frame or set "
            "look.hero_plate so the A/B is judged on the real look") if sess.get("provisional") else ""
    out["text"] = (f"font A/B {'ready' if r['created'] else 'session already exists (--reset for a new one)'}: "
                   f"{len(sess['fonts'])} fonts ({', '.join(out['fonts'])}), {len(sess['cards']) // 2} pairs, each "
                   f"shown in both orders ({len(sess['cards'])} cards, ~{len(sess['cards']) * 4.2 / 60:.0f} min), "
                   f"{prog['answered']} answered."
                   + (f"\nlink: {out['url']}" if out.get("url") else "") + tunnel_note + warn
                   + "\nWhen the user is done: slop taste fonts rank")
    return out


# ---------------------------------------------------------------- profiles, sheets, verdicts, apply

def cmd_use(a) -> dict:
    from .profile import use
    p = resolve_project(getattr(a, "project", None))
    return use(p, a.profile, fork=a.fork, merge=a.merge, ignore_local=a.ignore_local)


def cmd_sheet(a) -> dict:
    pdir = _pdir(a)
    with small_blas():
        from .sheet import discard, make_sheets
        if a.discard:
            return discard(pdir, a.discard)
        return make_sheets(pdir, pairs=a.pairs, per_sheet=a.per_sheet, seed=a.seed, new=a.new)


def cmd_record(a) -> dict:
    pdir = _pdir(a)
    with small_blas():
        from .sheet import record
        return record(pdir, a.answers, sheet=a.sheet, redo=a.redo, meter=not a.no_meter)


def cmd_verdict(a) -> dict:
    from . import verdicts as VD
    pdir = _pdir(a)
    if a.list or not a.rule:
        return VD.list_rules(pdir)
    if not a.status:
        raise SlopError(f"say confirmed or rejected: slop taste verdict {a.rule} confirmed --note \"the owner's words\"")
    return VD.record(pdir, a.rule, a.status, note=a.note, value=a.value)


def cmd_apply(a) -> dict:
    from .apply import apply
    return apply(_pdir(a), yes=a.yes, note=a.note, accent=a.accent, mode=a.mode, lyric=a.lyric_font,
                 micro=a.micro_font, display=a.display_font, texture=a.texture, medium=a.medium, tail=a.tail)
