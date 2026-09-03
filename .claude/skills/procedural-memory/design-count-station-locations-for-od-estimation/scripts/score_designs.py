"""Scoring harness for count-station designs, plus the non-deployable oracle.

This module is the TRUTH SIDE of the barrier. It is the only place allowed to open the
ground-truth matrix. Keep it that way, and keep `placement_lib.py` free of any import
of this file, so a grep can prove the deployable strategies never saw the truth.

Three doors, and only three:
  * `observed_counts()` — the data-generating process. Estimators see only the
    *instrumented rows* of what it returns, i.e. noisy link flows, never the matrix.
  * `score()` — called only AFTER an estimate exists. Scoring is not estimation.
  * `oracle_gain()` / `oracle_order()` — used only by the oracle strategy, which must
    be labelled NON-DEPLOYABLE everywhere it appears in results.

Everything here also works in a real (non-synthetic) study with the truth doors simply
unavailable — in which case `score()` degenerates to the count-fit half, which is
exactly the trap this skill exists to warn about. In a real study you cannot rank
designs; you can only reason about `P`. See SKILL.md, "What to do in a real study".
"""
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ODME_SCRIPTS = os.environ.get(
    "ODME_SCRIPTS",
    os.path.abspath(os.path.join(_HERE, "..", "..", "estimate-od-matrix-with-odme", "scripts")),
)
if ODME_SCRIPTS not in sys.path:
    sys.path.insert(0, ODME_SCRIPTS)
from odme_core import count_fit, od_recovery, rmsn                    # noqa: E402

import placement_lib as pl                                            # noqa: E402


# =========================================================== data-generating process
def observed_counts(true_assigned, realisation=0, cv=0.05, bias=0.0):
    """Synthesise field counts on EVERY candidate link from the true assignment.

    `true_assigned` is (n_realisations, n_links) — the route-implied link counts of the
    true matrix under several router seeds. Using >1 router seed matters: it makes each
    count realisation span *assignment* realisation noise as well as measurement noise,
    and assignment noise is usually the larger of the two.

    `bias` is a systematic multiplicative detector under-count (0.08 -> reads 8% low).
    Keep it separate from `cv`: they behave completely differently (see SKILL.md).
    """
    R = np.atleast_2d(true_assigned)
    v = R[realisation % R.shape[0]]
    rng = np.random.default_rng(9000 + realisation)
    c = v * (1.0 + rng.normal(0.0, cv, size=len(v))) * (1.0 - bias)
    return np.maximum(np.round(c), 0.0)


def observed_from_base(base, noise_seed=0, cv=0.05, bias=0.0):
    """Add measurement noise to an arbitrary true observation vector — used for subpath
    reader observations, whose base comes from ID matching in one microsim run rather
    than from the route-implied realisations."""
    base = np.asarray(base, float)
    rng = np.random.default_rng(50000 + noise_seed)
    c = base * (1.0 + rng.normal(0.0, cv, size=len(base))) * (1.0 - bias)
    return np.maximum(np.round(c), 0.0)


def count_noise_floor(true_assigned, cv=0.05, n=6):
    """RMSN between independent count realisations = THE COUNT NOISE FLOOR.

    Measure this BEFORE ranking any designs. Every strategy comparison has to clear it,
    and in the reference study it is what turned an apparent winner into a null result.
    Returns (mean, sd, all pairwise values)."""
    reps = [observed_counts(true_assigned, r, cv=cv) for r in range(n)]
    vals = [rmsn(reps[i], reps[j]) for i in range(n) for j in range(i + 1, n)]
    return float(np.mean(vals)), float(np.std(vals)), vals


# ============================================================== the two criteria
def score(pairs, x_hat, P, c_obs, sel_idx, heldout_idx, truth, top_k=10):
    """Score one design+estimate on BOTH criteria. Never conflate them.

    Count fit is reported three ways on purpose, because which link set you score on
    changes the answer completely:
      * `inst_*`  — the INSTRUMENTED links. This is what a practitioner reports and it
                    is very nearly useless for ranking designs: it is the objective the
                    estimator just minimised, on the links the design itself chose.
      * `held_*`  — links deliberately excluded from selection AND estimation.
      * `all_*`   — every candidate link, i.e. a FIXED reference set independent of the
                    design. This is the count-based statistic that actually correlates
                    with OD recovery.

    `od_struct_rmsn_pct` rescales the estimate to the true total before comparing, so it
    measures PATTERN error with the level right by construction. Report it alongside
    plain cell %RMSN — otherwise a single well-placed count that fixes the overall level
    looks like a large recovery improvement.
    """
    truth = np.asarray(truth, float)
    v_hat = P @ x_hat
    inst = count_fit(v_hat[sel_idx], c_obs[sel_idx])
    held = count_fit(v_hat[heldout_idx], c_obs[heldout_idx])
    allc = count_fit(v_hat, c_obs)
    rec = od_recovery([tuple(p) for p in pairs], x_hat, truth)
    order = np.argsort(-truth)[:top_k]
    top_err = float(100.0 * np.abs(x_hat[order] - truth[order]).sum() / truth[order].sum())
    sf = x_hat * (truth.sum() / max(x_hat.sum(), 1e-9))
    return dict(
        inst_rmsn_pct=inst["rmsn_pct"], inst_geh_lt5_pct=inst["geh_lt5_pct"],
        inst_geh_mean=inst["geh_mean"], n_inst=inst["n_links"],
        held_rmsn_pct=held["rmsn_pct"], held_geh_lt5_pct=held["geh_lt5_pct"],
        all_rmsn_pct=allc["rmsn_pct"], all_geh_lt5_pct=allc["geh_lt5_pct"],
        od_rmsn_pct=rec["cell_rmsn_pct"], od_struct_rmsn_pct=round(float(rmsn(sf, truth)), 3),
        od_mae=rec["cell_mae"], od_corr=rec["cell_corr"],
        total_err_pct=rec["total_demand_err_pct"],
        row_mape_pct=rec["row_marginal_mape_pct"],
        col_mape_pct=rec["col_marginal_mape_pct"],
        misallocated_pct=rec["share_misallocated_pct"],
        top10_err_pct=round(top_err, 3),
    )


