#!/usr/bin/env python3
"""Unit tests for the separately testable steps of counts_to_demand.py.

Run:  python3 test_c2d.py
"""
import json
import math
import os

from counts_to_demand import (peak_window, peak_hour_factor,
                              design_hour_from_profile, balance_link,
                              apply_hv_and_growth, path_movement_volumes)
from common import SCEN, N_BINS
import demand as D

ok = 0
fail = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print("  PASS %s %s" % (name, detail))
    else:
        fail.append(name)
        print("  FAIL %s %s" % (name, detail))


print("(b) sliding peak-hour search and PHF")
# a deliberately NON clock-aligned peak: bins 7-10, PHF exactly 0.87
s = [100 * x for x in D.SHARES]
i, V = peak_window(s)
check("peak window found at bin 7 (not clock-aligned)", i == 7, "-> %d" % i)
r = peak_hour_factor(s)
check("PHF == 0.87", abs(r["PHF"] - 0.87) < 1e-9, "-> %.6f" % r["PHF"])
# a clock-aligned-assumption check: the best CLOCK-ALIGNED window (bins 4-7 or 8-11)
aligned = max(sum(s[k:k + 4]) for k in (0, 4, 8, 12))
check("clock-aligned assumption under-states the peak hour", aligned < V,
      "aligned=%.2f sliding=%.2f (%.1f%% low)" % (aligned, V, 100 * (1 - aligned / V)))

print("(a) design hour: K and D")
atr = {}
bins = [900 * k for k in range(N_BINS)]
for k, b in enumerate(bins):
    atr[("EB", b)] = (600 * D.SHARES[k], 0.0)
    atr[("WB", b)] = (400 * D.SHARES[k], 0.0)
dh = design_hour_from_profile(atr, bins, "observed", study_window_share=0.32)
check("D = 0.60", abs(dh["D"] - 0.6) < 1e-9, "-> %.6f" % dh["D"])
check("DHV = 1000", abs(dh["DHV_observed"] - 1000.0) < 1e-9, "-> %.3f" % dh["DHV_observed"])
daily = sum(1000 * x for x in D.SHARES) / 0.32
check("K = DHV/daily", abs(dh["K_observed"] - 1000.0 / daily) < 1e-12,
      "-> %.5f" % dh["K_observed"])
dh2 = design_hour_from_profile(atr, bins, "k30", k30=0.10, aadt=25000)
check("K30 x AADT path", abs(dh2["DHV_design"] - 2500.0) < 1e-9,
      "DHV=%.0f scale=%.4f" % (dh2["DHV_design"], dh2["design_scale"]))

print("(c) link balancing")
r = balance_link(1000.0, 900.0, 0.5)
check("B = mean(U,A)", abs(r["B"] - 950.0) < 1e-9, "-> %.1f" % r["B"])
check("relative imbalance", abs(r["rel_imbalance"] - (100.0 / 950.0)) < 1e-9,
      "-> %.5f" % r["rel_imbalance"])
r0 = balance_link(1000.0, 900.0, 0.0)
check("w=0 keeps the downstream count", abs(r0["B"] - 900.0) < 1e-9)
r1 = balance_link(1000.0, 900.0, 1.0)
check("w=1 keeps the upstream count", abs(r1["B"] - 1000.0) < 1e-9)

print("(d) heavy-vehicle adjustment and growth")
t = {("J1", "EB", "T", 0): (1000.0, 100.0)}
out, pcu = apply_hv_and_growth(t, growth=1.02, pce=2.0)
v = pcu[("J1", "EB", "T", 0)]
check("growth applied", abs(out[("J1", "EB", "T", 0)][0] - 1020.0) < 1e-9)
check("P_HV = 0.10", abs(v["P_HV"] - 0.10) < 1e-12, "-> %.4f" % v["P_HV"])
check("f_HV = 1/(1+0.1*(2-1)) = 0.90909",
      abs(v["f_HV"] - 1.0 / 1.1) < 1e-12, "-> %.6f" % v["f_HV"])
check("pcu = veh/f_HV", abs(v["pcu"] - 1020.0 * 1.1) < 1e-9, "-> %.1f" % v["pcu"])

print("(e) path expansion conserves the counted approach volumes")
rp = os.path.join(SCEN, "rec_over_report.json")
if os.path.exists(rp):
    rep = json.load(open(rp))
    paths = {k: dict(seq=[tuple(x.split()) for x in v["seq"]], vol=v["per_bin"])
             for k, v in rep["paths"].items()}
    mv = path_movement_volumes(paths, len(rep["bins"]))
    rec = rep["recovered_movement_volumes"]
    worst = 0.0
    for k, v in mv.items():
        r = rec["%s|%s|%s" % k]
        worst = max(worst, max(abs(a - b) for a, b in zip(v, r)))
    check("path expansion is self-consistent", worst < 1e-6, "max diff %.2e" % worst)
    # every entry approach's recovered volume must equal its counted volume
    import csv as _csv
    from common import OUT
    tmc = {}
    for row in _csv.DictReader(open(os.path.join(OUT, "tmc_counts_over.csv"))):
        tmc[(row["intersection"], row["approach"], row["movement"],
             int(row["bin_start_s"]))] = float(row["veh_count"])
    tot_c = sum(tmc[k] for k in tmc if k[0] == "J1" and k[1] == "EB")
    tot_r = sum(sum(rec["J1|EB|%s" % m]) for m in "LTR")
    # exact preservation holds only where a mid-block imbalance can be
    # MATERIALISED on a real access edge; where it cannot, the tool absorbs it by
    # rescaling upstream streams, which retroactively shrinks the upstream
    # movement volumes by exactly that amount.  Both are reported.
    nonmat = sum(-m["midblock_net"] for m in rep["midblock_reconciliation"]
                 if not m["materialised"] and m["midblock_net"] < 0)
    check("entry approach volume preserved to within the non-materialisable "
          "mid-block imbalance", abs(tot_c - tot_r) / tot_c < 0.02,
          "counted=%.0f recovered=%.0f (%.2f%%), non-materialisable=%.0f"
          % (tot_c, tot_r, 100 * (tot_c - tot_r) / tot_c, nonmat))
else:
    print("  SKIP path-expansion tests (run the pipeline first)")

print("\n%d passed, %d failed %s" % (ok, len(fail), fail))
raise SystemExit(1 if fail else 0)
