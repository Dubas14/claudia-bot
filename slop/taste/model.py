"""The feed's taste model + held-out meter — a faithful port of the retired feed/taste.py, feed/analyze.py and the
server's kNN/Thompson mechanics (research 11-gap-5 §4, §5; research 05 §5.3). Pure numpy, CPU, < 1 s refits.

Model (verbatim mechanics, constants kept):
  * every item is its embedding projected onto the top-k principal directions of the WHOLE pool (unlabelled,
    transductive: research 11-gap-5 §6.2 shows a few hundred pool images are enough for the basis), columns scaled
    to unit variance; k = adaptive_k(rows) = clamp(rows // 6, 16, 128) ("~6 taps per dimension"), also <= pool-1.
  * ONE weight vector w scores everything: like/pass rows P(like) = σ(w·x + b_kind) (free intercept per kind
    human/generated/composed, prior 1e-2); pair rows P(A wins) = σ(w·(x_A − x_B)) (Bradley–Terry on the same w).
  * MAP Bayesian logistic regression, Gaussian prior N(0, 1/λ), Newton <= 50 iterations, stop at |step| < 1e-6;
    λ ∈ {0.3, 1, 3, 10, 30, 100} by inner 4-fold held-out log-loss (ties -> stronger prior); λ = 10 below 40 rows.
  * Laplace posterior N(w, H⁻¹) -> Thompson sampling (one draw w + L·ε per card batch).
  * kNN "modes" term: mean of the top-10 cosines to liked items minus the same to passed items (pair winners count
    as likes, losers as passes); the deployed score is z(linear draw) + z(kNN) ("+1.7 points held-out").
  * meter: pooled held-out "picks the one you prefer" = (AUC(likes vs passes)·n_unary + Σ pair-correct) /
    (n_unary + n_pairs), repeated 5-fold with λ re-chosen inside each fold (nested), deployed ensemble;
    margin = 1.96·√(0.25/n).
Card-policy constants (server.py): EXPLORE 0.15, PAIR_EVERY 7, DUP_COS 0.93, REPEAT 0.04.
Onboarding additions from research 11-gap-5 §5.3 (new, not in the retired feed): a 40-card cold start stratified
over k-means clusters of the pool (replaces the reel-still "seed" cards, which a new user does not have; a user who
adds `--kind reference`-style seeds still gets the fading seed share 1/(1 + n_unary/25)); 4–6 scheduled repeats of
cards answered >= 60 taps earlier (one every 15 taps from tap 60 until 6 are done, then the 4 % rate) so
self-agreement — the ceiling — is measured from day one; the learning curve acc(n) ≈ 0.5 + 0.316·(1 − e^(−n/75.3));
the stopping rule (stop when the last 50 taps moved the meter < 2 points, or at 200 taps).
Fixer change (review round 1): the stop rule never fires before the recommended 150 taps (unless 200), compares the
mean of the last 3 meter readings (the app's own series; CLI readings are a fallback) and needs the < 2-point
movement on two consecutive checks — single reps=2 readings swing 5-9 points, so the literal rule fired in the
flat stretch (90-120 taps at 0.66-0.74 on a replay of the author's 372-tap log, which later reached 0.78-0.79).
"""
from __future__ import annotations

import math
import random

import numpy as np

KINDS = ["human", "generated", "composed"]
LAMS = [0.3, 1, 3, 10, 30, 100]
KNN_K = 10
EXPLORE, PAIR_EVERY, DUP_COS, REPEAT = 0.15, 7, 0.93, 0.04
PAIR_LOOKALIKE = 0.85      # a pair's two images must look different (cosine < 0.85)
COLD_START = 40
REPEAT_GAP = 60
REPEAT_TARGET = 6
REPEAT_EVERY = 15
TARGET_TAPS = 150          # recommended onboarding (~7 min)
MIN_TAPS = 60              # minimum viable (~3 min)
STOP_AT = 200
STOP_WINDOW, STOP_DELTA = 50, 0.02
STOP_SMOOTH, STOP_CONFIRM = 3, 2   # fixer: smoothed meter, two checks in a row, never before TARGET_TAPS


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def basis(X: np.ndarray, k: int):
    """top-k principal directions of the pool, scaled so each projected column has unit variance"""
    mu = X.mean(0)
    Xc = X - mu
    C = (Xc.T @ Xc) / max(len(X) - 1, 1)
    ev, V = np.linalg.eigh(C)
    order = np.argsort(ev)[::-1]
    k = max(1, min(k, len(X) - 1, len(ev)))
    order = order[:k]
    return mu, V[:, order].T, np.sqrt(np.maximum(ev[order], 1e-12))


