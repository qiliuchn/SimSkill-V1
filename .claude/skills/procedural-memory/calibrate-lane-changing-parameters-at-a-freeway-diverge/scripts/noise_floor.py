#!/usr/bin/env python3
"""STEP 2 -- establish the seed-to-seed NOISE FLOOR of every calibration
observable at the SUMO default LC2013 vector, following the replication-design
discipline of `quantify-sumo-run-to-run-variability` /
[[sumo-stochastic-variability-and-replication-design]].

Nothing in the screening or the calibration may be believed unless its effect
exceeds the numbers this script measures.
"""
import os, sys, json, math, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lc_common as L
from lc_eval import evaluate_runs

NSEED = int(sys.argv[1]) if len(sys.argv) > 1 else 16
SEEDS = tuple(1000 + 7 * i for i in range(NSEED))

p = L.full_params()
res = evaluate_runs([p], seeds=SEEDS, keep=False)[0]
reps = [r for r in res["reps"] if r.get("ok")]
print("ok replications: %d/%d" % (len(reps), NSEED))

METRICS = ["obj", "rmsn_lane", "geh_max", "dlc", "coop_rate", "strat_rate",
           "p85", "p50", "flow", "fail_frac", "depart_delay"]
rows = []
for m in METRICS:
    v = [r[m] for r in reps]
    mu = st.mean(v); sd = st.stdev(v) if len(v) > 1 else 0.0
    hw = 1.96 * sd / math.sqrt(len(v))
    rows.append(dict(metric=m, mean=mu, sd=sd, cv=(sd / mu if mu else float("nan")),
                     ci95_halfwidth=hw, lo=min(v), hi=max(v), n=len(v)))
for i in range(3):
    v = [r["share"][i] for r in reps]
    mu = st.mean(v); sd = st.stdev(v)
    rows.append(dict(metric="share_lane%d" % i, mean=mu, sd=sd, cv=sd / mu,
                     ci95_halfwidth=1.96 * sd / math.sqrt(len(v)),
                     lo=min(v), hi=max(v), n=len(v)))

print("\n%-16s %10s %10s %8s %10s %10s %10s" %
      ("metric", "mean", "sd", "cv", "ci95_hw", "min", "max"))
for r in rows:
    print("%-16s %10.4f %10.4f %8.4f %10.4f %10.4f %10.4f" %
          (r["metric"], r["mean"], r["sd"], r["cv"], r["ci95_halfwidth"],
           r["lo"], r["hi"]))

# required replications for a target half-width of 5% of the mean
def req_n(sd, mu, frac=0.05):
    if mu == 0 or sd == 0:
        return 1
    n = 2
    for _ in range(200):
        t = 1.96 + 2.5 / max(n - 1, 1)      # crude t approximation
        nn = int(math.ceil((t * sd / (frac * abs(mu))) ** 2))
        if nn == n:
            break
        n = max(2, nn)
    return n

for r in rows:
    r["req_n_5pct"] = req_n(r["sd"], r["mean"])

json.dump(dict(seeds=list(SEEDS), rows=rows,
               note="default LC2013 vector; all metrics from raw SUMO output"),
          open(os.path.join(L.TBL, "noise_floor.json"), "w"), indent=2)
print("\nrequired replications for +-5%% CI half-width:")
for r in rows:
    print("  %-16s %d" % (r["metric"], r["req_n_5pct"]))
print("\nwrote", os.path.join(L.TBL, "noise_floor.json"))
