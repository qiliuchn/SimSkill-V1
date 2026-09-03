import statistics as st
import math

# two-sided 95% t-critical values by degrees of freedom (n-1), for small-n replications
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
       11: 2.201, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042}


def t_crit(df):
    if df in T95:
        return T95[df]
    if df > 30:
        return 1.96
    # nearest available
    keys = sorted(T95.keys())
    best = min(keys, key=lambda k: abs(k - df))
    return T95[best]


def mean_ci(values):
    values = [v for v in values if v is not None]
    n = len(values)
    if n == 0:
        return dict(n=0, mean=None, ci_lo=None, ci_hi=None, sd=None)
    m = st.mean(values)
    if n == 1:
        return dict(n=1, mean=m, ci_lo=None, ci_hi=None, sd=None)
    sd = st.stdev(values)
    se = sd / math.sqrt(n)
    tc = t_crit(n - 1)
    return dict(n=n, mean=round(m, 4), ci_lo=round(m - tc * se, 4), ci_hi=round(m + tc * se, 4), sd=round(sd, 4))


def paired_diff_ci(a, b):
    """a, b: lists of equal length, paired (e.g. by seed). Returns CI on mean(a-b)."""
    assert len(a) == len(b)
    diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    return mean_ci(diffs)
