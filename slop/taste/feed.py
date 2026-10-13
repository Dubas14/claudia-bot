"""Card selection for the tap app — the retired feed/server.py `State` (cards / human_pair / reposts / meter),
re-pointed at a project's own pool and extended with the onboarding policy of research 11-gap-5 §5.3.

Per card batch (the client asks for ~6 singles when its queue runs low; one pair is added -> ~1 card in 7):
  * repeats: from tap 60, one card answered >= 60 taps earlier every 15 taps until 6 are done (then 4 %);
  * cold start: the first 40 single cards walk a k-means-stratified order of the pool (every mode gets seen);
  * after that: 15 % uniform explore, a fading seed share if the pool has `reference` items, else the model's
    pick from ONE Thompson draw of the posterior, ensembled with the kNN modes term (z + z);
  * pairs: two unseen items the model scores alike (its top third) that look different (cosine < 0.85, not the same
    project); sides are shuffled by the client, which logs "shown" (ab/ba) and "layout" (row/stack);
  * never re-serve: seen items, re-posts of anything seen (cosine > 0.93), same-project items of the last 300 taps.
Images without vectors yet (embedding still running) are served only as cold/explore cards.

Fixer changes (review round 1):
  * snapshot consistency: reload() builds an immutable `Space` (pool + vectors + index + keys + cold order) and swaps
    it in one step; a fitted model keeps the Space it was fitted on, and cards() / human_pair() look scores up
    through it by image id. Images that arrived after the last fit (background-embedding flushes, `pool add` while
    serving) are served unscored (explore / fallback) until the next refit, instead of indexing the old arrays
    (that raised IndexError and dropped /api/next). Refits are serialised.
  * a random card standing in for a blocked model / seed pick is labelled "fallback" (not "explore", so
    like_rate_by_why stays honest) and obeys the same-project rule; only when nothing else at all can be served is
    one same-project card allowed (never a re-post); an exhausted pool asks for one repeat at a time.
  * `composed` items (the generated starter deck, starter.py) are served like human/generated ones and get their
    own intercept in the model (model.KINDS already has it).
Review round 2: a Feed resolves its taste profile root ONCE (`self.root`) and reads / writes every file there (pool,
vectors, taps, meter). Looking the root up at write time let a background meter thread write into another root after
the project was relinked (`slop taste use`) or after a test restored SLOP_HOME; `wait_idle()` lets callers (tests)
wait for that thread.
"""
from __future__ import annotations

import random
import threading
import time
from pathlib import Path

import numpy as np

from . import model as M
from .embed import load_store, store_paths
from .pool import load_pool
from .store import append_jsonl, new_eid, now_iso, read_events, read_jsonl, split_events, taste_dir

SERVE_KINDS = ("human", "generated", "composed")
WHY = {"cold", "model", "explore", "seed", "repeat", "fallback"}


