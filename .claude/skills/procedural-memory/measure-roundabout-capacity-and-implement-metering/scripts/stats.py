"""Paired (Common Random Numbers) replication statistics."""
import math

# two-sided t critical values, df -> t_{0.975}
_T = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
      9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
      16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 24: 2.064, 29: 2.045,
      39: 2.023, 59: 2.001}


def tcrit(df):
    if df <= 0:
        return float("nan")
    ks = sorted(_T)
    for k in ks:
        if df <= k:
            return _T[k]
    return 1.96


def mean_ci(xs):
    n = len(xs)
    if n == 0:
        return dict(mean=float("nan"), ci95=float("nan"), n=0, sd=float("nan"))
    m = sum(xs) / n
    if n == 1:
        return dict(mean=round(m, 3), ci95=float("nan"), n=1, sd=float("nan"))
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return dict(mean=round(m, 3), sd=round(sd, 3), n=n,
                ci95=round(tcrit(n - 1) * sd / math.sqrt(n), 3))


def paired_diff(a, b):
    """a - b, paired by index (CRN). Returns mean diff, 95% CI, t, and a
    significance flag, plus the paired correlation (which is what determines
    whether CRN actually reduced variance for this metric)."""
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    if n < 2:
        return dict(n=n)
    m = sum(d) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    se = sd / math.sqrt(n) if n else float("nan")
    t = m / se if se > 0 else float("inf") if m else 0.0
    tc = tcrit(n - 1)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a) / (n - 1))
    sb = math.sqrt(sum((x - mb) ** 2 for x in b) / (n - 1))
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (n - 1)
    rho = cov / (sa * sb) if sa > 0 and sb > 0 else float("nan")
    # variance-reduction factor of the paired design vs an independent design
    vrf = ((sa ** 2 + sb ** 2) / (sd ** 2)) if sd > 0 else float("inf")
    return dict(mean_diff=round(m, 3), ci95=round(tc * se, 3), t=round(t, 3), n=n,
                significant_95=bool(abs(t) > tc),
                pct=round(100 * m / mb, 2) if mb else None,
                paired_corr=round(rho, 3) if rho == rho else None,
                crn_vrf=round(vrf, 2) if vrf == vrf else None)
