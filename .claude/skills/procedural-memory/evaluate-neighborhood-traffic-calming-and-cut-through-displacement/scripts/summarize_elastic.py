#!/usr/bin/env python3
"""Collect the elastic-demand sweep and locate the displacement->evaporation crossover."""
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from elastic_demand import costs_and_metrics, RUNS, ANA  # noqa: E402

VARIANT = sys.argv[1] if len(sys.argv) > 1 else "F"


# Reference points come from the SAME 3-pass x 8-iteration DUE machinery as the elastic
# arms (elastic_demand.py --elasticity 0 keeps every trip), so the e=0 point and the
# baseline are methodologically identical to the e>0 points -- not borrowed from the
# 25-iteration main assignment, which would not be comparable.
base = json.load(open(os.path.join(ANA, "elastic_A_e0.json")))["trace"][-1]
pts = []
for f in sorted(glob.glob(os.path.join(ANA, "elastic_%s_e*.json" % VARIANT))):
    j = json.load(open(f))
    pts.append((j["elasticity"], j["trace"][-1]))
pts.sort()

METRICS = ["n_completed", "VHT_h", "VHT_incl_dd_h", "ring_vehkm", "ring_timeloss_vehh",
           "cutthrough_vehkm", "interior_vehkm_total", "mean_total_cost"]

rows = [["elasticity"] + METRICS + ["n_demanded", "n_suppressed", "suppressed_pct"]]
rows.append(["A baseline (fixed demand)"] + [base[m] for m in METRICS] +
            [base["n_completed"], 0, 0.0])
for e, m in pts:
    nd = m.get("n_demanded", m["n_completed"])
    ns = m.get("n_suppressed", 0)
    rows.append([e] + [m[k] for k in METRICS] +
                [nd, ns, round(100.0 * ns / (nd + ns) if (nd + ns) else 0, 2)])
with open(os.path.join(ANA, "elastic_sweep_%s.csv" % VARIANT), "w", newline="") as f:
    csv.writer(f).writerows(rows)

cross = {}
for m in ("VHT_h", "VHT_incl_dd_h", "ring_vehkm", "ring_timeloss_vehh"):
    xs = [(e, d[m]) for e, d in pts]
    b = base[m]
    hit = None
    for (e0, v0), (e1, v1) in zip(xs, xs[1:]):
        if (v0 - b) * (v1 - b) <= 0 and v0 != v1:
            hit = round(e0 + (b - v0) * (e1 - e0) / (v1 - v0), 3)
            break
    cross[m] = dict(baseline_A=b, at_e0=xs[0][1], at_emax=xs[-1][1],
                    crossover_elasticity=hit,
                    exceeds_baseline_at_e0=bool(xs[0][1] > b))
json.dump(dict(variant=VARIANT, baseline=base, points=[dict(elasticity=e, **d) for e, d in pts],
               crossover=cross),
          open(os.path.join(ANA, "elastic_summary_%s.json" % VARIANT), "w"), indent=1)

for r in rows:
    print("  ".join(str(x) for x in r))
print()
for m, d in cross.items():
    print("%-20s baseline_A=%.1f  variant@e=0=%.1f  variant@e=%.2f=%.1f  crossover e*=%s"
          % (m, d["baseline_A"], d["at_e0"], pts[-1][0], d["at_emax"], d["crossover_elasticity"]))