class Space:
    """an immutable snapshot of the servable pool and its vectors (one reload); row numbers are only meaningful
    together with the Space they came from"""

    def __init__(self, gen: int, pool: dict, ids: list[str], X: np.ndarray, seed: int):
        self.gen = gen
        self.pool = pool
        self.ids = ids
        self.X = X
        self.index = {i: n for n, i in enumerate(ids)}
        self.keys = [pool[i].get("keys") or [] for i in ids]
        ref = np.array([pool[i].get("kind") == "reference" for i in ids], dtype=bool)
        self.seedvec = None
        if ref.any():
            m = X[ref].mean(0)
            self.seedvec = m / (np.linalg.norm(m) + 1e-12)
        self.serve_ids = [i for i, it in pool.items() if it.get("kind", "human") in SERVE_KINDS]
        order = M.cold_start_order(X, M.COLD_START, seed) if len(X) else []
        cold = [ids[n] for n in order if pool[ids[n]].get("kind", "human") in SERVE_KINDS]
        if len(cold) < M.COLD_START:   # not embedded yet: fill the cold start with a shuffled remainder
            have = set(cold)
            rest = [i for i in self.serve_ids if i not in have]
            random.Random(seed).shuffle(rest)
            cold += rest[: M.COLD_START - len(cold)]
        self.cold = cold

    def same_project(self, i: int, j: int, cos: float | None = None) -> bool:
        c = float(self.X[i] @ self.X[j]) if cos is None else cos
        if c > M.DUP_COS:
            return True
        for k in set(self.keys[i]) & set(self.keys[j]):
            if k.startswith(("behance:", "ig:")):
                return True
            if k.startswith("page:") and c >= 0.6:
                return True
            if k.startswith("batch:") and c >= 0.7:
                return True
        return False

    def reposts(self, unary, pairs) -> set[str]:
        """ids that re-post something already answered (cosine > 0.93, or the same project by key)"""
        idx = self.index
        seen = sorted({idx[i] for i, _, _ in unary if i in idx} | {idx[x] for a, b, _ in pairs for x in (a, b) if x in idx})
        if not seen or not len(self.ids):
            return set()
        mask = (self.X @ self.X[seen].T).max(1) > M.DUP_COS
        by_key: dict[str, list[int]] = {}
        for j in seen:
            for k in self.keys[j]:
                by_key.setdefault(k, []).append(j)
        for i, ks in enumerate(self.keys):
            if mask[i] or not ks:
                continue
            if any(self.same_project(i, j) for k in ks for j in by_key.get(k, ())):
                mask[i] = True
        mask[seen] = False
        return {self.ids[i] for i in np.flatnonzero(mask)}


