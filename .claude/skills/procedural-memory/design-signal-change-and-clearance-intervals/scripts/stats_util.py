"""Small statistics helpers: t confidence intervals, paired (CRN) comparisons."""
import math
import statistics as st

try:
    from scipy import stats as _sps
except ImportError:
    _sps = None

_T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
         8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
         15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
         25: 2.060, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980}


def t975(df):
    if _sps is not None:
        return float(_sps.t.ppf(0.975, df))
    if df in _T975:
        return _T975[df]
    ks = sorted(_T975)
    for k in ks:
        if df <= k:
            return _T975[k]
    return 1.96


def mean_ci(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n == 0:
        return dict(n=0, mean=None, sd=None, hw=None, lo=None, hi=None)
    m = st.mean(xs)
    if n == 1:
        return dict(n=1, mean=m, sd=0.0, hw=None, lo=None, hi=None)
    s = st.stdev(xs)
    hw = t975(n - 1) * s / math.sqrt(n)
    return dict(n=n, mean=m, sd=s, hw=hw, lo=m - hw, hi=m + hw)


def paired(a, b):
    """CRN paired comparison of arm b vs arm a (same seed order). Returns diff = b - a."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return dict(n=len(pairs), diff=None, hw=None, lo=None, hi=None, p=None, sig=None)
    d = [y - x for x, y in pairs]
    n = len(d)
    m = st.mean(d)
    s = st.stdev(d)
    hw = t975(n - 1) * s / math.sqrt(n) if s > 0 else 0.0
    p = None
    if _sps is not None and s > 0:
        tstat = m / (s / math.sqrt(n))
        p = float(2 * (1 - _sps.t.cdf(abs(tstat), n - 1)))
    elif s == 0:
        p = 0.0 if m != 0 else 1.0
    corr = None
    if n >= 3:
        try:
            corr = st.correlation([x for x, _ in pairs], [y for _, y in pairs])
        except Exception:
            corr = None
    return dict(n=n, diff=m, sd=s, hw=hw, lo=m - hw, hi=m + hw, p=p,
                sig=(p is not None and p < 0.05), paired_corr=corr,
                mean_a=st.mean([x for x, _ in pairs]), mean_b=st.mean([y for _, y in pairs]))


def wilson(k, n, z=1.96):
    """Wilson score interval for a proportion -- correct for the small/zero counts here."""
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, c - h), min(1.0, c + h))