def project(X: np.ndarray, B) -> np.ndarray:
    mu, V, sd = B
    return (X - mu) @ V.T / sd


def fit_logistic(A, y, wt, lam, n_free=0, iters=50):
    """MAP logistic regression, prior N(0, 1/λ) on all but the last n_free columns (intercepts, weak prior 1e-2)
    -> (w, H) with H the Hessian of the negative log posterior (posterior covariance ≈ H⁻¹)"""
    d = A.shape[1]
    w = np.zeros(d)
    P = np.full(d, float(lam))
    if n_free:
        P[d - n_free:] = 1e-2
    for _ in range(iters):
        p = sigmoid(A @ w)
        g = A.T @ (wt * (p - y)) + P * w
        H = (A * (wt * p * (1 - p))[:, None]).T @ A + np.diag(P)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-6:
            break
    p = sigmoid(A @ w)
    H = (A * (wt * p * (1 - p))[:, None]).T @ A + np.diag(P)
    return w, H


def design(unary, pairs, Z, index, B):
    """[projected x | kind one-hot] for unary rows, [x_a − x_b | 0] for pair rows"""
    k = B[1].shape[0]
    rows, y = [], []
    for item, lab, kind in unary:
        if item not in index:
            continue
        r = np.zeros(k + len(KINDS))
        r[:k] = Z[index[item]]
        r[k + KINDS.index(kind if kind in KINDS else "human")] = 1
        rows.append(r)
        y.append(lab)
    for a, b, lab in pairs:
        if a not in index or b not in index:
            continue
        r = np.zeros(k + len(KINDS))
        r[:k] = Z[index[a]] - Z[index[b]]
        rows.append(r)
        y.append(lab)
    if not rows:
        return np.zeros((0, k + len(KINDS))), np.zeros(0)
    return np.array(rows), np.array(y, dtype=float)


def auc(scores, labels):
    """probability a random like outranks a random pass (ties count half)"""
    s, y = np.asarray(scores, dtype=float), np.asarray(labels, dtype=float)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return None
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def best_lam_all(unary, pairs, Z, index, B, rng, folds=4):
    rows = [("u", u) for u in unary] + [("p", p) for p in pairs]
    if len(rows) < 16:
        return 10.0
    order = list(range(len(rows)))
    rng.shuffle(order)
    score = {}
    for L in LAMS:
        ll = 0.0
        for f in range(folds):
            te = [rows[i] for j, i in enumerate(order) if j % folds == f]
            tr = [rows[i] for j, i in enumerate(order) if j % folds != f]
            A, y = design([r for t, r in tr if t == "u"], [r for t, r in tr if t == "p"], Z, index, B)
            if not len(y):
                continue
            w, _ = fit_logistic(A, y, np.ones(len(y)), L, n_free=len(KINDS))
            At, yt = design([r for t, r in te if t == "u"], [r for t, r in te if t == "p"], Z, index, B)
            if not len(yt):
                continue
            p = np.clip(sigmoid(At @ w), 1e-6, 1 - 1e-6)
            ll += float(-(yt * np.log(p) + (1 - yt) * np.log(1 - p)).sum())
        score[L] = ll
    return min(LAMS, key=lambda L: (score[L], -L))   # held-out log-loss; ties -> stronger prior


