#!/usr/bin/env python3
"""
Sub-goal 6: test the five explicit claims against measured CIs, using the
collected factorial results (collect_results.py output), the lag sweep, and
the severity sweep.

Usage: python test_claims.py --collected results.json --noise-floor noise_floor.json \
    --lag-sweep-collected lag_results.json --severity-collected severity_results.json \
    --out claims_report.json
"""
import argparse
import json
import sys
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from factorial import analyze, additivity_check  # noqa: E402

FACTORS = ["D", "M", "S", "V"]


def paired_bootstrap_diff(rows, arm_a, arm_b, y_col="tstt_veh_h", n_boot=4000, seed=0):
    """CRN-paired bootstrap CI for mean(y | arm_a) - mean(y | arm_b), resampling
    whole seeds. arm_a/arm_b are dicts of factor->0/1."""
    def sel(arm):
        return {r["seed"]: r[y_col] for r in rows
                if all(r[f] == arm[f] for f in FACTORS) and not r["no_incident"]}
    ya = sel(arm_a)
    yb = sel(arm_b)
    common = sorted(set(ya) & set(yb))
    if not common:
        return None
    diffs = np.array([ya[s] - yb[s] for s in common])
    point = diffs.mean()
    rng = np.random.default_rng(seed)
    boot = [rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(n_boot)]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return dict(n_seeds=len(common), mean_diff=float(point), ci_lo=float(lo), ci_hi=float(hi),
                significant=bool(not (lo <= 0 <= hi)))


def claim_i(rows, noise_floor):
    ac = additivity_check(rows, FACTORS, y_col="tstt_veh_h")
    nf = noise_floor.get("reference", {}).get("tstt_veh_h", {}).get("noise_floor_2x_sem")
    return dict(
        description="Combined effect of D+M+S+V is sub-additive relative to the sum of individual main effects (TSTT reduction).",
        base_TSTT_veh_h=ac["base"], combined_TSTT_veh_h=ac["combined"],
        combined_delta_veh_h=ac["combined_delta"], sum_of_individual_deltas_veh_h=ac["sum_of_individual_deltas"],
        single_deltas=ac["single_deltas"],
        sub_additive=ac["sub_additive"], ratio_combined_over_sum=ac["ratio_combined_over_sum"],
        noise_floor_veh_h=nf,
        resolvable=(nf is not None and abs(ac["combined_delta"] - ac["sum_of_individual_deltas"]) > 2 * nf),
    )


def claim_ii(rows, incident_only_rows):
    d_alone = dict(D=1, M=0, S=0, V=0)
    none = dict(D=0, M=0, S=0, V=0)
    diff = paired_bootstrap_diff(rows, d_alone, none, y_col="tstt_veh_h")
    spillback_rows = [r for r in incident_only_rows if r["D"] == 1 and r["M"] == 0 and r["S"] == 0 and r["V"] == 0]
    return dict(
        description="D alone (diversion, no responsive arterial signals) is harmful or neutral, verified via arterial/ramp spillback onto the mainline.",
        tstt_diff_D_alone_vs_none=diff,
        interpretation=("HARMFUL" if diff and diff["significant"] and diff["mean_diff"] > 0 else
                         "NEUTRAL" if diff and not diff["significant"] else
                         "BENEFICIAL" if diff and diff["significant"] and diff["mean_diff"] < 0 else "INSUFFICIENT_DATA"),
        n_spillback_runs_checked=len(spillback_rows),
    )


def claim_iii(rows, noise_floor):
    res = analyze(rows, FACTORS, y_col="tstt_veh_h",
                   noise_floor=noise_floor.get("reference", {}).get("tstt_veh_h", {}).get("noise_floor_2x_sem"))
    dm = [e for e in res["effects"] if e["term"] == "D:M"]
    return dict(
        description="Ramp metering and diversion are antagonistic (D:M interaction on TSTT should be positive/harmful).",
        D_M_interaction=dm[0] if dm else None,
        antagonistic=(dm[0]["effect"] > 0 and dm[0]["significant"]) if dm else None,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collected", required=True)
    ap.add_argument("--noise-floor", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.collected) as f:
        rows = json.load(f)["rows"]
    with open(args.noise_floor) as f:
        noise_floor = json.load(f)

    incident_rows = [r for r in rows if not r["no_incident"]]

    report = dict(
        claim_i=claim_i(incident_rows, noise_floor),
        claim_ii=claim_ii(incident_rows, incident_rows),
        claim_iii=claim_iii(incident_rows, noise_floor),
    )
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
