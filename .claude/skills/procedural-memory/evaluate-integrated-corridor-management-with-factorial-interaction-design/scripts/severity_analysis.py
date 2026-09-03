#!/usr/bin/env python3
"""
Sub-goal 6 claim (v): incident-duration/severity threshold below which ICM
response does not pay. Reads collected severity-sweep results and, for each
(duration, lanes_blocked) cell, computes the best-arm benefit relative to the
no-control arm at that same cell, with a bootstrap CI -- so the threshold
where benefit crosses zero is directly visible.
"""
import argparse
import json

import numpy as np


def sel_by_seed(rows, D, M, S, V, duration, lanes_blocked):
    """seed -> tstt_veh_h for the given arm/cell (keyed by seed, so callers can
    pair same-seed observations across arms -- required for CRN resampling)."""
    return {r["seed"]: r["tstt_veh_h"] for r in rows
            if r["D"] == D and r["M"] == M and r["S"] == S and r["V"] == V
            and not r["no_incident"] and r.get("incident_duration") == duration
            and r.get("lanes_blocked") == lanes_blocked}


def mean_tstt(rows, D, M, S, V, duration, lanes_blocked):
    by_seed = sel_by_seed(rows, D, M, S, V, duration, lanes_blocked)
    if not by_seed:
        return None, []
    vals = list(by_seed.values())
    return sum(vals) / len(vals), vals


def paired_bootstrap_diff_cell(rows, base_arm, best_arm, duration, lanes_blocked, n_boot=4000, seed=0):
    """CRN-paired bootstrap CI for mean(base) - mean(best) at one (duration,
    lanes_blocked) cell, resampling whole SEEDS (not the two arms
    independently) -- the same convention as test_claims.paired_bootstrap_diff,
    used here so every cell in this report is computed identically instead of
    mixing a paired method for some cells with an unpaired one for others."""
    base_by_seed = sel_by_seed(rows, *base_arm, duration, lanes_blocked)
    best_by_seed = sel_by_seed(rows, *best_arm, duration, lanes_blocked)
    common = sorted(set(base_by_seed) & set(best_by_seed))
    if not common:
        return None
    diffs = np.array([base_by_seed[s] - best_by_seed[s] for s in common])
    point = diffs.mean()
    rng = np.random.default_rng(seed)
    boot = [rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(n_boot)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return dict(n_seeds=len(common), mean_diff=float(point), ci_lo=float(lo), ci_hi=float(hi))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collected", required=True,
                     help="severity-sweep collected results (e.g. severity_collected.json)")
    ap.add_argument("--extra-collected", nargs="*", default=[],
                     help="additional collected-result files to pull cells from, e.g. "
                          "factorial_collected.json for the 1800s reference-duration cell "
                          "(so every cell in the report -- 900s/1800s/3600s -- is computed "
                          "by this same paired-bootstrap code path)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--best-arm", default="1111")
    ap.add_argument("--worst-arm", default="0000")
    ap.add_argument("--n-boot", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    with open(args.collected) as f:
        rows = json.load(f)["rows"]
    for extra in args.extra_collected:
        with open(extra) as f:
            rows = rows + json.load(f)["rows"]

    cells = sorted({(r.get("incident_duration"), r.get("lanes_blocked")) for r in rows if not r["no_incident"]})
    d_, m_, s_, v_ = (int(c) for c in args.best_arm)
    wd_, wm_, ws_, wv_ = (int(c) for c in args.worst_arm)

    report = dict(cells=[])
    for dur, lb in cells:
        base_mean, base_vals = mean_tstt(rows, wd_, wm_, ws_, wv_, dur, lb)
        best_mean, best_vals = mean_tstt(rows, d_, m_, s_, v_, dur, lb)
        if base_mean is None or best_mean is None:
            continue
        # CRN-paired bootstrap (resamples whole seeds' base-vs-best differences
        # together, NOT the two arms independently) -- same method/convention
        # as test_claims.paired_bootstrap_diff, used consistently for every
        # cell in this report.
        diff = paired_bootstrap_diff_cell(rows, (wd_, wm_, ws_, wv_), (d_, m_, s_, v_), dur, lb,
                                           n_boot=args.n_boot, seed=args.seed)
        report["cells"].append(dict(duration_s=dur, lanes_blocked=lb,
                                     no_control_TSTT_veh_h=base_mean, best_arm_TSTT_veh_h=best_mean,
                                     benefit_veh_h=diff["mean_diff"], ci_lo=diff["ci_lo"], ci_hi=diff["ci_hi"],
                                     n_seeds=diff["n_seeds"],
                                     pays_off=bool(diff["ci_lo"] > 0),
                                     method=f"paired_bootstrap_diff_cell(seed={args.seed}, n_boot={args.n_boot})"))
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
