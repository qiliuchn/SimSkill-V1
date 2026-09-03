"""H2 -- NEAR-SIDE vs FAR-SIDE vs MID-BLOCK, with and without TSP.

Two claims tested separately:
 (a) TSP benefit depends on placement -- a near-side stop should largely CANCEL the
     priority green (the bus consumes the green it was just granted by dwelling at
     the stop line), while a far-side stop should preserve it.
 (b) Independently of TSP, a near-side stop sits on the signal APPROACH and should
     therefore worsen car queues more than a far-side stop.

TSP controller is the one from `implement-transit-signal-priority` (conditional
mode: bounded green extension + red truncation, per-cycle grant limit, offset
recovery), imported unchanged.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from expbase import run_arms, paired, mean, col, validity, save  # noqa: E402

SEEDS = list(range(1, 13))
PLACEMENTS = ("nearside", "farside", "midblock")


def main():
    base = dict(lanes_art=2, q_art=1400.0, q_cross=280.0, pax_rate=1200.0,
                headway=150.0, stop_type="inlane")
    arms = {}
    for p in PLACEMENTS:
        arms[f"h2_{p}_notsp"] = (Cfg(stop_placement=p, **base), "none")
        arms[f"h2_{p}_tsp"] = (Cfg(stop_placement=p, **base), "conditional")
    # no-stop control: isolates the TSP effect from the stop effect entirely
    arms["h2_nostop_notsp"] = (Cfg(stop_placement="farside", n_stops_override=1,
                                   pax_rate=1.0, **{k: v for k, v in base.items()
                                                    if k != "pax_rate"}), "none")
    print(f"H2: {len(arms)} arms x {len(SEEDS)} seeds")
    res, errs = run_arms(arms, SEEDS, workers=9, tag="h2")

    out = {"seeds": SEEDS, "placements": {}, "n_failed": len(errs)}
    for p in PLACEMENTS:
        a = res[f"h2_{p}_notsp"]
        b = res[f"h2_{p}_tsp"]
        rec = {
            "notsp": {k: round(mean(col(a, k)), 3) for k in
                      ("car_mean_loss", "car_art_mean_loss", "car_cross_mean_loss",
                       "bus_mean_dur", "bus_mean_loss", "rider_mean_total",
                       "rider_mean_inveh", "rider_mean_wait", "mean_dwell",
                       "total_person_hours", "car_person_hours", "rider_person_hours")},
            "tsp": {k: round(mean(col(b, k)), 3) for k in
                    ("car_mean_loss", "car_art_mean_loss", "car_cross_mean_loss",
                     "bus_mean_dur", "bus_mean_loss", "rider_mean_total",
                     "rider_mean_inveh", "rider_mean_wait", "mean_dwell",
                     "total_person_hours", "car_person_hours", "rider_person_hours")},
            "tsp_grants": round(mean([m["grants"]["total"] for m in b if m.get("grants")]), 1),
            "tsp_ext": round(mean([m["grants"]["ext"] for m in b if m.get("grants")]), 1),
            "tsp_trunc": round(mean([m["grants"]["trunc"] for m in b if m.get("grants")]), 1),
            "tsp_blocked": round(mean([m["grants"]["blocked"] for m in b if m.get("grants")]), 1),
            "d_bus_dur": paired(col(a, "bus_mean_dur"), col(b, "bus_mean_dur")),
            "d_bus_loss": paired(col(a, "bus_mean_loss"), col(b, "bus_mean_loss")),
            "d_rider_total": paired(col(a, "rider_mean_total"), col(b, "rider_mean_total")),
            "d_rider_inveh": paired(col(a, "rider_mean_inveh"), col(b, "rider_mean_inveh")),
            "d_car_art_loss": paired(col(a, "car_art_mean_loss"), col(b, "car_art_mean_loss")),
            "d_car_cross_loss": paired(col(a, "car_cross_mean_loss"), col(b, "car_cross_mean_loss")),
            "d_total_ph": paired(col(a, "total_person_hours"), col(b, "total_person_hours")),
            "validity_notsp": validity(a), "validity_tsp": validity(b),
        }
        out["placements"][p] = rec
        print(f"{p:9s} noTSP busDur={rec['notsp']['bus_mean_dur']:7.1f} artLoss={rec['notsp']['car_art_mean_loss']:6.2f} "
              f"| TSP busDur={rec['tsp']['bus_mean_dur']:7.1f} grants={rec['tsp_grants']:5.1f} "
              f"| dBusDur={rec['d_bus_dur']['diff']:+7.2f}+-{rec['d_bus_dur']['half_width']:.2f} "
              f"({rec['d_bus_dur']['pct']:+5.1f}%) {'SIG' if rec['d_bus_dur']['significant'] else ''}")

    # placement effect WITHOUT tsp (claim b), and vs the no-stop control
    ns = res["h2_nostop_notsp"]
    out["nostop_control"] = {k: round(mean(col(ns, k)), 3) for k in
                             ("car_mean_loss", "car_art_mean_loss", "bus_mean_dur")}
    out["placement_effect_notsp"] = {}
    ref = res["h2_farside_notsp"]
    for p in PLACEMENTS:
        a = res[f"h2_{p}_notsp"]
        out["placement_effect_notsp"][p] = {
            "vs_farside_car_art_loss": paired(col(ref, "car_art_mean_loss"), col(a, "car_art_mean_loss")),
            "vs_farside_total_ph": paired(col(ref, "total_person_hours"), col(a, "total_person_hours")),
            "vs_farside_rider_total": paired(col(ref, "rider_mean_total"), col(a, "rider_mean_total")),
            "vs_nostop_car_art_loss": paired(col(ns, "car_art_mean_loss"), col(a, "car_art_mean_loss")),
        }
        e = out["placement_effect_notsp"][p]
        print(f"  {p:9s} vs farside: artCarLoss {e['vs_farside_car_art_loss']['diff']:+6.2f}"
              f"+-{e['vs_farside_car_art_loss']['half_width']:.2f} "
              f"riderTotal {e['vs_farside_rider_total']['diff']:+7.2f}"
              f"+-{e['vs_farside_rider_total']['half_width']:.2f}")
    save(out, "h2_nearside_farside_tsp.json")


if __name__ == "__main__":
    main()
