"""Taste profiles: the user's taste follows them from song to song (``slop taste use``).

Retention: a user's taps, model, meter and font picks live in ONE user profile (``$SLOP_HOME/taste``). Every new
project links to it by default, so the second song starts with the first song's taste and meter instead of an empty
tap app. A project can keep its own taste instead:

    slop taste use                          # show where this project's taste lives
    slop taste use --profile user           # share the user profile (the default for a new project)
    slop taste use --profile project        # this project keeps its own taste data (starts empty)
    slop taste use --profile project --fork # ... starting from a copy of the user profile (to try a new direction)
    slop taste use --profile user --merge   # an older project with its own taps: add them to the user profile

What is shared (in the profile root): pool + images, vectors, taps, model, meter, image statistics, font A/B
sessions/picks/ranking, pair sheets. What stays in each project (``<project>/taste``): the link, taste-tokens.json,
look-bible.md, boards/, verdicts.jsonl (this project's verdicts; rule verdicts are also copied to the user profile so
they carry over), applied.json.

Copies: image files are hard-linked when the file system allows it (they are never modified), every log is copied
(they are appended to). Merges are by id: pool rows by image id/sha1, taps and font picks by event id, verdicts by
verdict id; vectors only when both sides use the same embedding model (else `slop taste embed` re-embeds, cheaply from
the per-image cache).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..config import SlopError
from .store import (PROFILE_KINDS, has_data, link_path, now_iso, profile_root, project_taste_dir, read_json,
                    read_jsonl, read_link, user_profile_dir, write_json)

PROFILE_MARKER = "PROFILE.json"
COPY_FILES = ("meter.jsonl", "model.npz", "model.json")       # copied only into an EMPTY root (else: refit)
SKIP_ON_COPY = ("server.json", "server.log", "tunnel.log", "sheets", PROFILE_MARKER)


def project_name(pdir: Path) -> str:
    try:
        from ..config import load_project
        return str(load_project(Path(pdir)).get("name") or Path(pdir).name)
    except (OSError, ValueError):
        return Path(pdir).name


def _register(root: Path, pdir: Path) -> None:
    """remember which projects share the user profile (shown by `slop taste use` / status)"""
    root.mkdir(parents=True, exist_ok=True)
    mp = root / PROFILE_MARKER
    m = read_json(mp, {}) or {}
    m.setdefault("kind", "user")
    m.setdefault("created", now_iso())
    projects = m.setdefault("projects", {})
    name = project_name(pdir)
    if name not in projects or projects[name].get("path") != str(Path(pdir)):
        projects[name] = {"path": str(Path(pdir)), "linked": now_iso()}
        write_json(mp, m)


def _write_link(pdir: Path, profile: str, by: str, **extra) -> dict:
    link = {"profile": profile, "since": now_iso(), "by": by, **extra}
    project_taste_dir(pdir)
    write_json(link_path(pdir), link)
    if profile == "user":
        _register(user_profile_dir(), pdir)
    return link


def ensure_link(pdir: Path) -> dict:
    """the CLI's default: link a project to the user profile on first use, unless it already holds its own data"""
    link = read_link(pdir)
    if link:
        return link
    local = Path(pdir) / "taste"
    if has_data(local):
        return _write_link(pdir, "project", "default",
                           note="this project already had its own taste data; share it with "
                                "`slop taste use --profile user --merge`")
    return _write_link(pdir, "user", "default")


def counts(root: Path) -> dict:
    """pool images, taps (likes/passes/pairs), font picks, last meter of a profile root (no model load)"""
    from .store import live_events
    root = Path(root)
    pool: dict[str, dict] = {}
    for r in read_jsonl(root / "pool" / "pool.jsonl"):
        if r.get("id"):
            if r.get("removed"):
                pool.pop(r["id"], None)
            else:
                pool[r["id"]] = r
    ev = live_events(read_jsonl(root / "taps.jsonl"))
    unary = sum(1 for e in ev if e.get("action") in ("like", "pass"))
    pairs = sum(1 for e in ev if e.get("winner"))
    fonts = sum(1 for e in live_events(read_jsonl(root / "fonts" / "taps.jsonl")) if e.get("winner"))
    hist = [r for r in read_jsonl(root / "meter.jsonl") if r.get("accuracy") is not None]
    last = hist[-1] if hist else None
    return {"images": len(pool), "taps": unary + pairs, "likes_passes": unary, "pairs": pairs, "font_picks": fonts,
            "meter": None if not last else {"accuracy": last.get("accuracy"), "margin": last.get("margin"),
                                            "n": last.get("n"), "t": last.get("t")}}