def adaptive_k(n_rows: int) -> int:
    """dimensions the model may use grow with the evidence: ~6 taps per dimension, 16…128"""
    return int(min(128, max(16, n_rows // 6)))


# ---------------------------------------------------------------- scorers (analyze.py factories, vectorised)

def rows_of(unary, pairs, index):
    U = [("u", u) for u in unary if u[0] in index]
    P = [("p", p) for p in pairs if p[0] in index and p[1] in index]
    return U + P


def linear(X, index, k=None, lam=None):
    """the live model: PCA-k (adaptive if k is None) + Bayesian logistic, λ by inner CV -> scores over all items"""
    cache: dict[int, tuple] = {}

    def factory(tu, tp, rng):
        kk = k or adaptive_k(len(tu) + len(tp))
        if kk not in cache:
            B = basis(X, kk)
            cache[kk] = (B, project(X, B))
        B, Z = cache[kk]
        L = lam if lam is not None else best_lam_all(tu, tp, Z, index, B, rng)
        A, y = design(tu, tp, Z, index, B)
        if not len(y):
            return np.zeros(len(X))
        w, _ = fit_logistic(A, y, np.ones(len(y)), L, n_free=len(KINDS))
        return Z @ w[:B[1].shape[0]]
    return factory


def _pos_neg(tu, tp, index):
    pos = [index[i] for i, y, _ in tu if y == 1 and i in index] + \
        [index[a if y == 1 else b] for a, b, y in tp if a in index and b in index]
    neg = [index[i] for i, y, _ in tu if y == 0 and i in index] + \
        [index[b if y == 1 else a] for a, b, y in tp if a in index and b in index]
    return pos, neg


def _topk_mean(S: np.ndarray, k: int) -> np.ndarray:
    if S.shape[1] == 0:
        return np.zeros(S.shape[0])
    kk = min(k, S.shape[1])
    return np.partition(S, -kk, axis=1)[:, -kk:].mean(1)


def knn(X, index, k=KNN_K):
    """similarity to what was liked minus similarity to what was passed (mean of the top-k cosines each)"""
    def factory(tu, tp, rng):
        pos, neg = _pos_neg(tu, tp, index)
        sp = _topk_mean(X @ X[pos].T, k) if pos else np.zeros(len(X))
        sn = _topk_mean(X @ X[neg].T, k) if neg else np.zeros(len(X))
        return sp - sn
    return factory


def ensemble(*factories, index=None):
    """z-score each model's scores over the training items so they add on one scale"""
    def factory(tu, tp, rng):
        ss = [f(tu, tp, rng) for f in factories]
        items = [index[i] for i, _, _ in tu if i in index] + [index[x] for a, b, _ in tp for x in (a, b) if x in index]
        out = np.zeros(len(ss[0]))
        for s in ss:
            v = s[items] if items else s
            out += (s - v.mean()) / (v.std() + 1e-9)
        return out
    return factory


def deployed(X, index):
    return ensemble(linear(X, index), knn(X, index, KNN_K), index=index)


def evaluate(rows, factory, index, folds=5, reps=4, seed=0):
    """pooled held-out 'prefers' accuracy: AUC of likes vs passes + pair accuracy (the page's meter)"""
    rng = random.Random(seed)
    res = []
    for _ in range(reps):
        order = list(range(len(rows)))
        rng.shuffle(order)
        us, ul, pc = [], [], []
        for f in range(folds):
            te = [rows[i] for j, i in enumerate(order) if j % folds == f]
            tr = [rows[i] for j, i in enumerate(order) if j % folds != f]
            s = factory([r for t, r in tr if t == "u"], [r for t, r in tr if t == "p"], rng)
            for t, r in te:
                if t == "u":
                    us.append(float(s[index[r[0]]]))
                    ul.append(r[1])
                else:
                    pc.append(float((s[index[r[0]]] > s[index[r[1]]]) == (r[2] == 1.0)))
        a = auc(us, ul)
        nu = len(us) if a is not None else 0
        res.append(((a or 0) * nu + sum(pc)) / max(nu + len(pc), 1))
    return float(np.mean(res)), float(np.std(res))


def margin(n: int) -> float:
    return float(1.96 * math.sqrt(0.25 / max(n, 1)))


def predicted(n: int) -> float:
    """research 11-gap-5 §5.2 fitted learning curve on the author's taps (deployed ensemble)"""
    return float(0.5 + 0.316 * (1 - math.exp(-n / 75.3)))


def meter(X, index, unary, pairs, reps=4, seed=0) -> dict | None:
    rows = rows_of(unary, pairs, index)
    if len(rows) < 20:
        return None
    acc, sd = evaluate(rows, deployed(X, index), index, reps=reps, seed=seed)
    return {"accuracy": round(acc, 4), "spread": round(sd, 4), "n": len(rows), "margin": round(margin(len(rows)), 4)}


# ---------------------------------------------------------------- the deployed fit (server + fit + boards)

def knn_scores(X, index, unary, pairs, k=KNN_K):
    """server.knn_scores: None until there are >= 3 likes and >= 3 passes"""
    pos, neg = _pos_neg(unary, pairs, index)
    if len(pos) < 3 or len(neg) < 3:
        return None
    return _topk_mean(X @ X[pos].T, k) - _topk_mean(X @ X[neg].T, k)


def fit(X, index, unary, pairs, seed=0) -> dict | None:
    """fit on every tap (server.refit): -> {B, Z, w, H, S, L, lam, k, knn, n_unary, n_pairs} or None (< 5 rows)"""
    n_rows = len([u for u in unary if u[0] in index]) + len([p for p in pairs if p[0] in index and p[1] in index])
    if len(X) < 3 or n_rows < 5:
        return None
    k = adaptive_k(n_rows)
    B = basis(X, k)
    Z = project(X, B)
    A, y = design(unary, pairs, Z, index, B)
    if len(y) < 5:
        return None
    lam = best_lam_all(unary, pairs, Z, index, B, random.Random(seed)) if len(y) >= 40 else 10.0
    w, H = fit_logistic(A, y, np.ones(len(y)), lam, n_free=len(KINDS))
    kk = B[1].shape[0]
    S = np.linalg.inv(H)[:kk, :kk]
    try:
        Lc = np.linalg.cholesky(S + 1e-9 * np.eye(kk))
    except np.linalg.LinAlgError:
        Lc = np.diag(np.sqrt(np.clip(np.diag(S), 0, None)))
    return {"B": B, "Z": Z, "w": w, "H": H, "S": S, "L": Lc, "lam": lam, "k": kk, "n_unary": len(unary),
            "n_pairs": len(pairs), "knn": knn_scores(X, index, unary, pairs)}


def linear_scores(model: dict, draw: bool = False, rng: np.random.Generator | None = None) -> np.ndarray:
    w = model["w"][:model["k"]]
    if draw:
        rng = rng or np.random.default_rng()
        w = w + model["L"] @ rng.standard_normal(model["k"])   # one posterior draw (Thompson)
    return model["Z"] @ w


def zs(v: np.ndarray) -> np.ndarray:
    return (v - v.mean()) / (v.std() + 1e-9)


def taste_scores(X, index, unary, pairs, seed=0) -> np.ndarray:
    """inspo.taste_scores: the deployed linear + kNN ensemble over every item, standardised (zeros with no taps)"""
    rows = rows_of(unary, pairs, index)
    if len(rows) < 5:
        return np.zeros(len(X))
    s = deployed(X, index)([r for t, r in rows if t == "u"], [r for t, r in rows if t == "p"], random.Random(seed))
    return zs(s)


# ---------------------------------------------------------------- onboarding helpers

def self_agreement(events: list[dict]) -> dict:
    """agreement of scheduled repeats with the first answer: like/pass cards, and decisive pairs shown again (with
    sides swapped) on a chat pair sheet — the same winner image = agree"""
    first: dict[str, str] = {}
    first_pair: dict[frozenset, str] = {}
    agree = []
    for e in events:
        if e.get("winner") in ("a", "b") and e.get("a") and e.get("b"):
            key, won = frozenset((e["a"], e["b"])), e[e["winner"]]
            if e.get("why") == "repeat" and key in first_pair:
                agree.append(first_pair[key] == won)
            else:
                first_pair.setdefault(key, won)
            continue
        if e.get("action") not in ("like", "pass"):
            continue
        if e.get("why") == "repeat" and e["item"] in first:
            agree.append(first[e["item"]] == e["action"])
        else:
            first.setdefault(e["item"], e["action"])
    return {"repeats": len(agree), "self_agreement": round(sum(agree) / len(agree), 3) if agree else None}


def _meter_series(history: list[dict]) -> list[dict]:
    """the app's own readings (every 10 rows, same reps) when there are any, else whatever exists: CLI readings use
    other reps at irregular times, and mixing the two adds noise to a < 2-point comparison"""
    h = [r for r in history if r.get("accuracy") is not None and r.get("n") is not None]
    app = [r for r in h if r.get("source", "app") == "app"]
    return app or h


def _moved(h: list[dict], k: int) -> tuple[float, int] | None:
    """|smoothed meter at reading k − smoothed meter at the last reading >= STOP_WINDOW rows earlier|, span in rows;
    smoothed = mean of STOP_SMOOTH consecutive readings. None if there is not enough history."""
    if k < STOP_SMOOTH - 1 or k >= len(h):
        return None
    j = next((t for t in range(k - 1, -1, -1) if h[t]["n"] <= h[k]["n"] - STOP_WINDOW), None)
    if j is None or j < STOP_SMOOTH - 1:
        return None
    sm = lambda t: sum(r["accuracy"] for r in h[t - STOP_SMOOTH + 1: t + 1]) / STOP_SMOOTH
    return abs(sm(k) - sm(j)), int(h[k]["n"] - h[j]["n"])


def stop_rule(history: list[dict], taps: int) -> dict:
    """research 11-gap-5 §5.3: stop when the last 50 taps moved the meter < 2 points, or at 200 taps — never before
    the recommended 150 (accuracy is flat, ~70 %, until ~150 and single readings swing 5-9 points, so the raw rule
    fired at 90-120 taps on the author's own log). The movement is measured on the mean of the last 3 readings and
    must stay < 2 points on two consecutive checks."""
    if taps >= STOP_AT:
        return {"stop": True, "why": f"{taps} taps (>= {STOP_AT}): the meter is near its plateau"}
    left = max(0, TARGET_TAPS - taps)
    if left:
        return {"stop": False, "why": f"{left} more taps to the recommended {TARGET_TAPS}"}
    h = _meter_series(history)
    moves = [_moved(h, len(h) - 1 - c) for c in range(STOP_CONFIRM)]
    if all(m is not None and m[0] < STOP_DELTA for m in moves):
        d, span = moves[0]
        return {"stop": True, "why": f"the last {span} taps moved the meter {d * 100:.1f} points (< {STOP_DELTA * 100:.0f}; "
                                     f"mean of {STOP_SMOOTH} readings, {STOP_CONFIRM} checks in a row)"}
    return {"stop": False, "why": f"past the recommended {TARGET_TAPS}; keep going until the meter stops moving "
                                  f"(or {STOP_AT} taps)"}


def kmeans(X: np.ndarray, k: int, seed: int = 0, iters: int = 30) -> np.ndarray:
    """k-means++ / Lloyd on (normalised) vectors -> labels"""
    n = len(X)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    cent = [X[rng.integers(n)]]
    d2 = ((X - cent[0]) ** 2).sum(1)
    for _ in range(1, k):
        p = d2 / d2.sum() if d2.sum() > 0 else np.full(n, 1.0 / n)
        cent.append(X[rng.choice(n, p=p)])
        d2 = np.minimum(d2, ((X - cent[-1]) ** 2).sum(1))
    C = np.stack(cent)
    lab = np.zeros(n, dtype=int)
    for _ in range(iters):
        D = (X ** 2).sum(1)[:, None] - 2 * X @ C.T + (C ** 2).sum(1)[None, :]
        new = D.argmin(1)
        if (new == lab).all() and _ > 0:
            break
        lab = new
        for j in range(k):
            m = lab == j
            if m.any():
                C[j] = X[m].mean(0)
    return lab


def cold_start_order(X: np.ndarray, n: int = COLD_START, seed: int = 0) -> list[int]:
    """n row indices stratified over k-means clusters of the pool (round-robin), so every mode gets seen"""
    if len(X) == 0:
        return []
    k = int(min(20, max(4, round(math.sqrt(len(X) / 2)))))
    lab = kmeans(X, k, seed)
    rng = random.Random(seed)
    groups = [[int(i) for i in np.flatnonzero(lab == j)] for j in range(lab.max() + 1)]
    for g in groups:
        rng.shuffle(g)
    rng.shuffle(groups)
    out = []
    while len(out) < min(n, len(X)) and any(groups):
        for g in groups:
            if g and len(out) < n:
                out.append(g.pop())
    return out


# ---------------------------------------------------------------- small exact tests (no scipy)

def _lchoose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact(a: int, b: int, c: int, d: int) -> float:
    """two-sided Fisher exact p for [[a, b], [c, d]] (sum of tables no more likely than the observed one)"""
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    if n == 0:
        return 1.0
    lo, hi = max(0, c1 - r2), min(c1, r1)

    def lp(x):
        return _lchoose(r1, x) + _lchoose(r2, c1 - x) - _lchoose(n, c1)
    obs = lp(a)
    p = sum(math.exp(lp(x)) for x in range(lo, hi + 1) if lp(x) <= obs + 1e-9)
    return float(min(1.0, p))


def binom_two_sided(k: int, n: int, p: float = 0.5) -> float:
    if n == 0:
        return 1.0

    def lp(x):
        return _lchoose(n, x) + x * math.log(p) + (n - x) * math.log(1 - p)
    obs = lp(k)
    return float(min(1.0, sum(math.exp(lp(x)) for x in range(n + 1) if lp(x) <= obs + 1e-9)))
