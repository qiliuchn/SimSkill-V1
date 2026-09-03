"""H1b -- WHERE IS THE BAY TRAP?

H1 found the bay never loses in total person-hours under SUMO's NATIVE mechanics.
Two explicit crossover statements are produced here instead of a bare "no trap":

 (1) CRITICAL CAR OCCUPANCY.  Total person-hours = occ_car * dCarVehHours
     + dRiderHours.  Since only the first term scales with assumed car occupancy,
     the occupancy at which the bay stops paying is closed-form per cell:
        occ* = -dRiderHours / dCarVehHours
     Report it for every H1 cell -> "the bay would only lose if a car carried
     fewer than occ* people".

 (2) CRITICAL PULL-OUT PENALTY.  Add an explicit extra parked delay E per bay stop
     (on top of SUMO's own, verified, gap-dependent re-entry cost) and find the E
     at which total person-hours cross zero, per cell.  That IS the bay trap
     boundary stated in a measurable engineering quantity.
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from expbase import run_arms, paired, mean, col, validity, save  # noqa: E402

SEEDS = list(range(1, 11))
PENALTIES = (0.0, 5.0, 10.0, 20.0, 40.0)
CELLS = [
    # (lanes, q_art, pax_rate, headway, spacing) -- picked to span the space where
    # the car benefit of a bay is smallest relative to its rider cost
    (3, 2100, 3000, 300, 200.0),
    (2, 1200, 2400, 300, 200.0),
    (2, 600, 2400, 300, 400.0),
    (2, 1800, 400, 180, 400.0),
    (1, 600, 1200, 180, 400.0),
]


def key(c):
    L, q, p, h, sp = c
    return f"L{L}_q{q}_p{p}_h{h}_sp{int(sp)}"


def main():
    arms = {}
    for c in CELLS:
        L, q, p, h, sp = c
        base = dict(lanes_art=L, q_art=float(q), pax_rate=float(p), headway=float(h),
                    stop_spacing=sp, q_cross=200.0, bus_capacity=150)
        arms[f"h1b_{key(c)}_inlane"] = Cfg(stop_type="inlane", **base)
        for E in PENALTIES:
            arms[f"h1b_{key(c)}_bayE{int(E)}"] = Cfg(stop_type="bay", bay_extra_penalty=E, **base)
    print(f"H1b: {len(arms)} arms x {len(SEEDS)} seeds = {len(arms)*len(SEEDS)} runs")
    res, errs = run_arms(arms, SEEDS, workers=9, tag="h1b")

    out = {"seeds": SEEDS, "penalties_s": PENALTIES, "cells": [], "n_failed": len(errs)}
    for c in CELLS:
        L, q, p, h, sp = c
        a = res[f"h1b_{key(c)}_inlane"]
        rec = {"lanes": L, "q_art": q, "q_per_lane": q / L, "pax_rate": p, "headway": h,
               "stop_spacing": sp, "n_stops": a[0]["n_stops"],
               "bus_occupancy": round(mean(col(a, "bus_mean_occupancy")), 2),
               "inlane_car_loss": round(mean(col(a, "car_mean_loss")), 2),
               "inlane_rider_total": round(mean(col(a, "rider_mean_total")), 2),
               "by_penalty": [], "validity_inlane": validity(a)}
        for E in PENALTIES:
            b = res[f"h1b_{key(c)}_bayE{int(E)}"]
            dcar = paired(col(a, "car_person_hours"), col(b, "car_person_hours"))
            drid = paired(col(a, "rider_person_hours"), col(b, "rider_person_hours"))
            dtot = paired(col(a, "total_person_hours"), col(b, "total_person_hours"))
            occ_used = a[0]["cfg"]["car_occupancy"]
            dcar_vehh = dcar["diff"] / occ_used
            occ_star = (-drid["diff"] / dcar_vehh) if dcar_vehh else float("nan")
            rec["by_penalty"].append({
                "extra_penalty_s": E,
                "bay_dwell": round(mean(col(b, "mean_dwell")), 2),
                "bay_rider_total": round(mean(col(b, "rider_mean_total")), 2),
                "bay_car_loss": round(mean(col(b, "car_mean_loss")), 2),
                "d_car_ph": dcar, "d_rider_ph": drid, "d_total_ph": dtot,
                "d_car_veh_hours": dcar_vehh,
                "critical_car_occupancy": occ_star,
                "bay_worse": dtot["diff"] > 0 and dtot["significant"],
                "validity_bay": validity(b)})
            print(f"{key(c):28s} E={E:5.1f} dCarPH={dcar['diff']:+9.3f} dRiderPH={drid['diff']:+9.3f} "
                  f"dTotPH={dtot['diff']:+9.3f}+-{dtot['half_width']:.3f} "
                  f"occ*={occ_star:7.3f} {'BAY WORSE' if dtot['diff'] > 0 and dtot['significant'] else ''}")
        # interpolate the crossover penalty
        xs = [r["extra_penalty_s"] for r in rec["by_penalty"]]
        ys = [r["d_total_ph"]["diff"] for r in rec["by_penalty"]]
        cross = None
        for i in range(len(xs) - 1):
            if ys[i] < 0 <= ys[i + 1]:
                cross = xs[i] + (0 - ys[i]) * (xs[i + 1] - xs[i]) / (ys[i + 1] - ys[i])
                break
        rec["crossover_extra_penalty_s"] = cross
        print(f"  -> crossover extra pull-out penalty: "
              f"{('%.1f s/stop' % cross) if cross is not None else 'NOT REACHED within %g s' % max(xs)}")
        out["cells"].append(rec)
    save(out, "h1b_bay_trap_probe.json")


if __name__ == "__main__":
    main()
