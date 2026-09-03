#!/usr/bin/env python3
"""Rebuild the per-variant DUE convergence diagnostic from runs/due/<V>/ (safe to run
after the parallel DUE stage, which cannot share one json file)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_variants import due_diagnostic, DUE_STEPS, RUNS, ANA, VARIANTS  # noqa: E402

diag = {}
for v in VARIANTS:
    d = os.path.join(RUNS, "due", v)
    if not os.path.isdir(d):
        continue
    diag[v] = due_diagnostic(d, DUE_STEPS)
    print("=== variant %s ===" % v)
    for r in diag[v]:
        print("  it%-3d n=%-5d dur=%8.2f departDelay=%7.2f total=%8.2f routeChange=%s"
              % (r["iter"], r["n_completed"], r["mean_duration"], r["mean_depart_delay"],
                 r["mean_total_cost"], r["route_change_fraction"]))
    tail = [r["mean_total_cost"] for r in diag[v][-4:]]
    rel = (max(tail) - min(tail)) / (sum(tail) / len(tail))
    print("  last-4-iteration relative spread of mean TOTAL cost: %.4f" % rel)
    diag[v + "_converged_rel_spread"] = round(rel, 5)
json.dump(diag, open(os.path.join(ANA, "due_convergence.json"), "w"), indent=1)
print("wrote", os.path.join(ANA, "due_convergence.json"))