def info(pdir: Path) -> dict:
    link = read_link(pdir)
    root = profile_root(pdir)
    kind = (link or {}).get("profile") or "project"
    out = {"profile": kind, "root": str(root), "linked": bool(link), **counts(root)}
    if kind == "user":
        m = read_json(root / PROFILE_MARKER, {}) or {}
        names = sorted(m.get("projects") or {})
        out["projects"] = names
        out["other_projects"] = [n for n in names if n != project_name(pdir)]
    local = Path(pdir) / "taste"
    if kind == "user" and has_data(local):
        out["unused_local"] = counts(local)
    return out


def status_stage(pdir: Path) -> dict:
    """for `slop status` (core): the taste stage of a project WITHOUT creating anything or loading numpy ->
    {done, detail, next, profile, taps, meter}. A new project that will link to a trained user profile is not sent
    back to tapping: it is told to write its tokens from the shared profile."""
    pdir = Path(pdir)
    tokens = (pdir / "taste" / "taste-tokens.json").is_file()
    link = read_link(pdir)
    local = pdir / "taste"
    if link is None:                       # what ensure_link will choose on the first taste command
        kind = "project" if has_data(local) else "user"
        root = local if kind == "project" else user_profile_dir()
    else:
        kind, root = link.get("profile"), profile_root(pdir, link)
    c = counts(root) if root.exists() else {"taps": 0, "images": 0, "meter": None}
    m = c.get("meter")
    where = "shared taste profile" if kind == "user" else "this project's taste"
    have = f"{where}: {c['taps']} taps" + (f", meter {m['accuracy'] * 100:.0f} %" if m and m.get("accuracy") else "")
    if tokens:
        return {"done": True, "detail": "taste/taste-tokens.json present; " + have, "next": None, "profile": kind,
                "taps": c["taps"], "meter": m}
    if c["taps"]:
        return {"done": False, "detail": have + " — no taste-tokens.json for this project yet",
                "next": "slop taste tokens", "profile": kind, "taps": c["taps"], "meter": m}
    return {"done": False, "detail": "no taste profile yet (optional; recommended for Studio/Director)",
            "next": "slop taste serve --tunnel   (no tunnel: slop taste sheet)", "profile": kind, "taps": 0,
            "meter": None}


def describe(i: dict) -> str:
    m = i.get("meter")
    meter = f"; the model predicts you {m['accuracy'] * 100:.0f} % ± {(m.get('margin') or 0) * 100:.0f}" if m else ""
    where = ("your user profile" if i["profile"] == "user" else "this project's own folder") + f" ({i['root']})"
    shared = ""
    if i["profile"] == "user" and i.get("other_projects"):
        shared = f"; shared with {', '.join(i['other_projects'][:5])}"
    return (f"taste profile: {where}: {i['images']} images, {i['taps']} taps ({i['pairs']} pairs), "
            f"{i['font_picks']} font picks{meter}{shared}")


# ---------------------------------------------------------------- copy / merge between roots

def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)                  # images are never modified in place: a hard link is a safe copy
    except OSError:
        shutil.copy2(src, dst)


def _append_rows(path: Path, rows: list[dict]) -> None:
    import json
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _merge_events(src: Path, dst: Path) -> int:
    """append src event rows whose eid (or undo target) dst does not have yet -> rows added"""
    have = read_jsonl(dst)
    eids = {r.get("eid") for r in have if r.get("eid")}
    undos = {r.get("undo") for r in have if "undo" in r}
    new = []
    for r in read_jsonl(src):
        if "undo" in r:
            if r["undo"] not in undos:
                new.append(r)
                undos.add(r["undo"])
        elif r.get("eid") and r["eid"] not in eids:
            new.append(r)
            eids.add(r["eid"])
    _append_rows(dst, new)
    return sum(1 for r in new if "undo" not in r)


def _merge_pool(src: Path, dst: Path) -> int:
    def live(rows):
        out: dict[str, dict] = {}
        for r in rows:
            if r.get("id"):
                if r.get("removed"):
                    out.pop(r["id"], None)
                else:
                    out[r["id"]] = r
        return out
    sp, dp = live(read_jsonl(src / "pool" / "pool.jsonl")), live(read_jsonl(dst / "pool" / "pool.jsonl"))
    shas = {r.get("sha1") for r in dp.values() if r.get("sha1")}
    new = []
    for iid, r in sp.items():
        if iid in dp or (r.get("sha1") and r["sha1"] in shas):
            continue
        img = src / "pool" / "images" / f"{iid}.jpg"
        if img.is_file():
            _link_or_copy(img, dst / "pool" / "images" / f"{iid}.jpg")
        new.append(r)
    _append_rows(dst / "pool" / "pool.jsonl", new)
    return len(new)


