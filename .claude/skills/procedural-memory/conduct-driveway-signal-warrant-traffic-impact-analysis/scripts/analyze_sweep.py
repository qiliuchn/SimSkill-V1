#!/usr/bin/env python3
"""
Site-intensity sweep: at what demand level does the DETECTOR-based MUTCD warrant
check start to disagree with the DEMAND-based one?

For each site intensity (0.00 ... 3.00 x the ITE-derived 100 ksf trip
generation) run TWSC and compare, hour by hour:
   (a) nominal demand from the flow file
   (b) realised generated demand   (tripinfo depart - departDelay)
   (c) vehicles actually inserted  (tripinfo depart)
   (d) vehicles counted at the stop bar (E1 detector)
and evaluate every warrant on bases (a) and (d).

The driveway's empirical CAPACITY per clock hour is taken as the PEAK of the
served-flow-vs-demand curve across the sweep (quantify-sumo-run-to-run-
variability: capacity is the peak of that curve, not the flow at the highest
demand tested).
"""
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RUNS, SCEN, TABLES, N_HOURS, hour_label
import mutcd_warrants as W
import analyze as A

SWEEP = [("nobuild", 0.00), ("site015", 0.15), ("site025", 0.25), ("site040", 0.40),
         ("site050", 0.50), ("site075", 0.75), ("build", 1.00), ("site150", 1.50),
         ("build_high", 2.00), ("site300", 3.00)]


def main():
    man = json.load(open(os.path.join(SCEN, "demand", "demand_manifest.json")))
    per_scen = {}
    for scen, scale in SWEEP:
        d = A.rundir(scen, "twsc", 11)
        recs = A.parse_tripinfo(d)
        per_scen[scen] = {
            "scale": scale,
            "nominal": A.volumes_from_demand(scen, man),
            "generated": A.volumes_from_generated(recs, "intended"),
            "inserted": A.volumes_from_generated(recs, "depart"),
            "detector": A.volumes_from_detectors(d),
            "stats": A.parse_statistics(d),
        }
    # empirical per-hour driveway capacity = peak served across the sweep
    cap = []
    for h in range(N_HOURS):
        cap.append(max(per_scen[s]["detector"][h]["driveway"] for s, _ in SWEEP))

    rows = []
    for scen, scale in SWEEP:
        p = per_scen[scen]
        for h in range(N_HOURS):
            nom, gen = p["nominal"][h], p["generated"][h]
            ins, det = p["inserted"][h], p["detector"][h]
            vc = nom["driveway"] / cap[h] if cap[h] else 0.0
            rows.append({
                "scenario": scen, "site_scale": scale, "hour": hour_label(h),
                "driveway_vc_nominal": round(vc, 3),
                "driveway_nominal": round(nom["driveway"], 1),
                "driveway_generated": gen["driveway"],
                "driveway_inserted": ins["driveway"],
                "driveway_stopbar": det["driveway"],
                "empirical_capacity_vph": cap[h],
                "stopbar_over_generated": (round(det["driveway"] / gen["driveway"], 4)
                                           if gen["driveway"] else ""),
                "minor_higher_nominal": round(nom["minor"], 1),
                "minor_higher_stopbar": det["minor"],
                "major_nominal": round(nom["major"], 1),
                "major_stopbar": det["major"],
            })
    with open(os.path.join(TABLES, "sweep_demand_vs_served.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print("[sweep] wrote sweep_demand_vs_served.csv")

    # ---- warrant conclusions on both bases, both percentage columns
    srows = []
    for scen, scale in SWEEP:
        p = per_scen[scen]
        for basis in ("nominal", "detector"):
            for pct, cname in ((100, "standard_100pct"), (70, "reduced_70pct")):
                ev = W.evaluate_hours(p[basis], "2+", "1", pct)
                s = W.summarise(ev)
                srows.append({"scenario": scen, "site_scale": scale,
                              "volume_basis": basis, "column": cname, **s})
    with open(os.path.join(TABLES, "sweep_warrant_conclusions.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(srows[0].keys()))
        w.writeheader(); w.writerows(srows)
    print("[sweep] wrote sweep_warrant_conclusions.csv")

    # ---- console: where do the two bases disagree?
    print(f"\n{'scenario':11s} {'scale':>5s} {'basis':9s} | "
          f"{'W1A':>4s} {'W1B':>4s} {'W1':>5s} {'W2h':>4s} {'W2':>5s} {'W3h':>4s} {'W3':>5s} {'ANY':>5s}")
    for scen, scale in SWEEP:
        for basis in ("nominal", "detector"):
            r = [x for x in srows if x["scenario"] == scen and x["volume_basis"] == basis
                 and x["column"] == "standard_100pct"][0]
            print(f"{scen:11s} {scale:5.2f} {basis:9s} | {r['W1A_hours']:4d} "
                  f"{r['W1B_hours']:4d} {str(r['W1_met']):>5s} {r['W2_hours']:4d} "
                  f"{str(r['W2_met']):>5s} {r['W3_hours']:4d} {str(r['W3_met']):>5s} "
                  f"{str(r['any_volume_warrant_met']):>5s}")

    print("\nPM peak hour (17:00-18:00) metering, by site intensity:")
    print(f"{'scale':>6s} {'v/c':>6s} {'nominal':>8s} {'generated':>10s} {'inserted':>9s} "
          f"{'stopbar':>8s} {'served/gen':>11s}")
    for scen, scale in SWEEP:
        r = [x for x in rows if x["scenario"] == scen and x["hour"] == "17:00-18:00"][0]
        print(f"{scale:6.2f} {r['driveway_vc_nominal']:6.2f} {r['driveway_nominal']:8.1f} "
              f"{r['driveway_generated']:10d} {r['driveway_inserted']:9d} "
              f"{r['driveway_stopbar']:8d} {str(r['stopbar_over_generated']):>11s}")


if __name__ == "__main__":
    main()
