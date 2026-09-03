#!/usr/bin/env python3
"""
Warrant 2 / Warrant 3 thresholds are DIGITISED from plotted MUTCD figures, so
every conclusion that rests on them must be tested against a plausible
digitisation error.  Re-evaluate all conclusions with the whole threshold curve
scaled by 0.90 / 0.95 / 1.00 / 1.05 / 1.10 and report which conclusions change.
(Warrant 1 comes from a numeric TABLE, not a curve, so it is exact and is shown
here only as a control.)
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SCEN, TABLES
import mutcd_warrants as W
import analyze as A

FACTORS = [0.90, 0.95, 1.00, 1.05, 1.10]


def main():
    man = json.load(open(os.path.join(SCEN, "demand", "demand_manifest.json")))
    rows = []
    for scen in ("nobuild", "build", "build_high"):
        bases = {"demand_nominal": A.volumes_from_demand(scen, man),
                 "detector_stopbar": A.volumes_from_detectors(A.rundir(scen, "twsc", 11))}
        for basis, v in bases.items():
            for f in FACTORS:
                ev = W.evaluate_hours(v, "2+", "1", 100 * f)
                s = W.summarise(ev)
                rows.append({"scenario": scen, "basis": basis,
                             "curve_scale": f,
                             "W1A_hours": s["W1A_hours"], "W1B_hours": s["W1B_hours"],
                             "W1_met": s["W1_met"],
                             "W2_hours": s["W2_hours"], "W2_met": s["W2_met"],
                             "W3_hours": s["W3_hours"], "W3_met": s["W3_met"],
                             "any_met": s["any_volume_warrant_met"]})
    with open(os.path.join(TABLES, "curve_digitisation_sensitivity.csv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("[sens] wrote curve_digitisation_sensitivity.csv\n")
    print(f"{'scenario':11s} {'basis':17s} {'x':>5s} | {'W2h':>4s} {'W2':>5s} "
          f"{'W3h':>4s} {'W3':>5s} {'ANY':>5s}")
    for r in rows:
        print(f"{r['scenario']:11s} {r['basis']:17s} {r['curve_scale']:5.2f} | "
              f"{r['W2_hours']:4d} {str(r['W2_met']):>5s} {r['W3_hours']:4d} "
              f"{str(r['W3_met']):>5s} {str(r['any_met']):>5s}")
    # which conclusions are unstable over the +/-10% band?
    print("\nConclusions that CHANGE within the +/-10% digitisation band:")
    any_change = False
    for scen in ("nobuild", "build", "build_high"):
        for basis in ("demand_nominal", "detector_stopbar"):
            sub = [r for r in rows if r["scenario"] == scen and r["basis"] == basis]
            for key in ("W2_met", "W3_met", "any_met"):
                vals = set(r[key] for r in sub)
                if len(vals) > 1:
                    any_change = True
                    print(f"  {scen:11s} {basis:17s} {key:8s} -> " +
                          ", ".join(f"x{r['curve_scale']:.2f}={r[key]}" for r in sub))
    if not any_change:
        print("  (none)")


if __name__ == "__main__":
    main()
