#!/usr/bin/env python3
"""Pick the empirically best fixed-time plan (structure x cycle) per demand level
from the s0 sweep -- this is what makes the fixed-time arm a genuinely
"well-tuned" baseline rather than whatever netconvert happened to generate."""
import json, os, sys, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import run_metrics

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMANDS = [300, 600, 900, 1200, 1500]
CYCLES = [40, 50, 60, 70, 80, 90, 110, 130]
SEEDS = [101, 102, 103]

best, table = {}, {}
for d in DEMANDS:
    rows = []
    for stru in ("p2", "p4"):
        for c in CYCLES:
            vals = []
            for s in SEEDS:
                m = run_metrics(os.path.join(BASE, "runs/s0/%s_d%d_c%d_s%d" % (stru, d, c, s)))
                if m:
                    vals.append(m["mean_delay"])
            if len(vals) == len(SEEDS):
                rows.append((st.mean(vals), stru, c))
    rows.sort()
    table[d] = [(round(r[0], 1), r[1], r[2]) for r in rows]
    best[d] = "net/plans/%s_d%d_c%d.xml" % (rows[0][1], d, rows[0][2])
    print("demand %4d: best = %s cycle %d  (mean delay %.1f s) | worst tested %.1f s"
          % (d, rows[0][1], rows[0][2], rows[0][0], rows[-1][0]))
json.dump(best, open(os.path.join(BASE, "net/plans/best.json"), "w"), indent=1)
json.dump(table, open(os.path.join(BASE, "runs/s0/sweep_table.json"), "w"), indent=1)