def _merge_vectors(src: Path, dst: Path) -> str:
    import numpy as np
    sv, dv = src / "emb" / "vectors.npz", dst / "emb" / "vectors.npz"
    sm, dm = read_json(src / "emb" / "meta.json", {}) or {}, read_json(dst / "emb" / "meta.json", {}) or {}
    if not sv.is_file():
        return "none to copy"
    if not dv.is_file() or not dm.get("tag"):
        (dst / "emb").mkdir(parents=True, exist_ok=True)
        shutil.copy2(sv, dv)
        write_json(dst / "emb" / "meta.json", sm)
        return "copied"
    if sm.get("tag") != dm.get("tag"):
        return (f"not merged: the two profiles use different embedding models ({sm.get('tag')} vs {dm.get('tag')}); "
                "run `slop taste embed` to embed the added images")
    a, b = np.load(dv, allow_pickle=False), np.load(sv, allow_pickle=False)
    ids_d = [str(x) for x in a["ids"].tolist()]
    ids_s = [str(x) for x in b["ids"].tolist()]
    keep = [k for k, i in enumerate(ids_s) if i not in set(ids_d)]
    if not keep:
        return "merged (nothing new)"
    ids = ids_d + [ids_s[k] for k in keep]
    vecs = np.concatenate([a["vecs"], b["vecs"][keep]]).astype("float16")
    tmp = dv.with_name(f"vectors.tmp{os.getpid()}.npz")
    np.savez(tmp, ids=np.array(ids), vecs=vecs)
    os.replace(tmp, dv)
    return f"merged (+{len(keep)})"


def copy_into(src: Path, dst: Path) -> dict:
    """add src's taste data to dst (dst may be empty): pool + images, vectors, taps, font picks/sessions, image stats;
    meter/model only into an empty dst. Never deletes anything in src or dst."""
    src, dst = Path(src), Path(dst)
    empty = not has_data(dst)
    dst.mkdir(parents=True, exist_ok=True)
    rep = {"images": _merge_pool(src, dst), "vectors": _merge_vectors(src, dst),
           "taps": _merge_events(src / "taps.jsonl", dst / "taps.jsonl"),
           "font_picks": _merge_events(src / "fonts" / "taps.jsonl", dst / "fonts" / "taps.jsonl")}
    for f in ("session.json", "frame.jpg", "ranking.json"):
        s, d = src / "fonts" / f, dst / "fonts" / f
        if s.is_file() and not d.exists():
            shutil.copy2(s, d)
    st_s, st_d = read_json(src / "stats.json", {}) or {}, read_json(dst / "stats.json", {}) or {}
    if st_s:
        write_json(dst / "stats.json", {**st_s, **st_d})
    if empty:
        for f in COPY_FILES:
            if (src / f).is_file():
                shutil.copy2(src / f, dst / f)
    rep["meter_copied"] = empty
    return rep


def _verdict_rows(path: Path) -> list[dict]:
    return [r for r in read_jsonl(path) if r.get("level") == "rule" and r.get("vid")]


def _copy_verdicts(src_file: Path, dst_file: Path) -> int:
    have = {r.get("vid") for r in read_jsonl(dst_file)}
    new = [r for r in _verdict_rows(src_file) if r["vid"] not in have]
    _append_rows(dst_file, new)
    return len(new)


# ---------------------------------------------------------------- slop taste use

def _stop_server(root: Path) -> str | None:
    from . import tunnel as T
    st = read_json(root / "server.json", {}) or {}
    killed = []
    if st.get("pid") and T.stop_pid(st["pid"]):
        killed.append("tap app")
    if (st.get("tunnel") or {}).get("pid") and T.stop_pid(st["tunnel"]["pid"]):
        killed.append("tunnel")
    if st and killed:
        st.update(pid=None, tunnel={}, stopped=now_iso())
        write_json(root / "server.json", st)
    return " and ".join(killed) or None