# ================================================================ the oracle bound
def oracle_gain(x_hat, truth):
    """NON-DEPLOYABLE. The objective the oracle placement strategy minimises."""
    return rmsn(x_hat, np.asarray(truth, float))


def oracle_order(P, c_obs, seed_vec, truth, cand=None, w_seed=0.1):
    """Greedy minimisation of ACTUAL OD-recovery error — the achievability upper bound.

    NON-DEPLOYABLE by construction; label it so in every table and figure. Its value is
    that "strategy X captures Y% of the oracle's gain" is a far more informative claim
    than "strategy X beats strategy Z", and it tells you whether a disappointing
    deployable result means the criterion is bad or the problem is simply hard.

    In the reference study oracle-greedy landed within 0.7-1.1 points of a near-exact
    local-search optimum, so greedy is a defensible stand-in for the true bound — but
    verify that on your own network with `enumerate_small_budget` / `local_search`.
    """
    cand = list(range(P.shape[0])) if cand is None else list(cand)
    order, remaining = [], set(cand)
    while remaining:
        best, best_err = None, np.inf
        for l in sorted(remaining):
            sel = order + [l]
            x, _ = pl.estimate(P, c_obs, sel, seed_vec, w_seed)
            e = oracle_gain(x, truth)
            if e < best_err:
                best, best_err = l, e
        order.append(best)
        remaining.discard(best)
    return order


# ====================================================== greedy vs near-exact checks
def enumerate_small_budget(P, c_obs, seed_vec, truth, cand, n=2, w_seed=0.1):
    """Exhaustively enumerate every design of size `n` to get a TRUE optimum.

    Do this at least once. It is cheap at n=2 (a few thousand solves, ~1 s) and it is
    the only way to know whether your greedy is near-optimal or merely plausible. In
    the reference study oracle-greedy recovered the enumerated optimum exactly, which
    is what licensed using greedy everywhere else."""
    from itertools import combinations
    best, best_err, evals = None, np.inf, 0
    for sel in combinations(sorted(cand), n):
        x, _ = pl.estimate(P, c_obs, list(sel), seed_vec, w_seed)
        e = oracle_gain(x, truth)
        evals += 1
        if e < best_err:
            best, best_err = list(sel), e
    return dict(best=best, best_err=float(best_err), n_designs=evals)


def local_search(P, c_obs, seed_vec, truth, start, cand, w_seed=0.1, max_iter=60):
    """Steepest-descent single-swap local search from `start` — the near-exact reference.

    Run it from at least TWO different greedy starts. Converging to the same value from
    different starts is the evidence that the local optimum is worth calling near-exact;
    a single run tells you nothing about the landscape."""
    sel = list(start)
    outside = [l for l in cand if l not in set(sel)]
    x, _ = pl.estimate(P, c_obs, sel, seed_vec, w_seed)
    cur = oracle_gain(x, truth)
    evals = 0
    for _ in range(max_iter):
        best_move, best_err = None, cur
        for i in range(len(sel)):
            for l in outside:
                trial = sel[:i] + [l] + sel[i + 1:]
                x, _ = pl.estimate(P, c_obs, trial, seed_vec, w_seed)
                e = oracle_gain(x, truth)
                evals += 1
                if e < best_err - 1e-12:
                    best_move, best_err = (i, l), e
        if best_move is None:
            break
        i, l = best_move
        outside = [o for o in outside if o != l] + [sel[i]]
        sel = sel[:i] + [l] + sel[i + 1:]
        cur = best_err
    return dict(design=sel, err=float(cur), evals=evals)


