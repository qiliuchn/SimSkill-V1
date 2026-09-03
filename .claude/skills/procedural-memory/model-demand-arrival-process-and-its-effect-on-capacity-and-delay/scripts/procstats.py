#!/usr/bin/env python3
"""Realised-headway process statistics: moments, empirical CDF, KS test."""
import numpy as np
from scipy import stats as sps

import arrivals

# grid on which the empirical CDF is stored for every run (seconds)
CDF_GRID = np.concatenate([np.arange(0.0, 6.0, 0.25), np.arange(6.0, 20.0, 1.0),
                           np.arange(20.0, 61.0, 5.0)])


def headway_stats(h, spec=None, V=None, keep_raw=False):
    h = np.asarray(h, float)
    h = h[np.isfinite(h)]
    out = {"n": int(h.size)}
    if h.size < 5:
        return out
    m, sd = float(h.mean()), float(h.std(ddof=1))
    out.update({"mean": m, "sd": sd, "cv": sd / m if m > 0 else None,
                "min": float(h.min()), "max": float(h.max()),
                "p05": float(np.percentile(h, 5)), "p25": float(np.percentile(h, 25)),
                "p50": float(np.percentile(h, 50)), "p75": float(np.percentile(h, 75)),
                "p95": float(np.percentile(h, 95)),
                "frac_lt_1_5s": float(np.mean(h < 1.5)),
                "frac_lt_2s": float(np.mean(h < 2.0)),
                "frac_lt_3s": float(np.mean(h < 3.0)),
                "frac_gt_2mean": float(np.mean(h > 2 * m))})
    hs = np.sort(h)
    out["ecdf_grid"] = [round(float(x), 4) for x in
                        np.searchsorted(hs, CDF_GRID, side="right") / hs.size]
    if spec is not None and V is not None:
        F = arrivals.intended_cdf(spec, V)
        # one-sample KS statistic against the INTENDED cdf
        n = hs.size
        Fv = np.clip(F(hs), 0.0, 1.0)
        d_plus = np.max(np.arange(1, n + 1) / n - Fv)
        d_minus = np.max(Fv - np.arange(0, n) / n)
        D = float(max(d_plus, d_minus))
        out["ks_D"] = D
        out["ks_p"] = float(sps.kstwo.sf(D, n)) if n < 100000 else float(
            sps.kstwobign.sf(D * np.sqrt(n)))
        if spec == "bin":
            # the intended law is DISCRETE (geometric on 1-s slots); the naive
            # continuous KS statistic above is inflated by the atoms, so also
            # report the discrete-aware statistic.
            out["ks_discrete"] = ks_discrete(hs, F, np.arange(1, 121))
        # common yardstick: distance from a Poisson (exponential) process of the
        # SAME realised mean headway -- comparable across all six specifications
        Fe = lambda x: 1.0 - np.exp(-np.asarray(x, float) / m)  # noqa: E731
        Fev = np.clip(Fe(hs), 0, 1)
        De = float(max(np.max(np.arange(1, n + 1) / n - Fev),
                       np.max(Fev - np.arange(0, n) / n)))
        out["ks_D_vs_exponential_same_mean"] = De
        mi, cvi = arrivals.intended_moments(spec, V)
        out["intended_mean"] = mi
        out["intended_cv"] = cvi
        out["cv_ratio_realised_over_intended"] = (sd / m) / cvi if cvi > 0 else None
        out["intended_cdf_on_grid"] = [round(float(x), 4) for x in np.clip(F(CDF_GRID), 0, 1)]
    if keep_raw:
        out["headways"] = [round(float(x), 3) for x in h]
    return out


def ks_discrete(h, F, support):
    """KS statistic for DISCRETE data.

    Applying a continuous-data KS test to a discrete sample is a real measurement
    trap: every tie at an atom makes the naive statistic jump to (at least) the
    size of that atom, so a PERFECT geometric sample scores D ~= p rather than
    D ~= 0.  The correct statistic compares the empirical and theoretical CDFs
    only AT the support points."""
    h = np.asarray(h, float)
    n = h.size
    if n < 5:
        return None
    sup = np.asarray(support, float)
    Fn = np.searchsorted(np.sort(h), sup, side="right") / n
    Fn_left = np.searchsorted(np.sort(h), sup, side="left") / n
    Ft = np.clip(F(sup), 0, 1)
    D = float(max(np.max(np.abs(Fn - Ft)), np.max(np.abs(Fn_left - Ft))))
    return {"D": D, "p": float(sps.kstwo.sf(D, n)), "n": int(n)}


def ks_two_sample(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.size < 5 or b.size < 5:
        return None
    r = sps.ks_2samp(a, b)
    return {"D": float(r.statistic), "p": float(r.pvalue), "na": int(a.size), "nb": int(b.size)}
