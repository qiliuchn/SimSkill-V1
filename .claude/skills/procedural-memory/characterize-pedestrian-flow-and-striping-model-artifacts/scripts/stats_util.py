#!/usr/bin/env python3
"""Small replication-statistics helpers shared by the analysis scripts."""
import math

try:
    from scipy import stats as _st
except Exception:
    _st = None


def tcrit(n, alpha=0.05):
    if n < 2:
        return float("nan")
    if _st is not None:
        return float(_st.t.ppf(1 - alpha / 2.0, n - 1))
    return 2.776 if n <= 5 else 2.0


def mean_ci(xs, alpha=0.05):
    xs = [x for x in xs if x == x]
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": float("nan"), "sd": float("nan"),
                "ci_half": float("nan"), "cv": float("nan")}
    m = sum(xs) / n
    if n == 1:
        return {"n": 1, "mean": m, "sd": 0.0, "ci_half": float("nan"), "cv": 0.0,
                "lo": m, "hi": m}
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    h = tcrit(n, alpha) * sd / math.sqrt(n)
    return {"n": n, "mean": m, "sd": sd, "ci_half": h, "cv": (sd / m if m else float("nan")),
            "lo": m - h, "hi": m + h}


def paired_diff(a, b, alpha=0.05):
    """CRN paired comparison: a and b are seed-aligned lists."""
    d = [x - y for x, y in zip(a, b)]
    s = mean_ci(d, alpha)
    s["significant"] = (s["n"] >= 2 and s["ci_half"] == s["ci_half"]
                        and abs(s["mean"]) > s["ci_half"])
    if len(a) >= 3:
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
        vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
        s["corr"] = cov / math.sqrt(va * vb) if va > 0 and vb > 0 else float("nan")
        # variance-reduction factor of CRN vs an independent-seed design
        s["var_paired"] = va + vb - 2 * cov
        s["var_independent"] = va + vb
        s["crn_vrf"] = (s["var_independent"] / s["var_paired"]
                        if s["var_paired"] > 1e-15 else float("inf"))
    return s
