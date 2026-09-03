#!/usr/bin/env python3
"""STEP 10 -- the headline scorecard: SUMO default vs calibrated LC2013 on the
training condition, each re-evaluated on the SAME 16 independent seeds (none of
them used by the optimiser), with 95% CIs on every reported metric.

Every headline number in the report comes from this file, so a reader can check
mean, SD and CI for each one instead of a single-run figure.
"""
import os, sys, json, math, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs

SEEDS = tuple(9000 + 23 * i for i in range(16))
METRICS = ["obj", "rmsn_lane", "geh_max", "dlc", "coop_rate", "strat_rate",
           "p85", "p50", "p15", "fail_frac", "flow", "ramp_entered",
           "E_entered", "teleports", "collisions", "not_inserted",
           "depart_delay", "ex_lane0_station", "th_lane0_station",
           "n_nochange"]


def stats(reps, key, idx=None):
    v = [(r[key][idx] if idx is not None else r[key]) for r in reps if r.get("ok")]
    mu = st.mean(v)
    sd = st.stdev(v) if len(v) > 1 else 0.0
    return dict(mean=mu, sd=sd, ci95=1.96 * sd / math.sqrt(len(v)),
                lo=min(v), hi=max(v), n=len(v))


def main():
    cal = json.load(open(os.path.join(L.TBL, "calibration.json")))
    calp = {k: float(v) for k, v in cal["best_params"].items()}
    vecs = [("default", L.full_params()), ("calibrated", calp)]
    res = evaluate_runs([v for _, v in vecs], seeds=SEEDS)
    out = {"seeds": list(SEEDS), "params": {n: v for (n, v) in vecs}}
    for (name, _), r in zip(vecs, res):
        reps = [x for x in r["reps"] if x.get("ok")]
        d = {m: stats(reps, m) for m in METRICS}
        for i in range(3):
            d["share_lane%d" % i] = stats(reps, "share", i)
            d["geh_lane%d" % i] = stats(reps, "geh", i)
        d["n_rep"] = len(reps)
        out[name] = d
        print("\n=== %s (16 independent seeds) ===" % name)
        print("%-20s %12s %10s %10s %10s %10s" %
              ("metric", "mean", "sd", "ci95", "min", "max"))
        for m in list(d.keys()):
            if m == "n_rep":
                continue
            s = d[m]
            print("%-20s %12.4f %10.4f %10.4f %10.4f %10.4f"
                  % (m, s["mean"], s["sd"], s["ci95"], s["lo"], s["hi"]))
    # paired differences on the SAME seeds (CRN)
    a = [x for x in res[0]["reps"] if x.get("ok")]
    b = [x for x in res[1]["reps"] if x.get("ok")]
    diffs = {}
    for m in ("obj", "p85", "p50", "dlc", "strat_rate", "flow", "ramp_entered"):
        dv = [y[m] - x[m] for x, y in zip(a, b)]
        mu = st.mean(dv); sd = st.stdev(dv)
        diffs[m] = dict(mean_diff=mu, sd=sd, ci95=1.96 * sd / math.sqrt(len(dv)),
                        n=len(dv),
                        significant=bool(abs(mu) > 1.96 * sd / math.sqrt(len(dv))))
    for i in range(3):
        dv = [y["share"][i] - x["share"][i] for x, y in zip(a, b)]
        mu = st.mean(dv); sd = st.stdev(dv)
        diffs["share_lane%d" % i] = dict(mean_diff=mu, sd=sd,
                                         ci95=1.96 * sd / math.sqrt(len(dv)),
                                         n=len(dv),
                                         significant=bool(abs(mu) > 1.96 * sd / math.sqrt(len(dv))))
    out["paired_diff_calibrated_minus_default"] = diffs
    print("\n=== paired (CRN) differences, calibrated - default ===")
    for k, v in diffs.items():
        print("  %-16s %+12.4f  +-%.4f  %s" % (k, v["mean_diff"], v["ci95"],
                                               "SIG" if v["significant"] else "ns"))
    json.dump(out, open(os.path.join(L.TBL, "final_scorecard.json"), "w"),
              indent=2, default=str)
    print("\nwrote", os.path.join(L.TBL, "final_scorecard.json"))


if __name__ == "__main__":
    main()