def use(pdir: Path, profile: str | None = None, fork: bool = False, merge: bool = False,
        ignore_local: bool = False) -> dict:
    pdir = Path(pdir)
    if profile is None:
        if fork or merge or ignore_local:
            raise SlopError("--fork / --merge / --ignore-local need --profile: e.g. `slop taste use --profile "
                            "project --fork` or `slop taste use --profile user --merge`")
        ensure_link(pdir)
        i = info(pdir)
        return {**i, "changed": False,
                "text": describe(i) + ("\nthis project keeps its own taste; share your user profile instead: "
                                       "slop taste use --profile user --merge" if i["profile"] == "project" else
                                       "\nto give this project its own taste: slop taste use --profile project "
                                       "[--fork]")}
    if profile not in PROFILE_KINDS:
        raise SlopError(f"--profile must be user or project (got {profile!r})")
    cur = ensure_link(pdir)              # the current (default) link: user, or project when it holds its own data
    old_root = profile_root(pdir)
    local = Path(pdir) / "taste"
    user = user_profile_dir()
    notes: list[str] = []
    rep: dict = {}
    if profile == "user":
        if fork:
            raise SlopError("--fork copies your user profile INTO this project: use it with --profile project "
                            "(`slop taste use --profile project --fork`)")
        local_counts = counts(local) if has_data(local) else None
        uses_local = cur is None or cur.get("profile") == "project"
        if local_counts and (uses_local or merge):
            if not has_data(user):
                rep = copy_into(local, user)
                notes.append(f"moved this project's taste into your user profile: {local_counts['images']} images, "
                             f"{local_counts['taps']} taps (the originals stay in {local}, unused)")
            elif merge:
                rep = copy_into(local, user)
                notes.append(f"merged this project's taste into your user profile: +{rep['images']} images, "
                             f"+{rep['taps']} taps, +{rep['font_picks']} font picks (vectors: {rep['vectors']}). "
                             "Refit: slop taste fit && slop taste meter")
            elif not ignore_local:
                u = counts(user)
                raise SlopError(
                    f"this project has its own taste data ({local_counts['images']} images, {local_counts['taps']} "
                    f"taps) and your user profile has some too ({u['images']} images, {u['taps']} taps). Choose one: "
                    "`slop taste use --profile user --merge` adds this project's taps and images to your profile; "
                    "`slop taste use --profile user --ignore-local` links without them (they stay unused in "
                    "taste/)")
            else:
                notes.append(f"this project's own taste data ({local_counts['taps']} taps) stays in {local}, unused")
            rep["verdicts"] = _copy_verdicts(local / "verdicts.jsonl", user / "verdicts.jsonl")
        elif merge and not local_counts:
            notes.append("nothing to merge: this project has no taste data of its own")
        link = _write_link(pdir, "user", "slop taste use")
    else:
        if merge or ignore_local:
            raise SlopError("--merge / --ignore-local are for --profile user; to start this project from a copy of "
                            "your user profile use `slop taste use --profile project --fork`")
        if fork:
            src = old_root if (cur or {}).get("profile") == "user" else user
            if src.resolve() == local.resolve():
                raise SlopError("this project already keeps its own taste: there is nothing to fork from")
            if has_data(local):
                c = counts(local)
                raise SlopError(f"this project's taste/ folder already holds taste data ({c['images']} images, "
                                f"{c['taps']} taps); --fork would mix two profiles. Use `slop taste use --profile "
                                "project` to keep using that data, or move taste/pool, taste/taps.jsonl and "
                                "taste/emb away first")
            if not has_data(src):
                raise SlopError("your user profile is empty: there is nothing to fork. Use `slop taste use --profile "
                                "project` for an empty project taste")
            rep = copy_into(src, local)
            rep["verdicts"] = _copy_verdicts(src / "verdicts.jsonl", local / "verdicts.jsonl")
            notes.append(f"forked: copied {rep['images']} images and {rep['taps']} taps from your user profile; from "
                         "now on this project's taps stay here (your user profile is not changed)")
        elif has_data(local):
            notes.append("this project's own taste data is used again")
        else:
            notes.append("this project starts with an empty taste: add references (slop taste pool add ...) and tap")
        link = _write_link(pdir, "project", "slop taste use", **({"forked_from": str(old_root)} if fork else {}))
    new_root = profile_root(pdir)
    changed = old_root.resolve() != new_root.resolve()
    if changed and old_root.resolve() == local.resolve():
        stopped = _stop_server(old_root)       # a project-local tap app would be unreachable after the switch
        if stopped:
            notes.append(f"stopped this project's own {stopped}; start the shared one with: slop taste serve --tunnel")
    elif changed:
        st = read_json(old_root / "server.json", {}) or {}
        if st.get("pid"):
            notes.append("the user profile's tap app keeps running for your other projects")
    i = info(pdir)
    return {**i, "changed": changed, "link": link, "copied": rep or None,
            "text": "\n".join([describe(i)] + notes + (["next: slop taste status"] if changed else []))}
