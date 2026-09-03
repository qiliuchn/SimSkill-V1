#!/usr/bin/env python3
"""Small CRN-aware statistics helpers: t-based CI on a mean, and paired CI on
a difference between two matched-by-seed samples (matches
`quantify-sumo-run-to-run-variability`'s CRN convention: compare configs at
the SAME seed, then take a CI on the per-seed differences)."""
import math
import statistics as st

try:
    from scipy import stats as sstats
except Exception:
    sstats = None


def ci_mean(values, conf=0.95):
    values = [v for v in values if v is not None]
    n = len(values)
    if n == 0:
        return {"mean": None, "lo": None, "hi": None, "n": 0, "sd": None}
    if n == 1:
        return {"mean": values[0], "lo": None, "hi": None, "n": 1, "sd": None}
    m = st.mean(values)
    sd = st.stdev(values)
    se = sd / math.sqrt(n)
    if sstats is not None:
        tcrit = sstats.t.ppf(0.5 + conf / 2.0, df=n - 1)
    else:
        tcrit = 2.776 if n <= 5 else 2.0  # rough fallback for small n
    return {"mean": round(m, 4), "lo": round(m - tcrit * se, 4), "hi": round(m + tcrit * se, 4),
            "n": n, "sd": round(sd, 4)}


def paired_diff_ci(rows_a, rows_b, key_field, seed_field="seed", conf=0.95):
    """rows_a/rows_b: lists of dicts sharing seed_field. Returns CI on
    (value_a - value_b) matched by seed (CRN pairing)."""
    a_by_seed = {r[seed_field]: r.get(key_field) for r in rows_a}
    b_by_seed = {r[seed_field]: r.get(key_field) for r in rows_b}
    diffs = []
    for s in a_by_seed:
        if s in b_by_seed and a_by_seed[s] is not None and b_by_seed[s] is not None:
            diffs.append(a_by_seed[s] - b_by_seed[s])
    res = ci_mean(diffs, conf=conf)
    res["diffs"] = diffs
    res["significant"] = (res["lo"] is not None and res["hi"] is not None and
                           (res["lo"] > 0 or res["hi"] < 0))
    return res
