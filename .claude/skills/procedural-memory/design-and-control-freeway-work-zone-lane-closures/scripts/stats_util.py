"""CRN-paired statistics, per `quantify-sumo-run-to-run-variability`.

Every arm comparison is PAIRED on the seed (Common Random Numbers).  Report the paired
mean difference, its t-CI, the paired correlation rho, and the per-seed sign-agreement
rate -- rho matters because CRN is NOT universally beneficial and can increase the
variance of the difference for a weakly-correlated metric.
"""
import numpy as np
from scipy import stats


def paired(a, b, alpha=0.05):
    """a, b aligned per-seed arrays.  Returns diff = a - b with CI and diagnostics."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    n = len(a)
    if n < 2:
        return dict(n=n, mean_a=float(np.mean(a)) if n else np.nan,
                    mean_b=float(np.mean(b)) if n else np.nan,
                    diff=np.nan, lo=np.nan, hi=np.nan, p=np.nan,
                    rho=np.nan, sign_agree=np.nan, sig=False)
    d = a - b
    md = float(np.mean(d))
    sd = float(np.std(d, ddof=1))
    tcrit = stats.t.ppf(1 - alpha / 2, n - 1)
    hw = tcrit * sd / np.sqrt(n) if sd > 0 else 0.0
    t, p = stats.ttest_rel(a, b) if sd > 0 else (np.inf if md else 0.0, 0.0 if md else 1.0)
    rho = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else np.nan
    sign = float(np.mean(np.sign(d) == np.sign(md))) if md != 0 else np.nan
    return dict(n=n, mean_a=float(np.mean(a)), mean_b=float(np.mean(b)),
                diff=md, lo=md - hw, hi=md + hw, p=float(p), rho=rho,
                sign_agree=sign, sig=bool(np.isfinite(p) and p < alpha),
                pct=100.0 * md / float(np.mean(b)) if np.mean(b) else np.nan)


def mean_ci(x, alpha=0.05):
    x = np.asarray([v for v in x if np.isfinite(v)], float)
    n = len(x)
    if n == 0:
        return dict(n=0, mean=np.nan, lo=np.nan, hi=np.nan, sd=np.nan)
    if n == 1:
        return dict(n=1, mean=float(x[0]), lo=float(x[0]), hi=float(x[0]), sd=0.0)
    m = float(np.mean(x))
    sd = float(np.std(x, ddof=1))
    hw = stats.t.ppf(1 - alpha / 2, n - 1) * sd / np.sqrt(n)
    return dict(n=n, mean=m, lo=m - hw, hi=m + hw, sd=sd)


def onesample_vs(x, ref, alpha=0.05):
    """Is the mean of x significantly different from a fixed reference (e.g. HCM 1600)?"""
    x = np.asarray([v for v in x if np.isfinite(v)], float)
    if len(x) < 2:
        return dict(n=len(x), mean=float(np.mean(x)) if len(x) else np.nan,
                    p=np.nan, sig=False, diff=np.nan)
    t, p = stats.ttest_1samp(x, ref)
    c = mean_ci(x, alpha)
    return dict(n=c["n"], mean=c["mean"], lo=c["lo"], hi=c["hi"],
                diff=c["mean"] - ref, p=float(p), sig=bool(p < alpha), ref=ref)
