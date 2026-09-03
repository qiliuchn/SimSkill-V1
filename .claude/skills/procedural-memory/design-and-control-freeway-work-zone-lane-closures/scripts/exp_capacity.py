"""H1 / H5 / H6: measured work-zone capacity vs the HCM reference.

All cells are driven at OVERLOAD (peak 8400 veh/h, well above 3-lane capacity) so the
activity-area E1 station is measuring a genuine QUEUE-DISCHARGE rate, not demand.

H1  per-open-lane work-zone capacity vs the same segment's unobstructed per-lane
    capacity, and vs HCM's ~1600 pc/h/ln; does the deficit grow with lanes closed?
H5  does taper length / advance-warning distance change measured capacity independently
    of lane count?
H6  what does the posted work-zone speed reduction cost in veh/h per 10 km/h?

Unobstructed reference cells use lanes_closed=0 with the mainline speed restored
(wz_speed_kmh=120), so fD/fE/fF are geometrically and legally identical to the rest of
the freeway -- the SAME SEGMENT, unobstructed, as the hypothesis requires.
"""
import json
import os

import wz_common as W
import batch

OUTD = os.path.join(W.OUT, "capacity")
os.makedirs(OUTD, exist_ok=True)
OVERLOAD = 8400
SEEDS = (1, 2, 3)
# a flat overload profile: the point is queue discharge, not a realistic peak
FLAT = [(0, 3600, 1.0)]


def cells():
    cs = []
    # ---- H1: lanes closed 0 (unobstructed, free speed), 0 (WZ speed only), 1, 2
    for lc, vwz, name in ((0, 120, "unobstructed"), (0, 80, "speedonly"),
                          (1, 80, "lc1"), (2, 80, "lc2")):
        for sd in SEEDS:
            cs.append(dict(label=f"H1_{name}_s{sd}", outroot=OUTD, arm="donothing",
                           rep="geom", merge="priority", peak=OVERLOAD, seed=sd,
                           demand_seed=200 + sd, profile=FLAT, end=4200,
                           params=dict(lanes_closed=lc, wz_speed_kmh=vwz),
                           tagname=f"H1_{name}"))
    # ---- H6: posted work-zone speed sweep at 1 lane closed
    for vwz in (50, 65, 80, 95, 110):
        for sd in SEEDS:
            cs.append(dict(label=f"H6_v{vwz}_s{sd}", outroot=OUTD, arm="donothing",
                           rep="geom", merge="priority", peak=OVERLOAD, seed=sd,
                           demand_seed=200 + sd, profile=FLAT, end=4200,
                           params=dict(lanes_closed=1, wz_speed_kmh=vwz),
                           tagname=f"H6_v{vwz}"))
    # ---- H5: taper length x advance-warning distance, at 1 and 2 lanes closed
    for lc in (1, 2):
        for tp in (80, 200, 500):
            for aw in (500, 1500, 3000):
                if lc == 2 and aw != 1500:
                    continue      # reduced factorial: full grid only at lc=1
                for sd in SEEDS:
                    cs.append(dict(label=f"H5_lc{lc}_tp{tp}_aw{aw}_s{sd}", outroot=OUTD,
                                   arm="donothing", rep="geom", merge="priority",
                                   peak=OVERLOAD, seed=sd, demand_seed=200 + sd,
                                   profile=FLAT, end=4200,
                                   params=dict(lanes_closed=lc, taper_len=tp,
                                               aw_len=aw, wz_speed_kmh=80),
                                   tagname=f"H5_lc{lc}_tp{tp}_aw{aw}"))
    return cs


if __name__ == "__main__":
    cs = cells()
    print(f"{len(cs)} capacity cells")
    batch.run_cells(cs, os.path.join(OUTD, "capacity_results.json"))
