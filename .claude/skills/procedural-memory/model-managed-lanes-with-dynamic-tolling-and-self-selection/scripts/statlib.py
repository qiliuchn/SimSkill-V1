#!/usr/bin/env python3
"""Small statistics helpers: t-based CIs, paired (CRN) differences, required replications."""
import math
import statistics as st

# two-sided 97.5% t quantiles for df = 1..30
_T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
      9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
      16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074,
      23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}


def tcrit(df):
    if df <= 0:
        return float("nan")
    return _T.get(df, 1.96 if df > 30 else 2.042)


def mean_ci(xs):
    xs = [float(x) for x in xs]
    n = len(xs)
    if n == 0:
        return float("nan"), float("nan"), 0
    m = st.mean(xs)
    if n == 1:
        return m, float("nan"), 1
    s = st.stdev(xs)
    return m, tcrit(n - 1) * s / math.sqrt(n), n


def paired_diff(a_by_seed, b_by_seed):
    """mean of (a - b) over shared seeds, with a paired 95% CI and a paired-t p-value proxy."""
    seeds = sorted(set(a_by_seed) & set(b_by_seed))
    d = [float(a_by_seed[s]) - float(b_by_seed[s]) for s in seeds]
    n = len(d)
    if n < 2:
        return dict(n=n, mean=st.mean(d) if d else float("nan"), hw=float("nan"),
                    t=float("nan"), sig=False, seeds=seeds)
    m, s = st.mean(d), st.stdev(d)
    hw = tcrit(n - 1) * s / math.sqrt(n)
    t = m / (s / math.sqrt(n)) if s > 0 else float("inf") * (1 if m > 0 else -1)
    return dict(n=n, mean=m, hw=hw, t=t, sig=abs(m) > hw, seeds=seeds, sd=s)


def crn_variance_reduction(a_by_seed, b_by_seed):
    """Var of the paired difference vs the variance an INDEPENDENT design would have had."""
    seeds = sorted(set(a_by_seed) & set(b_by_seed))
    A = [float(a_by_seed[s]) for s in seeds]
    B = [float(b_by_seed[s]) for s in seeds]
    if len(seeds) < 3:
        return float("nan"), float("nan")
    va, vb = st.variance(A), st.variance(B)
    d = [x - y for x, y in zip(A, B)]
    vd = st.variance(d)
    indep = va + vb
    try:
        rho = st.correlation(A, B)
    except Exception:                                       # noqa: BLE001
        rho = float("nan")
    return (indep / vd if vd > 0 else float("inf")), rho


def required_n(xs, rel_halfwidth=0.05):
    """Replications needed for a 95% CI half-width of rel_halfwidth * mean."""
    xs = [float(x) for x in xs]
    if len(xs) < 2:
        return float("nan")
    m, s = st.mean(xs), st.stdev(xs)
    d = abs(rel_halfwidth * m)
    if d == 0:
        return float("nan")
    n = len(xs)
    for _ in range(50):
        n_new = max(2, math.ceil((tcrit(max(1, n - 1)) * s / d) ** 2))
        if n_new == n:
            break
        n = n_new
    return n