def marginal_gain_diagnostics(errs):
    """Given a strategy's error-vs-N curve, report whether the marginal-gain sequence
    is actually diminishing (submodular-like) and whether error is monotone in N.

    Do not assume either. Measured on the reference network, 32-43% of single-sensor
    additions INCREASED OD error and 22-52% of steps were non-diminishing, for every
    strategy including the oracle — so greedy-with-submodularity guarantees borrowed
    from the network-design literature do not transfer here."""
    e = np.asarray(errs, float)
    gains = -np.diff(e)                      # positive = error went down
    steps = len(gains)
    return dict(
        n_steps=steps,
        negative_gain_steps=int((gains < 0).sum()),
        negative_gain_pct=round(100.0 * float((gains < 0).mean()), 1) if steps else 0.0,
        non_diminishing_steps=int((np.diff(gains) > 0).sum()),
        non_diminishing_pct=round(100.0 * float((np.diff(gains) > 0).mean()), 1) if steps > 1 else 0.0,
        monotone=bool((gains >= 0).all()),
        best_n_index=int(np.argmin(e)),
        best_err=float(e.min()),
        err_at_full=float(e[-1]),
    )


# ===================================================== resolvable-difference testing
def resolvable_difference(sigma, n=1, rho=0.0):
    """`optimize-under-simulation-noise-with-a-fixed-budget`'s minimum difference two
    designs must differ by before you may call one better, at n replications with
    correlation rho under common random numbers."""
    return 1.96 * np.sqrt(2.0 * (1.0 - rho)) * float(sigma) / np.sqrt(n)


def paired_crn_test(err_a, err_b):
    """Paired CRN comparison of two designs across matched count realisations.

    Pairing is the whole point: the same realisation index must mean the same synthetic
    count vector for both designs. Returns the mean paired difference and its 95%
    half-width; if |mean| < half_width the two designs are TIED and you must say so
    rather than reporting a winner. This is the test that converted the reference
    study's apparent winner into an honest null result."""
    d = np.asarray(err_a, float) - np.asarray(err_b, float)
    n = len(d)
    hw = 1.96 * float(d.std(ddof=1)) / np.sqrt(n) if n > 1 else float("inf")
    return dict(mean_diff=float(d.mean()), half_width=hw,
                resolvable=bool(abs(float(d.mean())) > hw), n=n)


def spearman(a, b):
    """Spearman rank correlation with tie-averaged ranks (no scipy.stats needed)."""
    def rk(v):
        v = np.asarray(v, float)
        order = np.argsort(v, kind="mergesort")
        r = np.empty(len(v))
        r[order] = np.arange(len(v), dtype=float)
        _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
        for i, c in enumerate(cnt):
            if c > 1:
                m = inv == i
                r[m] = r[m].mean()
        return r
    ra, rb = rk(a), rk(b)
    ra -= ra.mean()
    rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den > 0 else float("nan")


def kendall_tau(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    conc = disc = 0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            s = np.sign(a[i] - a[j]) * np.sign(b[i] - b[j])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    tot = conc + disc
    return float((conc - disc) / tot) if tot else float("nan")


def corr_significance(rho, n):
    """Two-sided p-value and Fisher 95% CI for a rank correlation on n observations.

    Use this on EVERY correlation you report. A design study typically compares a
    handful of designs downstream, and a correlation on n=12 has a CI roughly one unit
    wide — wide enough that its sign is not established. The reference study initially
    reported a bolded negative correlation that this function shows to be
    indistinguishable from zero (rho=-0.294, n=12, p=0.354, CI [-0.74, +0.34])."""
    import math
    if abs(rho) >= 1 or n < 4:
        return dict(rho=float(rho), n=int(n), p=0.0, ci=(float(rho), float(rho)))
    t = rho * math.sqrt((n - 2) / (1 - rho ** 2))
    df = n - 2
    x = df / (df + t * t)
    p = _betai(df / 2.0, 0.5, x)
    z, se = 0.5 * math.log((1 + rho) / (1 - rho)), 1.0 / math.sqrt(n - 3)
    f = lambda v: (math.exp(2 * v) - 1) / (math.exp(2 * v) + 1)          # noqa: E731
    return dict(rho=float(rho), n=int(n), p=float(p),
                ci=(f(z - 1.96 * se), f(z + 1.96 * se)),
                resolvable=bool(p < 0.05))


def _betai(a, b, x):
    import math
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    def betacf(a, b, x, itmax=200, eps=3e-16):
        qab, qap, qam = a + b, a + 1.0, a - 1.0
        c, d = 1.0, 1.0 - qab * x / qap
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        h = d
        for m in range(1, itmax + 1):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
            c = 1.0 + aa / c
            c = c if abs(c) > 1e-300 else 1e-300
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
            c = 1.0 + aa / c
            c = c if abs(c) > 1e-300 else 1e-300
            de = d * c
            h *= de
            if abs(de - 1.0) < eps:
                break
        return h

    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lb + a * math.log(x) + b * math.log(1 - x)) * betacf(a, b, x) / a
    return 1.0 - math.exp(lb + b * math.log(1 - x) + a * math.log(x)) * betacf(b, a, 1 - x) / b
