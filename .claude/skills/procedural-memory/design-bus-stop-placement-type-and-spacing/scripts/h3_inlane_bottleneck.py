"""H3 -- THE IN-LANE STOP AS A BOTTLENECK (one lane per direction).

Sweep bus frequency x mean dwell (via passenger load) at fixed car demand on a
one-lane-per-direction section and find where car delay starts growing
superlinearly and queues spill back to the upstream signal.

Instrumented with E2 detectors spanning each full arterial link (storage ratio),
teleport counters, and the curb-blockage-time normalisation used by
`model-curbside-delivery-and-lane-blocking-externality` so the two externalities
can be compared on the same axis (delay per vehicle-hour of lane blockage).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scenario import Cfg  # noqa: E402
from expbase import run_arms, paired, mean, sd, col, validity, save, ci  # noqa: E402

SEEDS = list(range(1, 11))
HEADWAYS = (900.0, 450.0, 300.0, 225.0, 150.0, 112.5, 90.0)   # 4..40 bus/h
PAX = (400.0, 1200.0, 2400.0)
Q_ART = 700.0


def main():
    arms = {}
    for h in HEADWAYS:
        for p in PAX:
            base = dict(lanes_art=1, q_art=Q_ART, q_cross=180.0, pax_rate=p,
                        headway=h, stop_placement="midblock", bus_capacity=150)
            arms[f"h3_h{int(h)}_p{int(p)}_inlane"] = Cfg(stop_type="inlane", **base)
            arms[f"h3_h{int(h)}_p{int(p)}_bay"] = Cfg(stop_type="bay", **base)
    # zero-bus control (no transit at all) -> the car-delay baseline the
    # externality is measured against
    arms["h3_nobus"] = Cfg(lanes_art=1, q_art=Q_ART, q_cross=180.0, pax_rate=1.0,
                           headway=100000.0, stop_placement="midblock",
                           stop_type="inlane", bus_capacity=150)
    print(f"H3: {len(arms)} arms x {len(SEEDS)} seeds")
    res, errs = run_arms(arms, SEEDS, workers=9, tag="h3", keep=("e2",))

    ctrl = res["h3_nobus"]
    base_loss = mean(col(ctrl, "car_mean_loss"))
    base_ph = mean(col(ctrl, "car_person_hours"))
    rows = []
    for h in HEADWAYS:
        for p in PAX:
            a = res[f"h3_h{int(h)}_p{int(p)}_inlane"]
            b = res[f"h3_h{int(h)}_p{int(p)}_bay"]
            if not a:
                continue
            blockage_h = mean(col(a, "total_dwell")) / 3600.0   # veh-hours of curb blockage
            d_ph = mean(col(a, "car_person_hours")) - base_ph
            row = {
                "headway_s": h, "bus_per_h": round(3600.0 / h, 2), "pax_rate": p,
                "mean_dwell_s": round(mean(col(a, "mean_dwell")), 2),
                "total_dwell_s": round(mean(col(a, "total_dwell")), 1),
                "bus_occupancy": round(mean(col(a, "bus_mean_occupancy")), 2),
                "inlane_car_loss": round(mean(col(a, "car_mean_loss")), 2),
                "inlane_car_loss_ci": round(ci(col(a, "car_mean_loss"))[1], 2),
                "bay_car_loss": round(mean(col(b, "car_mean_loss")), 2),
                "nobus_car_loss": round(base_loss, 2),
                "excess_car_loss_s": round(mean(col(a, "car_mean_loss")) - base_loss, 2),
                "excess_car_ph": round(d_ph, 3),
                "blockage_veh_h": round(blockage_h, 3),
                "externality_rate_ph_per_blockage_h": round(d_ph / blockage_h, 3) if blockage_h > 0 else None,
                "max_storage_ratio": round(mean(col(a, "max_storage_ratio")), 3),
                "mean_storage_ratio": round(mean(col(a, "max_mean_storage_ratio")), 3),
                "n_links_spillback": round(mean(col(a, "n_links_spillback")), 2),
                "teleports": round(mean(col(a, "teleports")), 2),
                "rider_total": round(mean(col(a, "rider_mean_total")), 1),
                "total_ph_inlane": round(mean(col(a, "total_person_hours")), 3),
                "total_ph_bay": round(mean(col(b, "total_person_hours")), 3),
                "d_total_ph_bay_minus_inlane": paired(col(a, "total_person_hours"),
                                                      col(b, "total_person_hours")),
                "validity": validity(a),
            }
            rows.append(row)
            print(f"hdwy={h:6.1f} ({row['bus_per_h']:5.2f}/h) pax={int(p):5d} dwell={row['mean_dwell_s']:6.2f} "
                  f"blockage={row['blockage_veh_h']:6.3f}vh | carLoss {row['inlane_car_loss']:7.2f} "
                  f"(+{row['excess_car_loss_s']:6.2f}) rate={row['externality_rate_ph_per_blockage_h']} "
                  f"stor={row['mean_storage_ratio']:.3f} spill={row['n_links_spillback']:.2f} "
                  f"tel={row['teleports']:.2f}")
    save({"seeds": SEEDS, "q_art": Q_ART,
          "nobus_control": {"car_mean_loss": round(base_loss, 3),
                            "car_person_hours": round(base_ph, 3),
                            "validity": validity(ctrl)},
          "cells": rows, "n_failed": len(errs)}, "h3_inlane_bottleneck.json")


if __name__ == "__main__":
    main()