class Feed:
    def __init__(self, pdir: Path, seed: int | None = None, background: bool = False):
        self.pdir = Path(pdir)
        self.root = taste_dir(self.pdir)     # fixed for this Feed's lifetime (see the module docstring)
        self.taps_file = self.root / "taps.jsonl"
        self.meter_file = self.root / "meter.jsonl"
        self.lock = threading.RLock()
        self.fit_lock = threading.Lock()     # refits run one at a time (loop, background embedding, tests)
        self.rng = random.Random(seed)
        self.nrng = np.random.default_rng(seed)
        self.seed = 0 if seed is None else seed
        self.dirty = threading.Event()
        self.model: dict | None = None
        self.meter: dict | None = None
        self.meter_rows = -1
        self.measuring = False
        self.vec_stamp = None
        self.pool_stamp = None
        self.auto_embed = False      # the server sets this: newly added pool images get embedded in the background
        self.embedding = {"running": False}
        self._gen = 0
        self.space: Space | None = None
        self.reload()
        self.refit()
        if background:
            threading.Thread(target=self.loop, daemon=True).start()

    # read-only views of the current snapshot (the server and the tests read these)
    pool = property(lambda self: self.space.pool)
    ids = property(lambda self: self.space.ids)
    X = property(lambda self: self.space.X)
    index = property(lambda self: self.space.index)
    keys = property(lambda self: self.space.keys)
    seedvec = property(lambda self: self.space.seedvec)
    serve_ids = property(lambda self: self.space.serve_ids)
    cold = property(lambda self: self.space.cold)

    # ---------------------------------------------------------------- data
    def _pool_file(self) -> Path:
        return self.root / "pool" / "pool.jsonl"

    def reload(self) -> None:
        vp, _ = store_paths(self.pdir, self.root)
        pp = self._pool_file()
        vstamp = vp.stat().st_mtime_ns if vp.exists() else None    # stat BEFORE reading: a write in between is
        pstamp = pp.stat().st_mtime_ns if pp.exists() else None    # picked up by the next loop, never missed
        pool = load_pool(self.pdir, root=self.root)
        ids_v, X, meta = load_store(self.pdir, root=self.root)
        keep = [n for n, i in enumerate(ids_v) if i in pool and pool[i].get("kind", "human") in SERVE_KINDS + ("reference",)]
        ids = [ids_v[n] for n in keep]
        Xk = X[keep].astype("float32") if len(keep) else np.zeros((0, max(1, X.shape[1] if X.ndim == 2 else 1)), "float32")
        if len(Xk):
            Xk = Xk / (np.linalg.norm(Xk, axis=1, keepdims=True) + 1e-12)
        with self.lock:
            self._gen += 1
            gen = self._gen
        sp = Space(gen, pool, ids, Xk, self.seed)
        with self.lock:
            if self.space is None or self.space.gen < gen:   # two concurrent reloads: the newest read wins
                self.space = sp
                self.vec_stamp, self.pool_stamp = vstamp, pstamp

    def events(self) -> list[dict]:
        return read_events(self.taps_file)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """wait until no background meter is running (tests call this before their temporary folders go away)"""
        return wait_for(lambda: not self.measuring, timeout=timeout)

    def refit(self) -> None:
        with self.fit_lock:
            with self.lock:
                sp = self.space
            unary, pairs = split_events(self.events())
            m = M.fit(sp.X, sp.index, unary, pairs, seed=self.seed) if len(sp.X) else None
            if m is not None:
                m["dup"] = sp.reposts(unary, pairs)
                m["space"] = sp                       # the snapshot its arrays (Z, knn) are indexed by
            with self.lock:
                self.model = m
        rows = len(M.rows_of(unary, pairs, sp.index))
        if rows >= 20 and (self.meter is None or rows - self.meter_rows >= 10) and not self.measuring:
            self.meter_rows = rows
            self.measuring = True
            threading.Thread(target=self.measure, args=(sp.X, sp.index, unary, pairs), daemon=True).start()

    def measure(self, X, index, unary, pairs) -> None:
        try:
            m = M.meter(X, index, unary, pairs, reps=2)
            if m:
                with self.lock:
                    self.meter = m
                append_jsonl(self.meter_file, {"t": now_iso(), "source": "app", **m})
        finally:
            self.measuring = False

    def loop(self) -> None:
        while True:
            if self.dirty.wait(timeout=15):
                self.dirty.clear()
                try:
                    self.refit()
                except Exception as e:  # noqa: BLE001 — keep serving on a bad refit
                    print("refit failed:", e, flush=True)
            try:
                vp, _ = store_paths(self.pdir, self.root)
                pp = self._pool_file()
                stamp = vp.stat().st_mtime_ns if vp.exists() else None
                pstamp = pp.stat().st_mtime_ns if pp.exists() else None
                if stamp != self.vec_stamp or pstamp != self.pool_stamp:
                    grew = pstamp != self.pool_stamp
                    self.reload()
                    self.refit()
                    if grew and self.auto_embed:   # `slop taste pool add` while the app runs
                        self.start_embedding()
            except Exception as e:  # noqa: BLE001
                print("reload failed:", e, flush=True)

    def start_embedding(self, provider: str = "auto") -> None:
        """embed images that still lack vectors in a background thread (the app serves meanwhile)"""
        if self.embedding.get("running"):
            return
        sp = self.space
        missing = [i for i in sp.pool if i not in sp.index]
        if not missing:
            return

        self.embedding = {"running": True, "todo": len(missing), "started": now_iso()}

        def run():
            from .embed import embed_pool
            try:
                r = embed_pool(self.pdir, provider=provider, log=lambda m: self.embedding.update(progress=m))
                self.embedding = {"running": False, "done": r.get("computed", 0) + r.get("cached", 0)}
            except Exception as e:  # noqa: BLE001
                self.embedding = {"running": False, "error": str(e)[:300]}
                print("background embedding failed:", e, flush=True)   # -> taste/server.log
            self.reload()
            self.refit()
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------------------- re-posts / same project (current snapshot)
    def same_project(self, i: int, j: int, cos: float | None = None) -> bool:
        return self.space.same_project(i, j, cos)

    def reposts(self, unary, pairs) -> set[str]:
        return self.space.reposts(unary, pairs)

    # ---------------------------------------------------------------- selection
    def _seen(self, ev, exclude) -> set[str]:
        s = {e["item"] for e in ev if "item" in e} | {x for e in ev if "a" in e for x in (e["a"], e["b"])}
        for k in exclude:
            if k.startswith(("h:", "c:")):
                s |= set(k[2:].split("|"))
            elif k.startswith("r:"):
                continue
            else:
                s.add(k)
        return s

    def cards(self, exclude: list[str], n: int = 6) -> list[dict]:
        return self._cards(exclude, n)[0]

    def _cards(self, exclude: list[str], n: int = 6) -> tuple[list[dict], int]:
        """-> (cards, number of unseen candidates left). Every row number below belongs to ONE snapshot `sp`;
        the model's scores are looked up through the model's own snapshot by image id."""
        with self.lock:
            sp, model = self.space, self.model
        ids, X, index = sp.ids, sp.X, sp.index
        ev = self.events()
        seen = self._seen(ev, exclude)
        dup = model["dup"] if model else set()
        cand_all = [i for i in sp.serve_ids if i not in seen and i not in dup]
        if not cand_all:
            return self._repeat_cards(ev, exclude, 1, pool=sp.pool), 0
        cand_emb = np.array([index[i] for i in cand_all if i in index], dtype=int)
        tapped = [e for e in ev if e.get("action") in ("like", "pass")]
        n_unary = len(tapped)
        f_seed = (1.0 / (1.0 + n_unary / 25.0)) if sp.seedvec is not None else 0.0
        ms = None            # model scores for cand_emb[scored] (the rows the fitted model has seen)
        scored = np.zeros(0, dtype=int)
        if model is not None and len(cand_emb):
            msp = model["space"]
            mrow = np.array([msp.index.get(ids[r], -1) for r in cand_emb], dtype=int)
            scored = np.flatnonzero(mrow >= 0)
            if len(scored):
                ms = M.linear_scores(model, draw=True, rng=self.nrng)[mrow[scored]]
                if model.get("knn") is not None:
                    ms = M.zs(ms) + M.zs(model["knn"][mrow[scored]])
        ss = X[cand_emb] @ sp.seedvec if (sp.seedvec is not None and len(cand_emb)) else None
        recent = [index[i] for i in [e.get("item") for e in ev[-300:]] + list(exclude) if i in index]
        chosen_rows: list[int] = []
        chosen_ids: set[str] = set()
        out: list[dict] = []

        def ok_row(r: int) -> bool:
            return not any(sp.same_project(r, c) for c in chosen_rows + recent)

        def single(iid, why, score=None):
            chosen_ids.add(iid)
            if iid in index:
                chosen_rows.append(index[iid])
            out.append({"type": "single", "key": iid, "item": iid, "img": f"img/{iid}", "why": why,
                        "score": None if score is None else round(float(score), 3)})

        def take_rows(rows, why, scores=None) -> bool:
            """the first acceptable row of `rows` (row numbers of `sp`, best first)"""
            for j, r in enumerate(rows[:400]):
                r = int(r)
                iid = ids[r]
                if iid in chosen_ids or not ok_row(r):
                    continue
                single(iid, why, None if scores is None else scores[j])
                return True
            return False

        def take_random(why, same_project_ok: bool = False) -> bool:
            pool_ = [i for i in cand_all if i not in chosen_ids]
            self.rng.shuffle(pool_)
            for iid in pool_:
                if not same_project_ok and iid in index and not ok_row(index[iid]):
                    continue
                single(iid, why)
                return True
            return False

        rep = self._repeat_cards(ev, exclude, 1, n_unary=n_unary, batch=n, pool=sp.pool)
        if rep:
            out += rep
        cand_set = set(cand_all)
        cold_left = [i for i in sp.cold if i in cand_set] if n_unary < M.COLD_START else []
        queued = sum(1 for k in exclude if not k.startswith(("h:", "c:", "r:")))
        for _ in range(n - len(out)):
            if n_unary + queued + len(out) < M.COLD_START and cold_left:
                nxt = next((i for i in cold_left if i not in chosen_ids), None)
                if nxt:
                    single(nxt, "cold")
                    continue
            r = self.rng.random()
            if ms is None or r < M.EXPLORE:
                if len(cand_emb) and ms is not None:
                    take_rows(cand_emb[self.nrng.permutation(len(cand_emb))], "explore") or take_random("explore")
                else:
                    take_random("explore")
            elif ss is not None and r < M.EXPLORE + (1 - M.EXPLORE) * f_seed:
                take_rows(cand_emb[np.argsort(-ss)], "seed") or take_random("fallback")
            else:
                o = np.argsort(-ms)
                take_rows(cand_emb[scored[o]], "model", ms[o]) or take_random("fallback")
        if not out:   # everything left is the same project as something just seen: one card rather than none
            take_random("fallback", same_project_ok=True)
        return out, len(cand_all)

    def _repeat_cards(self, ev, exclude, n, n_unary: int | None = None, batch: int = 1,
                      pool: dict | None = None) -> list[dict]:
        """scheduled self-agreement repeats: answered >= 60 taps ago, each shown again once; after the first 6,
        the retired feed's 4 % per card (one draw per batch of `batch` cards)"""
        pool = self.pool if pool is None else pool
        tapped = [e for e in ev if e.get("action") in ("like", "pass")]
        n_unary = len(tapped) if n_unary is None else n_unary
        done = sum(1 for e in tapped if e.get("why") == "repeat")
        queued = sum(1 for k in exclude if k.startswith("r:"))
        reps = done + queued
        if n_unary < M.REPEAT_GAP:
            return []
        if reps < M.REPEAT_TARGET:
            due = n_unary >= M.REPEAT_GAP + M.REPEAT_EVERY * reps
        else:
            due = self.rng.random() < min(1.0, M.REPEAT * max(1, batch))
        if not due:
            return []
        repeated = {e["item"] for e in tapped if e.get("why") == "repeat"} | {k[2:] for k in exclude if k.startswith("r:")}
        old = [e["item"] for e in tapped[:-M.REPEAT_GAP] if e.get("why") != "repeat" and e["item"] not in repeated
               and e["item"] in pool]
        old = list(dict.fromkeys(old))
        out = []
        while old and len(out) < n:
            iid = old.pop(self.rng.randrange(len(old)))
            out.append({"type": "single", "key": f"r:{iid}", "item": iid, "img": f"img/{iid}", "why": "repeat", "score": None})
        return out

    def human_pair(self, exclude: list[str]) -> dict | None:
        """two unseen items the model scores alike (among its top third) that look different — rows of the fitted
        model's own snapshot, restricted to what the current pool still serves"""
        with self.lock:
            model, serve, pool_now = self.model, set(self.space.serve_ids), self.space.pool
        if model is None:
            return None
        msp: Space = model["space"]
        ids, X = msp.ids, msp.X
        ev = self.events()
        if sum(1 for e in ev if e.get("action") or e.get("winner") in ("a", "b")) < M.COLD_START:
            return None          # decisive pairs count too: a chat-sheet user answers pairs only (sheet.py)
        seen = self._seen(ev, exclude)
        dup = model.get("dup") or set()
        cand = np.array([n for n, i in enumerate(ids) if i in serve and i not in seen and i not in dup], dtype=int)
        if len(cand) < 10:
            return None
        s_all = M.linear_scores(model)
        s = s_all[cand]
        top = cand[np.argsort(-s)[: max(min(50, len(cand)), len(cand) // 3)]]
        a = int(self.rng.choice(list(top)))
        sa = float(s_all[a])
        near = sorted(top, key=lambda j: abs(float(s_all[j]) - sa))
        b = next((int(j) for j in near[1:200] if float(X[a] @ X[j]) < M.PAIR_LOOKALIKE and not msp.same_project(a, int(j))), None)
        if b is None:
            return None
        pa, pb = ids[a], ids[b]

        def side(i):
            it = pool_now.get(i) or msp.pool.get(i, {})
            return {"id": i, "img": f"img/{i}", "ar": round((it.get("w") or 1) / max(1, it.get("h") or 1), 3)}
        return {"type": "pair", "key": f"h:{pa}|{pb}", "via": "human", "a": side(pa), "b": side(pb)}

    def next(self, exclude: list[str]) -> dict:
        cards, left = self._cards(exclude)
        pair = self.human_pair(exclude + [c["key"] for c in cards])
        if pair and pair["key"] not in exclude:
            cards.insert(self.rng.randrange(len(cards) + 1), pair)
        out = {"cards": cards, "meter": self.summary()}
        if not cards:   # nothing unseen is left (the client's queued cards are already excluded)
            out["exhausted"] = left == 0 and not self.embedding.get("running")
        return out

    # ---------------------------------------------------------------- writes
    def record_tap(self, body: dict) -> dict:
        iid = str(body.get("item", ""))[:80]
        if iid not in self.pool or body.get("action") not in ("like", "pass"):
            raise ValueError("bad tap")
        why = str(body.get("why", ""))[:12]
        sc = body.get("score")
        rec = {"eid": new_eid(), "t": now_iso(), "item": iid, "action": body["action"],
               "kind": self.pool[iid].get("kind", "human"), "dwell_ms": _int(body.get("dwell_ms")),
               "why": why if why in WHY else "", "score": sc if isinstance(sc, (int, float)) else None}
        append_jsonl(self.taps_file, rec)
        self.dirty.set()
        return rec

    def record_pair(self, body: dict) -> dict:
        w = body.get("winner")
        a, b = str(body.get("a", ""))[:80], str(body.get("b", ""))[:80]
        if w not in ("a", "b", "tie", "skip") or a not in self.pool or b not in self.pool or a == b:
            raise ValueError("bad pick")
        rec = {"eid": new_eid(), "t": now_iso(), "a": a, "b": b, "winner": w, "via": "human",
               "dwell_ms": _int(body.get("dwell_ms")),
               "shown": body.get("shown") if body.get("shown") in ("ab", "ba") else "ab",
               "layout": body.get("layout") if body.get("layout") in ("row", "stack") else "row"}
        append_jsonl(self.taps_file, rec)
        self.dirty.set()
        return rec

    def undo(self, eid: str) -> None:
        if eid:
            append_jsonl(self.taps_file, {"undo": str(eid)[:20], "t": now_iso()})
            self.dirty.set()

    # ---------------------------------------------------------------- read-outs
    def summary(self) -> dict:
        ev = self.events()
        likes = sum(1 for e in ev if e.get("action") == "like")
        passes = sum(1 for e in ev if e.get("action") == "pass")
        pairs = sum(1 for e in ev if e.get("winner") in ("a", "b"))
        taps = likes + passes + sum(1 for e in ev if e.get("winner"))
        m, mod = self.meter, self.model
        hist = read_jsonl(self.meter_file)
        return {"taps": taps, "likes": likes, "passes": passes, "pairs": pairs, "target": M.TARGET_TAPS,
                "phase": "cold start" if likes + passes < M.COLD_START else "learning",
                **M.self_agreement(ev),
                "accuracy": m and m["accuracy"], "margin": m and m["margin"], "n": m and m["n"],
                "predicted": round(M.predicted(likes + passes + pairs), 3),
                "dims": mod and mod["k"], "pool": len(self.serve_ids), "embedded": len(self.ids),
                "embedding": self.embedding, "stop": M.stop_rule(hist, taps)}

    def liked(self) -> list[dict]:
        out, done = [], set()
        for e in reversed(self.events()):                      # newest first, one entry per image
            if e.get("action") != "like" or e["item"] not in self.pool or e["item"] in done:
                continue
            done.add(e["item"])
            it = self.pool[e["item"]]
            link = f"https://www.are.na/block/{it['block_id']}" if it.get("block_id") else (it.get("source_url") or "")
            out.append({"id": e["item"], "img": f"img/{e['item']}", "title": it.get("title", ""), "link": link})
        return out


def _int(v) -> int:
    try:
        return max(0, min(int(v), 10 ** 7))
    except (TypeError, ValueError):
        return 0


def wait_for(cond, timeout: float = 5.0, step: float = 0.05) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False
