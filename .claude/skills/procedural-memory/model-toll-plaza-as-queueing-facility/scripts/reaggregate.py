#!/usr/bin/env python3
"""Re-derive per-run metrics from the EXISTING sweep run directories (no re-simulation)."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as M
HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
RUNS = os.path.join(EP, "attempts", "attempt-1", "runs", "sweep")
OUT = os.path.join(EP, "outputs", "step3_sweep_raw.json")
D = json.load(open(OUT)); C = 6
tff = {int(k): v for k, v in D["tff"].items()}
tff_bin = {int(k): v for k, v in D["tff_bin"].items()}
rows = []
for arm, pre in (("random", "rnd"), ("shortest_queue", "sq"), ("shortest_queue_late", "sql")):
    for rho in D["rhos"]:
        for seed in D["seeds"]:
            d = os.path.join(RUNS, "%s_r%03d_s%d" % (pre, round(rho * 100), seed))
            m = M.run_metrics(d, C, tff, D["warm"], D["w1"], 5400.0, tff_bin=tff_bin)
            if m is None:
                print("no metrics", d); continue
            m.update(arm=arm, rho_nominal=rho, seed=seed, run_dir=d)
            rows.append(m)
D["rows"] = rows
json.dump(D, open(OUT, "w"), indent=1)
print("re-aggregated", len(rows), "rows")
