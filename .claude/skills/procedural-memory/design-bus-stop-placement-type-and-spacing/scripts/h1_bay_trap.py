"""H1 -- THE BUS BAY TRAP.

A pull-out bay removes the in-lane blocking externality from cars but makes the
bus pay a re-entry penalty.  Sweep car flow x bus ridership x lanes and find where
the bay makes TOTAL PERSON-HOURS worse than an in-lane stop.

Both arms are reported in vehicle-delay AND person-delay terms.  CRN: identical
seed list in every arm; every stochastic stream is seeded from it.
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from expbase import run_arms, paired, mean, col, validity, save, ci  # noqa: E402

SEEDS = list(range(1, 11))


def main():
    cells = []
    for lanes, qs in ((2, (600, 1200, 1800, 2400)), (1, (300, 600, 900))):
        for q in qs:
            for pax in (400, 1200, 2400):
                cells.append((lanes, q, pax))
    arms = {}
    for lanes, q, pax in cells:
        base = dict(lanes_art=lanes, q_art=float(q), pax_rate=float(pax),
                    stop_placement="farside", headway=180.0,
                    q_cross=(250.0 if lanes == 2 else 180.0))
        arms[f"h1_L{lanes}_q{q}_p{pax}_inlane"] = Cfg(stop_type="inlane", **base)
        arms[f"h1_L{lanes}_q{q}_p{pax}_bay"] = Cfg(stop_type="bay", **base)
    print(f"H1: {len(arms)} arms x {len(SEEDS)} seeds = {len(arms)*len(SEEDS)} runs")
    res, errs = run_arms(arms, SEEDS, workers=9, tag="h1")

    rows = []
    for lanes, q, pax in cells:
        a = res[f"h1_L{lanes}_q{q}_p{pax}_inlane"]
        b = res[f"h1_L{lanes}_q{q}_p{pax}_bay"]
        if not a or not b:
            continue
        row = {"lanes": lanes, "q_art": q, "q_per_lane": q / lanes, "pax_rate": pax,
               "bus_occupancy": round(mean(col(a, "bus_mean_occupancy")), 2),
               "n_riders": round(mean(col(a, "n_riders")), 1),
               "n_cars": round(mean(col(a, "n_cars")), 1),
               "inlane_car_loss": round(mean(col(a, "car_mean_loss")), 2),
               "bay_car_loss": round(mean(col(b, "car_mean_loss")), 2),
               "inlane_rider_total": round(mean(col(a, "rider_mean_total")), 2),
               "bay_rider_total": round(mean(col(b, "rider_mean_total")), 2),
               "inlane_dwell": round(mean(col(a, "mean_dwell")), 2),
               "bay_dwell": round(mean(col(b, "mean_dwell")), 2),
               "d_car_ph": paired(col(a, "car_person_hours"), col(b, "car_person_hours")),
               "d_rider_ph": paired(col(a, "rider_person_hours"), col(b, "rider_person_hours")),
               "d_total_ph": paired(col(a, "total_person_hours"), col(b, "total_person_hours")),
               "d_veh_delay_h": paired(col(a, "veh_delay_hours"), col(b, "veh_delay_hours")),
               "d_bus_loss": paired(col(a, "bus_mean_loss"), col(b, "bus_mean_loss")),
               "validity_inlane": validity(a), "validity_bay": validity(b)}
        rows.append(row)
        d = row["d_total_ph"]
        print(f"L{lanes} q={q:5d} pax={pax:5d} occ={row['bus_occupancy']:5.1f} | "
              f"carPH {d['mean_a']:7.2f}->{d['mean_b']:7.2f} | "
              f"dTotalPH {d['diff']:+7.3f} +-{d['half_width']:.3f} "
              f"{'SIG' if d['significant'] else '   '} "
              f"{'BAY WORSE' if d['diff'] > 0 and d['significant'] else ''}")
    save({"seeds": SEEDS, "cells": rows, "n_failed": len(errs)}, "h1_bay_trap.json")


if __name__ == "__main__":
    main()
